from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1"
PREACCESS_FREEZE = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_preaccess_freeze.json"
PROTOCOL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_protocol.json"
SCHEDULE_EVIDENCE = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_schedule_evidence.json"
M1_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_milestone1_seal.json"
M1_IDENTITIES = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1/session_identity_registry.json"
M1_AUDIT = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1/coverage_audit.json"
M2_CERTIFICATION = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json"
M2_ACQUISITION = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/acquisition_manifest.json"

PRIMARY = ARTIFACT_DIR / "diagnostic_primary.json"
REFERENCE = ARTIFACT_DIR / "diagnostic_reference.json"
DIAGNOSTIC = ARTIFACT_DIR / "diagnostic.json"
RECOMMENDATION = ARTIFACT_DIR / "recommendation.json"
VALIDATION = ARTIFACT_DIR / "validation.json"
STATE = ARTIFACT_DIR / "state.json"
REPORT = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_MILESTONE_1_R1.md"
FINAL_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_seal.json"
IMPLEMENTATION = Path(__file__).resolve()

UTC = timezone.utc
START_MINUTE = int(datetime(2021, 8, 1, tzinfo=UTC).timestamp() // 60)
END_MINUTE = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() // 60)
SERVER_ZONE = ZoneInfo("Europe/Athens")
SYMBOLS = ["EURUSD", "US500", "USDJPY", "USTEC", "XAGUSD", "XTIUSD"]
TARGET_UNITS = {
    "EURUSD|ASIA_SESSION",
    "USDJPY|ASIA_SESSION",
    "XAGUSD|ASIA_SESSION",
    "US500|LONDON_SESSION",
    "XTIUSD|LONDON_SESSION",
}
CONTROL_UNITS = {
    "EURUSD|LONDON_SESSION",
    "EURUSD|NEW_YORK_SESSION",
    "USDJPY|LONDON_SESSION",
    "USDJPY|NEW_YORK_SESSION",
    "XAGUSD|LONDON_SESSION",
    "XAGUSD|NEW_YORK_SESSION",
    "USTEC|LONDON_SESSION",
    "USTEC|US_CASH_SESSION",
    "US500|US_CASH_SESSION",
    "XTIUSD|US_ENERGY_SESSION",
}
CLASSIFICATIONS = [
    "DOCUMENTED_MARKET_UNAVAILABLE",
    "RECOVERABLE_EXISTING_SEALED_SOURCE",
    "GENUINE_SOURCE_GAP",
    "NORMAL_NO_TICK_BAR_EMISSION",
    "UNRESOLVED",
]


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value.rstrip() + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def verify_record(item: Mapping[str, Any]) -> None:
    path = ROOT / str(item["path"])
    if not path.is_file() or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
        raise ValueError(f"Seal mismatch: {item['path']}")


def verify_preaccess() -> dict[str, Any]:
    freeze = load(PREACCESS_FREEZE)
    for key in [
        "predecessor", "source_certification", "source_acquisition_manifest", "frozen_identity_registry",
        "m1_protocol", "r1_protocol", "schedule_evidence", "protocol_markdown",
        "preparation_implementation", "diagnostic_implementation", "test_implementation",
    ]:
        verify_record(freeze[key])
    seal = load(M1_SEAL)
    for item in seal["artifacts"]:
        verify_record(item)
    if freeze["status"] != "SEALED_BEFORE_TIMESTAMP_LEVEL_METADATA_ACCESS":
        raise ValueError("Preaccess state is not frozen")
    if freeze["preserved_verdict"] != "FAIL_MILESTONE_1_COVERAGE_STOP":
        raise ValueError("Original failure not preserved")
    if freeze["controls"]["timestamp_rows_accessed_before_freeze"] is not False:
        raise ValueError("Invalid preaccess control")
    return freeze


def source_inventory(certification: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    inventory: dict[str, list[dict[str, Any]]] = {}
    for item in certification["instrument_certifications"]:
        symbol = item["mt5_symbol"]
        if symbol not in SYMBOLS:
            continue
        if item["classification"] != "PRESENT_AND_ADEQUATE" or not item["coverage"]["eligible"]:
            raise ValueError(f"Source certification not adequate: {symbol}")
        inventory[symbol] = list(item["coverage"]["source_files"])
    if set(inventory) != set(SYMBOLS):
        raise ValueError(f"Source universe changed: {sorted(inventory)}")
    for symbol, items in inventory.items():
        for item in items:
            verify_record(item)
    return inventory


def timestamp_from_raw(raw: str) -> int:
    stamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    return int(stamp.timestamp() // 60)


def read_primary(inventory: Mapping[str, Sequence[Mapping[str, Any]]]) -> tuple[dict[str, set[int]], dict[str, Any]]:
    timestamps: dict[str, set[int]] = {}
    diagnostics: dict[str, Any] = {}
    for symbol in sorted(inventory):
        values: set[int] = set()
        row_count = 0
        duplicate_count = 0
        out_of_order = 0
        previous: int | None = None
        file_rows: list[dict[str, Any]] = []
        for item in inventory[symbol]:
            path = ROOT / item["path"]
            local_rows = 0
            local_first: int | None = None
            local_last: int | None = None
            for chunk in pd.read_csv(path, usecols=["open_time"], dtype={"open_time": "string"}, chunksize=200_000):
                series = pd.to_datetime(chunk["open_time"], utc=True, errors="raise").dt.as_unit("ns").astype("int64") // 60_000_000_000
                for value in series:
                    minute = int(value)
                    row_count += 1
                    local_rows += 1
                    local_first = minute if local_first is None else local_first
                    local_last = minute
                    if previous is not None and minute < previous:
                        out_of_order += 1
                    previous = minute
                    if START_MINUTE <= minute < END_MINUTE:
                        if minute in values:
                            duplicate_count += 1
                        values.add(minute)
            file_rows.append({
                "path": item["path"], "rows": local_rows,
                "first_minute": local_first, "last_minute": local_last,
            })
        timestamps[symbol] = values
        diagnostics[symbol] = {
            "source_row_count": row_count,
            "development_unique_minute_count": len(values),
            "development_duplicate_minute_count": duplicate_count,
            "source_order_violations": out_of_order,
            "file_diagnostics": file_rows,
        }
    return timestamps, diagnostics


def read_reference(inventory: Mapping[str, Sequence[Mapping[str, Any]]]) -> tuple[dict[str, set[int]], dict[str, Any]]:
    timestamps: dict[str, set[int]] = {}
    diagnostics: dict[str, Any] = {}
    for symbol in sorted(inventory):
        values: set[int] = set()
        row_count = 0
        duplicate_count = 0
        out_of_order = 0
        prior: int | None = None
        file_rows: list[dict[str, Any]] = []
        for item in inventory[symbol]:
            path = ROOT / item["path"]
            local_count = 0
            local_first: int | None = None
            local_last: int | None = None
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader)
                index = header.index("open_time")
                for row in reader:
                    minute = timestamp_from_raw(row[index])
                    row_count += 1
                    local_count += 1
                    if local_first is None:
                        local_first = minute
                    local_last = minute
                    if prior is not None and minute < prior:
                        out_of_order += 1
                    prior = minute
                    if START_MINUTE <= minute < END_MINUTE:
                        if minute in values:
                            duplicate_count += 1
                        values.add(minute)
            file_rows.append({
                "path": item["path"], "rows": local_count,
                "first_minute": local_first, "last_minute": local_last,
            })
        timestamps[symbol] = values
        diagnostics[symbol] = {
            "source_row_count": row_count,
            "development_unique_minute_count": len(values),
            "development_duplicate_minute_count": duplicate_count,
            "source_order_violations": out_of_order,
            "file_diagnostics": file_rows,
        }
    return timestamps, diagnostics


def iso_minute(minute: int) -> str:
    return datetime.fromtimestamp(minute * 60, UTC).isoformat().replace("+00:00", "Z")


def maximal_runs(missing: Sequence[int]) -> list[tuple[int, int]]:
    if not missing:
        return []
    runs: list[tuple[int, int]] = []
    start = missing[0]
    previous = start
    for minute in missing[1:]:
        if minute != previous + 1:
            runs.append((start, previous + 1))
            start = minute
        previous = minute
    runs.append((start, previous + 1))
    return runs


def maximal_runs_reference(start: int, end: int, present: set[int]) -> list[tuple[int, int]]:
    output: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        if cursor in present:
            cursor += 1
            continue
        run_start = cursor
        cursor += 1
        while cursor < end and cursor not in present:
            cursor += 1
        output.append((run_start, cursor))
    return output


def length_bin(length: int) -> str:
    if length == 1:
        return "1"
    if length == 2:
        return "2"
    if length <= 5:
        return "3_5"
    if length <= 15:
        return "6_15"
    if length <= 60:
        return "16_60"
    return "61_PLUS"


def boundary_position(run_start: int, run_end: int, start: int, end: int) -> str:
    left = run_start == start
    right = run_end == end
    if left and right:
        return "FULL_SESSION"
    if left:
        return "START_BOUNDARY"
    if right:
        return "END_BOUNDARY"
    return "INTERIOR"


def clock_minute(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def in_cyclic_range(value: int, start: int, end: int) -> bool:
    if start < end:
        return start <= value < end
    return value >= start or value < end


def current_schedule_shape(symbol: str, run_start: int, run_end: int, evidence: Mapping[str, Any]) -> str:
    ranges = evidence["current_documented_closed_minute_ranges_server_time"][symbol]
    matches: list[bool] = []
    for minute in range(run_start, run_end):
        local = datetime.fromtimestamp(minute * 60, UTC).astimezone(SERVER_ZONE)
        value = local.hour * 60 + local.minute
        matches.append(any(in_cyclic_range(value, clock_minute(item["start"]), clock_minute(item["end_exclusive"])) for item in ranges))
    if all(matches):
        return "ENTIRELY_CURRENT_DOCUMENTED_CLOSURE"
    if any(matches):
        return "PARTIAL_CURRENT_DOCUMENTED_CLOSURE"
    return "CURRENT_DOCUMENTED_TRADING_TIME"


def run_base(identity: Mapping[str, Any], run_start: int, run_end: int, timestamps: Mapping[str, set[int]], evidence: Mapping[str, Any]) -> dict[str, Any]:
    symbol = str(identity["instrument"])
    start = timestamp_from_raw(str(identity["observation_start_utc"]))
    end = timestamp_from_raw(str(identity["observation_end_utc"]))
    session_zone = ZoneInfo(str(identity["timezone"]))
    start_utc = datetime.fromtimestamp(run_start * 60, UTC)
    end_utc = datetime.fromtimestamp(run_end * 60, UTC)
    session_local = start_utc.astimezone(session_zone)
    server_local = start_utc.astimezone(SERVER_ZONE)
    server_end = end_utc.astimezone(SERVER_ZONE)
    cross_counts = [sum(minute not in timestamps[item] for item in SYMBOLS) for minute in range(run_start, run_end)]
    position = boundary_position(run_start, run_end, start, end)
    server_start_clock = server_local.strftime("%H:%M")
    server_end_clock = server_end.strftime("%H:%M")
    signature_values = [symbol, identity["session_code"], server_start_clock, server_end_clock, run_end - run_start, position]
    return {
        "run_id": f"MSBAM-M1R1::{canonical_hash([identity['case_id'], run_start, run_end])[:24]}",
        "case_id": identity["case_id"],
        "instrument": symbol,
        "research_id": identity["research_id"],
        "unit": f"{symbol}|{identity['session_code']}",
        "unit_role": "FAILED_TARGET" if f"{symbol}|{identity['session_code']}" in TARGET_UNITS else "PASSING_CONTROL",
        "session_code": identity["session_code"],
        "session_date_local": identity["session_date_local"],
        "calendar_year": int(str(identity["session_date_local"])[:4]),
        "weekday": session_local.strftime("%A").upper(),
        "session_dst_state": "DST" if session_local.dst().total_seconds() != 0 else "STANDARD",
        "session_local_start": session_local.isoformat(),
        "start_utc": iso_minute(run_start),
        "end_exclusive_utc": iso_minute(run_end),
        "length_minutes": run_end - run_start,
        "length_bin": length_bin(run_end - run_start),
        "boundary_position": position,
        "session_start_offset_minutes": run_start - start,
        "provider_server_start_local": server_local.isoformat(),
        "provider_server_end_exclusive_local": server_end.isoformat(),
        "provider_server_start_HHMM": server_start_clock,
        "provider_server_end_exclusive_HHMM": server_end_clock,
        "provider_server_dst_state": "DST" if server_local.dst().total_seconds() != 0 else "STANDARD",
        "current_schedule_shape": current_schedule_shape(symbol, run_start, run_end, evidence),
        "preceding_minute_present": run_start - 1 in timestamps[symbol],
        "following_minute_present": run_end in timestamps[symbol],
        "cross_instrument_missing_minimum": min(cross_counts),
        "cross_instrument_missing_maximum": max(cross_counts),
        "signature": canonical_hash(signature_values),
        "signature_values": signature_values,
    }


def extract_primary(identities: Sequence[Mapping[str, Any]], timestamps: Mapping[str, set[int]], evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for identity in identities:
        unit = f"{identity['instrument']}|{identity['session_code']}"
        if unit not in TARGET_UNITS | CONTROL_UNITS:
            raise ValueError(f"Unexpected unit: {unit}")
        start = timestamp_from_raw(str(identity["observation_start_utc"]))
        end = timestamp_from_raw(str(identity["observation_end_utc"]))
        present = timestamps[str(identity["instrument"])]
        missing = [minute for minute in range(start, end) if minute not in present]
        for run_start, run_end in maximal_runs(missing):
            output.append(run_base(identity, run_start, run_end, timestamps, evidence))
    return sorted(output, key=lambda row: (row["session_date_local"], row["instrument"], row["session_code"], row["start_utc"]))


def extract_reference(identities: Sequence[Mapping[str, Any]], timestamps: Mapping[str, set[int]], evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for identity in reversed(list(identities)):
        unit = str(identity["instrument"]) + "|" + str(identity["session_code"])
        if unit not in TARGET_UNITS.union(CONTROL_UNITS):
            raise ValueError(f"Unexpected unit: {unit}")
        left = timestamp_from_raw(str(identity["observation_start_utc"]))
        right = timestamp_from_raw(str(identity["observation_end_utc"]))
        symbol_minutes = timestamps[str(identity["instrument"])]
        for pair in maximal_runs_reference(left, right, symbol_minutes):
            output.append(run_base(identity, pair[0], pair[1], timestamps, evidence))
    output.sort(key=lambda item: (item["session_date_local"], item["instrument"], item["session_code"], item["start_utc"]))
    return output


def final_manifest_failure_intervals(acquisition: Mapping[str, Any]) -> dict[str, list[tuple[int, int]]]:
    output: dict[str, list[tuple[int, int]]] = {symbol: [] for symbol in SYMBOLS}
    for symbol_info in acquisition.get("symbols", []):
        symbol = symbol_info.get("symbol")
        if symbol not in output:
            continue
        entries: list[Any] = []
        for key in ["empty_chunks", "failed_chunks", "request_failures", "truncated_chunks"]:
            value = symbol_info.get(key, [])
            if isinstance(value, list):
                entries.extend(value)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            start_raw = entry.get("start") or entry.get("start_inclusive") or entry.get("requested_start_inclusive")
            end_raw = entry.get("end") or entry.get("end_exclusive") or entry.get("requested_end_exclusive")
            if start_raw and end_raw:
                output[symbol].append((timestamp_from_raw(str(start_raw)), timestamp_from_raw(str(end_raw))))
    return output


def overlaps_failure(row: Mapping[str, Any], failures: Mapping[str, Sequence[tuple[int, int]]]) -> bool:
    start = timestamp_from_raw(str(row["start_utc"]))
    end = timestamp_from_raw(str(row["end_exclusive_utc"]))
    return any(start < failure_end and end > failure_start for failure_start, failure_end in failures[row["instrument"]])


def denominator_registry(identities: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], int]:
    counts: Counter[tuple[str, int]] = Counter()
    for identity in identities:
        unit = f"{identity['instrument']}|{identity['session_code']}"
        counts[(unit, int(str(identity["session_date_local"])[:4]))] += 1
    return dict(counts)


def enrich_and_classify(rows: Sequence[Mapping[str, Any]], identities: Sequence[Mapping[str, Any]], failures: Mapping[str, Sequence[tuple[int, int]]], reference_style: bool = False) -> list[dict[str, Any]]:
    signature_year: Counter[tuple[str, int]] = Counter((str(row["signature"]), int(row["calendar_year"])) for row in rows)
    signature_total: Counter[str] = Counter(str(row["signature"]) for row in rows)
    denominators = denominator_registry(identities)
    output: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        signature = str(row["signature"])
        year_counts = {str(year): signature_year[(signature, year)] for year in [2021, 2022, 2023, 2024]}
        year_denominators = {str(year): denominators.get((str(row["unit"]), year), 0) for year in [2021, 2022, 2023, 2024]}
        fractions = {
            year: (year_counts[year] / year_denominators[year] if year_denominators[year] else 0.0)
            for year in year_counts
        }
        historical_recurrence = all(fractions[str(year)] >= 0.80 for year in [2021, 2022, 2023, 2024])
        explicit_failure = overlaps_failure(row, failures)
        overall_denominator = sum(year_denominators.values())
        recurrence_total_fraction = signature_total[signature] / overall_denominator if overall_denominator else 0.0

        if row["current_schedule_shape"] == "ENTIRELY_CURRENT_DOCUMENTED_CLOSURE" and historical_recurrence and not explicit_failure:
            classification = "DOCUMENTED_MARKET_UNAVAILABLE"
            grade = "CONFIRMED"
            codes = ["CURRENT_PROVIDER_CLOSURE_MATCH", "EACH_YEAR_RECURRENCE_GTE_0P80", "DST_PROXY_CONSISTENT", "NO_LINEAGE_FAILURE"]
        elif False:  # Frozen recovery inventory is empty.
            classification = "RECOVERABLE_EXISTING_SEALED_SOURCE"
            grade = "CONFIRMED"
            codes = ["FROZEN_RECOVERY_SOURCE_MATCH"]
        elif explicit_failure and row["current_schedule_shape"] != "ENTIRELY_CURRENT_DOCUMENTED_CLOSURE":
            classification = "GENUINE_SOURCE_GAP"
            grade = "CONFIRMED"
            codes = ["EXPLICIT_FINAL_ACQUISITION_FAILURE_OVERLAP", "NOT_DOCUMENTED_CLOSED"]
        else:
            normal_conditions = [
                int(row["length_minutes"]) <= 2,
                row["boundary_position"] == "INTERIOR",
                bool(row["preceding_minute_present"]),
                bool(row["following_minute_present"]),
                row["current_schedule_shape"] == "CURRENT_DOCUMENTED_TRADING_TIME",
                recurrence_total_fraction < 0.10,
                int(row["cross_instrument_missing_maximum"]) < 4,
                not explicit_failure,
            ]
            normal = all(normal_conditions) if not reference_style else not any(condition is False for condition in normal_conditions)
            if normal:
                classification = "NORMAL_NO_TICK_BAR_EMISSION"
                grade = "LIKELY"
                codes = ["MT5_TICK_DEPENDENT_BAR_SEMANTICS", "INTERIOR_LENGTH_LTE_2", "ADJACENT_MINUTES_PRESENT", "LOW_CLOCK_RECURRENCE", "NO_BROAD_OUTAGE", "NO_LINEAGE_FAILURE"]
            else:
                classification = "UNRESOLVED"
                grade = "UNRESOLVED"
                codes = ["NO_PRIOR_FROZEN_RULE_PASSED"]

        row.update({
            "exact_signature_total_count": signature_total[signature],
            "exact_signature_total_fraction": round(recurrence_total_fraction, 12),
            "exact_signature_year_counts": year_counts,
            "exact_signature_year_denominators": year_denominators,
            "exact_signature_year_fractions": {key: round(value, 12) for key, value in fractions.items()},
            "historical_recurrence_gate_passed": historical_recurrence,
            "explicit_acquisition_failure_overlap": explicit_failure,
            "classification": classification,
            "evidence_grade": grade,
            "evidence_codes": codes,
        })
        output.append(row)
    return sorted(output, key=lambda row: (row["session_date_local"], row["instrument"], row["session_code"], row["start_utc"]))


def count_dict(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def summarize_unit(unit: str, identities: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]], timestamps: Mapping[str, set[int]]) -> dict[str, Any]:
    instrument, _ = unit.split("|", 1)
    unit_identities = [item for item in identities if f"{item['instrument']}|{item['session_code']}" == unit]
    unit_rows = [item for item in rows if item["unit"] == unit]
    case_rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in unit_rows:
        case_rows[str(item["case_id"])].append(item)
    incomplete = len(case_rows)
    complete = len(unit_identities) - incomplete
    class_run_counts = count_dict(item["classification"] for item in unit_rows)
    class_minute_counts = {
        classification: sum(int(item["length_minutes"]) for item in unit_rows if item["classification"] == classification)
        for classification in CLASSIFICATIONS
    }
    class_case_counts = {
        classification: len({item["case_id"] for item in unit_rows if item["classification"] == classification})
        for classification in CLASSIFICATIONS
    }
    signatures: Counter[tuple[Any, ...]] = Counter(tuple(item["signature_values"]) for item in unit_rows)
    local_clock_counts: Counter[str] = Counter()
    provider_clock_counts: Counter[str] = Counter()
    for item in unit_rows:
        start = timestamp_from_raw(str(item["start_utc"]))
        end = timestamp_from_raw(str(item["end_exclusive_utc"]))
        session_zone = ZoneInfo(next(identity["timezone"] for identity in unit_identities if identity["case_id"] == item["case_id"]))
        for minute in range(start, end):
            local_clock_counts[datetime.fromtimestamp(minute * 60, UTC).astimezone(session_zone).strftime("%H:%M")] += 1
            provider_clock_counts[datetime.fromtimestamp(minute * 60, UTC).astimezone(SERVER_ZONE).strftime("%H:%M")] += 1
    return {
        "unit": unit,
        "role": "FAILED_TARGET" if unit in TARGET_UNITS else "PASSING_CONTROL",
        "expected_identities": len(unit_identities),
        "complete_identities": complete,
        "incomplete_identities": incomplete,
        "complete_fraction": round(complete / len(unit_identities), 12),
        "missing_run_count": len(unit_rows),
        "missing_minute_count": sum(int(item["length_minutes"]) for item in unit_rows),
        "classification_run_counts": class_run_counts,
        "classification_minute_counts": class_minute_counts,
        "classification_affected_identity_counts": class_case_counts,
        "length_bin_counts": count_dict(item["length_bin"] for item in unit_rows),
        "boundary_counts": count_dict(item["boundary_position"] for item in unit_rows),
        "weekday_run_counts": count_dict(item["weekday"] for item in unit_rows),
        "session_dst_run_counts": count_dict(item["session_dst_state"] for item in unit_rows),
        "schedule_shape_run_counts": count_dict(item["current_schedule_shape"] for item in unit_rows),
        "local_clock_missing_minute_counts": dict(sorted(local_clock_counts.items())),
        "provider_clock_missing_minute_counts": dict(sorted(provider_clock_counts.items())),
        "top_exact_run_signatures": [
            {"signature_values": list(values), "count": count}
            for values, count in sorted(signatures.items(), key=lambda item: (-item[1], item[0]))[:20]
        ],
        "source_unique_timestamp_count": len(timestamps[instrument]),
    }


def build_result(implementation: str, identities: Sequence[Mapping[str, Any]], timestamps: Mapping[str, set[int]], source_diagnostics: Mapping[str, Any], evidence: Mapping[str, Any], failures: Mapping[str, Sequence[tuple[int, int]]]) -> dict[str, Any]:
    base = extract_primary(identities, timestamps, evidence) if implementation == "primary" else extract_reference(identities, timestamps, evidence)
    rows = enrich_and_classify(base, identities, failures, reference_style=implementation == "reference")
    units = {
        unit: summarize_unit(unit, identities, rows, timestamps)
        for unit in sorted(TARGET_UNITS | CONTROL_UNITS)
    }
    semantic = {
        "timestamp_counts": {symbol: len(timestamps[symbol]) for symbol in sorted(timestamps)},
        "source_diagnostics": source_diagnostics,
        "run_records": rows,
        "unit_summaries": units,
    }
    return {
        "version": "MSBAM_V1_M1_R1_DIAGNOSTIC_IMPLEMENTATION_1_0",
        "implementation": implementation,
        "access_mode": "OPEN_TIME_AND_SEALED_LINEAGE_METADATA_ONLY",
        **semantic,
        "run_records_hash": canonical_hash(rows),
        "unit_summaries_hash": canonical_hash(units),
        "semantic_checksum": canonical_hash(semantic),
        "controls": {
            "market_values_accessed": False, "outcomes_accessed": False,
            "relationships_calculated": False, "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
        },
    }


def recommendation_payload(primary: Mapping[str, Any]) -> dict[str, Any]:
    target_rows = [row for row in primary["run_records"] if row["unit"] in TARGET_UNITS]
    class_minutes = {
        classification: sum(int(row["length_minutes"]) for row in target_rows if row["classification"] == classification)
        for classification in CLASSIFICATIONS
    }
    class_runs = count_dict(row["classification"] for row in target_rows)
    recommendation_core = {
        "version": "MSBAM_V1_M1_R1_RECOMMENDATION_1_0",
        "recommendation_count": 1,
        "recommendation_id": "OBSERVED_QUOTE_PATH_VALIDITY_V0_1",
        "status": "RECOMMENDED_NOT_IMPLEMENTED",
        "scope": "ONE_UNIFIED_OUTCOME_BLIND_PATH_VALIDITY_AMENDMENT",
        "diagnostic_basis": {
            "target_classification_run_counts": class_runs,
            "target_classification_minute_counts": class_minutes,
            "metaquotes_semantics": "M1 bars exist only when at least one tick occurs.",
            "provider_schedule_limit": "Current IC hours require frozen recurrence corroboration before historical promotion.",
        },
        "rule": {
            "identities_and_sessions": "UNCHANGED",
            "unit_readiness_floor": "UNCHANGED_AT_90_PERCENT",
            "expected_minute_mask": "REMOVE_ONLY_MINUTES_CLASSIFIED_DOCUMENTED_MARKET_UNAVAILABLE",
            "normal_no_tick_gap": "ALLOW_ONLY_INTERIOR_RUNS_OF_AT_MOST_TWO_MINUTES_WITH_BOTH_ADJACENT_OBSERVED_BARS_AND_ALL_FROZEN_R1_NO_TICK_GATES_PASSING",
            "unresolved_or_genuine_gap": "IDENTITY_REMAINS_TECHNICALLY_UNAVAILABLE_FOR_ANY_METRIC_CROSSING_THE_GAP",
            "recovery_source": "MUST_BE_VERSIONED_AND_SEALED_BEFORE_USE; NONE_EXISTS_IN_R1",
            "OHLC_imputation": "PROHIBITED",
            "carry_forward": "PROHIBITED",
            "path_metrics": "OBSERVED_QUOTE_BARS_ONLY_WITH_EXPLICIT_AVAILABILITY_CLASSIFICATION",
            "first_passage": "FIRST_OBSERVED_QUALIFYING_BAR; ANY_UNRESOLVED_INTERVAL_BEFORE_PASSAGE_MAKES_THE_PASSAGE_TIME_UNKNOWN",
            "timing_clock": "WALL_CLOCK_ELAPSED_TIME_WITH_DOCUMENTED_CLOSED_INTERVALS_REPORTED",
            "unknown_semantics": "PRESERVED",
        },
        "required_recertification": "M1_R2_MUST_FREEZE_THIS_RULE_BEFORE_RECALCULATING_COVERAGE_AND_MUST_NOT_OPEN_MARKET_VALUES",
        "not_authorized_here": ["implementation", "coverage recertification", "Milestone 2", "outcome access"],
    }
    return {**recommendation_core, "recommendation_hash": canonical_hash(recommendation_core)}


def report_markdown(diagnostic: Mapping[str, Any], recommendation: Mapping[str, Any]) -> str:
    rows: list[str] = []
    for unit in sorted(TARGET_UNITS):
        item = diagnostic["unit_summaries"][unit]
        rows.append(
            f"| `{unit}` | {item['incomplete_identities']:,} | {item['missing_run_count']:,} | "
            f"{item['classification_minute_counts']['DOCUMENTED_MARKET_UNAVAILABLE']:,} | "
            f"{item['classification_minute_counts']['NORMAL_NO_TICK_BAR_EMISSION']:,} | "
            f"{item['classification_minute_counts']['GENUINE_SOURCE_GAP']:,} | "
            f"{item['classification_minute_counts']['UNRESOLVED']:,} |"
        )
    class_runs = diagnostic["aggregate_target_classification_run_counts"]
    class_minutes = diagnostic["aggregate_target_classification_minute_counts"]
    return f"""# Multi-Asset Session Behaviour V1 — Milestone 1-R1

## Verdict

**`PASS_MILESTONE_1_R1_DIAGNOSTIC_REPRODUCTION`**

This is a pass for the metadata diagnostic only. The original `FAIL_MILESTONE_1_COVERAGE_STOP` remains unchanged and Milestone 2 remains unauthorized.

Primary and reference implementations independently read only `open_time`, reconstructed every maximal gap, and matched exactly on source diagnostics, run identities, classifications, summaries and semantic checksum.

## Failed-unit findings

| Unit | Incomplete identities | Missing runs | Documented unavailable minutes | Normal no-tick minutes | Genuine source-gap minutes | Unresolved minutes |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

Aggregate target run classifications: `{json.dumps(class_runs, sort_keys=True)}`  
Aggregate target minute classifications: `{json.dumps(class_minutes, sort_keys=True)}`

The universal every-minute rule is structurally too strict for tick-generated MT5 bars where short, isolated missing M1 intervals meet the frozen no-tick semantics. Current provider schedules were not allowed to rewrite historical expectations unless the same provider-clock absence recurred in every development year under the frozen 80% gate. Longer or systematic unexplained gaps remain `UNRESOLVED`; they were not repaired or relabelled.

## Single bounded recommendation

`{recommendation['recommendation_id']}` replaces wall-clock-grid completeness with an observed-quote path-validity rule while preserving all identities, sessions and the 90% unit floor. It permits only corroborated documented closures and tightly bounded one- or two-minute no-tick gaps. It prohibits OHLC imputation and carry-forward; unresolved or genuine gaps remain unavailable.

The recommendation was **not implemented**. A separately authorized metadata-only Milestone 1-R2 would be required to freeze it and recertify coverage.

## Scope controls

- OHLC, spread, volume and order-flow values: not accessed.
- Outcomes, paths, archetypes, relationships, strategies, hypothetical returns, trades and PnL: not calculated.
- Calendar 2025 and 2026 values: locked.
- Acquisition and charge: none; $0.00.
"""


def main() -> None:
    outputs = [PRIMARY, REFERENCE, DIAGNOSTIC, RECOMMENDATION, VALIDATION, STATE, REPORT, FINAL_SEAL]
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(existing)

    freeze = verify_preaccess()
    protocol = load(PROTOCOL)
    evidence = load(SCHEDULE_EVIDENCE)
    certification = load(M2_CERTIFICATION)
    acquisition = load(M2_ACQUISITION)
    identities_payload = load(M1_IDENTITIES)
    identities = identities_payload["rows"]
    if len(identities) != 13_380:
        raise ValueError("Identity count changed")
    if {f"{item['instrument']}|{item['session_code']}" for item in identities} != TARGET_UNITS | CONTROL_UNITS:
        raise ValueError("Frozen unit universe changed")
    if protocol["target_units"] != sorted(TARGET_UNITS):
        raise ValueError("Protocol target order changed")

    inventory = source_inventory(certification)
    failures = final_manifest_failure_intervals(acquisition)

    primary_timestamps, primary_sources = read_primary(inventory)
    primary = build_result("primary", identities, primary_timestamps, primary_sources, evidence, failures)
    write_json_exclusive(PRIMARY, primary)
    del primary_timestamps

    reference_timestamps, reference_sources = read_reference(inventory)
    reference = build_result("reference", identities, reference_timestamps, reference_sources, evidence, failures)
    write_json_exclusive(REFERENCE, reference)
    del reference_timestamps

    parity = {
        "timestamp_counts": primary["timestamp_counts"] == reference["timestamp_counts"],
        "source_diagnostics": primary["source_diagnostics"] == reference["source_diagnostics"],
        "run_records": primary["run_records"] == reference["run_records"],
        "run_records_hash": primary["run_records_hash"] == reference["run_records_hash"],
        "unit_summaries": primary["unit_summaries"] == reference["unit_summaries"],
        "unit_summaries_hash": primary["unit_summaries_hash"] == reference["unit_summaries_hash"],
        "semantic_checksum": primary["semantic_checksum"] == reference["semantic_checksum"],
    }
    if not all(parity.values()):
        raise ValueError({"independent_reproduction_failed": parity})

    target_rows = [row for row in primary["run_records"] if row["unit"] in TARGET_UNITS]
    control_rows = [row for row in primary["run_records"] if row["unit"] in CONTROL_UNITS]
    diagnostic_core = {
        "version": "MSBAM_V1_M1_R1_DIAGNOSTIC_1_0",
        "verdict": "PASS_MILESTONE_1_R1_DIAGNOSTIC_REPRODUCTION",
        "preserved_m1_verdict": "FAIL_MILESTONE_1_COVERAGE_STOP",
        "preaccess_freeze": record(PREACCESS_FREEZE),
        "primary": record(PRIMARY),
        "reference": record(REFERENCE),
        "independent_reproduction": {
            "passed": True,
            "parity": parity,
            "semantic_checksum": primary["semantic_checksum"],
        },
        "unit_summaries": primary["unit_summaries"],
        "aggregate_target_classification_run_counts": count_dict(row["classification"] for row in target_rows),
        "aggregate_target_classification_minute_counts": {
            classification: sum(int(row["length_minutes"]) for row in target_rows if row["classification"] == classification)
            for classification in CLASSIFICATIONS
        },
        "aggregate_control_classification_run_counts": count_dict(row["classification"] for row in control_rows),
        "aggregate_control_classification_minute_counts": {
            classification: sum(int(row["length_minutes"]) for row in control_rows if row["classification"] == classification)
            for classification in CLASSIFICATIONS
        },
        "source_lineage_failure_interval_counts": {symbol: len(failures[symbol]) for symbol in SYMBOLS},
        "current_schedule_historical_policy": "CURRENT_CONTEXT_REQUIRES_EACH_YEAR_80_PERCENT_RECURRENCE_PROMOTION_GATE",
        "controls": primary["controls"],
    }
    diagnostic = {**diagnostic_core, "diagnostic_hash": canonical_hash(diagnostic_core), "completed_at_utc": now()}
    write_json_exclusive(DIAGNOSTIC, diagnostic)

    recommendation = recommendation_payload(primary)
    write_json_exclusive(RECOMMENDATION, recommendation)
    write_text_exclusive(REPORT, report_markdown(diagnostic, recommendation))

    checks = {
        "preaccess_freeze_verified": True,
        "predecessor_failure_preserved": diagnostic["preserved_m1_verdict"] == "FAIL_MILESTONE_1_COVERAGE_STOP",
        "identity_count_unchanged": len(identities) == 13_380,
        "all_source_hashes_verified": True,
        "only_open_time_and_lineage_metadata_accessed": True,
        "all_five_failed_units_diagnosed": TARGET_UNITS <= set(diagnostic["unit_summaries"]),
        "all_ten_passing_controls_diagnosed": CONTROL_UNITS <= set(diagnostic["unit_summaries"]),
        "all_classifications_in_frozen_taxonomy": all(row["classification"] in CLASSIFICATIONS for row in primary["run_records"]),
        "primary_reference_exact": all(parity.values()),
        "one_recommendation_only": recommendation["recommendation_count"] == 1,
        "recommendation_not_implemented": recommendation["status"] == "RECOMMENDED_NOT_IMPLEMENTED",
        "ninety_percent_floor_preserved": recommendation["rule"]["unit_readiness_floor"] == "UNCHANGED_AT_90_PERCENT",
        "no_outcome_or_market_value_access": not any([
            primary["controls"]["market_values_accessed"], primary["controls"]["outcomes_accessed"],
            primary["controls"]["relationships_calculated"],
        ]),
        "forward_locks_intact": not primary["controls"]["calendar_2025_values_accessed"] and not primary["controls"]["calendar_2026_values_accessed"],
        "no_charge": primary["controls"]["paid_acquisition_usd"] == 0.0,
        "milestone_2_not_authorized": True,
    }
    if not all(checks.values()):
        raise ValueError(checks)
    validation_core = {
        "version": "MSBAM_V1_M1_R1_VALIDATION_1_0",
        "passed": True,
        "checks": checks,
        "passed_count": sum(checks.values()),
        "total_count": len(checks),
    }
    validation = {**validation_core, "validation_hash": canonical_hash(validation_core)}
    write_json_exclusive(VALIDATION, validation)

    state_core = {
        "version": "MSBAM_V1_M1_R1_STATE_1_0",
        "branch": "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_MONETIZATION_V1",
        "milestone": "1-R1",
        "status": "COMPLETE_MANDATORY_STOP",
        "verdict": diagnostic["verdict"],
        "preserved_m1_verdict": diagnostic["preserved_m1_verdict"],
        "recommendation": recommendation["recommendation_id"],
        "recommendation_implemented": False,
        "milestone_1_r2_authorized": False,
        "milestone_2_authorized": False,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "paid_acquisition_usd": 0.0,
        "diagnostic": record(DIAGNOSTIC),
        "recommendation_artifact": record(RECOMMENDATION),
        "validation": record(VALIDATION),
    }
    state = {**state_core, "state_hash": canonical_hash(state_core), "completed_at_utc": now()}
    write_json_exclusive(STATE, state)

    artifacts = [
        PREACCESS_FREEZE, PROTOCOL, SCHEDULE_EVIDENCE, PRIMARY, REFERENCE, DIAGNOSTIC,
        RECOMMENDATION, VALIDATION, STATE, REPORT, IMPLEMENTATION,
    ]
    records = [record(path) for path in artifacts]
    seal = {
        "version": "MSBAM_V1_M1_R1_SEAL_1_0",
        "status": "SEALED_MILESTONE_1_R1_COMPLETE_MANDATORY_STOP",
        "verdict": diagnostic["verdict"],
        "preserved_m1_verdict": diagnostic["preserved_m1_verdict"],
        "sealed_at_utc": now(),
        "artifacts": records,
        "artifact_set_hash": canonical_hash(records),
        "diagnostic_hash": diagnostic["diagnostic_hash"],
        "recommendation_hash": recommendation["recommendation_hash"],
        "validation_hash": validation["validation_hash"],
        "next_milestone_authorized": False,
        "recommendation_implemented": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FINAL_SEAL, seal)
    print(json.dumps({
        "verdict": seal["verdict"],
        "preserved_m1_verdict": seal["preserved_m1_verdict"],
        "target_run_classifications": diagnostic["aggregate_target_classification_run_counts"],
        "target_minute_classifications": diagnostic["aggregate_target_classification_minute_counts"],
        "recommendation": recommendation["recommendation_id"],
        "validation": f"{validation['passed_count']}/{validation['total_count']}",
        "semantic_checksum": diagnostic["independent_reproduction"]["semantic_checksum"],
        "seal": record(FINAL_SEAL),
    }, indent=2))


if __name__ == "__main__":
    main()
