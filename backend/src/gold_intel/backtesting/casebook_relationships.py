from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from statistics import NormalDist
from typing import Any, Literal

Side = Literal["LONG", "SHORT"]
RelationshipType = Literal["SINGLE", "INTERACTION"]


@dataclass(frozen=True, slots=True)
class OutcomeTrade:
    side: Side
    net_pnl_usd: float
    net_return_basis_points: float


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    long: OutcomeTrade
    short: OutcomeTrade

    def for_side(self, side: Side) -> OutcomeTrade:
        return self.long if side == "LONG" else self.short


@dataclass(frozen=True, slots=True)
class RawFeature:
    feature_id: str
    family_code: str
    transform: str
    raw_value: float | str | None
    source_key: str | None
    cot_report_id: str | None = None


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    feature_id: str
    family_code: str
    transform: str
    raw_value: float | str | None
    state: str
    source_key: str | None
    cot_report_id: str | None = None


@dataclass(frozen=True, slots=True)
class DevelopmentCase:
    case_id: str
    case_record_hash: str
    session_code: str
    session_date: date
    decision_at: datetime
    chronological_half: str
    features: Mapping[str, FeatureObservation]
    outcome: CaseOutcome

    @property
    def iso_week_key(self) -> str:
        iso = self.session_date.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"


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


def fit_tertile_thresholds(
    raw_cases: Sequence[Mapping[str, RawFeature]],
    *,
    feature_ids: Sequence[str],
) -> dict[str, dict[str, float | int]]:
    thresholds: dict[str, dict[str, float | int]] = {}
    for feature_id in sorted(feature_ids):
        values = [
            float(feature.raw_value)
            for raw in raw_cases
            if (feature := raw.get(feature_id)) is not None
            and isinstance(feature.raw_value, int | float)
            and math.isfinite(float(feature.raw_value))
        ]
        if not values:
            continue
        thresholds[feature_id] = {
            "low_max": quantile_type_7(values, 1 / 3),
            "high_min": quantile_type_7(values, 2 / 3),
            "fit_observations": len(values),
        }
    return thresholds


def materialize_feature(
    feature: RawFeature,
    *,
    tertile_thresholds: Mapping[str, Mapping[str, float | int]],
    direction_bearish_max: float = -0.1,
    direction_bullish_min: float = 0.1,
    sign_epsilon: float = 1e-12,
) -> FeatureObservation:
    state = transform_feature_value(
        feature.feature_id,
        feature.raw_value,
        transform=feature.transform,
        tertile_thresholds=tertile_thresholds,
        direction_bearish_max=direction_bearish_max,
        direction_bullish_min=direction_bullish_min,
        sign_epsilon=sign_epsilon,
    )
    return FeatureObservation(
        feature_id=feature.feature_id,
        family_code=feature.family_code,
        transform=feature.transform,
        raw_value=feature.raw_value,
        state=state,
        source_key=feature.source_key,
        cot_report_id=feature.cot_report_id,
    )


def transform_feature_value(
    feature_id: str,
    value: float | str | None,
    *,
    transform: str,
    tertile_thresholds: Mapping[str, Mapping[str, float | int]],
    direction_bearish_max: float = -0.1,
    direction_bullish_min: float = 0.1,
    sign_epsilon: float = 1e-12,
) -> str:
    if value is None:
        return "UNKNOWN"
    if transform in {"CATEGORY", "RANGE_RELATION"}:
        text = str(value)
        return text if text else "UNKNOWN"
    if not isinstance(value, int | float) or not math.isfinite(float(value)):
        return "UNKNOWN"
    number = float(value)
    if transform == "DIRECTION_3":
        if number <= direction_bearish_max:
            return "BEARISH"
        if number >= direction_bullish_min:
            return "BULLISH"
        return "NEUTRAL"
    if transform == "SIGN_3":
        if number < -sign_epsilon:
            return "NEGATIVE"
        if number > sign_epsilon:
            return "POSITIVE"
        return "FLAT"
    if transform == "TERTILE":
        threshold = tertile_thresholds.get(feature_id)
        if threshold is None:
            return "UNKNOWN"
        if number <= float(threshold["low_max"]):
            return "LOW"
        if number >= float(threshold["high_min"]):
            return "HIGH"
        return "MID"
    raise ValueError(f"Unsupported feature transform: {transform}")


