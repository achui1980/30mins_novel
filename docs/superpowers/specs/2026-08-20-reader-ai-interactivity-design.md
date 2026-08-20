# 沉浸式阅读器 + AI↔原文双向联动 — 设计文档

> 目标：把现有的"章节手风琴"原文 Tab 升级为一个真正的连续滚动小说阅读器（目录/字号/日夜模式/
> 阅读进度记忆），并让 AI 分析结果（人物关系证据、时间轴事件、图谱边）与原文之间建立**双向**
> 联动：原文中的人名可弹出 AI 卡片；AI 分析的"证据"文本可以精准跳转并高亮原文中的具体段落
> （而不是像现在一样只能跳到整章）。同时新增"选中原文问 AI"能力。

日期：2026-08-20
状态：设计已批准，待实施
关联文档：`2026-07-27-novel-knowledge-graph-design.md`（总体架构与数据模型基础）、
`2026-08-09-raw-text-view-design.md`（当前"原文"Tab 的手风琴实现，本设计将其重构）

---

## 1. 背景与现状

- 原文已完整持久化：解析阶段落盘 `raw.txt`（完整原文）与 `chapters.json`
  （`{chapter_id: {title, text}}`，`backend/app/pipeline/orchestrator.py:80-87`），可寻址粒度
  仅到**整章**（`chapter_id`，形如 `ch0001`）。全代码库不存在任何段落级/句子级 id、偏移量或
  高亮基础设施。
- 当前"原文"Tab（`frontend/src/components/tabs/RawTextTab.jsx`，119 行）是章节手风琴：右栏
  目录 + 主区逐章展开，展开时才调用 `GET /works/{id}/chapters/{chapter_id}/text`
  （`backend/app/routes.py:158-173`）懒加载该章 `{chapter_id, title, text}`（纯文本，
  `whitespace-pre-wrap` 渲染）。跨 Tab 跳转仅有一种现成模式：`TimelineTab` 的"查看原文→"按钮
  （`TimelineTab.jsx:80-86`）通过 `ReaderPage.jsx:56-59` 的 `viewChapter(chapterId)` 设置
  `rawJump={chapterId, nonce}`，`RawTextTab.jsx:65-76` 用 `nonce` 去重展开+滚动到该章节
  （章级粒度，无法定位到章内具体位置）。
- `backend/app/models.py` 中 `Relationship`（84-90 行）已有 `evidence: str` 字段（"支持该关系
  的原文证据/摘录"），抽取 prompt（`extract.py:29-39` `SYSTEM_PROMPT`）要求 LLM 给出，
  fake-LLM 离线模式（`extract.py:124`）直接取 `block.text[:40]`（block 文本的精确子串）。但
  `Relationship` 模型本身**不带章节信息**，`merge.py` 的 `EntityRegistry.add_relationship`
  （142-171 行）虽然调用方 `add_extraction`（173-188 行）作用域内已经有 `chapter_id`（events
  已经在用，184 行 `"chapter": e.chapter or chapter_id`），却**没有把它传给
  `add_relationship`**——关系记录完全不知道自己来自哪一章，这是本设计要打通的第一个断点。
- `Event`（`models.py:66-72`）目前只有 `summary`（LLM 一句话概括，是**改写**不是原文）+
  `chapter`（已知）+ `participants`/`order_hint`，**没有任何原文证据/引用字段**——`summary` 是
  paraphrase，不能直接拿去和原文做模糊匹配定位。
- `backend/app/pipeline/graph.py` 的 `build_extraction_json`（50-154 行）给**节点**写了一个
  目前完全未使用的空字段 `"source_location": ""`（87、103 行），但**边（edges，131-145 行）
  没有这个字段**——之前排查认为边上已有可复用的空字段，实测并不成立，本设计需要给边**新增**
  该字段（字段名沿用 `source_location` 以保持节点/边命名一致，即便节点侧目前仍是未使用的占位）。
