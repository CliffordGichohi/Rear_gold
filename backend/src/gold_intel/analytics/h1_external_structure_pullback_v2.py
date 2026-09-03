"""Outcome-blind H1 external-structure and M15 pullback correction.

This module is an exposed semantic regression.  It deliberately contains no
outcome reader or performance calculation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    TICK_FLOOR,
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
)
from gold_intel.analytics.early_m5_curvature_entry_v1 import trigger_direction
from gold_intel.analytics.h1_governed_trade_plan_v1 import assert_outcome_blind
from gold_intel.analytics.h1_governed_trade_scanner_v1 import (
    END,
    RETEST_EXPIRY_BARS,
    START,
    PointInTimeInventoryTimeline,
    _first_valid_retest,
    _is_unconsumed,
    _source_swing,
    h1_context_at,
    m15_context_at,
)
from gold_intel.analytics.swing_curvature_entry_v1 import overlaps_zone


Direction = Literal["LONG", "SHORT"]
RULESET = "GOLD_H1_EXTERNAL_STRUCTURE_PULLBACK_CORRECTION_V2"


def external_structure_state(
    states: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Classify external structure without letting contained pivots flip it."""

    known = sorted(
        [
            dict(item)
            for item in states
            if item.get("kind") in {"HIGH", "LOW"}
            and item.get("state") != "UNKNOWN_TECHNICAL"
        ],
        key=lambda item: (
            parse_dt(str(item["pivot_at"])),
            parse_dt(str(item["known_at"])),
            str(item["kind"]),
            str(item["identity"]),
        ),
    )
    external_high: dict[str, Any] | None = None
    external_low: dict[str, Any] | None = None
    internal_highs: list[dict[str, Any]] = []
    internal_lows: list[dict[str, Any]] = []
    direction: Direction | None = None
    transition: dict[str, Any] | None = None

    for swing in known:
        if swing["kind"] == "HIGH":
            if external_high is None:
                external_high = swing
                continue
            if float(swing["level"]) > float(external_high["level"]):
                lows_since_high = [
                    item
                    for item in internal_lows
                    if parse_dt(str(item["pivot_at"]))
                    > parse_dt(str(external_high["pivot_at"]))
                ]
                if lows_since_high:
                    external_low = min(
                        lows_since_high,
                        key=lambda item: (
                            float(item["level"]),
                            parse_dt(str(item["pivot_at"])),
                            str(item["identity"]),
                        ),
                    )
                direction = "LONG"
                external_high = swing
                transition = swing
                internal_highs = []
                internal_lows = []
            else:
                internal_highs.append(swing)
            continue

        if external_low is None:
            external_low = swing
            continue
        if float(swing["level"]) < float(external_low["level"]):
            highs_since_low = [
                item
                for item in internal_highs
                if parse_dt(str(item["pivot_at"]))
                > parse_dt(str(external_low["pivot_at"]))
            ]
            if highs_since_low:
                external_high = max(
                    highs_since_low,
                    key=lambda item: (
                        float(item["level"]),
                        parse_dt(str(item["pivot_at"])),
                        str(item["identity"]),
                    ),
                )
            direction = "SHORT"
            external_low = swing
            transition = swing
            internal_highs = []
            internal_lows = []
        else:
            internal_lows.append(swing)

    state = "TRANSITIONING" if direction is None else (
        "UPTREND" if direction == "LONG" else "DOWNTREND"
    )
    control = (
        external_low
        if direction == "LONG"
        else external_high if direction == "SHORT" else None
    )
    payload: dict[str, Any] = {
        "state": state,
        "direction": direction,
        "external_high": external_high,
        "external_low": external_low,
        "governing_control": control,
        "transition": transition,
        "contained_internal_highs": len(internal_highs),
        "contained_internal_lows": len(internal_lows),
    }
    payload["identity"] = canonical_hash(
        [
            RULESET,
            state,
            None if external_high is None else external_high["identity"],
            None if external_low is None else external_low["identity"],
            None if transition is None else transition["identity"],
        ]
    )
    return payload


def _nearest_h1_destination(
    states: Sequence[Mapping[str, Any]], *, direction: Direction, price: float
) -> dict[str, Any] | None:
    wanted = "HIGH" if direction == "LONG" else "LOW"
    candidates = [
        dict(item)
        for item in states
        if item["kind"] == wanted
        and _is_unconsumed(item)
        and (
            float(item["level"]) > price
            if direction == "LONG"
            else float(item["level"]) < price
        )
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            abs(float(item["level"]) - price),
            parse_dt(str(item["known_at"])),
            str(item["identity"]),
        ),
    )


