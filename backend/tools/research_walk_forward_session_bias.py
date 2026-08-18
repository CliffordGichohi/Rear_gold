from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
from explore_session_playbooks import Bar, Day, _build_days
from research_cross_market_auction_micro_execution import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
    _contiguous_momentum,
    _coverage,
)
from research_daily_session_playbooks import _atr_by_close

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory

FEATURE_NAMES = (
    "FUNDAMENTAL_SCORE",
    "FUNDAMENTAL_CONFIDENCE",
    "FUNDAMENTAL_COVERAGE",
    "REAL_YIELD_EVIDENCE",
    "TWO_YEAR_YIELD_EVIDENCE",
    "USD_EVIDENCE",
    "FED_PATH_EVIDENCE",
    "INFLATION_REGIME_EVIDENCE",
    "GROWTH_REGIME_EVIDENCE",
    "LABOUR_REGIME_EVIDENCE",
    "POSITIONING_FLOW_EVIDENCE",
    "CATALYST_SURPRISE_EVIDENCE",
    "GOLD_60M_MOMENTUM_ATR",
    "GOLD_4H_MOMENTUM_ATR",
    "ASIA_RETURN_ATR",
    "ASIA_RANGE_ATR",
    "ASIA_CLOSE_LOCATION",
    "ASIA_RANGE_PERCENTILE_120",
    "EURUSD_60M_MOMENTUM_ATR",
    "EURUSD_4H_MOMENTUM_ATR",
    "SILVER_60M_MOMENTUM_ATR",
    "SILVER_4H_MOMENTUM_ATR",
    "PRIOR_LONDON_LARGER_EXCURSION",
    "DAY_OF_WEEK_SIN",
    "DAY_OF_WEEK_COS",
)
RIDGE_PENALTY = 4.0
MINIMUM_TRAINING_SESSIONS = 120


@dataclass(frozen=True, slots=True)
class SessionExample:
    session_date: date
    decision_at: datetime
    features: tuple[float, ...]
    larger_excursion_direction: int
    london_close_return_atr: float
    upward_excursion_atr: float
    downward_excursion_atr: float
    first_asia_break: int | None


@dataclass(frozen=True, slots=True)
class RidgeLogisticModel:
    means: np.ndarray
    scales: np.ndarray
    coefficients: np.ndarray
    iterations: int

    def predict(
        self,
        features: Sequence[float],
    ) -> tuple[float, np.ndarray, np.ndarray]:
        raw = np.asarray(features, dtype=np.float64)
        imputed = np.where(np.isfinite(raw), raw, self.means)
        standardized = np.clip(
            (imputed - self.means) / self.scales,
            -6.0,
            6.0,
        )
        contributions = self.coefficients[1:] * standardized
        logit = float(self.coefficients[0] + contributions.sum())
        return _sigmoid(logit), standardized, contributions


