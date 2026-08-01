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


def read_chapters(work_id: str) -> dict | None:
    """Return {chapter_id: {title, text}} persisted at parse time, or None."""
    path = config.work_dir(work_id) / "chapters.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_events(work_id: str) -> list | None:
    """Return the persisted raw event list (see EntityRegistry.events), or None."""
    path = config.work_dir(work_id) / "events.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except (ValueError, OSError):
        return None


def _chapter_summaries_path(work_id: str) -> Path:
    return config.work_dir(work_id) / "chapter_summaries.json"


def read_chapter_summaries(work_id: str) -> dict:
    """Return the on-demand chapter-summary cache {chapter_id: summary}."""
    path = _chapter_summaries_path(work_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def write_chapter_summary(work_id: str, chapter_id: str, summary: str) -> None:
    """Cache a generated chapter summary to disk (merge into existing map)."""
    cache = read_chapter_summaries(work_id)
    cache[chapter_id] = summary
    self_path = _chapter_summaries_path(work_id)
    self_path.parent.mkdir(parents=True, exist_ok=True)
    self_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def read_spine(work_id: str) -> dict | None:
    """Return the persisted 编导纲要 {main_thread,tone,protagonists,key_beats,timeline_text}, or None."""
    path = config.work_dir(work_id) / "spine.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _beat_summaries_path(work_id: str) -> Path:
    return config.work_dir(work_id) / "beat_summaries.json"


def read_beat_summaries(work_id: str) -> dict:
    """Return the on-demand beat-story cache {beat_index(str): story}."""
    path = _beat_summaries_path(work_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def write_beat_summary(work_id: str, beat_index: int, summary: str) -> None:
    """Cache a generated beat story to disk (merge into existing map)."""
    cache = read_beat_summaries(work_id)
    cache[str(beat_index)] = summary
    path = _beat_summaries_path(work_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def read_graph_data(work_id: str) -> dict | None:
    """Return the parsed graph.json {nodes, edges|links, ...}, or None."""
    path = config.work_dir(work_id) / "graph.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _ask_history_path(work_id: str) -> Path:
    return config.work_dir(work_id) / "ask_history.json"


def read_ask_history(work_id: str) -> list:
    """Return the Q&A history list [{question, answer, cited}], newest last."""
    path = _ask_history_path(work_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def find_ask_answer(work_id: str, question: str) -> dict | None:
    """Return a cached Q&A entry whose question matches (case/space-insensitive)."""
    norm = (question or "").strip().lower().replace(" ", "")
    for entry in read_ask_history(work_id):
        if (entry.get("question") or "").strip().lower().replace(" ", "") == norm:
            return entry
    return None


def append_ask_entry(work_id: str, entry: dict) -> None:
    """Append a Q&A entry to the work's history on disk."""
    history = read_ask_history(work_id)
    history.append(entry)
    path = _ask_history_path(work_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


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
