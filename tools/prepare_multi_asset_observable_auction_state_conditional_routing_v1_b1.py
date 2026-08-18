#!/usr/bin/env python3
"""Seal deterministic post-opening engineering Amendment B for MAOASCR V1."""

from __future__ import annotations

import json

try:
    from tools import run_multi_asset_observable_auction_state_conditional_routing_v1 as original
except ModuleNotFoundError:
    import run_multi_asset_observable_auction_state_conditional_routing_v1 as original


ROOT = original.ROOT
AMENDMENT_A = original.MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_materialization_amendment_a.json"
AMENDMENT_B = original.MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_engineering_amendment_b.json"
FAILURE = original.ARTIFACTS / "stage1_attempt1_engineering_failure.json"
ENGINE_B = ROOT / "tools/maoascr_v1_engine_b.py"
RUNNER_A = ROOT / "tools/run_multi_asset_observable_auction_state_conditional_routing_v1_a1.py"
RUNNER_B = ROOT / "tools/run_multi_asset_observable_auction_state_conditional_routing_v1_b1.py"


def main() -> int:
    original.verify_freeze()
    if not original.OUTCOME_OPENING.exists() or not original.PRIMARY_JOIN.exists() or not original.REFERENCE_JOIN.exists():
        raise ValueError("Expected one opening and two persisted joins")
    opening = original.load(original.OUTCOME_OPENING)
    if opening.get("opening_count") != 1:
        raise ValueError("Opening count must remain one")
    if original.sha256_file(original.PRIMARY_JOIN) != original.sha256_file(original.REFERENCE_JOIN):
        raise ValueError("Persisted joins do not reproduce")
    if any(path.exists() for path in (original.STAGE1_PRIMARY, original.STAGE1_REFERENCE, original.STAGE1_SEAL, original.STAGE2_PRIMARY, original.ROUTER_PRIMARY, original.FINAL_RESULT)):
        raise ValueError("Stage outputs unexpectedly exist")
    failure = {
        "version": "MAOASCR_V1_STAGE1_ATTEMPT1_FAILURE_1_0",
        "verdict": "FAIL_STAGE1_CONSTANT_PREDICTOR_UNHANDLED",
        "failed_at_utc": original.utc_now(),
        "failure_type": "DETERMINISTIC_ENGINEERING_EXCEPTION",
        "exception": "TypeError_FLOAT_NONE_AFTER_SCIPY_CONSTANT_INPUT_UNDEFINED_SPEARMAN",
        "research_result_credit": "NONE",
        "stage1_results_persisted": False,
        "stage2_started": False, "router_started": False,
        "development_outcome_opening_count": 1,
        "joined_payloads_preserved": [original.record(original.PRIMARY_JOIN), original.record(original.REFERENCE_JOIN)],
        "2025_values_accessed": False, "2026_values_accessed": False,
    }
    original.write_json_exclusive(FAILURE, failure)
    amendment = {
        "version": "MAOASCR_V1_ENGINEERING_AMENDMENT_B_1_0",
        "status": "SEALED_POST_OPENING_DETERMINISTIC_ENGINEERING_AMENDMENT_B",
        "sealed_at_utc": original.utc_now(),
        "preserved_failure": "FAIL_STAGE1_CONSTANT_PREDICTOR_UNHANDLED",
        "single_correction": "IF_REGISTERED_PREDICTOR_OR_INTERACTION_HAS_LT_2_UNIQUE_VALUES_OR_SPEARMAN_IS_UNDEFINED_RECORD_SUPPORT_FAIL_NO_VARIATION_INSTEAD_OF_CASTING_NULL",
        "unchanged": ["FEATURES", "OUTCOMES", "TEST_IDENTITIES", "SUPPORT_FLOORS", "MULTIPLICITY", "EFFECT_GATES", "ANNUAL_STABILITY", "MODELS", "ROUTER", "ECONOMIC_GATES"],
        "source_reopening_permitted": False,
        "resume_source": "IDENTICAL_SEALED_PRIMARY_AND_REFERENCE_JOIN_PAYLOADS",
        "attempt_limit": 1,
        "development_outcome_opening_count": 1,
        "2025_values_accessed": False, "2026_values_accessed": False,
        "bindings": {
            "preoutcome_freeze": original.record(original.FREEZE),
            "amendment_a": original.record(AMENDMENT_A),
            "outcome_opening": original.record(original.OUTCOME_OPENING),
            "primary_join": original.record(original.PRIMARY_JOIN),
            "reference_join": original.record(original.REFERENCE_JOIN),
            "attempt1_failure": original.record(FAILURE),
            "original_engine": original.record(ROOT / "tools/maoascr_v1_engine.py"),
            "corrected_engine": original.record(ENGINE_B),
            "attempt1_runner": original.record(RUNNER_A),
            "resume_runner": original.record(RUNNER_B),
        },
    }
    original.write_json_exclusive(AMENDMENT_B, amendment)
    print(json.dumps({
        "failure": original.record(FAILURE), "amendment": original.record(AMENDMENT_B),
        "opening_count": 1, "joins_byte_identical": True, "source_reopening": False,
        "2025_values_accessed": False, "2026_values_accessed": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

