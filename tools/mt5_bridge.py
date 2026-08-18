"""Read-only IC Markets MT5 bridge for the Gold Intelligence Engine.

This process must run natively on Windows because MetaTrader5 uses local IPC with
the terminal. It never calls order_send and reuses the account session already
saved in the terminal.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5
import requests

DEFAULT_TERMINAL = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")
DEFAULT_API = "http://localhost:8000/api/v1"


def main() -> int:
    args = _parser().parse_args()
    if not _initialize(Path(args.terminal_path)):
        return 1
    try:
        if args.command == "status":
            print(json.dumps(_safe_status(args.symbol), indent=2))
            return 0
        if args.command == "symbols":
            print(json.dumps(_matching_symbols(args.query), indent=2))
            return 0
        return _history(args)
    finally:
        mt5.shutdown()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only Windows bridge from a logged-in MT5 terminal."
    )
    parser.add_argument(
        "--terminal-path",
        default=str(DEFAULT_TERMINAL),
        help="Path to terminal64.exe.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Check the safe connection state.")
    status.add_argument("--symbol", default="XAUUSD")

    symbols = subparsers.add_parser(
        "symbols",
        help="Search the connected broker's read-only instrument catalog.",
    )
    symbols.add_argument(
        "--query",
        default="FED,FEDERAL FUNDS,SOFR,ZQ",
        help="Comma-separated case-insensitive terms matched against symbol metadata.",
    )

    history = subparsers.add_parser(
        "history",
        help="Export completed one-minute bars and optionally upload them.",
    )
    history.add_argument("--symbol", default="XAUUSD")
    history.add_argument("--days", type=_history_days, default=30)
    history.add_argument(
        "--start",
        type=_iso_datetime,
        help=(
            "Inclusive UTC history start. When provided, --days is ignored; "
            "use with --end for an exact resumable interval."
        ),
    )
    history.add_argument(
        "--chunk-days",
        type=_chunk_days,
        default=30,
        help=(
            "Maximum calendar span per MT5 request/file. Keep below 70 days "
            "because the terminal rejects ranges above about 100,000 minutes."
        ),
    )
    end_group = history.add_mutually_exclusive_group()
    end_group.add_argument(
        "--end",
        type=_iso_datetime,
        help="Exclusive UTC history endpoint, for example 2026-06-23T08:15:00Z.",
    )
    end_group.add_argument(
        "--before-existing",
        action="store_true",
        help=(
            "Use the API's earliest stored real IC Markets bar as the exclusive "
            "endpoint, allowing overlap-free backfill."
        ),
    )
    end_group.add_argument(
        "--after-existing",
        action="store_true",
        help=(
            "Use the API's latest stored real IC Markets bar close as the inclusive "
            "start, allowing an overlap-free append through the current UTC minute."
        ),
    )
    history.add_argument("--api-url", default=DEFAULT_API)
    history.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "data" / "mt5"),
    )
    history.add_argument("--no-upload", action="store_true")
    return parser


def _initialize(terminal_path: Path) -> bool:
    if not terminal_path.is_file():
        print(
            json.dumps({"ok": False, "error": f"MT5 terminal not found: {terminal_path}"}),
            file=sys.stderr,
        )
        return False
    if not mt5.initialize(path=str(terminal_path)):
        print(
            json.dumps({"ok": False, "error": "MT5 initialize failed", "code": mt5.last_error()}),
            file=sys.stderr,
        )
        return False
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None or not terminal.connected:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "MT5 is open but no connected account session is available.",
                }
            ),
            file=sys.stderr,
        )
        return False
    return True


def _safe_status(symbol: str) -> dict[str, Any]:
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    selected = mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol) if selected else None
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 3) if selected else None
    trade_mode = getattr(account, "trade_mode", None)
    return {
        "ok": True,
        "connected": bool(getattr(terminal, "connected", False)),
        "terminal_build": getattr(terminal, "build", None),
        "max_bars_in_chart": getattr(terminal, "maxbars", None),
        "environment": {0: "DEMO", 1: "CONTEST", 2: "LIVE"}.get(trade_mode, "UNKNOWN"),
        "broker_company": getattr(account, "company", None),
        "server": getattr(account, "server", None),
        "symbol": symbol,
        "symbol_selected": selected,
        "tick_available": tick is not None,
        "recent_m1_bars": 0 if rates is None else len(rates),
        "permissions": "READ_ONLY_BRIDGE_POLICY",
    }


def _matching_symbols(query: str) -> dict[str, Any]:
    terms = tuple(term.strip().casefold() for term in query.split(",") if term.strip())
    if not terms:
        return {"ok": False, "error": "At least one symbol search term is required."}
    symbols = mt5.symbols_get()
    if symbols is None:
        return {
            "ok": False,
            "error": "MT5 could not return the broker instrument catalog.",
            "code": mt5.last_error(),
        }
    matches: list[dict[str, Any]] = []
    for symbol in symbols:
        searchable = " ".join(
            str(getattr(symbol, field, "") or "")
            for field in ("name", "description", "path", "basis")
        ).casefold()
        matched_terms = [term for term in terms if term in searchable]
        if not matched_terms:
            continue
        matches.append(
            {
                "name": getattr(symbol, "name", None),
                "description": getattr(symbol, "description", None),
                "path": getattr(symbol, "path", None),
                "digits": getattr(symbol, "digits", None),
                "point": getattr(symbol, "point", None),
                "spread_points": getattr(symbol, "spread", None),
                "spread_is_floating": getattr(symbol, "spread_float", None),
                "contract_size": getattr(symbol, "trade_contract_size", None),
                "tick_size": getattr(symbol, "trade_tick_size", None),
                "tick_value": getattr(symbol, "trade_tick_value", None),
                "tick_value_profit": getattr(symbol, "trade_tick_value_profit", None),
                "tick_value_loss": getattr(symbol, "trade_tick_value_loss", None),
                "currency_base": getattr(symbol, "currency_base", None),
                "currency_profit": getattr(symbol, "currency_profit", None),
                "currency_margin": getattr(symbol, "currency_margin", None),
                "volume_min": getattr(symbol, "volume_min", None),
                "volume_max": getattr(symbol, "volume_max", None),
                "volume_step": getattr(symbol, "volume_step", None),
                "matched_terms": matched_terms,
            }
        )
    return {
        "ok": True,
        "terms": list(terms),
        "catalog_size": len(symbols),
        "match_count": len(matches),
        "matches": matches,
        "permissions": "READ_ONLY_BRIDGE_POLICY",
    }


def _history(args: argparse.Namespace) -> int:
    symbol = str(args.symbol).upper()
    if not mt5.symbol_select(symbol, True):
        return _error(f"MT5 symbol is unavailable: {symbol}")
    api_url = str(args.api_url).rstrip("/")
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    if args.start is not None and (
        args.before_existing or args.after_existing
    ):
        return _error(
            "--start cannot be combined with --before-existing or "
            "--after-existing"
        )
    if args.before_existing:
        end = _existing_earliest(
            api_url=api_url,
            symbol=symbol,
        )
        end = min(end.astimezone(UTC), now)
        start = end - timedelta(days=int(args.days))
    elif args.after_existing:
        end = now
        start = _existing_latest(
            api_url=api_url,
            symbol=symbol,
        )
    else:
        end = args.end or now
        end = min(end.astimezone(UTC), now)
        start = (
            args.start.astimezone(UTC)
            if args.start is not None
            else end - timedelta(days=int(args.days))
        )
    if start >= end:
        return _error(
            f"No append interval exists: start {start.isoformat()} is not before "
            f"end {end.isoformat()}."
        )
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    ingestions: list[dict[str, Any]] = []
    first_time: datetime | None = None
    last_time: datetime | None = None
    bar_count = 0
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=int(args.chunk_days)), end)
        rates = mt5.copy_rates_range(
            symbol,
            mt5.TIMEFRAME_M1,
            cursor,
            chunk_end,
        )
        if rates is None:
            return _error(
                f"MT5 history request failed for {cursor.isoformat()} through "
                f"{chunk_end.isoformat()}; MT5 error={mt5.last_error()}"
            )
        completed = [
            row
            for row in rates
            if cursor <= datetime.fromtimestamp(int(row["time"]), UTC) < chunk_end
            and datetime.fromtimestamp(int(row["time"]), UTC) + timedelta(minutes=1) <= end
        ]
        if completed:
            chunk_first = datetime.fromtimestamp(int(completed[0]["time"]), UTC)
            chunk_last = datetime.fromtimestamp(int(completed[-1]["time"]), UTC)
            filename = (
                f"{symbol.lower()}_1m_ic_markets_mt5_"
                f"{chunk_first:%Y%m%dT%H%M}_{chunk_last:%Y%m%dT%H%M}.csv"
            )
            destination = output_dir / filename
            _write_csv(destination, completed)
            files.append(destination)
            bar_count += len(completed)
            first_time = min(first_time, chunk_first) if first_time else chunk_first
            last_time = max(last_time, chunk_last) if last_time else chunk_last
            if not args.no_upload:
                ingestions.append(
                    _upload(
                        destination,
                        api_url=api_url,
                        dataset_code=f"{symbol}_1M",
                    )
                )
        cursor = chunk_end

    if not files or first_time is None or last_time is None:
        return _error(
            f"No completed {symbol} one-minute history was returned for "
            f"{start.isoformat()} through {end.isoformat()}."
        )

    status: dict[str, Any] = {
        **_safe_status(symbol),
        "requested_start": start.isoformat(),
        "requested_end_exclusive": end.isoformat(),
        "chunk_days": int(args.chunk_days),
        "files": [str(path) for path in files],
        "bars": bar_count,
        "first_open_time": first_time.isoformat(),
        "last_open_time": last_time.isoformat(),
        "requested_coverage_complete": first_time <= start + timedelta(minutes=1),
        "leading_history_shortfall_days": round(
            max(0.0, (first_time - start).total_seconds() / 86_400),
            3,
        ),
        "uploaded": not args.no_upload,
    }
    if len(files) == 1:
        status["file"] = str(files[0])
    if ingestions:
        status["ingestions"] = ingestions
        status["inserted_records"] = sum(int(item["record_count"]) for item in ingestions)
    print(json.dumps(status, indent=2))
    return 0


def _write_csv(destination: Path, rows: list[Any]) -> None:
    temporary = destination.with_suffix(".tmp")
    fields = [
        "open_time",
        "close_time",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "volume_type",
        "spread_points",
        "real_volume",
    ]
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            open_time = datetime.fromtimestamp(int(row["time"]), UTC)
            close_time = open_time + timedelta(minutes=1)
            writer.writerow(
                {
                    "open_time": open_time.isoformat(),
                    "close_time": close_time.isoformat(),
                    "available_at": close_time.isoformat(),
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": int(row["tick_volume"]),
                    "volume_type": "TICK",
                    "spread_points": int(row["spread"]),
                    "real_volume": int(row["real_volume"]),
                }
            )
    temporary.replace(destination)


def _upload(
    path: Path,
    *,
    api_url: str,
    dataset_code: str,
) -> dict[str, Any]:
    response: requests.Response | None = None
    for attempt in range(3):
        try:
            with path.open("rb") as stream:
                response = requests.post(
                    f"{api_url}/ingestions/files",
                    files={"file": (path.name, stream, "text/csv")},
                    data={
                        "provider_code": "IC_MARKETS_MT5",
                        "dataset_code": dataset_code,
                        "schema_version": "1",
                        "is_synthetic": "false",
                    },
                    timeout=240,
                )
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
            continue
        if response.status_code < 500 or attempt == 2:
            break
        time.sleep(2**attempt)
    if response is None:
        raise RuntimeError("Ingestion request produced no response")
    if response.status_code != 201:
        raise RuntimeError(
            f"Ingestion failed with HTTP {response.status_code}: {response.text[:500]}"
        )
    payload = response.json()
    return {
        "batch_id": payload["batch_id"],
        "duplicate": payload["duplicate"],
        "record_count": payload["record_count"],
        "quality_issue_count": payload["quality_issue_count"],
        "status": payload["status"],
    }


def _existing_earliest(*, api_url: str, symbol: str) -> datetime:
    return _existing_boundary(
        api_url=api_url,
        symbol=symbol,
        field="earliest",
        option="--before-existing",
    )


def _existing_latest(*, api_url: str, symbol: str) -> datetime:
    return _existing_boundary(
        api_url=api_url,
        symbol=symbol,
        field="latest",
        option="--after-existing",
    )


def _existing_boundary(
    *,
    api_url: str,
    symbol: str,
    field: str,
    option: str,
) -> datetime:
    response = requests.get(
        f"{api_url}/backtests/data-range",
        params={
            "instrument": symbol,
            "provider_code": "IC_MARKETS_MT5",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            "Could not obtain the existing MT5 data range: "
            f"HTTP {response.status_code}: {response.text[:500]}"
        )
    boundary = response.json().get(field)
    if not isinstance(boundary, str) or not boundary:
        raise RuntimeError(f"{option} requires at least one stored IC Markets price bar.")
    return _iso_datetime(boundary)


def _iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "timestamp must be ISO-8601, for example 2026-06-23T08:15:00Z"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _history_days(value: str) -> int:
    return _bounded_integer(value, minimum=1, maximum=1825, label="days")


def _chunk_days(value: str) -> int:
    return _bounded_integer(value, minimum=1, maximum=69, label="chunk-days")


def _bounded_integer(
    value: str,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _error(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
