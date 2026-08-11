"""Tests for the filesystem-backed work store (design §6 storage)."""

import json

import pytest

from app import config, store
from app.models import WorkStatus


@pytest.fixture()
def temp_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "works")
    config.ensure_data_root()
    return config.DATA_ROOT


def _write_status(work_id: str, phase: str) -> None:
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    status = WorkStatus(work_id=work_id, title="测试作品", phase=phase, progress=1.0)
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")


def _write_meta(work_id: str, content_sha256: str) -> None:
    store.write_meta(
        work_id,
        {"filename": "x.txt", "title": "测试作品", "content_sha256": content_sha256},
    )


# -- delete_work --------------------------------------------------------------


def test_delete_work_removes_existing_directory(temp_data_root):
    work_id = "work-to-delete"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True)
    (wdir / "raw.txt").write_text("hello", encoding="utf-8")

    result = store.delete_work(work_id)

    assert result is True
    assert not wdir.exists()


def test_delete_work_missing_work_returns_false(temp_data_root):
    # Directory never existed -> delete_work returns False rather than raising.
    assert store.delete_work("does-not-exist") is False


# -- find_ask_answer ------------------------------------------------------------


def test_find_ask_answer_matches_cached_question(temp_data_root):
    work_id = "work-with-history"
    store.append_ask_entry(
        work_id, {"question": "宝玉最后怎样了？", "answer": "郁郁而终。", "cited": ["贾宝玉"]}
    )

    found = store.find_ask_answer(work_id, "宝玉最后怎样了？")

    assert found is not None
    assert found["answer"] == "郁郁而终。"
    assert found["cited"] == ["贾宝玉"]


def test_find_ask_answer_is_case_and_space_insensitive(temp_data_root):
    work_id = "work-with-history-2"
    store.append_ask_entry(work_id, {"question": "Who is Tom?", "answer": "A cat.", "cited": []})

    found = store.find_ask_answer(work_id, "  who IS tom ? ")

    assert found is not None
    assert found["answer"] == "A cat."


def test_find_ask_answer_returns_none_when_not_cached(temp_data_root):
    work_id = "work-without-history"
    assert store.find_ask_answer(work_id, "任意问题") is None


def test_find_ask_answer_returns_none_for_unrelated_question(temp_data_root):
    work_id = "work-with-history-3"
    store.append_ask_entry(work_id, {"question": "结局如何？", "answer": "略。", "cited": []})

    assert store.find_ask_answer(work_id, "主角是谁？") is None


# -- read_graph_data ------------------------------------------------------------


def test_read_graph_data_parses_existing_file(temp_data_root):
    work_id = "work-with-graph"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True)
    graph = {"nodes": [{"id": "a", "label": "甲"}], "edges": []}
    (wdir / "graph.json").write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")

    data = store.read_graph_data(work_id)

    assert data == graph


def test_read_graph_data_returns_none_when_missing(temp_data_root):
    assert store.read_graph_data("no-such-work") is None


def test_read_graph_data_returns_none_on_malformed_json(temp_data_root):
    work_id = "work-with-bad-graph"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True)
    (wdir / "graph.json").write_text("{not valid json", encoding="utf-8")

    assert store.read_graph_data(work_id) is None


# -- find_completed_work_by_hash -------------------------------------------------


def test_find_completed_work_by_hash_matches_done_work(temp_data_root):
    target_hash = "abc123"
    _write_meta("work-done", target_hash)
    _write_status("work-done", "done")

    found = store.find_completed_work_by_hash(target_hash)

    assert found == "work-done"


def test_find_completed_work_by_hash_ignores_non_done_phase(temp_data_root):
    target_hash = "def456"
    _write_meta("work-extracting", target_hash)
    _write_status("work-extracting", "extracting")

    assert store.find_completed_work_by_hash(target_hash) is None


def test_find_completed_work_by_hash_finds_done_work_despite_sibling_with_same_hash(
    temp_data_root,
):
    target_hash = "shared-hash"
    _write_meta("work-a-failed", target_hash)
    _write_status("work-a-failed", "failed")
    _write_meta("work-b-done", target_hash)
    _write_status("work-b-done", "done")

    found = store.find_completed_work_by_hash(target_hash)

    assert found == "work-b-done"


def test_find_completed_work_by_hash_no_match_returns_none(temp_data_root):
    _write_meta("work-x", "some-hash")
    _write_status("work-x", "done")

    assert store.find_completed_work_by_hash("different-hash") is None


def test_find_completed_work_by_hash_empty_data_root_returns_none(temp_data_root):
    assert store.find_completed_work_by_hash("anything") is None
