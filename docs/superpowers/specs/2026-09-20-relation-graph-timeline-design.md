# 关系图时间维度 设计文档

- 日期：2026-09-20
- 状态：已评审
- 关联：`docs/superpowers/specs/2026-07-27-novel-knowledge-graph-design.md`（§5.3 图数据模型、§7.3.3 人物关系页）
- 前置：`docs/superpowers/specs/2026-08-02-arc-parallel-extraction-design.md`（arc 并行提取与跨 arc 合并）

---

## 1. 目标与非目标

### 1.1 产品意图

现有人物关系图是**静态全量**的：一本书所有人物、所有关系一次性铺开，看不出结构随情节的演化。本功能给图谱加上时间维度，服务**上帝视角的结构分析**——读完（或不打算读）之后，用图谱看清这本书的人物结构是怎么长出来的：

- 谁是开篇就在的，谁是中段才登场并迅速变成核心的
- 哪一对关系发生过反转（朋友 → 敌人）、在第几章反转
- 主角团是从第几章开始成型的

明确**不是**「防剧透陪读模式」（按阅读进度渐进解锁）。那是另一种产品形态，两者的默认状态、交互重心都相反，不在本期。

### 1.2 v1 范围

纳入三个视图：

1. **时间滑块关系网**——拖动到某个刻度，图上只显示截至该点已出现的人物与关系。这是另外两项的基础。
2. **关系演变高亮**——特别标记发生过类别变化的关系边，点击可看「第 3 章：朋友 → 第 40 章：敌人」及两段证据原文。这是意图 1.1 的核心价值。
3. **人物出场曲线**——单个人物按章节的提及次数折线。

### 1.3 明确不做（v2 再议）

- **播放动画**（自动推进滑块）——成本主要在对抗 vis-network 动态增删节点时的布局抖动，属纯打磨项，不应与数据结构变更同期上线。
- **登场/退场标记**——信息与出场曲线重叠，等曲线上线后再评估是否还需要。
- **vis-network 交互测试与 `GraphTab` 渲染测试**——项目「零前端组件测试」是独立的技术债，不并入本期。

---

## 2. 关键前提：演变数据已经存在，只是没被标注

`EntityRegistry.relationships` 的键是 `(source, target, category)`（`merge.py:80,159`），**类别是键的一部分**。因此「A 与 B 在第 3 章是朋友、第 40 章是敌人」在今天的数据里**已经是两条独立的 `RelationRecord`**，`graph.py:110-146` 也已经把它们输出为同一对节点之间的**两条平行边**。

所以本设计不需要发明「每次出现各带一个类别」的新结构，只需要：

1. 给记录补上**按章节的出现分布**（现在只有总 `count`）；
2. 增加一个**裁决环节**，判断同一对人物的多条平行边里，哪些是真实演变、哪些是提取噪声。

同时纠正一个易误用的字段：`rec.chapter_id` **不是首次出现章节**。`add_relationship` 在创建时写入，之后**每遇到更长的 evidence 就覆盖一次**（`merge.py:172-174`），语义是「最长证据所在章节」，不能当时间轴锚点。该字段保持不动，因为 `locate.py:118` 仍依赖它定位证据段落。

---

## 3. 数据层：`merge.py`

全部为新增字段，不改动任何既有语义。

### 3.1 `RelationRecord.chapters: dict[str, int]`

章节 id → 该关系在该章节出现的次数，在 `add_relationship` 中累加。

- `count` 不变，等于 `sum(chapters.values())`，仍作为边的 `weight`。
- 首次出现章节 = `chapters` 中章节序最小的键。

### 3.2 `CharacterRecord.mentions_by_chapter: dict[str, int]`

章节 id → 该人物在该章节被提及次数。

`add_character`（`merge.py:104-116`）目前没有章节参数，需要从 `add_extraction`（`merge.py:176-192`，已持有 `chapter_id`）把章节透传下去。`mention_count` 不变。

**为什么放在节点上而不是从 `events.json` 推导**：`events.json` 只记录事件的 participants，一个「被提及但未参与事件」的人物会在推导出的曲线里凭空消失。既然为了边已经要改 `merge.py`，顺带记录按章提及次数是边际成本。

