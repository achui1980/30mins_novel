"""Filesystem-backed work store (design §6 storage).

Layout: data/works/{work_id}/  ->  raw.<ext>, graph.json, graph.html,
summary.json, status.json, meta.json
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from . import config
from .models import WorkListItem, WorkPackage, WorkStatus
from .pipeline.orchestrator import read_status


def new_work_id() -> str:
    return uuid.uuid4().hex[:12]


def save_upload(work_id: str, filename: str, data: bytes) -> Path:
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    raw_path = wdir / f"raw{suffix}"
    raw_path.write_bytes(data)
    return raw_path


def write_meta(work_id: str, meta: dict) -> None:
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def read_meta(work_id: str) -> dict | None:
    path = config.work_dir(work_id) / "meta.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_status(work_id: str) -> WorkStatus | None:
    return read_status(work_id)


def get_package(work_id: str) -> WorkPackage | None:
    path = config.work_dir(work_id) / "summary.json"
    if not path.exists():
        return None
    return WorkPackage.model_validate_json(path.read_text(encoding="utf-8"))


def graph_json_path(work_id: str) -> Path:
    return config.work_dir(work_id) / "graph.json"


def graph_html_path(work_id: str) -> Path:
    return config.work_dir(work_id) / "graph.html"


def list_works() -> list[WorkListItem]:
    root = config.DATA_ROOT
    if not root.exists():
        return []
    items: list[WorkListItem] = []
    for wdir in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not wdir.is_dir():
            continue
        status = read_status(wdir.name)
        if status is None:
            continue
        items.append(
            WorkListItem(
                work_id=status.work_id,
                title=status.title,
                phase=status.phase,
                granularity=status.granularity,
            )
        )
    return items


def delete_work(work_id: str) -> bool:
    wdir = config.work_dir(work_id)
    if wdir.exists():
        shutil.rmtree(wdir)
        return True
    return False
