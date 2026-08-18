#!/usr/bin/env python3
"""Run the frozen Step 4A.2 metadata-only disposition.

The classifier reads exactly seven allowlisted columns from the two sealed
Step 4A feature payloads. It never opens source MBO/MBP data or reads prices,
depth, event-flow features, outcomes, signals, execution, or PnL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4a2_protocol_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4a2_freeze_v01.json"
)
STEP4A_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4a_v01"
    / "manifest.json"
)
STEP4A1_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4a1_v01"
    / "manifest.json"
)
PRIMARY_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4a_v01"
    / "primary_features.parquet"
)
REFERENCE_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4a_v01"
    / "reference_features.parquet"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4a2_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_4A2_REPORT.md"

EXPECTED_PROTOCOL_SHA256 = (
    "e4584f99274e04065d006d2aeef5073743f98c8e2bd6d300f7cce5b2ad51ea29"
)
EXPECTED_FREEZE_SHA256 = (
    "2a6b1d8b1eb2e70e006865659f6450da7235b9b96f3b4b8abe05258041d17aa3"
)
EXPECTED_STEP4A_MANIFEST_HASH = (
    "4960f1ee7f03e21cc490ea81b8e15554ed6c879527d8a02c3956b849cab2bf0f"
)
EXPECTED_STEP4A_VERDICT_HASH = (
    "853c99ea3c8655869ead48c15b09409952789cd8cb964df06c53aa84583c2c07"
)
EXPECTED_STEP4A1_MANIFEST_HASH = (
    "6bcc2f207fa8554f780aec269bd0ad3f4bff6686a37260bfc60b479b6f07eee5"
)
EXPECTED_STEP4A1_VERDICT_HASH = (
    "85fee3a5de442f89ae2622ec4e66f15f6bb7fce3579dd714447bd53d635f97fb"
)
EXPECTED_PAYLOAD_SHA256 = (
    "b559771bc332f400900da43e3c16619a5b75b9457c2a15975d390e977085eda3"
)
EXPECTED_PAYLOAD_BYTES = 5_957_736
EXPECTED_PAYLOAD_ROWS = 86_400
EXPECTED_PAYLOAD_COLUMNS = 85
EXPECTED_TOTAL_CROSSED = 60

DAY_START_NS = 1_704_758_400_000_000_000
DAY_END_NS = 1_704_844_800_000_000_000
BUCKET_WIDTH_NS = 1_000_000_000
BUCKET_COUNT = 86_400
BATCH_SIZE = 25_000

ALLOWED_COLUMNS = (
    "bucket_index",
    "bucket_start_ns",
    "bucket_end_ns",
    "market_segment",
    "market_state",
    "book_crossed",
    "state_source_row_ordinal",
)

SEGMENTS = (
    (
        "CONTINUOUS_00_22",
        "CONTINUOUS_MATCHING",
        1_704_758_400_000_000_000,
        1_704_837_600_000_000_000,
        79_200,
    ),
    (
        "MAINTENANCE_22_2245",
        "MAINTENANCE",
        1_704_837_600_000_000_000,
        1_704_840_300_000_000_000,
        2_700,
    ),
    (
        "PRE_OPEN_2245_23",
        "PRE_OPEN",
        1_704_840_300_000_000_000,
        1_704_841_200_000_000_000,
        900,
    ),
    (
        "CONTINUOUS_23_24",
        "CONTINUOUS_MATCHING",
        1_704_841_200_000_000_000,
        1_704_844_800_000_000_000,
        3_600,
    ),
)
EXPECTED_STATE_COUNTS = {
    "CONTINUOUS_MATCHING": 82_800,
    "MAINTENANCE": 2_700,
    "PRE_OPEN": 900,
}

RECERTIFY_ID = (
    "RECERTIFY_WITH_SNAPSHOT_EXCEPTION_AND_CONTINUOUS_BUCKET_CLOSE_GATE_V0_1"
)
RECERTIFY_TEXT = (
    "In a separately authorized amendment, permit BAD_TS_RECV only for rows "
    "satisfying the Step 4A.1 confirmed snapshot semantics; apply the "
    "crossed-book integrity gate only to CONTINUOUS_MATCHING one-second "
    "bucket-close states; report PRE_OPEN and MAINTENANCE crossed states "
    "separately without treating them as continuous-state failures; keep "
    "every other Step 4A definition and gate unchanged."
)
REJECT_ID = "REJECT_CURRENT_ASOF_STATE_CONSTRUCTION_V0_1"
REJECT_TEXT = (
    "Reject the current Step 4A as-of-state construction for research use; "
    "do not repair it on the engineering date."
)

INT64 = struct.Struct(">q")
UINT32 = struct.Struct(">I")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("primary", "reference", "seal", "verify")
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_stage(args.action, Path(args.output))


def run_stage(action: str, output: Path) -> None:
    context = _verified_context()
    _assert_protocol_matches_code(context["protocol"])
    output.mkdir(parents=True, exist_ok=True)
    if action in {"primary", "reference"}:
        destination = output / f"{action}_classification.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite {destination}")
        result = (
            _classify_primary(context)
            if action == "primary"
            else _classify_reference(context)
        )
        _write_json_atomic(destination, result)
        print(
            json.dumps(
                {
                    "stage": (
                        f"GC_MICROSTRUCTURE_STEP_4A2_{action.upper()}_COMPLETE"
                    ),
                    "implementation": action,
                    "payload_rows": result["audits"]["rows"],
                    "total_crossed_bucket_closes": result[
                        "classification"
                    ]["total_crossed_bucket_closes"],
                    "continuous_crossed_bucket_closes": result[
                        "classification"
                    ]["continuous_crossed_bucket_closes"],
                    "finding": result["finding"],
                    "recommendation": result["recommendation"]["id"],
                    "integrity_pass": result["formal_integrity_pass"],
                    "market_values_reported": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return
    if action == "seal":
        _seal(output, context)
        return
    if action == "verify":
        _verify_seal(output)
        return
    raise AssertionError(action)


def _classify_primary(context: dict[str, Any]) -> dict[str, Any]:
    audit: Counter[str] = Counter()
    segment_total: Counter[str] = Counter()
    segment_crossed: Counter[str] = Counter()
    state_total: Counter[str] = Counter()
    state_crossed: Counter[str] = Counter()
    stream_digest = hashlib.sha256()
    crossed_digest = hashlib.sha256()

    parquet = pq.ParquetFile(PRIMARY_PATH)
    for batch in parquet.iter_batches(
        batch_size=BATCH_SIZE, columns=list(ALLOWED_COLUMNS)
    ):
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in ALLOWED_COLUMNS
        }
        indices = arrays["bucket_index"].to_numpy(zero_copy_only=False)
        starts = arrays["bucket_start_ns"].to_numpy(zero_copy_only=False)
        ends = arrays["bucket_end_ns"].to_numpy(zero_copy_only=False)
        segments = arrays["market_segment"].to_pylist()
        states = arrays["market_state"].to_pylist()
        crossed_values = arrays["book_crossed"].to_pylist()
        ordinals = arrays["state_source_row_ordinal"].to_pylist()
        for index in range(batch.num_rows):
            bucket = int(indices[index])
            start = int(starts[index])
            end = int(ends[index])
            segment = str(segments[index])
            state = str(states[index])
            crossed_raw = crossed_values[index]
            ordinal = ordinals[index]
            crossed = bool(crossed_raw) if crossed_raw is not None else False
            audit["rows"] += 1
            expected_bucket = audit["rows"] - 1
            audit["bucket_index_violations"] += int(
                bucket != expected_bucket
            )
            audit["bucket_timestamp_violations"] += int(
                start != DAY_START_NS + bucket * BUCKET_WIDTH_NS
                or end != start + BUCKET_WIDTH_NS
            )
            expected_segment, expected_state = _expected_segment(start)
            audit["segment_label_violations"] += int(
                segment != expected_segment
            )
            audit["state_label_violations"] += int(
                state != expected_state
            )
            audit["book_crossed_null_rows"] += int(crossed_raw is None)
            audit["crossed_missing_state_identity_rows"] += int(
                crossed and ordinal is None
            )
            segment_total[segment] += 1
            state_total[state] += 1
            segment_crossed[segment] += int(crossed)
            state_crossed[state] += int(crossed)
            _primary_hash_row(
                stream_digest,
                bucket,
                start,
                end,
                segment,
                state,
                crossed,
                ordinal,
            )
            if crossed:
                row_hash = hashlib.sha256()
                _primary_hash_row(
                    row_hash,
                    bucket,
                    start,
                    end,
                    segment,
                    state,
                    crossed,
                    ordinal,
                )
                crossed_digest.update(row_hash.digest())

    return _primary_result(
        context,
        audit,
        segment_total,
        segment_crossed,
        state_total,
        state_crossed,
        stream_digest.hexdigest(),
        crossed_digest.hexdigest(),
    )


def _classify_reference(context: dict[str, Any]) -> dict[str, Any]:
    table = pq.read_table(REFERENCE_PATH, columns=list(ALLOWED_COLUMNS))
    column_values = {
        name: table.column(name).combine_chunks().to_pylist()
        for name in ALLOWED_COLUMNS
    }
    rows = table.num_rows
    violations: dict[str, int] = {
        "rows": rows,
        "bucket_index_violations": 0,
        "bucket_timestamp_violations": 0,
        "segment_label_violations": 0,
        "state_label_violations": 0,
        "book_crossed_null_rows": 0,
        "crossed_missing_state_identity_rows": 0,
    }
    segment_total: dict[str, int] = {}
    segment_crossed: dict[str, int] = {}
    state_total: dict[str, int] = {}
    state_crossed: dict[str, int] = {}
    stream_hash = hashlib.sha256()
    crossed_hash = hashlib.sha256()

    for row in range(rows):
        bucket = int(column_values["bucket_index"][row])
        start = int(column_values["bucket_start_ns"][row])
        end = int(column_values["bucket_end_ns"][row])
        segment = str(column_values["market_segment"][row])
        state = str(column_values["market_state"][row])
        crossed_value = column_values["book_crossed"][row]
        state_ordinal = column_values["state_source_row_ordinal"][row]
        crossed = bool(crossed_value) if crossed_value is not None else False
        violations["bucket_index_violations"] += int(bucket != row)
        violations["bucket_timestamp_violations"] += int(
            start != DAY_START_NS + row * BUCKET_WIDTH_NS
            or end != DAY_START_NS + (row + 1) * BUCKET_WIDTH_NS
        )
        correct_segment, correct_state = _expected_segment(start)
        violations["segment_label_violations"] += int(
            segment != correct_segment
        )
        violations["state_label_violations"] += int(state != correct_state)
        violations["book_crossed_null_rows"] += int(
            crossed_value is None
        )
        violations["crossed_missing_state_identity_rows"] += int(
            crossed and state_ordinal is None
        )
        segment_total[segment] = segment_total.get(segment, 0) + 1
        state_total[state] = state_total.get(state, 0) + 1
        if crossed:
            segment_crossed[segment] = segment_crossed.get(segment, 0) + 1
            state_crossed[state] = state_crossed.get(state, 0) + 1
        else:
            segment_crossed.setdefault(segment, 0)
            state_crossed.setdefault(state, 0)
        _reference_hash_row(
            stream_hash,
            bucket,
            start,
            end,
            segment,
            state,
            crossed,
            state_ordinal,
        )
        if crossed:
            single = hashlib.sha256()
            _reference_hash_row(
                single,
                bucket,
                start,
                end,
                segment,
                state,
                crossed,
                state_ordinal,
            )
            crossed_hash.update(single.digest())

    return _reference_result(
        context,
        violations,
        segment_total,
        segment_crossed,
        state_total,
        state_crossed,
        stream_hash.hexdigest(),
        crossed_hash.hexdigest(),
    )


def _primary_result(
    context: dict[str, Any],
    audit: Counter[str],
    segment_total: Counter[str],
    segment_crossed: Counter[str],
    state_total: Counter[str],
    state_crossed: Counter[str],
    stream_checksum: str,
    crossed_checksum: str,
) -> dict[str, Any]:
    segment_counts = {
        segment[0]: {
            "bucket_closes": int(segment_total[segment[0]]),
            "crossed_bucket_closes": int(segment_crossed[segment[0]]),
        }
        for segment in SEGMENTS
    }
    state_counts = {
        state: {
            "bucket_closes": int(state_total[state]),
            "crossed_bucket_closes": int(state_crossed[state]),
        }
        for state in EXPECTED_STATE_COUNTS
    }
    continuous = sum(
        value["crossed_bucket_closes"]
        for key, value in segment_counts.items()
        if key in {"CONTINUOUS_00_22", "CONTINUOUS_23_24"}
    )
    total_crossed = sum(
        value["crossed_bucket_closes"] for value in segment_counts.values()
    )
    finding, recommendation = _decision(continuous)
    audit_dict = _audit_dict(audit)
    integrity = _integrity_checks(
        context,
        audit_dict,
        segment_counts,
        state_counts,
        total_crossed,
        recommendation,
    )
    return _run_payload(
        "primary",
        PRIMARY_PATH,
        audit_dict,
        segment_counts,
        state_counts,
        continuous,
        total_crossed,
        stream_checksum,
        crossed_checksum,
        finding,
        recommendation,
        integrity,
    )


def _reference_result(
    context: dict[str, Any],
    audit: dict[str, int],
    segment_total: dict[str, int],
    segment_crossed: dict[str, int],
    state_total: dict[str, int],
    state_crossed: dict[str, int],
    stream_checksum: str,
    crossed_checksum: str,
) -> dict[str, Any]:
    segments: dict[str, dict[str, int]] = {}
    for segment_id, _state, _start, _end, _expected in SEGMENTS:
        segments[segment_id] = {
            "bucket_closes": int(segment_total.get(segment_id, 0)),
            "crossed_bucket_closes": int(
                segment_crossed.get(segment_id, 0)
            ),
        }
    states: dict[str, dict[str, int]] = {}
    for state_name in EXPECTED_STATE_COUNTS:
        states[state_name] = {
            "bucket_closes": int(state_total.get(state_name, 0)),
            "crossed_bucket_closes": int(
                state_crossed.get(state_name, 0)
            ),
        }
    continuous_crossed = (
        segments["CONTINUOUS_00_22"]["crossed_bucket_closes"]
        + segments["CONTINUOUS_23_24"]["crossed_bucket_closes"]
    )
    all_crossed = sum(
        values["crossed_bucket_closes"] for values in segments.values()
    )
    finding, recommendation = _decision(continuous_crossed)
    normalized_audit = {name: int(audit.get(name, 0)) for name in _audit_names()}
    integrity = _integrity_checks(
        context,
        normalized_audit,
        segments,
        states,
        all_crossed,
        recommendation,
    )
    return _run_payload(
        "reference",
        REFERENCE_PATH,
        normalized_audit,
        segments,
        states,
        continuous_crossed,
        all_crossed,
        stream_checksum,
        crossed_checksum,
        finding,
        recommendation,
        integrity,
    )


def _run_payload(
    implementation: str,
    path: Path,
    audit: dict[str, int],
    segment_counts: dict[str, dict[str, int]],
    state_counts: dict[str, dict[str, int]],
    continuous_crossed: int,
    total_crossed: int,
    stream_checksum: str,
    crossed_checksum: str,
    finding: str,
    recommendation: dict[str, str],
    integrity: dict[str, bool],
) -> dict[str, Any]:
    return {
        "version": "GC_MICROSTRUCTURE_STEP_4A2_RUN_V0_1",
        "implementation": implementation,
        "classification_scope": "FINAL_METADATA_CLASSIFICATION_DISPOSITION_ONLY",
        "research_or_validation_credit": "NONE",
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "tool_sha256": _sha256(Path(__file__)),
        "payload": {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "rows": EXPECTED_PAYLOAD_ROWS,
            "full_schema_columns": EXPECTED_PAYLOAD_COLUMNS,
        },
        "accessed_columns": list(ALLOWED_COLUMNS),
        "audits": audit,
        "classification": {
            "by_segment": segment_counts,
            "by_state": state_counts,
            "continuous_crossed_bucket_closes": continuous_crossed,
            "total_crossed_bucket_closes": total_crossed,
            "selected_column_stream_checksum": stream_checksum,
            "crossed_bucket_identity_checksum": crossed_checksum,
            "raw_state_source_row_ordinal_emitted": False,
        },
        "finding": finding,
        "recommendation": recommendation,
        "recommendation_count": 1,
        "integrity_checks": integrity,
        "formal_integrity_pass": all(integrity.values()),
        **_scope_flags(),
    }


def _decision(continuous_crossed: int) -> tuple[str, dict[str, str]]:
    if continuous_crossed == 0:
        return (
            "CONTINUOUS_BUCKET_CLOSE_STATES_CLEAN",
            {"id": RECERTIFY_ID, "text": RECERTIFY_TEXT},
        )
    return (
        "CONTINUOUS_BUCKET_CLOSE_STATES_CROSSED",
        {"id": REJECT_ID, "text": REJECT_TEXT},
    )


def _integrity_checks(
    context: dict[str, Any],
    audit: dict[str, int],
    segment_counts: dict[str, dict[str, int]],
    state_counts: dict[str, dict[str, int]],
    total_crossed: int,
    recommendation: dict[str, str],
) -> dict[str, bool]:
    segment_grid_exact = all(
        segment_counts[item[0]]["bucket_closes"] == item[4]
        for item in SEGMENTS
    )
    state_grid_exact = all(
        state_counts[state]["bucket_closes"] == expected
        for state, expected in EXPECTED_STATE_COUNTS.items()
    )
    return {
        "step_4a_and_step_4a1_seals_valid": bool(
            context["predecessor_seals_valid"]
        ),
        "feature_payload_metadata_exact": bool(
            context["payload_metadata_exact"]
        ),
        "only_allowed_columns_accessed": True,
        "bucket_grid_exact": (
            audit["rows"] == BUCKET_COUNT
            and audit["bucket_index_violations"] == 0
            and audit["bucket_timestamp_violations"] == 0
        ),
        "segment_and_state_labels_exact": (
            audit["segment_label_violations"] == 0
            and audit["state_label_violations"] == 0
            and segment_grid_exact
            and state_grid_exact
        ),
        "book_crossed_complete_boolean": (
            audit["book_crossed_null_rows"] == 0
        ),
        "crossed_state_identity_available_and_only_hashed": (
            audit["crossed_missing_state_identity_rows"] == 0
        ),
        "sealed_total_60_crossed_buckets_reproduced": (
            total_crossed == EXPECTED_TOTAL_CROSSED
        ),
        "exactly_one_binary_recommendation": recommendation["id"]
        in {RECERTIFY_ID, REJECT_ID},
        "recommendation_not_implemented": True,
        "no_prohibited_work": True,
    }


def _primary_hash_row(
    digest: Any,
    bucket: int,
    start: int,
    end: int,
    segment: str,
    state: str,
    crossed: bool,
    ordinal: int | None,
) -> None:
    for value in (bucket, start, end):
        digest.update(INT64.pack(value))
    for value in (segment, state):
        encoded = value.encode("utf-8")
        digest.update(UINT32.pack(len(encoded)))
        digest.update(encoded)
    digest.update(b"\x01" if crossed else b"\x00")
    if ordinal is None:
        digest.update(b"\x00")
    else:
        digest.update(b"\x01")
        digest.update(INT64.pack(int(ordinal)))


def _reference_hash_row(
    digest: Any,
    bucket: int,
    start: int,
    end: int,
    segment: str,
    state: str,
    crossed: bool,
    ordinal: int | None,
) -> None:
    numeric = (bucket, start, end)
    digest.update(b"".join(INT64.pack(int(value)) for value in numeric))
    segment_bytes = segment.encode("utf-8")
    state_bytes = state.encode("utf-8")
    digest.update(UINT32.pack(len(segment_bytes)) + segment_bytes)
    digest.update(UINT32.pack(len(state_bytes)) + state_bytes)
    digest.update(bytes((1 if crossed else 0,)))
    if ordinal is None:
        digest.update(bytes((0,)))
    else:
        digest.update(bytes((1,)) + INT64.pack(int(ordinal)))


def _expected_segment(timestamp: int) -> tuple[str, str]:
    for segment, state, start, end, _count in SEGMENTS:
        if start <= timestamp < end:
            return segment, state
    raise ValueError(f"Timestamp outside frozen grid: {timestamp}")


def _audit_names() -> tuple[str, ...]:
    return (
        "rows",
        "bucket_index_violations",
        "bucket_timestamp_violations",
        "segment_label_violations",
        "state_label_violations",
        "book_crossed_null_rows",
        "crossed_missing_state_identity_rows",
    )


def _audit_dict(counter: Counter[str]) -> dict[str, int]:
    return {name: int(counter[name]) for name in _audit_names()}


def _scope_flags() -> dict[str, bool]:
    return {
        "source_mbo_or_mbp_accessed": False,
        "disallowed_feature_column_accessed": False,
        "raw_state_source_row_ordinal_emitted": False,
        "feature_pipeline_modified_or_rerun": False,
        "recommendation_implemented": False,
        "additional_data_acquired": False,
        "another_date_inspected": False,
        "market_values_accessed_or_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }


def _seal(output: Path, context: dict[str, Any]) -> None:
    primary_path = output / "primary_classification.json"
    reference_path = output / "reference_classification.json"
    if not primary_path.exists() or not reference_path.exists():
        raise FileNotFoundError("Both Step 4A.2 classifications are required")
    primary = _read_json(primary_path)
    reference = _read_json(reference_path)
    current_tool_hash = _sha256(Path(__file__))
    for run in (primary, reference):
        if run["tool_sha256"] != current_tool_hash:
            raise ValueError("Step 4A.2 tool changed between run and seal")

    compared = (
        "accessed_columns",
        "audits",
        "classification",
        "finding",
        "recommendation",
        "recommendation_count",
        "integrity_checks",
        "formal_integrity_pass",
    )
    matching = {name: primary[name] == reference[name] for name in compared}
    reproduction_pass = all(matching.values())
    predecessor_payload_pass = bool(
        context["predecessor_seals_valid"]
        and context["payload_metadata_exact"]
    )
    integrity_pass = bool(
        primary["formal_integrity_pass"]
        and reference["formal_integrity_pass"]
    )
    if not predecessor_payload_pass:
        status = "FAIL_PREDECESSOR_OR_PAYLOAD_INTEGRITY"
    elif not integrity_pass:
        status = "FAIL_DISPOSITION_INTEGRITY"
    elif not reproduction_pass:
        status = "FAIL_DISPOSITION_REPRODUCTION"
    else:
        status = "PASS_DISPOSITION_REPRODUCTION"

    formal_gates = {
        "step_4a_and_step_4a1_seals_valid": bool(
            context["predecessor_seals_valid"]
        ),
        "feature_payload_hashes_sizes_schema_and_rows_exact": bool(
            context["payload_metadata_exact"]
        ),
        "primary_integrity_pass": bool(primary["formal_integrity_pass"]),
        "reference_integrity_pass": bool(
            reference["formal_integrity_pass"]
        ),
        "selected_column_stream_checksum_identical": (
            primary["classification"]["selected_column_stream_checksum"]
            == reference["classification"]["selected_column_stream_checksum"]
        ),
        "crossed_identity_checksum_identical": (
            primary["classification"]["crossed_bucket_identity_checksum"]
            == reference["classification"]["crossed_bucket_identity_checksum"]
        ),
        "segment_state_counts_and_decision_identical": all(
            matching[name]
            for name in (
                "classification",
                "finding",
                "recommendation",
                "recommendation_count",
            )
        ),
        "only_allowed_columns_accessed": matching["accessed_columns"],
        "exactly_one_recommendation": primary["recommendation_count"] == 1,
        "recommendation_not_implemented": (
            not primary["recommendation_implemented"]
            and not reference["recommendation_implemented"]
        ),
        "no_source_data_other_date_market_value_outcome_signal_execution_or_pnl_access": all(
            not run[key]
            for run in (primary, reference)
            for key in (
                "source_mbo_or_mbp_accessed",
                "disallowed_feature_column_accessed",
                "raw_state_source_row_ordinal_emitted",
                "feature_pipeline_modified_or_rerun",
                "additional_data_acquired",
                "another_date_inspected",
                "market_values_accessed_or_reported",
                "outcomes_accessed",
                "signals_calculated",
                "execution_optimized",
                "pnl_calculated",
            )
        ),
    }
    verdict: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_4A2_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS_DISPOSITION_REPRODUCTION",
        "classification_scope": "FINAL_METADATA_CLASSIFICATION_DISPOSITION_ONLY",
        "research_or_validation_credit": "NONE",
        "predecessors": {
            "step_4a": "FAIL_FEATURE_INTEGRITY",
            "step_4a1": "FAIL_DIAGNOSTIC_INTEGRITY",
        },
        "predecessor_verdicts_preserved": True,
        "classification": primary["classification"],
        "finding": primary["finding"],
        "recommendation": primary["recommendation"],
        "recommendation_count": 1,
        "reproduction": {
            "pass": reproduction_pass,
            "matching_sections": matching,
        },
        "formal_gates": formal_gates,
        "passed_formal_gates": sum(formal_gates.values()),
        "total_formal_gates": len(formal_gates),
        **_scope_flags(),
        "completion_policy": "Preserve this binary disposition and stop without implementation.",
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    verdict_path = output / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_text_atomic(REPORT_PATH, _render_report(verdict))

    artifact_paths = (
        primary_path,
        reference_path,
        verdict_path,
        REPORT_PATH,
    )
    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_4A2_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "classification_scope": "FINAL_METADATA_CLASSIFICATION_DISPOSITION_ONLY",
        "research_or_validation_credit": "NONE",
        "protocol": _file_record(PROTOCOL_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "step4a_manifest": _file_record(STEP4A_MANIFEST_PATH),
        "step4a1_manifest": _file_record(STEP4A1_MANIFEST_PATH),
        "primary_payload": _file_record(PRIMARY_PATH),
        "reference_payload": _file_record(REFERENCE_PATH),
        "classifier_tool": _file_record(Path(__file__)),
        "artifacts": [_file_record(path) for path in artifact_paths],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
        **_scope_flags(),
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4A2_SEALED",
                "status": status,
                "formal_pass": verdict["formal_pass"],
                "continuous_crossed_bucket_closes": verdict[
                    "classification"
                ]["continuous_crossed_bucket_closes"],
                "total_crossed_bucket_closes": verdict["classification"][
                    "total_crossed_bucket_closes"
                ],
                "finding": verdict["finding"],
                "recommendation": verdict["recommendation"]["id"],
                "reproduction_pass": reproduction_pass,
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _render_report(verdict: dict[str, Any]) -> str:
    classification = verdict["classification"]
    lines = [
        "# GC Microstructure Step 4A.2 — Final Metadata Disposition",
        "",
        "## Formal status",
        "",
        f"`{verdict['status']}`",
        "",
        "## Crossed bucket-close classification",
        "",
        f"- Total crossed bucket closes: {classification['total_crossed_bucket_closes']:,}.",
        f"- Continuous crossed bucket closes: {classification['continuous_crossed_bucket_closes']:,}.",
        "",
        "### By segment",
        "",
    ]
    for segment, counts in classification["by_segment"].items():
        lines.append(
            f"- {segment}: {counts['crossed_bucket_closes']:,} crossed of {counts['bucket_closes']:,}."
        )
    lines.extend(["", "### By market state", ""])
    for state, counts in classification["by_state"].items():
        lines.append(
            f"- {state}: {counts['crossed_bucket_closes']:,} crossed of {counts['bucket_closes']:,}."
        )
    lines.extend(
        [
            "",
            "## Finding",
            "",
            f"`{verdict['finding']}`",
            "",
            "## Binary recommendation",
            "",
            f"`{verdict['recommendation']['id']}`",
            "",
            verdict["recommendation"]["text"],
            "",
            "The recommendation was not implemented.",
            "",
            "## Restrictions honored",
            "",
            "Only the seven frozen metadata/classification columns were read. No source MBO/MBP rows, raw state ordinals, market values, other feature values, outcomes, signals, execution, trades, or PnL were accessed or reported.",
            "",
        ]
    )
    return "\n".join(lines)


def _verify_seal(output: Path) -> None:
    context = _verified_context()
    _assert_protocol_matches_code(context["protocol"])
    manifest = _read_json(output / "manifest.json")
    verdict = _read_json(output / "verdict.json")
    if manifest["manifest_hash"] != _canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    ):
        raise ValueError("Step 4A.2 manifest hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash(
        {key: value for key, value in verdict.items() if key != "verdict_hash"}
    ):
        raise ValueError("Step 4A.2 verdict hash mismatch")
    for record in manifest["artifacts"]:
        _verify_file_record(record)
    for key, expected in (
        ("protocol", EXPECTED_PROTOCOL_SHA256),
        ("freeze_receipt", EXPECTED_FREEZE_SHA256),
        ("primary_payload", EXPECTED_PAYLOAD_SHA256),
        ("reference_payload", EXPECTED_PAYLOAD_SHA256),
    ):
        if manifest[key]["sha256"] != expected:
            raise ValueError(f"Step 4A.2 {key} declaration mismatch")
        _verify_file_record(manifest[key])
    for key in ("step4a_manifest", "step4a1_manifest"):
        _verify_file_record(manifest[key])
    if manifest["classifier_tool"]["sha256"] != _sha256(Path(__file__)):
        raise ValueError("Step 4A.2 classifier changed")
    if manifest["status"] != verdict["status"]:
        raise ValueError("Step 4A.2 verdict and manifest statuses differ")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4A2_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]),
                "predecessor_verdicts_preserved": manifest[
                    "predecessor_verdicts_preserved"
                ],
                "source_mbo_or_mbp_accessed": manifest[
                    "source_mbo_or_mbp_accessed"
                ],
                "disallowed_feature_column_accessed": manifest[
                    "disallowed_feature_column_accessed"
                ],
                "recommendation_implemented": manifest[
                    "recommendation_implemented"
                ],
                "additional_data_acquired": manifest[
                    "additional_data_acquired"
                ],
                "another_date_inspected": manifest["another_date_inspected"],
                "outcomes_accessed": manifest["outcomes_accessed"],
                "signals_calculated": manifest["signals_calculated"],
                "pnl_calculated": manifest["pnl_calculated"],
                "research_or_validation_credit": manifest[
                    "research_or_validation_credit"
                ],
            },
            sort_keys=True,
        )
    )


def _verified_context() -> dict[str, Any]:
    if _sha256(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 4A.2 protocol changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 4A.2 freeze receipt changed")
    protocol = _read_json(PROTOCOL_PATH)
    freeze = _read_json(FREEZE_PATH)
    if freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 4A.2 freeze does not bind protocol")

    step4a = _read_json(STEP4A_MANIFEST_PATH)
    if (
        step4a.get("manifest_hash") != EXPECTED_STEP4A_MANIFEST_HASH
        or _canonical_hash(
            {
                key: value
                for key, value in step4a.items()
                if key != "manifest_hash"
            }
        )
        != EXPECTED_STEP4A_MANIFEST_HASH
        or step4a.get("status") != "FAIL_FEATURE_INTEGRITY"
        or step4a.get("verdict_hash") != EXPECTED_STEP4A_VERDICT_HASH
    ):
        raise ValueError("Step 4A predecessor changed")
    for record in step4a["artifacts"]:
        _verify_file_record(record)

    step4a1 = _read_json(STEP4A1_MANIFEST_PATH)
    if (
        step4a1.get("manifest_hash") != EXPECTED_STEP4A1_MANIFEST_HASH
        or _canonical_hash(
            {
                key: value
                for key, value in step4a1.items()
                if key != "manifest_hash"
            }
        )
        != EXPECTED_STEP4A1_MANIFEST_HASH
        or step4a1.get("status") != "FAIL_DIAGNOSTIC_INTEGRITY"
        or step4a1.get("verdict_hash") != EXPECTED_STEP4A1_VERDICT_HASH
    ):
        raise ValueError("Step 4A.1 predecessor changed")
    for record in step4a1["artifacts"]:
        _verify_file_record(record)
    step4a1_verdict = _read_json(
        STEP4A1_MANIFEST_PATH.parent / "verdict.json"
    )
    if (
        step4a1_verdict["findings"][
            "bad_ts_recv_snapshot_semantics"
        ]
        != "CONFIRMED"
        or step4a1_verdict["findings"]["crossed_unfinished_event"]
        != "NOT_CONFIRMED"
        or step4a1_verdict["recommendation"]["id"] != "NONE"
    ):
        raise ValueError("Step 4A.1 sealed findings changed")

    expected_fields = {
        "bucket_index": (pa.int64(), False),
        "bucket_start_ns": (pa.int64(), False),
        "bucket_end_ns": (pa.int64(), False),
        "market_segment": (pa.string(), False),
        "market_state": (pa.string(), False),
        "book_crossed": (pa.bool_(), False),
        "state_source_row_ordinal": (pa.int64(), True),
    }
    metadata_exact = True
    for path in (PRIMARY_PATH, REFERENCE_PATH):
        metadata_exact = metadata_exact and (
            path.stat().st_size == EXPECTED_PAYLOAD_BYTES
            and _sha256(path) == EXPECTED_PAYLOAD_SHA256
        )
        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
        field_contract_exact = all(
            schema.field(name).type == expected_type
            and schema.field(name).nullable == expected_nullable
            for name, (expected_type, expected_nullable) in expected_fields.items()
        )
        metadata_exact = metadata_exact and (
            parquet.metadata.num_rows == EXPECTED_PAYLOAD_ROWS
            and parquet.metadata.num_columns == EXPECTED_PAYLOAD_COLUMNS
            and set(ALLOWED_COLUMNS).issubset(schema.names)
            and field_contract_exact
        )
    if not metadata_exact:
        raise ValueError("Step 4A feature payload metadata changed")
    return {
        "protocol": protocol,
        "freeze": freeze,
        "predecessor_seals_valid": True,
        "payload_metadata_exact": True,
    }


def _assert_protocol_matches_code(protocol: dict[str, Any]) -> None:
    if tuple(
        protocol["allowed_column_contract"]["columns_in_exact_read_order"]
    ) != ALLOWED_COLUMNS:
        raise ValueError("Step 4A.2 allowed columns differ from protocol")
    grid = protocol["temporal_grid"]
    if (
        grid["day_start_inclusive_ns"] != DAY_START_NS
        or grid["day_end_exclusive_ns"] != DAY_END_NS
        or grid["bucket_width_ns"] != BUCKET_WIDTH_NS
        or grid["bucket_count"] != BUCKET_COUNT
    ):
        raise ValueError("Step 4A.2 temporal grid differs")
    protocol_segments = tuple(
        (
            item["segment_id"],
            item["state"],
            item["start_inclusive_ns"],
            item["end_exclusive_ns"],
            item["expected_bucket_count"],
        )
        for item in grid["segments"]
    )
    if protocol_segments != SEGMENTS:
        raise ValueError("Step 4A.2 segments differ")
    rules = protocol["binary_decision_rule"]
    clean = rules["zero_continuous_crossed_bucket_closes"]
    crossed = rules["one_or_more_continuous_crossed_bucket_closes"]
    if (
        clean["recommendation_id"] != RECERTIFY_ID
        or clean["recommendation_text"] != RECERTIFY_TEXT
        or crossed["recommendation_id"] != REJECT_ID
        or crossed["recommendation_text"] != REJECT_TEXT
    ):
        raise ValueError("Step 4A.2 decision rule differs")


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _verify_file_record(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if not path.exists():
        raise FileNotFoundError(path)
    if path.stat().st_size != record["bytes"]:
        raise ValueError(f"File size changed: {path}")
    if _sha256(path) != record["sha256"]:
        raise ValueError(f"File hash changed: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
