"""Outcome-blind H1-governed trade-plan semantics.

H1 defines the governing auction and destination.  M15 defines the local
setup, while M5 supplies the executable turn/retest and local invalidation.
Trend plans must target a known H1 liquidity swing.  Range plans must target
known internal M15 liquidity and may never use the opposite range boundary as
their automatic destination.

This module deliberately contains no price-path resolver, trade result, PnL,
MFE, MAE, or performance calculation.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    iso,
    parse_dt,
)

Direction = Literal["LONG", "SHORT"]
AuctionFamily = Literal["TREND", "RANGE"]

RULESET = "GOLD_H1_GOVERNED_TRADE_PLAN_SEMANTICS_V1"
FORBIDDEN_OUTPUT_KEYS = {
    "outcome",
    "result",
    "resolution",
    "pnl",
    "net_r",
    "gross_r",
    "mfe",
    "mae",
    "win_rate",
    "profit_factor",
    "return",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def assert_outcome_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_OUTPUT_KEYS:
                raise RuntimeError(f"Forbidden outcome field at {path}.{key}")
            assert_outcome_blind(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            assert_outcome_blind(child, f"{path}[{index}]")


def _known_no_later_than(
    item: Mapping[str, Any], decision_at: str, label: str
) -> str:
    require("known_at" in item, f"{label} is missing known_at")
    known_at = iso(item["known_at"])
    require(
        parse_dt(known_at) <= parse_dt(decision_at),
        f"{label} was not known at the decision timestamp",
    )
    return known_at


def _normalize_swing(
    item: Mapping[str, Any], *, decision_at: str, label: str
) -> dict[str, Any]:
    require(str(item.get("kind")) in {"HIGH", "LOW"}, f"{label} has invalid kind")
    require(str(item.get("timeframe")) in {"H1", "M15", "M5"}, f"{label} has invalid timeframe")
    state = str(item.get("liquidity_state", ""))
    require(
        state in {"UNCONSUMED_UNTOUCHED", "UNCONSUMED_ENGAGED"},
        f"{label} must be unconsumed",
    )
    return {
        "identity": str(item["identity"]),
        "timeframe": str(item["timeframe"]),
        "kind": str(item["kind"]),
        "level": float(item["level"]),
        "known_at": _known_no_later_than(item, decision_at, label),
        "liquidity_state": state,
        "epistemic_status": "CALCULATED_FROM_COMPLETED_CANDLES",
    }


def compile_trade_plan(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Compile one complete causal plan from already-observable components."""

    assert_outcome_blind(spec)
    sample_id = str(spec["sample_id"])
    family: AuctionFamily = str(spec["family"])  # type: ignore[assignment]
    direction: Direction = str(spec["direction"])  # type: ignore[assignment]
    require(family in {"TREND", "RANGE"}, "family must be TREND or RANGE")
    require(direction in {"LONG", "SHORT"}, "direction must be LONG or SHORT")
    decision_at = iso(spec["decision_at"])

    h1 = dict(spec["h1_context"])
    m15 = dict(spec["m15_setup"])
    m5 = dict(spec["m5_trigger"])
    entry = dict(spec["entry"])
    destination_source = dict(spec["destination"])

    h1_known_at = _known_no_later_than(h1, decision_at, "H1 context")
    m15_known_at = _known_no_later_than(m15, decision_at, "M15 setup")
    turn_known_at = _known_no_later_than(
        {"known_at": m5["turn_known_at"]}, decision_at, "M5 turn"
    )
    retest_known_at = _known_no_later_than(
        {"known_at": m5["retest_known_at"]}, decision_at, "M5 retest"
    )
    require(parse_dt(turn_known_at) <= parse_dt(retest_known_at), "M5 retest precedes turn")
    require(retest_known_at == decision_at, "Decision must be the completed M5 retest timestamp")

    require(str(m15.get("direction")) == direction, "M15 direction disagrees with plan")
    require(str(m5.get("direction")) == direction, "M5 direction disagrees with plan")
    require(
        str(m15.get("governing_h1_state")) == str(h1.get("state")),
        "M15 setup does not reference the governing H1 state",
    )
    require(
        str(m5.get("sequence")) == "TURN_THEN_FIRST_VALID_RETEST",
        "M5 sequence must be turn followed by first valid retest",
    )
    require(bool(m5.get("retest_better_extreme")), "M5 retest did not fail at a better extreme")
    require(bool(m5.get("aligned_close")), "M5 retest lacks the aligned completed close")

    entry_level = float(entry["level"])
    stop_level = float(spec["invalidation"]["level"])
    require(iso(entry["activated_at"]) == decision_at, "Entry activation differs from decision")
    require(
        str(entry.get("source")) == "M5_CONFIRMED_RETEST_CLOSE",
        "Entry must come from the completed M5 retest close",
    )

    zone_lower = float(m15["zone_lower"])
    zone_upper = float(m15["zone_upper"])
    require(zone_lower < zone_upper, "M15 location zone is invalid")
    turn_extreme = float(m5["turn_extreme"])
    retest_extreme = float(m5["retest_extreme"])
    require(
        zone_lower <= turn_extreme <= zone_upper,
        "M5 turn extreme does not engage the M15 location zone",
    )
    if direction == "LONG":
        require(stop_level < min(turn_extreme, retest_extreme, entry_level), "LONG stop is not beyond local curvature")
    else:
        require(stop_level > max(turn_extreme, retest_extreme, entry_level), "SHORT stop is not beyond local curvature")

    governing_invalidation = float(h1["governing_invalidation_level"])
    if direction == "LONG":
        require(governing_invalidation < entry_level, "LONG H1 invalidation must be below entry")
    else:
        require(governing_invalidation > entry_level, "SHORT H1 invalidation must be above entry")

    destination = _normalize_swing(
        destination_source, decision_at=decision_at, label="destination"
    )
    target_level = float(destination["level"])
    wanted_kind = "HIGH" if direction == "LONG" else "LOW"
    require(destination["kind"] == wanted_kind, "Destination kind disagrees with direction")
    if direction == "LONG":
        require(stop_level < entry_level < target_level, "LONG stop-entry-target geometry is invalid")
    else:
        require(target_level < entry_level < stop_level, "SHORT target-entry-stop geometry is invalid")

    range_payload: dict[str, Any] | None = None
    if family == "TREND":
        expected_state = "UPTREND" if direction == "LONG" else "DOWNTREND"
        require(str(h1.get("state")) == expected_state, "H1 trend state disagrees with direction")
        require(str(m15.get("setup_family")) == "PULLBACK_TO_CURVATURE", "Trend plan requires an M15 pullback")
        require(destination["timeframe"] == "H1", "Trend destination must be an H1 swing")
        require(
            str(destination_source.get("role")) == "H1_LIQUIDITY_SWING",
            "Trend destination role must be H1_LIQUIDITY_SWING",
        )
        target_policy = "PREEXISTING_UNCONSUMED_H1_LIQUIDITY_SWING"
    else:
        require(str(h1.get("state")) == "ACTIVE_RANGE", "Range plan requires ACTIVE_RANGE")
        require(str(m15.get("setup_family")) == "ROTATION_FROM_BOUNDARY", "Range plan requires M15 boundary rotation")
        lower = float(h1["lower_boundary"])
        upper = float(h1["upper_boundary"])
        require(lower < upper, "H1 range boundaries are invalid")
        midpoint = (lower + upper) / 2.0
        supplied_midpoint = float(h1.get("midpoint", midpoint))
        require(abs(supplied_midpoint - midpoint) <= 1e-9, "H1 range midpoint differs")
        if direction == "LONG":
            require(lower < entry_level <= midpoint, "Range LONG entry is not in the lower half")
            require(entry_level < target_level < upper, "Range LONG target is not internal and forward")
        else:
            require(midpoint <= entry_level < upper, "Range SHORT entry is not in the upper half")
            require(lower < target_level < entry_level, "Range SHORT target is not internal and forward")
        require(destination["timeframe"] == "M15", "Range destination must be internal M15 liquidity")
        require(
            str(destination_source.get("role")) == "RANGE_INTERNAL_LIQUIDITY",
            "Range destination role must be RANGE_INTERNAL_LIQUIDITY",
        )
        require(not bool(destination_source.get("is_range_boundary", False)), "Range boundary cannot be the automatic target")
        range_payload = {
            "lower_boundary": lower,
            "upper_boundary": upper,
            "midpoint": midpoint,
            "entry_half": "LOWER" if direction == "LONG" else "UPPER",
            "target_is_strictly_internal": True,
        }
        target_policy = "PREEXISTING_INTERNAL_M15_LIQUIDITY_NOT_RANGE_EXTREME"

    controlling_m15 = _normalize_swing(
        dict(m15["controlling_swing"]),
        decision_at=decision_at,
        label="M15 controlling swing",
    )
    require(controlling_m15["timeframe"] == "M15", "Controlling swing must be M15")

    payload: dict[str, Any] = {
        "ruleset": RULESET,
        "sample_id": sample_id,
        "title": str(spec["title"]),
        "synthetic": bool(spec.get("synthetic", False)),
        "decision_at": decision_at,
        "family": family,
        "direction": direction,
        "governing_h1_auction": {
            "state": str(h1["state"]),
            "known_at": h1_known_at,
            "governing_invalidation_level": governing_invalidation,
            "range": range_payload,
            "role": "GOVERNS_DIRECTION_AND_DESTINATION_NOT_ENTRY",
        },
        "m15_setup": {
            "identity": str(m15["identity"]),
            "known_at": m15_known_at,
            "setup_family": str(m15["setup_family"]),
            "controlling_swing": controlling_m15,
            "zone_lower": zone_lower,
            "zone_upper": zone_upper,
            "role": "LOCAL_LOCATION_AND_TURNING_STRUCTURE",
        },
        "m5_execution": {
            "identity": str(m5["identity"]),
            "turn_known_at": turn_known_at,
            "retest_known_at": retest_known_at,
            "turn_extreme": turn_extreme,
            "retest_extreme": retest_extreme,
            "sequence": "TURN_THEN_FIRST_VALID_RETEST",
            "role": "ENTRY_TIMING_AND_LOCAL_INVALIDATION",
        },
        "entry": {
            "level": entry_level,
            "activated_at": decision_at,
            "source": "M5_CONFIRMED_RETEST_CLOSE",
        },
        "invalidation": {
            "level": stop_level,
            "source": "BEYOND_M5_TURN_RETEST_CURVATURE",
            "governing_h1_level": governing_invalidation,
        },
        "destination": {
            **destination,
            "role": str(destination_source["role"]),
            "target_policy": target_policy,
        },
        "guards": {
            "h1_governs": True,
            "m15_sets_up": True,
            "m5_executes": True,
            "trend_target_is_h1_swing": family == "TREND",
            "range_target_is_internal_not_extreme": family == "RANGE",
            "outcome_data_present": False,
            "performance_calculated": False,
        },
        "epistemic_status": {
            "ohlc": (
                "SYNTHETIC_FOR_SEMANTIC_PROOF"
                if bool(spec.get("synthetic", False))
                else "OBSERVED_SEALED_XAUUSD"
            ),
            "structure_and_liquidity_roles": "CALCULATED",
            "auction_interpretation": "INFERRED",
            "resting_orders_or_institutional_intent": "UNKNOWN",
        },
    }
    payload["plan_identity"] = canonical_hash(
        [
            RULESET,
            sample_id,
            decision_at,
            family,
            direction,
            m15["identity"],
            m5["identity"],
            destination["identity"],
        ]
    )
    assert_outcome_blind(payload)
    payload["plan_sha256"] = canonical_hash(payload)
    return payload