def direction_metrics(
    cases: Sequence[DevelopmentCase],
    *,
    side: Side,
) -> dict[str, Any]:
    if not cases:
        return _empty_direction_metrics()
    trades = [case.outcome.for_side(side) for case in cases]
    pnl = [trade.net_pnl_usd for trade in trades]
    returns = [trade.net_return_basis_points for trade in trades]
    gains = math.fsum(value for value in pnl if value > 0)
    losses = math.fsum(value for value in pnl if value < 0)
    mean_return = statistics.fmean(returns)
    standard_deviation = statistics.stdev(returns) if len(returns) >= 2 else 0.0
    half_width = (
        1.96 * standard_deviation / math.sqrt(len(returns))
        if standard_deviation > 0
        else 0.0
    )
    return {
        "observations": len(cases),
        "net_win_rate_pct": _percentage(
            sum(value > 0 for value in pnl),
            len(pnl),
        ),
        "mean_net_pnl_usd_per_ounce": _rounded(statistics.fmean(pnl)),
        "median_net_pnl_usd_per_ounce": _rounded(statistics.median(pnl)),
        "mean_net_return_basis_points": _rounded(mean_return),
        "normal_95pct_ci_basis_points": [
            _rounded(mean_return - half_width),
            _rounded(mean_return + half_width),
        ],
        "total_net_pnl_usd_per_ounce": _rounded(math.fsum(pnl)),
        "profit_factor": (
            _rounded(gains / abs(losses))
            if losses < 0
            else None
        ),
        "return_standard_deviation_basis_points": _rounded(
            standard_deviation
        ),
    }


