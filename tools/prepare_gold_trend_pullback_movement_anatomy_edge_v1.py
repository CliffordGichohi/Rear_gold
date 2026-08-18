from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
CONTRACT = ROOT / "GOLD_TREND_PULLBACK_MOVEMENT_ANATOMY_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_protocol.json"
FREEZE = MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_design_freeze.json"
STATE = OUTPUT / "state_m1.json"

CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
EDGE = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
ECONOMIC = ARTIFACTS / "gold_trend_pullback_continuation_economic_v1_v01"
CASEBOOK = ARTIFACTS / "gold_casebook_v01"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


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


def main() -> None:
    if FREEZE.exists() or STATE.exists():
        raise FileExistsError("Movement-anatomy design already frozen")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["status"] != "FROZEN_BEFORE_NEW_MOVEMENT_ANATOMY_ACCESS":
        raise ValueError("Protocol is not frozen")
    predecessor_candidates = json.loads((EDGE / "frozen_provisional_candidates.json").read_text(encoding="utf-8"))
    if predecessor_candidates["candidate_count"] != 9:
        raise ValueError("Expected exactly nine predecessor relationship candidates")
    prior_economic = json.loads((ECONOMIC / "final_seal.json").read_text(encoding="utf-8"))
    if prior_economic["status"] != "REJECT_NO_ECONOMIC_EDGE_UNDER_FROZEN_EXECUTION":
        raise ValueError("Prior economic verdict changed")
    sources = {
        "contract": CONTRACT,
        "protocol": PROTOCOL,
        "casebook_price_bars": CASEBOOK / "price_bars.jsonl.gz",
        "features_primary": EDGE / "primary_features.parquet",
        "features_reference": EDGE / "reference_features.parquet",
        "census_cases_primary": CENSUS / "primary_pullback_cases.parquet",
        "census_cases_reference": CENSUS / "reference_pullback_cases.parquet",
        "swings_primary": CENSUS / "primary_swings.parquet",
        "swings_reference": CENSUS / "reference_swings.parquet",
        "structure_events_primary": CENSUS / "primary_structure_events.parquet",
        "structure_events_reference": CENSUS / "reference_structure_events.parquet",
        "census_final_seal": CENSUS / "final_seal.json",
        "relationship_candidates": EDGE / "frozen_provisional_candidates.json",
        "relationship_final_seal": EDGE / "final_seal.json",
        "prior_economic_final_seal": ECONOMIC / "final_seal.json",
    }
    for name, path in sources.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing {name}: {path}")
    if sha256_file(sources["features_primary"]) != sha256_file(sources["features_reference"]):
        raise ValueError("Feature predecessors differ")
    if sha256_file(sources["census_cases_primary"]) != sha256_file(sources["census_cases_reference"]):
        raise ValueError("Case predecessors differ")
    metadata = {}
    for name in ("features_primary", "census_cases_primary", "swings_primary", "structure_events_primary"):
        path = sources[name]
        meta = pq.read_metadata(path)
        metadata[name] = {"rows": meta.num_rows, "row_groups": meta.num_row_groups, "schema": str(pq.read_schema(path))}
    freeze = {
        "version": "GOLD_TPMA_EDGE_V1_DESIGN_FREEZE_1_0",
        "status": "FROZEN_BEFORE_NEW_MOVEMENT_ANATOMY_ACCESS",
        "frozen_at_utc": utc_now(),
        "predecessor_candidate_ids": predecessor_candidates["candidate_ids"],
        "execution_specifications_per_condition": 180,
        "total_registered_condition_specifications": 1620,
        "source_records": {name: file_record(path) for name, path in sources.items()},
        "source_metadata": metadata,
        "forward_values_accessed_for_new_branch": False,
        "paid_acquisition_authorized": False,
        "retuning_after_outcome_access": False,
    }
    freeze["freeze_hash"] = canonical_hash(freeze)
    write_json_exclusive(FREEZE, freeze)
    write_json_exclusive(STATE, {
        "version": "GOLD_TPMA_EDGE_V1_STATE_M1_1_0",
        "status": "PASS_DESIGN_FROZEN",
        "recorded_at_utc": utc_now(),
        "design_freeze": file_record(FREEZE),
        "next_step": "MATERIALIZE_DEVELOPMENT_MOVEMENT_ANATOMY_AND_EXECUTION_GRID",
    })
    print(json.dumps({
        "status": "PASS_DESIGN_FROZEN",
        "candidate_conditions": 9,
        "registered_specifications": 1620,
        "design_freeze": file_record(FREEZE),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
