from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from explore_session_playbooks import Bar
from research_cross_market_auction_micro_execution import (
    _bars,
    _five_minute_bars_from_csv_directory,
    _five_minute_bars_from_minutes,
)
from research_daily_session_playbooks import _atr_by_close
from research_multi_asset_session_portfolio import (
    FIVE_MINUTE_SQL,
    POINT_SIZES,
)
from research_one_minute_auction_execution import ONE_MINUTE_SQL
from research_rates_gold_lead_lag import _future_path, _session
from research_rates_policy_session_edge import _rates_panel

from gold_intel.infrastructure.database import session_factory

LOCKED_HOLDOUT = datetime(2025, 1, 1, tzinfo=UTC)
FEATURES = ("EURUSD", "XAGUSD", "US500", "ZT.v.0", "ZN.v.0")
RIDGE_PENALTY = 25.0
TRAINING_DAYS = 60
MINIMUM_TRAINING_ROWS = 1_000
HORIZONS = (15, 30, 60)


@dataclass(frozen=True, slots=True)
class Observation:
    decision: datetime
    session: str
    gold_z: float
    features: tuple[float, ...]
    atr: float


@dataclass(frozen=True, slots=True)
class Prediction:
    observation: Observation
    training_rows: int
    fair_value_z: float
    fair_strength_z: float
    residual_z: float
    contributions: tuple[float, ...]


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Test whether a point-in-time cross-market fair-value residual "
            "predicts gold catch-up, continuation, or reversion."
        ),
    )
    parser.add_argument("--rates-dir", type=Path, required=True)
    parser.add_argument("--us500-csv-dir", type=Path, required=True)
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > LOCKED_HOLDOUT:
        raise ValueError("The locked calendar-2025 holdout must not be loaded")

    started = time.perf_counter()
    load_start = start - timedelta(days=90)
    async with session_factory() as session:
        gold_minutes = _bars(
            (
                await session.execute(
                    ONE_MINUTE_SQL,
                    {"load_start": load_start, "load_end": end},
                )
            ).mappings(),
        )
        cross_market: dict[str, list[Bar]] = {}
        for instrument in ("EURUSD", "XAGUSD"):
            cross_market[instrument] = _bars(
                (
                    await session.execute(
                        FIVE_MINUTE_SQL,
                        {
                            "instrument": instrument,
                            "load_start": load_start,
                            "load_end": end,
                        },
                    )
                ).mappings(),
            )
    gold = _five_minute_bars_from_minutes(gold_minutes)
    cross_market["US500"] = _five_minute_bars_from_csv_directory(
        args.us500_csv_dir,
        load_start=load_start,
        load_end=end,
        point_size=POINT_SIZES["US500"],
    )
    decision_times = [
        bar.close_time
        for bar in gold
        if start <= bar.close_time < end and _session(bar.close_time) is not None
    ]
    rates, rates_contract = _rates_panel(
        args.rates_dir,
        load_start=load_start,
        end=end,
        target_times=decision_times,
    )
    _phase("SOURCE_DATA_LOADED", started)

    observations = _observations(
        gold,
        cross_market=cross_market,
        rates=rates,
        start=load_start,
        end=end,
    )
    predictions, model_snapshots = _walk_forward_predictions(
        observations,
        prediction_start=start,
    )
    _phase("WALK_FORWARD_PREDICTIONS_COMPLETE", started)
    outcomes = _outcomes(
        predictions,
        gold=gold,
    )
    reports = _reports(outcomes)
    report = {
        "contract": {
            "version": "GOLD_CROSS_MARKET_FAIR_VALUE_DISLOCATION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "features": list(FEATURES),
            "model": (
                "Transparent standardized ridge regression of completed "
                "five-minute gold return on simultaneous completed EURUSD, "
                "silver, US500, 2-year Treasury-future, and 10-year "
                "Treasury-future returns."
            ),
            "walk_forward": (
                "Refit once per UTC day on only the prior 60 calendar days; "
                "the current day is excluded. Minimum 1,000 prior observations."
            ),
            "states": {
                "LAG_CATCHUP": (
                    "Absolute fair-value prediction >=1.0 prior-prediction "
                    "standard deviations while gold moved <=0.10 ATR in that "
                    "direction; test continuation toward fair value."
                ),
                "FAIR_CONFIRMED": (
                    "Absolute fair-value prediction >=1.0 standard deviations "
                    "and gold already moved >=0.25 ATR in that direction; test "
                    "continuation."
                ),
                "RESIDUAL_REVERSION": (
                    "Absolute contemporaneous model residual >=1.5 prior "
                    "residual standard deviations; test reversal of the residual."
                ),
            },
            "label": (
                "Enter conceptually at the next completed five-minute bar open; "
                "measure 15/30/60-minute signed final return, MFE, and MAE in "
                "decision-time gold ATR. A 15-minute per-state cooldown reduces "
                "overlapping labels."
            ),
            "purpose": (
                "Target-validity diagnostic only. It must establish a stable "
                "relationship before any stop/target strategy is backtested."
            ),
        },
        "data": {
            "gold_bars_5m": len(gold),
            "cross_market_bars_5m": {
                instrument: len(bars)
                for instrument, bars in sorted(cross_market.items())
            },
            "rates": rates_contract,
        },
        "source_counts": {
            "synchronized_observations": len(observations),
            "walk_forward_predictions": len(predictions),
            "diagnostic_outcomes": len(outcomes),
        },
        "model_diagnostics": {
            "coefficient_stability": _coefficient_stability(model_snapshots),
            "contemporaneous_calibration": _calibration(predictions),
        },
        "hypotheses": reports,
        "stable_positive_relationships": _stable(reports),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output is None:
        print(serialized)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "output": str(args.output),
                    "observations": len(observations),
                    "predictions": len(predictions),
                    "outcomes": len(outcomes),
                    "stable_relationships": len(
                        report["stable_positive_relationships"],
                    ),
                    "elapsed_seconds": report["elapsed_seconds"],
                },
                indent=2,
            ),
        )


