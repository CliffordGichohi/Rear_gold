from __future__ import annotations

import gc
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

import run_gold_h4_continuation_tradable_ceiling_v1 as base
from materialize_gold_point_in_time_auction_state_v1_outcomes import RangeTree


AMENDMENT = base.ROOT / "research_manifests/gold_h4_continuation_tradable_ceiling_v1_amendment_a.json"
FAILURE = base.OUTPUT / "attempt_1_failure.json"
RECOVERY_FREEZE = base.ROOT / "research_manifests/gold_h4_continuation_tradable_ceiling_v1_recovery_freeze_a.json"
RECOVERY_OPENING = base.OUTPUT / "recovery_path_opening_a.json"
RECOVERY_TESTS = base.ROOT / "tests/test_gold_h4_continuation_tradable_ceiling_v1_r1.py"


def recovery_preflight() -> dict[str, Any]:
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    original = json.loads(base.PREPATH_FREEZE.read_text(encoding="utf-8"))
    if amendment.get("status") != "FROZEN_BEFORE_RECOVERY_PATH_REOPENING" or amendment.get("performance_results_calculated") is not False:
        raise ValueError("Recovery amendment is not frozen")
    if failure.get("status") != "FAIL_FROZEN_ORACLE_COVERAGE_ASSUMPTION":
        raise ValueError("Original failure was not preserved")
    if original.get("status") != "SEALED_BEFORE_H4_PATH_REOPENING":
        raise ValueError("Original prepath freeze changed")
    implementation_record = original["controls"]["implementation"]
    if base.IMPLEMENTATION.stat().st_size != int(implementation_record["bytes"]) or base.sha256_file(base.IMPLEMENTATION) != str(implementation_record["sha256"]):
        raise ValueError("Original attempt implementation changed")
    base.verify_predecessor_seal()
    for path, expected, label in (
        (base.PRIMARY_PLANS, base.EXPECTED["primary_plans"], "primary plans"),
        (base.REFERENCE_PLANS, base.EXPECTED["reference_plans"], "reference plans"),
        (base.PRIMARY_OOF, base.EXPECTED["primary_oof"], "primary OOF"),
        (base.REFERENCE_OOF, base.EXPECTED["reference_oof"], "reference OOF"),
        (base.ATLAS, base.EXPECTED["atlas"], "atlas"),
        (base.RAW_PRICE, base.EXPECTED["raw_price"], "raw price"),
    ):
        base.verify_record(path, expected, label)
    if not RECOVERY_TESTS.exists():
        raise FileNotFoundError(RECOVERY_TESTS)
    allowed = {base.OPENING.name, FAILURE.name}
    present = {path.name for path in base.OUTPUT.iterdir()}
    if present != allowed:
        raise ValueError({"unexpected_existing_recovery_artifacts": sorted(present - allowed), "missing": sorted(allowed - present)})
    if any(path.exists() for path in (RECOVERY_FREEZE, RECOVERY_OPENING, base.PRIMARY_CASES, base.REFERENCE_CASES, base.PRIMARY_RESULT, base.REFERENCE_RESULT, base.FINAL_RESULT, base.CERTIFICATION, base.FINAL_FREEZE, base.REPORT)):
        raise FileExistsError("Recovery outputs already exist")
    return {"amendment": amendment, "failure": failure, "original": original}


