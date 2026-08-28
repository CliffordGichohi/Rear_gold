"""Semantic Amendment A for the point-in-time gold auction-plan compiler.

V1 selected either an M15 transition or a later M5 refinement as one local
trigger.  The amended payload retains the H4/H1 governing auction, M15 setup
state, and optional M5 refinement as distinct observable layers.  It preserves
the V1 execution anchor so governing-auction, invalidation, and destination
geometry remain unchanged.
"""

from __future__ import annotations

from typing import Any

from gold_intel.analytics import auction_plan_compiler_v1 as v1
from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    iso,
    parse_dt,
)

RULESET = "gold-auction-plan-compiler-v1-semantic-amendment-a"
REQUIRED_COMPONENTS = v1.REQUIRED_COMPONENTS


def _break_layer(
    event: dict[str, Any],
    *,
    family: str,
    containing_identity: str | None,
) -> dict[str, Any]:
    return {
        "identity": canonical_hash(
            ["AUCTION_SEMANTIC_LAYER_A", family, event["identity"], containing_identity]
        ),
        "event_identity": event["identity"],
        "family": family,
        "timeframe": event["timeframe"],
        "direction": event["direction"],
        "break_at": event["break_at"],
        "known_at": event["break_at"],
        "broken_swing_identity": event["broken_identity"],
        "broken_level": float(event["broken_level"]),
        "protected_swing_identity": event["protected_identity"],
        "protected_level": float(event["protected_level"]),
        "transition_origin_at": event["origin_at"],
        "transition_origin_adverse": float(event["origin_adverse"]),
        "transition_atr": float(event["atr"]),
        "break_buffer": float(event["buffer"]),
        "containing_auction_identity": containing_identity,
        "evidence_classification": "CALCULATED",
    }


def _balance_setup_layer(
    balance: dict[str, Any], *, direction: v1.Direction, entry: float
) -> dict[str, Any]:
    low = float(balance["low"])
    high = float(balance["high"])
    width = high - low
    location = (entry - low) / width if width > 0 else None
    if location is None:
        directional_zone = "UNKNOWN"
    elif direction == "LONG" and location <= 0.25:
        directional_zone = "DISCOUNT_QUARTER"
    elif direction == "SHORT" and location >= 0.75:
        directional_zone = "PREMIUM_QUARTER"
    else:
        directional_zone = "INTERIOR"
    return {
        "identity": canonical_hash(
            ["AUCTION_SEMANTIC_LAYER_A", "M15_BALANCE_CONTEXT", balance["identity"], direction]
        ),
        "event_identity": balance["identity"],
        "family": "M15_BALANCE_CONTEXT",
        "timeframe": "M15",
        "direction": direction,
        "known_at": balance["known_at"],
        "low": low,
        "high": high,
        "midpoint": float(balance["midpoint"]),
        "location": location,
        "directional_zone": directional_zone,
        "evidence_classification": "CALCULATED",
    }


def _trigger_hierarchy_component(
    *,
    legacy_trigger: dict[str, Any] | None,
    active_m15: dict[str, Any] | None,
    active_m5: dict[str, Any] | None,
    m15_balance: dict[str, Any] | None,
    direction: v1.Direction,
    entry: float,
    cutoff: str,
) -> dict[str, Any] | None:
    """Represent setup and refinement without changing V1 execution geometry."""

    if legacy_trigger is None:
        return None
    setup = (
        _break_layer(
            active_m15,
            family="M15_STRUCTURE_TRANSITION",
            containing_identity=active_m15["identity"],
        )
        if active_m15 is not None
        else (
            _balance_setup_layer(m15_balance, direction=direction, entry=entry)
            if m15_balance is not None
            else None
        )
    )
    refinement = (
        _break_layer(
            active_m5,
            family="M5_ENTRY_REFINEMENT",
            containing_identity=setup and setup["identity"],
        )
        if active_m5 is not None and setup is not None
        else None
    )
    anchor = {
        "identity": legacy_trigger["identity"],
        "family": legacy_trigger["family"],
        "timeframe": legacy_trigger["timeframe"],
        "break_at": legacy_trigger["break_at"],
        "structural_role": "V1_EXECUTION_GEOMETRY_ANCHOR",
    }
    known_values = [
        value
        for value in (
            setup and setup.get("known_at"),
            refinement and refinement.get("known_at"),
            anchor.get("break_at"),
        )
        if value is not None
    ]
    known_at = max(known_values, key=parse_dt) if known_values else cutoff
    return {
        "identity": canonical_hash(
            [
                "HIERARCHICAL_AUCTION_TRIGGER_A",
                setup and setup["identity"],
                refinement and refinement["identity"],
                anchor["identity"],
                cutoff,
            ]
        ),
        "family": "HIERARCHICAL_AUCTION_TRIGGER",
        "direction": direction,
        "known_at": iso(known_at),
        "setup_transition": setup,
        "entry_refinement": refinement,
        "execution_anchor": anchor,
        "evidence_classification": "CALCULATED",
    }


