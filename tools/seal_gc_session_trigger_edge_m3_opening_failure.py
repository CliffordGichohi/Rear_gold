#!/usr/bin/env python3
"""Seal the Milestone-3 single-opening serialization failure.

This is an incident recorder only.  It never opens a market source, event
payload, feature payload, or outcome value.
"""

from __future__ import annotations

from datetime import UTC, datetime
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "research_manifests" / "gc_session_trigger_edge_m3_freeze_v01.json"
IMPLEMENTATION = ROOT / "tools" / "run_gc_session_trigger_edge_m3.py"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def valid_receipt(value: Mapping[str, Any], field: str) -> bool:
    expected = value.get(field)
    return isinstance(expected, str) and expected == canonical({**value, field: None})


def write(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def seal(output: Path) -> None:
    freeze = load(FREEZE)
    preflight_path = output / "preflight.json"
    preflight = load(preflight_path)
    if freeze.get("status") != "SEALED_BEFORE_DEVELOPMENT_OUTCOME_VALUE_ACCESS" or not valid_receipt(freeze, "freeze_receipt"):
        raise ValueError("M3 pre-outcome freeze failed")
    if sha256_file(IMPLEMENTATION) != freeze["implementation"]["sha256"]:
        raise ValueError("Frozen M3 implementation changed")
    if preflight.get("status") != "PASS_M3_PRE_OUTCOME_FREEZE_AND_READINESS" or not valid_receipt(preflight, "preflight_receipt"):
        raise ValueError("M3 preflight failed")
    allowed = {"preflight.json"}
    observed = {path.name for path in output.iterdir() if path.is_file()}
    if observed != allowed:
        raise ValueError(f"Unexpected persisted outcome or result artifact: {sorted(observed)}")

    failure = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_OUTCOME_OPENING_FAILURE_V1_0",
        "status": "FAIL_M3_SINGLE_OUTCOME_OPEN_SERIALIZATION",
        "recorded_at_utc": now(),
        "failure_stage": "WRITE_PRIMARY_JOINED_EVENT_OUTCOMES_PARQUET",
        "failure_code": "PARQUET_WRITE_TABLE_ARGUMENT_ORDER",
        "exception_type": "AttributeError",
        "exception_message": "'PosixPath' object has no attribute 'schema'",
        "frozen_call_site": "pq.write_table(temporary, table, ...)",
        "bounded_correction_not_implemented": "Use pq.write_table(table, temporary, ...) only after a separately authorized amendment.",
        "development_outcome_source_open_count": 1,
        "development_outcome_values_accessed_in_process_memory": True,
        "joined_outcome_artifact_persisted": False,
        "persisted_files_at_failure": ["preflight.json"],
        "relationship_or_hit_rate_calculation_started": False,
        "stage1_or_stage2_started": False,
        "candidates_created": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "automatic_retry_performed": False,
        "failure_receipt": None,
    }
    failure["failure_receipt"] = canonical({**failure, "failure_receipt": None})
    failure_path = output / "outcome_opening_failure.json"
    write(failure_path, failure)

    verdict = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_FAILURE_VERDICT_V1_0",
        "status": failure["status"],
        "formal_milestone_pass": False,
        "recorded_at_utc": now(),
        "reason": "The sealed source was opened once, but a serialization-only implementation defect prevented persistence of the independently calculated join. The source cannot be reopened under the current authorization.",
        "edge_verdict": "NOT_EVALUATED",
        "development_outcome_source_open_count": 1,
        "relationship_tests_completed": 0,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = canonical({**verdict, "verdict_receipt": None})
    verdict_path = output / "verdict.json"
    write(verdict_path, verdict)

    manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_FAILURE_MANIFEST_V1_0",
        "status": failure["status"],
        "sealed_at_utc": now(),
        "predecessors": {"m3_freeze_receipt": freeze["freeze_receipt"], "preflight_receipt": preflight["preflight_receipt"]},
        "artifacts": {
            "preflight.json": {"sha256": sha256_file(preflight_path), "bytes": preflight_path.stat().st_size},
            "outcome_opening_failure.json": {"sha256": sha256_file(failure_path), "bytes": failure_path.stat().st_size},
            "verdict.json": {"sha256": sha256_file(verdict_path), "bytes": verdict_path.stat().st_size},
        },
        "development_outcome_source_open_count": 1,
        "outcome_join_persisted": False,
        "relationship_tests_completed": 0,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = canonical({**manifest, "manifest_receipt": None})
    manifest_path = output / "manifest.json"
    write(manifest_path, manifest)
    final = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_FAILURE_FINAL_SEAL_V1_0",
        "status": failure["status"],
        "sealed_at_utc": now(),
        "failure_sha256": sha256_file(failure_path),
        "failure_receipt": failure["failure_receipt"],
        "verdict_sha256": sha256_file(verdict_path),
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = canonical({**final, "final_seal_receipt": None})
    write(output / "final_seal.json", final)
    print(json.dumps({"status": final["status"], "final_seal_receipt": final["final_seal_receipt"], "outcome_source_open_count": 1, "relationship_tests_completed": 0}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seal(args.output)


if __name__ == "__main__":
    main()
