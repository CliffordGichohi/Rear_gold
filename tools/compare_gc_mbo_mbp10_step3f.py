#!/usr/bin/env python3
"""Run the frozen Step 3F two-stage engineering-only comparator."""

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
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3f_amendment_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3f_freeze_v01.json"
)
STEP3E_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_3e_v01"
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
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_3f_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_3F_REPORT.md"

EXPECTED_AMENDMENT_SHA256 = (
    "f98b6766f179fb6ed5da8a1ff3a3bdf6a6029697c840012569a68fdabe8d0d88"
)
EXPECTED_FREEZE_SHA256 = (
    "5df19f6f731a01da1409d2b344122510b4e54ea4ccd4aa9da16036a53e910702"
)
EXPECTED_STEP3E_MANIFEST_HASH = (
    "8ad2aef85445e587a8a8f24ff87945e519f3c72ce353896834dc5cf2b5d33b60"
)
EXPECTED_STEP3E_FINDINGS_HASH = (
    "ec75b90cea6289e5e063d5a003ef34010ceb8f64080a8a1bc4a0f8220de4a8ad"
)
EXPECTED_MBO_SHA256 = (
    "43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3"
)
EXPECTED_MBP_SHA256 = (
    "4ead358f538d7c383a14f39bbde35b8ccfa21e38e58205edbc51bedfb2ed80d4"
)
EXPECTED_MBO_RECORDS = 2_322_905
EXPECTED_MBP_RECORDS = 1_924_786
EXPECTED_PRIMARY_SELECTED = 1_922_234
EXPECTED_FALLBACK_SELECTED = 2_552
EXPECTED_UNALIGNED = 0
EXPECTED_REUSE = 0

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
    _verified_context()
    output.mkdir(parents=True, exist_ok=True)
    if action in {"primary", "reference"}:
        destination = output / f"{action}_comparison.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite: {destination}")
        result = compare_sources(implementation=action)
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
                    "stage": f"GC_MICROSTRUCTURE_STEP_3F_{action.upper()}_COMPLETE",
                    "implementation": action,
                    "mbo_records": result["counts"]["mbo_records"],
                    "mbp10_records": result["counts"]["mbp10_records"],
                    "primary_selected": result["counts"][
                        "primary_selected_records"
                    ],
                    "fallback_selected": result["counts"][
                        "fallback_selected_records"
                    ],
                    "unaligned_records": result["counts"][
                        "unaligned_records"
                    ],
                    "selected_mismatch_rows": result["counts"][
                        "selected_mismatch_rows"
                    ],
                    "selected_field_mismatches": result["counts"][
                        "selected_field_mismatches"
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
        _seal(output)
        return
    if action == "verify":
        _verify_seal(output)
        return
    raise AssertionError(action)


def compare_sources(*, implementation: str) -> dict[str, Any]:
    replay_audit: dict[str, Any] = {}
    vendor_audit: dict[str, Any] = {}
    mbo_stream = iter(
        _mbo_groups(
            MBO_PATH,
            implementation=implementation,
            audit=replay_audit,
        )
    )
    vendor_stream = iter(_vendor_groups(MBP_PATH, audit=vendor_audit))
    current_mbo = next(mbo_stream, None)
    current_vendor = next(vendor_stream, None)

    counts: Counter[str] = Counter()
    state_counts: dict[str, Counter[str]] = defaultdict(Counter)
    mismatch_fields: Counter[str] = Counter()
    mismatch_families: Counter[str] = Counter()
    mismatch_sides: Counter[str] = Counter()
    mismatch_depths: Counter[str] = Counter()
    selector_hash = hashlib.sha256()
    comparison_hash = hashlib.sha256()
    vendor_state_hash = hashlib.sha256()
    reconstructed_state_hash = hashlib.sha256()

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
            for vendor_row in vendor_group:
                counts["unaligned_records"] += 1
                _hash_selector_decision(
                    selector_hash,
                    vendor_row,
                    primary_occurrence=0,
                    fallback_occurrence=0,
                    stage="UNALIGNED",
                    selected_ordinal=-1,
                )
            current_vendor = next(vendor_stream, None)
        else:
            assert current_mbo is not None and current_vendor is not None
            _, mbo_group = current_mbo
            _, vendor_group = current_vendor
            counts["mbo_records"] += len(mbo_group)
            counts["mbp10_records"] += len(vendor_group)
            counts["shared_k3_groups"] += 1
            _compare_group(
                mbo_group,
                vendor_group,
                counts=counts,
                state_counts=state_counts,
                mismatch_fields=mismatch_fields,
                mismatch_families=mismatch_families,
                mismatch_sides=mismatch_sides,
                mismatch_depths=mismatch_depths,
                selector_hash=selector_hash,
                comparison_hash=comparison_hash,
                vendor_state_hash=vendor_state_hash,
                reconstructed_state_hash=reconstructed_state_hash,
            )
            current_mbo = next(mbo_stream, None)
            current_vendor = next(vendor_stream, None)

    for name in (
        "mbo_records",
        "mbp10_records",
        "primary_selected_records",
        "fallback_triggered_records",
        "fallback_selected_records",
        "unaligned_records",
        "selected_records",
        "selected_exact_rows",
        "selected_mismatch_rows",
        "selected_field_mismatches",
        "primary_mismatch_rows",
        "primary_field_mismatches",
        "fallback_mismatch_rows",
        "fallback_field_mismatches",
        "selected_mbo_reuse",
        "alternative_candidate_attempts",
    ):
        counts.setdefault(name, 0)
    counts["compared_book_fields"] = counts["selected_records"] * 60
    traceability = {
        "mbo_records_exact": counts["mbo_records"]
        == EXPECTED_MBO_RECORDS,
        "mbp10_records_exact": counts["mbp10_records"]
        == EXPECTED_MBP_RECORDS,
        "primary_selected_exact": counts["primary_selected_records"]
        == EXPECTED_PRIMARY_SELECTED,
        "fallback_selected_exact": counts["fallback_selected_records"]
        == EXPECTED_FALLBACK_SELECTED,
        "unaligned_exact": counts["unaligned_records"]
        == EXPECTED_UNALIGNED,
        "selected_reuse_exact": counts["selected_mbo_reuse"]
        == EXPECTED_REUSE,
    }
    integrity = {
        "all_mbo_rows_processed": counts["mbo_records"]
        == EXPECTED_MBO_RECORDS,
        "all_mbp10_rows_processed": counts["mbp10_records"]
        == EXPECTED_MBP_RECORDS,
        "every_vendor_row_classified_once": counts["mbp10_records"]
        == counts["selected_records"] + counts["unaligned_records"],
        "all_selected_rows_compared": counts["selected_records"]
        == counts["selected_exact_rows"] + counts["selected_mismatch_rows"],
        "selector_traceability_reproduced": all(traceability.values()),
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
        "market_state_coverage_complete": sum(
            values["vendor_records"] for values in state_counts.values()
        )
        == counts["mbp10_records"],
        "no_alternative_candidate_attempts": counts[
            "alternative_candidate_attempts"
        ]
        == 0,
    }
    selector_audit = {
        "rule": "EXACT_METADATA_THEN_ACTION_OCCURRENCE_V0_1",
        "primary_fields": [
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
        "fallback_fields": [
            "publisher_id",
            "instrument_id",
            "sequence",
            "ts_event",
            "ts_recv",
            "action",
            "within_action_occurrence",
        ],
        "fallback_occurrence_includes_all_vendor_rows": True,
        "fallback_triggered_only_by_primary_absence": True,
        "book_values_used_for_selection": False,
        "primary_mismatch_triggered_fallback": False,
        "alternative_candidates_tried": 0,
        "selection_final_after_metadata": True,
        "another_date_inspected": False,
    }
    result: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3F_COMPARISON_V0_1",
        "implementation": implementation,
        "classification": "ENGINEERING_ONLY",
        "counts": _counter_dict(counts),
        "market_state_counts": _nested_counter_dict(state_counts),
        "mismatch_field_counts": _counter_dict(mismatch_fields),
        "mismatch_field_family": _counter_dict(mismatch_families),
        "mismatch_field_side": _counter_dict(mismatch_sides),
        "mismatch_field_depth": _counter_dict(mismatch_depths),
        "selector_traceability_checks": traceability,
        "integrity_checks": integrity,
        "selector_audit": selector_audit,
        "replay_audit": replay_audit,
        "vendor_audit": vendor_audit,
        "hashes": {
            "selector_checksum": selector_hash.hexdigest(),
            "comparison_checksum": comparison_hash.hexdigest(),
            "selected_vendor_state_hash": vendor_state_hash.hexdigest(),
            "selected_reconstructed_state_hash": (
                reconstructed_state_hash.hexdigest()
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
        "selection_retuned_after_results": False,
        "additional_fallback_implemented": False,
        "additional_data_acquired": False,
        "another_date_inspected": False,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    result["comparison_payload_hash"] = _canonical_hash(result)
    return result


def _compare_group(
    mbo: list[MboRecord],
    vendor: list[VendorRecord],
    *,
    counts: Counter[str],
    state_counts: dict[str, Counter[str]],
    mismatch_fields: Counter[str],
    mismatch_families: Counter[str],
    mismatch_sides: Counter[str],
    mismatch_depths: Counter[str],
    selector_hash: Any,
    comparison_hash: Any,
    vendor_state_hash: Any,
    reconstructed_state_hash: Any,
) -> None:
    exact_mbo: dict[
        tuple[tuple[int, int, int, int, int], str, str, int],
        list[MboRecord],
    ] = defaultdict(list)
    action_mbo: dict[
        tuple[tuple[int, int, int, int, int], str], list[MboRecord]
    ] = defaultdict(list)
    for row in mbo:
        exact_mbo[(row.key5, row.action, row.side, row.flags)].append(row)
        action_mbo[(row.key5, row.action)].append(row)

    exact_vendor_occurrence: Counter[
        tuple[tuple[int, int, int, int, int], str, str, int]
    ] = Counter()
    action_vendor_occurrence: Counter[
        tuple[tuple[int, int, int, int, int], str]
    ] = Counter()
    selected_ordinals: set[int] = set()
    for vendor_row in vendor:
        state = _market_state(vendor_row.key5[4])
        state_counts[state]["vendor_records"] += 1
        exact_key = (
            vendor_row.key5,
            vendor_row.action,
            vendor_row.side,
            vendor_row.flags,
        )
        action_key = (vendor_row.key5, vendor_row.action)
        exact_vendor_occurrence[exact_key] += 1
        action_vendor_occurrence[action_key] += 1
        primary_occurrence = exact_vendor_occurrence[exact_key]
        fallback_occurrence = action_vendor_occurrence[action_key]
        primary_available = exact_mbo.get(exact_key, [])
        if primary_occurrence <= len(primary_available):
            selected = primary_available[primary_occurrence - 1]
            stage = "PRIMARY"
            counts["primary_selected_records"] += 1
            state_counts[state]["primary_selected_records"] += 1
        else:
            counts["fallback_triggered_records"] += 1
            state_counts[state]["fallback_triggered_records"] += 1
            fallback_available = action_mbo.get(action_key, [])
            if fallback_occurrence <= len(fallback_available):
                selected = fallback_available[fallback_occurrence - 1]
                stage = "FALLBACK"
                counts["fallback_selected_records"] += 1
                state_counts[state]["fallback_selected_records"] += 1
            else:
                selected = None
                stage = "UNALIGNED"
                counts["unaligned_records"] += 1
                state_counts[state]["unaligned_records"] += 1

        _hash_selector_decision(
            selector_hash,
            vendor_row,
            primary_occurrence=primary_occurrence,
            fallback_occurrence=fallback_occurrence,
            stage=stage,
            selected_ordinal=(selected.ordinal if selected is not None else -1),
        )
        if selected is None:
            comparison_hash.update(b"UNALIGNED")
            comparison_hash.update(KEY5_STRUCT.pack(*vendor_row.key5))
            comparison_hash.update(INT64.pack(vendor_row.ordinal))
            continue

        counts["selected_records"] += 1
        state_counts[state]["selected_records"] += 1
        if selected.ordinal in selected_ordinals:
            counts["selected_mbo_reuse"] += 1
            state_counts[state]["selected_mbo_reuse"] += 1
        selected_ordinals.add(selected.ordinal)
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
            counts["selected_mismatch_rows"] += 1
            counts["selected_field_mismatches"] += len(
                field_mismatch_names
            )
            counts[f"{stage.lower()}_mismatch_rows"] += 1
            counts[f"{stage.lower()}_field_mismatches"] += len(
                field_mismatch_names
            )
            state_counts[state]["selected_mismatch_rows"] += 1
            state_counts[state]["selected_field_mismatches"] += len(
                field_mismatch_names
            )
            for name in field_mismatch_names:
                mismatch_fields[name] += 1
                side, family, depth = name.split("_")
                mismatch_sides[side] += 1
                mismatch_families[family] += 1
                mismatch_depths[depth] += 1
        else:
            counts["selected_exact_rows"] += 1
            state_counts[state]["selected_exact_rows"] += 1

        _hash_levels(vendor_state_hash, vendor_row.levels)
        _hash_levels(reconstructed_state_hash, selected.post)
        comparison_hash.update(stage.encode("ascii"))
        comparison_hash.update(KEY5_STRUCT.pack(*vendor_row.key5))
        comparison_hash.update(INT64.pack(vendor_row.ordinal))
        comparison_hash.update(INT64.pack(selected.ordinal))
        for name in field_mismatch_names:
            comparison_hash.update(name.encode("ascii"))
            comparison_hash.update(b"\x00")


def _hash_selector_decision(
    digest: Any,
    vendor: VendorRecord,
    *,
    primary_occurrence: int,
    fallback_occurrence: int,
    stage: str,
    selected_ordinal: int,
) -> None:
    digest.update(KEY5_STRUCT.pack(*vendor.key5))
    digest.update(INT64.pack(vendor.ordinal))
    digest.update(vendor.action.encode("ascii"))
    digest.update(vendor.side.encode("ascii"))
    digest.update(INT64.pack(vendor.flags))
    digest.update(INT64.pack(primary_occurrence))
    digest.update(INT64.pack(fallback_occurrence))
    digest.update(stage.encode("ascii"))
    digest.update(INT64.pack(selected_ordinal))


def _hash_levels(digest: Any, levels: tuple[int, ...]) -> None:
    for value in levels:
        digest.update(INT64.pack(value))


def _seal(output: Path) -> None:
    verdict_path = output / "verdict.json"
    manifest_path = output / "manifest.json"
    if verdict_path.exists() or manifest_path.exists() or REPORT_PATH.exists():
        raise FileExistsError("Refusing to overwrite Step 3F seal")
    primary = _verified_result(output / "primary_comparison.json", "primary")
    reference = _verified_result(
        output / "reference_comparison.json", "reference"
    )
    sections = (
        "counts",
        "market_state_counts",
        "mismatch_field_counts",
        "mismatch_field_family",
        "mismatch_field_side",
        "mismatch_field_depth",
        "selector_traceability_checks",
        "integrity_checks",
        "selector_audit",
    )
    matching_sections = {
        name: primary[name] == reference[name] for name in sections
    }
    matching_hashes = {
        name: primary["hashes"][name] == reference["hashes"][name]
        for name in (
            "selector_checksum",
            "comparison_checksum",
            "selected_vendor_state_hash",
            "selected_reconstructed_state_hash",
            "mbo_input_hash",
            "mbp10_input_hash",
            "final_reconstruction_state_hash",
            "final_reconstruction_structure_hash",
        )
    }
    reproduction_pass = all(matching_sections.values()) and all(
        matching_hashes.values()
    )
    foundational_integrity = (
        all(primary["integrity_checks"].values())
        and all(reference["integrity_checks"].values())
    )
    counts = primary["counts"]
    gates = {
        "all_predecessor_and_source_seals_valid": True,
        "all_mbo_and_mbp10_rows_processed": (
            counts["mbo_records"] == EXPECTED_MBO_RECORDS
            and counts["mbp10_records"] == EXPECTED_MBP_RECORDS
        ),
        "selector_applied_without_book_values": not primary[
            "selector_audit"
        ]["book_values_used_for_selection"],
        "primary_and_fallback_traceability_counts_exact": all(
            primary["selector_traceability_checks"].values()
        )
        and all(reference["selector_traceability_checks"].values()),
        "every_vendor_row_selected": counts["selected_records"]
        == counts["mbp10_records"],
        "unaligned_residual_rows_zero": counts["unaligned_records"] == 0,
        "selected_mbo_reuse_zero": counts["selected_mbo_reuse"] == 0,
        "all_selected_rows_compared": counts["selected_records"]
        == counts["selected_exact_rows"] + counts["selected_mismatch_rows"],
        "selected_book_mismatch_rows_zero": counts[
            "selected_mismatch_rows"
        ]
        == 0,
        "selected_book_field_mismatches_zero": counts[
            "selected_field_mismatches"
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
        "no_rule_retuning_or_additional_fallback": (
            not primary["selection_retuned_after_results"]
            and not primary["additional_fallback_implemented"]
        ),
        "no_data_acquired_or_other_date_inspected": (
            not primary["additional_data_acquired"]
            and not primary["another_date_inspected"]
        ),
        "no_prohibited_analysis": True,
    }
    if not foundational_integrity:
        status = "FAIL_INTEGRITY"
    elif not reproduction_pass:
        status = "FAIL_REPRODUCTION"
    elif counts["unaligned_records"] > 0:
        status = "FAIL_UNALIGNED_RESIDUAL"
    elif counts["selected_mbo_reuse"] > 0:
        status = "FAIL_SELECTED_MBO_REUSE"
    elif counts["selected_mismatch_rows"] > 0:
        status = "FAIL_BOOK_MISMATCH"
    elif all(gates.values()):
        status = "PASS"
    else:
        status = "FAIL_INTEGRITY"
    verdict: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3F_VERDICT_V0_1",
        "status": status,
        "classification": "ENGINEERING_ONLY",
        "formal_pass": status == "PASS",
        "research_or_validation_credit": "NONE",
        "counts": counts,
        "formal_gates": gates,
        "passed_formal_gates": sum(gates.values()),
        "total_formal_gates": len(gates),
        "independent_reproduction": {
            "pass": reproduction_pass,
            "matching_sections": matching_sections,
            "matching_hashes": matching_hashes,
        },
        "interpretation": _interpretation(status, counts),
        "fixed_completion_policy": {
            "further_corrections_permitted": 0,
            "text": "Preserve this formal result and stop Step 3F.",
        },
        "predecessor_verdicts": {
            "step_3d": "FAIL_UNALIGNED_RESIDUAL",
            "step_3e": "PASS_DIAGNOSTIC_REPRODUCTION",
        },
        "predecessor_verdicts_preserved": True,
        "selector_retuned": False,
        "additional_fallback_implemented": False,
        "additional_data_acquired": False,
        "another_date_inspected": False,
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
        "version": "GC_MICROSTRUCTURE_STEP_3F_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": _utc_now(),
        "classification": "ENGINEERING_ONLY",
        "amendment": _artifact(AMENDMENT_PATH),
        "freeze_receipt": _artifact(FREEZE_PATH),
        "comparison_tool": _artifact(Path(__file__).resolve()),
        "step3e_manifest": _artifact(STEP3E_MANIFEST_PATH),
        "mbo_source": _artifact(MBO_PATH),
        "mbp10_source": _artifact(MBP_PATH),
        "artifacts": [
            _artifact(output / "primary_comparison.json"),
            _artifact(output / "reference_comparison.json"),
            _artifact(verdict_path),
            _artifact(REPORT_PATH),
        ],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
        "research_or_validation_credit": "NONE",
        "additional_data_acquired": False,
        "another_date_inspected": False,
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
                "stage": "GC_MICROSTRUCTURE_STEP_3F_SEALED",
                "status": status,
                "formal_pass": status == "PASS",
                "primary_selected": counts["primary_selected_records"],
                "fallback_selected": counts["fallback_selected_records"],
                "unaligned_records": counts["unaligned_records"],
                "selected_mismatch_rows": counts[
                    "selected_mismatch_rows"
                ],
                "selected_field_mismatches": counts[
                    "selected_field_mismatches"
                ],
                "reproduction_pass": reproduction_pass,
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _interpretation(status: str, counts: dict[str, int]) -> str:
    if status == "PASS":
        return "The frozen two-stage selector aligned every vendor row without reuse and every selected post-event book matched exactly on the engineering-only date."
    if status == "FAIL_BOOK_MISMATCH":
        return f"The frozen selector aligned every row without reuse, but {counts['selected_mismatch_rows']} selected rows contained book mismatches."
    if status == "FAIL_UNALIGNED_RESIDUAL":
        return f"The frozen selector left {counts['unaligned_records']} vendor rows unaligned."
    if status == "FAIL_SELECTED_MBO_REUSE":
        return f"The frozen selector reused {counts['selected_mbo_reuse']} selected MBO rows."
    return "The controlling verdict follows the frozen precedence."


def _write_report(
    path: Path,
    verdict: dict[str, Any],
    result: dict[str, Any],
) -> None:
    counts = verdict["counts"]
    lines = [
        "# GC Microstructure Step 3F — Two-Stage Comparator",
        "",
        "## Scope",
        "",
        "- Permanently engineering-only date: `2024-01-09`.",
        "- Primary selector: exact K5, action, side, flags, and occurrence.",
        "- Fallback only on primary metadata absence: exact K5, action, and within-action occurrence across all vendor rows.",
        "- A selected row was final; book equality never selected or changed a boundary.",
        "- No additional data or date was accessed.",
        "",
        "## Formal verdict",
        "",
        f"`{verdict['status']}`",
        "",
        f"- Vendor records: {counts['mbp10_records']:,}.",
        f"- Primary-selected records: {counts['primary_selected_records']:,}.",
        f"- Fallback-selected records: {counts['fallback_selected_records']:,}.",
        f"- Unaligned records: {counts['unaligned_records']:,}.",
        f"- Selected MBO reuse: {counts['selected_mbo_reuse']:,}.",
        f"- Selected exact rows: {counts['selected_exact_rows']:,}.",
        f"- Selected mismatch rows: {counts['selected_mismatch_rows']:,}.",
        f"- Selected field mismatches: {counts['selected_field_mismatches']:,}.",
        f"- Compared book fields: {counts['compared_book_fields']:,}.",
        f"- Primary mismatch rows: {counts['primary_mismatch_rows']:,}.",
        f"- Fallback mismatch rows: {counts['fallback_mismatch_rows']:,}.",
        "",
        verdict["interpretation"],
        "",
        "## Independent reproduction",
        "",
        f"- Reproduction pass: `{str(verdict['independent_reproduction']['pass']).lower()}`.",
        f"- Selector checksum: `{result['hashes']['selector_checksum']}`.",
        f"- Comparison checksum: `{result['hashes']['comparison_checksum']}`.",
        "",
        "## Completion policy",
        "",
        "No additional correction is permitted in Step 3F. This result has no research or validation credit and is preserved as engineering-only.",
        "",
        "No outcomes, signals, execution optimization, trades, PnL, R multiples, or account returns were calculated.",
        "",
    ]
    _write_text_atomic(path, "\n".join(lines))


def _verified_context() -> None:
    if _sha256(AMENDMENT_PATH) != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Step 3F amendment changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 3F freeze receipt changed")
    amendment = _load_json(AMENDMENT_PATH)
    freeze = _load_json(FREEZE_PATH)
    if (
        amendment["status"]
        != "FROZEN_BEFORE_IMPLEMENTATION_AND_ROW_LEVEL_ACCESS"
        or freeze["status"]
        != "AMENDMENT_SEALED_BEFORE_IMPLEMENTATION_AND_ROW_LEVEL_ACCESS"
        or freeze["amendment"]["sha256"] != EXPECTED_AMENDMENT_SHA256
    ):
        raise ValueError("Step 3F freeze identity invalid")
    manifest = _load_json(STEP3E_MANIFEST_PATH)
    without = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if (
        manifest["manifest_hash"] != EXPECTED_STEP3E_MANIFEST_HASH
        or manifest["manifest_hash"] != _canonical_hash(without)
        or manifest["findings_hash"] != EXPECTED_STEP3E_FINDINGS_HASH
        or manifest["status"] != "PASS_DIAGNOSTIC_REPRODUCTION"
    ):
        raise ValueError("Step 3E seal changed")
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
            raise ValueError(f"Step 3E artifact changed: {path}")
    findings = _load_json(
        REPO_ROOT
        / "research_artifacts"
        / "gc_microstructure_step_3e_v01"
        / "findings.json"
    )
    if (
        findings["findings_hash"] != EXPECTED_STEP3E_FINDINGS_HASH
        or findings["recommendation"]["candidate_id"]
        != "C04_ACTION_ONLY"
        or findings["recommendation"]["corrections_recommended"] != 1
    ):
        raise ValueError("Step 3E recommendation seal changed")
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
        or result["amendment_sha256"] != EXPECTED_AMENDMENT_SHA256
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
        raise ValueError("Step 3F manifest hash mismatch")
    for item in (
        manifest["amendment"],
        manifest["freeze_receipt"],
        manifest["comparison_tool"],
        manifest["step3e_manifest"],
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
            raise ValueError(f"Step 3F artifact changed: {path}")
    verdict = _load_json(output / "verdict.json")
    verdict_without = {
        key: value for key, value in verdict.items() if key != "verdict_hash"
    }
    if (
        verdict["verdict_hash"] != _canonical_hash(verdict_without)
        or verdict["verdict_hash"] != manifest["verdict_hash"]
    ):
        raise ValueError("Step 3F verdict hash mismatch")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_3F_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]) + 6,
                "predecessor_verdicts_preserved": True,
                "research_or_validation_credit": "NONE",
                "additional_data_acquired": False,
                "another_date_inspected": False,
                "outcomes_accessed": False,
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