def external_h1_context_at(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    price: float,
    timeline: PointInTimeInventoryTimeline,
) -> dict[str, Any] | None:
    inventory = timeline.inventory(cutoff)
    hierarchy = external_structure_state(inventory["states"])
    if hierarchy["direction"] != direction:
        return None
    control = hierarchy["governing_control"]
    if control is None:
        return None
    control_behind = (
        float(control["level"]) < price
        if direction == "LONG"
        else float(control["level"]) > price
    )
    if not control_behind:
        return None
    destination = _nearest_h1_destination(
        inventory["states"], direction=direction, price=price
    )
    if destination is None:
        return None
    transition = hierarchy["transition"] or control
    return {
        "family": "TREND",
        "direction": direction,
        "state": "UPTREND" if direction == "LONG" else "DOWNTREND",
        "known_at": iso(transition["known_at"]),
        "governing_control": dict(control),
        "governing_invalidation_level": float(control["level"]),
        "destination": destination,
        "range": None,
        "external_structure": hierarchy,
        "identity": str(hierarchy["identity"]),
    }


def trend_m15_pullback_context_at(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    price: float,
    h1_control: Mapping[str, Any],
    timeline: PointInTimeInventoryTimeline,
) -> dict[str, Any] | None:
    states = [
        dict(item)
        for item in timeline.inventory(cutoff)["states"]
        if item["state"] != "UNKNOWN_TECHNICAL"
    ]
    terminal_kind = "HIGH" if direction == "LONG" else "LOW"
    origin_kind = "LOW" if direction == "LONG" else "HIGH"
    terminals = sorted(
        [item for item in states if item["kind"] == terminal_kind],
        key=lambda item: (
            parse_dt(str(item["pivot_at"])),
            parse_dt(str(item["known_at"])),
            str(item["identity"]),
        ),
        reverse=True,
    )
    for terminal in terminals:
        origins = [
            item
            for item in states
            if item["kind"] == origin_kind
            and parse_dt(str(item["pivot_at"]))
            < parse_dt(str(terminal["pivot_at"]))
        ]
        if not origins:
            continue
        origin = max(
            origins,
            key=lambda item: (
                parse_dt(str(item["pivot_at"])),
                parse_dt(str(item["known_at"])),
                str(item["identity"]),
            ),
        )
        valid_leg = (
            float(origin["level"]) < float(terminal["level"])
            if direction == "LONG"
            else float(origin["level"]) > float(terminal["level"])
        )
        if not valid_leg:
            continue
        inside_leg = (
            float(origin["level"]) <= price < float(terminal["level"])
            if direction == "LONG"
            else float(terminal["level"]) < price <= float(origin["level"])
        )
        beyond_h1_control = (
            price > float(h1_control["level"])
            if direction == "LONG"
            else price < float(h1_control["level"])
        )
        if not inside_leg or not beyond_h1_control:
            continue
        return {
            "setup_family": "ACTIVE_M15_PULLBACK_LEG",
            "control": origin,
            "terminal": terminal,
            "zone": {
                "lower": min(float(origin["level"]), float(terminal["level"])),
                "upper": max(float(origin["level"]), float(terminal["level"])),
                "invalidation": float(origin["level"]),
            },
            "known_at": max(
                (iso(origin["known_at"]), iso(terminal["known_at"])),
                key=parse_dt,
            ),
            "terminal_liquidity_state": str(terminal["state"]),
            "identity": canonical_hash(
                [
                    RULESET,
                    "M15_PULLBACK",
                    direction,
                    origin["identity"],
                    terminal["identity"],
                ]
            ),
        }
    return None


