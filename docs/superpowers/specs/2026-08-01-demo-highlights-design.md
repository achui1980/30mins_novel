# 30分钟读懂一本书 — 演示亮点改造设计

状态：设计已通过分段确认，待生成实施计划。
日期：2026-08-01

## 1. 背景与目标

现有项目（小说上传 → 异步 pipeline → 知识图谱 + 分层摘要 + 问答）已经实现了不少被埋没的亮点：
两段式"叙事编导"摘要（`summarize.py` 的 `_story_spine` + 4 种 tone 语调）、agentic
工具调用式问答（`ask.py`，5 个 `@tool`：list_characters/get_relations/list_chapters/
read_chapter/search_text）、Louvain 社区检测（`graph.py` 的 `cluster_mod.cluster`）、
带原文证据引用的图谱点击详情、全套离线 `NOVEL_KG_USE_FAKE_LLM` 镜像、以及"永不抛异常"的
pipeline（逐 block 失败仅记录 warning）。

但当前呈现方式没有把这些亮点展示出来，反而暴露了三个具体缺陷（见第2节）。本次改造目标是
**在不触及上传/进度页、不触及问答检索逻辑本身、不引入新的前端依赖的前提下，依次修复这三个
缺陷，最大化产品演示（面向老板/客户，追求30秒内"哇"效果）时阅读页（`ReaderPage.jsx`）的
视觉与交互冲击力**。

### 受众与演示流程（已确认）

- **受众/目的**：产品/业务演示，评判标准是屏幕呈现效果，不是代码架构深度。
- **演示流程**：现场上传作为开场动作，但讲解时会切到一个预处理好的作品来细讲阅读页。
  阅读页的呈现质量是本次改造的重点；上传/进度页不在范围内。

### 范围约束（已确认）

- 不碰上传/进度页（`HomePage.jsx` / `ProcessingPage.jsx`）。
- 不碰问答 tab 本身的检索逻辑（`ask.py` 的 agentic 工具调用不变）。
- 不碰离线 fake-LLM 路径以外的代码，但 fake 路径必须同步更新以支撑新功能（测试和离线演示都
  依赖 `NOVEL_KG_USE_FAKE_LLM=1`）。
- 已知的 `ask.py:80` `spine` 死参数问题（Q&A agent 从未使用传入的 `spine`，看不到已算好的
  剧情主线和关键节拍）**不在本次修复范围**，仅记录在第6节"已知限制"中。

### 老数据迁移策略（已确认）

现有 `data/works/` 下 11 个已处理作品：

- **图谱降噪**：纯前端渲染逻辑，对现有 `graph.json` 立即生效，无需重新跑 pipeline。
- **修复建议问题 / 时间线功能**：都需要新格式的后端产物（新的 `suggested_questions` 生成方式、
  新的 `events.json`）。老作品缺少这些新数据时，前端**优雅降级**——隐藏对应区块/tab，不报错、
  不显示占位假数据。不为旧 `summary.json` 写兼容/回填代码。演示前，用新代码重新处理一遍演示用
  的那本书，生成全新数据。

## 2. 现状问题清单

1. **图谱噪音**：地点节点严重过多且几乎不连边。实测 `data/works/dd89e648bda1/graph.json`：
   310 个节点中 226 个是地点、仅 84 个人物，但总共只有 128 条边——"人物关系图"视觉上变成一堆
   断开的灰色方块。
2. **"你可能想问"是乱码级尴尬**：该字段来自 graphify 的 `analyze.suggest_questions`
   （betweenness centrality，代码审查场景设计），对小说文本产出类似
   `"Should \`雪穗娘家\` be split into smaller, more focused modules?"` 的驴唇不对马嘴问题。
   前端 `ReaderPage.jsx` 把这个区块标注为"（展示用）"——承认它是假的——但旁边就是能真正回答
   问题的 agentic Q&A tab，反差尴尬。
