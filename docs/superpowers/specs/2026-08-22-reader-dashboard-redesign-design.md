# 30分钟读懂一本书 — Reader Dashboard 重设计

状态：设计已通过分段确认 + HTML mockup（v1→v2 修订）验证，待生成实施计划。
日期：2026-08-22
配套原型：`docs/superpowers/specs/2026-08-22-reader-dashboard-mockup.html`（静态 HTML，无构建步骤，可直接在浏览器打开）

## 1. 背景与目标

现有 `ReaderPage.jsx` 采用持久化顶部 Tab 栏（总览/人物/故事正片/原文/情节线/时间轴/图谱/
问答/设置，共 9 个 tab），用户需要逐个点开 tab 才能拼出这本书的全貌。这与产品的核心定位
"**30分钟读懂一本书**"不匹配：用户打开一本书后应该先看到一个**全景视图**，快速获得
书的基本信息、人物关系、情节脉络等，再自行决定是否要深入阅读原文——阅读原文是**可选的
深度动作**，不是默认路径。

产品的另一个长期目标是**未来发布为 APP**（移动端），这意味着当前"桌面网页 Tab 栏"式的
导航模型需要向"App 式堆栈导航"（根屏 + 全屏子页 + 返回）过渡。

本次目标：将 `ReaderPage` 从"9 tab 平铺"重构为"**Dashboard 全景根屏 + 堆栈式深度子页**"
的信息架构，同时保留几乎所有现有 tab 组件的实现（不重写内部逻辑，只改变它们被谁引用、
以什么身份出现）。

### 范围与约束（已确认）

- 只重构 `ReaderPage` 及其导航模型；`HomePage`/`ProcessingPage`、AppShell 左栏"书架"、
  后端 API、数据结构均不改动。
- 现有 9 个 tab 组件（`OverviewTab`/`StoryTab`/`ArcsTab`/`RawTextTab`/`TimelineTab`/
  `CharactersTab`/`GraphTab`/`SettingsTab`/`AskTab`）**全部复用现有实现**，不重写内部
  渲染/交互逻辑，只调整它们的挂载位置、传参方式和触达路径。
- 视觉设计语言（配色 token、字体、圆角、阴影等，见 `frontend/tailwind.config.js`）保持
  不变，直接沿用现有"宣纸墨迹"体系（paper/ink/seal/pine/amber）。
- 不做响应式/移动端适配（与既有前端约束一致，见 `2026-08-04-frontend-ui-redesign-design.md`
  §"范围与约束"）；本次重构是为未来 App 化做**导航结构**上的准备，不是本次就实现移动端
  布局。
- 已通过 HTML 静态 mockup 做了一轮设计验证（v1）与一轮基于用户critique的修订（v2），本
  文档描述的是 **v2（最终）版本**的设计。

## 2. 信息架构与导航模型

### 2.1 核心原则

"30分钟读懂一本书" → 全景优先，深度阅读是可选的下钻动作。

### 2.2 导航结构：堆栈式（Stack Navigation），取代持久 Tab 栏

- **根屏 = Dashboard**：一个可滚动的单页，取代原来的 9-tab 栏。
- **无持久顶部 Tab 栏**：任何"深度内容"（完整人物关系图谱、完整情节脉络、原文阅读、
  完整时间轴、逐幕剧情正片）都以**全屏子页**形式打开，带一个"← 返回"按钮，返回后回到
  Dashboard 之前的滚动位置。
- **吸顶锚点导航条**（v2 新增，用于弥补去掉 Tab 栏后桌面端跨区块跳转变慢的问题）：
  Dashboard 顶部吸顶显示 5 个锚点药丸按钮（简介/人物/情节/时间/设定），点击在**页面内**
  平滑滚动到对应 section（`scrollIntoView`），不产生路由跳转，因此不违反"无 Tab 栏"的
  决策。配合一个基于 `IntersectionObserver` 的 scroll-spy，滚动时自动高亮当前所在区块
  对应的锚点（呼应现有 `ArcsTab` 章节 TOC 高亮、`RawTextTab` 阅读进度追踪等既有的
  IntersectionObserver 使用模式）。
