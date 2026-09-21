from app import config
from app.models import Character, Place, Relationship, RelationCategory
from app.pipeline.merge import (SIMILARITY_THRESHOLD, EntityRegistry,
                                MergeGroup, _find_merge_candidates, merge_arcs)


def _arc(chars, rels=(), places=()):
    reg = EntityRegistry()
    for c in chars:
        reg.add_character(c)
    for p in places:
        reg.add_place(p)
    for r in rels:
        reg.add_relationship(r)
    return reg


def test_merge_arcs_shared_character_merges():
    a = _arc([Character(name="贾宝玉")])
    b = _arc([Character(name="贾宝玉")])
    merged = merge_arcs([a, b])
    assert set(merged.characters) == {"贾宝玉"}
    assert merged.characters["贾宝玉"].mention_count == 2


def test_merge_arcs_alias_resolves_across_arcs():
    a = _arc([Character(name="贾宝玉", aliases=["宝玉", "宝二爷"])])
    b = _arc([Character(name="宝玉")])
    merged = merge_arcs([a, b], confirm=False)
    assert set(merged.characters) == {"贾宝玉"}


def test_merge_arcs_relations_merged_into_one():
    a = _arc([Character(name="贾宝玉"), Character(name="林黛玉")],
             [Relationship(source="贾宝玉", target="林黛玉", category=RelationCategory.LOVER, detail="青梅竹马")])
    b = _arc([Character(name="贾宝玉"), Character(name="林黛玉")],
             [Relationship(source="林黛玉", target="贾宝玉", category=RelationCategory.LOVER, detail="互诉衷肠")])
    merged = merge_arcs([a, b], confirm=False)
    assert (min("贾宝玉", "林黛玉"), max("贾宝玉", "林黛玉"), "爱人") in merged.relationships


def test_merge_arcs_l2_confirm_merges_and_rewrites_relations(monkeypatch):
    monkeypatch.setattr(config, "USE_FAKE_LLM", False)
    a = _arc([Character(name="林妹妹")],
             [Relationship(source="林妹妹", target="贾宝玉", category=RelationCategory.LOVER)])
    b = _arc([Character(name="林妹妹"), Character(name="林黛玉")],
             [Relationship(source="林黛玉", target="薛宝钗", category=RelationCategory.FRIEND)])
    merged = merge_arcs([a, b], confirmer=lambda batches: [
        {"names": ["林妹妹", "林黛玉"], "final_name": "林黛玉"}
    ])
    assert set(merged.characters) == {"贾宝玉", "林黛玉", "薛宝钗"}
    assert ("林黛玉", "贾宝玉", "爱人") in merged.relationships
    assert ("林黛玉", "薛宝钗", "朋友") in merged.relationships


def test_merge_arcs_l2_skipped_in_fake_mode(monkeypatch):
    import app.pipeline.merge as merge_mod
    def _boom(batches):
        raise AssertionError("must not be called")
    monkeypatch.setattr(merge_mod, "_llm_confirm", _boom)
    a = _arc([Character(name="林妹妹")])
    b = _arc([Character(name="林黛玉")])
    merged = merge_arcs([a, b], confirm=True)
    assert set(merged.characters) == {"林妹妹", "林黛玉"}


def test_merge_arcs_empty_inputs():
    merged = merge_arcs([])
    assert merged.characters == {}
    assert merged.events == []


def test_find_merge_candidates_marks_multi_arc_and_near_similar():
    a = _arc([Character(name="贾宝玉"), Character(name="林黛玉")])
    b = _arc([Character(name="贾宝玉"), Character(name="林哥哥")])
    merged = merge_arcs([a, b], confirm=False)
    candidates = _find_merge_candidates(merged, [a, b])
    assert "贾宝玉" in candidates          # 跨弧同现 ≥2
    assert set(candidates) <= set(merged.characters)


def test_merge_arcs_l2_confirm_accepts_pydantic_groups(monkeypatch):
    monkeypatch.setattr(config, "USE_FAKE_LLM", False)
    a = _arc([Character(name="林妹妹")])
    b = _arc([Character(name="林妹妹"), Character(name="林黛玉")])
    merged = merge_arcs([a, b], confirmer=lambda batches: [
        MergeGroup(names=["林妹妹", "林黛玉"], final_name="林黛玉")
    ])
    assert set(merged.characters) == {"林黛玉"}


