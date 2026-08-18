from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
CONTRACT = ROOT / "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_AND_RISK_ALLOCATION_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_pullback_archetype_setup_routing_v1_protocol.json"
FREEZE = MANIFESTS / "gold_pullback_archetype_setup_routing_v1_preperformance_freeze.json"

SOURCES = {
    "archetypes_primary": ARTIFACTS / "gold_pullback_behavioural_archetypes_v1/primary_archetypes.parquet",
    "archetypes_reference": ARTIFACTS / "gold_pullback_behavioural_archetypes_v1/reference_archetypes.parquet",
    "archetype_seal": ARTIFACTS / "gold_pullback_behavioural_archetypes_v1/final_seal.json",
    "features_primary": ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01/primary_features.parquet",
    "features_reference": ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01/reference_features.parquet",
    "triggers_primary": ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01/primary_trigger_facts.parquet",
    "triggers_reference": ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01/reference_trigger_facts.parquet",
    "anatomy_primary": ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01/primary_movement_anatomy.parquet",
    "anatomy_reference": ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01/reference_movement_anatomy.parquet",
    "cases_primary": ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02/primary_pullback_cases.parquet",
    "cases_reference": ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02/reference_pullback_cases.parquet",
    "swings_primary": ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02/primary_swings.parquet",
    "swings_reference": ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02/reference_swings.parquet",
    "events_primary": ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02/primary_structure_events.parquet",
    "events_reference": ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02/reference_structure_events.parquet",
    "price_bars": ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz",
    "movement_pretest_seal": MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_pretest_seal.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.suffix == ".parquet":
        parquet = pq.ParquetFile(path)
        item.update({
            "rows": parquet.metadata.num_rows,
            "row_groups": parquet.metadata.num_row_groups,
            "schema": str(parquet.schema_arrow),
        })
    return item


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["status"] != "FROZEN_BEFORE_NEW_MODEL_BY_ARCHETYPE_PERFORMANCE_MEASUREMENT":
        raise ValueError("Protocol is not frozen")
    missing = [name for name, path in SOURCES.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing predecessor sources: {missing}")
    sources = {name: record(path) for name, path in SOURCES.items()}
    controls = {"contract": record(CONTRACT), "protocol": record(PROTOCOL)}
    freeze = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_PREPERFORMANCE_FREEZE_1_0",
        "status": "FROZEN_BEFORE_NEW_MODEL_BY_ARCHETYPE_PERFORMANCE_MEASUREMENT",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "controls": controls,
        "sources": sources,
        "source_set_hash": canonical_hash({name: item["sha256"] for name, item in sources.items()}),
        "entry_model_registry_hash": canonical_hash(protocol["entry_models"]),
        "probability_protocol_hash": canonical_hash(protocol["probability_tree"]),
        "risk_protocol_hash": canonical_hash({"risk": protocol["risk"], "costs": protocol["costs_usd_per_ounce_roundtrip"]}),
        "prior_development_outcomes_previously_exposed": True,
        "new_model_by_archetype_performance_measured_before_freeze": False,
        "calendar_2025_values_accessed_for_branch": False,
        "calendar_2026_values_accessed_for_branch": False,
        "paid_acquisition_authorized": False,
    }
    write_exclusive(FREEZE, freeze)
    print(json.dumps({
        "status": freeze["status"],
        "source_count": len(sources),
        "source_set_hash": freeze["source_set_hash"],
        "entry_model_registry_hash": freeze["entry_model_registry_hash"],
        "calendar_2025_values_accessed_for_branch": False,
        "calendar_2026_values_accessed_for_branch": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
