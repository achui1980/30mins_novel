# 演示亮点改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three demo-visibility defects in `30mins_demo`'s reader page — a noisy knowledge graph dominated by disconnected place nodes, a decorative/nonsensical "suggested questions" block, and a fully-extracted-but-never-surfaced event timeline — without touching the upload/processing pages or the Q&A retrieval logic itself.

**Architecture:** Three independently-shippable phases, executed in order: (1) pure-frontend graph denoising plus a backend prompt tweak, both effective immediately including for old works; (2) a new backend LLM (+ deterministic fake) stage that replaces graphify's garbage `suggest_questions` with real plot-grounded questions, wired to jump into the existing agentic Q&A tab on click; (3) persisting previously-discarded `registry.events` to disk, a new flattening module, a new `GET /works/{id}/timeline` endpoint, and a new horizontal-scrolling timeline tab. Every backend change keeps the existing `NOVEL_KG_USE_FAKE_LLM=1` offline mirror in sync so tests and demos never touch AWS.

**Tech Stack:** FastAPI + Pydantic v2 (backend, Python 3.11+, package `app`), pytest + pytest-asyncio (backend tests), React 18 + Vite 5 + vis-network (frontend, no test tooling — manual browser verification only).

## Global Constraints

- **Never run `git commit`.** Each task's final step stages the relevant files with `git add` and stops there — the user decides when and whether to commit. Do not amend, squash, or otherwise touch git history unless the user explicitly asks.
- Backend venv/tests: run `cd backend && PYTHONPATH=. pytest -q` after every backend task; all existing tests plus new ones must pass (baseline: 21 existing tests, must never regress).
- Offline fake-LLM parity: any new LLM-backed behavior must have a working, deterministic, no-randomness fake/offline counterpart gated on `config.USE_FAKE_LLM`, matching the existing `_fake_*` naming and independent-fallback conventions in `summarize.py`.
- Do NOT modify `frontend/src/pages/HomePage.jsx` or `frontend/src/pages/ProcessingPage.jsx` — out of scope per design spec §1.
- Do NOT modify `backend/app/pipeline/ask.py`'s retrieval/tool-use logic — out of scope per design spec §1. (Frontend wiring that calls the existing `/works/{id}/ask` endpoint is in scope.)
- Do NOT introduce new frontend dependencies or a test runner — no vitest/@testing-library. Frontend verification is manual-in-browser only, per design spec §5.
- Do NOT write backfill/compatibility code for the 11 pre-existing works in `data/works/`. New-format data (suggested_questions, `events.json`) is either present (new/reprocessed works) or absent (old works) — the frontend must degrade gracefully (hide the section/tab, no fake placeholder data, no error banner) when absent. Graph denoising is the one exception: it is pure frontend rendering logic and benefits ALL existing works immediately with no backend changes needed.
- New persisted file name is exactly `events.json` (not `timeline.json`), living alongside `chapters.json`/`graph.json`/`summary.json` in `{DATA_ROOT}/{work_id}/`.
- Reference design doc: `docs/superpowers/specs/2026-08-01-demo-highlights-design.md`. Section numbers below (§4.1/§4.2/§4.3) refer to it.

---

## Phase 1: 图谱降噪 (Graph Denoising) — design §4.1

### Task 1: Tighten place-extraction guidance in the real LLM prompt

**Files:**
- Modify: `backend/app/pipeline/extract.py:27-37` (`SYSTEM_PROMPT`, `COMPLETE_HINT`)
- Test: `backend/tests/test_extract.py` (new file)

**Interfaces:**
- Consumes: nothing new.
- Produces: `SYSTEM_PROMPT: str`, `QUICK_HINT: str`, `COMPLETE_HINT: str` (module-level constants in `extract.py`, unchanged names, changed content) — Task 2 in this same file relies on nothing from this task except the file continuing to exist with the same constant names.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_extract.py`:

```python
"""Tests for the extraction layer (design §4.1 图谱降噪)."""

from app.pipeline.extract import COMPLETE_HINT, SYSTEM_PROMPT


def test_system_prompt_has_place_restraint_guidance():
    assert "地点" in SYSTEM_PROMPT
    assert "克制" in SYSTEM_PROMPT


def test_complete_hint_no_longer_demands_exhaustive_places():
    # The old wording unconditionally told the LLM to extract "all" places
    # even in complete mode, which is the root cause of place over-generation.
    assert "尽量抽取全部人物、地点、事件与关系" not in COMPLETE_HINT
    assert "地点" in COMPLETE_HINT
    assert "克制" in COMPLETE_HINT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_extract.py -v`
Expected: FAIL — `SYSTEM_PROMPT`/`COMPLETE_HINT` don't yet contain "克制", and `COMPLETE_HINT` still contains the literal old phrase "尽量抽取全部人物、地点、事件与关系".

- [ ] **Step 3: Edit `extract.py` to add restraint guidance**

Replace lines 27-37 of `backend/app/pipeline/extract.py`:

```python
SYSTEM_PROMPT = (
    "你是一个小说信息抽取引擎。给定一段小说正文，抽取其中的人物、地点、事件和人物关系，"
    "并严格按照给定的结构化 schema 返回。要求：\n"
    "- 人物 name 使用最正式/最常用的称呼，把绰号代称放进 aliases。\n"
    "- 地点抽取要克制：只抽取对情节有实际作用、被反复提及或承载关键事件的地点，"
    "忽略一次性出现、无情节意义的泛化地名（如路过的某条街、某个房间），"
    "避免地点数量远超人物数量。\n"
    "- 关系 category 必须是以下之一：家人, 爱人, 朋友, 敌人, 师徒, 主仆, 同盟, 其他。\n"
    "- 关系必须给出简短 detail 与原文 evidence，并估计 confidence(0-1)。\n"
    "- 只抽取文中明确出现或强烈暗示的信息，不要编造。"
)

