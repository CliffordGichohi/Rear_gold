"""Outcome-blind, direction-symmetric M5/M15 auction-transition scanner.

The scanner emits every causal New York control event rather than routing one
pre-filtered candidate per day.  Planning functions deliberately have no
outcome, trade-result, PnL, MFE, or MAE input.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from gold_intel.analytics.auction_control_router_v1 import (
    active_control_event,
    control_observations,
    session_bounds,
    strong_breaks,
    sweep_reclaims,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (
    TICK_FLOOR,
    canonical_hash,
    complete_rows,
    confirmed_swings,
    iso,
    macro_state,
    parse_dt,
    structural_breaks,
    swing_relations,
    true_ranges_and_atr,
)

Direction = Literal["LONG", "SHORT"]
TransitionClass = Literal[
    "INITIAL_CONTROL",
    "REVERSAL_TRANSFER",
    "CONTROL_REASSERTION",
    "CONTINUATION_REFRESH",
]

RULESET = "GOLD_ALL_TRANSITION_AUCTION_SCANNER_SEMANTIC_REVIEW_V1"
SESSION = "NEW_YORK"
TIMEFRAME_KEYS: Mapping[str, str] = {
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "H4": "4h",
}
FORBIDDEN_OUTPUT_KEYS = {
    "outcome",
    "result",
    "resolution",
    "pnl",
    "net_r",
    "mfe",
    "mae",
    "future",
    "win_rate",
    "profit_factor",
}


def direction_from_state(state: str) -> Direction | None:
    if state == "BUYER_CONTROL":
        return "LONG"
    if state == "SELLER_CONTROL":
        return "SHORT"
    return None


def _event_identity(event: dict[str, Any] | None) -> str | None:
    return None if event is None else str(event["identity"])


def _pair_identity(observation: dict[str, Any]) -> tuple[str | None, str | None]:
    return (
        _event_identity(observation.get("m5_event")),
        _event_identity(observation.get("m15_event")),
    )


def _new_break_timeframes(
    previous: dict[str, Any] | None, current: dict[str, Any]
) -> list[str]:
    if previous is None:
        return []
    decision_at = parse_dt(current["at"])
    output: list[str] = []
    for timeframe, key in (("M5", "m5_event"), ("M15", "m15_event")):
        before = previous.get(key)
        after = current.get(key)
        if after is None or _event_identity(before) == _event_identity(after):
            continue
        # A fallback to an older surviving event after invalidation is not a
        # fresh continuation event.  A new event must become knowable at this
        # completed-candle checkpoint.
        if parse_dt(after["break_at"]) == decision_at:
            output.append(timeframe)
    return output


def enumerate_transition_observations(
    observations: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit causal accepted-control events without a daily-count limit."""

    emitted: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    last_directional: Direction | None = None
    for observation in observations:
        direction = direction_from_state(str(observation["state"]))
        if direction is None:
            previous = observation
            continue

        prior_direction = (
            None if previous is None else direction_from_state(str(previous["state"]))
        )
        event_class: TransitionClass | None = None
        new_timeframes: list[str] = []
        if prior_direction is None:
            if last_directional is None:
                event_class = "INITIAL_CONTROL"
            elif last_directional != direction:
                event_class = "REVERSAL_TRANSFER"
            else:
                event_class = "CONTROL_REASSERTION"
        elif prior_direction != direction:
            event_class = "REVERSAL_TRANSFER"
        elif _pair_identity(previous) != _pair_identity(observation):
            new_timeframes = _new_break_timeframes(previous, observation)
            if new_timeframes:
                event_class = "CONTINUATION_REFRESH"

        if event_class is not None:
            payload = {
                "decision_at": iso(observation["at"]),
                "direction": direction,
                "event_class": event_class,
                "new_break_timeframes": new_timeframes,
                "active_m5_identity": _event_identity(observation.get("m5_event")),
                "active_m15_identity": _event_identity(observation.get("m15_event")),
                "source_observation_identity": canonical_hash(
                    {
                        "at": iso(observation["at"]),
                        "raw_state": str(observation["raw_state"]),
                        "state": str(observation["state"]),
                        "active_m5_identity": _event_identity(
                            observation.get("m5_event")
                        ),
                        "active_m15_identity": _event_identity(
                            observation.get("m15_event")
                        ),
                    }
                ),
                "_m5_event": observation.get("m5_event"),
                "_m15_event": observation.get("m15_event"),
            }
            emitted.append(payload)
        last_directional = direction
        previous = observation
    return emitted


