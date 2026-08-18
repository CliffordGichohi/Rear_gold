from __future__ import annotations

import bisect
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from prepare_gold_point_in_time_auction_state_v1 import ROOT, ARTIFACTS, MANIFESTS, parse_ns, record as file_record, timestamp_registry


READINESS = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_preoutcome" / "primary_case_tape_registry.parquet"
OUTPUT = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape" / "setup_baseline_metadata_audit.json"
SEAL = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_setup_baseline_metadata_audit_seal.json"
SIGNAL = {"M15": "1m", "H1": "5m", "H4": "15m"}
PARENT = {"M15": "15m", "H1": "1h", "H4": "4h"}


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True); raise


def exists(values: np.ndarray, timestamp: int, implementation: str) -> bool:
    index = int(np.searchsorted(values, timestamp, side="left")) if implementation == "primary" else bisect.bisect_left(values, timestamp)
    return index < len(values) and int(values[index]) == timestamp


def calculate(rows: list[dict[str, Any]], closes: dict[str, np.ndarray], implementation: str) -> dict[str, Any]:
    totals = Counter(); by_timeframe: dict[str, Counter[str]] = {name: Counter() for name in ("M15", "H1", "H4")}; identity = hashlib.sha256(); exceptions: list[dict[str, Any]] = []
    for row in rows:
        known = parse_ns(str(row["known_at_utc"])); timeframe = str(row["timeframe"])
        signal_exact = exists(closes[SIGNAL[timeframe]], known, implementation); parent_exact = exists(closes[PARENT[timeframe]], known, implementation)
        first_exact = row["first_checkpoint_at_utc"] == row["known_at_utc"] if row["tape_status"] == "AVAILABLE" else False
        labels = {
            "signal_close_exact": signal_exact, "parent_close_exact": parent_exact, "first_actionable_equals_known": first_exact,
            "signal_only": signal_exact and not parent_exact, "parent_only": parent_exact and not signal_exact,
            "neither": not signal_exact and not parent_exact,
        }
        for label, value in labels.items():
            totals[f"{label}|{value}"] += 1; by_timeframe[timeframe][f"{label}|{value}"] += 1
        identity.update(json.dumps([row["pullback_id"], known, signal_exact, parent_exact, first_exact], separators=(",", ":")).encode()); identity.update(b"\n")
        if not signal_exact or not parent_exact or not first_exact:
            exceptions.append({"pullback_id": row["pullback_id"], "timeframe": timeframe, "known_at_utc": row["known_at_utc"], "signal_close_exact": signal_exact, "parent_close_exact": parent_exact, "first_actionable_equals_known": first_exact})
    return {
        "implementation": implementation, "rows": len(rows), "counts": dict(sorted(totals.items())),
        "by_timeframe": {key: dict(sorted(value.items())) for key, value in by_timeframe.items()},
        "classification_hash": identity.hexdigest(), "exceptions": exceptions,
    }


def main() -> None:
    if OUTPUT.exists() or SEAL.exists(): raise FileExistsError(OUTPUT if OUTPUT.exists() else SEAL)
    rows = pq.read_table(READINESS).to_pylist(); _, closes, price_metadata = timestamp_registry()
    primary = calculate(rows, closes, "primary"); reference = calculate(rows, closes, "reference")
    comparable = ("rows", "counts", "by_timeframe", "classification_hash", "exceptions")
    differences = [key for key in comparable if primary[key] != reference[key]]
    signal_all_available = primary["counts"].get("signal_close_exact|True", 0) == 8653
    status = "PASS_REPRODUCED_BASELINE_METADATA_AUDIT" if not differences else "FAIL_BASELINE_METADATA_AUDIT_REPRODUCTION"
    recommendation = "USE_EXACT_SIGNAL_FRAME_CLOSE_AT_KNOWN_AT_WITHOUT_REQUIRING_FIRST_ACTIONABLE_CHECKPOINT_EQUALITY" if signal_all_available else "NO_UNIVERSAL_SIGNAL_BASELINE_AVAILABLE"
    result = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_SETUP_BASELINE_METADATA_AUDIT_1_0", "status": status, "audited_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "primary": primary, "reference": reference, "differences": differences, "signal_baseline_available_for_all_cases": signal_all_available,
        "recommendation": recommendation, "price_metadata": price_metadata, "market_values_reported": False, "development_outcomes_accessed": False,
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(OUTPUT, result)
    write_json_exclusive(SEAL, {
        "version": "GOLD_PIT_AUCTION_STATE_V1_SETUP_BASELINE_METADATA_AUDIT_SEAL_1_0", "status": status, "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "audit": file_record(OUTPUT), "source_registry": file_record(READINESS), "classification_hash": primary["classification_hash"],
        "recommendation": recommendation, "development_outcomes_accessed": False, "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    })
    print(json.dumps({"status": status, "counts": primary["counts"], "signal_all": signal_all_available, "recommendation": recommendation}, sort_keys=True))
    if status.startswith("FAIL"): raise SystemExit(2)


if __name__ == "__main__":
    main()
