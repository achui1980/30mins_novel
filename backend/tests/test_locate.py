import json

from app.pipeline.locate import (
    locate_paragraph,
    patch_graph_edge_locations,
    resolve_source_location,
    split_paragraphs,
)
from app.pipeline.merge import EntityRegistry, RelationRecord


def test_split_paragraphs_blank_line_delimited():
    text = "第一段第一句。第一段第二句。\n\n第二段内容。\n\n第三段内容。"
    assert split_paragraphs(text) == ["第一段第一句。第一段第二句。", "第二段内容。", "第三段内容。"]


def test_split_paragraphs_falls_back_to_single_newline():
    text = "第一行内容。\n第二行内容。\n第三行内容。"
    assert split_paragraphs(text) == ["第一行内容。", "第二行内容。", "第三行内容。"]


def test_split_paragraphs_falls_back_to_whole_chapter():
    text = "没有任何换行的一整段文字内容。"
    assert split_paragraphs(text) == ["没有任何换行的一整段文字内容。"]


def test_split_paragraphs_empty_text():
    assert split_paragraphs("") == []
    assert split_paragraphs("   \n\n  ") == []


def test_locate_paragraph_exact_substring_match():
    paragraphs = ["贾宝玉在园中读书。", "林黑玉忽然到来，两人相谈甚欢。", "夜幕降临，众人散去。"]
    assert locate_paragraph(paragraphs, "林黑玉忽然到来") == 1


def test_locate_paragraph_fuzzy_near_match():
    paragraphs = ["贾宝玉在园中读书写字。", "林黑玉忽然到来，两人相谈甚欢，情投意合。", "夜幕降临，众人散去。"]
    # Slightly reworded quote (near, not exact) should still resolve via difflib.
    assert locate_paragraph(paragraphs, "林黑玉忽然到来两人相谈甚欢情投意合") == 1


def test_locate_paragraph_below_threshold_returns_none():
    paragraphs = ["贾宝玉在园中读书。", "林黑玉忽然到来。"]
    assert locate_paragraph(paragraphs, "完全不相关的一句话内容") is None


def test_locate_paragraph_empty_quote_or_paragraphs_returns_none():
    assert locate_paragraph(["有内容的段落。"], "") is None
    assert locate_paragraph([], "任意引用") is None


def test_resolve_source_location_with_matched_paragraph():
    paragraphs_by_chapter = {"ch0001": ["贾宝玉在园中读书。", "林黑玉忽然到来。"]}
    loc = resolve_source_location("ch0001", "林黑玉忽然到来", paragraphs_by_chapter)
    assert loc == "ch0001#p1"


def test_resolve_source_location_with_unmatched_paragraph_falls_back_to_chapter():
    paragraphs_by_chapter = {"ch0001": ["贾宝玉在园中读书。"]}
    loc = resolve_source_location("ch0001", "完全不相关的内容", paragraphs_by_chapter)
    assert loc == "ch0001"


def test_resolve_source_location_with_no_chapter_returns_empty_string():
    assert resolve_source_location("", "任意引用", {}) == ""
    assert resolve_source_location(None, "任意引用", {}) == ""


