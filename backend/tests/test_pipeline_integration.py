"""Mock end-to-end integration test for the ingestion pipeline.

Runs the whole pipeline with the fake (offline) LLM backend against a small
synthetic novel and asserts the produced graph.json + summary.json are valid.
"""

import asyncio
import json

import pytest

from app import config, store
from app.models import WorkPackage
from app.pipeline.orchestrator import run_pipeline


SAMPLE_NOVEL = """第一章 相遇

贾宝玉走进大观园，遇见了林黛玉。贾宝玉对林黛玉一见倾心，林黛玉也对贾宝玉心生好感。
薛宝钗此时也在园中，薛宝钗与贾宝玉是表亲。贾宝玉、林黛玉、薛宝钗三人常常一起吟诗。

第二章 冲突

贾宝玉与薛蟠发生了争执。薛蟠是薛宝钗的哥哥，薛蟠性情暴躁。
林黛玉劝阻贾宝玉，贾宝玉听从了林黛玉的话。

第三章 离别

林黛玉病重，贾宝玉日夜守候。薛宝钗前来探望林黛玉。
最终林黛玉离世，贾宝玉悲痛欲绝，薛宝钗默默陪伴在贾宝玉身边。
"""


@pytest.fixture()
def temp_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "works")
    config.ensure_data_root()
    monkeypatch.setattr(config, "USE_FAKE_LLM", True)
    return config.DATA_ROOT


def test_pipeline_end_to_end(temp_data_root):
    work_id = store.new_work_id()
    raw_path = store.save_upload(work_id, "test.txt", SAMPLE_NOVEL.encode("utf-8"))

    asyncio.run(
        run_pipeline(
            work_id=work_id,
            raw_path=raw_path,
            original_filename="test.txt",
            title="红楼一梦",
            granularity="quick",
        )
    )

    # Status should have reached 'done'.
    status = store.get_status(work_id)
    assert status is not None, "status.json missing"
    assert status.phase == "done", f"pipeline did not finish: {status.phase} / {status.error}"

    # graph.json exists and is well-formed.
    graph_path = store.graph_json_path(work_id)
    assert graph_path.exists()
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert "nodes" in graph
    assert graph["nodes"], "no nodes produced"
    # Edges may be keyed as 'edges' or 'links' depending on networkx version.
    edges = graph.get("edges", graph.get("links", []))
    assert isinstance(edges, list)
    # Custom fields preserved on nodes.
    node = graph["nodes"][0]
    assert "node_type" in node
    assert "mention_count" in node

    # events.json must be persisted right after extraction (design §4.3) so
    # timeline data survives even if a later phase (summarize) fails.
    events_path = config.work_dir(work_id) / "events.json"
    assert events_path.exists(), "events.json was not persisted"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    assert isinstance(events, list)
    assert events, "no events persisted"
    assert all({"summary", "chapter", "participants", "order_hint"} <= set(e.keys()) for e in events)

    events_path = config.work_dir(work_id) / "events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    for e in events:
        assert {"summary", "chapter", "participants", "order_hint", "evidence", "paragraph_index"} <= set(e.keys())
    assert any(e["paragraph_index"] is not None for e in events), "expected at least one located event"

    graph_data = json.loads(store.graph_json_path(work_id).read_text(encoding="utf-8"))
    edge_list = graph_data.get("links") if graph_data.get("links") is not None else graph_data.get("edges", [])
    assert any(edge.get("source_location") for edge in edge_list), "expected at least one located edge"

    # summary.json -> valid WorkPackage.
    pkg = store.get_package(work_id)
    assert pkg is not None
    assert isinstance(pkg, WorkPackage)
    assert pkg.work_id == work_id
    assert pkg.title == "红楼一梦"
    assert pkg.layered_summary.one_liner
    assert pkg.layered_summary.arcs, "no arcs (communities) produced"
    assert pkg.setting_cards, "no setting cards produced"
    assert pkg.main_characters, "no main characters produced"

    # Suggested questions must be real, plot-grounded questions (design §4.2) —
    # not graphify's code-review-oriented output, and not empty/decorative.
    assert pkg.suggested_questions, "no suggested questions produced"
    joined_questions = " ".join(q.question for q in pkg.suggested_questions)
    for bad_kw in ("模块", "拆分", "重构", "split", "module", "refactor"):
        assert bad_kw not in joined_questions


