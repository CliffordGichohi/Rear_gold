#!/usr/bin/env python3
"""Materialize sealed 2022 replay streams without rendering or reporting values."""

from __future__ import annotations

import gc
import gzip
import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator

import materialize_gold_annotated_replay_v3 as v3


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1"
FREEZE = ROOT / "research_manifests/gold_blind_codex_operator_replay_v1_prevalue_freeze.json"
REGISTRY = OUT / "population_registry.private.json"
FAILED_PRIMARY_DIR = OUT / "private_streams/primary"
FAILED_REFERENCE_DIR = OUT / "private_streams/reference"
FAILED_ATTEMPT = OUT / "materialization_attempt_1_timeout.json"
PRIMARY_DIR = OUT / "private_streams_recovery_a/primary"
REFERENCE_DIR = OUT / "private_streams_recovery_a/reference"
CERTIFICATION = OUT / "stream_materialization_certification.json"
RECOVERY_PROTOCOL = OUT / "materialization_recovery_a_protocol.json"
PRICE = ROOT / "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz"
TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")
SOURCE_TIMEFRAMES = {"1d", "4h", "1h", "15m", "5m", "1m"}
LIMITS = {"1w": 52, "1d": 260, "4h": 200, "1h": 300, "15m": 400, "5m": 600, "1m": 1500}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


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


def verify_freeze() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_BEFORE_CALENDAR_2022_VALUE_MATERIALIZATION":
        raise RuntimeError("Codex pre-value freeze differs")
    for item in [*freeze["sealed_outputs"], *freeze["source_records"]]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Frozen materialization input differs: {item['path']}")
    return freeze


def load_prices_primary() -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            source = json.loads(line)
            timeframe = str(source.get("timeframe"))
            if source.get("instrument_code") != "XAUUSD" or timeframe not in SOURCE_TIMEFRAMES or not v3.display_eligible(source):
                continue
            if parse_time(str(source["close_time"])) >= datetime(2023, 1, 1, tzinfo=timezone.utc):
                continue
            rows[timeframe].append(v3.price_record(source))
    for timeframe in rows:
        rows[timeframe].sort(key=lambda item: (item["close_at"], item["bar_id"]))
    return dict(rows)


def load_prices_reference() -> dict[str, list[dict[str, Any]]]:
    tuples: list[tuple[str, str, dict[str, Any]]] = []
    with gzip.GzipFile(filename=PRICE, mode="rb") as handle:
        for raw in handle:
            source = json.loads(raw.decode("utf-8"))
            timeframe = str(source.get("timeframe"))
            if source.get("instrument_code") != "XAUUSD" or timeframe not in SOURCE_TIMEFRAMES or not v3.display_eligible(source):
                continue
            if parse_time(str(source["close_time"])) >= datetime(2023, 1, 1, tzinfo=timezone.utc):
                continue
            record = v3.price_record(source)
            tuples.append((timeframe, record["close_at"], record))
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for timeframe, _, record in sorted(tuples, key=lambda item: (item[0], item[1], item[2]["bar_id"])):
        output[timeframe].append(record)
    return dict(output)


