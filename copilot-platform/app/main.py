"""FastAPI app — the base copilot chat shell (Part A / Part C step 1)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .config import get_settings
from .db import init_db
from .routers import completions, conversations
from .ui import PAGE


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Copilot Platform — chat shell", version="0.1.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.copilot_cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    # SSE streaming works through CORS; we don't rely on cookies (dev principal),
    # so credentials stay off and explicit origins are used.
    expose_headers=["X-Run-Id"],
)

app.include_router(conversations.router)
app.include_router(completions.router)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return PAGE


@app.get("/health")
async def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "copilot_ws_enabled": s.copilot_ws_enabled,
        "model": s.copilot_model,
        "fake_llm": s.copilot_fake_llm or not bool(s.anthropic_api_key),
    }
