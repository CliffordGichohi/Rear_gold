from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_gold_point_in_time_auction_state_v1_development as core  # noqa: E402
import run_gold_point_in_time_auction_state_v1_gc_incremental as attempt  # noqa: E402
import run_gold_point_in_time_auction_state_v1_gc_incremental_r1 as r1  # noqa: E402
import run_gold_point_in_time_auction_state_v1_gc_incremental_r2 as r2  # noqa: E402


INTERRUPTION = r2.OUTPUT / "attempt_3_interruption.json"
OUTPUT = core.ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_r3"
AMENDMENT = core.MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_amendment_c.json"
FINAL = core.MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_r3_final_freeze.json"
PRIMARY = OUTPUT / "primary_complete_evaluation.json"
REFERENCE = OUTPUT / "reference_complete_evaluation.json"

EXPECTED = {
    "interruption": "5919f9b1a6616b870ab831cc4fc2da1dbb887e215ec792ba532eb30db6722b0b",
    "amendment_b": "e40c6dfab952e04aad6308b36f1be06db59e6f59aa09a88fb2a61bde167cf24d",
    "primary_features": "eae9e88b893b319f3446691c455f02a280696b499aee6f2cb8e99834a99417cb",
    "reference_features": "eae9e88b893b319f3446691c455f02a280696b499aee6f2cb8e99834a99417cb",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def verify_common() -> dict[str, Any]:
    checks = {
        INTERRUPTION: EXPECTED["interruption"], r2.AMENDMENT: EXPECTED["amendment_b"],
        r1.PRIMARY_FEATURES: EXPECTED["primary_features"], r1.REFERENCE_FEATURES: EXPECTED["reference_features"],
    }
    for path, expected in checks.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"R3 predecessor seal failed: {path}")
    interruption = json.loads(INTERRUPTION.read_text(encoding="utf-8"))
    if interruption.get("status") != "INTERRUPTED_AFTER_PRIMARY_CHECKPOINT_BEFORE_REFERENCE_COMPLETION" or interruption.get("research_gate_failure"):
        raise ValueError("Unexpected R2 interruption disposition")
    base = json.loads(attempt.BASE_RESULT.read_text(encoding="utf-8"))
    if base.get("development_verdict") != "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE" or base.get("passing_candidates"):
        raise ValueError("Base development disposition changed")
    return base


def amendment_payload(base: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": "GOLD_PIT_AUCTION_STATE_V1_GC_INCREMENTAL_AMENDMENT_C_1_0",
        "status": "FROZEN_EXECUTION_CHECKPOINTING_ONLY_CORRECTION",
        "sealed_at_utc": core.utc_now(),
        "preserved": {
            "attempt_1_failure": file_record(attempt.OUTPUT / "attempt_1_failure.json"),
            "attempt_2_failure": file_record(r1.R1_FAILURE if hasattr(r1, "R1_FAILURE") else r1.OUTPUT / "attempt_2_failure.json"),
            "attempt_3_interruption": file_record(INTERRUPTION), "amendment_a": file_record(r1.AMENDMENT),
            "amendment_b": file_record(r2.AMENDMENT), "primary_gc_features": file_record(r1.PRIMARY_FEATURES),
            "reference_gc_features": file_record(r1.REFERENCE_FEATURES), "base_development_verdict": base["development_verdict"],
        },
        "single_correction": {
            "old": "PRIMARY_AND_REFERENCE_PASSES_EXECUTED_IN_ONE_LONG_HOST_COMMAND;INTERMEDIATE PRIMARY SERIALIZATION OMITTED TRADE ROWS",
            "new": "EXECUTE PRIMARY_AND_REFERENCE_IN_SEPARATE BOUNDED COMMANDS;PERSIST COMPLETE EVALUATION INCLUDING TRADE ROWS AFTER EACH;FINALIZE IN_A_THIRD_COMMAND",
            "scope": "EXECUTION_CHECKPOINTING_AND_SERIALIZATION_COMPLETENESS_ONLY",
        },
        "unchanged": [
            "FEATURES", "OUTCOMES", "TRANSFORMERS", "BASE_COEFFICIENTS", "MODELS", "FOLDS", "SEEDS",
            "SUPPORT", "POLICIES", "MULTIPLICITY", "ECONOMIC_GATES", "EXECUTION", "COSTS", "RISK",
            "REPRODUCTION_EQUALITY_RULE", "NO_STANDALONE_CREDIT",
        ],
        "implementation": file_record(Path(__file__).resolve()),
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }


def serialize_complete(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in evaluation.items() if key != "trades"}
    payload["trades_by_candidate"] = {
        f"{candidate}|||{comparator}": rows
        for (candidate, comparator), rows in sorted(evaluation["trades"].items())
    }
    return payload


