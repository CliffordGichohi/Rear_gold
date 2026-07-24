"""Collect and audit the read-only MetaTrader 5 economic-calendar export.

The MQL5 calendar API is not exposed by the MetaTrader5 Python package and cannot
run in Strategy Tester. ``GoldIntelCalendarExport.mq5`` therefore writes a raw CSV
inside MT5's Common/Files sandbox. This host-side utility copies that immutable
export into the repository and performs a schema and coverage audit before any
normalization or database ingestion is allowed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5
import requests

BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from gold_intel.providers.mt5_calendar import (  # noqa: E402
    MT5_KE_TIMEZONE_POLICY,
    Mt5Calendar,
    mt5_calendar_bundles,
    parse_mt5_calendar_export,
)

DEFAULT_TERMINAL = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")
DEFAULT_API = "http://localhost:8000/api/v1"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "mt5" / "calendar"
RAW_RELATIVE_PATH = Path("Files") / "GoldIntel" / "mt5_us_calendar_raw.csv"
STATUS_RELATIVE_PATH = Path("Files") / "GoldIntel" / "mt5_us_calendar_status.csv"

EXPECTED_RAW_FIELDS = (
    "schema_version",
    "exported_at_server",
    "exported_at_gmt",
    "current_server_utc_offset_seconds",
    "terminal_build",
    "chunk_from_server",
    "chunk_to_server",
    "value_id",
    "event_id",
    "event_time_server",
    "observation_period_server",
    "revision",
    "actual_value",
    "previous_value",
    "revised_previous_value",
    "forecast_value",
    "impact_type",
    "event_type",
    "sector",
    "frequency",
    "time_mode",
    "country_id",
    "country_code",
    "country_name",
    "currency",
    "unit",
    "importance",
    "multiplier",
    "digits",
    "event_code",
    "event_name",
    "source_url",
)

REQUIRED_FAMILY_TERMS: dict[str, tuple[str, ...]] = {
    "CPI": ("consumer price", "cpi"),
    "CORE_CPI": ("core consumer price", "core cpi"),
    "PCE": ("pce price", "personal consumption expenditures price"),
    "CORE_PCE": ("core pce",),
    "NFP": ("nonfarm payroll", "non-farm payroll"),
    "UNEMPLOYMENT": ("unemployment rate",),
    "WAGES": ("average hourly earnings",),
    "JOBLESS_CLAIMS": ("initial jobless claims",),
    "GDP": ("gross domestic product", "gdp"),
    "RETAIL_SALES": ("retail sales",),
    "FED_RATE": ("interest rate decision", "federal funds rate", "fed funds rate"),
}


@dataclass(frozen=True, slots=True)
class RawAudit:
    report: dict[str, Any]
    canonical_rows: tuple[dict[str, str], ...]


def main() -> int:
    args = _parser().parse_args()
    if args.command == "collect":
        return _collect(args)
    if args.command == "audit":
        audit = audit_raw_export(Path(args.input).resolve())
        print(json.dumps(audit.report, indent=2))
        return 0 if audit.report["valid"] else 1
    if args.command == "normalize":
        return _normalize_command(args, upload=False)
    if args.command == "upload":
        return _normalize_command(args, upload=True)
    raise AssertionError(f"Unsupported command: {args.command}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect and audit the Gold Intelligence MT5 calendar export."
    )
    parser.add_argument(
        "--terminal-path",
        default=str(DEFAULT_TERMINAL),
        help="Path to the connected terminal64.exe.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser(
        "collect",
        help="Copy the completed MT5 export into data/mt5/calendar and audit it.",
    )
    collect.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))

    audit = subparsers.add_parser("audit", help="Audit an existing raw calendar CSV.")
    audit.add_argument("input")

    for command, help_text in (
        (
            "normalize",
            "Normalize approved gold-macro events into annual point-in-time bundles.",
        ),
        (
            "upload",
            "Normalize and upload annual bundles through the idempotent event API.",
        ),
    ):
        normalizer = subparsers.add_parser(command, help=help_text)
        normalizer.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
        if command == "upload":
            normalizer.add_argument("--api-url", default=DEFAULT_API)
    return parser


def _collect(args: argparse.Namespace) -> int:
    common_path = _mt5_common_path(Path(args.terminal_path))
    if common_path is None:
        return 1
    source_raw = common_path / RAW_RELATIVE_PATH
    source_status = common_path / STATUS_RELATIVE_PATH
    if not source_raw.is_file() or not source_status.is_file():
        return _error(
            "The MT5 calendar export is not complete. Run "
            "Scripts/GoldIntel/GoldIntelCalendarExport in the connected terminal first."
        )

    status_rows = _read_csv(source_status)
    if len(status_rows) != 1:
        return _error("The MT5 calendar status file must contain exactly one result row.")
    status = status_rows[0]
    failed_chunks = _required_int(status, "chunks_failed")
    rows_written = _required_int(status, "rows_written")
    if failed_chunks:
        return _error(
            f"MT5 reported {failed_chunks} failed calendar chunks; source error "
            f"{status.get('last_error') or 'UNKNOWN'}."
        )

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_destination = output_dir / "mt5_us_calendar_raw.csv"
    status_destination = output_dir / "mt5_us_calendar_status.csv"
    _atomic_copy(source_raw, raw_destination)
    _atomic_copy(source_status, status_destination)

    audit = audit_raw_export(raw_destination)
    report = {
        **audit.report,
        "mt5_status": status,
        "reported_rows_written": rows_written,
        "row_count_matches_status": (
            audit.report["raw_row_count"] == rows_written
        ),
        "repository_raw_path": str(raw_destination),
        "repository_status_path": str(status_destination),
    }
    report["valid"] = bool(
        report["valid"]
        and report["row_count_matches_status"]
        and failed_chunks == 0
    )
    audit_path = output_dir / "mt5_us_calendar_audit.json"
    audit_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report["audit_path"] = str(audit_path)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


def audit_raw_export(path: Path) -> RawAudit:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = _read_csv(path)
    if not rows:
        return RawAudit(
            report={
                "valid": False,
                "error": "The raw export contains no calendar rows.",
                "raw_row_count": 0,
            },
            canonical_rows=(),
        )

    fields = tuple(rows[0])
    missing_fields = sorted(set(EXPECTED_RAW_FIELDS) - set(fields))
    unexpected_fields = sorted(set(fields) - set(EXPECTED_RAW_FIELDS))
    canonical: dict[str, dict[str, str]] = {}
    conflicting_ids: list[str] = []
    duplicate_count = 0
    for row in rows:
        value_id = row.get("value_id", "").strip()
        if not value_id:
            continue
        existing = canonical.get(value_id)
        if existing is None:
            canonical[value_id] = row
            continue
        duplicate_count += 1
        if _semantic_row(existing) != _semantic_row(row):
            conflicting_ids.append(value_id)

    canonical_rows = tuple(
        sorted(
            canonical.values(),
            key=lambda item: (
                item["event_time_server"],
                item["event_id"],
                item["value_id"],
            ),
        )
    )
    names: dict[str, dict[str, Any]] = {}
    for row in canonical_rows:
        name = row["event_name"].strip()
        item = names.setdefault(
            name,
            {
                "event_ids": set(),
                "rows": 0,
                "actual_rows": 0,
                "forecast_rows": 0,
                "first_server_time": row["event_time_server"],
                "last_server_time": row["event_time_server"],
            },
        )
        item["event_ids"].add(row["event_id"])
        item["rows"] += 1
        item["actual_rows"] += bool(row["actual_value"].strip())
        item["forecast_rows"] += bool(row["forecast_value"].strip())
        item["first_server_time"] = min(
            item["first_server_time"], row["event_time_server"]
        )
        item["last_server_time"] = max(
            item["last_server_time"], row["event_time_server"]
        )

    family_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, statistics in names.items():
        normalized = _normalized_name(name)
        for family, terms in REQUIRED_FAMILY_TERMS.items():
            if any(term in normalized for term in terms):
                family_candidates[family].append(
                    {
                        "event_name": name,
                        "event_ids": sorted(statistics["event_ids"]),
                        "rows": statistics["rows"],
                        "actual_rows": statistics["actual_rows"],
                        "forecast_rows": statistics["forecast_rows"],
                        "first_server_time": statistics["first_server_time"],
                        "last_server_time": statistics["last_server_time"],
                    }
                )

    for candidates in family_candidates.values():
        candidates.sort(key=lambda item: (-item["rows"], item["event_name"]))

    actual_count = sum(bool(row["actual_value"].strip()) for row in canonical_rows)
    forecast_count = sum(bool(row["forecast_value"].strip()) for row in canonical_rows)
    report: dict[str, Any] = {
        "valid": not missing_fields and not conflicting_ids and bool(canonical_rows),
        "source_path": str(path),
        "source_sha256": _sha256(path),
        "schema_version": rows[0].get("schema_version"),
        "raw_row_count": len(rows),
        "unique_value_count": len(canonical_rows),
        "duplicate_row_count": duplicate_count,
        "conflicting_value_ids": sorted(set(conflicting_ids)),
        "missing_fields": missing_fields,
        "unexpected_fields": unexpected_fields,
        "event_definition_count": len(names),
        "first_server_time": canonical_rows[0]["event_time_server"],
        "last_server_time": canonical_rows[-1]["event_time_server"],
        "actual_value_count": actual_count,
        "forecast_value_count": forecast_count,
        "actual_coverage_percent": round(100 * actual_count / len(canonical_rows), 2),
        "forecast_coverage_percent": round(
            100 * forecast_count / len(canonical_rows), 2
        ),
        "required_family_candidates": dict(sorted(family_candidates.items())),
        "missing_required_families": sorted(
            set(REQUIRED_FAMILY_TERMS) - set(family_candidates)
        ),
    }
    return RawAudit(report=report, canonical_rows=canonical_rows)


def _normalize_command(args: argparse.Namespace, *, upload: bool) -> int:
    output_dir = Path(args.output_dir).resolve()
    raw_path = output_dir / "mt5_us_calendar_raw.csv"
    status_path = output_dir / "mt5_us_calendar_status.csv"
    if not raw_path.is_file() or not status_path.is_file():
        return _error("Run the collect command before normalization.")
    status_rows = _read_csv(status_path)
    if len(status_rows) != 1:
        return _error("The MT5 calendar status file must contain one row.")
    server_offset = _required_int(status_rows[0], "current_server_utc_offset_seconds")
    calendar = parse_mt5_calendar_export(
        raw_path,
        server_utc_offset_seconds=server_offset,
        timezone_policy=MT5_KE_TIMEZONE_POLICY,
    )
    bundles = mt5_calendar_bundles(calendar)
    bundle_paths: list[str] = []
    for bundle in bundles:
        destination = output_dir / f"{bundle['dataset_code'].lower()}.json"
        destination.write_text(
            json.dumps(bundle, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        bundle_paths.append(str(destination))

    upload_results: list[dict[str, Any]] = []
    if upload:
        api_url = str(args.api_url).rstrip("/")
        for bundle in bundles:
            response = requests.post(
                f"{api_url}/events/bundles",
                json=bundle,
                timeout=240,
            )
            if response.status_code != 201:
                return _error(
                    f"Event bundle {bundle['dataset_code']} failed with HTTP "
                    f"{response.status_code}: {response.text[:500]}"
                )
            response_payload = response.json()
            exclusion_counts = Counter(
                exclusion.get("reason", "UNKNOWN")
                for exclusion in response_payload.get("surprise_exclusions", [])
            )
            upload_results.append(
                {
                    "dataset_code": response_payload["dataset_code"],
                    "batch_id": response_payload["batch_id"],
                    "duplicate": response_payload["duplicate"],
                    "event_count": response_payload["event_count"],
                    "forecast_count": response_payload["forecast_count"],
                    "release_count": response_payload["release_count"],
                    "surprise_count": response_payload["surprise_count"],
                    "surprise_exclusion_counts": dict(sorted(exclusion_counts.items())),
                }
            )

    report = _normalization_report(calendar)
    report.update(
        {
            "bundle_count": len(bundles),
            "bundle_paths": bundle_paths,
            "uploaded": upload,
            "upload_results": upload_results,
        }
    )
    report_path = output_dir / "mt5_us_calendar_normalization.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report["report_path"] = str(report_path)
    print(json.dumps(report, indent=2))
    return 0


def _normalization_report(calendar: Mt5Calendar) -> dict[str, Any]:
    component_rows: Counter[str] = Counter()
    component_actuals: Counter[str] = Counter()
    component_forecasts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for event in calendar.events:
        status_counts[event.status] += 1
        for component in event.components:
            code = component.specification.component_code
            component_rows[code] += 1
            component_actuals[code] += component.actual_value is not None
            component_forecasts[code] += component.forecast_value is not None
    components = {
        code: {
            "rows": component_rows[code],
            "actual_rows": component_actuals[code],
            "forecast_rows": component_forecasts[code],
        }
        for code in sorted(component_rows)
    }
    return {
        "valid": True,
        "provider_code": "METAQUOTES_MT5_CALENDAR",
        "retrieved_at": calendar.retrieved_at.isoformat(),
        "source_sha256": calendar.source_sha256,
        "timezone_policy": calendar.timezone_policy,
        "server_utc_offset_seconds": calendar.server_utc_offset_seconds,
        "raw_row_count": calendar.raw_row_count,
        "selected_component_row_count": calendar.selected_row_count,
        "excluded_non_scope_row_count": calendar.excluded_row_count,
        "grouped_event_count": len(calendar.events),
        "status_counts": dict(sorted(status_counts.items())),
        "component_coverage": components,
    }


def _mt5_common_path(terminal_path: Path) -> Path | None:
    if not terminal_path.is_file():
        _error(f"MT5 terminal not found: {terminal_path}")
        return None
    if not mt5.initialize(path=str(terminal_path)):
        _error(f"MT5 initialize failed: {mt5.last_error()}")
        return None
    try:
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            _error("MT5 is open but no connected account session is available.")
            return None
        common = getattr(terminal, "commondata_path", "")
        if not common:
            _error("MT5 did not expose its Common data path.")
            return None
        return Path(common)
    finally:
        mt5.shutdown()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return [dict(row) for row in reader]


def _atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


def _semantic_row(row: dict[str, str]) -> tuple[tuple[str, str], ...]:
    ignored = {
        "exported_at_server",
        "exported_at_gmt",
        "current_server_utc_offset_seconds",
        "terminal_build",
        "chunk_from_server",
        "chunk_to_server",
    }
    return tuple(sorted((key, value) for key, value in row.items() if key not in ignored))


def _normalized_name(value: str) -> str:
    return " ".join(
        "".join(character.lower() if character.isalnum() else " " for character in value).split()
    )


def _required_int(row: dict[str, str], field: str) -> int:
    raw = row.get(field, "").strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"MT5 status field {field!r} is not an integer.") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
