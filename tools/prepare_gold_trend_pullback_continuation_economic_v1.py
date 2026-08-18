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
OUTPUT = ARTIFACTS / "gold_trend_pullback_continuation_economic_v1_v01"

CONTRACT = ROOT / "GOLD_TREND_PULLBACK_CONTINUATION_ECONOMIC_EDGE_VALIDATION_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_trend_pullback_continuation_economic_v1_protocol.json"
DESIGN_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_economic_v1_design_freeze.json"

PREDECESSOR = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
CASEBOOK = ARTIFACTS / "gold_casebook_v01"
FORWARD_SNAPSHOT = ARTIFACTS / "gold_session_behaviour_v3_m6b_source_snapshot_v01"
MT5 = ROOT / "data" / "mt5"

EXPECTED_CANDIDATES = [
    "M15|S1|RESPONSE_DISPLACEMENT_HALF_ATR",
    "M15|S1|CONFIRMATION_DISPLACEMENT",
    "M15|S2|REFERENCE_SWEEP_RECLAIM__CONFIRMATION_DISPLACEMENT",
    "H1|S1|RESPONSE_DISPLACEMENT_HALF_ATR",
    "H1|S1|CONFIRMATION_DISPLACEMENT",
    "H1|S1|REFERENCE_SWEEP_RECLAIM",
    "H4|S1|RESPONSE_DISPLACEMENT_HALF_ATR",
    "H4|S1|REFERENCE_SWEEP_RECLAIM",
    "H4|S1|HTF_FULL_ALIGNMENT",
]


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


def verify_predecessor() -> dict[str, Any]:
    seal_path = PREDECESSOR / "final_seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("status") != "PASS_PROVISIONAL_DEVELOPMENT_RELATIONSHIP":
        raise ValueError("Relationship predecessor did not pass")
    if seal.get("calendar_2025_values_accessed") is not False or seal.get("calendar_2026_values_accessed") is not False:
        raise ValueError("Relationship predecessor forward boundary is not clean")
    if seal.get("execution_or_pnl_calculated") is not False:
        raise ValueError("Relationship predecessor already accessed economics")
    candidates_path = PREDECESSOR / "frozen_provisional_candidates.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    if candidates.get("candidate_ids") != EXPECTED_CANDIDATES or candidates.get("candidate_count") != 9:
        raise ValueError("Frozen candidate identities changed")
    for name, item in seal["artifacts"].items():
        path = ROOT / item["path"]
        if not path.exists() or record(path)["sha256"] != item["sha256"]:
            raise ValueError(f"Predecessor artifact changed: {name}")
    return {
        "status": seal["status"],
        "final_seal": record(seal_path),
        "candidate_source": record(candidates_path),
        "candidate_ids": EXPECTED_CANDIDATES,
        "predecessor_artifact_set_hash": seal["artifact_set_hash"],
    }


def forward_files() -> list[dict[str, Any]]:
    snapshot_path = FORWARD_SNAPSHOT / "source_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    records = [
        item for item in snapshot["lineage"]["batch_records"]
        if item.get("dataset_code") == "XAUUSD_1M"
    ]
    if not records:
        raise ValueError("No sealed XAUUSD forward batches")
    output = []
    seen_names: set[str] = set()
    for item in records:
        name = Path(str(item["raw_object_path"])).name
        if name in seen_names:
            raise ValueError(f"Duplicate forward batch name: {name}")
        seen_names.add(name)
        path = MT5 / name
        if not path.exists():
            raise FileNotFoundError(path)
        source = record(path)
        if source["sha256"] != item["content_hash"]:
            raise ValueError(f"Local forward hash differs from sealed snapshot: {name}")
        output.append({
            **source,
            "batch_id": item["batch_id"],
            "provider_code": item["provider_code"],
            "dataset_code": item["dataset_code"],
            "declared_record_count": item["record_count"],
            "declared_status": item["status"],
        })
    return output


def main() -> None:
    if DESIGN_FREEZE.exists() or OUTPUT.exists():
        raise FileExistsError("Economic V1 design/output already exists")
    predecessor = verify_predecessor()
    controls = {"contract": record(CONTRACT), "protocol": record(PROTOCOL)}
    sources = {
        "development_price_bars": record(CASEBOOK / "price_bars.jsonl.gz"),
        "development_casebook_manifest": record(CASEBOOK / "manifest.json"),
        "census_pullbacks": record(CENSUS / "primary_pullback_cases.parquet"),
        "census_swings": record(CENSUS / "primary_swings.parquet"),
        "census_events": record(CENSUS / "primary_structure_events.parquet"),
        "feature_matrix": record(PREDECESSOR / "primary_features.parquet"),
        "candidate_source": predecessor["candidate_source"],
        "relationship_final_seal": predecessor["final_seal"],
        "forward_source_snapshot": record(FORWARD_SNAPSHOT / "source_snapshot.json"),
        "forward_source_snapshot_manifest": record(FORWARD_SNAPSHOT / "manifest.json"),
        "forward_metadata_readiness_audit": record(FORWARD_SNAPSHOT / "metadata_readiness_audit.json"),
    }
    forward = forward_files()
    freeze = {
        "version": "GOLD_TPCE_ECONOMIC_V1_DESIGN_FREEZE_1_0",
        "status": "FROZEN_BEFORE_POST_DECISION_PRICE_PATH_ACCESS",
        "sealed_at_utc": utc_now(),
        "controls": controls,
        "predecessor": predecessor,
        "sources": sources,
        "forward_xauusd_batches": forward,
        "control_set_hash": canonical_hash({name: item["sha256"] for name, item in controls.items()}),
        "source_set_hash": canonical_hash({name: item["sha256"] for name, item in sources.items()}),
        "forward_batch_set_hash": canonical_hash([{key: item[key] for key in ("path", "bytes", "sha256", "declared_record_count")} for item in forward]),
        "development_post_decision_paths_accessed": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_authorized": False,
        "live_trading_authorized": False,
    }
    write_json_exclusive(DESIGN_FREEZE, freeze)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        OUTPUT / "state_m1.json",
        {
            "version": "GOLD_TPCE_ECONOMIC_V1_STATE_M1_1_0",
            "status": freeze["status"],
            "recorded_at_utc": utc_now(),
            "design_freeze": record(DESIGN_FREEZE),
            "candidate_count": 9,
            "forward_batch_count": len(forward),
            "next_step": "DEVELOPMENT_TRADE_PATH_MATERIALIZATION",
        },
    )
    print(json.dumps({
        "status": freeze["status"],
        "candidate_count": 9,
        "forward_batch_count": len(forward),
        "design_freeze": record(DESIGN_FREEZE),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
