#!/usr/bin/env python3
"""Diagnose Step 3D residual alignment using sealed metadata only.

No price, size, order ID, or bid/ask book column is loaded. Candidate
selectors are the five definitions frozen in the Step 3E protocol.
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
from typing import Any, Callable, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from compare_gc_mbo_mbp10_step3b2 import _canonical_hash, _sha256

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3e_protocol_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3e_freeze_v01.json"
)
STEP3D_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_3d_v01"
    / "manifest.json"
)
MBO_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "databento_gc_mbo_engineering_pilot"
    / "GLBX-20260730-WB9AXCVFET"
    / "normalized"
    / "gc_v_0_2024_01_09_mbo.parquet"
)
MBP_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "databento_gc_mbp10_engineering_benchmark"
    / "GLBX-20260731-UJHWEDQUSX"
    / "normalized"
    / "gc_v_0_2024_01_09_mbp10.parquet"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_3e_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_3E_REPORT.md"

EXPECTED_PROTOCOL_SHA256 = (
    "8785226f10013f65fa7f583f7f47d5b6809688f65c48644c60bf4c9d9fee96be"
)
EXPECTED_FREEZE_SHA256 = (
    "2c1adfa4529e1550f7f18694ce931dae032291624f6c529a4c6af88910ddad5d"
)
EXPECTED_STEP3D_MANIFEST_HASH = (
    "2a8e9aecc3c21887968b6741e7093c28b069441c52a25e355802d2ab0434585b"
)
EXPECTED_STEP3D_VERDICT_HASH = (
    "1c45844ebe71c71624fb5d6e9b6d521d65b59b0d397c002c607e218e74e27360"
)
EXPECTED_MBO_SHA256 = (
    "43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3"
)
EXPECTED_MBP_SHA256 = (
    "4ead358f538d7c383a14f39bbde35b8ccfa21e38e58205edbc51bedfb2ed80d4"
)
EXPECTED_MBO_RECORDS = 2_322_905
EXPECTED_MBP_RECORDS = 1_924_786
EXPECTED_RESIDUALS = 2_552

F_LAST = 128
F_PUBLISHER_SPECIFIC = 2
INT64 = struct.Struct(">q")
KEY5_STRUCT = struct.Struct(">5q")

MBO_COLUMNS = (
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "publisher_id",
    "instrument_id",
    "sequence",
    "action",
    "side",
    "flags",
)
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
)
FORBIDDEN_COLUMN_TOKENS = (
    "price",
    "size",
    "order_id",
    "bid_px",
    "ask_px",
    "bid_sz",
    "ask_sz",
    "bid_ct",
    "ask_ct",
)
CANDIDATES = (
    "C01_MASK_PUBLISHER_SPECIFIC_FLAG",
    "C02_IGNORE_FLAGS",
    "C03_SIDE_IF_SPECIFIED_IGNORE_FLAGS",
    "C04_ACTION_ONLY",
    "C05_K5_OCCURRENCE_DIAGNOSTIC_ONLY",
)
ELIGIBLE_CANDIDATES = CANDIDATES[:4]


@dataclass(frozen=True, slots=True)
class MboMeta:
    ordinal: int
    key3: tuple[int, int, int]
    key5: tuple[int, int, int, int, int]
    action: str
    side: str
    flags: int

    @property
    def is_f_last(self) -> bool:
        return bool(self.flags & F_LAST)


@dataclass(frozen=True, slots=True)
class VendorMeta:
    ordinal: int
    key3: tuple[int, int, int]
    key5: tuple[int, int, int, int, int]
    action: str
    side: str
    depth: int
    flags: int


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
    _verified_context()
    output.mkdir(parents=True, exist_ok=True)
    if action in {"primary", "reference"}:
        destination = output / f"{action}_diagnostic.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite: {destination}")
        result = diagnose(implementation=action)
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
                    "stage": f"GC_MICROSTRUCTURE_STEP_3E_{action.upper()}_COMPLETE",
                    "implementation": action,
                    "mbo_records": result["counts"]["mbo_records"],
                    "mbp10_records": result["counts"]["mbp10_records"],
                    "step3d_residuals": result["counts"][
                        "step3d_residuals"
                    ],
                    "candidate_available": {
                        candidate: result["candidate_results"][candidate][
                            "available"
                        ]
                        for candidate in CANDIDATES
                    },
                    "metadata_decision_checksum": result["hashes"][
                        "metadata_decision_checksum"
                    ],
                    "book_columns_loaded": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return
    if action == "seal":
        _seal(output)
        return
    if action == "verify":
        _verify_seal(output)
        return
    raise AssertionError(action)


def diagnose(*, implementation: str) -> dict[str, Any]:
    mbo_audit: dict[str, Any] = {}
    vendor_audit: dict[str, Any] = {}
    mbo_stream = iter(_mbo_groups(MBO_PATH, audit=mbo_audit))
    vendor_stream = iter(_vendor_groups(MBP_PATH, audit=vendor_audit))
    current_mbo = next(mbo_stream, None)
    current_vendor = next(vendor_stream, None)

    counts: Counter[str] = Counter()
    component_tests: Counter[str] = Counter()
    topology: Counter[str] = Counter()
    distributions: dict[str, Counter[str]] = defaultdict(Counter)
    crosswalks: dict[str, Counter[str]] = defaultdict(Counter)
    candidate_counts: dict[str, Counter[str]] = {
        candidate: Counter() for candidate in CANDIDATES
    }
    candidate_selected_ordinals: dict[str, set[int]] = {
        candidate: set() for candidate in CANDIDATES
    }
    metadata_hash = hashlib.sha256()
    residual_hash = hashlib.sha256()

    while current_mbo is not None or current_vendor is not None:
        mbo_key = current_mbo[0] if current_mbo is not None else None
        vendor_key = current_vendor[0] if current_vendor is not None else None
        if vendor_key is None or (
            mbo_key is not None and mbo_key < vendor_key
        ):
            _, mbo_group = current_mbo
            counts["mbo_records"] += len(mbo_group)
            counts["mbo_only_k3_groups"] += 1
            current_mbo = next(mbo_stream, None)
        elif mbo_key is None or vendor_key < mbo_key:
            _, vendor_group = current_vendor
            counts["mbp10_records"] += len(vendor_group)
            counts["mbp10_only_k3_groups"] += 1
            # These rows necessarily fail the Step 3D selector and the
            # same-K5 requirement. They remain visible to integrity gates.
            counts["step3d_residuals"] += len(vendor_group)
            counts["residuals_without_same_k5_group"] += len(vendor_group)
            current_vendor = next(vendor_stream, None)
        else:
            assert current_mbo is not None and current_vendor is not None
            _, mbo_group = current_mbo
            _, vendor_group = current_vendor
            counts["mbo_records"] += len(mbo_group)
            counts["mbp10_records"] += len(vendor_group)
            counts["shared_k3_groups"] += 1
            _diagnose_group(
                mbo_group,
                vendor_group,
                implementation=implementation,
                counts=counts,
                component_tests=component_tests,
                topology=topology,
                distributions=distributions,
                crosswalks=crosswalks,
                candidate_counts=candidate_counts,
                candidate_selected_ordinals=candidate_selected_ordinals,
                metadata_hash=metadata_hash,
                residual_hash=residual_hash,
            )
            current_mbo = next(mbo_stream, None)
            current_vendor = next(vendor_stream, None)

    for name in (
        "mbo_records",
        "mbp10_records",
        "step3d_aligned_rows",
        "step3d_residuals",
        "residuals_with_same_k5_group",
        "residuals_without_same_k5_group",
    ):
        counts.setdefault(name, 0)
    candidate_results: dict[str, dict[str, Any]] = {}
    for candidate in CANDIDATES:
        current = candidate_counts[candidate]
        for name in (
            "available",
            "unavailable",
            "selected_reuse_with_residual",
            "selected_reuse_with_step3d_aligned",
            "occurrence_shortfall",
        ):
            current.setdefault(name, 0)
        candidate_results[candidate] = {
            **_counter_dict(current),
            "coverage_fraction": (
                current["available"] / counts["step3d_residuals"]
                if counts["step3d_residuals"]
                else 0.0
            ),
            "recommendation_eligible_by_registry": candidate
            in ELIGIBLE_CANDIDATES,
        }

    integrity = {
        "mbo_record_count_exact": counts["mbo_records"]
        == EXPECTED_MBO_RECORDS,
        "mbp10_record_count_exact": counts["mbp10_records"]
        == EXPECTED_MBP_RECORDS,
        "step3d_residual_count_exact": counts["step3d_residuals"]
        == EXPECTED_RESIDUALS,
        "every_residual_has_same_k5_group": counts[
            "residuals_without_same_k5_group"
        ]
        == 0
        and counts["residuals_with_same_k5_group"] == EXPECTED_RESIDUALS,
        "all_vendor_rows_classified_once": counts["mbp10_records"]
        == counts["step3d_aligned_rows"] + counts["step3d_residuals"],
        "mbo_source_ordinals_monotonic": mbo_audit[
            "source_ordinal_regressions"
        ]
        == 0,
        "mbp_source_ordinals_monotonic": vendor_audit[
            "source_ordinal_regressions"
        ]
        == 0,
        "only_permitted_mbo_columns_loaded": mbo_audit[
            "only_permitted_columns_loaded"
        ],
        "only_permitted_mbp10_columns_loaded": vendor_audit[
            "only_permitted_columns_loaded"
        ],
        "no_book_columns_loaded": (
            not mbo_audit["book_columns_loaded"]
            and not vendor_audit["book_columns_loaded"]
        ),
        "all_frozen_candidates_reported": set(candidate_results)
        == set(CANDIDATES),
    }
    result: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3E_METADATA_DIAGNOSTIC_V0_1",
        "implementation": implementation,
        "classification": "ENGINEERING_ONLY",
        "counts": _counter_dict(counts),
        "component_tests": _counter_dict(component_tests),
        "event_topology": _counter_dict(topology),
        "distributions": _nested_counter_dict(distributions),
        "metadata_crosswalks": _nested_counter_dict(crosswalks),
        "candidate_results": candidate_results,
        "integrity_checks": integrity,
        "mbo_audit": mbo_audit,
        "vendor_audit": vendor_audit,
        "hashes": {
            "metadata_decision_checksum": metadata_hash.hexdigest(),
            "residual_identity_checksum": residual_hash.hexdigest(),
            "mbo_metadata_input_hash": mbo_audit["metadata_input_hash"],
            "mbp10_metadata_input_hash": vendor_audit[
                "metadata_input_hash"
            ],
        },
        "candidate_occurrence_population": "ALL_VENDOR_ROWS_WITHIN_TRANSFORMED_KEY",
        "candidate_coverage_population": "STEP_3D_RESIDUAL_ROWS_ONLY",
        "step3d_selected_mbo_reuse_checked": True,
        "book_columns_loaded": False,
        "book_state_reconstructed": False,
        "book_values_compared": False,
        "correction_implemented": False,
        "additional_data_acquired": False,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    result["diagnostic_payload_hash"] = _canonical_hash(result)
    return result


def _diagnose_group(
    mbo: list[MboMeta],
    vendor: list[VendorMeta],
    *,
    implementation: str,
    counts: Counter[str],
    component_tests: Counter[str],
    topology: Counter[str],
    distributions: dict[str, Counter[str]],
    crosswalks: dict[str, Counter[str]],
    candidate_counts: dict[str, Counter[str]],
    candidate_selected_ordinals: dict[str, set[int]],
    metadata_hash: Any,
    residual_hash: Any,
) -> None:
    exact_mbo: dict[
        tuple[tuple[int, int, int, int, int], str, str, int],
        list[MboMeta],
    ] = defaultdict(list)
    mbo_by_k5: dict[
        tuple[int, int, int, int, int], list[MboMeta]
    ] = defaultdict(list)
    for row in mbo:
        exact_mbo[(row.key5, row.action, row.side, row.flags)].append(row)
        mbo_by_k5[row.key5].append(row)

    exact_vendor_occurrence: Counter[
        tuple[tuple[int, int, int, int, int], str, str, int]
    ] = Counter()
    base_selected_ordinals: set[int] = set()
    residuals: list[VendorMeta] = []
    residual_base_occurrence: dict[int, int] = {}
    for row in vendor:
        key = (row.key5, row.action, row.side, row.flags)
        exact_vendor_occurrence[key] += 1
        occurrence = exact_vendor_occurrence[key]
        available = exact_mbo.get(key, [])
        if occurrence <= len(available):
            counts["step3d_aligned_rows"] += 1
            base_selected_ordinals.add(available[occurrence - 1].ordinal)
        else:
            counts["step3d_residuals"] += 1
            residuals.append(row)
            residual_base_occurrence[row.ordinal] = occurrence
            if row.key5 in mbo_by_k5:
                counts["residuals_with_same_k5_group"] += 1
            else:
                counts["residuals_without_same_k5_group"] += 1

    vendor_occurrences: dict[str, dict[int, int]] = {
        candidate: {} for candidate in CANDIDATES
    }
    for candidate in CANDIDATES:
        counter: Counter[tuple[Any, ...]] = Counter()
        for row in vendor:
            key = _vendor_candidate_key(candidate, row)
            counter[key] += 1
            vendor_occurrences[candidate][row.ordinal] = counter[key]

    if implementation == "primary":
        indexes = _build_candidate_indexes(mbo)
        selector: Callable[
            [str, VendorMeta, int], tuple[MboMeta | None, int]
        ] = lambda candidate, row, occurrence: _select_primary(
            indexes, candidate, row, occurrence
        )
    elif implementation == "reference":
        selector = lambda candidate, row, occurrence: _select_reference(
            mbo_by_k5.get(row.key5, []), candidate, row, occurrence
        )
    else:
        raise ValueError(implementation)

    for row in residuals:
        same_k5 = mbo_by_k5.get(row.key5, [])
        residual_hash.update(KEY5_STRUCT.pack(*row.key5))
        residual_hash.update(INT64.pack(row.ordinal))
        residual_hash.update(row.action.encode("ascii"))
        residual_hash.update(row.side.encode("ascii"))
        residual_hash.update(INT64.pack(row.flags))
        residual_hash.update(INT64.pack(row.depth))
        _update_component_and_topology_tests(
            row,
            same_k5,
            component_tests,
            topology,
            distributions,
            crosswalks,
            residual_base_occurrence[row.ordinal],
        )
        for candidate in CANDIDATES:
            occurrence = vendor_occurrences[candidate][row.ordinal]
            selected, candidate_count = selector(
                candidate, row, occurrence
            )
            current = candidate_counts[candidate]
            current["population"] += 1
            current[f"candidate_count.{candidate_count}"] += 1
            current[f"vendor_occurrence.{occurrence}"] += 1
            if selected is None:
                current["unavailable"] += 1
                current["occurrence_shortfall"] += 1
                selected_ordinal = -1
            else:
                current["available"] += 1
                selected_ordinal = selected.ordinal
                if selected_ordinal in candidate_selected_ordinals[candidate]:
                    current["selected_reuse_with_residual"] += 1
                candidate_selected_ordinals[candidate].add(selected_ordinal)
                if selected_ordinal in base_selected_ordinals:
                    current["selected_reuse_with_step3d_aligned"] += 1
                current[f"selected_action.{selected.action}"] += 1
                current[f"selected_side.{selected.side}"] += 1
                current[f"selected_flags.{selected.flags}"] += 1
                current[
                    "selected_f_last." + str(selected.is_f_last).lower()
                ] += 1
            _hash_candidate_decision(
                metadata_hash,
                candidate,
                row,
                occurrence,
                candidate_count,
                selected_ordinal,
            )


def _update_component_and_topology_tests(
    vendor: VendorMeta,
    mbo: list[MboMeta],
    tests: Counter[str],
    topology: Counter[str],
    distributions: dict[str, Counter[str]],
    crosswalks: dict[str, Counter[str]],
    base_occurrence: int,
) -> None:
    tests["population"] += 1
    distributions["vendor_action"][vendor.action] += 1
    distributions["vendor_side"][vendor.side] += 1
    distributions["vendor_flags"][str(vendor.flags)] += 1
    distributions["vendor_depth"][str(vendor.depth)] += 1
    distributions["step3d_exact_occurrence"][str(base_occurrence)] += 1
    distributions["same_k5_mbo_cardinality"][str(len(mbo))] += 1
    actions = {row.action for row in mbo}
    sides = {row.side for row in mbo}
    flags = {row.flags for row in mbo}
    masked_flags = {row.flags & ~F_PUBLISHER_SPECIFIC for row in mbo}
    distributions["same_k5_distinct_actions"][str(len(actions))] += 1
    distributions["same_k5_distinct_sides"][str(len(sides))] += 1
    distributions["same_k5_distinct_flags"][str(len(flags))] += 1
    f_last = [row for row in mbo if row.is_f_last]
    distributions["same_k5_f_last_cardinality"][str(len(f_last))] += 1

    checks = {
        "action_any": vendor.action in actions,
        "side_any": vendor.side in sides,
        "flags_any": vendor.flags in flags,
        "masked_flags_any": (
            vendor.flags & ~F_PUBLISHER_SPECIFIC
        )
        in masked_flags,
        "action_side_any": any(
            row.action == vendor.action and row.side == vendor.side
            for row in mbo
        ),
        "action_flags_any": any(
            row.action == vendor.action and row.flags == vendor.flags
            for row in mbo
        ),
        "action_masked_flags_any": any(
            row.action == vendor.action
            and (row.flags & ~F_PUBLISHER_SPECIFIC)
            == (vendor.flags & ~F_PUBLISHER_SPECIFIC)
            for row in mbo
        ),
        "side_flags_any": any(
            row.side == vendor.side and row.flags == vendor.flags
            for row in mbo
        ),
        "exact_tuple_any": any(
            row.action == vendor.action
            and row.side == vendor.side
            and row.flags == vendor.flags
            for row in mbo
        ),
        "masked_tuple_any": any(
            row.action == vendor.action
            and row.side == vendor.side
            and (row.flags & ~F_PUBLISHER_SPECIFIC)
            == (vendor.flags & ~F_PUBLISHER_SPECIFIC)
            for row in mbo
        ),
    }
    for name, value in checks.items():
        tests[f"{name}.{'true' if value else 'false'}"] += 1

    topology[
        "group_contains_publisher_specific_flag."
        + str(any(row.flags & F_PUBLISHER_SPECIFIC for row in mbo)).lower()
    ] += 1
    topology[
        "group_contains_none_action."
        + str(any(row.action == "N" for row in mbo)).lower()
    ] += 1
    topology[
        "group_contains_none_side."
        + str(any(row.side == "N" for row in mbo)).lower()
    ] += 1
    if mbo:
        _update_position_match(topology, "first", vendor, [mbo[0]])
        _update_position_match(topology, "last", vendor, [mbo[-1]])
    _update_position_match(topology, "f_last", vendor, f_last)

    for row in mbo:
        crosswalks["action"][
            f"vendor={vendor.action}|mbo={row.action}"
        ] += 1
        crosswalks["side"][
            f"vendor={vendor.side}|mbo={row.side}"
        ] += 1
        crosswalks["flags"][
            f"vendor={vendor.flags}|mbo={row.flags}"
        ] += 1
        crosswalks["action_side_flags"][
            f"vendor={vendor.action}/{vendor.side}/{vendor.flags}|mbo={row.action}/{row.side}/{row.flags}"
        ] += 1
        crosswalks["flags_xor_all_same_k5"][
            str(vendor.flags ^ row.flags)
        ] += 1
        if row.action == vendor.action:
            crosswalks["flags_xor_same_action"][
                str(vendor.flags ^ row.flags)
            ] += 1
            crosswalks["side_same_action"][
                f"vendor={vendor.side}|mbo={row.side}"
            ] += 1


def _update_position_match(
    target: Counter[str],
    label: str,
    vendor: VendorMeta,
    records: list[MboMeta],
) -> None:
    metrics = {
        "action": any(row.action == vendor.action for row in records),
        "side": any(row.side == vendor.side for row in records),
        "flags": any(row.flags == vendor.flags for row in records),
        "tuple": any(
            row.action == vendor.action
            and row.side == vendor.side
            and row.flags == vendor.flags
            for row in records
        ),
    }
    for metric, value in metrics.items():
        target[
            f"vendor_matches_{label}_{metric}."
            + ("true" if value else "false")
        ] += 1


def _build_candidate_indexes(
    mbo: list[MboMeta],
) -> dict[str, dict[tuple[Any, ...], list[MboMeta]]]:
    indexes: dict[str, dict[tuple[Any, ...], list[MboMeta]]] = {
        candidate: defaultdict(list) for candidate in CANDIDATES
    }
    for row in mbo:
        for candidate in CANDIDATES:
            for key in _mbo_candidate_keys(candidate, row):
                indexes[candidate][key].append(row)
    return indexes


def _select_primary(
    indexes: dict[str, dict[tuple[Any, ...], list[MboMeta]]],
    candidate: str,
    vendor: VendorMeta,
    occurrence: int,
) -> tuple[MboMeta | None, int]:
    available = indexes[candidate].get(
        _vendor_candidate_key(candidate, vendor), []
    )
    selected = available[occurrence - 1] if occurrence <= len(available) else None
    return selected, len(available)


def _select_reference(
    same_k5: list[MboMeta],
    candidate: str,
    vendor: VendorMeta,
    occurrence: int,
) -> tuple[MboMeta | None, int]:
    available = [
        row
        for row in same_k5
        if _candidate_predicate(candidate, vendor, row)
    ]
    selected = available[occurrence - 1] if occurrence <= len(available) else None
    return selected, len(available)


def _vendor_candidate_key(
    candidate: str,
    row: VendorMeta,
) -> tuple[Any, ...]:
    if candidate == "C01_MASK_PUBLISHER_SPECIFIC_FLAG":
        return (row.key5, row.action, row.side, row.flags & ~2)
    if candidate == "C02_IGNORE_FLAGS":
        return (row.key5, row.action, row.side)
    if candidate == "C03_SIDE_IF_SPECIFIED_IGNORE_FLAGS":
        return (
            row.key5,
            row.action,
            "*" if row.side == "N" else row.side,
        )
    if candidate == "C04_ACTION_ONLY":
        return (row.key5, row.action)
    if candidate == "C05_K5_OCCURRENCE_DIAGNOSTIC_ONLY":
        return (row.key5,)
    raise ValueError(candidate)


def _mbo_candidate_keys(
    candidate: str,
    row: MboMeta,
) -> tuple[tuple[Any, ...], ...]:
    if candidate == "C01_MASK_PUBLISHER_SPECIFIC_FLAG":
        return ((row.key5, row.action, row.side, row.flags & ~2),)
    if candidate == "C02_IGNORE_FLAGS":
        return ((row.key5, row.action, row.side),)
    if candidate == "C03_SIDE_IF_SPECIFIED_IGNORE_FLAGS":
        return (
            (row.key5, row.action, row.side),
            (row.key5, row.action, "*"),
        )
    if candidate == "C04_ACTION_ONLY":
        return ((row.key5, row.action),)
    if candidate == "C05_K5_OCCURRENCE_DIAGNOSTIC_ONLY":
        return ((row.key5,),)
    raise ValueError(candidate)


def _candidate_predicate(
    candidate: str,
    vendor: VendorMeta,
    mbo: MboMeta,
) -> bool:
    if mbo.key5 != vendor.key5:
        return False
    if candidate == "C01_MASK_PUBLISHER_SPECIFIC_FLAG":
        return (
            mbo.action == vendor.action
            and mbo.side == vendor.side
            and (mbo.flags & ~2) == (vendor.flags & ~2)
        )
    if candidate == "C02_IGNORE_FLAGS":
        return mbo.action == vendor.action and mbo.side == vendor.side
    if candidate == "C03_SIDE_IF_SPECIFIED_IGNORE_FLAGS":
        return mbo.action == vendor.action and (
            vendor.side == "N" or mbo.side == vendor.side
        )
    if candidate == "C04_ACTION_ONLY":
        return mbo.action == vendor.action
    if candidate == "C05_K5_OCCURRENCE_DIAGNOSTIC_ONLY":
        return True
    raise ValueError(candidate)


def _hash_candidate_decision(
    digest: Any,
    candidate: str,
    vendor: VendorMeta,
    occurrence: int,
    candidate_count: int,
    selected_ordinal: int,
) -> None:
    digest.update(candidate.encode("ascii"))
    digest.update(b"\x00")
    digest.update(KEY5_STRUCT.pack(*vendor.key5))
    digest.update(INT64.pack(vendor.ordinal))
    digest.update(INT64.pack(occurrence))
    digest.update(INT64.pack(candidate_count))
    digest.update(INT64.pack(selected_ordinal))


def _mbo_groups(
    path: Path,
    *,
    audit: dict[str, Any],
) -> Iterator[tuple[tuple[int, int, int], list[MboMeta]]]:
    _assert_permitted_columns(MBO_COLUMNS)
    digest = hashlib.sha256()
    records = 0
    ordinal_regressions = 0
    group_key_regressions = 0
    prior_ordinal: int | None = None
    current_key: tuple[int, int, int] | None = None
    current_group: list[MboMeta] = []
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
            publisher = int(numeric["publisher_id"][index])
            instrument = int(numeric["instrument_id"][index])
            sequence = int(numeric["sequence"][index])
            event = int(events[index])
            recv = int(receives[index])
            action = str(actions[index])
            side = str(sides[index])
            flags = int(numeric["flags"][index])
            key3 = (publisher, instrument, sequence)
            key5 = (*key3, event, recv)
            if prior_ordinal is not None and ordinal <= prior_ordinal:
                ordinal_regressions += 1
            prior_ordinal = ordinal
            if current_key is not None and key3 != current_key:
                if key3 < current_key:
                    group_key_regressions += 1
                yield current_key, current_group
                current_group = []
            current_key = key3
            row = MboMeta(
                ordinal=ordinal,
                key3=key3,
                key5=key5,
                action=action,
                side=side,
                flags=flags,
            )
            current_group.append(row)
            _hash_meta(digest, row, depth=None)
    if current_key is not None:
        yield current_key, current_group
    audit.update(
        {
            "records": records,
            "metadata_input_hash": digest.hexdigest(),
            "source_ordinal_regressions": ordinal_regressions,
            "group_key_regressions": group_key_regressions,
            "loaded_columns": list(MBO_COLUMNS),
            "only_permitted_columns_loaded": True,
            "book_columns_loaded": False,
        }
    )


def _vendor_groups(
    path: Path,
    *,
    audit: dict[str, Any],
) -> Iterator[tuple[tuple[int, int, int], list[VendorMeta]]]:
    _assert_permitted_columns(MBP_COLUMNS)
    digest = hashlib.sha256()
    records = 0
    ordinal_regressions = 0
    group_key_regressions = 0
    prior_ordinal: int | None = None
    current_key: tuple[int, int, int] | None = None
    current_group: list[VendorMeta] = []
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=100_000,
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
            publisher = int(numeric["publisher_id"][index])
            instrument = int(numeric["instrument_id"][index])
            sequence = int(numeric["sequence"][index])
            event = int(events[index])
            recv = int(receives[index])
            action = str(actions[index])
            side = str(sides[index])
            depth = int(numeric["depth"][index])
            flags = int(numeric["flags"][index])
            key3 = (publisher, instrument, sequence)
            key5 = (*key3, event, recv)
            if prior_ordinal is not None and ordinal <= prior_ordinal:
                ordinal_regressions += 1
            prior_ordinal = ordinal
            if current_key is not None and key3 != current_key:
                if key3 < current_key:
                    group_key_regressions += 1
                yield current_key, current_group
                current_group = []
            current_key = key3
            row = VendorMeta(
                ordinal=ordinal,
                key3=key3,
                key5=key5,
                action=action,
                side=side,
                depth=depth,
                flags=flags,
            )
            current_group.append(row)
            _hash_meta(digest, row, depth=depth)
    if current_key is not None:
        yield current_key, current_group
    audit.update(
        {
            "records": records,
            "metadata_input_hash": digest.hexdigest(),
            "source_ordinal_regressions": ordinal_regressions,
            "group_key_regressions": group_key_regressions,
            "loaded_columns": list(MBP_COLUMNS),
            "only_permitted_columns_loaded": True,
            "book_columns_loaded": False,
        }
    )


def _hash_meta(
    digest: Any,
    row: MboMeta | VendorMeta,
    *,
    depth: int | None,
) -> None:
    digest.update(INT64.pack(row.ordinal))
    digest.update(KEY5_STRUCT.pack(*row.key5))
    digest.update(row.action.encode("ascii"))
    digest.update(row.side.encode("ascii"))
    digest.update(INT64.pack(row.flags))
    if depth is not None:
        digest.update(INT64.pack(depth))


def _assert_permitted_columns(columns: tuple[str, ...]) -> None:
    lowered = [column.lower() for column in columns]
    offending = [
        column
        for column in lowered
        if any(token in column for token in FORBIDDEN_COLUMN_TOKENS)
    ]
    if offending:
        raise ValueError(f"Forbidden metadata diagnostic columns: {offending}")


def _seal(output: Path) -> None:
    findings_path = output / "findings.json"
    manifest_path = output / "manifest.json"
    if findings_path.exists() or manifest_path.exists() or REPORT_PATH.exists():
        raise FileExistsError("Refusing to overwrite Step 3E seal")
    primary = _verified_result(output / "primary_diagnostic.json", "primary")
    reference = _verified_result(
        output / "reference_diagnostic.json", "reference"
    )
    sections = (
        "counts",
        "component_tests",
        "event_topology",
        "distributions",
        "metadata_crosswalks",
        "candidate_results",
        "integrity_checks",
    )
    matching_sections = {
        name: primary[name] == reference[name] for name in sections
    }
    matching_hashes = {
        name: primary["hashes"][name] == reference["hashes"][name]
        for name in (
            "metadata_decision_checksum",
            "residual_identity_checksum",
            "mbo_metadata_input_hash",
            "mbp10_metadata_input_hash",
        )
    }
    reproduction_pass = (
        all(matching_sections.values())
        and all(matching_hashes.values())
        and all(primary["integrity_checks"].values())
        and all(reference["integrity_checks"].values())
    )
    findings = _classify(
        primary,
        reproduction_pass=reproduction_pass,
        matching_sections=matching_sections,
        matching_hashes=matching_hashes,
    )
    findings["findings_hash"] = _canonical_hash(findings)
    _write_json_atomic(findings_path, findings)
    _write_report(REPORT_PATH, findings, primary)
    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3E_MANIFEST_V0_1",
        "status": findings["status"],
        "sealed_at_utc": _utc_now(),
        "classification": "ENGINEERING_ONLY",
        "protocol": _artifact(PROTOCOL_PATH),
        "freeze_receipt": _artifact(FREEZE_PATH),
        "diagnostic_tool": _artifact(Path(__file__).resolve()),
        "step3d_manifest": _artifact(STEP3D_MANIFEST_PATH),
        "mbo_source": _artifact(MBO_PATH),
        "mbp10_source": _artifact(MBP_PATH),
        "artifacts": [
            _artifact(output / "primary_diagnostic.json"),
            _artifact(output / "reference_diagnostic.json"),
            _artifact(findings_path),
            _artifact(REPORT_PATH),
        ],
        "findings_hash": findings["findings_hash"],
        "predecessor_verdicts_preserved": True,
        "book_columns_loaded": False,
        "book_values_compared": False,
        "correction_implemented": False,
        "additional_data_acquired": False,
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
                "stage": "GC_MICROSTRUCTURE_STEP_3E_SEALED",
                "status": findings["status"],
                "reproduction_pass": reproduction_pass,
                "residual_records": primary["counts"][
                    "step3d_residuals"
                ],
                "recommendation_id": findings["recommendation"]["id"],
                "recommended_correction_count": findings[
                    "recommendation"
                ]["corrections_recommended"],
                "manifest_hash": manifest["manifest_hash"],
                "book_columns_loaded": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _classify(
    result: dict[str, Any],
    *,
    reproduction_pass: bool,
    matching_sections: dict[str, bool],
    matching_hashes: dict[str, bool],
) -> dict[str, Any]:
    total = result["counts"]["step3d_residuals"]
    tests = result["component_tests"]
    topology = result["event_topology"]
    distributions = result["distributions"]

    def count(name: str) -> int:
        return int(tests.get(name, 0))

    action_present = count("action_any.true")
    side_unspecified = int(
        distributions.get("vendor_side", {}).get("N", 0)
    )
    publisher_specific = sum(
        value
        for key, value in distributions.get("vendor_flags", {}).items()
        if int(key) & F_PUBLISHER_SPECIFIC
    )
    multi_record = sum(
        value
        for key, value in distributions.get(
            "same_k5_mbo_cardinality", {}
        ).items()
        if int(key) > 1
    )
    findings = [
        {
            "id": "ACTION_PRESERVATION",
            "classification": _coverage_class(
                action_present, total, reproduction_pass
            ),
            "finding": "Residual MBP-10 action is present in its same-K5 MBO group.",
            "support": {
                "residual_records": total,
                "action_present": action_present,
                "coverage_fraction": _ratio(action_present, total),
            },
            "semantic_basis": "Official action enum plus exhaustive metadata count.",
        },
        {
            "id": "UNSPECIFIED_SIDE",
            "classification": _coverage_class(
                side_unspecified, total, reproduction_pass
            ),
            "finding": "Vendor side N contributes to the residual population; official semantics define N as no side specified.",
            "support": {
                "residual_records": total,
                "vendor_side_n": side_unspecified,
                "coverage_fraction": _ratio(side_unspecified, total),
            },
            "semantic_basis": "Official Side definition; causal attribution remains empirical.",
        },
        {
            "id": "PUBLISHER_SPECIFIC_NORMALIZATION",
            "classification": _coverage_class(
                publisher_specific, total, reproduction_pass
            ),
            "finding": "F_PUBLISHER_SPECIFIC is set on the stated share of residual vendor headers.",
            "support": {
                "residual_records": total,
                "publisher_specific_flag_set": publisher_specific,
                "coverage_fraction": _ratio(publisher_specific, total),
            },
            "semantic_basis": "Official flag definition; exact GLBX header derivation is not documented in the reviewed pages.",
        },
        {
            "id": "FLAGS_AS_NONIDENTITY_METADATA",
            "classification": _coverage_class(
                count("action_side_any.true")
                - count("exact_tuple_any.true"),
                total,
                reproduction_pass,
            ),
            "finding": "Action-and-side matches can exist even where exact action/side/flags identity does not.",
            "support": {
                "action_side_present": count("action_side_any.true"),
                "exact_tuple_present": count("exact_tuple_any.true"),
                "difference": count("action_side_any.true")
                - count("exact_tuple_any.true"),
                "residual_records": total,
            },
            "semantic_basis": "Official flags describe characteristics; the causal header-copy rule is not guaranteed.",
        },
        {
            "id": "MULTI_RECORD_EVENT_EMISSION",
            "classification": _coverage_class(
                multi_record, total, reproduction_pass
            ),
            "finding": "The stated share of residuals belongs to same-K5 groups with multiple MBO records.",
            "support": {
                "residual_records": total,
                "multi_record_groups_at_row_level": multi_record,
                "coverage_fraction": _ratio(multi_record, total),
                "vendor_matches_any_f_last_tuple": topology.get(
                    "vendor_matches_f_last_tuple.true", 0
                ),
            },
            "semantic_basis": "Official documentation confirms publisher events can normalize to multiple MBO records.",
        },
    ]
    recommendation = _select_recommendation(
        result["candidate_results"], total, reproduction_pass
    )
    unresolved_header = recommendation["corrections_recommended"] == 0
    findings.append(
        {
            "id": "UNRESOLVED_HEADER_DERIVATION",
            "classification": "UNRESOLVED" if unresolved_header else "LIKELY",
            "finding": (
                "No eligible frozen selector fully explains the residual metadata."
                if unresolved_header
                else "The recommended selector is a reproduced metadata rule, but the reviewed official pages do not explicitly guarantee this MBP-10 header derivation."
            ),
            "support": {
                "eligible_complete_candidate_found": not unresolved_header,
                "recommended_candidate": recommendation.get(
                    "candidate_id"
                ),
            },
            "semantic_basis": "Explicitly limited by the official-documentation boundary frozen before residual access.",
        }
    )
    status = (
        "PASS_DIAGNOSTIC_REPRODUCTION"
        if reproduction_pass
        else "FAIL_DIAGNOSTIC_REPRODUCTION"
    )
    return {
        "version": "GC_MICROSTRUCTURE_STEP_3E_FINDINGS_V0_1",
        "status": status,
        "classification": "ENGINEERING_ONLY",
        "diagnostic_reproduction": {
            "pass": reproduction_pass,
            "matching_sections": matching_sections,
            "matching_hashes": matching_hashes,
        },
        "findings": findings,
        "candidate_results": result["candidate_results"],
        "recommendation": recommendation,
        "official_documentation_limit": "The reviewed Databento pages do not guarantee a byte-for-byte MBP-10-to-MBO header copy rule.",
        "step3d_verdict": "FAIL_UNALIGNED_RESIDUAL",
        "step3d_verdict_preserved": True,
        "book_columns_loaded": False,
        "book_values_compared": False,
        "correction_implemented": False,
        "additional_data_acquired": False,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }


def _select_recommendation(
    results: dict[str, dict[str, Any]],
    total: int,
    reproduction_pass: bool,
) -> dict[str, Any]:
    for candidate in ELIGIBLE_CANDIDATES:
        current = results[candidate]
        eligible = (
            reproduction_pass
            and current["available"] == total
            and current["unavailable"] == 0
            and current["occurrence_shortfall"] == 0
            and current["selected_reuse_with_residual"] == 0
            and current["selected_reuse_with_step3d_aligned"] == 0
        )
        if eligible:
            return {
                "id": "ONE_VALUE_BLIND_CORRECTION_RECOMMENDED",
                "corrections_recommended": 1,
                "candidate_id": candidate,
                "coverage_records": current["available"],
                "residual_population": total,
                "coverage_fraction": current["coverage_fraction"],
                "selected_reuse": 0,
                "implementation_during_step_3e": False,
                "validation_credit": "NONE",
                "text": "Freeze this candidate as a post-hoc engineering fallback in a separate amendment; do not implement or validate it in Step 3E.",
            }
    return {
        "id": "NO_CORRECTION_RECOMMENDED",
        "corrections_recommended": 0,
        "candidate_id": None,
        "residual_population": total,
        "implementation_during_step_3e": False,
        "validation_credit": "NONE",
        "text": "No eligible frozen metadata selector covers all residuals without reuse; preserve the Step 3D failure.",
    }


def _coverage_class(
    numerator: int,
    denominator: int,
    reproduced: bool,
) -> str:
    if not reproduced or denominator == 0:
        return "UNRESOLVED"
    if numerator == denominator:
        return "CONFIRMED"
    if numerator / denominator >= 0.95:
        return "LIKELY"
    return "UNRESOLVED"


def _write_report(
    path: Path,
    findings: dict[str, Any],
    result: dict[str, Any],
) -> None:
    lines = [
        "# GC Microstructure Step 3E — Residual Metadata Semantics",
        "",
        "## Scope",
        "",
        "- Step 3D `FAIL_UNALIGNED_RESIDUAL` is preserved.",
        "- Only sealed metadata columns were loaded; no price, size, order ID, or bid/ask book field was loaded.",
        "- No book was reconstructed and no candidate book state was compared.",
        f"- Reproduced Step 3D residual records: {result['counts']['step3d_residuals']:,}.",
        "",
        "## Official semantics used",
        "",
        "- [Databento MBO schema](https://databento.com/docs/schemas-and-data-formats/mbo)",
        "- [Databento MBP-10 schema](https://databento.com/docs/schemas-and-data-formats/market-by-price)",
        "- [Databento common fields and enums](https://databento.com/docs/standards-and-conventions/common-fields-enums-types)",
        "- [Databento order-state and F_LAST guidance](https://databento.com/docs/examples/order-book/order-tracking)",
        "- [Databento release notes](https://databento.com/docs/release-notes)",
        "",
        "The reviewed pages define actions, side N, flags, and F_LAST, but do not guarantee that an MBP-10 header is a byte-for-byte copy of one MBO row.",
        "",
        "## Findings",
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
                "Support: `"
                + json.dumps(
                    item["support"],
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "`.",
                "",
            ]
        )
    lines.extend(["## Frozen candidate results", ""])
    for candidate in CANDIDATES:
        current = findings["candidate_results"][candidate]
        lines.append(
            f"- `{candidate}`: {current['available']:,}/{result['counts']['step3d_residuals']:,} available; residual reuse {current['selected_reuse_with_residual']:,}; Step 3D reuse {current['selected_reuse_with_step3d_aligned']:,}."
        )
    recommendation = findings["recommendation"]
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"`{recommendation['id']}`",
            "",
            recommendation["text"],
            "",
            "No correction was implemented. No additional data, outcomes, signals, execution optimization, trades, or PnL were used.",
            "",
        ]
    )
    _write_text_atomic(path, "\n".join(lines))


def _verified_context() -> None:
    if _sha256(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 3E protocol changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 3E freeze receipt changed")
    protocol = _load_json(PROTOCOL_PATH)
    freeze = _load_json(FREEZE_PATH)
    if (
        protocol["status"] != "FROZEN_BEFORE_RESIDUAL_METADATA_ACCESS"
        or freeze["status"]
        != "PROTOCOL_SEALED_BEFORE_RESIDUAL_METADATA_ACCESS"
        or freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256
    ):
        raise ValueError("Step 3E freeze identity invalid")
    manifest = _load_json(STEP3D_MANIFEST_PATH)
    without = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if (
        manifest["manifest_hash"] != EXPECTED_STEP3D_MANIFEST_HASH
        or manifest["manifest_hash"] != _canonical_hash(without)
        or manifest["verdict_hash"] != EXPECTED_STEP3D_VERDICT_HASH
        or manifest["status"] != "FAIL_UNALIGNED_RESIDUAL"
    ):
        raise ValueError("Step 3D seal changed")
    for item in (
        manifest["amendment"],
        manifest["freeze_receipt"],
        manifest["comparison_tool"],
        manifest["step3c_manifest"],
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
            raise ValueError(f"Step 3D artifact changed: {path}")
    if _sha256(MBO_PATH) != EXPECTED_MBO_SHA256:
        raise ValueError("MBO source changed")
    if _sha256(MBP_PATH) != EXPECTED_MBP_SHA256:
        raise ValueError("MBP-10 source changed")


def _verified_result(path: Path, implementation: str) -> dict[str, Any]:
    result = _load_json(path)
    declared = result["result_hash"]
    without = {
        key: value for key, value in result.items() if key != "result_hash"
    }
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
    manifest = _load_json(output / "manifest.json")
    without = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if manifest["manifest_hash"] != _canonical_hash(without):
        raise ValueError("Step 3E manifest hash mismatch")
    for item in (
        manifest["protocol"],
        manifest["freeze_receipt"],
        manifest["diagnostic_tool"],
        manifest["step3d_manifest"],
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
            raise ValueError(f"Step 3E sealed artifact changed: {path}")
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
        raise ValueError("Step 3E findings hash mismatch")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_3E_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]) + 6,
                "step3d_fail_preserved": True,
                "book_columns_loaded": False,
                "book_values_compared": False,
                "correction_implemented": False,
                "additional_data_acquired": False,
                "outcomes_accessed": False,
                "pnl_calculated": False,
            },
            sort_keys=True,
        )
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: int(value) for key, value in sorted(counter.items())}


def _nested_counter_dict(
    value: dict[str, Counter[str]],
) -> dict[str, dict[str, int]]:
    return {
        name: _counter_dict(counter)
        for name, counter in sorted(value.items())
    }


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
    _write_text_atomic(
        path, json.dumps(value, indent=2, sort_keys=True) + "\n"
    )


def _write_text_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(
            descriptor, "w", encoding="utf-8", newline="\n"
        ) as handle:
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
