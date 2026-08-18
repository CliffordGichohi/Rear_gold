from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from research_daily_session_playbooks import Trade
from research_session_state_transitions import _compact_metrics

RIDGE_PENALTY = 25.0
MINIMUM_TRAINING_EXAMPLES = 1_000
THRESHOLDS = (-0.10, 0.0, 0.05, 0.10, 0.15, 0.20, 0.30)
INSTRUMENTS = ("XAUUSD", "XAGUSD", "EURUSD", "US500")
SESSIONS = (
    "LONDON_OPEN",
    "COMEX_OPEN",
    "NEW_YORK_CASH",
    "LONDON_NEW_YORK",
    "NEW_YORK_LIQUID",
)
PATTERNS = (
    "OR_BREAKOUT",
    "OR_RETEST",
    "OR_FAILURE",
    "DONCHIAN_BREAKOUT",
    "FAILED_DONCHIAN",
    "COMPRESSION_BREAK",
    "EXTENSION_REJECTION",
)
MANAGERS = ("FIXED_1_50R", "FIXED_2_00R", "FIXED_3_00R", "FIXED_4_00R")
CONTINUOUS_FEATURES = (
    "SIDE_LONG",
    "RISK_ATR",
    "ESTIMATED_COST_R",
    "RELATIVE_VOLUME",
    "OPENING_RANGE_ATR",
    "OPENING_RANGE_PERCENTILE",
    "SIGNED_TREND_60_ATR",
    "SIGNED_TREND_240_ATR",
    "VOLATILITY_RATIO",
)
FEATURE_NAMES = (
    *CONTINUOUS_FEATURES,
    *(f"INSTRUMENT::{name}" for name in INSTRUMENTS),
    *(f"SESSION::{name}" for name in SESSIONS),
    *(f"PATTERN::{name}" for name in PATTERNS),
    *(f"MANAGER::{name}" for name in MANAGERS),
    *(f"TREND_60_X::{name}" for name in INSTRUMENTS),
    *(f"TREND_240_X::{name}" for name in INSTRUMENTS),
    *(f"RANGE_PERCENTILE_X::{name}" for name in PATTERNS),
    *(
        f"INSTRUMENT_PATTERN::{instrument}::{pattern}"
        for instrument in INSTRUMENTS
        for pattern in PATTERNS
    ),
    *(f"MANAGER_PATTERN::{manager}::{pattern}" for manager in MANAGERS for pattern in PATTERNS),
)


@dataclass(frozen=True, slots=True)
class Example:
    trade: Trade
    stress_trade: Trade
    manager: str
    instrument: str
    cluster: str
    pattern: str
    features: tuple[float, ...]

    @property
    def signal_key(self) -> tuple[str, datetime, str]:
        return (
            self.trade.playbook,
            self.trade.signal_time,
            self.trade.side,
        )


@dataclass(frozen=True, slots=True)
class RidgeModel:
    means: np.ndarray
    scales: np.ndarray
    coefficients: np.ndarray

    def predict(
        self,
        features: Sequence[float],
    ) -> tuple[float, np.ndarray]:
        raw = np.asarray(features, dtype=np.float64)
        imputed = np.where(np.isfinite(raw), raw, self.means)
        standardized = np.clip(
            (imputed - self.means) / self.scales,
            -6.0,
            6.0,
        )
        contributions = self.coefficients[1:] * standardized
        prediction = float(self.coefficients[0] + contributions.sum())
        return prediction, contributions


