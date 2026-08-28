from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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

from gold_intel.analytics.liquidity_shift_v3 import (
    PERSISTENT_LIQUIDITY_SHIFT_V3_RULESET,
    PersistentEntryIntentV3,
    PersistentLiquidityShiftStudyV3,
    PersistentLiquidityShiftV3Config,
    build_persistent_liquidity_shift_study_v3,
)

EXPECTED_RULES_HASH = "eed31ffc05acc4751a2947fd519131aa8ea4bf299f0a5782d39a1821cea92dca"


def verify_freeze(root: Path) -> dict[str, Any]:
    path = (
        root
        / "research_manifests"
        / "gold_persistent_liquidity_shift_auction_state_v3_preoutcome_freeze.json"
    )
    freeze = read_json(path)
    if freeze.get("status") != "SEALED_BEFORE_V3_SEMANTIC_CALIBRATION":
        raise RuntimeError("V3 pre-outcome freeze is invalid")
    if freeze.get("rules_hash") != EXPECTED_RULES_HASH:
        raise RuntimeError("V3 frozen rules hash changed")
    for section in ("controls", "predecessors"):
        for record in freeze[section].values():
            source = root / record["path"]
            if sha256_file(source) != record["sha256"]:
                raise RuntimeError(f"Frozen predecessor changed: {record['path']}")
    prohibited = (
        "matched_outcome_ledger_opened",
        "development_outcomes_opened",
        "calendar_2025_opened",
        "calendar_2026_opened",
    )
    if any(freeze.get(key) is not False for key in prohibited):
        raise RuntimeError("A prohibited outcome partition is marked open")
    return freeze


def verify_config(root: Path) -> PersistentLiquidityShiftV3Config:
    protocol = read_json(
        root
        / "research_manifests"
        / "gold_persistent_liquidity_shift_auction_state_v3_protocol.json"
    )
    config = PersistentLiquidityShiftV3Config()
    expected = {
        "maximum_state_hours": protocol["state"]["maximum_hours"],
        "opposite_transition_range_atr": protocol["state"][
            "opposite_transition_range_atr"
        ],
        "opposite_transition_body_ratio": protocol["state"][
            "opposite_transition_body_ratio"
        ],
        "opposite_transition_break_buffer_atr": protocol["state"][
            "opposite_transition_break_buffer_atr"
        ],
        "m5_impulse_range_atr": protocol["m5_impulse"]["range_atr"],
        "m5_impulse_body_ratio": protocol["m5_impulse"]["body_ratio"],
        "m5_impulse_break_buffer_atr": protocol["m5_impulse"]["break_buffer_atr"],
        "m5_origin_lookback_bars": protocol["m5_impulse"]["origin_lookback_bars"],
        "retracement_min": protocol["entries"]["retracement_min"],
        "retracement_max": protocol["entries"]["retracement_max"],
        "limit_retracement": protocol["entries"]["limit_retracement"],
        "entry_expiry_m5_bars": protocol["entries"]["expiry_m5_bars"],
        "confirmation_body_ratio": protocol["entries"]["confirmation_body_ratio"],
        "confirmation_break_prior_m5_bars": protocol["entries"][
            "confirmation_break_prior_m5_bars"
        ],
        "stop_buffer_m5_atr": protocol["entries"]["stop_buffer_m5_atr"],
        "minimum_stop_m15_atr": protocol["entries"]["minimum_stop_m15_atr"],
        "maximum_stop_m15_atr": protocol["entries"]["maximum_stop_m15_atr"],
    }
    actual = asdict(config)
    for key, value in expected.items():
        if actual[key] != value:
            raise RuntimeError(f"V3 implementation/config mismatch: {key}")
    return config


def read_preserved_v2_rows(root: Path) -> dict[str, dict[str, str]]:
    directory = root / "research_artifacts" / "gold_hierarchical_liquidity_shift_edge_v2"
    seal = read_json(directory / "semantic_seal_amendment_a.json")
    record = seal["files"]["semantic_rows_amendment_a.csv"]
    path = directory / "semantic_rows_amendment_a.csv"
    if sha256_file(path) != record["sha256"]:
        raise RuntimeError("Preserved V2 semantic rows changed")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != EXPECTED_HUMAN_TRADES:
        raise RuntimeError("Preserved V2 human-trade population changed")
    return {row["case_alias"]: row for row in rows}


