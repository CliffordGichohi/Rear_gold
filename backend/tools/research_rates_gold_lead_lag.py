from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from explore_session_playbooks import Bar
from research_cross_market_auction_micro_execution import (
    _bars,
    _five_minute_bars_from_minutes,
)
from research_daily_session_playbooks import _atr_by_close
from research_one_minute_auction_execution import ONE_MINUTE_SQL
from research_rates_policy_session_edge import _rates_panel

from gold_intel.infrastructure.database import session_factory

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
THRESHOLDS = (0.5, 1.0, 1.5)
HORIZONS = (15, 30, 60)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rates-dir", type=Path, required=True)
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    started = time.perf_counter()
    async with session_factory() as session:
        minutes = _bars(
            (
                await session.execute(
                    ONE_MINUTE_SQL,
                    {
                        "load_start": start - timedelta(days=8),
                        "load_end": end,
                    },
                )
            ).mappings(),
        )
    gold = _five_minute_bars_from_minutes(minutes)
    decision_times = [
        bar.close_time
        for bar in gold
        if start <= bar.close_time < end and _session(bar.close_time) is not None
    ]
    panel, rates_contract = _rates_panel(
        args.rates_dir,
        load_start=start - timedelta(days=32),
        end=end,
        target_times=decision_times,
    )
    outcomes = _outcomes(
        gold,
        panel=panel,
        start=start,
        end=end,
    )
    hypotheses = _reports(outcomes)
    report = {
        "contract": {
            "version": "RATES_GOLD_LEAD_LAG_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "question": (
                "After a completed five-minute ZT/ZN move, does gold continue "
                "in the lower-yield direction over the next 15, 30, or 60 "
                "minutes, and is the effect stronger when gold is lagging?"
            ),
            "sampling": (
                "London 08:00-16:00 local and New York 08:00-12:00 local. "
                "Signals have a 15-minute cooldown to reduce overlapping labels."
            ),
            "entry_reference": ("Next five-minute open after both gold and rates bars complete."),
            "rates_thresholds": list(THRESHOLDS),
            "policy_variants": (
                "Treasury-only and Treasury signal with ZQ/SR3 composite not "
                "opposing by more than 0.25 standardized units."
            ),
            "purpose": (
                "Target-validity diagnostic only; no transaction-cost-free "
                "return is presented as a tradable edge."
            ),
        },
        "rates_data": rates_contract,
        "outcomes": len(outcomes),
        "hypotheses": hypotheses,
        "stable_positive_relationships": _stable(hypotheses),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _outcomes(
    gold: Sequence[Bar],
    *,
    panel: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    bars_by_open = {bar.open_time: bar for bar in gold}
    atr_by_close = _atr_by_close(gold)
    last_signal: dict[tuple[float, str], datetime] = {}
    output: list[dict[str, Any]] = []
    for bar in gold:
        decision = bar.close_time
        session = _session(decision)
        atr = atr_by_close.get(decision)
        if (
            session is None
            or atr is None
            or atr <= 0
            or not start <= decision < end
            or decision not in panel.index
        ):
            continue
        row = panel.loc[pd.Timestamp(decision)]
        zt = float(row["ZT.v.0|z5"])
        zn = float(row["ZN.v.0|z5"])
        if not np.isfinite(zt) or not np.isfinite(zn) or zt * zn <= 0:
            continue
        direction = 1 if zt > 0 else -1
        strength = abs(statistics.median((zt, zn)))
        policy_values = [
            float(row[column]) for column in ("ZQ.v.0|z5", "SR3.v.0|z5") if pd.notna(row[column])
        ]
        signed_policy = direction * statistics.median(policy_values) if policy_values else np.nan
        signed_gold_bar = direction * (bar.close - bar.open) / atr
        gold_state = (
            "LAGGING"
            if signed_gold_bar <= 0
            else "ACCEPTED"
            if signed_gold_bar >= 0.25
            else "PARTIAL_ALIGNMENT"
        )
        future = {
            horizon: _future_path(
                bars_by_open,
                decision,
                minutes=horizon,
            )
            for horizon in HORIZONS
        }
        if any(path is None for path in future.values()):
            continue
        entry_bar = bars_by_open.get(decision)
        if entry_bar is None:
            continue
        for threshold in THRESHOLDS:
            if strength < threshold:
                continue
            for policy_variant in ("TREASURY_ONLY", "POLICY_NOT_OPPOSED"):
                if policy_variant == "POLICY_NOT_OPPOSED" and (
                    not np.isfinite(signed_policy) or signed_policy < -0.25
                ):
                    continue
                cooldown_key = (threshold, policy_variant)
                previous = last_signal.get(cooldown_key)
                if previous is not None and decision < previous + timedelta(minutes=15):
                    continue
                for horizon, path in future.items():
                    if path is None:
                        continue
                    final = direction * (path[-1].close - entry_bar.open) / atr
                    favourable = max(
                        direction
                        * ((member.high if direction > 0 else member.low) - entry_bar.open)
                        / atr
                        for member in path
                    )
                    adverse = max(
                        -direction
                        * ((member.low if direction > 0 else member.high) - entry_bar.open)
                        / atr
                        for member in path
                    )
                    output.append(
                        {
                            "decision": decision,
                            "year": decision.year,
                            "session": session,
                            "side": "LONG" if direction > 0 else "SHORT",
                            "threshold": threshold,
                            "policy_variant": policy_variant,
                            "gold_state": gold_state,
                            "horizon": horizon,
                            "strength": strength,
                            "signed_policy": signed_policy,
                            "signed_final_atr": final,
                            "mfe_atr": max(0.0, favourable),
                            "mae_atr": max(0.0, adverse),
                        },
                    )
                last_signal[cooldown_key] = decision
    return output


def _reports(outcomes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in outcomes:
        key = (
            item["threshold"],
            item["policy_variant"],
            item["gold_state"],
            item["horizon"],
        )
        grouped[key].append(item)
    return [
        {
            "threshold": key[0],
            "policy_variant": key[1],
            "gold_state": key[2],
            "horizon_minutes": key[3],
            "all": _metrics(members),
            "by_year": {
                str(year): _metrics(
                    [item for item in members if item["year"] == year],
                )
                for year in (2022, 2023, 2024)
            },
            "by_session": {
                session: _metrics(
                    [item for item in members if item["session"] == session],
                )
                for session in ("LONDON", "NEW_YORK", "OVERLAP")
            },
        }
        for key, members in sorted(grouped.items())
    ]


def _stable(reports: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        report
        for report in reports
        if report["all"]["observations"] >= 100
        and report["all"]["average_signed_final_atr"] > 0
        and all(
            report["by_year"][str(year)]["observations"] >= 20
            and report["by_year"][str(year)]["average_signed_final_atr"] > 0
            for year in (2022, 2023, 2024)
        )
    ]


def _metrics(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "observations": 0,
            "positive_pct": None,
            "average_signed_final_atr": None,
            "average_mfe_atr": None,
            "average_mae_atr": None,
        }
    final = [float(item["signed_final_atr"]) for item in items]
    interval = _bootstrap(final)
    return {
        "observations": len(items),
        "positive_pct": round(sum(value > 0 for value in final) / len(final) * 100, 4),
        "average_signed_final_atr": round(statistics.mean(final), 6),
        "median_signed_final_atr": round(statistics.median(final), 6),
        "bootstrap_95ci": [round(interval[0], 6), round(interval[1], 6)],
        "average_mfe_atr": round(
            statistics.mean(float(item["mfe_atr"]) for item in items),
            6,
        ),
        "average_mae_atr": round(
            statistics.mean(float(item["mae_atr"]) for item in items),
            6,
        ),
    }


def _bootstrap(values: Sequence[float]) -> tuple[float, float]:
    if len(values) < 2:
        value = values[0] if values else 0.0
        return value, value
    array = np.asarray(values, dtype=np.float64)
    generator = np.random.default_rng(20260728)
    means = np.empty(2_000, dtype=np.float64)
    for index in range(len(means)):
        means[index] = float(
            generator.choice(array, size=len(array), replace=True).mean(),
        )
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _future_path(
    bars_by_open: dict[datetime, Bar],
    start: datetime,
    *,
    minutes: int,
) -> list[Bar] | None:
    path = [bars_by_open.get(start + timedelta(minutes=offset)) for offset in range(0, minutes, 5)]
    return None if any(bar is None for bar in path) else [bar for bar in path if bar is not None]


def _session(timestamp: datetime) -> str | None:
    london = timestamp.astimezone(LONDON)
    new_york = timestamp.astimezone(NEW_YORK)
    in_london = 8 <= london.hour < 16
    in_new_york = 8 <= new_york.hour < 12
    if in_london and in_new_york:
        return "OVERLAP"
    if in_london:
        return "LONDON"
    if in_new_york:
        return "NEW_YORK"
    return None


if __name__ == "__main__":
    asyncio.run(main())
