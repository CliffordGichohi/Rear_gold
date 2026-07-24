from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import text

from gold_intel.config import get_settings
from gold_intel.infrastructure.database import engine

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    checks: dict[str, str] = Field(default_factory=dict)


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok", service="api")


@router.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    settings = get_settings()
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = type(exc).__name__

    redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = type(exc).__name__
    finally:
        await redis.aclose()

    if any(value != "ok" for value in checks.values()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DEPENDENCY_NOT_READY", "checks": checks},
        )
    return HealthResponse(status="ok", service="api", checks=checks)