- `GraphTab.jsx`（132-147 行）的边详情面板目前只展示 `category`/`detail`/`evidence` 文字，
  **没有任何跳转到原文的按钮**——这是全新增的联动能力，不是现有功能的增强。
- 单本小说规模：实测约 30-60 万字、100+ 章（如《三国演义》109 章、59.6 万字），因此阅读器
  和定位机制都必须是"按需/懒加载"，绝不能一次性把全书渲染进 DOM 或一次性跑全文模糊匹配。
- 前端无用户账号体系（单用户 Demo），全代码库目前**没有任何 `localStorage` 用法**——阅读进度、
  字号、日夜模式偏好是本设计里第一次引入客户端本地持久化，选型上直接用 `localStorage`
  即可，不需要引入账号/后端存储。
- 旧作品（该功能上线前已处理完成的书）不做回填/重跑：旧数据里关系记录完全没有章节归属信息，
  必须重新跑一次 LLM 抽取才能补上，成本不对等；用户已明确认可"旧书保持现状（只能跳整章甚至
  跳不了），新书才享受精准定位"这一降级策略，不是待解决的问题，是明确的产品决策。

## 2. 总体架构

不引入新的持久化格式（`chapters.json` 仍是整章文本字符串，不改成段落数组落盘），而是新增
**唯一的规范分段函数** `split_paragraphs()`（后端），供两处共用：

1. 流水线里的"定位"步骤——把关系证据 / 事件证据 quote 解析成 `(chapter_id, paragraph_index)`；
2. `GET /works/{id}/chapters/{chapter_id}/text` 接口——把整章文本切成段落数组返回给前端。

这样前端永远不用自己实现分段逻辑，也就不存在"前端分段结果和后端定位时用的分段结果不一致"
的风险（对比过的另一方案是前端独立实现一份切段逻辑、后端各跑各的，一旦两边切分规则出现哪怕
一个字符的差异，`paragraph_index` 就会错位、高亮跳到错误段落——判断该风险不可接受，故排除）。

整体拆成四块，互相独立、可分别验证：

1. **后端定位流水线**：`Event` 新增证据字段 → `merge.py` 打通关系的章节归属 → 新模块
   `locate.py`（唯一分段函数 + 证据定位函数）→ `orchestrator.py` 里新增一步，跑完抽取/建图后
   把结果回填进 `graph.json` 的边和 `events.json` 的事件。
2. **原文→AI 卡片**（纯前端，零新增接口）：阅读器渲染时，用已经加载好的 `graph.json` 节点
   （人物/地点及其别名）构造一次性的名字匹配，包出 `<span>` 高亮，点击/悬停弹出身份+关系卡片。
3. **AI→原文精准跳转**：泛化现有的 `rawJump={chapterId, nonce}` 为
   `{chapterId, paragraphIndex, nonce}`；时间轴事件、人物关系详情、图谱边详情三处"查看原文"
   入口，有 `paragraph_index`/`source_location` 就带上，没有就退化成今天的整章跳转（同一套
   跳转逻辑自然覆盖新书精确跳转和旧书/未匹配数据的整章兜底，不需要任何特殊分支判断"是不是旧书"）。
4. **选中原文问 AI**（纯前端，零新增接口）：阅读器区域监听文本选中，出现"就这段问 AI"悬浮按钮，
   点击后复用已有的 `askSeed`/`seed.nonce` 跳转模式带着选中原文切到问答 Tab。

## 3. 后端改动

### 3.1 `models.py`：`Event` 增加 `evidence` 字段

在 `Event`（66-72 行）里新增一个字段，写法与 `Relationship.evidence`（89 行）完全一致：

