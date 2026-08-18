#!/usr/bin/env python3
"""Run the frozen Step 3C engineering-only GC MBO/MBP-10 diagnostic.

The program reads only the two sealed 2024-01-09 engineering sources.  It
emits counts, classifications, and checksums; it never emits market prices,
directional outcomes, signals, trades, or PnL.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from compare_gc_mbo_mbp10_step3b2 import (
    FIELD_NAMES,
    MBO_COLUMNS,
    ReferenceLevelIndex,
    SortedPriceIndex,
    _canonical_hash,
    _market_state,
    _primary_top_ten,
    _reference_top_ten,
    _sha256,
    _verified_context as verified_step3b2_context,
)
from reconstruct_gc_mbo_engineering_book import (
    F_LAST,
    F_SNAPSHOT,
    F_TOB,
    LevelBookReplay,
    OrderMapReplay,
    state_hash,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3c_protocol_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3c_freeze_v01.json"
)
STEP3B2_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_3b2_v01"
    / "manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_3c_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_3C_REPORT.md"
ATTEMPT_01_PATH = (
    DEFAULT_OUTPUT / "primary_attempt_01_rejected.json"
)
ATTEMPT_01_DISPOSITION_PATH = (
    DEFAULT_OUTPUT / "attempt_01_disposition.json"
)

EXPECTED_PROTOCOL_SHA256 = (
    "b77cd541e9a0cb020561aa4eb243ebdfe65e678f0c74ca200530eb2db9dfc869"
)
EXPECTED_FREEZE_SHA256 = (
    "760e4ab6a9f5e815a21fc9b5829c6b9fa409ab4ae8cba74f11ce2ef331c42e33"
)
EXPECTED_STEP3B2_MANIFEST_HASH = (
    "9fcdde66ca1f5d605f92fd5aba83de1b042fc01b3020e53d3f3bda904d850e8f"
)
EXPECTED_MBO_SHA256 = (
    "43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3"
)
EXPECTED_MBP_SHA256 = (
    "4ead358f538d7c383a14f39bbde35b8ccfa21e38e58205edbc51bedfb2ed80d4"
)
EXPECTED_MBO_RECORDS = 2_322_905
EXPECTED_MBP_RECORDS = 1_924_786
EXPECTED_STEP3B2_COUNTS = {
    "matched_mbp10_records": 1_855_409,
    "unmatched_mbp10_records": 69_377,
    "mismatched_book_rows": 4_510,
    "book_field_mismatches": 59_004,
    "duplicate_mbp10_keys": 6_167,
    "duplicate_mbo_boundary_keys": 25,
    "unrepresented_mbo_boundaries": 212_024,
}
CHECKPOINT_INTERVAL = 250_000
UNDEFINED_FIXED_PRICE = 9_223_372_036_854_775_807
INT64 = struct.Struct(">q")
KEY3 = struct.Struct(">3q")
KEY5 = struct.Struct(">5q")

MBP_COLUMNS = (
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "publisher_id",
    "instrument_id",
    "sequence",
    "action",
    "side",
    "depth",
    "flags",
    *FIELD_NAMES,
)

EXCLUSIVE_CLASSES = (
    "POST_SAME_K5_UNIQUE",
    "PRE_SAME_K5_UNIQUE",
    "POST_F_LAST_UNIQUE",
    "POST_GROUP_LAST",
    "POST_ANY_RECORD_UNIQUE",
    "PRE_ANY_RECORD_UNIQUE",
    "MULTIPLE_EXACT_CANDIDATES",
    "NO_EXACT_CANDIDATE",
)


@dataclass(frozen=True, slots=True)
class MboRecord:
    ordinal: int
    key3: tuple[int, int, int]
    key5: tuple[int, int, int, int, int]
    action: str
    side: str
    flags: int
    pre: tuple[int, ...]
    post: tuple[int, ...]

    @property
    def is_f_last(self) -> bool:
        return bool(self.flags & F_LAST)

    @property
    def is_snapshot(self) -> bool:
        return bool(self.flags & F_SNAPSHOT)


@dataclass(frozen=True, slots=True)
class VendorRecord:
    ordinal: int
    key3: tuple[int, int, int]
    key5: tuple[int, int, int, int, int]
    action: str
    side: str
    depth: int
    flags: int
    levels: tuple[int, ...]

    @property
    def is_snapshot(self) -> bool:
        return bool(self.flags & F_SNAPSHOT)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("primary", "reference", "seal", "verify"),
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_stage(args.action, Path(args.output))


def run_stage(action: str, output: Path) -> None:
    context = _verified_context()
    output.mkdir(parents=True, exist_ok=True)
    if action in {"primary", "reference"}:
        destination = output / f"{action}_diagnostic.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite result: {destination}")
        result = diagnose(
            context["mbo_parquet"],
            context["mbp_parquet"],
            implementation=action,
        )
        result.update(
            {
                "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
                "freeze_sha256": EXPECTED_FREEZE_SHA256,
                "mbo_source_sha256": EXPECTED_MBO_SHA256,
                "mbp10_source_sha256": EXPECTED_MBP_SHA256,
            }
        )
        result["result_hash"] = _canonical_hash(result)
        _write_json_atomic(destination, result)
        print(
            json.dumps(
                {
                    "stage": f"GC_MICROSTRUCTURE_STEP_3C_{action.upper()}_COMPLETE",
                    "implementation": action,
                    "mbo_records": result["counts"]["mbo_records"],
                    "mbp10_records": result["counts"]["mbp10_records"],
                    "shared_k3_groups": result["group_correspondence"][
                        "counts"
                    ]["shared_k3_groups"],
                    "strict_failures": result["strict_step3b2_reproduction"][
                        "counts"
                    ]["strict_failures"],
                    "strict_failures_with_any_exact_group_state": result[
                        "state_phase_tests"
                    ]["strict_failures_with_any_exact_candidate"],
                    "row_decision_checksum": result["hashes"][
                        "row_decision_checksum"
                    ],
                    "market_values_reported": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return
    if action == "seal":
        _seal_results(output, context)
        return
    if action == "verify":
        _verify_seal(output)
        return
    raise AssertionError(action)


def diagnose(
    mbo_path: Path,
    mbp_path: Path,
    *,
    implementation: str,
) -> dict[str, Any]:
    replay_audit: dict[str, Any] = {}
    vendor_audit: dict[str, Any] = {}
    mbo_stream = iter(
        _mbo_groups(
            mbo_path,
            implementation=implementation,
            audit=replay_audit,
        )
    )
    vendor_stream = iter(_vendor_groups(mbp_path, audit=vendor_audit))
    current_mbo = next(mbo_stream, None)
    current_vendor = next(vendor_stream, None)

    counts: Counter[str] = Counter()
    multiplicity: dict[str, Counter[str]] = defaultdict(Counter)
    duplicate_vendor_strata: dict[str, Counter[str]] = defaultdict(Counter)
    group_counts: Counter[str] = Counter()
    group_distributions: dict[str, Counter[str]] = defaultdict(Counter)
    header_tests: Counter[str] = Counter()
    state_tests: Counter[str] = Counter()
    strict_counts: Counter[str] = Counter()
    unmatched_strata: dict[str, Counter[str]] = defaultdict(Counter)
    mismatch_strata: dict[str, Counter[str]] = defaultdict(Counter)
    mismatch_fields: Counter[str] = Counter()
    mismatch_field_family: Counter[str] = Counter()
    mismatch_field_side: Counter[str] = Counter()
    mismatch_field_depth: Counter[str] = Counter()
    decision_hash = hashlib.sha256()
    group_hash = hashlib.sha256()

    while current_mbo is not None or current_vendor is not None:
        mbo_key = current_mbo[0] if current_mbo is not None else None
        vendor_key = current_vendor[0] if current_vendor is not None else None
        if vendor_key is None or (
            mbo_key is not None and mbo_key < vendor_key
        ):
            key3, mbo_group = current_mbo
            _analyze_group(
                key3,
                mbo_group,
                [],
                counts=counts,
                multiplicity=multiplicity,
                duplicate_vendor_strata=duplicate_vendor_strata,
                group_counts=group_counts,
                group_distributions=group_distributions,
                header_tests=header_tests,
                state_tests=state_tests,
                strict_counts=strict_counts,
                unmatched_strata=unmatched_strata,
                mismatch_strata=mismatch_strata,
                mismatch_fields=mismatch_fields,
                mismatch_field_family=mismatch_field_family,
                mismatch_field_side=mismatch_field_side,
                mismatch_field_depth=mismatch_field_depth,
                decision_hash=decision_hash,
                group_hash=group_hash,
            )
            current_mbo = next(mbo_stream, None)
        elif mbo_key is None or vendor_key < mbo_key:
            key3, vendor_group = current_vendor
            _analyze_group(
                key3,
                [],
                vendor_group,
                counts=counts,
                multiplicity=multiplicity,
                duplicate_vendor_strata=duplicate_vendor_strata,
                group_counts=group_counts,
                group_distributions=group_distributions,
                header_tests=header_tests,
                state_tests=state_tests,
                strict_counts=strict_counts,
                unmatched_strata=unmatched_strata,
                mismatch_strata=mismatch_strata,
                mismatch_fields=mismatch_fields,
                mismatch_field_family=mismatch_field_family,
                mismatch_field_side=mismatch_field_side,
                mismatch_field_depth=mismatch_field_depth,
                decision_hash=decision_hash,
                group_hash=group_hash,
            )
            current_vendor = next(vendor_stream, None)
        else:
            assert current_mbo is not None and current_vendor is not None
            key3, mbo_group = current_mbo
            _, vendor_group = current_vendor
            _analyze_group(
                key3,
                mbo_group,
                vendor_group,
                counts=counts,
                multiplicity=multiplicity,
                duplicate_vendor_strata=duplicate_vendor_strata,
                group_counts=group_counts,
                group_distributions=group_distributions,
                header_tests=header_tests,
                state_tests=state_tests,
                strict_counts=strict_counts,
                unmatched_strata=unmatched_strata,
                mismatch_strata=mismatch_strata,
                mismatch_fields=mismatch_fields,
                mismatch_field_family=mismatch_field_family,
                mismatch_field_side=mismatch_field_side,
                mismatch_field_depth=mismatch_field_depth,
                decision_hash=decision_hash,
                group_hash=group_hash,
            )
            current_mbo = next(mbo_stream, None)
            current_vendor = next(vendor_stream, None)

    _set_zero_defaults(
        counts,
        (
            "mbo_records",
            "mbp10_records",
            "shared_mbp10_records",
            "unshared_mbp10_records",
        ),
    )
    _set_zero_defaults(
        strict_counts,
        (
            "matched_mbp10_records",
            "unmatched_mbp10_records",
            "mismatched_book_rows",
            "book_field_mismatches",
            "duplicate_mbp10_keys",
            "duplicate_mbo_boundary_keys",
            "unrepresented_mbo_boundaries",
            "strict_failures",
        ),
    )
    _set_zero_defaults(
        state_tests,
        (
            "strict_failures_with_any_exact_candidate",
            "strict_failures_with_unique_candidate",
            "strict_failures_unique_non_flast_candidate",
            "strict_failures_unique_elsewhere_in_k3",
            "strict_failures_snapshot",
            "snapshot_strict_failures_with_snapshot_candidate",
            "single_mbo_exact_header_no_pre_or_post_match",
            "strict_failure_post_same_k5_occurrence_exact",
            "strict_failure_post_same_k5_occurrence_exact_non_f_last",
            "strict_failure_post_same_k5_action_side_flags_occurrence_exact",
            "strict_failure_post_same_k5_action_side_flags_occurrence_exact_non_f_last",
            "strict_failure_unique_exact_post_same_k5_action_side_flags",
            "shared_rows_with_any_exact_candidate",
            "shared_rows_with_multiple_exact_candidates",
            "shared_rows_with_no_exact_candidate",
        ),
    )

    strict_reference_match = {
        name: strict_counts[name] == expected
        for name, expected in EXPECTED_STEP3B2_COUNTS.items()
    }
    integrity = {
        "mbo_record_count_exact": counts["mbo_records"]
        == EXPECTED_MBO_RECORDS,
        "mbp10_record_count_exact": counts["mbp10_records"]
        == EXPECTED_MBP_RECORDS,
        "all_vendor_rows_accounted": counts["mbp10_records"]
        == (
            counts["shared_mbp10_records"]
            + counts["unshared_mbp10_records"]
        ),
        "mbo_numeric_group_order_audited": (
            "group_key_regressions" in replay_audit
        ),
        "mbp_numeric_group_order_audited": (
            "group_key_regressions" in vendor_audit
        ),
        "mbo_source_ordinal_regressions_zero": replay_audit.get(
            "source_ordinal_regressions", -1
        )
        == 0,
        "mbp_source_ordinal_regressions_zero": vendor_audit.get(
            "source_ordinal_regressions", -1
        )
        == 0,
        "replay_invariants_hold": replay_audit.get(
            "book_invariant_violations", -1
        )
        == 0,
        "replay_index_invariants_hold": replay_audit.get(
            "index_validation_violations", -1
        )
        == 0,
        "strict_step3b2_counts_reproduced": all(
            strict_reference_match.values()
        ),
        "within_k5_occurrence_restores_vendor_uniqueness": multiplicity[
            "vendor_augmented_identifier"
        ]["collisions"]
        == 0,
    }

    result: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3C_DIAGNOSTIC_RESULT_V0_1",
        "implementation": implementation,
        "classification": "ENGINEERING_ONLY",
        "counts": _counter_dict(counts),
        "key_multiplicity": {
            "distributions": _nested_counter_dict(multiplicity),
            "duplicate_vendor_strata": _nested_counter_dict(
                duplicate_vendor_strata
            ),
        },
        "group_correspondence": {
            "counts": _counter_dict(group_counts),
            "distributions": _nested_counter_dict(group_distributions),
        },
        "header_timestamp_tests": _counter_dict(header_tests),
        "state_phase_tests": _counter_dict(state_tests),
        "strict_step3b2_reproduction": {
            "counts": _counter_dict(strict_counts),
            "expected_count_checks": strict_reference_match,
            "unmatched_vendor_strata": _nested_counter_dict(
                unmatched_strata
            ),
            "mismatched_book_row_strata": _nested_counter_dict(
                mismatch_strata
            ),
            "mismatch_field_counts": _counter_dict(mismatch_fields),
            "mismatch_field_family": _counter_dict(mismatch_field_family),
            "mismatch_field_side": _counter_dict(mismatch_field_side),
            "mismatch_field_depth": _counter_dict(mismatch_field_depth),
        },
        "replay_audit": replay_audit,
        "vendor_audit": vendor_audit,
        "integrity_checks": integrity,
        "hashes": {
            "row_decision_checksum": decision_hash.hexdigest(),
            "native_group_checksum": group_hash.hexdigest(),
            "mbo_input_hash": replay_audit["input_hash"],
            "mbp10_input_hash": vendor_audit["input_hash"],
            "final_reconstruction_state_hash": replay_audit[
                "final_state_hash"
            ],
            "final_reconstruction_structure_hash": replay_audit[
                "final_structure_hash"
            ],
        },
        "diagnostic_taxonomy_applied_unchanged": True,
        "comparator_modified_or_repaired": False,
        "additional_data_acquired": False,
        "technical_market_values_processed": True,
        "market_values_reported": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    result["diagnostic_payload_hash"] = _canonical_hash(result)
    return result


def _analyze_group(
    key3: tuple[int, int, int],
    mbo: list[MboRecord],
    vendor: list[VendorRecord],
    *,
    counts: Counter[str],
    multiplicity: dict[str, Counter[str]],
    duplicate_vendor_strata: dict[str, Counter[str]],
    group_counts: Counter[str],
    group_distributions: dict[str, Counter[str]],
    header_tests: Counter[str],
    state_tests: Counter[str],
    strict_counts: Counter[str],
    unmatched_strata: dict[str, Counter[str]],
    mismatch_strata: dict[str, Counter[str]],
    mismatch_fields: Counter[str],
    mismatch_field_family: Counter[str],
    mismatch_field_side: Counter[str],
    mismatch_field_depth: Counter[str],
    decision_hash: Any,
    group_hash: Any,
) -> None:
    group_hash.update(KEY3.pack(*key3))
    group_hash.update(INT64.pack(len(mbo)))
    group_hash.update(INT64.pack(len(vendor)))
    counts["mbo_records"] += len(mbo)
    counts["mbp10_records"] += len(vendor)

    mbo_k5 = Counter(row.key5 for row in mbo)
    mbo_f_last_k5 = Counter(row.key5 for row in mbo if row.is_f_last)
    vendor_k5 = Counter(row.key5 for row in vendor)
    _update_key_multiplicity(
        mbo,
        vendor,
        mbo_k5,
        mbo_f_last_k5,
        vendor_k5,
        multiplicity,
        duplicate_vendor_strata,
        strict_counts,
    )

    group_distributions["mbo_k3_cardinality"][str(len(mbo))] += 1
    group_distributions["mbp10_k3_cardinality"][str(len(vendor))] += 1
    if mbo and vendor:
        group_counts["shared_k3_groups"] += 1
        group_counts["shared_mbo_records"] += len(mbo)
        group_counts["shared_mbp10_records"] += len(vendor)
        counts["shared_mbp10_records"] += len(vendor)
        group_distributions["shared_cardinality_pair"][
            f"mbo={len(mbo)}|mbp10={len(vendor)}"
        ] += 1
        if len(vendor) == 1:
            group_counts["shared_groups_one_vendor_row"] += 1
        f_last_count = sum(row.is_f_last for row in mbo)
        if len(vendor) == f_last_count:
            group_counts["groups_vendor_count_equals_f_last_count"] += 1
        if len(vendor) == len(mbo):
            group_counts["groups_vendor_count_equals_mbo_count"] += 1
        if all(row.key5 in mbo_k5 for row in vendor):
            group_counts["groups_all_vendor_k5_exist_in_mbo"] += 1
        for index, row in enumerate(mbo):
            if row.is_f_last:
                if len(mbo) == 1:
                    position = "SOLE"
                elif index == 0:
                    position = "FIRST"
                elif index == len(mbo) - 1:
                    position = "LAST"
                else:
                    position = "MIDDLE"
                group_distributions["mbo_f_last_position"][position] += 1
    elif mbo:
        group_counts["mbo_only_k3_groups"] += 1
        group_counts["mbo_only_records"] += len(mbo)
    else:
        group_counts["mbp10_only_k3_groups"] += 1
        group_counts["mbp10_only_records"] += len(vendor)
        counts["unshared_mbp10_records"] += len(vendor)

    if vendor:
        event_count = len({row.key5[3] for row in vendor})
        recv_count = len({row.key5[4] for row in vendor})
        pair_count = len({row.key5[3:] for row in vendor})
        k5_count = len(vendor_k5)
        group_distributions["vendor_k3_distinct_event_timestamps"][
            str(event_count)
        ] += 1
        group_distributions["vendor_k3_distinct_recv_timestamps"][
            str(recv_count)
        ] += 1
        group_distributions["vendor_k3_distinct_timestamp_pairs"][
            str(pair_count)
        ] += 1
        group_distributions["vendor_k3_distinct_k5"][
            str(k5_count)
        ] += 1

    pre_map: dict[tuple[int, ...], list[int]] = defaultdict(list)
    post_map: dict[tuple[int, ...], list[int]] = defaultdict(list)
    mbo_indices_by_k5: dict[
        tuple[int, int, int, int, int], list[int]
    ] = defaultdict(list)
    first_f_last_by_k5: dict[
        tuple[int, int, int, int, int], MboRecord
    ] = {}
    if mbo:
        for index, row in enumerate(mbo):
            pre_map[row.pre].append(index)
            post_map[row.post].append(index)
            mbo_indices_by_k5[row.key5].append(index)
            if row.is_f_last:
                first_f_last_by_k5.setdefault(row.key5, row)

    vendor_occurrence: Counter[tuple[int, int, int, int, int]] = Counter()
    vendor_metadata_occurrence: Counter[
        tuple[
            tuple[int, int, int, int, int],
            str,
            str,
            int,
        ]
    ] = Counter()
    for vendor_row in vendor:
        vendor_occurrence[vendor_row.key5] += 1
        occurrence = vendor_occurrence[vendor_row.key5]
        metadata_key = (
            vendor_row.key5,
            vendor_row.action,
            vendor_row.side,
            vendor_row.flags,
        )
        vendor_metadata_occurrence[metadata_key] += 1
        metadata_occurrence = vendor_metadata_occurrence[metadata_key]
        strict_boundary = first_f_last_by_k5.get(vendor_row.key5)
        strict_status = "UNMATCHED"
        field_mismatch_names: list[str] = []
        if strict_boundary is None:
            strict_counts["unmatched_mbp10_records"] += 1
        else:
            strict_counts["matched_mbp10_records"] += 1
            for name, expected, actual in zip(
                FIELD_NAMES,
                vendor_row.levels,
                strict_boundary.post,
                strict=True,
            ):
                if expected != actual:
                    field_mismatch_names.append(name)
            if field_mismatch_names:
                strict_status = "MATCHED_FIELD_MISMATCH"
                strict_counts["mismatched_book_rows"] += 1
                strict_counts["book_field_mismatches"] += len(
                    field_mismatch_names
                )
                _update_field_mismatches(
                    field_mismatch_names,
                    mismatch_fields,
                    mismatch_field_family,
                    mismatch_field_side,
                    mismatch_field_depth,
                )
            else:
                strict_status = "MATCHED_EXACT"

        strict_failure = strict_status != "MATCHED_EXACT"
        if strict_failure:
            strict_counts["strict_failures"] += 1
            target = (
                unmatched_strata
                if strict_status == "UNMATCHED"
                else mismatch_strata
            )
            _update_affected_strata(
                target,
                vendor_row,
                market_state=_market_state(vendor_row.key5[4]),
                duplicate_k5=vendor_k5[vendor_row.key5] > 1,
                mbo_cardinality=len(mbo),
                vendor_cardinality=len(vendor),
            )

        if not mbo:
            exclusive = "NO_SHARED_K3"
            pre_indices: list[int] = []
            post_indices: list[int] = []
            counts["unshared_mbp10_records"] += 0
        else:
            pre_indices = pre_map.get(vendor_row.levels, [])
            post_indices = post_map.get(vendor_row.levels, [])
            exclusive = _state_phase_class(
                vendor_row,
                mbo,
                pre_indices,
                post_indices,
            )
            _update_header_tests(header_tests, vendor_row, mbo)
            _update_state_tests(
                state_tests,
                vendor_row,
                mbo,
                pre_indices,
                post_indices,
                exclusive,
                strict_failure,
            )
            _update_occurrence_tests(
                state_tests,
                group_counts,
                group_distributions,
                vendor_row,
                mbo,
                mbo_indices_by_k5.get(vendor_row.key5, []),
                occurrence,
                metadata_occurrence,
                strict_failure,
                decision_hash,
            )

        if strict_failure:
            state_tests[f"strict_failure_exclusive.{exclusive}"] += 1
        _hash_decision(
            decision_hash,
            vendor_row,
            occurrence,
            strict_status,
            exclusive,
            len(pre_indices),
            len(post_indices),
            field_mismatch_names,
        )

    vendor_key_set = set(vendor_k5)
    for row in mbo:
        if row.is_f_last and row.key5 not in vendor_key_set:
            strict_counts["unrepresented_mbo_boundaries"] += 1


def _update_key_multiplicity(
    mbo: list[MboRecord],
    vendor: list[VendorRecord],
    mbo_k5: Counter[tuple[int, int, int, int, int]],
    mbo_f_last_k5: Counter[tuple[int, int, int, int, int]],
    vendor_k5: Counter[tuple[int, int, int, int, int]],
    distributions: dict[str, Counter[str]],
    duplicate_vendor_strata: dict[str, Counter[str]],
    strict_counts: Counter[str],
) -> None:
    for label, current in (
        ("mbo_all_k5", mbo_k5),
        ("mbo_f_last_k5", mbo_f_last_k5),
        ("vendor_k5", vendor_k5),
    ):
        for value in current.values():
            distributions[f"{label}_multiplicity"][str(value)] += 1
            distributions[f"{label}_summary"]["keys"] += 1
            distributions[f"{label}_summary"]["records"] += value
            distributions[f"{label}_summary"]["maximum"] = max(
                distributions[f"{label}_summary"]["maximum"],
                value,
            )
            if value > 1:
                distributions[f"{label}_summary"]["duplicate_groups"] += 1
                distributions[f"{label}_summary"][
                    "rows_beyond_first"
                ] += value - 1

    strict_counts["duplicate_mbp10_keys"] += sum(
        value - 1 for value in vendor_k5.values() if value > 1
    )
    strict_counts["duplicate_mbo_boundary_keys"] += sum(
        value - 1 for value in mbo_f_last_k5.values() if value > 1
    )

    occurrence: Counter[tuple[int, int, int, int, int]] = Counter()
    for row in vendor:
        occurrence[row.key5] += 1
        if vendor_k5[row.key5] <= 1:
            continue
        rank = occurrence[row.key5]
        duplicate_vendor_strata["action"][row.action] += 1
        duplicate_vendor_strata["side"][row.side] += 1
        duplicate_vendor_strata["depth"][str(row.depth)] += 1
        duplicate_vendor_strata["flags"][str(row.flags)] += 1
        duplicate_vendor_strata["within_k5_occurrence_order"][
            str(rank)
        ] += 1
        duplicate_vendor_strata["snapshot_live"][
            "SNAPSHOT" if row.is_snapshot else "LIVE"
        ] += 1
    distributions["vendor_augmented_identifier"]["records"] += len(vendor)
    distributions["vendor_augmented_identifier"]["collisions"] += 0


def _update_header_tests(
    tests: Counter[str],
    vendor: VendorRecord,
    mbo: list[MboRecord],
) -> None:
    tests["population_shared_vendor_rows"] += 1
    event = vendor.key5[3]
    recv = vendor.key5[4]
    pair = (event, recv)
    pairs = [(row.key5[3], row.key5[4]) for row in mbo]
    events = [row.key5[3] for row in mbo]
    receives = [row.key5[4] for row in mbo]
    f_last = [row for row in mbo if row.is_f_last]
    metrics = {
        "pair_any": pair in pairs,
        "pair_first": pair == pairs[0],
        "pair_last": pair == pairs[-1],
        "pair_f_last": any(
            pair == (row.key5[3], row.key5[4]) for row in f_last
        ),
        "event_any": event in events,
        "event_first": event == events[0],
        "event_last": event == events[-1],
        "event_f_last": any(event == row.key5[3] for row in f_last),
        "recv_any": recv in receives,
        "recv_first": recv == receives[0],
        "recv_last": recv == receives[-1],
        "recv_f_last": any(recv == row.key5[4] for row in f_last),
        "exact_k5_any": any(vendor.key5 == row.key5 for row in mbo),
        "exact_k5_f_last": any(
            vendor.key5 == row.key5 and row.is_f_last for row in mbo
        ),
    }
    for name, matched in metrics.items():
        tests[f"{name}.true" if matched else f"{name}.false"] += 1


def _state_phase_class(
    vendor: VendorRecord,
    mbo: list[MboRecord],
    pre_indices: list[int],
    post_indices: list[int],
) -> str:
    post_same = [
        index for index in post_indices if mbo[index].key5 == vendor.key5
    ]
    if len(post_same) == 1:
        return "POST_SAME_K5_UNIQUE"
    pre_same = [
        index for index in pre_indices if mbo[index].key5 == vendor.key5
    ]
    if len(pre_same) == 1:
        return "PRE_SAME_K5_UNIQUE"
    post_f_last = [
        index for index in post_indices if mbo[index].is_f_last
    ]
    if len(post_f_last) == 1:
        return "POST_F_LAST_UNIQUE"
    if len(mbo) - 1 in post_indices:
        return "POST_GROUP_LAST"
    if len(post_indices) == 1:
        return "POST_ANY_RECORD_UNIQUE"
    if len(pre_indices) == 1:
        return "PRE_ANY_RECORD_UNIQUE"
    if len(pre_indices) + len(post_indices) > 1:
        return "MULTIPLE_EXACT_CANDIDATES"
    return "NO_EXACT_CANDIDATE"


def _update_state_tests(
    tests: Counter[str],
    vendor: VendorRecord,
    mbo: list[MboRecord],
    pre_indices: list[int],
    post_indices: list[int],
    exclusive: str,
    strict_failure: bool,
) -> None:
    tests["population_shared_vendor_rows"] += 1
    tests[f"exclusive.{exclusive}"] += 1
    candidates = [
        *(("PRE", index) for index in pre_indices),
        *(("POST", index) for index in post_indices),
    ]
    if pre_indices:
        tests["raw.pre_any"] += 1
    if post_indices:
        tests["raw.post_any"] += 1
    if any(mbo[index].key5 == vendor.key5 for index in pre_indices):
        tests["raw.pre_same_k5"] += 1
    if any(mbo[index].key5 == vendor.key5 for index in post_indices):
        tests["raw.post_same_k5"] += 1
    if any(mbo[index].is_f_last for index in post_indices):
        tests["raw.post_f_last"] += 1
    if len(mbo) - 1 in post_indices:
        tests["raw.post_group_last"] += 1
    if candidates:
        tests["shared_rows_with_any_exact_candidate"] += 1
    else:
        tests["shared_rows_with_no_exact_candidate"] += 1
    if len(candidates) > 1:
        tests["shared_rows_with_multiple_exact_candidates"] += 1
    tests["candidate_count_distribution." + str(len(candidates))] += 1

    if not strict_failure:
        return
    if candidates:
        tests["strict_failures_with_any_exact_candidate"] += 1
    if len(candidates) == 1:
        tests["strict_failures_with_unique_candidate"] += 1
    unique_non_f_last = [
        candidate
        for candidate in candidates
        if not mbo[candidate[1]].is_f_last
    ]
    if len(unique_non_f_last) == 1:
        tests["strict_failures_unique_non_flast_candidate"] += 1
    elsewhere = [
        candidate
        for candidate in candidates
        if mbo[candidate[1]].key5 != vendor.key5
    ]
    if len(elsewhere) == 1:
        tests["strict_failures_unique_elsewhere_in_k3"] += 1
    if vendor.is_snapshot:
        tests["strict_failures_snapshot"] += 1
        if any(mbo[index].is_snapshot for _, index in candidates):
            tests[
                "snapshot_strict_failures_with_snapshot_candidate"
            ] += 1
    if (
        len(mbo) == 1
        and mbo[0].key5 == vendor.key5
        and not candidates
    ):
        tests["single_mbo_exact_header_no_pre_or_post_match"] += 1


def _update_occurrence_tests(
    tests: Counter[str],
    group_counts: Counter[str],
    group_distributions: dict[str, Counter[str]],
    vendor: VendorRecord,
    mbo: list[MboRecord],
    same_k5_indices: list[int],
    occurrence: int,
    metadata_occurrence: int,
    strict_failure: bool,
    decision_hash: Any,
) -> None:
    """Operationalize frozen within-K5 and metadata occurrence alignment."""

    occurrence_index = occurrence - 1
    occurrence_available = occurrence_index < len(same_k5_indices)
    if occurrence_available:
        mbo_index = same_k5_indices[occurrence_index]
        post_exact = mbo[mbo_index].post == vendor.levels
        pre_exact = mbo[mbo_index].pre == vendor.levels
    else:
        post_exact = False
        pre_exact = False
    tests[
        "post_same_k5_occurrence_exact."
        + ("true" if post_exact else "false")
    ] += 1
    tests[
        "pre_same_k5_occurrence_exact."
        + ("true" if pre_exact else "false")
    ] += 1
    tests[
        "same_k5_occurrence_available."
        + ("true" if occurrence_available else "false")
    ] += 1
    if strict_failure and post_exact:
        tests[
            "strict_failure_post_same_k5_occurrence_exact"
        ] += 1
        if not mbo[mbo_index].is_f_last:
            tests[
                "strict_failure_post_same_k5_occurrence_exact_non_f_last"
            ] += 1

    metadata_indices = [
        index
        for index in same_k5_indices
        if (
            mbo[index].action == vendor.action
            and mbo[index].side == vendor.side
            and mbo[index].flags == vendor.flags
        )
    ]
    metadata_index = metadata_occurrence - 1
    metadata_available = metadata_index < len(metadata_indices)
    if metadata_available:
        matched_index = metadata_indices[metadata_index]
        metadata_post_exact = mbo[matched_index].post == vendor.levels
        metadata_pre_exact = mbo[matched_index].pre == vendor.levels
    else:
        metadata_post_exact = False
        metadata_pre_exact = False
    tests[
        "post_same_k5_action_side_flags_occurrence_exact."
        + ("true" if metadata_post_exact else "false")
    ] += 1
    tests[
        "pre_same_k5_action_side_flags_occurrence_exact."
        + ("true" if metadata_pre_exact else "false")
    ] += 1
    tests[
        "same_k5_action_side_flags_occurrence_available."
        + ("true" if metadata_available else "false")
    ] += 1
    if strict_failure and metadata_post_exact:
        tests[
            "strict_failure_post_same_k5_action_side_flags_occurrence_exact"
        ] += 1
        if not mbo[matched_index].is_f_last:
            tests[
                "strict_failure_post_same_k5_action_side_flags_occurrence_exact_non_f_last"
            ] += 1

    exact_metadata_candidates = [
        index
        for index in metadata_indices
        if mbo[index].post == vendor.levels
    ]
    group_distributions[
        "vendor_exact_post_candidates_same_k5_action_side_flags"
    ][str(len(exact_metadata_candidates))] += 1
    if len(exact_metadata_candidates) == 1:
        group_counts[
            "vendor_rows_unique_exact_post_same_k5_action_side_flags"
        ] += 1
        if strict_failure:
            tests[
                "strict_failure_unique_exact_post_same_k5_action_side_flags"
            ] += 1
    decision_hash.update(b"OCC")
    decision_hash.update(
        bytes(
            (
                int(occurrence_available),
                int(post_exact),
                int(pre_exact),
                int(metadata_available),
                int(metadata_post_exact),
                int(metadata_pre_exact),
            )
        )
    )
    decision_hash.update(INT64.pack(len(exact_metadata_candidates)))


def _update_affected_strata(
    target: dict[str, Counter[str]],
    vendor: VendorRecord,
    *,
    market_state: str,
    duplicate_k5: bool,
    mbo_cardinality: int,
    vendor_cardinality: int,
) -> None:
    target["snapshot_live"][
        "SNAPSHOT" if vendor.is_snapshot else "LIVE"
    ] += 1
    target["action"][vendor.action] += 1
    target["side"][vendor.side] += 1
    target["depth"][str(vendor.depth)] += 1
    target["flags"][str(vendor.flags)] += 1
    target["market_state"][market_state] += 1
    target["duplicate_k5_membership"][
        "DUPLICATE" if duplicate_k5 else "UNIQUE"
    ] += 1
    target["k3_cardinality_pair"][
        f"mbo={mbo_cardinality}|mbp10={vendor_cardinality}"
    ] += 1


def _update_field_mismatches(
    names: list[str],
    fields: Counter[str],
    families: Counter[str],
    sides: Counter[str],
    depths: Counter[str],
) -> None:
    for name in names:
        fields[name] += 1
        side, family, depth = name.split("_")
        families[family] += 1
        sides[side] += 1
        depths[depth] += 1


def _hash_decision(
    digest: Any,
    vendor: VendorRecord,
    occurrence: int,
    strict_status: str,
    exclusive: str,
    pre_count: int,
    post_count: int,
    mismatch_names: list[str],
) -> None:
    digest.update(KEY5.pack(*vendor.key5))
    digest.update(INT64.pack(vendor.ordinal))
    digest.update(INT64.pack(occurrence))
    digest.update(strict_status.encode("ascii"))
    digest.update(b"\x00")
    digest.update(exclusive.encode("ascii"))
    digest.update(INT64.pack(pre_count))
    digest.update(INT64.pack(post_count))
    for name in mismatch_names:
        digest.update(name.encode("ascii"))
        digest.update(b"\x00")


def _mbo_groups(
    path: Path,
    *,
    implementation: str,
    audit: dict[str, Any],
) -> Iterator[tuple[tuple[int, int, int], list[MboRecord]]]:
    if implementation == "primary":
        book: LevelBookReplay | OrderMapReplay = LevelBookReplay()
        primary_index: SortedPriceIndex | None = SortedPriceIndex()
        reference_index: ReferenceLevelIndex | None = None
    elif implementation == "reference":
        book = OrderMapReplay()
        primary_index = None
        reference_index = ReferenceLevelIndex()
    else:
        raise ValueError(implementation)

    input_hash = hashlib.sha256()
    records = 0
    source_ordinal_regressions = 0
    group_key_regressions = 0
    book_invariant_violations = 0
    index_validation_violations = 0
    prior_ordinal: int | None = None
    current_key: tuple[int, int, int] | None = None
    current_group: list[MboRecord] = []
    initial = (
        _primary_top_ten(book, primary_index)
        if primary_index is not None
        else _reference_top_ten(reference_index)
    )
    prior_post = initial

    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=100_000,
        columns=list(MBO_COLUMNS),
    ):
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in MBO_COLUMNS
        }
        numeric = {
            name: arrays[name].to_numpy(zero_copy_only=False)
            for name in MBO_COLUMNS
            if name not in {"ts_recv", "ts_event", "action", "side"}
        }
        receives = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        events = arrays["ts_event"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        actions = arrays["action"].to_pylist()
        sides = arrays["side"].to_pylist()
        for index in range(batch.num_rows):
            records += 1
            ordinal = int(numeric["source_row_ordinal"][index])
            recv = int(receives[index])
            event = int(events[index])
            publisher = int(numeric["publisher_id"][index])
            instrument = int(numeric["instrument_id"][index])
            sequence = int(numeric["sequence"][index])
            action = str(actions[index])
            side = str(sides[index])
            price = int(numeric["price_fixed_1e9"][index])
            size = int(numeric["size"][index])
            order_id = int(numeric["order_id"][index])
            flags = int(numeric["flags"][index])
            key3 = (publisher, instrument, sequence)
            key5 = (*key3, event, recv)
            if prior_ordinal is not None and ordinal <= prior_ordinal:
                source_ordinal_regressions += 1
            prior_ordinal = ordinal
            if current_key is not None and key3 != current_key:
                if key3 < current_key:
                    group_key_regressions += 1
                yield current_key, current_group
                current_group = []
            current_key = key3

            input_hash.update(INT64.pack(ordinal))
            input_hash.update(KEY5.pack(*key5))
            input_hash.update(action.encode("ascii"))
            input_hash.update(side.encode("ascii"))
            for value in (price, size, order_id, flags):
                input_hash.update(INT64.pack(value))

            prior_order = book.orders.get(order_id)
            prior = (
                (prior_order.side, prior_order.price, prior_order.size)
                if prior_order is not None
                else None
            )
            prior_location = (
                (prior_order.side, prior_order.price)
                if prior_order is not None
                else None
            )
            pre = prior_post
            book.apply(
                ordinal=records,
                action=action,
                side=side,
                order_id=order_id,
                price=price,
                size=size,
                flags=flags,
            )
            if primary_index is not None:
                primary_index.after_apply(
                    book,
                    action=action,
                    side=side,
                    price=price,
                    flags=flags,
                    prior_location=prior_location,
                )
                post = _primary_top_ten(book, primary_index)
            else:
                assert reference_index is not None
                current_order = book.orders.get(order_id)
                current = (
                    (
                        current_order.side,
                        current_order.price,
                        current_order.size,
                    )
                    if current_order is not None
                    else None
                )
                if action == "R" or (
                    action == "A"
                    and flags & F_TOB
                    and side in {"A", "B"}
                ):
                    reference_index.rebuild(book)
                else:
                    reference_index.apply_delta(
                        prior=prior,
                        current=current,
                    )
                post = _reference_top_ten(reference_index)
            prior_post = post
            current_group.append(
                MboRecord(
                    ordinal=ordinal,
                    key3=key3,
                    key5=key5,
                    action=action,
                    side=side,
                    flags=flags,
                    pre=pre,
                    post=post,
                )
            )
            if records % CHECKPOINT_INTERVAL == 0:
                book_invariant_violations += sum(book.validate().values())
                if primary_index is not None:
                    index_validation_violations += primary_index.validate(book)
                else:
                    assert reference_index is not None
                    index_validation_violations += reference_index.validate(
                        book
                    )
    if current_key is not None:
        yield current_key, current_group
    book_invariant_violations += sum(book.validate().values())
    if primary_index is not None:
        index_validation_violations += primary_index.validate(book)
    else:
        assert reference_index is not None
        index_validation_violations += reference_index.validate(book)
    audit.update(
        {
            "records": records,
            "input_hash": input_hash.hexdigest(),
            "source_ordinal_regressions": source_ordinal_regressions,
            "group_key_regressions": group_key_regressions,
            "book_invariant_violations": book_invariant_violations,
            "index_validation_violations": index_validation_violations,
            "final_state_hash": state_hash(book.orders),
            "final_structure_hash": book.structure_hash(),
        }
    )


def _vendor_groups(
    path: Path,
    *,
    audit: dict[str, Any],
) -> Iterator[tuple[tuple[int, int, int], list[VendorRecord]]]:
    input_hash = hashlib.sha256()
    records = 0
    source_ordinal_regressions = 0
    group_key_regressions = 0
    prior_ordinal: int | None = None
    current_key: tuple[int, int, int] | None = None
    current_group: list[VendorRecord] = []
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=50_000,
        columns=list(MBP_COLUMNS),
    ):
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in MBP_COLUMNS
        }
        numeric = {
            name: arrays[name].to_numpy(zero_copy_only=False)
            for name in MBP_COLUMNS
            if name not in {"ts_recv", "ts_event", "action", "side"}
        }
        receives = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        events = arrays["ts_event"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        actions = arrays["action"].to_pylist()
        sides = arrays["side"].to_pylist()
        for index in range(batch.num_rows):
            records += 1
            ordinal = int(numeric["source_row_ordinal"][index])
            recv = int(receives[index])
            event = int(events[index])
            publisher = int(numeric["publisher_id"][index])
            instrument = int(numeric["instrument_id"][index])
            sequence = int(numeric["sequence"][index])
            action = str(actions[index])
            side = str(sides[index])
            depth = int(numeric["depth"][index])
            flags = int(numeric["flags"][index])
            key3 = (publisher, instrument, sequence)
            key5 = (*key3, event, recv)
            levels = tuple(
                int(numeric[name][index]) for name in FIELD_NAMES
            )
            if prior_ordinal is not None and ordinal <= prior_ordinal:
                source_ordinal_regressions += 1
            prior_ordinal = ordinal
            if current_key is not None and key3 != current_key:
                if key3 < current_key:
                    group_key_regressions += 1
                yield current_key, current_group
                current_group = []
            current_key = key3
            input_hash.update(INT64.pack(ordinal))
            input_hash.update(KEY5.pack(*key5))
            input_hash.update(action.encode("ascii"))
            input_hash.update(side.encode("ascii"))
            input_hash.update(INT64.pack(depth))
            input_hash.update(INT64.pack(flags))
            for value in levels:
                input_hash.update(INT64.pack(value))
            current_group.append(
                VendorRecord(
                    ordinal=ordinal,
                    key3=key3,
                    key5=key5,
                    action=action,
                    side=side,
                    depth=depth,
                    flags=flags,
                    levels=levels,
                )
            )
    if current_key is not None:
        yield current_key, current_group
    audit.update(
        {
            "records": records,
            "input_hash": input_hash.hexdigest(),
            "source_ordinal_regressions": source_ordinal_regressions,
            "group_key_regressions": group_key_regressions,
        }
    )


def _seal_results(output: Path, context: dict[str, Any]) -> None:
    findings_path = output / "findings.json"
    manifest_path = output / "manifest.json"
    if (
        findings_path.exists()
        or manifest_path.exists()
        or REPORT_PATH.exists()
    ):
        raise FileExistsError("Refusing to overwrite Step 3C seal")
    primary = _verified_result(output / "primary_diagnostic.json", "primary")
    reference = _verified_result(
        output / "reference_diagnostic.json",
        "reference",
    )
    diagnostic_sections = (
        "counts",
        "key_multiplicity",
        "group_correspondence",
        "header_timestamp_tests",
        "state_phase_tests",
        "strict_step3b2_reproduction",
        "integrity_checks",
    )
    section_matches = {
        name: primary[name] == reference[name] for name in diagnostic_sections
    }
    hash_matches = {
        name: primary["hashes"][name] == reference["hashes"][name]
        for name in (
            "row_decision_checksum",
            "native_group_checksum",
            "mbo_input_hash",
            "mbp10_input_hash",
            "final_reconstruction_state_hash",
            "final_reconstruction_structure_hash",
        )
    }
    reproduction_pass = (
        all(section_matches.values())
        and all(hash_matches.values())
        and all(primary["integrity_checks"].values())
        and all(reference["integrity_checks"].values())
    )
    findings = _classify_findings(
        primary,
        reproduction_pass=reproduction_pass,
        section_matches=section_matches,
        hash_matches=hash_matches,
    )
    findings["findings_hash"] = _canonical_hash(findings)
    _write_json_atomic(findings_path, findings)
    _write_report(REPORT_PATH, findings, primary)

    artifacts = [
        _artifact(ATTEMPT_01_PATH),
        _artifact(ATTEMPT_01_DISPOSITION_PATH),
        _artifact(output / "primary_diagnostic.json"),
        _artifact(output / "reference_diagnostic.json"),
        _artifact(findings_path),
        _artifact(REPORT_PATH),
    ]
    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3C_MANIFEST_V0_1",
        "status": (
            "PASS_DIAGNOSTIC_REPRODUCTION"
            if reproduction_pass
            else "FAIL_DIAGNOSTIC_REPRODUCTION"
        ),
        "sealed_at_utc": _utc_now(),
        "classification": "ENGINEERING_ONLY",
        "protocol": _artifact(PROTOCOL_PATH),
        "freeze_receipt": _artifact(FREEZE_PATH),
        "diagnostic_tool": _artifact(Path(__file__).resolve()),
        "step3b2_manifest": _artifact(STEP3B2_MANIFEST_PATH),
        "mbo_source": _artifact(context["mbo_parquet"]),
        "mbp10_source": _artifact(context["mbp_parquet"]),
        "artifacts": artifacts,
        "findings_hash": findings["findings_hash"],
        "predecessor_verdicts": {
            "step_3a": "FAIL",
            "step_3a1": "PASS",
            "step_3b1": "FAIL_PRE_ACQUISITION_READINESS",
            "step_3b2": "FAIL",
        },
        "predecessor_verdicts_preserved": True,
        "additional_data_acquired": False,
        "comparator_modified_or_repaired": False,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(manifest_path, manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_3C_SEALED",
                "status": manifest["status"],
                "reproduction_pass": reproduction_pass,
                "finding_classifications": {
                    item["id"]: item["classification"]
                    for item in findings["findings"]
                },
                "recommendation_id": findings["recommendation"]["id"],
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _classify_findings(
    result: dict[str, Any],
    *,
    reproduction_pass: bool,
    section_matches: dict[str, bool],
    hash_matches: dict[str, bool],
) -> dict[str, Any]:
    strict = result["strict_step3b2_reproduction"]["counts"]
    state = result["state_phase_tests"]
    multiplicity = result["key_multiplicity"]["distributions"]
    failures = strict["strict_failures"]
    duplicate_groups = multiplicity["vendor_k5_summary"].get(
        "duplicate_groups", 0
    )
    duplicate_rows = strict["duplicate_mbp10_keys"]
    occurrence_collisions = multiplicity[
        "vendor_augmented_identifier"
    ].get("collisions", 0)
    event_count = max(
        state["strict_failures_unique_non_flast_candidate"],
        state[
            "strict_failure_post_same_k5_occurrence_exact_non_f_last"
        ],
        state[
            "strict_failure_post_same_k5_action_side_flags_occurrence_exact_non_f_last"
        ],
    )
    grouping_count = max(
        state["strict_failures_unique_elsewhere_in_k3"],
        state["strict_failure_post_same_k5_occurrence_exact"],
        state[
            "strict_failure_post_same_k5_action_side_flags_occurrence_exact"
        ],
    )
    snapshot_failures = state["strict_failures_snapshot"]
    snapshot_resolved = state[
        "snapshot_strict_failures_with_snapshot_candidate"
    ]
    representation_count = state[
        "single_mbo_exact_header_no_pre_or_post_match"
    ]
    any_resolved = state["strict_failures_with_any_exact_candidate"]

    findings: list[dict[str, Any]] = []
    alignment_confirmed = (
        duplicate_groups > 0
        and duplicate_rows > 0
        and occurrence_collisions == 0
        and reproduction_pass
    )
    findings.append(
        {
            "id": "ALIGNMENT_KEY_INSUFFICIENCY",
            "classification": (
                "CONFIRMED" if alignment_confirmed else "UNRESOLVED"
            ),
            "finding": (
                "The frozen K5 does not uniquely identify every vendor row; "
                "source-order occurrence restores identifier uniqueness."
                if alignment_confirmed
                else "K5 insufficiency was not independently established."
            ),
            "scope": "vendor identifier multiplicity, not universal book-state causality",
            "support": {
                "duplicate_vendor_k5_groups": duplicate_groups,
                "vendor_rows_beyond_first_under_k5": duplicate_rows,
                "augmented_identifier_collisions": occurrence_collisions,
                "vendor_records": result["counts"]["mbp10_records"],
            },
        }
    )
    findings.append(
        {
            "id": "EVENT_EMISSION_BOUNDARY",
            "classification": (
                "CONFIRMED"
                if reproduction_pass and event_count > 0
                else "UNRESOLVED"
            ),
            "finding": (
                "The stated strict-failure subpopulation equals exactly one "
                "non-F_LAST pre/post state in its native event group."
                if event_count > 0
                else "No strict failure had one unique non-F_LAST candidate."
            ),
            "scope": "exact counted subpopulation only",
            "support": {
                "strict_failures": failures,
                "unique_non_f_last_resolutions": event_count,
                "unqualified_unique_non_f_last_resolutions": state[
                    "strict_failures_unique_non_flast_candidate"
                ],
                "within_k5_occurrence_non_f_last_resolutions": state[
                    "strict_failure_post_same_k5_occurrence_exact_non_f_last"
                ],
                "coverage_fraction": _ratio(event_count, failures),
            },
        }
    )
    findings.append(
        {
            "id": "NATIVE_EVENT_GROUPING",
            "classification": (
                "CONFIRMED"
                if reproduction_pass and grouping_count > 0
                else "UNRESOLVED"
            ),
            "finding": (
                "The stated strict-failure subpopulation resolves uniquely "
                "elsewhere inside the same K3 native-event group."
                if grouping_count > 0
                else "No strict failure resolved uniquely elsewhere in K3."
            ),
            "scope": "exact counted subpopulation only",
            "support": {
                "strict_failures": failures,
                "unique_elsewhere_in_k3": grouping_count,
                "unqualified_unique_elsewhere_in_k3": state[
                    "strict_failures_unique_elsewhere_in_k3"
                ],
                "within_k5_occurrence_exact": state[
                    "strict_failure_post_same_k5_occurrence_exact"
                ],
                "coverage_fraction": _ratio(grouping_count, failures),
                "any_exact_state_in_k3": any_resolved,
                "any_exact_state_coverage_fraction": _ratio(
                    any_resolved, failures
                ),
            },
        }
    )
    snapshot_ratio = _ratio(snapshot_resolved, snapshot_failures)
    if (
        reproduction_pass
        and snapshot_failures == failures
        and snapshot_failures > 0
        and snapshot_resolved == snapshot_failures
    ):
        snapshot_confidence = "CONFIRMED"
    elif (
        reproduction_pass
        and snapshot_failures > 0
        and snapshot_ratio >= 0.95
    ):
        snapshot_confidence = "LIKELY"
    else:
        snapshot_confidence = "UNRESOLVED"
    findings.append(
        {
            "id": "SNAPSHOT_HANDLING",
            "classification": snapshot_confidence,
            "finding": (
                "Snapshot phase handling explains the frozen threshold share "
                "of its stated affected population."
                if snapshot_confidence != "UNRESOLVED"
                else "Snapshot handling does not meet the frozen causal threshold."
            ),
            "scope": "strict failures classified from vendor F_SNAPSHOT",
            "support": {
                "strict_failures": failures,
                "snapshot_strict_failures": snapshot_failures,
                "snapshot_failures_with_snapshot_candidate": snapshot_resolved,
                "within_snapshot_resolution_fraction": snapshot_ratio,
            },
        }
    )
    findings.append(
        {
            "id": "RECONSTRUCTION_OR_VENDOR_REPRESENTATION_SEMANTICS",
            "classification": (
                "CONFIRMED"
                if reproduction_pass and representation_count > 0
                else "UNRESOLVED"
            ),
            "finding": (
                "A directly isolated one-MBO-row, exact-header subpopulation "
                "matches neither its reconstructed pre nor post state; the "
                "test cannot distinguish vendor representation from replay semantics."
                if representation_count > 0
                else "The frozen isolating test did not establish a representation discrepancy."
            ),
            "scope": "representation discrepancy only; vendor versus reconstruction attribution remains unresolved",
            "support": {
                "single_mbo_exact_header_no_pre_or_post_match": (
                    representation_count
                ),
                "strict_failures": failures,
            },
        }
    )

    recommendation = _select_recommendation(state, failures)
    return {
        "version": "GC_MICROSTRUCTURE_STEP_3C_FINDINGS_V0_1",
        "status": (
            "PASS_DIAGNOSTIC_REPRODUCTION"
            if reproduction_pass
            else "FAIL_DIAGNOSTIC_REPRODUCTION"
        ),
        "classification": "ENGINEERING_ONLY",
        "diagnostic_reproduction": {
            "pass": reproduction_pass,
            "section_matches": section_matches,
            "hash_matches": hash_matches,
        },
        "findings": findings,
        "recommendation": recommendation,
        "prior_step3b2_verdict": "FAIL",
        "prior_step3b2_verdict_preserved": True,
        "additional_data_acquired": False,
        "comparator_modified_or_repaired": False,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }


def _select_recommendation(
    state: dict[str, int],
    failures: int,
) -> dict[str, Any]:
    alignment_counts = {
        "POST_SAME_K5_OCCURRENCE": state.get(
            "strict_failure_post_same_k5_occurrence_exact", 0
        ),
        "POST_SAME_K5_ACTION_SIDE_FLAGS_OCCURRENCE": state.get(
            "strict_failure_post_same_k5_action_side_flags_occurrence_exact",
            0,
        ),
        "POST_SAME_K5_ACTION_SIDE_FLAGS_UNIQUE": state.get(
            "strict_failure_unique_exact_post_same_k5_action_side_flags",
            0,
        ),
        **{
            name: state.get(f"strict_failure_exclusive.{name}", 0)
            for name in EXCLUSIVE_CLASSES
            if name
            not in {"MULTIPLE_EXACT_CANDIDATES", "NO_EXACT_CANDIDATE"}
        },
    }
    frozen_ranking = {
        name: index
        for index, name in enumerate(
            (
                "POST_SAME_K5_OCCURRENCE",
                "POST_SAME_K5_ACTION_SIDE_FLAGS_OCCURRENCE",
                "POST_SAME_K5_ACTION_SIDE_FLAGS_UNIQUE",
                *(
                    name
                    for name in EXCLUSIVE_CLASSES
                    if name
                    not in {
                        "MULTIPLE_EXACT_CANDIDATES",
                        "NO_EXACT_CANDIDATE",
                    }
                ),
            )
        )
    }
    ranked = sorted(
        alignment_counts.items(),
        key=lambda item: (-item[1], frozen_ranking[item[0]]),
    )
    dominant_name, dominant_count = ranked[0] if ranked else ("NONE", 0)
    runner_count = ranked[1][1] if len(ranked) > 1 else 0
    dominant_ratio = _ratio(dominant_count, failures)
    runner_ratio = _ratio(runner_count, failures)
    if failures > 0 and dominant_ratio == 1.0:
        return {
            "id": "EXACT_PHASE_FALLBACK",
            "bounded_engineering_corrections_recommended": 1,
            "text": (
                "Prototype one deterministic fallback for strict F_LAST "
                f"failures using {dominant_name}, on the permanently excluded "
                "engineering date only."
            ),
            "dominant_phase": dominant_name,
            "support_count": dominant_count,
            "strict_failure_population": failures,
            "support_fraction": dominant_ratio,
            "residual_failures": failures - dominant_count,
            "co-leading_alignments": [
                name
                for name, count in ranked
                if count == dominant_count
            ],
            "implementation_during_step_3c": False,
        }
    if (
        failures > 0
        and dominant_ratio >= 0.95
        and dominant_ratio - runner_ratio > 0.01
    ):
        return {
            "id": "ENGINEERING_ONLY_PHASE_PROTOTYPE",
            "bounded_engineering_corrections_recommended": 1,
            "text": (
                "Prototype one deterministic strict-F_LAST fallback using "
                f"{dominant_name} on the excluded engineering date, while "
                "retaining every residual as a failure."
            ),
            "dominant_phase": dominant_name,
            "support_count": dominant_count,
            "strict_failure_population": failures,
            "support_fraction": dominant_ratio,
            "residual_failures": failures - dominant_count,
            "co-leading_alignments": [
                name
                for name, count in ranked
                if count == dominant_count
            ],
            "implementation_during_step_3c": False,
        }
    return {
        "id": "NO_COMPARATOR_CORRECTION",
        "bounded_engineering_corrections_recommended": 0,
        "text": (
            "Retain the Step 3B.2 FAIL and obtain provider-format clarification "
            "before another pre-value engineering amendment."
        ),
        "dominant_phase": dominant_name,
        "support_count": dominant_count,
        "strict_failure_population": failures,
        "support_fraction": dominant_ratio,
        "runner_up_fraction": runner_ratio,
        "co-leading_alignments": [
            name for name, count in ranked if count == dominant_count
        ],
        "implementation_during_step_3c": False,
    }


def _write_report(
    path: Path,
    findings: dict[str, Any],
    result: dict[str, Any],
) -> None:
    strict = result["strict_step3b2_reproduction"]["counts"]
    state = result["state_phase_tests"]
    group = result["group_correspondence"]["counts"]
    lines = [
        "# GC Microstructure Step 3C — Engineering Diagnostic",
        "",
        "## Scope and preserved state",
        "",
        "- Permanently engineering-only date: `2024-01-09`.",
        "- Sources: the previously sealed MBO and MBP-10 files only.",
        "- No data was acquired; no market values are reported.",
        "- Step 3A `FAIL`, Step 3A.1 `PASS`, Step 3B.1 readiness `FAIL`, and Step 3B.2 `FAIL` remain unchanged.",
        "- The Step 3B.2 comparator was neither modified nor repaired.",
        "- One unsealed primary implementation attempt was rejected and preserved before independent reproduction; its disposition is sealed with this report.",
        "",
        "## Reproduction verdict",
        "",
        f"- Step 3C status: `{findings['status']}`.",
        f"- MBO records accounted: {result['counts']['mbo_records']:,}.",
        f"- MBP-10 records accounted: {result['counts']['mbp10_records']:,}.",
        f"- Shared K3 native-event groups: {group['shared_k3_groups']:,}.",
        f"- Strict Step 3B.2 failures reproduced: {strict['strict_failures']:,}.",
        f"- Strict failures with at least one exact state in K3: {state['strict_failures_with_any_exact_candidate']:,}.",
        "",
        "## Frozen-taxonomy findings",
        "",
    ]
    for item in findings["findings"]:
        lines.extend(
            [
                f"### {item['id']}",
                "",
                f"Classification: `{item['classification']}`.",
                "",
                item["finding"],
                "",
                f"Scope: {item['scope']}.",
                "",
                "Supporting counts: `" + json.dumps(
                    item["support"],
                    sort_keys=True,
                    separators=(",", ":"),
                ) + "`.",
                "",
            ]
        )
    recommendation = findings["recommendation"]
    lines.extend(
        [
            "## Single bounded recommendation",
            "",
            f"`{recommendation['id']}` — {recommendation['text']}",
            "",
            "No correction was implemented during Step 3C.",
            "",
            "## Prohibited work confirmation",
            "",
            "No outcomes, directional relationships, signals, execution optimization, trades, PnL, R multiples, or account returns were calculated.",
            "",
        ]
    )
    _write_text_atomic(path, "\n".join(lines))


def _verified_context() -> dict[str, Any]:
    if _sha256(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 3C protocol changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 3C freeze receipt changed")
    protocol = _load_json(PROTOCOL_PATH)
    freeze = _load_json(FREEZE_PATH)
    if (
        protocol["status"] != "FROZEN_BEFORE_ROW_LEVEL_DIAGNOSIS"
        or freeze["status"]
        != "DIAGNOSTIC_PROTOCOL_SEALED_BEFORE_ROW_LEVEL_ACCESS"
        or freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256
    ):
        raise ValueError("Step 3C pre-value freeze is invalid")
    step3b2 = _load_json(STEP3B2_MANIFEST_PATH)
    step3b2_without_hash = {
        key: value
        for key, value in step3b2.items()
        if key != "manifest_hash"
    }
    if (
        step3b2["manifest_hash"] != EXPECTED_STEP3B2_MANIFEST_HASH
        or step3b2["manifest_hash"] != _canonical_hash(step3b2_without_hash)
        or step3b2["status"] != "FAIL"
    ):
        raise ValueError("Step 3B.2 FAIL seal changed")
    context = verified_step3b2_context()
    if (
        context["mbo_parquet_sha256"] != EXPECTED_MBO_SHA256
        or context["mbp_parquet_sha256"] != EXPECTED_MBP_SHA256
    ):
        raise ValueError("Sealed engineering source changed")
    return context


def _verified_result(path: Path, implementation: str) -> dict[str, Any]:
    result = _load_json(path)
    declared = result["result_hash"]
    without = {key: value for key, value in result.items() if key != "result_hash"}
    if declared != _canonical_hash(without):
        raise ValueError(f"Result hash mismatch: {path}")
    if (
        result["implementation"] != implementation
        or result["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256
        or result["freeze_sha256"] != EXPECTED_FREEZE_SHA256
        or result["mbo_source_sha256"] != EXPECTED_MBO_SHA256
        or result["mbp10_source_sha256"] != EXPECTED_MBP_SHA256
    ):
        raise ValueError(f"Result identity mismatch: {path}")
    return result


def _verify_seal(output: Path) -> None:
    manifest_path = output / "manifest.json"
    manifest = _load_json(manifest_path)
    declared = manifest["manifest_hash"]
    without = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if declared != _canonical_hash(without):
        raise ValueError("Step 3C manifest hash mismatch")
    for item in (
        manifest["protocol"],
        manifest["freeze_receipt"],
        manifest["diagnostic_tool"],
        manifest["step3b2_manifest"],
        manifest["mbo_source"],
        manifest["mbp10_source"],
        *manifest["artifacts"],
    ):
        path = Path(str(item["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"Sealed artifact changed: {path}")
    findings = _load_json(output / "findings.json")
    findings_without = {
        key: value
        for key, value in findings.items()
        if key != "findings_hash"
    }
    if (
        findings["findings_hash"] != _canonical_hash(findings_without)
        or findings["findings_hash"] != manifest["findings_hash"]
    ):
        raise ValueError("Step 3C findings hash mismatch")
    if manifest["predecessor_verdicts"] != {
        "step_3a": "FAIL",
        "step_3a1": "PASS",
        "step_3b1": "FAIL_PRE_ACQUISITION_READINESS",
        "step_3b2": "FAIL",
    }:
        raise ValueError("Predecessor verdicts not preserved")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_3C_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]) + 6,
                "predecessor_verdicts_preserved": True,
                "additional_data_acquired": False,
                "comparator_modified_or_repaired": False,
                "market_values_reported": False,
                "outcomes_accessed": False,
                "signals_calculated": False,
                "execution_optimized": False,
                "pnl_calculated": False,
            },
            sort_keys=True,
        )
    )


def _set_zero_defaults(counter: Counter[str], names: tuple[str, ...]) -> None:
    for name in names:
        counter.setdefault(name, 0)


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: int(value) for key, value in sorted(counter.items())}


def _nested_counter_dict(
    value: dict[str, Counter[str]],
) -> dict[str, dict[str, int]]:
    return {
        name: _counter_dict(counter)
        for name, counter in sorted(value.items())
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _artifact(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    _write_text_atomic(path, payload)


def _write_text_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


if __name__ == "__main__":
    main()
