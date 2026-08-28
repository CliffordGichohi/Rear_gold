#!/usr/bin/env python3
"""Freeze, reproduce, and seal the bounded Router V2-R1 correction."""

from __future__ import annotations

import argparse
import copy
import csv
import gc
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_auction_semantic_family_router_exposed_regression_v2 as failed_v2  # noqa: E402
import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.auction_family_router_v1 import (  # noqa: E402
    first_structural_repair_retest,
)
from gold_intel.analytics.auction_family_router_v2 import (  # noqa: E402
    first_balance_boundary_reclaim,
    planned_geometry,
    simulate_structural_management,
)
from gold_intel.analytics.auction_family_router_v2_r1 import (  # noqa: E402
    destination_hierarchy,
    direct_legacy_signal_route,
    m15_setup_event,
    pre_entry_invalidation_disposition,
    select_destination_hierarchy,
)
from gold_intel.analytics.auction_plan_compiler_v1_semantic_amendment_a import (  # noqa: E402
    compile_auction_plan_v1_semantic_amendment_a,
    plan_integrity_violations,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    iso,
    parse_dt,
)
from gold_intel.analytics.day_by_day_auction_confirmation_v1 import (  # noqa: E402
    first_complete_m1_after,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    classify_autonomous,
    latest_m1_at,
    spread,
)


PROTOCOL = ROOT / "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_EXPOSED_REGRESSION_V2_R1.md"
DIAGNOSTIC = ROOT / "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_V2_IMPLEMENTATION_FAILURE_DIAGNOSTIC.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_family_router_v2_r1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_family_router_v2_r1.py"
RUNNER = Path(__file__).resolve()

FAILED_ROOT = ROOT / "research_artifacts" / "gold_auction_semantic_family_router_exposed_regression_v2"
FAILED_RESULT = FAILED_ROOT / "final_result.json"
FAILED_SEAL = FAILED_ROOT / "final_seal.json"
FAILED_SEMANTIC_SHA256 = "d86278ed0d751e1b3122b37ea89bdb4316bb7936b912c24b2104d4ae6b0dc6a8"

BASELINE_RESULT = failed_v2.BASELINE_RESULT
V1_RESULT = failed_v2.V1_RESULT
OUT = ROOT / "research_artifacts" / "gold_auction_semantic_family_router_exposed_regression_v2_r1"
FREEZE = OUT / "prepath_freeze.json"
PRIMARY_RESULT = OUT / "router_v2_r1.primary.json"
REFERENCE_RESULT = OUT / "router_v2_r1.reference.json"
FINAL_RESULT = OUT / "final_result.json"
DAILY_LEDGER = OUT / "daily_ledger.csv"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_EXPOSED_REGRESSION_V2_R1_REPORT.md"

RISK_USD = 50.0
STARTING_EQUITY_USD = 10_000.0
SLIPPAGE_USD_PER_OUNCE = 0.05
WIN_EPSILON = 1e-12
FAMILIES = ("CONTINUATION_WITH_ROOM", "RANGE_ROTATION", "STRUCTURAL_REPAIR")


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_failed_v2() -> dict[str, Any]:
    seal = failed_v2.verify_list_seal(
        FAILED_SEAL,
        semantic_path=FAILED_RESULT,
        semantic_hash=FAILED_SEMANTIC_SHA256,
    )
    return {
        "semantic_result_sha256": FAILED_SEMANTIC_SHA256,
        "seal_sha256": seal["seal_sha256"],
        "result_file_sha256": sha256_file(FAILED_RESULT),
    }


def verify_predecessors() -> dict[str, Any]:
    return {
        "v2_predecessors": failed_v2.verify_predecessors(),
        "failed_v2": verify_failed_v2(),
    }


def _synthetic_zone(identity: str, level: float, state: str) -> dict[str, Any]:
    return {
        "identity": identity,
        "source": "H1",
        "state": state,
        "level": level,
        "buffer": 0.2,
        "known_at": "2022-01-03T07:00:00Z",
        "prominence_atr": 1.0,
    }


