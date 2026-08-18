#!/usr/bin/env python3
"""Resume MAOASCR V1 from sealed joins under engineering Amendment B."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from tools import maoascr_v1_engine as core
    from tools import maoascr_v1_engine_b as corrected
    from tools import run_multi_asset_observable_auction_state_conditional_routing_v1 as original
except ModuleNotFoundError:
    import maoascr_v1_engine as core
    import maoascr_v1_engine_b as corrected
    import run_multi_asset_observable_auction_state_conditional_routing_v1 as original


ROOT = original.ROOT
AMENDMENT_A = original.MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_materialization_amendment_a.json"
AMENDMENT_B = original.MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_engineering_amendment_b.json"
RECERTIFICATION_A1 = original.ARTIFACTS / "materialization_recertification_a1.json"
STAGE1_FAILURE = original.ARTIFACTS / "stage1_attempt1_engineering_failure.json"


def verify_resume() -> None:
    original.verify_freeze()
    amendment = original.load(AMENDMENT_B)
    if amendment.get("status") != "SEALED_POST_OPENING_DETERMINISTIC_ENGINEERING_AMENDMENT_B":
        raise ValueError("Invalid Amendment B")
    for item in amendment.get("bindings", {}).values():
        original.verify_record(item)
    opening = original.load(original.OUTCOME_OPENING)
    if opening.get("opening_count") != 1:
        raise ValueError("Development outcome opening count changed")
    if any(path.exists() for path in (original.STAGE1_PRIMARY, original.STAGE1_REFERENCE, original.STAGE1_SEAL, original.STAGE2_PRIMARY, original.ROUTER_PRIMARY, original.FINAL_RESULT)):
        raise ValueError("Unexpected post-failure result artifact exists")
    if original.sha256_file(original.PRIMARY_JOIN) != original.sha256_file(original.REFERENCE_JOIN):
        raise ValueError("Sealed joins differ")


def main() -> int:
    verify_resume()
    primary_join = original.load(original.PRIMARY_JOIN)["rows"]
    reference_join = original.load(original.REFERENCE_JOIN)["rows"]

    primary_stage1 = corrected.stage1_tests(primary_join)
    reference_stage1 = corrected.stage1_tests(reference_join)
    original.write_json_exclusive(original.STAGE1_PRIMARY, {"tests": primary_stage1})
    original.write_json_exclusive(original.STAGE1_REFERENCE, {"tests": reference_stage1})
    stage1_reproduced = original.sha256_file(original.STAGE1_PRIMARY) == original.sha256_file(original.STAGE1_REFERENCE)
    stage1_records = [original.record(original.STAGE1_PRIMARY), original.record(original.STAGE1_REFERENCE)]
    original.write_json_exclusive(original.STAGE1_SEAL, {
        "version": "MAOASCR_V1_STAGE1_SEAL_1_0", "status": "SEALED_BEFORE_STAGE2",
        "sealed_at_utc": original.utc_now(), "reproduced": stage1_reproduced,
        "preserved_attempt1_failure": "FAIL_STAGE1_CONSTANT_PREDICTOR_UNHANDLED",
        "engineering_amendment_b_sha256": original.sha256_file(AMENDMENT_B),
        "test_count": len(primary_stage1), "pass_count": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage1),
        "artifacts": stage1_records, "artifact_set_hash": core.canonical_hash(stage1_records),
    })
    if not stage1_reproduced:
        raise RuntimeError("Stage 1 did not reproduce")

    primary_stage2 = corrected.stage2_tests(primary_join)
    reference_stage2 = corrected.stage2_tests(reference_join)
    original.write_json_exclusive(original.STAGE2_PRIMARY, {"tests": primary_stage2})
    original.write_json_exclusive(original.STAGE2_REFERENCE, {"tests": reference_stage2})
    if original.sha256_file(original.STAGE2_PRIMARY) != original.sha256_file(original.STAGE2_REFERENCE):
        raise RuntimeError("Stage 2 did not reproduce")

    primary_predictions, primary_models = core.oof_router(primary_join)
    reference_predictions, reference_models = core.oof_router(reference_join)
    primary_router = core.router_metrics(primary_predictions)
    reference_router = core.router_metrics(reference_predictions)
    original.write_json_exclusive(original.ROUTER_PRIMARY, {"models": primary_models, "predictions": primary_predictions, **primary_router})
    original.write_json_exclusive(original.ROUTER_REFERENCE, {"models": reference_models, "predictions": reference_predictions, **reference_router})
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
        "checkpoint_rows": 23_836,
        "stage1": {"tests": len(primary_stage1), "passes": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage1), "support_failures": sum(row["verdict"] == "SUPPORT_FAIL" for row in primary_stage1)},
        "stage2": {"tests": len(primary_stage2), "passes": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage2), "support_failures": sum(row["verdict"] == "SUPPORT_FAIL" for row in primary_stage2)},
        "router": metrics, "candidate_count": 1 if development_pass else 0,
        "forward_disposition": forward_disposition, "independent_reproduction": True, "outcome_opening_count": 1,
        "controls": {"2025_values_accessed": False, "2026_values_accessed": False, "charge_usd": 0.0, "XAUUSD_accessed": False},
        "preserved_predecessor_verdict": "FAIL_M3_CURRENT_UNIVERSE_BELOW_10R_CAPACITY",
        "preserved_materialization_failure": "FAIL_FEATURE_REPRODUCTION",
        "preserved_stage1_attempt1_failure": "FAIL_STAGE1_CONSTANT_PREDICTOR_UNHANDLED",
        "amendments": ["MATERIALIZATION_AMENDMENT_A", "ENGINEERING_AMENDMENT_B"],
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
        [original.FREEZE, AMENDMENT_A, AMENDMENT_B, original.MATERIALIZATION, RECERTIFICATION_A1, STAGE1_FAILURE, original.PRIMARY_FEATURES, original.REFERENCE_FEATURES, original.OUTCOME_OPENING, original.PRIMARY_JOIN, original.REFERENCE_JOIN, original.STAGE1_SEAL, original.STAGE1_PRIMARY, original.STAGE1_REFERENCE, original.STAGE2_PRIMARY, original.STAGE2_REFERENCE, original.ROUTER_PRIMARY, original.ROUTER_REFERENCE, original.FINAL_RESULT, original.STATE, original.REPORT, Path(__file__).resolve(), ROOT / "tools/maoascr_v1_engine.py", ROOT / "tools/maoascr_v1_engine_b.py", ROOT / "tools/run_multi_asset_observable_auction_state_conditional_routing_v1.py", ROOT / "tools/run_multi_asset_observable_auction_state_conditional_routing_v1_a1.py"],
        {"independent_reproduction": True, "2025_values_accessed": False, "2026_values_accessed": False, "candidate_count": final["candidate_count"], "materialization_amendment_a": True, "engineering_amendment_b": True},
    )
    print(json.dumps({
        "verdict": verdict, "checkpoint_rows": final["checkpoint_rows"], "stage1": final["stage1"], "stage2": final["stage2"],
        "router": {key: metrics.get(key) for key in ("accepted_trades", "trades_per_month", "win_rate", "net_expectancy_r", "profit_factor", "net_r_per_month", "dollars_per_month", "maximum_drawdown_r", "stress_expectancy_r", "failed_gates")},
        "forward_disposition": forward_disposition, "final_seal_sha256": original.sha256_file(original.FINAL_SEAL),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

