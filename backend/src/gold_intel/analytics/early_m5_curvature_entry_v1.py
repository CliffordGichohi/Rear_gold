"""Causal early-M5 curvature response scanner and fixed lifecycle.

The scanner never receives the later M15 turning-point census.  Census pivots
are joined only after every causal decision and lifecycle has been produced.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any, Literal

from gold_intel.analytics.auction_liquidity_range_semantics_v1 import (
    active_range_context,
    build_timeframe_inventory,
    structure_state,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (
    TICK_FLOOR,
    canonical_hash,
    complete_rows,
    confirmed_swings,
    iso,
    latest_atr,
    parse_dt,
    swing_relations,
)

Direction = Literal["LONG", "SHORT"]

RULESET = "GOLD_JANUARY_EARLY_M5_CURVATURE_ENTRY_EXPOSED_REGRESSION_V1"
RISK_BUDGET_USD = 50.0
STARTING_EQUITY_USD = 10_000.0
SLIPPAGE_USD_PER_OUNCE_PER_SIDE = 0.05
SPREAD_FALLBACK = 0.20
M15_ATR_STOP_BUFFER = 0.05


def _bar_midpoint(row: Mapping[str, Any]) -> float:
    return (float(row["high"]) + float(row["low"])) / 2.0


def _aligned(row: Mapping[str, Any], direction: Direction) -> bool:
    if direction == "LONG":
        return float(row["close"]) > float(row["open"])
    return float(row["close"]) < float(row["open"])


def _directional_half_close(row: Mapping[str, Any], direction: Direction) -> bool:
    if not _aligned(row, direction):
        return False
    midpoint = _bar_midpoint(row)
    if direction == "LONG":
        return float(row["close"]) >= midpoint
    return float(row["close"]) <= midpoint


def contiguous_m5(rows: Sequence[Mapping[str, Any]]) -> bool:
    """Require exact consecutive five-minute opens for the four-bar pattern."""

    if len(rows) != 4:
        return False
    opens = [parse_dt(str(row["open_at"])) for row in rows]
    return all(right - left == timedelta(minutes=5) for left, right in zip(opens, opens[1:]))


def trigger_direction(
    preceding_three: Sequence[Mapping[str, Any]],
    current: Mapping[str, Any],
) -> Direction | None:
    """Return the mirrored first-response direction, without later bars."""

    if len(preceding_three) != 3 or not contiguous_m5([*preceding_three, current]):
        return None
    first, middle, prior = preceding_three

    long_adverse = (
        float(prior["close"]) < float(first["close"])
        and min(float(middle["low"]), float(prior["low"])) < float(first["low"])
        and any(float(row["close"]) < float(row["open"]) for row in (middle, prior))
        and (
            float(prior["close"]) < float(prior["open"])
            or float(prior["low"]) <= float(middle["low"])
        )
    )
    long_turn = (
        _directional_half_close(current, "LONG")
        and float(current["close"]) > _bar_midpoint(prior)
    )

    short_adverse = (
        float(prior["close"]) > float(first["close"])
        and max(float(middle["high"]), float(prior["high"])) > float(first["high"])
        and any(float(row["close"]) > float(row["open"]) for row in (middle, prior))
        and (
            float(prior["close"]) > float(prior["open"])
            or float(prior["high"]) >= float(middle["high"])
        )
    )
    short_turn = (
        _directional_half_close(current, "SHORT")
        and float(current["close"]) < _bar_midpoint(prior)
    )

    if long_adverse and long_turn and not (short_adverse and short_turn):
        return "LONG"
    if short_adverse and short_turn and not (long_adverse and long_turn):
        return "SHORT"
    return None


def _strictly_consumed(
    minute_rows: Sequence[dict[str, Any]],
    timeframe_rows: Sequence[dict[str, Any]],
    swing: Mapping[str, Any],
    cutoff: str,
) -> bool:
    kind = str(swing["kind"])
    level = float(swing["level"])
    pivot_bars = [
        row
        for row in complete_rows(timeframe_rows, cutoff)
        if iso(row["open_at"]) == iso(swing["pivot_at"])
    ]
    if len(pivot_bars) != 1:
        raise RuntimeError(f"Pivot candle is not uniquely available: {swing['identity']}")
    pivot_complete = parse_dt(pivot_bars[0]["available_at"])
    # The parent-timeframe OHLC extrema preserve strict traded-price breaches
    # and provide complete history when the daily M1 replay lookback begins
    # after an older H1/M15 pivot.  M1 is therefore not allowed to truncate the
    # pivot lifecycle.
    del minute_rows
    for row in complete_rows(timeframe_rows, cutoff):
        if parse_dt(row["available_at"]) <= pivot_complete:
            continue
        if kind == "HIGH" and float(row["high"]) > level:
            return True
        if kind == "LOW" and float(row["low"]) < level:
            return True
    return False


def _known_swings(
    rows: Sequence[dict[str, Any]], cutoff: str, timeframe: str
) -> list[dict[str, Any]]:
    _, swings = confirmed_swings(rows, cutoff, timeframe)
    return [
        dict(row)
        for row in swings
        if parse_dt(row["detected_at"]) <= parse_dt(cutoff)
    ]


def _structure_snapshot(
    rows: Sequence[dict[str, Any]], cutoff: str, timeframe: str
) -> dict[str, Any]:
    swings = _known_swings(rows, cutoff, timeframe)
    relations = swing_relations(swings)
    if relations == {"high": "HH", "low": "HL"}:
        state = "UPTREND"
    elif relations == {"high": "LH", "low": "LL"}:
        state = "DOWNTREND"
    else:
        state = "MIXED_OR_TRANSITIONING"
    return {
        "timeframe": timeframe,
        "state": state,
        "relations": relations,
        "known_swing_count": len(swings),
        "last_high_identity": next(
            (row["identity"] for row in reversed(swings) if row["kind"] == "HIGH"), None
        ),
        "last_low_identity": next(
            (row["identity"] for row in reversed(swings) if row["kind"] == "LOW"), None
        ),
    }


def _trend_context(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
) -> dict[str, Any] | None:
    m15 = stream["timeframes"]["15m"]
    snapshot = _structure_snapshot(m15, cutoff, "M15")
    wanted_state = "UPTREND" if direction == "LONG" else "DOWNTREND"
    if snapshot["state"] != wanted_state:
        return None
    swings = _known_swings(m15, cutoff, "M15")
    wanted_kind = "LOW" if direction == "LONG" else "HIGH"
    controls = [row for row in swings if row["kind"] == wanted_kind]
    if not controls:
        return None
    control = controls[-1]
    if _strictly_consumed(
        stream["timeframes"]["1m"], m15, control, cutoff
    ):
        return None
    return {
        "family": "TREND_PULLBACK",
        "direction": direction,
        "m15_structure": snapshot,
        "control": control,
        "range": None,
        "context_identity": canonical_hash(
            [
                "EARLY_M5_TREND_CONTEXT",
                direction,
                snapshot["relations"],
                control["identity"],
            ]
        ),
    }


def _range_context(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    price: float,
) -> dict[str, Any] | None:
    m15 = stream["timeframes"]["15m"]
    inventory = build_timeframe_inventory(m15, cutoff, "M15")
    snapshot = structure_state(inventory)
    if snapshot["state"] != "MIXED_OR_TRANSITIONING":
        return None
    context = active_range_context(
        m15,
        cutoff=cutoff,
        timeframe="M15",
        direction=direction,
        price=price,
        inventory=inventory,
    )
    if context.get("state") != "ACTIVE_RANGE":
        return None
    midpoint = float(context["midpoint"])
    if direction == "LONG" and not price < midpoint:
        return None
    if direction == "SHORT" and not price > midpoint:
        return None
    control = dict(
        context["lower_boundary"] if direction == "LONG" else context["upper_boundary"]
    )
    if str(control["state"]) == "CONSUMED":
        return None
    return {
        "family": "RANGE_ROTATION",
        "direction": direction,
        "m15_structure": {
            "timeframe": "M15",
            "state": snapshot["state"],
            "relations": snapshot["relations"],
            "known_swing_count": inventory["known_pivots"],
        },
        "control": control,
        "range": context,
        "context_identity": canonical_hash(
            ["EARLY_M5_RANGE_CONTEXT", direction, context["range_identity"]]
        ),
    }


def governing_context(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    price: float,
) -> dict[str, Any] | None:
    trend = _trend_context(stream, cutoff=cutoff, direction=direction)
    if trend is not None:
        return trend
    return _range_context(
        stream, cutoff=cutoff, direction=direction, price=price
    )


def _higher_timeframe_context(
    stream: Mapping[str, Any], cutoff: str, direction: Direction
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    wanted = "UPTREND" if direction == "LONG" else "DOWNTREND"
    for timeframe, key in (("H1", "1h"), ("H4", "4h")):
        item = _structure_snapshot(stream["timeframes"][key], cutoff, timeframe)
        item["alignment"] = "ALIGNED" if item["state"] == wanted else (
            "COUNTER" if item["state"] in {"UPTREND", "DOWNTREND"} else "MIXED"
        )
        output[timeframe] = item
    alignments = [output[key]["alignment"] for key in ("H1", "H4")]
    output["combined_alignment"] = (
        "BOTH_ALIGNED" if alignments == ["ALIGNED", "ALIGNED"]
        else "BOTH_COUNTER" if alignments == ["COUNTER", "COUNTER"]
        else "MIXED_ALIGNMENT"
    )
    return output


def _trend_destination(
    stream: Mapping[str, Any],
    *,
    cutoff: str,
    direction: Direction,
    price: float,
) -> dict[str, Any] | None:
    wanted = "HIGH" if direction == "LONG" else "LOW"
    candidates: list[dict[str, Any]] = []
    for timeframe, key in (("M15", "15m"), ("H1", "1h")):
        rows = stream["timeframes"][key]
        for swing in _known_swings(rows, cutoff, timeframe):
            level = float(swing["level"])
            beyond = level > price if direction == "LONG" else level < price
            if swing["kind"] != wanted or not beyond:
                continue
            if _strictly_consumed(
                stream["timeframes"]["1m"], rows, swing, cutoff
            ):
                continue
            candidates.append({**swing, "timeframe": timeframe})
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda row: (
            abs(float(row["level"]) - price),
            parse_dt(row["detected_at"]),
            row["identity"],
        ),
    )
    return {
        "identity": str(selected["identity"]),
        "timeframe": str(selected["timeframe"]),
        "kind": str(selected["kind"]),
        "level": float(selected["level"]),
        "pivot_at": iso(selected["pivot_at"]),
        "known_at": iso(selected["detected_at"]),
        "basis": "NEAREST_KNOWN_STRICTLY_UNCONSUMED_OPPOSING_M15_OR_H1_SWING",
    }


def _range_destination(
    context: Mapping[str, Any], direction: Direction, price: float
) -> dict[str, Any] | None:
    range_item = context.get("range")
    if not isinstance(range_item, Mapping):
        return None
    selected = dict(
        range_item["upper_boundary"] if direction == "LONG" else range_item["lower_boundary"]
    )
    level = float(selected["level"])
    if not (level > price if direction == "LONG" else level < price):
        return None
    return {
        "identity": str(selected["identity"]),
        "timeframe": "M15_RANGE",
        "kind": str(selected["kind"]),
        "level": level,
        "pivot_at": iso(selected["pivot_at"]),
        "known_at": iso(selected["known_at"]),
        "basis": "EXACT_PREEXISTING_OPPOSITE_M15_RANGE_BOUNDARY",
    }


def build_decision(
    stream: Mapping[str, Any],
    preceding_three: Sequence[Mapping[str, Any]],
    current: Mapping[str, Any],
) -> dict[str, Any] | None:
    direction = trigger_direction(preceding_three, current)
    if direction is None:
        return None
    cutoff = iso(current["available_at"])
    price = float(current["close"])
    context = governing_context(
        stream, cutoff=cutoff, direction=direction, price=price
    )
    if context is None:
        return None
    atr = latest_atr(stream["timeframes"]["15m"], cutoff)
    if atr is None or not math.isfinite(atr) or atr <= 0:
        return None
    buffer = max(TICK_FLOOR, M15_ATR_STOP_BUFFER * float(atr))
    window = [*preceding_three, current]
    if direction == "LONG":
        extreme = min(float(row["low"]) for row in window)
        stop = extreme - buffer
    else:
        extreme = max(float(row["high"]) for row in window)
        stop = extreme + buffer
    destination = (
        _range_destination(context, direction, price)
        if context["family"] == "RANGE_ROTATION"
        else _trend_destination(
            stream, cutoff=cutoff, direction=direction, price=price
        )
    )
    disposition = "ELIGIBLE_FOR_NEXT_M1_ENTRY" if destination is not None else "NO_TRADE_NO_KNOWN_DESTINATION"
    payload: dict[str, Any] = {
        "ruleset": RULESET,
        "case_alias": str(stream["case_alias"]),
        "trading_date_utc": str(stream["trading_date_utc"]),
        "decision_at": cutoff,
        "direction": direction,
        "family": str(context["family"]),
        "context_identity": str(context["context_identity"]),
        "m15_structure": context["m15_structure"],
        "controlling_swing": {
            "identity": str(context["control"]["identity"]),
            "kind": str(context["control"]["kind"]),
            "level": float(context["control"]["level"]),
            "pivot_at": iso(context["control"]["pivot_at"]),
            "known_at": iso(context["control"].get("known_at", context["control"].get("detected_at"))),
            "strictly_unconsumed_at_decision": True,
        },
        "higher_timeframe_context": _higher_timeframe_context(
            stream, cutoff, direction
        ),
        "m5_trigger": {
            "preceding_open_times": [iso(row["open_at"]) for row in preceding_three],
            "turn_open_at": iso(current["open_at"]),
            "turn_available_at": cutoff,
            "turn_close": price,
            "curvature_extreme": extreme,
            "rule": "THREE_BAR_ADVERSE_PULLBACK_THEN_FIRST_DIRECTIONAL_HALF_CLOSE",
        },
        "geometry_at_decision": {
            "entry_reference": price,
            "stop": stop,
            "buffer": buffer,
            "m15_atr14": float(atr),
            "destination": destination,
        },
        "disposition": disposition,
        "point_in_time_only": True,
    }
    payload["decision_identity"] = canonical_hash(
        [
            RULESET,
            payload["case_alias"],
            cutoff,
            direction,
            payload["context_identity"],
            payload["m5_trigger"]["preceding_open_times"],
        ]
    )
    payload["decision_sha256"] = canonical_hash(payload)
    return payload


def scan_stream(stream: Mapping[str, Any]) -> list[dict[str, Any]]:
    start = parse_dt(str(stream["start_inclusive"]))
    end = parse_dt(str(stream["end_exclusive"]))
    rows = complete_rows(stream["timeframes"]["5m"], str(stream["end_exclusive"]))
    output: list[dict[str, Any]] = []
    for index in range(3, len(rows)):
        current = rows[index]
        decision_at = parse_dt(current["available_at"])
        if not (start < decision_at < end):
            continue
        decision = build_decision(stream, rows[index - 3:index], current)
        if decision is not None:
            output.append(decision)
    output.sort(key=lambda row: (parse_dt(row["decision_at"]), row["decision_identity"]))
    identities = [row["decision_identity"] for row in output]
    if len(identities) != len(set(identities)):
        raise RuntimeError(f"Duplicate early-M5 decision in {stream['case_alias']}")
    return output


def _spread(row: Mapping[str, Any]) -> float:
    value = row.get("spread_price")
    if value is None:
        return SPREAD_FALLBACK
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else SPREAD_FALLBACK


def resolve_decision(
    stream: Mapping[str, Any], decision: Mapping[str, Any]
) -> dict[str, Any]:
    base = {
        "decision_identity": str(decision["decision_identity"]),
        "case_alias": str(decision["case_alias"]),
        "trading_date_utc": str(decision["trading_date_utc"]),
        "decision_at": str(decision["decision_at"]),
        "direction": str(decision["direction"]),
        "family": str(decision["family"]),
        "higher_timeframe_alignment": str(
            decision["higher_timeframe_context"]["combined_alignment"]
        ),
    }
    if decision["disposition"] != "ELIGIBLE_FOR_NEXT_M1_ENTRY":
        payload = {**base, "executed": False, "disposition": decision["disposition"]}
        payload["lifecycle_sha256"] = canonical_hash(payload)
        return payload

    point = parse_dt(str(decision["decision_at"]))
    end = parse_dt(str(stream["end_exclusive"]))
    m1 = complete_rows(stream["timeframes"]["1m"], str(stream["end_exclusive"]))
    fill_bar = next(
        (row for row in m1 if point < parse_dt(row["open_at"]) < end), None
    )
    if fill_bar is None:
        payload = {**base, "executed": False, "disposition": "NO_NEXT_M1_ENTRY"}
        payload["lifecycle_sha256"] = canonical_hash(payload)
        return payload

    direction: Direction = str(decision["direction"])  # type: ignore[assignment]
    sign = 1.0 if direction == "LONG" else -1.0
    fill = float(fill_bar["open"])
    stop = float(decision["geometry_at_decision"]["stop"])
    target = float(decision["geometry_at_decision"]["destination"]["level"])
    valid = stop < fill < target if direction == "LONG" else target < fill < stop
    if not valid:
        payload = {
            **base,
            "executed": False,
            "disposition": "NO_TRADE_GEOMETRY_INVALID_AT_ACTUAL_FILL",
            "fill_at": iso(fill_bar["open_at"]),
        }
        payload["lifecycle_sha256"] = canonical_hash(payload)
        return payload

    risk = abs(fill - stop)
    quantity = math.floor(RISK_BUDGET_USD / risk)
    if quantity < 1:
        payload = {
            **base,
            "executed": False,
            "disposition": "NO_TRADE_WHOLE_OUNCE_EXCEEDS_RISK_BUDGET",
            "fill_at": iso(fill_bar["open_at"]),
        }
        payload["lifecycle_sha256"] = canonical_hash(payload)
        return payload

    path = [
        row
        for row in m1
        if parse_dt(row["open_at"]) >= parse_dt(fill_bar["open_at"])
        and parse_dt(row["open_at"]) < end
    ]
    if not path:
        raise RuntimeError("No post-fill path")
    exit_price: float | None = None
    exit_at: str | None = None
    resolution: str | None = None
    favourable = 0.0
    adverse = 0.0
    for row in path:
        favourable = max(
            favourable,
            float(row["high"]) - fill if direction == "LONG" else fill - float(row["low"]),
        )
        adverse = max(
            adverse,
            fill - float(row["low"]) if direction == "LONG" else float(row["high"]) - fill,
        )
        stop_hit = float(row["low"]) <= stop if direction == "LONG" else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if stop_hit:
            exit_price = stop
            exit_at = iso(row["available_at"])
            resolution = "STOP_FIRST_AMBIGUOUS_M1" if target_hit else "STRUCTURAL_STOP"
            break
        if target_hit:
            exit_price = target
            exit_at = iso(row["available_at"])
            resolution = "LIQUIDITY_TARGET"
            break
    if exit_price is None:
        terminal = path[-1]
        exit_price = float(terminal["close"])
        exit_at = iso(terminal["available_at"])
        resolution = "UTC_DAY_TIME_EXIT"

    spread = _spread(fill_bar)
    cost_per_ounce = spread + 2.0 * SLIPPAGE_USD_PER_OUNCE_PER_SIDE
    gross_price = sign * (exit_price - fill)
    gross_unit_r = gross_price / risk
    cost_unit_r = cost_per_ounce / risk
    net_unit_r = gross_unit_r - cost_unit_r
    planned_risk_usd = quantity * risk
    gross_usd = quantity * gross_price
    cost_usd = quantity * cost_per_ounce
    payload = {
        **base,
        "executed": True,
        "disposition": "EXECUTED",
        "fill_at": iso(fill_bar["open_at"]),
        "fill": fill,
        "stop": stop,
        "target": target,
        "structural_risk_per_ounce": risk,
        "quantity_ounces": quantity,
        "planned_risk_usd": planned_risk_usd,
        "cost_per_ounce": cost_per_ounce,
        "resolution": resolution,
        "final_at": exit_at,
        "exit_price": exit_price,
        "gross_unit_r": gross_unit_r,
        "cost_unit_r": cost_unit_r,
        "net_unit_r": net_unit_r,
        "gross_usd": gross_usd,
        "cost_usd": cost_usd,
        "net_usd": gross_usd - cost_usd,
        "net_r50": (gross_usd - cost_usd) / RISK_BUDGET_USD,
        "mfe_unit_r": favourable / risk,
        "mae_unit_r": adverse / risk,
    }
    payload["lifecycle_sha256"] = canonical_hash(payload)
    return payload


def match_to_census(
    decisions: Sequence[Mapping[str, Any]],
    census: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Outcome-independent chronological one-to-one attribution."""

    eligible = [
        row for row in decisions
        if row.get("direction") in {"LONG", "SHORT"}
    ]
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for row in eligible:
        by_date.setdefault(str(row["trading_date_utc"]), []).append(row)
    for rows in by_date.values():
        rows.sort(key=lambda row: (parse_dt(row["decision_at"]), row["decision_identity"]))

    used: set[str] = set()
    matches: list[dict[str, Any]] = []
    missed: list[str] = []
    ordered_cases = sorted(
        census, key=lambda row: (parse_dt(row["pivot_at_utc"]), row["combined_case_id"])
    )
    for case in ordered_cases:
        direction = "LONG" if case["direction"] == "UP" else "SHORT"
        start = parse_dt(case["pivot_at_utc"]) - timedelta(minutes=15)
        end = parse_dt(case["known_at_utc"])
        candidates = [
            row
            for row in by_date.get(str(case["pivot_at_utc"])[:10], [])
            if row["direction"] == direction
            and row["decision_identity"] not in used
            and start <= parse_dt(row["decision_at"]) < end
        ]
        if not candidates:
            missed.append(str(case["combined_case_id"]))
            continue
        selected = candidates[0]
        used.add(str(selected["decision_identity"]))
        matches.append(
            {
                "combined_case_id": str(case["combined_case_id"]),
                "pivot_at_utc": str(case["pivot_at_utc"]),
                "known_at_utc": str(case["known_at_utc"]),
                "direction": direction,
                "decision_identity": str(selected["decision_identity"]),
                "decision_at": str(selected["decision_at"]),
                "minutes_before_m15_known": (
                    end - parse_dt(selected["decision_at"])
                ).total_seconds() / 60.0,
            }
        )
    unmatched = [
        str(row["decision_identity"])
        for row in eligible
        if str(row["decision_identity"]) not in used
    ]
    payload = {
        "matches": matches,
        "missed_case_ids": missed,
        "unmatched_decision_ids": unmatched,
        "matched_count": len(matches),
        "missed_count": len(missed),
        "unmatched_count": len(unmatched),
    }
    payload["attribution_sha256"] = canonical_hash(payload)
    return payload


