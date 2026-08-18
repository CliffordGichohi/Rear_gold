from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from gold_intel.backtesting.casebook_baseline import (
    BaselineTrade,
    calculate_baseline_metrics,
)

ATLAS_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_OUTCOME_ATLAS_V0_1"
ATLAS_SCHEMA_VERSION = "gold-casebook-discovery-v2-outcome-atlas-schema-0.1.0"
SESSION_CODES = ("LONDON", "NEW_YORK")
QUANTILE_PROBABILITIES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
CONTROL_FIELDS = (
    "observations",
    "gross_win_rate_pct",
    "net_win_rate_pct",
    "mean_gross_pnl_usd_per_ounce",
    "median_gross_pnl_usd_per_ounce",
    "mean_net_pnl_usd_per_ounce",
    "median_net_pnl_usd_per_ounce",
    "mean_gross_return_basis_points",
    "mean_net_return_basis_points",
    "total_net_pnl_usd_per_ounce",
    "profit_factor",
    "maximum_drawdown_usd_per_ounce",
    "total_cost_usd_per_ounce",
    "average_holding_minutes",
)
ABSOLUTE_MOVE_BINS = (
    ("ABS_LT_2", 0.0, 2.0),
    ("ABS_2_TO_LT_5", 2.0, 5.0),
    ("ABS_5_TO_LT_10", 5.0, 10.0),
    ("ABS_10_TO_LT_20", 10.0, 20.0),
    ("ABS_GE_20", 20.0, None),
)

Direction = Literal["UP", "DOWN", "FLAT"]
CostHurdleState = Literal["LONG_NET_WIN", "SHORT_NET_WIN", "NO_SIDE_NET_WIN"]


@dataclass(frozen=True, slots=True)
class SourceTrade:
    record_id: str
    record_hash: str
    trade: BaselineTrade


@dataclass(frozen=True, slots=True)
class OutcomePair:
    long: SourceTrade
    short: SourceTrade

    @property
    def case_id(self) -> str:
        return self.long.trade.case_id


@dataclass(frozen=True, slots=True)
class OutcomeCase:
    case_id: str
    case_record_hash: str
    session_code: str
    session_date: date
    decision_at: datetime
    entry_time: datetime
    exit_time: datetime
    holding_minutes: int
    source_long_record_id: str
    source_long_record_hash: str
    source_short_record_id: str
    source_short_record_hash: str
    reference_entry_price: float
    reference_exit_price: float
    gross_move_usd_per_ounce: float
    gross_move_basis_points: float
    absolute_move_usd_per_ounce: float
    absolute_move_basis_points: float
    direction: Direction
    absolute_move_bin: str
    cost_usd_per_ounce: float
    cost_basis_points: float
    cost_hurdle_state: CostHurdleState
    long_net_pnl_usd: float
    short_net_pnl_usd: float
    long_net_return_basis_points: float
    short_net_return_basis_points: float
    execution_manifest_hash: str
    measurement_manifest_hash: str


def build_outcome_case(
    pair: OutcomePair,
    *,
    measurement_manifest_hash: str,
) -> OutcomeCase:
    long = pair.long.trade
    short = pair.short.trade
    _validate_pair(pair)
    move = long.reference_exit_price - long.reference_entry_price
    move_bps = 10_000 * move / long.reference_entry_price
    absolute_move = abs(move)
    absolute_bps = abs(move_bps)
    direction: Direction = "UP" if move > 0 else "DOWN" if move < 0 else "FLAT"
    if long.net_pnl_usd > 0 and short.net_pnl_usd > 0:
        raise ValueError(f"Both sides net positive: {long.case_id}")
    hurdle: CostHurdleState
    if long.net_pnl_usd > 0:
        hurdle = "LONG_NET_WIN"
    elif short.net_pnl_usd > 0:
        hurdle = "SHORT_NET_WIN"
    else:
        hurdle = "NO_SIDE_NET_WIN"
    cost = long.total_cost_usd
    return OutcomeCase(
        case_id=long.case_id,
        case_record_hash=long.case_record_hash,
        session_code=long.session_code,
        session_date=long.session_date,
        decision_at=long.decision_at,
        entry_time=long.entry_time,
        exit_time=long.exit_time,
        holding_minutes=long.holding_minutes,
        source_long_record_id=pair.long.record_id,
        source_long_record_hash=pair.long.record_hash,
        source_short_record_id=pair.short.record_id,
        source_short_record_hash=pair.short.record_hash,
        reference_entry_price=_rounded(long.reference_entry_price),
        reference_exit_price=_rounded(long.reference_exit_price),
        gross_move_usd_per_ounce=_rounded(move),
        gross_move_basis_points=_rounded(move_bps),
        absolute_move_usd_per_ounce=_rounded(absolute_move),
        absolute_move_basis_points=_rounded(absolute_bps),
        direction=direction,
        absolute_move_bin=absolute_move_bin(absolute_move),
        cost_usd_per_ounce=_rounded(cost),
        cost_basis_points=_rounded(10_000 * cost / long.reference_entry_price),
        cost_hurdle_state=hurdle,
        long_net_pnl_usd=_rounded(long.net_pnl_usd),
        short_net_pnl_usd=_rounded(short.net_pnl_usd),
        long_net_return_basis_points=_rounded(long.net_return_basis_points),
        short_net_return_basis_points=_rounded(short.net_return_basis_points),
        execution_manifest_hash=long.execution_manifest_hash,
        measurement_manifest_hash=measurement_manifest_hash,
    )


