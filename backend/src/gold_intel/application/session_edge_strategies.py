from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.session_edges import SESSION_EDGE_RULESET_VERSION
from gold_intel.backtesting.session_edge_strategy import (
    SESSION_EDGE_EXECUTION_VERSION,
    SessionExecutionBar,
    SessionStrategyConfig,
    SessionStrategySetup,
    required_execution_windows,
    run_delayed_reclaim_strategy,
)
from gold_intel.infrastructure.models import (
    BacktestRun,
    BacktestTrade,
    PriceBar,
    SessionEdgeStudyRun,
    SessionOpportunity,
)

MAX_EXECUTION_ROWS = 100_000


async def execute_session_edge_strategy(
    session: AsyncSession,
    *,
    source_study_run_ids: list[UUID],
    config: SessionStrategyConfig,
) -> tuple[BacktestRun, list[BacktestTrade]]:
    if not source_study_run_ids or len(set(source_study_run_ids)) != len(
        source_study_run_ids
    ):
        raise ValueError("source_study_run_ids must be non-empty and unique")

    source_runs = list(
        (
            await session.scalars(
                select(SessionEdgeStudyRun)
                .where(SessionEdgeStudyRun.id.in_(source_study_run_ids))
                .order_by(SessionEdgeStudyRun.start_time)
            )
        ).all()
    )
    if len(source_runs) != len(source_study_run_ids):
        found = {item.id for item in source_runs}
        missing = [str(item) for item in source_study_run_ids if item not in found]
        raise ValueError(f"Source session-edge run not found: {', '.join(missing)}")
    _validate_source_runs(source_runs, config=config)

    opportunity_models = list(
        (
            await session.scalars(
                select(SessionOpportunity)
                .where(
                    SessionOpportunity.run_id.in_(source_study_run_ids),
                    SessionOpportunity.setup_side.is_not(None),
                )
                .order_by(
                    SessionOpportunity.session_date,
                    SessionOpportunity.entry_time,
                )
            )
        ).all()
    )
    if not opportunity_models:
        raise ValueError("The source study runs contain no triggered opportunities")
    setups = [_strategy_setup(item) for item in opportunity_models]
    maximum_minutes = 300 if config.calculate_robustness else config.max_holding_minutes
    windows = required_execution_windows(setups, maximum_minutes=maximum_minutes)
    if not windows:
        raise ValueError("The triggered source opportunities contain no entry clocks")

    first_run = source_runs[0]
    window_predicate = or_(
        *[
            and_(
                PriceBar.open_time >= window_start,
                PriceBar.open_time < window_end,
            )
            for window_start, window_end in windows
        ]
    )
    query = (
        select(
            PriceBar.open_time,
            PriceBar.close_time,
            PriceBar.open,
            PriceBar.high,
            PriceBar.low,
            PriceBar.close,
            PriceBar.spread_price,
            PriceBar.available_at,
            PriceBar.source_record_key,
            PriceBar.is_complete,
        )
        .where(
            PriceBar.instrument_code == first_run.instrument_code,
            PriceBar.provider_code == first_run.provider_code,
            PriceBar.timeframe == "1m",
            PriceBar.is_complete.is_(True),
            PriceBar.is_synthetic.is_(False),
            PriceBar.available_at <= PriceBar.close_time,
            window_predicate,
        )
        .order_by(PriceBar.open_time, PriceBar.available_at)
    )
    rows = list((await session.execute(query)).all())
    if not rows:
        raise ValueError("No point-in-time execution bars matched the source opportunities")
    if len(rows) > MAX_EXECUTION_ROWS:
        raise ValueError(
            f"The strategy evaluator is limited to {MAX_EXECUTION_ROWS:,} source rows"
        )
    bars = [
        SessionExecutionBar(
            open_time=row.open_time,
            close_time=row.close_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            spread_price=(
                float(row.spread_price) if row.spread_price is not None else None
            ),
            available_at=row.available_at,
            source_record_key=row.source_record_key,
            complete=bool(row.is_complete),
        )
        for row in rows
    ]
    start = min(item.start_time for item in source_runs).astimezone(UTC)
    end = max(item.end_time for item in source_runs).astimezone(UTC)
    result = await asyncio.to_thread(
        run_delayed_reclaim_strategy,
        setups,
        bars,
        start=start,
        end=end,
        config=config,
    )

    source_manifest = [
        {
            "id": str(item.id),
            "start": item.start_time.isoformat(),
            "end": item.end_time.isoformat(),
            "data_hash": item.data_hash,
            "strategy_version": item.strategy_version,
        }
        for item in source_runs
    ]
    now = datetime.now(UTC)
    run = BacktestRun(
        id=uuid4(),
        strategy_name=result.strategy,
        strategy_version=SESSION_EDGE_EXECUTION_VERSION,
        instrument_code=first_run.instrument_code,
        provider_code=first_run.provider_code,
        start_time=start,
        end_time=end,
        status="COMPLETED" if result.trades else "COMPLETED_NO_TRADES",
        parameters={
            **_jsonable(asdict(config)),
            "source_study_run_ids": [str(item.id) for item in source_runs],
        },
        data_hash=str(result.provenance["combined_data_hash_sha256"]),
        source_bar_count=len(rows),
        metrics={
            **result.metrics,
            "source_study_run_ids": [str(item.id) for item in source_runs],
        },
        equity_curve=list(result.equity_curve),
        provenance={
            **result.provenance,
            "source_study_runs": source_manifest,
            "source_detector_version": SESSION_EDGE_RULESET_VERSION,
            "instrument": first_run.instrument_code,
            "provider_code": first_run.provider_code,
            "requested_source_period_start": start.isoformat(),
            "requested_source_period_end": end.isoformat(),
            "raw_execution_row_count": len(rows),
            "exclusions": result.exclusions,
            "persistence_policy": (
                "The backtest run and trades are append-only. Every trade links "
                "to an immutable source opportunity and source study run."
            ),
        },
        completed_at=now,
    )
    session.add(run)
    await session.flush()

    trade_models: list[BacktestTrade] = []
    for trade in result.trades:
        model = BacktestTrade(
            run_id=run.id,
            sequence=trade.sequence,
            side=trade.side,
            signal_time=trade.signal_time,
            entry_time=trade.entry_time,
            exit_time=trade.exit_time,
            entry_price=_decimal(trade.entry_price),
            exit_price=_decimal(trade.exit_price),
            stop_price=_decimal(trade.stop_price),
            target_price=_decimal(trade.target_price),
            quantity_lots=_decimal(trade.quantity_lots),
            exit_reason=trade.exit_reason,
            gross_pnl=_decimal(trade.gross_pnl),
            costs=_decimal(trade.costs),
            net_pnl=_decimal(trade.net_pnl),
            r_multiple=_decimal(trade.r_multiple),
            mfe_r=_decimal(trade.mfe_r),
            mae_r=_decimal(trade.mae_r),
            holding_minutes=trade.holding_minutes,
            evidence={
                **trade.evidence,
                "reference_entry_price": trade.reference_entry_price,
                "reference_exit_price": trade.reference_exit_price,
            },
        )
        session.add(model)
        trade_models.append(model)
    await session.flush()
    return run, trade_models


