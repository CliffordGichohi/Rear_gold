"""Point-in-time LONG opportunity deduplication and structural management.

This module is intentionally independent of file I/O and model fitting.  It
adds two narrowly scoped behaviours to the already-frozen LONG auction
translator:

* emit a later opportunity only after a genuinely new signal episode or a new
  active M15 bullish structure identity; and
* replace fixed-R protection with causal M5 governing-structure management.

All decisions use completed bars.  Outcome paths are consumed only by the
execution simulator after the opportunity and geometry have been fixed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    complete_rows,
    confirmed_swings,
    iso,
    parse_dt,
    structural_breaks,
    true_ranges_and_atr,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (
    RISK_BUDGET_USD,
    RUNNER_FRACTION,
    TARGET_ACCEPTANCE_ATR,
)

LONG_SIGNAL_THRESHOLD = 0.90
REARM_BELOW_MINUTES = 15
STRUCTURAL_STOP_BUFFER_ATR = 0.05
TICK_FLOOR = 0.02


def signal_episodes(
    checkpoints: Sequence[dict[str, Any]],
    probabilities: Sequence[float],
    *,
    structure_identities: Sequence[str | None] | None = None,
    session: str = "NEW_YORK",
    threshold: float = LONG_SIGNAL_THRESHOLD,
    rearm_below_minutes: int = REARM_BELOW_MINUTES,
) -> list[dict[str, Any]]:
    """Return value-blind, deduplicated LONG signal episodes.

    The first threshold crossing is eligible.  A subsequent crossing requires
    ``rearm_below_minutes`` consecutive below-threshold checkpoints.  A newly
    active M15 bullish structure identity may also emit one opportunity while
    the probability remains above threshold.  Merely remaining above the
    threshold never creates repeated minute-by-minute setups.
    """

    if len(checkpoints) != len(probabilities):
        raise ValueError("checkpoint/probability length differs")
    identities = (
        list(structure_identities)
        if structure_identities is not None
        else [None] * len(checkpoints)
    )
    if len(identities) != len(checkpoints):
        raise ValueError("checkpoint/structure-identity length differs")
    if rearm_below_minutes < 1:
        raise ValueError("rearm_below_minutes must be positive")

    emitted: list[dict[str, Any]] = []
    armed = True
    below_count = 0
    last_emitted_structure: str | None = None
    episode = 0
    for row, raw_probability, structure_identity in zip(
        checkpoints, probabilities, identities, strict=True
    ):
        if str(row.get("session")) != session:
            continue
        probability = float(raw_probability)
        if probability < threshold:
            below_count += 1
            if below_count >= rearm_below_minutes:
                armed = True
            continue

        new_structure = (
            structure_identity is not None
            and last_emitted_structure is not None
            and structure_identity != last_emitted_structure
        )
        if not armed and not new_structure:
            below_count = 0
            continue

        episode += 1
        reason = "THRESHOLD_REARM" if armed else "NEW_M15_BULLISH_STRUCTURE"
        payload = {
            "episode": episode,
            "checkpoint_at": str(row["checkpoint_at"]),
            "session": session,
            "probability": probability,
            "emission_reason": reason,
            "m15_structure_identity": structure_identity,
            "checkpoint": row,
        }
        payload["episode_identity"] = canonical_hash(
            {
                key: value
                for key, value in payload.items()
                if key not in {"checkpoint", "episode_identity"}
            }
        )
        emitted.append(payload)
        armed = False
        below_count = 0
        last_emitted_structure = structure_identity
    return emitted


def _bar_containing(
    rows: Sequence[dict[str, Any]], timestamp: str
) -> dict[str, Any] | None:
    point = parse_dt(timestamp)
    for row in rows:
        if parse_dt(row["open_at"]) <= point < parse_dt(row["close_at"]):
            return row
    return None


def _core_runner_split(quantity: int) -> tuple[int, int]:
    runner = int(RUNNER_FRACTION * quantity)
    return quantity - runner, runner


def _empty_result(classification: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "track": "M5_STRUCTURAL_MANAGEMENT_V1",
        "executed": False,
        "resolution": str(classification["primary_disposition"]),
        "net_usd": 0.0,
        "net_r50": 0.0,
        "stressed_1_5x_cost_net_usd": 0.0,
        "stressed_1_5x_cost_r50": 0.0,
        "legs": [],
        "structural_events": [],
    }
    payload["result_hash"] = canonical_hash(payload)
    return payload


def build_structural_cache(stream: dict[str, Any]) -> dict[str, Any]:
    """Calculate immutable full-day M5 structural objects once per case.

    The objects retain their causal ``detected_at``/``break_at`` timestamps;
    callers must still filter them at each decision timestamp.
    """

    _, swings = confirmed_swings(
        stream["timeframes"]["5m"], stream["end_exclusive"], "M5"
    )
    bullish = structural_breaks(
        stream["timeframes"]["5m"], stream["end_exclusive"], "M5", "LONG"
    )
    bearish = structural_breaks(
        stream["timeframes"]["5m"], stream["end_exclusive"], "M5", "SHORT"
    )
    payload = {
        "swings": swings,
        "bullish_events": bullish,
        "bearish_events": bearish,
    }
    payload["cache_sha256"] = canonical_hash(payload)
    return payload


def simulate_structural_long(
    *,
    classification: dict[str, Any],
    stream: dict[str, Any],
    fill_at: str,
    structure_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Simulate the frozen causal M5 structural-management alternative.

    The initial stop, target, deadline, sizing and cost convention are kept.
    A newly completed bullish M5 break may raise the stop behind its confirmed
    protected low.  A completed bearish M5 break of the current governing low
    exits at the next M1 open.  Same-bar ambiguity remains stop-first.
    """

    if not classification["admitted"]:
        return _empty_result(classification)
    if classification["direction"] != "LONG":
        raise ValueError("structural-management V1 is LONG-only")

    fill = float(classification["fill"])
    initial_stop = float(classification["stop"])
    target = float(classification["target"])
    quantity = int(classification["quantity_ounces"])
    cost_per_ounce = float(classification["cost_per_ounce"])
    runner_enabled = classification["family"] == "CONTINUATION_WITH_ROOM"
    opened = parse_dt(fill_at)
    deadline = parse_dt(stream["end_exclusive"])
    path = [
        row
        for row in complete_rows(stream["timeframes"]["1m"], deadline)
        if opened <= parse_dt(row["open_at"]) < deadline
    ]
    if not path:
        raise RuntimeError("Missing post-fill M1 path")
    m15 = complete_rows(stream["timeframes"]["15m"], deadline)
    _, m15_atrs = true_ranges_and_atr(m15)
    m15_index = {
        (iso(row["open_at"]), iso(row["available_at"])): index
        for index, row in enumerate(m15)
    }

    cache = structure_cache if structure_cache is not None else build_structural_cache(stream)
    entry_swings = [
        row
        for row in cache["swings"]
        if parse_dt(row["detected_at"]) <= opened
    ]
    known_lows = [row for row in entry_swings if row["kind"] == "LOW"]
    governing = known_lows[-1] if known_lows else None
    governing_identity = None if governing is None else str(governing["identity"])
    governing_level = None if governing is None else float(governing["level"])

    bullish_events = [
        event for event in cache["bullish_events"] if parse_dt(event["break_at"]) >= opened
    ]
    bearish_events = [
        event for event in cache["bearish_events"] if parse_dt(event["break_at"]) >= opened
    ]
    events_by_time: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for direction, events in (("LONG", bullish_events), ("SHORT", bearish_events)):
        for event in events:
            events_by_time.setdefault(str(event["break_at"]), []).append((direction, event))

    current_stop = initial_stop
    structural_events: list[dict[str, Any]] = []
    processed_event_ids: set[str] = set()
    target_touched = False
    target_touch_m15: dict[str, Any] | None = None
    target_acceptance: bool | None = None
    runner_active = False
    core_quantity, runner_quantity = (
        _core_runner_split(quantity) if runner_enabled else (quantity, 0)
    )
    remaining = quantity
    legs: list[dict[str, Any]] = []
    path_high = fill
    path_low = fill

    def append_leg(qty: int, price: float, at: str, resolution: str) -> None:
        nonlocal remaining
        if qty <= 0:
            return
        legs.append(
            {
                "quantity_ounces": qty,
                "exit_price": float(price),
                "exit_at": iso(at),
                "resolution": resolution,
            }
        )
        remaining -= qty

    for row in path:
        current_at = iso(row["open_at"])
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        path_high = max(path_high, high)
        path_low = min(path_low, low)

        failed_governing_structure = False
        eligible_event_times = sorted(
            timestamp
            for timestamp in events_by_time
            if opened < parse_dt(timestamp) <= parse_dt(current_at)
        )
        for timestamp in eligible_event_times:
            for event_direction, event in events_by_time[timestamp]:
                identity = str(event["identity"])
                if identity in processed_event_ids:
                    continue
                processed_event_ids.add(identity)
                if event_direction == "LONG":
                    protected_level = float(event["protected_level"])
                    candidate_stop = protected_level - max(
                        STRUCTURAL_STOP_BUFFER_ATR * float(event["atr"]), TICK_FLOOR
                    )
                    prior_stop = current_stop
                    if candidate_stop > current_stop:
                        current_stop = candidate_stop
                    if governing_level is None or protected_level >= governing_level:
                        governing_identity = str(event["protected_identity"])
                        governing_level = protected_level
                    structural_events.append(
                        {
                            "at": timestamp,
                            "event_identity": identity,
                            "action": "BULLISH_BREAK_PROTECT",
                            "prior_stop": prior_stop,
                            "new_stop": current_stop,
                            "governing_identity": governing_identity,
                            "governing_level": governing_level,
                        }
                    )
                elif (
                    governing_identity is not None
                    and str(event["broken_identity"]) == governing_identity
                ):
                    structural_events.append(
                        {
                            "at": timestamp,
                            "event_identity": identity,
                            "action": "BEARISH_BREAK_GOVERNING_FAILURE",
                            "governing_identity": governing_identity,
                            "governing_level": governing_level,
                        }
                    )
                    failed_governing_structure = True

        if failed_governing_structure and remaining > 0:
            append_leg(remaining, open_price, current_at, "M5_GOVERNING_STRUCTURE_EXIT")
            break

        gap_stopped = open_price <= current_stop
        if gap_stopped:
            append_leg(remaining, open_price, current_at, "GAP_STOP")
            break
        if low <= current_stop:
            reason = (
                "M5_STRUCTURAL_PROTECTED_STOP"
                if current_stop > initial_stop
                else "STRUCTURAL_STOP"
            )
            append_leg(remaining, current_stop, current_at, reason)
            break

        reached_target = high >= target
        if reached_target and not target_touched:
            target_touched = True
            if runner_quantity <= 0:
                append_leg(remaining, target, current_at, "SEALED_TARGET")
            else:
                target_touch_m15 = _bar_containing(m15, current_at)
                append_leg(min(core_quantity, remaining), target, current_at, "SEALED_TARGET_CORE")
                if target_touch_m15 is None and remaining > 0:
                    target_acceptance = False
                    append_leg(remaining, target, current_at, "RUNNER_CONTEXT_UNAVAILABLE")
        if remaining <= 0:
            break

        newly_completed_m15 = [
            bar
            for bar in m15
            if target_touched
            and target_acceptance is None
            and target_touch_m15 is not None
            and iso(bar["open_at"]) == iso(target_touch_m15["open_at"])
            and parse_dt(bar["available_at"]) <= parse_dt(current_at)
        ]
        if newly_completed_m15:
            completed = newly_completed_m15[0]
            index = m15_index[(iso(completed["open_at"]), iso(completed["available_at"]))]
            atr = m15_atrs[index]
            target_acceptance = bool(
                atr is not None and float(completed["close"]) - target >= TARGET_ACCEPTANCE_ATR * atr
            )
            if target_acceptance:
                runner_active = True
            elif remaining > 0:
                append_leg(remaining, open_price, current_at, "RUNNER_NO_TARGET_ACCEPTANCE")
                break

    if remaining > 0:
        last = path[-1]
        append_leg(remaining, float(last["close"]), last["close_at"], "UTC_DAY_TIME_EXIT")

    gross = sum(
        (float(leg["exit_price"]) - fill) * int(leg["quantity_ounces"])
        for leg in legs
    )
    total_cost = cost_per_ounce * quantity
    net = gross - total_cost
    stressed = gross - 1.5 * total_cost
    payload: dict[str, Any] = {
        "track": "M5_STRUCTURAL_MANAGEMENT_V1",
        "executed": True,
        "resolution": str(legs[-1]["resolution"]),
        "final_at": str(legs[-1]["exit_at"]),
        "quantity_ounces": quantity,
        "legs": legs,
        "initial_stop": initial_stop,
        "final_stop": current_stop,
        "initial_governing_identity": None if governing is None else str(governing["identity"]),
        "initial_governing_level": None if governing is None else float(governing["level"]),
        "final_governing_identity": governing_identity,
        "final_governing_level": governing_level,
        "structural_events": structural_events,
        "target_touched": target_touched,
        "target_acceptance": target_acceptance,
        "runner_activated": runner_active,
        "gross_usd": gross,
        "cost_usd": total_cost,
        "net_usd": net,
        "net_r50": net / RISK_BUDGET_USD,
        "stressed_1_5x_cost_net_usd": stressed,
        "stressed_1_5x_cost_r50": stressed / RISK_BUDGET_USD,
        "mfe_r50": (path_high - fill) * quantity / RISK_BUDGET_USD,
        "mae_r50": (fill - path_low) * quantity / RISK_BUDGET_USD,
    }
    payload["result_hash"] = canonical_hash(payload)
    return payload


def non_overlapping(
    opportunities: Sequence[dict[str, Any]],
    *,
    occupied_until: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the frozen one-open-position policy in chronological order."""

    accepted: list[dict[str, Any]] = []
    audited: list[dict[str, Any]] = []
    current_until = parse_dt(occupied_until) if occupied_until else None
    for opportunity in opportunities:
        signal_at = parse_dt(opportunity["signal_at"])
        result = opportunity.get("result")
        if current_until is not None and signal_at <= current_until:
            audited.append({**opportunity, "portfolio_disposition": "OVERLAP_EXISTING_POSITION"})
            continue
        if result is None or result.get("executed") is not True:
            audited.append({**opportunity, "portfolio_disposition": "NO_EXECUTED_TRADE"})
            continue
        accepted.append(opportunity)
        current_until = parse_dt(result["final_at"])
        audited.append({**opportunity, "portfolio_disposition": "ACCEPTED"})
    return accepted, audited