def _base_spec(
    *,
    sample_id: str,
    title: str,
    family: AuctionFamily,
    direction: Direction,
    state: str,
    entry: float,
    stop: float,
    target: float,
    target_timeframe: str,
    target_role: str,
    governing_invalidation: float,
    zone_lower: float,
    zone_upper: float,
    turn_extreme: float,
    retest_extreme: float,
    controlling_level: float,
    range_bounds: tuple[float, float] | None = None,
) -> dict[str, Any]:
    decision_at = "2024-01-09T14:30:00Z"
    h1: dict[str, Any] = {
        "state": state,
        "known_at": "2024-01-09T12:00:00Z",
        "governing_invalidation_level": governing_invalidation,
    }
    if range_bounds is not None:
        h1.update({
            "lower_boundary": range_bounds[0],
            "upper_boundary": range_bounds[1],
            "midpoint": sum(range_bounds) / 2.0,
        })
    setup_family = "PULLBACK_TO_CURVATURE" if family == "TREND" else "ROTATION_FROM_BOUNDARY"
    return {
        "sample_id": sample_id,
        "title": title,
        "synthetic": True,
        "family": family,
        "direction": direction,
        "decision_at": decision_at,
        "h1_context": h1,
        "m15_setup": {
            "identity": f"{sample_id}-M15",
            "direction": direction,
            "governing_h1_state": state,
            "setup_family": setup_family,
            "known_at": "2024-01-09T14:15:00Z",
            "zone_lower": zone_lower,
            "zone_upper": zone_upper,
            "controlling_swing": {
                "identity": f"{sample_id}-M15-CONTROL",
                "timeframe": "M15",
                "kind": "LOW" if direction == "LONG" else "HIGH",
                "level": controlling_level,
                "known_at": "2024-01-09T13:45:00Z",
                "liquidity_state": "UNCONSUMED_ENGAGED",
            },
        },
        "m5_trigger": {
            "identity": f"{sample_id}-M5",
            "direction": direction,
            "sequence": "TURN_THEN_FIRST_VALID_RETEST",
            "turn_known_at": "2024-01-09T14:20:00Z",
            "retest_known_at": decision_at,
            "turn_extreme": turn_extreme,
            "retest_extreme": retest_extreme,
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
            "identity": f"{sample_id}-DESTINATION",
            "timeframe": target_timeframe,
            "kind": "HIGH" if direction == "LONG" else "LOW",
            "level": target,
            "known_at": "2024-01-09T11:00:00Z",
            "liquidity_state": "UNCONSUMED_UNTOUCHED",
            "role": target_role,
            "is_range_boundary": False,
        },
    }