def outcome_case_to_dict(value: OutcomeCase) -> dict[str, Any]:
    return {field: getattr(value, field) for field in value.__dataclass_fields__}


def build_atlas(
    pairs: Sequence[OutcomePair],
    *,
    measurement_manifest_hash: str,
) -> tuple[list[OutcomeCase], dict[str, Any]]:
    if not pairs:
        raise ValueError("Outcome atlas requires at least one source pair")
    outcomes = [
        build_outcome_case(
            pair,
            measurement_manifest_hash=measurement_manifest_hash,
        )
        for pair in pairs
    ]
    outcomes.sort(key=lambda item: (item.decision_at, item.case_id))
    if len({item.case_id for item in outcomes}) != len(outcomes):
        raise ValueError("Duplicate outcome case ID")

    session_results: dict[str, Any] = {}
    for session_code in SESSION_CODES:
        selected_pairs = [pair for pair in pairs if pair.long.trade.session_code == session_code]
        if not selected_pairs:
            raise ValueError(f"No outcome pairs for {session_code}")
        session_results[session_code] = {
            "overall": summarize_pairs(selected_pairs),
            "by_calendar_year": _group_summaries(
                selected_pairs,
                key=lambda pair: str(pair.long.trade.session_date.year),
            ),
            "by_calendar_quarter": _group_summaries(
                selected_pairs,
                key=lambda pair: (
                    f"{pair.long.trade.session_date.year}-"
                    f"Q{(pair.long.trade.session_date.month - 1) // 3 + 1}"
                ),
            ),
            "by_calendar_month": _group_summaries(
                selected_pairs,
                key=lambda pair: pair.long.trade.session_date.strftime("%Y-%m"),
            ),
        }
    return outcomes, session_results


def summarize_pairs(pairs: Sequence[OutcomePair]) -> dict[str, Any]:
    if not pairs:
        raise ValueError("Cannot summarize an empty outcome group")
    outcomes = [
        build_outcome_case(pair, measurement_manifest_hash="SUMMARY_ONLY") for pair in pairs
    ]
    outcomes.sort(key=lambda item: (item.decision_at, item.case_id))
    direction_counts = Counter(item.direction for item in outcomes)
    hurdle_counts = Counter(item.cost_hurdle_state for item in outcomes)
    bin_counts = Counter(item.absolute_move_bin for item in outcomes)
    count = len(outcomes)
    long_metrics = calculate_baseline_metrics([pair.long.trade for pair in pairs])
    short_metrics = calculate_baseline_metrics([pair.short.trade for pair in pairs])
    return {
        "case_count": count,
        "unique_session_dates": len({item.session_date for item in outcomes}),
        "first_session_date": min(item.session_date for item in outcomes).isoformat(),
        "last_session_date": max(item.session_date for item in outcomes).isoformat(),
        "direction": _categorical_summary(
            direction_counts,
            categories=("UP", "DOWN", "FLAT"),
            denominator=count,
        ),
        "cost_hurdle": _categorical_summary(
            hurdle_counts,
            categories=("LONG_NET_WIN", "SHORT_NET_WIN", "NO_SIDE_NET_WIN"),
            denominator=count,
        ),
        "gross_move_usd_per_ounce": _distribution(
            [item.gross_move_usd_per_ounce for item in outcomes],
            include_standard_deviation=True,
        ),
        "gross_move_basis_points": _distribution(
            [item.gross_move_basis_points for item in outcomes],
            include_standard_deviation=True,
        ),
        "absolute_move_usd_per_ounce": _distribution(
            [item.absolute_move_usd_per_ounce for item in outcomes],
            include_standard_deviation=False,
        ),
        "absolute_move_basis_points": _distribution(
            [item.absolute_move_basis_points for item in outcomes],
            include_standard_deviation=False,
        ),
        "absolute_move_bins_usd_per_ounce": _categorical_summary(
            bin_counts,
            categories=tuple(item[0] for item in ABSOLUTE_MOVE_BINS),
            denominator=count,
        ),
        "cost_usd_per_ounce": _distribution(
            [item.cost_usd_per_ounce for item in outcomes],
            include_standard_deviation=False,
        ),
        "cost_basis_points": _distribution(
            [item.cost_basis_points for item in outcomes],
            include_standard_deviation=False,
        ),
        "fixed_controls": {
            "ALWAYS_LONG": {key: long_metrics[key] for key in CONTROL_FIELDS},
            "ALWAYS_SHORT": {key: short_metrics[key] for key in CONTROL_FIELDS},
        },
    }