def test_patch_graph_edge_locations_happy_path(tmp_path):
    graph_json_path = tmp_path / "graph.json"
    graph_json_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}, {"id": "n4"}],
                "links": [
                    {"source": "n1", "target": "n2", "category": "爱人"},
                    {"source": "n3", "target": "n4", "category": "朋友"},
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = EntityRegistry()
    rec = RelationRecord(
        source="贾宝玉", target="林黑玉", category="爱人", evidence="林黑玉忽然到来",
        chapter_id="ch0001",
    )
    registry.relationships[("贾宝玉", "林黑玉", "爱人")] = rec

    label_to_id = {"贾宝玉": "n1", "林黑玉": "n2"}
    paragraphs_by_chapter = {
        "ch0001": ["贾宝玉在园中读书。", "林黑玉忽然到来，两人相谈甚欢。"]
    }

    patch_graph_edge_locations(graph_json_path, registry, label_to_id, paragraphs_by_chapter)

    data = json.loads(graph_json_path.read_text(encoding="utf-8"))
    edges = {(e["source"], e["target"]): e for e in data["links"]}
    assert edges[("n1", "n2")]["source_location"] == "ch0001#p1"
    assert "source_location" not in edges[("n3", "n4")]


def test_patch_graph_edge_locations_default_chapter_id_leaves_location_empty(tmp_path):
    graph_json_path = tmp_path / "graph.json"
    graph_json_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "n1"}, {"id": "n2"}],
                "links": [
                    {"source": "n1", "target": "n2", "category": "爱人", "source_location": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = EntityRegistry()
    # RelationRecord.chapter_id defaults to "" when not passed. That's a
    # falsy/unknown chapter, so resolve_source_location() legitimately
    # returns "" (see test_resolve_source_location_with_no_chapter_returns_empty_string)
    # and patch_graph_edge_locations leaves the edge's source_location
    # untouched. This is normal behavior, not an exception being caught.
    rec = RelationRecord(
        source="贾宝玉", target="林黑玉", category="爱人", evidence="林黑玉忽然到来"
    )
    registry.relationships[("贾宝玉", "林黑玉", "爱人")] = rec

    label_to_id = {"贾宝玉": "n1", "林黑玉": "n2"}
    paragraphs_by_chapter = {
        "ch0001": ["贾宝玉在园中读书。", "林黑玉忽然到来，两人相谈甚欢。"]
    }

    patch_graph_edge_locations(graph_json_path, registry, label_to_id, paragraphs_by_chapter)

    data = json.loads(graph_json_path.read_text(encoding="utf-8"))
    edge = next(e for e in data["links"] if e["source"] == "n1" and e["target"] == "n2")
    assert edge["source_location"] == ""


def test_patch_graph_edge_locations_relation_missing_chapter_id_attr_is_noop(tmp_path):
    """Genuine AttributeError-resilience guard.

    A real ``RelationRecord`` always has ``chapter_id`` (default ``""``), so
    it can no longer trigger the ``except (AttributeError, TypeError)`` guard
    in ``patch_graph_edge_locations``. This test exercises that guard
    directly with a duck-typed stand-in object that lacks ``.chapter_id``
    entirely (e.g. a malformed/legacy registry entry), confirming the
    function still degrades gracefully instead of raising.
    """
    graph_json_path = tmp_path / "graph.json"
    graph_json_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "n1"}, {"id": "n2"}],
                "links": [
                    {"source": "n1", "target": "n2", "category": "爱人", "source_location": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    class _RelationLikeWithoutChapterId:
        def __init__(self, source, target, category, evidence):
            self.source = source
            self.target = target
            self.category = category
            self.evidence = evidence
            # deliberately no chapter_id attribute

    registry = EntityRegistry()
    rec = _RelationLikeWithoutChapterId(
        source="贾宝玉", target="林黑玉", category="爱人", evidence="林黑玉忽然到来"
    )
    registry.relationships[("贾宝玉", "林黑玉", "爱人")] = rec

    label_to_id = {"贾宝玉": "n1", "林黑玉": "n2"}
    paragraphs_by_chapter = {
        "ch0001": ["贾宝玉在园中读书。", "林黑玉忽然到来，两人相谈甚欢。"]
    }

    # Must not raise AttributeError; the edge's source_location stays untouched.
    patch_graph_edge_locations(graph_json_path, registry, label_to_id, paragraphs_by_chapter)

    data = json.loads(graph_json_path.read_text(encoding="utf-8"))
    edge = next(e for e in data["links"] if e["source"] == "n1" and e["target"] == "n2")
    assert edge["source_location"] == ""


def test_patch_graph_edge_locations_unhashable_category_never_raises(tmp_path):
    graph_json_path = tmp_path / "graph.json"
    graph_json_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "n1"}, {"id": "n2"}],
                "links": [
                    {"source": "n1", "target": "n2", "category": ["not", "hashable"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = EntityRegistry()
    label_to_id: dict[str, str] = {}
    paragraphs_by_chapter: dict[str, list[str]] = {}

    # Must not raise TypeError: unhashable type when hashing the lookup key.
    patch_graph_edge_locations(graph_json_path, registry, label_to_id, paragraphs_by_chapter)


def test_patch_graph_edge_locations_malformed_input_never_raises(tmp_path):
    registry = EntityRegistry()

    # Missing file: no-op, no exception, no file created.
    missing_path = tmp_path / "missing.json"
    patch_graph_edge_locations(missing_path, registry, {}, {})
    assert not missing_path.exists()

    # Invalid JSON content: no-op, file left untouched.
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not valid json", encoding="utf-8")
    patch_graph_edge_locations(invalid_path, registry, {}, {})
    assert invalid_path.read_text(encoding="utf-8") == "{not valid json"

    # Valid JSON but non-dict top level: no-op, file left untouched.
    non_dict_path = tmp_path / "non_dict.json"
    non_dict_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    patch_graph_edge_locations(non_dict_path, registry, {}, {})
    assert json.loads(non_dict_path.read_text(encoding="utf-8")) == [1, 2, 3]
