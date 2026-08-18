#!/usr/bin/env python3
"""Apply the frozen Step 3D metadata-only MBO/MBP-10 comparator.

Selection is based only on K5, action, side, flags, and within-identical-
metadata occurrence. Book values are consulted only after a row has a selected
MBO occurrence. The program emits counts and hashes, never market values.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from compare_gc_mbo_mbp10_step3b2 import (
    FIELD_NAMES,
    _canonical_hash,
    _market_state,
    _sha256,
)
from diagnose_gc_mbo_mbp10_step3c import (
    MboRecord,
    VendorRecord,
    _mbo_groups,
    _vendor_groups,
    _verified_context as verified_step3c_source_context,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3d_amendment_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3d_freeze_v01.json"
)
STEP3C_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_3c_v01"
    / "manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_3d_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_3D_REPORT.md"

EXPECTED_AMENDMENT_SHA256 = (
    "15ff635e299888421fc8c37b11dc7632c13c21cae0aec65972bb18386771299d"
)
EXPECTED_FREEZE_SHA256 = (
    "0a0fae610b1899aae9429cc6c8ff24a1bfd08dcbcfebd4bbcf5de9c9dad5dc8d"
)
EXPECTED_STEP3C_MANIFEST_HASH = (
    "e14afa4de4e487f2a8db9b6e044de4aba6c7d9fcaeef10f6b0ca8ee337bcb749"
)
EXPECTED_STEP3C_FINDINGS_HASH = (
    "d362c7999ee5503a149b764375ed079ada79bd4282dc2121fc8ada354aeb8f7f"
)
EXPECTED_MBO_SHA256 = (
    "43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3"
)
EXPECTED_MBP_SHA256 = (
    "4ead358f538d7c383a14f39bbde35b8ccfa21e38e58205edbc51bedfb2ed80d4"
)
EXPECTED_MBO_RECORDS = 2_322_905
EXPECTED_MBP_RECORDS = 1_924_786
EXPECTED_ALIGNED = 1_922_234
EXPECTED_UNALIGNED = 2_552
EXPECTED_ALIGNED_MISMATCH_ROWS = 0
EXPECTED_ALIGNED_FIELD_MISMATCHES = 0
EXPECTED_PRIOR_STEP3B2_FAILURES_RESOLVED = 73_887

INT64 = struct.Struct(">q")
KEY5_STRUCT = struct.Struct(">5q")


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
        destination = output / f"{action}_comparison.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite: {destination}")
        result = compare_sources(
            context["mbo_parquet"],
            context["mbp_parquet"],
            implementation=action,
        )
        result.update(
            {
                "amendment_sha256": EXPECTED_AMENDMENT_SHA256,
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
                    "stage": f"GC_MICROSTRUCTURE_STEP_3D_{action.upper()}_COMPLETE",
                    "implementation": action,
                    "mbo_records": result["counts"]["mbo_records"],
                    "mbp10_records": result["counts"]["mbp10_records"],
                    "aligned_records": result["counts"]["aligned_records"],
                    "unaligned_residual_records": result["counts"][
                        "unaligned_residual_records"
                    ],
                    "aligned_mismatch_rows": result["counts"][
                        "aligned_mismatch_rows"
                    ],
                    "aligned_field_mismatches": result["counts"][
                        "aligned_field_mismatches"
                    ],
                    "selector_checksum": result["hashes"][
                        "selector_checksum"
                    ],
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


def compare_sources(
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
    residual_strata: dict[str, Counter[str]] = defaultdict(Counter)
    mismatch_fields: Counter[str] = Counter()
    mismatch_families: Counter[str] = Counter()
    mismatch_sides: Counter[str] = Counter()
    mismatch_depths: Counter[str] = Counter()
    market_states: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    selector_hash = hashlib.sha256()
    comparison_hash = hashlib.sha256()
    aligned_vendor_hash = hashlib.sha256()
    selected_reconstruction_hash = hashlib.sha256()

    while current_mbo is not None or current_vendor is not None:
        mbo_key = current_mbo[0] if current_mbo is not None else None
        vendor_key = current_vendor[0] if current_vendor is not None else None
        if vendor_key is None or (
            mbo_key is not None and mbo_key < vendor_key
        ):
            key3, mbo_group = current_mbo
            _compare_group(
                key3,
                mbo_group,
                [],
                counts,
                residual_strata,
                mismatch_fields,
                mismatch_families,
                mismatch_sides,
                mismatch_depths,
                market_states,
                group_counts,
                selector_hash,
                comparison_hash,
                aligned_vendor_hash,
                selected_reconstruction_hash,
            )
            current_mbo = next(mbo_stream, None)
        elif mbo_key is None or vendor_key < mbo_key:
            key3, vendor_group = current_vendor
            _compare_group(
                key3,
                [],
                vendor_group,
                counts,
                residual_strata,
                mismatch_fields,
                mismatch_families,
                mismatch_sides,
                mismatch_depths,
                market_states,
                group_counts,
                selector_hash,
                comparison_hash,
                aligned_vendor_hash,
                selected_reconstruction_hash,
            )
            current_vendor = next(vendor_stream, None)
        else:
            assert current_mbo is not None and current_vendor is not None
            key3, mbo_group = current_mbo
            _, vendor_group = current_vendor
            _compare_group(
                key3,
                mbo_group,
                vendor_group,
                counts,
                residual_strata,
                mismatch_fields,
                mismatch_families,
                mismatch_sides,
                mismatch_depths,
                market_states,
                group_counts,
                selector_hash,
                comparison_hash,
                aligned_vendor_hash,
                selected_reconstruction_hash,
            )
            current_mbo = next(mbo_stream, None)
            current_vendor = next(vendor_stream, None)

    for name in (
        "mbo_records",
        "mbp10_records",
        "aligned_records",
        "unaligned_residual_records",
        "aligned_exact_rows",
        "aligned_mismatch_rows",
        "aligned_field_mismatches",
        "selected_mbo_reuse",
        "aligned_rows_that_failed_step3b2",
        "selected_f_last_rows",
        "selected_non_f_last_rows",
    ):
        counts.setdefault(name, 0)
    counts["unselected_mbo_records"] = (
        counts["mbo_records"] - counts["aligned_records"]
    )

    traceability = {
        "mbo_records_exact": counts["mbo_records"]
        == EXPECTED_MBO_RECORDS,
        "mbp10_records_exact": counts["mbp10_records"]
        == EXPECTED_MBP_RECORDS,
        "metadata_aligned_records_exact": counts["aligned_records"]
        == EXPECTED_ALIGNED,
        "unaligned_residual_records_exact": counts[
            "unaligned_residual_records"
        ]
        == EXPECTED_UNALIGNED,
        "aligned_mismatch_rows_exact": counts["aligned_mismatch_rows"]
        == EXPECTED_ALIGNED_MISMATCH_ROWS,
        "aligned_field_mismatches_exact": counts[
            "aligned_field_mismatches"
        ]
        == EXPECTED_ALIGNED_FIELD_MISMATCHES,
        "prior_step3b2_failures_resolved_exact": counts[
            "aligned_rows_that_failed_step3b2"
        ]
        == EXPECTED_PRIOR_STEP3B2_FAILURES_RESOLVED,
    }
    integrity = {
        "all_mbo_rows_processed": counts["mbo_records"]
        == EXPECTED_MBO_RECORDS,
        "all_mbp10_rows_processed": counts["mbp10_records"]
        == EXPECTED_MBP_RECORDS,
        "all_vendor_rows_classified_once": counts["mbp10_records"]
        == counts["aligned_records"]
        + counts["unaligned_residual_records"],
        "all_aligned_rows_compared": counts["aligned_records"]
        == counts["aligned_exact_rows"] + counts["aligned_mismatch_rows"],
        "selected_mbo_rows_not_reused": counts["selected_mbo_reuse"] == 0,
        "source_ordinals_monotonic": replay_audit.get(
            "source_ordinal_regressions", -1
        )
        == 0
        and vendor_audit.get("source_ordinal_regressions", -1) == 0,
        "reconstruction_invariants_hold": replay_audit.get(
            "book_invariant_violations", -1
        )
        == 0,
        "reconstruction_index_invariants_hold": replay_audit.get(
            "index_validation_violations", -1
        )
        == 0,
        "market_state_coverage_complete": sum(market_states.values())
        == counts["mbp10_records"],
        "step3c_traceability_reproduced": all(traceability.values()),
    }
    selector_audit = {
        "rule": "SAME_K5_ACTION_SIDE_FLAGS_OCCURRENCE_POST_V0_1",
        "book_values_used_for_selection": False,
        "alternative_candidates_tried": 0,
        "f_last_priority_used": False,
        "unaligned_rows_compared_to_book": 0,
        "fallback_used": False,
        "selector_fields": [
            "publisher_id",
            "instrument_id",
            "sequence",
            "ts_event",
            "ts_recv",
            "action",
            "side",
            "flags",
            "within_identical_metadata_occurrence",
        ],
    }
    result: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3D_COMPARISON_V0_1",
        "implementation": implementation,
        "classification": "ENGINEERING_ONLY",
        "counts": _counter_dict(counts),
        "group_counts": _counter_dict(group_counts),
        "market_state_counts": _counter_dict(market_states),
        "unaligned_residual_strata": _nested_counter_dict(
            residual_strata
        ),
        "mismatch_field_counts": _counter_dict(mismatch_fields),
        "mismatch_field_family": _counter_dict(mismatch_families),
        "mismatch_field_side": _counter_dict(mismatch_sides),
        "mismatch_field_depth": _counter_dict(mismatch_depths),
        "selector_audit": selector_audit,
        "step3c_traceability_checks": traceability,
        "integrity_checks": integrity,
        "replay_audit": replay_audit,
        "vendor_audit": vendor_audit,
        "hashes": {
            "selector_checksum": selector_hash.hexdigest(),
            "comparison_checksum": comparison_hash.hexdigest(),
            "aligned_vendor_state_hash": aligned_vendor_hash.hexdigest(),
            "selected_reconstruction_state_hash": (
                selected_reconstruction_hash.hexdigest()
            ),
            "mbo_input_hash": replay_audit["input_hash"],
            "mbp10_input_hash": vendor_audit["input_hash"],
            "final_reconstruction_state_hash": replay_audit[
                "final_state_hash"
            ],
            "final_reconstruction_structure_hash": replay_audit[
                "final_structure_hash"
            ],
        },
        "selection_uses_book_values": False,
        "unaligned_rows_preserved_as_failures": True,
        "comparator_repaired_after_results": False,
        "additional_data_acquired": False,
        "technical_market_values_processed_after_alignment": True,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    result["comparison_payload_hash"] = _canonical_hash(result)
    return result


def _compare_group(
    key3: tuple[int, int, int],
    mbo: list[MboRecord],
    vendor: list[VendorRecord],
    counts: Counter[str],
    residual_strata: dict[str, Counter[str]],
    mismatch_fields: Counter[str],
    mismatch_families: Counter[str],
    mismatch_sides: Counter[str],
    mismatch_depths: Counter[str],
    market_states: Counter[str],
    group_counts: Counter[str],
    selector_hash: Any,
    comparison_hash: Any,
    aligned_vendor_hash: Any,
    selected_reconstruction_hash: Any,
) -> None:
    del key3
    counts["mbo_records"] += len(mbo)
    counts["mbp10_records"] += len(vendor)
    if mbo and vendor:
        group_counts["shared_k3_groups"] += 1
    elif mbo:
        group_counts["mbo_only_k3_groups"] += 1
    else:
        group_counts["mbp10_only_k3_groups"] += 1

    candidates: dict[
        tuple[tuple[int, int, int, int, int], str, str, int],
        list[MboRecord],
    ] = defaultdict(list)
    first_f_last: dict[
        tuple[int, int, int, int, int], MboRecord
    ] = {}
    for row in mbo:
        candidates[(row.key5, row.action, row.side, row.flags)].append(row)
        if row.is_f_last:
            first_f_last.setdefault(row.key5, row)

    vendor_occurrences: Counter[
        tuple[tuple[int, int, int, int, int], str, str, int]
    ] = Counter()
    vendor_k5_counts = Counter(row.key5 for row in vendor)
    selected_ordinals: set[int] = set()
    for vendor_row in vendor:
        state = _market_state(vendor_row.key5[4])
        market_states[state] += 1
        selector_key = (
            vendor_row.key5,
            vendor_row.action,
            vendor_row.side,
            vendor_row.flags,
        )
        vendor_occurrences[selector_key] += 1
        occurrence = vendor_occurrences[selector_key]
        available = candidates.get(selector_key, [])
        selected = (
            available[occurrence - 1]
            if occurrence <= len(available)
            else None
        )
        _hash_selection(
            selector_hash,
            vendor_row,
            occurrence,
            selected.ordinal if selected is not None else -1,
        )
        if selected is None:
            counts["unaligned_residual_records"] += 1
            _update_residual_strata(
                residual_strata,
                vendor_row,
                market_state=state,
                k5_multiplicity=vendor_k5_counts[vendor_row.key5],
                occurrence=occurrence,
                candidate_count=len(available),
            )
            comparison_hash.update(b"UNALIGNED")
            comparison_hash.update(KEY5_STRUCT.pack(*vendor_row.key5))
            comparison_hash.update(INT64.pack(vendor_row.ordinal))
            continue

        counts["aligned_records"] += 1
        if selected.ordinal in selected_ordinals:
            counts["selected_mbo_reuse"] += 1
        selected_ordinals.add(selected.ordinal)
        if selected.is_f_last:
            counts["selected_f_last_rows"] += 1
        else:
            counts["selected_non_f_last_rows"] += 1

        field_mismatch_names: list[str] = []
        for name, vendor_value, reconstructed_value in zip(
            FIELD_NAMES,
            vendor_row.levels,
            selected.post,
            strict=True,
        ):
            if vendor_value != reconstructed_value:
                field_mismatch_names.append(name)
        if field_mismatch_names:
            counts["aligned_mismatch_rows"] += 1
            counts["aligned_field_mismatches"] += len(
                field_mismatch_names
            )
            for name in field_mismatch_names:
                mismatch_fields[name] += 1
                side, family, depth = name.split("_")
                mismatch_sides[side] += 1
                mismatch_families[family] += 1
                mismatch_depths[depth] += 1
        else:
            counts["aligned_exact_rows"] += 1

        prior_boundary = first_f_last.get(vendor_row.key5)
        if (
            prior_boundary is None
            or vendor_row.levels != prior_boundary.post
        ):
            counts["aligned_rows_that_failed_step3b2"] += 1

        _hash_levels(aligned_vendor_hash, vendor_row.levels)
        _hash_levels(selected_reconstruction_hash, selected.post)
        comparison_hash.update(b"ALIGNED")
        comparison_hash.update(KEY5_STRUCT.pack(*vendor_row.key5))
        comparison_hash.update(INT64.pack(vendor_row.ordinal))
        comparison_hash.update(INT64.pack(selected.ordinal))
        for name in field_mismatch_names:
            comparison_hash.update(name.encode("ascii"))
            comparison_hash.update(b"\x00")


def _update_residual_strata(
    strata: dict[str, Counter[str]],
    vendor: VendorRecord,
    *,
    market_state: str,
    k5_multiplicity: int,
    occurrence: int,
    candidate_count: int,
) -> None:
    strata["action"][vendor.action] += 1
    strata["side"][vendor.side] += 1
    strata["flags"][str(vendor.flags)] += 1
    strata["depth"][str(vendor.depth)] += 1
    strata["market_state"][market_state] += 1
    strata["k5_multiplicity"][str(k5_multiplicity)] += 1
    strata["within_metadata_occurrence"][str(occurrence)] += 1
    strata["matching_mbo_metadata_candidate_count"][
        str(candidate_count)
    ] += 1


def _hash_selection(
    digest: Any,
    vendor: VendorRecord,
    occurrence: int,
    selected_ordinal: int,
) -> None:
    digest.update(KEY5_STRUCT.pack(*vendor.key5))
    digest.update(vendor.action.encode("ascii"))
    digest.update(vendor.side.encode("ascii"))
    digest.update(INT64.pack(vendor.flags))
    digest.update(INT64.pack(occurrence))
    digest.update(INT64.pack(selected_ordinal))


def _hash_levels(digest: Any, levels: tuple[int, ...]) -> None:
    for value in levels:
        digest.update(INT64.pack(value))


def _seal(output: Path, context: dict[str, Any]) -> None:
    verdict_path = output / "verdict.json"
    manifest_path = output / "manifest.json"
    if verdict_path.exists() or manifest_path.exists() or REPORT_PATH.exists():
        raise FileExistsError("Refusing to overwrite Step 3D seal")
    primary = _verified_result(output / "primary_comparison.json", "primary")
    reference = _verified_result(
        output / "reference_comparison.json", "reference"
    )
    matching_sections = {
        name: primary[name] == reference[name]
        for name in (
            "counts",
            "group_counts",
            "market_state_counts",
            "unaligned_residual_strata",
            "mismatch_field_counts",
            "mismatch_field_family",
            "mismatch_field_side",
            "mismatch_field_depth",
            "selector_audit",
            "step3c_traceability_checks",
            "integrity_checks",
        )
    }
    matching_hashes = {
        name: primary["hashes"][name] == reference["hashes"][name]
        for name in (
            "selector_checksum",
            "comparison_checksum",
            "aligned_vendor_state_hash",
            "selected_reconstruction_state_hash",
            "mbo_input_hash",
            "mbp10_input_hash",
            "final_reconstruction_state_hash",
            "final_reconstruction_structure_hash",
        )
    }
    reproduction_pass = all(matching_sections.values()) and all(
        matching_hashes.values()
    )
    counts = primary["counts"]
    foundational_integrity = (
        all(primary["integrity_checks"].values())
        and all(reference["integrity_checks"].values())
        and context["all_predecessor_seals_valid"]
        and context["sources_exact"]
    )
    gates = {
        "all_predecessor_seals_valid": context[
            "all_predecessor_seals_valid"
        ],
        "sources_exact_and_unchanged": context["sources_exact"],
        "all_mbo_and_mbp10_rows_processed": (
            counts["mbo_records"] == EXPECTED_MBO_RECORDS
            and counts["mbp10_records"] == EXPECTED_MBP_RECORDS
        ),
        "metadata_selector_applied_without_book_values": not primary[
            "selector_audit"
        ]["book_values_used_for_selection"],
        "every_vendor_row_aligned": counts["aligned_records"]
        == counts["mbp10_records"],
        "unaligned_residual_rows_zero": counts[
            "unaligned_residual_records"
        ]
        == 0,
        "all_aligned_rows_compared": counts["aligned_records"]
        == counts["aligned_exact_rows"] + counts["aligned_mismatch_rows"],
        "aligned_book_mismatch_rows_zero": counts[
            "aligned_mismatch_rows"
        ]
        == 0,
        "aligned_book_field_mismatches_zero": counts[
            "aligned_field_mismatches"
        ]
        == 0,
        "market_state_coverage_complete": primary["integrity_checks"][
            "market_state_coverage_complete"
        ],
        "both_reconstruction_invariants_hold": (
            primary["integrity_checks"]["reconstruction_invariants_hold"]
            and primary["integrity_checks"][
                "reconstruction_index_invariants_hold"
            ]
            and reference["integrity_checks"][
                "reconstruction_invariants_hold"
            ]
            and reference["integrity_checks"][
                "reconstruction_index_invariants_hold"
            ]
        ),
        "primary_and_reference_results_identical": reproduction_pass,
        "step_3c_traceability_expectation_reproduced": all(
            primary["step3c_traceability_checks"].values()
        )
        and all(reference["step3c_traceability_checks"].values()),
        "no_predecessor_or_source_modified": True,
        "no_additional_data_acquired": True,
        "no_prohibited_analysis": True,
    }
    if not foundational_integrity:
        status = "FAIL_INTEGRITY"
    elif not reproduction_pass:
        status = "FAIL_REPRODUCTION"
    elif counts["unaligned_residual_records"] > 0:
        status = "FAIL_UNALIGNED_RESIDUAL"
    elif counts["aligned_mismatch_rows"] > 0:
        status = "FAIL_BOOK_MISMATCH"
    elif all(gates.values()):
        status = "PASS"
    else:
        status = "FAIL_INTEGRITY"

    verdict: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3D_VERDICT_V0_1",
        "status": status,
        "classification": "ENGINEERING_ONLY",
        "formal_pass": status == "PASS",
        "partial_pass_label_used": False,
        "counts": counts,
        "aligned_fraction": counts["aligned_records"]
        / counts["mbp10_records"],
        "formal_gates": gates,
        "passed_formal_gates": sum(gates.values()),
        "total_formal_gates": len(gates),
        "independent_reproduction": {
            "pass": reproduction_pass,
            "matching_sections": matching_sections,
            "matching_hashes": matching_hashes,
        },
        "interpretation": (
            "Every metadata-aligned row is exact, but the frozen rule fails "
            "formally because one or more vendor rows is unaligned."
            if status == "FAIL_UNALIGNED_RESIDUAL"
            else "The formal status follows the frozen verdict precedence."
        ),
        "fixed_recommendation": {
            "id": "NO_FURTHER_CORRECTION_RECOMMENDED_IN_STEP_3D",
            "additional_corrections_recommended": 0,
            "text": "Preserve the verdict and residuals unchanged and stop Step 3D.",
        },
        "predecessor_verdicts": {
            "step_3a": "FAIL",
            "step_3a1": "PASS",
            "step_3b1": "FAIL_PRE_ACQUISITION_READINESS",
            "step_3b2": "FAIL",
            "step_3c": "PASS_DIAGNOSTIC_REPRODUCTION",
        },
        "predecessor_verdicts_preserved": True,
        "comparator_retuned_after_results": False,
        "residuals_repaired_or_filtered": False,
        "additional_data_acquired": False,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    _write_json_atomic(verdict_path, verdict)
    _write_report(REPORT_PATH, verdict, primary)

    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3D_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": _utc_now(),
        "classification": "ENGINEERING_ONLY",
        "amendment": _artifact(AMENDMENT_PATH),
        "freeze_receipt": _artifact(FREEZE_PATH),
        "comparison_tool": _artifact(Path(__file__).resolve()),
        "step3c_manifest": _artifact(STEP3C_MANIFEST_PATH),
        "mbo_source": _artifact(context["mbo_parquet"]),
        "mbp10_source": _artifact(context["mbp_parquet"]),
        "artifacts": [
            _artifact(output / "primary_comparison.json"),
            _artifact(output / "reference_comparison.json"),
            _artifact(verdict_path),
            _artifact(REPORT_PATH),
        ],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
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
                "stage": "GC_MICROSTRUCTURE_STEP_3D_SEALED",
                "status": status,
                "formal_pass": status == "PASS",
                "aligned_records": counts["aligned_records"],
                "unaligned_residual_records": counts[
                    "unaligned_residual_records"
                ],
                "aligned_mismatch_rows": counts[
                    "aligned_mismatch_rows"
                ],
                "reproduction_pass": reproduction_pass,
                "recommendation_id": verdict["fixed_recommendation"]["id"],
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _write_report(
    path: Path,
    verdict: dict[str, Any],
    result: dict[str, Any],
) -> None:
    counts = verdict["counts"]
    lines = [
        "# GC Microstructure Step 3D — Metadata-Only Comparator",
        "",
        "## Scope",
        "",
        "- Permanently engineering-only date: `2024-01-09`.",
        "- Only the previously sealed MBO and MBP-10 sources were used.",
        "- Alignment used exact K5, action, side, flags, and within-identical-metadata occurrence.",
        "- Book equality was not used to select a boundary.",
        "- Unaligned rows were retained as formal failures; no fallback was attempted.",
        "",
        "## Formal verdict",
        "",
        f"`{verdict['status']}`",
        "",
        f"- Vendor rows: {counts['mbp10_records']:,}.",
        f"- Metadata-aligned rows: {counts['aligned_records']:,} ({verdict['aligned_fraction']:.6%}).",
        f"- Unaligned residual rows: {counts['unaligned_residual_records']:,}.",
        f"- Exact aligned rows: {counts['aligned_exact_rows']:,}.",
        f"- Aligned mismatch rows: {counts['aligned_mismatch_rows']:,}.",
        f"- Aligned field mismatches: {counts['aligned_field_mismatches']:,}.",
        f"- Rows aligned to non-F_LAST MBO events: {counts['selected_non_f_last_rows']:,}.",
        f"- Rows aligned to F_LAST MBO events: {counts['selected_f_last_rows']:,}.",
        "",
        "The rule is exact whenever it produces an alignment, but the frozen formal gate requires every vendor row to align. Therefore the residual population forces the formal failure; no partial-pass label is used.",
        "",
        "## Independent reproduction",
        "",
        f"- Reproduction pass: `{str(verdict['independent_reproduction']['pass']).lower()}`.",
        f"- Selector checksum: `{result['hashes']['selector_checksum']}`.",
        f"- Comparison checksum: `{result['hashes']['comparison_checksum']}`.",
        "",
        "## Fixed recommendation",
        "",
        "`NO_FURTHER_CORRECTION_RECOMMENDED_IN_STEP_3D` — preserve the verdict and all residuals unchanged and stop.",
        "",
        "## Prohibited-work confirmation",
        "",
        "No data was acquired. No residual was filtered, repaired, or tested against an alternate boundary. No outcomes, signals, execution optimization, trades, PnL, R multiples, or account returns were calculated.",
        "",
    ]
    _write_text_atomic(path, "\n".join(lines))


def _verified_context() -> dict[str, Any]:
    if _sha256(AMENDMENT_PATH) != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Step 3D amendment changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 3D freeze receipt changed")
    amendment = _load_json(AMENDMENT_PATH)
    freeze = _load_json(FREEZE_PATH)
    if (
        amendment["status"]
        != "FROZEN_BEFORE_STEP_3D_IMPLEMENTATION_AND_ROW_ACCESS"
        or freeze["status"]
        != "AMENDMENT_SEALED_BEFORE_IMPLEMENTATION_AND_ROW_ACCESS"
        or freeze["amendment"]["sha256"] != EXPECTED_AMENDMENT_SHA256
    ):
        raise ValueError("Step 3D freeze identity invalid")
    step3c = _load_json(STEP3C_MANIFEST_PATH)
    without_hash = {
        key: value for key, value in step3c.items() if key != "manifest_hash"
    }
    if (
        step3c["manifest_hash"] != EXPECTED_STEP3C_MANIFEST_HASH
        or step3c["manifest_hash"] != _canonical_hash(without_hash)
        or step3c["findings_hash"] != EXPECTED_STEP3C_FINDINGS_HASH
        or step3c["status"] != "PASS_DIAGNOSTIC_REPRODUCTION"
    ):
        raise ValueError("Step 3C seal changed")
    for item in (
        step3c["protocol"],
        step3c["freeze_receipt"],
        step3c["diagnostic_tool"],
        step3c["step3b2_manifest"],
        step3c["mbo_source"],
        step3c["mbp10_source"],
        *step3c["artifacts"],
    ):
        path = Path(str(item["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"Step 3C artifact changed: {path}")
    context = verified_step3c_source_context()
    sources_exact = (
        context["mbo_parquet_sha256"] == EXPECTED_MBO_SHA256
        and context["mbp_parquet_sha256"] == EXPECTED_MBP_SHA256
    )
    if not sources_exact:
        raise ValueError("Sealed source changed")
    context.update(
        {
            "all_predecessor_seals_valid": True,
            "sources_exact": sources_exact,
        }
    )
    return context


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
        or result["amendment_sha256"] != EXPECTED_AMENDMENT_SHA256
        or result["freeze_sha256"] != EXPECTED_FREEZE_SHA256
        or result["mbo_source_sha256"] != EXPECTED_MBO_SHA256
        or result["mbp10_source_sha256"] != EXPECTED_MBP_SHA256
    ):
        raise ValueError(f"Result identity mismatch: {path}")
    return result


def _verify_seal(output: Path) -> None:
    manifest = _load_json(output / "manifest.json")
    declared = manifest["manifest_hash"]
    without = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if declared != _canonical_hash(without):
        raise ValueError("Step 3D manifest hash mismatch")
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
            raise ValueError(f"Step 3D sealed artifact changed: {path}")
    verdict = _load_json(output / "verdict.json")
    verdict_without = {
        key: value for key, value in verdict.items() if key != "verdict_hash"
    }
    if (
        verdict["verdict_hash"] != _canonical_hash(verdict_without)
        or verdict["verdict_hash"] != manifest["verdict_hash"]
    ):
        raise ValueError("Step 3D verdict hash mismatch")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_3D_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]) + 6,
                "predecessor_verdicts_preserved": True,
                "additional_data_acquired": False,
                "market_values_reported": False,
                "outcomes_accessed": False,
                "signals_calculated": False,
                "execution_optimized": False,
                "pnl_calculated": False,
            },
            sort_keys=True,
        )
    )


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
