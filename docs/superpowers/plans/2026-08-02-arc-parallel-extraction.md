# 弧并行抽取（Arc-Parallel Extraction）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把抽取瓶颈 `extract_all` 从"全局滑动上下文串行依赖"改为"按情节弧分片并行抽取 + 跨弧合并"，500-1000 block 目标 ≤20min，质量不降级，并提供跨弧去重/别名归一化。

**Architecture:** 新增 `partition.py` 把 blocks 按章节不可拆分地分成 K 个弧；`extract_arcs` 每条弧一个独立 `EntityRegistry` + 局部滑动上下文，`asyncio.gather` 并行、共享全局 `Semaphore`，落盘 `arcs/arc_{i:02d}.json`；`merge_arcs` 先确定性合并（复用 `add_character/add_place/add_relationship`），再对"跨弧同现 ≥2 或相似度 [0.6,0.86)"候选做强模型批量确认；摘要阶段 spine 串行后三路并行；`extract_all` 保留为单流基线。

**Tech Stack:** Python 3.11+, asyncio, pydantic, strands, pytest, difflib。测试统一 `cd backend && PYTHONPATH=. pytest -q`。

**Config contract (env, prefix `NOVEL_KG_`):**

| 变量 | 说明 | 默认 |
|---|---|---|
| `NOVEL_KG_ARC_BLOCKS_TARGET` | 每条弧目标 block 数 | `60` |
| `NOVEL_KG_MIN_ARC` | 最小弧数 | `2` |
| `NOVEL_KG_MAX_ARC` | 最大弧数 | `16` |
| `NOVEL_KG_ARC_ANCHOR_COUNT` | 全局锚点角色数 | `20` |
| `NOVEL_KG_GLOBAL_EXTRACT_CONCURRENCY` | 全局抽取并发（所有弧共享 Semaphore） | `20` |
| `NOVEL_KG_STRONG_MODEL_ID` | 强模型 id（空则回退各 provider 默认模型） | `''` |
| `NOVEL_KG_STRONG_LLM_PROVIDER` | 强模型 provider | 跟随 `LLM_PROVIDER` |

---

## File Structure

- Create: `backend/app/pipeline/partition.py` — 弧分片 + 全局锚点扫描 + 共享 CJK n-gram 计数
- Create: `backend/tests/test_partition.py`
- Create: `backend/tests/test_extract_arcs.py`
- Create: `backend/tests/test_merge_arcs.py`
- Create: `backend/tests/test_config_arc.py`
- Modify: `backend/app/config.py` — 新增 7 个配置键
- Modify: `backend/app/pipeline/llm.py` — `structured_output/make_model/make_agent` 增加 `tier` 参数
- Modify: `backend/app/pipeline/extract.py` — 抽 `run_block`、`fake_extract_block` 复用共享计数、新增 `extract_arcs`
- Modify: `backend/app/pipeline/merge.py` — 新增 `merge_arcs` + L2 确认
- Modify: `backend/app/pipeline/summarize.py` — spine 串行后三路并行（ThreadPoolExecutor）
- Modify: `backend/app/pipeline/orchestrator.py` — 接入 `extract_arcs` + `merge_arcs`
- Modify: `backend/tests/test_llm.py` — tier 测试
- Modify: `backend/tests/test_pipeline_integration.py` — 等价性测试

---

### Task 1: 新增配置键

**Files:**
- Modify: `backend/app/config.py`（在 `OPENAI_COMPATIBLE_TIMEOUT` 之后追加）
- Test: `backend/tests/test_config_arc.py`

- [ ] **Step 1: 写失败测试**

```python
from app import config


def test_arc_defaults():
    assert config.ARC_BLOCKS_TARGET == 60
    assert config.MIN_ARC == 2
    assert config.MAX_ARC == 16
    assert config.ARC_ANCHOR_COUNT == 20
    assert config.GLOBAL_EXTRACT_CONCURRENCY == 20
    assert config.STRONG_MODEL_ID == ""
    assert config.STRONG_LLM_PROVIDER == config.LLM_PROVIDER


def test_strong_provider_inherits_llm_provider():
    assert config.STRONG_LLM_PROVIDER in {"bedrock", "openai_compatible"}
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_config_arc.py -v`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'ARC_BLOCKS_TARGET'`

- [ ] **Step 3: 实现**

在 `backend/app/config.py` 中 `OPENAI_COMPATIBLE_TIMEOUT` 一行之后追加：

```python
ARC_BLOCKS_TARGET = int(_env('NOVEL_KG_ARC_BLOCKS_TARGET', '60'))
MIN_ARC = int(_env('NOVEL_KG_MIN_ARC', '2'))
MAX_ARC = int(_env('NOVEL_KG_MAX_ARC', '16'))
ARC_ANCHOR_COUNT = int(_env('NOVEL_KG_ARC_ANCHOR_COUNT', '20'))
GLOBAL_EXTRACT_CONCURRENCY = int(_env('NOVEL_KG_GLOBAL_EXTRACT_CONCURRENCY', '20'))
STRONG_MODEL_ID = _env('NOVEL_KG_STRONG_MODEL_ID', '')
STRONG_LLM_PROVIDER = _env('NOVEL_KG_STRONG_LLM_PROVIDER', LLM_PROVIDER)
if STRONG_LLM_PROVIDER not in {'bedrock', 'openai_compatible'}:
    raise ValueError(f'NOVEL_KG_STRONG_LLM_PROVIDER must be bedrock or openai_compatible, got {STRONG_LLM_PROVIDER!r}')
