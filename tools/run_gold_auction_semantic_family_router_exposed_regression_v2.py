#!/usr/bin/env python3
"""Freeze, replay, reproduce, and seal Auction-Semantic Family Router V2."""

from __future__ import annotations

import argparse
import copy
import csv
import gc
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_auction_family_router_exposed_regression_v1 as router_v1  # noqa: E402
import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.auction_family_router_v1 import (  # noqa: E402
    first_structural_repair_retest,
)
from gold_intel.analytics.auction_family_router_v2 import (  # noqa: E402
    direct_continuation_route,
    first_balance_boundary_reclaim,
    plan_trigger_event,
    planned_geometry,
    simulate_structural_management,
    trigger_is_fresh,
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
    pre_entry_disposition,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    classify_autonomous,
    latest_m1_at,
    spread,
)


PROTOCOL = ROOT / "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_EXPOSED_REGRESSION_V2.md"
IMPLEMENTATION = (
    ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_family_router_v2.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_family_router_v2.py"
RUNNER = Path(__file__).resolve()
COMPILER_V1 = (
    ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_plan_compiler_v1.py"
)
COMPILER_A = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "auction_plan_compiler_v1_semantic_amendment_a.py"
)
COMPILER_ROOT = (
    ROOT / "research_artifacts" / "gold_auction_plan_compiler_v1_semantic_amendment_a"
)
COMPILER_SEAL = COMPILER_ROOT / "final_seal.json"

BASELINE_ROOT = (
    ROOT / "research_artifacts" / "gold_day_by_day_auction_confirmation_exposed_regression_v1"
)
BASELINE_RESULT = BASELINE_ROOT / "final_result.json"
BASELINE_SEAL = BASELINE_ROOT / "final_seal.json"
BASELINE_SEMANTIC_SHA256 = "955db0688bf7b9b8f56e51e90b01424f581b7cf40886d53031611dd567fd5b7f"

V1_ROOT = ROOT / "research_artifacts" / "gold_auction_family_router_exposed_regression_v1"
V1_RESULT = V1_ROOT / "final_result.json"
V1_SEAL = V1_ROOT / "final_seal.json"
V1_SEMANTIC_SHA256 = "6a5427449742fac3666c3a7db22c01eb041aaa74392b14abd4162990b0d39588"

OUT = ROOT / "research_artifacts" / "gold_auction_semantic_family_router_exposed_regression_v2"
FREEZE = OUT / "prepath_freeze.json"
PRIMARY_RESULT = OUT / "router_v2.primary.json"
REFERENCE_RESULT = OUT / "router_v2.reference.json"
FINAL_RESULT = OUT / "final_result.json"
DAILY_LEDGER = OUT / "daily_ledger.csv"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_EXPOSED_REGRESSION_V2_REPORT.md"

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


def verify_list_seal(path: Path, *, semantic_path: Path, semantic_hash: str) -> dict[str, Any]:
    seal = load_json(path)
    submitted = seal.pop("seal_sha256")
    require(canonical_hash(seal) == submitted, f"Seal payload differs: {path}")
    seal["seal_sha256"] = submitted
    for record in seal["files"]:
        target = ROOT / record["path"]
        require(target.is_file(), f"Sealed file absent: {target}")
        require(target.stat().st_size == record["bytes"], f"Sealed size differs: {target}")
        require(sha256_file(target) == record["sha256"], f"Sealed hash differs: {target}")
    result = load_json(semantic_path)
    require(result["result_sha256"] == semantic_hash, f"Semantic result differs: {semantic_path}")
    return seal


def verify_compiler_seal() -> dict[str, Any]:
    require(COMPILER_SEAL.is_file(), "Compiler seal absent")
    seal = load_json(COMPILER_SEAL)
    submitted = seal.pop("seal_sha256")
    require(canonical_hash(seal) == submitted, "Compiler seal payload differs")
    seal["seal_sha256"] = submitted
    require(seal["status"] == "PASS_SEMANTIC_AMENDMENT_A_CERTIFICATION", "Compiler did not pass")
    for record in seal["files"].values():
        target = ROOT / record["path"]
        require(target.is_file(), f"Compiler artifact absent: {target}")
        require(target.stat().st_size == record["bytes"], f"Compiler artifact size differs: {target}")
        require(sha256_file(target) == record["sha256"], f"Compiler artifact hash differs: {target}")
    return seal