- **全局悬浮元素**（Dashboard 与所有全屏子页上都可见）：
  - **Ask-AI 悬浮入口**（右下角圆形按钮 + 展开的提问面板）：取代原来的"问答"tab，
    对应 `onAsk(question)` 回调；点击 Dashboard 上"你可能想问"里的问题会预填到该面板。
  - **设置齿轮图标**（右上角）：点开一个弹层，包含**App 阅读偏好**（字号 A-/A+、
    日间/夜间主题——即目前 `RawTextTab` 里全局 localStorage 的
    `novel_kg_reader_font_size`/`novel_kg_reader_theme`）。**注意**：这与 Dashboard
    上的"世界观设定"（`SettingsTab` 展示的书内设定卡）是两个完全不同的概念，不要混淆——
    前者是 App 偏好，后者是书籍内容。

### 2.3 CTA（开始阅读原文）的位置——v2 修订

v1 mockup 把"开始阅读原文"大按钮放在 Hero 区（第一屏），收到反馈：这与"全景优先，
阅读是可选深度动作"的核心原则相矛盾——用户会看到大按钮就直接点掉，跳过全景。v2 修订为
两处入口，权重不同：

1. **Hero 区**：降级为一个低调的文字链接"不看全景，直接读原文 →"（`.ghost-link`
   样式，弱化色，不与 Hero 主视觉竞争），供确实想跳过全景、直接看书的用户使用。
2. **Dashboard 末尾**（全部 7 个 section 之后）：一个醒目的大按钮 CTA（"全景看完了？
   带着这些人物和线索，去读原文会更有感觉。" + "开始阅读原文 →"），作为看完全景后的
   自然下一步，此时才给予视觉重量。

两处都调用同一个 `openStack('raw')` 逻辑，打开原文全屏子页。

## 3. Dashboard —— 7 个 Section（从上到下）

| # | Section | 内容来源 | 展开链接 |
|---|---|---|---|
| 1 | **Hero** | 书名、`ls.one_liner`、`ls.story_hook`；v2 新增 `.meta-row`（章节数、字数、预计全景阅读时长、原文阅读进度百分比+当前章节）；`.ghost-link` 跳读入口 | → 原文（子页） |
| 2 | **内容简介（Overview）** | `ls.overview` | 无 |
| 3 | **你可能想问** | `pkg.suggested_questions`，复用 `SuggestedQuestions.jsx` | 点击问题 → 打开 Ask-AI 悬浮面板并预填 |
| 4 | **人物关系**（合并 Characters + Graph） | `pkg.main_characters` 卡片网格 + 一个小型图谱预览区块；数据来自 `pkg.main_characters` + `getGraph(id)` | "查看完整图谱→" → 完整图谱（子页，复用 `GraphTab`） |
| 5 | **情节脉络** | `ls.arcs` 卡片列表（title/summary/涉及人物）；额外的"查看逐幕剧情正片 →"子链接 | "查看完整→" → 完整情节脉络（子页，复用 `ArcsTab`）；子链接 → 剧情正片（子页，复用 `StoryTab`） |
| 6 | **时间轴** | `getTimeline(id)` 的一个子集（3–5 个关键/近期事件） | "查看完整→" → 完整时间轴（子页，复用 `TimelineTab`） |
| 7 | **世界观设定** | `ls.setting_cards`，直接复用 `SettingsTab` | 无 |

末尾追加：v2 新增的底部 CTA（见 §2.3 第 2 点）。

### 3.1 关于"剧情正片"（StoryTab）归属的决定

`StoryTab`（逐幕生成的故事正片文本）与 `ArcsTab`（情节线卡片 + 章节摘要）是两个独立的
数据源，但都属于"情节"这一大类概念。为了不把已锁定的 7-section 顺序变成 8 个、同时
保持用户认知负担最小，决定将"剧情正片"作为"情节脉络"Section 内的一个**次级链接**
（而非独立 Dashboard section，也不是完全隐藏在 ArcsTab 内部才能发现），复用现有
`StoryTab` 组件作为其全屏子页目标。

