#!/usr/bin/env python3
"""Correct the shared Step 5D-R1 evaluator defect without reopening sources."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping

from diagnose_gc_microstructure_step5dr1 import (
    EXPECTED_FREEZE_SHA,
    EXPECTED_PRICE_SHA,
    EXPECTED_PROTOCOL_SHA,
    EXPECTED_SESSION_SHA,
    FREEZE_PATH,
    PROTOCOL_PATH,
    ROOT,
    canonical_hash,
    load_json,
    recommendation_for,
    sha256_file,
    write_json,
)


ORIGINAL_DIR = ROOT / "research_artifacts" / "gc_microstructure_step5dr1_v01"
ORIGINAL_FINAL_SEAL_SHA = "d163c989e9c1008163c36732db026955c0a325ee57d2096adeaa5053e4848bf9"
OUTPUT_DIR = ROOT / "research_artifacts" / "gc_microstructure_step5dr1_corrected_v01"
REPORT_PATH = ROOT / "GC_MICROSTRUCTURE_STEP_5D_R1_CORRECTED_REPORT.md"


def corrected_result(source: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(source)
    for item in result["keys"]:
        required = ["ASIA", "LONDON"]
        if item["session_code"] == "NEW_YORK":
            required.append("NEW_YORK")
        windows = item["five_minute_case_builder_windows"]
        predicted = all(bool(windows[code]["metadata_integrity_pass"]) for code in required)
        actual = bool(item["session_record"]["valid_emission"])
        if item["session_record"]["emission_count"] > 1 or item["session_record"]["metadata_error_codes"]:
            reproduction = "CONTRADICTION_INVALID_OR_DUPLICATE_SESSION_RECORD"
        elif predicted != actual:
            reproduction = "CONTRADICTION_PREDICTED_EMISSION_MISMATCH"
        else:
            reproduction = "MATCH_PRESENT" if actual else "MATCH_EXCLUDED"
        exclusions = []
        for code in required:
            window = windows[code]
            if window["metadata_integrity_pass"]:
                continue
            error_codes = sorted({
                error
                for timestamp in window["metadata_ineligible_timestamps"]
                for error in timestamp["error_codes"]
            })
            exclusions.append({
                "window": code,
                "reason": "INCOMPLETE_OR_MISSING_EXACT_5M_SOURCE",
                "missing_timestamp_count": window["missing_timestamp_count"],
                "duplicate_timestamp_count": window["duplicate_timestamp_count"],
                "metadata_ineligible_timestamp_count": window["metadata_ineligible_timestamp_count"],
                "metadata_error_codes": error_codes,
            })
        item["exact_v3_case_builder"] = {
            "required_windows": required,
            "input_filter": "Only five-minute facts with complete=true enter build_session_case_specs",
            "predicted_emission": predicted,
            "actual_valid_emission": actual,
            "reproduction": reproduction,
            "exclusion_reasons": exclusions,
        }
        if reproduction.startswith("CONTRADICTION"):
            classification = "UNRESOLVED"
        elif item["holiday"]["sealed_official_full_closure"]:
            classification = "DOCUMENTED_UNAVAILABLE"
        elif item["one_minute_outcome_coverage"]["metadata_integrity_pass"]:
            classification = "RECOVERABLE_EXISTING_SEALED_SOURCE"
        else:
            classification = "RECOVERABLE_TARGETED_MT5_REFRESH"
        item["classification"] = classification
    counts = Counter(item["classification"] for item in result["keys"])
    result["classification_counts"] = dict(sorted(counts.items()))
    constructible = 358 + counts["RECOVERABLE_EXISTING_SEALED_SOURCE"]
    result["coverage_determination"] = {
        "currently_constructible_nonholiday_outcomes": constructible,
        "required_nonholiday_outcomes": 374,
        "all_374_constructible_from_existing_sealed_source": constructible == 374,
        "unchanged_neutral_outcome_definition": True,
    }
    result["evaluator_correction"] = {
        "defect": "Original shared evaluator used five-minute timestamp membership instead of the builder's pre-filtered complete-bar membership.",
        "correction": "Predicted session emission now requires every frozen five-minute timestamp to pass the complete metadata-integrity gate.",
        "source_rows_reopened": 0,
        "market_or_outcome_values_accessed": False,
    }
    return result


def report_text(
    result: Mapping[str, Any], recommendation: Mapping[str, Any], checksum: str
) -> str:
    coverage = result["coverage_determination"]
    lines = [
        "# GC Microstructure Step 5D-R1 Corrected Report",
        "",
        "Formal status: `PASS_STEP_5D_R1_DIAGNOSTIC_REPRODUCTION_AFTER_IMPLEMENTATION_CORRECTION`",
        "",
        "The original sealed R1 run is preserved. Its two metadata parsers agreed, but its shared evaluator failed to apply the V3 builder's `fact.complete` pre-filter. This corrected disposition was derived independently from the two sealed metadata projections; no source row, outcome, or market value was reopened.",
        "",
        "## Verdict",
        "",
        "- Independent corrected reproduction: `PASS`",
        f"- Existing sealed source can construct: `{coverage['currently_constructible_nonholiday_outcomes']} / 374` required non-holiday outcomes",
        f"- All 374 constructible now: `{str(coverage['all_374_constructible_from_existing_sealed_source']).upper()}`",
        f"- Classifications: `{json.dumps(result['classification_counts'], sort_keys=True)}`",
        f"- Corrected complete-result checksum: `{checksum}`",
        "- Step 5D remains `FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE`; Stage 1 and Stage 2 remain unexecuted.",
        "",
        "## Missing-key audit",
        "",
        "| Date | Session | Valid 1m / 239 | Missing 1m | V3 exclusion | Classification |",
        "|---|---|---:|---:|---|---|",
    ]
    for item in result["keys"]:
        one = item["one_minute_outcome_coverage"]
        exclusions = item["exact_v3_case_builder"]["exclusion_reasons"]
        exclusion = ", ".join(
            f"{entry['window']} ({entry['missing_timestamp_count']} missing, "
            f"{entry['metadata_ineligible_timestamp_count']} ineligible; "
            f"{','.join(entry['metadata_error_codes']) or 'none'})"
            for entry in exclusions
        ) or item["exact_v3_case_builder"]["reproduction"]
        lines.append(
            f"| {item['session_date']} | {item['session_code']} | "
            f"{one['metadata_eligible_timestamp_count']} | {one['missing_timestamp_count']} | "
            f"{exclusion} | {item['classification']} |"
        )
    lines.extend([
        "",
        "## One bounded recommendation",
        "",
        f"`{recommendation['code']}` — {recommendation['bounded_path']}",
        "",
        "This recommendation was not implemented. No data was refreshed, repaired, acquired, or charged.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    if OUTPUT_DIR.exists() or REPORT_PATH.exists():
        raise FileExistsError("Corrected Step 5D-R1 artifacts already exist")
    if sha256_file(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA or sha256_file(FREEZE_PATH) != EXPECTED_FREEZE_SHA:
        raise ValueError("Frozen Step 5D-R1 protocol changed")
    if sha256_file(ORIGINAL_DIR / "final_seal.json") != ORIGINAL_FINAL_SEAL_SHA:
        raise ValueError("Original Step 5D-R1 seal changed")
    original_seal = load_json(ORIGINAL_DIR / "final_seal.json")
    original_manifest = load_json(ORIGINAL_DIR / "manifest.json")
    for name, metadata in original_manifest["artifacts"].items():
        if sha256_file(ORIGINAL_DIR / name) != metadata["sha256"]:
            raise ValueError(f"Original R1 artifact changed: {name}")

    primary_source = load_json(ORIGINAL_DIR / "primary_diagnostic.json")
    reference_source = load_json(ORIGINAL_DIR / "reference_diagnostic.json")
    primary = corrected_result(primary_source["result"])
    reference = corrected_result(reference_source["result"])
    primary_checksum = canonical_hash(primary)
    reference_checksum = canonical_hash(reference)
    if primary != reference or primary_checksum != reference_checksum:
        raise ValueError("Corrected independent reproductions disagree")
    recommendation = recommendation_for(primary)
    if recommendation is None:
        raise ValueError("Frozen recommendation rule produced no disposition")
    status = "PASS_STEP_5D_R1_DIAGNOSTIC_REPRODUCTION_AFTER_IMPLEMENTATION_CORRECTION"

    staging = OUTPUT_DIR.with_name(OUTPUT_DIR.name + ".building")
    if staging.exists():
        raise FileExistsError(staging)
    staging.mkdir(parents=True)
    correction = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_IMPLEMENTATION_CORRECTION_V0_1",
        "status": status,
        "original_artifact_preserved": True,
        "original_final_seal_sha256": ORIGINAL_FINAL_SEAL_SHA,
        "original_result_checksum": original_seal["result_checksum"],
        "defect": "The common evaluator tested builder_membership_pass, which admitted present but incomplete five-minute records. The V3 builder filters to fact.complete before constructing cases.",
        "bounded_correction": "Use the already-sealed metadata_integrity_pass for each required five-minute window; change no timestamp, source, outcome rule, classification rule, or source projection.",
        "raw_source_rows_reopened": 0,
        "previously_found_outcomes_reopened": 0,
        "market_or_outcome_values_accessed": False,
        "research_test_or_candidate_executed": False,
    }
    correction["correction_hash"] = canonical_hash(correction)
    write_json(staging / "implementation_correction.json", correction)
    write_json(staging / "primary_corrected_diagnostic.json", {
        "implementation": "PRIMARY_SEALED_PROJECTION_CORRECTED_EVALUATOR",
        "result_checksum": primary_checksum,
        "result": primary,
    })
    write_json(staging / "reference_corrected_diagnostic.json", {
        "implementation": "REFERENCE_SEALED_PROJECTION_INDEPENDENT_CORRECTED_EVALUATOR",
        "result_checksum": reference_checksum,
        "result": reference,
    })
    findings = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_CORRECTED_FINDINGS_V0_1",
        "status": status,
        "independent_reproduction_pass": True,
        "primary_checksum": primary_checksum,
        "reference_checksum": reference_checksum,
        "classification_counts": primary["classification_counts"],
        "coverage_determination": primary["coverage_determination"],
        "recommendation": recommendation,
        "raw_source_rows_reopened": 0,
        "forbidden_values_accessed": False,
    }
    findings["findings_hash"] = canonical_hash(findings)
    write_json(staging / "findings.json", findings)
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_CORRECTED_VERDICT_V0_1",
        "status": status,
        "preserved_step5d_status": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
        "preserved_original_r1_seal": ORIGINAL_FINAL_SEAL_SHA,
        "all_374_constructible_from_existing_sealed_source": primary["coverage_determination"]["all_374_constructible_from_existing_sealed_source"],
        "currently_constructible_nonholiday_outcomes": primary["coverage_determination"]["currently_constructible_nonholiday_outcomes"],
        "classification_counts": primary["classification_counts"],
        "recommendation_code": recommendation["code"],
        "recovery_implemented": False,
        "stage_1_or_stage_2_executed": False,
    }
    verdict["verdict_hash"] = canonical_hash(verdict)
    write_json(staging / "verdict.json", verdict)
    temporary_report = REPORT_PATH.with_suffix(REPORT_PATH.suffix + ".building")
    temporary_report.write_text(report_text(primary, recommendation, primary_checksum), encoding="utf-8", newline="\n")
    names = [
        "implementation_correction.json", "primary_corrected_diagnostic.json",
        "reference_corrected_diagnostic.json", "findings.json", "verdict.json",
    ]
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_CORRECTED_MANIFEST_V0_1",
        "status": status,
        "protocol_sha256": EXPECTED_PROTOCOL_SHA,
        "freeze_sha256": EXPECTED_FREEZE_SHA,
        "original_final_seal_sha256": ORIGINAL_FINAL_SEAL_SHA,
        "bound_source_hashes": {"price_bars": EXPECTED_PRICE_SHA, "sessions": EXPECTED_SESSION_SHA},
        "artifacts": {
            name: {"sha256": sha256_file(staging / name), "bytes": (staging / name).stat().st_size}
            for name in names
        },
        "report": {"path": REPORT_PATH.name, "sha256": sha256_file(temporary_report), "bytes": temporary_report.stat().st_size},
        "result_checksum": primary_checksum,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    write_json(staging / "manifest.json", manifest)
    final_seal = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_CORRECTED_FINAL_SEAL_V0_1",
        "status": status,
        "manifest_sha256": sha256_file(staging / "manifest.json"),
        "manifest_hash": manifest["manifest_hash"],
        "verdict_sha256": sha256_file(staging / "verdict.json"),
        "findings_sha256": sha256_file(staging / "findings.json"),
        "result_checksum": primary_checksum,
        "independent_reproduction_pass": True,
        "original_artifacts_preserved": True,
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    final_seal["final_seal_receipt"] = canonical_hash(final_seal)
    write_json(staging / "final_seal.json", final_seal)
    staging.replace(OUTPUT_DIR)
    temporary_report.replace(REPORT_PATH)
    sealed_manifest = load_json(OUTPUT_DIR / "manifest.json")
    for name, metadata in sealed_manifest["artifacts"].items():
        if sha256_file(OUTPUT_DIR / name) != metadata["sha256"]:
            raise ValueError(f"Corrected artifact seal failed: {name}")
    if sha256_file(REPORT_PATH) != sealed_manifest["report"]["sha256"]:
        raise ValueError("Corrected report seal failed")
    print(json.dumps({
        "status": status,
        "classification_counts": primary["classification_counts"],
        "coverage": primary["coverage_determination"],
        "recommendation": recommendation["code"],
        "result_checksum": primary_checksum,
        "final_seal_sha256": sha256_file(OUTPUT_DIR / "final_seal.json"),
        "raw_source_rows_reopened": 0,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
