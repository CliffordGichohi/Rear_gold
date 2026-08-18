from __future__ import annotations

from copy import deepcopy

import pytest

from gold_intel.backtesting.casebook_discovery_v2_shortlist import (
    metadata_readiness,
    validate_shortlist_definition,
)


def _manifest() -> dict:
    return {
        "manifest_version": ("GOLD_CASEBOOK_DISCOVERY_V2_SHORTLIST_MANIFEST_V0_1"),
        "status": "FROZEN_BEFORE_CALENDAR_2025_VALUE_ACCESS",
        "milestone": "V2_M5_SHORTLIST_FREEZE",
        "prohibited": {"holdout": True},
        "candidate_budget": {
            "london_frozen": 1,
            "london_maximum": 2,
            "new_york_frozen": 0,
            "new_york_maximum": 2,
            "total_frozen": 1,
        },
        "candidates": [
            {
                "candidate_code": "LONDON_ZN_4H_POSTHOC_V0_1",
                "session": "LONDON",
                "conditions": 1,
                "threshold": None,
                "rule_table": {
                    "FLAT": "NO_BIAS",
                    "NEGATIVE": "SHORT",
                    "POSITIVE": "LONG",
                    "UNKNOWN": "NO_BIAS",
                },
                "missing_data_policy": {"proxy_substitution": "PROHIBITED"},
            }
        ],
        "holdout_2025": {
            "candidate_family_size": 1,
            "evaluation_gates": [
                {"gate_id": gate_id}
                for gate_id in (
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
            ],
            "readiness_gates_before_value_access": [
                {"gate_id": gate_id}
                for gate_id in (
                    "R01_XAUUSD_TIMESTAMP_COVERAGE",
                    "R02_ZN_LICENSED_ARCHIVE_SEALED",
                    "R03_ZN_ROLL_LINEAGE_SEALED",
                    "R04_ZN_TIMESTAMP_ONLY_CASE_COVERAGE",
                    "R05_PREOPEN_AUDIT_CLEAN",
                )
            ],
            "evaluation_policy": {"all_gates_required": True},
            "readiness_policy": {"all_readiness_gates_required": True},
        },
    }


def test_shortlist_definition_accepts_only_frozen_london_candidate() -> None:
    validate_shortlist_definition(_manifest())
    changed = deepcopy(_manifest())
    changed["candidates"][0]["rule_table"]["NEGATIVE"] = "LONG"
    with pytest.raises(ValueError, match="rule table changed"):
        validate_shortlist_definition(changed)


def test_metadata_readiness_blocks_when_zn_is_missing() -> None:
    coverage = {
        "audit_boundary": {
            "access_class": "METADATA_ONLY",
            "sql_guard_passed": True,
            "forbidden_value_columns_referenced": [],
            "holdout_ohlc_or_market_values_read": False,
            "holdout_feature_values_calculated": False,
            "holdout_outcomes_calculated": False,
            "holdout_feature_outcome_joins_calculated": False,
        },
        "holdout_2025": {
            "xauusd_timestamp_only_session_coverage": {
                "counts": {
                    "london_case_complete": 257,
                    "requested_weekdays": 261,
                    "london_case_complete_pct": 98.4674,
                }
            },
            "cme_rates_metadata": {
                "holdout_2025": {
                    "zn_v_0_available": False,
                    "reason": "2025 not loaded",
                }
            },
        },
    }
    readiness = metadata_readiness(coverage)
    assert readiness["status"] == "BLOCKED_MISSING_ZN_2025"
    assert readiness["gates"][0]["passed"] is True
    assert readiness["gates"][1]["passed"] is False
    assert readiness["calendar_2025_values_accessed"] is False
