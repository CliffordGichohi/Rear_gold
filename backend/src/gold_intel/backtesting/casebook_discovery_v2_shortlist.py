from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SHORTLIST_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_SHORTLIST_V0_1"
SHORTLIST_SCHEMA_VERSION = "gold-casebook-discovery-v2-shortlist-schema-0.1.0"
CANDIDATE_CODE = "LONDON_ZN_4H_POSTHOC_V0_1"
EVALUATION_GATE_IDS = (
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
READINESS_GATE_IDS = (
    "R01_XAUUSD_TIMESTAMP_COVERAGE",
    "R02_ZN_LICENSED_ARCHIVE_SEALED",
    "R03_ZN_ROLL_LINEAGE_SEALED",
    "R04_ZN_TIMESTAMP_ONLY_CASE_COVERAGE",
    "R05_PREOPEN_AUDIT_CLEAN",
)


def validate_shortlist_definition(document: Mapping[str, Any]) -> None:
    if document["manifest_version"] != "GOLD_CASEBOOK_DISCOVERY_V2_SHORTLIST_MANIFEST_V0_1":
        raise ValueError("Unexpected V2 M5 manifest version")
    if document["status"] != "FROZEN_BEFORE_CALENDAR_2025_VALUE_ACCESS":
        raise ValueError("V2 M5 manifest is not frozen before holdout access")
    if document["milestone"] != "V2_M5_SHORTLIST_FREEZE":
        raise ValueError("Unexpected V2 milestone")
    if not all(bool(value) for value in document["prohibited"].values()):
        raise ValueError("One or more V2 M5 prohibitions is unlocked")
    budget = document["candidate_budget"]
    if budget != {
        "london_frozen": 1,
        "london_maximum": 2,
        "new_york_frozen": 0,
        "new_york_maximum": 2,
        "total_frozen": 1,
    }:
        raise ValueError("Frozen candidate budget changed")
    candidates = document["candidates"]
    if len(candidates) != 1:
        raise ValueError("V2 M5 must freeze exactly one candidate")
    candidate = candidates[0]
    if candidate["candidate_code"] != CANDIDATE_CODE:
        raise ValueError("Unexpected V2 M5 candidate")
    if candidate["session"] != "LONDON":
        raise ValueError("V2 M5 candidate is not London-only")
    if candidate["conditions"] != 1 or candidate["threshold"] is not None:
        raise ValueError("Frozen London candidate was retuned")
    if candidate["rule_table"] != {
        "FLAT": "NO_BIAS",
        "NEGATIVE": "SHORT",
        "POSITIVE": "LONG",
        "UNKNOWN": "NO_BIAS",
    }:
        raise ValueError("Frozen London rule table changed")
    if candidate["missing_data_policy"]["proxy_substitution"] != "PROHIBITED":
        raise ValueError("ZN proxy substitution was enabled")

    holdout = document["holdout_2025"]
    evaluation_ids = tuple(item["gate_id"] for item in holdout["evaluation_gates"])
    if evaluation_ids != EVALUATION_GATE_IDS:
        raise ValueError("Frozen holdout evaluation gate set changed")
    readiness_ids = tuple(
        item["gate_id"] for item in holdout["readiness_gates_before_value_access"]
    )
    if readiness_ids != READINESS_GATE_IDS:
        raise ValueError("Frozen preopen readiness gate set changed")
    if holdout["candidate_family_size"] != 1:
        raise ValueError("Frozen holdout candidate family changed")
    if holdout["evaluation_policy"]["all_gates_required"] is not True:
        raise ValueError("Holdout no longer requires every evaluation gate")
    if holdout["readiness_policy"]["all_readiness_gates_required"] is not True:
        raise ValueError("Holdout no longer requires every readiness gate")


def metadata_readiness(
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    audit = coverage["audit_boundary"]
    holdout = coverage["holdout_2025"]
    session_counts = holdout["xauusd_timestamp_only_session_coverage"]["counts"]
    xau_pct = float(session_counts["london_case_complete_pct"])
    zn_ready = bool(holdout["cme_rates_metadata"]["holdout_2025"]["zn_v_0_available"])
    existing_audit_clean = bool(
        audit["access_class"] == "METADATA_ONLY"
        and audit["sql_guard_passed"]
        and not audit["forbidden_value_columns_referenced"]
        and audit["holdout_ohlc_or_market_values_read"] is False
        and audit["holdout_feature_values_calculated"] is False
        and audit["holdout_outcomes_calculated"] is False
        and audit["holdout_feature_outcome_joins_calculated"] is False
    )
    gates = [
        _gate(
            "R01_XAUUSD_TIMESTAMP_COVERAGE",
            xau_pct >= 95.0,
            {
                "london_case_complete": session_counts["london_case_complete"],
                "requested_weekdays": session_counts["requested_weekdays"],
                "coverage_pct": xau_pct,
                "minimum_pct": 95.0,
            },
        ),
        _gate(
            "R02_ZN_LICENSED_ARCHIVE_SEALED",
            zn_ready,
            {
                "zn_v_0_available": zn_ready,
                "reason": holdout["cme_rates_metadata"]["holdout_2025"]["reason"],
            },
        ),
        _gate(
            "R03_ZN_ROLL_LINEAGE_SEALED",
            False,
            {
                "sealed": False,
                "reason": "Calendar-2025 ZN normalization does not exist.",
            },
        ),
        _gate(
            "R04_ZN_TIMESTAMP_ONLY_CASE_COVERAGE",
            False,
            {
                "audited": False,
                "reason": "Calendar-2025 ZN timestamps are not present.",
            },
        ),
        _gate(
            "R05_PREOPEN_AUDIT_CLEAN",
            False,
            {
                "existing_metadata_audit_clean": existing_audit_clean,
                "candidate_specific_reaudit_complete": False,
                "reason": (
                    "A new metadata-only audit is required after the missing "
                    "ZN archive is acquired and sealed."
                ),
            },
        ),
    ]
    failed = [item["gate_id"] for item in gates if not item["passed"]]
    return {
        "status": ("READY_FOR_ONE_TIME_HOLDOUT_OPEN" if not failed else "BLOCKED_MISSING_ZN_2025"),
        "all_readiness_gates_passed": not failed,
        "failed_gate_ids": failed,
        "gates": gates,
        "calendar_2025_values_accessed": False,
    }


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
