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

- `count` 不变，仍作为边的 `weight`。
- 首次出现章节 = `chapters` 中章节序最小的键。

> **勘误（实现后修正）**：本节初稿断言 `count == sum(chapters.values())`，**这是错的**，代码是对的。
> `merge_arcs` 的跨弧再摄入（`merge.py:448-458`）对每条弧内记录调用一次公开的
> `add_relationship`，后者只把 `count` **+1**（`merge.py:208`），而真实的按章分布由
> `_merge_counts(merged_rel.chapters, rel.chapters)`（`merge.py:458`）整体搬运。
> 所以合并后 `count` 是「参与合并的弧内记录条数」，`chapters` 才是真实分布，两者量级可以相差很多。
>
> 这是**有意的分歧**，不要为了对齐文档去改代码：
> - `merge.py:80-82` 的字段注释、`graph.py:180-181` 的 `weight` 注释都已就地记录该分歧
>   （注：`graph.py:181` 把注释位置写成 `merge.py:81-83`，实际是 `merge.py:80-82`，差一行）；
> - `evolve.py:82` 的稳定性阈值正确地用 `sum(rec.chapters[c] for c in known)` 而**不是** `rec.count`。
>
> 因此本节及 §3.3 中所有「`count >= 阈值`」的表述，实现上一律指**按章分布之和**。

### 3.2 `CharacterRecord.mentions_by_chapter: dict[str, int]`

章节 id → 该人物在该章节被提及次数。

`add_character`（`merge.py:104-116`）目前没有章节参数，需要从 `add_extraction`（`merge.py:176-192`，已持有 `chapter_id`）把章节透传下去。`mention_count` 不变。

**为什么放在节点上而不是从 `events.json` 推导**：`events.json` 只记录事件的 participants，一个「被提及但未参与事件」的人物会在推导出的曲线里凭空消失。既然为了边已经要改 `merge.py`，顺带记录按章提及次数是边际成本。

### 3.3 新模块 `app/pipeline/evolve.py`

消费合并后的 registry，产出 `transitions`。两级裁决：

**第一级 · 确定性预过滤**

- 按人物对分组（`evolve.py:69`）。
- 只有一个类别的人物对直接跳过。
- 多类别人物对中，每个类别状态必须满足 `count >= EVOLVE_STABILITY_MIN`（默认 2）**或**跨 ≥2 个章节；不满足的判为提取噪声丢弃。
- 过滤后仍有 ≥2 个状态、且章节区间次序清晰的人物对，才成为候选。

> **勘误 + 已知限制（实现后修正）**：本节初稿写的是「复用 `merge.py:157-158` 的 `src > tgt`
> 交换规则，保证对齐」。**两句都不成立**，而且第二句掩盖了一个真实的功能缺口。
>
> 1. 行号错：该交换规则实际在 `merge.py:197`。
> 2. 行为错：`merge.py:197` 的交换是**有条件**的——
>    `if cat_enum not in DIRECTED_CATEGORIES and src > tgt`，即**只对无向类别**
>    归一化成 `src <= tgt`；`师徒`/`主仆`（`models.py:37` 的 `DIRECTED_CATEGORIES`）
>    保留 LLM 给出的原始方向。而 `evolve.py:69` 是按 `(rec.source, rec.target)`
>    **原始元组**分组的，没有再做任何排序。
>
> **后果**：对于一对人物 `甲 > 乙`（按 Python 字符串序），`朋友` 记录落进分组 `(乙,甲)`，
> 而 `师徒` 记录落进 `(甲,乙)` 还是 `(乙,甲)` 取决于 LLM 当时朝哪个方向写。两者落进
> 不同分组时，该人物对在每个分组里都只剩 1 条记录，`evolve.py:74` 的 `len(recs) < 2`
> 直接跳过——**一次 `师徒 → 敌人` 的演变就这样被漏掉了**。
>
> 失败方向是单向的：只会**漏报**高亮，绝不会误报一个不存在的演变。所以这是一个可接受
> 的已知限制而不是缺陷（详见 §11 后续工作）。
>
> **为什么没有直接改成 `tuple(sorted(...))`**：§4.1 规定 `transitions[].pair` 用本节的
> 规范化顺序，而前端是用边上存的 `(source, target)` 建 `pairKey` 索引去匹配它的。
> 无条件排序会让 `pair` 不再等于任何一条边的实际端点顺序，索引直接失配，整个演变高亮
> 会从「偶尔漏报」变成「全部不显示」。要修必须同时改 `evolve.py` 的分组、§4.1 的
> `pair` 契约和前端索引三处，属于设计级变更。