def _plan(
    stream: Mapping[str, Any],
    *,
    direction: Direction,
    h1: Mapping[str, Any],
    m15: Mapping[str, Any],
    turn: Mapping[str, Any],
    retest: Mapping[str, Any],
) -> dict[str, Any] | None:
    decision_at = iso(retest["available_at"])
    entry = float(retest["close"])
    stop = (
        min(float(turn["low"]), float(retest["low"])) - TICK_FLOOR
        if direction == "LONG"
        else max(float(turn["high"]), float(retest["high"])) + TICK_FLOOR
    )
    destination = dict(h1["destination"])
    target = float(destination["level"])
    if not (
        stop < entry < target
        if direction == "LONG"
        else target < entry < stop
    ):
        return None
    for item in (h1["governing_control"], m15["control"], m15["terminal"], destination):
        if parse_dt(str(item["known_at"])) > parse_dt(decision_at):
            raise RuntimeError("Plan used a pivot not known at decision")
    sample_id = canonical_hash(
        [
            RULESET,
            direction,
            h1["identity"],
            m15["identity"],
            iso(turn["available_at"]),
            decision_at,
        ]
    )[:20]
    output: dict[str, Any] = {
        "sample_id": sample_id,
        "title": f"{decision_at[5:16].replace('T', ' ')} | TREND | {direction}",
        "synthetic": False,
        "family": "TREND",
        "direction": direction,
        "decision_at": decision_at,
        "governing_h1_auction": {
            "state": h1["state"],
            "known_at": h1["known_at"],
            "governing_invalidation_level": h1["governing_invalidation_level"],
            "role": "EXTERNAL_STRUCTURE_GOVERNS_DIRECTION_AND_DESTINATION",
            "range": None,
        },
        "m15_setup": {
            "identity": m15["identity"],
            "setup_family": m15["setup_family"],
            "known_at": m15["known_at"],
            "zone_lower": m15["zone"]["lower"],
            "zone_upper": m15["zone"]["upper"],
            "controlling_swing": _source_swing(m15["control"]),
            "terminal_liquidity_state": m15["terminal_liquidity_state"],
            "role": "LOCAL_PULLBACK_LEG_NOT_GOVERNING_DIRECTION",
        },
        "m5_execution": {
            "identity": canonical_hash(
                ["M5_TURN_RETEST", direction, turn["bar_id"], retest["bar_id"]]
            ),
            "sequence": "TURN_THEN_FIRST_VALID_RETEST",
            "turn_known_at": iso(turn["available_at"]),
            "retest_known_at": decision_at,
            "turn_extreme": float(turn["low"] if direction == "LONG" else turn["high"]),
            "retest_extreme": float(retest["low"] if direction == "LONG" else retest["high"]),
            "role": "ENTRY_TIMING_AND_LOCAL_INVALIDATION",
        },
        "entry": {
            "level": entry,
            "activated_at": decision_at,
            "source": "M5_CONFIRMED_RETEST_CLOSE",
        },
        "invalidation": {
            "level": stop,
            "source": "BEYOND_M5_TURN_RETEST_CURVATURE",
            "governing_h1_level": h1["governing_invalidation_level"],
        },
        "destination": {
            **_source_swing(destination),
            "role": "H1_LIQUIDITY_SWING",
            "target_policy": "PREEXISTING_UNCONSUMED_H1_LIQUIDITY_SWING",
        },
        "epistemic_status": {
            "ohlc": "OBSERVED_SEALED_XAUUSD",
            "structure_and_liquidity_roles": "CALCULATED",
            "auction_interpretation": "INFERRED",
            "resting_orders_or_institutional_intent": "UNKNOWN",
        },
        "guards": {
            "h1_external_structure_governs": True,
            "contained_h1_pivots_do_not_flip_direction": True,
            "m15_consumed_terminal_allowed": True,
            "m5_execution_unchanged": True,
            "outcome_data_present": False,
            "performance_calculated": False,
        },
        "h1_context_identity": h1["identity"],
        "source_evidence": {
            "h1_external_high": _source_swing(h1["external_structure"]["external_high"]),
            "h1_external_low": _source_swing(h1["external_structure"]["external_low"]),
            "h1_governing_control": _source_swing(h1["governing_control"]),
            "h1_destination": _source_swing(destination),
            "m15_control": _source_swing(m15["control"]),
            "m15_terminal": _source_swing(m15["terminal"]),
            "m5_turn": {
                "bar_id": str(turn["bar_id"]),
                "open_at": iso(turn["open_at"]),
                "available_at": iso(turn["available_at"]),
            },
            "m5_retest": {
                "bar_id": str(retest["bar_id"]),
                "open_at": iso(retest["open_at"]),
                "available_at": decision_at,
            },
        },
        "ruleset": RULESET,
        "scanner_ruleset": RULESET,
        "source_stream_sha256": str(stream["stream_sha256"]),
    }
    output["plan_identity"] = canonical_hash(
        [
            RULESET,
            direction,
            h1["identity"],
            m15["identity"],
            output["m5_execution"]["identity"],
            decision_at,
            entry,
            stop,
            target,
        ]
    )
    assert_outcome_blind(output)
    output["plan_sha256"] = canonical_hash(output)
    output["scanner_plan_sha256"] = canonical_hash(output)
    return output


