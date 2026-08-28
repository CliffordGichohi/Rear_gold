#!/usr/bin/env python3
"""Run the fixed-original-quantity true negation diagnostic."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import runpy
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import run_gold_auction_all_transition_executable_multi_opportunity_v2 as v2_runner  # noqa: E402
import run_gold_auction_all_transition_executable_multi_opportunity_v2_r1 as original  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
import run_gold_continuation_refresh_direct_inversion_v1 as inversion  # noqa: E402
from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 import (  # noqa: E402
    economic_summary,
    execute_every_executable,
    matched_nonoverlap_diagnostic,
    summarize,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402
from gold_intel.analytics.continuation_refresh_true_negation_fixed_quantity_v1 import (  # noqa: E402
    RULESET,
    attach_original_quantities,
    resolve_plan_fixed_original_quantity,
)


CONTRACT = ROOT / "GOLD_CONTINUATION_REFRESH_TRUE_NEGATION_FIXED_QUANTITY_EXPOSED_DIAGNOSTIC_V1.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "continuation_refresh_true_negation_fixed_quantity_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_continuation_refresh_true_negation_fixed_quantity_v1.py"
RUNNER = Path(__file__).resolve()

RERISKED_ROOT = ROOT / "research_artifacts" / "gold_continuation_refresh_direct_inversion_exposed_diagnostic_v1_r1"
RERISKED_FINAL = RERISKED_ROOT / "final_result.json"
RERISKED_SEAL = RERISKED_ROOT / "seal.json"

OUT = ROOT / "research_artifacts" / "gold_continuation_refresh_true_negation_fixed_quantity_exposed_diagnostic_v1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "trade_ledger.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_CONTINUATION_REFRESH_TRUE_NEGATION_FIXED_QUANTITY_EXPOSED_DIAGNOSTIC_V1_REPORT.md"


def proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    tests = sorted(
        name
        for name, value in namespace.items()
        if name.startswith("test_") and callable(value)
    )
    v2_runner.require(len(tests) == 4, f"Unexpected fixed-quantity tests: {tests}")
    for name in tests:
        namespace[name]()
    payload = {"passed": len(tests), "tests": tests}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def load_original_payload(side: str) -> dict[str, Any]:
    path = original.PRIMARY if side == "primary" else original.REFERENCE
    return v2_runner.verify_canonical_payload(path, "payload_sha256")


def original_execution_map(side: str) -> dict[str, dict[str, Any]]:
    payload = load_original_payload(side)
    return {
        str(row["event_identity"]): dict(row["result"]["execution"])
        for row in payload["rows"]
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    }


def original_result_map(side: str) -> dict[str, dict[str, Any]]:
    payload = load_original_payload(side)
    return {
        str(row["event_identity"]): dict(row)
        for row in payload["rows"]
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    }


def load_population(side: str) -> list[dict[str, Any]]:
    return attach_original_quantities(inversion.load_population(side))


def assert_population(
    rows: list[dict[str, Any]], old_execution: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    v2_runner.require(len(rows) == 729, "Expected 729 transition rows")
    executable = [row for row in rows if row["mechanically_executable"]]
    inverted = [row for row in executable if row["continuation_directly_inverted"]]
    unchanged = [row for row in executable if not row["continuation_directly_inverted"]]
    v2_runner.require(len(executable) == 648, "Expected 648 executable plans")
    v2_runner.require(len(inverted) == 434, "Expected 434 inverted continuation plans")
    v2_runner.require(len(unchanged) == 214, "Expected 214 unchanged plans")
    v2_runner.require(
        all(row["event_class"] == "CONTINUATION_REFRESH" for row in inverted),
        "A non-continuation plan was inverted",
    )
    quantities: list[int] = []
    new_stop_exposures: list[float] = []
    quantity_rows: list[dict[str, Any]] = []
    for row in inverted:
        plan = row["plan"]
        direct = plan["direct_inversion"]
        fixed = plan["fixed_original_quantity"]
        event = str(row["event_identity"])
        old = old_execution[event]
        derived = math.floor(
            50.0 / abs(float(plan["entry"]) - float(direct["original_stop"]))
        )
        frozen_quantity = int(fixed["quantity_ounces"])
        v2_runner.require(
            frozen_quantity == int(old["quantity_ounces"]) == derived,
            f"Original quantity differs: {event}",
        )
        v2_runner.require(
            fixed["quantity_recalculated_after_inversion"] is False,
            f"Quantity was recalculated after inversion: {event}",
        )
        v2_runner.require(
            float(plan["stop"]) == float(direct["original_target"]),
            f"Original target did not become stop: {event}",
        )
        v2_runner.require(
            float(plan["target"]["level"]) == float(direct["original_stop"]),
            f"Original stop did not become target: {event}",
        )
        v2_runner.require(
            str(plan["direction"]) != str(direct["original_direction"]),
            f"Direction did not reverse: {event}",
        )
        quantities.append(frozen_quantity)
        new_stop_exposures.append(float(fixed["inverted_displayed_stop_risk_usd"]))
        quantity_rows.append(
            {
                "event_identity": event,
                "original_quantity_ounces": frozen_quantity,
                "original_displayed_planned_risk_usd": float(
                    fixed["original_displayed_planned_risk_usd"]
                ),
                "inverted_displayed_stop_risk_usd": float(
                    fixed["inverted_displayed_stop_risk_usd"]
                ),
                "quantity_recalculated_after_inversion": False,
            }
        )
    ordered = sorted(quantities)
    p99 = ordered[math.ceil(0.99 * len(ordered)) - 1]
    return {
        "events": len(rows),
        "executable": len(executable),
        "continuation_true_negated": len(inverted),
        "non_continuation_unchanged": len(unchanged),
        "fixed_original_quantity_min": min(quantities),
        "fixed_original_quantity_max": max(quantities),
        "fixed_original_quantity_p99": p99,
        "fixed_original_quantity_median": statistics.median(quantities),
        "inverted_stop_exposure_min_usd": min(new_stop_exposures),
        "inverted_stop_exposure_max_usd": max(new_stop_exposures),
        "inverted_stop_exposure_median_usd": statistics.median(new_stop_exposures),
        "quantity_rows": quantity_rows,
        "quantity_rows_sha256": canonical_hash(quantity_rows),
        "all_434_match_original_sealed_execution_quantities": True,
        "quantity_recalculation_count": 0,
    }


def preflight() -> dict[str, Any]:
    original_freeze = original.verify_freeze()
    original_seal = v2_runner.verify_canonical_seal(original.SEAL)
    rerisked_seal = v2_runner.verify_canonical_seal(RERISKED_SEAL)
    rerisked_final = v2_runner.verify_canonical_payload(RERISKED_FINAL, "final_sha256")
    primary_old = original_execution_map("primary")
    reference_old = original_execution_map("reference")
    v2_runner.require(primary_old == reference_old, "Original primary/reference executions differ")
    primary = load_population("primary")
    reference = load_population("reference")
    v2_runner.require(primary == reference, "Primary/reference fixed mappings differ")
    population = assert_population(primary, primary_old)
    test_proof = proof()
    payload: dict[str, Any] = {
        "status": "PREFLIGHT_TRUE_NEGATION_FIXED_QUANTITY_PASS",
        "original_freeze_sha256": original_freeze["freeze_sha256"],
        "original_seal_sha256": original_seal["seal_sha256"],
        "rerisked_seal_sha256": rerisked_seal["seal_sha256"],
        "rerisked_continuation_net_r50": rerisked_final["inverted_continuation"][
            "net_r50"
        ],
        "population": population,
        "synthetic_proof": test_proof,
    }
    payload["preflight_sha256"] = canonical_hash(payload)
    return payload


def freeze() -> None:
    v2_runner.require(not OUT.exists(), f"Output directory already exists: {OUT}")
    v2_runner.require(not REPORT.exists(), f"Report already exists: {REPORT}")
    checked = preflight()
    original_final = v2_runner.verify_canonical_payload(original.FINAL, "final_sha256")
    rerisked_final = v2_runner.verify_canonical_payload(RERISKED_FINAL, "final_sha256")
    original_freeze = original.verify_freeze()
    primary = load_population("primary")
    inverted = [row for row in primary if row["continuation_directly_inverted"]]
    direction_flips = Counter(
        f"{row['source_direction']}_TO_{row['execution_direction']}" for row in inverted
    )
    population = dict(checked["population"])
    quantity_rows = population.pop("quantity_rows")
    payload: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_TRUE_NEGATION_FIXED_QUANTITY_V1_FREEZE_1_0",
        "frozen_at": v2_runner.now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_POST_HOC_EXPOSED_DIAGNOSTIC",
        "correction": {
            "prior_plus_467r_classification": "RERISKED_SIZING_DIAGNOSTIC_NOT_TRUE_NEGATION",
            "original_quantity_frozen_before_new_path_resolution": True,
            "quantity_recalculation_after_inversion": False,
            "quantity_cap_or_scaling": False,
        },
        "population": {
            **population,
            "direction_flips": dict(sorted(direction_flips.items())),
            "true_negated_identities": [str(row["event_identity"]) for row in inverted],
            "true_negated_identities_sha256": canonical_hash(
                [str(row["event_identity"]) for row in inverted]
            ),
            "complete_execution_identities": [
                str(row["event_identity"])
                for row in primary
                if row["mechanically_executable"]
            ],
            "complete_execution_identities_sha256": canonical_hash(
                [
                    str(row["event_identity"])
                    for row in primary
                    if row["mechanically_executable"]
                ]
            ),
        },
        "frozen_quantity_rows": quantity_rows,
        "mapping": {
            "long_becomes_short": True,
            "short_becomes_long": True,
            "original_absolute_tp_becomes_new_sl": True,
            "original_absolute_sl_becomes_new_tp": True,
            "same_original_quantity": True,
            "same_decision_latency_deadline_costs_and_overlap": True,
            "remaining_214_plans_unchanged": True,
            "alternative_permitted": False,
        },
        "original_exposed_continuation": original_final["summary"]["by_event_class"][
            "CONTINUATION_REFRESH"
        ],
        "rerisked_sizing_diagnostic_continuation": rerisked_final[
            "inverted_continuation"
        ],
        "synthetic_proof": checked["synthetic_proof"],
        "predecessor": {
            "original_freeze_sha256": checked["original_freeze_sha256"],
            "original_seal_sha256": checked["original_seal_sha256"],
            "rerisked_seal_sha256": checked["rerisked_seal_sha256"],
            "original_freeze": v2_runner.file_record(original.FREEZE),
            "original_primary": v2_runner.file_record(original.PRIMARY),
            "original_reference": v2_runner.file_record(original.REFERENCE),
            "original_final": v2_runner.file_record(original.FINAL),
            "original_seal": v2_runner.file_record(original.SEAL),
            "rerisked_final": v2_runner.file_record(RERISKED_FINAL),
            "rerisked_seal": v2_runner.file_record(RERISKED_SEAL),
        },
        "governing_files": [
            v2_runner.file_record(path)
            for path in (
                CONTRACT,
                IMPLEMENTATION,
                TESTS,
                RUNNER,
                inversion.IMPLEMENTATION,
                inversion.RUNNER,
                original.IMPLEMENTATION,
                original.RUNNER,
                v2_runner.OUTCOME_IMPLEMENTATION,
            )
        ],
        "source_records": original_freeze["source_records"],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    v2_runner.write_json(FREEZE, payload)
    print(
        json.dumps(
            {
                "status": "FROZEN_TRUE_NEGATION_FIXED_QUANTITY",
                "continuation_true_negated": 434,
                "non_continuation_unchanged": 214,
                "quantity_min": payload["population"]["fixed_original_quantity_min"],
                "quantity_max": payload["population"]["fixed_original_quantity_max"],
                "tests": checked["synthetic_proof"]["passed"],
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
    for record in frozen["predecessor"].values():
        if isinstance(record, dict) and "path" in record:
            v2_runner.verify_file_record(record)
    original_state = original.verify_freeze()
    original_seal = v2_runner.verify_canonical_seal(original.SEAL)
    rerisked_seal = v2_runner.verify_canonical_seal(RERISKED_SEAL)
    v2_runner.require(
        original_state["freeze_sha256"]
        == frozen["predecessor"]["original_freeze_sha256"],
        "Original freeze differs",
    )
    v2_runner.require(
        original_seal["seal_sha256"]
        == frozen["predecessor"]["original_seal_sha256"],
        "Original seal differs",
    )
    v2_runner.require(
        rerisked_seal["seal_sha256"]
        == frozen["predecessor"]["rerisked_seal_sha256"],
        "Re-risked diagnostic seal differs",
    )
    return frozen


def concentration_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    continuation = [
        row
        for row in rows
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
        and row["event_class"] == "CONTINUATION_REFRESH"
    ]
    ordered = sorted(continuation, key=lambda row: float(row["net_r50"]), reverse=True)
    values = [float(row["net_r50"]) for row in ordered]
    quantities = [int(row["result"]["execution"]["quantity_ounces"]) for row in continuation]
    stop_exposures = [
        float(row["result"]["execution"]["displayed_planned_risk_usd"])
        for row in continuation
    ]
    total = sum(values)
    largest = ordered[0]
    top_five = sum(values[:5])
    return {
        "largest_trade": {
            "event_identity": largest["event_identity"],
            "trading_date_utc": largest["trading_date_utc"],
            "direction": largest["direction"],
            "net_r50": float(largest["net_r50"]),
            "quantity_ounces": int(largest["result"]["execution"]["quantity_ounces"]),
            "displayed_stop_exposure_usd": float(
                largest["result"]["execution"]["displayed_planned_risk_usd"]
            ),
        },
        "top_five_net_r50": top_five,
        "net_r50_excluding_top_five": total - top_five,
        "top_five_share_of_net": None if abs(total) <= 1e-12 else top_five / total,
        "maximum_original_quantity_ounces": max(quantities),
        "p99_original_quantity_ounces": sorted(quantities)[
            math.ceil(0.99 * len(quantities)) - 1
        ],
        "maximum_inverted_stop_exposure_usd": max(stop_exposures),
        "median_inverted_stop_exposure_usd": statistics.median(stop_exposures),
        "post_fill_geometry_invalid": sum(
            row["result"]["execution"]["resolution"]
            == "POST_FILL_GEOMETRY_INVALID"
            for row in continuation
        ),
    }


def run_side(side: str, frozen: dict[str, Any]) -> dict[str, Any]:
    old_execution = original_execution_map(side)
    old_results = original_result_map(side)
    compiled = load_population(side)
    population = assert_population(compiled, old_execution)
    v2_runner.require(
        [row["event_identity"] for row in compiled if row["continuation_directly_inverted"]]
        == frozen["population"]["true_negated_identities"],
        f"{side} true-negated identities differ",
    )
    v2_runner.require(
        population["quantity_rows_sha256"]
        == frozen["population"]["quantity_rows_sha256"],
        f"{side} frozen quantities differ",
    )
    streams = source.load_streams(side)
    rows = execute_every_executable(
        compiled, streams, resolve_plan_fixed_original_quantity
    )
    executed = [
        row
        for row in rows
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    ]
    v2_runner.require(len(executed) == 648, f"{side} did not execute all 648 plans")
    continuation = [row for row in executed if row["event_class"] == "CONTINUATION_REFRESH"]
    unchanged = [row for row in executed if row["event_class"] != "CONTINUATION_REFRESH"]
    v2_runner.require(len(continuation) == 434, f"{side} continuation count differs")
    v2_runner.require(len(unchanged) == 214, f"{side} unchanged count differs")
    for row in continuation:
        execution = row["result"]["execution"]
        old = old_execution[str(row["event_identity"])]
        v2_runner.require(
            int(execution["quantity_ounces"]) == int(old["quantity_ounces"]),
            f"{side} execution quantity changed: {row['event_identity']}",
        )
        v2_runner.require(
            execution["quantity_recalculated_after_inversion"] is False,
            f"{side} re-sized an inverted trade: {row['event_identity']}",
        )
    for row in unchanged:
        old = old_results[str(row["event_identity"])]
        v2_runner.require(
            row["result"] == old["result"] and float(row["net_r50"]) == float(old["net_r50"]),
            f"{side} changed a non-continuation execution: {row['event_identity']}",
        )
    diagnostic = matched_nonoverlap_diagnostic(rows)
    replacement = summarize(rows, diagnostic)
    continuation_values = [float(row["net_r50"]) for row in continuation]
    unchanged_values = [float(row["net_r50"]) for row in unchanged]
    payload: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_TRUE_NEGATION_FIXED_QUANTITY_V1_SIDE_1_0",
        "side": side,
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
        "nonoverlap_diagnostic_rows": diagnostic,
        "nonoverlap_diagnostic_sha256": canonical_hash(diagnostic),
        "replacement_portfolio": replacement,
        "replacement_portfolio_sha256": canonical_hash(replacement),
        "true_negated_continuation": economic_summary(continuation_values),
        "unchanged_non_continuation": economic_summary(unchanged_values),
        "quantity_and_concentration": concentration_summary(rows),
        "quantity_and_concentration_sha256": canonical_hash(concentration_summary(rows)),
        "all_434_original_quantities_preserved": True,
        "all_214_non_continuation_results_exact": True,
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def ledger_csv(rows: list[dict[str, Any]]) -> str:
    handle = io.StringIO(newline="")
    fields = [
        "trading_date_utc",
        "event_identity",
        "decision_at",
        "direction",
        "event_class",
        "entry",
        "stop",
        "target",
        "quantity_ounces",
        "original_displayed_planned_risk_usd",
        "inverted_displayed_stop_risk_usd",
        "quantity_recalculated_after_inversion",
        "resolution",
        "fill_at",
        "exit_at",
        "net_r50",
        "net_pnl_usd",
    ]
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        if row["execution_disposition"] != "EXECUTED_UNRESTRICTED_ALL_SIGNALS":
            continue
        result = row["result"]
        execution = result["execution"]
        inverted = row["event_class"] == "CONTINUATION_REFRESH"
        writer.writerow(
            {
                "trading_date_utc": row["trading_date_utc"],
                "event_identity": row["event_identity"],
                "decision_at": row["decision_at"],
                "direction": row["direction"],
                "event_class": row["event_class"],
                "entry": result["entry"],
                "stop": result["stop"],
                "target": result["target"],
                "quantity_ounces": execution["quantity_ounces"],
                "original_displayed_planned_risk_usd": execution.get(
                    "original_displayed_planned_risk_usd",
                    execution["displayed_planned_risk_usd"],
                ),
                "inverted_displayed_stop_risk_usd": (
                    execution["displayed_planned_risk_usd"] if inverted else ""
                ),
                "quantity_recalculated_after_inversion": (
                    execution.get("quantity_recalculated_after_inversion", False)
                    if inverted
                    else ""
                ),
                "resolution": execution["resolution"],
                "fill_at": execution["fill_at"],
                "exit_at": execution["exit_at"],
                "net_r50": execution["net_r50"],
                "net_pnl_usd": execution["net_pnl_usd"],
            }
        )
    return handle.getvalue()


def pf(row: dict[str, Any]) -> str:
    return "inf" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"


def report_markdown(final: dict[str, Any]) -> str:
    original_row = final["original_continuation"]
    rerisked = final["rerisked_sizing_diagnostic_continuation"]
    true = final["true_negated_continuation"]
    unchanged = final["unchanged_non_continuation"]
    portfolio = final["replacement_portfolio"]
    total = portfolio["all_executable_signals"]
    concentration = final["quantity_and_concentration"]
    lines = [
        "# Gold Continuation-Refresh True Negation Fixed-Quantity Exposed Diagnostic V1 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "This is the requested strategy negation. Each of the 434 continuation trades retained its original sealed whole-ounce quantity; direction reversed, TP became SL, and SL became TP. No trade was re-sized against the new stop. The other 214 trades were unchanged.",
        "",
        "| Track | Trades | Win rate | Net R | PnL USD | PF | Max DD R |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Original continuation | {original_row['trades']} | {original_row['win_rate'] * 100:.2f}% | {original_row['net_r50']:+.4f} | ${original_row['net_pnl_usd']:+.2f} | {pf(original_row)} | {original_row['maximum_drawdown_r50']:.4f} |",
        f"| Prior re-risked sizing diagnostic, not the answer | {rerisked['trades']} | {rerisked['win_rate'] * 100:.2f}% | {rerisked['net_r50']:+.4f} | ${rerisked['net_pnl_usd']:+.2f} | {pf(rerisked)} | {rerisked['maximum_drawdown_r50']:.4f} |",
        f"| True-negated continuation, fixed original quantity | {true['trades']} | {true['win_rate'] * 100:.2f}% | {true['net_r50']:+.4f} | ${true['net_pnl_usd']:+.2f} | {pf(true)} | {true['maximum_drawdown_r50']:.4f} |",
        f"| Unchanged non-continuation | {unchanged['trades']} | {unchanged['win_rate'] * 100:.2f}% | {unchanged['net_r50']:+.4f} | ${unchanged['net_pnl_usd']:+.2f} | {pf(unchanged)} | {unchanged['maximum_drawdown_r50']:.4f} |",
        f"| Complete replacement portfolio | {total['trades']} | {total['win_rate'] * 100:.2f}% | {total['net_r50']:+.4f} | ${total['net_pnl_usd']:+.2f} | {pf(total)} | {total['maximum_drawdown_r50']:.4f} |",
        "",
        "## Fixed-quantity proof",
        "",
        f"- All **434/434** continuation quantities matched the original sealed executions exactly.",
        f"- Quantity range: **{final['quantity_freeze']['fixed_original_quantity_min']} to {final['quantity_freeze']['fixed_original_quantity_max']} ounces**; prior false headline used up to 5,000 ounces.",
        f"- Maximum actual inverted displayed stop exposure: **${concentration['maximum_inverted_stop_exposure_usd']:.2f}**. This was reported, not normalized or capped.",
        f"- Largest true-negated trade: **{concentration['largest_trade']['net_r50']:+.4f}R**, {concentration['largest_trade']['quantity_ounces']} ounces.",
        f"- Top five: **{concentration['top_five_net_r50']:+.4f}R**; result excluding them: **{concentration['net_r50_excluding_top_five']:+.4f}R**.",
        "",
        "## Replacement portfolio by month",
        "",
        "| Month | Trades | Win rate | Net R | PnL USD | PF |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for month, row in portfolio["by_month"].items():
        lines.append(
            f"| {month} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | ${row['net_pnl_usd']:+.2f} | {pf(row)} |"
        )
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "- Independent primary and reference plans, fixed quantities, executions, summaries, and checksums matched exactly.",
            "- The unchanged 214 executions matched the original sealed results exactly.",
            "- No cap, scale, re-sizing, filter, alternate inversion, new date, 2025, or 2026 was used.",
            "- This remains a post-hoc exposed diagnostic with zero validation credit.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    primary = run_side("primary", frozen)
    print("primary true-negation pass complete: 648 trades", flush=True)
    reference = run_side("reference", frozen)
    print("reference true-negation pass complete: 648 trades", flush=True)
    v2_runner.require(primary["rows"] == reference["rows"], "Primary/reference executions differ")
    v2_runner.require(
        primary["nonoverlap_diagnostic_rows"] == reference["nonoverlap_diagnostic_rows"],
        "Primary/reference overlap diagnostics differ",
    )
    v2_runner.require(
        primary["replacement_portfolio"] == reference["replacement_portfolio"],
        "Primary/reference portfolio summaries differ",
    )
    v2_runner.require(
        primary["quantity_and_concentration"] == reference["quantity_and_concentration"],
        "Primary/reference quantity diagnostics differ",
    )
    final: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_TRUE_NEGATION_FIXED_QUANTITY_V1_FINAL_1_0",
        "verdict": "COMPLETE_TRUE_NEGATION_FIXED_QUANTITY_EXPOSED_DIAGNOSTIC_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "original_continuation": frozen["original_exposed_continuation"],
        "rerisked_sizing_diagnostic_continuation": frozen[
            "rerisked_sizing_diagnostic_continuation"
        ],
        "true_negated_continuation": primary["true_negated_continuation"],
        "unchanged_non_continuation": primary["unchanged_non_continuation"],
        "replacement_portfolio": primary["replacement_portfolio"],
        "quantity_freeze": {
            key: value
            for key, value in frozen["population"].items()
            if key.startswith("fixed_original_quantity")
            or key.startswith("quantity_recalculation")
        },
        "quantity_and_concentration": primary["quantity_and_concentration"],
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
    v2_runner.write_text(LEDGER, ledger_csv(primary["rows"]))
    v2_runner.write_text(REPORT, report_markdown(final))
    certification: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_TRUE_NEGATION_FIXED_QUANTITY_V1_CERTIFICATION_1_0",
        "completed_at": v2_runner.now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "continuation_exact_434": final["true_negated_continuation"]["trades"] == 434,
            "non_continuation_exact_214": final["unchanged_non_continuation"]["trades"] == 214,
            "replacement_exact_648": final["replacement_portfolio"]["all_executable_signals"]["trades"] == 648,
            "all_original_quantities_preserved": primary["all_434_original_quantities_preserved"],
            "no_quantity_recalculation": frozen["population"]["quantity_recalculation_count"] == 0,
            "all_non_continuation_results_exact": primary["all_214_non_continuation_results_exact"],
            "maximum_quantity_is_original_86_not_5000": final["quantity_and_concentration"]["maximum_original_quantity_ounces"] == 86,
            "primary_reference_exact": True,
            "no_alternative_tested": True,
            "fresh_periods_locked": True,
            "no_charge": True,
        },
        "output_records": [
            v2_runner.file_record(path)
            for path in (PRIMARY, REFERENCE, FINAL, LEDGER, REPORT)
        ],
    }
    v2_runner.require(all(certification["gates"].values()), "Certification gate failed")
    certification["certification_sha256"] = canonical_hash(certification)
    v2_runner.write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_REFRESH_TRUE_NEGATION_FIXED_QUANTITY_V1_SEAL_1_0",
        "sealed_at": v2_runner.now(),
        "verdict": final["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [
            v2_runner.file_record(path)
            for path in (FREEZE, PRIMARY, REFERENCE, FINAL, LEDGER, CERTIFICATION, REPORT)
        ],
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
                "true_negated_continuation": final["true_negated_continuation"],
                "unchanged_non_continuation": final["unchanged_non_continuation"],
                "replacement_portfolio": final["replacement_portfolio"],
                "quantity_and_concentration": final["quantity_and_concentration"],
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
    parser.add_argument("action", choices=("preflight", "freeze", "run", "all"))
    args = parser.parse_args()
    if args.action == "preflight":
        print(json.dumps(preflight(), indent=2), flush=True)
        return
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"run", "all"}:
        run()


if __name__ == "__main__":
    main()
