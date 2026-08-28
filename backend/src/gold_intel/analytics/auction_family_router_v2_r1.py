"""Semantic-integration corrections for the exposed Auction Router V2-R1.

This module is intentionally small.  It does not discover a new signal and it
does not alter the sealed V2 implementation.  It separates the legacy decision
anchor from optional semantic trigger layers and applies the existing liquidity
state machine to destination selection.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
    zone_registry,
)

Direction = Literal["LONG", "SHORT"]
FINAL_DESTINATION_STATES = frozenset({"ACTIVE_UNTOUCHED", "ACTIVE_ENGAGED"})
INTERMEDIATE_DESTINATION_STATES = frozenset({"REACTIVATED_REVERSE"})


def direction_sign(direction: Direction) -> int:
    return 1 if direction == "LONG" else -1


def direct_legacy_signal_route(
    *, signal_at: str, direction: Direction
) -> dict[str, Any]:
    """Use the already-frozen signal as the sole continuation decision."""

    payload = {
        "route": "LEGACY_SIGNAL_EXECUTION_ANCHOR_DIRECT",
        "direction": direction,
        "confirmation_at": iso(signal_at),
        "bar_open_at": None,
        "within_route_occurrence": 0,
        "second_trigger_required": False,
    }
    payload["route_hash"] = canonical_hash(payload)
    return payload


def m15_setup_event(plan: dict[str, Any]) -> dict[str, Any] | None:
    """Return the M15 setup transition and never the optional M5 refinement."""

    local = (plan.get("components") or {}).get("local_trigger")
    if not isinstance(local, dict):
        return None
    setup = local.get("setup_transition")
    if not isinstance(setup, dict) or setup.get("timeframe") != "M15":
        return None
    required = (
        "event_identity",
        "direction",
        "break_at",
        "broken_swing_identity",
        "broken_level",
        "protected_swing_identity",
        "protected_level",
        "transition_origin_at",
        "transition_origin_adverse",
        "transition_atr",
        "break_buffer",
    )
    if any(setup.get(key) is None for key in required):
        return None
    return {
        "identity": str(setup["event_identity"]),
        "timeframe": "M15",
        "direction": str(setup["direction"]),
        "break_at": iso(setup["break_at"]),
        "broken_identity": str(setup["broken_swing_identity"]),
        "broken_level": float(setup["broken_level"]),
        "protected_identity": str(setup["protected_swing_identity"]),
        "protected_level": float(setup["protected_level"]),
        "origin_at": iso(setup["transition_origin_at"]),
        "origin_adverse": float(setup["transition_origin_adverse"]),
        "atr": float(setup["transition_atr"]),
        "buffer": float(setup["break_buffer"]),
        "semantic_layer_identity": str(setup["identity"]),
    }


def _forward_distance(*, level: float, entry: float, direction: Direction) -> float:
    return direction_sign(direction) * (float(level) - float(entry))


def select_destination_hierarchy(
    zones: Sequence[dict[str, Any]],
    *,
    entry: float,
    direction: Direction,
) -> dict[str, Any] | None:
    """Select final active liquidity and any nearer reactivated reference.

    The selector uses lifecycle metadata only.  It does not use future path,
    target-room, or outcome information to choose among levels.
    """

    forward = [
        dict(zone)
        for zone in zones
        if zone.get("source") in {"H1", "H4"}
        and _forward_distance(
            level=float(zone["level"]), entry=entry, direction=direction
        )
        > 0
    ]
    final_candidates = [
        zone for zone in forward if zone.get("state") in FINAL_DESTINATION_STATES
    ]
    if not final_candidates:
        return None
    final = min(
        final_candidates,
        key=lambda zone: (
            _forward_distance(
                level=float(zone["level"]), entry=entry, direction=direction
            ),
            -1 if zone.get("source") == "H4" else 0,
            str(zone.get("identity")),
        ),
    )
    final_distance = _forward_distance(
        level=float(final["level"]), entry=entry, direction=direction
    )
    intermediate_candidates = [
        zone
        for zone in forward
        if zone.get("state") in INTERMEDIATE_DESTINATION_STATES
        and _forward_distance(
            level=float(zone["level"]), entry=entry, direction=direction
        )
        < final_distance
    ]
    intermediate = (
        min(
            intermediate_candidates,
            key=lambda zone: (
                _forward_distance(
                    level=float(zone["level"]), entry=entry, direction=direction
                ),
                str(zone.get("identity")),
            ),
        )
        if intermediate_candidates
        else None
    )
    payload: dict[str, Any] = {
        "selector": "NEXT_ACTIVE_NONCONSUMED_LIQUIDITY_V2_R1",
        "direction": direction,
        "entry_reference": float(entry),
        "final": {
            "identity": str(final["identity"]),
            "source_timeframe": str(final["source"]),
            "lifecycle_state": str(final["state"]),
            "level": float(final["level"]),
            "buffer": float(final["buffer"]),
            "known_at": iso(final["known_at"]),
            "prominence_atr": final.get("prominence_atr"),
            "evidence_classification": "INFERRED",
        },
        "intermediate": (
            {
                "identity": str(intermediate["identity"]),
                "source_timeframe": str(intermediate["source"]),
                "lifecycle_state": str(intermediate["state"]),
                "level": float(intermediate["level"]),
                "buffer": float(intermediate["buffer"]),
                "known_at": iso(intermediate["known_at"]),
                "prominence_atr": intermediate.get("prominence_atr"),
                "evidence_classification": "INFERRED",
            }
            if intermediate is not None
            else None
        ),
        "eligible_final_count": len(final_candidates),
        "intermediate_count_before_final": len(intermediate_candidates),
    }
    payload["hierarchy_hash"] = canonical_hash(payload)
    return payload


def destination_hierarchy(
    *,
    stream: dict[str, Any],
    cutoff: str,
    entry: float,
    direction: Direction,
    plan: dict[str, Any],
) -> dict[str, Any] | None:
    """Build the causal destination hierarchy at ``cutoff``."""

    components = plan.get("components") or {}
    governing = components.get("governing_auction") or {}
    controlling = components.get("controlling_structure") or {}
    original = components.get("liquidity_destination") or {}
    if governing.get("family") == "RANGE_ROTATION":
        level = original.get("level")
        identity = original.get("identity")
        if level is None or identity is None:
            return None
        if _forward_distance(level=float(level), entry=entry, direction=direction) <= 0:
            return None
        partial = original.get("partial_realization_level")
        payload: dict[str, Any] = {
            "selector": "ACTIVE_NAMED_BALANCE_BOUNDARY_V2_R1",
            "direction": direction,
            "entry_reference": float(entry),
            "final": {
                "identity": str(identity),
                "source_timeframe": str(original.get("source_timeframe")),
                "lifecycle_state": "ACTIVE_BALANCE_BOUNDARY",
                "level": float(level),
                "buffer": float(original.get("buffer", 0.0)),
                "known_at": iso(original.get("known_at")),
                "prominence_atr": None,
                "evidence_classification": "INFERRED",
            },
            "intermediate": (
                {
                    "identity": canonical_hash(
                        ["BALANCE_PARTIAL", controlling.get("identity"), partial]
                    ),
                    "source_timeframe": str(original.get("source_timeframe")),
                    "lifecycle_state": "ACTIVE_BALANCE_MIDPOINT",
                    "level": float(partial),
                    "buffer": float(original.get("buffer", 0.0)),
                    "known_at": iso(original.get("known_at")),
                    "prominence_atr": None,
                    "evidence_classification": "CALCULATED",
                }
                if partial is not None
                else None
            ),
            "eligible_final_count": 1,
            "intermediate_count_before_final": int(partial is not None),
        }
        payload["hierarchy_hash"] = canonical_hash(payload)
        return payload
    return select_destination_hierarchy(
        zone_registry(stream, iso(cutoff), direction),
        entry=float(entry),
        direction=direction,
    )


def pre_entry_invalidation_disposition(
    rows: Sequence[dict[str, Any]],
    *,
    signal_at: str,
    fill_at: str,
    stop: float,
    direction: Direction,
) -> dict[str, Any]:
    """Cancel a delayed route only when structural invalidation is touched."""

    signal = parse_dt(signal_at)
    fill = parse_dt(fill_at)
    for row in complete_rows(rows, fill):
        opened = parse_dt(row["open_at"])
        if opened < signal or opened >= fill:
            continue
        stop_touched = (
            float(row["low"]) <= float(stop)
            if direction == "LONG"
            else float(row["high"]) >= float(stop)
        )
        if stop_touched:
            payload = {
                "disposition": "STRUCTURAL_INVALIDATION_TOUCHED_PRE_ENTRY",
                "at": iso(row["open_at"]),
                "bar_hash": canonical_hash(
                    [
                        iso(row["open_at"]),
                        iso(row["available_at"]),
                        row.get("source_record_hash"),
                    ]
                ),
            }
            payload["disposition_hash"] = canonical_hash(payload)
            return payload
    payload = {
        "disposition": "CLEAR_TO_DELAYED_ENTRY",
        "at": None,
        "bar_hash": None,
    }
    payload["disposition_hash"] = canonical_hash(payload)
    return payload

