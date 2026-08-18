from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from explore_session_playbooks import Bar
from research_cross_market_auction_micro_execution import (
    _bars,
    _five_minute_bars_from_csv_directory,
)
from research_daily_session_playbooks import (
    Signal,
    Trade,
    _atr_by_close,
    _directional_bar,
)
from research_session_state_transitions import (
    Candidate,
    ContextRule,
    ManagedResult,
    _candidate_report,
    _compact_metrics,
    _ranking_key,
    _select_discovery_candidates,
    _slice,
)
from sqlalchemy import text

from gold_intel.infrastructure.database import session_factory

LOCKED_HOLDOUT = datetime(2025, 1, 1, tzinfo=UTC)
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")

FIVE_MINUTE_SQL = text(
    """
    WITH canonical AS (
        SELECT DISTINCT ON (open_time)
            open_time,
            close_time,
            open,
            high,
            low,
            close,
            volume,
            spread_price,
            available_at
        FROM market.price_bars
        WHERE instrument_code = :instrument
          AND provider_code = 'IC_MARKETS_MT5'
          AND timeframe = '1m'
          AND is_complete
          AND NOT is_synthetic
          AND open_time >= :load_start
          AND open_time < :load_end
          AND available_at <= close_time
        ORDER BY open_time, available_at
    ),
    bucketed AS (
        SELECT
            time_bucket(INTERVAL '5 minutes', open_time) AS open_time,
            time_bucket(INTERVAL '5 minutes', open_time)
                + INTERVAL '5 minutes' AS close_time,
            first(open, open_time) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, open_time) AS close,
            sum(volume) AS volume,
            avg(spread_price) AS spread_price,
            count(*) AS members,
            max(close_time) AS last_close
        FROM canonical
        GROUP BY 1
    )
    SELECT
        open_time,
        close_time,
        open,
        high,
        low,
        close,
        volume,
        spread_price
    FROM bucketed
    WHERE members = 5
      AND last_close = open_time + INTERVAL '5 minutes'
    ORDER BY open_time
    """
)

MANAGERS = {
    "FIXED_1_50R": 1.5,
    "FIXED_2_00R": 2.0,
    "FIXED_3_00R": 3.0,
    "FIXED_4_00R": 4.0,
}

POINT_SIZES = {
    "AUDUSD": 0.00001,
    "DE40": 0.01,
    "GBPUSD": 0.00001,
    "USDJPY": 0.001,
    "US500": 0.01,
    "USTEC": 0.01,
    "XTIUSD": 0.01,
}


@dataclass(frozen=True, slots=True)
class CostSpec:
    slippage_per_side: float
    round_turn_commission_price: float


COSTS = {
    "XAUUSD": CostSpec(0.05, 0.07),
    "XAGUSD": CostSpec(0.005, 0.007),
    "EURUSD": CostSpec(0.00002, 0.00007),
    "GBPUSD": CostSpec(0.00002, 0.00007),
    "AUDUSD": CostSpec(0.00002, 0.00007),
    "USDJPY": CostSpec(0.002, 0.012),
    "US500": CostSpec(0.10, 0.0),
    "USTEC": CostSpec(0.25, 0.0),
    "DE40": CostSpec(0.25, 0.0),
    "XTIUSD": CostSpec(0.01, 0.0),
}

CLUSTERS = {
    "XAUUSD": "METALS",
    "XAGUSD": "METALS",
    "EURUSD": "FX",
    "GBPUSD": "FX",
    "AUDUSD": "FX",
    "USDJPY": "FX",
    "US500": "EQUITY",
    "USTEC": "EQUITY",
    "DE40": "EQUITY",
    "XTIUSD": "ENERGY",
}


@dataclass(frozen=True, slots=True)
class SessionSpec:
    name: str
    instruments: tuple[str, ...]
    zone: ZoneInfo
    opening_range_start: clock_time
    opening_range_end: clock_time
    trade_end: clock_time


SESSIONS = (
    SessionSpec(
        "LONDON_OPEN",
        ("XAUUSD", "XAGUSD", "EURUSD"),
        LONDON,
        clock_time(8, 0),
        clock_time(8, 15),
        clock_time(12, 0),
    ),
    SessionSpec(
        "COMEX_OPEN",
        ("XAUUSD", "XAGUSD"),
        NEW_YORK,
        clock_time(8, 20),
        clock_time(8, 35),
        clock_time(12, 30),
    ),
    SessionSpec(
        "NEW_YORK_CASH",
        ("US500",),
        NEW_YORK,
        clock_time(9, 30),
        clock_time(9, 45),
        clock_time(12, 30),
    ),
)

