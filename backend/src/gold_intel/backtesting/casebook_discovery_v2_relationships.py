from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from gold_intel.analytics.casebook import json_ready

V2_RELATIONSHIP_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_RELATIONSHIPS_V0_1"
V2_RELATIONSHIP_SCHEMA_VERSION = "gold-casebook-discovery-v2-relationships-schema-0.1.0"
ZN_4H_FEATURE_ID = "cross_zn_v_0_4_hours"


def embedded_manifest_hash(document: Mapping[str, Any]) -> str:
    content = {key: value for key, value in document.items() if key != "manifest_hash"}
    return hashlib.sha256(
        json.dumps(
            json_ready(content),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def feature_design_fingerprint(document: Mapping[str, Any]) -> str:
    content = {key: document[key] for key in ("transforms", "feature_universe", "interactions")}
    return hashlib.sha256(
        json.dumps(
            json_ready(content),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def hypothesis_classification(
    record: Mapping[str, Any],
) -> tuple[str, bool, str | None]:
    is_single_zn = record["relationship_type"] == "SINGLE" and list(record["feature_ids"]) == [
        ZN_4H_FEATURE_ID
    ]
    if not is_single_zn:
        return "INHERITED_PREDECLARED_DEVELOPMENT_SCREEN", False, None
    if record["session_code"] == "LONDON":
        return (
            "KNOWN_POSTHOC",
            True,
            "LONDON_ZN_4H_POSTHOC_V0_1 is governed separately and receives "
            "no new-discovery credit.",
        )
    if record["session_code"] == "NEW_YORK":
        return (
            "PRIOR_REJECTED_RULE_COMPONENT",
            True,
            "The New York component belonged to the rejected universal ZN "
            "rule and cannot be renamed as a fresh discovery.",
        )
    raise ValueError(f"Unexpected session: {record['session_code']}")


def apply_v2_stability_and_lead_flags(
    records: Sequence[dict[str, Any]],
    *,
    q_threshold: float,
    minimum_positive_years: int,
) -> None:
    for record in records:
        years = list(record["development_years"].values())
        adequate_years = sum(bool(item["adequate_support"]) for item in years)
        positive_years = sum(bool(item["positive_mean"]) for item in years)
        positive_halves = int(record["positive_chronological_half_count"])
        record["positive_development_year_count"] = positive_years
        record["adequately_supported_development_year_count"] = adequate_years
        record["stability_flag"] = bool(
            positive_halves == 2
            and positive_years >= minimum_positive_years
            and adequate_years >= minimum_positive_years
        )

        classification, excluded, exclusion_reason = hypothesis_classification(record)
        record["hypothesis_classification"] = classification
        record["known_hypothesis_lead_excluded"] = excluded
        record["lead_exclusion_reason"] = exclusion_reason

        selected = record["selected_metrics"]
        q_value = record["benjamini_hochberg_q_value"]
        profit_factor = selected["profit_factor"]
        lower_bound = float(record["cluster_bootstrap_95pct_ci_basis_points"][0])
        failures: list[str] = []
        if not record["support_eligible"]:
            failures.append("SUPPORT_INELIGIBLE")
        if excluded:
            failures.append("KNOWN_HYPOTHESIS_EXCLUDED")
        if float(selected["mean_net_return_basis_points"]) <= 0:
            failures.append("NON_POSITIVE_MEAN_AFTER_COST")
        if profit_factor is None or float(profit_factor) <= 1:
            failures.append("PROFIT_FACTOR_NOT_ABOVE_ONE")
        if float(record["excess_mean_net_return_vs_baseline_bps"]) <= 0:
            failures.append("DOES_NOT_BEAT_SAME_DIRECTION_CONTROL")
        if positive_halves != 2:
            failures.append("NOT_POSITIVE_IN_BOTH_HALVES")
        if positive_years < minimum_positive_years:
            failures.append("INSUFFICIENT_POSITIVE_YEARS")
        if lower_bound <= 0:
            failures.append("BOOTSTRAP_LOWER_BOUND_NOT_POSITIVE")
        if q_value is None or float(q_value) > q_threshold:
            failures.append("BH_Q_VALUE_ABOVE_THRESHOLD")
        record["lead_gate_failures"] = failures
        record["discovery_lead"] = not failures


def v2_relationship_rank_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    q_value = record["benjamini_hochberg_q_value"]
    return (
        -int(bool(record["discovery_lead"])),
        -int(bool(record["support_eligible"])),
        float(q_value) if q_value is not None else float("inf"),
        -float(record["cluster_bootstrap_95pct_ci_basis_points"][0]),
        -float(record["excess_mean_net_return_vs_baseline_bps"]),
        -float(record["selected_metrics"]["mean_net_return_basis_points"]),
        -int(record["case_count"]),
        str(record["relationship_id"]),
        str(record["state"]),
    )