def active_session(timestamp: datetime) -> tuple[str | None, float]:
    sessions = (
        ("LONDON", ZoneInfo("Europe/London")),
        ("NEW_YORK", ZoneInfo("America/New_York")),
    )
    for name, timezone in sessions:
        local = timestamp.astimezone(timezone)
        minute = local.hour * 60 + local.minute + local.second / 60
        if 8 * 60 <= minute < 12 * 60:
            return name, 12 * 60 - minute
    return None, 0.0


def intent_available_at(
    intent: PersistentEntryIntentV3,
    study: PersistentLiquidityShiftStudyV3,
    decision_at: datetime,
) -> tuple[bool, str, datetime | None]:
    if intent.state == "INVALID_GEOMETRY" or intent.order_at > decision_at:
        return False, "NOT_AVAILABLE", None
    state = next(item for item in study.states if item.identity == intent.state_identity)
    if not state.started_at <= intent.order_at < state.terminal_at:
        raise RuntimeError("Entry intent lies outside its auction state")
    if intent.triggered_at is not None and intent.triggered_at <= decision_at:
        session, remaining = active_session(intent.triggered_at)
        return session is not None and remaining >= 30, "TRIGGERED", intent.triggered_at
    if decision_at < intent.expires_at and (
        intent.triggered_at is None or intent.triggered_at > decision_at
    ):
        session, remaining = active_session(decision_at)
        return session is not None and remaining >= 30, "PENDING", decision_at
    return False, "EXPIRED_OR_NOT_TRIGGERED", None