def evaluate_relationship_state(
    cases: Sequence[DevelopmentCase],
    *,
    relationship_type: RelationshipType,
    relationship_id: str,
    state: str,
    feature_ids: Sequence[str],
    total_session_cases: int,
    same_session_baselines: Mapping[Side, Mapping[str, Any]],
    manifest_hash: str,
    bootstrap_replications: int,
    minimum_cases: int,
    maximum_prevalence_pct: float,
    minimum_week_clusters: int,
    minimum_years_with_10_cases: int,
    cot_minimum_reports: int,
    development_years: Sequence[int],
) -> dict[str, Any]:
    if not cases:
        raise ValueError("A relationship state requires at least one case")
    session_code = cases[0].session_code
    if any(case.session_code != session_code for case in cases):
        raise ValueError("Relationship cases cross session boundaries")
    long_metrics = direction_metrics(cases, side="LONG")
    short_metrics = direction_metrics(cases, side="SHORT")
    long_mean = float(long_metrics["mean_net_return_basis_points"])
    short_mean = float(short_metrics["mean_net_return_basis_points"])
    selected_side: Side = "LONG" if long_mean >= short_mean else "SHORT"
    selected_metrics = long_metrics if selected_side == "LONG" else short_metrics
    selected_returns = [
        case.outcome.for_side(selected_side).net_return_basis_points
        for case in cases
    ]
    week_clusters = {
        case.iso_week_key for case in cases
    }
    prevalence = 100 * len(cases) / total_session_cases
    years_with_10 = sum(
        sum(case.session_date.year == year for case in cases) >= 10
        for year in development_years
    )
    cot_reports = {
        observation.cot_report_id
        for case in cases
        for feature_id in feature_ids
        if (observation := case.features.get(feature_id)) is not None
        and observation.cot_report_id is not None
    }
    involves_cot = any(
        case.features.get(feature_id) is not None
        and case.features[feature_id].family_code == "POSITIONING"
        for case in cases
        for feature_id in feature_ids
    )
    support_failures: list[str] = []
    if len(cases) < minimum_cases:
        support_failures.append("INSUFFICIENT_CASES")
    if prevalence > maximum_prevalence_pct:
        support_failures.append("STATE_TOO_BROAD")
    if len(week_clusters) < minimum_week_clusters:
        support_failures.append("INSUFFICIENT_WEEK_CLUSTERS")
    if years_with_10 < minimum_years_with_10_cases:
        support_failures.append("INSUFFICIENT_YEAR_SUPPORT")
    if involves_cot and len(cot_reports) < cot_minimum_reports:
        support_failures.append("INSUFFICIENT_COT_REPORTS")
    support_eligible = not support_failures

    bootstrap_ci = cluster_bootstrap_mean_ci(
        cases,
        side=selected_side,
        replications=bootstrap_replications,
        seed_material=(
            f"{manifest_hash}|{session_code}|{relationship_id}|{state}"
        ),
    )
    p_value = selection_adjusted_p_value(selected_returns)
    selected_baseline = same_session_baselines[selected_side]
    baseline_mean = float(
        selected_baseline["mean_net_return_basis_points"]
    )
    year_results: dict[str, dict[str, Any]] = {}
    positive_years = 0
    adequate_years = 0
    for year in development_years:
        year_cases = [
            case for case in cases if case.session_date.year == year
        ]
        year_metrics = direction_metrics(year_cases, side=selected_side)
        adequate = len(year_cases) >= 10
        positive = (
            adequate
            and float(year_metrics["mean_net_return_basis_points"]) > 0
        )
        adequate_years += int(adequate)
        positive_years += int(positive)
        year_results[str(year)] = {
            **year_metrics,
            "adequate_support": adequate,
            "positive_mean": positive,
        }
    half_results: dict[str, dict[str, Any]] = {}
    positive_halves = 0
    for half in ("EARLY", "LATE"):
        half_cases = [
            case for case in cases if case.chronological_half == half
        ]
        metrics = direction_metrics(half_cases, side=selected_side)
        positive = (
            bool(half_cases)
            and float(metrics["mean_net_return_basis_points"]) > 0
        )
        positive_halves += int(positive)
        half_results[half] = {
            **metrics,
            "positive_mean": positive,
        }
    stability_flag = (
        positive_halves == 2
        and positive_years >= 2
        and adequate_years >= minimum_years_with_10_cases
    )
    return {
        "relationship_type": relationship_type,
        "relationship_id": relationship_id,
        "state": state,
        "feature_ids": list(feature_ids),
        "session_code": session_code,
        "case_count": len(cases),
        "prevalence_pct": _rounded(prevalence),
        "iso_week_cluster_count": len(week_clusters),
        "distinct_cot_report_count": len(cot_reports),
        "involves_cot": involves_cot,
        "support_eligible": support_eligible,
        "support_failures": support_failures,
        "directions": {
            "LONG": long_metrics,
            "SHORT": short_metrics,
        },
        "selected_direction": selected_side,
        "selected_metrics": selected_metrics,
        "same_session_same_direction_baseline": dict(selected_baseline),
        "excess_mean_net_return_vs_baseline_bps": _rounded(
            float(selected_metrics["mean_net_return_basis_points"])
            - baseline_mean
        ),
        "cluster_bootstrap_95pct_ci_basis_points": bootstrap_ci,
        "selection_adjusted_p_value": _rounded(p_value),
        "benjamini_hochberg_q_value": None,
        "development_years": year_results,
        "positive_development_year_count": positive_years,
        "chronological_halves": half_results,
        "positive_chronological_half_count": positive_halves,
        "stability_flag": stability_flag,
        "discovery_lead": False,
    }


def cluster_bootstrap_mean_ci(
    cases: Sequence[DevelopmentCase],
    *,
    side: Side,
    replications: int,
    seed_material: str,
) -> list[float]:
    if not cases:
        return [0.0, 0.0]
    clusters: dict[str, list[float]] = defaultdict(list)
    for case in cases:
        clusters[case.iso_week_key].append(
            case.outcome.for_side(side).net_return_basis_points
        )
    cluster_summaries = [
        (math.fsum(values), len(values))
        for _, values in sorted(clusters.items())
    ]
    if len(cluster_summaries) == 1 or replications <= 0:
        mean = statistics.fmean(
            case.outcome.for_side(side).net_return_basis_points
            for case in cases
        )
        return [_rounded(mean), _rounded(mean)]
    seed = int.from_bytes(
        hashlib.sha256(seed_material.encode("utf-8")).digest()[:8],
        "big",
    )
    generator = random.Random(seed)
    cluster_count = len(cluster_summaries)
    means: list[float] = []
    for _ in range(replications):
        total = 0.0
        observations = 0
        for _ in range(cluster_count):
            cluster_total, cluster_observations = cluster_summaries[
                generator.randrange(cluster_count)
            ]
            total += cluster_total
            observations += cluster_observations
        means.append(total / observations)
    return [
        _rounded(quantile_type_7(means, 0.025)),
        _rounded(quantile_type_7(means, 0.975)),
    ]


