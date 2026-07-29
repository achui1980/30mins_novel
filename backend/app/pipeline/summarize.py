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

import logging
from typing import Optional

from .. import config

logger = logging.getLogger("novel_kg.summarize")
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


# 叙事编导：先判断作品基调，再据此选择讲述口吻。
TONE_LIGHT = "轻松通俗"
TONE_CLASSIC = "严肃经典"
TONE_TRAGIC = "沉重悲剧"
TONE_NONFICTION = "纪实历史"
VALID_TONES = {TONE_LIGHT, TONE_CLASSIC, TONE_TRAGIC, TONE_NONFICTION}

# 每种基调对应的讲述口吻（“半小时漫画式”只用于轻松通俗类）。
TONE_VOICE = {
    TONE_LIGHT: (
        "用“半小时漫画”式的通俗口吻：像跟朋友唠嗑一样讲这个故事，"
        "可以适度玩梗、用大白话打比方，轻松幽默，但每个梗都要服务于把剧情讲清楚。"
    ),
    TONE_CLASSIC: (
        "用通俗但克制的口吻：把经典/严肃文学讲得让普通读者能读懂，"
        "少玩梗，多在关键处点透主题与深意，庄重而不枯燥。"
    ),
    TONE_TRAGIC: (
        "用庄重、共情的口吻：面对沉重或悲剧题材，保持尊重与克制，"
        "不玩梗、不调侃，突出人物命运与情感冲击。"
    ),
    TONE_NONFICTION: (
        "用清晰的科普/讲解口吻：像给零基础读者做知识梳理，"
        "把事件的来龙去脉、时间线与因果讲清楚，客观平实。"
    ),
}


def _voice_for_tone(tone: str) -> str:
    return TONE_VOICE.get(tone, TONE_VOICE[TONE_LIGHT])


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


def _structured_with_retry(agent, schema, prompt, *, what: str, attempts: int = 3):  # pragma: no cover - AWS
    """Call agent.structured_output with retries for transient Bedrock errors.

    Bedrock (esp. via streaming) can intermittently raise throttling / transient
    ResourceNotFound errors. A single such blip previously discarded the whole
    LLM summary and fell back to the template. Retry with backoff first.
    """
    import time

    last_exc = None
    for attempt in range(attempts):
        try:
            return agent.structured_output(schema, prompt)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "structured_output(%s) attempt %d/%d failed: %s",
                what, attempt + 1, attempts, exc,
            )
            if attempt < attempts - 1:
                time.sleep(config.EXTRACT_BACKOFF_BASE ** (attempt + 1))
    raise last_exc


def _story_spine(agent, digest: str, title: str):  # pragma: no cover - AWS
    """Step 1 of 叙事编导：produce an internal '编导纲要' (not shown to user).

    Decides the main thread, the tone (基调), the protagonists and the main-trunk
    beats, so step 2 can boldly cut side material and tell one coherent story in
    a voice that matches the work. Returns a StorySpine instance.
    """
    from pydantic import BaseModel, Field

    class StorySpine(BaseModel):
        main_thread: str = Field(description="一句话概括贯穿全书的主线（最重要的那条故事线）")
        tone: str = Field(
            description="作品基调，只能取以下之一：轻松通俗 / 严肃经典 / 沉重悲剧 / 纪实历史"
        )
        protagonists: list[str] = Field(default_factory=list, description="真正的主角（1-3人）")
        key_beats: list[str] = Field(
            default_factory=list, description="主干情节节点，按时间顺序，5-10条，删掉支线"
        )

    prompt = (
        f"书名：{title}\n\n{digest}\n\n"
        "你现在是一名“叙事编导”。请先通读上面的人物、关系与情节时间线，做一份内部编导纲要（不直接给读者看）：\n"
        "1. main_thread：找出贯穿全书、最重要的一条主线剧情。\n"
        "2. tone：判断这本书的基调，只能从【轻松通俗 / 严肃经典 / 沉重悲剧 / 纪实历史】中选一个"
        "（网文/爽文/搞笑类→轻松通俗；名著/严肃文学→严肃经典；悲剧/沉重题材→沉重悲剧；纪实/历史→纪实历史）。\n"
        "3. protagonists：谁是真正的主角（1-3人）。\n"
        "4. key_beats：沿主线抽出5-10个主干情节节点，按时间顺序，果断舍弃支线与龙套。"
    )
    spine = _structured_with_retry(agent, StorySpine, prompt, what="StorySpine")
    if spine.tone not in VALID_TONES:
        spine.tone = TONE_LIGHT
    return spine


