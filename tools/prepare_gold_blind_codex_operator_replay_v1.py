#!/usr/bin/env python3
"""Freeze the outcome-blind 2022 Codex browser-operator replay protocol."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "research_artifacts/gold_casebook_v01"
SOURCE_AUDIT = ROOT / "research_artifacts/gold_annotated_replay_v3/metadata_coverage_audit.json"
V3_CERT_SEAL = ROOT / "research_manifests/gold_annotated_replay_v3_practice_certification_seal.json"
V3_INTERPRETATION_SEAL = ROOT / "research_manifests/gold_annotated_replay_v3_post_practice_interpretation_seal.json"
V3_LEDGER = ROOT / "research_artifacts/gold_annotated_replay_v3/ledgers/practice_event_ledger_v3.jsonl"
CONTRACT = ROOT / "GOLD_BLIND_CODEX_OPERATOR_REPLAY_AUDIT_CONTRACT_V1.md"
OUT = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1"
MANIFEST = ROOT / "research_manifests/gold_blind_codex_operator_replay_v1_prevalue_freeze.json"

PRICE = CASEBOOK / "price_bars.jsonl.gz"
SESSIONS = CASEBOOK / "sessions.jsonl.gz"

PRIVATE_REGISTRY = OUT / "population_registry.private.json"
PUBLIC_REGISTRY = OUT / "population_registry.public.json"
COVERAGE = OUT / "metadata_coverage_audit.json"
DECISION = OUT / "decision_policy.json"
EXECUTION = OUT / "execution_policy.json"
EVIDENCE = OUT / "evidence_policy.json"
LEDGER = OUT / "ledger_policy.json"
EVALUATION = OUT / "evaluation_policy.json"

TIMEFRAME_RE = re.compile(r'"timeframe"\s*:\s*"([^"]+)"')
COMPLETE_RE = re.compile(r'"complete"\s*:\s*(true|false)')
CLOSE_RE = re.compile(r'"close_time"\s*:\s*"([^"]+)"')
AVAILABLE_RE = re.compile(r'"available_at"\s*:\s*"([^"]+)"')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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
        "path": path.resolve().relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"Append-only output already exists: {path.relative_to(ROOT)}")
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def verify_sealed_file(item: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / str(item["path"])
    actual = file_record(path)
    if actual["bytes"] != int(item["bytes"]) or actual["sha256"] != str(item["sha256"]):
        raise RuntimeError(f"Sealed predecessor differs: {item['path']}")
    return actual


def verify_predecessors() -> list[dict[str, Any]]:
    cert = json.loads(V3_CERT_SEAL.read_text(encoding="utf-8"))
    if cert.get("verdict") != "PASS_V3_APPLICATION_AND_BROWSER_CERTIFICATION":
        raise RuntimeError("V3 application/browser predecessor is not a PASS")
    records = [verify_sealed_file(item) for item in cert["sealed_outputs"]]
    interpretation = json.loads(V3_INTERPRETATION_SEAL.read_text(encoding="utf-8"))
    if interpretation.get("status") != "SEALED_INFERRED_REVIEW_ZERO_CREDIT":
        raise RuntimeError("V3 post-practice interpretation predecessor differs")
    for item in (
        interpretation["source_diagnostic"],
        interpretation["source_diagnostic_seal"],
        interpretation["interpretation"],
    ):
        records.append(verify_sealed_file(item))
    ledger_record = file_record(V3_LEDGER)
    if ledger_record["sha256"] != "7639d3609b904a2bd7f92c6df5a596cecf148a91d4853282a6d5a17e68d193d6":
        raise RuntimeError("Human V3 practice ledger differs from its completed seal")
    records.append(ledger_record)
    return records


def verify_sources() -> list[dict[str, Any]]:
    audit = json.loads(SOURCE_AUDIT.read_text(encoding="utf-8"))
    if audit.get("verdict") != "PASS_V3_METADATA_COVERAGE":
        raise RuntimeError("V3 source coverage predecessor is not a PASS")
    records: list[dict[str, Any]] = []
    for item in audit["source_records"]:
        actual = file_record(ROOT / item["path"])
        if actual["bytes"] != int(item["bytes"]) or actual["sha256"] != item["sha256"]:
            raise RuntimeError(f"Casebook source differs: {item['path']}")
        records.append(actual)
    return records


def m1_metadata_primary() -> tuple[dict[str, tuple[int, str, str, str]], int]:
    minutes_by_day: dict[str, set[int]] = defaultdict(set)
    duplicates = 0
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("instrument_code") != "XAUUSD" or row.get("timeframe") != "1m" or row.get("complete") is not True:
                continue
            close = parse_time(str(row["close_time"]))
            if parse_time(str(row["available_at"])) > close:
                continue
            minute = close.hour * 60 + close.minute
            day = close.date().isoformat()
            duplicates += int(minute in minutes_by_day[day])
            minutes_by_day[day].add(minute)
    return ({
        day: (
            len(minutes),
            f"{min(minutes) // 60:02d}:{min(minutes) % 60:02d}",
            f"{max(minutes) // 60:02d}:{max(minutes) % 60:02d}",
            canonical_hash(sorted(minutes)),
        )
        for day, minutes in minutes_by_day.items()
    }, duplicates)


def m1_metadata_reference() -> tuple[dict[str, tuple[int, str, str, str]], int]:
    minutes_by_day: dict[str, set[int]] = defaultdict(set)
    duplicates = 0
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            timeframe = TIMEFRAME_RE.search(line)
            complete = COMPLETE_RE.search(line)
            if timeframe is None or timeframe.group(1) != "1m" or complete is None or complete.group(1) != "true":
                continue
            close_match = CLOSE_RE.search(line)
            available_match = AVAILABLE_RE.search(line)
            if close_match is None or available_match is None:
                raise RuntimeError("Reference timestamp parser failed")
            close = parse_time(close_match.group(1))
            if parse_time(available_match.group(1)) > close:
                continue
            minute = close.hour * 60 + close.minute
            day = close.date().isoformat()
            duplicates += int(minute in minutes_by_day[day])
            minutes_by_day[day].add(minute)
    return ({
        day: (
            len(minutes),
            f"{min(minutes) // 60:02d}:{min(minutes) % 60:02d}",
            f"{max(minutes) // 60:02d}:{max(minutes) % 60:02d}",
            canonical_hash(sorted(minutes)),
        )
        for day, minutes in minutes_by_day.items()
    }, duplicates)


def complete_session_dates() -> set[str]:
    primary: dict[str, set[str]] = defaultdict(set)
    reference_rows: list[tuple[str, str]] = []
    with gzip.open(SESSIONS, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("session_code") in {"LONDON", "NEW_YORK"} and row.get("data_quality", {}).get("status") == "COMPLETE":
                pair = (str(row["session_date"]), str(row["session_code"]))
                primary[pair[0]].add(pair[1])
                reference_rows.append(pair)
    reference: dict[str, set[str]] = defaultdict(set)
    for day, code in sorted(reference_rows):
        reference[day].add(code)
    if dict(primary) != dict(reference):
        raise RuntimeError("Independent session metadata extraction differs")
    return {day for day, codes in primary.items() if codes == {"LONDON", "NEW_YORK"}}


def main() -> int:
    targets = (PRIVATE_REGISTRY, PUBLIC_REGISTRY, COVERAGE, DECISION, EXECUTION, EVIDENCE, LEDGER, EVALUATION, MANIFEST)
    if any(path.exists() for path in targets):
        raise RuntimeError("Append-only Codex pre-value output already exists")
    if "Status: `APPROVED_AND_FROZEN_BEFORE_2022_VALUE_ACCESS`" not in CONTRACT.read_text(encoding="utf-8"):
        raise RuntimeError("Codex-operator contract is not approved")
    disk_free = shutil.disk_usage(ROOT).free
    if disk_free < 25 * 1024**3:
        raise RuntimeError("Pre-value storage gate failed: less than 25 GiB free")

    predecessor_records = verify_predecessors()
    source_records = verify_sources()
    primary, primary_duplicates = m1_metadata_primary()
    reference, reference_duplicates = m1_metadata_reference()
    if primary != reference or primary_duplicates != reference_duplicates:
        raise RuntimeError("Independent M1 timestamp metadata differs")
    session_dates = complete_session_dates()
    eligible = {
        day: details
        for day, details in primary.items()
        if day.startswith("2022-")
        and details[0] >= 1000
        and day in session_dates
        and datetime.fromisoformat(day).weekday() < 5
    }
    days = sorted(eligible)
    if len(days) != 249:
        raise RuntimeError(f"Frozen 2022 population expected 249 dates, found {len(days)}")

    cases = []
    for sequence, day in enumerate(days, start=1):
        start = parse_time(f"{day}T00:00:00Z")
        cases.append({
            "case_alias": f"CBR-2022-{sequence:03d}",
            "mode": "CODEX_BLIND",
            "mode_sequence": sequence,
            "trading_date_utc": day,
            "start_inclusive": start.isoformat().replace("+00:00", "Z"),
            "end_exclusive": (start + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "observed_m1_minutes": eligible[day][0],
            "first_close_utc": eligible[day][1],
            "last_close_utc": eligible[day][2],
            "minute_identity_sha256": eligible[day][3],
            "maximum_submitted_trades": 1,
            "research_credit": "BLINDED_HISTORICAL_OPERATOR_EVIDENCE",
        })

    private_registry = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PRIVATE_POPULATION_1_0",
        "created_at": utc_now(),
        "selection_semantics": "ALL_METADATA_ELIGIBLE_CALENDAR_2022_UTC_TRADING_DATES",
        "case_count": len(cases),
        "cases": cases,
        "population_sha256": canonical_hash(cases),
        "operator": "CODEX_BLIND",
        "outcomes": "LOCKED_UNTIL_COMPLETE_POPULATION",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    public_cases = [{
        "case_alias": case["case_alias"],
        "mode_sequence": case["mode_sequence"],
        "trading_date_utc": case["trading_date_utc"],
        "research_credit": case["research_credit"],
    } for case in cases]
    public_registry = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PUBLIC_POPULATION_1_0",
        "case_count": len(cases),
        "cases": public_cases,
        "public_population_sha256": canonical_hash(public_cases),
        "outcomes": "LOCKED",
        "human_decisions": "HIDDEN",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    decision_policy = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_DECISION_POLICY_1_0",
        "frozen_at": utc_now(),
        "operator_input": "RENDERED_BROWSER_PIXELS_AND_VISIBLE_CONTROLS_ONLY",
        "case_actions": ["LONG", "SHORT", "NO_TRADE"],
        "setup_classes": [
            "MACRO_ALIGNED_CONTINUATION",
            "COUNTER_MACRO_RANGE_ROTATION",
            "MACRO_NEUTRAL_AUCTION_TRADE",
        ],
        "entry_sessions": ["LONDON", "LONDON_NEW_YORK_OVERLAP", "NEW_YORK"],
        "asia_use": "CONTEXT_ONLY",
        "primary_trigger_timeframe": "15m",
        "context_timeframes": ["1w", "1d", "4h", "1h"],
        "execution_refinement_timeframes": ["5m", "1m"],
        "method": [
            "POINT_IN_TIME_MACRO_CONTEXT",
            "PREEXISTING_HTF_TREND_OR_RANGE_AND_LOCATION",
            "M15_TRANSITION_ORIGINATING_AT_LOCATION",
            "ACTIVE_SESSION_NEW_AUCTION_DIRECTION",
            "OPPOSING_STRUCTURE_OR_ORIGIN_ZONE_INVALIDATION",
            "NEXT_PREEXISTING_OPPOSING_LIQUIDITY_TARGET",
        ],
        "counter_macro_requirement": "HTF_RANGE_AND_PREEXISTING_PREMIUM_DISCOUNT_EXTREME_AND_ALIGNED_M15_TRANSITION",
        "maximum_submitted_trades_per_case": 1,
        "outcome_feedback_during_collection": False,
        "retroactive_decisions": False,
    }
    execution_policy = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EXECUTION_POLICY_1_0",
        "frozen_at": utc_now(),
        "account_equity_usd": 10000.0,
        "maximum_planned_risk_usd": 50.0,
        "maximum_effective_fill_to_stop_risk_usd": 55.0,
        "order_types": ["MARKET"],
        "latency_minutes": 1,
        "market_fill": "FIRST_OBSERVED_M1_OPEN_AFTER_CONFIRMATION_PLUS_DIRECTIONAL_HALF_SPREAD_AND_0P05_SLIPPAGE",
        "spread": "SOURCE_SPREAD_PRICE_WHEN_AVAILABLE_ELSE_0P20_PRICE",
        "market_and_stop_slippage_price": 0.05,
        "commission_usd_per_whole_ounce_round_turn": 0.0,
        "same_bar_ambiguity": "STOP_FIRST",
        "quantity": "FLOOR_50_USD_DIVIDED_BY_ABSOLUTE_ENTRY_MINUS_STOP_TO_WHOLE_OUNCES",
        "minimum_quantity_ounces": 1,
        "one_live_position": True,
        "maximum_submitted_trades_per_case": 1,
        "partial_exits": False,
        "manual_close": False,
        "post_fill_modification": False,
        "time_exit": "UTC_TRADING_DAY_END_LAST_OBSERVED_M1_CLOSE",
        "invalid_fill_geometry": "FLATTEN_FIRST_PERMITTED_OBSERVATION_RETAIN_RESULT_AND_FLAG",
    }
    evidence_policy = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EVIDENCE_POLICY_1_0",
        "frozen_at": utc_now(),
        "required_case_artifacts": [
            "INITIAL_FULL_PAGE_SCREENSHOT",
            "EACH_INSPECTED_TIMEFRAME_SCREENSHOT",
            "FINAL_PREDECISION_FULL_PAGE_SCREENSHOT",
            "FINAL_PREDECISION_CHART_CROP",
            "COMPLETED_DECISION_FORM_SCREENSHOT",
            "FULL_BROWSER_VIDEO",
            "PLAYWRIGHT_TRACE",
            "CHRONOLOGICAL_ACTION_LOG",
            "VISIBLE_STATE_AND_DECISION_HASHES",
            "SEALED_OUTCOME_SCREENSHOT_AND_VIDEO",
        ],
        "predecision_storage": "OPERATOR_VISIBLE_APPEND_ONLY_EVIDENCE",
        "outcome_storage": "SEALED_OUTCOME_VAULT_NOT_OPERATOR_ACCESSIBLE_UNTIL_FINAL_OPEN",
        "hash": "SHA256_EVERY_FILE_PLUS_CASE_MANIFEST",
        "external_upload": False,
        "preopen_minimum_free_gib": 25,
        "runtime_stop_free_gib": 10,
    }
    ledger_policy = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_LEDGER_POLICY_1_0",
        "frozen_at": utc_now(),
        "operator": "CODEX_BLIND",
        "genesis_sha256": "0" * 64,
        "append_only": True,
        "fsync_before_response": True,
        "idempotency_required": True,
        "human_ledger_path_forbidden": "research_artifacts/gold_annotated_replay_v3/ledgers/practice_event_ledger_v3.jsonl",
        "event_types": [
            "CASE_STARTED",
            "CURSOR_ADVANCED",
            "TIMEFRAME_INSPECTED",
            "DECISION_SEALED",
            "NO_TRADE_SEALED",
            "CASE_TERMINAL_HIDDEN",
        ],
        "outcome_event_types": ["ORDER_FILLED", "POSITION_RESOLVED", "CASE_OUTCOME_SEALED"],
        "outcome_ledger_isolation": True,
    }
    evaluation_policy = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EVALUATION_POLICY_1_0",
        "frozen_at": utc_now(),
        "minimum_valid_filled_trades": 30,
        "profit_factor_minimum": 1.10,
        "expectancy_required_positive": True,
        "clustered_95pct_expectancy_lower_bound_required_positive": True,
        "positive_quarters_minimum": 3,
        "stressed_cost_multiplier": 1.5,
        "stressed_expectancy_required_positive": True,
        "maximum_drawdown_pct": 15.0,
        "maximum_single_quarter_positive_pnl_share": 0.70,
        "bootstrap_seed": 20260818,
        "bootstrap_resamples": 20000,
        "verdicts": ["PASS", "REJECT", "INCONCLUSIVE", "FAIL_INTEGRITY"],
    }
    coverage = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_METADATA_COVERAGE_AUDIT_1_0",
        "performed_at": utc_now(),
        "verdict": "PASS_CODEX_OPERATOR_2022_METADATA_AND_POWER_READINESS",
        "market_values_accessed": False,
        "outcomes_accessed": False,
        "selection_uses_outcomes": False,
        "source_m1_dates": len(primary),
        "complete_session_dates": len(session_dates),
        "calendar_2022_case_count": len(cases),
        "duplicate_complete_m1_timestamps": primary_duplicates,
        "minimum_observed_m1_minutes": min(case["observed_m1_minutes"] for case in cases),
        "maximum_observed_m1_minutes": max(case["observed_m1_minutes"] for case in cases),
        "first_case_date": cases[0]["trading_date_utc"],
        "last_case_date": cases[-1]["trading_date_utc"],
        "usable_disk_gib": round(disk_free / 1024**3, 3),
        "source_records": source_records,
        "gates": {
            "contract_approved": True,
            "v3_predecessors_verified": True,
            "human_ledger_preserved": True,
            "casebook_sources_verified": True,
            "primary_reference_timestamp_metadata_exact": True,
            "session_metadata_reproduced": True,
            "population_exactly_all_249_eligible_2022_dates": len(cases) == 249,
            "minimum_1000_m1_minutes_each": all(case["observed_m1_minutes"] >= 1000 for case in cases),
            "dates_unique_and_chronological": days == sorted(set(days)),
            "storage_at_least_25_gib": disk_free >= 25 * 1024**3,
            "calendar_2025_2026_locked": True,
            "no_acquisition_or_charge": True,
        },
        "charge_usd": 0.0,
    }
    if not all(coverage["gates"].values()):
        raise RuntimeError(f"Pre-value coverage gate failed: {coverage['gates']}")

    for path, payload in (
        (PRIVATE_REGISTRY, private_registry),
        (PUBLIC_REGISTRY, public_registry),
        (COVERAGE, coverage),
        (DECISION, decision_policy),
        (EXECUTION, execution_policy),
        (EVIDENCE, evidence_policy),
        (LEDGER, ledger_policy),
        (EVALUATION, evaluation_policy),
    ):
        write_new(path, payload)

    sealed_outputs = [file_record(path) for path in (
        CONTRACT,
        PRIVATE_REGISTRY,
        PUBLIC_REGISTRY,
        COVERAGE,
        DECISION,
        EXECUTION,
        EVIDENCE,
        LEDGER,
        EVALUATION,
        Path(__file__),
    )]
    freeze = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PREVALUE_FREEZE_1_0",
        "sealed_at": utc_now(),
        "status": "SEALED_BEFORE_CALENDAR_2022_VALUE_MATERIALIZATION",
        "verdict": "PASS_CONTRACT_COVERAGE_POPULATION_POLICY_FREEZE",
        "population_sha256": private_registry["population_sha256"],
        "case_count": len(cases),
        "predecessor_records": predecessor_records,
        "source_records": source_records,
        "sealed_outputs": sealed_outputs,
        "sealed_outputs_sha256": canonical_hash(sealed_outputs),
        "outcomes": "LOCKED",
        "human_decisions": "HIDDEN",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    write_new(MANIFEST, freeze)
    print(json.dumps({
        "verdict": freeze["verdict"],
        "case_count": len(cases),
        "first_case_date": cases[0]["trading_date_utc"],
        "last_case_date": cases[-1]["trading_date_utc"],
        "usable_disk_gib": coverage["usable_disk_gib"],
        "population_sha256": private_registry["population_sha256"],
        "manifest_sha256": sha256_file(MANIFEST),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
