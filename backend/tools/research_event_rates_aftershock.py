from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from bisect import bisect_right
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from explore_session_playbooks import Bar
from research_cross_market_auction_micro_execution import (
    _bars,
    _five_minute_bars_from_minutes,
)
from research_daily_session_playbooks import Signal, _atr_by_close
from research_fundamental_state_transitions import _fundamental_records
from research_one_minute_auction_execution import ONE_MINUTE_SQL
from research_rates_guided_session_breakouts import _portfolio_trade_summary
from research_rates_policy_session_edge import (
    ExecutionContext,
    Permission,
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
    _write_context_cache,
)
from research_session_state_transitions import Candidate

from gold_intel.analytics.fundamentals import (
    EventSurprisePoint,
    FundamentalEventPoint,
)
from gold_intel.application.fundamentals import (
    FundamentalInputs,
    load_fundamental_inputs,
)
from gold_intel.infrastructure.database import session_factory

DECISION_HORIZONS = (5, 15, 30)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rates-dir", type=Path, required=True)
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--cache-output", type=Path)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    started = time.perf_counter()
    query = {
        "load_start": start - timedelta(days=8),
        "load_end": end,
    }
    async with session_factory() as session:
        minute_bars = _bars(
            (await session.execute(ONE_MINUTE_SQL, query)).mappings(),
        )
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)
    five_minute_gold = _five_minute_bars_from_minutes(minute_bars)
    events = _events(fundamental_inputs, start=start, end=end)
    decision_times = sorted(
        {
            event.scheduled_at + timedelta(minutes=horizon)
            for event in events
            for horizon in DECISION_HORIZONS
            if event.scheduled_at + timedelta(minutes=horizon) < end
        },
    )
    panel, rates_contract = _rates_panel(
        args.rates_dir,
        load_start=start - timedelta(days=32),
        end=end,
        target_times=decision_times,
    )
    _phase("SOURCE_DATA_LOADED", started)

    signals = _event_signals(
        events,
        surprises=fundamental_inputs.event_surprises,
        minute_bars=minute_bars,
        five_minute_gold=five_minute_gold,
        rates_panel=panel,
    )
    managed = _managed_results(signals, minute_bars=minute_bars)
    fundamentals = _fundamental_records(
        managed,
        fundamental_inputs=fundamental_inputs,
    )
    contexts = _contexts(fundamentals, panel=panel)
    if args.cache_output is not None:
        _write_context_cache(contexts, args.cache_output)
    candidates, candidate_trades = _candidate_results(contexts)
    selected = _select(candidates, candidate_trades=candidate_trades)
    _phase("EVENT_EXECUTIONS_AND_CANDIDATES_BUILT", started)

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
            "version": "EVENT_RATES_AFTERSHOCK_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "causal_chain": (
                "Observed scheduled release -> completed 5/15/30-minute ZT and "
                "ZN repricing -> gold acceptance in that direction, or a 15-minute "
                "reclaim after an opposing first move -> next-minute entry."
            ),
            "event_scope": (
                "Released real US CPI, PCE, Employment Situation, initial claims, "
                "GDP, retail sales, and FOMC rate-decision events with importance "
                "at least medium."
            ),
            "rates_direction": (
                "Both Treasury futures must move in the same direction with a "
                "median absolute standardized move of at least 0.25. Higher "
                "Treasury futures prices imply lower yields and a long-gold bias."
            ),
            "price_confirmation": (
                "Acceptance requires gold to move at least 0.25 pre-event ATR in "
                "the rates-implied direction. Reclaim requires a >=0.20 ATR first "
                "move against rates and a later close >=0.10 ATR through the "
                "pre-event price in the rates direction."
            ),
            "selection": (
                "Discovery 2021-08 through 2022 only; 2023 validation and 2024 "
                "forward-development are not used to choose a candidate."
            ),
            "costs": (
                "Observed IC Markets spread, $0.05/oz slippage per side, and "
                "$7/lot round-turn commission; also 1.50x stress."
            ),
            "target": (
                "10R average per month at 1% risk is a hard promotion hurdle, "
                "not a promised result."
            ),
        },
        "source_counts": {
            "events": len(events),
            "signals": len(signals),
            "managed_executions": len(managed),
            "contexts": len(contexts),
            "candidate_hypotheses": len(candidates),
        },
        "event_funnel": _event_funnel(events),
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


def _events(
    inputs: FundamentalInputs,
    *,
    start: datetime,
    end: datetime,
) -> list[FundamentalEventPoint]:
    allowed = {
        "US_CPI",
        "US_PCE",
        "US_EMPLOYMENT_SITUATION",
        "US_INITIAL_JOBLESS_CLAIMS",
        "US_GDP",
        "US_RETAIL_SALES",
        "US_FOMC_RATE_DECISION",
    }
    return sorted(
        [
            event
            for event in inputs.events
            if event.event_code in allowed
            and event.status == "RELEASED"
            and event.importance >= 2
            and start <= event.scheduled_at < end
            and event.available_at <= event.scheduled_at
        ],
        key=lambda item: item.scheduled_at,
    )


