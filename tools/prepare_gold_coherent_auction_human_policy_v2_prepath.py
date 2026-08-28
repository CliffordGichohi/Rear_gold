"""Seal V2 semantic fidelity and outcome-free contextual classifications."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    canonical_hash,
    classify_predecision,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_human_policy_v2"
RESULT = OUTPUT / "prepath_classification.json"
SEAL = OUTPUT / "prepath_classification_seal.json"
FREEZE = ROOT / "research_manifests/gold_coherent_auction_human_policy_v2_freeze.json"
SYNTHETIC = OUTPUT / "synthetic_certification.json"
SYNTHETIC_SEAL = OUTPUT / "synthetic_certification_seal.json"
COMPARISON = ROOT / "research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json"
ORIGINAL_PRIMARY = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams/primary"
RECOVERY_PRIMARY = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams_recovery_a/primary"
RECOVERY_REFERENCE = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams_recovery_a/reference"
MODULE = ROOT / "backend/src/gold_intel/analytics/coherent_auction_human_policy_v2.py"

ANNOTATION_FIELDS = (
    "higher_timeframe_context",
    "preexisting_location",
    "m15_transition",
    "session_liquidity_context",
    "invalidation_condition",
    "target_logic",
    "thesis",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def primary_path(alias: str) -> Path:
    original = ORIGINAL_PRIMARY / f"{alias}.json.gz"
    return original if original.exists() else RECOVERY_PRIMARY / f"{alias}.json.gz"


def decision_input(human: dict[str, Any]) -> dict[str, Any]:
    annotation = human.get("annotation") or {}
    return {
        "direction": human["action"],
        "submitted_at": human["submitted_at"],
        "fill_at": human["fill_at"],
        "fill_price": human["fill_price"],
        "sealed_stop": human["stop"],
        "sealed_target": human["target"],
        "quantity_ounces": human["quantity_ounces"],
        "estimated_base_cost_usd": human["estimated_base_cost_usd"],
        "annotation": {field: annotation.get(field) for field in ANNOTATION_FIELDS},
    }


def main() -> None:
    if RESULT.exists() or SEAL.exists():
        raise FileExistsError("V2 prepath classification is already sealed")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha256(ROOT / freeze["contract_path"]) != freeze["contract_sha256"]:
        raise RuntimeError("V2 contract hash mismatch")
    if sha256(MODULE) != freeze["implementation_sha256"]:
        raise RuntimeError("V2 implementation hash mismatch")
    synthetic = json.loads(SYNTHETIC.read_text(encoding="utf-8"))
    synthetic_seal = json.loads(SYNTHETIC_SEAL.read_text(encoding="utf-8"))
    if sha256(SYNTHETIC) != synthetic_seal["result_sha256"]:
        raise RuntimeError("Synthetic certification seal mismatch")
    if synthetic["status"] != "PASS_SYNTHETIC_CLASSIFIER_AND_LIFECYCLE":
        raise RuntimeError("Synthetic certification did not pass")

    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    records = [record for record in comparison["cases"] if record["human"]["is_trade"]]
    if len(records) != 16:
        raise RuntimeError(f"Expected 16 sealed human trades, found {len(records)}")

    cases: list[dict[str, Any]] = []
    for record in records:
        alias = record["case_alias"]
        inputs = decision_input(record["human"])
        primary_source = primary_path(alias)
        reference_source = RECOVERY_REFERENCE / f"{alias}.json.gz"
        if not primary_source.exists() or not reference_source.exists():
            raise FileNotFoundError(alias)
        primary_stream = load_gzip(primary_source)
        reference_stream = load_gzip(reference_source)
        primary = classify_predecision(decision=inputs, stream=primary_stream)
        reference = classify_predecision(decision=inputs, stream=reference_stream)
        if canonical_hash(primary) != canonical_hash(reference):
            raise RuntimeError(f"Primary/reference classification mismatch for {alias}")
        cases.append(
            {
                "case_alias": alias,
                "submitted_at": inputs["submitted_at"],
                "fill_at": inputs["fill_at"],
                "primary_source": str(primary_source.relative_to(ROOT)).replace("\\", "/"),
                "primary_source_sha256": sha256(primary_source),
                "reference_source": str(reference_source.relative_to(ROOT)).replace("\\", "/"),
                "reference_source_sha256": sha256(reference_source),
                "whitelisted_input": inputs,
                "classification": primary,
                "primary_reference_checksum": canonical_hash(primary),
            }
        )

    fidelity_count = sum(item["classification"]["human_intent"]["detected"] for item in cases)
    if fidelity_count != 16:
        raise RuntimeError(f"Semantic-fidelity gate failed: {fidelity_count}/16")
    payload: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_HUMAN_POLICY_V2_PREPATH_1_0",
        "status": "PASS_V2_SEMANTIC_FIDELITY_AND_CLASSIFICATION_REPRODUCTION",
        "evidence_status": "EXPOSED_CALIBRATION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": sha256(FREEZE),
        "module_sha256": sha256(MODULE),
        "synthetic_certification_sha256": sha256(SYNTHETIC),
        "population": len(cases),
        "semantic_fidelity": fidelity_count,
        "admitted": sum(item["classification"]["admitted"] for item in cases),
        "rejected": sum(not item["classification"]["admitted"] for item in cases),
        "cases": cases,
        "classifier_input_fields": [
            "direction",
            "submitted_at",
            "fill_at",
            "fill_price",
            "sealed_stop",
            "sealed_target",
            "quantity_ounces",
            "estimated_base_cost_usd",
            *[f"annotation.{field}" for field in ANNOTATION_FIELDS],
        ],
        "outcome_fields_passed_to_classifier": [],
        "post_fill_paths_simulated": 0,
        "fresh_50_case_block": "LOCKED_UNOPENED",
        "calendar_2025": "LOCKED_UNOPENED",
        "calendar_2026": "LOCKED_UNOPENED",
    }
    payload["payload_sha256"] = canonical_hash(payload)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal = {
        "status": payload["status"],
        "result_path": str(RESULT.relative_to(ROOT)).replace("\\", "/"),
        "result_sha256": sha256(RESULT),
        "payload_sha256": payload["payload_sha256"],
        "semantic_fidelity": fidelity_count,
        "population": payload["population"],
        "admitted": payload["admitted"],
        "rejected": payload["rejected"],
        "module_sha256": payload["module_sha256"],
    }
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(seal, sort_keys=True))


if __name__ == "__main__":
    main()
