"""Outcome-blind swing-curvature entry semantics.

This module stops at a complete point-in-time auction plan. It contains no
path simulator and accepts no outcome, PnL, MFE, MAE, or trade-result input.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from gold_intel.analytics.auction_control_router_v1 import session_bounds
from gold_intel.analytics.auction_liquidity_range_semantics_v1 import (
    active_range_context,
    build_timeframe_inventory,
    structure_state,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (
    TICK_FLOOR,
    aligned_close,
    canonical_hash,
    complete_rows,
    iso,
    macro_state,
    parse_dt,
)

Direction = Literal["LONG", "SHORT"]

RULESET = "GOLD_SWING_CURVATURE_ENTRY_SEMANTIC_RECOVERY_V1"
SESSION = "NEW_YORK"
FIB_NEAR = 0.705
FIB_MID = 0.788
FIB_INVALIDATION = 0.886
TURN_EXPIRY_M5_BARS = 3
RETEST_EXPIRY_M5_BARS = 3
FORBIDDEN_OUTPUT_KEYS = {
    "outcome", "result", "resolution", "pnl", "net_r", "mfe", "mae",
    "win_rate", "profit_factor", "return",
}


def curvature_zone(
    pivot_candle: Mapping[str, Any], direction: Direction
) -> dict[str, float]:
    """Directional half of the exact range-boundary M15 candle."""
    low = float(pivot_candle["low"])
    high = float(pivot_candle["high"])
    if high < low:
        raise ValueError("Pivot candle high is below low")
    midpoint = (low + high) / 2.0
    lower, upper = (low, midpoint) if direction == "LONG" else (midpoint, high)
    return {
        "lower": lower,
        "upper": upper,
        "midpoint": midpoint,
        "invalidation": low if direction == "LONG" else high,
    }


def retracement_zone(
    origin_level: float, terminal_level: float, direction: Direction
) -> dict[str, float]:
    """Exact 0.705-0.886 retracement band of a completed impulse."""
    origin = float(origin_level)
    terminal = float(terminal_level)
    if direction == "LONG":
        if terminal <= origin:
            raise ValueError("LONG impulse terminal must be above its origin")
        span = terminal - origin
        near = terminal - FIB_NEAR * span
        midpoint = terminal - FIB_MID * span
        invalidation = terminal - FIB_INVALIDATION * span
        lower, upper = invalidation, near
    else:
        if terminal >= origin:
            raise ValueError("SHORT impulse terminal must be below its origin")
        span = origin - terminal
        near = terminal + FIB_NEAR * span
        midpoint = terminal + FIB_MID * span
        invalidation = terminal + FIB_INVALIDATION * span
        lower, upper = near, invalidation
    return {
        "lower": lower,
        "upper": upper,
        "midpoint": midpoint,
        "near_0p705": near,
        "mid_0p788": midpoint,
        "invalidation_0p886": invalidation,
        "invalidation": invalidation,
    }


def overlaps_zone(row: Mapping[str, Any], zone: Mapping[str, float]) -> bool:
    return float(row["high"]) >= float(zone["lower"]) and float(row["low"]) <= float(zone["upper"])


def directional_half_close(row: Mapping[str, Any], direction: Direction) -> bool:
    """Require an aligned candle closing in its directional range half."""
    midpoint = (float(row["low"]) + float(row["high"])) / 2.0
    if direction == "LONG":
        return aligned_close(dict(row), direction) and float(row["close"]) >= midpoint
    return aligned_close(dict(row), direction) and float(row["close"]) <= midpoint


def pivot_consumed(
    minute_rows: Sequence[dict[str, Any]], pivot: Mapping[str, Any], cutoff: str
) -> bool:
    """Strict traded-price consumption; equality is only engagement."""
    kind = str(pivot["kind"])
    if kind not in {"HIGH", "LOW"}:
        raise ValueError(f"Unsupported pivot kind: {kind}")
    level = float(pivot["level"])
    origin_complete = parse_dt(pivot.get("pivot_candle_completed_at", pivot.get("detected_at")))
    for row in complete_rows(minute_rows, cutoff):
        if parse_dt(row["available_at"]) <= origin_complete:
            continue
        if kind == "HIGH" and float(row["high"]) > level:
            return True
        if kind == "LOW" and float(row["low"]) < level:
            return True
    return False


def pivot_engaged(
    minute_rows: Sequence[dict[str, Any]], pivot: Mapping[str, Any], cutoff: str
) -> bool:
    kind = str(pivot["kind"])
    level = float(pivot["level"])
    origin_complete = parse_dt(pivot.get("pivot_candle_completed_at", pivot.get("detected_at")))
    for row in complete_rows(minute_rows, cutoff):
        if parse_dt(row["available_at"]) <= origin_complete:
            continue
        traded = float(row["high"] if kind == "HIGH" else row["low"])
        if (kind == "HIGH" and traded >= level) or (kind == "LOW" and traded <= level):
            return True
    return False


def _pivot_candle(
    rows: Sequence[dict[str, Any]], pivot: Mapping[str, Any], cutoff: str
) -> dict[str, Any]:
    matches = [
        row for row in complete_rows(rows, cutoff)
        if iso(row["open_at"]) == iso(pivot["pivot_at"])
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Pivot candle not uniquely resolved: {pivot['identity']}")
    return matches[0]


def _known_inventory_states(
    stream: Mapping[str, Any], timeframe: str, cutoff: str
) -> list[dict[str, Any]]:
    key = {"M15": "15m", "H1": "1h", "H4": "4h"}[timeframe]
    inventory = build_timeframe_inventory(stream["timeframes"][key], cutoff, timeframe)
    return [
        item for item in inventory["states"]
        if item["state"] != "UNKNOWN_TECHNICAL"
        and parse_dt(item["known_at"]) <= parse_dt(cutoff)
    ]


def _latest_known_impulse(
    stream: Mapping[str, Any], *, cutoff: str, direction: Direction,
    inventory: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Resolve the latest fully known M15 origin-terminal impulse pair."""
    origin_kind = "LOW" if direction == "LONG" else "HIGH"
    terminal_kind = "HIGH" if direction == "LONG" else "LOW"
    states = [
        dict(item) for item in inventory["states"]
        if item["state"] != "UNKNOWN_TECHNICAL"
        and parse_dt(item["known_at"]) <= parse_dt(cutoff)
    ]
    terminals = sorted(
        [item for item in states if item["kind"] == terminal_kind],
        key=lambda item: (parse_dt(item["pivot_at"]), parse_dt(item["known_at"]), item["identity"]),
        reverse=True,
    )
    for terminal in terminals:
        origins = [
            item for item in states
            if item["kind"] == origin_kind
            and parse_dt(item["pivot_at"]) < parse_dt(terminal["pivot_at"])
        ]
        if not origins:
            continue
        origin = max(
            origins,
            key=lambda item: (parse_dt(item["pivot_at"]), parse_dt(item["known_at"]), item["identity"]),
        )
        valid = (
            float(terminal["level"]) > float(origin["level"])
            if direction == "LONG"
            else float(terminal["level"]) < float(origin["level"])
        )
        if not valid:
            continue
        if pivot_consumed(stream["timeframes"]["1m"], origin, cutoff):
            continue
        if pivot_consumed(stream["timeframes"]["1m"], terminal, cutoff):
            continue
        zone = retracement_zone(float(origin["level"]), float(terminal["level"]), direction)
        known_at = max((origin["known_at"], terminal["known_at"]), key=parse_dt)
        return {
            "origin": origin,
            "terminal": terminal,
            "zone": zone,
            "known_at": known_at,
            "location_identity": canonical_hash(
                ["M15_IMPULSE_CURVATURE", direction, origin["identity"], terminal["identity"]]
            ),
        }
    return None