def deserialize_complete(payload: Mapping[str, Any]) -> dict[str, Any]:
    evaluation = {key: value for key, value in payload.items() if key != "trades_by_candidate"}
    evaluation["trades"] = {}
    for key, rows in payload["trades_by_candidate"].items():
        candidate, comparator = key.split("|||", 1)
        evaluation["trades"][(candidate, comparator)] = rows
    return evaluation


def run_pass(which: str) -> None:
    base = verify_common()
    if not OUTPUT.exists():
        OUTPUT.mkdir(parents=True, exist_ok=False)
        write_json_exclusive(AMENDMENT, amendment_payload(base))
    elif not AMENDMENT.is_file():
        raise ValueError("R3 output exists without sealed Amendment C")
    target = PRIMARY if which == "primary" else REFERENCE
    if target.exists():
        raise FileExistsError(target)
    attempt.verify_base_bundle_reconstruction = r1.corrected_verify_base_bundle
    protocol = json.loads(core.PROTOCOL.read_text(encoding="utf-8"))
    source = r1.PRIMARY_FEATURES if which == "primary" else r1.REFERENCE_FEATURES
    evaluation = attempt.run_evaluation("R3_NEUTRAL_REPRODUCTION", source, protocol)
    write_json_exclusive(target, serialize_complete(evaluation))
    print(canonical_json({"status": "PASS_CHECKPOINT_COMPLETE", "pass": which, "artifact": file_record(target)}), flush=True)


def finalize() -> None:
    base = verify_common()
    if not AMENDMENT.is_file() or not PRIMARY.is_file() or not REFERENCE.is_file():
        raise FileNotFoundError("R3 complete primary/reference checkpoints are required")
    primary_payload = json.loads(PRIMARY.read_text(encoding="utf-8")); reference_payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    reproduction = canonical_hash(primary_payload) == canonical_hash(reference_payload)
    if not reproduction:
        raise ValueError("R3 complete primary/reference checkpoints differ")
    primary = deserialize_complete(primary_payload)
    protocol = json.loads(core.PROTOCOL.read_text(encoding="utf-8"))
    comparisons = attempt.comparison_results(primary, protocol)
    passing = [row["candidate_id"] for row in comparisons if row["verdict"] == "ADDS_INCREMENTAL_VALUE"]
    verdict = "ADDS_PROVEN_INCREMENTAL_GC_VALUE_NO_STANDALONE_CREDIT" if passing else "NO_PROVEN_INCREMENTAL_GC_VALUE"
    result = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_GC_INCREMENTAL_R3_FINAL_1_0",
        "status": "PASS_R3_INDEPENDENT_GC_INCREMENTAL_REPRODUCTION", "verdict": verdict,
        "completed_at_utc": core.utc_now(), "passing_incremental_comparisons": passing,
        "comparisons": comparisons, "coverage": primary["coverage"], "support_failures": primary["support_failures"],
        "attempt_1_failure_preserved": file_record(attempt.OUTPUT / "attempt_1_failure.json"),
        "attempt_2_failure_preserved": file_record(r1.OUTPUT / "attempt_2_failure.json"),
        "attempt_3_interruption_preserved": file_record(INTERRUPTION), "amendment_c": file_record(AMENDMENT),
        "complete_checkpoint_reproduction": reproduction, "base_development_verdict_preserved": base["development_verdict"],
        "standalone_candidate_credit": False, "forward_disposition": "KEEP_2025_2026_LOCKED",
        "prospective_ledger_initialized": False, "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    report = ROOT / "GOLD_POINT_IN_TIME_AUCTION_STATE_AND_ADAPTIVE_MANAGEMENT_V1_GC_INCREMENTAL_R3_RESULTS.md"
    report.write_text(attempt.report_markdown(result), encoding="utf-8", newline="\n")
    result["artifacts"] = {
        "amendment_c": file_record(AMENDMENT), "primary_complete": file_record(PRIMARY),
        "reference_complete": file_record(REFERENCE), "report": file_record(report),
    }
    result_path = OUTPUT / "gc_incremental_r3_results.json"
    write_json_exclusive(result_path, result); result["artifacts"]["result"] = file_record(result_path)
    write_json_exclusive(FINAL, result)
    print(canonical_json({"status": "COMPLETE", "verdict": verdict, "passing_incremental_comparisons": passing, "reproduction": reproduction}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("primary", "reference", "finalize"))
    args = parser.parse_args()
    if args.mode == "finalize":
        finalize()
    else:
        run_pass(args.mode)


if __name__ == "__main__":
    main()
