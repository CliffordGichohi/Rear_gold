"""Seal matched-case classifications before any post-fill path simulation."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    classify_predecision,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_complete_correction_v1"
RESULT = OUTPUT / "prepath_classification.json"
SEAL = OUTPUT / "prepath_classification_seal.json"
COMPARISON = ROOT / "research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json"
MODULE = ROOT / "backend/src/gold_intel/analytics/coherent_auction_correction_v1.py"
SYNTHETIC = OUTPUT / "synthetic_certification_seal.json"
SYNTHETIC_A = OUTPUT / "synthetic_certification_amendment_a_seal.json"
FINAL_FREEZE = ROOT / "research_manifests/gold_coherent_auction_complete_correction_rulebook_v1_final_freeze.json"
MAPPING = ROOT / "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_V1_IMPLEMENTATION_MAPPING.md"

ORIGINAL_PRIMARY = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams/primary"
RECOVERY_PRIMARY = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams_recovery_a/primary"
RECOVERY_REFERENCE = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams_recovery_a/reference"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def primary_path(alias: str) -> Path:
    original = ORIGINAL_PRIMARY / f"{alias}.json.gz"
    return original if original.exists() else RECOVERY_PRIMARY / f"{alias}.json.gz"


def decision_input(human: dict[str, Any]) -> dict[str, Any]:
    # Deliberately whitelist classifier inputs. No result/path diagnostic field
    # can cross this boundary.
    return {
        "direction": human["action"],
        "submitted_at": human["submitted_at"],
        "fill_at": human["fill_at"],
        "fill_price": human["fill_price"],
        "quantity_ounces": human["quantity_ounces"],
        "estimated_base_cost_usd": human["estimated_base_cost_usd"],
    }


def main() -> None:
    if RESULT.exists() or SEAL.exists():
        raise FileExistsError("Prepath classification already sealed")
    synthetic = json.loads(SYNTHETIC.read_text(encoding="utf-8"))
    synthetic_a = json.loads(SYNTHETIC_A.read_text(encoding="utf-8"))
    module_sha = sha256(MODULE)
    if synthetic["module_sha256"] != module_sha or synthetic_a["module_sha256"] != module_sha:
        raise RuntimeError("Implementation differs from synthetic-certified module")
    freeze = json.loads(FINAL_FREEZE.read_text(encoding="utf-8"))
    if sha256(ROOT / freeze["approved_document"]["path"]) != freeze["approved_document"]["sha256"]:
        raise RuntimeError("Approved rulebook hash mismatch")

    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    records = [record for record in comparison["cases"] if record["human"]["is_trade"]]
    if len(records) != 16:
        raise RuntimeError(f"Expected 16 sealed human trades, found {len(records)}")

    cases = []
    for record in records:
        alias = record["case_alias"]
        input_record = decision_input(record["human"])
        primary_source = primary_path(alias)
        reference_source = RECOVERY_REFERENCE / f"{alias}.json.gz"
        if not primary_source.exists() or not reference_source.exists():
            raise FileNotFoundError(alias)
        primary_stream = load_gzip(primary_source)
        reference_stream = load_gzip(reference_source)
        primary = classify_predecision(decision=input_record, stream=primary_stream)
        reference = classify_predecision(decision=input_record, stream=reference_stream)
        if canonical_hash(primary) != canonical_hash(reference):
            raise RuntimeError(
                f"Primary/reference classification mismatch for {alias}: "
                f"{canonical_hash(primary)} != {canonical_hash(reference)}"
            )
        cases.append(
            {
                "case_alias": alias,
                "submitted_at": input_record["submitted_at"],
                "fill_at": input_record["fill_at"],
                "primary_source": str(primary_source.relative_to(ROOT)).replace("\\", "/"),
                "primary_source_sha256": sha256(primary_source),
                "reference_source": str(reference_source.relative_to(ROOT)).replace("\\", "/"),
                "reference_source_sha256": sha256(reference_source),
                "whitelisted_input": input_record,
                "classification": primary,
                "primary_reference_checksum": canonical_hash(primary),
            }
        )

    payload: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_V1_PREPATH_CLASSIFICATION_1_0",
        "status": "PASS_PREPATH_CLASSIFICATION_REPRODUCTION",
        "evidence_status": "EXPOSED_MATCHED_CASE_ZERO_VALIDATION_CREDIT",
        "approved_rulebook_sha256": freeze["approved_document"]["sha256"],
        "implementation_mapping_sha256": sha256(MAPPING),
        "module_sha256": module_sha,
        "synthetic_certification_sha256": synthetic["certification_sha256"],
        "synthetic_amendment_a_sha256": synthetic_a["result_sha256"],
        "population": len(cases),
        "admitted": sum(item["classification"]["admitted"] for item in cases),
        "rejected": sum(not item["classification"]["admitted"] for item in cases),
        "cases": cases,
        "classifier_input_fields": sorted(decision_input(records[0]["human"])),
        "outcome_fields_passed_to_classifier": [],
        "post_fill_paths_simulated": 0,
        "fresh_cases_opened": 0,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    payload["payload_sha256"] = canonical_hash(payload)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal = {
        "status": payload["status"],
        "result_path": str(RESULT.relative_to(ROOT)).replace("\\", "/"),
        "result_sha256": sha256(RESULT),
        "payload_sha256": payload["payload_sha256"],
        "module_sha256": module_sha,
        "population": payload["population"],
        "admitted": payload["admitted"],
        "rejected": payload["rejected"],
    }
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(seal, sort_keys=True))


if __name__ == "__main__":
    main()

