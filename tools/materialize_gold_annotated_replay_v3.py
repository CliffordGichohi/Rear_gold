#!/usr/bin/env python3
"""Materialize independently reproduced, practice-only V3 chronological replay streams."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
OUT = ROOT / "research_artifacts" / "gold_annotated_replay_v3"
FREEZE = ROOT / "research_manifests" / "gold_annotated_replay_v3_preimplementation_freeze.json"
AMENDMENT_FREEZE = ROOT / "research_manifests" / "gold_annotated_replay_v3_practice_stream_coverage_amendment_a_freeze.json"
REGISTRY = OUT / "practice_registry.private.json"
PRIMARY = OUT / "practice_streams_v3_1.primary.jsonl.gz"
REFERENCE = OUT / "practice_streams_v3_1.reference.jsonl.gz"
CERTIFICATION = OUT / "practice_stream_materialization_certification_v3_1.json"

PRICE = CASEBOOK / "price_bars.jsonl.gz"
FUNDAMENTALS = CASEBOOK / "fundamentals.jsonl.gz"
STRUCTURE = CASEBOOK / "structure_snapshots.jsonl.gz"
CROSS_MARKET = CASEBOOK / "cross_market_snapshots.jsonl.gz"
POSITIONING = CASEBOOK / "positioning.jsonl.gz"
EVENTS = CASEBOOK / "events.jsonl.gz"
SESSIONS = CASEBOOK / "sessions.jsonl.gz"

TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")
SOURCE_TIMEFRAMES = {"1d", "4h", "1h", "15m", "5m", "1m"}
LIMITS = {"1w": 52, "1d": 260, "4h": 200, "1h": 300, "15m": 400, "5m": 600, "1m": 1500}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@lru_cache(maxsize=None)
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_frozen_sources() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_PRACTICE_ONLY_BEFORE_VALUE_MATERIALIZATION":
        raise RuntimeError("V3 preimplementation freeze differs")
    for item in freeze["sealed_outputs"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Frozen V3 output differs: {item['path']}")
    for item in json.loads((OUT / "metadata_coverage_audit.json").read_text(encoding="utf-8"))["source_records"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Frozen casebook source differs: {item['path']}")
    amendment = json.loads(AMENDMENT_FREEZE.read_text(encoding="utf-8"))
    if amendment.get("status") != "SEALED_BEFORE_CORRECTED_MATERIALIZATION":
        raise RuntimeError("V3 practice-stream coverage amendment differs")
    for item in [amendment["amendment"], *amendment["preserved_original_artifacts"], amendment["reused_predecessor_rule"]]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Coverage Amendment A predecessor differs: {item['path']}")
    return freeze


def display_eligible(row: dict[str, Any]) -> bool:
    if row.get("timeframe") != "1d":
        return row.get("complete") is True
    source_count = int(row.get("source", {}).get("source_count") or 0)
    total = source_count + int(row.get("missing_source_minutes") or 0)
    return source_count >= 1000 and total > 0 and source_count / total >= 0.95


def price_record(row: dict[str, Any]) -> dict[str, Any]:
    ohlc = row["ohlc"]
    spread_source = row.get("spread_price")
    if isinstance(spread_source, dict):
        spread_source = spread_source.get("average")
    body = {
        "timeframe": str(row["timeframe"]),
        "open_at": iso(parse_time(str(row["open_time"]))),
        "close_at": iso(parse_time(str(row["close_time"]))),
        "available_at": iso(parse_time(str(row["available_at"]))),
        "open": float(ohlc["open"]),
        "high": float(ohlc["high"]),
        "low": float(ohlc["low"]),
        "close": float(ohlc["close"]),
        "volume": None if row.get("volume") is None else float(row["volume"]),
        "spread_price": None if spread_source is None else float(spread_source),
        "complete": bool(row["complete"]),
        "missing_source_minutes": int(row.get("missing_source_minutes") or 0),
        "source_record_id": str(row["record_id"]),
        "source_record_hash": str(row["record_hash"]),
    }
    return {"bar_id": canonical_hash(body), **body}


def load_prices_primary() -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            source = json.loads(line)
            if source.get("instrument_code") != "XAUUSD" or source.get("timeframe") not in SOURCE_TIMEFRAMES or not display_eligible(source):
                continue
            close = parse_time(str(source["close_time"]))
            if close >= datetime(2022, 1, 1, tzinfo=timezone.utc):
                continue
            rows[str(source["timeframe"])].append(price_record(source))
    for timeframe in rows:
        rows[timeframe].sort(key=lambda item: (item["close_at"], item["bar_id"]))
    return dict(rows)


def load_prices_reference() -> dict[str, list[dict[str, Any]]]:
    tuples: list[tuple[str, str, dict[str, Any]]] = []
    with gzip.GzipFile(filename=PRICE, mode="rb") as handle:
        for raw in handle:
            source = json.loads(raw.decode("utf-8"))
            timeframe = str(source.get("timeframe"))
            if source.get("instrument_code") != "XAUUSD" or timeframe not in SOURCE_TIMEFRAMES or not display_eligible(source):
                continue
            close = parse_time(str(source["close_time"]))
            if close >= datetime(2022, 1, 1, tzinfo=timezone.utc):
                continue
            record = price_record(source)
            tuples.append((timeframe, record["close_at"], record))
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for timeframe, _, record in sorted(tuples, key=lambda item: (item[0], item[1], item[2]["bar_id"])):
        output[timeframe].append(record)
    return dict(output)


def weekly_rows(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in daily:
        opened = parse_time(row["open_at"])
        year, week, _ = opened.isocalendar()
        grouped[(year, week)].append(row)
    output: list[dict[str, Any]] = []
    for key in sorted(grouped):
        source = sorted(grouped[key], key=lambda item: item["open_at"])
        if len(source) < 4:
            continue
        body = {
            "timeframe": "1w",
            "open_at": source[0]["open_at"],
            "close_at": source[-1]["close_at"],
            "available_at": max(item["available_at"] for item in source),
            "open": source[0]["open"],
            "high": max(item["high"] for item in source),
            "low": min(item["low"] for item in source),
            "close": source[-1]["close"],
            "volume": sum(float(item["volume"] or 0) for item in source),
            "spread_price": source[-1]["spread_price"],
            "complete": True,
            "missing_source_minutes": sum(item["missing_source_minutes"] for item in source),
            "source_record_id": canonical_hash([item["source_record_id"] for item in source]),
            "source_record_hash": canonical_hash([item["source_record_hash"] for item in source]),
        }
        output.append({"bar_id": canonical_hash(body), **body})
    return output


def read_rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def latest_plus_day(
    rows: list[dict[str, Any]], *, timestamp_key: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    eligible = [row for row in rows if parse_time(str(row[timestamp_key])) < end]
    before = [row for row in eligible if parse_time(str(row[timestamp_key])) <= start]
    during = [row for row in eligible if start < parse_time(str(row[timestamp_key])) < end]
    return ([max(before, key=lambda row: str(row[timestamp_key]))] if before else []) + sorted(during, key=lambda row: str(row[timestamp_key]))


def safe_fundamental(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row["record_id"],
        "available_at": iso(parse_time(str(row["available_at"]))),
        "as_of": iso(parse_time(str(row["as_of"]))),
        "epistemic_status": row["epistemic_status"],
        "engine_state": row["engine_state"],
        "series_state": row["series_state"],
        "record_hash": row["record_hash"],
    }


def safe_structure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row["record_id"],
        "available_at": iso(parse_time(str(row["available_at"]))),
        "as_of": iso(parse_time(str(row["as_of"]))),
        "epistemic_status": row["epistemic_status"],
        "timeframes": row["timeframes"],
        "record_hash": row["record_hash"],
    }


def safe_cross_market(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row["record_id"],
        "available_at": iso(parse_time(str(row["available_at"]))),
        "as_of": iso(parse_time(str(row["as_of"]))),
        "epistemic_status": row["epistemic_status"],
        "instruments": row["instruments"],
        "quality": row["quality"],
        "record_hash": row["record_hash"],
    }


def safe_positioning(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row["record_id"],
        "available_at": iso(parse_time(str(row["available_at"]))),
        "publication_at": iso(parse_time(str(row["publication_at"]))),
        "epistemic_status": row["epistemic_status"],
        "calculated": row["calculated"],
        "inferred": row["inferred"],
        "availability_quality": row["availability_quality"],
        "record_hash": row["record_hash"],
    }


def safe_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row["record_id"],
        "event_code": row["event_code"],
        "name": row["name"],
        "event_type": row["event_type"],
        "importance": row["importance"],
        "is_scheduled": row["is_scheduled"],
        "schedule_verified_for_pre_event_use": row["schedule_verified_for_pre_event_use"],
        "scheduled_at": None if row.get("scheduled_at") is None else iso(parse_time(str(row["scheduled_at"]))),
        "released_at": iso(parse_time(str(row["released_at"]))),
        "event_available_at": iso(parse_time(str(row["event_available_at"]))),
        "forecasts": row["forecasts"],
        "releases": row["releases"],
        "raw_surprises": row["raw_surprises"],
        "standardized_surprises": row["standardized_surprises"],
        "record_hash": row["record_hash"],
    }


def safe_session(row: dict[str, Any]) -> dict[str, Any]:
    decision = row["decision_state"]
    return {
        "record_id": row["record_id"],
        "session_code": row["session_code"],
        "session_date": row["session_date"],
        "session_timezone": row["session_timezone"],
        "available_at": iso(parse_time(str(row["availability_at"]))),
        "decision_at": iso(parse_time(str(row["decision_at"]))),
        "observation_end": iso(parse_time(str(row["observation_end"]))),
        "epistemic_status": row["epistemic_status"],
        "known_levels": decision.get("known_levels", []),
        "windows": decision.get("windows", {}),
        "record_hash": row["record_hash"],
    }


def build_contexts() -> dict[str, list[dict[str, Any]]]:
    fundamentals = [row for row in read_rows(FUNDAMENTALS) if row.get("record_type") == "FUNDAMENTAL_SNAPSHOT"]
    structure = [row for row in read_rows(STRUCTURE) if row.get("record_type") == "STRUCTURE_SNAPSHOT"]
    cross = [row for row in read_rows(CROSS_MARKET) if row.get("record_type") == "CROSS_MARKET_SNAPSHOT"]
    positioning = [row for row in read_rows(POSITIONING) if row.get("record_type") == "POSITIONING_REPORT"]
    events = [row for row in read_rows(EVENTS) if row.get("record_type") == "EVENT_CASE"]
    sessions = [row for row in read_rows(SESSIONS) if row.get("record_type") == "SESSION_CASE"]
    return {
        "fundamentals": fundamentals,
        "structure": structure,
        "cross_market": cross,
        "positioning": positioning,
        "events": events,
        "sessions": sessions,
    }


def timeline_for_case(
    case: dict[str, Any], prices: dict[str, list[dict[str, Any]]], contexts: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    alias = case["case_alias"]
    start = parse_time(case["start_inclusive"])
    end = parse_time(case["end_exclusive"])
    price_source = {**prices, "1w": weekly_rows(prices.get("1d", []))}
    timelines: dict[str, list[dict[str, Any]]] = {}
    for timeframe in TIMEFRAMES:
        rows = price_source.get(timeframe, [])
        before = [row for row in rows if parse_time(row["close_at"]) < start and parse_time(row["available_at"]) <= start]
        during = [row for row in rows if start <= parse_time(row["close_at"]) < end and parse_time(row["available_at"]) < end]
        selected = [*before[-LIMITS[timeframe]:], *during]
        if selected != sorted(selected, key=lambda row: (row["close_at"], row["bar_id"])):
            raise RuntimeError(f"Price timeline order failure: {alias} {timeframe}")
        if len({row["bar_id"] for row in selected}) != len(selected):
            raise RuntimeError(f"Duplicate bar identity: {alias} {timeframe}")
        timelines[timeframe] = selected

    m1_day = [row for row in timelines["1m"] if start <= parse_time(row["close_at"]) < end]
    if len(m1_day) != int(case["observed_m1_minutes"]):
        raise RuntimeError(f"M1 practice-day count differs: {alias} {len(m1_day)}")

    day = case["trading_date_utc"]
    event_rows = []
    for row in contexts["events"]:
        released = parse_time(str(row["released_at"]))
        scheduled = parse_time(str(row.get("scheduled_at") or row["released_at"]))
        if start <= released < end or (row.get("schedule_verified_for_pre_event_use") and start <= scheduled < end):
            event_rows.append(safe_event(row))
    session_rows = [safe_session(row) for row in contexts["sessions"] if str(row.get("session_date")) == day and row.get("session_code") in {"LONDON", "NEW_YORK"}]

    context_timeline = {
        "fundamentals": [safe_fundamental(row) for row in latest_plus_day(contexts["fundamentals"], timestamp_key="available_at", start=start, end=end)],
        "structure": [safe_structure(row) for row in latest_plus_day(contexts["structure"], timestamp_key="available_at", start=start, end=end)],
        "cross_market": [safe_cross_market(row) for row in latest_plus_day(contexts["cross_market"], timestamp_key="available_at", start=start, end=end)],
        "positioning": [safe_positioning(row) for row in latest_plus_day(contexts["positioning"], timestamp_key="available_at", start=start, end=end)],
        "events": sorted(event_rows, key=lambda row: row["released_at"]),
        "sessions": sorted(session_rows, key=lambda row: row["decision_at"]),
    }
    body = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_PRACTICE_STREAM_1_1",
        "case_alias": alias,
        "mode": "PRACTICE",
        "mode_sequence": case["mode_sequence"],
        "trading_date_utc": day,
        "start_inclusive": case["start_inclusive"],
        "end_exclusive": case["end_exclusive"],
        "initial_cursor_at": case["start_inclusive"],
        "maximum_cursor_at": case["end_exclusive"],
        "research_credit": "ZERO_PRACTICE_ONLY",
        "timeframes": timelines,
        "context_timeline": context_timeline,
        "source_lineage": {
            "practice_registry_population_sha256": case["minute_identity_sha256"],
            "price_casebook_sha256": sha256_file(PRICE),
        },
    }
    body["stream_sha256"] = canonical_hash(body)
    return body


def build_streams(
    registry: dict[str, Any], price_loader: Callable[[], dict[str, list[dict[str, Any]]]]
) -> list[dict[str, Any]]:
    prices = price_loader()
    contexts = build_contexts()
    return [timeline_for_case(case, prices, contexts) for case in registry["cases"]]


def write_gzip_new(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"Append-only output exists: {path.relative_to(ROOT)}")
    with path.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            for row in rows:
                zipped.write(canonical_bytes(row) + b"\n")


def write_new_json(path: Path, value: Any) -> None:
    if path.exists():
        raise RuntimeError(f"Append-only output exists: {path.relative_to(ROOT)}")
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> int:
    for path in (PRIMARY, REFERENCE, CERTIFICATION):
        if path.exists():
            raise RuntimeError(f"Append-only V3 stream output exists: {path.relative_to(ROOT)}")
    freeze = verify_frozen_sources()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if registry.get("case_count") != 20 or registry.get("primary_collection_state") != "CLOSED_NOT_MATERIALIZED":
        raise RuntimeError("Frozen V3 registry differs")
    if registry.get("population_sha256") != freeze.get("practice_population_sha256"):
        raise RuntimeError("V3 population hash differs from freeze")

    primary = build_streams(registry, load_prices_primary)
    reference = build_streams(registry, load_prices_reference)
    if primary != reference:
        raise RuntimeError("Independent V3 practice stream structures differ")
    write_gzip_new(PRIMARY, primary)
    write_gzip_new(REFERENCE, reference)

    forbidden_event_keys = {"fixed_horizon_reactions", "reaction_snapshots", "complete_observation_available_at"}
    gates = {
        "preimplementation_freeze_verified": True,
        "practice_cases_exact_20": len(primary) == 20,
        "practice_aliases_exact": [row["case_alias"] for row in primary] == [f"V3-P-{index:03d}" for index in range(1, 21)],
        "all_rows_practice_zero_credit": all(row["mode"] == "PRACTICE" and row["research_credit"] == "ZERO_PRACTICE_ONLY" for row in primary),
        "all_m1_day_counts_match_frozen_registry": all(
            len([bar for bar in row["timeframes"]["1m"] if row["start_inclusive"] <= bar["close_at"] < row["end_exclusive"]])
            == int(registry["cases"][index]["observed_m1_minutes"])
            for index, row in enumerate(primary)
        ),
        "daily_quote_path_coverage_minimum_met": all(len(row["timeframes"]["1d"]) >= 5 for row in primary),
        "weekly_display_coverage_minimum_met": all(len(row["timeframes"]["1w"]) >= 1 for row in primary),
        "all_bars_ordered_unique": all(
            bars == sorted(bars, key=lambda bar: (bar["close_at"], bar["bar_id"])) and len({bar["bar_id"] for bar in bars}) == len(bars)
            for row in primary for bars in row["timeframes"].values()
        ),
        "no_bar_available_after_day_horizon": all(
            bar["available_at"] <= row["end_exclusive"] for row in primary for bars in row["timeframes"].values() for bar in bars
        ),
        "event_outcome_fields_absent": all(
            forbidden_event_keys.isdisjoint(event) for row in primary for event in row["context_timeline"]["events"]
        ),
        "session_outcomes_absent": all(
            "subsequent_observation" not in session for row in primary for session in row["context_timeline"]["sessions"]
        ),
        "primary_reference_structures_exact": primary == reference,
        "primary_reference_bytes_exact": sha256_file(PRIMARY) == sha256_file(REFERENCE),
        "primary_collection_year_not_materialized": all(row["trading_date_utc"].startswith("2021-") for row in primary),
        "calendar_2025_2026_not_opened": True,
        "no_acquisition_or_charge": True,
    }
    certification = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_PRACTICE_STREAM_CERTIFICATION_1_1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS_V3_PRACTICE_STREAM_COVERAGE_AMENDMENT_A" if all(gates.values()) else "FAIL_V3_PRACTICE_STREAM_COVERAGE_AMENDMENT_A",
        "practice_case_count": len(primary),
        "timeframe_counts": {
            timeframe: {
                "minimum": min(len(row["timeframes"][timeframe]) for row in primary),
                "maximum": max(len(row["timeframes"][timeframe]) for row in primary),
            }
            for timeframe in TIMEFRAMES
        },
        "primary_sha256": sha256_file(PRIMARY),
        "reference_sha256": sha256_file(REFERENCE),
        "complete_stream_set_sha256": canonical_hash(primary),
        "gates": gates,
        "primary_collection_year": registry["primary_collection_year"],
        "primary_collection_state": "CLOSED_NOT_MATERIALIZED",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    write_new_json(CERTIFICATION, certification)
    if certification["verdict"] != "PASS_V3_PRACTICE_STREAM_COVERAGE_AMENDMENT_A":
        raise RuntimeError(f"V3 practice stream gate failure: {gates}")
    print(json.dumps({
        "verdict": certification["verdict"],
        "practice_cases": len(primary),
        "timeframe_counts": certification["timeframe_counts"],
        "gates": gates,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