```python
class Event(BaseModel):
    summary: str = Field(description="事件的一句话概述")
    chapter: Optional[str] = Field(default=None, description="所属章节标识")
    participants: list[str] = Field(default_factory=list, description="参与角色姓名")
    order_hint: Optional[int] = Field(
        default=None, description="事件在全书中的粗略先后顺序，用于未来时间线"
    )
    evidence: str = Field(default="", description="支持该事件的原文证据/摘录（若能提供）")
    ...
```

`TimelineEvent`（166-174 行）同步新增 `paragraph_index: Optional[int] = None`（供定位结果
携带给前端；`None` 表示未匹配到，前端据此判断是否降级为整章跳转）。

`ChapterText`（128-133 行）把 `text: str` 换成 `paragraphs: list[str]`——这是本设计**唯一**
的破坏性接口变更（见 §3.5），可接受，因为这是单前端消费者的 Demo 应用，没有版本兼容负担。

### 3.2 `extract.py`：让 LLM / fake 抽取器产出事件证据

- `SYSTEM_PROMPT`（29-39 行）在"关系必须给出简短 detail 与原文 evidence"那条之后加一句：
  "事件如能对应到原文中的具体句子，请同样给出简短 evidence 原文摘录；无法确定就留空，不要
  编造。"——故意允许留空，不强制，因为不是每个事件都能精确对应一句原文。
- `fake_extract_block`（81-138 行）离线确定性抽取器，构造 `Event` 时（128-137 行）加上
  `evidence=block.text[:40]`，与同一函数里关系抽取的写法（124 行）保持一致，确保离线/测试
  路径下事件证据永远是 block 文本的精确子串，定位时走精确匹配即可命中。

### 3.3 `merge.py`：把 `chapter_id` 打通到关系记录

`RelationRecord`（60-68 行）新增字段：

```python
@dataclass
class RelationRecord:
    source: str
    target: str
    category: str
    detail: str = ""
    evidence: str = ""
    confidence: float = 0.0
    count: int = 0
    chapter_id: str = ""
```

`add_relationship`（142-171 行）签名改为 `add_relationship(self, rel: Relationship,
chapter_id: str = "") -> None`：

- 新建记录时（161-165 行）传入 `chapter_id=chapter_id`；
- "最长 evidence 获胜"那段（170-171 行）里，evidence 更新的同时同步更新 chapter_id，保证
  `chapter_id` 永远和当前胜出的 `evidence` 出自同一章：
  ```python
  if len(rel.evidence) > len(rec.evidence):
      rec.evidence = rel.evidence
      rec.chapter_id = chapter_id
  ```

`add_extraction`（173-188 行）调用处改为 `self.add_relationship(r, chapter_id)`（原来是
`self.add_relationship(r)`，`chapter_id` 参数在该函数作用域内本来就存在，只是没往下传）。事件
字典（181-188 行）同步加一行 `"evidence": e.evidence`。

跨弧合并两处也要保持 `chapter_id` 语义一致（否则合并后的关系记录会丢失/张冠李戴章节归属）：

- `merge_arcs`（366-408 行）里把各弧的 `RelationRecord` 重新灌回 `merged.add_relationship`
  的地方（377-380 行），补上 `chapter_id=rel.chapter_id`：
  ```python
  for rel in arc.relationships.values():
      merged.add_relationship(
          Relationship(source=rel.source, target=rel.target, category=rel.category,
                       detail=rel.detail, evidence=rel.evidence, confidence=rel.confidence),
          chapter_id=rel.chapter_id,
      )
  ```
- `_apply_merge`（317-362 行）合并同一人物的不同别名记录时，直接构造/更新 `RelationRecord`
  （不经过 `add_relationship`）：新建分支（352-354 行）补上 `chapter_id=rec.chapter_id`；更新
  分支里 evidence 更新那行（360-361 行）同样同步 `chapter_id`：
  ```python
  if len(rec.evidence) > len(old.evidence):
      old.evidence = rec.evidence
      old.chapter_id = rec.chapter_id
  ```

### 3.4 新模块 `backend/app/pipeline/locate.py`

