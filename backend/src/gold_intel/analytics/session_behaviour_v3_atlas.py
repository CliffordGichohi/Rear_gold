from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import parse_timestamp

ATLAS_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_ATLAS_V0_1"
TRANSFORM_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M3_TRANSFORM_V0_1"
M3_PRE_RESULT_MANIFEST_HASH = (
    "30ae532aeeb3c3639bc87adc089757b11d4b83ba698af689dbf312a8ad2c2cf2"
)
M2_RESULT_MANIFEST_HASH = (
    "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7"
)
M2_CASE_ARTIFACT_HASH = (
    "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9"
)
CREATED_AND_SEALED_AT = "2026-07-30T09:45:55.2340749Z"

SESSION_CODES = ("LONDON", "NEW_YORK")
HORIZONS = ("5m", "15m", "30m", "60m", "SESSION_CLOSE")
DIRECTION_STATES = ("UP", "DOWN", "FLAT")
EXTREME_ORDER_STATES = ("HIGH_FIRST", "LOW_FIRST", "SAME_BAR")
EXPECTED_PATH_OFFSETS = tuple(range(0, 240, 5))
PERCENTILES = (
    ("p05", Decimal("0.05")),
    ("p10", Decimal("0.10")),
    ("p25", Decimal("0.25")),
    ("median", Decimal("0.50")),
    ("p75", Decimal("0.75")),
    ("p90", Decimal("0.90")),
    ("p95", Decimal("0.95")),
)
TIME_BINS = (
    ("M01_30", 1, 30),
    ("M31_60", 31, 60),
    ("M61_120", 61, 120),
    ("M121_180", 121, 180),
    ("M181_239", 181, 239),
)
WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")

NUMERIC_QUANTUM = Decimal("0.00000001")
PERCENT_QUANTUM = Decimal("0.000001")
DIRECTION_EPSILON = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PathPoint:
    offset_minutes: int
    close: Decimal


@dataclass(frozen=True, slots=True)
class LevelInteraction:
    level_id: str
    level_type: str
    first_interaction_at: datetime | None
    touched: bool
    breached: bool
    accepted: bool
    rejected: bool
    failed_break: bool
    retested: bool


@dataclass(frozen=True, slots=True)
class AtlasCase:
    case_id: str
    session_code: str
    session_date: date
    decision_at: datetime
    neutral_price: Decimal
    fixed_horizons: Mapping[str, Decimal]
    signed_close_displacement: Decimal
    absolute_close_displacement: Decimal
    maximum_upward_displacement: Decimal
    maximum_downward_displacement: Decimal
    session_range: Decimal
    path_efficiency: Decimal | None
    close_location_fraction: Decimal | None
    session_high_at: datetime
    session_low_at: datetime
    extreme_order: str
    path: tuple[PathPoint, ...]
    level_interactions: tuple[LevelInteraction, ...]


