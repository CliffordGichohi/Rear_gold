from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast

from gold_intel.backtesting.engine import TradeResult, calculate_metrics

SESSION_EDGE_EXECUTION_VERSION = "C1_DELAYED_RECLAIM_EXECUTION_V1"
SESSION_EDGE_EXECUTION_METRICS_VERSION = "SESSION_EDGE_EXECUTION_METRICS_V1"

SessionStrategyMode = Literal[
    "DELAYED_RECLAIM_PRICE_CONTROL",
    "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED",
]


@dataclass(frozen=True, slots=True)
class SessionStrategyConfig:
    strategy_mode: SessionStrategyMode = "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED"
    initial_equity: float = 10_000.0
    risk_per_trade_pct: float = 1.0
    target_r: float = 1.0
    max_holding_minutes: int = 240
    slippage_price_per_side: float = 0.05
    commission_per_lot_round_turn: float = 7.0
    cost_multiplier: float = 1.0
    contract_size: float = 100.0
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lots: float = 10.0
    allow_unknown_event_risk: bool = True
    calculate_robustness: bool = True


@dataclass(frozen=True, slots=True)
class SessionStrategySetup:
    source_opportunity_id: str
    source_run_id: str
    source_data_hash: str
    session_date: date
    status: str
    side: str | None
    signal_time: datetime | None
    entry_time: datetime | None
    entry_reference_price: float | None
    invalidation_price: float | None
    risk_distance: float | None
    bias_alignment: str
    event_risk: str
    regime_label: str
    dominant_driver: str | None
    facts: dict[str, Any]
    outcomes: list[dict[str, Any]]
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SessionExecutionBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    spread_price: float | None
    available_at: datetime
    source_record_key: str | None
    complete: bool = True


@dataclass(frozen=True, slots=True)
class SessionStrategyEvaluation:
    strategy: str
    metrics: dict[str, Any]
    trades: tuple[TradeResult, ...]
    equity_curve: tuple[dict[str, Any], ...]
    exclusions: dict[str, int]
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _PortfolioResult:
    trades: tuple[TradeResult, ...]
    equity_curve: tuple[dict[str, Any], ...]
    exclusions: dict[str, int]
    final_equity: float


def run_delayed_reclaim_strategy(
    setups: Sequence[SessionStrategySetup],
    bars: Sequence[SessionExecutionBar],
    *,
    start: datetime,
    end: datetime,
    config: SessionStrategyConfig | None = None,
) -> SessionStrategyEvaluation:
    selected = config or SessionStrategyConfig()
    _validate_inputs(setups, bars, start=start, end=end, config=selected)
    canonical_bars = _canonical_bars(bars)
    centre = _simulate_portfolio(setups, canonical_bars, config=selected)
    metrics = calculate_metrics(
        list(centre.trades),
        initial_equity=selected.initial_equity,
        final_equity=centre.final_equity,
        start=start,
        end=end,
        bars=[],
    )
    metrics.update(
        _execution_metrics(
            setups,
            centre,
            strategy_mode=selected.strategy_mode,
        )
    )
    if selected.calculate_robustness:
        metrics["robustness"] = _robustness_summary(
            setups,
            canonical_bars,
            selected,
        )
        metrics["development_gate"] = _development_gate(metrics)

    config_payload = _jsonable(asdict(selected))
    config_hash = _sha256(config_payload)
    bar_hash = _bar_hash(canonical_bars)
    source_hash = _sha256(
        [
            {
                "opportunity_id": item.source_opportunity_id,
                "run_id": item.source_run_id,
                "data_hash": item.source_data_hash,
            }
            for item in sorted(
                setups,
                key=lambda row: (row.session_date, row.source_opportunity_id),
            )
        ]
    )
    combined_hash = _sha256(
        {
            "execution_version": SESSION_EDGE_EXECUTION_VERSION,
            "metrics_version": SESSION_EDGE_EXECUTION_METRICS_VERSION,
            "config_hash": config_hash,
            "source_opportunity_hash": source_hash,
            "execution_bar_hash": bar_hash,
        }
    )
    return SessionStrategyEvaluation(
        strategy=selected.strategy_mode,
        metrics=metrics,
        trades=centre.trades,
        equity_curve=centre.equity_curve,
        exclusions=centre.exclusions,
        provenance={
            "candidate_version": SESSION_EDGE_EXECUTION_VERSION,
            "metrics_version": SESSION_EDGE_EXECUTION_METRICS_VERSION,
            "configuration": config_payload,
            "configuration_hash_sha256": config_hash,
            "source_opportunity_hash_sha256": source_hash,
            "execution_bar_hash_sha256": bar_hash,
            "combined_data_hash_sha256": combined_hash,
            "candidate_count": len(setups),
            "canonical_execution_bar_count": len(canonical_bars),
            "entry_policy": (
                "Market-reference entry at the next complete five-minute bar open "
                "after displacement; observed entry/exit spread, adverse slippage, "
                "and round-turn commission are deducted."
            ),
            "path_policy": (
                "One-minute stop/target replay; a same-minute stop and target is "
                "resolved stop-first. Missing minutes or spreads exclude the setup."
            ),
            "research_status": "RESEARCH / EDGE NOT YET ESTABLISHED",
        },
    )


