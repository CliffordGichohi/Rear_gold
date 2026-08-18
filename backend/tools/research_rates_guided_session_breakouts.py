from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from explore_session_playbooks import Bar, Day, _build_days
from research_cross_market_auction_micro_execution import (
    _bars,
    _five_minute_bars_from_minutes,
)
from research_daily_session_playbooks import (
    Signal,
    _atr_by_close,
    _directional_bar,
)
from research_fundamental_state_transitions import _fundamental_records
from research_one_minute_auction_execution import ONE_MINUTE_SQL
from research_rates_policy_session_edge import (
    ExecutionContext,
    Permission,
    _accepted_portfolio_trades,
    _annual_gate,
    _candidate_report,
    _contexts,
    _feature_coverage,
    _managed_results,
    _portfolio_report,
    _rank,
    _rates_panel,
    _select,
    _side_diagnostics,
    _target_gate,
    _treasury_both,
    _write_context_cache,
)
from research_session_state_transitions import Candidate

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory

Predicate = Callable[[ExecutionContext], bool]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rates-dir", type=Path, required=True)
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--cache-output", type=Path)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    started = time.perf_counter()
    gold_query = {
        "load_start": start - timedelta(days=8),
        "load_end": end,
    }
    async with session_factory() as session:
        minute_bars = _bars(
            (await session.execute(ONE_MINUTE_SQL, gold_query)).mappings(),
        )
        five_minute_gold = _five_minute_bars_from_minutes(minute_bars)
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)
    _phase("SOURCE_DATA_LOADED", started)

    days = _build_days(five_minute_gold, start=start, end=end)
    signals = _session_signals(days, five_minute_gold=five_minute_gold)
    managed = _managed_results(signals, minute_bars=minute_bars)
    fundamentals = _fundamental_records(
        managed,
        fundamental_inputs=fundamental_inputs,
    )
    _phase("SESSION_EXECUTIONS_BUILT", started)

    panel, rates_contract = _rates_panel(
        args.rates_dir,
        load_start=start - timedelta(days=32),
        end=end,
        target_times=sorted(
            {item.managed.signal.signal_time for item in fundamentals},
        ),
    )
    contexts = _contexts(fundamentals, panel=panel)
    if args.cache_output is not None:
        _write_context_cache(contexts, args.cache_output)
    candidates, candidate_trades = _candidate_results(contexts)
    selected = _select(candidates, candidate_trades=candidate_trades)
    _phase("CANDIDATES_BUILT", started)

    base_portfolio = _portfolio_report(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    stress_portfolio = _portfolio_report(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.5,
    )
    report = {
        "contract": {
            "version": "RATES_GUIDED_SESSION_BREAKOUTS_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "hypothesis": (
                "Gold frequently auctions beyond the completed Asian range in "
                "London and beyond the completed London range in New York. A "
                "completed directional five-minute close defines acceptance; a "
                "recent sweep followed by a directional close back through the "
                "level defines rejection. Intraday Treasury pricing supplies "
                "directional permission."
            ),
            "entry": (
                "The signal uses only a completed five-minute bar. Entry is the "
                "next five-minute open, simulated on one-minute gold bars."
            ),
            "invalidation": (
                "Acceptance stop is 0.15 five-minute ATR back through the broken "
                "range boundary. Rejection stop is 0.10 ATR beyond the observed "
                "three-bar sweep extreme."
            ),
            "search_space": (
                "Four level/session playbooks, ten predeclared permissions, and four fixed-R exits."
            ),
            "selection": (
                "Discovery 2021-08 through 2022 only; one permission/manager per "
                "playbook. The same candidate is then frozen for 2023 and 2024."
            ),
            "costs": (
                "Observed IC Markets spread, $0.05/oz slippage per side, and "
                "$7/lot round-turn commission; identical signals at 1.50x cost."
            ),
            "target": (
                "10R average per calendar month at 1% risk is a required hurdle, "
                "not an assumed or guaranteed result."
            ),
        },
        "source_counts": {
            "complete_sessions": len(days),
            "signals": len(signals),
            "managed_executions": len(managed),
            "contexts": len(contexts),
            "candidate_hypotheses": len(candidates),
        },
        "signal_funnel": _signal_funnel(signals),
        "rates_data": rates_contract,
        "rates_feature_coverage_pct": _feature_coverage(contexts),
        "selected_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in selected
        ],
        "portfolio": {
            "base_cost": base_portfolio,
            "cost_stress_1_50x": stress_portfolio,
            "positive_each_development_year": _annual_gate(
                selected,
                candidate_trades=candidate_trades,
            ),
            "ten_r_monthly_promotion_gate": _target_gate(
                base_portfolio,
                stress_portfolio,
            ),
        },
        "top_discovery_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in sorted(
                candidates,
                key=lambda item: _rank(
                    item,
                    candidate_trades=candidate_trades,
                ),
                reverse=True,
            )[: args.top]
        ],
        "side_diagnostics": _side_diagnostics(
            selected,
            candidate_trades=candidate_trades,
        ),
        "selected_portfolio_trades": _portfolio_trade_summary(
            selected,
            candidate_trades=candidate_trades,
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _session_signals(
    days: Sequence[Day],
    *,
    five_minute_gold: Sequence[Bar],
) -> list[Signal]:
    atr_by_close = _atr_by_close(five_minute_gold)
    asia_range_history: list[float] = []
    london_range_history: list[float] = []
    output: list[Signal] = []
    for day in days:
        asia_high = max(bar.high for bar in day.asia)
        asia_low = min(bar.low for bar in day.asia)
        asia_range = asia_high - asia_low
        asia_percentile = _percentile(asia_range, asia_range_history)
        london_high = max(bar.high for bar in day.london)
        london_low = min(bar.low for bar in day.london)
        london_range = london_high - london_low
        london_percentile = _percentile(
            london_range,
            london_range_history,
        )
        common = {
            "asia_high": asia_high,
            "asia_low": asia_low,
            "asia_range": asia_range,
            "asia_range_percentile": asia_percentile,
        }
        london_acceptance = _first_acceptance(
            day,
            session_name="LONDON",
            bars=day.london,
            high_level=asia_high,
            low_level=asia_low,
            atr_by_close=atr_by_close,
            evidence=common,
            exit_time=day.new_york[-1].close_time,
        )
        london_rejection = _first_rejection(
            day,
            session_name="LONDON",
            bars=day.london,
            high_level=asia_high,
            low_level=asia_low,
            atr_by_close=atr_by_close,
            evidence=common,
            exit_time=day.new_york[-1].close_time,
        )
        ny_context = {
            **common,
            "london_high": london_high,
            "london_low": london_low,
            "london_range": london_range,
            "london_range_percentile": london_percentile,
        }
        ny_acceptance = _first_acceptance(
            day,
            session_name="NEW_YORK",
            bars=day.new_york,
            high_level=london_high,
            low_level=london_low,
            atr_by_close=atr_by_close,
            evidence=ny_context,
            exit_time=day.new_york[-1].close_time,
        )
        ny_rejection = _first_rejection(
            day,
            session_name="NEW_YORK",
            bars=day.new_york,
            high_level=london_high,
            low_level=london_low,
            atr_by_close=atr_by_close,
            evidence=ny_context,
            exit_time=day.new_york[-1].close_time,
        )
        output.extend(
            signal
            for signal in (
                london_acceptance,
                london_rejection,
                ny_acceptance,
                ny_rejection,
            )
            if signal is not None
        )
        asia_range_history.append(asia_range)
        london_range_history.append(london_range)
    return sorted(output, key=lambda item: (item.entry_time, item.playbook))


def _first_acceptance(
    day: Day,
    *,
    session_name: str,
    bars: Sequence[Bar],
    high_level: float,
    low_level: float,
    atr_by_close: dict[datetime, float],
    evidence: dict[str, Any],
    exit_time: datetime,
) -> Signal | None:
    for index in range(1, min(len(bars) - 1, 36)):
        prior = bars[index - 1]
        current = bars[index]
        atr = atr_by_close.get(current.close_time)
        if atr is None or atr <= 0:
            continue
        side: str | None = None
        boundary = 0.0
        if prior.close <= high_level and current.close >= high_level + 0.05 * atr:
            side = "LONG"
            boundary = high_level
        elif prior.close >= low_level and current.close <= low_level - 0.05 * atr:
            side = "SHORT"
            boundary = low_level
        if side is None or not _directional_bar(
            current,
            side=side,
            atr=atr,
            min_body_atr=0.15,
            min_body_ratio=0.50,
            min_close_location=0.60,
        ):
            continue
        stop = boundary - 0.15 * atr if side == "LONG" else boundary + 0.15 * atr
        signal = _signal(
            day,
            playbook=f"{session_name}|RANGE_ACCEPTANCE",
            side=side,
            signal_bar=current,
            entry_bar=bars[index + 1],
            stop=stop,
            atr=atr,
            exit_time=exit_time,
            evidence={
                **evidence,
                "session": session_name,
                "level": boundary,
                "level_type": ("ASIA_RANGE" if session_name == "LONDON" else "LONDON_RANGE"),
                "detection": "FIRST_DIRECTIONAL_CLOSE_OUTSIDE",
            },
        )
        if signal is not None:
            return signal
    return None


def _first_rejection(
    day: Day,
    *,
    session_name: str,
    bars: Sequence[Bar],
    high_level: float,
    low_level: float,
    atr_by_close: dict[datetime, float],
    evidence: dict[str, Any],
    exit_time: datetime,
) -> Signal | None:
    for index in range(2, min(len(bars) - 1, 36)):
        current = bars[index]
        atr = atr_by_close.get(current.close_time)
        if atr is None or atr <= 0:
            continue
        recent = bars[index - 2 : index + 1]
        recent_high = max(bar.high for bar in recent)
        recent_low = min(bar.low for bar in recent)
        side: str | None = None
        boundary = 0.0
        sweep_extreme = 0.0
        if recent_high >= high_level + 0.10 * atr and current.close <= high_level - 0.05 * atr:
            side = "SHORT"
            boundary = high_level
            sweep_extreme = recent_high
        elif recent_low <= low_level - 0.10 * atr and current.close >= low_level + 0.05 * atr:
            side = "LONG"
            boundary = low_level
            sweep_extreme = recent_low
        if side is None or not _directional_bar(
            current,
            side=side,
            atr=atr,
            min_body_atr=0.15,
            min_body_ratio=0.50,
            min_close_location=0.60,
        ):
            continue
        stop = sweep_extreme - 0.10 * atr if side == "LONG" else sweep_extreme + 0.10 * atr
        signal = _signal(
            day,
            playbook=f"{session_name}|RANGE_REJECTION",
            side=side,
            signal_bar=current,
            entry_bar=bars[index + 1],
            stop=stop,
            atr=atr,
            exit_time=exit_time,
            evidence={
                **evidence,
                "session": session_name,
                "level": boundary,
                "level_type": ("ASIA_RANGE" if session_name == "LONDON" else "LONDON_RANGE"),
                "sweep_extreme": sweep_extreme,
                "detection": "THREE_BAR_SWEEP_AND_DIRECTIONAL_CLOSE_BACK_INSIDE",
            },
        )
        if signal is not None:
            return signal
    return None


def _signal(
    day: Day,
    *,
    playbook: str,
    side: str,
    signal_bar: Bar,
    entry_bar: Bar,
    stop: float,
    atr: float,
    exit_time: datetime,
    evidence: dict[str, Any],
) -> Signal | None:
    if entry_bar.open_time != signal_bar.close_time:
        return None
    if (side == "LONG" and stop >= entry_bar.open) or (side == "SHORT" and stop <= entry_bar.open):
        return None
    risk_atr = abs(entry_bar.open - stop) / atr
    if not 0.20 <= risk_atr <= 2.50:
        return None
    holding = int((exit_time - entry_bar.open_time).total_seconds() // 60)
    if holding < 10:
        return None
    return Signal(
        playbook=playbook,
        session_date=day.session_date,
        side=side,
        signal_time=signal_bar.close_time,
        entry_time=entry_bar.open_time,
        entry_reference=entry_bar.open,
        stop=stop,
        base_target_r=2.0,
        max_holding_minutes=holding,
        atr=atr,
        evidence={
            **evidence,
            "risk_atr": risk_atr,
        },
    )


def _permissions() -> tuple[Permission, ...]:
    return (
        Permission("BASE", lambda item: True),
        Permission(
            "TREASURY_5_BOTH",
            lambda item: _treasury_both(item, 5, minimum=0.0),
        ),
        Permission(
            "TREASURY_15_BOTH",
            lambda item: _treasury_both(item, 15, minimum=0.0),
        ),
        Permission(
            "TREASURY_15_STRONG",
            lambda item: _treasury_both(item, 15, minimum=0.50),
        ),
        Permission(
            "TREASURY_15_60",
            lambda item: (
                _treasury_both(item, 15, minimum=0.0) and _treasury_both(item, 60, minimum=0.0)
            ),
        ),
        Permission(
            "MACRO_AND_TREASURY_15",
            lambda item: (
                item.fundamental.signed_score >= -5 and _treasury_both(item, 15, minimum=0.0)
            ),
        ),
        Permission(
            "COMPRESSED_AND_TREASURY_15",
            lambda item: (
                _evidence(item, "asia_range_percentile") <= 50
                and _treasury_both(item, 15, minimum=0.0)
            ),
        ),
        Permission(
            "EXPANDED_AND_TREASURY_15",
            lambda item: (
                _evidence(item, "asia_range_percentile") > 50
                and _treasury_both(item, 15, minimum=0.0)
            ),
        ),
        Permission(
            "EVENT_CLEAR_TREASURY_15",
            lambda item: (
                (
                    item.fundamental.minutes_to_catalyst is None
                    or item.fundamental.minutes_to_catalyst > 30
                )
                and _treasury_both(item, 15, minimum=0.0)
            ),
        ),
        Permission(
            "POST_EVENT_TREASURY_15",
            lambda item: (
                item.fundamental.event_age_hours is not None
                and 0 <= item.fundamental.event_age_hours <= 2
                and _treasury_both(item, 15, minimum=0.0)
            ),
        ),
    )


def _candidate_results(
    contexts: Sequence[ExecutionContext],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Any]]]:
    permissions = _permissions()
    playbooks = sorted(
        {item.fundamental.managed.signal.playbook for item in contexts},
    )
    managers = sorted(
        {item.fundamental.managed.manager for item in contexts},
    )
    candidates = [
        Candidate(playbook, permission.name, manager)
        for playbook in playbooks
        for permission in permissions
        for manager in managers
    ]
    permission_by_name = {item.name: item for item in permissions}
    output: dict[tuple[str, float], list[Any]] = {}
    for candidate in candidates:
        permission = permission_by_name[candidate.rule]
        for cost_multiplier in (1.0, 1.5):
            output[(candidate.key, cost_multiplier)] = [
                item.trade
                for item in contexts
                if item.fundamental.managed.signal.playbook == candidate.archetype
                and item.fundamental.managed.manager == candidate.manager
                and item.fundamental.managed.cost_multiplier == cost_multiplier
                and permission.predicate(item)
            ]
    return candidates, output


def _evidence(item: ExecutionContext, key: str) -> float:
    value = item.fundamental.managed.signal.evidence.get(key)
    return float(value) if value is not None else math.nan


def _percentile(value: float, history: Sequence[float]) -> float:
    if not history:
        return 50.0
    return sum(member <= value for member in history) / len(history) * 100


def _signal_funnel(signals: Sequence[Signal]) -> dict[str, int]:
    return {
        playbook: sum(signal.playbook == playbook for signal in signals)
        for playbook in sorted({signal.playbook for signal in signals})
    }


def _portfolio_trade_summary(
    selected: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> dict[str, Any]:
    accepted = _accepted_portfolio_trades(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    return {
        "first": accepted[0].entry_time.isoformat() if accepted else None,
        "last": accepted[-1].entry_time.isoformat() if accepted else None,
        "by_playbook": {
            playbook: sum(item.playbook == playbook for item in accepted)
            for playbook in sorted({item.playbook for item in accepted})
        },
    }


def _phase(name: str, started: float) -> None:
    print(
        f"{name} elapsed={time.perf_counter() - started:.3f}s",
        flush=True,
        file=__import__("sys").stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
