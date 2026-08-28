"""Human-policy-faithful coherent-auction calibration.

This module intentionally separates three concerns:

* the sealed operator record supplies the setup intent;
* an outcome-free contextual policy may veto that intent;
* post-fill paths are resolved only after the classification is frozen.

The policy is calibrated on an exposed sample and has no validation credit.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    complete_rows,
    confirmed_swings,
    direction_sign,
    event_is_active,
    event_lock_state,
    h4_damage_state,
    iso,
    latest_atr,
    macro_state,
    parse_dt,
    structural_breaks,
    true_ranges_and_atr,
)

RULESET = "gold-coherent-auction-human-policy-reconstruction-v2"
Direction = Literal["LONG", "SHORT"]
RISK_BUDGET_USD = 50.0
HTF_LOCATION_LIMIT = 0.80
HTF_DISPLACEMENT_LIMIT_ATR = 3.00
PROTECTION_THRESHOLD_R = 1.25
RUNNER_FRACTION = 0.20
TARGET_ACCEPTANCE_ATR = 0.10
TICK_FLOOR = 0.02


def _text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _is_substantive(value: Any) -> bool:
    text = _text(value)
    return bool(text) and text not in {
        "unknown",
        "none",
        "n/a",
        "not applicable",
        "no eligible completed higher-timeframe location.",
        "no qualifying completed m15 transition.",
    }


def _true_range(rows: Sequence[dict[str, Any]], index: int) -> float:
    row = rows[index]
    prior = float(rows[index - 1]["close"]) if index else float(row["open"])
    return max(
        float(row["high"]) - float(row["low"]),
        abs(float(row["high"]) - prior),
        abs(float(row["low"]) - prior),
    )


def _simple_h4_pivots(rows: Sequence[dict[str, Any]], width: int = 2) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index in range(width, len(rows) - width):
        window = rows[index - width : index + width + 1]
        high = float(rows[index]["high"])
        low = float(rows[index]["low"])
        if high == max(float(row["high"]) for row in window) and sum(
            float(row["high"]) == high for row in window
        ) == 1:
            output.append({"kind": "H", "index": index, "price": high})
        if low == min(float(row["low"]) for row in window) and sum(
            float(row["low"]) == low for row in window
        ) == 1:
            output.append({"kind": "L", "index": index, "price": low})
    return sorted(output, key=lambda row: (int(row["index"]), str(row["kind"])))


def h4_context_metrics(
    stream: dict[str, Any], cutoff: str, direction: Direction
) -> dict[str, Any]:
    rows = complete_rows(stream["timeframes"]["4h"], cutoff)
    if len(rows) < 24:
        return {
            "available": False,
            "reason": "INSUFFICIENT_COMPLETED_H4_BARS",
            "signed_range_location": None,
            "signed_fifteen_bar_change_atr": None,
        }
    recent_atr = rows[-14:]
    atr14 = sum(_true_range(rows, rows.index(row)) for row in recent_atr) / len(recent_atr)
    close = float(rows[-1]["close"])
    close_15 = float(rows[-16]["close"])
    recent = rows[-24:]
    range_low = min(float(row["low"]) for row in recent)
    range_high = max(float(row["high"]) for row in recent)
    raw_location = (close - range_low) / (range_high - range_low) if range_high > range_low else 0.5
    raw_change = (close - close_15) / atr14 if atr14 > 0 else None
    pivots = _simple_h4_pivots(rows)
    highs = [row for row in pivots if row["kind"] == "H"]
    lows = [row for row in pivots if row["kind"] == "L"]
    high_relation = "INSUFFICIENT"
    low_relation = "INSUFFICIENT"
    if len(highs) >= 2:
        high_relation = "HH" if float(highs[-1]["price"]) > float(highs[-2]["price"]) else "LH"
    if len(lows) >= 2:
        low_relation = "HL" if float(lows[-1]["price"]) > float(lows[-2]["price"]) else "LL"
    if high_relation == "HH" and low_relation == "HL":
        sequence = "BULLISH_SWING_SEQUENCE"
    elif high_relation == "LH" and low_relation == "LL":
        sequence = "BEARISH_SWING_SEQUENCE"
    else:
        sequence = "MIXED_OR_TRANSITIONAL_SEQUENCE"
    sign = direction_sign(direction)
    return {
        "available": True,
        "last_completed_at": iso(rows[-1]["available_at"]),
        "atr14": atr14,
        "raw_range_location": raw_location,
        "raw_fifteen_bar_change_atr": raw_change,
        "signed_range_location": raw_location if direction == "LONG" else 1.0 - raw_location,
        "signed_fifteen_bar_change_atr": sign * raw_change if raw_change is not None else None,
        "confirmed_high_relation": high_relation,
        "confirmed_low_relation": low_relation,
        "swing_sequence": sequence,
    }


def active_m15_directional_structure(
    stream: dict[str, Any], cutoff: str, direction: Direction
) -> dict[str, Any]:
    events = structural_breaks(stream["timeframes"]["15m"], cutoff, "M15", direction)
    active = [
        event
        for event in events
        if event_is_active(event, stream["timeframes"]["15m"], cutoff)
    ]
    latest = active[-1] if active else None
    return {
        "available": bool(active),
        "active_count": len(active),
        "latest_identity": latest and latest["identity"],
        "latest_break_at": latest and latest["break_at"],
        "latest_protected_level": latest and latest["protected_level"],
    }


def human_intent_fidelity(decision: dict[str, Any]) -> dict[str, Any]:
    annotation = decision.get("annotation") or {}
    direction = decision.get("direction")
    fill = decision.get("fill_price")
    stop = decision.get("sealed_stop")
    target = decision.get("sealed_target")
    geometry = False
    if direction in {"LONG", "SHORT"} and None not in {fill, stop, target}:
        sign = direction_sign(direction)
        geometry = sign * (float(fill) - float(stop)) > 0 and sign * (
            float(target) - float(fill)
        ) > 0
    checks = {
        "direction": direction in {"LONG", "SHORT"},
        "ordered_geometry": geometry,
        "higher_timeframe_context": _is_substantive(
            annotation.get("higher_timeframe_context")
            or annotation.get("preexisting_location")
        ),
        "local_transition": _is_substantive(
            annotation.get("m15_transition")
            or annotation.get("session_liquidity_context")
        ),
        "invalidation_logic": _is_substantive(annotation.get("invalidation_condition")),
        "target_logic": _is_substantive(annotation.get("target_logic")),
    }
    return {
        "detected": all(checks.values()),
        "checks": checks,
        "failed_checks": sorted(key for key, passed in checks.items() if not passed),
    }


_CONTROLLING_RANGE_PATTERNS = (
    re.compile(r"\bh[14]\s+(?:was|is)\s+(?:in\s+)?(?:a\s+)?range\b"),
    re.compile(
        r"\b(?:discount|discounted|premium)(?:\s+\w+){0,4}\s+"
        r"(?:of\s+)?(?:an?\s+)?h[14]\s+range\b"
    ),
)


def thesis_family(decision: dict[str, Any], damage: dict[str, Any] | None) -> str:
    if damage is not None:
        return "STRUCTURAL_REPAIR"
    annotation = decision.get("annotation") or {}
    context = " ".join(
        _text(annotation.get(key))
        for key in ("higher_timeframe_context", "preexisting_location", "thesis")
    )
    signed_location_word = "discount" if decision["direction"] == "LONG" else "premium"
    controlling_range = any(pattern.search(context) for pattern in _CONTROLLING_RANGE_PATTERNS)
    if controlling_range and signed_location_word in context:
        return "RANGE_ROTATION"
    return "CONTINUATION_WITH_ROOM"


def contextual_veto_codes(
    *,
    family: str,
    h4: dict[str, Any],
    m15: dict[str, Any],
    event: dict[str, Any],
    damage: dict[str, Any] | None,
) -> list[str]:
    """Return only the five frozen contextual vetoes in their gate order."""

    codes: list[str] = []
    if not m15["available"]:
        codes.append("NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE")
    if event["locked"]:
        codes.append("UNRESOLVED_TIER1_EVENT_AUCTION")
    signed_location = h4.get("signed_range_location")
    signed_displacement = h4.get("signed_fifteen_bar_change_atr")
    if (
        signed_location is not None
        and signed_displacement is not None
        and signed_location >= HTF_LOCATION_LIMIT
        and signed_displacement >= HTF_DISPLACEMENT_LIMIT_ATR
    ):
        codes.append("EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION")
    if (
        damage is not None
        and signed_displacement is not None
        and signed_displacement <= -HTF_DISPLACEMENT_LIMIT_ATR
    ):
        codes.append("SEVERE_OPPOSING_HTF_IMPULSE")
    if (
        family == "RANGE_ROTATION"
        and signed_location is not None
        and signed_location >= HTF_LOCATION_LIMIT
    ):
        codes.append("HTF_PREMIUM_RANGE_ROTATION_CONFLICT")
    return codes


def classify_predecision(
    *, decision: dict[str, Any], stream: dict[str, Any]
) -> dict[str, Any]:
    """Apply the frozen V2 policy without accepting an outcome field."""

    direction: Direction = decision["direction"]
    decision_at = iso(decision["submitted_at"])
    fill = float(decision["fill_price"])
    stop = float(decision["sealed_stop"])
    target = float(decision["sealed_target"])
    fidelity = human_intent_fidelity(decision)
    h4 = h4_context_metrics(stream, decision_at, direction)
    m15 = active_m15_directional_structure(stream, decision_at, direction)
    event = event_lock_state(stream, decision_at, direction)
    macro = macro_state(stream, decision_at, direction)
    damage = h4_damage_state(stream, decision_at, direction)
    family = thesis_family(decision, damage)
    blockers: list[dict[str, Any]] = []

    original_quantity = int(decision["quantity_ounces"])
    cost_per_ounce = (
        float(decision["estimated_base_cost_usd"]) / original_quantity
        if original_quantity > 0
        else math.inf
    )
    sign = direction_sign(direction)
    geometry_valid = (
        fidelity["detected"]
        and sign * (fill - stop) > 0
        and sign * (target - fill) > 0
        and math.isfinite(cost_per_ounce)
    )
    planned_loss_per_ounce = abs(fill - stop) + cost_per_ounce
    quantity = (
        math.floor(RISK_BUDGET_USD / planned_loss_per_ounce)
        if geometry_valid and planned_loss_per_ounce > 0
        else 0
    )
    if not geometry_valid or not h4["available"] or quantity < 1:
        blockers.append(
            {
                "gate": 1,
                "code": "GEOMETRY_OR_REQUIRED_CONTEXT_UNAVAILABLE",
                "evidence": {
                    "fidelity": fidelity,
                    "h4_available": h4["available"],
                    "quantity_ounces": quantity,
                },
            }
        )
    signed_location = h4.get("signed_range_location")
    contextual_codes = contextual_veto_codes(
        family=family, h4=h4, m15=m15, event=event, damage=damage
    )
    gate_by_code = {
        "NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE": 2,
        "UNRESOLVED_TIER1_EVENT_AUCTION": 3,
        "EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION": 4,
        "SEVERE_OPPOSING_HTF_IMPULSE": 5,
        "HTF_PREMIUM_RANGE_ROTATION_CONFLICT": 6,
    }
    for code in contextual_codes:
        evidence: Any = h4
        if code == "NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE":
            evidence = m15
        elif code == "UNRESOLVED_TIER1_EVENT_AUCTION":
            evidence = event
        elif code == "SEVERE_OPPOSING_HTF_IMPULSE":
            evidence = {"h4": h4, "damage": damage}
        blockers.append({"gate": gate_by_code[code], "code": code, "evidence": evidence})

    warnings: list[str] = []
    if macro["state"] in {"OPPOSED", "UNKNOWN"}:
        warnings.append(f"MACRO_{macro['state']}")
    if damage is not None and not any(
        item["code"] == "SEVERE_OPPOSING_HTF_IMPULSE" for item in blockers
    ):
        warnings.append("BOUNDED_STRUCTURAL_REPAIR_ONLY")
    if (
        signed_location is not None
        and signed_location >= HTF_LOCATION_LIMIT
        and not any(
            item["code"] == "EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION"
            for item in blockers
        )
    ):
        warnings.append("HIGH_HTF_LOCATION_WITHOUT_EXTENSION_CONJUNCTION")

    blockers.sort(key=lambda row: (int(row["gate"]), str(row["code"])))
    admitted = fidelity["detected"] and not blockers
    result: dict[str, Any] = {
        "ruleset": RULESET,
        "decision_at": decision_at,
        "direction": direction,
        "human_intent": fidelity,
        "family": family,
        "admitted": admitted,
        "primary_disposition": "ADMIT" if admitted else blockers[0]["code"],
        "blockers": blockers,
        "warnings": sorted(warnings),
        "macro": macro,
        "event": event,
        "h4": h4,
        "h4_damage": damage,
        "m15_structure": m15,
        "fill": fill,
        "stop": stop,
        "target": target,
        "structural_price_risk_per_ounce": abs(fill - stop),
        "cost_per_ounce": cost_per_ounce,
        "planned_loss_per_ounce": planned_loss_per_ounce,
        "quantity_ounces": quantity,
        "classification_hash": None,
    }
    result["classification_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "classification_hash"}
    )
    return result


def core_runner_split(quantity: int) -> tuple[int, int]:
    runner = math.floor(RUNNER_FRACTION * quantity)
    return quantity - runner, runner


def net_break_even_stop(
    *, fill: float, cost_per_ounce: float, direction: Direction
) -> float:
    return fill + direction_sign(direction) * cost_per_ounce


def _containing_bar(
    rows: Sequence[dict[str, Any]], timestamp: str
) -> dict[str, Any] | None:
    point = parse_dt(timestamp)
    for row in rows:
        if parse_dt(row["open_at"]) <= point < parse_dt(row["close_at"]):
            return row
    return None


def _latest_runner_stop(
    stream: dict[str, Any], cutoff: str, direction: Direction
) -> float | None:
    rows, swings = confirmed_swings(stream["timeframes"]["15m"], cutoff, "M15")
    wanted = "LOW" if direction == "LONG" else "HIGH"
    candidates = [row for row in swings if row["kind"] == wanted]
    atr = latest_atr(rows, cutoff)
    if not candidates or atr is None:
        return None
    level = float(candidates[-1]["level"])
    return level - 0.10 * atr if direction == "LONG" else level + 0.10 * atr


def _empty_result(classification: dict[str, Any], track: str) -> dict[str, Any]:
    return {
        "track": track,
        "executed": False,
        "resolution": classification["primary_disposition"],
        "net_usd": 0.0,
        "net_r50": 0.0,
        "stressed_1_5x_cost_net_usd": 0.0,
        "stressed_1_5x_cost_r50": 0.0,
        "legs": [],
        "result_hash": canonical_hash(
            [classification["classification_hash"], track, "NO_TRADE"]
        ),
    }


def simulate_track(
    *,
    classification: dict[str, Any],
    stream: dict[str, Any],
    fill_at: str,
    track: Literal["FAITHFUL_FIXED_GEOMETRY", "PROTECTED_FIXED_GEOMETRY", "COMPLETE_V2_POLICY"],
    protection_threshold_r: float = PROTECTION_THRESHOLD_R,
) -> dict[str, Any]:
    if not classification["admitted"]:
        return _empty_result(classification, track)

    direction: Direction = classification["direction"]
    sign = direction_sign(direction)
    fill = float(classification["fill"])
    initial_stop = float(classification["stop"])
    target = float(classification["target"])
    quantity = int(classification["quantity_ounces"])
    cost_per_ounce = float(classification["cost_per_ounce"])
    structural_risk = float(classification["structural_price_risk_per_ounce"])
    protection_price = fill + sign * protection_threshold_r * structural_risk
    protection_enabled = track != "FAITHFUL_FIXED_GEOMETRY"
    runner_enabled = (
        track == "COMPLETE_V2_POLICY"
        and classification["family"] == "CONTINUATION_WITH_ROOM"
    )
    path = [
        row
        for row in complete_rows(stream["timeframes"]["1m"], stream["end_exclusive"])
        if parse_dt(row["open_at"]) >= parse_dt(fill_at)
        and parse_dt(row["open_at"]) < parse_dt(stream["end_exclusive"])
    ]
    if not path:
        raise RuntimeError("Missing post-fill M1 path")
    m15 = complete_rows(stream["timeframes"]["15m"], stream["end_exclusive"])
    _, m15_atrs = true_ranges_and_atr(m15)
    m15_index = {
        (iso(row["open_at"]), iso(row["available_at"])): index
        for index, row in enumerate(m15)
    }

    current_stop = initial_stop
    last_m15_processed = fill_at
    protection_at: str | None = None
    target_touched = False
    target_touch_m15: dict[str, Any] | None = None
    target_acceptance: bool | None = None
    runner_active = False
    runner_stop_changes: list[dict[str, Any]] = []
    core_quantity, runner_quantity = core_runner_split(quantity) if runner_enabled else (quantity, 0)
    remaining = quantity
    legs: list[dict[str, Any]] = []
    path_high = fill
    path_low = fill

    def append_leg(qty: int, price: float, at: str, resolution: str) -> None:
        nonlocal remaining
        if qty <= 0:
            return
        legs.append(
            {
                "quantity_ounces": qty,
                "exit_price": price,
                "exit_at": iso(at),
                "resolution": resolution,
            }
        )
        remaining -= qty

    for row in path:
        now = iso(row["open_at"])
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        path_high = max(path_high, high)
        path_low = min(path_low, low)

        newly_completed = [
            bar
            for bar in m15
            if parse_dt(last_m15_processed) < parse_dt(bar["available_at"]) <= parse_dt(now)
        ]
        for completed in newly_completed:
            last_m15_processed = iso(completed["available_at"])
            aligned_close = sign * (float(completed["close"]) - protection_price) >= 0
            if protection_enabled and protection_at is None and aligned_close:
                proposed = net_break_even_stop(
                    fill=fill, cost_per_ounce=cost_per_ounce, direction=direction
                )
                current_stop = (
                    max(current_stop, proposed)
                    if direction == "LONG"
                    else min(current_stop, proposed)
                )
                protection_at = iso(completed["available_at"])

            if (
                target_touched
                and target_acceptance is None
                and target_touch_m15 is not None
                and iso(completed["open_at"]) == iso(target_touch_m15["open_at"])
            ):
                index = m15_index[(iso(completed["open_at"]), iso(completed["available_at"]))]
                atr = m15_atrs[index]
                accepted = atr is not None and sign * (
                    float(completed["close"]) - target
                ) >= TARGET_ACCEPTANCE_ATR * atr
                target_acceptance = bool(accepted)
                if accepted and remaining > 0:
                    runner_active = True
                elif remaining > 0:
                    append_leg(remaining, open_price, now, "RUNNER_NO_TARGET_ACCEPTANCE")

            if runner_active and remaining > 0:
                proposed = _latest_runner_stop(stream, iso(completed["available_at"]), direction)
                if proposed is not None:
                    prior = current_stop
                    current_stop = (
                        max(current_stop, proposed)
                        if direction == "LONG"
                        else min(current_stop, proposed)
                    )
                    if current_stop != prior:
                        runner_stop_changes.append(
                            {
                                "available_at": iso(completed["available_at"]),
                                "prior_stop": prior,
                                "new_stop": current_stop,
                            }
                        )

        if remaining <= 0:
            break

        gap_stopped = open_price <= current_stop if direction == "LONG" else open_price >= current_stop
        if gap_stopped:
            append_leg(remaining, open_price, now, "GAP_STOP")
            break
        stop_touched = low <= current_stop if direction == "LONG" else high >= current_stop
        if stop_touched:
            reason = "PROTECTED_STOP" if protection_at is not None else "STRUCTURAL_STOP"
            append_leg(remaining, current_stop, now, reason)
            break

        reached_target = high >= target if direction == "LONG" else low <= target
        if reached_target and not target_touched:
            target_touched = True
            if runner_quantity <= 0:
                append_leg(remaining, target, now, "SEALED_TARGET")
            else:
                target_touch_m15 = _containing_bar(m15, now)
                append_leg(min(core_quantity, remaining), target, now, "SEALED_TARGET_CORE")
                if target_touch_m15 is None and remaining > 0:
                    target_acceptance = False
                    append_leg(remaining, target, now, "RUNNER_CONTEXT_UNAVAILABLE")
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
        "track": track,
        "executed": True,
        "resolution": legs[-1]["resolution"],
        "final_at": legs[-1]["exit_at"],
        "quantity_ounces": quantity,
        "legs": legs,
        "protection_threshold_r": protection_threshold_r if protection_enabled else None,
        "protection_at": protection_at,
        "target_touched": target_touched,
        "target_acceptance": target_acceptance,
        "runner_quantity_ounces": runner_quantity,
        "runner_activated": runner_active,
        "runner_stop_changes": runner_stop_changes,
        "gross_usd": gross,
        "cost_usd": total_cost,
        "net_usd": net,
        "net_r50": net / RISK_BUDGET_USD,
        "stressed_1_5x_cost_net_usd": stressed,
        "stressed_1_5x_cost_r50": stressed / RISK_BUDGET_USD,
        "mfe_r50": favourable * quantity / RISK_BUDGET_USD,
        "mae_r50": adverse * quantity / RISK_BUDGET_USD,
        "result_hash": None,
    }
    result["result_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "result_hash"}
    )
    return result
