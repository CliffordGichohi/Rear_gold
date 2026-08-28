"""Book-aligned structural execution research for the frozen hybrid direction."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import timedelta
from typing import Any

import gold_intel.analytics.auction_trade_placement_outcomes_v1 as base
from gold_intel.analytics.auction_liquidity_hierarchy_hybrid_router_v1 import (
    _execution_with_quantity,
    resolve_risk_controlled,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    iso,
    parse_dt,
)

RULESET = "GOLD_HYBRID_STRUCTURAL_EXECUTION_RESEARCH_V1"
ENTRY_MODES = (
    "E0_CONTROL_MECHANICAL",
    "E1_IMMEDIATE_LOCAL_M15_INVALIDATION",
    "E2_M5_SWEEP_RECLAIM_POST_STRUCTURE",
)
EXIT_MODES = (
    "T0_PRIMARY_LIQUIDITY_FULL",
    "T1_LOCAL_M15_FIRST_FULL",
    "T2_HALF_AT_1R_THEN_PRIMARY",
)
POLICY_IDS = tuple(f"{entry}::{exit_mode}" for entry in ENTRY_MODES for exit_mode in EXIT_MODES)


def policy_id(entry_mode: str, exit_mode: str) -> str:
    if entry_mode not in ENTRY_MODES or exit_mode not in EXIT_MODES:
        raise ValueError(f"Unregistered policy: {entry_mode}::{exit_mode}")
    return f"{entry_mode}::{exit_mode}"


def _directional_distance(direction: str, start: float, end: float) -> float:
    if direction == "LONG":
        return end - start
    if direction == "SHORT":
        return start - end
    raise ValueError(f"Unsupported direction: {direction}")


def original_quantity(row: Mapping[str, Any]) -> int:
    value = row.get("original_quantity_ounces")
    if value is not None:
        return int(value)
    plan = row.get("plan")
    if plan is None:
        raise ValueError(f"No plan for quantity: {row['event_identity']}")
    risk = abs(float(plan["entry"]) - float(plan["stop"]))
    quantity = math.floor(base.RISK_BUDGET_USD / risk)
    if quantity < 1:
        raise ValueError(f"Original quantity is infeasible: {row['event_identity']}")
    return quantity


def decision_m15_buffer(event: Mapping[str, Any]) -> float | None:
    active = event.get("active_breaks", {}).get("M15")
    if active is None or active.get("buffer") is None:
        return None
    value = float(active["buffer"])
    return value if value > 0 else None


def _apply_target_mode(
    plan: dict[str, Any], *, route_action: str, exit_mode: str
) -> dict[str, Any]:
    output = deepcopy(plan)
    output["execution_research_exit_mode"] = exit_mode
    output["primary_target"] = deepcopy(output["target"])
    output["target_replaced_by_local_m15"] = False
    if exit_mode != "T1_LOCAL_M15_FIRST_FULL" or route_action != "PRESERVE":
        return output
    local = output.get("local_m15_liquidity")
    if not isinstance(local, Mapping) or local.get("level") is None:
        return output
    direction = str(output["direction"])
    entry = float(output["entry"])
    primary = float(output["target"]["level"])
    local_level = float(local["level"])
    primary_distance = _directional_distance(direction, entry, primary)
    local_distance = _directional_distance(direction, entry, local_level)
    if local_distance <= 0 or primary_distance <= 0 or local_distance >= primary_distance:
        return output
    replacement = deepcopy(dict(local))
    replacement["source_rule"] = "NEAREST_POINT_IN_TIME_LOCAL_M15_DESTINATION"
    output["target"] = replacement
    output["target_rule"] = "LOCAL_M15_DESTINATION_WHEN_CLOSER_THAN_PRIMARY"
    output["target_replaced_by_local_m15"] = True
    return output


def prepare_static_plan(
    row: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    entry_mode: str,
    exit_mode: str,
) -> dict[str, Any]:
    """Prepare only point-in-time fields; E2 confirmation remains unresolved."""

    identifier = policy_id(entry_mode, exit_mode)
    if not row["mechanically_executable"]:
        return {
            "policy_id": identifier,
            "event_identity": str(row["event_identity"]),
            "disposition": "NOT_EXECUTABLE_HARD_REASON",
            "plan": None,
        }
    plan = deepcopy(dict(row["plan"]))
    action = str(row["hybrid_route_action"])
    plan = _apply_target_mode(plan, route_action=action, exit_mode=exit_mode)
    plan["execution_research_policy_id"] = identifier
    plan["execution_research_entry_mode"] = entry_mode
    plan["original_decision_at"] = str(row["decision_at"])
    plan["original_quantity_ounces"] = original_quantity(row)
    plan["partial_at_1r"] = exit_mode == "T2_HALF_AT_1R_THEN_PRIMARY"
    plan["route_action"] = action
    plan["route_reason"] = str(row["hybrid_route_reason"])
    if action != "NEGATE" or entry_mode == "E0_CONTROL_MECHANICAL":
        disposition = "STATIC_PLAN_READY"
    else:
        local = plan.get("local_m15_liquidity")
        buffer = decision_m15_buffer(event)
        if not isinstance(local, Mapping) or local.get("level") is None or buffer is None:
            return {
                "policy_id": identifier,
                "event_identity": str(row["event_identity"]),
                "disposition": "NO_TRADE_UNRESOLVED_LOCAL_INVALIDATION",
                "plan": None,
            }
        plan["local_invalidation_reference"] = deepcopy(dict(local))
        plan["decision_m15_buffer"] = buffer
        if entry_mode == "E1_IMMEDIATE_LOCAL_M15_INVALIDATION":
            level = float(local["level"])
            plan["stop"] = level - buffer if plan["direction"] == "LONG" else level + buffer
            plan["stop_rule"] = "LOCAL_M15_REFERENCE_FAR_SIDE_PLUS_DECISION_M15_BUFFER"
            disposition = "STATIC_PLAN_READY"
        else:
            plan["stop"] = None
            plan["stop_rule"] = "PENDING_FIRST_COMPLETED_M5_SWEEP_RECLAIM_EXTREME_PLUS_BUFFER"
            disposition = "PENDING_M5_SWEEP_RECLAIM"
    if plan["stop"] is not None:
        risk = _directional_distance(
            str(plan["direction"]), float(plan["stop"]), float(plan["entry"])
        )
        reward = _directional_distance(
            str(plan["direction"]), float(plan["entry"]), float(plan["target"]["level"])
        )
        if risk <= 0 or reward <= 0:
            return {
                "policy_id": identifier,
                "event_identity": str(row["event_identity"]),
                "disposition": "NO_TRADE_INVALID_STATIC_GEOMETRY",
                "plan": None,
            }
        plan["risk_price"] = risk
        plan["reward_price"] = reward
        plan["planned_r"] = reward / risk
    plan.pop("plan_sha256", None)
    plan["plan_sha256"] = canonical_hash(plan)
    return {
        "policy_id": identifier,
        "event_identity": str(row["event_identity"]),
        "disposition": disposition,
        "plan": plan,
        "static_plan_sha256": plan["plan_sha256"],
    }


def completed_m5_bars(
    rows: Sequence[Mapping[str, Any]], *, start_at: str, end_at: str
) -> list[dict[str, Any]]:
    """Build UTC-aligned complete M5 bars from exact [start, end) M1 rows."""

    start = parse_dt(start_at)
    end = parse_dt(end_at)
    usable = sorted(
        (
            dict(row)
            for row in rows
            if row.get("complete") is True
            and start <= parse_dt(str(row["open_at"])) < end
        ),
        key=lambda row: parse_dt(str(row["open_at"])),
    )
    groups: dict[Any, list[dict[str, Any]]] = {}
    for row in usable:
        point = parse_dt(str(row["open_at"]))
        group_start = point.replace(minute=(point.minute // 5) * 5, second=0, microsecond=0)
        if group_start < start:
            continue
        groups.setdefault(group_start, []).append(row)
    output: list[dict[str, Any]] = []
    for group_start in sorted(groups):
        members = groups[group_start]
        expected = [group_start + timedelta(minutes=index) for index in range(5)]
        observed = [parse_dt(str(row["open_at"])) for row in members]
        if observed != expected:
            continue
        group_end = group_start + timedelta(minutes=5)
        if group_end >= end:
            continue
        if any(parse_dt(str(row["available_at"])) > group_end for row in members):
            continue
        payload = {
            "open_at": iso(group_start),
            "close_at": iso(group_end),
            "available_at": iso(group_end),
            "open": float(members[0]["open"]),
            "high": max(float(row["high"]) for row in members),
            "low": min(float(row["low"]) for row in members),
            "close": float(members[-1]["close"]),
            "source_bar_ids": [str(row.get("bar_id")) for row in members],
        }
        payload["m5_bar_sha256"] = canonical_hash(payload)
        output.append(payload)
    return output


def apply_sweep_reclaim_confirmation(
    plan: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    direction = str(plan["direction"])
    local = dict(plan["local_invalidation_reference"])
    level = float(local["level"])
    buffer = float(plan["decision_m15_buffer"])
    deadline = base.session_deadline(str(plan["original_decision_at"]))
    bars = completed_m5_bars(
        rows,
        start_at=str(plan["original_decision_at"]),
        end_at=iso(deadline),
    )
    confirmation = None
    for bar in bars:
        if direction == "LONG":
            qualifies = float(bar["low"]) < level and float(bar["close"]) > level
        else:
            qualifies = float(bar["high"]) > level and float(bar["close"]) < level
        if qualifies and parse_dt(str(bar["close_at"])) + timedelta(minutes=1) < deadline:
            confirmation = bar
            break
    if confirmation is None:
        return None
    output = deepcopy(dict(plan))
    output["decision_at"] = str(confirmation["close_at"])
    output["entry"] = float(confirmation["close"])
    output["entry_rule"] = "FIRST_COMPLETED_M5_LOCAL_LIQUIDITY_SWEEP_RECLAIM_PLUS_1M_LATENCY"
    output["stop"] = (
        float(confirmation["low"]) - buffer
        if direction == "LONG"
        else float(confirmation["high"]) + buffer
    )
    output["confirmation"] = confirmation
    risk = _directional_distance(direction, float(output["stop"]), float(output["entry"]))
    reward = _directional_distance(
        direction, float(output["entry"]), float(output["target"]["level"])
    )
    if risk <= 0 or reward <= 0:
        return None
    output["risk_price"] = risk
    output["reward_price"] = reward
    output["planned_r"] = reward / risk
    output.pop("plan_sha256", None)
    output["plan_sha256"] = canonical_hash(output)
    return output


def selected_quantity(plan: Mapping[str, Any]) -> int:
    distance = abs(float(plan["entry"]) - float(plan["stop"]))
    risk_limited = math.floor(base.RISK_BUDGET_USD / distance)
    return min(int(plan["original_quantity_ounces"]), risk_limited)


def _market_exit_price(direction: str, raw: float, row: Mapping[str, Any]) -> float:
    half_spread = base.spread(dict(row)) / 2.0
    if direction == "LONG":
        return raw - half_spread - base.SLIPPAGE_PRICE
    return raw + half_spread + base.SLIPPAGE_PRICE


def _partial_execution(
    plan: dict[str, Any], rows: list[dict[str, Any]], quantity: int
) -> dict[str, Any]:
    direction = str(plan["direction"])
    sign = 1.0 if direction == "LONG" else -1.0
    decision = parse_dt(str(plan["decision_at"]))
    effective_at = decision + timedelta(minutes=base.LATENCY_MINUTES)
    deadline = base.session_deadline(str(plan["original_decision_at"]))
    path = base._complete_path(rows, effective_at, deadline)
    if not path:
        raise RuntimeError(f"No executable outcome path for {plan['event_identity']}")
    fill_bar = path[0]
    raw_fill = float(fill_bar["open"])
    fill = (
        raw_fill + base.spread(fill_bar) / 2.0 + base.SLIPPAGE_PRICE
        if direction == "LONG"
        else raw_fill - base.spread(fill_bar) / 2.0 - base.SLIPPAGE_PRICE
    )
    stop = float(plan["stop"])
    target = float(plan["target"]["level"])
    displayed_risk = abs(float(plan["entry"]) - stop)
    effective_risk = sign * (fill - stop)
    effective_reward = sign * (target - fill)
    eligible_partial = quantity >= 2 and effective_risk > 0 and effective_reward > effective_risk
    partial_quantity = quantity // 2 if eligible_partial else 0
    remaining = quantity
    partial_price = fill + sign * effective_risk
    partial_done = False
    partial_pnl = 0.0
    resolution = "TIME_EXIT"
    exit_bar = path[-1]
    raw_exit = float(exit_bar["close"])
    actual_exit = _market_exit_price(direction, raw_exit, exit_bar)
    used_path = path
    ambiguous = False
    if effective_risk <= 0 or effective_reward <= 0:
        exit_bar = path[1] if len(path) > 1 else path[0]
        raw_exit = float(exit_bar["open"] if len(path) > 1 else exit_bar["close"])
        actual_exit = _market_exit_price(direction, raw_exit, exit_bar)
        used_path = path[:2]
        resolution = "POST_FILL_GEOMETRY_INVALID"
        eligible_partial = False
        partial_quantity = 0
        partial_price = fill
        remaining = quantity
        pnl = sign * (actual_exit - fill) * quantity
        mfe_r, mae_r = base._excursions(
            used_path,
            direction=direction,
            reference=fill,
            risk_price=displayed_risk,
        )
        payload: dict[str, Any] = {
            "resolution": resolution,
            "fill_at": str(fill_bar["open_at"]),
            "raw_fill": raw_fill,
            "actual_fill": fill,
            "fill_spread": base.spread(fill_bar),
            "slippage_price": base.SLIPPAGE_PRICE,
            "quantity_ounces": quantity,
            "displayed_planned_risk_usd": displayed_risk * quantity,
            "effective_fill_to_stop_risk_usd": effective_risk * quantity,
            "original_quantity_ounces": int(plan["original_quantity_ounces"]),
            "quantity_increased_after_routing": False,
            "partial_eligible": False,
            "partial_quantity_ounces": 0,
            "partial_filled": False,
            "partial_price": None,
            "partial_pnl_usd": 0.0,
            "remaining_quantity_ounces": quantity,
            "exit_at": str(exit_bar["close_at"]),
            "raw_exit": raw_exit,
            "actual_exit": actual_exit,
            "net_pnl_usd": pnl,
            "net_r50": pnl / base.RISK_BUDGET_USD,
            "net_r_on_displayed_planned_risk": pnl / (displayed_risk * quantity),
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "ambiguous_stop_first": False,
            "path_bars": len(used_path),
            "deadline": iso(deadline),
            "risk_controlled_no_upsize": True,
        }
        payload["execution_sha256"] = canonical_hash(payload)
        return payload
    for index, row in enumerate(path):
        stop_touched, target_touched = base._touches(row, direction, stop, target)
        if stop_touched:
            ambiguous = target_touched or (
                eligible_partial
                and not partial_done
                and (
                    float(row["high"]) >= partial_price
                    if direction == "LONG"
                    else float(row["low"]) <= partial_price
                )
            )
            raw_exit = (
                min(stop, float(row["open"]))
                if direction == "LONG"
                else max(stop, float(row["open"]))
            )
            actual_exit = _market_exit_price(direction, raw_exit, row)
            resolution = "PARTIAL_THEN_STOPPED" if partial_done else "STOPPED"
            exit_bar = row
            used_path = path[: index + 1]
            break
        if target_touched:
            if eligible_partial and not partial_done:
                partial_pnl += sign * (partial_price - fill) * partial_quantity
                remaining -= partial_quantity
                partial_done = True
            raw_exit = target
            actual_exit = target
            resolution = "PARTIAL_THEN_TARGET" if partial_done else "TARGET_HIT"
            exit_bar = row
            used_path = path[: index + 1]
            break
        partial_touched = eligible_partial and not partial_done and (
            float(row["high"]) >= partial_price
            if direction == "LONG"
            else float(row["low"]) <= partial_price
        )
        if partial_touched:
            partial_pnl += sign * (partial_price - fill) * partial_quantity
            remaining -= partial_quantity
            partial_done = True
    else:
        resolution = "PARTIAL_THEN_TIME_EXIT" if partial_done else "TIME_EXIT"
    final_pnl = sign * (actual_exit - fill) * remaining
    pnl = partial_pnl + final_pnl
    mfe_r, mae_r = base._excursions(
        used_path,
        direction=direction,
        reference=fill,
        risk_price=displayed_risk,
    )
    payload: dict[str, Any] = {
        "resolution": resolution,
        "fill_at": str(fill_bar["open_at"]),
        "raw_fill": raw_fill,
        "actual_fill": fill,
        "fill_spread": base.spread(fill_bar),
        "slippage_price": base.SLIPPAGE_PRICE,
        "quantity_ounces": quantity,
        "displayed_planned_risk_usd": displayed_risk * quantity,
        "effective_fill_to_stop_risk_usd": effective_risk * quantity,
        "original_quantity_ounces": int(plan["original_quantity_ounces"]),
        "quantity_increased_after_routing": False,
        "partial_eligible": eligible_partial,
        "partial_quantity_ounces": partial_quantity,
        "partial_filled": partial_done,
        "partial_price": partial_price if eligible_partial else None,
        "partial_pnl_usd": partial_pnl,
        "remaining_quantity_ounces": remaining,
        "exit_at": str(exit_bar["close_at"]),
        "raw_exit": raw_exit,
        "actual_exit": actual_exit,
        "net_pnl_usd": pnl,
        "net_r50": pnl / base.RISK_BUDGET_USD,
        "net_r_on_displayed_planned_risk": pnl / (displayed_risk * quantity),
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "ambiguous_stop_first": ambiguous,
        "path_bars": len(used_path),
        "deadline": iso(deadline),
        "risk_controlled_no_upsize": True,
    }
    payload["execution_sha256"] = canonical_hash(payload)
    return payload


def resolve_prepared_plan(
    prepared: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    disposition = str(prepared["disposition"])
    if prepared.get("plan") is None:
        return {"disposition": disposition, "result": None}
    plan = deepcopy(dict(prepared["plan"]))
    if disposition == "PENDING_M5_SWEEP_RECLAIM":
        confirmed = apply_sweep_reclaim_confirmation(plan, rows)
        if confirmed is None:
            return {"disposition": "NO_TRADE_NO_VALID_SWEEP_RECLAIM", "result": None}
        plan = confirmed
    quantity = selected_quantity(plan)
    if quantity < 1:
        return {"disposition": "RISK_INFEASIBLE_WHOLE_OUNCE", "result": None}
    if (
        plan["execution_research_entry_mode"] == "E0_CONTROL_MECHANICAL"
        and plan["execution_research_exit_mode"] == "T0_PRIMARY_LIQUIDITY_FULL"
    ):
        result = resolve_risk_controlled(plan, list(rows))
    else:
        execution = (
            _partial_execution(plan, list(rows), quantity)
            if plan["partial_at_1r"]
            else _execution_with_quantity(plan, list(rows), quantity)
        )
        result = {
            "ruleset": RULESET,
            "policy_id": plan["execution_research_policy_id"],
            "event_identity": plan["event_identity"],
            "case_alias": plan["case_alias"],
            "original_decision_at": plan["original_decision_at"],
            "decision_at": plan["decision_at"],
            "direction": plan["direction"],
            "entry": plan["entry"],
            "stop": plan["stop"],
            "target": plan["target"]["level"],
            "planned_r": plan["planned_r"],
            "plan_sha256": plan["plan_sha256"],
            "execution": execution,
        }
        result["result_sha256"] = canonical_hash(result)
    return {
        "disposition": "EXECUTED_UNRESTRICTED_ALL_SIGNALS",
        "result": result,
        "resolved_plan": plan,
    }
