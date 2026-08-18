from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from explore_session_playbooks import Bar, Day, _build_days
from research_daily_session_playbooks import (
    Side,
    Signal,
    Trade,
    _atr_by_close,
    _directional_bar,
    _metrics,
    _signal,
    _simulate,
)
from research_intraday_usd_confirmation import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
)

from gold_intel.infrastructure.database import session_factory

RulePredicate = Callable[[Signal], bool]
_METRICS_CACHE: dict[tuple[int, ...], dict[str, Any]] = {}
PERIODS = {
    "discovery": (date(2021, 8, 1), date(2023, 1, 1)),
    "validation": (date(2023, 1, 1), date(2024, 1, 1)),
    "forward": (date(2024, 1, 1), date(2025, 1, 1)),
    "all": (date(2021, 8, 1), date(2025, 1, 1)),
}


@dataclass(frozen=True, slots=True)
class ContextRule:
    name: str
    predicate: RulePredicate


@dataclass(frozen=True, slots=True)
class ManagedResult:
    signal: Signal
    manager: str
    cost_multiplier: float
    trade: Trade


@dataclass(frozen=True, slots=True)
class Candidate:
    archetype: str
    rule: str
    manager: str

    @property
    def key(self) -> str:
        return f"{self.archetype}|{self.rule}|{self.manager}"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    async with session_factory() as session:
        query = {
            "load_start": start - timedelta(days=8),
            "load_end": end,
        }
        gold_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "XAUUSD", **query},
                )
            ).mappings()
        )
        eurusd_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "EURUSD", **query},
                )
            ).mappings()
        )

    days = _build_days(gold_bars, start=start, end=end)
    signals = _build_signals(
        days,
        gold_bars=gold_bars,
        eurusd_bars=eurusd_bars,
    )
    managed = _simulate_all(signals, gold_bars=gold_bars)
    candidates, candidate_trades = _candidate_results(managed)
    selected = _select_discovery_candidates(
        candidates,
        candidate_trades=candidate_trades,
    )
    portfolios = {
        f"{cost_multiplier:.2f}x": _portfolio_report(
            selected,
            candidate_trades=candidate_trades,
            cost_multiplier=cost_multiplier,
        )
        for cost_multiplier in (1.0, 1.5)
    }
    report = {
        "contract": {
            "version": "SESSION_STATE_TRANSITION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "signals": len(signals),
            "managed_results": len(managed),
            "candidate_hypotheses": len(candidates),
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
            "selection": (
                "Discovery only: n>=40, expectancy>=0.10R, PF>=1.15, "
                "1.50x-cost expectancy>0, bootstrap lower>=-0.05R; at most "
                "one candidate per archetype."
            ),
            "portfolio": (
                "One XAUUSD position, discovery-expectancy conflict priority, "
                "no new entries after -2R realized on the session date."
            ),
        },
        "signal_funnel": {
            archetype: sum(signal.playbook == archetype for signal in signals)
            for archetype in sorted({signal.playbook for signal in signals})
        },
        "selected_candidates": [
            {
                "key": candidate.key,
                "discovery": _compact_period_metrics(
                    _slice(
                        candidate_trades[(candidate.key, 1.0)],
                        "discovery",
                    ),
                    "discovery",
                ),
                "validation_2023": _compact_period_metrics(
                    _slice(
                        candidate_trades[(candidate.key, 1.0)],
                        "validation",
                    ),
                    "validation",
                ),
                "forward_2024": _compact_period_metrics(
                    _slice(
                        candidate_trades[(candidate.key, 1.0)],
                        "forward",
                    ),
                    "forward",
                ),
            }
            for candidate in selected
        ],
        "top_discovery_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in sorted(
                candidates,
                key=lambda item: _ranking_key(
                    item,
                    candidate_trades=candidate_trades,
                ),
                reverse=True,
            )[: args.top]
        ],
        "portfolios": portfolios,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _build_signals(
    days: Sequence[Day],
    *,
    gold_bars: Sequence[Bar],
    eurusd_bars: Sequence[Bar],
) -> list[Signal]:
    gold_atr = _atr_by_close(gold_bars)
    gold_close_times = [bar.close_time for bar in gold_bars]
    eurusd_atr = _atr_by_close(eurusd_bars)
    eurusd_close_times = [bar.close_time for bar in eurusd_bars]
    asia_history: list[float] = []
    output: list[Signal] = []
    for day in days:
        asia_high = max(bar.high for bar in day.asia)
        asia_low = min(bar.low for bar in day.asia)
        asia_range = asia_high - asia_low
        asia_percentile = _percentile(
            asia_range,
            asia_history[-60:],
        )
        output.extend(
            _scan_session(
                day,
                session_name="LONDON",
                session_bars=day.london,
                asia_high=asia_high,
                asia_low=asia_low,
                asia_percentile=asia_percentile,
                gold_bars=gold_bars,
                gold_close_times=gold_close_times,
                gold_atr=gold_atr,
                eurusd_bars=eurusd_bars,
                eurusd_close_times=eurusd_close_times,
                eurusd_atr=eurusd_atr,
            )
        )
        output.extend(
            _scan_session(
                day,
                session_name="NEW_YORK",
                session_bars=day.new_york,
                asia_high=asia_high,
                asia_low=asia_low,
                asia_percentile=asia_percentile,
                gold_bars=gold_bars,
                gold_close_times=gold_close_times,
                gold_atr=gold_atr,
                eurusd_bars=eurusd_bars,
                eurusd_close_times=eurusd_close_times,
                eurusd_atr=eurusd_atr,
            )
        )
        asia_history.append(asia_range)
    return output


