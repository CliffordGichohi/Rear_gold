"""Outcome-blind trade placement examples for the corrected auction semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt

RULESET = "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1"
MINIMUM_PLANNED_R = 1.5


def _directional_distance(direction: str, start: float, end: float) -> float:
    if direction == "LONG":
        return end - start
    if direction == "SHORT":
        return start - end
    raise ValueError(f"Unsupported direction: {direction}")


def compile_trade_plan(event: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Compile one plan from information available at the event decision time."""

    direction = str(event["direction"])
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"Unsupported direction: {direction}")
    if str(overlay["event_identity"]) != str(event["event_identity"]):
        raise ValueError("Event and semantic overlay identities differ")

    reasons: list[str] = []
    active_m15 = event.get("active_breaks", {}).get("M15")
    active_m5 = event.get("active_breaks", {}).get("M5")
    if active_m15 is None or str(active_m15.get("direction")) != direction:
        reasons.append("M15_CONTROL_NOT_ALIGNED")
    if active_m5 is None or str(active_m5.get("direction")) != direction:
        reasons.append("M5_CONTROL_NOT_ALIGNED")

    roles = overlay.get("timeframes", {}).get("M5", {}).get("active_control_roles")
    protected = None if roles is None else roles.get("protected_internal_pivot")
    if protected is None:
        reasons.append("M5_PROTECTED_PIVOT_UNRESOLVED")
    elif not str(protected.get("state", "")).startswith("UNCONSUMED_"):
        reasons.append("M5_PROTECTED_PIVOT_ALREADY_CONSUMED")

    entry = float(event["decision_price"])
    stop: float | None = None
    risk: float | None = None
    distance_from_break_atr: float | None = None
    if active_m5 is not None and protected is not None:
        buffer = float(active_m5["buffer"])
        protected_level = float(protected["level"])
        stop = protected_level - buffer if direction == "LONG" else protected_level + buffer
        risk = _directional_distance(direction, stop, entry)
        if risk <= 0:
            reasons.append("NONPOSITIVE_STRUCTURAL_RISK")
        atr = float(active_m5["atr"])
        distance_from_break_atr = abs(entry - float(active_m5["broken_level"])) / atr
        if distance_from_break_atr > 1.0:
            reasons.append("DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR")

    higher_timeframe_destinations = [
        overlay["timeframes"][timeframe].get("nearest_unconsumed_destination")
        for timeframe in ("H1", "H4")
    ]
    higher_timeframe_destinations = [
        item for item in higher_timeframe_destinations if item is not None
    ]
    target = (
        min(
            higher_timeframe_destinations,
            key=lambda item: (
                float(item["distance_price"]),
                parse_dt(item["known_at"]),
                str(item["identity"]),
            ),
        )
        if higher_timeframe_destinations
        else None
    )
    if target is None:
        reasons.append("NO_UNCONSUMED_H1_OR_H4_DESTINATION")

    reward: float | None = None
    planned_r: float | None = None
    if target is not None and risk is not None and risk > 0:
        reward = _directional_distance(direction, entry, float(target["level"]))
        if reward <= 0:
            reasons.append("TARGET_NOT_BEYOND_ENTRY")
        else:
            planned_r = reward / risk
            if planned_r < MINIMUM_PLANNED_R:
                reasons.append("TARGET_ROOM_BELOW_1P5R")

    local_destination = overlay["timeframes"]["M15"].get(
        "nearest_unconsumed_destination"
    )
    plan: dict[str, Any] = {
        "ruleset": RULESET,
        "event_identity": str(event["event_identity"]),
        "case_alias": str(event["case_alias"]),
        "trading_date_utc": str(event["trading_date_utc"]),
        "decision_at": str(event["decision_at"]),
        "session": str(event["session"]),
        "direction": direction,
        "event_class": str(event["event_class"]),
        "context_family": str(overlay["context_family"]),
        "entry": entry,
        "entry_rule": "COMPLETED_M5_SIGNAL_DECISION_PRICE",
        "stop": stop,
        "stop_rule": "M5_PROTECTED_INTERNAL_PIVOT_PLUS_EXISTING_BREAK_BUFFER",
        "protected_pivot": protected,
        "broken_control": None if active_m5 is None else {
            "identity": str(active_m5["broken_identity"]),
            "level": float(active_m5["broken_level"]),
            "break_at": str(active_m5["break_at"]),
            "atr": float(active_m5["atr"]),
            "buffer": float(active_m5["buffer"]),
        },
        "target": target,
        "target_rule": "NEAREST_UNCONSUMED_H1_OR_H4_DIRECTIONAL_PIVOT",
        "local_m15_liquidity": local_destination,
        "risk_price": risk,
        "reward_price": reward,
        "planned_r": planned_r,
        "distance_from_m5_break_atr": distance_from_break_atr,
        "eligible": not reasons,
        "reasons": reasons,
        "macro_context": event["macro_context"],
        "higher_timeframe_context": event["higher_timeframe_context"],
        "epistemic_status": {
            "completed_candles_and_decision_price": "OBSERVED",
            "pivots_structure_and_liquidity_lifecycle": "CALCULATED",
            "auction_control_and_trade_plan": "INFERRED",
            "institutional_orders": "UNKNOWN",
        },
    }
    plan["plan_sha256"] = canonical_hash(plan)
    return plan


def _take_earliest(
    plans: Sequence[dict[str, Any]],
    *,
    direction: str,
    context: str,
    count: int,
    used_dates: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for plan in sorted(plans, key=lambda item: (parse_dt(item["decision_at"]), item["event_identity"])):
        if plan["direction"] != direction or plan["context_family"] != context:
            continue
        if plan["trading_date_utc"] in used_dates:
            continue
        selected.append(plan)
        used_dates.add(plan["trading_date_utc"])
        if len(selected) == count:
            break
    if len(selected) != count:
        raise RuntimeError(f"Insufficient eligible {direction} {context} examples")
    return selected


def select_ten_examples(
    events: Sequence[Mapping[str, Any]], overlays: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    overlay_by_identity = {str(item["event_identity"]): item for item in overlays}
    if len(overlay_by_identity) != len(overlays):
        raise ValueError("Duplicate semantic overlay identities")
    plans = [
        compile_trade_plan(event, overlay_by_identity[str(event["event_identity"])])
        for event in events
    ]
    eligible = [item for item in plans if item["eligible"]]
    selected: list[dict[str, Any]] = []
    for direction in ("LONG", "SHORT"):
        used_dates: set[str] = set()
        selected.extend(
            _take_earliest(
                eligible,
                direction=direction,
                context="RANGE_ROTATION_WITH_LTF_CONTROL",
                count=1,
                used_dates=used_dates,
            )
        )
        selected.extend(
            _take_earliest(
                eligible,
                direction=direction,
                context="TREND_PULLBACK_WITH_LTF_CONTROL",
                count=2,
                used_dates=used_dates,
            )
        )
        selected.extend(
            _take_earliest(
                eligible,
                direction=direction,
                context="TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL",
                count=2,
                used_dates=used_dates,
            )
        )
    if len(selected) != 10:
        raise RuntimeError("Trade-placement atlas must contain exactly ten examples")
    return selected

