from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from explore_session_playbooks import (
    FIVE_MINUTE_SQL,
    LONDON,
    Bar,
    _complete,
    _window,
)
from research_daily_session_playbooks import (
    Side,
    Signal,
    Trade,
    _atr_by_close,
    _directional_bar,
)
from research_gold_auction_windows import SPECS, WindowSpec
from research_session_state_transitions import (
    Candidate,
    ContextRule,
    ManagedResult,
    _candidate_report,
    _portfolio_report,
    _select_discovery_candidates,
    _simulate_all,
)

from gold_intel.infrastructure.database import session_factory

Predicate = Callable[[Signal], bool]


@dataclass(frozen=True, slots=True)
class AuctionDay:
    session_date: date
    specification: WindowSpec
    pre: tuple[Bar, ...]
    post: tuple[Bar, ...]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    async with session_factory() as session:
        rows = (
            await session.execute(
                FIVE_MINUTE_SQL,
                {
                    "load_start": start - timedelta(days=8),
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

    auction_days = _auction_days(bars, start=start, end=end)
    signals = _signals(auction_days, bars=bars)
    managed = _simulate_all(signals, gold_bars=bars)
    candidates, candidate_trades = _candidate_results(managed)
    selected = _select_discovery_candidates(
        candidates,
        candidate_trades=candidate_trades,
    )
    report = {
        "contract": {
            "version": "AUCTION_STATE_PLAYBOOKS_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "auction_days": len(auction_days),
            "signals": len(signals),
            "managed_results": len(managed),
            "candidate_hypotheses": len(candidates),
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
            "selection": (
                "Discovery only: n>=40, expectancy>=0.10R, PF>=1.15, "
                "1.50x-cost expectancy>0, bootstrap lower>=-0.05R; one "
                "candidate per auction/archetype."
            ),
        },
        "signal_funnel": {
            playbook: sum(
                signal.playbook == playbook for signal in signals
            )
            for playbook in sorted({signal.playbook for signal in signals})
        },
        "selected_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in selected
        ],
        "top_discovery_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in sorted(
                candidates,
                key=lambda candidate: _discovery_rank(
                    candidate,
                    candidate_trades=candidate_trades,
                ),
                reverse=True,
            )[: args.top]
        ],
        "portfolios": {
            f"{cost_multiplier:.2f}x": _portfolio_report(
                selected,
                candidate_trades=candidate_trades,
                cost_multiplier=cost_multiplier,
            )
            for cost_multiplier in (1.0, 1.5)
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _auction_days(
    bars: Sequence[Bar],
    *,
    start: datetime,
    end: datetime,
) -> list[AuctionDay]:
    bars_by_open = {bar.open_time: bar for bar in bars}
    first_date = start.astimezone(LONDON).date()
    last_date = (end - timedelta(microseconds=1)).astimezone(LONDON).date()
    output: list[AuctionDay] = []
    current = first_date
    while current <= last_date:
        if current.weekday() < 5:
            for spec in SPECS:
                pre_start = datetime.combine(
                    current,
                    spec.pre_start,
                    tzinfo=spec.timezone,
                ).astimezone(UTC)
                pre_end = datetime.combine(
                    current,
                    spec.pre_end,
                    tzinfo=spec.timezone,
                ).astimezone(UTC)
                post_start = datetime.combine(
                    current,
                    spec.post_start,
                    tzinfo=spec.timezone,
                ).astimezone(UTC)
                post_end = datetime.combine(
                    current,
                    spec.post_end,
                    tzinfo=spec.timezone,
                ).astimezone(UTC)
                pre = _window(bars_by_open, pre_start, pre_end)
                post = _window(bars_by_open, post_start, post_end)
                if _complete(pre, pre_start, pre_end) and _complete(
                    post,
                    post_start,
                    post_end,
                ):
                    output.append(
                        AuctionDay(
                            session_date=current,
                            specification=spec,
                            pre=pre,
                            post=post,
                        )
                    )
        current += timedelta(days=1)
    return output


def _signals(
    auction_days: Sequence[AuctionDay],
    *,
    bars: Sequence[Bar],
) -> list[Signal]:
    atr_by_close = _atr_by_close(bars)
    range_history: dict[str, list[float]] = {
        spec.name: [] for spec in SPECS
    }
    output: list[Signal] = []
    for day in auction_days:
        pre_high = max(bar.high for bar in day.pre)
        pre_low = min(bar.low for bar in day.pre)
        pre_range = pre_high - pre_low
        history = range_history[day.specification.name]
        percentile = _percentile(pre_range, history[-60:])
        output.extend(
            _scan(
                day,
                atr_by_close=atr_by_close,
                pre_high=pre_high,
                pre_low=pre_low,
                pre_range_percentile=percentile,
            )
        )
        history.append(pre_range)
    return output


def _scan(
    day: AuctionDay,
    *,
    atr_by_close: dict[datetime, float],
    pre_high: float,
    pre_low: float,
    pre_range_percentile: float,
) -> list[Signal]:
    found: dict[str, Signal] = {}
    volume_median = statistics.median(bar.volume for bar in day.pre)
    spread_median = statistics.median(bar.spread for bar in day.pre)
    pre_return = day.pre[-1].close - day.pre[0].open
    for index in range(2, len(day.post) - 1):
        current = day.post[index]
        atr = atr_by_close.get(current.close_time)
        if atr is None or atr <= 0:
            continue
        context = {
            "auction_window": day.specification.name,
            "pre_high": pre_high,
            "pre_low": pre_low,
            "pre_range": pre_high - pre_low,
            "pre_range_percentile": pre_range_percentile,
            "relative_volume": (
                current.volume / volume_median
                if volume_median > 0
                else 1.0
            ),
            "relative_spread": (
                current.spread / spread_median
                if spread_median > 0
                else 1.0
            ),
        }
        prefix = day.specification.name
        if f"{prefix}|ACCEPTANCE" not in found:
            candidate = _acceptance(
                day,
                index=index,
                atr=atr,
                pre_high=pre_high,
                pre_low=pre_low,
                pre_return=pre_return,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate
        if f"{prefix}|RETEST" not in found:
            candidate = _retest(
                day,
                index=index,
                atr=atr,
                pre_high=pre_high,
                pre_low=pre_low,
                pre_return=pre_return,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate
        if f"{prefix}|FAILED_AUCTION" not in found:
            candidate = _failed_auction(
                day,
                index=index,
                atr=atr,
                pre_high=pre_high,
                pre_low=pre_low,
                pre_return=pre_return,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate
        if f"{prefix}|OPENING_DRIVE" not in found:
            candidate = _opening_drive(
                day,
                index=index,
                atr=atr,
                pre_return=pre_return,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate
    return list(found.values())


def _acceptance(
    day: AuctionDay,
    *,
    index: int,
    atr: float,
    pre_high: float,
    pre_low: float,
    pre_return: float,
    context: dict[str, Any],
) -> Signal | None:
    prior = day.post[index - 1]
    current = day.post[index]
    for side, boundary in (("LONG", pre_high), ("SHORT", pre_low)):
        outside = (
            prior.close > boundary and current.close > boundary
            if side == "LONG"
            else prior.close < boundary and current.close < boundary
        )
        if outside and _directional_bar(
            current,
            side=side,
            atr=atr,
            min_body_atr=0.12,
            min_body_ratio=0.45,
            min_close_location=0.60,
        ):
            stop = (
                min(prior.low, current.low, boundary) - 0.10 * atr
                if side == "LONG"
                else max(prior.high, current.high, boundary) + 0.10 * atr
            )
            return _auction_signal(
                day,
                archetype="ACCEPTANCE",
                side=side,
                index=index,
                stop=stop,
                atr=atr,
                evidence={
                    **context,
                    "reference_boundary": boundary,
                    "signed_pre_return": (
                        pre_return if side == "LONG" else -pre_return
                    ),
                },
            )
    return None


def _retest(
    day: AuctionDay,
    *,
    index: int,
    atr: float,
    pre_high: float,
    pre_low: float,
    pre_return: float,
    context: dict[str, Any],
) -> Signal | None:
    current = day.post[index]
    for side, boundary in (("LONG", pre_high), ("SHORT", pre_low)):
        accepted = any(
            (
                day.post[cursor - 1].close > boundary
                and day.post[cursor].close > boundary
                if side == "LONG"
                else day.post[cursor - 1].close < boundary
                and day.post[cursor].close < boundary
            )
            for cursor in range(1, index)
        )
        touched = (
            current.low <= boundary + 0.10 * atr
            if side == "LONG"
            else current.high >= boundary - 0.10 * atr
        )
        held = (
            current.close > boundary
            if side == "LONG"
            else current.close < boundary
        )
        if accepted and touched and held and _directional_bar(
            current,
            side=side,
            atr=atr,
            min_body_atr=0.10,
            min_body_ratio=0.45,
            min_close_location=0.58,
        ):
            stop = (
                current.low - 0.10 * atr
                if side == "LONG"
                else current.high + 0.10 * atr
            )
            return _auction_signal(
                day,
                archetype="RETEST",
                side=side,
                index=index,
                stop=stop,
                atr=atr,
                evidence={
                    **context,
                    "reference_boundary": boundary,
                    "signed_pre_return": (
                        pre_return if side == "LONG" else -pre_return
                    ),
                },
            )
    return None


def _failed_auction(
    day: AuctionDay,
    *,
    index: int,
    atr: float,
    pre_high: float,
    pre_low: float,
    pre_return: float,
    context: dict[str, Any],
) -> Signal | None:
    current = day.post[index]
    so_far = day.post[: index + 1]
    breached_high = any(bar.high > pre_high for bar in so_far)
    breached_low = any(bar.low < pre_low for bar in so_far)
    if breached_high == breached_low:
        return None
    side: Side = "SHORT" if breached_high else "LONG"
    inside = pre_low < current.close < pre_high
    prior2 = day.post[index - 2 : index]
    displaced = (
        current.close < min(bar.low for bar in prior2)
        if side == "SHORT"
        else current.close > max(bar.high for bar in prior2)
    )
    if not inside or not displaced:
        return None
    stop = (
        max(bar.high for bar in so_far) + 0.10 * atr
        if side == "SHORT"
        else min(bar.low for bar in so_far) - 0.10 * atr
    )
    return _auction_signal(
        day,
        archetype="FAILED_AUCTION",
        side=side,
        index=index,
        stop=stop,
        atr=atr,
        evidence={
            **context,
            "signed_pre_return": (
                pre_return if side == "LONG" else -pre_return
            ),
        },
    )


def _opening_drive(
    day: AuctionDay,
    *,
    index: int,
    atr: float,
    pre_return: float,
    context: dict[str, Any],
) -> Signal | None:
    if index != 2:
        return None
    opening = day.post[:3]
    move = opening[-1].close - opening[0].open
    if abs(move) < 0.60 * atr:
        return None
    side: Side = "LONG" if move > 0 else "SHORT"
    directional = sum(
        bar.close > bar.open if side == "LONG" else bar.close < bar.open
        for bar in opening
    )
    if directional < 2:
        return None
    stop = (
        min(bar.low for bar in opening) - 0.10 * atr
        if side == "LONG"
        else max(bar.high for bar in opening) + 0.10 * atr
    )
    return _auction_signal(
        day,
        archetype="OPENING_DRIVE",
        side=side,
        index=index,
        stop=stop,
        atr=atr,
        evidence={
            **context,
            "opening_move_atr": abs(move) / atr,
            "signed_pre_return": (
                pre_return if side == "LONG" else -pre_return
            ),
        },
    )


def _auction_signal(
    day: AuctionDay,
    *,
    archetype: str,
    side: Side,
    index: int,
    stop: float,
    atr: float,
    evidence: dict[str, Any],
) -> Signal | None:
    signal_bar = day.post[index]
    entry_bar = day.post[index + 1]
    risk = abs(entry_bar.open - stop)
    if risk <= 0:
        return None
    if (side == "LONG" and stop >= entry_bar.open) or (
        side == "SHORT" and stop <= entry_bar.open
    ):
        return None
    risk_atr = risk / atr
    if not 0.30 <= risk_atr <= 5.0:
        return None
    holding = int(
        (day.post[-1].close_time - entry_bar.open_time).total_seconds()
        // 60
    )
    if holding < 10:
        return None
    return Signal(
        playbook=f"{day.specification.name}|{archetype}",
        session_date=day.session_date,
        side=side,
        signal_time=signal_bar.close_time,
        entry_time=entry_bar.open_time,
        entry_reference=entry_bar.open,
        stop=stop,
        base_target_r=2.0,
        max_holding_minutes=holding,
        atr=atr,
        evidence={**evidence, "risk_atr": risk_atr},
    )


def _context_rules() -> tuple[ContextRule, ...]:
    return (
        ContextRule("BASE", lambda signal: True),
        ContextRule(
            "PRE_RANGE_COMPRESSION_P30",
            lambda signal: (
                _evidence_float(signal, "pre_range_percentile") <= 30
            ),
        ),
        ContextRule(
            "SPREAD_LE_1_25X",
            lambda signal: (
                _evidence_float(signal, "relative_spread") <= 1.25
            ),
        ),
        ContextRule(
            "VOLUME_GE_1_20X",
            lambda signal: (
                _evidence_float(signal, "relative_volume") >= 1.20
            ),
        ),
        ContextRule(
            "PRE_DIRECTION_ALIGNED",
            lambda signal: (
                _evidence_float(signal, "signed_pre_return") > 0
            ),
        ),
        ContextRule(
            "PRE_DIRECTION_OPPOSED",
            lambda signal: (
                _evidence_float(signal, "signed_pre_return") < 0
            ),
        ),
    )


def _candidate_results(
    managed: Sequence[ManagedResult],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Trade]]]:
    playbooks = sorted({result.signal.playbook for result in managed})
    managers = sorted({result.manager for result in managed})
    candidates = [
        Candidate(
            archetype=playbook,
            rule=rule.name,
            manager=manager,
        )
        for playbook in playbooks
        for rule in _context_rules()
        for manager in managers
    ]
    rules = {rule.name: rule for rule in _context_rules()}
    output: dict[tuple[str, float], list[Trade]] = {}
    for candidate in candidates:
        rule = rules[candidate.rule]
        for cost_multiplier in (1.0, 1.5):
            output[(candidate.key, cost_multiplier)] = [
                result.trade
                for result in managed
                if result.signal.playbook == candidate.archetype
                and result.manager == candidate.manager
                and result.cost_multiplier == cost_multiplier
                and rule.predicate(result.signal)
            ]
    return candidates, output


def _discovery_rank(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
) -> tuple[float, float, int]:
    trades = [
        trade
        for trade in candidate_trades[(candidate.key, 1.0)]
        if trade.session_date < date(2023, 1, 1)
    ]
    expectancy = (
        statistics.mean(trade.net_r for trade in trades)
        if trades
        else -999.0
    )
    wins = sum(max(0.0, trade.net_r) for trade in trades)
    losses = abs(sum(min(0.0, trade.net_r) for trade in trades))
    return (
        expectancy,
        wins / losses if losses > 0 else -999.0,
        len(trades),
    )


def _percentile(value: float, history: Sequence[float]) -> float:
    if not history:
        return 50.0
    return sum(item <= value for item in history) / len(history) * 100


def _evidence_float(signal: Signal, key: str) -> float:
    value = signal.evidence.get(key)
    return float(value) if value is not None else -999.0


if __name__ == "__main__":
    asyncio.run(main())