def _spine_block(spine) -> str:
    """Render the internal spine as prompt context for step 2."""
    beats = "\n".join(f"  {i}. {b}" for i, b in enumerate(spine.key_beats, start=1))
    return (
        "【编导纲要（内部参考，不要原样照抄给读者）】\n"
        f"主线：{spine.main_thread}\n"
        f"主角：{('、'.join(spine.protagonists)) or '（未定）'}\n"
        f"主干节点：\n{beats}"
    )


# ---------------------------------------------------------------------------
# On-demand single-chapter summary
# ---------------------------------------------------------------------------

# Cap the source text fed to the model for a single chapter (keeps prompt bounded).
MAX_CHAPTER_CHARS = 12000


def summarize_one_chapter(title: str, chapter_title: str, text: str) -> str:
    """Generate a reader-facing summary for ONE chapter, on demand.

    Uses the LLM against the chapter's own source text when available; falls back
    to a trivial truncation when USE_FAKE_LLM is set or the LLM call fails.
    """
    body = (text or "").strip()
    if not body:
        return "（本章没有正文内容）"
    if config.USE_FAKE_LLM:
        return _fake_chapter_summary(chapter_title, body)
    try:  # pragma: no cover - AWS path
        return _llm_chapter_summary(title, chapter_title, body)
    except Exception:  # noqa: BLE001
        logger.exception("chapter summary failed, falling back to fake")
        return _fake_chapter_summary(chapter_title, body)


def _llm_chapter_summary(title: str, chapter_title: str, body: str) -> str:  # pragma: no cover - AWS
    from pydantic import BaseModel, Field

    class ChapterBrief(BaseModel):
        summary: str = Field(description="本章的读者向摘要，150-300字")

    agent = _make_summary_agent()
    snippet = body[:MAX_CHAPTER_CHARS]
    prompt = (
        f"书名：{title}\n章节：{chapter_title}\n\n"
        "以下是这一章的正文内容：\n"
        f"{snippet}\n\n"
        "请用通俗易懂、面向零基础读者的口吻，概括这一章到底讲了什么（150-300字）：\n"
        "说清楚本章发生的关键事件、推动了哪些情节、涉及的主要人物。\n"
        "必须忠于原文，不要虚构原文没有的情节，也不要剧透后续章节。"
    )
    brief = _structured_with_retry(agent, ChapterBrief, prompt, what="ChapterBrief")
    return (brief.summary or "").strip() or _fake_chapter_summary(chapter_title, body)


def _fake_chapter_summary(chapter_title: str, body: str) -> str:
    head = body.replace("\n", " ").strip()[:120]
    return f"【{chapter_title}】{head}……（离线模式摘要，仅截取开头片段）"


# ---------------------------------------------------------------------------
# On-demand story-beat narration ("故事正片" / 半小时漫画式讲述)
# ---------------------------------------------------------------------------


def generate_beat_story(title: str, spine: dict, beat_index: int) -> str:
    """Expand ONE key_beat into a 150-300字 narrated paragraph, on demand.

    ``spine`` is the persisted 编导纲要 payload with keys:
    main_thread, tone, protagonists, key_beats, timeline_text.
    Uses the tone-adaptive voice; falls back to a plain restatement offline / on error.
    """
    beats = spine.get("key_beats") or []
    if beat_index < 0 or beat_index >= len(beats):
        return "（该情节节拍不存在）"
    beat = str(beats[beat_index] or "").strip()
    if not beat:
        return "（该情节节拍为空）"
    if config.USE_FAKE_LLM:
        return _fake_beat_story(spine, beat_index)
    try:  # pragma: no cover - AWS path
        return _llm_beat_story(title, spine, beat_index)
    except Exception:  # noqa: BLE001
        logger.exception("beat story failed, falling back to fake")
        return _fake_beat_story(spine, beat_index)