def required_execution_windows(
    setups: Sequence[SessionStrategySetup],
    *,
    maximum_minutes: int = 300,
) -> tuple[tuple[datetime, datetime], ...]:
    windows: list[tuple[datetime, datetime]] = []
    for setup in setups:
        if setup.entry_time is None:
            continue
        windows.append(
            (
                setup.entry_time.astimezone(UTC),
                setup.entry_time.astimezone(UTC) + timedelta(minutes=maximum_minutes),
            )
        )
    return tuple(windows)


def _simulate_portfolio(
    setups: Sequence[SessionStrategySetup],
    bars: dict[datetime, SessionExecutionBar],
    *,
    config: SessionStrategyConfig,
) -> _PortfolioResult:
    equity = config.initial_equity
    trades: list[TradeResult] = []
    exclusions: dict[str, int] = defaultdict(int)
    equity_curve: list[dict[str, Any]] = [
        {
            "timestamp": min(
                (item.entry_time for item in setups if item.entry_time is not None),
                default=datetime.now(UTC),
            ).isoformat(),
            "equity": round(equity, 2),
        }
    ]
    for setup in sorted(
        setups,
        key=lambda item: (
            item.entry_time or datetime.max.replace(tzinfo=UTC),
            item.source_opportunity_id,
        ),
    ):
        reason = _eligibility_reason(setup, config=config)
        if reason is not None:
            exclusions[reason] += 1
            continue
        trade_or_reason = _simulate_setup(
            setup,
            bars,
            equity=equity,
            config=config,
            sequence=len(trades) + 1,
        )
        if isinstance(trade_or_reason, str):
            exclusions[trade_or_reason] += 1
            continue
        trade = trade_or_reason
        trades.append(trade)
        equity += trade.net_pnl
        equity_curve.append(
            {
                "timestamp": trade.exit_time.isoformat(),
                "equity": round(equity, 2),
            }
        )
    return _PortfolioResult(
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
        exclusions=dict(sorted(exclusions.items())),
        final_equity=equity,
    )


def _eligibility_reason(
    setup: SessionStrategySetup,
    *,
    config: SessionStrategyConfig,
) -> str | None:
    if setup.status != "TRIGGERED":
        return "SOURCE_OUTCOME_INCOMPLETE"
    if (
        setup.side not in {"LONG", "SHORT"}
        or setup.signal_time is None
        or setup.entry_time is None
        or setup.entry_reference_price is None
        or setup.invalidation_price is None
        or setup.risk_distance is None
        or setup.risk_distance <= 0
    ):
        return "SOURCE_TRIGGER_INCOMPLETE"
    primary = _primary_attempt(setup)
    if primary is None:
        return "PRIMARY_ATTEMPT_MISSING"
    sweep_time = _optional_datetime(primary.get("sweep_time"))
    reclaim_time = _optional_datetime(primary.get("reclaim_time"))
    if sweep_time is None or reclaim_time is None:
        return "RECLAIM_CLOCK_MISSING"
    if reclaim_time == sweep_time:
        return "SAME_BAR_RECLAIM"
    if reclaim_time < sweep_time:
        return "INVALID_RECLAIM_ORDER"
    longest = _longest_outcome(setup.outcomes)
    if (
        longest is None
        or longest.get("status") != "COMPLETE"
        or int(longest.get("horizon_minutes", 0)) < 240
    ):
        return "SOURCE_240M_PATH_INCOMPLETE"
    if (
        config.strategy_mode == "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED"
        and setup.bias_alignment != "ALIGNED"
    ):
        return f"FUNDAMENTAL_{setup.bias_alignment}"
    if (
        setup.event_risk == "UNKNOWN"
        and not config.allow_unknown_event_risk
    ):
        return "CATALYST_UNKNOWN"
    if setup.event_risk in {"HIGH", "EXTREME"}:
        return "CATALYST_HIGH_OR_EXTREME"
    return None


