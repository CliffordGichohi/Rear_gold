from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
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
from calibrate_persistent_liquidity_shift_v3 import (
    active_session,
    read_preserved_v2_rows,
    verify_config,
    verify_freeze,
)

from gold_intel.analytics.liquidity_shift_v3 import (
    PERSISTENT_LIQUIDITY_SHIFT_V3_RULESET,
    PersistentEntryIntentV3,
    PersistentLiquidityShiftStudyV3,
    build_persistent_liquidity_shift_study_v3,
)


def verify_correction_freeze(root: Path) -> dict[str, Any]:
    path = (
        root
        / "research_manifests"
        / "gold_persistent_liquidity_shift_v3_semantic_engineering_correction_a_freeze.json"
    )
    freeze = read_json(path)
    if freeze.get("status") != "SEALED_BEFORE_CORRECTED_SEMANTIC_REPRODUCTION":
        raise RuntimeError("Correction A freeze is invalid")
    for record in freeze["files"].values():
        source = root / record["path"]
        if sha256_file(source) != record["sha256"]:
            raise RuntimeError(f"Correction A frozen file changed: {record['path']}")
    if freeze.get("single_change_only") is not True:
        raise RuntimeError("Correction A scope is not singular")
    return freeze


def corrected_intent_available_at(
    intent: PersistentEntryIntentV3,
    study: PersistentLiquidityShiftStudyV3,
    decision_at: datetime,
) -> tuple[bool, str, datetime | None]:
    if intent.state == "INVALID_GEOMETRY" or intent.order_at > decision_at:
        return False, "NOT_AVAILABLE", None
    state = next(item for item in study.states if item.identity == intent.state_identity)
    if not state.started_at <= intent.order_at < state.terminal_at:
        raise RuntimeError("Entry intent lies outside its auction state")
    if (
        intent.triggered_at is not None
        and intent.triggered_at <= decision_at < intent.expires_at
    ):
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
        direction = "BULLISH" if decision["action"] == "LONG" else "BEARISH"
        decision_at = parse_time(decision["expected_cursor_at"])
        available: list[tuple[PersistentEntryIntentV3, str, datetime]] = []
        for intent in study.entry_intents:
            if intent.direction != direction:
                continue
            matched, state, available_at = corrected_intent_available_at(
                intent, study, decision_at
            )
            if matched and available_at is not None:
                available.append((intent, state, available_at))
        prior = preserved[alias]
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
                "latest_order_expires_at": (
                    iso(max(item.expires_at for item, _, _ in available))
                    if available
                    else ""
                ),
                "state_source_timeframes": "|".join(
                    sorted(
                        {
                            auction.source_zone_timeframe
                            for intent, _, _ in available
                            for auction in study.states
                            if auction.identity == intent.state_identity
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
    v3_freeze = verify_freeze(root)
    correction_freeze = verify_correction_freeze(root)
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
        raise RuntimeError("Corrected V3 primary/reference mismatch")
    rows, metrics = calibrate(primary, decisions, preserved)
    result = {
        "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_V3_SEMANTIC_ENGINEERING_CORRECTION_A_RESULT_1_0",
        "ruleset": PERSISTENT_LIQUIDITY_SHIFT_V3_RULESET,
        "research_credit": "SEMANTIC_ONLY_ZERO_ECONOMIC_CREDIT",
        "preserved_invalid_engineering_result": "PASS_SEMANTIC_REPRESENTATION_16_OF_16",
        "single_correction": "triggered_at <= decision_at < expires_at",
        "v3_preoutcome_rules_hash": v3_freeze["rules_hash"],
        "correction_freeze_sha256": sha256_file(
            root
            / "research_manifests"
            / "gold_persistent_liquidity_shift_v3_semantic_engineering_correction_a_freeze.json"
        ),
        "correction_frozen_files": correction_freeze["files"],
        "human_visible_ledger_head_sha256": ledger_head,
        "source": source,
        "detector_counts": {
            "states": len(primary.states),
            "impulses": len(primary.impulses),
            "entry_intents": len(primary.entry_intents),
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
    result_path = output / "semantic_calibration_correction_a.json"
    rows_path = output / "semantic_rows_correction_a.csv"
    seal_path = output / "semantic_seal_correction_a.json"
    if any(path.exists() for path in (result_path, rows_path, seal_path)):
        raise FileExistsError("Corrected semantic artifacts already exist")
    result, rows = asyncio.run(run_and_dispose(args.root.resolve()))
    write_json_exclusive(result_path, result)
    write_csv_exclusive(rows_path, rows)
    seal = {
        "version": "GOLD_PERSISTENT_LIQUIDITY_SHIFT_V3_SEMANTIC_ENGINEERING_CORRECTION_A_SEAL_1_0",
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
