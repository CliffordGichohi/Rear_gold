"""Mutually exclusive auction control and observable seller-auction routing.

The module deliberately separates point-in-time plan construction from path
simulation.  No outcome or result object is accepted by any planning function.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from gold_intel.analytics.coherent_auction_correction_v1 import (
    TICK_FLOOR,
    canonical_hash,
    complete_rows,
    confirmed_swings,
    iso,
    parse_dt,
    structural_breaks,
    true_ranges_and_atr,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (
    h4_context_metrics,
    macro_state,
)

Direction = Literal["LONG", "SHORT"]
ControlState = Literal[
    "BUYER_CONTROL", "SELLER_CONTROL", "CONFLICTED", "UNRESOLVED"
]

RULESET = "GOLD_AUCTION_CONTROL_ROUTER_JAN_JUN_2022_V1"
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")

PIVOT_BREAK_BUFFER_ATR = 0.05
M5_MINIMUM_RANGE_ATR = 0.80
M15_MINIMUM_RANGE_ATR = 0.90
MINIMUM_BODY_RATIO = 0.55
ACTIVE_INVALIDATION_BUFFER_ATR = 0.10
ACCEPTANCE_M5_CLOSES = 2
RETEST_TOLERANCE_ATR = 0.25
RETEST_EXPIRY_M5_BARS = 6
STOP_BUFFER_M15_ATR = 0.10
TARGET_ROOM_R_MINIMUM = 1.50
SLIPPAGE_USD_PER_OUNCE = 0.05
SPREAD_FALLBACK = 0.20
RISK_USD = 50.0


def spread_price(row: dict[str, Any]) -> float:
    value = row.get("spread_price")
    if value is None:
        return SPREAD_FALLBACK
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else SPREAD_FALLBACK


def session_bounds(calendar_day: date, session: str) -> tuple[datetime, datetime]:
    if session not in {"LONDON", "NEW_YORK"}:
        raise ValueError(f"Unsupported session: {session}")
    zone = LONDON if session == "LONDON" else NEW_YORK
    opened = datetime.combine(calendar_day, time(8), tzinfo=zone).astimezone(UTC)
    return opened, (opened + timedelta(hours=4)).astimezone(UTC)


def session_for_timestamp(value: str | datetime) -> str | None:
    point = parse_dt(value)
    london = point.astimezone(LONDON).time()
    new_york = point.astimezone(NEW_YORK).time()
    if time(8) <= london < time(12):
        return "LONDON"
    if time(8) <= new_york < time(12):
        return "NEW_YORK"
    return None


def _minimum_range(timeframe: str) -> float:
    if timeframe == "M5":
        return M5_MINIMUM_RANGE_ATR
    if timeframe == "M15":
        return M15_MINIMUM_RANGE_ATR
    raise ValueError(f"Unsupported control timeframe: {timeframe}")


def strong_breaks(
    rows: Sequence[dict[str, Any]], cutoff: str | datetime, timeframe: str
) -> list[dict[str, Any]]:
    """Return qualifying breaks with a point-in-time valid invalidation time."""

    output: list[dict[str, Any]] = []
    for direction in ("LONG", "SHORT"):
        output.extend(
            structural_breaks(
                rows,
                cutoff,
                timeframe,
                direction,
                buffer_atr=PIVOT_BREAK_BUFFER_ATR,
                minimum_range_atr=_minimum_range(timeframe),
                minimum_body_ratio=MINIMUM_BODY_RATIO,
            )
        )
    output.sort(
        key=lambda row: (
            parse_dt(row["break_at"]),
            str(row["direction"]),
            str(row["identity"]),
        )
    )
    bars = complete_rows(rows, cutoff)
    for event in output:
        invalidation_buffer = max(
            ACTIVE_INVALIDATION_BUFFER_ATR * float(event["atr"]), TICK_FLOOR
        )
        invalidated_at: str | None = None
        for bar in bars:
            if parse_dt(bar["available_at"]) <= parse_dt(event["break_at"]):
                continue
            invalid = (
                float(bar["close"])
                < float(event["protected_level"]) - invalidation_buffer
                if event["direction"] == "LONG"
                else float(bar["close"])
                > float(event["protected_level"]) + invalidation_buffer
            )
            if invalid:
                invalidated_at = iso(bar["available_at"])
                break
        event["invalidated_at"] = invalidated_at
        event["active_invalidation_buffer"] = invalidation_buffer
    return output


def active_control_event(
    events: Sequence[dict[str, Any]], cutoff: str | datetime
) -> dict[str, Any] | None:
    point = parse_dt(cutoff)
    eligible = [
        event
        for event in events
        if parse_dt(event["break_at"]) <= point
        and (
            event.get("invalidated_at") is None
            or point < parse_dt(event["invalidated_at"])
        )
    ]
    return eligible[-1] if eligible else None


def raw_control_label(
    m5_event: dict[str, Any] | None, m15_event: dict[str, Any] | None
) -> ControlState:
    if m5_event is None or m15_event is None:
        return "UNRESOLVED"
    if m5_event["direction"] != m15_event["direction"]:
        return "CONFLICTED"
    return (
        "BUYER_CONTROL" if m5_event["direction"] == "LONG" else "SELLER_CONTROL"
    )


def accepted_state_sequence(raw_states: Sequence[ControlState]) -> list[ControlState]:
    """Apply the frozen two-consecutive-close acceptance state machine."""

    candidate: ControlState | None = None
    count = 0
    output: list[ControlState] = []
    for raw in raw_states:
        if raw not in {"BUYER_CONTROL", "SELLER_CONTROL"}:
            candidate = None
            count = 0
            output.append(raw)
            continue
        if raw == candidate:
            count += 1
        else:
            candidate = raw
            count = 1
        output.append(raw if count >= ACCEPTANCE_M5_CLOSES else "UNRESOLVED")
    return output


def control_observations(
    *,
    m5_rows: Sequence[dict[str, Any]],
    m5_events: Sequence[dict[str, Any]],
    m15_events: Sequence[dict[str, Any]],
    start: str | datetime,
    end: str | datetime,
) -> list[dict[str, Any]]:
    opened = parse_dt(start)
    closed = parse_dt(end)
    checkpoints = [
        parse_dt(row["available_at"])
        for row in complete_rows(m5_rows, closed)
        if opened < parse_dt(row["available_at"]) <= closed
    ]
    raw: list[ControlState] = []
    pairs: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []
    for checkpoint in checkpoints:
        m5 = active_control_event(m5_events, checkpoint)
        m15 = active_control_event(m15_events, checkpoint)
        pairs.append((m5, m15))
        raw.append(raw_control_label(m5, m15))
    accepted = accepted_state_sequence(raw)
    output: list[dict[str, Any]] = []
    previous: ControlState | None = None
    for checkpoint, raw_state, state, pair in zip(
        checkpoints, raw, accepted, pairs, strict=True
    ):
        m5, m15 = pair
        transition = state in {"BUYER_CONTROL", "SELLER_CONTROL"} and state != previous
        row = {
            "at": iso(checkpoint),
            "raw_state": raw_state,
            "state": state,
            "transition": transition,
            "m5_event": m5,
            "m15_event": m15,
        }
        row["observation_sha256"] = canonical_hash(row)
        output.append(row)
        previous = state
    return output


def control_state_at(
    observations: Sequence[dict[str, Any]], at: str | datetime
) -> dict[str, Any]:
    point = parse_dt(at)
    eligible = [row for row in observations if parse_dt(row["at"]) <= point]
    if not eligible:
        return {
            "at": iso(point),
            "state": "UNRESOLVED",
            "raw_state": "UNRESOLVED",
            "source_observation_at": None,
            "m5_event_identity": None,
            "m15_event_identity": None,
        }
    source = eligible[-1]
    return {
        "at": iso(point),
        "state": source["state"],
        "raw_state": source["raw_state"],
        "source_observation_at": source["at"],
        "m5_event_identity": (source.get("m5_event") or {}).get("identity"),
        "m15_event_identity": (source.get("m15_event") or {}).get("identity"),
    }


def sweep_reclaims(
    rows: Sequence[dict[str, Any]], cutoff: str | datetime, timeframe: str = "M5"
) -> list[dict[str, Any]]:
    bars, swings = confirmed_swings(rows, cutoff, timeframe)
    output: list[dict[str, Any]] = []
    for bar in bars:
        known = [
            swing
            for swing in swings
            if parse_dt(swing["detected_at"]) <= parse_dt(bar["open_at"])
        ]
        highs = [swing for swing in known if swing["kind"] == "HIGH"]
        lows = [swing for swing in known if swing["kind"] == "LOW"]
        if highs:
            level = float(highs[-1]["level"])
            if float(bar["high"]) > level + TICK_FLOOR and float(bar["close"]) < level:
                output.append(
                    {
                        "at": iso(bar["available_at"]),
                        "direction": "SHORT",
                        "kind": "BUY_SIDE_SWEEP_RECLAIM",
                        "level": level,
                        "swing_identity": highs[-1]["identity"],
                    }
                )
        if lows:
            level = float(lows[-1]["level"])
            if float(bar["low"]) < level - TICK_FLOOR and float(bar["close"]) > level:
                output.append(
                    {
                        "at": iso(bar["available_at"]),
                        "direction": "LONG",
                        "kind": "SELL_SIDE_SWEEP_RECLAIM",
                        "level": level,
                        "swing_identity": lows[-1]["identity"],
                    }
                )
    return sorted(output, key=lambda row: (parse_dt(row["at"]), row["direction"]))


def latest_atr(
    rows: Sequence[dict[str, Any]], cutoff: str | datetime
) -> float | None:
    bars = complete_rows(rows, cutoff)
    if not bars:
        return None
    _, atrs = true_ranges_and_atr(bars)
    value = atrs[-1]
    return float(value) if value is not None and value > 0 else None


def first_m1_strictly_after(
    rows: Sequence[dict[str, Any]], after: str | datetime, before: str | datetime
) -> dict[str, Any] | None:
    start = parse_dt(after)
    end = parse_dt(before)
    return next(
        (
            row
            for row in complete_rows(rows, end)
            if start < parse_dt(row["open_at"]) < end
        ),
        None,
    )


def first_bearish_retest(
    rows: Sequence[dict[str, Any]],
    *,
    accepted_at: str | datetime,
    session_end: str | datetime,
    broken_level: float,
) -> dict[str, Any] | None:
    start = parse_dt(accepted_at)
    candidates = [
        row
        for row in complete_rows(rows, session_end)
        if parse_dt(row["available_at"]) > start
    ][:RETEST_EXPIRY_M5_BARS]
    for row in candidates:
        atr = latest_atr(rows, row["available_at"])
        if atr is None:
            continue
        tolerance = RETEST_TOLERANCE_ATR * atr
        qualifies = (
            float(row["high"]) >= float(broken_level) - tolerance
            and float(row["close"]) < float(broken_level)
            and float(row["close"]) < float(row["open"])
        )
        if qualifies:
            result = {
                "confirmation_at": iso(row["available_at"]),
                "bar_open_at": iso(row["open_at"]),
                "broken_level": float(broken_level),
                "m5_atr": atr,
                "tolerance": tolerance,
                "bar_identity": row.get("bar_id") or row.get("source_record_hash"),
            }
            result["confirmation_sha256"] = canonical_hash(result)
            return result
    return None


def nearest_downside_liquidity(
    stream: dict[str, Any],
    *,
    decision_at: str | datetime,
    fill: float,
    session: str,
) -> dict[str, Any] | None:
    """Return the nearest already-known downside liquidity; never skip it."""

    point = parse_dt(decision_at)
    candidates: list[dict[str, Any]] = []
    for key, label in (("15m", "M15"), ("1h", "H1"), ("4h", "H4")):
        _, swings = confirmed_swings(stream["timeframes"][key], point, label)
        for swing in swings:
            level = float(swing["level"])
            if swing["kind"] == "LOW" and level < fill:
                candidates.append(
                    {
                        "kind": f"{label}_CONFIRMED_SWING_LOW",
                        "level": level,
                        "known_at": swing["detected_at"],
                        "identity": swing["identity"],
                    }
                )

    calendar_day = date.fromisoformat(str(stream["trading_date_utc"]))
    if session == "LONDON":
        london_open, _ = session_bounds(calendar_day, "LONDON")
        range_start = datetime.combine(calendar_day, time.min, tzinfo=UTC)
        range_end = london_open
        range_kind = "COMPLETED_ASIA_OBSERVED_LOW"
    else:
        range_start, range_end = session_bounds(calendar_day, "LONDON")
        range_kind = "COMPLETED_LONDON_OBSERVED_LOW"
    if point >= range_end:
        range_rows = [
            row
            for row in complete_rows(stream["timeframes"]["1m"], range_end)
            if range_start <= parse_dt(row["open_at"]) < range_end
        ]
        if range_rows:
            level = min(float(row["low"]) for row in range_rows)
            if level < fill:
                identity = canonical_hash(
                    [range_kind, iso(range_start), iso(range_end), level]
                )
                candidates.append(
                    {
                        "kind": range_kind,
                        "level": level,
                        "known_at": iso(range_end),
                        "identity": identity,
                    }
                )
    if not candidates:
        return None
    nearest_level = max(float(row["level"]) for row in candidates)
    nearest = sorted(
        [row for row in candidates if float(row["level"]) == nearest_level],
        key=lambda row: (str(row["kind"]), str(row["identity"])),
    )[0]
    result = {**nearest, "eligible_level_count": len(candidates)}
    result["selection_sha256"] = canonical_hash(result)
    return result


def prepare_control(stream: dict[str, Any]) -> dict[str, Any]:
    cutoff = stream["end_exclusive"]
    m5_events = strong_breaks(stream["timeframes"]["5m"], cutoff, "M5")
    m15_events = strong_breaks(stream["timeframes"]["15m"], cutoff, "M15")
    sessions: dict[str, list[dict[str, Any]]] = {}
    calendar_day = date.fromisoformat(str(stream["trading_date_utc"]))
    for session in ("LONDON", "NEW_YORK"):
        start, end = session_bounds(calendar_day, session)
        sessions[session] = control_observations(
            m5_rows=stream["timeframes"]["5m"],
            m5_events=m5_events,
            m15_events=m15_events,
            start=start,
            end=end,
        )
    prepared = {
        "m5_events": m5_events,
        "m15_events": m15_events,
        "m5_sweeps": sweep_reclaims(stream["timeframes"]["5m"], cutoff),
        "sessions": sessions,
    }
    prepared["prepared_sha256"] = canonical_hash(prepared)
    return prepared


def _failed_buyer_antecedent(
    *,
    observations: Sequence[dict[str, Any]],
    sweeps: Sequence[dict[str, Any]],
    session_start: datetime,
    accepted_at: datetime,
) -> dict[str, Any] | None:
    buyers = [
        row
        for row in observations
        if session_start < parse_dt(row["at"]) < accepted_at
        and row["state"] == "BUYER_CONTROL"
    ]
    sweep_rows = [
        row
        for row in sweeps
        if session_start < parse_dt(row["at"]) < accepted_at
        and row["kind"] == "BUY_SIDE_SWEEP_RECLAIM"
    ]
    candidates: list[dict[str, Any]] = []
    if buyers:
        candidates.append(
            {
                "kind": "PRIOR_ACCEPTED_BUYER_CONTROL",
                "at": buyers[-1]["at"],
                "identity": buyers[-1]["observation_sha256"],
            }
        )
    if sweep_rows:
        candidates.append(
            {
                "kind": "BUY_SIDE_SWEEP_RECLAIM",
                "at": sweep_rows[-1]["at"],
                "identity": sweep_rows[-1]["swing_identity"],
            }
        )
    return max(candidates, key=lambda row: parse_dt(row["at"])) if candidates else None


def seller_auction_short_plans(
    stream: dict[str, Any], prepared: dict[str, Any], session: str
) -> dict[str, Any]:
    calendar_day = date.fromisoformat(str(stream["trading_date_utc"]))
    opened, closed = session_bounds(calendar_day, session)
    observations = prepared["sessions"][session]
    transitions = [
        row
        for row in observations
        if row["transition"] and row["state"] == "SELLER_CONTROL"
    ]
    attempts: list[dict[str, Any]] = []
    admitted: list[dict[str, Any]] = []
    for transition in transitions:
        accepted_at = parse_dt(transition["at"])
        m5_event = transition.get("m5_event")
        antecedent = _failed_buyer_antecedent(
            observations=observations,
            sweeps=prepared["m5_sweeps"],
            session_start=opened,
            accepted_at=accepted_at,
        )
        if m5_event is None:
            attempts.append(
                {"accepted_at": transition["at"], "disposition": "M5_CONTROL_EVENT_MISSING"}
            )
            continue
        if antecedent is None:
            attempts.append(
                {"accepted_at": transition["at"], "disposition": "NO_FAILED_BUYER_AUCTION"}
            )
            continue
        confirmation = first_bearish_retest(
            stream["timeframes"]["5m"],
            accepted_at=accepted_at,
            session_end=closed,
            broken_level=float(m5_event["broken_level"]),
        )
        if confirmation is None:
            attempts.append(
                {
                    "accepted_at": transition["at"],
                    "antecedent": antecedent,
                    "disposition": "NO_BEARISH_RETEST_WITHIN_6_M5",
                }
            )
            continue
        fill_bar = first_m1_strictly_after(
            stream["timeframes"]["1m"], confirmation["confirmation_at"], closed
        )
        if fill_bar is None:
            attempts.append(
                {
                    "accepted_at": transition["at"],
                    "antecedent": antecedent,
                    "confirmation": confirmation,
                    "disposition": "NO_EXECUTABLE_M1_BEFORE_SESSION_END",
                }
            )
            continue
        fill_at = iso(fill_bar["open_at"])
        decision_rows = complete_rows(
            stream["timeframes"]["1m"], confirmation["confirmation_at"]
        )
        if not decision_rows:
            attempts.append(
                {"accepted_at": transition["at"], "disposition": "DECISION_SPREAD_UNAVAILABLE"}
            )
            continue
        fill = float(fill_bar["open"]) - (
            spread_price(fill_bar) / 2.0 + SLIPPAGE_USD_PER_OUNCE
        )
        cost = spread_price(decision_rows[-1]) + 2.0 * SLIPPAGE_USD_PER_OUNCE
        m15_atr = latest_atr(
            stream["timeframes"]["15m"], confirmation["confirmation_at"]
        )
        if m15_atr is None:
            attempts.append(
                {"accepted_at": transition["at"], "disposition": "M15_ATR_UNAVAILABLE"}
            )
            continue
        stop = float(m5_event["protected_level"]) + max(
            STOP_BUFFER_M15_ATR * m15_atr, TICK_FLOOR
        )
        liquidity = nearest_downside_liquidity(
            stream,
            decision_at=confirmation["confirmation_at"],
            fill=fill,
            session=session,
        )
        if liquidity is None:
            attempts.append(
                {"accepted_at": transition["at"], "disposition": "NO_KNOWN_DOWNSIDE_LIQUIDITY"}
            )
            continue
        target = float(liquidity["level"])
        risk = stop - fill
        reward = fill - target
        geometry_valid = risk > 0 and reward > 0
        room = reward / risk if geometry_valid else None
        quantity = math.floor(RISK_USD / (risk + cost)) if geometry_valid else 0
        if not geometry_valid:
            disposition = "INVALID_SHORT_GEOMETRY"
        elif room is None or room < TARGET_ROOM_R_MINIMUM:
            disposition = "NEAREST_LIQUIDITY_ROOM_LT_1P5R"
        elif quantity < 1:
            disposition = "WHOLE_OUNCE_RISK_UNAVAILABLE"
        else:
            disposition = "ADMIT"
        plan: dict[str, Any] = {
            "ruleset": RULESET,
            "session": session,
            "direction": "SHORT",
            "accepted_at": transition["at"],
            "control_observation_sha256": transition["observation_sha256"],
            "antecedent": antecedent,
            "confirmation": confirmation,
            "fill_at": fill_at,
            "fill": fill,
            "stop": stop,
            "target": target,
            "m15_atr": m15_atr,
            "structural_price_risk_per_ounce": risk if geometry_valid else None,
            "target_room_r": room,
            "cost_per_ounce": cost,
            "quantity_ounces": quantity,
            "liquidity_target": liquidity,
            "macro": macro_state(stream, confirmation["confirmation_at"], "SHORT"),
            "h4": h4_context_metrics(stream, confirmation["confirmation_at"], "SHORT"),
            "disposition": disposition,
            "admitted": disposition == "ADMIT",
        }
        plan["plan_sha256"] = canonical_hash(plan)
        attempts.append(plan)
        if plan["admitted"]:
            admitted.append(plan)
    admitted.sort(key=lambda row: (parse_dt(row["fill_at"]), row["plan_sha256"]))
    return {
        "session": session,
        "seller_control_transitions": len(transitions),
        "attempts": attempts,
        "first_admitted": admitted[0] if admitted else None,
    }


def short_classification(plan: dict[str, Any]) -> dict[str, Any]:
    if not plan.get("admitted"):
        raise ValueError("Cannot classify a rejected short plan")
    result = {
        "ruleset": RULESET,
        "decision_at": plan["confirmation"]["confirmation_at"],
        "direction": "SHORT",
        "family": "SELLER_AUCTION_FAILED_BUYER_RETEST",
        "admitted": True,
        "primary_disposition": "ADMIT",
        "blockers": [],
        "warnings": [],
        "macro": plan["macro"],
        "h4": plan["h4"],
        "fill": plan["fill"],
        "stop": plan["stop"],
        "target": plan["target"],
        "structural_price_risk_per_ounce": plan["structural_price_risk_per_ounce"],
        "cost_per_ounce": plan["cost_per_ounce"],
        "planned_loss_per_ounce": (
            float(plan["structural_price_risk_per_ounce"])
            + float(plan["cost_per_ounce"])
        ),
        "quantity_ounces": plan["quantity_ounces"],
        "classification_hash": None,
    }
    result["classification_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "classification_hash"}
    )
    return result


def earliest_candidate(
    long_candidate: dict[str, Any] | None, short_candidate: dict[str, Any] | None
) -> dict[str, Any] | None:
    candidates = [row for row in (long_candidate, short_candidate) if row is not None]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: (
            parse_dt(row["fill_at"]),
            0 if row["direction"] == "LONG" else 1,
        ),
    )
