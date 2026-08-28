#!/usr/bin/env python3
"""Run the exposed New-York direction-symmetry and monetization-gap audit."""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_auction_family_router_exposed_regression_v1 as router  # noqa: E402
import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    materialize_case,
    predict_class,
    predict_class_probability,
    predict_regression,
    prepare_features,
    require,
    sha256_file,
    transform_rows,
)
from gold_intel.analytics.auction_direction_symmetry_v1 import (  # noqa: E402
    Direction,
    classify_autonomous_directional,
    directional_fill,
    directional_geometry,
    orient_feature_row,
)
from gold_intel.analytics.auction_family_router_v1_r1 import (  # noqa: E402
    corrected_router_lifecycle,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    simulate_track,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    first_m1_after,
    latest_m1_at,
    spread,
)
from run_gold_coherent_auction_frozen_translator_unseen_block_v1 import (  # noqa: E402
    infer_streams,
)


PROTOCOL = ROOT / "GOLD_DIRECTION_SYMMETRIC_AUCTION_AND_MONETIZATION_GAP_AUDIT_V1.md"
IMPLEMENTATION = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "auction_direction_symmetry_v1.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_direction_symmetry_v1.py"
RUNNER = Path(__file__).resolve()
TRANSLATOR = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "translator.json"
)
CURRENT_RESULT = (
    ROOT
    / "research_artifacts"
    / "gold_auction_family_router_v1_r1_mechanical_correction"
    / "final_result.json"
)
CURRENT_SEAL = (
    ROOT
    / "research_artifacts"
    / "gold_auction_family_router_v1_r1_mechanical_correction"
    / "final_seal.json"
)
OUT = ROOT / "research_artifacts" / "gold_direction_symmetric_auction_gap_audit_v1"
FREEZE = OUT / "preoutcome_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_DIRECTION_SYMMETRIC_AUCTION_AND_MONETIZATION_GAP_AUDIT_V1_REPORT.md"