@dataclass(frozen=True, slots=True)
class Prediction:
    example: SessionExample
    probability_up: float
    predicted_direction: int
    confidence: float
    training_sessions: int
    model_month: str
    top_contributions: tuple[dict[str, float | str], ...]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    run_started = time.perf_counter()
    query = {
        "load_start": start - timedelta(days=8),
        "load_end": end,
    }
    async with session_factory() as session:
        gold_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "XAUUSD", **query},
                )
            ).mappings()
        )
        _phase("GOLD_LOADED", run_started)
        eurusd_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "EURUSD", **query},
                )
            ).mappings()
        )
        _phase("EURUSD_LOADED", run_started)
        silver_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "XAGUSD", **query},
                )
            ).mappings()
        )
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)
        _phase("SILVER_AND_FUNDAMENTALS_LOADED", run_started)

    days = _build_days(gold_bars, start=start, end=end)
    examples = _examples(
        days,
        gold_bars=gold_bars,
        eurusd_bars=eurusd_bars,
        silver_bars=silver_bars,
        fundamental_inputs=fundamental_inputs,
    )
    _phase("POINT_IN_TIME_EXAMPLES_BUILT", run_started)
    predictions, model_snapshots = _walk_forward_predictions(examples)
    _phase("WALK_FORWARD_MODELS_COMPLETE", run_started)

    report = {
        "contract": {
            "version": "WALK_FORWARD_SESSION_BIAS_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "eligible_examples": len(examples),
            "walk_forward_predictions": len(predictions),
            "decision_clock": (
                "DST-aware London open. The Asian range has completed and "
                "only bars/evidence available by that timestamp are eligible."
            ),
            "target": (
                "Direction of the larger London-session excursion from the "
                "London open; this is a bias target, not a fill or trade."
            ),
            "model": (
                "Standardized ridge logistic regression with a fixed L2 "
                "penalty. It is refit once per calendar month using only "
                "earlier completed months."
            ),
            "ridge_penalty": RIDGE_PENALTY,
            "minimum_training_sessions": MINIMUM_TRAINING_SESSIONS,
            "thresholds": (
                "All predictions, probability at least 55/45, and probability "
                "at least 60/40 were declared before evaluating results."
            ),
            "development_policy": (
                "All pre-2025 results are development diagnostics because "
                "2023-2024 have already informed earlier research. Calendar "
                "2025 remains the only untouched holdout and is not loaded."
            ),
            "interpretation": (
                "This diagnostic has no entry, stop, target, cost, position "
                "size, or P&L. A useful bias must still pass a separate costed "
                "execution test."
            ),
        },
        "data_coverage": {
            "XAUUSD_5M": _coverage(gold_bars),
            "EURUSD_5M": _coverage(eurusd_bars),
            "XAGUSD_5M": _coverage(silver_bars),
            "feature_non_missing_pct": _feature_coverage(examples),
        },
        "features": list(FEATURE_NAMES),
        "class_balance": _class_balance(examples),
        "metrics": {
            label: _prediction_metrics(predictions, minimum_confidence=threshold)
            for label, threshold in (
                ("ALL", 0.0),
                ("PROBABILITY_55", 0.10),
                ("PROBABILITY_60", 0.20),
            )
        },
        "coefficient_stability": _coefficient_stability(model_snapshots),
        "model_snapshots": model_snapshots,
        "predictions": [_prediction_payload(item) for item in predictions],
        "elapsed_seconds": round(time.perf_counter() - run_started, 3),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _examples(
    days: Sequence[Day],
    *,
    gold_bars: Sequence[Bar],
    eurusd_bars: Sequence[Bar],
    silver_bars: Sequence[Bar],
    fundamental_inputs: Any,
) -> list[SessionExample]:
    series = {
        "XAUUSD": gold_bars,
        "EURUSD": eurusd_bars,
        "XAGUSD": silver_bars,
    }
    clocks = {
        instrument: [bar.close_time for bar in bars]
        for instrument, bars in series.items()
    }
    atrs = {
        instrument: _atr_by_close(bars)
        for instrument, bars in series.items()
    }
    asia_range_history: list[float] = []
    prior_larger_excursion = math.nan
    output: list[SessionExample] = []
    for day in days:
        decision_at = day.london[0].open_time
        gold_atr = atrs["XAUUSD"].get(decision_at)
        if gold_atr is None or gold_atr <= 0:
            continue
        state = fundamental_inputs.state_at(
            decision_at,
            compute_data_hash=False,
        )
        components = {
            component.code: _effective_direction(component)
            for component in state.components
            if component.epistemic_status != "UNKNOWN"
        }
        asia_open = day.asia[0].open
        asia_close = day.asia[-1].close
        asia_high = max(bar.high for bar in day.asia)
        asia_low = min(bar.low for bar in day.asia)
        asia_range = asia_high - asia_low
        close_location = (
            (asia_close - asia_low) / asia_range * 2.0 - 1.0
            if asia_range > 0
            else 0.0
        )
        range_percentile = _trailing_percentile(
            asia_range,
            asia_range_history[-120:],
        )
        london_open = day.london[0].open
        london_close = day.london[-1].close
        london_high = max(bar.high for bar in day.london)
        london_low = min(bar.low for bar in day.london)
        upward = (london_high - london_open) / gold_atr
        downward = (london_open - london_low) / gold_atr
        larger_direction = 1 if upward > downward else -1
        feature_values = (
            state.directional_score / 100.0,
            state.confidence / 100.0,
            state.coverage / 100.0,
            components.get("REAL_YIELD", math.nan),
            components.get("TWO_YEAR_YIELD", math.nan),
            components.get("USD", math.nan),
            components.get("FED_PATH", math.nan),
            components.get("INFLATION_REGIME", math.nan),
            components.get("GROWTH_REGIME", math.nan),
            components.get("LABOUR_REGIME", math.nan),
            components.get("POSITIONING_FLOW", math.nan),
            components.get("CATALYST_SURPRISE", math.nan),
            _momentum(
                series,
                clocks,
                atrs,
                instrument="XAUUSD",
                as_of=decision_at,
                lookback=12,
            ),
            _momentum(
                series,
                clocks,
                atrs,
                instrument="XAUUSD",
                as_of=decision_at,
                lookback=48,
            ),
            (asia_close - asia_open) / gold_atr,
            asia_range / gold_atr,
            close_location,
            range_percentile,
            _momentum(
                series,
                clocks,
                atrs,
                instrument="EURUSD",
                as_of=decision_at,
                lookback=12,
            ),
            _momentum(
                series,
                clocks,
                atrs,
                instrument="EURUSD",
                as_of=decision_at,
                lookback=48,
            ),
            _momentum(
                series,
                clocks,
                atrs,
                instrument="XAGUSD",
                as_of=decision_at,
                lookback=12,
            ),
            _momentum(
                series,
                clocks,
                atrs,
                instrument="XAGUSD",
                as_of=decision_at,
                lookback=48,
            ),
            prior_larger_excursion,
            math.sin(2.0 * math.pi * day.session_date.weekday() / 5.0),
            math.cos(2.0 * math.pi * day.session_date.weekday() / 5.0),
        )
        output.append(
            SessionExample(
                session_date=day.session_date,
                decision_at=decision_at,
                features=feature_values,
                larger_excursion_direction=larger_direction,
                london_close_return_atr=(london_close - london_open) / gold_atr,
                upward_excursion_atr=upward,
                downward_excursion_atr=downward,
                first_asia_break=_first_asia_break(
                    day.london,
                    asia_high=asia_high,
                    asia_low=asia_low,
                ),
            )
        )
        asia_range_history.append(asia_range)
        prior_larger_excursion = float(larger_direction)
    return output


def _effective_direction(component: Any) -> float:
    if component.weight <= 0:
        return float(component.direction)
    return float(component.contribution / component.weight)


def _momentum(
    series: dict[str, Sequence[Bar]],
    clocks: dict[str, Sequence[datetime]],
    atrs: dict[str, dict[datetime, float]],
    *,
    instrument: str,
    as_of: datetime,
    lookback: int,
) -> float:
    atr = atrs[instrument].get(as_of)
    if atr is None or atr <= 0:
        return math.nan
    value = _contiguous_momentum(
        series[instrument],
        close_times=clocks[instrument],
        as_of=as_of,
        lookback=lookback,
        atr=atr,
    )
    return value if value is not None else math.nan


def _trailing_percentile(value: float, history: Sequence[float]) -> float:
    if len(history) < 20:
        return math.nan
    return sum(prior <= value for prior in history) / len(history)


def _first_asia_break(
    bars: Sequence[Bar],
    *,
    asia_high: float,
    asia_low: float,
) -> int | None:
    for bar in bars:
        broke_high = bar.high > asia_high
        broke_low = bar.low < asia_low
        if broke_high and broke_low:
            return None
        if broke_high:
            return 1
        if broke_low:
            return -1
    return None


def _walk_forward_predictions(
    examples: Sequence[SessionExample],
) -> tuple[list[Prediction], list[dict[str, Any]]]:
    by_month: dict[tuple[int, int], list[SessionExample]] = defaultdict(list)
    for example in examples:
        by_month[(example.session_date.year, example.session_date.month)].append(
            example
        )
    predictions: list[Prediction] = []
    snapshots: list[dict[str, Any]] = []
    for year, month in sorted(by_month):
        month_start = date(year, month, 1)
        training = [
            example
            for example in examples
            if example.session_date < month_start
        ]
        if len(training) < MINIMUM_TRAINING_SESSIONS:
            continue
        model = _fit_model(training)
        model_month = f"{year:04d}-{month:02d}"
        snapshots.append(
            {
                "model_month": model_month,
                "training_sessions": len(training),
                "training_first": training[0].session_date.isoformat(),
                "training_last": training[-1].session_date.isoformat(),
                "iterations": model.iterations,
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
        )
        for example in by_month[(year, month)]:
            probability, _, contributions = model.predict(example.features)
            predicted_direction = 1 if probability >= 0.5 else -1
            ranked = sorted(
                zip(FEATURE_NAMES, contributions, strict=True),
                key=lambda item: abs(float(item[1])),
                reverse=True,
            )[:5]
            predictions.append(
                Prediction(
                    example=example,
                    probability_up=probability,
                    predicted_direction=predicted_direction,
                    confidence=abs(probability - 0.5) * 2.0,
                    training_sessions=len(training),
                    model_month=model_month,
                    top_contributions=tuple(
                        {
                            "feature": name,
                            "logit_contribution": round(float(value), 8),
                        }
                        for name, value in ranked
                    ),
                )
            )
    return predictions, snapshots


def _fit_model(examples: Sequence[SessionExample]) -> RidgeLogisticModel:
    matrix = np.asarray([example.features for example in examples], dtype=np.float64)
    targets = np.asarray(
        [example.larger_excursion_direction > 0 for example in examples],
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
    imputed = np.where(np.isfinite(matrix), matrix, means)
    scales = np.std(imputed, axis=0)
    scales = np.where(scales >= 1e-8, scales, 1.0)
    standardized = np.clip((imputed - means) / scales, -6.0, 6.0)
    design = np.column_stack((np.ones(len(standardized)), standardized))
    coefficients = np.zeros(design.shape[1], dtype=np.float64)
    penalty = np.eye(design.shape[1], dtype=np.float64) * RIDGE_PENALTY
    penalty[0, 0] = 0.0
    iterations = 0
    for iteration in range(1, 101):
        logits = design @ coefficients
        probabilities = np.asarray([_sigmoid(value) for value in logits])
        variance = np.clip(probabilities * (1.0 - probabilities), 1e-6, None)
        gradient = (
            design.T @ (probabilities - targets)
            + penalty @ coefficients
        )
        hessian = design.T @ (design * variance[:, None]) + penalty
        step = np.linalg.solve(hessian, gradient)
        coefficients -= step
        iterations = iteration
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return RidgeLogisticModel(
        means=means,
        scales=scales,
        coefficients=coefficients,
        iterations=iterations,
    )


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def _prediction_metrics(
    predictions: Sequence[Prediction],
    *,
    minimum_confidence: float,
) -> dict[str, Any]:
    by_year: dict[int, list[Prediction]] = defaultdict(list)
    for prediction in predictions:
        if prediction.confidence >= minimum_confidence:
            by_year[prediction.example.session_date.year].append(prediction)
    output = {
        str(year): _period_metrics(members)
        for year, members in sorted(by_year.items())
    }
    output["ALL_AVAILABLE"] = _period_metrics(
        [
            prediction
            for prediction in predictions
            if prediction.confidence >= minimum_confidence
        ]
    )
    return output


def _period_metrics(predictions: Sequence[Prediction]) -> dict[str, Any]:
    if not predictions:
        return {
            "observations": 0,
            "directional_accuracy_pct": None,
            "accuracy_wilson_95ci_pct": None,
            "mean_excursion_advantage_atr": None,
            "mean_directional_close_atr": None,
            "mean_selected_mfe_atr": None,
            "mean_selected_mae_atr": None,
            "first_asia_break_accuracy_pct": None,
            "brier_score": None,
        }
    correct = sum(
        prediction.predicted_direction
        == prediction.example.larger_excursion_direction
        for prediction in predictions
    )
    advantage = [
        prediction.predicted_direction
        * (
            prediction.example.upward_excursion_atr
            - prediction.example.downward_excursion_atr
        )
        for prediction in predictions
    ]
    directional_close = [
        prediction.predicted_direction
        * prediction.example.london_close_return_atr
        for prediction in predictions
    ]
    selected_mfe = [
        (
            prediction.example.upward_excursion_atr
            if prediction.predicted_direction > 0
            else prediction.example.downward_excursion_atr
        )
        for prediction in predictions
    ]
    selected_mae = [
        (
            prediction.example.downward_excursion_atr
            if prediction.predicted_direction > 0
            else prediction.example.upward_excursion_atr
        )
        for prediction in predictions
    ]
    first_break = [
        prediction
        for prediction in predictions
        if prediction.example.first_asia_break is not None
    ]
    brier = statistics.mean(
        (
            prediction.probability_up
            - (1.0 if prediction.example.larger_excursion_direction > 0 else 0.0)
        )
        ** 2
        for prediction in predictions
    )
    return {
        "observations": len(predictions),
        "directional_accuracy_pct": round(correct / len(predictions) * 100, 4),
        "accuracy_wilson_95ci_pct": [
            round(value * 100, 4)
            for value in _wilson_interval(correct, len(predictions))
        ],
        "mean_excursion_advantage_atr": round(statistics.mean(advantage), 6),
        "mean_directional_close_atr": round(
            statistics.mean(directional_close),
            6,
        ),
        "mean_selected_mfe_atr": round(statistics.mean(selected_mfe), 6),
        "mean_selected_mae_atr": round(statistics.mean(selected_mae), 6),
        "first_asia_break_accuracy_pct": (
            round(
                sum(
                    prediction.predicted_direction
                    == prediction.example.first_asia_break
                    for prediction in first_break
                )
                / len(first_break)
                * 100,
                4,
            )
            if first_break
            else None
        ),
        "brier_score": round(brier, 6),
    }


def _wilson_interval(successes: int, observations: int) -> tuple[float, float]:
    if observations == 0:
        return 0.0, 0.0
    z = 1.959963984540054
    proportion = successes / observations
    denominator = 1.0 + z * z / observations
    centre = (proportion + z * z / (2.0 * observations)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / observations
            + z * z / (4.0 * observations * observations)
        )
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _feature_coverage(
    examples: Sequence[SessionExample],
) -> dict[str, float]:
    if not examples:
        return {name: 0.0 for name in FEATURE_NAMES}
    matrix = np.asarray([example.features for example in examples], dtype=np.float64)
    return {
        name: round(float(np.isfinite(matrix[:, index]).mean() * 100), 3)
        for index, name in enumerate(FEATURE_NAMES)
    }


def _class_balance(examples: Sequence[SessionExample]) -> dict[str, Any]:
    by_year: dict[int, list[SessionExample]] = defaultdict(list)
    for example in examples:
        by_year[example.session_date.year].append(example)
    return {
        str(year): {
            "sessions": len(members),
            "up_larger_excursion_pct": round(
                sum(item.larger_excursion_direction > 0 for item in members)
                / len(members)
                * 100,
                4,
            ),
        }
        for year, members in sorted(by_year.items())
    }


def _coefficient_stability(
    snapshots: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not snapshots:
        return {}
    output: dict[str, Any] = {}
    for feature in FEATURE_NAMES:
        values = [
            float(snapshot["standardized_coefficients"][feature])
            for snapshot in snapshots
        ]
        signs = [1 if value > 0 else -1 if value < 0 else 0 for value in values]
        sign_changes = sum(
            current != prior
            for prior, current in zip(signs, signs[1:], strict=False)
        )
        output[feature] = {
            "mean": round(statistics.mean(values), 8),
            "standard_deviation": round(statistics.pstdev(values), 8),
            "positive_month_pct": round(
                sum(value > 0 for value in values) / len(values) * 100,
                3,
            ),
            "sign_changes": sign_changes,
        }
    return output


def _prediction_payload(prediction: Prediction) -> dict[str, Any]:
    example = prediction.example
    return {
        "session_date": example.session_date.isoformat(),
        "decision_at": example.decision_at.isoformat(),
        "model_month": prediction.model_month,
        "training_sessions": prediction.training_sessions,
        "probability_up": round(prediction.probability_up, 8),
        "confidence": round(prediction.confidence, 8),
        "predicted_direction": prediction.predicted_direction,
        "actual_larger_excursion_direction": example.larger_excursion_direction,
        "london_close_return_atr": round(example.london_close_return_atr, 8),
        "upward_excursion_atr": round(example.upward_excursion_atr, 8),
        "downward_excursion_atr": round(example.downward_excursion_atr, 8),
        "first_asia_break": example.first_asia_break,
        "top_contributions": list(prediction.top_contributions),
    }


def _phase(name: str, started: float) -> None:
    print(
        json.dumps(
            {
                "phase": name,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