def _llm_beat_story(title: str, spine: dict, beat_index: int) -> str:  # pragma: no cover - AWS
    from pydantic import BaseModel, Field

    class BeatStory(BaseModel):
        story: str = Field(description="这一情节节拍的叙述段落，150-300字")

    beats = spine.get("key_beats") or []
    beat = str(beats[beat_index])
    tone = spine.get("tone") or TONE_LIGHT
    if tone not in VALID_TONES:
        tone = TONE_LIGHT
    voice = _voice_for_tone(tone)
    main_thread = spine.get("main_thread") or ""
    protagonists = "、".join(spine.get("protagonists") or []) or "（未定）"
    timeline_text = spine.get("timeline_text") or ""
    beat_list = "\n".join(f"  {i + 1}. {b}" for i, b in enumerate(beats))

    prompt = (
        f"书名：{title}\n"
        f"全书主线：{main_thread}\n"
        f"主角：{protagonists}\n\n"
        "【完整情节节拍（编导已排好序）】\n"
        f"{beat_list}\n\n"
        "【原著情节时间线（忠实性锚点，只能依据它讲，不得编造）】\n"
        f"{timeline_text}\n\n"
        f"这本书的基调是【{tone}】。请你据此选择讲述口吻：{voice}\n"
        "无论何种口吻，都必须遵守：忠于原著、绝不虚构原著没有的情节。\n\n"
        f"现在请把第 {beat_index + 1} 个节拍——“{beat}”——展开讲述成一个 150-300 字的叙述段落：\n"
        "把这一段剧情讲得像在给没读过原著的朋友讲故事：说清楚这一拍发生了什么、"
        "涉及哪些人物、和前后剧情如何衔接、对主线有什么推动。只讲这一拍，不要把整本书都讲完。"
    )
    result = _structured_with_retry(_make_summary_agent(), BeatStory, prompt, what="BeatStory")
    return (result.story or "").strip() or _fake_beat_story(spine, beat_index)


def _fake_beat_story(spine: dict, beat_index: int) -> str:
    beats = spine.get("key_beats") or []
    beat = str(beats[beat_index]) if 0 <= beat_index < len(beats) else ""
    main_thread = spine.get("main_thread") or ""
    prefix = f"（第{beat_index + 1}拍）"
    body = beat
    if main_thread:
        body += f" 这一拍紧扣主线：{main_thread}"
    return f"{prefix}{body}……（离线模式讲述，仅基于编导纲要节点）"


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
    chapter_titles: Optional[dict] = None,
) -> tuple[LayeredSummary, list[SettingCard], Optional[dict]]:
    """Return (LayeredSummary, setting_cards, spine_payload).

    spine_payload is the 编导纲要 (main_thread/tone/protagonists/key_beats/timeline_text)
    used to power the on-demand "故事正片" beat narration, or None if unavailable.
    """
    if chapter_titles:
        registry.chapter_titles = chapter_titles
    if config.USE_FAKE_LLM:
        return _fake_summary(registry, chapters, communities, community_labels, id_to_name, title, chapter_titles)
    try:  # pragma: no cover - AWS path
        return _llm_summary(registry, chapters, communities, community_labels, id_to_name, title, chapter_titles)
    except Exception:  # noqa: BLE001
        logger.exception("LLM summary failed, falling back to fake summary")
        return _fake_summary(registry, chapters, communities, community_labels, id_to_name, title, chapter_titles)


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


