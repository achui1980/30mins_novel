"""Tests for the timeline flattening module (design §4.3)."""

from app.pipeline.timeline import build_timeline

CHAPTERS = {
    "ch0001": {"title": "第一章", "text": "..."},
    "ch0002": {"title": "第二章", "text": "..."},
}


def test_build_timeline_preserves_chapter_order_and_sorts_by_order_hint():
    events = [
        {"summary": "B事件", "chapter": "ch0001", "participants": ["甲"], "order_hint": 2},
        {"summary": "A事件", "chapter": "ch0001", "participants": ["甲", "乙"], "order_hint": 1},
        {"summary": "C事件", "chapter": "ch0002", "participants": ["乙"], "order_hint": 1},
    ]
    timeline = build_timeline(events, CHAPTERS)
    assert [e.summary for e in timeline] == ["A事件", "B事件", "C事件"]
    assert [e.chapter_id for e in timeline] == ["ch0001", "ch0001", "ch0002"]
    assert [e.chapter_title for e in timeline] == ["第一章", "第一章", "第二章"]
    assert [e.seq for e in timeline] == [0, 1, 2]
    assert timeline[0].participants == ["甲", "乙"]


def test_build_timeline_none_order_hint_treated_as_zero():
    events = [
        {"summary": "有序事件", "chapter": "ch0001", "participants": [], "order_hint": 0},
        {"summary": "无序事件", "chapter": "ch0001", "participants": [], "order_hint": None},
    ]
    timeline = build_timeline(events, CHAPTERS)
    # Both order_hint 0 and None sort equally; a stable sort keeps insertion order.
    assert [e.summary for e in timeline] == ["有序事件", "无序事件"]


def test_build_timeline_unknown_chapter_appended_at_end_and_falls_back_to_id():
    events = [
        {"summary": "已知章节事件", "chapter": "ch0001", "participants": [], "order_hint": 0},
        {"summary": "未知章节事件", "chapter": "ch9999", "participants": [], "order_hint": 0},
    ]
    timeline = build_timeline(events, CHAPTERS)
    assert [e.chapter_id for e in timeline] == ["ch0001", "ch9999"]
    assert timeline[-1].chapter_title == "ch9999"  # not in CHAPTERS -> falls back to id


def test_build_timeline_empty_events_returns_empty_list():
    assert build_timeline([], CHAPTERS) == []


def test_build_timeline_missing_chapter_key_defaults_to_empty_string():
    events = [{"summary": "无章节事件", "participants": [], "order_hint": 0}]
    timeline = build_timeline(events, CHAPTERS)
    assert timeline[0].chapter_id == ""
