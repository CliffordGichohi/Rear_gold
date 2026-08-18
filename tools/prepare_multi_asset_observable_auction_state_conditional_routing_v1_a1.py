#!/usr/bin/env python3
"""Seal pre-outcome serialization-only Amendment A for MAOASCR V1."""

from __future__ import annotations

import json

try:
    from tools import run_multi_asset_observable_auction_state_conditional_routing_v1 as original
except ModuleNotFoundError:
    import run_multi_asset_observable_auction_state_conditional_routing_v1 as original


ROOT = original.ROOT
AMENDMENT = original.MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_materialization_amendment_a.json"
RESUME = ROOT / "tools/run_multi_asset_observable_auction_state_conditional_routing_v1_a1.py"


def main() -> int:
    original.verify_freeze()
    if original.OUTCOME_OPENING.exists():
        raise ValueError("Cannot freeze pre-outcome amendment after outcome opening")
    failure = original.load(original.MATERIALIZATION)
    if failure.get("verdict") != "FAIL_FEATURE_REPRODUCTION" or failure.get("outcomes_accessed"):
        raise ValueError("Expected preserved value-blind materialization failure")
    primary = failure["primary"]
    reference = failure["reference"]
    if (
        primary["rows"] != reference["rows"]
        or primary["row_identity_hash"] != reference["row_identity_hash"]
        or primary["semantic_hash"] != reference["semantic_hash"]
        or primary["timeframe_counts"] != reference["timeframe_counts"]
        or primary["source_diagnostics"] != reference["source_diagnostics"]
    ):
        raise ValueError("Failure is not proven wrapper-only from certification metadata")
    amendment = {
        "version": "MAOASCR_V1_MATERIALIZATION_AMENDMENT_A_1_0",
        "status": "SEALED_PRE_OUTCOME_SERIALIZATION_ONLY_AMENDMENT_A",
        "sealed_at_utc": original.utc_now(),
        "preserved_original_verdict": "FAIL_FEATURE_REPRODUCTION",
        "diagnosis": "TOP_LEVEL_IMPLEMENTATION_PROVENANCE_LABEL_PRIMARY_VS_REFERENCE_CAUSES_TWO_BYTE_FILE_DIFFERENCE",
        "changed_rule_only": "REQUIRE_EXACT_COMPLETE_ROWS_ARRAY_EQUALITY_AND_EQUAL_ROW_SEMANTIC_HASH; RETAIN_DIFFERING_PROVENANCE_WRAPPERS",
        "unchanged": ["ALL_23836_CHECKPOINT_IDENTITIES", "ALL_FEATURE_VALUES", "ALL_SOURCE_DIAGNOSTICS", "ALL_FEATURE_DEFINITIONS", "ALL_OUTCOME_RULES", "ALL_TESTS", "ALL_MODELS", "ALL_GATES"],
        "attempt_limit": 1,
        "development_outcomes_accessed": False, "2025_values_accessed": False, "2026_values_accessed": False,
        "bindings": {
            "original_freeze": original.record(original.FREEZE),
            "original_runner": original.record(ROOT / "tools/run_multi_asset_observable_auction_state_conditional_routing_v1.py"),
            "resume_runner": original.record(RESUME),
            "materialization_failure": original.record(original.MATERIALIZATION),
            "primary_feature_payload": original.record(original.PRIMARY_FEATURES),
            "reference_feature_payload": original.record(original.REFERENCE_FEATURES),
        },
    }
    original.write_json_exclusive(AMENDMENT, amendment)
    print(json.dumps({
        "amendment": original.record(AMENDMENT), "preserved_failure": failure["verdict"],
        "row_count": primary["rows"], "row_identity_hash_equal": True,
        "semantic_hash_equal": True, "development_outcomes_accessed": False,
        "2025_values_accessed": False, "2026_values_accessed": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

