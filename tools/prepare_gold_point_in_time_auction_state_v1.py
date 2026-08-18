from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
CONTRACT = ROOT / "GOLD_POINT_IN_TIME_AUCTION_STATE_AND_ADAPTIVE_TRADE_MANAGEMENT_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_protocol.json"
OUTPUT = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_preoutcome"
FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_preoutcome_freeze.json"

ATLAS = ARTIFACTS / "gold_pullback_behavioural_archetypes_v1"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
FEATURES = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
ANATOMY = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
CASEBOOK = ARTIFACTS / "gold_casebook_v01"
SEQUENTIAL = ARTIFACTS / "gold_sequential_auction_confirmation_entry_v1_development"
GC_MANIFEST = ARTIFACTS / "gc_session_trigger_edge_v2r1_v01" / "manifest.json"

TF_PRICE = {"M15": "15m", "H1": "1h", "H4": "4h"}
SIGNAL_PRICE = {"M15": "1m", "H1": "5m", "H4": "15m"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * 1_000_000_000 + parsed.microsecond * 1_000


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z")


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True); raise


def write_parquet_exclusive(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        table = pa.Table.from_pylist(list(rows))
        pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, version="2.6", data_page_version="1.0")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True); raise


def verify_seal(path: Path, status: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != status:
        raise ValueError(f"Predecessor status changed: {path}:{payload.get('status')}")
    return payload


def timestamp_registry() -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, Any]]:
    selected: dict[str, list[tuple[int, int]]] = {timeframe: [] for timeframe in ("1m", "5m", "15m", "1h", "4h")}
    counts: Counter[str] = Counter(); malformed = 0
    path = CASEBOOK / "price_bars.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("record_type") != "PRICE_BAR" or row.get("instrument_code") != "XAUUSD":
                continue
            timeframe = str(row.get("timeframe"))
            if timeframe not in selected:
                continue
            if not bool(row.get("complete", True)):
                malformed += 1; continue
            opened = parse_ns(str(row["open_time"])); closed = parse_ns(str(row["close_time"]))
            if opened >= parse_ns("2025-01-01T00:00:00Z") or closed > parse_ns("2025-01-01T00:00:00Z"):
                raise ValueError("Forward timestamp entered development timestamp registry")
            selected[timeframe].append((opened, closed)); counts[timeframe] += 1
    opens: dict[str, np.ndarray] = {}; closes: dict[str, np.ndarray] = {}
    for timeframe, values in selected.items():
        values.sort()
        opens[timeframe] = np.asarray([row[0] for row in values], dtype=np.int64)
        closes[timeframe] = np.asarray([row[1] for row in values], dtype=np.int64)
        if len(values) == 0 or np.any(np.diff(opens[timeframe]) <= 0) or np.any(np.diff(closes[timeframe]) <= 0):
            raise ValueError(f"Timestamp registry invalid: {timeframe}")
    return opens, closes, {"source": record(path), "counts": dict(sorted(counts.items())), "incomplete_skipped": malformed}


def load_identities(side: str) -> list[dict[str, Any]]:
    columns = ["pullback_id", "timeframe", "direction", "known_at_utc", "decision_date"]
    return [dict(row) for row in pq.read_table(ATLAS / f"{side}_archetypes.parquet", columns=columns).to_pylist()]


