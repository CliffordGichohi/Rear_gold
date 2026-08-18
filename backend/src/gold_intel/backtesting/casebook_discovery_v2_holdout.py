from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.backtesting.casebook_discovery_v2_walk_forward import (
    ReturnObservation,
    WalkForwardCase,
    cluster_bootstrap_mean_ci,
    cluster_sign_flip_p_value,
    control_observation,
    observation_metrics,
    selected_observation,
)

M6_QUOTE_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_M6_ZN_QUOTE_V0_1"
M6_QUOTE_SCHEMA_VERSION = "gold-casebook-discovery-v2-m6-zn-quote-schema-0.1.0"
M6_HOLDOUT_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_HOLDOUT_V0_1"
M6_HOLDOUT_SCHEMA_VERSION = "gold-casebook-discovery-v2-holdout-schema-0.1.0"
CANDIDATE_CODE = "LONDON_ZN_4H_POSTHOC_V0_1"
PASS_VERDICT = "PASS_CALENDAR_2025_HOLDOUT"
REJECT_VERDICT = "REJECT_CALENDAR_2025_HOLDOUT"
EXPECTED_READINESS_GATE_IDS = (
    "R01_XAUUSD_TIMESTAMP_COVERAGE",
    "R02_ZN_LICENSED_ARCHIVE_SEALED",
    "R03_ZN_ROLL_LINEAGE_SEALED",
    "R04_ZN_TIMESTAMP_ONLY_CASE_COVERAGE",
    "R05_PREOPEN_AUDIT_CLEAN",
)
EXPECTED_EVALUATION_GATE_IDS = (
    "G01_POINT_IN_TIME_AND_LINEAGE_INTEGRITY",
    "G02_DIRECTIONAL_CASE_SUPPORT",
    "G03_DIRECTIONAL_STATE_SUPPORT",
    "G04_DIRECTIONAL_STATE_WEEK_SUPPORT",
    "G05_MEAN_NET_RETURN_POSITIVE",
    "G06_PROFIT_FACTOR_ABOVE_ONE",
    "G07_BEATS_BEST_MATCHED_CONTROL",
    "G08_DIRECTION_MAPPING_CONSISTENCY",
    "G09_CHRONOLOGICAL_HALF_STABILITY",
    "G10_COST_STRESS",
    "G11_CLUSTER_BOOTSTRAP_LOWER_BOUND",
    "G12_MULTIPLICITY_AWARE_Q_VALUE",
)

EXPECTED_ZN_QUOTE_REQUEST: dict[str, Any] = {
    "dataset": "GLBX.MDP3",
    "symbols": ["ZN.v.0"],
    "schema": "ohlcv-1m",
    "stype_in": "continuous",
    "start": "2025-01-01T00:00:00Z",
    "end": "2026-01-01T00:00:00Z",
}

EXPECTED_ZN_BATCH_REQUEST: dict[str, Any] = {
    **EXPECTED_ZN_QUOTE_REQUEST,
    "stype_out": "instrument_id",
    "encoding": "dbn",
    "compression": "zstd",
    "split_duration": "year",
    "split_symbols": False,
    "delivery": "download",
}


@dataclass(frozen=True, slots=True)
class HoldoutCase:
    case_id: str
    case_record_hash: str
    session_date: date
    decision_at: datetime
    chronological_half: str
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

    def as_walk_forward_case(self) -> WalkForwardCase:
        return WalkForwardCase(
            case_id=self.case_id,
            case_record_hash=self.case_record_hash,
            session_date=self.session_date,
            decision_at=self.decision_at,
            feature_state=self.feature_state,
            raw_percent_change=self.raw_percent_change,
            feature_source_key=self.feature_source_key,
            reference_entry_price=self.reference_entry_price,
            gross_move_usd_per_ounce=self.gross_move_usd_per_ounce,
            cost_usd_per_ounce=self.cost_usd_per_ounce,
            long_net_pnl_usd_per_ounce=self.long_net_pnl_usd_per_ounce,
            long_net_return_basis_points=self.long_net_return_basis_points,
            short_net_pnl_usd_per_ounce=self.short_net_pnl_usd_per_ounce,
            short_net_return_basis_points=self.short_net_return_basis_points,
        )


