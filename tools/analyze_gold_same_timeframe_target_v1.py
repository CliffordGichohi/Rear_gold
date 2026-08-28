"""Post-result same-timeframe target diagnostic for matched human trades."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMPARISON = (
    ROOT
    / "research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json"
)
STREAM_ROOTS = [
    ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams/primary",
    ROOT
    / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams_recovery_a/primary",
]
OUTPUT = ROOT / "research_artifacts/gold_same_timeframe_target_v1"
RESULT = OUTPUT / "same_timeframe_target_diagnostic.json"
TABLE = OUTPUT / "same_timeframe_target_cases.csv"


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_stream(alias: str) -> tuple[dict, str]:
    for root in STREAM_ROOTS:
        path = root / f"{alias}.json.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return json.load(handle), str(path.relative_to(ROOT)).replace("\\", "/")
    raise FileNotFoundError(alias)


def confirmed_highs(rows: list[dict], cutoff: str, width: int = 2) -> list[dict]:
    eligible = [
        row
        for row in rows
        if row.get("complete") is True and row["available_at"] <= cutoff
    ]
    output: list[dict] = []
    for index in range(width, len(eligible) - width):
        window = eligible[index - width : index + width + 1]
        high = float(eligible[index]["high"])
        if high != max(float(row["high"]) for row in window):
            continue
        if sum(float(row["high"]) == high for row in window) != 1:
            continue
        output.append(
            {
                "level": high,
                "swing_bar_open_at": eligible[index]["open_at"],
                "swing_bar_available_at": eligible[index]["available_at"],
                "confirmed_at": eligible[index + width]["available_at"],
                "timeframe": eligible[index]["timeframe"],
            }
        )
    return output


def nearest_target(
    stream: dict, timeframe: str, decision_at: str, intended_entry: float
) -> dict | None:
    candidates = [
        row
        for row in confirmed_highs(stream["timeframes"][timeframe], decision_at)
        if float(row["level"]) > intended_entry
    ]
    if not candidates:
        return None
    # Nearest in price; use the most recently formed reference only as a tie-break.
    candidates.sort(key=lambda row: (float(row["level"]), row["confirmed_at"]), reverse=False)
    nearest_level = float(candidates[0]["level"])
    tied = [row for row in candidates if float(row["level"]) == nearest_level]
    return sorted(tied, key=lambda row: row["confirmed_at"], reverse=True)[0]


def evaluate_target(case: dict, stream: dict, target: float | None) -> dict:
    fill = float(case["fill_price"])
    stop = float(case["stop"])
    risk = fill - stop
    if risk <= 0:
        raise RuntimeError(f"Invalid original risk for {case['case_alias']}")
    quantity = math.floor(50.0 / risk)
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
    if target is None:
        return {
            "target": None,
            "target_r": None,
            "outcome": "NO_POINT_IN_TIME_TARGET",
            "target_first": False,
            "positive": False,
            "quantity_ounces": quantity,
            "net_usd": 0.0,
            "net_r50": 0.0,
        }
    target = float(target)
    if target <= fill:
        cost = cost_per_ounce * quantity
        return {
            "target": target,
            "target_r": (target - fill) / risk,
            "outcome": "POST_FILL_TARGET_GEOMETRY_INVALID",
            "target_first": False,
            "positive": False,
            "quantity_ounces": quantity,
            "net_usd": -cost,
            "net_r50": -cost / 50.0,
        }

    stop_index = None
    target_index = None
    for index, bar in enumerate(bars):
        if stop_index is None and float(bar["low"]) <= stop:
            stop_index = index
        if target_index is None and float(bar["high"]) >= target:
            target_index = index
        if stop_index is not None or target_index is not None:
            # Stop-first applies if both are touched in the first resolving bar.
            if stop_index is not None and (
                target_index is None or stop_index <= target_index
            ):
                outcome = "STOP_FIRST"
                gross_per_ounce = -risk
                exit_at = bars[stop_index]["open_at"]
            else:
                outcome = "TARGET_FIRST"
                gross_per_ounce = target - fill
                exit_at = bars[target_index]["open_at"]
            break
    else:
        outcome = "TIME_EXIT"
        gross_per_ounce = float(bars[-1]["close"]) - fill
        exit_at = bars[-1]["open_at"]

    net_usd = gross_per_ounce * quantity - cost_per_ounce * quantity
    return {
        "target": target,
        "target_r": (target - fill) / risk,
        "outcome": outcome,
        "exit_at": exit_at,
        "target_first": outcome == "TARGET_FIRST",
        "positive": net_usd > 0,
        "quantity_ounces": quantity,
        "planned_actual_fill_risk_usd": quantity * risk,
        "cost_per_ounce": cost_per_ounce,
        "net_usd": net_usd,
        "net_r50": net_usd / 50.0,
    }


def summarize(rows: list[dict], key: str) -> dict:
    payloads = [row[key] for row in rows]
    valid_targets = [
        row
        for row in payloads
        if row["outcome"]
        not in {"NO_POINT_IN_TIME_TARGET", "POST_FILL_TARGET_GEOMETRY_INVALID"}
    ]
    economic = [row for row in payloads if row["outcome"] != "NO_POINT_IN_TIME_TARGET"]
    positive = [row for row in economic if row["net_r50"] > 0]
    negative = [row for row in economic if row["net_r50"] < 0]
    gross_profit = sum(row["net_r50"] for row in positive)
    gross_loss = -sum(row["net_r50"] for row in negative)
    return {
        "population": len(rows),
        "point_in_time_targets": sum(
            row["outcome"] != "NO_POINT_IN_TIME_TARGET" for row in payloads
        ),
        "post_fill_target_geometry_invalid": sum(
            row["outcome"] == "POST_FILL_TARGET_GEOMETRY_INVALID"
            for row in payloads
        ),
        "valid_target_geometry": len(valid_targets),
        "target_first": sum(row["target_first"] for row in payloads),
        "target_first_rate_all_cases": sum(row["target_first"] for row in payloads)
        / len(rows),
        "target_first_rate_valid_geometry": (
            sum(row["target_first"] for row in valid_targets) / len(valid_targets)
            if valid_targets
            else None
        ),
        "positive_results": len(positive),
        "positive_rate_all_cases": len(positive) / len(rows),
        "net_r50": sum(row["net_r50"] for row in economic),
        "expectancy_r50_all_cases": sum(row["net_r50"] for row in economic)
        / len(rows),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "median_target_r": sorted(
            row["target_r"] for row in valid_targets if row["target_r"] is not None
        )[len(valid_targets) // 2]
        if valid_targets
        else None,
        "outcome_counts": {
            outcome: sum(row["outcome"] == outcome for row in payloads)
            for outcome in sorted({row["outcome"] for row in payloads})
        },
    }


def round_floats(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, list):
        return [round_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: round_floats(item) for key, item in value.items()}
    return value


def main() -> None:
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for record in comparison["cases"]:
        case = record["human"]
        if not case["is_trade"]:
            continue
        stream, source = load_stream(record["case_alias"])
        intended_entry = float(case["entry"])
        m15_reference = nearest_target(
            stream, "15m", case["submitted_at"], intended_entry
        )
        trigger_text = str(case["annotation"]["m15_transition"])
        trigger_timeframe = "5m" if "m5" in trigger_text.casefold() else "15m"
        trigger_reference = nearest_target(
            stream, trigger_timeframe, case["submitted_at"], intended_entry
        )
        original = evaluate_target(case, stream, float(case["target"]))
        m15 = evaluate_target(
            case,
            stream,
            float(m15_reference["level"]) if m15_reference else None,
        )
        trigger = evaluate_target(
            case,
            stream,
            float(trigger_reference["level"]) if trigger_reference else None,
        )
        rows.append(
            {
                "case_alias": record["case_alias"],
                "trading_date_utc": record["trading_date_utc"],
                "decision_at": case["submitted_at"],
                "recorded_trigger_timeframe": trigger_timeframe,
                "original_resolution": case["resolution_state"],
                "original_recorded_r50": float(case["r50"]),
                "terminal_direction_correct": case["path_diagnostic"][
                    "terminal_direction_correct"
                ],
                "known_stale_size_geometry_failure": bool(
                    case["post_fill_geometry_invalid"]
                ),
                "source": source,
                "original_control": original,
                "m15_reference": m15_reference,
                "m15_same_timeframe": m15,
                "trigger_reference": trigger_reference,
                "recorded_trigger_timeframe_target": trigger,
            }
        )

    result = round_floats(
        {
            "version": "GOLD_MATCHED_HUMAN_SAME_TIMEFRAME_TARGET_DIAGNOSTIC_V1_0",
            "evidence_status": "POST_RESULT_ZERO_CREDIT_DESCRIPTIVE",
            "population": len(rows),
            "recorded_target_timeframe": "1h_FOR_ALL_16",
            "primary_entry_and_invalidation_timeframe": "15m_FOR_ALL_16",
            "summaries": {
                "original_h1_target_control_with_actual_fill_resizing": summarize(
                    rows, "original_control"
                ),
                "m15_nearest_confirmed_swing_high": summarize(
                    rows, "m15_same_timeframe"
                ),
                "recorded_trigger_timeframe_nearest_confirmed_swing_high": summarize(
                    rows, "recorded_trigger_timeframe_target"
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
        "trading_date_utc",
        "terminal_direction_correct",
        "known_stale_size_geometry_failure",
        "recorded_trigger_timeframe",
        "original_recorded_r50",
        "original_target_r",
        "original_outcome",
        "original_net_r50",
        "m15_target",
        "m15_target_r",
        "m15_outcome",
        "m15_net_r50",
        "trigger_target",
        "trigger_target_r",
        "trigger_outcome",
        "trigger_net_r50",
    ]
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in result["cases"]:
            writer.writerow(
                {
                    "case_alias": row["case_alias"],
                    "trading_date_utc": row["trading_date_utc"],
                    "terminal_direction_correct": row["terminal_direction_correct"],
                    "known_stale_size_geometry_failure": row[
                        "known_stale_size_geometry_failure"
                    ],
                    "recorded_trigger_timeframe": row["recorded_trigger_timeframe"],
                    "original_recorded_r50": row["original_recorded_r50"],
                    "original_target_r": row["original_control"]["target_r"],
                    "original_outcome": row["original_control"]["outcome"],
                    "original_net_r50": row["original_control"]["net_r50"],
                    "m15_target": row["m15_same_timeframe"]["target"],
                    "m15_target_r": row["m15_same_timeframe"]["target_r"],
                    "m15_outcome": row["m15_same_timeframe"]["outcome"],
                    "m15_net_r50": row["m15_same_timeframe"]["net_r50"],
                    "trigger_target": row["recorded_trigger_timeframe_target"][
                        "target"
                    ],
                    "trigger_target_r": row["recorded_trigger_timeframe_target"][
                        "target_r"
                    ],
                    "trigger_outcome": row["recorded_trigger_timeframe_target"][
                        "outcome"
                    ],
                    "trigger_net_r50": row["recorded_trigger_timeframe_target"][
                        "net_r50"
                    ],
                }
            )
    print(json.dumps(result["summaries"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
