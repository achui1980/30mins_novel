"""API routes (design §6). FastAPI, v1 no-auth, filesystem storage."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import config, store
from .models import CreateWorkResponse, WorkStatus
from .pipeline.orchestrator import run_pipeline

router = APIRouter()


def _launch_pipeline(work_id, raw_path, filename, title, granularity) -> None:
    """Run the async pipeline on a fresh event loop in a background thread."""
    asyncio.run(run_pipeline(work_id, raw_path, filename, title, granularity))


@router.post("/works", status_code=201, response_model=CreateWorkResponse)
async def create_work(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    granularity: str = Form("quick"),
) -> CreateWorkResponse:
    filename = file.filename or "novel.txt"
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"仅支持 {', '.join(sorted(config.ALLOWED_EXTENSIONS))} 文件")
    if granularity not in ("quick", "complete"):
        granularity = "quick"

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(400, "文件为空")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大（上限 {config.MAX_UPLOAD_BYTES // (1024*1024)}MB）")

    work_id = store.new_work_id()
    raw_path = store.save_upload(work_id, filename, data)
    title = filename.rsplit(".", 1)[0]
    store.write_meta(work_id, {"filename": filename, "title": title, "granularity": granularity})

    # Initialize queued status so it appears in listings immediately.
    store.get_status(work_id) or _init_status(work_id, title, granularity)

    background_tasks.add_task(
        _launch_pipeline, work_id, raw_path, filename, title, granularity
    )
    return CreateWorkResponse(work_id=work_id, status="queued")


def _init_status(work_id: str, title: str, granularity: str) -> None:
    from .pipeline.orchestrator import write_status

    write_status(
        WorkStatus(
            work_id=work_id,
            title=title,
            granularity=granularity,
            phase="queued",
            progress=0.0,
            message="排队中…",
        )
    )


@router.get("/works")
async def list_works():
    return [item.model_dump() for item in store.list_works()]


@router.get("/works/{work_id}/status", response_model=WorkStatus)
async def get_status(work_id: str):
    status = store.get_status(work_id)
    if status is None:
        raise HTTPException(404, "作品不存在")
    return status


@router.get("/works/{work_id}")
async def get_work(work_id: str):
    package = store.get_package(work_id)
    if package is None:
        status = store.get_status(work_id)
        if status is None:
            raise HTTPException(404, "作品不存在")
        raise HTTPException(409, f"作品尚未处理完成（当前阶段：{status.phase}）")
    return package


@router.get("/works/{work_id}/graph")
async def get_graph(work_id: str):
    path = store.graph_json_path(work_id)
    if not path.exists():
        raise HTTPException(404, "图谱尚未生成")
    return FileResponse(path, media_type="application/json")


@router.get("/works/{work_id}/graph.html")
async def get_graph_html(work_id: str):
    path = store.graph_html_path(work_id)
    if not path.exists():
        raise HTTPException(404, "交互图谱尚未生成")
    return FileResponse(path, media_type="text/html")


@router.post("/works/{work_id}/chapters/{chapter_id}/summary")
async def generate_chapter_summary(work_id: str, chapter_id: str):
    """Generate (or return cached) a summary for a single chapter, on demand."""
    if store.get_status(work_id) is None:
        raise HTTPException(404, "作品不存在")

    # Serve from disk cache if already generated.
    cached = store.read_chapter_summaries(work_id).get(chapter_id)
    if cached:
        return {"chapter": chapter_id, "summary": cached, "cached": True}

    chapters = store.read_chapters(work_id)
    if not chapters or chapter_id not in chapters:
        raise HTTPException(404, "章节不存在或未保存原文（请重新处理该作品）")

    ch = chapters[chapter_id]
    meta = store.read_meta(work_id) or {}
    title = meta.get("title") or work_id

    from .pipeline.summarize import summarize_one_chapter

    summary = await asyncio.to_thread(
        summarize_one_chapter, title, ch.get("title") or chapter_id, ch.get("text") or ""
    )
    store.write_chapter_summary(work_id, chapter_id, summary)
    return {"chapter": chapter_id, "summary": summary, "cached": False}


@router.get("/works/{work_id}/beats")
async def list_beats(work_id: str):
    """Return the story beats (故事正片) list from the persisted 编导纲要."""
    if store.get_status(work_id) is None:
        raise HTTPException(404, "作品不存在")
    spine = store.read_spine(work_id)
    if not spine or not spine.get("key_beats"):
        raise HTTPException(404, "该作品未生成故事正片（请重新处理该作品以体验此功能）")
    beats = [
        {"index": i, "title": str(b)}
        for i, b in enumerate(spine.get("key_beats") or [])
    ]
    return {
        "main_thread": spine.get("main_thread") or "",
        "tone": spine.get("tone") or "",
        "beats": beats,
    }


@router.post("/works/{work_id}/beats/{beat_index}/story")
async def generate_beat_story_route(work_id: str, beat_index: int):
    """Generate (or return cached) the narrated paragraph for one story beat."""
    if store.get_status(work_id) is None:
        raise HTTPException(404, "作品不存在")

    cached = store.read_beat_summaries(work_id).get(str(beat_index))
    if cached:
        return {"index": beat_index, "story": cached, "cached": True}

    spine = store.read_spine(work_id)
    if not spine or not spine.get("key_beats"):
        raise HTTPException(404, "该作品未生成故事正片（请重新处理该作品）")
    if beat_index < 0 or beat_index >= len(spine.get("key_beats") or []):
        raise HTTPException(404, "该情节节拍不存在")

    meta = store.read_meta(work_id) or {}
    title = meta.get("title") or work_id

    from .pipeline.summarize import generate_beat_story

    story = await asyncio.to_thread(generate_beat_story, title, spine, beat_index)
    store.write_beat_summary(work_id, beat_index, story)
    return {"index": beat_index, "story": story, "cached": False}


@router.delete("/works/{work_id}")
async def delete_work(work_id: str):
    if not store.delete_work(work_id):
        raise HTTPException(404, "作品不存在")
    return JSONResponse({"deleted": work_id})
