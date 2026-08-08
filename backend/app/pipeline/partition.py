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
        if remaining_arcs > 0 and (remaining_groups == remaining_arcs
                                   or (count >= per_arc_target and remaining_groups > remaining_arcs)):
            idx += 1
            count = 0
    return arcs


def scan_global_anchors(blocks: list[Block], *, top_n: Optional[int] = None) -> list[str]:
    """扫描全书最高频人名候选，作为全局锚点注入各弧首个窗口。"""
    top = top_n or config.ARC_ANCHOR_COUNT
    counts = count_cjk_ngrams("\n".join(b.text for b in blocks))
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
