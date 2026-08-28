#!/usr/bin/env python3
"""Run the noon-deadline-corrected 648-setup exposed regression."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import render_gold_auction_trade_placement_examples_v1 as placement  # noqa: E402
import run_gold_auction_all_transition_executable_multi_opportunity_v2 as v2_runner  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 import (  # noqa: E402
    execute_every_executable,
    matched_nonoverlap_diagnostic,
    summarize,
)
from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2_r1 import (  # noqa: E402
    NO_TIME_REASON,
    RULESET,
    compile_executable_population_r1,
)
from gold_intel.analytics.auction_trade_placement_outcomes_v1 import resolve_plan  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


CONTRACT = ROOT / "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_V2_R1_NOON_DEADLINE_AMENDMENT.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_all_transition_executable_multi_opportunity_v2_r1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_all_transition_executable_multi_opportunity_v2_r1.py"
RUNNER = Path(__file__).resolve()
BASE_TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_all_transition_executable_multi_opportunity_v2.py"

OUT = ROOT / "research_artifacts" / "gold_auction_all_transition_executable_multi_opportunity_v2_r1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "trade_ledger.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_V2_R1_REPORT.md"


def synthetic_proof() -> dict[str, Any]:
    names: list[str] = []
    for path, expected in ((BASE_TESTS, 6), (TESTS, 3)):
        namespace = runpy.run_path(str(path))
        tests = sorted(name for name, value in namespace.items() if name.startswith("test_") and callable(value))
        v2_runner.require(len(tests) == expected, f"Unexpected tests in {path}: {tests}")
        for name in tests:
            namespace[name]()
            names.append(f"{path.name}::{name}")
    payload = {"passed": len(names), "tests": names}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def load_compiled(side: str) -> list[dict[str, Any]]:
    events_path = placement.EVENTS_PRIMARY if side == "primary" else placement.EVENTS_REFERENCE
    overlays_path = placement.OVERLAYS_PRIMARY if side == "primary" else placement.OVERLAYS_REFERENCE
    events = v2_runner.load_json(events_path)["events"]
    overlays = v2_runner.load_json(overlays_path)["overlays"]
    return compile_executable_population_r1(events, overlays)


def assert_population(rows: list[dict[str, Any]]) -> None:
    v2_runner.require(len(rows) == 729, "Expected 729 transitions")
    v2_runner.require(len({row["event_identity"] for row in rows}) == 729, "Transition identities differ")
    v2_runner.require(len({row["trading_date_utc"] for row in rows}) == 117, "Expected 117 session-days")
    executable = [row for row in rows if row["mechanically_executable"]]
    noon = [row for row in rows if NO_TIME_REASON in row["hard_inexecutable_reasons"]]
    v2_runner.require(len(executable) == 648, "Expected exactly 648 executable setups")
    v2_runner.require(len(noon) == 12, "Expected exactly 12 noon-deadline dispositions")
    v2_runner.require(all(row["decision_at"] == row["noon_deadline"] for row in noon), "A noon disposition is not exactly at the deadline")
    v2_runner.require(all(row["event_class"] == "CONTINUATION_REFRESH" for row in noon), "Noon disposition event class differs")
    v2_runner.require(all(row["session"] == "NEW_YORK" for row in rows), "Non-New-York event entered population")
    dates = sorted({row["trading_date_utc"] for row in rows})
    v2_runner.require(dates[0] == "2022-01-03" and dates[-1] == "2022-06-30", "Population endpoints differ")
    v2_runner.require(not any("2022-02-17" <= value <= "2022-02-28" for value in dates), "Unopened February gap entered population")


def freeze() -> None:
    v2_runner.require(not OUT.exists(), f"Output directory already exists: {OUT}")
    v2_runner.require(not REPORT.exists(), f"Report already exists: {REPORT}")
    old = v2_runner.verify_freeze()
    v2_runner.require(not v2_runner.PRIMARY.exists(), "Stopped V2 unexpectedly wrote a primary result")
    v2_runner.require(not v2_runner.REFERENCE.exists(), "Stopped V2 unexpectedly wrote a reference result")
    v2_runner.require(not v2_runner.FINAL.exists(), "Stopped V2 unexpectedly wrote a final result")
    primary = load_compiled("primary")
    reference = load_compiled("reference")
    assert_population(primary)
    v2_runner.require(primary == reference, "Primary/reference R1 pre-outcome compilation differs")
    proof = synthetic_proof()
    executable = [row for row in primary if row["mechanically_executable"]]
    hard_counts = dict(sorted(Counter(reason for row in primary for reason in row["hard_inexecutable_reasons"]).items()))
    v2_runner.require(
        hard_counts
        == {
            "M5_PROTECTED_PIVOT_ALREADY_CONSUMED": 45,
            "NONPOSITIVE_STRUCTURAL_RISK": 1,
            "NO_TIME_REMAINING_BEFORE_NOON_DEADLINE": 12,
            "NO_UNCONSUMED_H1_OR_H4_DESTINATION": 24,
        },
        f"R1 hard reason counts differ: {hard_counts}",
    )
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_V2_R1_FREEZE_1_0",
        "frozen_at": v2_runner.now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_EXPOSED_NARROW_EXECUTION_CORRECTION",
        "correction": {
            "v2_execution_stopped_before_result_writes": True,
            "reason": "DECISION_AT_NOON_HAD_NO_LEGAL_PATH_BEFORE_PRESERVED_NOON_DEADLINE",
            "changed_classification_only": NO_TIME_REASON,
            "deadline_extended": False,
        },
        "population": {
            "events": 729,
            "executable_setups": 648,
            "hard_inexecutable_setups": 81,
            "noon_deadline_dispositions": 12,
            "event_identities": [row["event_identity"] for row in primary],
            "event_identities_sha256": canonical_hash([row["event_identity"] for row in primary]),
            "executable_identities": [row["event_identity"] for row in executable],
            "executable_identities_sha256": canonical_hash([row["event_identity"] for row in executable]),
            "hard_reason_counts": hard_counts,
        },
        "preserved_v2_rules": {
            "fitted_selector_absent": True,
            "minimum_reward_to_risk": None,
            "maximum_distance_from_break_atr": None,
            "continuation_rejection": False,
            "local_m15_room_filter": None,
            "daily_cap": False,
            "wait_for_previous_resolution": False,
            "execute_overlaps": True,
            "noon_deadline_preserved": True,
            "structural_stops_and_known_liquidity_targets_preserved": True,
        },
        "synthetic_proof": proof,
        "predecessor": {
            "v2_freeze": v2_runner.file_record(v2_runner.FREEZE),
            "v2_freeze_sha256": old["freeze_sha256"],
        },
        "governing_files": [
            v2_runner.file_record(path)
            for path in (
                CONTRACT,
                IMPLEMENTATION,
                TESTS,
                RUNNER,
                BASE_TESTS,
                v2_runner.IMPLEMENTATION,
                v2_runner.RUNNER,
                v2_runner.OUTCOME_IMPLEMENTATION,
            )
        ],
        "source_records": old["source_records"],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    v2_runner.write_json(FREEZE, payload)
    print(
        json.dumps(
            {
                "status": "FROZEN_V2_R1",
                "events": 729,
                "executable_setups": 648,
                "noon_dispositions": 12,
                "synthetic_tests": proof["passed"],
                "freeze_sha256": payload["freeze_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def verify_freeze() -> dict[str, Any]:
    frozen = v2_runner.verify_canonical_payload(FREEZE, "freeze_sha256")
    for record in frozen["governing_files"] + frozen["source_records"]:
        v2_runner.verify_file_record(record)
    v2_runner.verify_file_record(frozen["predecessor"]["v2_freeze"])
    old = v2_runner.verify_freeze()
    v2_runner.require(old["freeze_sha256"] == frozen["predecessor"]["v2_freeze_sha256"], "V2 predecessor freeze differs")
    v2_runner.require(frozen["population"]["executable_setups"] == 648, "Frozen R1 population differs")
    return frozen


def run_side(side: str, frozen: dict[str, Any]) -> dict[str, Any]:
    compiled = load_compiled(side)
    assert_population(compiled)
    v2_runner.require([row["event_identity"] for row in compiled] == frozen["population"]["event_identities"], f"{side} event identities differ")
    v2_runner.require([row["event_identity"] for row in compiled if row["mechanically_executable"]] == frozen["population"]["executable_identities"], f"{side} executable identities differ")
    streams = source.load_streams(side)
    rows = execute_every_executable(compiled, streams, resolve_plan)
    diagnostic = matched_nonoverlap_diagnostic(rows)
    summary = summarize(rows, diagnostic)
    v2_runner.require(summary["all_executable_signals"]["trades"] == 648, f"{side} did not execute all 648 setups")
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_V2_R1_SIDE_1_0",
        "side": side,
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
        "nonoverlap_diagnostic_rows": diagnostic,
        "nonoverlap_diagnostic_sha256": canonical_hash(diagnostic),
        "summary": summary,
        "summary_sha256": canonical_hash(summary),
        "all_648_executed": True,
        "overlap_suppression_applied": False,
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def pf(row: dict[str, Any]) -> str:
    return "inf" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"


def report_markdown(final: dict[str, Any]) -> str:
    summary = final["summary"]
    primary = summary["all_executable_signals"]
    diagnostic = summary["matched_nonoverlap_diagnostic"]
    lines = [
        "# Gold Auction All-Transition Executable Multi-Opportunity V2-R1 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "The noon-New-York deadline was preserved. Twelve signals occurring exactly at noon were classified mechanically unavailable, leaving all other **648** executable setups unchanged.",
        "",
        f"- Frequency: **{summary['average_trades_per_calendar_month']:.2f} trades/month**, across {summary['days_with_trade']} days, maximum {summary['maximum_trades_one_day']} trades in one day.",
        f"- Direction: **{summary['by_direction']['LONG']['trades']} LONG / {summary['by_direction']['SHORT']['trades']} SHORT**.",
        f"- Overlapping setups retained: **{summary['overlap_signals_retained_by_primary']}**.",
        f"- Maximum concurrency: **{summary['concurrency']['maximum_concurrent_positions']} positions / ${summary['concurrency']['maximum_concurrent_planned_risk_usd']:.2f} planned risk**.",
        "",
        f"Unrestricted primary: **{primary['net_r50']:+.4f}R / ${primary['net_pnl_usd']:+.2f}**, {primary['win_rate'] * 100:.2f}% win rate, {primary['expectancy_r50']:+.4f}R expectancy, PF {pf(primary)}, max drawdown {primary['maximum_drawdown_r50']:.4f}R.",
        "",
        f"Matched wait-for-resolution diagnostic: **{diagnostic['net_r50']:+.4f}R / ${diagnostic['net_pnl_usd']:+.2f}**, {diagnostic['trades']} trades, PF {pf(diagnostic)}.",
        "",
        "## Monthly results",
        "",
        "| Month | Trades | Win rate | Net R | PnL USD | PF | Max DD R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for month, row in summary["by_month"].items():
        lines.append(f"| {month} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | ${row['net_pnl_usd']:+.2f} | {pf(row)} | {row['maximum_drawdown_r50']:.4f} |")
    lines.extend(
        [
            "",
            "## Direction results",
            "",
            "| Direction | Trades | Win rate | Net R | PnL USD | PF |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for direction, row in summary["by_direction"].items():
        lines.append(f"| {direction} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | ${row['net_pnl_usd']:+.2f} | {pf(row)} |")
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "- Both independent passes executed the same 648 identities and matched exactly.",
            "- No fitted selector, quality filter, daily cap, or overlap suppression was applied.",
            "- Structural stops, known-liquidity targets, costs, risk, and noon deadline were preserved.",
            "- No new period, 2025, or 2026 was opened and no charge occurred.",
            "- This remains exposed regression evidence with zero validation credit.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    primary = run_side("primary", frozen)
    print("primary complete: 648 trades", flush=True)
    reference = run_side("reference", frozen)
    print("reference complete: 648 trades", flush=True)
    v2_runner.require(primary["rows"] == reference["rows"], "Primary/reference executions differ")
    v2_runner.require(primary["nonoverlap_diagnostic_rows"] == reference["nonoverlap_diagnostic_rows"], "Primary/reference diagnostics differ")
    v2_runner.require(primary["summary"] == reference["summary"], "Primary/reference summaries differ")
    summary = primary["summary"]
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_V2_R1_FINAL_1_0",
        "verdict": "COMPLETE_CORRECTED_ALL_648_EXPOSED_REGRESSION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "primary_reference_exact": True,
        "all_648_executed": True,
        "noon_deadline_preserved": True,
        "overlap_suppression_applied": False,
        "summary": summary,
        "summary_sha256": canonical_hash(summary),
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "validation_credit": "ZERO_EXPOSED_CORRECTIVE_REGRESSION",
    }
    final["final_sha256"] = canonical_hash(final)
    v2_runner.write_json(PRIMARY, primary)
    v2_runner.write_json(REFERENCE, reference)
    v2_runner.write_json(FINAL, final)
    v2_runner.write_text(LEDGER, v2_runner.ledger_csv(primary["rows"]))
    v2_runner.write_text(REPORT, report_markdown(final))
    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_V2_R1_CERTIFICATION_1_0",
        "completed_at": v2_runner.now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "events_exact_729": summary["event_population"] == 729,
            "trades_exact_648": summary["all_executable_signals"]["trades"] == 648,
            "noon_deadline_preserved": True,
            "twelve_noon_signals_excluded": summary["hard_reason_counts"].get(NO_TIME_REASON) == 12,
            "daily_cap_absent": True,
            "wait_for_resolution_absent": True,
            "overlap_suppression_absent": True,
            "primary_reference_exact": True,
            "fresh_periods_locked": True,
            "no_charge": True,
        },
        "output_records": [v2_runner.file_record(path) for path in (PRIMARY, REFERENCE, FINAL, LEDGER, REPORT)],
    }
    v2_runner.require(all(certification["gates"].values()), "Certification gate failed")
    certification["certification_sha256"] = canonical_hash(certification)
    v2_runner.write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_V2_R1_SEAL_1_0",
        "sealed_at": v2_runner.now(),
        "verdict": final["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [v2_runner.file_record(path) for path in (FREEZE, PRIMARY, REFERENCE, FINAL, LEDGER, CERTIFICATION, REPORT)],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    v2_runner.write_json(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": final["verdict"],
                "summary": summary,
                "report": REPORT.relative_to(ROOT).as_posix(),
                "ledger": LEDGER.relative_to(ROOT).as_posix(),
                "seal_sha256": seal["seal_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"run", "all"}:
        run()


if __name__ == "__main__":
    main()
