"""FastAPI application entrypoint (design §6)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .config import InvalidWorkIdError
from .routes import router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="30分钟读懂一本书 · 小说知识图谱", version="1.0.0")

# No-auth demo app: allow_origins=["*"] is an accepted tradeoff (any frontend
# may call this API), but allow_credentials must stay False. There is no
# cookie/auth mechanism anywhere in this app, so credentials are never
# actually needed, and combining allow_credentials=True with a wildcard
# origin is a known-dangerous pattern (Starlette echoes back the request's
# Origin header verbatim when credentials are allowed).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(InvalidWorkIdError)
async def _invalid_work_id_handler(request: Request, exc: InvalidWorkIdError) -> JSONResponse:
    # Deliberately vague: don't echo the offending value back to the client.
    return JSONResponse(status_code=400, content={"detail": "invalid work_id"})


@app.on_event("startup")
async def _startup() -> None:
    config.ensure_data_root()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "fake_llm": config.USE_FAKE_LLM}
