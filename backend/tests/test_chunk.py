"""Tests for the chunking layer."""

from app.pipeline.chunk import Block, chunk_chapter, chunk_novel, estimate_tokens
from app.pipeline.parse import Chapter, ParsedNovel


def test_estimate_tokens_nonzero():
    assert estimate_tokens("这是一段中文文本") > 0
    assert estimate_tokens("这是一段中文文本") >= estimate_tokens("短")


def test_chunk_chapter_produces_blocks():
    text = "。".join(f"第{i}句话内容" for i in range(200))
    ch = Chapter(index=0, title="第一章", text=text)
    blocks = chunk_chapter(ch, start_order=0)
    assert blocks
    assert all(isinstance(b, Block) for b in blocks)
    assert all(b.chapter_id == ch.id for b in blocks)
    assert all(b.chapter_title == "第一章" for b in blocks)
    # block ids are prefixed by chapter id
    assert all(b.block_id.startswith(ch.id) for b in blocks)


def test_chunk_novel_preserves_global_order():
    chapters = [
        Chapter(index=0, title="第一章", text="内容" * 500),
        Chapter(index=1, title="第二章", text="故事" * 500),
    ]
    novel = ParsedNovel(title="测试", chapters=chapters)
    blocks = chunk_novel(novel)
    orders = [b.order for b in blocks]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)  # unique, monotonic


def test_empty_chapter_yields_no_blocks():
    ch = Chapter(index=0, title="空章", text="")
    assert chunk_chapter(ch, start_order=0) == []
