#!/usr/bin/env python3
"""Resume MAOASCR V1 after pre-outcome serialization-only Amendment A."""

from __future__ import annotations

import gc
import json
from pathlib import Path

try:
    from tools import maoascr_v1_engine as research
    from tools import run_multi_asset_observable_auction_state_conditional_routing_v1 as original
except ModuleNotFoundError:
    import maoascr_v1_engine as research
    import run_multi_asset_observable_auction_state_conditional_routing_v1 as original


ROOT = original.ROOT
AMENDMENT = original.MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_materialization_amendment_a.json"
RECERTIFICATION = original.ARTIFACTS / "materialization_recertification_a1.json"


def verify_amendment() -> dict:
    original.verify_freeze()
    amendment = original.load(AMENDMENT)
    if amendment.get("status") != "SEALED_PRE_OUTCOME_SERIALIZATION_ONLY_AMENDMENT_A":
        raise ValueError("Invalid Amendment A")
    for item in amendment.get("bindings", {}).values():
        original.verify_record(item)
    if amendment.get("development_outcomes_accessed") or amendment.get("2025_values_accessed") or amendment.get("2026_values_accessed"):
        raise ValueError("Amendment A was not frozen value-blind")
    if original.OUTCOME_OPENING.exists():
        raise ValueError("Outcome opening already exists")
    return amendment


