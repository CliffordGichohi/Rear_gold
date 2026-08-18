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
CONTRACT = ROOT / "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_RESEARCH_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_protocol.json"
OUTPUT = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_pre_outcome_freeze.json"


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
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)

    routing = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"
    anatomy = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
    features = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
    stop_study = ARTIFACTS / "gold_structural_stop_geometry_v1_economic"
    gc_features = ARTIFACTS / "gc_microstructure_step5c_v01"
    gc_session = ARTIFACTS / "gc_session_trigger_edge_v2r1_v01"
    price = ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz"

    seals = {
        "routing": routing / "development_seal.json",
        "movement_anatomy": anatomy / "movement_anatomy_certification.json",
        "structural_stop_final": stop_study / "final_seal.json",
    }
    expected = {
        "routing": "REJECT_DEVELOPMENT_ROUTED_SYSTEM",
        "movement_anatomy": "PASS_MOVEMENT_ANATOMY_MATERIALIZATION",
        "structural_stop_final": "REJECT_NO_DEVELOPMENT_ECONOMIC_STOP_CANDIDATE",
    }
    for name, path in seals.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != expected[name]:
            raise ValueError(f"Predecessor status changed: {name}")
        for key in ("forward_values_accessed", "calendar_2025_values_accessed", "calendar_2026_values_accessed"):
            if payload.get(key) is True:
                raise ValueError(f"Forward lock changed in predecessor: {name}:{key}")

    pairs = {
        "model_trades": (routing / "primary_model_trades.parquet", routing / "reference_model_trades.parquet", 51_918),
        "trigger_facts": (anatomy / "primary_trigger_facts.parquet", anatomy / "reference_trigger_facts.parquet", 42_085),
        "features": (features / "primary_features.parquet", features / "reference_features.parquet", 37_191),
    }
    frozen_pairs: dict[str, Any] = {}
    for name, (primary, reference, expected_rows) in pairs.items():
        primary_hash = sha256_file(primary)
        reference_hash = sha256_file(reference)
        if primary_hash != reference_hash:
            raise ValueError(f"Primary/reference source differs: {name}")
        primary_meta = pq.read_metadata(primary)
        reference_meta = pq.read_metadata(reference)
        if primary_meta.num_rows != expected_rows or reference_meta.num_rows != expected_rows:
            raise ValueError(f"Unexpected source population: {name}")
        if primary_meta.num_columns != reference_meta.num_columns:
            raise ValueError(f"Primary/reference schema differs: {name}")
        frozen_pairs[name] = {
            "primary": record(primary),
            "reference": record(reference),
            "rows": expected_rows,
            "columns": primary_meta.num_columns,
            "byte_identical": True,
        }

    executed = pq.read_table(
        pairs["model_trades"][0], columns=["trade_id", "status", "timeframe", "model_id", "entry_at_utc"]
    ).to_pylist()
    executed = [row for row in executed if row["status"] == "EXECUTED"]
    if len(executed) != 22_193 or len({row["trade_id"] for row in executed}) != 22_193:
        raise ValueError("Frozen executed-setup population changed")
    if any(not str(row["entry_at_utc"]).startswith(("2021-", "2022-", "2023-", "2024-")) for row in executed):
        raise ValueError("Forward setup found in development population")

    anatomy_cert = json.loads(seals["movement_anatomy"].read_text(encoding="utf-8"))
    if anatomy_cert["price_diagnostics"]["source"] != record(price):
        raise ValueError("Development XAUUSD source changed")

    gc_records: dict[str, Any] = {}
    for name in ("primary_london_buckets.parquet", "reference_london_buckets.parquet", "primary_new_york_buckets.parquet", "reference_new_york_buckets.parquet"):
        path = gc_features / name
        if not path.is_file():
            raise FileNotFoundError(path)
        gc_records[name] = record(path)
    if gc_records["primary_london_buckets.parquet"]["sha256"] != gc_records["reference_london_buckets.parquet"]["sha256"]:
        raise ValueError("London GC feature pair differs")
    if gc_records["primary_new_york_buckets.parquet"]["sha256"] != gc_records["reference_new_york_buckets.parquet"]["sha256"]:
        raise ValueError("New York GC feature pair differs")
    gc_manifest = gc_session / "manifest.json"
    gc_payload = json.loads(gc_manifest.read_text(encoding="utf-8"))
    if gc_payload.get("status") != "PASS_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION":
        raise ValueError("GC full-session technical certification changed")

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_DELAYED_ENTRY_MATERIALIZATION_OR_OUTCOMES":
        raise ValueError("Protocol is not frozen")
    if protocol["candidate_tests"] != 36 or len(protocol["family_mapping"]) != 6:
        raise ValueError("Frozen test registry changed")
    if protocol.get("calendar_2025_values_accessed") or protocol.get("calendar_2026_values_accessed"):
        raise ValueError("Forward lock not intact")

    payload = {
        "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_PRE_OUTCOME_FREEZE_1_0",
        "status": "FROZEN_READY_FOR_OUTCOME_BLIND_CONFIRMATION_MATERIALIZATION",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "controls": {"contract": record(CONTRACT), "protocol": record(PROTOCOL)},
        "predecessor_seals": {name: record(path) for name, path in seals.items()},
        "source_pairs": frozen_pairs,
        "development_xauusd": record(price),
        "gc_incremental_existing_sources": gc_records,
        "gc_full_session_technical_manifest": record(gc_manifest),
        "coverage": {
            "executed_setup_rows": 22_193,
            "setup_date_min": min(str(row["entry_at_utc"]) for row in executed),
            "setup_date_max": max(str(row["entry_at_utc"]) for row in executed),
            "timeframe_counts": {
                timeframe: sum(row["timeframe"] == timeframe for row in executed)
                for timeframe in ("M15", "H1", "H4")
            },
            "model_counts": {
                model: sum(row["model_id"] == model for row in executed)
                for model in sorted({str(row["model_id"]) for row in executed})
            },
        },
        "outcome_access_before_freeze": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_exclusive(OUTPUT, payload)
    print(json.dumps({"status": payload["status"], "freeze": record(OUTPUT), "coverage": payload["coverage"]}, sort_keys=True))


if __name__ == "__main__":
    main()
