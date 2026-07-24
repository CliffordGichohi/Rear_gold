from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from gold_intel.analytics.fundamentals import (
    FUNDAMENTAL_RULESET_VERSION,
    FundamentalState,
)
from gold_intel.analytics.liquidity import (
    LIQUIDITY_RULESET_VERSION,
    LiquidityBar,
    calculate_liquidity_snapshot,
)
from gold_intel.domain.rulesets import BOOK_RULESET_VERSION

TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
StrategyMode = Literal["PRICE_ONLY_CONTROL", "FUNDAMENTAL_ALIGNED"]


@dataclass(frozen=True, slots=True)
class BacktestBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    available_at: datetime
    spread_points: int | None = None
    spread_price: float | None = None


@dataclass(frozen=True, slots=True)
class FiveMinuteBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    complete: bool


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    strategy_mode: StrategyMode = "PRICE_ONLY_CONTROL"
    initial_equity: float = 10_000.0
    risk_per_trade_pct: float = 1.0
    asia_start_local: str = "10:05"
    asia_end_local: str = "16:00"
    confirmation_bars: int = 2
    breakout_buffer_atr: float = 0.10
    stop_atr_multiple: float = 1.50
    target_r: float = 2.0
    spread_price: float = 0.30
    slippage_price: float = 0.05
    commission_per_lot_round_turn: float = 7.0
    contract_size: float = 100.0
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lots: float = 10.0
    fundamental_min_score: float = 5.0
    fundamental_min_coverage: float = 35.0
    fundamental_min_confidence: float = 25.0
    block_high_impact_events: bool = True
    block_elevated_or_abnormal_liquidity: bool = True
    allow_unknown_liquidity: bool = False


@dataclass(frozen=True, slots=True)
class TradeResult:
    sequence: int
    side: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    reference_entry_price: float
    reference_exit_price: float
    stop_price: float
    target_price: float
    quantity_lots: float
    exit_reason: str
    gross_pnl: float
    costs: float
    net_pnl: float
    r_multiple: float
    mfe_r: float
    mae_r: float
    holding_minutes: int
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BacktestResult:
    strategy: str
    metrics: dict[str, Any]
    trades: tuple[TradeResult, ...]
    equity_curve: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _AsiaRange:
    session_date: date
    high: float
    low: float
    bar_count: int


