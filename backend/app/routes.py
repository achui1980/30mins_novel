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


@router.delete("/works/{work_id}")
async def delete_work(work_id: str):
    if not store.delete_work(work_id):
        raise HTTPException(404, "作品不存在")
    return JSONResponse({"deleted": work_id})