@dataclass(frozen=True, slots=True)
class Prediction:
    example: Example
    predicted_net_r: float
    model_month: str
    training_examples: int
    top_contributions: tuple[dict[str, float | str], ...]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--prediction-cache", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    examples = _load_examples(args.cache)
    _phase("EXAMPLES_LOADED", started)
    predictions, snapshots = _walk_forward_predictions(examples)
    _phase("WALK_FORWARD_COMPLETE", started)
    if args.prediction_cache is not None:
        _write_prediction_cache(predictions, args.prediction_cache)

    threshold_reports = {
        _threshold_label(threshold): _threshold_report(
            predictions,
            minimum_prediction=threshold,
        )
        for threshold in THRESHOLDS
    }
    selected_threshold = _select_threshold(threshold_reports)
    selected_report = (
        threshold_reports[_threshold_label(selected_threshold)]
        if selected_threshold is not None
        else None
    )
    report = {
        "contract": {
            "version": "MULTI_ASSET_WALK_FORWARD_RIDGE_V0_3",
            "source_cache": str(args.cache.resolve()),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "model": (
                "Standardized ridge regression predicts net R. It refits at "
                "every month boundary using only prior completed months."
            ),
            "target_choice": (
                "Each signal has four declared fixed-R alternatives. The model "
                "chooses the highest predicted manager before observing its path."
            ),
            "ridge_penalty": RIDGE_PENALTY,
            "minimum_training_examples": MINIMUM_TRAINING_EXAMPLES,
            "declared_thresholds": list(THRESHOLDS),
            "threshold_selection": (
                "Calendar 2022 only: at least 120 accepted trades, expectancy "
                "at least 0.05R, profit factor at least 1.10, and positive "
                "expectancy at 1.50x costs. Rank by the weaker of base and "
                "stressed expectancy. Calendar 2023 and 2024 never select."
            ),
            "portfolio": (
                "One position per correlation cluster, at most two simultaneous "
                "positions, and no new entry after -3R realized daily P&L."
            ),
            "promotion": (
                "The selected threshold must remain positive in 2022, 2023, "
                "and 2024 under base and stressed costs. The hard target is "
                "10R average per calendar month in every year, positive median "
                "month, and at least 55% positive months."
            ),
        },
        "source_counts": {
            "base_manager_examples": len(examples),
            "unique_signals": len({example.signal_key for example in examples}),
            "walk_forward_selected_manager_predictions": len(predictions),
            "model_months": len(snapshots),
        },
        "features": list(FEATURE_NAMES),
        "feature_non_missing_pct": _feature_coverage(examples),
        "manager_choice_funnel": _manager_funnel(predictions),
        "baseline": _threshold_report(
            predictions,
            minimum_prediction=-math.inf,
        ),
        "thresholds": threshold_reports,
        "selected_threshold": selected_threshold,
        "selected_threshold_report": selected_report,
        "promotion_gate": _promotion_gate(selected_report),
        "calibration": _calibration(predictions),
        "coefficient_stability": _coefficient_stability(snapshots),
        "model_snapshots": snapshots,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _load_examples(path: Path) -> list[Example]:
    frame = pd.read_csv(
        path,
        parse_dates=["signal_time", "entry_time", "exit_time"],
    )
    required = {
        "playbook",
        "session_date",
        "side",
        "manager",
        "cost_multiplier",
        "instrument",
        "cluster",
        "gross_r",
        "net_r",
        "cost_r",
        "mfe_r",
        "mae_r",
        "risk_distance",
    }
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"Context cache is missing columns: {sorted(missing)}")
    for column in ("signal_time", "entry_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    if (frame["signal_time"] >= pd.Timestamp("2025-01-01T00:00:00Z")).any():
        raise RuntimeError("Locked 2025 data leaked into the context cache")
    frame = frame[
        (frame["session_date"] >= "2021-08-01") & (frame["session_date"] < "2025-01-01")
    ].copy()
    key_columns = ["playbook", "signal_time", "side", "manager"]
    base = frame[np.isclose(frame["cost_multiplier"], 1.0)].copy()
    stress = frame[np.isclose(frame["cost_multiplier"], 1.5)].copy()
    if base.duplicated(key_columns).any() or stress.duplicated(key_columns).any():
        raise RuntimeError("Duplicate signal-manager rows in context cache")
    stress_by_key = {
        tuple(row[column] for column in key_columns): row for _, row in stress.iterrows()
    }
    output: list[Example] = []
    for _, row in base.iterrows():
        key = tuple(row[column] for column in key_columns)
        stress_row = stress_by_key.get(key)
        if stress_row is None:
            raise RuntimeError(f"Missing stressed execution for {key}")
        playbook_parts = str(row["playbook"]).split("|")
        if len(playbook_parts) != 3:
            raise RuntimeError(f"Unexpected playbook contract: {row['playbook']}")
        instrument, _, pattern = playbook_parts
        manager = str(row["manager"])
        output.append(
            Example(
                trade=_trade(row),
                stress_trade=_trade(stress_row),
                manager=manager,
                instrument=instrument,
                cluster=str(row["cluster"]),
                pattern=pattern,
                features=_features(
                    row,
                    instrument=instrument,
                    pattern=pattern,
                    manager=manager,
                ),
            ),
        )
    return sorted(
        output,
        key=lambda example: (
            example.trade.signal_time,
            example.trade.playbook,
            example.manager,
        ),
    )


def _trade(row: pd.Series[Any]) -> Trade:
    evidence = {
        "instrument": str(row["instrument"]),
        "cluster": str(row["cluster"]),
        "session": str(row["session"]),
        "manager": str(row["manager"]),
    }
    return Trade(
        playbook=str(row["playbook"]),
        session_date=date.fromisoformat(str(row["session_date"])),
        side=str(row["side"]),
        signal_time=_timestamp(row["signal_time"]),
        entry_time=_timestamp(row["entry_time"]),
        exit_time=_timestamp(row["exit_time"]),
        exit_reason=str(row["exit_reason"]),
        risk_distance=float(row["risk_distance"]),
        gross_r=float(row["gross_r"]),
        net_r=float(row["net_r"]),
        cost_r=float(row["cost_r"]),
        mfe_r=float(row["mfe_r"]),
        mae_r=float(row["mae_r"]),
        holding_minutes=int(row["holding_minutes"]),
        evidence=evidence,
    )


def _features(
    row: pd.Series[Any],
    *,
    instrument: str,
    pattern: str,
    manager: str,
) -> tuple[float, ...]:
    trend_60 = _number(row, "signed_trend_60_atr")
    trend_240 = _number(row, "signed_trend_240_atr")
    range_percentile = _number(row, "opening_range_percentile")
    continuous = (
        1.0 if str(row["side"]) == "LONG" else 0.0,
        _number(row, "risk_atr"),
        _number(row, "estimated_cost_r"),
        _number(row, "relative_volume"),
        _number(row, "opening_range_atr"),
        range_percentile,
        trend_60,
        trend_240,
        _number(row, "volatility_ratio"),
    )
    values = (
        *continuous,
        *(1.0 if instrument == name else 0.0 for name in INSTRUMENTS),
        *(1.0 if str(row["session"]) == name else 0.0 for name in SESSIONS),
        *(1.0 if pattern == name else 0.0 for name in PATTERNS),
        *(1.0 if manager == name else 0.0 for name in MANAGERS),
        *(trend_60 if instrument == name else 0.0 for name in INSTRUMENTS),
        *(trend_240 if instrument == name else 0.0 for name in INSTRUMENTS),
        *(range_percentile if pattern == name else 0.0 for name in PATTERNS),
        *(
            1.0 if instrument == instrument_name and pattern == pattern_name else 0.0
            for instrument_name in INSTRUMENTS
            for pattern_name in PATTERNS
        ),
        *(
            1.0 if manager == manager_name and pattern == pattern_name else 0.0
            for manager_name in MANAGERS
            for pattern_name in PATTERNS
        ),
    )
    if len(values) != len(FEATURE_NAMES):
        raise RuntimeError("Feature contract length is inconsistent")
    return tuple(float(value) for value in values)


def _walk_forward_predictions(
    examples: Sequence[Example],
) -> tuple[list[Prediction], list[dict[str, Any]]]:
    by_month: dict[tuple[int, int], list[Example]] = defaultdict(list)
    for example in examples:
        day = example.trade.session_date
        by_month[(day.year, day.month)].append(example)
    predictions: list[Prediction] = []
    snapshots: list[dict[str, Any]] = []
    for year, month in sorted(by_month):
        month_start = date(year, month, 1)
        training = [example for example in examples if example.trade.session_date < month_start]
        if year < 2022 or len(training) < MINIMUM_TRAINING_EXAMPLES:
            continue
        model = _fit_model(training)
        model_month = f"{year:04d}-{month:02d}"
        snapshots.append(_model_snapshot(model, model_month, training))
        alternatives: dict[
            tuple[str, datetime, str],
            list[Prediction],
        ] = defaultdict(list)
        for example in by_month[(year, month)]:
            predicted, contributions = model.predict(example.features)
            ranked = sorted(
                zip(FEATURE_NAMES, contributions, strict=True),
                key=lambda item: abs(float(item[1])),
                reverse=True,
            )[:5]
            alternatives[example.signal_key].append(
                Prediction(
                    example=example,
                    predicted_net_r=predicted,
                    model_month=model_month,
                    training_examples=len(training),
                    top_contributions=tuple(
                        {
                            "feature": name,
                            "predicted_r_contribution": round(float(value), 8),
                        }
                        for name, value in ranked
                    ),
                ),
            )
        predictions.extend(
            max(
                members,
                key=lambda prediction: (
                    prediction.predicted_net_r,
                    prediction.example.manager,
                ),
            )
            for members in alternatives.values()
        )
    return sorted(
        predictions,
        key=lambda prediction: (
            prediction.example.trade.entry_time,
            prediction.example.trade.playbook,
        ),
    ), snapshots


def _fit_model(examples: Sequence[Example]) -> RidgeModel:
    matrix = np.asarray(
        [example.features for example in examples],
        dtype=np.float64,
    )
    targets = np.asarray(
        [example.trade.net_r for example in examples],
        dtype=np.float64,
    )
    finite = np.isfinite(matrix)
    counts = finite.sum(axis=0)
    means = np.divide(
        np.where(finite, matrix, 0.0).sum(axis=0),
        counts,
        out=np.zeros(matrix.shape[1], dtype=np.float64),
        where=counts > 0,
    )
    imputed = np.where(finite, matrix, means)
    scales = np.std(imputed, axis=0)
    scales = np.where(scales >= 1e-8, scales, 1.0)
    standardized = np.clip((imputed - means) / scales, -6.0, 6.0)
    design = np.column_stack((np.ones(len(standardized)), standardized))
    penalty = np.eye(design.shape[1], dtype=np.float64) * RIDGE_PENALTY
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        design.T @ design + penalty,
        design.T @ targets,
    )
    return RidgeModel(
        means=means,
        scales=scales,
        coefficients=coefficients,
    )


