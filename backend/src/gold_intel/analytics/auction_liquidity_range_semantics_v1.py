"""Point-in-time liquidity inventory and range context for sealed auction events.

Liquidity consumption is deliberately independent of close-based structural
acceptance. A confirmed high is consumed by a later observed price strictly
above it; a confirmed low is consumed by a later observed price strictly below
it. No ATR, body, close, or persistence condition is used for that lifecycle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    complete_rows,
    confirmed_swings,
    iso,
    parse_dt,
    swing_relations,
    true_ranges_and_atr,
)

Direction = Literal["LONG", "SHORT"]
LiquidityState = Literal[
    "UNCONSUMED_UNTOUCHED",
    "UNCONSUMED_ENGAGED",
    "CONSUMED",
    "UNKNOWN_TECHNICAL",
]

RULESET = "GOLD_AUCTION_LIQUIDITY_AND_RANGE_SEMANTICS_AMENDMENT_B_V1"
TIMEFRAME_KEYS: Mapping[str, str] = {
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "H4": "4h",
}
RANGE_WINDOW_BARS = 20
RANGE_MAX_WIDTH_ATR = 5.0
RANGE_REJECTION_PROXIMITY_ATR = 0.50


def _unknown(swing: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "identity": str(swing.get("identity", "UNKNOWN")),
        "kind": str(swing.get("kind", "UNKNOWN")),
        "timeframe": str(swing.get("timeframe", "UNKNOWN")),
        "pivot_at": None if swing.get("pivot_at") is None else iso(swing["pivot_at"]),
        "known_at": None if swing.get("detected_at") is None else iso(swing["detected_at"]),
        "level": None if swing.get("level") is None else float(swing["level"]),
        "state": "UNKNOWN_TECHNICAL",
        "engaged_at": None,
        "consumed_at": None,
        "reason": reason,
        "epistemic_status": "UNKNOWN",
    }


def classify_pivot_liquidity(
    rows: Sequence[dict[str, Any]],
    swing: Mapping[str, Any],
    cutoff: str,
    *,
    completed: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify one known swing using strict later traded-price extrema."""

    required = {"identity", "kind", "timeframe", "pivot_at", "detected_at", "level"}
    if not required.issubset(swing):
        return _unknown(swing, "SWING_FIELDS_MISSING")
    if parse_dt(swing["detected_at"]) > parse_dt(cutoff):
        return _unknown(swing, "PIVOT_NOT_KNOWN_AT_CUTOFF")
    kind = str(swing["kind"])
    if kind not in {"HIGH", "LOW"}:
        return _unknown(swing, "UNSUPPORTED_SWING_KIND")

    bars = list(completed) if completed is not None else complete_rows(rows, cutoff)
    pivot_rows = [row for row in bars if iso(row["open_at"]) == iso(swing["pivot_at"])]
    if len(pivot_rows) != 1:
        return _unknown(swing, "PIVOT_CANDLE_NOT_UNIQUELY_RESOLVED")
    pivot_row = pivot_rows[0]
    level = float(swing["level"])
    recorded = float(pivot_row["high"] if kind == "HIGH" else pivot_row["low"])
    if recorded != level:
        return _unknown(swing, "PIVOT_LEVEL_DIFFERS_FROM_SOURCE_EXTREME")

    origin_complete = parse_dt(pivot_row["available_at"])
    later = [row for row in bars if parse_dt(row["available_at"]) > origin_complete]
    engaged_at: str | None = None
    consumed_at: str | None = None
    for row in later:
        traded = float(row["high"] if kind == "HIGH" else row["low"])
        engaged = traded >= level if kind == "HIGH" else traded <= level
        consumed = traded > level if kind == "HIGH" else traded < level
        if engaged and engaged_at is None:
            engaged_at = iso(row["available_at"])
        if consumed:
            consumed_at = iso(row["available_at"])
            break

    state: LiquidityState
    if consumed_at is not None:
        state = "CONSUMED"
    elif engaged_at is not None:
        state = "UNCONSUMED_ENGAGED"
    else:
        state = "UNCONSUMED_UNTOUCHED"
    payload: dict[str, Any] = {
        "identity": str(swing["identity"]),
        "kind": kind,
        "timeframe": str(swing["timeframe"]),
        "pivot_at": iso(swing["pivot_at"]),
        "pivot_candle_completed_at": iso(pivot_row["available_at"]),
        "known_at": iso(swing["detected_at"]),
        "level": level,
        "state": state,
        "engaged_at": engaged_at,
        "consumed_at": consumed_at,
        "strict_beyond_rule": "LATER_HIGH_GT_LEVEL" if kind == "HIGH" else "LATER_LOW_LT_LEVEL",
        "close_or_atr_required": False,
        "epistemic_status": "CALCULATED_FROM_OBSERVED_TRADED_PRICE_EXTREMA",
    }
    payload["lifecycle_sha256"] = canonical_hash(payload)
    return payload