def _simulate_setup(
    setup: SessionStrategySetup,
    bars: dict[datetime, SessionExecutionBar],
    *,
    equity: float,
    config: SessionStrategyConfig,
    sequence: int,
) -> TradeResult | str:
    side = cast(str, setup.side)
    entry_time = cast(datetime, setup.entry_time).astimezone(UTC)
    reference_entry = cast(float, setup.entry_reference_price)
    stop = cast(float, setup.invalidation_price)
    risk_distance = cast(float, setup.risk_distance)
    direction = 1.0 if side == "LONG" else -1.0

    expected_opens = [
        entry_time + timedelta(minutes=offset)
        for offset in range(config.max_holding_minutes)
    ]
    path = [bars.get(open_time) for open_time in expected_opens]
    if any(item is None or not item.complete for item in path):
        return "EXECUTION_PATH_MISSING_MINUTES"
    complete_path = [cast(SessionExecutionBar, item) for item in path]
    if any(item.available_at > item.close_time for item in complete_path):
        return "EXECUTION_BAR_NOT_POINT_IN_TIME_ELIGIBLE"
    entry_bar = complete_path[0]
    if abs(entry_bar.open - reference_entry) > 0.000001:
        return "ENTRY_REFERENCE_MISMATCH"
    if entry_bar.spread_price is None:
        return "ENTRY_SPREAD_UNKNOWN"

    risk_budget = equity * config.risk_per_trade_pct / 100
    raw_lots = risk_budget / (risk_distance * config.contract_size)
    quantity = math.floor(raw_lots / config.lot_step + 1e-12) * config.lot_step
    quantity = min(quantity, config.max_lots)
    if quantity < config.min_lot:
        return "POSITION_BELOW_MINIMUM_LOT"
    quantity = round(quantity, 8)

    target = reference_entry + direction * config.target_r * risk_distance
    reference_exit = complete_path[-1].close
    exit_bar = complete_path[-1]
    exit_reason = "TIME_240M"
    favourable = 0.0
    adverse = 0.0
    for bar in complete_path:
        if side == "LONG":
            stop_hit = bar.low <= stop
            target_hit = bar.high >= target
            bar_favourable = max(0.0, bar.high - reference_entry)
            bar_adverse = max(0.0, reference_entry - bar.low)
        else:
            stop_hit = bar.high >= stop
            target_hit = bar.low <= target
            bar_favourable = max(0.0, reference_entry - bar.low)
            bar_adverse = max(0.0, bar.high - reference_entry)
        favourable = max(favourable, bar_favourable)
        adverse = max(adverse, bar_adverse)
        if stop_hit:
            reference_exit = stop
            exit_bar = bar
            exit_reason = "STOP"
            adverse = max(adverse, risk_distance)
            break
        if target_hit:
            reference_exit = target
            exit_bar = bar
            exit_reason = "TARGET"
            favourable = max(favourable, config.target_r * risk_distance)
            break

    if exit_bar.spread_price is None:
        return "EXIT_SPREAD_UNKNOWN"
    entry_spread = entry_bar.spread_price
    exit_spread = exit_bar.spread_price
    spread_cost_price = (
        (entry_spread + exit_spread) / 2 * config.cost_multiplier
    )
    slippage_cost_price = (
        2 * config.slippage_price_per_side * config.cost_multiplier
    )
    entry_price = reference_entry + direction * (
        entry_spread / 2 * config.cost_multiplier
        + config.slippage_price_per_side * config.cost_multiplier
    )
    exit_price = reference_exit - direction * (
        exit_spread / 2 * config.cost_multiplier
        + config.slippage_price_per_side * config.cost_multiplier
    )
    gross_pnl = (
        direction
        * (reference_exit - reference_entry)
        * config.contract_size
        * quantity
    )
    execution_pnl = (
        direction * (exit_price - entry_price) * config.contract_size * quantity
    )
    commission = (
        config.commission_per_lot_round_turn
        * quantity
        * config.cost_multiplier
    )
    spread_cost = spread_cost_price * config.contract_size * quantity
    slippage_cost = slippage_cost_price * config.contract_size * quantity
    net_pnl = execution_pnl - commission
    costs = spread_cost + slippage_cost + commission
    planned_risk = risk_distance * config.contract_size * quantity
    gross_r = gross_pnl / planned_risk
    net_r = net_pnl / planned_risk

    return TradeResult(
        sequence=sequence,
        side=side,
        signal_time=cast(datetime, setup.signal_time),
        entry_time=entry_bar.open_time,
        exit_time=exit_bar.close_time,
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
        r_multiple=round(net_r, 6),
        mfe_r=round(favourable / risk_distance, 6),
        mae_r=round(adverse / risk_distance, 6),
        holding_minutes=int(
            (exit_bar.close_time - entry_bar.open_time).total_seconds() // 60
        ),
        evidence={
            "source_opportunity_id": setup.source_opportunity_id,
            "source_study_run_id": setup.source_run_id,
            "source_opportunity_hash": setup.source_data_hash,
            "session_date": setup.session_date.isoformat(),
            "bias_alignment": setup.bias_alignment,
            "event_risk": setup.event_risk,
            "catalyst_verification": (
                "UNVERIFIED" if setup.event_risk == "UNKNOWN" else "KNOWN"
            ),
            "fundamental_permission": {
                "alignment": setup.bias_alignment,
                "regime": setup.regime_label,
                "dominant_driver": setup.dominant_driver,
            },
            "reference_entry_price": round(reference_entry, 6),
            "reference_exit_price": round(reference_exit, 6),
            "risk_distance": round(risk_distance, 6),
            "planned_risk_usd": round(planned_risk, 2),
            "gross_r": round(gross_r, 6),
            "entry_spread_price": round(entry_spread, 6),
            "exit_spread_price": round(exit_spread, 6),
            "spread_cost_usd": round(spread_cost, 2),
            "slippage_cost_usd": round(slippage_cost, 2),
            "commission_usd": round(commission, 2),
            "cost_multiplier": config.cost_multiplier,
            "entry_bar_source_record_key": entry_bar.source_record_key,
            "exit_bar_source_record_key": exit_bar.source_record_key,
        },
    )