def _model_snapshot(
    model: RidgeModel,
    model_month: str,
    training: Sequence[Example],
) -> dict[str, Any]:
    return {
        "model_month": model_month,
        "training_examples": len(training),
        "training_first": training[0].trade.session_date.isoformat(),
        "training_last": training[-1].trade.session_date.isoformat(),
        "intercept": round(float(model.coefficients[0]), 8),
        "standardized_coefficients": {
            name: round(float(value), 8)
            for name, value in zip(
                FEATURE_NAMES,
                model.coefficients[1:],
                strict=True,
            )
        },
    }


def _threshold_report(
    predictions: Sequence[Prediction],
    *,
    minimum_prediction: float,
) -> dict[str, Any]:
    eligible = [
        prediction for prediction in predictions if prediction.predicted_net_r >= minimum_prediction
    ]
    accepted, diagnostics = _portfolio(eligible)
    base = _period_reports(
        [prediction.example.trade for prediction in accepted],
    )
    stress = _period_reports(
        [prediction.example.stress_trade for prediction in accepted],
    )
    return {
        "minimum_predicted_net_r": (
            None if not math.isfinite(minimum_prediction) else minimum_prediction
        ),
        "eligible_signals": len(eligible),
        "accepted_trades": len(accepted),
        **diagnostics,
        "base_cost": base,
        "stress_1_50x_cost": stress,
        "by_instrument": _group_report(accepted, "instrument"),
        "by_manager": _group_report(accepted, "manager"),
    }