@dataclass(frozen=True, slots=True)
class ZnHoldoutSample:
    source_record_id: str
    source_file_sha256: str
    source_row_ordinal: int
    open_time: datetime
    available_at: datetime
    continuous_symbol: str
    instrument_id: int
    underlying_raw_symbol: str
    close: float


@dataclass(frozen=True, slots=True)
class ZnHoldoutFeature:
    state: str
    reason_code: str
    raw_absolute_change: float | None
    raw_percent_change: float | None
    source_key: str | None
    current: ZnHoldoutSample | None
    reference: ZnHoldoutSample | None

    @property
    def bias(self) -> str:
        if self.state == "POSITIVE":
            return "LONG"
        if self.state == "NEGATIVE":
            return "SHORT"
        return "NO_BIAS"


@dataclass(frozen=True, slots=True)
class ZnHoldoutSeries:
    samples: tuple[ZnHoldoutSample, ...]
    available_times: tuple[datetime, ...]

    @classmethod
    def from_samples(
        cls,
        samples: Sequence[ZnHoldoutSample],
    ) -> ZnHoldoutSeries:
        frozen = tuple(samples)
        available = tuple(item.available_at for item in frozen)
        if any(right <= left for left, right in zip(available, available[1:], strict=False)):
            raise ValueError("ZN samples must be strictly ordered by available_at")
        return cls(samples=frozen, available_times=available)

    def feature_at(
        self,
        decision_at: datetime,
        *,
        current_staleness_maximum: timedelta = timedelta(hours=8),
        reference_staleness_maximum: timedelta = timedelta(days=3),
    ) -> ZnHoldoutFeature:
        if decision_at.tzinfo is None:
            raise ValueError("ZN feature decision_at must be timezone-aware")
        if not self.samples:
            return _unknown_zn_feature("NO_ELIGIBLE_CURRENT")

        current_index = bisect.bisect_right(self.available_times, decision_at) - 1
        if current_index < 0:
            return _unknown_zn_feature("NO_ELIGIBLE_CURRENT")
        current = self.samples[current_index]
        if decision_at - current.available_at > current_staleness_maximum:
            return _unknown_zn_feature("CURRENT_STALE", current=current)

        reference_target = decision_at - timedelta(hours=4)
        reference_index = bisect.bisect_right(self.available_times, reference_target) - 1
        if reference_index < 0:
            return _unknown_zn_feature(
                "NO_ELIGIBLE_REFERENCE",
                current=current,
            )
        reference = self.samples[reference_index]
        if reference_target - reference.available_at > reference_staleness_maximum:
            return _unknown_zn_feature(
                "REFERENCE_STALE",
                current=current,
                reference=reference,
            )
        if current.instrument_id != reference.instrument_id:
            return _unknown_zn_feature(
                "CONTINUOUS_CONTRACT_ROLL",
                current=current,
                reference=reference,
            )
        if (
            not math.isfinite(current.close)
            or not math.isfinite(reference.close)
            or reference.close == 0
        ):
            return _unknown_zn_feature(
                "MISSING_OR_NONFINITE_CHANGE",
                current=current,
                reference=reference,
            )

        absolute = current.close - reference.close
        percent = round(100 * absolute / reference.close, 8)
        state = "POSITIVE" if percent > 0 else "NEGATIVE" if percent < 0 else "FLAT"
        return ZnHoldoutFeature(
            state=state,
            reason_code=f"ZN_4H_{state}",
            raw_absolute_change=round(absolute, 8),
            raw_percent_change=percent,
            source_key=(f"ZN.v.0|4_HOURS|{reference.source_record_id}|{current.source_record_id}"),
            current=current,
            reference=reference,
        )


def materialize_zn_4h_feature(
    samples: Sequence[ZnHoldoutSample],
    *,
    decision_at: datetime,
    current_staleness_maximum: timedelta = timedelta(hours=8),
    reference_staleness_maximum: timedelta = timedelta(days=3),
) -> ZnHoldoutFeature:
    """Apply the frozen point-in-time ZN four-hour sign feature.

    Selection is based on ``available_at``, never the interval timestamp.
    The percentage-change value matches the development feature; only its
    sign is consumed by the frozen candidate.
    """

    if decision_at.tzinfo is None:
        raise ValueError("ZN feature decision_at must be timezone-aware")
    return ZnHoldoutSeries.from_samples(samples).feature_at(
        decision_at,
        current_staleness_maximum=current_staleness_maximum,
        reference_staleness_maximum=reference_staleness_maximum,
    )