def scan_stream(
    stream: Mapping[str, Any], *, start: str = START, end: str = END
) -> list[dict[str, Any]]:
    """Scan corrected trend contexts and carry V1 range plans unchanged."""

    all_m5 = complete_rows(stream["timeframes"]["5m"], end)
    h1_timeline = PointInTimeInventoryTimeline(
        stream["timeframes"]["1h"], end=end, timeframe="1h"
    )
    m15_timeline = PointInTimeInventoryTimeline(
        stream["timeframes"]["15m"], end=end, timeframe="15m"
    )
    used: set[tuple[str, str, str]] = set()
    plans: list[dict[str, Any]] = []

    for index in range(3, len(all_m5)):
        turn = all_m5[index]
        if not (
            parse_dt(start)
            <= parse_dt(str(turn["available_at"]))
            < parse_dt(end)
        ):
            continue
        direction = trigger_direction(all_m5[index - 3 : index], turn)
        if direction is None:
            continue
        cutoff = iso(turn["available_at"])
        price = float(turn["close"])
        h1 = external_h1_context_at(
            stream,
            cutoff=cutoff,
            direction=direction,
            price=price,
            timeline=h1_timeline,
        )
        if h1 is None:
            continue
        m15 = trend_m15_pullback_context_at(
            stream,
            cutoff=cutoff,
            direction=direction,
            price=price,
            h1_control=h1["governing_control"],
            timeline=m15_timeline,
        )
        if m15 is None:
            continue
        context_key = (direction, str(h1["identity"]), str(m15["terminal"]["identity"]))
        if context_key in used:
            continue
        zone = dict(m15["zone"])
        if not any(overlaps_zone(row, zone) for row in [*all_m5[index - 3 : index], turn]):
            continue
        turn_extreme = float(turn["low"] if direction == "LONG" else turn["high"])
        if not float(zone["lower"]) <= turn_extreme <= float(zone["upper"]):
            continue
        retest = _first_valid_retest(
            all_m5,
            turn_index=index,
            direction=direction,
            zone=zone,
            control=m15["control"],
        )
        if retest is None:
            continue
        plan = _plan(
            stream,
            direction=direction,
            h1=h1,
            m15=m15,
            turn=turn,
            retest=retest["bar"],
        )
        if plan is None:
            continue
        plans.append(plan)
        used.add(context_key)

    # The correction changes trend semantics only. Carry any V1 range plan
    # byte-for-byte so the range branch cannot move during this comparison.
    from gold_intel.analytics.h1_governed_trade_scanner_v1 import (
        scan_stream as scan_v1,
    )

    plans.extend(plan for plan in scan_v1(stream, start=start, end=end) if plan["family"] == "RANGE")
    plans.sort(
        key=lambda item: (
            parse_dt(str(item["decision_at"])),
            str(item["direction"]),
            str(item["plan_identity"]),
        )
    )
    if len({item["plan_identity"] for item in plans}) != len(plans):
        raise RuntimeError("Duplicate corrected plan identity")
    assert_outcome_blind(plans)
    return plans


def synthetic_proof() -> dict[str, Any]:
    """Prove that contained pivots cannot flip external structure."""

    def swing(number: int, kind: str, level: float) -> dict[str, Any]:
        hour = number + 1
        return {
            "identity": f"S{number}",
            "kind": kind,
            "timeframe": "H1",
            "pivot_at": f"2022-01-01T{hour:02d}:00:00Z",
            "known_at": f"2022-01-01T{hour + 1:02d}:00:00Z",
            "level": level,
            "state": "UNCONSUMED_UNTOUCHED",
        }

    bullish = [
        swing(0, "LOW", 100.0),
        swing(1, "HIGH", 110.0),
        swing(2, "LOW", 104.0),
        swing(3, "HIGH", 115.0),
        swing(4, "LOW", 109.0),
        swing(5, "HIGH", 113.0),
        swing(6, "LOW", 107.0),
    ]
    before_break = external_structure_state(bullish)
    after_break = external_structure_state([*bullish, swing(7, "LOW", 99.0)])
    result = {
        "contained_lower_high_and_lower_low_preserve_long": (
            before_break["direction"] == "LONG"
        ),
        "strict_external_low_break_flips_short": after_break["direction"] == "SHORT",
        "deterministic_reorder": external_structure_state(list(reversed(bullish)))[
            "identity"
        ]
        == before_break["identity"],
    }
    result["passed"] = all(result.values())
    return result