def run_asia_range_acceptance(
    bars: list[BacktestBar],
    *,
    start: datetime,
    end: datetime,
    config: StrategyConfig,
    fundamental_state_at: Callable[[datetime], FundamentalState] | None = None,
) -> BacktestResult:
    """Run the first auditable structure strategy.

    The Tokyo range is complete before the London decision window. A signal is
    calculated only from closed, point-in-time-available bars and is executed at
    the next complete five-minute bar open.
    """

    _validate_inputs(bars, start, end, config)
    if config.strategy_mode == "FUNDAMENTAL_ALIGNED" and fundamental_state_at is None:
        raise ValueError("FUNDAMENTAL_ALIGNED mode requires a point-in-time fundamental evaluator.")
    five_minute = aggregate_point_in_time_five_minutes(bars, end)
    complete_count = sum(bar.complete for bar in five_minute)
    atr_by_time = _atr_by_time(five_minute, window=14)
    asia_start = _parse_local_session_time(config.asia_start_local)
    asia_end = _parse_local_session_time(config.asia_end_local)
    asia_ranges = _asia_ranges(
        five_minute,
        start_local=asia_start,
        end_local=asia_end,
    )
    data_hash = _data_hash(bars)
    liquidity_bars = [
        LiquidityBar(
            open_time=item.open_time,
            close_time=item.close_time,
            high=item.high,
            low=item.low,
            close=item.close,
            tick_volume=item.volume,
            spread_points=item.spread_points,
            spread_price=item.spread_price,
            available_at=item.available_at,
        )
        for item in bars
    ]

    trades: list[TradeResult] = []
    equity_curve: list[dict[str, Any]] = [
        {"timestamp": start.isoformat(), "equity": round(config.initial_equity, 2)}
    ]
    equity = config.initial_equity
    traded_dates: set[date] = set()
    gate_evaluated_dates: set[date] = set()
    blackout_signatures: dict[date, tuple[str, str | None, str | None]] = {}
    confirmations: dict[date, dict[str, list[FiveMinuteBar]]] = defaultdict(
        lambda: {"LONG": [], "SHORT": []}
    )
    skipped_incomplete_sessions = 0
    mechanical_candidates = 0
    permitted_candidates = 0
    rejection_reasons: dict[str, int] = defaultdict(int)
    gate_decisions: list[dict[str, Any]] = []

    for index, bar in enumerate(five_minute):
        if (
            not bar.complete
            or bar.open_time < start
            or bar.close_time > end
            or bar.open_time not in atr_by_time
        ):
            continue

        london_open = bar.open_time.astimezone(LONDON)
        london_close = bar.close_time.astimezone(LONDON)
        session_date = london_open.date()
        if session_date in traded_dates:
            continue
        if config.strategy_mode == "FUNDAMENTAL_ALIGNED" and session_date in gate_evaluated_dates:
            continue
        if not (
            time(8, 0) <= london_open.time() < time(12, 0) and london_close.date() == session_date
        ):
            continue

        asia = asia_ranges.get(session_date)
        if asia is None:
            skipped_incomplete_sessions += 1
            continue

        atr = atr_by_time[bar.open_time]
        buffer = atr * config.breakout_buffer_atr
        upper = asia.high + buffer
        lower = asia.low - buffer
        state = confirmations[session_date]
        if bar.close > upper:
            state["LONG"].append(bar)
            state["SHORT"].clear()
        elif bar.close < lower:
            state["SHORT"].append(bar)
            state["LONG"].clear()
        else:
            state["LONG"].clear()
            state["SHORT"].clear()

        side: Literal["LONG", "SHORT"] | None = None
        if len(state["LONG"]) >= config.confirmation_bars:
            side = "LONG"
        elif len(state["SHORT"]) >= config.confirmation_bars:
            side = "SHORT"
        if side is None:
            continue

        entry_index = index + 1
        if entry_index >= len(five_minute):
            continue
        entry_bar = five_minute[entry_index]
        if (
            not entry_bar.complete
            or entry_bar.open_time != bar.close_time
            or entry_bar.open_time.astimezone(LONDON).date() != session_date
            or entry_bar.open_time.astimezone(LONDON).time() >= time(12, 0)
        ):
            continue

        fundamental_state: FundamentalState | None = None
        liquidity_snapshot = None
        if config.strategy_mode == "FUNDAMENTAL_ALIGNED":
            if fundamental_state_at is None:  # pragma: no cover - validated above
                raise RuntimeError("Missing fundamental evaluator")
            fundamental_state = fundamental_state_at(bar.close_time)
            liquidity_snapshot = calculate_liquidity_snapshot(
                liquidity_bars,
                bar.close_time,
                provider_code="BACKTEST_SOURCE",
            )
            if config.block_high_impact_events and fundamental_state.event_risk in {
                "HIGH",
                "EXTREME",
            }:
                catalyst = fundamental_state.upcoming_catalyst or {}
                blackout_signature = (
                    side,
                    str(catalyst.get("event_code"))
                    if catalyst.get("event_code") is not None
                    else None,
                    str(catalyst.get("scheduled_at"))
                    if catalyst.get("scheduled_at") is not None
                    else None,
                )
                if blackout_signatures.get(session_date) == blackout_signature:
                    continue
                blackout_signatures[session_date] = blackout_signature
                permitted, reason = False, "MAJOR_EVENT_BLACKOUT"
            else:
                permitted, reason = fundamental_state.permission(
                    side,
                    minimum_score=config.fundamental_min_score,
                    minimum_coverage=config.fundamental_min_coverage,
                    minimum_confidence=config.fundamental_min_confidence,
                )
            if permitted and config.block_elevated_or_abnormal_liquidity:
                if liquidity_snapshot.status in {"ELEVATED", "ABNORMAL"}:
                    permitted, reason = False, "LIQUIDITY_RISK_GATE"
                elif (
                    liquidity_snapshot.status == "UNKNOWN"
                    and not config.allow_unknown_liquidity
                ):
                    permitted, reason = False, "LIQUIDITY_UNKNOWN_GATE"
            mechanical_candidates += 1
            gate_decisions.append(
                {
                    "signal_time": bar.close_time.isoformat(),
                    "side": side,
                    "permitted": permitted,
                    "reason": reason,
                    "directional_score": fundamental_state.directional_score,
                    "confidence": fundamental_state.confidence,
                    "coverage": fundamental_state.coverage,
                    "bias": fundamental_state.bias_label,
                    "regime": fundamental_state.regime_label,
                    "dominant_driver": fundamental_state.dominant_driver,
                    "main_contradiction": fundamental_state.main_contradiction,
                    "event_risk": fundamental_state.event_risk,
                    "upcoming_catalyst": fundamental_state.upcoming_catalyst,
                    "fundamental_data_hash": fundamental_state.data_hash,
                    "liquidity": {
                        "status": liquidity_snapshot.status,
                        "execution_confidence_multiplier": (
                            liquidity_snapshot.execution_confidence_multiplier
                        ),
                        "data_quality_score": liquidity_snapshot.data_quality_score,
                        "freshness_score": liquidity_snapshot.freshness_score,
                        "data_hash": liquidity_snapshot.data_hash,
                        "warnings": list(liquidity_snapshot.warnings),
                    },
                }
            )
            if not permitted:
                rejection_reasons[reason] += 1
                if reason != "MAJOR_EVENT_BLACKOUT":
                    gate_evaluated_dates.add(session_date)
                continue
            permitted_candidates += 1
        else:
            mechanical_candidates += 1
            permitted_candidates += 1

        confirmation = state[side][-config.confirmation_bars :]
        trade = _simulate_trade(
            bars=five_minute,
            entry_index=entry_index,
            end=end,
            side=side,
            signal_time=bar.close_time,
            atr=atr,
            asia=asia,
            confirmation=confirmation,
            equity=equity,
            config=config,
            sequence=len(trades) + 1,
        )
        if trade is None:
            continue
        if fundamental_state is not None:
            trade = replace(
                trade,
                evidence={
                    **trade.evidence,
                    "fundamental_permission": {
                        "ruleset_version": FUNDAMENTAL_RULESET_VERSION,
                        "as_of": fundamental_state.as_of.isoformat(),
                        "directional_score": fundamental_state.directional_score,
                        "confidence": fundamental_state.confidence,
                        "coverage": fundamental_state.coverage,
                        "bias": fundamental_state.bias_label,
                        "regime": fundamental_state.regime_label,
                        "dominant_driver": fundamental_state.dominant_driver,
                        "main_contradiction": fundamental_state.main_contradiction,
                        "event_risk": fundamental_state.event_risk,
                        "upcoming_catalyst": fundamental_state.upcoming_catalyst,
                        "components": [
                            asdict(component) for component in fundamental_state.components
                        ],
                        "data_hash": fundamental_state.data_hash,
                    },
                    "session_liquidity_gate": (
                        {
                            "ruleset_version": LIQUIDITY_RULESET_VERSION,
                            "status": liquidity_snapshot.status,
                            "execution_confidence_multiplier": (
                                liquidity_snapshot.execution_confidence_multiplier
                            ),
                            "data_quality_score": liquidity_snapshot.data_quality_score,
                            "freshness_score": liquidity_snapshot.freshness_score,
                            "data_hash": liquidity_snapshot.data_hash,
                            "warnings": list(liquidity_snapshot.warnings),
                        }
                        if liquidity_snapshot is not None
                        else None
                    ),
                },
            )
        trades.append(trade)
        equity += trade.net_pnl
        equity_curve.append({"timestamp": trade.exit_time.isoformat(), "equity": round(equity, 2)})
        traded_dates.add(session_date)

    metrics = calculate_metrics(
        trades,
        initial_equity=config.initial_equity,
        final_equity=equity,
        start=start,
        end=end,
        bars=five_minute,
    )
    metrics.update(
        {
            "mechanical_candidates": mechanical_candidates,
            "fundamental_gate_permitted": permitted_candidates,
            "fundamental_gate_rejected": sum(rejection_reasons.values()),
            "fundamental_gate_rejection_reasons": dict(sorted(rejection_reasons.items())),
        }
    )
    return BacktestResult(
        strategy=(
            "BOOK_ALIGNED_ASIA_ACCEPTANCE_RESEARCH_V1"
            if config.strategy_mode == "FUNDAMENTAL_ALIGNED"
            else "ASIA_RANGE_ACCEPTANCE_V1"
        ),
        metrics=metrics,
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
        provenance={
            "data_hash_sha256": data_hash,
            "source_1m_bars": len(bars),
            "aggregated_5m_bars": len(five_minute),
            "complete_5m_bars": complete_count,
            "complete_asia_sessions": len(asia_ranges),
            "skipped_incomplete_session_observations": skipped_incomplete_sessions,
            "decision_clock": "bar_close",
            "fill_clock": "next_complete_5m_bar_open",
            "intrabar_policy": "STOP_FIRST_IF_STOP_AND_TARGET_TOUCH_SAME_BAR",
            "strategy_mode": config.strategy_mode,
            "book_ruleset_version": BOOK_RULESET_VERSION,
            "fundamental_gate": {
                "ruleset_version": (
                    FUNDAMENTAL_RULESET_VERSION
                    if config.strategy_mode == "FUNDAMENTAL_ALIGNED"
                    else None
                ),
                "minimum_score": config.fundamental_min_score,
                "minimum_coverage": config.fundamental_min_coverage,
                "minimum_confidence": config.fundamental_min_confidence,
                "block_high_impact_events": config.block_high_impact_events,
                "block_elevated_or_abnormal_liquidity": (
                    config.block_elevated_or_abnormal_liquidity
                ),
                "allow_unknown_liquidity": config.allow_unknown_liquidity,
                "decisions": gate_decisions,
            },
            "book_alignment_scope": {
                "directional_layers": [1, 2, 3, 4, 6],
                "execution_gate_layers": [5, 7],
                "implemented_in_this_strategy": [
                    "point-in-time fundamental permission",
                    "event blackout",
                    "session window",
                    "broker-spread liquidity gate",
                    "two-close price acceptance",
                    "structure/ATR stop",
                    "risk-based sizing",
                    "target and transaction costs",
                ],
                "not_claimed": [
                    "portfolio cluster exposure",
                    "multi-position total open risk",
                    "account daily-loss state",
                    "licensed options/dealer gamma",
                    "complete ETF and central-bank flow history",
                ],
            },
            "session_definition": {
                "asia": (
                    f"{config.asia_start_local}-{config.asia_end_local} "
                    "Asia/Tokyo (after IC Markets maintenance)"
                ),
                "entry": "08:00-12:00 Europe/London",
                "forced_exit": "16:00 America/New_York",
            },
            "config": asdict(config),
        },
    )


