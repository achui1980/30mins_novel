"""关系演变判定 (design §3.3)。

前提：EntityRegistry.relationships 的键含 category，所以同一人物对的不同
关系类别本来就是多条独立记录、在图里是多条平行边。这里做两件事：

1. 确定性预过滤：把同一人物对的多个类别聚起来，用稳定性阈值丢掉抽取噪声。
2. 强模型确认：只把"看起来真的变了"的对送去让强模型确认。

本模块永不抛异常 —— 失败就退化成"没有演变"，其余图谱不受影响。
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from pydantic import BaseModel, Field

from .. import config
from ..models import RelationCategory
from .merge import EntityRegistry

logger = logging.getLogger(__name__)


def chapter_order_map(chapters: Iterable[dict]) -> dict[str, int]:
    """把 [{id,title,order}] 压成 chapter_id -> order 的查表。

    章节先后**只以 order 为准**。chNNNN 的字典序恰好和章序一致是巧合，
    不是契约。
    """
    out: dict[str, int] = {}
    for item in chapters or []:
        cid = (item or {}).get("id")
        if cid:
            out[cid] = int(item.get("order") or 0)
    return out


def prefilter_candidates(
    registry: EntityRegistry,
    chapter_order: dict[str, int],
    *,
    stability_min: int | None = None,
) -> list[dict]:
    """确定性预过滤。返回 confirmed=False 的候选演变列表。"""
    if stability_min is None:
        stability_min = config.EVOLVE_STABILITY_MIN

    groups: dict[tuple[str, str], list] = {}
    for rec in registry.relationships.values():
        if rec.category == RelationCategory.OTHER.value:
            continue
        groups.setdefault((rec.source, rec.target), []).append(rec)

    candidates: list[dict] = []
    for pair in sorted(groups):
        recs = groups[pair]
        if len(recs) < 2:
            continue

        states: list[tuple[int, str, object]] = []
        for rec in recs:
            known = [c for c in rec.chapters if c in chapter_order]
            if not known:
                continue
            total = sum(rec.chapters[c] for c in known)
            if total < stability_min and len(known) < 2:
                continue
            first = min(known, key=lambda c: chapter_order[c])
            states.append((chapter_order[first], first, rec))

        if len(states) < 2:
            continue
        # 两个状态起始于同一章，说明是同章并存而不是先后演变。
        if len({s[0] for s in states}) != len(states):
            continue

        states.sort(key=lambda s: s[0])
        candidates.append(
            {
                "pair": [pair[0], pair[1]],
                "steps": [
                    {
                        "chapter_id": chapter_id,
                        "category": rec.category,
                        "evidence": rec.evidence,
                    }
                    for _, chapter_id, rec in states
                ],
                "confirmed": False,
            }
        )
    return candidates
