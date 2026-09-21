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


# --- 第二级：强模型确认 -----------------------------------------------------

CONFIRM_INSTRUCTIONS = """你是中文小说的关系分析助手。
下面给出若干「人物对」的关系状态序列，每个状态包含章节、关系类别和一句原文证据。
请判断每一对的关系是否**真的随剧情发生了转变**（例如朋友后来变成敌人），
而不是抽取噪声或同一段关系被打了不同标签。

判断要点：
- 真实演变：前后类别语义确实冲突，且证据支持这种转变。
- 不是演变：同一段关系的不同侧面（如"同盟"与"朋友"并存）、称呼差异、
  或证据完全看不出冲突。
- 证据只是该类别下最长的一条原文，不保证出自所标注的那一章；
  判断请以类别序列本身的语义冲突为主，不要因为证据与章节对不上而否定。

只输出 JSON。对每一项给出 index 和 is_evolution。"""


class ConfirmItem(BaseModel):
    index: int
    is_evolution: bool
    reason: str = ""


class ConfirmResult(BaseModel):
    items: list[ConfirmItem] = Field(default_factory=list)


def _format_candidate(offset: int, candidate: dict) -> str:
    pair = " 与 ".join(candidate["pair"])
    lines = [f"[{offset}] {pair}"]
    for step in candidate["steps"]:
        evidence = step.get("evidence") or "（无证据）"
        lines.append(
            f"    {step['chapter_id']}：{step['category']} —— 「{evidence}」"
        )
    return "\n".join(lines)


def _llm_confirm(batch: list[dict]) -> list[int]:
    """让强模型确认一批候选，返回被判定为真实演变的下标（相对 batch）。"""
    from . import llm

    body = "\n".join(_format_candidate(i, c) for i, c in enumerate(batch))
    prompt = f"{CONFIRM_INSTRUCTIONS}\n\n待判定：\n{body}"
    # llm.structured_output 的 system_prompt 是**必填**关键字参数（无默认值），
    # 省掉它会直接 TypeError，让整条确认路径永久降级成"没有演变"。判断规则本身
    # 拼在 prompt 正文里，system_prompt 只放一句角色设定（与 merge.py L2 一致）。
    result = llm.structured_output(
        ConfirmResult,
        prompt,
        system_prompt="你是中文小说的关系分析助手。",
        what="RelationEvolutionConfirm",
        tier="strong",
    )
    return [
        item.index
        for item in result.items
        if item.is_evolution and 0 <= item.index < len(batch)
    ]


def detect_transitions(
    registry: EntityRegistry,
    chapters: Iterable[dict],
    *,
    confirmer: Callable[[list[dict]], list[int]] | None = None,
    warn_cb: Callable[[str], None] | None = None,
) -> list[dict]:
    """判定关系演变。永不抛异常；失败时返回空列表并记一条警告。

    降级的代价只是"平行边不展开成时间轴"：节点/边的按章分布与顶层 chapters
    照常输出，滑块与出场曲线不受影响。

    config 一律在函数体内惰性读取，好让 monkeypatch 生效。
    """
    # 总开关关掉时连预过滤都不跑，强模型一次也不会被调用。
    if not config.EVOLVE_ENABLED:
        return []
    try:
        order = chapter_order_map(chapters)
        candidates = prefilter_candidates(registry, order)
        if not candidates:
            return []

        # 离线模式没有强模型可用：直接采纳预过滤结果，标为未确认，
        # 让 offline 测试仍然端到端走完预过滤。
        if confirmer is None and config.USE_FAKE_LLM:
            return candidates

        confirm = confirmer or _llm_confirm
        batch_size = max(1, config.EVOLVE_BATCH_SIZE)
        kept: list[dict] = []
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            # 下标由模型给出，越界一律忽略（幻觉不能错标到别的候选上）。
            for index in confirm(batch):
                if 0 <= index < len(batch):
                    item = dict(batch[index])  # 副本：别就地改预过滤结果
                    item["confirmed"] = True
                    kept.append(item)
        return kept
    except Exception:  # noqa: BLE001 - 本模块的契约就是永不抛异常
        logger.warning("evolve: 关系演变判定失败，本次不输出演变", exc_info=True)
        if warn_cb is not None:
            warn_cb("关系演变判定失败，本次结果不含关系演变标记")
        return []
