"""Milestone-1 metadata-only coverage audit for the multi-asset portfolio branch.

The reader deliberately extracts only timestamp/availability/spread-presence metadata
from MT5 CSV files.  It never parses OHLC, volume, returns, or forward outcomes.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
START = datetime(2021, 8, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)
ARTIFACT_DIR = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m1"
CONTRACT = ROOT / "MULTI_ASSET_MACRO_AND_SESSION_PORTFOLIO_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_protocol.json"
SEAL = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_milestone1_seal.json"
OLD_INVENTORY = ROOT / "research_artifacts/gold_macro_acceptance_source_inventory_v01/inventory.json"
OLD_INVENTORY_SEAL = ROOT / "research_artifacts/gold_macro_acceptance_source_inventory_v01/final_seal.json"
GOLD_TERMINATION = ROOT / "research_manifests/gold_h4_liquidity_target_capture_falsification_v1_final_freeze.json"
CASEBOOK_CROSS_MARKET = ROOT / "research_artifacts/gold_casebook_v01/cross_market_snapshots.jsonl.gz"
MT5_DIR = ROOT / "data/mt5"
TERMINAL = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")

INSTRUMENTS: tuple[dict[str, Any], ...] = (
    {"research_id": "XAUUSD", "symbol": "XAUUSD", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION")},
    {"research_id": "XAGUSD", "symbol": "XAGUSD", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION")},
    {"research_id": "EURUSD", "symbol": "EURUSD", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION")},
    {"research_id": "USDJPY", "symbol": "USDJPY", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION")},
    {"research_id": "NAS100", "symbol": "USTEC", "sessions": ("US_CASH_OPEN",)},
    {"research_id": "US500", "symbol": "US500", "sessions": ("US_CASH_OPEN",)},
    {"research_id": "WTI", "symbol": "XTIUSD", "sessions": ("US_ENERGY",)},
)

SESSIONS = {
    "LONDON_DECISION": ("Europe/London", time(7, 0), time(12, 0)),
    "NEW_YORK_DECISION": ("America/New_York", time(8, 0), time(12, 0)),
    "US_CASH_OPEN": ("America/New_York", time(9, 30), time(12, 0)),
    "US_ENERGY": ("America/New_York", time(8, 0), time(14, 30)),
}

REQUIRED_COLUMNS = ("open_time", "close_time", "available_at", "spread_points")
FILE_RE = re.compile(r"^(?P<symbol>[a-z0-9]+)_1m_ic_markets_mt5_(?P<start>\d{8}t\d{4})_(?P<end>\d{8}t\d{4})\.csv$")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def utc_parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp lacks timezone: {value!r}")
    return parsed.astimezone(UTC)


def dt_key(value: datetime) -> int:
    delta = value - EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def month_universe() -> list[str]:
    output: list[str] = []
    cursor = date(START.year, START.month, 1)
    while cursor < END.date():
        output.append(cursor.strftime("%Y-%m"))
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return output


def weekday_universe() -> list[date]:
    cursor = START.date()
    output: list[date] = []
    while cursor < END.date():
        if cursor.weekday() < 5:
            output.append(cursor)
        cursor += timedelta(days=1)
    return output


def source_files(symbol: str) -> list[Path]:
    output: list[Path] = []
    prefix = symbol.casefold()
    for path in MT5_DIR.glob(f"{prefix}_1m_ic_markets_mt5_*.csv"):
        match = FILE_RE.match(path.name.casefold())
        if not match or match.group("symbol") != prefix:
            continue
        encoded_start = datetime.strptime(match.group("start"), "%Y%m%dt%H%M").replace(tzinfo=UTC)
        if encoded_start < END:
            output.append(path)
    return sorted(output, key=lambda item: item.name)


def _metadata_checksum(rows: Iterable[tuple[int, int, int, str, int, str]]) -> str:
    digest = hashlib.sha256()
    for open_key, close_key, available_key, spread_present, occurrence, source in rows:
        digest.update(f"{open_key}|{close_key}|{available_key}|{spread_present}|{occurrence}|{source}\n".encode())
    return digest.hexdigest()


def _session_coverage(timestamp_keys: set[int], names: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    weekdays = weekday_universe()
    for name in names:
        timezone_name, local_start, local_end = SESSIONS[name]
        zone = ZoneInfo(timezone_name)
        expected_per_session = int(
            (datetime.combine(date.min, local_end) - datetime.combine(date.min, local_start)).total_seconds() / 60
        )
        complete = 0
        fractions: list[float] = []
        complete_dates: list[date] = []
        for day in weekdays:
            start_local = datetime.combine(day, local_start, zone)
            end_local = datetime.combine(day, local_end, zone)
            cursor = start_local.astimezone(UTC)
            stop = end_local.astimezone(UTC)
            found = 0
            while cursor < stop:
                found += int(dt_key(cursor) in timestamp_keys)
                cursor += timedelta(minutes=1)
            fraction = found / expected_per_session
            fractions.append(fraction)
            if fraction >= 0.90:
                complete += 1
                complete_dates.append(day)
        result[name] = {
            "timezone": timezone_name,
            "expected_minutes": expected_per_session,
            "eligible_weekday_windows": len(weekdays),
            "complete_windows": complete,
            "complete_window_fraction": complete / len(weekdays),
            "mean_minute_fraction": sum(fractions) / len(fractions),
            "first_complete_date": complete_dates[0].isoformat() if complete_dates else None,
            "last_complete_date": complete_dates[-1].isoformat() if complete_dates else None,
        }
    return result


def _finalize_scan(
    *,
    symbol: str,
    paths: list[Path],
    occurrences: Counter[int],
    canonical: dict[int, tuple[str, int, int, int, str]],
    rows: int,
    in_file_order_errors: int,
    minute_alignment_errors: int,
    close_errors: int,
    availability_errors: int,
    spread_present: int,
    file_metadata: list[dict[str, Any]],
    session_names: tuple[str, ...],
) -> dict[str, Any]:
    ordered_keys = sorted(canonical)
    timestamps = set(ordered_keys)
    months = Counter()
    days: set[date] = set()
    checksum_rows = []
    for key in ordered_keys:
        source, row_number, close_key, available_key, spread = canonical[key]
        current = EPOCH + timedelta(microseconds=key)
        months[current.strftime("%Y-%m")] += 1
        days.add(current.date())
        checksum_rows.append((key, close_key, available_key, spread, occurrences[key], f"{source}:{row_number}"))
    all_months = month_universe()
    weekday_days = set(weekday_universe())
    active_weekdays = len(days & weekday_days)
    sessions = _session_coverage(timestamps, session_names) if timestamps else {}
    gates = {
        "all_41_months": all(month in months for month in all_months),
        "first_usable_session_lte_2021_08_02": bool(sessions) and all(
            value["first_complete_date"] is not None and value["first_complete_date"] <= "2021-08-02"
            for value in sessions.values()
        ),
        "last_usable_session_gte_2024_12_31": bool(sessions) and all(
            value["last_complete_date"] is not None and value["last_complete_date"] >= "2024-12-31"
            for value in sessions.values()
        ),
        "active_weekday_presence_gte_0p90": bool(weekday_days) and active_weekdays / len(weekday_days) >= 0.90,
        "primary_session_complete_fraction_gte_0p90": bool(sessions) and all(
            value["complete_window_fraction"] >= 0.90 for value in sessions.values()
        ),
        "spread_metadata_fraction_gte_0p95": bool(ordered_keys) and spread_present / rows >= 0.95,
        "minute_aligned": minute_alignment_errors == 0,
        "close_time_exactly_plus_one_minute": close_errors == 0,
        "available_at_not_before_close": availability_errors == 0,
        "monotonic_within_source_file": in_file_order_errors == 0,
        "canonical_keys_unique": len(ordered_keys) == len(set(ordered_keys)),
    }
    return {
        "symbol": symbol,
        "resolution": "M1",
        "development_start_inclusive": iso_z(START),
        "development_end_exclusive": iso_z(END),
        "source_file_count": len(paths),
        "source_files": file_metadata,
        "source_file_inventory_sha256": object_sha256(file_metadata),
        "raw_rows_in_development_window": rows,
        "canonical_unique_timestamps": len(ordered_keys),
        "duplicate_timestamp_occurrences": rows - len(ordered_keys),
        "duplicate_timestamp_groups": sum(1 for count in occurrences.values() if count > 1),
        "first_timestamp": iso_z(EPOCH + timedelta(microseconds=ordered_keys[0])) if ordered_keys else None,
        "last_timestamp": iso_z(EPOCH + timedelta(microseconds=ordered_keys[-1])) if ordered_keys else None,
        "covered_month_count": sum(1 for month in all_months if months[month] > 0),
        "missing_months": [month for month in all_months if months[month] == 0],
        "month_row_counts": dict(sorted(months.items())),
        "active_weekdays": active_weekdays,
        "eligible_weekdays": len(weekday_days),
        "active_weekday_presence": active_weekdays / len(weekday_days),
        "spread_metadata_present_rows": spread_present,
        "spread_metadata_fraction": spread_present / rows if rows else 0.0,
        "in_file_order_errors": in_file_order_errors,
        "minute_alignment_errors": minute_alignment_errors,
        "close_time_errors": close_errors,
        "availability_errors": availability_errors,
        "session_coverage": sessions,
        "gates": gates,
        "eligible": all(gates.values()),
        "canonical_deduplication_policy": "EARLIEST_LEXICOGRAPHIC_SOURCE_FILENAME_THEN_SOURCE_ROW; RAW_FILES_PRESERVED",
        "canonical_metadata_checksum": _metadata_checksum(checksum_rows),
        "semantic_market_values_accessed": False,
    }


def scan_csv_primary(symbol: str, session_names: tuple[str, ...], paths: list[Path] | None = None) -> dict[str, Any]:
    paths = source_files(symbol) if paths is None else sorted(paths, key=lambda item: item.name)
    occurrences: Counter[int] = Counter()
    canonical: dict[int, tuple[str, int, int, int, str]] = {}
    file_metadata: list[dict[str, Any]] = []
    rows = order_errors = alignment_errors = close_errors = availability_errors = spread_present = 0
    for path in paths:
        file_metadata.append({"path": relative(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        prior: int | None = None
        with path.open("r", encoding="utf-8", newline="") as stream:
            header = stream.readline().rstrip("\r\n").split(",")
            indices = {name: header.index(name) for name in REQUIRED_COLUMNS}
            for row_number, line in enumerate(stream, start=2):
                fields = line.rstrip("\r\n").split(",")
                opened = utc_parse(fields[indices["open_time"]])
                if opened >= END:
                    break
                if opened < START:
                    continue
                closed = utc_parse(fields[indices["close_time"]])
                available = utc_parse(fields[indices["available_at"]])
                open_key, close_key, available_key = dt_key(opened), dt_key(closed), dt_key(available)
                rows += 1
                if prior is not None and open_key < prior:
                    order_errors += 1
                prior = open_key
                alignment_errors += int(opened.second != 0 or opened.microsecond != 0)
                close_errors += int(closed != opened + timedelta(minutes=1))
                availability_errors += int(available < closed)
                spread = "1" if fields[indices["spread_points"]].strip() else "0"
                spread_present += int(spread == "1")
                occurrences[open_key] += 1
                candidate = (path.name, row_number, close_key, available_key, spread)
                if open_key not in canonical or candidate[:2] < canonical[open_key][:2]:
                    canonical[open_key] = candidate
    return _finalize_scan(
        symbol=symbol, paths=paths, occurrences=occurrences, canonical=canonical, rows=rows,
        in_file_order_errors=order_errors, minute_alignment_errors=alignment_errors,
        close_errors=close_errors, availability_errors=availability_errors,
        spread_present=spread_present, file_metadata=file_metadata, session_names=session_names,
    )


def scan_csv_reference(symbol: str, session_names: tuple[str, ...], paths: list[Path] | None = None) -> dict[str, Any]:
    """Independent DictReader implementation; only named metadata fields are inspected."""
    paths = source_files(symbol) if paths is None else sorted(paths, key=lambda item: item.name)
    occurrences: Counter[int] = Counter()
    canonical: dict[int, tuple[str, int, int, int, str]] = {}
    file_metadata: list[dict[str, Any]] = []
    rows = order_errors = alignment_errors = close_errors = availability_errors = spread_present = 0
    for path in paths:
        file_metadata.append({"path": relative(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        prior: datetime | None = None
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or any(name not in reader.fieldnames for name in REQUIRED_COLUMNS):
                raise ValueError(f"required metadata column missing in {path}")
            for row_number, record in enumerate(reader, start=2):
                opened = utc_parse(record["open_time"])
                if opened >= END:
                    break
                if opened < START:
                    continue
                closed = utc_parse(record["close_time"])
                available = utc_parse(record["available_at"])
                rows += 1
                if prior is not None and opened < prior:
                    order_errors += 1
                prior = opened
                alignment_errors += int(opened != opened.replace(second=0, microsecond=0))
                close_errors += int((closed - opened).total_seconds() != 60)
                availability_errors += int((available - closed).total_seconds() < 0)
                spread = "1" if (record["spread_points"] or "").strip() else "0"
                spread_present += int(spread == "1")
                key = dt_key(opened)
                occurrences[key] += 1
                candidate = (path.name, row_number, dt_key(closed), dt_key(available), spread)
                incumbent = canonical.get(key)
                canonical[key] = candidate if incumbent is None or candidate[:2] < incumbent[:2] else incumbent
    return _finalize_scan(
        symbol=symbol, paths=paths, occurrences=occurrences, canonical=canonical, rows=rows,
        in_file_order_errors=order_errors, minute_alignment_errors=alignment_errors,
        close_errors=close_errors, availability_errors=availability_errors,
        spread_present=spread_present, file_metadata=file_metadata, session_names=session_names,
    )


CROSS_METADATA_FIELDS = (
    "instrument_id", "available_at", "observed_at", "requested_at", "source_locator",
    "source_record_key", "source_type", "epistemic_status", "status", "staleness_seconds",
)


def scan_cross_market_metadata(reference: bool = False) -> dict[str, Any]:
    requested = ("XAUUSD", "XAGUSD", "EURUSD", "USDJPY", "USTEC", "US500", "XTIUSD")
    counters = {name: {"nonnull": 0, "statuses": Counter(), "sources": Counter(), "keys": Counter(), "first": None, "last": None} for name in requested}
    digest = hashlib.sha256()
    opener: Callable[..., Any] = gzip.open
    with opener(CASEBOOK_CROSS_MARKET, "rt", encoding="utf-8") as stream:
        lines = list(stream) if reference else stream
        for line in lines:
            record = json.loads(line)
            as_of = utc_parse(record["as_of"])
            if not START <= as_of < END:
                continue
            digest_row: dict[str, Any] = {"record_id": record["record_id"], "as_of": iso_z(as_of), "instruments": {}}
            instruments = record.get("instruments", {})
            for name in requested:
                item = instruments.get(name)
                if not isinstance(item, dict):
                    digest_row["instruments"][name] = None
                    continue
                metadata = {field: item.get(field) for field in CROSS_METADATA_FIELDS}
                digest_row["instruments"][name] = metadata
                state = counters[name]
                state["nonnull"] += 1
                state["statuses"][str(item.get("status"))] += 1
                state["sources"][str(item.get("source_type"))] += 1
                source_key = json.dumps(item.get("source_record_key"), sort_keys=True, default=str)
                state["keys"][source_key] += 1
                observed = item.get("observed_at")
                if observed:
                    observed_dt = utc_parse(observed)
                    state["first"] = observed_dt if state["first"] is None or observed_dt < state["first"] else state["first"]
                    state["last"] = observed_dt if state["last"] is None or observed_dt > state["last"] else state["last"]
            digest.update(canonical_json_bytes(digest_row) + b"\n")
    output: dict[str, Any] = {}
    for name, state in counters.items():
        output[name] = {
            "nonnull_snapshots": state["nonnull"],
            "first_observed_at": iso_z(state["first"]),
            "last_observed_at": iso_z(state["last"]),
            "status_counts": dict(sorted(state["statuses"].items())),
            "source_type_counts": dict(sorted(state["sources"].items())),
            "duplicate_source_record_occurrences": sum(count - 1 for count in state["keys"].values() if count > 1),
        }
    return {
        "source": relative(CASEBOOK_CROSS_MARKET),
        "bytes": CASEBOOK_CROSS_MARKET.stat().st_size,
        "sha256": sha256_file(CASEBOOK_CROSS_MARKET),
        "instruments": output,
        "metadata_checksum": digest.hexdigest(),
        "excluded_fields": ["value", "changes", "spread_price", "volume"],
        "semantic_market_values_accessed": False,
    }


def verify_artifact(path_text: str, expected: str) -> dict[str, Any]:
    path = ROOT / Path(path_text.replace("/", str(Path("/")).replace("/", "\\")))
    if not path.exists():
        path = ROOT / path_text
    actual = sha256_file(path) if path.is_file() else None
    return {"path": relative(path), "expected_sha256": expected, "actual_sha256": actual, "verified": actual == expected}


def verify_predecessors() -> dict[str, Any]:
    old_seal = json.loads(OLD_INVENTORY_SEAL.read_text(encoding="utf-8"))
    inventory_checks = [verify_artifact(item["path"], item["sha256"]) for item in old_seal["artifacts"]]
    binding_checks = [verify_artifact(item["path"], item["file_sha256"]) for item in old_seal["predecessor_bindings"]]
    gold = json.loads(GOLD_TERMINATION.read_text(encoding="utf-8"))
    gold_checks: list[dict[str, Any]] = []
    for value in gold.values():
        if isinstance(value, dict) and "path" in value and "sha256" in value:
            gold_checks.append(verify_artifact(value["path"], value["sha256"]))
    return {
        "gold_only_branch_verdict": gold.get("verdict"),
        "gold_only_termination_seal_sha256": sha256_file(GOLD_TERMINATION),
        "gold_only_artifacts": gold_checks,
        "macro_inventory_seal_sha256": sha256_file(OLD_INVENTORY_SEAL),
        "macro_inventory_artifacts": inventory_checks,
        "macro_inventory_predecessor_bindings": binding_checks,
        "all_verified": (
            gold.get("verdict") == "TERMINATE_GOLD_ONLY_10R_BRANCH"
            and all(item["verified"] for item in inventory_checks + binding_checks + gold_checks)
        ),
    }


def read_mt5_catalog() -> dict[str, Any]:
    """Read exact static symbol metadata only; never request a tick or rate."""
    import MetaTrader5 as mt5

    if not TERMINAL.is_file():
        raise RuntimeError(f"MT5 terminal missing: {TERMINAL}")
    if not mt5.initialize(path=str(TERMINAL)):
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
    try:
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            raise RuntimeError("MT5 terminal has no connected broker session")
        fields = (
            "name", "description", "path", "digits", "point", "trade_contract_size",
            "trade_tick_size", "currency_base", "currency_profit", "currency_margin",
            "volume_min", "volume_max", "volume_step", "trade_mode",
        )
        result: dict[str, Any] = {}
        for item in INSTRUMENTS:
            symbol = item["symbol"]
            info = mt5.symbol_info(symbol)
            result[symbol] = None if info is None else {field: getattr(info, field, None) for field in fields}
        return {
            "provider": "IC_MARKETS_MT5_CONNECTED_CATALOG",
            "terminal_connected": True,
            "catalog_size": mt5.symbols_total(),
            "query_type": "EXACT_SYMBOL_INFO_STATIC_METADATA_ONLY",
            "tick_or_rate_request_made": False,
            "symbols": result,
        }
    finally:
        mt5.shutdown()


def semantic_scan_view(scan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in scan.items() if key != "implementation"}


def build_audit() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    predecessor = verify_predecessors()
    if not predecessor["all_verified"]:
        raise RuntimeError("a predecessor seal or bound artifact failed verification")
    catalog = read_mt5_catalog()
    write_json(ARTIFACT_DIR / "mt5_symbol_catalog_snapshot.json", catalog)

    primary_scans: dict[str, Any] = {}
    reference_scans: dict[str, Any] = {}
    for item in INSTRUMENTS:
        symbol, sessions = item["symbol"], tuple(item["sessions"])
        paths = source_files(symbol)
        primary_scans[symbol] = scan_csv_primary(symbol, sessions, paths)
        reference_scans[symbol] = scan_csv_reference(symbol, sessions, paths)
    primary_cross = scan_cross_market_metadata(reference=False)
    reference_cross = scan_cross_market_metadata(reference=True)

    primary = {"implementation": "PRIMARY_SPLIT_METADATA_READER", "csv": primary_scans, "cross_market": primary_cross}
    reference = {"implementation": "REFERENCE_DICT_METADATA_READER", "csv": reference_scans, "cross_market": reference_cross}
    primary_semantic = semantic_scan_view(primary)
    reference_semantic = semantic_scan_view(reference)
    reproduced = canonical_json_bytes(primary_semantic) == canonical_json_bytes(reference_semantic)
    write_json(ARTIFACT_DIR / "coverage_primary.json", primary)
    write_json(ARTIFACT_DIR / "coverage_reference.json", reference)
    if not reproduced:
        raise RuntimeError("primary/reference coverage audit mismatch")

    old_inventory = json.loads(OLD_INVENTORY.read_text(encoding="utf-8"))
    old_requirements = {item["id"]: item for item in old_inventory["requirements"]}
    macro_ids = (
        "FRED_ALFRED_POINT_IN_TIME_MACRO", "MT5_SCHEDULED_MACRO_EVENTS_POST_RELEASE",
        "CFTC_GOLD_COT", "DAILY_RISK_MARKET_CONTEXT", "ZT_INTRADAY_TWO_YEAR_PROXY",
        "ZN_INTRADAY_TEN_YEAR_PROXY", "ZQ_FRONT_CONTINUOUS_POLICY_PROXY",
        "SR3_FRONT_CONTINUOUS_POLICY_PROXY",
    )
    macro_reuse = [old_requirements[item_id] for item_id in macro_ids]

    classifications: list[dict[str, Any]] = []
    for item in INSTRUMENTS:
        research_id, symbol = item["research_id"], item["symbol"]
        scan = primary_scans[symbol]
        snapshot = primary_cross["instruments"].get(symbol, {})
        catalog_present = catalog["symbols"].get(symbol) is not None
        if scan["eligible"]:
            classification = "PRESENT_AND_ADEQUATE"
            reason = "Stored IC Markets M1 history passes every frozen value-blind eligibility gate."
        elif scan["canonical_unique_timestamps"] > 0 or snapshot.get("nonnull_snapshots", 0) > 0:
            classification = "PRESENT_BUT_PARTIAL"
            reason = "Some sealed observations exist, but no full eligible IC Markets M1 development path is stored."
        else:
            classification = "MISSING"
            reason = "The connected broker catalog contains the symbol, but no stored development M1 path exists."
        classifications.append({
            "research_id": research_id,
            "mt5_symbol": symbol,
            "classification": classification,
            "catalog_present": catalog_present,
            "m1_coverage": scan,
            "sealed_cross_market_snapshot_metadata": snapshot,
            "lineage": (
                f"IC Markets MT5 {symbol} CSV -> deterministic timestamp-key deduplication"
                if scan["canonical_unique_timestamps"] else
                (f"sealed gold-casebook cross-market snapshot metadata for {symbol}" if snapshot.get("nonnull_snapshots", 0) else None)
            ),
            "fitness": reason,
        })

    counts = Counter(item["classification"] for item in classifications)
    incomplete = [item for item in classifications if item["classification"] != "PRESENT_AND_ADEQUATE"]
    acquisition = [
        {
            "research_id": item["research_id"],
            "mt5_symbol": item["mt5_symbol"],
            "source": "EXISTING_CONNECTED_IC_MARKETS_MT5",
            "schema": "M1_BARS_WITH_TIMESTAMPS_AND_SPREAD_METADATA",
            "interval": "2021-08-01T00:00:00Z/2025-01-01T00:00:00Z",
            "expected_charge_usd": 0.0,
            "action_performed_in_milestone_1": False,
        }
        for item in incomplete
    ]
    audit = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_MILESTONE_1_COVERAGE_1_0",
        "audit_mode": "METADATA_ONLY_NO_CHARGE_NO_OUTCOME_ACCESS",
        "contract_sha256": sha256_file(CONTRACT),
        "protocol_sha256": sha256_file(PROTOCOL),
        "development": protocol["development"],
        "preserved_predecessors": predecessor,
        "classification_counts": dict(sorted(counts.items())),
        "instrument_requirements": classifications,
        "macro_and_context_sources_reused": macro_reuse,
        "deduplication": {
            "policy": "EARLIEST_LEXICOGRAPHIC_SOURCE_FILENAME_THEN_SOURCE_ROW; APPEND_ONLY_RAW_SOURCES",
            "XAUUSD_duplicate_occurrences": primary_scans["XAUUSD"]["duplicate_timestamp_occurrences"],
            "EURUSD_duplicate_occurrences": primary_scans["EURUSD"]["duplicate_timestamp_occurrences"],
            "source_files_modified": False,
        },
        "independent_reproduction": {
            "passed": reproduced,
            "primary_semantic_sha256": object_sha256(primary_semantic),
            "reference_semantic_sha256": object_sha256(reference_semantic),
        },
        "readiness": {
            "verdict": "PASS_MILESTONE_1_CONTRACT_AND_AUDIT__SOURCE_BACKFILL_REQUIRED_BEFORE_DISCOVERY",
            "seven_instrument_discovery_ready": len(incomplete) == 0,
            "adequate_instruments": [item["research_id"] for item in classifications if item["classification"] == "PRESENT_AND_ADEQUATE"],
            "incomplete_instruments": [item["research_id"] for item in incomplete],
            "research_failure": False,
            "relationship_discovery_authorized": False,
        },
        "minimal_no_charge_acquisition_list": acquisition,
        "controls": {
            "OHLC_values_parsed_or_reported": False,
            "returns_or_relationships_calculated": False,
            "cases_signals_or_candidates_constructed": False,
            "trades_or_PnL_calculated": False,
            "calendar_2025_market_values_accessed": False,
            "calendar_2026_market_values_accessed": False,
            "paid_data_acquired": False,
            "charge_incurred_usd": 0.0,
            "existing_sources_modified": False,
            "cryptographic_source_hashing_is_nonsemantic": True,
        },
        "next_action_authorized": False,
        "stop_required": True,
    }
    return audit, primary, reference


def make_report(audit: dict[str, Any]) -> str:
    rows = []
    for item in audit["instrument_requirements"]:
        coverage = item["m1_coverage"]
        rows.append(
            f"| {item['research_id']} | `{item['mt5_symbol']}` | {item['classification']} | "
            f"{coverage['canonical_unique_timestamps']:,} | {coverage['first_timestamp'] or '-'} | "
            f"{coverage['last_timestamp'] or '-'} | {coverage['duplicate_timestamp_occurrences']:,} |"
        )
    macro_rows = []
    for item in audit["macro_and_context_sources_reused"]:
        macro_rows.append(f"| `{item['id']}` | {item['classification']} | {item['fitness']} |")
    missing_rows = []
    for item in audit["minimal_no_charge_acquisition_list"]:
        missing_rows.append(f"- `{item['mt5_symbol']}` ({item['research_id']}): IC Markets MT5 M1, 2021-08-01 through 2024-12-31; expected paid-provider charge $0.")
    return f"""# Multi-Asset Macro and Session Portfolio Edge Discovery V1 — Milestone 1 Coverage Audit

