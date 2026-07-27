# 小说知识图谱应用（30mins Demo）— 设计文档

> 目标：上传一本小说（.txt / .epub），自动生成知识图谱，产出面向读者的「30 分钟读懂一本书」体验：分层摘要、人物关系网、设定卡片。
> 复用 graphify 的图构建/聚类/分析内核，只新增小说专属的语义提取层与读者摘要层。

日期：2026-07-27
状态：设计已批准，待实施

---

## 1. 产品目标

让读者在几分钟内知道「这本书讲了什么」，并可按需下钻：

- 分层故事摘要（一句话 → 概述 → 情节线 → 章节）
- 人物关系网图谱（按关系类别着色，点节点/边查看详情）
- 主题/设定卡片
- （v2）基于 GraphRAG 的问答

UI 必须简单。核心体验是「30 分钟读懂一本书」。

---

## 2. 总体架构：摄取管道 + 静态产出

上传后台异步跑一次管道，产出静态工作包，读者快速浏览。选用此方案（Approach A）而非实时按需（B）或纯 agent 无预处理（C），因为它给读者最快的浏览体验，提取只跑一次，契合 graphify「构建一次、多次查询」的模型。

```
上传 .txt/.epub
  → 解析(epub→文本, 按章节切分)
  → 分块(每章 ~2-4k token, 保留章节归属)
  → 逐块提取(Strands structured_output, 滑动上下文注入已知实体)
  → 增量合并去重(精确名 → 别名表 → 相似名归一化确认)
  → graphify build_from_json(图在此诞生)
  → cluster(社区≈情节线/阵营) + analyze(god_nodes=主角/桥接/建议问题)
  → summarize(Strands→分层摘要+设定卡)
  → 打包 work package
```

进度通过轮询 `GET /works/{id}/status` 上报：parsing → extracting(%) → building → summarizing → done。

### 关键澄清
- 知识图谱**不是预先存在的**——分块 LLM 提取正是「创建」图谱的过程。顺序：小说文本 → 分块提取 → 合并去重 → graphify `build_from_json`（图在此诞生）→ 聚类/分析/摘要。
- graphify 处理超大代码库靠 AST 结构解析（本地、与规模无关、不用模型）；小说是非结构化散文，关系没有语法标记，**必须**走 LLM 语义提取路径，受上下文窗口限制 → 分块是必需的。小说提取对应 graphify 的「文档语义」路径。

---

## 3. AI 后端

- AWS Strands（开源 Python agent SDK）+ Amazon Bedrock（Claude / Nova）。
- 用 `agent.structured_output(PydanticModel, text)` 做可靠结构化提取。
- 自定义工具用 TOOL_SPEC dict + function；模型 provider 可插拔。

---

## 4. 提取层

### 4.1 分块
按章节切分，每章再切成 ~2-4k token 的块，保留章节归属。

**滑动上下文摘要**：提取第 N 块时，把「已知实体列表」（姓名+别名+一句话身份）注入 prompt，让模型把代词（「他」「那少年」）解析到已有角色，大幅减少同一人被拆成多个节点。

### 4.2 提取调用
每块 `agent.structured_output(ChunkExtraction, prompt + block + known_entities)`。并发用信号量限制（~5）避免 Bedrock 限流；失败块指数退避重试，最终跳过并记录，不阻塞整个任务。

### 4.3 增量合并（边提取边合并，保持滑动上下文最新）
1. 精确规范名匹配 → 合并
2. 别名表命中 → 合并
3. 高相似名 → 批量一次 Strands「实体归一化」确认调用

### 4.4 提取分档
- **快速（默认）**：仅角色 + 主线关系 + 关键事件，跳过次要地点/龙套角色。让「30 分钟读懂」核心体验跑得最快、成本可控。
- **完整**：全部实体。

---

## 5. 数据模型

### 5.1 提取模型（Pydantic）
- `ChunkExtraction{characters, places, events, relationships}`
- `Character{name, aliases[], role, description}`
- `Place{name, description}`
- `Event{summary, chapter, participants[], order_hint}`
- `Relationship{source, target, category, detail, evidence, confidence}`