def extract_atlas_case(record: Mapping[str, Any]) -> AtlasCase:
    """Extract only M3-authorized fields from one sealed M2 row."""

    metadata = record["case_metadata"]
    if metadata["data_partition"] != "DEVELOPMENT_2021_2024":
        raise ValueError(f"Non-development row: {metadata['case_id']}")
    if metadata["access_class"] != "DEVELOPMENT":
        raise ValueError(f"Non-development access class: {metadata['case_id']}")

    outcome = record["subsequent_behaviour"]
    if outcome["decision_eligible"] is not False:
        raise ValueError(f"Outcome separation violated: {metadata['case_id']}")
    if outcome["path"]["complete"] is not True:
        raise ValueError(f"Incomplete path: {metadata['case_id']}")
    if outcome["path"]["one_minute_source_count"] != 239:
        raise ValueError(f"Unexpected one-minute count: {metadata['case_id']}")
    if outcome["path"]["missing_one_minute_bars"] != 0:
        raise ValueError(f"Missing one-minute bars: {metadata['case_id']}")

    decision_at = parse_timestamp(str(metadata["decision_at"]))
    levels = {
        str(level["level_id"]): str(level["level_type"])
        for level in record["decision_state"]["levels"]
    }
    if len(levels) != len(record["decision_state"]["levels"]):
        raise ValueError(f"Duplicate level ID: {metadata['case_id']}")

    interactions: list[LevelInteraction] = []
    interaction_ids: set[str] = set()
    for interaction in outcome["level_interactions"]:
        level_id = str(interaction["level_id"])
        if level_id not in levels:
            raise ValueError(
                f"Outcome level has no decision-time identity: "
                f"{metadata['case_id']} {level_id}"
            )
        if level_id in interaction_ids:
            raise ValueError(f"Duplicate level interaction: {metadata['case_id']}")
        interaction_ids.add(level_id)
        first_at = interaction["first_interaction_at"]
        interactions.append(
            LevelInteraction(
                level_id=level_id,
                level_type=levels[level_id],
                first_interaction_at=(
                    parse_timestamp(str(first_at)) if first_at is not None else None
                ),
                touched=_fact_bool(interaction["touched"]),
                breached=_fact_bool(interaction["breached"]),
                accepted=_fact_bool(interaction["accepted"]),
                rejected=_fact_bool(interaction["rejected"]),
                failed_break=_fact_bool(interaction["failed_break"]),
                retested=_fact_bool(interaction["retested"]),
            )
        )
    if interaction_ids != set(levels):
        missing = sorted(set(levels) - interaction_ids)
        raise ValueError(
            f"Decision levels lack outcome interaction rows: "
            f"{metadata['case_id']} {missing[:3]}"
        )

    path = tuple(
        PathPoint(
            offset_minutes=int(point["offset_minutes"]),
            close=_decimal(point["xauusd"]["value"]["ohlc"]["close"]),
        )
        for point in outcome["path"]["five_minute_points"]
    )
    if tuple(point.offset_minutes for point in path) != EXPECTED_PATH_OFFSETS:
        raise ValueError(f"Unexpected five-minute offsets: {metadata['case_id']}")

    fixed = {
        str(item["horizon"]): _decimal(item["signed_displacement"]["value"])
        for item in outcome["fixed_horizons"]
    }
    if tuple(fixed) != HORIZONS:
        raise ValueError(f"Unexpected fixed horizons: {metadata['case_id']}")

    excursions = outcome["neutral_excursions"]
    extremes = outcome["extremes"]
    classification = outcome["path_classification"]["value"]
    close_location = outcome["close_location"]["value"]
    case = AtlasCase(
        case_id=str(metadata["case_id"]),
        session_code=str(metadata["session_code"]),
        session_date=date.fromisoformat(str(metadata["session_date"])),
        decision_at=decision_at,
        neutral_price=_decimal(outcome["neutral_reference"]["price"]["value"]),
        fixed_horizons=fixed,
        signed_close_displacement=_fact_decimal(
            excursions["signed_close_displacement"]
        ),
        absolute_close_displacement=_fact_decimal(
            excursions["absolute_close_displacement"]
        ),
        maximum_upward_displacement=_fact_decimal(
            excursions["maximum_upward_displacement"]
        ),
        maximum_downward_displacement=_fact_decimal(
            excursions["maximum_downward_displacement"]
        ),
        session_range=_fact_decimal(excursions["session_range"]),
        path_efficiency=_optional_decimal(classification.get("path_efficiency")),
        close_location_fraction=_optional_decimal(close_location.get("fraction")),
        session_high_at=parse_timestamp(str(extremes["session_high_at"]["value"])),
        session_low_at=parse_timestamp(str(extremes["session_low_at"]["value"])),
        extreme_order=str(extremes["extreme_order"]["value"]),
        path=path,
        level_interactions=tuple(interactions),
    )
    _validate_extracted_case(case, classification)
    return case


