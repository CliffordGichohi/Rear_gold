from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from research_daily_session_playbooks import (
    Bar,
    Day,
    _atr_by_close,
    _bootstrap_mean,
    _build_days,
)
from research_intraday_usd_confirmation import FIVE_MINUTE_INSTRUMENT_SQL

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory

OutcomeCode = Literal[
    "LONDON_CLOSE",
    "NEW_YORK_CLOSE_FROM_LONDON_OPEN",
    "LONDON_LARGER_EXCURSION",
    "FIRST_ASIA_BREAK",
    "LONDON_CLOSE_OUTSIDE_ASIA",
]
Predictor = Callable[["BiasDay"], int]


@dataclass(frozen=True, slots=True)
class BiasDay:
    session_date: date
    score: float
    confidence: float
    coverage: float
    regime: str
    reaction_function: str
    dominant_driver: str | None
    component_directions: dict[str, float]
    outcomes: dict[OutcomeCode, float | None]
    london_range_atr: float
    new_york_range_atr: float
    london_range_price: float
    new_york_range_price: float


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    predictor: Predictor


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded during development")

    async with session_factory() as session:
        rows = (
            await session.execute(
                FIVE_MINUTE_INSTRUMENT_SQL,
                {
                    "instrument": "XAUUSD",
                    "load_start": start - timedelta(days=6),
                    "load_end": end,
                },
            )
        ).mappings()
        bars = [
            Bar(
                open_time=row["open_time"],
                close_time=row["close_time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                spread=float(row["spread_price"]),
            )
            for row in rows
        ]
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)

    days = _build_days(bars, start=start, end=end)
    records = _build_records(
        days,
        atr_by_close=_atr_by_close(bars),
        fundamental_inputs=fundamental_inputs,
    )
    report: dict[str, Any] = {
        "contract": {
            "version": "FUNDAMENTAL_BIAS_TARGET_VALIDITY_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(records),
            "decision_clock": (
                "Five minutes before the DST-aware London research window; "
                "only evidence available at that clock is eligible."
            ),
            "development_splits": {
                "discovery": "2021-08-01 through 2022-12-31",
                "validation": "calendar year 2023",
                "forward": "calendar year 2024",
                "locked_holdout": "calendar year 2025 (not loaded)",
            },
            "interpretation": (
                "This is a target-validity diagnostic, not a tradable backtest. "
                "It contains no fill, stop, target, or position sizing."
            ),
        },
        "opportunity": _opportunity(records),
        "predictors": {},
    }
    for rule in _rules():
        report["predictors"][rule.name] = {
            outcome: _rule_metrics(records, rule=rule, outcome=outcome)
            for outcome in (
                "LONDON_CLOSE",
                "NEW_YORK_CLOSE_FROM_LONDON_OPEN",
                "LONDON_LARGER_EXCURSION",
                "FIRST_ASIA_BREAK",
                "LONDON_CLOSE_OUTSIDE_ASIA",
            )
        }
    print(json.dumps(report, indent=2, sort_keys=True))


def _build_records(
    days: Sequence[Day],
    *,
    atr_by_close: dict[datetime, float],
    fundamental_inputs: Any,
) -> list[BiasDay]:
    output: list[BiasDay] = []
    for day in days:
        decision_at = day.london[0].open_time - timedelta(minutes=5)
        atr = atr_by_close.get(decision_at)
        if atr is None or atr <= 0:
            continue
        # This diagnostic never persists or compares snapshot hashes. Building
        # the hash serializes the complete eligible evidence history for every
        # session and cannot change any analytical output below.
        state = fundamental_inputs.state_at(
            decision_at,
            compute_data_hash=False,
        )
        components = {
            component.code: component.direction
            for component in state.components
            if component.epistemic_status != "UNKNOWN"
        }
        london_open = day.london[0].open
        london_close = day.london[-1].close
        new_york_close = day.new_york[-1].close
        london_high = max(bar.high for bar in day.london)
        london_low = min(bar.low for bar in day.london)
        new_york_high = max(bar.high for bar in day.new_york)
        new_york_low = min(bar.low for bar in day.new_york)
        asia_high = max(bar.high for bar in day.asia)
        asia_low = min(bar.low for bar in day.asia)
        first_break = _first_asia_break(
            day.london,
            asia_high=asia_high,
            asia_low=asia_low,
        )
        outside_direction = (
            1.0
            if london_close > asia_high
            else -1.0
            if london_close < asia_low
            else None
        )
        upward_excursion = london_high - london_open
        downward_excursion = london_open - london_low
        larger_excursion = (
            1.0
            if upward_excursion > downward_excursion
            else -1.0
            if downward_excursion > upward_excursion
            else None
        )
        output.append(
            BiasDay(
                session_date=day.session_date,
                score=state.directional_score,
                confidence=state.confidence,
                coverage=state.coverage,
                regime=state.regime_label,
                reaction_function=state.reaction_function,
                dominant_driver=state.dominant_driver,
                component_directions=components,
                outcomes={
                    "LONDON_CLOSE": (london_close - london_open) / atr,
                    "NEW_YORK_CLOSE_FROM_LONDON_OPEN": (
                        new_york_close - london_open
                    )
                    / atr,
                    "LONDON_LARGER_EXCURSION": larger_excursion,
                    "FIRST_ASIA_BREAK": first_break,
                    "LONDON_CLOSE_OUTSIDE_ASIA": outside_direction,
                },
                london_range_atr=(london_high - london_low) / atr,
                new_york_range_atr=(new_york_high - new_york_low) / atr,
                london_range_price=london_high - london_low,
                new_york_range_price=new_york_high - new_york_low,
            )
        )
    return output