def test_find_merge_candidates_prefilter_keeps_similar_and_drops_disjoint():
    a = _arc([Character(name="贾宝玉"), Character(name="林黛玉"), Character(name="史湘云")])
    b = _arc([Character(name="贾宝玉"), Character(name="黛玉")])
    merged = merge_arcs([a, b], confirm=False)
    candidates = _find_merge_candidates(merged, [a, b])
    assert "林黛玉" in candidates and "黛玉" in candidates   # 0.8 ratio, differing first chars
    assert "贾宝玉" in candidates                            # multi-arc rule
    assert "史湘云" not in candidates                         # disjoint pair excluded


def test_merge_arcs_l2_alias_index_repoints_to_survivor(monkeypatch):
    monkeypatch.setattr(config, "USE_FAKE_LLM", False)
    a = _arc([Character(name="林妹妹")])
    # 林妹 (near-similar to 林妹妹, ratio 0.8) makes 林妹妹 an L2 candidate so
    # the merge actually runs; without it a/b alone would produce no candidates.
    b = _arc([Character(name="林黛玉"), Character(name="林妹")])
    merged = merge_arcs([a, b], confirmer=lambda batches: [
        {"names": ["林妹妹", "林黛玉"], "final_name": "林黛玉"}
    ])
    assert merged.resolve_character("林妹妹") == "林黛玉"
    assert "林妹妹" not in merged.characters
    assert merged.characters["林黛玉"].mention_count == 2


def test_merge_arcs_l2_confirm_preserves_chapter_id_with_longest_evidence(monkeypatch):
    monkeypatch.setattr(config, "USE_FAKE_LLM", False)
    a = _arc([Character(name="林妹妹")])
    a.add_relationship(
        Relationship(source="林妹妹", target="贾宝玉", category=RelationCategory.LOVER,
                      evidence="短", confidence=0.5),
        chapter_id="ch0001",
    )
    b = _arc([Character(name="林妹妹"), Character(name="林黛玉")])
    b.add_relationship(
        Relationship(source="林黛玉", target="贾宝玉", category=RelationCategory.LOVER,
                      evidence="更长的一段原文证据内容", confidence=0.6),
        chapter_id="ch0002",
    )
    # Both relationships target 贾宝玉 with the same category, so once 林妹妹
    # is aliased to 林黛玉 by the L2 confirm step, they collide into the same
    # (source, target, category) key inside _apply_merge and must be merged
    # there (not in add_relationship, which never sees this collision).
    merged = merge_arcs([a, b], confirmer=lambda batches: [
        {"names": ["林妹妹", "林黛玉"], "final_name": "林黛玉"}
    ])
    key = (min("林黛玉", "贾宝玉"), max("林黛玉", "贾宝玉"), "爱人")
    rec = merged.relationships[key]
    assert rec.evidence == "更长的一段原文证据内容"
    assert rec.chapter_id == "ch0002"


def test_merge_arcs_preserves_chapter_id_with_longest_evidence():
    a = _arc([Character(name="贾宝玉"), Character(name="林黑玉")])
    a.add_relationship(
        Relationship(source="贾宝玉", target="林黑玉", category="爱人", evidence="短", confidence=0.5),
        chapter_id="ch0001",
    )
    b = _arc([Character(name="贾宝玉"), Character(name="林黑玉")])
    b.add_relationship(
        Relationship(source="贾宝玉", target="林黑玉", category="爱人", evidence="更长的一段原文证据", confidence=0.6),
        chapter_id="ch0002",
    )
    merged = merge_arcs([a, b], confirm=False)
    key = (min("贾宝玉", "林黑玉"), max("贾宝玉", "林黑玉"), "爱人")
    rec = merged.relationships[key]
    assert rec.evidence == "更长的一段原文证据"
    assert rec.chapter_id == "ch0002"