def summarize_lifecycles(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    executed = [row for row in rows if row.get("executed") is True]
    net = [float(row["net_unit_r"]) for row in executed]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in net:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    dispositions: dict[str, int] = {}
    for row in rows:
        key = str(row["disposition"])
        dispositions[key] = dispositions.get(key, 0) + 1
    return {
        "decisions": len(rows),
        "executed": len(executed),
        "dispositions": dict(sorted(dispositions.items())),
        "win_rate": len(wins) / len(executed) if executed else None,
        "net_unit_r": sum(net),
        "expectancy_unit_r": sum(net) / len(executed) if executed else None,
        "profit_factor": (
            sum(wins) / abs(sum(losses)) if losses else None
        ),
        "max_drawdown_unit_r": max_drawdown,
        "net_usd": sum(float(row["net_usd"]) for row in executed),
        "net_r50": sum(float(row["net_r50"]) for row in executed),
    }


def synthetic_proof() -> dict[str, Any]:
    def bar(minute: int, o: float, h: float, low: float, c: float) -> dict[str, Any]:
        opened = f"2022-01-03T00:{minute:02d}:00Z"
        available = f"2022-01-03T00:{minute + 5:02d}:00Z"
        return {
            "open_at": opened,
            "available_at": available,
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "complete": True,
        }

    long_rows = [
        bar(0, 10.0, 10.2, 9.8, 10.1),
        bar(5, 10.1, 10.15, 9.7, 9.8),
        bar(10, 9.8, 9.85, 9.5, 9.6),
        bar(15, 9.55, 10.0, 9.45, 9.9),
    ]
    short_rows = [
        bar(0, 10.0, 10.2, 9.8, 9.9),
        bar(5, 9.9, 10.3, 9.85, 10.2),
        bar(10, 10.2, 10.5, 10.15, 10.4),
        bar(15, 10.45, 10.55, 10.0, 10.1),
    ]
    return {
        "long_first_response_detected": trigger_direction(long_rows[:3], long_rows[3]) == "LONG",
        "short_mirror_detected": trigger_direction(short_rows[:3], short_rows[3]) == "SHORT",
        "noncontiguous_rejected": trigger_direction(
            [long_rows[0], long_rows[1], {**long_rows[2], "open_at": "2022-01-03T00:11:00Z"}],
            long_rows[3],
        ) is None,
    }
