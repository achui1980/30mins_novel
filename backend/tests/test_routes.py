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


def test_get_chapter_text_returns_full_chapter(client):
    from app.models import WorkStatus

    work_id = "work-rawtext-ok"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    status = WorkStatus(work_id=work_id, title="测试作品", phase="done", progress=1.0)
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")
    (wdir / "chapters.json").write_text(
        json.dumps({"ch0001": {"title": "第一章", "text": "这是第一章的正文内容。"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    resp = client.get(f"/works/{work_id}/chapters/ch0001/text")

    assert resp.status_code == 200
    body = resp.json()
    assert body["chapter_id"] == "ch0001"
    assert body["title"] == "第一章"
    assert body["paragraphs"] == ["这是第一章的正文内容。"]


def test_get_chapter_text_404_when_chapters_missing(client):
    from app.models import WorkStatus

    work_id = "work-rawtext-no-chapters"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    status = WorkStatus(work_id=work_id, title="测试作品", phase="done", progress=1.0)
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")

    resp = client.get(f"/works/{work_id}/chapters/ch0001/text")

    assert resp.status_code == 404


def test_get_chapter_text_404_when_chapter_id_unknown(client):
    from app.models import WorkStatus

    work_id = "work-rawtext-unknown-chapter"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    status = WorkStatus(work_id=work_id, title="测试作品", phase="done", progress=1.0)
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")
    (wdir / "chapters.json").write_text(
        json.dumps({"ch0001": {"title": "第一章", "text": "正文"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    resp = client.get(f"/works/{work_id}/chapters/ch9999/text")

    assert resp.status_code == 404


def test_get_chapter_text_404_when_work_unknown(client):
    resp = client.get("/works/nonexistent_work_id/chapters/ch0001/text")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Path-traversal / invalid work_id regression tests
#
# config._validate_work_id (^[A-Za-z0-9_-]{1,64}$) is invoked by every
# config.work_dir() call, i.e. on nearly every route below. Malformed ids
# must be rejected with 400 "invalid work_id" *before* any filesystem access
# — never a 404/500, and never an id echoed back in the response body.
#
# Note: ids containing a literal "/" (e.g. "a/b") never reach our code at
# all — Starlette's router treats it as extra path segments and returns its
# own 404 "Not Found" without matching the route. That's still safe (no
# filesystem access happens), just not our validator's 400. Only when the
# offending characters stay within a single path segment (URL-encoded "..",
# a space, an embedded NUL, a backslash, or an overlong id) does the request
# actually reach config.work_dir() and get our 400.
# ---------------------------------------------------------------------------

_MALFORMED_WORK_IDS = [
    "%2e%2e",  # ".." URL-encoded — classic path-traversal payload
    "%20",  # a single space — outside the allowed charset
    "abc%00def",  # embedded NUL byte
    "..%5c..%5cwindows",  # backslash-based traversal (URL-encoded)
    "a" * 65,  # over the 64-char length cap
]

_WORK_ID_ROUTES = [
    ("GET", "/works/{wid}/status"),
    ("GET", "/works/{wid}"),
    ("GET", "/works/{wid}/graph"),
    ("DELETE", "/works/{wid}"),
]


@pytest.mark.parametrize("method,path_tmpl", _WORK_ID_ROUTES)
@pytest.mark.parametrize("bad_id", _MALFORMED_WORK_IDS)
def test_malformed_work_id_rejected_with_400(client, method, path_tmpl, bad_id):
    path = path_tmpl.format(wid=bad_id)
    res = client.request(method, path)
    # Must never succeed, never 500, and never silently 404 as if the (bad)
    # id were merely "not found" — it must be flagged as invalid input.
    assert res.status_code == 400, (
        f"{method} {path} returned {res.status_code}, expected 400 "
        f"(body={res.text!r})"
    )
    body = res.json()
    assert body["detail"] == "invalid work_id"
    # The offending value must never be echoed back to the client.
    assert bad_id not in res.text


@pytest.mark.parametrize("method,path_tmpl", _WORK_ID_ROUTES)
def test_literal_dotdot_never_reaches_filesystem(client, method, path_tmpl):
    """A literal unencoded ".." segment (e.g. /works/../status) is collapsed
    by Starlette's own path normalization *before* routing even happens, so
    it never reaches our route handlers or config.work_dir() at all — the
    request 404s at the framework level (no route matches the normalized
    path). This is still safe (no filesystem access occurs), just via a
    different mechanism than our 400 validator, hence the separate test."""
    path = path_tmpl.format(wid="..")
    res = client.request(method, path)
    assert res.status_code == 404


_WORK_ID_ROUTE_NOT_FOUND_DETAIL = {
    ("GET", "/works/{wid}/status"): "作品不存在",
    ("GET", "/works/{wid}"): "作品不存在",
    ("GET", "/works/{wid}/graph"): "图谱尚未生成",
    ("DELETE", "/works/{wid}"): "作品不存在",
}


@pytest.mark.parametrize("method,path_tmpl", _WORK_ID_ROUTES)
def test_wellformed_but_unknown_work_id_still_404(client, method, path_tmpl):
    """A syntactically valid work_id that simply doesn't exist must still 404,
    proving the new validation doesn't swallow the normal not-found case."""
    path = path_tmpl.format(wid="abc123def456")
    res = client.request(method, path)
    assert res.status_code == 404
    assert res.json()["detail"] == _WORK_ID_ROUTE_NOT_FOUND_DETAIL[(method, path_tmpl)]


# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------


def test_cors_credentials_disallowed():
    """allow_credentials must stay False: combined with allow_origins=["*"]
    this is a known-dangerous pattern (see app/main.py comment)."""
    from starlette.middleware.cors import CORSMiddleware

    cors_middlewares = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors_middlewares) == 1
    assert cors_middlewares[0].kwargs["allow_credentials"] is False


def test_cors_preflight_response_has_no_allow_credentials_header(client):
    res = client.options(
        "/works",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.headers.get("access-control-allow-credentials") != "true"


# ---------------------------------------------------------------------------
# get_status must not leak a full traceback over the API
# ---------------------------------------------------------------------------


def test_get_status_truncates_error_to_first_line(client):
    from app.models import WorkStatus

    work_id = "work-with-traceback-error"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    traceback_like = (
        "解析失败: boom\n"
        "Traceback (most recent call last):\n"
        '  File "orchestrator.py", line 123, in run_pipeline\n'
        "    raise ValueError('boom')\n"
        "ValueError: boom"
    )
    status = WorkStatus(
        work_id=work_id,
        title="出错的作品",
        phase="failed",
        progress=0.5,
        error=traceback_like,
    )
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")

    res = client.get(f"/works/{work_id}/status")

    assert res.status_code == 200
    body = res.json()
    assert body["error"] == "解析失败: boom"
    assert "\n" not in body["error"]
    assert "Traceback" not in body["error"]


# ---------------------------------------------------------------------------
# Upload dedup: store.find_completed_work_by_hash
#
# Tested at the store level rather than through POST /works: create_work
# dispatches the real pipeline via BackgroundTasks.add_task, which
# TestClient *does* execute (after the response is returned) but which would
# require either running the full offline pipeline twice (slow, and
# indirectly re-testing orchestrator/parse/extract rather than the dedup
# logic itself) or monkeypatching _launch_pipeline (which would then no
# longer exercise the real create_work + pipeline interaction anyway).
# Exercising find_completed_work_by_hash directly against on-disk
# meta.json/status.json fixtures verifies the actual dedup predicate with no
# extra mocking, and matches the store-level test_get_timeline style already
# used elsewhere in this suite for pipeline-adjacent state.
# ---------------------------------------------------------------------------


def test_find_completed_work_by_hash_matches_done_work(client):
    matching_hash = "a" * 64
    store.write_meta("work-done-match", {"content_sha256": matching_hash})
    _write_status(config.work_dir("work-done-match"), "work-done-match", "done")

    found = store.find_completed_work_by_hash(matching_hash)

    assert found == "work-done-match"


def test_find_completed_work_by_hash_ignores_non_done_work(client):
    same_hash = "b" * 64
    store.write_meta("work-still-processing", {"content_sha256": same_hash})
    _write_status(config.work_dir("work-still-processing"), "work-still-processing", "extracting")

    assert store.find_completed_work_by_hash(same_hash) is None


def test_find_completed_work_by_hash_ignores_other_hashes(client):
    store.write_meta("work-different-hash", {"content_sha256": "c" * 64})
    _write_status(config.work_dir("work-different-hash"), "work-different-hash", "done")

    assert store.find_completed_work_by_hash("d" * 64) is None


def _write_status(wdir, work_id: str, phase: str) -> None:
    from app.models import WorkStatus

    wdir.mkdir(parents=True, exist_ok=True)
    progress = 1.0 if phase == "done" else 0.5
    status = WorkStatus(work_id=work_id, title="测试作品", phase=phase, progress=progress)
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")


# ---------------------------------------------------------------------------
# DELETE /works/{work_id}
# ---------------------------------------------------------------------------


def test_delete_work_removes_directory_and_then_404s(client):
    work_id = "work-to-delete"
    wdir = config.work_dir(work_id)
    _write_status(wdir, work_id, "done")
    assert wdir.exists()

    res = client.delete(f"/works/{work_id}")

    assert res.status_code == 200
    assert res.json() == {"deleted": work_id}
    assert not wdir.exists()

    res2 = client.get(f"/works/{work_id}/status")
    assert res2.status_code == 404


def test_delete_work_404_when_wellformed_id_does_not_exist(client):
    res = client.delete("/works/never-existed-id")
    assert res.status_code == 404
    assert res.json()["detail"] == "作品不存在"


# ---------------------------------------------------------------------------
# Additional happy-path coverage for previously-untested endpoints
# ---------------------------------------------------------------------------


def test_list_works_returns_seeded_work(client):
    _write_status(config.work_dir("work-in-listing"), "work-in-listing", "done")

    res = client.get("/works")

    assert res.status_code == 200
    body = res.json()
    assert any(item["work_id"] == "work-in-listing" for item in body)


def test_list_works_empty_when_no_works(client):
    res = client.get("/works")
    assert res.status_code == 200
    assert res.json() == []


def test_get_graph_html_404_when_missing(client):
    _write_status(config.work_dir("work-no-graph-html"), "work-no-graph-html", "done")
    res = client.get("/works/work-no-graph-html/graph.html")
    assert res.status_code == 404


def test_get_graph_html_returns_file_when_present(client):
    work_id = "work-with-graph-html"
    wdir = config.work_dir(work_id)
    _write_status(wdir, work_id, "done")
    (wdir / "graph.html").write_text("<html>图谱</html>", encoding="utf-8")

    res = client.get(f"/works/{work_id}/graph.html")

    assert res.status_code == 200
    assert "图谱" in res.text


def test_generate_chapter_summary_creates_and_caches(client):
    work_id = "work-chapter-summary"
    wdir = config.work_dir(work_id)
    _write_status(wdir, work_id, "done")
    (wdir / "chapters.json").write_text(
        json.dumps({"ch0001": {"title": "第一章", "text": "从前有座山。"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    res = client.post(f"/works/{work_id}/chapters/ch0001/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["chapter"] == "ch0001"
    assert body["cached"] is False
    assert body["summary"]

    res2 = client.post(f"/works/{work_id}/chapters/ch0001/summary")
    assert res2.status_code == 200
    assert res2.json()["cached"] is True
    assert res2.json()["summary"] == body["summary"]


def test_generate_chapter_summary_404_when_chapter_unknown(client):
    work_id = "work-chapter-summary-missing"
    wdir = config.work_dir(work_id)
    _write_status(wdir, work_id, "done")
    (wdir / "chapters.json").write_text(json.dumps({}), encoding="utf-8")

    res = client.post(f"/works/{work_id}/chapters/ch9999/summary")
    assert res.status_code == 404


def _seed_spine(work_id: str) -> None:
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "spine.json").write_text(
        json.dumps(
            {
                "main_thread": "少年学艺终成大侠",
                "tone": "热血",
                "key_beats": ["初入江湖", "拜师学艺", "终成大侠"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_list_beats_returns_indexed_beats(client):
    work_id = "work-beats"
    _write_status(config.work_dir(work_id), work_id, "done")
    _seed_spine(work_id)

    res = client.get(f"/works/{work_id}/beats")

    assert res.status_code == 200
    body = res.json()
    assert body["main_thread"] == "少年学艺终成大侠"
    assert len(body["beats"]) == 3
    assert body["beats"][0] == {"index": 0, "title": "初入江湖"}


def test_list_beats_404_when_spine_missing(client):
    work_id = "work-beats-missing"
    _write_status(config.work_dir(work_id), work_id, "done")
    res = client.get(f"/works/{work_id}/beats")
    assert res.status_code == 404


def test_generate_beat_story_creates_and_caches(client):
    work_id = "work-beat-story"
    _write_status(config.work_dir(work_id), work_id, "done")
    _seed_spine(work_id)

    res = client.post(f"/works/{work_id}/beats/0/story")
    assert res.status_code == 200
    body = res.json()
    assert body["index"] == 0
    assert body["cached"] is False
    assert body["story"]

    res2 = client.post(f"/works/{work_id}/beats/0/story")
    assert res2.json()["cached"] is True
    assert res2.json()["story"] == body["story"]


def test_generate_beat_story_404_when_index_out_of_range(client):
    work_id = "work-beat-story-oob"
    _write_status(config.work_dir(work_id), work_id, "done")
    _seed_spine(work_id)

    res = client.post(f"/works/{work_id}/beats/99/story")
    assert res.status_code == 404


def _seed_graph_data(work_id: str) -> None:
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "graph.json").write_text(
        json.dumps({"nodes": [{"id": "n1", "label": "甲"}], "edges": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_ask_history_empty_then_populated_after_asking(client):
    work_id = "work-ask"
    _write_status(config.work_dir(work_id), work_id, "done")
    _seed_graph_data(work_id)

    empty_res = client.get(f"/works/{work_id}/ask")
    assert empty_res.status_code == 200
    assert empty_res.json() == {"history": []}

    ask_res = client.post(f"/works/{work_id}/ask", json={"question": "甲是谁？"})
    assert ask_res.status_code == 200
    body = ask_res.json()
    assert body["question"] == "甲是谁？"
    assert body["cached"] is False

    history_res = client.get(f"/works/{work_id}/ask")
    assert history_res.status_code == 200
    assert len(history_res.json()["history"]) == 1

    cached_res = client.post(f"/works/{work_id}/ask", json={"question": "甲是谁？"})
    assert cached_res.status_code == 200
    assert cached_res.json()["cached"] is True


def test_ask_question_400_when_empty(client):
    work_id = "work-ask-empty-question"
    _write_status(config.work_dir(work_id), work_id, "done")
    _seed_graph_data(work_id)

    res = client.post(f"/works/{work_id}/ask", json={"question": "   "})
    assert res.status_code == 400


def test_ask_question_404_when_graph_missing(client):
    work_id = "work-ask-no-graph"
    _write_status(config.work_dir(work_id), work_id, "done")

    res = client.post(f"/works/{work_id}/ask", json={"question": "任何问题"})
    assert res.status_code == 404