def _execution_metrics(
    setups: Sequence[SessionStrategySetup],
    portfolio: _PortfolioResult,
    *,
    strategy_mode: str,
) -> dict[str, Any]:
    trades = list(portfolio.trades)
    gross_values = [
        float(trade.evidence.get("gross_r", 0.0))
        for trade in trades
    ]
    spread_costs = [
        float(trade.evidence.get("spread_cost_usd", 0.0))
        for trade in trades
    ]
    slippage_costs = [
        float(trade.evidence.get("slippage_cost_usd", 0.0))
        for trade in trades
    ]
    commissions = [
        float(trade.evidence.get("commission_usd", 0.0))
        for trade in trades
    ]
    winners = sorted((trade.net_pnl for trade in trades if trade.net_pnl > 0), reverse=True)
    gross_profit = sum(winners)
    total_net = sum(trade.net_pnl for trade in trades)
    return {
        "candidate_version": SESSION_EDGE_EXECUTION_VERSION,
        "strategy_mode": strategy_mode,
        "triggered_opportunities": len(setups),
        "eligible_trades": len(trades),
        "exclusion_funnel": portfolio.exclusions,
        "gross_expectancy_r": _mean(gross_values),
        "net_expectancy_r": _mean([trade.r_multiple for trade in trades]),
        "total_gross_pnl": round(sum(trade.gross_pnl for trade in trades), 2),
        "spread_costs": round(sum(spread_costs), 2),
        "slippage_costs": round(sum(slippage_costs), 2),
        "commissions": round(sum(commissions), 2),
        "unknown_catalyst_trades": sum(
            trade.evidence.get("catalyst_verification") == "UNVERIFIED"
            for trade in trades
        ),
        "largest_winner_share_of_gross_profit_pct": (
            round(winners[0] / gross_profit * 100, 4)
            if winners and gross_profit > 0
            else None
        ),
        "largest_winner_share_of_total_net_profit_pct": (
            round(winners[0] / total_net * 100, 4)
            if winners and total_net > 0
            else None
        ),
    }


