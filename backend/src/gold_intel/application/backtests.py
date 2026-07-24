from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.fundamentals import FundamentalState
from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.backtesting.engine import (
    BacktestBar,
    StrategyConfig,
    run_asia_range_acceptance,
)
from gold_intel.infrastructure.models import BacktestRun, BacktestTrade, PriceBar


async def execute_backtest(
    session: AsyncSession,
    *,
    instrument: str,
    provider_code: str,
    start: datetime,
    end: datetime,
    config: StrategyConfig,
) -> tuple[BacktestRun, list[BacktestTrade]]:
    warmup_start = start - timedelta(days=5)
    query = (
        select(PriceBar)
        .where(
            PriceBar.instrument_code == instrument,
            PriceBar.provider_code == provider_code,
            PriceBar.timeframe == "1m",
            PriceBar.open_time >= warmup_start,
            PriceBar.open_time < end,
            PriceBar.available_at <= end,
            PriceBar.is_complete.is_(True),
        )
        .order_by(PriceBar.open_time, PriceBar.available_at)
    )
    rows = list((await session.scalars(query)).all())
    if len(rows) < 1_000:
        raise ValueError(
            "At least 1,000 one-minute bars are required. Ingest more provider history first."
        )
    if len(rows) > 250_000:
        raise ValueError("The first backtest slice is limited to 250,000 source bars.")

    bars = [
        BacktestBar(
            open_time=row.open_time,
            close_time=row.close_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume) if row.volume is not None else None,
            available_at=row.available_at,
            spread_points=row.spread_points,
            spread_price=(
                float(row.spread_price) if row.spread_price is not None else None
            ),
        )
        for row in rows
    ]
    fundamental_inputs = None
    fundamental_cache: dict[datetime, FundamentalState] = {}
    if config.strategy_mode == "FUNDAMENTAL_ALIGNED":
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)

    def fundamental_state_at(decision_time: datetime) -> FundamentalState:
        if fundamental_inputs is None:
            raise RuntimeError("Fundamental inputs were not loaded")
        state = fundamental_cache.get(decision_time)
        if state is None:
            state = fundamental_inputs.state_at(decision_time)
            fundamental_cache[decision_time] = state
        return state

    result = run_asia_range_acceptance(
        bars,
        start=start,
        end=end,
        config=config,
        fundamental_state_at=(
            fundamental_state_at if config.strategy_mode == "FUNDAMENTAL_ALIGNED" else None
        ),
    )
    fundamental_data_hash = (
        fundamental_inputs.state_at(end).data_hash if fundamental_inputs is not None else None
    )
    fundamental_provenance = (
        fundamental_inputs.provenance_at(end)
        if fundamental_inputs is not None
        else None
    )
    combined_data_hash = hashlib.sha256(
        json.dumps(
            {
                "price_data_hash": result.provenance["data_hash_sha256"],
                "fundamental_data_hash": fundamental_data_hash,
                "parameters": asdict(config),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    provenance = {
        **result.provenance,
        "instrument": instrument,
        "provider_code": provider_code,
        "warmup_start": warmup_start.isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "price_data_hash_sha256": result.provenance["data_hash_sha256"],
        "fundamental_data_hash_sha256": fundamental_data_hash,
        "fundamental_evidence": fundamental_provenance,
        "combined_data_hash_sha256": combined_data_hash,
        "lookahead_policy": (
            "Only the earliest price version with available_at at or before the "
            "five-minute decision close is eligible. In fundamental mode, each "
            "observation and COT report must also have available_at/publication_at "
            "at or before that individual decision close. Event schedules, "
            "forecasts, original releases, and calculated surprises are filtered "
            "by their own point-in-time availability at the same decision clock. "
            "Quarterly SOFR distributions are eligible only after their conservative "
            "next-US-business-day availability timestamp. Synthetic evidence is "
            "never loaded for a FUNDAMENTAL_ALIGNED run."
        ),
    }
    now = datetime.now(UTC)
    run = BacktestRun(
        strategy_name=result.strategy,
        strategy_version="1.4.0",
        instrument_code=instrument,
        provider_code=provider_code,
        start_time=start,
        end_time=end,
        status="COMPLETED",
        parameters=asdict(config),
        data_hash=combined_data_hash,
        source_bar_count=len(rows),
        metrics=result.metrics,
        equity_curve=list(result.equity_curve),
        provenance=provenance,
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


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))