### 3.3 新模块 `app/pipeline/evolve.py`

消费合并后的 registry，产出 `transitions`。两级裁决：

**第一级 · 确定性预过滤**

- 按规范化人物对分组，复用 `merge.py:157-158` 的 `src > tgt` 交换规则，保证对齐。
- 只有一个类别的人物对直接跳过。
- 多类别人物对中，每个类别状态必须满足 `count >= EVOLVE_STABILITY_MIN`（默认 2）**或**跨 ≥2 个章节；不满足的判为提取噪声丢弃。
- 过滤后仍有 ≥2 个状态、且章节区间次序清晰的人物对，才成为候选。

**第二级 · 强模型确认**

候选分批送入 `structured_output(tier="strong")`，询问该关系是否真的发生了转变、在第几章、从什么变成什么。复用 `merge.py:285-318` 已有的 L2 批量确认模式，不引入新机制。

**`其他` 类别完全排除在裁决之外**：`朋友 → 其他` 没有叙事含义，且 `其他` 是兜底类别、最容易被 LLM 误填。

### 3.4 编排位置

`evolve.py` 在 `merge_arcs` 之后、`build_extraction_json` 之前执行，**留在既有的 `building` 阶段内**。不新增 Phase 值，因此后端 `Phase` 枚举与 `frontend/src/constants.js` 中镜像的 `PHASE_*` 都无需改动。进度通过 `on_progress` 的消息文案体现（「正在判定关系演变…」）。

---

## 4. 产出层：`graph.json`

**不在后端折叠同对多类别的平行边。** 全部改动为纯新增。

### 4.1 新增字段

人物节点：

- `first_chapter`：如 `"ch0003"`
- `mentions_by_chapter`：`{chapter_id: count}`

地点节点：

- `first_chapter`（地点不做提及曲线）

边：

- `chapters`：`{chapter_id: count}`，**该类别**在各章节的出现次数
- `first_chapter`

新增顶层字段：

- `chapters`：`[{id, title, order}]`——时间轴刻度与分桶依据
- `transitions`：`[{pair: [nodeIdA, nodeIdB], steps: [{chapter_id, category, evidence}, …], confirmed: bool}]`——`evolve.py` 的裁决结果。`pair` 用 §3.3 的规范化顺序；`steps` 按章节序升序排列

**章节序是唯一的比较依据。** 所有「早于/晚于」判断都通过顶层 `chapters[].order` 查表比较，**不做 chapter_id 字符串比较**——`ch0003` 这类 id 的字典序只是碰巧和章节序一致，不是契约。

### 4.2 为什么不折叠

- 折叠会改变既有边语义。`graph.json` 有三个消费方（`GraphTab`、`RawTextTab` 的实体链接化、`CharactersGraphPreviewSection`），还要经过 graphify 的 `build_from_json` / `to_html`。纯新增意味着三者与 `graph.html` 都不用改。
- 前端反正要对演变边做特殊处理，从 `transitions` 索引比逼后端在折叠时任选一个「当前类别」更准确。

### 4.3 为什么带上顶层 `chapters`

滑块需要章节顺序与标题来画刻度、做分桶。若不带，前端得额外调 `/timeline`，违背方案一「单一数据源、拖动零延迟」的前提。带上之后 `graph.json` 自包含，**降级判定也简化为一次字段检查**（无顶层 `chapters` ⇒ 旧版作品）。

### 4.4 体积

约 500 条边 × 约 3 个章节键 + 约 200 个节点 × 稀疏章节分布 ⇒ `graph.json` 从约 200KB 增长到约 400–600KB。demo 量级可接受。千章级网文才会成为问题，届时正确的解法是服务端裁剪（`GET /works/{id}/graph?until_chapter=N`），而不是拆分文件。

---

## 5. 前端

三个视图全部落在 `GraphTab.jsx`（全屏 `GraphStack` 页）。Dashboard 的 `CharactersGraphPreviewSection` 不动——预览区只有缩略 SVG，放不下滑块。

### 5.1 章节滑块

新增 `components/graph/ChapterSlider.jsx`，置于页面顶部。

