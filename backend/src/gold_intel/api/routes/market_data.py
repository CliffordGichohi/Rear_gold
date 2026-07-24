from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import ObservationResponse, PriceBarResponse
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import Observation, PriceBar
from gold_intel.providers.public_data import FRED_MARKET_SERIES

router = APIRouter(prefix="/market-data", tags=["market-data"])
PUBLIC_OBSERVATION_CODES = frozenset(
    specification.internal_code for specification in FRED_MARKET_SERIES
)
DEFAULT_CROSS_MARKET_CODES = (
    "US_TREASURY_2Y",
    "US_TREASURY_10Y",
    "US_REAL_YIELD_10Y",
    "US_BREAKEVEN_10Y",
    "USD_BROAD_NOMINAL",
    "US_EQUITY_PROXY",
    "US_VOLATILITY_INDEX",
)


@router.get("/bars", response_model=list[PriceBarResponse])
async def bars(
    instrument: str = "XAUUSD",
    timeframe: str = "1m",
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
    limit: int = Query(500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> list[PriceBarResponse]:
    if as_of is not None and as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone.")
    query = select(PriceBar).where(
        PriceBar.instrument_code == instrument,
        PriceBar.timeframe == timeframe,
    )
    if start is not None:
        query = query.where(PriceBar.open_time >= start)
    if end is not None:
        query = query.where(PriceBar.open_time < end)
    if as_of is not None:
        query = query.where(PriceBar.available_at <= as_of, PriceBar.close_time <= as_of)
    rows = list((await session.scalars(query.order_by(PriceBar.open_time).limit(limit))).all())
    return [
        PriceBarResponse(
            id=row.id,
            instrument=row.instrument_code,
            provider=row.provider_code,
            timeframe=row.timeframe,
            open_time=row.open_time,
            close_time=row.close_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume) if row.volume is not None else None,
            volume_type=row.volume_type,
            spread_points=row.spread_points,
            spread_price=(
                float(row.spread_price) if row.spread_price is not None else None
            ),
            available_at=row.available_at,
            is_complete=row.is_complete,
            is_synthetic=row.is_synthetic,
        )
        for row in rows
    ]


@router.get("/observations", response_model=list[ObservationResponse])
async def observations(
    series: str = Query(default=",".join(DEFAULT_CROSS_MARKET_CODES)),
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
    limit_per_series: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> list[ObservationResponse]:
    """Return canonical point-in-time public observations for synchronized research.

    Later revisions replace earlier vintages only when they were available by the
    requested ``as_of`` clock. The raw historical versions remain immutable.
    """

    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone.")
    end_at = end or cutoff
    start_at = start or end_at - timedelta(days=180)
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail="start and end must include a timezone.",
        )
    if start_at >= end_at:
        raise HTTPException(status_code=422, detail="start must precede end.")
    if end_at - start_at > timedelta(days=3650):
        raise HTTPException(status_code=422, detail="range is limited to ten years.")

    requested = tuple(
        dict.fromkeys(code.strip().upper() for code in series.split(",") if code.strip())
    )
    if not requested:
        raise HTTPException(status_code=422, detail="at least one series is required.")
    unsupported = sorted(set(requested) - PUBLIC_OBSERVATION_CODES)
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported public series: {', '.join(unsupported)}",
        )

    rows = list(
        (
            await session.scalars(
                select(Observation)
                .where(
                    Observation.series_code.in_(requested),
                    Observation.observation_time >= start_at,
                    Observation.observation_time < end_at,
                    Observation.observation_time <= cutoff,
                    Observation.available_at <= cutoff,
                    Observation.is_synthetic.is_(False),
                )
                .order_by(
                    Observation.series_code,
                    Observation.observation_time,
                    Observation.available_at,
                    Observation.ingested_at,
                )
            )
        ).all()
    )
    selected = _select_canonical_observations(
        rows,
        requested=requested,
        limit_per_series=limit_per_series,
    )

    return [
        ObservationResponse(
            series_code=row.series_code,
            observation_time=row.observation_time,
            value=float(row.value),
            unit=row.unit,
            available_at=row.available_at,
            vintage=row.vintage,
            is_revision=row.is_revision,
            source_record_key=row.source_record_key,
        )
        for row in selected
    ]


def _select_canonical_observations(
    rows: list[Observation],
    *,
    requested: tuple[str, ...],
    limit_per_series: int,
) -> list[Observation]:
    canonical: dict[tuple[str, datetime], Observation] = {}
    for row in sorted(
        rows,
        key=lambda item: (
            item.series_code,
            item.observation_time,
            item.available_at,
        ),
    ):
        canonical[(row.series_code, row.observation_time)] = row

    by_series: dict[str, list[Observation]] = {}
    for row in canonical.values():
        by_series.setdefault(row.series_code, []).append(row)

    selected: list[Observation] = []
    for code in requested:
        values = sorted(
            by_series.get(code, []),
            key=lambda row: row.observation_time,
        )
        selected.extend(values[-limit_per_series:])
    selected.sort(key=lambda row: (row.observation_time, row.series_code))
    return selected