def _observations(
    gold: Sequence[Bar],
    *,
    cross_market: dict[str, list[Bar]],
    rates: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> list[Observation]:
    gold_atr = _atr_by_close(gold)
    cross_by_close = {
        instrument: {bar.close_time: bar for bar in bars}
        for instrument, bars in cross_market.items()
    }
    cross_atr = {
        instrument: _atr_by_close(bars)
        for instrument, bars in cross_market.items()
    }
    output: list[Observation] = []
    for bar in gold:
        decision = bar.close_time
        session = _session(decision)
        atr = gold_atr.get(decision)
        if (
            session is None
            or atr is None
            or atr <= 0
            or not start <= decision < end
            or decision not in rates.index
        ):
            continue
        feature_values: list[float] = []
        complete = True
        for instrument in ("EURUSD", "XAGUSD", "US500"):
            member = cross_by_close[instrument].get(decision)
            member_atr = cross_atr[instrument].get(decision)
            if member is None or member_atr is None or member_atr <= 0:
                complete = False
                break
            feature_values.append((member.close - member.open) / member_atr)
        if not complete:
            continue
        rate_row = rates.loc[pd.Timestamp(decision)]
        rate_values = [
            float(rate_row["ZT.v.0|z5"]),
            float(rate_row["ZN.v.0|z5"]),
        ]
        if not all(np.isfinite(value) for value in (*feature_values, *rate_values)):
            continue
        output.append(
            Observation(
                decision=decision,
                session=session,
                gold_z=(bar.close - bar.open) / atr,
                features=tuple((*feature_values, *rate_values)),
                atr=atr,
            ),
        )
    return output


def _walk_forward_predictions(
    observations: Sequence[Observation],
    *,
    prediction_start: datetime,
) -> tuple[list[Prediction], list[dict[str, Any]]]:
    by_date: dict[date, list[Observation]] = defaultdict(list)
    for observation in observations:
        by_date[observation.decision.date()].append(observation)
    ordered = sorted(observations, key=lambda item: item.decision)
    output: list[Prediction] = []
    snapshots: list[dict[str, Any]] = []
    for model_date in sorted(by_date):
        if model_date < prediction_start.date():
            continue
        day_start = datetime.combine(
            model_date,
            datetime.min.time(),
            tzinfo=UTC,
        )
        training_start = day_start - timedelta(days=TRAINING_DAYS)
        training = [
            item
            for item in ordered
            if training_start <= item.decision < day_start
        ]
        if len(training) < MINIMUM_TRAINING_ROWS:
            continue
        train_x = np.asarray(
            [item.features for item in training],
            dtype=np.float64,
        )
        train_y = np.asarray(
            [item.gold_z for item in training],
            dtype=np.float64,
        )
        means = train_x.mean(axis=0)
        scales = train_x.std(axis=0)
        scales = np.where(scales > 1e-8, scales, 1.0)
        standardized = np.clip((train_x - means) / scales, -6.0, 6.0)
        design = np.column_stack((np.ones(len(training)), standardized))
        penalty = np.eye(design.shape[1]) * RIDGE_PENALTY
        penalty[0, 0] = 0.0
        coefficients = np.linalg.solve(
            design.T @ design + penalty,
            design.T @ train_y,
        )
        fitted = design @ coefficients
        prediction_scale = float(np.std(fitted))
        residual_scale = float(np.std(train_y - fitted))
        if prediction_scale <= 1e-8 or residual_scale <= 1e-8:
            continue
        snapshots.append(
            {
                "model_date": model_date.isoformat(),
                "training_rows": len(training),
                "intercept": float(coefficients[0]),
                "coefficients": {
                    feature: float(coefficient)
                    for feature, coefficient in zip(
                        FEATURES,
                        coefficients[1:],
                        strict=True,
                    )
                },
                "prediction_scale": prediction_scale,
                "residual_scale": residual_scale,
            },
        )
        for observation in by_date[model_date]:
            standardized_current = np.clip(
                (np.asarray(observation.features) - means) / scales,
                -6.0,
                6.0,
            )
            contributions = coefficients[1:] * standardized_current
            fair_value = float(coefficients[0] + contributions.sum())
            output.append(
                Prediction(
                    observation=observation,
                    training_rows=len(training),
                    fair_value_z=fair_value,
                    fair_strength_z=fair_value / prediction_scale,
                    residual_z=(
                        observation.gold_z - fair_value
                    )
                    / residual_scale,
                    contributions=tuple(float(value) for value in contributions),
                ),
            )
    return output, snapshots


def _outcomes(
    predictions: Sequence[Prediction],
    *,
    gold: Sequence[Bar],
) -> list[dict[str, Any]]:
    bars_by_open = {bar.open_time: bar for bar in gold}
    last_signal: dict[str, datetime] = {}
    output: list[dict[str, Any]] = []
    for prediction in predictions:
        observation = prediction.observation
        fair_direction = 1 if prediction.fair_strength_z > 0 else -1
        signed_gold = fair_direction * observation.gold_z
        proposals: list[tuple[str, int]] = []
        if abs(prediction.fair_strength_z) >= 1.0 and signed_gold <= 0.10:
            proposals.append(("LAG_CATCHUP", fair_direction))
        if abs(prediction.fair_strength_z) >= 1.0 and signed_gold >= 0.25:
            proposals.append(("FAIR_CONFIRMED", fair_direction))
        if abs(prediction.residual_z) >= 1.5:
            proposals.append(
                (
                    "RESIDUAL_REVERSION",
                    -1 if prediction.residual_z > 0 else 1,
                ),
            )
        for state, direction in proposals:
            previous = last_signal.get(state)
            if (
                previous is not None
                and observation.decision < previous + timedelta(minutes=15)
            ):
                continue
            for horizon in HORIZONS:
                path = _future_path(
                    bars_by_open,
                    observation.decision,
                    minutes=horizon,
                )
                entry = bars_by_open.get(observation.decision)
                if path is None or entry is None:
                    continue
                final = (
                    direction
                    * (path[-1].close - entry.open)
                    / observation.atr
                )
                favourable = max(
                    direction
                    * (
                        (bar.high if direction > 0 else bar.low)
                        - entry.open
                    )
                    / observation.atr
                    for bar in path
                )
                adverse = max(
                    -direction
                    * (
                        (bar.low if direction > 0 else bar.high)
                        - entry.open
                    )
                    / observation.atr
                    for bar in path
                )
                output.append(
                    {
                        "decision": observation.decision,
                        "year": observation.decision.year,
                        "session": observation.session,
                        "state": state,
                        "horizon": horizon,
                        "side": "LONG" if direction > 0 else "SHORT",
                        "fair_strength_z": prediction.fair_strength_z,
                        "residual_z": prediction.residual_z,
                        "signed_final_atr": final,
                        "mfe_atr": max(0.0, favourable),
                        "mae_atr": max(0.0, adverse),
                    },
                )
            last_signal[state] = observation.decision
    return output


def _reports(outcomes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for item in outcomes:
        grouped[(str(item["state"]), int(item["horizon"]))].append(item)
    reports: list[dict[str, Any]] = []
    for (state, horizon), members in sorted(grouped.items()):
        reports.append(
            {
                "state": state,
                "horizon_minutes": horizon,
                "discovery": _metrics(
                    [
                        item
                        for item in members
                        if item["decision"] < datetime(2023, 1, 1, tzinfo=UTC)
                    ],
                ),
                "validation_2023": _metrics(
                    [item for item in members if int(item["year"]) == 2023],
                ),
                "forward_2024": _metrics(
                    [item for item in members if int(item["year"]) == 2024],
                ),
                "all_pre_2025": _metrics(members),
                "by_session": {
                    session: _metrics(
                        [item for item in members if item["session"] == session],
                    )
                    for session in ("LONDON", "OVERLAP", "NEW_YORK")
                },
            },
        )
    return reports


def _metrics(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    values = [float(item["signed_final_atr"]) for item in items]
    if not values:
        return {
            "observations": 0,
            "average_signed_final_atr": None,
            "median_signed_final_atr": None,
            "positive_pct": None,
            "average_mfe_atr": None,
            "average_mae_atr": None,
            "bootstrap_95ci": [None, None],
        }
    return {
        "observations": len(values),
        "average_signed_final_atr": round(statistics.mean(values), 6),
        "median_signed_final_atr": round(statistics.median(values), 6),
        "positive_pct": round(
            sum(value > 0 for value in values) / len(values) * 100,
            4,
        ),
        "average_mfe_atr": round(
            statistics.mean(float(item["mfe_atr"]) for item in items),
            6,
        ),
        "average_mae_atr": round(
            statistics.mean(float(item["mae_atr"]) for item in items),
            6,
        ),
        "bootstrap_95ci": list(_bootstrap(values)),
    }


def _bootstrap(values: Sequence[float]) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    array = np.asarray(values, dtype=np.float64)
    generator = np.random.default_rng(20260728 + len(values))
    means = np.empty(2_000, dtype=np.float64)
    for index in range(len(means)):
        means[index] = generator.choice(
            array,
            size=len(array),
            replace=True,
        ).mean()
    return (
        round(float(np.quantile(means, 0.025)), 6),
        round(float(np.quantile(means, 0.975)), 6),
    )


def _stable(reports: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for report in reports:
        periods = (
            report["discovery"],
            report["validation_2023"],
            report["forward_2024"],
        )
        overall = report["all_pre_2025"]
        if (
            all(int(period["observations"]) >= 100 for period in periods)
            and all(
                float(period["average_signed_final_atr"]) > 0
                for period in periods
            )
            and float(overall["bootstrap_95ci"][0]) > 0
        ):
            output.append(report)
    return output


def _coefficient_stability(
    snapshots: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for feature in FEATURES:
        values = [
            float(snapshot["coefficients"][feature])
            for snapshot in snapshots
        ]
        output[feature] = {
            "snapshots": len(values),
            "median": round(statistics.median(values), 6) if values else None,
            "positive_pct": (
                round(sum(value > 0 for value in values) / len(values) * 100, 4)
                if values
                else None
            ),
        }
    return output


def _calibration(
    predictions: Sequence[Prediction],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for label, members in (
        ("all_pre_2025", list(predictions)),
        (
            "discovery",
            [
                item
                for item in predictions
                if item.observation.decision.year <= 2022
            ],
        ),
        (
            "validation_2023",
            [
                item
                for item in predictions
                if item.observation.decision.year == 2023
            ],
        ),
        (
            "forward_2024",
            [
                item
                for item in predictions
                if item.observation.decision.year == 2024
            ],
        ),
    ):
        fair = np.asarray(
            [item.fair_value_z for item in members],
            dtype=np.float64,
        )
        actual = np.asarray(
            [item.observation.gold_z for item in members],
            dtype=np.float64,
        )
        correlation = (
            float(np.corrcoef(fair, actual)[0, 1])
            if len(members) >= 2
            else float("nan")
        )
        output[label] = {
            "observations": len(members),
            "prediction_actual_correlation": (
                round(correlation, 6)
                if np.isfinite(correlation)
                else None
            ),
            "average_absolute_prediction_atr": (
                round(float(np.mean(np.abs(fair))), 6)
                if len(members)
                else None
            ),
        }
    return output


def _phase(name: str, started: float) -> None:
    print(
        f"{name} elapsed={time.perf_counter() - started:.3f}s",
        flush=True,
        file=__import__("sys").stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