def _unknown_zn_feature(
    reason_code: str,
    *,
    current: ZnHoldoutSample | None = None,
    reference: ZnHoldoutSample | None = None,
) -> ZnHoldoutFeature:
    return ZnHoldoutFeature(
        state="UNKNOWN",
        reason_code=reason_code,
        raw_absolute_change=None,
        raw_percent_change=None,
        source_key=None,
        current=current,
        reference=reference,
    )


def embedded_manifest_hash(document: Mapping[str, Any]) -> str:
    content = {key: value for key, value in document.items() if key != "manifest_hash"}
    return canonical_hash(content)


def validate_quote_manifest(document: Mapping[str, Any]) -> str:
    supplied_hash = str(document.get("manifest_hash", ""))
    if not supplied_hash or embedded_manifest_hash(document) != supplied_hash:
        raise ValueError("M6 quote manifest hash mismatch")
    if document.get("manifest_version") != ("GOLD_CASEBOOK_DISCOVERY_V2_M6_ZN_QUOTE_MANIFEST_V0_1"):
        raise ValueError("Unexpected M6 quote manifest version")
    if document.get("milestone") != "V2_M6_PREOPEN_ZN_COST_ESTIMATE":
        raise ValueError("Unexpected M6 quote milestone")
    if document.get("request") != EXPECTED_ZN_QUOTE_REQUEST:
        raise ValueError("M6 quote request changed")

    boundary = document.get("authorization_boundary")
    if not isinstance(boundary, Mapping):
        raise ValueError("M6 quote authorization boundary is missing")
    if boundary.get("current_authorization") != "METADATA_COST_ESTIMATE_ONLY":
        raise ValueError("M6 quote exceeds the current authorization")
    if boundary.get("paid_submission_authorized") is not False:
        raise ValueError("Paid submission must remain unauthorized")
    if boundary.get("market_value_access_authorized") is not False:
        raise ValueError("Market-value access must remain unauthorized")
    if boundary.get("holdout_outcome_access_authorized") is not False:
        raise ValueError("Holdout outcome access must remain unauthorized")

    prohibited = document.get("prohibited")
    if not isinstance(prohibited, Mapping) or not prohibited:
        raise ValueError("M6 quote prohibited actions are missing")
    if any(value is not True for value in prohibited.values()):
        raise ValueError("Every prohibited M6 quote action must remain active")
    return supplied_hash


def quote_request_fingerprint() -> str:
    return canonical_hash(EXPECTED_ZN_QUOTE_REQUEST)


def batch_request_fingerprint() -> str:
    return canonical_hash(EXPECTED_ZN_BATCH_REQUEST)


