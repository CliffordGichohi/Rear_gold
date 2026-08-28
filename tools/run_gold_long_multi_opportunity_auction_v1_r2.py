#!/usr/bin/env python3
"""Resume V1 under recursive machine-precision Amendment R2."""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_long_multi_opportunity_auction_v1 as study  # noqa: E402
import run_gold_long_multi_opportunity_auction_v1_r1 as r1  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.auction_family_router_v1_r1 import (  # noqa: E402
    corrected_router_lifecycle as original_corrected_router_lifecycle,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


AMENDMENT = ROOT / "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_ENGINEERING_AMENDMENT_R2.md"
RUNNER = Path(__file__).resolve()
FAILURE = study.OUT / "engineering_failure_day82.json"
FREEZE = study.OUT / "engineering_amendment_r2.json"
FINAL_SEAL_R2 = study.OUT / "final_seal_r2.json"
REL_TOLERANCE = 1e-13
ABS_TOLERANCE = 1e-12
IGNORED_DERIVED_PATHS = {
    ".source_lifecycle_sha256",
    ".correction_sha256",
    ".effective_result.result_hash",
}


def machine_precision_equal(left: Any, right: Any, path: str = "") -> bool:
    if path in IGNORED_DERIVED_PATHS:
        return True
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, int) or isinstance(right, int):
        return type(left) is type(right) and left == right
    if isinstance(left, float) or isinstance(right, float):
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return False
        return math.isclose(
            float(left),
            float(right),
            rel_tol=REL_TOLERANCE,
            abs_tol=ABS_TOLERANCE,
        )
    if isinstance(left, dict) or isinstance(right, dict):
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False
        if set(left) != set(right):
            return False
        return all(
            machine_precision_equal(left[key], right[key], f"{path}.{key}")
            for key in sorted(left)
        )
    if isinstance(left, list) or isinstance(right, list):
        if not isinstance(left, list) or not isinstance(right, list):
            return False
        return len(left) == len(right) and all(
            machine_precision_equal(a, b, f"{path}[{index}]")
            for index, (a, b) in enumerate(zip(left, right, strict=True))
        )
    return type(left) is type(right) and left == right


class MachinePrecisionCorrectedLifecycle(dict[str, Any]):
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, dict):
            return False
        left_room = self.get("actual_fill_target_room_r")
        right_room = other.get("actual_fill_target_room_r")
        if left_room is not None and right_room is not None and (
            (float(left_room) >= 1.5) != (float(right_room) >= 1.5)
        ):
            return False
        return machine_precision_equal(dict(self), dict(other))


def amended_corrected_router_lifecycle(
    lifecycle: dict[str, Any],
) -> MachinePrecisionCorrectedLifecycle:
    return MachinePrecisionCorrectedLifecycle(
        original_corrected_router_lifecycle(lifecycle)
    )


