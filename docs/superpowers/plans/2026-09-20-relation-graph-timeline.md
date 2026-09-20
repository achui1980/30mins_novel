# 关系图时间维度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给人物关系图加上时间维度——章节滑块、关系演变高亮、人物出场曲线——并新增 `POST /works/{id}/reanalyze` 让旧作品可以重新分析解锁该功能。

**Architecture:** 纯增量改造。`merge.py` 在既有记录上加"按章计数"字典；新模块 `evolve.py` 用「确定性预过滤 + 强模型确认」判定哪些同人物对的多类别平行边是真正的关系演变；`graph.py` 把新字段写进 `extraction`，并在 graphify `to_json` 之后补写顶层 `chapters` / `transitions`（与既有 `locate.patch_graph_edge_locations` 同一模式）。前端一次性取 `graph.json`，滑块拖动只做 vis-network DataSet 的 `hidden` 批量更新，不重建网络。

**Tech Stack:** Python 3.11 / FastAPI / pydantic v2 / graphify / pytest；React 18 / Vite 5 / vis-network / vitest。

**Spec:** `docs/superpowers/specs/2026-09-20-relation-graph-timeline-design.md`

---

## 运行测试的方式（每一步都按这个来）

```bash
# 后端：必须在 backend/ 下且带 PYTHONPATH=.，否则 ModuleNotFoundError: app
cd backend && PYTHONPATH=. pytest -q

# 前端
cd frontend && npm run test -- --run
```

后端测试全部离线：`backend/tests/conftest.py` 已设置 `NOVEL_KG_USE_FAKE_LLM=1`。

## 提交的方式（这个仓库特有的坑）

`rtk git add <path>` **不认路径参数**，会把未跟踪的 `archify/` 一起扫进去。必须带 `--` 分隔符，并且提交后用 `git show --stat` 核对：

```bash
rtk git add -- path/one path/two
rtk git commit -m "feat: ..."
git show --stat
```

---

## File Structure

**新建**

| 文件 | 职责 |
|---|---|
| `backend/app/pipeline/evolve.py` | 关系演变判定：预过滤 + 强模型确认。不抛异常。 |
| `backend/tests/test_evolve.py` | evolve 的单元测试 |
| `frontend/src/lib/graphTimeline.js` | 纯函数：章节分桶、可见性过滤、transitions 索引 |
| `frontend/src/lib/graphTimeline.test.js` | 上述纯函数的单元测试 |
| `frontend/src/components/graph/ChapterSlider.jsx` | 章节滑块 |
| `frontend/src/components/graph/MentionSparkline.jsx` | 人物出场曲线（无依赖内联 SVG） |

**修改**

| 文件 | 改什么 |
|---|---|
| `backend/app/config.py` | 新增 `EVOLVE_STABILITY_MIN` / `EVOLVE_BATCH_SIZE` / `EVOLVE_ENABLED` |
| `backend/.env.example` | 补齐漂移的环境变量文档 |
| `backend/app/pipeline/merge.py` | `RelationRecord.chapters`、`CharacterRecord/PlaceRecord.mentions_by_chapter`、`add_*` 接受并记录 `chapter_id`、`merge_arcs`/`_apply_merge` 合并新字典 |
| `backend/app/pipeline/graph.py` | 节点/边新字段；新函数 `patch_graph_timeline` 补写顶层 `chapters`/`transitions` |
| `backend/app/pipeline/orchestrator.py` | 构造 `chapters_meta`、调用 `detect_transitions` 与 `patch_graph_timeline` |
| `backend/app/store.py` | 新增 `find_raw_path` / `clear_beat_cache` |
| `backend/app/routes.py` | 新增 `POST /works/{id}/reanalyze` |
| `backend/tests/test_merge.py`,`test_graph.py`,`test_routes.py`,`test_pipeline_integration.py` | 追加断言 |
| `frontend/src/api.js` | 错误对象带上 `status`；新增 `reanalyzeWork` |
| `frontend/src/constants.js` | 演变边样式常量 |
| `frontend/src/components/tabs/GraphTab.jsx` | 接入滑块 / hidden 过滤 / 演变边 / 右栏曲线 / 降级横幅 |
| `frontend/src/pages/ProcessingPage.jsx` | 失败卡片改成「重新分析」按钮 |
| `frontend/src/pages/ReaderPage.jsx` | 409 时跳转处理页 |

---

## Task 1: 配置项

**Files:**
- Modify: `backend/app/config.py` (在 `MAX_CONCURRENT_JOBS` 之后、`class InvalidWorkIdError` 之前插入)
- Modify: `backend/.env.example`
- Test: `backend/tests/test_config_arc.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_config_arc.py` 末尾：

```python
def test_evolve_defaults():
    from app import config

    assert config.EVOLVE_STABILITY_MIN == 2
    assert config.EVOLVE_BATCH_SIZE == 10
    assert config.EVOLVE_ENABLED is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_config_arc.py::test_evolve_defaults -q`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'EVOLVE_STABILITY_MIN'`

- [ ] **Step 3: 实现**

在 `backend/app/config.py` 里 `MAX_CONCURRENT_JOBS = int(_env("NOVEL_KG_MAX_CONCURRENT_JOBS", "3"))` 这一行之后插入：

```python

