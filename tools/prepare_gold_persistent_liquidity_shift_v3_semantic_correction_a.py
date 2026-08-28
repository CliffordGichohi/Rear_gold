from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FREEZE = (
    ROOT
    / "research_manifests"
    / "gold_persistent_liquidity_shift_v3_semantic_engineering_correction_a_freeze.json"
)
CONTROLS = {
    "amendment": ROOT
    / "GOLD_PERSISTENT_LIQUIDITY_SHIFT_V3_SEMANTIC_ENGINEERING_CORRECTION_A.md",
    "manifest": ROOT
    / "research_manifests"
    / "gold_persistent_liquidity_shift_v3_semantic_engineering_correction_a.json",
    "v3_preoutcome_freeze": ROOT
    / "research_manifests"
    / "gold_persistent_liquidity_shift_auction_state_v3_preoutcome_freeze.json",
    "v3_implementation": ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "liquidity_shift_v3.py",
    "invalid_result": ROOT
    / "research_artifacts"
    / "gold_persistent_liquidity_shift_auction_state_v3"
    / "semantic_calibration.json",
    "invalid_rows": ROOT
    / "research_artifacts"
    / "gold_persistent_liquidity_shift_auction_state_v3"
    / "semantic_rows.csv",
    "invalid_seal": ROOT
    / "research_artifacts"
    / "gold_persistent_liquidity_shift_auction_state_v3"
    / "semantic_seal.json",
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


def main() -> None:
    if FREEZE.exists():
        raise FileExistsError(FREEZE)
    missing = [name for name, path in CONTROLS.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    invalid = json.loads(CONTROLS["invalid_result"].read_text(encoding="utf-8"))
    if invalid["metrics"]["semantic_verdict"] != "PASS_SEMANTIC_REPRESENTATION":
        raise RuntimeError("Invalid engineering run was not preserved")
    if invalid["metrics"]["triggered_or_pending_entry_matches"] != 16:
        raise RuntimeError("Invalid engineering-run support changed")
    manifest = json.loads(CONTROLS["manifest"].read_text(encoding="utf-8"))
    if manifest["single_change"] != {
        "field": "TRIGGERED_INTENT_AVAILABILITY",
        "before": "triggered_at <= decision_at",
        "after": "triggered_at <= decision_at < expires_at",
    }:
        raise RuntimeError("Correction scope changed")
    payload = {
        "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_V3_SEMANTIC_ENGINEERING_CORRECTION_A_FREEZE_1_0",
        "status": "SEALED_BEFORE_CORRECTED_SEMANTIC_REPRODUCTION",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "files": {name: record(path) for name, path in CONTROLS.items()},
        "single_change_only": True,
        "market_outcomes_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(FREEZE, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": payload["status"], "files": len(payload["files"])}, indent=2))


if __name__ == "__main__":
    main()
