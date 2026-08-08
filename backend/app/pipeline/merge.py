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
import logging
from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel

from .. import config
from ..models import Character, ChunkExtraction, Place, Relationship

logger = logging.getLogger('novel_kg.merge')

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


MERGE_CONFIRM_SIM_MIN = 0.6


def _arc_seen(merged, arc_registries) -> dict[str, set[int]]:
    """Canonical merged name -> set of arc indices it appears in (by name or alias)."""
    seen: dict[str, set[int]] = {}
    for arc_idx, arc in enumerate(arc_registries):
        for rec in arc.characters.values():
            for name in rec.all_names():
                canonical = merged._alias_index.get(_norm(name))
                if canonical is not None:
                    seen.setdefault(canonical, set()).add(arc_idx)
    return seen


def _find_merge_candidates(merged, arc_registries) -> list[str]:
    seen = _arc_seen(merged, arc_registries)
    names = sorted(merged.characters)
    candidates: set[str] = set()
    for name in names:
        if len(seen.get(name, ())) >= 2:
            candidates.add(name)
    normed = {name: _norm(name) for name in names}
    counters = {name: Counter(normed[name]) for name in names}
    lens = {name: len(normed[name]) for name in names}
    n = len(names)
    for i in range(n):
        a = names[i]
        la = lens[a]
        if la == 0:
            continue
        ca = counters[a]
        for j in range(i + 1, n):
            b = names[j]
            lb = lens[b]
            if lb == 0:
                continue
            if max(la, lb) > 2.4 * min(la, lb):
                continue
            cb = counters[b]
            shared = 0
            if len(ca) <= len(cb):
                for k, v in ca.items():
                    w = cb.get(k)
                    if w:
                        shared += v if v <= w else w
            else:
                for k, v in cb.items():
                    w = ca.get(k)
                    if w:
                        shared += v if v <= w else w
            if 2 * shared / (la + lb) < 0.6:
                continue
            ratio = difflib.SequenceMatcher(None, normed[a], normed[b]).ratio()
            if MERGE_CONFIRM_SIM_MIN <= ratio < SIMILARITY_THRESHOLD:
                candidates.add(a)
                candidates.add(b)
    return sorted(candidates)


def _confirm_batches(merged, candidates, counts, batch_size=25) -> list[list[dict]]:
    batches = []
    for i in range(0, len(candidates), batch_size):
        chunk = candidates[i:i + batch_size]
        records = []
        for name in chunk:
            rec = merged.characters[name]
            records.append({
                "canonical": rec.canonical,
                "aliases": sorted(rec.aliases),
                "identity": rec.identity_line(),
                "arcs": counts.get(rec.canonical, 0),
            })
        batches.append(records)
    return batches


class MergeGroup(BaseModel):
    names: list[str]
    final_name: str


class MergeGroups(BaseModel):
    groups: list[MergeGroup]


def _llm_confirm(batches) -> list[MergeGroup]:
    from . import llm
    groups: list[MergeGroup] = []
    for batch in batches:
        lines = '\n'.join(
            f"- {r['identity']}（出现于 {r['arcs']} 个分卷）"
            for r in batch
        )
        prompt = (
            '以下是从小说不同分卷抽取出的角色记录。请判断哪些记录实际上指向同一个人物，并给出合并分组。\n'
            '规则：\n'
            '- 只合并确实指向同一人的记录（别称/简称/译名差异）；\n'
            '- 无法确定归属的记录不要放进任何分组；\n'
            '- 每组给出 final_name：该人物最正式的称呼；\n'
            '- 每组至少包含 2 个名字才需要合并。\n\n'
            f'{lines}'
        )
        try:
            result = llm.structured_output(MergeGroups, prompt,
                                           system_prompt='你是小说人物归一化专家。',
                                           what='ArcMergeConfirm', tier='strong')
            groups.extend(result.groups)
        except Exception:  # noqa: BLE001
            logger.warning('ArcMergeConfirm batch failed; skipping', exc_info=True)
    return groups