def compile_auction_plan_v1_semantic_amendment_a(
    *,
    stream: dict[str, Any],
    decision_at: str,
    direction: v1.Direction | None,
    entry_reference: float | None,
) -> dict[str, Any]:
    """Compile an amended plan using records available at ``decision_at`` only."""

    cutoff = iso(decision_at)
    if direction not in {"LONG", "SHORT"}:
        payload = v1._unresolved_without_direction(cutoff)
        return _stamp_amendment(payload)
    if entry_reference is None:
        return _stamp_amendment(
            v1._unresolved_invalid_entry(cutoff, direction, "ENTRY_REFERENCE_MISSING")
        )
    entry = float(entry_reference)
    if not (-1e12 < entry < 1e12):
        return _stamp_amendment(
            v1._unresolved_invalid_entry(cutoff, direction, "ENTRY_REFERENCE_NONFINITE")
        )

    macro = v1._macro_component(stream, cutoff, direction)
    legacy_trigger, active_m15, m15_balance = v1._select_local_trigger(
        stream, cutoff=cutoff, direction=direction, entry=entry
    )
    active_m5 = v1._latest(
        v1._active_breaks(
            stream,
            cutoff=cutoff,
            timeframe_key="5m",
            timeframe_label="M5",
            direction=direction,
        )
    )
    trigger_hierarchy = _trigger_hierarchy_component(
        legacy_trigger=legacy_trigger,
        active_m15=active_m15,
        active_m5=active_m5,
        m15_balance=m15_balance,
        direction=direction,
        entry=entry,
        cutoff=cutoff,
    )
    governing, controlling, _ = v1._governing_components(
        stream,
        cutoff=cutoff,
        direction=direction,
        entry=entry,
        trigger=legacy_trigger,
    )
    invalidation = v1._invalidation_component(
        stream,
        cutoff=cutoff,
        direction=direction,
        entry=entry,
        trigger=legacy_trigger,
        active_m15=active_m15,
        m15_balance=m15_balance,
        controlling=controlling,
        governing=governing,
    )
    destination = v1._destination_component(
        stream,
        cutoff=cutoff,
        direction=direction,
        entry=entry,
        governing=governing,
        controlling=controlling,
    )
    components = {
        "macro_context": macro,
        "governing_auction": governing,
        "controlling_structure": controlling,
        "local_trigger": trigger_hierarchy,
        "structural_invalidation": invalidation,
        "liquidity_destination": destination,
    }
    missing = [key for key in REQUIRED_COMPONENTS if components[key] is None]
    payload = {
        "ruleset": RULESET,
        "semantic_hierarchy_version": "H4_H1__M15__OPTIONAL_M5_A",
        "decision_at": cutoff,
        "direction": direction,
        "entry_reference": entry,
        "disposition": "EXECUTABLE_PLAN" if not missing else "NO_TRADE_UNRESOLVED",
        "missing_components": missing,
        "components": components,
        "learned_geometry_used": False,
        "plan_sha256": None,
    }
    payload["plan_sha256"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "plan_sha256"}
    )
    return payload


def _stamp_amendment(payload: dict[str, Any]) -> dict[str, Any]:
    payload["ruleset"] = RULESET
    payload["semantic_hierarchy_version"] = "H4_H1__M15__OPTIONAL_M5_A"
    payload["plan_sha256"] = None
    payload["plan_sha256"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "plan_sha256"}
    )
    return payload


def causality_violations(plan: dict[str, Any]) -> list[dict[str, Any]]:
    cutoff = parse_dt(plan["decision_at"])
    violations: list[dict[str, Any]] = []
    timestamp_keys = {"available_at", "known_at", "break_at", "transition_origin_at"}

    def visit(value: Any, trail: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                next_trail = (*trail, str(key))
                if key in timestamp_keys and item is not None and parse_dt(item) > cutoff:
                    violations.append(
                        {
                            "component": ".".join(next_trail),
                            "field": key,
                            "value": iso(item),
                            "decision_at": iso(cutoff),
                        }
                    )
                else:
                    visit(item, next_trail)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, (*trail, str(index)))

    visit(plan.get("components", {}), ("components",))
    return violations


def plan_integrity_violations(plan: dict[str, Any]) -> list[str]:
    violations = [
        item for item in v1.plan_integrity_violations(plan) if not item.startswith("FUTURE_EVIDENCE:")
    ]
    if plan.get("disposition") == "EXECUTABLE_PLAN":
        trigger = plan.get("components", {}).get("local_trigger")
        if not isinstance(trigger, dict):
            violations.append("HIERARCHICAL_TRIGGER_MISSING")
        else:
            setup = trigger.get("setup_transition")
            refinement = trigger.get("entry_refinement")
            anchor = trigger.get("execution_anchor")
            if not isinstance(setup, dict) or setup.get("timeframe") != "M15":
                violations.append("M15_SETUP_TRANSITION_MISSING")
            if not isinstance(anchor, dict) or anchor.get("timeframe") not in {"M15", "M5"}:
                violations.append("EXECUTION_ANCHOR_INVALID")
            if (
                isinstance(anchor, dict)
                and anchor.get("timeframe") == "M5"
                and (not isinstance(refinement, dict) or refinement.get("timeframe") != "M5")
            ):
                violations.append("M5_ANCHOR_WITHOUT_REFINEMENT")
    violations.extend(
        f"FUTURE_EVIDENCE:{row['component']}" for row in causality_violations(plan)
    )
    return sorted(set(violations))
