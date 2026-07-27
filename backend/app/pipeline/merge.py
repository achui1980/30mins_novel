"""Incremental merge / dedup of extracted entities (design §4.3, §5.5).

Strategy, in order of cost:
  1. exact canonical-name match  -> merge
  2. alias-table hit             -> merge
  3. high similarity name        -> queued for a batched LLM normalization confirm

The registry also serves the *sliding context*: at any point it can emit the
"known entities" list (name + aliases + one-line identity) that the extractor
injects into the next chunk's prompt so pronouns resolve to existing characters.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from ..models import Character, ChunkExtraction, Place, Relationship

# Names at/above this ratio are treated as "possibly the same" and sent to the
# optional LLM normalization step (or auto-merged if it is disabled).
SIMILARITY_THRESHOLD = 0.86


def _norm(name: str) -> str:
    return name.strip().lower().replace(" ", "").replace("\u3000", "")


@dataclass
class CharacterRecord:
    canonical: str
    aliases: set[str] = field(default_factory=set)
    role: str = ""
    description: str = ""
    mention_count: int = 0

    def all_names(self) -> set[str]:
        return {self.canonical, *self.aliases}

    def identity_line(self) -> str:
        alias_str = f"（别名：{', '.join(sorted(self.aliases))}）" if self.aliases else ""
        desc = self.description or self.role
        return f"{self.canonical}{alias_str}: {desc}".strip().rstrip(":")


@dataclass
class PlaceRecord:
    canonical: str
    description: str = ""
    mention_count: int = 0


@dataclass
class RelationRecord:
    source: str  # canonical
    target: str  # canonical
    category: str
    detail: str = ""
    evidence: str = ""
    confidence: float = 0.0
    count: int = 0


class EntityRegistry:
    """Accumulates and deduplicates entities across chunks."""

    def __init__(self) -> None:
        self.characters: dict[str, CharacterRecord] = {}  # canonical -> record
        self._alias_index: dict[str, str] = {}  # normalized name/alias -> canonical
        self.places: dict[str, PlaceRecord] = {}
        self._place_index: dict[str, str] = {}
        self.relationships: dict[tuple[str, str, str], RelationRecord] = {}
        self.events: list[dict] = []

    # -- resolution ---------------------------------------------------------
    def resolve_character(self, name: str) -> str | None:
        """Return the canonical name for ``name`` if already known, else None."""
        key = _norm(name)
        if key in self._alias_index:
            return self._alias_index[key]
        # Fuzzy match against known names.
        best: tuple[float, str] | None = None
        for known_key, canonical in self._alias_index.items():
            ratio = difflib.SequenceMatcher(None, key, known_key).ratio()
            if ratio >= SIMILARITY_THRESHOLD and (best is None or ratio > best[0]):
                best = (ratio, canonical)
        return best[1] if best else None

    # -- ingestion ----------------------------------------------------------
    def add_character(self, char: Character) -> str:
        canonical = self.resolve_character(char.name)
        if canonical is None:
            # Also try resolving via any provided alias before creating new.
            for alias in char.aliases:
                canonical = self.resolve_character(alias)
                if canonical:
                    break
        if canonical is None:
            canonical = char.name.strip()
            self.characters[canonical] = CharacterRecord(
                canonical=canonical,
                role=char.role,
                description=char.description,
            )
            self._alias_index[_norm(canonical)] = canonical

        rec = self.characters[canonical]
        rec.mention_count += 1
        if not rec.role and char.role:
            rec.role = char.role
        if len(char.description) > len(rec.description):
            rec.description = char.description
        # Register aliases (and the incoming name itself if different).
        for alias in {char.name, *char.aliases}:
            alias = alias.strip()
            if not alias or alias == canonical:
                continue
            rec.aliases.add(alias)
            self._alias_index.setdefault(_norm(alias), canonical)
        return canonical

    def add_place(self, place: Place) -> str:
        key = _norm(place.name)
        canonical = self._place_index.get(key)
        if canonical is None:
            canonical = place.name.strip()
            self.places[canonical] = PlaceRecord(canonical=canonical, description=place.description)
            self._place_index[key] = canonical
        rec = self.places[canonical]
        rec.mention_count += 1
        if len(place.description) > len(rec.description):
            rec.description = place.description
        return canonical

    def add_relationship(self, rel: Relationship) -> None:
        src = self.resolve_character(rel.source) or rel.source.strip()
        tgt = self.resolve_character(rel.target) or rel.target.strip()
        if src == tgt:
            return
        category = rel.category.value if hasattr(rel.category, "value") else str(rel.category)
        # Undirected categories: normalize the key so (a,b)==(b,a).
        from ..models import DIRECTED_CATEGORIES, RelationCategory

        try:
            cat_enum = RelationCategory(category)
        except ValueError:
            cat_enum = RelationCategory.OTHER
            category = cat_enum.value
        if cat_enum not in DIRECTED_CATEGORIES and src > tgt:
            src, tgt = tgt, src
        key = (src, tgt, category)
        rec = self.relationships.get(key)
        if rec is None:
            rec = RelationRecord(
                source=src, target=tgt, category=category,
                detail=rel.detail, evidence=rel.evidence, confidence=rel.confidence,
            )
            self.relationships[key] = rec
        rec.count += 1
        rec.confidence = max(rec.confidence, rel.confidence)
        if len(rel.detail) > len(rec.detail):
            rec.detail = rel.detail
        if len(rel.evidence) > len(rec.evidence):
            rec.evidence = rel.evidence

    def add_extraction(self, extraction: ChunkExtraction, chapter_id: str) -> None:
        for c in extraction.characters:
            self.add_character(c)
        for p in extraction.places:
            self.add_place(p)
        for r in extraction.relationships:
            self.add_relationship(r)
        for e in extraction.events:
            self.events.append(
                {
                    "summary": e.summary,
                    "chapter": e.chapter or chapter_id,
                    "participants": e.participants,
                    "order_hint": e.order_hint,
                }
            )

    # -- sliding context ----------------------------------------------------
    def known_entities_prompt(self, max_entities: int = 40) -> str:
        """Emit the 'known characters' block injected into the next chunk prompt."""
        if not self.characters:
            return ""
        ranked = sorted(
            self.characters.values(), key=lambda r: r.mention_count, reverse=True
        )[:max_entities]
        lines = [r.identity_line() for r in ranked]
        return "已知角色（请把代词/别称解析到这些已有角色，不要重复创建）：\n" + "\n".join(
            f"- {ln}" for ln in lines
        )