3. **时间线数据齐全但功能完全不存在**：`Event.order_hint` 被抽取，`summarize.py` 的
   `_plot_timeline` 会组装时间线文本喂给 LLM 做"忠实性锚点"，但 `orchestrator.py` 明确写了
   `registry.events` 从未持久化到磁盘——pipeline 跑完这些事件数据就丢失了，没有 API，前端
   没有任何时间线 UI。

## 3. 实施顺序（已确认）

按投入产出比：

1. 图谱降噪（不需要重跑 pipeline，纯前端，老作品立即生效）
2. 修复"你可能想问"（需要改后端生成逻辑，新作品见效）
3. 时间线功能（events 从未落盘，需要后端持久化 + API + 前端 UI，工作量最大）

## 4. 详细设计

### 4.1 图谱降噪

**(a) 后端 prompt 收紧**（治本，长期生效，仅影响新处理的作品）

- `backend/app/pipeline/extract.py` 的 `SYSTEM_PROMPT`（:27-34）新增地点抽取的克制性指导：
  只提取对情节有实际作用、被反复提及或承载关键事件的地点，忽略一次性/泛化地名。
- `COMPLETE_HINT`（:37，当前为"当前为【完整】档，尽量抽取全部人物、地点、事件与关系"）
  弱化"尽量抽取全部...地点"的措辞，改为强调地点仍需满足上述克制性标准，即使在完整档下也
  不应无差别抽取。

**(b) 前端 Top-N 过滤 + 显示全部切换**（兜底，立即生效，让老作品立即受益）

- `frontend/src/pages/ReaderPage.jsx` 的 `GraphTab` 组件（:381-487）当前完全没有节点过滤逻辑
  （:399-409 构建 `nodes` 数组时无任何裁剪）。新增地点节点过滤：
  - 按**度数（degree，即连接边数）**排序，而非 `mention_count`——高提及但零连接的地点仍应
    被过滤。
  - 默认只保留度数最高的 Top-15 地点节点；提供"显示全部地点"切换开关。
  - 被过滤的节点从传给 vis-network 的 `nodes`/`edges` 数组中**完全剔除**（不是仅设置
    `hidden`），避免 Barnes-Hut 物理引擎浪费布局算力在被过滤节点上。
  - 人物节点不受此过滤影响。

**(c) 离线 fake 路径新增少量假地点**（支撑离线演示/测试展示该过滤 UI）

- `fake_extract_block`（extract.py:75-131）目前完全不产生 `Place` 对象（只 import 了
  `Character/Event/Relationship/RelationCategory`）。新增：在现有 Top-5 非重叠 CJK 子串选作
  `Character` 之后，取排名靠后的 1-2 个非重叠子串作为 `Place` 候选（复用同一频率排序机制，
  无需语义准确性）。
- 新增单元测试：断言 `fake_extract_block` 输出包含 1-3 个 `Place` 对象。

**老数据兼容**：11 个现有作品的 `graph.json` 已固化在磁盘，前端过滤是运行时处理已加载的
`graph.json`，老数据无需重新生成即可享受降噪效果。

### 4.2 修复"你可能想问"

**现状数据流**（已通过 grep 全代码库验证）：

```
graph.py:197  analyze.suggest_questions(G, communities, community_labels, top_n=7)
  -> graph.py:221  GraphArtifacts.suggested_questions
  -> orchestrator.py:160  _build_suggested_questions(artifacts)  [orchestrator.py:215-232]
  -> orchestrator.py:170  WorkPackage(..., suggested_questions=suggested)
  -> models.py:157  WorkPackage.suggested_questions: list[SuggestedQuestion]
```

**(a) 后端：新的 LLM 生成阶段**

- `summarize.py` 的 `summarize(...)` 函数（当前签名 :365-387，返回
  `tuple[LayeredSummary, list[SettingCard], Optional[dict]]`）改为返回 **4 元组**，新增
  `suggested_questions: list[SuggestedQuestion]`（复用 `models.py:144` 已有的
  `SuggestedQuestion{question, rationale}` 模型，无需新建模型）。
