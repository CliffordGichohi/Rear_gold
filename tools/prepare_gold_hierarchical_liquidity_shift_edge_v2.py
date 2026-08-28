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
OUTPUT = ARTIFACTS / "gold_hierarchical_liquidity_shift_edge_v2"
FREEZE = MANIFESTS / "gold_hierarchical_liquidity_shift_edge_v2_preoutcome_freeze.json"

CONTROLS = {
    "contract": ROOT / "GOLD_HIERARCHICAL_LIQUIDITY_SHIFT_EDGE_DISCOVERY_CONTRACT_V2.md",
    "protocol": MANIFESTS / "gold_hierarchical_liquidity_shift_edge_v2_protocol.json",
    "test_registry": MANIFESTS / "gold_hierarchical_liquidity_shift_edge_v2_test_registry.json",
}

SOURCES = {
    "reference_book": ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf",
    "casebook_manifest": ARTIFACTS / "gold_casebook_v01" / "manifest.json",
    "casebook_price": ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz",
    "case_matrix_manifest": ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01" / "manifest.json",
    "case_matrix_cases": ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01" / "cases.jsonl.gz",
    "matched_population_public": ARTIFACTS / "gold_matched_human_replay_v1" / "population_registry.public.json",
    "matched_population_private": ARTIFACTS / "gold_matched_human_replay_v1" / "population_registry.private.json",
    "matched_human_visible_ledger": ARTIFACTS / "gold_matched_human_replay_v1" / "ledgers" / "matched_human_visible_ledger.jsonl",
    "matched_stream_certification": ARTIFACTS / "gold_matched_human_replay_v1" / "stream_materialization_certification.json",
    "v1_result_seal": ARTIFACTS / "gold_auction_automation_matched_replay_verification_v1" / "final_seal.json",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


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
    if FREEZE.exists() or (OUTPUT.exists() and any(OUTPUT.iterdir())):
        raise FileExistsError("V2 freeze/output already exists; refusing to overwrite sealed state")
    missing = [path.relative_to(ROOT).as_posix() for path in (*CONTROLS.values(), *SOURCES.values()) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing required bindings: {missing}")

    protocol = json.loads(CONTROLS["protocol"].read_text(encoding="utf-8"))
    registry = json.loads(CONTROLS["test_registry"].read_text(encoding="utf-8"))
    casebook = json.loads(SOURCES["casebook_manifest"].read_text(encoding="utf-8"))
    if protocol.get("ruleset") != "gold-hierarchical-liquidity-shift-v2":
        raise ValueError("Ruleset identity mismatch")
    if len(registry.get("ordered_cells", [])) != 8:
        raise ValueError("The frozen registry must contain exactly eight cells")
    if protocol["partitions"]["locked"] != [2025, 2026]:
        raise ValueError("Forward lock changed")
    if protocol["candidate_limit"] != 2 or protocol["live_order_permitted"] is not False:
        raise ValueError("Candidate or live-order policy changed")

    price_record = next(item for item in casebook["artifacts"] if item["name"] == "price_bars.jsonl.gz")
    actual_price_hash = sha256_file(SOURCES["casebook_price"])
    if actual_price_hash != price_record["sha256"]:
        raise ValueError("Casebook price source no longer matches its sealed manifest")
    if casebook["contract"]["case_end_exclusive"] != "2025-01-01T00:00:00+00:00":
        raise ValueError("Development price boundary changed")
    if casebook["contract"]["holdout_loaded"] is not False:
        raise ValueError("Casebook claims that its holdout has been loaded")

    controls = {name: file_record(path) for name, path in CONTROLS.items()}
    sources = {name: file_record(path) for name, path in SOURCES.items()}
    freeze = {
        "version": "GOLD_HIERARCHICAL_LIQUIDITY_SHIFT_EDGE_V2_PREOUTCOME_FREEZE_1_0",
        "status": "SEALED_BEFORE_SEMANTIC_CALIBRATION_AND_DEVELOPMENT_OUTCOME_ACCESS",
        "sealed_at_utc": utc_now(),
        "controls": controls,
        "sources": sources,
        "rules_hash": canonical_hash(
            {
                "contract": controls["contract"]["sha256"],
                "protocol": controls["protocol"]["sha256"],
                "test_registry": controls["test_registry"]["sha256"],
            }
        ),
        "declared_price_rows": price_record["record_count"],
        "declared_price_sha256": price_record["sha256"],
        "matched_outcome_ledger_bound_or_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition_permitted": False,
        "live_order_permitted": False,
        "prior_v1_preserved": True,
    }
    write_json_exclusive(FREEZE, freeze)

    OUTPUT.mkdir(parents=True, exist_ok=False)
    state = {
        "version": "GOLD_HIERARCHICAL_LIQUIDITY_SHIFT_EDGE_V2_STATE_1_0",
        "status": "PREOUTCOME_FROZEN_READY_FOR_IMPLEMENTATION",
        "updated_at_utc": utc_now(),
        "preoutcome_freeze": file_record(FREEZE),
        "semantic_calibration_complete": False,
        "development_outcomes_opened": False,
        "development_economics_complete": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "prospective_candidate": None,
    }
    write_json_exclusive(OUTPUT / "state.json", state)
    print(json.dumps({"status": freeze["status"], "rules_hash": freeze["rules_hash"]}, indent=2))


if __name__ == "__main__":
    main()
