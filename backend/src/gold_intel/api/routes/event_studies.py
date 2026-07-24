from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import EventStudyRunRequest, EventStudyRunResponse
from gold_intel.application.event_studies import (
    event_study_to_dict,
    execute_event_study,
)
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import EventStudyRun

router = APIRouter(prefix="/event-studies", tags=["event studies"])


@router.post(
    "/runs",
    response_model=EventStudyRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_event_study(
    request: EventStudyRunRequest,
    session: AsyncSession = Depends(get_session),
) -> EventStudyRunResponse:
    try:
        async with session.begin():
            run = await execute_event_study(
                session,
                instrument=request.instrument,
                provider_code=request.provider_code,
                start=request.start,
                end=request.end,
                study_as_of=request.study_as_of,
                data_mode=request.data_mode,
                minimum_importance=request.minimum_importance,
                component_codes=request.component_codes,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EventStudyRunResponse.model_validate(event_study_to_dict(run))


@router.get("/runs", response_model=list[EventStudyRunResponse])
async def list_event_studies(
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> list[EventStudyRunResponse]:
    rows = list(
        (
            await session.scalars(
                select(EventStudyRun).order_by(EventStudyRun.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [EventStudyRunResponse.model_validate(event_study_to_dict(row)) for row in rows]


@router.get("/runs/{run_id}", response_model=EventStudyRunResponse)
async def get_event_study(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> EventStudyRunResponse:
    run = await session.get(EventStudyRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Event-study run not found.")
    return EventStudyRunResponse.model_validate(event_study_to_dict(run))