def verify_predecessors() -> dict[str, Any]:
    baseline.verify_static_inputs()
    baseline_seal = verify_list_seal(
        BASELINE_SEAL,
        semantic_path=BASELINE_RESULT,
        semantic_hash=BASELINE_SEMANTIC_SHA256,
    )
    v1_seal = verify_list_seal(
        V1_SEAL,
        semantic_path=V1_RESULT,
        semantic_hash=V1_SEMANTIC_SHA256,
    )
    compiler_seal = verify_compiler_seal()
    return {
        "baseline": {
            "semantic_result_sha256": BASELINE_SEMANTIC_SHA256,
            "seal_sha256": baseline_seal["seal_sha256"],
            "file_sha256": sha256_file(BASELINE_RESULT),
        },
        "router_v1": {
            "semantic_result_sha256": V1_SEMANTIC_SHA256,
            "seal_sha256": v1_seal["seal_sha256"],
            "file_sha256": sha256_file(V1_RESULT),
        },
        "compiler": {
            "seal_sha256": compiler_seal["seal_sha256"],
            "implementation_sha256": sha256_file(COMPILER_A),
        },
    }


def synthetic_bar(
    opened: datetime,
    minutes: int,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> dict[str, Any]:
    closed = opened + timedelta(minutes=minutes)
    return {
        "open_at": iso(opened),
        "close_at": iso(closed),
        "available_at": iso(closed),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "source_record_hash": canonical_hash([iso(opened), minutes, open_, high, low, close]),
    }


def synthetic_proof() -> dict[str, Any]:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    from gold_intel.analytics.auction_family_router_v2 import (  # local import keeps proof explicit
        balance_boundary_reclaim_qualifies,
    )

    checks = {
        "long_named_boundary": balance_boundary_reclaim_qualifies(
            synthetic_bar(point, 5, 99.8, 101, 98.9, 100.5),
            boundary=100.0,
            direction="LONG",
        ),
        "middle_wick_rejected": not balance_boundary_reclaim_qualifies(
            synthetic_bar(point, 5, 100.2, 101, 99.1, 100.6),
            boundary=99.0,
            direction="LONG",
        ),
        "short_named_boundary": balance_boundary_reclaim_qualifies(
            synthetic_bar(point, 5, 100.2, 101.1, 99, 99.5),
            boundary=100.0,
            direction="SHORT",
        ),
        "actual_fill_room_boundary": planned_geometry(
            fill=100, stop=98, target=103, cost_per_ounce=0.1, direction="LONG"
        )["passes_actual_fill_1p5r"],
        "consumed_room_rejected": not planned_geometry(
            fill=102, stop=98, target=103, cost_per_ounce=0.1, direction="LONG"
        )["passes_actual_fill_1p5r"],
        "whole_ounce_gate": not planned_geometry(
            fill=100, stop=40, target=200, cost_per_ounce=0.1, direction="LONG"
        )["passes_whole_ounce_risk"],
    }
    preentry = pre_entry_disposition(
        [synthetic_bar(point + timedelta(minutes=1), 1, 100, 112, 88, 101)],
        signal_at=point,
        fill_at=point + timedelta(minutes=2),
        stop=90,
        target=110,
        direction="LONG",
    )
    checks["preentry_stop_first"] = (
        preentry["disposition"] == "ORIGINAL_STOP_TOUCHED_PRE_ENTRY"
        and preentry["same_bar_target_touch"] is True
    )
    fill_bar = first_complete_m1_after(
        [
            synthetic_bar(point + timedelta(minutes=5), 1, 100, 101, 99, 100),
            synthetic_bar(point + timedelta(minutes=6), 1, 100, 101, 99, 100),
        ],
        point + timedelta(minutes=5),
    )
    checks["strict_latency"] = fill_bar is not None and fill_bar["open_at"] == iso(point + timedelta(minutes=6))
    require(all(checks.values()), f"Router V2 synthetic proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    for path in (PROTOCOL, IMPLEMENTATION, TESTS, RUNNER, COMPILER_V1, COMPILER_A):
        require(path.is_file(), f"Required implementation absent: {path}")
    predecessors = verify_predecessors()
    controls = baseline.control_rows()
    dates = [str(row["trading_date_utc"]) for row in controls]
    require(len(dates) == 95 and len(set(dates)) == 95, "Expected 95 unique dates")
    proof = synthetic_proof()
    files = [
        PROTOCOL,
        IMPLEMENTATION,
        TESTS,
        RUNNER,
        COMPILER_V1,
        COMPILER_A,
        COMPILER_SEAL,
        BASELINE_RESULT,
        BASELINE_SEAL,
        V1_RESULT,
        V1_SEAL,
    ]
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_EXPOSED_REGRESSION_V2_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_V2_PATH_REPLAY",
        "files": [file_record(path) for path in files],
        "predecessors": predecessors,
        "dates": dates,
        "date_counts": dict(sorted(Counter(value[:7] for value in dates).items())),
        "population_sha256": canonical_hash(
            [{"case_alias": row["case_alias"], "trading_date_utc": row["trading_date_utc"]} for row in controls]
        ),
        "outcome_blind_compiler_coverage_audit": {
            "signals": 60,
            "executable_plans": 57,
            "unresolved_plans": 3,
            "compiled_families": {
                "CONTINUATION_WITH_ROOM": 34,
                "STRUCTURAL_REPAIR": 16,
                "RANGE_ROTATION": 7,
            },
            "integrity_violations": 0,
        },
        "policy": {
            "learned_geometry_used": False,
            "actual_fill_target_room_minimum_r": 1.5,
            "risk_usd": RISK_USD,
            "freshness": {"M5_minutes": 5, "M15_minutes": 15},
            "range_reclaim_maximum_m5_bars": 6,
            "retest_maximum_m5_bars": 12,
            "numeric_break_even_used": False,
            "runner_fraction_continuation": 0.20,
            "structural_trail": "NEW_ALIGNED_M5_BREAK_THEN_M15_AFTER_DESTINATION_ACCEPTANCE",
        },
        "synthetic_proof": proof,
        "random_50_case_population_opened": False,
        "february_17_28_opened": False,
        "additional_dates_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(json.dumps({"status": payload["status"], "dates": len(dates), "predecessors": predecessors, "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "V2 prepath freeze absent")
    payload = load_json(FREEZE)
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "V2 freeze payload differs")
    payload["freeze_sha256"] = submitted
    require(payload["status"] == "SEALED_BEFORE_V2_PATH_REPLAY", "V2 freeze status differs")
    for record in payload["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen hash differs: {path}")
    current = verify_predecessors()
    require(current == payload["predecessors"], "Predecessor rollback state differs")
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
        "geometry": extra.pop("geometry", None),
        "classification": extra.pop("classification", None),
        "result": None,
        "post_exit_diagnostic": None,
        **extra,
    }


