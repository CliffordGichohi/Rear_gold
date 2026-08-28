"""True continuation-strategy negation with each original quantity preserved."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import timedelta
from typing import Any

import gold_intel.analytics.auction_trade_placement_outcomes_v1 as base
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt

RULESET = "GOLD_CONTINUATION_REFRESH_TRUE_NEGATION_FIXED_QUANTITY_EXPOSED_DIAGNOSTIC_V1"


def attach_original_quantities(
    inverted_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in inverted_rows:
        row = deepcopy(dict(source))
        row.pop("compile_row_sha256", None)
        if row.get("continuation_directly_inverted"):
            plan = deepcopy(dict(row["plan"]))
            direct = plan["direct_inversion"]
            original_entry = float(plan["entry"])
            original_stop = float(direct["original_stop"])
            original_risk_price = abs(original_entry - original_stop)
            quantity = math.floor(base.RISK_BUDGET_USD / original_risk_price)
            if quantity < 1:
                raise RuntimeError(
                    f"Original strategy had zero quantity: {row['event_identity']}"
                )
            original_planned_risk = original_risk_price * quantity
            inverted_stop_risk = abs(float(plan["stop"]) - original_entry) * quantity
            plan["fixed_original_quantity"] = {
                "quantity_ounces": quantity,
                "original_risk_price": original_risk_price,
                "original_displayed_planned_risk_usd": original_planned_risk,
                "inverted_displayed_stop_risk_usd": inverted_stop_risk,
                "quantity_recalculated_after_inversion": False,
            }
            plan.pop("plan_sha256", None)
            plan["plan_sha256"] = canonical_hash(plan)
            row["plan"] = plan
            row["plan_sha256"] = plan["plan_sha256"]
        row["compile_row_sha256"] = canonical_hash(row)
        output.append(row)
    return output


def _fixed_quantity_execution(
    plan: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    fixed = plan.get("fixed_original_quantity")
    if fixed is None or not plan.get("direct_inversion"):
        raise RuntimeError(f"Missing frozen original quantity: {plan['event_identity']}")
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
    quantity = int(fixed["quantity_ounces"])
    if quantity < 1:
        raise RuntimeError(f"Frozen original quantity is invalid: {plan['event_identity']}")
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
        "original_displayed_planned_risk_usd": float(
            fixed["original_displayed_planned_risk_usd"]
        ),
        "quantity_recalculated_after_inversion": False,
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
        "fixed_original_quantity_applied": True,
    }
    payload["execution_sha256"] = canonical_hash(payload)
    return payload


def resolve_plan_fixed_original_quantity(
    plan: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    if not plan.get("direct_inversion"):
        return base.resolve_plan(plan, rows)
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
        "execution": _fixed_quantity_execution(plan, rows),
    }
    result["result_sha256"] = canonical_hash(result)
    return result
