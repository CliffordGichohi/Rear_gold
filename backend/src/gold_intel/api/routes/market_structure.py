from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import MarketStructureSnapshotResponse
from gold_intel.application.market_structure import calculate_market_structure
from gold_intel.infrastructure.database import get_session

router = APIRouter(prefix="/market-structure", tags=["market-structure"])


@router.get("/snapshot", response_model=MarketStructureSnapshotResponse)
async def structure_snapshot(
    instrument: str = Query(default="XAUUSD", pattern=r"^[A-Z0-9_.-]{2,32}$"),
    provider_code: str | None = Query(
        default=None,
        pattern=r"^[A-Z0-9_]{2,64}$",
    ),
    as_of: datetime | None = None,
    data_mode: Literal["AUTO", "REAL_ONLY", "SYNTHETIC_ONLY"] = "AUTO",
    chart_timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d"] = "5m",
    max_source_bars: int = Query(default=60_000, ge=1_000, le=100_000),
    session: AsyncSession = Depends(get_session),
) -> MarketStructureSnapshotResponse:
    if as_of is not None and as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone.")
    result = await calculate_market_structure(
        session,
        instrument=instrument,
        provider_code=provider_code,
        as_of=as_of,
        data_mode=data_mode,
        chart_timeframe=chart_timeframe,
        max_source_bars=max_source_bars,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No eligible complete one-minute bars are available for the requested "
                "instrument, provider, data mode, and point-in-time cutoff."
            ),
        )
    return MarketStructureSnapshotResponse.model_validate(result)
