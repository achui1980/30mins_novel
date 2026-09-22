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


def test_edges_have_empty_source_location_placeholder():
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉"))
    reg.add_character(Character(name="林黑玉"))
    reg.add_relationship(Relationship(source="贾宝玉", target="林黑玉", category="爱人", confidence=0.7))
    extraction, _name_to_id, _id_to_name = build_extraction_json(reg)
    edges = extraction["edges"] if "edges" in extraction else extraction["links"]
    assert edges, "expected at least one edge"
    for edge in edges:
        assert edge["source_location"] == ""


def test_nodes_and_edges_carry_chapter_distribution():
    from app.models import Character, Place, Relationship
    from app.pipeline.graph import build_extraction_json
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    reg.add_character(Character(name="甲", aliases=[], role="主角", description="少年"), "ch0010")
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0002")
    reg.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0002")
    reg.add_place(Place(name="洛阳", description="东都"), "ch0010")
    reg.add_relationship(
        Relationship(
            source="甲",
            target="乙",
            category="朋友",
            detail="同门",
            evidence="甲与乙同行",
            confidence=0.9,
        ),
        "ch0010",
    )

    # order 故意与字典序**相反**：ch0010 是第 1 章，ch0002 是第 2 章。
    # 这样「按 order 取最小」和「按 id 字典序取最小」给出不同答案，
    # min(known, key=order.__getitem__) 退化成 min(known) 时本测试必须失败。
    order = {"ch0010": 1, "ch0002": 2}
    extraction, _, _ = build_extraction_json(reg, chapter_order=order)

    by_label = {n["label"]: n for n in extraction["nodes"]}
    assert by_label["甲"]["mentions_by_chapter"] == {"ch0010": 1, "ch0002": 1}
    # first_chapter 以 order 为准，不是字典序，也不是插入顺序。
    # 字典序会答 ch0002（更小的字符串），order 答 ch0010（order=1）。
    assert by_label["甲"]["first_chapter"] == "ch0010"
    # 同一张 order 表下，直方图不同的人物答案也不同（乙 只出现在 ch0002）。
    assert by_label["乙"]["first_chapter"] == "ch0002"
    assert by_label["洛阳"]["first_chapter"] == "ch0010"
    assert "mentions_by_chapter" not in by_label["洛阳"]

    edge = extraction["edges"][0]
    assert edge["chapters"] == {"ch0010": 1}
    assert edge["first_chapter"] == "ch0010"


def test_build_extraction_json_without_chapter_order_still_works():
    from app.models import Character
    from app.pipeline.graph import build_extraction_json
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    # ch0005 先插入、ch0002 后插入，于是「插入顺序最早」= ch0005，而
    # 「字典序最小」= ch0002，两者不同：断言 ch0002 才能真正钉住退化语义
    # （max / next(iter()) / 插入顺序 都会答 ch0005）。
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0005")
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0002")

    # 不传 chapter_order：调用形态必须照旧可用，两个字段都要在。
    extraction, _, _ = build_extraction_json(reg)
    node = extraction["nodes"][0]
    assert node["first_chapter"] == "ch0002"
    assert node["mentions_by_chapter"] == {"ch0005": 1, "ch0002": 1}


def test_stub_nodes_get_empty_timeline_fields():
    from app.models import Relationship
    from app.pipeline.graph import build_extraction_json
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    reg.add_relationship(
        Relationship(
            source="甲",
            target="乙",
            category="朋友",
            detail="",
            evidence="",
            confidence=0.5,
        ),
        "ch0001",
    )

    extraction, _, _ = build_extraction_json(reg, chapter_order={"ch0001": 1})
    for node in extraction["nodes"]:
        assert node["first_chapter"] == ""
        assert node["mentions_by_chapter"] == {}


