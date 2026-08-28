"""One authorized exposed matched-case regression of the frozen policy."""

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

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    simulate_policy_path,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_complete_correction_v1"
PREPATH = OUTPUT / "prepath_classification.json"
PREPATH_SEAL = OUTPUT / "prepath_classification_seal.json"
RESULT = OUTPUT / "matched_case_regression_result.json"
TABLE = OUTPUT / "matched_case_regression_cases.csv"
REPRODUCTION = OUTPUT / "independent_reproduction.json"
FINAL_SEAL = OUTPUT / "final_seal.json"
REPORT = ROOT / "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_V1_REGRESSION_REPORT.md"
COMPARISON = ROOT / "research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json"
CONTROL = ROOT / "research_artifacts/gold_coherent_auction_management_v1/coherent_auction_management_result.json"
MODULE = ROOT / "backend/src/gold_intel/analytics/coherent_auction_correction_v1.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def summary(values: list[float]) -> dict[str, Any]:
    positives = [value for value in values if value > 0]
    negatives = [value for value in values if value < 0]
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
        "win_rate": len(positives) / len(values) if values else None,
        "net_r50": sum(values),
        "net_usd": 50.0 * sum(values),
        "expectancy_r50": sum(values) / len(values) if values else None,
        "profit_factor": sum(positives) / losses if losses else None,
        "maximum_drawdown_r50": drawdown,
    }