Rule = Callable[[Signal], bool]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--us500-csv-dir", type=Path, required=True)
    parser.add_argument("--cache-output", type=Path)
    parser.add_argument(
        "--cost-aware-risk",
        action="store_true",
        help=(
            "Widen structural risk to at least 0.75 ATR and enough distance "
            "to keep estimated round-trip friction at or below 0.15R."
        ),
    )
    parser.add_argument("--top", type=int, default=60)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > LOCKED_HOLDOUT:
        raise ValueError("The locked 2025 holdout must not be loaded")

    started = time.perf_counter()
    all_signals: list[Signal] = []
    managed: list[ManagedResult] = []
    coverage: dict[str, Any] = {}
    query = {
        "load_start": start - timedelta(days=12),
        "load_end": end,
    }
    async with session_factory() as session:
        for instrument in ("XAUUSD", "XAGUSD", "EURUSD"):
            bars = _bars(
                (
                    await session.execute(
                        FIVE_MINUTE_SQL,
                        {"instrument": instrument, **query},
                    )
                ).mappings(),
            )
            signals = _instrument_signals(
                instrument,
                bars=bars,
                start=start,
                end=end,
            )
            if args.cost_aware_risk:
                signals = _cost_aware_signals(signals)
            all_signals.extend(signals)
            managed.extend(_managed_results(signals, bars=bars))
            coverage[instrument] = _coverage(bars)
            _phase(f"{instrument}_COMPLETE", started)

    us500 = _five_minute_bars_from_csv_directory(
        args.us500_csv_dir,
        load_start=query["load_start"],
        load_end=end,
        point_size=POINT_SIZES["US500"],
    )
    us500_signals = _instrument_signals(
        "US500",
        bars=us500,
        start=start,
        end=end,
    )
    if args.cost_aware_risk:
        us500_signals = _cost_aware_signals(us500_signals)
    all_signals.extend(us500_signals)
    managed.extend(_managed_results(us500_signals, bars=us500))
    coverage["US500"] = _coverage(us500)
    _phase("US500_COMPLETE", started)

    if args.cache_output is not None:
        _write_cache(managed, args.cache_output)
        _phase("CACHE_WRITTEN", started)

    candidates, candidate_trades = _candidate_results(managed)
    selected = _select_discovery_candidates(
        candidates,
        candidate_trades=candidate_trades,
    )
    ranked = sorted(
        candidates,
        key=lambda candidate: _ranking_key(
            candidate,
            candidate_trades=candidate_trades,
        ),
        reverse=True,
    )
    base_portfolio = _portfolio_report(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    stressed_portfolio = _portfolio_report(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.5,
    )
    report = {
        "contract": {
            "version": (
                "MULTI_ASSET_SESSION_PORTFOLIO_SCREEN_V0_2"
                if args.cost_aware_risk
                else "MULTI_ASSET_SESSION_PORTFOLIO_SCREEN_V0_1"
            ),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "purpose": (
                "Search for several modest, independently executable session "
                "edges rather than forcing 10R from one gold rule."
            ),
            "signals": (
                "DST-aware 15-minute opening-range breakout, accepted retest, "
                "and failed breakout for London, COMEX, and New York cash."
            ),
            "selection": (
                "Candidates are selected on 2021-08 through 2022 only. Calendar "
                "2023 and 2024 are judgment periods and never select parameters."
            ),
            "execution": (
                "Next completed five-minute open; structural stop; pessimistic "
                "stop-first handling when target and stop share a bar."
            ),
            "risk_policy": (
                "Structural distance widened, never narrowed, to at least "
                "0.75 ATR and estimated friction <=0.15R; reject above 2.50 ATR."
                if args.cost_aware_risk
                else "Original structural distance between 0.20 and 2.50 ATR."
            ),
            "costs": {
                instrument: {
                    "observed_entry_and_exit_spread": True,
                    "slippage_per_side": spec.slippage_per_side,
                    "round_turn_commission_price": spec.round_turn_commission_price,
                    "stress_multiplier": 1.5,
                }
                for instrument, spec in COSTS.items()
            },
            "portfolio": (
                "At most one open position per correlation cluster, two total "
                "open positions, and a -3R realized daily stop."
            ),
            "promotion_boundary": (
                "This is a five-minute screen. Even a passing portfolio requires "
                "separate one-minute execution validation before holdout use."
            ),
        },
        "coverage": coverage,
        "source_counts": {
            "signals": len(all_signals),
            "managed_executions": len(managed),
            "candidate_hypotheses": len(candidates),
            "selected_candidates": len(selected),
        },
        "signal_funnel": _signal_funnel(all_signals),
        "selected_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in selected
        ],
        "portfolio": {
            "base_cost": base_portfolio,
            "cost_stress_1_50x": stressed_portfolio,
            "positive_each_development_year": _annual_gate(
                selected,
                candidate_trades=candidate_trades,
            ),
            "ten_r_monthly_promotion_gate": _target_gate(
                base_portfolio,
                stressed_portfolio,
            ),
        },
        "top_discovery_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in ranked[: args.top]
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _instrument_signals(
    instrument: str,
    *,
    bars: Sequence[Bar],
    start: datetime,
    end: datetime,
) -> list[Signal]:
    if not bars:
        raise RuntimeError(f"No five-minute history for {instrument}")
    if bars[-1].open_time >= LOCKED_HOLDOUT:
        raise RuntimeError(f"Locked holdout leaked into {instrument}")
    specs = [spec for spec in SESSIONS if instrument in spec.instruments]
    by_open = {bar.open_time: bar for bar in bars}
    atr_by_close = _atr_by_close(bars)
    output: list[Signal] = []
    for spec in specs:
        opening_range_history: list[float] = []
        local_date = start.astimezone(spec.zone).date()
        final_date = (end - timedelta(microseconds=1)).astimezone(spec.zone).date()
        while local_date <= final_date:
            if local_date.weekday() < 5:
                range_start = datetime.combine(
                    local_date,
                    spec.opening_range_start,
                    tzinfo=spec.zone,
                ).astimezone(UTC)
                range_end = datetime.combine(
                    local_date,
                    spec.opening_range_end,
                    tzinfo=spec.zone,
                ).astimezone(UTC)
                trade_end = datetime.combine(
                    local_date,
                    spec.trade_end,
                    tzinfo=spec.zone,
                ).astimezone(UTC)
                range_bars = _complete_path(
                    by_open,
                    start=range_start,
                    end=range_end,
                )
                search_bars = _complete_path(
                    by_open,
                    start=range_end,
                    end=trade_end,
                )
                if range_bars is not None and search_bars is not None:
                    atr = atr_by_close.get(range_end)
                    if atr is not None and atr > 0 and search_bars:
                        width = max(bar.high for bar in range_bars) - min(
                            bar.low for bar in range_bars
                        )
                        percentile = _prior_percentile(
                            opening_range_history,
                            width,
                        )
                        context = _session_context(
                            by_open,
                            range_start=range_start,
                            atr=atr,
                            opening_range_width=width,
                            opening_range_percentile=percentile,
                        )
                        output.extend(
                            _signals_for_session(
                                instrument,
                                spec=spec,
                                session_date=local_date,
                                range_bars=range_bars,
                                search_bars=search_bars,
                                trade_end=trade_end,
                                atr=atr,
                                context=context,
                            ),
                        )
                        opening_range_history.append(width)
            local_date += timedelta(days=1)
    return output


def _cost_aware_signals(
    signals: Sequence[Signal],
) -> list[Signal]:
    output: list[Signal] = []
    for signal in signals:
        structural_risk = abs(signal.entry_reference - signal.stop)
        estimated_cost_r = _evidence(signal, "estimated_cost_r")
        if structural_risk <= 0 or not math.isfinite(estimated_cost_r):
            continue
        estimated_cost_price = estimated_cost_r * structural_risk
        adjusted_risk = max(
            structural_risk,
            0.75 * signal.atr,
            estimated_cost_price / 0.15,
        )
        adjusted_risk_atr = adjusted_risk / signal.atr
        if adjusted_risk_atr > 2.50:
            continue
        direction = 1.0 if signal.side == "LONG" else -1.0
        evidence = {
            **signal.evidence,
            "original_structural_risk_atr": structural_risk / signal.atr,
            "risk_atr": adjusted_risk_atr,
            "estimated_cost_r": estimated_cost_price / adjusted_risk,
            "cost_aware_risk_adjusted": adjusted_risk > structural_risk,
        }
        output.append(
            replace(
                signal,
                stop=signal.entry_reference - direction * adjusted_risk,
                evidence=evidence,
            ),
        )
    return output


def _signals_for_session(
    instrument: str,
    *,
    spec: SessionSpec,
    session_date: date,
    range_bars: Sequence[Bar],
    search_bars: Sequence[Bar],
    trade_end: datetime,
    atr: float,
    context: dict[str, float | None],
) -> list[Signal]:
    high = max(bar.high for bar in range_bars)
    low = min(bar.low for bar in range_bars)
    output: list[Signal] = []
    breakout = _opening_range_breakout(
        instrument,
        spec=spec,
        session_date=session_date,
        bars=search_bars,
        high=high,
        low=low,
        atr=atr,
        trade_end=trade_end,
        context=context,
    )
    if breakout is not None:
        output.append(breakout)
    retest = _opening_range_retest(
        instrument,
        spec=spec,
        session_date=session_date,
        bars=search_bars,
        high=high,
        low=low,
        atr=atr,
        trade_end=trade_end,
        context=context,
    )
    if retest is not None:
        output.append(retest)
    failure = _opening_range_failure(
        instrument,
        spec=spec,
        session_date=session_date,
        bars=search_bars,
        high=high,
        low=low,
        atr=atr,
        trade_end=trade_end,
        context=context,
    )
    if failure is not None:
        output.append(failure)
    return output


def _opening_range_breakout(
    instrument: str,
    *,
    spec: SessionSpec,
    session_date: date,
    bars: Sequence[Bar],
    high: float,
    low: float,
    atr: float,
    trade_end: datetime,
    context: dict[str, float | None],
) -> Signal | None:
    for index in range(min(len(bars) - 1, 24)):
        current = bars[index]
        side = (
            "LONG"
            if current.close >= high + 0.05 * atr
            else "SHORT"
            if current.close <= low - 0.05 * atr
            else None
        )
        if side is None or not _directional_bar(
            current,
            side=side,
            atr=atr,
            min_body_atr=0.15,
            min_body_ratio=0.55,
            min_close_location=0.65,
        ):
            continue
        recent = bars[max(0, index - 2) : index + 1]
        stop = (
            min(bar.low for bar in recent) - 0.10 * atr
            if side == "LONG"
            else max(bar.high for bar in recent) + 0.10 * atr
        )
        return _make_signal(
            instrument,
            spec=spec,
            playbook="OR_BREAKOUT",
            session_date=session_date,
            side=side,
            signal_bar=current,
            entry_bar=bars[index + 1],
            stop=stop,
            atr=atr,
            trade_end=trade_end,
            context=context,
            relative_volume=_relative_volume(bars, index),
        )
    return None


def _opening_range_retest(
    instrument: str,
    *,
    spec: SessionSpec,
    session_date: date,
    bars: Sequence[Bar],
    high: float,
    low: float,
    atr: float,
    trade_end: datetime,
    context: dict[str, float | None],
) -> Signal | None:
    break_index: int | None = None
    side: str | None = None
    boundary = 0.0
    for index in range(min(len(bars) - 1, 18)):
        bar = bars[index]
        if break_index is None:
            if bar.close >= high + 0.05 * atr:
                break_index, side, boundary = index, "LONG", high
            elif bar.close <= low - 0.05 * atr:
                break_index, side, boundary = index, "SHORT", low
            continue
        if index > break_index + 6 or side is None:
            return None
        accepted = (
            bar.low <= boundary + 0.10 * atr and bar.close >= boundary + 0.05 * atr
            if side == "LONG"
            else bar.high >= boundary - 0.10 * atr and bar.close <= boundary - 0.05 * atr
        )
        if not accepted or not _directional_bar(
            bar,
            side=side,
            atr=atr,
            min_body_atr=0.10,
            min_body_ratio=0.50,
            min_close_location=0.60,
        ):
            continue
        path = bars[break_index : index + 1]
        stop = (
            min(member.low for member in path) - 0.10 * atr
            if side == "LONG"
            else max(member.high for member in path) + 0.10 * atr
        )
        return _make_signal(
            instrument,
            spec=spec,
            playbook="OR_RETEST",
            session_date=session_date,
            side=side,
            signal_bar=bar,
            entry_bar=bars[index + 1],
            stop=stop,
            atr=atr,
            trade_end=trade_end,
            context=context,
            relative_volume=_relative_volume(bars, index),
        )
    return None


def _opening_range_failure(
    instrument: str,
    *,
    spec: SessionSpec,
    session_date: date,
    bars: Sequence[Bar],
    high: float,
    low: float,
    atr: float,
    trade_end: datetime,
    context: dict[str, float | None],
) -> Signal | None:
    for index in range(min(len(bars) - 1, 24)):
        bar = bars[index]
        side: str | None = None
        if bar.high >= high + 0.10 * atr and bar.close <= high - 0.05 * atr:
            side = "SHORT"
            stop = bar.high + 0.10 * atr
        elif bar.low <= low - 0.10 * atr and bar.close >= low + 0.05 * atr:
            side = "LONG"
            stop = bar.low - 0.10 * atr
        else:
            continue
        if not _directional_bar(
            bar,
            side=side,
            atr=atr,
            min_body_atr=0.12,
            min_body_ratio=0.50,
            min_close_location=0.60,
        ):
            continue
        return _make_signal(
            instrument,
            spec=spec,
            playbook="OR_FAILURE",
            session_date=session_date,
            side=side,
            signal_bar=bar,
            entry_bar=bars[index + 1],
            stop=stop,
            atr=atr,
            trade_end=trade_end,
            context=context,
            relative_volume=_relative_volume(bars, index),
        )
    return None


def _make_signal(
    instrument: str,
    *,
    spec: SessionSpec,
    playbook: str,
    session_date: date,
    side: str,
    signal_bar: Bar,
    entry_bar: Bar,
    stop: float,
    atr: float,
    trade_end: datetime,
    context: dict[str, float | None],
    relative_volume: float | None,
) -> Signal | None:
    if entry_bar.open_time != signal_bar.close_time:
        return None
    if (side == "LONG" and stop >= entry_bar.open) or (side == "SHORT" and stop <= entry_bar.open):
        return None
    risk = abs(entry_bar.open - stop)
    risk_atr = risk / atr
    if not 0.20 <= risk_atr <= 2.50:
        return None
    holding = min(
        240,
        int((trade_end - entry_bar.open_time).total_seconds() // 60),
    )
    holding -= holding % 5
    if holding < 15:
        return None
    side_sign = 1.0 if side == "LONG" else -1.0
    cost = COSTS[instrument]
    expected_cost = (
        entry_bar.spread + 2 * cost.slippage_per_side + cost.round_turn_commission_price
    ) / risk
    return Signal(
        playbook=f"{instrument}|{spec.name}|{playbook}",
        session_date=session_date,
        side=side,
        signal_time=signal_bar.close_time,
        entry_time=entry_bar.open_time,
        entry_reference=entry_bar.open,
        stop=stop,
        base_target_r=2.0,
        max_holding_minutes=holding,
        atr=atr,
        evidence={
            "instrument": instrument,
            "cluster": CLUSTERS[instrument],
            "session": spec.name,
            "entry_resolution": "5m",
            "risk_atr": risk_atr,
            "estimated_cost_r": expected_cost,
            "relative_volume": relative_volume,
            "opening_range_atr": context["opening_range_atr"],
            "opening_range_percentile": context["opening_range_percentile"],
            "signed_trend_60_atr": side_sign * _or_nan(context["trend_60_atr"]),
            "signed_trend_240_atr": side_sign * _or_nan(context["trend_240_atr"]),
        },
    )


def _managed_results(
    signals: Sequence[Signal],
    *,
    bars: Sequence[Bar],
) -> list[ManagedResult]:
    by_open = {bar.open_time: bar for bar in bars}
    output: list[ManagedResult] = []
    for signal in signals:
        instrument = str(signal.evidence["instrument"])
        for cost_multiplier in (1.0, 1.5):
            for manager, target_r in MANAGERS.items():
                trade = _simulate(
                    signal,
                    bars_by_open=by_open,
                    target_r=target_r,
                    cost_multiplier=cost_multiplier,
                    cost=COSTS[instrument],
                )
                if trade is not None:
                    output.append(
                        ManagedResult(
                            signal=signal,
                            manager=manager,
                            cost_multiplier=cost_multiplier,
                            trade=trade,
                        ),
                    )
    return output


def _simulate(
    signal: Signal,
    *,
    bars_by_open: dict[datetime, Bar],
    target_r: float,
    cost_multiplier: float,
    cost: CostSpec,
) -> Trade | None:
    risk = abs(signal.entry_reference - signal.stop)
    if risk <= 0:
        return None
    expected = [
        signal.entry_time + timedelta(minutes=offset)
        for offset in range(0, signal.max_holding_minutes, 5)
    ]
    path = [bars_by_open.get(timestamp) for timestamp in expected]
    if any(bar is None for bar in path):
        return None
    bars = [bar for bar in path if bar is not None]
    direction = 1 if signal.side == "LONG" else -1
    target = signal.entry_reference + direction * target_r * risk
    exit_bar = bars[-1]
    exit_price = exit_bar.close
    exit_reason = "TIME"
    favourable = 0.0
    adverse = 0.0
    for bar in bars:
        if signal.side == "LONG":
            stop_hit = bar.low <= signal.stop
            target_hit = bar.high >= target
            favourable = max(favourable, bar.high - signal.entry_reference)
            adverse = max(adverse, signal.entry_reference - bar.low)
        else:
            stop_hit = bar.high >= signal.stop
            target_hit = bar.low <= target
            favourable = max(favourable, signal.entry_reference - bar.low)
            adverse = max(adverse, bar.high - signal.entry_reference)
        if stop_hit:
            exit_bar, exit_price, exit_reason = bar, signal.stop, "STOP"
            break
        if target_hit:
            exit_bar, exit_price, exit_reason = bar, target, "TARGET"
            break
    gross_r = direction * (exit_price - signal.entry_reference) / risk
    cost_price = (
        bars[0].spread / 2
        + exit_bar.spread / 2
        + 2 * cost.slippage_per_side
        + cost.round_turn_commission_price
    ) * cost_multiplier
    cost_r = cost_price / risk
    return Trade(
        playbook=signal.playbook,
        session_date=signal.session_date,
        side=signal.side,
        signal_time=signal.signal_time,
        entry_time=signal.entry_time,
        exit_time=exit_bar.close_time,
        exit_reason=exit_reason,
        risk_distance=round(risk, 8),
        gross_r=round(gross_r, 6),
        net_r=round(gross_r - cost_r, 6),
        cost_r=round(cost_r, 6),
        mfe_r=round(max(0.0, favourable / risk), 6),
        mae_r=round(max(0.0, adverse / risk), 6),
        holding_minutes=int(
            (exit_bar.close_time - signal.entry_time).total_seconds() // 60,
        ),
        evidence={
            **signal.evidence,
            "target_r": target_r,
            "entry_spread": bars[0].spread,
            "exit_spread": exit_bar.spread,
            "same_bar_ambiguity": "STOP_FIRST",
            "cost_multiplier": cost_multiplier,
        },
    )


def _rules() -> tuple[ContextRule, ...]:
    return (
        ContextRule("BASE", lambda signal: True),
        ContextRule(
            "COST_LE_0_20R",
            lambda signal: _evidence(signal, "estimated_cost_r") <= 0.20,
        ),
        ContextRule(
            "TREND_60_ALIGNED",
            lambda signal: _evidence(signal, "signed_trend_60_atr") > 0,
        ),
        ContextRule(
            "TREND_240_ALIGNED",
            lambda signal: _evidence(signal, "signed_trend_240_atr") > 0,
        ),
        ContextRule(
            "TREND_BOTH_ALIGNED",
            lambda signal: (
                _evidence(signal, "signed_trend_60_atr") > 0
                and _evidence(signal, "signed_trend_240_atr") > 0
            ),
        ),
        ContextRule(
            "TREND_60_OPPOSED",
            lambda signal: _evidence(signal, "signed_trend_60_atr") < 0,
        ),
        ContextRule(
            "TREND_BOTH_OPPOSED",
            lambda signal: (
                _evidence(signal, "signed_trend_60_atr") < 0
                and _evidence(signal, "signed_trend_240_atr") < 0
            ),
        ),
        ContextRule(
            "OPENING_RANGE_P40",
            lambda signal: (
                _evidence(
                    signal,
                    "opening_range_percentile",
                )
                <= 40
            ),
        ),
        ContextRule(
            "OPENING_RANGE_P60_PLUS",
            lambda signal: (
                _evidence(
                    signal,
                    "opening_range_percentile",
                )
                >= 60
            ),
        ),
        ContextRule(
            "RELATIVE_VOLUME_1_20X",
            lambda signal: _evidence(signal, "relative_volume") >= 1.20,
        ),
        ContextRule(
            "TREND_BOTH_AND_COST",
            lambda signal: (
                _evidence(signal, "signed_trend_60_atr") > 0
                and _evidence(signal, "signed_trend_240_atr") > 0
                and _evidence(signal, "estimated_cost_r") <= 0.20
            ),
        ),
    )


def _candidate_results(
    managed: Sequence[ManagedResult],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Trade]]]:
    rules = _rules()
    archetypes = sorted({result.signal.playbook for result in managed})
    managers = sorted({result.manager for result in managed})
    candidates = [
        Candidate(archetype, rule.name, manager)
        for archetype in archetypes
        for rule in rules
        for manager in managers
    ]
    rule_by_name = {rule.name: rule for rule in rules}
    output: dict[tuple[str, float], list[Trade]] = {}
    for candidate in candidates:
        rule = rule_by_name[candidate.rule]
        for multiplier in (1.0, 1.5):
            output[(candidate.key, multiplier)] = [
                result.trade
                for result in managed
                if result.signal.playbook == candidate.archetype
                and result.manager == candidate.manager
                and result.cost_multiplier == multiplier
                and rule.predicate(result.signal)
            ]
    return candidates, output