## 4. 全屏子页（堆栈子页）—— 均复用现有组件，仅重新挂载路径

| 子页 | 复用组件 | 入口 | 布局模式 |
|---|---|---|---|
| 原文 | `RawTextTab`（不改动内部逻辑） | Hero 的"不看全景"链接 / Dashboard 末尾 CTA | **沉浸式，无右侧栏**（v2 新增，见 §5） |
| 完整图谱 | `GraphTab`（不改动） | "人物关系"section 的展开链接 | 保留 AppShell 右侧栏 |
| 完整情节脉络 | `ArcsTab`（不改动） | "情节脉络"section 的展开链接 | 保留 AppShell 右侧栏 |
| 剧情正片 | `StoryTab`（不改动） | "情节脉络"section 的次级链接 | 单栏（StoryTab 本身不使用 `setRight`，无需右侧栏） |
| 完整时间轴 | `TimelineTab`（不改动） | "时间轴"section 的展开链接 | 保留 AppShell 右侧栏 |

所有子页都带一个"← 返回"头部，点击返回 Dashboard 并恢复此前的滚动位置。

## 5. 右侧详情栏决策 —— 保留，但按页面类型区分为两种模式（v2 修订）

现状：`GraphTab`/`ArcsTab`/`TimelineTab`/`CharactersTab` 都通过 AppShell 的 `setRight`
机制把"选中项详情"或"章节 TOC"推到一个持久的 200px 右侧栏（详见现有实现，未改动）。

v1 mockup 曾经笼统地"把所有子页都做成全屏子页，同时保留右侧栏"，收到反馈：这样"原文"
阅读页仍然两侧带栏（左侧书架 140px + 右侧详情栏 200px），并不是真正的沉浸式阅读体验，
与"这是一个小说阅读器"的产品诉求冲突。

v2 修订为**按子页类型区分两种布局**：

- **保留右侧栏（`setRight` 模式不变）**：完整图谱、完整情节脉络、完整时间轴——这三个
  子页的"点击节点/事件查看详情"交互本质上依赖右侧详情栏，改动风险大、收益低，维持现状。
- **无右侧栏，真正沉浸**：原文（`RawTextTab`）子页——这是用户在应用中停留时间最长、
  最需要沉浸感的场景，去掉两侧栏，页面顶部增加一个小的沉浸态标签
  （"沉浸阅读 · 无侧栏"）与阅读进度提示行（"阅读进度：第 X 章 / 共 N 章"），替代原来
  依赖右侧栏展示的章节 TOC（原有的章节 TOC 功能本身不变，只是不再展示在右侧栏——具体
  在实施阶段决定是否需要一个可展开的章节列表浮层来替代，本设计文档不强制规定）。
- 剧情正片（`StoryTab`）子页本身在现有实现里不使用 `setRight`，因此天然是单栏，无需
  额外处理。

## 6. 跨组件契约（实施时必须保留，不能破坏）

- **`onAsk(question)`**：问题 → Ask 流程的回调，目前在 `OverviewTab`/
  `SuggestedQuestions.jsx` 中触发。重构后必须同时可从 Dashboard 的"你可能想问"卡片
  与全局悬浮 Ask-AI 入口触达，语义不变。
- **`onViewChapter(chapterId, paragraphIndex)`**：深链跳转回调，解析形如
  `chapterId#pN` 的 `source_location` 字符串，用于从 `TimelineTab`/`CharactersTab`/
  `GraphTab` 跳转到 `RawTextTab` 中的具体段落。重构后这三者仍然是各自独立的全屏子页，
  这个回调必须能从子页内部正确打开"原文"子页并定位到目标段落（即：原文子页需要支持
  "带着定位参数被直接打开"，而不仅仅是从 Dashboard 用户手动点入）。
