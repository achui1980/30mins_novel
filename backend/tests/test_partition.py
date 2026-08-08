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
    assert counts["黛玉"] >= 2
    assert counts["林黛玉"] >= 2


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


def _assert_no_empty_arcs(arcs, total_blocks):
    assert arcs, "expected at least one arc"
    assert all(arc for arc in arcs), f"found empty arc: {[len(a) for a in arcs]}"
    assert sum(len(a) for a in arcs) == total_blocks, "block total not conserved"
    arc_of = {}
    for i, arc in enumerate(arcs):
        for b in arc:
            arc_of.setdefault(b.chapter_id, set()).add(i)
    assert all(len(idx) == 1 for idx in arc_of.values()), "chapter split across arcs"


def test_partition_no_empty_arcs_many_chapters_default_target():
    blocks = _many_chapters(1000)
    arcs = partition_blocks(blocks)
    _assert_no_empty_arcs(arcs, len(blocks))


def test_partition_no_empty_arcs_handcrafted_sizes():
    sizes = [3, 7, 11, 1, 2, 14, 9, 2, 6, 10, 1, 15, 9, 4, 1, 2, 7, 7, 2, 4, 2]
    blocks = []
    for i, n in enumerate(sizes):
        blocks += _blocks(n, f"ch{i:04d}")
    arcs = partition_blocks(blocks, arc_blocks_target=20)
    _assert_no_empty_arcs(arcs, len(blocks))


def test_scan_global_anchors_returns_common_names():
    blocks = [Block(block_id="ch0001_b000", chapter_id="ch0001", chapter_title="第ch0001章", order=0, text="贾宝玉。" * 10),
              Block(block_id="ch0002_b000", chapter_id="ch0002", chapter_title="第ch0002章", order=1, text="贾宝玉。" * 10)]
    anchors = scan_global_anchors(blocks, top_n=5)
    assert "贾宝玉" in anchors
    assert len(anchors) <= 5
