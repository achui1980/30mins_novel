"""Tests for the extraction layer (design §4.1 图谱降噪)."""

from app.pipeline.chunk import Block
from app.pipeline.extract import COMPLETE_HINT, SYSTEM_PROMPT, fake_extract_block


def test_system_prompt_has_place_restraint_guidance():
    assert "地点" in SYSTEM_PROMPT
    assert "克制" in SYSTEM_PROMPT


def test_complete_hint_no_longer_demands_exhaustive_places():
    # The old wording unconditionally told the LLM to extract "all" places
    # even in complete mode, which is the root cause of place over-generation.
    assert "尽量抽取全部人物、地点、事件与关系" not in COMPLETE_HINT
    assert "地点" in COMPLETE_HINT
    assert "克制" in COMPLETE_HINT


def _block(text: str) -> Block:
    return Block(block_id="ch0001_b000", chapter_id="ch0001", chapter_title="第一章", order=0, text=text)


# Enough distinct, repeated 2-4 char CJK substrings that the top-5 character
# slots fill up and at least 1-2 candidates remain available for places.
SAMPLE_TEXT = (
    "贾宝玉贾宝玉贾宝玉在潇湘馆潇湘馆潇湘馆遇见林黛玉林黛玉林黛玉。"
    "薛宝钗薛宝钗薛宝钗与王熙凤王熙凤王熙凤在大观园大观园大观园游玩。"
    "史湘云史湘云史湘云也在潇湘馆潇湘馆潇湘馆附近说话。"
)


def test_fake_extract_block_produces_up_to_five_characters():
    ext = fake_extract_block(_block(SAMPLE_TEXT))
    assert len(ext.characters) == 5


def test_fake_extract_block_produces_place_objects():
    ext = fake_extract_block(_block(SAMPLE_TEXT))
    assert 1 <= len(ext.places) <= 3
    char_names = {c.name for c in ext.characters}
    for p in ext.places:
        assert p.name not in char_names
        assert p.description


def test_fake_extract_block_places_empty_when_not_enough_candidates():
    # A block with fewer than 6 distinct frequent substrings has nothing left
    # over for places after the top-5 characters are chosen — must not error.
    ext = fake_extract_block(_block("张三张三李四李四"))
    assert isinstance(ext.places, list)
