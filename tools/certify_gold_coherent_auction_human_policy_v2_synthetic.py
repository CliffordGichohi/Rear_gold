"""Standalone synthetic certification for the V2 human-policy translation."""

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
FREEZE = ROOT / "research_manifests/gold_coherent_auction_human_policy_v2_freeze.json"
OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_human_policy_v2"
RESULT = OUTPUT / "synthetic_certification.json"
SEAL = OUTPUT / "synthetic_certification_seal.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def execute() -> list[dict[str, Any]]:
    specification = importlib.util.spec_from_file_location("v2_synthetic_tests", TESTS)
    if specification is None or specification.loader is None:
        raise RuntimeError("Unable to load synthetic test module")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    rows: list[dict[str, Any]] = []
    for name in sorted(item for item in vars(module) if item.startswith("test_")):
        function = getattr(module, name)
        function()
        rows.append({"test": name, "status": "PASS"})
    return rows


def main() -> None:
    if RESULT.exists() or SEAL.exists():
        raise FileExistsError("V2 synthetic certification is already sealed")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha256(MODULE) != freeze["implementation_sha256"]:
        raise RuntimeError("Implementation hash differs from the V2 freeze")
    if sha256(TESTS) != freeze["synthetic_test_sha256"]:
        raise RuntimeError("Synthetic-test hash differs from the V2 freeze")
    primary = execute()
    reference = execute()
    if canonical_hash(primary) != canonical_hash(reference):
        raise RuntimeError("Synthetic primary/reference results disagree")
    payload = {
        "version": "GOLD_COHERENT_AUCTION_HUMAN_POLICY_V2_SYNTHETIC_1_0",
        "status": "PASS_SYNTHETIC_CLASSIFIER_AND_LIFECYCLE",
        "tests": primary,
        "test_count": len(primary),
        "primary_sha256": canonical_hash(primary),
        "reference_sha256": canonical_hash(reference),
        "freeze_sha256": sha256(FREEZE),
        "implementation_sha256": sha256(MODULE),
        "synthetic_test_sha256": sha256(TESTS),
    }
    payload["payload_sha256"] = canonical_hash(payload)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal = {
        "status": payload["status"],
        "result_path": str(RESULT.relative_to(ROOT)).replace("\\", "/"),
        "result_sha256": sha256(RESULT),
        "payload_sha256": payload["payload_sha256"],
        "test_count": payload["test_count"],
    }
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(seal, sort_keys=True))


if __name__ == "__main__":
    main()
