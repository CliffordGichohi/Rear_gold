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
from zoneinfo import ZoneInfo

import numpy as np
from explore_session_playbooks import _build_days
from research_cross_market_auction_micro_execution import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
    _coverage,
    _five_minute_bars_from_minutes,
)
from research_daily_session_playbooks import Trade
from research_fundamental_state_transitions import (
    FundamentalRecord,
    _fundamental_records,
)
from research_liquidity_level_state_machine import (
    _enrich_cross_market,
    _liquidity_signals,
    _managed_results,
)
from research_one_minute_auction_execution import ONE_MINUTE_SQL
from research_session_state_transitions import _compact_metrics

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
RIDGE_PENALTY = 8.0
MINIMUM_TRAINING_SIGNALS = 150
TARGET_MANAGER = "FIXED_2_00R"
PLAYBOOKS = (
    "LONDON|ACCEPTED_RETEST|ASIA_RANGE",
    "LONDON|ACCEPTED_RETEST|PRIOR_24H",
    "LONDON|FAST_REJECTION|ASIA_RANGE",
    "LONDON|FAST_REJECTION|PRIOR_24H",
    "NEW_YORK|ACCEPTED_RETEST|ASIA_RANGE",
    "NEW_YORK|ACCEPTED_RETEST|LONDON_HANDOVER",
    "NEW_YORK|FAST_REJECTION|ASIA_RANGE",
    "NEW_YORK|FAST_REJECTION|LONDON_HANDOVER",
    "NEW_YORK|FAST_REJECTION|PRIOR_24H",
    "NEW_YORK|HANDOVER_CONFIRMATION|ASIA_RANGE",
    "NEW_YORK|HANDOVER_REJECTION|ASIA_RANGE",
)
REACTION_FUNCTIONS = (
    "FINANCIAL_STRESS_FOCUS",
    "INFLATION_FOCUS",
    "GROWTH_LABOUR_FOCUS",
    "MIXED_MACRO_REACTION_FUNCTION",
    "EVENT_SURPRISE_WITH_PARTIAL_MACRO",
    "UNKNOWN_WITHOUT_EVENT_AND_REGIME_CORE",
)
CONTINUOUS_FEATURES = (
    "SIDE_LONG",
    "MINUTES_IN_SESSION",
    "BREACH_DEPTH_ATR",
    "ASIA_RANGE_PERCENTILE",
    "RELATIVE_VOLUME",
    "RELATIVE_SPREAD",
    "ESTIMATED_COST_R",
    "LEVEL_CONFLUENCE",
    "SIGNED_FUNDAMENTAL_SCORE",
    "FUNDAMENTAL_CONFIDENCE",
    "FUNDAMENTAL_COVERAGE",
    "REAL_YIELD_ALIGNED",
    "TWO_YEAR_YIELD_ALIGNED",
    "USD_ALIGNED",
    "FED_PATH_ALIGNED",
    "INFLATION_REGIME_ALIGNED",
    "GROWTH_REGIME_ALIGNED",
    "LABOUR_REGIME_ALIGNED",
    "POSITIONING_FLOW_ALIGNED",
    "CATALYST_SURPRISE_ALIGNED",
    "EURUSD_60M_ALIGNED_ATR",
    "SILVER_60M_ALIGNED_ATR",
    "CROWDING_SUPPORT",
)
FEATURE_NAMES = (
    *CONTINUOUS_FEATURES,
    *(f"PLAYBOOK::{name}" for name in PLAYBOOKS),
    *(f"REACTION::{name}" for name in REACTION_FUNCTIONS),
)