def seal_recovery(proof: Mapping[str, Any]) -> None:
    base.write_json_exclusive(
        RECOVERY_FREEZE,
        {
            "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_RECOVERY_FREEZE_A_1_0",
            "status": "SEALED_BEFORE_RECOVERY_PATH_REOPENING",
            "sealed_at_utc": base.utc_now(),
            "controls": {
                "original_prepath_freeze": base.file_record(base.PREPATH_FREEZE),
                "original_failure": base.file_record(FAILURE),
                "amendment_a": base.file_record(AMENDMENT),
                "recovery_implementation": base.file_record(Path(__file__).resolve()),
                "recovery_tests": base.file_record(RECOVERY_TESTS),
            },
            "oracle_coverage": {"executable": 248, "available": 215, "unavailable": 33, "retained_unavailable": 24, "overlap_unavailable": 9},
            "unchanged_decision_population": 248,
            "synthetic_proof": dict(proof),
            "cumulative_source_opening_count_before_recovery": 1,
            "performance_results_calculated": False,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )


def materialize_r1(
    plan_path: Path,
    oof_path: Path,
    destination: Path,
    m1: base.Frame,
    implementation: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    oof_rows, plans, oracle, population = base.load_population(plan_path, oof_path)
    tree = RangeTree(m1.high_e8, m1.low_e8)
    invalid_prefix = np.concatenate(([0], np.cumsum(~m1.valid.astype(bool), dtype=np.int64)))
    output: list[dict[str, Any]] = []
    exits: Counter[str] = Counter()
    for oof in oof_rows:
        identity = str(oof["pullback_id"])
        plan = plans[identity]
        if not bool(oof["traded"]):
            output.append(base.empty_case(oof, plan))
            continue
        row = base.audit_executable_case(oof, plan, oracle.get(identity), m1, tree, invalid_prefix, implementation)
        output.append(row)
        exits[str(row["exit_reason"])] += 1
    executable = [row for row in output if row["case_status"] == "EXECUTABLE"]
    oracle_available = sum(row["oracle_r"] is not None for row in executable)
    oracle_unavailable = len(executable) - oracle_available
    retained_unavailable = sum(row["oracle_r"] is None and bool(row["retained_after_overlap"]) for row in executable)
    overlap_unavailable = sum(row["oracle_r"] is None and not bool(row["retained_after_overlap"]) for row in executable)
    if (len(output), len(executable), sum(bool(row["retained_after_overlap"]) for row in output)) != (424, 248, 198):
        raise ValueError("Recovery audit population changed")
    if (oracle_available, oracle_unavailable, retained_unavailable, overlap_unavailable) != (215, 33, 24, 9):
        raise ValueError("Documented oracle coverage changed")
    output.sort(key=lambda row: (row["decision_date"], row["pullback_id"]))
    base.write_parquet(output, destination)
    checksum = base.canonical_hash([[row[name] for name in base.CASE_SCHEMA.names] for row in output])
    diagnostics = {
        "implementation": implementation,
        "population": population,
        "output_rows": len(output),
        "executable": len(executable),
        "retained": sum(bool(row["retained_after_overlap"]) for row in output),
        "oracle_available": oracle_available,
        "oracle_unavailable": oracle_unavailable,
        "retained_oracle_unavailable": retained_unavailable,
        "overlap_oracle_unavailable": overlap_unavailable,
        "exit_counts": dict(sorted(exits.items())),
        "complete_row_checksum": checksum,
        "output": base.file_record(destination),
    }
    return output, diagnostics


def summarize_r1(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # The predecessor summary function is reused for every tradable stage. A
    # zero placeholder exists only inside this call so its oracle-only scalar
    # can be replaced immediately; no case field or output is imputed.
    placeholder_rows: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        if row["case_status"] == "EXECUTABLE" and row["behavioural_oracle_usd"] is None:
            row["behavioural_oracle_usd"] = 0.0
        placeholder_rows.append(row)
    result = base.summarize(placeholder_rows)
    executable = [row for row in rows if row["case_status"] == "EXECUTABLE"]
    available = [row for row in executable if row["behavioural_oracle_usd"] is not None]
    oracle_values = [float(row["behavioural_oracle_usd"]) for row in available]
    oracle_total = sum(oracle_values)
    oracle_stage = base.stage("BEHAVIOURAL_ORACLE_AVAILABLE_SUBSET", oracle_values, oracle_total)
    result["main_waterfall"][0] = oracle_stage
    for item in result["main_waterfall"][1:] + result["operational_upper_bound"]:
        item["retention_of_behavioural_oracle_pct"] = None
    result["incremental_loss_r"]["behavioural_oracle_to_observable_entry"] = None
    result["oracle_reference_coverage"] = {
        "status": "PARTIAL_REFERENCE_NOT_USED_BY_TEN_R_DECISION",
        "executable_cases": 248,
        "available_cases": 215,
        "unavailable_cases": 33,
        "coverage_fraction": base.rounded(215 / 248),
        "cross_denominator_retention_comparison": "NOT_COMPARABLE",
    }
    result["version"] = "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_RESULT_R1_1_0"
    result["amendment_a_applied"] = True
    return result


def render_report_r1(result: Mapping[str, Any], certification: Mapping[str, Any]) -> str:
    text = base.render_report(result, certification)
    insertion = (
        "## Amendment A: behavioural-oracle coverage\n\n"
        "The visual behavioural oracle exists for 215 of 248 executable cases. The 33 unavailable references were not imputed or filtered: all 248 cases remain in every observable, stop-feasible, execution, cost, overlap, and 10R decision stage. Oracle retention against those all-case stages is therefore reported as not comparable.\n\n"
    )
    return text.replace("## Matched-case waterfall\n", insertion + "## Matched-case waterfall\n")


def main() -> None:
    recovery_preflight()
    proof = base.synthetic_proof()
    seal_recovery(proof)
    base.write_json_exclusive(
        RECOVERY_OPENING,
        {
            "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_RECOVERY_OPENING_A_1_0",
            "status": "SECOND_AND_FINAL_CONTROLLED_OPENING_AFTER_RECOVERY_FREEZE",
            "opened_at_utc": base.utc_now(),
            "recovery_freeze": base.file_record(RECOVERY_FREEZE),
            "cumulative_source_opening_count": 2,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    frames, price_diagnostics = base.load_price()
    m1 = frames["M1"]
    primary_rows, primary_diagnostics = materialize_r1(base.PRIMARY_PLANS, base.PRIMARY_OOF, base.PRIMARY_CASES, m1, "primary")
    reference_rows, reference_diagnostics = materialize_r1(base.REFERENCE_PLANS, base.REFERENCE_OOF, base.REFERENCE_CASES, m1, "reference")
    compare_fields = (
        "population", "output_rows", "executable", "retained", "oracle_available", "oracle_unavailable",
        "retained_oracle_unavailable", "overlap_oracle_unavailable", "exit_counts", "complete_row_checksum",
    )
    differences = [name for name in compare_fields if primary_diagnostics[name] != reference_diagnostics[name]]
    case_bytes_identical = base.sha256_file(base.PRIMARY_CASES) == base.sha256_file(base.REFERENCE_CASES)
    if differences or not case_bytes_identical:
        raise RuntimeError({"status": "FAIL_RECOVERY_CASE_REPRODUCTION", "differences": differences, "byte_identical": case_bytes_identical})
    primary_result = summarize_r1(primary_rows)
    reference_result = summarize_r1(reference_rows)
    if base.canonical_json(primary_result) != base.canonical_json(reference_result):
        raise RuntimeError("FAIL_RECOVERY_RESULT_REPRODUCTION")
    base.write_json_exclusive(base.PRIMARY_RESULT, primary_result)
    base.write_json_exclusive(base.REFERENCE_RESULT, reference_result)
    result_bytes_identical = base.sha256_file(base.PRIMARY_RESULT) == base.sha256_file(base.REFERENCE_RESULT)
    if not result_bytes_identical:
        raise RuntimeError("FAIL_RECOVERY_RESULT_BYTE_REPRODUCTION")
    certification = {
        "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_CERTIFICATION_R1_1_0",
        "status": "PASS_INDEPENDENT_REPRODUCTION_UNDER_AMENDMENT_A",
        "certified_at_utc": base.utc_now(),
        "primary": primary_diagnostics,
        "reference": reference_diagnostics,
        "differences": differences,
        "case_payloads_byte_identical": case_bytes_identical,
        "results_byte_identical": result_bytes_identical,
        "price_diagnostics": price_diagnostics,
        "original_failure": base.file_record(FAILURE),
        "amendment_a": base.file_record(AMENDMENT),
        "recovery_freeze": base.file_record(RECOVERY_FREEZE),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    base.write_json_exclusive(base.CERTIFICATION, certification)
    final = {
        **primary_result,
        "completed_at_utc": base.utc_now(),
        "reproduction": base.file_record(base.CERTIFICATION),
        "primary_cases": base.file_record(base.PRIMARY_CASES),
        "reference_cases": base.file_record(base.REFERENCE_CASES),
        "primary_result": base.file_record(base.PRIMARY_RESULT),
        "reference_result": base.file_record(base.REFERENCE_RESULT),
    }
    base.write_json_exclusive(base.FINAL_RESULT, final)
    base.REPORT.write_text(render_report_r1(final, certification), encoding="utf-8", newline="\n")
    base.write_json_exclusive(
        base.FINAL_FREEZE,
        {
            "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_FINAL_FREEZE_R1_1_0",
            "status": "SEALED_FINAL_AUDIT_UNDER_AMENDMENT_A",
            "sealed_at_utc": base.utc_now(),
            "verdict": final["verdict"],
            "contract": base.file_record(base.CONTRACT),
            "protocol": base.file_record(base.PROTOCOL),
            "original_prepath_freeze": base.file_record(base.PREPATH_FREEZE),
            "original_failure": base.file_record(FAILURE),
            "amendment_a": base.file_record(AMENDMENT),
            "recovery_freeze": base.file_record(RECOVERY_FREEZE),
            "final_result": base.file_record(base.FINAL_RESULT),
            "certification": base.file_record(base.CERTIFICATION),
            "report": base.file_record(base.REPORT),
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    print(base.canonical_json({"status": final["verdict"], "feasibility": final["feasibility"], "recommendation": final["recommendation"], "result": base.file_record(base.FINAL_RESULT)}))
    del frames
    gc.collect()


if __name__ == "__main__":
    main()
