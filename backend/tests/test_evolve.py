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


# -- detect_transitions：强模型确认与降级 -----------------------------------


def _two_state_registry():
    reg = EntityRegistry()
    for chapter in ("ch0001", "ch0002"):
        reg.add_relationship(_rel("甲", "乙", "朋友", "并肩而行"), chapter)
    for chapter in ("ch0010", "ch0020"):
        reg.add_relationship(_rel("甲", "乙", "敌人", "拔剑相向"), chapter)
    return reg


def _two_pair_registry():
    """两对人物各有一次演变 —— 预过滤输出按人物对排序为 [丁丙, 乙甲]。

    需要两个候选才能看见"下标 -1 错标到最后一个候选"这类越界后果：只有一个
    候选时 batch[-1] is batch[0]，错标与正解完全同形，测不出来。
    """
    reg = EntityRegistry()
    for first, second in (("甲", "乙"), ("丙", "丁")):
        for _ in range(2):
            reg.add_relationship(_rel(first, second, "朋友"), "ch0001")
        for _ in range(2):
            reg.add_relationship(_rel(first, second, "敌人"), "ch0020")
    return reg


def test_two_pair_registry_yields_two_sorted_candidates():
    """给下面几个测试兜底：辅助函数真的产出两个按对排序的候选。"""
    cands = prefilter_candidates(_two_pair_registry(), ORDER)
    assert [c["pair"] for c in cands] == [["丁", "丙"], ["乙", "甲"]]


def test_detect_transitions_fake_mode_keeps_prefilter_unconfirmed(monkeypatch):
    """离线模式跳过强模型，直接采纳预过滤结果（confirmed=False）。

    显式把 config.USE_FAKE_LLM 设成 True，不靠 conftest 的
    os.environ.setdefault —— setdefault 不会覆盖环境里已有的
    NOVEL_KG_USE_FAKE_LLM=0，那种环境下本测试会掉进 _llm_confirm
    真去打 Bedrock。断言要钉的是分支，不是跑测试的机器。
    """
    from app.pipeline import evolve

    monkeypatch.setattr(evolve.config, "USE_FAKE_LLM", True)

    out = evolve.detect_transitions(_two_state_registry(), CHAPTERS)
    assert len(out) == 1
    assert out[0]["confirmed"] is False
    assert [s["category"] for s in out[0]["steps"]] == ["朋友", "敌人"]


def test_detect_transitions_uses_confirmer_and_marks_confirmed():
    from app.pipeline.evolve import detect_transitions

    seen = {}

    def confirmer(batch):
        seen["size"] = len(batch)
        return [0]

    out = detect_transitions(_two_state_registry(), CHAPTERS, confirmer=confirmer)
    assert seen["size"] == 1
    assert len(out) == 1
    assert out[0]["confirmed"] is True


def test_detect_transitions_drops_rejected_candidates():
    from app.pipeline.evolve import detect_transitions

    out = detect_transitions(_two_state_registry(), CHAPTERS, confirmer=lambda batch: [])
    assert out == []


def test_detect_transitions_never_raises_and_warns():
    from app.pipeline.evolve import detect_transitions

    warnings = []

    def boom(batch):
        raise RuntimeError("模型挂了")

    out = detect_transitions(
        _two_state_registry(), CHAPTERS, confirmer=boom, warn_cb=warnings.append
    )
    assert out == []
    assert len(warnings) == 1
    assert "关系演变" in warnings[0]


def test_detect_transitions_survives_malformed_confirmer_output():
    """强模型返回的东西根本不能迭代时，也只能降级成"没有演变"。"""
    from app.pipeline.evolve import detect_transitions

    warnings = []
    out = detect_transitions(
        _two_state_registry(),
        CHAPTERS,
        confirmer=lambda batch: None,
        warn_cb=warnings.append,
    )
    assert out == []
    assert len(warnings) == 1


def test_detect_transitions_ignores_out_of_range_indices():
    """下标越界只能被**静默跳过**，不能 IndexError 后降级、也不能错标到别的候选。

    关键是 warn_cb：跳过不该有警告，而"炸了再被 except 吞掉"必然有一条警告 ——
    只断言 out == [] 分不清这两种情况（两者都返回空列表）。
    """
    from app.pipeline.evolve import detect_transitions

    # 正越界：batch[7] 会 IndexError，被 except 吞掉后同样返回 []，
    # 所以必须靠"没有警告"来否证它。
    warnings = []
    assert (
        detect_transitions(
            _two_pair_registry(),
            CHAPTERS,
            confirmer=lambda batch: [7, -1],
            warn_cb=warnings.append,
        )
        == []
    )
    assert warnings == [], "越界下标应被静默跳过，而不是抛异常后降级"

    # 负下标：Python 的 batch[-1] 合法，会把**最后一个**候选错标成已确认。
    # 这一支不抛异常，只有两个候选时才看得见错标。
    warnings = []
    assert (
        detect_transitions(
            _two_pair_registry(),
            CHAPTERS,
            confirmer=lambda batch: [-1],
            warn_cb=warnings.append,
        )
        == []
    ), "负下标不能被当成「最后一个候选」而错标"
    assert warnings == []