def synthetic_proof() -> dict[str, Any]:
    setup = {
        "identity": "semantic-m15",
        "event_identity": "m15",
        "timeframe": "M15",
        "direction": "LONG",
        "break_at": "2022-01-03T08:00:00Z",
        "broken_swing_identity": "broken",
        "broken_level": 101.0,
        "protected_swing_identity": "protected",
        "protected_level": 98.0,
        "transition_origin_at": "2022-01-03T07:00:00Z",
        "transition_origin_adverse": 97.0,
        "transition_atr": 2.0,
        "break_buffer": 0.2,
    }
    refinement = {**setup, "identity": "semantic-m5", "event_identity": "m5", "timeframe": "M5"}
    plan = {
        "components": {
            "local_trigger": {
                "setup_transition": setup,
                "entry_refinement": refinement,
                "execution_anchor": {
                    "identity": "legacy-anchor",
                    "timeframe": "M15",
                    "break_at": "2022-01-03T08:00:00Z",
                },
            }
        }
    }
    selected = m15_setup_event(plan)
    hierarchy = select_destination_hierarchy(
        [
            _synthetic_zone("reactivated", 101.0, "REACTIVATED_REVERSE"),
            _synthetic_zone("engaged", 103.0, "ACTIVE_ENGAGED"),
            _synthetic_zone("consumed", 102.0, "CONSUMED_ACCEPTED"),
        ],
        entry=100.0,
        direction="LONG",
    )
    bar = {
        "open_at": "2022-01-03T08:01:00Z",
        "close_at": "2022-01-03T08:02:00Z",
        "available_at": "2022-01-03T08:02:00Z",
        "open": 100.0,
        "high": 120.0,
        "low": 99.0,
        "close": 101.0,
        "complete": True,
        "source_record_hash": "synthetic",
    }
    target_touch = pre_entry_invalidation_disposition(
        [bar],
        signal_at="2022-01-03T08:00:00Z",
        fill_at="2022-01-03T08:03:00Z",
        stop=98.0,
        direction="LONG",
    )
    stopped = pre_entry_invalidation_disposition(
        [{**bar, "low": 97.0}],
        signal_at="2022-01-03T08:00:00Z",
        fill_at="2022-01-03T08:03:00Z",
        stop=98.0,
        direction="LONG",
    )
    direct = direct_legacy_signal_route(
        signal_at="2022-01-03T08:00:00Z", direction="LONG"
    )
    checks = {
        "m15_setup_not_m5_refinement": selected is not None and selected["identity"] == "m15",
        "single_direct_anchor": direct["second_trigger_required"] is False,
        "engaged_final_eligible": hierarchy is not None and hierarchy["final"]["identity"] == "engaged",
        "reactivated_is_intermediate": hierarchy is not None and hierarchy["intermediate"]["identity"] == "reactivated",
        "consumed_not_selected": hierarchy is not None and hierarchy["final"]["identity"] != "consumed",
        "target_touch_not_cancelled": target_touch["disposition"] == "CLEAR_TO_DELAYED_ENTRY",
        "stop_touch_cancelled": stopped["disposition"] == "STRUCTURAL_INVALIDATION_TOUCHED_PRE_ENTRY",
    }
    require(all(checks.values()), f"V2-R1 synthetic proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    for path in (PROTOCOL, DIAGNOSTIC, IMPLEMENTATION, TESTS, RUNNER):
        require(path.is_file(), f"Required file absent: {path}")
    predecessors = verify_predecessors()
    controls = baseline.control_rows()
    dates = [str(row["trading_date_utc"]) for row in controls]
    require(len(dates) == 95 and len(set(dates)) == 95, "Expected 95 exposed dates")
    proof = synthetic_proof()
    files = [
        PROTOCOL,
        DIAGNOSTIC,
        IMPLEMENTATION,
        TESTS,
        RUNNER,
        FAILED_RESULT,
        FAILED_SEAL,
        BASELINE_RESULT,
        V1_RESULT,
    ]
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_V2_R1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_V2_R1_EXPOSED_REPLAY",
        "files": [file_record(path) for path in files],
        "predecessors": predecessors,
        "dates": dates,
        "date_counts": dict(sorted(Counter(value[:7] for value in dates).items())),
        "population_sha256": canonical_hash(
            [
                {
                    "case_alias": row["case_alias"],
                    "trading_date_utc": row["trading_date_utc"],
                }
                for row in controls
            ]
        ),
        "policy": {
            "single_signal_lifecycle": "FROZEN_LEGACY_SIGNAL",
            "continuation_route": "DIRECT",
            "structural_repair_trigger": "M15_SETUP_TRANSITION",
            "range_trigger": "NAMED_BALANCE_BOUNDARY_SWEEP_RECLAIM",
            "m5_refinement_execution_role": "EVIDENCE_ONLY",
            "pre_entry_cancel": "STRUCTURAL_INVALIDATION_ONLY",
            "final_destination_states": ["ACTIVE_ENGAGED", "ACTIVE_UNTOUCHED"],
            "intermediate_destination_states": ["REACTIVATED_REVERSE"],
            "consumed_destination_state": "EXCLUDED",
            "delayed_destination_refresh": True,
            "actual_fill_target_room_minimum_r": 1.5,
            "risk_usd": RISK_USD,
            "numeric_break_even_used": False,
        },
        "synthetic_proof": proof,
        "random_50_case_population_opened": False,
        "february_17_28_opened": False,
        "additional_dates_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(json.dumps({"status": payload["status"], "dates": len(dates), "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "V2-R1 prepath freeze absent")
    payload = load_json(FREEZE)
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "V2-R1 freeze payload differs")
    payload["freeze_sha256"] = submitted
    require(payload["status"] == "SEALED_BEFORE_V2_R1_EXPOSED_REPLAY", "Freeze status differs")
    for record in payload["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen hash differs: {path}")
    require(verify_predecessors() == payload["predecessors"], "Predecessors differ")
    require([row["trading_date_utc"] for row in baseline.control_rows()] == payload["dates"], "Date order differs")
    return payload


