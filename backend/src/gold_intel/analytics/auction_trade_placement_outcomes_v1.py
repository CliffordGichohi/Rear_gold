"""Frozen outcome resolution for ten auction trade-placement examples."""

from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, iso, parse_dt

RULESET = "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_OUTCOME_REVEAL"
NEW_YORK = ZoneInfo("America/New_York")
RISK_BUDGET_USD = 50.0
LATENCY_MINUTES = 1
SLIPPAGE_PRICE = 0.05
FALLBACK_SPREAD_PRICE = 0.20


def session_deadline(decision_at: str) -> datetime:
    point = parse_dt(decision_at)
    local = point.astimezone(NEW_YORK)
    return datetime.combine(local.date(), time(12), tzinfo=NEW_YORK).astimezone(UTC)


def spread(row: dict[str, Any]) -> float:
    value = row.get("spread_price")
    if value is None or float(value) < 0:
        return FALLBACK_SPREAD_PRICE
    return float(value)


def _complete_path(rows: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("complete") is True
        and start <= parse_dt(row["open_at"]) < end
        and parse_dt(row["available_at"]) <= end
    ]


def _touches(row: dict[str, Any], direction: str, stop: float, target: float) -> tuple[bool, bool]:
    if direction == "LONG":
        return float(row["low"]) <= stop, float(row["high"]) >= target
    if direction == "SHORT":
        return float(row["high"]) >= stop, float(row["low"]) <= target
    raise ValueError(f"Unsupported direction: {direction}")


def _excursions(
    path: list[dict[str, Any]], *, direction: str, reference: float, risk_price: float
) -> tuple[float, float]:
    if direction == "LONG":
        favourable = max([0.0, *[float(row["high"]) - reference for row in path]])
        adverse = max([0.0, *[reference - float(row["low"]) for row in path]])
    else:
        favourable = max([0.0, *[reference - float(row["low"]) for row in path]])
        adverse = max([0.0, *[float(row["high"]) - reference for row in path]])
    return favourable / risk_price, adverse / risk_price


def structural_first_passage(plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    direction = str(plan["direction"])
    sign = 1.0 if direction == "LONG" else -1.0
    decision = parse_dt(plan["decision_at"])
    deadline = session_deadline(plan["decision_at"])
    path = _complete_path(rows, decision, deadline)
    if not path:
        raise RuntimeError(f"No structural outcome path for {plan['event_identity']}")
    entry = float(plan["entry"])
    stop = float(plan["stop"])
    target = float(plan["target"]["level"])
    risk_price = abs(entry - stop)
    resolution: Literal["STOP_FIRST", "TARGET_FIRST", "TIME_EXIT"] = "TIME_EXIT"
    exit_price = float(path[-1]["close"])
    exit_at = str(path[-1]["close_at"])
    used_path = path
    ambiguous = False
    for index, row in enumerate(path):
        stop_touched, target_touched = _touches(row, direction, stop, target)
        if not stop_touched and not target_touched:
            continue
        ambiguous = stop_touched and target_touched
        if stop_touched:
            resolution = "STOP_FIRST"
            exit_price = stop
        else:
            resolution = "TARGET_FIRST"
            exit_price = target
        exit_at = str(row["close_at"])
        used_path = path[: index + 1]
        break
    gross_r = sign * (exit_price - entry) / risk_price
    mfe_r, mae_r = _excursions(
        used_path, direction=direction, reference=entry, risk_price=risk_price
    )
    payload: dict[str, Any] = {
        "resolution": resolution,
        "exit_at": exit_at,
        "exit_price": exit_price,
        "gross_r": gross_r,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "ambiguous_stop_first": ambiguous,
        "path_bars": len(used_path),
        "deadline": iso(deadline),
    }
    payload["structural_sha256"] = canonical_hash(payload)
    return payload


def execution_outcome(plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    direction = str(plan["direction"])
    sign = 1.0 if direction == "LONG" else -1.0
    decision = parse_dt(plan["decision_at"])
    effective_at = decision + timedelta(minutes=LATENCY_MINUTES)
    deadline = session_deadline(plan["decision_at"])
    path = _complete_path(rows, effective_at, deadline)
    if not path:
        raise RuntimeError(f"No executable outcome path for {plan['event_identity']}")
    fill_bar = path[0]
    fill_half_spread = spread(fill_bar) / 2.0
    raw_fill = float(fill_bar["open"])
    fill = (
        raw_fill + fill_half_spread + SLIPPAGE_PRICE
        if direction == "LONG"
        else raw_fill - fill_half_spread - SLIPPAGE_PRICE
    )
    displayed_entry = float(plan["entry"])
    stop = float(plan["stop"])
    target = float(plan["target"]["level"])
    displayed_risk_price = abs(displayed_entry - stop)
    quantity = math.floor(RISK_BUDGET_USD / displayed_risk_price)
    if quantity < 1:
        raise RuntimeError(f"Whole-ounce sizing produced zero quantity: {plan['event_identity']}")
    effective_risk_usd = sign * (fill - stop) * quantity
    effective_reward_price = sign * (target - fill)
    resolution: Literal[
        "STOPPED", "TARGET_HIT", "TIME_EXIT", "POST_FILL_GEOMETRY_INVALID"
    ] = "TIME_EXIT"
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
            stop_touched, target_touched = _touches(row, direction, stop, target)
            if not stop_touched and not target_touched:
                continue
            ambiguous = stop_touched and target_touched
            exit_bar = row
            if stop_touched:
                resolution = "STOPPED"
                raw_exit = min(stop, float(row["open"])) if direction == "LONG" else max(
                    stop, float(row["open"])
                )
            else:
                resolution = "TARGET_HIT"
                raw_exit = target
            used_path = path[: index + 1]
            break
    if resolution == "TARGET_HIT":
        actual_exit = raw_exit
    else:
        exit_half_spread = spread(exit_bar) / 2.0
        actual_exit = (
            raw_exit - exit_half_spread - SLIPPAGE_PRICE
            if direction == "LONG"
            else raw_exit + exit_half_spread + SLIPPAGE_PRICE
        )
    pnl = sign * (actual_exit - fill) * quantity
    mfe_price_r, mae_price_r = _excursions(
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
        "fill_spread": spread(fill_bar),
        "slippage_price": SLIPPAGE_PRICE,
        "quantity_ounces": quantity,
        "displayed_planned_risk_usd": displayed_risk_price * quantity,
        "effective_fill_to_stop_risk_usd": effective_risk_usd,
        "exit_at": str(exit_bar["close_at"]),
        "raw_exit": raw_exit,
        "actual_exit": actual_exit,
        "net_pnl_usd": pnl,
        "net_r50": pnl / RISK_BUDGET_USD,
        "net_r_on_displayed_planned_risk": pnl / (displayed_risk_price * quantity),
        "mfe_r": mfe_price_r,
        "mae_r": mae_price_r,
        "ambiguous_stop_first": ambiguous,
        "path_bars": len(used_path),
        "deadline": iso(deadline),
    }
    payload["execution_sha256"] = canonical_hash(payload)
    return payload


def resolve_plan(plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
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
        "structural": structural_first_passage(plan, rows),
        "execution": execution_outcome(plan, rows),
    }
    result["result_sha256"] = canonical_hash(result)
    return result

