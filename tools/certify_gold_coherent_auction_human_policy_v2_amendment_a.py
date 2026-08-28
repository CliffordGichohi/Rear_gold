"""Synthetic recertification after V2 pre-path Amendment A."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
MODULE = ROOT / "backend/src/gold_intel/analytics/coherent_auction_human_policy_v2.py"
TESTS = ROOT / "backend/tests/unit/test_coherent_auction_human_policy_v2.py"
FREEZE = ROOT / "research_manifests/gold_coherent_auction_human_policy_v2_amendment_a_freeze.json"
OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_human_policy_v2"
RESULT = OUTPUT / "synthetic_certification_amendment_a.json"
SEAL = OUTPUT / "synthetic_certification_amendment_a_seal.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def execute() -> list[dict[str, str]]:
    specification = importlib.util.spec_from_file_location("v2_a_tests", TESTS)
    if specification is None or specification.loader is None:
        raise RuntimeError("Unable to load V2 Amendment A tests")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    rows: list[dict[str, str]] = []
    for name in sorted(item for item in vars(module) if item.startswith("test_")):
        getattr(module, name)()
        rows.append({"test": name, "status": "PASS"})
    return rows


def main() -> None:
    if RESULT.exists() or SEAL.exists():
        raise FileExistsError("V2 Amendment A synthetic certification already exists")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha256(MODULE) != freeze["amended_implementation_sha256"]:
        raise RuntimeError("Amended implementation hash mismatch")
    if sha256(TESTS) != freeze["amended_synthetic_test_sha256"]:
        raise RuntimeError("Amended test hash mismatch")
    original_result = OUTPUT / "prepath_classification.json"
    original_seal = OUTPUT / "prepath_classification_seal.json"
    if sha256(original_result) != freeze["preserved_first_prepath_result_sha256"]:
        raise RuntimeError("Original prepath result was not preserved")
    if sha256(original_seal) != freeze["preserved_first_prepath_seal_sha256"]:
        raise RuntimeError("Original prepath seal was not preserved")
    primary = execute()
    reference = execute()
    if canonical_hash(primary) != canonical_hash(reference):
        raise RuntimeError("Amendment A synthetic reproductions disagree")
    payload = {
        "version": "GOLD_COHERENT_AUCTION_HUMAN_POLICY_V2_SYNTHETIC_A_1_0",
        "status": "PASS_AMENDMENT_A_SYNTHETIC_RECERTIFICATION",
        "tests": primary,
        "test_count": len(primary),
        "primary_sha256": canonical_hash(primary),
        "reference_sha256": canonical_hash(reference),
        "amendment_freeze_sha256": sha256(FREEZE),
        "implementation_sha256": sha256(MODULE),
        "test_sha256": sha256(TESTS),
    }
    payload["payload_sha256"] = canonical_hash(payload)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal = {
        "status": payload["status"],
        "result_sha256": sha256(RESULT),
        "payload_sha256": payload["payload_sha256"],
        "test_count": payload["test_count"],
    }
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(seal, sort_keys=True))


if __name__ == "__main__":
    main()
