#!/usr/bin/env python3
"""Seal the approved V3 contract and perform the value-blind source/readiness freeze."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
OUT = ROOT / "research_artifacts" / "gold_annotated_replay_v3"
CONTRACT = ROOT / "GOLD_ANNOTATED_TRADINGVIEW_STYLE_REPLAY_AND_HUMAN_EDGE_AUDIT_CONTRACT_V3.md"
PREDECESSOR = ROOT / "research_manifests" / "gold_blind_synchronized_setup_replay_v2_regression_correction_amendment_e_seal.json"
MANIFEST = CASEBOOK / "manifest.json"
PRICE = CASEBOOK / "price_bars.jsonl.gz"
SESSIONS = CASEBOOK / "sessions.jsonl.gz"
AUDIT = OUT / "metadata_coverage_audit.json"
PRIVATE = OUT / "practice_registry.private.json"
PUBLIC = OUT / "practice_registry.public.json"
EXECUTION = OUT / "execution_policy.json"
LEDGER = OUT / "ledger_policy.json"
FREEZE = ROOT / "research_manifests" / "gold_annotated_replay_v3_preimplementation_freeze.json"
SEED = 20260814

TIMEFRAME_RE = re.compile(r'"timeframe":"([^"]+)"')
CLOSE_RE = re.compile(r'"close_time":"([^"]+)"')
AVAILABLE_RE = re.compile(r'"available_at":"([^"]+)"')
COMPLETE_RE = re.compile(r'"complete":(true|false)')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def verify_predecessor() -> dict[str, Any]:
    seal = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if seal.get("verdict") != "PASS_V2_REGRESSION_CORRECTION_AMENDMENT_E":
        raise RuntimeError("Unexpected V2 predecessor verdict")
    for item in seal.get("sealed_outputs", []):
        path = ROOT / str(item["path"])
        if not path.is_file() or path.stat().st_size != int(item["bytes"]) or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"V2 predecessor output differs: {item['path']}")
    return file_record(PREDECESSOR)


def verify_casebook() -> list[dict[str, Any]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("casebook_version") != "GOLD_CASEBOOK_V0_1":
        raise RuntimeError("Unexpected casebook version")
    if manifest.get("contract", {}).get("holdout_loaded") is not False:
        raise RuntimeError("Casebook holdout boundary differs")
    records = []
    for item in manifest["artifacts"]:
        path = CASEBOOK / item["path"]
        record = file_record(path)
        record["expected_bytes"] = item["bytes"]
        record["expected_sha256"] = item["sha256"]
        record["verified"] = record["bytes"] == item["bytes"] and record["sha256"] == item["sha256"]
        records.append(record)
    if not all(item["verified"] for item in records):
        raise RuntimeError("A sealed casebook source failed verification")
    return records


def minute_metadata_primary() -> dict[str, tuple[int, str, str, str]]:
    by_day: dict[str, set[int]] = defaultdict(set)
    duplicate_count = 0
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("timeframe") != "1m" or row.get("complete") is not True:
                continue
            close = parse_time(str(row["close_time"]))
            available = parse_time(str(row["available_at"]))
            if available > close:
                continue
            minute = close.hour * 60 + close.minute
            day = close.date().isoformat()
            if minute in by_day[day]:
                duplicate_count += 1
            by_day[day].add(minute)
    return {
        day: (
            len(minutes),
            f"{min(minutes) // 60:02d}:{min(minutes) % 60:02d}",
            f"{max(minutes) // 60:02d}:{max(minutes) % 60:02d}",
            canonical_hash(sorted(minutes)),
        )
        for day, minutes in by_day.items()
    } | {"__diagnostic__": (duplicate_count, "", "", "")}


def minute_metadata_reference() -> dict[str, tuple[int, str, str, str]]:
    by_day: dict[str, set[int]] = defaultdict(set)
    duplicate_count = 0
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            timeframe = TIMEFRAME_RE.search(line)
            complete = COMPLETE_RE.search(line)
            if timeframe is None or timeframe.group(1) != "1m" or complete is None or complete.group(1) != "true":
                continue
            close_match = CLOSE_RE.search(line)
            available_match = AVAILABLE_RE.search(line)
            if close_match is None or available_match is None:
                raise RuntimeError("Reference minute parser could not extract metadata")
            close = parse_time(close_match.group(1))
            if parse_time(available_match.group(1)) > close:
                continue
            minute = close.hour * 60 + close.minute
            day = close.date().isoformat()
            if minute in by_day[day]:
                duplicate_count += 1
            by_day[day].add(minute)
    return {
        day: (
            len(minutes),
            f"{min(minutes) // 60:02d}:{min(minutes) % 60:02d}",
            f"{max(minutes) // 60:02d}:{max(minutes) % 60:02d}",
            canonical_hash(sorted(minutes)),
        )
        for day, minutes in by_day.items()
    } | {"__diagnostic__": (duplicate_count, "", "", "")}


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


def rank(day: str) -> str:
    return hashlib.sha256(f"GOLD_ANNOTATED_REPLAY_V3|{day}|{SEED}".encode("utf-8")).hexdigest()


def main() -> int:
    targets = (AUDIT, PRIVATE, PUBLIC, EXECUTION, LEDGER, FREEZE)
    if any(path.exists() for path in targets):
        raise RuntimeError("Append-only V3 preimplementation output already exists")
    if "Status: `APPROVED_AND_FROZEN_FOR_IMPLEMENTATION`" not in CONTRACT.read_text(encoding="utf-8"):
        raise RuntimeError("V3 contract is not approved")

    predecessor = verify_predecessor()
    source_records = verify_casebook()
    primary = minute_metadata_primary()
    reference = minute_metadata_reference()
    if primary != reference:
        raise RuntimeError("Primary/reference M1 metadata differs")
    duplicate_count = int(primary.pop("__diagnostic__")[0])
    reference.pop("__diagnostic__")
    session_dates = complete_session_dates()

    eligible = {
        day: details
        for day, details in primary.items()
        if details[0] >= 1000 and day in session_dates and datetime.fromisoformat(day).weekday() < 5
    }
    selected: list[str] = []
    for month in range(8, 13):
        prefix = f"2021-{month:02d}-"
        candidates = sorted((day for day in eligible if day.startswith(prefix)), key=rank)
        if len(candidates) < 4:
            raise RuntimeError(f"Insufficient practice coverage in {prefix}: {len(candidates)}")
        selected.extend(candidates[:4])
    selected.sort()
    if len(selected) != 20 or len(set(selected)) != 20:
        raise RuntimeError("Practice population selection failed")

    yearly = Counter(day[:4] for day in eligible if "2022-01-01" <= day < "2025-01-01")
    viable_years = [year for year in ("2022", "2023", "2024") if yearly[year] >= 230]
    if not viable_years:
        raise RuntimeError(f"No complete primary collection year: {dict(yearly)}")
    primary_year = viable_years[0]

    cases = [
        {
            "case_alias": f"V3-P-{index:03d}",
            "mode": "PRACTICE",
            "mode_sequence": index,
            "trading_date_utc": day,
            "start_inclusive": f"{day}T00:00:00Z",
            "end_exclusive": None,
            "observed_m1_minutes": eligible[day][0],
            "first_close_utc": eligible[day][1],
            "last_close_utc": eligible[day][2],
            "minute_identity_sha256": eligible[day][3],
            "research_credit": "ZERO_PRACTICE_ONLY",
        }
        for index, day in enumerate(selected, start=1)
    ]
    for case in cases:
        start = parse_time(case["start_inclusive"])
        case["end_exclusive"] = (start + timedelta(days=1)).isoformat().replace("+00:00", "Z")

    private = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_PRIVATE_PRACTICE_REGISTRY_1_0",
        "created_at": utc_now(),
        "selection_semantics": "TIMESTAMPS_SESSION_METADATA_AND_COVERAGE_ONLY",
        "seed": SEED,
        "case_count": 20,
        "cases": cases,
        "population_sha256": canonical_hash(cases),
        "primary_collection_year": primary_year,
        "primary_collection_state": "CLOSED_NOT_MATERIALIZED",
        "later_years": [year for year in ("2022", "2023", "2024") if year != primary_year],
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    public_cases = [
        {
            "case_alias": case["case_alias"],
            "mode_sequence": case["mode_sequence"],
            "trading_date_utc": case["trading_date_utc"],
            "research_credit": case["research_credit"],
        }
        for case in cases
    ]
    public = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_PUBLIC_PRACTICE_REGISTRY_1_0",
        "case_count": 20,
        "cases": public_cases,
        "public_population_sha256": canonical_hash(public_cases),
        "one_year_collection": "CLOSED",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    audit = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_METADATA_COVERAGE_AUDIT_1_0",
        "performed_at": utc_now(),
        "verdict": "PASS_V3_METADATA_COVERAGE",
        "market_values_accessed": False,
        "outcomes_accessed": False,
        "source_m1_dates": len(primary),
        "duplicate_complete_m1_timestamps": duplicate_count,
        "complete_london_new_york_session_dates": len(session_dates),
        "eligible_full_day_dates": len(eligible),
        "eligible_by_year": dict(sorted(yearly.items())),
        "practice_dates": selected,
        "practice_observed_m1_counts": {day: eligible[day][0] for day in selected},
        "primary_collection_year": primary_year,
        "primary_collection_year_state": "CLOSED_NOT_MATERIALIZED",
        "selection_semantics": "FOUR_HASH_RANKED_DATES_PER_MONTH_AUGUST_THROUGH_DECEMBER_2021",
        "source_records": source_records,
        "gates": {
            "contract_approved": True,
            "v2_predecessor_verified": True,
            "casebook_sources_verified": True,
            "primary_reference_m1_metadata_exact": True,
            "session_metadata_reproduced": True,
            "practice_exact_20": len(selected) == 20,
            "practice_four_per_month": all(sum(day.startswith(f"2021-{month:02d}-") for day in selected) == 4 for month in range(8, 13)),
            "practice_minimum_1000_observed_minutes": all(eligible[day][0] >= 1000 for day in selected),
            "primary_year_at_least_230_eligible_days": yearly[primary_year] >= 230,
            "one_year_collection_closed": True,
            "calendar_2025_2026_locked": True,
            "no_acquisition_or_charge": True,
        },
        "charge_usd": 0.0,
    }

    execution = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_EXECUTION_POLICY_1_0",
        "frozen_at": utc_now(),
        "account_equity_usd": 10000.0,
        "maximum_planned_risk_usd": 50.0,
        "one_active_position": True,
        "pyramiding": False,
        "partial_exits": False,
        "post_fill_geometry_mutable": False,
        "replay_intervals_minutes": [1, 5, 15],
        "playback_speeds": [1, 2, 4, 8],
        "order_types": ["MARKET", "LIMIT", "STOP"],
        "pending_order_amendment": "PERMITTED_AT_CURRENT_CURSOR_APPEND_ONLY",
        "pending_order_default_expiry": "UTC_TRADING_DAY_END",
        "active_position_time_exit": "UTC_TRADING_DAY_END_LAST_OBSERVED_CLOSE",
        "market_fill": "FIRST_OBSERVED_M1_OPEN_AFTER_CONFIRMATION_PLUS_DIRECTIONAL_HALF_SPREAD_AND_SLIPPAGE",
        "limit_fill": "ENTRY_MUST_BE_EXCEEDED_BY_ONE_0P01_TICK",
        "stop_fill": "FIRST_TOUCH_WITH_DIRECTIONAL_HALF_SPREAD_AND_0P05_PRICE_SLIPPAGE",
        "spread": "SOURCE_SPREAD_PRICE_WHEN_AVAILABLE_ELSE_0P20_PRICE",
        "market_and_stop_slippage_price": 0.05,
        "commission_usd_per_whole_ounce_round_turn": 0.0,
        "latency_minutes": 1,
        "same_bar_ambiguity": "STOP_FIRST",
        "manual_close": "PERMITTED_AS_NEW_ANNOTATED_ACTION_ORIGINAL_GEOMETRY_IMMUTABLE",
        "quantity": "FLOOR_50_USD_DIVIDED_BY_ABSOLUTE_ENTRY_MINUS_STOP_TO_WHOLE_OUNCES",
        "minimum_quantity_ounces": 1,
        "no_retroactive_order_or_amendment": True,
    }
    ledger = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_LEDGER_POLICY_1_0",
        "frozen_at": utc_now(),
        "storage": "SEPARATE_APPEND_ONLY_JSONL_HASH_CHAINS",
        "genesis_sha256": "0" * 64,
        "fsync_before_response": True,
        "idempotency_required": True,
        "human_ledger_isolation_from_tests": True,
        "event_types": [
            "CURSOR_ADVANCED", "INTERVAL_SKIPPED", "ORDER_SUBMITTED", "ORDER_AMENDED",
            "ORDER_CANCELLED", "ORDER_FILLED", "POSITION_CLOSED", "PRACTICE_DAY_COMPLETED",
        ],
        "order_states": ["PENDING_ORDER", "ACTIVE_POSITION", "CANCELLED", "EXPIRED", "RESOLVED"],
        "resolution_states": ["STOPPED", "TARGET_HIT", "MANUAL_CLOSE", "TIME_EXIT", "UNRESOLVED"],
        "immutable_after_fill": ["direction", "order_type", "entry", "stop", "target", "risk_usd", "annotation"],
        "required_record_fields": [
            "version", "ledger_sequence", "event_type", "case_alias", "cursor_at", "idempotency_key",
            "submission_sha256", "prior_record_sha256", "record_sha256",
        ],
        "one_year_collection_ledger": "NOT_CREATED_UNTIL_SEPARATE_AUTHORIZATION",
    }

    write_new(PRIVATE, private)
    write_new(PUBLIC, public)
    write_new(AUDIT, audit)
    write_new(EXECUTION, execution)
    write_new(LEDGER, ledger)
    if not all(audit["gates"].values()):
        raise RuntimeError("V3 metadata coverage gate failed")

    sealed_outputs = [file_record(path) for path in (CONTRACT, AUDIT, PRIVATE, PUBLIC, EXECUTION, LEDGER, Path(__file__))]
    freeze = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_PREIMPLEMENTATION_FREEZE_1_0",
        "sealed_at": utc_now(),
        "status": "SEALED_PRACTICE_ONLY_BEFORE_VALUE_MATERIALIZATION",
        "verdict": "PASS_V3_CONTRACT_COVERAGE_AND_POLICY_FREEZE",
        "predecessor": predecessor,
        "sealed_outputs": sealed_outputs,
        "practice_population_sha256": private["population_sha256"],
        "primary_collection_year": primary_year,
        "primary_collection_state": "CLOSED_NOT_MATERIALIZED",
        "human_practice_events": 0,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    write_new(FREEZE, freeze)
    print(json.dumps({
        "verdict": freeze["verdict"],
        "practice_dates": selected,
        "primary_collection_year": primary_year,
        "eligible_by_year": dict(sorted(yearly.items())),
        "gates": audit["gates"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