**第二级 · 强模型确认**

候选分批送入 `structured_output(tier="strong")`，询问该关系是否真的发生了转变、在第几章、从什么变成什么。复用 `merge.py` 已有的 L2 批量确认模式（`_llm_confirm`，实现后位于 `merge.py:337-361`；初稿写的 `merge.py:285-318` 是设计时的估算行号），不引入新机制。

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
- 人物对分组顺序（注意：见 §3.3 的勘误，`evolve.py:69` 与 `merge.py:197` 的有条件交换**并不**对齐）
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

---

## 11. 后续工作与已知限制

本节记录 `feat/relation-graph-timeline` 分支合并时**已知但有意未修**的问题。全分支评审结论是
「批准合并、无阻塞代码改动」，下列各项都不构成合并阻塞，但都是真实的缺口，按优先级降序排列。
行号以分支末尾提交 `504e8fb` 为准，可能随后续改动漂移。

### 11.1 演变高亮与箭头两条路径在真实数据上零覆盖（最高优先级）

**问题**：`data/works/t17verify0001/graph.json`（本分支的验证作品）里 `transitions` 是 `[]`，
且 207 条边**全部**是 `directed: false` / `category: "朋友"`。于是：

- **关系演变高亮**（§5.3，`§1.2` 称其为「意图 1.1 的核心价值」）从未端到端跑通过一次。
  committed 覆盖只有各层的单元测试，加上 `test_pipeline_integration.py` 里**一条手工注入**的
  transition。
- **有向边箭头**（`GraphTab.jsx:239` 的 `arrows: e.directed ? "to" : undefined`）同样从未在真实
  产物上被执行过——它是 §5 的必须保留项之一。

**单一根因**：离线 fake 抽取器只产出一个类别。`extract.py:123` 是 `category=RelationCategory.FRIEND`
的唯一出现处；`merge` 以 `(src, tgt, category)` 为键，所以任何一对人物都不可能持有 2 条记录，
`prefilter_candidates` 必定在 `evolve.py:74` 的 `len(recs) < 2` 处退出。同理没有 `师徒`/`主仆`，
就没有 `directed: true` 的边。

**修法与代价**：让 fake 抽取器给某一对人物产出第二个类别（例如在最后一章把首对关系改成
`ENEMY`，`extract.py:118-128`）。这是 ~3 行改动，但它扰动**全体离线测试共用的 fixture**，
需要重新基线所有统计 relationship / edge 数量的断言。所以本分支未做。

**规模**：半天。改动小，重新基线是主要成本。

### 11.2 `ensure_id` 同名碰撞销毁 39% 的人物节点

**问题**（先于本分支存在）：`graph.py:88-102` 的 `ensure_id` 以**人物/地点名字**为键
（`name_to_id`）。人物节点先 append（`graph.py:105-122`），地点节点后 append
（`graph.py:124-140`）且复用同一个 id，下游按 id 去重时**后写的地点节点覆盖前面的人物节点**。

**实测**（`t17verify0001`）：139 个节点 = 63 个存活人物 + 76 个地点，其中 **40 个地点节点同时带
`mentions_by_chapter` 和 `role`**（`role` 只由 `graph.py:116` 的人物分支产出，`mentions_by_chapter`
由 `graph.py:119` 产出，地点分支 `graph.py:137` 明确不写），即碰撞是**实测到的而非推断的**。
换算：原本注册了 103 个人物，40 个被覆写成地点节点 = **39%**。其中 15 个 `mention_count > 1`。