def synthetic_plan_specs() -> list[dict[str, Any]]:
    """Four symmetric predecision examples used for semantic certification."""

    return [
        _base_spec(
            sample_id="SYN_TREND_SHORT",
            title="H1 downtrend · M15 pullback · M5 short",
            family="TREND",
            direction="SHORT",
            state="DOWNTREND",
            entry=2038.4,
            stop=2042.4,
            target=2010.0,
            target_timeframe="H1",
            target_role="H1_LIQUIDITY_SWING",
            governing_invalidation=2050.0,
            zone_lower=2038.0,
            zone_upper=2042.0,
            turn_extreme=2041.6,
            retest_extreme=2041.2,
            controlling_level=2042.0,
        ),
        _base_spec(
            sample_id="SYN_TREND_LONG",
            title="H1 uptrend · M15 pullback · M5 long",
            family="TREND",
            direction="LONG",
            state="UPTREND",
            entry=2021.6,
            stop=2017.6,
            target=2050.0,
            target_timeframe="H1",
            target_role="H1_LIQUIDITY_SWING",
            governing_invalidation=2010.0,
            zone_lower=2018.0,
            zone_upper=2022.0,
            turn_extreme=2018.4,
            retest_extreme=2018.8,
            controlling_level=2018.0,
        ),
        _base_spec(
            sample_id="SYN_RANGE_SHORT",
            title="H1 range upper rotation · M15/M5 short",
            family="RANGE",
            direction="SHORT",
            state="ACTIVE_RANGE",
            entry=2035.0,
            stop=2040.6,
            target=2023.0,
            target_timeframe="M15",
            target_role="RANGE_INTERNAL_LIQUIDITY",
            governing_invalidation=2040.0,
            zone_lower=2035.0,
            zone_upper=2040.0,
            turn_extreme=2039.6,
            retest_extreme=2039.1,
            controlling_level=2040.0,
            range_bounds=(2000.0, 2040.0),
        ),
        _base_spec(
            sample_id="SYN_RANGE_LONG",
            title="H1 range lower rotation · M15/M5 long",
            family="RANGE",
            direction="LONG",
            state="ACTIVE_RANGE",
            entry=2005.0,
            stop=1999.4,
            target=2017.0,
            target_timeframe="M15",
            target_role="RANGE_INTERNAL_LIQUIDITY",
            governing_invalidation=2000.0,
            zone_lower=2000.0,
            zone_upper=2005.0,
            turn_extreme=2000.4,
            retest_extreme=2000.9,
            controlling_level=2000.0,
            range_bounds=(2000.0, 2040.0),
        ),
    ]


