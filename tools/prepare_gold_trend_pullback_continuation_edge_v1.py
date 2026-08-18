from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"

CONTRACT = ROOT / "GOLD_TREND_PULLBACK_CONTINUATION_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_protocol.json"
FEATURE_REGISTRY = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_feature_registry.json"
TEST_REGISTRY = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_test_registry.json"
DESIGN_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_design_freeze.json"

CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
CASEBOOK = ARTIFACTS / "gold_casebook_v01"

SOURCES = {
    "census_final_seal": CENSUS / "final_seal.json",
    "census_pullbacks_primary": CENSUS / "primary_pullback_cases.parquet",
    "census_pullbacks_reference": CENSUS / "reference_pullback_cases.parquet",
    "census_events_primary": CENSUS / "primary_structure_events.parquet",
    "census_events_reference": CENSUS / "reference_structure_events.parquet",
    "census_swings_primary": CENSUS / "primary_swings.parquet",
    "census_swings_reference": CENSUS / "reference_swings.parquet",
    "price_bars": CASEBOOK / "price_bars.jsonl.gz",
    "fundamentals": CASEBOOK / "fundamentals.jsonl.gz",
    "positioning": CASEBOOK / "positioning.jsonl.gz",
    "casebook_manifest": CASEBOOK / "manifest.json",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def verify_predecessors() -> dict[str, Any]:
    seal = json.loads(SOURCES["census_final_seal"].read_text(encoding="utf-8"))
    if seal.get("status") != "PASS_COMPLETE_DESCRIPTIVE_CENSUS":
        raise ValueError("Census predecessor did not pass")
    if seal.get("forward_values_accessed") is not False:
        raise ValueError("Census forward boundary is not clean")
    if sha256_file(SOURCES["census_pullbacks_primary"]) != sha256_file(SOURCES["census_pullbacks_reference"]):
        raise ValueError("Primary/reference pullback registries differ")
    if sha256_file(SOURCES["census_events_primary"]) != sha256_file(SOURCES["census_events_reference"]):
        raise ValueError("Primary/reference event registries differ")
    if sha256_file(SOURCES["census_swings_primary"]) != sha256_file(SOURCES["census_swings_reference"]):
        raise ValueError("Primary/reference swing registries differ")
    casebook = json.loads(SOURCES["casebook_manifest"].read_text(encoding="utf-8"))
    if casebook.get("contract", {}).get("holdout_loaded") is not False:
        raise ValueError("Casebook holdout boundary is not clean")
    return {
        "census_status": seal["status"],
        "census_artifact_set_hash": seal.get("artifact_set_hash"),
        "casebook_manifest_hash": casebook.get("manifest_hash"),
        "primary_reference_census_exact": True,
    }


def main() -> None:
    if DESIGN_FREEZE.exists() or OUTPUT.exists():
        raise FileExistsError("TPCE V1 design or output already exists")
    controls = {
        "contract": record(CONTRACT),
        "protocol": record(PROTOCOL),
        "feature_registry": record(FEATURE_REGISTRY),
        "test_registry": record(TEST_REGISTRY),
    }
    predecessor = verify_predecessors()
    sources = {name: record(path) for name, path in SOURCES.items()}
    freeze = {
        "version": "GOLD_TPCE_V1_DESIGN_FREEZE_1_0",
        "status": "SEALED_BEFORE_CONDITIONAL_FEATURE_OR_OUTCOME_ACCESS",
        "sealed_at_utc": utc_now(),
        "controls": controls,
        "sources": sources,
        "predecessor_verification": predecessor,
        "control_set_hash": canonical_hash({name: item["sha256"] for name, item in controls.items()}),
        "source_set_hash": canonical_hash({name: item["sha256"] for name, item in sources.items()}),
        "feature_values_accessed": False,
        "development_outcomes_accessed": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "execution_or_pnl_permitted": False,
        "paid_acquisition_authorized": False,
    }
    write_json_exclusive(DESIGN_FREEZE, freeze)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        OUTPUT / "state.json",
        {
            "version": "GOLD_TPCE_V1_STATE_1_0",
            "status": "DESIGN_FROZEN_AWAITING_OUTCOME_BLIND_MATERIALIZATION",
            "recorded_at_utc": utc_now(),
            "design_freeze": record(DESIGN_FREEZE),
            "forward_locked": ["2025", "2026"],
            "paid_acquisition_usd": 0.0,
        },
    )
    print(json.dumps({"status": freeze["status"], "design_freeze": record(DESIGN_FREEZE)}, indent=2))


if __name__ == "__main__":
    main()