QUICK_HINT = "\n注意：当前为【快速】档，只需抽取主要角色、主线关系与关键事件，忽略龙套与次要地点。"
COMPLETE_HINT = (
    "\n注意：当前为【完整】档，尽量抽取全部人物、事件与关系；"
    "地点仍需遵守上述克制标准——只保留反复出现或承载关键情节的地点，"
    "不要因为是【完整】档就无差别地为每个提到的地名创建节点。"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_extract.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: all tests pass (21 existing + 2 new = 23)

- [ ] **Step 6: Stage changes (do NOT commit — wait for user approval)**

```bash
git add backend/app/pipeline/extract.py backend/tests/test_extract.py
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

### Task 2: Offline fake extractor emits Place objects

**Files:**
- Modify: `backend/app/pipeline/extract.py:75-131` (`fake_extract_block`)
- Test: `backend/tests/test_extract.py` (append)

**Interfaces:**
- Consumes: `Block` dataclass from `chunk.py` (`block_id, chapter_id, chapter_title, order, text`), unchanged.
- Produces: `fake_extract_block(block: Block) -> ChunkExtraction` — same signature as before, but the returned `ChunkExtraction.places` is no longer always `[]`. Task 3 (frontend) does not depend on this directly (frontend filters whatever `graph.json` already contains); this task exists so the offline demo/tests actually have place nodes to exercise the Task 3 filter UI against.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_extract.py`:

```python
from app.pipeline.chunk import Block
from app.pipeline.extract import fake_extract_block


def _block(text: str) -> Block:
    return Block(block_id="ch0001_b000", chapter_id="ch0001", chapter_title="第一章", order=0, text=text)


# Enough distinct, repeated 2-4 char CJK substrings that the top-5 character
# slots fill up and at least 1-2 candidates remain available for places.
SAMPLE_TEXT = (
    "贾宝玉贾宝玉贾宝玉在潇湘馆潇湘馆潇湘馆遇见林黛玉林黛玉林黛玉。"
    "薛宝钗薛宝钗薛宝钗与王熙凤王熙凤王熙凤在大观园大观园大观园游玩。"
    "史湘云史湘云史湘云也在潇湘馆潇湘馆潇湘馆附近说话。"
)


def test_fake_extract_block_produces_up_to_five_characters():
    ext = fake_extract_block(_block(SAMPLE_TEXT))
    assert len(ext.characters) == 5


def test_fake_extract_block_produces_place_objects():
    ext = fake_extract_block(_block(SAMPLE_TEXT))
    assert 1 <= len(ext.places) <= 3
    char_names = {c.name for c in ext.characters}
    for p in ext.places:
        assert p.name not in char_names
        assert p.description


def test_fake_extract_block_places_empty_when_not_enough_candidates():
    # A block with fewer than 6 distinct frequent substrings has nothing left
    # over for places after the top-5 characters are chosen — must not error.
    ext = fake_extract_block(_block("张三张三李四李四"))
    assert isinstance(ext.places, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_extract.py -v`
Expected: FAIL on `test_fake_extract_block_produces_place_objects` — `ext.places == []` currently (fake_extract_block never imports/emits `Place`).

- [ ] **Step 3: Edit `fake_extract_block` to also emit places**

Replace the body of `fake_extract_block` in `backend/app/pipeline/extract.py` (lines 75-131) with:

```python
def fake_extract_block(block: Block) -> ChunkExtraction:
    """A cheap deterministic extractor for offline runs.

    Heuristic: treat the most frequent 2-4 char CJK tokens in the block as
    characters, and pair consecutive distinct characters as 'friend' relations.
    This is *not* accurate but produces a well-formed graph for demos/tests.

    The next 1-2 ranked (non-overlapping) candidates beyond the top-5
    characters become Place objects, reusing the same frequency ranking —
    this keeps the offline/fake path exercising the same place-filtering UI
    (design §4.1) that real extraction produces, without any semantic
    place-detection logic.
    """
    from ..models import Character, Event, Place, Relationship, RelationCategory

    # Count every 2-, 3- and 4-char CJK substring (sliding window) so repeated
    # names surface regardless of surrounding punctuation/particles. We then
    # greedily keep the highest-frequency, longest candidates while suppressing
    # substrings already covered by a chosen longer name.
    counts: dict[str, int] = {}
    for run in re.findall(r"[\u4e00-\u9fff]+", block.text):
        for length in (2, 3, 4):
            for i in range(len(run) - length + 1):
                sub = run[i : i + length]
                counts[sub] = counts.get(sub, 0) + 1

    # Rank by (frequency, length) so longer, more-frequent names win.
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], len(kv[0])), reverse=True)
    top: list[str] = []
    place_candidates: list[str] = []
    for name, cnt in ranked:
        if cnt < 2:
            continue
        chosen_so_far = top + place_candidates
        if any(name in chosen or chosen in name for chosen in chosen_so_far):
            continue
        if len(top) < 5:
            top.append(name)
        elif len(place_candidates) < 2:
            place_candidates.append(name)
        if len(top) >= 5 and len(place_candidates) >= 2:
            break
    characters = [Character(name=n, description=f"在{block.chapter_title}中出现") for n in top]
    places = [Place(name=n, description=f"在{block.chapter_title}中提及的地点") for n in place_candidates]

    relationships = []
    for a, b in zip(top, top[1:]):
        relationships.append(
            Relationship(
                source=a,
                target=b,
                category=RelationCategory.FRIEND,
                detail=f"{a}与{b}在同一段落中出现",
                evidence=block.text[:40],
                confidence=0.5,
            )
        )
    events = []
    if top:
        events.append(
            Event(
                summary=f"{block.chapter_title}中，{top[0]}相关的情节",
                chapter=block.chapter_id,
                participants=top[:3],
                order_hint=block.order,
            )
        )
    return ChunkExtraction(characters=characters, places=places, relationships=relationships, events=events)
```

(Only the `from ..models import ...` line gains `Place`, the ranking loop gains the `place_candidates` branch, and `ChunkExtraction(...)` gains `places=places`. Everything else is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_extract.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: all pass (23 existing + 3 new = 26). Pay attention to `test_pipeline_integration.py::test_pipeline_end_to_end` — it should still pass; the sample novel text there has repeated character names so it may or may not produce places, which is fine (no assertion currently checks `places`).

- [ ] **Step 6: Stage changes (do NOT commit — wait for user approval)**

```bash
git add backend/app/pipeline/extract.py backend/tests/test_extract.py
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

### Task 3: Frontend Top-N place filter + "显示全部地点" toggle in GraphTab

**Files:**
- Modify: `frontend/src/pages/ReaderPage.jsx:381-487` (`GraphTab` component)
- Modify: `frontend/src/styles.css` (append `.graph-controls` styles)

**Interfaces:**
- Consumes: `graph.nodes[]` / `graph.edges|links[]` shape from `GET /works/{id}/graph` (unchanged), `categoryColor()` from `constants.js` (unchanged).
- Produces: no exported interface — this is a leaf UI component. No later task depends on it.

No automated test exists for the frontend (design spec §5: no test tooling introduced). This task is verified manually in the browser per Step 2.

- [ ] **Step 1: Edit `GraphTab` in `frontend/src/pages/ReaderPage.jsx`**

Replace the `GraphTab` function (lines 381-487) with:

```jsx
const PLACE_TOP_N = 15;

function GraphTab({ id }) {
  const containerRef = useRef(null);
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [showAllPlaces, setShowAllPlaces] = useState(false);

  useEffect(() => {
    getGraph(id).then(setGraph).catch((e) => setError(e.message));
  }, [id]);

  // Normalize edges (may be under 'edges' or 'links').
  const edges = useMemo(() => {
    if (!graph) return [];
    return graph.edges || graph.links || [];
  }, [graph]);

  const placeCount = useMemo(() => {
    if (!graph) return 0;
    return (graph.nodes || []).filter((n) => n.node_type === "place").length;
  }, [graph]);

  useEffect(() => {
    if (!graph || !containerRef.current) return;
    const rawNodes = graph.nodes || [];

    // Degree = number of edges touching a node. We filter places by degree
    // (not mention_count) because a place mentioned often but never linked
    // to anything is still visual noise (design §4.1b).
    const degree = {};
    for (const e of edges) {
      degree[e.source] = (degree[e.source] || 0) + 1;
      degree[e.target] = (degree[e.target] || 0) + 1;
    }

    let visibleNodes = rawNodes;
    if (!showAllPlaces) {
      const characters = rawNodes.filter((n) => n.node_type !== "place");
      const places = rawNodes.filter((n) => n.node_type === "place");
      const topPlaces = [...places]
        .sort((a, b) => (degree[b.id] || 0) - (degree[a.id] || 0))
        .slice(0, PLACE_TOP_N);
      visibleNodes = [...characters, ...topPlaces];
    }
    // Filtered-out nodes are fully excluded (not just hidden) so the
    // Barnes-Hut physics engine doesn't waste layout effort on them.
    const visibleIds = new Set(visibleNodes.map((n) => n.id));

    const nodes = visibleNodes.map((n) => ({
      id: n.id,
      label: n.label,
      shape: n.node_type === "place" ? "box" : "dot",
      size: 12 + Math.min(20, (n.mention_count || 1) * 2),
      color:
        n.node_type === "place"
          ? { background: "#d9d9d9", border: "#b0b0b0" }
          : undefined,
      _raw: n,
    }));
    const visEdges = edges
      .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
      .map((e, i) => ({
        id: `e${i}`,
        from: e.source,
        to: e.target,
        color: { color: categoryColor(e.category) },
        width: Math.max(1, Math.min(6, e.weight || 1)),
        arrows: e.directed ? "to" : undefined,
        _raw: e,
      }));

    const network = new Network(
      containerRef.current,
      { nodes, edges: visEdges },
      {
        nodes: { font: { size: 15, face: "PingFang SC, Microsoft YaHei, sans-serif" } },
        edges: { smooth: { type: "continuous" } },
        physics: { stabilization: { iterations: 150 }, barnesHut: { springLength: 130 } },
        interaction: { hover: true, tooltipDelay: 120 },
      }
    );

    network.on("click", (params) => {
      if (params.nodes.length > 0) {
        const n = nodes.find((x) => x.id === params.nodes[0]);
        setDetail({ type: "node", data: n?._raw });
      } else if (params.edges.length > 0) {
        const e = visEdges.find((x) => x.id === params.edges[0]);
        setDetail({ type: "edge", data: e?._raw });
      } else {
        setDetail(null);
      }
    });

    return () => network.destroy();
  }, [graph, edges, showAllPlaces]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!graph) return <div className="empty"><span className="spinner" /> 加载图谱…</div>;

  return (
    <div>
      <div className="legend">
        {CATEGORY_ORDER.map((cat) => (
          <span key={cat} className="item">
            <span className="swatch" style={{ background: categoryColor(cat) }} />
            {cat}
          </span>
        ))}
      </div>

      {placeCount > PLACE_TOP_N && (
        <div className="graph-controls">
          <label>
            <input
              type="checkbox"
              checked={showAllPlaces}
              onChange={(e) => setShowAllPlaces(e.target.checked)}
            />
            显示全部地点（共 {placeCount} 个，默认只显示连接最多的 {PLACE_TOP_N} 个）
          </label>
        </div>
      )}

      <div id="graph" ref={containerRef} />

      {detail?.type === "node" && detail.data && (
        <div className="graph-detail">
          <div className="char-card">
            <span className="name">{detail.data.label}</span>
            {detail.data.role && <span className="role">{detail.data.role}</span>}
          </div>
          {detail.data.description && <div className="desc">{detail.data.description}</div>}
          <div className="k" style={{ marginTop: 8 }}>
            {detail.data.node_type === "place" ? "地点" : "人物"} · 提及 {detail.data.mention_count || 0} 次
          </div>
        </div>
      )}

      {detail?.type === "edge" && detail.data && (
        <div className="graph-detail">
          <div>
            <span className="swatch" style={{ background: categoryColor(detail.data.category), display: "inline-block", width: 12, height: 12, borderRadius: 3, marginRight: 6 }} />
            <strong>{detail.data.category}</strong>
            <span className="k"> · {detail.data.confidence_label}</span>
          </div>
          {detail.data.detail && <div className="desc" style={{ marginTop: 6 }}>{detail.data.detail}</div>}
          {detail.data.evidence && <div className="evidence">「{detail.data.evidence}」</div>}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add CSS for the toggle control**

Append to `frontend/src/styles.css` (after the `.legend` block, before `#graph`):

```css
.graph-controls { margin-bottom: 12px; font-size: 13px; color: var(--muted); }
.graph-controls label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
```

- [ ] **Step 3: Manual verification in browser**

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173/works/dd89e648bda1` (or any existing work with many places — this work's `graph.json` on disk already has 226 places / 84 characters per the design doc's measured baseline) and go to the "人物关系" tab. Verify:
1. The graph renders with visibly fewer disconnected grey boxes than before (character nodes plus at most 15 place nodes).
2. A line reading "显示全部地点（共 226 个，默认只显示连接最多的 15 个）" with a checkbox appears above the graph.
3. Checking the box redraws the graph including all 226 places; unchecking returns to the filtered view.
4. Character (dot) nodes and their edges are unaffected by the toggle.
5. Clicking a node/edge still opens the detail panel as before.

- [ ] **Step 4: Stage changes (do NOT commit — wait for user approval)**

```bash
git add frontend/src/pages/ReaderPage.jsx frontend/src/styles.css
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

## Phase 2: 修复"你可能想问" (Suggested Questions) — design §4.2

### Task 4: `summarize()` generates real suggested questions (fake + LLM paths), returns a 4-tuple

**Files:**
- Modify: `backend/app/pipeline/summarize.py` (imports at top; `_fake_summary`; `_llm_summary`; `summarize`; new `_fake_suggested_questions` helper)
- Test: `backend/tests/test_summarize.py` (new file)

**Interfaces:**
- Consumes: `EntityRegistry` from `merge.py` (unchanged), `SuggestedQuestion{question, rationale}` from `models.py:144` (unchanged, reused — no new model).
- Produces: `summarize(registry, chapters, communities, community_labels, id_to_name, title, chapter_titles=None) -> tuple[LayeredSummary, list[SettingCard], list[SuggestedQuestion], Optional[dict]]` — **return type changes from a 3-tuple to a 4-tuple**, with `suggested_questions` inserted as the 3rd element (before `spine_payload`, which stays last). Task 5 (`orchestrator.py`) consumes this new 4-tuple shape directly: `layered, setting_cards, suggested_questions, spine_payload = summarize(...)`.
- Also produces: `_fake_suggested_questions(spine_payload: dict) -> list[SuggestedQuestion]` (module-private helper, testable directly).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_summarize.py`:

```python
"""Tests for suggested-question generation (design §4.2)."""

from app.pipeline.summarize import _fake_suggested_questions, summarize
from app.pipeline.merge import EntityRegistry
from app.models import Character, SuggestedQuestion

# Keywords that indicate graphify's old code-review-oriented questions leaked
# through (e.g. "Should `X` be split into smaller, more focused modules?").
_CODE_REVIEW_KEYWORDS = ("模块", "拆分", "重构", "split", "module", "refactor")


def _sample_spine_payload():
    return {
        "main_thread": "贾宝玉与林黛玉的爱情悲剧",
        "tone": "沉重悲剧",
        "protagonists": ["贾宝玉", "林黛玉"],
        "key_beats": ["贾宝玉初见林黛玉", "薛宝钗入府", "林黛玉病重离世"],
        "timeline_text": "",
    }


def test_fake_suggested_questions_returns_three_to_five():
    questions = _fake_suggested_questions(_sample_spine_payload())
    assert 3 <= len(questions) <= 5
    assert all(isinstance(q, SuggestedQuestion) for q in questions)
    assert all(q.question.strip() for q in questions)


def test_fake_suggested_questions_grounded_in_protagonists_and_beats():
    questions = _fake_suggested_questions(_sample_spine_payload())
    joined = " ".join(q.question for q in questions)
    assert "贾宝玉" in joined
    assert "林黛玉" in joined


def test_fake_suggested_questions_avoid_code_review_style():
    questions = _fake_suggested_questions(_sample_spine_payload())
    joined = " ".join(q.question for q in questions)
    for kw in _CODE_REVIEW_KEYWORDS:
        assert kw not in joined


def test_fake_suggested_questions_handles_missing_fields():
    # No protagonists, no key_beats — must not crash, still returns something.
    questions = _fake_suggested_questions({})
    assert isinstance(questions, list)


def test_summarize_fake_path_returns_four_tuple_with_questions(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "USE_FAKE_LLM", True)
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉"))
    reg.add_character(Character(name="林黛玉"))
    reg.events.append(
        {"summary": "初遇", "chapter": "ch0001", "participants": ["贾宝玉", "林黛玉"], "order_hint": 0}
    )
    result = summarize(reg, ["ch0001"], {0: ["贾宝玉", "林黛玉"]}, {0: "情节线"}, {}, "红楼梦")
    assert len(result) == 4
    layered, cards, suggested_questions, spine_payload = result
    assert isinstance(suggested_questions, list)
    assert len(suggested_questions) >= 1
    assert all(isinstance(q, SuggestedQuestion) for q in suggested_questions)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_summarize.py -v`
Expected: FAIL — `_fake_suggested_questions` does not exist yet (ImportError), and `summarize()` still returns a 3-tuple.

- [ ] **Step 3: Add `SuggestedQuestion` import and the `_fake_suggested_questions` helper**

In `backend/app/pipeline/summarize.py`, change the imports block (currently lines 21-26):

```python
from ..models import (
    ArcSummary,
    ChapterSummary,
    LayeredSummary,
    SettingCard,
    SuggestedQuestion,
)
```

Add this new function right before `_fake_setting_cards` (i.e. just above line 580, `def _fake_setting_cards(...)`):

```python
def _fake_suggested_questions(spine_payload: dict) -> list[SuggestedQuestion]:
    """Deterministic, template-based suggested questions for offline/tests.

    Grounded in the same spine_payload (protagonists/key_beats/main_thread)
    used to power the 故事正片 tab, so questions are always about this book's
    actual plot — never graphify's code-review-style output (design §4.2).
    """
    protagonists = spine_payload.get("protagonists") or []
    key_beats = spine_payload.get("key_beats") or []
    main_thread = spine_payload.get("main_thread") or ""

    questions: list[SuggestedQuestion] = []
    if len(protagonists) >= 2:
        a, b = protagonists[0], protagonists[1]
        questions.append(
            SuggestedQuestion(
                question=f"{a}和{b}之间是什么关系？",
                rationale=f"{a}与{b}是本书的核心人物。",
            )
        )
    elif protagonists:
        questions.append(
            SuggestedQuestion(
                question=f"{protagonists[0]}在故事里扮演什么角色？",
                rationale="主角是理解全书情节的起点。",
            )
        )
    if key_beats:
        questions.append(
            SuggestedQuestion(
                question=f"“{key_beats[0]}”这件事是怎么发生的？",
                rationale="这是故事的开端情节。",
            )
        )
    if len(key_beats) > 1:
        questions.append(
            SuggestedQuestion(
                question=f"“{key_beats[-1]}”之后故事是如何收尾的？",
                rationale="这是故事走向结局的关键节点。",
            )
        )
    questions.append(
        SuggestedQuestion(
            question="这本书最终的结局是什么？",
            rationale="结局往往是读者最关心的问题。",
        )
    )
    if main_thread:
        questions.append(
            SuggestedQuestion(
                question=f"“{main_thread}”这条主线是如何推进的？",
                rationale="主线是贯穿全书的核心脉络。",
            )
        )
    return questions[:5]
```

- [ ] **Step 4: Wire `_fake_suggested_questions` into `_fake_summary` and return a 4-tuple**

In `_fake_summary` (currently lines 499-577), change the final section. Find:

```python
    cards = _fake_setting_cards(registry, communities, community_labels)

    # Simplified 编导纲要 so the offline path also powers the 故事正片 tab.
    fake_beats = [e.get("summary", "") for e in ordered_events if e.get("summary")][:8]
    spine_payload = {
        "main_thread": one_liner,
        "tone": TONE_LIGHT,
        "protagonists": main_names,
        "key_beats": fake_beats,
        "timeline_text": _plot_timeline(registry, chapters),
    }
    return layered, cards, spine_payload
```

Replace with:

```python
    cards = _fake_setting_cards(registry, communities, community_labels)

    # Simplified 编导纲要 so the offline path also powers the 故事正片 tab.
    fake_beats = [e.get("summary", "") for e in ordered_events if e.get("summary")][:8]
    spine_payload = {
        "main_thread": one_liner,
        "tone": TONE_LIGHT,
        "protagonists": main_names,
        "key_beats": fake_beats,
        "timeline_text": _plot_timeline(registry, chapters),
    }
    suggested_questions = _fake_suggested_questions(spine_payload)
    return layered, cards, suggested_questions, spine_payload
```

- [ ] **Step 5: Add a real-LLM suggested-questions step to `_llm_summary` and return a 4-tuple**

In `_llm_summary` (currently lines 418-477), find the tail end:

```python
    cards_prompt = f"书名：{title}\n\n{digest}\n\n请生成3-6张设定卡（世界观/主题/关键概念），每张有title与content。"
    # 设定卡失败不应连累已经生成好的分层摘要——单独兜底为假数据卡。
    try:
        cards = _structured_with_retry(agent, SettingCards, cards_prompt, what="SettingCards").cards
    except Exception:  # noqa: BLE001
        logger.exception("SettingCards generation failed; keeping LLM summary with fallback cards")
        cards = _fake_setting_cards(registry, communities, community_labels)
    return layered, cards, spine_payload
```

Replace with:

```python
    cards_prompt = f"书名：{title}\n\n{digest}\n\n请生成3-6张设定卡（世界观/主题/关键概念），每张有title与content。"
    # 设定卡失败不应连累已经生成好的分层摘要——单独兜底为假数据卡。
    try:
        cards = _structured_with_retry(agent, SettingCards, cards_prompt, what="SettingCards").cards
    except Exception:  # noqa: BLE001
        logger.exception("SettingCards generation failed; keeping LLM summary with fallback cards")
        cards = _fake_setting_cards(registry, communities, community_labels)

    # Step 3: 你可能想问——复用同一 agent，基于已经算好的主线/主角/节拍与概述，
    # 生成能被 agentic Q&A 真正回答的问题，而不是 graphify 的代码审查式问题。
    # 失败时独立兜底到确定性模板问题，绝不拖累已经生成好的摘要（同 SettingCards 模式）。
    try:
        class SuggestedQuestionsSchema(__import__("pydantic").BaseModel):
            questions: list[SuggestedQuestion]

        questions_prompt = (
            f"书名：{title}\n\n{spine_block}\n\n"
            f"故事概述：{layered.overview}\n\n"
            "请基于以上信息，生成3-5个读者读完这段简介后可能想问、且可以通过阅读小说实际章节内容"
            "回答的问题（例如人物关系、情节转折、结局走向）。\n"
            "严格禁止：\n"
            "- 代码审查风格的问题（例如“是否应该拆分模块/重构”之类，与本书内容无关）；\n"
            "- 过于主观、开放、无法从原文找到答案的问题（例如“你觉得这本书好看吗”）。\n"
            "每个问题附一句简短 rationale（说明读者为什么可能想问这个）。"
        )
        suggested_questions = _structured_with_retry(
            agent, SuggestedQuestionsSchema, questions_prompt, what="SuggestedQuestions"
        ).questions
    except Exception:  # noqa: BLE001
        logger.exception("SuggestedQuestions generation failed; falling back to heuristic questions")
        suggested_questions = _fake_suggested_questions(spine_payload or {})

    return layered, cards, suggested_questions, spine_payload
```

- [ ] **Step 6: Update the `summarize()` docstring and return-type annotation**

Change the `summarize` function signature and docstring (currently lines 365-387):

```python
def summarize(
    registry: EntityRegistry,
    chapters: list[str],
    communities: dict,
    community_labels: dict,
    id_to_name: dict,
    title: str,
    chapter_titles: Optional[dict] = None,
) -> tuple[LayeredSummary, list[SettingCard], list[SuggestedQuestion], Optional[dict]]:
    """Return (LayeredSummary, setting_cards, suggested_questions, spine_payload).

    suggested_questions are 3-5 plot-grounded questions the reader can have
    truthfully answered via the agentic Q&A tab (design §4.2) — replacing
    graphify's code-review-oriented analyze.suggest_questions output.

    spine_payload is the 编导纲要 (main_thread/tone/protagonists/key_beats/timeline_text)
    used to power the on-demand "故事正片" beat narration, or None if unavailable.
    """
```

(Only the return-type annotation and docstring change; the function body — the `if config.USE_FAKE_LLM: ... else: try/except` dispatch — is unchanged, since `_fake_summary`/`_llm_summary` now both return 4-tuples already.)

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_summarize.py -v`
Expected: PASS (5 passed)

- [ ] **Step 8: Run full backend suite**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: `test_pipeline_integration.py` will now FAIL — it still unpacks `summarize()`'s old 3-tuple shape indirectly via `orchestrator.py` (Task 5 fixes this). This is expected at this checkpoint; do not attempt to fix `orchestrator.py` in this task. Confirm the failure is specifically in `test_pipeline_integration.py` (a `ValueError: too many values to unpack` from `orchestrator.py`'s `layered, setting_cards, spine_payload = summarize(...)` line) and not elsewhere.

- [ ] **Step 9: Stage changes (do NOT commit — wait for user approval)**

```bash
git add backend/app/pipeline/summarize.py backend/tests/test_summarize.py
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

### Task 5: Remove graphify's dead `suggest_questions` code; wire `orchestrator.py` to the new 4-tuple

**Files:**
- Modify: `backend/app/pipeline/graph.py` (`GraphArtifacts` dataclass; `run_graphify`; module docstring)
- Modify: `backend/app/pipeline/orchestrator.py` (imports; `run_pipeline`; remove `_build_suggested_questions`)
- Test: `backend/tests/test_pipeline_integration.py` (append assertions)

**Interfaces:**
- Consumes: `summarize(...)`'s new 4-tuple return from Task 4.
- Produces: `GraphArtifacts` dataclass loses its `suggested_questions` field (any future code must not reference `artifacts.suggested_questions`). `run_pipeline(...)` now takes `suggested_questions` straight from `summarize()`'s return value instead of building it from `artifacts.suggested_questions`.

- [ ] **Step 1: Write the failing test (extend existing integration test)**

In `backend/tests/test_pipeline_integration.py`, add these lines to the end of `test_pipeline_end_to_end` (after the existing `assert pkg.main_characters, "no main characters produced"` line):

```python
    # Suggested questions must be real, plot-grounded questions (design §4.2) —
    # not graphify's code-review-oriented output, and not empty/decorative.
    assert pkg.suggested_questions, "no suggested questions produced"
    joined_questions = " ".join(q.question for q in pkg.suggested_questions)
    for bad_kw in ("模块", "拆分", "重构", "split", "module", "refactor"):
        assert bad_kw not in joined_questions
```

Also add a new assertion to `test_pipeline_end_to_end` right after the `graph.json` block (after `assert "mention_count" in node`), to lock in Task 7's persistence requirement early isn't needed here — skip, that belongs to Task 7's own test. Keep this task's diff limited to the suggested-questions assertions above.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_pipeline_integration.py -v`
Expected: FAIL — `orchestrator.py` still calls `summarize()` expecting a 3-tuple, so this currently raises `ValueError: too many values to unpack` before the new assertions are even reached (same failure noted at the end of Task 4).

- [ ] **Step 3: Remove `suggest_questions` from `graph.py`**

In `backend/app/pipeline/graph.py`:

1. Update the module docstring (lines 1-13) — remove the `suggest_questions` step from the pipeline diagram:

```python
"""graphify integration (design §5.3, §7 graph output).

Converts the deduplicated EntityRegistry into graphify's extraction-JSON schema,
then runs the canonical graphify build pipeline:

    build_from_json -> cluster -> score_all -> god_nodes
                    -> export.to_json + export.to_html

Custom node/edge fields (node_type, description, category, detail, evidence,
mention_count, confidence...) are preserved by build_from_json straight into
graph.json, which is exactly what the reader UI consumes.

Note: graphify's analyze.suggest_questions (betweenness-centrality, code-review
oriented) is intentionally NOT used — it produces nonsensical questions for
novel text. Suggested questions are instead generated in summarize.py from the
already-computed story spine (design §4.2).
"""
```

2. Remove the `suggested_questions: list` field from `GraphArtifacts` (currently line 42):

```python
@dataclass
class GraphArtifacts:
    graph: object  # networkx.Graph
    communities: dict  # community_id -> [node_id, ...]
    community_labels: dict  # community_id -> label
    god_nodes: list  # ranked hub nodes
    id_to_label: dict  # node_id -> display label
    label_to_id: dict
```

3. Remove the `suggest_questions` call (currently lines 196-199) inside `run_graphify`. Find:

```python
    try:
        suggested = analyze.suggest_questions(G, communities, community_labels, top_n=7) or []
    except Exception:  # noqa: BLE001
        suggested = []

    graph_json_path.parent.mkdir(parents=True, exist_ok=True)
```

Replace with:

```python
    graph_json_path.parent.mkdir(parents=True, exist_ok=True)
```

4. Remove `suggested_questions=suggested,` from the `GraphArtifacts(...)` construction (currently line 221):

```python
    return GraphArtifacts(
        graph=G,
        communities=communities,
        community_labels=community_labels,
        god_nodes=gods,
        id_to_label=id_to_name,
        label_to_id=name_to_id,
    )
```

- [ ] **Step 4: Wire `orchestrator.py` to the new 4-tuple and remove `_build_suggested_questions`**

In `backend/app/pipeline/orchestrator.py`:

1. Update the imports block (currently lines 18-23) — remove `SuggestedQuestion` (no longer referenced once `_build_suggested_questions` is deleted):

```python
from ..models import (
    MainCharacter,
    WorkPackage,
    WorkStatus,
)
```

2. Replace the `summarize()` call and the two lines after it (currently lines 142-160):

```python
        layered, setting_cards, spine_payload = summarize(
            registry,
            chapter_ids,
            artifacts.communities,
            artifacts.community_labels,
            artifacts.id_to_label,
            title,
            chapter_titles,
        )

        # Persist the 编导纲要 so the 故事正片 tab can expand beats on demand later.
        if spine_payload and spine_payload.get("key_beats"):
            (wdir / "spine.json").write_text(
                json.dumps(spine_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        main_characters = _build_main_characters(artifacts, registry)
        suggested = _build_suggested_questions(artifacts)
```

with:

```python
        layered, setting_cards, suggested_questions, spine_payload = summarize(
            registry,
            chapter_ids,
            artifacts.communities,
            artifacts.community_labels,
            artifacts.id_to_label,
            title,
            chapter_titles,
        )

        # Persist the 编导纲要 so the 故事正片 tab can expand beats on demand later.
        if spine_payload and spine_payload.get("key_beats"):
            (wdir / "spine.json").write_text(
                json.dumps(spine_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        main_characters = _build_main_characters(artifacts, registry)
```

3. Update the `WorkPackage(...)` construction right below (currently line 170) to use `suggested_questions` instead of `suggested`:

```python
        package = WorkPackage(
            work_id=work_id,
            title=title,
            granularity=granularity,
            layered_summary=layered,
            setting_cards=setting_cards,
            graph_ref="graph.json",
            main_characters=main_characters,
            suggested_questions=suggested_questions,
        )
```

4. Delete the entire `_build_suggested_questions` function (currently lines 215-232, the last function in the file):

```python
def _build_suggested_questions(artifacts) -> list[SuggestedQuestion]:
    out: list[SuggestedQuestion] = []
    for q in artifacts.suggested_questions:
        if isinstance(q, dict):
            # graphify may emit a placeholder like
            # {"type": "no_signal", "question": None, "why": ...} when it has
            # no basis for questions — skip those instead of stringifying.
            if q.get("type") == "no_signal" or not q.get("question") and not q.get("text"):
                continue
            question = q.get("question") or q.get("text")
            rationale = q.get("rationale") or q.get("reason") or q.get("why") or ""
        else:
            question = str(q).strip()
            rationale = ""
        if not question:
            continue
        out.append(SuggestedQuestion(question=question, rationale=rationale))
    return out
```

Delete this whole function — nothing else in the file references it after step 4.2.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_pipeline_integration.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Run full backend suite**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: all pass (26 from Task 2 + 5 from Task 4 = 31, no regressions)

- [ ] **Step 7: Stage changes (do NOT commit — wait for user approval)**

```bash
git add backend/app/pipeline/graph.py backend/app/pipeline/orchestrator.py backend/tests/test_pipeline_integration.py
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

### Task 6: Frontend — clickable suggested questions jump to Ask tab and auto-submit

**Files:**
- Modify: `frontend/src/pages/ReaderPage.jsx` (`ReaderPage`, `Overview`, `AskFeature`)
- Modify: `frontend/src/styles.css` (`.q-item` → clickable button styling)

**Interfaces:**
- Consumes: `pkg.suggested_questions[]` (now real questions per Task 5), existing `askQuestion(id, question)` / `getAskHistory(id)` from `api.js` (unchanged).
- Produces: `AskFeature({ id, seed })` — new `seed` prop shape `{ question: string, nonce: number } | null`. `Overview({ ls, pkg, onAsk })` — new `onAsk: (question: string) => void` prop. No later task depends on these (leaf UI change).

No automated frontend test exists. Verified manually per Step 4.

- [ ] **Step 1: Lift `seed`/`onAsk` state into `ReaderPage`**

In `frontend/src/pages/ReaderPage.jsx`, replace the `ReaderPage` function (lines 16-76):

```jsx
export default function ReaderPage() {
  const { id } = useParams();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");
  const [askSeed, setAskSeed] = useState(null); // { question, nonce } | null

  useEffect(() => {
    getWork(id).then(setPkg).catch((e) => setError(e.message));
  }, [id]);

  function askAbout(question) {
    setAskSeed({ question, nonce: Date.now() });
    setTab("ask");
  }

  if (error) {
    return (
      <div className="reader-container">
        <Link to="/" className="muted">← 返回首页</Link>
        <div className="error-banner" style={{ marginTop: 16 }}>{error}</div>
      </div>
    );
  }
  if (!pkg) {
    return (
      <div className="reader-container">
        <div className="empty"><span className="spinner" /> 加载中…</div>
      </div>
    );
  }

  const ls = pkg.layered_summary || {};

  return (
    <div className="reader-container">
      <div className="reader-header">
        <div>
          <Link to="/" className="muted">← 返回首页</Link>
          <h1 className="reader-title">{pkg.title}</h1>
        </div>
        <a href={graphHtmlUrl(id)} target="_blank" rel="noreferrer" className="btn ghost">
          完整图谱 ↗
        </a>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`tab${tab === t.key ? " active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview ls={ls} pkg={pkg} onAsk={askAbout} />}
      {tab === "story" && <StoryFeature id={id} />}
      {tab === "arcs" && <Arcs ls={ls} id={id} />}
      {tab === "graph" && <GraphTab id={id} />}
      {tab === "ask" && <AskFeature id={id} seed={askSeed} />}
      {tab === "settings" && <Settings cards={pkg.setting_cards || []} />}
    </div>
  );
}
```

- [ ] **Step 2: Make suggested questions clickable in `Overview`**

Replace the `Overview` function (lines 78-121):

```jsx
function Overview({ ls, pkg, onAsk }) {
  const mains = pkg.main_characters || [];
  const questions = pkg.suggested_questions || [];
  return (
    <div>
      <div className="card">
        {ls.one_liner && <p className="one-liner">{ls.one_liner}</p>}
        {ls.story_hook && <p className="story-hook">{ls.story_hook}</p>}
        {ls.overview && <p className="overview">{ls.overview}</p>}
      </div>

      <h2 className="section-title">主要人物</h2>
      {mains.length === 0 ? (
        <div className="empty">未识别到主要人物</div>
      ) : (
        <div className="grid cols">
          {mains.map((c) => (
            <div key={c.id} className="card char-card">
              <div>
                <span className="name">{c.label}</span>
              </div>
              {c.description && <div className="desc">{c.description}</div>}
              <div className="mention">提及 {c.mention_count} 次</div>
            </div>
          ))}
        </div>
      )}

      {questions.length > 0 && (
        <div className="questions">
          <h2 className="section-title">你可能想问</h2>
          <div className="card">
            {questions.map((q, i) => (
              <button
                key={i}
                type="button"
                className="q-item"
                onClick={() => onAsk(q.question)}
              >
                <div className="q">{q.question}</div>
                {q.rationale && <div className="r">{q.rationale}</div>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

(Changes: label text drops "（展示用）"; each question becomes a `<button>` with `onClick={() => onAsk(q.question)}` instead of a plain `<div>`.)

- [ ] **Step 3: Refactor `AskFeature` to accept a `seed` prop and expose `runAsk`**

Replace the `AskFeature` function (lines 123-193):

```jsx
function AskFeature({ id, seed }) {
  const [history, setHistory] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getAskHistory(id)
      .then((r) => setHistory(r.history || []))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [id]);

  async function runAsk(questionText) {
    const question = (questionText || "").trim();
    if (!question || loading) return;
    setLoading(true);
    setError("");
    try {
      const res = await askQuestion(id, question);
      setHistory((h) => [...h, { question, answer: res.answer, cited: res.cited || [] }]);
      setQ("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  // A "seed" question (design §4.2c: click a suggested question -> jump here
  // and auto-submit). `nonce` changes on every click so re-clicking the same
  // question re-submits it instead of being a no-op.
  useEffect(() => {
    if (seed && seed.question) {
      runAsk(seed.question);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed && seed.nonce]);

  async function submit(e) {
    e.preventDefault();
    await runAsk(q);
  }

  return (
    <div>
      <div className="card">
        <p className="muted" style={{ margin: 0 }}>
          基于这本书的知识图谱与情节信息回答你的问题（仅依据已分析内容，不会凭空编造）。
        </p>
        <form onSubmit={submit} className="ask-form">
          <input
            className="ask-input"
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="例如：主角和反派是什么关系？"
            disabled={loading}
          />
          <button type="submit" className="btn" disabled={loading || !q.trim()}>
            {loading ? "思考中…" : "提问"}
          </button>
        </form>
        {error && <div className="error-banner" style={{ marginTop: 8 }}>{error}</div>}
      </div>

      {loaded && history.length === 0 && !loading && (
        <div className="empty">还没有问答记录，试着问一个问题吧。</div>
      )}

      <div className="ask-history">
        {[...history].reverse().map((item, i) => (
          <div key={i} className="ask-qa card">
            <p className="ask-q">Q：{item.question}</p>
            <p className="ask-a">{item.answer}</p>
            {item.cited && item.cited.length > 0 && (
              <p className="muted ask-cited">涉及：{item.cited.join("、")}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Update `.q-item` CSS for its new `<button>` semantics**

In `frontend/src/styles.css`, replace the existing `.q-item` rules (currently lines 240-242):

```css
.q-item {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  padding: 10px 0;
  border-top: 1px dashed var(--line);
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.q-item:hover .q { color: var(--accent-ink); text-decoration: underline; }
.q-item .q { font-weight: 600; }
.q-item .r { color: var(--muted); font-size: 13px; }
```

- [ ] **Step 5: Manual verification in browser**

```bash
cd backend && PYTHONPATH=. NOVEL_KG_USE_FAKE_LLM=1 uvicorn app.main:app --reload &
cd frontend && npm run dev
```

Re-upload (or delete + re-upload) a small `.txt` novel so it's processed with the new code (old works on disk still carry graphify's old `suggested_questions`, per the design's explicit no-backfill policy — verify separately in Step 6 that old works degrade gracefully). On the freshly-processed work:
1. Open the "概览" tab. Confirm the section header reads "你可能想问" (no "（展示用）" suffix).
2. Confirm each question is grounded in the book's actual plot (mentions character names / plot beats), not "Should `X` be split into modules?" style text.
3. Click a question. Confirm the view jumps to the "问答" tab and the question is auto-submitted (loading indicator appears, then an answer appears in the history without you typing/clicking submit).
4. Click the same question again from "概览" while already on a different tab — confirm it re-jumps and re-submits (nonce mechanism working).

- [ ] **Step 6: Manual verification of graceful degradation on an old work**

Open one of the 11 pre-existing works in `data/works/` (e.g. `dd89e648bda1`) whose `summary.json` predates this change. Confirm:
- If its `suggested_questions` is empty/absent, the "你可能想问" section simply doesn't render (no error, no empty card).
- If it still has graphify's old garbage questions, they will render as before (clickable now) — this is acceptable per the design's no-backfill policy; only newly (re)processed works get real questions.

- [ ] **Step 7: Stage changes (do NOT commit — wait for user approval)**

```bash
git add frontend/src/pages/ReaderPage.jsx frontend/src/styles.css
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

## Phase 3: 交互式时间线功能 (Interactive Timeline) — design §4.3

### Task 7: Persist `registry.events` to `events.json` right after extraction

**Files:**
- Modify: `backend/app/pipeline/orchestrator.py` (`run_pipeline`)
- Test: `backend/tests/test_pipeline_integration.py` (append assertions)

**Interfaces:**
- Consumes: `registry.events: list[dict]` from `EntityRegistry` (`merge.py:73`, unchanged) — each item has keys `summary, chapter, participants, order_hint`.
- Produces: `{work_dir}/events.json` — a JSON array of those raw dicts, written to disk. Task 8's `build_timeline()` and Task 9's route both consume this file's exact shape.

- [ ] **Step 1: Write the failing test**

Append to `test_pipeline_end_to_end` in `backend/tests/test_pipeline_integration.py`, after the `graph.json`-related assertions (after `assert "mention_count" in node`) and before the `summary.json` assertions:

```python
    # events.json must be persisted right after extraction (design §4.3) so
    # timeline data survives even if a later phase (summarize) fails.
    events_path = config.work_dir(work_id) / "events.json"
    assert events_path.exists(), "events.json was not persisted"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    assert isinstance(events, list)
    assert events, "no events persisted"
    assert all({"summary", "chapter", "participants", "order_hint"} <= set(e.keys()) for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_pipeline_integration.py -v`
Expected: FAIL — `events.json` does not exist yet.

- [ ] **Step 3: Persist `events.json` in `orchestrator.py`**

In `backend/app/pipeline/orchestrator.py`, find:

```python
        if not registry.characters:
            raise ParseError("未能抽取到任何人物，无法构建图谱")

        # 4. Build graph -----------------------------------------------------
```

Replace with:

```python
        if not registry.characters:
            raise ParseError("未能抽取到任何人物，无法构建图谱")

        # Persist raw events immediately after extraction (before graph/summarize)
        # so timeline data survives even if a later phase fails (design §4.3).
        (config.work_dir(work_id) / "events.json").write_text(
            json.dumps(registry.events, ensure_ascii=False), encoding="utf-8"
        )

        # 4. Build graph -----------------------------------------------------
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_pipeline_integration.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: all pass (31 from Task 5 + 0 net new in this file, still 31 — this task adds assertions to an existing test, not a new test function)

- [ ] **Step 6: Stage changes (do NOT commit — wait for user approval)**

```bash
git add backend/app/pipeline/orchestrator.py backend/tests/test_pipeline_integration.py
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

### Task 8: `TimelineEvent` model + `backend/app/pipeline/timeline.py` (`build_timeline`)

**Files:**
- Modify: `backend/app/models.py` (add `TimelineEvent`)
- Create: `backend/app/pipeline/timeline.py`
- Test: `backend/tests/test_timeline.py` (new file)

**Interfaces:**
- Consumes: raw `events.json` shape from Task 7 (`list[dict]` with `summary/chapter/participants/order_hint` keys), `chapters.json` shape (`dict[chapter_id, {title, text}]`, already persisted by the existing parse phase, unchanged).
- Produces: `models.TimelineEvent{seq: int, chapter_id: str, chapter_title: str, summary: str, participants: list[str]}` and `timeline.build_timeline(events: list[dict], chapters: dict) -> list[TimelineEvent]`. Task 9's route handler calls `build_timeline(...)` directly and serializes the result.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_timeline.py`:

```python
"""Tests for the timeline flattening module (design §4.3)."""

from app.pipeline.timeline import build_timeline

CHAPTERS = {
    "ch0001": {"title": "第一章", "text": "..."},
    "ch0002": {"title": "第二章", "text": "..."},
}


def test_build_timeline_preserves_chapter_order_and_sorts_by_order_hint():
    events = [
        {"summary": "B事件", "chapter": "ch0001", "participants": ["甲"], "order_hint": 2},
        {"summary": "A事件", "chapter": "ch0001", "participants": ["甲", "乙"], "order_hint": 1},
        {"summary": "C事件", "chapter": "ch0002", "participants": ["乙"], "order_hint": 1},
    ]
    timeline = build_timeline(events, CHAPTERS)
    assert [e.summary for e in timeline] == ["A事件", "B事件", "C事件"]
    assert [e.chapter_id for e in timeline] == ["ch0001", "ch0001", "ch0002"]
    assert [e.chapter_title for e in timeline] == ["第一章", "第一章", "第二章"]
    assert [e.seq for e in timeline] == [0, 1, 2]
    assert timeline[0].participants == ["甲", "乙"]


def test_build_timeline_none_order_hint_treated_as_zero():
    events = [
        {"summary": "有序事件", "chapter": "ch0001", "participants": [], "order_hint": 0},
        {"summary": "无序事件", "chapter": "ch0001", "participants": [], "order_hint": None},
    ]
    timeline = build_timeline(events, CHAPTERS)
    # Both order_hint 0 and None sort equally; a stable sort keeps insertion order.
    assert [e.summary for e in timeline] == ["有序事件", "无序事件"]


def test_build_timeline_unknown_chapter_appended_at_end_and_falls_back_to_id():
    events = [
        {"summary": "已知章节事件", "chapter": "ch0001", "participants": [], "order_hint": 0},
        {"summary": "未知章节事件", "chapter": "ch9999", "participants": [], "order_hint": 0},
    ]
    timeline = build_timeline(events, CHAPTERS)
    assert [e.chapter_id for e in timeline] == ["ch0001", "ch9999"]
    assert timeline[-1].chapter_title == "ch9999"  # not in CHAPTERS -> falls back to id


def test_build_timeline_empty_events_returns_empty_list():
    assert build_timeline([], CHAPTERS) == []


def test_build_timeline_missing_chapter_key_defaults_to_empty_string():
    events = [{"summary": "无章节事件", "participants": [], "order_hint": 0}]
    timeline = build_timeline(events, CHAPTERS)
    assert timeline[0].chapter_id == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_timeline.py -v`
Expected: FAIL — `app.pipeline.timeline` module does not exist yet (`ModuleNotFoundError`).

- [ ] **Step 3: Add `TimelineEvent` to `models.py`**

In `backend/app/models.py`, add this class right after `SuggestedQuestion` (currently lines 144-146), before `WorkPackage`:

```python
class SuggestedQuestion(BaseModel):
    question: str
    rationale: str = ""


class TimelineEvent(BaseModel):
    """One flattened, chapter-tagged plot event for the interactive timeline (design §4.3)."""

    seq: int
    chapter_id: str
    chapter_title: str
    summary: str
    participants: list[str] = Field(default_factory=list)


class WorkPackage(BaseModel):
```

(Only the new `TimelineEvent` class is inserted between the existing `SuggestedQuestion` and `WorkPackage` classes — nothing else in `models.py` changes.)

- [ ] **Step 4: Create `backend/app/pipeline/timeline.py`**

```python
"""Timeline construction (design §4.3).

Flattens the raw ``registry.events`` list (persisted to ``events.json`` by
``orchestrator.py`` right after extraction) into a structured,
chapter-ordered, globally-sequenced list for the interactive horizontal
timeline UI.

Kept as its own lightweight module — separate from ``summarize.py`` — so
``routes.py`` can build the timeline response without pulling in the
Strands/Bedrock agent dependency chain that ``summarize.py`` needs for its
LLM-heavy work. This mirrors ``summarize._plot_timeline``'s grouping/sorting
logic, but outputs structured JSON (via ``TimelineEvent``) instead of prompt
text.
"""

from __future__ import annotations

from ..models import TimelineEvent


def _chapter_title(chapters: dict, chapter_id: str) -> str:
    """Best-effort human chapter label; falls back to the chapter id."""
    entry = chapters.get(chapter_id) if isinstance(chapters, dict) else None
    if isinstance(entry, dict):
        title = entry.get("title")
        if title:
            return str(title)
    return chapter_id


def build_timeline(events: list[dict], chapters: dict) -> list[TimelineEvent]:
    """Flatten ``events`` into a globally-ordered, chapter-tagged list.

    ``events`` is the raw list persisted to events.json (see
    EntityRegistry.events / merge.add_extraction): each item is a dict with
    keys summary/chapter/participants/order_hint.

    ``chapters`` is the parsed chapters.json payload {chapter_id: {title,
    text}}; its key insertion order is the novel's chapter order (Python
    3.7+ dicts preserve insertion order), used to group+order events the
    same way summarize._plot_timeline does.
    """
    by_chapter: dict[str, list[dict]] = {}
    for e in events:
        by_chapter.setdefault(e.get("chapter") or "", []).append(e)

    chapter_order = list(chapters.keys()) if isinstance(chapters, dict) else []
    ordered_chapters = [c for c in chapter_order if c in by_chapter]
    for c in by_chapter:
        if c not in ordered_chapters:
            ordered_chapters.append(c)

    out: list[TimelineEvent] = []
    seq = 0
    for chapter_id in ordered_chapters:
        chapter_events = sorted(
            by_chapter.get(chapter_id, []), key=lambda x: (x.get("order_hint") or 0)
        )
        chapter_title = _chapter_title(chapters, chapter_id)
        for e in chapter_events:
            out.append(
                TimelineEvent(
                    seq=seq,
                    chapter_id=chapter_id,
                    chapter_title=chapter_title,
                    summary=e.get("summary", ""),
                    participants=list(e.get("participants") or []),
                )
            )
            seq += 1
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_timeline.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Run full backend suite**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: all pass (31 from Task 7 + 5 new = 36)

- [ ] **Step 7: Stage changes (do NOT commit — wait for user approval)**

```bash
git add backend/app/models.py backend/app/pipeline/timeline.py backend/tests/test_timeline.py
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

### Task 9: `store.read_events` + `GET /works/{id}/timeline` endpoint + route tests

**Files:**
- Modify: `backend/app/store.py` (add `read_events`)
- Modify: `backend/app/routes.py` (add `get_timeline` route)
- Test: `backend/tests/test_routes.py` (new file — first route/API test in the repo)

**Interfaces:**
- Consumes: `build_timeline(events, chapters)` from Task 8, `store.read_chapters(work_id)` (existing, unchanged), `store.get_status(work_id)` (existing, unchanged).
- Produces: `store.read_events(work_id: str) -> list | None` (returns `None` if `events.json` is absent/unreadable — mirrors `read_spine`'s convention). New HTTP route `GET /works/{work_id}/timeline` returning `{"work_id": str, "events": [TimelineEvent, ...]}` on success, `404` if `events.json` is missing. Task 10 (frontend `api.js`) calls this exact route.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_routes.py`:

```python
"""API route tests (design §4.3) — first route-level tests in this repo.

Uses FastAPI's TestClient against the real app, with DATA_ROOT redirected to
a temp dir (same pattern as test_pipeline_integration.py) so nothing touches
the real data/works/ directory.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import config, store
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "works")
    config.ensure_data_root()
    monkeypatch.setattr(config, "USE_FAKE_LLM", True)
    return TestClient(app)


def _seed_work_with_events(work_id: str) -> None:
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    from app.models import WorkStatus

    (wdir / "status.json").write_text(
        WorkStatus(work_id=work_id, title="测试作品", phase="done", progress=1.0).model_dump_json(),
        encoding="utf-8",
    )
    (wdir / "chapters.json").write_text(
        json.dumps({"ch0001": {"title": "第一章", "text": "……"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (wdir / "events.json").write_text(
        json.dumps(
            [
                {"summary": "甲登场", "chapter": "ch0001", "participants": ["甲"], "order_hint": 0},
                {"summary": "甲遇见乙", "chapter": "ch0001", "participants": ["甲", "乙"], "order_hint": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_get_timeline_returns_structured_events(client):
    _seed_work_with_events("work_with_events")
    res = client.get("/works/work_with_events/timeline")
    assert res.status_code == 200
    body = res.json()
    assert body["work_id"] == "work_with_events"
    assert len(body["events"]) == 2
    assert body["events"][0]["summary"] == "甲登场"
    assert body["events"][0]["chapter_title"] == "第一章"
    assert body["events"][0]["seq"] == 0
    assert body["events"][1]["seq"] == 1


def test_get_timeline_404_when_events_missing(client):
    wdir = config.work_dir("work_without_events")
    wdir.mkdir(parents=True, exist_ok=True)
    from app.models import WorkStatus

    (wdir / "status.json").write_text(
        WorkStatus(work_id="work_without_events", title="旧作品", phase="done", progress=1.0).model_dump_json(),
        encoding="utf-8",
    )
    res = client.get("/works/work_without_events/timeline")
    assert res.status_code == 404


def test_get_timeline_404_when_work_unknown(client):
    res = client.get("/works/nonexistent_work_id/timeline")
    assert res.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. pytest tests/test_routes.py -v`
Expected: FAIL — `GET /works/{work_id}/timeline` doesn't exist yet, `TestClient` gets a 404 from FastAPI's router-not-found (not our intentional 404), so `test_get_timeline_returns_structured_events` fails with `assert 404 == 200`.

- [ ] **Step 3: Add `read_events` to `store.py`**

In `backend/app/store.py`, add this function right after `read_chapters` (currently lines 64-69), before `_chapter_summaries_path`:

```python
def read_events(work_id: str) -> list | None:
    """Return the persisted raw event list (see EntityRegistry.events), or None."""
    path = config.work_dir(work_id) / "events.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except (ValueError, OSError):
        return None
```

- [ ] **Step 4: Add the `GET /works/{work_id}/timeline` route**

In `backend/app/routes.py`, add this route right after `get_graph_html` (currently ends at line 107), before the chapter-summary route:

```python
@router.get("/works/{work_id}/timeline")
async def get_timeline(work_id: str):
    """Return the interactive timeline (design §4.3): flattened, chapter-ordered events."""
    if store.get_status(work_id) is None:
        raise HTTPException(404, "作品不存在")
    events = store.read_events(work_id)
    if events is None:
        raise HTTPException(404, "该作品未生成时间线数据（请重新处理该作品以体验此功能）")
    chapters = store.read_chapters(work_id) or {}

    from .pipeline.timeline import build_timeline

    timeline = build_timeline(events, chapters)
    return {"work_id": work_id, "events": [e.model_dump() for e in timeline]}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. pytest tests/test_routes.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Run full backend suite**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: all pass (36 from Task 8 + 3 new = 39)

- [ ] **Step 7: Stage changes (do NOT commit — wait for user approval)**

```bash
git add backend/app/store.py backend/app/routes.py backend/tests/test_routes.py
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

### Task 10: Frontend — `getTimeline` API call + "时间线" tab + `TimelineTab` component

**Files:**
- Modify: `frontend/src/api.js` (add `getTimeline`)
- Modify: `frontend/src/pages/ReaderPage.jsx` (`TABS`, imports, tab render list, new `TimelineTab` component)
- Modify: `frontend/src/styles.css` (append `.timeline-*` styles)

**Interfaces:**
- Consumes: `GET /works/{id}/timeline` from Task 9, returning `{work_id, events: [{seq, chapter_id, chapter_title, summary, participants}]}`.
- Produces: no exported interface — leaf UI component, last task in the plan besides final verification.

No automated frontend test exists. Verified manually per Step 4.

- [ ] **Step 1: Add `getTimeline` to `api.js`**

Append to `frontend/src/api.js` (after `askQuestion`):

```js
export async function getTimeline(id) {
  return json(await fetch(`${BASE}/works/${id}/timeline`));
}
```

- [ ] **Step 2: Add the "时间线" tab and `TimelineTab` component to `ReaderPage.jsx`**

1. Update the import line at the top of `frontend/src/pages/ReaderPage.jsx` (currently line 4):

```jsx
import { getWork, getGraph, graphHtmlUrl, getChapterSummary, getBeats, getBeatStory, getAskHistory, askQuestion, getTimeline } from "../api";
```

2. Update the `TABS` array (currently lines 7-14) to insert a new tab between "故事脉络" and "人物关系":

```jsx
const TABS = [
  { key: "overview", label: "概览" },
  { key: "story", label: "故事正片" },
  { key: "arcs", label: "故事脉络" },
  { key: "timeline", label: "时间线" },
  { key: "graph", label: "人物关系" },
  { key: "ask", label: "问答" },
  { key: "settings", label: "设定卡" },
];
```

3. Update the tab-render block inside `ReaderPage` (from Task 6's version) to add the `TimelineTab` render line between `Arcs` and `GraphTab`:

```jsx
      {tab === "overview" && <Overview ls={ls} pkg={pkg} onAsk={askAbout} />}
      {tab === "story" && <StoryFeature id={id} />}
      {tab === "arcs" && <Arcs ls={ls} id={id} />}
      {tab === "timeline" && <TimelineTab id={id} />}
      {tab === "graph" && <GraphTab id={id} />}
      {tab === "ask" && <AskFeature id={id} seed={askSeed} />}
      {tab === "settings" && <Settings cards={pkg.setting_cards || []} />}
```

4. Add a new `TimelineTab` component. Insert it anywhere among the other tab components — e.g. right after the `Arcs` function (after its closing `}` at what was line 363 before this task's edits):

```jsx
function TimelineTab({ id }) {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    getTimeline(id)
      .then((r) => setEvents(r.events || []))
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div className="empty" style={{ lineHeight: 1.8 }}>
        {error}
        <div className="muted" style={{ marginTop: 6 }}>
          （此功能仅对新处理的作品生效，旧作品请重新上传处理体验。）
        </div>
      </div>
    );
  }
  if (!events) {
    return <div className="empty"><span className="spinner" /> 加载中…</div>;
  }
  if (events.length === 0) {
    return <div className="empty">未生成任何情节事件</div>;
  }

  // Group consecutive events by chapter so we can render a chapter-title
  // band above each chapter's run of event cards on the horizontal track.
  const groups = [];
  for (const e of events) {
    const last = groups[groups.length - 1];
    if (last && last.chapter_id === e.chapter_id) {
      last.events.push(e);
    } else {
      groups.push({ chapter_id: e.chapter_id, chapter_title: e.chapter_title, events: [e] });
    }
  }

  return (
    <div>
      <p className="muted" style={{ margin: "0 0 12px" }}>
        按章节顺序排列的关键情节事件，横向滚动查看，点击卡片展开详情。
      </p>
      <div className="timeline-track">
        {groups.map((g, gi) => (
          <div key={gi} className="timeline-chapter-group">
            <div className="timeline-chapter-label">{g.chapter_title}</div>
            <div className="timeline-chapter-events">
              {g.events.map((e) => (
                <button
                  key={e.seq}
                  type="button"
                  className={`timeline-card${selected?.seq === e.seq ? " active" : ""}`}
                  onClick={() => setSelected(selected?.seq === e.seq ? null : e)}
                >
                  {e.summary}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <div className="graph-detail">
          <div className="k">{selected.chapter_title} · 第 {selected.seq + 1} 个事件</div>
          <div className="desc" style={{ marginTop: 6 }}>{selected.summary}</div>
          {selected.participants.length > 0 && (
            <div className="members" style={{ marginTop: 6 }}>参与者：{selected.participants.join("、")}</div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add CSS for the horizontal timeline track**

Append to `frontend/src/styles.css`:

```css
.timeline-track { display: flex; gap: 20px; overflow-x: auto; padding: 8px 4px 16px; }
.timeline-chapter-group { flex: none; display: flex; flex-direction: column; gap: 8px; min-width: 220px; }
.timeline-chapter-label {
  font-size: 13px; font-weight: 700; color: var(--accent-ink);
  background: #faf5ff; border-radius: 6px; padding: 4px 10px; display: inline-block; width: fit-content;
}
.timeline-chapter-events { display: flex; gap: 10px; }
.timeline-card {
  flex: none; width: 180px; text-align: left; background: var(--panel);
  border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px;
  font: inherit; color: inherit; cursor: pointer; line-height: 1.5; box-shadow: var(--shadow);
}
.timeline-card:hover { border-color: var(--accent); }
.timeline-card.active { border-color: var(--accent); background: #faf5ff; }
```

- [ ] **Step 4: Manual verification in browser**

```bash
cd backend && PYTHONPATH=. NOVEL_KG_USE_FAKE_LLM=1 uvicorn app.main:app --reload &
cd frontend && npm run dev
```

Upload a fresh `.txt` novel (multi-chapter, so grouping is visible) so it's processed with Task 7's `events.json` persistence. On the freshly-processed work:
1. Confirm a new "时间线" tab appears between "故事脉络" and "人物关系".
2. Open it: confirm a horizontally-scrollable strip of event cards appears, grouped under chapter-title labels, in chapter order.
3. Click a card: confirm it expands a detail panel below showing the chapter, sequence number, full summary, and participants; confirm the card gets an "active" highlight.
4. Click the same card again: confirm the detail panel collapses.
5. Open the same tab on an old pre-existing work (e.g. `dd89e648bda1`, which has no `events.json`): confirm the friendly "此功能仅对新处理的作品生效…" message appears instead of an error banner or a blank/crashed tab.

- [ ] **Step 5: Stage changes (do NOT commit — wait for user approval)**

```bash
git add frontend/src/api.js frontend/src/pages/ReaderPage.jsx frontend/src/styles.css
```

> Per user instruction: do not run `git commit`. Only stage the files above and stop; the user decides when/whether to commit.

## Final Task

### Task 11: Full regression pass + end-to-end manual demo walkthrough

**Files:** none (verification only).

**Interfaces:** none — this task only verifies the combined output of Tasks 1-10.

- [ ] **Step 1: Run the full backend suite one more time**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: all tests pass. Running tally across this plan: 21 (baseline) + 2 (Task 1) + 3 (Task 2) + 5 (Task 4) + 5 (Task 8) + 3 (Task 9) = 39 tests, 0 failures. (Tasks 3, 5, 6, 7, 10 add assertions to existing tests or are frontend-only, not new test functions.)

- [ ] **Step 2: Pick (or process) a demo book and reprocess it with the new code**

Per the design doc's migration strategy (§1: old works get suggested-questions/timeline via graceful degradation only, never backfill), the book used for the live demo must be freshly processed after all 10 tasks:

```bash
cd backend && PYTHONPATH=. NOVEL_KG_USE_FAKE_LLM=1 uvicorn app.main:app --reload &
cd frontend && npm run dev
```

Upload the intended demo novel via the HomePage (unchanged upload flow), wait for it to reach `done`, then open its reader page.

- [ ] **Step 3: End-to-end manual walkthrough checklist**

On the freshly-processed demo work, confirm all three fixes together:
1. **概览**: suggested questions are real, clickable, plot-grounded; clicking one jumps to 问答 and gets a real agentic answer.
2. **时间线**: a new tab shows a horizontal, chapter-grouped, click-to-expand event strip.
3. **人物关系**: place nodes are filtered to the top 15 by degree by default, with a working "显示全部地点" toggle; toggling shows/hides the rest without touching character nodes.
4. Confirm the untouched surfaces are still fine: HomePage upload flow, ProcessingPage polling, StoryFeature (故事正片) beat narration, Arcs (故事脉络) chapter accordion, Settings (设定卡) grid.

- [ ] **Step 4: Verify graceful degradation on an old, un-reprocessed work**

Open one of the original 11 works in `data/works/` that was never reprocessed:
1. Graph denoising still applies (pure frontend — works immediately).
2. If it has no `suggested_questions`, the "你可能想问" section doesn't render. If it has graphify's old questions, they render (now clickable) — acceptable per the no-backfill policy.
3. The "时间线" tab shows the friendly "此功能仅对新处理的作品生效…" message instead of erroring.

- [ ] **Step 5: Report results to the user**

Summarize: full test count/pass status, and the outcome of the manual walkthrough (any issues found and how they were resolved). Do NOT commit anything — leave all staged changes from Tasks 1-10 for the user to review and commit at their discretion (`git status` / `git diff --staged` to show what's pending).
