from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from gold_intel.backtesting.casebook_relationships import quantile_type_7

WALK_FORWARD_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_WALK_FORWARD_V0_1"
WALK_FORWARD_SCHEMA_VERSION = "gold-casebook-discovery-v2-walk-forward-schema-0.1.0"
PASS_VERDICT = "PASS_INTERNAL_WALK_FORWARD_STABILITY"
REJECT_VERDICT = "REJECT_INTERNAL_WALK_FORWARD_STABILITY"

Side = Literal["LONG", "SHORT"]
Bias = Literal["LONG", "SHORT", "NO_BIAS"]


@dataclass(frozen=True, slots=True)
class WalkForwardCase:
    case_id: str
    case_record_hash: str
    session_date: date
    decision_at: datetime
    feature_state: str
    raw_percent_change: float | None
    feature_source_key: str | None
    reference_entry_price: float
    gross_move_usd_per_ounce: float
    cost_usd_per_ounce: float
    long_net_pnl_usd_per_ounce: float
    long_net_return_basis_points: float
    short_net_pnl_usd_per_ounce: float
    short_net_return_basis_points: float

    @property
    def iso_week_key(self) -> str:
        value = self.session_date.isocalendar()
        return f"{value.year:04d}-W{value.week:02d}"

    @property
    def bias(self) -> Bias:
        if self.feature_state == "POSITIVE":
            return "LONG"
        if self.feature_state == "NEGATIVE":
            return "SHORT"
        return "NO_BIAS"


@dataclass(frozen=True, slots=True)
class ReturnObservation:
    case_id: str
    session_date: date
    side: Side
    net_pnl_usd_per_ounce: float
    net_return_basis_points: float

    @property
    def iso_week_key(self) -> str:
        value = self.session_date.isocalendar()
        return f"{value.year:04d}-W{value.week:02d}"


def selected_observation(
    case: WalkForwardCase,
    *,
    cost_multiplier: float = 1.0,
) -> ReturnObservation | None:
    if not math.isfinite(cost_multiplier) or cost_multiplier < 0:
        raise ValueError("Cost multiplier must be finite and non-negative")
    bias = case.bias
    if bias == "NO_BIAS":
        return None
    gross = case.gross_move_usd_per_ounce if bias == "LONG" else -case.gross_move_usd_per_ounce
    net_pnl = gross - cost_multiplier * case.cost_usd_per_ounce
    net_return = (
        10_000 * net_pnl / case.reference_entry_price if case.reference_entry_price else 0.0
    )
    expected_pnl = (
        case.long_net_pnl_usd_per_ounce if bias == "LONG" else case.short_net_pnl_usd_per_ounce
    )
    expected_return = (
        case.long_net_return_basis_points if bias == "LONG" else case.short_net_return_basis_points
    )
    if cost_multiplier == 1.0 and (
        not math.isclose(net_pnl, expected_pnl, abs_tol=1e-8)
        or not math.isclose(net_return, expected_return, abs_tol=1e-8)
    ):
        raise ValueError(f"Frozen outcome identity changed: {case.case_id}")
    return ReturnObservation(
        case_id=case.case_id,
        session_date=case.session_date,
        side=bias,
        net_pnl_usd_per_ounce=net_pnl,
        net_return_basis_points=net_return,
    )


def control_observation(
    case: WalkForwardCase,
    *,
    side: Side,
) -> ReturnObservation:
    return ReturnObservation(
        case_id=case.case_id,
        session_date=case.session_date,
        side=side,
        net_pnl_usd_per_ounce=(
            case.long_net_pnl_usd_per_ounce if side == "LONG" else case.short_net_pnl_usd_per_ounce
        ),
        net_return_basis_points=(
            case.long_net_return_basis_points
            if side == "LONG"
            else case.short_net_return_basis_points
        ),
    )


