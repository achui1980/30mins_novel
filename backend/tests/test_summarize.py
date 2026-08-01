"""Tests for suggested-question generation (design §4.2)."""

from app.pipeline.summarize import _fake_suggested_questions, summarize
from app.pipeline.merge import EntityRegistry
from app.models import Character, SuggestedQuestion

# Keywords that indicate graphify's old code-review-oriented questions leaked
# through (e.g. "Should `X` be split into smaller, more focused modules?").
_CODE_REVIEW_KEYWORDS = ("模块", "拆分", "重构", "split", "module", "refactor")


def _sample_spine_payload():
    return {
        "main_thread": "贾宝玉与林黛玉的爱情悲剧",
        "tone": "沉重悲剧",
        "protagonists": ["贾宝玉", "林黛玉"],
        "key_beats": ["贾宝玉初见林黛玉", "薛宝钗入府", "林黛玉病重离世"],
        "timeline_text": "",
    }


def test_fake_suggested_questions_returns_three_to_five():
    questions = _fake_suggested_questions(_sample_spine_payload())
    assert 3 <= len(questions) <= 5
    assert all(isinstance(q, SuggestedQuestion) for q in questions)
    assert all(q.question.strip() for q in questions)


def test_fake_suggested_questions_grounded_in_protagonists_and_beats():
    questions = _fake_suggested_questions(_sample_spine_payload())
    joined = " ".join(q.question for q in questions)
    assert "贾宝玉" in joined
    assert "林黛玉" in joined


def test_fake_suggested_questions_avoid_code_review_style():
    questions = _fake_suggested_questions(_sample_spine_payload())
    joined = " ".join(q.question for q in questions)
    for kw in _CODE_REVIEW_KEYWORDS:
        assert kw not in joined


def test_fake_suggested_questions_handles_missing_fields():
    # No protagonists, no key_beats — must not crash, still returns something.
    questions = _fake_suggested_questions({})
    assert isinstance(questions, list)


def test_summarize_fake_path_returns_four_tuple_with_questions(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "USE_FAKE_LLM", True)
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉"))
    reg.add_character(Character(name="林黛玉"))
    reg.events.append(
        {"summary": "初遇", "chapter": "ch0001", "participants": ["贾宝玉", "林黛玉"], "order_hint": 0}
    )
    result = summarize(reg, ["ch0001"], {0: ["贾宝玉", "林黛玉"]}, {0: "情节线"}, {}, "红楼梦")
    assert len(result) == 4
    layered, cards, suggested_questions, spine_payload = result
    assert isinstance(suggested_questions, list)
    assert len(suggested_questions) >= 1
    assert all(isinstance(q, SuggestedQuestion) for q in suggested_questions)
