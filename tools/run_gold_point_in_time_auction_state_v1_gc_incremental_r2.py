from __future__ import annotations

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


R1_FAILURE = r1.OUTPUT / "attempt_2_failure.json"
OUTPUT = core.ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_r2"
AMENDMENT = core.MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_amendment_b.json"
FINAL = core.MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_r2_final_freeze.json"

EXPECTED = {
    "attempt_2_failure": "1ba2e11f0fe653d563a17be959f6f2f7e0b01853998a076b3acf342a2684d56e",
    "amendment_a": "2c5dc157c35bb9c49c1a684117b5d3478bd30b01a3364293674c8c7e62e95d2a",
    "r1_implementation": "007acc84cfa617e580075435252243a0d49d58bbe0f3b5d540240578d158ddef",
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


def preflight() -> dict[str, Any]:
    checks = {
        R1_FAILURE: EXPECTED["attempt_2_failure"],
        r1.AMENDMENT: EXPECTED["amendment_a"],
        Path(r1.__file__).resolve(): EXPECTED["r1_implementation"],
        r1.PRIMARY_FEATURES: EXPECTED["primary_features"],
        r1.REFERENCE_FEATURES: EXPECTED["reference_features"],
    }
    for path, expected in checks.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"R2 predecessor seal failed: {path}")
    failure = json.loads(R1_FAILURE.read_text(encoding="utf-8"))
    if failure.get("status") != "FAIL_REPRODUCTION_LABEL_SERIALIZATION":
        raise ValueError("Unexpected R1 failure")
    base = json.loads(attempt.BASE_RESULT.read_text(encoding="utf-8"))
    if base.get("development_verdict") != "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE" or base.get("passing_candidates"):
        raise ValueError("Base development disposition changed")
    if any(path.exists() for path in (OUTPUT, AMENDMENT, FINAL)):
        raise FileExistsError("R2 output or freeze already exists")
    return base


def amendment_payload(base: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": "GOLD_PIT_AUCTION_STATE_V1_GC_INCREMENTAL_AMENDMENT_B_1_0",
        "status": "FROZEN_REPRODUCTION_LABEL_ONLY_CORRECTION_BEFORE_R2_EVALUATION",
        "sealed_at_utc": core.utc_now(),
        "preserved": {
            "attempt_1_failure": file_record(attempt.OUTPUT / "attempt_1_failure.json"),
            "attempt_2_failure": file_record(R1_FAILURE),
            "amendment_a": file_record(r1.AMENDMENT),
            "primary_gc_features": file_record(r1.PRIMARY_FEATURES),
            "reference_gc_features": file_record(r1.REFERENCE_FEATURES),
            "gc_feature_payloads_byte_identical": True,
            "base_development_verdict": base["development_verdict"],
        },
        "single_correction": {
            "old": "DISTINCT PRIMARY_R1/REFERENCE_R1 LABELS WERE SERIALIZED_AND_INCLUDED_IN_DIAGNOSTIC_BOOTSTRAP_SEEDS",
            "new": "USE THE SAME NEUTRAL REPRODUCTION LABEL_AND_IDENTICAL_BOOTSTRAP_SEED_FOR_BOTH PASSES;EXCLUDE THE NONANALYTICAL IMPLEMENTATION LABEL FROM THE EQUALITY PAYLOAD",
            "scope": "REPRODUCTION LABEL AND DIAGNOSTIC SEED ONLY",
        },
        "unchanged": [
            "EVERY FEATURE VALUE_AND_AVAILABILITY", "EXACT_TRANSFORMER_CORRECTION", "BASE_COEFFICIENTS",
            "FOLDS", "OUTCOMES", "MODELS", "POLICIES", "SUPPORT", "MULTIPLICITY", "ECONOMIC_GATES",
            "EXECUTION", "COSTS", "RISK", "NO_STANDALONE_CREDIT",
        ],
        "implementation": file_record(Path(__file__).resolve()),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }


def strip_reproduction_payload(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in evaluation.items() if key not in {"trades", "implementation"}}


def main() -> None:
    base = preflight()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(AMENDMENT, amendment_payload(base))
    attempt.verify_base_bundle_reconstruction = r1.corrected_verify_base_bundle
    protocol = json.loads(core.PROTOCOL.read_text(encoding="utf-8"))
    neutral_label = "R2_NEUTRAL_REPRODUCTION"

    primary = attempt.run_evaluation(neutral_label, r1.PRIMARY_FEATURES, protocol)
    primary_serial = strip_reproduction_payload(primary)
    primary_path = OUTPUT / "primary_evaluation.json"
    write_json_exclusive(primary_path, primary_serial)

    reference = attempt.run_evaluation(neutral_label, r1.REFERENCE_FEATURES, protocol)
    reference_serial = strip_reproduction_payload(reference)
    reference_path = OUTPUT / "reference_evaluation.json"
    write_json_exclusive(reference_path, reference_serial)

    reproduction = canonical_hash(primary_serial) == canonical_hash(reference_serial)
    if not reproduction:
        raise ValueError("R2 corrected primary/reference evaluation differs")
    comparisons = attempt.comparison_results(primary, protocol)
    passing = [row["candidate_id"] for row in comparisons if row["verdict"] == "ADDS_INCREMENTAL_VALUE"]
    verdict = "ADDS_PROVEN_INCREMENTAL_GC_VALUE_NO_STANDALONE_CREDIT" if passing else "NO_PROVEN_INCREMENTAL_GC_VALUE"
    result = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_GC_INCREMENTAL_R2_FINAL_1_0",
        "status": "PASS_R2_INDEPENDENT_GC_INCREMENTAL_REPRODUCTION",
        "verdict": verdict, "completed_at_utc": core.utc_now(), "passing_incremental_comparisons": passing,
        "comparisons": comparisons, "coverage": primary["coverage"], "support_failures": primary["support_failures"],
        "attempt_1_failure_preserved": file_record(attempt.OUTPUT / "attempt_1_failure.json"),
        "attempt_2_failure_preserved": file_record(R1_FAILURE), "amendment_a_preserved": file_record(r1.AMENDMENT),
        "amendment_b": file_record(AMENDMENT), "gc_feature_payloads_reused_unchanged": True,
        "evaluation_reproduction": reproduction, "base_development_verdict_preserved": base["development_verdict"],
        "standalone_candidate_credit": False, "forward_disposition": "KEEP_2025_2026_LOCKED",
        "prospective_ledger_initialized": False, "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    report = ROOT / "GOLD_POINT_IN_TIME_AUCTION_STATE_AND_ADAPTIVE_MANAGEMENT_V1_GC_INCREMENTAL_R2_RESULTS.md"
    report.write_text(attempt.report_markdown(result), encoding="utf-8", newline="\n")
    result["artifacts"] = {
        "amendment_b": file_record(AMENDMENT), "primary_evaluation": file_record(primary_path),
        "reference_evaluation": file_record(reference_path), "primary_gc_features": file_record(r1.PRIMARY_FEATURES),
        "reference_gc_features": file_record(r1.REFERENCE_FEATURES), "report": file_record(report),
    }
    result_path = OUTPUT / "gc_incremental_r2_results.json"
    write_json_exclusive(result_path, result); result["artifacts"]["result"] = file_record(result_path)
    write_json_exclusive(FINAL, result)
    print(canonical_json({"status": "COMPLETE", "verdict": verdict, "passing_incremental_comparisons": passing, "evaluation_reproduction": reproduction}), flush=True)


if __name__ == "__main__":
    main()
