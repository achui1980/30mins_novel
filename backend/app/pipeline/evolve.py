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

    畸形输入一律跳过、绝不抛异常（兑现模块头部的"永不抛异常"约定）：
    非 dict 元素忽略，缺 id 的元素忽略。

    order 缺失或非数值时退化成该元素的**枚举下标**，而不是 0：退化成 0 会让
    所有章节同序，prefilter_candidates 的"同章并存"判断随即否掉每一对人物，
    transitions 永久为空且没有任何报错。用下标至少保住单调性，让漏传 order
    的调用方降级而不是静默失效。
    """
    out: dict[str, int] = {}
    for index, item in enumerate(chapters or []):
        if not isinstance(item, dict):
            continue
        cid = item.get("id")
        if not cid:
            continue
        try:
            order = int(item["order"])
        except (KeyError, TypeError, ValueError):
            order = index
        out[str(cid)] = order
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
                        # 这里的 chapter_id 是上面按 order 最小推出的**首次出场章**，
                        # 与 RelationRecord.chapter_id（"最长证据所在章"，语义不稳）
                        # 同名但不同义。spec §4.1 定的字段名就是 chapter_id。
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
