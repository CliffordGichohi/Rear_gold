from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from calibrate_liquidity_shift_v2_matched_replay import (
    EXPECTED_CASES,
    aggregate_study_inputs,
    canonical_hash,
    iso,
    load_minutes,
    parse_time,
    read_json,
    read_jsonl,
    sha256_file,
    verify_chain,
    write_csv_exclusive,
    write_json_exclusive,
)
from calibrate_persistent_liquidity_shift_v3 import active_session

from gold_intel.analytics.liquidity_shift_v2 import (
    Direction,
    LiquidityShiftV2Config,
    build_liquidity_shift_study_v2,
    latest_swing_range_at,
    trend_state_at,
)
from gold_intel.analytics.liquidity_shift_v4 import (
    LiquidityResponseM5StateStudyV4,
    M5ActivationStateV4,
    build_liquidity_response_m5_state_study_v4,
)
from gold_intel.analytics.structure import AggregateBar


def verify_freeze(root: Path) -> dict[str, Any]:
    path = (
        root
        / "research_manifests"
        / "gold_liquidity_response_v4_failure_attribution_freeze.json"
    )
    freeze = read_json(path)
    if freeze.get("status") != "SEALED_BEFORE_VALUE_BLIND_FAILURE_ATTRIBUTION":
        raise RuntimeError("V4 failure-attribution freeze is invalid")
    for record in freeze["files"].values():
        source = root / record["path"]
        if sha256_file(source) != record["sha256"]:
            raise RuntimeError(f"Frozen attribution input changed: {record['path']}")
    return freeze


def read_v4_semantic_rows(root: Path) -> dict[str, dict[str, str]]:
    path = (
        root
        / "research_artifacts"
        / "gold_liquidity_response_m5_structure_state_edge_v4"
        / "semantic_rows.csv"
    )
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != EXPECTED_CASES:
        raise RuntimeError("V4 semantic population changed")
    return {row["case_alias"]: row for row in rows}


def canonical_bars(values: list[AggregateBar]) -> list[AggregateBar]:
    return sorted(values, key=lambda item: item.open_time)


def higher_timeframe_eligible(
    *,
    direction: Direction,
    timestamp: datetime,
    bars: dict[str, list[AggregateBar]],
    pivots: dict[str, tuple[Any, ...]],
) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    for timeframe in ("1h", "4h"):
        completed = [item for item in bars[timeframe] if item.close_time <= timestamp]
        known = [item for item in pivots[timeframe] if item.detected_at <= timestamp]
        if not completed or not known:
            continue
        trend = trend_state_at(known, timestamp)
        if trend == direction:
            evidence.append(f"{timeframe.upper()}_TREND_ALIGNED")
        swing_range = latest_swing_range_at(known, timestamp)
        if swing_range is None or swing_range[1] <= swing_range[0]:
            continue
        position = (completed[-1].close - swing_range[0]) / (
            swing_range[1] - swing_range[0]
        )
        if direction == "BULLISH" and position <= 0.35:
            evidence.append(f"{timeframe.upper()}_OUTER_DISCOUNT")
        if direction == "BEARISH" and position >= 0.65:
            evidence.append(f"{timeframe.upper()}_OUTER_PREMIUM")
    return bool(evidence), evidence


def natural_terminal(
    activation: M5ActivationStateV4,
    study: LiquidityResponseM5StateStudyV4,
) -> datetime:
    location = next(
        item for item in study.locations if item.identity == activation.location_identity
    )
    return min(activation.started_at + timedelta(hours=4), location.terminal_at)