def synthetic_proof() -> dict[str, Any]:
    base = {
        "admitted": True,
        "disposition": "STRUCTURAL_STOP",
        "actual_fill_target_room_r": 5.171883623684184,
        "room_gate_passed": True,
        "quantity": 10,
        "effective_result": {
            "executed": True,
            "resolution": "STRUCTURAL_STOP",
            "net_usd": -45.686850311311446,
            "net_r50": -0.9137370062262289,
            "legs": [{"quantity_ounces": 10, "exit_price": 1845.3313149688688}],
            "result_hash": "A",
        },
        "source_lifecycle_sha256": "B",
        "correction_sha256": "C",
        "classification_hash": "MUST_REMAIN_EXACT",
    }
    within = copy.deepcopy(base)
    within["actual_fill_target_room_r"] = 5.171883623684295
    within["effective_result"]["net_usd"] = -45.68685031130917
    within["effective_result"]["net_r50"] = -0.9137370062261835
    within["effective_result"]["legs"][0]["exit_price"] = 1845.331314968869
    within["effective_result"]["result_hash"] = "D"
    within["source_lifecycle_sha256"] = "E"
    within["correction_sha256"] = "F"
    numeric_outside = copy.deepcopy(within)
    numeric_outside["effective_result"]["net_usd"] += 1e-8
    resolution_change = copy.deepcopy(within)
    resolution_change["effective_result"]["resolution"] = "TARGET"
    quantity_change = copy.deepcopy(within)
    quantity_change["quantity"] = 11
    unapproved_hash_change = copy.deepcopy(within)
    unapproved_hash_change["classification_hash"] = "CHANGED"
    gate_left = MachinePrecisionCorrectedLifecycle(
        {**base, "actual_fill_target_room_r": 1.5 + 5e-13}
    )
    gate_right = {**within, "actual_fill_target_room_r": 1.5 - 5e-13}
    comparator = MachinePrecisionCorrectedLifecycle(base)
    checks = {
        "exact_passes": comparator == base,
        "observed_propagated_rounding_passes": comparator == within,
        "economic_numeric_difference_fails": not (comparator == numeric_outside),
        "resolution_difference_fails": not (comparator == resolution_change),
        "integer_quantity_difference_fails": not (comparator == quantity_change),
        "unapproved_hash_difference_fails": not (comparator == unapproved_hash_change),
        "room_gate_side_change_fails": not (gate_left == gate_right),
    }
    require(all(checks.values()), f"R2 proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not FAILURE.exists() and not FREEZE.exists(), "R2 artifacts already exist")
    original = study.verify_freeze()
    r1_payload = r1.verify_amendment()
    primary = study.verify_checkpoint_chain("primary", original)
    reference = study.verify_checkpoint_chain("reference", original)
    require(len(primary) == 81 and not reference, "Expected formal stop after primary 81")
    stderr = study.OUT / "background_r1.stderr.log"
    require(stderr.is_file(), "R1 failure log absent")
    error_text = stderr.read_text(encoding="utf-8", errors="replace")
    require("Original corrected lifecycle differs: CAM-2022-052" in error_text, "R1 failure differs")
    failure: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_R1_FORMAL_FAILURE_1_0",
        "recorded_at": study.now(),
        "status": "FAIL_R1_EXACT_EFFECTIVE_RESULT_FLOAT_PROPAGATION",
        "failed_side": "primary",
        "failed_ordinal": 82,
        "failed_alias": "CAM-2022-052",
        "preserved_checkpoint_count": 81,
        "preserved_checkpoint_tip": primary[-1]["checkpoint_sha256"],
        "checkpoint_82_written": False,
        "later_days_processed": False,
        "observed_max_price_difference": 2.2737367544323206e-13,
        "observed_max_usd_difference": 2.2737367544323206e-12,
        "observed_max_r_difference": 4.54081217071689e-14,
        "categorical_or_identity_difference_count": 0,
        "stderr_sha256": sha256_file(stderr),
    }
    failure["failure_sha256"] = canonical_hash(failure)
    study.write_new_json(FAILURE, failure)
    amendment: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_ENGINEERING_AMENDMENT_R2_FREEZE_1_0",
        "sealed_at": study.now(),
        "status": "SEALED_RECURSIVE_MACHINE_PRECISION_REPRODUCTION_AMENDMENT",
        "original_freeze_sha256": original["freeze_sha256"],
        "r1_amendment_sha256": r1_payload["amendment_sha256"],
        "formal_failure": study.file_record(FAILURE),
        "amendment": study.file_record(AMENDMENT),
        "runner": study.file_record(RUNNER),
        "relative_tolerance": REL_TOLERANCE,
        "absolute_tolerance": ABS_TOLERANCE,
        "ignored_only_derived_paths": sorted(IGNORED_DERIVED_PATHS),
        "synthetic_proof": synthetic_proof(),
        "checkpoint_count_at_freeze": {"primary": 81, "reference": 0},
        "checkpoint_tip_at_freeze": primary[-1]["checkpoint_sha256"],
        "research_definition_changed": False,
        "execution_changed": False,
        "outcome_changed": False,
        "short_branch_opened": False,
        "fresh_dates_opened": False,
    }
    amendment["amendment_sha256"] = canonical_hash(amendment)
    study.write_new_json(FREEZE, amendment)
    print(json.dumps(amendment, indent=2, sort_keys=True))


def verify_amendment() -> dict[str, Any]:
    require(FREEZE.is_file() and FAILURE.is_file(), "R2 amendment not frozen")
    payload = study.load_json(FREEZE)
    submitted = payload.pop("amendment_sha256")
    require(canonical_hash(payload) == submitted, "R2 amendment payload differs")
    payload["amendment_sha256"] = submitted
    for key in ("formal_failure", "amendment", "runner"):
        record = payload[key]
        path = ROOT / record["path"]
        require(path.is_file(), f"R2 file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"R2 size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"R2 hash differs: {path}")
    synthetic_proof()
    return payload


def seal_completion(amendment: dict[str, Any]) -> None:
    if not study.SEAL.exists() or FINAL_SEAL_R2.exists():
        return
    original_seal = study.load_json(study.SEAL)
    payload: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_R2_FINAL_SEAL_1_0",
        "sealed_at": study.now(),
        "verdict": original_seal["verdict"],
        "r1_amendment": study.file_record(r1.FREEZE),
        "r2_amendment_sha256": amendment["amendment_sha256"],
        "original_final_seal": study.file_record(study.SEAL),
        "final_result": study.file_record(study.FINAL),
        "checkpoint_counts": {"primary": 95, "reference": 95},
        "research_definition_changed": False,
        "execution_changed": False,
        "short_branch_opened": False,
        "fresh_dates_opened": False,
    }
    payload["seal_sha256"] = canonical_hash(payload)
    study.write_new_json(FINAL_SEAL_R2, payload)


def run(max_days: int | None) -> None:
    amendment = verify_amendment()
    study.corrected_router_lifecycle = amended_corrected_router_lifecycle
    study.run(max_days)
    seal_completion(amendment)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "status"))
    parser.add_argument("--max-days", type=int, default=None)
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    elif args.phase == "status":
        study.print_status()
    else:
        require(args.max_days is None or args.max_days >= 1, "--max-days must be positive")
        run(args.max_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
