#!/usr/bin/env python3
"""Reproduce the sealed human-input V2 result without changing any artifact."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    canonical_hash,
    simulate_track,
)


BASE = ROOT / "research_artifacts" / "gold_coherent_auction_human_policy_v2"
PREPATH = BASE / "prepath_classification_amendment_a.json"
PREPATH_SEAL = BASE / "prepath_classification_amendment_a_seal.json"
SEALED_RESULT = BASE / "matched_case_regression_v2.json"
FINAL_SEAL = BASE / "final_seal_v2.json"
MODULE = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "coherent_auction_human_policy_v2.py"
)
OUT = ROOT / "research_artifacts" / "gold_coherent_auction_autonomous_translation_v1"
RESULT = OUT / "same_month_overlay_control.json"

EXPECTED_NET_R = 10.681846581267534
TOLERANCE = 1e-8


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    return value


def verify() -> dict[str, Any]:
    required = (PREPATH, PREPATH_SEAL, SEALED_RESULT, FINAL_SEAL, MODULE)
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)

    prepath = json.loads(PREPATH.read_text(encoding="utf-8"))
    prepath_seal = json.loads(PREPATH_SEAL.read_text(encoding="utf-8"))
    sealed = json.loads(SEALED_RESULT.read_text(encoding="utf-8"))
    final_seal = json.loads(FINAL_SEAL.read_text(encoding="utf-8"))

    checks = {
        "prepath_hash": sha256_file(PREPATH) == prepath_seal["result_sha256"],
        "module_hash": sha256_file(MODULE) == prepath_seal["module_sha256"],
        "sealed_result_hash": sha256_file(SEALED_RESULT) == final_seal["result_sha256"],
        "sealed_expected_net_r": math.isclose(
            float(sealed["track_summaries"]["COMPLETE_V2_POLICY"]["net_r50"]),
            EXPECTED_NET_R,
            abs_tol=TOLERANCE,
        ),
        "population": len(prepath["cases"]) == 16 == len(sealed["cases"]),
    }
    if not all(checks.values()):
        raise RuntimeError({key: value for key, value in checks.items() if not value})

    sealed_by_alias = {row["case_alias"]: row for row in sealed["cases"]}
    rows: list[dict[str, Any]] = []
    reproduction_hashes: list[str] = []
    for frozen in prepath["cases"]:
        alias = frozen["case_alias"]
        expected = sealed_by_alias[alias]
        classification = frozen["classification"]
        primary = load_gzip(ROOT / frozen["primary_source"])
        reference = load_gzip(ROOT / frozen["reference_source"])
        primary_result = rounded(
            simulate_track(
                classification=classification,
                stream=primary,
                fill_at=frozen["fill_at"],
                track="COMPLETE_V2_POLICY",
            )
        )
        reference_result = rounded(
            simulate_track(
                classification=classification,
                stream=reference,
                fill_at=frozen["fill_at"],
                track="COMPLETE_V2_POLICY",
            )
        )
        expected_result = expected["tracks"]["COMPLETE_V2_POLICY"]
        primary_hash = canonical_hash(primary_result)
        reference_hash = canonical_hash(reference_result)
        expected_hash = canonical_hash(expected_result)
        result_equal = primary_hash == reference_hash == expected_hash
        disposition_equal = (
            bool(classification["admitted"]) == bool(expected["admitted"])
            and classification["primary_disposition"]
            == expected["primary_disposition"]
        )
        if not result_equal or not disposition_equal:
            raise RuntimeError(f"Same-month control mismatch: {alias}")
        reproduction_hashes.append(primary_hash)
        rows.append(
            {
                "case_alias": alias,
                "admitted": bool(classification["admitted"]),
                "primary_disposition": classification["primary_disposition"],
                "net_r50": float(primary_result["net_r50"]),
                "resolution": primary_result["resolution"],
                "result_sha256": primary_hash,
                "primary_reference_exact": True,
                "sealed_case_exact": True,
            }
        )

    reproduced_net_r = sum(row["net_r50"] for row in rows)
    aggregate_exact = math.isclose(reproduced_net_r, EXPECTED_NET_R, abs_tol=TOLERANCE)
    if not aggregate_exact:
        raise RuntimeError(
            f"Aggregate mismatch: {reproduced_net_r!r} != {EXPECTED_NET_R!r}"
        )

    payload: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_AUTONOMOUS_TRANSLATION_V1_OVERLAY_CONTROL_1_0",
        "status": "PASS_SAME_MONTH_HUMAN_INPUT_OVERLAY_CONTROL",
        "evidence_status": "EXPOSED_ZERO_VALIDATION_CREDIT",
        "population": "CBR-2022-001_THROUGH_CBR-2022-030_HUMAN_TRADES_ONLY",
        "human_setup_records": len(rows),
        "admitted": sum(row["admitted"] for row in rows),
        "rejected": sum(not row["admitted"] for row in rows),
        "reproduced_complete_policy_net_r50": reproduced_net_r,
        "expected_complete_policy_net_r50": EXPECTED_NET_R,
        "absolute_difference_r50": abs(reproduced_net_r - EXPECTED_NET_R),
        "tolerance_r50": TOLERANCE,
        "case_results": rows,
        "checks": checks,
        "case_bundle_sha256": canonical_hash(reproduction_hashes),
        "fresh_block_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "autonomous_translation_gate_passed": False,
        "warning": (
            "This certifies the unchanged V2 overlay with sealed human inputs. "
            "It does not certify autonomous setup discovery or geometry."
        ),
    }
    payload["payload_sha256"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "payload_sha256"}
    )
    return payload


def main() -> None:
    payload = verify()
    OUT.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if RESULT.exists():
        existing = json.loads(RESULT.read_text(encoding="utf-8"))
        if existing != payload:
            raise RuntimeError("Existing overlay-control artifact differs")
    else:
        RESULT.write_text(serialized, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "human_setup_records": payload["human_setup_records"],
                "admitted": payload["admitted"],
                "rejected": payload["rejected"],
                "complete_policy_net_r50": payload[
                    "reproduced_complete_policy_net_r50"
                ],
                "absolute_difference_r50": payload["absolute_difference_r50"],
                "autonomous_translation_gate_passed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
