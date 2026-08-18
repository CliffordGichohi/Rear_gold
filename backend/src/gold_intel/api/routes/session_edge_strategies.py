from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import BacktestRunResponse
from gold_intel.api.session_edge_schemas import SessionEdgeStrategyRunRequest
from gold_intel.application.session_edge_strategies import (
    execute_session_edge_strategy,
    session_strategy_run_to_dict,
)
from gold_intel.backtesting.session_edge_strategy import SESSION_EDGE_EXECUTION_VERSION
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import BacktestRun, BacktestTrade

router = APIRouter(
    prefix="/session-edge-strategies",
    tags=["session edge strategies"],
)


@router.post(
    "/runs",
    response_model=BacktestRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session_edge_strategy_run(
    request: SessionEdgeStrategyRunRequest,
    session: AsyncSession = Depends(get_session),
) -> BacktestRunResponse:
    try:
        async with session.begin():
            run, trades = await execute_session_edge_strategy(
                session,
                source_study_run_ids=request.source_study_run_ids,
                config=request.to_domain(),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BacktestRunResponse.model_validate(
        session_strategy_run_to_dict(run, trades)
    )


@router.get("/runs", response_model=list[BacktestRunResponse])
async def list_session_edge_strategy_runs(
    limit: int = Query(default=10, ge=1, le=50),
    detail_limit: int = Query(default=1, ge=0, le=10),
    session: AsyncSession = Depends(get_session),
) -> list[BacktestRunResponse]:
    runs = list(
        (
            await session.scalars(
                select(BacktestRun)
                .where(BacktestRun.strategy_version == SESSION_EDGE_EXECUTION_VERSION)
                .order_by(BacktestRun.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    output: list[BacktestRunResponse] = []
    for index, run in enumerate(runs):
        include_details = index < detail_limit
        trades = (
            list(
                (
                    await session.scalars(
                        select(BacktestTrade)
                        .where(BacktestTrade.run_id == run.id)
                        .order_by(BacktestTrade.sequence)
                    )
                ).all()
            )
            if include_details
            else []
        )
        output.append(
            BacktestRunResponse.model_validate(
                session_strategy_run_to_dict(
                    run,
                    trades,
                    include_details=include_details,
                )
            )
        )
    return output


@router.get("/runs/{run_id}", response_model=BacktestRunResponse)
async def get_session_edge_strategy_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> BacktestRunResponse:
    run = await session.get(BacktestRun, run_id)
    if run is None or run.strategy_version != SESSION_EDGE_EXECUTION_VERSION:
        raise HTTPException(status_code=404, detail="Session-edge strategy run not found.")
    trades = list(
        (
            await session.scalars(
                select(BacktestTrade)
                .where(BacktestTrade.run_id == run.id)
                .order_by(BacktestTrade.sequence)
            )
        ).all()
    )
    return BacktestRunResponse.model_validate(
        session_strategy_run_to_dict(run, trades)
    )
