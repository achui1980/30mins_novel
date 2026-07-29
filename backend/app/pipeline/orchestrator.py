"""Async pipeline orchestrator (design §2, §6 storage, §8 error handling).

Runs the full ingestion pipeline for one work and continuously writes progress
to ``data/works/{work_id}/status.json``:

    queued -> parsing -> extracting(%) -> building -> summarizing -> done|failed

Produces on disk: raw.<ext>, graph.json, graph.html, summary.json, status.json.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path

from .. import config
from ..models import (
    MainCharacter,
    SuggestedQuestion,
    WorkPackage,
    WorkStatus,
)
from .chunk import chunk_novel
from .extract import extract_all
from .graph import run_graphify
from .merge import EntityRegistry
from .parse import ParseError, parse_upload
from .summarize import label_communities, summarize


def _status_path(work_id: str) -> Path:
    return config.work_dir(work_id) / "status.json"


def write_status(status: WorkStatus) -> None:
    path = _status_path(status.work_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(status.model_dump_json(indent=2), encoding="utf-8")


def read_status(work_id: str) -> WorkStatus | None:
    path = _status_path(work_id)
    if not path.exists():
        return None
    return WorkStatus.model_validate_json(path.read_text(encoding="utf-8"))


async def run_pipeline(
    work_id: str,
    raw_path: Path,
    original_filename: str,
    title: str,
    granularity: str,
) -> None:
    """Execute the full pipeline; never raises (records failure into status)."""
    warnings: list[str] = []
    status = WorkStatus(
        work_id=work_id,
        title=title,
        granularity=granularity,
        phase="parsing",
        progress=0.0,
        message="正在解析文件…",
        warnings=warnings,
    )
    write_status(status)

    try:
        # 1. Parse -----------------------------------------------------------
        novel = parse_upload(raw_path, original_filename)
        if title in (None, "", original_filename) and novel.title:
            title = novel.title
            status.title = title
        chapter_ids = [c.id for c in novel.chapters]
        chapter_titles = novel.chapter_titles
        # Persist per-chapter source text so chapter summaries can be generated
        # on demand later (registry/events are in-memory only and not saved).
        chapters_payload = {
            c.id: {"title": c.title, "text": c.text} for c in novel.chapters
        }
        (config.work_dir(work_id) / "chapters.json").write_text(
            json.dumps(chapters_payload, ensure_ascii=False), encoding="utf-8"
        )
        status.message = f"解析完成，共 {len(novel.chapters)} 章"
        write_status(status)

        # 2. Chunk -----------------------------------------------------------
        blocks = chunk_novel(novel)
        if not blocks:
            raise ParseError("未能从文件中提取到任何正文内容")

        # 3. Extract ---------------------------------------------------------
        status.phase = "extracting"
        status.message = "正在抽取人物与关系…"
        write_status(status)
        registry = EntityRegistry()

        def on_progress(done: int, total: int) -> None:
            status.progress = round(done / total, 4) if total else 1.0
            status.message = f"抽取中 {done}/{total} 块"
            write_status(status)

        def on_warn(msg: str) -> None:
            warnings.append(msg)
            status.warnings = warnings
            write_status(status)

        await extract_all(
            blocks,
            registry,
            granularity=granularity,
            progress_cb=on_progress,
            warn_cb=on_warn,
        )

        if not registry.characters:
            raise ParseError("未能抽取到任何人物，无法构建图谱")

        # 4. Build graph -----------------------------------------------------
        status.phase = "building"
        status.progress = 1.0
        status.message = "正在构建知识图谱…"
        write_status(status)

        wdir = config.work_dir(work_id)
        graph_json = wdir / "graph.json"
        graph_html = wdir / "graph.html"

        artifacts = run_graphify(
            registry,
            graph_json,
            graph_html,
            community_labeler=label_communities,
        )

        # 5. Summarize -------------------------------------------------------
        status.phase = "summarizing"
        status.message = "正在生成分层摘要与设定卡…"
        write_status(status)

        layered, setting_cards, spine_payload = summarize(
            registry,
            chapter_ids,
            artifacts.communities,
            artifacts.community_labels,
            artifacts.id_to_label,
            title,
            chapter_titles,
        )

        # Persist the 编导纲要 so the 故事正片 tab can expand beats on demand later.
        if spine_payload and spine_payload.get("key_beats"):
            (wdir / "spine.json").write_text(
                json.dumps(spine_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        main_characters = _build_main_characters(artifacts, registry)
        suggested = _build_suggested_questions(artifacts)

        package = WorkPackage(
            work_id=work_id,
            title=title,
            granularity=granularity,
            layered_summary=layered,
            setting_cards=setting_cards,
            graph_ref="graph.json",
            main_characters=main_characters,
            suggested_questions=suggested,
        )
        (wdir / "summary.json").write_text(
            package.model_dump_json(indent=2), encoding="utf-8"
        )

        # 6. Done ------------------------------------------------------------
        status.phase = "done"
        status.progress = 1.0
        status.message = "完成"
        write_status(status)

    except ParseError as exc:
        status.phase = "failed"
        status.error = str(exc)
        status.message = f"处理失败：{exc}"
        write_status(status)
    except Exception as exc:  # noqa: BLE001
        status.phase = "failed"
        status.error = f"{exc}\n{traceback.format_exc()}"
        status.message = f"处理失败：{exc}"
        write_status(status)


def _build_main_characters(artifacts, registry: EntityRegistry) -> list[MainCharacter]:
    out: list[MainCharacter] = []
    for g in artifacts.god_nodes:
        nid = g.get("id") if isinstance(g, dict) else getattr(g, "id", None)
        if nid is None:
            continue
        name = artifacts.id_to_label.get(nid, g.get("label", nid) if isinstance(g, dict) else nid)
        rec = registry.characters.get(name)
        score = g.get("score", 0.0) if isinstance(g, dict) else 0.0
        out.append(
            MainCharacter(
                id=nid,
                label=name,
                description=(rec.description if rec else "") or (rec.role if rec else ""),
                score=float(score or 0.0),
                mention_count=rec.mention_count if rec else 0,
            )
        )
    return out


def _build_suggested_questions(artifacts) -> list[SuggestedQuestion]:
    out: list[SuggestedQuestion] = []
    for q in artifacts.suggested_questions:
        if isinstance(q, dict):
            # graphify may emit a placeholder like
            # {"type": "no_signal", "question": None, "why": ...} when it has
            # no basis for questions — skip those instead of stringifying.
            if q.get("type") == "no_signal" or not q.get("question") and not q.get("text"):
                continue
            question = q.get("question") or q.get("text")
            rationale = q.get("rationale") or q.get("reason") or q.get("why") or ""
        else:
            question = str(q).strip()
            rationale = ""
        if not question:
            continue
        out.append(SuggestedQuestion(question=question, rationale=rationale))
    return out