def selection_adjusted_p_value(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 1.0
    mean = statistics.fmean(values)
    standard_deviation = statistics.stdev(values)
    if standard_deviation == 0:
        return 0.0 if mean > 0 else 1.0
    standard_error = standard_deviation / math.sqrt(len(values))
    z_score = mean / standard_error
    one_sided = 1 - NormalDist().cdf(z_score)
    return min(1.0, 2 * one_sided)


def apply_benjamini_hochberg(
    records: Sequence[dict[str, Any]],
) -> None:
    eligible = [
        record
        for record in records
        if record["support_eligible"]
    ]
    if not eligible:
        return
    ordered = sorted(
        eligible,
        key=lambda item: (
            float(item["selection_adjusted_p_value"]),
            item["relationship_id"],
            item["state"],
        ),
    )
    total = len(ordered)
    running = 1.0
    for reverse_index in range(total - 1, -1, -1):
        rank = reverse_index + 1
        raw = (
            float(ordered[reverse_index]["selection_adjusted_p_value"])
            * total
            / rank
        )
        running = min(running, raw)
        ordered[reverse_index]["benjamini_hochberg_q_value"] = _rounded(
            min(1.0, running)
        )


def apply_discovery_lead_flags(
    records: Sequence[dict[str, Any]],
    *,
    q_threshold: float,
) -> None:
    for record in records:
        selected = record["selected_metrics"]
        q_value = record["benjamini_hochberg_q_value"]
        record["discovery_lead"] = bool(
            record["support_eligible"]
            and float(selected["mean_net_return_basis_points"]) > 0
            and selected["profit_factor"] is not None
            and float(selected["profit_factor"]) > 1
            and float(
                record["excess_mean_net_return_vs_baseline_bps"]
            )
            > 0
            and record["stability_flag"]
            and q_value is not None
            and float(q_value) <= q_threshold
        )


def relationship_rank_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    lower_ci = float(
        record["cluster_bootstrap_95pct_ci_basis_points"][0]
    )
    mean = float(
        record["selected_metrics"]["mean_net_return_basis_points"]
    )
    return (
        -int(bool(record["support_eligible"])),
        -lower_ci,
        -mean,
        -int(record["case_count"]),
        str(record["relationship_id"]),
        str(record["state"]),
    )


def feature_coverage(
    cases: Sequence[DevelopmentCase],
    *,
    feature_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for feature_id in sorted(feature_ids):
        observations = [
            case.features[feature_id]
            for case in cases
            if feature_id in case.features
        ]
        known = [
            observation
            for observation in observations
            if observation.state != "UNKNOWN"
        ]
        states = Counter(observation.state for observation in observations)
        output[feature_id] = {
            "cases": len(cases),
            "known": len(known),
            "unknown": len(cases) - len(known),
            "coverage_pct": _percentage(len(known), len(cases)),
            "state_counts": dict(sorted(states.items())),
        }
    return output


def _empty_direction_metrics() -> dict[str, Any]:
    return {
        "observations": 0,
        "net_win_rate_pct": None,
        "mean_net_pnl_usd_per_ounce": None,
        "median_net_pnl_usd_per_ounce": None,
        "mean_net_return_basis_points": None,
        "normal_95pct_ci_basis_points": [None, None],
        "total_net_pnl_usd_per_ounce": 0.0,
        "profit_factor": None,
        "return_standard_deviation_basis_points": None,
    }


def _percentage(numerator: int, denominator: int) -> float | None:
    return _rounded(100 * numerator / denominator) if denominator else None


def _rounded(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None
