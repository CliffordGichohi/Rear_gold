from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE = (
    ROOT
    / "research_manifests"
    / "gold_liquidity_shift_predecision_trigger_diagnostic_v1_freeze.json"
)
FILES = {
    "protocol": ROOT / "GOLD_LIQUIDITY_SHIFT_PREDECISION_TRIGGER_DIAGNOSTIC_V1.md",
    "registry": ROOT
    / "research_manifests"
    / "gold_liquidity_shift_predecision_trigger_diagnostic_v1.json",
    "v3_final_seal": ROOT
    / "research_artifacts"
    / "gold_persistent_liquidity_shift_auction_state_v3"
    / "final_seal.json",
    "human_visible_ledger": ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "ledgers"
    / "matched_human_visible_ledger.jsonl",
    "v2_implementation": ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "liquidity_shift_v2.py",
    "v3_implementation": ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "liquidity_shift_v3.py",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    if FREEZE.exists():
        raise FileExistsError(FREEZE)
    missing = [name for name, path in FILES.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    payload = {
        "version": "GOLD_LIQUIDITY_SHIFT_PREDECISION_TRIGGER_DIAGNOSTIC_V1_FREEZE_1_0",
        "status": "SEALED_BEFORE_PREDECISION_VALUE_ACCESS",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "files": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for name, path in FILES.items()
        },
        "postdecision_market_values_opened": False,
        "outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    descriptor = os.open(FREEZE, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": payload["status"], "files": len(payload["files"])}, indent=2))


if __name__ == "__main__":
    main()