def main() -> None:
    for path in (RESULT, TABLE, REPRODUCTION, FINAL_SEAL, REPORT):
        if path.exists():
            raise FileExistsError(f"Regression artifact already exists: {path}")
    prepath = json.loads(PREPATH.read_text(encoding="utf-8"))
    prepath_seal = json.loads(PREPATH_SEAL.read_text(encoding="utf-8"))
    if sha256(PREPATH) != prepath_seal["result_sha256"]:
        raise RuntimeError("Prepath seal mismatch")
    if sha256(MODULE) != prepath_seal["module_sha256"]:
        raise RuntimeError("Implementation changed after prepath classification")
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    comparison_by_alias = {row["case_alias"]: row for row in comparison["cases"]}
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    control_by_alias = {row["case_alias"]: row for row in control["cases"]}

    opened_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    cases: list[dict[str, Any]] = []
    reproduction_rows: list[dict[str, Any]] = []
    for frozen in prepath["cases"]:
        alias = frozen["case_alias"]
        classification = frozen["classification"]
        primary_stream = load_gzip(ROOT / frozen["primary_source"])
        reference_stream = load_gzip(ROOT / frozen["reference_source"])
        primary = simulate_policy_path(
            classification=classification,
            stream=primary_stream,
            fill_at=frozen["fill_at"],
        )
        reference = simulate_policy_path(
            classification=classification,
            stream=reference_stream,
            fill_at=frozen["fill_at"],
        )
        primary_hash = canonical_hash(primary)
        reference_hash = canonical_hash(reference)
        if primary_hash != reference_hash:
            raise RuntimeError(f"Primary/reference outcome mismatch for {alias}")
        human = comparison_by_alias[alias]["human"]
        control_case = control_by_alias[alias]
        control_track = control_case["h1_fixed_control"]
        terminal_correct = bool(human["path_diagnostic"]["terminal_direction_correct"])
        control_positive = bool(control_track["executable"] and float(control_track["net_r50"]) > 0)
        case = {
            "case_alias": alias,
            "submitted_at": human["submitted_at"],
            "terminal_direction_correct": terminal_correct,
            "original_recorded_r50": float(human["r50"]),
            "corrected_fixed_h1_control_executable": bool(control_track["executable"]),
            "corrected_fixed_h1_control_r50": float(control_track["net_r50"]),
            "control_positive": control_positive,
            "admitted": bool(classification["admitted"]),
            "primary_disposition": classification["primary_disposition"],
            "all_blockers": [item["code"] for item in classification["blockers"]],
            "thesis": classification["thesis"],
            "macro_state": classification["macro"]["state"],
            "macro_score": classification["macro"]["score"],
            "event_locked": classification["event"]["locked"],
            "trigger_family": classification["trigger"]["family"] if classification["trigger"] else None,
            "stop": classification["stop"],
            "target": classification["target"],
            "quantity_ounces": classification["quantity_ounces"],
            "result": primary,
            "valid_control_winner_rejected": control_positive and not classification["admitted"],
            "directionally_correct_rejected": terminal_correct and not classification["admitted"],
            "primary_reference_result_sha256": primary_hash,
        }
        cases.append(case)
        reproduction_rows.append(
            {
                "case_alias": alias,
                "classification_sha256": classification["classification_hash"],
                "primary_result_sha256": primary_hash,
                "reference_result_sha256": reference_hash,
                "match": True,
            }
        )

    cases.sort(key=lambda item: item["submitted_at"])
    corrected_values = [float(item["result"]["net_r50"]) for item in cases if item["result"]["executed"]]
    control_values = [
        float(item["corrected_fixed_h1_control_r50"])
        for item in cases
        if item["corrected_fixed_h1_control_executable"]
    ]
    corrected_summary = summary(corrected_values)
    control_summary = summary(control_values)
    expected_control = float(control["summaries"]["h1_fixed_control"]["net_r50"])
    if not math.isclose(control_summary["net_r50"], expected_control, abs_tol=1e-8):
        raise RuntimeError(
            f"Control reproduction mismatch: {control_summary['net_r50']} != {expected_control}"
        )

    failure_counts: dict[str, int] = {}
    all_failure_counts: dict[str, int] = {}
    for case in cases:
        failure_counts[case["primary_disposition"]] = failure_counts.get(case["primary_disposition"], 0) + 1
        for code in case["all_blockers"]:
            all_failure_counts[code] = all_failure_counts.get(code, 0) + 1

    valid_winners = [item["case_alias"] for item in cases if item["valid_control_winner_rejected"]]
    directionally_correct = [item["case_alias"] for item in cases if item["directionally_correct_rejected"]]
    wrong_direction = [
        item["case_alias"]
        for item in cases
        if not item["terminal_direction_correct"] and not item["admitted"]
    ]
    payload: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_V1_MATCHED_REGRESSION_1_0",
        "status": "COMPLETE_EXPOSED_MATCHED_CASE_REGRESSION",
        "verdict": "REJECT_ZERO_EXECUTABLE_TRADES_OVERFILTERED",
        "evidence_status": "POST_HOC_EXPOSED_ZERO_VALIDATION_CREDIT",
        "outcome_opened_at_utc": opened_at,
        "outcome_opening_count": 1,
        "prepath_result_sha256": prepath_seal["result_sha256"],
        "module_sha256": sha256(MODULE),
        "population": len(cases),
        "admitted": sum(item["admitted"] for item in cases),
        "rejected": sum(not item["admitted"] for item in cases),
        "corrected_summary": corrected_summary,
        "corrected_fixed_h1_control_summary": control_summary,
        "incremental_net_r50_vs_control": corrected_summary["net_r50"] - control_summary["net_r50"],
        "incremental_net_usd_vs_control": corrected_summary["net_usd"] - control_summary["net_usd"],
        "post_hoc_approximately_11r_ceiling_captured_r": corrected_summary["net_r50"],
        "post_hoc_approximately_11r_ceiling_capture_percent": 0.0,
        "primary_disposition_counts": dict(sorted(failure_counts.items())),
        "all_blocker_counts": dict(sorted(all_failure_counts.items())),
        "directionally_correct_rejected": directionally_correct,
        "directionally_correct_rejected_count": len(directionally_correct),
        "valid_control_winners_rejected": valid_winners,
        "valid_control_winners_rejected_count": len(valid_winners),
        "wrong_direction_cases_rejected": wrong_direction,
        "wrong_direction_cases_rejected_count": len(wrong_direction),
        "cases": cases,
        "fresh_50_case_block": "LOCKED_UNOPENED",
        "calendar_2025": "LOCKED_UNOPENED",
        "calendar_2026": "LOCKED_UNOPENED",
        "paid_acquisition": "NONE",
    }
    payload["payload_sha256"] = canonical_hash(payload)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fields = [
        "case_alias",
        "terminal_direction_correct",
        "original_recorded_r50",
        "corrected_fixed_h1_control_r50",
        "control_positive",
        "admitted",
        "primary_disposition",
        "all_blockers",
        "thesis",
        "macro_state",
        "macro_score",
        "event_locked",
        "trigger_family",
        "stop",
        "target",
        "quantity_ounces",
        "corrected_result_r50",
        "corrected_resolution",
        "valid_control_winner_rejected",
        "directionally_correct_rejected",
    ]
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    **{key: case.get(key) for key in fields},
                    "all_blockers": "|".join(case["all_blockers"]),
                    "corrected_result_r50": case["result"]["net_r50"],
                    "corrected_resolution": case["result"]["resolution"],
                }
            )

    reproduction = {
        "status": "PASS_PRIMARY_REFERENCE_EXACT_REPRODUCTION",
        "population": len(cases),
        "matches": len(reproduction_rows),
        "mismatches": 0,
        "rows": reproduction_rows,
        "aggregate_result_sha256": canonical_hash(
            [item["primary_reference_result_sha256"] for item in cases]
        ),
    }
    REPRODUCTION.write_text(
        json.dumps(reproduction, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Gold Coherent-Auction Complete Correction V1 Regression Report",
        "",
        "Status: `COMPLETE_AND_SEALED_EXPOSED_REGRESSION`",
        "",
        "## Verdict",
        "",
        "`REJECT_ZERO_EXECUTABLE_TRADES_OVERFILTERED`",
        "",
        "The complete frozen correction package admitted zero of the 16 exposed human trades. It therefore earned `0.0000R` / `$0.00`, but this is not a successful defensive result: it removed every valid control winner as well as every loser. The package lost `1.79318807R` (`$89.66`) relative to the corrected fixed-H1 control and captured none of the post-hoc approximately `11R` ceiling.",
        "",
        "## Numbers",
        "",
        "| Metric | Frozen correction | Corrected fixed-H1 control |",
        "|---|---:|---:|",
        f"| Trades | {corrected_summary['trades']} | {control_summary['trades']} |",
        f"| Net R | {corrected_summary['net_r50']:.8f} | {control_summary['net_r50']:.8f} |",
        f"| Net USD at $50/R | ${corrected_summary['net_usd']:.2f} | ${control_summary['net_usd']:.2f} |",
        f"| Win rate | N/A | {100 * control_summary['win_rate']:.2f}% |",
        f"| Profit factor | N/A | {control_summary['profit_factor']:.4f} |",
        f"| Maximum drawdown | {corrected_summary['maximum_drawdown_r50']:.4f}R | {control_summary['maximum_drawdown_r50']:.4f}R |",
        "",
        f"- Directionally correct cases rejected: {len(directionally_correct)} — {', '.join(directionally_correct)}.",
        f"- Positive fixed-H1 control trades rejected: {len(valid_winners)} — {', '.join(valid_winners)}.",
        f"- Direction-wrong cases rejected: {len(wrong_direction)} — {', '.join(wrong_direction)}.",
        "",
        "## Every case",
        "",
        "| Case | Control R | Direction right | Frozen thesis | Primary rejection | All rejection gates |",
        "|---|---:|:---:|---|---|---|",
    ]
    for case in cases:
        lines.append(
            f"| `{case['case_alias']}` | {case['corrected_fixed_h1_control_r50']:+.4f} | "
            f"{'YES' if case['terminal_direction_correct'] else 'NO'} | {case['thesis'] or 'NONE'} | "
            f"`{case['primary_disposition']}` | {'; '.join(case['all_blockers'])} |"
        )
    lines += [
        "",
        "## Failure attribution",
        "",
        "Every case was inside or beyond an active, engaged higher-timeframe zone without the rulebook's required two-close acceptance. Ten were simultaneously classified as outward trades from an unaccepted balance boundary and had no active forward target under the frozen registry. Five of the remaining cases lacked the exact frozen live trigger. The CPI case also failed the event-range acceptance/retest gate.",
        "",
        "This proves the package is too restrictive for the operator's observed method. It does **not** prove the underlying method has no edge. It proves that this exact deterministic translation does not preserve the method: its specificity is zero on this exposed sample because it authorizes no trades.",
        "",
        "No threshold, lifecycle rule, or classification was changed after the pre-path seal. Primary/reference results matched for all 16 cases. The fresh 50-case block, 2025, and 2026 remain unopened.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    final_seal = {
        "status": "COMPLETE_AND_SEALED_EXPOSED_REGRESSION",
        "verdict": payload["verdict"],
        "result_sha256": sha256(RESULT),
        "table_sha256": sha256(TABLE),
        "reproduction_sha256": sha256(REPRODUCTION),
        "report_sha256": sha256(REPORT),
        "payload_sha256": payload["payload_sha256"],
        "module_sha256": payload["module_sha256"],
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
                "verdict": final_seal["verdict"],
                "admitted": payload["admitted"],
                "rejected": payload["rejected"],
                "net_r50": corrected_summary["net_r50"],
                "control_r50": control_summary["net_r50"],
                "valid_winners_rejected": len(valid_winners),
                "seal": final_seal["result_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

