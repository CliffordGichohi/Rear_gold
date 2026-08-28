"""Point-in-time compiler for explicit gold auction plans.

The compiler validates a proposed timestamp and direction.  It does not produce
directional signals and it never receives learned stop/target distances or an
outcome.  Every executable plan names the auction, controlling structure, local
trigger, structural invalidation, liquidity destination, and macro context.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    TICK_FLOOR,
    active_balance_candidates,
    canonical_hash,
    direction_sign,
    directional_progression,
    event_is_active,
    h4_damage_state,
    iso,
    latest_atr,
    latest_internal_m15_balance,
    macro_state,
    parse_dt,
    structural_breaks,
    zone_registry,
)

RULESET = "gold-auction-plan-compiler-v1"
Direction = Literal["LONG", "SHORT"]
Disposition = Literal["EXECUTABLE_PLAN", "NO_TRADE_UNRESOLVED"]
ACTIVE_DESTINATION_STATES = {
    "ACTIVE_UNTOUCHED",
    "ACTIVE_ENGAGED",
    "REACTIVATED_REVERSE",
}
REQUIRED_COMPONENTS = (
    "macro_context",
    "governing_auction",
    "controlling_structure",
    "local_trigger",
    "structural_invalidation",
    "liquidity_destination",
)


def _active_breaks(
    stream: dict[str, Any],
    *,
    cutoff: str,
    timeframe_key: str,
    timeframe_label: str,
    direction: Direction,
) -> list[dict[str, Any]]:
    rows = stream["timeframes"][timeframe_key]
    return [
        event
        for event in structural_breaks(rows, cutoff, timeframe_label, direction)
        if event_is_active(event, rows, cutoff)
    ]


def _latest(values: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not values:
        return None
    return max(values, key=lambda row: (parse_dt(row["break_at"]), str(row["identity"])))


def _accepted_breakout_identity(
    accepted_breakout: dict[str, Any], direction: Direction
) -> str:
    """Normalize legacy/current accepted-breakout identity field names."""

    return str(
        accepted_breakout.get("row_identity")
        or accepted_breakout.get("identity")
        or canonical_hash(
            ["ACCEPTED_BREAKOUT_IDENTITY", direction, accepted_breakout]
        )
    )


def _macro_component(stream: dict[str, Any], cutoff: str, direction: Direction) -> dict[str, Any]:
    state = macro_state(stream, cutoff, direction)
    identity = state.get("record_hash") or canonical_hash(
        ["MACRO_CONTEXT_UNKNOWN", cutoff, direction, state.get("reason")]
    )
    return {
        "identity": identity,
        "state": state.get("state", "UNKNOWN"),
        "score": state.get("score"),
        "confidence": state.get("confidence"),
        "quality": state.get("quality"),
        "available_at": state.get("available_at"),
        "dominant_driver": state.get("dominant_driver"),
        "bias_label": state.get("bias_label"),
        "reason": state.get("reason"),
        "evidence_classification": (
            "CALCULATED" if state.get("available_at") is not None else "UNKNOWN"
        ),
    }


def _select_local_trigger(
    stream: dict[str, Any], *, cutoff: str, direction: Direction, entry: float
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    active_m15 = _active_breaks(
        stream,
        cutoff=cutoff,
        timeframe_key="15m",
        timeframe_label="M15",
        direction=direction,
    )
    active_m5 = _active_breaks(
        stream,
        cutoff=cutoff,
        timeframe_key="5m",
        timeframe_label="M5",
        direction=direction,
    )
    m15_event = _latest(active_m15)
    m5_event = _latest(active_m5)
    m15_balance = latest_internal_m15_balance(stream, cutoff, entry)

    m5_is_contained = m5_event is not None and (m15_event is not None or m15_balance is not None)
    choose_m5 = m5_is_contained and (
        m15_event is None or parse_dt(m5_event["break_at"]) > parse_dt(m15_event["break_at"])
    )
    event = m5_event if choose_m5 else m15_event
    if event is None:
        return None, m15_event, m15_balance
    if choose_m5:
        container = m15_balance or m15_event
        family = "M5_INTERNAL_ROTATION"
        containing_identity = container and container["identity"]
    else:
        family = "M15_STRUCTURE_TRANSITION"
        containing_identity = m15_event and m15_event["identity"]
    trigger = {
        "identity": canonical_hash(
            [
                "AUCTION_TRIGGER_V1",
                family,
                event["identity"],
                containing_identity,
                cutoff,
            ]
        ),
        "family": family,
        "timeframe": event["timeframe"],
        "direction": direction,
        "break_at": event["break_at"],
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
    return trigger, m15_event, m15_balance


def _repair_break(
    stream: dict[str, Any], *, cutoff: str, direction: Direction, damage_at: str
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for key, label in (("1h", "H1"), ("15m", "M15")):
        candidates.extend(
            event
            for event in _active_breaks(
                stream,
                cutoff=cutoff,
                timeframe_key=key,
                timeframe_label=label,
                direction=direction,
            )
            if parse_dt(event["break_at"]) > parse_dt(damage_at)
        )
    if not candidates:
        return None
    return min(candidates, key=lambda row: (parse_dt(row["break_at"]), str(row["identity"])))


def _governing_components(
    stream: dict[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    entry: float,
    trigger: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    damage = h4_damage_state(stream, cutoff, direction)
    progression = directional_progression(stream, cutoff, direction)
    balances = active_balance_candidates(stream, cutoff, entry, direction)
    balance = balances[0] if balances else None

    if damage is not None and trigger is not None:
        repair = _repair_break(
            stream,
            cutoff=cutoff,
            direction=direction,
            damage_at=damage["damage_at"],
        )
        if repair is not None and parse_dt(trigger["break_at"]) >= parse_dt(repair["break_at"]):
            controlling = {
                "identity": canonical_hash(
                    ["STRUCTURAL_REPAIR_CONTROL", damage["damage_at"], repair["identity"]]
                ),
                "timeframe": "H4_TO_" + repair["timeframe"],
                "kind": "DAMAGED_AUCTION_WITH_ALIGNED_REPAIR",
                "known_at": repair["break_at"],
                "levels": {
                    "damaged_reference": float(damage["broken_reference"]),
                    "repair_broken_level": float(repair["broken_level"]),
                    "repair_protected_level": float(repair["protected_level"]),
                    "repair_origin_adverse": float(repair["origin_adverse"]),
                },
                "damage_identity": canonical_hash(damage),
                "repair_break_identity": repair["identity"],
                "evidence_classification": "INFERRED",
            }
            auction = {
                "identity": canonical_hash(
                    ["GOVERNING_AUCTION", "STRUCTURAL_REPAIR", controlling["identity"]]
                ),
                "family": "STRUCTURAL_REPAIR",
                "controlling_timeframe": controlling["timeframe"],
                "controlling_structure_identity": controlling["identity"],
                "known_at": controlling["known_at"],
                "evidence_classification": "INFERRED",
            }
            return auction, controlling, balance

    directional_starting_quarter = False
    accepted_breakout = None
    if balance is not None:
        location = float(balance["location"])
        directional_starting_quarter = location <= 0.25 if direction == "LONG" else location >= 0.75
        accepted_breakout = balance.get("accepted_breakout")
    if progression is None and balance is not None and directional_starting_quarter and accepted_breakout is None:
        boundary = float(balance["low"] if direction == "LONG" else balance["high"])
        controlling = {
            "identity": balance["identity"],
            "timeframe": balance["timeframe"],
            "kind": "ACTIVE_BALANCE_DIRECTIONAL_BOUNDARY",
            "known_at": balance["known_at"],
            "levels": {
                "low": float(balance["low"]),
                "high": float(balance["high"]),
                "midpoint": float(balance["midpoint"]),
                "directional_boundary": boundary,
                "location": location,
            },
            "evidence_classification": "CALCULATED",
        }
        auction = {
            "identity": canonical_hash(
                ["GOVERNING_AUCTION", "RANGE_ROTATION", controlling["identity"], direction]
            ),
            "family": "RANGE_ROTATION",
            "controlling_timeframe": controlling["timeframe"],
            "controlling_structure_identity": controlling["identity"],
            "known_at": controlling["known_at"],
            "evidence_classification": "INFERRED",
        }
        return auction, controlling, balance

    if progression is not None:
        event = progression["event"]
        controlling = {
            "identity": event["identity"],
            "timeframe": progression["timeframe"],
            "kind": "ACTIVE_DIRECTIONAL_PROGRESSION",
            "known_at": event["break_at"],
            "levels": {
                "broken_level": float(event["broken_level"]),
                "protected_level": float(event["protected_level"]),
                "origin_adverse": float(event["origin_adverse"]),
            },
            "relations": progression["relations"],
            "aligned_relation": progression["aligned_relation"],
            "later_than_opposite": progression["later_than_opposite"],
            "evidence_classification": "CALCULATED",
        }
        auction = {
            "identity": canonical_hash(
                ["GOVERNING_AUCTION", "CONTINUATION_WITH_ROOM", controlling["identity"]]
            ),
            "family": "CONTINUATION_WITH_ROOM",
            "controlling_timeframe": controlling["timeframe"],
            "controlling_structure_identity": controlling["identity"],
            "known_at": controlling["known_at"],
            "evidence_classification": "INFERRED",
        }
        return auction, controlling, balance

    if balance is not None and accepted_breakout is not None:
        acceptance_identity = _accepted_breakout_identity(
            accepted_breakout, direction
        )
        controlling = {
            "identity": balance["identity"],
            "timeframe": balance["timeframe"],
            "kind": "ACCEPTED_BALANCE_BREAKOUT",
            "known_at": accepted_breakout["retest_at"],
            "levels": {
                "low": float(balance["low"]),
                "high": float(balance["high"]),
                "midpoint": float(balance["midpoint"]),
            },
            "acceptance_identity": acceptance_identity,
            "evidence_classification": "CALCULATED",
        }
        auction = {
            "identity": canonical_hash(
                ["GOVERNING_AUCTION", "CONTINUATION_WITH_ROOM", controlling["identity"]]
            ),
            "family": "CONTINUATION_WITH_ROOM",
            "controlling_timeframe": controlling["timeframe"],
            "controlling_structure_identity": controlling["identity"],
            "known_at": controlling["known_at"],
            "evidence_classification": "INFERRED",
        }
        return auction, controlling, balance
    return None, None, balance


def _invalidation_component(
    stream: dict[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    entry: float,
    trigger: dict[str, Any] | None,
    active_m15: dict[str, Any] | None,
    m15_balance: dict[str, Any] | None,
    controlling: dict[str, Any] | None,
    governing: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if trigger is None:
        return None
    atr = latest_atr(stream["timeframes"]["15m"], cutoff)
    if atr is None or atr <= 0:
        return None
    references: list[dict[str, Any]] = [
        {
            "kind": "TRIGGER_PROTECTED_SWING",
            "identity": trigger["protected_swing_identity"],
            "level": float(trigger["protected_level"]),
        },
        {
            "kind": "TRIGGER_TRANSITION_ORIGIN",
            "identity": canonical_hash(
                [trigger["identity"], "ORIGIN", trigger["transition_origin_at"]]
            ),
            "level": float(trigger["transition_origin_adverse"]),
        },
    ]
    if trigger["timeframe"] == "M5" and active_m15 is not None:
        references.extend(
            [
                {
                    "kind": "ACTIVE_M15_PROTECTED_SWING",
                    "identity": active_m15["protected_identity"],
                    "level": float(active_m15["protected_level"]),
                },
                {
                    "kind": "ACTIVE_M15_TRANSITION_ORIGIN",
                    "identity": canonical_hash(
                        [active_m15["identity"], "ORIGIN", active_m15["origin_at"]]
                    ),
                    "level": float(active_m15["origin_adverse"]),
                },
            ]
        )
    if trigger["timeframe"] == "M5" and m15_balance is not None:
        references.append(
            {
                "kind": "CONTAINING_M15_BALANCE_BOUNDARY",
                "identity": m15_balance["identity"],
                "level": float(m15_balance["low"] if direction == "LONG" else m15_balance["high"]),
            }
        )
    if governing is not None and governing["family"] == "STRUCTURAL_REPAIR" and controlling is not None:
        references.append(
            {
                "kind": "STRUCTURAL_REPAIR_ORIGIN",
                "identity": controlling["repair_break_identity"],
                "level": float(controlling["levels"]["repair_origin_adverse"]),
            }
        )
    adverse_reference = (
        min(float(row["level"]) for row in references)
        if direction == "LONG"
        else max(float(row["level"]) for row in references)
    )
    buffer = max(0.10 * atr, TICK_FLOOR)
    price = adverse_reference - buffer if direction == "LONG" else adverse_reference + buffer
    if direction_sign(direction) * (entry - price) <= 0:
        return None
    identity = canonical_hash(
        ["STRUCTURAL_INVALIDATION_V1", direction, references, atr, price, cutoff]
    )
    return {
        "identity": identity,
        "price": price,
        "m15_atr": float(atr),
        "buffer": buffer,
        "adverse_reference": adverse_reference,
        "references": references,
        "known_at": cutoff,
        "evidence_classification": "CALCULATED",
    }


def _destination_component(
    stream: dict[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    entry: float,
    governing: dict[str, Any] | None,
    controlling: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if governing is None or controlling is None:
        return None
    sign = direction_sign(direction)
    if governing["family"] == "RANGE_ROTATION":
        level = float(
            controlling["levels"]["high"]
            if direction == "LONG"
            else controlling["levels"]["low"]
        )
        if sign * (level - entry) <= 0:
            return None
        atr = latest_atr(stream["timeframes"]["15m"], cutoff)
        buffer = max(0.10 * float(atr or 0.0), TICK_FLOOR)
        return {
            "identity": canonical_hash(
                ["BALANCE_LIQUIDITY_DESTINATION", controlling["identity"], direction, level]
            ),
            "source_timeframe": controlling["timeframe"],
            "lifecycle_state": "ACTIVE_BALANCE_BOUNDARY",
            "level": level,
            "buffer": buffer,
            "known_at": controlling["known_at"],
            "partial_realization_level": float(controlling["levels"]["midpoint"]),
            "evidence_classification": "INFERRED",
        }
    zones = zone_registry(stream, cutoff, direction)
    eligible = [
        zone
        for zone in zones
        if zone["source"] in {"H1", "H4"}
        and zone["state"] in ACTIVE_DESTINATION_STATES
        and sign * (float(zone["level"]) - entry) > 0
    ]
    h1 = [zone for zone in eligible if zone["source"] == "H1"]
    candidates = h1 if h1 else [zone for zone in eligible if zone["source"] == "H4"]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda zone: (sign * (float(zone["level"]) - entry), str(zone["identity"])),
    )
    return {
        "identity": selected["identity"],
        "source_timeframe": selected["source"],
        "lifecycle_state": selected["state"],
        "level": float(selected["level"]),
        "buffer": float(selected["buffer"]),
        "known_at": selected["known_at"],
        "prominence_atr": selected.get("prominence_atr"),
        "evidence_classification": "INFERRED",
    }


def compile_auction_plan_v1(
    *,
    stream: dict[str, Any],
    decision_at: str,
    direction: Direction | None,
    entry_reference: float | None,
) -> dict[str, Any]:
    """Compile one explicit plan using only records available at ``decision_at``."""

    cutoff = iso(decision_at)
    if direction not in {"LONG", "SHORT"}:
        return _unresolved_without_direction(cutoff)
    if entry_reference is None:
        return _unresolved_invalid_entry(cutoff, direction, "ENTRY_REFERENCE_MISSING")
    entry = float(entry_reference)
    if not (-1e12 < entry < 1e12):
        return _unresolved_invalid_entry(cutoff, direction, "ENTRY_REFERENCE_NONFINITE")

    macro = _macro_component(stream, cutoff, direction)
    trigger, active_m15, m15_balance = _select_local_trigger(
        stream, cutoff=cutoff, direction=direction, entry=entry
    )
    governing, controlling, _ = _governing_components(
        stream,
        cutoff=cutoff,
        direction=direction,
        entry=entry,
        trigger=trigger,
    )
    invalidation = _invalidation_component(
        stream,
        cutoff=cutoff,
        direction=direction,
        entry=entry,
        trigger=trigger,
        active_m15=active_m15,
        m15_balance=m15_balance,
        controlling=controlling,
        governing=governing,
    )
    destination = _destination_component(
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
        "local_trigger": trigger,
        "structural_invalidation": invalidation,
        "liquidity_destination": destination,
    }
    missing = [key for key in REQUIRED_COMPONENTS if components[key] is None]
    disposition: Disposition = "EXECUTABLE_PLAN" if not missing else "NO_TRADE_UNRESOLVED"
    payload = {
        "ruleset": RULESET,
        "decision_at": cutoff,
        "direction": direction,
        "entry_reference": entry,
        "disposition": disposition,
        "missing_components": missing,
        "components": components,
        "learned_geometry_used": False,
        "plan_sha256": None,
    }
    payload["plan_sha256"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "plan_sha256"}
    )
    return payload


def _unresolved_without_direction(cutoff: str) -> dict[str, Any]:
    payload = {
        "ruleset": RULESET,
        "decision_at": cutoff,
        "direction": None,
        "entry_reference": None,
        "disposition": "NO_TRADE_UNRESOLVED",
        "missing_components": ["direction_proposal", *REQUIRED_COMPONENTS],
        "unresolved_reason": "NO_DIRECTION_PROPOSAL",
        "components": {key: None for key in REQUIRED_COMPONENTS},
        "learned_geometry_used": False,
        "plan_sha256": None,
    }
    payload["plan_sha256"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "plan_sha256"}
    )
    return payload


def _unresolved_invalid_entry(cutoff: str, direction: Direction, reason: str) -> dict[str, Any]:
    payload = {
        "ruleset": RULESET,
        "decision_at": cutoff,
        "direction": direction,
        "entry_reference": None,
        "disposition": "NO_TRADE_UNRESOLVED",
        "missing_components": ["entry_reference", *REQUIRED_COMPONENTS],
        "unresolved_reason": reason,
        "components": {key: None for key in REQUIRED_COMPONENTS},
        "learned_geometry_used": False,
        "plan_sha256": None,
    }
    payload["plan_sha256"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "plan_sha256"}
    )
    return payload


def causality_violations(plan: dict[str, Any]) -> list[dict[str, Any]]:
    cutoff = parse_dt(plan["decision_at"])
    violations: list[dict[str, Any]] = []
    for component_name, component in plan.get("components", {}).items():
        if not isinstance(component, dict):
            continue
        for key in ("available_at", "known_at", "break_at", "transition_origin_at"):
            value = component.get(key)
            if value is not None and parse_dt(value) > cutoff:
                violations.append(
                    {
                        "component": component_name,
                        "field": key,
                        "value": iso(value),
                        "decision_at": iso(cutoff),
                    }
                )
    return violations


def plan_integrity_violations(plan: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if plan.get("learned_geometry_used") is not False:
        violations.append("LEARNED_GEOMETRY_NOT_PROHIBITED")
    components = plan.get("components", {})
    if plan.get("disposition") == "EXECUTABLE_PLAN":
        if any(components.get(key) is None for key in REQUIRED_COMPONENTS):
            violations.append("EXECUTABLE_PLAN_MISSING_COMPONENT")
        direction = plan.get("direction")
        entry = float(plan["entry_reference"])
        invalidation = float(components["structural_invalidation"]["price"])
        destination = float(components["liquidity_destination"]["level"])
        sign = 1 if direction == "LONG" else -1
        if sign * (entry - invalidation) <= 0:
            violations.append("INVALIDATION_NOT_ADVERSE")
        if sign * (destination - entry) <= 0:
            violations.append("DESTINATION_NOT_FORWARD")
    elif not plan.get("missing_components"):
        violations.append("UNRESOLVED_PLAN_MISSING_REASON")
    violations.extend(
        f"FUTURE_EVIDENCE:{row['component']}:{row['field']}"
        for row in causality_violations(plan)
    )
    return sorted(set(violations))