**连带影响**：`node_type` 翻成 `place`、`role`/`description` 被替换，于是该节点被
`_fallback_god_nodes`（`graph.py:276` 的 `node_type == "place"` 跳过）和
`_heuristic_labels`（`graph.py:304` 同样跳过）排除——**god 节点排名与社区命名也一起受影响**。

**本分支让它变得可见**（这是本分支唯一的新增部分）：新加的两个字段在这些节点上**自相矛盾**。
`n80`/「了一」的 `first_chapter` 是 `ch0002`（来自**地点**的 histogram），而
`mentions_by_chapter` 是 `{ch0010: 1}`（来自**人物**的 histogram）——滑块会在第 2 章就把它放出来，
而它唯一的曲线柱子在第 10 章。同时 §4.1「地点不做提及曲线」对这 40 个节点**被违反**：它们会
渲染成「地点 · 提及 N 次」并带一条曲线。

**如实记录缓解因素**：39% 被离线 fixture 放大了——碰撞的 label 是 fake 抽取器的 n-gram 垃圾
（「了一」/「那个」/「梗本」/「没有」）。真实 LLM 抽取碰撞率低得多，但**不为零**
（例如「桃花岛」既是地点又可作人物别号）。

**为什么不在本分支修**：修 `ensure_id`（例如把键改成 `(node_type, name)`）会让**每个产物里的
每个节点 id 全部重新编号**，从而作废 `data/works/` 下已有的 15 个作品。必须配迁移方案。

**规模**：1-2 天，含迁移与重新基线。

### 11.3 reanalyze 的 TOCTOU（检查与写入不原子）

**问题**：`routes.py:123-124` 的阶段守卫与 `routes.py:139` 的 `_init_status(...)` 之间
**不是原子的**。两个并发 POST 可以都通过守卫、都 dispatch 一次管道到**同一个 work 目录**
（`MAX_CONCURRENT_JOBS = 3`，`app/config.py:139`，所以两条管道确实能同时跑）。

**今天为什么安全**：纯属偶然——`reanalyze_work` 是 `async def` 且**函数体内一个 `await` 都没有**
（已核实：`routes.py:101-143` 的函数体内 `await` 出现 0 次），所以这一段在事件循环上是原子的。
加入任何 `await`（比如一个完全合理的 `asyncio.to_thread` 包住那几次磁盘读），或者用多 worker
启 uvicorn，都会立刻打开双重 dispatch。**偶然安全且无文档**是最糟的组合——所以本分支在
`routes.py` 的阶段守卫处补了一段注释就地记录该不变量（纯注释，无行为改动）。

**相关的前端路径**：`ProcessingPage` 在 A→B→A 导航时会重置 `retryPending`
（`ProcessingPage.jsx:61-65` 的 id-keyed effect），于是 A 的第二个 POST 可以在第一个还在飞的时候
发出；两者都通过身份守卫、都 bump nonce，后端用 409 回答第二个——降级成一条**令人困惑的提示**
而非数据损坏，**除非**正好撞上本节的 TOCTOU。

**修法**：加锁（`asyncio.Lock` per work_id）或改成原子的 compare-and-set 写入。本分支只加注释，
不加锁：加锁是行为改动，且需要决定锁的粒度与多进程下的语义（进程内锁对多 worker 无效）。

**规模**：半天（进程内锁）；多 worker 正确需要文件锁或外部协调，1-2 天。

### 11.4 重新分析一个已 `done` 的作品会返回过期的 200

**问题**：`store.get_package`（`store.py:72-76`）**只**以 `summary.json` 是否存在为判据。
reanalyze 有意不预删任何产物（`routes.py:104-108` 的 docstring 说明了理由：预删后中途失败
就把作品毁了），而 `clear_beat_cache` 只删 `beat_summaries.json`。于是
`GET /works/{id}` 在**整个重跑期间**都返回 200 + **上一次的过期读者数据**，直到
`orchestrator.py:232` 覆写 `summary.json` 时才静默变正确。

