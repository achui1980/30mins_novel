"""Extraction layer: per-block LLM structured extraction (design §4.2).

Uses AWS Strands ``agent.structured_output(ChunkExtraction, prompt)`` against
Amazon Bedrock. Concurrency is bounded by a semaphore; failed blocks retry with
exponential backoff and are ultimately skipped (recorded as a warning) rather
than failing the whole job.

When ``config.USE_FAKE_LLM`` is set, a deterministic regex-based extractor is
used instead so the full pipeline runs offline and in tests.
"""

from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable, Optional

from .. import config
from ..models import ChunkExtraction
from .chunk import Block
from .merge import EntityRegistry

# A callback the orchestrator supplies to receive per-block progress.
ProgressCb = Callable[[int, int], None]


SYSTEM_PROMPT = (
    "你是一个小说信息抽取引擎。给定一段小说正文，抽取其中的人物、地点、事件和人物关系，"
    "并严格按照给定的结构化 schema 返回。要求：\n"
    "- 人物 name 使用最正式/最常用的称呼，把绰号代称放进 aliases。\n"
    "- 关系 category 必须是以下之一：家人, 爱人, 朋友, 敌人, 师徒, 主仆, 同盟, 其他。\n"
    "- 关系必须给出简短 detail 与原文 evidence，并估计 confidence(0-1)。\n"
    "- 只抽取文中明确出现或强烈暗示的信息，不要编造。"
)

QUICK_HINT = "\n注意：当前为【快速】档，只需抽取主要角色、主线关系与关键事件，忽略龙套与次要地点。"
COMPLETE_HINT = "\n注意：当前为【完整】档，尽量抽取全部人物、地点、事件与关系。"


def _build_prompt(block: Block, known_entities: str, granularity: str) -> str:
    hint = QUICK_HINT if granularity == "quick" else COMPLETE_HINT
    parts = [SYSTEM_PROMPT, hint]
    if known_entities:
        parts.append("\n" + known_entities)
    parts.append(f"\n【章节】{block.chapter_title}")
    parts.append("【正文】\n" + block.text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Strands / Bedrock backend
# ---------------------------------------------------------------------------


def _make_agent():  # pragma: no cover - requires AWS creds
    from strands import Agent
    from strands.models import BedrockModel

    model = BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.BEDROCK_REGION)
    return Agent(model=model, system_prompt=SYSTEM_PROMPT)


def _extract_block_sync(agent, prompt: str) -> ChunkExtraction:  # pragma: no cover - AWS
    """Blocking call into Strands structured_output."""
    return agent.structured_output(ChunkExtraction, prompt)


# ---------------------------------------------------------------------------
# Fake deterministic backend (offline / tests)
# ---------------------------------------------------------------------------

_FAKE_NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")


def fake_extract_block(block: Block) -> ChunkExtraction:
    """A cheap deterministic extractor for offline runs.

    Heuristic: treat the most frequent 2-4 char CJK tokens in the block as
    characters, and pair consecutive distinct characters as 'friend' relations.
    This is *not* accurate but produces a well-formed graph for demos/tests.
    """
    from ..models import Character, Event, Relationship, RelationCategory

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
    for name, cnt in ranked:
        if cnt < 2:
            continue
        # Skip candidates that are substrings of an already-selected name.
        if any(name in chosen or chosen in name for chosen in top):
            continue
        top.append(name)
        if len(top) >= 5:
            break
    characters = [Character(name=n, description=f"在{block.chapter_title}中出现") for n in top]

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
    return ChunkExtraction(characters=characters, relationships=relationships, events=events)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


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
    agent = None
    if not use_fake:
        agent = _make_agent()

    sem = asyncio.Semaphore(config.EXTRACT_CONCURRENCY)
    processed = 0

    async def run_block(block: Block, known: str) -> ChunkExtraction | None:
        async with sem:
            for attempt in range(config.EXTRACT_MAX_RETRIES):
                try:
                    if use_fake:
                        return fake_extract_block(block)
                    prompt = _build_prompt(block, known, granularity)
                    return await asyncio.to_thread(_extract_block_sync, agent, prompt)
                except Exception as exc:  # noqa: BLE001
                    if attempt == config.EXTRACT_MAX_RETRIES - 1:
                        if warn_cb:
                            warn_cb(f"块 {block.block_id} 抽取失败，已跳过: {exc}")
                        return None
                    await asyncio.sleep(config.EXTRACT_BACKOFF_BASE ** attempt)
        return None

    # Process in ordered windows so sliding context stays fresh.
    window = max(1, config.EXTRACT_CONCURRENCY)
    for start in range(0, total, window):
        batch = blocks[start : start + window]
        known = registry.known_entities_prompt()
        results = await asyncio.gather(*(run_block(b, known) for b in batch))
        for block, extraction in zip(batch, results):
            if extraction is not None:
                registry.add_extraction(extraction, block.chapter_id)
            processed += 1
            if progress_cb:
                progress_cb(processed, total)
