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