唯一的分段实现 + 证据定位，供 `routes.py`（接口）和 `orchestrator.py`（定位流水线步骤）共用：

```python
"""Evidence-to-paragraph locating.

Resolves a short evidence/quote string (Relationship.evidence or
Event.evidence) to a paragraph index within its chapter, so the reader can
scroll to and highlight the exact paragraph instead of only the chapter.
Best-effort: returns None on low confidence — callers MUST treat that as
"fall back to chapter-level jump", not as an error.
"""
from __future__ import annotations

import difflib
import json
import re

_PARA_SPLIT_RE = re.compile(r"\n\s*\n+")  # blank-line-delimited paragraphs
FUZZY_MATCH_THRESHOLD = 0.6


def split_paragraphs(text: str) -> list[str]:
    """The one canonical chapter-text -> paragraph-list splitter.

    Falls back to single '\\n' splitting when a chapter has no blank-line
    breaks (some EPUB sources), and to a single-element list when there are
    no line breaks at all — the reader still renders correctly, just without
    finer-grained paragraph highlighting for that chapter.
    """
    if not text or not text.strip():
        return []
    parts = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    if len(parts) > 1:
        return parts
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    return parts or [text.strip()]


def locate_paragraph(paragraphs: list[str], quote: str) -> int | None:
    """Index of the paragraph that best contains `quote`, or None.

    1. Exact substring match first (fake-LLM evidence is always a literal
       substring; real-LLM evidence usually is too).
    2. Fallback: difflib ratio against each whole paragraph, threshold-gated.
    """
    quote = (quote or "").strip()
    if not quote or not paragraphs:
        return None
    for i, p in enumerate(paragraphs):
        if quote in p:
            return i
    best_idx, best_ratio = None, 0.0
    for i, p in enumerate(paragraphs):
        ratio = difflib.SequenceMatcher(None, quote, p).ratio()
        if ratio > best_ratio:
            best_ratio, best_idx = ratio, i
    return best_idx if best_idx is not None and best_ratio >= FUZZY_MATCH_THRESHOLD else None


def resolve_source_location(
    chapter_id: str | None, quote: str, paragraphs_by_chapter: dict[str, list[str]]
) -> str:
    """`"{chapter_id}"` or `"{chapter_id}#p{index}"`, or `""` if chapter_id is
    unknown. Always returns at least the chapter_id when known, so the
    frontend can fall back to a chapter-level jump even when the paragraph
    match misses."""
    chapter_id = chapter_id or ""
    if not chapter_id:
        return ""
    idx = locate_paragraph(paragraphs_by_chapter.get(chapter_id, []), quote)
    return f"{chapter_id}#p{idx}" if idx is not None else chapter_id


def patch_graph_edge_locations(
    graph_json_path, registry, label_to_id: dict, paragraphs_by_chapter: dict[str, list[str]]
) -> None:
    """Patch graph.json's edges in place with resolved `source_location`.

    Matches edges back to `registry.relationships` via (source_node_id,
    target_node_id, category) — graph.json edges only carry node ids, not
    canonical character names, so `label_to_id` (from GraphArtifacts) is the
    bridge. Edges whose relationship can't be resolved (should not normally
    happen) are left untouched.
    """
    data = json.loads(graph_json_path.read_text(encoding="utf-8"))
    edge_list = data.get("links") if data.get("links") is not None else data.get("edges", [])
    loc_by_pair: dict[tuple[str, str, str], str] = {}
    for rec in registry.relationships.values():
        sid, tid = label_to_id.get(rec.source), label_to_id.get(rec.target)
        if sid is None or tid is None:
            continue
        loc_by_pair[(sid, tid, rec.category)] = resolve_source_location(
            rec.chapter_id, rec.evidence, paragraphs_by_chapter
        )
    for edge in edge_list:
        key = (edge.get("source"), edge.get("target"), edge.get("category") or edge.get("relation"))
        loc = loc_by_pair.get(key)
        if loc:
            edge["source_location"] = loc
    graph_json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
```

