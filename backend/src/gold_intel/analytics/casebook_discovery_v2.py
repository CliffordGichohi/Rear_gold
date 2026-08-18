from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gold_intel.analytics.casebook import json_ready

AUDIT_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_COVERAGE_V0_1"
HOLDOUT_START = datetime(2025, 1, 1, tzinfo=UTC)
HOLDOUT_END = datetime(2026, 1, 1, tzinfo=UTC)

TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")

MT5_XAU_FILENAME = re.compile(
    r"^xauusd_1m_ic_markets_mt5_"
    r"(?P<start>\d{8}T\d{4})_(?P<end>\d{8}T\d{4})\.csv$",
    re.IGNORECASE,
)

FORBIDDEN_VALUE_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "value",
    "forecast_value",
    "actual_value",
    "previous_value",
    "revised_previous_value",
    "open_interest",
    "long_contracts",
    "short_contracts",
    "spreading_contracts",
    "probability",
    "percent_change",
    "direction",
    "return",
    "pnl",
    "mfe",
    "mae",
)


@dataclass(frozen=True, slots=True)
class SessionWindow:
    code: str
    timezone: ZoneInfo
    start: time
    end: time


WINDOWS = (
    SessionWindow("ASIA", TOKYO, time(10, 5), time(16, 0)),
    SessionWindow("LONDON", LONDON, time(8, 0), time(12, 0)),
    SessionWindow("NEW_YORK", NEW_YORK, time(8, 0), time(12, 0)),
)


def validate_holdout_metadata_interval(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Coverage boundaries must be timezone-aware")
    if start.astimezone(UTC) != HOLDOUT_START or end.astimezone(UTC) != HOLDOUT_END:
        raise ValueError("V2 metadata coverage is restricted to calendar 2025")


def assert_metadata_only_sql(statements: Mapping[str, str]) -> None:
    for name, statement in statements.items():
        normalized = _without_sql_comments_and_literals(statement).lower()
        for column in FORBIDDEN_VALUE_COLUMNS:
            if re.search(rf"\b{re.escape(column)}\b", normalized):
                raise ValueError(
                    f"Metadata-only SQL {name!r} references forbidden column {column!r}"
                )


def audit_timestamp_only_session_coverage(
    five_minute_open_times: Iterable[datetime],
    *,
    start: datetime = HOLDOUT_START,
    end: datetime = HOLDOUT_END,
) -> dict[str, Any]:
    validate_holdout_metadata_interval(start, end)
    available = {item.astimezone(UTC) for item in five_minute_open_times}
    counters = _empty_session_counts()
    missing: dict[str, list[str]] = defaultdict(list)

    current = date(2025, 1, 1)
    while current < date(2026, 1, 1):
        london_anchor = _local_datetime(current, time(8), LONDON).astimezone(UTC)
        if current.weekday() < 5 and start <= london_anchor < end:
            counters["requested_weekdays"] += 1
            complete = {
                spec.code: _window_complete(
                    available,
                    session_date=current,
                    spec=spec,
                )
                for spec in WINDOWS
            }
            for code, is_complete in complete.items():
                if is_complete:
                    counters[f"{code.lower()}_complete"] += 1
                else:
                    missing[code].append(current.isoformat())

            london_complete = complete["ASIA"] and complete["LONDON"]
            new_york_complete = london_complete and complete["NEW_YORK"]
            if london_complete:
                counters["london_case_complete"] += 1
            else:
                missing["LONDON_CASE"].append(current.isoformat())
            if new_york_complete:
                counters["new_york_case_complete"] += 1
            else:
                missing["NEW_YORK_CASE"].append(current.isoformat())
        current += timedelta(days=1)

    requested = counters["requested_weekdays"]
    for key in (
        "asia_complete",
        "london_complete",
        "new_york_complete",
        "london_case_complete",
        "new_york_case_complete",
    ):
        counters[f"{key}_pct"] = _percentage(counters[key], requested)

    return {
        "data_access_class": "TIMESTAMPS_ONLY",
        "definition": {
            "source_resolution": "Complete timestamp-only five-minute buckets",
            "asia": "10:05-16:00 Asia/Tokyo",
            "london": "08:00-12:00 Europe/London",
            "new_york": "08:00-12:00 America/New_York",
            "dst_policy": "IANA timezone database",
            "weekday_note": (
                "Weekdays include exchange holidays; missing holidays are recorded "
                "and never synthesized."
            ),
        },
        "counts": counters,
        "missing_dates": dict(sorted(missing.items())),
    }


def mt5_xau_files_overlapping_holdout(directory: Path) -> list[Path]:
    output: list[Path] = []
    for path in sorted(directory.glob("xauusd_1m_ic_markets_mt5_*.csv")):
        match = MT5_XAU_FILENAME.fullmatch(path.name)
        if match is None:
            continue
        file_start = _filename_time(match.group("start"))
        file_end = _filename_time(match.group("end"))
        if file_start < HOLDOUT_END and file_end >= HOLDOUT_START:
            output.append(path)
    return output


def source_file_metadata(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "content_deserialized": False,
    }


def add_deterministic_hash(
    document: dict[str, Any],
    *,
    hash_field: str = "data_hash",
) -> str:
    content = {
        key: value for key, value in document.items() if key not in {"generated_at", hash_field}
    }
    digest = hashlib.sha256(
        json.dumps(
            json_ready(content),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    document[hash_field] = digest
    return digest


def verify_embedded_hash(
    document: Mapping[str, Any],
    *,
    hash_field: str,
) -> str:
    supplied = str(document[hash_field])
    content = {key: value for key, value in document.items() if key != hash_field}
    calculated = hashlib.sha256(
        json.dumps(
            json_ready(content),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if calculated != supplied:
        raise ValueError(f"{hash_field} mismatch")
    return supplied


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _window_complete(
    available: set[datetime],
    *,
    session_date: date,
    spec: SessionWindow,
) -> bool:
    window_start = _local_datetime(
        session_date,
        spec.start,
        spec.timezone,
    ).astimezone(UTC)
    end_date = session_date + timedelta(days=1) if spec.end <= spec.start else session_date
    window_end = _local_datetime(end_date, spec.end, spec.timezone).astimezone(UTC)
    expected = int((window_end - window_start).total_seconds() // 300)
    return all(
        window_start + timedelta(minutes=5 * offset) in available for offset in range(expected)
    )


def _filename_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%dT%H%M").replace(tzinfo=UTC)


def _local_datetime(
    session_date: date,
    local_time: time,
    timezone: ZoneInfo,
) -> datetime:
    return datetime.combine(session_date, local_time, tzinfo=timezone)


def _empty_session_counts() -> dict[str, int]:
    return {
        "requested_weekdays": 0,
        "asia_complete": 0,
        "london_complete": 0,
        "new_york_complete": 0,
        "london_case_complete": 0,
        "new_york_case_complete": 0,
    }


def _percentage(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 4) if denominator else 0.0


def _without_sql_comments_and_literals(statement: str) -> str:
    no_block_comments = re.sub(r"/\*.*?\*/", " ", statement, flags=re.DOTALL)
    no_line_comments = re.sub(r"--[^\n]*", " ", no_block_comments)
    return re.sub(r"'(?:''|[^'])*'", "''", no_line_comments)