def timeline_for_case(
    case: dict[str, Any],
    price_source: dict[str, tuple[list[dict[str, Any]], list[datetime]]],
    contexts: dict[str, list[dict[str, Any]]],
    population_sha256: str,
) -> dict[str, Any]:
    alias = str(case["case_alias"])
    start = parse_time(case["start_inclusive"])
    end = parse_time(case["end_exclusive"])
    timelines: dict[str, list[dict[str, Any]]] = {}
    for timeframe in TIMEFRAMES:
        rows, close_times = price_source.get(timeframe, ([], []))
        start_index = bisect_left(close_times, start)
        end_index = bisect_left(close_times, end)
        before_reversed: list[dict[str, Any]] = []
        for index in range(start_index - 1, -1, -1):
            row = rows[index]
            if parse_time(row["available_at"]) <= start:
                before_reversed.append(row)
                if len(before_reversed) == LIMITS[timeframe]:
                    break
        before = list(reversed(before_reversed))
        during = [row for row in rows[start_index:end_index] if parse_time(row["available_at"]) < end]
        selected = [*before, *during]
        if selected != sorted(selected, key=lambda row: (row["close_at"], row["bar_id"])):
            raise RuntimeError(f"Price timeline ordering failed: {alias} {timeframe}")
        if len({row["bar_id"] for row in selected}) != len(selected):
            raise RuntimeError(f"Duplicate bar identity: {alias} {timeframe}")
        timelines[timeframe] = selected

    m1_day = [row for row in timelines["1m"] if start <= parse_time(row["close_at"]) < end]
    if len(m1_day) != int(case["observed_m1_minutes"]):
        raise RuntimeError(f"M1 count differs: {alias} {len(m1_day)}")

    day = str(case["trading_date_utc"])
    event_rows = []
    for row in contexts["events"]:
        released = parse_time(str(row["released_at"]))
        scheduled = parse_time(str(row.get("scheduled_at") or row["released_at"]))
        if start <= released < end or (row.get("schedule_verified_for_pre_event_use") and start <= scheduled < end):
            event_rows.append(v3.safe_event(row))
    session_rows = [
        v3.safe_session(row)
        for row in contexts["sessions"]
        if str(row.get("session_date")) == day and row.get("session_code") in {"LONDON", "NEW_YORK"}
    ]
    context_timeline = {
        "fundamentals": [v3.safe_fundamental(row) for row in v3.latest_plus_day(contexts["fundamentals"], timestamp_key="available_at", start=start, end=end)],
        "structure": [v3.safe_structure(row) for row in v3.latest_plus_day(contexts["structure"], timestamp_key="available_at", start=start, end=end)],
        "cross_market": [v3.safe_cross_market(row) for row in v3.latest_plus_day(contexts["cross_market"], timestamp_key="available_at", start=start, end=end)],
        "positioning": [v3.safe_positioning(row) for row in v3.latest_plus_day(contexts["positioning"], timestamp_key="available_at", start=start, end=end)],
        "events": sorted(event_rows, key=lambda row: row["released_at"]),
        "sessions": sorted(session_rows, key=lambda row: row["decision_at"]),
    }
    body = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PRIVATE_STREAM_1_0",
        "case_alias": alias,
        "mode": "CODEX_BLIND",
        "mode_sequence": int(case["mode_sequence"]),
        "trading_date_utc": day,
        "start_inclusive": case["start_inclusive"],
        "end_exclusive": case["end_exclusive"],
        "initial_cursor_at": case["start_inclusive"],
        "maximum_cursor_at": case["end_exclusive"],
        "research_credit": case["research_credit"],
        "timeframes": timelines,
        "context_timeline": context_timeline,
        "source_lineage": {
            "population_sha256": population_sha256,
            "minute_identity_sha256": case["minute_identity_sha256"],
            "price_casebook_sha256": sha256_file(PRICE),
        },
    }
    body["stream_sha256"] = canonical_hash(body)
    return body


def stream_rows(
    registry: dict[str, Any],
    loader: Callable[[], dict[str, list[dict[str, Any]]]],
) -> Iterator[dict[str, Any]]:
    prices = loader()
    prices["1w"] = v3.weekly_rows(prices.get("1d", []))
    price_index = {
        timeframe: (rows, [parse_time(row["close_at"]) for row in rows])
        for timeframe, rows in prices.items()
    }
    contexts = v3.build_contexts()
    for case in registry["cases"]:
        yield timeline_for_case(case, price_index, contexts, registry["population_sha256"])
    del prices, price_index, contexts
    gc.collect()


