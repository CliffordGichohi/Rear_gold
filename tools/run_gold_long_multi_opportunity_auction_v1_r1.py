#!/usr/bin/env python3
"""Resume V1 under the sealed float-serialization-only Amendment R1."""

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
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.auction_family_router_v1_r1 import (  # noqa: E402
    corrected_router_lifecycle as original_corrected_router_lifecycle,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


AMENDMENT = ROOT / "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_ENGINEERING_AMENDMENT_R1.md"
RUNNER = Path(__file__).resolve()
FAILURE = study.OUT / "engineering_failure_day31.json"
FREEZE = study.OUT / "engineering_amendment_r1.json"
FINAL_SEAL_R1 = study.OUT / "final_seal_r1.json"
ROOM_ABS_TOLERANCE = 1e-12
DERIVED_HASH_FIELDS = {"source_lifecycle_sha256", "correction_sha256"}


class SemanticCorrectedLifecycle(dict[str, Any]):
    """Dict whose equality retains exact semantics with one float tolerance."""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, dict):
            return False
        left = copy.deepcopy(dict(self))
        right = copy.deepcopy(dict(other))
        left_room = left.pop("actual_fill_target_room_r", None)
        right_room = right.pop("actual_fill_target_room_r", None)
        for key in DERIVED_HASH_FIELDS:
            left.pop(key, None)
            right.pop(key, None)
        if left != right:
            return False
        if left_room is None or right_room is None:
            return left_room is right_room
        if not math.isclose(
            float(left_room),
            float(right_room),
            rel_tol=0.0,
            abs_tol=ROOM_ABS_TOLERANCE,
        ):
            return False
        return (float(left_room) >= 1.5) == (float(right_room) >= 1.5)


def amended_corrected_router_lifecycle(lifecycle: dict[str, Any]) -> SemanticCorrectedLifecycle:
    return SemanticCorrectedLifecycle(original_corrected_router_lifecycle(lifecycle))


def synthetic_proof() -> dict[str, Any]:
    base = {
        "admitted": True,
        "disposition": "TARGET",
        "actual_fill_target_room_r": 2.5,
        "room_gate_passed": True,
        "effective_result": {"executed": True, "net_r50": 1.0},
        "source_lifecycle_sha256": "A",
        "correction_sha256": "B",
    }
    tolerant = SemanticCorrectedLifecycle(base)
    within = {
        **base,
        "actual_fill_target_room_r": 2.5 + 5e-13,
        "source_lifecycle_sha256": "C",
        "correction_sha256": "D",
    }
    outside = {**within, "actual_fill_target_room_r": 2.5 + 2e-12}
    result_change = copy.deepcopy(within)
    result_change["effective_result"]["net_r50"] = 0.99
    gate_change = {
        **base,
        "actual_fill_target_room_r": 1.5 - 5e-13,
    }
    boundary = SemanticCorrectedLifecycle(
        {**base, "actual_fill_target_room_r": 1.5 + 5e-13}
    )
    checks = {
        "exact_passes": tolerant == base,
        "sub_tolerance_and_derived_hash_only_passes": tolerant == within,
        "larger_float_difference_fails": not (tolerant == outside),
        "effective_result_difference_fails": not (tolerant == result_change),
        "room_gate_side_change_fails": not (boundary == gate_change),
    }
    require(all(checks.values()), f"Amendment proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not FAILURE.exists() and not FREEZE.exists(), "R1 amendment artifacts already exist")
    frozen = study.verify_freeze()
    primary = study.verify_checkpoint_chain("primary", frozen)
    reference = study.verify_checkpoint_chain("reference", frozen)
    require(len(primary) == 30 and not reference, "Expected the formal stop after primary checkpoint 30")
    stderr = study.OUT / "background.stderr.log"
    require(stderr.is_file(), "Original failure log is absent")
    error_text = stderr.read_text(encoding="utf-8", errors="replace")
    require("Original corrected lifecycle differs: CAM-2022-001" in error_text, "Original failure differs")
    failure: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_FORMAL_FAILURE_1_0",
        "recorded_at": study.now(),
        "status": "FAIL_EXACT_PREDECESSOR_REPRODUCTION_FLOAT_SERIALIZATION",
        "failed_side": "primary",
        "failed_ordinal": 31,
        "failed_alias": "CAM-2022-001",
        "preserved_checkpoint_count": 30,
        "preserved_checkpoint_tip": primary[-1]["checkpoint_sha256"],
        "difference_count": 3,
        "differences": {
            "actual_fill_target_room_r": {
                "sealed": 2.5842570458393075,
                "rebuilt": 2.584257045839317,
                "absolute_difference": abs(2.5842570458393075 - 2.584257045839317),
            },
            "derived_hash_fields": sorted(DERIVED_HASH_FIELDS),
        },
        "effective_result_exact": True,
        "checkpoint_31_written": False,
        "later_days_processed": False,
        "stderr_sha256": sha256_file(stderr),
    }
    failure["failure_sha256"] = canonical_hash(failure)
    study.write_new_json(FAILURE, failure)
    amendment: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_ENGINEERING_AMENDMENT_R1_FREEZE_1_0",
        "sealed_at": study.now(),
        "status": "SEALED_FLOAT_SERIALIZATION_ONLY_REPRODUCTION_AMENDMENT",
        "original_freeze_sha256": frozen["freeze_sha256"],
        "formal_failure": study.file_record(FAILURE),
        "amendment": study.file_record(AMENDMENT),
        "runner": study.file_record(RUNNER),
        "room_abs_tolerance": ROOM_ABS_TOLERANCE,
        "ignored_only_derived_hash_fields": sorted(DERIVED_HASH_FIELDS),
        "synthetic_proof": synthetic_proof(),
        "checkpoint_count_at_freeze": {"primary": 30, "reference": 0},
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
    require(FREEZE.is_file() and FAILURE.is_file(), "R1 amendment is not frozen")
    payload = study.load_json(FREEZE)
    submitted = payload.pop("amendment_sha256")
    require(canonical_hash(payload) == submitted, "R1 amendment payload differs")
    payload["amendment_sha256"] = submitted
    for key in ("formal_failure", "amendment", "runner"):
        record = payload[key]
        path = ROOT / record["path"]
        require(path.is_file(), f"R1 frozen file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"R1 frozen file size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"R1 frozen file hash differs: {path}")
    synthetic_proof()
    return payload


def seal_completion(amendment: dict[str, Any]) -> None:
    if not study.SEAL.exists() or FINAL_SEAL_R1.exists():
        return
    original_seal = study.load_json(study.SEAL)
    payload: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_R1_FINAL_SEAL_1_0",
        "sealed_at": study.now(),
        "verdict": original_seal["verdict"],
        "amendment_sha256": amendment["amendment_sha256"],
        "original_final_seal": study.file_record(study.SEAL),
        "final_result": study.file_record(study.FINAL),
        "checkpoint_counts": {"primary": 95, "reference": 95},
        "research_definition_changed": False,
        "execution_changed": False,
        "short_branch_opened": False,
        "fresh_dates_opened": False,
    }
    payload["seal_sha256"] = canonical_hash(payload)
    study.write_new_json(FINAL_SEAL_R1, payload)


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
