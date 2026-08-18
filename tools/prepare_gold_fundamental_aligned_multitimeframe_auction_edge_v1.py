from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_v01"

CONTRACT = ROOT / "GOLD_FUNDAMENTAL_ALIGNED_MULTITIMEFRAME_AUCTION_EDGE_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_protocol.json"
TRACEABILITY = MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_traceability.json"
TEST_REGISTRY = MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_test_registry.json"

SEALED_SOURCES = {
    "reference_book": ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf",
    "book_alignment": ROOT / "BOOK_ALIGNMENT.md",
    "casebook_manifest": ARTIFACTS / "gold_casebook_v01/manifest.json",
    "casebook_semantic_validation": ARTIFACTS / "gold_casebook_v01/semantic_validation.json",
    "case_matrix_manifest": ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01/manifest.json",
    "case_matrix_semantic_validation": ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01/semantic_validation.json",
    "state_transition_final_seal": ARTIFACTS / "gc_session_state_transition_v1_v01/final_seal.json",
    "session_trigger_v2r1_manifest": ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/manifest.json",
    "session_trigger_v2r1_verdict": ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/verdict.json",
    "gc_source_recertification_manifest": ARTIFACTS / "gc_microstructure_step_5b2_v01/step5b2_final/manifest.json",
    "gc_source_recertification_verdict": ARTIFACTS / "gc_microstructure_step_5b2_v01/step5b2_final/verdict.json",
    "macro_source_inventory_final_seal": ARTIFACTS / "gold_macro_acceptance_source_inventory_v01/final_seal.json",
    "forward_source_snapshot_manifest": ARTIFACTS / "gold_session_behaviour_v3_m6b_source_snapshot_v01/manifest.json",
    "prior_state_transition_contract": ROOT / "GC_SESSION_STATE_TRANSITION_EDGE_DISCOVERY_CONTRACT_V1.md",
    "prior_state_transition_report": ROOT / "GC_SESSION_STATE_TRANSITION_EDGE_DISCOVERY_V1_REPORT.md",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite branch artifacts: {OUTPUT}")
    controls = {
        name: file_record(path)
        for name, path in {
            "contract": CONTRACT,
            "protocol": PROTOCOL,
            "traceability": TRACEABILITY,
            "test_registry": TEST_REGISTRY,
        }.items()
    }
    sources: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name, path in SEALED_SOURCES.items():
        if not path.is_file():
            missing.append(str(path.relative_to(ROOT)).replace("\\", "/"))
            continue
        sources[name] = file_record(path)
    if missing:
        raise FileNotFoundError(f"Missing required sealed bindings: {missing}")
    expected_book_hash = json.loads(TRACEABILITY.read_text(encoding="utf-8"))["reference_book"]["sha256"]
    if sources["reference_book"]["sha256"] != expected_book_hash:
        raise ValueError("Reference-book hash changed")

    xau_files = sorted((ROOT / "data/mt5").glob("xauusd_1m_ic_markets_mt5_*.csv"))
    forward_files = [
        path for path in xau_files
        if "_2025" in path.name or "_2026" in path.name
    ]
    if not forward_files:
        raise ValueError("No existing exposed-period XAUUSD files were found")
    forward_inventory = [file_record(path) for path in forward_files]
    inventory_identity = [
        {"path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
        for item in forward_inventory
    ]

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    tests = json.loads(TEST_REGISTRY.read_text(encoding="utf-8"))
    if len(protocol["setups"]) != 3 or tests["counts"] != {"base": 6, "gc_incremental": 6, "portfolio_diagnostic": 2}:
        raise ValueError("Frozen setup/test cardinality changed")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    preflight = {
        "version": "GOLD_FAMAE_V1_PREFLIGHT_1_0",
        "status": "PASS_PREOUTCOME_DESIGN_AND_SOURCE_BINDING",
        "created_at_utc": utc_now(),
        "controls": controls,
        "sealed_sources": sources,
        "existing_forward_xauusd_file_count": len(forward_inventory),
        "existing_forward_xauusd_inventory": forward_inventory,
        "existing_forward_xauusd_inventory_hash": canonical_hash(inventory_identity),
        "gc_acquisition_permitted": False,
        "paid_acquisition_permitted": False,
        "new_branch_outcomes_accessed": False,
        "prior_results_preserved": True,
        "prior_zero_candidate_state_transition_result_reused_as_validation_credit": False,
    }
    write_json_exclusive(OUTPUT / "preflight.json", preflight)
    preflight_record = file_record(OUTPUT / "preflight.json")
    freeze = {
        "version": "GOLD_FAMAE_V1_PREOUTCOME_FREEZE_1_0",
        "status": "SEALED_BEFORE_NEW_BRANCH_OUTCOME_COMPUTATION",
        "sealed_at_utc": utc_now(),
        "controls": controls,
        "source_bindings": sources,
        "forward_xauusd_inventory_hash": preflight["existing_forward_xauusd_inventory_hash"],
        "preflight": preflight_record,
        "branch_rules_hash": canonical_hash({
            "protocol_sha256": controls["protocol"]["sha256"],
            "traceability_sha256": controls["traceability"]["sha256"],
            "test_registry_sha256": controls["test_registry"]["sha256"],
        }),
        "new_branch_outcomes_accessed": False,
    }
    write_json_exclusive(MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_preoutcome_freeze.json", freeze)
    state = {
        "version": "GOLD_FAMAE_V1_STATE_0_1",
        "status": "PREOUTCOME_FROZEN_READY_FOR_MATERIALIZATION",
        "updated_at_utc": utc_now(),
        "preoutcome_freeze": file_record(MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_preoutcome_freeze.json"),
        "new_branch_outcomes_accessed": False,
        "development_candidates_frozen": False,
        "exposed_2025_opened": False,
        "exposed_2026_opened": False,
        "prospective_ledger_initialized": False,
    }
    write_json_exclusive(OUTPUT / "state_v01.json", state)
    print(json.dumps({
        "status": preflight["status"],
        "forward_xauusd_files": len(forward_inventory),
        "freeze": freeze["status"],
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