### 3.5 `graph.py`：边新增 `source_location` 占位字段

`build_extraction_json`（108-145 行）的 `edges.append({...})` 里加一行
`"source_location": ""`（和节点侧 87/103 行的占位字段同名，保持 schema 一致性），构建时永远
是空字符串，由 §3.6 的定位步骤事后回填——`graph.py` 本身不需要知道 `chapter_id`，也不需要
引入 `locate.py` 依赖，保持这个模块只管"抽取结果 → graphify 格式"的单一职责。

### 3.6 `orchestrator.py`：新增定位步骤

在现有解析阶段（80-87 行，`chapters_payload` 构建完毕）之后，就地算出一次全书的分段结果，供
本次运行内两处复用：

```python
from .locate import patch_graph_edge_locations, split_paragraphs, locate_paragraph
...
paragraphs_by_chapter = {
    cid: split_paragraphs(v.get("text") or "") for cid, v in chapters_payload.items()
}
```

"持久化事件"这一步（129-133 行，紧跟抽取完成之后）在写盘前补上段落定位（此时
`paragraphs_by_chapter` 已经可用）：

```python
for e in registry.events:
    e["paragraph_index"] = locate_paragraph(
        paragraphs_by_chapter.get(e.get("chapter") or "", []), e.get("evidence") or ""
    )
(config.work_dir(work_id) / "events.json").write_text(
    json.dumps(registry.events, ensure_ascii=False), encoding="utf-8"
)
```

建图完成后（`artifacts = run_graphify(...)`，145-150 行之后）补一步，回填 `graph.json` 边上的
`source_location`：

```python
patch_graph_edge_locations(graph_json, registry, artifacts.label_to_id, paragraphs_by_chapter)
```

两步都是"读已有内存数据 + 写一次 JSON"，不引入新的失败模式：`locate_paragraph` 内部永不抛异常
（找不到就返回 `None`），`patch_graph_edge_locations` 对无法匹配的边直接跳过而不是报错。即便
这两步整体失败（理论上不应该，但为防御起见），也应包在现有 `try/except` 之内（本来就整段包在
`run_pipeline` 的大 `try` 里，见 196-210 行），失败只会体现为"这次跑的定位信息缺失"，绝不会
让整个 pipeline 状态变成 `failed`——这一属性通过把两步都放在现有大 `try` 块内部即可自然获得，
不需要额外包裹。

### 3.7 API 改动

| 接口 | 变化 |
|---|---|
| `GET /works/{id}/chapters/{chapter_id}/text` | 响应体从 `{chapter_id, title, text}` 变为 `{chapter_id, title, paragraphs: [str]}`（`routes.py:158-173`，用 `split_paragraphs(chapter.get("text") or "")` 生成；需新增 `from .pipeline.locate import split_paragraphs` 导入）。**唯一破坏性变更。** |
| `GET /works/{id}/graph` | 接口本身不变，边多了一个可能非空的 `source_location` 字段。 |
| `GET /works/{id}/timeline` | 接口本身不变，事件多了一个可能非空的 `paragraph_index` 字段（`timeline.py:61-69` 的 `TimelineEvent(...)` 构造加上 `paragraph_index=e.get("paragraph_index")`）。 |
| 人名高亮、选文本问 AI | **零新增接口**——分别复用已经在拉取的 `/works/{id}/graph`（节点別名）和已有的 `POST /works/{id}/ask`。 |

## 4. 前端改动

### 4.1 `RawTextTab.jsx`：手风琴 → 连续滚动阅读器

彻底重写这个组件（119 行手风琴逻辑整体替换），核心结构：

- 右栏仍是章节目录（复用现有 `setRight` 模式），但点击目录项改为"平滑滚动到该章节的锚点
  `<div id="ch-{chapterId}">`"，而不是"展开手风琴项"。