def test_pipeline_emits_timeline_fields(temp_data_root, monkeypatch):
    """离线跑完整管道，钉住 building 阶段的时间轴接线（design §4.1）。

    这里用 spy 在**调用处**钉住几处接线，因为它们对 graph.json 没有可观测差异，
    或其行为本身已在别处的单测里钉过：
    - `run_graphify(chapter_order=...)`：`build_extraction_json` 的章序行为已由
      `tests/test_graph.py` 钉住（ch0010 胜 ch0002），编排这一层剩下的义务只是
      「kwarg 确实传下去了」，那是个调用形状事实。
    - `warn_cb=on_warn`：`evolve.py` 降级时只通过这个回调把警告送进
      `status.warnings`，漏传的后果是警告静默消失，产物完全一样。
    - `patch_graph_timeline` 必须跑在 `patch_graph_edge_locations` **之后**：两者都是
      整字典读-改-写，互相保留对方的键，换序后产物同样一字不变。
    """
    from app.pipeline import orchestrator

    # 这条是**载荷性**的，不是装饰：EVOLVE_ENABLED 为假时 real_detect 会在
    # evolve.py:191-192 直接 return []，下面 spy 里对 warn_cb / 真函数返回值的断言
    # 就再也走不到真正的判定路径。config 在调用时读模块属性，改 env 无效，只能
    # monkeypatch 模块属性。
    # （USE_FAKE_LLM 不在这里重复钉 —— temp_data_root fixture 已经钉过了。）
    monkeypatch.setattr(config, "EVOLVE_ENABLED", True)

    calls: list[str] = []
    seen: dict = {}

    real_detect = orchestrator.detect_transitions

    def spy_detect(registry, chapters, **kwargs):
        calls.append("detect_transitions")
        seen["chapters_meta"] = [dict(c) for c in chapters]
        # 降级警告必须能抵达 status.warnings：evolve.py:220-221 只经由 warn_cb
        # 上报「关系演变判定失败」，漏传这个 kwarg 后警告静默消失而产物不变。
        assert kwargs.get("warn_cb") is not None, kwargs
        # 真函数也跑一遍：确认编排传进来的参数形状它确实吃得下（永不抛异常）。
        assert isinstance(real_detect(registry, chapters, **kwargs), list)
        names = sorted(registry.characters)
        assert len(names) >= 2, names
        pair = names[:2]
        seen["pair"] = pair
        cids = [c["id"] for c in chapters]
        return [
            {
                "pair": pair,
                "steps": [
                    {"chapter_id": cids[0], "category": "朋友", "evidence": "结为好友"},
                    {"chapter_id": cids[-1], "category": "敌人", "evidence": "拔剑相向"},
                ],
                "confirmed": True,
            }
        ]

    monkeypatch.setattr(orchestrator, "detect_transitions", spy_detect)

    real_run_graphify = orchestrator.run_graphify

    def spy_run_graphify(*args, **kwargs):
        calls.append("run_graphify")
        seen["chapter_order"] = kwargs.get("chapter_order")
        return real_run_graphify(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "run_graphify", spy_run_graphify)

    real_patch_locations = orchestrator.patch_graph_edge_locations

    def spy_patch_locations(*args, **kwargs):
        calls.append("patch_graph_edge_locations")
        return real_patch_locations(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "patch_graph_edge_locations", spy_patch_locations)

    real_patch_timeline = orchestrator.patch_graph_timeline

    def spy_patch_timeline(*args, **kwargs):
        calls.append("patch_graph_timeline")
        seen["timeline_args"] = (args, kwargs)
        return real_patch_timeline(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "patch_graph_timeline", spy_patch_timeline)

    work_id = store.new_work_id()
    raw_path = store.save_upload(work_id, "test.txt", SAMPLE_NOVEL.encode("utf-8"))
    asyncio.run(
        run_pipeline(
            work_id=work_id,
            raw_path=raw_path,
            original_filename="test.txt",
            title="红楼一梦",
            granularity="quick",
        )
    )

    status = store.get_status(work_id)
    assert status is not None and status.phase == "done", status

    # --- 调用处接线 -------------------------------------------------------
    # 演变判定跑在既有 building 阶段内：run_graphify 之前，且不新增 Phase。
    assert calls == [
        "detect_transitions",
        "run_graphify",
        "patch_graph_edge_locations",
        "patch_graph_timeline",
    ], calls

    chapters_meta = seen["chapters_meta"]
    assert len(chapters_meta) >= 3, chapters_meta
    assert all(set(c) == {"id", "title", "order"} for c in chapters_meta), chapters_meta
    # order 必须**每章都给**且从 1 连续递增：漏给会让 evolve.chapter_order_map
    # 退化成枚举下标，与真 order 共用一个数轴而无从对账，可能把章序整体反转。
    assert [c["order"] for c in chapters_meta] == list(range(1, len(chapters_meta) + 1))

    # run_graphify 必须拿到 order 表（章序是先后比较的唯一依据，绝不比 id 字符串）。
    assert seen["chapter_order"] == {c["id"]: c["order"] for c in chapters_meta}

    # patch_graph_timeline 必须收到 name->id 方向的映射（label_to_id），不是反向。
    timeline_args = seen["timeline_args"][0]
    name_to_id = timeline_args[3]
    assert all(n in name_to_id for n in seen["pair"]), (seen["pair"], name_to_id)

    # --- 产物 -------------------------------------------------------------
    data = json.loads(store.graph_json_path(work_id).read_text(encoding="utf-8"))

    assert isinstance(data.get("chapters"), list)
    assert data["chapters"] == chapters_meta
    first = data["chapters"][0]
    assert set(first) == {"id", "title", "order"}
    assert first["order"] == 1

    transitions = data.get("transitions")
    assert isinstance(transitions, list)
    assert len(transitions) == 1, transitions
    tr = transitions[0]
    # pair 必须已经从人物名翻成节点 id（CJK 名 slug 成空串后退化为 n{salt}）。
    assert tr["pair"] == [name_to_id[n] for n in seen["pair"]]
    assert tr["pair"] != seen["pair"]
    assert tr["confirmed"] is True
    assert [s["category"] for s in tr["steps"]] == ["朋友", "敌人"]

    nodes = data.get("nodes") or []
    assert nodes and any("first_chapter" in n for n in nodes)
    assert any("mentions_by_chapter" in n for n in nodes)
    edges = data.get("links") if data.get("links") is not None else data.get("edges", [])
    assert edges and all("chapters" in e for e in edges)
    # 不是换序检查的兜底（换序在带/不带 transitions 两种情况下都是字节等同的）：
    # 这条守的是**未来**某个 patch_graph_timeline 从「合并顶层键」退化成「整体覆写」，
    # 把前一步补好的 source_location 冲掉。
    assert any(e.get("source_location") for e in edges)


def test_pipeline_rejects_empty_novel(temp_data_root):
    work_id = store.new_work_id()
    raw_path = store.save_upload(work_id, "empty.txt", "   ".encode("utf-8"))
    asyncio.run(
        run_pipeline(
            work_id=work_id,
            raw_path=raw_path,
            original_filename="empty.txt",
            title="空书",
            granularity="quick",
        )
    )
    status = store.get_status(work_id)
    assert status is not None
    assert status.phase == "failed"
    assert status.error
