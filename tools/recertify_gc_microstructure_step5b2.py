#!/usr/bin/env python3
"""Run the frozen Step 5B.2 value-blind source recertification.

No source row or market value is opened. The tool verifies sealed files and
rebuilds formal quality maps from existing sealed technical diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
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
CORRECTION_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b1_implementation_scope_correction_v01.json"
)

EXPECTED_AMENDMENT_SHA256 = (
    "1a6dd3372f40b52d219b38e35504b9a96046ffc284117ed1ac6cc703d009f9d7"
)
EXPECTED_FREEZE_SHA256 = (
    "0c1e7b8db099ea4489c201dda9893da184a55f8159f89a4ce946e78a1485f918"
)
EXPECTED_CORRECTION_SHA256 = (
    "8575cc960b6b9c9d3124c224d790a50a8d3750676f59d85768426c54a834865c"
)
STEP5B_STATUS = "FAIL_STEP_5B_BUDGET_C_SOURCE_INTEGRITY"
STEP5B_MANIFEST_HASH = (
    "6b4074aa95953232db878027aa0dc85666c478f4abd80e864022e61fded46683"
)
STEP5B1_STATUS = "PASS_STEP_5B1_DIAGNOSTIC_REPRODUCTION"
STEP5B1_MANIFEST_HASH = (
    "df049551f423a70bd96c4c5acdd4720a6b531b6774f5b35d71d5c1bf7e232419"
)
PASS_STATUS = "PASS_STEP_5B2_SOURCE_INTEGRITY_RECERTIFICATION"

CHECK_RECEIVE = "receive_does_not_precede_event"
CHECK_BAD = "bad_ts_recv_rows_follow_snapshot_semantics"
CHECK_CALENDAR = "all_prediction_windows_complete_or_documented_unknown"
AUTHORIZED_CHECKS = {CHECK_RECEIVE, CHECK_BAD, CHECK_CALENDAR}
EXPECTED_CHANGED_CHECK_COUNTS = {
    CHECK_RECEIVE: 10,
    CHECK_BAD: 2,
    CHECK_CALENDAR: 2,
}
EXPECTED_FILE_CATEGORIES = {
    "data_quality": 80,
    "lineage": 80,
    "normalized_payload": 80,
    "provider_dbn": 376,
    "provider_metadata": 240,
    "source_seal": 80,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("source_verify", "primary", "reference", "seal", "verify")
    )
    parser.add_argument(
        "--remote-root", default="/home/wapi/rear_gold_step5b_v01"
    )
    parser.add_argument("--output", default=None)
    parser.add_argument("--artifacts", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    remote_root = Path(args.remote_root)
    output = Path(args.output) if args.output else remote_root / "artifacts/step5b2_runs"
    artifacts = (
        Path(args.artifacts)
        if args.artifacts
        else remote_root / "artifacts/step5b2_final"
    )
    report = (
        Path(args.report)
        if args.report
        else remote_root / "artifacts/GC_MICROSTRUCTURE_STEP_5B2_REPORT.md"
    )
    run_stage(args.action, remote_root, output, artifacts, report)


def run_stage(
    action: str,
    remote_root: Path,
    output: Path,
    artifacts: Path,
    report: Path,
) -> None:
    context = _verified_context(remote_root)
    _assert_amendment_matches_code(context["amendment"])
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / "source_verification.json"
    if action == "source_verify":
        if receipt_path.exists():
            raise FileExistsError(f"Refusing to overwrite {receipt_path}")
        payload = _verify_all_source_records(context, emit_progress=True)
        result = {
            "version": "GC_MICROSTRUCTURE_STEP_5B2_SOURCE_VERIFICATION_V0_1",
            "completed_at_utc": _utc_now(),
            "tool_sha256": _sha256(Path(__file__)),
            "amendment_sha256": EXPECTED_AMENDMENT_SHA256,
            "freeze_sha256": EXPECTED_FREEZE_SHA256,
            "reproducible_payload": payload,
        }
        _write_json_atomic(receipt_path, result)
        print(
            json.dumps(
                {
                    "stage": "GC_MICROSTRUCTURE_STEP_5B2_SOURCE_SEALS_VERIFIED",
                    "status": payload["status"],
                    "verified_files": payload["verified_files"],
                    "verified_source_seals": payload["categories"]["source_seal"],
                    "verified_provider_requests": payload["verified_provider_requests"],
                    "market_values_or_outcomes_accessed": False,
                    "charge_incurred_usd": 0.0,
                },
                sort_keys=True,
            )
        )
        return

    source_receipt = _verified_source_receipt(receipt_path, context)
    if action in {"primary", "reference"}:
        destination = output / f"{action}_recertification.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite {destination}")
        payload = _run_recertification(context, source_receipt, implementation=action)
        result = {
            "version": "GC_MICROSTRUCTURE_STEP_5B2_RECERTIFICATION_RUN_V0_1",
            "implementation": action,
            "completed_at_utc": _utc_now(),
            "tool_sha256": _sha256(Path(__file__)),
            "amendment_sha256": EXPECTED_AMENDMENT_SHA256,
            "freeze_sha256": EXPECTED_FREEZE_SHA256,
            "source_verification_sha256": _sha256(receipt_path),
            "reproducible_payload": payload,
        }
        _write_json_atomic(destination, result)
        print(
            json.dumps(
                {
                    "stage": f"GC_MICROSTRUCTURE_STEP_5B2_{action.upper()}_COMPLETE",
                    "integrity_pass": payload["formal_integrity_pass"],
                    "original_unchanged_passes": payload["aggregate"][
                        "unchanged_original_passes"
                    ],
                    "diagnosed_requests_recertified": payload["aggregate"][
                        "diagnosed_requests_recertified"
                    ],
                    "recertified_passes": payload["aggregate"][
                        "recertified_pass_count"
                    ],
                    "market_values_or_outcomes_accessed": False,
                    "charge_incurred_usd": 0.0,
                },
                sort_keys=True,
            )
        )
        return
    if action == "seal":
        _seal(context, source_receipt, output, artifacts, report)
        return
    if action == "verify":
        _verify_seal(context, source_receipt, artifacts, report)
        return
    raise AssertionError(action)


def _verify_all_source_records(
    context: dict[str, Any], *, emit_progress: bool
) -> dict[str, Any]:
    records = context["step5b_manifest"]["source_and_normalized_files"]
    if len(records) != 936:
        raise ValueError("Frozen source inventory does not contain 936 records")
    paths = [record["path"] for record in records]
    if len(paths) != len(set(paths)):
        raise ValueError("Frozen source inventory contains duplicate paths")
    categories = Counter()
    failures: list[dict[str, Any]] = []
    inventory_digest = hashlib.sha256()
    verified_bytes = 0
    seal_request_ids: set[str] = set()
    original_quality_gates = Counter()
    inventory_by_path = {record["path"]: record for record in records}

    for index, record in enumerate(records, start=1):
        path = Path(record["path"])
        category = _file_category(path)
        categories[category] += 1
        actual_bytes = path.stat().st_size if path.is_file() else None
        actual_sha = _sha256(path) if path.is_file() else None
        matches = (
            actual_bytes == int(record["bytes"])
            and actual_sha == record["sha256"]
        )
        if not matches:
            failures.append(
                {
                    "path_hash": hashlib.sha256(str(path).encode()).hexdigest(),
                    "category": category,
                    "exists": path.is_file(),
                    "bytes_match": actual_bytes == int(record["bytes"]),
                    "sha256_match": actual_sha == record["sha256"],
                }
            )
        else:
            verified_bytes += int(record["bytes"])
        inventory_digest.update(
            f"{record['path']}|{record['bytes']}|{record['sha256']}\n".encode()
        )
        if category == "source_seal" and matches:
            seal = _read_json(path)
            seal_without_hash = dict(seal)
            embedded = seal_without_hash.pop("seal_hash")
            if _canonical_json_hash(seal_without_hash) != embedded:
                failures.append(
                    {
                        "path_hash": hashlib.sha256(str(path).encode()).hexdigest(),
                        "category": "source_seal_internal_hash",
                        "exists": True,
                        "bytes_match": True,
                        "sha256_match": False,
                    }
                )
            request_id = seal["request_id"]
            if request_id in seal_request_ids:
                raise ValueError(f"Duplicate source seal request ID: {request_id}")
            seal_request_ids.add(request_id)
            original_quality_gates[seal["quality_gate"]] += 1
            for key in ("normalized_payload", "lineage", "data_quality"):
                internal = seal[key]
                external = inventory_by_path.get(internal["path"])
                if external != internal:
                    failures.append(
                        {
                            "path_hash": hashlib.sha256(str(path).encode()).hexdigest(),
                            "category": f"source_seal_{key}_binding",
                            "exists": True,
                            "bytes_match": False,
                            "sha256_match": False,
                        }
                    )
            for raw in seal["raw_sources"]:
                external = inventory_by_path.get(raw["path"])
                if external != raw:
                    failures.append(
                        {
                            "path_hash": hashlib.sha256(str(path).encode()).hexdigest(),
                            "category": "source_seal_raw_binding",
                            "exists": True,
                            "bytes_match": False,
                            "sha256_match": False,
                        }
                    )
        if emit_progress and (index % 50 == 0 or index == len(records)):
            print(
                json.dumps(
                    {
                        "progress": f"{index}/{len(records)}",
                        "technical_files_verified": index - len(failures),
                        "failures": len(failures),
                        "market_values_accessed": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    category_map = {key: int(value) for key, value in sorted(categories.items())}
    gates = {
        "exactly_936_unique_file_records": len(records) == 936 and len(set(paths)) == 936,
        "all_file_bytes_and_hashes_match": not failures,
        "exact_file_categories_reproduced": category_map == EXPECTED_FILE_CATEGORIES,
        "exactly_80_unique_source_seals": len(seal_request_ids) == 80,
        "original_67_pass_13_fail_seals_reproduced": dict(original_quality_gates) == {
            "FAIL": 13,
            "PASS": 67,
        },
        "all_seal_internal_hashes_and_bindings_valid": not failures,
        "no_source_rows_or_market_values_opened": True,
    }
    status = "PASS_SOURCE_SEAL_VERIFICATION" if all(gates.values()) else "FAIL_SOURCE_SEAL_VERIFICATION"
    return {
        "status": status,
        "verified_files": len(records) - len([item for item in failures if item["category"] in EXPECTED_FILE_CATEGORIES]),
        "verified_bytes": verified_bytes,
        "verified_provider_requests": len(seal_request_ids),
        "categories": category_map,
        "original_quality_gates": dict(sorted(original_quality_gates.items())),
        "source_inventory_ordered_sha256": inventory_digest.hexdigest(),
        "failure_count": len(failures),
        "failures": failures,
        "formal_gates": gates,
        "formal_pass": all(gates.values()),
        "source_rows_or_market_values_accessed": False,
        "charge_incurred_usd": 0.0,
    }


def _run_recertification(
    context: dict[str, Any],
    source_receipt: dict[str, Any],
    *,
    implementation: str,
) -> dict[str, Any]:
    acquisition = context["acquisition"]
    diagnostic_wrapper = (
        context["step5b1_primary"]
        if implementation == "primary"
        else context["step5b1_reference"]
    )
    diagnostic_sources = {
        item["request_id"]: item
        for item in diagnostic_wrapper["reproducible_payload"]["sources"]
    }
    request_results = []
    for request in acquisition["requests"]:
        quality_record = request["normalization"]["data_quality"]
        quality = _read_json(Path(quality_record["path"]))
        if _sha256(Path(quality_record["path"])) != quality_record["sha256"]:
            raise ValueError(f"Quality record changed: {request['request_id']}")
        result = (
            _recertify_request_primary(request, quality, diagnostic_sources)
            if implementation == "primary"
            else _recertify_request_reference(request, quality, diagnostic_sources)
        )
        request_results.append(result)
    return _assemble_recertification(
        request_results, source_receipt, context=context
    )


def _recertify_request_primary(
    request: dict[str, Any],
    quality: dict[str, Any],
    diagnostic_sources: dict[str, Any],
) -> dict[str, Any]:
    request_id = request["request_id"]
    original = {key: bool(value) for key, value in quality["formal_checks"].items()}
    original_false = sorted(key for key, value in original.items() if not value)
    amended = dict(original)
    evidence: dict[str, str] = {}
    diagnostic = diagnostic_sources.get(request_id)
    if quality["quality_gate"] == "PASS":
        if original_false or diagnostic is not None:
            raise ValueError(f"Passing request changed or entered diagnostic set: {request_id}")
    else:
        if diagnostic is None or set(original_false).difference(AUTHORIZED_CHECKS):
            raise ValueError(f"Unauthorized failed check for {request_id}: {original_false}")
        for check in original_false:
            if check == CHECK_RECEIVE:
                passed = _primary_receive_evidence(diagnostic)
                evidence[check] = "STEP5B1_DOCUMENTED_TIMESTAMP_SEMANTICS"
            elif check == CHECK_BAD:
                passed = _primary_bad_evidence(diagnostic)
                evidence[check] = "STEP5B1_DOCUMENTED_BAD_TS_RECV_SEMANTICS"
            elif check == CHECK_CALENDAR:
                passed = _primary_calendar_evidence(diagnostic)
                evidence[check] = "STEP5B1_CME_GOOD_FRIDAY_UNAVAILABLE"
            else:
                raise AssertionError(check)
            amended[check] = passed
    return _request_result(request_id, quality, original, amended, evidence)


def _recertify_request_reference(
    request: dict[str, Any],
    quality: dict[str, Any],
    diagnostic_sources: dict[str, Any],
) -> dict[str, Any]:
    request_id = request["request_id"]
    pairs = [(key, bool(value)) for key, value in quality["formal_checks"].items()]
    original = dict(pairs)
    failed = [key for key, value in pairs if value is False]
    amended_pairs = list(pairs)
    evidence: dict[str, str] = {}
    diagnostic = diagnostic_sources.get(request_id)
    if quality["quality_gate"] == "PASS":
        if failed or request_id in diagnostic_sources:
            raise ValueError(f"Reference found changed passing request: {request_id}")
    else:
        if diagnostic is None or any(key not in AUTHORIZED_CHECKS for key in failed):
            raise ValueError(f"Reference found unauthorized failure: {request_id}")
        replacements: dict[str, bool] = {}
        for check in failed:
            if check == CHECK_RECEIVE:
                replacements[check] = _reference_receive_evidence(diagnostic)
                evidence[check] = "STEP5B1_DOCUMENTED_TIMESTAMP_SEMANTICS"
            elif check == CHECK_BAD:
                replacements[check] = _reference_bad_evidence(diagnostic)
                evidence[check] = "STEP5B1_DOCUMENTED_BAD_TS_RECV_SEMANTICS"
            elif check == CHECK_CALENDAR:
                replacements[check] = _reference_calendar_evidence(diagnostic)
                evidence[check] = "STEP5B1_CME_GOOD_FRIDAY_UNAVAILABLE"
        amended_pairs = [
            (key, replacements.get(key, value)) for key, value in amended_pairs
        ]
    return _request_result(request_id, quality, original, dict(amended_pairs), evidence)


def _primary_receive_evidence(source: dict[str, Any]) -> bool:
    counter = source["technical_cross_tabs"]["receive_taxonomy"]
    accepted = int(counter.get("RB_FLAGGED_BAD_TS_RECV", 0)) + int(
        counter.get("RB_UNFLAGGED_NEGATIVE_DELTA_COHERENT", 0)
    )
    reproduced = int(source["reproduced_counts"]["receive_before_event_rows"])
    rejected = sum(
        int(counter.get(key, 0))
        for key in (
            "RB_STRUCTURAL_INVALID",
            "RB_UNFLAGGED_CLAMPED_TS_IN_DELTA",
            "RB_UNFLAGGED_TIMESTAMP_INCOHERENT",
        )
    )
    return (
        source["family_findings"].get("receive_before_event")
        == "DOCUMENTED_VALID_SEMANTICS"
        and accepted == reproduced
        and rejected == 0
    )


def _reference_receive_evidence(source: dict[str, Any]) -> bool:
    categories = source["technical_cross_tabs"]["receive_taxonomy"]
    forbidden = {
        "RB_STRUCTURAL_INVALID",
        "RB_UNFLAGGED_CLAMPED_TS_IN_DELTA",
        "RB_UNFLAGGED_TIMESTAMP_INCOHERENT",
    }
    observed_forbidden = any(int(categories.get(key, 0)) != 0 for key in forbidden)
    permitted_total = sum(
        int(value)
        for key, value in categories.items()
        if key in {
            "RB_FLAGGED_BAD_TS_RECV",
            "RB_UNFLAGGED_NEGATIVE_DELTA_COHERENT",
        }
    )
    return (
        not observed_forbidden
        and permitted_total
        == int(source["sealed_counts"]["receive_before_event_rows"])
        and source["request_classification"] == "DOCUMENTED_VALID_SEMANTICS"
    )


def _primary_bad_evidence(source: dict[str, Any]) -> bool:
    counter = source["technical_cross_tabs"]["bad_taxonomy"]
    documented = int(counter.get("BAD_NON_SNAPSHOT_DOCUMENTED", 0))
    rejected = sum(
        int(counter.get(key, 0))
        for key in (
            "BAD_STRUCTURAL_INVALID",
            "BAD_SNAPSHOT_CONTRADICTION",
            "BAD_OTHER_UNRESOLVED",
        )
    )
    return (
        source["family_findings"].get("bad_ts_recv_old_snapshot_rule")
        == "DOCUMENTED_VALID_SEMANTICS"
        and documented
        == int(source["reproduced_counts"]["bad_ts_recv_old_snapshot_rule_violations"])
        and rejected == 0
    )


def _reference_bad_evidence(source: dict[str, Any]) -> bool:
    taxonomy = source["technical_cross_tabs"]["bad_taxonomy"]
    keys = {key for key, value in taxonomy.items() if int(value) > 0}
    return (
        keys == {"BAD_NON_SNAPSHOT_DOCUMENTED"}
        and int(taxonomy["BAD_NON_SNAPSHOT_DOCUMENTED"])
        == int(source["sealed_counts"]["bad_ts_recv_old_snapshot_rule_violations"])
        and source["request_classification"] == "DOCUMENTED_VALID_SEMANTICS"
    )


def _primary_calendar_evidence(source: dict[str, Any]) -> bool:
    incomplete = [
        item
        for item in source["prediction_windows"]
        if item["reproduced_disposition"] == "INCOMPLETE_SOURCE"
    ]
    expected = {
        ("2022-04-15", "LONDON"),
        ("2022-04-15", "NEW_YORK"),
    }
    return (
        source["family_findings"].get("calendar_coverage")
        == "EXPECTED_CALENDAR_UNAVAILABILITY"
        and {(item["trade_date"], item["session"]) for item in incomplete} == expected
        and all(item["official_calendar_state"] == "CME_GOOD_FRIDAY_HOLIDAY" for item in incomplete)
    )


def _reference_calendar_evidence(source: dict[str, Any]) -> bool:
    dispositions = Counter(
        (
            item["trade_date"],
            item["session"],
            item["reproduced_disposition"],
            item["official_calendar_state"],
        )
        for item in source["prediction_windows"]
    )
    required = {
        ("2022-04-15", "LONDON", "INCOMPLETE_SOURCE", "CME_GOOD_FRIDAY_HOLIDAY"),
        ("2022-04-15", "NEW_YORK", "INCOMPLETE_SOURCE", "CME_GOOD_FRIDAY_HOLIDAY"),
    }
    observed = {key for key, value in dispositions.items() if key[2] == "INCOMPLETE_SOURCE" and value == 1}
    return (
        observed == required
        and source["request_classification"] == "EXPECTED_CALENDAR_UNAVAILABILITY"
    )


def _request_result(
    request_id: str,
    quality: dict[str, Any],
    original: dict[str, bool],
    amended: dict[str, bool],
    evidence: dict[str, str],
) -> dict[str, Any]:
    changed = sorted(key for key in original if original[key] != amended[key])
    unchanged = sorted(key for key in original if original[key] == amended[key])
    unauthorized = sorted(set(changed).difference(AUTHORIZED_CHECKS))
    return {
        "request_id": request_id,
        "schema": quality["schema"],
        "original_quality_gate": quality["quality_gate"],
        "original_formal_checks": original,
        "amended_formal_checks": amended,
        "changed_checks": changed,
        "unchanged_check_count": len(unchanged),
        "unauthorized_changed_checks": unauthorized,
        "evidence": evidence,
        "recertified_quality_gate": "PASS" if all(amended.values()) else "FAIL",
        "source_rows_or_market_values_accessed": False,
    }


def _assemble_recertification(
    requests: list[dict[str, Any]],
    source_receipt: dict[str, Any],
    *,
    context: dict[str, Any],
) -> dict[str, Any]:
    original_gates = Counter(item["original_quality_gate"] for item in requests)
    recertified_gates = Counter(item["recertified_quality_gate"] for item in requests)
    changed_counts = Counter(
        check for item in requests for check in item["changed_checks"]
    )
    unchanged_passes = sum(
        item["original_quality_gate"] == "PASS" and not item["changed_checks"]
        for item in requests
    )
    diagnosed = sum(
        item["original_quality_gate"] == "FAIL"
        and item["recertified_quality_gate"] == "PASS"
        for item in requests
    )
    unauthorized = sum(len(item["unauthorized_changed_checks"]) for item in requests)
    check_maps_hash = _canonical_json_hash(
        [
            {
                "request_id": item["request_id"],
                "checks": item["amended_formal_checks"],
            }
            for item in requests
        ]
    )
    gates = {
        "step5b_historical_failure_preserved": context["step5b_verdict"]["status"] == STEP5B_STATUS,
        "step5b1_diagnostic_pass_preserved": context["step5b1_verdict"]["status"] == STEP5B1_STATUS,
        "source_verification_passed": source_receipt["reproducible_payload"]["formal_pass"],
        "exactly_80_requests_rebuilt": len(requests) == 80,
        "original_67_pass_13_fail_reproduced": dict(original_gates) == {"FAIL": 13, "PASS": 67},
        "67_original_passes_unchanged": unchanged_passes == 67,
        "13_diagnosed_requests_recertified": diagnosed == 13,
        "only_authorized_checks_changed": unauthorized == 0 and set(changed_counts).issubset(AUTHORIZED_CHECKS),
        "exact_changed_check_counts_reproduced": dict(changed_counts) == EXPECTED_CHANGED_CHECK_COUNTS,
        "all_80_requests_pass_amended_map": dict(recertified_gates) == {"PASS": 80},
        "no_source_rows_market_values_features_outcomes_or_trades": True,
        "no_data_change_acquisition_or_charge": True,
    }
    return {
        "requests": requests,
        "aggregate": {
            "request_count": len(requests),
            "original_quality_gates": dict(sorted(original_gates.items())),
            "recertified_quality_gates": dict(sorted(recertified_gates.items())),
            "unchanged_original_passes": unchanged_passes,
            "diagnosed_requests_recertified": diagnosed,
            "recertified_pass_count": recertified_gates["PASS"],
            "changed_check_counts": dict(sorted(changed_counts.items())),
            "amended_check_maps_sha256": check_maps_hash,
            "source_inventory_ordered_sha256": source_receipt["reproducible_payload"]["source_inventory_ordered_sha256"],
        },
        "formal_integrity_gates": gates,
        "formal_integrity_pass": all(gates.values()),
        "restrictions": {
            "source_rows_or_market_values_accessed": False,
            "features_relationships_signals_execution_or_pnl_calculated": False,
            "data_filtered_repaired_replaced_relabelled_or_reacquired": False,
            "charge_incurred_usd": 0.0,
        },
    }


def _verified_context(remote_root: Path) -> dict[str, Any]:
    _verify_hash(AMENDMENT_PATH, EXPECTED_AMENDMENT_SHA256)
    _verify_hash(FREEZE_PATH, EXPECTED_FREEZE_SHA256)
    _verify_hash(CORRECTION_PATH, EXPECTED_CORRECTION_SHA256)
    amendment = _read_json(AMENDMENT_PATH)
    freeze = _read_json(FREEZE_PATH)
    if freeze["amendment"]["sha256"] != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Freeze no longer binds the amendment")
    paths = amendment["sealed_inputs"]
    for key, record in paths.items():
        if not isinstance(record, dict) or "path" not in record:
            continue
        _verify_file_record(record)
    step5b_manifest = _read_json(Path(paths["step5b_manifest"]["path"]))
    step5b_verdict = _read_json(Path(paths["step5b_verdict"]["path"]))
    acquisition = _read_json(Path(paths["step5b_acquisition_manifest"]["path"]))
    step5b1_manifest = _read_json(Path(paths["step5b1_manifest"]["path"]))
    step5b1_verdict = _read_json(Path(paths["step5b1_verdict"]["path"]))
    step5b1_primary = _read_json(Path(paths["step5b1_primary"]["path"]))
    step5b1_reference = _read_json(Path(paths["step5b1_reference"]["path"]))
    if step5b_manifest["status"] != STEP5B_STATUS or step5b_manifest["manifest_hash"] != STEP5B_MANIFEST_HASH:
        raise ValueError("Step 5B predecessor changed")
    if step5b_verdict["status"] != STEP5B_STATUS:
        raise ValueError("Step 5B verdict changed")
    if step5b1_manifest["status"] != STEP5B1_STATUS or step5b1_manifest["manifest_hash"] != STEP5B1_MANIFEST_HASH:
        raise ValueError("Step 5B.1 predecessor changed")
    if step5b1_verdict["status"] != STEP5B1_STATUS:
        raise ValueError("Step 5B.1 verdict changed")
    if step5b1_primary["reproducible_payload"] != step5b1_reference["reproducible_payload"]:
        raise ValueError("Step 5B.1 independent diagnostics differ")
    return {
        "remote_root": remote_root,
        "amendment": amendment,
        "freeze": freeze,
        "step5b_manifest": step5b_manifest,
        "step5b_verdict": step5b_verdict,
        "acquisition": acquisition,
        "step5b1_manifest": step5b1_manifest,
        "step5b1_verdict": step5b1_verdict,
        "step5b1_primary": step5b1_primary,
        "step5b1_reference": step5b1_reference,
    }


def _assert_amendment_matches_code(amendment: dict[str, Any]) -> None:
    frozen = set(amendment["authorized_changes"]["exact_formal_check_keys"])
    if frozen != AUTHORIZED_CHECKS:
        raise ValueError("Authorized formal-check set changed")
    if amendment["sealed_inputs"]["source_and_normalized_file_records"] != 936:
        raise ValueError("Frozen source-file record count changed")
    if amendment["sealed_inputs"]["provider_requests"] != 80:
        raise ValueError("Frozen request count changed")
    if amendment["unchanged_policy"]["67_previously_passing_requests"] != "RETAIN ORIGINAL FORMAL CHECKS WITHOUT MUTATION":
        raise ValueError("Original-pass preservation rule changed")


def _verified_source_receipt(
    path: Path, context: dict[str, Any]
) -> dict[str, Any]:
    receipt = _read_json(path)
    if receipt["amendment_sha256"] != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Source receipt uses another amendment")
    payload = receipt["reproducible_payload"]
    if payload["status"] != "PASS_SOURCE_SEAL_VERIFICATION" or not payload["formal_pass"]:
        raise ValueError("All 80 source seals have not passed verification")
    if payload["verified_files"] != 936 or payload["verified_provider_requests"] != 80:
        raise ValueError("Source receipt coverage is incomplete")
    return receipt


def _seal(
    context: dict[str, Any],
    source_receipt: dict[str, Any],
    output: Path,
    artifacts: Path,
    report: Path,
) -> None:
    if artifacts.exists():
        raise FileExistsError(f"Refusing to overwrite {artifacts}")
    if report.exists():
        raise FileExistsError(f"Refusing to overwrite {report}")
    primary_path = output / "primary_recertification.json"
    reference_path = output / "reference_recertification.json"
    receipt_path = output / "source_verification.json"
    primary = _read_json(primary_path)
    reference = _read_json(reference_path)
    identical = primary["reproducible_payload"] == reference["reproducible_payload"]
    primary_pass = bool(primary["reproducible_payload"]["formal_integrity_pass"])
    reference_pass = bool(reference["reproducible_payload"]["formal_integrity_pass"])
    source_pass = bool(source_receipt["reproducible_payload"]["formal_pass"])
    if not source_pass:
        status = "FAIL_STEP_5B2_PREDECESSOR_OR_SOURCE_SEAL"
    elif not primary_pass or not reference_pass:
        status = "FAIL_STEP_5B2_RECERTIFICATION_INTEGRITY"
    elif not identical:
        status = "FAIL_STEP_5B2_RECERTIFICATION_REPRODUCTION"
    else:
        status = PASS_STATUS
    aggregate = primary["reproducible_payload"]["aggregate"]
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5B2_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == PASS_STATUS,
        "classification": "VALUE_BLIND_SOURCE_INTEGRITY_RECERTIFICATION_ONLY",
        "research_or_validation_credit": "NONE",
        "completed_at_utc": _utc_now(),
        "historical_step5b_status_preserved": context["step5b_verdict"]["status"],
        "step5b1_status_preserved": context["step5b1_verdict"]["status"],
        "predecessor_verdicts_changed": False,
        "implementation_correction_preserved": True,
        "amendment": _file_record(AMENDMENT_PATH),
        "freeze": _file_record(FREEZE_PATH),
        "tool": _file_record(Path(__file__)),
        "source_verification": _file_record(receipt_path),
        "primary_recertification": _file_record(primary_path),
        "reference_recertification": _file_record(reference_path),
        "source_seal_verification_pass": source_pass,
        "primary_integrity_pass": primary_pass,
        "reference_integrity_pass": reference_pass,
        "independent_recertifications_identical": identical,
        "aggregate": aggregate,
        "all_80_sources_recertified_pass": aggregate["recertified_pass_count"] == 80,
        "recommendation_implemented": "TIMESTAMP_FLAG_AND_OFFICIAL_HOLIDAY_DISPOSITION_V0_1",
        "authorized_check_changes_only": True,
        "data_filtered_repaired_replaced_relabelled_or_reacquired": False,
        "market_values_or_outcomes_accessed_or_reported": False,
        "features_relationships_signals_execution_trades_or_pnl_calculated": False,
        "charge_incurred_usd": 0.0,
        "completion_policy": "Step 5B.2 complete; stop before Step 5C.",
    }
    artifacts.mkdir(parents=True, exist_ok=False)
    verdict_path = artifacts / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_report(report, verdict)
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5B2_MANIFEST_V0_1",
        "status": status,
        "created_at_utc": _utc_now(),
        "amendment": _file_record(AMENDMENT_PATH),
        "freeze": _file_record(FREEZE_PATH),
        "tool": _file_record(Path(__file__)),
        "inputs": [
            _file_record(receipt_path),
            _file_record(primary_path),
            _file_record(reference_path),
        ],
        "artifacts": [_file_record(verdict_path), _file_record(report)],
        "step5b_manifest_hash": STEP5B_MANIFEST_HASH,
        "step5b1_manifest_hash": STEP5B1_MANIFEST_HASH,
        "source_inventory_ordered_sha256": source_receipt["reproducible_payload"]["source_inventory_ordered_sha256"],
        "source_file_records_verified": 936,
        "source_seals_verified": 80,
        "provider_requests_recertified": 80,
        "market_values_or_outcomes_accessed_or_reported": False,
        "manifest_hash": None,
    }
    manifest["manifest_hash"] = _canonical_json_hash({**manifest, "manifest_hash": None})
    _write_json_atomic(artifacts / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B2_SEALED",
                "status": status,
                "source_files_verified": 936,
                "source_seals_verified": 80,
                "recertified_passes": aggregate["recertified_pass_count"],
                "independent_recertifications_identical": identical,
                "market_values_or_outcomes_accessed": False,
                "charge_incurred_usd": 0.0,
            },
            sort_keys=True,
        )
    )


def _verify_seal(
    context: dict[str, Any],
    source_receipt: dict[str, Any],
    artifacts: Path,
    report: Path,
) -> None:
    manifest = _read_json(artifacts / "manifest.json")
    verdict = _read_json(artifacts / "verdict.json")
    expected_manifest_hash = _canonical_json_hash({**manifest, "manifest_hash": None})
    if manifest["manifest_hash"] != expected_manifest_hash:
        raise ValueError("Step 5B.2 manifest hash mismatch")
    for record in (
        manifest["amendment"],
        manifest["freeze"],
        manifest["tool"],
        *manifest["inputs"],
        *manifest["artifacts"],
    ):
        _verify_file_record(record)
    repeated = _verify_all_source_records(context, emit_progress=True)
    if repeated != source_receipt["reproducible_payload"]:
        raise ValueError("Independent source-seal verification did not reproduce")
    if verdict["status"] != manifest["status"] or verdict["status"] != PASS_STATUS:
        raise ValueError("Step 5B.2 did not seal a PASS")
    if verdict["historical_step5b_status_preserved"] != STEP5B_STATUS:
        raise ValueError("Historical Step 5B failure was not preserved")
    if verdict["step5b1_status_preserved"] != STEP5B1_STATUS:
        raise ValueError("Step 5B.1 pass was not preserved")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B2_SEAL_VERIFIED",
                "status": verdict["status"],
                "manifest_hash": manifest["manifest_hash"],
                "source_files_reverified": repeated["verified_files"],
                "source_seals_reverified": repeated["categories"]["source_seal"],
                "independent_recertifications_identical": verdict[
                    "independent_recertifications_identical"
                ],
                "market_values_or_outcomes_accessed": False,
                "charge_incurred_usd": 0.0,
            },
            sort_keys=True,
        )
    )


def _write_report(path: Path, verdict: dict[str, Any]) -> None:
    aggregate = verdict["aggregate"]
    lines = [
        "# GC Microstructure Step 5B.2 — Source-Integrity Recertification",
        "",
        "## Formal verdict",
        "",
        f"`{verdict['status']}`",
        "",
        "## Preserved history",
        "",
        f"- Original Step 5B: `{verdict['historical_step5b_status_preserved']}`.",
        f"- Step 5B.1 diagnostic: `{verdict['step5b1_status_preserved']}`.",
        "- Neither predecessor verdict was changed or overwritten.",
        "",
        "## Value-blind recertification",
        "",
        "- Frozen file records reverified: 936.",
        "- Source seals reverified: 80.",
        f"- Previously passing requests retained unchanged: {aggregate['unchanged_original_passes']}.",
        f"- Diagnosed requests recertified: {aggregate['diagnosed_requests_recertified']}.",
        f"- Final passing requests: {aggregate['recertified_pass_count']} of 80.",
        f"- Independent recertifications identical: `{str(verdict['independent_recertifications_identical']).lower()}`.",
        "",
        "## Authorized changes applied",
        "",
    ]
    for check, count in aggregate["changed_check_counts"].items():
        lines.append(f"- `{check}`: {count} request dispositions changed from false to true.")
    lines.extend(
        [
            "",
            "Every other original formal check remained unchanged.",
            "",
            "## Restrictions honored",
            "",
            "No source or row was filtered, repaired, relabeled, replaced, or "
            "reacquired. No source row, price, depth, size, order-flow value, "
            "outcome, feature, relationship, signal, execution result, trade, "
            "PnL, R multiple, or return was inspected or calculated. No charge "
            "was incurred.",
            "",
            "Step 5B.2 stops here before Step 5C.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.replace(path)


def _file_category(path: Path) -> str:
    normalized = str(path).replace("\\", "/")
    if normalized.endswith("/normalized/seal.json"):
        return "source_seal"
    if normalized.endswith("/normalized/data_quality.json"):
        return "data_quality"
    if normalized.endswith("/normalized/lineage.json"):
        return "lineage"
    if normalized.endswith(".parquet"):
        return "normalized_payload"
    if normalized.endswith(".dbn.zst"):
        return "provider_dbn"
    return "provider_metadata"


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
    path_text = (
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if path.is_relative_to(REPO_ROOT)
        else str(path)
    )
    return {"path": path_text, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _verify_file_record(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if not path.is_absolute():
        path = REPO_ROOT / path
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"Byte-size mismatch for {path}")
    _verify_hash(path, record["sha256"])


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
