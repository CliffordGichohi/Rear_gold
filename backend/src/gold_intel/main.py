from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from gold_intel import __version__
from gold_intel.api.routes import (
    backtests,
    blind_replay,
    blind_replay_v2,
    blind_replay_v3,
    codex_operator_replay,
    coherent_auction_validation,
    data_health,
    decisions,
    event_studies,
    events,
    expectations,
    factors,
    fundamentals,
    health,
    ingestions,
    intelligence,
    market_data,
    market_structure,
    matched_human_replay,
    providers,
    session_edge_strategies,
    session_edges,
)
from gold_intel.config import get_settings
from gold_intel.logging import configure_logging

configure_logging()
logger = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Path(settings.raw_store_path).mkdir(parents=True, exist_ok=True)
    logger.info("application_started", version=__version__, environment=settings.app_env)
    yield
    logger.info("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info("request_completed", method=request.method, status_code=response.status_code)
    return response


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": __version__,
        "docs": "/docs",
    }


app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(providers.router, prefix=settings.api_prefix)
app.include_router(ingestions.router, prefix=settings.api_prefix)
app.include_router(market_data.router, prefix=settings.api_prefix)
app.include_router(market_structure.router, prefix=settings.api_prefix)
app.include_router(decisions.router, prefix=settings.api_prefix)
app.include_router(intelligence.router, prefix=settings.api_prefix)
app.include_router(data_health.router, prefix=settings.api_prefix)
app.include_router(backtests.router, prefix=settings.api_prefix)
app.include_router(blind_replay.router, prefix=settings.api_prefix)
app.include_router(blind_replay_v2.router, prefix=settings.api_prefix)
app.include_router(blind_replay_v3.router, prefix=settings.api_prefix)
app.include_router(codex_operator_replay.router, prefix=settings.api_prefix)
app.include_router(coherent_auction_validation.router, prefix=settings.api_prefix)
app.include_router(matched_human_replay.router, prefix=settings.api_prefix)
app.include_router(factors.router, prefix=settings.api_prefix)
app.include_router(fundamentals.router, prefix=settings.api_prefix)
app.include_router(events.router, prefix=settings.api_prefix)
app.include_router(event_studies.router, prefix=settings.api_prefix)
app.include_router(session_edges.router, prefix=settings.api_prefix)
app.include_router(session_edge_strategies.router, prefix=settings.api_prefix)
app.include_router(expectations.router, prefix=settings.api_prefix)