def validate_holdout_manifest(document: Mapping[str, Any]) -> str:
    supplied_hash = str(document.get("manifest_hash", ""))
    if not supplied_hash or embedded_manifest_hash(document) != supplied_hash:
        raise ValueError("M6 holdout manifest hash mismatch")
    if document.get("manifest_version") != ("GOLD_CASEBOOK_DISCOVERY_V2_M6_HOLDOUT_MANIFEST_V0_1"):
        raise ValueError("Unexpected M6 holdout manifest version")
    if document.get("milestone") != "V2_M6_CALENDAR_2025_HOLDOUT":
        raise ValueError("Unexpected M6 holdout milestone")
    acquisition = document.get("acquisition")
    if not isinstance(acquisition, Mapping):
        raise ValueError("M6 acquisition definition is missing")
    if acquisition.get("request") != EXPECTED_ZN_BATCH_REQUEST:
        raise ValueError("M6 acquisition request changed")
    if float(acquisition.get("maximum_cost_usd", -1)) != 1.25:
        raise ValueError("M6 acquisition cost cap changed")
    if acquisition.get("paid_submission_authorized") is not True:
        raise ValueError("M6 paid submission is not authorized")
    if document.get("candidate", {}).get("candidate_code") != CANDIDATE_CODE:
        raise ValueError("M6 candidate changed")
    if document.get("candidate", {}).get("rule_table") != {
        "FLAT": "NO_BIAS",
        "NEGATIVE": "SHORT",
        "POSITIVE": "LONG",
        "UNKNOWN": "NO_BIAS",
    }:
        raise ValueError("M6 candidate rule changed")
    if document.get("candidate", {}).get("tuning_permitted") is not False:
        raise ValueError("M6 candidate tuning was enabled")
    evaluation = document["evaluation"]
    if int(evaluation["candidate_family_size"]) != 1:
        raise ValueError("M6 multiplicity family changed")
    if evaluation["all_gates_required"] is not True:
        raise ValueError("M6 no longer requires every gate")
    if tuple(evaluation["gate_ids"]) != EXPECTED_EVALUATION_GATE_IDS:
        raise ValueError("M6 evaluation gates changed")
    if evaluation["thresholds"] != {
        "maximum_q_value": 0.1,
        "minimum_directional_cases": 180,
        "minimum_directional_cases_per_half": 70,
        "minimum_state_cases": 80,
        "minimum_state_iso_week_clusters": 35,
    }:
        raise ValueError("M6 evaluation thresholds changed")
    if evaluation["uncertainty"]["bootstrap_replications"] != 5000:
        raise ValueError("M6 bootstrap replications changed")
    if evaluation["uncertainty"]["sign_flip_replications"] != 20000:
        raise ValueError("M6 sign-flip replications changed")
    readiness = document["readiness"]
    if readiness["all_gates_required"] is not True:
        raise ValueError("M6 no longer requires every readiness gate")
    if tuple(readiness["gate_ids"]) != EXPECTED_READINESS_GATE_IDS:
        raise ValueError("M6 readiness gates changed")
    if float(readiness["minimum_case_coverage_pct"]) != 95.0:
        raise ValueError("M6 readiness coverage threshold changed")
    execution = document["execution"]
    expected_execution = {
        "commission_usd_per_lot_round_turn": 7.0,
        "contract_size_ounces_per_lot": 100.0,
        "cost_stress_multiplier": 1.5,
        "decision_clock_local": "08:00",
        "entry_clock_local": "08:01",
        "exit_clock_local": "12:00",
        "notional_ounces": 1.0,
        "provider": "IC_MARKETS_MT5",
        "slippage_usd_per_ounce_per_side": 0.05,
        "symbol": "XAUUSD",
        "timeframe": "1m",
        "timezone": "Europe/London",
    }
    if any(execution.get(key) != value for key, value in expected_execution.items()):
        raise ValueError("M6 execution changed")
    if document["holdout"]["start_inclusive"] != "2025-01-01T00:00:00Z":
        raise ValueError("M6 holdout start changed")
    if document["holdout"]["end_exclusive"] != "2026-01-01T00:00:00Z":
        raise ValueError("M6 holdout end changed")
    prohibited = document.get("prohibited")
    if not isinstance(prohibited, Mapping) or any(
        value is not True for value in prohibited.values()
    ):
        raise ValueError("M6 prohibited actions changed")
    return supplied_hash


