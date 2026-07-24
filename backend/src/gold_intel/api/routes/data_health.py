from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import DataHealthSummaryResponse
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import DataQualityIssue

router = APIRouter(prefix="/data-health", tags=["data-health"])


@router.get("/summary", response_model=DataHealthSummaryResponse)
async def summary(session: AsyncSession = Depends(get_session)) -> DataHealthSummaryResponse:
    rows = (
        await session.execute(
            select(DataQualityIssue.severity, func.count(DataQualityIssue.id))
            .where(DataQualityIssue.status == "OPEN")
            .group_by(DataQualityIssue.severity)
        )
    ).all()
    counts = {severity: count for severity, count in rows}
    warnings = int(counts.get("WARNING", 0))
    errors = int(counts.get("ERROR", 0))
    total = sum(int(value) for value in counts.values())
    return DataHealthSummaryResponse(
        status="DEGRADED" if total else "HEALTHY",
        open_issue_count=total,
        warning_count=warnings,
        error_count=errors,
        stale_series=[],
    )
