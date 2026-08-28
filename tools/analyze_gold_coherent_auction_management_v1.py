"""Exposed matched-case calibration of coherent auction geometry and management."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from analyze_gold_same_timeframe_target_v1 import (
    COMPARISON,
    ROOT,
    canonical_hash,
    load_stream,
    round_floats,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_management_v1"
RESULT = OUTPUT / "coherent_auction_management_result.json"
TABLE = OUTPUT / "coherent_auction_management_cases.csv"
PROTOCOL = ROOT / "GOLD_MATCHED_HUMAN_COHERENT_AUCTION_MANAGEMENT_CALIBRATION_PROTOCOL_V1.md"

ATR_WINDOW = 14
PIVOT_WIDTH = 2
PIVOT_PROMINENCE_ATR = 0.25
BREAK_BUFFER_ATR = 0.10
LEVEL_ENGAGEMENT_ATR = 0.10
LEVEL_RESPONSE_ATR = 0.05
TICK_FLOOR = 0.02
MAX_RESPONSE_M5_BARS = 3
RISK_BUDGET_USD = 50.0


def eligible_rows(rows: list[dict], cutoff: str) -> list[dict]:
    return sorted(
        [
            row
            for row in rows
            if row.get("complete") is True and row["available_at"] <= cutoff
        ],
        key=lambda row: (row["open_at"], row["available_at"]),
    )


def atr_values(rows: list[dict]) -> list[float]:
    true_ranges: list[float] = []
    output: list[float] = []
    for index, row in enumerate(rows):
        high = float(row["high"])
        low = float(row["low"])
        if index == 0:
            value = high - low
        else:
            prior_close = float(rows[index - 1]["close"])
            value = max(high - low, abs(high - prior_close), abs(low - prior_close))
        true_ranges.append(value)
        members = true_ranges[max(0, index - ATR_WINDOW + 1) : index + 1]
        output.append(sum(members) / len(members))
    return output


def confirmed_swings(rows: list[dict], cutoff: str, timeframe: str) -> tuple[list[dict], list[dict]]:
    bars = eligible_rows(rows, cutoff)
    atrs = atr_values(bars)
    swings: list[dict] = []
    if len(bars) < 2 * PIVOT_WIDTH + 1:
        return bars, swings
    for index in range(PIVOT_WIDTH, len(bars) - PIVOT_WIDTH):
        center = bars[index]
        neighbors = (
            bars[index - PIVOT_WIDTH : index]
            + bars[index + 1 : index + PIVOT_WIDTH + 1]
        )
        atr = max(atrs[index], 0.01)
        minimum = max(PIVOT_PROMINENCE_ATR * atr, TICK_FLOOR)
        candidates = (
            (
                "HIGH",
                float(center["high"]),
                float(center["high"]) - min(float(row["low"]) for row in neighbors),
            ),
            (
                "LOW",
                float(center["low"]),
                max(float(row["high"]) for row in neighbors) - float(center["low"]),
            ),
        )
        for kind, level, prominence in candidates:
            if kind == "HIGH":
                strict = all(level > float(row["high"]) for row in neighbors)
            else:
                strict = all(level < float(row["low"]) for row in neighbors)
            if not strict or prominence < minimum:
                continue
            detected_at = bars[index + PIVOT_WIDTH]["available_at"]
            identity = canonical_hash(
                ["SWING", timeframe, kind, center["open_at"], level, detected_at]
            )
            swings.append(
                {
                    "identity": identity,
                    "kind": kind,
                    "timeframe": timeframe,
                    "pivot_index": index,
                    "pivot_at": center["open_at"],
                    "detected_at": detected_at,
                    "level": level,
                    "atr": atr,
                    "prominence_atr": prominence / atr,
                }
            )
    return bars, sorted(swings, key=lambda row: (row["detected_at"], row["kind"]))


def bullish_break_events(rows: list[dict], cutoff: str, timeframe: str) -> list[dict]:
    bars, swings = confirmed_swings(rows, cutoff, timeframe)
    atrs = atr_values(bars)
    broken_highs: set[str] = set()
    events: list[dict] = []
    for index, bar in enumerate(bars):
        highs = [
            item
            for item in swings
            if item["kind"] == "HIGH"
            and item["detected_at"] <= bar["open_at"]
            and item["pivot_index"] < index
            and item["identity"] not in broken_highs
        ]
        if not highs:
            continue
        swing_high = max(highs, key=lambda item: item["pivot_index"])
        atr = max(atrs[index], 0.01)
        buffer = max(BREAK_BUFFER_ATR * atr, TICK_FLOOR)
        if float(bar["close"]) <= float(swing_high["level"]) + buffer:
            continue
        lows = [
            item
            for item in swings
            if item["kind"] == "LOW"
            and item["detected_at"] <= bar["open_at"]
            and item["pivot_index"] < index
        ]
        if not lows:
            continue
        protected = max(lows, key=lambda item: item["pivot_index"])
        broken_highs.add(str(swing_high["identity"]))
        events.append(
            {
                "identity": canonical_hash(
                    [
                        "BULLISH_BREAK",
                        timeframe,
                        swing_high["identity"],
                        protected["identity"],
                        bar["available_at"],
                    ]
                ),
                "timeframe": timeframe,
                "break_index": index,
                "break_at": bar["available_at"],
                "broken_high": swing_high["level"],
                "broken_high_identity": swing_high["identity"],
                "protected_low": protected["level"],
                "protected_low_identity": protected["identity"],
                "atr": atr,
                "buffer": buffer,
                "stop": float(protected["level"]) - buffer,
            }
        )
    return events


def active_bullish_break(rows: list[dict], cutoff: str, timeframe: str) -> dict | None:
    bars = eligible_rows(rows, cutoff)
    events = bullish_break_events(rows, cutoff, timeframe)
    active: list[dict] = []
    for event in events:
        invalidating = next(
            (
                row
                for row in bars[event["break_index"] + 1 :]
                if float(row["close"]) < float(event["stop"])
            ),
            None,
        )
        enriched = dict(event)
        enriched["invalidated_at"] = (
            invalidating["available_at"] if invalidating is not None else None
        )
        if invalidating is None:
            active.append(enriched)
    return max(active, key=lambda item: item["break_at"]) if active else None


def latest_atr(rows: list[dict], cutoff: str) -> float:
    bars = eligible_rows(rows, cutoff)
    if not bars:
        raise RuntimeError("No eligible rows for ATR")
    return atr_values(bars)[-1]


def untouched_after_confirmation(
    bars: list[dict], swing: dict, cutoff: str
) -> bool:
    return not any(
        row["available_at"] > swing["detected_at"]
        and row["available_at"] <= cutoff
        and float(row["high"]) >= float(swing["level"])
        for row in bars
    )


def level_registry(
    stream: dict,
    *,
    decision_at: str,
    fill: float,
    original_target: float,
    decision_m15_atr: float,
) -> list[dict]:
    band = max(LEVEL_ENGAGEMENT_ATR * decision_m15_atr, TICK_FLOOR)
    candidates: list[dict] = []
    for timeframe in ("15m", "1h"):
        bars, swings = confirmed_swings(
            stream["timeframes"][timeframe], decision_at, timeframe
        )
        for swing in swings:
            if swing["kind"] != "HIGH":
                continue
            if float(swing["level"]) <= fill + band:
                continue
            if not untouched_after_confirmation(bars, swing, decision_at):
                continue
            candidates.append(
                {
                    "identity": swing["identity"],
                    "level": float(swing["level"]),
                    "timeframe": timeframe,
                    "source": "CALCULATED_CONFIRMED_SWING",
                    "epistemic_status": "CALCULATED",
                    "state": "UNTOUCHED_AFTER_CONFIRMATION",
                    "detected_at": swing["detected_at"],
                    "prominence_atr": swing["prominence_atr"],
                    "priority": 2 if timeframe == "1h" else 1,
                }
            )
    if original_target > fill + band:
        candidates.append(
            {
                "identity": canonical_hash(
                    ["OPERATOR_H1_TARGET", decision_at, original_target]
                ),
                "level": original_target,
                "timeframe": "1h",
                "source": "SEALED_OPERATOR_DRAWING",
                "epistemic_status": "OBSERVED",
                "state": "POINT_IN_TIME_RECORDED",
                "detected_at": decision_at,
                "prominence_atr": None,
                "priority": 3,
            }
        )
    merged: list[dict] = []
    for candidate in sorted(candidates, key=lambda item: (item["level"], -item["priority"])):
        match_index = next(
            (
                index
                for index, existing in enumerate(merged)
                if abs(float(existing["level"]) - float(candidate["level"])) <= band
            ),
            None,
        )
        if match_index is None:
            merged.append(candidate)
        elif candidate["priority"] > merged[match_index]["priority"]:
            merged[match_index] = candidate
    for row in merged:
        row.pop("priority", None)
    return sorted(merged, key=lambda item: item["level"])


def invalid_track(reason: str) -> dict:
    return {
        "executable": False,
        "resolution": reason,
        "exit_at": None,
        "exit_price": None,
        "net_usd": 0.0,
        "net_r50": 0.0,
        "net_initial_r": None,
        "positive": False,
    }


def economic_result(
    *,
    fill: float,
    exit_price: float,
    exit_at: str,
    resolution: str,
    quantity: int,
    cost_per_ounce: float,
    planned_risk_usd: float,
    extra: dict[str, Any] | None = None,
) -> dict:
    gross_usd = (exit_price - fill) * quantity
    cost_usd = cost_per_ounce * quantity
    net_usd = gross_usd - cost_usd
    result: dict[str, Any] = {
        "executable": True,
        "resolution": resolution,
        "exit_at": exit_at,
        "exit_price": exit_price,
        "gross_usd": gross_usd,
        "cost_usd": cost_usd,
        "net_usd": net_usd,
        "net_r50": net_usd / RISK_BUDGET_USD,
        "net_initial_r": net_usd / planned_risk_usd,
        "positive": net_usd > 0,
    }
    if extra:
        result.update(extra)
    return result


def path_rows(stream: dict, fill_at: str) -> list[dict]:
    return [
        row
        for row in stream["timeframes"]["1m"]
        if row.get("complete") is True and row["open_at"] >= fill_at
    ]


def simulate_fixed(
    *,
    stream: dict,
    fill_at: str,
    fill: float,
    stop: float,
    target: float,
    quantity: int,
    cost_per_ounce: float,
    planned_risk_usd: float,
    label: str,
) -> dict:
    bars = path_rows(stream, fill_at)
    if not bars or not stop < fill < target:
        return invalid_track(f"{label}_INVALID_GEOMETRY")
    for bar in bars:
        if float(bar["low"]) <= stop:
            return economic_result(
                fill=fill,
                exit_price=stop,
                exit_at=bar["open_at"],
                resolution="STOP_FIRST",
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
            )
        if float(bar["high"]) >= target:
            return economic_result(
                fill=fill,
                exit_price=target,
                exit_at=bar["open_at"],
                resolution="TARGET_FIRST",
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
            )
    last = bars[-1]
    return economic_result(
        fill=fill,
        exit_price=float(last["close"]),
        exit_at=last["close_at"],
        resolution="TIME_EXIT",
        quantity=quantity,
        cost_per_ounce=cost_per_ounce,
        planned_risk_usd=planned_risk_usd,
    )


def stop_feasible_oracle(
    *,
    stream: dict,
    fill_at: str,
    fill: float,
    stop: float,
    quantity: int,
    cost_per_ounce: float,
    planned_risk_usd: float,
) -> dict:
    best_price = fill
    best_at = fill_at
    stopped_at: str | None = None
    for bar in path_rows(stream, fill_at):
        if float(bar["low"]) <= stop:
            stopped_at = bar["open_at"]
            break
        if float(bar["high"]) > best_price:
            best_price = float(bar["high"])
            best_at = bar["open_at"]
    result = economic_result(
        fill=fill,
        exit_price=best_price,
        exit_at=best_at,
        resolution="STOP_FEASIBLE_MFE_ORACLE",
        quantity=quantity,
        cost_per_ounce=cost_per_ounce,
        planned_risk_usd=planned_risk_usd,
        extra={"initial_stop_first_at": stopped_at},
    )
    result["research_credit"] = "NONE_HINDSIGHT_CEILING"
    return result


def simulate_runner(
    *,
    stream: dict,
    fill_at: str,
    fill: float,
    initial_stop: float,
    levels: list[dict],
    decision_m15_atr: float,
    quantity: int,
    cost_per_ounce: float,
    planned_risk_usd: float,
) -> dict:
    bars = path_rows(stream, fill_at)
    if not bars:
        return invalid_track("RUNNER_MISSING_PATH")
    m5_rows = sorted(
        [
            row
            for row in stream["timeframes"]["5m"]
            if row.get("complete") is True and row["available_at"] > fill_at
        ],
        key=lambda row: row["available_at"],
    )
    m5_breaks = sorted(
        bullish_break_events(
            stream["timeframes"]["5m"], stream["end_exclusive"], "5m"
        ),
        key=lambda row: row["break_at"],
    )
    response_band = max(LEVEL_RESPONSE_ATR * decision_m15_atr, TICK_FLOOR)
    current_stop = initial_stop
    level_index = 0
    active_level = levels[0] if levels else None
    touched_at: str | None = None
    response_count = 0
    consecutive_above = 0
    m5_index = 0
    break_index = 0
    accepted_levels: list[dict] = []
    rejected_levels: list[dict] = []
    no_acceptance_levels: list[dict] = []
    trail_changes: list[dict] = []
    last_accept_at: str | None = None
    last_accepted_level: float | None = None
    trail_active_for_last_accept = False
    pending_exit: tuple[str, str] | None = None

    for bar in bars:
        now = bar["open_at"]
        while m5_index < len(m5_rows) and m5_rows[m5_index]["available_at"] <= now:
            completed = m5_rows[m5_index]
            m5_index += 1
            if (
                last_accept_at is not None
                and last_accepted_level is not None
                and not trail_active_for_last_accept
                and completed["available_at"] > last_accept_at
                and float(completed["close"]) < last_accepted_level - response_band
            ):
                pending_exit = ("FAILED_ACCEPTANCE", completed["available_at"])
                break
            if touched_at is None or completed["available_at"] <= touched_at:
                continue
            response_count += 1
            close = float(completed["close"])
            level = float(active_level["level"]) if active_level is not None else None
            if level is None:
                continue
            if close > level + response_band:
                consecutive_above += 1
                if consecutive_above >= 2:
                    accepted = dict(active_level)
                    accepted["accepted_at"] = completed["available_at"]
                    accepted_levels.append(accepted)
                    last_accept_at = completed["available_at"]
                    last_accepted_level = level
                    trail_active_for_last_accept = False
                    level_index += 1
                    active_level = levels[level_index] if level_index < len(levels) else None
                    touched_at = None
                    response_count = 0
                    consecutive_above = 0
            elif close < level - response_band:
                rejected = dict(active_level)
                rejected["rejected_at"] = completed["available_at"]
                rejected_levels.append(rejected)
                pending_exit = ("LEVEL_REJECTION", completed["available_at"])
                break
            else:
                consecutive_above = 0
            if response_count >= MAX_RESPONSE_M5_BARS and touched_at is not None:
                expired = dict(active_level)
                expired["no_acceptance_at"] = completed["available_at"]
                no_acceptance_levels.append(expired)
                pending_exit = ("LEVEL_NO_ACCEPTANCE", completed["available_at"])
                break

        while break_index < len(m5_breaks) and m5_breaks[break_index]["break_at"] <= now:
            event = m5_breaks[break_index]
            break_index += 1
            if last_accept_at is None or event["break_at"] <= last_accept_at:
                continue
            proposed = float(event["stop"])
            if proposed > current_stop:
                trail_changes.append(
                    {
                        "available_at": event["break_at"],
                        "prior_stop": current_stop,
                        "new_stop": proposed,
                        "break_identity": event["identity"],
                    }
                )
                current_stop = proposed
                trail_active_for_last_accept = True

        open_price = float(bar["open"])
        if open_price <= current_stop:
            reason = "TRAIL_GAP_STOP" if current_stop > initial_stop else "INITIAL_GAP_STOP"
            return economic_result(
                fill=fill,
                exit_price=open_price,
                exit_at=now,
                resolution=reason,
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
                extra={
                    "initial_stop": initial_stop,
                    "final_stop": current_stop,
                    "accepted_levels": accepted_levels,
                    "rejected_levels": rejected_levels,
                    "no_acceptance_levels": no_acceptance_levels,
                    "trail_changes": trail_changes,
                },
            )
        if pending_exit is not None:
            reason, evidence_at = pending_exit
            return economic_result(
                fill=fill,
                exit_price=open_price,
                exit_at=now,
                resolution=reason,
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
                extra={
                    "management_evidence_at": evidence_at,
                    "initial_stop": initial_stop,
                    "final_stop": current_stop,
                    "accepted_levels": accepted_levels,
                    "rejected_levels": rejected_levels,
                    "no_acceptance_levels": no_acceptance_levels,
                    "trail_changes": trail_changes,
                },
            )
        if float(bar["low"]) <= current_stop:
            reason = "TRAIL_STOP" if current_stop > initial_stop else "INITIAL_STOP"
            return economic_result(
                fill=fill,
                exit_price=current_stop,
                exit_at=now,
                resolution=reason,
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
                extra={
                    "initial_stop": initial_stop,
                    "final_stop": current_stop,
                    "accepted_levels": accepted_levels,
                    "rejected_levels": rejected_levels,
                    "no_acceptance_levels": no_acceptance_levels,
                    "trail_changes": trail_changes,
                },
            )
        if active_level is not None and touched_at is None:
            if float(bar["high"]) >= float(active_level["level"]):
                touched_at = bar["close_at"]
                response_count = 0
                consecutive_above = 0

    last = bars[-1]
    return economic_result(
        fill=fill,
        exit_price=float(last["close"]),
        exit_at=last["close_at"],
        resolution="TIME_EXIT",
        quantity=quantity,
        cost_per_ounce=cost_per_ounce,
        planned_risk_usd=planned_risk_usd,
        extra={
            "initial_stop": initial_stop,
            "final_stop": current_stop,
            "accepted_levels": accepted_levels,
            "rejected_levels": rejected_levels,
            "no_acceptance_levels": no_acceptance_levels,
            "trail_changes": trail_changes,
        },
    )


def summarize(cases: list[dict], key: str) -> dict:
    tracks = [row[key] for row in cases if row[key]["executable"]]
    positives = [row for row in tracks if row["net_r50"] > 0]
    negatives = [row for row in tracks if row["net_r50"] < 0]
    gains = sum(row["net_r50"] for row in positives)
    losses = -sum(row["net_r50"] for row in negatives)
    ordered = [row[key]["net_r50"] for row in sorted(cases, key=lambda row: row["decision_at"]) if row[key]["executable"]]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in ordered:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "population": len(cases),
        "executable": len(tracks),
        "positive": len(positives),
        "win_rate": len(positives) / len(tracks) if tracks else None,
        "net_r50": sum(row["net_r50"] for row in tracks),
        "net_usd": sum(row["net_usd"] for row in tracks),
        "expectancy_r50": (
            sum(row["net_r50"] for row in tracks) / len(tracks) if tracks else None
        ),
        "profit_factor": gains / losses if losses else None,
        "maximum_drawdown_r50": max_drawdown,
        "resolution_counts": {
            name: sum(row["resolution"] == name for row in tracks)
            for name in sorted({row["resolution"] for row in tracks})
        },
    }


def analyze() -> dict:
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    cases: list[dict] = []
    for record in comparison["cases"]:
        case = record["human"]
        if not case["is_trade"]:
            continue
        stream, source = load_stream(record["case_alias"])
        decision_at = case["submitted_at"]
        fill_at = case["fill_at"]
        intended_entry = float(case["entry"])
        fill = float(case["fill_price"])
        original_target = float(case["target"])
        m15_atr = latest_atr(stream["timeframes"]["15m"], decision_at)
        active_break = active_bullish_break(
            stream["timeframes"]["15m"], decision_at, "15m"
        )
        reason: str | None = None
        if active_break is None:
            reason = "NO_ACTIVE_BULLISH_M15_BREAK"
            stop = None
        else:
            stop = float(active_break["stop"])
            if stop >= intended_entry:
                reason = "PROTECTED_LOW_NOT_BELOW_INTENDED_ENTRY"
            elif stop >= fill:
                reason = "PROTECTED_LOW_NOT_BELOW_ACTUAL_FILL"
        levels = level_registry(
            stream,
            decision_at=decision_at,
            fill=fill,
            original_target=original_target,
            decision_m15_atr=m15_atr,
        )
        if reason is None and not levels:
            reason = "NO_FROZEN_LEVEL_ABOVE_FILL"
        if reason is None and original_target <= fill:
            reason = "ORIGINAL_H1_TARGET_NOT_ABOVE_FILL"

        if reason is not None or stop is None:
            h1 = invalid_track(reason or "UNKNOWN_GEOMETRY_FAILURE")
            first = invalid_track(reason or "UNKNOWN_GEOMETRY_FAILURE")
            runner = invalid_track(reason or "UNKNOWN_GEOMETRY_FAILURE")
            oracle = invalid_track(reason or "UNKNOWN_GEOMETRY_FAILURE")
            quantity = 0
            planned_risk_usd = 0.0
            reward_risk = None
        else:
            risk = fill - stop
            quantity = math.floor(RISK_BUDGET_USD / risk)
            if quantity < 1:
                reason = "MINIMUM_ONE_OUNCE_EXCEEDS_RISK_CAP"
                h1 = invalid_track(reason)
                first = invalid_track(reason)
                runner = invalid_track(reason)
                oracle = invalid_track(reason)
                planned_risk_usd = 0.0
                reward_risk = None
            else:
                planned_risk_usd = quantity * risk
                reward_risk = (original_target - fill) / risk
                cost_per_ounce = float(case["estimated_base_cost_usd"]) / float(
                    case["quantity_ounces"]
                )
                h1 = simulate_fixed(
                    stream=stream,
                    fill_at=fill_at,
                    fill=fill,
                    stop=stop,
                    target=original_target,
                    quantity=quantity,
                    cost_per_ounce=cost_per_ounce,
                    planned_risk_usd=planned_risk_usd,
                    label="H1_CONTROL",
                )
                first = simulate_fixed(
                    stream=stream,
                    fill_at=fill_at,
                    fill=fill,
                    stop=stop,
                    target=float(levels[0]["level"]),
                    quantity=quantity,
                    cost_per_ounce=cost_per_ounce,
                    planned_risk_usd=planned_risk_usd,
                    label="FIRST_LEVEL",
                )
                runner = simulate_runner(
                    stream=stream,
                    fill_at=fill_at,
                    fill=fill,
                    initial_stop=stop,
                    levels=levels,
                    decision_m15_atr=m15_atr,
                    quantity=quantity,
                    cost_per_ounce=cost_per_ounce,
                    planned_risk_usd=planned_risk_usd,
                )
                oracle = stop_feasible_oracle(
                    stream=stream,
                    fill_at=fill_at,
                    fill=fill,
                    stop=stop,
                    quantity=quantity,
                    cost_per_ounce=cost_per_ounce,
                    planned_risk_usd=planned_risk_usd,
                )

        cases.append(
            {
                "case_alias": record["case_alias"],
                "decision_at": decision_at,
                "source": source,
                "original_recorded_r50": float(case["r50"]),
                "original_resolution": case["resolution_state"],
                "terminal_direction_correct": bool(
                    case["path_diagnostic"]["terminal_direction_correct"]
                ),
                "intended_entry": intended_entry,
                "actual_fill": fill,
                "original_h1_target": original_target,
                "decision_m15_atr": m15_atr,
                "structural_eligibility": reason is None,
                "structural_failure": reason,
                "active_m15_break": active_break,
                "reconstructed_stop": stop,
                "quantity_ounces": quantity,
                "planned_risk_usd": planned_risk_usd,
                "planned_h1_reward_risk": reward_risk,
                "level_registry": levels,
                "h1_fixed_control": h1,
                "first_level_fixed_exit": first,
                "full_structural_runner": runner,
                "stop_feasible_mfe_oracle": oracle,
            }
        )

    eligible = [row for row in cases if row["structural_eligibility"]]
    for row in eligible:
        oracle_r = float(row["stop_feasible_mfe_oracle"]["net_r50"])
        for key in (
            "h1_fixed_control",
            "first_level_fixed_exit",
            "full_structural_runner",
        ):
            row[key]["oracle_capture_efficiency"] = (
                float(row[key]["net_r50"]) / oracle_r if oracle_r > 0 else None
            )
    runner_improved = [
        row["case_alias"]
        for row in eligible
        if row["full_structural_runner"]["net_r50"]
        > row["h1_fixed_control"]["net_r50"]
    ]
    runner_degraded = [
        row["case_alias"]
        for row in eligible
        if row["full_structural_runner"]["net_r50"]
        < row["h1_fixed_control"]["net_r50"]
    ]
    payload = {
        "version": "GOLD_MATCHED_HUMAN_COHERENT_AUCTION_MANAGEMENT_V1_0",
        "evidence_status": "POST_RESULT_ZERO_CREDIT_CALIBRATION",
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "population": len(cases),
        "structurally_eligible": len(eligible),
        "structural_failure_counts": {
            name: sum(row["structural_failure"] == name for row in cases)
            for name in sorted(
                {
                    row["structural_failure"]
                    for row in cases
                    if row["structural_failure"] is not None
                }
            )
        },
        "summaries": {
            "h1_fixed_control": summarize(cases, "h1_fixed_control"),
            "first_level_fixed_exit": summarize(cases, "first_level_fixed_exit"),
            "full_structural_runner": summarize(cases, "full_structural_runner"),
            "stop_feasible_mfe_oracle": summarize(cases, "stop_feasible_mfe_oracle"),
        },
        "management_attribution": {
            "runner_improved_vs_h1_control": runner_improved,
            "runner_degraded_vs_h1_control": runner_degraded,
            "runner_equal_vs_h1_control": [
                row["case_alias"]
                for row in eligible
                if row["full_structural_runner"]["net_r50"]
                == row["h1_fixed_control"]["net_r50"]
            ],
        },
        "cases": cases,
        "calendar_2025": "UNTOUCHED",
        "calendar_2026": "UNTOUCHED",
    }
    return round_floats(payload)


def write_case_table(payload: dict) -> None:
    fields = [
        "case_alias",
        "terminal_direction_correct",
        "structural_eligibility",
        "structural_failure",
        "actual_fill",
        "reconstructed_stop",
        "first_level",
        "planned_h1_reward_risk",
        "original_recorded_r50",
        "h1_control_resolution",
        "h1_control_r50",
        "first_level_resolution",
        "first_level_r50",
        "runner_resolution",
        "runner_r50",
        "runner_accepted_levels",
        "runner_rejected_levels",
        "runner_trail_changes",
        "oracle_r50",
        "runner_oracle_capture_efficiency",
    ]
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in payload["cases"]:
            runner = row["full_structural_runner"]
            writer.writerow(
                {
                    "case_alias": row["case_alias"],
                    "terminal_direction_correct": row["terminal_direction_correct"],
                    "structural_eligibility": row["structural_eligibility"],
                    "structural_failure": row["structural_failure"],
                    "actual_fill": row["actual_fill"],
                    "reconstructed_stop": row["reconstructed_stop"],
                    "first_level": (
                        row["level_registry"][0]["level"]
                        if row["level_registry"]
                        else None
                    ),
                    "planned_h1_reward_risk": row["planned_h1_reward_risk"],
                    "original_recorded_r50": row["original_recorded_r50"],
                    "h1_control_resolution": row["h1_fixed_control"]["resolution"],
                    "h1_control_r50": row["h1_fixed_control"]["net_r50"],
                    "first_level_resolution": row["first_level_fixed_exit"]["resolution"],
                    "first_level_r50": row["first_level_fixed_exit"]["net_r50"],
                    "runner_resolution": runner["resolution"],
                    "runner_r50": runner["net_r50"],
                    "runner_accepted_levels": len(runner.get("accepted_levels", [])),
                    "runner_rejected_levels": len(runner.get("rejected_levels", [])),
                    "runner_trail_changes": len(runner.get("trail_changes", [])),
                    "oracle_r50": row["stop_feasible_mfe_oracle"]["net_r50"],
                    "runner_oracle_capture_efficiency": runner.get(
                        "oracle_capture_efficiency"
                    ),
                }
            )


def main() -> None:
    primary = analyze()
    reference = analyze()
    primary_hash = canonical_hash(primary)
    reference_hash = canonical_hash(reference)
    if primary_hash != reference_hash:
        raise RuntimeError("Independent calibration reproductions disagree")
    primary["independent_reproduction"] = {
        "status": "PASS_EXACT_REPRODUCTION",
        "primary_payload_sha256": primary_hash,
        "reference_payload_sha256": reference_hash,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(
        json.dumps(primary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_case_table(primary)
    print(json.dumps(primary["summaries"], indent=2, sort_keys=True))
    print(json.dumps(primary["structural_failure_counts"], indent=2, sort_keys=True))
    print(json.dumps(primary["management_attribution"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
