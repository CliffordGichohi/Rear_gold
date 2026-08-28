"""Run the single exposed matched-case regression for frozen V2 Amendment A."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    canonical_hash,
    simulate_track,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_human_policy_v2"
PREPATH = OUTPUT / "prepath_classification_amendment_a.json"
PREPATH_SEAL = OUTPUT / "prepath_classification_amendment_a_seal.json"
RESULT = OUTPUT / "matched_case_regression_v2.json"
TABLE = OUTPUT / "matched_case_regression_v2_cases.csv"
REPRODUCTION = OUTPUT / "independent_reproduction_v2.json"
FINAL_SEAL = OUTPUT / "final_seal_v2.json"
REPORT = ROOT / "GOLD_COHERENT_AUCTION_HUMAN_POLICY_V2_REGRESSION_REPORT.md"
COMPARISON = ROOT / "research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json"
V1_CONTROL = ROOT / "research_artifacts/gold_coherent_auction_management_v1/coherent_auction_management_result.json"
MODULE = ROOT / "backend/src/gold_intel/analytics/coherent_auction_human_policy_v2.py"
FREEZE = ROOT / "research_manifests/gold_coherent_auction_human_policy_v2_amendment_a_freeze.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    return value


def summarize(values: list[float]) -> dict[str, Any]:
    positives = [value for value in values if value > 1e-12]
    negatives = [value for value in values if value < -1e-12]
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    losses = -sum(negatives)
    return {
        "trades": len(values),
        "wins": len(positives),
        "losses": len(negatives),
        "breakeven": len(values) - len(positives) - len(negatives),
        "win_rate": len(positives) / len(values) if values else None,
        "net_r50": sum(values),
        "net_usd": 50.0 * sum(values),
        "expectancy_r50": sum(values) / len(values) if values else None,
        "profit_factor": sum(positives) / losses if losses else None,
        "maximum_drawdown_r50": drawdown,
    }


def forced_admission(classification: dict[str, Any]) -> dict[str, Any]:
    copy = json.loads(json.dumps(classification))
    copy["admitted"] = True
    copy["primary_disposition"] = "FORCED_FIXED_GEOMETRY_ATTRIBUTION_ONLY"
    copy["classification_hash"] = canonical_hash(
        {key: value for key, value in copy.items() if key != "classification_hash"}
    )
    return copy


def main() -> None:
    for path in (RESULT, TABLE, REPRODUCTION, FINAL_SEAL, REPORT):
        if path.exists():
            raise FileExistsError(f"V2 regression artifact already exists: {path}")
    prepath = json.loads(PREPATH.read_text(encoding="utf-8"))
    prepath_seal = json.loads(PREPATH_SEAL.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha256(PREPATH) != prepath_seal["result_sha256"]:
        raise RuntimeError("Amended prepath seal mismatch")
    if sha256(MODULE) != prepath_seal["module_sha256"]:
        raise RuntimeError("Implementation changed after amended prepath seal")
    if sha256(MODULE) != freeze["amended_implementation_sha256"]:
        raise RuntimeError("Implementation differs from Amendment A freeze")
    if prepath["semantic_fidelity"] != 16:
        raise RuntimeError("Semantic-fidelity gate did not pass")

    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    comparison_by_alias = {row["case_alias"]: row for row in comparison["cases"]}
    v1_control = json.loads(V1_CONTROL.read_text(encoding="utf-8"))
    opened_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    cases: list[dict[str, Any]] = []
    reproduction_rows: list[dict[str, Any]] = []

    for frozen in prepath["cases"]:
        alias = frozen["case_alias"]
        classification = frozen["classification"]
        primary_stream = load_gzip(ROOT / frozen["primary_source"])
        reference_stream = load_gzip(ROOT / frozen["reference_source"])
        track_names = (
            "FAITHFUL_FIXED_GEOMETRY",
            "PROTECTED_FIXED_GEOMETRY",
            "COMPLETE_V2_POLICY",
        )
        primary_tracks: dict[str, dict[str, Any]] = {}
        reference_tracks: dict[str, dict[str, Any]] = {}
        for track in track_names:
            primary_tracks[track] = simulate_track(
                classification=classification,
                stream=primary_stream,
                fill_at=frozen["fill_at"],
                track=track,
            )
            reference_tracks[track] = simulate_track(
                classification=classification,
                stream=reference_stream,
                fill_at=frozen["fill_at"],
                track=track,
            )
        sensitivity: dict[str, dict[str, Any]] = {}
        sensitivity_reference: dict[str, dict[str, Any]] = {}
        for threshold in (1.0, 1.5, 2.0):
            key = f"{threshold:.2f}R"
            sensitivity[key] = simulate_track(
                classification=classification,
                stream=primary_stream,
                fill_at=frozen["fill_at"],
                track="PROTECTED_FIXED_GEOMETRY",
                protection_threshold_r=threshold,
            )
            sensitivity_reference[key] = simulate_track(
                classification=classification,
                stream=reference_stream,
                fill_at=frozen["fill_at"],
                track="PROTECTED_FIXED_GEOMETRY",
                protection_threshold_r=threshold,
            )

        forced = forced_admission(classification)
        forced_primary = simulate_track(
            classification=forced,
            stream=primary_stream,
            fill_at=frozen["fill_at"],
            track="FAITHFUL_FIXED_GEOMETRY",
        )
        forced_reference = simulate_track(
            classification=forced,
            stream=reference_stream,
            fill_at=frozen["fill_at"],
            track="FAITHFUL_FIXED_GEOMETRY",
        )
        primary_bundle = {
            "tracks": primary_tracks,
            "sensitivity": sensitivity,
            "forced_all_case_fixed_geometry": forced_primary,
        }
        reference_bundle = {
            "tracks": reference_tracks,
            "sensitivity": sensitivity_reference,
            "forced_all_case_fixed_geometry": forced_reference,
        }
        primary_hash = canonical_hash(primary_bundle)
        reference_hash = canonical_hash(reference_bundle)
        if primary_hash != reference_hash:
            raise RuntimeError(f"Primary/reference V2 path mismatch for {alias}")

        human = comparison_by_alias[alias]["human"]
        terminal_correct = bool(human["path_diagnostic"]["terminal_direction_correct"])
        forced_positive = float(forced_primary["net_r50"]) > 0
        case = {
            "case_alias": alias,
            "submitted_at": frozen["submitted_at"],
            "terminal_direction_correct": terminal_correct,
            "original_recorded_r50": float(human["r50"]),
            "human_intent_detected": classification["human_intent"]["detected"],
            "admitted": classification["admitted"],
            "family": classification["family"],
            "primary_disposition": classification["primary_disposition"],
            "all_blockers": [row["code"] for row in classification["blockers"]],
            "warnings": classification["warnings"],
            "h4_signed_location": classification["h4"]["signed_range_location"],
            "h4_signed_displacement_atr": classification["h4"]["signed_fifteen_bar_change_atr"],
            "active_m15_structure": classification["m15_structure"]["available"],
            "event_locked": classification["event"]["locked"],
            "macro_state": classification["macro"]["state"],
            "fill": classification["fill"],
            "stop": classification["stop"],
            "target": classification["target"],
            "quantity_ounces": classification["quantity_ounces"],
            "planned_loss_per_ounce": classification["planned_loss_per_ounce"],
            "tracks": primary_tracks,
            "sensitivity": sensitivity,
            "forced_all_case_fixed_geometry": forced_primary,
            "directionally_correct_rejected": terminal_correct and not classification["admitted"],
            "directionally_wrong_admitted": (not terminal_correct) and classification["admitted"],
            "positive_fixed_geometry_rejected": forced_positive and not classification["admitted"],
            "primary_reference_bundle_sha256": primary_hash,
        }
        cases.append(case)
        reproduction_rows.append(
            {
                "case_alias": alias,
                "classification_sha256": classification["classification_hash"],
                "primary_bundle_sha256": primary_hash,
                "reference_bundle_sha256": reference_hash,
                "match": True,
            }
        )

    cases.sort(key=lambda row: row["submitted_at"])
    track_summaries: dict[str, dict[str, Any]] = {}
    for track in (
        "FAITHFUL_FIXED_GEOMETRY",
        "PROTECTED_FIXED_GEOMETRY",
        "COMPLETE_V2_POLICY",
    ):
        track_summaries[track] = summarize(
            [
                float(row["tracks"][track]["net_r50"])
                for row in cases
                if row["tracks"][track]["executed"]
            ]
        )
    all_case_fixed_summary = summarize(
        [float(row["forced_all_case_fixed_geometry"]["net_r50"]) for row in cases]
    )
    sensitivity_summaries = {
        threshold: summarize(
            [
                float(row["sensitivity"][threshold]["net_r50"])
                for row in cases
                if row["sensitivity"][threshold]["executed"]
            ]
        )
        for threshold in ("1.00R", "1.50R", "2.00R")
    }
    complete_stress = summarize(
        [
            float(row["tracks"]["COMPLETE_V2_POLICY"]["stressed_1_5x_cost_r50"])
            for row in cases
            if row["tracks"]["COMPLETE_V2_POLICY"]["executed"]
        ]
    )
    complete = track_summaries["COMPLETE_V2_POLICY"]
    fixed = track_summaries["FAITHFUL_FIXED_GEOMETRY"]
    protected = track_summaries["PROTECTED_FIXED_GEOMETRY"]
    attribution = {
        "all_16_strict_risk_fixed_geometry_r50": all_case_fixed_summary["net_r50"],
        "contextual_selection_increment_r50": fixed["net_r50"] - all_case_fixed_summary["net_r50"],
        "selected_fixed_geometry_r50": fixed["net_r50"],
        "protection_increment_r50": protected["net_r50"] - fixed["net_r50"],
        "selected_protected_geometry_r50": protected["net_r50"],
        "runner_increment_r50": complete["net_r50"] - protected["net_r50"],
        "complete_policy_r50": complete["net_r50"],
    }
    directionally_correct_rejected = [
        row["case_alias"] for row in cases if row["directionally_correct_rejected"]
    ]
    wrong_admitted = [row["case_alias"] for row in cases if row["directionally_wrong_admitted"]]
    positive_rejected = [
        row["case_alias"] for row in cases if row["positive_fixed_geometry_rejected"]
    ]
    selection_confusion = {
        "directionally_correct_admitted": sum(
            row["terminal_direction_correct"] and row["admitted"] for row in cases
        ),
        "directionally_correct_rejected": len(directionally_correct_rejected),
        "directionally_wrong_admitted": len(wrong_admitted),
        "directionally_wrong_rejected": sum(
            (not row["terminal_direction_correct"]) and (not row["admitted"])
            for row in cases
        ),
        "warning": "POST_HOC_EXPOSED_CALIBRATION_NOT_OUT_OF_SAMPLE_CLASSIFICATION_ACCURACY",
    }
    v1_summary = v1_control["summaries"]["h1_fixed_control"]
    verdict = (
        "PROMISING_EXPOSED_CALIBRATION_NOT_VALIDATED"
        if complete["net_r50"] > 0 and complete_stress["net_r50"] > 0
        else "REJECT_EXPOSED_ECONOMICS"
    )
    payload: dict[str, Any] = rounded(
        {
            "version": "GOLD_COHERENT_AUCTION_HUMAN_POLICY_V2_REGRESSION_1_0",
            "status": "COMPLETE_EXPOSED_MATCHED_CASE_REGRESSION",
            "verdict": verdict,
            "evidence_status": "POST_HOC_EXPOSED_CALIBRATION_ZERO_VALIDATION_CREDIT",
            "v2_path_opened_at_utc": opened_at,
            "v2_path_simulation_count": 1,
            "prepath_result_sha256": sha256(PREPATH),
            "module_sha256": sha256(MODULE),
            "population": len(cases),
            "semantic_fidelity": prepath["semantic_fidelity"],
            "admitted": sum(row["admitted"] for row in cases),
            "rejected": sum(not row["admitted"] for row in cases),
            "selection_confusion": selection_confusion,
            "directionally_correct_rejected": directionally_correct_rejected,
            "directionally_wrong_admitted": wrong_admitted,
            "positive_fixed_geometry_rejected": positive_rejected,
            "all_case_fixed_geometry_summary": all_case_fixed_summary,
            "track_summaries": track_summaries,
            "complete_policy_1_5x_cost_summary": complete_stress,
            "protection_threshold_sensitivity": sensitivity_summaries,
            "value_attribution": attribution,
            "preserved_v1_generic_m15_stop_control": v1_summary,
            "cases": cases,
            "fresh_50_case_block": "LOCKED_UNOPENED",
            "calendar_2025": "LOCKED_UNOPENED",
            "calendar_2026": "LOCKED_UNOPENED",
            "paid_acquisition": "NONE",
        }
    )
    payload["payload_sha256"] = canonical_hash(payload)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fields = [
        "case_alias",
        "terminal_direction_correct",
        "admitted",
        "family",
        "primary_disposition",
        "all_blockers",
        "warnings",
        "h4_signed_location",
        "h4_signed_displacement_atr",
        "active_m15_structure",
        "event_locked",
        "macro_state",
        "fill",
        "stop",
        "target",
        "quantity_ounces",
        "forced_all_case_fixed_r50",
        "selected_fixed_r50",
        "protected_r50",
        "complete_v2_r50",
        "complete_resolution",
        "protection_at",
        "runner_activated",
        "directionally_correct_rejected",
        "directionally_wrong_admitted",
        "positive_fixed_geometry_rejected",
    ]
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in cases:
            complete_case = row["tracks"]["COMPLETE_V2_POLICY"]
            writer.writerow(
                {
                    **{key: row.get(key) for key in fields},
                    "all_blockers": "|".join(row["all_blockers"]),
                    "warnings": "|".join(row["warnings"]),
                    "forced_all_case_fixed_r50": row["forced_all_case_fixed_geometry"]["net_r50"],
                    "selected_fixed_r50": row["tracks"]["FAITHFUL_FIXED_GEOMETRY"]["net_r50"],
                    "protected_r50": row["tracks"]["PROTECTED_FIXED_GEOMETRY"]["net_r50"],
                    "complete_v2_r50": complete_case["net_r50"],
                    "complete_resolution": complete_case["resolution"],
                    "protection_at": complete_case.get("protection_at"),
                    "runner_activated": complete_case.get("runner_activated"),
                }
            )

    reproduction = {
        "status": "PASS_PRIMARY_REFERENCE_EXACT_REPRODUCTION",
        "population": len(cases),
        "matches": len(reproduction_rows),
        "mismatches": 0,
        "rows": reproduction_rows,
        "aggregate_bundle_sha256": canonical_hash(
            [row["primary_reference_bundle_sha256"] for row in cases]
        ),
    }
    REPRODUCTION.write_text(
        json.dumps(reproduction, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Gold Coherent-Auction Human-Policy Reconstruction V2 Regression",
        "",
        f"Verdict: `{verdict}`",
        "",
        "## What was corrected",
        "",
        "V2 preserves the operator's sealed structural stop and liquidity target, resizes at the actual fill, treats macro and an engaged decision zone as context rather than universal vetoes, and applies only the five frozen conjunctive risk states. The result remains exposed calibration with zero validation credit.",
        "",
        "## Economic result",
        "",
        "| Track | Trades | Win rate | Net R | Net USD | PF | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, summary in (
        ("All 16: faithful geometry, no selection", all_case_fixed_summary),
        ("Selected: faithful fixed geometry", fixed),
        ("Selected: + completed-M15 1.25R protection", protected),
        ("Complete V2: + bounded accepted runner", complete),
        ("Complete V2 at 1.5x costs", complete_stress),
    ):
        win = "N/A" if summary["win_rate"] is None else f"{100 * summary['win_rate']:.2f}%"
        pf = "N/A" if summary["profit_factor"] is None else f"{summary['profit_factor']:.4f}"
        lines.append(
            f"| {label} | {summary['trades']} | {win} | {summary['net_r50']:+.4f} | "
            f"${summary['net_usd']:+.2f} | {pf} | {summary['maximum_drawdown_r50']:.4f}R |"
        )
    lines += [
        "",
        "## Value-retention attribution",
        "",
        f"- Strict-risk fixed geometry across all 16: `{attribution['all_16_strict_risk_fixed_geometry_r50']:+.4f}R`.",
        f"- Contextual selection contribution: `{attribution['contextual_selection_increment_r50']:+.4f}R`.",
        f"- Completed-M15 protection contribution: `{attribution['protection_increment_r50']:+.4f}R`.",
        f"- Bounded runner contribution: `{attribution['runner_increment_r50']:+.4f}R`.",
        f"- Complete exposed V2 calibration: `{attribution['complete_policy_r50']:+.4f}R`.",
        "",
        "## Selection audit",
        "",
        f"The policy admitted {payload['admitted']} and rejected {payload['rejected']} cases. It rejected {len(directionally_correct_rejected)} directionally correct cases and admitted {len(wrong_admitted)} directionally wrong cases. That separation is descriptive only: these contextual thresholds were constructed from the same exposed cases, so it is a calibration result, not predictive accuracy.",
        "",
        "## Every trade",
        "",
        "| Case | Right later | Decision | Family | Reason/warning | Fixed R | Protected R | Complete R | Final resolution |",
        "|---|:---:|---|---|---|---:|---:|---:|---|",
    ]
    for row in cases:
        complete_case = row["tracks"]["COMPLETE_V2_POLICY"]
        reason = row["primary_disposition"] if not row["admitted"] else (", ".join(row["warnings"]) or "NONE")
        lines.append(
            f"| `{row['case_alias']}` | {'YES' if row['terminal_direction_correct'] else 'NO'} | "
            f"{'ADMIT' if row['admitted'] else 'REJECT'} | {row['family']} | `{reason}` | "
            f"{row['tracks']['FAITHFUL_FIXED_GEOMETRY']['net_r50']:+.4f} | "
            f"{row['tracks']['PROTECTED_FIXED_GEOMETRY']['net_r50']:+.4f} | "
            f"{complete_case['net_r50']:+.4f} | {complete_case['resolution']} |"
        )
    lines += [
        "",
        "## Protection sensitivity (mandatory, not hidden)",
        "",
        "| Completed-M15 close threshold | Net R | PF | Max DD |",
        "|---|---:|---:|---:|",
    ]
    for threshold, summary in sensitivity_summaries.items():
        pf = "N/A" if summary["profit_factor"] is None else f"{summary['profit_factor']:.4f}"
        lines.append(
            f"| {threshold} | {summary['net_r50']:+.4f} | {pf} | {summary['maximum_drawdown_r50']:.4f}R |"
        )
    lines += [
        "",
        "## Honest interpretation",
        "",
        "This V2 regression answers the narrow correction question: a faithful translation can monetize substantially more of the already-observed sample than the V1 zero-trade rulebook. It does not establish a durable edge because selection and the 1.25R protection threshold were calibrated on these same exposed trades. The complete policy is now frozen; changing it again before fresh evaluation would invalidate the next test.",
        "",
        "The unopened 50-case block, 2025 and 2026 remain locked. No paid data was acquired.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    final_seal = {
        "status": "COMPLETE_AND_SEALED_EXPOSED_V2_REGRESSION",
        "verdict": verdict,
        "result_sha256": sha256(RESULT),
        "table_sha256": sha256(TABLE),
        "reproduction_sha256": sha256(REPRODUCTION),
        "report_sha256": sha256(REPORT),
        "payload_sha256": payload["payload_sha256"],
        "module_sha256": payload["module_sha256"],
        "complete_policy_net_r50": complete["net_r50"],
        "fresh_50_case_block": "LOCKED_UNOPENED",
        "calendar_2025": "LOCKED_UNOPENED",
        "calendar_2026": "LOCKED_UNOPENED",
    }
    FINAL_SEAL.write_text(
        json.dumps(final_seal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": final_seal["status"],
                "verdict": verdict,
                "admitted": payload["admitted"],
                "rejected": payload["rejected"],
                "fixed_r50": fixed["net_r50"],
                "protected_r50": protected["net_r50"],
                "complete_r50": complete["net_r50"],
                "stressed_r50": complete_stress["net_r50"],
                "seal": final_seal["result_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
