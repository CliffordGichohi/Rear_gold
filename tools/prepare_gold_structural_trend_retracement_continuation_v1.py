from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_structural_trend_retracement_continuation_v1_v01"
FREEZE = MANIFESTS / "gold_structural_trend_retracement_continuation_v1_design_freeze.json"

CONTROLS = {
    "contract": ROOT / "GOLD_STRUCTURAL_TREND_RETRACEMENT_CONTINUATION_EDGE_CONTRACT_V1.md",
    "protocol": MANIFESTS / "gold_structural_trend_retracement_continuation_v1_protocol.json",
    "test_registry": MANIFESTS / "gold_structural_trend_retracement_continuation_v1_test_registry.json",
}
SOURCES = {
    "reference_book": ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf",
    "casebook_price": ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz",
    "casebook_manifest": ARTIFACTS / "gold_casebook_v01/manifest.json",
    "case_matrix": ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz",
    "case_matrix_manifest": ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01/manifest.json",
    "gc_primary_events": ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/primary_events.parquet",
    "gc_reference_events": ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/reference_events.parquet",
    "gc_final_manifest": ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/manifest.json",
    "prior_branch_final_seal": ARTIFACTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_v02/final_seal.json",
    "prior_branch_results": ARTIFACTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_v02/development_results.json",
}
PINNED_SOURCE_HASHES = {
    "reference_book": "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a",
    "casebook_price": "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
    "casebook_manifest": "38e4aadc43917a5b91d04d47ab18542d7514fe257cc030f959d34080865314d6",
    "case_matrix": "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9",
    "case_matrix_manifest": "dddbe125d11afef2094b7843f5521b7bbfcc95178e3fa376b60af8bdd2efc3b5",
    "gc_primary_events": "9557731bbc45d985d06227b3b15451f69e31f069697ab7cc5fae66293965a87b",
    "gc_reference_events": "9557731bbc45d985d06227b3b15451f69e31f069697ab7cc5fae66293965a87b"
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def source_record(name: str, path: Path) -> dict[str, Any]:
    if name in PINNED_SOURCE_HASHES:
        return {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": PINNED_SOURCE_HASHES[name],
            "verification": "INHERITED_FROM_EXISTING_SEALED_PREDECESSOR"
        }
    return record(path)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if FREEZE.exists() or OUTPUT.exists():
        raise FileExistsError("STRC V1 design is already initialized")
    missing = [str(path) for path in (*CONTROLS.values(), *SOURCES.values()) if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    prior = json.loads(SOURCES["prior_branch_final_seal"].read_text(encoding="utf-8"))
    if prior.get("status") != "REJECT_NO_ECONOMICALLY_TRADABLE_CANDIDATE":
        raise ValueError("Prior rejection is not preserved")
    if prior.get("forward_values_accessed") is not False:
        raise ValueError("Unexpected prior forward access")
    if PINNED_SOURCE_HASHES["gc_primary_events"] != PINNED_SOURCE_HASHES["gc_reference_events"]:
        raise ValueError("GC source reproductions no longer match")
    controls = {name: record(path) for name, path in CONTROLS.items()}
    sources = {name: source_record(name, path) for name, path in SOURCES.items()}
    preflight = {
        "version": "GOLD_STRC_V1_PREFLIGHT_1_0", "status": "PASS_DESIGN_AND_SOURCE_READINESS",
        "completed_at_utc": utc_now(), "controls": controls, "sources": sources,
        "development_outcomes_accessed": False, "forward_values_accessed": False,
        "paid_acquisition_usd": 0.0, "prior_rejection_preserved": True,
    }
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(OUTPUT / "preflight.json", preflight)
    freeze = {
        "version": "GOLD_STRC_V1_DESIGN_FREEZE_1_0",
        "status": "SEALED_BEFORE_ANY_BRANCH_OUTCOME_ACCESS", "sealed_at_utc": utc_now(),
        "controls": controls, "sources": sources, "preflight": record(OUTPUT / "preflight.json"),
        "rules_hash": canonical_hash({"controls": controls, "sources": sources}),
        "development_outcomes_accessed": False, "forward_values_accessed": False,
        "paid_acquisition_authorized": False,
    }
    write_json_exclusive(FREEZE, freeze)
    print(json.dumps({"status": freeze["status"], "rules_hash": freeze["rules_hash"], "source_count": len(sources)}, indent=2))


if __name__ == "__main__":
    main()