- 主区渲染全部章节的**容器**（章节标题 + 段落占位），但章节正文**不是一次性全部拉取**：给
  每个章节容器包一个 `IntersectionObserver`（`rootMargin` 提前量，比如 `"200px"`），当章节
  容器进入（或即将进入）可视区域才调用 `getChapterText(id, chapterId)` 拉取该章
  `{paragraphs}` 并渲染；已拉取过的章节缓存在 state 里，滚出视口不卸载内容（简单起见不做虚拟
  滚动/回收，Demo 规模的内存占用可接受，若某章已经拉取过就不会重复请求）。这是"滚动懒加载"对
  "点击展开懒加载"（`raw-text-view-design.md` §2.4 原有模式）的直接替代，同样满足"不能一次性
  把全书塞进 DOM/网络请求"的约束——区别只是触发时机从"点击"变成"滚动到附近"。
- 每个段落渲染为 `<p id="p-{chapterId}-{index}" data-chapter={chapterId} data-para={index}>`，
  这个 `id` 就是全部精准跳转/高亮功能的锚点。

### 4.2 工具条：字号 + 日夜模式

阅读器顶部新增一个小工具条（两个控件），状态持久化到 `localStorage`（全局偏好，不分书，因为
没有账号体系）：

- 字号：`novel_kg_reader_font_size`，5 档（14/16/18/20/22px），+/- 按钮，直接作为
  `style={{ fontSize }}` 加在段落容器上。
- 日夜模式：`novel_kg_reader_theme`，`"day" | "night"`，**只影响阅读器内容区域本身**（背景/
  文字颜色），不去改造全局 `AppShell`/侧边栏或引入 Tailwind `darkMode` 配置——用两组直接写好
  的类名切换（如 `bg-white text-ink-900` ↔ `bg-ink-900 text-paper-50`），把改动面严格限制在
  这一个组件内，不影响应用其他任何地方的视觉。

### 4.3 阅读进度记忆

用同一个 `IntersectionObserver`（4.1 里已经在用）额外承担一个职责：持续追踪"当前可视区域内最
靠上的段落"，节流写入 `localStorage`（key 按作品区分，如
`novel_kg_reader_progress_{workId}` → `{chapterId, paragraphIndex}`）。进入阅读器 Tab 时，若
该 key 存在，自动滚动到对应段落（无记录则从头开始，不做任何提示/弹窗打扰）。

### 4.4 原文→AI 卡片（人名高亮 + 悬停/点击卡片）

- `RawTextTab` 拿到已加载的 `graph.json`（`GraphTab.jsx` 已经在用 `getGraph(id)`，这里同样
  调一次，零新增接口），构建一次"规范名+别名 → 节点"的查找表（角色节点 + 地点节点）。
- 渲染每个段落文本前，用**最长匹配优先**的一次性转义正则做匹配替换（避免"李"和"李逍遥"这种
  互相包含的名字被错误地拆成两段），命中片段包成
  `<span class="entity-link" data-node-id="...">名字</span>`。
- 点击（移动端友好，优先于纯 hover）弹出一个小卡片：角色定位 `role` + 一句话 `description` +
  该角色的关系列表（关系列表数据来源与 `CharactersTab.jsx:27-34` 完全同一套逻辑——遍历
  `graph.edges`/`graph.links` 找 source/target 命中该节点的边，配上对方节点的 label——直接
  复用同一段计算逻辑抽成小工具函数即可，不需要新请求）。卡片里的关系项可点击跳转到"人物"
  Tab 对应角色（复用 `CharactersTab` 现有的按 `selectedId` 选中机制）。

### 4.5 跨 Tab 精准跳转：泛化 `rawJump`

`ReaderPage.jsx` 的 `rawJump` state（34 行）与 `viewChapter`（56-59 行）泛化：

