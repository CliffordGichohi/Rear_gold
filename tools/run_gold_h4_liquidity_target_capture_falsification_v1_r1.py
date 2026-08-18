from __future__ import annotations

import gc
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

import run_gold_h4_liquidity_target_capture_falsification_v1 as base
from materialize_gold_point_in_time_auction_state_v1_outcomes import RangeTree as OriginalRangeTree
from materialize_gold_point_in_time_auction_state_v1_tape import canonical_json, file_record, load_price, sha256_file, utc_now, write_json_exclusive


AMENDMENT = base.ROOT / "research_manifests/gold_h4_liquidity_target_capture_falsification_v1_amendment_a.json"
FAILURE = base.OUTPUT / "attempt_1_failure.json"
RECOVERY_FREEZE = base.ROOT / "research_manifests/gold_h4_liquidity_target_capture_falsification_v1_recovery_freeze_a.json"
RECOVERY_OPENING = base.OUTPUT / "recovery_path_opening_a.json"
RECOVERY_TESTS = base.ROOT / "tests/test_gold_h4_liquidity_target_capture_falsification_v1_r1.py"


class ImmutableRangeTreeCache:
    _cache: dict[tuple[int, int], OriginalRangeTree] = {}

    def __new__(cls, high: np.ndarray, low: np.ndarray) -> OriginalRangeTree:
        key = (id(high), id(low))
        tree = cls._cache.get(key)
        if tree is None:
            tree = OriginalRangeTree(high, low)
            cls._cache[key] = tree
        return tree

    @classmethod
    def clear(cls) -> None:
        cls._cache.clear()


def cache_proof() -> dict[str, Any]:
    high = np.asarray([10, 13, 11, 15, 12], dtype=np.int64)
    low = np.asarray([4, 6, 3, 8, 7], dtype=np.int64)
    uncached = OriginalRangeTree(high, low)
    cached_a = ImmutableRangeTreeCache(high, low)
    cached_b = ImmutableRangeTreeCache(high, low)
    if cached_a is not cached_b:
        raise AssertionError("Cache did not reuse immutable range tree")
    comparisons = [
        uncached.extrema_primary(0, 5) == cached_a.extrema_primary(0, 5),
        uncached.extrema_reference(0, 5) == cached_a.extrema_reference(0, 5),
        uncached.first_high_primary(0, 5, 13) == cached_a.first_high_primary(0, 5, 13),
        uncached.first_high_reference(0, 5, 13) == cached_a.first_high_reference(0, 5, 13),
        uncached.first_low_primary(0, 5, 4) == cached_a.first_low_primary(0, 5, 4),
        uncached.first_low_reference(0, 5, 4) == cached_a.first_low_reference(0, 5, 4),
    ]
    if not all(comparisons):
        raise AssertionError("Cached and uncached queries differ")
    ImmutableRangeTreeCache.clear()
    return {
        "status": "PASS_SYNTHETIC_IMMUTABLE_RANGE_TREE_CACHE_PROOF",
        "same_object_reused": True,
        "primary_reference_query_comparisons": len(comparisons),
        "all_query_comparisons_equal": True,
    }