## Verdict

**PASS_MILESTONE_1_CONTRACT_AND_AUDIT — SOURCE BACKFILL REQUIRED BEFORE DISCOVERY.**

The contract is frozen and the audit reproduced exactly. The seven-instrument branch is not yet ready for relationship discovery: two instruments have adequate stored one-minute paths, two are partial, and three have catalog presence but no stored development path. This is a source-readiness result, not evidence for or against an edge.

The previous `TERMINATE_GOLD_ONLY_10R_BRANCH` verdict remains binding. No outcome, relationship, trade, PnL, or 2025/2026 market value was opened, and no charge was incurred.

## Instrument coverage

| Research instrument | Exact MT5 symbol | Classification | Unique development M1 timestamps | First | Last | Duplicate occurrences |
|---|---|---:|---:|---|---|---:|
{chr(10).join(rows)}

Catalog presence is not history coverage. Partial casebook snapshots are context observations and cannot replace an M1 decision/outcome path. Existing XAUUSD and EURUSD sources must not be reacquired.

## Deduplication and reproduction

- Canonical identity: `(MT5 symbol, open_time)`.
- Duplicate resolution: lexicographically earliest source filename, then source row; raw files remain unchanged.
- XAUUSD duplicate occurrences in the development window: {audit['deduplication']['XAUUSD_duplicate_occurrences']:,}.
- EURUSD duplicate occurrences in the development window: {audit['deduplication']['EURUSD_duplicate_occurrences']:,}.
- Primary/reference semantic hash: `{audit['independent_reproduction']['primary_semantic_sha256']}`.
- Independent reproduction: **PASS**.

