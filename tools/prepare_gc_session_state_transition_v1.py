#!/usr/bin/env python3
"""Freeze GC Session State-Transition Edge Discovery V1 before outcomes.

This program is metadata-only. It hashes sources, reads JSON manifests and
Parquet metadata, creates the complete test registry, and seals the design. It
must not deserialize a market row or an outcome value.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gc_session_state_transition_v1_design_v01"
CONTRACT = ROOT / "GC_SESSION_STATE_TRANSITION_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gc_session_state_transition_v1_protocol_v01.json"
REGISTRY = MANIFESTS / "gc_session_state_transition_v1_test_registry_v01.json"
FREEZE = MANIFESTS / "gc_session_state_transition_v1_design_freeze_v01.json"

EVENT_FAMILIES = (
    "LEVEL_SWEEP_RECLAIM",
    "LEVEL_BREAK_ACCEPT",
    "LEVEL_FAILED_ACCEPTANCE",
    "STRUCTURE_BREAK_CONTINUATION",
    "STRUCTURE_STATE_REVERSAL",
    "COMPRESSION_EXPANSION_BREAK",
    "FLOW_DEPTH_ALIGNMENT_ONSET",
    "ABSORPTION_ONSET",
    "FRAGILITY_FLOW_ONSET",
)
CONTEXTS = (
    "MACRO_CONCORDANT",
    "MACRO_REAL_USD_CONCORDANT",
    "SESSION_OPEN_STRUCTURE_CONCORDANT",
    "GC_CONFIRMING_WITHIN_5M",
)
SESSIONS = ("LONDON", "NEW_YORK")

BOUND = {
    "reference_book": (
        ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf",
        "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a",
    ),
    "case_matrix": (
        ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz",
        "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9",
    ),
    "case_matrix_manifest": (
        ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01/manifest.json",
        "dddbe125d11afef2094b7843f5521b7bbfcc95178e3fa376b60af8bdd2efc3b5",
    ),
    "xauusd_price_bars": (
        ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz",
        "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
    ),
    "gold_casebook_manifest": (
        ARTIFACTS / "gold_casebook_v01/manifest.json",
        "38e4aadc43917a5b91d04d47ab18542d7514fe257cc030f959d34080865314d6",
    ),
    "gc_primary_events": (
        ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/primary_events.parquet",
        "9557731bbc45d985d06227b3b15451f69e31f069697ab7cc5fae66293965a87b",
    ),
    "gc_reference_events": (
        ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/reference_events.parquet",
        "9557731bbc45d985d06227b3b15451f69e31f069697ab7cc5fae66293965a87b",
    ),
    "gc_v2r1_manifest": (
        ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/manifest.json",
        "f8b9805ffab9d86d4e695eef82e5e9c4fa22c3764eed1059b7638d91bd81264e",
    ),
    "binary_event_branch_final_seal": (
        ARTIFACTS / "gc_session_trigger_edge_m4_v01/final_seal.json",
        "0ec0695f558dea29dbd3ba331a6173847e1bda3553de76b22dc3bd14646363dd",
    ),
    "continuous_branch_final_seal": (
        ARTIFACTS / "gc_continuous_state_response_v3_m3_v01/final_seal.json",
        "8dd3b8d97fc14c1374361bdd5a4a0f61c783844ddf76a56096a78739c6ab8286",
    ),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_registry() -> dict[str, Any]:
    tests: list[dict[str, Any]] = []
    for session in SESSIONS:
        for family in EVENT_FAMILIES:
            tests.append(
                {
                    "test_id": f"{session}|S1|{family}",
                    "session": session,
                    "stage": 1,
                    "event_family": family,
                    "context": None,
                    "estimand": "MEAN_FIRST_PASSAGE_SCORE_VS_ZERO",
                }
            )
        for family in EVENT_FAMILIES:
            for context in CONTEXTS:
                tests.append(
                    {
                        "test_id": f"{session}|S2|{family}|{context}",
                        "session": session,
                        "stage": 2,
                        "event_family": family,
                        "context": context,
                        "estimand": "CONDITION_MINUS_KNOWN_CONTEXT_COMPLEMENT_FIRST_PASSAGE_SCORE",
                    }
                )
    payload: dict[str, Any] = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_TEST_REGISTRY_1_0",
        "status": "FROZEN_COMPLETE_REGISTRY_BEFORE_OUTCOME_ACCESS",
        "sessions": list(SESSIONS),
        "event_families": list(EVENT_FAMILIES),
        "contexts": list(CONTEXTS),
        "counts": {"stage1": 18, "stage2": 72, "total": 90, "per_session": 45},
        "tests": tests,
        "outcomes_accessed": False,
        "year_2025_or_2026_accessed": False,
    }
    payload["registry_receipt"] = canonical_hash(payload)
    return payload


def main() -> None:
    if OUTPUT.exists() or REGISTRY.exists() or FREEZE.exists():
        raise FileExistsError("Refusing to overwrite a state-transition design artifact")
    checks: dict[str, bool] = {}
    sources: dict[str, Any] = {}
    for name, (path, expected) in BOUND.items():
        actual = sha256_file(path)
        checks[f"{name}_seal"] = actual == expected
        sources[name] = file_record(path)

    protocol = load_json(PROTOCOL)
    case_manifest = load_json(BOUND["case_matrix_manifest"][0])
    gc_manifest = load_json(BOUND["gc_v2r1_manifest"][0])
    primary_meta = pq.ParquetFile(BOUND["gc_primary_events"][0])
    reference_meta = pq.ParquetFile(BOUND["gc_reference_events"][0])
    checks.update(
        {
            "protocol_frozen": protocol.get("status") == "FROZEN_BEFORE_OUTCOME_ACCESS",
            "case_population_1659": case_manifest.get("case_counts", {}).get("total") == 1659,
            "case_end_2024": case_manifest.get("development_partition", {}).get("session_date_end_inclusive") == "2024-12-31",
            "case_values_not_read": True,
            "gc_v2r1_technical_pass": gc_manifest.get("status") == "PASS_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION",
            "gc_primary_rows_4950": primary_meta.metadata.num_rows == 4950,
            "gc_reference_rows_4950": reference_meta.metadata.num_rows == 4950,
            "gc_schema_exact": primary_meta.schema_arrow == reference_meta.schema_arrow,
            "gc_values_not_read": True,
            "locked_years_2025_2026": protocol.get("development", {}).get("locked_years") == [2025, 2026],
            "no_acquisition": True,
        }
    )
    if not all(checks.values()):
        raise RuntimeError([name for name, passed in checks.items() if not passed])

    registry = build_registry()
    write_json_exclusive(REGISTRY, registry)
    registry_record = file_record(REGISTRY)
    controls = {
        "contract": file_record(CONTRACT),
        "protocol": file_record(PROTOCOL),
        "test_registry": registry_record,
        "prepare_implementation": file_record(Path(__file__).resolve()),
    }
    freeze: dict[str, Any] = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_DESIGN_FREEZE_1_0",
        "status": "SEALED_BEFORE_ANY_V1_OUTCOME_ACCESS",
        "sealed_at_utc": utc_now(),
        "controls": controls,
        "sources": sources,
        "checks": checks,
        "outcome_values_accessed": False,
        "development_relationships_calculated": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    freeze["freeze_receipt"] = canonical_hash(freeze)
    write_json_exclusive(FREEZE, freeze)

    OUTPUT.mkdir(parents=True)
    preflight: dict[str, Any] = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_DESIGN_PREFLIGHT_1_0",
        "status": "PASS_PRE_OUTCOME_DESIGN_AND_SOURCE_METADATA_READINESS",
        "completed_at_utc": utc_now(),
        "checks": checks,
        "sources": sources,
        "controls": {**controls, "design_freeze": file_record(FREEZE)},
        "registered_tests": registry["counts"],
        "market_rows_deserialized": 0,
        "outcome_values_accessed": False,
        "year_2025_or_2026_accessed": False,
    }
    preflight["preflight_receipt"] = canonical_hash(preflight)
    write_json_exclusive(OUTPUT / "preflight.json", preflight)
    print(json.dumps({"status": preflight["status"], "checks": len(checks), "tests": 90}, sort_keys=True))


if __name__ == "__main__":
    main()
