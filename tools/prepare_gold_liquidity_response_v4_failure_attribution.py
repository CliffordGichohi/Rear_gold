from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "research_manifests/gold_liquidity_response_v4_failure_attribution_freeze.json"
FILES = {
    "protocol": ROOT / "GOLD_LIQUIDITY_RESPONSE_V4_FAILURE_ATTRIBUTION_PROTOCOL.md",
    "registry": ROOT
    / "research_manifests/gold_liquidity_response_v4_failure_attribution_protocol.json",
    "v4_final_seal": ROOT
    / "research_artifacts/gold_liquidity_response_m5_structure_state_edge_v4/final_seal.json",
    "v4_rows": ROOT
    / "research_artifacts/gold_liquidity_response_m5_structure_state_edge_v4/semantic_rows.csv",
    "predecision_seal": ROOT
    / "research_artifacts/gold_liquidity_shift_predecision_trigger_diagnostic_v1/seal.json",
    "visible_ledger": ROOT
    / "research_artifacts/gold_matched_human_replay_v1/ledgers/matched_human_visible_ledger.jsonl",
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
        "version": "GOLD_LIQUIDITY_RESPONSE_V4_FAILURE_ATTRIBUTION_FREEZE_1_0",
        "status": "SEALED_BEFORE_VALUE_BLIND_FAILURE_ATTRIBUTION",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "files": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for name, path in FILES.items()
        },
        "outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    descriptor = os.open(FREEZE, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": payload["status"]}, indent=2))


if __name__ == "__main__":
    main()