def case_registry(cases: Sequence[dict[str, Any]], opens: dict[str, np.ndarray], closes: dict[str, np.ndarray], implementation: str) -> tuple[list[dict[str, Any]], str]:
    output: list[dict[str, Any]] = []; global_digest = hashlib.sha256()
    for case in sorted(cases, key=lambda row: (str(row["known_at_utc"]), str(row["timeframe"]), str(row["pullback_id"]))):
        timeframe = str(case["timeframe"]); known_ns = parse_ns(str(case["known_at_utc"])); parent_close = closes[TF_PRICE[timeframe]]
        if implementation == "primary":
            first_parent = int(np.searchsorted(parent_close, known_ns, side="right"))
        else:
            first_parent = bisect.bisect_right(parent_close, known_ns)
        deadline_index = first_parent + 16 - 1
        deadline = int(parent_close[deadline_index]) if deadline_index < len(parent_close) else None
        status = "AVAILABLE"; reason = ""
        checkpoint_times: list[int] = []
        if deadline is None:
            status = "UNAVAILABLE_TECHNICAL"; reason = "MISSING_SIXTEENTH_PARENT_DEADLINE"
        else:
            signal_close = closes[SIGNAL_PRICE[timeframe]]; signal_open = opens[SIGNAL_PRICE[timeframe]]; m1_open = opens["1m"]
            if implementation == "primary":
                left = int(np.searchsorted(signal_close, known_ns, side="left")); right = int(np.searchsorted(signal_close, deadline, side="left"))
            else:
                left = bisect.bisect_left(signal_close, known_ns); right = bisect.bisect_left(signal_close, deadline)
            for index in range(left, right):
                checkpoint = int(signal_close[index])
                signal_entry = int(np.searchsorted(signal_open, checkpoint, side="left")) if implementation == "primary" else bisect.bisect_left(signal_open, checkpoint)
                m1_entry = int(np.searchsorted(m1_open, checkpoint, side="left")) if implementation == "primary" else bisect.bisect_left(m1_open, checkpoint)
                if signal_entry >= len(signal_open) or int(signal_open[signal_entry]) != checkpoint or m1_entry >= len(m1_open) or int(m1_open[m1_entry]) != checkpoint:
                    continue
                checkpoint_times.append(checkpoint)
            if not checkpoint_times:
                status = "UNAVAILABLE_TECHNICAL"; reason = "NO_EXACT_CHECKPOINT_FILL_TIMESTAMPS"
        checkpoint_hash = canonical_hash(checkpoint_times)
        for timestamp in checkpoint_times:
            global_digest.update(canonical_json([str(case["pullback_id"]), timestamp]).encode("utf-8")); global_digest.update(b"\n")
        output.append({
            "pullback_id": str(case["pullback_id"]), "timeframe": timeframe, "direction": str(case["direction"]),
            "known_at_utc": str(case["known_at_utc"]), "decision_date": str(case["decision_date"]),
            "deadline_at_utc": ns_iso(deadline) if deadline is not None else None, "tape_status": status,
            "unavailable_reason": reason, "checkpoint_rows": len(checkpoint_times),
            "first_checkpoint_at_utc": ns_iso(checkpoint_times[0]) if checkpoint_times else None,
            "last_checkpoint_at_utc": ns_iso(checkpoint_times[-1]) if checkpoint_times else None,
            "checkpoint_timestamp_hash": checkpoint_hash,
            "case_tape_identity_hash": canonical_hash([str(case["pullback_id"]), timeframe, str(case["direction"]), str(case["known_at_utc"]), deadline, checkpoint_hash]),
        })
    return output, global_digest.hexdigest()


