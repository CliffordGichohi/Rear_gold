"""Frozen liquidity-hierarchy direction router and no-upsize execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import timedelta
from typing import Any

import gold_intel.analytics.auction_trade_placement_outcomes_v1 as base
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt
from gold_intel.analytics.continuation_refresh_direct_inversion_v1 import invert_plan
from gold_intel.analytics.continuation_refresh_true_negation_fixed_quantity_v1 import (
    resolve_plan_fixed_original_quantity,
)

RULESET = "GOLD_AUCTION_LIQUIDITY_HIERARCHY_HYBRID_ROUTER_EXPOSED_BENCHMARK_V1"
TARGET_FRESH_MINUTES = 240.0


def _original_quantity(plan: Mapping[str, Any]) -> int:
    distance = abs(float(plan["entry"]) - float(plan["stop"]))
    quantity = math.floor(base.RISK_BUDGET_USD / distance)
    if quantity < 1:
        raise RuntimeError(f"Original quantity is infeasible: {plan['event_identity']}")
    return quantity


def route_reason(plan: Mapping[str, Any]) -> str:
    context = str(plan["context_family"])
    if context.startswith("RANGE_"):
        return "RANGE_CONTEXT_PRESERVE"
    target = dict(plan["target"])
    if str(target.get("timeframe")) == "H4":
        return "H4_DESTINATION_PRESERVE"
    local = plan.get("local_m15_liquidity")
    if (
        isinstance(local, Mapping)
        and local.get("level") is not None
        and target.get("level") is not None
        and float(local["level"]) == float(target["level"])
    ):
        return "LOCAL_M15_LEVEL_CONFIRMS_DESTINATION_PRESERVE"
    age_minutes = (
        parse_dt(str(plan["decision_at"])) - parse_dt(str(target["known_at"]))
    ).total_seconds() / 60.0
    if age_minutes < TARGET_FRESH_MINUTES:
        return "DESTINATION_AGE_LT_240M_PRESERVE"
    return "H1_UNCONFIRMED_AGE_GTE_240M_NEGATE"


def route_population(
    compiled_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in compiled_rows:
        row = deepcopy(dict(source))
        row.pop("compile_row_sha256", None)
        if not row["mechanically_executable"]:
            row.update(
                {
                    "hybrid_route_reason": "HARD_INEXECUTABLE_UNCHANGED",
                    "hybrid_route_action": "NO_EXECUTION",
                    "original_direction": str(row["direction"]),
                    "selected_direction": str(row["direction"]),
                    "original_quantity_ounces": None,
                    "risk_controlled_quantity_ounces": None,
                    "risk_controlled_disposition": "NOT_APPLICABLE",
                }
            )
            row["compile_row_sha256"] = canonical_hash(row)
            output.append(row)
            continue
        if row["plan"] is None:
            raise RuntimeError(f"Executable row lacks plan: {row['event_identity']}")
        original_plan = deepcopy(dict(row["plan"]))
        original_direction = str(original_plan["direction"])
        original_quantity = _original_quantity(original_plan)
        if str(row["event_class"]) != "CONTINUATION_REFRESH":
            row.update(
                {
                    "hybrid_route_reason": "NON_CONTINUATION_UNCHANGED",
                    "hybrid_route_action": "PRESERVE",
                    "original_direction": original_direction,
                    "selected_direction": original_direction,
                    "original_quantity_ounces": original_quantity,
                    "risk_controlled_quantity_ounces": original_quantity,
                    "risk_controlled_disposition": "EXECUTABLE_NO_UPSIZE",
                }
            )
            row["compile_row_sha256"] = canonical_hash(row)
            output.append(row)
            continue
        reason = route_reason(original_plan)
        action = "NEGATE" if reason.endswith("_NEGATE") else "PRESERVE"
        selected_plan = (
            invert_plan(original_plan) if action == "NEGATE" else deepcopy(original_plan)
        )
        selected_stop_distance = abs(
            float(selected_plan["entry"]) - float(selected_plan["stop"])
        )
        risk_limited_quantity = math.floor(
            base.RISK_BUDGET_USD / selected_stop_distance
        )
        risk_controlled_quantity = min(original_quantity, risk_limited_quantity)
        risk_disposition = (
            "EXECUTABLE_NO_UPSIZE"
            if risk_controlled_quantity >= 1
            else "RISK_INFEASIBLE_WHOLE_OUNCE"
        )
        original_stop_distance = abs(
            float(original_plan["entry"]) - float(original_plan["stop"])
        )
        route_metadata = {
            "reason": reason,
            "action": action,
            "original_direction": original_direction,
            "selected_direction": str(selected_plan["direction"]),
            "original_quantity_ounces": original_quantity,
            "risk_controlled_quantity_ounces": risk_controlled_quantity,
            "risk_controlled_disposition": risk_disposition,
            "original_stop_distance": original_stop_distance,
            "selected_stop_distance": selected_stop_distance,
            "fixed_original_stop_exposure_usd": selected_stop_distance
            * original_quantity,
            "risk_controlled_stop_exposure_usd": selected_stop_distance
            * risk_controlled_quantity,
            "quantity_increased_after_routing": False,
        }
        selected_plan["hybrid_route"] = route_metadata
        if action == "NEGATE":
            selected_plan["fixed_original_quantity"] = {
                "quantity_ounces": original_quantity,
                "original_risk_price": original_stop_distance,
                "original_displayed_planned_risk_usd": original_stop_distance
                * original_quantity,
                "inverted_displayed_stop_risk_usd": selected_stop_distance
                * original_quantity,
                "quantity_recalculated_after_inversion": False,
            }
        selected_plan.pop("plan_sha256", None)
        selected_plan["plan_sha256"] = canonical_hash(selected_plan)
        row.update(
            {
                "plan": selected_plan,
                "plan_sha256": selected_plan["plan_sha256"],
                "direction": str(selected_plan["direction"]),
                "hybrid_route_reason": reason,
                "hybrid_route_action": action,
                "original_direction": original_direction,
                "selected_direction": str(selected_plan["direction"]),
                "original_quantity_ounces": original_quantity,
                "risk_controlled_quantity_ounces": risk_controlled_quantity,
                "risk_controlled_disposition": risk_disposition,
            }
        )
        row["compile_row_sha256"] = canonical_hash(row)
        output.append(row)
    return output


def resolve_fixed_original_quantity(
    plan: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    route = plan.get("hybrid_route")
    if route and route["action"] == "NEGATE":
        return resolve_plan_fixed_original_quantity(plan, rows)
    return base.resolve_plan(plan, rows)


def _execution_with_quantity(
    plan: dict[str, Any], rows: list[dict[str, Any]], quantity: int
) -> dict[str, Any]:
    if quantity < 1:
        raise RuntimeError(f"Risk-controlled quantity is infeasible: {plan['event_identity']}")
    direction = str(plan["direction"])
    sign = 1.0 if direction == "LONG" else -1.0
    decision = parse_dt(plan["decision_at"])
    effective_at = decision + timedelta(minutes=base.LATENCY_MINUTES)
    deadline = base.session_deadline(plan["decision_at"])
    path = base._complete_path(rows, effective_at, deadline)
    if not path:
        raise RuntimeError(f"No executable outcome path for {plan['event_identity']}")
    fill_bar = path[0]
    fill_half_spread = base.spread(fill_bar) / 2.0
    raw_fill = float(fill_bar["open"])
    fill = (
        raw_fill + fill_half_spread + base.SLIPPAGE_PRICE
        if direction == "LONG"
        else raw_fill - fill_half_spread - base.SLIPPAGE_PRICE
    )
    displayed_entry = float(plan["entry"])
    stop = float(plan["stop"])
    target = float(plan["target"]["level"])
    displayed_risk_price = abs(displayed_entry - stop)
    displayed_planned_risk = displayed_risk_price * quantity
    effective_risk_usd = sign * (fill - stop) * quantity
    effective_reward_price = sign * (target - fill)
    resolution = "TIME_EXIT"
    raw_exit = float(path[-1]["close"])
    exit_bar = path[-1]
    used_path = path
    ambiguous = False
    if effective_risk_usd <= 0 or effective_reward_price <= 0:
        resolution = "POST_FILL_GEOMETRY_INVALID"
        exit_bar = path[1] if len(path) > 1 else path[0]
        raw_exit = float(exit_bar["open"] if len(path) > 1 else exit_bar["close"])
        used_path = path[:2]
    else:
        for index, row in enumerate(path):
            stop_touched, target_touched = base._touches(row, direction, stop, target)
            if not stop_touched and not target_touched:
                continue
            ambiguous = stop_touched and target_touched
            exit_bar = row
            if stop_touched:
                resolution = "STOPPED"
                raw_exit = (
                    min(stop, float(row["open"]))
                    if direction == "LONG"
                    else max(stop, float(row["open"]))
                )
            else:
                resolution = "TARGET_HIT"
                raw_exit = target
            used_path = path[: index + 1]
            break
    if resolution == "TARGET_HIT":
        actual_exit = raw_exit
    else:
        exit_half_spread = base.spread(exit_bar) / 2.0
        actual_exit = (
            raw_exit - exit_half_spread - base.SLIPPAGE_PRICE
            if direction == "LONG"
            else raw_exit + exit_half_spread + base.SLIPPAGE_PRICE
        )
    pnl = sign * (actual_exit - fill) * quantity
    mfe_r, mae_r = base._excursions(
        used_path,
        direction=direction,
        reference=fill,
        risk_price=displayed_risk_price,
    )
    route = dict(plan.get("hybrid_route") or {})
    payload: dict[str, Any] = {
        "resolution": resolution,
        "fill_at": str(fill_bar["open_at"]),
        "raw_fill": raw_fill,
        "actual_fill": fill,
        "fill_spread": base.spread(fill_bar),
        "slippage_price": base.SLIPPAGE_PRICE,
        "quantity_ounces": quantity,
        "displayed_planned_risk_usd": displayed_planned_risk,
        "effective_fill_to_stop_risk_usd": effective_risk_usd,
        "original_quantity_ounces": route.get("original_quantity_ounces", quantity),
        "quantity_increased_after_routing": False,
        "exit_at": str(exit_bar["close_at"]),
        "raw_exit": raw_exit,
        "actual_exit": actual_exit,
        "net_pnl_usd": pnl,
        "net_r50": pnl / base.RISK_BUDGET_USD,
        "net_r_on_displayed_planned_risk": (
            pnl / displayed_planned_risk if displayed_planned_risk > 0 else None
        ),
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "ambiguous_stop_first": ambiguous,
        "path_bars": len(used_path),
        "deadline": base.iso(deadline),
        "risk_controlled_no_upsize": True,
    }
    payload["execution_sha256"] = canonical_hash(payload)
    return payload


def resolve_risk_controlled(
    plan: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    route = plan.get("hybrid_route")
    if route is None:
        return base.resolve_plan(plan, rows)
    quantity = int(route["risk_controlled_quantity_ounces"])
    result: dict[str, Any] = {
        "ruleset": RULESET,
        "event_identity": plan["event_identity"],
        "case_alias": plan["case_alias"],
        "decision_at": plan["decision_at"],
        "direction": plan["direction"],
        "entry": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"]["level"],
        "planned_r": plan["planned_r"],
        "plan_sha256": plan["plan_sha256"],
        "structural": base.structural_first_passage(plan, rows),
        "execution": _execution_with_quantity(plan, rows, quantity),
    }
    result["result_sha256"] = canonical_hash(result)
    return result
