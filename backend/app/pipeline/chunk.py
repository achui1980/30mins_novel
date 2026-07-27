"""Chunking layer: chapters -> ~2-4k token blocks with chapter attribution.

We do not depend on a real tokenizer. For mixed Chinese/English novel text a
reasonable approximation is ~1 token per Chinese character and ~1 token per 4
Latin characters. To keep it simple and robust we estimate tokens as
``len(text) / CHARS_PER_TOKEN`` where CHARS_PER_TOKEN is tuned for CJK-heavy
prose. Blocks split on paragraph boundaries so we never cut mid-sentence when
avoidable.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import CHUNK_MAX_TOKENS, CHUNK_TARGET_TOKENS
from .parse import Chapter, ParsedNovel

# Heuristic: CJK prose is roughly 1 char/token; we bias slightly < 1 to be safe.
CHARS_PER_TOKEN = 1.6


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


@dataclass
class Block:
    """A unit of text handed to the extractor."""

    block_id: str
    chapter_id: str
    chapter_title: str
    order: int  # global order across the whole novel
    text: str


def _split_paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    return paras or ([text.strip()] if text.strip() else [])


def _split_long_paragraph(para: str, max_chars: int) -> list[str]:
    """Split a single oversized paragraph on sentence punctuation, then hard-cut."""
    if len(para) <= max_chars:
        return [para]
    pieces: list[str] = []
    buf = ""
    # Break after common sentence terminators (CJK + Latin).
    terminators = "。！？!?；;\n"
    for ch in para:
        buf += ch
        if ch in terminators and len(buf) >= max_chars * 0.6:
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    # Hard-cut any still-too-long fragment.
    out: list[str] = []
    for p in pieces:
        while len(p) > max_chars:
            out.append(p[:max_chars])
            p = p[max_chars:]
        if p:
            out.append(p)
    return out


def chunk_chapter(
    chapter: Chapter,
    start_order: int,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    max_tokens: int = CHUNK_MAX_TOKENS,
) -> list[Block]:
    """Split one chapter into blocks near ``target_tokens`` (never over max)."""
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    target_chars = int(target_tokens * CHARS_PER_TOKEN)

    blocks: list[Block] = []
    order = start_order
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len, order
        if not buf:
            return
        text = "\n".join(buf).strip()
        if text:
            blocks.append(
                Block(
                    block_id=f"{chapter.id}_b{len(blocks):03d}",
                    chapter_id=chapter.id,
                    chapter_title=chapter.title,
                    order=order,
                    text=text,
                )
            )
            order += 1
        buf = []
        buf_len = 0

    for para in _split_paragraphs(chapter.text):
        for piece in _split_long_paragraph(para, max_chars):
            piece_len = len(piece)
            if buf_len + piece_len > target_chars and buf:
                flush()
            buf.append(piece)
            buf_len += piece_len
    flush()

    # A chapter with a title but no body still yields one (empty-ish) marker block
    # so downstream chapter accounting stays consistent.
    if not blocks and chapter.text.strip():
        blocks.append(
            Block(
                block_id=f"{chapter.id}_b000",
                chapter_id=chapter.id,
                chapter_title=chapter.title,
                order=start_order,
                text=chapter.text.strip(),
            )
        )
    return blocks


def chunk_novel(novel: ParsedNovel) -> list[Block]:
    """Chunk an entire parsed novel, preserving global order + chapter attribution."""
    blocks: list[Block] = []
    order = 0
    for chapter in novel.chapters:
        chapter_blocks = chunk_chapter(chapter, start_order=order)
        blocks.extend(chapter_blocks)
        order += len(chapter_blocks)
    return blocks