def aggregate_point_in_time_five_minutes(
    bars: list[BacktestBar], as_of: datetime
) -> list[FiveMinuteBar]:
    """Aggregate only the earliest version known by each five-minute close."""

    canonical: dict[datetime, BacktestBar] = {}
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        if bar.close_time <= as_of:
            canonical.setdefault(bar.open_time, bar)

    buckets: dict[datetime, list[BacktestBar]] = defaultdict(list)
    for bar in canonical.values():
        bucket = bar.open_time.replace(
            minute=bar.open_time.minute - bar.open_time.minute % 5,
            second=0,
            microsecond=0,
        )
        buckets[bucket].append(bar)

    output: list[FiveMinuteBar] = []
    for bucket, members in sorted(buckets.items()):
        members.sort(key=lambda item: item.open_time)
        close_time = bucket + timedelta(minutes=5)
        expected = {bucket + timedelta(minutes=offset) for offset in range(5)}
        actual = {member.open_time for member in members}
        complete = (
            len(members) == 5
            and actual == expected
            and all(member.available_at <= close_time for member in members)
        )
        volume = None
        if all(member.volume is not None for member in members):
            volume = sum(member.volume or 0 for member in members)
        output.append(
            FiveMinuteBar(
                open_time=bucket,
                close_time=close_time,
                open=members[0].open,
                high=max(member.high for member in members),
                low=min(member.low for member in members),
                close=members[-1].close,
                volume=volume,
                complete=complete,
            )
        )
    return output


