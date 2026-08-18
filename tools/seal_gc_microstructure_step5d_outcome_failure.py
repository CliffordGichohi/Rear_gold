#!/usr/bin/env python3
"""Seal the formal Step 5D outcome-coverage failure without reopening data."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_artifacts" / "gc_microstructure_step5d_v01"
TOP_REPORT = ROOT / "GC_MICROSTRUCTURE_STEP_5D_REPORT.md"

BOUND = {
    "protocol": (
        ROOT / "research_manifests" / "gc_microstructure_step_5d_protocol_v01.json",
        "835361070b3955912938b5519ec0b7b32542d6774c895f43bde11a93fb268b64",
    ),
    "test_registry": (
        ROOT / "research_manifests" / "gc_microstructure_step_5d_test_registry_v01.json",
        "e3b7a132f03cebaff4c05cc646e00f0b1867881d0109c65b71f1076e74ab2d4a",
    ),
    "freeze": (
        ROOT / "research_manifests" / "gc_microstructure_step_5d_freeze_v01.json",
        "982464e185fabaab57b5871506fc3f75b9f577267eb3bcd52ebd83a4fbf2725d",
    ),
    "implementation_v01": (
        ROOT / "research_manifests" / "gc_microstructure_step_5d_implementation_v01.json",
        "dce2e997e6c95fa2bf2eb0759595bb3ad80dd298b7d30897f63ca65d8f2fac7a",
    ),
    "implementation_amendment_a": (
        ROOT / "research_manifests" / "gc_microstructure_step_5d_implementation_amendment_a_v01.json",
        "436300bc285914a9151c3fe74ec25a8b6c7651716a2e94c0e0c86f39537332fe",
    ),
    "implementation_v02": (
        ROOT / "research_manifests" / "gc_microstructure_step_5d_implementation_v02.json",
        "ffebe445bb2732a2e29105c148b702bf800fb211a9d47a545722597ae2fa38c3",
    ),
    "preflight_attempt_1_failure": (
        ROOT / "research_artifacts" / "gc_microstructure_step5d_preflight_attempt1_failed.json",
        "4dd7bd7c84302c52697e932bc11553ab21c6cd85ee83bcad049186d5fc2cb720",
    ),
    "preflight_pass": (
        OUTPUT / "preflight.json",
        "04a756d9369e0f8242f730ec2b4c1cf86c0b5dd0e368a4ccc3136ab93f73ee78",
    ),
    "analysis_tool_v02": (
        ROOT / "tools" / "run_gc_microstructure_step5d.py",
        "b129b18d6f62ba8338c81b05163b9ee8e4cff0fd79d8f3fd89a50b7ecef6e44a",
    ),
}

MISSING = [
    ["2021-12-13", "LONDON"],
    ["2021-12-13", "NEW_YORK"],
    ["2021-12-15", "LONDON"],
    ["2021-12-15", "NEW_YORK"],
    ["2022-07-12", "LONDON"],
    ["2022-07-12", "NEW_YORK"],
    ["2022-10-11", "LONDON"],
    ["2022-10-11", "NEW_YORK"],
    ["2023-03-15", "NEW_YORK"],
    ["2023-08-15", "LONDON"],
    ["2023-08-15", "NEW_YORK"],
    ["2023-09-11", "LONDON"],
    ["2023-09-11", "NEW_YORK"],
    ["2023-09-13", "NEW_YORK"],
    ["2024-05-13", "LONDON"],
    ["2024-05-13", "NEW_YORK"],
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite sealed artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_text(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite sealed artifact: {path}")
    path.write_text(value, encoding="utf-8", newline="\n")


def main() -> None:
    for name, (path, expected) in BOUND.items():
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Bound artifact changed: {name} {actual}")
    forbidden_partial_outputs = [
        "outcome_opening.json",
        "outcome_projection.parquet",
        "primary_joined_development.parquet",
        "reference_joined_development.parquet",
        "primary_stage1_results.json",
        "reference_stage1_results.json",
        "stage1_seal.json",
        "primary_stage2_results.json",
        "reference_stage2_results.json",
        "complete_results.json",
    ]
    present = [name for name in forbidden_partial_outputs if (OUTPUT / name).exists()]
    if present:
        raise ValueError(f"Unexpected partial analysis outputs exist: {present}")

    completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    failure: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_OUTCOME_OPENING_FAILURE_V0_1",
        "status": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
        "completed_at_utc": completed_at,
        "source_stream_open_count": 1,
        "source_metadata_rows_seen": 1659,
        "required_nonholiday_selected_outcomes": 374,
        "selected_outcomes_found_and_validated_in_memory": 358,
        "unexpected_missing_required_outcomes": 16,
        "predeclared_documented_good_friday_unknown_rows": 2,
        "missing_keys": [
            {"session_date": session_date, "session_code": session}
            for session_date, session in MISSING
        ],
        "frozen_gate": "Exactly 374 available one-to-one outcome joins plus the two predeclared Good Friday UNKNOWN rows; any other missing key is a formal integrity failure and no testing may begin.",
        "disposition": "STOP_NO_STAGE_1_OR_STAGE_2_TESTING",
        "cause": "UNRESOLVED_WITHIN_STEP_5D; diagnosing or substituting the missing outcome source requires a separately authorized metadata-only step.",
        "outcome_projection_persisted": False,
        "joined_feature_outcome_payload_persisted": False,
        "relationship_tests_executed": 0,
        "candidates_created": 0,
        "development_outcome_values_reported": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    failure["failure_receipt"] = canonical_hash(failure)
    failure_path = OUTPUT / "outcome_opening_failure.json"
    write_json(failure_path, failure)

    verdict: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_VERDICT_V0_1",
        "status": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
        "formal_step_pass": False,
        "completed_at_utc": completed_at,
        "failure_receipt": failure["failure_receipt"],
        "registered_tests": 148,
        "tests_executed": 0,
        "provisional_candidates": 0,
        "zero_candidate_scientific_verdict": False,
        "interpretation": "Step 5D did not test whether an edge exists. It failed before relationship calculation because the frozen development outcome join was incomplete.",
        "mandatory_stop": True,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    verdict["verdict_hash"] = canonical_hash(verdict)
    verdict_path = OUTPUT / "verdict.json"
    write_json(verdict_path, verdict)

    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_FAILURE_MANIFEST_V0_1",
        "status": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
        "sealed_at_utc": completed_at,
        "bound_artifacts": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": expected,
            }
            for name, (path, expected) in BOUND.items()
        },
        "artifacts": {
            "outcome_opening_failure": {
                "path": str(failure_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(failure_path),
            },
            "verdict": {
                "path": str(verdict_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(verdict_path),
            },
        },
        "failure_receipt": failure["failure_receipt"],
        "verdict_hash": verdict["verdict_hash"],
        "stage_1_started": False,
        "stage_2_started": False,
        "year_2025_or_2026_values_accessed": False,
        "candidate_repair_retune_inversion_or_filter": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    manifest_path = OUTPUT / "manifest.json"
    write_json(manifest_path, manifest)

    report = """# GC Microstructure Step 5D — Development Conditional-Edge Discovery

