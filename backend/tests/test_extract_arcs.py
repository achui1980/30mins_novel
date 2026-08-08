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
