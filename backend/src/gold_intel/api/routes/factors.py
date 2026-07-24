from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import FactorCoverageResponse
from gold_intel.application.factor_coverage import build_coverage_report
from gold_intel.infrastructure.database import get_session

router = APIRouter(prefix="/factors", tags=["factors"])


@router.get("/coverage", response_model=FactorCoverageResponse)
async def factor_coverage(
    as_of: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> FactorCoverageResponse:
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    report = await build_coverage_report(session, as_of=cutoff)
    return FactorCoverageResponse.model_validate(report, from_attributes=True)
