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
CONTRACT = ROOT / "GOLD_PULLBACK_MONETIZABILITY_GAP_DECOMPOSITION_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_pullback_monetizability_gap_decomposition_v1_protocol.json"
FREEZE = MANIFESTS / "gold_pullback_monetizability_gap_decomposition_v1_pre_result_freeze.json"

ATLAS = ARTIFACTS / "gold_pullback_behavioural_archetypes_v1"
ANATOMY = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
ROUTING = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"
PRICE = ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz"


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
    atlas_seal = json.loads((ATLAS / "final_seal.json").read_text(encoding="utf-8"))
    anatomy_cert = json.loads((ANATOMY / "movement_anatomy_certification.json").read_text(encoding="utf-8"))
    routing_seal = json.loads((ROUTING / "development_seal.json").read_text(encoding="utf-8"))
    if atlas_seal["status"] != "PASS_COMPLETE_DEVELOPMENT_ARCHETYPE_ATLAS" or atlas_seal["forward_values_accessed"]:
        raise ValueError("Atlas seal invalid")
    if anatomy_cert["status"] != "PASS_MOVEMENT_ANATOMY_MATERIALIZATION" or anatomy_cert["forward_values_accessed"]:
        raise ValueError("Anatomy certification invalid")
    if routing_seal["status"] != "REJECT_DEVELOPMENT_ROUTED_SYSTEM":
        raise ValueError("Corrected routing result not preserved")
    if routing_seal["calendar_2025_values_accessed"] or routing_seal["calendar_2026_values_accessed"]:
        raise ValueError("Routing development seal unexpectedly contains forward access")

    pairs = {
        "archetypes": (ATLAS / "primary_archetypes.parquet", ATLAS / "reference_archetypes.parquet", 8653),
        "movement_anatomy": (ANATOMY / "primary_movement_anatomy.parquet", ANATOMY / "reference_movement_anatomy.parquet", 8653),
        "trigger_facts": (ANATOMY / "primary_trigger_facts.parquet", ANATOMY / "reference_trigger_facts.parquet", 42085),
        "model_trades": (ROUTING / "primary_model_trades.parquet", ROUTING / "reference_model_trades.parquet", 51918),
        "oof_predictions": (ROUTING / "primary_oof_predictions.parquet", ROUTING / "reference_oof_predictions.parquet", 16240),
        "equal_risk_oof_decisions": (ROUTING / "primary_equal_risk_oof_decisions.parquet", ROUTING / "reference_equal_risk_oof_decisions.parquet", 16240),
        "variable_risk_oof_decisions": (ROUTING / "primary_variable_risk_oof_decisions.parquet", ROUTING / "reference_variable_risk_oof_decisions.parquet", 497),
    }
    pair_records: dict[str, Any] = {}
    for name, (primary, reference, expected_rows) in pairs.items():
        if sha256_file(primary) != sha256_file(reference):
            raise ValueError(f"Primary/reference source differs: {name}")
        primary_metadata = pq.read_metadata(primary)
        reference_metadata = pq.read_metadata(reference)
        if primary_metadata.num_rows != expected_rows or reference_metadata.num_rows != expected_rows:
            raise ValueError(f"Unexpected row count: {name}")
        pair_records[name] = {
            "primary": record(primary),
            "reference": record(reference),
            "rows": expected_rows,
            "columns": primary_metadata.num_columns,
            "primary_reference_byte_identical": True,
        }
    if record(PRICE) != anatomy_cert["price_diagnostics"]["source"]:
        raise ValueError("Development price source changed")

    freeze = {
        "version": "GOLD_PULLBACK_MONETIZABILITY_GAP_DECOMPOSITION_V1_PRE_RESULT_FREEZE_1_0",
        "status": "FROZEN_AND_READY_FOR_DECOMPOSITION",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "controls": {"contract": record(CONTRACT), "protocol": record(PROTOCOL)},
        "predecessor_seals": {
            "atlas": record(ATLAS / "final_seal.json"),
            "anatomy": record(ANATOMY / "movement_anatomy_certification.json"),
            "routing": record(ROUTING / "development_seal.json"),
        },
        "source_pairs": pair_records,
        "development_price": record(PRICE),
        "expected": {
            "pullback_cases": 8653,
            "model_case_rows": 51918,
            "models": 6,
            "oof_prediction_rows": 16240,
            "equal_risk_oof_decision_rows": 16240,
            "variable_risk_oof_decision_rows": 497,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
        },
        "value_rows_accessed_before_freeze": False,
        "paid_acquisition_usd": 0.0,
    }
    write_exclusive(FREEZE, freeze)
    print(json.dumps({"status": freeze["status"], "freeze": record(FREEZE)}, sort_keys=True))


if __name__ == "__main__":
    main()