def _strict_location_breach(
    minute_rows: Sequence[dict[str, Any]], *, direction: Direction,
    location_known_at: str, cutoff: str, invalidation: float,
) -> bool:
    for row in complete_rows(minute_rows, cutoff):
        if parse_dt(row["available_at"]) <= parse_dt(location_known_at):
            continue
        if direction == "LONG" and float(row["low"]) < invalidation:
            return True
        if direction == "SHORT" and float(row["high"]) > invalidation:
            return True
    return False


def governing_contexts(
    stream: Mapping[str, Any], *, cutoff: str, price: float
) -> list[dict[str, Any]]:
    """Classify one point-in-time M15 auction without later paths."""
    rows = stream["timeframes"]["15m"]
    inventory = build_timeframe_inventory(rows, cutoff, "M15")
    trend = structure_state(inventory)
    state = str(trend["state"])

    if state in {"UPTREND", "DOWNTREND"}:
        direction: Direction = "LONG" if state == "UPTREND" else "SHORT"
        impulse = _latest_known_impulse(
            stream, cutoff=cutoff, direction=direction, inventory=inventory
        )
        if impulse is None:
            return []
        zone = dict(impulse["zone"])
        if _strict_location_breach(
            stream["timeframes"]["1m"], direction=direction,
            location_known_at=str(impulse["known_at"]), cutoff=cutoff,
            invalidation=float(zone["invalidation"]),
        ):
            return []
        return [{
            "direction": direction,
            "governing_state": f"TREND_{direction}",
            "controlling_swing": impulse["origin"],
            "terminal_swing": impulse["terminal"],
            "range_identity": None,
            "swing_relations": trend["relations"],
            "location_zone": zone,
            "location_known_at": impulse["known_at"],
            "location_identity": impulse["location_identity"],
            "location_construction": "M15_IMPULSE_FIB_0P705_TO_0P886",
        }]

    # A range is considered only when M15 relations do not establish a trend.
    range_long = active_range_context(
        rows, cutoff=cutoff, timeframe="M15", direction="LONG",
        price=price, inventory=inventory,
    )
    range_short = active_range_context(
        rows, cutoff=cutoff, timeframe="M15", direction="SHORT",
        price=price, inventory=inventory,
    )
    range_context: Mapping[str, Any]
    direction = "LONG"
    if range_long["state"] == "ACTIVE_RANGE" and price < float(range_long["midpoint"]):
        range_context = range_long
        pivot = dict(range_long["lower_boundary"])
    elif range_short["state"] == "ACTIVE_RANGE" and price > float(range_short["midpoint"]):
        range_context = range_short
        direction = "SHORT"
        pivot = dict(range_short["upper_boundary"])
    else:
        return []
    if pivot_consumed(stream["timeframes"]["1m"], pivot, cutoff):
        return []
    pivot_candle = _pivot_candle(rows, pivot, cutoff)
    zone = curvature_zone(pivot_candle, direction)
    known_at = str(range_context["known_at"])
    if _strict_location_breach(
        stream["timeframes"]["1m"], direction=direction,
        location_known_at=known_at, cutoff=cutoff,
        invalidation=float(zone["invalidation"]),
    ):
        return []
    return [{
        "direction": direction,
        "governing_state": f"RANGE_{direction}",
        "controlling_swing": pivot,
        "terminal_swing": None,
        "range_identity": range_context["range_identity"],
        "swing_relations": trend["relations"],
        "location_zone": zone,
        "location_known_at": known_at,
        "location_identity": canonical_hash(
            ["M15_RANGE_CURVATURE", direction, range_context["range_identity"], pivot["identity"]]
        ),
        "location_construction": "DIRECTIONAL_HALF_OF_EXACT_M15_RANGE_BOUNDARY_CANDLE",
    }]


