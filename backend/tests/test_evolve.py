"""关系演变判定测试 (design §3.3/§9)。全部离线。"""

from __future__ import annotations

from app.models import Relationship
from app.pipeline.evolve import chapter_order_map, prefilter_candidates
from app.pipeline.merge import EntityRegistry

# order 故意与 chapter_id 的字典序**不一致**（ch0002 排在 ch0010 之后）。
# 若两者一致，"章节先后只以 order 为准"这条契约就无法被测试否证：把
# min(known, key=order) 换成 known[0] 或 min(known) 都会照样通过。
CHAPTERS = [
    {"id": "ch0001", "title": "第一章", "order": 1},
    {"id": "ch0002", "title": "第二章", "order": 9},
    {"id": "ch0010", "title": "第十章", "order": 2},
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
    assert ORDER == {"ch0001": 1, "ch0002": 9, "ch0010": 2, "ch0020": 4}


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


def test_first_appearance_uses_order_not_chapter_id_lexical():
    """首次出场章只能按 order 判：既不是插入序的第一章，也不是字典序最小的章。

    朋友 先在 ch0002(order 9) 出现、后在 ch0010(order 2) 出现，所以：
    - 插入序第一 = ch0002（错）
    - 字典序最小 = ch0002（错）
    - order 最小 = ch0010（对）
    """
    reg = EntityRegistry()
    for chapter in ("ch0002", "ch0010"):
        reg.add_relationship(_rel("甲", "乙", "朋友"), chapter)
    for _ in range(2):
        reg.add_relationship(_rel("甲", "乙", "敌人"), "ch0020")

    cands = prefilter_candidates(reg, ORDER)
    assert len(cands) == 1
    steps = cands[0]["steps"]
    assert [s["chapter_id"] for s in steps] == ["ch0010", "ch0020"]
    assert [s["category"] for s in steps] == ["朋友", "敌人"]


def test_steps_are_sorted_by_order_not_insertion_order():
    """后发生的类别先入库时，steps 仍须按 order 升序 —— 这才是时间轴。"""
    reg = EntityRegistry()
    for _ in range(2):  # 敌人 起于 ch0020(order 4)，先入库
        reg.add_relationship(_rel("甲", "乙", "敌人"), "ch0020")
    for _ in range(2):  # 朋友 起于 ch0001(order 1)，后入库
        reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0001")

    cands = prefilter_candidates(reg, ORDER)
    assert len(cands) == 1
    steps = cands[0]["steps"]
    assert [s["category"] for s in steps] == ["朋友", "敌人"]
    assert [s["chapter_id"] for s in steps] == ["ch0001", "ch0020"]


def test_candidates_are_sorted_by_pair():
    """多对人物的输出顺序按人物对排序，与入库顺序无关。"""
    reg = EntityRegistry()
    for first, second in (("甲", "乙"), ("丙", "丁")):
        for _ in range(2):
            reg.add_relationship(_rel(first, second, "朋友"), "ch0001")
        for _ in range(2):
            reg.add_relationship(_rel(first, second, "敌人"), "ch0020")

    cands = prefilter_candidates(reg, ORDER)
    assert [c["pair"] for c in cands] == [["丁", "丙"], ["乙", "甲"]]


# -- chapter_order_map 的畸形输入：只跳过、不抛异常 -------------------------


def test_chapter_order_map_skips_non_dict_elements():
    assert chapter_order_map(
        ["ch0001", None, {"id": "ch0002", "order": 9}]
    ) == {"ch0002": 9}


def test_chapter_order_map_falls_back_to_enumeration_index_for_bad_order():
    assert chapter_order_map(
        [
            {"id": "ch0001", "order": 7},
            {"id": "ch0002", "order": "第二章"},
        ]
    ) == {"ch0001": 7, "ch0002": 1}


def test_chapter_order_map_without_order_keys_stays_monotonic():
    """缺 order 时退化成枚举下标，而不是全为 0。

    全 0 会让 prefilter_candidates 的"同章并存"判断否掉每一对人物，
    transitions 永久为空且没有任何报错 —— 静默失效比报错更糟。
    """
    got = chapter_order_map(
        [
            {"id": "ch0001", "title": "第一章"},
            {"id": "ch0002", "title": "第二章"},
            {"id": "ch0010", "title": "第十章"},
        ]
    )
    assert got == {"ch0001": 0, "ch0002": 1, "ch0010": 2}
    assert sorted(got, key=got.get) == ["ch0001", "ch0002", "ch0010"]


def test_prefilter_still_works_when_chapters_lack_order():
    """退化序下 prefilter 仍须判得出演变（静默失效的回归守卫）。"""
    order = chapter_order_map(
        [{"id": "ch0001", "title": "第一章"}, {"id": "ch0020", "title": "第二十章"}]
    )
    reg = EntityRegistry()
    for _ in range(2):
        reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0001")
    for _ in range(2):
        reg.add_relationship(_rel("甲", "乙", "敌人"), "ch0020")

    cands = prefilter_candidates(reg, order)
    assert len(cands) == 1
    assert [s["chapter_id"] for s in cands[0]["steps"]] == ["ch0001", "ch0020"]