- 真实路径 `_llm_summary`（:418-477）：在 Step1（`_story_spine`）+ Step2（`LayeredSummary`
  生成）之后新增 Step3，复用同一个 `agent` 对象，prompt 基于 `spine_block`
  （main_thread/protagonists/key_beats）+ `layered.overview`，明确要求 LLM 生成 3-5 个：
  - 可以通过阅读小说实际章节回答的问题（人物关系/情节转折/结局方向）；
  - 明确禁止代码审查风格问题（"是否应该拆分模块"类）；
  - 明确禁止过于主观开放、无法从文本回答的问题。
  - 通过新的 `SuggestedQuestions{questions: list[SuggestedQuestion]}` pydantic 包装模型
    （模仿现有 `SettingCards` 包装模式，:467）走 `_structured_with_retry`（:153）。
  - 失败时**独立**兜底到 fake/heuristic 问题生成器（模仿 `SettingCards` 的独立 fallback，
    :471-476），确保建议问题生成失败不会拖垮整个摘要。
- fake 路径 `_fake_summary`（:499-577）：基于 `spine_payload` 的 `protagonists`/`key_beats`/
  `one_liner` 构建确定性模板问题（例如两大主角关系问题、基于首/末 `key_beat` 的问题、结局
  方向问题）——无 LLM 调用，保证离线 demo/测试可靠性，风格参考 `_fake_setting_cards`
  （:580-598）的"无随机性、模板字符串"惯例。

**(b) 清理死代码**

- 移除 `graph.py` 里 `analyze.suggest_questions(...)` 调用（:197）和
  `GraphArtifacts.suggested_questions` 字段（:42, :221）。
- 移除 `orchestrator.py` 的 `_build_suggested_questions()` 函数（:215-232）及其调用点（:160）。
- `orchestrator.py` 改为直接从 `summarize(...)` 新的 4 元组返回值里取 `suggested_questions`
  传入 `WorkPackage(...)`。

**(c) 前端交互：点击建议问题 → 跳转问答 tab 并自动提交**

- `Overview` 组件（ReaderPage.jsx :78-121）的建议问题列表项变为可点击，完全移除
  "（展示用）"字样（当前在 :108）。
- 点击 → 跳转到"问答"tab（`ask`）+ 自动提交该问题，走现有 `/works/{id}/ask` 流程，直接展示
  能真正工作的 agentic Q&A。
- 实现方式：
  - `ReaderPage` 新增一个"pending/seed question"状态，并把 `setTab` 传给 `Overview`
    （当前 `Overview` 只接收 `{ls, pkg}` props，无 `setTab` 访问权限）。
  - `AskFeature`（:123-193）现有的 `submit(e)` 处理逻辑（当前自包含，:137-152）重构为可复用的
    `runAsk(questionText)` 函数。
  - `AskFeature` 新增 `seed` prop，通过 `useEffect` 监听——当 `seed` 变化时（用新的
    nonce/timestamp 允许重复点击同一问题）自动调用 `runAsk(seed.question)` 而不只是预填
    输入框。

**(d) 老数据兼容**：不为旧 `summary.json`（含 graphify 旧垃圾问题或完全没有）写兼容代码，
前端仅在数据缺失/形状不符时隐藏该区块；演示书用新代码重新生成全新数据。

### 4.3 交互式时间线功能

**背景事实**（已通过代码审查确认）：

- `models.py:66-72` `Event{summary, chapter, participants: list[str]=[], order_hint: int|None}`。
- `merge.py:73` `EntityRegistry.events: list[dict] = []`；`add_extraction`（:166-181）向其中
  append 纯 dict：`{"summary", "chapter", "participants", "order_hint"}`。**注意
  `participants` 是 LLM 抽取的原始字符串，未经过 `resolve_character` 规范化**——与
  characters/relationships 不同。因此时间线 UI 仅展示参与者姓名文本，不做图谱人物联动
  （联动列为未来工作，见第6节）。
