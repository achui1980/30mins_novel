"""Summarization layer (design §5.4, §7 reader output).

Produces the reader-facing artifacts from the built graph + registry:
  - LayeredSummary: one_liner -> overview -> arcs (per community) -> chapters
  - SettingCard[]: theme / worldview cards
  - community labels: 2-5 word names per community (used by graphify + arcs)

Uses AWS Strands structured_output against Bedrock. When config.USE_FAKE_LLM is
set, a deterministic fallback derives everything from the registry so the whole
pipeline runs offline / in tests.
"""

from __future__ import annotations

from typing import Optional

from .. import config
from ..models import (
    ArcSummary,
    ChapterSummary,
    LayeredSummary,
    SettingCard,
)
from .merge import EntityRegistry


# ---------------------------------------------------------------------------
# Strands backend
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM_PROMPT = (
    "你是一个面向读者的小说导读助手。基于给定的人物、关系、事件与章节信息，"
    "生成分层摘要与设定卡，帮助读者在30分钟内读懂这本书。语言简洁、无剧透警告地直接概述。"
)


MAX_TIMELINE_EVENTS = 120


def _chapter_title(registry: EntityRegistry, chapter_id: str) -> str:
    """Best-effort human chapter label; falls back to the chapter id."""
    titles = getattr(registry, "chapter_titles", None)
    if isinstance(titles, dict):
        t = titles.get(chapter_id)
        if t:
            return str(t)
    return chapter_id


def _plot_timeline(registry: EntityRegistry, chapters: list[str]) -> str:
    """Assemble an ordered, chapter-grouped plot timeline (design: 强化情节层).

    Groups events by chapter (in the chapter order of the novel), sorts within
    a chapter by order_hint, and emits structured text so the summarizer can
    write a real story synopsis (起因-发展-高潮-结局). Total events capped at
    MAX_TIMELINE_EVENTS (~120) to bound prompt size.
    """
    by_chapter: dict[str, list[dict]] = {}
    for e in registry.events:
        by_chapter.setdefault(e.get("chapter", ""), []).append(e)

    # Preserve novel chapter order; append any chapters not in the list at the end.
    ordered_chapters = [c for c in chapters if c in by_chapter]
    for c in by_chapter:
        if c not in ordered_chapters:
            ordered_chapters.append(c)

    lines: list[str] = []
    emitted = 0
    for ch in ordered_chapters:
        if emitted >= MAX_TIMELINE_EVENTS:
            break
        events = sorted(by_chapter.get(ch, []), key=lambda x: (x.get("order_hint") or 0))
        if not events:
            continue
        lines.append(f"【{_chapter_title(registry, ch)}】")
        for idx, e in enumerate(events, start=1):
            if emitted >= MAX_TIMELINE_EVENTS:
                lines.append("  …（后续事件从略）")
                break
            participants = e.get("participants") or []
            who = "、".join(str(p) for p in participants[:4])
            suffix = f"（参与者：{who}）" if who else ""
            lines.append(f"  {idx}. {e.get('summary', '')}{suffix}")
            emitted += 1
    return "\n".join(lines)


def _registry_digest(registry: EntityRegistry, chapters: list[str]) -> str:
    """Build a compact textual digest of the registry to feed the summarizer."""
    lines: list[str] = []
    top_chars = sorted(
        registry.characters.values(), key=lambda r: r.mention_count, reverse=True
    )[:20]
    lines.append("主要人物：")
    for r in top_chars:
        lines.append(f"- {r.identity_line()} (出现{r.mention_count}次)")
    lines.append("\n关系：")
    for rec in list(registry.relationships.values())[:40]:
        lines.append(f"- {rec.source} —[{rec.category}]— {rec.target}: {rec.detail}")
    timeline = _plot_timeline(registry, chapters)
    if timeline:
        lines.append("\n情节时间线（按章节顺序，用于概括故事走向）：")
        lines.append(timeline)
    else:
        lines.append("\n情节时间线：（暂无可用事件）")
    return "\n".join(lines)


