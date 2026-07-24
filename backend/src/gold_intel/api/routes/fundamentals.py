from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import (
    FundamentalCalculationRequest,
    FundamentalSnapshotResponse,
)
from gold_intel.application.fundamentals import (
    calculate_and_store_fundamental_snapshot,
    snapshot_to_dict,
)
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import FundamentalSnapshot

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])


@router.post(
    "/snapshots",
    response_model=FundamentalSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def calculate_snapshot(
    request: FundamentalCalculationRequest,
    session: AsyncSession = Depends(get_session),
) -> FundamentalSnapshotResponse:
    if request.as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    async with session.begin():
        snapshot, _, _ = await calculate_and_store_fundamental_snapshot(
            session,
            instrument=request.instrument,
            as_of=request.as_of,
        )
    return FundamentalSnapshotResponse.model_validate(snapshot_to_dict(snapshot))


@router.get("/snapshots/latest", response_model=FundamentalSnapshotResponse)
async def latest_snapshot(
    instrument: str = Query(default="XAUUSD", pattern=r"^[A-Z0-9_.-]{2,32}$"),
    session: AsyncSession = Depends(get_session),
) -> FundamentalSnapshotResponse:
    snapshot = await session.scalar(
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.instrument_code == instrument)
        .order_by(FundamentalSnapshot.as_of.desc(), FundamentalSnapshot.created_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No fundamental snapshot is available.")
    return FundamentalSnapshotResponse.model_validate(snapshot_to_dict(snapshot))


@router.get("/snapshots/{snapshot_id}", response_model=FundamentalSnapshotResponse)
async def get_snapshot(
    snapshot_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> FundamentalSnapshotResponse:
    snapshot = await session.get(FundamentalSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Fundamental snapshot not found.")
    return FundamentalSnapshotResponse.model_validate(snapshot_to_dict(snapshot))