def test_merge_counts_accumulates_on_shared_keys():
    """`_merge_counts` 必须累加而不是覆盖。

    只有当 dst/src 共享同一个 chapter key 时，「累加」和「覆盖」才可区分；
    键不相交的用例两种实现结果相同，抓不到 bug。
    """
    from app.pipeline.merge import _merge_counts

    dst = {"ch0001": 2, "ch0002": 1}
    _merge_counts(dst, {"ch0001": 3, "ch0009": 1})
    assert dst == {"ch0001": 5, "ch0002": 1, "ch0009": 1}

    # 空 src 不改变 dst；空 dst 等于拷贝 src。
    _merge_counts(dst, {})
    assert dst == {"ch0001": 5, "ch0002": 1, "ch0009": 1}
    fresh: dict[str, int] = {}
    _merge_counts(fresh, {"ch0003": 4})
    assert fresh == {"ch0003": 4}


def test_merge_arcs_preserves_chapter_distributions():
    from app.models import Character, Place, Relationship
    from app.pipeline.merge import EntityRegistry, merge_arcs

    def _friend(source: str, target: str) -> Relationship:
        return Relationship(
            source=source,
            target=target,
            category="朋友",
            detail="同门",
            evidence="甲与乙同行",
            confidence=0.9,
        )

    # arc1 在 ch0001 里提及两次 —— 让直方图出现 >1 的计数。
    arc1 = EntityRegistry()
    arc1.add_character(Character(name="甲", aliases=[], role="主角", description="少年"), "ch0001")
    arc1.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0001")
    arc1.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0001")
    arc1.add_place(Place(name="洛阳", description="东都"), "ch0001")
    arc1.add_place(Place(name="洛阳", description=""), "ch0001")
    arc1.add_relationship(_friend("甲", "乙"), "ch0001")
    arc1.add_relationship(_friend("甲", "乙"), "ch0001")

    # arc2 与 arc1 在 ch0001 上**重叠**，另有独占的 ch0009。重叠是关键：
    # 只有共享 key 才能让「覆盖」式实现失败。
    arc2 = EntityRegistry()
    arc2.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0001")
    arc2.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0009")
    arc2.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0009")
    arc2.add_place(Place(name="洛阳", description=""), "ch0001")
    arc2.add_place(Place(name="洛阳", description=""), "ch0009")
    # 反向给出无向关系，确保归一化后仍然只有一条记录。
    arc2.add_relationship(_friend("乙", "甲"), "ch0001")
    arc2.add_relationship(_friend("甲", "乙"), "ch0009")

    merged = merge_arcs([arc1, arc2], confirm=False)

    assert merged.characters["甲"].mentions_by_chapter == {"ch0001": 3, "ch0009": 1}
    assert merged.places["洛阳"].mentions_by_chapter == {"ch0001": 3, "ch0009": 1}
    # 无向关系的 src/tgt 归一化必须把正反两种写法收敛到同一条记录。
    assert len(merged.relationships) == 1
    rec = next(iter(merged.relationships.values()))
    assert rec.chapters == {"ch0001": 3, "ch0009": 1}


def test_apply_merge_folds_chapter_distributions():
    from app.models import Character, Relationship
    from app.pipeline.merge import EntityRegistry, _apply_merge

    def _friend(source: str) -> Relationship:
        return Relationship(
            source=source,
            target="乙",
            category="朋友",
            detail="",
            evidence="",
            confidence=0.5,
        )

    reg = EntityRegistry()
    # 张三 与 张三丰 在 ch0004 上重叠，折叠时才能区分累加与覆盖。
    reg.add_character(Character(name="张三", aliases=[], role="", description=""), "ch0001")
    reg.add_character(Character(name="张三", aliases=[], role="", description=""), "ch0004")
    reg.add_character(Character(name="张三丰", aliases=[], role="", description=""), "ch0004")
    reg.add_character(Character(name="张三丰", aliases=[], role="", description=""), "ch0004")
    reg.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0001")
    reg.add_relationship(_friend("张三"), "ch0001")
    reg.add_relationship(_friend("张三"), "ch0004")
    reg.add_relationship(_friend("张三丰"), "ch0004")
    reg.add_relationship(_friend("张三丰"), "ch0004")

    _apply_merge(reg, "张三丰", "张三")

    assert "张三丰" not in reg.characters
    assert reg.characters["张三"].mentions_by_chapter == {"ch0001": 1, "ch0004": 3}
    # 两条关系记录折叠成一条（键冲突分支）。
    assert len(reg.relationships) == 1
    rec = next(iter(reg.relationships.values()))
    assert rec.chapters == {"ch0001": 1, "ch0004": 3}