# --- 关系演变判定 (design §3.3/§8) ------------------------------------------
# 一个「关系状态」至少要出现多少次才算真实状态（低于此且只出现在单一章节的，
# 视为抽取噪声丢弃）。
EVOLVE_STABILITY_MIN = int(_env("NOVEL_KG_EVOLVE_STABILITY_MIN", "2"))
# 强模型确认时每批塞多少个候选对。
EVOLVE_BATCH_SIZE = int(_env("NOVEL_KG_EVOLVE_BATCH_SIZE", "10"))
# 总开关。关掉后 transitions 恒为空数组，但节点/边的按章分布与顶层 chapters
# 仍然照常输出——滑块与出场曲线不受影响，只是没有演变高亮。
EVOLVE_ENABLED = _env("NOVEL_KG_EVOLVE_ENABLED", "1") not in {
    "0",
    "false",
    "False",
    "no",
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_config_arc.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 补齐 .env.example**

把 `backend/.env.example` 末尾追加（审计发现原文件只记录了 ~11 个变量，这里补上其余的）：

```bash

# --- 分块 -------------------------------------------------------------------
# NOVEL_KG_CHUNK_TARGET_TOKENS=3000
# NOVEL_KG_CHUNK_MAX_TOKENS=4000

# --- Bedrock ----------------------------------------------------------------
# NOVEL_KG_BEDROCK_TIMEOUT=120

# --- 弧并行抽取 -------------------------------------------------------------
# NOVEL_KG_ARC_BLOCKS_TARGET=60
# NOVEL_KG_MIN_ARC=2
# NOVEL_KG_MAX_ARC=16
# NOVEL_KG_ARC_ANCHOR_COUNT=20
# NOVEL_KG_GLOBAL_EXTRACT_CONCURRENCY=20

# --- 强模型档（跨弧合并确认 / 关系演变确认）--------------------------------
# NOVEL_KG_STRONG_MODEL_ID=
# NOVEL_KG_STRONG_LLM_PROVIDER=

# --- 跨请求任务并发 ---------------------------------------------------------
# NOVEL_KG_MAX_CONCURRENT_JOBS=3

# --- 关系演变判定 -----------------------------------------------------------
# NOVEL_KG_EVOLVE_STABILITY_MIN=2
# NOVEL_KG_EVOLVE_BATCH_SIZE=10
# NOVEL_KG_EVOLVE_ENABLED=1
```

- [ ] **Step 6: 提交**

```bash
rtk git add -- backend/app/config.py backend/.env.example backend/tests/test_config_arc.py
rtk git commit -m "feat(config): add EVOLVE_* settings and fill .env.example drift"
git show --stat
```

---

## Task 2: `RelationRecord.chapters` —— 关系的按章分布

**Files:**
- Modify: `backend/app/pipeline/merge.py`
- Test: `backend/tests/test_merge.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_merge.py` 末尾：

```python
def test_add_relationship_accumulates_chapters():
    from app.models import Relationship
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    rel = Relationship(
        source="甲",
        target="乙",
        category="朋友",
        detail="同门",
        evidence="甲与乙同行",
        confidence=0.9,
    )
    reg.add_relationship(rel, "ch0001")
    reg.add_relationship(rel, "ch0001")
    reg.add_relationship(rel, "ch0005")

    rec = next(iter(reg.relationships.values()))
    assert rec.chapters == {"ch0001": 2, "ch0005": 1}
    assert rec.count == 3


def test_add_relationship_returns_record_and_skips_chapter_when_asked():
    from app.models import Relationship
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    rel = Relationship(
        source="甲",
        target="乙",
        category="朋友",
        detail="",
        evidence="",
        confidence=0.5,
    )
    rec = reg.add_relationship(rel, "ch0002", record_chapter=False)
    assert rec is not None
    assert rec.chapters == {}
    assert rec.count == 1
    assert rec.chapter_id == "ch0002"


def test_add_relationship_returns_none_for_self_loop():
    from app.models import Relationship
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    rel = Relationship(
        source="甲",
        target="甲",
        category="朋友",
        detail="",
        evidence="",
        confidence=0.5,
    )
    assert reg.add_relationship(rel, "ch0001") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_merge.py -q -k "chapters or record_chapter or self_loop"`
Expected: FAIL — `AttributeError: 'RelationRecord' object has no attribute 'chapters'` 以及 `assert None is not None`

- [ ] **Step 3: 实现**

3a. 在 `backend/app/pipeline/merge.py` 的 `_norm` 函数之后加一个计数合并小工具：

```python
def _merge_counts(dst: dict[str, int], src: dict[str, int]) -> None:
    """把 src 的按章计数累加进 dst（原地）。"""
    for key, value in src.items():
        dst[key] = dst.get(key, 0) + value
```

3b. 给 `RelationRecord` 加字段（在 `chapter_id: str = ""` 之后）：

```python
    # 该「关系类别」在各章出现的次数。chapter_id -> count。
    # 注意 count 不等于 sum(chapters.values())：跨弧合并时 count 走公开 API
    # 每弧只 +1，而 chapters 是真实分布，后者才是时间轴的依据。
    chapters: dict[str, int] = field(default_factory=dict)
```

3c. 改 `add_relationship` 的签名与返回值。把

```python
    def add_relationship(self, rel: Relationship, chapter_id: str = "") -> None:
```

改成

```python
    def add_relationship(
        self,
        rel: Relationship,
        chapter_id: str = "",
        *,
        record_chapter: bool = True,
    ) -> RelationRecord | None:
```

把函数里的 `return`（self-loop 那一处 `if src == tgt: return`）改成 `return None`，并在函数末尾（现有 `rec.chapter_id = chapter_id` 之后）追加：

```python
        if record_chapter and chapter_id:
            rec.chapters[chapter_id] = rec.chapters.get(chapter_id, 0) + 1
        return rec
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_merge.py -q`
Expected: PASS（原有 12 个 + 新增 3 个）

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/pipeline/merge.py backend/tests/test_merge.py
rtk git commit -m "feat(merge): record per-chapter occurrence counts on RelationRecord"
git show --stat
```

---

## Task 3: `mentions_by_chapter` —— 人物/地点的按章提及分布

**Files:**
- Modify: `backend/app/pipeline/merge.py`
- Test: `backend/tests/test_merge.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_merge.py` 末尾：

```python
def test_add_character_records_mentions_by_chapter():
    from app.models import Character
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    reg.add_character(Character(name="甲", aliases=[], role="主角", description="少年"), "ch0001")
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0001")
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0003")

    rec = reg.characters["甲"]
    assert rec.mentions_by_chapter == {"ch0001": 2, "ch0003": 1}
    assert rec.mention_count == 3


def test_add_place_records_mentions_by_chapter():
    from app.models import Place
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    reg.add_place(Place(name="洛阳", description="东都"), "ch0002")
    reg.add_place(Place(name="洛阳", description=""), "ch0004")

    assert reg.places["洛阳"].mentions_by_chapter == {"ch0002": 1, "ch0004": 1}


def test_add_extraction_threads_chapter_into_characters():
    from app.models import ChunkExtraction, Character, Place
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    extraction = ChunkExtraction(
        characters=[Character(name="甲", aliases=[], role="", description="")],
        places=[Place(name="洛阳", description="")],
        events=[],
        relationships=[],
    )
    reg.add_extraction(extraction, "ch0007")

    assert reg.characters["甲"].mentions_by_chapter == {"ch0007": 1}
    assert reg.places["洛阳"].mentions_by_chapter == {"ch0007": 1}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_merge.py -q -k "mentions_by_chapter or threads_chapter"`
Expected: FAIL — `TypeError: add_character() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: 实现**

3a. `CharacterRecord` 加字段（在 `mention_count: int = 0` 之后）：

```python
    # chapter_id -> 该章提及次数。用于前端人物出场曲线。
    mentions_by_chapter: dict[str, int] = field(default_factory=dict)
```

3b. `PlaceRecord` 加同样的字段（在 `mention_count: int = 0` 之后）：

```python
    # chapter_id -> 该章提及次数。地点只用它推首次出场章，不画曲线。
    mentions_by_chapter: dict[str, int] = field(default_factory=dict)
```

3c. `add_character` 签名改为：

```python
    def add_character(
        self,
        char: Character,
        chapter_id: str = "",
        *,
        record_chapter: bool = True,
    ) -> str:
```

在现有 `rec.mention_count += 1` 这一行之后插入：

```python
        if record_chapter and chapter_id:
            rec.mentions_by_chapter[chapter_id] = (
                rec.mentions_by_chapter.get(chapter_id, 0) + 1
            )
```

3d. `add_place` 签名改为：

```python
    def add_place(
        self,
        place: Place,
        chapter_id: str = "",
        *,
        record_chapter: bool = True,
    ) -> str:
```

在它的 `rec.mention_count += 1` 之后插入同样的三行：

```python
        if record_chapter and chapter_id:
            rec.mentions_by_chapter[chapter_id] = (
                rec.mentions_by_chapter.get(chapter_id, 0) + 1
            )
```

3e. `add_extraction` 里把两处调用带上章节。把

```python
        for c in extraction.characters:
            self.add_character(c)
```

改成

```python
        for c in extraction.characters:
            self.add_character(c, chapter_id)
```

把

```python
        for p in extraction.places:
            self.add_place(p)
```

改成

```python
        for p in extraction.places:
            self.add_place(p, chapter_id)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_merge.py tests/test_extract_arcs.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/pipeline/merge.py backend/tests/test_merge.py
rtk git commit -m "feat(merge): track per-chapter mentions for characters and places"
git show --stat
```

---

## Task 4: 跨弧合并保住新字段

跨弧合并 `merge_arcs` 是**通过公开 API 重新灌入**每个弧的记录的，而 `Character`/`Relationship` 这两个 pydantic 模型里没有章节信息。如果不显式处理，Task 2/3 加的字典在合并后会全部变空。`_apply_merge` 折叠同一人物时同理。

**Files:**
- Modify: `backend/app/pipeline/merge.py`
- Test: `backend/tests/test_merge_arcs.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_merge_arcs.py` 末尾：

```python
def test_merge_arcs_preserves_chapter_distributions():
    from app.models import Character, Place, Relationship
    from app.pipeline.merge import EntityRegistry, merge_arcs

    arc1 = EntityRegistry()
    arc1.add_character(Character(name="甲", aliases=[], role="主角", description="少年"), "ch0001")
    arc1.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0001")
    arc1.add_place(Place(name="洛阳", description="东都"), "ch0001")
    arc1.add_relationship(
        Relationship(
            source="甲",
            target="乙",
            category="朋友",
            detail="同门",
            evidence="甲与乙同行",
            confidence=0.9,
        ),
        "ch0001",
    )

    arc2 = EntityRegistry()
    arc2.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0009")
    arc2.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0009")
    arc2.add_place(Place(name="洛阳", description=""), "ch0009")
    arc2.add_relationship(
        Relationship(
            source="甲",
            target="乙",
            category="朋友",
            detail="",
            evidence="",
            confidence=0.5,
        ),
        "ch0009",
    )

    merged = merge_arcs([arc1, arc2], confirm=False)

    assert merged.characters["甲"].mentions_by_chapter == {"ch0001": 1, "ch0009": 1}
    assert merged.places["洛阳"].mentions_by_chapter == {"ch0001": 1, "ch0009": 1}
    rec = next(iter(merged.relationships.values()))
    assert rec.chapters == {"ch0001": 1, "ch0009": 1}


def test_apply_merge_folds_chapter_distributions():
    from app.models import Character, Relationship
    from app.pipeline.merge import EntityRegistry, _apply_merge

    reg = EntityRegistry()
    reg.add_character(Character(name="张三", aliases=[], role="", description=""), "ch0001")
    reg.add_character(Character(name="张三丰", aliases=[], role="", description=""), "ch0004")
    reg.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0001")
    reg.add_relationship(
        Relationship(
            source="张三",
            target="乙",
            category="朋友",
            detail="",
            evidence="",
            confidence=0.5,
        ),
        "ch0001",
    )
    reg.add_relationship(
        Relationship(
            source="张三丰",
            target="乙",
            category="朋友",
            detail="",
            evidence="",
            confidence=0.5,
        ),
        "ch0004",
    )

    _apply_merge(reg, "张三丰", "张三")

    assert "张三丰" not in reg.characters
    assert reg.characters["张三"].mentions_by_chapter == {"ch0001": 1, "ch0004": 1}
    rec = next(iter(reg.relationships.values()))
    assert rec.chapters == {"ch0001": 1, "ch0004": 1}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_merge_arcs.py -q -k "chapter_distributions"`
Expected: FAIL — 合并后的字典是 `{}`（`assert {} == {'ch0001': 1, 'ch0009': 1}`）

- [ ] **Step 3: 实现**

3a. 在 `merge_arcs` 里，把重新灌入的三处调用改成「不记章 + 显式合并字典」。找到现有的人物灌入代码：

```python
            merged.add_character(
                Character(
                    name=rec.canonical,
                    aliases=sorted(rec.aliases),
                    role=rec.role,
                    description=rec.description,
                )
            )
```

改成：

```python
            canonical = merged.add_character(
                Character(
                    name=rec.canonical,
                    aliases=sorted(rec.aliases),
                    role=rec.role,
                    description=rec.description,
                ),
                record_chapter=False,
            )
            _merge_counts(
                merged.characters[canonical].mentions_by_chapter,
                rec.mentions_by_chapter,
            )
```

3b. 地点灌入同样处理。把

```python
            merged.add_place(Place(name=rec.canonical, description=rec.description))
```

改成：

```python
            place_canonical = merged.add_place(
                Place(name=rec.canonical, description=rec.description),
                record_chapter=False,
            )
            _merge_counts(
                merged.places[place_canonical].mentions_by_chapter,
                rec.mentions_by_chapter,
            )
```

3c. 关系灌入。把

```python
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

改成：

```python
            merged_rel = merged.add_relationship(
                Relationship(
                    source=rel.source,
                    target=rel.target,
                    category=rel.category,
                    detail=rel.detail,
                    evidence=rel.evidence,
                    confidence=rel.confidence,
                ),
                chapter_id=rel.chapter_id,
                record_chapter=False,
            )
            if merged_rel is not None:
                _merge_counts(merged_rel.chapters, rel.chapters)
```

3d. `_apply_merge` 里，在 `trec.mention_count += srec.mention_count` 之后插入：

```python
    _merge_counts(trec.mentions_by_chapter, srec.mentions_by_chapter)
```

3e. `_apply_merge` 重建 `new_rels` 时带上 `chapters`。键冲突分支里（`old.count += rec.count` 附近）插入：

```python
            _merge_counts(old.chapters, rec.chapters)
```

首次插入分支里，给 `RelationRecord(...)` 构造追加一个参数：

```python
                chapters=dict(rec.chapters),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_merge.py tests/test_merge_arcs.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/pipeline/merge.py backend/tests/test_merge_arcs.py
rtk git commit -m "feat(merge): carry per-chapter distributions through arc merge and character folding"
git show --stat
```

---
## Task 5: `evolve.py` 第一级 —— 确定性预过滤

判定逻辑的关键前提（spec §2）：`EntityRegistry.relationships` 的键是 `(source, target, category)`，**类别是键的一部分**，所以"甲乙在第 3 章是朋友、第 40 章是敌人"今天就已经是**两条独立的 `RelationRecord`**、在图里是两条平行边。这一步要做的是把同一人物对的多个类别聚起来，丢掉抽取噪声，留下疑似演变的对。

**Files:**
- Create: `backend/app/pipeline/evolve.py`
- Test: `backend/tests/test_evolve.py`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_evolve.py`：

```python
"""关系演变判定测试 (design §3.3/§9)。全部离线。"""

from __future__ import annotations

from app.models import Relationship
from app.pipeline.evolve import chapter_order_map, prefilter_candidates
from app.pipeline.merge import EntityRegistry

CHAPTERS = [
    {"id": "ch0001", "title": "第一章", "order": 1},
    {"id": "ch0002", "title": "第二章", "order": 2},
    {"id": "ch0010", "title": "第十章", "order": 3},
    {"id": "ch0020", "title": "第二十章", "order": 4},
]
ORDER = chapter_order_map(CHAPTERS)


def _rel(source, target, category, evidence=""):
    return Relationship(
        source=source,
        target=target,
        category=category,
        detail="",
        evidence=evidence,
        confidence=0.9,
    )


def test_chapter_order_map_builds_lookup():
    assert ORDER == {"ch0001": 1, "ch0002": 2, "ch0010": 3, "ch0020": 4}


def test_single_category_pair_is_not_a_candidate():
    reg = EntityRegistry()
    reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0001")
    reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0002")

    assert prefilter_candidates(reg, ORDER) == []


def test_two_stable_states_become_a_candidate():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友", "并肩而行"), chapter)
    for chapter in ("ch0010", "ch0020"):
        reg.add_relationship(_rel("甲", "乙", "敌人", "拔剑相向"), chapter)

    cands = prefilter_candidates(reg, ORDER)
    assert len(cands) == 1
    cand = cands[0]
    assert cand["pair"] == ["乙", "甲"]
    assert [s["category"] for s in cand["steps"]] == ["朋友", "敌人"]
    assert [s["chapter_id"] for s in cand["steps"]] == ["ch0001", "ch0010"]
    assert cand["steps"][1]["evidence"] == "拔剑相向"
    assert cand["confirmed"] is False


def test_single_occurrence_state_is_dropped_as_noise():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友"), chapter)
    reg.add_relationship(_rel("甲", "乙", "敌人"), "ch0010")

    assert prefilter_candidates(reg, ORDER) == []


def test_other_category_is_excluded():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友"), chapter)
    for chapter in ("ch0010", "ch0020"):
        reg.add_relationship(_rel("甲", "乙", "其他"), chapter)

    assert prefilter_candidates(reg, ORDER) == []


def test_states_starting_in_the_same_chapter_are_not_evolution():
    reg = EntityRegistry()
    for _ in range(2):
        reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0001")
        reg.add_relationship(_rel("甲", "乙", "同盟"), "ch0001")

    assert prefilter_candidates(reg, ORDER) == []


def test_chapters_outside_the_order_table_are_ignored():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友"), chapter)
    for _ in range(3):
        reg.add_relationship(_rel("甲", "乙", "敌人"), "ch9999")

    assert prefilter_candidates(reg, ORDER) == []


def test_pair_uses_the_same_normalization_as_merge():
    """无向类别在 merge.py 里按 src > tgt 交换过，预过滤必须沿用同一顺序。"""
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("乙", "甲", "朋友"), chapter)
    for chapter in ("ch0010", "ch0020"):
        reg.add_relationship(_rel("甲", "乙", "敌人"), chapter)

    cands = prefilter_candidates(reg, ORDER)
    assert len(cands) == 1
    assert cands[0]["pair"] == ["乙", "甲"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_evolve.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipeline.evolve'`

- [ ] **Step 3: 实现**

创建 `backend/app/pipeline/evolve.py`：

```python
"""关系演变判定 (design §3.3)。

前提：EntityRegistry.relationships 的键含 category，所以同一人物对的不同
关系类别本来就是多条独立记录、在图里是多条平行边。这里做两件事：

1. 确定性预过滤：把同一人物对的多个类别聚起来，用稳定性阈值丢掉抽取噪声。
2. 强模型确认：只把"看起来真的变了"的对送去让强模型确认。

本模块永不抛异常 —— 失败就退化成"没有演变"，其余图谱不受影响。
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from pydantic import BaseModel, Field

from .. import config
from ..models import RelationCategory
from .merge import EntityRegistry

logger = logging.getLogger(__name__)


def chapter_order_map(chapters: Iterable[dict]) -> dict[str, int]:
    """把 [{id,title,order}] 压成 chapter_id -> order 的查表。

    章节先后**只以 order 为准**。chNNNN 的字典序恰好和章序一致是巧合，
    不是契约。
    """
    out: dict[str, int] = {}
    for item in chapters or []:
        cid = (item or {}).get("id")
        if cid:
            out[cid] = int(item.get("order") or 0)
    return out


def prefilter_candidates(
    registry: EntityRegistry,
    chapter_order: dict[str, int],
    *,
    stability_min: int | None = None,
) -> list[dict]:
    """确定性预过滤。返回 confirmed=False 的候选演变列表。"""
    if stability_min is None:
        stability_min = config.EVOLVE_STABILITY_MIN

    groups: dict[tuple[str, str], list] = {}
    for rec in registry.relationships.values():
        if rec.category == RelationCategory.OTHER.value:
            continue
        groups.setdefault((rec.source, rec.target), []).append(rec)

    candidates: list[dict] = []
    for pair in sorted(groups):
        recs = groups[pair]
        if len(recs) < 2:
            continue

        states: list[tuple[int, str, object]] = []
        for rec in recs:
            known = [c for c in rec.chapters if c in chapter_order]
            if not known:
                continue
            total = sum(rec.chapters[c] for c in known)
            if total < stability_min and len(known) < 2:
                continue
            first = min(known, key=lambda c: chapter_order[c])
            states.append((chapter_order[first], first, rec))

        if len(states) < 2:
            continue
        # 两个状态起始于同一章，说明是同章并存而不是先后演变。
        if len({s[0] for s in states}) != len(states):
            continue

        states.sort(key=lambda s: s[0])
        candidates.append(
            {
                "pair": [pair[0], pair[1]],
                "steps": [
                    {
                        "chapter_id": chapter_id,
                        "category": rec.category,
                        "evidence": rec.evidence,
                    }
                    for _, chapter_id, rec in states
                ],
                "confirmed": False,
            }
        )
    return candidates
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_evolve.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/pipeline/evolve.py backend/tests/test_evolve.py
rtk git commit -m "feat(evolve): deterministic prefilter for relationship evolution candidates"
git show --stat
```

---

## Task 6: `evolve.py` 第二级 —— 强模型确认与降级

**Files:**
- Modify: `backend/app/pipeline/evolve.py`
- Test: `backend/tests/test_evolve.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_evolve.py` 末尾：

```python
def _two_state_registry():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友", "并肩而行"), chapter)
    for chapter in ("ch0010", "ch0020"):
        reg.add_relationship(_rel("甲", "乙", "敌人", "拔剑相向"), chapter)
    return reg


def test_detect_transitions_fake_mode_keeps_prefilter_unconfirmed():
    """离线模式跳过强模型，直接采纳预过滤结果（confirmed=False）。"""
    from app.pipeline.evolve import detect_transitions

    out = detect_transitions(_two_state_registry(), CHAPTERS)
    assert len(out) == 1
    assert out[0]["confirmed"] is False
    assert [s["category"] for s in out[0]["steps"]] == ["朋友", "敌人"]


def test_detect_transitions_uses_confirmer_and_marks_confirmed():
    from app.pipeline.evolve import detect_transitions

    seen = {}

    def confirmer(batch):
        seen["size"] = len(batch)
        return [0]

    out = detect_transitions(_two_state_registry(), CHAPTERS, confirmer=confirmer)
    assert seen["size"] == 1
    assert len(out) == 1
    assert out[0]["confirmed"] is True


def test_detect_transitions_drops_rejected_candidates():
    from app.pipeline.evolve import detect_transitions

    out = detect_transitions(_two_state_registry(), CHAPTERS, confirmer=lambda batch: [])
    assert out == []


def test_detect_transitions_never_raises_and_warns():
    from app.pipeline.evolve import detect_transitions

    warnings = []

    def boom(batch):
        raise RuntimeError("模型挂了")

    out = detect_transitions(
        _two_state_registry(), CHAPTERS, confirmer=boom, warn_cb=warnings.append
    )
    assert out == []
    assert len(warnings) == 1
    assert "关系演变" in warnings[0]


def test_detect_transitions_respects_kill_switch(monkeypatch):
    from app.pipeline import evolve

    monkeypatch.setattr(evolve.config, "EVOLVE_ENABLED", False)
    assert evolve.detect_transitions(_two_state_registry(), CHAPTERS) == []


def test_detect_transitions_returns_empty_without_candidates():
    from app.pipeline.evolve import detect_transitions

    reg = EntityRegistry()
    reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0001")
    assert detect_transitions(reg, CHAPTERS) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_evolve.py -q -k detect_transitions`
Expected: FAIL — `ImportError: cannot import name 'detect_transitions' from 'app.pipeline.evolve'`

- [ ] **Step 3: 实现**

在 `backend/app/pipeline/evolve.py` 末尾追加：

```python
CONFIRM_SYSTEM_PROMPT = """你是中文小说的关系分析助手。
下面给出若干「人物对」的关系状态序列，每个状态包含章节、关系类别和一句原文证据。
请判断每一对的关系是否**真的随剧情发生了转变**（例如朋友后来变成敌人），
而不是抽取噪声或同一段关系被打了不同标签。

判断要点：
- 真实演变：前后类别语义确实冲突，且证据支持这种转变。
- 不是演变：同一段关系的不同侧面（如"同盟"与"朋友"并存）、称呼差异、
  或证据完全看不出冲突。

只输出 JSON。对每一项给出 index 和 is_evolution。"""


class ConfirmItem(BaseModel):
    index: int
    is_evolution: bool
    reason: str = ""


class ConfirmResult(BaseModel):
    items: list[ConfirmItem] = Field(default_factory=list)


def _format_candidate(offset: int, candidate: dict) -> str:
    pair = " 与 ".join(candidate["pair"])
    lines = [f"[{offset}] {pair}"]
    for step in candidate["steps"]:
        evidence = step.get("evidence") or "（无证据）"
        lines.append(
            f"    {step['chapter_id']}：{step['category']} —— 「{evidence}」"
        )
    return "\n".join(lines)


def _llm_confirm(batch: list[dict]) -> list[int]:
    """让强模型确认一批候选，返回被判定为真实演变的下标（相对 batch）。"""
    from .llm import structured_output

    body = "\n".join(_format_candidate(i, c) for i, c in enumerate(batch))
    prompt = f"{CONFIRM_SYSTEM_PROMPT}\n\n待判定：\n{body}"
    result = structured_output(
        ConfirmResult,
        prompt,
        what="RelationEvolutionConfirm",
        tier="strong",
    )
    return [
        item.index
        for item in result.items
        if item.is_evolution and 0 <= item.index < len(batch)
    ]


def detect_transitions(
    registry: EntityRegistry,
    chapters: Iterable[dict],
    *,
    confirmer: Callable[[list[dict]], list[int]] | None = None,
    warn_cb: Callable[[str], None] | None = None,
) -> list[dict]:
    """判定关系演变。永不抛异常；失败时返回空列表并记一条警告。"""
    if not config.EVOLVE_ENABLED:
        return []
    try:
        order = chapter_order_map(chapters)
        candidates = prefilter_candidates(registry, order)
        if not candidates:
            return []

        # 离线模式没有强模型可用：直接采纳预过滤结果，标为未确认。
        if confirmer is None and config.USE_FAKE_LLM:
            return candidates

        confirm = confirmer or _llm_confirm
        batch_size = max(1, config.EVOLVE_BATCH_SIZE)
        kept: list[dict] = []
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            for index in confirm(batch):
                if 0 <= index < len(batch):
                    item = dict(batch[index])
                    item["confirmed"] = True
                    kept.append(item)
        return kept
    except Exception:
        logger.warning("evolve: 关系演变判定失败，本次不输出演变", exc_info=True)
        if warn_cb is not None:
            warn_cb("关系演变判定失败，本次结果不含关系演变标记")
        return []
```

> 指令规则直接拼进 prompt 正文，只用 `structured_output` 已有的 `what` / `tier` 两个关键字参数（与 `merge.py` 的 L2 跨弧确认调用一致）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_evolve.py -q`
Expected: PASS（14 passed）

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/pipeline/evolve.py backend/tests/test_evolve.py
rtk git commit -m "feat(evolve): strong-model confirmation with graceful degradation"
git show --stat
```

---

## Task 7: `graph.py` 节点与边的新字段

**Files:**
- Modify: `backend/app/pipeline/graph.py`
- Test: `backend/tests/test_graph.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_graph.py` 末尾：

```python
def test_nodes_and_edges_carry_chapter_distribution():
    from app.models import Character, Place, Relationship
    from app.pipeline.graph import build_extraction_json
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    reg.add_character(Character(name="甲", aliases=[], role="主角", description="少年"), "ch0010")
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0002")
    reg.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0002")
    reg.add_place(Place(name="洛阳", description="东都"), "ch0010")
    reg.add_relationship(
        Relationship(
            source="甲",
            target="乙",
            category="朋友",
            detail="同门",
            evidence="甲与乙同行",
            confidence=0.9,
        ),
        "ch0010",
    )

    order = {"ch0002": 1, "ch0010": 2}
    extraction, _, _ = build_extraction_json(reg, chapter_order=order)

    by_label = {n["label"]: n for n in extraction["nodes"]}
    assert by_label["甲"]["mentions_by_chapter"] == {"ch0010": 1, "ch0002": 1}
    # first_chapter 以 order 为准，不是字典序，也不是插入顺序
    assert by_label["甲"]["first_chapter"] == "ch0002"
    assert by_label["洛阳"]["first_chapter"] == "ch0010"
    assert "mentions_by_chapter" not in by_label["洛阳"]

    edge = extraction["edges"][0]
    assert edge["chapters"] == {"ch0010": 1}
    assert edge["first_chapter"] == "ch0010"


def test_build_extraction_json_without_chapter_order_still_works():
    from app.models import Character
    from app.pipeline.graph import build_extraction_json
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0005")

    extraction, _, _ = build_extraction_json(reg)
    node = extraction["nodes"][0]
    assert node["first_chapter"] == "ch0005"
    assert node["mentions_by_chapter"] == {"ch0005": 1}


def test_stub_nodes_get_empty_timeline_fields():
    from app.models import Relationship
    from app.pipeline.graph import build_extraction_json
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    reg.add_relationship(
        Relationship(
            source="甲",
            target="乙",
            category="朋友",
            detail="",
            evidence="",
            confidence=0.5,
        ),
        "ch0001",
    )

    extraction, _, _ = build_extraction_json(reg, chapter_order={"ch0001": 1})
    for node in extraction["nodes"]:
        assert node["first_chapter"] == ""
        assert node["mentions_by_chapter"] == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_graph.py -q -k "chapter_distribution or without_chapter_order or stub_nodes_get"`
Expected: FAIL — `TypeError: build_extraction_json() got an unexpected keyword argument 'chapter_order'`

- [ ] **Step 3: 实现**

3a. 在 `backend/app/pipeline/graph.py` 的 `_slug` 之后加一个小工具：

```python
def _first_chapter(
    counts: dict[str, int], chapter_order: dict[str, int] | None
) -> str:
    """按章序取首次出场章。没有 order 表时退化为字典序（chNNNN 零填充）。"""
    if not counts:
        return ""
    if chapter_order:
        known = [c for c in counts if c in chapter_order]
        if known:
            return min(known, key=lambda c: chapter_order[c])
    return min(counts)
```

3b. `build_extraction_json` 签名改为：

```python
def build_extraction_json(
    registry: EntityRegistry, chapter_order: dict[str, int] | None = None
) -> tuple[dict, dict, dict]:
```

3c. 人物节点的 dict 里，在 `"mention_count": rec.mention_count,` 之后追加两行：

```python
                "mentions_by_chapter": dict(rec.mentions_by_chapter),
                "first_chapter": _first_chapter(rec.mentions_by_chapter, chapter_order),
```

3d. 地点节点的 dict 里，在 `"mention_count": rec.mention_count,` 之后只追加一行（地点不画曲线）：

```python
                "first_chapter": _first_chapter(rec.mentions_by_chapter, chapter_order),
```

3e. 关系补桩节点（`"description": ""` / `"mention_count": 1` 那个 dict）里追加：

```python
                    "mentions_by_chapter": {},
                    "first_chapter": "",
```

3f. 边的 dict 里，在 `"weight": max(1, rec.count),` 之后追加：

```python
                "chapters": dict(rec.chapters),
                "first_chapter": _first_chapter(rec.chapters, chapter_order),
```

3g. `run_graphify` 透传 order 表。签名改为：

```python
def run_graphify(
    registry: EntityRegistry,
    graph_json_path,
    graph_html_path,
    community_labeler=None,
    chapter_order: dict[str, int] | None = None,
) -> GraphArtifacts:
```

并把内部调用改成：

```python
    extraction, name_to_id, id_to_name = build_extraction_json(
        registry, chapter_order=chapter_order
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_graph.py -q`
Expected: PASS（原有 14 个 + 新增 3 个）

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/pipeline/graph.py backend/tests/test_graph.py
rtk git commit -m "feat(graph): emit per-chapter distribution and first_chapter on nodes and edges"
git show --stat
```

---

## Task 8: `graph.json` 顶层 `chapters` 与 `transitions`

`graph.json` 是 graphify 的 `to_json` 从 networkx 图写出来的，顶层自定义键塞不进去，所以走「写完再补丁」的路子 —— 和既有的 `locate.patch_graph_edge_locations` 完全同一个模式。

**Files:**
- Modify: `backend/app/pipeline/graph.py`
- Test: `backend/tests/test_graph.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_graph.py` 末尾：

```python
def test_patch_graph_timeline_injects_top_level_keys(tmp_path):
    import json

    from app.pipeline.graph import patch_graph_timeline

    path = tmp_path / "graph.json"
    path.write_text(
        json.dumps({"nodes": [{"id": "n1"}], "edges": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    chapters = [{"id": "ch0001", "title": "第一章", "order": 1}]
    transitions = [
        {
            "pair": ["甲", "乙"],
            "steps": [{"chapter_id": "ch0001", "category": "朋友", "evidence": "同行"}],
            "confirmed": True,
        }
    ]

    patch_graph_timeline(path, chapters, transitions, {"甲": "jia", "乙": "yi"})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["chapters"] == chapters
    assert data["transitions"][0]["pair"] == ["jia", "yi"]
    assert data["transitions"][0]["confirmed"] is True
    assert data["nodes"] == [{"id": "n1"}]


def test_patch_graph_timeline_drops_transitions_with_unknown_names(tmp_path):
    import json

    from app.pipeline.graph import patch_graph_timeline

    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
    transitions = [{"pair": ["甲", "丙"], "steps": [], "confirmed": False}]

    patch_graph_timeline(path, [], transitions, {"甲": "jia"})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["transitions"] == []


def test_patch_graph_timeline_never_raises_on_bad_file(tmp_path):
    from app.pipeline.graph import patch_graph_timeline

    missing = tmp_path / "nope.json"
    patch_graph_timeline(missing, [], [], {})
    assert not missing.exists()

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    patch_graph_timeline(broken, [{"id": "ch0001", "title": "x", "order": 1}], [], {})
    assert broken.read_text(encoding="utf-8") == "{not json"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_graph.py -q -k patch_graph_timeline`
Expected: FAIL — `ImportError: cannot import name 'patch_graph_timeline' from 'app.pipeline.graph'`

- [ ] **Step 3: 实现**

在 `backend/app/pipeline/graph.py` 末尾追加：

```python
def patch_graph_timeline(
    graph_json_path,
    chapters: list[dict],
    transitions: list[dict],
    name_to_id: dict[str, str],
) -> None:
    """把顶层 chapters / transitions 补写进 graph.json (design §4.1)。

    graph.json 由 graphify 的 to_json 写出，顶层自定义键只能事后补 —— 与
    locate.patch_graph_edge_locations 同一模式。本函数永不抛异常：补不上就
    保持原文件不动，前端按"旧版本作品"降级。
    """
    import json
    from pathlib import Path

    path = Path(graph_json_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("patch_graph_timeline: 读取 graph.json 失败，跳过", exc_info=True)
        return

    if not isinstance(data, dict):
        return

    mapped: list[dict] = []
    for item in transitions or []:
        pair = (item or {}).get("pair") or []
        if len(pair) != 2:
            continue
        src_id = name_to_id.get(pair[0])
        tgt_id = name_to_id.get(pair[1])
        if not src_id or not tgt_id:
            continue
        mapped.append(
            {
                "pair": [src_id, tgt_id],
                "steps": item.get("steps") or [],
                "confirmed": bool(item.get("confirmed")),
            }
        )

    data["chapters"] = list(chapters or [])
    data["transitions"] = mapped

    try:
        from graphify.paths import write_json_atomic

        write_json_atomic(path, data)
    except Exception:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.warning("patch_graph_timeline: 写回 graph.json 失败", exc_info=True)
```

> 若 `graph.py` 顶部还没有 `logger`，加上 `import logging` 与 `logger = logging.getLogger(__name__)`（`locate.py` 已有同样写法可参照）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_graph.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/pipeline/graph.py backend/tests/test_graph.py
rtk git commit -m "feat(graph): patch top-level chapters and transitions into graph.json"
git show --stat
```

---

## Task 9: 编排接线

`evolve` 跑在 `merge_arcs` 之后、`build_extraction_json` 之前，**仍在既有的 `building` 阶段内** —— 不新增 Phase，后端 `Phase` 枚举与前端镜像的 `PHASE_*` 都不用动。

**Files:**
- Modify: `backend/app/pipeline/orchestrator.py`
- Test: `backend/tests/test_pipeline_integration.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_pipeline_integration.py` 末尾（沿用该文件已有的 tmp DATA_ROOT fixture 与建小说的辅助函数；下面用文件内已存在的方式跑一次完整管道，再断言新字段）：

```python
async def test_pipeline_emits_timeline_fields(tmp_work_env):
    """离线跑完整管道，断言 graph.json 带上时间轴所需的新字段。"""
    import json

    from app import config
    from app.pipeline.orchestrator import read_status, run_pipeline

    work_id = "tl0001"
    raw = config.work_dir(work_id)
    raw.mkdir(parents=True, exist_ok=True)
    raw_path = raw / "raw.txt"
    raw_path.write_text(
        "第一章 相遇\n甲与乙在洛阳相遇，结为好友。甲与乙同行。\n\n"
        "第二章 同行\n甲与乙一路向北。甲与乙互相扶持。\n\n"
        "第三章 决裂\n甲与乙拔剑相向，自此为敌。甲与乙决裂。\n",
        encoding="utf-8",
    )

    await run_pipeline(work_id, raw_path, "raw.txt", "测试小说", "quick")

    status = read_status(work_id)
    assert status is not None and status.phase == "done", status

    data = json.loads((config.work_dir(work_id) / "graph.json").read_text(encoding="utf-8"))
    assert isinstance(data.get("chapters"), list) and len(data["chapters"]) >= 1
    first = data["chapters"][0]
    assert set(first) == {"id", "title", "order"}
    assert first["order"] == 1
    assert isinstance(data.get("transitions"), list)

    nodes = data.get("nodes") or []
    assert any("first_chapter" in n for n in nodes)
    assert any("mentions_by_chapter" in n for n in nodes)
    edges = data.get("edges") or data.get("links") or []
    assert edges and all("chapters" in e for e in edges)
```

> 如果该文件里 tmp DATA_ROOT fixture 不叫 `tmp_work_env`，改成文件里实际的 fixture 名；其余不动。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_pipeline_integration.py -q -k timeline_fields`
Expected: FAIL — `AssertionError: assert isinstance(None, list)`（graph.json 里还没有顶层 chapters）

- [ ] **Step 3: 实现**

3a. 在 `backend/app/pipeline/orchestrator.py` 的 import 区加：

```python
from .evolve import detect_transitions
from .graph import patch_graph_timeline
```

（`run_graphify` 已经从 `.graph` 导入了，把 `patch_graph_timeline` 并进那一行也可以。）

3b. 在 `registry = await asyncio.to_thread(merge_arcs, arc_registries)` 之后、`if not registry.characters:` 之前插入：

```python
        chapters_meta = [
            {"id": c.id, "title": c.title, "order": i + 1}
            for i, c in enumerate(novel.chapters)
        ]
        chapter_order = {c["id"]: c["order"] for c in chapters_meta}
```

3c. 在 `building` 阶段设置 `status.message` 的地方之后、`run_graphify` 调用之前插入演变判定。`detect_transitions` 的 `confirmer` / `warn_cb` 是 keyword-only，而 `asyncio.to_thread` 只能传位置参数，所以用 `functools.partial` 包一层（文件顶部加 `import functools`）：

```python
        status.message = "正在判定关系演变…"
        write_status(status)
        transitions = await asyncio.to_thread(
            functools.partial(
                detect_transitions, registry, chapters_meta, warn_cb=on_warn
            )
        )
```

3d. `run_graphify` 调用带上 order 表：

```python
        artifacts = run_graphify(
            registry,
            graph_json,
            graph_html,
            community_labeler=label_communities,
            chapter_order=chapter_order,
        )
```

3e. 在 `patch_graph_edge_locations(...)` 那一行之后插入：

```python
        patch_graph_timeline(
            graph_json, chapters_meta, transitions, artifacts.label_to_id
        )
```

演变判定跑在既有 `building` 阶段内，`Phase` 枚举与前端 `PHASE_*` 都不用动；进度只通过 `status.message` 体现。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: PASS（全量）

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/pipeline/orchestrator.py backend/tests/test_pipeline_integration.py
rtk git commit -m "feat(pipeline): wire relationship evolution detection and timeline patch into building phase"
git show --stat
```

---
## Task 10: store 辅助函数 —— 找回原文、清掉 beat 缓存

**Files:**
- Modify: `backend/app/store.py`
- Test: `backend/tests/test_store.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_store.py` 末尾：

```python
def test_find_raw_path_locates_upload(tmp_path, monkeypatch):
    from app import config, store

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    wdir = tmp_path / "w1"
    wdir.mkdir()
    (wdir / "raw.epub").write_bytes(b"x")

    found = store.find_raw_path("w1")
    assert found is not None and found.name == "raw.epub"


def test_find_raw_path_returns_none_when_missing(tmp_path, monkeypatch):
    from app import config, store

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    (tmp_path / "w2").mkdir()
    assert store.find_raw_path("w2") is None


def test_clear_beat_cache_removes_only_beat_summaries(tmp_path, monkeypatch):
    from app import config, store

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    wdir = tmp_path / "w3"
    wdir.mkdir()
    (wdir / "beat_summaries.json").write_text("{}", encoding="utf-8")
    (wdir / "chapter_summaries.json").write_text("{}", encoding="utf-8")
    (wdir / "ask_history.json").write_text("[]", encoding="utf-8")

    store.clear_beat_cache("w3")

    assert not (wdir / "beat_summaries.json").exists()
    assert (wdir / "chapter_summaries.json").exists()
    assert (wdir / "ask_history.json").exists()


def test_clear_beat_cache_is_idempotent(tmp_path, monkeypatch):
    from app import config, store

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    (tmp_path / "w4").mkdir()
    store.clear_beat_cache("w4")  # 不存在也不应该炸
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_store.py -q -k "find_raw_path or clear_beat_cache"`
Expected: FAIL — `AttributeError: module 'app.store' has no attribute 'find_raw_path'`

- [ ] **Step 3: 实现**

在 `backend/app/store.py` 的 `save_upload` 之后插入：

```python
def find_raw_path(work_id: str) -> Path | None:
    """找回作品目录下的 raw.<ext>（重新分析时复用，不必重新上传）。"""
    wdir = config.work_dir(work_id)
    if not wdir.exists():
        return None
    for path in sorted(wdir.glob("raw.*")):
        if path.is_file():
            return path
    return None


def clear_beat_cache(work_id: str) -> None:
    """删掉 beat_summaries.json。

    它按 beat 下标做键，而 spine.json 会在重新分析时重建，下标含义会变，
    留着就会错位。chapter_summaries.json（按 chapter_id）与 ask_history.json
    （用户可见历史）都保留。
    """
    path = config.work_dir(work_id) / "beat_summaries.json"
    if path.exists():
        path.unlink()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_store.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/store.py backend/tests/test_store.py
rtk git commit -m "feat(store): add find_raw_path and clear_beat_cache helpers"
git show --stat
```

---

## Task 11: `POST /works/{id}/reanalyze`

**Files:**
- Modify: `backend/app/routes.py`
- Test: `backend/tests/test_routes.py`

- [ ] **Step 1: 写失败的测试**

追加到 `backend/tests/test_routes.py` 末尾（沿用该文件已有的 `client` / tmp DATA_ROOT fixture 命名方式；若 fixture 名不同，照文件里实际的改）：

```python
def _seed_work(tmp_root, work_id, phase="done"):
    """在磁盘上摆出一个"已完成"的作品，供 reanalyze 用。"""
    import json

    wdir = tmp_root / work_id
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "raw.txt").write_text("第一章\n甲与乙。\n", encoding="utf-8")
    (wdir / "meta.json").write_text(
        json.dumps(
            {
                "filename": "novel.txt",
                "title": "旧作品",
                "granularity": "quick",
                "content_sha256": "deadbeef",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (wdir / "status.json").write_text(
        json.dumps(
            {
                "work_id": work_id,
                "title": "旧作品",
                "granularity": "quick",
                "phase": phase,
                "progress": 1.0,
                "message": "",
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return wdir


def test_reanalyze_returns_202_and_queues(client, data_root):
    wdir = _seed_work(data_root, "re0001")
    (wdir / "beat_summaries.json").write_text("{}", encoding="utf-8")
    (wdir / "chapter_summaries.json").write_text("{}", encoding="utf-8")

    res = client.post("/works/re0001/reanalyze")
    assert res.status_code == 202
    body = res.json()
    assert body["work_id"] == "re0001"
    assert body["status"] == "queued"
    assert body["reused"] is False
    assert not (wdir / "beat_summaries.json").exists()
    assert (wdir / "chapter_summaries.json").exists()


def test_reanalyze_rejects_malformed_work_id(client):
    res = client.post("/works/bad%20id/reanalyze")
    assert res.status_code == 400


def test_reanalyze_404_for_unknown_work(client, data_root):
    res = client.post("/works/nosuchwork/reanalyze")
    assert res.status_code == 404


def test_reanalyze_409_while_processing(client, data_root):
    _seed_work(data_root, "re0002", phase="extracting")
    res = client.post("/works/re0002/reanalyze")
    assert res.status_code == 409


def test_reanalyze_409_when_raw_file_missing(client, data_root):
    wdir = _seed_work(data_root, "re0003")
    (wdir / "raw.txt").unlink()
    res = client.post("/works/re0003/reanalyze")
    assert res.status_code == 409
```

> 这些测试依赖 TestClient 的 `BackgroundTasks` 行为：TestClient 会同步跑完后台任务，也就是会真的把管道跑一遍（离线 fake LLM，3 行文本，很快）。如果该文件既有的 fixture 不提供 `client` / `data_root` 这两个名字，改成文件里实际的名字即可。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_routes.py -q -k reanalyze`
Expected: FAIL — 全部 404（路由还不存在）

- [ ] **Step 3: 实现**

在 `backend/app/routes.py` 的 `_init_status` 之后插入：

```python
@router.post(
    "/works/{work_id}/reanalyze", status_code=202, response_model=CreateWorkResponse
)
async def reanalyze_work(
    work_id: str, background_tasks: BackgroundTasks
) -> CreateWorkResponse:
    """用磁盘上已有的 raw.* 重跑一次管道（design §6）。

    不预删旧产物：管道会逐阶段覆盖它们。预删的话中途失败就把作品毁了，
    覆盖则失败后仍能看到上一次的结果。
    """
    # read_meta 内部会走 config.work_dir 校验 work_id，非法 id -> 400。
    meta = store.read_meta(work_id)
    if meta is None:
        raise HTTPException(404, "作品不存在")

    status = store.get_status(work_id)
    if status is not None and status.phase not in ("done", "failed"):
        raise HTTPException(409, "该作品正在处理中")

    raw_path = store.find_raw_path(work_id)
    if raw_path is None:
        raise HTTPException(409, "原始文件已丢失，无法重新分析")

    # beat_summaries.json 按 beat 下标做键，spine.json 会重建，必须清掉。
    store.clear_beat_cache(work_id)

    filename = meta.get("filename") or raw_path.name
    title = meta.get("title") or filename.rsplit(".", 1)[0]
    granularity = meta.get("granularity") or "quick"
    if granularity not in ("quick", "complete"):
        granularity = "quick"

    _init_status(work_id, title, granularity)
    background_tasks.add_task(
        _launch_pipeline, work_id, raw_path, filename, title, granularity
    )
    return CreateWorkResponse(work_id=work_id, status="queued", reused=False)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: PASS（全量）

- [ ] **Step 5: 提交**

```bash
rtk git add -- backend/app/routes.py backend/tests/test_routes.py
rtk git commit -m "feat(api): add POST /works/{id}/reanalyze"
git show --stat
```

---

## Task 12: 前端纯函数层 `lib/graphTimeline.js`

**Files:**
- Create: `frontend/src/lib/graphTimeline.js`
- Test: `frontend/src/lib/graphTimeline.test.js`

- [ ] **Step 1: 写失败的测试**

创建 `frontend/src/lib/graphTimeline.test.js`：

```js
import { describe, expect, it } from "vitest";
import {
  buildBuckets,
  buildChapterOrder,
  buildTransitionIndex,
  hasTimeline,
  isVisibleAt,
  pairKey,
} from "./graphTimeline";

function chapters(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: `ch${String(i + 1).padStart(4, "0")}`,
    title: `第${i + 1}章`,
    order: i + 1,
  }));
}

describe("hasTimeline", () => {
  it("requires a non-empty top-level chapters array", () => {
    expect(hasTimeline(null)).toBe(false);
    expect(hasTimeline({})).toBe(false);
    expect(hasTimeline({ chapters: [] })).toBe(false);
    expect(hasTimeline({ chapters: chapters(1) })).toBe(true);
  });
});

describe("buildChapterOrder", () => {
  it("maps chapter id to order", () => {
    const map = buildChapterOrder(chapters(2));
    expect(map.get("ch0001")).toBe(1);
    expect(map.get("ch0002")).toBe(2);
  });

  it("tolerates empty input", () => {
    expect(buildChapterOrder(undefined).size).toBe(0);
  });
});

describe("buildBuckets", () => {
  it("returns one bucket per chapter at or below the per-chapter cap", () => {
    const buckets = buildBuckets(chapters(20));
    expect(buckets).toHaveLength(20);
    expect(buckets[0]).toEqual({ label: "第1章", cutoff: 1, chapterId: "ch0001" });
    expect(buckets[19].cutoff).toBe(20);
  });

  it("collapses long books into 16 buckets", () => {
    const buckets = buildBuckets(chapters(100));
    expect(buckets).toHaveLength(16);
    // 第一个桶覆盖 1..6，label 取桶内首章，cutoff 取桶内末章的 order
    expect(buckets[0].label).toBe("第1章");
    expect(buckets[0].cutoff).toBe(6);
    expect(buckets[15].cutoff).toBe(100);
  });

  it("sorts by order rather than array position", () => {
    const buckets = buildBuckets([
      { id: "ch0002", title: "第二章", order: 2 },
      { id: "ch0001", title: "第一章", order: 1 },
    ]);
    expect(buckets.map((b) => b.chapterId)).toEqual(["ch0001", "ch0002"]);
  });

  it("returns an empty array for empty input", () => {
    expect(buildBuckets([])).toEqual([]);
    expect(buildBuckets(undefined)).toEqual([]);
  });
});

describe("isVisibleAt", () => {
  const order = buildChapterOrder(chapters(10));

  it("hides items whose first chapter is later than the cutoff", () => {
    expect(isVisibleAt({ first_chapter: "ch0005" }, 4, order)).toBe(false);
    expect(isVisibleAt({ first_chapter: "ch0005" }, 5, order)).toBe(true);
    expect(isVisibleAt({ first_chapter: "ch0005" }, 9, order)).toBe(true);
  });

  it("keeps items with no or unknown first chapter always visible", () => {
    expect(isVisibleAt({}, 1, order)).toBe(true);
    expect(isVisibleAt({ first_chapter: "" }, 1, order)).toBe(true);
    expect(isVisibleAt({ first_chapter: "ch9999" }, 1, order)).toBe(true);
  });
});

describe("pairKey / buildTransitionIndex", () => {
  it("is order independent", () => {
    expect(pairKey("a", "b")).toBe(pairKey("b", "a"));
  });

  it("indexes transitions by node pair", () => {
    const index = buildTransitionIndex([
      { pair: ["a", "b"], steps: [{ chapter_id: "ch0001", category: "朋友" }], confirmed: true },
    ]);
    expect(index.get(pairKey("b", "a")).confirmed).toBe(true);
  });

  it("skips malformed entries and tolerates empty input", () => {
    const index = buildTransitionIndex([{ pair: ["only"] }, null, { steps: [] }]);
    expect(index.size).toBe(0);
    expect(buildTransitionIndex(undefined).size).toBe(0);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- --run src/lib/graphTimeline.test.js`
Expected: FAIL — `Failed to resolve import "./graphTimeline"`

- [ ] **Step 3: 实现**

创建 `frontend/src/lib/graphTimeline.js`：

```js
// 关系图时间维度的纯函数层 (design §5)。
// 章节先后只以 order 为准 —— chNNNN 的字典序恰好和章序一致是巧合，不是契约。

export const MAX_BUCKETS = 16;
export const PER_CHAPTER_MAX = 20;

/** graph.json 是否带时间轴数据（旧版本作品没有顶层 chapters）。 */
export function hasTimeline(graph) {
  return Boolean(graph && Array.isArray(graph.chapters) && graph.chapters.length > 0);
}

/** chapter_id -> order 的查表。 */
export function buildChapterOrder(chapters) {
  const map = new Map();
  for (const c of chapters || []) {
    if (c && c.id) map.set(c.id, Number(c.order) || 0);
  }
  return map;
}

function sortedChapters(chapters) {
  return (chapters || [])
    .filter((c) => c && c.id)
    .slice()
    .sort((a, b) => (Number(a.order) || 0) - (Number(b.order) || 0));
}

/**
 * 章节分桶。≤PER_CHAPTER_MAX 章时一章一档；否则均分成 MAX_BUCKETS 档。
 * 每档的 label 取档内首章标题，cutoff 取档内**末章**的 order
 * （停在第 k 档意味着"读到第 k 档结束"）。
 */
export function buildBuckets(chapters, options) {
  const { maxBuckets = MAX_BUCKETS, perChapterMax = PER_CHAPTER_MAX } = options || {};
  const list = sortedChapters(chapters);
  if (list.length === 0) return [];

  if (list.length <= perChapterMax) {
    return list.map((c) => ({
      label: c.title || c.id,
      cutoff: Number(c.order) || 0,
      chapterId: c.id,
    }));
  }

  const buckets = [];
  for (let i = 0; i < maxBuckets; i += 1) {
    const start = Math.floor((i * list.length) / maxBuckets);
    const end = Math.floor(((i + 1) * list.length) / maxBuckets) - 1;
    if (end < start) continue;
    const first = list[start];
    const last = list[end];
    buckets.push({
      label: first.title || first.id,
      cutoff: Number(last.order) || 0,
      chapterId: last.id,
    });
  }
  return buckets;
}

/** 首次出场章的 order；缺失或不在表内时返回 0（= 始终可见）。 */
export function firstChapterOrder(item, orderMap) {
  const cid = item && item.first_chapter;
  if (!cid) return 0;
  const order = orderMap && orderMap.get(cid);
  return typeof order === "number" ? order : 0;
}

/** 该节点/边在 cutoff 处是否可见。 */
export function isVisibleAt(item, cutoff, orderMap) {
  return firstChapterOrder(item, orderMap) <= cutoff;
}

/** 与顺序无关的人物对键。 */
export function pairKey(a, b) {
  return String(a) < String(b) ? `${a}|${b}` : `${b}|${a}`;
}

/** transitions 数组 -> Map<pairKey, transition>。 */
export function buildTransitionIndex(transitions) {
  const index = new Map();
  for (const t of transitions || []) {
    const pair = t && t.pair;
    if (!Array.isArray(pair) || pair.length !== 2) continue;
    index.set(pairKey(pair[0], pair[1]), t);
  }
  return index;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm run test -- --run src/lib/graphTimeline.test.js`
Expected: PASS（15 passed）

- [ ] **Step 5: 提交**

```bash
rtk git add -- frontend/src/lib/graphTimeline.js frontend/src/lib/graphTimeline.test.js
rtk git commit -m "feat(frontend): add graphTimeline pure helpers with tests"
git show --stat
```

---

## Task 13: `api.js` —— 错误带状态码 + reanalyze

**Files:**
- Modify: `frontend/src/api.js`

- [ ] **Step 1: 实现（这一步是纯管道代码，行为由 Task 16/17 的页面逻辑覆盖）**

把 `frontend/src/api.js` 里的 `json` 函数改成给 Error 带上状态码：

```js
async function json(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* ignore */
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}
```

在文件末尾追加：

```js
export async function reanalyzeWork(id) {
  return apiFetch(`/works/${id}/reanalyze`, { method: "POST" });
}
```

- [ ] **Step 2: 跑既有前端测试确认没破坏**

Run: `cd frontend && npm run test -- --run`
Expected: PASS（原有 4 个测试文件 + graphTimeline）

- [ ] **Step 3: 提交**

```bash
rtk git add -- frontend/src/api.js
rtk git commit -m "feat(frontend): expose HTTP status on api errors and add reanalyzeWork"
git show --stat
```

---

## Task 14: `constants.js` —— 演变边样式

**Files:**
- Modify: `frontend/src/constants.js`

- [ ] **Step 1: 实现**

在 `frontend/src/constants.js` 末尾追加：

```js
// 关系演变边的样式与文案 (design §5.3/§7)。
// confirmed=false 表示强模型没确认（或离线模式跳过了确认）。
export const EVOLUTION_EDGE_DASHES = [6, 4];
export const EVOLUTION_BADGE_CONFIRMED = "关系演变";
export const EVOLUTION_BADGE_UNCONFIRMED = "疑似演变";

export function evolutionBadge(confirmed) {
  return confirmed ? EVOLUTION_BADGE_CONFIRMED : EVOLUTION_BADGE_UNCONFIRMED;
}
```

- [ ] **Step 2: 跑测试确认没破坏**

Run: `cd frontend && npm run test -- --run`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
rtk git add -- frontend/src/constants.js
rtk git commit -m "feat(frontend): add evolution edge style constants"
git show --stat
```

---

## Task 15: `ChapterSlider.jsx`

**Files:**
- Create: `frontend/src/components/graph/ChapterSlider.jsx`

- [ ] **Step 1: 实现**

创建 `frontend/src/components/graph/ChapterSlider.jsx`：

```jsx
// 章节时间滑块 (design §5.1)。受控组件，只负责显示与回调。

export default function ChapterSlider({ buckets, value, onChange }) {
  if (!buckets || buckets.length === 0) return null;

  const last = buckets.length - 1;
  const index = Math.max(0, Math.min(Number(value) || 0, last));
  const current = buckets[index];

  return (
    <div className="rounded-card border border-ink-300 bg-white px-4 py-3">
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-ink-600">时间轴</span>
        <span className="text-sm text-ink-900">读到：{current.label}</span>
      </div>
      <input
        type="range"
        min={0}
        max={last}
        step={1}
        value={index}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="章节时间轴"
        className="mt-2 w-full accent-seal-600"
      />
      <div className="mt-1 flex justify-between text-xs text-ink-600">
        <span>{buckets[0].label}</span>
        <span>{buckets[last].label}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
rtk git add -- frontend/src/components/graph/ChapterSlider.jsx
rtk git commit -m "feat(frontend): add ChapterSlider component"
git show --stat
```

---

## Task 16: `MentionSparkline.jsx`

**Files:**
- Create: `frontend/src/components/graph/MentionSparkline.jsx`

- [ ] **Step 1: 实现**

创建 `frontend/src/components/graph/MentionSparkline.jsx`：

```jsx
// 人物出场曲线 (design §5.4)。无依赖内联 SVG，和 MiniGraphPreview 同一路子。

const WIDTH = 220;
const HEIGHT = 44;
const GAP = 1;

export default function MentionSparkline({ mentions, chapters, cutoff }) {
  const list = (chapters || []).filter((c) => c && c.id);
  if (list.length === 0 || !mentions) return null;

  const counts = list.map((c) => Number(mentions[c.id]) || 0);
  const peak = Math.max(...counts);
  if (peak <= 0) return null;

  const slot = WIDTH / list.length;
  const barWidth = Math.max(1, slot - GAP);
  const limit = typeof cutoff === "number" ? cutoff : Infinity;

  return (
    <div className="mt-2">
      <svg
        width={WIDTH}
        height={HEIGHT}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="按章提及次数"
      >
        {list.map((chapter, i) => {
          const count = counts[i];
          const height = count === 0 ? 0 : Math.max(2, (count / peak) * (HEIGHT - 4));
          const dimmed = (Number(chapter.order) || 0) > limit;
          return (
            <rect
              key={chapter.id}
              x={i * slot}
              y={HEIGHT - height}
              width={barWidth}
              height={height}
              fill={dimmed ? "#d9d9d9" : "#C9A15B"}
            />
          );
        })}
      </svg>
      <p className="mt-1 text-xs text-ink-600">
        按章提及 · 峰值 {peak} 次（共 {list.length} 章）
      </p>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
rtk git add -- frontend/src/components/graph/MentionSparkline.jsx
rtk git commit -m "feat(frontend): add MentionSparkline component"
git show --stat
```

---
## Task 17: `GraphTab.jsx` 接入三个视图

这一步是整个前端的收口：滑块、`hidden` 过滤、演变边、右栏曲线、旧版本降级横幅。改动面太大，直接给出替换后的完整文件。

**关键技术决定：拖动滑块只做 DataSet 的 `update({id, hidden})`，绝不调 `setData`** —— `setData` 会重跑布局让节点乱跳，把拖动手感毁掉；`hidden` 保持坐标稳定，代价是 O(变化量)，同时为 v2 的播放动画铺路。

**Files:**
- Modify: `frontend/src/components/tabs/GraphTab.jsx`（整体替换）

- [ ] **Step 1: 实现**

把 `frontend/src/components/tabs/GraphTab.jsx` 全文替换为：

```jsx
import { useEffect, useMemo, useRef, useState } from "react";
import { getGraph, reanalyzeWork } from "../../api";
import {
  CATEGORY_ORDER,
  EVOLUTION_EDGE_DASHES,
  categoryColor,
  evolutionBadge,
} from "../../constants";
import ChapterSlider from "../graph/ChapterSlider";
import MentionSparkline from "../graph/MentionSparkline";
import {
  buildBuckets,
  buildChapterOrder,
  buildTransitionIndex,
  hasTimeline,
  isVisibleAt,
  pairKey,
} from "../../lib/graphTimeline";

const PLACE_TOP_N = 15;

export default function GraphTab({ id, setRight, onViewChapter }) {
  const containerRef = useRef(null);
  const nodesDsRef = useRef(null);
  const edgesDsRef = useRef(null);
  const cutoffRef = useRef(Infinity);

  const [graph, setGraph] = useState(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [showAllPlaces, setShowAllPlaces] = useState(false);
  const [bucketIdx, setBucketIdx] = useState(0);
  const [built, setBuilt] = useState(0);
  const [reanalyzeMsg, setReanalyzeMsg] = useState("");

  useEffect(() => {
    getGraph(id).then(setGraph).catch((e) => setError(e.message));
  }, [id]);

  const edges = useMemo(() => {
    if (!graph) return [];
    return graph.edges || graph.links || [];
  }, [graph]);

  const timelineOn = useMemo(() => hasTimeline(graph), [graph]);
  const chapters = useMemo(() => (graph && graph.chapters) || [], [graph]);
  const orderMap = useMemo(() => buildChapterOrder(chapters), [chapters]);
  const buckets = useMemo(() => buildBuckets(chapters), [chapters]);
  const transitionIndex = useMemo(
    () => buildTransitionIndex(graph && graph.transitions),
    [graph]
  );

  // 默认停在最后一档（全书），符合"上帝视角"的产品意图。
  useEffect(() => {
    setBucketIdx(buckets.length > 0 ? buckets.length - 1 : 0);
  }, [buckets]);

  const cutoff = useMemo(() => {
    if (buckets.length === 0) return Infinity;
    const bucket = buckets[Math.min(bucketIdx, buckets.length - 1)];
    return bucket ? bucket.cutoff : Infinity;
  }, [buckets, bucketIdx]);

  cutoffRef.current = cutoff;

  const placeCount = useMemo(() => {
    if (!graph) return 0;
    return (graph.nodes || []).filter((n) => n.node_type === "place").length;
  }, [graph]);

  useEffect(() => {
    if (!graph || !containerRef.current) return;

    let cancelled = false;
    let network = null;

    async function buildNetwork() {
      const { DataSet, Network } = await import("vis-network/standalone");
      if (cancelled || !containerRef.current) return;

      const rawNodes = graph.nodes || [];

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
      const visibleIds = new Set(visibleNodes.map((n) => n.id));
      const at = cutoffRef.current;

      const nodes = visibleNodes.map((n) => ({
        id: n.id,
        label: n.label,
        shape: n.node_type === "place" ? "box" : "dot",
        size: 12 + Math.min(20, (n.mention_count || 1) * 2),
        color:
          n.node_type === "place" ? { background: "#d9d9d9", border: "#b0b0b0" } : undefined,
        hidden: !isVisibleAt(n, at, orderMap),
        _raw: n,
      }));

      const visEdges = edges
        .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
        .map((e, i) => {
          const transition = transitionIndex.get(pairKey(e.source, e.target));
          return {
            id: `e${i}`,
            from: e.source,
            to: e.target,
            color: { color: categoryColor(e.category) },
            width: Math.max(1, Math.min(6, e.weight || 1)),
            arrows: e.directed ? "to" : undefined,
            dashes: transition ? EVOLUTION_EDGE_DASHES : undefined,
            label: transition ? evolutionBadge(transition.confirmed) : undefined,
            font: transition ? { size: 11, color: "#6B2E2E", strokeWidth: 3 } : undefined,
            hidden: !isVisibleAt(e, at, orderMap),
            _raw: e,
            _transition: transition || null,
          };
        });

      if (cancelled || !containerRef.current) return;

      const nodesDs = new DataSet(nodes);
      const edgesDs = new DataSet(visEdges);
      nodesDsRef.current = nodesDs;
      edgesDsRef.current = edgesDs;

      network = new Network(
        containerRef.current,
        { nodes: nodesDs, edges: edgesDs },
        {
          nodes: { font: { size: 15, face: "PingFang SC, Microsoft YaHei, sans-serif" } },
          edges: { smooth: { type: "continuous" } },
          physics: { stabilization: { iterations: 150 }, barnesHut: { springLength: 130 } },
          interaction: { hover: true, tooltipDelay: 120 },
        }
      );

      network.on("click", (params) => {
        if (params.nodes.length > 0) {
          const n = nodesDs.get(params.nodes[0]);
          setDetail({ type: "node", data: n && n._raw });
        } else if (params.edges.length > 0) {
          const e = edgesDs.get(params.edges[0]);
          setDetail({ type: "edge", data: e && e._raw, transition: e && e._transition });
        } else {
          setDetail(null);
        }
      });

      setBuilt((v) => v + 1);
    }

    buildNetwork();

    return () => {
      cancelled = true;
      nodesDsRef.current = null;
      edgesDsRef.current = null;
      if (network) network.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, edges, showAllPlaces, orderMap, transitionIndex]);

  // 拖动滑块：只批量改 hidden，不重建网络（否则布局重跑、节点乱跳）。
  useEffect(() => {
    const nodesDs = nodesDsRef.current;
    const edgesDs = edgesDsRef.current;
    if (!nodesDs || !edgesDs) return;

    const nodePatch = [];
    nodesDs.forEach((item) => {
      const next = !isVisibleAt(item._raw, cutoff, orderMap);
      if (next !== Boolean(item.hidden)) nodePatch.push({ id: item.id, hidden: next });
    });
    if (nodePatch.length > 0) nodesDs.update(nodePatch);

    const edgePatch = [];
    edgesDs.forEach((item) => {
      const next = !isVisibleAt(item._raw, cutoff, orderMap);
      if (next !== Boolean(item.hidden)) edgePatch.push({ id: item.id, hidden: next });
    });
    if (edgePatch.length > 0) edgesDs.update(edgePatch);
  }, [cutoff, orderMap, built]);

  useEffect(() => {
    if (!detail?.data) {
      setRight(<div className="text-sm text-ink-600">点击图谱中的节点或连线查看详情</div>);
      return () => setRight(null);
    }

    function jumpTo(location) {
      if (!location) return;
      const [chapterId, para] = String(location).split("#p");
      onViewChapter?.(chapterId, para !== undefined ? Number(para) : undefined);
    }

    if (detail.type === "node") {
      setRight(
        <div>
          <h3 className="font-serif text-lg font-semibold text-ink-900">{detail.data.label}</h3>
          {detail.data.role && <p className="text-sm text-ink-600">{detail.data.role}</p>}
          {detail.data.description && (
            <p className="mt-3 text-sm text-ink-900">{detail.data.description}</p>
          )}
          <p className="mt-4 text-xs text-ink-600">
            {detail.data.node_type === "place" ? "地点" : "人物"} · 提及{" "}
            {detail.data.mention_count || 0} 次
          </p>
          {timelineOn && detail.data.node_type !== "place" && (
            <MentionSparkline
              mentions={detail.data.mentions_by_chapter}
              chapters={chapters}
              cutoff={cutoff}
            />
          )}
        </div>
      );
    } else {
      const transition = detail.transition;
      setRight(
        <div>
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-3 w-3 rounded-sm"
              style={{ background: categoryColor(detail.data.category) }}
            />
            <strong className="text-ink-900">{detail.data.category}</strong>
            <span className="text-xs text-ink-600">· {detail.data.confidence_label}</span>
          </div>

          {transition && (
            <div className="mt-3 rounded-card border border-ink-300 bg-paper-100 p-3">
              <p className="text-xs font-semibold text-seal-600">
                {evolutionBadge(transition.confirmed)}
              </p>
              {!transition.confirmed && (
                <p className="mt-1 text-xs text-ink-600">（未经强模型确认，仅供参考）</p>
              )}
              <ol className="mt-2 space-y-2">
                {(transition.steps || []).map((step, i) => {
                  const order = orderMap.get(step.chapter_id) || 0;
                  const later = order > cutoff;
                  return (
                    <li key={`${step.chapter_id}-${i}`} className={later ? "opacity-40" : ""}>
                      <p className="text-sm text-ink-900">
                        {step.chapter_id} · {step.category}
                      </p>
                      {step.evidence && (
                        <p className="mt-1 text-xs italic text-ink-600">「{step.evidence}」</p>
                      )}
                      <button
                        type="button"
                        onClick={() => jumpTo(step.chapter_id)}
                        className="mt-1 text-xs text-ink-600 hover:text-seal-600 hover:underline"
                      >
                        查看原文 →
                      </button>
                    </li>
                  );
                })}
              </ol>
            </div>
          )}

          {detail.data.detail && <p className="mt-3 text-sm text-ink-900">{detail.data.detail}</p>}
          {detail.data.evidence && (
            <p className="mt-3 text-sm italic text-ink-600">「{detail.data.evidence}」</p>
          )}
          {detail.data.source_location && (
            <button
              type="button"
              onClick={() => jumpTo(detail.data.source_location)}
              className="mt-2 text-xs text-ink-600 hover:text-seal-600 hover:underline"
            >
              查看原文 →
            </button>
          )}
        </div>
      );
    }
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail, chapters, cutoff, orderMap, timelineOn]);

  async function onReanalyze() {
    setReanalyzeMsg("正在提交…");
    try {
      await reanalyzeWork(id);
      setReanalyzeMsg("已提交重新分析，可在处理页查看进度。");
    } catch (e) {
      setReanalyzeMsg(e.message || "重新分析失败");
    }
  }

  if (error) return <div className="px-8 py-10 text-danger-600">{error}</div>;
  if (!graph) {
    return (
      <div className="px-8 py-10 text-ink-600">
        <span className="spinner" /> 加载图谱…
      </div>
    );
  }

  return (
    <div className="px-8 py-10">
      <div className="flex flex-wrap gap-4">
        {CATEGORY_ORDER.map((cat) => (
          <span key={cat} className="flex items-center gap-1.5 text-xs text-ink-600">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: categoryColor(cat) }}
            />
            {cat}
          </span>
        ))}
      </div>

      {timelineOn ? (
        <div className="mt-4">
          <ChapterSlider buckets={buckets} value={bucketIdx} onChange={setBucketIdx} />
        </div>
      ) : (
        <div className="mt-4 rounded-card border border-ink-300 bg-paper-100 px-4 py-3">
          <p className="text-sm text-ink-900">
            该作品分析于旧版本，重新分析可解锁时间轴。
          </p>
          <button
            type="button"
            onClick={onReanalyze}
            className="mt-2 rounded-btn bg-seal-600 px-3 py-1.5 text-sm text-white hover:bg-seal-700"
          >
            重新分析
          </button>
          {reanalyzeMsg && <p className="mt-2 text-xs text-ink-600">{reanalyzeMsg}</p>}
        </div>
      )}

      {placeCount > PLACE_TOP_N && (
        <label className="mt-3 flex items-center gap-2 text-sm text-ink-600">
          <input
            type="checkbox"
            checked={showAllPlaces}
            onChange={(e) => setShowAllPlaces(e.target.checked)}
          />
          显示全部地点（共 {placeCount} 个，默认只显示连接最多的 {PLACE_TOP_N} 个）
        </label>
      )}

      <div
        id="graph"
        ref={containerRef}
        className="mt-4 h-[560px] rounded-card border border-ink-300 bg-white"
      />
    </div>
  );
}
```

- [ ] **Step 2: 跑测试确认没破坏**

Run: `cd frontend && npm run test -- --run`
Expected: PASS

- [ ] **Step 3: 构建确认没有语法/导入错误**

Run: `cd frontend && npm run build`
Expected: 构建成功，无 "Could not resolve" / "Unexpected token"

- [ ] **Step 4: 提交**

```bash
rtk git add -- frontend/src/components/tabs/GraphTab.jsx
rtk git commit -m "feat(frontend): add chapter slider, evolution highlight and mention curve to GraphTab"
git show --stat
```

---

## Task 18: 失败卡片变成真的重试 + 阅读页 409 跳转

审计里的第 3 号缺口：`ProcessingPage` 的"前端显示重试"其实只是一个回首页的 `<Link>`，必须重新上传。现在有了 reanalyze 端点，把它换成真按钮。同时补上阅读页刷新未完成作品只报错的洞。

**Files:**
- Modify: `frontend/src/pages/ProcessingPage.jsx`
- Modify: `frontend/src/pages/ReaderPage.jsx`

- [ ] **Step 1: 改 ProcessingPage 的 import**

把

```jsx
import { useParams, useNavigate, Link } from "react-router-dom";
import { getStatus } from "../api";
```

改成

```jsx
import { useParams, useNavigate, Link } from "react-router-dom";
import { getStatus, reanalyzeWork } from "../api";
```

- [ ] **Step 2: 在组件里加重试状态与处理函数**

在 `const [status, setStatus] = useState(null);` 之后插入：

```jsx
  const [retryMsg, setRetryMsg] = useState("");

  async function onRetry() {
    setRetryMsg("正在提交…");
    try {
      await reanalyzeWork(id);
      setRetryMsg("");
      setStatus(null);
    } catch (e) {
      setRetryMsg(e.message || "重新分析失败");
    }
  }
```

- [ ] **Step 3: 替换失败卡片里的链接**

把

```jsx
            <Link
              to="/"
              className="mt-4 inline-block rounded-btn bg-seal-600 px-4 py-2 text-sm text-white hover:bg-seal-700"
            >
              返回首页重试
            </Link>
```

替换为

```jsx
            <div className="mt-4 flex items-center gap-3">
              <button
                type="button"
                onClick={onRetry}
                className="rounded-btn bg-seal-600 px-4 py-2 text-sm text-white hover:bg-seal-700"
              >
                重新分析
              </button>
              <Link to="/" className="text-sm text-ink-600 hover:text-seal-600 hover:underline">
                返回首页
              </Link>
            </div>
            {retryMsg && <p className="mt-2 text-xs text-ink-600">{retryMsg}</p>}
```

> `setStatus(null)` 会让页面回到"加载中"，而既有的 2s 轮询会立刻取到新的 `queued` 状态继续往下走——不需要动轮询逻辑。

- [ ] **Step 4: 改 ReaderPage —— 409 时跳处理页**

把

```jsx
import { useParams } from "react-router-dom";
```

改成

```jsx
import { useNavigate, useParams } from "react-router-dom";
```

在 `const { id } = useParams();` 之后插入：

```jsx
  const navigate = useNavigate();
```

把加载 effect 的 catch 分支

```jsx
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
```

改成

```jsx
      .catch((e) => {
        if (cancelled) return;
        // 作品还没跑完（含重新分析进行中）：后端返回 409，回到处理页看进度。
        if (e.status === 409) {
          navigate(`/works/${id}/processing`, { replace: true });
          return;
        }
        setError(e.message);
      });
```

并把该 effect 的依赖数组从 `[id]` 改成 `[id, navigate]`。

- [ ] **Step 5: 跑测试与构建**

Run: `cd frontend && npm run test -- --run && npm run build`
Expected: 测试 PASS，构建成功

- [ ] **Step 6: 提交**

```bash
rtk git add -- frontend/src/pages/ProcessingPage.jsx frontend/src/pages/ReaderPage.jsx
rtk git commit -m "feat(frontend): real retry via reanalyze and redirect reader to processing on 409"
git show --stat
```

---

## Task 19: 全量验证与文档同步

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: 全部 PASS，无 warning 级别的 collection error

- [ ] **Step 2: 前端全量测试与构建**

Run: `cd frontend && npm run test -- --run && npm run build`
Expected: 全部 PASS，构建成功

- [ ] **Step 3: 手工离线跑一遍（可选但推荐）**

```bash
cd backend && NOVEL_KG_USE_FAKE_LLM=1 uvicorn app.main:app --port 8000
# 另一个终端
cd frontend && npm run dev
```

上传 `test_novel.txt`，进入阅读页 → 人物关系，确认：滑块出现、拖到最左时图上节点变少、点人物右栏出现出场曲线。

- [ ] **Step 4: 同步 README 的 API 速览**

在 `README.md` 的 API 速览表里，紧跟 `DELETE /works/{id}` 那一行之后加一行：

```markdown
| `POST` | `/works/{id}/reanalyze` | 用已存的原文重跑管道（重试 / 解锁时间轴） |
```

并在"关系类别"一节之后补一小节：

```markdown
## 关系图时间维度

`graph.json` 带有顶层 `chapters`（`{id,title,order}`）与 `transitions`
（关系演变），节点带 `first_chapter` / `mentions_by_chapter`，边带 `chapters` /
`first_chapter`。阅读页「人物关系」据此提供章节滑块、关系演变高亮与人物出场
曲线。旧版本产出的作品没有这些字段，页面会提示「重新分析」。

关掉演变判定：`NOVEL_KG_EVOLVE_ENABLED=0`（滑块与曲线仍然可用）。
```

- [ ] **Step 5: 提交**

```bash
rtk git add -- README.md
rtk git commit -m "docs: document reanalyze endpoint and graph timeline fields"
git show --stat
```



