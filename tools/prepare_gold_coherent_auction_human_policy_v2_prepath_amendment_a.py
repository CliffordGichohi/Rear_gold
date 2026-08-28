"""Rerun only V2 pre-path classification after semantic Amendment A."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    canonical_hash,
    classify_predecision,
)
from prepare_gold_coherent_auction_human_policy_v2_prepath import (  # noqa: E402
    ANNOTATION_FIELDS,
    COMPARISON,
    RECOVERY_REFERENCE,
    decision_input,
    load_gzip,
    primary_path,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_human_policy_v2"
RESULT = OUTPUT / "prepath_classification_amendment_a.json"
SEAL = OUTPUT / "prepath_classification_amendment_a_seal.json"
FREEZE = ROOT / "research_manifests/gold_coherent_auction_human_policy_v2_amendment_a_freeze.json"
SYNTHETIC = OUTPUT / "synthetic_certification_amendment_a.json"
SYNTHETIC_SEAL = OUTPUT / "synthetic_certification_amendment_a_seal.json"
MODULE = ROOT / "backend/src/gold_intel/analytics/coherent_auction_human_policy_v2.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if RESULT.exists() or SEAL.exists():
        raise FileExistsError("V2 Amendment A prepath already sealed")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha256(MODULE) != freeze["amended_implementation_sha256"]:
        raise RuntimeError("Amended implementation hash mismatch")
    if sha256(SYNTHETIC) != json.loads(SYNTHETIC_SEAL.read_text())["result_sha256"]:
        raise RuntimeError("Amendment A synthetic seal mismatch")
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    records = [row for row in comparison["cases"] if row["human"]["is_trade"]]
    cases: list[dict[str, Any]] = []
    for record in records:
        alias = record["case_alias"]
        inputs = decision_input(record["human"])
        primary_source = primary_path(alias)
        reference_source = RECOVERY_REFERENCE / f"{alias}.json.gz"
        primary = classify_predecision(
            decision=inputs, stream=load_gzip(primary_source)
        )
        reference = classify_predecision(
            decision=inputs, stream=load_gzip(reference_source)
        )
        if canonical_hash(primary) != canonical_hash(reference):
            raise RuntimeError(f"Amended primary/reference mismatch for {alias}")
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
    fidelity = sum(row["classification"]["human_intent"]["detected"] for row in cases)
    if fidelity != 16:
        raise RuntimeError(f"Amended fidelity gate failed: {fidelity}/16")
    payload: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_HUMAN_POLICY_V2_PREPATH_A_1_0",
        "status": "PASS_AMENDMENT_A_PREPATH_REPRODUCTION",
        "evidence_status": "EXPOSED_CALIBRATION_ZERO_VALIDATION_CREDIT",
        "amendment_freeze_sha256": sha256(FREEZE),
        "module_sha256": sha256(MODULE),
        "synthetic_amendment_a_sha256": sha256(SYNTHETIC),
        "population": len(cases),
        "semantic_fidelity": fidelity,
        "admitted": sum(row["classification"]["admitted"] for row in cases),
        "rejected": sum(not row["classification"]["admitted"] for row in cases),
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
        "result_sha256": sha256(RESULT),
        "payload_sha256": payload["payload_sha256"],
        "semantic_fidelity": fidelity,
        "population": len(cases),
        "admitted": payload["admitted"],
        "rejected": payload["rejected"],
        "module_sha256": payload["module_sha256"],
    }
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(seal, sort_keys=True))


if __name__ == "__main__":
    main()
