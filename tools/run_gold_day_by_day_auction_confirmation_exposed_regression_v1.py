#!/usr/bin/env python3
"""Freeze, run, reproduce, and seal the exposed day-by-day regression."""

from __future__ import annotations

import argparse
import csv
import gc
import gzip
import json
import math
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    load_certified_streams,
    require,
    sha256_file,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    confirmed_swings,
    iso,
    parse_dt,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    active_m15_directional_structure,
    event_lock_state,
    h4_context_metrics,
    macro_state,
    simulate_track,
)
from gold_intel.analytics.day_by_day_auction_confirmation_v1 import (  # noqa: E402
    find_first_m5_confirmation,
    first_complete_m1_after,
    m5_close_one_r_break_even,
    m5_pair_qualifies,
    pre_entry_disposition,
    target_room,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    classify_autonomous,
    latest_m1_at,
    spread,
)


PROTOCOL = ROOT / "GOLD_DAY_BY_DAY_AUCTION_CONFIRMATION_EXPOSED_REGRESSION_V1.md"
IMPLEMENTATION = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "day_by_day_auction_confirmation_v1.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_day_by_day_auction_confirmation_v1.py"
RUNNER = Path(__file__).resolve()

JAN_ROOT = ROOT / "research_artifacts" / "gold_coherent_auction_end_to_end_same_month_v1"
JAN_CONTROL = JAN_ROOT / "autonomous_result.json"
JAN_SEAL = JAN_ROOT / "final_seal.json"
JAN_CERTIFICATION = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "stream_materialization_certification.json"
)
TRANSLATOR = JAN_ROOT / "translator.json"

MAR_ROOT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_consecutive_months_mar_may_2022_v1"
)
MAR_CONTROL = MAR_ROOT / "final_result.json"
MAR_SEAL = MAR_ROOT / "final_seal.json"
MAR_PRIMARY_STREAM = MAR_ROOT / "daily_streams.primary.jsonl.gz"
MAR_REFERENCE_STREAM = MAR_ROOT / "daily_streams.reference.jsonl.gz"

OUT = (
    ROOT
    / "research_artifacts"
    / "gold_day_by_day_auction_confirmation_exposed_regression_v1"
)
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY_RESULT = OUT / "corrected.primary.json"
REFERENCE_RESULT = OUT / "corrected.reference.json"
FINAL_RESULT = OUT / "final_result.json"
DAILY_LEDGER = OUT / "daily_ledger.csv"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_DAY_BY_DAY_AUCTION_CONFIRMATION_EXPOSED_REGRESSION_V1_REPORT.md"

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
RISK_USD = 50.0
STARTING_EQUITY_USD = 10_000.0
SLIPPAGE_USD_PER_OUNCE = 0.05
WIN_EPSILON = 1e-12

EXPECTED_STATIC_SHA256 = {
    JAN_CONTROL: "c2ff398eaf3cb865191e85bace5542a79a9d23063fe51d164c4b31bc7979637d",
    TRANSLATOR: "c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841",
    JAN_CERTIFICATION: "0124f64bae5a2fceff10e63b43b08381e4fec702d3b2a09c6d97c8772617dcef",
    MAR_CONTROL: "09b092874933d08f8307663aad73f019ece4dcb0b43e70e33c3d72ffd38d3b92",
    MAR_PRIMARY_STREAM: "120b88417ea40f7cd89842d2f77a79cd1f4d381c290751612ad939356e64794c",
    MAR_REFERENCE_STREAM: "120b88417ea40f7cd89842d2f77a79cd1f4d381c290751612ad939356e64794c",
}


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_static_inputs() -> None:
    for path in (
        PROTOCOL,
        IMPLEMENTATION,
        TESTS,
        RUNNER,
        JAN_CONTROL,
        JAN_SEAL,
        JAN_CERTIFICATION,
        TRANSLATOR,
        MAR_CONTROL,
        MAR_SEAL,
        MAR_PRIMARY_STREAM,
        MAR_REFERENCE_STREAM,
    ):
        require(path.is_file(), f"Required predecessor is absent: {path}")
    for path, expected in EXPECTED_STATIC_SHA256.items():
        require(sha256_file(path) == expected, f"Sealed predecessor differs: {path}")

    jan_seal = load_json(JAN_SEAL)
    require(
        jan_seal["verdict"] == "PASS_EXPOSED_END_TO_END_REPLICATION_ZERO_VALIDATION_CREDIT",
        "January-February predecessor verdict differs",
    )
    require(jan_seal["two_complete_reruns_identical"] is True, "Jan-Feb reproduction differs")
    mar_seal = load_json(MAR_SEAL)
    require(
        mar_seal["verdict"] == "COMPLETE_UNCHANGED_THREE_CALENDAR_MONTH_TEST",
        "March-May predecessor verdict differs",
    )
    require(mar_seal["primary_reference_exact"] is True, "March-May reproduction differs")