def calculate_metrics(
    trades: list[TradeResult],
    *,
    initial_equity: float,
    final_equity: float,
    start: datetime,
    end: datetime,
    bars: list[FiveMinuteBar],
) -> dict[str, Any]:
    r_values = [trade.r_multiple for trade in trades]
    net_values = [trade.net_pnl for trade in trades]
    winners = [value for value in net_values if value > 0]
    losers = [value for value in net_values if value < 0]
    equity = initial_equity
    peak = equity
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    daily_pnl: dict[date, float] = defaultdict(float)
    by_side: dict[str, list[TradeResult]] = defaultdict(list)
    by_year: dict[str, list[TradeResult]] = defaultdict(list)
    by_month: dict[str, list[TradeResult]] = defaultdict(list)
    by_regime: dict[str, list[TradeResult]] = defaultdict(list)
    by_signal_hour_utc: dict[str, list[TradeResult]] = defaultdict(list)
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        max_drawdown = max(max_drawdown, drawdown)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, drawdown / peak * 100)
        daily_pnl[trade.exit_time.date()] += trade.net_pnl
        by_side[trade.side].append(trade)
        by_year[str(trade.exit_time.year)].append(trade)
        by_month[trade.exit_time.strftime("%Y-%m")].append(trade)
        permission = trade.evidence.get("fundamental_permission")
        regime = (
            str(permission.get("regime", "UNKNOWN"))
            if isinstance(permission, dict)
            else "UNFILTERED_CONTROL"
        )
        by_regime[regime].append(trade)
        by_signal_hour_utc[f"{trade.signal_time.hour:02d}:00"].append(trade)

    daily_returns = [value / initial_equity for value in daily_pnl.values()]
    sharpe = _annualized_sharpe(daily_returns)
    sortino = _annualized_sortino(daily_returns)
    ci_low: float | None = None
    ci_high: float | None = None
    if len(r_values) >= 2:
        margin = 1.96 * statistics.stdev(r_values) / math.sqrt(len(r_values))
        ci_low = statistics.mean(r_values) - margin
        ci_high = statistics.mean(r_values) + margin
    bootstrap_ci = _bootstrap_mean_interval(r_values)

    benchmark_return_pct: float | None = None
    complete = [bar for bar in bars if bar.complete and start <= bar.open_time < end]
    if len(complete) >= 2 and complete[0].open:
        benchmark_return_pct = (complete[-1].close / complete[0].open - 1) * 100

    return {
        "observations": len(complete),
        "trades": len(trades),
        "wins": len(winners),
        "losses": len(losers),
        "win_rate_pct": _percent(len(winners), len(trades)),
        "average_r": _mean(r_values),
        "median_r": _median(r_values),
        "expectancy_r": _mean(r_values),
        "expectancy_r_95ci": [
            _rounded(ci_low),
            _rounded(ci_high),
        ],
        "expectancy_r_bootstrap_95ci": [
            _rounded(bootstrap_ci[0]),
            _rounded(bootstrap_ci[1]),
        ],
        "profit_factor": (
            _rounded(sum(winners) / abs(sum(losers))) if losers and winners else None
        ),
        "total_net_pnl": _rounded(sum(net_values)),
        "total_costs": _rounded(sum(trade.costs for trade in trades)),
        "return_pct": _rounded((final_equity / initial_equity - 1) * 100),
        "final_equity": _rounded(final_equity),
        "maximum_drawdown": _rounded(max_drawdown),
        "maximum_drawdown_pct": _rounded(max_drawdown_pct),
        "sharpe_ratio": _rounded(sharpe),
        "sortino_ratio": _rounded(sortino),
        "average_mfe_r": _mean([trade.mfe_r for trade in trades]),
        "average_mae_r": _mean([trade.mae_r for trade in trades]),
        "average_holding_minutes": _mean([float(trade.holding_minutes) for trade in trades]),
        "benchmark_buy_hold_pct": _rounded(benchmark_return_pct),
        "performance_by_side": {
            side: _group_metrics(group) for side, group in sorted(by_side.items())
        },
        "performance_by_year": {
            year: _group_metrics(group) for year, group in sorted(by_year.items())
        },
        "performance_by_month": {
            month: _group_metrics(group) for month, group in sorted(by_month.items())
        },
        "performance_by_regime": {
            regime: _group_metrics(group) for regime, group in sorted(by_regime.items())
        },
        "performance_by_signal_hour_utc": {
            hour: _group_metrics(group) for hour, group in sorted(by_signal_hour_utc.items())
        },
        "monte_carlo_trade_order": _trade_order_monte_carlo(
            trades,
            initial_equity=initial_equity,
        ),
    }


