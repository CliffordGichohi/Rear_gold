"""Causal H1-governed M15/M5 trade-plan scanner.

The scanner stops at the entry plan. It never reads post-decision prices and
contains no outcome, PnL, MFE, MAE, or performance calculation.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any, Literal

from gold_intel.analytics.auction_liquidity_range_semantics_v1 import (
    RANGE_MAX_WIDTH_ATR,
    RANGE_REJECTION_PROXIMITY_ATR,
    RANGE_WINDOW_BARS,
    active_range_context,
    build_timeframe_inventory,
    structure_state,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (
    TICK_FLOOR,
    canonical_hash,
    complete_rows,
    confirmed_swings,
    iso,
    parse_dt,
    true_ranges_and_atr,
)
from gold_intel.analytics.early_m5_curvature_entry_v1 import trigger_direction
from gold_intel.analytics.h1_governed_trade_plan_v1 import (
    assert_outcome_blind,
    compile_trade_plan,
)
from gold_intel.analytics.swing_curvature_entry_v1 import (
    curvature_zone,
    directional_half_close,
    overlaps_zone,
    retracement_zone,
)

Direction = Literal["LONG", "SHORT"]

RULESET = "GOLD_H1_GOVERNED_TRADE_SCANNER_V1"
START = "2022-01-01T00:00:00Z"
END = "2022-02-01T00:00:00Z"
RETEST_EXPIRY_BARS = 3


class PointInTimeInventoryTimeline:
    """Precompute immutable swing lifecycles without changing cutoff semantics."""

    def __init__(
        self, rows: Sequence[dict[str, Any]], *, end: str, timeframe: str
    ) -> None:
        self.timeframe = timeframe_label(timeframe)
        self.rows, self.swings = confirmed_swings(rows, end, self.timeframe)
        self.available = [parse_dt(row["available_at"]) for row in self.rows]
        self.row_by_open = {iso(row["open_at"]): row for row in self.rows}
        _ranges, self.atrs = true_ranges_and_atr(self.rows)
        self.lifecycle: dict[str, dict[str, str | None]] = {}
        for swing in self.swings:
            level = float(swing["level"])
            kind = str(swing["kind"])
            pivot_index = int(swing["pivot_index"])
            engaged_at: str | None = None
            consumed_at: str | None = None
            for row in self.rows[pivot_index + 1 :]:
                traded = float(row["high"] if kind == "HIGH" else row["low"])
                engaged = traded >= level if kind == "HIGH" else traded <= level
                consumed = traded > level if kind == "HIGH" else traded < level
                if engaged and engaged_at is None:
                    engaged_at = iso(row["available_at"])
                if consumed:
                    consumed_at = iso(row["available_at"])
                    break
            self.lifecycle[str(swing["identity"])] = {
                "engaged_at": engaged_at,
                "consumed_at": consumed_at,
            }

    def completed_count(self, cutoff: str) -> int:
        return bisect_right(self.available, parse_dt(cutoff))

    def location_breached(
        self,
        *,
        direction: Direction,
        known_at: str,
        cutoff: str,
        invalidation: float,
    ) -> bool:
        start = bisect_right(self.available, parse_dt(known_at))
        end = self.completed_count(cutoff)
        return any(
            (
                float(row["low"]) < invalidation
                if direction == "LONG"
                else float(row["high"]) > invalidation
            )
            for row in self.rows[start:end]
        )

    def inventory(self, cutoff: str) -> dict[str, Any]:
        end = parse_dt(cutoff)
        count = self.completed_count(cutoff)
        states: list[dict[str, Any]] = []
        for swing in self.swings:
            if parse_dt(swing["detected_at"]) > end:
                continue
            lifecycle = self.lifecycle[str(swing["identity"])]
            engaged_at = lifecycle["engaged_at"]
            consumed_at = lifecycle["consumed_at"]
            if consumed_at is not None and parse_dt(consumed_at) <= end:
                state = "CONSUMED"
            elif engaged_at is not None and parse_dt(engaged_at) <= end:
                state = "UNCONSUMED_ENGAGED"
            else:
                state = "UNCONSUMED_UNTOUCHED"
            state_payload: dict[str, Any] = {
                    "identity": str(swing["identity"]),
                    "kind": str(swing["kind"]),
                    "timeframe": self.timeframe,
                    "pivot_at": iso(swing["pivot_at"]),
                    "pivot_candle_completed_at": iso(
                        self.rows[int(swing["pivot_index"])]["available_at"]
                    ),
                    "known_at": iso(swing["detected_at"]),
                    "level": float(swing["level"]),
                    "state": state,
                    "engaged_at": (
                        engaged_at
                        if engaged_at is not None and parse_dt(engaged_at) <= end
                        else None
                    ),
                    "consumed_at": (
                        consumed_at
                        if consumed_at is not None and parse_dt(consumed_at) <= end
                        else None
                    ),
                    "strict_beyond_rule": (
                        "LATER_HIGH_GT_LEVEL"
                        if swing["kind"] == "HIGH"
                        else "LATER_LOW_LT_LEVEL"
                    ),
                    "close_or_atr_required": False,
                    "epistemic_status": "CALCULATED_FROM_OBSERVED_TRADED_PRICE_EXTREMA",
            }
            state_payload["lifecycle_sha256"] = canonical_hash(state_payload)
            states.append(state_payload)
        payload: dict[str, Any] = {
            "timeframe": self.timeframe,
            "cutoff": iso(cutoff),
            "completed_bars": count,
            "known_pivots": len(states),
            "states": states,
            "state_counts": {
                name: sum(item["state"] == name for item in states)
                for name in (
                    "UNCONSUMED_UNTOUCHED",
                    "UNCONSUMED_ENGAGED",
                    "CONSUMED",
                    "UNKNOWN_TECHNICAL",
                )
            },
        }
        return payload

    def active_range(
        self,
        *,
        cutoff: str,
        direction: Direction,
        price: float,
        inventory: Mapping[str, Any],
    ) -> dict[str, Any]:
        def absent(reason: str, **details: Any) -> dict[str, Any]:
            return {"state": "NO_ACTIVE_RANGE", "reason": reason, **details}

        count = self.completed_count(cutoff)
        if count < RANGE_WINDOW_BARS:
            return absent("INSUFFICIENT_COMPLETED_BARS", completed_bars=count)
        atr = self.atrs[count - 1]
        if atr is None or atr <= 0:
            return absent("CURRENT_ATR_UNAVAILABLE")
        start_index = count - RANGE_WINDOW_BARS
        states = {str(item["identity"]): item for item in inventory["states"]}
        members = [
            states[str(swing["identity"])]
            for swing in self.swings
            if int(swing["pivot_index"]) >= start_index
            and int(swing["pivot_index"]) < count
            and parse_dt(swing["detected_at"]) <= parse_dt(cutoff)
            and str(swing["identity"]) in states
        ]
        highs = [item for item in members if item["kind"] == "HIGH"]
        lows = [item for item in members if item["kind"] == "LOW"]
        if len(highs) < 2 or len(lows) < 2:
            return absent(
                "INSUFFICIENT_TWO_SIDED_CONFIRMED_PIVOTS",
                highs=len(highs),
                lows=len(lows),
            )

        upper_level = max(float(item["level"]) for item in highs)
        lower_level = min(float(item["level"]) for item in lows)
        upper = max(
            [item for item in highs if float(item["level"]) == upper_level],
            key=lambda item: (parse_dt(item["known_at"]), item["identity"]),
        )
        lower = max(
            [item for item in lows if float(item["level"]) == lower_level],
            key=lambda item: (parse_dt(item["known_at"]), item["identity"]),
        )
        width = upper_level - lower_level
        if width <= 0:
            return absent("NONPOSITIVE_BOUNDARY_WIDTH")
        width_atr = width / float(atr)
        if width_atr > RANGE_MAX_WIDTH_ATR:
            return absent("BOUNDARY_WIDTH_EXCEEDS_LIMIT", width_atr=width_atr)
        proximity = RANGE_REJECTION_PROXIMITY_ATR * float(atr)
        upper_interactions = [
            item for item in highs if float(item["level"]) >= upper_level - proximity
        ]
        lower_interactions = [
            item for item in lows if float(item["level"]) <= lower_level + proximity
        ]
        if len(upper_interactions) < 2 or len(lower_interactions) < 2:
            return absent(
                "REPEATED_BOUNDARY_REJECTION_NOT_CONFIRMED",
                upper_interactions=len(upper_interactions),
                lower_interactions=len(lower_interactions),
            )
        if upper["state"] == "CONSUMED" or lower["state"] == "CONSUMED":
            return absent("EXACT_RANGE_BOUNDARY_CONSUMED")
        if not (lower_level <= price <= upper_level):
            return absent("DECISION_PRICE_OUTSIDE_BOUNDARIES")
        midpoint = (lower_level + upper_level) / 2.0
        inward = (direction == "LONG" and price <= midpoint) or (
            direction == "SHORT" and price >= midpoint
        )
        known_at = max(
            [item["known_at"] for item in (*upper_interactions, *lower_interactions)],
            key=parse_dt,
        )
        payload: dict[str, Any] = {
            "state": "ACTIVE_RANGE",
            "timeframe": self.timeframe,
            "known_at": iso(known_at),
            "window_bars": RANGE_WINDOW_BARS,
            "window_first_open_at": iso(self.rows[start_index]["open_at"]),
            "atr": float(atr),
            "width_atr": width_atr,
            "lower_boundary": lower,
            "upper_boundary": upper,
            "lower_interaction_identities": [
                item["identity"] for item in lower_interactions
            ],
            "upper_interaction_identities": [
                item["identity"] for item in upper_interactions
            ],
            "midpoint": midpoint,
            "decision_location": (price - lower_level) / width,
            "direction_relation": (
                "INWARD_FROM_DIRECTIONAL_HALF"
                if inward
                else "OUTWARD_FROM_OPPOSITE_HALF"
            ),
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
                self.timeframe,
                lower["identity"],
                upper["identity"],
                known_at,
            ]
        )
        payload["range_sha256"] = canonical_hash(payload)
        return payload


def timeframe_label(timeframe: str) -> str:
    return {"1h": "H1", "15m": "M15", "5m": "M5"}.get(timeframe, timeframe)


def _states(
    rows: Sequence[dict[str, Any]],
    cutoff: str,
    timeframe: str,
    timeline: PointInTimeInventoryTimeline | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    inventory = (
        timeline.inventory(cutoff)
        if timeline is not None
        else build_timeframe_inventory(rows, cutoff, timeframe)
    )
    states = [
        dict(item)
        for item in inventory["states"]
        if item["state"] != "UNKNOWN_TECHNICAL"
        and parse_dt(item["known_at"]) <= parse_dt(cutoff)
    ]
    return inventory, states


def _latest(states: Sequence[Mapping[str, Any]], kind: str) -> dict[str, Any] | None:
    matches = [dict(item) for item in states if item["kind"] == kind]
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: (
            parse_dt(item["pivot_at"]),
            parse_dt(item["known_at"]),
            item["identity"],
        ),
    )


def _is_unconsumed(item: Mapping[str, Any]) -> bool:
    return str(item["state"]).startswith("UNCONSUMED_")


def _source_swing(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "identity": str(item["identity"]),
        "timeframe": str(item["timeframe"]),
        "kind": str(item["kind"]),
        "level": float(item["level"]),
        "pivot_at": iso(item["pivot_at"]),
        "known_at": iso(item["known_at"]),
        "liquidity_state": str(item["state"]),
    }


def _pivot_candle(
    rows: Sequence[dict[str, Any]],
    pivot: Mapping[str, Any],
    cutoff: str,
    timeline: PointInTimeInventoryTimeline | None = None,
) -> dict[str, Any] | None:
    if timeline is not None:
        row = timeline.row_by_open.get(iso(pivot["pivot_at"]))
        if row is None or parse_dt(row["available_at"]) > parse_dt(cutoff):
            return None
        return dict(row)
    matches = [
        dict(row)
        for row in complete_rows(rows, cutoff)
        if iso(row["open_at"]) == iso(pivot["pivot_at"])
    ]
    return matches[0] if len(matches) == 1 else None


def _location_breached(
    rows: Sequence[dict[str, Any]],
    *,
    direction: Direction,
    known_at: str,
    cutoff: str,
    invalidation: float,
    timeline: PointInTimeInventoryTimeline | None = None,
) -> bool:
    if timeline is not None:
        return timeline.location_breached(
            direction=direction,
            known_at=known_at,
            cutoff=cutoff,
            invalidation=invalidation,
        )
    for row in complete_rows(rows, cutoff):
        if parse_dt(row["available_at"]) <= parse_dt(known_at):
            continue
        if direction == "LONG" and float(row["low"]) < invalidation:
            return True
        if direction == "SHORT" and float(row["high"]) > invalidation:
            return True
    return False


def h1_context_at(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    price: float,
    timeline: PointInTimeInventoryTimeline | None = None,
) -> dict[str, Any] | None:
    rows = stream["timeframes"]["1h"]
    inventory, states = _states(rows, cutoff, "H1", timeline)
    structure = structure_state(inventory)
    wanted_state = "UPTREND" if direction == "LONG" else "DOWNTREND"
    if structure["state"] == wanted_state:
        control_kind = "LOW" if direction == "LONG" else "HIGH"
        control = _latest(states, control_kind)
        destination_kind = "HIGH" if direction == "LONG" else "LOW"
        destinations = [
            dict(item)
            for item in states
            if item["kind"] == destination_kind
            and _is_unconsumed(item)
            and (
                float(item["level"]) > price
                if direction == "LONG"
                else float(item["level"]) < price
            )
        ]
        control_is_behind_price = (
            float(control["level"]) < price
            if control is not None and direction == "LONG"
            else (
                float(control["level"]) > price
                if control is not None
                else False
            )
        )
        if (
            control is None
            or not _is_unconsumed(control)
            or not control_is_behind_price
            or not destinations
        ):
            return None
        destination = min(
            destinations,
            key=lambda item: (
                abs(float(item["level"]) - price),
                parse_dt(item["known_at"]),
                item["identity"],
            ),
        )
        latest_high = _latest(states, "HIGH")
        latest_low = _latest(states, "LOW")
        if latest_high is None or latest_low is None:
            return None
        known_at = max(
            [latest_high["known_at"], latest_low["known_at"]], key=parse_dt
        )
        return {
            "family": "TREND",
            "direction": direction,
            "state": wanted_state,
            "known_at": iso(known_at),
            "structure_relations": structure["relations"],
            "governing_control": control,
            "governing_invalidation_level": float(control["level"]),
            "destination": destination,
            "range": None,
            "identity": canonical_hash(
                [
                    "H1_TREND_CONTEXT",
                    direction,
                    structure["relations"],
                    control["identity"],
                    destination["identity"],
                ]
            ),
        }

    if structure["state"] != "MIXED_OR_TRANSITIONING":
        return None
    range_item = (
        timeline.active_range(
            cutoff=cutoff,
            direction=direction,
            price=price,
            inventory=inventory,
        )
        if timeline is not None
        else active_range_context(
            rows,
            cutoff=cutoff,
            timeframe="H1",
            direction=direction,
            price=price,
            inventory=inventory,
        )
    )
    if range_item.get("state") != "ACTIVE_RANGE":
        return None
    midpoint = float(range_item["midpoint"])
    if direction == "LONG" and price > midpoint:
        return None
    if direction == "SHORT" and price < midpoint:
        return None
    boundary = dict(
        range_item["lower_boundary"]
        if direction == "LONG"
        else range_item["upper_boundary"]
    )
    return {
        "family": "RANGE",
        "direction": direction,
        "state": "ACTIVE_RANGE",
        "known_at": iso(range_item["known_at"]),
        "structure_relations": structure["relations"],
        "governing_control": boundary,
        "governing_invalidation_level": float(boundary["level"]),
        "destination": None,
        "range": range_item,
        "identity": canonical_hash(
            ["H1_RANGE_CONTEXT", direction, range_item["range_identity"]]
        ),
    }


def _trend_m15_context(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    timeline: PointInTimeInventoryTimeline | None = None,
) -> dict[str, Any] | None:
    rows = stream["timeframes"]["15m"]
    _inventory, states = _states(rows, cutoff, "M15", timeline)
    origin_kind = "LOW" if direction == "LONG" else "HIGH"
    terminal_kind = "HIGH" if direction == "LONG" else "LOW"
    terminals = sorted(
        [item for item in states if item["kind"] == terminal_kind],
        key=lambda item: (
            parse_dt(item["pivot_at"]),
            parse_dt(item["known_at"]),
            item["identity"],
        ),
        reverse=True,
    )
    for terminal in terminals:
        origins = [
            item
            for item in states
            if item["kind"] == origin_kind
            and parse_dt(item["pivot_at"]) < parse_dt(terminal["pivot_at"])
        ]
        if not origins:
            continue
        origin = max(
            origins,
            key=lambda item: (
                parse_dt(item["pivot_at"]),
                parse_dt(item["known_at"]),
                item["identity"],
            ),
        )
        valid = (
            float(terminal["level"]) > float(origin["level"])
            if direction == "LONG"
            else float(terminal["level"]) < float(origin["level"])
        )
        if not valid or not _is_unconsumed(origin) or not _is_unconsumed(terminal):
            continue
        zone = retracement_zone(
            float(origin["level"]), float(terminal["level"]), direction
        )
        known_at = max([origin["known_at"], terminal["known_at"]], key=parse_dt)
        if _location_breached(
            rows,
            direction=direction,
            known_at=str(known_at),
            cutoff=cutoff,
            invalidation=float(zone["invalidation"]),
            timeline=timeline,
        ):
            continue
        return {
            "setup_family": "PULLBACK_TO_CURVATURE",
            "control": origin,
            "terminal": terminal,
            "zone": zone,
            "known_at": iso(known_at),
            "identity": canonical_hash(
                [
                    "H1_GOVERNED_M15_PULLBACK",
                    direction,
                    origin["identity"],
                    terminal["identity"],
                ]
            ),
        }
    return None


def _range_m15_context(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    h1_context: Mapping[str, Any],
    timeline: PointInTimeInventoryTimeline | None = None,
) -> dict[str, Any] | None:
    range_item = h1_context.get("range")
    if not isinstance(range_item, Mapping):
        return None
    rows = stream["timeframes"]["15m"]
    _inventory, states = _states(rows, cutoff, "M15", timeline)
    control_kind = "LOW" if direction == "LONG" else "HIGH"
    lower = float(range_item["lower_boundary"]["level"])
    upper = float(range_item["upper_boundary"]["level"])
    midpoint = float(range_item["midpoint"])
    controls = [
        item
        for item in states
        if item["kind"] == control_kind
        and _is_unconsumed(item)
        and lower <= float(item["level"]) <= upper
        and (
            float(item["level"]) <= midpoint
            if direction == "LONG"
            else float(item["level"]) >= midpoint
        )
    ]
    if not controls:
        return None
    control = max(
        controls,
        key=lambda item: (
            parse_dt(item["pivot_at"]),
            parse_dt(item["known_at"]),
            item["identity"],
        ),
    )
    candle = _pivot_candle(rows, control, cutoff, timeline)
    if candle is None:
        return None
    zone = curvature_zone(candle, direction)
    if _location_breached(
        rows,
        direction=direction,
        known_at=str(control["known_at"]),
        cutoff=cutoff,
        invalidation=float(zone["invalidation"]),
        timeline=timeline,
    ):
        return None
    return {
        "setup_family": "ROTATION_FROM_BOUNDARY",
        "control": control,
        "terminal": None,
        "zone": zone,
        "known_at": iso(control["known_at"]),
        "identity": canonical_hash(
            [
                "H1_RANGE_M15_ROTATION",
                direction,
                range_item["range_identity"],
                control["identity"],
            ]
        ),
    }


def m15_context_at(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    h1_context: Mapping[str, Any],
    timeline: PointInTimeInventoryTimeline | None = None,
) -> dict[str, Any] | None:
    if h1_context["family"] == "TREND":
        return _trend_m15_context(
            stream, cutoff=cutoff, direction=direction, timeline=timeline
        )
    return _range_m15_context(
        stream,
        cutoff=cutoff,
        direction=direction,
        h1_context=h1_context,
        timeline=timeline,
    )


def _internal_range_destination(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    entry: float,
    h1_context: Mapping[str, Any],
    timeline: PointInTimeInventoryTimeline | None = None,
) -> dict[str, Any] | None:
    range_item = h1_context.get("range")
    if not isinstance(range_item, Mapping):
        return None
    lower = float(range_item["lower_boundary"]["level"])
    upper = float(range_item["upper_boundary"]["level"])
    _inventory, states = _states(
        stream["timeframes"]["15m"], cutoff, "M15", timeline
    )
    wanted = "HIGH" if direction == "LONG" else "LOW"
    candidates = [
        item
        for item in states
        if item["kind"] == wanted
        and _is_unconsumed(item)
        and lower < float(item["level"]) < upper
        and (
            float(item["level"]) > entry
            if direction == "LONG"
            else float(item["level"]) < entry
        )
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            abs(float(item["level"]) - entry),
            parse_dt(item["known_at"]),
            item["identity"],
        ),
    )


def _first_valid_retest(
    m5_rows: Sequence[dict[str, Any]],
    *,
    turn_index: int,
    direction: Direction,
    zone: Mapping[str, float],
    control: Mapping[str, Any],
) -> dict[str, Any] | None:
    turn = m5_rows[turn_index]
    body_low = min(float(turn["open"]), float(turn["close"]))
    body_high = max(float(turn["open"]), float(turn["close"]))
    for offset in range(1, RETEST_EXPIRY_BARS + 1):
        index = turn_index + offset
        if index >= len(m5_rows):
            return None
        row = m5_rows[index]
        if parse_dt(row["open_at"]) - parse_dt(turn["open_at"]) != timedelta(
            minutes=5 * offset
        ):
            return None
        location_breached = (
            float(row["low"]) < float(zone["invalidation"])
            if direction == "LONG"
            else float(row["high"]) > float(zone["invalidation"])
        )
        control_consumed = (
            float(row["low"]) < float(control["level"])
            if direction == "LONG"
            else float(row["high"]) > float(control["level"])
        )
        if location_breached or control_consumed:
            return None
        body_overlap = float(row["high"]) >= body_low and float(row["low"]) <= body_high
        if not (body_overlap or overlaps_zone(row, zone)):
            continue
        better = (
            float(row["low"]) > float(turn["low"])
            if direction == "LONG"
            else float(row["high"]) < float(turn["high"])
        )
        if not better or not directional_half_close(row, direction):
            return None
        return {"index": index, "bar": dict(row), "better_extreme": True}
    return None


def _build_spec(
    stream: Mapping[str, Any],
    *,
    direction: Direction,
    h1_context: Mapping[str, Any],
    m15_context: Mapping[str, Any],
    turn: Mapping[str, Any],
    retest: Mapping[str, Any],
    m15_timeline: PointInTimeInventoryTimeline | None = None,
) -> dict[str, Any] | None:
    decision_at = iso(retest["available_at"])
    entry = float(retest["close"])
    governing_invalidation = float(h1_context["governing_invalidation_level"])
    if direction == "LONG" and governing_invalidation >= entry:
        return None
    if direction == "SHORT" and governing_invalidation <= entry:
        return None
    if h1_context["family"] == "RANGE":
        range_item = h1_context.get("range")
        if not isinstance(range_item, Mapping):
            return None
        lower = float(range_item["lower_boundary"]["level"])
        upper = float(range_item["upper_boundary"]["level"])
        midpoint = float(range_item["midpoint"])
        inside_directional_half = (
            lower < entry <= midpoint
            if direction == "LONG"
            else midpoint <= entry < upper
        )
        if not inside_directional_half:
            return None
    stop = (
        min(float(turn["low"]), float(retest["low"])) - TICK_FLOOR
        if direction == "LONG"
        else max(float(turn["high"]), float(retest["high"])) + TICK_FLOOR
    )
    if h1_context["family"] == "TREND":
        destination = dict(h1_context["destination"])
        target_role = "H1_LIQUIDITY_SWING"
        target_timeframe = "H1"
        is_boundary = False
    else:
        destination = _internal_range_destination(
            stream,
            cutoff=decision_at,
            direction=direction,
            entry=entry,
            h1_context=h1_context,
            timeline=m15_timeline,
        )
        if destination is None:
            return None
        destination = dict(destination)
        target_role = "RANGE_INTERNAL_LIQUIDITY"
        target_timeframe = "M15"
        is_boundary = False
    target = float(destination["level"])
    if not (stop < entry < target if direction == "LONG" else target < entry < stop):
        return None
    control = dict(m15_context["control"])
    zone = dict(m15_context["zone"])
    sample_id = canonical_hash(
        [
            RULESET,
            direction,
            h1_context["identity"],
            m15_context["identity"],
            iso(turn["available_at"]),
            decision_at,
        ]
    )[:20]
    h1_source: dict[str, Any] = {
        "state": str(h1_context["state"]),
        "known_at": iso(h1_context["known_at"]),
        "governing_invalidation_level": float(
            h1_context["governing_invalidation_level"]
        ),
    }
    if h1_context["family"] == "RANGE":
        range_item = h1_context["range"]
        h1_source.update(
            {
                "lower_boundary": float(range_item["lower_boundary"]["level"]),
                "upper_boundary": float(range_item["upper_boundary"]["level"]),
                "midpoint": float(range_item["midpoint"]),
            }
        )
    return {
        "sample_id": sample_id,
        "title": (
            f"{decision_at[5:16].replace('T', ' ')} · {h1_context['family']} · {direction}"
        ),
        "synthetic": False,
        "family": str(h1_context["family"]),
        "direction": direction,
        "decision_at": decision_at,
        "h1_context": h1_source,
        "m15_setup": {
            "identity": str(m15_context["identity"]),
            "direction": direction,
            "governing_h1_state": str(h1_context["state"]),
            "setup_family": str(m15_context["setup_family"]),
            "known_at": iso(m15_context["known_at"]),
            "zone_lower": float(zone["lower"]),
            "zone_upper": float(zone["upper"]),
            "controlling_swing": _source_swing(control),
        },
        "m5_trigger": {
            "identity": canonical_hash(
                ["M5_TURN_RETEST", direction, turn["bar_id"], retest["bar_id"]]
            ),
            "direction": direction,
            "sequence": "TURN_THEN_FIRST_VALID_RETEST",
            "turn_known_at": iso(turn["available_at"]),
            "retest_known_at": decision_at,
            "turn_extreme": float(
                turn["low"] if direction == "LONG" else turn["high"]
            ),
            "retest_extreme": float(
                retest["low"] if direction == "LONG" else retest["high"]
            ),
            "retest_better_extreme": True,
            "aligned_close": True,
        },
        "entry": {
            "level": entry,
            "activated_at": decision_at,
            "source": "M5_CONFIRMED_RETEST_CLOSE",
        },
        "invalidation": {"level": stop},
        "destination": {
            "identity": str(destination["identity"]),
            "timeframe": target_timeframe,
            "kind": str(destination["kind"]),
            "level": target,
            "pivot_at": iso(destination["pivot_at"]),
            "known_at": iso(destination["known_at"]),
            "liquidity_state": str(destination["state"]),
            "role": target_role,
            "is_range_boundary": is_boundary,
        },
    }


def scan_stream(
    stream: Mapping[str, Any], *, start: str = START, end: str = END
) -> list[dict[str, Any]]:
    """Scan all completed January M5 bars and emit complete causal plans."""

    all_m5 = complete_rows(stream["timeframes"]["5m"], end)
    h1_timeline = PointInTimeInventoryTimeline(
        stream["timeframes"]["1h"], end=end, timeframe="1h"
    )
    m15_timeline = PointInTimeInventoryTimeline(
        stream["timeframes"]["15m"], end=end, timeframe="15m"
    )
    used_contexts: set[tuple[str, str, str]] = set()
    plans: list[dict[str, Any]] = []
    for index in range(3, len(all_m5)):
        turn = all_m5[index]
        if not (parse_dt(start) <= parse_dt(turn["available_at"]) < parse_dt(end)):
            continue
        preceding = all_m5[index - 3 : index]
        direction = trigger_direction(preceding, turn)
        if direction is None:
            continue
        cutoff = iso(turn["available_at"])
        price = float(turn["close"])
        h1_context = h1_context_at(
            stream,
            cutoff=cutoff,
            direction=direction,
            price=price,
            timeline=h1_timeline,
        )
        if h1_context is None:
            continue
        m15_context = m15_context_at(
            stream,
            cutoff=cutoff,
            direction=direction,
            h1_context=h1_context,
            timeline=m15_timeline,
        )
        if m15_context is None:
            continue
        context_key = (
            direction,
            str(h1_context["identity"]),
            str(m15_context["identity"]),
        )
        if context_key in used_contexts:
            continue
        zone = dict(m15_context["zone"])
        if not any(overlaps_zone(row, zone) for row in [*preceding, turn]):
            continue
        turn_extreme = float(turn["low"] if direction == "LONG" else turn["high"])
        if not float(zone["lower"]) <= turn_extreme <= float(zone["upper"]):
            continue
        retest = _first_valid_retest(
            all_m5,
            turn_index=index,
            direction=direction,
            zone=zone,
            control=m15_context["control"],
        )
        if retest is None:
            continue
        spec = _build_spec(
            stream,
            direction=direction,
            h1_context=h1_context,
            m15_context=m15_context,
            turn=turn,
            retest=retest["bar"],
            m15_timeline=m15_timeline,
        )
        if spec is None:
            continue
        plan = compile_trade_plan(spec)
        plan["scanner_ruleset"] = RULESET
        plan["h1_context_identity"] = str(h1_context["identity"])
        source_evidence: dict[str, Any] = {
            "h1_structure_relations": dict(h1_context["structure_relations"]),
            "h1_governing_control": _source_swing(
                h1_context["governing_control"]
            ),
            "h1_destination": (
                _source_swing(h1_context["destination"])
                if h1_context["destination"] is not None
                else None
            ),
            "selected_destination": {
                **dict(plan["destination"]),
                "pivot_at": iso(spec["destination"]["pivot_at"]),
            },
            "m15_control": {
                **_source_swing(m15_context["control"]),
                "pivot_at": iso(m15_context["control"]["pivot_at"]),
            },
            "m15_terminal": (
                {
                    **_source_swing(m15_context["terminal"]),
                    "pivot_at": iso(m15_context["terminal"]["pivot_at"]),
                }
                if m15_context["terminal"] is not None
                else None
            ),
            "m5_turn": {
                "bar_id": str(turn["bar_id"]),
                "open_at": iso(turn["open_at"]),
                "available_at": iso(turn["available_at"]),
            },
            "m5_retest": {
                "bar_id": str(retest["bar"]["bar_id"]),
                "open_at": iso(retest["bar"]["open_at"]),
                "available_at": iso(retest["bar"]["available_at"]),
            },
        }
        if h1_context["range"] is not None:
            source_evidence["h1_range"] = {
                "lower_boundary": {
                    **_source_swing(h1_context["range"]["lower_boundary"]),
                    "pivot_at": iso(
                        h1_context["range"]["lower_boundary"]["pivot_at"]
                    ),
                },
                "upper_boundary": {
                    **_source_swing(h1_context["range"]["upper_boundary"]),
                    "pivot_at": iso(
                        h1_context["range"]["upper_boundary"]["pivot_at"]
                    ),
                },
            }
        plan["source_evidence"] = source_evidence
        plan["source_stream_sha256"] = str(stream["stream_sha256"])
        assert_outcome_blind(plan)
        plan["scanner_plan_sha256"] = canonical_hash(plan)
        plans.append(plan)
        used_contexts.add(context_key)
    plans.sort(
        key=lambda item: (
            parse_dt(item["decision_at"]),
            item["direction"],
            item["plan_identity"],
        )
    )
    if len({item["plan_identity"] for item in plans}) != len(plans):
        raise RuntimeError("Duplicate H1-governed plan identity")
    return plans