def _robustness_summary(
    setups: Sequence[SessionStrategySetup],
    bars: dict[datetime, SessionExecutionBar],
    config: SessionStrategyConfig,
) -> dict[str, Any]:
    cost_stress: list[dict[str, Any]] = []
    for multiplier in (1.0, 1.5, 2.0):
        result = _simulate_portfolio(
            setups,
            bars,
            config=replace(
                config,
                cost_multiplier=multiplier,
                calculate_robustness=False,
            ),
        )
        cost_stress.append(_compact_result(result, label=f"{multiplier:.2f}x"))

    neighbourhood: list[dict[str, Any]] = []
    for target_r in (0.75, 1.0, 1.25):
        for holding_minutes in (180, 240, 300):
            result = _simulate_portfolio(
                setups,
                bars,
                config=replace(
                    config,
                    target_r=target_r,
                    max_holding_minutes=holding_minutes,
                    cost_multiplier=1.0,
                    calculate_robustness=False,
                ),
            )
            neighbourhood.append(
                {
                    **_compact_result(
                        result,
                        label=f"{target_r:.2f}R_{holding_minutes}M",
                    ),
                    "target_r": target_r,
                    "max_holding_minutes": holding_minutes,
                }
            )
    return {
        "cost_stress": cost_stress,
        "parameter_neighbourhood": neighbourhood,
        "selection_policy": (
            "The frozen centre remains 1.00R/240m. Neighbouring cells diagnose "
            "fragility and are not eligible to replace the centre after inspection."
        ),
    }


def _compact_result(result: _PortfolioResult, *, label: str) -> dict[str, Any]:
    trades = list(result.trades)
    net_r = [trade.r_multiple for trade in trades]
    winners = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losers = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    return {
        "label": label,
        "trades": len(trades),
        "win_rate_pct": round(len(winners) / len(trades) * 100, 4) if trades else None,
        "net_expectancy_r": _mean(net_r),
        "total_net_pnl": round(sum(trade.net_pnl for trade in trades), 2),
        "total_costs": round(sum(trade.costs for trade in trades), 2),
        "profit_factor": (
            round(sum(winners) / abs(sum(losers)), 6)
            if winners and losers
            else None
        ),
        "exclusions": result.exclusions,
    }


def _development_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    by_year = cast(dict[str, dict[str, Any]], metrics.get("performance_by_year", {}))
    by_side = cast(dict[str, dict[str, Any]], metrics.get("performance_by_side", {}))
    by_regime = cast(dict[str, dict[str, Any]], metrics.get("performance_by_regime", {}))
    robustness = cast(dict[str, Any], metrics.get("robustness", {}))
    cost_rows = cast(list[dict[str, Any]], robustness.get("cost_stress", []))
    one_and_half = next(
        (item for item in cost_rows if item.get("label") == "1.50x"),
        None,
    )
    annual_expectancies = [
        float(item["average_r"])
        for item in by_year.values()
        if item.get("average_r") is not None
    ]
    side_counts = [
        int(item.get("trades", 0))
        for item in by_side.values()
        if int(item.get("trades", 0)) > 0
    ]
    regime_counts = [
        int(item.get("trades", 0))
        for item in by_regime.values()
        if int(item.get("trades", 0)) > 0
    ]
    trade_count = int(metrics.get("trades", 0))
    largest_regime_share = (
        max(regime_counts) / trade_count * 100
        if regime_counts and trade_count > 0
        else 100.0
    )
    criteria = {
        "positive_centre_net_expectancy": (
            metrics.get("net_expectancy_r") is not None
            and float(metrics["net_expectancy_r"]) > 0
        ),
        "positive_each_development_year": (
            len(annual_expectancies) >= 2
            and all(value > 0 for value in annual_expectancies)
        ),
        "positive_at_1_5x_costs": (
            one_and_half is not None
            and one_and_half.get("net_expectancy_r") is not None
            and float(one_and_half["net_expectancy_r"]) > 0
        ),
        "largest_winner_below_half_total_net_profit": (
            metrics.get("largest_winner_share_of_total_net_profit_pct") is not None
            and float(metrics["largest_winner_share_of_total_net_profit_pct"]) < 50
        ),
        "more_than_one_direction": len(side_counts) >= 2,
        "no_single_regime_above_80_pct": largest_regime_share <= 80,
    }
    passed = all(criteria.values())
    return {
        "status": "PASS" if passed else "FAIL",
        "continue_to_locked_validation": passed,
        "criteria": criteria,
        "largest_regime_share_pct": round(largest_regime_share, 4),
        "holdout_policy": (
            "Run calendar year 2025 once only if the primary fundamental-aligned "
            "candidate passes every development criterion."
        ),
    }