def _simulate_trade(
    *,
    bars: list[FiveMinuteBar],
    entry_index: int,
    end: datetime,
    side: str,
    signal_time: datetime,
    atr: float,
    asia: _AsiaRange,
    confirmation: list[FiveMinuteBar],
    equity: float,
    config: StrategyConfig,
    sequence: int,
) -> TradeResult | None:
    direction = 1.0 if side == "LONG" else -1.0
    entry_bar = bars[entry_index]
    reference_entry = entry_bar.open
    risk_distance = atr * config.stop_atr_multiple
    if risk_distance <= 0:
        return None

    risk_budget = equity * config.risk_per_trade_pct / 100
    raw_lots = risk_budget / (risk_distance * config.contract_size)
    quantity = math.floor(raw_lots / config.lot_step + 1e-12) * config.lot_step
    quantity = min(quantity, config.max_lots)
    if quantity < config.min_lot:
        return None
    quantity = round(quantity, 8)

    stop = reference_entry - direction * risk_distance
    target = reference_entry + direction * config.target_r * risk_distance
    half_spread = config.spread_price / 2
    entry_price = reference_entry + direction * (half_spread + config.slippage_price)
    reference_exit = entry_bar.close
    exit_reason = "END_OF_DATA"
    exit_time = entry_bar.close_time
    favorable = 0.0
    adverse = 0.0

    for bar in bars[entry_index:]:
        if not bar.complete or bar.open_time >= end:
            continue
        if side == "LONG":
            stop_hit = bar.low <= stop
            target_hit = bar.high >= target
            bar_favorable = max(0.0, bar.high - reference_entry)
            bar_adverse = max(0.0, reference_entry - bar.low)
        else:
            stop_hit = bar.high >= stop
            target_hit = bar.low <= target
            bar_favorable = max(0.0, reference_entry - bar.low)
            bar_adverse = max(0.0, bar.high - reference_entry)

        if stop_hit:
            reference_exit = stop
            exit_reason = "STOP"
            exit_time = bar.close_time
            adverse = max(adverse, risk_distance)
            break
        favorable = max(favorable, bar_favorable)
        adverse = max(adverse, bar_adverse)
        if target_hit:
            reference_exit = target
            exit_reason = "TARGET"
            exit_time = bar.close_time
            favorable = max(favorable, config.target_r * risk_distance)
            break
        if bar.close_time.astimezone(NEW_YORK).time() >= time(16, 0):
            reference_exit = bar.close
            exit_reason = "NEW_YORK_CUTOFF"
            exit_time = bar.close_time
            break
        reference_exit = bar.close
        exit_time = bar.close_time

    exit_price = reference_exit - direction * (half_spread + config.slippage_price)
    gross_pnl = direction * (reference_exit - reference_entry) * config.contract_size * quantity
    execution_pnl = direction * (exit_price - entry_price) * config.contract_size * quantity
    commission = config.commission_per_lot_round_turn * quantity
    net_pnl = execution_pnl - commission
    costs = gross_pnl - net_pnl
    planned_risk = risk_distance * config.contract_size * quantity
    r_multiple = net_pnl / planned_risk
    holding_minutes = int((exit_time - entry_bar.open_time).total_seconds() // 60)

    return TradeResult(
        sequence=sequence,
        side=side,
        signal_time=signal_time,
        entry_time=entry_bar.open_time,
        exit_time=exit_time,
        entry_price=round(entry_price, 6),
        exit_price=round(exit_price, 6),
        reference_entry_price=round(reference_entry, 6),
        reference_exit_price=round(reference_exit, 6),
        stop_price=round(stop, 6),
        target_price=round(target, 6),
        quantity_lots=quantity,
        exit_reason=exit_reason,
        gross_pnl=round(gross_pnl, 2),
        costs=round(costs, 2),
        net_pnl=round(net_pnl, 2),
        r_multiple=round(r_multiple, 6),
        mfe_r=round(favorable / risk_distance, 6),
        mae_r=round(adverse / risk_distance, 6),
        holding_minutes=holding_minutes,
        evidence={
            "asia_session_date": asia.session_date.isoformat(),
            "asia_high": round(asia.high, 6),
            "asia_low": round(asia.low, 6),
            "asia_complete_5m_bars": asia.bar_count,
            "atr14": round(atr, 6),
            "breakout_buffer": round(atr * config.breakout_buffer_atr, 6),
            "confirmation_closes": [round(item.close, 6) for item in confirmation],
            "confirmation_times": [item.close_time.isoformat() for item in confirmation],
            "planned_risk_usd": round(planned_risk, 2),
        },
    )


def _asia_ranges(
    bars: list[FiveMinuteBar],
    *,
    start_local: time,
    end_local: time,
) -> dict[date, _AsiaRange]:
    expected_bars = (
        (end_local.hour * 60 + end_local.minute)
        - (start_local.hour * 60 + start_local.minute)
    ) // 5
    groups: dict[date, list[FiveMinuteBar]] = defaultdict(list)
    for bar in bars:
        if not bar.complete:
            continue
        local_open = bar.open_time.astimezone(TOKYO)
        local_close = bar.close_time.astimezone(TOKYO)
        if (
            start_local <= local_open.time() < end_local
            and local_close.date() == local_open.date()
            and local_close.time() <= end_local
        ):
            groups[local_open.date()].append(bar)

    output: dict[date, _AsiaRange] = {}
    for session_date, members in groups.items():
        if len(members) != expected_bars:
            continue
        members.sort(key=lambda item: item.open_time)
        if any(
            current.open_time != prior.close_time
            for prior, current in zip(members, members[1:], strict=False)
        ):
            continue
        output[session_date] = _AsiaRange(
            session_date=session_date,
            high=max(item.high for item in members),
            low=min(item.low for item in members),
            bar_count=len(members),
        )
    return output


def _atr_by_time(bars: list[FiveMinuteBar], window: int) -> dict[datetime, float]:
    output: dict[datetime, float] = {}
    true_ranges: list[float] = []
    prior_close: float | None = None
    for bar in bars:
        if not bar.complete:
            continue
        true_range = bar.high - bar.low
        if prior_close is not None:
            true_range = max(
                true_range,
                abs(bar.high - prior_close),
                abs(bar.low - prior_close),
            )
        true_ranges.append(true_range)
        prior_close = bar.close
        if len(true_ranges) >= window:
            output[bar.open_time] = statistics.mean(true_ranges[-window:])
    return output


def _validate_inputs(
    bars: list[BacktestBar], start: datetime, end: datetime, config: StrategyConfig
) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Backtest timestamps must include a timezone.")
    if start >= end:
        raise ValueError("Backtest start must precede end.")
    if not bars:
        raise ValueError("No price bars were supplied.")
    if any(
        bar.open_time.tzinfo is None
        or bar.close_time.tzinfo is None
        or bar.available_at.tzinfo is None
        for bar in bars
    ):
        raise ValueError("All price-bar timestamps must include a timezone.")
    if not 0 < config.risk_per_trade_pct <= 5:
        raise ValueError("risk_per_trade_pct must be in (0, 5].")
    if config.confirmation_bars not in {1, 2, 3}:
        raise ValueError("confirmation_bars must be 1, 2, or 3.")
    if config.strategy_mode not in {"PRICE_ONLY_CONTROL", "FUNDAMENTAL_ALIGNED"}:
        raise ValueError("Unsupported strategy_mode.")
    asia_start = _parse_local_session_time(config.asia_start_local)
    asia_end = _parse_local_session_time(config.asia_end_local)
    asia_start_minutes = asia_start.hour * 60 + asia_start.minute
    asia_end_minutes = asia_end.hour * 60 + asia_end.minute
    if asia_start_minutes >= asia_end_minutes:
        raise ValueError("asia_start_local must precede asia_end_local.")
    if (asia_end_minutes - asia_start_minutes) % 5:
        raise ValueError("The Asia range must contain whole five-minute bars.")
    if not 0 <= config.fundamental_min_score <= 100:
        raise ValueError("fundamental_min_score must be in [0, 100].")
    if not 0 <= config.fundamental_min_coverage <= 100:
        raise ValueError("fundamental_min_coverage must be in [0, 100].")
    if not 0 <= config.fundamental_min_confidence <= 100:
        raise ValueError("fundamental_min_confidence must be in [0, 100].")
    if (
        min(
            config.initial_equity,
            config.stop_atr_multiple,
            config.target_r,
            config.contract_size,
            config.min_lot,
            config.lot_step,
            config.max_lots,
        )
        <= 0
    ):
        raise ValueError("Positive backtest configuration values are required.")
    if (
        min(
            config.breakout_buffer_atr,
            config.spread_price,
            config.slippage_price,
            config.commission_per_lot_round_turn,
        )
        < 0
    ):
        raise ValueError("Cost and buffer values cannot be negative.")


def _parse_local_session_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Session times must use HH:MM 24-hour format.") from exc
    if parsed.second or parsed.microsecond or parsed.minute % 5:
        raise ValueError("Session times must align to five-minute boundaries.")
    return parsed


def _data_hash(bars: list[BacktestBar]) -> str:
    digest = hashlib.sha256()
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        row = (
            f"{bar.open_time.isoformat()}|{bar.available_at.isoformat()}|"
            f"{bar.open:.8f}|{bar.high:.8f}|{bar.low:.8f}|{bar.close:.8f}\n"
        )
        digest.update(row.encode())
    return digest.hexdigest()


def _annualized_sharpe(returns: list[float]) -> float | None:
    if len(returns) < 10:
        return None
    deviation = statistics.stdev(returns)
    if deviation == 0:
        return None
    return statistics.mean(returns) / deviation * math.sqrt(252)


def _annualized_sortino(returns: list[float]) -> float | None:
    if len(returns) < 10:
        return None
    downside = [min(0.0, value) for value in returns]
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside))
    if downside_deviation == 0:
        return None
    return statistics.mean(returns) / downside_deviation * math.sqrt(252)