def destination_at(
    stream: Mapping[str, Any], *, cutoff: str, direction: Direction, entry: float,
) -> dict[str, Any] | None:
    wanted = "HIGH" if direction == "LONG" else "LOW"
    candidates: list[dict[str, Any]] = []
    for timeframe in ("M15", "H1"):
        for item in _known_inventory_states(stream, timeframe, cutoff):
            level = float(item["level"])
            beyond = level > entry if direction == "LONG" else level < entry
            if (
                item["kind"] == wanted and beyond
                and not pivot_consumed(stream["timeframes"]["1m"], item, cutoff)
            ):
                candidates.append({**item, "timeframe": timeframe})
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda item: (
            abs(float(item["level"]) - entry), parse_dt(item["known_at"]), item["identity"]
        ),
    )
    return {
        "identity": str(selected["identity"]),
        "timeframe": str(selected["timeframe"]),
        "kind": str(selected["kind"]),
        "pivot_at": iso(selected["pivot_at"]),
        "known_at": iso(selected["known_at"]),
        "level": float(selected["level"]),
        "liquidity_state_at_plan": (
            "UNCONSUMED_ENGAGED"
            if pivot_engaged(stream["timeframes"]["1m"], selected, cutoff)
            else "UNCONSUMED_UNTOUCHED"
        ),
        "epistemic_status": "CALCULATED_OPPOSING_AUCTION_REFERENCE",
    }


