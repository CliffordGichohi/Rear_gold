from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import numpy as np
from explore_session_playbooks import (
    FIVE_MINUTE_SQL,
    Bar,
    Day,
    _build_days,
)

from gold_intel.infrastructure.database import session_factory

Side = Literal["LONG", "SHORT"]


@dataclass(frozen=True, slots=True)
class Signal:
    playbook: str
    session_date: date
    side: Side
    signal_time: datetime
    entry_time: datetime
    entry_reference: float
    stop: float
    base_target_r: float
    max_holding_minutes: int
    atr: float
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Trade:
    playbook: str
    session_date: date
    side: Side
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    risk_distance: float
    gross_r: float
    net_r: float
    cost_r: float
    mfe_r: float
    mae_r: float
    holding_minutes: int
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Acceptance:
    side: Side
    boundary: float
    signal_index: int
    atr: float


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact research summary instead of every diagnostic.",
    )
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    async with session_factory() as session:
        rows = (
            await session.execute(
                FIVE_MINUTE_SQL,
                {
                    "load_start": start - timedelta(days=5),
                    "load_end": end,
                },
            )
        ).mappings()
        bars = [
            Bar(
                open_time=row["open_time"],
                close_time=row["close_time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                spread=float(row["spread_price"]),
            )
            for row in rows
        ]

    days = _build_days(bars, start=start, end=end)
    atr_by_close = _atr_by_close(bars)
    bars_by_open = {item.open_time: item for item in bars}
    london_range_history: list[float] = []
    signals: list[Signal] = []
    signal_funnel: dict[str, int] = defaultdict(int)
    for day in days:
        day_signals = _signals_for_day(
            day,
            atr_by_close=atr_by_close,
            london_range_history=london_range_history,
        )
        for signal in day_signals:
            signals.append(signal)
            signal_funnel[signal.playbook] += 1
        london_range_history.append(
            max(item.high for item in day.london)
            - min(item.low for item in day.london)
        )

    payload: dict[str, Any] = {
        "contract": {
            "version": "DAILY_SESSION_PLAYBOOK_DISCOVERY_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "signals": len(signals),
            "signal_funnel": dict(sorted(signal_funnel.items())),
            "cost_model": {
                "observed_entry_exit_spread": True,
                "slippage_price_per_side": 0.05,
                "commission_price_round_turn": 0.07,
            },
            "splits": {
                "discovery": "2021-08-01 through 2023-12-31",
                "development_forward": "calendar year 2024",
                "locked_validation": "calendar year 2025 (not loaded)",
            },
        },
        "playbooks": {},
    }
    for playbook in sorted(signal_funnel):
        selected = [item for item in signals if item.playbook == playbook]
        base_trades = [
            trade
            for signal in selected
            if (
                trade := _simulate(
                    signal,
                    bars_by_open,
                    target_r=signal.base_target_r,
                    cost_multiplier=1.0,
                )
            )
            is not None
        ]
        discovery = [
            item for item in base_trades if item.session_date < date(2024, 1, 1)
        ]
        forward = [
            item for item in base_trades if item.session_date >= date(2024, 1, 1)
        ]
        payload["playbooks"][playbook] = {
            "base_target_r": selected[0].base_target_r if selected else None,
            "signals": len(selected),
            "complete_trades": len(base_trades),
            "all_development": _metrics(base_trades),
            "discovery_2021_2023": _metrics(discovery),
            "forward_2024": _metrics(forward),
            "target_neighbourhood": {
                f"{target_r:.2f}R": _metrics(
                    [
                        trade
                        for signal in selected
                        if (
                            trade := _simulate(
                                signal,
                                bars_by_open,
                                target_r=target_r,
                                cost_multiplier=1.0,
                            )
                        )
                        is not None
                    ]
                )
                for target_r in (1.0, 1.5, 2.0)
            },
            "cost_stress": {
                f"{multiplier:.2f}x": _metrics(
                    [
                        trade
                        for signal in selected
                        if (
                            trade := _simulate(
                                signal,
                                bars_by_open,
                                target_r=signal.base_target_r,
                                cost_multiplier=multiplier,
                            )
                        )
                        is not None
                    ]
                )
                for multiplier in (1.0, 1.5, 2.0)
            },
        }
    if args.summary:
        payload = {
            "contract": payload["contract"],
            "playbooks": {
                name: {
                    "base_target_r": result["base_target_r"],
                    "signals": result["signals"],
                    "complete_trades": result["complete_trades"],
                    "all_development": _compact_metrics(
                        result["all_development"]
                    ),
                    "discovery_2021_2023": _compact_metrics(
                        result["discovery_2021_2023"]
                    ),
                    "forward_2024": _compact_metrics(result["forward_2024"]),
                    "target_neighbourhood": {
                        key: _tiny_metrics(value)
                        for key, value in result["target_neighbourhood"].items()
                    },
                    "cost_stress": {
                        key: _tiny_metrics(value)
                        for key, value in result["cost_stress"].items()
                    },
                }
                for name, result in payload["playbooks"].items()
            },
        }
    print(json.dumps(payload, indent=2, sort_keys=True))


def _signals_for_day(
    day: Day,
    *,
    atr_by_close: dict[datetime, float],
    london_range_history: Sequence[float],
) -> list[Signal]:
    output: list[Signal] = []
    asia_high = max(item.high for item in day.asia)
    asia_low = min(item.low for item in day.asia)
    acceptance = _london_acceptance(
        day,
        asia_high=asia_high,
        asia_low=asia_low,
        atr_by_close=atr_by_close,
    )
    if acceptance is not None:
        signal = _acceptance_signal(day, acceptance=acceptance)
        if signal is not None:
            output.append(signal)
        retest = _retest_signal(day, acceptance=acceptance)
        if retest is not None:
            output.append(retest)

    rejection = _london_rejection_signal(
        day,
        asia_high=asia_high,
        asia_low=asia_low,
        atr_by_close=atr_by_close,
    )
    if rejection is not None:
        output.append(rejection)

    continuation = _new_york_continuation_signal(
        day,
        asia_high=asia_high,
        asia_low=asia_low,
        atr_by_close=atr_by_close,
    )
    if continuation is not None:
        output.append(continuation)

    handover_rejection = _new_york_rejection_signal(
        day,
        asia_high=asia_high,
        asia_low=asia_low,
        atr_by_close=atr_by_close,
        london_range_history=london_range_history,
    )
    if handover_rejection is not None:
        output.append(handover_rejection)
    return output


def _london_acceptance(
    day: Day,
    *,
    asia_high: float,
    asia_low: float,
    atr_by_close: dict[datetime, float],
) -> Acceptance | None:
    candidates: list[Acceptance] = []
    for side, boundary in (("LONG", asia_high), ("SHORT", asia_low)):
        for index in range(1, len(day.london)):
            prior = day.london[index - 1]
            current = day.london[index]
            outside = (
                prior.close > boundary and current.close > boundary
                if side == "LONG"
                else prior.close < boundary and current.close < boundary
            )
            atr = atr_by_close.get(current.close_time)
            if (
                outside
                and atr is not None
                and _directional_bar(
                    current,
                    side=side,
                    atr=atr,
                    min_body_atr=0.25,
                    min_body_ratio=0.55,
                    min_close_location=0.65,
                )
            ):
                candidates.append(
                    Acceptance(
                        side=side,
                        boundary=boundary,
                        signal_index=index,
                        atr=atr,
                    )
                )
                break
    return min(candidates, key=lambda item: item.signal_index, default=None)


def _acceptance_signal(
    day: Day,
    *,
    acceptance: Acceptance,
) -> Signal | None:
    index = acceptance.signal_index
    if index + 1 >= len(day.london):
        return None
    signal_bar = day.london[index]
    entry_bar = day.london[index + 1]
    stop = (
        acceptance.boundary - 0.15 * acceptance.atr
        if acceptance.side == "LONG"
        else acceptance.boundary + 0.15 * acceptance.atr
    )
    return _signal(
        playbook="P1_LONDON_ACCEPTANCE_CONTINUATION",
        day=day,
        side=acceptance.side,
        signal_bar=signal_bar,
        entry_bar=entry_bar,
        stop=stop,
        target_r=1.5,
        holding_minutes=240,
        atr=acceptance.atr,
        evidence={"asia_boundary": acceptance.boundary},
    )


def _retest_signal(
    day: Day,
    *,
    acceptance: Acceptance,
) -> Signal | None:
    start = acceptance.signal_index + 1
    end = min(len(day.london) - 1, acceptance.signal_index + 9)
    for index in range(start, end):
        bar = day.london[index]
        touched = (
            bar.low <= acceptance.boundary + 0.15 * acceptance.atr
            if acceptance.side == "LONG"
            else bar.high >= acceptance.boundary - 0.15 * acceptance.atr
        )
        held = (
            bar.close > acceptance.boundary
            if acceptance.side == "LONG"
            else bar.close < acceptance.boundary
        )
        if (
            touched
            and held
            and _directional_bar(
                bar,
                side=acceptance.side,
                atr=acceptance.atr,
                min_body_atr=0.15,
                min_body_ratio=0.50,
                min_close_location=0.60,
            )
        ):
            entry_bar = day.london[index + 1]
            stop = (
                bar.low - 0.10 * acceptance.atr
                if acceptance.side == "LONG"
                else bar.high + 0.10 * acceptance.atr
            )
            return _signal(
                playbook="P2_LONDON_ACCEPTED_RETEST",
                day=day,
                side=acceptance.side,
                signal_bar=bar,
                entry_bar=entry_bar,
                stop=stop,
                target_r=2.0,
                holding_minutes=240,
                atr=acceptance.atr,
                evidence={
                    "asia_boundary": acceptance.boundary,
                    "acceptance_time": day.london[
                        acceptance.signal_index
                    ].close_time.isoformat(),
                },
            )
    return None


def _london_rejection_signal(
    day: Day,
    *,
    asia_high: float,
    asia_low: float,
    atr_by_close: dict[datetime, float],
) -> Signal | None:
    candidates: list[tuple[int, Signal]] = []
    for sweep_index, sweep_bar in enumerate(day.london):
        atr = atr_by_close.get(sweep_bar.close_time)
        if atr is None or atr <= 0:
            continue
        breached_high = sweep_bar.high > asia_high
        breached_low = sweep_bar.low < asia_low
        if breached_high == breached_low:
            continue
        side: Side = "SHORT" if breached_high else "LONG"
        boundary = asia_high if breached_high else asia_low
        depth = (
            sweep_bar.high - boundary if breached_high else boundary - sweep_bar.low
        )
        if not 0.02 * atr <= depth <= 0.75 * atr:
            continue
        reclaim_index = next(
            (
                index
                for index in range(
                    sweep_index,
                    min(len(day.london), sweep_index + 2),
                )
                if (
                    day.london[index].close < boundary
                    if side == "SHORT"
                    else day.london[index].close > boundary
                )
            ),
            None,
        )
        if reclaim_index is None:
            continue
        sweep_members = day.london[sweep_index : reclaim_index + 1]
        extreme = (
            max(item.high for item in sweep_members)
            if side == "SHORT"
            else min(item.low for item in sweep_members)
        )
        for signal_index in range(
            reclaim_index,
            min(len(day.london) - 1, reclaim_index + 4),
        ):
            if signal_index < 3:
                continue
            bar = day.london[signal_index]
            micro = day.london[signal_index - 3 : signal_index]
            breaks_structure = (
                bar.close < min(item.low for item in micro)
                if side == "SHORT"
                else bar.close > max(item.high for item in micro)
            )
            if breaks_structure and _directional_bar(
                bar,
                side=side,
                atr=atr,
                min_body_atr=0.25,
                min_body_ratio=0.55,
                min_close_location=0.65,
            ):
                entry_bar = day.london[signal_index + 1]
                stop = extreme + 0.10 * atr if side == "SHORT" else extreme - 0.10 * atr
                candidate = _signal(
                    playbook="P3_LONDON_SWEEP_REJECTION",
                    day=day,
                    side=side,
                    signal_bar=bar,
                    entry_bar=entry_bar,
                    stop=stop,
                    target_r=1.0,
                    holding_minutes=240,
                    atr=atr,
                    evidence={
                        "asia_boundary": boundary,
                        "sweep_time": sweep_bar.open_time.isoformat(),
                        "reclaim_time": day.london[
                            reclaim_index
                        ].close_time.isoformat(),
                        "reclaim_speed": (
                            "SAME_BAR"
                            if reclaim_index == sweep_index
                            else "DELAYED"
                        ),
                    },
                )
                if candidate is not None:
                    candidates.append((signal_index, candidate))
                break
    return min(candidates, key=lambda item: item[0], default=(0, None))[1]


def _new_york_continuation_signal(
    day: Day,
    *,
    asia_high: float,
    asia_low: float,
    atr_by_close: dict[datetime, float],
) -> Signal | None:
    london_close = day.london[-1].close
    side: Side | None = (
        "LONG"
        if london_close > asia_high
        else "SHORT"
        if london_close < asia_low
        else None
    )
    if side is None:
        return None
    boundary = asia_high if side == "LONG" else asia_low
    opening = day.new_york[:6]
    if len(opening) != 6 or any(
        item.close <= boundary if side == "LONG" else item.close >= boundary
        for item in opening
    ):
        return None
    opening_high = max(item.high for item in opening)
    opening_low = min(item.low for item in opening)
    for index in range(6, min(len(day.new_york) - 1, 30)):
        bar = day.new_york[index]
        atr = atr_by_close.get(bar.close_time)
        if atr is None:
            continue
        breakout = bar.close > opening_high if side == "LONG" else bar.close < opening_low
        if breakout and _directional_bar(
            bar,
            side=side,
            atr=atr,
            min_body_atr=0.25,
            min_body_ratio=0.55,
            min_close_location=0.65,
        ):
            return _signal(
                playbook="P4_NEW_YORK_CONFIRMATION",
                day=day,
                side=side,
                signal_bar=bar,
                entry_bar=day.new_york[index + 1],
                stop=(opening_high + opening_low) / 2,
                target_r=1.5,
                holding_minutes=180,
                atr=atr,
                evidence={
                    "asia_boundary": boundary,
                    "opening_range_high": opening_high,
                    "opening_range_low": opening_low,
                },
            )
    return None


def _new_york_rejection_signal(
    day: Day,
    *,
    asia_high: float,
    asia_low: float,
    atr_by_close: dict[datetime, float],
    london_range_history: Sequence[float],
) -> Signal | None:
    london_close = day.london[-1].close
    london_side: Side | None = (
        "LONG"
        if london_close > asia_high
        else "SHORT"
        if london_close < asia_low
        else None
    )
    if london_side is None:
        return None
    rejection_side: Side = "SHORT" if london_side == "LONG" else "LONG"
    london_range = max(item.high for item in day.london) - min(
        item.low for item in day.london
    )
    prior_median = _median(list(london_range_history[-20:]))
    for index in range(3, min(len(day.new_york) - 1, 24)):
        bar = day.new_york[index]
        atr = atr_by_close.get(bar.close_time)
        if atr is None:
            continue
        returned_inside = asia_low <= bar.close <= asia_high
        micro = day.new_york[index - 3 : index]
        breaks_structure = (
            bar.close < min(item.low for item in micro)
            if rejection_side == "SHORT"
            else bar.close > max(item.high for item in micro)
        )
        if returned_inside and breaks_structure and _directional_bar(
            bar,
            side=rejection_side,
            atr=atr,
            min_body_atr=0.25,
            min_body_ratio=0.55,
            min_close_location=0.65,
        ):
            observed = day.new_york[: index + 1]
            stop = (
                max(item.high for item in observed) + 0.10 * atr
                if rejection_side == "SHORT"
                else min(item.low for item in observed) - 0.10 * atr
            )
            return _signal(
                playbook="P5_NEW_YORK_HANDOVER_REJECTION",
                day=day,
                side=rejection_side,
                signal_bar=bar,
                entry_bar=day.new_york[index + 1],
                stop=stop,
                target_r=1.5,
                holding_minutes=180,
                atr=atr,
                evidence={
                    "london_side": london_side,
                    "london_range": london_range,
                    "prior_20_london_median": prior_median,
                    "extreme_expansion_1_5x": (
                        prior_median is not None
                        and london_range >= 1.5 * prior_median
                    ),
                },
            )
    return None


def _signal(
    *,
    playbook: str,
    day: Day,
    side: Side,
    signal_bar: Bar,
    entry_bar: Bar,
    stop: float,
    target_r: float,
    holding_minutes: int,
    atr: float,
    evidence: dict[str, Any],
) -> Signal | None:
    if entry_bar.open_time != signal_bar.close_time:
        return None
    risk = abs(entry_bar.open - stop)
    if risk <= 0:
        return None
    return Signal(
        playbook=playbook,
        session_date=day.session_date,
        side=side,
        signal_time=signal_bar.close_time,
        entry_time=entry_bar.open_time,
        entry_reference=entry_bar.open,
        stop=stop,
        base_target_r=target_r,
        max_holding_minutes=holding_minutes,
        atr=atr,
        evidence=evidence,
    )


def _simulate(
    signal: Signal,
    bars_by_open: dict[datetime, Bar],
    *,
    target_r: float,
    cost_multiplier: float,
) -> Trade | None:
    risk = abs(signal.entry_reference - signal.stop)
    if risk <= 0:
        return None
    expected = [
        signal.entry_time + timedelta(minutes=offset)
        for offset in range(0, signal.max_holding_minutes, 5)
    ]
    path = [bars_by_open.get(open_time) for open_time in expected]
    if any(item is None for item in path):
        return None
    members = [item for item in path if item is not None]
    direction = 1 if signal.side == "LONG" else -1
    target = signal.entry_reference + direction * target_r * risk
    reference_exit = members[-1].close
    exit_bar = members[-1]
    exit_reason = "TIME"
    favourable = 0.0
    adverse = 0.0
    for bar in members:
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
            reference_exit = signal.stop
            exit_bar = bar
            exit_reason = "STOP"
            break
        if target_hit:
            reference_exit = target
            exit_bar = bar
            exit_reason = "TARGET"
            break
    gross_r = direction * (reference_exit - signal.entry_reference) / risk
    cost_price = (
        (members[0].spread + exit_bar.spread) / 2 + 0.10 + 0.07
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
        risk_distance=risk,
        gross_r=round(gross_r, 6),
        net_r=round(gross_r - cost_r, 6),
        cost_r=round(cost_r, 6),
        mfe_r=round(max(0.0, favourable / risk), 6),
        mae_r=round(max(0.0, adverse / risk), 6),
        holding_minutes=int(
            (exit_bar.close_time - signal.entry_time).total_seconds() // 60
        ),
        evidence={
            **signal.evidence,
            "target_r": target_r,
            "entry_spread": members[0].spread,
            "exit_spread": exit_bar.spread,
        },
    )


def _metrics(trades: Sequence[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "win_rate_pct": None,
            "net_expectancy_r": None,
            "profit_factor": None,
        }
    ordered = sorted(trades, key=lambda item: (item.entry_time, item.playbook))
    net = [item.net_r for item in ordered]
    winners = [value for value in net if value > 0]
    losers = [value for value in net if value < 0]
    by_year: dict[str, list[float]] = defaultdict(list)
    by_side: dict[str, list[float]] = defaultdict(list)
    by_month: dict[str, list[float]] = defaultdict(list)
    for trade in ordered:
        by_year[str(trade.session_date.year)].append(trade.net_r)
        by_side[trade.side].append(trade.net_r)
        by_month[trade.session_date.strftime("%Y-%m")].append(trade.net_r)
    monthly_r = [sum(values) for _, values in sorted(by_month.items())]
    capital_paths = {
        f"{risk_pct:.2f}%": _capital_path(ordered, risk_pct=risk_pct)
        for risk_pct in (0.5, 1.0, 1.5)
    }
    bootstrap = _bootstrap_mean(net)
    return {
        "trades": len(ordered),
        "wins": len(winners),
        "losses": len(losers),
        "win_rate_pct": round(len(winners) / len(ordered) * 100, 4),
        "gross_expectancy_r": round(
            statistics.mean(item.gross_r for item in ordered),
            6,
        ),
        "net_expectancy_r": round(statistics.mean(net), 6),
        "median_net_r": round(statistics.median(net), 6),
        "bootstrap_95ci": [round(bootstrap[0], 6), round(bootstrap[1], 6)],
        "profit_factor": (
            round(sum(winners) / abs(sum(losers)), 6)
            if winners and losers
            else None
        ),
        "total_net_r": round(sum(net), 6),
        "average_cost_r": round(statistics.mean(item.cost_r for item in ordered), 6),
        "average_mfe_r": round(statistics.mean(item.mfe_r for item in ordered), 6),
        "average_mae_r": round(statistics.mean(item.mae_r for item in ordered), 6),
        "average_holding_minutes": round(
            statistics.mean(item.holding_minutes for item in ordered),
            2,
        ),
        "maximum_drawdown_r": round(_maximum_drawdown(net), 6),
        "maximum_consecutive_losses": _maximum_consecutive_losses(net),
        "monthly": {
            "months": len(monthly_r),
            "average_r": round(statistics.mean(monthly_r), 6),
            "median_r": round(statistics.median(monthly_r), 6),
            "positive_month_pct": round(
                sum(value > 0 for value in monthly_r) / len(monthly_r) * 100,
                4,
            ),
            "best_r": round(max(monthly_r), 6),
            "worst_r": round(min(monthly_r), 6),
        },
        "by_year": {
            key: _group(values) for key, values in sorted(by_year.items())
        },
        "by_side": {
            key: _group(values) for key, values in sorted(by_side.items())
        },
        "capital_paths": capital_paths,
    }


def _compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    if not metrics["trades"]:
        return metrics
    monthly = metrics["monthly"]
    capital = metrics["capital_paths"]["1.00%"]
    return {
        "trades": metrics["trades"],
        "win_rate_pct": metrics["win_rate_pct"],
        "net_expectancy_r": metrics["net_expectancy_r"],
        "bootstrap_95ci": metrics["bootstrap_95ci"],
        "profit_factor": metrics["profit_factor"],
        "total_net_r": metrics["total_net_r"],
        "maximum_drawdown_r": metrics["maximum_drawdown_r"],
        "average_monthly_r": monthly["average_r"],
        "positive_month_pct": monthly["positive_month_pct"],
        "worst_month_r": monthly["worst_r"],
        "average_monthly_pnl_usd_at_1pct_risk": capital[
            "average_monthly_pnl_usd"
        ],
        "maximum_drawdown_pct_at_1pct_risk": capital[
            "maximum_drawdown_pct"
        ],
    }


def _tiny_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metrics[key]
        for key in (
            "trades",
            "win_rate_pct",
            "net_expectancy_r",
            "profit_factor",
            "total_net_r",
        )
    }


def _capital_path(trades: Sequence[Trade], *, risk_pct: float) -> dict[str, Any]:
    equity = 10_000.0
    peak = equity
    max_drawdown_pct = 0.0
    monthly_pnl: dict[str, float] = defaultdict(float)
    for trade in trades:
        pnl = equity * risk_pct / 100 * trade.net_r
        equity += pnl
        monthly_pnl[trade.session_date.strftime("%Y-%m")] += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100)
    month_values = list(monthly_pnl.values())
    return {
        "initial_equity": 10_000.0,
        "final_equity": round(equity, 2),
        "total_return_pct": round((equity / 10_000 - 1) * 100, 4),
        "maximum_drawdown_pct": round(max_drawdown_pct, 4),
        "average_monthly_pnl_usd": (
            round(statistics.mean(month_values), 2) if month_values else None
        ),
        "months_with_trades": len(month_values),
    }


