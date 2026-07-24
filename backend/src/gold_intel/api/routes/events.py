from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import (
    EconomicEventBundleRequest,
    EconomicEventBundleResponse,
    EconomicEventResponse,
    EconomicSurpriseBatchResponse,
    EconomicSurpriseCalculationRequest,
    EconomicSurpriseResponse,
)
from gold_intel.application.economic_events import (
    calculate_and_store_economic_surprises,
    ingest_economic_event_bundle,
    load_event_surprise_context,
    surprise_to_dict,
)
from gold_intel.config import get_settings
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import (
    EconomicEvent,
    EconomicRelease,
    EconomicSurprise,
    ForecastSnapshot,
)

router = APIRouter(prefix="/events", tags=["events"])
settings = get_settings()


@router.post(
    "/bundles",
    response_model=EconomicEventBundleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_event_bundle(
    request: EconomicEventBundleRequest,
    session: AsyncSession = Depends(get_session),
) -> EconomicEventBundleResponse:
    try:
        async with session.begin():
            result = await ingest_economic_event_bundle(
                session,
                payload=request.model_dump(mode="python"),
                raw_store_root=Path(settings.raw_store_path),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EconomicEventBundleResponse(
        batch_id=result.batch.id,
        provider_code=result.batch.provider_code,
        dataset_code=result.batch.dataset_code,
        content_hash=result.batch.content_hash,
        duplicate=result.duplicate,
        event_count=result.event_count,
        forecast_count=result.forecast_count,
        release_count=result.release_count,
        surprise_count=len(result.surprise_result.models),
        surprise_exclusions=list(result.surprise_result.batch.exclusions),
        is_synthetic=result.batch.is_synthetic,
        ingested_at=result.batch.ingested_at,
    )


@router.post(
    "/surprises/calculate",
    response_model=EconomicSurpriseBatchResponse,
)
async def calculate_surprises(
    request: EconomicSurpriseCalculationRequest,
    session: AsyncSession = Depends(get_session),
) -> EconomicSurpriseBatchResponse:
    async with session.begin():
        result = await calculate_and_store_economic_surprises(
            session,
            as_of=request.as_of,
            data_mode=request.data_mode,
        )
    context = await load_event_surprise_context(session, list(result.models))
    responses = [
        EconomicSurpriseResponse.model_validate(surprise_to_dict(model, context[model.event_id]))
        for model in result.models
    ]
    return EconomicSurpriseBatchResponse(
        as_of=request.as_of,
        data_mode=result.data_mode,
        calculated_count=len(result.batch.calculations),
        inserted_count=result.inserted_count,
        exclusions=list(result.batch.exclusions),
        surprises=responses,
    )


@router.get("/surprises", response_model=list[EconomicSurpriseResponse])
async def list_surprises(
    as_of: datetime | None = None,
    data_mode: str = Query(
        default="REAL_ONLY",
        pattern=r"^(REAL_ONLY|SYNTHETIC_ONLY)$",
    ),
    component_code: str | None = Query(
        default=None,
        pattern=r"^[A-Z0-9_]{2,96}$",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[EconomicSurpriseResponse]:
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    synthetic = data_mode == "SYNTHETIC_ONLY"
    query = (
        select(EconomicSurprise)
        .where(
            EconomicSurprise.available_at <= cutoff,
            EconomicSurprise.is_synthetic.is_(synthetic),
        )
        .order_by(
            EconomicSurprise.released_at.desc(),
            EconomicSurprise.history_count.desc(),
            EconomicSurprise.created_at.desc(),
        )
        .limit(limit * 3)
    )
    if component_code is not None:
        query = query.where(EconomicSurprise.component_code == component_code)
    rows = list((await session.scalars(query)).all())
    canonical: dict[Any, EconomicSurprise] = {}
    for row in rows:
        canonical.setdefault(row.release_id, row)
    selected = list(canonical.values())[:limit]
    context = await load_event_surprise_context(session, selected)
    return [
        EconomicSurpriseResponse.model_validate(surprise_to_dict(model, context[model.event_id]))
        for model in selected
    ]


@router.get("", response_model=list[EconomicEventResponse])
async def list_events(
    as_of: datetime | None = None,
    data_mode: str = Query(
        default="REAL_ONLY",
        pattern=r"^(REAL_ONLY|SYNTHETIC_ONLY)$",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[EconomicEventResponse]:
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    synthetic = data_mode == "SYNTHETIC_ONLY"
    rows = list(
        (
            await session.scalars(
                select(EconomicEvent)
                .where(
                    EconomicEvent.available_at <= cutoff,
                    EconomicEvent.is_synthetic.is_(synthetic),
                )
                .order_by(
                    EconomicEvent.available_at.desc(),
                    EconomicEvent.scheduled_at.desc(),
                )
                .limit(limit * 4)
            )
        ).all()
    )
    canonical: dict[tuple[str, str], EconomicEvent] = {}
    for row in rows:
        canonical.setdefault((row.provider_code, row.source_event_key), row)
    events = sorted(
        canonical.values(),
        key=lambda event: event.scheduled_at,
        reverse=True,
    )[:limit]
    event_ids = [event.id for event in events]
    event_keys = {(event.event_code, event.scheduled_at) for event in events}
    releases = (
        list(
            (
                await session.scalars(
                    select(EconomicRelease)
                    .where(
                        EconomicRelease.event_id.in_(event_ids),
                        EconomicRelease.available_at <= cutoff,
                    )
                    .order_by(EconomicRelease.available_at)
                )
            ).all()
        )
        if event_ids
        else []
    )
    forecasts = (
        list(
            (
                await session.scalars(
                    select(ForecastSnapshot)
                    .where(
                        ForecastSnapshot.available_at <= cutoff,
                        ForecastSnapshot.is_synthetic.is_(synthetic),
                    )
                    .order_by(ForecastSnapshot.available_at)
                )
            ).all()
        )
        if event_keys
        else []
    )
    releases_by_event: dict[Any, list[EconomicRelease]] = {}
    for release in releases:
        releases_by_event.setdefault(release.event_id, []).append(release)
    forecasts_by_event: dict[tuple[str, datetime], list[ForecastSnapshot]] = {}
    for forecast in forecasts:
        key = (forecast.event_code, forecast.scheduled_at)
        if key in event_keys:
            forecasts_by_event.setdefault(key, []).append(forecast)
    return [
        EconomicEventResponse(
            id=event.id,
            event_code=event.event_code,
            name=event.name,
            event_type=event.event_type,
            scheduled_at=event.scheduled_at,
            released_at=event.released_at,
            importance=event.importance,
            status=event.status,
            provider_code=event.provider_code,
            source_event_key=event.source_event_key,
            available_at=event.available_at,
            is_synthetic=event.is_synthetic,
            forecasts=[
                {
                    "id": str(forecast.id),
                    "component_code": forecast.component_code,
                    "forecast_value": float(forecast.forecast_value),
                    "unit": forecast.unit,
                    "forecast_as_of": forecast.forecast_as_of.isoformat(),
                    "available_at": forecast.available_at.isoformat(),
                    "provider_code": forecast.provider_code,
                    "vintage": forecast.vintage,
                }
                for forecast in forecasts_by_event.get(
                    (event.event_code, event.scheduled_at),
                    [],
                )
            ],
            releases=[
                {
                    "id": str(release.id),
                    "component_code": release.component_code,
                    "observation_period": release.observation_period.isoformat(),
                    "actual_value": float(release.actual_value),
                    "previous_value": (
                        float(release.previous_value)
                        if release.previous_value is not None
                        else None
                    ),
                    "revised_previous_value": (
                        float(release.revised_previous_value)
                        if release.revised_previous_value is not None
                        else None
                    ),
                    "unit": release.unit,
                    "released_at": release.released_at.isoformat(),
                    "available_at": release.available_at.isoformat(),
                    "is_revision": release.is_revision,
                    "vintage": release.vintage,
                }
                for release in releases_by_event.get(event.id, [])
            ],
        )
        for event in events
    ]