def first_confirmed_retest(
    m5_rows: Sequence[dict[str, Any]], *, direction: Direction,
    turn_bar: Mapping[str, Any], zone: Mapping[str, float],
    session_end: str, controlling_swing: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Evaluate the first adverse M5 retest only; never try a later attempt."""
    turn_available = parse_dt(turn_bar["available_at"])
    later = [
        row for row in complete_rows(m5_rows, session_end)
        if parse_dt(row["available_at"]) > turn_available
    ][:RETEST_EXPIRY_M5_BARS]
    body_low = min(float(turn_bar["open"]), float(turn_bar["close"]))
    body_high = max(float(turn_bar["open"]), float(turn_bar["close"]))
    control_level = float(controlling_swing["level"])
    for row in later:
        location_breached = (
            float(row["low"]) < float(zone["invalidation"])
            if direction == "LONG" else float(row["high"]) > float(zone["invalidation"])
        )
        control_consumed = (
            float(row["low"]) < control_level
            if direction == "LONG" else float(row["high"]) > control_level
        )
        if location_breached or control_consumed:
            return None
        body_overlap = float(row["high"]) >= body_low and float(row["low"]) <= body_high
        if not (body_overlap or overlaps_zone(row, zone)):
            continue
        better_extreme = (
            float(row["low"]) > float(turn_bar["low"])
            if direction == "LONG" else float(row["high"]) < float(turn_bar["high"])
        )
        if not better_extreme or not directional_half_close(row, direction):
            return None
        identity = canonical_hash([
            "M5_FIRST_RETEST_FLIP", direction, iso(turn_bar["open_at"]),
            iso(row["open_at"]), float(row["close"]),
        ])
        return {
            "identity": identity,
            "bar": dict(row),
            "known_at": iso(row["available_at"]),
            "better_extreme": True,
            "aligned_directional_half_close": True,
        }
    return None


def _environment_at(
    stream: Mapping[str, Any], cutoff: str, direction: Direction
) -> dict[str, Any]:
    structures: dict[str, Any] = {}
    for timeframe, key in (("H1", "1h"), ("H4", "4h")):
        inventory = build_timeframe_inventory(stream["timeframes"][key], cutoff, timeframe)
        structures[timeframe] = structure_state(inventory)
    return {
        "macro": macro_state(dict(stream), cutoff, direction),
        "higher_timeframe_structure": structures,
        "session": SESSION,
        "role": "POINT_IN_TIME_CONTEXT_NOT_ENTRY_TRIGGER",
        "gex": "UNKNOWN_NOT_IN_SEALED_SOURCE",
        "volume_profile_value_area": "UNKNOWN_NOT_IN_SEALED_SOURCE",
        "observed_gc_order_flow": "UNKNOWN_FOR_BASE_XAUUSD_SEMANTIC_REVIEW",
    }


def _candidate_from_engagement(
    stream: Mapping[str, Any], *, context: Mapping[str, Any],
    engagement_bar: Mapping[str, Any], session_end: str,
) -> dict[str, Any] | None:
    direction: Direction = str(context["direction"])  # type: ignore[assignment]
    pivot = dict(context["controlling_swing"])
    terminal = dict(context["terminal_swing"]) if context.get("terminal_swing") else None
    zone = dict(context["location_zone"])
    engagement_at = iso(engagement_bar["available_at"])
    m5_rows = complete_rows(stream["timeframes"]["5m"], session_end)
    engagement_index = next((
        index for index, row in enumerate(m5_rows)
        if iso(row["open_at"]) == iso(engagement_bar["open_at"])
        and iso(row["available_at"]) == engagement_at
    ), None)
    if engagement_index is None:
        raise RuntimeError("Engagement candle is absent from the M5 stream")

    turn_bar: dict[str, Any] | None = None
    for row in m5_rows[engagement_index:engagement_index + TURN_EXPIRY_M5_BARS]:
        cutoff = iso(row["available_at"])
        if pivot_consumed(stream["timeframes"]["1m"], pivot, cutoff):
            return None
        if _strict_location_breach(
            stream["timeframes"]["1m"], direction=direction,
            location_known_at=str(context["location_known_at"]), cutoff=cutoff,
            invalidation=float(zone["invalidation"]),
        ):
            return None
        if overlaps_zone(row, zone) and directional_half_close(row, direction):
            turn_bar = row
            break
    if turn_bar is None:
        return None

    retest = first_confirmed_retest(
        m5_rows, direction=direction, turn_bar=turn_bar, zone=zone,
        session_end=session_end, controlling_swing=pivot,
    )
    if retest is None:
        return None
    retest_bar = dict(retest["bar"])
    decision_at = str(retest["known_at"])
    if pivot_consumed(stream["timeframes"]["1m"], pivot, decision_at):
        return None
    if _strict_location_breach(
        stream["timeframes"]["1m"], direction=direction,
        location_known_at=str(context["location_known_at"]), cutoff=decision_at,
        invalidation=float(zone["invalidation"]),
    ):
        return None

    entry = float(retest_bar["close"])
    stop = (
        min(float(turn_bar["low"]), float(retest_bar["low"])) - TICK_FLOOR
        if direction == "LONG"
        else max(float(turn_bar["high"]), float(retest_bar["high"])) + TICK_FLOOR
    )
    destination = destination_at(stream, cutoff=decision_at, direction=direction, entry=entry)
    if destination is None:
        return None
    target = float(destination["level"])
    if not (stop < entry < target if direction == "LONG" else target < entry < stop):
        return None

    retest_identity = str(retest["identity"])
    turn_pivot_identity = canonical_hash([
        "M5_CONFIRMED_TURN_EXTREME", direction, iso(turn_bar["open_at"]),
        float(turn_bar["low"] if direction == "LONG" else turn_bar["high"]),
        retest_identity,
    ])
    curvature: dict[str, Any] = {
        "identity": str(context["location_identity"]),
        "engagement_bar_open_at": iso(engagement_bar["open_at"]),
        "engagement_at": engagement_at,
        "known_at": iso(context["location_known_at"]),
        "zone_lower": float(zone["lower"]),
        "zone_upper": float(zone["upper"]),
        "zone_midpoint": float(zone["midpoint"]),
        "location_invalidation": float(zone["invalidation"]),
        "construction": str(context["location_construction"]),
    }
    if terminal:
        curvature.update({
            "fib_0p705": float(zone["near_0p705"]),
            "fib_0p788": float(zone["mid_0p788"]),
            "fib_0p886": float(zone["invalidation_0p886"]),
            "impulse_origin_level": float(pivot["level"]),
            "impulse_terminal_level": float(terminal["level"]),
        })
    else:
        pivot_candle = _pivot_candle(stream["timeframes"]["15m"], pivot, decision_at)
        curvature["pivot_candle_open_at"] = iso(pivot_candle["open_at"])

    payload: dict[str, Any] = {
        "ruleset": RULESET,
        "case_alias": str(stream["case_alias"]),
        "trading_date_utc": str(stream["trading_date_utc"]),
        "session": SESSION,
        "decision_at": decision_at,
        "direction": direction,
        "governing_auction": {
            "state": str(context["governing_state"]),
            "range_identity": context.get("range_identity"),
            "swing_relations": context.get("swing_relations"),
            "terminal_swing": ({
                "identity": str(terminal["identity"]),
                "kind": str(terminal["kind"]),
                "pivot_at": iso(terminal["pivot_at"]),
                "known_at": iso(terminal["known_at"]),
                "level": float(terminal["level"]),
            } if terminal else None),
            "epistemic_status": "INFERRED_FROM_COMPLETED_M15_STRUCTURE",
        },
        "controlling_swing": {
            "identity": str(pivot["identity"]),
            "kind": str(pivot["kind"]),
            "timeframe": "M15",
            "pivot_at": iso(pivot["pivot_at"]),
            "known_at": iso(pivot["known_at"]),
            "level": float(pivot["level"]),
            "state_at_decision": "UNCONSUMED_ENGAGED",
            "epistemic_status": "CALCULATED",
        },
        "curvature": curvature,
        "m5_turn": {
            "turn_candle_identity": canonical_hash([
                "M5_TURN_CANDLE", direction, iso(turn_bar["open_at"]),
                iso(turn_bar["available_at"]), float(turn_bar["open"]),
                float(turn_bar["high"]), float(turn_bar["low"]), float(turn_bar["close"]),
            ]),
            "turn_pivot_identity": turn_pivot_identity,
            "turn_candle_open_at": iso(turn_bar["open_at"]),
            "turn_at": iso(turn_bar["available_at"]),
            "turn_extreme": float(turn_bar["low"] if direction == "LONG" else turn_bar["high"]),
            "directional_half_close": True,
            "overlaps_curvature": True,
            "expiry_m5_bars": TURN_EXPIRY_M5_BARS,
            "price_response_status": "CALCULATED_PRICE_RESPONSE_NOT_OBSERVED_ABSORPTION",
        },
        "retest": {
            "identity": retest_identity,
            "bar_open_at": iso(retest_bar["open_at"]),
            "known_at": decision_at,
            "extreme": float(retest_bar["low"] if direction == "LONG" else retest_bar["high"]),
            "selection": "FIRST_ADVERSE_M5_RETOUCH_ONLY",
            "better_extreme_than_turn": True,
            "aligned_flip_close": True,
            "expiry_m5_bars": RETEST_EXPIRY_M5_BARS,
        },
        "entry": {
            "order_type": "MARKET_REFERENCE_AT_COMPLETED_M5_RETEST_FLIP",
            "level": entry,
            "activated_at": decision_at,
        },
        "invalidation": {
            "level": stop,
            "source": "LOWER_OR_HIGHER_OF_M5_TURN_AND_RETEST_PLUS_ONE_MINIMUM_TICK",
            "known_at": decision_at,
        },
        "destination": destination,
        "environment": _environment_at(stream, decision_at, direction),
        "epistemic_status": {
            "ohlc_and_timestamps": "OBSERVED",
            "structure_location_turn_retest": "CALCULATED",
            "governing_auction_and_liquidity_role": "INFERRED",
            "resting_orders_and_institutional_motive": "UNKNOWN",
        },
        "source_stream_sha256": str(stream["stream_sha256"]),
    }
    payload["candidate_identity"] = canonical_hash([
        RULESET, payload["case_alias"], decision_at, direction,
        context["location_identity"], turn_pivot_identity, retest_identity,
    ])
    assert_outcome_blind(payload)
    payload["candidate_sha256"] = canonical_hash(payload)
    return payload


def scan_stream(stream: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Emit complete semantic plans in one exposed New York session."""
    day = parse_dt(f"{stream['trading_date_utc']}T00:00:00Z").date()
    start_dt, end_dt = session_bounds(day, SESSION)
    end = iso(end_dt)
    m5_rows = [
        row for row in complete_rows(stream["timeframes"]["5m"], end)
        if start_dt < parse_dt(row["available_at"]) <= end_dt
    ]
    first_engagement: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for bar in m5_rows:
        cutoff = iso(bar["available_at"])
        for context in governing_contexts(stream, cutoff=cutoff, price=float(bar["close"])):
            key = str(context["location_identity"])
            if key in first_engagement:
                continue
            direction: Direction = str(context["direction"])  # type: ignore[assignment]
            zone = dict(context["location_zone"])
            pivot = dict(context["controlling_swing"])
            if (
                parse_dt(cutoff) >= parse_dt(context["location_known_at"])
                and overlaps_zone(bar, zone)
                and not pivot_consumed(stream["timeframes"]["1m"], pivot, cutoff)
                and not _strict_location_breach(
                    stream["timeframes"]["1m"], direction=direction,
                    location_known_at=str(context["location_known_at"]), cutoff=cutoff,
                    invalidation=float(zone["invalidation"]),
                )
            ):
                first_engagement[key] = (dict(context), bar)

    candidates: list[dict[str, Any]] = []
    used_controls: set[tuple[str, str]] = set()
    ordered = sorted(
        first_engagement.items(),
        key=lambda item: (
            parse_dt(item[1][1]["available_at"]), item[1][0]["direction"], item[0]
        ),
    )
    for _, (context, engagement) in ordered:
        control_key = (
            str(context["direction"]), str(context["controlling_swing"]["identity"])
        )
        if control_key in used_controls:
            continue
        used_controls.add(control_key)
        candidate = _candidate_from_engagement(
            stream, context=context, engagement_bar=engagement, session_end=end
        )
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda item: (
        parse_dt(item["decision_at"]), item["direction"], item["candidate_identity"]
    ))
    if len({item["candidate_identity"] for item in candidates}) != len(candidates):
        raise RuntimeError(f"Duplicate candidate in {stream['case_alias']}")
    for item in candidates:
        assert_outcome_blind(item)
    return candidates


