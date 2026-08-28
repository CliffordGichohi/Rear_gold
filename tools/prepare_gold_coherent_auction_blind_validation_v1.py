#!/usr/bin/env python3
"""Freeze the outcome-blind population and policies for coherent-auction validation V1."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
OUT = ROOT / "research_artifacts" / "gold_coherent_auction_blind_validation_v1"
CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_CONTRACT_V1.md"
SOURCE_REGISTRY = (
    ROOT
    / "research_artifacts"
    / "gold_blind_discretionary_replay_v1"
    / "population_registry_v1_1.private.json"
)
MATCHED_REGISTRY = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "population_registry.private.json"
)
PRICE = CASEBOOK / "price_bars.jsonl.gz"
MANIFEST = CASEBOOK / "manifest.json"
PRIVATE = OUT / "population_registry.private.json"
PUBLIC = OUT / "population_registry.public.json"
COVERAGE = OUT / "metadata_coverage_audit.json"
PROTOCOL = OUT / "protocol.json"
EXECUTION = OUT / "execution_policy.json"
LEDGER = OUT / "ledger_policy.json"
STATE = OUT / "state.json"
FREEZE = ROOT / "research_manifests" / "gold_coherent_auction_blind_validation_v1_prevalue_freeze.json"

SESSION_TARGET = 25
MIN_COVERAGE = 0.95
SESSIONS = ("LONDON", "NEW_YORK")


def now() -> str:
    return datetime.now(UTC).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def verify_casebook() -> list[dict[str, Any]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("casebook_version") != "GOLD_CASEBOOK_V0_1":
        raise RuntimeError("Unexpected casebook version")
    if manifest.get("contract", {}).get("holdout_loaded") is not False:
        raise RuntimeError("Casebook holdout boundary differs")
    records: list[dict[str, Any]] = []
    for expected in manifest["artifacts"]:
        path = CASEBOOK / expected["path"]
        record = file_record(path)
        if record["bytes"] != expected["bytes"] or record["sha256"] != expected["sha256"]:
            raise RuntimeError(f"Sealed casebook artifact differs: {expected['path']}")
        records.append(record)
    return records


def price_timestamp_metadata() -> tuple[set[datetime], int, str]:
    timestamps: set[datetime] = set()
    duplicates = 0
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if (
                row.get("instrument_code") != "XAUUSD"
                or row.get("timeframe") != "1m"
                or row.get("complete") is not True
            ):
                continue
            close = parse_time(str(row["close_time"]))
            if not datetime(2022, 1, 1, tzinfo=UTC) <= close < datetime(
                2023, 1, 2, tzinfo=UTC
            ):
                continue
            available = parse_time(str(row["available_at"]))
            if available > close:
                continue
            if close in timestamps:
                duplicates += 1
            timestamps.add(close)
    return timestamps, duplicates, canonical_hash([iso(value) for value in sorted(timestamps)])


def expected_closes(start: datetime, end: datetime) -> list[datetime]:
    minutes = int((end - start).total_seconds() // 60)
    if minutes <= 0:
        raise RuntimeError("Session window is not positive")
    return [start + timedelta(minutes=index) for index in range(1, minutes + 1)]


def main() -> int:
    targets = (PRIVATE, PUBLIC, COVERAGE, PROTOCOL, EXECUTION, LEDGER, STATE, FREEZE)
    existing = [path.relative_to(ROOT).as_posix() for path in targets if path.exists()]
    if existing:
        raise RuntimeError(f"Append-only validation outputs already exist: {existing}")
    contract_text = CONTRACT.read_text(encoding="utf-8")
    if "APPROVED_AND_FROZEN_BEFORE_VALIDATION_VALUE_MATERIALIZATION" not in contract_text:
        raise RuntimeError("Validation contract is not frozen")

    source_records = verify_casebook()
    source_registry = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    matched_registry = json.loads(MATCHED_REGISTRY.read_text(encoding="utf-8"))
    if source_registry.get("version") != "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRIVATE_POPULATION_1_1":
        raise RuntimeError("Unexpected source population version")
    exposed_dates = {str(row["trading_date_utc"]) for row in matched_registry["cases"]}
    if len(exposed_dates) != 30:
        raise RuntimeError("Matched-human exclusion population differs from the sealed 30 cases")

    timestamps, duplicate_count, timestamp_sha = price_timestamp_metadata()
    candidates: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for row in source_registry["cases"]:
        if row.get("mode") != "SCORED" or not str(row.get("session_date", "")).startswith("2022-"):
            continue
        start = parse_time(str(row["decision_at"]))
        end = parse_time(str(row["session_end"]))
        expected = expected_closes(start, end)
        observed = [value for value in expected if value in timestamps]
        coverage = len(observed) / len(expected)
        eligible = (
            row["session_code"] in SESSIONS
            and row["session_date"] not in exposed_dates
            and row["session_date"] > "2022-02-16"
            and coverage >= MIN_COVERAGE
        )
        metadata = {
            "source_case_alias": row["case_alias"],
            "source_mode_sequence": int(row["mode_sequence"]),
            "session_code": row["session_code"],
            "session_date": row["session_date"],
            "start_inclusive": iso(start),
            "end_inclusive": iso(end),
            "expected_m1_closes": len(expected),
            "observed_m1_closes": len(observed),
            "coverage_fraction": round(coverage, 8),
            "observed_identity_sha256": canonical_hash([iso(value) for value in observed]),
            "excluded_as_previously_exposed": row["session_date"] in exposed_dates,
            "eligible": eligible,
        }
        audit_rows.append(metadata)
        if eligible:
            candidates.append({**row, **metadata})

    selected_source: list[dict[str, Any]] = []
    for session in SESSIONS:
        eligible = sorted(
            (row for row in candidates if row["session_code"] == session),
            key=lambda row: int(row["source_mode_sequence"]),
        )
        if len(eligible) < SESSION_TARGET:
            raise RuntimeError(f"Insufficient metadata-eligible {session} cases: {len(eligible)}")
        selected_source.extend(eligible[:SESSION_TARGET])
    selected_source.sort(key=lambda row: int(row["source_mode_sequence"]))

    cases: list[dict[str, Any]] = []
    for index, source in enumerate(selected_source, start=1):
        case = {
            "case_alias": f"GAV-2022-{index:03d}",
            "mode": "BLIND_HISTORICAL_ROBUSTNESS",
            "mode_sequence": index,
            "source_case_alias": source["source_case_alias"],
            "source_mode_sequence": source["source_mode_sequence"],
            "source_session_record_id": source["session_record_id"],
            "source_session_record_hash": source["session_record_hash"],
            "session_code": source["session_code"],
            "trading_date_utc": source["session_date"],
            "start_inclusive": source["start_inclusive"],
            "end_inclusive": source["end_inclusive"],
            "expected_m1_closes": source["expected_m1_closes"],
            "observed_m1_closes": source["observed_m1_closes"],
            "coverage_fraction": source["coverage_fraction"],
            "observed_identity_sha256": source["observed_identity_sha256"],
            "research_credit": "HISTORICAL_BLIND_ROBUSTNESS_ONLY",
        }
        cases.append(case)

    counts = Counter(row["session_code"] for row in cases)
    if counts != Counter({"LONDON": 25, "NEW_YORK": 25}):
        raise RuntimeError(f"Frozen session balance differs: {dict(counts)}")
    if any(row["trading_date_utc"] in exposed_dates for row in cases):
        raise RuntimeError("A previously exposed date entered the validation population")

    private = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_PRIVATE_POPULATION_1_0",
        "created_at": now(),
        "selection_semantics": "FIRST_25_PER_SESSION_IN_EXISTING_OUTCOME_BLIND_V1_1_ORDER_AFTER_METADATA_EXCLUSIONS",
        "case_count": len(cases),
        "cases": cases,
        "population_sha256": canonical_hash(cases),
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    public_cases = [
        {
            "case_alias": row["case_alias"],
            "mode_sequence": row["mode_sequence"],
            "session_code": row["session_code"],
            "trading_date_utc": row["trading_date_utc"],
            "research_credit": row["research_credit"],
        }
        for row in cases
    ]
    public = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_PUBLIC_POPULATION_1_0",
        "case_count": len(public_cases),
        "cases": public_cases,
        "public_population_sha256": canonical_hash(public_cases),
        "aggregate_results": "LOCKED_UNTIL_ALL_50_COMPLETE",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }

    protocol = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_PROTOCOL_1_0",
        "frozen_at": now(),
        "contract_sha256": sha256_file(CONTRACT),
        "case_count": 50,
        "maximum_orders_per_case": 1,
        "decision_taxonomy": {
            "auction_families": [
                "CONTINUATION_WITH_ROOM",
                "RANGE_ROTATION",
                "STRUCTURAL_REPAIR",
                "OTHER_EXPLICIT",
            ],
            "h4_states": [
                "PULLBACK_WITH_ROOM",
                "BALANCE_LOWER_ROTATION",
                "BALANCE_UPPER_ROTATION",
                "UPPER_BOUNDARY_EXTENDED",
                "LOWER_BOUNDARY_EXTENDED",
                "BEARISH_DAMAGE",
                "BULLISH_DAMAGE",
                "ACCEPTED_REPAIR",
                "UNKNOWN",
            ],
            "locations": [
                "DISCOUNT",
                "MIDRANGE",
                "PREMIUM",
                "AT_SUPPORT",
                "AT_RESISTANCE",
                "UNKNOWN",
            ],
            "stop_bases": [
                "ACTIVE_M15_PROTECTED_SWING",
                "CONTROLLING_M15_RANGE_BOUNDARY",
                "POST_REPAIR_ORIGIN",
                "OTHER_EXPLICIT",
            ],
            "target": "H1_OPPOSING_LIQUIDITY",
        },
        "management_tracks": {
            "A": "ONE_HUNDRED_PERCENT_AT_FROZEN_H1_TARGET",
            "B": "PLUS_1R_M5_PROTECTION_THEN_80_PERCENT_H1_CORE_AND_20_PERCENT_ACCEPTED_M15_RUNNER",
        },
        "pass_gates": {
            "minimum_executed_trades": 20,
            "net_expectancy_after_costs_gt": 0.0,
            "profit_factor_gte": 1.10,
            "both_chronological_halves_positive": True,
            "maximum_single_session_positive_gross_share": 0.80,
            "positive_at_cost_multiplier": 1.5,
        },
        "aggregate_feedback_before_case_50": "PROHIBITED",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    execution = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_EXECUTION_POLICY_1_0",
        "frozen_at": now(),
        "account_equity_usd": 10000.0,
        "maximum_planned_risk_usd": 50.0,
        "minimum_quantity_ounces": 1,
        "quantity": "FLOOR_50_USD_DIVIDED_BY_ABSOLUTE_ENTRY_MINUS_STOP_TO_WHOLE_OUNCES",
        "order_types": ["MARKET", "LIMIT", "STOP"],
        "market_and_stop_slippage_price": 0.05,
        "spread": "SOURCE_SPREAD_PRICE_WHEN_AVAILABLE_ELSE_0P20_PRICE",
        "commission_usd_per_whole_ounce_round_turn": 0.0,
        "latency_minutes": 1,
        "same_bar_ambiguity": "STOP_FIRST",
        "one_active_position": True,
        "maximum_orders_per_case": 1,
        "partial_exits_in_live_replay": False,
        "management_tracks_evaluated_after_collection": ["H1_CONTROL", "PROTECTION_80_20_RUNNER"],
        "post_fill_geometry_mutable": False,
        "pending_order_amendment": "PERMITTED_AT_CURRENT_CURSOR_APPEND_ONLY",
        "active_position_time_exit": "SESSION_END_LAST_OBSERVED_CLOSE",
        "market_fill": "FIRST_OBSERVED_M1_OPEN_AFTER_CONFIRMATION_PLUS_DIRECTIONAL_HALF_SPREAD_AND_SLIPPAGE",
        "limit_fill": "ENTRY_MUST_BE_EXCEEDED_BY_ONE_0P01_TICK",
        "stop_fill": "FIRST_TOUCH_WITH_DIRECTIONAL_HALF_SPREAD_AND_0P05_PRICE_SLIPPAGE",
        "no_retroactive_order_or_amendment": True,
    }
    ledger = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_LEDGER_POLICY_1_0",
        "frozen_at": now(),
        "storage": "SEPARATE_APPEND_ONLY_JSONL_HASH_CHAIN",
        "genesis_sha256": "0" * 64,
        "event_version": "GOLD_ANNOTATED_REPLAY_V3_EVENT_1_0",
        "event_types": [
            "CURSOR_ADVANCED",
            "INTERVAL_SKIPPED",
            "ORDER_SUBMITTED",
            "ORDER_AMENDED",
            "ORDER_CANCELLED",
            "ORDER_FILLED",
            "POSITION_CLOSED",
            "NO_TRADE_RECORDED",
            "PRACTICE_DAY_COMPLETED",
        ],
        "fsync_before_response": True,
        "idempotency_required": True,
        "aggregate_results_locked_until_complete": True,
    }
    coverage = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_METADATA_COVERAGE_AUDIT_1_0",
        "performed_at": now(),
        "verdict": "PASS_PREVALUE_POPULATION_AND_COVERAGE_FREEZE",
        "market_values_accessed": False,
        "outcomes_accessed": False,
        "timestamp_universe_sha256": timestamp_sha,
        "duplicate_eligible_price_timestamps": duplicate_count,
        "source_2022_scored_session_count": sum(
            row.get("mode") == "SCORED" and str(row.get("session_date", "")).startswith("2022-")
            for row in source_registry["cases"]
        ),
        "previously_exposed_date_count": len(exposed_dates),
        "eligible_counts_before_selection": dict(Counter(row["session_code"] for row in candidates)),
        "selected_counts": dict(counts),
        "selected_minimum_coverage_fraction": min(row["coverage_fraction"] for row in cases),
        "candidate_metadata": audit_rows,
        "source_records": [
            *source_records,
            file_record(CONTRACT),
            file_record(SOURCE_REGISTRY),
            file_record(MATCHED_REGISTRY),
        ],
        "gates": {
            "contract_frozen": True,
            "casebook_seals_verified": True,
            "source_population_verified": True,
            "matched_exclusions_exact_30": len(exposed_dates) == 30,
            "every_selected_date_after_2022_02_16": all(
                row["trading_date_utc"] > "2022-02-16" for row in cases
            ),
            "every_selected_case_at_least_95pct_m1_coverage": all(
                row["coverage_fraction"] >= MIN_COVERAGE for row in cases
            ),
            "exact_25_london_and_25_new_york": counts
            == Counter({"LONDON": 25, "NEW_YORK": 25}),
            "no_previously_exposed_dates": all(
                row["trading_date_utc"] not in exposed_dates for row in cases
            ),
            "calendar_2025_2026_locked": True,
            "no_acquisition_or_charge": True,
        },
        "charge_usd": 0.0,
    }
    if not all(coverage["gates"].values()):
        raise RuntimeError(f"Prevalue coverage gate failed: {coverage['gates']}")

    write_new(PRIVATE, private)
    write_new(PUBLIC, public)
    write_new(COVERAGE, coverage)
    write_new(PROTOCOL, protocol)
    write_new(EXECUTION, execution)
    write_new(LEDGER, ledger)
    sealed_outputs = [file_record(path) for path in (PRIVATE, PUBLIC, COVERAGE, PROTOCOL, EXECUTION, LEDGER)]
    freeze = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_PREVALUE_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_VALIDATION_VALUE_MATERIALIZATION",
        "population_sha256": private["population_sha256"],
        "case_count": 50,
        "sealed_outputs": sealed_outputs,
        "source_records": coverage["source_records"],
        "values_materialized": False,
        "outcomes_accessed": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "charge_usd": 0.0,
    }
    write_new(FREEZE, freeze)
    state = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_STATE_1_0",
        "recorded_at": now(),
        "status": "PASS_PREVALUE_FREEZE_READY_FOR_STREAM_MATERIALIZATION",
        "population_sha256": private["population_sha256"],
        "prevalue_freeze": file_record(FREEZE),
        "decisions_collected": 0,
        "aggregate_results": "LOCKED",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    write_new(STATE, state)
    print(
        json.dumps(
            {
                "verdict": coverage["verdict"],
                "cases": len(cases),
                "sessions": dict(counts),
                "date_min": min(row["trading_date_utc"] for row in cases),
                "date_max": max(row["trading_date_utc"] for row in cases),
                "minimum_coverage": coverage["selected_minimum_coverage_fraction"],
                "population_sha256": private["population_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
