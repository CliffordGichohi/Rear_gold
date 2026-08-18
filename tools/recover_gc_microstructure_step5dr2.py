#!/usr/bin/env python3
"""Acquire and certify only the four sealed Step 5D-R2 MT5 windows."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
from typing import Any, Callable, Iterable, Mapping

import MetaTrader5 as mt5

from diagnose_gc_microstructure_step5dr1 import (
    EXPECTED_PRICE_SHA,
    PRICE_PATH,
    canonical_hash,
    evaluate_bars,
    make_targets,
    primary_price_projection,
    reference_price_projection,
    sha256_file,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "research_manifests" / "gc_microstructure_step_5dr2_recovery_protocol_v01.json"
FREEZE_PATH = ROOT / "research_manifests" / "gc_microstructure_step_5dr2_recovery_freeze_v01.json"
OUTPUT_DIR = ROOT / "research_artifacts" / "gc_microstructure_step5dr2_v01"
REPORT_PATH = ROOT / "GC_MICROSTRUCTURE_STEP_5D_R2_REPORT.md"
R1_DIR = ROOT / "research_artifacts" / "gc_microstructure_step5dr1_corrected_v01"


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


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def write_gzip_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> tuple[int, str]:
    if path.exists():
        raise FileExistsError(path)
    count = 0
    digest = hashlib.sha256()
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", compresslevel=6, fileobj=raw_handle, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="\n") as text_handle:
                for row in rows:
                    line = json.dumps(
                        row,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    text_handle.write(line + "\n")
                    digest.update(line.encode("utf-8") + b"\n")
                    count += 1
    return count, digest.hexdigest()


def expected_opens(start: datetime, end: datetime) -> list[str]:
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Invalid recovery window")
    output: list[str] = []
    cursor = start.astimezone(UTC)
    finish = end.astimezone(UTC)
    while cursor < finish:
        output.append(iso_z(cursor))
        cursor += timedelta(minutes=1)
    return output


def source_record(
    *,
    request: Mapping[str, Any],
    row: Any,
    ordinal: int,
    capture_at: str,
    batch_id: str,
    lineage: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    open_time = datetime.fromtimestamp(int(row["time"]), UTC)
    close_time = open_time + timedelta(minutes=1)
    raw = {
        "request_id": request["request_id"],
        "provider_row_ordinal": ordinal,
        "time_epoch_seconds": int(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "tick_volume": int(row["tick_volume"]),
        "spread_points": int(row["spread"]),
        "real_volume": int(row["real_volume"]),
    }
    source_hash = canonical_hash(raw)
    source_key = f"{lineage['server']}|XAUUSD|M1|{iso_z(open_time)}"
    record_without_hash: dict[str, Any] = {
        "record_type": "PRICE_BAR",
        "record_id": (
            f"STEP5DR2-XAUUSD-1m-{open_time:%Y%m%dT%H%M%SZ}-"
            f"{request['request_id']}-{ordinal:04d}"
        ),
        "schema_version": "gc-step5dr2-mt5-price-bar-0.1.0",
        "recovery_version": "GC_MICROSTRUCTURE_STEP_5D_R2_V0_1",
        "epistemic_status": "OBSERVED",
        "provider_code": "IC_MARKETS_MT5",
        "instrument_code": "XAUUSD",
        "timeframe": "1m",
        "open_time": iso_z(open_time),
        "close_time": iso_z(close_time),
        "available_at": iso_z(close_time),
        "ingested_at": capture_at,
        "complete": True,
        "missing_source_minutes": 0,
        "ohlc": {
            "open": raw["open"],
            "high": raw["high"],
            "low": raw["low"],
            "close": raw["close"],
        },
        "volume": raw["tick_volume"],
        "volume_type": "TICK",
        "spread_points": raw["spread_points"],
        "real_volume": raw["real_volume"],
        "source": {
            "batch_id": batch_id,
            "capture_request_id": request["request_id"],
            "provider_row_ordinal": ordinal,
            "source_record_key": source_key,
            "source_count": 1,
            "source_hash": source_hash,
            "broker_company": lineage["broker_company"],
            "server": lineage["server"],
            "terminal_build": lineage["terminal_build"],
        },
        "calculation_version": "OBSERVED_MT5_RECOVERY_ROW_V1",
    }
    normalized = dict(record_without_hash)
    normalized["record_hash"] = canonical_hash(record_without_hash)
    return raw, normalized


def scan_price_metadata(
    path: Path,
    *,
    parser: Callable[[bytes, set[tuple[str, str]]], dict[str, Any] | None],
    target: set[tuple[str, str]],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, int]]:
    records: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    total = retained = 0
    with gzip.open(path, "rb") as handle:
        for raw in handle:
            total += 1
            projected = parser(raw.rstrip(b"\r\n"), target)
            if projected is None:
                continue
            retained += 1
            records[(str(projected["timeframe"]), str(projected["open_time"]))].append(projected)
    return dict(records), {"total_rows": total, "retained_metadata_rows": retained}


def audit_result(
    *,
    protocol: Mapping[str, Any],
    existing: Mapping[tuple[str, str], list[dict[str, Any]]],
    refreshed: Mapping[tuple[str, str], list[dict[str, Any]]],
    existing_scan: Mapping[str, int],
    refresh_scan: Mapping[str, int],
) -> dict[str, Any]:
    authorized_keys = [dict(item) for item in protocol["coverage_audit"]["all_16_keys"]]
    specs, _ = make_targets(authorized_keys)
    refresh_keys = {
        (str(item["session_date"]), str(item["session_code"]))
        for item in protocol["recovery_requests"]
    }
    rows: list[dict[str, Any]] = []
    for key in sorted(specs):
        spec = specs[key]
        session_key = (str(spec["session_date"]), str(spec["session_code"]))
        expected = list(spec["outcome"])
        original = evaluate_bars(existing, expected, "1m")
        refresh = evaluate_bars(refreshed, expected, "1m") if session_key in refresh_keys else None
        selected = refresh if refresh is not None else original
        source_selection = (
            "VERSIONED_STEP_5D_R2_MT5_REFRESH"
            if refresh is not None
            else "EXISTING_SEALED_GOLD_CASEBOOK_V0_1"
        )
        constructible = bool(selected["metadata_integrity_pass"])
        rows.append({
            "session_date": spec["session_date"],
            "session_code": spec["session_code"],
            "session_timezone": spec["session_timezone"],
            "decision_at": spec["decision_at"],
            "observation_end": spec["observation_end"],
            "dst_conversion": "IANA_ZONEINFO_REPRODUCED",
            "selected_source": source_selection,
            "existing_source_coverage": original,
            "refreshed_source_coverage": refresh,
            "effective_metadata_coverage": selected,
            "classification": (
                "CONSTRUCTIBLE_UNDER_UNCHANGED_NEUTRAL_OUTCOME_DEFINITION"
                if constructible
                else "NOT_CONSTRUCTIBLE_UNDER_UNCHANGED_NEUTRAL_OUTCOME_DEFINITION"
            ),
        })
    constructible_count = sum(
        item["classification"] == "CONSTRUCTIBLE_UNDER_UNCHANGED_NEUTRAL_OUTCOME_DEFINITION"
        for item in rows
    )
    return {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_COVERAGE_AUDIT_V0_1",
        "audited_missing_key_count": len(rows),
        "previously_found_outcomes_reopened": 0,
        "previously_found_outcome_count": 358,
        "keys": rows,
        "constructible_missing_key_count": constructible_count,
        "constructible_nonholiday_outcome_count": 358 + constructible_count,
        "required_nonholiday_outcome_count": 374,
        "all_374_constructible": 358 + constructible_count == 374,
        "unchanged_neutral_outcome_definition": True,
        "source_scan": {
            "existing_casebook": dict(existing_scan),
            "versioned_refresh": dict(refresh_scan),
            "forbidden_value_fields_deserialized": 0,
            "ohlc_values_reported": 0,
        },
        "year_2025_or_2026_values_accessed": False,
    }


def verify_predecessors(protocol: Mapping[str, Any], freeze: Mapping[str, Any]) -> None:
    if protocol.get("status") != "SEALED_BEFORE_MT5_ACCESS":
        raise ValueError("Recovery protocol is not sealed")
    if freeze.get("status") != "SEALED_BEFORE_MT5_ACCESS":
        raise ValueError("Recovery freeze is not sealed")
    if sha256_file(PROTOCOL_PATH) != freeze["protocol"]["sha256"]:
        raise ValueError("Recovery protocol hash changed")
    script_path = Path(__file__).resolve()
    if sha256_file(script_path) != freeze["implementation"]["sha256"]:
        raise ValueError("Frozen recovery implementation changed")
    for binding in protocol["predecessor_bindings"].values():
        path = ROOT / binding["path"]
        if sha256_file(path) != binding["sha256"]:
            raise ValueError(f"Predecessor changed: {path}")
    if sha256_file(PRICE_PATH) != EXPECTED_PRICE_SHA:
        raise ValueError("Existing casebook source changed")
    terminal = Path(protocol["mt5_source"]["terminal_path"])
    if sha256_file(terminal) != protocol["mt5_source"]["terminal_executable_sha256"]:
        raise ValueError("Frozen MT5 terminal executable changed")


def safe_lineage() -> tuple[dict[str, Any] | None, str | None]:
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None:
        return None, "MT5 terminal or account metadata unavailable"
    if not bool(getattr(terminal, "connected", False)):
        return None, "MT5 terminal is not connected"
    company = str(getattr(account, "company", "") or "")
    server = str(getattr(account, "server", "") or "")
    if "ic markets" not in f"{company} {server}".casefold().replace("icmarkets", "ic markets"):
        return None, "Connected account does not identify IC Markets"
    return {
        "broker_company": company,
        "server": server,
        "terminal_build": int(getattr(terminal, "build", 0) or 0),
        "terminal_max_bars": int(getattr(terminal, "maxbars", 0) or 0),
        "account_environment": {0: "DEMO", 1: "CONTEST", 2: "LIVE"}.get(
            getattr(account, "trade_mode", None), "UNKNOWN"
        ),
        "account_identifier_stored": False,
        "permissions": "READ_ONLY_HISTORY_RECOVERY",
    }, None


def render_report(
    *,
    status: str,
    audit: Mapping[str, Any] | None,
    request_diagnostics: list[Mapping[str, Any]],
    reproduction_pass: bool,
    failure_reason: str | None,
) -> str:
    lines = [
        "# GC Microstructure Step 5D-R2 Report",
        "",
        f"Formal status: `{status}`",
        "",
        "This step performed only the sealed four-window MT5 recovery and metadata certification. No OHLC value is displayed in this report, and no outcome, direction, return, relationship, candidate, trade, or PnL was calculated.",
        "",
        "## Verdict",
        "",
        f"- Independent metadata reproduction: `{'PASS' if reproduction_pass else 'FAIL_OR_NOT_REACHED'}`",
    ]
    if failure_reason:
        lines.append(f"- Failure reason: `{failure_reason}`")
    if audit is not None:
        lines.extend([
            f"- Recovered missing keys constructible: `{audit['constructible_missing_key_count']} / 16`",
            f"- Total non-holiday outcomes constructible: `{audit['constructible_nonholiday_outcome_count']} / 374`",
            f"- All 374 constructible: `{str(audit['all_374_constructible']).upper()}`",
        ])
    lines.extend([
        "- Previously found outcomes reopened: `0`",
        "- Stage 1 or Stage 2 executed: `0`",
        "- 2025/2026 values inspected: `FALSE`",
        "",
        "## Authorized MT5 requests",
        "",
        "| Date | Session | Expected | Returned exact | Missing | Duplicate |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for item in request_diagnostics:
        lines.append(
            f"| {item['session_date']} | {item['session_code']} | {item['expected_timestamp_count']} | "
            f"{item['unique_exact_timestamp_count']} | {item['missing_timestamp_count']} | "
            f"{item['duplicate_timestamp_count']} |"
        )
    if audit is not None:
        lines.extend([
            "",
            "## Sixteen-key effective coverage",
            "",
            "| Date | Session | Selected source | Valid / 239 | Missing | Status |",
            "|---|---|---|---:|---:|---|",
        ])
        for item in audit["keys"]:
            coverage = item["effective_metadata_coverage"]
            lines.append(
                f"| {item['session_date']} | {item['session_code']} | {item['selected_source']} | "
                f"{coverage['metadata_eligible_timestamp_count']} | {coverage['missing_timestamp_count']} | "
                f"{item['classification']} |"
            )
    lines.extend([
        "",
        "The original casebook and every predecessor artifact remain unchanged. Refreshed rows are retained only in the new versioned Step 5D-R2 source bundle.",
        "",
    ])
    return "\n".join(lines)


def seal_failure(
    *,
    staging: Path,
    protocol: Mapping[str, Any],
    status: str,
    reason: str,
) -> None:
    failure = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_FAILURE_V0_1",
        "status": status,
        "reason": reason,
        "mt5_values_reported": False,
        "outcomes_calculated": False,
        "stage_1_or_stage_2_executed": False,
    }
    failure["failure_hash"] = canonical_hash(failure)
    write_json(staging / "failure.json", failure)
    report_temp = REPORT_PATH.with_suffix(REPORT_PATH.suffix + ".building")
    report_temp.write_text(
        render_report(
            status=status,
            audit=None,
            request_diagnostics=[],
            reproduction_pass=False,
            failure_reason=reason,
        ),
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_FAILURE_MANIFEST_V0_1",
        "status": status,
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "failure_sha256": sha256_file(staging / "failure.json"),
        "report_sha256": sha256_file(report_temp),
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    write_json(staging / "manifest.json", manifest)
    seal = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_FAILURE_FINAL_SEAL_V0_1",
        "status": status,
        "manifest_sha256": sha256_file(staging / "manifest.json"),
        "manifest_hash": manifest["manifest_hash"],
        "sealed_at_utc": iso_z(datetime.now(UTC)),
    }
    seal["final_seal_receipt"] = canonical_hash(seal)
    write_json(staging / "final_seal.json", seal)
    staging.replace(OUTPUT_DIR)
    report_temp.replace(REPORT_PATH)


def self_test() -> None:
    start = datetime(2023, 3, 15, 12, 1, tzinfo=UTC)
    end = datetime(2023, 3, 15, 16, 0, tzinfo=UTC)
    values = expected_opens(start, end)
    if len(values) != 239 or values[0] != "2023-03-15T12:01:00Z" or values[-1] != "2023-03-15T15:59:00Z":
        raise AssertionError("Exact recovery window construction failed")
    print(json.dumps({"status": "PASS_SYNTHETIC_SELF_TEST", "mt5_accessed": False}, sort_keys=True))


def run() -> None:
    if OUTPUT_DIR.exists() or REPORT_PATH.exists():
        raise FileExistsError("Step 5D-R2 output already exists")
    protocol = load_json(PROTOCOL_PATH)
    freeze = load_json(FREEZE_PATH)
    verify_predecessors(protocol, freeze)
    staging = OUTPUT_DIR.with_name(OUTPUT_DIR.name + ".building")
    if staging.exists():
        raise FileExistsError(staging)
    staging.mkdir(parents=True)

    terminal_path = protocol["mt5_source"]["terminal_path"]
    if not mt5.initialize(path=terminal_path):
        seal_failure(
            staging=staging,
            protocol=protocol,
            status="FAIL_STEP_5D_R2_MT5_PREFLIGHT",
            reason=f"MT5 initialize failed with code {mt5.last_error()[0]}",
        )
        print(json.dumps({"status": "FAIL_STEP_5D_R2_MT5_PREFLIGHT"}, sort_keys=True))
        return
    try:
        lineage, lineage_error = safe_lineage()
        if lineage_error or lineage is None:
            seal_failure(
                staging=staging,
                protocol=protocol,
                status="FAIL_STEP_5D_R2_MT5_PREFLIGHT",
                reason=lineage_error or "MT5 lineage unavailable",
            )
            print(json.dumps({"status": "FAIL_STEP_5D_R2_MT5_PREFLIGHT"}, sort_keys=True))
            return
        if not mt5.symbol_select("XAUUSD", True):
            seal_failure(
                staging=staging,
                protocol=protocol,
                status="FAIL_STEP_5D_R2_MT5_PREFLIGHT",
                reason="XAUUSD is unavailable in the connected IC Markets terminal",
            )
            print(json.dumps({"status": "FAIL_STEP_5D_R2_MT5_PREFLIGHT"}, sort_keys=True))
            return

        capture_at = iso_z(datetime.now(UTC))
        batch_id = "STEP5DR2-" + canonical_hash({
            "capture_at": capture_at,
            "server": lineage["server"],
            "requests": protocol["recovery_requests"],
        })[:24]
        raw_rows: list[dict[str, Any]] = []
        normalized_rows: list[dict[str, Any]] = []
        request_diagnostics: list[dict[str, Any]] = []
        for request in protocol["recovery_requests"]:
            start = parse_timestamp(str(request["start_utc_inclusive"]))
            end = parse_timestamp(str(request["end_utc_exclusive"]))
            expected = expected_opens(start, end)
            expected_set = set(expected)
            rates = mt5.copy_rates_range(
                "XAUUSD",
                mt5.TIMEFRAME_M1,
                start,
                end - timedelta(minutes=1),
            )
            if rates is None:
                provider_rows: list[Any] = []
                provider_error_code = int(mt5.last_error()[0])
            else:
                provider_rows = list(rates)
                provider_error_code = 0
            exact_rows: list[Any] = []
            outside_authorized_count = 0
            observed: Counter[str] = Counter()
            for row in provider_rows:
                timestamp = iso_z(datetime.fromtimestamp(int(row["time"]), UTC))
                if timestamp not in expected_set:
                    outside_authorized_count += 1
                    continue
                exact_rows.append(row)
                observed[timestamp] += 1
            for ordinal, row in enumerate(exact_rows, start=1):
                raw, normalized = source_record(
                    request=request,
                    row=row,
                    ordinal=ordinal,
                    capture_at=capture_at,
                    batch_id=batch_id,
                    lineage=lineage,
                )
                raw_rows.append(raw)
                normalized_rows.append(normalized)
            missing = [timestamp for timestamp in expected if observed[timestamp] == 0]
            duplicates = [timestamp for timestamp in expected if observed[timestamp] > 1]
            request_diagnostics.append({
                "request_id": request["request_id"],
                "session_date": request["session_date"],
                "session_code": request["session_code"],
                "start_utc_inclusive": request["start_utc_inclusive"],
                "end_utc_exclusive": request["end_utc_exclusive"],
                "expected_timestamp_count": len(expected),
                "provider_returned_count": len(provider_rows),
                "unique_exact_timestamp_count": len(observed),
                "exact_emission_count": len(exact_rows),
                "outside_authorized_timestamp_count": outside_authorized_count,
                "missing_timestamp_count": len(missing),
                "missing_timestamps": missing,
                "duplicate_timestamp_count": len(duplicates),
                "duplicate_timestamps": duplicates,
                "provider_error_code": provider_error_code,
                "coverage_complete": len(missing) == 0 and len(duplicates) == 0 and len(observed) == 239,
            })
    finally:
        mt5.shutdown()

    source_dir = staging / "versioned_source"
    source_dir.mkdir()
    raw_count, raw_content_hash = write_gzip_jsonl(source_dir / "provider_capture.jsonl.gz", raw_rows)
    normalized_count, normalized_content_hash = write_gzip_jsonl(
        source_dir / "normalized_price_bars.jsonl.gz", normalized_rows
    )
    source_manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_SOURCE_V0_1",
        "provider_code": "IC_MARKETS_MT5",
        "instrument_code": "XAUUSD",
        "timeframe": "1m",
        "capture_at": capture_at,
        "batch_id": batch_id,
        "lineage": lineage,
        "requests": request_diagnostics,
        "raw_capture": {
            "path": "provider_capture.jsonl.gz",
            "rows": raw_count,
            "file_sha256": sha256_file(source_dir / "provider_capture.jsonl.gz"),
            "uncompressed_content_sha256": raw_content_hash,
        },
        "normalized": {
            "path": "normalized_price_bars.jsonl.gz",
            "rows": normalized_count,
            "file_sha256": sha256_file(source_dir / "normalized_price_bars.jsonl.gz"),
            "uncompressed_content_sha256": normalized_content_hash,
        },
        "existing_casebook_modified": False,
        "human_ohlc_inspection_or_reporting": False,
    }
    source_manifest["source_manifest_hash"] = canonical_hash(source_manifest)
    write_json(source_dir / "source_manifest.json", source_manifest)

    authorized_keys = [dict(item) for item in protocol["coverage_audit"]["all_16_keys"]]
    specs, all_target = make_targets(authorized_keys)
    one_minute_target = {(timeframe, timestamp) for timeframe, timestamp in all_target if timeframe == "1m"}
    refresh_path = source_dir / "normalized_price_bars.jsonl.gz"
    primary_existing, primary_existing_scan = scan_price_metadata(
        PRICE_PATH, parser=primary_price_projection, target=one_minute_target
    )
    primary_refresh, primary_refresh_scan = scan_price_metadata(
        refresh_path, parser=primary_price_projection, target=one_minute_target
    )
    primary_audit = audit_result(
        protocol=protocol,
        existing=primary_existing,
        refreshed=primary_refresh,
        existing_scan=primary_existing_scan,
        refresh_scan=primary_refresh_scan,
    )
    reference_existing, reference_existing_scan = scan_price_metadata(
        PRICE_PATH, parser=reference_price_projection, target=one_minute_target
    )
    reference_refresh, reference_refresh_scan = scan_price_metadata(
        refresh_path, parser=reference_price_projection, target=one_minute_target
    )
    reference_audit = audit_result(
        protocol=protocol,
        existing=reference_existing,
        refreshed=reference_refresh,
        existing_scan=reference_existing_scan,
        refresh_scan=reference_refresh_scan,
    )
    primary_checksum = canonical_hash(primary_audit)
    reference_checksum = canonical_hash(reference_audit)
    reproduction_pass = primary_audit == reference_audit and primary_checksum == reference_checksum
    request_pass = all(bool(item["coverage_complete"]) for item in request_diagnostics)
    source_counts_pass = raw_count == normalized_count == 4 * 239
    pass_all = (
        reproduction_pass
        and request_pass
        and source_counts_pass
        and bool(primary_audit["all_374_constructible"])
    )
    status = (
        "PASS_STEP_5D_R2_RECOVERY_AND_METADATA_CERTIFICATION"
        if pass_all
        else "FAIL_STEP_5D_R2_RECOVERY_OR_METADATA_CERTIFICATION"
    )
    write_json(staging / "primary_coverage_audit.json", {
        "implementation": "PRIMARY_BYTE_REGEX_METADATA_PROJECTION",
        "result_checksum": primary_checksum,
        "result": primary_audit,
    })
    write_json(staging / "reference_coverage_audit.json", {
        "implementation": "REFERENCE_STRUCTURAL_BYTE_SCANNER",
        "result_checksum": reference_checksum,
        "result": reference_audit,
    })
    certification = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_CERTIFICATION_V0_1",
        "status": status,
        "request_coverage_pass": request_pass,
        "source_count_gate_pass": source_counts_pass,
        "independent_reproduction_pass": reproduction_pass,
        "primary_checksum": primary_checksum,
        "reference_checksum": reference_checksum,
        "constructible_missing_keys": primary_audit["constructible_missing_key_count"],
        "constructible_nonholiday_outcomes": primary_audit["constructible_nonholiday_outcome_count"],
        "all_374_constructible": primary_audit["all_374_constructible"],
        "previously_found_outcomes_reopened": 0,
        "outcomes_calculated": False,
        "stage_1_or_stage_2_executed": False,
        "ohlc_values_reported": False,
        "year_2025_or_2026_values_accessed": False,
    }
    certification["certification_hash"] = canonical_hash(certification)
    write_json(staging / "certification.json", certification)
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_VERDICT_V0_1",
        "status": status,
        "step5d_status_preserved": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
        "r1_corrected_status_preserved": "PASS_STEP_5D_R1_DIAGNOSTIC_REPRODUCTION_AFTER_IMPLEMENTATION_CORRECTION",
        "all_374_constructible": primary_audit["all_374_constructible"],
        "constructible_nonholiday_outcomes": primary_audit["constructible_nonholiday_outcome_count"],
        "next_action_if_pass": "A separately authorized Step 5D resumption may construct and join outcomes once and run the frozen Stage-1/Stage-2 registry.",
        "research_resumed": False,
    }
    verdict["verdict_hash"] = canonical_hash(verdict)
    write_json(staging / "verdict.json", verdict)
    report_temp = REPORT_PATH.with_suffix(REPORT_PATH.suffix + ".building")
    report_temp.write_text(
        render_report(
            status=status,
            audit=primary_audit,
            request_diagnostics=request_diagnostics,
            reproduction_pass=reproduction_pass,
            failure_reason=None if pass_all else "One or more frozen recovery or certification gates failed",
        ),
        encoding="utf-8",
        newline="\n",
    )
    artifact_names = [
        "primary_coverage_audit.json",
        "reference_coverage_audit.json",
        "certification.json",
        "verdict.json",
    ]
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_MANIFEST_V0_1",
        "status": status,
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "source": {
            "manifest_sha256": sha256_file(source_dir / "source_manifest.json"),
            "raw_capture_sha256": sha256_file(source_dir / "provider_capture.jsonl.gz"),
            "normalized_sha256": sha256_file(source_dir / "normalized_price_bars.jsonl.gz"),
        },
        "artifacts": {
            name: {"sha256": sha256_file(staging / name), "bytes": (staging / name).stat().st_size}
            for name in artifact_names
        },
        "report": {"path": REPORT_PATH.name, "sha256": sha256_file(report_temp), "bytes": report_temp.stat().st_size},
        "coverage_checksum": primary_checksum,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    write_json(staging / "manifest.json", manifest)
    final_seal = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_FINAL_SEAL_V0_1",
        "status": status,
        "manifest_sha256": sha256_file(staging / "manifest.json"),
        "manifest_hash": manifest["manifest_hash"],
        "verdict_sha256": sha256_file(staging / "verdict.json"),
        "certification_sha256": sha256_file(staging / "certification.json"),
        "source_manifest_sha256": sha256_file(source_dir / "source_manifest.json"),
        "coverage_checksum": primary_checksum,
        "sealed_at_utc": iso_z(datetime.now(UTC)),
    }
    final_seal["final_seal_receipt"] = canonical_hash(final_seal)
    write_json(staging / "final_seal.json", final_seal)
    staging.replace(OUTPUT_DIR)
    report_temp.replace(REPORT_PATH)

    sealed_manifest = load_json(OUTPUT_DIR / "manifest.json")
    for name, metadata in sealed_manifest["artifacts"].items():
        if sha256_file(OUTPUT_DIR / name) != metadata["sha256"]:
            raise ValueError(f"Post-seal verification failed: {name}")
    if sha256_file(REPORT_PATH) != sealed_manifest["report"]["sha256"]:
        raise ValueError("Post-seal report verification failed")
    print(json.dumps({
        "status": status,
        "requests_complete": sum(bool(item["coverage_complete"]) for item in request_diagnostics),
        "requests_required": 4,
        "captured_rows": normalized_count,
        "constructible_nonholiday_outcomes": primary_audit["constructible_nonholiday_outcome_count"],
        "required_nonholiday_outcomes": 374,
        "independent_reproduction_pass": reproduction_pass,
        "ohlc_values_reported": False,
        "final_seal_sha256": sha256_file(OUTPUT_DIR / "final_seal.json"),
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    run()


if __name__ == "__main__":
    main()
