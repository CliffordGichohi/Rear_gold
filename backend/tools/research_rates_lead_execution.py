from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from explore_session_playbooks import Bar
from research_cross_market_auction_micro_execution import (
    _bars,
    _five_minute_bars_from_minutes,
)
from research_daily_session_playbooks import Signal, _atr_by_close
from research_fundamental_state_transitions import _fundamental_records
from research_one_minute_auction_execution import ONE_MINUTE_SQL
from research_rates_gold_lead_lag import _session
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

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rates-dir", type=Path, required=True)
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=48)
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
    decision_times = [
        bar.close_time
        for bar in five_minute_gold
        if start <= bar.close_time < end and _session(bar.close_time) is not None
    ]
    panel, rates_contract = _rates_panel(
        args.rates_dir,
        load_start=start - timedelta(days=32),
        end=end,
        target_times=decision_times,
    )
    _phase("SOURCE_DATA_LOADED", started)

    signals = _signals(
        five_minute_gold,
        panel=panel,
        start=start,
        end=end,
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
    _phase("EXECUTIONS_AND_CANDIDATES_BUILT", started)

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
            "version": "RATES_LEAD_EXECUTION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "entry": (
                "After a completed five-minute ZT/ZN shock of at least 1.0 "
                "standardized units, classify gold as ACCEPTED when its completed "
                "five-minute bar moved >=0.25 ATR in the same direction, or "
                "LAGGING when it moved against that direction. Enter at the next "
                "five-minute open."
            ),
            "stop": (
                "Beyond the three-bar gold swing plus 0.10 five-minute ATR; "
                "signals with risk below 0.20 or above 2.50 ATR are rejected."
            ),
            "permissions": (
                "Threshold 1.0 or 1.5, optionally requiring ZQ/SR3 not to oppose; "
                "macro/event filters are separate declared permissions."
            ),
            "holding": "Maximum 60 minutes; fixed 1.5R, 2R, 3R, and 4R exits.",
            "costs": (
                "Observed spread, $0.05/oz slippage per side, $7/lot round-turn "
                "commission, and identical 1.50x stress."
            ),
            "selection": (
                "Discovery 2021-08 through 2022 only; candidates are frozen for 2023 and 2024."
            ),
            "target": "10R/month at 1% risk is a hard hurdle, not an assumption.",
        },
        "source_counts": {
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


def _signals(
    bars: Sequence[Bar],
    *,
    panel: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> list[Signal]:
    atr_by_close = _atr_by_close(bars)
    output: list[Signal] = []
    last_by_state: dict[str, datetime] = {}
    for index in range(3, len(bars) - 1):
        current = bars[index]
        decision = current.close_time
        session = _session(decision)
        atr = atr_by_close.get(decision)
        if (
            session is None
            or atr is None
            or atr <= 0
            or not start <= decision < end
            or decision not in panel.index
            or bars[index + 1].open_time != decision
        ):
            continue
        row = panel.loc[pd.Timestamp(decision)]
        zt = float(row["ZT.v.0|z5"])
        zn = float(row["ZN.v.0|z5"])
        if not np.isfinite(zt) or not np.isfinite(zn) or zt * zn <= 0:
            continue
        direction = 1 if zt > 0 else -1
        strength = abs(statistics.median((zt, zn)))
        if strength < 1.0:
            continue
        signed_gold = direction * (current.close - current.open) / atr
        state = "ACCEPTED" if signed_gold >= 0.25 else "LAGGING" if signed_gold <= 0 else None
        if state is None:
            continue
        previous = last_by_state.get(state)
        if previous is not None and decision < previous + timedelta(minutes=15):
            continue
        recent = bars[index - 2 : index + 1]
        stop = (
            min(bar.low for bar in recent) - 0.10 * atr
            if direction > 0
            else max(bar.high for bar in recent) + 0.10 * atr
        )
        entry = bars[index + 1]
        risk_atr = abs(entry.open - stop) / atr
        if not 0.20 <= risk_atr <= 2.50:
            continue
        policy_values = [
            float(row[column]) for column in ("ZQ.v.0|z5", "SR3.v.0|z5") if pd.notna(row[column])
        ]
        signed_policy = direction * statistics.median(policy_values) if policy_values else math.nan
        side = "LONG" if direction > 0 else "SHORT"
        output.append(
            Signal(
                playbook=f"RATES_{state}",
                session_date=decision.date(),
                side=side,
                signal_time=decision,
                entry_time=entry.open_time,
                entry_reference=entry.open,
                stop=stop,
                base_target_r=2.0,
                max_holding_minutes=60,
                atr=atr,
                evidence={
                    "session": session,
                    "rates_strength": strength,
                    "signed_policy": signed_policy,
                    "signed_gold_bar_atr": signed_gold,
                    "risk_atr": risk_atr,
                },
            ),
        )
        last_by_state[state] = decision
    return output


def _permissions() -> tuple[Permission, ...]:
    return (
        Permission("THRESHOLD_1_00", lambda item: True),
        Permission(
            "THRESHOLD_1_50",
            lambda item: _evidence(item, "rates_strength") >= 1.50,
        ),
        Permission(
            "THRESHOLD_1_00_POLICY",
            lambda item: _evidence(item, "signed_policy") >= -0.25,
        ),
        Permission(
            "THRESHOLD_1_50_POLICY",
            lambda item: (
                _evidence(item, "rates_strength") >= 1.50
                and _evidence(item, "signed_policy") >= -0.25
            ),
        ),
        Permission(
            "THRESHOLD_1_50_POLICY_MACRO",
            lambda item: (
                _evidence(item, "rates_strength") >= 1.50
                and _evidence(item, "signed_policy") >= -0.25
                and item.fundamental.signed_score >= -5
            ),
        ),
        Permission(
            "THRESHOLD_1_50_POLICY_EVENT_CLEAR",
            lambda item: (
                _evidence(item, "rates_strength") >= 1.50
                and _evidence(item, "signed_policy") >= -0.25
                and (
                    item.fundamental.minutes_to_catalyst is None
                    or item.fundamental.minutes_to_catalyst > 30
                )
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
