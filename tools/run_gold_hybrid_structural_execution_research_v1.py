#!/usr/bin/env python3
"""Run the frozen 3x3 exposed structural-execution research matrix."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import runpy
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import render_gold_auction_trade_placement_examples_v1 as placement  # noqa: E402
import run_gold_auction_all_transition_executable_multi_opportunity_v2 as v2_runner  # noqa: E402
import run_gold_auction_all_transition_executable_multi_opportunity_v2_r1 as original  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
import run_gold_auction_liquidity_hierarchy_hybrid_router_v1 as hybrid  # noqa: E402
from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 import (  # noqa: E402
    economic_summary,
    matched_nonoverlap_diagnostic,
    summarize,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt  # noqa: E402
from gold_intel.analytics.hybrid_structural_execution_research_v1 import (  # noqa: E402
    ENTRY_MODES,
    EXIT_MODES,
    POLICY_IDS,
    RULESET,
    prepare_static_plan,
    resolve_prepared_plan,
)


CONTRACT = ROOT / "GOLD_HYBRID_STRUCTURAL_EXECUTION_RESEARCH_CONTRACT_V1.md"
BOOK = ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "hybrid_structural_execution_research_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_hybrid_structural_execution_research_v1.py"
RUNNER = Path(__file__).resolve()

OUT = ROOT / "research_artifacts" / "gold_hybrid_structural_execution_research_v1"
FREEZE = OUT / "preresult_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "complete_policy_trade_ledger.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_HYBRID_STRUCTURAL_EXECUTION_RESEARCH_V1_REPORT.md"

CONTROL_POLICY = "E0_CONTROL_MECHANICAL::T0_PRIMARY_LIQUIDITY_FULL"
CONTROL_NET_R50 = 21.312216428575976
BENCHMARK_NET_R50 = 45.772787857150256
BOOTSTRAP_SEED = 20260827
BOOTSTRAP_DRAWS = 5000
BONFERRONI_INTERVAL = 0.99375
EPSILON = 1e-9


def synthetic_proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    tests = sorted(
        name
        for name, value in namespace.items()
        if name.startswith("test_") and callable(value)
    )
    v2_runner.require(len(tests) == 9, f"Unexpected structural-execution tests: {tests}")
    for name in tests:
        namespace[name]()
    payload = {"passed": len(tests), "tests": tests}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def event_map(side: str) -> dict[str, dict[str, Any]]:
    path = placement.EVENTS_PRIMARY if side == "primary" else placement.EVENTS_REFERENCE
    events = v2_runner.load_json(path)["events"]
    output = {str(row["event_identity"]): dict(row) for row in events}
    v2_runner.require(len(output) == len(events), f"{side}: duplicate event identity")
    return output


def load_routed(side: str) -> list[dict[str, Any]]:
    return hybrid.load_routed(side)


def static_record(
    row: Mapping[str, Any], event: Mapping[str, Any], entry_mode: str, exit_mode: str
) -> dict[str, Any]:
    prepared = prepare_static_plan(
        row,
        event,
        entry_mode=entry_mode,
        exit_mode=exit_mode,
    )
    plan = prepared.get("plan")
    return {
        "policy_id": prepared["policy_id"],
        "event_identity": str(row["event_identity"]),
        "trading_date_utc": str(row["trading_date_utc"]),
        "mechanically_executable": bool(row["mechanically_executable"]),
        "route_action": str(row["hybrid_route_action"]),
        "route_reason": str(row["hybrid_route_reason"]),
        "disposition": str(prepared["disposition"]),
        "static_plan_sha256": None if plan is None else str(plan["plan_sha256"]),
        "target_replaced_by_local_m15": False
        if plan is None
        else bool(plan["target_replaced_by_local_m15"]),
        "partial_at_1r": False if plan is None else bool(plan["partial_at_1r"]),
    }


def static_audit(side: str) -> dict[str, Any]:
    rows = load_routed(side)
    events = event_map(side)
    v2_runner.require(len(rows) == 729, f"{side}: expected 729 routed identities")
    records: list[dict[str, Any]] = []
    for entry_mode in ENTRY_MODES:
        for exit_mode in EXIT_MODES:
            records.extend(
                static_record(row, events[str(row["event_identity"])], entry_mode, exit_mode)
                for row in rows
            )
    v2_runner.require(len(records) == 9 * 729, f"{side}: static registry cardinality differs")
    dispositions: dict[str, dict[str, int]] = {}
    local_target_counts: dict[str, int] = {}
    for identifier in POLICY_IDS:
        selected = [row for row in records if row["policy_id"] == identifier]
        dispositions[identifier] = dict(sorted(Counter(row["disposition"] for row in selected).items()))
        local_target_counts[identifier] = sum(row["target_replaced_by_local_m15"] for row in selected)
    return {
        "rows": len(rows),
        "static_records": records,
        "static_records_sha256": canonical_hash(records),
        "dispositions": dispositions,
        "local_target_counts": local_target_counts,
    }


def preflight() -> dict[str, Any]:
    hybrid_freeze = hybrid.verify_freeze()
    hybrid_seal = v2_runner.verify_canonical_seal(hybrid.SEAL)
    hybrid_final = v2_runner.verify_canonical_payload(hybrid.FINAL, "final_sha256")
    actual_control = hybrid_final["track_b"]["summary"]["all_executable_signals"]
    v2_runner.require(
        math.isclose(float(actual_control["net_r50"]), CONTROL_NET_R50, abs_tol=1e-12),
        "Sealed risk-controlled control differs",
    )
    primary = static_audit("primary")
    reference = static_audit("reference")
    v2_runner.require(
        primary["static_records"] == reference["static_records"],
        "Primary/reference static plans differ",
    )
    proof = synthetic_proof()
    payload = {
        "status": "PASS_STRUCTURAL_EXECUTION_PRERESULT_PREFLIGHT",
        "control": actual_control,
        "static_audit": primary,
        "synthetic_proof": proof,
        "hybrid_freeze_sha256": hybrid_freeze["freeze_sha256"],
        "hybrid_seal_sha256": hybrid_seal["seal_sha256"],
    }
    payload["preflight_sha256"] = canonical_hash(payload)
    return payload


def freeze() -> None:
    v2_runner.require(not OUT.exists(), f"Output directory already exists: {OUT}")
    v2_runner.require(not REPORT.exists(), f"Report already exists: {REPORT}")
    checked = preflight()
    audit = dict(checked["static_audit"])
    records = audit.pop("static_records")
    original_freeze = original.verify_freeze()
    payload: dict[str, Any] = {
        "version": "GOLD_HYBRID_STRUCTURAL_EXECUTION_RESEARCH_V1_FREEZE_1_0",
        "frozen_at": v2_runner.now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_POST_HOC_EXPOSED_EXECUTION_RESEARCH",
        "population": {
            "events": 729,
            "mechanically_executable": 648,
            "continuation": 434,
            "selectively_negated_continuation": 180,
            "preserved": 468,
            "unopened_february_gap": "2022-02-17/2022-02-28",
        },
        "policy_registry": list(POLICY_IDS),
        "entry_modes": list(ENTRY_MODES),
        "exit_modes": list(EXIT_MODES),
        "static_audit": audit,
        "frozen_static_records": records,
        "control": {
            "policy_id": CONTROL_POLICY,
            "net_r50": CONTROL_NET_R50,
            "sealed_summary": checked["control"],
        },
        "benchmark_net_r50": BENCHMARK_NET_R50,
        "risk_and_execution": {
            "risk_budget_usd": 50.0,
            "quantity": "min(original_quantity, floor(50 / selected_stop_distance))",
            "quantity_upsize": False,
            "latency_minutes": 1,
            "slippage_price_per_ounce": 0.05,
            "observed_spread": True,
            "stop_first_ambiguity": True,
            "deadline": "NOON_AMERICA_NEW_YORK",
            "overlap_suppression": False,
        },
        "statistics": {
            "cluster": "TRADING_DATE_UTC",
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_draws": BOOTSTRAP_DRAWS,
            "comparisons_to_control": 8,
            "bonferroni_interval": BONFERRONI_INTERVAL,
        },
        "improvement_gates": {
            "negated_executions_min": 50,
            "net_r50_above_control_min": 2.0,
            "profit_factor_gte_control": True,
            "maximum_drawdown_lte_control": True,
            "positive_months_min": 4,
            "adjusted_paired_improvement_ci_lower_gt_zero": True,
            "maximum_displayed_trade_risk_usd": 50.0,
            "primary_reference_exact": True,
        },
        "candidate_limit": 2,
        "synthetic_proof": checked["synthetic_proof"],
        "predecessor": {
            "hybrid_freeze_sha256": checked["hybrid_freeze_sha256"],
            "hybrid_seal_sha256": checked["hybrid_seal_sha256"],
            "hybrid_freeze": v2_runner.file_record(hybrid.FREEZE),
            "hybrid_primary": v2_runner.file_record(hybrid.PRIMARY),
            "hybrid_reference": v2_runner.file_record(hybrid.REFERENCE),
            "hybrid_final": v2_runner.file_record(hybrid.FINAL),
            "hybrid_seal": v2_runner.file_record(hybrid.SEAL),
        },
        "governing_files": [
            v2_runner.file_record(path)
            for path in (
                CONTRACT,
                BOOK,
                IMPLEMENTATION,
                TESTS,
                RUNNER,
                hybrid.IMPLEMENTATION,
                hybrid.RUNNER,
                v2_runner.OUTCOME_IMPLEMENTATION,
            )
        ],
        "source_records": original_freeze["source_records"],
        "fresh_period_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    v2_runner.write_json(FREEZE, payload)
    print(
        json.dumps(
            {
                "status": "FROZEN_STRUCTURAL_EXECUTION_3X3",
                "policies": len(POLICY_IDS),
                "static_dispositions": audit["dispositions"],
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
    hybrid_state = hybrid.verify_freeze()
    hybrid_seal = v2_runner.verify_canonical_seal(hybrid.SEAL)
    v2_runner.require(
        hybrid_state["freeze_sha256"] == frozen["predecessor"]["hybrid_freeze_sha256"],
        "Hybrid predecessor freeze differs",
    )
    v2_runner.require(
        hybrid_seal["seal_sha256"] == frozen["predecessor"]["hybrid_seal_sha256"],
        "Hybrid predecessor seal differs",
    )
    for side in ("primary", "reference"):
        audit = static_audit(side)
        v2_runner.require(
            audit["static_records"] == frozen["frozen_static_records"],
            f"{side}: static plan registry differs after freeze",
        )
    return frozen


def control_execution_map(side: str) -> dict[str, dict[str, Any]]:
    path = hybrid.PRIMARY if side == "primary" else hybrid.REFERENCE
    payload = v2_runner.verify_canonical_payload(path, "payload_sha256")
    return {str(row["event_identity"]): dict(row) for row in payload["track_b"]["rows"]}


def execute_policy(
    side: str,
    entry_mode: str,
    exit_mode: str,
    rows: Sequence[Mapping[str, Any]],
    events: Mapping[str, Mapping[str, Any]],
    streams: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    identifier = f"{entry_mode}::{exit_mode}"
    output: list[dict[str, Any]] = []
    for source_row in rows:
        row = {key: value for key, value in source_row.items() if key != "plan"}
        prepared = prepare_static_plan(
            source_row,
            events[str(source_row["event_identity"])],
            entry_mode=entry_mode,
            exit_mode=exit_mode,
        )
        row.update(
            {
                "policy_id": identifier,
                "entry_mode": entry_mode,
                "exit_mode": exit_mode,
                "static_disposition": prepared["disposition"],
            }
        )
        if prepared.get("plan") is None:
            row.update(
                {
                    "execution_disposition": prepared["disposition"],
                    "result": None,
                    "net_r50": 0.0,
                    "target_replaced_by_local_m15": False,
                    "confirmation_used": False,
                }
            )
        else:
            alias = str(source_row["case_alias"])
            v2_runner.require(alias in streams, f"{side}: missing stream {alias}")
            resolved = resolve_prepared_plan(
                prepared,
                list(streams[alias]["timeframes"]["1m"]),
            )
            result = resolved.get("result")
            resolved_plan = resolved.get("resolved_plan")
            row.update(
                {
                    "execution_disposition": resolved["disposition"],
                    "result": result,
                    "net_r50": 0.0 if result is None else float(result["execution"]["net_r50"]),
                    "target_replaced_by_local_m15": bool(
                        prepared["plan"]["target_replaced_by_local_m15"]
                    ),
                    "confirmation_used": bool(
                        resolved_plan is not None and resolved_plan.get("confirmation") is not None
                    ),
                    "resolved_plan_sha256": None
                    if resolved_plan is None
                    else str(resolved_plan["plan_sha256"]),
                }
            )
        row["execution_row_sha256"] = canonical_hash(row)
        output.append(row)
    return output


def grouped_economics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS":
            groups[str(row[key])].append(dict(row))
    output: dict[str, Any] = {}
    for name in sorted(groups):
        ordered = sorted(
            groups[name],
            key=lambda row: (
                parse_dt(str(row["result"]["execution"]["fill_at"])),
                str(row["event_identity"]),
            ),
        )
        output[name] = economic_summary([float(row["net_r50"]) for row in ordered])
    return output


def policy_diagnostics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    executed = [
        row
        for row in rows
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
    ]
    negated = [row for row in executed if row["hybrid_route_action"] == "NEGATE"]
    risks = [float(row["result"]["execution"]["displayed_planned_risk_usd"]) for row in executed]
    quantities = [int(row["result"]["execution"]["quantity_ounces"]) for row in executed]
    return {
        "execution_dispositions": dict(sorted(Counter(row["execution_disposition"] for row in rows).items())),
        "negated_executed": len(negated),
        "negated_economics": economic_summary([float(row["net_r50"]) for row in negated]),
        "confirmation_executed": sum(row["confirmation_used"] for row in executed),
        "local_target_executed": sum(row["target_replaced_by_local_m15"] for row in executed),
        "partial_filled": sum(
            bool(row["result"]["execution"].get("partial_filled")) for row in executed
        ),
        "maximum_displayed_trade_risk_usd": max(risks),
        "maximum_quantity_ounces": max(quantities),
        "quantity_upsize_count": sum(
            int(row["result"]["execution"]["quantity_ounces"])
            > int(row["original_quantity_ounces"])
            for row in executed
        ),
        "by_route_action": grouped_economics(executed, "hybrid_route_action"),
        "by_route_reason": grouped_economics(executed, "hybrid_route_reason"),
        "by_direction": grouped_economics(executed, "selected_direction"),
        "resolution_counts": dict(
            sorted(Counter(row["result"]["execution"]["resolution"] for row in executed).items())
        ),
    }


def run_side(side: str, frozen: Mapping[str, Any]) -> dict[str, Any]:
    rows = load_routed(side)
    events = event_map(side)
    streams = source.load_streams(side)
    policies: dict[str, Any] = {}
    for index, identifier in enumerate(POLICY_IDS, start=1):
        entry_mode, exit_mode = identifier.split("::")
        executed_rows = execute_policy(side, entry_mode, exit_mode, rows, events, streams)
        overlap = matched_nonoverlap_diagnostic(executed_rows)
        summary = summarize(executed_rows, overlap)
        diagnostics = policy_diagnostics(executed_rows)
        policies[identifier] = {
            "rows": executed_rows,
            "rows_sha256": canonical_hash(executed_rows),
            "nonoverlap_diagnostic_rows": overlap,
            "summary": summary,
            "diagnostics": diagnostics,
        }
        print(
            f"checkpoint: {side} policy {index}/9 complete; "
            f"trades={summary['all_executable_signals']['trades']} "
            f"net={summary['all_executable_signals']['net_r50']:+.4f}R",
            flush=True,
        )
    sealed_control = control_execution_map(side)
    control_rows = policies[CONTROL_POLICY]["rows"]
    for row in control_rows:
        old = sealed_control[str(row["event_identity"])]
        v2_runner.require(
            row["execution_disposition"] == old["execution_disposition"],
            f"{side}: control disposition differs: {row['event_identity']}",
        )
        if row["result"] is not None:
            v2_runner.require(
                row["result"]["execution"] == old["result"]["execution"]
                and float(row["net_r50"]) == float(old["net_r50"]),
                f"{side}: control execution differs: {row['event_identity']}",
            )
    control_net = policies[CONTROL_POLICY]["summary"]["all_executable_signals"]["net_r50"]
    v2_runner.require(
        math.isclose(float(control_net), CONTROL_NET_R50, abs_tol=1e-12),
        f"{side}: control net differs",
    )
    payload: dict[str, Any] = {
        "version": "GOLD_HYBRID_STRUCTURAL_EXECUTION_RESEARCH_V1_SIDE_1_0",
        "side": side,
        "freeze_sha256": frozen["freeze_sha256"],
        "policies": policies,
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def daily_values(rows: Sequence[Mapping[str, Any]], dates: Sequence[str]) -> list[float]:
    values: dict[str, float] = defaultdict(float)
    for row in rows:
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS":
            values[str(row["trading_date_utc"])] += float(row["net_r50"])
    return [values[date] for date in dates]


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("Cannot calculate an empty quantile")
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def paired_bootstrap(
    policy_rows: Sequence[Mapping[str, Any]],
    control_rows: Sequence[Mapping[str, Any]],
    dates: Sequence[str],
    policy_index: int,
) -> dict[str, Any]:
    policy_daily = daily_values(policy_rows, dates)
    control_daily = daily_values(control_rows, dates)
    differences = [left - right for left, right in zip(policy_daily, control_daily, strict=True)]
    rng = random.Random(BOOTSTRAP_SEED + policy_index)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_DRAWS):
        draws.append(sum(differences[rng.randrange(len(differences))] for _ in differences))
    tail = (1.0 - BONFERRONI_INTERVAL) / 2.0
    payload = {
        "observed_incremental_net_r50": sum(differences),
        "bonferroni_interval_level": BONFERRONI_INTERVAL,
        "lower_r50": quantile(draws, tail),
        "upper_r50": quantile(draws, 1.0 - tail),
        "bootstrap_seed": BOOTSTRAP_SEED + policy_index,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "cluster_dates": len(dates),
    }
    payload["bootstrap_sha256"] = canonical_hash(payload)
    return payload


def evaluate_policies(primary: Mapping[str, Any]) -> dict[str, Any]:
    control = primary["policies"][CONTROL_POLICY]
    control_economic = control["summary"]["all_executable_signals"]
    dates = sorted(
        {str(row["trading_date_utc"]) for row in control["rows"]}
    )
    evaluations: dict[str, Any] = {}
    for index, identifier in enumerate(POLICY_IDS):
        policy = primary["policies"][identifier]
        economic = policy["summary"]["all_executable_signals"]
        diagnostics = policy["diagnostics"]
        months = policy["summary"]["by_month"]
        bootstrap = (
            {
                "observed_incremental_net_r50": 0.0,
                "bonferroni_interval_level": None,
                "lower_r50": 0.0,
                "upper_r50": 0.0,
                "bootstrap_seed": None,
                "bootstrap_draws": 0,
                "cluster_dates": len(dates),
            }
            if identifier == CONTROL_POLICY
            else paired_bootstrap(policy["rows"], control["rows"], dates, index)
        )
        gates = {
            "negated_executions_gte_50": diagnostics["negated_executed"] >= 50,
            "net_improvement_gte_2r": float(economic["net_r50"])
            >= float(control_economic["net_r50"]) + 2.0 - EPSILON,
            "profit_factor_gte_control": (
                economic["profit_factor"] is not None
                and control_economic["profit_factor"] is not None
                and float(economic["profit_factor"]) + EPSILON
                >= float(control_economic["profit_factor"])
            ),
            "maximum_drawdown_lte_control": float(economic["maximum_drawdown_r50"])
            <= float(control_economic["maximum_drawdown_r50"]) + EPSILON,
            "positive_months_gte_4": sum(float(row["net_r50"]) > 0 for row in months.values()) >= 4,
            "adjusted_incremental_ci_lower_gt_zero": identifier != CONTROL_POLICY
            and float(bootstrap["lower_r50"]) > 0,
            "maximum_trade_risk_lte_50": diagnostics["maximum_displayed_trade_risk_usd"]
            <= 50.0 + EPSILON,
            "no_quantity_upsize": diagnostics["quantity_upsize_count"] == 0,
        }
        improvement_pass = identifier != CONTROL_POLICY and all(gates.values())
        evaluations[identifier] = {
            "economics": economic,
            "diagnostics": diagnostics,
            "bootstrap_vs_control": bootstrap,
            "gates": gates,
            "improvement_pass": improvement_pass,
            "benchmark_met": float(economic["net_r50"]) + EPSILON >= BENCHMARK_NET_R50,
        }
    passing = [identifier for identifier in POLICY_IDS if evaluations[identifier]["improvement_pass"]]
    passing.sort(
        key=lambda identifier: (
            not evaluations[identifier]["benchmark_met"],
            -float(evaluations[identifier]["economics"]["net_r50"]),
            -float(evaluations[identifier]["economics"]["profit_factor"] or 0.0),
            float(evaluations[identifier]["economics"]["maximum_drawdown_r50"]),
            identifier,
        )
    )
    return {
        "dates": dates,
        "control_policy": CONTROL_POLICY,
        "evaluations": evaluations,
        "provisional_candidates": passing[:2],
        "passing_beyond_candidate_limit": passing[2:],
    }


def ledger_csv(policies: Mapping[str, Any]) -> str:
    handle = io.StringIO(newline="")
    fields = [
        "policy_id",
        "trading_date_utc",
        "event_identity",
        "decision_at",
        "route_action",
        "route_reason",
        "selected_direction",
        "execution_disposition",
        "confirmation_used",
        "target_replaced_by_local_m15",
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
    for identifier in POLICY_IDS:
        for row in policies[identifier]["rows"]:
            execution = None if row["result"] is None else row["result"]["execution"]
            writer.writerow(
                {
                    "policy_id": identifier,
                    "trading_date_utc": row["trading_date_utc"],
                    "event_identity": row["event_identity"],
                    "decision_at": row["decision_at"],
                    "route_action": row["hybrid_route_action"],
                    "route_reason": row["hybrid_route_reason"],
                    "selected_direction": row["selected_direction"],
                    "execution_disposition": row["execution_disposition"],
                    "confirmation_used": row["confirmation_used"],
                    "target_replaced_by_local_m15": row["target_replaced_by_local_m15"],
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
    lines = [
        "# Gold Hybrid Structural Execution Research V1 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "This is exposed execution research with zero validation credit. The frozen hybrid directions were unchanged. Nine preregistered structural execution policies were evaluated once; no alternative was added or retuned afterward.",
        "",
        "| Policy | Trades | Negated | Win rate | Net R | PF | Max DD | Delta vs control | Adjusted CI low | Positive months | Benchmark | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for identifier in POLICY_IDS:
        row = final["evaluation"]["evaluations"][identifier]
        economic = row["economics"]
        months = final["policy_months"][identifier]
        lines.append(
            f"| {identifier} | {economic['trades']} | {row['diagnostics']['negated_executed']} | "
            f"{economic['win_rate'] * 100:.2f}% | {economic['net_r50']:+.4f} | {pf(economic)} | "
            f"{economic['maximum_drawdown_r50']:.4f} | "
            f"{row['bootstrap_vs_control']['observed_incremental_net_r50']:+.4f} | "
            f"{row['bootstrap_vs_control']['lower_r50']:+.4f} | "
            f"{sum(float(value['net_r50']) > 0 for value in months.values())} | "
            f"{'YES' if row['benchmark_met'] else 'NO'} | "
            f"{'PASS' if row['improvement_pass'] else 'REJECT'} |"
        )
    lines.extend(
        [
            "",
            "## Provisional disposition",
            "",
            f"- Provisional policies: `{', '.join(final['evaluation']['provisional_candidates']) or 'NONE'}`.",
            f"- Any policy reached +45.7728R under the $50/no-upsize rules: **{'YES' if final['any_benchmark_met'] else 'NO'}**.",
            "- The mechanical stop/target swap remains only the control; it is not treated as a logical invalidation model.",
            "- The unopened February interval, 2025 and 2026 remained closed.",
            "",
            "## Integrity",
            "",
            "- Primary and reference plans, confirmations, executions, policy metrics and checksums matched exactly.",
            "- No direction, date, case, loss or winner was removed after outcomes.",
            "- Every executed setup stayed at or below $50 displayed risk and no quantity was upsized.",
            "- Multiple simultaneous valid setups remained permitted.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    primary = run_side("primary", frozen)
    print("checkpoint: complete primary 3x3 matrix finished", flush=True)
    reference = run_side("reference", frozen)
    print("checkpoint: complete independent reference 3x3 matrix finished", flush=True)
    for identifier in POLICY_IDS:
        left = primary["policies"][identifier]
        right = reference["policies"][identifier]
        v2_runner.require(left["rows"] == right["rows"], f"{identifier}: rows differ")
        v2_runner.require(left["summary"] == right["summary"], f"{identifier}: summary differs")
        v2_runner.require(
            left["diagnostics"] == right["diagnostics"], f"{identifier}: diagnostics differ"
        )
    evaluation = evaluate_policies(primary)
    candidates = evaluation["provisional_candidates"]
    any_benchmark = any(
        evaluation["evaluations"][identifier]["benchmark_met"] for identifier in POLICY_IDS
    )
    if candidates and any(
        evaluation["evaluations"][identifier]["benchmark_met"] for identifier in candidates
    ):
        verdict = "PASS_PROVISIONAL_EXPOSED_EXECUTION_IMPROVEMENT_AND_BENCHMARK_ZERO_VALIDATION_CREDIT"
    elif candidates:
        verdict = "PASS_PROVISIONAL_EXPOSED_EXECUTION_IMPROVEMENT_BELOW_BENCHMARK_ZERO_VALIDATION_CREDIT"
    else:
        verdict = "REJECT_NO_PROVISIONAL_STRUCTURAL_EXECUTION_IMPROVEMENT_ZERO_VALIDATION_CREDIT"
    final: dict[str, Any] = {
        "version": "GOLD_HYBRID_STRUCTURAL_EXECUTION_RESEARCH_V1_FINAL_1_0",
        "verdict": verdict,
        "freeze_sha256": frozen["freeze_sha256"],
        "control_net_r50": CONTROL_NET_R50,
        "benchmark_net_r50": BENCHMARK_NET_R50,
        "evaluation": evaluation,
        "policy_months": {
            identifier: primary["policies"][identifier]["summary"]["by_month"]
            for identifier in POLICY_IDS
        },
        "any_benchmark_met": any_benchmark,
        "primary_reference_exact": True,
        "fresh_period_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "validation_credit": "ZERO_POST_HOC_EXPOSED_EXECUTION_RESEARCH",
    }
    final["final_sha256"] = canonical_hash(final)
    v2_runner.write_json(PRIMARY, primary)
    v2_runner.write_json(REFERENCE, reference)
    v2_runner.write_json(FINAL, final)
    v2_runner.write_text(LEDGER, ledger_csv(primary["policies"]))
    v2_runner.write_text(REPORT, report_markdown(final))
    certification: dict[str, Any] = {
        "version": "GOLD_HYBRID_STRUCTURAL_EXECUTION_RESEARCH_V1_CERTIFICATION_1_0",
        "completed_at": v2_runner.now(),
        "verdict": verdict,
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "nine_policies_complete": len(primary["policies"]) == 9,
            "control_exact_21p312216r": math.isclose(
                float(
                    primary["policies"][CONTROL_POLICY]["summary"]["all_executable_signals"]["net_r50"]
                ),
                CONTROL_NET_R50,
                abs_tol=1e-12,
            ),
            "primary_reference_exact": True,
            "all_policy_risk_caps_pass": all(
                primary["policies"][identifier]["diagnostics"]["maximum_displayed_trade_risk_usd"]
                <= 50.0 + EPSILON
                for identifier in POLICY_IDS
            ),
            "no_quantity_upsize": all(
                primary["policies"][identifier]["diagnostics"]["quantity_upsize_count"] == 0
                for identifier in POLICY_IDS
            ),
            "candidate_limit_respected": len(candidates) <= 2,
            "no_unregistered_policy": set(primary["policies"]) == set(POLICY_IDS),
            "fresh_periods_locked": True,
            "no_charge": True,
        },
        "output_records": [
            v2_runner.file_record(path) for path in (PRIMARY, REFERENCE, FINAL, LEDGER, REPORT)
        ],
    }
    v2_runner.require(all(certification["gates"].values()), "Certification gate failed")
    certification["certification_sha256"] = canonical_hash(certification)
    v2_runner.write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_HYBRID_STRUCTURAL_EXECUTION_RESEARCH_V1_SEAL_1_0",
        "sealed_at": v2_runner.now(),
        "verdict": verdict,
        "certification_sha256": certification["certification_sha256"],
        "files": [
            v2_runner.file_record(path)
            for path in (FREEZE, PRIMARY, REFERENCE, FINAL, LEDGER, CERTIFICATION, REPORT)
        ],
        "fresh_period_opened": False,
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
                "control_net_r50": CONTROL_NET_R50,
                "benchmark_net_r50": BENCHMARK_NET_R50,
                "provisional_candidates": candidates,
                "any_benchmark_met": any_benchmark,
                "policy_results": {
                    identifier: {
                        "trades": evaluation["evaluations"][identifier]["economics"]["trades"],
                        "net_r50": evaluation["evaluations"][identifier]["economics"]["net_r50"],
                        "profit_factor": evaluation["evaluations"][identifier]["economics"]["profit_factor"],
                        "max_drawdown_r50": evaluation["evaluations"][identifier]["economics"]["maximum_drawdown_r50"],
                        "incremental_ci_lower_r50": evaluation["evaluations"][identifier]["bootstrap_vs_control"]["lower_r50"],
                        "improvement_pass": evaluation["evaluations"][identifier]["improvement_pass"],
                        "benchmark_met": evaluation["evaluations"][identifier]["benchmark_met"],
                    }
                    for identifier in POLICY_IDS
                },
                "report": REPORT.relative_to(ROOT).as_posix(),
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
        audit = dict(checked["static_audit"])
        audit.pop("static_records", None)
        print(
            json.dumps(
                {
                    "status": checked["status"],
                    "control": checked["control"],
                    "static_audit": audit,
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