def absolute_move_bin(value: float) -> str:
    if value < 0:
        raise ValueError("Absolute move cannot be negative")
    for code, lower, upper in ABSOLUTE_MOVE_BINS:
        if value >= lower and (upper is None or value < upper):
            return code
    raise AssertionError("Absolute-move bins are not exhaustive")


def quantile_type_7(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a quantile without values")
    if not 0 <= probability <= 1:
        raise ValueError("Quantile probability must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _validate_pair(pair: OutcomePair) -> None:
    long = pair.long.trade
    short = pair.short.trade
    if long.control_code != "ALWAYS_LONG" or long.side != "LONG":
        raise ValueError(f"Invalid long source: {long.case_id}")
    if short.control_code != "ALWAYS_SHORT" or short.side != "SHORT":
        raise ValueError(f"Invalid short source: {short.case_id}")
    exact_fields = (
        "case_id",
        "case_record_hash",
        "session_code",
        "session_date",
        "decision_at",
        "entry_time",
        "exit_time",
        "holding_minutes",
        "entry_bar_id",
        "entry_bar_hash",
        "exit_bar_id",
        "exit_bar_hash",
        "reference_entry_price",
        "reference_exit_price",
        "entry_spread_price",
        "exit_spread_price",
        "quantity_ounces",
        "quantity_lots",
        "spread_cost_usd",
        "slippage_cost_usd",
        "commission_usd",
        "total_cost_usd",
        "execution_manifest_hash",
    )
    for field in exact_fields:
        if getattr(long, field) != getattr(short, field):
            raise ValueError(f"Long/short {field} mismatch: {long.case_id}")
    if long.session_code not in SESSION_CODES:
        raise ValueError(f"Unexpected session: {long.session_code}")
    if long.session_date.year >= 2025:
        raise ValueError(f"Outcome pair enters locked holdout: {long.case_id}")
    if long.quantity_ounces != 1.0:
        raise ValueError(f"Outcome quantity changed: {long.case_id}")
    if not math.isclose(long.gross_pnl_usd, -short.gross_pnl_usd, abs_tol=1e-7):
        raise ValueError(f"Long/short gross P&L mismatch: {long.case_id}")
    for trade in (long, short):
        if not math.isclose(
            trade.gross_pnl_usd - trade.net_pnl_usd,
            trade.total_cost_usd,
            abs_tol=1e-7,
        ):
            raise ValueError(f"Cost identity failed: {trade.case_id}")


def _group_summaries(
    pairs: Sequence[OutcomePair],
    *,
    key: Any,
) -> dict[str, Any]:
    labels = sorted({str(key(pair)) for pair in pairs})
    return {
        label: summarize_pairs([pair for pair in pairs if str(key(pair)) == label])
        for label in labels
    }


def _distribution(
    values: Sequence[float],
    *,
    include_standard_deviation: bool,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "mean": _rounded(statistics.fmean(values)),
        "median": _rounded(statistics.median(values)),
        "quantiles": {
            _quantile_label(probability): _rounded(quantile_type_7(values, probability))
            for probability in QUANTILE_PROBABILITIES
        },
    }
    if include_standard_deviation:
        output["standard_deviation"] = _rounded(
            statistics.stdev(values) if len(values) >= 2 else 0.0
        )
    return output


def _categorical_summary(
    counts: Mapping[str, int],
    *,
    categories: Sequence[str],
    denominator: int,
) -> dict[str, Any]:
    return {
        category: {
            "count": int(counts.get(category, 0)),
            "pct": _percentage(int(counts.get(category, 0)), denominator),
        }
        for category in categories
    }


def _quantile_label(probability: float) -> str:
    return f"p{round(100 * probability):02d}"


def _percentage(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 4) if denominator else 0.0


def _rounded(value: float) -> float:
    return round(float(value), 8)