def _sanitized_break(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "identity": str(event["identity"]),
        "timeframe": str(event["timeframe"]),
        "direction": str(event["direction"]),
        "break_at": iso(event["break_at"]),
        "broken_level": float(event["broken_level"]),
        "broken_identity": str(event["broken_identity"]),
        "protected_level": float(event["protected_level"]),
        "protected_identity": str(event["protected_identity"]),
        "origin_at": iso(event["origin_at"]),
        "origin_adverse": float(event["origin_adverse"]),
        "atr": float(event["atr"]),
        "range_atr": float(event["range_atr"]),
        "body_ratio": float(event["body_ratio"]),
        "buffer": float(event["buffer"]),
        "epistemic_status": "INFERRED_AUCTION_REFERENCE_CONSUMED",
    }


def _last_completed_price(stream: dict[str, Any], cutoff: str) -> float:
    bars = complete_rows(stream["timeframes"]["5m"], cutoff)
    if not bars:
        raise RuntimeError(f"No completed M5 bar at {cutoff}")
    return float(bars[-1]["close"])


def build_semantic_cache(stream: dict[str, Any]) -> dict[str, Any]:
    """Precompute causal objects once; callers still filter by known timestamp."""

    cutoff = str(stream["end_exclusive"])
    timeframes: dict[str, dict[str, Any]] = {}
    for timeframe, key in TIMEFRAME_KEYS.items():
        bars, swings = confirmed_swings(stream["timeframes"][key], cutoff, timeframe)
        _, atrs = true_ranges_and_atr(bars)
        timeframes[timeframe] = {"bars": bars, "swings": swings, "atrs": atrs}
    m5_events = strong_breaks(stream["timeframes"]["5m"], cutoff, "M5")
    m15_events = strong_breaks(stream["timeframes"]["15m"], cutoff, "M15")
    return {
        "timeframes": timeframes,
        "breaks": {
            "M5": m5_events,
            "M15": m15_events,
            "H1": [
                *structural_breaks(stream["timeframes"]["1h"], cutoff, "H1", "LONG"),
                *structural_breaks(stream["timeframes"]["1h"], cutoff, "H1", "SHORT"),
            ],
            "H4": [
                *structural_breaks(stream["timeframes"]["4h"], cutoff, "H4", "LONG"),
                *structural_breaks(stream["timeframes"]["4h"], cutoff, "H4", "SHORT"),
            ],
        },
        "m5_events": m5_events,
        "m15_events": m15_events,
        "sweeps": sweep_reclaims(stream["timeframes"]["5m"], cutoff),
    }


def _atr_at(rows: Sequence[dict[str, Any]], cutoff: str) -> float | None:
    bars = complete_rows(rows, cutoff)
    if not bars:
        return None
    _, atrs = true_ranges_and_atr(bars)
    value = atrs[-1]
    return None if value is None or value <= 0 else float(value)


def _breaks_for_destination(
    rows: Sequence[dict[str, Any]], cutoff: str, timeframe: str, direction: Direction
) -> list[dict[str, Any]]:
    if timeframe == "M5":
        return strong_breaks(rows, cutoff, "M5")
    if timeframe == "M15":
        return strong_breaks(rows, cutoff, "M15")
    return structural_breaks(rows, cutoff, timeframe, direction)


