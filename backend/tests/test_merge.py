"""Tests for the merge / dedup layer (design §4.3, §5.5)."""

from app.models import Character, ChunkExtraction, Place, Relationship, RelationCategory
from app.pipeline.merge import EntityRegistry


def test_exact_name_merge_bumps_mention_count():
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉"))
    reg.add_character(Character(name="贾宝玉"))
    assert len(reg.characters) == 1
    assert reg.characters["贾宝玉"].mention_count == 2


def test_alias_table_merge():
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉", aliases=["宝玉", "宝二爷"]))
    # A later chunk refers to the character by an alias only.
    canonical = reg.add_character(Character(name="宝玉"))
    assert canonical == "贾宝玉"
    assert len(reg.characters) == 1


def test_similar_name_fuzzy_merge():
    reg = EntityRegistry()
    reg.add_character(Character(name="林黛玉"))
    # Near-identical spelling should fuzzy-merge (>=0.86 ratio).
    canonical = reg.add_character(Character(name="林黛玉 "))
    assert canonical == "林黛玉"
    assert len(reg.characters) == 1


def test_distinct_characters_stay_separate():
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉"))
    reg.add_character(Character(name="薛宝钗"))
    assert len(reg.characters) == 2


def test_relationship_dedup_and_undirected_normalization():
    reg = EntityRegistry()
    reg.add_character(Character(name="贾宝玉"))
    reg.add_character(Character(name="林黛玉"))
    reg.add_relationship(
        Relationship(source="贾宝玉", target="林黛玉", category=RelationCategory.LOVER, confidence=0.7)
    )
    # Reverse direction, same undirected category -> should merge into one edge.
    reg.add_relationship(
        Relationship(source="林黛玉", target="贾宝玉", category=RelationCategory.LOVER, confidence=0.9)
    )
    assert len(reg.relationships) == 1
    rec = next(iter(reg.relationships.values()))
    assert rec.count == 2
    assert rec.confidence == 0.9  # max kept


def test_self_loop_relationship_skipped():
    reg = EntityRegistry()
    reg.add_character(Character(name="孙悟空"))
    reg.add_relationship(
        Relationship(source="孙悟空", target="孙悟空", category=RelationCategory.OTHER)
    )
    assert len(reg.relationships) == 0


def test_add_extraction_populates_all():
    reg = EntityRegistry()
    from app.models import Event

    ext = ChunkExtraction(
        characters=[Character(name="唐僧"), Character(name="孙悟空")],
        places=[Place(name="花果山")],
        relationships=[
            Relationship(source="唐僧", target="孙悟空", category=RelationCategory.MASTER_APPRENTICE)
        ],
        events=[Event(summary="收徒", participants=["唐僧", "孙悟空"])],
    )
    reg.add_extraction(ext, chapter_id="ch0001")
    assert len(reg.characters) == 2
    assert len(reg.places) == 1
    assert len(reg.relationships) == 1
    assert len(reg.events) == 1
    assert reg.events[0]["chapter"] == "ch0001"


def test_directed_category_keeps_direction():
    reg = EntityRegistry()
    reg.add_character(Character(name="师父"))
    reg.add_character(Character(name="徒弟"))
    reg.add_relationship(
        Relationship(source="师父", target="徒弟", category=RelationCategory.MASTER_APPRENTICE)
    )
    rec = next(iter(reg.relationships.values()))
    assert rec.source == "师父" and rec.target == "徒弟"


def test_known_entities_prompt_ranks_by_mention():
    reg = EntityRegistry()
    for _ in range(3):
        reg.add_character(Character(name="主角"))
    reg.add_character(Character(name="配角"))
    prompt = reg.known_entities_prompt()
    assert "已知角色" in prompt
    assert prompt.index("主角") < prompt.index("配角")
