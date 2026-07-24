from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import (
    IntelligenceCalculationRequest,
    IntelligenceSnapshotResponse,
    SignalResponse,
)
from gold_intel.api.serializers import serialize_signal, serialize_snapshot
from gold_intel.application.intelligence import (
    calculate_intelligence,
    latest_snapshot,
    snapshot_signals,
)
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import ScoreSnapshot

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.post(
    "/calculations",
    response_model=IntelligenceSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
    description=(
        "Legacy vertical-slice scorer. Use POST /decisions/snapshots for the "
        "canonical seven-layer reference-book decision."
    ),
)
async def calculate(
    request: IntelligenceCalculationRequest,
    session: AsyncSession = Depends(get_session),
) -> IntelligenceSnapshotResponse:
    if request.as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone.")
    async with session.begin():
        snapshot = await calculate_intelligence(
            session,
            instrument_code=request.instrument,
            as_of=request.as_of,
        )
    return serialize_snapshot(snapshot)


@router.get(
    "/snapshots/latest",
    response_model=IntelligenceSnapshotResponse,
    deprecated=True,
    description="Legacy snapshot. Use GET /decisions/snapshots/latest.",
)
async def get_latest(
    instrument: str = "XAUUSD", session: AsyncSession = Depends(get_session)
) -> IntelligenceSnapshotResponse:
    snapshot = await latest_snapshot(session, instrument_code=instrument)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No intelligence snapshot is available.")
    return serialize_snapshot(snapshot)


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=IntelligenceSnapshotResponse,
    deprecated=True,
    description="Legacy snapshot. Use GET /decisions/snapshots/{snapshot_id}.",
)
async def get_snapshot(
    snapshot_id: UUID, session: AsyncSession = Depends(get_session)
) -> IntelligenceSnapshotResponse:
    snapshot = await session.get(ScoreSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Intelligence snapshot not found.")
    return serialize_snapshot(snapshot)


@router.get(
    "/snapshots/{snapshot_id}/signals",
    response_model=list[SignalResponse],
    deprecated=True,
    description="Legacy signal surface retained for compatibility and audit history.",
)
async def get_signals(
    snapshot_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[SignalResponse]:
    snapshot = await session.get(ScoreSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Intelligence snapshot not found.")
    return [serialize_signal(signal) for signal in await snapshot_signals(session, snapshot)]