def build_atlas_document(
    cases: Sequence[AtlasCase],
) -> dict[str, Any]:
    by_session = {
        session: sorted(
            (case for case in cases if case.session_code == session),
            key=lambda case: (case.session_date, case.case_id),
        )
        for session in SESSION_CODES
    }
    counts = {session: len(values) for session, values in by_session.items()}
    if counts != {"LONDON": 833, "NEW_YORK": 826}:
        raise ValueError(f"Unexpected M3 session counts: {counts}")
    if len(cases) != 1659 or len({case.case_id for case in cases}) != 1659:
        raise ValueError("M3 requires exactly 1,659 unique cases")

    atlas: dict[str, Any] = {
        "atlas_version": ATLAS_VERSION,
        "transform_version": TRANSFORM_VERSION,
        "created_at": CREATED_AND_SEALED_AT,
        "sealed_at": CREATED_AND_SEALED_AT,
        "milestone": "V3_M3_DEVELOPMENT_BEHAVIOUR_ATLAS",
        "source": {
            "pre_result_manifest_hash": M3_PRE_RESULT_MANIFEST_HASH,
            "case_matrix_manifest_hash": M2_RESULT_MANIFEST_HASH,
            "case_artifact_sha256": M2_CASE_ARTIFACT_HASH,
            "data_partition": "DEVELOPMENT_2021_2024",
            "session_date_start_inclusive": "2021-08-01",
            "session_date_end_inclusive": "2024-12-31",
        },
        "interpretation_boundary": {
            "descriptive_only": True,
            "causal_attribution": False,
            "conditional_relationships_tested": 0,
            "candidates_created_or_ranked": 0,
            "predictive_metrics_calculated": 0,
            "hypothesis_tests_calculated": 0,
            "execution_variants_tested": 0,
            "trades_or_returns_calculated": 0,
            "calendar_2025_values_opened": False,
            "calendar_2026_values_opened": False,
            "combined_session_result": False,
        },
        "case_counts": {
            "total": len(cases),
            "london": counts["LONDON"],
            "new_york": counts["NEW_YORK"],
        },
        "sessions": {
            session: _build_session_atlas(values)
            for session, values in by_session.items()
        },
    }
    atlas["atlas_hash"] = canonical_hash(atlas)
    return json_ready(atlas)


def summarize_numeric(
    values: Iterable[Decimal | int | float | None],
) -> dict[str, Any]:
    converted = [None if value is None else _decimal(value) for value in values]
    present = sorted(value for value in converted if value is not None)
    missing = len(converted) - len(present)
    if not present:
        return {
            "count": 0,
            "missing_count": missing,
            "mean": None,
            "standard_deviation": None,
            "minimum": None,
            "p05": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "maximum": None,
        }
    with localcontext() as context:
        context.prec = 40
        mean = sum(present, Decimal(0)) / Decimal(len(present))
        if len(present) < 2:
            standard_deviation = None
        else:
            variance = sum((value - mean) ** 2 for value in present) / Decimal(
                len(present) - 1
            )
            standard_deviation = variance.sqrt()
    output: dict[str, Any] = {
        "count": len(present),
        "missing_count": missing,
        "mean": _numeric_output(mean),
        "standard_deviation": (
            _numeric_output(standard_deviation)
            if standard_deviation is not None
            else None
        ),
        "minimum": _numeric_output(present[0]),
    }
    for code, probability in PERCENTILES:
        output[code] = _numeric_output(_percentile_type_7(present, probability))
    output["maximum"] = _numeric_output(present[-1])
    return output


def direction_frequency(
    values: Iterable[Decimal | int | float],
) -> dict[str, Any]:
    converted = [_decimal(value) for value in values]
    counts = Counter(_direction(value) for value in converted)
    total = len(converted)
    return {
        "denominator": total,
        "states": {
            state: {
                "count": counts[state],
                "percentage": _percentage(counts[state], total),
            }
            for state in DIRECTION_STATES
        },
    }


def categorical_frequency(
    values: Iterable[str],
    *,
    states: Sequence[str],
) -> dict[str, Any]:
    converted = [str(value) for value in values]
    counts = Counter(converted)
    unexpected = set(counts) - set(states)
    if unexpected:
        raise ValueError(f"Unexpected categorical states: {sorted(unexpected)}")
    total = len(converted)
    return {
        "denominator": total,
        "states": {
            state: {
                "count": counts[state],
                "percentage": _percentage(counts[state], total),
            }
            for state in states
        },
    }