def _portfolio(
    predictions: Sequence[Prediction],
) -> tuple[list[Prediction], dict[str, int]]:
    ordered = sorted(
        predictions,
        key=lambda prediction: (
            prediction.example.trade.entry_time,
            -prediction.predicted_net_r,
            prediction.example.trade.playbook,
        ),
    )
    accepted: list[Prediction] = []
    active: list[Prediction] = []
    pending: list[Prediction] = []
    realized_by_day: dict[date, float] = defaultdict(float)
    skipped_cluster = 0
    skipped_capacity = 0
    skipped_daily_loss = 0
    for prediction in ordered:
        trade = prediction.example.trade
        completed = [item for item in pending if item.example.trade.exit_time <= trade.entry_time]
        for item in completed:
            key = item.example.trade.entry_time.astimezone(UTC).date()
            realized_by_day[key] += item.example.trade.net_r
        pending = [item for item in pending if item.example.trade.exit_time > trade.entry_time]
        active = [item for item in active if item.example.trade.exit_time > trade.entry_time]
        if any(item.example.cluster == prediction.example.cluster for item in active):
            skipped_cluster += 1
            continue
        if len(active) >= 2:
            skipped_capacity += 1
            continue
        day_key = trade.entry_time.astimezone(UTC).date()
        if realized_by_day[day_key] <= -3.0:
            skipped_daily_loss += 1
            continue
        accepted.append(prediction)
        active.append(prediction)
        pending.append(prediction)
    return accepted, {
        "skipped_cluster_overlap": skipped_cluster,
        "skipped_account_capacity": skipped_capacity,
        "skipped_daily_loss": skipped_daily_loss,
    }


