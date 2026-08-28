#!/usr/bin/env python3
"""Run direct inversion with the authorized three-setup risk exception."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import run_gold_auction_all_transition_executable_multi_opportunity_v2 as v2_runner  # noqa: E402
import run_gold_continuation_refresh_direct_inversion_v1 as base  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 import (  # noqa: E402
    economic_summary,
    execute_every_executable,
    matched_nonoverlap_diagnostic,
    summarize,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402
from gold_intel.analytics.continuation_refresh_direct_inversion_risk_exception_v1 import (  # noqa: E402
    EXCEPTION_IDENTITIES,
    MAX_EXCEPTION_DISPLAYED_RISK_USD,
    RULESET,
    resolve_plan_with_bounded_exception,
)


CONTRACT = ROOT / "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_V1_R1_BOUNDED_RISK_EXCEPTION.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "continuation_refresh_direct_inversion_risk_exception_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_continuation_refresh_direct_inversion_risk_exception_v1.py"
RUNNER = Path(__file__).resolve()

OUT = ROOT / "research_artifacts" / "gold_continuation_refresh_direct_inversion_exposed_diagnostic_v1_r1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "trade_ledger.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_V1_R1_REPORT.md"


def proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    tests = sorted(name for name, value in namespace.items() if name.startswith("test_") and callable(value))
    v2_runner.require(len(tests) == 4, f"Unexpected risk-exception tests: {tests}")
    for name in tests:
        namespace[name]()
    payload = {"passed": len(tests), "tests": tests}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def freeze() -> None:
    v2_runner.require(not OUT.exists(), f"Output directory already exists: {OUT}")
    v2_runner.require(not REPORT.exists(), f"Report already exists: {REPORT}")
    predecessor = base.verify_freeze()
    v2_runner.require(not base.PRIMARY.exists(), "Stopped inversion unexpectedly wrote primary results")
    v2_runner.require(not base.REFERENCE.exists(), "Stopped inversion unexpectedly wrote reference results")
    v2_runner.require(not base.FINAL.exists(), "Stopped inversion unexpectedly wrote final results")
    primary = base.load_population("primary")
    reference = base.load_population("reference")
    base.assert_population(primary)
    v2_runner.require(primary == reference, "Primary/reference risk-exception mapping differs")
    required = {
        str(row["event_identity"]): float(row["plan"]["risk_price"])
        for row in primary
        if row["continuation_directly_inverted"]
        and float(row["plan"]["risk_price"]) > 50.0
    }
    v2_runner.require(set(required) == set(EXCEPTION_IDENTITIES), f"Risk-exception identities differ: {required}")
    v2_runner.require(max(required.values()) <= MAX_EXCEPTION_DISPLAYED_RISK_USD + 1e-9, "Required exception exceeds cap")
    test_proof = proof()
    payload: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_V1_R1_FREEZE_1_0",
        "frozen_at": v2_runner.now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_POST_HOC_EXPOSED_DIAGNOSTIC",
        "population": predecessor["population"],
        "risk_exception": {
            "identities": sorted(EXCEPTION_IDENTITIES),
            "displayed_risk_usd_by_identity": dict(sorted(required.items())),
            "quantity_ounces": 1,
            "maximum_displayed_planned_risk_usd": MAX_EXCEPTION_DISPLAYED_RISK_USD,
            "all_other_setups_retain_50_usd_whole_ounce_sizing": True,
            "r_reporting_benchmark_usd": 50.0,
        },
        "inversion": predecessor["inversion"],
        "original_exposed_continuation_result": predecessor["original_exposed_continuation_result"],
        "synthetic_proof": test_proof,
        "predecessor": {
            "freeze_sha256": predecessor["freeze_sha256"],
            "freeze": v2_runner.file_record(base.FREEZE),
        },
        "governing_files": [
            v2_runner.file_record(path)
            for path in (
                CONTRACT,
                IMPLEMENTATION,
                TESTS,
                RUNNER,
                base.IMPLEMENTATION,
                base.RUNNER,
                v2_runner.OUTCOME_IMPLEMENTATION,
            )
        ],
        "source_records": predecessor["source_records"],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    v2_runner.write_json(FREEZE, payload)
    print(
        json.dumps(
            {
                "status": "FROZEN_BOUNDED_RISK_EXCEPTION",
                "exception_setups": len(required),
                "risk_range_usd": [min(required.values()), max(required.values())],
                "tests": test_proof["passed"],
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
    v2_runner.verify_file_record(frozen["predecessor"]["freeze"])
    predecessor = base.verify_freeze()
    v2_runner.require(predecessor["freeze_sha256"] == frozen["predecessor"]["freeze_sha256"], "Inversion predecessor differs")
    v2_runner.require(set(frozen["risk_exception"]["identities"]) == set(EXCEPTION_IDENTITIES), "Risk exception registry differs")
    return frozen


def run_side(side: str, frozen: dict[str, Any]) -> dict[str, Any]:
    compiled = base.load_population(side)
    base.assert_population(compiled)
    streams = source.load_streams(side)
    rows = execute_every_executable(compiled, streams, resolve_plan_with_bounded_exception)
    diagnostic = matched_nonoverlap_diagnostic(rows)
    summary = summarize(rows, diagnostic)
    continuation = [float(row["net_r50"]) for row in rows if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS" and row["event_class"] == "CONTINUATION_REFRESH"]
    unchanged = [float(row["net_r50"]) for row in rows if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS" and row["event_class"] != "CONTINUATION_REFRESH"]
    exception_rows = [
        row
        for row in rows
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
        and row["event_identity"] in EXCEPTION_IDENTITIES
    ]
    v2_runner.require(len(continuation) == 434 and len(unchanged) == 214, f"{side} execution counts differ")
    v2_runner.require(len(exception_rows) == 3, f"{side} exception count differs")
    v2_runner.require(all(row["result"]["execution"].get("bounded_risk_exception_applied") is True for row in exception_rows), f"{side} exception was not applied")
    payload: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_V1_R1_SIDE_1_0",
        "side": side,
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
        "nonoverlap_diagnostic_rows": diagnostic,
        "nonoverlap_diagnostic_sha256": canonical_hash(diagnostic),
        "replacement_portfolio": summary,
        "replacement_portfolio_sha256": canonical_hash(summary),
        "inverted_continuation": economic_summary(continuation),
        "unchanged_non_continuation": economic_summary(unchanged),
        "risk_exception_rows": exception_rows,
        "risk_exception_rows_sha256": canonical_hash(exception_rows),
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def pf(row: dict[str, Any]) -> str:
    return "inf" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"


def report_markdown(final: dict[str, Any]) -> str:
    original = final["original_continuation"]
    inverted = final["inverted_continuation"]
    unchanged = final["unchanged_non_continuation"]
    portfolio = final["replacement_portfolio"]
    total = portfolio["all_executable_signals"]
    lines = [
        "# Gold Continuation-Refresh Direct Inversion V1-R1 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "All 434 continuation-refresh trades were inverted exactly. Three required one ounce with displayed planned risk between $50.91 and $53.01; every other setup retained the original $50 whole-ounce sizing rule.",
        "",
        "| Track | Trades | Win rate | Net R | PnL USD | PF | Max DD R |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Original continuation | {original['trades']} | {original['win_rate'] * 100:.2f}% | {original['net_r50']:+.4f} | ${original['net_pnl_usd']:+.2f} | {pf(original)} | {original['maximum_drawdown_r50']:.4f} |",
        f"| Inverted continuation | {inverted['trades']} | {inverted['win_rate'] * 100:.2f}% | {inverted['net_r50']:+.4f} | ${inverted['net_pnl_usd']:+.2f} | {pf(inverted)} | {inverted['maximum_drawdown_r50']:.4f} |",
        f"| Unchanged non-continuation | {unchanged['trades']} | {unchanged['win_rate'] * 100:.2f}% | {unchanged['net_r50']:+.4f} | ${unchanged['net_pnl_usd']:+.2f} | {pf(unchanged)} | {unchanged['maximum_drawdown_r50']:.4f} |",
        f"| Complete replacement portfolio | {total['trades']} | {total['win_rate'] * 100:.2f}% | {total['net_r50']:+.4f} | ${total['net_pnl_usd']:+.2f} | {pf(total)} | {total['maximum_drawdown_r50']:.4f} |",
        "",
        f"Frequency: **{portfolio['average_trades_per_calendar_month']:.2f} trades/month**. Overlapping signals retained: **{portfolio['overlap_signals_retained_by_primary']}**. Maximum concurrency: **{portfolio['concurrency']['maximum_concurrent_positions']} positions / ${portfolio['concurrency']['maximum_concurrent_planned_risk_usd']:.2f} planned risk**.",
        "",
        "## Replacement portfolio by month",
        "",
        "| Month | Trades | Win rate | Net R | PF |",
        "|---|---:|---:|---:|---:|",
    ]
    for month, row in portfolio["by_month"].items():
        lines.append(f"| {month} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | {pf(row)} |")
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "- Primary and reference results and checksums matched exactly.",
            "- Only the exact three authorized one-ounce exceptions exceeded $50; none exceeded $53.01.",
            "- No alternative inversion, filter, management rule, or fresh period was tested.",
            "- This is post-hoc exposed evidence with zero validation credit.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    primary = run_side("primary", frozen)
    print("primary inversion complete", flush=True)
    reference = run_side("reference", frozen)
    print("reference inversion complete", flush=True)
    v2_runner.require(primary["rows"] == reference["rows"], "Primary/reference executions differ")
    v2_runner.require(primary["replacement_portfolio"] == reference["replacement_portfolio"], "Primary/reference summaries differ")
    v2_runner.require(primary["risk_exception_rows"] == reference["risk_exception_rows"], "Primary/reference exceptions differ")
    final: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_V1_R1_FINAL_1_0",
        "verdict": "COMPLETE_DIRECT_INVERSION_WITH_BOUNDED_RISK_EXCEPTION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "original_continuation": frozen["original_exposed_continuation_result"],
        "inverted_continuation": primary["inverted_continuation"],
        "unchanged_non_continuation": primary["unchanged_non_continuation"],
        "replacement_portfolio": primary["replacement_portfolio"],
        "risk_exception_count": 3,
        "primary_reference_exact": True,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "validation_credit": "ZERO_POST_HOC_EXPOSED_DIAGNOSTIC",
    }
    final["final_sha256"] = canonical_hash(final)
    v2_runner.write_json(PRIMARY, primary)
    v2_runner.write_json(REFERENCE, reference)
    v2_runner.write_json(FINAL, final)
    v2_runner.write_text(LEDGER, v2_runner.ledger_csv(primary["rows"]))
    v2_runner.write_text(REPORT, report_markdown(final))
    certification: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_V1_R1_CERTIFICATION_1_0",
        "completed_at": v2_runner.now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "continuation_exact_434": final["inverted_continuation"]["trades"] == 434,
            "replacement_exact_648": final["replacement_portfolio"]["all_executable_signals"]["trades"] == 648,
            "exception_exact_3": final["risk_exception_count"] == 3,
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
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_V1_R1_SEAL_1_0",
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
                "original_continuation": final["original_continuation"],
                "inverted_continuation": final["inverted_continuation"],
                "unchanged_non_continuation": final["unchanged_non_continuation"],
                "replacement_portfolio": final["replacement_portfolio"],
                "report": REPORT.relative_to(ROOT).as_posix(),
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