def build_timeframe_inventory(
    rows: Sequence[dict[str, Any]], cutoff: str, timeframe: str
) -> dict[str, Any]:
    completed, swings = confirmed_swings(rows, cutoff, timeframe)
    states = [
        classify_pivot_liquidity(rows, swing, cutoff, completed=completed)
        for swing in swings
        if parse_dt(swing["detected_at"]) <= parse_dt(cutoff)
    ]
    payload: dict[str, Any] = {
        "timeframe": timeframe,
        "cutoff": iso(cutoff),
        "completed_bars": len(completed),
        "known_pivots": len(states),
        "states": states,
        "state_counts": {
            state: sum(item["state"] == state for item in states)
            for state in (
                "UNCONSUMED_UNTOUCHED",
                "UNCONSUMED_ENGAGED",
                "CONSUMED",
                "UNKNOWN_TECHNICAL",
            )
        },
    }
    payload["inventory_sha256"] = canonical_hash(payload)
    return payload


def nearest_unconsumed_destination(
    inventory: Mapping[str, Any], *, direction: Direction, price: float
) -> dict[str, Any] | None:
    kind = "HIGH" if direction == "LONG" else "LOW"
    eligible = [
        item
        for item in inventory["states"]
        if item["kind"] == kind
        and str(item["state"]).startswith("UNCONSUMED_")
        and (
            float(item["level"]) > price
            if direction == "LONG"
            else float(item["level"]) < price
        )
    ]
    if not eligible:
        return None
    selected = min(
        eligible,
        key=lambda item: (abs(float(item["level"]) - price), parse_dt(item["known_at"]), item["identity"]),
    )
    return {
        **selected,
        "distance_price": abs(float(selected["level"]) - price),
        "role": "UNCONSUMED_DESTINATION_CANDIDATE",
    }


def structure_state(inventory: Mapping[str, Any]) -> dict[str, Any]:
    swings = [
        {
            "kind": item["kind"],
            "level": item["level"],
            "detected_at": item["known_at"],
            "identity": item["identity"],
        }
        for item in inventory["states"]
        if item["state"] != "UNKNOWN_TECHNICAL"
    ]
    relations = swing_relations(swings)
    if relations == {"high": "HH", "low": "HL"}:
        state = "UPTREND"
    elif relations == {"high": "LH", "low": "LL"}:
        state = "DOWNTREND"
    else:
        state = "MIXED_OR_TRANSITIONING"
    return {"state": state, "relations": relations}


def _boundary_item(
    candidates: Sequence[dict[str, Any]], *, high: bool
) -> dict[str, Any]:
    level = (
        max(float(item["level"]) for item in candidates)
        if high
        else min(float(item["level"]) for item in candidates)
    )
    exact = [item for item in candidates if float(item["level"]) == level]
    return max(exact, key=lambda item: (parse_dt(item["known_at"]), item["identity"]))


