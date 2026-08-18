#!/usr/bin/env python3
"""Independent read-back verifier for the sealed Step 3B.1 artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_3b1_v01"
    / "manifest.json"
)


def main() -> None:
    manifest = _load_json(MANIFEST_PATH)
    declared_manifest_hash = str(manifest.pop("manifest_hash"))
    if _canonical_hash(manifest) != declared_manifest_hash:
        raise ValueError("Step 3B.1 manifest canonical hash mismatch")

    sealed_items = [
        manifest["protocol"],
        manifest["freeze_receipt"],
        manifest["quote_tool"],
        *manifest["artifacts"],
    ]
    for item in sealed_items:
        path = REPO_ROOT / str(item["path"])
        if not path.is_file():
            raise FileNotFoundError(f"Sealed file missing: {path}")
        if path.stat().st_size != int(item["bytes"]):
            raise ValueError(f"Sealed file byte count changed: {path}")
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"Sealed file hash changed: {path}")

    quote = _load_json(
        REPO_ROOT
        / "research_artifacts"
        / "gc_microstructure_step_3b1_v01"
        / "metadata_quote.json"
    )
    declared_quote_hash = str(quote.pop("quote_hash"))
    if (
        _canonical_hash(quote) != declared_quote_hash
        or declared_quote_hash != manifest["quote_hash"]
    ):
        raise ValueError("Step 3B.1 quote hash mismatch")

    readiness = _load_json(
        REPO_ROOT
        / "research_artifacts"
        / "gc_microstructure_step_3b1_v01"
        / "readiness.json"
    )
    gates = readiness["step_3b1_readiness_gates"]
    expected_true = {
        "predecessor_hashes_verified_before_protocol_freeze",
        "protocol_frozen_before_metadata_quote",
        "metadata_request_matches_frozen_identity",
        "estimated_cost_is_finite_and_nonnegative",
        "estimated_record_count_is_positive",
        "estimated_billable_size_is_positive",
    }
    expected_false = {
        "batch_job_submitted",
        "data_downloaded",
        "charge_incurred",
        "mbp10_values_accessed",
        "market_outcomes_accessed",
    }
    if set(gates) != expected_true | expected_false:
        raise ValueError("Step 3B.1 readiness gate names changed")
    if any(gates[name] is not True for name in expected_true):
        raise ValueError("A positive Step 3B.1 readiness gate failed")
    if any(gates[name] is not False for name in expected_false):
        raise ValueError("A prohibited Step 3B.1 action occurred")

    protocol = _load_json(REPO_ROOT / manifest["protocol"]["path"])
    for item in protocol["predecessor_preservation"]["frozen_files"]:
        path = REPO_ROOT / str(item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"Frozen predecessor changed: {path}")

    cardinality = readiness["pre_acquisition_cardinality_audit"]
    calculated_difference = (
        int(cardinality["sealed_mbo_f_last_boundaries"])
        - int(cardinality["metadata_estimated_mbp10_records"])
    )
    if calculated_difference != int(cardinality["absolute_difference"]):
        raise ValueError("Cardinality difference was recorded incorrectly")
    if calculated_difference <= 0:
        raise ValueError("Expected the frozen cardinality incompatibility")
    if cardinality["counts_support_frozen_one_to_one_cardinality"] is not False:
        raise ValueError("Frozen one-to-one incompatibility was not preserved")

    if (
        manifest["status"] != "FAIL_PRE_ACQUISITION_READINESS"
        or manifest["quote_compliance_status"] != "PASS"
        or manifest["future_book_comparison_status"] != "NOT_RUN"
        or readiness["required_stop"] != "STOP_BEFORE_ACQUISITION"
    ):
        raise ValueError("Step 3B.1 verdict or required stop changed")

    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_3B1_SEAL_VERIFIED",
                "status": manifest["status"],
                "quote_compliance_status": manifest["quote_compliance_status"],
                "future_book_comparison_status": manifest[
                    "future_book_comparison_status"
                ],
                "manifest_hash": declared_manifest_hash,
                "sealed_files_verified": len(sealed_items),
                "predecessor_files_verified": len(
                    protocol["predecessor_preservation"]["frozen_files"]
                )
                + 2,
                "cardinality_difference": calculated_difference,
                "batch_job_submitted": False,
                "data_downloaded": False,
                "charge_incurred": False,
                "mbp10_values_accessed": False,
                "market_outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
