# 沉浸式阅读器 + AI↔原文互动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing chapter-accordion "原文" tab into a continuous-scroll novel reader with reading-progress/theme/font persistence, and make AI analysis results (relationship evidence, timeline events, graph edges) precisely jump-and-highlight the exact paragraph in the original text instead of only the chapter — while keeping full backward compatibility for already-processed books.

**Architecture:** A new backend module `locate.py` provides the single canonical paragraph splitter (`split_paragraphs`) and a best-effort evidence→paragraph resolver (`locate_paragraph`); the pipeline orchestrator runs a post-hoc "locate" pass after chapters/graph/events are built, patching the previously-plain `graph.json` edges with `source_location` and `events.json` entries with `paragraph_index`. The frontend generalizes its existing `rawJump={chapterId,nonce}` cross-tab mechanism to `{chapterId,paragraphIndex,nonce}`, and rewrites `RawTextTab.jsx` into an `IntersectionObserver`-driven continuous-scroll reader. Everything degrades gracefully: unresolved/old-book items simply omit the "查看原文→" button or fall back to chapter-only jump — never an error.

**Tech Stack:** FastAPI + Pydantic (backend), React 18 + Vite (frontend), pytest (backend tests), no frontend test framework (manual verification), `difflib` for fuzzy text matching, browser `IntersectionObserver`/`localStorage` (native, no new deps).

---

## Backend Tasks

### Task 1: `locate.py` — canonical paragraph splitter + evidence locator

**Files:**
- Create: `backend/app/pipeline/locate.py`
- Test: `backend/tests/test_locate.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_locate.py`:

```python
from app.pipeline.locate import (
    locate_paragraph,
    resolve_source_location,
    split_paragraphs,
)


def test_split_paragraphs_blank_line_delimited():
    text = "第一段第一句。第一段第二句。\n\n第二段内容。\n\n第三段内容。"
    assert split_paragraphs(text) == ["第一段第一句。第一段第二句。", "第二段内容。", "第三段内容。"]


def test_split_paragraphs_falls_back_to_single_newline():
    text = "第一行内容。\n第二行内容。\n第三行内容。"
    assert split_paragraphs(text) == ["第一行内容。", "第二行内容。", "第三行内容。"]


def test_split_paragraphs_falls_back_to_whole_chapter():
    text = "没有任何换行的一整段文字内容。"
    assert split_paragraphs(text) == ["没有任何换行的一整段文字内容。"]


def test_split_paragraphs_empty_text():
    assert split_paragraphs("") == []
    assert split_paragraphs("   \n\n  ") == []


def test_locate_paragraph_exact_substring_match():
    paragraphs = ["贾宝玉在园中读书。", "林黑玉忽然到来，两人相谈甚欢。", "夜幕降临，众人散去。"]
    assert locate_paragraph(paragraphs, "林黑玉忽然到来") == 1


def test_locate_paragraph_fuzzy_near_match():
    paragraphs = ["贾宝玉在园中读书写字。", "林黑玉忽然到来，两人相谈甚欢，情投意合。", "夜幕降临，众人散去。"]
    # Slightly reworded quote (near, not exact) should still resolve via difflib.
    assert locate_paragraph(paragraphs, "林黑玉忽然到来两人相谈甚欢情投意合") == 1


def test_locate_paragraph_below_threshold_returns_none():
    paragraphs = ["贾宝玉在园中读书。", "林黑玉忽然到来。"]
    assert locate_paragraph(paragraphs, "完全不相关的一句话内容") is None


def test_locate_paragraph_empty_quote_or_paragraphs_returns_none():
    assert locate_paragraph(["有内容的段落。"], "") is None
    assert locate_paragraph([], "任意引用") is None


def test_resolve_source_location_with_matched_paragraph():
    paragraphs_by_chapter = {"ch0001": ["贾宝玉在园中读书。", "林黑玉忽然到来。"]}
    loc = resolve_source_location("ch0001", "林黑玉忽然到来", paragraphs_by_chapter)
    assert loc == "ch0001#p1"


def test_resolve_source_location_with_unmatched_paragraph_falls_back_to_chapter():
    paragraphs_by_chapter = {"ch0001": ["贾宝玉在园中读书。"]}
    loc = resolve_source_location("ch0001", "完全不相关的内容", paragraphs_by_chapter)
    assert loc == "ch0001"


def test_resolve_source_location_with_no_chapter_returns_empty_string():
    assert resolve_source_location("", "任意引用", {}) == ""
    assert resolve_source_location(None, "任意引用", {}) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. pytest tests/test_locate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.locate'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/pipeline/locate.py`:

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_locate.py -v`
Expected: PASS (all 11 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/locate.py backend/tests/test_locate.py
git commit -m "feat: add locate.py for evidence-to-paragraph resolution"
```

---

### Task 2: `models.py` — `Event.evidence`, `TimelineEvent.paragraph_index`, `ChapterText.paragraphs`

**Files:**
- Modify: `backend/app/models.py:66-81` (Event), `backend/app/models.py:128-133` (ChapterText), `backend/app/models.py:166-174` (TimelineEvent)
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_models.py` (append at end of file):

```python
def test_event_has_optional_evidence_field():
    from app.models import Event

    e = Event(summary="收徒", chapter="ch0001", participants=["贾宝玉"])
    assert e.evidence == ""
    e2 = Event(summary="收徒", chapter="ch0001", evidence="贾宝玉收林黑玉为徒。")
    assert e2.evidence == "贾宝玉收林黑玉为徒。"


def test_timeline_event_has_optional_paragraph_index():
    from app.models import TimelineEvent

    t = TimelineEvent(seq=1, chapter_id="ch0001", chapter_title="第一章", summary="相遇")
    assert t.paragraph_index is None
    t2 = TimelineEvent(seq=1, chapter_id="ch0001", chapter_title="第一章", summary="相遇", paragraph_index=3)
    assert t2.paragraph_index == 3


