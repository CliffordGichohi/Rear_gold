#!/usr/bin/env python3
"""Run the bounded Step 4A.3 feature-integrity recertification.

The original Step 4A primary and reference feature calculations are called
unchanged.  Only the two integrity classifications sealed by the Step 4A.3
amendment are replaced.  No feature value, outcome, signal, execution result,
or PnL is printed or inspected by the operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from tools import build_gc_microstructure_features_step4a as base


REPO_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4a3_amendment_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4a3_freeze_v01.json"
)
STEP4A_MANIFEST_PATH = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4a_v01" / "manifest.json"
)
STEP4A1_MANIFEST_PATH = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4a1_v01" / "manifest.json"
)
STEP4A2_MANIFEST_PATH = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4a2_v01" / "manifest.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4a3_v01"
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_4A3_REPORT.md"

EXPECTED_AMENDMENT_SHA256 = (
    "59861ceb1ad282772dcd9bdfa196432aa879916f222550ad547a3f006ca74e24"
)
EXPECTED_FREEZE_SHA256 = (
    "b4968106e21ffd7836ccca4438b826f63237ffd2cd0dca17c1ad9ef45973b1bb"
)
EXPECTED_ORIGINAL_TOOL_SHA256 = (
    "c5589914a1acae6a3a1e9079c302821477866bba3741317392c567bb590c2369"
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
EXPECTED_STEP4A2_MANIFEST_HASH = (
    "b273efc3826a3e10856e5693c75262ca286d4aa66bfe4cef6c53b64e893e0fb2"
)
EXPECTED_STEP4A2_VERDICT_HASH = (
    "f750b8f9359a9e56fc69ea8931ea2b486c221c5e07890c68e6cd6cab74573353"
)
EXPECTED_SCHEMA_HASH = (
    "dfaf74cdc55b37469966857fc1ed2279b3d18c98f90454ced65859cb32494232"
)
EXPECTED_COMPLETE_ROW_CHECKSUM = (
    "10e9282feaedd99bf13ad4e77415c49c3a6b193bf87a4fc184abce57da96fd30"
)
EXPECTED_PARQUET_SHA256 = (
    "b559771bc332f400900da43e3c16619a5b75b9457c2a15975d390e977085eda3"
)
EXPECTED_PARQUET_BYTES = 5_957_736
EXPECTED_SOURCE_CHECKSUMS = {
    "mbo_complete_pass": "09f51c7711200041f41c2c98a4b1da97f161e34318c1a4cf5f96da37ddd8ebb1",
    "mbp10_complete_pass": "2dcb350f27bce920b6495569b0453024460160290d620e6d1fff66214bf3f944",
}
EXPECTED_BAD_COUNTS = {
    "combined_bad_flag_rows": 2_745,
    "mbo_bad_flag_rows": 2_744,
    "mbo_action_A": 2_743,
    "mbo_action_R": 1,
    "mbp10_bad_flag_rows": 1,
    "mbp10_action_A": 1,
    "mbp10_action_R": 0,
    "violating_bad_flag_rows": 0,
}
EXPECTED_BY_SEGMENT = {
    "CONTINUOUS_00_22": {"bucket_closes": 79_200, "crossed_bucket_closes": 0},
    "MAINTENANCE_22_2245": {"bucket_closes": 2_700, "crossed_bucket_closes": 0},
    "PRE_OPEN_2245_23": {"bucket_closes": 900, "crossed_bucket_closes": 60},
    "CONTINUOUS_23_24": {"bucket_closes": 3_600, "crossed_bucket_closes": 0},
}
EXPECTED_BY_STATE = {
    "CONTINUOUS_MATCHING": {"bucket_closes": 82_800, "crossed_bucket_closes": 0},
    "MAINTENANCE": {"bucket_closes": 2_700, "crossed_bucket_closes": 0},
    "PRE_OPEN": {"bucket_closes": 900, "crossed_bucket_closes": 60},
}
SNAPSHOT_COLUMNS = (
    "ts_recv",
    "ts_event",
    "action",
    "flags",
)
SUPERSEDED_GATES = {
    "bad_ts_recv_flag_rows_zero",
    "continuous_crossed_book_rows_zero",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("primary", "reference", "seal", "verify"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_stage(args.action, Path(args.output))


def run_stage(action: str, output: Path) -> None:
    context = _verified_context()
    _assert_amendment_matches_code(context["amendment"])
    output.mkdir(parents=True, exist_ok=True)

    if action in {"primary", "reference"}:
        feature_path = output / f"{action}_features.parquet"
        summary_path = output / f"{action}_summary.json"
        if feature_path.exists() or summary_path.exists():
            raise FileExistsError(f"Refusing to overwrite Step 4A.3 {action} output")

        if action == "primary":
            columns, audits, source_checksums = base._calculate_primary()
            snapshot_semantics = _snapshot_semantics_primary()
            bucket_classification = _bucket_classification_primary(columns)
        else:
            columns, audits, source_checksums = base._calculate_reference()
            snapshot_semantics = _snapshot_semantics_reference()
            bucket_classification = _bucket_classification_reference(columns)

        base._validate_column_lengths(columns)
        original_integrity = base._integrity_checks(
            columns, audits, context["base_context"]
        )
        _validate_original_integrity_shape(original_integrity)
        feature_hashes = base._feature_hashes(columns)
        base._write_feature_parquet(feature_path, columns)
        feature_parquet = _file_record(feature_path)
        unchanged_feature_reproduction = _unchanged_feature_reproduction(
            source_checksums, feature_hashes, feature_parquet
        )
        amended_integrity = _amended_integrity_checks(
            original_integrity=original_integrity,
            audits=audits,
            snapshot_semantics=snapshot_semantics,
            bucket_classification=bucket_classification,
            unchanged_feature_reproduction=unchanged_feature_reproduction,
            context=context,
        )
        summary = {
            "version": "GC_MICROSTRUCTURE_STEP_4A3_RUN_V0_1",
            "implementation": action,
            "classification": "ENGINEERING_ONLY_FEATURE_INTEGRITY_RECERTIFICATION",
            "research_or_validation_credit": "NONE",
            "amendment_sha256": EXPECTED_AMENDMENT_SHA256,
            "freeze_sha256": EXPECTED_FREEZE_SHA256,
            "recertification_tool_sha256": _sha256(Path(__file__)),
            "unchanged_original_tool_sha256": _sha256(Path(base.__file__)),
            "source_input_checksums": source_checksums,
            "feature_rows": base.BUCKET_COUNT,
            "feature_columns": list(base.FEATURE_COLUMNS),
            "feature_column_count": len(base.FEATURE_COLUMNS),
            "feature_schema_hash": base._feature_schema_hash(),
            "feature_hashes": feature_hashes,
            "feature_parquet": feature_parquet,
            "audits": audits,
            "snapshot_semantics": snapshot_semantics,
            "bucket_close_classification": bucket_classification,
            "original_integrity_checks": original_integrity,
            "superseded_original_gate_results": {
                name: original_integrity[name] for name in sorted(SUPERSEDED_GATES)
            },
            "unchanged_feature_reproduction": unchanged_feature_reproduction,
            "amended_integrity_checks": amended_integrity,
            "formal_integrity_pass": all(amended_integrity.values()),
            "mbo_mbp_alignment_attempts": 0,
            "source_rows_filtered_dropped_repaired_or_relabeled": False,
            "additional_data_acquired": False,
            "another_date_inspected": False,
            "market_values_human_or_model_inspected": False,
            "outcomes_accessed": False,
            "signals_calculated": False,
            "execution_optimized": False,
            "pnl_calculated": False,
        }
        _write_json_atomic(summary_path, summary)
        print(
            json.dumps(
                {
                    "stage": f"GC_MICROSTRUCTURE_STEP_4A3_{action.upper()}_COMPLETE",
                    "implementation": action,
                    "feature_rows": base.BUCKET_COUNT,
                    "feature_columns": len(base.FEATURE_COLUMNS),
                    "bad_ts_recv_rows": snapshot_semantics["combined"]["bad_flag_rows"],
                    "snapshot_semantic_violations": snapshot_semantics["combined"]["violating_rows"],
                    "continuous_crossed_bucket_closes": bucket_classification["continuous_crossed_bucket_closes"],
                    "pre_open_crossed_bucket_closes": bucket_classification["by_state"]["PRE_OPEN"]["crossed_bucket_closes"],
                    "integrity_pass": all(amended_integrity.values()),
                    "complete_row_checksum": feature_hashes["complete_row_checksum"],
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


def _snapshot_semantics_primary() -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    for source, path in (("MBO", base.MBO_PATH), ("MBP10", base.MBP_PATH)):
        counts: Counter[str] = Counter()
        actions: Counter[str] = Counter()
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(
            batch_size=base.BATCH_SIZE, columns=list(SNAPSHOT_COLUMNS)
        ):
            receives = batch.column(batch.schema.get_field_index("ts_recv")).cast(pa.int64()).to_numpy(zero_copy_only=False)
            events = batch.column(batch.schema.get_field_index("ts_event")).cast(pa.int64()).to_numpy(zero_copy_only=False)
            flags_values = batch.column(batch.schema.get_field_index("flags")).to_numpy(zero_copy_only=False)
            action_values = batch.column(batch.schema.get_field_index("action")).to_pylist()
            counts["records"] += batch.num_rows
            for index in range(batch.num_rows):
                flags = int(flags_values[index])
                if not flags & base.F_BAD_TS_RECV:
                    continue
                receive = int(receives[index])
                event = int(events[index])
                action = str(action_values[index])
                counts["bad_flag_rows"] += 1
                actions[action if action in {"A", "R"} else "OTHER"] += 1
                predicates = {
                    "non_snapshot_rows": not bool(flags & base.F_SNAPSHOT),
                    "receive_not_day_start_rows": receive != base.DAY_START_NS,
                    "receive_outside_frozen_day_rows": not (base.DAY_START_NS <= receive < base.DAY_END_NS),
                    "event_not_pre_start_rows": event >= base.DAY_START_NS,
                    "event_after_receive_rows": event > receive,
                    "action_not_allowed_rows": action not in {"A", "R"},
                }
                violation = False
                for name, failed in predicates.items():
                    counts[name] += int(failed)
                    violation = violation or failed
                counts["violating_rows"] += int(violation)
                counts["passing_rows"] += int(not violation)
        results[source] = _snapshot_source_result(counts, actions)
    return _combine_snapshot_results(results)


def _snapshot_semantics_reference() -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    for source, path in (("MBO", base.MBO_PATH), ("MBP10", base.MBP_PATH)):
        table = pq.read_table(path, columns=list(SNAPSHOT_COLUMNS))
        flags = table["flags"].combine_chunks().to_numpy(zero_copy_only=False).astype(np.int64, copy=False)
        receives = table["ts_recv"].combine_chunks().cast(pa.int64()).to_numpy(zero_copy_only=False)
        events = table["ts_event"].combine_chunks().cast(pa.int64()).to_numpy(zero_copy_only=False)
        actions_all = np.asarray(table["action"].combine_chunks().to_pylist(), dtype=object)
        bad = (flags & base.F_BAD_TS_RECV) != 0
        bad_flags = flags[bad]
        bad_receives = receives[bad]
        bad_events = events[bad]
        bad_actions = actions_all[bad]
        non_snapshot = (bad_flags & base.F_SNAPSHOT) == 0
        receive_not_start = bad_receives != base.DAY_START_NS
        receive_outside = (bad_receives < base.DAY_START_NS) | (bad_receives >= base.DAY_END_NS)
        event_not_pre_start = bad_events >= base.DAY_START_NS
        event_after_receive = bad_events > bad_receives
        action_not_allowed = ~np.isin(bad_actions, np.asarray(["A", "R"], dtype=object))
        violation = (
            non_snapshot
            | receive_not_start
            | receive_outside
            | event_not_pre_start
            | event_after_receive
            | action_not_allowed
        )
        counts: Counter[str] = Counter(
            {
                "records": int(table.num_rows),
                "bad_flag_rows": int(np.count_nonzero(bad)),
                "non_snapshot_rows": int(np.count_nonzero(non_snapshot)),
                "receive_not_day_start_rows": int(np.count_nonzero(receive_not_start)),
                "receive_outside_frozen_day_rows": int(np.count_nonzero(receive_outside)),
                "event_not_pre_start_rows": int(np.count_nonzero(event_not_pre_start)),
                "event_after_receive_rows": int(np.count_nonzero(event_after_receive)),
                "action_not_allowed_rows": int(np.count_nonzero(action_not_allowed)),
                "violating_rows": int(np.count_nonzero(violation)),
                "passing_rows": int(violation.size - np.count_nonzero(violation)),
            }
        )
        action_counter = Counter(str(value) if value in {"A", "R"} else "OTHER" for value in bad_actions.tolist())
        results[source] = _snapshot_source_result(counts, action_counter)
    return _combine_snapshot_results(results)


def _snapshot_source_result(counts: Counter[str], actions: Counter[str]) -> dict[str, Any]:
    count_names = (
        "records",
        "bad_flag_rows",
        "passing_rows",
        "violating_rows",
        "non_snapshot_rows",
        "receive_not_day_start_rows",
        "receive_outside_frozen_day_rows",
        "event_not_pre_start_rows",
        "event_after_receive_rows",
        "action_not_allowed_rows",
    )
    return {
        "counts": {name: int(counts[name]) for name in count_names},
        "action_counts": {name: int(actions[name]) for name in ("A", "R", "OTHER")},
    }


def _combine_snapshot_results(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mbo = results["MBO"]
    mbp = results["MBP10"]
    combined = {
        "bad_flag_rows": mbo["counts"]["bad_flag_rows"] + mbp["counts"]["bad_flag_rows"],
        "passing_rows": mbo["counts"]["passing_rows"] + mbp["counts"]["passing_rows"],
        "violating_rows": mbo["counts"]["violating_rows"] + mbp["counts"]["violating_rows"],
    }
    observed = {
        "combined_bad_flag_rows": combined["bad_flag_rows"],
        "mbo_bad_flag_rows": mbo["counts"]["bad_flag_rows"],
        "mbo_action_A": mbo["action_counts"]["A"],
        "mbo_action_R": mbo["action_counts"]["R"],
        "mbp10_bad_flag_rows": mbp["counts"]["bad_flag_rows"],
        "mbp10_action_A": mbp["action_counts"]["A"],
        "mbp10_action_R": mbp["action_counts"]["R"],
        "violating_bad_flag_rows": combined["violating_rows"],
    }
    return {
        "by_source": results,
        "combined": combined,
        "expected_counts": EXPECTED_BAD_COUNTS,
        "observed_counts": observed,
        "all_bad_rows_satisfy_confirmed_snapshot_semantics": (
            combined["bad_flag_rows"] > 0
            and combined["violating_rows"] == 0
            and combined["passing_rows"] == combined["bad_flag_rows"]
            and observed == EXPECTED_BAD_COUNTS
        ),
    }


def _bucket_classification_primary(columns: dict[str, list[Any]]) -> dict[str, Any]:
    by_segment = {name: {"bucket_closes": 0, "crossed_bucket_closes": 0} for name in EXPECTED_BY_SEGMENT}
    by_state = {name: {"bucket_closes": 0, "crossed_bucket_closes": 0} for name in EXPECTED_BY_STATE}
    for index in range(base.BUCKET_COUNT):
        segment = str(columns["market_segment"][index])
        state = str(columns["market_state"][index])
        crossed = bool(columns["book_crossed"][index])
        by_segment[segment]["bucket_closes"] += 1
        by_segment[segment]["crossed_bucket_closes"] += int(crossed)
        by_state[state]["bucket_closes"] += 1
        by_state[state]["crossed_bucket_closes"] += int(crossed)
    return _finalize_bucket_classification(by_segment, by_state)


def _bucket_classification_reference(columns: dict[str, list[Any]]) -> dict[str, Any]:
    segment_totals = Counter(str(value) for value in columns["market_segment"])
    state_totals = Counter(str(value) for value in columns["market_state"])
    segment_crosses = Counter(
        str(segment)
        for segment, crossed in zip(columns["market_segment"], columns["book_crossed"])
        if bool(crossed)
    )
    state_crosses = Counter(
        str(state)
        for state, crossed in zip(columns["market_state"], columns["book_crossed"])
        if bool(crossed)
    )
    by_segment = {
        name: {
            "bucket_closes": int(segment_totals[name]),
            "crossed_bucket_closes": int(segment_crosses[name]),
        }
        for name in EXPECTED_BY_SEGMENT
    }
    by_state = {
        name: {
            "bucket_closes": int(state_totals[name]),
            "crossed_bucket_closes": int(state_crosses[name]),
        }
        for name in EXPECTED_BY_STATE
    }
    return _finalize_bucket_classification(by_segment, by_state)


def _finalize_bucket_classification(by_segment: dict[str, Any], by_state: dict[str, Any]) -> dict[str, Any]:
    continuous = int(by_state["CONTINUOUS_MATCHING"]["crossed_bucket_closes"])
    return {
        "by_segment": by_segment,
        "by_state": by_state,
        "total_crossed_bucket_closes": int(sum(value["crossed_bucket_closes"] for value in by_state.values())),
        "continuous_crossed_bucket_closes": continuous,
        "counts_match_frozen_disposition": by_segment == EXPECTED_BY_SEGMENT and by_state == EXPECTED_BY_STATE,
        "continuous_matching_bucket_close_crossed_states_zero": continuous == 0,
    }


def _unchanged_feature_reproduction(source_checksums: dict[str, str], feature_hashes: dict[str, Any], parquet_record: dict[str, Any]) -> dict[str, bool]:
    return {
        "source_input_checksums_exact": source_checksums == EXPECTED_SOURCE_CHECKSUMS,
        "feature_schema_hash_exact": base._feature_schema_hash() == EXPECTED_SCHEMA_HASH,
        "complete_row_checksum_exact": feature_hashes["complete_row_checksum"] == EXPECTED_COMPLETE_ROW_CHECKSUM,
        "feature_parquet_sha256_exact": parquet_record["sha256"] == EXPECTED_PARQUET_SHA256,
        "feature_parquet_bytes_exact": parquet_record["bytes"] == EXPECTED_PARQUET_BYTES,
        "feature_row_and_column_counts_exact": base.BUCKET_COUNT == 86_400 and len(base.FEATURE_COLUMNS) == 85,
    }


def _validate_original_integrity_shape(original: dict[str, bool]) -> None:
    expected = {
        "predecessor_and_source_seals_valid",
        "required_input_columns_present",
        "source_record_counts_exact",
        "publisher_and_instrument_exact",
        "all_receive_timestamps_in_frozen_day",
        "receive_timestamp_and_source_ordinal_order_nondecreasing",
        "every_source_row_allocated_exactly_once",
        "output_bucket_rows_exact",
        "output_bucket_grid_complete_unique_and_ordered",
        "no_cross_segment_state_carry",
        "empty_levels_canonical",
        "book_sizes_and_counts_nonnegative",
        "continuous_crossed_book_rows_zero",
        "bad_ts_recv_flag_rows_zero",
        "maybe_bad_book_flag_rows_zero",
        "unknown_action_rows_zero",
        "no_mbo_to_mbp_alignment",
        "no_outcome_signal_execution_or_pnl_work",
    }
    if set(original) != expected:
        raise ValueError("Original Step 4A integrity-gate registry changed")


def _amended_integrity_checks(
    *,
    original_integrity: dict[str, bool],
    audits: dict[str, Any],
    snapshot_semantics: dict[str, Any],
    bucket_classification: dict[str, Any],
    unchanged_feature_reproduction: dict[str, bool],
    context: dict[str, Any],
) -> dict[str, bool]:
    checks = {
        name: bool(value)
        for name, value in original_integrity.items()
        if name not in SUPERSEDED_GATES
    }
    checks.update(
        {
            "step_4a_step_4a1_step_4a2_seals_valid": bool(context["predecessor_seals_valid"]),
            "unchanged_original_feature_engine_bound": bool(context["original_engine_bound"]),
            "bad_ts_recv_rows_all_confirmed_snapshot_semantics": bool(snapshot_semantics["all_bad_rows_satisfy_confirmed_snapshot_semantics"]),
            "continuous_matching_bucket_close_crossed_states_zero": bool(bucket_classification["continuous_matching_bucket_close_crossed_states_zero"]),
            "crossed_bucket_close_segment_and_state_counts_reproduced": bool(bucket_classification["counts_match_frozen_disposition"]),
            "raw_continuous_crossed_source_row_count_reproduced": audits["mbp10"]["continuous_crossed_book_rows"] == 1,
            "unchanged_feature_payload_reproduced_exactly": all(unchanged_feature_reproduction.values()),
            "source_rows_not_filtered_dropped_repaired_or_relabeled": True,
        }
    )
    return checks


def _seal(output: Path, context: dict[str, Any]) -> None:
    primary = _read_json(output / "primary_summary.json")
    reference = _read_json(output / "reference_summary.json")
    current_tool_hash = _sha256(Path(__file__))
    for run in (primary, reference):
        if run["recertification_tool_sha256"] != current_tool_hash:
            raise ValueError("Step 4A.3 tool changed between calculation and seal")
        _verify_run_payload(run)

    compared_sections = (
        "source_input_checksums",
        "feature_rows",
        "feature_columns",
        "feature_column_count",
        "feature_schema_hash",
        "feature_hashes",
        "audits",
        "snapshot_semantics",
        "bucket_close_classification",
        "original_integrity_checks",
        "superseded_original_gate_results",
        "unchanged_feature_reproduction",
        "amended_integrity_checks",
        "formal_integrity_pass",
    )
    matching_sections = {name: primary[name] == reference[name] for name in compared_sections}
    parquet_identical = primary["feature_parquet"]["sha256"] == reference["feature_parquet"]["sha256"]
    reproduction_pass = all(matching_sections.values()) and parquet_identical
    primary_integrity = bool(primary["formal_integrity_pass"])
    reference_integrity = bool(reference["formal_integrity_pass"])
    predecessor_source_pass = bool(
        context["predecessor_seals_valid"]
        and context["original_engine_bound"]
        and context["base_context"]["predecessor_and_source_seals_valid"]
        and context["base_context"]["required_input_columns_present"]
    )
    if not predecessor_source_pass:
        status = "FAIL_PREDECESSOR_OR_SOURCE_INTEGRITY"
    elif not primary_integrity or not reference_integrity:
        status = "FAIL_FEATURE_INTEGRITY_RECERTIFICATION"
    elif not reproduction_pass:
        status = "FAIL_RECERTIFICATION_REPRODUCTION"
    else:
        status = "PASS_FEATURE_INTEGRITY_RECERTIFICATION"

    formal_gates = {
        "predecessor_and_source_seals_valid": predecessor_source_pass,
        "primary_amended_integrity_pass": primary_integrity,
        "reference_amended_integrity_pass": reference_integrity,
        "unchanged_feature_payload_matches_original": all(primary["unchanged_feature_reproduction"].values()) and all(reference["unchanged_feature_reproduction"].values()),
        "source_input_checksums_identical": matching_sections["source_input_checksums"],
        "feature_counts_schema_hashes_and_payload_identical": all(matching_sections[name] for name in ("feature_rows", "feature_columns", "feature_column_count", "feature_schema_hash", "feature_hashes")) and parquet_identical,
        "technical_diagnostics_identical": matching_sections["audits"],
        "snapshot_semantics_identical": matching_sections["snapshot_semantics"],
        "crossed_bucket_close_classification_identical": matching_sections["bucket_close_classification"],
        "amended_and_unchanged_integrity_gates_identical": matching_sections["amended_integrity_checks"],
        "no_mbo_mbp_alignment": primary["mbo_mbp_alignment_attempts"] == 0 and reference["mbo_mbp_alignment_attempts"] == 0,
        "no_filter_repair_acquisition_other_date_value_inspection_outcome_signal_execution_or_pnl": all(
            not run[key]
            for run in (primary, reference)
            for key in (
                "source_rows_filtered_dropped_repaired_or_relabeled",
                "additional_data_acquired",
                "another_date_inspected",
                "market_values_human_or_model_inspected",
                "outcomes_accessed",
                "signals_calculated",
                "execution_optimized",
                "pnl_calculated",
            )
        ),
    }
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_4A3_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS_FEATURE_INTEGRITY_RECERTIFICATION",
        "classification": "ENGINEERING_ONLY_FEATURE_INTEGRITY_RECERTIFICATION",
        "research_or_validation_credit": "NONE",
        "predecessors": {
            "step_4a": "FAIL_FEATURE_INTEGRITY",
            "step_4a1": "FAIL_DIAGNOSTIC_INTEGRITY",
            "step_4a2": "PASS_DISPOSITION_REPRODUCTION",
        },
        "predecessor_verdicts_preserved": True,
        "formal_gates": formal_gates,
        "passed_formal_gates": sum(formal_gates.values()),
        "total_formal_gates": len(formal_gates),
        "reproduction": {
            "pass": reproduction_pass,
            "matching_sections": matching_sections,
            "parquet_sha256_identical": parquet_identical,
        },
        "amendments_applied": {
            "bad_ts_recv": "CONFIRMED_SNAPSHOT_SEMANTICS_GATE",
            "crossed_book": "CONTINUOUS_MATCHING_BUCKET_CLOSE_GATE",
        },
        "superseded_original_gate_results": primary["superseded_original_gate_results"],
        "snapshot_semantics": primary["snapshot_semantics"],
        "bucket_close_classification": primary["bucket_close_classification"],
        "raw_continuous_crossed_source_rows_reported_not_gated": primary["audits"]["mbp10"]["continuous_crossed_book_rows"],
        "unchanged_feature_reproduction": primary["unchanged_feature_reproduction"],
        "feature_rows": primary["feature_rows"],
        "feature_columns": primary["feature_column_count"],
        "complete_row_checksum": primary["feature_hashes"]["complete_row_checksum"],
        "feature_parquet_sha256": primary["feature_parquet"]["sha256"],
        "source_rows_filtered_dropped_repaired_or_relabeled": False,
        "additional_data_acquired": False,
        "another_date_inspected": False,
        "market_values_reported_or_inspected": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
        "completion_policy": "Preserve this recertification result and stop without research.",
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    verdict_path = output / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_text_atomic(REPORT_PATH, _render_report(verdict))

    artifacts = (
        output / "primary_features.parquet",
        output / "primary_summary.json",
        output / "reference_features.parquet",
        output / "reference_summary.json",
        verdict_path,
        REPORT_PATH,
    )
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_4A3_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "classification": "ENGINEERING_ONLY_FEATURE_INTEGRITY_RECERTIFICATION",
        "research_or_validation_credit": "NONE",
        "amendment": _file_record(AMENDMENT_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "step4a_manifest": _file_record(STEP4A_MANIFEST_PATH),
        "step4a1_manifest": _file_record(STEP4A1_MANIFEST_PATH),
        "step4a2_manifest": _file_record(STEP4A2_MANIFEST_PATH),
        "mbo_source": _file_record(base.MBO_PATH),
        "mbp10_source": _file_record(base.MBP_PATH),
        "unchanged_original_feature_tool": _file_record(Path(base.__file__)),
        "recertification_tool": _file_record(Path(__file__)),
        "artifacts": [_file_record(path) for path in artifacts],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
        "feature_calculations_changed": False,
        "only_two_integrity_classifications_replaced": True,
        "source_rows_filtered_dropped_repaired_or_relabeled": False,
        "mbo_mbp_alignment_attempts": 0,
        "additional_data_acquired": False,
        "another_date_inspected": False,
        "market_values_human_or_model_inspected": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4A3_SEALED",
                "status": status,
                "formal_pass": verdict["formal_pass"],
                "reproduction_pass": reproduction_pass,
                "feature_payload_matches_original": formal_gates["unchanged_feature_payload_matches_original"],
                "snapshot_semantic_violations": verdict["snapshot_semantics"]["combined"]["violating_rows"],
                "continuous_crossed_bucket_closes": verdict["bucket_close_classification"]["continuous_crossed_bucket_closes"],
                "pre_open_crossed_bucket_closes": verdict["bucket_close_classification"]["by_state"]["PRE_OPEN"]["crossed_bucket_closes"],
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _render_report(verdict: dict[str, Any]) -> str:
    snapshot = verdict["snapshot_semantics"]
    buckets = verdict["bucket_close_classification"]
    return "\n".join(
        [
            "# GC Microstructure Step 4A.3 — Feature-Integrity Recertification",
            "",
            "## Formal verdict",
            "",
            f"`{verdict['status']}`",
            "",
            "The original Step 4A feature calculations were rerun unchanged. Only the two sealed integrity classifications were replaced.",
            "",
            "## Snapshot-semantic gate",
            "",
            f"- BAD_TS_RECV rows: {snapshot['combined']['bad_flag_rows']:,}.",
            f"- Rows satisfying every frozen snapshot predicate: {snapshot['combined']['passing_rows']:,}.",
            f"- Violating rows: {snapshot['combined']['violating_rows']:,}.",
            "- No flag was cleared and no source row was filtered, dropped, repaired, or relabeled.",
            "",
            "## Bucket-close crossed-book gate",
            "",
            f"- Continuous-matching crossed bucket closes: {buckets['by_state']['CONTINUOUS_MATCHING']['crossed_bucket_closes']:,} of {buckets['by_state']['CONTINUOUS_MATCHING']['bucket_closes']:,}.",
            f"- Maintenance crossed bucket closes: {buckets['by_state']['MAINTENANCE']['crossed_bucket_closes']:,} of {buckets['by_state']['MAINTENANCE']['bucket_closes']:,}.",
            f"- Pre-open crossed bucket closes: {buckets['by_state']['PRE_OPEN']['crossed_bucket_closes']:,} of {buckets['by_state']['PRE_OPEN']['bucket_closes']:,}.",
            f"- Raw continuous crossed source rows reported but not gated: {verdict['raw_continuous_crossed_source_rows_reported_not_gated']:,}.",
            "",
            "## Exact feature reproduction",
            "",
            f"- Feature rows: {verdict['feature_rows']:,}.",
            f"- Feature columns: {verdict['feature_columns']:,}.",
            f"- Complete-row checksum: `{verdict['complete_row_checksum']}`.",
            f"- Feature Parquet SHA-256: `{verdict['feature_parquet_sha256']}`.",
            f"- Independent reproduction pass: `{str(verdict['reproduction']['pass']).lower()}`.",
            "",
            "## Preserved history and restrictions",
            "",
            "Step 4A FAIL_FEATURE_INTEGRITY, Step 4A.1 FAIL_DIAGNOSTIC_INTEGRITY, and Step 4A.2 PASS_DISPOSITION_REPRODUCTION remain unchanged.",
            "",
            "No additional data, other date, market-value inspection, outcome, edge discovery, signal, execution optimization, trade, PnL, R multiple, or account return was accessed or calculated.",
            "",
            "This engineering-only date receives zero research or validation credit.",
            "",
        ]
    )


def _verify_run_payload(run: dict[str, Any]) -> None:
    if run["amendment_sha256"] != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Run amendment hash mismatch")
    if run["freeze_sha256"] != EXPECTED_FREEZE_SHA256:
        raise ValueError("Run freeze hash mismatch")
    if run["unchanged_original_tool_sha256"] != EXPECTED_ORIGINAL_TOOL_SHA256:
        raise ValueError("Run original feature tool mismatch")
    _verify_file_record(run["feature_parquet"])
    if run["feature_parquet"]["sha256"] != EXPECTED_PARQUET_SHA256:
        raise ValueError("Run feature payload differs from original Step 4A")


def _verify_seal(output: Path) -> None:
    context = _verified_context()
    _assert_amendment_matches_code(context["amendment"])
    manifest = _read_json(output / "manifest.json")
    verdict = _read_json(output / "verdict.json")
    if manifest["manifest_hash"] != _canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}):
        raise ValueError("Step 4A.3 manifest canonical hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash({key: value for key, value in verdict.items() if key != "verdict_hash"}):
        raise ValueError("Step 4A.3 verdict canonical hash mismatch")
    for record in manifest["artifacts"]:
        _verify_file_record(record)
    for key, expected in (
        ("amendment", EXPECTED_AMENDMENT_SHA256),
        ("freeze_receipt", EXPECTED_FREEZE_SHA256),
        ("mbo_source", base.EXPECTED_MBO_SHA256),
        ("mbp10_source", base.EXPECTED_MBP_SHA256),
        ("unchanged_original_feature_tool", EXPECTED_ORIGINAL_TOOL_SHA256),
    ):
        if manifest[key]["sha256"] != expected:
            raise ValueError(f"Manifest {key} hash declaration mismatch")
        _verify_file_record(manifest[key])
    for key in ("step4a_manifest", "step4a1_manifest", "step4a2_manifest"):
        _verify_file_record(manifest[key])
    if manifest["recertification_tool"]["sha256"] != _sha256(Path(__file__)):
        raise ValueError("Step 4A.3 recertification tool changed")
    if manifest["status"] != verdict["status"]:
        raise ValueError("Step 4A.3 manifest and verdict statuses differ")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4A3_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]),
                "predecessor_verdicts_preserved": manifest["predecessor_verdicts_preserved"],
                "feature_calculations_changed": manifest["feature_calculations_changed"],
                "only_two_integrity_classifications_replaced": manifest["only_two_integrity_classifications_replaced"],
                "source_rows_filtered_dropped_repaired_or_relabeled": manifest["source_rows_filtered_dropped_repaired_or_relabeled"],
                "additional_data_acquired": manifest["additional_data_acquired"],
                "another_date_inspected": manifest["another_date_inspected"],
                "outcomes_accessed": manifest["outcomes_accessed"],
                "signals_calculated": manifest["signals_calculated"],
                "pnl_calculated": manifest["pnl_calculated"],
                "research_or_validation_credit": manifest["research_or_validation_credit"],
            },
            sort_keys=True,
        )
    )


def _verified_context() -> dict[str, Any]:
    if _sha256(AMENDMENT_PATH) != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Step 4A.3 amendment changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 4A.3 freeze receipt changed")
    amendment = _read_json(AMENDMENT_PATH)
    freeze = _read_json(FREEZE_PATH)
    if freeze["amendment"]["sha256"] != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Step 4A.3 freeze does not bind amendment")

    requirements = (
        (STEP4A_MANIFEST_PATH, EXPECTED_STEP4A_MANIFEST_HASH, EXPECTED_STEP4A_VERDICT_HASH, "FAIL_FEATURE_INTEGRITY"),
        (STEP4A1_MANIFEST_PATH, EXPECTED_STEP4A1_MANIFEST_HASH, EXPECTED_STEP4A1_VERDICT_HASH, "FAIL_DIAGNOSTIC_INTEGRITY"),
        (STEP4A2_MANIFEST_PATH, EXPECTED_STEP4A2_MANIFEST_HASH, EXPECTED_STEP4A2_VERDICT_HASH, "PASS_DISPOSITION_REPRODUCTION"),
    )
    for path, manifest_hash, verdict_hash, status in requirements:
        manifest = _read_json(path)
        if manifest.get("manifest_hash") != manifest_hash or _canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}) != manifest_hash:
            raise ValueError(f"Predecessor manifest changed: {path}")
        if manifest.get("verdict_hash") != verdict_hash or manifest.get("status") != status:
            raise ValueError(f"Predecessor verdict declaration changed: {path}")
        for record in manifest["artifacts"]:
            _verify_file_record(record)

    step4a1_verdict = _read_json(STEP4A1_MANIFEST_PATH.parent / "verdict.json")
    if step4a1_verdict["findings"]["bad_ts_recv_snapshot_semantics"] != "CONFIRMED":
        raise ValueError("Step 4A.1 confirmed snapshot finding changed")
    step4a2_verdict = _read_json(STEP4A2_MANIFEST_PATH.parent / "verdict.json")
    if step4a2_verdict["finding"] != "CONTINUOUS_BUCKET_CLOSE_STATES_CLEAN" or step4a2_verdict["recommendation"]["id"] != "RECERTIFY_WITH_SNAPSHOT_EXCEPTION_AND_CONTINUOUS_BUCKET_CLOSE_GATE_V0_1":
        raise ValueError("Step 4A.2 disposition changed")
    if _sha256(Path(base.__file__)) != EXPECTED_ORIGINAL_TOOL_SHA256:
        raise ValueError("Original Step 4A feature engine changed")
    base_context = base._verified_context()
    base._assert_protocol_matches_code(base_context["protocol"])
    return {
        "amendment": amendment,
        "freeze": freeze,
        "predecessor_seals_valid": True,
        "original_engine_bound": True,
        "base_context": base_context,
    }


def _assert_amendment_matches_code(amendment: dict[str, Any]) -> None:
    pipeline = amendment["unchanged_feature_pipeline"]
    if (
        pipeline["required_original_tool_sha256"] != EXPECTED_ORIGINAL_TOOL_SHA256
        or pipeline["expected_feature_rows"] != base.BUCKET_COUNT
        or pipeline["expected_feature_columns"] != len(base.FEATURE_COLUMNS)
        or pipeline["expected_feature_schema_hash"] != EXPECTED_SCHEMA_HASH
        or pipeline["expected_complete_row_checksum"] != EXPECTED_COMPLETE_ROW_CHECKSUM
        or pipeline["expected_feature_parquet_sha256"] != EXPECTED_PARQUET_SHA256
        or pipeline["expected_feature_parquet_bytes"] != EXPECTED_PARQUET_BYTES
        or pipeline["expected_source_input_checksums"] != EXPECTED_SOURCE_CHECKSUMS
    ):
        raise ValueError("Step 4A.3 unchanged-pipeline binding differs from code")
    if amendment["amendment_one_bad_ts_recv"]["required_exact_counts"] != EXPECTED_BAD_COUNTS:
        raise ValueError("Step 4A.3 snapshot count contract differs from code")
    crossed = amendment["amendment_two_crossed_book"]
    if crossed["required_reporting_by_segment"] != EXPECTED_BY_SEGMENT or crossed["required_reporting_by_market_state"] != EXPECTED_BY_STATE or crossed["required_continuous_crossed_bucket_closes"] != 0 or crossed["raw_continuous_crossed_source_rows"]["required_reported_count"] != 1:
        raise ValueError("Step 4A.3 crossed-book contract differs from code")


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _verify_file_record(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if not path.exists() or path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
        raise ValueError(f"Sealed file changed: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
