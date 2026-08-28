#!/usr/bin/env python3
"""Run the single frozen exposed liquidity-hierarchy hybrid benchmark."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import runpy
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import run_gold_auction_all_transition_executable_multi_opportunity_v2 as v2_runner  # noqa: E402
import run_gold_auction_all_transition_executable_multi_opportunity_v2_r1 as original  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
import run_gold_continuation_refresh_true_negation_fixed_quantity_v1 as negated  # noqa: E402
from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 import (  # noqa: E402
    economic_summary,
    execute_every_executable,
    matched_nonoverlap_diagnostic,
    summarize,
)
from gold_intel.analytics.auction_liquidity_hierarchy_hybrid_router_v1 import (  # noqa: E402
    RULESET,
    resolve_fixed_original_quantity,
    resolve_risk_controlled,
    route_population,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


CONTRACT = ROOT / "GOLD_AUCTION_LIQUIDITY_HIERARCHY_HYBRID_ROUTER_EXPOSED_BENCHMARK_V1.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_liquidity_hierarchy_hybrid_router_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_liquidity_hierarchy_hybrid_router_v1.py"
RUNNER = Path(__file__).resolve()

ATTRIBUTION_ROOT = ROOT / "research_artifacts" / "gold_continuation_true_negation_matched_case_attribution_v1"
ATTRIBUTION_FINAL = ATTRIBUTION_ROOT / "final_result.json"
ATTRIBUTION_SEAL = ATTRIBUTION_ROOT / "seal.json"
NEGATED_FINAL = negated.FINAL
NEGATED_SEAL = negated.SEAL

OUT = ROOT / "research_artifacts" / "gold_auction_liquidity_hierarchy_hybrid_router_exposed_benchmark_v1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
TRACK_A_LEDGER = OUT / "track_a_fixed_original_quantity_ledger.csv"
TRACK_B_LEDGER = OUT / "track_b_no_upsize_50_usd_risk_ledger.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_AUCTION_LIQUIDITY_HIERARCHY_HYBRID_ROUTER_V1_REPORT.md"

BENCHMARK_NET_R50 = 45.772787857150256
BENCHMARK_PROFIT_FACTOR = 1.2406708931572503
BENCHMARK_MAX_DRAWDOWN_R50 = 21.758157857141946
EPSILON = 1e-9


def synthetic_proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    tests = sorted(
        name
        for name, value in namespace.items()
        if name.startswith("test_") and callable(value)
    )
    v2_runner.require(len(tests) == 7, f"Unexpected hybrid-router tests: {tests}")
    for name in tests:
        namespace[name]()
    payload = {"passed": len(tests), "tests": tests}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def load_original_execution_map(side: str) -> dict[str, dict[str, Any]]:
    path = original.PRIMARY if side == "primary" else original.REFERENCE
    payload = v2_runner.verify_canonical_payload(path, "payload_sha256")
    return {
        str(row["event_identity"]): dict(row["result"]["execution"])
        for row in payload["rows"]
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    }


def load_negated_execution_map(side: str) -> dict[str, dict[str, Any]]:
    path = negated.PRIMARY if side == "primary" else negated.REFERENCE
    payload = v2_runner.verify_canonical_payload(path, "payload_sha256")
    return {
        str(row["event_identity"]): dict(row["result"]["execution"])
        for row in payload["rows"]
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    }


def load_routed(side: str) -> list[dict[str, Any]]:
    return route_population(original.load_compiled(side))


def routing_record(row: Mapping[str, Any]) -> dict[str, Any]:
    plan = row.get("plan")
    route = None if plan is None else plan.get("hybrid_route")
    return {
        "event_identity": str(row["event_identity"]),
        "mechanically_executable": bool(row["mechanically_executable"]),
        "event_class": str(row["event_class"]),
        "context_family": str(row["context_family"]),
        "hybrid_route_reason": str(row["hybrid_route_reason"]),
        "hybrid_route_action": str(row["hybrid_route_action"]),
        "original_direction": str(row["original_direction"]),
        "selected_direction": str(row["selected_direction"]),
        "selected_plan_sha256": None if plan is None else str(plan["plan_sha256"]),
        "original_quantity_ounces": row["original_quantity_ounces"],
        "risk_controlled_quantity_ounces": row["risk_controlled_quantity_ounces"],
        "risk_controlled_disposition": str(row["risk_controlled_disposition"]),
        "selected_stop_distance": None if route is None else float(route["selected_stop_distance"]),
        "fixed_original_stop_exposure_usd": None
        if route is None
        else float(route["fixed_original_stop_exposure_usd"]),
        "risk_controlled_stop_exposure_usd": None
        if route is None
        else float(route["risk_controlled_stop_exposure_usd"]),
    }


def assert_population(rows: Sequence[Mapping[str, Any]], side: str) -> dict[str, Any]:
    v2_runner.require(len(rows) == 729, f"{side}: expected 729 transitions")
    v2_runner.require(
        len({str(row["event_identity"]) for row in rows}) == 729,
        f"{side}: duplicate transition identity",
    )
    executable = [row for row in rows if row["mechanically_executable"]]
    continuation = [row for row in executable if row["event_class"] == "CONTINUATION_REFRESH"]
    non_continuation = [row for row in executable if row["event_class"] != "CONTINUATION_REFRESH"]
    v2_runner.require(len(executable) == 648, f"{side}: expected 648 executable plans")
    v2_runner.require(len(continuation) == 434, f"{side}: expected 434 continuation plans")
    v2_runner.require(len(non_continuation) == 214, f"{side}: expected 214 non-continuation plans")
    originals = original.load_compiled(side)
    v2_runner.require(
        [row["event_identity"] for row in rows] == [row["event_identity"] for row in originals],
        f"{side}: routed population identity/order differs",
    )
    original_by_id = {str(row["event_identity"]): row for row in originals}
    risk_infeasible: list[str] = []
    max_risk_controlled_exposure = 0.0
    for row in executable:
        identity = str(row["event_identity"])
        old = original_by_id[identity]
        old_plan = old["plan"]
        selected = row["plan"]
        v2_runner.require(
            int(row["risk_controlled_quantity_ounces"]) <= int(row["original_quantity_ounces"]),
            f"{side}: quantity increased after routing: {identity}",
        )
        selected_exposure = abs(float(selected["entry"]) - float(selected["stop"])) * int(
            row["risk_controlled_quantity_ounces"]
        )
        max_risk_controlled_exposure = max(max_risk_controlled_exposure, selected_exposure)
        if row["risk_controlled_disposition"] == "RISK_INFEASIBLE_WHOLE_OUNCE":
            v2_runner.require(
                int(row["risk_controlled_quantity_ounces"]) == 0,
                f"{side}: infeasible identity has nonzero quantity: {identity}",
            )
            risk_infeasible.append(identity)
        else:
            v2_runner.require(
                selected_exposure <= 50.0 + EPSILON,
                f"{side}: risk-controlled exposure exceeds $50: {identity}",
            )
        if row["event_class"] != "CONTINUATION_REFRESH":
            v2_runner.require(selected == old_plan, f"{side}: non-continuation plan changed: {identity}")
            continue
        if row["hybrid_route_action"] == "PRESERVE":
            v2_runner.require(
                str(selected["direction"]) == str(old_plan["direction"])
                and float(selected["stop"]) == float(old_plan["stop"])
                and float(selected["target"]["level"]) == float(old_plan["target"]["level"]),
                f"{side}: preserved geometry changed: {identity}",
            )
        else:
            v2_runner.require(
                str(selected["direction"]) != str(old_plan["direction"])
                and float(selected["stop"]) == float(old_plan["target"]["level"])
                and float(selected["target"]["level"]) == float(old_plan["stop"]),
                f"{side}: negated geometry differs: {identity}",
            )
    records = [routing_record(row) for row in rows]
    route_counts = dict(sorted(Counter(row["hybrid_route_reason"] for row in continuation).items()))
    action_counts = dict(sorted(Counter(row["hybrid_route_action"] for row in continuation).items()))
    return {
        "events": len(rows),
        "executable": len(executable),
        "continuation": len(continuation),
        "non_continuation": len(non_continuation),
        "continuation_route_counts": route_counts,
        "continuation_action_counts": action_counts,
        "risk_feasible_executable": len(executable) - len(risk_infeasible),
        "risk_infeasible_count": len(risk_infeasible),
        "risk_infeasible_identities": risk_infeasible,
        "max_risk_controlled_stop_exposure_usd": max_risk_controlled_exposure,
        "routing_records": records,
        "routing_records_sha256": canonical_hash(records),
    }


def preflight() -> dict[str, Any]:
    original_freeze = original.verify_freeze()
    original_seal = v2_runner.verify_canonical_seal(original.SEAL)
    negated_seal = v2_runner.verify_canonical_seal(NEGATED_SEAL)
    attribution_seal = v2_runner.verify_canonical_seal(ATTRIBUTION_SEAL)
    negated_final = v2_runner.verify_canonical_payload(NEGATED_FINAL, "final_sha256")
    attribution_final = v2_runner.verify_canonical_payload(ATTRIBUTION_FINAL, "final_sha256")
    benchmark = negated_final["replacement_portfolio"]["all_executable_signals"]
    v2_runner.require(
        math.isclose(float(benchmark["net_r50"]), BENCHMARK_NET_R50, abs_tol=1e-12)
        and math.isclose(float(benchmark["profit_factor"]), BENCHMARK_PROFIT_FACTOR, abs_tol=1e-12)
        and math.isclose(
            float(benchmark["maximum_drawdown_r50"]),
            BENCHMARK_MAX_DRAWDOWN_R50,
            abs_tol=1e-12,
        ),
        "Sealed +45.7728R benchmark differs",
    )
    primary = assert_population(load_routed("primary"), "primary")
    reference = assert_population(load_routed("reference"), "reference")
    v2_runner.require(
        primary["routing_records"] == reference["routing_records"],
        "Primary/reference pre-outcome routes differ",
    )
    proof = synthetic_proof()
    payload = {
        "status": "PASS_HYBRID_ROUTER_PREOUTCOME_PREFLIGHT",
        "benchmark": benchmark,
        "population": primary,
        "synthetic_proof": proof,
        "predecessor_hashes": {
            "original_freeze_sha256": original_freeze["freeze_sha256"],
            "original_seal_sha256": original_seal["seal_sha256"],
            "true_negation_seal_sha256": negated_seal["seal_sha256"],
            "attribution_seal_sha256": attribution_seal["seal_sha256"],
            "attribution_final_sha256": attribution_final["final_sha256"],
        },
    }
    payload["preflight_sha256"] = canonical_hash(payload)
    return payload


def freeze() -> None:
    v2_runner.require(not OUT.exists(), f"Output directory already exists: {OUT}")
    v2_runner.require(not REPORT.exists(), f"Report already exists: {REPORT}")
    checked = preflight()
    population = dict(checked["population"])
    routing_records = population.pop("routing_records")
    original_freeze = original.verify_freeze()
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_LIQUIDITY_HIERARCHY_HYBRID_ROUTER_V1_FREEZE_1_0",
        "frozen_at": v2_runner.now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_POST_HOC_EXPOSED_BENCHMARK",
        "single_ordered_policy": [
            "RANGE_CONTEXT_PRESERVE",
            "H4_DESTINATION_PRESERVE",
            "LOCAL_M15_LEVEL_CONFIRMS_DESTINATION_PRESERVE",
            "DESTINATION_AGE_LT_240M_PRESERVE",
            "H1_UNCONFIRMED_AGE_GTE_240M_NEGATE",
        ],
        "policy_constraints": {
            "target_fresh_minutes_strictly_less_than": 240,
            "macro_used": False,
            "outcomes_used": False,
            "case_or_date_exception_used": False,
            "multiple_simultaneous_setups_retained": True,
            "daily_cap": False,
            "wait_for_resolution": False,
            "alternative_or_retune_permitted": False,
        },
        "tracks": {
            "TRACK_A_FIXED_ORIGINAL_QUANTITY": {
                "quantity": "sealed original whole-ounce quantity",
                "risk_cap_after_routing": None,
            },
            "TRACK_B_NO_UPSIZE_50_USD_RISK": {
                "quantity": "min(original_quantity, floor(50 / selected_stop_distance))",
                "displayed_stop_risk_cap_usd": 50.0,
                "whole_ounce_minimum": 1,
            },
        },
        "benchmark": {
            "net_r50": BENCHMARK_NET_R50,
            "profit_factor": BENCHMARK_PROFIT_FACTOR,
            "maximum_drawdown_r50": BENCHMARK_MAX_DRAWDOWN_R50,
            "source": checked["benchmark"],
        },
        "population": population,
        "frozen_routing_records": routing_records,
        "synthetic_proof": checked["synthetic_proof"],
        "predecessor": {
            **checked["predecessor_hashes"],
            "original_freeze": v2_runner.file_record(original.FREEZE),
            "original_primary": v2_runner.file_record(original.PRIMARY),
            "original_reference": v2_runner.file_record(original.REFERENCE),
            "original_seal": v2_runner.file_record(original.SEAL),
            "true_negation_final": v2_runner.file_record(NEGATED_FINAL),
            "true_negation_primary": v2_runner.file_record(negated.PRIMARY),
            "true_negation_reference": v2_runner.file_record(negated.REFERENCE),
            "true_negation_seal": v2_runner.file_record(NEGATED_SEAL),
            "attribution_final": v2_runner.file_record(ATTRIBUTION_FINAL),
            "attribution_seal": v2_runner.file_record(ATTRIBUTION_SEAL),
        },
        "governing_files": [
            v2_runner.file_record(path)
            for path in (
                CONTRACT,
                IMPLEMENTATION,
                TESTS,
                RUNNER,
                original.IMPLEMENTATION,
                original.RUNNER,
                negated.IMPLEMENTATION,
                negated.RUNNER,
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
                "status": "FROZEN_SINGLE_HYBRID_POLICY",
                "route_counts": population["continuation_route_counts"],
                "risk_feasible": population["risk_feasible_executable"],
                "risk_infeasible": population["risk_infeasible_count"],
                "synthetic_tests": checked["synthetic_proof"]["passed"],
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
    negated_seal = v2_runner.verify_canonical_seal(NEGATED_SEAL)
    attribution_seal = v2_runner.verify_canonical_seal(ATTRIBUTION_SEAL)
    v2_runner.require(
        original_state["freeze_sha256"] == frozen["predecessor"]["original_freeze_sha256"],
        "Original freeze differs",
    )
    v2_runner.require(
        original_seal["seal_sha256"] == frozen["predecessor"]["original_seal_sha256"],
        "Original seal differs",
    )
    v2_runner.require(
        negated_seal["seal_sha256"] == frozen["predecessor"]["true_negation_seal_sha256"],
        "True-negation seal differs",
    )
    v2_runner.require(
        attribution_seal["seal_sha256"] == frozen["predecessor"]["attribution_seal_sha256"],
        "Attribution seal differs",
    )
    for side in ("primary", "reference"):
        checked = assert_population(load_routed(side), side)
        v2_runner.require(
            checked["routing_records"] == frozen["frozen_routing_records"],
            f"{side}: frozen routes differ",
        )
    return frozen


def execute_risk_controlled_population(
    compiled_rows: Sequence[Mapping[str, Any]],
    streams: Mapping[str, Mapping[str, Any]],
    resolver: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in compiled_rows:
        payload = {key: value for key, value in row.items() if key != "plan"}
        if not row["mechanically_executable"]:
            payload.update(
                {
                    "execution_disposition": "NOT_EXECUTABLE_HARD_REASON",
                    "result": None,
                    "net_r50": 0.0,
                }
            )
        elif row["risk_controlled_disposition"] == "RISK_INFEASIBLE_WHOLE_OUNCE":
            payload.update(
                {
                    "execution_disposition": "RISK_INFEASIBLE_WHOLE_OUNCE",
                    "result": None,
                    "net_r50": 0.0,
                }
            )
        else:
            alias = str(row["case_alias"])
            v2_runner.require(alias in streams, f"Missing daily stream: {alias}")
            result = resolver(dict(row["plan"]), list(streams[alias]["timeframes"]["1m"]))
            payload.update(
                {
                    "execution_disposition": "EXECUTED_UNRESTRICTED_ALL_SIGNALS",
                    "result": result,
                    "net_r50": float(result["execution"]["net_r50"]),
                }
            )
        payload["execution_row_sha256"] = canonical_hash(payload)
        output.append(payload)
    return output


def grouped_economics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["execution_disposition"] != "EXECUTED_UNRESTRICTED_ALL_SIGNALS":
            continue
        groups[str(row[key])].append(float(row["net_r50"]))
    return {name: economic_summary(groups[name]) for name in sorted(groups)}


def track_diagnostics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    executed = [
        row
        for row in rows
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    ]
    quantities = [int(row["result"]["execution"]["quantity_ounces"]) for row in executed]
    risks = [float(row["result"]["execution"]["displayed_planned_risk_usd"]) for row in executed]
    return {
        "execution_dispositions": dict(sorted(Counter(row["execution_disposition"] for row in rows).items())),
        "risk_infeasible_identities": [
            str(row["event_identity"])
            for row in rows
            if row["execution_disposition"] == "RISK_INFEASIBLE_WHOLE_OUNCE"
        ],
        "maximum_quantity_ounces": max(quantities),
        "maximum_displayed_stop_risk_usd": max(risks),
        "minimum_displayed_stop_risk_usd": min(risks),
        "resolution_counts": dict(
            sorted(Counter(row["result"]["execution"]["resolution"] for row in executed).items())
        ),
        "by_route_reason": grouped_economics(executed, "hybrid_route_reason"),
        "by_route_action": grouped_economics(executed, "hybrid_route_action"),
        "by_context_family": grouped_economics(executed, "context_family"),
    }


def run_side(side: str, frozen: Mapping[str, Any]) -> dict[str, Any]:
    compiled = load_routed(side)
    population = assert_population(compiled, side)
    v2_runner.require(
        population["routing_records"] == frozen["frozen_routing_records"],
        f"{side}: route identities changed after freeze",
    )
    streams = source.load_streams(side)
    track_a_rows = execute_every_executable(
        compiled, streams, resolve_fixed_original_quantity
    )
    track_b_rows = execute_risk_controlled_population(
        compiled, streams, resolve_risk_controlled
    )
    track_a_executed = [
        row
        for row in track_a_rows
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    ]
    track_b_executed = [
        row
        for row in track_b_rows
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    ]
    v2_runner.require(len(track_a_executed) == 648, f"{side}: Track A did not execute 648")
    v2_runner.require(
        len(track_b_executed) == int(frozen["population"]["risk_feasible_executable"]),
        f"{side}: Track B risk-feasible count differs",
    )
    old_execution = load_original_execution_map(side)
    negated_execution = load_negated_execution_map(side)
    for row in track_a_executed:
        expected = (
            negated_execution[str(row["event_identity"])]
            if row["hybrid_route_action"] == "NEGATE"
            else old_execution[str(row["event_identity"])]
        )
        v2_runner.require(
            row["result"]["execution"] == expected,
            f"{side}: Track A did not reproduce frozen source execution: {row['event_identity']}",
        )
    for row in track_b_executed:
        execution = row["result"]["execution"]
        v2_runner.require(
            int(execution["quantity_ounces"]) <= int(row["original_quantity_ounces"]),
            f"{side}: Track B upsized: {row['event_identity']}",
        )
        v2_runner.require(
            float(execution["displayed_planned_risk_usd"]) <= 50.0 + EPSILON,
            f"{side}: Track B displayed risk exceeded $50: {row['event_identity']}",
        )
    track_a_overlap = matched_nonoverlap_diagnostic(track_a_rows)
    track_b_overlap = matched_nonoverlap_diagnostic(track_b_rows)
    track_a_summary = summarize(track_a_rows, track_a_overlap)
    track_b_summary = summarize(track_b_rows, track_b_overlap)
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_LIQUIDITY_HIERARCHY_HYBRID_ROUTER_V1_SIDE_1_0",
        "side": side,
        "routing_records_sha256": population["routing_records_sha256"],
        "track_a": {
            "rows": track_a_rows,
            "rows_sha256": canonical_hash(track_a_rows),
            "nonoverlap_diagnostic_rows": track_a_overlap,
            "summary": track_a_summary,
            "diagnostics": track_diagnostics(track_a_rows),
        },
        "track_b": {
            "rows": track_b_rows,
            "rows_sha256": canonical_hash(track_b_rows),
            "nonoverlap_diagnostic_rows": track_b_overlap,
            "summary": track_b_summary,
            "diagnostics": track_diagnostics(track_b_rows),
        },
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def ledger_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    handle = io.StringIO(newline="")
    fields = [
        "trading_date_utc",
        "event_identity",
        "decision_at",
        "event_class",
        "context_family",
        "route_reason",
        "route_action",
        "original_direction",
        "selected_direction",
        "execution_disposition",
        "quantity_ounces",
        "displayed_stop_risk_usd",
        "resolution",
        "fill_at",
        "exit_at",
        "net_r50",
        "net_pnl_usd",
    ]
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        execution = None if row["result"] is None else row["result"]["execution"]
        writer.writerow(
            {
                "trading_date_utc": row["trading_date_utc"],
                "event_identity": row["event_identity"],
                "decision_at": row["decision_at"],
                "event_class": row["event_class"],
                "context_family": row["context_family"],
                "route_reason": row["hybrid_route_reason"],
                "route_action": row["hybrid_route_action"],
                "original_direction": row["original_direction"],
                "selected_direction": row["selected_direction"],
                "execution_disposition": row["execution_disposition"],
                "quantity_ounces": "" if execution is None else execution["quantity_ounces"],
                "displayed_stop_risk_usd": ""
                if execution is None
                else execution["displayed_planned_risk_usd"],
                "resolution": "" if execution is None else execution["resolution"],
                "fill_at": "" if execution is None else execution["fill_at"],
                "exit_at": "" if execution is None else execution["exit_at"],
                "net_r50": row["net_r50"],
                "net_pnl_usd": "" if execution is None else execution["net_pnl_usd"],
            }
        )
    return handle.getvalue()


def pf(row: Mapping[str, Any]) -> str:
    return "inf" if row["profit_factor"] is None else f"{float(row['profit_factor']):.3f}"


def report_markdown(final: Mapping[str, Any]) -> str:
    a = final["track_a"]["summary"]["all_executable_signals"]
    b = final["track_b"]["summary"]["all_executable_signals"]
    lines = [
        "# Gold Auction Liquidity-Hierarchy Hybrid Router V1 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "This was one frozen post-hoc exposed policy. It was run once without an alternative or retune. The sealed +45.7728R result is the comparison benchmark, not an unseen validation result.",
        "",
        "| Track | Executed | Win rate | Net R | PnL USD | PF | Max DD R | Max displayed stop risk |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| A: fixed original quantity | {a['trades']} | {a['win_rate'] * 100:.2f}% | {a['net_r50']:+.4f} | ${a['net_pnl_usd']:+.2f} | {pf(a)} | {a['maximum_drawdown_r50']:.4f} | ${final['track_a']['diagnostics']['maximum_displayed_stop_risk_usd']:.2f} |",
        f"| B: no-upsize, $50 cap | {b['trades']} | {b['win_rate'] * 100:.2f}% | {b['net_r50']:+.4f} | ${b['net_pnl_usd']:+.2f} | {pf(b)} | {b['maximum_drawdown_r50']:.4f} | ${final['track_b']['diagnostics']['maximum_displayed_stop_risk_usd']:.2f} |",
        f"| Frozen complete-negation benchmark | 648 | — | {BENCHMARK_NET_R50:+.4f} | ${BENCHMARK_NET_R50 * 50:+.2f} | {BENCHMARK_PROFIT_FACTOR:.3f} | {BENCHMARK_MAX_DRAWDOWN_R50:.4f} | not risk-capped |",
        "",
        f"Track B benchmark met: **{'YES' if final['track_b_benchmark_met'] else 'NO'}**.",
        f"Risk-infeasible whole-ounce identities retained: **{len(final['track_b']['diagnostics']['risk_infeasible_identities'])}**.",
        "",
        "## Track B by month",
        "",
        "| Month | Trades | Win rate | Net R | PnL USD | PF |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for month, row in final["track_b"]["summary"]["by_month"].items():
        lines.append(
            f"| {month} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | ${row['net_pnl_usd']:+.2f} | {pf(row)} |"
        )
    lines.extend(
        [
            "",
            "## Track B route contribution",
            "",
            "| Frozen route | Trades | Net R | PF |",
            "|---|---:|---:|---:|",
        ]
    )
    for reason, row in final["track_b"]["diagnostics"]["by_route_reason"].items():
        lines.append(f"| {reason} | {row['trades']} | {row['net_r50']:+.4f} | {pf(row)} |")
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "- All 648 original executable identities were retained; no daily cap or overlap suppression was used.",
            "- Track A reproduced either the sealed original or sealed fixed-quantity negated execution for every identity.",
            "- Track B never increased quantity and never exceeded $50 displayed stop exposure.",
            "- Primary and reference routes, executions, summaries and checksums matched exactly.",
            "- No alternative policy, new data, 2025, 2026 or paid source was opened.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    primary = run_side("primary", frozen)
    print("checkpoint: primary Track A and Track B complete", flush=True)
    reference = run_side("reference", frozen)
    print("checkpoint: independent reference Track A and Track B complete", flush=True)
    for track in ("track_a", "track_b"):
        v2_runner.require(
            primary[track]["rows"] == reference[track]["rows"],
            f"Primary/reference {track} executions differ",
        )
        v2_runner.require(
            primary[track]["summary"] == reference[track]["summary"],
            f"Primary/reference {track} summaries differ",
        )
        v2_runner.require(
            primary[track]["diagnostics"] == reference[track]["diagnostics"],
            f"Primary/reference {track} diagnostics differ",
        )
    a_net = float(primary["track_a"]["summary"]["all_executable_signals"]["net_r50"])
    b_net = float(primary["track_b"]["summary"]["all_executable_signals"]["net_r50"])
    track_b_benchmark_met = b_net + EPSILON >= BENCHMARK_NET_R50
    verdict = (
        "PASS_HYBRID_NO_UPSIZE_EXPOSED_BENCHMARK_ZERO_VALIDATION_CREDIT"
        if track_b_benchmark_met
        else "REJECT_HYBRID_NO_UPSIZE_EXPOSED_BENCHMARK_ZERO_VALIDATION_CREDIT"
    )
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_LIQUIDITY_HIERARCHY_HYBRID_ROUTER_V1_FINAL_1_0",
        "verdict": verdict,
        "freeze_sha256": frozen["freeze_sha256"],
        "benchmark": frozen["benchmark"],
        "track_a": {
            "summary": primary["track_a"]["summary"],
            "diagnostics": primary["track_a"]["diagnostics"],
            "benchmark_delta_r50": a_net - BENCHMARK_NET_R50,
            "benchmark_met": a_net + EPSILON >= BENCHMARK_NET_R50,
        },
        "track_b": {
            "summary": primary["track_b"]["summary"],
            "diagnostics": primary["track_b"]["diagnostics"],
            "benchmark_delta_r50": b_net - BENCHMARK_NET_R50,
            "benchmark_met": track_b_benchmark_met,
        },
        "track_b_benchmark_met": track_b_benchmark_met,
        "primary_reference_exact": True,
        "single_policy_only": True,
        "retuned_after_result": False,
        "validation_credit": "ZERO_POST_HOC_EXPOSED_BENCHMARK",
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    final["final_sha256"] = canonical_hash(final)
    v2_runner.write_json(PRIMARY, primary)
    v2_runner.write_json(REFERENCE, reference)
    v2_runner.write_json(FINAL, final)
    v2_runner.write_text(TRACK_A_LEDGER, ledger_csv(primary["track_a"]["rows"]))
    v2_runner.write_text(TRACK_B_LEDGER, ledger_csv(primary["track_b"]["rows"]))
    v2_runner.write_text(REPORT, report_markdown(final))
    risk_infeasible_expected = frozen["population"]["risk_infeasible_identities"]
    risk_infeasible_actual = final["track_b"]["diagnostics"]["risk_infeasible_identities"]
    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_LIQUIDITY_HIERARCHY_HYBRID_ROUTER_V1_CERTIFICATION_1_0",
        "completed_at": v2_runner.now(),
        "verdict": verdict,
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "track_a_all_648_executed": final["track_a"]["summary"]["all_executable_signals"]["trades"] == 648,
            "track_b_all_risk_feasible_executed": final["track_b"]["summary"]["all_executable_signals"]["trades"]
            == frozen["population"]["risk_feasible_executable"],
            "risk_infeasible_identities_retained_exactly": risk_infeasible_actual == risk_infeasible_expected,
            "track_b_max_risk_at_most_50": final["track_b"]["diagnostics"]["maximum_displayed_stop_risk_usd"]
            <= 50.0 + EPSILON,
            "primary_reference_exact": True,
            "all_overlaps_retained": final["track_a"]["summary"]["all_executable_signals"]["trades"] == 648,
            "one_policy_only_no_retune": True,
            "fresh_periods_locked": True,
            "no_charge": True,
        },
        "economic_gate": {
            "track_b_benchmark_required_r50": BENCHMARK_NET_R50,
            "track_b_actual_r50": b_net,
            "track_b_benchmark_met": track_b_benchmark_met,
        },
        "output_records": [
            v2_runner.file_record(path)
            for path in (PRIMARY, REFERENCE, FINAL, TRACK_A_LEDGER, TRACK_B_LEDGER, REPORT)
        ],
    }
    v2_runner.require(all(certification["gates"].values()), "Integrity certification gate failed")
    certification["certification_sha256"] = canonical_hash(certification)
    v2_runner.write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_LIQUIDITY_HIERARCHY_HYBRID_ROUTER_V1_SEAL_1_0",
        "sealed_at": v2_runner.now(),
        "verdict": verdict,
        "certification_sha256": certification["certification_sha256"],
        "files": [
            v2_runner.file_record(path)
            for path in (
                FREEZE,
                PRIMARY,
                REFERENCE,
                FINAL,
                TRACK_A_LEDGER,
                TRACK_B_LEDGER,
                CERTIFICATION,
                REPORT,
            )
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
                "verdict": verdict,
                "benchmark_net_r50": BENCHMARK_NET_R50,
                "track_a": final["track_a"],
                "track_b": final["track_b"],
                "report": REPORT.relative_to(ROOT).as_posix(),
                "track_a_ledger": TRACK_A_LEDGER.relative_to(ROOT).as_posix(),
                "track_b_ledger": TRACK_B_LEDGER.relative_to(ROOT).as_posix(),
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
        checked = preflight()
        population = dict(checked["population"])
        population.pop("routing_records", None)
        print(
            json.dumps(
                {
                    "status": checked["status"],
                    "benchmark": checked["benchmark"],
                    "population": population,
                    "synthetic_proof": checked["synthetic_proof"],
                    "preflight_sha256": checked["preflight_sha256"],
                },
                indent=2,
            ),
            flush=True,
        )
        return
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"run", "all"}:
        run()


if __name__ == "__main__":
    main()