def build_holdout_report(
    cases: list[HoldoutCase],
    *,
    manifest_hash: str,
    bootstrap_replications: int,
    sign_flip_replications: int,
    stress_multiplier: float,
) -> dict[str, Any]:
    ordered = sorted(cases, key=lambda item: (item.decision_at, item.case_id))
    converted = [item.as_walk_forward_case() for item in ordered]
    directional = [item for item in converted if item.bias != "NO_BIAS"]
    selected = _selected(directional)
    stressed = _selected(directional, cost_multiplier=stress_multiplier)
    controls = {
        f"ALWAYS_{side}": observation_metrics(
            [control_observation(item, side=side) for item in directional]
        )
        for side in ("LONG", "SHORT")
    }
    best_control = max(
        controls,
        key=lambda key: (
            _sortable_metric(
                controls[key]["mean_net_return_basis_points"],
            ),
            key,
        ),
    )
    selector_metrics = observation_metrics(selected)
    selector_mean = selector_metrics["mean_net_return_basis_points"]
    control_mean = controls[best_control]["mean_net_return_basis_points"]
    state_results: dict[str, Any] = {}
    for state, side in (("POSITIVE", "LONG"), ("NEGATIVE", "SHORT")):
        state_cases = [item for item in converted if item.feature_state == state]
        state_results[state] = {
            "bias": side,
            "case_count": len(state_cases),
            "iso_week_cluster_count": len(
                {_iso_week_key(item.session_date) for item in state_cases}
            ),
            "metrics": observation_metrics(_selected(state_cases)),
        }
    half_results: dict[str, Any] = {}
    for label in ("EARLY", "LATE"):
        half_cases = [
            converted[index]
            for index, item in enumerate(ordered)
            if item.chronological_half == label and converted[index].bias != "NO_BIAS"
        ]
        half_results[label] = {
            "directional_case_count": len(half_cases),
            "metrics": observation_metrics(_selected(half_cases)),
        }
    bootstrap_seed_material = f"{manifest_hash}|{CANDIDATE_CODE}|BOOTSTRAP"
    sign_flip_seed_material = f"{manifest_hash}|{CANDIDATE_CODE}|SIGN_FLIP"
    p_value = cluster_sign_flip_p_value(
        selected,
        replications=sign_flip_replications,
        seed_material=sign_flip_seed_material,
    )
    return {
        "candidate_code": CANDIDATE_CODE,
        "total_timestamp_complete_case_count": len(ordered),
        "directional_case_count": len(directional),
        "no_bias_count": len(ordered) - len(directional),
        "state_results": state_results,
        "chronological_half_results": half_results,
        "selector_metrics": selector_metrics,
        "matched_unconditional_controls": controls,
        "best_matched_control": best_control,
        "excess_mean_net_return_vs_best_control_bps": (
            _rounded(float(selector_mean) - float(control_mean))
            if selector_mean is not None and control_mean is not None
            else None
        ),
        "cost_stress": {
            "multiplier": stress_multiplier,
            "metrics": observation_metrics(stressed),
        },
        "cluster_bootstrap_95pct_ci_mean_net_return_basis_points": (
            cluster_bootstrap_mean_ci(
                selected,
                replications=bootstrap_replications,
                seed_material=bootstrap_seed_material,
            )
        ),
        "cluster_sign_flip_p_value": p_value,
        "benjamini_hochberg_q_value": p_value,
        "uncertainty": {
            "cluster": "ISO_WEEK_OF_SESSION_DATE",
            "bootstrap_replications": bootstrap_replications,
            "bootstrap_seed_material_sha256": canonical_hash(
                {"seed_material": bootstrap_seed_material}
            ),
            "sign_flip_replications": sign_flip_replications,
            "sign_flip_seed_material_sha256": canonical_hash(
                {"seed_material": sign_flip_seed_material}
            ),
            "candidate_family_size": 1,
            "multiplicity_method": "BENJAMINI_HOCHBERG",
        },
    }