def _primary_attempt(setup: SessionStrategySetup) -> dict[str, Any] | None:
    attempts = setup.facts.get("attempts")
    index = setup.evidence.get("primary_attempt_index")
    if (
        not isinstance(attempts, list)
        or not isinstance(index, int)
        or index < 0
        or index >= len(attempts)
        or not isinstance(attempts[index], dict)
    ):
        return None
    return cast(dict[str, Any], attempts[index])


def _longest_outcome(outcomes: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    return max(
        outcomes,
        key=lambda item: int(item.get("horizon_minutes", 0)),
        default=None,
    )


def _canonical_bars(
    bars: Sequence[SessionExecutionBar],
) -> dict[datetime, SessionExecutionBar]:
    canonical: dict[datetime, SessionExecutionBar] = {}
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        open_time = bar.open_time.astimezone(UTC)
        if (
            bar.complete
            and bar.close_time.astimezone(UTC) == open_time + timedelta(minutes=1)
            and bar.available_at <= bar.close_time
        ):
            canonical.setdefault(open_time, bar)
    return canonical


def _bar_hash(bars: dict[datetime, SessionExecutionBar]) -> str:
    digest = hashlib.sha256()
    for open_time, bar in sorted(bars.items()):
        digest.update(
            (
                f"{open_time.isoformat()}|{bar.available_at.isoformat()}|"
                f"{bar.open:.8f}|{bar.high:.8f}|{bar.low:.8f}|"
                f"{bar.close:.8f}|{bar.spread_price}|{bar.source_record_key}\n"
            ).encode()
        )
    return digest.hexdigest()


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("Stored strategy evidence contains a naive timestamp")
        return parsed
    return None


def _validate_inputs(
    setups: Sequence[SessionStrategySetup],
    bars: Sequence[SessionExecutionBar],
    *,
    start: datetime,
    end: datetime,
    config: SessionStrategyConfig,
) -> None:
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Strategy start/end must be timezone-aware and ordered")
    if not setups:
        raise ValueError("At least one triggered source opportunity is required")
    if not bars:
        raise ValueError("Execution bars are required")
    if config.strategy_mode not in {
        "DELAYED_RECLAIM_PRICE_CONTROL",
        "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED",
    }:
        raise ValueError("Unsupported session strategy mode")
    if not 0 < config.risk_per_trade_pct <= 5:
        raise ValueError("risk_per_trade_pct must be in (0, 5]")
    if config.max_holding_minutes <= 0:
        raise ValueError("max_holding_minutes must be positive")
    if min(
        config.initial_equity,
        config.target_r,
        config.cost_multiplier,
        config.contract_size,
        config.min_lot,
        config.lot_step,
        config.max_lots,
    ) <= 0:
        raise ValueError("Positive strategy configuration values are required")
    if min(
        config.slippage_price_per_side,
        config.commission_per_lot_round_turn,
    ) < 0:
        raise ValueError("Execution costs cannot be negative")
    if config.max_lots < config.min_lot:
        raise ValueError("max_lots cannot be below min_lot")
    if any(
        item.open_time.tzinfo is None
        or item.close_time.tzinfo is None
        or item.available_at.tzinfo is None
        for item in bars
    ):
        raise ValueError("All execution bar clocks must be timezone-aware")


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _jsonable(value: object) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