**连带影响**：`ReaderPage` 的 409 重定向（`ReaderPage.jsx:44-47`）因此**只覆盖在 summarizing
之前就失败的作品**。好消息是那是主流路径——重新分析按钮长在失败卡片上。

**修法**：让 `get_work` 在 package 存在时也查 `status.phase`（phase 不是 `done` 就返回 409）。
本分支未做，因为它落在 Task 18 允许修改的两个文件之外。

**规模**：1-2 小时，含一条路由测试。

### 11.5 测试套件的环境变量脆弱性，以及一个真金白银的 AWS 泄漏

**已复现**：`NOVEL_KG_EVOLVE_ENABLED=0 NOVEL_KG_EVOLVE_STABILITY_MIN=3` 下跑全量套件得到
**14 failed / 254 passed**（默认环境下是 268 passed）。其中恰好 **1 个是正确行为**
（`test_config_arc.py::test_evolve_defaults`，它的存在目的就是断言默认值）；另外
**13 个是 `test_evolve.py` 的真实脆弱性**：该文件 29 个测试、8 处 `monkeypatch.setattr`
（7 处针对 `evolve.config`，1 处针对 `llm.structured_output`），而这 7 处只覆盖
`EVOLVE_BATCH_SIZE`、`USE_FAKE_LLM`、以及把 `EVOLVE_ENABLED` 设为 `False`（测 kill switch）——
**没有任何一处把 `EVOLVE_ENABLED` 钉成 `True`，也没有一处钉 `EVOLVE_STABILITY_MIN`**。
所以 8 个 `detect_transitions_*` / `_llm_confirm` 测试在 `EVOLVE_ENABLED=0` 下被短路，
另外 5 个排序/预过滤测试在阈值抬高后因候选被饿死而崩。

**更糟的那一半**：`tests/test_extract_arcs.py` **没有 `USE_FAKE_LLM` 钉子**，而套件唯一的保护是
`conftest.py:9` 的 `os.environ.setdefault("NOVEL_KG_USE_FAKE_LLM", "1")`——`setdefault` 被任何
环境已有值击穿。于是 `NOVEL_KG_USE_FAKE_LLM=0` 会让该文件**发出真实的 Bedrock 调用而测试依然
全绿**（实测约 150 秒、600 次 socket 尝试）：静默烧钱，**没有任何红色信号**。这比会大声失败的
那 13 个更危险。

**修法**：一个 autouse fixture 强制 `config.USE_FAKE_LLM = True`（外加可选的 socket 阻断）
即可让整个套件抗环境污染，一次性作废上面整整一类问题。

**顺带**：`create_work` 的 `granularity` 归一化（`routes.py:47-48`）同样无测试钉住。它比
reanalyze 那一处（`routes.py:136-137`）**危险**：输入是客户端可控的 Form 字段，所以
`granularity=weird` 的任何请求都能触达 `_init_status` → `WorkStatus` 的 `Literal` 校验错误 → 500，
而 `write_meta` + `save_upload` 都在 `_init_status` **之前**执行，于是 500 会在磁盘上留下一个
半成品作品（有 `meta.json` + `raw.*`、没有 `status.json`）。

**规模**：半天，纯测试改动。

### 11.6 离线解析器切分不足（新暴露，非新引入）

**问题**（先于本分支存在）：一本 921 KB 的小说只解析出 **14 章**，且带一个**多余的首章**——
标题序列是 `第1章, 第一章, 第二章 … 第十三章`（`第{idx}章` 是 `parse.py` 的兜底标题格式，
所以第一条是兜底产物）。

**为什么现在才算问题**：时间轴让「章」这个粒度**对用户可见**了。全书位置时滑块读作
「读到：第十三章」，而图上显示的是 14 章。这是对一个坏上游标题的**诚实标注**，不是时间轴的 bug。

**顺带确认了一件好事**：`buildBuckets` 的 `N > 20 → 16 桶` 分支虽然在真实产物上**从未执行过**
（14 ≤ `PER_CHAPTER_MAX = 20`，走的是一章一桶分支），但它已被**数值穷举验证**：
N ∈ {21, 22, 31, 32, 33, 48, 137, 921, 1000} 时一律恰好 16 桶、cutoff 严格单调、最后一个 cutoff
恒等于 N（没有章节不可达）、无重复。即该分支「构造上正确」。