def write_streams(
    directory: Path,
    registry: dict[str, Any],
    loader: Callable[[], dict[str, list[dict[str, Any]]]],
) -> tuple[list[str], dict[str, dict[str, int]], str, list[dict[str, Any]]]:
    if directory.exists():
        raise RuntimeError(f"Append-only output exists: {directory.relative_to(ROOT)}")
    directory.mkdir(parents=True)
    row_hashes: list[str] = []
    counts = {timeframe: {"minimum": 10**9, "maximum": 0} for timeframe in TIMEFRAMES}
    complete_digest = hashlib.sha256()
    files: list[dict[str, Any]] = []
    for row in stream_rows(registry, loader):
        payload = canonical_bytes(row)
        path = directory / f"{row['case_alias']}.json.gz"
        with path.open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                zipped.write(payload + b"\n")
        row_hashes.append(row["stream_sha256"])
        complete_digest.update(len(payload).to_bytes(8, "big"))
        complete_digest.update(payload)
        for timeframe, bars in row["timeframes"].items():
            counts[timeframe]["minimum"] = min(counts[timeframe]["minimum"], len(bars))
            counts[timeframe]["maximum"] = max(counts[timeframe]["maximum"], len(bars))
        files.append({
            "case_alias": row["case_alias"],
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "stream_sha256": row["stream_sha256"],
        })
    return row_hashes, counts, complete_digest.hexdigest(), files


def write_new_json(path: Path, payload: Any) -> None:
    if path.exists():
        raise RuntimeError(f"Append-only output exists: {path.relative_to(ROOT)}")
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def seal_failed_timeout_attempt() -> dict[str, Any]:
    if FAILED_ATTEMPT.exists():
        record = json.loads(FAILED_ATTEMPT.read_text(encoding="utf-8"))
        if record.get("verdict") != "FAIL_MATERIALIZATION_ATTEMPT_1_SHELL_TIMEOUT":
            raise RuntimeError("Attempt-1 timeout record differs")
        return record
    if not FAILED_PRIMARY_DIR.is_dir() or FAILED_REFERENCE_DIR.exists() or CERTIFICATION.exists():
        raise RuntimeError("Attempt-1 timeout filesystem disposition differs")
    files = sorted(FAILED_PRIMARY_DIR.glob("*.json.gz"))
    aliases = [path.stem.removesuffix(".json") for path in files]
    expected = [f"CBR-2022-{index:03d}" for index in range(1, len(files) + 1)]
    if not files or aliases != expected:
        raise RuntimeError("Attempt-1 partial aliases are not a consecutive frozen prefix")
    artifacts = []
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            row = json.loads(handle.readline())
            if handle.readline():
                raise RuntimeError(f"Attempt-1 partial stream has multiple rows: {path.name}")
        submitted = row.pop("stream_sha256", None)
        if submitted is None or canonical_hash(row) != submitted:
            raise RuntimeError(f"Attempt-1 partial stream is structurally invalid: {path.name}")
        artifacts.append({
            "case_alias": row["case_alias"],
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "stream_sha256": submitted,
        })
    record = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_MATERIALIZATION_ATTEMPT_1_FAILURE_1_0",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "FAIL_MATERIALIZATION_ATTEMPT_1_SHELL_TIMEOUT",
        "shell_exit_code": 124,
        "shell_timeout_seconds": 120,
        "completed_primary_prefix_count": len(artifacts),
        "reference_started": False,
        "certification_written": False,
        "partial_artifacts": artifacts,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "charge_usd": 0.0,
        "disposition": "PRESERVED_IMMUTABLY_ZERO_RESEARCH_CREDIT",
    }
    write_new_json(FAILED_ATTEMPT, record)
    return record