def _event_signals(
    events: Sequence[FundamentalEventPoint],
    *,
    surprises: Sequence[EventSurprisePoint],
    minute_bars: Sequence[Bar],
    five_minute_gold: Sequence[Bar],
    rates_panel: pd.DataFrame,
) -> list[Signal]:
    bars_by_open = {bar.open_time: bar for bar in minute_bars}
    atr_by_close = _atr_by_close(five_minute_gold)
    atr_times = sorted(atr_by_close)
    surprise_by_event = _surprise_by_event(surprises)
    output: list[Signal] = []
    for event in events:
        pre_bar = bars_by_open.get(event.scheduled_at - timedelta(minutes=1))
        if pre_bar is None:
            continue
        atr = _latest_atr(
            atr_by_close,
            atr_times=atr_times,
            as_of=event.scheduled_at,
        )
        if atr is None or atr <= 0:
            continue
        first_five = _path(
            bars_by_open,
            event.scheduled_at,
            minutes=5,
        )
        if first_five is None:
            continue
        surprise = surprise_by_event.get(event.event_id)
        for horizon in DECISION_HORIZONS:
            decision = event.scheduled_at + timedelta(minutes=horizon)
            path = _path(
                bars_by_open,
                event.scheduled_at,
                minutes=horizon,
            )
            if path is None or decision not in rates_panel.index:
                continue
            rates_side, rates_strength = _rates_side(
                rates_panel.loc[pd.Timestamp(decision)],
                horizon=horizon,
            )
            if rates_side is None:
                continue
            acceptance = _acceptance_signal(
                event,
                pre_bar=pre_bar,
                path=path,
                next_bar=bars_by_open.get(decision),
                side=rates_side,
                rates_strength=rates_strength,
                atr=atr,
                horizon=horizon,
                surprise=surprise,
            )
            if acceptance is not None:
                output.append(acceptance)
            if horizon == 15:
                reclaim = _reclaim_signal(
                    event,
                    pre_bar=pre_bar,
                    first_five=first_five,
                    path=path,
                    next_bar=bars_by_open.get(decision),
                    side=rates_side,
                    rates_strength=rates_strength,
                    atr=atr,
                    surprise=surprise,
                )
                if reclaim is not None:
                    output.append(reclaim)
    return sorted(output, key=lambda item: (item.entry_time, item.playbook))


def _rates_side(
    row: pd.Series,
    *,
    horizon: int,
) -> tuple[str | None, float]:
    zt = float(row[f"ZT.v.0|z{horizon}"])
    zn = float(row[f"ZN.v.0|z{horizon}"])
    if not math.isfinite(zt) or not math.isfinite(zn):
        return None, math.nan
    median = statistics.median((zt, zn))
    if zt > 0 and zn > 0 and median >= 0.25:
        return "LONG", median
    if zt < 0 and zn < 0 and median <= -0.25:
        return "SHORT", abs(median)
    return None, abs(median)


def _acceptance_signal(
    event: FundamentalEventPoint,
    *,
    pre_bar: Bar,
    path: Sequence[Bar],
    next_bar: Bar | None,
    side: str,
    rates_strength: float,
    atr: float,
    horizon: int,
    surprise: dict[str, float] | None,
) -> Signal | None:
    if next_bar is None:
        return None
    direction = 1 if side == "LONG" else -1
    signed_move = direction * (path[-1].close - pre_bar.close) / atr
    signed_last_five = direction * (path[-1].close - path[max(0, len(path) - 5)].open) / atr
    if signed_move < 0.25 or signed_last_five <= 0:
        return None
    stop = pre_bar.close - direction * 0.15 * atr
    return _signal(
        event,
        playbook=f"EVENT_{horizon}M_ACCEPTANCE",
        side=side,
        signal_time=path[-1].close_time,
        entry_bar=next_bar,
        stop=stop,
        atr=atr,
        evidence=_event_evidence(
            event,
            side=side,
            rates_strength=rates_strength,
            signed_gold_move_atr=signed_move,
            surprise=surprise,
        ),
    )


def _reclaim_signal(
    event: FundamentalEventPoint,
    *,
    pre_bar: Bar,
    first_five: Sequence[Bar],
    path: Sequence[Bar],
    next_bar: Bar | None,
    side: str,
    rates_strength: float,
    atr: float,
    surprise: dict[str, float] | None,
) -> Signal | None:
    if next_bar is None:
        return None
    direction = 1 if side == "LONG" else -1
    first_move = direction * (first_five[-1].close - pre_bar.close) / atr
    final_move = direction * (path[-1].close - pre_bar.close) / atr
    last_five = direction * (path[-1].close - path[-5].open) / atr
    if first_move > -0.20 or final_move < 0.10 or last_five <= 0:
        return None
    opposing_extreme = (
        min(bar.low for bar in first_five)
        if side == "LONG"
        else max(bar.high for bar in first_five)
    )
    stop = opposing_extreme - 0.10 * atr if side == "LONG" else opposing_extreme + 0.10 * atr
    return _signal(
        event,
        playbook="EVENT_15M_RECLAIM",
        side=side,
        signal_time=path[-1].close_time,
        entry_bar=next_bar,
        stop=stop,
        atr=atr,
        evidence=_event_evidence(
            event,
            side=side,
            rates_strength=rates_strength,
            signed_gold_move_atr=final_move,
            surprise=surprise,
        ),
    )


