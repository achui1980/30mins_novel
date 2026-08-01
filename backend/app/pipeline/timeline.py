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