- `summarize.py` 的 `_plot_timeline`（:85-121）已有分组+排序逻辑：按章节分组（:93-95，
  `by_chapter.setdefault(e.get("chapter",""), []).append(e)`），保留小说章节原有顺序
  （`ordered_chapters`，:98-101，未在 chapters 列表里的章节追加到末尾），章节内按
  `order_hint` 排序（:108，`key=lambda x: (x.get("order_hint") or 0)`，`None` 视为 0），
  上限 `MAX_TIMELINE_EVENTS=120`（:72，仅为控制 prompt 体积）。输出目前是文本行格式，供 LLM
  做"忠实性锚点"。新的时间线 API 需要复用其分组/排序逻辑，但输出结构化 JSON。
- `orchestrator.py:77-78` 明确注释 "registry/events are in-memory only and not saved"——
  这是本次要解决的持久化缺口。
- `orchestrator.py` 的异常处理（:182-191）确认：即使 Phase 5（摘要）失败，已写入磁盘的文件
  （如 `chapters.json`/`graph.json`）不会被回滚。因此 **`events.json` 应在 Phase 3 抽取
  完成后立即持久化**，而不是等到 Phase 5，这样即使后续 `summarize` 失败，时间线功能依然
  可用。
- `fake_extract_block`（extract.py:75-131）的 `Event` 已设置 `order_hint=block.order`
  （block.order 为全局单调递增的分块顺序，见 chunk.py），并且 `participants=top[:3]`
  复用同一 block 生成的角色名——**离线/fake 路径已天然产生有意义的顺序和一致的参与者**，
  无需为时间线功能修改 `fake_extract_block`。

**(1) 后端持久化**

- `orchestrator.py`：在 Phase 3 抽取完成、`registry.characters` 校验通过之后（紧跟在现有
  `extract_all` 调用之后，早于 Phase 5 摘要），新增将 `registry.events`（原始 dict 列表）
  写入 `{work_dir}/events.json` 的逻辑，写入方式与 `chapters.json` 一致。

**(2) 新模块** `backend/app/pipeline/timeline.py`

- 新增函数（如 `build_timeline(events, chapters) -> list[TimelineEvent]`），复用
  `_plot_timeline` 的分组（按章节，保留小说顺序）+ 排序（`order_hint`，`None` 视为 0）逻辑，
  但输出扁平化结构：`[{seq, chapter_id, chapter_title, summary, participants}, ...]`
  （而非嵌套的按章节分组结构），因为扁平列表更适合渲染为一条横向时间轴上的离散事件卡片；
  `chapter_id`/`chapter_title` 挂在每个事件上而非分组容器上。
- 不放进 `summarize.py`（避免其继续膨胀超过 598 行，也避免 `routes.py` 引入 `summarize.py`
  的重 LLM-agent 依赖链只是为了做这个轻量的 JSON 整形）。

**(3) 新模型** `models.py` 新增：

```python
class TimelineEvent(BaseModel):
    seq: int
    chapter_id: str
    chapter_title: str
    summary: str
    participants: list[str] = Field(default_factory=list)
```

**(4) 新 API 端点** `GET /works/{id}/timeline`

- 读取 `events.json` + `chapters.json`（后者提供章节标题，且其字典 key 插入顺序即小说章节
  原始顺序，Python 3.7+ 字典保序特性可直接利用）。
- 调用 `build_timeline(...)`，返回 `{work_id, events: [...]}`（与其他端点风格一致的包装）。
- 若 `events.json` 不存在（老作品，或 pipeline 在抽取阶段前失败），返回 404，遵循现有
  "缺失产物返回404"惯例（对标 `/beats` 端点在 `spine.json` 缺失时的 404 行为）。

**(5) 前端 UI**

