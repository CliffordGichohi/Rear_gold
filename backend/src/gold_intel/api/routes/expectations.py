from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import (
    PolicyPathBundleRequest,
    PolicyPathBundleResponse,
    PolicyPathResponse,
    QuarterlyPolicyExpectationResponse,
)
from gold_intel.application.atlanta_fed_mpt import (
    policy_expectation_window_to_dict,
)
from gold_intel.application.policy_paths import (
    ingest_policy_path_bundle,
    policy_path_rows_to_dict,
)
from gold_intel.config import get_settings
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import PolicyExpectationWindow, PolicyPathPoint

router = APIRouter(prefix="/expectations", tags=["expectations"])
settings = get_settings()


@router.post(
    "/policy-paths/bundles",
    response_model=PolicyPathBundleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_policy_path_bundle(
    request: PolicyPathBundleRequest,
    session: AsyncSession = Depends(get_session),
) -> PolicyPathBundleResponse:
    async with session.begin():
        result = await ingest_policy_path_bundle(
            session,
            payload=request.model_dump(mode="python"),
            raw_store_root=Path(settings.raw_store_path),
        )
    return PolicyPathBundleResponse(
        batch_id=result.batch.id,
        provider_code=result.batch.provider_code,
        dataset_code=result.batch.dataset_code,
        content_hash=result.batch.content_hash,
        duplicate=result.duplicate,
        snapshot_count=result.snapshot_count,
        point_count=result.point_count,
        is_synthetic=result.batch.is_synthetic,
        ingested_at=result.batch.ingested_at,
    )


@router.get("/policy-paths", response_model=list[PolicyPathResponse])
async def list_policy_paths(
    as_of: datetime | None = None,
    data_mode: str = Query(
        default="REAL_ONLY",
        pattern=r"^(REAL_ONLY|SYNTHETIC_ONLY)$",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[PolicyPathResponse]:
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    synthetic = data_mode == "SYNTHETIC_ONLY"
    rows = list(
        (
            await session.scalars(
                select(PolicyPathPoint)
                .where(
                    PolicyPathPoint.available_at <= cutoff,
                    PolicyPathPoint.is_synthetic.is_(synthetic),
                )
                .order_by(
                    PolicyPathPoint.snapshot_as_of.desc(),
                    PolicyPathPoint.meeting_date,
                    PolicyPathPoint.outcome_basis_points,
                )
                .limit(limit * 500)
            )
        ).all()
    )
    snapshots = policy_path_rows_to_dict(rows)[:limit]
    return [PolicyPathResponse.model_validate(snapshot) for snapshot in snapshots]


@router.get(
    "/quarterly-sofr-distributions",
    response_model=list[QuarterlyPolicyExpectationResponse],
)
async def list_quarterly_sofr_distributions(
    as_of: datetime | None = None,
    observation_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[QuarterlyPolicyExpectationResponse]:
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    query = select(PolicyExpectationWindow).where(
        PolicyExpectationWindow.available_at <= cutoff,
        PolicyExpectationWindow.snapshot_as_of <= cutoff,
        PolicyExpectationWindow.is_synthetic.is_(False),
    )
    if observation_date is not None:
        query = query.where(PolicyExpectationWindow.observation_date == observation_date)
    rows = list(
        (
            await session.scalars(
                query.order_by(
                    PolicyExpectationWindow.observation_date.desc(),
                    PolicyExpectationWindow.reference_start,
                ).limit(limit)
            )
        ).all()
    )
    return [
        QuarterlyPolicyExpectationResponse.model_validate(policy_expectation_window_to_dict(row))
        for row in rows
    ]
