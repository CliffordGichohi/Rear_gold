"""Acquire the five frozen Milestone-2 IC Markets M1 histories.

This utility talks only to the already-connected local MT5 terminal.  It never
submits an order, uploads data, requests a paid service, or requests timestamps
outside the frozen 2021-08-01 through 2024-12-31 development interval.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import MetaTrader5 as mt5


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")
PROTOCOL = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_m2_protocol.json"
M1_SEAL = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_milestone1_seal.json"
OUTPUT_DIR = ROOT / "data/mt5"
ARTIFACT_DIR = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2"
MANIFEST = ARTIFACT_DIR / "acquisition_manifest.json"
ATTEMPT_1_FAILURE = ARTIFACT_DIR / "attempt_1_failure.json"
START = datetime(2021, 8, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)
SYMBOLS = ("XAGUSD", "USDJPY", "USTEC", "US500", "XTIUSD")
CHUNK_DAYS = 60
MIN_FREE_BYTES = 5 * 1024**3

FIELDS = (
    "open_time", "close_time", "available_at", "open", "high", "low", "close",
    "volume", "volume_type", "spread_points", "real_volume",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ordered_existing_inventory(symbol: str) -> dict[str, Any]:
    files = sorted(OUTPUT_DIR.glob(f"{symbol.lower()}_1m_ic_markets_mt5_*.csv"))
    entries = [
        {"path": relative(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in files
    ]
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "file_count": len(entries),
        "bytes": sum(item["bytes"] for item in entries),
        "first_path": entries[0]["path"] if entries else None,
        "last_path": entries[-1]["path"] if entries else None,
        "ordered_inventory_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def verify_m1_seal() -> dict[str, Any]:
    seal = json.loads(M1_SEAL.read_text(encoding="utf-8"))
    checks = []
    for item in seal["artifacts"]:
        path = ROOT / item["path"]
        actual = sha256_file(path) if path.is_file() else None
        checks.append({
            "path": item["path"],
            "expected_sha256": item["sha256"],
            "actual_sha256": actual,
            "verified": actual == item["sha256"] and path.stat().st_size == item["bytes"] if path.exists() else False,
        })
    valid = (
        seal.get("verdict") == "PASS_MILESTONE_1_CONTRACT_AND_AUDIT__SOURCE_BACKFILL_REQUIRED_BEFORE_DISCOVERY"
        and seal.get("gold_only_10r_branch") == "TERMINATED_AND_NOT_REOPENED"
        and all(item["verified"] for item in checks)
    )
    return {"seal_sha256": sha256_file(M1_SEAL), "checks": checks, "verified": valid}


def chunk_intervals() -> list[tuple[datetime, datetime]]:
    result: list[tuple[datetime, datetime]] = []
    cursor = START
    while cursor < END:
        stop = min(cursor + timedelta(days=CHUNK_DAYS), END)
        result.append((cursor, stop))
        cursor = stop
    return result


def preflight() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if tuple(protocol["acquisition"]["mt5_symbols"]) != SYMBOLS:
        raise RuntimeError("frozen symbol list differs from implementation")
    if protocol["acquisition"]["start_inclusive"] != START.isoformat().replace("+00:00", "Z"):
        raise RuntimeError("frozen start differs from implementation")
    if protocol["acquisition"]["end_exclusive"] != END.isoformat().replace("+00:00", "Z"):
        raise RuntimeError("frozen end differs from implementation")
    if protocol["acquisition"]["chunk_days"] != CHUNK_DAYS:
        raise RuntimeError("frozen chunk size differs from implementation")
    if protocol["controls"]["maximum_paid_charge_usd"] != 0.0:
        raise RuntimeError("protocol permits a charge")
    predecessor = verify_m1_seal()
    if not predecessor["verified"]:
        raise RuntimeError("Milestone-1 predecessor verification failed")
    free = shutil.disk_usage(ROOT).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(f"insufficient free disk: {free} bytes")
    existing = {symbol: _ordered_existing_inventory(symbol) for symbol in SYMBOLS}
    recovery = None
    if any(item["file_count"] for item in existing.values()):
        if not ATTEMPT_1_FAILURE.is_file():
            raise RuntimeError("target history exists without a sealed interrupted-attempt record")
        failure = json.loads(ATTEMPT_1_FAILURE.read_text(encoding="utf-8"))
        if failure.get("verdict") != "FAIL_EXTERNAL_COMMAND_TIMEOUT_DURING_FROZEN_ACQUISITION":
            raise RuntimeError("existing history is not bound to the permitted timeout recovery")
        expected = failure["symbols"]
        mismatches = [symbol for symbol in SYMBOLS if existing[symbol] != expected[symbol]]
        if mismatches:
            raise RuntimeError(f"interrupted source inventory changed: {mismatches}")
        current_temporaries = []
        for item in failure["temporary_files"]:
            path = ROOT / item["path"]
            current_temporaries.append(
                path.is_file() and path.stat().st_size == item["bytes"] and sha256_file(path) == item["sha256"]
            )
        if not all(current_temporaries):
            raise RuntimeError("interrupted temporary source changed")
        recovery = {
            "attempt_1_failure_sha256": sha256_file(ATTEMPT_1_FAILURE),
            "existing_inventory_verified": True,
            "temporary_inventory_verified": True,
        }
    return {
        "protocol_sha256": sha256_file(PROTOCOL),
        "predecessor": predecessor,
        "free_bytes_before": free,
        "minimum_free_bytes": MIN_FREE_BYTES,
        "target_files_existing_before": existing,
        "timeout_recovery": recovery,
        "exact_chunk_count_per_symbol": len(chunk_intervals()),
        "exact_total_request_count": len(chunk_intervals()) * len(SYMBOLS),
    }


def _write_source_csv(destination: Path, rows: Iterable[Any]) -> tuple[bool, str]:
    """Write once atomically; an existing path may only be reused byte-identically."""
    temporary = destination.with_suffix(".tmp")
    if temporary.exists():
        quarantine = ARTIFACT_DIR / "interrupted_temporary_files" / f"{temporary.name}.attempt_1"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        if quarantine.exists():
            raise RuntimeError(f"temporary-file quarantine collision: {quarantine}")
        temporary.replace(quarantine)
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            opened = datetime.fromtimestamp(int(row["time"]), UTC)
            closed = opened + timedelta(minutes=1)
            writer.writerow({
                "open_time": opened.isoformat(),
                "close_time": closed.isoformat(),
                "available_at": closed.isoformat(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": int(row["tick_volume"]),
                "volume_type": "TICK",
                "spread_points": int(row["spread"]),
                "real_volume": int(row["real_volume"]),
            })
    generated_hash = sha256_file(temporary)
    if destination.exists():
        if sha256_file(destination) != generated_hash:
            temporary.unlink()
            raise RuntimeError(f"source-preservation conflict at {destination}")
        temporary.unlink()
        return False, generated_hash
    temporary.replace(destination)
    return True, generated_hash


def acquire_symbol(symbol: str) -> dict[str, Any]:
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"MT5 symbol unavailable: {symbol}; error={mt5.last_error()}")
    files: list[dict[str, Any]] = []
    total_rows = 0
    first: datetime | None = None
    last: datetime | None = None
    empty_chunks: list[dict[str, str]] = []
    provider_requests_made = 0
    for request_number, (start, stop) in enumerate(chunk_intervals(), start=1):
        existing = []
        for path in OUTPUT_DIR.glob(f"{symbol.lower()}_1m_ic_markets_mt5_*.csv"):
            stem_parts = path.stem.split("_")
            if len(stem_parts) < 2:
                continue
            try:
                path_first = datetime.strptime(stem_parts[-2], "%Y%m%dT%H%M").replace(tzinfo=UTC)
                path_last = datetime.strptime(stem_parts[-1], "%Y%m%dT%H%M").replace(tzinfo=UTC)
            except ValueError:
                continue
            if start <= path_first < stop and start <= path_last < stop:
                existing.append((path, path_first, path_last))
        if len(existing) > 1:
            raise RuntimeError(f"multiple preserved files map to {symbol} request {request_number}")
        if existing:
            destination, chunk_first, chunk_last = existing[0]
            with destination.open("rb") as stream:
                existing_rows = max(0, sum(1 for _ in stream) - 1)
            files.append({
                "request_number": request_number,
                "request_start": start.isoformat().replace("+00:00", "Z"),
                "request_end_exclusive": stop.isoformat().replace("+00:00", "Z"),
                "path": relative(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "rows": existing_rows,
                "first_open_time": chunk_first.isoformat().replace("+00:00", "Z"),
                "last_open_time": chunk_last.isoformat().replace("+00:00", "Z"),
                "created": False,
                "preserved_from_interrupted_attempt": True,
            })
            total_rows += existing_rows
            first = chunk_first if first is None or chunk_first < first else first
            last = chunk_last if last is None or chunk_last > last else last
            continue
        provider_requests_made += 1
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start, stop)
        if rates is None:
            raise RuntimeError(
                f"MT5 request failed for {symbol} [{start.isoformat()}, {stop.isoformat()}): {mt5.last_error()}"
            )
        completed = [
            row for row in rates
            if start <= datetime.fromtimestamp(int(row["time"]), UTC) < stop
            and datetime.fromtimestamp(int(row["time"]), UTC) + timedelta(minutes=1) <= END
        ]
        if not completed:
            empty_chunks.append({"start": start.isoformat(), "end_exclusive": stop.isoformat()})
            continue
        chunk_first = datetime.fromtimestamp(int(completed[0]["time"]), UTC)
        chunk_last = datetime.fromtimestamp(int(completed[-1]["time"]), UTC)
        destination = OUTPUT_DIR / (
            f"{symbol.lower()}_1m_ic_markets_mt5_"
            f"{chunk_first:%Y%m%dT%H%M}_{chunk_last:%Y%m%dT%H%M}.csv"
        )
        created, digest = _write_source_csv(destination, completed)
        files.append({
            "request_number": request_number,
            "request_start": start.isoformat().replace("+00:00", "Z"),
            "request_end_exclusive": stop.isoformat().replace("+00:00", "Z"),
            "path": relative(destination),
            "bytes": destination.stat().st_size,
            "sha256": digest,
            "rows": len(completed),
            "first_open_time": chunk_first.isoformat().replace("+00:00", "Z"),
            "last_open_time": chunk_last.isoformat().replace("+00:00", "Z"),
            "created": created,
        })
        total_rows += len(completed)
        first = chunk_first if first is None or chunk_first < first else first
        last = chunk_last if last is None or chunk_last > last else last
    if not files:
        raise RuntimeError(f"MT5 returned no completed development bars for {symbol}")
    return {
        "symbol": symbol,
        "requested_start_inclusive": START.isoformat().replace("+00:00", "Z"),
        "requested_end_exclusive": END.isoformat().replace("+00:00", "Z"),
        "request_count": len(chunk_intervals()),
        "provider_requests_made_in_this_run": provider_requests_made,
        "file_count": len(files),
        "rows": total_rows,
        "first_open_time": first.isoformat().replace("+00:00", "Z") if first else None,
        "last_open_time": last.isoformat().replace("+00:00", "Z") if last else None,
        "empty_chunks": empty_chunks,
        "files": files,
    }


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    readiness = preflight()
    started = datetime.now(UTC)
    if not mt5.initialize(path=str(TERMINAL)):
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
    try:
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            raise RuntimeError("MT5 terminal has no connected broker session")
        symbol_results = [acquire_symbol(symbol) for symbol in SYMBOLS]
    finally:
        mt5.shutdown()
    manifest = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M2_ACQUISITION_1_0",
        "provider": "IC_MARKETS_MT5_LOCAL_CONNECTED_TERMINAL",
        "schema": "NORMALIZED_M1_CSV_1_0",
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "preflight": readiness,
        "symbols": symbol_results,
        "source_preservation": "WRITE_ONCE_ATOMIC; EXISTING_DIFFERENT_BYTES_REJECTED",
        "controls": {
            "only_frozen_symbols_requested": True,
            "requested_2025_or_2026_timestamps": False,
            "calendar_2025_or_2026_values_written_or_reported": False,
            "orders_or_trades_submitted": False,
            "api_upload_performed": False,
            "paid_provider_called": False,
            "charge_incurred_usd": 0.0,
            "OHLC_values_humanly_inspected_or_reported": False,
            "relationships_trades_or_PnL_calculated": False,
            "XAUUSD_or_EURUSD_requested": False,
        },
        "free_bytes_after": shutil.disk_usage(ROOT).free,
        "certification_pending": True,
    }
    write_json(MANIFEST, manifest)
    print(json.dumps({
        "status": "PASS_FROZEN_NO_CHARGE_MT5_ACQUISITION",
        "symbols": {item["symbol"]: {"rows": item["rows"], "files": item["file_count"]} for item in symbol_results},
        "requests": sum(item["request_count"] for item in symbol_results),
        "charge_usd": 0.0,
        "manifest": relative(MANIFEST),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