def test_first_chapter_ignores_chapter_ids_absent_from_order_table():
    """order 表里没有的章 id 必须被**过滤掉**，而不是当成 order 0。

    把 min(known, key=order.__getitem__) 换成
    min(counts, key=lambda c: order.get(c, 0)) 时本测试必须失败：
    零填充会让缺席的 chZZ 拿到 order 0 从而胜出，过滤则答 ch0009。
    节点和边两条调用点都覆盖（边那条同时钉住 chapter_order 确实透传到了边）。
    """
    from app.models import Character, Relationship
    from app.pipeline.graph import build_extraction_json
    from app.pipeline.merge import EntityRegistry

    reg = EntityRegistry()
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "chZZ")
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0009")
    reg.add_character(Character(name="乙", aliases=[], role="", description=""), "ch0009")
    for chap in ("chZZ", "ch0009"):
        reg.add_relationship(
            Relationship(
                source="甲",
                target="乙",
                category="朋友",
                detail="同门",
                evidence="甲与乙同行",
                confidence=0.9,
            ),
            chap,
        )

    # chZZ 故意缺席；ch0009 的 order 故意取一个较大的数（5），
    # 这样零填充（chZZ->0）和过滤（只剩 ch0009）的答案一定不同。
    order = {"ch0009": 5}
    extraction, _, _ = build_extraction_json(reg, chapter_order=order)

    by_label = {n["label"]: n for n in extraction["nodes"]}
    assert by_label["甲"]["mentions_by_chapter"] == {"chZZ": 1, "ch0009": 1}
    assert by_label["甲"]["first_chapter"] == "ch0009"

    edge = extraction["edges"][0]
    assert edge["chapters"] == {"chZZ": 1, "ch0009": 1}
    assert edge["first_chapter"] == "ch0009"


def test_relationship_only_character_with_empty_histogram_yields_blank_first_chapter():
    """merge_arcs（merge.py:465）会为「只在关系里出现过」的人物补一条
    CharacterRecord，其 mentions_by_chapter 是空的。这条记录走的是
    registry.characters -> 人物节点分支（graph.py:115-116），
    和字段写死成 "" / {} 的关系补桩分支（graph.py:146-158）不是同一条路径。

    所以空直方图必须在**人物节点分支**上也被覆盖：删掉 graph.py:49-50 的空值
    保护后，min({}) 会抛 ValueError，本测试必须失败。
    """
    from app.models import Character
    from app.pipeline.graph import build_extraction_json
    from app.pipeline.merge import CharacterRecord, EntityRegistry

    reg = EntityRegistry()
    reg.add_character(Character(name="甲", aliases=[], role="", description=""), "ch0001")
    # 与 merge.py:465 完全相同的构造形态（mentions_by_chapter 默认空 dict）。
    reg.characters["丙"] = CharacterRecord(canonical="丙", mention_count=1)

    # 给一张可用的 order 表：空直方图不能因为「有 order 表」就走进 min({})。
    extraction, _, _ = build_extraction_json(reg, chapter_order={"ch0001": 1})

    by_label = {n["label"]: n for n in extraction["nodes"]}
    丙 = by_label["丙"]
    # 证明它确实是人物节点分支产出的，而不是关系补桩：补桩节点没有
    # source_location / role / aliases 这几个键。
    assert "source_location" in 丙
    assert 丙["aliases"] == []
    assert 丙["node_type"] == "character"
    assert 丙["mention_count"] == 1
    # 空直方图 -> 安全值，且不抛异常。
    assert 丙["mentions_by_chapter"] == {}
    assert 丙["first_chapter"] == ""
    # 正常人物不受影响。
    assert by_label["甲"]["first_chapter"] == "ch0001"


# -- patch_graph_timeline ---------------------------------------------------------


def test_patch_graph_timeline_injects_top_level_keys(tmp_path):
    import json

    from app.pipeline.graph import patch_graph_timeline

    path = tmp_path / "graph.json"
    # 和 graphify to_json 真正写出的顶层键形状一致：built_at_commit / directed /
    # graph / hyperedges / links / multigraph / nodes（注意是 links，不是 edges）。
    # 补丁必须是纯增量，所以少写回、改写、或整体替换掉任何一个已有顶层键都必须
    # 让本测试失败。
    fixture = {
        "built_at_commit": "3c60c00",
        "directed": False,
        "graph": {"communities": {"0": ["n1"]}, "community_labels": {"0": "甲相关情节线"}},
        "hyperedges": [],
        "links": [{"source": "zeta", "target": "alpha", "category": "朋友"}],
        "multigraph": False,
        "nodes": [{"id": "n1"}],
    }
    path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    chapters = [{"id": "ch0001", "title": "第一章", "order": 1}]
    # steps 已由 evolve.prefilter_candidates 按章序升序排好，Tasks 12/17 直接按这个
    # 顺序取下标，所以本函数只能原样搬运。故意给两步、且顺序既非字母序也非章号序，
    # 这样「写死成 []」和「重排/反转」都必须让本测试失败。
    steps = [
        {"chapter_id": "ch0009", "category": "敌人", "evidence": "反目"},
        {"chapter_id": "ch0002", "category": "朋友", "evidence": "同行"},
    ]
    transitions = [{"pair": ["甲", "乙"], "steps": steps, "confirmed": True}]

    # 名字→id 故意映射成**非**排序序（zeta 排在 alpha 前）：pair 的顺序来自
    # merge.py:197-198 的无向规范序，本函数不得重排，sorted() 必须失败。
    patch_graph_timeline(path, chapters, transitions, {"甲": "zeta", "乙": "alpha"})

    data = json.loads(path.read_text(encoding="utf-8"))
    # 整体等值：fixture 的每个顶层键原值存活，只多出 chapters / transitions 两个。
    assert data == {
        **fixture,
        "chapters": chapters,
        "transitions": [{"pair": ["zeta", "alpha"], "steps": steps, "confirmed": True}],
    }
    # 逐项断言保留（整体比较已覆盖，留着让失败信息更聚焦）。
    assert data["chapters"] == chapters
    assert data["transitions"][0]["pair"] == ["zeta", "alpha"]
    assert data["transitions"][0]["steps"] == steps
    assert data["transitions"][0]["confirmed"] is True
    assert data["nodes"] == [{"id": "n1"}]