def _scan_session(
    day: Day,
    *,
    session_name: str,
    session_bars: Sequence[Bar],
    asia_high: float,
    asia_low: float,
    asia_percentile: float,
    gold_bars: Sequence[Bar],
    gold_close_times: Sequence[datetime],
    gold_atr: dict[datetime, float],
    eurusd_bars: Sequence[Bar],
    eurusd_close_times: Sequence[datetime],
    eurusd_atr: dict[datetime, float],
) -> list[Signal]:
    found: dict[str, Signal] = {}
    for index in range(3, len(session_bars) - 1):
        current = session_bars[index]
        entry = session_bars[index + 1]
        atr = gold_atr.get(current.close_time)
        if atr is None or atr <= 0:
            continue
        gold_index = bisect_right(gold_close_times, current.close_time) - 1
        if gold_index < 48 or gold_close_times[gold_index] != current.close_time:
            continue
        prior_global = gold_bars[max(0, gold_index - 12) : gold_index]
        if len(prior_global) < 12:
            continue
        gold_60m = (
            current.close - gold_bars[gold_index - 12].close
        ) / atr
        gold_4h = (
            current.close - gold_bars[gold_index - 48].close
        ) / atr
        eurusd_60m = _momentum(
            eurusd_bars,
            close_times=eurusd_close_times,
            atr_by_close=eurusd_atr,
            as_of=current.close_time,
            lookback=12,
        )
        volume_median = statistics.median(bar.volume for bar in prior_global)
        spread_median = statistics.median(bar.spread for bar in prior_global)
        context = {
            "session": session_name,
            "session_bar_index": index,
            "asia_high": asia_high,
            "asia_low": asia_low,
            "asia_range_percentile": asia_percentile,
            "gold_60m_atr": gold_60m,
            "gold_4h_atr": gold_4h,
            "eurusd_60m_atr": eurusd_60m,
            "relative_volume": (
                current.volume / volume_median if volume_median > 0 else 1.0
            ),
            "relative_spread": (
                current.spread / spread_median if spread_median > 0 else 1.0
            ),
            "classification": (
                "Price/session states are calculated; EURUSD confirmation is "
                "an inferred inverse-USD proxy."
            ),
        }
        so_far = session_bars[: index + 1]
        prior3 = session_bars[index - 3 : index]

        if "A1_ACCEPTANCE_MOMENTUM" not in found:
            candidate = _acceptance_momentum(
                day,
                session_bars=session_bars,
                index=index,
                asia_high=asia_high,
                asia_low=asia_low,
                atr=atr,
                gold_60m=gold_60m,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate

        if "A2_ACCEPTED_RETEST" not in found:
            candidate = _accepted_retest(
                day,
                session_bars=session_bars,
                index=index,
                asia_high=asia_high,
                asia_low=asia_low,
                atr=atr,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate

        if "A3_FAILED_AUCTION_REVERSAL" not in found:
            candidate = _failed_auction(
                day,
                session_bars=session_bars,
                index=index,
                so_far=so_far,
                prior3=prior3,
                asia_high=asia_high,
                asia_low=asia_low,
                atr=atr,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate

        if (
            session_name == "NEW_YORK"
            and "A4_HANDOVER_CONFIRMATION" not in found
        ):
            candidate = _handover_confirmation(
                day,
                session_bars=session_bars,
                index=index,
                prior3=prior3,
                atr=atr,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate

        if (
            session_name == "NEW_YORK"
            and "A5_HANDOVER_REJECTION" not in found
        ):
            candidate = _handover_rejection(
                day,
                session_bars=session_bars,
                index=index,
                so_far=so_far,
                prior3=prior3,
                asia_high=asia_high,
                asia_low=asia_low,
                atr=atr,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate

        if "A6_TREND_PULLBACK_RECLAIM" not in found:
            candidate = _trend_pullback_reclaim(
                day,
                session_bars=session_bars,
                index=index,
                prior3=prior3,
                gold_4h=gold_4h,
                atr=atr,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate

        if index == 5 and "A7_OPENING_DRIVE" not in found:
            candidate = _opening_drive(
                day,
                session_bars=session_bars,
                index=index,
                atr=atr,
                context=context,
            )
            if candidate is not None:
                found[candidate.playbook] = candidate

        if len(found) == 7:
            break
        if entry.open_time != current.close_time:
            raise RuntimeError("Non-contiguous signal and entry bars")
    return list(found.values())


def _acceptance_momentum(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    index: int,
    asia_high: float,
    asia_low: float,
    atr: float,
    gold_60m: float,
    context: dict[str, Any],
) -> Signal | None:
    current = session_bars[index]
    prior = session_bars[index - 1]
    for side, boundary in (("LONG", asia_high), ("SHORT", asia_low)):
        outside = (
            prior.close > boundary and current.close > boundary
            if side == "LONG"
            else prior.close < boundary and current.close < boundary
        )
        signed_momentum = gold_60m if side == "LONG" else -gold_60m
        if (
            outside
            and signed_momentum >= 0.25
            and _directional_bar(
                current,
                side=side,
                atr=atr,
                min_body_atr=0.20,
                min_body_ratio=0.50,
                min_close_location=0.60,
            )
        ):
            stop = (
                boundary - 0.15 * atr
                if side == "LONG"
                else boundary + 0.15 * atr
            )
            return _research_signal(
                day,
                playbook="A1_ACCEPTANCE_MOMENTUM",
                side=side,
                signal_bar=current,
                entry_bar=session_bars[index + 1],
                stop=stop,
                atr=atr,
                context={**context, "reference_boundary": boundary},
            )
    return None


def _accepted_retest(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    index: int,
    asia_high: float,
    asia_low: float,
    atr: float,
    context: dict[str, Any],
) -> Signal | None:
    current = session_bars[index]
    for side, boundary in (("LONG", asia_high), ("SHORT", asia_low)):
        accepted_before = any(
            (
                session_bars[cursor - 1].close > boundary
                and session_bars[cursor].close > boundary
                if side == "LONG"
                else session_bars[cursor - 1].close < boundary
                and session_bars[cursor].close < boundary
            )
            for cursor in range(1, index)
        )
        touched = (
            current.low <= boundary + 0.15 * atr
            if side == "LONG"
            else current.high >= boundary - 0.15 * atr
        )
        held = (
            current.close > boundary
            if side == "LONG"
            else current.close < boundary
        )
        if (
            accepted_before
            and touched
            and held
            and _directional_bar(
                current,
                side=side,
                atr=atr,
                min_body_atr=0.15,
                min_body_ratio=0.50,
                min_close_location=0.60,
            )
        ):
            stop = (
                current.low - 0.10 * atr
                if side == "LONG"
                else current.high + 0.10 * atr
            )
            return _research_signal(
                day,
                playbook="A2_ACCEPTED_RETEST",
                side=side,
                signal_bar=current,
                entry_bar=session_bars[index + 1],
                stop=stop,
                atr=atr,
                context={**context, "reference_boundary": boundary},
            )
    return None


def _failed_auction(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    index: int,
    so_far: Sequence[Bar],
    prior3: Sequence[Bar],
    asia_high: float,
    asia_low: float,
    atr: float,
    context: dict[str, Any],
) -> Signal | None:
    current = session_bars[index]
    breached_high = any(bar.high > asia_high for bar in so_far)
    breached_low = any(bar.low < asia_low for bar in so_far)
    if breached_high == breached_low:
        return None
    side: Side = "SHORT" if breached_high else "LONG"
    inside = asia_low < current.close < asia_high
    displaced = (
        current.close < min(bar.low for bar in prior3)
        if side == "SHORT"
        else current.close > max(bar.high for bar in prior3)
    )
    if not inside or not displaced or not _directional_bar(
        current,
        side=side,
        atr=atr,
        min_body_atr=0.20,
        min_body_ratio=0.50,
        min_close_location=0.60,
    ):
        return None
    extreme = (
        max(bar.high for bar in so_far)
        if side == "SHORT"
        else min(bar.low for bar in so_far)
    )
    stop = extreme + 0.10 * atr if side == "SHORT" else extreme - 0.10 * atr
    return _research_signal(
        day,
        playbook="A3_FAILED_AUCTION_REVERSAL",
        side=side,
        signal_bar=current,
        entry_bar=session_bars[index + 1],
        stop=stop,
        atr=atr,
        context={**context, "failed_auction_extreme": extreme},
    )


def _handover_confirmation(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    index: int,
    prior3: Sequence[Bar],
    atr: float,
    context: dict[str, Any],
) -> Signal | None:
    london_move = day.london[-1].close - day.london[0].open
    if abs(london_move) < atr:
        return None
    side: Side = "LONG" if london_move > 0 else "SHORT"
    current = session_bars[index]
    ny_move = current.close - session_bars[0].open
    aligned = ny_move > 0.50 * atr if side == "LONG" else ny_move < -0.50 * atr
    displaced = (
        current.close > max(bar.high for bar in prior3)
        if side == "LONG"
        else current.close < min(bar.low for bar in prior3)
    )
    if not aligned or not displaced or not _directional_bar(
        current,
        side=side,
        atr=atr,
        min_body_atr=0.20,
        min_body_ratio=0.50,
        min_close_location=0.60,
    ):
        return None
    recent = session_bars[max(0, index - 6) : index + 1]
    stop = (
        min(bar.low for bar in recent) - 0.10 * atr
        if side == "LONG"
        else max(bar.high for bar in recent) + 0.10 * atr
    )
    return _research_signal(
        day,
        playbook="A4_HANDOVER_CONFIRMATION",
        side=side,
        signal_bar=current,
        entry_bar=session_bars[index + 1],
        stop=stop,
        atr=atr,
        context={**context, "london_move_atr": london_move / atr},
    )


def _handover_rejection(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    index: int,
    so_far: Sequence[Bar],
    prior3: Sequence[Bar],
    asia_high: float,
    asia_low: float,
    atr: float,
    context: dict[str, Any],
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
    side: Side = "SHORT" if london_side == "LONG" else "LONG"
    current = session_bars[index]
    returned_inside = asia_low < current.close < asia_high
    displaced = (
        current.close < min(bar.low for bar in prior3)
        if side == "SHORT"
        else current.close > max(bar.high for bar in prior3)
    )
    if not returned_inside or not displaced or not _directional_bar(
        current,
        side=side,
        atr=atr,
        min_body_atr=0.20,
        min_body_ratio=0.50,
        min_close_location=0.60,
    ):
        return None
    stop = (
        max(bar.high for bar in so_far) + 0.10 * atr
        if side == "SHORT"
        else min(bar.low for bar in so_far) - 0.10 * atr
    )
    return _research_signal(
        day,
        playbook="A5_HANDOVER_REJECTION",
        side=side,
        signal_bar=current,
        entry_bar=session_bars[index + 1],
        stop=stop,
        atr=atr,
        context={**context, "rejected_london_side": london_side},
    )


def _trend_pullback_reclaim(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    index: int,
    prior3: Sequence[Bar],
    gold_4h: float,
    atr: float,
    context: dict[str, Any],
) -> Signal | None:
    if abs(gold_4h) < 2.0:
        return None
    side: Side = "LONG" if gold_4h > 0 else "SHORT"
    session_open = session_bars[0].open
    prior = session_bars[index - 1]
    current = session_bars[index]
    crossed = (
        prior.close <= session_open < current.close
        if side == "LONG"
        else prior.close >= session_open > current.close
    )
    displaced = (
        current.close > max(bar.high for bar in prior3)
        if side == "LONG"
        else current.close < min(bar.low for bar in prior3)
    )
    if not crossed or not displaced or not _directional_bar(
        current,
        side=side,
        atr=atr,
        min_body_atr=0.20,
        min_body_ratio=0.50,
        min_close_location=0.60,
    ):
        return None
    auction = session_bars[: index + 1]
    stop = (
        min(bar.low for bar in auction) - 0.10 * atr
        if side == "LONG"
        else max(bar.high for bar in auction) + 0.10 * atr
    )
    return _research_signal(
        day,
        playbook="A6_TREND_PULLBACK_RECLAIM",
        side=side,
        signal_bar=current,
        entry_bar=session_bars[index + 1],
        stop=stop,
        atr=atr,
        context={**context, "session_open": session_open},
    )


def _opening_drive(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    index: int,
    atr: float,
    context: dict[str, Any],
) -> Signal | None:
    opening = session_bars[: index + 1]
    current = session_bars[index]
    move = current.close - opening[0].open
    if abs(move) < 2.0 * atr:
        return None
    side: Side = "LONG" if move > 0 else "SHORT"
    if not _directional_bar(
        current,
        side=side,
        atr=atr,
        min_body_atr=0.20,
        min_body_ratio=0.50,
        min_close_location=0.60,
    ):
        return None
    high = max(bar.high for bar in opening)
    low = min(bar.low for bar in opening)
    stop = (high + low) / 2
    return _research_signal(
        day,
        playbook="A7_OPENING_DRIVE",
        side=side,
        signal_bar=current,
        entry_bar=session_bars[index + 1],
        stop=stop,
        atr=atr,
        context={
            **context,
            "opening_move_atr": move / atr,
            "opening_range_high": high,
            "opening_range_low": low,
        },
    )


def _research_signal(
    day: Day,
    *,
    playbook: str,
    side: Side,
    signal_bar: Bar,
    entry_bar: Bar,
    stop: float,
    atr: float,
    context: dict[str, Any],
) -> Signal | None:
    if (side == "LONG" and stop >= entry_bar.open) or (
        side == "SHORT" and stop <= entry_bar.open
    ):
        return None
    risk_atr = abs(entry_bar.open - stop) / atr
    if not 0.30 <= risk_atr <= 8.00:
        return None
    exit_at = day.new_york[-1].close_time
    holding = int((exit_at - entry_bar.open_time).total_seconds() // 60)
    if holding < 10:
        return None
    eurusd = context.get("eurusd_60m_atr")
    signed_eurusd = (
        (1 if side == "LONG" else -1) * float(eurusd)
        if eurusd is not None
        else None
    )
    return _signal(
        playbook=playbook,
        day=day,
        side=side,
        signal_bar=signal_bar,
        entry_bar=entry_bar,
        stop=stop,
        target_r=2.0,
        holding_minutes=holding,
        atr=atr,
        evidence={
            **context,
            "eurusd_60m_signed_atr": signed_eurusd,
            "risk_atr": risk_atr,
        },
    )


def _momentum(
    bars: Sequence[Bar],
    *,
    close_times: Sequence[datetime],
    atr_by_close: dict[datetime, float],
    as_of: datetime,
    lookback: int,
) -> float | None:
    index = bisect_right(close_times, as_of) - 1
    if index < lookback or close_times[index] != as_of:
        return None
    atr = atr_by_close.get(as_of)
    if atr is None or atr <= 0:
        return None
    return (bars[index].close - bars[index - lookback].close) / atr


def _simulate_all(
    signals: Sequence[Signal],
    *,
    gold_bars: Sequence[Bar],
) -> list[ManagedResult]:
    bars_by_open = {bar.open_time: bar for bar in gold_bars}
    output: list[ManagedResult] = []
    for signal in signals:
        for cost_multiplier in (1.0, 1.5):
            for manager, target in (
                ("FIXED_1_50R", 1.5),
                ("FIXED_2_00R", 2.0),
            ):
                trade = _simulate(
                    signal,
                    bars_by_open,
                    target_r=target,
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
            partial = _simulate_partial_runner(
                signal,
                bars_by_open=bars_by_open,
                cost_multiplier=cost_multiplier,
            )
            if partial is not None:
                output.append(
                    ManagedResult(
                        signal=signal,
                        manager="PARTIAL_1R_RUNNER_4R",
                        cost_multiplier=cost_multiplier,
                        trade=partial,
                    )
                )
    return output


def _simulate_partial_runner(
    signal: Signal,
    *,
    bars_by_open: dict[datetime, Bar],
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
    if any(bar is None for bar in path):
        return None
    bars = [bar for bar in path if bar is not None]
    direction = 1 if signal.side == "LONG" else -1
    one_r = signal.entry_reference + direction * risk
    four_r = signal.entry_reference + direction * 4.0 * risk
    active_stop = signal.stop
    remaining = 1.0
    gross_r = 0.0
    partial_taken = False
    exit_bar = bars[-1]
    exit_reason = "TIME"
    weighted_exit_spread = 0.0
    favourable = 0.0
    adverse = 0.0
    for index, bar in enumerate(bars):
        if signal.side == "LONG":
            stop_hit = bar.low <= active_stop
            one_hit = bar.high >= one_r
            four_hit = bar.high >= four_r
            favourable = max(favourable, bar.high - signal.entry_reference)
            adverse = max(adverse, signal.entry_reference - bar.low)
        else:
            stop_hit = bar.high >= active_stop
            one_hit = bar.low <= one_r
            four_hit = bar.low <= four_r
            favourable = max(favourable, signal.entry_reference - bar.low)
            adverse = max(adverse, bar.high - signal.entry_reference)
        if stop_hit:
            gross_r += (
                remaining
                * direction
                * (active_stop - signal.entry_reference)
                / risk
            )
            weighted_exit_spread += remaining * bar.spread
            exit_bar = bar
            exit_reason = "STOP" if not partial_taken else "RUNNER_STOP"
            remaining = 0.0
            break
        if not partial_taken and one_hit:
            gross_r += 0.5
            weighted_exit_spread += 0.5 * bar.spread
            remaining = 0.5
            partial_taken = True
            active_stop = signal.entry_reference
        elif partial_taken and four_hit:
            gross_r += remaining * 4.0
            weighted_exit_spread += remaining * bar.spread
            exit_bar = bar
            exit_reason = "RUNNER_4R"
            remaining = 0.0
            break
        if partial_taken and index >= 3:
            completed = bars[index - 2 : index + 1]
            trail = (
                min(member.low for member in completed) - 0.10 * signal.atr
                if signal.side == "LONG"
                else max(member.high for member in completed) + 0.10 * signal.atr
            )
            # A bar-close trailing decision cannot fill above the same close for a
            # long (or below it for a short) on the next bar. Keep the stop on the
            # executable side of the price that was known when it was advanced.
            trail = (
                min(trail, bar.close - 0.01)
                if signal.side == "LONG"
                else max(trail, bar.close + 0.01)
            )
            active_stop = (
                max(active_stop, trail)
                if signal.side == "LONG"
                else min(active_stop, trail)
            )
    if remaining > 0:
        gross_r += (
            remaining
            * direction
            * (exit_bar.close - signal.entry_reference)
            / risk
        )
        weighted_exit_spread += remaining * exit_bar.spread
    cost_price = (
        bars[0].spread / 2
        + weighted_exit_spread / 2
        + 0.10
        + 0.07
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
            "manager": "PARTIAL_1R_RUNNER_4R",
            "partial_taken": partial_taken,
            "cost_multiplier": cost_multiplier,
        },
    )


def _context_rules() -> tuple[ContextRule, ...]:
    return (
        ContextRule("BASE", lambda signal: True),
        ContextRule(
            "EURUSD_60M_ALIGNED",
            lambda signal: (
                _evidence_float(signal, "eurusd_60m_signed_atr") > 0
            ),
        ),
        ContextRule(
            "ASIA_COMPRESSION_P30",
            lambda signal: (
                _evidence_float(signal, "asia_range_percentile") <= 30
            ),
        ),
        ContextRule(
            "EURUSD_AND_ASIA_COMPRESSION",
            lambda signal: (
                _evidence_float(signal, "eurusd_60m_signed_atr") > 0
                and _evidence_float(signal, "asia_range_percentile") <= 30
            ),
        ),
        ContextRule(
            "SPREAD_LE_1_25X",
            lambda signal: _evidence_float(signal, "relative_spread") <= 1.25,
        ),
        ContextRule(
            "VOLUME_GE_1_20X",
            lambda signal: _evidence_float(signal, "relative_volume") >= 1.20,
        ),
    )


def _candidate_results(
    managed: Sequence[ManagedResult],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Trade]]]:
    archetypes = sorted({result.signal.playbook for result in managed})
    managers = sorted({result.manager for result in managed})
    candidates = [
        Candidate(archetype=archetype, rule=rule.name, manager=manager)
        for archetype in archetypes
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


def _select_discovery_candidates(
    candidates: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
) -> list[Candidate]:
    eligible = [
        candidate
        for candidate in candidates
        if _selectable(
            _slice(candidate_trades[(candidate.key, 1.0)], "discovery"),
            stressed=_slice(
                candidate_trades[(candidate.key, 1.5)],
                "discovery",
            ),
        )
    ]
    by_archetype: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in eligible:
        by_archetype[candidate.archetype].append(candidate)
    selected = [
        max(
            members,
            key=lambda candidate: _ranking_key(
                candidate,
                candidate_trades=candidate_trades,
            ),
        )
        for members in by_archetype.values()
    ]
    return sorted(
        selected,
        key=lambda candidate: _ranking_key(
            candidate,
            candidate_trades=candidate_trades,
        ),
        reverse=True,
    )


def _selectable(
    trades: Sequence[Trade],
    *,
    stressed: Sequence[Trade],
) -> bool:
    if len(trades) < 40 or not stressed:
        return False
    net = [trade.net_r for trade in trades]
    stressed_net = [trade.net_r for trade in stressed]
    winners = [value for value in net if value > 0]
    losers = [value for value in net if value < 0]
    if not winners or not losers:
        return False
    expectancy = round(statistics.mean(net), 6)
    profit_factor = round(sum(winners) / abs(sum(losers)), 6)
    stressed_expectancy = round(statistics.mean(stressed_net), 6)
    if (
        expectancy < 0.10
        or profit_factor < 1.15
        or stressed_expectancy <= 0
    ):
        return False
    # Bootstrap only candidates that pass the deterministic cheap gates.
    metrics = _cached_metrics(trades)
    interval = metrics.get("bootstrap_95ci")
    return bool(
        isinstance(interval, list)
        and float(interval[0]) >= -0.05
    )


def _ranking_key(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
) -> tuple[float, float, int]:
    metrics = _cached_metrics(
        _slice(
            candidate_trades[(candidate.key, 1.0)],
            "discovery",
        )
    )
    expectancy = metrics["net_expectancy_r"]
    profit_factor = metrics["profit_factor"]
    return (
        float(expectancy) if expectancy is not None else -999.0,
        float(profit_factor) if profit_factor is not None else -999.0,
        int(metrics["trades"]),
    )


def _candidate_report(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
) -> dict[str, Any]:
    base = candidate_trades[(candidate.key, 1.0)]
    stressed = candidate_trades[(candidate.key, 1.5)]
    return {
        "key": candidate.key,
        "selectable_on_discovery": _selectable(
            _slice(base, "discovery"),
            stressed=_slice(stressed, "discovery"),
        ),
        "discovery": _compact_period_metrics(
            _slice(base, "discovery"),
            "discovery",
        ),
        "discovery_1_50x_cost": _compact_period_metrics(
            _slice(stressed, "discovery"),
            "discovery",
        ),
        "validation_2023": _compact_period_metrics(
            _slice(base, "validation"),
            "validation",
        ),
        "forward_2024": _compact_period_metrics(
            _slice(base, "forward"),
            "forward",
        ),
    }


def _portfolio_report(
    selected: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
    cost_multiplier: float,
) -> dict[str, Any]:
    priority = {
        candidate.key: index for index, candidate in enumerate(selected)
    }
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
        )
    )
    accepted: list[Trade] = []
    open_until: datetime | None = None
    realized_by_date: dict[date, float] = defaultdict(float)
    skipped_overlap = 0
    skipped_daily_loss = 0
    for trade, _ in members:
        if open_until is not None and trade.entry_time < open_until:
            skipped_overlap += 1
            continue
        if realized_by_date[trade.session_date] <= -2.0:
            skipped_daily_loss += 1
            continue
        accepted.append(trade)
        open_until = trade.exit_time
        realized_by_date[trade.session_date] += trade.net_r
    discovery = _slice(accepted, "discovery")
    validation = _slice(accepted, "validation")
    forward = _slice(accepted, "forward")
    all_metrics = _cached_metrics(accepted)
    profit_by_archetype: dict[str, float] = defaultdict(float)
    for trade in accepted:
        profit_by_archetype[trade.playbook] += max(0.0, trade.net_r)
    positive_profit = sum(profit_by_archetype.values())
    max_profit_share = (
        max(profit_by_archetype.values(), default=0.0) / positive_profit
        if positive_profit > 0
        else 1.0
    )
    period_metrics = [
        _cached_metrics(slice_trades)
        for slice_trades in (discovery, validation, forward)
    ]
    qualifies = bool(
        selected
        and all(metric["trades"] >= 20 for metric in period_metrics)
        and all(
            metric["net_expectancy_r"] is not None
            and float(metric["net_expectancy_r"]) > 0
            and metric["profit_factor"] is not None
            and float(metric["profit_factor"]) > 1.25
            for metric in period_metrics
        )
        and all_metrics["profit_factor"] is not None
        and float(all_metrics["profit_factor"]) > 1.25
        and max_profit_share <= 0.60
    )
    return {
        "selected_candidate_count": len(selected),
        "accepted_trades": len(accepted),
        "skipped_overlap": skipped_overlap,
        "skipped_daily_loss": skipped_daily_loss,
        "discovery": _compact_period_metrics(discovery, "discovery"),
        "validation_2023": _compact_period_metrics(
            validation,
            "validation",
        ),
        "forward_2024": _compact_period_metrics(forward, "forward"),
        "all_pre_2025": _compact_period_metrics(accepted, "all"),
        "max_positive_profit_share_pct": round(max_profit_share * 100, 3),
        "qualifies_before_fundamental_overlay": qualifies,
    }


def _slice(trades: Sequence[Trade], period: str) -> list[Trade]:
    if period == "discovery":
        return [
            trade
            for trade in trades
            if trade.session_date < date(2023, 1, 1)
        ]
    if period == "validation":
        return [
            trade
            for trade in trades
            if date(2023, 1, 1)
            <= trade.session_date
            < date(2024, 1, 1)
        ]
    if period == "forward":
        return [
            trade
            for trade in trades
            if date(2024, 1, 1)
            <= trade.session_date
            < date(2025, 1, 1)
        ]
    raise ValueError(f"Unknown period: {period}")


def _compact_period_metrics(
    trades: Sequence[Trade],
    period: str,
) -> dict[str, Any]:
    start, end = PERIODS[period]
    return _compact_metrics(trades, calendar_start=start, calendar_end=end)


def _compact_metrics(
    trades: Sequence[Trade],
    *,
    calendar_start: date,
    calendar_end: date,
) -> dict[str, Any]:
    metrics = _cached_metrics(trades)
    capital = metrics.get("capital_paths", {}).get("1.00%", {})
    monthly = _calendar_month_metrics(
        trades,
        start=calendar_start,
        end=calendar_end,
    )
    return {
        "trades": metrics["trades"],
        "win_rate_pct": metrics.get("win_rate_pct"),
        "net_expectancy_r": metrics.get("net_expectancy_r"),
        "profit_factor": metrics.get("profit_factor"),
        "total_net_r": metrics.get("total_net_r"),
        "bootstrap_95ci": metrics.get("bootstrap_95ci"),
        "average_cost_r": metrics.get("average_cost_r"),
        "average_mfe_r": metrics.get("average_mfe_r"),
        "average_mae_r": metrics.get("average_mae_r"),
        "average_holding_minutes": metrics.get("average_holding_minutes"),
        "maximum_drawdown_r": metrics.get("maximum_drawdown_r"),
        "maximum_consecutive_losses": metrics.get(
            "maximum_consecutive_losses"
        ),
        "calendar_months": monthly["months"],
        "months_with_trades": monthly["months_with_trades"],
        "average_monthly_r": monthly["average_r"],
        "median_monthly_r": monthly["median_r"],
        "positive_month_pct": monthly["positive_month_pct"],
        "target_10r_month_pct": monthly["target_10r_month_pct"],
        "average_monthly_pnl_usd_at_1pct": monthly[
            "average_pnl_usd_at_1pct"
        ],
        "target_1000_month_pct_at_1pct": monthly[
            "target_1000_month_pct_at_1pct"
        ],
        "required_risk_pct_for_1000_average": monthly[
            "required_risk_pct_for_1000_average"
        ],
        "best_month_r": monthly["best_r"],
        "worst_month_r": monthly["worst_r"],
        "final_equity_at_1pct": capital.get("final_equity"),
        "maximum_drawdown_pct_at_1pct": capital.get(
            "maximum_drawdown_pct"
        ),
    }


def _calendar_month_metrics(
    trades: Sequence[Trade],
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    month_keys: list[str] = []
    cursor = date(start.year, start.month, 1)
    while cursor < end:
        month_keys.append(cursor.strftime("%Y-%m"))
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    r_by_month = {key: 0.0 for key in month_keys}
    pnl_by_month = {key: 0.0 for key in month_keys}
    equity = 10_000.0
    months_with_trades: set[str] = set()
    for trade in sorted(trades, key=lambda item: item.entry_time):
        key = trade.session_date.strftime("%Y-%m")
        if key not in r_by_month:
            continue
        r_by_month[key] += trade.net_r
        pnl = equity * 0.01 * trade.net_r
        equity += pnl
        pnl_by_month[key] += pnl
        months_with_trades.add(key)
    r_values = list(r_by_month.values())
    pnl_values = list(pnl_by_month.values())
    average_r = statistics.mean(r_values) if r_values else 0.0
    return {
        "months": len(month_keys),
        "months_with_trades": len(months_with_trades),
        "average_r": round(average_r, 6),
        "median_r": round(statistics.median(r_values), 6),
        "positive_month_pct": round(
            sum(value > 0 for value in r_values) / len(r_values) * 100,
            4,
        ),
        "target_10r_month_pct": round(
            sum(value >= 10 for value in r_values) / len(r_values) * 100,
            4,
        ),
        "average_pnl_usd_at_1pct": round(
            statistics.mean(pnl_values),
            2,
        ),
        "target_1000_month_pct_at_1pct": round(
            sum(value >= 1_000 for value in pnl_values)
            / len(pnl_values)
            * 100,
            4,
        ),
        "required_risk_pct_for_1000_average": (
            round(10.0 / average_r, 4) if average_r > 0 else None
        ),
        "best_r": round(max(r_values), 6),
        "worst_r": round(min(r_values), 6),
    }


def _cached_metrics(trades: Sequence[Trade]) -> dict[str, Any]:
    key = tuple(id(trade) for trade in trades)
    cached = _METRICS_CACHE.get(key)
    if cached is None:
        cached = _metrics(trades)
        _METRICS_CACHE[key] = cached
    return cached


def _evidence_float(signal: Signal, key: str) -> float:
    value = signal.evidence.get(key)
    return float(value) if value is not None else -999.0


def _percentile(value: float, history: Sequence[float]) -> float:
    if not history:
        return 50.0
    return sum(item <= value for item in history) / len(history) * 100


if __name__ == "__main__":
    asyncio.run(main())