def _portfolio_report(
    selected: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
    cost_multiplier: float,
) -> dict[str, Any]:
    accepted, diagnostics = _accepted_portfolio_trades(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=cost_multiplier,
    )
    period_trades = {
        "discovery": _slice(accepted, "discovery"),
        "validation_2023": _slice(accepted, "validation"),
        "forward_2024": _slice(accepted, "forward"),
    }
    metrics = {
        "discovery": _compact_metrics(
            period_trades["discovery"],
            calendar_start=date(2021, 8, 1),
            calendar_end=date(2023, 1, 1),
        ),
        "validation_2023": _compact_metrics(
            period_trades["validation_2023"],
            calendar_start=date(2023, 1, 1),
            calendar_end=date(2024, 1, 1),
        ),
        "forward_2024": _compact_metrics(
            period_trades["forward_2024"],
            calendar_start=date(2024, 1, 1),
            calendar_end=date(2025, 1, 1),
        ),
        "all_pre_2025": _compact_metrics(
            accepted,
            calendar_start=date(2021, 8, 1),
            calendar_end=date(2025, 1, 1),
        ),
    }
    profit_by_instrument: dict[str, float] = defaultdict(float)
    for trade in accepted:
        instrument = str(trade.evidence["instrument"])
        profit_by_instrument[instrument] += max(trade.net_r, 0.0)
    total_positive = sum(profit_by_instrument.values())
    max_share = (
        max(profit_by_instrument.values(), default=0.0) / total_positive
        if total_positive > 0
        else 1.0
    )
    return {
        "selected_candidate_count": len(selected),
        "accepted_trades": len(accepted),
        **diagnostics,
        **metrics,
        "positive_profit_by_instrument": {
            key: round(value, 6) for key, value in sorted(profit_by_instrument.items())
        },
        "max_positive_profit_share_pct": round(max_share * 100, 3),
    }