- `ReaderPage.jsx` 的 `TABS` 数组（:7-14）新增一个"时间线"tab。
- 新建 `TimelineTab({id})` 组件：
  - mount 时 fetch `/works/{id}/timeline`。
  - 404 时展示"该作品是使用旧版本处理的，请重新处理以查看时间线"式的友好提示（对标
    `StoryFeature` 组件里"older works must be re-uploaded"的既有错误提示模式，
    ReaderPage.jsx :228）。
  - 有数据时渲染**交互式横向可滚动时间轴**：flex + `overflow-x: auto` 的 CSS 横向条带，
    事件作为条带上可点击的节点/卡片（可按章节分组加浅色背景色块/章节标题标签）。点击展开
    显示该事件详情（`summary` + `participants`），复用 `GraphTab` 点击详情面板的既有交互
    模式（:431-441）以保持全站 UI 一致性。
  - 技术选型：不引入新的图表库，延续全站"纯手写 CSS + flex"风格（`GraphTab` 用 vis-network
    做图谱是唯一例外），因为时间线只是一条刻度的横向轴，flex 布局完全够用。

**(6) fake/离线路径**：无需修改 `fake_extract_block`——已确认其产生的 `order_hint`/
`participants` 在离线模式下就是有意义且一致的（见上文背景事实）。

**(7) 老数据兼容**：`events.json` 缺失时端点返回 404，前端隐藏时间线 tab 内容并显示友好
提示；不为旧作品做迁移，演示用书会用新代码重新处理生成全新数据。

## 5. 测试计划

- **单元测试**（`backend/tests/`，延续现有 `NOVEL_KG_USE_FAKE_LLM=1` 离线约定）：
  - `fake_extract_block` 输出包含 1-3 个 `Place` 对象（图谱降噪）。
  - `_fake_summary`（或新的 fake 建议问题生成函数）输出 3-5 个 `SuggestedQuestion`，且不包含
    "拆分模块"类代码审查关键词。
  - `build_timeline(...)`：多章节多事件输入 → 验证章节顺序保留、章节内按 `order_hint` 排序、
    `order_hint=None` 视为 0、`seq` 全局唯一递增。
  - `events.json` 持久化：`run_pipeline` 集成测试（现有 `test_pipeline_integration.py`）新增
    断言 `events.json` 存在且内容与 `registry.events` 一致。
- **路由测试**（新增，当前 `routes.py` 零覆盖，本次至少覆盖新端点）：
  - `GET /works/{id}/timeline` 成功返回 200 + 结构化列表。
  - `events.json` 缺失时返回 404。
- **前端**：本项目无前端测试工具链（无 vitest/@testing-library），本次不引入，通过手动
  在浏览器验证三个模块的交互效果（图谱过滤开关、建议问题点击跳转、时间线横向滚动/点击详情）。

## 6. 已知限制 / 未来工作（不在本次范围内）

- `ask.py:80` 的 `spine` 参数从未被 `_agent_answer_question` 使用——Q&A agent 看不到已算好
  的剧情主线和关键节拍。虽然与时间线主题相关，但按范围约束"不碰问答tab本身的检索逻辑"，
  本次不修复。
- 时间线与图谱联动（点击时间轴事件，图谱同步高亮涉及的人物/关系）——需要先解决
  `Event.participants` 未经 `resolve_character` 规范化的问题，列为二期加分项。
- `graphify` 的 `god_nodes`/`surprising_connections` 等其他分析能力仍有优化空间（既有代码
  审查发现），不在本次范围。

## 7. 实施顺序总结

1. 图谱降噪（后端 prompt + 前端过滤 + fake 路径地点生成 + 单测）
2. 修复建议问题（后端 4 元组改造 + 死代码清理 + 前端点击跳转 + 单测）
3. 时间线功能（后端持久化 + 新模块 + 新模型 + 新端点 + 前端新 tab + 单测/路由测试）

每步完成后建议独立验证（`cd backend && PYTHONPATH=. pytest -q`），确保不破坏现有 21 个测试。