```

注意：`STRONG_LLM_PROVIDER` 的默认值必须引用已定义在前的 `LLM_PROVIDER` 变量（`_env` 的第二个参数）。

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_config_arc.py`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/tests/test_config_arc.py
git commit -m "feat: add arc-parallel extraction config keys"
```

---

### Task 2: partition.py —— 弧分片与全局锚点

**Files:**
- Create: `backend/app/pipeline/partition.py`
- Test: `backend/tests/test_partition.py`

- [ ] **Step 1: 写失败测试**

```python
from app.pipeline.chunk import Block
from app.pipeline.partition import count_cjk_ngrams, partition_blocks, scan_global_anchors


def _blocks(n, chapter_id="ch0001"):
    return [Block(block_id=f"{chapter_id}_b{i:03d}", chapter_id=chapter_id, chapter_title=f"第{chapter_id}章",
                  order=i, text=f"贾宝玉林黛玉薛宝钗" * 10) for i in range(n)]


def _many_chapters(total, per_chapter=10):
    blocks = []
    for ch in range(total // per_chapter + 1):
        blocks += _blocks(min(per_chapter, total - len(blocks)), f"ch{ch:04d}")
        if len(blocks) >= total:
            break
    return blocks


def test_count_cjk_ngrams_counts_substrings():
    counts = count_cjk_ngrams("林黛玉林黛玉")
    assert counts["黛玉"] >= 4


def test_partition_chapters_never_split():
    blocks = _blocks(10, "ch0001") + _blocks(10, "ch0002") + _blocks(10, "ch0003")
    arcs = partition_blocks(blocks, arc_blocks_target=8)
    for arc in arcs:
        assert len({b.chapter_id for b in arc}) == 1
    assert sum(len(a) for a in arcs) == 30


def test_partition_respects_arc_bounds():
    assert len(partition_blocks(_blocks(3, "ch0001") + _blocks(2, "ch0002"), arc_blocks_target=60)) == 2          # MIN_ARC
    assert len(partition_blocks(_many_chapters(500), arc_blocks_target=60)) == 9         # ceil(500/60)
    assert len(partition_blocks(_many_chapters(2000), arc_blocks_target=60)) == 16       # MAX_ARC


def test_partition_deterministic():
    blocks = _blocks(50, "ch0001") + _blocks(50, "ch0002")
    a = partition_blocks(blocks, arc_blocks_target=20)
    b = partition_blocks(blocks, arc_blocks_target=20)
    assert [len(x) for x in a] == [len(x) for x in b]
    assert [x[0].block_id for x in a] == [x[0].block_id for x in b]


def test_partition_empty_blocks():
    assert partition_blocks([]) == []


def test_scan_global_anchors_returns_common_names():
    blocks = _blocks(3, "ch0001") + _blocks(3, "ch0002")
    anchors = scan_global_anchors(blocks, top_n=5)
    assert "贾宝玉" in anchors
    assert len(anchors) <= 5
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_partition.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipeline.partition'`

- [ ] **Step 3: 实现**

创建 `backend/app/pipeline/partition.py`：

```python
"""弧分片与全局锚点扫描 (§3)。"""
import re
from math import ceil
from typing import Optional

from .. import config
from .chunk import Block

_NAME_RE = re.compile(r"[\u4e00-\u9fff]+")


def count_cjk_ngrams(text: str) -> dict[str, int]:
    """统计文本中所有 2/3/4 字 CJK 子串的滑动窗口频次。"""
    counts: dict[str, int] = {}
    for run in _NAME_RE.findall(text):
        for length in (2, 3, 4):
            for i in range(len(run) - length + 1):
                sub = run[i:i + length]
                counts[sub] = counts.get(sub, 0) + 1
    return counts


def partition_blocks(blocks: list[Block], *, arc_blocks_target: Optional[int] = None,
                     min_arc: Optional[int] = None, max_arc: Optional[int] = None) -> list[list[Block]]:
    """把 blocks 分成若干弧：章节不可拆分、确定、按块数尽量均衡。"""
    if not blocks:
        return []
    target = arc_blocks_target or config.ARC_BLOCKS_TARGET
    min_a = min_arc or config.MIN_ARC
    max_a = max_arc or config.MAX_ARC
    n = len(blocks)
    k = max(min_a, min(max_a, ceil(n / target)))
    groups: list[list[Block]] = []
    for b in blocks:
        if groups and groups[-1][0].chapter_id == b.chapter_id:
            groups[-1].append(b)
        else:
            groups.append([b])
    effective = min(k, len(groups))
    per_arc_target = ceil(n / effective)
    arcs: list[list[Block]] = [[] for _ in range(effective)]
    idx = 0
    count = 0
    for gi, ch_blocks in enumerate(groups):
        arcs[idx].extend(ch_blocks)
        count += len(ch_blocks)
        remaining_groups = len(groups) - gi - 1
        remaining_arcs = effective - idx - 1
        if remaining_arcs > 0 and count >= per_arc_target and remaining_groups >= remaining_arcs:
            idx += 1
            count = 0
    return arcs


def scan_global_anchors(blocks: list[Block], *, top_n: Optional[int] = None) -> list[str]:
    """扫描全书最高频人名候选，作为全局锚点注入各弧首个窗口。"""
    top = top_n or config.ARC_ANCHOR_COUNT
    counts = count_cjk_ngrams("".join(b.text for b in blocks))
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], len(kv[0])), reverse=True)
    anchors: list[str] = []
    for name, cnt in ranked:
        if cnt < 2:
            continue
        if any(name in chosen or chosen in name for chosen in anchors):
            continue
        anchors.append(name)
        if len(anchors) >= top:
            break
    return anchors
```

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_partition.py`
Expected: PASS (6 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/partition.py backend/tests/test_partition.py
git commit -m "feat: add arc partition and global anchor scanning"
```

---

### Task 3: extract.py 重构 —— 抽 run_block、共享 n-gram 计数

**Files:**
- Modify: `backend/app/pipeline/extract.py`（`fake_extract_block`、`extract_all`）
- Test: `backend/tests/test_extract.py`（已有，验证不回归）

- [ ] **Step 1: 运行既有测试确认基线绿**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_extract.py`
Expected: PASS (5 passed)

- [ ] **Step 2: 实现重构**

修改 `backend/app/pipeline/extract.py`：

1. 文件顶部 import 增加：`import json`、`from .partition import count_cjk_ngrams, partition_blocks, scan_global_anchors`。删除 `_FAKE_NAME_RE`（已死代码）。
2. **重试收敛到 llm 层（spec §6）**：`_extract_block_sync` 由 `attempts=1` 改为 `attempts=config.EXTRACT_MAX_RETRIES`（backoff 由 llm 层负责，删除外层 4x 循环，去掉原先 4x3=12 次堆叠调用）：

```python
def _extract_block_sync(prompt) -> ChunkExtraction:
    from . import llm
    return llm.structured_output(ChunkExtraction, prompt, system_prompt=SYSTEM_PROMPT,
                                 what='ChunkExtraction', attempts=config.EXTRACT_MAX_RETRIES)
```

3. 把 `extract_all` 内的 `run_block` 提升为模块级函数（不再自带重试循环）：

```python
async def run_block(block, known, granularity, sem, use_fake, warn_cb=None):
    """抽取单个 block，失败返回 None 并告警；重试已收敛到 llm 层。"""
    async with sem:
        try:
            if use_fake:
                return fake_extract_block(block)
            prompt = _build_prompt(block, known, granularity)
            return await asyncio.to_thread(_extract_block_sync, prompt)
        except Exception as exc:  # noqa: BLE001
            if warn_cb:
                warn_cb(f'块 {block.block_id} 抽取失败，已跳过: {exc}')
            return None
```

4. `fake_extract_block` 开头改为复用共享计数（删掉原来内联的滑动窗口计数循环）：

```python
def fake_extract_block(block) -> ChunkExtraction:
    from ..models import Character, Event, Place, Relationship, RelationCategory
    counts = count_cjk_ngrams(block.text)
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
```

（后续 characters/places/relationships/events 组装代码保持不变。）

5. `extract_all` 改为调用模块级 `run_block`：

```python
async def extract_all(blocks, registry, granularity='quick', progress_cb=None, warn_cb=None) -> None:
    total = len(blocks)
    if total == 0:
        return
    use_fake = config.USE_FAKE_LLM
    sem = asyncio.Semaphore(config.EXTRACT_CONCURRENCY)
    processed = 0
    window = max(1, config.EXTRACT_CONCURRENCY)
    for start in range(0, total, window):
        batch = blocks[start:start + window]
        known = registry.known_entities_prompt()
        results = await asyncio.gather(
            *(run_block(b, known, granularity, sem, use_fake, warn_cb) for b in batch)
        )
        for block, extraction in zip(batch, results):
            if extraction is not None:
                registry.add_extraction(extraction, block.chapter_id)
            processed += 1
            if progress_cb:
                progress_cb(processed, total)
```

- [ ] **Step 3: 运行验证无回归**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_extract.py tests/test_merge.py`
Expected: PASS (5 + 9 passed)

- [ ] **Step 4: 提交**

```bash
git add backend/app/pipeline/extract.py
git commit -m "refactor: extract run_block and share cjk ngram counting"
```

---

### Task 4: llm.py —— tier 双模型支持

**Files:**
- Modify: `backend/app/pipeline/llm.py`
- Test: `backend/tests/test_llm.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_llm.py` 末尾追加：

```python
def test_structured_output_strong_tier_selects_strong_model(monkeypatch):
    monkeypatch.setattr(config, 'STRONG_LLM_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(config, 'LLM_PROVIDER', 'bedrock')
    monkeypatch.setattr(config, 'STRONG_MODEL_ID', 'strong-model-9')
    seen = {}
    def _completion(messages, *, model, max_tokens):
        seen['model'] = model
        return '{"name": "张三", "age": 30}'
    monkeypatch.setattr(llm, '_openai_completion', _completion)
    out = llm.structured_output(_Dummy, '问', system_prompt='s', what='t', tier='strong')
    assert out.name == '张三'
    assert seen['model'] == 'strong-model-9'


def test_structured_output_strong_tier_falls_back_to_default_model(monkeypatch):
    monkeypatch.setattr(config, 'STRONG_LLM_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(config, 'LLM_PROVIDER', 'bedrock')
    monkeypatch.setattr(config, 'STRONG_MODEL_ID', '')
    seen = {}
    def _completion(messages, *, model, max_tokens):
        seen['model'] = model
        return '{"name": "李四", "age": 40}'
    monkeypatch.setattr(llm, '_openai_completion', _completion)
    llm.structured_output(_Dummy, '问', system_prompt='s', what='t', tier='strong')
    assert seen['model'] == config.OPENAI_COMPATIBLE_MODEL_ID


def test_structured_output_fast_tier_uses_fast_provider(monkeypatch):
    monkeypatch.setattr(config, 'STRONG_LLM_PROVIDER', 'openai_compatible')
    monkeypatch.setattr(config, 'LLM_PROVIDER', 'bedrock')
    monkeypatch.setattr(config, 'STRONG_MODEL_ID', 'strong-model-9')
    monkeypatch.setattr(config, 'OPENAI_COMPATIBLE_MODEL_ID', 'fast-model-1')
    assert llm._resolve_provider('fast') == 'bedrock'
    assert llm._resolve_model_id('fast') == 'fast-model-1'
    assert llm._resolve_provider('strong') == 'openai_compatible'
    assert llm._resolve_model_id('strong') == 'strong-model-9'
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_llm.py -v`
Expected: 前两个 FAIL — `TypeError: structured_output() got an unexpected keyword argument 'tier'`；第三个 FAIL — `AttributeError: module 'app.pipeline.llm' has no attribute '_resolve_provider'`。

- [ ] **Step 3: 实现**

修改 `backend/app/pipeline/llm.py`：

1. 新增 provider 解析辅助：

```python
def _resolve_provider(tier: str) -> str:
    return config.STRONG_LLM_PROVIDER if tier == 'strong' else config.LLM_PROVIDER


def _resolve_model_id(tier: str) -> str:
    provider = _resolve_provider(tier)
    if provider == 'openai_compatible':
        return config.STRONG_MODEL_ID or config.OPENAI_COMPATIBLE_MODEL_ID
    return config.STRONG_MODEL_ID or config.BEDROCK_MODEL_ID
```

2. `make_model(tier='fast')`：`provider = _resolve_provider(tier)`；`model_id = _resolve_model_id(tier)`；其余分支不变。
3. `make_agent(system_prompt, tools=None, tier='fast')`：`Agent(model=make_model(tier=tier), system_prompt=system_prompt, tools=tools)`。
4. `structured_output(schema, prompt, *, system_prompt, what='', attempts=3, tier='fast')`：

```python
def structured_output(schema, prompt, *, system_prompt, what='', attempts=3, tier='fast'):
    if _resolve_provider(tier) == 'openai_compatible':
        return _openai_structured_output(schema, prompt, system_prompt=system_prompt,
                                         what=what, attempts=attempts, tier=tier)
    return _bedrock_structured_output(schema, prompt, system_prompt=system_prompt,
                                      what=what, attempts=attempts, tier=tier)
```

5. `_bedrock_structured_output(..., tier='fast')`：`agent = make_agent(system_prompt or '', tier=tier)`。
6. `_openai_structured_output(..., tier='fast')`：调用 `_openai_completion(messages, model=_resolve_model_id(tier), max_tokens=config.OPENAI_COMPATIBLE_MAX_TOKENS)`（替换原先直接使用 `config.OPENAI_COMPATIBLE_MODEL_ID` 处；`_openai_completion` 签名保持 `(messages, *, model, max_tokens)` 不变）。

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_llm.py`
Expected: PASS（原 11 个 + 新 3 个 = 14 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/llm.py backend/tests/test_llm.py
git commit -m "feat: add tier-based model selection to llm layer"
```

---

### Task 5: extract.py —— extract_arcs

**Files:**
- Modify: `backend/app/pipeline/extract.py`
- Test: `backend/tests/test_extract_arcs.py`

- [ ] **Step 1: 写失败测试**

```python
import asyncio
import json

from app.pipeline.chunk import Block
from app.pipeline.merge import EntityRegistry
from app.pipeline.extract import extract_arcs


def _blocks(n, chapter_id="ch0001", order=0):
    return [Block(block_id=f"{chapter_id}_b{i:03d}", chapter_id=chapter_id, chapter_title=f"第{chapter_id}章",
                  order=order + i, text="贾宝玉林黛玉薛宝钗王熙凤" * 8) for i in range(n)]


def test_extract_arcs_returns_registry_per_arc():
    blocks = _blocks(30, "ch0001") + _blocks(30, "ch0002")
    regs = asyncio.run(extract_arcs(blocks, granularity="quick"))
    assert len(regs) >= 2
    assert all(isinstance(r, EntityRegistry) for r in regs)


def test_extract_arcs_persists_arc_files(tmp_path):
    blocks = _blocks(30, "ch0001")
    arcs_dir = tmp_path / "arcs"
    asyncio.run(extract_arcs(blocks, granularity="quick", work_dir=arcs_dir))
    files = sorted(arcs_dir.glob("arc_*.json"))
    assert len(files) >= 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert set(payload) == {"characters", "places", "relationships", "events"}


def test_extract_arcs_progress_reports_total_blocks():
    blocks = _blocks(30, "ch0001") + _blocks(30, "ch0002")
    seen = []
    asyncio.run(extract_arcs(blocks, granularity="quick", progress_cb=lambda d, t: seen.append((d, t))))
    assert seen[-1][0] == len(blocks)
    assert seen[-1][1] == len(blocks)


def test_extract_arcs_empty_blocks_returns_empty():
    assert asyncio.run(extract_arcs([], granularity="quick")) == []


def test_extract_arcs_per_arc_failure_returns_empty_registry(monkeypatch):
    from app.pipeline import extract as extract_mod
    async def boom(block, known, granularity, sem, use_fake, warn_cb=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(extract_mod, "run_block", boom)
    blocks = _blocks(30, "ch0001")
    warns = []
    regs = asyncio.run(extract_arcs(blocks, granularity="quick", warn_cb=warns.append))
    assert warns
    assert all(len(r.characters) == 0 for r in regs)
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_extract_arcs.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_arcs' from 'app.pipeline.extract'`

- [ ] **Step 3: 实现**

在 `backend/app/pipeline/extract.py` 末尾追加（`json` 已在 Task 3 引入 import）：

```python
def _save_arc(registry, arcs_dir, arc_index):
    arcs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'characters': [
            {'canonical': r.canonical, 'aliases': sorted(r.aliases), 'role': r.role,
             'description': r.description, 'mention_count': r.mention_count}
            for r in registry.characters.values()
        ],
        'places': [
            {'canonical': p.canonical, 'description': p.description, 'mention_count': p.mention_count}
            for p in registry.places.values()
        ],
        'relationships': [
            {'source': r.source, 'target': r.target, 'category': r.category, 'detail': r.detail,
             'evidence': r.evidence, 'confidence': r.confidence, 'count': r.count}
            for r in registry.relationships.values()
        ],
        'events': registry.events,
    }
    (arcs_dir / f'arc_{arc_index:02d}.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _anchors_prompt(anchors):
    lines = '\n'.join(f'- {name}' for name in anchors)
    return '全局主角（全书反复出现的核心人物，请把代词/别称解析到这些名字，不要重复创建）：\n' + lines


async def extract_arcs(blocks, *, granularity='quick', work_dir=None,
                       progress_cb=None, arc_progress_cb=None, warn_cb=None) -> list[EntityRegistry]:
    """把 blocks 分成弧并行抽取，返回每条弧的独立 EntityRegistry。"""
    arcs = partition_blocks(blocks)
    if not arcs:
        return []
    use_fake = config.USE_FAKE_LLM
    global_sem = asyncio.Semaphore(config.GLOBAL_EXTRACT_CONCURRENCY)
    anchors = scan_global_anchors(blocks)
    anchors_prompt = _anchors_prompt(anchors) if anchors else None
    total = len(blocks)
    arc_count = len(arcs)
    processed = 0
    lock = asyncio.Lock()

    async def run_arc(arc_blocks, arc_index):
        registry = EntityRegistry()
        try:
            window = max(1, config.EXTRACT_CONCURRENCY)
            for start in range(0, len(arc_blocks), window):
                batch = arc_blocks[start:start + window]
                known = registry.known_entities_prompt()
                if start == 0 and anchors_prompt:
                    known = (known + '\n' + anchors_prompt) if known else anchors_prompt
                results = await asyncio.gather(
                    *(run_block(b, known, granularity, global_sem, use_fake, warn_cb) for b in batch)
                )
                for block, extraction in zip(batch, results):
                    if extraction is not None:
                        registry.add_extraction(extraction, block.chapter_id)
                    async with lock:
                        processed += 1
                        if progress_cb:
                            progress_cb(processed, total)
            if work_dir:
                _save_arc(registry, work_dir, arc_index)
            if arc_progress_cb:
                arc_progress_cb(arc_index, arc_count, processed, total)
            return registry
        except Exception as exc:  # noqa: BLE001
            if warn_cb:
                warn_cb(f'arc {arc_index + 1} 抽取失败，已跳过: {exc}')
            if arc_progress_cb:
                arc_progress_cb(arc_index, arc_count, processed, total)
            return registry

    return await asyncio.gather(*(run_arc(arcs[i], i) for i in range(arc_count)))
```

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_extract_arcs.py tests/test_extract.py`
Expected: PASS (5 + 5 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/extract.py backend/tests/test_extract_arcs.py
git commit -m "feat: parallel arc extraction with per-arc registries"
```

---

### Task 6: merge.py —— merge_arcs 两级合并

**Files:**
- Modify: `backend/app/pipeline/merge.py`
- Test: `backend/tests/test_merge_arcs.py`

- [ ] **Step 1: 写失败测试**

```python
import difflib

from app import config
from app.models import Character, Place, Relationship, RelationCategory
from app.pipeline.merge import (SIMILARITY_THRESHOLD, EntityRegistry,
                                _find_merge_candidates, merge_arcs)


def _arc(chars, rels=(), places=()):
    reg = EntityRegistry()
    for c in chars:
        reg.add_character(c)
    for p in places:
        reg.add_place(p)
    for r in rels:
        reg.add_relationship(r)
    return reg


def test_merge_arcs_shared_character_merges():
    a = _arc([Character(name="贾宝玉")])
    b = _arc([Character(name="贾宝玉")])
    merged = merge_arcs([a, b])
    assert set(merged.characters) == {"贾宝玉"}
    assert merged.characters["贾宝玉"].mention_count == 2


def test_merge_arcs_alias_resolves_across_arcs():
    a = _arc([Character(name="贾宝玉", aliases=["宝玉", "宝二爷"])])
    b = _arc([Character(name="宝玉")])
    merged = merge_arcs([a, b], confirm=False)
    assert set(merged.characters) == {"贾宝玉"}


def test_merge_arcs_relations_merged_into_one():
    a = _arc([Character(name="贾宝玉"), Character(name="林黛玉")],
             [Relationship(source="贾宝玉", target="林黛玉", category=RelationCategory.LOVER, detail="青梅竹马")])
    b = _arc([Character(name="贾宝玉"), Character(name="林黛玉")],
             [Relationship(source="林黛玉", target="贾宝玉", category=RelationCategory.LOVER, detail="互诉衷肠")])
    merged = merge_arcs([a, b], confirm=False)
    assert (min("贾宝玉", "林黛玉"), max("贾宝玉", "林黛玉"), "爱人") in merged.relationships


def test_merge_arcs_l2_confirm_merges_and_rewrites_relations(monkeypatch):
    monkeypatch.setattr(config, "USE_FAKE_LLM", False)
    a = _arc([Character(name="林妹妹")],
             [Relationship(source="林妹妹", target="贾宝玉", category=RelationCategory.LOVER)])
    b = _arc([Character(name="林妹妹"), Character(name="林黛玉")],
             [Relationship(source="林黛玉", target="薛宝钗", category=RelationCategory.FRIEND)])
    merged = merge_arcs([a, b], confirmer=lambda batches: [
        {"names": ["林妹妹", "林黛玉"], "final_name": "林黛玉"}
    ])
    assert set(merged.characters) == {"贾宝玉", "林黛玉", "薛宝钗"}
    assert ("林黛玉", "贾宝玉", "爱人") in merged.relationships
    assert ("林黛玉", "薛宝钗", "朋友") in merged.relationships


def test_merge_arcs_l2_skipped_in_fake_mode(monkeypatch):
    import app.pipeline.merge as merge_mod
    def _boom(batches):
        raise AssertionError("must not be called")
    monkeypatch.setattr(merge_mod, "_llm_confirm", _boom)
    a = _arc([Character(name="林妹妹")])
    b = _arc([Character(name="林黛玉")])
    merged = merge_arcs([a, b], confirm=True)
    assert set(merged.characters) == {"林妹妹", "林黛玉"}


def test_merge_arcs_empty_inputs():
    merged = merge_arcs([])
    assert merged.characters == {}
    assert merged.events == []


def test_find_merge_candidates_marks_multi_arc_and_near_similar():
    a = _arc([Character(name="贾宝玉"), Character(name="林黛玉")])
    b = _arc([Character(name="贾宝玉"), Character(name="林哥哥")])
    merged = merge_arcs([a, b], confirm=False)
    candidates = _find_merge_candidates(merged, [a, b])
    assert "贾宝玉" in candidates          # 跨弧同现 ≥2
    assert set(candidates) <= set(merged.characters)
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_merge_arcs.py -v`
Expected: FAIL — `ImportError: cannot import name 'merge_arcs' from 'app.pipeline.merge'`

- [ ] **Step 3: 实现**

修改 `backend/app/pipeline/merge.py`：

1. 顶部 import 增加：`import logging`、`from .. import config`、`from pydantic import BaseModel`。`logger = logging.getLogger('novel_kg.merge')`。
2. 文件末尾追加：

```python
MERGE_CONFIRM_SIM_MIN = 0.6


def _arc_appearance_counts(arc_registries) -> dict[str, int]:
    counts: dict[str, int] = {}
    for arc in arc_registries:
        for name in arc.characters:
            counts[name] = counts.get(name, 0) + 1
    return counts


def _find_merge_candidates(merged, arc_registries) -> list[str]:
    counts = _arc_appearance_counts(arc_registries)
    names = sorted(merged.characters)
    candidates: set[str] = set()
    for name in names:
        if counts.get(name, 0) >= 2:
            candidates.add(name)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ratio = difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()
            if MERGE_CONFIRM_SIM_MIN <= ratio < SIMILARITY_THRESHOLD:
                candidates.add(a)
                candidates.add(b)
    return sorted(candidates)


def _confirm_batches(merged, candidates, counts, batch_size=25) -> list[list[dict]]:
    batches = []
    for i in range(0, len(candidates), batch_size):
        chunk = candidates[i:i + batch_size]
        records = []
        for name in chunk:
            rec = merged.characters[name]
            records.append({
                'canonical': rec.canonical,
                'aliases': sorted(rec.aliases),
                'identity': rec.identity_line(),
                'arcs': counts.get(rec.canonical, 0),
            })
        batches.append(records)
    return batches


class MergeGroup(BaseModel):
    names: list[str]
    final_name: str


class MergeGroups(BaseModel):
    groups: list[MergeGroup]


def _llm_confirm(batches) -> list[MergeGroup]:
    from . import llm
    groups: list[MergeGroup] = []
    for batch in batches:
        lines = '\n'.join(
            f"- {r['canonical']}（别名：{'、'.join(r['aliases']) or '无'}，出现于 {r['arcs']} 个分卷）"
            for r in batch
        )
        prompt = (
            '以下是从小说不同分卷抽取出的角色记录。请判断哪些记录实际上指向同一个人物，并给出合并分组。\n'
            '规则：\n'
            '- 只合并确实指向同一人的记录（别称/简称/译名差异）；\n'
            '- 无法确定归属的记录不要放进任何分组；\n'
            '- 每组给出 final_name：该人物最正式的称呼；\n'
            '- 每组至少包含 2 个名字才需要合并。\n\n'
            f'{lines}'
        )
        try:
            result = llm.structured_output(MergeGroups, prompt,
                                           system_prompt='你是小说人物归一化专家。',
                                           what='ArcMergeConfirm', tier='strong')
            groups.extend(result.groups)
        except Exception:  # noqa: BLE001
            logger.warning('ArcMergeConfirm batch failed; skipping', exc_info=True)
    return groups


def _apply_merge(merged, src, tgt):
    if src == tgt:
        return
    srec = merged.characters.get(src)
    trec = merged.characters.get(tgt)
    if srec is None or trec is None:
        return
    trec.aliases.update(srec.aliases)
    trec.aliases.add(src)
    trec.mention_count += srec.mention_count
    if srec.role and not trec.role:
        trec.role = srec.role
    if len(srec.description) > len(trec.description):
        trec.description = srec.description
    for alias in srec.all_names():
        merged._alias_index[_norm(alias)] = tgt
    from ..models import DIRECTED_CATEGORIES, RelationCategory
    new_rels: dict[tuple[str, str, str], RelationRecord] = {}
    for (s, t, cat), rec in merged.relationships.items():
        ns = tgt if s == src else s
        nt = tgt if t == src else t
        if ns == nt:
            continue
        try:
            cat_enum = RelationCategory(cat)
        except ValueError:
            cat_enum = RelationCategory.OTHER
        if cat_enum not in DIRECTED_CATEGORIES and ns > nt:
            ns, nt = nt, ns
        key = (ns, nt, cat)
        old = new_rels.get(key)
        if old is None:
            new_rels[key] = RelationRecord(source=ns, target=nt, category=cat,
                                           detail=rec.detail, evidence=rec.evidence,
                                           confidence=rec.confidence, count=rec.count)
        else:
            old.count += rec.count
            old.confidence = max(old.confidence, rec.confidence)
            if len(rec.detail) > len(old.detail):
                old.detail = rec.detail
            if len(rec.evidence) > len(old.evidence):
                old.evidence = rec.evidence
    merged.relationships = new_rels
    del merged.characters[src]


def merge_arcs(arc_registries, *, confirm: bool = True, confirmer=None) -> EntityRegistry:
    """两级跨弧合并：L1 确定性，L2 强模型确认。confirmer 供测试注入。"""
    merged = EntityRegistry()
    if not arc_registries:
        return merged
    for arc in arc_registries:
        for rec in arc.characters.values():
            merged.add_character(Character(name=rec.canonical, aliases=sorted(rec.aliases),
                                           role=rec.role, description=rec.description))
        for rec in arc.places.values():
            merged.add_place(Place(name=rec.canonical, description=rec.description))
        for rel in arc.relationships.values():
            merged.add_relationship(Relationship(source=rel.source, target=rel.target,
                                                 category=rel.category, detail=rel.detail,
                                                 evidence=rel.evidence, confidence=rel.confidence))
        merged.events.extend(arc.events)
    if confirm and (confirmer is not None or not config.USE_FAKE_LLM):
        try:
            counts = _arc_appearance_counts(arc_registries)
            candidates = _find_merge_candidates(merged, arc_registries)
            if candidates:
                batches = _confirm_batches(merged, candidates, counts)
                groups = (confirmer if confirmer else _llm_confirm)(batches)
                for group in groups:
                    names = [n for n in group['names'] if n in merged.characters]
                    if len(names) < 2:
                        continue
                    target = group['final_name'] if group['final_name'] in names else names[0]
                    for name in names:
                        if name != target:
                            _apply_merge(merged, name, target)
        except Exception:  # noqa: BLE001
            logger.warning('merge_arcs L2 confirm failed; keeping deterministic merge', exc_info=True)
    return merged
```

注：`merge_arcs` 的 `confirmer` 返回元素用 dict 兼容测试（`{"names": [...], "final_name": "..."}`）；`_llm_confirm` 返回的 `MergeGroup` 为 pydantic 模型，支持下标访问 `group['names']`。

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_merge_arcs.py tests/test_merge.py`
Expected: PASS (7 + 9 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/merge.py backend/tests/test_merge_arcs.py
git commit -m "feat: two-level cross-arc merge with strong model confirm"
```

---

### Task 7: summarize.py —— spine 串行后三路并行

**Files:**
- Modify: `backend/app/pipeline/summarize.py`
- Test: `backend/tests/test_summarize.py`（已有，验证不回归）

- [ ] **Step 1: 运行既有测试确认基线绿**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_summarize.py`
Expected: PASS (5 passed)

- [ ] **Step 2: 实现**

修改 `backend/app/pipeline/summarize.py`：

1. 顶部 import 增加：`import concurrent.futures`、`from pydantic import BaseModel`。
2. 模块级抽 schema（原 `__import__('pydantic').BaseModel` 内联类删除）：

```python
class SettingCards(BaseModel):
    cards: list[SettingCard]


class SuggestedQuestionsSchema(BaseModel):
    questions: list[SuggestedQuestion]
```

3. 新增三个生成函数（放 `_llm_summary` 之前）：

```python
def _gen_layered(digest, spine_block, tone, voice, title) -> LayeredSummary:
    prompt = (f'书名：{title}\n\n{digest}\n\n' f'{spine_block}\n\n'
              f'这本书的基调是【{tone}】。请你据此选择讲述口吻：{voice}\n'
              '无论何种口吻，都必须遵守：忠于原著、绝不虚构原著没有的情节、面向没读过原著的零基础读者。\n\n'
              '请围绕上面的主线讲清楚这本小说到底在讲什么，生成分层摘要，字段要求如下：\n'
              '- one_liner：一句话点明故事核心（谁，遭遇了什么，追求什么），要有吸引力。\n'
              '- story_hook：30-50字，告诉读者“这本书为什么值得读”，一句能勾起兴趣的钩子。\n'
              '- overview：一段完整的故事梗概（200-400字），围绕主线、大胆取舍支线，必须按【起因→发展→高潮→结局】的叙事顺序讲清楚：开端与主要矛盾、情节如何推进、关键转折/高潮、以及最终结局或走向。要让没读过原著的读者看完就明白这本小说讲的是什么，禁止只罗列人物或关系。\n'
              '- arcs：每条情节线一段摘要，对应下方给出的人物社区。\n')
    return llm.structured_output(LayeredSummary, prompt, system_prompt=SUMMARY_SYSTEM_PROMPT,
                                 what='LayeredSummary', tier='strong')


def _gen_cards(digest, title, registry, communities, community_labels) -> list[SettingCard]:
    cards_prompt = f'书名：{title}\n\n{digest}\n\n请生成3-6张设定卡（世界观/主题/关键概念），每张有title与content。'
    try:
        return llm.structured_output(SettingCards, cards_prompt, system_prompt=SUMMARY_SYSTEM_PROMPT,
                                     what='SettingCards', tier='strong').cards
    except Exception:  # noqa: BLE001
        logger.exception('SettingCards generation failed; keeping LLM summary with fallback cards')
        return _fake_setting_cards(registry, communities, community_labels)


def _gen_questions(spine_block, digest, title, spine_payload) -> list[SuggestedQuestion]:
    questions_prompt = (f'书名：{title}\n\n{spine_block}\n\n' f'故事摘要：\n{digest}\n\n'
                        '请基于以上信息，生成3-5个读者读完这段简介后可能想问、且可以通过阅读小说实际章节内容回答的问题（例如人物关系、情节转折、结局走向）。\n'
                        '严格禁止：\n- 代码审查风格的问题（例如“是否应该拆分模块/重构”之类，与本书内容无关）；\n'
                        '- 过于主观、开放、无法从原文找到答案的问题（例如“你觉得这本书好看吗”）。\n'
                        '每个问题附一句简短 rationale（说明读者为什么可能想问这个）。')
    try:
        return llm.structured_output(SuggestedQuestionsSchema, questions_prompt,
                                     system_prompt=SUMMARY_SYSTEM_PROMPT,
                                     what='SuggestedQuestions', tier='strong').questions
    except Exception:  # noqa: BLE001
        logger.exception('SuggestedQuestions generation failed; falling back to heuristic questions')
        return _fake_suggested_questions(spine_payload or {})
```

4. `_story_spine` 中 `llm.structured_output(...)` 调用追加 `tier='strong'`。
5. `_llm_summary` 中 Step 2/Step 3 整体替换为三路并行（保持 Step 1 spine 串行不变）：

```python
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_layered = pool.submit(_gen_layered, digest, spine_block, tone, voice, title)
        f_cards = pool.submit(_gen_cards, digest, title, registry, communities, community_labels)
        f_questions = pool.submit(_gen_questions, spine_block, digest, title, spine_payload)
        layered = f_layered.result()
        cards = f_cards.result()
        suggested_questions = f_questions.result()
    titles = chapter_titles or {}
    layered.chapters = [ChapterSummary(chapter=ch, title=titles.get(ch, ''), summary='') for ch in chapters]
    return layered, cards, suggested_questions, spine_payload
```

删除原 Step 2 中的内联 `SettingCards` 类、`cards_prompt`、`cards = ...`、原 `layered.chapters` 占位赋值，以及原 Step 3 内联 `SuggestedQuestionsSchema` 类与 `suggested_questions` 生成块。

- [ ] **Step 3: 运行验证无回归**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_summarize.py`
Expected: PASS (5 passed)

- [ ] **Step 4: 提交**

```bash
git add backend/app/pipeline/summarize.py
git commit -m "perf: parallelize layered/cards/questions summary generation"
```

---

### Task 8: orchestrator 接入 + 端到端等价性测试

**Files:**
- Modify: `backend/app/pipeline/orchestrator.py`
- Modify: `backend/tests/test_pipeline_integration.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_pipeline_integration.py` 追加（复用已有 `temp_data_root` fixture、`SAMPLE_NOVEL`、`store` import）：

```python
def test_arc_parallel_equals_single_stream(temp_data_root):
    from app.pipeline.chunk import chunk_novel
    from app.pipeline.extract import extract_all, extract_arcs
    from app.pipeline.merge import EntityRegistry, merge_arcs
    from app.pipeline.parse import parse_upload

    work_id = store.new_work_id()
    raw_path = store.save_upload(work_id, 'test.txt', SAMPLE_NOVEL.encode('utf-8'))
    novel = parse_upload(raw_path, 'test.txt')
    blocks = chunk_novel(novel)

    arc_regs = asyncio.run(extract_arcs(blocks, granularity='quick'))
    merged = merge_arcs(arc_regs)

    baseline = EntityRegistry()
    asyncio.run(extract_all(blocks, baseline, granularity='quick'))

    assert set(merged.characters) == set(baseline.characters)
    assert set(merged.relationships) == set(baseline.relationships)
    assert len(merged.events) == len(baseline.events)
```

- [ ] **Step 2: 运行验证失败**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_pipeline_integration.py::test_arc_parallel_equals_single_stream -v`
Expected: 当前不失败（extract_arcs/merge_arcs 已存在），本步骤确认测试可运行。

- [ ] **Step 3: 修改 orchestrator**

修改 `backend/app/pipeline/orchestrator.py`：

1. import 增加：`import asyncio`；`from .extract import extract_arcs`；`from .merge import EntityRegistry, merge_arcs`（删掉原 `from .extract import extract_all`、`from .merge import EntityRegistry`）。
2. Step 3 (extracting) 中，把 `registry = EntityRegistry()` 之前的整段替换为：

```python
        status.phase = 'extracting'
        status.message = '正在抽取人物与关系…'
        write_status(status)

        def on_progress(done, total):
            status.progress = round(done / total, 4) if total else 1.0
            write_status(status)

        def on_arc_progress(arc_index, arc_count, done, total):
            status.message = f'抽取中 arc {arc_index + 1}/{arc_count} (block {done}/{total})'
            write_status(status)

        def on_warn(msg):
            warnings.append(msg)
            status.warnings = warnings
            write_status(status)

        wdir = config.work_dir(work_id)
        arc_registries = await extract_arcs(blocks, granularity=granularity,
                                            work_dir=wdir / 'arcs',
                                            progress_cb=on_progress,
                                            arc_progress_cb=on_arc_progress,
                                            warn_cb=on_warn)
        registry = await asyncio.to_thread(merge_arcs, arc_registries)
        if not registry.characters:
            raise ParseError('未能抽取到任何人物，无法构建图谱')
```

（保留其后 `events.json` 持久化等代码不变；`on_progress` 原"抽取中 {done}/{total} 块"message 由 `on_arc_progress` 的 arc 消息替代。）

- [ ] **Step 4: 运行验证通过**

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_pipeline_integration.py -v`
Expected: PASS (3 passed：原 2 个 + 新增等价性)

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/orchestrator.py backend/tests/test_pipeline_integration.py
git commit -m "feat: wire arc-parallel extraction and cross-arc merge into pipeline"
```

---

### Task 9: 全量回归 + 图谱更新

**Files:** 无（运行命令）

- [ ] **Step 1: 全量测试**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: ALL PASS（test_config_arc 2 + test_partition 6 + test_extract 5 + test_extract_arcs 5 + test_merge 9 + test_merge_arcs 7 + test_llm 14 + test_summarize 5 + test_pipeline_integration 3 + 其余 = 全部通过，0 failed）

- [ ] **Step 2: 更新知识图谱**

Run: `graphify update .`
Expected: 输出显示已扫描/更新，无报错。

- [ ] **Step 3: 提交（如 graphify-out 有变更）**

```bash
git add -A
git commit -m "chore: refresh knowledge graph after arc-parallel extraction"
```

（若 `git status` 显示无变更，则跳过本步。）