def verify_atlas_hash(atlas: Mapping[str, Any]) -> bool:
    supplied = str(atlas.get("atlas_hash", ""))
    unhashed = {key: value for key, value in atlas.items() if key != "atlas_hash"}
    return bool(supplied) and canonical_hash(unhashed) == supplied


def validate_atlas_semantics(atlas: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not verify_atlas_hash(atlas):
        errors.append("ATLAS_HASH_MISMATCH")
    if atlas.get("case_counts") != {
        "total": 1659,
        "london": 833,
        "new_york": 826,
    }:
        errors.append("CASE_COUNT_MISMATCH")
    if set(atlas.get("sessions", {})) != set(SESSION_CODES):
        errors.append("SESSION_SET_MISMATCH")
    boundary = atlas.get("interpretation_boundary", {})
    expected_false = (
        "causal_attribution",
        "calendar_2025_values_opened",
        "calendar_2026_values_opened",
        "combined_session_result",
    )
    if boundary.get("descriptive_only") is not True or any(
        boundary.get(key) is not False for key in expected_false
    ):
        errors.append("INTERPRETATION_BOUNDARY_MISMATCH")
    expected_zero = (
        "conditional_relationships_tested",
        "candidates_created_or_ranked",
        "predictive_metrics_calculated",
        "hypothesis_tests_calculated",
        "execution_variants_tested",
        "trades_or_returns_calculated",
    )
    if any(boundary.get(key) != 0 for key in expected_zero):
        errors.append("PROHIBITED_RESEARCH_COUNT_NONZERO")

    for session_code, expected_count in (("LONDON", 833), ("NEW_YORK", 826)):
        session = atlas.get("sessions", {}).get(session_code, {})
        if session.get("case_count") != expected_count:
            errors.append(f"{session_code}:CASE_COUNT")
        directions = session.get("direction_frequencies", {})
        if len(directions) != len(HORIZONS) or set(directions) != set(HORIZONS):
            errors.append(f"{session_code}:HORIZON_SET")
        for horizon, frequency in directions.items():
            if not _frequency_reconciles(frequency, expected_count):
                errors.append(f"{session_code}:{horizon}:DIRECTION_RECONCILIATION")
        extreme_frequency = session.get("timing", {}).get("extreme_order", {})
        if not _frequency_reconciles(extreme_frequency, expected_count):
            errors.append(f"{session_code}:EXTREME_ORDER_RECONCILIATION")
        curve = session.get("path_curve", [])
        if [item.get("offset_minutes") for item in curve] != list(
            EXPECTED_PATH_OFFSETS
        ):
            errors.append(f"{session_code}:PATH_OFFSETS")
        for item in curve:
            if item.get("displacement_summary", {}).get("count") != expected_count:
                errors.append(f"{session_code}:PATH_COUNT")
                break
            if not _frequency_reconciles(
                item.get("direction_frequency", {}),
                expected_count,
            ):
                errors.append(f"{session_code}:PATH_DIRECTION_RECONCILIATION")
                break
        calendar = session.get("calendar_stability", {})
        if sum(item["case_count"] for item in calendar.get("by_year", [])) != expected_count:
            errors.append(f"{session_code}:YEAR_COUNT")
        if (
            sum(item["case_count"] for item in calendar.get("by_month_of_year", []))
            != expected_count
        ):
            errors.append(f"{session_code}:MONTH_COUNT")
        if (
            sum(item["case_count"] for item in calendar.get("by_weekday", []))
            != expected_count
        ):
            errors.append(f"{session_code}:WEEKDAY_COUNT")
        for level in session.get("level_interactions", []):
            denominator = int(level["eligible_level_count"])
            for metric in (
                "touched",
                "breached",
                "accepted",
                "rejected",
                "failed_break",
                "retested",
            ):
                if not _count_percentage_reconciles(level[metric], denominator):
                    errors.append(
                        f"{session_code}:{level['level_type']}:{metric}:RECONCILIATION"
                    )
    if _contains_prohibited_key(atlas):
        errors.append("PROHIBITED_KEY")
    return sorted(set(errors))


def _build_session_atlas(cases: Sequence[AtlasCase]) -> dict[str, Any]:
    direction_frequencies = {
        horizon: direction_frequency(
            case.fixed_horizons[horizon] for case in cases
        )
        for horizon in HORIZONS
    }
    return {
        "case_count": len(cases),
        "first_session_date": cases[0].session_date.isoformat(),
        "last_session_date": cases[-1].session_date.isoformat(),
        "direction_frequencies": direction_frequencies,
        "excursions_and_close": {
            "signed_close_displacement": summarize_numeric(
                case.signed_close_displacement for case in cases
            ),
            "absolute_close_displacement": summarize_numeric(
                case.absolute_close_displacement for case in cases
            ),
            "maximum_upward_displacement": summarize_numeric(
                case.maximum_upward_displacement for case in cases
            ),
            "maximum_downward_displacement": summarize_numeric(
                case.maximum_downward_displacement for case in cases
            ),
            "maximum_downward_displacement_magnitude": summarize_numeric(
                abs(case.maximum_downward_displacement) for case in cases
            ),
            "session_range": summarize_numeric(case.session_range for case in cases),
            "path_efficiency": summarize_numeric(
                case.path_efficiency for case in cases
            ),
            "close_location_fraction": summarize_numeric(
                case.close_location_fraction for case in cases
            ),
        },
        "timing": _build_timing_atlas(cases),
        "path_curve": _build_path_curve(cases),
        "level_interactions": _build_level_atlas(cases),
        "calendar_stability": _build_calendar_atlas(cases),
    }


def _build_timing_atlas(cases: Sequence[AtlasCase]) -> dict[str, Any]:
    high_minutes = [
        int((case.session_high_at - case.decision_at).total_seconds() // 60)
        for case in cases
    ]
    low_minutes = [
        int((case.session_low_at - case.decision_at).total_seconds() // 60)
        for case in cases
    ]
    return {
        "extreme_order": categorical_frequency(
            (case.extreme_order for case in cases),
            states=EXTREME_ORDER_STATES,
        ),
        "session_high_minute": {
            "summary": summarize_numeric(high_minutes),
            "bins": _timing_bins(high_minutes),
        },
        "session_low_minute": {
            "summary": summarize_numeric(low_minutes),
            "bins": _timing_bins(low_minutes),
        },
    }


def _build_path_curve(cases: Sequence[AtlasCase]) -> list[dict[str, Any]]:
    values: dict[int, list[Decimal]] = {
        offset: [] for offset in EXPECTED_PATH_OFFSETS
    }
    for case in cases:
        for point in case.path:
            values[point.offset_minutes].append(point.close - case.neutral_price)
    return [
        {
            "offset_minutes": offset,
            "source_bar_close_available_offset_minutes": offset + 5,
            "displacement_summary": summarize_numeric(values[offset]),
            "direction_frequency": direction_frequency(values[offset]),
        }
        for offset in EXPECTED_PATH_OFFSETS
    ]


def _build_level_atlas(cases: Sequence[AtlasCase]) -> list[dict[str, Any]]:
    grouped: dict[str, list[tuple[str, LevelInteraction, datetime]]] = defaultdict(list)
    for case in cases:
        for interaction in case.level_interactions:
            grouped[interaction.level_type].append(
                (case.case_id, interaction, case.decision_at)
            )
    output: list[dict[str, Any]] = []
    for level_type in sorted(grouped):
        rows = grouped[level_type]
        first_minutes = [
            int((interaction.first_interaction_at - decision).total_seconds() // 60)
            for _case_id, interaction, decision in rows
            if interaction.touched and interaction.first_interaction_at is not None
        ]
        output.append(
            {
                "level_type": level_type,
                "eligible_level_count": len(rows),
                "cases_with_level": len({case_id for case_id, _item, _dt in rows}),
                "touched": _boolean_count(rows, "touched"),
                "breached": _boolean_count(rows, "breached"),
                "accepted": _boolean_count(rows, "accepted"),
                "rejected": _boolean_count(rows, "rejected"),
                "failed_break": _boolean_count(rows, "failed_break"),
                "retested": _boolean_count(rows, "retested"),
                "first_interaction_minute_for_touched_levels": summarize_numeric(
                    first_minutes
                ),
            }
        )
    return output


def _build_calendar_atlas(cases: Sequence[AtlasCase]) -> dict[str, Any]:
    years = [
        _calendar_group(
            code=str(year),
            label=(
                "PARTIAL_FROM_2021_08_01" if year == 2021 else "FULL_CALENDAR_YEAR"
            ),
            cases=[case for case in cases if case.session_date.year == year],
        )
        for year in (2021, 2022, 2023, 2024)
    ]
    months = [
        _calendar_group(
            code=f"{month:02d}",
            label=datetime(2000, month, 1).strftime("%B").upper(),
            cases=[case for case in cases if case.session_date.month == month],
        )
        for month in range(1, 13)
    ]
    weekdays = [
        _calendar_group(
            code=weekday,
            label=weekday,
            cases=[
                case
                for case in cases
                if case.session_date.strftime("%A").upper() == weekday
            ],
        )
        for weekday in WEEKDAYS
    ]
    return {
        "by_year": years,
        "by_month_of_year": months,
        "by_weekday": weekdays,
        "annual_stability_summary": _annual_stability_summary(years),
        "interpretation": (
            "Descriptive calendar slices only. No trend, significance, predictive, "
            "selection, or causal inference is made."
        ),
    }


def _calendar_group(
    *,
    code: str,
    label: str,
    cases: Sequence[AtlasCase],
) -> dict[str, Any]:
    return {
        "group_code": code,
        "group_label": label,
        "case_count": len(cases),
        "close_direction": direction_frequency(
            case.signed_close_displacement for case in cases
        ),
        "signed_close_displacement": summarize_numeric(
            case.signed_close_displacement for case in cases
        ),
        "session_range": summarize_numeric(case.session_range for case in cases),
        "maximum_upward_displacement": summarize_numeric(
            case.maximum_upward_displacement for case in cases
        ),
        "maximum_downward_displacement": summarize_numeric(
            case.maximum_downward_displacement for case in cases
        ),
        "extreme_order": categorical_frequency(
            (case.extreme_order for case in cases),
            states=EXTREME_ORDER_STATES,
        ),
    }


def _annual_stability_summary(
    years: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "up_percentage_range": _descriptive_range(
            Decimal(str(year["close_direction"]["states"]["UP"]["percentage"]))
            for year in years
        ),
        "down_percentage_range": _descriptive_range(
            Decimal(str(year["close_direction"]["states"]["DOWN"]["percentage"]))
            for year in years
        ),
        "flat_percentage_range": _descriptive_range(
            Decimal(str(year["close_direction"]["states"]["FLAT"]["percentage"]))
            for year in years
        ),
        "median_signed_close_displacement_range": _descriptive_range(
            Decimal(str(year["signed_close_displacement"]["median"]))
            for year in years
        ),
        "median_session_range_range": _descriptive_range(
            Decimal(str(year["session_range"]["median"])) for year in years
        ),
    }


def _descriptive_range(values: Iterable[Decimal]) -> dict[str, Any]:
    converted = list(values)
    minimum = min(converted)
    maximum = max(converted)
    return {
        "minimum": _numeric_output(minimum),
        "maximum": _numeric_output(maximum),
        "range": _numeric_output(maximum - minimum),
    }


def _timing_bins(values: Sequence[int]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for code, lower, upper in TIME_BINS:
        count = sum(lower <= value <= upper for value in values)
        output.append(
            {
                "bin": code,
                "lower_inclusive": lower,
                "upper_inclusive": upper,
                "count": count,
                "percentage": _percentage(count, len(values)),
            }
        )
    if sum(item["count"] for item in output) != len(values):
        raise ValueError("Extreme timing falls outside frozen bins")
    return output


def _boolean_count(
    rows: Sequence[tuple[str, LevelInteraction, datetime]],
    field: str,
) -> dict[str, Any]:
    count = sum(bool(getattr(interaction, field)) for _case, interaction, _dt in rows)
    return {
        "count": count,
        "percentage": _percentage(count, len(rows)),
    }


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    value = Decimal(numerator) * Decimal(100) / Decimal(denominator)
    return _decimal_output(value, PERCENT_QUANTUM)


def _direction(value: Decimal) -> str:
    if value > DIRECTION_EPSILON:
        return "UP"
    if value < -DIRECTION_EPSILON:
        return "DOWN"
    return "FLAT"


def _percentile_type_7(
    sorted_values: Sequence[Decimal],
    probability: Decimal,
) -> Decimal:
    if not sorted_values:
        raise ValueError("Cannot calculate a percentile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = Decimal(len(sorted_values) - 1) * probability
    lower = int(index)
    fraction = index - Decimal(lower)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + fraction * (
        sorted_values[upper] - sorted_values[lower]
    )


def _numeric_output(value: Decimal) -> float:
    return _decimal_output(value, NUMERIC_QUANTUM)


def _decimal_output(value: Decimal, quantum: Decimal) -> float:
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    if rounded == 0:
        return 0.0
    return float(rounded)


def _decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else _decimal(value)


def _fact_decimal(value: Mapping[str, Any]) -> Decimal:
    return _decimal(value["value"])


def _fact_bool(value: Mapping[str, Any]) -> bool:
    raw = value["value"]
    if not isinstance(raw, bool):
        raise ValueError("Level-interaction fact is not boolean")
    return raw


def _validate_extracted_case(
    case: AtlasCase,
    classification: Mapping[str, Any],
) -> None:
    if case.session_code not in SESSION_CODES:
        raise ValueError(f"Unexpected session: {case.case_id}")
    if not date(2021, 8, 1) <= case.session_date <= date(2024, 12, 31):
        raise ValueError(f"Case outside development: {case.case_id}")
    if case.maximum_upward_displacement < 0:
        raise ValueError(f"Negative upward displacement: {case.case_id}")
    if case.maximum_downward_displacement > 0:
        raise ValueError(f"Positive downward displacement: {case.case_id}")
    if case.session_range < 0:
        raise ValueError(f"Negative range: {case.case_id}")
    if case.extreme_order not in EXTREME_ORDER_STATES:
        raise ValueError(f"Unexpected extreme order: {case.case_id}")
    if _direction(case.signed_close_displacement) != classification["net_state"]:
        raise ValueError(f"Close direction mismatch: {case.case_id}")
    high_minute = int(
        (case.session_high_at - case.decision_at).total_seconds() // 60
    )
    low_minute = int((case.session_low_at - case.decision_at).total_seconds() // 60)
    if not 1 <= high_minute <= 239 or not 1 <= low_minute <= 239:
        raise ValueError(f"Extreme timing outside frozen window: {case.case_id}")


def _frequency_reconciles(
    frequency: Mapping[str, Any],
    denominator: int,
) -> bool:
    states = frequency.get("states", {})
    return (
        frequency.get("denominator") == denominator
        and sum(int(item.get("count", -1)) for item in states.values()) == denominator
        and all(
            _count_percentage_reconciles(item, denominator)
            for item in states.values()
        )
    )


def _count_percentage_reconciles(
    value: Mapping[str, Any],
    denominator: int,
) -> bool:
    count = int(value.get("count", -1))
    return (
        0 <= count <= denominator
        and value.get("percentage") == _percentage(count, denominator)
    )


def _contains_prohibited_key(value: Any) -> bool:
    prohibited = {
        "correlation",
        "regression",
        "p_value",
        "significance",
        "candidate",
        "candidate_rank",
        "predictive_accuracy",
        "auc",
        "trade_direction",
        "entry",
        "stop",
        "target",
        "pnl",
        "r_multiple",
        "mfe",
        "mae",
        "account_return",
        "position_size",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in prohibited:
                return True
            if _contains_prohibited_key(nested):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return any(_contains_prohibited_key(item) for item in value)
    return False