def main() -> int:
    protocol = json.loads(RECOVERY_PROTOCOL.read_text(encoding="utf-8"))
    if (
        protocol.get("status") != "SEALED_BEFORE_RECOVERY_A_SOURCE_VALUE_ACCESS"
        or protocol.get("implementation_sha256") != sha256_file(Path(__file__).resolve())
    ):
        raise RuntimeError("Materialization Recovery A protocol or implementation differs")
    failed_attempt = seal_failed_timeout_attempt()
    for path in (PRIMARY_DIR, REFERENCE_DIR, CERTIFICATION):
        if path.exists():
            raise RuntimeError(f"Append-only stream output exists: {path.relative_to(ROOT)}")
    freeze = verify_freeze()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if registry.get("case_count") != 249 or registry.get("population_sha256") != freeze.get("population_sha256"):
        raise RuntimeError("Frozen Codex population differs")

    primary_hashes, primary_counts, primary_complete, primary_files = write_streams(PRIMARY_DIR, registry, load_prices_primary)
    reference_hashes, reference_counts, reference_complete, reference_files = write_streams(REFERENCE_DIR, registry, load_prices_reference)
    paired_files = []
    for primary_item, reference_item in zip(primary_files, reference_files, strict=True):
        if primary_item["case_alias"] != reference_item["case_alias"]:
            raise RuntimeError("Primary/reference case-file order differs")
        paired_files.append({
            "case_alias": primary_item["case_alias"],
            "primary": primary_item,
            "reference": reference_item,
            "bytes_exact": primary_item["sha256"] == reference_item["sha256"],
        })
    gates = {
        "prevalue_freeze_verified": True,
        "cases_exact_249": len(primary_hashes) == 249,
        "aliases_exact": [case["case_alias"] for case in registry["cases"]] == [f"CBR-2022-{index:03d}" for index in range(1, 250)],
        "primary_reference_row_hashes_exact": primary_hashes == reference_hashes,
        "primary_reference_counts_exact": primary_counts == reference_counts,
        "primary_reference_complete_checksums_exact": primary_complete == reference_complete,
        "primary_reference_bytes_exact": all(item["bytes_exact"] for item in paired_files),
        "calendar_2022_only": all(case["trading_date_utc"].startswith("2022-") for case in registry["cases"]),
        "calendar_2025_2026_locked": True,
        "outcomes_not_joined": True,
        "no_acquisition_or_charge": True,
    }
    certification = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_STREAM_CERTIFICATION_1_0",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION" if all(gates.values()) else "FAIL_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION",
        "case_count": len(primary_hashes),
        "population_sha256": registry["population_sha256"],
        "primary_file_manifest_sha256": canonical_hash(primary_files),
        "reference_file_manifest_sha256": canonical_hash(reference_files),
        "complete_stream_set_sha256": primary_complete,
        "row_hash_sequence_sha256": canonical_hash(primary_hashes),
        "case_files": paired_files,
        "timeframe_counts": primary_counts,
        "gates": gates,
        "recovery": {
            "amendment": "MATERIALIZATION_RECOVERY_A",
            "failed_attempt_record": {
                "path": FAILED_ATTEMPT.relative_to(ROOT).as_posix(),
                "bytes": FAILED_ATTEMPT.stat().st_size,
                "sha256": sha256_file(FAILED_ATTEMPT),
                "verdict": failed_attempt["verdict"],
            },
            "research_definitions_changed": False,
            "optimization": "BINARY_SEARCH_CLOSE_TIME_INDEX_ONLY",
        },
        "market_values_reported": False,
        "outcomes_accessed": False,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "charge_usd": 0.0,
    }
    write_new_json(CERTIFICATION, certification)
    if certification["verdict"] != "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION":
        raise RuntimeError(f"Private stream materialization failed: {gates}")
    print(json.dumps({
        "verdict": certification["verdict"],
        "case_count": certification["case_count"],
        "timeframe_counts": primary_counts,
        "primary_bytes": sum(item["bytes"] for item in primary_files),
        "reference_bytes": sum(item["bytes"] for item in reference_files),
        "primary_reference_bytes_exact": gates["primary_reference_bytes_exact"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
