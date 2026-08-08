"""Extraction layer: per-block LLM structured extraction (design §4.2).

LLM calls are routed through ``pipeline.llm``, a provider-agnostic layer that
supports Amazon Bedrock (via strands) and OpenAI-compatible endpoints (DeepSeek
and similar). Concurrency is bounded by a semaphore; failed blocks retry with
exponential backoff and are ultimately skipped (recorded as a warning) rather
than failing the whole job.

When ``config.USE_FAKE_LLM`` is set, a deterministic regex-based extractor is
used instead so the full pipeline runs offline and in tests.
"""

from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable, Optional

from .. import config
from ..models import ChunkExtraction
from .chunk import Block
from .merge import EntityRegistry
from .partition import count_cjk_ngrams, partition_blocks, scan_global_anchors

# A callback the orchestrator supplies to receive per-block progress.
ProgressCb = Callable[[int, int], None]


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


def _build_prompt(block: Block, known_entities: str, granularity: str) -> str:
    hint = QUICK_HINT if granularity == "quick" else COMPLETE_HINT
    parts = [SYSTEM_PROMPT, hint]
    if known_entities:
        parts.append("\n" + known_entities)
    parts.append(f"\n【章节】{block.chapter_title}")
    parts.append("【正文】\n" + block.text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Provider-backed backend (via pipeline.llm)
# ---------------------------------------------------------------------------


def _extract_block_sync(prompt: str) -> ChunkExtraction:  # pragma: no cover - requires LLM creds
    """Blocking structured extraction, provider-agnostic."""
    from . import llm

    # 重试已收敛到 llm 层（spec §6）：由 llm.structured_output 内部负责
    # attempts 次退避重试，外层 run_block 不再叠加重试循环。
    return llm.structured_output(
        ChunkExtraction, prompt, system_prompt=SYSTEM_PROMPT, what="ChunkExtraction",
        attempts=config.EXTRACT_MAX_RETRIES,
    )


# ---------------------------------------------------------------------------
# Fake deterministic backend (offline / tests)
# ---------------------------------------------------------------------------


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

    counts = count_cjk_ngrams(block.text)
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


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


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
                warn_cb(f"块 {block.block_id} 抽取失败，已跳过: {exc}")
            return None


async def extract_all(
    blocks: list[Block],
    registry: EntityRegistry,
    granularity: str = "quick",
    progress_cb: Optional[ProgressCb] = None,
    warn_cb: Optional[Callable[[str], None]] = None,
) -> None:
    """Extract every block into ``registry``.

    Blocks are processed with bounded concurrency. Because the sliding known-
    entity context must stay current, extraction results are *merged in block
    order* even though the LLM calls run concurrently: we launch a window of
    calls, then merge completed ones in order and refresh the context for the
    next window.
    """
    total = len(blocks)
    if total == 0:
        return

    use_fake = config.USE_FAKE_LLM

    sem = asyncio.Semaphore(config.EXTRACT_CONCURRENCY)
    processed = 0

    # Process in ordered windows so sliding context stays fresh.
    window = max(1, config.EXTRACT_CONCURRENCY)
    for start in range(0, total, window):
        batch = blocks[start : start + window]
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
        nonlocal processed
        arc_done = 0
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
                        arc_done += 1
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
            async with lock:
                processed += len(arc_blocks) - arc_done
                if progress_cb:
                    progress_cb(processed, total)
            if work_dir:
                try:
                    _save_arc(registry, work_dir, arc_index)
                except Exception as save_exc:  # noqa: BLE001
                    if warn_cb:
                        warn_cb(f'arc {arc_index + 1} 持久化失败: {save_exc}')
            if arc_progress_cb:
                arc_progress_cb(arc_index, arc_count, processed, total)
            return registry

    return await asyncio.gather(*(run_arc(arcs[i], i) for i in range(arc_count)))