def _signal(
    event: FundamentalEventPoint,
    *,
    playbook: str,
    side: str,
    signal_time: datetime,
    entry_bar: Bar,
    stop: float,
    atr: float,
    evidence: dict[str, Any],
) -> Signal | None:
    if entry_bar.open_time != signal_time:
        return None
    if (side == "LONG" and stop >= entry_bar.open) or (side == "SHORT" and stop <= entry_bar.open):
        return None
    risk_atr = abs(entry_bar.open - stop) / atr
    if not 0.20 <= risk_atr <= 3.0:
        return None
    return Signal(
        playbook=playbook,
        session_date=event.scheduled_at.date(),
        side=side,
        signal_time=signal_time,
        entry_time=entry_bar.open_time,
        entry_reference=entry_bar.open,
        stop=stop,
        base_target_r=2.0,
        max_holding_minutes=180,
        atr=atr,
        evidence={**evidence, "risk_atr": risk_atr},
    )


def _event_evidence(
    event: FundamentalEventPoint,
    *,
    side: str,
    rates_strength: float,
    signed_gold_move_atr: float,
    surprise: dict[str, float] | None,
) -> dict[str, Any]:
    surprise_direction = surprise.get("direction") if surprise else None
    side_sign = 1.0 if side == "LONG" else -1.0
    return {
        "event_id": event.event_id,
        "event_code": event.event_code,
        "event_name": event.event_name,
        "event_importance": event.importance,
        "scheduled_at": event.scheduled_at.isoformat(),
        "rates_strength": rates_strength,
        "signed_gold_move_atr": signed_gold_move_atr,
        "surprise_direction": surprise_direction,
        "surprise_strength": surprise.get("strength") if surprise else None,
        "surprise_aligned": (
            surprise_direction is not None and side_sign * float(surprise_direction) > 0
        ),
    }


def _surprise_by_event(
    surprises: Sequence[EventSurprisePoint],
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[EventSurprisePoint]] = {}
    for surprise in surprises:
        grouped.setdefault(surprise.event_id, []).append(surprise)
    output: dict[str, dict[str, float]] = {}
    for event_id, members in grouped.items():
        weights = [max(0.01, member.strength * member.confidence / 100) for member in members]
        denominator = sum(weights)
        output[event_id] = {
            "direction": sum(
                member.gold_direction * weight
                for member, weight in zip(members, weights, strict=True)
            )
            / denominator,
            "strength": statistics.mean(member.strength for member in members),
        }
    return output


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


def _permissions() -> tuple[Permission, ...]:
    return (
        Permission("BASE", lambda item: True),
        Permission(
            "HIGH_IMPORTANCE",
            lambda item: _evidence(item, "event_importance") >= 3,
        ),
        Permission(
            "SURPRISE_ALIGNED",
            lambda item: bool(
                item.fundamental.managed.signal.evidence.get(
                    "surprise_aligned",
                ),
            ),
        ),
        Permission(
            "MACRO_NOT_OPPOSED",
            lambda item: item.fundamental.signed_score >= -5,
        ),
        Permission(
            "SURPRISE_AND_MACRO",
            lambda item: (
                bool(
                    item.fundamental.managed.signal.evidence.get(
                        "surprise_aligned",
                    ),
                )
                and item.fundamental.signed_score >= -5
            ),
        ),
        Permission(
            "RATES_STRENGTH_0_75",
            lambda item: _evidence(item, "rates_strength") >= 0.75,
        ),
    )


def _path(
    bars_by_open: dict[datetime, Bar],
    start: datetime,
    *,
    minutes: int,
) -> list[Bar] | None:
    path = [bars_by_open.get(start + timedelta(minutes=offset)) for offset in range(minutes)]
    return None if any(bar is None for bar in path) else [bar for bar in path if bar is not None]


def _latest_atr(
    atr_by_close: dict[datetime, float],
    *,
    atr_times: Sequence[datetime],
    as_of: datetime,
) -> float | None:
    index = bisect_right(atr_times, as_of) - 1
    return atr_by_close[atr_times[index]] if index >= 0 else None


def _evidence(item: ExecutionContext, key: str) -> float:
    value = item.fundamental.managed.signal.evidence.get(key)
    return float(value) if value is not None else math.nan


def _event_funnel(
    events: Sequence[FundamentalEventPoint],
) -> dict[str, int]:
    return {
        code: sum(event.event_code == code for event in events)
        for code in sorted({event.event_code for event in events})
    }


def _signal_funnel(signals: Sequence[Signal]) -> dict[str, int]:
    return {
        playbook: sum(signal.playbook == playbook for signal in signals)
        for playbook in sorted({signal.playbook for signal in signals})
    }


def _phase(name: str, started: float) -> None:
    print(
        f"{name} elapsed={time.perf_counter() - started:.3f}s",
        flush=True,
        file=__import__("sys").stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