def known_liquidity_destinations(
    stream: dict[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    price: float,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return nearest known, still-unbroken opposing swing per timeframe."""

    desired_kind = "HIGH" if direction == "LONG" else "LOW"
    output: dict[str, dict[str, Any] | None] = {}
    semantic = cache if cache is not None else build_semantic_cache(stream)
    for timeframe in TIMEFRAME_KEYS:
        swings = [
            item
            for item in semantic["timeframes"][timeframe]["swings"]
            if parse_dt(item["detected_at"]) <= parse_dt(cutoff)
        ]
        broken = {
            str(item["broken_identity"])
            for item in semantic["breaks"][timeframe]
            if item["direction"] == direction
            and parse_dt(item["break_at"]) <= parse_dt(cutoff)
        }
        candidates = [
            swing
            for swing in swings
            if swing["kind"] == desired_kind
            and str(swing["identity"]) not in broken
            and (
                float(swing["level"]) > price + TICK_FLOOR
                if direction == "LONG"
                else float(swing["level"]) < price - TICK_FLOOR
            )
        ]
        if not candidates:
            output[timeframe] = None
            continue
        nearest = min(candidates, key=lambda item: abs(float(item["level"]) - price))
        output[timeframe] = {
            "identity": str(nearest["identity"]),
            "timeframe": timeframe,
            "kind": str(nearest["kind"]),
            "level": float(nearest["level"]),
            "known_at": iso(nearest["detected_at"]),
            "distance_price": abs(float(nearest["level"]) - price),
            "epistemic_status": "INFERRED_UNCONSUMED_LIQUIDITY_DESTINATION",
        }
    local = [output[key] for key in ("M5", "M15") if output[key] is not None]
    higher = [output[key] for key in ("H1", "H4") if output[key] is not None]
    return {
        "by_timeframe": output,
        "nearest_local": min(local, key=lambda item: item["distance_price"]) if local else None,
        "nearest_higher_timeframe": (
            min(higher, key=lambda item: item["distance_price"]) if higher else None
        ),
    }


def timeframe_context(
    stream: dict[str, Any],
    *,
    cutoff: str,
    timeframe: str,
    price: float,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic = cache if cache is not None else build_semantic_cache(stream)
    cached = semantic["timeframes"][timeframe]
    rows = [
        item for item in cached["bars"] if parse_dt(item["available_at"]) <= parse_dt(cutoff)
    ]
    swings = [
        item
        for item in cached["swings"]
        if parse_dt(item["detected_at"]) <= parse_dt(cutoff)
    ]
    known_highs = [item for item in swings if item["kind"] == "HIGH"]
    known_lows = [item for item in swings if item["kind"] == "LOW"]
    latest_high = known_highs[-1] if known_highs else None
    latest_low = known_lows[-1] if known_lows else None
    low = None if latest_low is None else float(latest_low["level"])
    high = None if latest_high is None else float(latest_high["level"])
    location = (
        (price - low) / (high - low)
        if low is not None and high is not None and high > low
        else None
    )
    return {
        "last_completed_at": iso(rows[-1]["available_at"]) if rows else None,
        "swing_relations": swing_relations(swings),
        "latest_high_identity": None if latest_high is None else latest_high["identity"],
        "latest_high_level": high,
        "latest_low_identity": None if latest_low is None else latest_low["identity"],
        "latest_low_level": low,
        "range_location": location,
        "atr": (
            None
            if not rows
            else cached["atrs"][len(rows) - 1]
        ),
        "epistemic_status": "CALCULATED_COMPLETED_CANDLES",
    }


def _sweep_context(
    sweeps: Sequence[dict[str, Any]],
    *,
    start: datetime,
    cutoff: str,
    direction: Direction,
) -> dict[str, Any]:
    point = parse_dt(cutoff)
    visible = [item for item in sweeps if start < parse_dt(item["at"]) <= point]
    aligned_kind = (
        "SELL_SIDE_SWEEP_RECLAIM" if direction == "LONG" else "BUY_SIDE_SWEEP_RECLAIM"
    )
    aligned = [item for item in visible if item["kind"] == aligned_kind]
    opposed = [item for item in visible if item["kind"] != aligned_kind]

    def sanitize(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "at": iso(item["at"]),
            "direction": str(item["direction"]),
            "kind": str(item["kind"]),
            "level": float(item["level"]),
            "swing_identity": str(item["swing_identity"]),
            "epistemic_status": "INFERRED_SWEEP_RECLAIM",
        }

    return {
        "latest_aligned": sanitize(aligned[-1] if aligned else None),
        "latest_opposed": sanitize(opposed[-1] if opposed else None),
        "visible_sweep_count": len(visible),
    }


def _assert_outcome_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_OUTPUT_KEYS:
                raise RuntimeError(f"Forbidden outcome field at {path}.{key}")
            if normalized == "invalidated_at":
                raise RuntimeError(f"Future invalidation metadata leaked at {path}.{key}")
            _assert_outcome_blind(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_outcome_blind(child, f"{path}[{index}]")


def scan_new_york_stream(stream: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate every accepted New York auction event in one sealed stream."""

    calendar_day = datetime.fromisoformat(str(stream["trading_date_utc"])).date()
    start, end = session_bounds(calendar_day, SESSION)
    semantic = build_semantic_cache(stream)
    m5_events = semantic["m5_events"]
    m15_events = semantic["m15_events"]
    observations = control_observations(
        m5_rows=stream["timeframes"]["5m"],
        m5_events=m5_events,
        m15_events=m15_events,
        start=start,
        end=end,
    )
    raw_events = enumerate_transition_observations(observations)
    sweeps = semantic["sweeps"]
    output: list[dict[str, Any]] = []
    for ordinal, raw in enumerate(raw_events, start=1):
        decision_at = str(raw["decision_at"])
        direction = raw["direction"]
        price = _last_completed_price(stream, decision_at)
        m5_break = _sanitized_break(raw.pop("_m5_event"))
        m15_break = _sanitized_break(raw.pop("_m15_event"))
        event: dict[str, Any] = {
            "ruleset": RULESET,
            "case_alias": str(stream["case_alias"]),
            "trading_date_utc": str(stream["trading_date_utc"]),
            "session": SESSION,
            "session_event_ordinal": ordinal,
            **raw,
            "decision_price": price,
            "active_breaks": {"M5": m5_break, "M15": m15_break},
            "higher_timeframe_context": {
                "H1": timeframe_context(
                    stream,
                    cutoff=decision_at,
                    timeframe="H1",
                    price=price,
                    cache=semantic,
                ),
                "H4": timeframe_context(
                    stream,
                    cutoff=decision_at,
                    timeframe="H4",
                    price=price,
                    cache=semantic,
                ),
            },
            "macro_context": macro_state(stream, decision_at, direction),
            "sweep_reclaim_context": _sweep_context(
                sweeps, start=start, cutoff=decision_at, direction=direction
            ),
            "liquidity_destinations": known_liquidity_destinations(
                stream,
                cutoff=decision_at,
                direction=direction,
                price=price,
                cache=semantic,
            ),
            "epistemic_status": {
                "completed_candles": "OBSERVED",
                "structure_and_location": "CALCULATED",
                "auction_control": "INFERRED",
                "consumed_and_unconsumed_liquidity": "INFERRED",
            },
            "source_stream_sha256": str(stream["stream_sha256"]),
        }
        event["event_identity"] = canonical_hash(
            {
                "case_alias": event["case_alias"],
                "decision_at": event["decision_at"],
                "direction": event["direction"],
                "event_class": event["event_class"],
                "active_m5_identity": event["active_m5_identity"],
                "active_m15_identity": event["active_m15_identity"],
            }
        )
        _assert_outcome_blind(event)
        event["event_sha256"] = canonical_hash(event)
        output.append(event)
    if len({item["event_identity"] for item in output}) != len(output):
        raise RuntimeError(f"Duplicate transition identity: {stream['case_alias']}")
    return output


def active_pair_at(
    *,
    m5_events: Sequence[dict[str, Any]],
    m15_events: Sequence[dict[str, Any]],
    at: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Small public helper used by independent integrity tests."""

    return active_control_event(m5_events, at), active_control_event(m15_events, at)
