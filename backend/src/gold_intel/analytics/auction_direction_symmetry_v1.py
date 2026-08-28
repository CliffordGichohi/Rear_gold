"""Direction-symmetric helpers for the exposed coherent-auction translator.

The original translator was calibrated only on LONG/NO_TRADE examples.  This
module does not fit a SHORT model.  It expresses a SHORT observation in the
same direction-normalized feature space used by the LONG model, then mirrors
execution geometry and all directional context checks.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    h4_damage_state,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (
    RISK_BUDGET_USD,
    active_m15_directional_structure,
    contextual_veto_codes,
    event_lock_state,
    h4_context_metrics,
    macro_state,
)

Direction = Literal["LONG", "SHORT"]


_VALUE_MIRROR = {
    "BULLISH": "BEARISH",
    "BEARISH": "BULLISH",
}


def _mirror_key(key: str) -> str:
    """Return the semantic opposite of a directional feature key."""

    pairs = (
        ("close_above_latest_low_atr", "close_below_latest_high_atr"),
        ("latest_high_age_minutes", "latest_low_age_minutes"),
        ("bullish_", "bearish_"),
    )
    for left, right in pairs:
        if left in key:
            return key.replace(left, right)
        if right in key:
            return key.replace(right, left)
    for left, right in (("bull_", "bear_"), ("long_", "short_")):
        if key.startswith(left):
            return right + key[len(left) :]
        if key.startswith(right):
            return left + key[len(right) :]
    return key


def mirror_feature_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror a raw checkpoint into the LONG-oriented coordinate system.

    Price identities and timestamps remain unchanged.  Directional state is
    exchanged, signed returns are negated, and range location is reflected.
    Applying this function twice reproduces the source row.
    """

    mirrored: dict[str, Any] = {}
    for source_key, source_value in row.items():
        target_key = _mirror_key(str(source_key))
        value = deepcopy(source_value)
        if source_key.endswith(("return_1_atr", "return_3_atr", "return_6_atr")):
            if value is not None:
                value = -float(value)
        elif source_key.endswith("swing_range_position"):
            if value is not None:
                value = round(1.0 - float(value), 8)
        elif source_key.endswith(("candle_direction", "trend")):
            value = _VALUE_MIRROR.get(str(value), value)
        if target_key in mirrored:
            raise ValueError(f"Feature mirror collision: {source_key} -> {target_key}")
        mirrored[target_key] = value
    return mirrored


def orient_feature_row(row: Mapping[str, Any], direction: Direction) -> dict[str, Any]:
    """Return features in the original LONG model's coordinate system."""

    if direction == "LONG":
        return deepcopy(dict(row))
    if direction == "SHORT":
        return mirror_feature_row(row)
    raise ValueError(f"Unsupported direction: {direction}")


def directional_geometry(
    *,
    reference: float,
    atr: float,
    stop_distance_atr: float,
    target_distance_atr: float,
    direction: Direction,
) -> tuple[float, float]:
    """Mirror positive learned distances around the observable reference."""

    if not all(
        math.isfinite(value)
        for value in (reference, atr, stop_distance_atr, target_distance_atr)
    ):
        raise ValueError("Non-finite directional geometry input")
    if atr <= 0 or stop_distance_atr <= 0 or target_distance_atr <= 0:
        raise ValueError("Directional geometry distances must be positive")
    sign = 1.0 if direction == "LONG" else -1.0
    stop = reference - sign * stop_distance_atr * atr
    target = reference + sign * target_distance_atr * atr
    return stop, target


def directional_fill(
    *, mid_open: float, spread_price: float, slippage: float, direction: Direction
) -> float:
    """Apply an equally adverse spread and slippage assumption to either side."""

    sign = 1.0 if direction == "LONG" else -1.0
    return float(mid_open) + sign * (float(spread_price) / 2.0 + float(slippage))


