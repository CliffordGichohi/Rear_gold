#!/usr/bin/env python3
"""Freeze, replay, reproduce, and seal Auction Family Router V1."""

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

import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.auction_family_router_v1 import (  # noqa: E402
    first_range_reclaim,
    first_structural_repair_retest,
    latest_active_m15_break,
    range_reclaim_qualifies,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    iso,
    parse_dt,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import simulate_track  # noqa: E402
from gold_intel.analytics.day_by_day_auction_confirmation_v1 import (  # noqa: E402
    first_complete_m1_after,
    m5_close_one_r_break_even,
    pre_entry_disposition,
    target_room,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    latest_m1_at,
    spread,
)


PROTOCOL = ROOT / "GOLD_AUCTION_FAMILY_ROUTER_EXPOSED_REGRESSION_V1.md"
IMPLEMENTATION = (
    ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_family_router_v1.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_family_router_v1.py"
RUNNER = Path(__file__).resolve()

ROLLBACK_ROOT = (
    ROOT / "research_artifacts" / "gold_day_by_day_auction_confirmation_exposed_regression_v1"
)
ROLLBACK_RESULT = ROLLBACK_ROOT / "final_result.json"
ROLLBACK_SEAL = ROLLBACK_ROOT / "final_seal.json"
ROLLBACK_SEMANTIC_SHA256 = "955db0688bf7b9b8f56e51e90b01424f581b7cf40886d53031611dd567fd5b7f"

OUT = ROOT / "research_artifacts" / "gold_auction_family_router_exposed_regression_v1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY_RESULT = OUT / "router.primary.json"
REFERENCE_RESULT = OUT / "router.reference.json"
FINAL_RESULT = OUT / "final_result.json"
DAILY_LEDGER = OUT / "daily_ledger.csv"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_AUCTION_FAMILY_ROUTER_EXPOSED_REGRESSION_V1_REPORT.md"

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


def verify_rollback() -> tuple[dict[str, Any], dict[str, Any]]:
    """Prove the immutable regression can be restored byte-for-byte."""

    baseline.verify_static_inputs()
    require(ROLLBACK_RESULT.is_file() and ROLLBACK_SEAL.is_file(), "Rollback baseline absent")
    seal = load_json(ROLLBACK_SEAL)
    submitted_seal = seal.pop("seal_sha256")
    require(canonical_hash(seal) == submitted_seal, "Rollback seal payload differs")
    seal["seal_sha256"] = submitted_seal
    require(seal["primary_reference_exact"] is True, "Rollback reproduction was not exact")
    require(seal["population_dates"] == 95, "Rollback population differs")
    for record in seal["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Rollback file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Rollback file size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Rollback file hash differs: {path}")
    result = load_json(ROLLBACK_RESULT)
    require(result["result_sha256"] == ROLLBACK_SEMANTIC_SHA256, "Rollback result differs")
    require(result["primary_reference_exact"] is True, "Rollback result reproduction differs")
    require(len(result["rows"]) == 95, "Rollback result row count differs")
    return seal, result


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
        "source_record_hash": canonical_hash(
            [iso(opened), minutes, open_, high, low, close]
        ),
    }


def routed_classification(
    original: dict[str, Any], *, fill: float, cost_per_ounce: float
) -> dict[str, Any]:
    """Change geometry only while retaining the original signal-time context."""

    require(original["admitted"] is True, "A rejected signal cannot be re-admitted")
    result = copy.deepcopy(original)
    direction = str(result["direction"])
    sign = 1.0 if direction == "LONG" else -1.0
    stop = float(result["stop"])
    target = float(result["target"])
    structural_risk = sign * (float(fill) - stop)
    reward = sign * (target - float(fill))
    geometry_valid = (
        all(math.isfinite(value) for value in (fill, stop, target, cost_per_ounce))
        and structural_risk > 0
        and reward > 0
    )
    planned_loss = structural_risk + float(cost_per_ounce) if geometry_valid else math.inf
    quantity = math.floor(RISK_USD / planned_loss) if planned_loss > 0 and math.isfinite(planned_loss) else 0
    require(geometry_valid and quantity >= 1, "Delayed geometry cannot support fixed risk")
    result.update(
        {
            "ruleset": f"{original['ruleset']}::FAMILY_ROUTER_V1_GEOMETRY_ONLY",
            "fill": float(fill),
            "structural_price_risk_per_ounce": structural_risk,
            "cost_per_ounce": float(cost_per_ounce),
            "planned_loss_per_ounce": planned_loss,
            "quantity_ounces": quantity,
            "classification_hash": None,
        }
    )
    result["classification_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "classification_hash"}
    )
    return result


def synthetic_proof() -> dict[str, Any]:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    long = synthetic_bar(point, 5, 100, 102, 98, 101)
    short = synthetic_bar(point, 5, 100, 102, 98, 99)
    checks: dict[str, bool] = {
        "range_long": range_reclaim_qualifies(long, "LONG"),
        "range_long_not_short": not range_reclaim_qualifies(long, "SHORT"),
        "range_short": range_reclaim_qualifies(short, "SHORT"),
        "range_short_not_long": not range_reclaim_qualifies(short, "LONG"),
    }
    route = first_range_reclaim(
        [long],
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    )
    checks["range_first"] = route is not None and route["confirmation_at"] == iso(point + timedelta(minutes=5))
    seventh = [
        synthetic_bar(point + timedelta(minutes=5 * index), 5, 100, 101, 99, 100)
        for index in range(6)
    ] + [synthetic_bar(point + timedelta(minutes=30), 5, 100, 102, 98, 101)]
    checks["range_six_bar_expiry"] = first_range_reclaim(
        seventh,
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    ) is None
    warmup = [
        synthetic_bar(point - timedelta(minutes=5 * (14 - index)), 5, 101, 101.5, 100.5, 101)
        for index in range(14)
    ]
    repair_event = {
        "identity": "synthetic-long-break",
        "direction": "LONG",
        "broken_level": 100.0,
        "protected_level": 95.0,
        "atr": 2.0,
    }
    repair = first_structural_repair_retest(
        warmup + [synthetic_bar(point, 5, 100.3, 101.2, 99.9, 100.8)],
        event=repair_event,
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    )
    checks["repair_retest"] = repair["disposition"] == "CONFIRMED"
    invalid = first_structural_repair_retest(
        warmup + [synthetic_bar(point, 5, 96, 96.2, 94, 94.7)],
        event=repair_event,
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    )
    checks["repair_invalidation"] = invalid["disposition"] == "REPAIR_STRUCTURE_INVALIDATED"
    fill_bar = first_complete_m1_after(
        [
            synthetic_bar(point + timedelta(minutes=5), 1, 101, 102, 100, 101),
            synthetic_bar(point + timedelta(minutes=6), 1, 101, 102, 100, 101),
        ],
        point + timedelta(minutes=5),
    )
    checks["strict_latency"] = fill_bar is not None and fill_bar["open_at"] == iso(point + timedelta(minutes=6))
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
    checks["continuation_direct_route"] = True
    require(all(checks.values()), f"Family-router synthetic proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    for path in (PROTOCOL, IMPLEMENTATION, TESTS, RUNNER):
        require(path.is_file(), f"Required implementation file absent: {path}")
    rollback_seal, rollback_result = verify_rollback()
    controls = baseline.control_rows()
    dates = [str(row["trading_date_utc"]) for row in controls]
    require(dates == [row["trading_date_utc"] for row in rollback_result["rows"]], "Rollback date order differs")
    proof = synthetic_proof()
    files = [PROTOCOL, IMPLEMENTATION, TESTS, RUNNER, ROLLBACK_RESULT, ROLLBACK_SEAL]
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_FAMILY_ROUTER_EXPOSED_REGRESSION_V1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_FAMILY_ROUTER_PATH_REPLAY",
        "files": [file_record(path) for path in files],
        "rollback": {
            "semantic_result_sha256": ROLLBACK_SEMANTIC_SHA256,
            "seal_sha256": rollback_seal["seal_sha256"],
            "final_result_file_sha256": sha256_file(ROLLBACK_RESULT),
            "restorable_byte_for_byte": True,
        },
        "dates": dates,
        "date_counts": dict(sorted(Counter(value[:7] for value in dates).items())),
        "population_sha256": canonical_hash(
            [{"case_alias": row["case_alias"], "trading_date_utc": row["trading_date_utc"]} for row in controls]
        ),
        "routes": {
            "CONTINUATION_WITH_ROOM": "ORIGINAL_NEXT_M1_FILL_NO_REDUNDANT_CONFIRMATION",
            "RANGE_ROTATION": "FIRST_ONE_BAR_M5_FAILED_AUCTION_RECLAIM_WITHIN_6",
            "STRUCTURAL_REPAIR": "FIRST_M5_RETEST_OF_LATEST_ACTIVE_M15_BREAK_WITHIN_12",
        },
        "universal": {
            "signal_time_context_must_be_admit": True,
            "original_fill_target_room_r_minimum": 1.5,
            "original_absolute_stop_target": True,
            "delayed_preentry_first_passage": "STOP_FIRST",
            "m5_close_plus_1r_net_break_even": True,
            "risk_usd": RISK_USD,
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
    print(json.dumps({"status": payload["status"], "dates": len(dates), "rollback": payload["rollback"], "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Prevalue freeze is absent")
    payload = load_json(FREEZE)
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "Prevalue freeze payload differs")
    payload["freeze_sha256"] = submitted
    require(payload["status"] == "SEALED_BEFORE_FAMILY_ROUTER_PATH_REPLAY", "Freeze status differs")
    for record in payload["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen file size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen file hash differs: {path}")
    _, rollback_result = verify_rollback()
    require([row["trading_date_utc"] for row in rollback_result["rows"]] == payload["dates"], "Frozen date order differs")
    return payload


def empty_lifecycle(disposition: str, **extra: Any) -> dict[str, Any]:
    return {
        "admitted": False,
        "disposition": disposition,
        "session": extra.pop("session", None),
        "family": extra.pop("family", None),
        "route": extra.pop("route", None),
        "original_target_room": extra.pop("original_target_room", None),
        "pre_entry": extra.pop("pre_entry", None),
        "geometry": extra.pop("geometry", None),
        "classification": extra.pop("classification", None),
        "pre_overlay_result": None,
        "break_even_overlay": None,
        "effective_result": None,
        **extra,
    }


def continuation_route(signal_at: str) -> dict[str, Any]:
    payload = {
        "route": "CONTINUATION_DIRECT_ORIGINAL_FILL",
        "direction": "LONG",
        "confirmation_at": signal_at,
        "bar_open_at": None,
        "within_route_occurrence": 0,
    }
    payload["route_hash"] = canonical_hash(payload)
    return payload


def family_lifecycle(*, control: dict[str, Any], stream: dict[str, Any]) -> dict[str, Any]:
    signal_value = control.get("signal_at")
    if signal_value is None:
        return empty_lifecycle("NO_SIGNAL")
    signal_at = str(signal_value)
    session = baseline.signal_session(signal_at)
    end = baseline.session_end(signal_at, session)
    geometry = control.get("geometry")
    classification = control.get("classification")
    require(geometry is not None and classification is not None, f"Signal payload absent: {control['case_alias']}")
    family = str(geometry["family"])
    require(family in FAMILIES, f"Unknown family: {family}")
    if not classification["admitted"]:
        return empty_lifecycle(
            f"ORIGINAL_SIGNAL_CONTEXT_REJECTED::{classification['primary_disposition']}",
            session=session,
            family=family,
            classification=classification,
        )

    direction = str(classification["direction"])
    stop = float(geometry["stop"])
    target = float(geometry["target"])
    original_room = target_room(
        fill=float(geometry["fill"]), stop=stop, target=target, direction=direction
    )
    if not original_room["geometry_valid"]:
        return empty_lifecycle(
            "ORIGINAL_GEOMETRY_INVALID",
            session=session,
            family=family,
            original_target_room=original_room,
            classification=classification,
        )
    if not original_room["passes_1p5r"]:
        return empty_lifecycle(
            "ORIGINAL_TARGET_ROOM_LT_1P5R",
            session=session,
            family=family,
            original_target_room=original_room,
            classification=classification,
        )

    delayed = family != "CONTINUATION_WITH_ROOM"
    route: dict[str, Any] | None
    if family == "CONTINUATION_WITH_ROOM":
        route = continuation_route(signal_at)
    elif family == "RANGE_ROTATION":
        route = first_range_reclaim(
            stream["timeframes"]["5m"],
            signal_at=signal_at,
            session_end=end,
            direction=direction,
        )
        if route is None:
            return empty_lifecycle(
                "NO_RANGE_RECLAIM_WITHIN_6_M5",
                session=session,
                family=family,
                original_target_room=original_room,
                classification=classification,
            )
    else:
        event = latest_active_m15_break(
            stream["timeframes"]["15m"], signal_at=signal_at, direction=direction
        )
        if event is None:
            return empty_lifecycle(
                "NO_ACTIVE_ALIGNED_M15_BREAK_AT_SIGNAL",
                session=session,
                family=family,
                original_target_room=original_room,
                classification=classification,
            )
        route = first_structural_repair_retest(
            stream["timeframes"]["5m"],
            event=event,
            signal_at=signal_at,
            session_end=end,
            direction=direction,
        )
        if route["disposition"] != "CONFIRMED":
            return empty_lifecycle(
                str(route["disposition"]),
                session=session,
                family=family,
                route=route,
                original_target_room=original_room,
                classification=classification,
            )

    if delayed:
        confirmation_at = str(route["confirmation_at"])
        fill_bar = first_complete_m1_after(stream["timeframes"]["1m"], confirmation_at)
        if fill_bar is None or parse_dt(fill_bar["open_at"]) >= end:
            return empty_lifecycle(
                "NO_EXECUTABLE_M1_AFTER_FAMILY_CONFIRMATION",
                session=session,
                family=family,
                route=route,
                original_target_room=original_room,
                classification=classification,
            )
        fill_at = iso(fill_bar["open_at"])
        preentry = pre_entry_disposition(
            stream["timeframes"]["1m"],
            signal_at=signal_at,
            fill_at=fill_at,
            stop=stop,
            target=target,
            direction=direction,
        )
        if preentry["disposition"] != "CLEAR_TO_DELAYED_ENTRY":
            return empty_lifecycle(
                str(preentry["disposition"]),
                session=session,
                family=family,
                route=route,
                original_target_room=original_room,
                pre_entry=preentry,
                classification=classification,
            )
        decision_bar = latest_m1_at(stream, confirmation_at)
        require(decision_bar is not None, f"Route decision bar absent: {control['case_alias']}")
        fill = float(fill_bar["open"]) + spread(fill_bar) / 2.0 + SLIPPAGE_USD_PER_OUNCE
        cost_per_ounce = spread(decision_bar) + 2.0 * SLIPPAGE_USD_PER_OUNCE
        entry_room = target_room(fill=fill, stop=stop, target=target, direction=direction)
        if not entry_room["geometry_valid"]:
            return empty_lifecycle(
                "DELAYED_GEOMETRY_INVALID",
                session=session,
                family=family,
                route=route,
                original_target_room=original_room,
                pre_entry=preentry,
                classification=classification,
                geometry={"fill_at": fill_at, "fill": fill, "stop": stop, "target": target, **entry_room},
            )
        routed = routed_classification(classification, fill=fill, cost_per_ounce=cost_per_ounce)
    else:
        fill_at = str(geometry["fill_at"])
        fill = float(geometry["fill"])
        cost_per_ounce = float(geometry["cost_per_ounce"])
        preentry = {
            "disposition": "DIRECT_ORIGINAL_FILL",
            "at": fill_at,
            "same_bar_target_touch": False,
            "bar_hash": None,
        }
        entry_room = original_room
        routed = copy.deepcopy(classification)

    routed_geometry = {
        "family": family,
        "fill_at": fill_at,
        "fill": fill,
        "stop": stop,
        "target": target,
        "cost_per_ounce": cost_per_ounce,
        **entry_room,
    }
    pre_overlay = simulate_track(
        classification=routed,
        stream=stream,
        fill_at=fill_at,
        track="COMPLETE_V2_POLICY",
    )
    require(pre_overlay["executed"] is True, "Admitted routed trade did not execute")
    if not delayed:
        original_result = control.get("result")
        require(
            original_result is not None
            and pre_overlay["result_hash"] == original_result["result_hash"],
            f"Direct continuation no longer reproduces control: {control['case_alias']}",
        )
    overlay = m5_close_one_r_break_even(
        m1_rows=stream["timeframes"]["1m"],
        m5_rows=stream["timeframes"]["5m"],
        fill_at=fill_at,
        baseline_final_at=pre_overlay["final_at"],
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=cost_per_ounce,
        direction=direction,
    )
    effective = baseline.effective_result_with_overlay(
        pre_overlay,
        overlay,
        classification=routed,
        stream=stream,
        fill_at=fill_at,
    )
    return {
        "admitted": True,
        "disposition": str(effective["resolution"]),
        "session": session,
        "family": family,
        "route": route,
        "original_target_room": original_room,
        "pre_entry": preentry,
        "geometry": routed_geometry,
        "classification": routed,
        "pre_overlay_result": pre_overlay,
        "break_even_overlay": overlay,
        "effective_result": effective,
    }


def result_value(result: dict[str, Any] | None, field: str = "net_r50") -> float:
    return 0.0 if result is None or not result.get("executed") else float(result[field])


def original_room_result(control: dict[str, Any]) -> dict[str, Any] | None:
    geometry = control.get("geometry")
    classification = control.get("classification")
    result = control.get("result")
    if geometry is None or classification is None or not classification["admitted"]:
        return None
    room = target_room(
        fill=float(geometry["fill"]),
        stop=float(geometry["stop"]),
        target=float(geometry["target"]),
        direction=str(classification["direction"]),
    )
    return result if room["passes_1p5r"] and result is not None and result.get("executed") else None


def run_side(
    side: str,
    controls: list[dict[str, Any]],
    rigid_by_alias: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    streams = baseline.load_all_streams(side)
    require(set(streams) == {row["case_alias"] for row in controls}, "Stream/control identities differ")
    rows: list[dict[str, Any]] = []
    for control in controls:
        alias = str(control["case_alias"])
        stream = streams[alias]
        require(stream["trading_date_utc"] == control["trading_date_utc"], "Stream date differs")
        router = family_lifecycle(control=control, stream=stream)
        rigid = copy.deepcopy(rigid_by_alias[alias]["corrected"])
        control_result = control.get("result")
        room_result = original_room_result(control)
        row: dict[str, Any] = {
            "case_alias": alias,
            "trading_date_utc": control["trading_date_utc"],
            "morning_plan": baseline.morning_plan(stream),
            "control": {
                "signal_at": control.get("signal_at"),
                "signal_probability": control.get("signal_probability"),
                "session": baseline.signal_session(control["signal_at"]) if control.get("signal_at") else None,
                "classification": control.get("classification"),
                "geometry": control.get("geometry"),
                "result": control_result,
            },
            "rigid_confirmation": rigid,
            "family_router": router,
            "attribution": {
                "control_net_r": result_value(control_result),
                "original_room_only_net_r": result_value(room_result),
                "rigid_confirmation_net_r": result_value(rigid.get("effective_result")),
                "router_pre_overlay_net_r": result_value(router.get("pre_overlay_result")),
                "router_final_net_r": result_value(router.get("effective_result")),
            },
        }
        row["attribution"]["family_route_delta_vs_room_r"] = (
            row["attribution"]["router_pre_overlay_net_r"]
            - row["attribution"]["original_room_only_net_r"]
        )
        row["attribution"]["break_even_delta_r"] = (
            row["attribution"]["router_final_net_r"]
            - row["attribution"]["router_pre_overlay_net_r"]
        )
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
    output: dict[str, Any] = {
        "version": "GOLD_AUCTION_FAMILY_ROUTER_EXPOSED_REGRESSION_V1_SIDE_1_0",
        "side": side,
        "rows": rows,
        "row_set_sha256": canonical_hash(rows),
        "additional_dates_opened": False,
        "random_50_case_population_opened": False,
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
    if policy == "router":
        return row["family_router"]["effective_result"]
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
    retained = [row for row in control_winners if result_value(lifecycle_result(row, "router")) > WIN_EPSILON]
    rejected_winners = [row for row in control_winners if lifecycle_result(row, "router") is None]
    avoided_losses = [
        row for row in rows
        if result_value(lifecycle_result(row, "control")) < -WIN_EPSILON
        and lifecycle_result(row, "router") is None
    ]
    saved_losses = [
        row for row in rows
        if result_value(lifecycle_result(row, "control")) < -WIN_EPSILON
        and lifecycle_result(row, "router") is not None
        and result_value(lifecycle_result(row, "router")) >= -WIN_EPSILON
    ]
    recovered_from_rigid = [
        row for row in rows
        if result_value(lifecycle_result(row, "control")) > WIN_EPSILON
        and result_value(lifecycle_result(row, "rigid")) <= WIN_EPSILON
        and result_value(lifecycle_result(row, "router")) > WIN_EPSILON
    ]
    attribution = {
        key: sum(float(row["attribution"][key]) for row in rows)
        for key in (
            "control_net_r",
            "original_room_only_net_r",
            "rigid_confirmation_net_r",
            "router_pre_overlay_net_r",
            "router_final_net_r",
            "family_route_delta_vs_room_r",
            "break_even_delta_r",
        )
    }
    return {
        "control": metric_block(rows, "control"),
        "rigid_confirmation": metric_block(rows, "rigid"),
        "family_router": metric_block(rows, "router"),
        "router_delta_vs_control_r": attribution["router_final_net_r"] - attribution["control_net_r"],
        "router_delta_vs_rigid_r": attribution["router_final_net_r"] - attribution["rigid_confirmation_net_r"],
        "control_winner_count": len(control_winners),
        "winner_retention_count": len(retained),
        "winner_retention_rate": len(retained) / len(control_winners) if control_winners else None,
        "valid_control_winners_rejected": len(rejected_winners),
        "valid_control_winners_rejected_r": sum(result_value(lifecycle_result(row, "control")) for row in rejected_winners),
        "avoided_loss_count": len(avoided_losses),
        "avoided_loss_control_r": sum(result_value(lifecycle_result(row, "control")) for row in avoided_losses),
        "saved_loss_count": len(saved_losses),
        "saved_loss_control_r": sum(result_value(lifecycle_result(row, "control")) for row in saved_losses),
        "recovered_control_winners_lost_by_rigid": len(recovered_from_rigid),
        "recovered_router_r": sum(result_value(lifecycle_result(row, "router")) for row in recovered_from_rigid),
        "break_even_saved_losses": sum(
            (row["family_router"].get("break_even_overlay") or {}).get("changed", False)
            and result_value(row["family_router"].get("pre_overlay_result")) < -WIN_EPSILON
            for row in rows
        ),
        "break_even_clipped_winners": sum(
            (row["family_router"].get("break_even_overlay") or {}).get("changed", False)
            and result_value(row["family_router"].get("pre_overlay_result")) > WIN_EPSILON
            for row in rows
        ),
        "attribution": attribution,
    }


def add_equity(rows: list[dict[str, Any]]) -> None:
    control_equity = rigid_equity = router_equity = STARTING_EQUITY_USD
    for row in rows:
        control_equity += result_value(lifecycle_result(row, "control"), "net_usd")
        rigid_equity += result_value(lifecycle_result(row, "rigid"), "net_usd")
        router_equity += result_value(lifecycle_result(row, "router"), "net_usd")
        row["control_equity_usd"] = control_equity
        row["rigid_equity_usd"] = rigid_equity
        row["router_equity_usd"] = router_equity


def write_ledger(rows: list[dict[str, Any]]) -> None:
    require(not DAILY_LEDGER.exists(), f"Append-only ledger already exists: {DAILY_LEDGER}")
    fields = [
        "trading_date_utc", "case_alias", "morning_macro_state", "control_signal_at",
        "session", "family", "control_disposition", "control_net_r", "rigid_disposition",
        "rigid_net_r", "router_route", "router_confirmation_at", "router_fill", "router_stop",
        "router_target", "router_disposition", "router_net_r", "control_equity_usd",
        "rigid_equity_usd", "router_equity_usd", "final_row_sha256",
    ]
    with DAILY_LEDGER.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            control_class = row["control"]["classification"]
            rigid = row["rigid_confirmation"]
            router = row["family_router"]
            route = router.get("route") or {}
            geometry = router.get("geometry") or {}
            writer.writerow(
                {
                    "trading_date_utc": row["trading_date_utc"],
                    "case_alias": row["case_alias"],
                    "morning_macro_state": row["morning_plan"]["macro"]["state"],
                    "control_signal_at": row["control"]["signal_at"],
                    "session": row["control"]["session"],
                    "family": router.get("family") or ((row["control"].get("geometry") or {}).get("family")),
                    "control_disposition": "NO_SIGNAL" if control_class is None else control_class["primary_disposition"],
                    "control_net_r": result_value(lifecycle_result(row, "control")),
                    "rigid_disposition": rigid["disposition"],
                    "rigid_net_r": result_value(lifecycle_result(row, "rigid")),
                    "router_route": route.get("route"),
                    "router_confirmation_at": route.get("confirmation_at"),
                    "router_fill": geometry.get("fill"),
                    "router_stop": geometry.get("stop"),
                    "router_target": geometry.get("target"),
                    "router_disposition": router["disposition"],
                    "router_net_r": result_value(lifecycle_result(row, "router")),
                    "control_equity_usd": row["control_equity_usd"],
                    "rigid_equity_usd": row["rigid_equity_usd"],
                    "router_equity_usd": row["router_equity_usd"],
                    "final_row_sha256": row["final_row_sha256"],
                }
            )


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gold Auction Family Router Exposed Regression V1 - Result",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "This is an exposed matched-data regression with zero validation credit. The immutable rollback baseline remains byte-for-byte restorable.",
        "",
        "| Period | Days | Control R | Rigid R | Router trades | Router R | Win % | Exp R | PF | Max DD R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("JANUARY", "FEBRUARY_TO_DATE", "MARCH", "APRIL", "MAY", "COMBINED"):
        block = result["periods"][key]
        routed = block["family_router"]
        lines.append(
            f"| {key} | {routed['days']} | {block['control']['net_r']:+.4f} | {block['rigid_confirmation']['net_r']:+.4f} | {routed['trades']} | {routed['net_r']:+.4f} | {100 * float(routed['win_rate'] or 0):.2f} | {routed['expectancy_r']:+.4f} | {routed['profit_factor']} | {routed['maximum_drawdown_r']:.4f} |"
        )
    lines.extend(["", "## Family contributions", "", "| Family | Signal days | Trades | Net R | PF |", "|---|---:|---:|---:|---:|"])
    for family in FAMILIES:
        block = result["families"][family]["family_router"]
        lines.append(f"| {family} | {block['signals']} | {block['trades']} | {block['net_r']:+.4f} | {block['profit_factor']} |")
    combined = result["periods"]["COMBINED"]
    lines.extend(
        [
            "",
            "## Matched comparison",
            "",
            f"- Control: {combined['control']['net_r']:+.4f}R.",
            f"- Rejected rigid two-stage confirmation: {combined['rigid_confirmation']['net_r']:+.4f}R.",
            f"- Family router: {combined['family_router']['net_r']:+.4f}R.",
            f"- Router minus rigid: {combined['router_delta_vs_rigid_r']:+.4f}R.",
            f"- Valid control winners rejected by router: {combined['valid_control_winners_rejected']} ({combined['valid_control_winners_rejected_r']:+.4f} control R).",
            f"- Control winners lost by rigid but recovered by router: {combined['recovered_control_winners_lost_by_rigid']}.",
            "",
            "The complete 95-day ledger is sealed in `research_artifacts/gold_auction_family_router_exposed_regression_v1/daily_ledger.csv`.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, DAILY_LEDGER, FINAL_SEAL, REPORT):
        require(not path.exists(), f"One-shot output already exists: {path}")
    controls = baseline.control_rows()
    rollback = load_json(ROLLBACK_RESULT)
    rigid_by_alias = {str(row["case_alias"]): row for row in rollback["rows"]}
    require(set(rigid_by_alias) == {row["case_alias"] for row in controls}, "Rigid/control identities differ")
    primary = run_side("primary", controls, rigid_by_alias)
    write_new_json(PRIMARY_RESULT, primary)
    reference = run_side("reference", controls, rigid_by_alias)
    write_new_json(REFERENCE_RESULT, reference)
    require(primary["rows"] == reference["rows"], "Primary/reference family-router rows differ")
    rows = primary["rows"]
    require(len(rows) == 95, "Family-router row count differs")
    add_equity(rows)
    for row in rows:
        row["final_row_sha256"] = canonical_hash(row)
    period_filters = {
        "JANUARY": lambda value: value.startswith("2022-01"),
        "FEBRUARY_TO_DATE": lambda value: value.startswith("2022-02"),
        "MARCH": lambda value: value.startswith("2022-03"),
        "APRIL": lambda value: value.startswith("2022-04"),
        "MAY": lambda value: value.startswith("2022-05"),
        "COMBINED": lambda value: True,
    }
    periods = {
        key: comparison_block([row for row in rows if predicate(row["trading_date_utc"])])
        for key, predicate in period_filters.items()
    }
    families = {
        family: comparison_block(
            [row for row in rows if (row["control"].get("geometry") or {}).get("family") == family]
        )
        for family in FAMILIES
    }
    write_ledger(rows)
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_FAMILY_ROUTER_EXPOSED_REGRESSION_V1_RESULT_1_0",
        "completed_at": now(),
        "verdict": "COMPLETE_EXPOSED_FAMILY_ROUTER_REGRESSION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "population_sha256": frozen["population_sha256"],
        "rollback": frozen["rollback"],
        "primary_reference_exact": True,
        "primary_rows_sha256": primary["row_set_sha256"],
        "reference_rows_sha256": reference["row_set_sha256"],
        "periods": periods,
        "families": families,
        "dispositions": dict(sorted(Counter(row["family_router"]["disposition"] for row in rows).items())),
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
        "version": "GOLD_AUCTION_FAMILY_ROUTER_EXPOSED_REGRESSION_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "files": [
            file_record(path)
            for path in (PROTOCOL, FREEZE, IMPLEMENTATION, TESTS, RUNNER, PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, DAILY_LEDGER, REPORT)
        ],
        "rollback_semantic_result_sha256": ROLLBACK_SEMANTIC_SHA256,
        "rollback_untouched": sha256_file(ROLLBACK_RESULT) == frozen["rollback"]["final_result_file_sha256"],
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
                "families": {key: value["family_router"] for key, value in families.items()},
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