def test_patch_graph_timeline_drops_transitions_with_unknown_names(tmp_path):
    import json

    from app.pipeline.graph import patch_graph_timeline

    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    transitions = [{"pair": ["甲", "丙"], "steps": [], "confirmed": False}]

    patch_graph_timeline(path, [], transitions, {"甲": "jia"})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["transitions"] == []
    # chapters 为空也必须写出顶层键：它是前端判断「本作品有没有时间轴数据」的
    # **唯一**信号，`if chapters:` 那样的省略会静默隐藏整个功能。
    assert data["chapters"] == []

    # pair 长度不是 2 的条目同样静默丢弃：删掉长度保护后，1 元 pair 会
    # IndexError（函数契约是永不抛异常），3 元 pair 会被截成一条假演变。
    # 同时放一条名字全部可解析、confirmed=False 的**存活**条目，钉住
    # bool(item.get("confirmed")) 的取值 —— 写死成 True 必须让本测试失败。
    malformed = [
        {"pair": ["甲"], "steps": [], "confirmed": True},
        {"pair": ["甲", "乙", "丁"], "steps": [], "confirmed": True},
        {"pair": ["甲", "乙"], "steps": [], "confirmed": False},
    ]
    patch_graph_timeline(path, [], malformed, {"甲": "jia", "乙": "yi", "丁": "ding"})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["transitions"] == [{"pair": ["jia", "yi"], "steps": [], "confirmed": False}]


def test_patch_graph_timeline_never_raises_on_bad_file(tmp_path):
    import json

    from app.pipeline.graph import patch_graph_timeline

    missing = tmp_path / "nope.json"
    patch_graph_timeline(missing, [], [], {})
    assert not missing.exists()

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    patch_graph_timeline(broken, [{"id": "ch0001", "title": "x", "order": 1}], [], {})
    assert broken.read_text(encoding="utf-8") == "{not json"

    # 顶层不是 dict：删掉 isinstance(data, dict) 保护后会变成
    # TypeError: list indices must be integers，把静默 no-op 变成抛异常。
    array_top = tmp_path / "array.json"
    array_top.write_text("[1, 2, 3]", encoding="utf-8")
    patch_graph_timeline(array_top, [{"id": "ch0001", "title": "x", "order": 1}], [], {})
    assert array_top.read_text(encoding="utf-8") == "[1, 2, 3]"

    # 畸形入参同样不能抛。Task 9 在 building 阶段调用本函数，永不抛异常是硬约束；
    # detect_transitions 今天只产出规范 dict，所以这些分支是纯防御。
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")

    # 条目不是 dict：非 dict 是真值，`(item or {}).get` 保护不住，会 AttributeError。
    patch_graph_timeline(ok, [], ["x", 123, ["a", "b"], None], {"甲": "jia"})
    assert json.loads(ok.read_text(encoding="utf-8"))["transitions"] == []

    # pair 元素不是字符串：list 不可 hash，name_to_id.get 会 TypeError。
    # pair 本身不是列表（整数 / 恰好两字的字符串）也不能穿过去。
    patch_graph_timeline(
        ok,
        [],
        [
            {"pair": [["甲"], "乙"]},
            {"pair": {"甲", "乙"}},
            {"pair": 2},
            {"pair": "甲乙"},
        ],
        {"甲": "jia", "乙": "yi"},
    )
    assert json.loads(ok.read_text(encoding="utf-8"))["transitions"] == []

    # name_to_id 为 None：.get 会 AttributeError。
    patch_graph_timeline(ok, [], [{"pair": ["甲", "乙"], "steps": [], "confirmed": True}], None)
    assert json.loads(ok.read_text(encoding="utf-8"))["transitions"] == []