def first_eligible_overlap(
    *,
    activation: M5ActivationStateV4,
    terminal: datetime,
    session_date: date,
    bars: dict[str, list[AggregateBar]],
    pivots: dict[str, tuple[Any, ...]],
) -> tuple[datetime | None, bool, list[str]]:
    day_start = datetime.combine(session_date, time.min, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    start = max(activation.started_at, day_start)
    end = min(terminal, day_end)
    cursor = start.replace(second=0, microsecond=0)
    if cursor < start:
        cursor += timedelta(minutes=1)
    while cursor < end:
        session, remaining = active_session(cursor)
        if session is not None and remaining >= 30:
            eligible, evidence = higher_timeframe_eligible(
                direction=activation.direction,
                timestamp=cursor,
                bars=bars,
                pivots=pivots,
            )
            return cursor, eligible, evidence
        cursor += timedelta(minutes=1)
    return None, False, []


def build_rows(
    *,
    decisions: list[dict[str, Any]],
    v4_rows: dict[str, dict[str, str]],
    v4: LiquidityResponseM5StateStudyV4,
    bars: dict[str, list[AggregateBar]],
    pivots: dict[str, tuple[Any, ...]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in decisions:
        alias = source["case_alias"]
        decision = source["data"]["decision"]
        action = decision["action"]
        decision_at = parse_time(decision["expected_cursor_at"])
        prior = v4_rows[alias]
        if action in {"LONG", "SHORT"}:
            direction: Direction = "BULLISH" if action == "LONG" else "BEARISH"
            natural = [
                item
                for item in v4.activations
                if item.direction == direction
                and item.started_at <= decision_at < natural_terminal(item, v4)
            ]
            htf, evidence = higher_timeframe_eligible(
                direction=direction,
                timestamp=decision_at,
                bars=bars,
                pivots=pivots,
            )
            actual = prior["semantic_match"] == "True"
            if actual:
                failure = "ACTUAL_V4_MATCH"
            elif natural:
                failure = "OPPOSITE_M5_TERMINATION_ONLY"
            else:
                recent = [
                    item
                    for item in v4.activations
                    if item.direction == direction
                    and timedelta(0)
                    <= decision_at - item.started_at
                    <= timedelta(hours=4)
                ]
                failure = (
                    "SOURCE_LOCATION_TERMINATED"
                    if recent
                    else "NO_ACTIVATION_WITHIN_FOUR_HOURS"
                )
            rows.append(
                {
                    "case_alias": alias,
                    "action": action,
                    "decision_at": iso(decision_at),
                    "actual_v4_match": actual,
                    "diagnostic_natural_state_match": bool(natural),
                    "htf_eligible": htf,
                    "natural_plus_htf_match": bool(natural) and htf,
                    "htf_evidence": "|".join(evidence),
                    "failure_classification": failure,
                    "control_natural_state": False,
                    "control_natural_plus_htf": False,
                }
            )
            continue
        natural_control = False
        htf_control = False
        first_at: datetime | None = None
        first_evidence: list[str] = []
        for activation in v4.activations:
            overlap, eligible, evidence = first_eligible_overlap(
                activation=activation,
                terminal=natural_terminal(activation, v4),
                session_date=decision_at.date(),
                bars=bars,
                pivots=pivots,
            )
            if overlap is None:
                continue
            natural_control = True
            if eligible:
                htf_control = True
                if first_at is None or overlap < first_at:
                    first_at = overlap
                    first_evidence = evidence
        rows.append(
            {
                "case_alias": alias,
                "action": action,
                "decision_at": iso(decision_at),
                "actual_v4_match": prior["semantic_match"] == "True",
                "diagnostic_natural_state_match": False,
                "htf_eligible": False,
                "natural_plus_htf_match": False,
                "htf_evidence": "",
                "failure_classification": "NO_TRADE_CONTROL",
                "control_natural_state": natural_control,
                "control_natural_plus_htf": htf_control,
                "first_control_htf_at": iso(first_at) if first_at else "",
                "first_control_htf_evidence": "|".join(first_evidence),
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trades = [item for item in rows if item["action"] != "NO_TRADE"]
    controls = [item for item in rows if item["action"] == "NO_TRADE"]
    return {
        "trade_population": len(trades),
        "actual_v4_matches": sum(item["actual_v4_match"] for item in trades),
        "diagnostic_natural_state_matches": sum(
            item["diagnostic_natural_state_match"] for item in trades
        ),
        "trade_htf_eligible": sum(item["htf_eligible"] for item in trades),
        "diagnostic_natural_plus_htf_matches": sum(
            item["natural_plus_htf_match"] for item in trades
        ),
        "failure_classes": {
            label: sum(item["failure_classification"] == label for item in trades)
            for label in sorted({item["failure_classification"] for item in trades})
        },
        "control_population": len(controls),
        "control_natural_state_days": sum(
            item["control_natural_state"] for item in controls
        ),
        "control_natural_plus_htf_days": sum(
            item["control_natural_plus_htf"] for item in controls
        ),
    }


async def run(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    freeze = verify_freeze(root)
    v4_rows = read_v4_semantic_rows(root)
    ledger_path = (
        root
        / "research_artifacts/gold_matched_human_replay_v1/ledgers/matched_human_visible_ledger.jsonl"
    )
    ledger = read_jsonl(ledger_path)
    head = verify_chain(ledger)
    decisions = [
        item
        for item in ledger
        if item.get("event_type") in {"DECISION_SEALED", "NO_TRADE_SEALED"}
    ]
    minutes, source = await load_minutes()
    inputs = aggregate_study_inputs(minutes)

    def calculate(
        calculation_inputs: dict[str, list[AggregateBar]],
    ) -> tuple[list[dict[str, Any]], str]:
        v2 = build_liquidity_shift_study_v2(
            calculation_inputs,
            config=LiquidityShiftV2Config(maximum_stop_m15_atr=6.5),
        )
        v4 = build_liquidity_response_m5_state_study_v4(calculation_inputs)
        bars = {
            key: canonical_bars(list(calculation_inputs[key]))
            for key in ("1h", "4h")
        }
        rows = build_rows(
            decisions=decisions,
            v4_rows=v4_rows,
            v4=v4,
            bars=bars,
            pivots=dict(v2.pivots),
        )
        return rows, canonical_hash(asdict(v4))

    primary_rows, primary_detector = calculate(inputs)
    reference_rows, reference_detector = calculate(
        {key: list(reversed(value)) for key, value in inputs.items()}
    )
    if canonical_hash(primary_rows) != canonical_hash(reference_rows):
        raise RuntimeError("Failure-attribution row mismatch")
    if primary_detector != reference_detector:
        raise RuntimeError("Failure-attribution detector mismatch")
    summary = summarize(primary_rows)
    result = {
        "version": "GOLD_LIQUIDITY_RESPONSE_V4_FAILURE_ATTRIBUTION_RESULT_1_0",
        "status": "PASS_OUTCOME_BLIND_FAILURE_ATTRIBUTION_REPRODUCTION",
        "freeze_status": freeze["status"],
        "human_visible_ledger_head_sha256": head,
        "source": source,
        "summary": summary,
        "recommendation": (
            "ONE_SUCCESSOR_USING_NATURAL_FOUR_HOUR_STATE_PLUS_FROZEN_HTF_ELIGIBILITY; "
            "REPLACE_ONLY_M5_NOISE_TERMINATION_WITH_M15_STRUCTURAL_INVALIDATION"
        ),
        "reproduction": {
            "primary_rows_sha256": canonical_hash(primary_rows),
            "reference_rows_sha256": canonical_hash(reference_rows),
            "primary_detector_sha256": primary_detector,
            "reference_detector_sha256": reference_detector,
            "identical": True,
        },
        "outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    return result, primary_rows


async def run_and_dispose(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from gold_intel.infrastructure.database import engine

    try:
        return await run(root)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/workspace"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "result.json"
    rows_path = output / "rows.csv"
    seal_path = output / "seal.json"
    if any(path.exists() for path in (result_path, rows_path, seal_path)):
        raise FileExistsError("Failure-attribution artifacts already exist")
    result, rows = asyncio.run(run_and_dispose(args.root.resolve()))
    write_json_exclusive(result_path, result)
    write_csv_exclusive(rows_path, rows)
    write_json_exclusive(
        seal_path,
        {
            "version": "GOLD_LIQUIDITY_RESPONSE_V4_FAILURE_ATTRIBUTION_SEAL_1_0",
            "status": result["status"],
            "files": {
                result_path.name: {
                    "bytes": result_path.stat().st_size,
                    "sha256": sha256_file(result_path),
                },
                rows_path.name: {
                    "bytes": rows_path.stat().st_size,
                    "sha256": sha256_file(rows_path),
                },
            },
        },
    )
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
