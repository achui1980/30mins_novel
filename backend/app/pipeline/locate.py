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
from pathlib import Path

from graphify.paths import write_json_atomic

from .merge import EntityRegistry

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
    graph_json_path: Path,
    registry: EntityRegistry,
    label_to_id: dict[str, str],
    paragraphs_by_chapter: dict[str, list[str]],
) -> None:
    """Patch graph.json's edges in place with resolved `source_location`.

    Matches edges back to `registry.relationships` via (source_node_id,
    target_node_id, category) — graph.json edges only carry node ids, not
    canonical character names, so `label_to_id` (from GraphArtifacts) is the
    bridge. Edges whose relationship can't be resolved (should not normally
    happen) are left untouched.

    Best-effort: NEVER raises. Any failure to read, parse, or interpret
    graph.json (missing file, invalid JSON, unexpected shapes, malformed
    registry records or edges) results in a silent no-op or partial patch —
    callers must treat "graph.json unchanged" as success, not as an error to
    propagate. See module docstring.
    """
    try:
        data = json.loads(graph_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return

    edge_list = data.get("links") if data.get("links") is not None else data.get("edges", [])
    if not isinstance(edge_list, list):
        edge_list = []

    loc_by_pair: dict[tuple[str, str, str], str] = {}
    for rec in registry.relationships.values():
        try:
            sid, tid = label_to_id.get(rec.source), label_to_id.get(rec.target)
            if sid is None or tid is None:
                continue
            loc_by_pair[(sid, tid, rec.category)] = resolve_source_location(
                rec.chapter_id, rec.evidence, paragraphs_by_chapter
            )
        except (AttributeError, TypeError):
            continue

    for edge in edge_list:
        try:
            key = (edge.get("source"), edge.get("target"), edge.get("category") or edge.get("relation"))
            loc = loc_by_pair.get(key)
            if loc:
                edge["source_location"] = loc
        except (AttributeError, TypeError):
            continue

    write_json_atomic(graph_json_path, data, indent=2, ensure_ascii=False)