def main() -> None:
    if OUTPUT.exists() or FREEZE.exists():
        raise FileExistsError(OUTPUT if OUTPUT.exists() else FREEZE)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_DECISION_TAPE_MARKET_VALUES_OR_OUTCOMES":
        raise ValueError("Protocol status changed")
    predecessor_paths = {
        "atlas": ATLAS / "final_seal.json",
        "census": CENSUS / "final_seal.json",
        "features": FEATURES / "final_seal.json",
        "sequential_rejection": SEQUENTIAL / "final_seal.json",
    }
    expected = {
        "atlas": "PASS_COMPLETE_DEVELOPMENT_ARCHETYPE_ATLAS",
        "census": "PASS_COMPLETE_DESCRIPTIVE_CENSUS",
        "features": "PASS_PROVISIONAL_DEVELOPMENT_RELATIONSHIP",
        "sequential_rejection": "REJECT_NO_DEVELOPMENT_ECONOMIC_CANDIDATE",
    }
    predecessor_payloads = {name: verify_seal(path, expected[name]) for name, path in predecessor_paths.items()}
    for name, payload in predecessor_payloads.items():
        for key in ("forward_values_accessed", "calendar_2025_values_accessed", "calendar_2026_values_accessed"):
            if payload.get(key) is True:
                raise ValueError(f"Unexpected predecessor forward access: {name}:{key}")
    pairs = {
        "atlas": (ATLAS / "primary_archetypes.parquet", ATLAS / "reference_archetypes.parquet", 8653),
        "features": (FEATURES / "primary_features.parquet", FEATURES / "reference_features.parquet", 37191),
        "cases": (CENSUS / "primary_pullback_cases.parquet", CENSUS / "reference_pullback_cases.parquet", 37191),
        "swings": (CENSUS / "primary_swings.parquet", CENSUS / "reference_swings.parquet", 96909),
        "events": (CENSUS / "primary_structure_events.parquet", CENSUS / "reference_structure_events.parquet", 46247),
        "triggers": (ANATOMY / "primary_trigger_facts.parquet", ANATOMY / "reference_trigger_facts.parquet", 42085),
    }
    pair_records: dict[str, Any] = {}
    for name, (primary, reference, rows) in pairs.items():
        if sha256_file(primary) != sha256_file(reference):
            raise ValueError(f"Source pair differs: {name}")
        if pq.read_metadata(primary).num_rows != rows or pq.read_metadata(reference).num_rows != rows:
            raise ValueError(f"Source row count differs: {name}")
        pair_records[name] = {"primary": record(primary), "reference": record(reference), "rows": rows, "byte_identical": True}
    primary_cases = load_identities("primary"); reference_cases = load_identities("reference")
    if primary_cases != reference_cases or len(primary_cases) != 8653 or len({row["pullback_id"] for row in primary_cases}) != 8653:
        raise ValueError("Unique identity population changed")
    if canonical_hash([row["pullback_id"] for row in primary_cases]) != protocol["population"]["identity_hash"]:
        raise ValueError("Unique identity hash changed")
    opens, closes, price_metadata = timestamp_registry()
    primary_registry, primary_hash = case_registry(primary_cases, opens, closes, "primary")
    reference_registry, reference_hash = case_registry(reference_cases, opens, closes, "reference")
    if primary_registry != reference_registry or primary_hash != reference_hash:
        raise ValueError("Independent checkpoint registry differs")
    OUTPUT.mkdir(parents=True)
    primary_path = OUTPUT / "primary_case_tape_registry.parquet"; reference_path = OUTPUT / "reference_case_tape_registry.parquet"
    write_parquet_exclusive(primary_path, primary_registry); write_parquet_exclusive(reference_path, reference_registry)
    if sha256_file(primary_path) != sha256_file(reference_path):
        raise ValueError("Case registry Parquet differs")
    by_tf = {
        timeframe: {
            "cases": sum(row["timeframe"] == timeframe for row in primary_registry),
            "available_cases": sum(row["timeframe"] == timeframe and row["tape_status"] == "AVAILABLE" for row in primary_registry),
            "checkpoint_rows": sum(row["checkpoint_rows"] for row in primary_registry if row["timeframe"] == timeframe),
        }
        for timeframe in ("M15", "H1", "H4")
    }
    unavailable = dict(sorted(Counter(row["unavailable_reason"] for row in primary_registry if row["tape_status"] != "AVAILABLE").items()))
    summary = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_PREOUTCOME_READINESS_1_0", "status": "PASS_PREOUTCOME_IDENTITY_AND_TIMESTAMP_READINESS",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "population": len(primary_registry),
        "available_cases": sum(row["tape_status"] == "AVAILABLE" for row in primary_registry),
        "checkpoint_rows": sum(row["checkpoint_rows"] for row in primary_registry), "checkpoint_identity_hash": primary_hash,
        "by_timeframe": by_tf, "unavailable_reasons": unavailable, "price_metadata": price_metadata,
        "outcomes_opened": False, "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    summary_path = OUTPUT / "readiness_summary.json"; write_json_exclusive(summary_path, summary)
    gc_payload = json.loads(GC_MANIFEST.read_text(encoding="utf-8"))
    if gc_payload.get("status") != "PASS_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION":
        raise ValueError("Existing GC technical certification changed")
    freeze = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_PREOUTCOME_FREEZE_1_0", "status": "FROZEN_READY_FOR_OUTCOME_BLIND_TAPE_FEATURES",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "controls": {"contract": record(CONTRACT), "protocol": record(PROTOCOL)},
        "predecessor_seals": {name: record(path) for name, path in predecessor_paths.items()}, "source_pairs": pair_records,
        "casebook_sources": {name: record(CASEBOOK / name) for name in ("price_bars.jsonl.gz", "fundamentals.jsonl.gz", "positioning.jsonl.gz")},
        "gc_technical_manifest": record(GC_MANIFEST),
        "artifacts": {"primary_registry": record(primary_path), "reference_registry": record(reference_path), "summary": record(summary_path)},
        "checkpoint_identity_hash": primary_hash, "checkpoint_rows": summary["checkpoint_rows"],
        "outcomes_opened_before_freeze": False, "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FREEZE, freeze)
    print(json.dumps({"status": summary["status"], "population": summary["population"], "available_cases": summary["available_cases"], "checkpoint_rows": summary["checkpoint_rows"], "by_timeframe": by_tf, "freeze": record(FREEZE)}, sort_keys=True))


if __name__ == "__main__":
    main()