```jsx
function viewChapter(chapterId, paragraphIndex) {
  setRawJump({ chapterId, paragraphIndex, nonce: Date.now() });
  setTab("raw");
}
```

`RawTextTab` 里原有的跳转 `useEffect`（65-76 行）在滚动到章节锚点之后，若
`jump.paragraphIndex != null`，改为精确滚动到 `#p-{chapterId}-{paragraphIndex}` 并加一个
CSS transition 短暂高亮闪烁（如 200ms 背景色过渡）；若 `paragraphIndex` 为空/未匹配，行为
与今天完全一致——只滚到章节顶部，不高亮。三处调用方按各自现有的详情数据解析
`source_location`/`paragraph_index` 并传入第二个参数：

- `TimelineTab.jsx`（82 行 `onViewChapter?.(g.chapter_id)`）——事件对象已带
  `paragraph_index`（3.7 节新增），传 `onViewChapter?.(e.chapter_id, e.paragraph_index)`（要
  改成按事件级别调用而不是按章节分组头调用，因为不同事件的段落索引不同；分组头的按钮保留但
  改为不带段落索引的整章跳转，作为"看整章"的备选，同时新增单个事件卡片内的"查看原文→"精确
  跳转按钮）。
- `CharactersTab.jsx`（右栏关系列表，51-73 行）——每条关系目前只有 `category`/对方节点，没有
  `source_location`；需要额外拉取一次 `graph.edges` 里对应边的 `source_location`（已经在
  `graph` state 里，19 行已经 `getGraph(id)` 过），关系列表项加一个"查看原文→"小按钮，样式
  同 `TimelineTab` 现有的 `hover:text-seal-600 hover:underline`（`TimelineTab.jsx:83`）。
- `GraphTab.jsx`（边详情面板，132-147 行）——`detail.data.source_location` 若非空，解析出
  `chapter_id`（`#` 前半段）和可选的 `p{n}`（`#` 后半段），渲染一个新的"查看原文→"按钮。
  `GraphTab` 目前没有拿到 `viewChapter`/切 Tab 的能力，需要从 `ReaderPage` 往下多传一个 prop
  （与 `TimelineTab` 现有的 `onViewChapter` 同名同签名）。

### 4.6 选中原文问 AI

`RawTextTab` 内容区监听 `mouseup`（简单可靠，兼容大多数浏览器，优先于 `selectionchange` 以
避免过于频繁触发）：若 `window.getSelection()` 有非空文本且选区落在阅读器容器内，在选区附近
定位一个小的悬浮按钮"就这段问 AI"；点击后，取选中文本 + 当前所在章节标题，复用现成的
`askSeed`/`nonce` 跳转模式（`ReaderPage.jsx:51-54` 的 `askAbout`，`AskTab.jsx:49-55` 的去重
触发），把 `{question: "关于这段内容：「${selectedText}」（出自${chapterTitle}），我想问：",
nonce}` 作为草稿预填到问答输入框——注意这里预填的是**输入框草稿**，不像 `askAbout` 那样自动
提交，因为选中的原文只是问题的上下文，用户还需要补充实际想问的问题；`AskTab` 需要区分"seed
question 是可直接自动提问"还是"seed 是仅预填输入框、等用户补充后手动提交"两种模式（加一个
`seed.autoSubmit` 布尔字段区分，`askAbout` 传 `true`，选文本问 AI 传 `false`）。

## 5. 边界情况 / 非目标（已达成一致，非待解决问题）

- 模糊匹配低于阈值（`locate_paragraph` 返回 `None`）→ `source_location` 只含 `chapter_id`
  （或 `paragraph_index` 为 `None`）→ 前端自动退化为整章跳转，不高亮——这就是今天的行为，
  不是新的失败模式。
- 章节没有明显的空行分段（部分 EPUB 排版）→ `split_paragraphs` 退化到按单个 `\n` 分段，再退化
  到整章作为唯一一个"段落"——阅读器仍能正常渲染，只是该章高亮定位精度较粗。