def evaluate_holdout_gates(
    report: Mapping[str, Any],
    *,
    integrity_passed: bool,
    minimum_directional_cases: int = 180,
    minimum_state_cases: int = 80,
    minimum_state_week_clusters: int = 35,
    minimum_half_directional_cases: int = 70,
    maximum_q_value: float = 0.10,
) -> dict[str, Any]:
    states = report["state_results"]
    halves = report["chronological_half_results"]
    metrics = report["selector_metrics"]
    stress = report["cost_stress"]["metrics"]
    controls = report["matched_unconditional_controls"]
    best_control = str(report["best_matched_control"])
    gates = [
        _gate(
            "G01_POINT_IN_TIME_AND_LINEAGE_INTEGRITY",
            integrity_passed,
            {"integrity_passed": integrity_passed},
        ),
        _gate(
            "G02_DIRECTIONAL_CASE_SUPPORT",
            int(report["directional_case_count"]) >= minimum_directional_cases,
            {
                "actual": report["directional_case_count"],
                "minimum": minimum_directional_cases,
            },
        ),
        _gate(
            "G03_DIRECTIONAL_STATE_SUPPORT",
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
            "G04_DIRECTIONAL_STATE_WEEK_SUPPORT",
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
            "G05_MEAN_NET_RETURN_POSITIVE",
            _positive(metrics["mean_net_return_basis_points"]),
            {"mean_net_return_basis_points": metrics["mean_net_return_basis_points"]},
        ),
        _gate(
            "G06_PROFIT_FACTOR_ABOVE_ONE",
            _above_one(metrics["profit_factor"]),
            {"profit_factor": metrics["profit_factor"]},
        ),
        _gate(
            "G07_BEATS_BEST_MATCHED_CONTROL",
            _positive(report["excess_mean_net_return_vs_best_control_bps"]),
            {
                "best_matched_control": best_control,
                "candidate_mean_net_return_basis_points": metrics["mean_net_return_basis_points"],
                "control_mean_net_return_basis_points": controls[best_control][
                    "mean_net_return_basis_points"
                ],
                "excess_mean_net_return_basis_points": report[
                    "excess_mean_net_return_vs_best_control_bps"
                ],
            },
        ),
        _gate(
            "G08_DIRECTION_MAPPING_CONSISTENCY",
            all(
                _positive(states[state]["metrics"]["mean_net_return_basis_points"])
                for state in ("POSITIVE", "NEGATIVE")
            ),
            {
                state: states[state]["metrics"]["mean_net_return_basis_points"]
                for state in ("POSITIVE", "NEGATIVE")
            },
        ),
        _gate(
            "G09_CHRONOLOGICAL_HALF_STABILITY",
            all(
                int(halves[label]["directional_case_count"]) >= minimum_half_directional_cases
                and _positive(halves[label]["metrics"]["mean_net_return_basis_points"])
                for label in ("EARLY", "LATE")
            ),
            {
                label: {
                    "directional_cases": halves[label]["directional_case_count"],
                    "minimum_directional_cases": minimum_half_directional_cases,
                    "mean_net_return_basis_points": halves[label]["metrics"][
                        "mean_net_return_basis_points"
                    ],
                }
                for label in ("EARLY", "LATE")
            },
        ),
        _gate(
            "G10_COST_STRESS",
            _positive(stress["mean_net_pnl_usd_per_ounce"]) and _above_one(stress["profit_factor"]),
            {
                "multiplier": report["cost_stress"]["multiplier"],
                "mean_net_pnl_usd_per_ounce": stress["mean_net_pnl_usd_per_ounce"],
                "profit_factor": stress["profit_factor"],
            },
        ),
        _gate(
            "G11_CLUSTER_BOOTSTRAP_LOWER_BOUND",
            float(report["cluster_bootstrap_95pct_ci_mean_net_return_basis_points"][0]) > 0,
            {
                "interval_basis_points": report[
                    "cluster_bootstrap_95pct_ci_mean_net_return_basis_points"
                ]
            },
        ),
        _gate(
            "G12_MULTIPLICITY_AWARE_Q_VALUE",
            float(report["benjamini_hochberg_q_value"]) <= maximum_q_value,
            {
                "benjamini_hochberg_q_value": report["benjamini_hochberg_q_value"],
                "maximum": maximum_q_value,
                "candidate_family_size": 1,
            },
        ),
    ]
    failed = [str(item["gate_id"]) for item in gates if not bool(item["passed"])]
    return {
        "passed": not failed,
        "failed_gate_ids": failed,
        "passed_gate_count": len(gates) - len(failed),
        "total_gate_count": len(gates),
        "gates": gates,
        "verdict": PASS_VERDICT if not failed else REJECT_VERDICT,
    }


def _selected(
    cases: list[WalkForwardCase],
    *,
    cost_multiplier: float = 1.0,
) -> list[ReturnObservation]:
    return [
        observation
        for item in cases
        if (
            observation := selected_observation(
                item,
                cost_multiplier=cost_multiplier,
            )
        )
        is not None
    ]


def _iso_week_key(value: date) -> str:
    iso = value.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


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
    return value is not None and math.isfinite(float(value)) and float(value) > 0


def _above_one(value: Any) -> bool:
    return value is not None and math.isfinite(float(value)) and float(value) > 1


def _rounded(value: float) -> float:
    return round(float(value), 8)


def _sortable_metric(value: Any) -> float:
    return float(value) if value is not None else float("-inf")