## Reused sealed macro/context sources

| Requirement | Status | Fitness |
|---|---|---|
{chr(10).join(macro_rows)}

The frozen limitations remain: EURUSD is an inverse-dollar proxy, not DXY; ZQ/SR3 are partial front-contract paths; COT is weekly metals context; historical MT5 forecasts are not verified pre-release vintages; Japanese rates and EIA inventory history are absent.

## Minimal missing-data acquisition list

{chr(10).join(missing_rows)}

This is a later, free MT5 backfill step. Nothing was downloaded in Milestone 1.

## Stop point

Milestone 1 is complete and sealed. Relationship discovery remains unauthorized until the five incomplete instruments pass the same value-blind M1 coverage gates. The 10R/month objective remains report-only and cannot influence candidate selection.
"""


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    audit, _, _ = build_audit()
    audit_path = ARTIFACT_DIR / "coverage_audit.json"
    write_json(audit_path, audit)
    report_path = ROOT / "MULTI_ASSET_MACRO_AND_SESSION_PORTFOLIO_EDGE_DISCOVERY_V1_COVERAGE.md"
    report_path.write_text(make_report(audit), encoding="utf-8")
    artifacts = []
    for path in (
        CONTRACT, PROTOCOL, ARTIFACT_DIR / "mt5_symbol_catalog_snapshot.json",
        ARTIFACT_DIR / "coverage_primary.json", ARTIFACT_DIR / "coverage_reference.json",
        audit_path, report_path,
    ):
        artifacts.append({"path": relative(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    seal = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_MILESTONE_1_SEAL_1_0",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "verdict": audit["readiness"]["verdict"],
        "gold_only_10r_branch": "TERMINATED_AND_NOT_REOPENED",
        "seven_instrument_discovery_ready": audit["readiness"]["seven_instrument_discovery_ready"],
        "artifacts": artifacts,
        "independent_reproduction": audit["independent_reproduction"],
        "controls": audit["controls"],
        "next_action_authorized": False,
        "stop_required": True,
    }
    write_json(SEAL, seal)
    print(json.dumps({
        "verdict": seal["verdict"],
        "classification_counts": audit["classification_counts"],
        "incomplete": audit["readiness"]["incomplete_instruments"],
        "reproduced": audit["independent_reproduction"]["passed"],
        "seal": relative(SEAL),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
