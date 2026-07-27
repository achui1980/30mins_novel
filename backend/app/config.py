"""Application configuration.

All settings can be overridden via environment variables. Defaults are chosen so
the app runs locally against a filesystem store and Amazon Bedrock.
"""

from __future__ import annotations

import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load key=value pairs from backend/.env into os.environ.

    A tiny, dependency-free parser. Existing environment variables always win,
    so an explicit `NOVEL_KG_...=` on the command line overrides the file.
    Supports `KEY=VALUE`, `#` comments, blank lines, and optional surrounding
    quotes around the value.
    """
    env_path = _BACKEND_DIR / ".env"
    try:
        raw = env_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _env(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val is not None and val != "" else default


# --- Storage ---------------------------------------------------------------
# data/works/{work_id}/ holds raw.txt, graph.json, graph.html, summary.json, status.json
_REPO_ROOT = _BACKEND_DIR.parent

DATA_ROOT = Path(_env("NOVEL_KG_DATA_ROOT", str(_REPO_ROOT / "data" / "works")))

# --- Upload limits ---------------------------------------------------------
ALLOWED_EXTENSIONS = {".txt", ".epub"}
MAX_UPLOAD_BYTES = int(_env("NOVEL_KG_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))  # 25 MB

# --- Chunking --------------------------------------------------------------
# Rough token target per block. We approximate tokens; see pipeline.chunk.
CHUNK_TARGET_TOKENS = int(_env("NOVEL_KG_CHUNK_TARGET_TOKENS", "3000"))
CHUNK_MAX_TOKENS = int(_env("NOVEL_KG_CHUNK_MAX_TOKENS", "4000"))

# --- Extraction concurrency / retries --------------------------------------
EXTRACT_CONCURRENCY = int(_env("NOVEL_KG_EXTRACT_CONCURRENCY", "5"))
EXTRACT_MAX_RETRIES = int(_env("NOVEL_KG_EXTRACT_MAX_RETRIES", "4"))
EXTRACT_BACKOFF_BASE = float(_env("NOVEL_KG_EXTRACT_BACKOFF_BASE", "1.5"))

# --- Bedrock / Strands -----------------------------------------------------
BEDROCK_MODEL_ID = _env(
    "NOVEL_KG_BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-6",
)
BEDROCK_REGION = _env("NOVEL_KG_BEDROCK_REGION", _env("AWS_REGION", "us-east-1"))

# When true, the pipeline uses a deterministic fake extractor/summarizer instead
# of calling Bedrock. Used by tests and offline demos.
USE_FAKE_LLM = _env("NOVEL_KG_USE_FAKE_LLM", "0") in {"1", "true", "True", "yes"}


def work_dir(work_id: str) -> Path:
    return DATA_ROOT / work_id


def ensure_data_root() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