def _llm_summary(registry, chapters, communities, community_labels, id_to_name, title, chapter_titles=None):  # pragma: no cover - AWS
    agent = _make_summary_agent()
    digest = _registry_digest(registry, chapters)
    timeline_text = _plot_timeline(registry, chapters)

    # Step 1: 叙事编导——先定主线与基调（失败则退回中性默认，不影响后续）。
    spine_payload: Optional[dict] = None
    try:
        spine = _story_spine(agent, digest, title)
        tone = spine.tone
        spine_block = _spine_block(spine)
        spine_payload = {
            "main_thread": spine.main_thread,
            "tone": spine.tone,
            "protagonists": list(spine.protagonists),
            "key_beats": list(spine.key_beats),
            "timeline_text": timeline_text,
        }
    except Exception:  # noqa: BLE001
        tone = TONE_LIGHT
        spine_block = ""

    voice = _voice_for_tone(tone)

    # Step 2: 按基调选定的口吻，围绕主线讲一个完整故事。
    prompt = (
        f"书名：{title}\n\n{digest}\n\n"
        f"{spine_block}\n\n"
        f"这本书的基调是【{tone}】。请你据此选择讲述口吻：{voice}\n"
        "无论何种口吻，都必须遵守：忠于原著、绝不虚构原著没有的情节、面向没读过原著的零基础读者。\n\n"
        "请围绕上面的主线讲清楚这本小说到底在讲什么，生成分层摘要，字段要求如下：\n"
        "- one_liner：一句话点明故事核心（谁，遭遇了什么，追求什么），要有吸引力。\n"
        "- story_hook：30-50字，告诉读者“这本书为什么值得读”，一句能勾起兴趣的钩子。\n"
        "- overview：一段完整的故事梗概（200-400字），围绕主线、大胆取舍支线，"
        "必须按【起因→发展→高潮→结局】的叙事顺序讲清楚：开端与主要矛盾、情节如何推进、"
        "关键转折/高潮、以及最终结局或走向。要让没读过原著的读者看完就明白这本小说讲的是什么，"
        "禁止只罗列人物或关系。\n"
        "- arcs：每条情节线一段摘要，对应下方给出的人物社区。\n"
    )
    layered = _structured_with_retry(agent, LayeredSummary, prompt, what="LayeredSummary")

    # 章节摘要改为“按需生成”：这里只放占位（章节id+标题，summary留空），
    # 由前端点击某章时再调用 /works/{id}/chapters/{ch}/summary 生成。
    titles = chapter_titles or {}
    layered.chapters = [
        ChapterSummary(chapter=ch, title=titles.get(ch, ""), summary="")
        for ch in chapters
    ]

    class SettingCards(__import__("pydantic").BaseModel):
        cards: list[SettingCard]

    cards_prompt = f"书名：{title}\n\n{digest}\n\n请生成3-6张设定卡（世界观/主题/关键概念），每张有title与content。"
    # 设定卡失败不应连累已经生成好的分层摘要——单独兜底为假数据卡。
    try:
        cards = _structured_with_retry(agent, SettingCards, cards_prompt, what="SettingCards").cards
    except Exception:  # noqa: BLE001
        logger.exception("SettingCards generation failed; keeping LLM summary with fallback cards")
        cards = _fake_setting_cards(registry, communities, community_labels)
    return layered, cards, spine_payload


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


def _fake_summary(registry, chapters, communities, community_labels, id_to_name, title, chapter_titles=None):
    top_chars = sorted(
        registry.characters.values(), key=lambda r: r.mention_count, reverse=True
    )
    main_names = [r.canonical for r in top_chars[:3]]
    one_liner = (
        f"《{title}》围绕{('、'.join(main_names)) or '主要人物'}展开的故事。"
    )
    story_hook = (
        f"跟着{(main_names[0] if main_names else '主角')}的脚步，"
        f"用30分钟理清这本书的{len(registry.events)}个关键情节，快速读懂它在讲什么。"
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

    # Chapter summaries are generated on demand (click). Leave summary empty here.
    chapter_summaries: list[ChapterSummary] = []
    titles = chapter_titles or {}
    for ch in chapters:
        chapter_summaries.append(
            ChapterSummary(chapter=ch, title=titles.get(ch, ""), summary="")
        )

    layered = LayeredSummary(
        one_liner=one_liner,
        story_hook=story_hook,
        overview=overview,
        arcs=arcs,
        chapters=chapter_summaries,
    )

    cards = _fake_setting_cards(registry, communities, community_labels)

    # Simplified 编导纲要 so the offline path also powers the 故事正片 tab.
    fake_beats = [e.get("summary", "") for e in ordered_events if e.get("summary")][:8]
    spine_payload = {
        "main_thread": one_liner,
        "tone": TONE_LIGHT,
        "protagonists": main_names,
        "key_beats": fake_beats,
        "timeline_text": _plot_timeline(registry, chapters),
    }
    return layered, cards, spine_payload


def _fake_setting_cards(registry, communities, community_labels) -> list[SettingCard]:
    top_chars = sorted(
        registry.characters.values(), key=lambda r: r.mention_count, reverse=True
    )
    main_names = [r.canonical for r in top_chars[:3]]
    return [
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