## Formal verdict

`FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE`

## What happened

The pre-result protocol, all 148 tests, seeds, support rules, statistical gates, stability gates, ranking order, and implementation were sealed before outcome access. The metadata-only preflight passed.

The sealed development case source was then streamed exactly once. It contained 358 of the 374 required non-holiday selected session outcomes. Sixteen required London/New York outcome keys were absent. The frozen missing-data policy permitted only the two predeclared 2022-04-15 Good Friday UNKNOWN rows, so the one-to-one outcome-join integrity gate failed.

## Research disposition

- Stage 1 tests executed: `0/24`.
- Stage 2 tests executed: `0/124`.
- Candidates created: `0`.
- This is **not** a scientific zero-candidate result and says nothing about whether the registered conditions have an edge.
- No missing date was silently dropped, backfilled, relabelled, or substituted.

## Scope boundary

Calendar 2025 and every 2026 value remained locked. No execution, trade, PnL, R multiple, or account return was calculated. No data was acquired and no charge was incurred.

Step 5D is sealed as a formal integrity failure and stops here. A separate metadata-only coverage diagnostic is required before any new research attempt.
"""
    artifact_report = OUTPUT / "GC_MICROSTRUCTURE_STEP_5D_REPORT.md"
    write_text(artifact_report, report)
    write_text(TOP_REPORT, report)

    print(
        json.dumps(
            {
                "status": verdict["status"],
                "manifest_hash": manifest["manifest_hash"],
                "verdict_hash": verdict["verdict_hash"],
                "failure_receipt": failure["failure_receipt"],
                "required_outcomes": 374,
                "found_outcomes": 358,
                "missing_outcomes": 16,
                "tests_executed": 0,
                "year_2025_or_2026_values_accessed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