SLIPPAGE = 0.05
EPSILON = 1e-12


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
    require(not path.exists(), f"Append-only output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def population() -> list[dict[str, Any]]:
    rows = baseline.control_rows()
    require(len(rows) == 95, "Exposed daily population differs")
    return rows


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    baseline.verify_static_inputs()
    rows = population()
    current = load_json(CURRENT_RESULT)
    require(len(current["rows"]) == 95, "Current corrected population differs")
    require(load_json(CURRENT_SEAL)["verdict"] == current["verdict"], "Current seal differs")
    files = [PROTOCOL, IMPLEMENTATION, TESTS, RUNNER, TRANSLATOR, CURRENT_RESULT, CURRENT_SEAL]
    require(all(path.is_file() for path in files), "A required frozen file is absent")
    identities = [
        {
            "case_alias": row["case_alias"],
            "trading_date_utc": row["trading_date_utc"],
            "source_row_sha256": row["row_sha256"],
        }
        for row in rows
    ]
    payload: dict[str, Any] = {
        "version": "GOLD_DIRECTION_SYMMETRIC_AUCTION_GAP_FREEZE_V1_0",
        "sealed_at": now(),
        "status": "SEALED_EXPOSED_DIRECTION_SYMMETRY_AND_GAP_PROTOCOL",
        "files": [file_record(path) for path in files],
        "population": identities,
        "population_sha256": canonical_hash(identities),
        "experimental_session": "NEW_YORK",
        "directions": ["LONG", "SHORT"],
        "first_signal_per_day": True,
        "same_model_threshold_and_router": True,
        "new_model_fit_permitted": False,
        "fresh_dates_opened": False,
        "february_17_28_opened": False,
        "random_50_cases_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(json.dumps({"status": payload["status"], "days": len(rows), "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Pre-outcome freeze is absent")
    payload = load_json(FREEZE)
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "Freeze payload differs")
    payload["freeze_sha256"] = submitted
    for record in payload["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen hash differs: {path}")
    identities = [
        {
            "case_alias": row["case_alias"],
            "trading_date_utc": row["trading_date_utc"],
            "source_row_sha256": row["row_sha256"],
        }
        for row in population()
    ]
    require(identities == payload["population"], "Frozen population differs")
    return payload


def normalized_control_row(row: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(row)
    output.pop("signal_session", None)
    return output


def reproduce_long_control(
    streams: dict[str, dict[str, Any]], controls: list[dict[str, Any]], translator: dict[str, Any]
) -> dict[str, Any]:
    produced: list[dict[str, Any]] = []
    for prefix in ("CBR-", "CAM-"):
        group = {key: value for key, value in streams.items() if key.startswith(prefix)}
        inferred = infer_streams(
            streams=group,
            lineage=[],
            translator=translator,
            side="long-regression",
            include_validation_metadata=False,
        )
        produced.extend(inferred["rows"])
    produced.sort(key=lambda row: (row["trading_date_utc"], row["case_alias"]))
    expected = [normalized_control_row(row) for row in controls]
    require(produced == expected, "Frozen LONG inference no longer reproduces")
    classifier_checks = 0
    for row in expected:
        if row.get("classification") is None:
            continue
        geometry = row["geometry"]
        reproduced = classify_autonomous_directional(
            stream=streams[row["case_alias"]],
            signal_at=row["signal_at"],
            direction="LONG",
            family=geometry["family"],
            fill=float(geometry["fill"]),
            stop=float(geometry["stop"]),
            target=float(geometry["target"]),
            cost_per_ounce=float(geometry["cost_per_ounce"]),
        )
        require(reproduced == row["classification"], f"LONG classifier differs: {row['case_alias']}")
        classifier_checks += 1
    return {
        "exact": True,
        "rows": len(produced),
        "signals_checked": classifier_checks,
        "rows_sha256": canonical_hash(produced),
    }


def short_family_lifecycle(*, control: dict[str, Any], stream: dict[str, Any]) -> dict[str, Any]:
    signal_value = control.get("signal_at")
    if signal_value is None:
        return router.empty_lifecycle("NO_SIGNAL")
    signal_at = str(signal_value)
    session = baseline.signal_session(signal_at)
    end = baseline.session_end(signal_at, session)
    geometry = control.get("geometry")
    classification = control.get("classification")
    require(geometry is not None and classification is not None, "SHORT signal payload absent")
    require(classification["direction"] == "SHORT", "SHORT lifecycle received another direction")
    family = str(geometry["family"])
    require(family in router.FAMILIES, f"Unknown family: {family}")
    if not classification["admitted"]:
        return router.empty_lifecycle(
            f"ORIGINAL_SIGNAL_CONTEXT_REJECTED::{classification['primary_disposition']}",
            session=session,
            family=family,
            classification=classification,
        )
    direction: Direction = "SHORT"
    stop = float(geometry["stop"])
    target = float(geometry["target"])
    original_room = router.target_room(
        fill=float(geometry["fill"]), stop=stop, target=target, direction=direction
    )
    if not original_room["geometry_valid"]:
        return router.empty_lifecycle(
            "ORIGINAL_GEOMETRY_INVALID",
            session=session,
            family=family,
            original_target_room=original_room,
            classification=classification,
        )
    if not original_room["passes_1p5r"]:
        return router.empty_lifecycle(
            "ORIGINAL_TARGET_ROOM_LT_1P5R",
            session=session,
            family=family,
            original_target_room=original_room,
            classification=classification,
        )
    delayed = family != "CONTINUATION_WITH_ROOM"
    if family == "CONTINUATION_WITH_ROOM":
        route = {
            "route": "CONTINUATION_DIRECT_ORIGINAL_FILL",
            "direction": direction,
            "confirmation_at": signal_at,
            "bar_open_at": None,
            "within_route_occurrence": 0,
        }
        route["route_hash"] = canonical_hash(route)
    elif family == "RANGE_ROTATION":
        route = router.first_range_reclaim(
            stream["timeframes"]["5m"],
            signal_at=signal_at,
            session_end=end,
            direction=direction,
        )
        if route is None:
            return router.empty_lifecycle(
                "NO_RANGE_RECLAIM_WITHIN_6_M5",
                session=session,
                family=family,
                original_target_room=original_room,
                classification=classification,
            )
    else:
        event = router.latest_active_m15_break(
            stream["timeframes"]["15m"], signal_at=signal_at, direction=direction
        )
        if event is None:
            return router.empty_lifecycle(
                "NO_ACTIVE_ALIGNED_M15_BREAK_AT_SIGNAL",
                session=session,
                family=family,
                original_target_room=original_room,
                classification=classification,
            )
        route = router.first_structural_repair_retest(
            stream["timeframes"]["5m"],
            event=event,
            signal_at=signal_at,
            session_end=end,
            direction=direction,
        )
        if route["disposition"] != "CONFIRMED":
            return router.empty_lifecycle(
                str(route["disposition"]),
                session=session,
                family=family,
                route=route,
                original_target_room=original_room,
                classification=classification,
            )
    if delayed:
        confirmation_at = str(route["confirmation_at"])
        fill_bar = router.first_complete_m1_after(stream["timeframes"]["1m"], confirmation_at)
        if fill_bar is None or parse_dt(fill_bar["open_at"]) >= end:
            return router.empty_lifecycle(
                "NO_EXECUTABLE_M1_AFTER_FAMILY_CONFIRMATION",
                session=session,
                family=family,
                route=route,
                original_target_room=original_room,
                classification=classification,
            )
        fill_at = iso(fill_bar["open_at"])
        preentry = router.pre_entry_disposition(
            stream["timeframes"]["1m"],
            signal_at=signal_at,
            fill_at=fill_at,
            stop=stop,
            target=target,
            direction=direction,
        )
        if preentry["disposition"] != "CLEAR_TO_DELAYED_ENTRY":
            return router.empty_lifecycle(
                str(preentry["disposition"]),
                session=session,
                family=family,
                route=route,
                original_target_room=original_room,
                pre_entry=preentry,
                classification=classification,
            )
        decision_bar = latest_m1_at(stream, confirmation_at)
        require(decision_bar is not None, "SHORT route decision bar absent")
        fill = directional_fill(
            mid_open=float(fill_bar["open"]),
            spread_price=spread(fill_bar),
            slippage=SLIPPAGE,
            direction=direction,
        )
        cost_per_ounce = spread(decision_bar) + 2.0 * SLIPPAGE
        entry_room = router.target_room(
            fill=fill, stop=stop, target=target, direction=direction
        )
        if not entry_room["geometry_valid"]:
            return router.empty_lifecycle(
                "DELAYED_GEOMETRY_INVALID",
                session=session,
                family=family,
                route=route,
                original_target_room=original_room,
                pre_entry=preentry,
                classification=classification,
                geometry={"fill_at": fill_at, "fill": fill, "stop": stop, "target": target, **entry_room},
            )
        routed = router.routed_classification(
            classification, fill=fill, cost_per_ounce=cost_per_ounce
        )
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
    require(pre_overlay["executed"] is True, "Admitted SHORT trade did not execute")
    return {
        "admitted": True,
        "disposition": str(pre_overlay["resolution"]),
        "session": session,
        "family": family,
        "route": route,
        "original_target_room": original_room,
        "pre_entry": preentry,
        "geometry": routed_geometry,
        "classification": routed,
        "pre_overlay_result": pre_overlay,
        "break_even_overlay": None,
        "effective_result": pre_overlay,
    }


def select_signal(
    checkpoints: list[dict[str, Any]], translator: dict[str, Any]
) -> tuple[dict[str, Any] | None, Direction | None, dict[str, float] | None, str | None]:
    semantic = translator["semantic"]
    schema = translator["preprocessing"]
    eligible = [row for row in checkpoints if row["session"] == "NEW_YORK"]
    long_matrix = transform_rows(eligible, schema)
    short_rows = [orient_feature_row(row, "SHORT") for row in eligible]
    short_matrix = transform_rows(short_rows, schema)
    long_probabilities = predict_class_probability(
        semantic["tree"], long_matrix, positive_class=1
    )
    short_probabilities = predict_class_probability(
        semantic["tree"], short_matrix, positive_class=1
    )
    threshold = float(semantic["threshold"])
    for row, long_probability, short_probability in zip(
        eligible, long_probabilities, short_probabilities, strict=True
    ):
        long_pass = float(long_probability) >= threshold
        short_pass = float(short_probability) >= threshold
        if not long_pass and not short_pass:
            continue
        probabilities = {
            "LONG": float(long_probability),
            "SHORT": float(short_probability),
        }
        if long_pass and short_pass and abs(float(long_probability) - float(short_probability)) <= EPSILON:
            return row, None, probabilities, "NO_TRADE_DIRECTION_CONFLICT"
        direction: Direction = (
            "LONG" if long_pass and (not short_pass or long_probability > short_probability) else "SHORT"
        )
        return row, direction, probabilities, None
    return None, None, None, None


def infer_group(
    *, streams: dict[str, dict[str, Any]], translator: dict[str, Any]
) -> list[dict[str, Any]]:
    prepared = prepare_features(streams.values())
    schema = translator["preprocessing"]
    geometry_model = translator["geometry"]
    rows: list[dict[str, Any]] = []
    for alias in sorted(streams):
        stream = streams[alias]
        checkpoints = materialize_case(
            alias=alias, stream=stream, prepared=prepared, end_at=None
        )
        signal_row, direction, probabilities, conflict = select_signal(checkpoints, translator)
        if signal_row is None or direction is None:
            row = {
                "case_alias": alias,
                "trading_date_utc": stream["trading_date_utc"],
                "signal_at": None if signal_row is None else signal_row["checkpoint_at"],
                "direction": None,
                "direction_probabilities": probabilities,
                "disposition": conflict or "NO_SIGNAL",
                "geometry": None,
                "classification": None,
                "raw_result": None,
                "family_router": None,
                "corrected": None,
            }
            row["row_sha256"] = canonical_hash(row)
            rows.append(row)
            continue
        oriented = orient_feature_row(signal_row, direction)
        matrix = transform_rows([oriented], schema)
        stop_distance = float(
            predict_regression(geometry_model["stop_distance_tree"], matrix)[0]
        )
        target_distance = float(
            predict_regression(geometry_model["target_distance_tree"], matrix)[0]
        )
        family = str(predict_class(geometry_model["family_tree"], matrix)[0])
        reference = float(signal_row["m1_reference_close"])
        atr = float(signal_row["m15_atr_scale"])
        stop, target = directional_geometry(
            reference=reference,
            atr=atr,
            stop_distance_atr=stop_distance,
            target_distance_atr=target_distance,
            direction=direction,
        )
        signal_at = str(signal_row["checkpoint_at"])
        fill_bar = first_m1_after(stream, signal_at)
        decision_bar = latest_m1_at(stream, signal_at)
        require(fill_bar is not None and decision_bar is not None, f"Execution data absent: {alias}")
        fill = directional_fill(
            mid_open=float(fill_bar["open"]),
            spread_price=spread(fill_bar),
            slippage=SLIPPAGE,
            direction=direction,
        )
        cost = spread(decision_bar) + 2.0 * SLIPPAGE
        classification = classify_autonomous_directional(
            stream=stream,
            signal_at=signal_at,
            direction=direction,
            family=family,
            fill=fill,
            stop=stop,
            target=target,
            cost_per_ounce=cost,
        )
        raw_result = simulate_track(
            classification=classification,
            stream=stream,
            fill_at=iso(fill_bar["open_at"]),
            track="COMPLETE_V2_POLICY",
        )
        control = {
            "case_alias": alias,
            "trading_date_utc": stream["trading_date_utc"],
            "signal_at": signal_at,
            "signal_probability": probabilities[direction],
            "geometry": {
                "reference_close": reference,
                "m15_atr": atr,
                "stop_distance_atr": stop_distance,
                "target_distance_atr": target_distance,
                "family": family,
                "fill_at": iso(fill_bar["open_at"]),
                "fill": fill,
                "stop": stop,
                "target": target,
                "cost_per_ounce": cost,
            },
            "classification": classification,
            "result": raw_result,
        }
        lifecycle = (
            router.family_lifecycle(control=control, stream=stream)
            if direction == "LONG"
            else short_family_lifecycle(control=control, stream=stream)
        )
        corrected = corrected_router_lifecycle(lifecycle)
        row = {
            "case_alias": alias,
            "trading_date_utc": stream["trading_date_utc"],
            "signal_at": signal_at,
            "direction": direction,
            "direction_probabilities": probabilities,
            "disposition": str(corrected["disposition"]),
            "geometry": control["geometry"],
            "classification": classification,
            "raw_result": raw_result,
            "family_router": lifecycle,
            "corrected": corrected,
        }
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
    return rows


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = [
        row["corrected"]["effective_result"]
        for row in rows
        if row.get("corrected") is not None
        and row["corrected"].get("effective_result") is not None
        and row["corrected"]["effective_result"].get("executed")
    ]
    values = [float(result["net_r50"]) for result in results]
    wins = [value for value in values if value > EPSILON]
    losses = [value for value in values if value < -EPSILON]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "days": len(rows),
        "signals": sum(row["signal_at"] is not None for row in rows),
        "direction_conflicts": sum(row["disposition"] == "NO_TRADE_DIRECTION_CONFLICT" for row in rows),
        "signal_directions": dict(sorted(Counter(row["direction"] for row in rows if row["direction"]).items())),
        "admitted_context": sum(bool((row.get("classification") or {}).get("admitted")) for row in rows),
        "trades": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(values) - len(wins) - len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "net_r": sum(values),
        "net_usd": sum(float(result["net_usd"]) for result in results),
        "expectancy_r": sum(values) / len(values) if values else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "maximum_drawdown_r": drawdown,
        "trades_per_represented_month": len(values) / 5.0,
        "r_per_represented_month": sum(values) / 5.0,
    }


def first_passage_diagnostic(row: dict[str, Any], stream: dict[str, Any]) -> dict[str, Any] | None:
    corrected = row.get("corrected")
    lifecycle = row.get("family_router")
    if corrected is None or lifecycle is None or corrected.get("effective_result") is None:
        return None
    result = corrected["effective_result"]
    geometry = lifecycle.get("geometry")
    if geometry is None:
        return None
    direction: Direction = row["direction"]
    sign = 1.0 if direction == "LONG" else -1.0
    fill = float(geometry["fill"])
    stop = float(geometry["stop"])
    target = float(geometry["target"])
    risk = sign * (fill - stop)
    require(risk > 0, "Diagnostic structural risk is invalid")
    fill_at = parse_dt(str(geometry["fill_at"]))
    bars = [
        bar
        for bar in complete_rows(stream["timeframes"]["1m"], stream["end_exclusive"])
        if parse_dt(bar["open_at"]) >= fill_at
    ]
    max_favourable = 0.0
    max_adverse = 0.0
    first_plus_half = first_minus_half = first_plus_one = first_minus_one = None
    first_stop_index = first_target_index = None
    for index, bar in enumerate(bars):
        favourable = (
            float(bar["high"]) - fill if direction == "LONG" else fill - float(bar["low"])
        ) / risk
        adverse = (
            fill - float(bar["low"]) if direction == "LONG" else float(bar["high"]) - fill
        ) / risk
        max_favourable = max(max_favourable, favourable)
        max_adverse = max(max_adverse, adverse)
        # Ambiguous bars are adverse/stop first throughout this audit.
        if first_minus_half is None and adverse >= 0.5:
            first_minus_half = index
        if first_minus_one is None and adverse >= 1.0:
            first_minus_one = index
        if first_plus_half is None and favourable >= 0.5:
            first_plus_half = index
        if first_plus_one is None and favourable >= 1.0:
            first_plus_one = index
        stop_touch = float(bar["low"]) <= stop if direction == "LONG" else float(bar["high"]) >= stop
        target_touch = float(bar["high"]) >= target if direction == "LONG" else float(bar["low"]) <= target
        if first_stop_index is None and stop_touch:
            first_stop_index = index
        if first_target_index is None and target_touch:
            first_target_index = index
    stop_then_target = bool(
        first_stop_index is not None
        and first_target_index is not None
        and first_target_index > first_stop_index
    )
    target_first = bool(
        first_target_index is not None
        and (first_stop_index is None or first_target_index < first_stop_index)
    )
    target_r = sign * (target - fill) / risk
    reference = float(row["geometry"]["reference_close"])
    entry_degradation_r = sign * (fill - reference) / risk
    net_r = float(result["net_r50"])
    direction_failure = bool(
        first_minus_one is not None
        and (first_plus_one is None or first_minus_one <= first_plus_one)
    )
    entry_early = bool(
        first_minus_half is not None
        and (first_plus_half is None or first_minus_half <= first_plus_half)
    )
    labels: list[str] = []
    if direction_failure:
        labels.append("DIRECTION_FAILURE")
    if stop_then_target:
        labels.append("STOP_THEN_TARGET")
    if first_stop_index is not None and not stop_then_target:
        labels.append("CLEAN_INVALIDATION")
    if entry_degradation_r >= 0.5:
        labels.append("ENTRY_LATE")
    if entry_early:
        labels.append("ENTRY_EARLY_OR_UNCONFIRMED")
    if target_first and max_favourable >= target_r + 0.5:
        labels.append("TARGET_TRUNCATION")
    if max_favourable - net_r >= 0.5:
        labels.append("MANAGEMENT_GIVEBACK")
    if net_r < -EPSILON and not direction_failure and not stop_then_target:
        labels.append("NORMAL_VARIANCE")
    return {
        "case_alias": row["case_alias"],
        "trading_date_utc": row["trading_date_utc"],
        "direction": direction,
        "family": lifecycle["family"],
        "net_r": net_r,
        "resolution": result["resolution"],
        "entry_degradation_r": entry_degradation_r,
        "path_mfe_r": max_favourable,
        "path_mae_r": max_adverse,
        "target_distance_r": target_r,
        "mfe_minus_realized_r": max_favourable - net_r,
        "labels": labels,
    }


def diagnostics(rows: list[dict[str, Any]], streams: dict[str, dict[str, Any]]) -> dict[str, Any]:
    trade_rows = [
        item
        for row in rows
        if (item := first_passage_diagnostic(row, streams[row["case_alias"]])) is not None
    ]
    label_counts = Counter(label for row in trade_rows for label in row["labels"])
    label_net_r = {
        label: sum(float(row["net_r"]) for row in trade_rows if label in row["labels"])
        for label in sorted(label_counts)
    }
    return {
        "trades": len(trade_rows),
        "label_counts": dict(sorted(label_counts.items())),
        "label_realized_net_r": label_net_r,
        "sum_path_mfe_r": sum(float(row["path_mfe_r"]) for row in trade_rows),
        "sum_realized_net_r": sum(float(row["net_r"]) for row in trade_rows),
        "aggregate_mfe_retention": (
            sum(float(row["net_r"]) for row in trade_rows)
            / sum(float(row["path_mfe_r"]) for row in trade_rows)
            if sum(float(row["path_mfe_r"]) for row in trade_rows) > 0
            else None
        ),
        "rows": trade_rows,
        "rows_sha256": canonical_hash(trade_rows),
    }


def run_side(side: str, controls: list[dict[str, Any]], translator: dict[str, Any]) -> dict[str, Any]:
    streams = baseline.load_all_streams(side)
    long_control = reproduce_long_control(streams, controls, translator)
    rows: list[dict[str, Any]] = []
    for prefix in ("CBR-", "CAM-"):
        group = {key: value for key, value in streams.items() if key.startswith(prefix)}
        rows.extend(infer_group(streams=group, translator=translator))
    rows.sort(key=lambda row: (row["trading_date_utc"], row["case_alias"]))
    require([row["case_alias"] for row in rows] == [row["case_alias"] for row in controls], "Output identities differ")
    output = {
        "version": "GOLD_DIRECTION_SYMMETRIC_AUCTION_GAP_SIDE_V1_0",
        "side": side,
        "long_control_reproduction": long_control,
        "metrics": metrics(rows),
        "by_direction": {
            direction: metrics([row for row in rows if row["direction"] == direction])
            for direction in ("LONG", "SHORT")
        },
        "by_month": {
            month: metrics([row for row in rows if row["trading_date_utc"].startswith(month)])
            for month in ("2022-01", "2022-02", "2022-03", "2022-04", "2022-05")
        },
        "diagnostics": diagnostics(rows, streams),
        "rows": rows,
    }
    output["payload_sha256"] = canonical_hash(output)
    return output


def markdown(result: dict[str, Any]) -> str:
    metrics_ = result["metrics"]
    diagnostics_ = result["diagnostics"]
    lines = [
        "# Gold Direction-Symmetric Auction and Monetization-Gap Audit V1 — Result",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "This is an exposed-data diagnostic with zero validation credit.",
        "",
        "## Direction-symmetric New York result",
        "",
        "| Scope | Signals | Trades | Wins | Losses | Win % | Net R | R/month | PF | DD R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, block in [("COMBINED", metrics_), *result["by_direction"].items()]:
        lines.append(
            f"| {label} | {block['signals']} | {block['trades']} | {block['wins']} | {block['losses']} | "
            f"{100 * float(block['win_rate'] or 0):.2f} | {block['net_r']:+.4f} | "
            f"{block['r_per_represented_month']:+.4f} | {block['profit_factor']} | {block['maximum_drawdown_r']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Monetization-gap taxonomy",
            "",
            f"- Realized: {diagnostics_['sum_realized_net_r']:+.4f}R.",
            f"- Post-entry MFE ceiling: {diagnostics_['sum_path_mfe_r']:+.4f}R.",
            f"- Aggregate MFE retained: {100 * float(diagnostics_['aggregate_mfe_retention'] or 0):.2f}%.",
        ]
    )
    for label, count in diagnostics_["label_counts"].items():
        lines.append(f"- {label}: {count} trades; realized {diagnostics_['label_realized_net_r'][label]:+.4f}R.")
    lines.extend(
        [
            "",
            "The original all-session LONG implementation reproduced exactly. No fresh period, 2025, or 2026 was opened.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY, REFERENCE, FINAL, SEAL, REPORT):
        require(not path.exists(), f"One-shot output exists: {path}")
    controls = population()
    translator = load_json(TRANSLATOR)
    primary = run_side("primary", controls, translator)
    reference = run_side("reference", controls, translator)
    require(primary["long_control_reproduction"] == reference["long_control_reproduction"], "Control reproduction differs")
    require(primary["metrics"] == reference["metrics"], "Metrics reproduction differs")
    require(primary["by_direction"] == reference["by_direction"], "Direction results differ")
    require(primary["by_month"] == reference["by_month"], "Monthly results differ")
    require(primary["diagnostics"] == reference["diagnostics"], "Diagnostics reproduction differs")
    require(primary["rows"] == reference["rows"], "Daily rows reproduction differs")
    write_new_json(PRIMARY, primary)
    write_new_json(REFERENCE, reference)
    result: dict[str, Any] = {
        "version": "GOLD_DIRECTION_SYMMETRIC_AUCTION_GAP_RESULT_V1_0",
        "completed_at": now(),
        "verdict": "COMPLETE_EXPOSED_DIRECTION_SYMMETRY_AND_MONETIZATION_GAP_AUDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "primary_reference_exact": True,
        "long_control_reproduction": primary["long_control_reproduction"],
        "metrics": primary["metrics"],
        "by_direction": primary["by_direction"],
        "by_month": primary["by_month"],
        "diagnostics": primary["diagnostics"],
        "rows": primary["rows"],
        "fresh_dates_opened": False,
        "february_17_28_opened": False,
        "random_50_cases_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "validation_credit": 0,
        "paid_acquisition": False,
    }
    result["result_sha256"] = canonical_hash(result)
    write_new_json(FINAL, result)
    REPORT.write_text(markdown(result), encoding="utf-8", newline="\n")
    seal: dict[str, Any] = {
        "version": "GOLD_DIRECTION_SYMMETRIC_AUCTION_GAP_SEAL_V1_0",
        "sealed_at": now(),
        "verdict": result["verdict"],
        "files": [file_record(path) for path in (PROTOCOL, FREEZE, PRIMARY, REFERENCE, FINAL, REPORT)],
        "primary_reference_exact": True,
        "fresh_dates_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(SEAL, seal)
    print(json.dumps({"verdict": result["verdict"], "metrics": result["metrics"], "by_direction": result["by_direction"], "diagnostics": {key: value for key, value in result["diagnostics"].items() if key != "rows"}}, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run"))
    args = parser.parse_args()
    freeze() if args.phase == "freeze" else run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