def regeometry_classification(
    classification: dict[str, Any],
    *,
    fill: float,
    stop: float,
    target: float,
    cost_per_ounce: float,
    family: str,
    plan_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    direction = str(classification["direction"])
    geometry = planned_geometry(
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=cost_per_ounce,
        direction=direction,
    )
    require(geometry["geometry_valid"], "Cannot classify invalid actual-fill geometry")
    result = copy.deepcopy(classification)
    result.update(
        {
            "ruleset": f"{classification['ruleset']}::AUCTION_SEMANTIC_ROUTER_V2",
            "family": family,
            "fill": float(fill),
            "stop": float(stop),
            "target": float(target),
            "structural_price_risk_per_ounce": geometry["structural_risk_per_ounce"],
            "cost_per_ounce": float(cost_per_ounce),
            "planned_loss_per_ounce": geometry["planned_loss_per_ounce"],
            "quantity_ounces": geometry["quantity_ounces"],
            "auction_plan_sha256": plan_sha256,
            "classification_hash": None,
        }
    )
    result["classification_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "classification_hash"}
    )
    return result, geometry


def route_for_plan(
    *,
    plan: dict[str, Any],
    stream: dict[str, Any],
    signal_at: str,
    session_end: datetime,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    governing = plan["components"]["governing_auction"]
    family = str(governing["family"])
    event = plan_trigger_event(plan)
    require(event is not None, "Executable plan lacks usable trigger event")
    if family == "CONTINUATION_WITH_ROOM" and trigger_is_fresh(event, signal_at=signal_at):
        return direct_continuation_route(event, signal_at=signal_at), None, False
    if family in {"CONTINUATION_WITH_ROOM", "STRUCTURAL_REPAIR"}:
        route = first_structural_repair_retest(
            stream["timeframes"]["5m"],
            event=event,
            signal_at=signal_at,
            session_end=session_end,
            direction="LONG",
            maximum_bars=12,
        )
        if route["disposition"] != "CONFIRMED":
            prefix = "INHERITED_CONTINUATION" if family == "CONTINUATION_WITH_ROOM" else "STRUCTURAL_REPAIR"
            return route, f"{prefix}::{route['disposition']}", True
        route["route"] = (
            "INHERITED_CONTINUATION_M5_RETEST"
            if family == "CONTINUATION_WITH_ROOM"
            else "STRUCTURAL_REPAIR_M5_RETEST"
        )
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
        direction="LONG",
        maximum_bars=6,
    )
    if route is None:
        return None, "RANGE_ROTATION::NO_NAMED_BOUNDARY_RECLAIM_WITHIN_6_M5", True
    return route, None, True


def post_exit_diagnostic(
    *, result: dict[str, Any], geometry: dict[str, Any], stream: dict[str, Any]
) -> dict[str, Any] | None:
    if float(result["net_r50"]) >= -WIN_EPSILON:
        return None
    final = parse_dt(result["final_at"])
    fill = float(geometry["fill"])
    stop = float(geometry["stop"])
    target = float(geometry["target"])
    risk = fill - stop
    path = [
        row
        for row in stream["timeframes"]["1m"]
        if row.get("complete") is True and parse_dt(row["open_at"]) > final
    ]
    maximum = max([0.0] + [(float(row["high"]) - fill) / risk for row in path])
    payload = {
        "later_plus_1r": any(float(row["high"]) >= fill + risk for row in path),
        "later_destination": any(float(row["high"]) >= target for row in path),
        "post_exit_maximum_price_r": maximum,
    }
    payload["diagnostic_hash"] = canonical_hash(payload)
    return payload


def v2_lifecycle(*, control: dict[str, Any], stream: dict[str, Any]) -> dict[str, Any]:
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

    reference = float(old_geometry["reference_close"])
    plan = compile_auction_plan_v1_semantic_amendment_a(
        stream=stream,
        decision_at=signal_at,
        direction="LONG",
        entry_reference=reference,
    )
    violations = plan_integrity_violations(plan)
    require(not violations, f"Auction plan integrity failed: {control['case_alias']} {violations}")
    if plan["disposition"] != "EXECUTABLE_PLAN":
        return empty_lifecycle(
            "NO_TRADE_UNRESOLVED::" + ",".join(plan["missing_components"]),
            session=session,
            plan=plan,
        )
    family = str(plan["components"]["governing_auction"]["family"])
    require(family in FAMILIES, f"Unknown compiled family: {family}")
    stop = float(plan["components"]["structural_invalidation"]["price"])
    target = float(plan["components"]["liquidity_destination"]["level"])
    signal_cost = float(old_geometry["cost_per_ounce"])
    signal_classification = classify_autonomous(
        stream=stream,
        signal_at=signal_at,
        family=family,
        fill=reference,
        stop=stop,
        target=target,
        cost_per_ounce=signal_cost,
    )
    if not signal_classification["admitted"]:
        return empty_lifecycle(
            f"COMPILED_FAMILY_CONTEXT_REJECTED::{signal_classification['primary_disposition']}",
            session=session,
            compiled_family=family,
            plan=plan,
            classification=signal_classification,
        )
    route, route_failure, delayed = route_for_plan(
        plan=plan,
        stream=stream,
        signal_at=signal_at,
        session_end=end,
    )
    if route_failure is not None:
        return empty_lifecycle(
            route_failure,
            session=session,
            compiled_family=family,
            plan=plan,
            route=route,
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
                classification=signal_classification,
            )
        fill_at = iso(fill_bar["open_at"])
        preentry = pre_entry_disposition(
            stream["timeframes"]["1m"],
            signal_at=signal_at,
            fill_at=fill_at,
            stop=stop,
            target=target,
            direction="LONG",
        )
        if preentry["disposition"] != "CLEAR_TO_DELAYED_ENTRY":
            return empty_lifecycle(
                str(preentry["disposition"]),
                session=session,
                compiled_family=family,
                plan=plan,
                route=route,
                pre_entry=preentry,
                classification=signal_classification,
            )
        decision_bar = latest_m1_at(stream, confirmation_at)
        require(decision_bar is not None, "Confirmation decision bar absent")
        fill = float(fill_bar["open"]) + spread(fill_bar) / 2.0 + SLIPPAGE_USD_PER_OUNCE
        cost_per_ounce = spread(decision_bar) + 2.0 * SLIPPAGE_USD_PER_OUNCE
    else:
        fill_at = str(old_geometry["fill_at"])
        fill = float(old_geometry["fill"])
        cost_per_ounce = signal_cost
        preentry = {
            "disposition": "DIRECT_ORIGINAL_FILL",
            "at": fill_at,
            "same_bar_target_touch": False,
            "bar_hash": None,
        }

    geometry = planned_geometry(
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=cost_per_ounce,
        direction="LONG",
    )
    geometry_payload = {
        "fill_at": fill_at,
        "fill": fill,
        "stop": stop,
        "target": target,
        "cost_per_ounce": cost_per_ounce,
        "invalidation_identity": plan["components"]["structural_invalidation"]["identity"],
        "destination_identity": plan["components"]["liquidity_destination"]["identity"],
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
            geometry=geometry_payload,
            classification=signal_classification,
        )
    actual_classification, geometry = regeometry_classification(
        signal_classification,
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=cost_per_ounce,
        family=family,
        plan_sha256=str(plan["plan_sha256"]),
    )
    if not geometry["passes_actual_fill_1p5r"]:
        return empty_lifecycle(
            "ACTUAL_FILL_TARGET_ROOM_LT_1P5R",
            session=session,
            compiled_family=family,
            plan=plan,
            route=route,
            pre_entry=preentry,
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
            geometry=geometry_payload,
            classification=actual_classification,
        )
    result = simulate_structural_management(
        classification=actual_classification,
        stream=stream,
        fill_at=fill_at,
    )
    diagnostic = post_exit_diagnostic(result=result, geometry=geometry_payload, stream=stream)
    return {
        "admitted": True,
        "disposition": str(result["resolution"]),
        "session": session,
        "compiled_family": family,
        "plan": plan,
        "route": route,
        "pre_entry": preentry,
        "geometry": geometry_payload,
        "classification": actual_classification,
        "result": result,
        "post_exit_diagnostic": diagnostic,
    }


def result_value(result: dict[str, Any] | None, field: str = "net_r50") -> float:
    return 0.0 if result is None or not result.get("executed") else float(result[field])


def run_side(
    side: str,
    controls: list[dict[str, Any]],
    baseline_by_alias: dict[str, dict[str, Any]],
    v1_by_alias: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    streams = baseline.load_all_streams(side)
    require(set(streams) == {row["case_alias"] for row in controls}, "Stream identities differ")
    rows: list[dict[str, Any]] = []
    for control in controls:
        alias = str(control["case_alias"])
        stream = streams[alias]
        lifecycle = v2_lifecycle(control=control, stream=stream)
        baseline_row = baseline_by_alias[alias]
        prior_row = v1_by_alias[alias]
        row: dict[str, Any] = {
            "case_alias": alias,
            "trading_date_utc": control["trading_date_utc"],
            "morning_plan": baseline.morning_plan(stream),
            "control": copy.deepcopy(baseline_row["control"]),
            "rigid_confirmation": copy.deepcopy(baseline_row["corrected"]),
            "router_v1": copy.deepcopy(prior_row["family_router"]),
            "router_v2": lifecycle,
        }
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
    output: dict[str, Any] = {
        "version": "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_EXPOSED_REGRESSION_V2_SIDE_1_0",
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
    return output


def lifecycle_result(row: dict[str, Any], policy: str) -> dict[str, Any] | None:
    if policy == "control":
        return row["control"]["result"]
    if policy == "rigid":
        return row["rigid_confirmation"]["effective_result"]
    if policy == "router_v1":
        return row["router_v1"]["effective_result"]
    if policy == "router_v2":
        return row["router_v2"]["result"]
    raise ValueError(policy)


def longest_streak(values: list[float], positive: bool) -> int:
    best = current = 0
    for value in values:
        match = value > WIN_EPSILON if positive else value < -WIN_EPSILON
        current = current + 1 if match else 0
        best = max(best, current)
    return best


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
        "no_trade_days": len(rows) - len(executed),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(values) - len(wins) - len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "expectancy_r": sum(values) / len(values) if values else 0.0,
        "profit_factor": positive / negative if negative else None,
        "profit_factor_unbounded": bool(positive and not negative),
        "net_r": sum(values),
        "net_usd": sum(float(result["net_usd"]) for result in executed),
        "maximum_drawdown_r": drawdown,
        "longest_winning_streak": longest_streak(values, True),
        "longest_losing_streak": longest_streak(values, False),
        "trades_per_month": len(executed) / len({row["trading_date_utc"][:7] for row in rows}) if rows else 0.0,
        "stressed_1p5x_cost_net_r": sum(float(result["stressed_1_5x_cost_r50"]) for result in executed),
    }


def comparison_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    control_winners = [row for row in rows if result_value(lifecycle_result(row, "control")) > WIN_EPSILON]
    retained = [row for row in control_winners if result_value(lifecycle_result(row, "router_v2")) > WIN_EPSILON]
    rejected = [row for row in control_winners if lifecycle_result(row, "router_v2") is None]
    avoided_losses = [
        row for row in rows
        if result_value(lifecycle_result(row, "control")) < -WIN_EPSILON
        and lifecycle_result(row, "router_v2") is None
    ]
    diagnostics = [
        row["router_v2"]["post_exit_diagnostic"]
        for row in rows
        if row["router_v2"].get("post_exit_diagnostic") is not None
    ]
    blocks = {policy: metric_block(rows, policy) for policy in ("control", "rigid", "router_v1", "router_v2")}
    return {
        **blocks,
        "v2_delta_vs_control_r": blocks["router_v2"]["net_r"] - blocks["control"]["net_r"],
        "v2_delta_vs_v1_r": blocks["router_v2"]["net_r"] - blocks["router_v1"]["net_r"],
        "control_winner_count": len(control_winners),
        "winner_retention_count": len(retained),
        "winner_retention_rate": len(retained) / len(control_winners) if control_winners else None,
        "valid_control_winners_rejected": len(rejected),
        "valid_control_winners_rejected_r": sum(result_value(lifecycle_result(row, "control")) for row in rejected),
        "avoided_loss_count": len(avoided_losses),
        "avoided_loss_control_r": sum(result_value(lifecycle_result(row, "control")) for row in avoided_losses),
        "post_exit_later_plus_1r_count": sum(bool(item["later_plus_1r"]) for item in diagnostics),
        "post_exit_later_destination_count": sum(bool(item["later_destination"]) for item in diagnostics),
    }


def add_equity(rows: list[dict[str, Any]]) -> None:
    equity = {key: STARTING_EQUITY_USD for key in ("control", "rigid", "router_v1", "router_v2")}
    for row in rows:
        for key in equity:
            equity[key] += result_value(lifecycle_result(row, key), "net_usd")
            row[f"{key}_equity_usd"] = equity[key]


def write_ledger(rows: list[dict[str, Any]]) -> None:
    require(not DAILY_LEDGER.exists(), f"Append-only ledger exists: {DAILY_LEDGER}")
    fields = [
        "trading_date_utc", "case_alias", "signal_at", "session", "compiled_family",
        "plan_disposition", "governing_auction_identity", "invalidation_identity",
        "destination_identity", "route", "confirmation_at", "fill", "stop", "target",
        "target_room_r", "v2_disposition", "control_net_r", "rigid_net_r", "v1_net_r",
        "v2_net_r", "v2_equity_usd", "final_row_sha256",
    ]
    with DAILY_LEDGER.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            v2 = row["router_v2"]
            plan = v2.get("plan") or {}
            components = plan.get("components") or {}
            geometry = v2.get("geometry") or {}
            route = v2.get("route") or {}
            writer.writerow(
                {
                    "trading_date_utc": row["trading_date_utc"],
                    "case_alias": row["case_alias"],
                    "signal_at": row["control"]["signal_at"],
                    "session": v2.get("session"),
                    "compiled_family": v2.get("compiled_family"),
                    "plan_disposition": plan.get("disposition"),
                    "governing_auction_identity": (components.get("governing_auction") or {}).get("identity"),
                    "invalidation_identity": geometry.get("invalidation_identity"),
                    "destination_identity": geometry.get("destination_identity"),
                    "route": route.get("route"),
                    "confirmation_at": route.get("confirmation_at"),
                    "fill": geometry.get("fill"),
                    "stop": geometry.get("stop"),
                    "target": geometry.get("target"),
                    "target_room_r": geometry.get("target_room_r"),
                    "v2_disposition": v2["disposition"],
                    "control_net_r": result_value(lifecycle_result(row, "control")),
                    "rigid_net_r": result_value(lifecycle_result(row, "rigid")),
                    "v1_net_r": result_value(lifecycle_result(row, "router_v1")),
                    "v2_net_r": result_value(lifecycle_result(row, "router_v2")),
                    "v2_equity_usd": row["router_v2_equity_usd"],
                    "final_row_sha256": row["final_row_sha256"],
                }
            )


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gold Auction-Semantic Family Router Exposed Regression V2 - Result",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "This is an exposed matched-data regression with zero validation credit. Every predecessor remains byte-for-byte restorable.",
        "",
        "| Period | Days | Control R | Rigid R | Router V1 R | V2 trades | V2 R | Win % | Exp R | PF | DD R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("JANUARY", "FEBRUARY_TO_DATE", "MARCH", "APRIL", "MAY", "COMBINED"):
        block = result["periods"][key]
        v2 = block["router_v2"]
        lines.append(
            f"| {key} | {v2['days']} | {block['control']['net_r']:+.4f} | {block['rigid']['net_r']:+.4f} | {block['router_v1']['net_r']:+.4f} | {v2['trades']} | {v2['net_r']:+.4f} | {100 * float(v2['win_rate'] or 0):.2f} | {v2['expectancy_r']:+.4f} | {v2['profit_factor']} | {v2['maximum_drawdown_r']:.4f} |"
        )
    lines.extend(["", "## Compiled-family contributions", "", "| Family | Rows | Trades | Net R | PF |", "|---|---:|---:|---:|---:|"])
    for family in FAMILIES:
        block = result["families"][family]["router_v2"]
        lines.append(f"| {family} | {block['days']} | {block['trades']} | {block['net_r']:+.4f} | {block['profit_factor']} |")
    combined = result["periods"]["COMBINED"]
    lines.extend(
        [
            "",
            "## Matched verdict",
            "",
            f"- Control: {combined['control']['net_r']:+.4f}R.",
            f"- Rigid confirmation: {combined['rigid']['net_r']:+.4f}R.",
            f"- Router V1: {combined['router_v1']['net_r']:+.4f}R.",
            f"- Auction-semantic Router V2: {combined['router_v2']['net_r']:+.4f}R.",
            f"- V2 minus V1: {combined['v2_delta_vs_v1_r']:+.4f}R.",
            f"- Valid control winners rejected by V2: {combined['valid_control_winners_rejected']} ({combined['valid_control_winners_rejected_r']:+.4f} control R).",
            f"- Losing V2 trades later reaching +1R / destination: {combined['post_exit_later_plus_1r_count']} / {combined['post_exit_later_destination_count']}.",
            "",
            "The complete ledger is sealed in `research_artifacts/gold_auction_semantic_family_router_exposed_regression_v2/daily_ledger.csv`.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, DAILY_LEDGER, FINAL_SEAL, REPORT):
        require(not path.exists(), f"One-shot output exists: {path}")
    controls = baseline.control_rows()
    baseline_result = load_json(BASELINE_RESULT)
    prior_result = load_json(V1_RESULT)
    baseline_by_alias = {str(row["case_alias"]): row for row in baseline_result["rows"]}
    v1_by_alias = {str(row["case_alias"]): row for row in prior_result["rows"]}
    identities = {str(row["case_alias"]) for row in controls}
    require(set(baseline_by_alias) == identities and set(v1_by_alias) == identities, "Predecessor identities differ")
    primary = run_side("primary", controls, baseline_by_alias, v1_by_alias)
    write_new_json(PRIMARY_RESULT, primary)
    reference = run_side("reference", controls, baseline_by_alias, v1_by_alias)
    write_new_json(REFERENCE_RESULT, reference)
    require(primary["rows"] == reference["rows"], "Primary/reference V2 rows differ")
    rows = primary["rows"]
    require(len(rows) == 95, "V2 row count differs")
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
        key: comparison_block([row for row in rows if predicate(row["trading_date_utc"])])
        for key, predicate in filters.items()
    }
    families = {
        family: comparison_block([row for row in rows if row["router_v2"].get("compiled_family") == family])
        for family in FAMILIES
    }
    write_ledger(rows)
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_EXPOSED_REGRESSION_V2_RESULT_1_0",
        "completed_at": now(),
        "verdict": "COMPLETE_EXPOSED_AUCTION_SEMANTIC_ROUTER_V2_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "population_sha256": frozen["population_sha256"],
        "predecessors": frozen["predecessors"],
        "primary_reference_exact": True,
        "primary_rows_sha256": primary["row_set_sha256"],
        "reference_rows_sha256": reference["row_set_sha256"],
        "periods": periods,
        "families": families,
        "dispositions": dict(sorted(Counter(row["router_v2"]["disposition"] for row in rows).items())),
        "compiled_plan_dispositions": dict(
            sorted(
                Counter(
                    (row["router_v2"].get("plan") or {}).get("disposition", "NO_PLAN")
                    for row in rows
                ).items()
            )
        ),
        "rows": rows,
        "random_50_case_population_opened": False,
        "february_17_28_opened": False,
        "additional_dates_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "retuning_performed": False,
        "alternative_thresholds_tested": False,
        "paid_acquisition": False,
    }
    final["result_sha256"] = canonical_hash(final)
    write_new_json(FINAL_RESULT, final)
    REPORT.write_text(markdown(final), encoding="utf-8", newline="\n")
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_SEMANTIC_FAMILY_ROUTER_EXPOSED_REGRESSION_V2_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "files": [
            file_record(path)
            for path in (PROTOCOL, FREEZE, IMPLEMENTATION, TESTS, RUNNER, PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, DAILY_LEDGER, REPORT)
        ],
        "predecessors_untouched": verify_predecessors() == frozen["predecessors"],
        "primary_reference_exact": True,
        "population_dates": len(rows),
        "random_50_case_population_opened": False,
        "february_17_28_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
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
                "families": {key: value["router_v2"] for key, value in families.items()},
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