def _period_reports(trades: Sequence[Trade]) -> dict[str, Any]:
    return {
        str(year): _compact_metrics(
            [trade for trade in trades if trade.session_date.year == year],
            calendar_start=date(year, 1, 1),
            calendar_end=date(year + 1, 1, 1),
        )
        for year in (2022, 2023, 2024)
    } | {
        "ALL_PRE_2025": _compact_metrics(
            trades,
            calendar_start=date(2022, 1, 1),
            calendar_end=date(2025, 1, 1),
        ),
    }


def _select_threshold(
    reports: dict[str, dict[str, Any]],
) -> float | None:
    eligible: list[tuple[float, float]] = []
    for threshold in THRESHOLDS:
        report = reports[_threshold_label(threshold)]
        base = report["base_cost"]["2022"]
        stress = report["stress_1_50x_cost"]["2022"]
        if (
            base["trades"] >= 120
            and base["net_expectancy_r"] is not None
            and float(base["net_expectancy_r"]) >= 0.05
            and base["profit_factor"] is not None
            and float(base["profit_factor"]) >= 1.10
            and stress["net_expectancy_r"] is not None
            and float(stress["net_expectancy_r"]) > 0
        ):
            conservative = min(
                float(base["net_expectancy_r"]),
                float(stress["net_expectancy_r"]),
            )
            eligible.append((conservative, threshold))
    return max(eligible)[1] if eligible else None


def _promotion_gate(
    selected: dict[str, Any] | None,
) -> dict[str, Any]:
    if selected is None:
        return {
            "passed": False,
            "reason": "No threshold qualified on calendar-2022 discovery.",
        }
    year_checks: dict[str, Any] = {}
    for year in ("2022", "2023", "2024"):
        base = selected["base_cost"][year]
        stress = selected["stress_1_50x_cost"][year]
        year_checks[year] = {
            "minimum_60_trades": base["trades"] >= 60,
            "positive_base_expectancy": (
                base["net_expectancy_r"] is not None and float(base["net_expectancy_r"]) > 0
            ),
            "profit_factor_ge_1_15": (
                base["profit_factor"] is not None and float(base["profit_factor"]) >= 1.15
            ),
            "positive_stress_expectancy": (
                stress["net_expectancy_r"] is not None and float(stress["net_expectancy_r"]) > 0
            ),
            "average_monthly_r_ge_10": (
                base["average_monthly_r"] is not None and float(base["average_monthly_r"]) >= 10
            ),
            "positive_median_month": (
                base["median_monthly_r"] is not None and float(base["median_monthly_r"]) > 0
            ),
            "positive_month_pct_ge_55": (
                base["positive_month_pct"] is not None and float(base["positive_month_pct"]) >= 55
            ),
        }
    return {
        "passed": all(all(checks.values()) for checks in year_checks.values()),
        "year_checks": year_checks,
        "holdout_open_authorized": False,
    }