def _accepted_portfolio_trades(
    selected: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
    cost_multiplier: float,
) -> tuple[list[Trade], dict[str, int]]:
    priority = {candidate.key: index for index, candidate in enumerate(selected)}
    members = [
        (trade, candidate)
        for candidate in selected
        for trade in candidate_trades[(candidate.key, cost_multiplier)]
    ]
    members.sort(
        key=lambda item: (
            item[0].entry_time,
            priority[item[1].key],
            item[0].playbook,
        ),
    )
    accepted: list[Trade] = []
    active: list[Trade] = []
    pending_realization: list[Trade] = []
    realized_by_date: dict[date, float] = defaultdict(float)
    skipped_cluster = 0
    skipped_capacity = 0
    skipped_daily_loss = 0
    for trade, _ in members:
        completed = [item for item in pending_realization if item.exit_time <= trade.entry_time]
        for item in completed:
            realized_by_date[item.session_date] += item.net_r
        pending_realization = [
            item for item in pending_realization if item.exit_time > trade.entry_time
        ]
        active = [item for item in active if item.exit_time > trade.entry_time]
        cluster = str(trade.evidence["cluster"])
        if any(str(item.evidence["cluster"]) == cluster for item in active):
            skipped_cluster += 1
            continue
        if len(active) >= 2:
            skipped_capacity += 1
            continue
        if realized_by_date[trade.session_date] <= -3.0:
            skipped_daily_loss += 1
            continue
        accepted.append(trade)
        active.append(trade)
        pending_realization.append(trade)
    return accepted, {
        "skipped_cluster_overlap": skipped_cluster,
        "skipped_account_capacity": skipped_capacity,
        "skipped_daily_loss": skipped_daily_loss,
    }


