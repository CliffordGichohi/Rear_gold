from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
from research_multi_asset_session_portfolio import (
    CLUSTERS,
    COSTS,
    FIVE_MINUTE_SQL,
    POINT_SIZES,
    _annual_gate,
    _coverage,
    _managed_results,
    _portfolio_report,
    _signal_funnel,
    _target_gate,
    _write_cache,
)
from research_session_state_transitions import (
    Candidate,
    ContextRule,
    ManagedResult,
    _candidate_report,
    _ranking_key,
    _select_discovery_candidates,
)

from gold_intel.infrastructure.database import session_factory

LOCKED_HOLDOUT = datetime(2025, 1, 1, tzinfo=UTC)
LONDON = ZoneInfo("Europe/London")
BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--us500-csv-dir", type=Path, required=True)
    parser.add_argument("--cache-output", type=Path)
    parser.add_argument("--top", type=int, default=80)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > LOCKED_HOLDOUT:
        raise ValueError("The locked 2025 holdout must not be loaded")

    started = time.perf_counter()
    signals: list[Signal] = []
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
            instrument_signals = _signals(
                instrument,
                bars=bars,
                start=start,
                end=end,
            )
            signals.extend(instrument_signals)
            managed.extend(_managed_results(instrument_signals, bars=bars))
            coverage[instrument] = _coverage(bars)
            _phase(f"{instrument}_COMPLETE", started)

    us500 = _five_minute_bars_from_csv_directory(
        args.us500_csv_dir,
        load_start=query["load_start"],
        load_end=end,
        point_size=POINT_SIZES["US500"],
    )
    us500_signals = _signals(
        "US500",
        bars=us500,
        start=start,
        end=end,
    )
    signals.extend(us500_signals)
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
    base = _portfolio_report(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    stress = _portfolio_report(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.5,
    )
    report = {
        "contract": {
            "version": "MULTI_ASSET_TREND_REVERSION_SCREEN_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "families": {
                "DONCHIAN_BREAKOUT": (
                    "Directional close beyond the prior completed six-hour "
                    "high/low during the liquid session."
                ),
                "FAILED_DONCHIAN": (
                    "Sweep beyond the prior six-hour extreme followed by a "
                    "directional close back inside."
                ),
                "COMPRESSION_BREAK": (
                    "Directional release beyond a completed one-hour range "
                    "whose width is at most 2.50 five-minute ATR."
                ),
                "EXTENSION_REJECTION": (
                    "Directional rejection after reaching at least two ATR "
                    "from the prior completed two-hour mean."
                ),
            },
            "sessions": (
                "08:00-16:00 Europe/London for metals and EURUSD; "
                "09:30-16:00 America/New_York for US500; DST-aware."
            ),
            "risk": (
                "Structural stop widened, never narrowed, to at least 0.75 ATR "
                "and enough distance to cap estimated round-trip friction at "
                "0.15R; reject above 2.50 ATR."
            ),
            "execution": (
                "Next five-minute open, fixed 1.5R/2R/3R/4R exits, family time "
                "limit, observed spread, slippage, commission, stop-first "
                "same-bar handling, and 1.50x friction stress."
            ),
            "selection": (
                "Calendar 2021-08 through 2022 only; at least 40 discovery "
                "trades, expectancy >=0.10R, PF >=1.15, positive stressed "
                "expectancy, and bootstrap lower bound >=-0.05R."
            ),
        },
        "coverage": coverage,
        "source_counts": {
            "signals": len(signals),
            "managed_executions": len(managed),
            "candidate_hypotheses": len(candidates),
            "selected_candidates": len(selected),
        },
        "signal_funnel": _signal_funnel(signals),
        "selected_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in selected
        ],
        "portfolio": {
            "base_cost": base,
            "cost_stress_1_50x": stress,
            "positive_each_development_year": _annual_gate(
                selected,
                candidate_trades=candidate_trades,
            ),
            "ten_r_monthly_promotion_gate": _target_gate(base, stress),
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


def _signals(
    instrument: str,
    *,
    bars: Sequence[Bar],
    start: datetime,
    end: datetime,
) -> list[Signal]:
    if not bars:
        raise RuntimeError(f"No five-minute bars for {instrument}")
    if bars[-1].open_time >= LOCKED_HOLDOUT:
        raise RuntimeError(f"Locked holdout leaked into {instrument}")
    by_open = {bar.open_time: bar for bar in bars}
    atr_fast = _atr_by_close(bars, window=14)
    atr_slow = _atr_by_close(bars, window=96)
    output: list[Signal] = []
    used: set[tuple[date, str]] = set()
    for current in bars:
        if not start <= current.close_time < end:
            continue
        session = _liquid_session(
            instrument,
            current.open_time,
        )
        if session is None:
            continue
        session_name, local_date, session_end = session
        entry = by_open.get(current.close_time)
        atr = atr_fast.get(current.close_time)
        slow_atr = atr_slow.get(current.close_time)
        if entry is None or atr is None or atr <= 0 or slow_atr is None or slow_atr <= 0:
            continue
        history_12 = _history(
            by_open,
            end=current.open_time,
            bars=12,
        )
        history_24 = _history(
            by_open,
            end=current.open_time,
            bars=24,
        )
        history_72 = _history(
            by_open,
            end=current.open_time,
            bars=72,
        )
        if history_12 is None or history_24 is None or history_72 is None:
            continue
        context = _context(
            current,
            history_12=history_12,
            history_72=history_72,
            atr=atr,
            slow_atr=slow_atr,
        )
        proposals = (
            _donchian_breakout(
                current,
                history=history_72,
                atr=atr,
            ),
            _failed_donchian(
                current,
                history=history_72,
                atr=atr,
            ),
            _compression_break(
                current,
                history=history_12,
                atr=atr,
            ),
            _extension_rejection(
                current,
                history=history_24,
                atr=atr,
            ),
        )
        for proposal in proposals:
            if proposal is None:
                continue
            family, side, structural_stop, max_minutes = proposal
            key = (local_date, family)
            if key in used:
                continue
            signal = _make_signal(
                instrument,
                session_name=session_name,
                family=family,
                session_date=local_date,
                side=side,
                signal_bar=current,
                entry_bar=entry,
                structural_stop=structural_stop,
                atr=atr,
                session_end=session_end,
                max_minutes=max_minutes,
                context=context,
            )
            if signal is not None:
                output.append(signal)
                used.add(key)
    return output


def _donchian_breakout(
    current: Bar,
    *,
    history: Sequence[Bar],
    atr: float,
) -> tuple[str, str, float, int] | None:
    high = max(bar.high for bar in history)
    low = min(bar.low for bar in history)
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
        min_body_atr=0.18,
        min_body_ratio=0.55,
        min_close_location=0.65,
    ):
        return None
    recent = history[-6:] + [current]
    stop = (
        min(bar.low for bar in recent) - 0.10 * atr
        if side == "LONG"
        else max(bar.high for bar in recent) + 0.10 * atr
    )
    return "DONCHIAN_BREAKOUT", side, stop, 360