**§5.1 分桶的固有取舍**：N = 137 时最左一档就已经放出 8 章，所以「只看第 1 章」这个位置
**不可达**。这是分桶方案本身的性质，不是缺陷，但值得记下来以免被当成 bug 报上来。

**规模**：解析器自己的工单，与时间轴解耦。

### 11.7 零散项

**(a) 从未做过手工浏览器验证。** 计划 Step 3 标注为「可选但推荐」
（`docs/superpowers/plans/2026-09-20-relation-graph-timeline.md:2836`），实际未执行。于是**所有
端到端 UX 断言**（滑块出现、左拖时节点变少、点人物出曲线）都只靠单元测试 + 读代码支撑。
建议补一次 10 分钟的离线人工验证，覆盖：滑块拖动、人物出场曲线、`NOVEL_KG_EVOLVE_ENABLED=0`
下的渲染（应只掉演变高亮，滑块与曲线照常）、旧格式降级横幅 + 重新分析按钮。

**(b) README 的 `界面预览` 缺 `时间轴` 小节。** README:20-21 的导语已经把 `时间轴` 列进 5 个
全屏浮层，但下面的小节只有 概览/故事正片/故事脉络/人物关系/原文 等，没有 `时间轴`。这是遗漏
而非事实错误，补它需要一张 `docs/screenshots/` 里**并不存在**的截图。

**(c) `AGENTS.md` 的 `backend/config.py` 路径是错的**，真实路径是 `backend/app/config.py`
（`AGENTS.md:42`）。这条过期路径在本分支施工过程中**真的把人误导过**。`AGENTS.md` 不在本分支
允许修改的文件集内，故留到分支外修。

**(d) `edgeList` 有一个潜在的静默零边洞。** `GraphTab.jsx:116-118` 是
`graph?.edges || graph?.links || []`，而 `graph.edges = []` 是 **truthy**，所以
`{edges: [], links: [...207]}` 会返回 `[]`——正是这个 helper 存在的目的所要防止的失败模式
（真实产物的边数组键是 `links`，`edges` 完全不存在，已核实全部 15 个产物皆然）。
从 graphify 的输出不可达，只有手写 fixture 同时带两个键时才会触发。一行修法：
`(graph?.edges?.length ? graph.edges : graph?.links) || []`，外加一个测试用例。

**(e) `ProcessingPage.jsx:61` 的 `useLayoutEffect` 无测试钉住**——把它改成 `useEffect`，86 个
前端测试全绿。这个选择是**正确**的（layout effect 在 commit 块内同步 flush，promise 续体是
microtask，无法插进同步 JS，因此 `liveId` ref 在任何 POST 续体运行时必定是最新的），但在 jsdom
里**不可观测**。今天没有现实危害（`src/` 里没有任何 `startTransition` / `Suspense` / `lazy`）。

**(f) 可顺手删除的死代码（约 3 行）**：`bucket.chapterId` 零消费者
（`graphTimeline.js:77,94`，`:63` 的 JSDoc 已自陈「保留字段，暂无消费者」）；`bucket.label`
只作为 `bucketText` 的兜底存活（`ChapterSlider.jsx:11`）；`ConfirmItem.reason`
（`evolve.py:135`）从未被读取。

### 11.8 逐任务评审中另外几条需长期保留的结论

以下几条来自本分支各任务的评审记录（该记录不入库，随分支消失），与 11.1–11.7 不重叠。

**(a) `steps[].evidence` 可能引用错章节的原文。** `merge.py:212-214` 会用**任意章节**里见到的
最长 evidence 覆盖 `rec.evidence`，所以一个标注为 `ch0001` 的 step 完全可能引到实际出现在
`ch0020` 的文字。彻底修好需要给 `RelationRecord` 加**按章 evidence**，即重开数据层。
**当前的缓解完全在展示层**：演变详情里的引文**不得**标成「第 N 章原文」，它是该关系的
代表性证据，必须照此措辞。任何后续改动若把它重新标成某一章的原文，就会把一个措辞取舍
变回一个事实错误。