def observation_metrics(
    observations: Sequence[ReturnObservation],
) -> dict[str, Any]:
    if not observations:
        return {
            "observations": 0,
            "long_direction_count": 0,
            "short_direction_count": 0,
            "net_win_rate_pct": None,
            "mean_net_pnl_usd_per_ounce": None,
            "median_net_pnl_usd_per_ounce": None,
            "total_net_pnl_usd_per_ounce": 0.0,
            "mean_net_return_basis_points": None,
            "median_net_return_basis_points": None,
            "profit_factor": None,
        }
    pnl = [item.net_pnl_usd_per_ounce for item in observations]
    returns = [item.net_return_basis_points for item in observations]
    gains = math.fsum(value for value in pnl if value > 0)
    losses = math.fsum(value for value in pnl if value < 0)
    return {
        "observations": len(observations),
        "long_direction_count": sum(item.side == "LONG" for item in observations),
        "short_direction_count": sum(item.side == "SHORT" for item in observations),
        "net_win_rate_pct": _rounded(100 * sum(value > 0 for value in pnl) / len(pnl)),
        "mean_net_pnl_usd_per_ounce": _rounded(statistics.fmean(pnl)),
        "median_net_pnl_usd_per_ounce": _rounded(statistics.median(pnl)),
        "total_net_pnl_usd_per_ounce": _rounded(math.fsum(pnl)),
        "mean_net_return_basis_points": _rounded(statistics.fmean(returns)),
        "median_net_return_basis_points": _rounded(statistics.median(returns)),
        "profit_factor": (_rounded(gains / abs(losses)) if losses < 0 else None),
    }


def cluster_bootstrap_mean_ci(
    observations: Sequence[ReturnObservation],
    *,
    replications: int,
    seed_material: str,
) -> list[float]:
    if not observations:
        return [0.0, 0.0]
    clusters = _cluster_summaries(observations)
    if len(clusters) == 1 or replications <= 0:
        mean = statistics.fmean(item.net_return_basis_points for item in observations)
        return [_rounded(mean), _rounded(mean)]
    generator = random.Random(_seed(seed_material))
    values: list[float] = []
    for _ in range(replications):
        total = 0.0
        count = 0
        for _ in range(len(clusters)):
            cluster_total, cluster_count = clusters[generator.randrange(len(clusters))]
            total += cluster_total
            count += cluster_count
        values.append(total / count)
    return [
        _rounded(quantile_type_7(values, 0.025)),
        _rounded(quantile_type_7(values, 0.975)),
    ]


def cluster_sign_flip_p_value(
    observations: Sequence[ReturnObservation],
    *,
    replications: int,
    seed_material: str,
) -> float:
    if not observations or replications <= 0:
        return 1.0
    clusters = _cluster_summaries(observations)
    observed = math.fsum(total for total, _ in clusters) / sum(count for _, count in clusters)
    if observed <= 0:
        return 1.0
    generator = random.Random(_seed(seed_material))
    denominator = sum(count for _, count in clusters)
    exceedances = 0
    for _ in range(replications):
        randomized = (
            math.fsum(total if generator.getrandbits(1) else -total for total, _ in clusters)
            / denominator
        )
        exceedances += randomized >= observed
    return _rounded((exceedances + 1) / (replications + 1))


def build_window_report(
    cases: Sequence[WalkForwardCase],
    *,
    manifest_hash: str,
    candidate_code: str,
    window_id: str,
    bootstrap_replications: int,
    sign_flip_replications: int,
    stress_multiplier: float,
) -> dict[str, Any]:
    ordered = sorted(cases, key=lambda item: (item.decision_at, item.case_id))
    directional = [case for case in ordered if case.bias != "NO_BIAS"]
    selected = [
        observation
        for case in directional
        if (
            observation := selected_observation(
                case,
                cost_multiplier=1.0,
            )
        )
        is not None
    ]
    stressed = [
        observation
        for case in directional
        if (
            observation := selected_observation(
                case,
                cost_multiplier=stress_multiplier,
            )
        )
        is not None
    ]
    controls = {
        f"ALWAYS_{side}": observation_metrics(
            [control_observation(case, side=side) for case in directional]
        )
        for side in ("LONG", "SHORT")
    }
    best_control = max(
        controls,
        key=lambda key: (
            float(controls[key]["mean_net_return_basis_points"]),
            key,
        ),
    )
    selector_metrics = observation_metrics(selected)
    state_results: dict[str, Any] = {}
    for state, side in (("POSITIVE", "LONG"), ("NEGATIVE", "SHORT")):
        state_cases = [case for case in directional if case.feature_state == state]
        state_observations = [
            observation
            for case in state_cases
            if (observation := selected_observation(case)) is not None
        ]
        state_results[state] = {
            "bias": side,
            "case_count": len(state_cases),
            "iso_week_cluster_count": len({case.iso_week_key for case in state_cases}),
            "metrics": observation_metrics(state_observations),
        }
    return {
        "window_id": window_id,
        "total_case_count": len(ordered),
        "directional_case_count": len(directional),
        "no_bias_count": len(ordered) - len(directional),
        "state_results": state_results,
        "selector_metrics": selector_metrics,
        "matched_unconditional_controls": controls,
        "best_matched_control": best_control,
        "excess_mean_net_return_vs_best_control_bps": _rounded(
            float(selector_metrics["mean_net_return_basis_points"])
            - float(controls[best_control]["mean_net_return_basis_points"])
        ),
        "cost_stress": {
            "multiplier": stress_multiplier,
            "metrics": observation_metrics(stressed),
        },
        "cluster_bootstrap_95pct_ci_mean_net_return_basis_points": (
            cluster_bootstrap_mean_ci(
                selected,
                replications=bootstrap_replications,
                seed_material=(f"{manifest_hash}|{candidate_code}|{window_id}|BOOTSTRAP"),
            )
        ),
        "cluster_sign_flip_p_value": cluster_sign_flip_p_value(
            selected,
            replications=sign_flip_replications,
            seed_material=(f"{manifest_hash}|{candidate_code}|{window_id}|SIGN_FLIP"),
        ),
    }