def classify_autonomous_directional(
    *,
    stream: dict[str, Any],
    signal_at: str,
    direction: Direction,
    family: str,
    fill: float,
    stop: float,
    target: float,
    cost_per_ounce: float,
) -> dict[str, Any]:
    """Apply the frozen contextual gates symmetrically to LONG or SHORT."""

    h4 = h4_context_metrics(stream, signal_at, direction)
    m15 = active_m15_directional_structure(stream, signal_at, direction)
    event = event_lock_state(stream, signal_at, direction)
    macro = macro_state(stream, signal_at, direction)
    damage = h4_damage_state(stream, signal_at, direction)
    sign = 1.0 if direction == "LONG" else -1.0
    blockers: list[dict[str, Any]] = []
    geometry_valid = (
        math.isfinite(fill)
        and math.isfinite(stop)
        and math.isfinite(target)
        and math.isfinite(cost_per_ounce)
        and sign * (fill - stop) > 0
        and sign * (target - fill) > 0
    )
    structural_risk = sign * (fill - stop) if geometry_valid else math.inf
    planned_loss_per_ounce = (
        structural_risk + cost_per_ounce if geometry_valid else math.inf
    )
    quantity = (
        math.floor(RISK_BUDGET_USD / planned_loss_per_ounce)
        if geometry_valid and planned_loss_per_ounce > 0
        else 0
    )
    if not geometry_valid or not h4["available"] or quantity < 1:
        blockers.append(
            {
                "gate": 1,
                "code": "GEOMETRY_OR_REQUIRED_CONTEXT_UNAVAILABLE",
                "evidence": {
                    "geometry_valid": geometry_valid,
                    "h4_available": h4["available"],
                    "quantity_ounces": quantity,
                },
            }
        )
    gate_by_code = {
        "NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE": 2,
        "UNRESOLVED_TIER1_EVENT_AUCTION": 3,
        "EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION": 4,
        "SEVERE_OPPOSING_HTF_IMPULSE": 5,
        "HTF_PREMIUM_RANGE_ROTATION_CONFLICT": 6,
    }
    for code in contextual_veto_codes(
        family=family, h4=h4, m15=m15, event=event, damage=damage
    ):
        evidence: Any = h4
        if code == "NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE":
            evidence = m15
        elif code == "UNRESOLVED_TIER1_EVENT_AUCTION":
            evidence = event
        elif code == "SEVERE_OPPOSING_HTF_IMPULSE":
            evidence = {"h4": h4, "damage": damage}
        blockers.append(
            {"gate": gate_by_code[code], "code": code, "evidence": evidence}
        )
    warnings: list[str] = []
    if macro["state"] in {"OPPOSED", "UNKNOWN"}:
        warnings.append(f"MACRO_{macro['state']}")
    if damage is not None and not any(
        row["code"] == "SEVERE_OPPOSING_HTF_IMPULSE" for row in blockers
    ):
        warnings.append("BOUNDED_STRUCTURAL_REPAIR_ONLY")
    signed_location = h4.get("signed_range_location")
    if (
        signed_location is not None
        and signed_location >= 0.80
        and not any(
            row["code"] == "EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION"
            for row in blockers
        )
    ):
        warnings.append("HIGH_HTF_LOCATION_WITHOUT_EXTENSION_CONJUNCTION")
    blockers.sort(key=lambda row: (int(row["gate"]), str(row["code"])))
    admitted = not blockers
    result = {
        "ruleset": (
            "AUTONOMOUS_TRANSLATOR_PLUS_FROZEN_HUMAN_POLICY_V2"
            if direction == "LONG"
            else "DIRECTION_SYMMETRIC_TRANSLATOR_PLUS_FROZEN_HUMAN_POLICY_V1"
        ),
        "decision_at": signal_at,
        "direction": direction,
        "family": family,
        "admitted": admitted,
        "primary_disposition": "ADMIT" if admitted else blockers[0]["code"],
        "blockers": blockers,
        "warnings": sorted(warnings),
        "macro": macro,
        "event": event,
        "h4": h4,
        "h4_damage": damage,
        "m15_structure": m15,
        "fill": fill,
        "stop": stop,
        "target": target,
        "structural_price_risk_per_ounce": abs(fill - stop),
        "cost_per_ounce": cost_per_ounce,
        "planned_loss_per_ounce": planned_loss_per_ounce,
        "quantity_ounces": quantity,
        "classification_hash": None,
    }
    result["classification_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "classification_hash"}
    )
    return result