def _calibration(
    predictions: Sequence[Prediction],
) -> dict[str, Any]:
    if not predictions:
        return {}
    ordered = sorted(
        predictions,
        key=lambda prediction: prediction.predicted_net_r,
    )
    quintiles: list[dict[str, Any]] = []
    for index, members in enumerate(
        np.array_split(np.asarray(ordered, dtype=object), 5),
    ):
        values = list(members)
        if not values:
            continue
        quintiles.append(
            {
                "quintile": index + 1,
                "signals": len(values),
                "mean_predicted_net_r": round(
                    statistics.mean(item.predicted_net_r for item in values),
                    6,
                ),
                "mean_realized_net_r": round(
                    statistics.mean(item.example.trade.net_r for item in values),
                    6,
                ),
            },
        )
    predicted = np.asarray(
        [prediction.predicted_net_r for prediction in predictions],
        dtype=np.float64,
    )
    realized = np.asarray(
        [prediction.example.trade.net_r for prediction in predictions],
        dtype=np.float64,
    )
    correlation = (
        float(np.corrcoef(predicted, realized)[0, 1])
        if float(np.std(predicted)) > 0 and float(np.std(realized)) > 0
        else 0.0
    )
    return {
        "pearson_correlation": round(correlation, 6),
        "mean_squared_error": round(
            float(np.mean((predicted - realized) ** 2)),
            6,
        ),
        "quintiles": quintiles,
    }


def _coefficient_stability(
    snapshots: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not snapshots:
        return {}
    return {
        feature: _coefficient_summary(
            [float(snapshot["standardized_coefficients"][feature]) for snapshot in snapshots],
        )
        for feature in FEATURE_NAMES
    }


def _coefficient_summary(values: Sequence[float]) -> dict[str, Any]:
    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in values]
    return {
        "mean": round(statistics.mean(values), 8),
        "standard_deviation": round(statistics.pstdev(values), 8),
        "positive_month_pct": round(
            sum(value > 0 for value in values) / len(values) * 100,
            3,
        ),
        "sign_changes": sum(
            current != previous for previous, current in zip(signs, signs[1:], strict=False)
        ),
    }


def _group_report(
    predictions: Sequence[Prediction],
    attribute: str,
) -> dict[str, Any]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for prediction in predictions:
        key = str(getattr(prediction.example, attribute))
        grouped[key].append(prediction.example.trade)
    return {
        key: _compact_metrics(
            trades,
            calendar_start=date(2022, 1, 1),
            calendar_end=date(2025, 1, 1),
        )
        for key, trades in sorted(grouped.items())
    }


def _manager_funnel(
    predictions: Sequence[Prediction],
) -> dict[str, int]:
    return {
        manager: sum(prediction.example.manager == manager for prediction in predictions)
        for manager in MANAGERS
    }


def _feature_coverage(
    examples: Sequence[Example],
) -> dict[str, float]:
    matrix = np.asarray(
        [example.features for example in examples],
        dtype=np.float64,
    )
    return {
        name: round(float(np.isfinite(matrix[:, index]).mean() * 100), 3)
        for index, name in enumerate(FEATURE_NAMES)
    }


def _write_prediction_cache(
    predictions: Sequence[Prediction],
    destination: Path,
) -> None:
    rows = [
        {
            "playbook": prediction.example.trade.playbook,
            "instrument": prediction.example.instrument,
            "cluster": prediction.example.cluster,
            "pattern": prediction.example.pattern,
            "side": prediction.example.trade.side,
            "signal_time": prediction.example.trade.signal_time.isoformat(),
            "entry_time": prediction.example.trade.entry_time.isoformat(),
            "exit_time": prediction.example.trade.exit_time.isoformat(),
            "manager": prediction.example.manager,
            "model_month": prediction.model_month,
            "training_examples": prediction.training_examples,
            "predicted_net_r": prediction.predicted_net_r,
            "realized_net_r": prediction.example.trade.net_r,
            "realized_stress_net_r": prediction.example.stress_trade.net_r,
        }
        for prediction in predictions
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    pd.DataFrame(rows).to_csv(
        temporary,
        index=False,
        compression="gzip",
    )
    temporary.replace(destination)


def _number(row: pd.Series[Any], key: str) -> float:
    value = row.get(key)
    return float(value) if value is not None and pd.notna(value) else math.nan


def _timestamp(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise RuntimeError(f"Timezone-naive timestamp in cache: {value}")
    return timestamp.to_pydatetime().astimezone(UTC)


def _threshold_label(value: float) -> str:
    sign = "M" if value < 0 else "P"
    return f"PREDICTED_R_{sign}{abs(value):.2f}".replace(".", "_")


def _phase(name: str, started: float) -> None:
    print(
        f"{name} elapsed={time.perf_counter() - started:.3f}s",
        flush=True,
        file=__import__("sys").stderr,
    )


if __name__ == "__main__":
    main()