def _failed_donchian(
    current: Bar,
    *,
    history: Sequence[Bar],
    atr: float,
) -> tuple[str, str, float, int] | None:
    high = max(bar.high for bar in history)
    low = min(bar.low for bar in history)
    if current.high >= high + 0.10 * atr and current.close <= high - 0.05 * atr:
        side, stop = "SHORT", current.high + 0.10 * atr
    elif current.low <= low - 0.10 * atr and current.close >= low + 0.05 * atr:
        side, stop = "LONG", current.low - 0.10 * atr
    else:
        return None
    if not _directional_bar(
        current,
        side=side,
        atr=atr,
        min_body_atr=0.12,
        min_body_ratio=0.50,
        min_close_location=0.60,
    ):
        return None
    return "FAILED_DONCHIAN", side, stop, 180


def _compression_break(
    current: Bar,
    *,
    history: Sequence[Bar],
    atr: float,
) -> tuple[str, str, float, int] | None:
    high = max(bar.high for bar in history)
    low = min(bar.low for bar in history)
    if (high - low) / atr > 2.50:
        return None
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
        return None
    stop = low - 0.10 * atr if side == "LONG" else high + 0.10 * atr
    return "COMPRESSION_BREAK", side, stop, 240


def _extension_rejection(
    current: Bar,
    *,
    history: Sequence[Bar],
    atr: float,
) -> tuple[str, str, float, int] | None:
    mean = statistics.mean(bar.close for bar in history)
    if current.high >= mean + 2.0 * atr and current.close <= mean + 1.50 * atr:
        side, stop = "SHORT", current.high + 0.10 * atr
    elif current.low <= mean - 2.0 * atr and current.close >= mean - 1.50 * atr:
        side, stop = "LONG", current.low - 0.10 * atr
    else:
        return None
    if not _directional_bar(
        current,
        side=side,
        atr=atr,
        min_body_atr=0.15,
        min_body_ratio=0.50,
        min_close_location=0.60,
    ):
        return None
    return "EXTENSION_REJECTION", side, stop, 120


