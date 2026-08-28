from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_artifacts" / "gold_persistent_liquidity_shift_auction_state_v3"
FINAL_STATE = OUTPUT / "final_state.json"
FINAL_SEAL = OUTPUT / "final_seal.json"
FILES = {
    "report": ROOT / "GOLD_PERSISTENT_LIQUIDITY_SHIFT_AUCTION_STATE_V3_REPORT.md",
    "preoutcome_freeze": ROOT
    / "research_manifests"
    / "gold_persistent_liquidity_shift_auction_state_v3_preoutcome_freeze.json",
    "invalid_result": OUTPUT / "semantic_calibration.json",
    "invalid_rows": OUTPUT / "semantic_rows.csv",
    "invalid_seal": OUTPUT / "semantic_seal.json",
    "correction_freeze": ROOT
    / "research_manifests"
    / "gold_persistent_liquidity_shift_v3_semantic_engineering_correction_a_freeze.json",
    "corrected_result": OUTPUT / "semantic_calibration_correction_a.json",
    "corrected_rows": OUTPUT / "semantic_rows_correction_a.csv",
    "corrected_seal": OUTPUT / "semantic_seal_correction_a.json",
    "implementation": ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "liquidity_shift_v3.py",
    "unit_tests": ROOT / "backend" / "tests" / "unit" / "test_liquidity_shift_v3.py",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    if FINAL_STATE.exists() or FINAL_SEAL.exists():
        raise FileExistsError("V3 final artifacts already exist")
    missing = [name for name, path in FILES.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    invalid = json.loads(FILES["invalid_result"].read_text(encoding="utf-8"))
    corrected = json.loads(FILES["corrected_result"].read_text(encoding="utf-8"))
    if invalid["metrics"]["triggered_or_pending_entry_matches"] != 16:
        raise RuntimeError("Invalid result was not preserved")
    if corrected["metrics"]["semantic_verdict"] != "FAIL_SEMANTIC_REPRESENTATION":
        raise RuntimeError("Corrected semantic failure was not preserved")
    if corrected["metrics"]["triggered_or_pending_entry_matches"] != 0:
        raise RuntimeError("Corrected support changed")
    files = {name: record(path) for name, path in FILES.items()}
    state = {
        "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_AUCTION_STATE_V3_FINAL_STATE_1_0",
        "status": "TERMINATED_FAIL_SEMANTIC_REPRESENTATION",
        "finalized_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "invalid_engineering_run_preserved": True,
        "corrected_entry_matches": 0,
        "required_entry_matches": 7,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "files": files,
    }
    exclusive_json(FINAL_STATE, state)
    seal = {
        "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_AUCTION_STATE_V3_FINAL_SEAL_1_0",
        "verdict": state["status"],
        "final_state": record(FINAL_STATE),
    }
    exclusive_json(FINAL_SEAL, seal)
    print(json.dumps({"status": state["status"], "files": len(files)}, indent=2))


if __name__ == "__main__":
    main()
