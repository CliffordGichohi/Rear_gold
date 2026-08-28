"""Bounded one-ounce risk exception for three frozen direct inversions."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import gold_intel.analytics.auction_trade_placement_outcomes_v1 as base
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt

RULESET = "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_V1_R1_BOUNDED_RISK_EXCEPTION"
MAX_EXCEPTION_DISPLAYED_RISK_USD = 53.01
EXCEPTION_QUANTITY_OUNCES = 1
EXCEPTION_IDENTITIES = frozenset(
    {
        "a3777d34fa264e9a8df98b79875e4a701d3cba8ac82a575039a73124f771f0e1",
        "b65abf1555b755bb6a55222879614ed2f59a8cb81b94120e99963c544d198230",
        "c7f54e079e5caecd216d1a70e91a54b6e6aeb567b2506ad90798cb693faab6f1",
    }
)


def _exception_execution(plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    identity = str(plan["event_identity"])
    if identity not in EXCEPTION_IDENTITIES:
        raise RuntimeError(f"Unauthorized risk-exception identity: {identity}")
    if str(plan["event_class"]) != "CONTINUATION_REFRESH" or not plan.get("direct_inversion"):
        raise RuntimeError(f"Risk exception is not a frozen direct inversion: {identity}")
    direction = str(plan["direction"])
    sign = 1.0 if direction == "LONG" else -1.0
    decision = parse_dt(plan["decision_at"])
    effective_at = decision + timedelta(minutes=base.LATENCY_MINUTES)
    deadline = base.session_deadline(plan["decision_at"])
    path = base._complete_path(rows, effective_at, deadline)
    if not path:
        raise RuntimeError(f"No executable outcome path for {identity}")
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
    standard_quantity = math.floor(base.RISK_BUDGET_USD / displayed_risk_price)
    if standard_quantity != 0:
        raise RuntimeError(f"Frozen exception no longer requires one-ounce override: {identity}")
    displayed_planned_risk = displayed_risk_price * EXCEPTION_QUANTITY_OUNCES
    if displayed_planned_risk > MAX_EXCEPTION_DISPLAYED_RISK_USD + 1e-9:
        raise RuntimeError(f"Frozen exception exceeds $53.01 cap: {identity}")
    quantity = EXCEPTION_QUANTITY_OUNCES
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
        "exit_at": str(exit_bar["close_at"]),
        "raw_exit": raw_exit,
        "actual_exit": actual_exit,
        "net_pnl_usd": pnl,
        "net_r50": pnl / base.RISK_BUDGET_USD,
        "net_r_on_displayed_planned_risk": pnl / displayed_planned_risk,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "ambiguous_stop_first": ambiguous,
        "path_bars": len(used_path),
        "deadline": base.iso(deadline),
        "bounded_risk_exception_applied": True,
        "bounded_risk_exception_cap_usd": MAX_EXCEPTION_DISPLAYED_RISK_USD,
    }
    payload["execution_sha256"] = canonical_hash(payload)
    return payload


def resolve_plan_with_bounded_exception(
    plan: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    identity = str(plan["event_identity"])
    if identity not in EXCEPTION_IDENTITIES:
        return base.resolve_plan(plan, rows)
    result: dict[str, Any] = {
        "ruleset": RULESET,
        "event_identity": identity,
        "case_alias": plan["case_alias"],
        "decision_at": plan["decision_at"],
        "direction": plan["direction"],
        "entry": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"]["level"],
        "planned_r": plan["planned_r"],
        "plan_sha256": plan["plan_sha256"],
        "structural": base.structural_first_passage(plan, rows),
        "execution": _exception_execution(plan, rows),
    }
    result["result_sha256"] = canonical_hash(result)
    return result