def _annual_gate(
    selected: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
) -> dict[str, Any]:
    trades, _ = _accepted_portfolio_trades(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    years: dict[str, Any] = {}
    for year in (2022, 2023, 2024):
        members = [trade for trade in trades if trade.session_date.year == year]
        years[str(year)] = {
            "trades": len(members),
            "total_net_r": round(sum(trade.net_r for trade in members), 6),
            "expectancy_r": (
                round(statistics.mean(trade.net_r for trade in members), 6) if members else None
            ),
        }
    return {
        "passed": all(
            result["trades"] >= 30
            and result["expectancy_r"] is not None
            and float(result["expectancy_r"]) > 0
            for result in years.values()
        ),
        "years": years,
    }


def _target_gate(
    base: dict[str, Any],
    stressed: dict[str, Any],
) -> dict[str, Any]:
    periods = ("discovery", "validation_2023", "forward_2024")
    ten_r = {
        period: (
            base[period]["average_monthly_r"] is not None
            and float(base[period]["average_monthly_r"]) >= 10
        )
        for period in periods
    }
    positive_stress = {
        period: (
            stressed[period]["net_expectancy_r"] is not None
            and float(stressed[period]["net_expectancy_r"]) > 0
        )
        for period in periods
    }
    stable_months = {
        period: (
            base[period]["median_monthly_r"] is not None
            and float(base[period]["median_monthly_r"]) > 0
            and float(base[period]["positive_month_pct"]) >= 55
        )
        for period in periods
    }
    return {
        "passed_screen": bool(
            ten_r
            and all(ten_r.values())
            and all(positive_stress.values())
            and all(stable_months.values())
            and base["max_positive_profit_share_pct"] <= 60
        ),
        "period_10r_checks": ten_r,
        "positive_expectancy_at_1_50x_costs": positive_stress,
        "positive_median_and_55pct_positive_months": stable_months,
        "diversification_check": base["max_positive_profit_share_pct"] <= 60,
        "requires_minute_validation": True,
    }


def _session_context(
    bars_by_open: dict[datetime, Bar],
    *,
    range_start: datetime,
    atr: float,
    opening_range_width: float,
    opening_range_percentile: float | None,
) -> dict[str, float | None]:
    recent = bars_by_open.get(range_start - timedelta(minutes=5))
    prior_60 = bars_by_open.get(range_start - timedelta(minutes=65))
    prior_240 = bars_by_open.get(range_start - timedelta(minutes=245))
    return {
        "opening_range_atr": opening_range_width / atr,
        "opening_range_percentile": opening_range_percentile,
        "trend_60_atr": (
            (recent.close - prior_60.close) / atr
            if recent is not None and prior_60 is not None
            else None
        ),
        "trend_240_atr": (
            (recent.close - prior_240.close) / atr
            if recent is not None and prior_240 is not None
            else None
        ),
    }


def _complete_path(
    bars_by_open: dict[datetime, Bar],
    *,
    start: datetime,
    end: datetime,
) -> list[Bar] | None:
    expected = [
        start + timedelta(minutes=offset)
        for offset in range(0, int((end - start).total_seconds() // 60), 5)
    ]
    path = [bars_by_open.get(timestamp) for timestamp in expected]
    if any(bar is None for bar in path):
        return None
    return [bar for bar in path if bar is not None]


def _relative_volume(
    bars: Sequence[Bar],
    index: int,
) -> float | None:
    history = [bar.volume for bar in bars[max(0, index - 12) : index]]
    if len(history) < 6:
        return None
    baseline = statistics.median(history)
    return bars[index].volume / baseline if baseline > 0 else None


def _prior_percentile(
    history: Sequence[float],
    value: float,
) -> float | None:
    if len(history) < 40:
        return None
    return sum(member <= value for member in history) / len(history) * 100


def _evidence(signal: Signal, key: str) -> float:
    value = signal.evidence.get(key)
    return float(value) if value is not None else math.nan


def _or_nan(value: float | None) -> float:
    return float(value) if value is not None else math.nan


def _coverage(bars: Sequence[Bar]) -> dict[str, Any]:
    return {
        "five_minute_bars": len(bars),
        "first_open": bars[0].open_time.isoformat() if bars else None,
        "last_open": bars[-1].open_time.isoformat() if bars else None,
    }


def _signal_funnel(signals: Sequence[Signal]) -> dict[str, int]:
    return {
        playbook: sum(signal.playbook == playbook for signal in signals)
        for playbook in sorted({signal.playbook for signal in signals})
    }


def _write_cache(
    managed: Sequence[ManagedResult],
    destination: Path,
) -> None:
    rows: list[dict[str, Any]] = []
    for result in managed:
        signal = result.signal
        trade = result.trade
        rows.append(
            {
                "playbook": trade.playbook,
                "session_date": trade.session_date.isoformat(),
                "side": trade.side,
                "signal_time": trade.signal_time.isoformat(),
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat(),
                "exit_reason": trade.exit_reason,
                "manager": result.manager,
                "cost_multiplier": result.cost_multiplier,
                "gross_r": trade.gross_r,
                "net_r": trade.net_r,
                "cost_r": trade.cost_r,
                "mfe_r": trade.mfe_r,
                "mae_r": trade.mae_r,
                "holding_minutes": trade.holding_minutes,
                "risk_distance": trade.risk_distance,
                **signal.evidence,
            },
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    pd.DataFrame(rows).to_csv(
        temporary,
        index=False,
        compression="gzip",
    )
    temporary.replace(destination)


def _phase(name: str, started: float) -> None:
    print(
        f"{name} elapsed={time.perf_counter() - started:.3f}s",
        flush=True,
        file=__import__("sys").stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
