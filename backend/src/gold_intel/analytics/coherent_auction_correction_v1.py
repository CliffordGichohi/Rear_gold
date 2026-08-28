"""Frozen coherent-auction correction policy.

The module is deliberately pure: classification receives only a sealed decision,
point-in-time replay stream, and the already-sealed fill.  Outcome fields are not
part of the classifier API.  Path simulation is a separate function called only
after classification has been sealed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

RULESET = "gold-coherent-auction-complete-correction-v1"
Direction = Literal["LONG", "SHORT"]

ATR_WINDOW = 14
PIVOT_WIDTH = 2
PIVOT_PROMINENCE_ATR = 0.25
TICK_FLOOR = 0.02
BREAK_BUFFER_ATR = 0.10
TRANSITION_BUFFER_ATR = 0.05
RETEST_TOLERANCE_ATR = 0.25
BALANCE_WINDOW = 20
BALANCE_MAX_WIDTH_ATR = 5.0
BALANCE_EXPIRY_BARS = 40
TRIGGER_EXPIRY_M5_BARS = 12
RISK_BUDGET_USD = 50.0

TIER_1_EVENTS = {
    "CPI",
    "CORE_CPI",
    "PCE",
    "CORE_PCE",
    "NFP",
    "NFP_PAYROLLS",
    "PAYROLLS",
    "UNEMPLOYMENT",
    "FOMC_RATE_DECISION",
    "FOMC_PROJECTIONS",
    "FOMC_PRESS_CONFERENCE",
}

TIMEFRAME_KEYS = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "H4": "4h",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso(value: str | datetime) -> str:
    return parse_dt(value).isoformat().replace("+00:00", "Z")


def before_or_equal(left: str | datetime, right: str | datetime) -> bool:
    return parse_dt(left) <= parse_dt(right)


def direction_sign(direction: Direction) -> int:
    return 1 if direction == "LONG" else -1


def adverse_extreme(row: dict[str, Any], direction: Direction) -> float:
    return float(row["low"] if direction == "LONG" else row["high"])


def favourable_extreme(row: dict[str, Any], direction: Direction) -> float:
    return float(row["high"] if direction == "LONG" else row["low"])


def aligned_close(row: dict[str, Any], direction: Direction) -> bool:
    return (
        float(row["close"]) > float(row["open"])
        if direction == "LONG"
        else float(row["close"]) < float(row["open"])
    )


def complete_rows(rows: Sequence[dict[str, Any]], cutoff: str | datetime) -> list[dict[str, Any]]:
    end = parse_dt(cutoff)
    return sorted(
        [
            row
            for row in rows
            if row.get("complete") is True
            and parse_dt(row["available_at"]) <= end
        ],
        key=lambda row: (parse_dt(row["open_at"]), parse_dt(row["available_at"])),
    )


def true_ranges_and_atr(rows: Sequence[dict[str, Any]]) -> tuple[list[float], list[float | None]]:
    true_ranges: list[float] = []
    atrs: list[float | None] = []
    for index, row in enumerate(rows):
        high = float(row["high"])
        low = float(row["low"])
        if index == 0:
            tr = high - low
        else:
            prior = float(rows[index - 1]["close"])
            tr = max(high - low, abs(high - prior), abs(low - prior))
        true_ranges.append(tr)
        if index + 1 < ATR_WINDOW:
            atrs.append(None)
        else:
            atrs.append(sum(true_ranges[index - ATR_WINDOW + 1 : index + 1]) / ATR_WINDOW)
    return true_ranges, atrs


def latest_atr(rows: Sequence[dict[str, Any]], cutoff: str | datetime) -> float | None:
    eligible = complete_rows(rows, cutoff)
    if not eligible:
        return None
    _, atrs = true_ranges_and_atr(eligible)
    return atrs[-1]


def confirmed_swings(
    rows: Sequence[dict[str, Any]], cutoff: str | datetime, timeframe: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bars = complete_rows(rows, cutoff)
    _, atrs = true_ranges_and_atr(bars)
    swings: list[dict[str, Any]] = []
    for index in range(PIVOT_WIDTH, len(bars) - PIVOT_WIDTH):
        atr = atrs[index]
        if atr is None or atr <= 0:
            continue
        center = bars[index]
        neighbors = bars[index - PIVOT_WIDTH : index] + bars[index + 1 : index + PIVOT_WIDTH + 1]
        minimum = max(PIVOT_PROMINENCE_ATR * atr, TICK_FLOOR)
        high = float(center["high"])
        low = float(center["low"])
        high_prominence = high - min(float(item["low"]) for item in neighbors)
        low_prominence = max(float(item["high"]) for item in neighbors) - low
        candidates = (
            ("HIGH", high, high_prominence, all(high > float(item["high"]) for item in neighbors)),
            ("LOW", low, low_prominence, all(low < float(item["low"]) for item in neighbors)),
        )
        for kind, level, prominence, strict in candidates:
            if not strict or prominence < minimum:
                continue
            detected_at = iso(bars[index + PIVOT_WIDTH]["available_at"])
            identity = canonical_hash(
                ["SWING", timeframe, kind, iso(center["open_at"]), level, detected_at]
            )
            swings.append(
                {
                    "identity": identity,
                    "kind": kind,
                    "timeframe": timeframe,
                    "pivot_index": index,
                    "pivot_at": iso(center["open_at"]),
                    "detected_at": detected_at,
                    "level": level,
                    "atr": atr,
                    "prominence_atr": prominence / atr,
                }
            )
    return bars, sorted(swings, key=lambda item: (parse_dt(item["detected_at"]), item["kind"], item["identity"]))


def swing_relations(swings: Sequence[dict[str, Any]]) -> dict[str, str]:
    highs = [item for item in swings if item["kind"] == "HIGH"]
    lows = [item for item in swings if item["kind"] == "LOW"]

    def relation(values: list[dict[str, Any]], high: bool) -> str:
        if len(values) < 2:
            return "UNKNOWN"
        prior = float(values[-2]["level"])
        latest = float(values[-1]["level"])
        if latest > prior + TICK_FLOOR:
            return "HH" if high else "HL"
        if latest < prior - TICK_FLOOR:
            return "LH" if high else "LL"
        return "EH" if high else "EL"

    return {"high": relation(highs, True), "low": relation(lows, False)}


def transition_origin(
    bars: Sequence[dict[str, Any]], index: int, direction: Direction
) -> dict[str, Any]:
    prior = list(bars[max(0, index - 4) : index])
    for row in reversed(prior):
        opposite = (
            float(row["close"]) < float(row["open"])
            if direction == "LONG"
            else float(row["close"]) > float(row["open"])
        )
        if opposite:
            return row
    return bars[index]


def structural_breaks(
    rows: Sequence[dict[str, Any]],
    cutoff: str | datetime,
    timeframe: str,
    direction: Direction,
    *,
    buffer_atr: float = BREAK_BUFFER_ATR,
    minimum_range_atr: float | None = None,
    minimum_body_ratio: float | None = None,
    after: str | datetime | None = None,
) -> list[dict[str, Any]]:
    bars, swings = confirmed_swings(rows, cutoff, timeframe)
    true_ranges, atrs = true_ranges_and_atr(bars)
    broken: set[str] = set()
    output: list[dict[str, Any]] = []
    target_kind = "HIGH" if direction == "LONG" else "LOW"
    protected_kind = "LOW" if direction == "LONG" else "HIGH"
    after_dt = parse_dt(after) if after is not None else None
    for index, bar in enumerate(bars):
        if after_dt is not None and parse_dt(bar["available_at"]) < after_dt:
            continue
        atr = atrs[index]
        if atr is None or atr <= 0:
            continue
        candidates = [
            swing
            for swing in swings
            if swing["kind"] == target_kind
            and swing["identity"] not in broken
            and swing["pivot_index"] < index
            and parse_dt(swing["detected_at"]) <= parse_dt(bar["open_at"])
        ]
        if not candidates:
            continue
        pivot = max(candidates, key=lambda item: (item["pivot_index"], item["detected_at"]))
        protected_candidates = [
            swing
            for swing in swings
            if swing["kind"] == protected_kind
            and swing["pivot_index"] < index
            and parse_dt(swing["detected_at"]) <= parse_dt(bar["open_at"])
        ]
        if not protected_candidates:
            continue
        protected = max(
            protected_candidates,
            key=lambda item: (item["pivot_index"], item["detected_at"]),
        )
        threshold_buffer = max(buffer_atr * atr, TICK_FLOOR)
        close = float(bar["close"])
        crossed = (
            close > float(pivot["level"]) + threshold_buffer
            if direction == "LONG"
            else close < float(pivot["level"]) - threshold_buffer
        )
        if not crossed:
            continue
        range_atr = true_ranges[index] / atr
        candle_range = max(float(bar["high"]) - float(bar["low"]), TICK_FLOOR)
        body_ratio = abs(close - float(bar["open"])) / candle_range
        if minimum_range_atr is not None and range_atr < minimum_range_atr:
            continue
        if minimum_body_ratio is not None and body_ratio < minimum_body_ratio:
            continue
        broken.add(str(pivot["identity"]))
        origin = transition_origin(bars, index, direction)
        output.append(
            {
                "identity": canonical_hash(
                    [
                        "BREAK",
                        timeframe,
                        direction,
                        pivot["identity"],
                        protected["identity"],
                        iso(bar["available_at"]),
                    ]
                ),
                "timeframe": timeframe,
                "direction": direction,
                "break_index": index,
                "break_at": iso(bar["available_at"]),
                "broken_level": float(pivot["level"]),
                "broken_identity": pivot["identity"],
                "protected_level": float(protected["level"]),
                "protected_identity": protected["identity"],
                "origin_at": iso(origin["open_at"]),
                "origin_adverse": adverse_extreme(origin, direction),
                "atr": atr,
                "range_atr": range_atr,
                "body_ratio": body_ratio,
                "buffer": threshold_buffer,
            }
        )
    return output


def event_is_active(
    event: dict[str, Any], rows: Sequence[dict[str, Any]], cutoff: str | datetime
) -> bool:
    bars = complete_rows(rows, cutoff)
    buffer = max(BREAK_BUFFER_ATR * float(event["atr"]), TICK_FLOOR)
    for bar in bars:
        if parse_dt(bar["available_at"]) <= parse_dt(event["break_at"]):
            continue
        invalid = (
            float(bar["close"]) < float(event["protected_level"]) - buffer
            if event["direction"] == "LONG"
            else float(bar["close"]) > float(event["protected_level"]) + buffer
        )
        if invalid:
            return False
    return True


def first_accepted_retest(
    rows: Sequence[dict[str, Any]],
    *,
    known_at: str | datetime,
    cutoff: str | datetime,
    level: float,
    direction: Direction,
    acceptance_buffer_atr: float = BREAK_BUFFER_ATR,
) -> dict[str, Any] | None:
    bars = complete_rows(rows, cutoff)
    _, atrs = true_ranges_and_atr(bars)
    consecutive = 0
    accepted_at: str | None = None
    for index, bar in enumerate(bars):
        if parse_dt(bar["open_at"]) < parse_dt(known_at):
            continue
        atr = atrs[index]
        if atr is None:
            continue
        buffer = max(acceptance_buffer_atr * atr, TICK_FLOOR)
        beyond = (
            float(bar["close"]) > level + buffer
            if direction == "LONG"
            else float(bar["close"]) < level - buffer
        )
        if accepted_at is None:
            consecutive = consecutive + 1 if beyond else 0
            if consecutive >= 2:
                accepted_at = iso(bar["available_at"])
            continue
        tolerance = RETEST_TOLERANCE_ATR * atr
        held = (
            float(bar["low"]) <= level + tolerance and float(bar["close"]) > level
            if direction == "LONG"
            else float(bar["high"]) >= level - tolerance and float(bar["close"]) < level
        )
        if held:
            return {
                "accepted_at": accepted_at,
                "retest_at": iso(bar["available_at"]),
                "level": level,
                "atr": atr,
            }
    return None


def level_lifecycle(
    rows: Sequence[dict[str, Any]],
    *,
    level: float,
    known_at: str | datetime,
    cutoff: str | datetime,
    direction: Direction,
) -> dict[str, Any]:
    bars = complete_rows(rows, cutoff)
    _, atrs = true_ranges_and_atr(bars)
    state = "ACTIVE_UNTOUCHED"
    forward = 0
    reverse = 0
    consumed_at: str | None = None
    reactivated_at: str | None = None
    engaged_at: str | None = None
    last_buffer = TICK_FLOOR
    for index, bar in enumerate(bars):
        if parse_dt(bar["available_at"]) <= parse_dt(known_at):
            continue
        atr = atrs[index]
        if atr is None:
            continue
        last_buffer = max(BREAK_BUFFER_ATR * atr, TICK_FLOOR)
        touched = (
            float(bar["high"]) >= level - last_buffer
            if direction == "LONG"
            else float(bar["low"]) <= level + last_buffer
        )
        if touched and engaged_at is None:
            engaged_at = iso(bar["available_at"])
            state = "ACTIVE_ENGAGED"
        beyond = (
            float(bar["close"]) > level + last_buffer
            if direction == "LONG"
            else float(bar["close"]) < level - last_buffer
        )
        back = (
            float(bar["close"]) < level - last_buffer
            if direction == "LONG"
            else float(bar["close"]) > level + last_buffer
        )
        if consumed_at is None:
            forward = forward + 1 if beyond else 0
            if forward >= 2:
                consumed_at = iso(bar["available_at"])
                state = "CONSUMED_ACCEPTED"
        else:
            reverse = reverse + 1 if back else 0
            if reverse >= 2:
                reactivated_at = iso(bar["available_at"])
                state = "REACTIVATED_REVERSE"
    return {
        "state": state,
        "engaged_at": engaged_at,
        "consumed_at": consumed_at,
        "reactivated_at": reactivated_at,
        "buffer": last_buffer,
    }


@dataclass(frozen=True, slots=True)
class BalanceBox:
    identity: str
    timeframe: str
    low: float
    high: float
    known_at: str
    source_end_index: int
    atr: float


def balance_boxes(
    rows: Sequence[dict[str, Any]], cutoff: str | datetime, timeframe: str
) -> tuple[list[dict[str, Any]], list[BalanceBox]]:
    bars, swings = confirmed_swings(rows, cutoff, timeframe)
    _, atrs = true_ranges_and_atr(bars)
    boxes: list[BalanceBox] = []
    for end in range(BALANCE_WINDOW - 1, len(bars)):
        atr = atrs[end]
        if atr is None or atr <= 0:
            continue
        start = end - BALANCE_WINDOW + 1
        window = bars[start : end + 1]
        low = min(float(row["low"]) for row in window)
        high = max(float(row["high"]) for row in window)
        if (high - low) / atr > BALANCE_MAX_WIDTH_ATR:
            continue
        members = [
            swing
            for swing in swings
            if start <= int(swing["pivot_index"]) <= end
            and parse_dt(swing["detected_at"]) <= parse_dt(bars[end]["available_at"])
        ]
        if sum(item["kind"] == "HIGH" for item in members) < 2:
            continue
        if sum(item["kind"] == "LOW" for item in members) < 2:
            continue
        known = iso(bars[end]["available_at"])
        boxes.append(
            BalanceBox(
                identity=canonical_hash(["BALANCE", timeframe, known, low, high]),
                timeframe=timeframe,
                low=low,
                high=high,
                known_at=known,
                source_end_index=end,
                atr=atr,
            )
        )
    return bars, boxes


def active_balance_candidates(
    stream: dict[str, Any],
    cutoff: str,
    price: float,
    direction: Direction,
    timeframes: Sequence[str] = ("H4", "H1"),
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for timeframe in timeframes:
        key = TIMEFRAME_KEYS[timeframe]
        bars, boxes = balance_boxes(stream["timeframes"][key], cutoff, timeframe)
        accept_key = "1h" if timeframe == "H4" else "15m" if timeframe == "H1" else "5m"
        for box in boxes:
            later_source = [
                row
                for row in bars
                if parse_dt(row["available_at"]) > parse_dt(box.known_at)
            ]
            if len(later_source) > BALANCE_EXPIRY_BARS:
                continue
            width = box.high - box.low
            if width <= 0:
                continue
            location = (price - box.low) / width
            breakout_level = box.high if direction == "LONG" else box.low
            breakout = first_accepted_retest(
                stream["timeframes"][accept_key],
                known_at=box.known_at,
                cutoff=cutoff,
                level=breakout_level,
                direction=direction,
            )
            boundary_engaged = location <= 0.25 or location >= 0.75
            if not boundary_engaged and breakout is None:
                continue
            event_at = breakout["retest_at"] if breakout else cutoff
            output.append(
                {
                    "identity": box.identity,
                    "timeframe": timeframe,
                    "low": box.low,
                    "high": box.high,
                    "midpoint": (box.low + box.high) / 2,
                    "known_at": box.known_at,
                    "atr": box.atr,
                    "location": location,
                    "boundary_engaged": boundary_engaged,
                    "accepted_breakout": breakout,
                    "event_at": event_at,
                }
            )
    priority = {"H4": 0, "H1": 1, "M15": 2}
    return sorted(
        output,
        key=lambda item: (
            parse_dt(item["event_at"]),
            -priority.get(item["timeframe"], 9),
            parse_dt(item["known_at"]),
            item["identity"],
        ),
        reverse=True,
    )


def latest_context_record(
    stream: dict[str, Any], family: str, cutoff: str
) -> dict[str, Any] | None:
    rows = [
        row
        for row in stream.get("context_timeline", {}).get(family, [])
        if parse_dt(row.get("available_at", row.get("event_available_at", cutoff)))
        <= parse_dt(cutoff)
    ]
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: parse_dt(row.get("available_at", row.get("event_available_at", cutoff))),
    )


def zone_registry(
    stream: dict[str, Any], cutoff: str, direction: Direction
) -> list[dict[str, Any]]:
    desired_kind = "HIGH" if direction == "LONG" else "LOW"
    acceptance_key = {"H4": "1h", "H1": "15m"}
    priority = {"H4": 4, "H1": 3, "SESSION": 2, "M15": 1}
    candidates: list[dict[str, Any]] = []
    for timeframe in ("H4", "H1"):
        _, swings = confirmed_swings(
            stream["timeframes"][TIMEFRAME_KEYS[timeframe]], cutoff, timeframe
        )
        for swing in swings:
            if swing["kind"] != desired_kind:
                continue
            lifecycle = level_lifecycle(
                stream["timeframes"][acceptance_key[timeframe]],
                level=float(swing["level"]),
                known_at=swing["detected_at"],
                cutoff=cutoff,
                direction=direction,
            )
            candidates.append(
                {
                    "identity": swing["identity"],
                    "source": timeframe,
                    "kind": desired_kind,
                    "level": float(swing["level"]),
                    "known_at": swing["detected_at"],
                    "prominence_atr": float(swing["prominence_atr"]),
                    "priority": priority[timeframe],
                    **lifecycle,
                }
            )
    session = latest_context_record(stream, "sessions", cutoff)
    if session is not None:
        for level in session.get("known_levels", []):
            wanted = level.get("side") == ("UPPER" if direction == "LONG" else "LOWER")
            if not wanted or parse_dt(level["known_at"]) > parse_dt(cutoff):
                continue
            lifecycle = level_lifecycle(
                stream["timeframes"]["15m"],
                level=float(level["price"]),
                known_at=level["known_at"],
                cutoff=cutoff,
                direction=direction,
            )
            candidates.append(
                {
                    "identity": canonical_hash(
                        ["SESSION_LEVEL", level.get("code"), level["known_at"], level["price"]]
                    ),
                    "source": "SESSION",
                    "kind": desired_kind,
                    "level": float(level["price"]),
                    "known_at": iso(level["known_at"]),
                    "prominence_atr": None,
                    "priority": priority["SESSION"],
                    **lifecycle,
                }
            )
    # Merge only zones that are within the approved ATR/tick band.  The higher
    # timeframe record owns the merged identity and lifecycle.
    ordered = sorted(
        candidates,
        key=lambda item: (
            direction_sign(direction) * float(item["level"]),
            -int(item["priority"]),
            parse_dt(item["known_at"]),
            item["identity"],
        ),
    )
    merged: list[dict[str, Any]] = []
    for candidate in ordered:
        match = next(
            (
                existing
                for existing in merged
                if abs(float(existing["level"]) - float(candidate["level"]))
                <= max(float(existing["buffer"]), float(candidate["buffer"]), TICK_FLOOR)
            ),
            None,
        )
        if match is None:
            merged.append(dict(candidate))
        elif int(candidate["priority"]) > int(match["priority"]):
            merged[merged.index(match)] = dict(candidate)
    for item in merged:
        item.pop("priority", None)
    return merged


def macro_state(stream: dict[str, Any], cutoff: str, direction: Direction) -> dict[str, Any]:
    record = latest_context_record(stream, "fundamentals", cutoff)
    if record is None:
        return {
            "state": "UNKNOWN",
            "score": None,
            "confidence": None,
            "quality": None,
            "available_at": None,
            "reason": "MISSING_FUNDAMENTAL_SNAPSHOT",
        }
    engine = record.get("engine_state", {})
    components = {item.get("code"): item for item in engine.get("components", [])}
    critical = [components.get("REAL_YIELD"), components.get("USD")]
    qualities = [
        float(item["data_quality"])
        for item in critical
        if item is not None and item.get("data_quality") is not None
    ]
    quality = min(qualities) if len(qualities) == 2 else None
    score = engine.get("directional_score")
    if score is None or quality is None or quality < 60:
        state = "UNKNOWN"
        reason = "SCORE_OR_CRITICAL_CONTEXT_UNAVAILABLE"
    else:
        score = float(score)
        signed = direction_sign(direction) * score
        if signed >= 20:
            state = "ALIGNED"
        elif signed <= -20:
            state = "OPPOSED"
        else:
            state = "NEUTRAL_OR_CONFLICTED"
        reason = None
    return {
        "state": state,
        "score": float(score) if score is not None else None,
        "confidence": engine.get("confidence"),
        "quality": quality,
        "available_at": iso(record["available_at"]),
        "bias_label": engine.get("bias_label"),
        "dominant_driver": engine.get("dominant_driver"),
        "reason": reason,
        "record_hash": record.get("record_hash"),
    }


def _event_code(event: dict[str, Any]) -> str:
    values = [
        str(event.get("event_type", "")).upper(),
        str(event.get("event_code", "")).upper(),
    ]
    for value in values:
        if value in TIER_1_EVENTS:
            return value
        if value.startswith("US_") and value[3:] in TIER_1_EVENTS:
            return value[3:]
    return values[0]


def event_lock_state(
    stream: dict[str, Any], cutoff: str, direction: Direction
) -> dict[str, Any]:
    decision = parse_dt(cutoff)
    events = []
    for event in stream.get("context_timeline", {}).get("events", []):
        if _event_code(event) not in TIER_1_EVENTS:
            continue
        scheduled_raw = event.get("scheduled_at") or event.get("released_at")
        if not scheduled_raw:
            continue
        scheduled = parse_dt(scheduled_raw)
        if scheduled.date() != decision.date():
            continue
        if decision < scheduled:
            if (scheduled - decision).total_seconds() <= 15 * 60:
                events.append((event, "PRE_EVENT_LOCK"))
            continue
        events.append((event, "POST_EVENT_CHECK"))
    if not events:
        return {"locked": False, "reason": None, "event": None, "acceptance": None}
    event, mode = max(events, key=lambda item: parse_dt(item[0].get("scheduled_at") or item[0]["released_at"]))
    scheduled = parse_dt(event.get("scheduled_at") or event["released_at"])
    if mode == "PRE_EVENT_LOCK" or decision <= scheduled.replace() + (decision - decision):
        return {
            "locked": True,
            "reason": "TIER1_PRE_EVENT_LOCK",
            "event": _event_code(event),
            "scheduled_at": iso(scheduled),
            "acceptance": None,
        }
    initial_end = scheduled.timestamp() + 15 * 60
    if decision.timestamp() <= initial_end:
        return {
            "locked": True,
            "reason": "TIER1_INITIAL_15M_RANGE_INCOMPLETE",
            "event": _event_code(event),
            "scheduled_at": iso(scheduled),
            "acceptance": None,
        }
    m1 = complete_rows(stream["timeframes"]["1m"], cutoff)
    members = [
        row
        for row in m1
        if scheduled <= parse_dt(row["open_at"])
        and parse_dt(row["open_at"]).timestamp() < initial_end
    ]
    if not members:
        return {
            "locked": True,
            "reason": "TIER1_INITIAL_RANGE_MISSING",
            "event": _event_code(event),
            "scheduled_at": iso(scheduled),
            "acceptance": None,
        }
    level = (
        max(float(row["high"]) for row in members)
        if direction == "LONG"
        else min(float(row["low"]) for row in members)
    )
    acceptance = first_accepted_retest(
        stream["timeframes"]["5m"],
        known_at=datetime.fromtimestamp(initial_end, tz=UTC),
        cutoff=cutoff,
        level=level,
        direction=direction,
    )
    return {
        "locked": acceptance is None,
        "reason": "TIER1_DIRECTIONAL_ACCEPTANCE_RETEST_MISSING" if acceptance is None else None,
        "event": _event_code(event),
        "scheduled_at": iso(scheduled),
        "initial_range_level": level,
        "acceptance": acceptance,
    }


def h4_damage_state(
    stream: dict[str, Any], cutoff: str, direction: Direction
) -> dict[str, Any] | None:
    rows = stream["timeframes"]["4h"]
    aligned = structural_breaks(rows, cutoff, "H4", direction)
    if not aligned:
        return None
    event = aligned[-1]
    bars = complete_rows(rows, cutoff)
    true_ranges, atrs = true_ranges_and_atr(bars)
    breached: dict[str, Any] | None = None
    consecutive = 0
    for index, bar in enumerate(bars):
        if parse_dt(bar["available_at"]) <= parse_dt(event["break_at"]):
            continue
        atr = atrs[index]
        if atr is None or atr <= 0:
            continue
        level = float(event["protected_level"])
        close = float(bar["close"])
        beyond_005 = close < level - 0.05 * atr if direction == "LONG" else close > level + 0.05 * atr
        beyond_010 = close < level - 0.10 * atr if direction == "LONG" else close > level + 0.10 * atr
        candle_range = max(float(bar["high"]) - float(bar["low"]), TICK_FLOOR)
        body_ratio = abs(close - float(bar["open"])) / candle_range
        displacement = true_ranges[index] / atr >= 1.25 and body_ratio >= 0.60 and beyond_005
        consecutive = consecutive + 1 if beyond_010 else 0
        if displacement or consecutive >= 2:
            breached = {
                "damage_at": iso(bar["available_at"]),
                "damage_type": "SINGLE_DISPLACEMENT" if displacement else "TWO_CLOSE_DAMAGE",
                "broken_reference": level,
                "prior_break": event,
                "atr": atr,
            }
            break
    if breached is None:
        return None
    repair = first_accepted_retest(
        rows,
        known_at=breached["damage_at"],
        cutoff=cutoff,
        level=float(breached["broken_reference"]),
        direction=direction,
    )
    if repair is not None:
        return None
    return breached


def repair_evidence(
    stream: dict[str, Any], cutoff: str, direction: Direction, damage: dict[str, Any]
) -> dict[str, Any] | None:
    for timeframe in ("H1", "M15"):
        rows = stream["timeframes"][TIMEFRAME_KEYS[timeframe]]
        events = structural_breaks(
            rows,
            cutoff,
            timeframe,
            direction,
            after=damage["damage_at"],
        )
        for event in reversed(events):
            accepted = first_accepted_retest(
                rows,
                known_at=event["break_at"],
                cutoff=cutoff,
                level=float(event["broken_level"]),
                direction=direction,
            )
            if accepted is not None:
                return {
                    "timeframe": timeframe,
                    "break": event,
                    "acceptance": accepted,
                    "available_at": accepted["retest_at"],
                }
    return None


def directional_progression(
    stream: dict[str, Any], cutoff: str, direction: Direction
) -> dict[str, Any] | None:
    opposite: Direction = "SHORT" if direction == "LONG" else "LONG"
    for timeframe in ("H4", "H1"):
        rows = stream["timeframes"][TIMEFRAME_KEYS[timeframe]]
        _, swings = confirmed_swings(rows, cutoff, timeframe)
        relations = swing_relations(swings)
        aligned_relation = (
            relations == {"high": "HH", "low": "HL"}
            if direction == "LONG"
            else relations == {"high": "LH", "low": "LL"}
        )
        events = structural_breaks(rows, cutoff, timeframe, direction)
        active = [item for item in events if event_is_active(item, rows, cutoff)]
        if not active:
            continue
        chosen = active[-1]
        opposing = structural_breaks(rows, cutoff, timeframe, opposite)
        later_than_opposite = not opposing or parse_dt(chosen["break_at"]) > parse_dt(opposing[-1]["break_at"])
        if aligned_relation or later_than_opposite:
            return {
                "timeframe": timeframe,
                "event": chosen,
                "relations": relations,
                "aligned_relation": aligned_relation,
                "later_than_opposite": later_than_opposite,
                "available_at": chosen["break_at"],
            }
    return None


def held_retest_within(
    rows: Sequence[dict[str, Any]],
    *,
    after: str,
    cutoff: str,
    level: float,
    direction: Direction,
    maximum_bars: int = TRIGGER_EXPIRY_M5_BARS,
) -> dict[str, Any] | None:
    bars = [
        row
        for row in complete_rows(rows, cutoff)
        if parse_dt(row["open_at"]) >= parse_dt(after)
    ][:maximum_bars]
    _, atrs = true_ranges_and_atr(complete_rows(rows, cutoff))
    all_bars = complete_rows(rows, cutoff)
    index_by_identity = {
        (iso(row["open_at"]), iso(row["available_at"])): index
        for index, row in enumerate(all_bars)
    }
    for row in bars:
        index = index_by_identity[(iso(row["open_at"]), iso(row["available_at"]))]
        atr = atrs[index]
        if atr is None:
            continue
        tolerance = RETEST_TOLERANCE_ATR * atr
        held = (
            float(row["low"]) <= level + tolerance and float(row["close"]) > level
            if direction == "LONG"
            else float(row["high"]) >= level - tolerance and float(row["close"]) < level
        )
        if held:
            return {
                "retest_at": iso(row["available_at"]),
                "level": level,
                "atr": atr,
                "row_identity": canonical_hash(
                    ["RETEST", iso(row["open_at"]), iso(row["available_at"]), level, direction]
                ),
            }
    return None


def trigger_is_live(
    trigger: dict[str, Any],
    stream: dict[str, Any],
    decision_at: str,
    direction: Direction,
) -> bool:
    confirmation = parse_dt(trigger["confirmation_at"])
    m5_after = [
        row
        for row in complete_rows(stream["timeframes"]["5m"], decision_at)
        if parse_dt(row["available_at"]) > confirmation
    ]
    if len(m5_after) > TRIGGER_EXPIRY_M5_BARS:
        return False
    stop_reference = float(trigger["stop_reference"])
    for row in m5_after:
        invalid = (
            float(row["close"]) < stop_reference
            if direction == "LONG"
            else float(row["close"]) > stop_reference
        )
        if invalid:
            return False
    return True


def latest_internal_m15_balance(
    stream: dict[str, Any], cutoff: str, price: float
) -> dict[str, Any] | None:
    bars, boxes = balance_boxes(stream["timeframes"]["15m"], cutoff, "M15")
    eligible: list[BalanceBox] = []
    for box in boxes:
        later = [row for row in bars if parse_dt(row["available_at"]) > parse_dt(box.known_at)]
        if len(later) > BALANCE_EXPIRY_BARS:
            continue
        if not box.low <= price <= box.high:
            continue
        accepted_up = first_accepted_retest(
            stream["timeframes"]["5m"],
            known_at=box.known_at,
            cutoff=cutoff,
            level=box.high,
            direction="LONG",
        )
        accepted_down = first_accepted_retest(
            stream["timeframes"]["5m"],
            known_at=box.known_at,
            cutoff=cutoff,
            level=box.low,
            direction="SHORT",
        )
        if accepted_up is not None or accepted_down is not None:
            continue
        eligible.append(box)
    if not eligible:
        return None
    box = max(eligible, key=lambda item: (parse_dt(item.known_at), item.identity))
    return {
        "identity": box.identity,
        "timeframe": box.timeframe,
        "low": box.low,
        "high": box.high,
        "midpoint": (box.low + box.high) / 2,
        "known_at": box.known_at,
        "atr": box.atr,
    }


def _trigger_from_break_event(
    *,
    event: dict[str, Any],
    stream: dict[str, Any],
    decision_at: str,
    direction: Direction,
    family: str,
    controlling_balance: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    retest = held_retest_within(
        stream["timeframes"]["5m"],
        after=event["break_at"],
        cutoff=decision_at,
        level=float(event["broken_level"]),
        direction=direction,
    )
    if retest is None:
        return None
    references = [float(event["protected_level"]), float(event["origin_adverse"])]
    if controlling_balance is not None:
        references.append(
            float(controlling_balance["low"] if direction == "LONG" else controlling_balance["high"])
        )
    stop_reference = min(references) if direction == "LONG" else max(references)
    trigger = {
        "identity": canonical_hash(
            [family, event["identity"], retest["row_identity"], controlling_balance and controlling_balance["identity"]]
        ),
        "family": family,
        "break_at": event["break_at"],
        "confirmation_at": retest["retest_at"],
        "broken_level": float(event["broken_level"]),
        "protected_level": float(event["protected_level"]),
        "origin_adverse": float(event["origin_adverse"]),
        "stop_reference": stop_reference,
        "transition_atr": float(event["atr"]),
        "controlling_balance": controlling_balance,
        "evidence": {"break": event, "retest": retest},
    }
    return trigger if trigger_is_live(trigger, stream, decision_at, direction) else None


def boundary_sweep_trigger(
    stream: dict[str, Any],
    *,
    decision_at: str,
    direction: Direction,
    formation_at: str,
    balance: dict[str, Any],
) -> dict[str, Any] | None:
    bars = complete_rows(stream["timeframes"]["15m"], decision_at)
    _, atrs = true_ranges_and_atr(bars)
    boundary = float(balance["low"] if direction == "LONG" else balance["high"])
    reclaim_at: str | None = None
    sweep_extreme: float | None = None
    for index, bar in enumerate(bars):
        if parse_dt(bar["open_at"]) < parse_dt(formation_at):
            continue
        atr = atrs[index]
        if atr is None:
            continue
        swept = (
            float(bar["low"]) < boundary - 0.05 * atr
            if direction == "LONG"
            else float(bar["high"]) > boundary + 0.05 * atr
        )
        if sweep_extreme is None and swept:
            sweep_extreme = adverse_extreme(bar, direction)
            if (
                (direction == "LONG" and float(bar["close"]) > boundary)
                or (direction == "SHORT" and float(bar["close"]) < boundary)
            ):
                reclaim_at = iso(bar["available_at"])
                break
            continue
        if sweep_extreme is not None:
            held = (
                float(bar["close"]) > boundary
                if direction == "LONG"
                else float(bar["close"]) < boundary
            )
            if held:
                reclaim_at = iso(bar["available_at"])
                break
            # Only the same or next completed M15 candle may reclaim.
            sweep_extreme = None
    if reclaim_at is None or sweep_extreme is None:
        return None
    m5_events = structural_breaks(
        stream["timeframes"]["5m"],
        decision_at,
        "M5",
        direction,
        buffer_atr=TRANSITION_BUFFER_ATR,
        minimum_range_atr=0.80,
        minimum_body_ratio=0.55,
        after=reclaim_at,
    )
    triggers: list[dict[str, Any]] = []
    for event in m5_events:
        trigger = _trigger_from_break_event(
            event=event,
            stream=stream,
            decision_at=decision_at,
            direction=direction,
            family="BOUNDARY_SWEEP_RECLAIM",
            controlling_balance=balance,
        )
        if trigger is None:
            continue
        trigger["sweep_extreme"] = sweep_extreme
        trigger["stop_reference"] = (
            min(float(trigger["stop_reference"]), boundary, sweep_extreme)
            if direction == "LONG"
            else max(float(trigger["stop_reference"]), boundary, sweep_extreme)
        )
        triggers.append(trigger)
    return min(triggers, key=lambda item: (parse_dt(item["confirmation_at"]), item["identity"])) if triggers else None


def m15_break_retest_trigger(
    stream: dict[str, Any],
    *,
    decision_at: str,
    direction: Direction,
    formation_at: str,
) -> dict[str, Any] | None:
    events = structural_breaks(
        stream["timeframes"]["15m"],
        decision_at,
        "M15",
        direction,
        buffer_atr=TRANSITION_BUFFER_ATR,
        minimum_range_atr=0.90,
        minimum_body_ratio=0.55,
        after=formation_at,
    )
    triggers = [
        trigger
        for event in events
        if (
            trigger := _trigger_from_break_event(
                event=event,
                stream=stream,
                decision_at=decision_at,
                direction=direction,
                family="M15_BREAK_RETEST",
            )
        )
        is not None
    ]
    return min(triggers, key=lambda item: (parse_dt(item["confirmation_at"]), item["identity"])) if triggers else None


def internal_rotation_trigger(
    stream: dict[str, Any],
    *,
    decision_at: str,
    direction: Direction,
    formation_at: str,
    price: float,
) -> dict[str, Any] | None:
    balance = latest_internal_m15_balance(stream, decision_at, price)
    if balance is None:
        return None
    after = max(parse_dt(formation_at), parse_dt(balance["known_at"]))
    events = structural_breaks(
        stream["timeframes"]["5m"],
        decision_at,
        "M5",
        direction,
        buffer_atr=TRANSITION_BUFFER_ATR,
        minimum_range_atr=0.80,
        minimum_body_ratio=0.55,
        after=after,
    )
    triggers = [
        trigger
        for event in events
        if (
            trigger := _trigger_from_break_event(
                event=event,
                stream=stream,
                decision_at=decision_at,
                direction=direction,
                family="M5_INTERNAL_ROTATION_IN_M15_BALANCE",
                controlling_balance=balance,
            )
        )
        is not None
    ]
    return min(triggers, key=lambda item: (parse_dt(item["confirmation_at"]), item["identity"])) if triggers else None


def select_trigger(
    stream: dict[str, Any],
    *,
    decision_at: str,
    direction: Direction,
    formation_at: str,
    price: float,
    thesis: str,
    balance: dict[str, Any] | None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    if thesis in {"RANGE_ROTATION", "STRUCTURAL_REPAIR"} and balance is not None:
        trigger = boundary_sweep_trigger(
            stream,
            decision_at=decision_at,
            direction=direction,
            formation_at=formation_at,
            balance=balance,
        )
        if trigger is not None:
            candidates.append(trigger)
    if thesis != "RANGE_ROTATION":
        trigger = m15_break_retest_trigger(
            stream,
            decision_at=decision_at,
            direction=direction,
            formation_at=formation_at,
        )
        if trigger is not None:
            candidates.append(trigger)
        trigger = internal_rotation_trigger(
            stream,
            decision_at=decision_at,
            direction=direction,
            formation_at=formation_at,
            price=price,
        )
        if trigger is not None:
            candidates.append(trigger)
    if not candidates:
        return None
    precedence = {
        "BOUNDARY_SWEEP_RECLAIM": 0,
        "M15_BREAK_RETEST": 1,
        "M5_INTERNAL_ROTATION_IN_M15_BALANCE": 2,
    }
    return min(
        candidates,
        key=lambda item: (
            parse_dt(item["confirmation_at"]),
            precedence[item["family"]],
            parse_dt(item["break_at"]),
            item["identity"],
        ),
    )


def _active_target_zones(
    zones: Iterable[dict[str, Any]], fill: float, direction: Direction, sources: set[str]
) -> list[dict[str, Any]]:
    sign = direction_sign(direction)
    return sorted(
        [
            zone
            for zone in zones
            if zone["source"] in sources
            and zone["state"] in {"ACTIVE_UNTOUCHED", "ACTIVE_ENGAGED", "REACTIVATED_REVERSE"}
            and sign * (float(zone["level"]) - fill) > 0
        ],
        key=lambda zone: (sign * float(zone["level"]), 0 if zone["source"] == "H1" else 1, zone["identity"]),
    )


def _engaged_blocker(
    zones: Iterable[dict[str, Any]], fill: float, direction: Direction
) -> dict[str, Any] | None:
    sign = direction_sign(direction)
    blockers = []
    for zone in zones:
        if zone["source"] not in {"H4", "H1"} or zone["state"] not in {"ACTIVE_ENGAGED", "REACTIVATED_REVERSE"}:
            continue
        level = float(zone["level"])
        buffer = float(zone["buffer"])
        inside_or_penetrated = (
            fill >= level - buffer if direction == "LONG" else fill <= level + buffer
        )
        if inside_or_penetrated:
            blockers.append(zone)
    if not blockers:
        return None
    return min(blockers, key=lambda zone: (abs(float(zone["level"]) - fill), sign * float(zone["level"]), zone["identity"]))


def classify_predecision(
    *,
    decision: dict[str, Any],
    stream: dict[str, Any],
) -> dict[str, Any]:
    """Classify using no outcome/path field.

    Required decision keys are direction, submitted_at, fill_price,
    estimated_base_cost_usd and quantity_ounces.  The latter two supply the
    already-frozen per-ounce cost only.
    """

    direction: Direction = decision["direction"]
    decision_at = iso(decision["submitted_at"])
    fill = float(decision["fill_price"])
    blockers: list[dict[str, Any]] = []
    macro = macro_state(stream, decision_at, direction)
    event = event_lock_state(stream, decision_at, direction)
    zones = zone_registry(stream, decision_at, direction)
    damage = h4_damage_state(stream, decision_at, direction)
    repair = repair_evidence(stream, decision_at, direction, damage) if damage else None
    balances = active_balance_candidates(stream, decision_at, fill, direction)
    controlling_balance = balances[0] if balances else None
    progression = directional_progression(stream, decision_at, direction)

    if macro["state"] == "UNKNOWN":
        blockers.append({"gate": 1, "code": "UNKNOWN_CRITICAL_MACRO_CONTEXT", "evidence": macro})
    if event["locked"]:
        blockers.append({"gate": 6, "code": event["reason"], "evidence": event})

    thesis: str | None = None
    thesis_evidence: dict[str, Any] | None = None
    formation_members: list[str] = [macro["available_at"]] if macro.get("available_at") else []
    if damage is not None:
        if repair is None:
            blockers.append({"gate": 2, "code": "NO_TRADE_H4_DAMAGE_UNREPAIRED", "evidence": damage})
        else:
            thesis = "STRUCTURAL_REPAIR"
            thesis_evidence = {"damage": damage, "repair": repair}
            formation_members.append(repair["available_at"])
    elif controlling_balance is not None:
        formation_members.append(controlling_balance["known_at"])
        breakout = controlling_balance.get("accepted_breakout")
        location = float(controlling_balance["location"])
        inward_side = location <= 0.25 if direction == "LONG" else location >= 0.75
        outward_side = location >= 0.75 if direction == "LONG" else location <= 0.25
        if breakout is not None:
            thesis = "CONTINUATION_WITH_ROOM"
            thesis_evidence = {"balance": controlling_balance, "mode": "ACCEPTED_BREAKOUT_RETEST"}
            formation_members.append(breakout["retest_at"])
        elif inward_side:
            thesis = "RANGE_ROTATION"
            thesis_evidence = {"balance": controlling_balance, "mode": "OUTER_QUARTILE_INWARD_ROTATION"}
        elif outward_side:
            blockers.append(
                {
                    "gate": 3,
                    "code": "NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY",
                    "evidence": controlling_balance,
                }
            )
        else:
            blockers.append({"gate": 3, "code": "NO_TRADE_BALANCE_INTERIOR_WITHOUT_EVENT", "evidence": controlling_balance})
    elif progression is not None:
        thesis = "CONTINUATION_WITH_ROOM"
        thesis_evidence = {"progression": progression, "mode": "INTACT_DIRECTIONAL_PROGRESSION"}
        formation_members.append(progression["available_at"])
    else:
        blockers.append({"gate": 5, "code": "NO_TRADE_UNCLASSIFIED_AUCTION", "evidence": None})

    if thesis == "CONTINUATION_WITH_ROOM" and macro["state"] == "OPPOSED":
        blockers.append({"gate": 7, "code": "CONTINUATION_MACRO_OPPOSED", "evidence": macro})

    formation_at = iso(max((parse_dt(item) for item in formation_members), default=parse_dt(decision_at)))
    trigger = None
    if thesis is not None:
        trigger = select_trigger(
            stream,
            decision_at=decision_at,
            direction=direction,
            formation_at=formation_at,
            price=fill,
            thesis=thesis,
            balance=controlling_balance,
        )
        if trigger is None:
            blockers.append({"gate": 2, "code": "NO_LIVE_FROZEN_TRIGGER", "evidence": {"thesis": thesis}})

    stop: float | None = None
    if trigger is not None:
        m15_atr = latest_atr(stream["timeframes"]["15m"], decision_at)
        if m15_atr is None:
            blockers.append({"gate": 1, "code": "M15_ATR_UNAVAILABLE", "evidence": None})
        else:
            stop = (
                float(trigger["stop_reference"]) - 0.10 * m15_atr
                if direction == "LONG"
                else float(trigger["stop_reference"]) + 0.10 * m15_atr
            )

    target: float | None = None
    first_realization: float | None = None
    target_zone: dict[str, Any] | None = None
    active_h1 = _active_target_zones(zones, fill, direction, {"H1"})
    active_h4 = _active_target_zones(zones, fill, direction, {"H4"})
    if thesis == "CONTINUATION_WITH_ROOM":
        choices = active_h1 if active_h1 else active_h4
        if choices:
            target_zone = choices[0]
            target = float(target_zone["level"])
    elif thesis == "RANGE_ROTATION" and controlling_balance is not None:
        first_realization = float(controlling_balance["midpoint"])
        target = float(controlling_balance["high"] if direction == "LONG" else controlling_balance["low"])
    elif thesis == "STRUCTURAL_REPAIR" and damage is not None:
        choices = []
        broken_reference = float(damage["broken_reference"])
        if direction_sign(direction) * (broken_reference - fill) > 0:
            choices.append((broken_reference, None))
        choices.extend((float(zone["level"]), zone) for zone in active_h1)
        if choices:
            choices.sort(key=lambda item: direction_sign(direction) * (item[0] - fill))
            target, target_zone = choices[0]
    if target is None:
        blockers.append({"gate": 2, "code": "NO_ACTIVE_FORWARD_TARGET", "evidence": None})

    engaged = _engaged_blocker(zones, fill, direction)
    if engaged is not None:
        blockers.append({"gate": 5, "code": "FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE", "evidence": engaged})

    sign = direction_sign(direction)
    if stop is not None and sign * (fill - stop) <= 0:
        blockers.append({"gate": 2, "code": "STOP_NOT_ADVERSE_TO_FILL", "evidence": {"fill": fill, "stop": stop}})
    if target is not None and sign * (target - fill) <= 0:
        blockers.append({"gate": 3, "code": "TARGET_NOT_FORWARD_OF_FILL", "evidence": {"fill": fill, "target": target}})
    if first_realization is not None and sign * (first_realization - fill) <= 0:
        blockers.append(
            {"gate": 3, "code": "RANGE_MIDPOINT_NOT_FORWARD_OF_FILL", "evidence": {"fill": fill, "midpoint": first_realization}}
        )

    original_quantity = int(decision["quantity_ounces"])
    cost_per_ounce = float(decision["estimated_base_cost_usd"]) / original_quantity
    quantity = 0
    planned_loss_per_ounce: float | None = None
    if stop is not None:
        planned_loss_per_ounce = abs(fill - stop) + cost_per_ounce
        quantity = math.floor(RISK_BUDGET_USD / planned_loss_per_ounce)
        if quantity < 1:
            blockers.append(
                {
                    "gate": 4,
                    "code": "MINIMUM_ONE_OUNCE_EXCEEDS_RISK_CAP",
                    "evidence": {"planned_loss_per_ounce": planned_loss_per_ounce},
                }
            )

    blockers.sort(key=lambda item: (int(item["gate"]), item["code"]))
    admitted = not blockers
    result = {
        "ruleset": RULESET,
        "decision_at": decision_at,
        "direction": direction,
        "fill": fill,
        "admitted": admitted,
        "primary_disposition": "ADMIT" if admitted else blockers[0]["code"],
        "blockers": blockers,
        "thesis": thesis,
        "thesis_evidence": thesis_evidence,
        "macro": macro,
        "event": event,
        "damage": damage,
        "repair": repair,
        "controlling_balance": controlling_balance,
        "progression": progression,
        "formation_at": formation_at,
        "trigger": trigger,
        "zones": zones,
        "stop": stop,
        "target": target,
        "first_realization": first_realization,
        "target_zone": target_zone,
        "cost_per_ounce": cost_per_ounce,
        "planned_loss_per_ounce": planned_loss_per_ounce,
        "quantity_ounces": quantity,
        "classification_hash": None,
    }
    result["classification_hash"] = canonical_hash({key: value for key, value in result.items() if key != "classification_hash"})
    return result


def _first_m1_index_at_or_after(rows: Sequence[dict[str, Any]], timestamp: str) -> int | None:
    target = parse_dt(timestamp)
    for index, row in enumerate(rows):
        if parse_dt(row["open_at"]) >= target:
            return index
    return None


def _opposing_m15_events(
    stream: dict[str, Any], after: str, cutoff: str, direction: Direction
) -> list[dict[str, Any]]:
    opposite: Direction = "SHORT" if direction == "LONG" else "LONG"
    return structural_breaks(
        stream["timeframes"]["15m"],
        cutoff,
        "M15",
        opposite,
        buffer_atr=BREAK_BUFFER_ATR,
        after=after,
    )


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
    choices = [item for item in swings if item["kind"] == wanted]
    if not choices:
        return None
    swing = choices[-1]
    atr = latest_atr(rows, cutoff)
    if atr is None:
        return None
    return (
        float(swing["level"]) - BREAK_BUFFER_ATR * atr
        if direction == "LONG"
        else float(swing["level"]) + BREAK_BUFFER_ATR * atr
    )


def _finalize_economic_result(
    *,
    classification: dict[str, Any],
    legs: list[dict[str, Any]],
    final_at: str,
    path_high: float,
    path_low: float,
) -> dict[str, Any]:
    direction: Direction = classification["direction"]
    sign = direction_sign(direction)
    fill = float(classification["fill"])
    initial_quantity = int(classification["quantity_ounces"])
    gross = sum(
        sign * (float(leg["exit_price"]) - fill) * int(leg["quantity_ounces"])
        for leg in legs
    )
    cost = float(classification["cost_per_ounce"]) * initial_quantity
    net = gross - cost
    stressed_net = gross - 1.5 * cost
    favourable = (path_high - fill) if direction == "LONG" else (fill - path_low)
    adverse = (fill - path_low) if direction == "LONG" else (path_high - fill)
    return {
        "executed": True,
        "resolution": legs[-1]["resolution"] if legs else "UNKNOWN",
        "final_at": final_at,
        "legs": legs,
        "gross_usd": gross,
        "cost_usd": cost,
        "net_usd": net,
        "net_r50": net / RISK_BUDGET_USD,
        "stressed_1_5x_cost_net_usd": stressed_net,
        "stressed_1_5x_cost_r50": stressed_net / RISK_BUDGET_USD,
        "mfe_r50": favourable * initial_quantity / RISK_BUDGET_USD,
        "mae_r50": adverse * initial_quantity / RISK_BUDGET_USD,
        "positive": net > 0,
        "result_hash": None,
    }


def simulate_policy_path(
    *,
    classification: dict[str, Any],
    stream: dict[str, Any],
    fill_at: str,
) -> dict[str, Any]:
    """Resolve an already-sealed classification on its post-fill path."""

    if not classification["admitted"]:
        return {
            "executed": False,
            "resolution": classification["primary_disposition"],
            "final_at": None,
            "legs": [],
            "gross_usd": 0.0,
            "cost_usd": 0.0,
            "net_usd": 0.0,
            "net_r50": 0.0,
            "stressed_1_5x_cost_net_usd": 0.0,
            "stressed_1_5x_cost_r50": 0.0,
            "mfe_r50": 0.0,
            "mae_r50": 0.0,
            "positive": False,
            "result_hash": canonical_hash([classification["classification_hash"], "NO_TRADE"]),
        }
    direction: Direction = classification["direction"]
    sign = direction_sign(direction)
    fill = float(classification["fill"])
    stop = float(classification["stop"])
    target = float(classification["target"])
    quantity = int(classification["quantity_ounces"])
    risk_price = abs(fill - stop)
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
    m15_index = {(iso(row["open_at"]), iso(row["available_at"])): index for index, row in enumerate(m15)}
    opposing = _opposing_m15_events(stream, fill_at, stream["end_exclusive"], direction)
    pending_structure = list(opposing)
    structure_pointer = 0
    legs: list[dict[str, Any]] = []
    remaining = quantity
    current_stop = stop
    armed_at: str | None = None
    midpoint_touched = False
    target_touched = False
    target_touch_m15: dict[str, Any] | None = None
    runner_active = False
    runner_decision_complete = False
    last_m15_processed: str | None = None
    path_high = fill
    path_low = fill
    thesis = str(classification["thesis"])
    midpoint = classification.get("first_realization")
    runner_quantity = math.floor(0.20 * quantity) if thesis == "CONTINUATION_WITH_ROOM" else 0
    core_quantity = quantity - runner_quantity

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

        # Completed M15 evidence becomes actionable at this M1 open.
        completed_since = [
            bar
            for bar in m15
            if parse_dt(bar["available_at"]) <= parse_dt(now)
            and parse_dt(bar["available_at"]) > parse_dt(last_m15_processed or fill_at)
        ]
        for completed in completed_since:
            last_m15_processed = iso(completed["available_at"])
            if thesis == "RANGE_ROTATION" and midpoint_touched and remaining > 0:
                beyond_mid = (
                    float(completed["close"]) > float(midpoint)
                    if direction == "LONG"
                    else float(completed["close"]) < float(midpoint)
                )
                if beyond_mid:
                    cost_cover = fill + sign * float(classification["cost_per_ounce"])
                    current_stop = max(current_stop, cost_cover) if direction == "LONG" else min(current_stop, cost_cover)
            if (
                target_touched
                and not runner_decision_complete
                and target_touch_m15 is not None
                and iso(completed["open_at"]) == iso(target_touch_m15["open_at"])
            ):
                index = m15_index[(iso(completed["open_at"]), iso(completed["available_at"]))]
                atr = m15_atrs[index]
                accepted = atr is not None and (
                    float(completed["close"]) >= target + 0.10 * atr
                    if direction == "LONG"
                    else float(completed["close"]) <= target - 0.10 * atr
                )
                runner_decision_complete = True
                if accepted:
                    runner_active = True
                elif remaining > 0:
                    append_leg(remaining, open_price, now, "RUNNER_NO_TARGET_ACCEPTANCE")
            if runner_active and remaining > 0:
                proposed = _latest_runner_stop(stream, iso(completed["open_at"]), direction)
                if proposed is not None:
                    current_stop = max(current_stop, proposed) if direction == "LONG" else min(current_stop, proposed)

        if remaining <= 0:
            break

        # Gap and intrabar stop are first by frozen ambiguity rule.
        gap_stopped = open_price <= current_stop if direction == "LONG" else open_price >= current_stop
        if gap_stopped:
            append_leg(remaining, open_price, now, "GAP_STOP")
            break
        stop_touched = low <= current_stop if direction == "LONG" else high >= current_stop
        if stop_touched:
            append_leg(remaining, current_stop, now, "STRUCTURAL_STOP")
            break

        # A genuine opposing M15 break executes at this open. Continuation
        # requires prior +1R arming; repair/range do not.
        while structure_pointer < len(pending_structure) and parse_dt(pending_structure[structure_pointer]["break_at"]) <= parse_dt(now):
            event = pending_structure[structure_pointer]
            structure_pointer += 1
            permitted = thesis != "CONTINUATION_WITH_ROOM" or (
                armed_at is not None and parse_dt(event["break_at"]) > parse_dt(armed_at)
            )
            if permitted and not target_touched:
                append_leg(remaining, open_price, now, "OPPOSING_M15_STRUCTURE_EXIT")
                break
        if remaining <= 0:
            break

        if thesis == "CONTINUATION_WITH_ROOM" and armed_at is None:
            armed = high >= fill + risk_price if direction == "LONG" else low <= fill - risk_price
            if armed:
                armed_at = now

        if thesis == "RANGE_ROTATION" and not midpoint_touched and midpoint is not None:
            reached_mid = high >= float(midpoint) if direction == "LONG" else low <= float(midpoint)
            if reached_mid:
                midpoint_touched = True
                partial = math.ceil(0.50 * quantity)
                append_leg(min(partial, remaining), float(midpoint), now, "RANGE_MIDPOINT_REALIZATION")
                if remaining <= 0:
                    break

        reached_target = high >= target if direction == "LONG" else low <= target
        if reached_target:
            if thesis == "CONTINUATION_WITH_ROOM":
                if not target_touched:
                    target_touched = True
                    target_touch_m15 = _containing_bar(m15, now)
                    append_leg(min(core_quantity, remaining), target, now, "H1_CORE_TARGET")
                    if runner_quantity == 0 and remaining > 0:
                        append_leg(remaining, target, now, "H1_TARGET_NO_WHOLE_OUNCE_RUNNER")
            else:
                append_leg(remaining, target, now, f"{thesis}_TARGET")
        if remaining <= 0:
            break

    if remaining > 0:
        last = path[-1]
        append_leg(remaining, float(last["close"]), last["close_at"], "UTC_DAY_TIME_EXIT")
    final_at = legs[-1]["exit_at"]
    result = _finalize_economic_result(
        classification=classification,
        legs=legs,
        final_at=final_at,
        path_high=path_high,
        path_low=path_low,
    )
    result["result_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "result_hash"}
    )
    return result
