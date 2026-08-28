"""Frozen constant execution for Autonomous Coherent-Auction Detector V1."""

from __future__ import annotations

import math
from typing import Any

from gold_intel.analytics.coherent_auction_correction_v1 import parse_dt

SPREAD_FALLBACK = 0.20
SLIPPAGE_PRICE = 0.05
MAXIMUM_RISK_USD = 50.0


def observed_spread(row: dict[str, Any]) -> float:
    value = row.get("spread_price")
    if value is None:
        return SPREAD_FALLBACK
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else SPREAD_FALLBACK


def _cost(row: dict[str, Any], multiplier: float) -> float:
    return observed_spread(row) * multiplier / 2.0 + SLIPPAGE_PRICE * multiplier


def simulate_autonomous_auction_trade_v1(
    *,
    stream: dict[str, Any],
    signal: dict[str, Any],
    cost_multiplier: float = 1.0,
    quantity_override: int | None = None,
) -> dict[str, Any]:
    if cost_multiplier <= 0:
        raise ValueError("cost_multiplier must be positive")
    if signal.get("disposition") != "SIGNAL":
        return {
            "disposition": "NO_SIGNAL",
            "quantity_ounces": 0,
            "net_usd": 0.0,
            "net_r50": 0.0,
            "exit_reason": None,
        }
    direction = str(signal["direction"])
    sign = 1.0 if direction == "LONG" else -1.0
    signal_at = parse_dt(signal["signal_at"])
    m1 = [
        row
        for row in stream["timeframes"]["1m"]
        if row.get("complete") is True
        and parse_dt(row["available_at"]) <= parse_dt(stream["end_exclusive"])
    ]
    fill_index = next(
        (
            index
            for index, row in enumerate(m1)
            if parse_dt(row["open_at"]) > signal_at
        ),
        None,
    )
    if fill_index is None:
        return {
            "disposition": "REJECT_NO_EXECUTION_BAR",
            "quantity_ounces": 0,
            "net_usd": 0.0,
            "net_r50": 0.0,
            "exit_reason": None,
        }
    fill_bar = m1[fill_index]
    plan = signal["plan"]
    stop = float(plan["components"]["structural_invalidation"]["price"])
    target = float(plan["components"]["liquidity_destination"]["level"])
    fill = float(fill_bar["open"]) + sign * _cost(fill_bar, cost_multiplier)
    stop_exit = stop - sign * _cost(fill_bar, cost_multiplier)
    loss_per_ounce = sign * (fill - stop_exit)
    target_distance = sign * (target - fill)
    if loss_per_ounce <= 0 or target_distance <= 0:
        return {
            "disposition": "REJECT_INVALID_EXECUTION_GEOMETRY",
            "quantity_ounces": 0,
            "net_usd": 0.0,
            "net_r50": 0.0,
            "exit_reason": None,
            "fill": fill,
            "stop": stop,
            "target": target,
        }
    quantity = (
        int(quantity_override)
        if quantity_override is not None
        else int(math.floor(MAXIMUM_RISK_USD / loss_per_ounce))
    )
    if quantity < 1:
        return {
            "disposition": "REJECT_RISK_GEOMETRY",
            "quantity_ounces": 0,
            "net_usd": 0.0,
            "net_r50": 0.0,
            "exit_reason": None,
            "fill": fill,
            "stop": stop,
            "target": target,
            "effective_loss_per_ounce": loss_per_ounce,
        }

    exit_price: float | None = None
    exit_at: str | None = None
    exit_reason: str | None = None
    for row in m1[fill_index:]:
        stop_hit = float(row["low"]) <= stop if direction == "LONG" else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if stop_hit:
            exit_price = stop - sign * _cost(row, cost_multiplier)
            exit_at = row["close_at"]
            exit_reason = "STOP_FIRST" if target_hit else "STRUCTURAL_STOP"
            break
        if target_hit:
            exit_price = target
            exit_at = row["close_at"]
            exit_reason = "LIQUIDITY_DESTINATION"
            break
    if exit_price is None:
        final = m1[-1]
        exit_price = float(final["close"]) - sign * _cost(final, cost_multiplier)
        exit_at = final["close_at"]
        exit_reason = "SESSION_TIME_EXIT"

    net_per_ounce = sign * (exit_price - fill)
    net_usd = quantity * net_per_ounce
    return {
        "disposition": "EXECUTED",
        "direction": direction,
        "fill_at": fill_bar["open_at"],
        "fill": fill,
        "stop": stop,
        "target": target,
        "exit_at": exit_at,
        "exit": exit_price,
        "exit_reason": exit_reason,
        "quantity_ounces": quantity,
        "effective_loss_per_ounce": loss_per_ounce,
        "planned_risk_usd": quantity * loss_per_ounce,
        "net_usd": net_usd,
        "net_r50": net_usd / MAXIMUM_RISK_USD,
        "cost_multiplier": cost_multiplier,
    }

