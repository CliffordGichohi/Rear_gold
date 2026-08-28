"""Deterministic lifecycle for the exposed day-by-day auction correction.

The functions in this module are deliberately free of model fitting and file I/O.
They operate only on completed bars supplied by the caller and implement the
frozen confirmation, pre-entry invalidation, target-room, and M5 break-even
rules from Gold Day-by-Day Auction-Confirmation Exposed Regression V1.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
)

Direction = Literal["LONG", "SHORT"]


def direction_sign(direction: Direction) -> int:
    return 1 if direction == "LONG" else -1


def m5_pair_qualifies(
    failed_auction: dict[str, Any],
    progression: dict[str, Any],
    direction: Direction,
) -> bool:
    """Return whether an adjacent completed M5 pair meets the frozen pattern."""

    if not failed_auction.get("complete") or not progression.get("complete"):
        return False
    if parse_dt(progression["open_at"]) != parse_dt(failed_auction["close_at"]):
        return False

    a_open = float(failed_auction["open"])
    a_high = float(failed_auction["high"])
    a_low = float(failed_auction["low"])
    a_close = float(failed_auction["close"])
    b_open = float(progression["open"])
    b_high = float(progression["high"])
    b_low = float(progression["low"])
    b_close = float(progression["close"])
    midpoint = (a_high + a_low) / 2.0

    if direction == "LONG":
        return (
            a_close > a_open
            and a_low < min(a_open, a_close)
            and a_close >= midpoint
            and b_low < a_close
            and b_low > a_low
            and b_close > b_open
            and b_close > a_close
        )
    return (
        a_close < a_open
        and a_high > max(a_open, a_close)
        and a_close <= midpoint
        and b_high > a_close
        and b_high < a_high
        and b_close < b_open
        and b_close < a_close
    )


def find_first_m5_confirmation(
    rows: Sequence[dict[str, Any]],
    *,
    signal_at: str | datetime,
    session_end: str | datetime,
    direction: Direction,
) -> dict[str, Any] | None:
    """Find the first qualifying adjacent pair after the frozen signal."""

    signal = parse_dt(signal_at)
    end = parse_dt(session_end)
    eligible = [
        row
        for row in complete_rows(rows, end)
        if signal < parse_dt(row["available_at"]) <= end
        and parse_dt(row["open_at"]) < end
    ]
    for failed_auction, progression in zip(eligible, eligible[1:], strict=False):
        if m5_pair_qualifies(failed_auction, progression, direction):
            payload = {
                "direction": direction,
                "failed_auction_open_at": iso(failed_auction["open_at"]),
                "failed_auction_available_at": iso(failed_auction["available_at"]),
                "progression_open_at": iso(progression["open_at"]),
                "confirmation_at": iso(progression["available_at"]),
                "failed_auction_bar_hash": _bar_hash(failed_auction),
                "progression_bar_hash": _bar_hash(progression),
            }
            payload["confirmation_hash"] = canonical_hash(payload)
            return payload
    return None


def _bar_hash(row: dict[str, Any]) -> str:
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


def first_complete_m1_after(
    rows: Sequence[dict[str, Any]], checkpoint_at: str | datetime
) -> dict[str, Any] | None:
    point = parse_dt(checkpoint_at)
    return next(
        (
            row
            for row in complete_rows(rows, datetime.max.replace(tzinfo=point.tzinfo))
            if parse_dt(row["open_at"]) > point
        ),
        None,
    )


def pre_entry_disposition(
    rows: Sequence[dict[str, Any]],
    *,
    signal_at: str | datetime,
    fill_at: str | datetime,
    stop: float,
    target: float,
    direction: Direction,
) -> dict[str, Any]:
    """Apply stop-first first passage between signal and delayed entry."""

    signal = parse_dt(signal_at)
    fill = parse_dt(fill_at)
    for row in complete_rows(rows, fill):
        opened = parse_dt(row["open_at"])
        if opened < signal or opened >= fill:
            continue
        high = float(row["high"])
        low = float(row["low"])
        stop_touched = low <= stop if direction == "LONG" else high >= stop
        target_touched = high >= target if direction == "LONG" else low <= target
        if stop_touched:
            return {
                "disposition": "ORIGINAL_STOP_TOUCHED_PRE_ENTRY",
                "at": iso(row["open_at"]),
                "same_bar_target_touch": target_touched,
                "bar_hash": _bar_hash(row),
            }
        if target_touched:
            return {
                "disposition": "ORIGINAL_TARGET_TOUCHED_PRE_ENTRY",
                "at": iso(row["open_at"]),
                "same_bar_target_touch": False,
                "bar_hash": _bar_hash(row),
            }
    return {
        "disposition": "CLEAR_TO_DELAYED_ENTRY",
        "at": None,
        "same_bar_target_touch": False,
        "bar_hash": None,
    }


def target_room(
    *, fill: float, stop: float, target: float, direction: Direction
) -> dict[str, Any]:
    sign = direction_sign(direction)
    structural_risk = sign * (float(fill) - float(stop))
    reward = sign * (float(target) - float(fill))
    valid = (
        all(math.isfinite(value) for value in (fill, stop, target))
        and structural_risk > 0
        and reward > 0
    )
    room = reward / structural_risk if valid else None
    return {
        "geometry_valid": valid,
        "structural_risk_per_ounce": structural_risk if valid else None,
        "target_room_r": room,
        "passes_1p5r": bool(valid and room is not None and room >= 1.5),
    }


@dataclass(frozen=True)
class BreakEvenOverlay:
    activated: bool
    activation_at: str | None
    exit_at: str | None
    disposition: str
    changed: bool

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "activated": self.activated,
            "activation_at": self.activation_at,
            "exit_at": self.exit_at,
            "disposition": self.disposition,
            "changed": self.changed,
        }
        payload["overlay_hash"] = canonical_hash(payload)
        return payload


def m5_close_one_r_break_even(
    *,
    m1_rows: Sequence[dict[str, Any]],
    m5_rows: Sequence[dict[str, Any]],
    fill_at: str | datetime,
    baseline_final_at: str | datetime,
    fill: float,
    stop: float,
    target: float,
    cost_per_ounce: float,
    direction: Direction,
) -> dict[str, Any]:
    """Evaluate the frozen M5-close +1R net-break-even overlay."""

    opened = parse_dt(fill_at)
    final = parse_dt(baseline_final_at)
    sign = direction_sign(direction)
    risk = abs(float(fill) - float(stop))
    activation_level = float(fill) + sign * risk
    activations = [
        row
        for row in complete_rows(m5_rows, final)
        if opened < parse_dt(row["available_at"]) <= final
        and sign * (float(row["close"]) - activation_level) >= 0
    ]
    if not activations:
        return BreakEvenOverlay(False, None, None, "UNCHANGED", False).as_dict()

    activation_at = parse_dt(activations[0]["available_at"])
    # The baseline final timestamp is the opening timestamp of its resolving M1
    # bar. Include that bar even though its ``available_at`` is one minute later:
    # this is outcome resolution, not a point-in-time decision input.
    path = [
        row
        for row in m1_rows
        if row.get("complete") is True
        and opened <= parse_dt(row["open_at"]) <= final
    ]
    target_before_activation = any(
        parse_dt(row["open_at"]) < activation_at
        and sign * (float(row["high"] if direction == "LONG" else row["low"]) - target)
        >= 0
        for row in path
    )
    if target_before_activation:
        return BreakEvenOverlay(
            True, iso(activation_at), None, "TARGET_PRECEDED_OVERLAY", False
        ).as_dict()

    break_even = float(fill) + sign * float(cost_per_ounce)
    for row in path:
        if parse_dt(row["open_at"]) < activation_at:
            continue
        stop_touched = (
            float(row["low"]) <= break_even
            if direction == "LONG"
            else float(row["high"]) >= break_even
        )
        target_touched = (
            float(row["high"]) >= target
            if direction == "LONG"
            else float(row["low"]) <= target
        )
        # Ambiguous-bar stop-first is retained.
        if stop_touched:
            return BreakEvenOverlay(
                True,
                iso(activation_at),
                iso(row["open_at"]),
                "M5_1R_NET_BREAK_EVEN",
                True,
            ).as_dict()
        if target_touched:
            return BreakEvenOverlay(
                True, iso(activation_at), None, "TARGET_PRECEDED_OVERLAY", False
            ).as_dict()
    return BreakEvenOverlay(True, iso(activation_at), None, "UNCHANGED", False).as_dict()
