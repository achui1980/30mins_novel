"""关系演变判定测试 (design §3.3/§9)。全部离线。"""

from __future__ import annotations

from app.models import Relationship
from app.pipeline.evolve import chapter_order_map, prefilter_candidates
from app.pipeline.merge import EntityRegistry

CHAPTERS = [
    {"id": "ch0001", "title": "第一章", "order": 1},
    {"id": "ch0002", "title": "第二章", "order": 2},
    {"id": "ch0010", "title": "第十章", "order": 3},
    {"id": "ch0020", "title": "第二十章", "order": 4},
]
ORDER = chapter_order_map(CHAPTERS)


def _rel(source, target, category, evidence=""):
    return Relationship(
        source=source,
        target=target,
        category=category,
        detail="",
        evidence=evidence,
        confidence=0.9,
    )


def test_chapter_order_map_builds_lookup():
    assert ORDER == {"ch0001": 1, "ch0002": 2, "ch0010": 3, "ch0020": 4}


def test_single_category_pair_is_not_a_candidate():
    reg = EntityRegistry()
    reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0001")
    reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0002")

    assert prefilter_candidates(reg, ORDER) == []


def test_two_stable_states_become_a_candidate():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友", "并肩而行"), chapter)
    for chapter in ("ch0010", "ch0020"):
        reg.add_relationship(_rel("甲", "乙", "敌人", "拔剑相向"), chapter)

    cands = prefilter_candidates(reg, ORDER)
    assert len(cands) == 1
    cand = cands[0]
    assert cand["pair"] == ["乙", "甲"]
    assert [s["category"] for s in cand["steps"]] == ["朋友", "敌人"]
    assert [s["chapter_id"] for s in cand["steps"]] == ["ch0001", "ch0010"]
    assert cand["steps"][1]["evidence"] == "拔剑相向"
    assert cand["confirmed"] is False


def test_single_occurrence_state_is_dropped_as_noise():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友"), chapter)
    reg.add_relationship(_rel("甲", "乙", "敌人"), "ch0010")

    assert prefilter_candidates(reg, ORDER) == []


def test_other_category_is_excluded():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友"), chapter)
    for chapter in ("ch0010", "ch0020"):
        reg.add_relationship(_rel("甲", "乙", "其他"), chapter)

    assert prefilter_candidates(reg, ORDER) == []


def test_states_starting_in_the_same_chapter_are_not_evolution():
    reg = EntityRegistry()
    for _ in range(2):
        reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0001")
        reg.add_relationship(_rel("甲", "乙", "同盟"), "ch0001")

    assert prefilter_candidates(reg, ORDER) == []


def test_chapters_outside_the_order_table_are_ignored():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友"), chapter)
    for _ in range(3):
        reg.add_relationship(_rel("甲", "乙", "敌人"), "ch9999")

    assert prefilter_candidates(reg, ORDER) == []


def test_pair_uses_the_same_normalization_as_merge():
    """无向类别在 merge.py 里按 src > tgt 交换过，预过滤必须沿用同一顺序。"""
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("乙", "甲", "朋友"), chapter)
    for chapter in ("ch0010", "ch0020"):
        reg.add_relationship(_rel("甲", "乙", "敌人"), chapter)

    cands = prefilter_candidates(reg, ORDER)
    assert len(cands) == 1
    assert cands[0]["pair"] == ["乙", "甲"]