- **`useAccordionCache`**：`StoryTab`/`ArcsTab` 用来做懒加载 + 展开状态缓存的 hook，
  在两者变成独立全屏子页后逻辑不变，直接沿用。
- **`setRight`/AppShell 右侧 `<aside>`（200px）模式**：按 §5 决策，图谱/情节脉络/
  时间轴三个子页保留不变；原文子页不再使用。

## 7. 数据来源一览

| Dashboard Section / 子页 | API / 数据源 |
|---|---|
| Hero / Overview | `getWork(id)` → `pkg.title`、`ls.one_liner`/`ls.story_hook`/`ls.overview` |
| 你可能想问 | `pkg.suggested_questions` |
| 人物关系 | `pkg.main_characters` + `getGraph(id)` |
| 情节脉络 | `ls.arcs`；子页章节摘要用 `getChapterSummary(id, chapterId)`（懒加载） |
| 剧情正片 | `getBeats(id)` + `getBeatStory(id, beatIndex)`（懒加载） |
| 时间轴 | `getTimeline(id)`（Dashboard 上取子集，子页取全部） |
| 世界观设定 | `ls.setting_cards` |
| 原文 | `getChapterText(id, chapterId)`（懒加载，逻辑已在近期 bug fix 中修正——见下） |
| Ask-AI | `askQuestion(id, question)` / `getAskHistory(id)` |

## 8. 已知限制 / 不在本次范围内

- 不做响应式/移动端布局实现——本次只调整信息架构/导航模型，为未来 App 化铺路，具体的
  移动端视觉适配是另一个独立项目。
- 图谱预览（Dashboard "人物关系"section 内的小型图谱缩略展示）的具体可视化方案（是否用
  真实的迷你力导向图、静态示意图，还是别的表现形式）留给实施阶段决定；mockup 中用了一个
  占位说明区块，不构成最终视觉规格。
- 整体信息密度/结构化数据的可读性优化（例如人物关系、时间轴是否需要更图形化的呈现）已
  作为 mockup critique 的第 6 点被记录，但明确**推迟到本次重构之后**的后续优化，不在
  本次 scope 内。
- 原文子页去掉右侧栏后，原有章节 TOC 是否需要一个替代性的浮层/抽屉入口，留给实施阶段
  决定（见 §5），本设计文档不强制规定具体交互形式。

## 9. 与近期 bug fix 的关系

`RawTextTab.jsx` 中修复的"章节懒加载竞态"bug（`loadChapter` 的 `shouldFetch` 闭包变量
在 `IntersectionObserver` 批量回调中读到过期值，导致部分章节永久卡在"加载中…"；已改为
`chapterFetchRef` 同步判重）与本次 Dashboard 重构无直接依赖关系，但由于"原文"页在新
架构下的使用频率会因"沉浸式设计"和底部大 CTA 而进一步提升，该修复的正确性对新架构的
体验质量更加重要。此修复已应用于代码但尚未提交 git；建议在开始本次重构的实施计划之前
先提交该修复。

## 10. 验证方式

- 前端目前无自动化测试基建（与既有约束一致）；验证方式为手动走一遍新 Dashboard 的全部
  7 个 section + 5 个全屏子页 + 全局 Ask-AI 悬浮入口 + 设置弹层，使用 `data/works/`
  下已处理完成的真实作品数据（如 `715322215446` 白夜行）覆盖：锚点导航跳转 + scroll-spy
  高亮、每个子页的"返回"按钮、`onViewChapter` 深链跳转到原文指定段落、Ask-AI 从不同
  入口（Dashboard 问题卡片 / 悬浮入口 / 子页内）触发后行为一致。
- `npm run build`（frontend）确认改动后构建无报错。
- 静态 HTML mockup（v2，本设计文档配套文件）已作为交互原型在浏览器中验证过锚点导航、
  堆栈子页打开/返回、右侧栏 vs. 沉浸式两种子页布局的视觉区分——实施阶段的真实组件接入
  应以该 mockup 的交互模式为准。