def empty_lifecycle(disposition: str, **extra: Any) -> dict[str, Any]:
    return {
        "admitted": False,
        "disposition": disposition,
        "session": extra.pop("session", None),
        "compiled_family": extra.pop("compiled_family", None),
        "plan": extra.pop("plan", None),
        "route": extra.pop("route", None),
        "pre_entry": extra.pop("pre_entry", None),
        "signal_destination_hierarchy": extra.pop("signal_destination_hierarchy", None),
        "entry_destination_hierarchy": extra.pop("entry_destination_hierarchy", None),
        "geometry": extra.pop("geometry", None),
        "classification": extra.pop("classification", None),
        "result": None,
        "post_exit_diagnostic": None,
        **extra,
    }


def route_for_plan(
    *,
    plan: dict[str, Any],
    stream: dict[str, Any],
    signal_at: str,
    session_end: datetime,
    direction: str,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    family = str(plan["components"]["governing_auction"]["family"])
    if family == "CONTINUATION_WITH_ROOM":
        return direct_legacy_signal_route(signal_at=signal_at, direction=direction), None, False
    if family == "STRUCTURAL_REPAIR":
        event = m15_setup_event(plan)
        if event is None:
            return None, "STRUCTURAL_REPAIR::M15_SETUP_TRANSITION_UNAVAILABLE", True
        route = first_structural_repair_retest(
            stream["timeframes"]["5m"],
            event=event,
            signal_at=signal_at,
            session_end=session_end,
            direction=direction,
            maximum_bars=12,
        )
        if route["disposition"] != "CONFIRMED":
            return route, f"STRUCTURAL_REPAIR::{route['disposition']}", True
        route["route"] = "STRUCTURAL_REPAIR_M15_SETUP_FIRST_M5_RETEST"
        route["route_hash"] = canonical_hash(
            {key: value for key, value in route.items() if key != "route_hash"}
        )
        return route, None, True
    controlling = plan["components"]["controlling_structure"]
    boundary = float(controlling["levels"]["directional_boundary"])
    route = first_balance_boundary_reclaim(
        stream["timeframes"]["5m"],
        signal_at=signal_at,
        session_end=session_end,
        boundary=boundary,
        boundary_identity=str(controlling["identity"]),
        direction=direction,
        maximum_bars=6,
    )
    if route is None:
        return None, "RANGE_ROTATION::NO_NAMED_BOUNDARY_RECLAIM_WITHIN_6_M5", True
    return route, None, True


def r1_lifecycle(*, control: dict[str, Any], stream: dict[str, Any]) -> dict[str, Any]:
    if control.get("signal_at") is None:
        return empty_lifecycle("NO_SIGNAL")
    signal_at = str(control["signal_at"])
    session = baseline.signal_session(signal_at)
    end = baseline.session_end(signal_at, session)
    old_classification = control.get("classification")
    old_geometry = control.get("geometry")
    require(old_classification is not None and old_geometry is not None, "Original signal payload absent")
    if not old_classification["admitted"]:
        return empty_lifecycle(
            f"ORIGINAL_SIGNAL_CONTEXT_REJECTED::{old_classification['primary_disposition']}",
            session=session,
            classification=old_classification,
        )

    direction = str(old_classification["direction"])
    require(direction in {"LONG", "SHORT"}, "Direction unavailable")
    reference = float(old_geometry["reference_close"])
    plan = compile_auction_plan_v1_semantic_amendment_a(
        stream=stream,
        decision_at=signal_at,
        direction=direction,
        entry_reference=reference,
    )
    violations = plan_integrity_violations(plan)
    require(not violations, f"Plan integrity failed: {control['case_alias']} {violations}")
    if plan["disposition"] != "EXECUTABLE_PLAN":
        return empty_lifecycle(
            "NO_TRADE_UNRESOLVED::" + ",".join(plan["missing_components"]),
            session=session,
            plan=plan,
        )
    family = str(plan["components"]["governing_auction"]["family"])
    require(family in FAMILIES, f"Unknown family: {family}")
    stop = float(plan["components"]["structural_invalidation"]["price"])
    signal_destination = destination_hierarchy(
        stream=stream,
        cutoff=signal_at,
        entry=reference,
        direction=direction,
        plan=plan,
    )
    if signal_destination is None:
        return empty_lifecycle(
            "NO_ACTIVE_NONCONSUMED_FINAL_DESTINATION_AT_SIGNAL",
            session=session,
            compiled_family=family,
            plan=plan,
        )
    signal_target = float(signal_destination["final"]["level"])
    signal_cost = float(old_geometry["cost_per_ounce"])
    signal_geometry = planned_geometry(
        fill=reference,
        stop=stop,
        target=signal_target,
        cost_per_ounce=signal_cost,
        direction=direction,
    )
    if not signal_geometry["geometry_valid"]:
        return empty_lifecycle(
            "SIGNAL_GEOMETRY_INVALID",
            session=session,
            compiled_family=family,
            plan=plan,
            signal_destination_hierarchy=signal_destination,
        )
    signal_classification = classify_autonomous(
        stream=stream,
        signal_at=signal_at,
        family=family,
        fill=reference,
        stop=stop,
        target=signal_target,
        cost_per_ounce=signal_cost,
    )
    if not signal_classification["admitted"]:
        return empty_lifecycle(
            f"COMPILED_FAMILY_CONTEXT_REJECTED::{signal_classification['primary_disposition']}",
            session=session,
            compiled_family=family,
            plan=plan,
            signal_destination_hierarchy=signal_destination,
            classification=signal_classification,
        )
    route, route_failure, delayed = route_for_plan(
        plan=plan,
        stream=stream,
        signal_at=signal_at,
        session_end=end,
        direction=direction,
    )
    if route_failure is not None:
        return empty_lifecycle(
            route_failure,
            session=session,
            compiled_family=family,
            plan=plan,
            route=route,
            signal_destination_hierarchy=signal_destination,
            classification=signal_classification,
        )

    if delayed:
        confirmation_at = str(route["confirmation_at"])
        fill_bar = first_complete_m1_after(stream["timeframes"]["1m"], confirmation_at)
        if fill_bar is None or parse_dt(fill_bar["open_at"]) >= end:
            return empty_lifecycle(
                "NO_EXECUTABLE_M1_AFTER_COMPILED_CONFIRMATION",
                session=session,
                compiled_family=family,
                plan=plan,
                route=route,
                signal_destination_hierarchy=signal_destination,
                classification=signal_classification,
            )
        fill_at = iso(fill_bar["open_at"])
        preentry = pre_entry_invalidation_disposition(
            stream["timeframes"]["1m"],
            signal_at=signal_at,
            fill_at=fill_at,
            stop=stop,
            direction=direction,
        )
        if preentry["disposition"] != "CLEAR_TO_DELAYED_ENTRY":
            return empty_lifecycle(
                str(preentry["disposition"]),
                session=session,
                compiled_family=family,
                plan=plan,
                route=route,
                pre_entry=preentry,
                signal_destination_hierarchy=signal_destination,
                classification=signal_classification,
            )
        decision_bar = latest_m1_at(stream, confirmation_at)
        require(decision_bar is not None, "Confirmation decision bar absent")
        destination_at_entry = destination_hierarchy(
            stream=stream,
            cutoff=confirmation_at,
            entry=float(decision_bar["close"]),
            direction=direction,
            plan=plan,
        )
        if destination_at_entry is None:
            return empty_lifecycle(
                "NO_ACTIVE_NONCONSUMED_FINAL_DESTINATION_AT_CONFIRMATION",
                session=session,
                compiled_family=family,
                plan=plan,
                route=route,
                pre_entry=preentry,
                signal_destination_hierarchy=signal_destination,
                classification=signal_classification,
            )
        target = float(destination_at_entry["final"]["level"])
        fill = float(fill_bar["open"]) + spread(fill_bar) / 2.0 + SLIPPAGE_USD_PER_OUNCE
        cost_per_ounce = spread(decision_bar) + 2.0 * SLIPPAGE_USD_PER_OUNCE
    else:
        fill_at = str(old_geometry["fill_at"])
        fill = float(old_geometry["fill"])
        cost_per_ounce = signal_cost
        preentry = {
            "disposition": "DIRECT_ORIGINAL_FILL",
            "at": fill_at,
            "bar_hash": None,
        }
        destination_at_entry = signal_destination
        target = signal_target

    geometry = planned_geometry(
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=cost_per_ounce,
        direction=direction,
    )
    geometry_payload = {
        "fill_at": fill_at,
        "fill": fill,
        "stop": stop,
        "target": target,
        "cost_per_ounce": cost_per_ounce,
        "invalidation_identity": plan["components"]["structural_invalidation"]["identity"],
        "destination_identity": destination_at_entry["final"]["identity"],
        "intermediate_destination_identity": (
            destination_at_entry["intermediate"] or {}
        ).get("identity"),
        **geometry,
    }
    if not geometry["geometry_valid"]:
        return empty_lifecycle(
            "ACTUAL_FILL_GEOMETRY_INVALID",
            session=session,
            compiled_family=family,
            plan=plan,
            route=route,
            pre_entry=preentry,
            signal_destination_hierarchy=signal_destination,
            entry_destination_hierarchy=destination_at_entry,
            geometry=geometry_payload,
            classification=signal_classification,
        )
    actual_classification, _ = failed_v2.regeometry_classification(
        signal_classification,
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=cost_per_ounce,
        family=family,
        plan_sha256=str(plan["plan_sha256"]),
    )
    actual_classification["ruleset"] = (
        str(actual_classification["ruleset"]) + "::SEMANTIC_INTEGRATION_R1"
    )
    actual_classification["classification_hash"] = canonical_hash(
        {
            key: value
            for key, value in actual_classification.items()
            if key != "classification_hash"
        }
    )
    if not geometry["passes_actual_fill_1p5r"]:
        return empty_lifecycle(
            "ACTUAL_FILL_FINAL_DESTINATION_ROOM_LT_1P5R",
            session=session,
            compiled_family=family,
            plan=plan,
            route=route,
            pre_entry=preentry,
            signal_destination_hierarchy=signal_destination,
            entry_destination_hierarchy=destination_at_entry,
            geometry=geometry_payload,
            classification=actual_classification,
        )
    if not geometry["passes_whole_ounce_risk"]:
        return empty_lifecycle(
            "ACTUAL_FILL_WHOLE_OUNCE_RISK_UNAVAILABLE",
            session=session,
            compiled_family=family,
            plan=plan,
            route=route,
            pre_entry=preentry,
            signal_destination_hierarchy=signal_destination,
            entry_destination_hierarchy=destination_at_entry,
            geometry=geometry_payload,
            classification=actual_classification,
        )
    result = simulate_structural_management(
        classification=actual_classification,
        stream=stream,
        fill_at=fill_at,
    )
    diagnostic = failed_v2.post_exit_diagnostic(
        result=result, geometry=geometry_payload, stream=stream
    )
    return {
        "admitted": True,
        "disposition": str(result["resolution"]),
        "session": session,
        "compiled_family": family,
        "plan": plan,
        "route": route,
        "pre_entry": preentry,
        "signal_destination_hierarchy": signal_destination,
        "entry_destination_hierarchy": destination_at_entry,
        "geometry": geometry_payload,
        "classification": actual_classification,
        "result": result,
        "post_exit_diagnostic": diagnostic,
    }


def run_side(
    side: str,
    controls: list[dict[str, Any]],
    baseline_by_alias: dict[str, dict[str, Any]],
    v1_by_alias: dict[str, dict[str, Any]],
    failed_by_alias: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    streams = baseline.load_all_streams(side)
    require(set(streams) == {str(row["case_alias"]) for row in controls}, "Stream identities differ")
    rows: list[dict[str, Any]] = []
    for control in controls:
        alias = str(control["case_alias"])
        lifecycle = r1_lifecycle(control=control, stream=streams[alias])
        row: dict[str, Any] = {
            "case_alias": alias,
            "trading_date_utc": control["trading_date_utc"],
            "morning_plan": baseline.morning_plan(streams[alias]),
            "control": copy.deepcopy(baseline_by_alias[alias]["control"]),
            "rigid_confirmation": copy.deepcopy(baseline_by_alias[alias]["corrected"]),
            "router_v1": copy.deepcopy(v1_by_alias[alias]["family_router"]),
            "failed_router_v2": copy.deepcopy(failed_by_alias[alias]["router_v2"]),
            "router_v2_r1": lifecycle,
        }
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_V2_R1_SIDE_1_0",
        "side": side,
        "rows": rows,
        "row_set_sha256": canonical_hash(rows),
        "random_50_case_population_opened": False,
        "february_17_28_opened": False,
        "additional_dates_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    del streams
    gc.collect()
    return payload


def lifecycle_result(row: dict[str, Any], policy: str) -> dict[str, Any] | None:
    if policy == "control":
        return row["control"]["result"]
    if policy == "rigid":
        return row["rigid_confirmation"]["effective_result"]
    if policy == "router_v1":
        return row["router_v1"]["effective_result"]
    if policy == "failed_v2":
        return row["failed_router_v2"]["result"]
    if policy == "router_v2_r1":
        return row["router_v2_r1"]["result"]
    raise ValueError(policy)


def result_value(result: dict[str, Any] | None, field: str = "net_r50") -> float:
    return 0.0 if result is None or not result.get("executed") else float(result[field])


def metric_block(rows: list[dict[str, Any]], policy: str) -> dict[str, Any]:
    results = [lifecycle_result(row, policy) for row in rows]
    executed = [result for result in results if result is not None and result.get("executed")]
    values = [float(result["net_r50"]) for result in executed]
    wins = [value for value in values if value > WIN_EPSILON]
    losses = [value for value in values if value < -WIN_EPSILON]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    positive = sum(wins)
    negative = abs(sum(losses))
    return {
        "days": len(rows),
        "signals": sum(row["control"]["signal_at"] is not None for row in rows),
        "trades": len(executed),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(values) - len(wins) - len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "expectancy_r": sum(values) / len(values) if values else 0.0,
        "profit_factor": positive / negative if negative else None,
        "net_r": sum(values),
        "net_usd": sum(float(result["net_usd"]) for result in executed),
        "maximum_drawdown_r": drawdown,
        "trades_per_month": len(executed) / len({row["trading_date_utc"][:7] for row in rows}) if rows else 0.0,
        "stressed_1p5x_cost_net_r": sum(float(result["stressed_1_5x_cost_r50"]) for result in executed),
    }


def comparison_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    policies = ("control", "rigid", "router_v1", "failed_v2", "router_v2_r1")
    blocks = {policy: metric_block(rows, policy) for policy in policies}
    control_winners = [row for row in rows if result_value(lifecycle_result(row, "control")) > WIN_EPSILON]
    rejected_winners = [row for row in control_winners if lifecycle_result(row, "router_v2_r1") is None]
    avoided_losses = [
        row
        for row in rows
        if result_value(lifecycle_result(row, "control")) < -WIN_EPSILON
        and lifecycle_result(row, "router_v2_r1") is None
    ]
    blocks.update(
        {
            "r1_delta_vs_control_r": blocks["router_v2_r1"]["net_r"] - blocks["control"]["net_r"],
            "r1_delta_vs_v1_r": blocks["router_v2_r1"]["net_r"] - blocks["router_v1"]["net_r"],
            "r1_delta_vs_failed_v2_r": blocks["router_v2_r1"]["net_r"] - blocks["failed_v2"]["net_r"],
            "valid_control_winners_rejected": len(rejected_winners),
            "valid_control_winners_rejected_r": sum(result_value(lifecycle_result(row, "control")) for row in rejected_winners),
            "avoided_control_losses": len(avoided_losses),
            "avoided_control_loss_r": sum(result_value(lifecycle_result(row, "control")) for row in avoided_losses),
        }
    )
    return blocks


def add_equity(rows: list[dict[str, Any]]) -> None:
    policies = ("control", "rigid", "router_v1", "failed_v2", "router_v2_r1")
    equity = {policy: STARTING_EQUITY_USD for policy in policies}
    for row in rows:
        for policy in policies:
            equity[policy] += result_value(lifecycle_result(row, policy), "net_usd")
            row[f"{policy}_equity_usd"] = equity[policy]


def write_ledger(rows: list[dict[str, Any]]) -> None:
    require(not DAILY_LEDGER.exists(), f"Append-only ledger exists: {DAILY_LEDGER}")
    fields = [
        "trading_date_utc",
        "case_alias",
        "signal_at",
        "session",
        "compiled_family",
        "route",
        "confirmation_at",
        "signal_final_state",
        "entry_final_state",
        "intermediate_identity",
        "fill",
        "stop",
        "target",
        "target_room_r",
        "r1_disposition",
        "control_net_r",
        "v1_net_r",
        "failed_v2_net_r",
        "r1_net_r",
        "r1_equity_usd",
        "final_row_sha256",
    ]
    with DAILY_LEDGER.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            r1 = row["router_v2_r1"]
            route = r1.get("route") or {}
            geometry = r1.get("geometry") or {}
            signal_destination = r1.get("signal_destination_hierarchy") or {}
            entry_destination = r1.get("entry_destination_hierarchy") or {}
            writer.writerow(
                {
                    "trading_date_utc": row["trading_date_utc"],
                    "case_alias": row["case_alias"],
                    "signal_at": row["control"]["signal_at"],
                    "session": r1.get("session"),
                    "compiled_family": r1.get("compiled_family"),
                    "route": route.get("route"),
                    "confirmation_at": route.get("confirmation_at"),
                    "signal_final_state": (signal_destination.get("final") or {}).get("lifecycle_state"),
                    "entry_final_state": (entry_destination.get("final") or {}).get("lifecycle_state"),
                    "intermediate_identity": geometry.get("intermediate_destination_identity"),
                    "fill": geometry.get("fill"),
                    "stop": geometry.get("stop"),
                    "target": geometry.get("target"),
                    "target_room_r": geometry.get("target_room_r"),
                    "r1_disposition": r1["disposition"],
                    "control_net_r": result_value(lifecycle_result(row, "control")),
                    "v1_net_r": result_value(lifecycle_result(row, "router_v1")),
                    "failed_v2_net_r": result_value(lifecycle_result(row, "failed_v2")),
                    "r1_net_r": result_value(lifecycle_result(row, "router_v2_r1")),
                    "r1_equity_usd": row["router_v2_r1_equity_usd"],
                    "final_row_sha256": row["final_row_sha256"],
                }
            )


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gold Auction-Semantic Family Router V2-R1 — Result",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "This is an exposed implementation-correction regression with zero validation credit. It does not reject or validate the strategy.",
        "",
        "| Period | Control R | Router V1 R | Failed V2 R | V2-R1 trades | V2-R1 R | Win % | PF | DD R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("JANUARY", "FEBRUARY_TO_DATE", "MARCH", "APRIL", "MAY", "COMBINED"):
        block = result["periods"][key]
        r1 = block["router_v2_r1"]
        lines.append(
            f"| {key} | {block['control']['net_r']:+.4f} | {block['router_v1']['net_r']:+.4f} | {block['failed_v2']['net_r']:+.4f} | {r1['trades']} | {r1['net_r']:+.4f} | {100 * float(r1['win_rate'] or 0):.2f} | {r1['profit_factor']} | {r1['maximum_drawdown_r']:.4f} |"
        )
    combined = result["periods"]["COMBINED"]
    lines.extend(
        [
            "",
            "## Disposition",
            "",
            f"- V2-R1 minus failed V2: {combined['r1_delta_vs_failed_v2_r']:+.4f}R.",
            f"- V2-R1 minus Router V1: {combined['r1_delta_vs_v1_r']:+.4f}R.",
            f"- V2-R1 minus control: {combined['r1_delta_vs_control_r']:+.4f}R.",
            f"- Valid control winners rejected: {combined['valid_control_winners_rejected']} ({combined['valid_control_winners_rejected_r']:+.4f} control R).",
            f"- Avoided control losses: {combined['avoided_control_losses']} ({combined['avoided_control_loss_r']:+.4f} control R).",
            "- The sealed failed V2 remains an implementation-failure record, not a strategy rejection.",
            "- No fresh period was opened.",
            "",
            "The complete ledger is sealed in `research_artifacts/gold_auction_semantic_family_router_exposed_regression_v2_r1/daily_ledger.csv`.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, DAILY_LEDGER, FINAL_SEAL, REPORT):
        require(not path.exists(), f"One-shot output exists: {path}")
    controls = baseline.control_rows()
    baseline_rows = {str(row["case_alias"]): row for row in load_json(BASELINE_RESULT)["rows"]}
    v1_rows = {str(row["case_alias"]): row for row in load_json(V1_RESULT)["rows"]}
    failed_rows = {str(row["case_alias"]): row for row in load_json(FAILED_RESULT)["rows"]}
    identities = {str(row["case_alias"]) for row in controls}
    require(set(baseline_rows) == identities, "Baseline identities differ")
    require(set(v1_rows) == identities, "V1 identities differ")
    require(set(failed_rows) == identities, "Failed V2 identities differ")
    primary = run_side("primary", controls, baseline_rows, v1_rows, failed_rows)
    write_new_json(PRIMARY_RESULT, primary)
    reference = run_side("reference", controls, baseline_rows, v1_rows, failed_rows)
    write_new_json(REFERENCE_RESULT, reference)
    require(primary["rows"] == reference["rows"], "Primary/reference V2-R1 rows differ")
    rows = primary["rows"]
    require(len(rows) == 95, "V2-R1 row count differs")
    add_equity(rows)
    for row in rows:
        row["final_row_sha256"] = canonical_hash(row)
    filters = {
        "JANUARY": lambda value: value.startswith("2022-01"),
        "FEBRUARY_TO_DATE": lambda value: value.startswith("2022-02"),
        "MARCH": lambda value: value.startswith("2022-03"),
        "APRIL": lambda value: value.startswith("2022-04"),
        "MAY": lambda value: value.startswith("2022-05"),
        "COMBINED": lambda value: True,
    }
    periods = {
        key: comparison_block(
            [row for row in rows if predicate(str(row["trading_date_utc"]))]
        )
        for key, predicate in filters.items()
    }
    families = {
        family: metric_block(
            [row for row in rows if row["router_v2_r1"].get("compiled_family") == family],
            "router_v2_r1",
        )
        for family in FAMILIES
    }
    write_ledger(rows)
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_V2_R1_RESULT_1_0",
        "completed_at": now(),
        "verdict": "PASS_V2_R1_SEMANTIC_INTEGRATION_REPLAY_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "population_sha256": frozen["population_sha256"],
        "predecessors": frozen["predecessors"],
        "primary_reference_exact": True,
        "primary_rows_sha256": primary["row_set_sha256"],
        "reference_rows_sha256": reference["row_set_sha256"],
        "periods": periods,
        "families": families,
        "dispositions": dict(sorted(Counter(row["router_v2_r1"]["disposition"] for row in rows).items())),
        "rows": rows,
        "random_50_case_population_opened": False,
        "february_17_28_opened": False,
        "additional_dates_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "retuning_performed": False,
        "alternative_hierarchy_tested": False,
        "paid_acquisition": False,
    }
    final["result_sha256"] = canonical_hash(final)
    write_new_json(FINAL_RESULT, final)
    REPORT.write_text(markdown(final), encoding="utf-8", newline="\n")
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_V2_R1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "files": [
            file_record(path)
            for path in (
                PROTOCOL,
                DIAGNOSTIC,
                FREEZE,
                IMPLEMENTATION,
                TESTS,
                RUNNER,
                PRIMARY_RESULT,
                REFERENCE_RESULT,
                FINAL_RESULT,
                DAILY_LEDGER,
                REPORT,
            )
        ],
        "predecessors_untouched": verify_predecessors() == frozen["predecessors"],
        "primary_reference_exact": True,
        "population_dates": len(rows),
        "fresh_dates_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(FINAL_SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": final["verdict"],
                "combined": periods["COMBINED"],
                "families": families,
                "dispositions": final["dispositions"],
                "result_sha256": final["result_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

