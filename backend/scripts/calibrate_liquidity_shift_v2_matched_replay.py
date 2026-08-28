from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from gold_intel.analytics.liquidity_shift_v2 import (
    LIQUIDITY_SHIFT_V2_RULESET,
    LiquidityEntryIntentV2,
    LiquidityShiftStudyV2,
    LiquidityShiftV2Config,
    build_liquidity_shift_study_v2,
)
from gold_intel.analytics.structure import AggregateBar, MinuteBar, aggregate_minutes
from gold_intel.infrastructure.database import engine, session_factory
from gold_intel.infrastructure.models import PriceBar

GENESIS = "0" * 64
MATCHED_START = datetime(2021, 11, 1, tzinfo=UTC)
MATCHED_END = datetime(2022, 2, 17, tzinfo=UTC)
EXPECTED_CASES = 30
EXPECTED_HUMAN_TRADES = 16


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    def ready(item: Any) -> Any:
        if isinstance(item, datetime):
            return iso(item)
        if isinstance(item, dict):
            return {str(key): ready(member) for key, member in item.items()}
        if isinstance(item, (list, tuple)):
            return [ready(member) for member in item]
        return item

    return json.dumps(
        ready(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def verify_chain(rows: Sequence[dict[str, Any]]) -> str:
    prior = GENESIS
    for sequence, source in enumerate(rows, start=1):
        row = dict(source)
        if row.get("ledger_sequence") != sequence:
            raise RuntimeError(f"Human ledger sequence mismatch at {sequence}")
        if row.get("prior_record_sha256") != prior:
            raise RuntimeError(f"Human ledger prior hash mismatch at {sequence}")
        submitted = str(row.pop("record_sha256", ""))
        if canonical_hash(row) != submitted:
            raise RuntimeError(f"Human ledger record hash mismatch at {sequence}")
        prior = submitted
    return prior


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_csv_exclusive(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def verify_freeze(root: Path) -> dict[str, Any]:
    path = root / "research_manifests" / "gold_hierarchical_liquidity_shift_edge_v2_preoutcome_freeze.json"
    freeze = read_json(path)
    if freeze.get("status") != "SEALED_BEFORE_SEMANTIC_CALIBRATION_AND_DEVELOPMENT_OUTCOME_ACCESS":
        raise RuntimeError("V2 pre-outcome freeze is not valid")
    for section in ("controls", "sources"):
        for record in freeze[section].values():
            source = root / record["path"]
            if sha256_file(source) != record["sha256"]:
                raise RuntimeError(f"Frozen binding changed: {record['path']}")
    if freeze["matched_outcome_ledger_bound_or_opened"] is not False:
        raise RuntimeError("Matched outcome ledger was bound or opened")
    return freeze


def verify_config(root: Path) -> LiquidityShiftV2Config:
    protocol = read_json(
        root / "research_manifests" / "gold_hierarchical_liquidity_shift_edge_v2_protocol.json"
    )
    config = LiquidityShiftV2Config()
    expected = {
        **protocol["structure"],
        **protocol["entries"],
    }
    mapping = {
        "pivot_left": config.pivot_left,
        "pivot_right": config.pivot_right,
        "atr_window": config.atr_window,
        "pivot_prominence_atr": config.pivot_prominence_atr,
        "zone_displacement_atr": config.zone_displacement_atr,
        "zone_body_ratio": config.zone_body_ratio,
        "zone_break_buffer_atr": config.zone_break_buffer_atr,
        "zone_origin_lookback_bars": config.zone_origin_lookback_bars,
        "zone_invalidation_buffer_atr": config.zone_invalidation_buffer_atr,
        "zone_expiry_calendar_days": config.zone_expiry_calendar_days,
        "minimum_zone_age_minutes": config.minimum_zone_age_minutes,
        "maximum_contact_episodes": config.maximum_contact_episodes,
        "contact_separation_m5_bars": config.contact_separation_m5_bars,
        "reaction_m5_bars": config.reaction_m5_bars,
        "transition_m15_bars": config.transition_m15_bars,
        "transition_range_atr": config.transition_range_atr,
        "transition_body_ratio": config.transition_body_ratio,
        "transition_break_buffer_atr": config.transition_break_buffer_atr,
        "retracement_min": config.retracement_min,
        "retracement_max": config.retracement_max,
        "limit_retracement": config.limit_retracement,
        "entry_expiry_m5_bars": config.entry_expiry_m5_bars,
        "confirmation_body_ratio": config.confirmation_body_ratio,
        "confirmation_break_prior_m5_bars": config.confirmation_break_prior_m5_bars,
        "stop_buffer_m15_atr": config.stop_buffer_m15_atr,
        "minimum_stop_m15_atr": config.minimum_stop_m15_atr,
        "maximum_stop_m15_atr": config.maximum_stop_m15_atr,
    }
    for key, value in mapping.items():
        if expected.get(key) != value:
            raise RuntimeError(f"Frozen config mismatch: {key}")
    return config


async def load_minutes() -> tuple[list[MinuteBar], dict[str, Any]]:
    query = (
        select(PriceBar)
        .where(
            PriceBar.instrument_code == "XAUUSD",
            PriceBar.provider_code == "IC_MARKETS_MT5",
            PriceBar.timeframe == "1m",
            PriceBar.is_complete.is_(True),
            PriceBar.is_synthetic.is_(False),
            PriceBar.open_time >= MATCHED_START,
            PriceBar.open_time < MATCHED_END,
        )
        .order_by(PriceBar.open_time, PriceBar.available_at)
    )
    async with session_factory() as session:
        records = list((await session.scalars(query)).all())
    counts = Counter(record.open_time for record in records)
    duplicates = [timestamp for timestamp, count in counts.items() if count != 1]
    if duplicates:
        raise RuntimeError(f"Duplicate M1 identities: {len(duplicates)}")
    bars = [
        MinuteBar(
            id=record.id,
            open_time=record.open_time.astimezone(UTC),
            close_time=record.close_time.astimezone(UTC),
            open=float(record.open),
            high=float(record.high),
            low=float(record.low),
            close=float(record.close),
            volume=float(record.volume) if record.volume is not None else None,
            available_at=record.available_at.astimezone(UTC),
        )
        for record in records
    ]
    digest_rows = [
        (
            item.open_time.isoformat(),
            item.close_time.isoformat(),
            item.open,
            item.high,
            item.low,
            item.close,
            item.available_at.isoformat(),
        )
        for item in bars
    ]
    return bars, {
        "rows": len(bars),
        "first_open": iso(bars[0].open_time) if bars else None,
        "last_open": iso(bars[-1].open_time) if bars else None,
        "identity_and_value_sha256": canonical_hash(digest_rows),
    }


def aggregate_study_inputs(minutes: Sequence[MinuteBar]) -> dict[str, list[AggregateBar]]:
    cutoff = minutes[-1].close_time
    output: dict[str, list[AggregateBar]] = {
        "1m": [
            AggregateBar(
                open_time=item.open_time,
                close_time=item.close_time,
                open=item.open,
                high=item.high,
                low=item.low,
                close=item.close,
                volume=item.volume,
                complete=True,
                source_ids=(str(item.id),),
            )
            for item in minutes
        ]
    }
    for timeframe, interval in (("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240)):
        output[timeframe] = [
            item
            for item in aggregate_minutes(
                list(minutes), timeframe_minutes=interval, as_of=cutoff
            )
            if item.complete and item.close_time <= cutoff
        ]
    return output


def intent_available_at(
    intent: LiquidityEntryIntentV2, decision_at: datetime
) -> tuple[bool, str]:
    if intent.state == "INVALID_GEOMETRY" or intent.order_at > decision_at:
        return False, "NOT_AVAILABLE"
    if intent.triggered_at is not None and intent.triggered_at <= decision_at:
        return True, "TRIGGERED"
    if decision_at < intent.expires_at and (
        intent.triggered_at is None or intent.triggered_at > decision_at
    ):
        return True, "PENDING"
    return False, "EXPIRED_OR_NOT_TRIGGERED"


def calibrate(
    study: LiquidityShiftStudyV2,
    human_rows: Sequence[dict[str, Any]],
    contact_lookback_hours: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    zone_by_id = {item.identity: item for item in study.zones}
    transitions_by_contact: dict[str, list[Any]] = {}
    for item in study.transitions:
        transitions_by_contact.setdefault(item.contact_identity, []).append(item)
    intents_by_transition: dict[str, list[LiquidityEntryIntentV2]] = {}
    for item in study.entry_intents:
        intents_by_transition.setdefault(item.transition_identity, []).append(item)

    rows: list[dict[str, Any]] = []
    for source in human_rows:
        decision = source["data"]["decision"]
        if decision["action"] == "NO_TRADE":
            continue
        direction = "BULLISH" if decision["action"] == "LONG" else "BEARISH"
        decision_at = parse_time(decision["expected_cursor_at"])
        earliest = decision_at - timedelta(hours=contact_lookback_hours)
        contacts = [
            item
            for item in study.contacts
            if item.direction == direction
            and earliest <= item.contact_at <= item.reaction_at <= decision_at
        ]
        transitions = [
            transition
            for contact in contacts
            for transition in transitions_by_contact.get(contact.identity, [])
            if transition.transition_at <= decision_at
        ]
        intent_states: list[tuple[LiquidityEntryIntentV2, str]] = []
        for transition in transitions:
            for intent in intents_by_transition.get(transition.identity, []):
                available, state = intent_available_at(intent, decision_at)
                if available:
                    intent_states.append((intent, state))
        contact_timeframes = sorted(
            {zone_by_id[item.zone_identity].timeframe for item in contacts}
        )
        rows.append(
            {
                "case_alias": source["case_alias"],
                "decision_at": iso(decision_at),
                "direction": direction,
                "contact_match": bool(contacts),
                "contact_count": len(contacts),
                "contact_zone_timeframes": "|".join(contact_timeframes),
                "transition_match": bool(transitions),
                "transition_count": len(transitions),
                "entry_state_match": bool(intent_states),
                "entry_state_count": len(intent_states),
                "entry_families": "|".join(
                    sorted({item.family for item, _ in intent_states})
                ),
                "entry_states": "|".join(sorted({state for _, state in intent_states})),
                "annotation_transition": decision["annotation"].get("m15_transition"),
                "annotation_thesis": decision["annotation"].get("thesis"),
            }
        )
    if len(rows) != EXPECTED_HUMAN_TRADES:
        raise RuntimeError(f"Expected {EXPECTED_HUMAN_TRADES} human trades, found {len(rows)}")
    count = len(rows)
    contact_rate = sum(item["contact_match"] for item in rows) / count
    transition_rate = sum(item["transition_match"] for item in rows) / count
    entry_rate = sum(item["entry_state_match"] for item in rows) / count
    metrics = {
        "human_trades": count,
        "contact_matches": sum(item["contact_match"] for item in rows),
        "contact_rate": round(contact_rate, 8),
        "transition_matches": sum(item["transition_match"] for item in rows),
        "transition_rate": round(transition_rate, 8),
        "triggered_or_pending_entry_matches": sum(
            item["entry_state_match"] for item in rows
        ),
        "triggered_or_pending_entry_rate": round(entry_rate, 8),
        "required_contact_rate": 0.60,
        "required_transition_rate": 0.50,
        "required_entry_rate": 0.40,
    }
    metrics["semantic_verdict"] = (
        "PASS_SEMANTIC_REPRESENTATION"
        if contact_rate >= 0.60 and transition_rate >= 0.50 and entry_rate >= 0.40
        else "FAIL_SEMANTIC_REPRESENTATION"
    )
    return rows, metrics


async def run(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    freeze = verify_freeze(root)
    config = verify_config(root)
    module_path = root / "backend" / "src" / "gold_intel" / "analytics" / "liquidity_shift_v2.py"
    human_path = (
        root
        / "research_artifacts"
        / "gold_matched_human_replay_v1"
        / "ledgers"
        / "matched_human_visible_ledger.jsonl"
    )
    human_ledger = read_jsonl(human_path)
    human_head = verify_chain(human_ledger)
    decisions = [
        item
        for item in human_ledger
        if item.get("event_type") in {"DECISION_SEALED", "NO_TRADE_SEALED"}
    ]
    if len(decisions) != EXPECTED_CASES:
        raise RuntimeError(f"Expected {EXPECTED_CASES} sealed decisions, found {len(decisions)}")

    minutes, source = await load_minutes()
    inputs = aggregate_study_inputs(minutes)
    primary = build_liquidity_shift_study_v2(inputs, config=config)
    reference_inputs = {key: list(reversed(value)) for key, value in inputs.items()}
    reference = build_liquidity_shift_study_v2(reference_inputs, config=config)
    primary_hash = canonical_hash(asdict(primary))
    reference_hash = canonical_hash(asdict(reference))
    if primary_hash != reference_hash:
        raise RuntimeError("Primary/reference V2 detector mismatch")

    protocol = read_json(
        root / "research_manifests" / "gold_hierarchical_liquidity_shift_edge_v2_protocol.json"
    )
    rows, metrics = calibrate(
        primary,
        decisions,
        int(protocol["semantic_gates"]["contact_lookback_hours"]),
    )
    result = {
        "version": "GOLD_HIERARCHICAL_LIQUIDITY_SHIFT_EDGE_V2_SEMANTIC_CALIBRATION_1_0",
        "ruleset": LIQUIDITY_SHIFT_V2_RULESET,
        "research_credit": "ZERO_ECONOMIC_CREDIT_EXPOSED_SEMANTIC_CALIBRATION",
        "preoutcome_freeze_sha256": sha256_file(
            root
            / "research_manifests"
            / "gold_hierarchical_liquidity_shift_edge_v2_preoutcome_freeze.json"
        ),
        "frozen_rules_hash": freeze["rules_hash"],
        "implementation_sha256": sha256_file(module_path),
        "human_visible_ledger_head_sha256": human_head,
        "matched_outcome_ledger_opened": False,
        "source": source,
        "detector_counts": {
            "zones": len(primary.zones),
            "contacts": len(primary.contacts),
            "transitions": len(primary.transitions),
            "entry_intents": len(primary.entry_intents),
            "zones_by_timeframe": dict(Counter(item.timeframe for item in primary.zones)),
            "intents_by_family": dict(Counter(item.family for item in primary.entry_intents)),
        },
        "metrics": metrics,
        "reproduction": {
            "primary_sha256": primary_hash,
            "reference_sha256": reference_hash,
            "identical": True,
        },
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    return result, rows


async def run_and_dispose(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        return await run(root)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/workspace"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result, rows = asyncio.run(run_and_dispose(args.root.resolve()))
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / "semantic_calibration.json"
    rows_path = args.output / "semantic_rows.csv"
    if result_path.exists() or rows_path.exists():
        raise FileExistsError("Semantic calibration artifacts already exist")
    write_json_exclusive(result_path, result)
    write_csv_exclusive(rows_path, rows)
    seal = {
        "version": "GOLD_HIERARCHICAL_LIQUIDITY_SHIFT_EDGE_V2_SEMANTIC_SEAL_1_0",
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
    write_json_exclusive(args.output / "semantic_seal.json", seal)
    print(json.dumps({"metrics": result["metrics"], "detector_counts": result["detector_counts"]}, indent=2))


if __name__ == "__main__":
    main()
