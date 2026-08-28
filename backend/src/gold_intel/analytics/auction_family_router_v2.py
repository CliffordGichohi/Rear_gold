"""Pure auction-semantic routing and structural management for Router V2."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    BREAK_BUFFER_ATR,
    TICK_FLOOR,
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
    structural_breaks,
    true_ranges_and_atr,
)

Direction = Literal["LONG", "SHORT"]
RISK_USD = 50.0
RUNNER_FRACTION = 0.20
TARGET_ACCEPTANCE_ATR = 0.10


def direction_sign(direction: Direction) -> int:
    return 1 if direction == "LONG" else -1


def balance_boundary_reclaim_qualifies(
    row: dict[str, Any], *, boundary: float, direction: Direction
) -> bool:
    """Require a real sweep and reclaim of a named balance boundary."""

    if row.get("complete") is not True:
        return False
    opened = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    closed = float(row["close"])
    midpoint = (high + low) / 2.0
    if direction == "LONG":
        return (
            low <= float(boundary) - TICK_FLOOR
            and closed > float(boundary)
            and closed > opened
            and closed >= midpoint
        )
    return (
        high >= float(boundary) + TICK_FLOOR
        and closed < float(boundary)
        and closed < opened
        and closed <= midpoint
    )


def first_balance_boundary_reclaim(
    rows: Sequence[dict[str, Any]],
    *,
    signal_at: str | datetime,
    session_end: str | datetime,
    boundary: float,
    boundary_identity: str,
    direction: Direction,
    maximum_bars: int = 6,
) -> dict[str, Any] | None:
    signal = parse_dt(signal_at)
    end = parse_dt(session_end)
    eligible = [
        row
        for row in complete_rows(rows, end)
        if signal < parse_dt(row["available_at"]) <= end
        and parse_dt(row["open_at"]) < end
    ][:maximum_bars]
    for occurrence, row in enumerate(eligible, start=1):
        if not balance_boundary_reclaim_qualifies(
            row, boundary=boundary, direction=direction
        ):
            continue
        payload = {
            "route": "NAMED_BALANCE_BOUNDARY_SWEEP_RECLAIM",
            "direction": direction,
            "confirmation_at": iso(row["available_at"]),
            "bar_open_at": iso(row["open_at"]),
            "within_route_occurrence": occurrence,
            "boundary": float(boundary),
            "boundary_identity": boundary_identity,
            "bar_identity": bar_identity(row),
        }
        payload["route_hash"] = canonical_hash(payload)
        return payload
    return None


def plan_trigger_event(plan: dict[str, Any]) -> dict[str, Any] | None:
    """Select M5 refinement when present, otherwise the M15 setup layer."""

    local = (plan.get("components") or {}).get("local_trigger")
    if not isinstance(local, dict):
        return None
    layer = local.get("entry_refinement") or local.get("setup_transition")
    if not isinstance(layer, dict) or layer.get("timeframe") not in {"M5", "M15"}:
        return None
    required = (
        "event_identity",
        "timeframe",
        "direction",
        "break_at",
        "broken_swing_identity",
        "broken_level",
        "protected_swing_identity",
        "protected_level",
        "transition_origin_at",
        "transition_origin_adverse",
        "transition_atr",
        "break_buffer",
    )
    if any(layer.get(key) is None for key in required):
        return None
    return {
        "identity": str(layer["event_identity"]),
        "timeframe": str(layer["timeframe"]),
        "direction": str(layer["direction"]),
        "break_at": iso(layer["break_at"]),
        "broken_identity": str(layer["broken_swing_identity"]),
        "broken_level": float(layer["broken_level"]),
        "protected_identity": str(layer["protected_swing_identity"]),
        "protected_level": float(layer["protected_level"]),
        "origin_at": iso(layer["transition_origin_at"]),
        "origin_adverse": float(layer["transition_origin_adverse"]),
        "atr": float(layer["transition_atr"]),
        "buffer": float(layer["break_buffer"]),
        "semantic_layer_identity": str(layer["identity"]),
    }


def trigger_is_fresh(
    event: dict[str, Any], *, signal_at: str | datetime
) -> bool:
    signal = parse_dt(signal_at)
    broken = parse_dt(event["break_at"])
    maximum_age = timedelta(minutes=5 if event["timeframe"] == "M5" else 15)
    return timedelta(0) <= signal - broken <= maximum_age


def direct_continuation_route(
    event: dict[str, Any], *, signal_at: str | datetime
) -> dict[str, Any]:
    payload = {
        "route": "FRESH_COMPILED_CONTINUATION_DIRECT",
        "direction": event["direction"],
        "confirmation_at": iso(signal_at),
        "bar_open_at": None,
        "within_route_occurrence": 0,
        "event_identity": event["identity"],
        "event_timeframe": event["timeframe"],
        "event_break_at": event["break_at"],
    }
    payload["route_hash"] = canonical_hash(payload)
    return payload


def planned_geometry(
    *, fill: float, stop: float, target: float, cost_per_ounce: float, direction: Direction
) -> dict[str, Any]:
    sign = direction_sign(direction)
    risk = sign * (float(fill) - float(stop))
    reward = sign * (float(target) - float(fill))
    valid = (
        all(math.isfinite(value) for value in (fill, stop, target, cost_per_ounce))
        and risk > 0
        and reward > 0
        and cost_per_ounce >= 0
    )
    room = reward / risk if valid else None
    planned_loss = risk + float(cost_per_ounce) if valid else None
    quantity = (
        math.floor(RISK_USD / planned_loss)
        if planned_loss is not None and planned_loss > 0
        else 0
    )
    return {
        "geometry_valid": valid,
        "structural_risk_per_ounce": risk if valid else None,
        "target_room_r": room,
        "passes_actual_fill_1p5r": bool(valid and room is not None and room >= 1.5),
        "planned_loss_per_ounce": planned_loss,
        "quantity_ounces": quantity,
        "passes_whole_ounce_risk": quantity >= 1,
    }


def _containing_bar(
    rows: Sequence[dict[str, Any]], timestamp: str | datetime
) -> dict[str, Any] | None:
    point = parse_dt(timestamp)
    for row in rows:
        if parse_dt(row["open_at"]) <= point < parse_dt(row["close_at"]):
            return row
    return None


def _trail_events(
    rows: Sequence[dict[str, Any]],
    *,
    cutoff: str | datetime,
    timeframe: str,
    direction: Direction,
    after: str | datetime,
) -> list[dict[str, Any]]:
    return structural_breaks(
        rows,
        cutoff,
        timeframe,
        direction,
        after=after,
    )


def simulate_structural_management(
    *,
    classification: dict[str, Any],
    stream: dict[str, Any],
    fill_at: str,
    m5_trail_events: Sequence[dict[str, Any]] | None = None,
    m15_trail_events: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Simulate explicit invalidation, liquidity target, and structural trails."""

    if not classification["admitted"]:
        payload = {
            "track": "AUCTION_SEMANTIC_STRUCTURAL_MANAGEMENT_V2",
            "executed": False,
            "resolution": classification["primary_disposition"],
            "net_usd": 0.0,
            "net_r50": 0.0,
            "stressed_1_5x_cost_net_usd": 0.0,
            "stressed_1_5x_cost_r50": 0.0,
            "legs": [],
            "result_hash": canonical_hash(
                [classification["classification_hash"], "STRUCTURAL_MANAGEMENT_V2", "NO_TRADE"]
            ),
        }
        return payload

    direction: Direction = classification["direction"]
    sign = direction_sign(direction)
    fill = float(classification["fill"])
    initial_stop = float(classification["stop"])
    target = float(classification["target"])
    quantity = int(classification["quantity_ounces"])
    cost_per_ounce = float(classification["cost_per_ounce"])
    family = str(classification["family"])
    require_geometry = planned_geometry(
        fill=fill,
        stop=initial_stop,
        target=target,
        cost_per_ounce=cost_per_ounce,
        direction=direction,
    )
    if not (
        require_geometry["geometry_valid"]
        and require_geometry["passes_actual_fill_1p5r"]
        and require_geometry["passes_whole_ounce_risk"]
        and quantity == require_geometry["quantity_ounces"]
    ):
        raise ValueError("Classification violates frozen actual-fill geometry")

    end = stream["end_exclusive"]
    path = [
        row
        for row in complete_rows(stream["timeframes"]["1m"], end)
        if parse_dt(fill_at) <= parse_dt(row["open_at"]) < parse_dt(end)
    ]
    if not path:
        raise ValueError("Missing post-fill M1 path")
    m5 = complete_rows(stream["timeframes"]["5m"], end)
    m15 = complete_rows(stream["timeframes"]["15m"], end)
    _, m15_atrs = true_ranges_and_atr(m15)
    m15_index = {
        (iso(row["open_at"]), iso(row["available_at"])): index
        for index, row in enumerate(m15)
    }
    m5_events = list(m5_trail_events) if m5_trail_events is not None else _trail_events(
        m5, cutoff=end, timeframe="M5", direction=direction, after=fill_at
    )
    m15_events = list(m15_trail_events) if m15_trail_events is not None else _trail_events(
        m15, cutoff=end, timeframe="M15", direction=direction, after=fill_at
    )
    m5_events.sort(key=lambda row: (parse_dt(row["break_at"]), str(row["identity"])))
    m15_events.sort(key=lambda row: (parse_dt(row["break_at"]), str(row["identity"])))

    current_stop = initial_stop
    m5_cursor = m15_cursor = 0
    target_touched = False
    target_touch_at: str | None = None
    target_touch_m15: dict[str, Any] | None = None
    target_acceptance: bool | None = None
    runner_active = False
    runner_quantity = math.floor(RUNNER_FRACTION * quantity) if family == "CONTINUATION_WITH_ROOM" else 0
    core_quantity = quantity - runner_quantity
    remaining = quantity
    legs: list[dict[str, Any]] = []
    stop_changes: list[dict[str, Any]] = []
    path_high = fill
    path_low = fill

    def append_leg(qty: int, price: float, at: str, resolution: str) -> None:
        nonlocal remaining
        if qty <= 0:
            return
        legs.append(
            {
                "quantity_ounces": qty,
                "exit_price": float(price),
                "exit_at": iso(at),
                "resolution": resolution,
            }
        )
        remaining -= qty

    def advance_stop(event: dict[str, Any], source: str, available_at: str) -> None:
        nonlocal current_stop
        buffer = max(BREAK_BUFFER_ATR * float(event["atr"]), TICK_FLOOR)
        proposed = (
            float(event["protected_level"]) - buffer
            if direction == "LONG"
            else float(event["protected_level"]) + buffer
        )
        improves = sign * (proposed - current_stop) > 0
        if not improves:
            return
        prior = current_stop
        current_stop = proposed
        stop_changes.append(
            {
                "available_at": iso(available_at),
                "source": source,
                "event_identity": event["identity"],
                "prior_stop": prior,
                "new_stop": current_stop,
            }
        )

    for row in path:
        now = iso(row["open_at"])
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        path_high = max(path_high, high)
        path_low = min(path_low, low)

        while m5_cursor < len(m5_events) and parse_dt(m5_events[m5_cursor]["break_at"]) <= parse_dt(now):
            event = m5_events[m5_cursor]
            advance_stop(event, "COMPLETED_M5_ALIGNED_BREAK", event["break_at"])
            m5_cursor += 1

        if (
            target_touched
            and target_acceptance is None
            and target_touch_m15 is not None
            and parse_dt(target_touch_m15["available_at"]) <= parse_dt(now)
        ):
            index = m15_index[(iso(target_touch_m15["open_at"]), iso(target_touch_m15["available_at"]))]
            atr = m15_atrs[index]
            target_acceptance = bool(
                atr is not None
                and sign * (float(target_touch_m15["close"]) - target)
                >= TARGET_ACCEPTANCE_ATR * atr
            )
            if target_acceptance:
                runner_active = True
            elif remaining > 0:
                append_leg(remaining, open_price, now, "DESTINATION_NOT_ACCEPTED")

        while m15_cursor < len(m15_events) and parse_dt(m15_events[m15_cursor]["break_at"]) <= parse_dt(now):
            event = m15_events[m15_cursor]
            if (
                runner_active
                and target_touch_at is not None
                and parse_dt(event["break_at"]) > parse_dt(target_touch_at)
            ):
                advance_stop(event, "POST_ACCEPTANCE_M15_ALIGNED_BREAK", event["break_at"])
            m15_cursor += 1

        if remaining <= 0:
            break
        gap_stopped = open_price <= current_stop if direction == "LONG" else open_price >= current_stop
        if gap_stopped:
            append_leg(remaining, open_price, now, "GAP_AUCTION_INVALIDATION")
            break
        stop_touched = low <= current_stop if direction == "LONG" else high >= current_stop
        target_reached = high >= target if direction == "LONG" else low <= target
        if stop_touched:
            reason = (
                "INITIAL_AUCTION_INVALIDATION"
                if not stop_changes
                else "STRUCTURAL_TRAIL_INVALIDATION"
            )
            append_leg(remaining, current_stop, now, reason)
            break
        if target_reached and not target_touched:
            target_touched = True
            target_touch_at = now
            if runner_quantity <= 0:
                append_leg(remaining, target, now, "EXPLICIT_LIQUIDITY_DESTINATION")
            else:
                target_touch_m15 = _containing_bar(m15, now)
                append_leg(min(core_quantity, remaining), target, now, "EXPLICIT_DESTINATION_CORE")
                if target_touch_m15 is None and remaining > 0:
                    target_acceptance = False
                    append_leg(remaining, target, now, "DESTINATION_CONTEXT_UNAVAILABLE")
        if remaining <= 0:
            break

    if remaining > 0:
        last = path[-1]
        append_leg(remaining, float(last["close"]), last["close_at"], "UTC_DAY_TIME_EXIT")

    gross = sum(
        sign * (float(leg["exit_price"]) - fill) * int(leg["quantity_ounces"])
        for leg in legs
    )
    total_cost = cost_per_ounce * quantity
    net = gross - total_cost
    stressed = gross - 1.5 * total_cost
    favourable = path_high - fill if direction == "LONG" else fill - path_low
    adverse = fill - path_low if direction == "LONG" else path_high - fill
    result: dict[str, Any] = {
        "track": "AUCTION_SEMANTIC_STRUCTURAL_MANAGEMENT_V2",
        "executed": True,
        "resolution": legs[-1]["resolution"],
        "final_at": legs[-1]["exit_at"],
        "quantity_ounces": quantity,
        "legs": legs,
        "numeric_break_even_used": False,
        "initial_stop": initial_stop,
        "final_stop": current_stop,
        "structural_stop_changes": stop_changes,
        "target_touched": target_touched,
        "target_acceptance": target_acceptance,
        "runner_quantity_ounces": runner_quantity,
        "runner_activated": runner_active,
        "gross_usd": gross,
        "cost_usd": total_cost,
        "net_usd": net,
        "net_r50": net / RISK_USD,
        "stressed_1_5x_cost_net_usd": stressed,
        "stressed_1_5x_cost_r50": stressed / RISK_USD,
        "mfe_r50": favourable * quantity / RISK_USD,
        "mae_r50": adverse * quantity / RISK_USD,
        "result_hash": None,
    }
    result["result_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "result_hash"}
    )
    return result


def bar_identity(row: dict[str, Any]) -> str:
    return canonical_hash(
        {
            key: row.get(key)
            for key in (
                "open_at",
                "close_at",
                "available_at",
                "open",
                "high",
                "low",
                "close",
                "complete",
                "source_record_hash",
            )
        }
    )
