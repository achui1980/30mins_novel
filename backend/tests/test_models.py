"""Tests for Pydantic models & taxonomy helpers."""

import pytest
from pydantic import ValidationError

from app.models import (
    Character,
    ChunkExtraction,
    DIRECTED_CATEGORIES,
    Event,
    Relationship,
    RelationCategory,
    confidence_label,
)


def test_confidence_label_thresholds():
    assert confidence_label(0.95) == "EXTRACTED"
    assert confidence_label(0.9) == "EXTRACTED"
    assert confidence_label(0.5) == "INFERRED"
    assert confidence_label(0.4) == "INFERRED"
    assert confidence_label(0.1) == "AMBIGUOUS"


def test_relation_category_values():
    assert RelationCategory.FAMILY.value == "家人"
    assert RelationCategory.MASTER_APPRENTICE.value == "师徒"
    assert RelationCategory.MASTER_APPRENTICE in DIRECTED_CATEGORIES
    assert RelationCategory.FRIEND not in DIRECTED_CATEGORIES


def test_character_defaults():
    c = Character(name="张三")
    assert c.aliases == []
    assert c.role == ""
    assert c.description == ""


def test_relationship_accepts_chinese_category():
    r = Relationship(source="a", target="b", category="敌人")
    assert r.category == RelationCategory.ENEMY


def test_relationship_rejects_bad_category():
    with pytest.raises(ValidationError):
        Relationship(source="a", target="b", category="仇人")


def test_chunk_extraction_empty_defaults():
    ext = ChunkExtraction()
    assert ext.characters == []
    assert ext.places == []
    assert ext.events == []
    assert ext.relationships == []


def test_event_chapter_coerces_int_to_str():
    e = Event(summary="甲登场", chapter=2)
    assert e.chapter == "2"


def test_event_chapter_keeps_str():
    e = Event(summary="甲登场", chapter="ch0001")
    assert e.chapter == "ch0001"