def recovery_preflight() -> dict[str, Any]:
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    original = json.loads(base.PREPATH_FREEZE.read_text(encoding="utf-8"))
    if amendment.get("status") != "FROZEN_BEFORE_RECOVERY_PATH_REOPENING":
        raise ValueError("Amendment A is not frozen")
    if failure.get("status") != "FAIL_ATTEMPT_1_INFRASTRUCTURE_TIMEOUT_NO_RESULT":
        raise ValueError("Attempt 1 failure was not preserved")
    if failure.get("partial_case_payload_written") is not False or failure.get("partial_result_payload_written") is not False:
        raise ValueError("Attempt 1 produced a partial research payload")
    if original.get("status") != "SEALED_BEFORE_2021_2024_POST_TARGET_PATH_ACCESS":
        raise ValueError("Original prepath freeze changed")
    implementation_record = original["controls"]["implementation"]
    if base.IMPLEMENTATION.stat().st_size != int(implementation_record["bytes"]) or sha256_file(base.IMPLEMENTATION) != str(implementation_record["sha256"]):
        raise ValueError("Original implementation changed after freeze")
    base.ceiling.verify_predecessor_seal()
    prior = json.loads(base.PREDECESSOR_FINAL_SEAL.read_text(encoding="utf-8"))
    for key in (
        "contract", "protocol", "original_prepath_freeze", "original_failure", "amendment_a",
        "recovery_freeze", "final_result", "certification", "report",
    ):
        base.verify_record(prior[key])
    for path, expected, label in (
        (base.ceiling.PRIMARY_PLANS, base.ceiling.EXPECTED["primary_plans"], "primary plans"),
        (base.ceiling.REFERENCE_PLANS, base.ceiling.EXPECTED["reference_plans"], "reference plans"),
        (base.ceiling.PRIMARY_OOF, base.ceiling.EXPECTED["primary_oof"], "primary OOF"),
        (base.ceiling.REFERENCE_OOF, base.ceiling.EXPECTED["reference_oof"], "reference OOF"),
        (base.ceiling.RAW_PRICE, base.ceiling.EXPECTED["raw_price"], "raw price"),
    ):
        base.ceiling.verify_record(path, expected, label)
    if not RECOVERY_TESTS.exists():
        raise FileNotFoundError(RECOVERY_TESTS)
    allowed = {base.OPENING.name, FAILURE.name}
    present = {path.name for path in base.OUTPUT.iterdir()}
    if present != allowed:
        raise ValueError({"unexpected_artifacts": sorted(present - allowed), "missing": sorted(allowed - present)})
    if any(path.exists() for path in (
        RECOVERY_FREEZE, RECOVERY_OPENING, base.PRIMARY_CASES, base.REFERENCE_CASES,
        base.PRIMARY_RESULTS, base.REFERENCE_RESULTS, base.CERTIFICATION, base.FINAL_RESULT,
        base.FINAL_FREEZE, base.REPORT,
    )):
        raise FileExistsError("Recovery outputs already exist")
    return {"amendment": amendment, "failure": failure, "original": original}


