from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.session_edge_schemas import (
    SessionEdgeComparisonRequest,
    SessionEdgeComparisonResponse,
    SessionEdgeStudyRequest,
    SessionEdgeStudyRunResponse,
    SessionOpportunityResponse,
)
from gold_intel.application.session_edges import (
    compare_session_edge_studies,
    execute_session_edge_study,
    session_edge_run_to_dict,
    session_opportunity_to_dict,
)
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import (
    SessionEdgeStudyRun,
    SessionOpportunity,
)

router = APIRouter(
    prefix="/session-edge-studies",
    tags=["session edge studies"],
)


@router.post(
    "/runs",
    response_model=SessionEdgeStudyRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session_edge_study(
    request: SessionEdgeStudyRequest,
    detail_limit: int = Query(default=50, ge=0, le=500),
    session: AsyncSession = Depends(get_session),
) -> SessionEdgeStudyRunResponse:
    try:
        async with session.begin():
            run, opportunities = await execute_session_edge_study(
                session,
                instrument=request.instrument,
                provider_code=request.provider_code,
                start=request.start,
                end=request.end,
                include_fundamentals=request.include_fundamentals,
                config=request.config.to_domain(),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    details = opportunities[-detail_limit:] if detail_limit else []
    return SessionEdgeStudyRunResponse.model_validate(
        session_edge_run_to_dict(run, details)
    )


@router.post(
    "/comparisons",
    response_model=SessionEdgeComparisonResponse,
)
async def compare_session_edge_runs(
    request: SessionEdgeComparisonRequest,
    session: AsyncSession = Depends(get_session),
) -> SessionEdgeComparisonResponse:
    try:
        result = await compare_session_edge_studies(
            session,
            run_ids=request.run_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SessionEdgeComparisonResponse.model_validate(result)


@router.get("/runs", response_model=list[SessionEdgeStudyRunResponse])
async def list_session_edge_studies(
    limit: int = Query(default=10, ge=1, le=50),
    detail_limit: int = Query(default=0, ge=0, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[SessionEdgeStudyRunResponse]:
    runs = list(
        (
            await session.scalars(
                select(SessionEdgeStudyRun)
                .order_by(SessionEdgeStudyRun.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    output: list[SessionEdgeStudyRunResponse] = []
    for run in runs:
        opportunities = (
            list(
                (
                    await session.scalars(
                        select(SessionOpportunity)
                        .where(SessionOpportunity.run_id == run.id)
                        .order_by(SessionOpportunity.session_date.desc())
                        .limit(detail_limit)
                    )
                ).all()
            )
            if detail_limit
            else []
        )
        output.append(
            SessionEdgeStudyRunResponse.model_validate(session_edge_run_to_dict(run, opportunities))
        )
    return output


@router.get(
    "/runs/{run_id}",
    response_model=SessionEdgeStudyRunResponse,
)
async def get_session_edge_study(
    run_id: UUID,
    detail_limit: int = Query(default=100, ge=0, le=500),
    session: AsyncSession = Depends(get_session),
) -> SessionEdgeStudyRunResponse:
    run = await session.get(SessionEdgeStudyRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Session-edge study run not found.")
    opportunities = (
        list(
            (
                await session.scalars(
                    select(SessionOpportunity)
                    .where(SessionOpportunity.run_id == run.id)
                    .order_by(SessionOpportunity.session_date.desc())
                    .limit(detail_limit)
                )
            ).all()
        )
        if detail_limit
        else []
    )
    return SessionEdgeStudyRunResponse.model_validate(session_edge_run_to_dict(run, opportunities))


@router.get(
    "/runs/{run_id}/opportunities",
    response_model=list[SessionOpportunityResponse],
)
async def list_session_opportunities(
    run_id: UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    bias_alignment: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[SessionOpportunityResponse]:
    if await session.get(SessionEdgeStudyRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Session-edge study run not found.")
    query = select(SessionOpportunity).where(SessionOpportunity.run_id == run_id)
    if status_filter is not None:
        query = query.where(SessionOpportunity.status == status_filter)
    if bias_alignment is not None:
        query = query.where(SessionOpportunity.bias_alignment == bias_alignment)
    rows = list(
        (
            await session.scalars(
                query.order_by(SessionOpportunity.session_date).offset(offset).limit(limit)
            )
        ).all()
    )
    return [
        SessionOpportunityResponse.model_validate(session_opportunity_to_dict(item))
        for item in rows
    ]