**(b) 强模型确认是全批丢弃语义。** `evolve.py:205-222` 把所有批次的 `kept` 累积在同一个
`try` 内，任何一批抛异常都走到 `except` 直接 `return []`——**先前批次已确认的演变一起丢掉**，
不同于 `merge.py` 的 L2 确认（它保留部分结果）。后果：一本候选数 > `EVOLVE_BATCH_SIZE`（默认 10）
的长篇，只要有一次 Bedrock 限流，就从「丢一部分高亮」变成「丢**全部**高亮」。这是当时
「任一失败 ⇒ `[]` + 一条警告」这条硬约束的直接产物，滑块与出场曲线不受影响，所以属设计降级
而非缺陷；但若要改成保留部分结果，warn 契约要同步改。

**(c) `store.read_meta` 是 `store.py` 里唯一没有守卫的 JSON 读，而 reanalyze 新把它变成了
必经关卡。** `store.py:61-65` 没有 try/except，而每一个同级读函数都有
（`store.py:103/118/138/153/173/189` 的 `except (ValueError, OSError)`）。于是损坏的
`meta.json` 会让 `POST /works/{id}/reanalyze` 抛未捕获的 `JSONDecodeError` → 500；
`meta.json` 内容是 `[]` 时则是 `AttributeError` → 500。先于本分支存在，但本分支提高了它的
可达性。一行 `except` 即可对齐兄弟函数。

**(d) 只出现在关系里的人物永远无法被滑块隐藏。** `graph.py:156-160` 为「只被关系提到、
自身没被抽成人物」的节点造桩，写的是 `mentions_by_chapter: {}` 和 `first_chapter: ""`。
空字符串在 `orderMap` 里查不到，`firstChapterOrder` 按约定返回 0（未知 ⇒ 视为最早 ⇒ **恒可见**），
所以这类节点从第一档起就一直在图上；同时因为 histogram 为空，`mentionPeak` 为 0，右栏
**不画曲线**（这是有意的：没有测量过 ≠ 测量结果为 0）。验证作品里恰好 0 个这种节点，所以今天
未被观察到。注意这里的未知章节默认方向与演变 step 的相反（`isStepAfterCutoff` 把未知章节
判为**变暗**），两处各自正确——都朝「不过度声明」的方向兜底——但相距 200 行且无交叉引用。

**(e) `EVOLVE_ENABLED` 的取值判定用的是「假值集合」而非「真值集合」**
（`app/config.py:149-154`，集合是 `{"0", "false", "False", "no"}`）。于是
`NOVEL_KG_EVOLVE_ENABLED=FALSE`、`=off`、`=OFF`、`=n` **都关不掉它**，与相邻那些
truthy-set 写法的开关（如 `USE_FAKE_LLM`，`app/config.py:82`）行为相反。§8 把这个变量
当作 kill switch 来卖，一个「关不掉的关闭开关」在需要它的时刻最容易出事。

**(f) 前端渲染测试的门槛是「一个文件」，不是「一个工具链项目」。** `vitest.config.js:5-6`
已经配好 `environment: "jsdom"` + `setupFiles`，`@testing-library/react`、
`@testing-library/jest-dom`、`jsdom` 都已安装（`ProcessingPage.test.jsx` 就是现成先例，
只需 2 个 mock）。§1.3 把渲染测试排除在本期之外是**计划取舍**，不是「做不到」——这个理由要
如实记住，否则下次会用错误的成本估算继续推迟。当前最值得补的就是 `GraphTab.jsx` 里
**helper 与调用点之间的连线**：`transitionBadgeText`（`:80`）和 `isStepAfterCutoff`（`:96`）
两个纯函数本身被测得很扎实，但把 `:241`/`:391` 的调用内联掉、或把 `:399` 的调用内联掉，
86 个测试**全绿**。而「badge 三元表达式被写反」正是当初完全看不见的那一类错误。