def main() -> int:
    verify_amendment()
    primary_feature_payload = original.load(original.PRIMARY_FEATURES)
    reference_feature_payload = original.load(original.REFERENCE_FEATURES)
    primary_rows = primary_feature_payload["rows"]
    reference_rows = reference_feature_payload["rows"]
    exact_rows = primary_rows == reference_rows
    primary_hash = research.canonical_hash(primary_rows)
    reference_hash = research.canonical_hash(reference_rows)
    if not exact_rows or primary_hash != reference_hash:
        raise RuntimeError("Amendment A row-payload reproduction failed")
    recertification = {
        "version": "MAOASCR_V1_MATERIALIZATION_RECERTIFICATION_A1_1_0",
        "verdict": "PASS_OUTCOME_BLIND_FEATURE_ROW_REPRODUCTION_A1",
        "preserved_original_verdict": "FAIL_FEATURE_REPRODUCTION",
        "original_file_byte_difference_preserved": True,
        "difference_classification": "TOP_LEVEL_IMPLEMENTATION_PROVENANCE_LABEL_ONLY",
        "row_count": len(primary_rows), "exact_row_payload_equality": True,
        "primary_row_hash": primary_hash, "reference_row_hash": reference_hash,
        "development_outcomes_accessed": False, "2025_values_accessed": False, "2026_values_accessed": False,
    }
    original.write_json_exclusive(RECERTIFICATION, recertification)

    opening = {
        "version": "MAOASCR_V1_DEVELOPMENT_OUTCOME_OPENING_1_0", "opened_at_utc": original.utc_now(),
        "opening_count": 1, "source": original.record(original.OUTCOME_SOURCE),
        "feature_population_hash": primary_hash,
        "materialization_amendment_a_sha256": original.sha256_file(AMENDMENT),
        "2025_values_accessed": False, "2026_values_accessed": False,
    }
    original.write_json_exclusive(original.OUTCOME_OPENING, opening)
    primary_join, primary_join_diag = original.open_and_join_outcomes(primary_rows)
    reference_join, reference_join_diag = original.open_and_join_outcomes(reference_rows)
    original.write_json_exclusive(original.PRIMARY_JOIN, {"rows": primary_join})
    original.write_json_exclusive(original.REFERENCE_JOIN, {"rows": reference_join})
    if original.sha256_file(original.PRIMARY_JOIN) != original.sha256_file(original.REFERENCE_JOIN) or primary_join_diag != reference_join_diag:
        raise RuntimeError("Outcome join did not reproduce")

    primary_stage1 = research.stage1_tests(primary_join)
    reference_stage1 = research.stage1_tests(reference_join)
    original.write_json_exclusive(original.STAGE1_PRIMARY, {"tests": primary_stage1})
    original.write_json_exclusive(original.STAGE1_REFERENCE, {"tests": reference_stage1})
    stage1_reproduced = original.sha256_file(original.STAGE1_PRIMARY) == original.sha256_file(original.STAGE1_REFERENCE)
    stage1_records = [original.record(original.STAGE1_PRIMARY), original.record(original.STAGE1_REFERENCE)]
    original.write_json_exclusive(original.STAGE1_SEAL, {
        "version": "MAOASCR_V1_STAGE1_SEAL_1_0", "status": "SEALED_BEFORE_STAGE2",
        "sealed_at_utc": original.utc_now(), "reproduced": stage1_reproduced,
        "test_count": len(primary_stage1), "pass_count": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage1),
        "artifacts": stage1_records, "artifact_set_hash": research.canonical_hash(stage1_records),
    })
    if not stage1_reproduced:
        raise RuntimeError("Stage 1 did not reproduce")

    primary_stage2 = research.stage2_tests(primary_join)
    reference_stage2 = research.stage2_tests(reference_join)
    original.write_json_exclusive(original.STAGE2_PRIMARY, {"tests": primary_stage2})
    original.write_json_exclusive(original.STAGE2_REFERENCE, {"tests": reference_stage2})
    if original.sha256_file(original.STAGE2_PRIMARY) != original.sha256_file(original.STAGE2_REFERENCE):
        raise RuntimeError("Stage 2 did not reproduce")

    primary_predictions, primary_models = research.oof_router(primary_join)
    reference_predictions, reference_models = research.oof_router(reference_join)
    primary_router = research.router_metrics(primary_predictions)
    reference_router = research.router_metrics(reference_predictions)
    primary_payload = {"models": primary_models, "predictions": primary_predictions, **primary_router}
    reference_payload = {"models": reference_models, "predictions": reference_predictions, **reference_router}
    original.write_json_exclusive(original.ROUTER_PRIMARY, primary_payload)
    original.write_json_exclusive(original.ROUTER_REFERENCE, reference_payload)
    if original.sha256_file(original.ROUTER_PRIMARY) != original.sha256_file(original.ROUTER_REFERENCE):
        raise RuntimeError("Router evaluation did not reproduce")

    metrics = primary_router["metrics"]
    development_pass = metrics["verdict"] == "PASS_PROVISIONAL_UNVALIDATED_CANDIDATE"
    if development_pass:
        forward_disposition = "BLOCKED_REQUIRED_EXISTING_2025_2026_SOURCES_NOT_CERTIFIED"
        verdict = "PASS_DEVELOPMENT_CANDIDATE_FORWARD_BLOCKED_SOURCE_UNAVAILABLE"
    else:
        forward_disposition = "NOT_OPENED_NO_DEVELOPMENT_CANDIDATE"
        verdict = "REJECT_NO_ECONOMICALLY_TRADABLE_CONDITIONAL_ROUTER"
    final = {
        "version": "MAOASCR_V1_FINAL_RESULT_1_0", "verdict": verdict, "completed_at_utc": original.utc_now(),
        "checkpoint_rows": len(primary_rows),
        "stage1": {"tests": len(primary_stage1), "passes": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage1), "support_failures": sum(row["verdict"] == "SUPPORT_FAIL" for row in primary_stage1)},
        "stage2": {"tests": len(primary_stage2), "passes": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage2), "support_failures": sum(row["verdict"] == "SUPPORT_FAIL" for row in primary_stage2)},
        "router": metrics, "candidate_count": 1 if development_pass else 0,
        "forward_disposition": forward_disposition, "independent_reproduction": True, "outcome_opening_count": 1,
        "controls": {"2025_values_accessed": False, "2026_values_accessed": False, "charge_usd": 0.0, "XAUUSD_accessed": False},
        "preserved_predecessor_verdict": "FAIL_M3_CURRENT_UNIVERSE_BELOW_10R_CAPACITY",
        "preserved_materialization_failure": "FAIL_FEATURE_REPRODUCTION",
        "materialization_recertification": "PASS_OUTCOME_BLIND_FEATURE_ROW_REPRODUCTION_A1",
    }
    original.write_json_exclusive(original.FINAL_RESULT, final)
    original.write_json_exclusive(original.STATE, {
        "version": "MAOASCR_V1_STATE_1_0", "status": "COMPLETE", "verdict": verdict,
        "forward_disposition": forward_disposition, "candidate_count": final["candidate_count"],
        "2025": "LOCKED_NOT_ACCESSED", "2026": "LOCKED_NOT_ACCESSED",
    })
    original.write_text_exclusive(original.REPORT, original.report(final))
    original.seal(
        original.FINAL_SEAL, verdict,
        [original.FREEZE, AMENDMENT, original.MATERIALIZATION, RECERTIFICATION, original.PRIMARY_FEATURES, original.REFERENCE_FEATURES, original.OUTCOME_OPENING, original.PRIMARY_JOIN, original.REFERENCE_JOIN, original.STAGE1_SEAL, original.STAGE1_PRIMARY, original.STAGE1_REFERENCE, original.STAGE2_PRIMARY, original.STAGE2_REFERENCE, original.ROUTER_PRIMARY, original.ROUTER_REFERENCE, original.FINAL_RESULT, original.STATE, original.REPORT, Path(__file__).resolve(), ROOT / "tools/maoascr_v1_engine.py", ROOT / "tools/run_multi_asset_observable_auction_state_conditional_routing_v1.py"],
        {"independent_reproduction": True, "2025_values_accessed": False, "2026_values_accessed": False, "candidate_count": final["candidate_count"], "materialization_amendment_a": True},
    )
    del primary_join, reference_join, primary_predictions, reference_predictions
    gc.collect()
    print(json.dumps({
        "verdict": verdict, "checkpoint_rows": final["checkpoint_rows"], "stage1": final["stage1"], "stage2": final["stage2"],
        "router": {key: metrics.get(key) for key in ("accepted_trades", "trades_per_month", "win_rate", "net_expectancy_r", "profit_factor", "net_r_per_month", "dollars_per_month", "maximum_drawdown_r", "stress_expectancy_r", "failed_gates")},
        "forward_disposition": forward_disposition, "final_seal_sha256": original.sha256_file(original.FINAL_SEAL),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