def _apply_merge(merged, src, tgt):
    if src == tgt:
        return
    srec = merged.characters.get(src)
    trec = merged.characters.get(tgt)
    if srec is None or trec is None:
        return
    trec.aliases.update(srec.aliases)
    trec.aliases.add(src)
    trec.mention_count += srec.mention_count
    if srec.role and not trec.role:
        trec.role = srec.role
    if len(srec.description) > len(trec.description):
        trec.description = srec.description
    for k, v in list(merged._alias_index.items()):
        if v == src:
            merged._alias_index[k] = tgt
    for alias in srec.all_names():
        merged._alias_index.setdefault(_norm(alias), tgt)
    from ..models import DIRECTED_CATEGORIES, RelationCategory
    new_rels: dict[tuple[str, str, str], RelationRecord] = {}
    for (s, t, cat), rec in merged.relationships.items():
        ns = tgt if s == src else s
        nt = tgt if t == src else t
        if ns == nt:
            continue
        try:
            cat_enum = RelationCategory(cat)
        except ValueError:
            cat_enum = RelationCategory.OTHER
        if cat_enum not in DIRECTED_CATEGORIES and ns > nt:
            ns, nt = nt, ns
        key = (ns, nt, cat)
        old = new_rels.get(key)
        if old is None:
            new_rels[key] = RelationRecord(source=ns, target=nt, category=cat,
                                           detail=rec.detail, evidence=rec.evidence,
                                           confidence=rec.confidence, count=rec.count)
        else:
            old.count += rec.count
            old.confidence = max(old.confidence, rec.confidence)
            if len(rec.detail) > len(old.detail):
                old.detail = rec.detail
            if len(rec.evidence) > len(old.evidence):
                old.evidence = rec.evidence
    merged.relationships = new_rels
    del merged.characters[src]


def merge_arcs(arc_registries, *, confirm: bool = True, confirmer=None) -> EntityRegistry:
    """两级跨弧合并：L1 确定性，L2 强模型确认。confirmer 供测试注入。"""
    merged = EntityRegistry()
    if not arc_registries:
        return merged
    for arc in arc_registries:
        for rec in arc.characters.values():
            merged.add_character(Character(name=rec.canonical, aliases=sorted(rec.aliases),
                                           role=rec.role, description=rec.description))
        for rec in arc.places.values():
            merged.add_place(Place(name=rec.canonical, description=rec.description))
        for rel in arc.relationships.values():
            merged.add_relationship(Relationship(source=rel.source, target=rel.target,
                                                 category=rel.category, detail=rel.detail,
                                                 evidence=rel.evidence, confidence=rel.confidence))
        merged.events.extend(dict(ev) for ev in arc.events)
    # Materialize characters referenced only by relationships so the merged
    # registry is the complete world (graph nodes) for downstream phases.
    for (src, tgt, _cat) in list(merged.relationships):
        for name in (src, tgt):
            if name not in merged.characters:
                merged.characters[name] = CharacterRecord(canonical=name, mention_count=1)
                merged._alias_index[_norm(name)] = name
    if confirm and (confirmer is not None or not config.USE_FAKE_LLM):
        try:
            seen = _arc_seen(merged, arc_registries)
            candidates = _find_merge_candidates(merged, arc_registries)
            if candidates:
                counts = {name: len(seen.get(name, ())) for name in candidates}
                batches = _confirm_batches(merged, candidates, counts)
                groups = (confirmer if confirmer else _llm_confirm)(batches)
                for group in groups:
                    g = group.model_dump() if isinstance(group, BaseModel) else group
                    names = [n for n in g['names'] if n in merged.characters]
                    if len(names) < 2:
                        continue
                    target = g['final_name'] if g['final_name'] in names else names[0]
                    for name in names:
                        if name != target:
                            _apply_merge(merged, name, target)
        except Exception:  # noqa: BLE001
            logger.warning('merge_arcs L2 confirm failed; keeping deterministic merge', exc_info=True)
    return merged