def _directional_bar(
    bar: Bar,
    *,
    side: Side,
    atr: float,
    min_body_atr: float,
    min_body_ratio: float,
    min_close_location: float,
) -> bool:
    candle_range = bar.high - bar.low
    if candle_range <= 0 or atr <= 0:
        return False
    body = bar.close - bar.open if side == "LONG" else bar.open - bar.close
    close_location = (
        (bar.close - bar.low) / candle_range
        if side == "LONG"
        else (bar.high - bar.close) / candle_range
    )
    return (
        body >= min_body_atr * atr
        and body / candle_range >= min_body_ratio
        and close_location >= min_close_location
    )


def _atr_by_close(bars: Sequence[Bar], window: int = 14) -> dict[datetime, float]:
    output: dict[datetime, float] = {}
    true_ranges: list[float] = []
    prior_close: float | None = None
    for bar in sorted(bars, key=lambda item: item.open_time):
        value = bar.high - bar.low
        if prior_close is not None:
            value = max(
                value,
                abs(bar.high - prior_close),
                abs(bar.low - prior_close),
            )
        true_ranges.append(value)
        prior_close = bar.close
        if len(true_ranges) >= window:
            output[bar.close_time] = statistics.mean(true_ranges[-window:])
    return output


def _group(values: Sequence[float]) -> dict[str, Any]:
    winners = [item for item in values if item > 0]
    losers = [item for item in values if item < 0]
    return {
        "trades": len(values),
        "win_rate_pct": round(len(winners) / len(values) * 100, 4),
        "net_expectancy_r": round(statistics.mean(values), 6),
        "total_net_r": round(sum(values), 6),
        "profit_factor": (
            round(sum(winners) / abs(sum(losers)), 6)
            if winners and losers
            else None
        ),
    }


def _bootstrap_mean(values: Sequence[float]) -> tuple[float, float]:
    if len(values) < 2:
        value = values[0] if values else 0.0
        return value, value
    observations = np.asarray(values, dtype=np.float64)
    generator = np.random.default_rng(20260727)
    indices = generator.integers(
        0,
        len(observations),
        size=(5_000, len(observations)),
    )
    estimates = np.sort(observations[indices].mean(axis=1))
    return (
        float(estimates[math.floor(0.025 * (len(estimates) - 1))]),
        float(estimates[math.ceil(0.975 * (len(estimates) - 1))]),
    )


def _maximum_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _maximum_consecutive_losses(values: Sequence[float]) -> int:
    maximum = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


if __name__ == "__main__":
    asyncio.run(main())
