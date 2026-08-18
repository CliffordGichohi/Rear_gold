from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from explore_session_playbooks import Bar, Day, _build_days
from research_cross_market_auction_micro_execution import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
    _five_minute_bars_from_csv_directory,
    _five_minute_bars_from_minutes,
)
from research_daily_session_playbooks import (
    Signal,
    _atr_by_close,
    _directional_bar,
)
from research_fundamental_state_transitions import (
    FundamentalRecord,
    _fundamental_records,
    _reaction_function_aligned,
)
from research_one_minute_auction_execution import (
    ONE_MINUTE_SQL,
    _simulate_minute,
)
from research_session_state_transitions import (
    Candidate,
    ManagedResult,
    _candidate_report,
    _portfolio_report,
    _select_discovery_candidates,
    _slice,
)

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory

Side = Literal["LONG", "SHORT"]
Predicate = Callable[[FundamentalRecord], bool]


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    break_side: Side
    price: float
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FundamentalRule:
    name: str
    predicate: Predicate


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--xagusd-csv-dir", type=Path)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    run_started = time.perf_counter()
    phase_started = run_started
    _phase("START", 0.0)
    query = {
        "load_start": start - timedelta(days=8),
        "load_end": end,
    }
    async with session_factory() as session:
        minute_bars = _bars(
            (await session.execute(ONE_MINUTE_SQL, query)).mappings()
        )
        five_minute_gold = _five_minute_bars_from_minutes(minute_bars)
        _phase("GOLD_LOADED", time.perf_counter() - phase_started)
        phase_started = time.perf_counter()
        eurusd_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "EURUSD", **query},
                )
            ).mappings()
        )
        _phase("EURUSD_LOADED", time.perf_counter() - phase_started)
        phase_started = time.perf_counter()
        if args.xagusd_csv_dir is not None:
            silver_bars = _five_minute_bars_from_csv_directory(
                args.xagusd_csv_dir,
                load_start=query["load_start"],
                load_end=query["load_end"],
                point_size=0.001,
            )
        else:
            silver_bars = _bars(
                (
                    await session.execute(
                        FIVE_MINUTE_INSTRUMENT_SQL,
                        {"instrument": "XAGUSD", **query},
                    )
                ).mappings()
            )
        fundamental_inputs = await load_fundamental_inputs(
            session,
            as_of=end,
        )
        _phase(
            "SILVER_AND_FUNDAMENTALS_LOADED",
            time.perf_counter() - phase_started,
        )
    phase_started = time.perf_counter()

    days = _build_days(five_minute_gold, start=start, end=end)
    signals = _liquidity_signals(
        days,
        minute_bars=minute_bars,
        five_minute_gold=five_minute_gold,
    )
    signals = _enrich_cross_market(
        signals,
        eurusd_bars=eurusd_bars,
        silver_bars=silver_bars,
    )
    _phase("LIQUIDITY_STATES_BUILT", time.perf_counter() - phase_started)
    phase_started = time.perf_counter()
    managed = _managed_results(signals, minute_bars=minute_bars)
    records = _fundamental_records(
        managed,
        fundamental_inputs=fundamental_inputs,
    )
    _phase(
        "TRADES_AND_FUNDAMENTALS_BUILT",
        time.perf_counter() - phase_started,
    )
    phase_started = time.perf_counter()

    rules = _rules()
    candidates, candidate_trades = _candidate_results(
        records,
        rules=rules,
    )
    selected = _select_discovery_candidates(
        candidates,
        candidate_trades=candidate_trades,
    )
    sampled = [
        candidate
        for candidate in candidates
        if len(
            _slice(
                candidate_trades[(candidate.key, 1.0)],
                "discovery",
            )
        )
        >= 40
    ]
    _phase("CANDIDATES_SELECTED", time.perf_counter() - phase_started)
    phase_started = time.perf_counter()

    report = {
        "contract": {
            "version": "LIQUIDITY_LEVEL_STATE_MACHINE_V0_3",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "signals": len(signals),
            "managed_results": len(managed),
            "candidate_hypotheses": len(candidates),
            "states": (
                "Fast rejection after a level sweep; accepted breakout plus "
                "held retest; New York confirmation or rejection of a London "
                "move outside the Asian range."
            ),
            "levels": (
                "Asian high/low, rolling prior-24-hour high/low, and the "
                "London-to-New-York handover high/low. Nearby levels are "
                "clustered before the session and never revised afterward."
            ),
            "entry": (
                "A completed one-minute displacement/structure break, followed "
                "by entry at the next one-minute open."
            ),
            "risk": (
                "Stop beyond the observed sweep/retest extreme; fixed 1.5R, "
                "2R, and 3R managers; maximum 180-minute hold."
            ),
            "costs": (
                "Observed XAUUSD entry/exit spread, $0.05/oz slippage per "
                "side, and $7/lot round-turn commission; also 1.50x stress."
            ),
            "ambiguity": "Same-minute stop and target is resolved stop-first.",
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
            "iteration_note": (
                "V0.3 adds a narrowly scoped real-yield permission family "
                "after the separate target-validity diagnostic found that "
                "real-yield direction was the only slow fundamental component "
                "with a positive London larger-excursion relationship in every "
                "available calendar year. V0.2 already used 2023-2024 for "
                "development diagnostics; only 2025 remains an untouched "
                "holdout."
            ),
            "selection": (
                "Discovery only: n>=40, expectancy>=0.10R, PF>=1.15, "
                "1.50x-cost expectancy>0, bootstrap lower>=-0.05R; one "
                "rule/manager per archetype."
            ),
            "monthly_hurdle": (
                "At 1% account risk, the requested $1,000 average on a "
                "$10,000 account requires approximately 10R per month."
            ),
        },
        "data_coverage": {
            "XAUUSD_1M": _coverage(minute_bars),
            "EURUSD_5M": _coverage(eurusd_bars),
            "XAGUSD_5M": _coverage(silver_bars),
        },
        "signal_funnel": dict(
            sorted(Counter(signal.playbook for signal in signals).items())
        ),
        "feature_coverage": _feature_coverage(records),
        "archetype_baselines": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in candidates
            if candidate.rule == "BASE"
        ],
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
                key=lambda candidate: _rank(
                    candidate,
                    candidate_trades=candidate_trades,
                ),
                reverse=True,
            )[: args.top]
        ],
        "top_minimum_sample_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in sorted(
                sampled,
                key=lambda candidate: _rank(
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
    _phase("REPORT_COMPLETE", time.perf_counter() - run_started)
    print(json.dumps(report, indent=2, sort_keys=True))


def _liquidity_signals(
    days: Sequence[Day],
    *,
    minute_bars: Sequence[Bar],
    five_minute_gold: Sequence[Bar],
) -> list[Signal]:
    bars_by_open = {bar.open_time: bar for bar in minute_bars}
    minute_open_times = [bar.open_time for bar in minute_bars]
    minute_index = {
        bar.open_time: index for index, bar in enumerate(minute_bars)
    }
    atr_by_close = _atr_by_close(five_minute_gold)
    asia_range_history: list[float] = []
    output: list[Signal] = []
    for day in days:
        asia_high = max(bar.high for bar in day.asia)
        asia_low = min(bar.low for bar in day.asia)
        asia_range = asia_high - asia_low
        asia_percentile = _percentile(asia_range, asia_range_history)
        london = _minute_window(
            bars_by_open,
            day.london[0].open_time,
            day.london[-1].close_time,
        )
        new_york = _minute_window(
            bars_by_open,
            day.new_york[0].open_time,
            day.new_york[-1].close_time,
        )
        if not london or not new_york:
            asia_range_history.append(asia_range)
            continue
        london_atr = atr_by_close.get(london[0].open_time)
        new_york_atr = atr_by_close.get(new_york[0].open_time)
        if london_atr is None or new_york_atr is None:
            asia_range_history.append(asia_range)
            continue

        london_levels = _cluster_levels(
            (
                LiquidityLevel("LONG", asia_high, ("ASIA_HIGH",)),
                LiquidityLevel("SHORT", asia_low, ("ASIA_LOW",)),
                *_rolling_levels(
                    minute_bars,
                    minute_open_times,
                    cutoff=london[0].open_time,
                ),
            ),
            atr=london_atr,
        )
        output.extend(
            _session_level_signals(
                day,
                session_name="LONDON",
                session_bars=london,
                levels=london_levels,
                atr=london_atr,
                asia_percentile=asia_percentile,
                all_bars=minute_bars,
                minute_index=minute_index,
                bars_by_open=bars_by_open,
            )
        )

        pre_ny_start = day.london[0].open_time
        pre_ny_end = new_york[0].open_time
        pre_ny = _minute_window(
            bars_by_open,
            pre_ny_start,
            pre_ny_end,
        )
        if pre_ny:
            ny_levels = _cluster_levels(
                (
                    LiquidityLevel("LONG", asia_high, ("ASIA_HIGH",)),
                    LiquidityLevel("SHORT", asia_low, ("ASIA_LOW",)),
                    LiquidityLevel(
                        "LONG",
                        max(bar.high for bar in pre_ny),
                        ("LONDON_PRE_NY_HIGH",),
                    ),
                    LiquidityLevel(
                        "SHORT",
                        min(bar.low for bar in pre_ny),
                        ("LONDON_PRE_NY_LOW",),
                    ),
                    *_rolling_levels(
                        minute_bars,
                        minute_open_times,
                        cutoff=new_york[0].open_time,
                    ),
                ),
                atr=new_york_atr,
            )
            output.extend(
                _session_level_signals(
                    day,
                    session_name="NEW_YORK",
                    session_bars=new_york,
                    levels=ny_levels,
                    atr=new_york_atr,
                    asia_percentile=asia_percentile,
                    all_bars=minute_bars,
                    minute_index=minute_index,
                    bars_by_open=bars_by_open,
                )
            )
            handover = _handover_signal(
                day,
                session_bars=new_york,
                asia_high=asia_high,
                asia_low=asia_low,
                atr=new_york_atr,
                asia_percentile=asia_percentile,
                all_bars=minute_bars,
                minute_index=minute_index,
                bars_by_open=bars_by_open,
            )
            if handover is not None:
                output.append(handover)
        asia_range_history.append(asia_range)
    return output


def _session_level_signals(
    day: Day,
    *,
    session_name: str,
    session_bars: Sequence[Bar],
    levels: Sequence[LiquidityLevel],
    atr: float,
    asia_percentile: float,
    all_bars: Sequence[Bar],
    minute_index: dict[datetime, int],
    bars_by_open: dict[datetime, Bar],
) -> list[Signal]:
    output: list[Signal] = []
    for level in levels:
        opening_inside = (
            session_bars[0].open <= level.price
            if level.break_side == "LONG"
            else session_bars[0].open >= level.price
        )
        if not opening_inside:
            continue
        signal = _resolved_level_signal(
            day,
            session_name=session_name,
            session_bars=session_bars,
            level=level,
            atr=atr,
            asia_percentile=asia_percentile,
            all_bars=all_bars,
            minute_index=minute_index,
            bars_by_open=bars_by_open,
        )
        if signal is not None:
            output.append(signal)
    return output


def _resolved_level_signal(
    day: Day,
    *,
    session_name: str,
    session_bars: Sequence[Bar],
    level: LiquidityLevel,
    atr: float,
    asia_percentile: float,
    all_bars: Sequence[Bar],
    minute_index: dict[datetime, int],
    bars_by_open: dict[datetime, Bar],
) -> Signal | None:
    minimum_depth = max(0.02 * atr, 0.03)
    breach_index = next(
        (
            index
            for index, bar in enumerate(session_bars[:-15])
            if (
                bar.high >= level.price + minimum_depth
                if level.break_side == "LONG"
                else bar.low <= level.price - minimum_depth
            )
        ),
        None,
    )
    if breach_index is None:
        return None
    breach = session_bars[breach_index]
    depth = (
        breach.high - level.price
        if level.break_side == "LONG"
        else level.price - breach.low
    )
    if depth > 0.80 * atr:
        return None

    resolution: Literal["REJECTION", "ACCEPTANCE"] | None = None
    resolution_index: int | None = None
    for index in range(
        breach_index,
        min(len(session_bars) - 1, breach_index + 9),
    ):
        bar = session_bars[index]
        outside = (
            bar.close > level.price
            if level.break_side == "LONG"
            else bar.close < level.price
        )
        if not outside:
            resolution = "REJECTION"
            resolution_index = index
            break
        if index - breach_index + 1 >= 3:
            resolution = "ACCEPTANCE"
            resolution_index = index
            break
    if resolution is None or resolution_index is None:
        return None

    if resolution == "REJECTION":
        side: Side = "SHORT" if level.break_side == "LONG" else "LONG"
        confirmation = _displacement_index(
            session_bars,
            start=resolution_index,
            end=min(len(session_bars) - 1, resolution_index + 13),
            side=side,
            atr=atr,
        )
        if confirmation is None:
            return None
        observed = session_bars[breach_index : confirmation + 1]
        extreme = (
            max(bar.high for bar in observed)
            if side == "SHORT"
            else min(bar.low for bar in observed)
        )
        buffer = max(0.03 * atr, 0.05)
        stop = extreme + buffer if side == "SHORT" else extreme - buffer
        state = "FAST_REJECTION"
    else:
        side = level.break_side
        confirmation = _accepted_retest_confirmation(
            session_bars,
            accepted_at=resolution_index,
            level=level.price,
            side=side,
            atr=atr,
        )
        if confirmation is None:
            return None
        retest = session_bars[confirmation]
        buffer = max(0.03 * atr, 0.05)
        stop = (
            min(retest.low, level.price - 0.05 * atr) - buffer
            if side == "LONG"
            else max(retest.high, level.price + 0.05 * atr) + buffer
        )
        state = "ACCEPTED_RETEST"

    return _make_signal(
        day,
        session_name=session_name,
        state=state,
        side=side,
        level=level,
        breach_index=breach_index,
        confirmation_index=confirmation,
        session_bars=session_bars,
        stop=stop,
        atr=atr,
        asia_percentile=asia_percentile,
        depth_atr=depth / atr,
        all_bars=all_bars,
        minute_index=minute_index,
        bars_by_open=bars_by_open,
    )


def _handover_signal(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    asia_high: float,
    asia_low: float,
    atr: float,
    asia_percentile: float,
    all_bars: Sequence[Bar],
    minute_index: dict[datetime, int],
    bars_by_open: dict[datetime, Bar],
) -> Signal | None:
    opening = session_bars[0].open
    break_side: Side | None = (
        "LONG" if opening > asia_high else "SHORT" if opening < asia_low else None
    )
    if break_side is None:
        return None
    level = LiquidityLevel(
        break_side,
        asia_high if break_side == "LONG" else asia_low,
        ("ASIA_HIGH",) if break_side == "LONG" else ("ASIA_LOW",),
    )
    inside_index = next(
        (
            index
            for index, bar in enumerate(session_bars[:90])
            if (
                bar.close < level.price
                if break_side == "LONG"
                else bar.close > level.price
            )
        ),
        None,
    )
    if inside_index is not None:
        side: Side = "SHORT" if break_side == "LONG" else "LONG"
        confirmation = _displacement_index(
            session_bars,
            start=inside_index,
            end=min(len(session_bars) - 1, inside_index + 13),
            side=side,
            atr=atr,
        )
        if confirmation is None:
            return None
        observed = session_bars[: confirmation + 1]
        extreme = (
            max(bar.high for bar in observed)
            if side == "SHORT"
            else min(bar.low for bar in observed)
        )
        buffer = max(0.03 * atr, 0.05)
        stop = extreme + buffer if side == "SHORT" else extreme - buffer
        return _make_signal(
            day,
            session_name="NEW_YORK",
            state="HANDOVER_REJECTION",
            side=side,
            level=level,
            breach_index=0,
            confirmation_index=confirmation,
            session_bars=session_bars,
            stop=stop,
            atr=atr,
            asia_percentile=asia_percentile,
            depth_atr=abs(opening - level.price) / atr,
            all_bars=all_bars,
            minute_index=minute_index,
            bars_by_open=bars_by_open,
        )

    opening_members = session_bars[:15]
    if len(opening_members) != 15:
        return None
    opening_high = max(bar.high for bar in opening_members)
    opening_low = min(bar.low for bar in opening_members)
    confirmation = next(
        (
            index
            for index in range(15, min(len(session_bars) - 1, 75))
            if (
                session_bars[index].close > opening_high
                if break_side == "LONG"
                else session_bars[index].close < opening_low
            )
            and _directional_bar(
                session_bars[index],
                side=break_side,
                atr=atr,
                min_body_atr=0.06,
                min_body_ratio=0.55,
                min_close_location=0.65,
            )
        ),
        None,
    )
    if confirmation is None:
        return None
    recent = session_bars[max(0, confirmation - 5) : confirmation + 1]
    stop = (
        min(bar.low for bar in recent) - max(0.03 * atr, 0.05)
        if break_side == "LONG"
        else max(bar.high for bar in recent) + max(0.03 * atr, 0.05)
    )
    return _make_signal(
        day,
        session_name="NEW_YORK",
        state="HANDOVER_CONFIRMATION",
        side=break_side,
        level=level,
        breach_index=0,
        confirmation_index=confirmation,
        session_bars=session_bars,
        stop=stop,
        atr=atr,
        asia_percentile=asia_percentile,
        depth_atr=abs(opening - level.price) / atr,
        all_bars=all_bars,
        minute_index=minute_index,
        bars_by_open=bars_by_open,
    )


def _accepted_retest_confirmation(
    bars: Sequence[Bar],
    *,
    accepted_at: int,
    level: float,
    side: Side,
    atr: float,
) -> int | None:
    for index in range(
        accepted_at + 1,
        min(len(bars) - 1, accepted_at + 26),
    ):
        bar = bars[index]
        invalidated = (
            bar.close < level - 0.03 * atr
            if side == "LONG"
            else bar.close > level + 0.03 * atr
        )
        if invalidated:
            return None
        touched = (
            bar.low <= level + 0.08 * atr and bar.close > level
            if side == "LONG"
            else bar.high >= level - 0.08 * atr and bar.close < level
        )
        if not touched:
            continue
        if _directional_bar(
            bar,
            side=side,
            atr=atr,
            min_body_atr=0.04,
            min_body_ratio=0.50,
            min_close_location=0.60,
        ):
            return index
        confirmation = _displacement_index(
            bars,
            start=index + 1,
            end=min(len(bars) - 1, index + 4),
            side=side,
            atr=atr,
        )
        return confirmation
    return None


def _displacement_index(
    bars: Sequence[Bar],
    *,
    start: int,
    end: int,
    side: Side,
    atr: float,
) -> int | None:
    for index in range(max(3, start), end):
        prior = bars[index - 3 : index]
        breaks = (
            bars[index].close > max(bar.high for bar in prior)
            if side == "LONG"
            else bars[index].close < min(bar.low for bar in prior)
        )
        if breaks and _directional_bar(
            bars[index],
            side=side,
            atr=atr,
            min_body_atr=0.06,
            min_body_ratio=0.55,
            min_close_location=0.65,
        ):
            return index
    return None


def _make_signal(
    day: Day,
    *,
    session_name: str,
    state: str,
    side: Side,
    level: LiquidityLevel,
    breach_index: int,
    confirmation_index: int,
    session_bars: Sequence[Bar],
    stop: float,
    atr: float,
    asia_percentile: float,
    depth_atr: float,
    all_bars: Sequence[Bar],
    minute_index: dict[datetime, int],
    bars_by_open: dict[datetime, Bar],
) -> Signal | None:
    confirmation = session_bars[confirmation_index]
    entry = bars_by_open.get(confirmation.close_time)
    if entry is None:
        return None
    risk = abs(entry.open - stop)
    if (
        risk <= 0
        or risk / atr < 0.06
        or risk / atr > 1.50
        or (side == "LONG" and stop >= entry.open)
        or (side == "SHORT" and stop <= entry.open)
    ):
        return None
    estimated_cost_r = (entry.spread + 0.17) / risk
    if estimated_cost_r > 0.35:
        return None
    global_index = minute_index.get(confirmation.open_time)
    if global_index is None:
        return None
    baseline = all_bars[max(0, global_index - 60) : global_index]
    if len(baseline) < 30:
        return None
    median_volume = statistics.median(bar.volume for bar in baseline)
    median_spread = statistics.median(bar.spread for bar in baseline)
    family = _level_family(level.names)
    return Signal(
        playbook=f"{session_name}|{state}|{family}",
        session_date=day.session_date,
        side=side,
        signal_time=confirmation.close_time,
        entry_time=entry.open_time,
        entry_reference=entry.open,
        stop=stop,
        base_target_r=2.0,
        max_holding_minutes=180,
        atr=atr,
        evidence={
            "session": session_name,
            "liquidity_state": state,
            "level_price": level.price,
            "level_names": list(level.names),
            "level_confluence": len(level.names),
            "breach_time": session_bars[breach_index].open_time.isoformat(),
            "confirmation_time": confirmation.close_time.isoformat(),
            "breach_depth_atr": depth_atr,
            "asia_range_percentile": asia_percentile,
            "relative_volume": (
                confirmation.volume / median_volume
                if median_volume > 0
                else None
            ),
            "relative_spread": (
                entry.spread / median_spread
                if median_spread > 0
                else None
            ),
            "estimated_cost_r": estimated_cost_r,
        },
    )


def _rolling_levels(
    bars: Sequence[Bar],
    open_times: Sequence[datetime],
    *,
    cutoff: datetime,
) -> tuple[LiquidityLevel, ...]:
    end = bisect_left(open_times, cutoff)
    start = bisect_left(open_times, cutoff - timedelta(hours=24))
    members = bars[start:end]
    if len(members) < 1_000:
        return ()
    return (
        LiquidityLevel(
            "LONG",
            max(bar.high for bar in members),
            ("PRIOR_24H_HIGH",),
        ),
        LiquidityLevel(
            "SHORT",
            min(bar.low for bar in members),
            ("PRIOR_24H_LOW",),
        ),
    )


def _cluster_levels(
    levels: Sequence[LiquidityLevel],
    *,
    atr: float,
) -> list[LiquidityLevel]:
    output: list[LiquidityLevel] = []
    for side in ("LONG", "SHORT"):
        members = sorted(
            (level for level in levels if level.break_side == side),
            key=lambda level: level.price,
        )
        clusters: list[list[LiquidityLevel]] = []
        for level in members:
            if (
                not clusters
                or abs(level.price - clusters[-1][-1].price) > 0.12 * atr
            ):
                clusters.append([level])
            else:
                clusters[-1].append(level)
        for cluster in clusters:
            price = (
                max(level.price for level in cluster)
                if side == "LONG"
                else min(level.price for level in cluster)
            )
            output.append(
                LiquidityLevel(
                    break_side=side,
                    price=price,
                    names=tuple(
                        sorted(
                            {
                                name
                                for level in cluster
                                for name in level.names
                            }
                        )
                    ),
                )
            )
    return output


def _minute_window(
    bars_by_open: dict[datetime, Bar],
    start: datetime,
    end: datetime,
) -> tuple[Bar, ...]:
    expected = int((end - start).total_seconds() // 60)
    values = tuple(
        bars_by_open.get(start + timedelta(minutes=offset))
        for offset in range(expected)
    )
    if any(bar is None for bar in values):
        return ()
    return tuple(bar for bar in values if bar is not None)


def _enrich_cross_market(
    signals: Sequence[Signal],
    *,
    eurusd_bars: Sequence[Bar],
    silver_bars: Sequence[Bar],
) -> list[Signal]:
    inputs = {
        "eurusd": eurusd_bars,
        "silver": silver_bars,
    }
    clocks = {
        name: [bar.close_time for bar in bars]
        for name, bars in inputs.items()
    }
    atrs = {
        name: _atr_by_close(bars)
        for name, bars in inputs.items()
    }
    output: list[Signal] = []
    for signal in signals:
        side_sign = 1 if signal.side == "LONG" else -1
        evidence = dict(signal.evidence)
        for name, bars in inputs.items():
            momentum = _momentum_as_of(
                bars,
                close_times=clocks[name],
                atr_by_close=atrs[name],
                as_of=signal.signal_time,
                lookback=12,
            )
            evidence[f"{name}_60m_signed_atr"] = (
                side_sign * momentum if momentum is not None else None
            )
        output.append(
            Signal(
                playbook=signal.playbook,
                session_date=signal.session_date,
                side=signal.side,
                signal_time=signal.signal_time,
                entry_time=signal.entry_time,
                entry_reference=signal.entry_reference,
                stop=signal.stop,
                base_target_r=signal.base_target_r,
                max_holding_minutes=signal.max_holding_minutes,
                atr=signal.atr,
                evidence=evidence,
            )
        )
    return output


def _momentum_as_of(
    bars: Sequence[Bar],
    *,
    close_times: Sequence[datetime],
    atr_by_close: dict[datetime, float],
    as_of: datetime,
    lookback: int,
) -> float | None:
    index = bisect_right(close_times, as_of) - 1
    if index < lookback:
        return None
    close_time = close_times[index]
    if (
        close_times[index - lookback]
        != close_time - timedelta(minutes=5 * lookback)
    ):
        return None
    atr = atr_by_close.get(close_time)
    if atr is None or atr <= 0:
        return None
    return (bars[index].close - bars[index - lookback].close) / atr


def _managed_results(
    signals: Sequence[Signal],
    *,
    minute_bars: Sequence[Bar],
) -> list[ManagedResult]:
    bars_by_open = {bar.open_time: bar for bar in minute_bars}
    output: list[ManagedResult] = []
    for signal in signals:
        for cost_multiplier in (1.0, 1.5):
            for manager, target_r in (
                ("FIXED_1_50R", 1.5),
                ("FIXED_2_00R", 2.0),
                ("FIXED_3_00R", 3.0),
            ):
                trade = _simulate_minute(
                    signal,
                    bars_by_open=bars_by_open,
                    target_r=target_r,
                    cost_multiplier=cost_multiplier,
                )
                if trade is not None:
                    output.append(
                        ManagedResult(
                            signal=signal,
                            manager=manager,
                            cost_multiplier=cost_multiplier,
                            trade=trade,
                        )
                    )
    return output


def _rules() -> tuple[FundamentalRule, ...]:
    return (
        FundamentalRule("BASE", lambda record: True),
        FundamentalRule(
            "COST_LE_0_20R",
            lambda record: _evidence(record, "estimated_cost_r") <= 0.20,
        ),
        FundamentalRule(
            "HEALTHY_LIQUIDITY",
            lambda record: (
                _evidence(record, "relative_spread") <= 1.25
                and _evidence(record, "relative_volume") >= 0.80
            ),
        ),
        FundamentalRule(
            "DISPLACEMENT_VOLUME_1_20X",
            lambda record: _evidence(record, "relative_volume") >= 1.20,
        ),
        FundamentalRule(
            "ASIA_COMPRESSION_P30",
            lambda record: _evidence(
                record,
                "asia_range_percentile",
            )
            <= 30,
        ),
        FundamentalRule(
            "ASIA_NOT_EXPANDED_P50",
            lambda record: _evidence(
                record,
                "asia_range_percentile",
            )
            <= 50,
        ),
        FundamentalRule(
            "SHALLOW_SWEEP_LE_0_25ATR",
            lambda record: _evidence(record, "breach_depth_atr") <= 0.25,
        ),
        FundamentalRule(
            "DEEP_SWEEP_GE_0_25ATR",
            lambda record: _evidence(record, "breach_depth_atr") >= 0.25,
        ),
        FundamentalRule(
            "LEVEL_CONFLUENCE",
            lambda record: _evidence(record, "level_confluence") >= 2,
        ),
        FundamentalRule(
            "EURUSD_60M_ALIGNED",
            lambda record: record.eurusd_aligned,
        ),
        FundamentalRule(
            "SILVER_60M_ALIGNED",
            lambda record: _evidence(record, "silver_60m_signed_atr") > 0,
        ),
        FundamentalRule(
            "EURUSD_AND_SILVER",
            lambda record: (
                record.eurusd_aligned
                and _evidence(record, "silver_60m_signed_atr") > 0
            ),
        ),
        FundamentalRule(
            "EURUSD_60M_OPPOSED",
            lambda record: _evidence(
                record,
                "eurusd_60m_signed_atr",
            )
            < 0,
        ),
        FundamentalRule(
            "SILVER_60M_OPPOSED",
            lambda record: _evidence(
                record,
                "silver_60m_signed_atr",
            )
            < 0,
        ),
        FundamentalRule(
            "EURUSD_AND_SILVER_OPPOSED",
            lambda record: (
                _evidence(record, "eurusd_60m_signed_atr") < 0
                and _evidence(record, "silver_60m_signed_atr") < 0
            ),
        ),
        FundamentalRule(
            "MACRO_NOT_OPPOSED_MINUS_5",
            lambda record: record.signed_score >= -5,
        ),
        FundamentalRule(
            "MACRO_ALIGNED_5",
            lambda record: record.signed_score >= 5,
        ),
        FundamentalRule(
            "MACRO_CONFLICT_ABS_5",
            lambda record: abs(record.signed_score) < 5,
        ),
        FundamentalRule(
            "MACRO_OPPOSED_MINUS_5",
            lambda record: record.signed_score <= -5,
        ),
        FundamentalRule(
            "MACRO_AND_EURUSD",
            lambda record: (
                record.signed_score >= 0 and record.eurusd_aligned
            ),
        ),
        FundamentalRule(
            "MACRO_AND_CROSS_BREADTH",
            lambda record: (
                record.signed_score >= 0
                and record.eurusd_aligned
                and _evidence(record, "silver_60m_signed_atr") > 0
            ),
        ),
        FundamentalRule(
            "RATES_USD_2_OF_3",
            lambda record: record.core_confirmation_count >= 2,
        ),
        FundamentalRule(
            "REAL_YIELD_ALIGNED",
            lambda record: (
                record.signed_components.get("REAL_YIELD") or 0.0
            )
            > 0,
        ),
        FundamentalRule(
            "REAL_YIELD_AND_MACRO_NOT_OPPOSED",
            lambda record: (
                (record.signed_components.get("REAL_YIELD") or 0.0) > 0
                and record.signed_score >= -5
            ),
        ),
        FundamentalRule(
            "REAL_YIELD_AND_EURUSD",
            lambda record: (
                (record.signed_components.get("REAL_YIELD") or 0.0) > 0
                and record.eurusd_aligned
            ),
        ),
        FundamentalRule(
            "REAL_YIELD_AND_ASIA_NOT_EXPANDED",
            lambda record: (
                (record.signed_components.get("REAL_YIELD") or 0.0) > 0
                and _evidence(record, "asia_range_percentile") <= 50
            ),
        ),
        FundamentalRule(
            "REACTION_FUNCTION_ALIGNED",
            _reaction_function_aligned,
        ),
        FundamentalRule(
            "RECENT_EVENT_ALIGNED",
            lambda record: record.recent_event_aligned,
        ),
    )


def _candidate_results(
    records: Sequence[FundamentalRecord],
    *,
    rules: Sequence[FundamentalRule],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Any]]]:
    archetypes = sorted(
        {record.managed.signal.playbook for record in records}
    )
    managers = sorted({record.managed.manager for record in records})
    candidates = [
        Candidate(
            archetype=archetype,
            rule=rule.name,
            manager=manager,
        )
        for archetype in archetypes
        for rule in rules
        for manager in managers
    ]
    grouped: dict[
        tuple[str, str, float],
        list[FundamentalRecord],
    ] = {}
    for record in records:
        grouped.setdefault(
            (
                record.managed.signal.playbook,
                record.managed.manager,
                record.managed.cost_multiplier,
            ),
            [],
        ).append(record)
    rule_by_name = {rule.name: rule for rule in rules}
    output: dict[tuple[str, float], list[Any]] = {}
    for candidate in candidates:
        rule = rule_by_name[candidate.rule]
        for cost_multiplier in (1.0, 1.5):
            output[(candidate.key, cost_multiplier)] = [
                record.managed.trade
                for record in grouped.get(
                    (
                        candidate.archetype,
                        candidate.manager,
                        cost_multiplier,
                    ),
                    [],
                )
                if rule.predicate(record)
            ]
    return candidates, output