- 长章节/长篇小说 → 阅读器沿用"滚动到附近才拉取该章"的懒加载策略，任何时刻都不会把全书文本
  塞进 DOM。
- **不对旧作品做任何回填/重跑**：旧关系记录完全没有章节归属，`chapter_id` 为空字符串，
  `resolve_source_location` 直接返回 `""`，等价于"完全没有定位信息"，前端该关系/事件的
  "查看原文"入口直接不显示按钮（而不是显示一个跳转不到任何地方的死按钮）——明确的产品决策，
  非缺陷。
- 事件/关系的原文证据字段留空（LLM 没给，或 fake 抽取器某些边界情况）→ `locate_paragraph`
  对空字符串直接返回 `None`（函数开头 `if not quote or not paragraphs: return None`），同样
  走整章兜底。

## 6. 测试计划

**后端**（`backend/tests/`，遵循现有 `temp_data_root`/fake-LLM fixture 写法）：

- 新文件 `test_locate.py`：`split_paragraphs`（空行分段 / 单换行退化 / 无换行整章退化三种输入）
  ；`locate_paragraph`（精确子串命中、模糊近似命中、低于阈值返回 `None`、空 quote 返回
  `None`）；`resolve_source_location`（有章节+命中段落 → `"chXXXX#pN"`；有章节+未命中 →
  `"chXXXX"`；无章节 → `""`）。
- `test_extract.py` 补一个用例：`fake_extract_block` 产出的 `Event.evidence` 非空且是对应
  block 文本的子串。
- `test_merge.py`/`test_merge_arcs.py` 补用例：`add_relationship` 传入的 `chapter_id` 最终体现
  在 `RelationRecord.chapter_id` 上；跨弧合并（`merge_arcs`）与同名合并（`_apply_merge`）后
  `chapter_id` 依然和胜出的 `evidence` 保持一致（构造一个"更长 evidence 来自不同章节"的场景
  断言两者同步更新）。
- `test_pipeline_integration.py`（`NOVEL_KG_USE_FAKE_LLM=1` 全流程离线跑一遍）新增断言：
  产出的 `graph.json` 至少有一条边的 `source_location` 非空；`events.json` 至少有一个事件的
  `paragraph_index` 非 `None`。
- `test_routes.py` 补用例：`GET .../chapters/{id}/text` 返回体是
  `{chapter_id, title, paragraphs: [...]}` 而不是旧的 `text` 字段。

**前端**（无自动化测试框架，静态检查 + 手工验证，沿用 `raw-text-view-design.md` §4 的验收
方式）：

1. `npx vite build` 无编译错误。
2. 打开一本新处理完成（fake-LLM 或真实流水线均可）的作品，"原文"Tab 表现为连续滚动而非手风琴；
   滚动到任意章节时该章内容懒加载出现，不需要点击。
3. 字号 +/- 按钮生效，刷新页面后字号偏好保留；日夜模式切换只影响阅读器内容区域，应用其他部分
   视觉不受影响，刷新后偏好保留。
4. 阅读到某处后离开该作品再返回，自动恢复到之前的阅读位置（同一本书）；换一本书打开是从头
   开始（互不干扰）。
5. 原文中人物名字被高亮，点击弹出卡片（角色定位+描述+关系列表），点击关系列表项跳到"人物"
   Tab 对应角色。
6. 时间轴事件卡片、人物关系详情、图谱边详情三处的"查看原文→"按钮：对新书能精确跳转到具体
   段落并有短暂高亮闪烁；对旧书（或未匹配到段落的条目）没有按钮或退化为整章跳转（不崩溃、
   不报错）。
7. 在阅读器里选中一段文字，出现"就这段问 AI"悬浮按钮，点击后切到"问答"Tab，输入框已预填
   带有选中原文和章节标题的草稿文本，且**不会自动提交**（需要用户手动点击"提问"）。
</content>
