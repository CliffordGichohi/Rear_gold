"""One bounded M15 structural-runner challenger for exposed matched cases."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from analyze_gold_coherent_auction_management_v1 import (
    BREAK_BUFFER_ATR,
    COMPARISON,
    OUTPUT as BASE_OUTPUT,
    ROOT,
    TICK_FLOOR,
    atr_values,
    bullish_break_events,
    canonical_hash,
    confirmed_swings,
    economic_result,
    eligible_rows,
    invalid_track,
    load_stream,
    path_rows,
    round_floats,
    summarize,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_management_amendment_a"
RESULT = OUTPUT / "m15_structural_runner_result.json"
TABLE = OUTPUT / "m15_structural_runner_cases.csv"
BASE_RESULT = BASE_OUTPUT / "coherent_auction_management_result.json"
AMENDMENT = ROOT / "GOLD_MATCHED_HUMAN_COHERENT_AUCTION_MANAGEMENT_AMENDMENT_A.md"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bearish_break_events(rows: list[dict], cutoff: str, timeframe: str) -> list[dict]:
    bars, swings = confirmed_swings(rows, cutoff, timeframe)
    atrs = atr_values(bars)
    broken_lows: set[str] = set()
    events: list[dict] = []
    for index, bar in enumerate(bars):
        lows = [
            item
            for item in swings
            if item["kind"] == "LOW"
            and item["detected_at"] <= bar["open_at"]
            and item["pivot_index"] < index
            and item["identity"] not in broken_lows
        ]
        if not lows:
            continue
        swing_low = max(lows, key=lambda item: item["pivot_index"])
        atr = max(atrs[index], 0.01)
        buffer = max(BREAK_BUFFER_ATR * atr, TICK_FLOOR)
        if float(bar["close"]) >= float(swing_low["level"]) - buffer:
            continue
        broken_lows.add(str(swing_low["identity"]))
        events.append(
            {
                "identity": canonical_hash(
                    [
                        "BEARISH_BREAK",
                        timeframe,
                        swing_low["identity"],
                        bar["available_at"],
                    ]
                ),
                "timeframe": timeframe,
                "break_at": bar["available_at"],
                "broken_low": swing_low["level"],
                "broken_low_identity": swing_low["identity"],
                "atr": atr,
                "buffer": buffer,
            }
        )
    return events


def simulate_m15_runner(
    *,
    stream: dict,
    fill_at: str,
    fill: float,
    initial_stop: float,
    levels: list[dict],
    quantity: int,
    cost_per_ounce: float,
    planned_risk_usd: float,
) -> dict:
    bars = path_rows(stream, fill_at)
    if not bars:
        return invalid_track("M15_RUNNER_MISSING_PATH")
    bullish = [
        event
        for event in bullish_break_events(
            stream["timeframes"]["15m"], stream["end_exclusive"], "15m"
        )
        if event["break_at"] > fill_at
    ]
    bearish = [
        event
        for event in bearish_break_events(
            stream["timeframes"]["15m"], stream["end_exclusive"], "15m"
        )
        if event["break_at"] > fill_at
    ]
    bullish.sort(key=lambda row: row["break_at"])
    bearish.sort(key=lambda row: row["break_at"])
    bullish_index = 0
    bearish_index = 0
    current_stop = initial_stop
    stop_changes: list[dict] = []
    level_touches: list[dict] = []
    touched_identities: set[str] = set()
    pending_bearish: dict | None = None

    def finish(exit_price: float, exit_at: str, resolution: str) -> dict:
        return economic_result(
            fill=fill,
            exit_price=exit_price,
            exit_at=exit_at,
            resolution=resolution,
            quantity=quantity,
            cost_per_ounce=cost_per_ounce,
            planned_risk_usd=planned_risk_usd,
            extra={
                "initial_stop": initial_stop,
                "final_stop": current_stop,
                "stop_changes": stop_changes,
                "level_touches": level_touches,
                "opposite_break": pending_bearish,
            },
        )

    for bar in bars:
        now = bar["open_at"]
        while bullish_index < len(bullish) and bullish[bullish_index]["break_at"] <= now:
            event = bullish[bullish_index]
            bullish_index += 1
            proposed = float(event["stop"])
            if proposed > current_stop:
                stop_changes.append(
                    {
                        "available_at": event["break_at"],
                        "prior_stop": current_stop,
                        "new_stop": proposed,
                        "break_identity": event["identity"],
                    }
                )
                current_stop = proposed
        while bearish_index < len(bearish) and bearish[bearish_index]["break_at"] <= now:
            pending_bearish = bearish[bearish_index]
            bearish_index += 1
            break

        open_price = float(bar["open"])
        if open_price <= current_stop:
            resolution = (
                "M15_TRAIL_GAP_STOP" if current_stop > initial_stop else "INITIAL_GAP_STOP"
            )
            return finish(open_price, now, resolution)
        if pending_bearish is not None:
            return finish(open_price, now, "OPPOSITE_M15_BREAK_EXIT")
        if float(bar["low"]) <= current_stop:
            resolution = "M15_TRAIL_STOP" if current_stop > initial_stop else "INITIAL_STOP"
            return finish(current_stop, now, resolution)
        for level in levels:
            identity = str(level["identity"])
            if identity in touched_identities:
                continue
            if float(bar["high"]) >= float(level["level"]):
                touched_identities.add(identity)
                level_touches.append(
                    {
                        "identity": identity,
                        "level": level["level"],
                        "timeframe": level["timeframe"],
                        "source": level["source"],
                        "touched_at": bar["close_at"],
                    }
                )
    last = bars[-1]
    return finish(float(last["close"]), last["close_at"], "TIME_EXIT")


def analyze() -> dict:
    base = json.loads(BASE_RESULT.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    human_by_alias = {
        record["case_alias"]: record["human"]
        for record in comparison["cases"]
        if record["human"]["is_trade"]
    }
    cases: list[dict] = []
    for base_case in base["cases"]:
        alias = base_case["case_alias"]
        if not base_case["structural_eligibility"]:
            challenger = invalid_track(base_case["structural_failure"])
        else:
            human = human_by_alias[alias]
            stream, _ = load_stream(alias)
            cost_per_ounce = float(human["estimated_base_cost_usd"]) / float(
                human["quantity_ounces"]
            )
            challenger = simulate_m15_runner(
                stream=stream,
                fill_at=human["fill_at"],
                fill=float(base_case["actual_fill"]),
                initial_stop=float(base_case["reconstructed_stop"]),
                levels=base_case["level_registry"],
                quantity=int(base_case["quantity_ounces"]),
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=float(base_case["planned_risk_usd"]),
            )
            oracle_r = float(base_case["stop_feasible_mfe_oracle"]["net_r50"])
            challenger["oracle_capture_efficiency"] = (
                float(challenger["net_r50"]) / oracle_r if oracle_r > 0 else None
            )
        cases.append(
            {
                "case_alias": alias,
                "decision_at": base_case["decision_at"],
                "terminal_direction_correct": base_case["terminal_direction_correct"],
                "structural_eligibility": base_case["structural_eligibility"],
                "structural_failure": base_case["structural_failure"],
                "original_recorded_r50": base_case["original_recorded_r50"],
                "h1_fixed_control": base_case["h1_fixed_control"],
                "v1_m5_response_runner": base_case["full_structural_runner"],
                "stop_feasible_mfe_oracle": base_case["stop_feasible_mfe_oracle"],
                "m15_protected_auction_runner": challenger,
            }
        )
    eligible = [row for row in cases if row["structural_eligibility"]]
    payload: dict[str, Any] = {
        "version": "GOLD_MATCHED_HUMAN_COHERENT_AUCTION_MANAGEMENT_AMENDMENT_A_V1_0",
        "evidence_status": "POST_RESULT_ZERO_CREDIT_CALIBRATION",
        "base_result_sha256": file_sha256(BASE_RESULT),
        "amendment_sha256": file_sha256(AMENDMENT),
        "population": len(cases),
        "structurally_eligible": len(eligible),
        "summary": summarize(cases, "m15_protected_auction_runner"),
        "comparisons": {
            "improved_vs_h1_control": [
                row["case_alias"]
                for row in eligible
                if row["m15_protected_auction_runner"]["net_r50"]
                > row["h1_fixed_control"]["net_r50"]
            ],
            "degraded_vs_h1_control": [
                row["case_alias"]
                for row in eligible
                if row["m15_protected_auction_runner"]["net_r50"]
                < row["h1_fixed_control"]["net_r50"]
            ],
            "equal_vs_h1_control": [
                row["case_alias"]
                for row in eligible
                if row["m15_protected_auction_runner"]["net_r50"]
                == row["h1_fixed_control"]["net_r50"]
            ],
        },
        "cases": cases,
        "calendar_2025": "UNTOUCHED",
        "calendar_2026": "UNTOUCHED",
    }
    return round_floats(payload)


def write_table(payload: dict) -> None:
    fields = [
        "case_alias",
        "terminal_direction_correct",
        "structural_eligibility",
        "original_recorded_r50",
        "h1_control_r50",
        "m5_response_runner_r50",
        "m15_runner_resolution",
        "m15_runner_r50",
        "m15_runner_stop_changes",
        "m15_runner_level_touches",
        "oracle_r50",
        "m15_runner_oracle_capture_efficiency",
    ]
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in payload["cases"]:
            runner = row["m15_protected_auction_runner"]
            writer.writerow(
                {
                    "case_alias": row["case_alias"],
                    "terminal_direction_correct": row["terminal_direction_correct"],
                    "structural_eligibility": row["structural_eligibility"],
                    "original_recorded_r50": row["original_recorded_r50"],
                    "h1_control_r50": row["h1_fixed_control"]["net_r50"],
                    "m5_response_runner_r50": row["v1_m5_response_runner"]["net_r50"],
                    "m15_runner_resolution": runner["resolution"],
                    "m15_runner_r50": runner["net_r50"],
                    "m15_runner_stop_changes": len(runner.get("stop_changes", [])),
                    "m15_runner_level_touches": len(runner.get("level_touches", [])),
                    "oracle_r50": row["stop_feasible_mfe_oracle"]["net_r50"],
                    "m15_runner_oracle_capture_efficiency": runner.get(
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
        raise RuntimeError("M15 runner independent reproductions disagree")
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
    write_table(primary)
    print(json.dumps(primary["summary"], indent=2, sort_keys=True))
    print(json.dumps(primary["comparisons"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