def _make_signal(
    instrument: str,
    *,
    session_name: str,
    family: str,
    session_date: date,
    side: str,
    signal_bar: Bar,
    entry_bar: Bar,
    structural_stop: float,
    atr: float,
    session_end: datetime,
    max_minutes: int,
    context: dict[str, float],
) -> Signal | None:
    if entry_bar.open_time != signal_bar.close_time:
        return None
    structural_risk = abs(entry_bar.open - structural_stop)
    if structural_risk <= 0:
        return None
    cost = COSTS[instrument]
    estimated_cost_price = (
        entry_bar.spread + 2 * cost.slippage_per_side + cost.round_turn_commission_price
    )
    risk = max(
        structural_risk,
        0.75 * atr,
        estimated_cost_price / 0.15,
    )
    risk_atr = risk / atr
    if risk_atr > 2.50:
        return None
    direction = 1.0 if side == "LONG" else -1.0
    stop = entry_bar.open - direction * risk
    holding = min(
        max_minutes,
        int((session_end - entry_bar.open_time).total_seconds() // 60),
    )
    holding -= holding % 5
    if holding < 15:
        return None
    return Signal(
        playbook=f"{instrument}|{session_name}|{family}",
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
            "session": session_name,
            "entry_resolution": "5m",
            "risk_atr": risk_atr,
            "original_structural_risk_atr": structural_risk / atr,
            "estimated_cost_r": estimated_cost_price / risk,
            "signed_trend_60_atr": direction * context["unsigned_trend_60_atr"],
            "signed_trend_240_atr": direction * context["unsigned_trend_240_atr"],
            **context,
        },
    )


def _rules() -> tuple[ContextRule, ...]:
    return (
        ContextRule("BASE", lambda signal: True),
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
            "VOLATILITY_EXPANSION",
            lambda signal: _evidence(signal, "volatility_ratio") >= 1.10,
        ),
        ContextRule(
            "VOLATILITY_CONTRACTION",
            lambda signal: _evidence(signal, "volatility_ratio") <= 0.90,
        ),
        ContextRule(
            "RELATIVE_VOLUME_1_20X",
            lambda signal: _evidence(signal, "relative_volume") >= 1.20,
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


def _context(
    current: Bar,
    *,
    history_12: Sequence[Bar],
    history_72: Sequence[Bar],
    atr: float,
    slow_atr: float,
) -> dict[str, float]:
    side_long_return_60 = (current.close - history_12[0].open) / atr
    side_long_return_240 = (current.close - history_72[-48].open) / atr
    baseline_volume = statistics.median(bar.volume for bar in history_12)
    return {
        "unsigned_trend_60_atr": side_long_return_60,
        "unsigned_trend_240_atr": side_long_return_240,
        "volatility_ratio": atr / slow_atr,
        "relative_volume": (current.volume / baseline_volume if baseline_volume > 0 else math.nan),
    }


def _evidence(signal: Signal, key: str) -> float:
    value = signal.evidence.get(key)
    return float(value) if value is not None else math.nan


def _history(
    bars_by_open: dict[datetime, Bar],
    *,
    end: datetime,
    bars: int,
) -> list[Bar] | None:
    timestamps = [end - timedelta(minutes=5 * (bars - index)) for index in range(bars)]
    path = [bars_by_open.get(timestamp) for timestamp in timestamps]
    if any(bar is None for bar in path):
        return None
    return [bar for bar in path if bar is not None]


def _liquid_session(
    instrument: str,
    timestamp: datetime,
) -> tuple[str, date, datetime] | None:
    if instrument in {"US500", "USTEC"}:
        local = timestamp.astimezone(NEW_YORK)
        if not clock_time(9, 30) <= local.time() < clock_time(16, 0):
            return None
        end = datetime.combine(
            local.date(),
            clock_time(16, 0),
            tzinfo=NEW_YORK,
        ).astimezone(UTC)
        return "NEW_YORK_LIQUID", local.date(), end
    if instrument == "DE40":
        local = timestamp.astimezone(BERLIN)
        if not clock_time(9, 0) <= local.time() < clock_time(17, 30):
            return None
        end = datetime.combine(
            local.date(),
            clock_time(17, 30),
            tzinfo=BERLIN,
        ).astimezone(UTC)
        return "EUROPE_CASH", local.date(), end
    if instrument == "XTIUSD":
        local = timestamp.astimezone(NEW_YORK)
        if not clock_time(8, 0) <= local.time() < clock_time(14, 30):
            return None
        end = datetime.combine(
            local.date(),
            clock_time(14, 30),
            tzinfo=NEW_YORK,
        ).astimezone(UTC)
        return "NEW_YORK_ENERGY", local.date(), end
    local = timestamp.astimezone(LONDON)
    if not clock_time(8, 0) <= local.time() < clock_time(16, 0):
        return None
    end = datetime.combine(
        local.date(),
        clock_time(16, 0),
        tzinfo=LONDON,
    ).astimezone(UTC)
    return "LONDON_NEW_YORK", local.date(), end


def _phase(name: str, started: float) -> None:
    print(
        f"{name} elapsed={time.perf_counter() - started:.3f}s",
        flush=True,
        file=__import__("sys").stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