def _make_summary_agent():  # pragma: no cover - requires AWS creds
    from strands import Agent
    from strands.models import BedrockModel

    model = BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.BEDROCK_REGION)
    return Agent(model=model, system_prompt=SUMMARY_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def label_communities(
    communities: dict,
    id_to_name: dict,
    registry: EntityRegistry,
) -> dict:
    """community_id -> 2-5 word label. Fake mode uses heuristic; real mode LLM."""
    if config.USE_FAKE_LLM:
        return _fake_labels(communities, id_to_name, registry)
    try:  # pragma: no cover - AWS path
        return _llm_labels(communities, id_to_name, registry)
    except Exception:  # noqa: BLE001
        return _fake_labels(communities, id_to_name, registry)


def summarize(
    registry: EntityRegistry,
    chapters: list[str],
    communities: dict,
    community_labels: dict,
    id_to_name: dict,
    title: str,
) -> tuple[LayeredSummary, list[SettingCard]]:
    """Return (LayeredSummary, setting_cards)."""
    if config.USE_FAKE_LLM:
        return _fake_summary(registry, chapters, communities, community_labels, id_to_name, title)
    try:  # pragma: no cover - AWS path
        return _llm_summary(registry, chapters, communities, community_labels, id_to_name, title)
    except Exception:  # noqa: BLE001
        return _fake_summary(registry, chapters, communities, community_labels, id_to_name, title)


# ---------------------------------------------------------------------------
# LLM implementations
# ---------------------------------------------------------------------------


def _llm_labels(communities, id_to_name, registry):  # pragma: no cover - AWS
    from pydantic import BaseModel, Field

    class CommunityLabel(BaseModel):
        community_id: int
        label: str = Field(description="2-5字的情节线/阵营名称")

    class CommunityLabels(BaseModel):
        labels: list[CommunityLabel]

    agent = _make_summary_agent()
    desc_lines = []
    for cid, members in communities.items():
        names = [id_to_name.get(m, m) for m in members][:8]
        desc_lines.append(f"社区{cid}: {', '.join(names)}")
    prompt = (
        "以下是按图聚类得到的人物社区，请为每个社区起一个2-5字的情节线或阵营名称：\n"
        + "\n".join(desc_lines)
    )
    result = agent.structured_output(CommunityLabels, prompt)
    return {lbl.community_id: lbl.label for lbl in result.labels}


def _llm_summary(registry, chapters, communities, community_labels, id_to_name, title):  # pragma: no cover - AWS
    agent = _make_summary_agent()
    digest = _registry_digest(registry, chapters)

    class _SummaryModel(LayeredSummary):
        pass

    prompt = (
        f"书名：{title}\n\n{digest}\n\n"
        "请基于上面的【情节时间线】写出这本小说到底在讲什么，生成分层摘要，字段要求如下：\n"
        "- one_liner：一句话点明故事核心（谁，遭遇了什么，追求什么）。\n"
        "- overview：一段完整的故事梗概（200-400字），必须按【起因→发展→高潮→结局】"
        "的叙事顺序讲清楚：故事的开端与主要矛盾、情节如何推进、关键转折/高潮、以及最终结局或走向。"
        "要让没读过原著的读者看完就明白这本小说讲的是什么，禁止只罗列人物或关系。\n"
        "- arcs：每条情节线一段摘要，对应下方给出的人物社区。\n"
        "- chapters：每章一句话，用叙事口吻概括本章发生了什么（推动了什么情节），"
        "不要写“本章无事件”这类空话。"
    )
    layered = agent.structured_output(LayeredSummary, prompt)

    class SettingCards(__import__("pydantic").BaseModel):
        cards: list[SettingCard]

    cards_prompt = f"书名：{title}\n\n{digest}\n\n请生成3-6张设定卡（世界观/主题/关键概念），每张有title与content。"
    cards = agent.structured_output(SettingCards, cards_prompt).cards
    return layered, cards


# ---------------------------------------------------------------------------
# Deterministic fake implementations (offline / tests)
# ---------------------------------------------------------------------------


def _fake_labels(communities, id_to_name, registry) -> dict:
    labels = {}
    for cid, members in communities.items():
        best_name, best = None, -1
        for m in members:
            name = id_to_name.get(m, m)
            rec = registry.characters.get(name)
            mentions = rec.mention_count if rec else 0
            if mentions > best:
                best, best_name = mentions, name
        labels[cid] = f"{best_name}的故事线" if best_name else f"情节线{cid}"
    return labels


def _fake_summary(registry, chapters, communities, community_labels, id_to_name, title):
    top_chars = sorted(
        registry.characters.values(), key=lambda r: r.mention_count, reverse=True
    )
    main_names = [r.canonical for r in top_chars[:3]]
    one_liner = (
        f"《{title}》围绕{('、'.join(main_names)) or '主要人物'}展开的故事。"
    )

    # Ordered plot events (by chapter order, then order_hint) for a story direction.
    by_chapter_ev: dict[str, list[dict]] = {}
    for e in registry.events:
        by_chapter_ev.setdefault(e.get("chapter", ""), []).append(e)
    ordered_events: list[dict] = []
    for ch in chapters:
        ordered_events.extend(
            sorted(by_chapter_ev.get(ch, []), key=lambda x: (x.get("order_hint") or 0))
        )
    opening = ordered_events[0]["summary"] if ordered_events else ""
    ending = ordered_events[-1]["summary"] if len(ordered_events) > 1 else ""
    direction = ""
    if opening and ending:
        direction = f"故事起于“{opening}”，最终走向“{ending}”。"
    elif opening:
        direction = f"故事以“{opening}”为开端。"

    overview = (
        f"本书共{len(chapters)}章，登场人物{len(registry.characters)}位，"
        f"核心人物包括{('、'.join(main_names)) or '若干角色'}。"
        f"故事涉及{len(registry.relationships)}组人物关系与{len(registry.events)}个关键事件。"
        f"{direction}"
    )

    arcs: list[ArcSummary] = []
    for cid, members in communities.items():
        member_names = [id_to_name.get(m, m) for m in members]
        char_names = [n for n in member_names if n in registry.characters]
        label = community_labels.get(cid, f"情节线{cid}")
        arcs.append(
            ArcSummary(
                title=label,
                summary=f"{label}：涉及{('、'.join(char_names[:5])) or '若干人物'}等{len(char_names)}位人物。",
                community_id=cid,
                member_characters=char_names[:10],
            )
        )

    # Chapter summaries: join the first few ordered events of each chapter.
    by_chapter: dict[str, list[str]] = {}
    for ch in chapters:
        evs = sorted(by_chapter_ev.get(ch, []), key=lambda x: (x.get("order_hint") or 0))
        by_chapter[ch] = [e["summary"] for e in evs]
    chapter_summaries: list[ChapterSummary] = []
    for ch in chapters:
        summaries = by_chapter.get(ch, [])
        if summaries:
            text = "；".join(summaries[:3])
        else:
            text = "（本章暂无提取到关键事件）"
        chapter_summaries.append(ChapterSummary(chapter=ch, summary=text))

    layered = LayeredSummary(
        one_liner=one_liner,
        overview=overview,
        arcs=arcs,
        chapters=chapter_summaries,
    )

    cards = [
        SettingCard(
            title="人物概览",
            content=f"全书共{len(registry.characters)}位登场人物，其中{('、'.join(main_names))}为核心角色。",
        ),
        SettingCard(
            title="关系网络",
            content=f"人物之间存在{len(registry.relationships)}组关系，涵盖家人、爱人、朋友、敌人等类别。",
        ),
        SettingCard(
            title="情节线",
            content=f"故事可归纳为{len(communities)}条主要情节线：{('；'.join(community_labels.values()))}。",
        ),
    ]
    return layered, cards
