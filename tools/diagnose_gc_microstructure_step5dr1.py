#!/usr/bin/env python3
"""Run the sealed Step 5D-R1 metadata-only outcome coverage diagnostic."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "research_manifests" / "gc_microstructure_step_5dr1_protocol_v01.json"
FREEZE_PATH = ROOT / "research_manifests" / "gc_microstructure_step_5dr1_freeze_v01.json"
PRICE_PATH = ROOT / "research_artifacts" / "gold_casebook_v01" / "price_bars.jsonl.gz"
SESSION_PATH = ROOT / "research_artifacts" / "gold_casebook_v01" / "sessions.jsonl.gz"
FAILURE_PATH = ROOT / "research_artifacts" / "gc_microstructure_step5d_v01" / "outcome_opening_failure.json"
OUTPUT_DIR = ROOT / "research_artifacts" / "gc_microstructure_step5dr1_v01"
REPORT_PATH = ROOT / "GC_MICROSTRUCTURE_STEP_5D_R1_REPORT.md"

EXPECTED_PROTOCOL_SHA = "18c4637970505d6b2f58e74e7cc4f8bb862bf50e1336aa6fd62057eaac3536ac"
EXPECTED_FREEZE_SHA = "3d2602f6c2efb8c2146835c8b877727d7a0a4bc82aa66d5617e08be18fc5b34d"
EXPECTED_FAILURE_SHA = "44f32d8da4e58d19f1f4e2d2a9fccace63457f75fa58370e119d0b5273090805"
EXPECTED_PRICE_SHA = "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"
EXPECTED_SESSION_SHA = "2695a2c0b9e8f41fcbf64c9f388e8883ebf7e1f0b3b09b90fb3a60ba7e64966a"
EXPECTED_FREEZE_RECEIPT = "5390d6267f28254b0d8a0277f98b64318100c0aaa9c0de08e9be4d2c72cd71f1"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SCALAR = rb'("(?:\\.|[^"\\])*"|true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)'
REGEX_CACHE: dict[str, re.Pattern[bytes]] = {}
IDENTITY_RE = re.compile(
    rb'"record_hash":' + SCALAR + rb',"record_id":' + SCALAR + rb',"record_type":' + SCALAR
)
SESSION_KEY_RE = re.compile(
    rb'"session_code":' + SCALAR + rb',"session_date":' + SCALAR + rb',"session_timezone":' + SCALAR
)
DATA_QUALITY_RE = re.compile(rb'"data_quality":\{([^{}]*)\}')

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
TOKYO = ZoneInfo("Asia/Tokyo")
SESSION_ZONES = {"LONDON": LONDON, "NEW_YORK": NEW_YORK}
WINDOW_ZONES = {"ASIA": TOKYO, "LONDON": LONDON, "NEW_YORK": NEW_YORK}
WINDOW_CLOCKS = {
    "ASIA": (time(10, 5), time(16), 71),
    "LONDON": (time(8), time(12), 48),
    "NEW_YORK": (time(8), time(12), 48),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"Expected timestamp string, received {type(value).__name__}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Naive timestamp")
    return parsed.astimezone(UTC)


def normalize_timestamp(value: Any) -> str | None:
    try:
        return iso_z(parse_timestamp(value))
    except (TypeError, ValueError):
        return None


def expected_range(day: date, start: time, end: time, zone: ZoneInfo, step_minutes: int) -> list[str]:
    cursor = datetime.combine(day, start, tzinfo=zone)
    finish = datetime.combine(day, end, tzinfo=zone)
    output: list[str] = []
    while cursor < finish:
        output.append(iso_z(cursor))
        cursor += timedelta(minutes=step_minutes)
    return output


def scalar_pattern(name: str) -> re.Pattern[bytes]:
    if name not in REGEX_CACHE:
        REGEX_CACHE[name] = re.compile(rb'"' + re.escape(name.encode("ascii")) + rb'":' + SCALAR)
    return REGEX_CACHE[name]


def decode_allowed_scalar(raw: bytes | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


def regex_scalar(raw: bytes, name: str) -> Any:
    match = scalar_pattern(name).search(raw)
    return decode_allowed_scalar(match.group(1)) if match else None


def primary_price_projection(raw: bytes, target: set[tuple[str, str]]) -> dict[str, Any] | None:
    timeframe = regex_scalar(raw, "timeframe")
    open_time = normalize_timestamp(regex_scalar(raw, "open_time"))
    if not isinstance(timeframe, str) or open_time is None or (timeframe, open_time) not in target:
        return None
    identity = IDENTITY_RE.search(raw)
    if identity is None:
        record_hash = record_id = record_type = None
    else:
        record_hash, record_id, record_type = (decode_allowed_scalar(identity.group(i)) for i in range(1, 4))
    return {
        "record_type": record_type,
        "record_id": record_id,
        "record_hash": record_hash,
        "provider_code": regex_scalar(raw, "provider_code"),
        "instrument_code": regex_scalar(raw, "instrument_code"),
        "timeframe": timeframe,
        "open_time": open_time,
        "close_time": normalize_timestamp(regex_scalar(raw, "close_time")),
        "available_at": normalize_timestamp(regex_scalar(raw, "available_at")),
        "ingested_at": normalize_timestamp(regex_scalar(raw, "ingested_at")),
        "complete": regex_scalar(raw, "complete"),
        "missing_source_minutes": regex_scalar(raw, "missing_source_minutes"),
        "epistemic_status": regex_scalar(raw, "epistemic_status"),
        "calculation_version": regex_scalar(raw, "calculation_version"),
        "source": {
            "batch_id": regex_scalar(raw, "batch_id"),
            "source_record_key": regex_scalar(raw, "source_record_key"),
            "source_count": regex_scalar(raw, "source_count"),
            "source_hash": regex_scalar(raw, "source_hash"),
            "first_source_open": normalize_timestamp(regex_scalar(raw, "first_source_open")),
            "last_source_open": normalize_timestamp(regex_scalar(raw, "last_source_open")),
            "source_batch_count": regex_scalar(raw, "source_batch_count"),
        },
    }


def primary_session_projection(raw: bytes, target_keys: set[tuple[str, str]]) -> dict[str, Any] | None:
    key_match = SESSION_KEY_RE.search(raw)
    if key_match is None:
        return None
    session_code, session_date, session_timezone = (
        decode_allowed_scalar(key_match.group(i)) for i in range(1, 4)
    )
    if (str(session_date), str(session_code)) not in target_keys:
        return None
    identity = IDENTITY_RE.search(raw)
    if identity is None:
        record_hash = record_id = record_type = None
    else:
        record_hash, record_id, record_type = (decode_allowed_scalar(identity.group(i)) for i in range(1, 4))
    quality_match = DATA_QUALITY_RE.search(raw)
    quality_raw = quality_match.group(1) if quality_match else b""
    return {
        "record_type": record_type,
        "record_id": record_id,
        "record_hash": record_hash,
        "session_date": session_date,
        "session_code": session_code,
        "session_timezone": session_timezone,
        "decision_at": normalize_timestamp(regex_scalar(raw, "decision_at")),
        "observation_end": normalize_timestamp(regex_scalar(raw, "observation_end")),
        "availability_at": normalize_timestamp(regex_scalar(raw, "availability_at")),
        "data_quality": {
            "status": regex_scalar(quality_raw, "status"),
            "five_minute_bar_count": regex_scalar(quality_raw, "five_minute_bar_count"),
            "one_minute_bar_count_implied": regex_scalar(quality_raw, "one_minute_bar_count_implied"),
        },
    }


def skip_ws(raw: bytes, index: int) -> int:
    while index < len(raw) and raw[index] in b" \t\r\n":
        index += 1
    return index


def string_end(raw: bytes, index: int) -> int:
    if index >= len(raw) or raw[index] != 34:
        raise ValueError("Expected JSON string")
    index += 1
    while index < len(raw):
        if raw[index] == 92:
            index += 2
            continue
        if raw[index] == 34:
            return index + 1
        index += 1
    raise ValueError("Unterminated JSON string")


def value_end(raw: bytes, index: int) -> int:
    index = skip_ws(raw, index)
    if index >= len(raw):
        raise ValueError("Missing JSON value")
    if raw[index] == 34:
        return string_end(raw, index)
    if raw[index] in (91, 123):
        stack = [raw[index]]
        index += 1
        while index < len(raw) and stack:
            byte = raw[index]
            if byte == 34:
                index = string_end(raw, index)
                continue
            if byte in (91, 123):
                stack.append(byte)
            elif byte == 93:
                if stack[-1] != 91:
                    raise ValueError("Mismatched JSON array")
                stack.pop()
            elif byte == 125:
                if stack[-1] != 123:
                    raise ValueError("Mismatched JSON object")
                stack.pop()
            index += 1
        if stack:
            raise ValueError("Unterminated JSON composite")
        return index
    while index < len(raw) and raw[index] not in b",}] \t\r\n":
        index += 1
    return index


def object_projection(raw: bytes, wanted: set[str]) -> dict[str, bytes]:
    index = skip_ws(raw, 0)
    if index >= len(raw) or raw[index] != 123:
        raise ValueError("Expected JSON object")
    index += 1
    output: dict[str, bytes] = {}
    while True:
        index = skip_ws(raw, index)
        if index < len(raw) and raw[index] == 125:
            return output
        key_finish = string_end(raw, index)
        key = json.loads(raw[index:key_finish].decode("utf-8"))
        index = skip_ws(raw, key_finish)
        if index >= len(raw) or raw[index] != 58:
            raise ValueError("Missing JSON colon")
        start = skip_ws(raw, index + 1)
        finish = value_end(raw, start)
        if key in wanted:
            output[str(key)] = raw[start:finish]
        index = skip_ws(raw, finish)
        if index < len(raw) and raw[index] == 44:
            index += 1
            continue
        if index < len(raw) and raw[index] == 125:
            return output
        raise ValueError("Malformed JSON object")


def projected_scalar(fields: Mapping[str, bytes], name: str) -> Any:
    return decode_allowed_scalar(fields.get(name))


def quick_scalar(raw: bytes, name: str) -> Any:
    token = b'"' + name.encode("ascii") + b'":'
    start = raw.find(token)
    if start < 0:
        return None
    start = skip_ws(raw, start + len(token))
    finish = value_end(raw, start)
    return decode_allowed_scalar(raw[start:finish])


PRICE_TOP_FIELDS = {
    "record_type", "record_id", "record_hash", "provider_code", "instrument_code",
    "timeframe", "open_time", "close_time", "available_at", "ingested_at", "complete",
    "missing_source_minutes", "epistemic_status", "calculation_version", "source",
}
PRICE_SOURCE_FIELDS = {
    "batch_id", "source_record_key", "source_count", "source_hash", "first_source_open",
    "last_source_open", "source_batch_count",
}
SESSION_TOP_FIELDS = {
    "record_type", "record_id", "record_hash", "session_date", "session_code",
    "session_timezone", "decision_at", "observation_end", "availability_at", "data_quality",
}
QUALITY_FIELDS = {"status", "five_minute_bar_count", "one_minute_bar_count_implied"}


def reference_price_projection(raw: bytes, target: set[tuple[str, str]]) -> dict[str, Any] | None:
    timeframe = quick_scalar(raw, "timeframe")
    open_time = normalize_timestamp(quick_scalar(raw, "open_time"))
    if not isinstance(timeframe, str) or open_time is None or (timeframe, open_time) not in target:
        return None
    top = object_projection(raw, PRICE_TOP_FIELDS)
    source_raw = top.get("source")
    source = object_projection(source_raw, PRICE_SOURCE_FIELDS) if source_raw is not None else {}
    return {
        "record_type": projected_scalar(top, "record_type"),
        "record_id": projected_scalar(top, "record_id"),
        "record_hash": projected_scalar(top, "record_hash"),
        "provider_code": projected_scalar(top, "provider_code"),
        "instrument_code": projected_scalar(top, "instrument_code"),
        "timeframe": projected_scalar(top, "timeframe"),
        "open_time": normalize_timestamp(projected_scalar(top, "open_time")),
        "close_time": normalize_timestamp(projected_scalar(top, "close_time")),
        "available_at": normalize_timestamp(projected_scalar(top, "available_at")),
        "ingested_at": normalize_timestamp(projected_scalar(top, "ingested_at")),
        "complete": projected_scalar(top, "complete"),
        "missing_source_minutes": projected_scalar(top, "missing_source_minutes"),
        "epistemic_status": projected_scalar(top, "epistemic_status"),
        "calculation_version": projected_scalar(top, "calculation_version"),
        "source": {
            "batch_id": projected_scalar(source, "batch_id"),
            "source_record_key": projected_scalar(source, "source_record_key"),
            "source_count": projected_scalar(source, "source_count"),
            "source_hash": projected_scalar(source, "source_hash"),
            "first_source_open": normalize_timestamp(projected_scalar(source, "first_source_open")),
            "last_source_open": normalize_timestamp(projected_scalar(source, "last_source_open")),
            "source_batch_count": projected_scalar(source, "source_batch_count"),
        },
    }


def reference_session_projection(raw: bytes, target_keys: set[tuple[str, str]]) -> dict[str, Any] | None:
    if not any(day.encode("ascii") in raw for day, _ in target_keys):
        return None
    top = object_projection(raw, SESSION_TOP_FIELDS)
    session_date = projected_scalar(top, "session_date")
    session_code = projected_scalar(top, "session_code")
    if (str(session_date), str(session_code)) not in target_keys:
        return None
    quality_raw = top.get("data_quality")
    quality = object_projection(quality_raw, QUALITY_FIELDS) if quality_raw is not None else {}
    return {
        "record_type": projected_scalar(top, "record_type"),
        "record_id": projected_scalar(top, "record_id"),
        "record_hash": projected_scalar(top, "record_hash"),
        "session_date": session_date,
        "session_code": session_code,
        "session_timezone": projected_scalar(top, "session_timezone"),
        "decision_at": normalize_timestamp(projected_scalar(top, "decision_at")),
        "observation_end": normalize_timestamp(projected_scalar(top, "observation_end")),
        "availability_at": normalize_timestamp(projected_scalar(top, "availability_at")),
        "data_quality": {
            "status": projected_scalar(quality, "status"),
            "five_minute_bar_count": projected_scalar(quality, "five_minute_bar_count"),
            "one_minute_bar_count_implied": projected_scalar(quality, "one_minute_bar_count_implied"),
        },
    }


def make_targets(keys: list[dict[str, str]]) -> tuple[dict[str, dict[str, Any]], set[tuple[str, str]]]:
    specs: dict[str, dict[str, Any]] = {}
    target: set[tuple[str, str]] = set()
    for item in keys:
        day = date.fromisoformat(item["session_date"])
        code = item["session_code"]
        key = f"{day.isoformat()}|{code}"
        zone = SESSION_ZONES[code]
        outcome = expected_range(day, time(8, 1), time(12), zone, 1)
        windows: dict[str, list[str]] = {}
        for window_code, (start, end, expected) in WINDOW_CLOCKS.items():
            values = expected_range(day, start, end, WINDOW_ZONES[window_code], 5)
            if len(values) != expected:
                raise AssertionError((window_code, day, len(values)))
            windows[window_code] = values
        if len(outcome) != 239:
            raise AssertionError((key, len(outcome)))
        specs[key] = {
            "session_date": day.isoformat(),
            "session_code": code,
            "session_timezone": zone.key,
            "decision_at": iso_z(datetime.combine(day, time(8), tzinfo=zone)),
            "observation_end": iso_z(datetime.combine(day, time(12), tzinfo=zone)),
            "outcome": outcome,
            "windows": windows,
        }
        target.update(("1m", value) for value in outcome)
        for values in windows.values():
            target.update(("5m", value) for value in values)
    return specs, target


def scan_sources(
    *,
    price_parser: Callable[[bytes, set[tuple[str, str]]], dict[str, Any] | None],
    session_parser: Callable[[bytes, set[tuple[str, str]]], dict[str, Any] | None],
    target: set[tuple[str, str]],
    target_keys: set[tuple[str, str]],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]], dict[str, Any]]:
    prices: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    sessions: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    price_rows = relevant_price_rows = session_rows = relevant_session_rows = 0
    with gzip.open(PRICE_PATH, "rb") as handle:
        for raw in handle:
            price_rows += 1
            projected = price_parser(raw.rstrip(b"\r\n"), target)
            if projected is None:
                continue
            relevant_price_rows += 1
            prices[(str(projected["timeframe"]), str(projected["open_time"]))].append(projected)
    with gzip.open(SESSION_PATH, "rb") as handle:
        for raw in handle:
            session_rows += 1
            projected = session_parser(raw.rstrip(b"\r\n"), target_keys)
            if projected is None:
                continue
            relevant_session_rows += 1
            sessions[(str(projected["session_date"]), str(projected["session_code"]))].append(projected)
    diagnostics = {
        "source_open_counts": {"price_bars": 1, "sessions": 1},
        "source_row_counts": {"price_bars": price_rows, "sessions": session_rows},
        "retained_metadata_rows": {"price_bars": relevant_price_rows, "sessions": relevant_session_rows},
        "forbidden_value_fields_deserialized": 0,
        "market_or_outcome_values_accessed": False,
    }
    return dict(prices), dict(sessions), diagnostics


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def valid_hash(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def validate_price_record(record: Mapping[str, Any], expected_open: str, timeframe: str) -> list[str]:
    errors: list[str] = []
    expected_minutes = 1 if timeframe == "1m" else 5
    if record.get("record_type") != "PRICE_BAR":
        errors.append("RECORD_TYPE")
    if record.get("provider_code") != "IC_MARKETS_MT5":
        errors.append("PROVIDER")
    if record.get("instrument_code") != "XAUUSD":
        errors.append("INSTRUMENT")
    if record.get("timeframe") != timeframe:
        errors.append("TIMEFRAME")
    if record.get("open_time") != expected_open:
        errors.append("OPEN_TIME")
    expected_close = iso_z(parse_timestamp(expected_open) + timedelta(minutes=expected_minutes))
    if record.get("close_time") != expected_close:
        errors.append("CLOSE_TIME")
    if record.get("complete") is not True:
        errors.append("COMPLETE")
    if record.get("missing_source_minutes") != 0:
        errors.append("MISSING_SOURCE_MINUTES")
    available = record.get("available_at")
    if available is None:
        errors.append("AVAILABLE_AT")
    else:
        try:
            if parse_timestamp(available) > parse_timestamp(expected_close):
                errors.append("AVAILABLE_AFTER_CLOSE")
        except (TypeError, ValueError):
            errors.append("AVAILABLE_AT")
    if not nonempty(record.get("record_id")):
        errors.append("RECORD_ID")
    if not valid_hash(record.get("record_hash")):
        errors.append("RECORD_HASH")
    source = record.get("source") if isinstance(record.get("source"), Mapping) else {}
    if not valid_hash(source.get("source_hash")):
        errors.append("SOURCE_HASH")
    if timeframe == "1m":
        if not nonempty(source.get("batch_id")):
            errors.append("BATCH_ID")
        if not nonempty(source.get("source_record_key")):
            errors.append("SOURCE_RECORD_KEY")
        if source.get("source_count") != 1:
            errors.append("SOURCE_COUNT")
    else:
        if source.get("source_count") != 5:
            errors.append("SOURCE_COUNT")
        if source.get("first_source_open") != expected_open:
            errors.append("FIRST_SOURCE_OPEN")
        expected_last = iso_z(parse_timestamp(expected_open) + timedelta(minutes=4))
        if source.get("last_source_open") != expected_last:
            errors.append("LAST_SOURCE_OPEN")
    return sorted(set(errors))


def evaluate_bars(
    records: Mapping[tuple[str, str], list[dict[str, Any]]],
    expected: list[str],
    timeframe: str,
) -> dict[str, Any]:
    missing: list[str] = []
    duplicates: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    valid_count = 0
    builder_membership_count = 0
    observed_emissions = 0
    for timestamp in expected:
        rows = records.get((timeframe, timestamp), [])
        observed_emissions += len(rows)
        if not rows:
            missing.append(timestamp)
            continue
        if len(rows) > 1:
            duplicates.append({"open_time": timestamp, "emissions": len(rows)})
        row_errors: list[list[str]] = [validate_price_record(row, timestamp, timeframe) for row in rows]
        if len(rows) == 1 and not row_errors[0]:
            valid_count += 1
        else:
            invalid.append({
                "open_time": timestamp,
                "emissions": len(rows),
                "error_codes": sorted({code for values in row_errors for code in values}),
            })
        if len(rows) == 1:
            row = rows[0]
            expected_close = iso_z(parse_timestamp(timestamp) + timedelta(minutes=1 if timeframe == "1m" else 5))
            if row.get("record_type") == "PRICE_BAR" and row.get("open_time") == timestamp and row.get("close_time") == expected_close:
                builder_membership_count += 1
    expected_count = len(expected)
    return {
        "expected_timestamp_count": expected_count,
        "observed_emission_count": observed_emissions,
        "observed_unique_timestamp_count": expected_count - len(missing),
        "metadata_eligible_timestamp_count": valid_count,
        "missing_timestamp_count": len(missing),
        "missing_timestamps": missing,
        "duplicate_timestamp_count": len(duplicates),
        "duplicate_timestamps": duplicates,
        "metadata_ineligible_timestamp_count": len(invalid),
        "metadata_ineligible_timestamps": invalid,
        "builder_membership_timestamp_count": builder_membership_count,
        "builder_membership_pass": builder_membership_count == expected_count,
        "metadata_integrity_pass": valid_count == expected_count,
    }


def validate_session_record(record: Mapping[str, Any], spec: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("record_type") != "SESSION_CASE":
        errors.append("RECORD_TYPE")
    for field in ("session_date", "session_code", "session_timezone", "decision_at", "observation_end"):
        if record.get(field) != spec.get(field):
            errors.append(field.upper())
    if record.get("availability_at") != spec.get("decision_at"):
        errors.append("AVAILABILITY_AT")
    if not nonempty(record.get("record_id")):
        errors.append("RECORD_ID")
    if not valid_hash(record.get("record_hash")):
        errors.append("RECORD_HASH")
    return sorted(set(errors))


def classify_key(
    *,
    one_minute: Mapping[str, Any],
    builder_reproduction: str,
    documented_unavailable: bool,
) -> str:
    if builder_reproduction.startswith("CONTRADICTION"):
        return "UNRESOLVED"
    if documented_unavailable:
        return "DOCUMENTED_UNAVAILABLE"
    if one_minute["metadata_integrity_pass"]:
        return "RECOVERABLE_EXISTING_SEALED_SOURCE"
    return "RECOVERABLE_TARGETED_MT5_REFRESH"


def evaluate(
    specs: Mapping[str, Mapping[str, Any]],
    prices: Mapping[tuple[str, str], list[dict[str, Any]]],
    sessions: Mapping[tuple[str, str], list[dict[str, Any]]],
    scan_diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for key in sorted(specs):
        spec = specs[key]
        outcome = evaluate_bars(prices, list(spec["outcome"]), "1m")
        windows = {
            code: evaluate_bars(prices, list(values), "5m")
            for code, values in spec["windows"].items()
        }
        required_windows = ["ASIA", "LONDON"] + (["NEW_YORK"] if spec["session_code"] == "NEW_YORK" else [])
        # The V3 casebook builder receives only `fact.complete` five-minute
        # bars.  Therefore exact timestamp presence alone is insufficient:
        # the complete/lineage metadata gate must pass before membership.
        predicted_emission = all(windows[code]["metadata_integrity_pass"] for code in required_windows)
        session_key = (str(spec["session_date"]), str(spec["session_code"]))
        session_rows = sessions.get(session_key, [])
        session_errors = [validate_session_record(row, spec) for row in session_rows]
        actual_emission = len(session_rows) == 1 and not session_errors[0]
        if len(session_rows) > 1 or (session_rows and session_errors[0]):
            builder_reproduction = "CONTRADICTION_INVALID_OR_DUPLICATE_SESSION_RECORD"
        elif predicted_emission != actual_emission:
            builder_reproduction = "CONTRADICTION_PREDICTED_EMISSION_MISMATCH"
        else:
            builder_reproduction = "MATCH_PRESENT" if actual_emission else "MATCH_EXCLUDED"
        exclusions = [
            {
                "window": code,
                "reason": "INCOMPLETE_OR_MISSING_EXACT_5M_SOURCE",
                "missing_timestamp_count": windows[code]["missing_timestamp_count"],
                "duplicate_timestamp_count": windows[code]["duplicate_timestamp_count"],
                "metadata_ineligible_timestamp_count": windows[code]["metadata_ineligible_timestamp_count"],
            }
            for code in required_windows
            if not windows[code]["metadata_integrity_pass"]
        ]
        documented_unavailable = False
        holiday = {
            "weekday": date.fromisoformat(str(spec["session_date"])).strftime("%A").upper(),
            "sealed_official_full_closure": documented_unavailable,
            "status": "NO_DOCUMENTED_FULL_CLOSURE",
            "required_window_has_sealed_timestamp_metadata": outcome["observed_emission_count"] > 0,
        }
        classification = classify_key(
            one_minute=outcome,
            builder_reproduction=builder_reproduction,
            documented_unavailable=documented_unavailable,
        )
        results.append({
            "session_date": spec["session_date"],
            "session_code": spec["session_code"],
            "session_timezone": spec["session_timezone"],
            "decision_at": spec["decision_at"],
            "observation_end": spec["observation_end"],
            "session_record": {
                "emission_count": len(session_rows),
                "valid_emission": actual_emission,
                "metadata_error_codes": sorted({code for values in session_errors for code in values}),
            },
            "one_minute_outcome_coverage": outcome,
            "five_minute_case_builder_windows": windows,
            "exact_v3_case_builder": {
                "required_windows": required_windows,
                "predicted_emission": predicted_emission,
                "actual_valid_emission": actual_emission,
                "reproduction": builder_reproduction,
                "exclusion_reasons": exclusions,
            },
            "dst_conversion": {
                "iana_timezone": spec["session_timezone"],
                "utc_offset_at_decision_seconds": int(
                    datetime.combine(
                        date.fromisoformat(str(spec["session_date"])), time(8), tzinfo=SESSION_ZONES[str(spec["session_code"])]
                    ).utcoffset().total_seconds()
                ),
                "status": "IANA_DERIVED",
            },
            "holiday": holiday,
            "source_lineage": {
                "artifact": "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz",
                "artifact_sha256": EXPECTED_PRICE_SHA,
                "record_hash_contents_recomputed": False,
                "reason_not_recomputed": "Would require forbidden OHLC values",
                "structural_lineage_gate": "PASS" if outcome["metadata_integrity_pass"] else "PARTIAL_OR_FAILED",
            },
            "classification": classification,
        })
    counts = Counter(item["classification"] for item in results)
    currently_recoverable = counts["RECOVERABLE_EXISTING_SEALED_SOURCE"]
    current_constructible = 358 + currently_recoverable
    return {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_DIAGNOSTIC_RESULT_V0_1",
        "scope": {
            "missing_keys_audited": len(results),
            "previously_found_outcomes_reopened": 0,
            "required_nonholiday_outcomes": 374,
            "previously_found_outcomes": 358,
            "year_2025_or_2026_values_accessed": False,
        },
        "source_scan": dict(scan_diagnostics),
        "keys": results,
        "classification_counts": dict(sorted(counts.items())),
        "coverage_determination": {
            "currently_constructible_nonholiday_outcomes": current_constructible,
            "required_nonholiday_outcomes": 374,
            "all_374_constructible_from_existing_sealed_source": current_constructible == 374,
            "unchanged_neutral_outcome_definition": True,
        },
    }


def recommendation_for(result: Mapping[str, Any]) -> dict[str, Any] | None:
    counts = Counter(result["classification_counts"])
    if counts["UNRESOLVED"] or counts["GENUINE_SOURCE_GAP"]:
        return {
            "code": "SEPARATE_SOURCE_RESOLUTION_PROTOCOL",
            "bounded_path": "Do not restart research until a separately authorized source-resolution protocol resolves the affected keys.",
            "implemented": False,
        }
    if counts["RECOVERABLE_TARGETED_MT5_REFRESH"]:
        keys = [
            {"session_date": item["session_date"], "session_code": item["session_code"]}
            for item in result["keys"]
            if item["classification"] == "RECOVERABLE_TARGETED_MT5_REFRESH"
        ]
        return {
            "code": "TARGETED_IC_MARKETS_MT5_REFRESH_ONLY",
            "bounded_path": "Refresh only the deficient one-minute IC Markets MT5 windows, seal the refreshed source, and repeat coverage certification before any outcome join.",
            "affected_keys": keys,
            "implemented": False,
        }
    if counts["RECOVERABLE_EXISTING_SEALED_SOURCE"]:
        return {
            "code": "SEALED_ONE_MINUTE_RECOVERY_AMENDMENT",
            "bounded_path": "Authorize a pre-value recovery amendment using only existing sealed one-minute rows and the unchanged neutral-outcome formula.",
            "implemented": False,
        }
    return None


def render_report(
    result: Mapping[str, Any],
    *,
    reproduction_pass: bool,
    recommendation: Mapping[str, Any] | None,
    final_status: str,
) -> str:
    coverage = result["coverage_determination"]
    lines = [
        "# GC Microstructure Step 5D-R1 Report",
        "",
        f"Formal status: `{final_status}`",
        "",
        "This was a metadata-only coverage diagnostic. No OHLC, displacement, direction, return, outcome, 2025/2026 value, signal, trade, or PnL field was accessed.",
        "",
        "## Verdict",
        "",
        f"- Independent reproduction: `{'PASS' if reproduction_pass else 'FAIL'}`",
        f"- Existing sealed source can currently construct all 374 non-holiday outcomes: `{str(coverage['all_374_constructible_from_existing_sealed_source']).upper()}`",
        f"- Constructible now: `{coverage['currently_constructible_nonholiday_outcomes']} / 374`",
        f"- Classification counts: `{json.dumps(result['classification_counts'], sort_keys=True)}`",
        "- Step 5D remains `FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE`; no Stage-1 or Stage-2 test was run.",
        "",
        "## Missing-key audit",
        "",
        "| Date | Session | 1m valid / 239 | Missing | Ineligible | V3 builder exclusion | Classification |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for item in result["keys"]:
        one = item["one_minute_outcome_coverage"]
        exclusions = item["exact_v3_case_builder"]["exclusion_reasons"]
        exclusion_text = ", ".join(
            f"{entry['window']}({entry['missing_timestamp_count']} missing, "
            f"{entry['metadata_ineligible_timestamp_count']} ineligible)" for entry in exclusions
        ) or item["exact_v3_case_builder"]["reproduction"]
        lines.append(
            f"| {item['session_date']} | {item['session_code']} | {one['metadata_eligible_timestamp_count']} | "
            f"{one['missing_timestamp_count']} | {one['metadata_ineligible_timestamp_count']} | {exclusion_text} | "
            f"{item['classification']} |"
        )
    lines.extend([
        "",
        "## Bounded recommendation",
        "",
        (f"`{recommendation['code']}` — {recommendation['bounded_path']}" if recommendation else "None."),
        "",
        "The recommendation was not implemented. All prior artifacts and verdicts remain unchanged.",
        "",
    ])
    return "\n".join(lines)


def verify_bound_inputs(protocol: Mapping[str, Any], freeze: Mapping[str, Any]) -> None:
    checks = {
        PROTOCOL_PATH: EXPECTED_PROTOCOL_SHA,
        FREEZE_PATH: EXPECTED_FREEZE_SHA,
        FAILURE_PATH: EXPECTED_FAILURE_SHA,
        PRICE_PATH: EXPECTED_PRICE_SHA,
        SESSION_PATH: EXPECTED_SESSION_SHA,
    }
    for path, expected in checks.items():
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Bound input changed: {path} {actual}")
    if freeze.get("freeze_receipt") != EXPECTED_FREEZE_RECEIPT:
        raise ValueError("Freeze receipt changed")
    if protocol.get("status") != "FROZEN_BEFORE_ROW_LEVEL_SOURCE_METADATA_ACCESS":
        raise ValueError("Protocol not frozen")


def main() -> None:
    if OUTPUT_DIR.exists() or REPORT_PATH.exists():
        raise FileExistsError("Step 5D-R1 output already exists")
    protocol = load_json(PROTOCOL_PATH)
    freeze = load_json(FREEZE_PATH)
    verify_bound_inputs(protocol, freeze)
    failure = load_json(FAILURE_PATH)
    if failure.get("status") != "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE" or failure.get("source_stream_open_count") != 1:
        raise ValueError("Step 5D failure or single-opening record changed")
    keys = sorted(
        ({"session_date": str(item["session_date"]), "session_code": str(item["session_code"])} for item in failure["missing_keys"]),
        key=lambda item: (item["session_date"], item["session_code"]),
    )
    if keys != protocol["authority"]["authorized_keys"]:
        raise ValueError("Authorized missing-key set changed")
    specs, target = make_targets(keys)
    target_keys = {(item["session_date"], item["session_code"]) for item in keys}

    primary_prices, primary_sessions, primary_scan = scan_sources(
        price_parser=primary_price_projection,
        session_parser=primary_session_projection,
        target=target,
        target_keys=target_keys,
    )
    primary_result = evaluate(specs, primary_prices, primary_sessions, primary_scan)
    reference_prices, reference_sessions, reference_scan = scan_sources(
        price_parser=reference_price_projection,
        session_parser=reference_session_projection,
        target=target,
        target_keys=target_keys,
    )
    reference_result = evaluate(specs, reference_prices, reference_sessions, reference_scan)
    primary_checksum = canonical_hash(primary_result)
    reference_checksum = canonical_hash(reference_result)
    reproduction_pass = primary_result == reference_result and primary_checksum == reference_checksum
    recommendation = recommendation_for(primary_result) if reproduction_pass else {
        "code": "SEPARATE_SOURCE_RESOLUTION_PROTOCOL",
        "bounded_path": "Independent metadata projections disagree; authorize no recovery until separately resolved.",
        "implemented": False,
    }
    status = (
        "PASS_STEP_5D_R1_DIAGNOSTIC_REPRODUCTION"
        if reproduction_pass
        else "FAIL_STEP_5D_R1_DIAGNOSTIC_REPRODUCTION"
    )

    staging = OUTPUT_DIR.with_name(OUTPUT_DIR.name + ".building")
    if staging.exists():
        raise FileExistsError(staging)
    staging.mkdir(parents=True)
    primary_document = {
        "implementation": "PRIMARY_BYTE_REGEX_METADATA_PROJECTION",
        "result_checksum": primary_checksum,
        "result": primary_result,
    }
    reference_document = {
        "implementation": "REFERENCE_STRUCTURAL_BYTE_SCANNER",
        "result_checksum": reference_checksum,
        "result": reference_result,
    }
    write_json(staging / "primary_diagnostic.json", primary_document)
    write_json(staging / "reference_diagnostic.json", reference_document)
    findings = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_FINDINGS_V0_1",
        "status": status,
        "result_checksum": primary_checksum,
        "independent_reproduction": {
            "pass": reproduction_pass,
            "primary_checksum": primary_checksum,
            "reference_checksum": reference_checksum,
            "exact_payload_equality": primary_result == reference_result,
        },
        "classification_counts": primary_result["classification_counts"],
        "coverage_determination": primary_result["coverage_determination"],
        "recommendation": recommendation,
        "constraints": {
            "forbidden_value_fields_deserialized": 0,
            "previously_found_outcomes_reopened": 0,
            "stage_1_tests_executed": 0,
            "stage_2_tests_executed": 0,
            "data_repaired_refreshed_substituted_or_acquired": False,
            "charge_incurred": False,
            "year_2025_or_2026_values_accessed": False,
        },
    }
    findings["findings_hash"] = canonical_hash(findings)
    write_json(staging / "findings.json", findings)
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_VERDICT_V0_1",
        "status": status,
        "preserved_predecessor_status": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
        "diagnostic_reproduction_pass": reproduction_pass,
        "all_374_constructible_from_existing_sealed_source": primary_result["coverage_determination"]["all_374_constructible_from_existing_sealed_source"],
        "currently_constructible_nonholiday_outcomes": primary_result["coverage_determination"]["currently_constructible_nonholiday_outcomes"],
        "classification_counts": primary_result["classification_counts"],
        "recommendation_code": recommendation["code"] if recommendation else None,
        "recovery_implemented": False,
        "stage_1_or_stage_2_executed": False,
    }
    verdict["verdict_hash"] = canonical_hash(verdict)
    write_json(staging / "verdict.json", verdict)

    report = render_report(
        primary_result,
        reproduction_pass=reproduction_pass,
        recommendation=recommendation,
        final_status=status,
    )
    temporary_report = REPORT_PATH.with_suffix(REPORT_PATH.suffix + ".building")
    temporary_report.write_text(report, encoding="utf-8", newline="\n")
    artifact_names = ["primary_diagnostic.json", "reference_diagnostic.json", "findings.json", "verdict.json"]
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_MANIFEST_V0_1",
        "status": status,
        "protocol": {"path": str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": EXPECTED_PROTOCOL_SHA},
        "freeze": {"path": str(FREEZE_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": EXPECTED_FREEZE_SHA, "receipt": EXPECTED_FREEZE_RECEIPT},
        "bound_sources": {"price_bars_sha256": EXPECTED_PRICE_SHA, "sessions_sha256": EXPECTED_SESSION_SHA},
        "artifacts": {
            name: {"sha256": sha256_file(staging / name), "bytes": (staging / name).stat().st_size}
            for name in artifact_names
        },
        "report": {"path": REPORT_PATH.name, "sha256": sha256_file(temporary_report), "bytes": temporary_report.stat().st_size},
        "result_checksum": primary_checksum,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    write_json(staging / "manifest.json", manifest)
    final_seal = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_FINAL_SEAL_V0_1",
        "status": status,
        "manifest_sha256": sha256_file(staging / "manifest.json"),
        "manifest_hash": manifest["manifest_hash"],
        "verdict_sha256": sha256_file(staging / "verdict.json"),
        "findings_sha256": sha256_file(staging / "findings.json"),
        "primary_sha256": sha256_file(staging / "primary_diagnostic.json"),
        "reference_sha256": sha256_file(staging / "reference_diagnostic.json"),
        "result_checksum": primary_checksum,
        "independent_reproduction_pass": reproduction_pass,
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    final_seal["final_seal_receipt"] = canonical_hash(final_seal)
    write_json(staging / "final_seal.json", final_seal)
    staging.replace(OUTPUT_DIR)
    temporary_report.replace(REPORT_PATH)

    # Post-seal verification reads only generated diagnostic artifacts.
    sealed_manifest = load_json(OUTPUT_DIR / "manifest.json")
    for name, metadata in sealed_manifest["artifacts"].items():
        if sha256_file(OUTPUT_DIR / name) != metadata["sha256"]:
            raise ValueError(f"Post-seal artifact verification failed: {name}")
    if sha256_file(REPORT_PATH) != sealed_manifest["report"]["sha256"]:
        raise ValueError("Post-seal report verification failed")
    print(json.dumps({
        "status": status,
        "classification_counts": primary_result["classification_counts"],
        "coverage": primary_result["coverage_determination"],
        "recommendation": recommendation["code"] if recommendation else None,
        "result_checksum": primary_checksum,
        "final_seal_sha256": sha256_file(OUTPUT_DIR / "final_seal.json"),
        "forbidden_value_fields_deserialized": 0,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
