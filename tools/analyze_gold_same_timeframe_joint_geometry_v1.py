"""Joint lower-timeframe stop/target diagnostic for matched human trades."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from analyze_gold_same_timeframe_target_v1 import (
    COMPARISON,
    ROOT,
    canonical_hash,
    load_stream,
    nearest_target,
    round_floats,
)


OUTPUT = ROOT / "research_artifacts/gold_same_timeframe_joint_geometry_v1"
RESULT = OUTPUT / "joint_geometry_diagnostic.json"
TABLE = OUTPUT / "joint_geometry_cases.csv"


def confirmed_lows(rows: list[dict], cutoff: str, width: int = 2) -> list[dict]:
    eligible = [
        row
        for row in rows
        if row.get("complete") is True and row["available_at"] <= cutoff
    ]
    output: list[dict] = []
    for index in range(width, len(eligible) - width):
        window = eligible[index - width : index + width + 1]
        low = float(eligible[index]["low"])
        if low != min(float(row["low"]) for row in window):
            continue
        if sum(float(row["low"]) == low for row in window) != 1:
            continue
        output.append(
            {
                "level": low,
                "swing_bar_open_at": eligible[index]["open_at"],
                "swing_bar_available_at": eligible[index]["available_at"],
                "confirmed_at": eligible[index + width]["available_at"],
                "timeframe": eligible[index]["timeframe"],
            }
        )
    return output


def latest_stop(stream: dict, timeframe: str, decision_at: str) -> dict | None:
    candidates = confirmed_lows(stream["timeframes"][timeframe], decision_at)
    return candidates[-1] if candidates else None


def invalid_result(outcome: str, stop: float | None, target: float | None) -> dict:
    return {
        "stop": stop,
        "target": target,
        "risk_price": None,
        "reward_price": None,
        "reward_risk": None,
        "outcome": outcome,
        "executable": False,
        "target_first": False,
        "positive": False,
        "quantity_ounces": 0,
        "net_usd": 0.0,
        "net_r50": 0.0,
    }


def evaluate_joint(
    case: dict,
    stream: dict,
    stop_reference: dict | None,
    target_reference: dict | None,
) -> dict:
    intended_entry = float(case["entry"])
    fill = float(case["fill_price"])
    stop = float(stop_reference["level"]) if stop_reference else None
    target = float(target_reference["level"]) if target_reference else None
    if stop is None or target is None:
        return invalid_result("NO_POINT_IN_TIME_GEOMETRY", stop, target)
    if stop >= intended_entry:
        return invalid_result("PREENTRY_STRUCTURE_ALREADY_BROKEN", stop, target)
    if stop >= fill:
        return invalid_result("POST_FILL_STOP_GEOMETRY_INVALID", stop, target)
    if target <= fill:
        return invalid_result("POST_FILL_TARGET_GEOMETRY_INVALID", stop, target)

    risk = fill - stop
    reward = target - fill
    quantity = math.floor(50.0 / risk)
    if quantity < 1:
        return invalid_result("MINIMUM_ONE_OUNCE_EXCEEDS_RISK_CAP", stop, target)
    cost_per_ounce = float(case["estimated_base_cost_usd"]) / float(
        case["quantity_ounces"]
    )
    bars = [
        row
        for row in stream["timeframes"]["1m"]
        if row["open_at"] >= case["fill_at"]
    ]
    if not bars:
        raise RuntimeError(f"Missing post-fill bars for {case['case_alias']}")

    outcome = "TIME_EXIT"
    exit_at = bars[-1]["open_at"]
    gross_per_ounce = float(bars[-1]["close"]) - fill
    for bar in bars:
        stop_hit = float(bar["low"]) <= stop
        target_hit = float(bar["high"]) >= target
        if stop_hit:
            outcome = "STOP_FIRST"
            exit_at = bar["open_at"]
            gross_per_ounce = -risk
            break
        if target_hit:
            outcome = "TARGET_FIRST"
            exit_at = bar["open_at"]
            gross_per_ounce = reward
            break

    net_usd = gross_per_ounce * quantity - cost_per_ounce * quantity
    return {
        "stop": stop,
        "target": target,
        "risk_price": risk,
        "reward_price": reward,
        "reward_risk": reward / risk,
        "outcome": outcome,
        "exit_at": exit_at,
        "executable": True,
        "target_first": outcome == "TARGET_FIRST",
        "positive": net_usd > 0,
        "quantity_ounces": quantity,
        "planned_actual_fill_risk_usd": quantity * risk,
        "cost_per_ounce": cost_per_ounce,
        "net_usd": net_usd,
        "net_r50": net_usd / 50.0,
    }


def rr_bin(value: float) -> str:
    if value < 0.5:
        return "LT_0P5"
    if value < 1.0:
        return "0P5_TO_LT_1"
    if value < 2.0:
        return "1_TO_LT_2"
    return "GTE_2"


def summarize(rows: list[dict], key: str) -> dict:
    payloads = [row[key] for row in rows]
    executable = [row for row in payloads if row["executable"]]
    positives = [row for row in executable if row["net_r50"] > 0]
    negatives = [row for row in executable if row["net_r50"] < 0]
    gross_profit = sum(row["net_r50"] for row in positives)
    gross_loss = -sum(row["net_r50"] for row in negatives)
    bins: dict[str, dict[str, Any]] = {}
    for name in ("LT_0P5", "0P5_TO_LT_1", "1_TO_LT_2", "GTE_2"):
        members = [row for row in executable if rr_bin(row["reward_risk"]) == name]
        bins[name] = {
            "support": len(members),
            "target_first": sum(row["target_first"] for row in members),
            "positive": sum(row["positive"] for row in members),
            "net_r50": sum(row["net_r50"] for row in members),
        }
    return {
        "population": len(rows),
        "executable": len(executable),
        "technical_or_structure_no_trade": len(rows) - len(executable),
        "outcome_counts": {
            outcome: sum(row["outcome"] == outcome for row in payloads)
            for outcome in sorted({row["outcome"] for row in payloads})
        },
        "target_first": sum(row["target_first"] for row in executable),
        "stop_first": sum(row["outcome"] == "STOP_FIRST" for row in executable),
        "time_exit": sum(row["outcome"] == "TIME_EXIT" for row in executable),
        "positive": len(positives),
        "win_rate_executable": len(positives) / len(executable) if executable else None,
        "net_r50": sum(row["net_r50"] for row in executable),
        "expectancy_r50_executable": (
            sum(row["net_r50"] for row in executable) / len(executable)
            if executable
            else None
        ),
        "expectancy_r50_all_original_cases": sum(
            row["net_r50"] for row in executable
        )
        / len(rows),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "median_reward_risk": (
            sorted(row["reward_risk"] for row in executable)[len(executable) // 2]
            if executable
            else None
        ),
        "reward_risk_bins": bins,
    }


def main() -> None:
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for record in comparison["cases"]:
        case = record["human"]
        if not case["is_trade"]:
            continue
        stream, source = load_stream(record["case_alias"])
        trigger_text = str(case["annotation"]["m15_transition"])
        trigger_timeframe = "5m" if "m5" in trigger_text.casefold() else "15m"
        m15_stop = latest_stop(stream, "15m", case["submitted_at"])
        m15_target = nearest_target(
            stream, "15m", case["submitted_at"], float(case["entry"])
        )
        trigger_stop = latest_stop(stream, trigger_timeframe, case["submitted_at"])
        trigger_target = nearest_target(
            stream, trigger_timeframe, case["submitted_at"], float(case["entry"])
        )
        if float(case["r50"]) > 0:
            bucket = "ORIGINAL_PROFITABLE"
        elif case["path_diagnostic"]["terminal_direction_correct"]:
            bucket = "DIRECTION_RIGHT_NOT_MONETIZED"
        else:
            bucket = "DIRECTION_WRONG_BY_CLOSE"
        rows.append(
            {
                "case_alias": record["case_alias"],
                "trading_date_utc": record["trading_date_utc"],
                "bucket": bucket,
                "decision_at": case["submitted_at"],
                "recorded_trigger_timeframe": trigger_timeframe,
                "original_stop": float(case["stop"]),
                "original_target": float(case["target"]),
                "original_recorded_r50": float(case["r50"]),
                "original_resolution": case["resolution_state"],
                "source": source,
                "m15_stop_reference": m15_stop,
                "m15_target_reference": m15_target,
                "m15_joint_geometry": evaluate_joint(
                    case, stream, m15_stop, m15_target
                ),
                "trigger_stop_reference": trigger_stop,
                "trigger_target_reference": trigger_target,
                "trigger_tf_joint_geometry": evaluate_joint(
                    case, stream, trigger_stop, trigger_target
                ),
            }
        )

    result = round_floats(
        {
            "version": "GOLD_MATCHED_HUMAN_SAME_TIMEFRAME_JOINT_GEOMETRY_V1_0",
            "evidence_status": "POST_RESULT_ZERO_CREDIT_DESCRIPTIVE",
            "predecessor_target_only_status": "INCOMPLETE_FOR_JOINT_R_GEOMETRY",
            "population": len(rows),
            "summaries": {
                "m15_joint_stop_target": summarize(rows, "m15_joint_geometry"),
                "recorded_trigger_timeframe_joint_stop_target": summarize(
                    rows, "trigger_tf_joint_geometry"
                ),
            },
            "cases": rows,
            "calendar_2025": "UNTOUCHED",
            "calendar_2026": "UNTOUCHED",
        }
    )
    result["cases_sha256"] = canonical_hash(result["cases"])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    fields = [
        "case_alias",
        "bucket",
        "recorded_trigger_timeframe",
        "original_recorded_r50",
        "m15_stop",
        "m15_target",
        "m15_reward_risk",
        "m15_outcome",
        "m15_net_r50",
        "trigger_stop",
        "trigger_target",
        "trigger_reward_risk",
        "trigger_outcome",
        "trigger_net_r50",
    ]
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in result["cases"]:
            m15 = row["m15_joint_geometry"]
            trigger = row["trigger_tf_joint_geometry"]
            writer.writerow(
                {
                    "case_alias": row["case_alias"],
                    "bucket": row["bucket"],
                    "recorded_trigger_timeframe": row["recorded_trigger_timeframe"],
                    "original_recorded_r50": row["original_recorded_r50"],
                    "m15_stop": m15["stop"],
                    "m15_target": m15["target"],
                    "m15_reward_risk": m15["reward_risk"],
                    "m15_outcome": m15["outcome"],
                    "m15_net_r50": m15["net_r50"],
                    "trigger_stop": trigger["stop"],
                    "trigger_target": trigger["target"],
                    "trigger_reward_risk": trigger["reward_risk"],
                    "trigger_outcome": trigger["outcome"],
                    "trigger_net_r50": trigger["net_r50"],
                }
            )
    print(json.dumps(result["summaries"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
