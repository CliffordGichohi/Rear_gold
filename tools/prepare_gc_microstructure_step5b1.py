#!/usr/bin/env python3
"""Freeze the value-blind Step 5B.1 source-integrity diagnostic protocol.

This preparation stage reads only sealed JSON metadata and Parquet footers. It
does not read source rows or any price, depth, order-flow, outcome, signal, or
PnL value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b1_protocol_v01.json"
)
INVENTORY_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b1_source_inventory_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b1_freeze_v01.json"
)

EXPECTED_STEP5B_MANIFEST_FILE_SHA256 = (
    "0a4abebcc8957568d33b734d7511481c0203a73e7cb7cacfc4a89c933a21c6f9"
)
EXPECTED_STEP5B_MANIFEST_HASH = (
    "6b4074aa95953232db878027aa0dc85666c478f4abd80e864022e61fded46683"
)
EXPECTED_STEP5B_VERDICT_FILE_SHA256 = (
    "2ee53fb8169bc1b47f38011cd2600ad74dec37404e806c1dd5a0ba0cbc2ce4bb"
)
EXPECTED_ACQUISITION_MANIFEST_SHA256 = (
    "b4e64d508790364dbd400da1478b139bb643d2b7afc9c97ff6691958365c5ccc"
)
EXPECTED_QUALITY_SUMMARY_SHA256 = (
    "f9cafd05800df50513d5357ea8c5e23f75f44038cdd12bd32e9795699cc88bab"
)
EXPECTED_VERIFY_LOG_SHA256 = (
    "1256ef75137d68416c89c2b9f4f56c881659be58787e317d9a004ade955521d1"
)
EXPECTED_STEP5B_STATUS = "FAIL_STEP_5B_BUDGET_C_SOURCE_INTEGRITY"
EXPECTED_FAILED_REQUESTS = (
    "Q007:mbo",
    "Q008:mbp-10",
    "Q017:mbo",
    "Q018:mbp-10",
    "Q035:mbo",
    "Q037:mbo",
    "Q039:mbo",
    "Q041:mbo",
    "Q043:mbo",
    "Q045:mbo",
    "Q063:mbo",
    "Q077:mbo",
    "Q083:mbo",
)
EXPECTED_FAILED_ROWS = 144_352_215
EXPECTED_RECEIVE_BEFORE_EVENT_ROWS = 719_524
EXPECTED_BAD_TS_RECV_OLD_RULE_VIOLATIONS = 174
EXPECTED_INCOMPLETE_WINDOWS = 4
EXPECTED_SCHEMA_FAILURES = {"mbo": 11, "mbp-10": 2}
REQUIRED_COLUMNS = {
    "source_file_index",
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "rtype",
    "publisher_id",
    "instrument_id",
    "action",
    "side",
    "flags",
    "ts_in_delta",
    "sequence",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--remote-root", default="/home/wapi/rear_gold_step5b_v01"
    )
    args = parser.parse_args()
    prepare(Path(args.remote_root))


def prepare(remote_root: Path) -> None:
    for target in (INVENTORY_PATH, PROTOCOL_PATH, FREEZE_PATH):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite frozen artifact: {target}")

    final_root = remote_root / "artifacts/step5b_budget_c_final"
    verdict_path = final_root / "verdict.json"
    manifest_path = final_root / "manifest.json"
    acquisition_path = (
        remote_root
        / "data/databento_gc_microstructure_budget_c_v01/acquisition_manifest.json"
    )
    quality_summary_path = remote_root / "artifacts/budget_c_quality_summary.json"
    verify_log_path = remote_root / "artifacts/budget_c_verify.log"

    expected_files = {
        manifest_path: EXPECTED_STEP5B_MANIFEST_FILE_SHA256,
        verdict_path: EXPECTED_STEP5B_VERDICT_FILE_SHA256,
        acquisition_path: EXPECTED_ACQUISITION_MANIFEST_SHA256,
        quality_summary_path: EXPECTED_QUALITY_SUMMARY_SHA256,
        verify_log_path: EXPECTED_VERIFY_LOG_SHA256,
    }
    for path, expected in expected_files.items():
        _verify_hash(path, expected)

    verdict = _read_json(verdict_path)
    manifest = _read_json(manifest_path)
    acquisition = _read_json(acquisition_path)
    summary = _read_json(quality_summary_path)
    if verdict.get("status") != EXPECTED_STEP5B_STATUS:
        raise ValueError("Step 5B verdict changed")
    if manifest.get("manifest_hash") != EXPECTED_STEP5B_MANIFEST_HASH:
        raise ValueError("Step 5B manifest hash changed")
    if manifest.get("status") != EXPECTED_STEP5B_STATUS:
        raise ValueError("Step 5B manifest status changed")
    if int(verdict.get("quality_pass_count", -1)) != 67:
        raise ValueError("Step 5B passing source count changed")
    if summary.get("market_values_or_outcomes_accessed") is not False:
        raise ValueError("Step 5B quality summary value-access declaration changed")

    failures = {item["request_id"]: item for item in summary["failures"]}
    if tuple(sorted(failures)) != tuple(sorted(EXPECTED_FAILED_REQUESTS)):
        raise ValueError("The frozen set of 13 failed requests changed")

    request_map = {item["request_id"]: item for item in acquisition["requests"]}
    inventory_rows: list[dict[str, Any]] = []
    total_rows = 0
    total_receive_before = 0
    total_bad_violations = 0
    total_incomplete = 0
    schema_failures: dict[str, int] = {"mbo": 0, "mbp-10": 0}

    for request_id in EXPECTED_FAILED_REQUESTS:
        request = request_map[request_id]
        normalization = request["normalization"]
        parquet_record = normalization["normalized_payload"]
        quality_record = normalization["data_quality"]
        lineage_record = normalization["lineage"]
        seal_record = normalization["seal"]
        for record in (parquet_record, quality_record, lineage_record, seal_record):
            _verify_hash(Path(record["path"]), record["sha256"])

        parquet = Path(parquet_record["path"])
        parquet_file = pq.ParquetFile(parquet)
        schema_names = parquet_file.schema_arrow.names
        missing = sorted(REQUIRED_COLUMNS.difference(schema_names))
        if missing:
            raise ValueError(f"{request_id} missing diagnostic columns: {missing}")
        footer_rows = int(parquet_file.metadata.num_rows)
        quality = _read_json(Path(quality_record["path"]))
        lineage = _read_json(Path(lineage_record["path"]))
        base = quality["base_normalizer_quality"]
        supplemental = quality["supplemental_validation"]
        failed_checks = sorted(
            key for key, value in quality["formal_checks"].items() if not value
        )
        if failed_checks != sorted(failures[request_id]["failed_checks"]):
            raise ValueError(f"{request_id} failed-gate set changed")
        if footer_rows != int(supplemental["record_count"]):
            raise ValueError(f"{request_id} footer row count differs from seal")
        if lineage["request_id"] != request_id:
            raise ValueError(f"{request_id} lineage request ID changed")

        receive_before = int(base.get("receive_before_event_records", 0))
        bad_violations = int(
            supplemental["bad_ts_recv_snapshot_semantic_violations"]
        )
        incomplete = int(supplemental["incomplete_prediction_window_count"])
        schema_failures[request["schema"]] += 1
        total_rows += footer_rows
        total_receive_before += receive_before
        total_bad_violations += bad_violations
        total_incomplete += incomplete
        inventory_rows.append(
            {
                "request_id": request_id,
                "schema": request["schema"],
                "selected_dates": request["selected_dates"],
                "selected_date_rows": request["selected_date_rows"],
                "expected_instrument_id_by_date": request[
                    "expected_instrument_id_by_date"
                ],
                "request": request["request"],
                "job_id": request["job_id"],
                "normalized_payload": parquet_record,
                "quality": quality_record,
                "lineage": lineage_record,
                "source_seal": seal_record,
                "source_seal_hash": normalization["seal_hash"],
                "footer_record_count": footer_rows,
                "parquet_schema_names": schema_names,
                "failed_checks": failed_checks,
                "sealed_expected_counts": {
                    "receive_before_event_rows": receive_before,
                    "bad_ts_recv_old_snapshot_rule_violations": bad_violations,
                    "incomplete_prediction_windows": incomplete,
                },
                "sealed_prediction_window_coverage": supplemental[
                    "prediction_window_coverage"
                ],
                "source_rows_accessed_during_preparation": False,
                "market_values_accessed_or_reported": False,
            }
        )

    if total_rows != EXPECTED_FAILED_ROWS:
        raise ValueError("Failed-request row total changed")
    if total_receive_before != EXPECTED_RECEIVE_BEFORE_EVENT_ROWS:
        raise ValueError("Receive-before-event total changed")
    if total_bad_violations != EXPECTED_BAD_TS_RECV_OLD_RULE_VIOLATIONS:
        raise ValueError("BAD_TS_RECV violation total changed")
    if total_incomplete != EXPECTED_INCOMPLETE_WINDOWS:
        raise ValueError("Incomplete prediction-window total changed")
    if schema_failures != EXPECTED_SCHEMA_FAILURES:
        raise ValueError("Failed schema counts changed")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    inventory = {
        "version": "GC_MICROSTRUCTURE_STEP_5B1_SOURCE_INVENTORY_V0_1",
        "status": "SEALED_METADATA_ONLY_SOURCE_INVENTORY",
        "created_at_utc": now,
        "classification": "SOURCE_INTEGRITY_DIAGNOSTIC_ONLY",
        "research_or_validation_credit": "NONE",
        "predecessor_step5b_status_preserved": EXPECTED_STEP5B_STATUS,
        "failed_request_count": len(inventory_rows),
        "schema_failure_counts": schema_failures,
        "total_source_rows": total_rows,
        "sealed_expected_receive_before_event_rows": total_receive_before,
        "sealed_expected_bad_ts_recv_old_snapshot_rule_violations": total_bad_violations,
        "sealed_expected_incomplete_prediction_windows": total_incomplete,
        "sources": inventory_rows,
        "parquet_footer_access_only": True,
        "source_rows_accessed": False,
        "market_values_or_outcomes_accessed_or_reported": False,
    }
    _write_json_atomic(INVENTORY_PATH, inventory)
    inventory_record = _file_record(INVENTORY_PATH)

    protocol = _build_protocol(
        now=now,
        remote_root=remote_root,
        inventory_record=inventory_record,
        expected_files=expected_files,
        inventory=inventory,
    )
    _write_json_atomic(PROTOCOL_PATH, protocol)
    protocol_record = _file_record(PROTOCOL_PATH)

    freeze = {
        "version": "GC_MICROSTRUCTURE_STEP_5B1_FREEZE_V0_1",
        "status": "DIAGNOSTIC_PROTOCOL_SEALED_BEFORE_ROW_LEVEL_ACCESS",
        "sealed_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "classification": "SOURCE_INTEGRITY_DIAGNOSTIC_ONLY",
        "research_or_validation_credit": "NONE",
        "protocol": protocol_record,
        "source_inventory": inventory_record,
        "preparation_tool": _file_record(Path(__file__)),
        "pre_freeze_verification": {
            "step5b_status": EXPECTED_STEP5B_STATUS,
            "step5b_manifest_hash": EXPECTED_STEP5B_MANIFEST_HASH,
            "failed_request_count": 13,
            "failed_request_normalized_payload_hashes_verified": 13,
            "failed_request_quality_lineage_and_seal_hashes_verified": 39,
            "parquet_footer_record_counts_verified": 13,
            "source_rows_accessed": False,
            "market_values_or_outcomes_accessed_or_reported": False,
        },
        "frozen_scope": {
            "diagnostic_taxonomy_frozen": True,
            "timestamp_tests_frozen": True,
            "bad_ts_recv_tests_frozen": True,
            "calendar_coverage_tests_frozen": True,
            "classification_precedence_frozen": True,
            "independent_reproduction_requirements_frozen": True,
            "maximum_recommendations": 1,
            "correction_or_recertification_implementation_permitted": False,
        },
        "prohibited_work_not_started": {
            "data_repair_filter_replacement_or_reacquisition": False,
            "feature_calculation": False,
            "market_value_or_outcome_inspection": False,
            "relationship_or_signal_testing": False,
            "execution_optimization": False,
            "trades_pnl_or_returns": False,
            "paid_request": False,
        },
    }
    _write_json_atomic(FREEZE_PATH, freeze)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B1_PROTOCOL_FROZEN",
                "protocol_sha256": protocol_record["sha256"],
                "inventory_sha256": inventory_record["sha256"],
                "freeze_sha256": _sha256(FREEZE_PATH),
                "failed_requests": 13,
                "source_rows_accessed": False,
                "market_values_or_outcomes_accessed": False,
                "charge_incurred_usd": 0.0,
            },
            sort_keys=True,
        )
    )


def _build_protocol(
    *,
    now: str,
    remote_root: Path,
    inventory_record: dict[str, Any],
    expected_files: dict[Path, str],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": "GC_MICROSTRUCTURE_STEP_5B1_PROTOCOL_V0_1",
        "status": "FROZEN_BEFORE_ROW_LEVEL_ACCESS",
        "frozen_at_utc": now,
        "classification": "SOURCE_INTEGRITY_DIAGNOSTIC_ONLY",
        "research_or_validation_credit": "NONE",
        "purpose": (
            "Classify only the three frozen Step 5B source-integrity failure "
            "families using technical metadata, without changing any source "
            "or calculating research features or outcomes."
        ),
        "predecessor_preservation": {
            "required_step5b_status": EXPECTED_STEP5B_STATUS,
            "required_step5b_manifest_hash": EXPECTED_STEP5B_MANIFEST_HASH,
            "required_step5b_quality_pass_count": 67,
            "required_step5b_failed_request_count": 13,
            "all_step5b_and_earlier_artifacts_immutable": True,
            "formal_step5b_failure_remains_unchanged": True,
        },
        "sealed_inputs": {
            "remote_root": str(remote_root),
            "predecessor_files": [
                {"path": str(path), "sha256": sha256}
                for path, sha256 in expected_files.items()
            ],
            "source_inventory": inventory_record,
            "failed_request_ids_in_order": list(EXPECTED_FAILED_REQUESTS),
            "failed_request_rows": EXPECTED_FAILED_ROWS,
            "expected_receive_before_event_rows": (
                EXPECTED_RECEIVE_BEFORE_EVENT_ROWS
            ),
            "expected_bad_ts_recv_old_snapshot_rule_violations": (
                EXPECTED_BAD_TS_RECV_OLD_RULE_VIOLATIONS
            ),
            "expected_incomplete_prediction_windows": (
                EXPECTED_INCOMPLETE_WINDOWS
            ),
            "source_substitution_or_reacquisition_permitted": False,
        },
        "official_semantics_registry": {
            "databento_common_fields": {
                "url": (
                    "https://databento.com/docs/standards-and-conventions/"
                    "common-fields-enums-types"
                ),
                "frozen_facts": [
                    "ts_recv is the Databento capture-server receive timestamp.",
                    "ts_event is the publisher matching-engine event timestamp.",
                    "ts_in_delta is ts_recv minus the publisher sending timestamp.",
                    "ts_in_delta may be negative because publisher and Databento clocks need not be synchronized.",
                    "F_BAD_TS_RECV bit 8 means ts_recv is inaccurate due to clock issues or packet reordering.",
                    "F_SNAPSHOT bit 32 identifies replay or snapshot messages.",
                    "F_LAST bit 128 marks the final record in one native event for an instrument.",
                ],
            },
            "databento_mbo_snapshot": {
                "url": (
                    "https://databento.com/docs/standards-and-conventions/"
                    "mbo-snapshot"
                ),
                "frozen_facts": [
                    "Historical MBO snapshots are synthetic day-start recovery state.",
                    "Snapshot records carry F_SNAPSHOT and F_BAD_TS_RECV.",
                    "A snapshot starts with action R and continues with zero or more action A rows.",
                    "Snapshot ts_recv is the snapshot generation timestamp while ts_event is preserved.",
                ],
            },
            "databento_glbx_mdp3": {
                "url": (
                    "https://databento.com/docs/venues-and-datasets/glbx-mdp3"
                ),
                "frozen_fact": (
                    "GLBX.MDP3 contains CME Group MDP 3.0 publisher timestamps "
                    "and Databento capture timestamps without adjusting the "
                    "publisher timestamp domain."
                ),
            },
            "cme_2022_metals_calendar": {
                "url": (
                    "https://www.cmegroup.com/trading/metals/files/"
                    "metals-prod-guide-2022.pdf"
                ),
                "frozen_fact": "2022-04-15 is marked as the Good Friday CME Group holiday.",
            },
            "cme_2022_good_friday_advisory": {
                "url": (
                    "https://www.cmegroup.com/tools-information/holiday-calendar/"
                    "files/2022-good-friday-advisory.pdf"
                ),
                "frozen_fact": "The advisory identifies 2022-04-15 as the Good Friday holiday.",
            },
            "cme_2022_good_friday_settlement_notice": {
                "url": (
                    "https://www.cmegroup.com/tools-information/holiday-calendar/"
                    "files/good-friday-holiday-settlement-times-2022.pdf"
                ),
                "frozen_fact": (
                    "CME states it would not derive or disseminate CME, CBOT, "
                    "NYMEX, or COMEX settlement prices on 2022-04-15."
                ),
            },
        },
        "constants": {
            "flag_bad_ts_recv": 8,
            "flag_snapshot": 32,
            "flag_last": 128,
            "int32_min": -2_147_483_648,
            "int32_max": 2_147_483_647,
            "allowed_actions": ["A", "C", "M", "T", "F", "R", "N"],
            "historical_snapshot_actions": ["A", "R"],
            "expected_publisher_id": 1,
            "timestamp_authority": "ts_recv",
            "timezone": "UTC",
            "market_state_timezone": "America/Chicago",
            "market_state_windows_local": {
                "MAINTENANCE": "16:00:00 inclusive to 16:45:00 exclusive",
                "PRE_OPEN": "16:45:00 inclusive to 17:00:00 exclusive",
                "CONTINUOUS_MATCHING": "all remaining UTC-day times",
            },
            "native_event_group_key": [
                "publisher_id",
                "instrument_id",
                "sequence",
            ],
        },
        "receive_before_event_diagnostic": {
            "scope": (
                "Every row in the ten failed MBO requests satisfying "
                "ts_recv < ts_event; exactly 719,524 rows must be reproduced."
            ),
            "per_row_fields_permitted": [
                "source_file_index",
                "source_row_ordinal",
                "ts_recv",
                "ts_event",
                "publisher_id",
                "instrument_id",
                "action",
                "side",
                "flags",
                "ts_in_delta",
                "sequence",
            ],
            "derived_metadata": {
                "receive_event_lead_ns": "ts_event - ts_recv, strictly positive",
                "publisher_send_ns": "ts_recv - ts_in_delta",
                "event_to_send_ns": "publisher_send_ns - ts_event",
            },
            "exclusive_row_taxonomy_in_precedence_order": [
                {
                    "id": "RB_STRUCTURAL_INVALID",
                    "rule": (
                        "Wrong publisher or date-mapped instrument, unknown "
                        "action, timestamp outside the frozen request by "
                        "ts_recv, event at/after request end, or undefined "
                        "required metadata."
                    ),
                    "disposition": "GENUINE_SOURCE_FAILURE",
                },
                {
                    "id": "RB_FLAGGED_BAD_TS_RECV",
                    "rule": (
                        "F_BAD_TS_RECV is set after structural validity; the "
                        "official flag explicitly documents inaccurate ts_recv "
                        "from clock issues or packet reordering."
                    ),
                    "disposition": "DOCUMENTED_VALID_SEMANTICS",
                },
                {
                    "id": "RB_UNFLAGGED_CLAMPED_TS_IN_DELTA",
                    "rule": (
                        "F_BAD_TS_RECV is not set and ts_in_delta equals "
                        "INT32_MIN or INT32_MAX."
                    ),
                    "disposition": "UNRESOLVED",
                },
                {
                    "id": "RB_UNFLAGGED_NEGATIVE_DELTA_COHERENT",
                    "rule": (
                        "F_BAD_TS_RECV is not set, ts_in_delta is negative, "
                        "and derived publisher_send_ns is at or after ts_event."
                    ),
                    "disposition": "DOCUMENTED_VALID_SEMANTICS",
                },
                {
                    "id": "RB_UNFLAGGED_TIMESTAMP_INCOHERENT",
                    "rule": (
                        "All remaining structurally valid unflagged rows, "
                        "including nonnegative ts_in_delta or publisher send "
                        "time preceding event time."
                    ),
                    "disposition": "GENUINE_SOURCE_FAILURE",
                },
            ],
            "required_cross_tabs": [
                "request and trade date",
                "action and side",
                "exact flags integer and snapshot/reset booleans",
                "market state",
                "receive-event lead bins",
                "exclusive row taxonomy",
                "native-event group size, target-row count, F_LAST count, and contiguity",
            ],
            "lead_bins_ns": [
                "1_TO_1K",
                "1K_TO_10K",
                "10K_TO_100K",
                "100K_TO_1M",
                "GT_1M",
            ],
            "finding_rule": (
                "DOCUMENTED_VALID_SEMANTICS only if every occurrence is in a "
                "documented-valid row class and all source/group integrity "
                "tests pass; GENUINE_SOURCE_FAILURE if any genuine class "
                "occurs; otherwise UNRESOLVED."
            ),
        },
        "bad_ts_recv_diagnostic": {
            "scope": (
                "Exactly the 174 F_BAD_TS_RECV rows that violated the former "
                "snapshot-only Step 5B rule, while scanning all F_BAD_TS_RECV "
                "rows for denominator and exhaustiveness checks."
            ),
            "old_rule_reproduction": (
                "F_BAD_TS_RECV and any of: not F_SNAPSHOT, ts_recv not UTC "
                "day start, ts_event at/after day start, ts_event after "
                "ts_recv, or action outside A/R."
            ),
            "exclusive_violation_taxonomy_in_precedence_order": [
                {
                    "id": "BAD_STRUCTURAL_INVALID",
                    "rule": (
                        "Wrong publisher/date-mapped instrument, unknown action, "
                        "or timestamp outside the frozen request."
                    ),
                    "disposition": "GENUINE_SOURCE_FAILURE",
                },
                {
                    "id": "BAD_SNAPSHOT_CONTRADICTION",
                    "rule": (
                        "F_SNAPSHOT is set but the documented historical "
                        "snapshot structure fails day-start receive, preserved "
                        "event not after receive, or A/R action semantics."
                    ),
                    "disposition": "GENUINE_SOURCE_FAILURE",
                },
                {
                    "id": "BAD_NON_SNAPSHOT_DOCUMENTED",
                    "rule": (
                        "F_SNAPSHOT is not set and structural validity passes; "
                        "the general F_BAD_TS_RECV definition documents the "
                        "receive timestamp issue without requiring a snapshot."
                    ),
                    "disposition": "DOCUMENTED_VALID_SEMANTICS",
                },
                {
                    "id": "BAD_OTHER_UNRESOLVED",
                    "rule": "Any remaining old-rule violation.",
                    "disposition": "UNRESOLVED",
                },
            ],
            "required_cross_tabs": [
                "request and schema",
                "snapshot boolean",
                "action and side",
                "flags integer",
                "market state",
                "overlap with receive-before-event scope",
                "exclusive violation taxonomy",
            ],
            "finding_rule": (
                "DOCUMENTED_VALID_SEMANTICS only if all 174 violations are "
                "BAD_NON_SNAPSHOT_DOCUMENTED and every denominator and "
                "structural check passes; GENUINE_SOURCE_FAILURE if any "
                "genuine class occurs; otherwise UNRESOLVED."
            ),
        },
        "calendar_coverage_diagnostic": {
            "scope": (
                "The four sealed incomplete windows: London and New York in "
                "Q017:mbo and Q018:mbp-10 on 2022-04-15."
            ),
            "required_tests": [
                "Reproduce exactly four and no other incomplete windows.",
                "Confirm 2022-04-15 is the official CME Good Friday holiday using the frozen official registry.",
                "Confirm the daily DBN file exists and its hash is sealed for both schemas.",
                "Confirm provider record counts, normalized row counts, source ordering, and date-mapped instrument lineage remain sealed.",
                "Using ts_recv only, count rows in each frozen 15-minute lookback and through each cutoff without reading market values.",
                "Confirm every 2022-04-11 through 2022-04-14 London and New York window remains complete.",
                "Confirm both schemas independently show no qualifying coverage for the two Good Friday windows.",
            ],
            "finding_rules": {
                "EXPECTED_CALENDAR_UNAVAILABILITY": (
                    "All tests pass and the only four incomplete windows are "
                    "the two sessions in both schemas on the official holiday."
                ),
                "GENUINE_SOURCE_FAILURE": (
                    "A required open-session window is absent or a sealed "
                    "source/file/completeness fact fails."
                ),
                "UNRESOLVED": (
                    "Official calendar evidence or technical coverage is "
                    "insufficient for an exact disposition."
                ),
            },
        },
        "request_classification": {
            "exclusive_classes": [
                "DOCUMENTED_VALID_SEMANTICS",
                "EXPECTED_CALENDAR_UNAVAILABILITY",
                "GENUINE_SOURCE_FAILURE",
                "UNRESOLVED",
            ],
            "precedence": [
                "GENUINE_SOURCE_FAILURE",
                "UNRESOLVED",
                "EXPECTED_CALENDAR_UNAVAILABILITY",
                "DOCUMENTED_VALID_SEMANTICS",
            ],
            "rules": {
                "GENUINE_SOURCE_FAILURE": "Any applicable diagnostic family returns GENUINE_SOURCE_FAILURE.",
                "UNRESOLVED": "No genuine failure exists and any applicable family is UNRESOLVED, or valid and calendar dispositions are mixed within one request.",
                "EXPECTED_CALENDAR_UNAVAILABILITY": "Every applicable family returns only EXPECTED_CALENDAR_UNAVAILABILITY.",
                "DOCUMENTED_VALID_SEMANTICS": "Every applicable family returns only DOCUMENTED_VALID_SEMANTICS.",
            },
        },
        "technical_output_policy": {
            "permitted": [
                "counts and boolean classifications",
                "timestamp relation and elapsed-nanosecond bins",
                "flags, actions, sides, sequence and event-group metadata",
                "snapshot/reset and market-state classes",
                "instrument identifiers and date mappings",
                "technical session-window coverage",
                "hashed row and group identities",
                "checksums and source lineage",
            ],
            "prohibited": [
                "price or price-derived values",
                "depth, size, order count, imbalance, or order-flow values",
                "market outcomes or directional relationships",
                "features, signals, candidates, execution, trades, PnL, R multiples, or returns",
            ],
            "row_identity_hash": (
                "SHA-256 over request ID, source file index, source row "
                "ordinal, ts_recv, ts_event, publisher ID, instrument ID, "
                "action, side, flags, ts_in_delta, and sequence in canonical "
                "UTF-8 pipe-delimited source order."
            ),
            "no_raw_timestamp_or_row_identity_emission": True,
        },
        "independent_reproduction": {
            "primary": (
                "PyArrow Parquet batch scan with NumPy masks and run-length "
                "native-event grouping."
            ),
            "reference": (
                "Independent PyArrow Dataset scan converted to pandas with "
                "separately coded predicates and group-boundary handling."
            ),
            "each_implementation_reads": (
                "Every row of all 13 failed normalized sources, selecting only "
                "the frozen technical metadata columns."
            ),
            "identical_required": [
                "all source row counts",
                "719,524 receive-before-event occurrence count",
                "174 old snapshot-rule violation count",
                "four incomplete-window classifications",
                "all exclusive taxonomies and cross-tabs",
                "ordered target-row identity checksums",
                "native-event grouping counts and checksums",
                "per-request and aggregate classifications",
                "recommendation or NONE",
            ],
            "any_difference": "FAIL_STEP_5B1_DIAGNOSTIC_REPRODUCTION",
        },
        "recommendation_rule": {
            "maximum_recommendations": 1,
            "all_requests_explained_without_genuine_or_unresolved": {
                "recommendation_id": (
                    "TIMESTAMP_FLAG_AND_OFFICIAL_HOLIDAY_DISPOSITION_V0_1"
                ),
                "bounded_text": (
                    "In a separately authorized recertification only: accept "
                    "structurally valid F_BAD_TS_RECV live rows under the "
                    "general provider flag semantics; accept structurally "
                    "valid unflagged ts_recv-before-ts_event rows only when "
                    "negative, unclamped ts_in_delta yields publisher send "
                    "time at/after event time; and mark the four 2022-04-15 "
                    "London/New York windows unavailable under the official "
                    "Good Friday calendar. Keep every other Step 5B source, "
                    "feature definition, and integrity gate unchanged."
                ),
            },
            "otherwise": "NONE",
            "implementation_in_step5b1_permitted": False,
        },
        "formal_gates": {
            "step5b_and_relevant_source_seals_valid": True,
            "exactly_13_failed_requests_processed": True,
            "all_144352215_rows_scanned_by_each_implementation": True,
            "all_frozen_occurrence_counts_reproduced": True,
            "every_target_row_classified_exactly_once": True,
            "every_failed_request_classified_exactly_once": True,
            "official_calendar_evidence_bound": True,
            "primary_and_reference_outputs_identical": True,
            "at_most_one_recommendation": True,
            "no_prohibited_values_or_work": True,
        },
        "status_precedence": [
            "FAIL_STEP_5B1_PREDECESSOR_OR_SOURCE_INTEGRITY",
            "FAIL_STEP_5B1_DIAGNOSTIC_INTEGRITY",
            "FAIL_STEP_5B1_DIAGNOSTIC_REPRODUCTION",
            "PASS_STEP_5B1_DIAGNOSTIC_REPRODUCTION",
        ],
        "prohibited": [
            "modifying any Step 5B or earlier verdict, seal, or source",
            "filtering, repairing, relabeling, replacing, or reacquiring data",
            "incurring a charge or using another account",
            "reading or reporting price, depth, size, order-flow, or outcome values",
            "calculating features, relationships, candidates, signals, or directional outcomes",
            "optimizing execution or calculating trades, PnL, R multiples, or returns",
            "implementing the recommendation or recertifying Step 5B",
        ],
        "completion_policy": (
            "Classify all 13 failed requests, independently reproduce the "
            "diagnostic, recommend at most one bounded value-blind amendment, "
            "seal Step 5B.1, and stop."
        ),
        "preparation_audit": {
            "inventory_failed_request_count": inventory["failed_request_count"],
            "source_rows_accessed": False,
            "market_values_or_outcomes_accessed_or_reported": False,
            "charge_incurred_usd": 0.0,
        },
    }


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


if __name__ == "__main__":
    main()