def test_chapter_text_uses_paragraphs_list():
    from app.models import ChapterText

    c = ChapterText(chapter_id="ch0001", title="第一章", paragraphs=["第一段。", "第二段。"])
    assert c.paragraphs == ["第一段。", "第二段。"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. pytest tests/test_models.py -v -k "evidence or paragraph_index or paragraphs_list"`
Expected: FAIL — `Event`/`TimelineEvent` reject unexpected `evidence`/`paragraph_index` kwargs (or `ChapterText` rejects `paragraphs` kwarg / has no such field), depending on Pydantic strictness — at minimum `test_chapter_text_uses_paragraphs_list` fails since `ChapterText` has no `paragraphs` field yet.

- [ ] **Step 3: Write the implementation**

In `backend/app/models.py`, locate the `Event` model (lines 66-81) and add the new field right after `order_hint`, before the validator:

```python
class Event(BaseModel):
    summary: str
    chapter: str = ""
    participants: list[str] = Field(default_factory=list)
    order_hint: int = 0
    evidence: str = Field(default="", description="支持该事件的原文证据/摘录（若能提供）")

    @field_validator("chapter", mode="before")
    @classmethod
    def _coerce_chapter_to_str(cls, v):
        ...
```

(Only the new `evidence` line is added; the rest of the class body is unchanged.)

Locate `ChapterText` (lines 128-133) and change the `text` field to `paragraphs`:

```python
class ChapterText(BaseModel):
    """Full persisted source text for one chapter (原文 tab)."""

    chapter_id: str
    title: str = ""
    paragraphs: list[str] = Field(default_factory=list)
```

Locate `TimelineEvent` (lines 166-174) and add `paragraph_index` after `participants`:

```python
class TimelineEvent(BaseModel):
    seq: int
    chapter_id: str
    chapter_title: str = ""
    summary: str
    participants: list[str] = Field(default_factory=list)
    paragraph_index: int | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_models.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add Event.evidence, TimelineEvent.paragraph_index, ChapterText.paragraphs"
```

---

### Task 3: `extract.py` — request event evidence from LLM + fake extractor

**Files:**
- Modify: `backend/app/pipeline/extract.py:29-39` (SYSTEM_PROMPT), `backend/app/pipeline/extract.py:130-137` (fake_extract_block Event construction)
- Test: `backend/tests/test_extract.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_extract.py` (append at end of file, reusing existing `_block`/`SAMPLE_TEXT` helpers already defined in that file):

```python
def test_fake_extract_block_events_have_evidence_substring():
    ext = fake_extract_block(_block(SAMPLE_TEXT))
    assert ext.events, "fake extraction should produce at least one event"
    for event in ext.events:
        assert event.evidence, "event evidence should not be empty"
        assert event.evidence in SAMPLE_TEXT


def test_system_prompt_mentions_event_evidence():
    assert "事件" in SYSTEM_PROMPT and "evidence" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_extract.py -v -k evidence`
Expected: FAIL — `event.evidence` raises `AttributeError` (field doesn't exist on `Event` yet in this task's context... actually it exists from Task 2) — more precisely: `assert event.evidence` fails because `fake_extract_block` never sets it, so it's `""` (falsy), failing the `assert event.evidence` line.

- [ ] **Step 3: Write the implementation**

In `backend/app/pipeline/extract.py`, locate `SYSTEM_PROMPT` (lines 29-39) and add one sentence immediately after the existing relationship-evidence instruction (after line 37, before the no-fabrication line):

```python
SYSTEM_PROMPT = (
    ...
    "- 关系必须给出简短 detail 与原文 evidence，并估计 confidence(0-1)。\n"
    "- 若能找到支持该事件的原文片段，请在事件的 evidence 字段中给出简短摘录；找不到可留空，不要编造。\n"
    "- 只抽取文中明确出现或强烈暗示的信息，不要编造。"
)
```

Locate `fake_extract_block`'s `Event(...)` construction (lines 130-137) and add `evidence=block.text[:40]`, mirroring the existing relationship evidence pattern at line 124:

```python
    events.append(
        Event(
            summary=f"{block.chapter_title}中，{top[0]}相关的情节",
            chapter=block.chapter_id,
            participants=top[:3],
            order_hint=block.order,
            evidence=block.text[:40],
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_extract.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/extract.py backend/tests/test_extract.py
git commit -m "feat: request event evidence from LLM and populate it in fake extractor"
```

---

### Task 4: `merge.py` — thread `chapter_id` through relationships

**Files:**
- Modify: `backend/app/pipeline/merge.py:60-68` (RelationRecord), `:142-171` (add_relationship), `:173-188` (add_extraction), `:317-362` (_apply_merge), `:366-408` (merge_arcs)
- Test: `backend/tests/test_merge.py`, `backend/tests/test_merge_arcs.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_merge.py` (append at end of file):

```python
def test_add_relationship_records_chapter_id():
    reg = EntityRegistry()
    reg.add_relationship(
        Relationship(source="贾宝玉", target="林黑玉", category=RelationCategory.LOVER, evidence="短证据", confidence=0.7),
        chapter_id="ch0001",
    )
    rec = next(iter(reg.relationships.values()))
    assert rec.chapter_id == "ch0001"


def test_add_relationship_chapter_id_follows_longest_evidence():
    reg = EntityRegistry()
    reg.add_relationship(
        Relationship(source="贾宝玉", target="林黑玉", category=RelationCategory.LOVER, evidence="短", confidence=0.5),
        chapter_id="ch0001",
    )
    reg.add_relationship(
        Relationship(source="贾宝玉", target="林黑玉", category=RelationCategory.LOVER, evidence="这是一段更长的原文证据摘录", confidence=0.6),
        chapter_id="ch0002",
    )
    rec = next(iter(reg.relationships.values()))
    assert rec.evidence == "这是一段更长的原文证据摘录"
    assert rec.chapter_id == "ch0002"


def test_add_extraction_threads_chapter_id_into_relationships():
    ext = ChunkExtraction(
        characters=[Character(name="贾宝玉"), Character(name="林黑玉")],
        relationships=[
            Relationship(source="贾宝玉", target="林黑玉", category=RelationCategory.LOVER, evidence="证据文本")
        ],
    )
    reg = EntityRegistry()
    reg.add_extraction(ext, chapter_id="ch0003")
    rec = next(iter(reg.relationships.values()))
    assert rec.chapter_id == "ch0003"
```

Add to `backend/tests/test_merge_arcs.py` (append at end of file):

```python
def test_merge_arcs_preserves_chapter_id_with_longest_evidence():
    a = _arc(["贾宝玉", "林黑玉"])
    a.add_relationship(
        Relationship(source="贾宝玉", target="林黑玉", category="爱人", evidence="短", confidence=0.5),
        chapter_id="ch0001",
    )
    b = _arc(["贾宝玉", "林黑玉"])
    b.add_relationship(
        Relationship(source="贾宝玉", target="林黑玉", category="爱人", evidence="更长的一段原文证据", confidence=0.6),
        chapter_id="ch0002",
    )
    merged = merge_arcs([a, b], confirm=False)
    key = (min("贾宝玉", "林黑玉"), max("贾宝玉", "林黑玉"), "爱人")
    rec = merged.relationships[key]
    assert rec.evidence == "更长的一段原文证据"
    assert rec.chapter_id == "ch0002"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && PYTHONPATH=. pytest tests/test_merge.py tests/test_merge_arcs.py -v -k "chapter_id"`
Expected: FAIL — `add_relationship()` raises `TypeError: add_relationship() got an unexpected keyword argument 'chapter_id'`, and `rec.chapter_id` raises `AttributeError` on `RelationRecord`.

- [ ] **Step 3: Write the implementation**

In `backend/app/pipeline/merge.py`, add a `chapter_id` field to `RelationRecord` (lines 60-68), as a new line after `count: int = 0`:

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

Change `add_relationship`'s signature (line 142) and body (new-record branch 160-165, evidence-wins branch 170-171):

```python
    def add_relationship(self, rel: Relationship, chapter_id: str = "") -> None:
        ...
        if rec is None:
            rec = RelationRecord(
                source=src,
                target=tgt,
                category=category,
                detail=rel.detail,
                evidence=rel.evidence,
                confidence=rel.confidence,
                chapter_id=chapter_id,
            )
            ...
        else:
            ...
            if len(rel.evidence) > len(rec.evidence):
                rec.evidence = rel.evidence
                rec.chapter_id = chapter_id
```

Change `add_extraction`'s relationship loop (line 179) to pass `chapter_id`, and add an `"evidence"` key to the event dict (within lines 181-188):

```python
        for r in extraction.relationships:
            self.add_relationship(r, chapter_id)
        ...
        self.events.append(
            {
                "summary": e.summary,
                "chapter": e.chapter or chapter_id,
                "participants": e.participants,
                "order_hint": e.order_hint,
                "evidence": e.evidence,
            }
        )
```

Change `_apply_merge`'s new-record branch (lines 351-354) and evidence-sync branch (lines 358-361):

```python
        if old is None:
            new_rels[key] = RelationRecord(
                source=ns,
                target=nt,
                category=cat,
                detail=rec.detail,
                evidence=rec.evidence,
                confidence=rec.confidence,
                count=rec.count,
                chapter_id=rec.chapter_id,
            )
        else:
            ...
            if len(rec.evidence) > len(old.evidence):
                old.evidence = rec.evidence
                old.chapter_id = rec.chapter_id
```

Change `merge_arcs`'s relationship-rebuild loop (lines 377-380):

```python
        for rel in arc.relationships.values():
            merged.add_relationship(
                Relationship(
                    source=rel.source,
                    target=rel.target,
                    category=rel.category,
                    detail=rel.detail,
                    evidence=rel.evidence,
                    confidence=rel.confidence,
                ),
                chapter_id=rel.chapter_id,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_merge.py tests/test_merge_arcs.py -v`
Expected: PASS (all tests, including the 4 new ones, and all pre-existing tests still pass since `chapter_id` defaults to `""` everywhere it isn't explicitly passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/merge.py backend/tests/test_merge.py backend/tests/test_merge_arcs.py
git commit -m "feat: thread chapter_id through relationship merging"
```

---

### Task 5: `graph.py` — add `source_location` field to edges

**Files:**
- Modify: `backend/app/pipeline/graph.py:131-145` (edge dict construction)
- Test: `backend/tests/test_graph.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_graph.py` (append at end of file):

```python
def test_edges_have_empty_source_location_placeholder():
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉"))
    reg.add_character(Character(name="林黑玉"))
    reg.add_relationship(Relationship(source="贾宝玉", target="林黑玉", category="爱人", confidence=0.7))
    extraction, _name_to_id, _id_to_name = build_extraction_json(reg)
    edges = extraction["edges"] if "edges" in extraction else extraction["links"]
    assert edges, "expected at least one edge"
    for edge in edges:
        assert edge["source_location"] == ""
```

(Note: `Character`/`Relationship` must be imported in this test file — add `from app.models import Character, Relationship` to the existing import block if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_graph.py -v -k source_location`
Expected: FAIL — `KeyError: 'source_location'`

- [ ] **Step 3: Write the implementation**

In `backend/app/pipeline/graph.py`, locate the edge dict construction (lines 131-145) and add a new `"source_location": ""` key after the existing `"weight"` key:

```python
        edges.append(
            {
                "source": ...,
                "target": ...,
                "relation": ...,
                "category": ...,
                "detail": ...,
                "evidence": ...,
                "confidence": ...,
                "confidence_score": ...,
                "confidence_label": ...,
                "directed": ...,
                "weight": max(1, rec.count),
                "source_location": "",
            }
        )
```

(Only the new `"source_location": ""` line is added; every other key/value in this dict literal is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_graph.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/graph.py backend/tests/test_graph.py
git commit -m "feat: add empty source_location placeholder to graph edges"
```

---

### Task 6: `timeline.py` — thread `paragraph_index` into `TimelineEvent`

**Files:**
- Modify: `backend/app/pipeline/timeline.py:61-69` (TimelineEvent construction)
- Test: `backend/tests/test_timeline.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_timeline.py` (append at end of file, reusing the existing module-level `CHAPTERS` dict):

```python
def test_build_timeline_carries_paragraph_index():
    events = [
        {"summary": "相遇", "chapter": "ch0001", "participants": ["贾宝玉"], "order_hint": 0, "paragraph_index": 2},
        {"summary": "分别", "chapter": "ch0002", "participants": ["林黑玉"], "order_hint": 0, "paragraph_index": None},
    ]
    timeline = build_timeline(events, CHAPTERS)
    assert timeline[0].paragraph_index == 2
    assert timeline[1].paragraph_index is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_timeline.py -v -k paragraph_index`
Expected: FAIL — `AttributeError: 'TimelineEvent' object has no attribute 'paragraph_index'`

- [ ] **Step 3: Write the implementation**

In `backend/app/pipeline/timeline.py`, locate the `TimelineEvent(...)` construction (lines 62-69) and add `paragraph_index`:

```python
        timeline.append(
            TimelineEvent(
                seq=seq,
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                summary=e.get("summary", ""),
                participants=list(e.get("participants") or []),
                paragraph_index=e.get("paragraph_index"),
            )
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_timeline.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/timeline.py backend/tests/test_timeline.py
git commit -m "feat: carry paragraph_index through into TimelineEvent"
```

---

### Task 7: `routes.py` — chapter-text endpoint returns `paragraphs`

**Files:**
- Modify: `backend/app/routes.py:13` (imports), `:158-173` (get_chapter_text)
- Test: `backend/tests/test_routes.py` (update existing test)

- [ ] **Step 1: Update the existing test to the new expected shape**

In `backend/tests/test_routes.py`, find `test_get_chapter_text_returns_full_chapter` and change its final assertion:

```python
    resp = client.get(f"/works/{work_id}/chapters/ch0001/text")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chapter_id"] == "ch0001"
    assert body["title"] == "第一章"
    assert body["paragraphs"] == ["这是第一章的正文内容。"]
```

- [ ] **Step 2: Run the test to verify it now fails against current code**

Run: `cd backend && PYTHONPATH=. pytest tests/test_routes.py -v -k test_get_chapter_text_returns_full_chapter`
Expected: FAIL — `KeyError: 'paragraphs'` (response body still has `text`, not `paragraphs`)

- [ ] **Step 3: Write the implementation**

In `backend/app/routes.py`, add an import for `split_paragraphs` near the existing import at line 13:

```python
from .models import ChapterText, CreateWorkResponse, WorkStatus
from .pipeline.locate import split_paragraphs
```

Locate `get_chapter_text` (lines 158-173) and change the return statement:

```python
    return ChapterText(
        chapter_id=chapter_id,
        title=chapter.get("title") or chapter_id,
        paragraphs=split_paragraphs(chapter.get("text") or ""),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_routes.py -v`
Expected: PASS (all tests, including the updated one)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes.py backend/tests/test_routes.py
git commit -m "feat: chapter-text endpoint returns paragraphs list instead of raw text"
```

---

### Task 8: `orchestrator.py` — wire the locate pass into the pipeline

**Files:**
- Modify: `backend/app/pipeline/orchestrator.py:20-30` (imports), `:82-87` (paragraphs_by_chapter), `:124-133` (per-event locate before events.json write), `:145-150` (patch_graph_edge_locations after run_graphify)
- Test: `backend/tests/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing test additions**

In `backend/tests/test_pipeline_integration.py`, extend the existing full-pipeline test (the one using `temp_data_root`, `SAMPLE_NOVEL`, `run_pipeline`) with new assertions after the existing `events.json` key-membership assertion:

```python
    events_path = config.work_dir(work_id) / "events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    for e in events:
        assert {"summary", "chapter", "participants", "order_hint", "evidence", "paragraph_index"} <= set(e.keys())
    assert any(e["paragraph_index"] is not None for e in events), "expected at least one located event"

    graph_data = json.loads(store.graph_json_path(work_id).read_text(encoding="utf-8"))
    edge_list = graph_data.get("links") if graph_data.get("links") is not None else graph_data.get("edges", [])
    assert any(edge.get("source_location") for edge in edge_list), "expected at least one located edge"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_pipeline_integration.py -v`
Expected: FAIL — `AssertionError` on the `{"summary", ..., "evidence", "paragraph_index"} <= set(e.keys())` line (neither key exists on events yet in the persisted output) and/or the "expected at least one located event/edge" assertions.

- [ ] **Step 3: Write the implementation**

In `backend/app/pipeline/orchestrator.py`, extend the import block (lines 20-30) with:

```python
from .locate import locate_paragraph, patch_graph_edge_locations, split_paragraphs
```

Immediately after the existing `chapters.json` write (lines 85-87), add:

```python
    paragraphs_by_chapter = {
        cid: split_paragraphs(v.get("text") or "") for cid, v in chapters_payload.items()
    }
```

Immediately before the existing `events.json` write (lines 131-133), add the per-event locate loop:

```python
    for e in registry.events:
        e["paragraph_index"] = locate_paragraph(
            paragraphs_by_chapter.get(e.get("chapter") or "", []), e.get("evidence") or ""
        )
```

(The `registry.events` list — already about to be serialized at line 132 via `json.dumps(registry.events, ...)` — now has `paragraph_index` set on every entry before that write happens.)

Immediately after the existing `artifacts = run_graphify(...)` call (lines 145-150), add:

```python
    patch_graph_edge_locations(graph_json, registry, artifacts.label_to_id, paragraphs_by_chapter)
```

(`graph_json` is the existing `wdir / "graph.json"` path variable already in scope at line 142; this call must run before the `status.phase = "summarizing"` transition at line 153, and remains inside the outer `try:` block spanning lines 72-210, so any exception it might raise is caught by the existing `except Exception` handler at line 201 rather than crashing the pipeline. `locate_paragraph` never raises — worst case it returns `None` — and `patch_graph_edge_locations` skips edges it can't resolve, so in practice this call should never fail.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && PYTHONPATH=. pytest tests/test_pipeline_integration.py -v`
Expected: PASS

Then run the full backend suite to confirm no regressions:

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: PASS (all tests across all files)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/orchestrator.py backend/tests/test_pipeline_integration.py
git commit -m "feat: wire evidence-to-paragraph locate pass into pipeline orchestrator"
```

---

## Frontend Tasks

There is no frontend automated test framework in this repo. Each frontend task's verification step is manual: run `npm run dev` (or `npx vite build` for a compile check), exercise the described UI behavior in the browser, and confirm via the listed checks. Do the backend tasks (1-8) and `npm run build` once first so `/api/*` responses already have the new shapes before manually testing frontend behavior end-to-end.

### Task 9: `ReaderPage.jsx` — generalize `viewChapter`, thread `onViewChapter` to more tabs

**Files:**
- Modify: `frontend/src/pages/ReaderPage.jsx:56-59` (viewChapter), `:132-134` (CharactersTab render), `:143` (GraphTab render)

- [ ] **Step 1: Update `viewChapter` to accept an optional paragraph index**

Change lines 56-59:

```jsx
  function viewChapter(chapterId, paragraphIndex) {
    setRawJump({ chapterId, paragraphIndex, nonce: Date.now() });
    setTab("raw");
  }
```

- [ ] **Step 2: Thread `onViewChapter` to `CharactersTab` and `GraphTab`**

Change line 132-134 (`CharactersTab` render):

```jsx
              <CharactersTab id={id} pkg={pkg} setRight={setRight} onViewChapter={viewChapter} />
```

Change line 143 (`GraphTab` render):

```jsx
          {tab === "graph" && <GraphTab id={id} setRight={setRight} onViewChapter={viewChapter} />}
```

- [ ] **Step 3: Verify no compile errors**

Run: `cd frontend && npx vite build`
Expected: build succeeds with no errors (CharactersTab/GraphTab don't yet use the new prop, which is harmless — unused props cause no build failure).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ReaderPage.jsx
git commit -m "feat: generalize viewChapter to accept paragraph index, thread onViewChapter to more tabs"
```

---

### Task 10: `TimelineTab.jsx` — per-event precise jump button

**Files:**
- Modify: `frontend/src/components/tabs/TimelineTab.jsx:88-113` (per-event card render)

- [ ] **Step 1: Add a per-event "查看原文→" button**

Locate the per-event card render (lines 88-113), which currently shows `{e.summary}` at line 108 with no jump button. Add a button right after the summary text, styled like the existing chapter-group-header button (line 80-86 pattern, `hover:text-seal-600 hover:underline`):

```jsx
                  <p className="text-sm text-ink-800">{e.summary}</p>
                  {e.chapter_id && (
                    <button
                      type="button"
                      onClick={() => onViewChapter?.(e.chapter_id, e.paragraph_index)}
                      className="mt-1 text-xs text-ink-600 hover:text-seal-600 hover:underline"
                    >
                      查看原文 →
                    </button>
                  )}
```

(This is additive: the existing chapter-group-header "查看原文→" button at lines 80-86, calling `onViewChapter?.(g.chapter_id)` with no paragraph index, is left completely unchanged — it remains the "jump to top of whole chapter" option; this new button is per-event and passes `e.paragraph_index`, which will be `undefined`/`null` for old, un-located events — `onViewChapter?.(e.chapter_id, undefined)` degrades to the exact same chapter-only-jump behavior as today, no special-casing needed.)

- [ ] **Step 2: Verify no compile errors**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

- [ ] **Step 3: Manual verification**

Run `npm run dev` in `frontend/`, open a newly-processed work's 时间轴 (Timeline) tab. For an event whose `paragraph_index` was resolved during pipeline run, clicking the new per-event "查看原文→" button should switch to the 原文 tab and land on that paragraph (full precise-scroll behavior lands once Task 14 rewrites RawTextTab — for now, confirm the button renders, is clickable, and calls `onViewChapter` without throwing).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/tabs/TimelineTab.jsx
git commit -m "feat: add per-event precise jump-to-original-text button in TimelineTab"
```

---

### Task 11: `CharactersTab.jsx` — relation-level jump button

**Files:**
- Modify: `frontend/src/components/tabs/CharactersTab.jsx:5` (props), `:27-34` (relation list building), `:55-71` (relation `<li>` render)

- [ ] **Step 1: Accept `onViewChapter` prop**

Change line 5:

```jsx
export default function CharactersTab({ id, pkg, setRight, onViewChapter }) {
```

- [ ] **Step 2: Carry `source_location` through the relation list**

Change the relation-list-building block (lines 27-34) to also read `source_location`:

```jsx
    const edges = (graph?.edges || graph?.links || []).filter(
      (e) => e.source === selectedId || e.target === selectedId
    );
    const relations = edges.map((e) => {
      const otherId = e.source === selectedId ? e.target : e.source;
      const other = graph?.nodes?.find((n) => n.id === otherId);
      return { label: other?.label || otherId, category: e.category, otherId, sourceLocation: e.source_location };
    });
```

- [ ] **Step 3: Add a "查看原文→" button to each relation `<li>`**

Locate the relation-list render (lines 55-71), which currently shows `（{r.category}）` around line 69. Add a jump button, parsing `chapterId`/`paragraphIndex` out of `r.sourceLocation` (format `"chXXXX"` or `"chXXXX#pN"`):

```jsx
                <span className="text-xs text-ink-500">（{r.category}）</span>
                {r.sourceLocation && (
                  <button
                    type="button"
                    onClick={() => {
                      const [chapterId, para] = r.sourceLocation.split("#p");
                      onViewChapter?.(chapterId, para !== undefined ? Number(para) : undefined);
                    }}
                    className="ml-2 text-xs text-ink-600 hover:text-seal-600 hover:underline"
                  >
                    查看原文 →
                  </button>
                )}
```

- [ ] **Step 4: Verify no compile errors**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

- [ ] **Step 5: Manual verification**

Run `npm run dev`, open a newly-processed work's 人物 (Characters) tab, select a character, confirm relation list entries with a resolved `source_location` now show a "查看原文→" button (and entries without one — old books, or unresolved relationships — show no button, not a broken one).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/tabs/CharactersTab.jsx
git commit -m "feat: add precise jump-to-original-text button in CharactersTab relation list"
```

---

### Task 12: `GraphTab.jsx` — edge-detail jump button

**Files:**
- Modify: `frontend/src/components/tabs/GraphTab.jsx:7` (props), `:132-147` (edge detail panel)

- [ ] **Step 1: Accept `onViewChapter` prop**

Change line 7:

```jsx
export default function GraphTab({ id, setRight, onViewChapter }) {
```

- [ ] **Step 2: Add a conditional jump button to the edge detail panel**

Locate the edge detail panel (lines 132-147), which currently ends with the evidence-quote paragraph (lines 143-145):

```jsx
              {detail.data.evidence && (
                <p className="mt-3 text-sm italic text-ink-600">「{detail.data.evidence}」</p>
              )}
              {detail.data.source_location && (
                <button
                  type="button"
                  onClick={() => {
                    const loc = detail.data.source_location;
                    const [chapterId, para] = loc.split("#p");
                    onViewChapter?.(chapterId, para !== undefined ? Number(para) : undefined);
                  }}
                  className="mt-2 text-xs text-ink-600 hover:text-seal-600 hover:underline"
                >
                  查看原文 →
                </button>
              )}
```

- [ ] **Step 3: Verify no compile errors**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

- [ ] **Step 4: Manual verification**

Run `npm run dev`, open a newly-processed work's 图谱 (Graph) tab, click an edge with resolved `source_location`, confirm the new "查看原文→" button appears and is clickable; click an edge without one, confirm no button appears (no error).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/tabs/GraphTab.jsx
git commit -m "feat: add precise jump-to-original-text button in GraphTab edge detail panel"
```

---

### Task 13: `AskTab.jsx` — support prefill-without-auto-submit seeds

**Files:**
- Modify: `frontend/src/components/tabs/AskTab.jsx:49-55` (seed-handling useEffect)

- [ ] **Step 1: Branch on `seed.autoSubmit`**

Change the seed-handling useEffect (lines 49-55):

```jsx
  useEffect(() => {
    if (loaded && seed && seed.nonce !== lastHandledNonceRef.current) {
      lastHandledNonceRef.current = seed.nonce;
      if (seed.autoSubmit === false) {
        setQ(seed.question);
      } else {
        runAsk(seed.question);
      }
    }
  }, [seed, loaded]);
```

(Default behavior — `seed.autoSubmit` absent/`undefined`/`true` — is unchanged: existing `askAbout` callers, which never set `autoSubmit`, keep auto-submitting exactly as today. Only an explicit `autoSubmit: false` switches to prefill-only mode.)

- [ ] **Step 2: Verify no compile errors**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

- [ ] **Step 3: Manual verification**

Run `npm run dev`, use an existing "问AI" entry point (e.g. from Characters tab, if one calls `askAbout`) and confirm it still auto-submits as before (regression check for the default path). This task has no new entry point of its own yet — Task 14 (select-text-to-ask) is what will exercise the new `autoSubmit: false` branch end-to-end.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/tabs/AskTab.jsx
git commit -m "feat: support prefill-only (non-auto-submitting) Ask seeds"
```

---

### Task 14: `RawTextTab.jsx` — continuous-scroll reader rewrite

This is the largest task: full rewrite of the file. Because there's no frontend test framework, this task is broken into incremental sub-steps, each independently manually verifiable, so problems are caught early rather than all at once at the end.

**Files:**
- Modify (full rewrite): `frontend/src/components/tabs/RawTextTab.jsx` (currently 119 lines, accordion-based)

- [ ] **Step 1: Read the current file in full before starting**

Run: `rtk read frontend/src/components/tabs/RawTextTab.jsx`

Confirm current props (`{ id, ls, jump, setRight }`), current TOC-building `useEffect` (lines 34-63), current `chapterRefs` ref-array pattern (line 91), and current `loadChapter`/`toggleChapter` functions — these patterns (TOC building, ref-array-per-chapter, lazy per-chapter API call) are preserved conceptually in the rewrite; only the trigger (click→expand becomes scroll-proximity→fetch) and the render shape (accordion becomes continuous flow) change.

- [ ] **Step 2: Rewrite — chapter list, TOC, and continuous scroll skeleton (no highlighting/toolbar yet)**

Replace the full file with:

```jsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getChapterText } from "../../api";

export default function RawTextTab({ id, ls, jump, setRight }) {
  const chapters = ls?.chapters || [];
  const [chapterState, setChapterState] = useState({}); // chapterId -> { loading, paragraphs }
  const chapterRefs = useRef({});
  const lastHandledNonceRef = useRef(null);

  const loadChapter = useCallback(
    async (chapterId) => {
      setChapterState((prev) => {
        if (prev[chapterId]?.loading || prev[chapterId]?.paragraphs) return prev;
        return { ...prev, [chapterId]: { loading: true, paragraphs: null } };
      });
      const res = await getChapterText(id, chapterId);
      setChapterState((prev) => ({ ...prev, [chapterId]: { loading: false, paragraphs: res.paragraphs || [] } }));
    },
    [id]
  );

  useEffect(() => {
    setRight(
      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink-700">章节目录</h3>
        <ul className="space-y-1">
          {chapters.map((c) => (
            <li key={c.chapter}>
              <button
                type="button"
                onClick={() =>
                  chapterRefs.current[c.chapter]?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
                className="text-sm text-ink-600 hover:text-seal-600 hover:underline"
              >
                {c.title || c.chapter}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
    return () => setRight(null);
  }, [chapters, setRight]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const chapterId = entry.target.dataset.chapterId;
            if (chapterId) loadChapter(chapterId);
          }
        }
      },
      { rootMargin: "200px" }
    );
    for (const c of chapters) {
      const el = chapterRefs.current[c.chapter];
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [chapters, loadChapter]);

  useEffect(() => {
    if (!jump || jump.nonce === lastHandledNonceRef.current) return;
    lastHandledNonceRef.current = jump.nonce;
    loadChapter(jump.chapterId);
    setTimeout(() => {
      chapterRefs.current[jump.chapterId]?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }, [jump, loadChapter]);

  return (
    <div className="mx-auto max-w-2xl">
      {chapters.map((c) => {
        const st = chapterState[c.chapter];
        return (
          <div
            key={c.chapter}
            ref={(el) => {
              chapterRefs.current[c.chapter] = el;
            }}
            data-chapter-id={c.chapter}
            className="mb-8"
          >
            <h2 className="mb-3 text-lg font-semibold text-ink-800">{c.title || c.chapter}</h2>
            {!st && <p className="text-sm text-ink-400">滚动到此处以加载正文…</p>}
            {st?.loading && <p className="text-sm text-ink-400">加载中…</p>}
            {st?.paragraphs?.map((p, i) => (
              <p key={i} id={`p-${c.chapter}-${i}`} data-chapter={c.chapter} data-para={i} className="mb-3 leading-relaxed text-ink-800">
                {p}
              </p>
            ))}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Verify no compile errors, manually test scroll-lazy-load and chapter-jump**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

Run `npm run dev`, open a work's 原文 tab: confirm all chapters are listed continuously (no accordion), scrolling near a chapter triggers its fetch/render, and the chapter TOC / cross-tab jump (e.g. from Timeline's existing chapter-only button) scrolls to the right chapter.

- [ ] **Step 4: Commit the skeleton**

```bash
git add frontend/src/components/tabs/RawTextTab.jsx
git commit -m "refactor: rewrite RawTextTab as continuous-scroll reader (skeleton)"
```

- [ ] **Step 5: Add font-size + day/night toolbar with localStorage persistence**

Add near the top of the component (after existing state):

```jsx
  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem("novel_kg_reader_font_size")) || 16);
  const [theme, setTheme] = useState(() => localStorage.getItem("novel_kg_reader_theme") || "day");

  useEffect(() => {
    localStorage.setItem("novel_kg_reader_font_size", String(fontSize));
  }, [fontSize]);

  useEffect(() => {
    localStorage.setItem("novel_kg_reader_theme", theme);
  }, [theme]);

  const FONT_SIZES = [14, 16, 18, 20, 22];
  function stepFontSize(delta) {
    setFontSize((cur) => {
      const idx = FONT_SIZES.indexOf(cur);
      const nextIdx = Math.min(FONT_SIZES.length - 1, Math.max(0, (idx === -1 ? 1 : idx) + delta));
      return FONT_SIZES[nextIdx];
    });
  }
```

Add a toolbar above the chapters list in the render, and wrap the chapters container with theme-conditional classes:

```jsx
  const themeClasses = theme === "night" ? "bg-ink-900 text-paper-50" : "bg-white text-ink-900";

  return (
    <div className={`rounded-md p-4 ${themeClasses}`}>
      <div className="mb-4 flex items-center gap-3 text-sm">
        <button type="button" onClick={() => stepFontSize(-1)} className="rounded border px-2 py-1">A-</button>
        <button type="button" onClick={() => stepFontSize(1)} className="rounded border px-2 py-1">A+</button>
        <button
          type="button"
          onClick={() => setTheme((t) => (t === "night" ? "day" : "night"))}
          className="rounded border px-2 py-1"
        >
          {theme === "night" ? "☀️ 日间" : "🌙 夜间"}
        </button>
      </div>
      <div className="mx-auto max-w-2xl" style={{ fontSize }}>
        {/* ...existing chapters.map(...) block unchanged... */}
      </div>
    </div>
  );
```

- [ ] **Step 6: Verify and manually test toolbar**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

Run `npm run dev`, confirm font +/- changes text size, night toggle swaps to dark colors (scoped to reader content only — sidebar/shell stay unaffected), and both persist after a page reload.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/tabs/RawTextTab.jsx
git commit -m "feat: add font-size and day/night toolbar to reader, persisted via localStorage"
```

- [ ] **Step 8: Add reading-progress persistence**

Extend the existing `IntersectionObserver` callback to also track and persist the topmost visible paragraph. Add a second observer (paragraphs, not chapters) after chapters render, or extend tracking within the existing per-chapter observer plus a scroll listener on paragraph elements. Simplest correct approach — track visible paragraphs directly:

```jsx
  const progressKey = `novel_kg_reader_progress_${id}`;
  const restoredRef = useRef(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length === 0) return;
        const top = visible.reduce((a, b) => (a.boundingClientRect.top < b.boundingClientRect.top ? a : b));
        const { chapter, para } = top.target.dataset;
        if (chapter && para !== undefined) {
          localStorage.setItem(progressKey, JSON.stringify({ chapterId: chapter, paragraphIndex: Number(para) }));
        }
      },
      { threshold: 0.1 }
    );
    const paras = document.querySelectorAll("[data-chapter][data-para]");
    for (const el of paras) observer.observe(el);
    return () => observer.disconnect();
  }, [chapterState, progressKey]);

  useEffect(() => {
    if (restoredRef.current) return;
    const saved = localStorage.getItem(progressKey);
    if (!saved) return;
    try {
      const { chapterId, paragraphIndex } = JSON.parse(saved);
      restoredRef.current = true;
      loadChapter(chapterId).then(() => {
        setTimeout(() => {
          document.getElementById(`p-${chapterId}-${paragraphIndex}`)?.scrollIntoView({ block: "start" });
        }, 50);
      });
    } catch {
      /* ignore malformed saved progress */
    }
  }, [progressKey, loadChapter]);
```

- [ ] **Step 9: Verify and manually test progress persistence**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

Run `npm run dev`, scroll partway into a work's 原文 tab, navigate away (e.g. to Home) and back into the same work's reader, confirm it auto-scrolls close to where you left off. Open a *different* work and confirm it starts from the top (per-work key, no cross-book interference).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/tabs/RawTextTab.jsx
git commit -m "feat: persist and restore reading progress per work via localStorage"
```

- [ ] **Step 11: Add entity name highlighting with click popover**

Fetch graph data (reusing the same call `GraphTab.jsx` already makes) and build a name+alias lookup:

```jsx
import { getGraph } from "../../api";
// ...
  const [graph, setGraph] = useState(null);
  const [popover, setPopover] = useState(null); // { nodeId, x, y }

  useEffect(() => {
    getGraph(id).then(setGraph).catch(() => setGraph(null));
  }, [id]);

  const nameLookup = useMemo(() => {
    if (!graph?.nodes) return [];
    const entries = [];
    for (const node of graph.nodes) {
      if (node.node_type !== "character" && node.node_type !== "place") continue;
      const names = [node.label, ...(node.aliases || [])].filter(Boolean);
      for (const name of names) entries.push({ name, nodeId: node.id });
    }
    return entries.sort((a, b) => b.name.length - a.name.length); // longest-match-first
  }, [graph]);

  const relationsFor = useCallback(
    (nodeId) => {
      const edges = (graph?.edges || graph?.links || []).filter((e) => e.source === nodeId || e.target === nodeId);
      return edges.map((e) => {
        const otherId = e.source === nodeId ? e.target : e.source;
        const other = graph?.nodes?.find((n) => n.id === otherId);
        return { label: other?.label || otherId, category: e.category };
      });
    },
    [graph]
  );

  function renderWithEntities(text, keyPrefix) {
    if (nameLookup.length === 0) return text;
    const pattern = new RegExp(`(${nameLookup.map((n) => n.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
    const parts = text.split(pattern);
    return parts.map((part, i) => {
      const hit = nameLookup.find((n) => n.name === part);
      if (!hit) return part;
      return (
        <span
          key={`${keyPrefix}-${i}`}
          className="entity-link cursor-pointer text-seal-700 underline decoration-dotted"
          onClick={(evt) => setPopover({ nodeId: hit.nodeId, x: evt.clientX, y: evt.clientY })}
        >
          {part}
        </span>
      );
    });
  }
```

Change the paragraph render to use `renderWithEntities`:

```jsx
            {st?.paragraphs?.map((p, i) => (
              <p key={i} id={`p-${c.chapter}-${i}`} data-chapter={c.chapter} data-para={i} className="mb-3 leading-relaxed">
                {renderWithEntities(p, `${c.chapter}-${i}`)}
              </p>
            ))}
```

Add the popover render (near the end of the component's returned JSX, as a sibling of the main content):

```jsx
      {popover && (
        <EntityPopover
          node={graph?.nodes?.find((n) => n.id === popover.nodeId)}
          relations={relationsFor(popover.nodeId)}
          x={popover.x}
          y={popover.y}
          onClose={() => setPopover(null)}
        />
      )}
```

Add a small helper component in the same file:

```jsx
function EntityPopover({ node, relations, x, y, onClose }) {
  if (!node) return null;
  return (
    <div
      className="fixed z-50 max-w-xs rounded-md border border-ink-200 bg-white p-3 shadow-lg"
      style={{ left: x, top: y }}
      onMouseLeave={onClose}
    >
      <p className="font-semibold text-ink-800">{node.label}</p>
      {node.role && <p className="text-xs text-ink-500">{node.role}</p>}
      {node.description && <p className="mt-1 text-sm text-ink-700">{node.description}</p>}
      {relations.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-ink-600">
          {relations.map((r, i) => (
            <li key={i}>
              {r.label}（{r.category}）
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={onClose} className="mt-2 text-xs text-ink-400 hover:underline">
        关闭
      </button>
    </div>
  );
}
```

- [ ] **Step 12: Verify and manually test entity highlighting**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

Run `npm run dev`, open a work's 原文 tab, confirm character/place names in the text are visually marked and clicking one opens a popover with role/description/relationship list; confirm clicking outside or the close button dismisses it.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/components/tabs/RawTextTab.jsx
git commit -m "feat: highlight character/place names in reader with click-to-view AI popover"
```

- [ ] **Step 14: Add precise paragraph jump-and-flash on top of the existing chapter-jump**

Extend the jump `useEffect` (from Step 2) to also scroll to and flash a specific paragraph when `jump.paragraphIndex` is present:

```jsx
  useEffect(() => {
    if (!jump || jump.nonce === lastHandledNonceRef.current) return;
    lastHandledNonceRef.current = jump.nonce;
    loadChapter(jump.chapterId).then(() => {
      setTimeout(() => {
        const targetId =
          jump.paragraphIndex != null ? `p-${jump.chapterId}-${jump.paragraphIndex}` : null;
        const el = targetId ? document.getElementById(targetId) : chapterRefs.current[jump.chapterId];
        el?.scrollIntoView({ behavior: "smooth", block: "start" });
        if (targetId && el) {
          el.classList.add("bg-amber-100");
          setTimeout(() => el.classList.remove("bg-amber-100"), 1200);
        }
      }, 50);
    });
  }, [jump, loadChapter]);
```

(When `jump.paragraphIndex` is `null`/`undefined` — old books or unresolved matches — this falls back to exactly today's chapter-top-only scroll with no flash, unchanged behavior, no special-casing needed.)

- [ ] **Step 15: Verify and manually test precise jump**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

Run `npm run dev`. From a newly-processed work's Timeline/Characters/Graph tab, click a "查看原文→" button that has a resolved paragraph index (added in Tasks 10-12); confirm the reader scrolls to and briefly highlights that exact paragraph. Click one without a resolved index (or use an old, already-processed work); confirm it falls back to scrolling to the top of the chapter with no highlight and no error.

- [ ] **Step 16: Commit**

```bash
git add frontend/src/components/tabs/RawTextTab.jsx
git commit -m "feat: precisely scroll to and flash-highlight target paragraph on cross-tab jump"
```

- [ ] **Step 17: Add select-text-to-ask floating button**

Add selection tracking and a floating button, plus wiring to switch tabs with a prefill-only Ask seed. This requires `ReaderPage.jsx` to pass down an `onAskAbout`-style callback that sets `askSeed` with `autoSubmit: false` — add a new prop to `RawTextTab`'s signature and its usage in `ReaderPage.jsx`:

In `frontend/src/pages/ReaderPage.jsx`, add a new function near `askAbout` (lines 51-54):

```jsx
  function askAboutSelection(question) {
    setAskSeed({ question, autoSubmit: false, nonce: Date.now() });
    setTab("ask");
  }
```

And pass it to `RawTextTab`'s render call (lines 136-138):

```jsx
              <RawTextTab id={id} ls={ls} jump={rawJump} setRight={setRight} onAskAboutSelection={askAboutSelection} />
```

In `RawTextTab.jsx`, accept the new prop and add selection handling:

```jsx
export default function RawTextTab({ id, ls, jump, setRight, onAskAboutSelection }) {
  // ...existing state...
  const [selectionButton, setSelectionButton] = useState(null); // { text, chapterTitle, x, y }

  useEffect(() => {
    function handleMouseUp() {
      const sel = window.getSelection();
      const text = sel?.toString().trim();
      if (!text) {
        setSelectionButton(null);
        return;
      }
      const anchorNode = sel.anchorNode;
      const paraEl = anchorNode?.parentElement?.closest("[data-chapter]");
      const chapterId = paraEl?.dataset.chapter;
      const chapterTitle = chapters.find((c) => c.chapter === chapterId)?.title || chapterId || "";
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      setSelectionButton({ text, chapterTitle, x: rect.right, y: rect.bottom });
    }
    document.addEventListener("mouseup", handleMouseUp);
    return () => document.removeEventListener("mouseup", handleMouseUp);
  }, [chapters]);
```

Add the floating button render:

```jsx
      {selectionButton && (
        <button
          type="button"
          className="fixed z-50 rounded bg-seal-600 px-2 py-1 text-xs text-white shadow"
          style={{ left: selectionButton.x, top: selectionButton.y }}
          onClick={() => {
            onAskAboutSelection?.(
              `关于这段内容：「${selectionButton.text}」（出自${selectionButton.chapterTitle}），我想问：`
            );
            setSelectionButton(null);
          }}
        >
          就这段问AI
        </button>
      )}
```

- [ ] **Step 18: Verify and manually test select-text-to-ask**

Run: `cd frontend && npx vite build`
Expected: build succeeds.

Run `npm run dev`, select a span of text in a work's 原文 tab, confirm the "就这段问AI" floating button appears near the selection; click it, confirm the app switches to the 问答 (Ask) tab with the input prefilled with the quote and chapter title but NOT auto-submitted (user must click 提问 themselves to send it) — this is the regression check that Task 13's `autoSubmit: false` branch works end-to-end.

- [ ] **Step 19: Commit**

```bash
git add frontend/src/pages/ReaderPage.jsx frontend/src/components/tabs/RawTextTab.jsx
git commit -m "feat: add select-text-to-ask floating button in reader"
```

---

## Final Verification

- [ ] **Run the full backend test suite one more time**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: PASS (all tests across all files, zero regressions)

- [ ] **Run a final frontend build**

Run: `cd frontend && npx vite build`
Expected: build succeeds with no errors

- [ ] **Manual end-to-end smoke test**

Upload a fresh `.txt` novel (offline mode, `NOVEL_KG_USE_FAKE_LLM=1` already set via `backend/tests/conftest.py`'s default, or set the env var when running `uvicorn` manually), let it process to `done`, then in the 原文 tab confirm: continuous scroll works, font-size/theme toggle and persist, reading progress persists across navigation, character names are highlighted and clickable, and at least one "查看原文→" button from Timeline/Characters/Graph precisely jumps to and flashes a paragraph. Then open an **old**, previously-processed work and confirm its 原文 tab still works (continuous scroll, no crash) and any "查看原文→" buttons either don't appear or fall back to chapter-only jump — no errors either way.