def active_range_context(
    rows: Sequence[dict[str, Any]],
    *,
    cutoff: str,
    timeframe: str,
    direction: Direction,
    price: float,
    inventory: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Identify a two-sided range from exact, still-unconsumed pivots."""

    inv = inventory or build_timeframe_inventory(rows, cutoff, timeframe)
    bars = complete_rows(rows, cutoff)

    def absent(reason: str, **details: Any) -> dict[str, Any]:
        return {"state": "NO_ACTIVE_RANGE", "reason": reason, **details}

    if len(bars) < RANGE_WINDOW_BARS:
        return absent("INSUFFICIENT_COMPLETED_BARS", completed_bars=len(bars))
    _, atrs = true_ranges_and_atr(bars)
    atr = atrs[-1]
    if atr is None or atr <= 0:
        return absent("CURRENT_ATR_UNAVAILABLE")

    start_index = len(bars) - RANGE_WINDOW_BARS
    by_identity = {str(item["identity"]): item for item in inv["states"]}
    _, known_swings = confirmed_swings(rows, cutoff, timeframe)
    members = [
        by_identity[str(swing["identity"])]
        for swing in known_swings
        if int(swing["pivot_index"]) >= start_index
        and str(swing["identity"]) in by_identity
        and by_identity[str(swing["identity"])]["state"] != "UNKNOWN_TECHNICAL"
    ]
    highs = [item for item in members if item["kind"] == "HIGH"]
    lows = [item for item in members if item["kind"] == "LOW"]
    if len(highs) < 2 or len(lows) < 2:
        return absent("INSUFFICIENT_TWO_SIDED_CONFIRMED_PIVOTS", highs=len(highs), lows=len(lows))

    upper = _boundary_item(highs, high=True)
    lower = _boundary_item(lows, high=False)
    width = float(upper["level"]) - float(lower["level"])
    if width <= 0:
        return absent("NONPOSITIVE_BOUNDARY_WIDTH")
    width_atr = width / float(atr)
    if width_atr > RANGE_MAX_WIDTH_ATR:
        return absent("BOUNDARY_WIDTH_EXCEEDS_LIMIT", width_atr=width_atr)

    proximity = RANGE_REJECTION_PROXIMITY_ATR * float(atr)
    upper_interactions = [item for item in highs if float(item["level"]) >= float(upper["level"]) - proximity]
    lower_interactions = [item for item in lows if float(item["level"]) <= float(lower["level"]) + proximity]
    if len(upper_interactions) < 2 or len(lower_interactions) < 2:
        return absent(
            "REPEATED_BOUNDARY_REJECTION_NOT_CONFIRMED",
            upper_interactions=len(upper_interactions),
            lower_interactions=len(lower_interactions),
        )
    if upper["state"] == "CONSUMED" or lower["state"] == "CONSUMED":
        return absent(
            "EXACT_RANGE_BOUNDARY_CONSUMED",
            upper_state=upper["state"],
            lower_state=lower["state"],
        )
    if not (float(lower["level"]) <= price <= float(upper["level"])):
        return absent("DECISION_PRICE_OUTSIDE_BOUNDARIES")

    midpoint = (float(lower["level"]) + float(upper["level"])) / 2.0
    inward = (direction == "LONG" and price <= midpoint) or (
        direction == "SHORT" and price >= midpoint
    )
    known_at = max(
        [item["known_at"] for item in (*upper_interactions, *lower_interactions)],
        key=parse_dt,
    )
    payload: dict[str, Any] = {
        "state": "ACTIVE_RANGE",
        "timeframe": timeframe,
        "known_at": known_at,
        "window_bars": RANGE_WINDOW_BARS,
        "window_first_open_at": iso(bars[start_index]["open_at"]),
        "atr": float(atr),
        "width_atr": width_atr,
        "lower_boundary": lower,
        "upper_boundary": upper,
        "lower_interaction_identities": [item["identity"] for item in lower_interactions],
        "upper_interaction_identities": [item["identity"] for item in upper_interactions],
        "midpoint": midpoint,
        "decision_location": (price - float(lower["level"])) / width,
        "direction_relation": "INWARD_FROM_DIRECTIONAL_HALF" if inward else "OUTWARD_FROM_OPPOSITE_HALF",
        "context_family": (
            "RANGE_ROTATION_WITH_LTF_CONTROL"
            if inward
            else "RANGE_OPPOSITE_HALF_WITH_LTF_CONTROL"
        ),
        "epistemic_status": "CALCULATED_POINT_IN_TIME_RANGE_CONTEXT",
    }
    payload["range_identity"] = canonical_hash(
        [
            "ACTIVE_RANGE",
            timeframe,
            lower["identity"],
            upper["identity"],
            known_at,
        ]
    )
    payload["range_sha256"] = canonical_hash(payload)
    return payload


def event_semantic_overlay(
    stream: Mapping[str, Any], event: Mapping[str, Any]
) -> dict[str, Any]:
    """Build an outcome-blind overlay without mutating the sealed event."""

    cutoff = str(event["decision_at"])
    direction: Direction = str(event["direction"])  # type: ignore[assignment]
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"Unsupported direction: {direction}")
    price = float(event["decision_price"])
    frames: dict[str, dict[str, Any]] = {}
    for timeframe, key in TIMEFRAME_KEYS.items():
        inventory = build_timeframe_inventory(stream["timeframes"][key], cutoff, timeframe)
        state_by_identity = {item["identity"]: item for item in inventory["states"]}
        active = event.get("active_breaks", {}).get(timeframe)
        active_roles: dict[str, Any] | None = None
        if active is not None:
            active_roles = {
                "broken_control_pivot": state_by_identity.get(str(active["broken_identity"])),
                "protected_internal_pivot": state_by_identity.get(str(active["protected_identity"])),
            }
        inventory_summary = {
            name: value
            for name, value in inventory.items()
            if name != "states"
        }
        frame: dict[str, Any] = {
            "inventory_summary": inventory_summary,
            "nearest_unconsumed_destination": nearest_unconsumed_destination(
                inventory, direction=direction, price=price
            ),
            "active_control_roles": active_roles,
            "structure": structure_state(inventory),
        }
        if timeframe in {"H1", "H4"}:
            frame["range"] = active_range_context(
                stream["timeframes"][key],
                cutoff=cutoff,
                timeframe=timeframe,
                direction=direction,
                price=price,
                inventory=inventory,
            )
        frames[timeframe] = frame

    active_ranges = [
        frames[timeframe]["range"]
        for timeframe in ("H4", "H1")
        if frames[timeframe]["range"]["state"] == "ACTIVE_RANGE"
    ]
    inward = [item for item in active_ranges if item["direction_relation"] == "INWARD_FROM_DIRECTIONAL_HALF"]
    if inward:
        context_family = "RANGE_ROTATION_WITH_LTF_CONTROL"
    elif active_ranges:
        context_family = "RANGE_OPPOSITE_HALF_WITH_LTF_CONTROL"
    else:
        aligned_trend = any(
            (direction == "LONG" and frames[timeframe]["structure"]["state"] == "UPTREND")
            or (direction == "SHORT" and frames[timeframe]["structure"]["state"] == "DOWNTREND")
            for timeframe in ("H4", "H1")
        )
        context_family = (
            "TREND_PULLBACK_WITH_LTF_CONTROL"
            if aligned_trend
            else "TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL"
        )

    overlay: dict[str, Any] = {
        "ruleset": RULESET,
        "event_identity": str(event["event_identity"]),
        "case_alias": str(event["case_alias"]),
        "decision_at": iso(cutoff),
        "direction": direction,
        "decision_price": price,
        "context_family": context_family,
        "timeframes": frames,
        "epistemic_status": {
            "traded_price_extrema": "OBSERVED",
            "confirmed_pivots_and_lifecycles": "CALCULATED",
            "range_context": "CALCULATED",
            "resting_orders_or_institutional_intent": "UNKNOWN",
        },
        "original_event_sha256": str(event["event_sha256"]),
        "source_stream_sha256": str(stream["stream_sha256"]),
    }
    overlay["overlay_sha256"] = canonical_hash(overlay)
    return overlay