分桶规则：章节数 ≤20 ⇒ 一章一格；否则均分 16 格，每格标注其首章标题。分桶是 `lib/graphTimeline.js` 里的纯函数。

每一格对应一个 **cutoff = 该格最后一章的 `order`**。滑块停在第 k 格，即「看到第 k 格末尾为止」。

默认位置 = 最后一格（全书），与 1.1 的上帝视角意图一致。

### 5.2 关键技术决策：用 vis-network 的 `hidden`，不重建图

拖动滑块时对 DataSet 批量 `update({id, hidden})`，**不调 `setData`**。因为 `setData` 会重跑布局、节点位置跳动，拖动手感尽失。`hidden` 保持坐标稳定，开销为 O(变化量)，也为 v2 的播放动画铺路。

过滤规则：节点/边的 `first_chapter` 所对应的 `order` **大于** cutoff ⇒ `hidden`。

### 5.3 关系演变高亮

加载时从 `transitions` 构建 `Map<"idA|idB", transition>`（放在 `lib/graphTimeline.js`）。

命中的边渲染为虚线 + 端点角标。点击后右栏显示步骤条「第 3 章 朋友 →（第 40 章）敌人」，每步带证据与「查看原文」跳转，复用既有的 `source_location` 跳转逻辑。晚于 `cutoff` 的步骤置灰。

### 5.4 人物出场曲线

新增 `components/graph/MentionSparkline.jsx`，无依赖内联 SVG（与既有 `MiniGraphPreview.jsx` 同路数）。放进右栏既有人物卡片、紧贴「提及 N 次」下方，不新增页面区域。

### 5.5 降级

`graph.json` 无顶层 `chapters` ⇒ 完全不渲染滑块与曲线，显示提示条「该作品分析于旧版本，重新分析可解锁时间轴」+ 按钮，调 `POST /works/{id}/reanalyze`。

### 5.6 改动文件

```
新增  frontend/src/lib/graphTimeline.js                纯函数：分桶 / 过滤 / transitions 索引
新增  frontend/src/components/graph/ChapterSlider.jsx
新增  frontend/src/components/graph/MentionSparkline.jsx
改    frontend/src/components/tabs/GraphTab.jsx         接入滑块、hidden 过滤、演变边、右栏 sparkline
改    frontend/src/constants.js                         演变边样式常量
改    frontend/src/api.js                               reanalyze
改    frontend/src/pages/ReaderPage.jsx                 409 跳转处理页
改    frontend/src/pages/ProcessingPage.jsx             失败卡片改为「重新分析」按钮
```

---

## 6. API：`POST /works/{id}/reanalyze`

### 6.1 契约

| 情形 | 响应 |
| --- | --- |
| 成功 | `202 {work_id, status:"queued", reused:false}` |
| work_id 非法 | `400`（既有 `InvalidWorkIdError` handler） |
| 作品不存在 | `404` |
| 正在处理中（phase ∉ {done, failed}） | `409` |
| `raw.*` 文件缺失 | `409` |

复用 `meta.json`（`filename` / `title` / `granularity`）与磁盘上的 `raw.*`，无需重新上传。实现复用 `_init_status` 与 `_launch_pipeline`（`routes.py:31-34,75`），并与 `POST /works` 共用同一个 `threading.Semaphore`（`routes.py:28`），并发上限不变。

### 6.2 重跑状态机

- `status.json` 立即回到 `queued`；前端成功后直接导航到 `/works/{id}/processing`，与上传流程完全一致，不需要新页面。
- **不预删旧产物**，由管道逐阶段覆盖（`chapters.json` → `events.json` → `graph.json` → `summary.json`）。理由：预删意味着中途失败会彻底毁掉这个作品；覆盖则保证 `phase=failed` 的重跑之后旧结果仍在。
- 代价：重跑窗口内 `graph.json` 可能被读到半新半旧。缓解手段——`GET /works/{id}` 在 `phase != done` 时**已经**返回 409（`routes.py:116-124`），所以只需让 **`ReaderPage` 在收到 409 时跳转到处理页**。这同时补上一个既有漏洞：刷新未完成作品的阅读页目前只会报错。

