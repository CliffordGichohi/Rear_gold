from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_persistent_liquidity_shift_auction_state_v3"
FREEZE = MANIFESTS / "gold_persistent_liquidity_shift_auction_state_v3_preoutcome_freeze.json"

CONTROLS = {
    "contract": ROOT / "GOLD_PERSISTENT_LIQUIDITY_SHIFT_AUCTION_STATE_EDGE_CONTRACT_V3.md",
    "protocol": MANIFESTS / "gold_persistent_liquidity_shift_auction_state_v3_protocol.json",
    "test_registry": MANIFESTS / "gold_persistent_liquidity_shift_auction_state_v3_test_registry.json",
}

PREDECESSORS = {
    "v2_preoutcome_freeze": MANIFESTS / "gold_hierarchical_liquidity_shift_edge_v2_preoutcome_freeze.json",
    "v2_original_semantic_seal": ARTIFACTS / "gold_hierarchical_liquidity_shift_edge_v2" / "semantic_seal.json",
    "v2_amendment_a": MANIFESTS / "gold_hierarchical_liquidity_shift_edge_v2_amendment_a.json",
    "v2_amendment_a_semantic_result": ARTIFACTS / "gold_hierarchical_liquidity_shift_edge_v2" / "semantic_calibration_amendment_a.json",
    "v2_amendment_a_semantic_seal": ARTIFACTS / "gold_hierarchical_liquidity_shift_edge_v2" / "semantic_seal_amendment_a.json",
    "v2_implementation": ROOT / "backend" / "src" / "gold_intel" / "analytics" / "liquidity_shift_v2.py",
    "casebook_price": ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz",
    "case_matrix_cases": ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01" / "cases.jsonl.gz",
    "human_visible_ledger": ARTIFACTS / "gold_matched_human_replay_v1" / "ledgers" / "matched_human_visible_ledger.jsonl",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if FREEZE.exists() or OUTPUT.exists():
        raise FileExistsError("V3 freeze or output already exists")
    missing = [path.relative_to(ROOT).as_posix() for path in (*CONTROLS.values(), *PREDECESSORS.values()) if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    protocol = json.loads(CONTROLS["protocol"].read_text(encoding="utf-8"))
    registry = json.loads(CONTROLS["test_registry"].read_text(encoding="utf-8"))
    v2_result = json.loads(PREDECESSORS["v2_amendment_a_semantic_result"].read_text(encoding="utf-8"))
    if v2_result["metrics"]["semantic_verdict"] != "FAIL_SEMANTIC_REPRESENTATION":
        raise ValueError("V2 Amendment A failure was not preserved")
    if v2_result["metrics"]["triggered_or_pending_entry_matches"] != 6:
        raise ValueError("V2 Amendment A support changed")
    if protocol["semantic"] != {
        "human_trades": 16,
        "minimum_matches": 7,
        "minimum_rate": 0.4,
        "attempts": 1,
        "outcomes_prohibited": True,
    }:
        raise ValueError("V3 semantic gate changed")
    if len(registry["ordered_cells"]) != 8:
        raise ValueError("V3 registry cardinality changed")
    controls = {name: file_record(path) for name, path in CONTROLS.items()}
    predecessors = {name: file_record(path) for name, path in PREDECESSORS.items()}
    freeze = {
        "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_AUCTION_STATE_V3_PREOUTCOME_FREEZE_1_0",
        "status": "SEALED_BEFORE_V3_SEMANTIC_CALIBRATION",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "controls": controls,
        "predecessors": predecessors,
        "rules_hash": canonical_hash({name: item["sha256"] for name, item in controls.items()}),
        "v2_failure_preserved": True,
        "matched_outcome_ledger_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition_permitted": False,
        "live_order_permitted": False,
    }
    write_json_exclusive(FREEZE, freeze)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        OUTPUT / "state.json",
        {
            "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_AUCTION_STATE_V3_STATE_1_0",
            "status": "PREOUTCOME_FROZEN_READY_FOR_IMPLEMENTATION",
            "preoutcome_freeze": file_record(FREEZE),
            "semantic_complete": False,
            "development_outcomes_opened": False,
            "calendar_2025_opened": False,
            "calendar_2026_opened": False,
        },
    )
    print(json.dumps({"status": freeze["status"], "rules_hash": freeze["rules_hash"]}, indent=2))


if __name__ == "__main__":
    main()
