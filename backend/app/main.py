"""FastAPI application entrypoint (design §6)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .routes import router

app = FastAPI(title="30分钟读懂一本书 · 小说知识图谱", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
async def _startup() -> None:
    config.ensure_data_root()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "fake_llm": config.USE_FAKE_LLM}
