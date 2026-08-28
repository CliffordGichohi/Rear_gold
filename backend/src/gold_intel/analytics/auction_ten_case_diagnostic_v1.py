"""Frozen descriptive diagnostic for ten exposed auction-placement examples."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence
from statistics import mean, median
from typing import Any

from gold_intel.analytics.auction_trade_placement_outcomes_v1 import (
    SLIPPAGE_PRICE,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    parse_dt,
)
from gold_intel.analytics.day_by_day_auction_confirmation_v1 import (
    m5_close_one_r_break_even,
)

RULESET = "GOLD_AUCTION_TEN_CASE_FAILURE_AND_PROFIT_RETENTION_DIAGNOSTIC_V1"
USEFUL_MFE_R = 1.0


def direction_sign(direction: str) -> float:
    if direction == "LONG":
        return 1.0
    if direction == "SHORT":
        return -1.0
    raise ValueError(f"Unsupported direction: {direction}")


def outcome_attribution(result: dict[str, Any]) -> dict[str, Any]:
    execution = result["execution"]
    net_r50 = float(execution["net_r50"])
    mfe_r = float(execution["mfe_r"])
    if net_r50 > 0:
        category = "MONETIZED_SUCCESS"
    elif mfe_r >= USEFUL_MFE_R:
        category = "DIRECTIONALLY_USEFUL_UNMONETIZED"
    else:
        category = "NO_MEANINGFUL_FAVOURABLE_AUCTION"
    payload = {
        "category": category,
        "directionally_useful": category != "NO_MEANINGFUL_FAVOURABLE_AUCTION",
        "net_r50": net_r50,
        "mfe_r": mfe_r,
        "mae_r": float(execution["mae_r"]),
    }
    payload["attribution_sha256"] = canonical_hash(payload)
    return payload


def _swing_pair(context: dict[str, Any], timeframe: str) -> str:
    relations = context.get(timeframe, {}).get("swing_relations", {})
    return f"{relations.get('high', 'UNKNOWN')}|{relations.get('low', 'UNKNOWN')}"


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def preentry_features(plan: dict[str, Any]) -> dict[str, Any]:
    sign = direction_sign(str(plan["direction"]))
    macro = plan.get("macro_context", {})
    context = plan.get("higher_timeframe_context", {})
    risk_price = abs(float(plan["entry"]) - float(plan["stop"]))
    break_atr = _float_or_none(plan.get("broken_control", {}).get("atr"))
    local_distance = _float_or_none(plan.get("local_m15_liquidity", {}).get("distance_price"))
    payload: dict[str, Any] = {
        "event_identity": plan["event_identity"],
        "case_alias": plan["case_alias"],
        "decision_at": plan["decision_at"],
        "direction": plan["direction"],
        "session": plan.get("session"),
        "context_family": plan.get("context_family"),
        "event_class": plan.get("event_class"),
        "planned_r": float(plan["planned_r"]),
        "macro_alignment_score": sign * float(macro.get("score", 0.0)),
        "macro_confidence": _float_or_none(macro.get("confidence")),
        "macro_state": macro.get("state", "UNKNOWN"),
        "macro_driver": macro.get("dominant_driver", "UNKNOWN"),
        "h1_swing_pair": _swing_pair(context, "H1"),
        "h4_swing_pair": _swing_pair(context, "H4"),
        "h1_range_location": _float_or_none(context.get("H1", {}).get("range_location")),
        "h4_range_location": _float_or_none(context.get("H4", {}).get("range_location")),
        "distance_from_m5_break_atr": _float_or_none(plan.get("distance_from_m5_break_atr")),
        "risk_in_break_atr": None if not break_atr else risk_price / break_atr,
        "target_timeframe": plan.get("target", {}).get("timeframe", "UNKNOWN"),
        "protected_pivot_timeframe": plan.get("protected_pivot", {}).get("timeframe", "UNKNOWN"),
        "local_m15_liquidity_room_r": None if not risk_price or local_distance is None else local_distance / risk_price,
    }
    payload["preentry_sha256"] = canonical_hash(payload)
    return payload


def _reference_overlay(
    *,
    plan: dict[str, Any],
    result: dict[str, Any],
    m1_rows: Sequence[dict[str, Any]],
    m5_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    execution = result["execution"]
    direction = str(plan["direction"])
    sign = direction_sign(direction)
    opened = parse_dt(execution["fill_at"])
    final = parse_dt(execution["exit_at"])
    fill = float(execution["actual_fill"])
    stop = float(plan["stop"])
    target = float(plan["target"]["level"])
    activation_level = fill + sign * abs(fill - stop)
    activations = sorted(
        (
            row
            for row in m5_rows
            if row.get("complete") is True
            and opened < parse_dt(row["available_at"]) <= final
            and sign * (float(row["close"]) - activation_level) >= 0
        ),
        key=lambda row: parse_dt(row["available_at"]),
    )
    if not activations:
        return {"activated": False, "activation_at": None, "exit_at": None, "disposition": "UNCHANGED", "changed": False}
    activation_at = parse_dt(activations[0]["available_at"])
    path = sorted(
        (
            row
            for row in m1_rows
            if row.get("complete") is True
            and opened <= parse_dt(row["open_at"]) <= final
        ),
        key=lambda row: parse_dt(row["open_at"]),
    )
    for row in path:
        if parse_dt(row["open_at"]) >= activation_at:
            break
        target_touch = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if target_touch:
            return {"activated": True, "activation_at": activations[0]["available_at"], "exit_at": None, "disposition": "TARGET_PRECEDED_OVERLAY", "changed": False}
    cost_per_ounce = float(execution["fill_spread"]) + 2.0 * SLIPPAGE_PRICE
    break_even = fill + sign * cost_per_ounce
    for row in path:
        if parse_dt(row["open_at"]) < activation_at:
            continue
        stop_touch = float(row["low"]) <= break_even if direction == "LONG" else float(row["high"]) >= break_even
        target_touch = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if stop_touch:
            return {"activated": True, "activation_at": activations[0]["available_at"], "exit_at": row["open_at"], "disposition": "M5_1R_NET_BREAK_EVEN", "changed": True}
        if target_touch:
            return {"activated": True, "activation_at": activations[0]["available_at"], "exit_at": None, "disposition": "TARGET_PRECEDED_OVERLAY", "changed": False}
    return {"activated": True, "activation_at": activations[0]["available_at"], "exit_at": None, "disposition": "UNCHANGED", "changed": False}


def management_overlay(
    *,
    plan: dict[str, Any],
    result: dict[str, Any],
    m1_rows: Sequence[dict[str, Any]],
    m5_rows: Sequence[dict[str, Any]],
    implementation: str = "primary",
) -> dict[str, Any]:
    execution = result["execution"]
    if implementation == "primary":
        overlay = m5_close_one_r_break_even(
            m1_rows=m1_rows,
            m5_rows=m5_rows,
            fill_at=execution["fill_at"],
            baseline_final_at=execution["exit_at"],
            fill=float(execution["actual_fill"]),
            stop=float(plan["stop"]),
            target=float(plan["target"]["level"]),
            cost_per_ounce=float(execution["fill_spread"]) + 2.0 * SLIPPAGE_PRICE,
            direction=str(plan["direction"]),
        )
        overlay = {key: value for key, value in overlay.items() if key != "overlay_hash"}
    elif implementation == "reference":
        overlay = _reference_overlay(plan=plan, result=result, m1_rows=m1_rows, m5_rows=m5_rows)
    else:
        raise ValueError(f"Unsupported implementation: {implementation}")
    baseline_r = float(execution["net_r50"])
    effective_r = 0.0 if overlay["changed"] else baseline_r
    payload = {
        **overlay,
        "baseline_r50": baseline_r,
        "effective_r50": effective_r,
        "incremental_r50": effective_r - baseline_r,
        "saved_loss": bool(overlay["changed"] and baseline_r < 0),
        "clipped_winner": bool(overlay["changed"] and baseline_r > 0),
    }
    payload["overlay_sha256"] = canonical_hash(payload)
    return payload


NUMERIC_FIELDS = (
    "planned_r",
    "macro_alignment_score",
    "macro_confidence",
    "h1_range_location",
    "h4_range_location",
    "distance_from_m5_break_atr",
    "risk_in_break_atr",
    "local_m15_liquidity_room_r",
)

CATEGORICAL_FIELDS = (
    "direction",
    "session",
    "context_family",
    "event_class",
    "macro_state",
    "macro_driver",
    "h1_swing_pair",
    "h4_swing_pair",
    "target_timeframe",
    "protected_pivot_timeframe",
)


def _numeric_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return {
        "n": len(values),
        "mean": None if not values else mean(values),
        "median": None if not values else median(values),
        "minimum": None if not values else min(values),
        "maximum": None if not values else max(values),
    }


def contrast_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {
        "DIRECTIONALLY_USEFUL": [row for row in rows if row["directionally_useful"]],
        "NO_MEANINGFUL_FAVOURABLE_AUCTION": [row for row in rows if not row["directionally_useful"]],
    }
    return {
        group: {
            "n": len(items),
            "numeric": {field: _numeric_summary(items, field) for field in NUMERIC_FIELDS},
            "categorical": {field: dict(sorted(Counter(str(row.get(field)) for row in items).items())) for field in CATEGORICAL_FIELDS},
        }
        for group, items in groups.items()
    }


def maximum_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def economic_summary(rows: list[dict[str, Any]], value: Callable[[dict[str, Any]], float]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (parse_dt(row["decision_at"]), row["event_identity"]))
    values = [float(value(row)) for row in ordered]
    positive = sum(item for item in values if item > 0)
    negative = -sum(item for item in values if item < 0)
    return {
        "observations": len(values),
        "wins": sum(item > 0 for item in values),
        "losses": sum(item < 0 for item in values),
        "scratches": sum(abs(item) <= 1e-12 for item in values),
        "net_r50": sum(values),
        "expectancy_r50": sum(values) / len(values),
        "profit_factor": positive / negative if negative > 0 else math.inf,
        "maximum_drawdown_r50": maximum_drawdown(values),
    }