### 5.2 关系模型（固定枚举 + 自由子标签）
- `category` ∈ {家人, 爱人, 朋友, 敌人, 师徒, 主仆, 同盟, 其他}（固定，用于图着色/图例）
- `detail`：自由文本（丰富描述，点击展开）
- `evidence`：证据文本
- `confidence`：置信度
- 方向：默认无向；仅 师徒 / 主仆 记 source→target 方向，显示为箭头。

### 5.3 图 JSON（graphify 格式）
- `node{id, label, node_type(character/place), description, source_location(chapter), mention_count}`
- `edge{source, target, relation, category, detail, evidence, confidence, confidence_score, weight=mention_count}`
- 置信度 → 标签：≥0.9 EXTRACTED / 0.4-0.9 INFERRED / <0.4 AMBIGUOUS

### 5.4 读者产出（summary.json）
- `SettingCard{title, content}`
- `LayeredSummary{one_liner, overview, arcs[ArcSummary], chapters[ChapterSummary]}`（arcs = 聚类社区）
- `WorkPackage{work_id, title, layered_summary, setting_cards[], graph_ref, main_characters[]=god_nodes, suggested_questions[]}`

### 5.5 去重策略
精确规范名匹配 → 别名表合并 → 高相似名走一次 Strands 实体归一化确认。事件在提取时顺带记 `chapter` + `order_hint`（近乎零成本），为未来时间线预留，无需重新提取。

---

## 6. API（FastAPI，v1 无鉴权，文件系统存储）

- `POST /works`（multipart: file .txt|.epub, granularity=quick|complete 默认 quick）→ 201 `{work_id, status:queued}`。存原文，spawn 后台异步任务，立即返回。
- `GET /works/{id}/status` → `{work_id, phase, progress, message}`；phase: queued → parsing → extracting(% = processed_blocks/total) → building → summarizing → done|failed。前端 ~2s 轮询。
- `GET /works/{id}` → WorkPackage。
- `GET /works/{id}/graph` → graph.json（供 vis-network/cytoscape）。
- `GET /works/{id}/graph.html` → graphify 交互 HTML（可 iframe）。
- `GET /works` → 已处理作品列表（首页）。
- `DELETE /works/{id}` → 删除作品及产出。
- Q&A（`POST /ask`）延到 v2；数据模型保留 `suggested_questions` 仅用于展示（v1 不作答）。

### 存储
文件系统（v1）。`data/works/{work_id}/` 存 raw.txt, graph.json, graph.html, summary.json, status.json。无数据库，后续可换 SQLite / 对象存储。

---

## 7. 前端（React + Vite + vis-network）

- **首页 `/`**：拖拽上传区（.txt/.epub + 档位选择 quick/complete）+ 已处理作品列表。
- **处理页 `/works/{id}/processing`**：进度条 + 阶段文字；轮询 status；done 时自动跳转阅读页。
- **阅读页 `/works/{id}`（核心，Tab 布局）**：
  - **[概览]** 一句话 → 概述 → 主角卡片（god_nodes）= 「30 分钟读懂」入口
  - **[故事脉络]** 按聚类情节线(arcs)展开的分层摘要，可下钻章节摘要
  - **[人物关系]** vis-network 渲染 graph.json，按关系类别着色 + 图例；点节点 → 人物卡，点边 → 关系详情 + 证据
  - **[设定卡]** 主题/世界观卡片流
  - graphify 的 graph.html 作为「完整图谱」在新窗口打开

---

## 8. 错误处理与测试

### 错误处理
- 上传校验扩展名/大小；epub 解析失败 → 明确报错。
- 单块提取重试（指数退避）→ 跳过并记录到 status.json warnings，不中断整个任务。
- Bedrock 限流 → 信号量并发 + 退避。
- 任务级失败 → status.phase=failed + error 字段，前端显示重试。

### 测试
- 单元：分块（章节切分/token 分块）、合并去重（同名 + 别名表 + 相似名归一化）、Pydantic 校验。
- 集成：小段 mock 文本走完整管道（mock Strands 输出）→ 断言 graph.json + summary.json 合法。
- e2e：短篇公版小说走真实 Bedrock，人工验证主角/主线关系。
- 前端：阅读组件渲染测试 + 轮询状态机测试。

---

## 9. 目录结构（本 demo）

```
30mins_demo/
  backend/          FastAPI 应用 + 摄取管道 + 提取层 + graphify 集成
  frontend/         React + Vite + vis-network
  data/works/       运行时产出（gitignore）
  docs/             本设计文档
```
