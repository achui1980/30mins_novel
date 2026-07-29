"""On-demand agentic Q&A over a built work (design §6 /ask, deferred v2).

Instead of stuffing a fixed context into one prompt, this uses an *agent*:
the LLM is given a set of tools (read a chapter, look up a character's
relations, keyword-search the full text) and decides on its own which to call,
how many times, to gather the evidence it needs before answering. This is what
lets it answer "how does it end?" — it can go read the last chapters itself.

Available artifacts (per work_id, on disk):
  - graph.json    : character/place nodes + relationship edges (always present)
  - spine.json    : 编导纲要 incl. ordered plot timeline (new works only)
  - chapters.json : {chapter_id: {title, text}} full source (new works only)

When chapters.json is absent (older works), only the graph tools are offered
and the agent degrades to relationship-level answers. When config.USE_FAKE_LLM
is set, or the agent call fails, a deterministic offline fallback is used.
"""

from __future__ import annotations

import logging
from typing import Optional

from .. import config

logger = logging.getLogger("novel_kg.ask")

# Bounds to keep tool outputs (and thus the agent's context) manageable.
MAX_CHAPTER_CHARS = 8000
MAX_SEARCH_HITS = 6
SEARCH_SNIPPET_RADIUS = 200

ASK_SYSTEM_PROMPT = (
    "你是一个小说问答助手。你可以调用工具去查阅这本书的资料（人物关系、章节原文、"
    "全文关键词搜索），来回答读者的问题。\n"
    "工作方式：\n"
    "1. 先想清楚要回答这个问题需要哪些信息，主动调用工具去查（可以多次调用）。\n"
    "2. 比如问“结局/最后怎样”，就去读靠后的章节；问某人物，就查该人物关系或搜其名字。\n"
    "3. 只依据工具查到的真实内容回答，绝不编造原文没有的情节。\n"
    "4. 如果查遍了也找不到相关信息，就如实说明“根据现有资料无法回答”。\n"
    "5. 回答用通俗易懂、面向零基础读者的口吻，简明扼要。"
)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def answer_question(
    title: str,
    graph_data: dict,
    spine: Optional[dict],
    chapters: Optional[dict],
    question: str,
) -> dict:
    """Answer one question about the work using an agent. Returns {answer, cited}."""
    q = (question or "").strip()
    if not q:
        return {"answer": "（问题为空）", "cited": []}

    if config.USE_FAKE_LLM:
        return _fake_answer_question(graph_data, q)
    try:  # pragma: no cover - AWS path
        return _agent_answer_question(title, graph_data, spine, chapters, q)
    except Exception:  # noqa: BLE001
        logger.exception("ask agent failed, falling back to fake")
        return _fake_answer_question(graph_data, q)


# ---------------------------------------------------------------------------
# Agentic path (tools + LLM-driven retrieval)
# ---------------------------------------------------------------------------


