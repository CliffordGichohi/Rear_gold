#!/usr/bin/env python3
"""Run the authorized direct inversion of continuation-refresh setups."""

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

import run_gold_auction_all_transition_executable_multi_opportunity_v2 as v2_runner  # noqa: E402
import run_gold_auction_all_transition_executable_multi_opportunity_v2_r1 as base  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 import (  # noqa: E402
    economic_summary,
    execute_every_executable,
    matched_nonoverlap_diagnostic,
    summarize,
)
from gold_intel.analytics.auction_trade_placement_outcomes_v1 import resolve_plan  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402
from gold_intel.analytics.continuation_refresh_direct_inversion_v1 import (  # noqa: E402
    RULESET,
    apply_inversion_population,
)


CONTRACT = ROOT / "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_V1.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "continuation_refresh_direct_inversion_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_continuation_refresh_direct_inversion_v1.py"
RUNNER = Path(__file__).resolve()

OUT = ROOT / "research_artifacts" / "gold_continuation_refresh_direct_inversion_exposed_diagnostic_v1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "trade_ledger.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_V1_REPORT.md"


def proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    tests = sorted(name for name, value in namespace.items() if name.startswith("test_") and callable(value))
    v2_runner.require(len(tests) == 4, f"Unexpected inversion tests: {tests}")
    for name in tests:
        namespace[name]()
    payload = {"passed": len(tests), "tests": tests}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def load_population(side: str) -> list[dict[str, Any]]:
    return apply_inversion_population(base.load_compiled(side))


def assert_population(rows: list[dict[str, Any]]) -> None:
    v2_runner.require(len(rows) == 729, "Expected 729 transition rows")
    executable = [row for row in rows if row["mechanically_executable"]]
    inverted = [row for row in rows if row["continuation_directly_inverted"]]
    unchanged = [row for row in executable if not row["continuation_directly_inverted"]]
    v2_runner.require(len(executable) == 648, "Expected 648 executable plans")
    v2_runner.require(len(inverted) == 434, "Expected exactly 434 inverted continuation plans")
    v2_runner.require(len(unchanged) == 214, "Expected exactly 214 unchanged executable plans")
    v2_runner.require(all(row["event_class"] == "CONTINUATION_REFRESH" for row in inverted), "A non-continuation plan was inverted")
    v2_runner.require(all(row["execution_direction"] != row["source_direction"] for row in inverted), "An inverted direction did not flip")
    v2_runner.require(all(row["execution_direction"] == row["source_direction"] for row in unchanged), "An unchanged direction moved")
    for row in inverted:
        direct = row["plan"]["direct_inversion"]
        v2_runner.require(float(row["plan"]["stop"]) == float(direct["original_target"]), "Original TP did not become SL")
        v2_runner.require(float(row["plan"]["target"]["level"]) == float(direct["original_stop"]), "Original SL did not become TP")


