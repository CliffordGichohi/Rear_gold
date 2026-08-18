#!/usr/bin/env python3
"""Freeze the bounded Step 5B.2 source-integrity recertification amendment.

Preparation verifies only predecessor artifacts and sealed inventories. It
does not open source rows or market values and does not recertify any request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b2_amendment_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b2_freeze_v01.json"
)

STEP5B_STATUS = "FAIL_STEP_5B_BUDGET_C_SOURCE_INTEGRITY"
STEP5B_MANIFEST_HASH = (
    "6b4074aa95953232db878027aa0dc85666c478f4abd80e864022e61fded46683"
)
STEP5B_MANIFEST_FILE_SHA256 = (
    "0a4abebcc8957568d33b734d7511481c0203a73e7cb7cacfc4a89c933a21c6f9"
)
STEP5B_VERDICT_FILE_SHA256 = (
    "2ee53fb8169bc1b47f38011cd2600ad74dec37404e806c1dd5a0ba0cbc2ce4bb"
)
STEP5B_ACQUISITION_MANIFEST_SHA256 = (
    "b4e64d508790364dbd400da1478b139bb643d2b7afc9c97ff6691958365c5ccc"
)
STEP5B1_STATUS = "PASS_STEP_5B1_DIAGNOSTIC_REPRODUCTION"
STEP5B1_MANIFEST_HASH = (
    "df049551f423a70bd96c4c5acdd4720a6b531b6774f5b35d71d5c1bf7e232419"
)
STEP5B1_MANIFEST_FILE_SHA256 = (
    "993a5a10172ac0c74cc0521ca6437369e5cc185a363c912d98cbccaafb6f02f7"
)
STEP5B1_VERDICT_FILE_SHA256 = (
    "b30a89a604d2f69a0616512e289267a342dcb99fde611520a034dfd89f439c96"
)
STEP5B1_PRIMARY_SHA256 = (
    "6ef3c3bfa2dfa6dd0a49c30d17adb4292b7168ff84fc73b02204457429d3c0bc"
)
STEP5B1_REFERENCE_SHA256 = (
    "562a2cda371f475885e8ebbc26edddb1603f148940b951b2cdf0c67e5ccd6275"
)
STEP5B1_PROTOCOL_SHA256 = (
    "62eaf586944d720ccab584e7ebfb1ce40d7eaabfe9e9508f542680873cfd5f87"
)
STEP5B1_INVENTORY_SHA256 = (
    "a4e2bf8acf97b0ddefde017f36142f5356223ec5ca106fc8e7228cdb5c75b0af"
)
STEP5B1_FREEZE_SHA256 = (
    "a6b9d1ceabb286836f279dc275e4427f8dd4871b1058abfa70e5e869e6a7e29a"
)
STEP5B1_CORRECTION_SHA256 = (
    "8575cc960b6b9c9d3124c224d790a50a8d3750676f59d85768426c54a834865c"
)

AUTHORIZED_CHANGED_CHECKS = (
    "receive_does_not_precede_event",
    "bad_ts_recv_rows_follow_snapshot_semantics",
    "all_prediction_windows_complete_or_documented_unknown",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--remote-root", default="/home/wapi/rear_gold_step5b_v01"
    )
    args = parser.parse_args()
    prepare(Path(args.remote_root))


def prepare(remote_root: Path) -> None:
    for path in (AMENDMENT_PATH, FREEZE_PATH):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite frozen artifact: {path}")

    step5b_manifest_path = remote_root / "artifacts/step5b_budget_c_final/manifest.json"
    step5b_verdict_path = remote_root / "artifacts/step5b_budget_c_final/verdict.json"
    acquisition_path = (
        remote_root
        / "data/databento_gc_microstructure_budget_c_v01/acquisition_manifest.json"
    )
    step5b1_manifest_path = remote_root / "artifacts/step5b1_final/manifest.json"
    step5b1_verdict_path = remote_root / "artifacts/step5b1_final/verdict.json"
    step5b1_primary_path = remote_root / "artifacts/step5b1_runs_v02/primary_diagnostic.json"
    step5b1_reference_path = remote_root / "artifacts/step5b1_runs_v02/reference_diagnostic.json"
    correction_path = (
        REPO_ROOT
        / "research_manifests"
        / "gc_microstructure_step_5b1_implementation_scope_correction_v01.json"
    )
    protocol_path = (
        REPO_ROOT
        / "research_manifests"
        / "gc_microstructure_step_5b1_protocol_v01.json"
    )
    inventory_path = (
        REPO_ROOT
        / "research_manifests"
        / "gc_microstructure_step_5b1_source_inventory_v01.json"
    )
    step5b1_freeze_path = (
        REPO_ROOT
        / "research_manifests"
        / "gc_microstructure_step_5b1_freeze_v01.json"
    )

    expected = {
        step5b_manifest_path: STEP5B_MANIFEST_FILE_SHA256,
        step5b_verdict_path: STEP5B_VERDICT_FILE_SHA256,
        acquisition_path: STEP5B_ACQUISITION_MANIFEST_SHA256,
        step5b1_manifest_path: STEP5B1_MANIFEST_FILE_SHA256,
        step5b1_verdict_path: STEP5B1_VERDICT_FILE_SHA256,
        step5b1_primary_path: STEP5B1_PRIMARY_SHA256,
        step5b1_reference_path: STEP5B1_REFERENCE_SHA256,
        correction_path: STEP5B1_CORRECTION_SHA256,
        protocol_path: STEP5B1_PROTOCOL_SHA256,
        inventory_path: STEP5B1_INVENTORY_SHA256,
        step5b1_freeze_path: STEP5B1_FREEZE_SHA256,
    }
    for path, sha256 in expected.items():
        _verify_hash(path, sha256)

    step5b_manifest = _read_json(step5b_manifest_path)
    step5b_verdict = _read_json(step5b_verdict_path)
    step5b1_manifest = _read_json(step5b1_manifest_path)
    step5b1_verdict = _read_json(step5b1_verdict_path)
    primary = _read_json(step5b1_primary_path)
    reference = _read_json(step5b1_reference_path)
    correction = _read_json(correction_path)
    acquisition = _read_json(acquisition_path)

    if step5b_manifest["manifest_hash"] != STEP5B_MANIFEST_HASH:
        raise ValueError("Step 5B manifest hash changed")
    if step5b_manifest["status"] != STEP5B_STATUS or step5b_verdict["status"] != STEP5B_STATUS:
        raise ValueError("Step 5B historical failure changed")
    if len(step5b_manifest["source_and_normalized_files"]) != 936:
        raise ValueError("Step 5B source inventory no longer has 936 files")
    if step5b1_manifest["manifest_hash"] != STEP5B1_MANIFEST_HASH:
        raise ValueError("Step 5B.1 manifest hash changed")
    if step5b1_manifest["status"] != STEP5B1_STATUS or step5b1_verdict["status"] != STEP5B1_STATUS:
        raise ValueError("Step 5B.1 diagnostic pass changed")
    if primary["reproducible_payload"] != reference["reproducible_payload"]:
        raise ValueError("Step 5B.1 independent payloads no longer match")
    if correction["attempt_overwritten_or_deleted"] is not False:
        raise ValueError("Step 5B.1 implementation attempt preservation changed")
    if len(acquisition["requests"]) != 80:
        raise ValueError("Acquisition request count changed")
    if int(step5b_verdict["quality_pass_count"]) != 67:
        raise ValueError("Original passing-request count changed")
    if step5b1_verdict["aggregate"]["request_classification_counts"] != {
        "DOCUMENTED_VALID_SEMANTICS": 11,
        "EXPECTED_CALENDAR_UNAVAILABILITY": 2,
    }:
        raise ValueError("Step 5B.1 classifications changed")

    now = _utc_now()
    amendment = {
        "version": "GC_MICROSTRUCTURE_STEP_5B2_AMENDMENT_V0_1",
        "status": "FROZEN_BEFORE_RECERTIFICATION",
        "frozen_at_utc": now,
        "classification": "VALUE_BLIND_SOURCE_INTEGRITY_RECERTIFICATION_ONLY",
        "research_or_validation_credit": "NONE",
        "purpose": (
            "Recertify the same 80 sealed Step 5B sources by changing only "
            "the three dispositions proven in Step 5B.1."
        ),
        "predecessor_preservation": {
            "required_step5b_status": STEP5B_STATUS,
            "required_step5b_manifest_hash": STEP5B_MANIFEST_HASH,
            "required_step5b1_status": STEP5B1_STATUS,
            "required_step5b1_manifest_hash": STEP5B1_MANIFEST_HASH,
            "implementation_correction_record_preserved": True,
            "all_predecessor_artifacts_and_seals_immutable": True,
        },
        "sealed_inputs": {
            "step5b_manifest": _file_record_external(step5b_manifest_path),
            "step5b_verdict": _file_record_external(step5b_verdict_path),
            "step5b_acquisition_manifest": _file_record_external(acquisition_path),
            "step5b1_manifest": _file_record_external(step5b1_manifest_path),
            "step5b1_verdict": _file_record_external(step5b1_verdict_path),
            "step5b1_primary": _file_record_external(step5b1_primary_path),
            "step5b1_reference": _file_record_external(step5b1_reference_path),
            "step5b1_protocol": _file_record(protocol_path),
            "step5b1_source_inventory": _file_record(inventory_path),
            "step5b1_freeze": _file_record(step5b1_freeze_path),
            "step5b1_implementation_correction": _file_record(correction_path),
            "source_and_normalized_file_records": 936,
            "provider_requests": 80,
            "previously_passing_requests": 67,
            "diagnosed_requests_to_recertify": 13,
        },
        "authorized_changes": {
            "exact_formal_check_keys": list(AUTHORIZED_CHANGED_CHECKS),
            "receive_does_not_precede_event": {
                "scope": "Only MBO rows satisfying ts_recv < ts_event.",
                "structural_validity_required": [
                    "publisher_id equals 1",
                    "instrument_id equals the frozen date mapping",
                    "action belongs to the frozen action registry",
                    "ts_recv is inside the frozen request",
                    "ts_event is before the frozen request end",
                ],
                "permitted_dispositions": [
                    "F_BAD_TS_RECV is set and structural validity passes",
                    "F_BAD_TS_RECV is unset, ts_in_delta is negative and unclamped, derived publisher_send_ns equals ts_recv minus ts_in_delta, publisher_send_ns is at or after ts_event, and structural validity passes",
                ],
                "all_other_ts_recv_before_ts_event_rows": "FAIL",
            },
            "bad_ts_recv_rows_follow_snapshot_semantics": {
                "snapshot_rows": (
                    "Retain the original historical snapshot requirements: "
                    "UTC day-start ts_recv, ts_event before day start and not "
                    "after ts_recv, and action A or R."
                ),
                "non_snapshot_rows": (
                    "Permit only when F_BAD_TS_RECV is set and the same "
                    "frozen structural-validity tests pass."
                ),
                "all_other_rows": "FAIL",
            },
            "all_prediction_windows_complete_or_documented_unknown": {
                "exact_new_dispositions": [
                    "Q017:mbo|2022-04-15|LONDON|UNAVAILABLE_DOCUMENTED",
                    "Q017:mbo|2022-04-15|NEW_YORK|UNAVAILABLE_DOCUMENTED",
                    "Q018:mbp-10|2022-04-15|LONDON|UNAVAILABLE_DOCUMENTED",
                    "Q018:mbp-10|2022-04-15|NEW_YORK|UNAVAILABLE_DOCUMENTED",
                ],
                "basis": "Official CME Good Friday calendar bound in sealed Step 5B.1.",
                "every_other_prediction_window": "UNCHANGED",
            },
        },
        "unchanged_policy": {
            "all_other_formal_check_keys": "BYTE-FOR-BYTE LOGICAL VALUES UNCHANGED",
            "sources_rows_hashes_definitions_prediction_windows_and_missing_data_rules": "UNCHANGED",
            "67_previously_passing_requests": "RETAIN ORIGINAL FORMAL CHECKS WITHOUT MUTATION",
            "no_source_row_filter_repair_relabel_replace_or_reacquisition": True,
        },
        "source_verification": {
            "verify_all_936_manifest_records_by_bytes_and_sha256": True,
            "verify_exactly_80_normalized_source_seals": True,
            "verify_exactly_80_normalized_payloads": True,
            "verify_exactly_80_quality_records": True,
            "verify_exactly_80_lineage_records": True,
            "source_rows_may_not_be_opened": True,
        },
        "independent_recertification": {
            "primary_input": "Sealed Step 5B.1 primary diagnostic",
            "reference_input": "Sealed Step 5B.1 reference diagnostic",
            "each_implementation": (
                "Independently rebuilds all 80 amended formal-check maps from "
                "the sealed original data-quality records and its own Step "
                "5B.1 diagnostic payload."
            ),
            "identical_required": [
                "all 80 request IDs and original quality gates",
                "all unchanged formal checks",
                "the exact changed-check set per diagnosed request",
                "all amended formal-check maps",
                "67 unchanged passes and 13 recertified requests",
                "all request verdicts and aggregate checksums",
            ],
        },
        "pass_rule": (
            "PASS only when all 936 source records verify, all 80 source "
            "requests pass the amended integrity map, the original 67 are "
            "unchanged, exactly 13 are recertified using only the three "
            "authorized checks, and independent outputs are identical."
        ),
        "status_precedence": [
            "FAIL_STEP_5B2_PREDECESSOR_OR_SOURCE_SEAL",
            "FAIL_STEP_5B2_RECERTIFICATION_INTEGRITY",
            "FAIL_STEP_5B2_RECERTIFICATION_REPRODUCTION",
            "PASS_STEP_5B2_SOURCE_INTEGRITY_RECERTIFICATION",
        ],
        "prohibited": [
            "changing any predecessor verdict, seal, source, or row",
            "changing any formal gate beyond the three authorized keys",
            "acquiring data or incurring a charge",
            "inspecting price, depth, size, order-flow, feature, or outcome values",
            "calculating relationships, candidates, signals, execution, trades, PnL, R multiples, or returns",
            "starting Step 5C",
        ],
        "completion_policy": "Document, seal, verify, and stop after Step 5B.2.",
        "market_values_or_outcomes_accessed_or_reported": False,
        "charge_incurred_usd": 0.0,
    }
    _write_json_atomic(AMENDMENT_PATH, amendment)
    amendment_record = _file_record(AMENDMENT_PATH)
    freeze = {
        "version": "GC_MICROSTRUCTURE_STEP_5B2_FREEZE_V0_1",
        "status": "BOUNDED_AMENDMENT_SEALED_BEFORE_RECERTIFICATION",
        "sealed_at_utc": _utc_now(),
        "classification": "VALUE_BLIND_SOURCE_INTEGRITY_RECERTIFICATION_ONLY",
        "research_or_validation_credit": "NONE",
        "amendment": amendment_record,
        "preparation_tool": _file_record(Path(__file__)),
        "pre_freeze_verification": {
            "step5b_historical_failure_preserved": True,
            "step5b1_diagnostic_pass_preserved": True,
            "step5b1_independent_payloads_identical": True,
            "implementation_correction_preserved": True,
            "source_inventory_records_bound": 936,
            "provider_requests_bound": 80,
            "source_rows_accessed": False,
            "market_values_or_outcomes_accessed_or_reported": False,
        },
        "frozen_scope": {
            "authorized_changed_check_keys": list(AUTHORIZED_CHANGED_CHECKS),
            "all_other_checks_unchanged": True,
            "source_verification_gates_frozen": True,
            "independent_recertification_gates_frozen": True,
            "pass_rule_frozen": True,
            "no_recategorization_or_repair_permitted": True,
        },
        "recertification_started": False,
        "market_values_or_outcomes_accessed_or_reported": False,
        "charge_incurred_usd": 0.0,
    }
    _write_json_atomic(FREEZE_PATH, freeze)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B2_AMENDMENT_FROZEN",
                "amendment_sha256": amendment_record["sha256"],
                "freeze_sha256": _sha256(FREEZE_PATH),
                "source_inventory_records": 936,
                "provider_requests": 80,
                "source_rows_accessed": False,
                "market_values_or_outcomes_accessed": False,
                "charge_incurred_usd": 0.0,
            },
            sort_keys=True,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual} != {expected}")


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _file_record_external(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
