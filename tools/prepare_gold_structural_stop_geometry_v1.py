from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
CONTRACT = ROOT / "GOLD_STRUCTURAL_STOP_GEOMETRY_ECONOMIC_RESEARCH_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_structural_stop_geometry_v1_protocol.json"
ENTRY_PROTOCOL = MANIFESTS / "gold_pullback_archetype_setup_routing_v1_protocol.json"
FREEZE = MANIFESTS / "gold_structural_stop_geometry_v1_pre_result_freeze.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if FREEZE.exists():
        raise FileExistsError(FREEZE)
    routing = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"
    anatomy = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
    features = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
    atlas = ARTIFACTS / "gold_pullback_behavioural_archetypes_v1"
    census = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
    gap = ARTIFACTS / "gold_pullback_monetizability_gap_decomposition_v1"
    price = ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz"

    seals = {
        "routing": routing / "development_seal.json",
        "anatomy": anatomy / "movement_anatomy_certification.json",
        "atlas": atlas / "final_seal.json",
        "census": census / "final_seal.json",
        "gap_decomposition": gap / "final_seal.json",
    }
    expected_statuses = {
        "routing": "REJECT_DEVELOPMENT_ROUTED_SYSTEM",
        "anatomy": "PASS_MOVEMENT_ANATOMY_MATERIALIZATION",
        "atlas": "PASS_COMPLETE_DEVELOPMENT_ARCHETYPE_ATLAS",
        "census": "PASS_COMPLETE_DESCRIPTIVE_CENSUS",
        "gap_decomposition": "PASS_COMPLETE_INDEPENDENT_DECOMPOSITION",
    }
    for name, path in seals.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != expected_statuses[name]:
            raise ValueError(f"Predecessor status changed: {name}")
        for key in ("forward_values_accessed", "calendar_2025_values_accessed", "calendar_2026_values_accessed"):
            if payload.get(key) is True:
                raise ValueError(f"Development predecessor unexpectedly records forward access: {name}:{key}")

    pairs = {
        "model_trades": (routing / "primary_model_trades.parquet", routing / "reference_model_trades.parquet", 51918),
        "archetypes": (atlas / "primary_archetypes.parquet", atlas / "reference_archetypes.parquet", 8653),
        "trigger_facts": (anatomy / "primary_trigger_facts.parquet", anatomy / "reference_trigger_facts.parquet", 42085),
        "features": (features / "primary_features.parquet", features / "reference_features.parquet", 37191),
        "pullback_cases": (census / "primary_pullback_cases.parquet", census / "reference_pullback_cases.parquet", 37191),
        "swings": (census / "primary_swings.parquet", census / "reference_swings.parquet", 96909),
    }
    source_pairs = {}
    for name, (primary, reference, rows) in pairs.items():
        if sha256_file(primary) != sha256_file(reference):
            raise ValueError(f"Primary/reference pair changed: {name}")
        left = pq.read_metadata(primary)
        right = pq.read_metadata(reference)
        if left.num_rows != rows or right.num_rows != rows or left.num_columns != right.num_columns:
            raise ValueError(f"Metadata mismatch: {name}")
        source_pairs[name] = {
            "primary": record(primary), "reference": record(reference), "rows": rows,
            "columns": left.num_columns, "primary_reference_byte_identical": True,
        }
    anatomy_cert = json.loads(seals["anatomy"].read_text(encoding="utf-8"))
    if record(price) != anatomy_cert["price_diagnostics"]["source"]:
        raise ValueError("Development price source changed")
    entry = json.loads(ENTRY_PROTOCOL.read_text(encoding="utf-8"))
    if len(entry["entry_models"]) != 6:
        raise ValueError("Frozen entry model registry changed")

    freeze = {
        "version": "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_PRE_RESULT_FREEZE_1_0",
        "status": "FROZEN_READY_FOR_STAGE_1",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "controls": {"contract": record(CONTRACT), "protocol": record(PROTOCOL), "entry_protocol": record(ENTRY_PROTOCOL)},
        "predecessor_seals": {name: record(path) for name, path in seals.items()},
        "source_pairs": source_pairs,
        "development_price": record(price),
        "expected": {
            "model_case_rows": 51918,
            "frozen_executed_rows": 22193,
            "primary_stops_per_model": 4,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
        },
        "stop_path_or_economic_results_accessed_before_freeze": False,
        "paid_acquisition_usd": 0.0,
    }
    write_exclusive(FREEZE, freeze)
    print(json.dumps({"status": freeze["status"], "freeze": record(FREEZE)}, sort_keys=True))


if __name__ == "__main__":
    main()