def control_rows() -> list[dict[str, Any]]:
    jan = load_json(JAN_CONTROL)
    mar = load_json(MAR_CONTROL)
    require(jan["summary"]["cases"] == 30, "Expected 30 Jan-Feb control rows")
    require(mar["combined"]["cases"] == 65, "Expected 65 Mar-May control rows")
    rows = [dict(row) for row in jan["rows"]] + [dict(row) for row in mar["rows"]]
    rows.sort(key=lambda row: (row["trading_date_utc"], row["case_alias"]))
    dates = [str(row["trading_date_utc"]) for row in rows]
    require(len(rows) == 95 and len(set(dates)) == 95, "Expected 95 unique daily rows")
    require(dates[0] == "2022-01-03" and dates[-1] == "2022-05-31", "Population endpoints differ")
    require(
        all(
            (date(2022, 1, 3) <= date.fromisoformat(value) <= date(2022, 2, 16))
            or (date(2022, 3, 1) <= date.fromisoformat(value) <= date(2022, 5, 31))
            for value in dates
        ),
        "Population includes a prohibited date",
    )
    require(
        not any("2022-02-17" <= value <= "2022-02-28" for value in dates),
        "Unopened February gap entered the population",
    )
    require(not any(str(row["case_alias"]).startswith("GAV-") for row in rows), "Random block entered population")
    return rows


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
    long_a = synthetic_bar(point, 5, 100, 102, 98, 101)
    long_b = synthetic_bar(point + timedelta(minutes=5), 5, 100.8, 103, 99, 102)
    short_a = synthetic_bar(point, 5, 100, 102, 98, 99)
    short_b = synthetic_bar(point + timedelta(minutes=5), 5, 99.2, 101, 97, 98)
    checks = {
        "long_pair": m5_pair_qualifies(long_a, long_b, "LONG"),
        "long_pair_not_short": not m5_pair_qualifies(long_a, long_b, "SHORT"),
        "short_pair": m5_pair_qualifies(short_a, short_b, "SHORT"),
        "short_pair_not_long": not m5_pair_qualifies(short_a, short_b, "LONG"),
    }
    confirmation = find_first_m5_confirmation(
        [long_a, long_b],
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    )
    checks["first_pair"] = confirmation is not None and confirmation["confirmation_at"] == "2022-01-03T08:10:00Z"
    fill_bar = first_complete_m1_after(
        [
            synthetic_bar(point + timedelta(minutes=10), 1, 102, 103, 101, 102),
            synthetic_bar(point + timedelta(minutes=11), 1, 102, 103, 101, 102),
        ],
        "2022-01-03T08:10:00Z",
    )
    checks["strict_latency"] = fill_bar is not None and fill_bar["open_at"] == "2022-01-03T08:11:00Z"
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
    room = target_room(fill=100, stop=98, target=103, direction="LONG")
    checks["target_room_boundary"] = room["passes_1p5r"] is True and room["target_room_r"] == 1.5
    overlay = m5_close_one_r_break_even(
        m1_rows=[
            synthetic_bar(point, 1, 100, 101, 99.5, 100.5),
            synthetic_bar(point + timedelta(minutes=5), 1, 102.1, 103, 100.1, 102),
        ],
        m5_rows=[synthetic_bar(point, 5, 100, 102.5, 99.5, 102.1)],
        fill_at=point,
        baseline_final_at=point + timedelta(minutes=5),
        fill=100,
        stop=98,
        target=105,
        cost_per_ounce=0.2,
        direction="LONG",
    )
    checks["m5_break_even"] = overlay["changed"] is True and overlay["exit_at"] == "2022-01-03T08:05:00Z"
    require(all(checks.values()), f"Synthetic lifecycle proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    verify_static_inputs()
    rows = control_rows()
    proof = synthetic_proof()
    dates = [str(row["trading_date_utc"]) for row in rows]
    files = [
        PROTOCOL,
        IMPLEMENTATION,
        TESTS,
        RUNNER,
        JAN_CONTROL,
        JAN_SEAL,
        JAN_CERTIFICATION,
        TRANSLATOR,
        MAR_CONTROL,
        MAR_SEAL,
        MAR_PRIMARY_STREAM,
        MAR_REFERENCE_STREAM,
    ]
    payload: dict[str, Any] = {
        "version": "GOLD_DAY_BY_DAY_AUCTION_CONFIRMATION_EXPOSED_REGRESSION_V1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_CORRECTED_ROW_LEVEL_REPLAY",
        "files": [file_record(path) for path in files],
        "dates": dates,
        "date_counts": dict(sorted(Counter(value[:7] for value in dates).items())),
        "population_sha256": canonical_hash(
            [{"case_alias": row["case_alias"], "trading_date_utc": row["trading_date_utc"]} for row in rows]
        ),
        "synthetic_proof": proof,
        "correction": {
            "target_room_r_minimum": 1.5,
            "confirmation": "FIRST_ADJACENT_TWO_STAGE_COMPLETED_M5_PAIR",
            "fill": "NEXT_M1_OPEN_STRICTLY_AFTER_CONFIRMATION_PLUS_SPREAD_SLIPPAGE",
            "protection": "FIRST_COMPLETED_M5_CLOSE_AT_PLUS_1R_THEN_NET_BREAK_EVEN",
            "attribution_order": ["TARGET_ROOM", "CONFIRMATION_AND_DELAY", "M5_BREAK_EVEN"],
        },
        "random_50_case_population_opened": False,
        "february_17_28_opened": False,
        "additional_dates_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(json.dumps({"status": payload["status"], "dates": len(dates), "date_counts": payload["date_counts"], "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Prevalue freeze is absent")
    payload = load_json(FREEZE)
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "Prevalue freeze payload differs")
    payload["freeze_sha256"] = submitted
    require(payload["status"] == "SEALED_BEFORE_CORRECTED_ROW_LEVEL_REPLAY", "Freeze status differs")
    for record in payload["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen file size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen file hash differs: {path}")
    rows = control_rows()
    require([row["trading_date_utc"] for row in rows] == payload["dates"], "Frozen date order differs")
    return payload


def load_mar_streams(path: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            submitted = row.pop("stream_sha256")
            require(canonical_hash(row) == submitted, f"Stream payload differs: {row.get('case_alias')}")
            row["stream_sha256"] = submitted
            alias = str(row["case_alias"])
            require(alias not in output, f"Duplicate stream alias: {alias}")
            output[alias] = row
    require(len(output) == 65, "Expected 65 March-May streams")
    return output


def load_all_streams(side: str) -> dict[str, dict[str, Any]]:
    jan, _ = load_certified_streams(JAN_CERTIFICATION, side)
    mar = load_mar_streams(MAR_PRIMARY_STREAM if side == "primary" else MAR_REFERENCE_STREAM)
    overlap = set(jan) & set(mar)
    require(not overlap, f"Duplicate aliases across populations: {sorted(overlap)}")
    return {**jan, **mar}


def signal_session(signal_at: str) -> str:
    point = parse_dt(signal_at)
    london_time = point.astimezone(LONDON).time()
    ny_time = point.astimezone(NEW_YORK).time()
    if time(8) <= london_time < time(12):
        return "LONDON"
    if time(8) <= ny_time < time(12):
        return "NEW_YORK"
    raise RuntimeError(f"Signal outside frozen sessions: {signal_at}")


def session_end(signal_at: str, session: str) -> datetime:
    point = parse_dt(signal_at)
    zone = LONDON if session == "LONDON" else NEW_YORK
    local = point.astimezone(zone)
    return datetime.combine(local.date(), time(12), tzinfo=zone).astimezone(UTC)


def morning_plan(stream: dict[str, Any]) -> dict[str, Any]:
    day = date.fromisoformat(str(stream["trading_date_utc"]))
    checkpoint = datetime.combine(day, time(8), tzinfo=LONDON).astimezone(UTC)
    cutoff = iso(checkpoint)
    last_m1 = latest_m1_at(stream, cutoff)
    price = float(last_m1["close"]) if last_m1 is not None else None
    _, swings = confirmed_swings(stream["timeframes"]["1h"], cutoff, "H1")
    lows = [row for row in swings if row["kind"] == "LOW" and price is not None and float(row["level"]) < price]
    highs = [row for row in swings if row["kind"] == "HIGH" and price is not None and float(row["level"]) > price]
    nearest_low = max(lows, key=lambda row: float(row["level"])) if lows else None
    nearest_high = min(highs, key=lambda row: float(row["level"])) if highs else None
    plan = {
        "checkpoint_at": cutoff,
        "macro": macro_state(stream, cutoff, "LONG"),
        "h4": h4_context_metrics(stream, cutoff, "LONG"),
        "m15_structure": active_m15_directional_structure(stream, cutoff, "LONG"),
        "event": event_lock_state(stream, cutoff, "LONG"),
        "reference_price_available": price is not None,
        "nearest_confirmed_h1_support": (
            None
            if nearest_low is None
            else {key: nearest_low[key] for key in ("identity", "detected_at", "pivot_at", "level")}
        ),
        "nearest_confirmed_h1_resistance": (
            None
            if nearest_high is None
            else {key: nearest_high[key] for key in ("identity", "detected_at", "pivot_at", "level")}
        ),
    }
    plan["plan_sha256"] = canonical_hash(plan)
    return plan


def empty_lifecycle(disposition: str) -> dict[str, Any]:
    return {
        "admitted": False,
        "disposition": disposition,
        "confirmation": None,
        "pre_entry": None,
        "geometry": None,
        "classification": None,
        "pre_overlay_result": None,
        "break_even_overlay": None,
        "effective_result": None,
    }


def effective_result_with_overlay(
    baseline: dict[str, Any],
    overlay: dict[str, Any],
    *,
    classification: dict[str, Any],
    stream: dict[str, Any],
    fill_at: str,
) -> dict[str, Any]:
    if not overlay["changed"]:
        return dict(baseline)
    quantity = int(baseline["quantity_ounces"])
    fill = float(classification["fill"])
    sign = 1.0 if classification["direction"] == "LONG" else -1.0
    cost_per_ounce = float(classification["cost_per_ounce"])
    exit_price = fill + sign * cost_per_ounce
    cost = cost_per_ounce * quantity
    final = parse_dt(overlay["exit_at"])
    path = [
        row
        for row in stream["timeframes"]["1m"]
        if row.get("complete") is True
        and parse_dt(fill_at) <= parse_dt(row["open_at"]) <= final
    ]
    favourable = max(
        [0.0]
        + [
            float(row["high"]) - fill if sign > 0 else fill - float(row["low"])
            for row in path
        ]
    )
    adverse = max(
        [0.0]
        + [
            fill - float(row["low"]) if sign > 0 else float(row["high"]) - fill
            for row in path
        ]
    )
    gross = sign * (exit_price - fill) * quantity
    result: dict[str, Any] = {
        **baseline,
        "resolution": "M5_1R_NET_BREAK_EVEN",
        "final_at": overlay["exit_at"],
        "legs": [
            {
                "quantity_ounces": quantity,
                "exit_price": exit_price,
                "exit_at": overlay["exit_at"],
                "resolution": "M5_1R_NET_BREAK_EVEN",
            }
        ],
        "protection_at": overlay["activation_at"],
        "target_touched": False,
        "target_acceptance": None,
        "runner_activated": False,
        "runner_stop_changes": [],
        "gross_usd": gross,
        "cost_usd": cost,
        "net_usd": gross - cost,
        "net_r50": (gross - cost) / RISK_USD,
        "stressed_1_5x_cost_net_usd": gross - 1.5 * cost,
        "stressed_1_5x_cost_r50": (gross - 1.5 * cost) / RISK_USD,
        "mfe_r50": favourable * quantity / RISK_USD,
        "mae_r50": adverse * quantity / RISK_USD,
        "result_hash": None,
    }
    result["result_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "result_hash"}
    )
    require(abs(float(result["net_r50"])) <= 1e-10, "Net break-even result is not zero")
    return result


def corrected_lifecycle(
    *, control: dict[str, Any], stream: dict[str, Any]
) -> dict[str, Any]:
    if control.get("signal_at") is None:
        return empty_lifecycle("NO_SIGNAL")
    signal_at = str(control["signal_at"])
    session = signal_session(signal_at)
    geometry = control.get("geometry")
    require(geometry is not None, f"Signal geometry absent: {control['case_alias']}")
    direction = "LONG"
    stop = float(geometry["stop"])
    target = float(geometry["target"])
    family = str(geometry["family"])
    confirmation = find_first_m5_confirmation(
        stream["timeframes"]["5m"],
        signal_at=signal_at,
        session_end=session_end(signal_at, session),
        direction=direction,
    )
    if confirmation is None:
        lifecycle = empty_lifecycle("NO_TWO_STAGE_M5_CONFIRMATION")
        lifecycle["session"] = session
        return lifecycle
    fill_bar = first_complete_m1_after(
        stream["timeframes"]["1m"], confirmation["confirmation_at"]
    )
    if fill_bar is None or parse_dt(fill_bar["open_at"]) >= session_end(signal_at, session):
        lifecycle = empty_lifecycle("NO_EXECUTABLE_M1_AFTER_CONFIRMATION")
        lifecycle.update({"session": session, "confirmation": confirmation})
        return lifecycle
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
        lifecycle = empty_lifecycle(str(preentry["disposition"]))
        lifecycle.update({"session": session, "confirmation": confirmation, "pre_entry": preentry})
        return lifecycle
    decision_bar = latest_m1_at(stream, confirmation["confirmation_at"])
    require(decision_bar is not None, f"Confirmation decision bar absent: {control['case_alias']}")
    fill = float(fill_bar["open"]) + spread(fill_bar) / 2.0 + SLIPPAGE_USD_PER_OUNCE
    cost_per_ounce = spread(decision_bar) + 2.0 * SLIPPAGE_USD_PER_OUNCE
    room = target_room(fill=fill, stop=stop, target=target, direction=direction)
    delayed_geometry = {
        "family": family,
        "fill_at": fill_at,
        "fill": fill,
        "stop": stop,
        "target": target,
        "cost_per_ounce": cost_per_ounce,
        **room,
    }
    if not room["geometry_valid"]:
        lifecycle = empty_lifecycle("DELAYED_GEOMETRY_INVALID")
        lifecycle.update({"session": session, "confirmation": confirmation, "pre_entry": preentry, "geometry": delayed_geometry})
        return lifecycle
    if not room["passes_1p5r"]:
        lifecycle = empty_lifecycle("TARGET_ROOM_LT_1P5R")
        lifecycle.update({"session": session, "confirmation": confirmation, "pre_entry": preentry, "geometry": delayed_geometry})
        return lifecycle
    classification = classify_autonomous(
        stream=stream,
        signal_at=confirmation["confirmation_at"],
        family=family,
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=cost_per_ounce,
    )
    if not classification["admitted"]:
        lifecycle = empty_lifecycle(str(classification["primary_disposition"]))
        lifecycle.update(
            {
                "session": session,
                "confirmation": confirmation,
                "pre_entry": preentry,
                "geometry": delayed_geometry,
                "classification": classification,
            }
        )
        return lifecycle
    pre_overlay = simulate_track(
        classification=classification,
        stream=stream,
        fill_at=fill_at,
        track="COMPLETE_V2_POLICY",
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
    effective = effective_result_with_overlay(
        pre_overlay,
        overlay,
        classification=classification,
        stream=stream,
        fill_at=fill_at,
    )
    return {
        "admitted": True,
        "disposition": str(effective["resolution"]),
        "session": session,
        "confirmation": confirmation,
        "pre_entry": preentry,
        "geometry": delayed_geometry,
        "classification": classification,
        "pre_overlay_result": pre_overlay,
        "break_even_overlay": overlay,
        "effective_result": effective,
    }


def result_value(result: dict[str, Any] | None, field: str = "net_r50") -> float:
    return 0.0 if result is None or not result.get("executed") else float(result[field])


def original_target_room_passes(control: dict[str, Any]) -> bool:
    geometry = control.get("geometry")
    if geometry is None:
        return False
    return bool(
        target_room(
            fill=float(geometry["fill"]),
            stop=float(geometry["stop"]),
            target=float(geometry["target"]),
            direction="LONG",
        )["passes_1p5r"]
    )


def run_side(side: str, controls: list[dict[str, Any]]) -> dict[str, Any]:
    streams = load_all_streams(side)
    require(set(streams) == {row["case_alias"] for row in controls}, "Stream/control identities differ")
    rows: list[dict[str, Any]] = []
    for control in controls:
        stream = streams[str(control["case_alias"])]
        require(stream["trading_date_utc"] == control["trading_date_utc"], "Stream date differs")
        plan = morning_plan(stream)
        lifecycle = corrected_lifecycle(control=control, stream=stream)
        control_result = control.get("result")
        target_room_stage_result = (
            control_result
            if control_result is not None
            and control_result.get("executed")
            and original_target_room_passes(control)
            else None
        )
        row: dict[str, Any] = {
            "case_alias": control["case_alias"],
            "trading_date_utc": control["trading_date_utc"],
            "morning_plan": plan,
            "control": {
                "signal_at": control.get("signal_at"),
                "signal_probability": control.get("signal_probability"),
                "session": signal_session(control["signal_at"]) if control.get("signal_at") else None,
                "classification": control.get("classification"),
                "geometry": control.get("geometry"),
                "result": control_result,
            },
            "corrected": lifecycle,
            "attribution": {
                "control_net_r": result_value(control_result),
                "target_room_only_net_r": result_value(target_room_stage_result),
                "confirmed_delayed_pre_overlay_net_r": result_value(lifecycle.get("pre_overlay_result")),
                "final_m5_break_even_net_r": result_value(lifecycle.get("effective_result")),
            },
        }
        row["attribution"]["target_room_delta_r"] = row["attribution"]["target_room_only_net_r"] - row["attribution"]["control_net_r"]
        row["attribution"]["confirmation_delay_delta_r"] = row["attribution"]["confirmed_delayed_pre_overlay_net_r"] - row["attribution"]["target_room_only_net_r"]
        row["attribution"]["m5_break_even_delta_r"] = row["attribution"]["final_m5_break_even_net_r"] - row["attribution"]["confirmed_delayed_pre_overlay_net_r"]
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
    output: dict[str, Any] = {
        "version": "GOLD_DAY_BY_DAY_AUCTION_CONFIRMATION_EXPOSED_REGRESSION_V1_SIDE_1_0",
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


def longest_streak(values: list[float], positive: bool) -> int:
    best = current = 0
    for value in values:
        matches = value > WIN_EPSILON if positive else value < -WIN_EPSILON
        current = current + 1 if matches else 0
        best = max(best, current)
    return best


def metric_block(rows: list[dict[str, Any]], corrected: bool) -> dict[str, Any]:
    results = [
        row["corrected"]["effective_result"] if corrected else row["control"]["result"]
        for row in rows
    ]
    executed = [result for result in results if result is not None and result.get("executed")]
    values = [float(result["net_r50"]) for result in executed]
    wins = [value for value in values if value > WIN_EPSILON]
    losses = [value for value in values if value < -WIN_EPSILON]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    signals = sum(row["control"]["signal_at"] is not None for row in rows)
    positive = sum(wins)
    negative = abs(sum(losses))
    return {
        "days": len(rows),
        "signals": signals,
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
    control_winners = [row for row in rows if result_value(row["control"]["result"]) > WIN_EPSILON]
    retained = [row for row in control_winners if result_value(row["corrected"]["effective_result"]) > WIN_EPSILON]
    avoided_losses = [
        row
        for row in rows
        if result_value(row["control"]["result"]) < -WIN_EPSILON
        and row["corrected"]["effective_result"] is None
    ]
    saved_losses = [
        row
        for row in rows
        if result_value(row["control"]["result"]) < -WIN_EPSILON
        and row["corrected"]["effective_result"] is not None
        and result_value(row["corrected"]["effective_result"]) >= -WIN_EPSILON
    ]
    rejected_winners = [row for row in control_winners if row["corrected"]["effective_result"] is None]
    attribution = {
        key: sum(float(row["attribution"][key]) for row in rows)
        for key in (
            "control_net_r",
            "target_room_only_net_r",
            "confirmed_delayed_pre_overlay_net_r",
            "final_m5_break_even_net_r",
            "target_room_delta_r",
            "confirmation_delay_delta_r",
            "m5_break_even_delta_r",
        )
    }
    return {
        "control": metric_block(rows, False),
        "corrected": metric_block(rows, True),
        "winner_retention_count": len(retained),
        "control_winner_count": len(control_winners),
        "winner_retention_rate": len(retained) / len(control_winners) if control_winners else None,
        "control_positive_r": sum(result_value(row["control"]["result"]) for row in control_winners),
        "retained_winner_corrected_r": sum(result_value(row["corrected"]["effective_result"]) for row in retained),
        "avoided_loss_count": len(avoided_losses),
        "avoided_loss_control_r": sum(result_value(row["control"]["result"]) for row in avoided_losses),
        "saved_loss_count": len(saved_losses),
        "saved_loss_control_r": sum(result_value(row["control"]["result"]) for row in saved_losses),
        "valid_control_winners_rejected": len(rejected_winners),
        "valid_control_winners_rejected_r": sum(result_value(row["control"]["result"]) for row in rejected_winners),
        "break_even_saved_losses": sum(
            (row["corrected"].get("break_even_overlay") or {}).get("changed", False)
            and result_value(row["corrected"].get("pre_overlay_result")) < -WIN_EPSILON
            for row in rows
        ),
        "break_even_clipped_winners": sum(
            (row["corrected"].get("break_even_overlay") or {}).get("changed", False)
            and result_value(row["corrected"].get("pre_overlay_result")) > WIN_EPSILON
            for row in rows
        ),
        "attribution": attribution,
    }


def add_equity(rows: list[dict[str, Any]]) -> None:
    control_equity = corrected_equity = STARTING_EQUITY_USD
    for row in rows:
        control_equity += result_value(row["control"]["result"], "net_usd")
        corrected_equity += result_value(row["corrected"]["effective_result"], "net_usd")
        row["control_equity_usd"] = control_equity
        row["corrected_equity_usd"] = corrected_equity


def write_ledger(rows: list[dict[str, Any]]) -> None:
    require(not DAILY_LEDGER.exists(), f"Append-only ledger already exists: {DAILY_LEDGER}")
    DAILY_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "trading_date_utc",
        "case_alias",
        "morning_macro_state",
        "morning_macro_score",
        "morning_h4_sequence",
        "morning_h4_location",
        "morning_m15_structure",
        "morning_h1_support",
        "morning_h1_resistance",
        "control_signal_at",
        "control_session",
        "control_disposition",
        "control_net_r",
        "corrected_confirmation_at",
        "corrected_entry",
        "corrected_stop",
        "corrected_target",
        "corrected_disposition",
        "corrected_net_r",
        "control_equity_usd",
        "corrected_equity_usd",
        "row_sha256",
    ]
    with DAILY_LEDGER.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            plan = row["morning_plan"]
            control_class = row["control"]["classification"]
            corrected = row["corrected"]
            geometry = corrected.get("geometry") or {}
            writer.writerow(
                {
                    "trading_date_utc": row["trading_date_utc"],
                    "case_alias": row["case_alias"],
                    "morning_macro_state": plan["macro"]["state"],
                    "morning_macro_score": plan["macro"]["score"],
                    "morning_h4_sequence": plan["h4"].get("swing_sequence"),
                    "morning_h4_location": plan["h4"].get("raw_range_location"),
                    "morning_m15_structure": plan["m15_structure"].get("latest_identity"),
                    "morning_h1_support": (plan["nearest_confirmed_h1_support"] or {}).get("level"),
                    "morning_h1_resistance": (plan["nearest_confirmed_h1_resistance"] or {}).get("level"),
                    "control_signal_at": row["control"]["signal_at"],
                    "control_session": row["control"]["session"],
                    "control_disposition": "NO_SIGNAL" if control_class is None else control_class["primary_disposition"],
                    "control_net_r": result_value(row["control"]["result"]),
                    "corrected_confirmation_at": (corrected.get("confirmation") or {}).get("confirmation_at"),
                    "corrected_entry": geometry.get("fill"),
                    "corrected_stop": geometry.get("stop"),
                    "corrected_target": geometry.get("target"),
                    "corrected_disposition": corrected["disposition"],
                    "corrected_net_r": result_value(corrected.get("effective_result")),
                    "control_equity_usd": row["control_equity_usd"],
                    "corrected_equity_usd": row["corrected_equity_usd"],
                    "row_sha256": row["row_sha256"],
                }
            )


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gold Day-by-Day Auction-Confirmation Exposed Regression V1 — Result",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "This is an exposed regression with zero validation credit. The random 50-case population and 2022-02-17 through 2022-02-28 were not opened.",
        "",
        "| Period | Days | Control trades | Control R | Corrected trades | Corrected R | Win % | Exp R | PF | Max DD R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("JANUARY", "FEBRUARY_TO_DATE", "MARCH", "APRIL", "MAY", "COMBINED"):
        block = result["periods"][key]
        control = block["control"]
        corrected = block["corrected"]
        lines.append(
            f"| {key} | {corrected['days']} | {control['trades']} | {control['net_r']:+.4f} | {corrected['trades']} | {corrected['net_r']:+.4f} | {100 * float(corrected['win_rate'] or 0):.2f} | {corrected['expectancy_r']:+.4f} | {corrected['profit_factor']} | {corrected['maximum_drawdown_r']:.4f} |"
        )
    combined = result["periods"]["COMBINED"]
    attr = combined["attribution"]
    lines.extend(
        [
            "",
            "## Fixed-order value attribution",
            "",
            f"- Unchanged control: {attr['control_net_r']:+.4f}R",
            f"- After original-fill 1.5R room screen: {attr['target_room_only_net_r']:+.4f}R ({attr['target_room_delta_r']:+.4f}R incremental)",
            f"- After frozen M5 confirmation and delayed entry: {attr['confirmed_delayed_pre_overlay_net_r']:+.4f}R ({attr['confirmation_delay_delta_r']:+.4f}R incremental)",
            f"- After M5-close +1R break-even: {attr['final_m5_break_even_net_r']:+.4f}R ({attr['m5_break_even_delta_r']:+.4f}R incremental)",
            "",
            "The attribution is descriptive and order-dependent; it is not a second strategy search.",
            "",
            "## Daily ledger",
            "",
            "The complete 95-day ledger is sealed in `research_artifacts/gold_day_by_day_auction_confirmation_exposed_regression_v1/daily_ledger.csv`.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, DAILY_LEDGER, FINAL_SEAL, REPORT):
        require(not path.exists(), f"One-shot output already exists: {path}")
    controls = control_rows()
    primary = run_side("primary", controls)
    write_new_json(PRIMARY_RESULT, primary)
    reference = run_side("reference", controls)
    write_new_json(REFERENCE_RESULT, reference)
    require(primary["rows"] == reference["rows"], "Primary/reference corrected rows differ")
    rows = primary["rows"]
    require(len(rows) == 95, "Corrected row count differs")
    add_equity(rows)
    # Equity is deterministic presentation state; seal row identities again after adding it.
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
    write_ledger(rows)
    final: dict[str, Any] = {
        "version": "GOLD_DAY_BY_DAY_AUCTION_CONFIRMATION_EXPOSED_REGRESSION_V1_RESULT_1_0",
        "completed_at": now(),
        "verdict": "COMPLETE_EXPOSED_DAY_BY_DAY_REGRESSION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "population_sha256": frozen["population_sha256"],
        "primary_reference_exact": True,
        "primary_rows_sha256": primary["row_set_sha256"],
        "reference_rows_sha256": reference["row_set_sha256"],
        "periods": periods,
        "dispositions": dict(sorted(Counter(row["corrected"]["disposition"] for row in rows).items())),
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
        "version": "GOLD_DAY_BY_DAY_AUCTION_CONFIRMATION_EXPOSED_REGRESSION_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "files": [file_record(path) for path in (PROTOCOL, FREEZE, IMPLEMENTATION, TESTS, RUNNER, PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, DAILY_LEDGER, REPORT)],
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
    print(json.dumps({"verdict": final["verdict"], "periods": periods, "dispositions": final["dispositions"], "result_sha256": final["result_sha256"]}, indent=2, sort_keys=True))


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