def assert_outcome_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_OUTPUT_KEYS:
                raise RuntimeError(f"Forbidden outcome field at {path}.{key}")
            assert_outcome_blind(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            assert_outcome_blind(child, f"{path}[{index}]")


def synthetic_proof() -> dict[str, Any]:
    long_zone = retracement_zone(100.0, 110.0, "LONG")
    short_zone = retracement_zone(110.0, 100.0, "SHORT")
    pivot_low = {
        "identity": "LOW", "kind": "LOW", "level": 100.0,
        "detected_at": "2022-01-01T00:05:00Z",
        "pivot_candle_completed_at": "2022-01-01T00:01:00Z",
    }
    equal_row = {
        "open_at": "2022-01-01T00:05:00Z", "available_at": "2022-01-01T00:06:00Z",
        "open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "complete": True,
    }
    beyond_row = {**equal_row, "low": 99.99}
    turn = {
        "open_at": "2022-01-01T00:10:00Z", "available_at": "2022-01-01T00:15:00Z",
        "open": 101.20, "high": 101.90, "low": 101.00, "close": 101.70, "complete": True,
    }
    failed_first = {
        "open_at": "2022-01-01T00:15:00Z", "available_at": "2022-01-01T00:20:00Z",
        "open": 101.65, "high": 101.80, "low": 100.95, "close": 101.60, "complete": True,
    }
    passing_later = {
        "open_at": "2022-01-01T00:20:00Z", "available_at": "2022-01-01T00:25:00Z",
        "open": 101.55, "high": 102.10, "low": 101.30, "close": 102.00, "complete": True,
    }
    passing_first = {**failed_first, "low": 101.10, "close": 101.75}
    retest = first_confirmed_retest(
        [turn, passing_first, passing_later], direction="LONG", turn_bar=turn,
        zone={"lower": 100.9, "upper": 102.0, "invalidation": 100.5},
        session_end="2022-01-01T01:00:00Z", controlling_swing=pivot_low,
    )
    no_later = first_confirmed_retest(
        [turn, failed_first, passing_later], direction="LONG", turn_bar=turn,
        zone={"lower": 100.9, "upper": 102.0, "invalidation": 100.5},
        session_end="2022-01-01T01:00:00Z", controlling_swing=pivot_low,
    )
    checks = {
        "trend_fib_zone_is_exact_and_symmetric": (
            round(long_zone["lower"], 6) == 101.14
            and round(long_zone["upper"], 6) == 102.95
            and round(short_zone["lower"], 6) == 107.05
            and round(short_zone["upper"], 6) == 108.86
        ),
        "equality_is_engagement_not_consumption": (
            not pivot_consumed([equal_row], pivot_low, "2022-01-01T00:06:00Z")
            and pivot_engaged([equal_row], pivot_low, "2022-01-01T00:06:00Z")
        ),
        "strict_beyond_consumes": pivot_consumed(
            [beyond_row], pivot_low, "2022-01-01T00:06:00Z"
        ),
        "directional_half_turn_is_observable": directional_half_close(turn, "LONG"),
        "first_valid_retest_is_selected": (
            retest is not None and retest["bar"]["open_at"] == "2022-01-01T00:15:00Z"
        ),
        "failed_first_retest_cannot_be_repaired_by_later_bar": no_later is None,
        "outcome_guard_accepts_plan_fields": True,
    }
    assert_outcome_blind({"entry": 101.75, "invalidation": 100.98, "destination": 103.0})
    try:
        assert_outcome_blind({"pnl": 1.0})
    except RuntimeError:
        checks["outcome_guard_rejects_performance"] = True
    else:
        checks["outcome_guard_rejects_performance"] = False
    if not all(checks.values()):
        raise RuntimeError(f"Synthetic semantic proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}