def _rank(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> tuple[float, float, int]:
    trades = _slice(
        candidate_trades[(candidate.key, 1.0)],
        "discovery",
    )
    if not trades:
        return (-999.0, -999.0, 0)
    values = [trade.net_r for trade in trades]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    profit_factor = (
        sum(winners) / abs(sum(losers))
        if winners and losers
        else -999.0
    )
    return (statistics.mean(values), profit_factor, len(trades))


def _feature_coverage(
    records: Sequence[FundamentalRecord],
) -> dict[str, Any]:
    unique: dict[int, FundamentalRecord] = {}
    for record in records:
        unique.setdefault(id(record.managed.signal), record)
    by_year: dict[int, list[FundamentalRecord]] = {}
    for record in unique.values():
        by_year.setdefault(
            record.managed.signal.session_date.year,
            [],
        ).append(record)
    return {
        str(year): {
            "signals": len(members),
            "macro_known": sum(member.coverage > 0 for member in members),
            "eurusd_known": sum(
                member.managed.signal.evidence.get(
                    "eurusd_60m_signed_atr"
                )
                is not None
                for member in members
            ),
            "silver_known": sum(
                member.managed.signal.evidence.get(
                    "silver_60m_signed_atr"
                )
                is not None
                for member in members
            ),
        }
        for year, members in sorted(by_year.items())
    }


def _evidence(record: FundamentalRecord, key: str) -> float:
    value = record.managed.signal.evidence.get(key)
    return float(value) if value is not None else -999.0


def _level_family(names: Sequence[str]) -> str:
    if any(name.startswith("LONDON_PRE_NY") for name in names):
        return "LONDON_HANDOVER"
    if any(name.startswith("ASIA_") for name in names):
        return "ASIA_RANGE"
    return "PRIOR_24H"


def _percentile(value: float, history: Sequence[float]) -> float:
    if not history:
        return 50.0
    return sum(member <= value for member in history) / len(history) * 100


def _coverage(bars: Sequence[Bar]) -> dict[str, Any]:
    return {
        "bars": len(bars),
        "first_close": bars[0].close_time.isoformat() if bars else None,
        "last_close": bars[-1].close_time.isoformat() if bars else None,
    }


def _phase(name: str, elapsed: float) -> None:
    print(
        json.dumps(
            {
                "phase": name,
                "elapsed_seconds": round(elapsed, 3),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