def evaluate_training_gates(
    report: Mapping[str, Any],
    *,
    minimum_directional_cases: int,
    minimum_state_cases: int,
    minimum_state_week_clusters: int,
) -> dict[str, Any]:
    return _evaluate_window_gates(
        report,
        minimum_directional_cases=minimum_directional_cases,
        minimum_state_cases=minimum_state_cases,
        minimum_state_week_clusters=minimum_state_week_clusters,
        require_cost_stress=False,
    )


def evaluate_test_gates(
    report: Mapping[str, Any],
    *,
    minimum_directional_cases: int,
    minimum_state_cases: int,
    minimum_state_week_clusters: int,
) -> dict[str, Any]:
    return _evaluate_window_gates(
        report,
        minimum_directional_cases=minimum_directional_cases,
        minimum_state_cases=minimum_state_cases,
        minimum_state_week_clusters=minimum_state_week_clusters,
        require_cost_stress=True,
    )


def evaluate_aggregate_gates(
    folds: Sequence[Mapping[str, Any]],
    *,
    aggregate_report: Mapping[str, Any],
    q_threshold: float,
    integrity_passed: bool,
) -> dict[str, Any]:
    gates = [
        _gate(
            "G01_POINT_IN_TIME_INTEGRITY",
            integrity_passed,
            {"integrity_passed": integrity_passed},
        ),
        _gate(
            "G02_ALL_TRAINING_BOUNDARIES_PASS",
            all(bool(item["training_gates"]["passed"]) for item in folds),
            {str(item["fold_id"]): item["training_gates"]["passed"] for item in folds},
        ),
        _gate(
            "G03_ALL_FORWARD_TEST_FOLDS_PASS",
            all(bool(item["test_gates"]["passed"]) for item in folds),
            {str(item["fold_id"]): item["test_gates"]["passed"] for item in folds},
        ),
        _gate(
            "G04_AGGREGATE_BOOTSTRAP_LOWER_BOUND_POSITIVE",
            float(aggregate_report["cluster_bootstrap_95pct_ci_mean_net_return_basis_points"][0])
            > 0,
            {
                "cluster_bootstrap_95pct_ci_mean_net_return_basis_points": (
                    aggregate_report["cluster_bootstrap_95pct_ci_mean_net_return_basis_points"]
                )
            },
        ),
        _gate(
            "G05_ONE_CANDIDATE_BH_Q_VALUE",
            float(aggregate_report["benjamini_hochberg_q_value"]) <= q_threshold,
            {
                "benjamini_hochberg_q_value": aggregate_report["benjamini_hochberg_q_value"],
                "maximum": q_threshold,
            },
        ),
    ]
    failures = [str(item["gate_id"]) for item in gates if not bool(item["passed"])]
    return {
        "passed": not failures,
        "failed_gate_ids": failures,
        "passed_gate_count": len(gates) - len(failures),
        "total_gate_count": len(gates),
        "gates": gates,
        "verdict": PASS_VERDICT if not failures else REJECT_VERDICT,
    }


