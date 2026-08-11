"""Tests for the graph-building layer (design §5.3, §7 graph output)."""

import networkx as nx

from app.models import Character, Place, RelationCategory, Relationship
from app.pipeline.graph import (
    _fallback_god_nodes,
    _heuristic_labels,
    _slug,
    build_extraction_json,
)
from app.pipeline.merge import EntityRegistry


# -- _slug ------------------------------------------------------------------------


def test_slug_cjk_name_falls_back_to_deterministic_id():
    # CJK names slugify to empty ([^a-z0-9_]+ strips everything), so _slug must
    # fall back to a deterministic n{salt} id (see AGENTS.md gotcha).
    assert _slug("贾宝玉", 3) == "n3"
    assert _slug("林黛玉", 3) == "n3"  # same salt -> same fallback id (deterministic)
    assert _slug("贾宝玉", 7) == "n7"


def test_slug_ascii_name_produces_lowercase_snake_case_id():
    assert _slug("John Doe", 1) == "john_doe"
    assert _slug("Mary-Jane O'Brien", 1) == "mary_jane_o_brien"


def test_slug_strips_leading_and_trailing_separators():
    assert _slug("  ***Bob***  ", 9) == "bob"


# -- build_extraction_json --------------------------------------------------------


def _registry_with_characters_place_and_relationship() -> EntityRegistry:
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉", role="主角"))
    reg.add_character(Character(name="林黛玉", role="女主角"))
    reg.add_place(Place(name="大观园", description="故事发生地"))
    reg.add_relationship(
        Relationship(
            source="贾宝玉", target="林黛玉", category=RelationCategory.LOVER, confidence=0.9
        )
    )
    return reg


def test_build_extraction_json_basic_structure():
    reg = _registry_with_characters_place_and_relationship()

    extraction, name_to_id, id_to_name = build_extraction_json(reg)

    assert set(extraction.keys()) == {
        "nodes",
        "edges",
        "hyperedges",
        "input_tokens",
        "output_tokens",
    }
    assert extraction["hyperedges"] == []
    # 2 characters + 1 place = 3 nodes; 1 relationship = 1 edge.
    assert len(extraction["nodes"]) == 3
    assert len(extraction["edges"]) == 1

    node_types = {n["label"]: n["node_type"] for n in extraction["nodes"]}
    assert node_types == {"贾宝玉": "character", "林黛玉": "character", "大观园": "place"}

    # name_to_id / id_to_name must be exact inverses.
    assert set(name_to_id) == {"贾宝玉", "林黛玉", "大观园"}
    for name, nid in name_to_id.items():
        assert id_to_name[nid] == name

    edge = extraction["edges"][0]
    # LOVER is an undirected category; EntityRegistry.add_relationship already
    # normalizes (src, tgt) ordering for undirected categories (see merge.py),
    # so only assert the edge connects the right two nodes, not which is which.
    assert {edge["source"], edge["target"]} == {name_to_id["贾宝玉"], name_to_id["林黛玉"]}
    assert edge["category"] == "爱人"
    assert edge["relation"] == "爱人"
    assert edge["directed"] is False  # LOVER is not in DIRECTED_CATEGORIES
    assert edge["confidence"] == 0.9


def test_build_extraction_json_directed_category_sets_directed_flag():
    reg = EntityRegistry()
    reg.add_character(Character(name="师父"))
    reg.add_character(Character(name="徒弟"))
    reg.add_relationship(
        Relationship(source="师父", target="徒弟", category=RelationCategory.MASTER_APPRENTICE)
    )

    extraction, _, _ = build_extraction_json(reg)

    edge = extraction["edges"][0]
    assert edge["directed"] is True


def test_build_extraction_json_creates_stub_nodes_for_relationship_only_names():
    """merge.EntityRegistry.add_relationship does not require the endpoints to
    have gone through add_character/add_place first. build_extraction_json must
    still materialize a node for each so the edge has valid endpoints."""
    reg = EntityRegistry()
    reg.add_relationship(
        Relationship(source="路人甲", target="路人乙", category=RelationCategory.OTHER)
    )

    extraction, name_to_id, id_to_name = build_extraction_json(reg)

    labels = {n["label"] for n in extraction["nodes"]}
    assert labels == {"路人甲", "路人乙"}
    assert all(n["node_type"] == "character" for n in extraction["nodes"])
    edge = extraction["edges"][0]
    # OTHER is an undirected category, so source/target order may have been
    # normalized by EntityRegistry.add_relationship; just check connectivity.
    assert {edge["source"], edge["target"]} == {name_to_id["路人甲"], name_to_id["路人乙"]}
    assert id_to_name[name_to_id["路人甲"]] == "路人甲"


def test_build_extraction_json_empty_registry_produces_no_nodes_or_edges():
    extraction, name_to_id, id_to_name = build_extraction_json(EntityRegistry())

    assert extraction["nodes"] == []
    assert extraction["edges"] == []
    assert name_to_id == {}
    assert id_to_name == {}


# -- _fallback_god_nodes -----------------------------------------------------------


def test_fallback_god_nodes_ranks_by_degree_and_excludes_places():
    g = nx.Graph()
    g.add_node("a", label="甲", node_type="character", mention_count=1)
    g.add_node("b", label="乙", node_type="character", mention_count=1)
    g.add_node("c", label="丙", node_type="character", mention_count=1)
    g.add_node("d", label="丁", node_type="character", mention_count=1)
    g.add_node("place1", label="某地", node_type="place", mention_count=99)
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("b", "d")
    g.add_edge("a", "place1")

    id_to_name = {"a": "甲", "b": "乙", "c": "丙", "d": "丁", "place1": "某地"}
    gods = _fallback_god_nodes(g, id_to_name)

    ids = [entry["id"] for entry in gods]
    assert "place1" not in ids  # places are excluded regardless of degree
    assert ids[0] == "b"  # highest degree (3) among character nodes
    assert gods[0]["degree"] == 3


def test_fallback_god_nodes_limits_to_top_ten():
    g = nx.Graph()
    for i in range(15):
        g.add_node(f"n{i}", label=f"人物{i}", node_type="character", mention_count=i)
        if i > 0:
            g.add_edge(f"n{i}", "n0")

    gods = _fallback_god_nodes(g, {f"n{i}": f"人物{i}" for i in range(15)})

    assert len(gods) == 10


def test_fallback_god_nodes_empty_graph_returns_empty_list():
    assert _fallback_god_nodes(nx.Graph(), {}) == []


# -- _heuristic_labels --------------------------------------------------------------


def test_heuristic_labels_names_community_after_most_mentioned_character():
    g = nx.Graph()
    g.add_node("a", label="甲", node_type="character", mention_count=2)
    g.add_node("b", label="乙", node_type="character", mention_count=9)
    g.add_node("place1", label="某地", node_type="place", mention_count=50)
    communities = {0: ["a", "b"], 1: ["place1"]}

    labels = _heuristic_labels(communities, g, {}, EntityRegistry())

    assert labels[0] == "乙相关情节线"
    assert labels[1] == "情节线 1"


def test_heuristic_labels_empty_communities_returns_empty_dict():
    assert _heuristic_labels({}, nx.Graph(), {}, EntityRegistry()) == {}
