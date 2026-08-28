from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from calibrate_liquidity_shift_v2_matched_replay import (
    EXPECTED_CASES,
    EXPECTED_HUMAN_TRADES,
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

from gold_intel.analytics.liquidity_shift_v4 import (
    LIQUIDITY_RESPONSE_M5_STATE_V4_RULESET,
    LiquidityResponseM5StateStudyV4,
    LiquidityResponseM5StateV4Config,
    M5ActivationStateV4,
    build_liquidity_response_m5_state_study_v4,
)


def verify_freeze(root: Path) -> dict[str, Any]:
    path = (
        root
        / "research_manifests"
        / "gold_liquidity_response_m5_structure_state_edge_v4_preoutcome_freeze.json"
    )
    freeze = read_json(path)
    if freeze.get("status") != (
        "SEALED_BEFORE_V4_SEMANTIC_AND_DEVELOPMENT_OUTCOME_ACCESS"
    ):
        raise RuntimeError("V4 pre-outcome freeze is invalid")
    for record in freeze["files"].values():
        source = root / record["path"]
        if sha256_file(source) != record["sha256"]:
            raise RuntimeError(f"Frozen V4 input changed: {record['path']}")
    prohibited = (
        "matched_outcomes_opened",
        "development_outcomes_opened",
        "calendar_2025_opened",
        "calendar_2026_opened",
    )
    if any(freeze.get(key) is not False for key in prohibited):
        raise RuntimeError("A prohibited V4 partition is marked open")
    return freeze


def verify_config(root: Path) -> LiquidityResponseM5StateV4Config:
    protocol = read_json(
        root
        / "research_manifests"
        / "gold_liquidity_response_m5_structure_state_edge_v4_protocol.json"
    )
    config = LiquidityResponseM5StateV4Config()
    expected = {
        "maximum_location_hours": protocol["location_episode"]["maximum_hours"],
        "maximum_activation_hours": protocol["activation"]["maximum_hours"],
        "break_buffer_ticks": protocol["activation"]["break_buffer_ticks"],
        "stop_buffer_m5_atr": protocol["stop_buffer_m5_atr"],
    }
    actual = asdict(config)
    for key, value in expected.items():
        if actual[key] != value:
            raise RuntimeError(f"V4 implementation/config mismatch: {key}")
    semantic = protocol["semantic"]
    if semantic != {
        "trade_population": 16,
        "minimum_trade_matches": 10,
        "no_trade_population": 14,
        "maximum_false_positive_days": 7,
        "minimum_minutes_to_session_close": 30,
        "attempts": 1,
        "outcomes_permitted": False,
    }:
        raise RuntimeError("V4 semantic gates changed")
    return config


def activation_at_decision(
    study: LiquidityResponseM5StateStudyV4,
    decision_at: datetime,
    direction: str,
) -> list[M5ActivationStateV4]:
    session, remaining = active_session(decision_at)
    if session is None or remaining < 30:
        return []
    return [
        item
        for item in study.activations
        if item.direction == direction
        and item.started_at <= decision_at < item.terminal_at
    ]


def eligible_overlap_on_utc_date(
    activation: M5ActivationStateV4, session_date: date
) -> tuple[bool, str | None, datetime | None]:
    day_start = datetime.combine(session_date, time.min, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    start = max(activation.started_at, day_start)
    end = min(activation.terminal_at, day_end)
    cursor = start.replace(second=0, microsecond=0)
    if cursor < start:
        cursor += timedelta(minutes=1)
    while cursor < end:
        session, remaining = active_session(cursor)
        if session is not None and remaining >= 30:
            return True, session, cursor
        cursor += timedelta(minutes=1)
    return False, None, None


def calibrate(
    study: LiquidityResponseM5StateStudyV4,
    decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    trade_matches = 0
    false_positive_days = 0
    for source in decisions:
        decision = source["data"]["decision"]
        decision_at = parse_time(decision["expected_cursor_at"])
        action = decision["action"]
        if action in {"LONG", "SHORT"}:
            direction = "BULLISH" if action == "LONG" else "BEARISH"
            matches = activation_at_decision(study, decision_at, direction)
            trade_matches += bool(matches)
            rows.append(
                {
                    "case_alias": source["case_alias"],
                    "action": action,
                    "decision_at": iso(decision_at),
                    "semantic_match": bool(matches),
                    "matching_activation_count": len(matches),
                    "latest_activation_started_at": (
                        iso(matches[-1].started_at) if matches else ""
                    ),
                    "latest_activation_age_minutes": (
                        round(
                            (decision_at - matches[-1].started_at).total_seconds() / 60,
                            4,
                        )
                        if matches
                        else None
                    ),
                    "zone_timeframes": "|".join(
                        sorted({item.zone_timeframe for item in matches})
                    ),
                    "false_positive_day": False,
                    "first_false_positive_at": "",
                    "first_false_positive_session": "",
                }
            )
            continue
        overlaps: list[tuple[M5ActivationStateV4, str, datetime]] = []
        for activation in study.activations:
            matched, session, timestamp = eligible_overlap_on_utc_date(
                activation, decision_at.date()
            )
            if matched and session is not None and timestamp is not None:
                overlaps.append((activation, session, timestamp))
        overlaps.sort(key=lambda item: (item[2], item[0].identity))
        false_positive_days += bool(overlaps)
        rows.append(
            {
                "case_alias": source["case_alias"],
                "action": action,
                "decision_at": iso(decision_at),
                "semantic_match": not overlaps,
                "matching_activation_count": len(overlaps),
                "latest_activation_started_at": "",
                "latest_activation_age_minutes": None,
                "zone_timeframes": "|".join(
                    sorted({item.zone_timeframe for item, _, _ in overlaps})
                ),
                "false_positive_day": bool(overlaps),
                "first_false_positive_at": iso(overlaps[0][2]) if overlaps else "",
                "first_false_positive_session": overlaps[0][1] if overlaps else "",
            }
        )
    if len(rows) != EXPECTED_CASES:
        raise RuntimeError("V4 semantic row count changed")
    verdict = (
        "PASS_SEMANTIC_REPRESENTATION"
        if trade_matches >= 10 and false_positive_days <= 7
        else "FAIL_SEMANTIC_REPRESENTATION"
    )
    metrics = {
        "trade_population": EXPECTED_HUMAN_TRADES,
        "trade_matches": trade_matches,
        "trade_match_rate": round(trade_matches / EXPECTED_HUMAN_TRADES, 8),
        "minimum_trade_matches": 10,
        "no_trade_population": EXPECTED_CASES - EXPECTED_HUMAN_TRADES,
        "false_positive_days": false_positive_days,
        "false_positive_day_rate": round(
            false_positive_days / (EXPECTED_CASES - EXPECTED_HUMAN_TRADES), 8
        ),
        "maximum_false_positive_days": 7,
        "semantic_verdict": verdict,
    }
    return rows, metrics


async def run(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    freeze = verify_freeze(root)
    config = verify_config(root)
    ledger_path = (
        root
        / "research_artifacts"
        / "gold_matched_human_replay_v1"
        / "ledgers"
        / "matched_human_visible_ledger.jsonl"
    )
    ledger = read_jsonl(ledger_path)
    head = verify_chain(ledger)
    decisions = [
        row
        for row in ledger
        if row.get("event_type") in {"DECISION_SEALED", "NO_TRADE_SEALED"}
    ]
    if len(decisions) != EXPECTED_CASES:
        raise RuntimeError("V4 decision population changed")
    minutes, source = await load_minutes()
    inputs = aggregate_study_inputs(minutes)
    primary = build_liquidity_response_m5_state_study_v4(inputs, config=config)
    reference = build_liquidity_response_m5_state_study_v4(
        {key: list(reversed(value)) for key, value in inputs.items()}, config=config
    )
    primary_hash = canonical_hash(asdict(primary))
    reference_hash = canonical_hash(asdict(reference))
    if primary_hash != reference_hash:
        raise RuntimeError("V4 detector reproduction mismatch")
    primary_rows, metrics = calibrate(primary, decisions)
    reference_rows, reference_metrics = calibrate(reference, decisions)
    if canonical_hash(primary_rows) != canonical_hash(reference_rows):
        raise RuntimeError("V4 semantic-row reproduction mismatch")
    if metrics != reference_metrics:
        raise RuntimeError("V4 metric reproduction mismatch")
    module = root / "backend" / "src" / "gold_intel" / "analytics" / "liquidity_shift_v4.py"
    result = {
        "version": "GOLD_LIQUIDITY_RESPONSE_M5_STRUCTURE_STATE_EDGE_V4_SEMANTIC_RESULT_1_0",
        "ruleset": LIQUIDITY_RESPONSE_M5_STATE_V4_RULESET,
        "research_credit": "SEMANTIC_ONLY_ZERO_ECONOMIC_CREDIT",
        "freeze_sha256": sha256_file(
            root
            / "research_manifests"
            / "gold_liquidity_response_m5_structure_state_edge_v4_preoutcome_freeze.json"
        ),
        "freeze_status": freeze["status"],
        "implementation_sha256": sha256_file(module),
        "human_visible_ledger_head_sha256": head,
        "source": source,
        "detector_counts": {
            "locations": len(primary.locations),
            "breaks": len(primary.breaks),
            "activations": len(primary.activations),
            "entry_intents": len(primary.entry_intents),
            "activations_by_direction": dict(
                Counter(item.direction for item in primary.activations)
            ),
            "activations_by_zone_timeframe": dict(
                Counter(item.zone_timeframe for item in primary.activations)
            ),
            "intent_states": dict(Counter(item.state for item in primary.entry_intents)),
        },
        "metrics": metrics,
        "reproduction": {
            "primary_detector_sha256": primary_hash,
            "reference_detector_sha256": reference_hash,
            "semantic_rows_sha256": canonical_hash(primary_rows),
            "identical": True,
        },
        "matched_outcomes_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
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
    result_path = output / "semantic_calibration.json"
    rows_path = output / "semantic_rows.csv"
    seal_path = output / "semantic_seal.json"
    if any(path.exists() for path in (result_path, rows_path, seal_path)):
        raise FileExistsError("V4 semantic artifacts already exist")
    result, rows = asyncio.run(run_and_dispose(args.root.resolve()))
    write_json_exclusive(result_path, result)
    write_csv_exclusive(rows_path, rows)
    seal = {
        "version": "GOLD_LIQUIDITY_RESPONSE_M5_STRUCTURE_STATE_EDGE_V4_SEMANTIC_SEAL_1_0",
        "verdict": result["metrics"]["semantic_verdict"],
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
    }
    write_json_exclusive(seal_path, seal)
    print(
        json.dumps(
            {"metrics": result["metrics"], "detector_counts": result["detector_counts"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
