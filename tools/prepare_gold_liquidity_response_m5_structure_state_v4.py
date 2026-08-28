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
    / "gold_liquidity_response_m5_structure_state_edge_v4_preoutcome_freeze.json"
)
FILES = {
    "contract": ROOT / "GOLD_LIQUIDITY_RESPONSE_M5_STRUCTURE_STATE_EDGE_CONTRACT_V4.md",
    "protocol": ROOT
    / "research_manifests"
    / "gold_liquidity_response_m5_structure_state_edge_v4_protocol.json",
    "diagnostic_seal": ROOT
    / "research_artifacts"
    / "gold_liquidity_shift_predecision_trigger_diagnostic_v1"
    / "seal.json",
    "diagnostic_result": ROOT
    / "research_artifacts"
    / "gold_liquidity_shift_predecision_trigger_diagnostic_v1"
    / "diagnostic.json",
    "diagnostic_rows": ROOT
    / "research_artifacts"
    / "gold_liquidity_shift_predecision_trigger_diagnostic_v1"
    / "predecision_rows.csv",
    "v3_final_seal": ROOT
    / "research_artifacts"
    / "gold_persistent_liquidity_shift_auction_state_v3"
    / "final_seal.json",
    "casebook_price": ROOT
    / "research_artifacts"
    / "gold_casebook_v01"
    / "price_bars.jsonl.gz",
    "case_matrix": ROOT
    / "research_artifacts"
    / "gold_session_behaviour_v3_case_matrix_v01"
    / "cases.jsonl.gz",
    "fundamentals": ROOT
    / "research_artifacts"
    / "gold_casebook_v01"
    / "fundamentals.jsonl.gz",
    "human_visible_ledger": ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "ledgers"
    / "matched_human_visible_ledger.jsonl",
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
    diagnostic = json.loads(FILES["diagnostic_result"].read_text(encoding="utf-8"))
    summary = diagnostic["summary"]
    expected = {
        "trades": 16,
        "active_v3_state_at_trade": 1,
        "corrected_v3_entry_at_trade": 0,
    }
    if any(summary.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Outcome-blind diagnostic changed")
    payload = {
        "version": "GOLD_LIQUIDITY_RESPONSE_M5_STRUCTURE_STATE_EDGE_V4_PREOUTCOME_FREEZE_1_0",
        "status": "SEALED_BEFORE_V4_SEMANTIC_AND_DEVELOPMENT_OUTCOME_ACCESS",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "files": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for name, path in FILES.items()
        },
        "matched_outcomes_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    descriptor = os.open(FREEZE, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": payload["status"], "files": len(payload["files"])}, indent=2))


if __name__ == "__main__":
    main()
