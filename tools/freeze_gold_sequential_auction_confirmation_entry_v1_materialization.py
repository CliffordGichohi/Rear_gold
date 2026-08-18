from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
PROTOCOL = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_protocol.json"
PRE_FREEZE = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_pre_outcome_freeze.json"
IMPLEMENTATION = ROOT / "tools" / "materialize_gold_sequential_auction_confirmation_entry_v1.py"
OUTPUT = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_materialization_implementation_freeze.json"


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
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    pre_freeze = json.loads(PRE_FREEZE.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_DELAYED_ENTRY_MATERIALIZATION_OR_OUTCOMES":
        raise ValueError("Protocol changed")
    if pre_freeze.get("status") != "FROZEN_READY_FOR_OUTCOME_BLIND_CONFIRMATION_MATERIALIZATION":
        raise ValueError("Pre-outcome freeze changed")
    completed = subprocess.run(
        [sys.executable, str(IMPLEMENTATION), "--self-test"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    proof = json.loads(completed.stdout.strip())
    if proof.get("status") != "PASS_SYNTHETIC_MATERIALIZER_PROOF":
        raise ValueError("Synthetic proof failed")
    payload = {
        "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_MATERIALIZATION_IMPLEMENTATION_FREEZE_1_0",
        "status": "FROZEN_BEFORE_DEVELOPMENT_SEQUENCE_VALUES",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "controls": {"protocol": record(PROTOCOL), "pre_outcome_freeze": record(PRE_FREEZE)},
        "implementation": record(IMPLEMENTATION),
        "synthetic_proof": proof,
        "signal_bar_semantics": {
            "aggregation": "UTC_EPOCH_ALIGNED_EXACT_CONSTITUENT_M1_BARS",
            "atr14": "MEAN_TRUE_RANGE_OF_14_STRICTLY_PRECEDING_BARS_WITH_15_BAR_CONTIGUOUS_PREHISTORY",
            "search_origin": "FIRST_ALIGNED_SIGNAL_BAR_OPEN_GTE_ORIGINAL_ENTRY",
            "missing_expected_bar": "UNAVAILABLE_NO_COMPRESSION_ACROSS_GAP",
            "decision": "COMPLETED_BAR_ONLY_ENTRY_AT_NEXT_COMPLETE_SIGNAL_BAR_OPEN",
        },
        "transition_semantics": {
            "selection": "FIRST_QUALIFYING_STATE_THEN_FIRST_QUALIFYING_NEXT_STATE_WITHIN_FROZEN_WINDOW",
            "family_1": "FIRST_TWO_CONSECUTIVE_ACCEPTED_CLOSES_THEN_FIRST_VALID_RETEST",
            "family_2": "FIRST_SWEEP_RECLAIM_THEN_FIRST_VALID_DISPLACEMENT_THEN_FIRST_VALID_RETEST",
            "family_3": "FIRST_VALID_DISPLACEMENT_THEN_FIRST_VALID_RETEST",
            "micro_break": "STRICT_CLOSE_THROUGH_EXTREME_OF_EXACT_THREE_PRECEDING_COMPLETE_SIGNAL_BARS",
        },
        "pre_entry_path": {
            "interval": "ORIGINAL_ENTRY_INCLUSIVE_DELAYED_ENTRY_EXCLUSIVE",
            "requires_contiguous_m1": True,
            "target_touch": "NO_TRADE",
            "original_stop_touch": "PERMITTED_WITHOUT_POSITION",
        },
        "independence": {
            "primary_aggregation": "NUMPY_GROUP_AND_SEARCHSORTED",
            "reference_aggregation": "TIMESTAMP_MAP_AND_PYTHON_ITERATION",
            "primary_sequence_lookup": "NUMPY_SEARCHSORTED",
            "reference_sequence_lookup": "EXACT_TIMESTAMP_DICTIONARY",
            "required": "LOGICAL_EXACTNESS_DIAGNOSTIC_EXACTNESS_AND_BYTE_IDENTICAL_PARQUET",
        },
        "expected_output_rows": 22_193 * 3 * 2,
        "outcomes_opened_before_freeze": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_exclusive(OUTPUT, payload)
    print(json.dumps({"status": payload["status"], "implementation": payload["implementation"], "synthetic_proof": proof}, sort_keys=True))


if __name__ == "__main__":
    main()
