"""Deterministic matched-case attribution for original and true-negated trades."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import gold_intel.analytics.auction_trade_placement_outcomes_v1 as execution_base
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt

RULESET = "GOLD_CONTINUATION_TRUE_NEGATION_MATCHED_CASE_ATTRIBUTION_AUDIT_V1"
EPSILON = 1e-12
R_BENCHMARK_USD = 50.0
NEW_YORK = ZoneInfo("America/New_York")


def result_sign(value: float) -> str:
    if value > EPSILON:
        return "WIN"
    if value < -EPSILON:
        return "LOSS"
    return "SCRATCH"


def numeric_bin(value: float, cuts: Sequence[tuple[float, str]], final: str) -> str:
    for upper, label in cuts:
        if value < upper:
            return label
    return final


def planned_r_bin(value: float) -> str:
    return numeric_bin(
        value,
        ((0.5, "<0.5"), (1.0, "0.5-1.0"), (1.5, "1.0-1.5"), (2.0, "1.5-2.0")),
        ">=2.0",
    )


def break_distance_bin(value: float) -> str:
    return numeric_bin(value, ((1.0, "<1"), (2.0, "1-2"), (4.0, "2-4")), ">=4")


def time_remaining_bin(value: float) -> str:
    return numeric_bin(
        value,
        ((30.0, "<30m"), (60.0, "30-60m"), (120.0, "60-120m")),
        ">=120m",
    )


def pivot_age_bin(value: float) -> str:
    return numeric_bin(
        value,
        ((15.0, "<15m"), (30.0, "15-30m"), (60.0, "30-60m")),
        ">=60m",
    )


def target_age_bin(value: float) -> str:
    return numeric_bin(
        value,
        ((60.0, "<1h"), (240.0, "1-4h"), (1440.0, "4-24h")),
        ">=24h",
    )


def decision_phase(decision_at: str) -> str:
    local = parse_dt(decision_at).astimezone(NEW_YORK)
    minute = local.hour * 60 + local.minute
    if 8 * 60 <= minute < 9 * 60 + 30:
        return "08:00-09:30"
    if 9 * 60 + 30 <= minute < 10 * 60 + 30:
        return "09:30-10:30"
    if 10 * 60 + 30 <= minute < 11 * 60 + 30:
        return "10:30-11:30"
    if 11 * 60 + 30 <= minute < 12 * 60:
        return "11:30-12:00"
    return "OUTSIDE_FROZEN_PHASES"


def structure_state(context: Mapping[str, Any]) -> str:
    relations = dict(context.get("swing_relations") or {})
    high = str(relations.get("high", "UNKNOWN"))
    low = str(relations.get("low", "UNKNOWN"))
    if high == "HH" and low == "HL":
        return "UP_TREND"
    if high == "LH" and low == "LL":
        return "DOWN_TREND"
    return "MIXED_OR_RANGE"


def directional_alignment(state: str, direction: str) -> str:
    if state == "MIXED_OR_RANGE":
        return "MIXED_OR_RANGE"
    if (state == "UP_TREND" and direction == "LONG") or (
        state == "DOWN_TREND" and direction == "SHORT"
    ):
        return "ALIGNED"
    return "CONTRADICTED"


def macro_alignment(macro: Mapping[str, Any], direction: str) -> str:
    state = str(macro.get("state") or macro.get("bias_label") or "UNKNOWN").upper()
    if "BULL" in state:
        return "ALIGNED" if direction == "LONG" else "CONTRADICTED"
    if "BEAR" in state:
        return "ALIGNED" if direction == "SHORT" else "CONTRADICTED"
    return "NEUTRAL_OR_UNKNOWN"


def former_quality_state(reasons: Sequence[str]) -> str:
    values = set(reasons)
    chase = "DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR" in values
    room = "TARGET_ROOM_BELOW_1P5R" in values
    if chase and room:
        return "CHASE_AND_ROOM"
    if chase:
        return "CHASE_ONLY"
    if room:
        return "ROOM_ONLY"
    return "NONE"


def run_ordinal_label(value: int) -> str:
    if value == 1:
        return "FIRST_IN_RUN"
    if value == 2:
        return "SECOND_IN_RUN"
    if value == 3:
        return "THIRD_IN_RUN"
    return "FOURTH_PLUS_IN_RUN"


def assign_run_ordinals(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    eligible = sorted(
        (
            row
            for row in rows
            if row.get("mechanically_executable")
            and row.get("event_class") == "CONTINUATION_REFRESH"
        ),
        key=lambda row: (
            str(row["trading_date_utc"]),
            parse_dt(str(row["decision_at"])),
            str(row["event_identity"]),
        ),
    )
    output: dict[str, dict[str, Any]] = {}
    day = None
    direction = None
    run_number = 0
    ordinal = 0
    for row in eligible:
        row_day = str(row["trading_date_utc"])
        row_direction = str(row["direction"])
        if row_day != day:
            day = row_day
            direction = None
            run_number = 0
            ordinal = 0
        if row_direction != direction:
            direction = row_direction
            run_number += 1
            ordinal = 1
        else:
            ordinal += 1
        output[str(row["event_identity"])] = {
            "continuation_run_number_day": run_number,
            "continuation_ordinal_in_run": ordinal,
            "continuation_ordinal_label": run_ordinal_label(ordinal),
            "continuation_run_identity": canonical_hash(
                {"date": row_day, "direction": row_direction, "run_number": run_number}
            ),
        }
    return output


def point_in_time_groups(
    compiled_row: Mapping[str, Any], run_state: Mapping[str, Any]
) -> dict[str, Any]:
    plan = dict(compiled_row["plan"])
    direction = str(plan["direction"])
    decision = parse_dt(str(plan["decision_at"]))
    deadline = execution_base.session_deadline(str(plan["decision_at"]))
    pivot = dict(plan["protected_pivot"])
    target = dict(plan["target"])
    local = plan.get("local_m15_liquidity")
    htf = dict(plan.get("higher_timeframe_context") or {})
    h1 = structure_state(dict(htf.get("H1") or {}))
    h4 = structure_state(dict(htf.get("H4") or {}))
    pivot_age = (decision - parse_dt(str(pivot["known_at"]))).total_seconds() / 60.0
    target_age = (decision - parse_dt(str(target["known_at"]))).total_seconds() / 60.0
    time_remaining = (deadline - decision).total_seconds() / 60.0
    local_matches = bool(
        isinstance(local, Mapping)
        and local.get("level") is not None
        and target.get("level") is not None
        and float(local["level"]) == float(target["level"])
    )
    payload: dict[str, Any] = {
        "original_direction": direction,
        "month": str(plan["trading_date_utc"])[:7],
        "context_family": str(plan["context_family"]),
        "macro_alignment": macro_alignment(dict(plan.get("macro_context") or {}), direction),
        "macro_state": str((plan.get("macro_context") or {}).get("state") or "UNKNOWN"),
        "h1_structure_state": h1,
        "h1_alignment": directional_alignment(h1, direction),
        "h4_structure_state": h4,
        "h4_alignment": directional_alignment(h4, direction),
        "target_timeframe": str(target.get("timeframe") or "UNKNOWN"),
        "local_m15_matches_htf_target_level": "MATCH"
        if local_matches
        else "DIFFERENT_OR_MISSING",
        "former_quality_state": former_quality_state(
            list(compiled_row.get("ignored_former_quality_filters") or [])
        ),
        "planned_r_bin": planned_r_bin(float(plan["planned_r"])),
        "break_distance_bin": break_distance_bin(float(plan["distance_from_m5_break_atr"])),
        "decision_phase": decision_phase(str(plan["decision_at"])),
        "time_remaining_bin": time_remaining_bin(time_remaining),
        "pivot_age_bin": pivot_age_bin(pivot_age),
        "target_age_bin": target_age_bin(target_age),
        "continuation_ordinal_label": str(run_state["continuation_ordinal_label"]),
        "continuation_run_number_day": int(run_state["continuation_run_number_day"]),
        "continuation_ordinal_in_run": int(run_state["continuation_ordinal_in_run"]),
        "continuation_run_identity": str(run_state["continuation_run_identity"]),
    }
    payload["point_in_time_groups_sha256"] = canonical_hash(payload)
    return payload


def _complete_path(
    bars: Sequence[Mapping[str, Any]], start: datetime, end: datetime
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in bars
        if row.get("complete") is True
        and start <= parse_dt(str(row["open_at"])) < end
        and parse_dt(str(row["available_at"])) <= end
    ]


def _target_touched(row: Mapping[str, Any], direction: str, target: float) -> bool:
    return float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target


def _entry_reclaimed(row: Mapping[str, Any], direction: str, entry: float) -> bool:
    return float(row["high"]) >= entry if direction == "LONG" else float(row["low"]) <= entry


def _favourable_price(
    rows: Sequence[Mapping[str, Any]], direction: str, reference: float
) -> float:
    if not rows:
        return 0.0
    if direction == "LONG":
        return max(0.0, max(float(row["high"]) for row in rows) - reference)
    return max(0.0, reference - min(float(row["low"]) for row in rows))


def _adverse_price(
    rows: Sequence[Mapping[str, Any]], direction: str, reference: float
) -> float:
    if not rows:
        return 0.0
    if direction == "LONG":
        return max(0.0, reference - min(float(row["low"]) for row in rows))
    return max(0.0, max(float(row["high"]) for row in rows) - reference)


def _deadline_exit(
    direction: str, quantity: int, last: Mapping[str, Any], actual_fill: float
) -> dict[str, float]:
    sign = 1.0 if direction == "LONG" else -1.0
    raw_exit = float(last["close"])
    half_spread = execution_base.spread(dict(last)) / 2.0
    actual_exit = (
        raw_exit - half_spread - execution_base.SLIPPAGE_PRICE
        if direction == "LONG"
        else raw_exit + half_spread + execution_base.SLIPPAGE_PRICE
    )
    pnl = sign * (actual_exit - actual_fill) * quantity
    return {"raw_exit": raw_exit, "actual_exit": actual_exit, "net_pnl_usd": pnl}


def analyse_track(result: Mapping[str, Any], bars: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    execution = dict(result["execution"])
    structural = dict(result["structural"])
    direction = str(result["direction"])
    sign = 1.0 if direction == "LONG" else -1.0
    quantity = int(execution["quantity_ounces"])
    entry = float(result["entry"])
    target = float(result["target"])
    fill = float(execution["actual_fill"])
    fill_at = parse_dt(str(execution["fill_at"]))
    exit_at = parse_dt(str(execution["exit_at"]))
    deadline = parse_dt(str(execution["deadline"]))
    path = _complete_path(bars, fill_at, deadline)
    if not path:
        raise RuntimeError(f"Missing audit path: {result['event_identity']}")
    pre_exit = [row for row in path if parse_dt(str(row["open_at"])) < exit_at]
    post_exit = [row for row in path if parse_dt(str(row["open_at"])) >= exit_at]
    available_mfe_usd = _favourable_price(path, direction, fill) * quantity
    available_mae_usd = _adverse_price(path, direction, fill) * quantity
    pre_exit_mfe_usd = _favourable_price(pre_exit, direction, fill) * quantity
    post_exit_extension_usd = 0.0
    if execution["resolution"] == "TARGET_HIT":
        post_exit_extension_usd = _favourable_price(post_exit, direction, target) * quantity
    stopped_disposition = None
    stopped_then_target_opportunity_usd = 0.0
    if execution["resolution"] == "STOPPED":
        if any(_target_touched(row, direction, target) for row in post_exit):
            stopped_disposition = "STOP_THEN_TARGET"
            stopped_then_target_opportunity_usd = sign * (target - fill) * quantity
        elif any(_entry_reclaimed(row, direction, entry) for row in post_exit):
            stopped_disposition = "STOP_THEN_ENTRY_RECLAIM"
        else:
            stopped_disposition = "STOP_CONFIRMED_TO_DEADLINE"
    deadline_exit = _deadline_exit(direction, quantity, path[-1], fill)
    raw_gross_pnl = sign * (
        float(execution["raw_exit"]) - float(execution["raw_fill"])
    ) * quantity
    net_pnl = float(execution["net_pnl_usd"])
    explicit_cost_drag = raw_gross_pnl - net_pnl
    market_entry_degradation = sign * (float(execution["raw_fill"]) - entry) * quantity
    total_entry_degradation = sign * (fill - entry) * quantity
    resolution_map = {
        "STOP_FIRST": "STOPPED",
        "TARGET_FIRST": "TARGET_HIT",
        "TIME_EXIT": "TIME_EXIT",
    }
    structural_execution_agreement = (
        resolution_map.get(str(structural["resolution"])) == execution["resolution"]
    )
    payload: dict[str, Any] = {
        "direction": direction,
        "resolution": str(execution["resolution"]),
        "result_sign": result_sign(net_pnl),
        "quantity_ounces": quantity,
        "net_pnl_usd": net_pnl,
        "net_r50": net_pnl / R_BENCHMARK_USD,
        "raw_gross_pnl_usd": raw_gross_pnl,
        "explicit_cost_drag_usd": explicit_cost_drag,
        "explicit_cost_drag_r50": explicit_cost_drag / R_BENCHMARK_USD,
        "market_entry_degradation_usd": market_entry_degradation,
        "market_entry_degradation_r50": market_entry_degradation / R_BENCHMARK_USD,
        "total_entry_degradation_usd": total_entry_degradation,
        "total_entry_degradation_r50": total_entry_degradation / R_BENCHMARK_USD,
        "available_mfe_usd": available_mfe_usd,
        "available_mfe_r50": available_mfe_usd / R_BENCHMARK_USD,
        "available_mae_usd": available_mae_usd,
        "available_mae_r50": available_mae_usd / R_BENCHMARK_USD,
        "pre_exit_mfe_usd": pre_exit_mfe_usd,
        "pre_exit_mfe_r50": pre_exit_mfe_usd / R_BENCHMARK_USD,
        "mfe_not_captured_usd": available_mfe_usd - max(net_pnl, 0.0),
        "mfe_not_captured_r50": (available_mfe_usd - max(net_pnl, 0.0))
        / R_BENCHMARK_USD,
        "positive_capture_efficiency": (
            net_pnl / available_mfe_usd
            if net_pnl > EPSILON and available_mfe_usd > EPSILON
            else None
        ),
        "post_exit_extension_usd": post_exit_extension_usd,
        "post_exit_extension_r50": post_exit_extension_usd / R_BENCHMARK_USD,
        "deadline_exit_net_pnl_usd": deadline_exit["net_pnl_usd"],
        "deadline_exit_net_r50": deadline_exit["net_pnl_usd"] / R_BENCHMARK_USD,
        "deadline_minus_actual_usd": deadline_exit["net_pnl_usd"] - net_pnl,
        "deadline_minus_actual_r50": (deadline_exit["net_pnl_usd"] - net_pnl)
        / R_BENCHMARK_USD,
        "stopped_disposition": stopped_disposition,
        "stopped_then_target_opportunity_usd": stopped_then_target_opportunity_usd,
        "stopped_then_target_opportunity_r50": stopped_then_target_opportunity_usd
        / R_BENCHMARK_USD,
        "stopped_then_target_recovery_delta_usd": (
            stopped_then_target_opportunity_usd - net_pnl
            if stopped_disposition == "STOP_THEN_TARGET"
            else 0.0
        ),
        "stopped_then_target_recovery_delta_r50": (
            (stopped_then_target_opportunity_usd - net_pnl) / R_BENCHMARK_USD
            if stopped_disposition == "STOP_THEN_TARGET"
            else 0.0
        ),
        "ambiguous_stop_first": bool(execution["ambiguous_stop_first"]),
        "structural_resolution": str(structural["resolution"]),
        "structural_execution_agreement": structural_execution_agreement,
        "path_bars_to_deadline": len(path),
        "post_exit_path_bars": len(post_exit),
    }
    payload["track_attribution_sha256"] = canonical_hash(payload)
    return payload


def analyse_pair(
    compiled_row: Mapping[str, Any],
    original_result: Mapping[str, Any],
    negated_result: Mapping[str, Any],
    bars: Sequence[Mapping[str, Any]],
    run_state: Mapping[str, Any],
) -> dict[str, Any]:
    original_track = analyse_track(original_result, bars)
    negated_track = analyse_track(negated_result, bars)
    groups = point_in_time_groups(compiled_row, run_state)
    payload: dict[str, Any] = {
        "event_identity": str(compiled_row["event_identity"]),
        "case_alias": str(compiled_row["case_alias"]),
        "trading_date_utc": str(compiled_row["trading_date_utc"]),
        "decision_at": str(compiled_row["decision_at"]),
        "pair_result_transition": f"ORIGINAL_{original_track['result_sign']}__NEGATED_{negated_track['result_sign']}",
        "pair_resolution_transition": f"ORIGINAL_{original_track['resolution']}__NEGATED_{negated_track['resolution']}",
        "negation_delta_r50": negated_track["net_r50"] - original_track["net_r50"],
        "negation_delta_usd": negated_track["net_pnl_usd"] - original_track["net_pnl_usd"],
        "groups": groups,
        "original": original_track,
        "negated": negated_track,
    }
    payload["matched_case_sha256"] = canonical_hash(payload)
    return payload


def economic_summary(values: Sequence[float]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    positive = sum(value for value in numbers if value > EPSILON)
    negative = -sum(value for value in numbers if value < -EPSILON)
    return {
        "trades": len(numbers),
        "wins": sum(value > EPSILON for value in numbers),
        "losses": sum(value < -EPSILON for value in numbers),
        "scratches": sum(abs(value) <= EPSILON for value in numbers),
        "win_rate": None if not numbers else sum(value > EPSILON for value in numbers) / len(numbers),
        "net_r50": sum(numbers),
        "expectancy_r50": None if not numbers else sum(numbers) / len(numbers),
        "gross_profit_r50": positive,
        "gross_loss_r50": negative,
        "profit_factor": positive / negative if negative > EPSILON else None,
    }


GROUP_FIELDS = (
    "original_direction",
    "month",
    "context_family",
    "macro_alignment",
    "macro_state",
    "h1_structure_state",
    "h1_alignment",
    "h4_structure_state",
    "h4_alignment",
    "target_timeframe",
    "local_m15_matches_htf_target_level",
    "former_quality_state",
    "planned_r_bin",
    "break_distance_bin",
    "decision_phase",
    "time_remaining_bin",
    "pivot_age_bin",
    "target_age_bin",
    "continuation_ordinal_label",
)


def _track_diagnostics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    tracks = [dict(row[key]) for row in rows]
    stopped = [row for row in tracks if row["resolution"] == "STOPPED"]
    targets = [row for row in tracks if row["resolution"] == "TARGET_HIT"]
    time_exits = [row for row in tracks if row["resolution"] == "TIME_EXIT"]
    efficiencies = [
        float(row["positive_capture_efficiency"])
        for row in tracks
        if row["positive_capture_efficiency"] is not None
    ]
    target_deadline_deltas = [float(row["deadline_minus_actual_r50"]) for row in targets]
    return {
        "economic": economic_summary([float(row["net_r50"]) for row in tracks]),
        "resolution_counts": dict(sorted(Counter(str(row["resolution"]) for row in tracks).items())),
        "structural_execution_disagreements": sum(
            not bool(row["structural_execution_agreement"]) for row in tracks
        ),
        "ambiguous_stop_first": sum(bool(row["ambiguous_stop_first"]) for row in tracks),
        "stops": {
            "count": len(stopped),
            "dispositions": dict(
                sorted(Counter(str(row["stopped_disposition"]) for row in stopped).items())
            ),
            "pre_stop_mfe_r50_total": sum(float(row["pre_exit_mfe_r50"]) for row in stopped),
            "pre_stop_mfe_r50_median": statistics.median(
                [float(row["pre_exit_mfe_r50"]) for row in stopped]
            )
            if stopped
            else None,
            "stopped_then_target_opportunity_r50_total": sum(
                float(row["stopped_then_target_opportunity_r50"]) for row in stopped
            ),
            "stopped_then_target_recovery_delta_r50_total": sum(
                float(row["stopped_then_target_recovery_delta_r50"]) for row in stopped
            ),
        },
        "targets": {
            "count": len(targets),
            "post_target_extension_r50_total": sum(
                float(row["post_exit_extension_r50"]) for row in targets
            ),
            "post_target_extension_r50_median": statistics.median(
                [float(row["post_exit_extension_r50"]) for row in targets]
            )
            if targets
            else None,
            "deadline_better_count": sum(value > EPSILON for value in target_deadline_deltas),
            "deadline_worse_count": sum(value < -EPSILON for value in target_deadline_deltas),
            "deadline_equal_count": sum(abs(value) <= EPSILON for value in target_deadline_deltas),
            "deadline_minus_actual_r50_total": sum(target_deadline_deltas),
        },
        "time_exits": {
            "count": len(time_exits),
            "mfe_not_captured_r50_total": sum(
                float(row["mfe_not_captured_r50"]) for row in time_exits
            ),
            "deadline_net_r50": sum(float(row["net_r50"]) for row in time_exits),
        },
        "available_mfe_r50_total": sum(float(row["available_mfe_r50"]) for row in tracks),
        "mfe_not_captured_r50_total": sum(float(row["mfe_not_captured_r50"]) for row in tracks),
        "positive_capture_efficiency_mean": statistics.fmean(efficiencies) if efficiencies else None,
        "positive_capture_efficiency_median": statistics.median(efficiencies) if efficiencies else None,
        "explicit_cost_drag_r50_total": sum(float(row["explicit_cost_drag_r50"]) for row in tracks),
        "market_entry_degradation_r50_total": sum(
            float(row["market_entry_degradation_r50"]) for row in tracks
        ),
        "total_entry_degradation_r50_total": sum(
            float(row["total_entry_degradation_r50"]) for row in tracks
        ),
    }


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[Mapping[str, Any]]]] = {
        field: defaultdict(list) for field in GROUP_FIELDS
    }
    for row in rows:
        for field in GROUP_FIELDS:
            grouped[field][str(row["groups"][field])].append(row)
    group_tables: dict[str, dict[str, Any]] = {}
    for field in GROUP_FIELDS:
        values: dict[str, Any] = {}
        for value in sorted(grouped[field]):
            members = grouped[field][value]
            original = economic_summary([float(row["original"]["net_r50"]) for row in members])
            negated = economic_summary([float(row["negated"]["net_r50"]) for row in members])
            values[value] = {
                "support": len(members),
                "original": original,
                "negated": negated,
                "negation_delta_r50": negated["net_r50"] - original["net_r50"],
            }
        group_tables[field] = values
    payload: dict[str, Any] = {
        "matched_cases": len(rows),
        "pair_result_transition_counts": dict(
            sorted(Counter(str(row["pair_result_transition"]) for row in rows).items())
        ),
        "pair_resolution_transition_counts": dict(
            sorted(Counter(str(row["pair_resolution_transition"]) for row in rows).items())
        ),
        "original": _track_diagnostics(rows, "original"),
        "negated": _track_diagnostics(rows, "negated"),
        "negation_delta_r50_total": sum(float(row["negation_delta_r50"]) for row in rows),
        "negation_delta_usd_total": sum(float(row["negation_delta_usd"]) for row in rows),
        "group_tables": group_tables,
    }
    payload["aggregate_sha256"] = canonical_hash(payload)
    return payload
