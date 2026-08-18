from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import (
    BacktestDataRangeResponse,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestTradeResponse,
)
from gold_intel.application.backtests import execute_backtest
from gold_intel.backtesting.engine import StrategyConfig
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import BacktestRun, BacktestTrade, PriceBar

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.get("/data-range", response_model=BacktestDataRangeResponse)
async def data_range(
    instrument: str = "XAUUSD",
    provider_code: str = "IC_MARKETS_MT5",
    session: AsyncSession = Depends(get_session),
) -> BacktestDataRangeResponse:
    earliest, latest, count = (
        await session.execute(
            select(
                func.min(PriceBar.open_time),
                func.max(PriceBar.close_time),
                func.count(PriceBar.id),
            ).where(
                PriceBar.instrument_code == instrument,
                PriceBar.provider_code == provider_code,
                PriceBar.timeframe == "1m",
                PriceBar.is_complete.is_(True),
            )
        )
    ).one()
    bar_count = int(count or 0)
    return BacktestDataRangeResponse(
        instrument=instrument,
        provider_code=provider_code,
        earliest=earliest,
        latest=latest,
        bar_count=bar_count,
        ready=bar_count >= 1_000,
    )


@router.post(
    "/runs",
    response_model=BacktestRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    request: BacktestRunRequest,
    session: AsyncSession = Depends(get_session),
) -> BacktestRunResponse:
    config = StrategyConfig(
        strategy_mode=request.strategy_mode,
        initial_equity=request.initial_equity,
        risk_per_trade_pct=request.risk_per_trade_pct,
        asia_start_local=request.asia_start_local,
        asia_end_local=request.asia_end_local,
        confirmation_bars=request.confirmation_bars,
        breakout_buffer_atr=request.breakout_buffer_atr,
        stop_atr_multiple=request.stop_atr_multiple,
        target_r=request.target_r,
        spread_price=request.spread_price,
        slippage_price=request.slippage_price,
        commission_per_lot_round_turn=request.commission_per_lot_round_turn,
        contract_size=request.contract_size,
        min_lot=request.min_lot,
        lot_step=request.lot_step,
        max_lots=request.max_lots,
        fundamental_min_score=request.fundamental_min_score,
        fundamental_min_coverage=request.fundamental_min_coverage,
        fundamental_min_confidence=request.fundamental_min_confidence,
        block_high_impact_events=request.block_high_impact_events,
        allow_unknown_event_risk=request.allow_unknown_event_risk,
        block_elevated_or_abnormal_liquidity=(
            request.block_elevated_or_abnormal_liquidity
        ),
        allow_unknown_liquidity=request.allow_unknown_liquidity,
    )
    try:
        async with session.begin():
            run, trades = await execute_backtest(
                session,
                instrument=request.instrument,
                provider_code=request.provider_code,
                start=request.start,
                end=request.end,
                config=config,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(run, trades)


@router.get("/runs", response_model=list[BacktestRunResponse])
async def list_runs(
    limit: int = Query(default=10, ge=1, le=50),
    strategy_version: str | None = Query(default=None, min_length=1, max_length=64),
    detail_limit: int = Query(
        default=0,
        ge=0,
        le=5,
        description=(
            "Include equity, provenance, and trades for only this many newest "
            "runs. Older rows remain comparison summaries."
        ),
    ),
    session: AsyncSession = Depends(get_session),
) -> list[BacktestRunResponse]:
    query = select(BacktestRun)
    if strategy_version is not None:
        query = query.where(BacktestRun.strategy_version == strategy_version)
    runs = list(
        (
            await session.scalars(
                query.order_by(BacktestRun.created_at.desc()).limit(limit)
            )
        ).all()
    )
    output: list[BacktestRunResponse] = []
    for index, run in enumerate(runs):
        include_details = index < min(detail_limit, limit)
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
        output.append(_response(run, trades, include_details=include_details))
    return output


@router.get("/runs/{run_id}", response_model=BacktestRunResponse)
async def get_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> BacktestRunResponse:
    run = await session.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found.")
    trades = list(
        (
            await session.scalars(
                select(BacktestTrade)
                .where(BacktestTrade.run_id == run.id)
                .order_by(BacktestTrade.sequence)
            )
        ).all()
    )
    return _response(run, trades)


def _response(
    run: BacktestRun,
    trades: list[BacktestTrade],
    *,
    include_details: bool = True,
) -> BacktestRunResponse:
    return BacktestRunResponse(
        id=run.id,
        strategy=run.strategy_name,
        strategy_version=run.strategy_version,
        instrument=run.instrument_code,
        provider_code=run.provider_code,
        start=run.start_time,
        end=run.end_time,
        status=run.status,
        parameters=run.parameters,
        data_hash=run.data_hash,
        source_bar_count=run.source_bar_count,
        metrics=run.metrics,
        equity_curve=run.equity_curve if include_details else [],
        provenance=(
            run.provenance
            if include_details
            else {
                "summary_only": True,
                "full_run_endpoint": f"/api/v1/backtests/runs/{run.id}",
            }
        ),
        created_at=run.created_at,
        completed_at=run.completed_at,
        trades=[
            BacktestTradeResponse(
                sequence=trade.sequence,
                side=trade.side,
                signal_time=trade.signal_time,
                entry_time=trade.entry_time,
                exit_time=trade.exit_time,
                entry_price=float(trade.entry_price),
                exit_price=float(trade.exit_price),
                stop_price=float(trade.stop_price),
                target_price=float(trade.target_price),
                quantity_lots=float(trade.quantity_lots),
                exit_reason=trade.exit_reason,
                gross_pnl=float(trade.gross_pnl),
                costs=float(trade.costs),
                net_pnl=float(trade.net_pnl),
                r_multiple=float(trade.r_multiple),
                mfe_r=float(trade.mfe_r),
                mae_r=float(trade.mae_r),
                holding_minutes=trade.holding_minutes,
                evidence=trade.evidence,
            )
            for trade in trades
        ],
    )