def session_strategy_run_to_dict(
    run: BacktestRun,
    trades: list[BacktestTrade],
    *,
    include_details: bool = True,
) -> dict[str, Any]:
    return {
        "id": run.id,
        "strategy": run.strategy_name,
        "strategy_version": run.strategy_version,
        "instrument": run.instrument_code,
        "provider_code": run.provider_code,
        "start": run.start_time,
        "end": run.end_time,
        "status": run.status,
        "parameters": run.parameters,
        "data_hash": run.data_hash,
        "source_bar_count": run.source_bar_count,
        "metrics": run.metrics,
        "equity_curve": run.equity_curve if include_details else [],
        "provenance": (
            run.provenance
            if include_details
            else {
                "summary_only": True,
                "full_run_endpoint": f"/api/v1/session-edge-strategies/runs/{run.id}",
            }
        ),
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "trades": [
            {
                "sequence": trade.sequence,
                "side": trade.side,
                "signal_time": trade.signal_time,
                "entry_time": trade.entry_time,
                "exit_time": trade.exit_time,
                "entry_price": float(trade.entry_price),
                "exit_price": float(trade.exit_price),
                "stop_price": float(trade.stop_price),
                "target_price": float(trade.target_price),
                "quantity_lots": float(trade.quantity_lots),
                "exit_reason": trade.exit_reason,
                "gross_pnl": float(trade.gross_pnl),
                "costs": float(trade.costs),
                "net_pnl": float(trade.net_pnl),
                "r_multiple": float(trade.r_multiple),
                "mfe_r": float(trade.mfe_r),
                "mae_r": float(trade.mae_r),
                "holding_minutes": trade.holding_minutes,
                "evidence": trade.evidence,
            }
            for trade in trades
        ],
    }


def _strategy_setup(model: SessionOpportunity) -> SessionStrategySetup:
    return SessionStrategySetup(
        source_opportunity_id=str(model.id),
        source_run_id=str(model.run_id),
        source_data_hash=model.data_hash,
        session_date=model.session_date,
        status=model.status,
        side=model.setup_side,
        signal_time=model.signal_time,
        entry_time=model.entry_time,
        entry_reference_price=(
            float(model.entry_reference_price)
            if model.entry_reference_price is not None
            else None
        ),
        invalidation_price=(
            float(model.invalidation_price)
            if model.invalidation_price is not None
            else None
        ),
        risk_distance=(
            float(model.risk_distance) if model.risk_distance is not None else None
        ),
        bias_alignment=model.bias_alignment,
        event_risk=model.event_risk,
        regime_label=model.regime_label,
        dominant_driver=model.dominant_driver,
        facts=model.facts,
        outcomes=model.outcomes,
        evidence=model.evidence,
    )


def _validate_source_runs(
    runs: list[SessionEdgeStudyRun],
    *,
    config: SessionStrategyConfig,
) -> None:
    first = runs[0]
    for item in runs:
        if item.status != "COMPLETED":
            raise ValueError(f"Source study run {item.id} is not complete")
        if item.strategy_version != SESSION_EDGE_RULESET_VERSION:
            raise ValueError(
                f"Source study run {item.id} uses {item.strategy_version}; "
                f"{SESSION_EDGE_RULESET_VERSION} is required"
            )
        if (
            item.instrument_code != first.instrument_code
            or item.provider_code != first.provider_code
        ):
            raise ValueError("Source study runs must use one instrument and provider")
        if item.parameters != first.parameters:
            raise ValueError("Source study runs must use identical detector parameters")
    ordered = sorted(runs, key=lambda item: item.start_time)
    if any(
        current.start_time < prior.end_time
        for prior, current in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("Source study run periods must not overlap")
    if (
        config.strategy_mode == "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED"
        and not bool(first.parameters.get("include_fundamentals"))
    ):
        raise ValueError("The fundamental-aligned strategy requires fundamental studies")


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _jsonable(value: object) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
