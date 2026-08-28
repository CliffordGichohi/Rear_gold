from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from calibrate_liquidity_shift_v2_matched_replay import (
    aggregate_study_inputs,
    iso,
    load_minutes,
    parse_time,
    read_jsonl,
    sha256_file,
    verify_chain,
    verify_config,
    verify_freeze,
    write_json_exclusive,
)

from gold_intel.analytics.liquidity_shift_v2 import build_liquidity_shift_study_v2


def classify_intent(intent: Any, decision_at: Any) -> list[str]:
    reasons: list[str] = []
    if intent.state == "INVALID_GEOMETRY":
        reasons.append("INVALID_GEOMETRY")
    if intent.triggered_at is None:
        reasons.append("NO_TRIGGER_IN_WINDOW")
    elif intent.triggered_at > decision_at:
        reasons.append("TRIGGER_AFTER_HUMAN_DECISION")
    else:
        reasons.append("TRIGGERED_BY_HUMAN_DECISION")
    if intent.order_at > decision_at:
        reasons.append("ORDER_AFTER_HUMAN_DECISION")
    elif intent.expires_at <= decision_at:
        reasons.append("EXPIRED_BY_HUMAN_DECISION")
    else:
        reasons.append("ORDER_LIVE_AT_HUMAN_DECISION")
    return reasons


async def diagnose(root: Path) -> dict[str, Any]:
    freeze = verify_freeze(root)
    config = verify_config(root)
    human_path = (
        root
        / "research_artifacts"
        / "gold_matched_human_replay_v1"
        / "ledgers"
        / "matched_human_visible_ledger.jsonl"
    )
    ledger = read_jsonl(human_path)
    head = verify_chain(ledger)
    decisions = [
        item
        for item in ledger
        if item.get("event_type") in {"DECISION_SEALED", "NO_TRADE_SEALED"}
        and item["data"]["decision"]["action"] != "NO_TRADE"
    ]
    minutes, source = await load_minutes()
    study = build_liquidity_shift_study_v2(
        aggregate_study_inputs(minutes), config=config
    )
    transitions_by_contact: dict[str, list[Any]] = {}
    for transition in study.transitions:
        transitions_by_contact.setdefault(transition.contact_identity, []).append(transition)
    intents_by_transition: dict[str, list[Any]] = {}
    for intent in study.entry_intents:
        intents_by_transition.setdefault(intent.transition_identity, []).append(intent)

    reason_counts: Counter[str] = Counter()
    family_state_counts: Counter[str] = Counter()
    detail: list[dict[str, Any]] = []
    matching_transitions = 0
    for source_decision in decisions:
        decision = source_decision["data"]["decision"]
        direction = "BULLISH" if decision["action"] == "LONG" else "BEARISH"
        decision_at = parse_time(decision["expected_cursor_at"])
        contacts = [
            item
            for item in study.contacts
            if item.direction == direction
            and decision_at - timedelta(hours=96)
            <= item.contact_at
            <= item.reaction_at
            <= decision_at
        ]
        transitions = [
            transition
            for contact in contacts
            for transition in transitions_by_contact.get(contact.identity, [])
            if transition.transition_at <= decision_at
        ]
        matching_transitions += len(transitions)
        for transition in transitions:
            for intent in intents_by_transition.get(transition.identity, []):
                reasons = classify_intent(intent, decision_at)
                reason_counts.update(reasons)
                family_state_counts[f"{intent.family}|{intent.state}"] += 1
                detail.append(
                    {
                        "case_alias": source_decision["case_alias"],
                        "decision_at": iso(decision_at),
                        "family": intent.family,
                        "zone_timeframe": intent.zone_timeframe,
                        "transition_at": iso(transition.transition_at),
                        "order_at": iso(intent.order_at),
                        "expires_at": iso(intent.expires_at),
                        "triggered_at": iso(intent.triggered_at)
                        if intent.triggered_at
                        else None,
                        "state": intent.state,
                        "stop_distance_atr": intent.stop_distance_atr,
                        "reasons": reasons,
                    }
                )
    return {
        "version": "GOLD_HIERARCHICAL_LIQUIDITY_SHIFT_EDGE_V2_SEMANTIC_ENTRY_DIAGNOSTIC_1_0",
        "scope": "OUTCOME_BLIND_ENTRY_STAGE_ONLY",
        "frozen_rules_hash": freeze["rules_hash"],
        "human_visible_ledger_head_sha256": head,
        "source": source,
        "human_trade_decisions": len(decisions),
        "matching_transition_instances": matching_transitions,
        "intent_instances": len(detail),
        "family_state_counts": dict(sorted(family_state_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "detail": detail,
        "matched_outcome_ledger_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }


async def diagnose_and_dispose(root: Path) -> dict[str, Any]:
    from gold_intel.infrastructure.database import engine

    try:
        return await diagnose(root)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/workspace"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(diagnose_and_dispose(args.root.resolve()))
    write_json_exclusive(args.output, result)
    print(
        json.dumps(
            {
                "human_trade_decisions": result["human_trade_decisions"],
                "matching_transition_instances": result["matching_transition_instances"],
                "intent_instances": result["intent_instances"],
                "family_state_counts": result["family_state_counts"],
                "reason_counts": result["reason_counts"],
                "sha256": sha256_file(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
