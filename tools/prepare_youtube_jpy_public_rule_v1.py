#!/usr/bin/env python3
"""Metadata-only readiness audit and pre-outcome seal for YouTube JPY V1."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EAT = ZoneInfo("Africa/Nairobi")
START = pd.Timestamp("2021-08-01T00:00:00Z")
END = pd.Timestamp("2025-01-01T00:00:00Z")
CERTIFICATION = Path("research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json")
SYMBOL_CATALOG = Path("research_artifacts/multi_asset_macro_session_portfolio_v1_m1/mt5_symbol_catalog_snapshot.json")
CALENDAR = Path("data/mt5/calendar/mt5_us_calendar_raw.csv")
CALENDAR_AUDIT = Path("data/mt5/calendar/mt5_us_calendar_audit.json")
CALENDAR_NORMALIZATION = Path("data/mt5/calendar/mt5_us_calendar_normalization.json")
CONTRACT = Path("YOUTUBE_JPY_PUBLIC_RULE_TRANSLATION_AND_FALSIFICATION_CONTRACT_V1.md")
SCREENING = Path("YOUTUBE_JPY_STRATEGY_SCREENING_V1.md")
PROTOCOL = Path("research_manifests/youtube_jpy_public_rule_translation_v1_protocol.json")
ENGINE = Path("tools/youtube_jpy_public_rule_v1_engine.py")
PREPARER = Path("tools/prepare_youtube_jpy_public_rule_v1.py")
RUNNER = Path("tools/run_youtube_jpy_public_rule_v1.py")
TESTS = Path("tests/test_youtube_jpy_public_rule_v1_engine.py")
READINESS = Path("research_artifacts/youtube_jpy_public_rule_v1_preoutcome/readiness.json")
FREEZE = Path("research_manifests/youtube_jpy_public_rule_v1_preoutcome_freeze.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_new_json(relative: Path, value: Any) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def usd_jpy_registry() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    certification = json.loads((ROOT / CERTIFICATION).read_text(encoding="utf-8"))
    if certification.get("verdict") != "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED":
        raise RuntimeError("USDJPY predecessor certification is not PASS")
    matches = [item for item in certification["instrument_certifications"] if item.get("mt5_symbol") == "USDJPY"]
    if len(matches) != 1 or matches[0].get("classification") != "PRESENT_AND_ADEQUATE":
        raise RuntimeError("Exactly one adequate USDJPY predecessor record is required")
    return certification, list(matches[0]["coverage"]["source_files"])


def verify_sources(registry: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in registry:
        relative = Path(item["path"])
        path = ROOT / relative
        actual_bytes = path.stat().st_size
        actual_hash = sha256_file(path)
        output.append(
            {
                "path": relative.as_posix(),
                "expected_bytes": int(item["bytes"]),
                "actual_bytes": actual_bytes,
                "expected_sha256": item["sha256"],
                "actual_sha256": actual_hash,
                "verified": actual_bytes == int(item["bytes"]) and actual_hash == item["sha256"],
            }
        )
    return output


def _digest_update(digest: Any, open_time: str, close_time: str, available_at: str) -> None:
    digest.update(f"{open_time}|{close_time}|{available_at}\n".encode("utf-8"))


def metadata_primary(paths: Iterable[str]) -> dict[str, Any]:
    digest = hashlib.sha256()
    daily_counts: dict[str, int] = defaultdict(int)
    session_counts: dict[str, int] = defaultdict(int)
    session_clocks: dict[str, set[str]] = defaultdict(set)
    rows = 0
    first = last = None
    for relative in sorted(paths):
        frame = pd.read_csv(ROOT / relative, usecols=["open_time", "close_time", "available_at"])
        opens = pd.to_datetime(frame["open_time"], utc=True, errors="raise")
        closes = pd.to_datetime(frame["close_time"], utc=True, errors="raise")
        available = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
        mask = (opens >= START) & (opens < END)
        opens, closes, available = opens[mask], closes[mask], available[mask]
        if not opens.is_monotonic_increasing:
            raise RuntimeError(f"Non-monotonic source: {relative}")
        local = opens.dt.tz_convert(EAT)
        for open_stamp, close_stamp, available_stamp, local_stamp in zip(opens, closes, available, local):
            open_text = open_stamp.isoformat().replace("+00:00", "Z")
            _digest_update(
                digest,
                open_text,
                close_stamp.isoformat().replace("+00:00", "Z"),
                available_stamp.isoformat().replace("+00:00", "Z"),
            )
            day, clock = local_stamp.strftime("%Y-%m-%d"), local_stamp.strftime("%H:%M")
            daily_counts[day] += 1
            if "06:00" <= clock < "20:00":
                session_counts[day] += 1
                if clock in {"06:00", "19:59"}:
                    session_clocks[day].add(clock)
            rows += 1
            first = first or open_text
            last = open_text
    return _metadata_payload(rows, first, last, digest.hexdigest(), daily_counts, session_counts, session_clocks)


def metadata_reference(paths: Iterable[str]) -> dict[str, Any]:
    digest = hashlib.sha256()
    daily_counts: dict[str, int] = defaultdict(int)
    session_counts: dict[str, int] = defaultdict(int)
    session_clocks: dict[str, set[str]] = defaultdict(set)
    rows = 0
    first = last = None
    for relative in sorted(paths):
        with (ROOT / relative).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            prior = None
            for row in reader:
                stamp = datetime.fromisoformat(row["open_time"].replace("Z", "+00:00")).astimezone(timezone.utc)
                if stamp < START.to_pydatetime() or stamp >= END.to_pydatetime():
                    continue
                if prior is not None and stamp < prior:
                    raise RuntimeError(f"Non-monotonic reference source: {relative}")
                prior = stamp
                close_stamp = datetime.fromisoformat(row["close_time"].replace("Z", "+00:00")).astimezone(timezone.utc)
                available_stamp = datetime.fromisoformat(row["available_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
                open_text = stamp.isoformat().replace("+00:00", "Z")
                _digest_update(
                    digest,
                    open_text,
                    close_stamp.isoformat().replace("+00:00", "Z"),
                    available_stamp.isoformat().replace("+00:00", "Z"),
                )
                local = stamp.astimezone(EAT)
                day, clock = local.strftime("%Y-%m-%d"), local.strftime("%H:%M")
                daily_counts[day] += 1
                if "06:00" <= clock < "20:00":
                    session_counts[day] += 1
                    if clock in {"06:00", "19:59"}:
                        session_clocks[day].add(clock)
                rows += 1
                first = first or open_text
                last = open_text
    return _metadata_payload(rows, first, last, digest.hexdigest(), daily_counts, session_counts, session_clocks)


def _metadata_payload(
    rows: int,
    first: str | None,
    last: str | None,
    checksum: str,
    daily_counts: dict[str, int],
    session_counts: dict[str, int],
    session_clocks: dict[str, set[str]],
) -> dict[str, Any]:
    complete_daily = sorted(
        day for day, count in daily_counts.items()
        if datetime.fromisoformat(day).weekday() < 5 and count >= 1200
    )
    complete_sessions = sorted(
        day for day, count in session_counts.items()
        if datetime.fromisoformat(day).weekday() < 5 and count >= 798 and session_clocks[day] == {"06:00", "19:59"}
    )
    strict_sessions = [day for day in complete_sessions if "2023-01-01" <= day <= "2024-12-31"]
    return {
        "rows": rows,
        "first_timestamp": first,
        "last_timestamp": last,
        "timestamp_metadata_sha256": checksum,
        "complete_weekday_daily_candles": len(complete_daily),
        "complete_sessions_all": len(complete_sessions),
        "complete_sessions_strict_credit": len(strict_sessions),
        "strict_years": {year: sum(day.startswith(year) for day in strict_sessions) for year in ("2023", "2024")},
        "strict_folds": {
            "2023_H1": sum("2023-01-01" <= day < "2023-07-01" for day in strict_sessions),
            "2023_H2": sum("2023-07-01" <= day < "2024-01-01" for day in strict_sessions),
            "2024_H1": sum("2024-01-01" <= day < "2024-07-01" for day in strict_sessions),
            "2024_H2": sum("2024-07-01" <= day < "2025-01-01" for day in strict_sessions),
        },
        "complete_session_identity_sha256": canonical_hash(complete_sessions),
    }


def run_synthetic_tests() -> list[str]:
    spec = importlib.util.spec_from_file_location("youtube_jpy_v1_tests", ROOT / TESTS)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load synthetic tests")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    passed = []
    for name in sorted(item for item in dir(module) if item.startswith("test_")):
        getattr(module, name)()
        passed.append(name)
    return passed


def main() -> int:
    for relative in (READINESS, FREEZE):
        if (ROOT / relative).exists():
            raise RuntimeError(f"Append-only target already exists: {relative}")
    static = (CONTRACT, SCREENING, PROTOCOL, ENGINE, PREPARER, RUNNER, TESTS, CERTIFICATION, SYMBOL_CATALOG, CALENDAR_AUDIT, CALENDAR_NORMALIZATION)
    for relative in static + (CALENDAR,):
        if not (ROOT / relative).is_file():
            raise RuntimeError(f"Required file missing: {relative}")

    certification, registry = usd_jpy_registry()
    paths = [item["path"].replace("\\", "/") for item in registry]
    source_checks = verify_sources(registry)
    primary = metadata_primary(paths)
    reference = metadata_reference(paths)
    calendar_audit = json.loads((ROOT / CALENDAR_AUDIT).read_text(encoding="utf-8"))
    calendar_normalization = json.loads((ROOT / CALENDAR_NORMALIZATION).read_text(encoding="utf-8"))
    raw_calendar_hash = sha256_file(ROOT / CALENDAR)
    symbol_catalog = json.loads((ROOT / SYMBOL_CATALOG).read_text(encoding="utf-8"))["symbols"]["USDJPY"]
    tests_passed = run_synthetic_tests()
    gates = {
        "predecessor_pass": certification.get("verdict") == "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED",
        "exactly_21_sources": len(registry) == 21,
        "all_source_hashes_verified": all(item["verified"] for item in source_checks),
        "primary_reference_timestamp_metadata_exact": primary == reference,
        "expected_unique_rows": primary["rows"] == 1_274_223,
        "strict_session_upper_support": primary["complete_sessions_strict_credit"] >= 350,
        "calendar_hash_verified": raw_calendar_hash == calendar_normalization.get("source_sha256"),
        "calendar_audit_valid": bool(calendar_audit.get("valid")),
        "calendar_fixed_utc_plus_3": int(calendar_normalization.get("server_utc_offset_seconds", 0)) == 10_800,
        "symbol_contract_verified": symbol_catalog.get("digits") == 3 and symbol_catalog.get("point") == 0.001 and symbol_catalog.get("volume_step") == 0.01,
        "synthetic_tests_pass": len(tests_passed) >= 4,
        "forward_values_not_present_in_scope": primary["last_timestamp"] < "2025-01-01T00:00:00Z",
        "no_acquisition_or_charge": True,
    }
    readiness = {
        "version": "YOUTUBE_JPY_PUBLIC_RULE_TRANSLATION_V1_READINESS_1_0",
        "performed_at": datetime.now(timezone.utc).isoformat(),
        "market_values_accessed": False,
        "outcomes_accessed": False,
        "calendar_values_accessed": False,
        "calendar_metadata_accessed": True,
        "paid_acquisition": False,
        "charge_usd": 0.0,
        "source_checks": source_checks,
        "primary_metadata": primary,
        "reference_metadata": reference,
        "calendar": {
            "path": CALENDAR.as_posix(),
            "sha256": raw_calendar_hash,
            "rows": calendar_audit.get("raw_row_count"),
            "first_server_time": calendar_audit.get("first_server_time"),
            "last_server_time": calendar_audit.get("last_server_time"),
            "timezone_policy": calendar_normalization.get("timezone_policy"),
        },
        "symbol_metadata": symbol_catalog,
        "synthetic_tests_passed": tests_passed,
        "gates": gates,
        "verdict": "PASS_OUTCOME_BLIND_READINESS" if all(gates.values()) else "FAIL_OUTCOME_BLIND_READINESS",
    }
    write_new_json(READINESS, readiness)
    if readiness["verdict"] != "PASS_OUTCOME_BLIND_READINESS":
        raise RuntimeError("Outcome-blind readiness failed; no outcome opening authorized")

    seal_paths = list(static) + [CALENDAR, READINESS] + [Path(item["path"]) for item in registry]
    sealed_files = [
        {"path": path.as_posix(), "bytes": (ROOT / path).stat().st_size, "sha256": sha256_file(ROOT / path)}
        for path in seal_paths
    ]
    freeze = {
        "version": "YOUTUBE_JPY_PUBLIC_RULE_TRANSLATION_V1_PREOUTCOME_FREEZE_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "status": "SEALED_AND_AUTHORIZED_FOR_ONE_DEVELOPMENT_OPENING",
        "readiness_verdict": readiness["verdict"],
        "contract_status": "FROZEN_PRE_OUTCOME",
        "sealed_file_count": len(sealed_files),
        "sealed_files": sealed_files,
        "sealed_files_manifest_sha256": canonical_hash(sealed_files),
        "outcome_opening_limit": 1,
        "calendar_2025": "LOCKED_UNLESS_STAGE_4_PASS",
        "calendar_2026": "LOCKED_UNLESS_STAGE_4_PASS",
        "acquisition_authorized": False,
        "charge_authorized_usd": 0.0,
    }
    write_new_json(FREEZE, freeze)
    print(json.dumps({"verdict": readiness["verdict"], "freeze": FREEZE.as_posix(), "gates": gates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