def _group_metrics(trades: list[TradeResult]) -> dict[str, Any]:
    return {
        "trades": len(trades),
        "win_rate_pct": _percent(
            sum(trade.net_pnl > 0 for trade in trades),
            len(trades),
        ),
        "net_pnl": _rounded(sum(trade.net_pnl for trade in trades)),
        "average_r": _mean([trade.r_multiple for trade in trades]),
    }


def _bootstrap_mean_interval(
    values: list[float],
    *,
    iterations: int = 5_000,
) -> tuple[float | None, float | None]:
    if len(values) < 5:
        return None, None
    rng = random.Random(_stable_seed(values, namespace="bootstrap"))
    sample_size = len(values)
    means = sorted(statistics.mean(rng.choices(values, k=sample_size)) for _ in range(iterations))
    return (
        means[int(iterations * 0.025)],
        means[min(iterations - 1, int(iterations * 0.975))],
    )


def _trade_order_monte_carlo(
    trades: list[TradeResult],
    *,
    initial_equity: float,
    iterations: int = 2_000,
) -> dict[str, Any]:
    if len(trades) < 5:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "iterations": 0,
            "trade_count": len(trades),
            "drawdown_pct_p50": None,
            "drawdown_pct_p95": None,
            "drawdown_pct_p99": None,
            "warning": ("At least five trades are required for trade-order reshuffling."),
        }
    pnl = [trade.net_pnl for trade in trades]
    rng = random.Random(_stable_seed(pnl, namespace="trade-order"))
    drawdowns: list[float] = []
    for _ in range(iterations):
        shuffled = pnl.copy()
        rng.shuffle(shuffled)
        equity = initial_equity
        peak = equity
        maximum_drawdown_pct = 0.0
        for value in shuffled:
            equity += value
            peak = max(peak, equity)
            if peak > 0:
                maximum_drawdown_pct = max(
                    maximum_drawdown_pct,
                    (peak - equity) / peak * 100,
                )
        drawdowns.append(maximum_drawdown_pct)
    drawdowns.sort()
    return {
        "status": "COMPLETED",
        "iterations": iterations,
        "trade_count": len(trades),
        "drawdown_pct_p50": _percentile(drawdowns, 0.50),
        "drawdown_pct_p95": _percentile(drawdowns, 0.95),
        "drawdown_pct_p99": _percentile(drawdowns, 0.99),
        "warning": (
            "This reshuffles realized net PnL only. It measures sequence risk "
            "and does not preserve regime clustering or create new trades."
        ),
    }


def _stable_seed(values: list[float], *, namespace: str) -> int:
    payload = namespace + "|" + "|".join(f"{value:.10f}" for value in values)
    return int(hashlib.sha256(payload.encode()).hexdigest()[:16], 16)


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, math.ceil(probability * len(values)) - 1))
    return _rounded(values[index])


def _percent(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 3) if denominator else None


def _mean(values: list[float]) -> float | None:
    return _rounded(statistics.mean(values)) if values else None


def _median(values: list[float]) -> float | None:
    return _rounded(statistics.median(values)) if values else None


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None and math.isfinite(value) else None