def _first_asia_break(
    bars: Sequence[Bar],
    *,
    asia_high: float,
    asia_low: float,
) -> float | None:
    for bar in bars:
        broke_high = bar.high > asia_high
        broke_low = bar.low < asia_low
        if broke_high and broke_low:
            return None
        if broke_high:
            return 1.0
        if broke_low:
            return -1.0
    return None


def _rules() -> tuple[Rule, ...]:
    return (
        Rule("OVERALL_SCORE_ABS_GE_0", lambda record: _sign(record.score)),
        Rule(
            "OVERALL_SCORE_ABS_GE_5",
            lambda record: _threshold_sign(record.score, 5),
        ),
        Rule(
            "OVERALL_SCORE_ABS_GE_10",
            lambda record: _threshold_sign(record.score, 10),
        ),
        Rule(
            "DOMINANT_DRIVER_DIRECTION",
            lambda record: _sign(
                record.component_directions.get(record.dominant_driver or "", 0.0)
            ),
        ),
        Rule(
            "REAL_YIELD_DIRECTION",
            lambda record: _sign(
                record.component_directions.get("REAL_YIELD", 0.0)
            ),
        ),
        Rule(
            "TWO_YEAR_YIELD_DIRECTION",
            lambda record: _sign(
                record.component_directions.get("TWO_YEAR_YIELD", 0.0)
            ),
        ),
        Rule(
            "BROAD_USD_DIRECTION",
            lambda record: _sign(
                record.component_directions.get("USD", 0.0)
            ),
        ),
        Rule(
            "RATES_USD_MAJORITY",
            lambda record: _sign(
                sum(
                    record.component_directions.get(code, 0.0)
                    for code in ("REAL_YIELD", "TWO_YEAR_YIELD", "USD")
                )
            ),
        ),
        Rule(
            "EVENT_SURPRISE_DIRECTION",
            lambda record: _sign(
                record.component_directions.get("CATALYST_SURPRISE", 0.0)
            ),
        ),
        Rule(
            "POSITIONING_FLOW_DIRECTION",
            lambda record: _sign(
                record.component_directions.get("POSITIONING_FLOW", 0.0)
            ),
        ),
    )


def _rule_metrics(
    records: Sequence[BiasDay],
    *,
    rule: Rule,
    outcome: OutcomeCode,
) -> dict[str, Any]:
    by_year: dict[int, list[float]] = defaultdict(list)
    correct_by_year: dict[int, int] = defaultdict(int)
    for record in records:
        prediction = rule.predictor(record)
        actual = record.outcomes[outcome]
        if prediction == 0 or actual is None or actual == 0:
            continue
        signed_outcome = prediction * actual
        by_year[record.session_date.year].append(signed_outcome)
        correct_by_year[record.session_date.year] += signed_outcome > 0
    return {
        str(year): _predictive_metrics(
            values,
            correct=correct_by_year[year],
        )
        for year, values in sorted(by_year.items())
    }


def _predictive_metrics(
    values: Sequence[float],
    *,
    correct: int,
) -> dict[str, Any]:
    interval = _bootstrap_mean(values)
    return {
        "observations": len(values),
        "directional_accuracy_pct": round(correct / len(values) * 100, 3),
        "mean_signed_outcome": round(statistics.mean(values), 6),
        "median_signed_outcome": round(statistics.median(values), 6),
        "bootstrap_95ci": [
            round(interval[0], 6),
            round(interval[1], 6),
        ],
    }


def _opportunity(records: Sequence[BiasDay]) -> dict[str, Any]:
    by_year: dict[int, list[BiasDay]] = defaultdict(list)
    for record in records:
        by_year[record.session_date.year].append(record)
    return {
        str(year): {
            "sessions": len(values),
            "mean_london_range_atr": round(
                statistics.mean(item.london_range_atr for item in values),
                6,
            ),
            "median_london_range_price": round(
                statistics.median(item.london_range_price for item in values),
                6,
            ),
            "mean_new_york_range_atr": round(
                statistics.mean(item.new_york_range_atr for item in values),
                6,
            ),
            "median_new_york_range_price": round(
                statistics.median(item.new_york_range_price for item in values),
                6,
            ),
        }
        for year, values in sorted(by_year.items())
    }


def _threshold_sign(value: float, threshold: float) -> int:
    return _sign(value) if abs(value) >= threshold else 0


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


if __name__ == "__main__":
    asyncio.run(main())
