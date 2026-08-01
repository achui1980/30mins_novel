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
