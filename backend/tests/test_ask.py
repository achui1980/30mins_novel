"""Tests for the on-demand Q&A layer (design §6 /ask, offline fallback path)."""

import pytest

from app import config
from app.pipeline.ask import _fake_answer_question, answer_question


# -- _fake_answer_question (offline fallback) ------------------------------------


def test_fake_answer_question_matches_known_entity_in_question():
    graph_data = {
        "nodes": [
            {"id": "n1", "label": "贾宝玉", "node_type": "character"},
            {"id": "n2", "label": "林黛玉", "node_type": "character"},
        ]
    }

    result = _fake_answer_question(graph_data, "贾宝玉最后怎么样了？")

    assert result["cited"] == ["贾宝玉"]
    assert "贾宝玉" in result["answer"]
    assert "离线模式" in result["answer"]


def test_fake_answer_question_matches_multiple_entities():
    graph_data = {
        "nodes": [
            {"id": "n1", "label": "贾宝玉", "node_type": "character"},
            {"id": "n2", "label": "林黛玉", "node_type": "character"},
            {"id": "n3", "label": "薛宝钗", "node_type": "character"},
        ]
    }

    result = _fake_answer_question(graph_data, "贾宝玉和林黛玉是什么关系？")

    assert result["cited"] == ["贾宝玉", "林黛玉"]


def test_fake_answer_question_no_entity_match():
    graph_data = {"nodes": [{"id": "n1", "label": "贾宝玉", "node_type": "character"}]}

    result = _fake_answer_question(graph_data, "这本书讲的是什么故事？")

    assert result["cited"] == []
    assert "未能" in result["answer"]


def test_fake_answer_question_handles_empty_node_list():
    result = _fake_answer_question({"nodes": []}, "随便问点什么")

    assert result["cited"] == []
    assert isinstance(result["answer"], str) and result["answer"]


def test_fake_answer_question_handles_missing_nodes_key():
    # graph_data.get("nodes") or [] must tolerate a graph_data with no "nodes" key.
    result = _fake_answer_question({}, "随便问点什么")

    assert result["cited"] == []


def test_fake_answer_question_is_deterministic_and_offline():
    graph_data = {"nodes": [{"id": "n1", "label": "甲", "node_type": "character"}]}

    first = _fake_answer_question(graph_data, "甲是谁？")
    second = _fake_answer_question(graph_data, "甲是谁？")

    assert first == second


# -- answer_question (public entry point) ----------------------------------------


def test_answer_question_rejects_empty_question():
    result = answer_question(
        title="红楼梦", graph_data={"nodes": []}, spine=None, chapters=None, question="   "
    )

    assert result == {"answer": "（问题为空）", "cited": []}


def test_answer_question_uses_fake_path_when_use_fake_llm_is_set(monkeypatch):
    monkeypatch.setattr(config, "USE_FAKE_LLM", True)
    graph_data = {"nodes": [{"id": "n1", "label": "贾宝玉", "node_type": "character"}]}

    result = answer_question(
        title="红楼梦", graph_data=graph_data, spine=None, chapters=None, question="贾宝玉是谁？"
    )

    assert result["cited"] == ["贾宝玉"]
    assert "离线模式" in result["answer"]
