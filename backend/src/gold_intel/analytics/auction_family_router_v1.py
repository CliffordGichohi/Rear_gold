"""Pure, deterministic routes for Auction Family Router V1."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    BREAK_BUFFER_ATR,
    RETEST_TOLERANCE_ATR,
    TICK_FLOOR,
    canonical_hash,
    complete_rows,
    event_is_active,
    iso,
    parse_dt,
    structural_breaks,
    true_ranges_and_atr,
)

Direction = Literal["LONG", "SHORT"]


def range_reclaim_qualifies(row: dict[str, Any], direction: Direction) -> bool:
    """Frozen one-bar failed-auction/reclaim definition."""

    if row.get("complete") is not True:
        return False
    opened = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    closed = float(row["close"])
    midpoint = (high + low) / 2.0
    if direction == "LONG":
        return closed > opened and low < min(opened, closed) and closed >= midpoint
    return closed < opened and high > max(opened, closed) and closed <= midpoint


def first_range_reclaim(
    rows: Sequence[dict[str, Any]],
    *,
    signal_at: str | datetime,
    session_end: str | datetime,
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
        if not range_reclaim_qualifies(row, direction):
            continue
        payload = {
            "route": "RANGE_ROTATION_RECLAIM",
            "direction": direction,
            "confirmation_at": iso(row["available_at"]),
            "bar_open_at": iso(row["open_at"]),
            "within_route_occurrence": occurrence,
            "bar_identity": bar_identity(row),
        }
        payload["route_hash"] = canonical_hash(payload)
        return payload
    return None


def latest_active_m15_break(
    rows: Sequence[dict[str, Any]],
    *,
    signal_at: str | datetime,
    direction: Direction,
) -> dict[str, Any] | None:
    events = structural_breaks(rows, signal_at, "M15", direction)
    active = [event for event in events if event_is_active(event, rows, signal_at)]
    return active[-1] if active else None


def first_structural_repair_retest(
    m5_rows: Sequence[dict[str, Any]],
    *,
    event: dict[str, Any],
    signal_at: str | datetime,
    session_end: str | datetime,
    direction: Direction,
    maximum_bars: int = 12,
) -> dict[str, Any]:
    """Return the first family-specific M5 repair retest or exact failure."""

    signal = parse_dt(signal_at)
    end = parse_dt(session_end)
    all_bars = complete_rows(m5_rows, end)
    _, atrs = true_ranges_and_atr(all_bars)
    index_by_identity = {
        (iso(row["open_at"]), iso(row["available_at"])): index
        for index, row in enumerate(all_bars)
    }
    eligible = [
        row
        for row in all_bars
        if signal < parse_dt(row["available_at"]) <= end
        and parse_dt(row["open_at"]) < end
    ][:maximum_bars]
    protected = float(event["protected_level"])
    broken = float(event["broken_level"])
    invalidation_buffer = max(BREAK_BUFFER_ATR * float(event["atr"]), TICK_FLOOR)

    for occurrence, row in enumerate(eligible, start=1):
        close = float(row["close"])
        invalid = (
            close < protected - invalidation_buffer
            if direction == "LONG"
            else close > protected + invalidation_buffer
        )
        if invalid:
            return {
                "route": "STRUCTURAL_REPAIR_RETEST",
                "disposition": "REPAIR_STRUCTURE_INVALIDATED",
                "confirmation_at": None,
                "invalidated_at": iso(row["available_at"]),
                "event_identity": event["identity"],
                "bar_identity": bar_identity(row),
            }
        index = index_by_identity[(iso(row["open_at"]), iso(row["available_at"]))]
        atr = atrs[index]
        if atr is None or atr <= 0:
            continue
        tolerance = max(RETEST_TOLERANCE_ATR * atr, TICK_FLOOR)
        opened = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        held = (
            low <= broken + tolerance and close > broken and close > opened
            if direction == "LONG"
            else high >= broken - tolerance and close < broken and close < opened
        )
        if not held:
            continue
        payload = {
            "route": "STRUCTURAL_REPAIR_RETEST",
            "disposition": "CONFIRMED",
            "direction": direction,
            "confirmation_at": iso(row["available_at"]),
            "bar_open_at": iso(row["open_at"]),
            "within_route_occurrence": occurrence,
            "event_identity": event["identity"],
            "broken_level": broken,
            "protected_level": protected,
            "tolerance": tolerance,
            "bar_identity": bar_identity(row),
        }
        payload["route_hash"] = canonical_hash(payload)
        return payload
    return {
        "route": "STRUCTURAL_REPAIR_RETEST",
        "disposition": "NO_REPAIR_RETEST_WITHIN_12_M5",
        "confirmation_at": None,
        "invalidated_at": None,
        "event_identity": event["identity"],
        "bar_identity": None,
    }


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