def _agent_answer_question(  # pragma: no cover - AWS
    title: str,
    graph_data: dict,
    spine: Optional[dict],
    chapters: Optional[dict],
    question: str,
) -> dict:
    from strands import Agent, tool
    from strands.models import BedrockModel

    nodes = graph_data.get("nodes") or []
    edges = graph_data.get("edges") or graph_data.get("links") or []
    id_to_label = {n.get("id"): n.get("label", n.get("id")) for n in nodes}
    characters = [n for n in nodes if n.get("node_type") == "character"]
    characters.sort(key=lambda n: n.get("mention_count", 0), reverse=True)

    # Ordered chapter listing (chapters.json keys are chapter ids like ch0001).
    chapter_items = sorted((chapters or {}).items()) if chapters else []

    # --- Tools -------------------------------------------------------------

    @tool
    def list_characters() -> str:
        """列出这本书的主要人物（按出现次数排序）。用于了解书里都有谁。"""
        lines = []
        for n in characters[:60]:
            role = (n.get("role") or "").strip()
            desc = (n.get("description") or "").strip()
            extra = "；".join(x for x in (role, desc) if x)
            lines.append(
                f"- {n.get('label','')}（出现{n.get('mention_count',0)}次）"
                f"{('：' + extra) if extra else ''}"
            )
        return "\n".join(lines) or "（没有人物信息）"

    @tool
    def get_relations(name: str) -> str:
        """查询某个人物与其他人的关系。参数 name 是人物名称。"""
        hits = []
        for e in edges:
            src = id_to_label.get(e.get("source"), e.get("source"))
            tgt = id_to_label.get(e.get("target"), e.get("target"))
            if name and (name in str(src) or name in str(tgt)):
                cat = e.get("category") or e.get("relation") or ""
                detail = (e.get("detail") or "").strip()
                hits.append(f"- {src} —[{cat}]— {tgt}{('：' + detail) if detail else ''}")
        return "\n".join(hits[:40]) or f"（没有查到与“{name}”相关的关系）"

    @tool
    def list_chapters() -> str:
        """列出这本书的章节目录（章节ID + 标题），用于决定去读哪一章。"""
        if not chapter_items:
            return "（本作品没有保存章节原文，无法按章阅读）"
        return "\n".join(
            f"- {cid}: {(c.get('title') or cid)}" for cid, c in chapter_items
        )

    @tool
    def read_chapter(chapter_id: str) -> str:
        """读取某一章的正文原文。参数 chapter_id 形如 ch0012（见 list_chapters）。"""
        if not chapters:
            return "（本作品没有保存章节原文）"
        ch = chapters.get(chapter_id)
        if not ch:
            return f"（找不到章节 {chapter_id}，请先调用 list_chapters 查看有哪些章节）"
        text = (ch.get("text") or "").strip()
        if not text:
            return f"（章节 {chapter_id} 没有正文）"
        return f"【{ch.get('title') or chapter_id}】\n{text[:MAX_CHAPTER_CHARS]}"

    @tool
    def search_text(keyword: str) -> str:
        """在全书正文里搜索关键词，返回命中的原文片段（含所在章节）。"""
        if not chapter_items:
            return "（本作品没有保存章节原文，无法全文搜索）"
        kw = (keyword or "").strip()
        if not kw:
            return "（关键词为空）"
        hits = []
        for cid, c in chapter_items:
            text = c.get("text") or ""
            start = 0
            while len(hits) < MAX_SEARCH_HITS:
                pos = text.find(kw, start)
                if pos < 0:
                    break
                a = max(0, pos - SEARCH_SNIPPET_RADIUS)
                b = min(len(text), pos + len(kw) + SEARCH_SNIPPET_RADIUS)
                snippet = text[a:b].replace("\n", " ")
                hits.append(f"[{c.get('title') or cid}] …{snippet}…")
                start = pos + len(kw)
            if len(hits) >= MAX_SEARCH_HITS:
                break
        return "\n\n".join(hits) or f"（全书未找到“{kw}”）"

    tools = [list_characters, get_relations]
    if chapter_items:
        tools += [list_chapters, read_chapter, search_text]

    model = BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.BEDROCK_REGION)
    agent = Agent(model=model, system_prompt=ASK_SYSTEM_PROMPT, tools=tools)

    hint = ""
    if not chapter_items:
        hint = "（提示：本作品没有章节原文，你只能依据人物关系回答，涉及具体情节/结局时请如实说明信息不足。）\n"
    prompt = f"书名：《{title}》\n{hint}读者的问题是：{question}"

    result = _run_agent_with_retry(agent, prompt)
    answer = str(result).strip()
    if not answer:
        return {"answer": "根据现有的分析资料，无法回答这个问题。", "cited": []}

    # Best-effort: which known character/place names appear in the answer.
    cited = [n.get("label", "") for n in nodes if n.get("label") and n["label"] in answer]
    return {"answer": answer, "cited": cited[:12]}


def _run_agent_with_retry(agent, prompt, *, attempts: int = 3):  # pragma: no cover - AWS
    """Invoke the agent with retries for transient Bedrock errors."""
    import time

    last_exc = None
    for attempt in range(attempts):
        try:
            return agent(prompt)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("ask agent attempt %d/%d failed: %s", attempt + 1, attempts, exc)
            if attempt < attempts - 1:
                time.sleep(config.EXTRACT_BACKOFF_BASE ** (attempt + 1))
    raise last_exc


# ---------------------------------------------------------------------------
# Offline fallback
# ---------------------------------------------------------------------------


def _fake_answer_question(graph_data: dict, question: str) -> dict:
    """Offline fallback: keyword-match graph nodes against the question."""
    nodes = graph_data.get("nodes") or []
    hits = [n.get("label", "") for n in nodes if n.get("label") and n["label"] in question]
    if hits:
        answer = (
            f"（离线模式）问题中提到了：{('、'.join(hits))}。"
            "已在知识图谱中定位到这些实体，但离线模式下无法调用工具检索原文，"
            "请在接入 Bedrock 后再次提问。"
        )
    else:
        answer = (
            "（离线模式）未能在知识图谱中匹配到问题里的实体，"
            "请在接入 Bedrock 后再次提问以获得完整回答。"
        )
    return {"answer": answer, "cited": hits}