def calibrate(
    study: PersistentLiquidityShiftStudyV3,
    human_rows: list[dict[str, Any]],
    preserved: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in human_rows:
        decision = source["data"]["decision"]
        if decision["action"] == "NO_TRADE":
            continue
        alias = source["case_alias"]
        prior = preserved[alias]
        direction = "BULLISH" if decision["action"] == "LONG" else "BEARISH"
        decision_at = parse_time(decision["expected_cursor_at"])
        available: list[tuple[PersistentEntryIntentV3, str, datetime]] = []
        for intent in study.entry_intents:
            if intent.direction != direction:
                continue
            matched, entry_state, available_at = intent_available_at(
                intent, study, decision_at
            )
            if matched and available_at is not None:
                available.append((intent, entry_state, available_at))
        session, remaining = active_session(decision_at)
        rows.append(
            {
                "case_alias": alias,
                "decision_at": iso(decision_at),
                "direction": direction,
                "decision_session": session or "OUTSIDE_FROZEN_SESSION",
                "minutes_to_session_close": round(remaining, 4),
                "preserved_contact_match": prior["contact_match"] == "True",
                "preserved_transition_match": prior["transition_match"] == "True",
                "entry_state_match": bool(available),
                "entry_state_count": len(available),
                "entry_families": "|".join(
                    sorted({item.family for item, _, _ in available})
                ),
                "entry_states": "|".join(sorted({state for _, state, _ in available})),
                "latest_available_at": (
                    iso(max(timestamp for _, _, timestamp in available))
                    if available
                    else ""
                ),
                "state_source_timeframes": "|".join(
                    sorted(
                        {
                            state.source_zone_timeframe
                            for intent, _, _ in available
                            for state in study.states
                            if state.identity == intent.state_identity
                        }
                    )
                ),
                "annotation_transition": decision["annotation"].get("m15_transition"),
                "annotation_thesis": decision["annotation"].get("thesis"),
            }
        )
    if len(rows) != EXPECTED_HUMAN_TRADES:
        raise RuntimeError(f"Expected {EXPECTED_HUMAN_TRADES} trades, found {len(rows)}")
    contact_matches = sum(row["preserved_contact_match"] for row in rows)
    transition_matches = sum(row["preserved_transition_match"] for row in rows)
    entry_matches = sum(row["entry_state_match"] for row in rows)
    metrics = {
        "human_trades": len(rows),
        "preserved_contact_matches": contact_matches,
        "preserved_contact_rate": round(contact_matches / len(rows), 8),
        "preserved_transition_matches": transition_matches,
        "preserved_transition_rate": round(transition_matches / len(rows), 8),
        "triggered_or_pending_entry_matches": entry_matches,
        "triggered_or_pending_entry_rate": round(entry_matches / len(rows), 8),
        "minimum_entry_matches": 7,
        "required_entry_rate": 0.40,
        "semantic_verdict": (
            "PASS_SEMANTIC_REPRESENTATION"
            if entry_matches >= 7
            else "FAIL_SEMANTIC_REPRESENTATION"
        ),
    }
    return rows, metrics


async def run(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    freeze = verify_freeze(root)
    config = verify_config(root)
    preserved = read_preserved_v2_rows(root)
    human_path = (
        root
        / "research_artifacts"
        / "gold_matched_human_replay_v1"
        / "ledgers"
        / "matched_human_visible_ledger.jsonl"
    )
    ledger = read_jsonl(human_path)
    ledger_head = verify_chain(ledger)
    decisions = [
        row
        for row in ledger
        if row.get("event_type") in {"DECISION_SEALED", "NO_TRADE_SEALED"}
    ]
    if len(decisions) != EXPECTED_CASES:
        raise RuntimeError(f"Expected {EXPECTED_CASES} decisions, found {len(decisions)}")
    minutes, source = await load_minutes()
    inputs = aggregate_study_inputs(minutes)
    primary = build_persistent_liquidity_shift_study_v3(inputs, config=config)
    reference = build_persistent_liquidity_shift_study_v3(
        {key: list(reversed(value)) for key, value in inputs.items()}, config=config
    )
    primary_hash = canonical_hash(asdict(primary))
    reference_hash = canonical_hash(asdict(reference))
    if primary_hash != reference_hash:
        raise RuntimeError("V3 primary/reference detector mismatch")
    rows, metrics = calibrate(primary, decisions, preserved)
    module = root / "backend" / "src" / "gold_intel" / "analytics" / "liquidity_shift_v3.py"
    result = {
        "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_AUCTION_STATE_V3_SEMANTIC_CALIBRATION_1_0",
        "ruleset": PERSISTENT_LIQUIDITY_SHIFT_V3_RULESET,
        "research_credit": "ZERO_ECONOMIC_CREDIT_EXPOSED_SEMANTIC_CALIBRATION",
        "preserved_v2_verdict": "FAIL_SEMANTIC_REPRESENTATION",
        "preoutcome_freeze_sha256": sha256_file(
            root
            / "research_manifests"
            / "gold_persistent_liquidity_shift_auction_state_v3_preoutcome_freeze.json"
        ),
        "frozen_rules_hash": freeze["rules_hash"],
        "implementation_sha256": sha256_file(module),
        "human_visible_ledger_head_sha256": ledger_head,
        "source": source,
        "detector_counts": {
            "states": len(primary.states),
            "impulses": len(primary.impulses),
            "entry_intents": len(primary.entry_intents),
            "states_by_direction": dict(Counter(item.direction for item in primary.states)),
            "states_by_source_timeframe": dict(
                Counter(item.source_zone_timeframe for item in primary.states)
            ),
            "intents_by_family": dict(Counter(item.family for item in primary.entry_intents)),
            "intent_states": dict(Counter(item.state for item in primary.entry_intents)),
        },
        "metrics": metrics,
        "reproduction": {
            "primary_sha256": primary_hash,
            "reference_sha256": reference_hash,
            "identical": True,
        },
        "matched_outcome_ledger_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    return result, rows


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
    result_path = output / "semantic_calibration.json"
    rows_path = output / "semantic_rows.csv"
    seal_path = output / "semantic_seal.json"
    if any(path.exists() for path in (result_path, rows_path, seal_path)):
        raise FileExistsError("V3 semantic artifacts already exist")
    result, rows = asyncio.run(run_and_dispose(args.root.resolve()))
    write_json_exclusive(result_path, result)
    write_csv_exclusive(rows_path, rows)
    seal = {
        "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_AUCTION_STATE_V3_SEMANTIC_SEAL_1_0",
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