def _evaluate_window_gates(
    report: Mapping[str, Any],
    *,
    minimum_directional_cases: int,
    minimum_state_cases: int,
    minimum_state_week_clusters: int,
    require_cost_stress: bool,
) -> dict[str, Any]:
    states = report["state_results"]
    metrics = report["selector_metrics"]
    gates = [
        _gate(
            "DIRECTIONAL_CASE_SUPPORT",
            int(report["directional_case_count"]) >= minimum_directional_cases,
            {
                "actual": report["directional_case_count"],
                "minimum": minimum_directional_cases,
            },
        ),
        _gate(
            "DIRECTIONAL_STATE_SUPPORT",
            all(
                int(states[state]["case_count"]) >= minimum_state_cases
                for state in ("POSITIVE", "NEGATIVE")
            ),
            {
                state: {
                    "actual": states[state]["case_count"],
                    "minimum": minimum_state_cases,
                }
                for state in ("POSITIVE", "NEGATIVE")
            },
        ),
        _gate(
            "DIRECTIONAL_STATE_WEEK_SUPPORT",
            all(
                int(states[state]["iso_week_cluster_count"]) >= minimum_state_week_clusters
                for state in ("POSITIVE", "NEGATIVE")
            ),
            {
                state: {
                    "actual": states[state]["iso_week_cluster_count"],
                    "minimum": minimum_state_week_clusters,
                }
                for state in ("POSITIVE", "NEGATIVE")
            },
        ),
        _gate(
            "MEAN_NET_RETURN_POSITIVE",
            _positive(metrics["mean_net_return_basis_points"]),
            {"mean_net_return_basis_points": metrics["mean_net_return_basis_points"]},
        ),
        _gate(
            "PROFIT_FACTOR_ABOVE_ONE",
            _above_one(metrics["profit_factor"]),
            {"profit_factor": metrics["profit_factor"]},
        ),
        _gate(
            "BEATS_BEST_MATCHED_CONTROL",
            _positive(report["excess_mean_net_return_vs_best_control_bps"]),
            {
                "best_control": report["best_matched_control"],
                "excess_mean_net_return_basis_points": report[
                    "excess_mean_net_return_vs_best_control_bps"
                ],
            },
        ),
        _gate(
            "DIRECTION_MAPPING_CONSISTENCY",
            all(
                _positive(states[state]["metrics"]["mean_net_return_basis_points"])
                for state in ("POSITIVE", "NEGATIVE")
            ),
            {
                state: states[state]["metrics"]["mean_net_return_basis_points"]
                for state in ("POSITIVE", "NEGATIVE")
            },
        ),
    ]
    if require_cost_stress:
        stress = report["cost_stress"]
        gates.append(
            _gate(
                "COST_STRESS_MEAN_PNL_POSITIVE",
                _positive(stress["metrics"]["mean_net_pnl_usd_per_ounce"]),
                {
                    "multiplier": stress["multiplier"],
                    "mean_net_pnl_usd_per_ounce": stress["metrics"]["mean_net_pnl_usd_per_ounce"],
                },
            )
        )
    failures = [str(item["gate_id"]) for item in gates if not bool(item["passed"])]
    return {
        "passed": not failures,
        "failed_gate_ids": failures,
        "passed_gate_count": len(gates) - len(failures),
        "total_gate_count": len(gates),
        "gates": gates,
    }


def _cluster_summaries(
    observations: Sequence[ReturnObservation],
) -> list[tuple[float, int]]:
    clusters: dict[str, list[float]] = defaultdict(list)
    for item in observations:
        clusters[item.iso_week_key].append(item.net_return_basis_points)
    return [(math.fsum(values), len(values)) for _, values in sorted(clusters.items())]


def _seed(material: str) -> int:
    return int.from_bytes(
        hashlib.sha256(material.encode()).digest()[:8],
        "big",
    )


def _gate(
    gate_id: str,
    passed: bool,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "passed": bool(passed),
        "evidence": dict(evidence),
    }


def _positive(value: Any) -> bool:
    return value is not None and float(value) > 0


def _above_one(value: Any) -> bool:
    return value is not None and float(value) > 1


def _rounded(value: float) -> float:
    return round(float(value), 8)