### 6.3 缓存处理

| 文件 | 处置 | 理由 |
| --- | --- | --- |
| `chapter_summaries.json` | 保留 | 按 chapter_id 索引，解析同一份原文是确定性的，省 LLM 成本 |
| `beat_summaries.json` | 删除 | 按 beat 下标索引，`spine.json` 会重新生成、下标含义改变，残留项会错位 |
| `ask_history.json` | 保留 | 用户可见历史，不是纯缓存 |

### 6.4 顺带闭环

`ProcessingPage.jsx:89-94` 的失败卡片目前只是一个回首页的 `<Link>`（必须重新上传）。本端点使其成为真正的「重新分析」按钮。5.5 的旧版本提示条复用同一端点。

---

## 7. 错误处理

遵循项目既有的降级约定（`merge.py:416-418`、`summarize.py:335-367`）。

| 情形 | 行为 |
| --- | --- |
| `evolve` 强模型确认失败/超时 | 绝不抛出；`transitions = []`，平行边原样保留；向 `status.warnings` 追加一条；图谱其余部分不受影响 |
| `evolve` 整模块异常 | 同上降级 |
| fake 模式（`NOVEL_KG_USE_FAKE_LLM=1`） | 跳过强模型，直接采用预过滤结果并标 `confirmed: false`，使离线测试仍能覆盖预过滤 |
| `confirmed: false` | 前端仍高亮该边，但角标显示「疑似演变」而非「关系演变」，右栏注明未确认 |
| 旧版作品（无顶层 `chapters`） | 不渲染滑块与曲线 + 重新分析提示条（见 5.5） |
| reanalyze 冲突 | 409，前端显示「该作品正在处理中」 |

---

## 8. 配置

`config.py` 新增（环境变量前缀 `NOVEL_KG_`）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `EVOLVE_STABILITY_MIN` | `2` | 类别状态成立所需的最小出现次数 |
| `EVOLVE_BATCH_SIZE` | `10` | 强模型确认的批大小 |
| `EVOLVE_ENABLED` | `true` | kill switch。置 `false` 时完全跳过 `evolve.py`，`transitions` 输出为空数组；§4.1 的其余新字段（节点/边的 `chapters`、`first_chapter`、顶层 `chapters`）照常产出，因此滑块与出场曲线仍可用，只是没有演变高亮 |

同时修正 `.env.example` 的文档漂移：当前只记录了约 25 个环境变量中的 11 个，本期补齐。

---

## 9. 测试策略

后端全部离线运行（`NOVEL_KG_USE_FAKE_LLM=1`）：

**新增 `backend/tests/test_evolve.py`**

- 预过滤丢弃单次出现的噪声
- 预过滤保留 ≥2 个稳定状态
- `其他` 类别被排除
- 人物对规范化与 `merge.py:157-158` 一致
- LLM 失败返回空且不抛出
- fake 路径结果确定

**既有测试补充**

| 文件 | 补充内容 |
| --- | --- |
| `test_merge.py` | `chapters` 累加、`mentions_by_chapter` 透传、跨 arc 合并保留两者 |
| `test_graph.py` | 新节点/边字段、顶层 `chapters` 与 `transitions`、地点节点只带 `first_chapter` |
| `test_routes.py` | reanalyze 的 202 / 400 / 404 / 409×2；`beat_summaries.json` 被删而 `chapter_summaries.json` 保留 |
| `test_pipeline_integration.py` | 端到端断言新字段存在 |

**前端**

`frontend/src/lib/graphTimeline.test.js` 纯函数测试：分桶边界、cutoff 过滤、transitions 索引、空数据。沿用既有 `lib/*.test.js` 先例。

**不在本期**：vis-network 交互测试、`GraphTab` 渲染测试（见 1.3）。

---

## 10. 迁移

已有作品的 `graph.json` 没有新字段，属正常情况：

1. 前端按 5.5 降级，展示重新分析入口；
2. 用户点击后走 §6 的 reanalyze 流程解锁时间轴。

不做自动批量迁移——重跑要花 LLM 成本，必须由用户显式触发。
