from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import (
    DecisionCalculationRequest,
    DecisionSnapshotResponse,
)
from gold_intel.application.decisions import (
    calculate_and_store_decision,
    decision_snapshot_to_dict,
)
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import DecisionSnapshot

router = APIRouter(prefix="/decisions", tags=["seven-layer decisions"])


@router.post(
    "/snapshots",
    response_model=DecisionSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def calculate_snapshot(
    request: DecisionCalculationRequest,
    session: AsyncSession = Depends(get_session),
) -> DecisionSnapshotResponse:
    if request.as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    async with session.begin():
        snapshot, _, _ = await calculate_and_store_decision(
            session,
            instrument=request.instrument,
            provider_code=request.provider_code,
            as_of=request.as_of,
            data_mode=request.data_mode,
            max_source_bars=request.max_source_bars,
        )
    return DecisionSnapshotResponse.model_validate(
        decision_snapshot_to_dict(snapshot)
    )


@router.get("/snapshots/latest", response_model=DecisionSnapshotResponse)
async def latest_snapshot(
    instrument: str = Query(default="XAUUSD", pattern=r"^[A-Z0-9_.-]{2,32}$"),
    session: AsyncSession = Depends(get_session),
) -> DecisionSnapshotResponse:
    snapshot = await session.scalar(
        select(DecisionSnapshot)
        .where(DecisionSnapshot.instrument_code == instrument)
        .order_by(DecisionSnapshot.as_of.desc(), DecisionSnapshot.created_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No unified seven-layer decision snapshot is available.",
        )
    return DecisionSnapshotResponse.model_validate(
        decision_snapshot_to_dict(snapshot)
    )


@router.get("/snapshots/{snapshot_id}", response_model=DecisionSnapshotResponse)
async def get_snapshot(
    snapshot_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DecisionSnapshotResponse:
    snapshot = await session.get(DecisionSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Decision snapshot not found.")
    return DecisionSnapshotResponse.model_validate(
        decision_snapshot_to_dict(snapshot)
    )