def freeze() -> None:
    v2_runner.require(not OUT.exists(), f"Output directory already exists: {OUT}")
    v2_runner.require(not REPORT.exists(), f"Report already exists: {REPORT}")
    predecessor = base.verify_freeze()
    predecessor_seal = v2_runner.verify_canonical_seal(base.SEAL)
    original_final = v2_runner.verify_canonical_payload(base.FINAL, "final_sha256")
    primary = load_population("primary")
    reference = load_population("reference")
    assert_population(primary)
    v2_runner.require(primary == reference, "Primary/reference inversion mapping differs")
    test_proof = proof()
    inverted = [row for row in primary if row["continuation_directly_inverted"]]
    direction_flips = Counter(f"{row['source_direction']}_TO_{row['execution_direction']}" for row in inverted)
    payload: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_V1_FREEZE_1_0",
        "frozen_at": v2_runner.now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_POST_HOC_EXPOSED_DIAGNOSTIC",
        "population": {
            "events": 729,
            "executable": 648,
            "continuation_inverted": 434,
            "non_continuation_unchanged": 214,
            "inverted_identities": [row["event_identity"] for row in inverted],
            "inverted_identities_sha256": canonical_hash([row["event_identity"] for row in inverted]),
            "complete_execution_identities": [row["event_identity"] for row in primary if row["mechanically_executable"]],
            "complete_execution_identities_sha256": canonical_hash([row["event_identity"] for row in primary if row["mechanically_executable"]]),
            "direction_flips": dict(sorted(direction_flips.items())),
        },
        "inversion": {
            "event_class": "CONTINUATION_REFRESH",
            "buy_becomes_sell": True,
            "sell_becomes_buy": True,
            "original_tp_becomes_new_sl": True,
            "original_sl_becomes_new_tp": True,
            "same_decision_timestamp": True,
            "same_latency_costs_deadline_and_overlap_policy": True,
            "quantity_recalculated_for_50_usd_maximum_planned_risk": True,
            "alternative_mapping_permitted": False,
        },
        "original_exposed_continuation_result": original_final["summary"]["by_event_class"]["CONTINUATION_REFRESH"],
        "synthetic_proof": test_proof,
        "predecessor": {
            "freeze_sha256": predecessor["freeze_sha256"],
            "seal_sha256": predecessor_seal["seal_sha256"],
            "freeze": v2_runner.file_record(base.FREEZE),
            "final": v2_runner.file_record(base.FINAL),
            "seal": v2_runner.file_record(base.SEAL),
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
                "status": "FROZEN_DIRECT_INVERSION",
                "continuation_inverted": 434,
                "unchanged": 214,
                "direction_flips": dict(direction_flips),
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
    for key in ("freeze", "final", "seal"):
        v2_runner.verify_file_record(frozen["predecessor"][key])
    predecessor = base.verify_freeze()
    seal = v2_runner.verify_canonical_seal(base.SEAL)
    v2_runner.require(predecessor["freeze_sha256"] == frozen["predecessor"]["freeze_sha256"], "Predecessor freeze differs")
    v2_runner.require(seal["seal_sha256"] == frozen["predecessor"]["seal_sha256"], "Predecessor seal differs")
    return frozen


def run_side(side: str, frozen: dict[str, Any]) -> dict[str, Any]:
    compiled = load_population(side)
    assert_population(compiled)
    v2_runner.require([row["event_identity"] for row in compiled if row["continuation_directly_inverted"]] == frozen["population"]["inverted_identities"], f"{side} inverted identities differ")
    streams = source.load_streams(side)
    rows = execute_every_executable(compiled, streams, resolve_plan)
    diagnostic = matched_nonoverlap_diagnostic(rows)
    summary = summarize(rows, diagnostic)
    continuation = [float(row["net_r50"]) for row in rows if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS" and row["event_class"] == "CONTINUATION_REFRESH"]
    unchanged = [float(row["net_r50"]) for row in rows if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS" and row["event_class"] != "CONTINUATION_REFRESH"]
    v2_runner.require(len(continuation) == 434 and len(unchanged) == 214, f"{side} execution counts differ")
    payload: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_V1_SIDE_1_0",
        "side": side,
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
        "nonoverlap_diagnostic_rows": diagnostic,
        "nonoverlap_diagnostic_sha256": canonical_hash(diagnostic),
        "replacement_portfolio": summary,
        "replacement_portfolio_sha256": canonical_hash(summary),
        "inverted_continuation": economic_summary(continuation),
        "unchanged_non_continuation": economic_summary(unchanged),
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
        "# Gold Continuation-Refresh Direct Inversion Exposed Diagnostic V1 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "The 434 continuation-refresh setups were inverted exactly: BUY became SELL, SELL became BUY, original TP became SL, and original SL became TP. The other 214 setups were unchanged.",
        "",
        "| Track | Trades | Win rate | Net R | PnL USD | PF | Max DD R |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Original continuation | {original['trades']} | {original['win_rate'] * 100:.2f}% | {original['net_r50']:+.4f} | ${original['net_pnl_usd']:+.2f} | {pf(original)} | {original['maximum_drawdown_r50']:.4f} |",
        f"| Executable inverted continuation | {inverted['trades']} | {inverted['win_rate'] * 100:.2f}% | {inverted['net_r50']:+.4f} | ${inverted['net_pnl_usd']:+.2f} | {pf(inverted)} | {inverted['maximum_drawdown_r50']:.4f} |",
        f"| Unchanged non-continuation | {unchanged['trades']} | {unchanged['win_rate'] * 100:.2f}% | {unchanged['net_r50']:+.4f} | ${unchanged['net_pnl_usd']:+.2f} | {pf(unchanged)} | {unchanged['maximum_drawdown_r50']:.4f} |",
        f"| Complete replacement portfolio | {total['trades']} | {total['win_rate'] * 100:.2f}% | {total['net_r50']:+.4f} | ${total['net_pnl_usd']:+.2f} | {pf(total)} | {total['maximum_drawdown_r50']:.4f} |",
        "",
        f"Replacement frequency remained **{portfolio['average_trades_per_calendar_month']:.2f} trades/month**. Maximum concurrency was **{portfolio['concurrency']['maximum_concurrent_positions']} positions / ${portfolio['concurrency']['maximum_concurrent_planned_risk_usd']:.2f} planned risk**.",
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
            "- Primary and reference plans, executions, diagnostics, summaries, and checksums matched exactly.",
            "- No second inversion, filter, threshold, or management alternative was tested.",
            "- No fresh period, 2025, or 2026 was opened and no charge occurred.",
            "- This is a post-hoc exposed diagnostic with zero validation credit.",
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
    v2_runner.require(primary["rows"] == reference["rows"], "Primary/reference inverted executions differ")
    v2_runner.require(primary["replacement_portfolio"] == reference["replacement_portfolio"], "Primary/reference replacement summaries differ")
    v2_runner.require(primary["inverted_continuation"] == reference["inverted_continuation"], "Primary/reference continuation summaries differ")
    final: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_V1_FINAL_1_0",
        "verdict": "COMPLETE_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "original_continuation": frozen["original_exposed_continuation_result"],
        "inverted_continuation": primary["inverted_continuation"],
        "unchanged_non_continuation": primary["unchanged_non_continuation"],
        "replacement_portfolio": primary["replacement_portfolio"],
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
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_V1_CERTIFICATION_1_0",
        "completed_at": v2_runner.now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "continuation_exact_434": final["inverted_continuation"]["trades"] == 434,
            "non_continuation_exact_214": final["unchanged_non_continuation"]["trades"] == 214,
            "replacement_exact_648": final["replacement_portfolio"]["all_executable_signals"]["trades"] == 648,
            "tp_to_sl_and_sl_to_tp_only": True,
            "primary_reference_exact": True,
            "no_alternative_tested": True,
            "fresh_periods_locked": True,
            "no_charge": True,
        },
        "output_records": [v2_runner.file_record(path) for path in (PRIMARY, REFERENCE, FINAL, LEDGER, REPORT)],
    }
    v2_runner.require(all(certification["gates"].values()), "Certification gate failed")
    certification["certification_sha256"] = canonical_hash(certification)
    v2_runner.write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_V1_SEAL_1_0",
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
