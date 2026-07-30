# AGENTS.md

Demo app "30分钟读懂一本书": upload a novel (`.txt`/`.epub`) → async pipeline →
knowledge graph + layered summaries + Q&A. FastAPI backend, React/Vite frontend.

## Layout

- `backend/` — FastAPI app + processing pipeline (Python 3.11+, package `app`)
- `frontend/` — React 18 + Vite 5 + vis-network SPA
- `data/works/` — per-work runtime output (gitignored)
- `docs/superpowers/specs/2026-07-27-novel-knowledge-graph-design.md` — authoritative
  design spec (Chinese). Code docstrings reference its section numbers (§1–§9); read it
  before non-trivial pipeline changes.

## Commands

Backend venv is `backend/.venv/` (gitignored) and normally already active on PATH.

```bash
# Tests — MUST run from backend/ with PYTHONPATH set, else ModuleNotFoundError: 'app'
cd backend && PYTHONPATH=. pytest -q

# Run backend API (from backend/)
uvicorn app.main:app --reload      # serves on :8000

# Frontend (from frontend/)
npm install
npm run dev                        # Vite on :5173, proxies /api/* -> :8000
npm run build
```

There is no lint/format/typecheck config, no CI, no Makefile.

## Gotchas

- **Tests need `PYTHONPATH=.` from `backend/`.** The `app` package is not pip-installed
  and there is no pytest rootdir/pythonpath config; tests import `from app...`. Running
  `pytest` from repo root or from `backend/` without `PYTHONPATH=.` fails.
- **Offline mode:** set `NOVEL_KG_USE_FAKE_LLM=1` to use the deterministic offline
  extractor/summarizer (no AWS needed). Tests rely on this. Real extraction calls AWS
  Bedrock via `strands` and needs valid credentials.
- **Config via env, prefix `NOVEL_KG_`.** `backend/config.py` auto-loads `backend/.env`
  on import (existing env vars win over the file). `.env` holds proxy/region config
  (`HTTPS_PROXY`, `NOVEL_KG_BEDROCK_REGION`, model id, `AWS_PROFILE`) — gitignored.
- **The pipeline never raises.** `app/pipeline/orchestrator.py:run_pipeline` records
  failures into `status.json` (phase=`failed`). Check that file, not exceptions, to debug
  a failed job. Phases: queued→parsing→extracting→building→summarizing→done|failed.
- **8 fixed relation categories must stay in sync.** `RelationCategory` in
  `backend/app/models.py` (家人/爱人/朋友/敌人/师徒/主仆/同盟/其他) and
  `CATEGORY_COLORS`/`CATEGORY_ORDER` in `frontend/src/constants.js` mirror each other.
  Only 师徒 and 主仆 (`DIRECTED_CATEGORIES`) draw arrows. `PHASE_*` in constants.js
  likewise mirrors the backend `Phase` enum.
- **graphify node ids must be lowercase `[a-z0-9_]`.** CJK names slugify to empty, so
  `app/pipeline/graph.py:_slug()` falls back to deterministic `n{salt}` ids and keeps
  id↔label maps. Don't assume node id == character name.
- Ignore any `v/` or `backend/v/` path an `ls` tool may show — it's a tooling artifact;
  the real venv is `backend/.venv/`.