@dataclass(frozen=True, slots=True)
class ExecutionExample:
    record: FundamentalRecord
    stress_trade: Trade
    features: tuple[float, ...]

    @property
    def trade(self) -> Trade:
        return self.record.managed.trade


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
class ExecutionPrediction:
    example: ExecutionExample
    predicted_net_r: float
    model_month: str
    training_signals: int
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

    started = time.perf_counter()
    query = {
        "load_start": start - timedelta(days=8),
        "load_end": end,
    }
    async with session_factory() as session:
        minute_bars = _bars(
            (await session.execute(ONE_MINUTE_SQL, query)).mappings()
        )
        five_minute_gold = _five_minute_bars_from_minutes(minute_bars)
        _phase("GOLD_LOADED", started)
        eurusd_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "EURUSD", **query},
                )
            ).mappings()
        )
        _phase("EURUSD_LOADED", started)
        silver_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "XAGUSD", **query},
                )
            ).mappings()
        )
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)
        _phase("SILVER_AND_FUNDAMENTALS_LOADED", started)

    days = _build_days(five_minute_gold, start=start, end=end)
    signals = _enrich_cross_market(
        _liquidity_signals(
            days,
            minute_bars=minute_bars,
            five_minute_gold=five_minute_gold,
        ),
        eurusd_bars=eurusd_bars,
        silver_bars=silver_bars,
    )
    managed = _managed_results(signals, minute_bars=minute_bars)
    records = _fundamental_records(
        managed,
        fundamental_inputs=fundamental_inputs,
    )
    examples = _execution_examples(records)
    _phase("EXECUTION_EXAMPLES_BUILT", started)
    predictions, snapshots = _walk_forward_predictions(examples)
    _phase("WALK_FORWARD_MODELS_COMPLETE", started)

    threshold_reports = {
        label: _threshold_report(
            predictions,
            minimum_prediction=threshold,
        )
        for label, threshold in (
            ("PREDICTED_R_GT_0", 0.0),
            ("PREDICTED_R_GE_0_10", 0.10),
            ("PREDICTED_R_GE_0_20", 0.20),
        )
    }
    baseline = _threshold_report(
        predictions,
        minimum_prediction=-math.inf,
    )
    report = {
        "contract": {
            "version": "WALK_FORWARD_LIQUIDITY_EXECUTION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "source_signals": len(signals),
            "target_manager": TARGET_MANAGER,
            "eligible_examples": len(examples),
            "walk_forward_predictions": len(predictions),
            "model": (
                "Standardized ridge regression predicts the realized net R of "
                "the fixed 2R execution manager. It refits at each month "
                "boundary using only earlier completed months."
            ),
            "ridge_penalty": RIDGE_PENALTY,
            "minimum_training_signals": MINIMUM_TRAINING_SIGNALS,
            "declared_thresholds": [0.0, 0.10, 0.20],
            "execution": (
                "Entry, structural stop, 2R target, 180-minute timeout, "
                "same-minute stop-first ambiguity, and observed spread remain "
                "unchanged from the deterministic liquidity state machine."
            ),
            "friction": (
                "$0.05/oz adverse slippage per side and $7/lot round-turn "
                "commission, with the exact same selected signals also tested "
                "at 1.50 times total friction."
            ),
            "portfolio": (
                "One position at a time; simultaneous signals ranked by "
                "predicted net R; no new signal after realized daily P&L "
                "reaches -2R."
            ),
            "development_policy": (
                "All pre-2025 results are development diagnostics. Calendar "
                "2025 remains the untouched holdout and is not loaded."
            ),
            "monthly_hurdle": (
                "At 1% account risk, $1,000 average monthly P&L on $10,000 "
                "requires approximately 10R per calendar month."
            ),
            "promotion_rule": (
                "No holdout access merely because one threshold ranks first. "
                "A candidate must have positive annual expectancy in 2022, "
                "2023, and 2024, survive 1.50x costs, retain PF above 1.15, "
                "and have at least 15 annual trades."
            ),
        },
        "data_coverage": {
            "XAUUSD_1M": {
                "bars": len(minute_bars),
                "first_open": (
                    minute_bars[0].open_time.isoformat()
                    if minute_bars
                    else None
                ),
                "last_close": (
                    minute_bars[-1].close_time.isoformat()
                    if minute_bars
                    else None
                ),
            },
            "EURUSD_5M": _coverage(eurusd_bars),
            "XAGUSD_5M": _coverage(silver_bars),
            "feature_non_missing_pct": _feature_coverage(examples),
        },
        "features": list(FEATURE_NAMES),
        "signal_funnel": _signal_funnel(examples),
        "baseline_all_walk_forward_signals": baseline,
        "thresholds": threshold_reports,
        "calibration": _calibration(predictions),
        "coefficient_stability": _coefficient_stability(snapshots),
        "model_snapshots": snapshots,
        "predictions": [_prediction_payload(item) for item in predictions],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _execution_examples(
    records: Sequence[FundamentalRecord],
) -> list[ExecutionExample]:
    base: dict[tuple[Any, ...], FundamentalRecord] = {}
    stress: dict[tuple[Any, ...], Trade] = {}
    for record in records:
        managed = record.managed
        if managed.manager != TARGET_MANAGER:
            continue
        key = _signal_key(managed.trade)
        if managed.cost_multiplier == 1.0:
            if key in base:
                raise RuntimeError(f"Duplicate base execution record: {key}")
            base[key] = record
        elif managed.cost_multiplier == 1.5:
            if key in stress:
                raise RuntimeError(f"Duplicate stress execution record: {key}")
            stress[key] = managed.trade
    if set(base) != set(stress):
        raise RuntimeError("Base and 1.50x-cost execution keys do not match")
    return [
        ExecutionExample(
            record=record,
            stress_trade=stress[key],
            features=_feature_values(record),
        )
        for key, record in sorted(
            base.items(),
            key=lambda item: (
                item[1].managed.trade.entry_time,
                item[1].managed.trade.playbook,
            ),
        )
    ]


def _signal_key(trade: Trade) -> tuple[Any, ...]:
    return (
        trade.session_date,
        trade.playbook,
        trade.side,
        trade.signal_time,
        trade.entry_time,
    )


def _feature_values(record: FundamentalRecord) -> tuple[float, ...]:
    signal = record.managed.signal
    side_sign = 1.0 if signal.side == "LONG" else -1.0
    crowding = record.crowding_percentile
    crowding_support = (
        -side_sign * (crowding - 50.0) / 50.0
        if crowding is not None
        else math.nan
    )
    continuous = (
        1.0 if signal.side == "LONG" else 0.0,
        _minutes_in_session(signal.signal_time, str(signal.evidence["session"]))
        / 240.0,
        _evidence(signal.evidence, "breach_depth_atr"),
        _evidence(signal.evidence, "asia_range_percentile") / 100.0,
        _evidence(signal.evidence, "relative_volume"),
        _evidence(signal.evidence, "relative_spread"),
        _evidence(signal.evidence, "estimated_cost_r"),
        _evidence(signal.evidence, "level_confluence"),
        record.signed_score / 100.0,
        record.confidence / 100.0,
        record.coverage / 100.0,
        _component(record, "REAL_YIELD"),
        _component(record, "TWO_YEAR_YIELD"),
        _component(record, "USD"),
        _component(record, "FED_PATH"),
        _component(record, "INFLATION_REGIME"),
        _component(record, "GROWTH_REGIME"),
        _component(record, "LABOUR_REGIME"),
        _component(record, "POSITIONING_FLOW"),
        _component(record, "CATALYST_SURPRISE"),
        _evidence(signal.evidence, "eurusd_60m_signed_atr"),
        _evidence(signal.evidence, "silver_60m_signed_atr"),
        crowding_support,
    )
    playbooks = tuple(
        1.0 if signal.playbook == playbook else 0.0
        for playbook in PLAYBOOKS
    )
    reactions = tuple(
        1.0 if record.reaction_function == reaction else 0.0
        for reaction in REACTION_FUNCTIONS
    )
    values = (*continuous, *playbooks, *reactions)
    if len(values) != len(FEATURE_NAMES):
        raise RuntimeError("Execution feature contract is inconsistent")
    return values


def _minutes_in_session(timestamp: datetime, session_name: str) -> float:
    zone = LONDON if session_name == "LONDON" else NEW_YORK
    local = timestamp.astimezone(zone)
    session_open = local.replace(hour=8, minute=0, second=0, microsecond=0)
    return max(0.0, (local - session_open).total_seconds() / 60.0)


def _evidence(evidence: dict[str, Any], key: str) -> float:
    value = evidence.get(key)
    return float(value) if value is not None else math.nan


def _component(record: FundamentalRecord, code: str) -> float:
    value = record.signed_components.get(code)
    return float(value) if value is not None else math.nan


def _walk_forward_predictions(
    examples: Sequence[ExecutionExample],
) -> tuple[list[ExecutionPrediction], list[dict[str, Any]]]:
    by_month: dict[tuple[int, int], list[ExecutionExample]] = defaultdict(list)
    for example in examples:
        day = example.trade.session_date
        by_month[(day.year, day.month)].append(example)
    predictions: list[ExecutionPrediction] = []
    snapshots: list[dict[str, Any]] = []
    for year, month in sorted(by_month):
        month_start = date(year, month, 1)
        training = [
            example
            for example in examples
            if example.trade.session_date < month_start
        ]
        if len(training) < MINIMUM_TRAINING_SIGNALS:
            continue
        model = _fit_model(training)
        model_month = f"{year:04d}-{month:02d}"
        snapshots.append(
            {
                "model_month": model_month,
                "training_signals": len(training),
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
        )
        for example in by_month[(year, month)]:
            predicted_net_r, contributions = model.predict(example.features)
            ranked = sorted(
                zip(FEATURE_NAMES, contributions, strict=True),
                key=lambda item: abs(float(item[1])),
                reverse=True,
            )[:5]
            predictions.append(
                ExecutionPrediction(
                    example=example,
                    predicted_net_r=predicted_net_r,
                    model_month=model_month,
                    training_signals=len(training),
                    top_contributions=tuple(
                        {
                            "feature": name,
                            "predicted_r_contribution": round(float(value), 8),
                        }
                        for name, value in ranked
                    ),
                )
            )
    return predictions, snapshots


def _fit_model(examples: Sequence[ExecutionExample]) -> RidgeModel:
    matrix = np.asarray([example.features for example in examples], dtype=np.float64)
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


def _threshold_report(
    predictions: Sequence[ExecutionPrediction],
    *,
    minimum_prediction: float,
) -> dict[str, Any]:
    eligible = [
        prediction
        for prediction in predictions
        if prediction.predicted_net_r >= minimum_prediction
    ]
    accepted, skipped_overlap, skipped_daily_loss = _portfolio(eligible)
    base_trades = [prediction.example.trade for prediction in accepted]
    stress_trades = [prediction.example.stress_trade for prediction in accepted]
    base = _period_reports(base_trades)
    stress = _period_reports(stress_trades)
    annual_base = [base[str(year)] for year in (2022, 2023, 2024)]
    annual_stress = [stress[str(year)] for year in (2022, 2023, 2024)]
    stable = all(
        metric["trades"] >= 15
        and metric["net_expectancy_r"] is not None
        and float(metric["net_expectancy_r"]) > 0
        and metric["profit_factor"] is not None
        and float(metric["profit_factor"]) > 1.15
        for metric in annual_base
    ) and all(
        metric["net_expectancy_r"] is not None
        and float(metric["net_expectancy_r"]) > 0
        for metric in annual_stress
    )
    all_base = base["ALL_PRE_2025"]
    return {
        "minimum_predicted_net_r": (
            None if not math.isfinite(minimum_prediction) else minimum_prediction
        ),
        "eligible_signals": len(eligible),
        "accepted_trades": len(accepted),
        "skipped_overlap": skipped_overlap,
        "skipped_daily_loss": skipped_daily_loss,
        "base_cost": base,
        "stress_1_50x_cost": stress,
        "stable_pre_holdout": stable,
        "meets_10r_monthly_hurdle": bool(
            all_base["average_monthly_r"] is not None
            and float(all_base["average_monthly_r"]) >= 10.0
        ),
    }


def _portfolio(
    predictions: Sequence[ExecutionPrediction],
) -> tuple[list[ExecutionPrediction], int, int]:
    ordered = sorted(
        predictions,
        key=lambda item: (
            item.example.trade.entry_time,
            -item.predicted_net_r,
            item.example.trade.playbook,
        ),
    )
    accepted: list[ExecutionPrediction] = []
    open_until: datetime | None = None
    realized_by_date: dict[date, float] = defaultdict(float)
    skipped_overlap = 0
    skipped_daily_loss = 0
    for prediction in ordered:
        trade = prediction.example.trade
        if open_until is not None and trade.entry_time < open_until:
            skipped_overlap += 1
            continue
        if realized_by_date[trade.session_date] <= -2.0:
            skipped_daily_loss += 1
            continue
        accepted.append(prediction)
        open_until = trade.exit_time
        realized_by_date[trade.session_date] += trade.net_r
    return accepted, skipped_overlap, skipped_daily_loss


def _period_reports(trades: Sequence[Trade]) -> dict[str, Any]:
    return {
        str(year): _compact_metrics(
            [
                trade
                for trade in trades
                if trade.session_date.year == year
            ],
            calendar_start=date(year, 1, 1),
            calendar_end=date(year + 1, 1, 1),
        )
        for year in (2022, 2023, 2024)
    } | {
        "ALL_PRE_2025": _compact_metrics(
            trades,
            calendar_start=date(2022, 1, 1),
            calendar_end=date(2025, 1, 1),
        )
    }


def _calibration(
    predictions: Sequence[ExecutionPrediction],
) -> dict[str, Any]:
    if not predictions:
        return {}
    ordered = sorted(predictions, key=lambda item: item.predicted_net_r)
    buckets: list[dict[str, Any]] = []
    for index, members in enumerate(np.array_split(np.asarray(ordered, dtype=object), 5)):
        values = list(members)
        if not values:
            continue
        buckets.append(
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
            }
        )
    predicted = np.asarray(
        [item.predicted_net_r for item in predictions],
        dtype=np.float64,
    )
    realized = np.asarray(
        [item.example.trade.net_r for item in predictions],
        dtype=np.float64,
    )
    correlation = (
        float(np.corrcoef(predicted, realized)[0, 1])
        if float(np.std(predicted)) > 0 and float(np.std(realized)) > 0
        else 0.0
    )
    return {
        "pearson_correlation": round(correlation, 6),
        "mean_squared_error": round(float(np.mean((predicted - realized) ** 2)), 6),
        "quintiles": buckets,
    }


def _feature_coverage(
    examples: Sequence[ExecutionExample],
) -> dict[str, float]:
    if not examples:
        return {name: 0.0 for name in FEATURE_NAMES}
    matrix = np.asarray([example.features for example in examples], dtype=np.float64)
    return {
        name: round(float(np.isfinite(matrix[:, index]).mean() * 100), 3)
        for index, name in enumerate(FEATURE_NAMES)
    }


def _signal_funnel(
    examples: Sequence[ExecutionExample],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for example in examples:
        counts[example.trade.playbook] += 1
    return dict(sorted(counts.items()))


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
        output[feature] = {
            "mean": round(statistics.mean(values), 8),
            "standard_deviation": round(statistics.pstdev(values), 8),
            "positive_month_pct": round(
                sum(value > 0 for value in values) / len(values) * 100,
                3,
            ),
            "sign_changes": sum(
                current != prior
                for prior, current in zip(signs, signs[1:], strict=False)
            ),
        }
    return output


def _prediction_payload(
    prediction: ExecutionPrediction,
) -> dict[str, Any]:
    trade = prediction.example.trade
    return {
        "session_date": trade.session_date.isoformat(),
        "signal_time": trade.signal_time.isoformat(),
        "entry_time": trade.entry_time.isoformat(),
        "playbook": trade.playbook,
        "side": trade.side,
        "model_month": prediction.model_month,
        "training_signals": prediction.training_signals,
        "predicted_net_r": round(prediction.predicted_net_r, 8),
        "realized_net_r": round(trade.net_r, 8),
        "realized_stress_net_r": round(
            prediction.example.stress_trade.net_r,
            8,
        ),
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
