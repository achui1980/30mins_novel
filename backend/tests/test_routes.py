"""API route tests (design §4.3) — first route-level tests in this repo.

Uses FastAPI's TestClient against the real app, with DATA_ROOT redirected to
a temp dir (same pattern as test_pipeline_integration.py) so nothing touches
the real data/works/ directory.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import config, store
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "works")
    config.ensure_data_root()
    monkeypatch.setattr(config, "USE_FAKE_LLM", True)
    return TestClient(app)


def _seed_work_with_events(work_id: str) -> None:
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    from app.models import WorkStatus

    (wdir / "status.json").write_text(
        WorkStatus(work_id=work_id, title="测试作品", phase="done", progress=1.0).model_dump_json(),
        encoding="utf-8",
    )
    (wdir / "chapters.json").write_text(
        json.dumps({"ch0001": {"title": "第一章", "text": "……"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (wdir / "events.json").write_text(
        json.dumps(
            [
                {"summary": "甲登场", "chapter": "ch0001", "participants": ["甲"], "order_hint": 0},
                {"summary": "甲遇见乙", "chapter": "ch0001", "participants": ["甲", "乙"], "order_hint": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_get_timeline_returns_structured_events(client):
    _seed_work_with_events("work_with_events")
    res = client.get("/works/work_with_events/timeline")
    assert res.status_code == 200
    body = res.json()
    assert body["work_id"] == "work_with_events"
    assert len(body["events"]) == 2
    assert body["events"][0]["summary"] == "甲登场"
    assert body["events"][0]["chapter_title"] == "第一章"
    assert body["events"][0]["seq"] == 0
    assert body["events"][1]["seq"] == 1


def test_get_timeline_404_when_events_missing(client):
    wdir = config.work_dir("work_without_events")
    wdir.mkdir(parents=True, exist_ok=True)
    from app.models import WorkStatus

    (wdir / "status.json").write_text(
        WorkStatus(work_id="work_without_events", title="旧作品", phase="done", progress=1.0).model_dump_json(),
        encoding="utf-8",
    )
    res = client.get("/works/work_without_events/timeline")
    assert res.status_code == 404


def test_get_timeline_404_when_work_unknown(client):
    res = client.get("/works/nonexistent_work_id/timeline")
    assert res.status_code == 404