def synthetic_proof() -> dict[str, Any]:
    plans = [compile_trade_plan(spec) for spec in synthetic_plan_specs()]
    by_id = {plan["sample_id"]: plan for plan in plans}

    def rejects(spec: dict[str, Any]) -> bool:
        try:
            compile_trade_plan(spec)
        except (ValueError, RuntimeError):
            return True
        return False

    lookup = {spec["sample_id"]: spec for spec in synthetic_plan_specs()}
    range_extreme = copy.deepcopy(lookup["SYN_RANGE_SHORT"])
    range_extreme["destination"]["level"] = range_extreme["h1_context"]["lower_boundary"]
    range_extreme["destination"]["is_range_boundary"] = True
    trend_m15_target = copy.deepcopy(lookup["SYN_TREND_SHORT"])
    trend_m15_target["destination"]["timeframe"] = "M15"
    future_destination = copy.deepcopy(lookup["SYN_TREND_LONG"])
    future_destination["destination"]["known_at"] = "2024-01-09T14:31:00Z"
    h1_entry = copy.deepcopy(lookup["SYN_TREND_LONG"])
    h1_entry["entry"]["source"] = "H1_PIVOT_CONFIRMATION"
    inside_stop = copy.deepcopy(lookup["SYN_TREND_SHORT"])
    inside_stop["invalidation"]["level"] = inside_stop["m5_trigger"]["turn_extreme"]
    checks = {
        "four_symmetric_plans_compile": len(plans) == 4 and len(by_id) == 4,
        "trend_short_targets_h1_low": (
            by_id["SYN_TREND_SHORT"]["destination"]["timeframe"] == "H1"
            and by_id["SYN_TREND_SHORT"]["destination"]["kind"] == "LOW"
        ),
        "trend_long_targets_h1_high": (
            by_id["SYN_TREND_LONG"]["destination"]["timeframe"] == "H1"
            and by_id["SYN_TREND_LONG"]["destination"]["kind"] == "HIGH"
        ),
        "range_short_targets_internal_m15": (
            by_id["SYN_RANGE_SHORT"]["destination"]["timeframe"] == "M15"
            and by_id["SYN_RANGE_SHORT"]["governing_h1_auction"]["range"]["lower_boundary"]
            < by_id["SYN_RANGE_SHORT"]["destination"]["level"]
            < by_id["SYN_RANGE_SHORT"]["entry"]["level"]
        ),
        "range_long_targets_internal_m15": (
            by_id["SYN_RANGE_LONG"]["destination"]["timeframe"] == "M15"
            and by_id["SYN_RANGE_LONG"]["entry"]["level"]
            < by_id["SYN_RANGE_LONG"]["destination"]["level"]
            < by_id["SYN_RANGE_LONG"]["governing_h1_auction"]["range"]["upper_boundary"]
        ),
        "all_plans_are_outcome_blind": all(
            not plan["guards"]["outcome_data_present"]
            and not plan["guards"]["performance_calculated"]
            for plan in plans
        ),
        "opposite_range_extreme_is_rejected": rejects(range_extreme),
        "trend_m15_target_is_rejected": rejects(trend_m15_target),
        "future_known_destination_is_rejected": rejects(future_destination),
        "h1_entry_source_is_rejected": rejects(h1_entry),
        "stop_inside_m5_curvature_is_rejected": rejects(inside_stop),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Synthetic H1-governed plan proof failed: {checks}")
    return {
        "checks": checks,
        "plans_sha256": canonical_hash(plans),
        "proof_sha256": canonical_hash(checks),
    }
