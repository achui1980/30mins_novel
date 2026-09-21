"""graphify integration (design §5.3, §7 graph output).

Converts the deduplicated EntityRegistry into graphify's extraction-JSON schema,
then runs the canonical graphify build pipeline:

    build_from_json -> cluster -> score_all -> god_nodes
                    -> export.to_json + export.to_html

Custom node/edge fields (node_type, description, category, detail, evidence,
mention_count, confidence...) are preserved by build_from_json straight into
graph.json, which is exactly what the reader UI consumes.

Note: graphify's analyze.suggest_questions (betweenness-centrality, code-review
oriented) is intentionally NOT used — it produces nonsensical questions for
novel text. Suggested questions are instead generated in summarize.py from the
already-computed story spine (design §4.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..models import DIRECTED_CATEGORIES, RelationCategory, confidence_label
from .merge import EntityRegistry

_ID_RE = re.compile(r"[^a-z0-9_]+")


def _slug(name: str, salt: int) -> str:
    """graphify node ids must be lowercase [a-z0-9_]. CJK names slugify to empty,
    so we fall back to a deterministic id derived from a running index."""
    base = _ID_RE.sub("_", name.strip().lower()).strip("_")
    if not base:
        base = f"n{salt}"
    return base


def _first_chapter(
    counts: dict[str, int], chapter_order: dict[str, int] | None
) -> str:
    """按章序取首次出场章。没有 order 表时退化为字典序（chNNNN 零填充）。

    永不抛异常：空直方图（merge_arcs 为「只在关系里出现过的人物」补的记录就是
    空的）返回 ""；直方图里的章 id 全都不在 order 表里时，过滤掉而不是把它们
    的序当 0，再退化到字典序。
    """
    if not counts:
        return ""
    if chapter_order:
        known = [c for c in counts if c in chapter_order]
        if known:
            return min(known, key=lambda c: chapter_order[c])
    return min(counts)


@dataclass
class GraphArtifacts:
    graph: object  # networkx.Graph
    communities: dict  # community_id -> [node_id, ...]
    community_labels: dict  # community_id -> label
    god_nodes: list  # ranked hub nodes
    id_to_label: dict  # node_id -> display label
    label_to_id: dict


def build_extraction_json(
    registry: EntityRegistry, chapter_order: dict[str, int] | None = None
) -> tuple[dict, dict, dict]:
    """Return (extraction_json, name_to_id, id_to_name).

    ``chapter_order`` is an optional ``chapter_id -> order`` lookup (see
    ``evolve.chapter_order_map``). It only decides which chapter counts as
    "first": chapter precedence is judged by that numeric order, never by
    comparing chapter-id strings. ``None`` is fully supported.
    """
    name_to_id: dict[str, str] = {}
    id_to_name: dict[str, str] = {}
    nodes: list[dict] = []

    salt = 0

    def ensure_id(name: str) -> str:
        nonlocal salt
        if name in name_to_id:
            return name_to_id[name]
        salt += 1
        nid = _slug(name, salt)
        # Guarantee uniqueness.
        base = nid
        k = 1
        while nid in id_to_name:
            nid = f"{base}_{k}"
            k += 1
        name_to_id[name] = nid
        id_to_name[nid] = name
        return nid

    # Character nodes
    for rec in registry.characters.values():
        nid = ensure_id(rec.canonical)
        nodes.append(
            {
                "id": nid,
                "label": rec.canonical,
                "file_type": "document",
                "source_file": rec.description or rec.canonical,
                "node_type": "character",
                "description": rec.description,
                "role": rec.role,
                "aliases": sorted(rec.aliases),
                "source_location": "",
                "mention_count": rec.mention_count,
                "mentions_by_chapter": dict(rec.mentions_by_chapter),
                "first_chapter": _first_chapter(rec.mentions_by_chapter, chapter_order),
            }
        )

    # Place nodes
    for rec in registry.places.values():
        nid = ensure_id(rec.canonical)
        nodes.append(
            {
                "id": nid,
                "label": rec.canonical,
                "file_type": "document",
                "source_file": rec.description or rec.canonical,
                "node_type": "place",
                "description": rec.description,
                "source_location": "",
                "mention_count": rec.mention_count,
                # 地点只用它推首次出场章，不画曲线，所以不带 mentions_by_chapter。
                "first_chapter": _first_chapter(rec.mentions_by_chapter, chapter_order),
            }
        )

    # Edges
    edges: list[dict] = []
    for rec in registry.relationships.values():
        if rec.source not in name_to_id or rec.target not in name_to_id:
            # Relationship referenced a name that never became a node; create it.
            for nm in (rec.source, rec.target):
                if nm not in name_to_id:
                    nid = ensure_id(nm)
                    nodes.append(
                        {
                            "id": nid,
                            "label": nm,
                            "file_type": "document",
                            "source_file": nm,
                            "node_type": "character",
                            "description": "",
                            "mention_count": 1,
                            "mentions_by_chapter": {},
                            "first_chapter": "",
                        }
                    )
        try:
            cat_enum = RelationCategory(rec.category)
        except ValueError:
            cat_enum = RelationCategory.OTHER
        edges.append(
            {
                "source": name_to_id[rec.source],
                "target": name_to_id[rec.target],
                "relation": rec.category,
                "category": rec.category,
                "detail": rec.detail,
                "evidence": rec.evidence,
                "confidence": rec.confidence,
                "confidence_score": rec.confidence,
                "confidence_label": confidence_label(rec.confidence),
                "directed": cat_enum in DIRECTED_CATEGORIES,
                "weight": max(1, rec.count),
                # 注意：weight 仍来自 rec.count，不从 chapters 推导。
                # count != sum(chapters.values())（见 merge.py:81-83），这是有意的。
                "chapters": dict(rec.chapters),
                "first_chapter": _first_chapter(rec.chapters, chapter_order),
                "source_location": "",
            }
        )

    extraction = {
        "nodes": nodes,
        "edges": edges,
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }
    return extraction, name_to_id, id_to_name


def run_graphify(
    registry: EntityRegistry,
    graph_json_path: Path,
    graph_html_path: Path,
    community_labeler=None,
    chapter_order: dict[str, int] | None = None,
) -> GraphArtifacts:
    """Run the full graphify build and write graph.json + graph.html.

    ``community_labeler`` is an optional callable
    ``(communities, id_to_name, registry) -> {community_id: label}``. If None,
    a simple heuristic label (top character in the community) is used.

    ``chapter_order`` is passed straight through to ``build_extraction_json`` so
    the per-node/per-edge ``first_chapter`` fields are ranked by chapter order.
    """
    import graphify.analyze as analyze
    import graphify.cluster as cluster_mod
    from graphify.build import build_from_json
    from graphify.export import to_json

    try:
        from graphify.exporters.html import to_html
    except Exception:  # pragma: no cover - fallback path
        from graphify.export import to_html  # type: ignore

    extraction, name_to_id, id_to_name = build_extraction_json(
        registry, chapter_order=chapter_order
    )
    G = build_from_json(extraction, directed=False)

    communities = cluster_mod.cluster(G) or {}
    try:
        cluster_mod.score_all(G, communities)
    except Exception:  # noqa: BLE001 - scoring is best-effort
        pass

    gods = analyze.god_nodes(G, top_n=10) or []
    # Fallback: if god_nodes is empty (small graphs), rank by degree/mention.
    if not gods:
        gods = _fallback_god_nodes(G, id_to_name)

    # Community labels.
    if community_labeler is not None:
        community_labels = community_labeler(communities, id_to_name, registry)
    else:
        community_labels = _heuristic_labels(communities, G, id_to_name, registry)

    graph_json_path.parent.mkdir(parents=True, exist_ok=True)
    to_json(G, communities, str(graph_json_path), force=True, community_labels=community_labels)

    member_counts = {cid: len(members) for cid, members in communities.items()}
    try:
        to_html(
            G,
            communities,
            str(graph_html_path),
            community_labels=community_labels,
            member_counts=member_counts,
        )
    except Exception:  # noqa: BLE001 - html is a nice-to-have
        pass

    return GraphArtifacts(
        graph=G,
        communities=communities,
        community_labels=community_labels,
        god_nodes=gods,
        id_to_label=id_to_name,
        label_to_id=name_to_id,
    )


def _fallback_god_nodes(G, id_to_name: dict) -> list[dict]:
    """Rank nodes by degree (tie-broken by mention_count) when god_nodes is empty."""
    ranked = []
    for nid in G.nodes():
        data = G.nodes[nid]
        if data.get("node_type") == "place":
            continue
        degree = G.degree(nid)
        mentions = data.get("mention_count", 0)
        ranked.append((degree, mentions, nid))
    ranked.sort(reverse=True)
    out = []
    for degree, mentions, nid in ranked[:10]:
        out.append(
            {
                "id": nid,
                "label": G.nodes[nid].get("label", id_to_name.get(nid, nid)),
                "score": float(degree),
                "degree": degree,
                "mention_count": mentions,
            }
        )
    return out


def _heuristic_labels(communities: dict, G, id_to_name: dict, registry: EntityRegistry) -> dict:
    """Name each community after its most-mentioned character."""
    labels: dict = {}
    for cid, members in communities.items():
        best_name = None
        best_mentions = -1
        for nid in members:
            data = G.nodes.get(nid, {})
            if data.get("node_type") == "place":
                continue
            mentions = data.get("mention_count", 0)
            if mentions > best_mentions:
                best_mentions = mentions
                best_name = data.get("label") or id_to_name.get(nid, nid)
        labels[cid] = f"{best_name}相关情节线" if best_name else f"情节线 {cid}"
    return labels