def seal_recovery(proof: Mapping[str, Any]) -> None:
    write_json_exclusive(
        RECOVERY_FREEZE,
        {
            "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_RECOVERY_FREEZE_A_1_0",
            "status": "SEALED_BEFORE_RECOVERY_PATH_REOPENING",
            "sealed_at_utc": utc_now(),
            "controls": {
                "contract": file_record(base.CONTRACT),
                "protocol": file_record(base.PROTOCOL),
                "original_prepath_freeze": file_record(base.PREPATH_FREEZE),
                "original_implementation": file_record(base.IMPLEMENTATION),
                "attempt_1_failure": file_record(FAILURE),
                "amendment_a": file_record(AMENDMENT),
                "recovery_implementation": file_record(Path(__file__).resolve()),
                "recovery_tests": file_record(RECOVERY_TESTS),
            },
            "single_change": "REUSE_ONE_IMMUTABLE_RANGE_TREE_PER_IN_MEMORY_PRICE_FRAME",
            "cache_proof": dict(proof),
            "cumulative_path_opening_count_before_recovery": 1,
            "research_result_produced_before_recovery": False,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )


def main() -> None:
    recovery_preflight()
    proof = cache_proof()
    seal_recovery(proof)
    write_json_exclusive(
        RECOVERY_OPENING,
        {
            "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_RECOVERY_OPENING_A_1_0",
            "status": "SECOND_AND_FINAL_CONTROLLED_2021_2024_PATH_OPENING",
            "opened_at_utc": utc_now(),
            "recovery_freeze": file_record(RECOVERY_FREEZE),
            "cumulative_path_opening_count": 2,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    ImmutableRangeTreeCache.clear()
    base.RangeTree = ImmutableRangeTreeCache
    base.ceiling.RangeTree = ImmutableRangeTreeCache
    frames, price_diagnostics = load_price()
    primary_rows, primary_materialization, primary_catalogs = base.run_implementation(
        "primary", frames, base.ceiling.PRIMARY_PLANS, base.ceiling.PRIMARY_OOF, base.PREDECESSOR_CASES_PRIMARY, base.PRIMARY_CASES
    )
    reference_rows, reference_materialization, reference_catalogs = base.run_implementation(
        "reference", frames, base.ceiling.REFERENCE_PLANS, base.ceiling.REFERENCE_OOF, base.PREDECESSOR_CASES_REFERENCE, base.REFERENCE_CASES
    )
    if primary_catalogs != reference_catalogs:
        raise RuntimeError("FAIL_PIVOT_CATALOG_REPRODUCTION")
    compare_materialization = [
        key for key in ("rows", "cases_per_policy", "control_retained", "control_skipped", "target_first_cases", "complete_row_checksum")
        if primary_materialization[key] != reference_materialization[key]
    ]
    case_bytes_identical = sha256_file(base.PRIMARY_CASES) == sha256_file(base.REFERENCE_CASES)
    if compare_materialization or not case_bytes_identical:
        raise RuntimeError({"status": "FAIL_CASE_REPRODUCTION", "differences": compare_materialization, "byte_identical": case_bytes_identical})
    primary_result = base.summarize(primary_rows, primary_catalogs)
    reference_result = base.summarize(reference_rows, reference_catalogs)
    if canonical_json(primary_result) != canonical_json(reference_result):
        raise RuntimeError("FAIL_RESULT_REPRODUCTION")
    write_json_exclusive(base.PRIMARY_RESULTS, primary_result)
    write_json_exclusive(base.REFERENCE_RESULTS, reference_result)
    results_identical = sha256_file(base.PRIMARY_RESULTS) == sha256_file(base.REFERENCE_RESULTS)
    if not results_identical:
        raise RuntimeError("FAIL_RESULT_BYTE_REPRODUCTION")
    certification = {
        "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_CERTIFICATION_R1_1_0",
        "status": "PASS_INDEPENDENT_REPRODUCTION_UNDER_AMENDMENT_A",
        "certified_at_utc": utc_now(),
        "primary_materialization": primary_materialization,
        "reference_materialization": reference_materialization,
        "catalogs": primary_catalogs,
        "materialization_differences": compare_materialization,
        "case_payloads_byte_identical": case_bytes_identical,
        "results_byte_identical": results_identical,
        "price_diagnostics": price_diagnostics,
        "attempt_1_failure": file_record(FAILURE),
        "amendment_a": file_record(AMENDMENT),
        "recovery_freeze": file_record(RECOVERY_FREEZE),
        "range_tree_cache_entries": len(ImmutableRangeTreeCache._cache),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(base.CERTIFICATION, certification)
    final = {
        **primary_result,
        "completed_at_utc": utc_now(),
        "attempt_1_failure": file_record(FAILURE),
        "amendment_a": file_record(AMENDMENT),
        "recovery_freeze": file_record(RECOVERY_FREEZE),
        "primary_cases": file_record(base.PRIMARY_CASES),
        "reference_cases": file_record(base.REFERENCE_CASES),
        "primary_results": file_record(base.PRIMARY_RESULTS),
        "reference_results": file_record(base.REFERENCE_RESULTS),
        "certification": file_record(base.CERTIFICATION),
    }
    write_json_exclusive(base.FINAL_RESULT, final)
    base.REPORT.write_text(base.render_report(final, certification), encoding="utf-8", newline="\n")
    write_json_exclusive(
        base.FINAL_FREEZE,
        {
            "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_FINAL_FREEZE_R1_1_0",
            "status": "SEALED_FINAL_FALSIFICATION_UNDER_AMENDMENT_A",
            "sealed_at_utc": utc_now(),
            "verdict": final["verdict"],
            "contract": file_record(base.CONTRACT),
            "protocol": file_record(base.PROTOCOL),
            "original_prepath_freeze": file_record(base.PREPATH_FREEZE),
            "attempt_1_failure": file_record(FAILURE),
            "amendment_a": file_record(AMENDMENT),
            "recovery_freeze": file_record(RECOVERY_FREEZE),
            "predecessor_final_seal": file_record(base.PREDECESSOR_FINAL_SEAL),
            "original_path_opening": file_record(base.OPENING),
            "recovery_path_opening": file_record(RECOVERY_OPENING),
            "final_result": file_record(base.FINAL_RESULT),
            "certification": file_record(base.CERTIFICATION),
            "report": file_record(base.REPORT),
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    print(canonical_json({"status": final["verdict"], "best": final["best_observed_policy"], "ceiling": final["target_only_hindsight_ceiling"], "result": file_record(base.FINAL_RESULT)}))
    ImmutableRangeTreeCache.clear()
    del frames, primary_rows, reference_rows
    gc.collect()


if __name__ == "__main__":
    main()