def test_detect_transitions_dedupes_and_sorts_confirmed_indices():
    """模型重复或乱序给下标时：每个候选只出现一次，且保持批内升序。

    升序是 Task 5 特意建立的按人物对排序，Tasks 8/12/17 直接消费；
    重复则会让同一条演变在前端出现两遍。
    """
    from app.pipeline.evolve import detect_transitions

    out = detect_transitions(
        _two_pair_registry(), CHAPTERS, confirmer=lambda batch: [1, 0, 1, 1]
    )
    assert [c["pair"] for c in out] == [["丁", "丙"], ["乙", "甲"]]
    assert all(c["confirmed"] is True for c in out)


def test_detect_transitions_respects_kill_switch(monkeypatch):
    from app.pipeline import evolve

    monkeypatch.setattr(evolve.config, "EVOLVE_ENABLED", False)
    assert evolve.detect_transitions(_two_state_registry(), CHAPTERS) == []


def test_kill_switch_skips_the_strong_model_entirely(monkeypatch):
    """总开关关掉时连候选都不该送去确认（省掉整个强模型开销）。

    用间谍记录而**不是**在 confirmer 里抛异常：在"永不抛异常"的边界内抛任何
    东西都不构成断言 —— AssertionError 也是 Exception，会被 except 吞掉，
    函数照样返回 []，删掉总开关也测不出来。
    """
    from app.pipeline import evolve

    monkeypatch.setattr(evolve.config, "EVOLVE_ENABLED", False)

    called = []

    def spy(batch):
        called.append(batch)
        return []

    assert (
        evolve.detect_transitions(_two_state_registry(), CHAPTERS, confirmer=spy)
        == []
    )
    assert called == [], "kill switch 未生效：confirmer 仍被调用"


def test_detect_transitions_returns_empty_without_candidates():
    from app.pipeline.evolve import detect_transitions

    reg = EntityRegistry()
    reg.add_relationship(_rel("甲", "乙", "朋友"), "ch0001")
    assert detect_transitions(reg, CHAPTERS) == []


def test_detect_transitions_batches_by_config(monkeypatch):
    """候选多于一批时按 EVOLVE_BATCH_SIZE 切批，下标须相对每批解释。"""
    from app.pipeline import evolve

    monkeypatch.setattr(evolve.config, "EVOLVE_BATCH_SIZE", 1)

    reg = EntityRegistry()
    for first, second in (("甲", "乙"), ("丙", "丁")):
        for _ in range(2):
            reg.add_relationship(_rel(first, second, "朋友"), "ch0001")
        for _ in range(2):
            reg.add_relationship(_rel(first, second, "敌人"), "ch0020")

    sizes = []

    def confirmer(batch):
        sizes.append(len(batch))
        return [0]

    out = evolve.detect_transitions(reg, CHAPTERS, confirmer=confirmer)
    assert sizes == [1, 1]
    assert [c["pair"] for c in out] == [["丁", "丙"], ["乙", "甲"]]
    assert all(c["confirmed"] is True for c in out)


def test_detect_transitions_does_not_mutate_prefilter_candidates():
    """确认标记必须写在副本上，别把预过滤结果就地改掉。"""
    from app.pipeline import evolve

    captured = []

    def confirmer(batch):
        captured.extend(batch)
        return [0]

    out = evolve.detect_transitions(
        _two_state_registry(), CHAPTERS, confirmer=confirmer
    )
    assert out[0]["confirmed"] is True
    assert captured[0]["confirmed"] is False


def test_llm_confirm_matches_structured_output_signature(monkeypatch):
    """_llm_confirm 必须能真的调通 llm.structured_output。

    structured_output 的 system_prompt 是必填关键字参数（无默认值）。漏传它会
    TypeError，被"永不抛异常"的 except 吞掉，于是线上确认路径永久静默降级成
    "没有演变" —— 用真实签名绑定一次是唯一能否证这点的办法。
    """
    from app.pipeline import evolve, llm

    calls = {}

    def fake_structured_output(
        schema, prompt, *, system_prompt, what="", attempts=3, tier="fast"
    ):
        calls["tier"] = tier
        calls["what"] = what
        calls["prompt"] = prompt
        return schema(items=[{"index": 0, "is_evolution": True}])

    monkeypatch.setattr(llm, "structured_output", fake_structured_output)
    monkeypatch.setattr(evolve.config, "USE_FAKE_LLM", False)

    out = evolve.detect_transitions(_two_state_registry(), CHAPTERS)
    assert len(out) == 1, "确认路径未跑通（很可能被 except 吞了 TypeError）"
    assert out[0]["confirmed"] is True
    assert calls["tier"] == "strong"
    assert calls["what"] == "RelationEvolutionConfirm"
    # 判断规则拼在正文里，而不是只靠 system_prompt。
    assert "真的随剧情发生了转变" in calls["prompt"]
    assert "朋友" in calls["prompt"] and "敌人" in calls["prompt"]
