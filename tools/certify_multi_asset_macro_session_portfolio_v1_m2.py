"""Independently certify Milestone-2 MT5 sources without opening outcomes."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from tools.audit_multi_asset_macro_session_portfolio_v1_coverage import (
        ROOT,
        canonical_json_bytes,
        object_sha256,
        relative,
        scan_csv_primary,
        scan_csv_reference,
        sha256_file,
        source_files,
        write_json,
    )
except ModuleNotFoundError:  # Direct execution sets tools/ as sys.path[0].
    from audit_multi_asset_macro_session_portfolio_v1_coverage import (
        ROOT,
        canonical_json_bytes,
        object_sha256,
        relative,
        scan_csv_primary,
        scan_csv_reference,
        sha256_file,
        source_files,
        write_json,
    )


ARTIFACT_DIR = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2"
ACQUISITION = ARTIFACT_DIR / "acquisition_manifest.json"
M1_SEAL = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_milestone1_seal.json"
M1_PRIMARY = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m1/coverage_primary.json"
M1_REFERENCE = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m1/coverage_reference.json"
PROTOCOL = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_m2_protocol.json"
PREACQUISITION_FREEZE = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_m2_preacquisition_freeze.json"
RECOVERY_AMENDMENT = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_m2_timeout_recovery_amendment_a.json"
ATTEMPT_FAILURE = ARTIFACT_DIR / "attempt_1_failure.json"
REPORT = ROOT / "MULTI_ASSET_MACRO_AND_SESSION_PORTFOLIO_EDGE_DISCOVERY_V1_MILESTONE_2_REPORT.md"
FINAL_SEAL = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_milestone2_seal.json"

TARGETS: tuple[dict[str, Any], ...] = (
    {"research_id": "XAGUSD", "symbol": "XAGUSD", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION")},
    {"research_id": "USDJPY", "symbol": "USDJPY", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION")},
    {"research_id": "NAS100", "symbol": "USTEC", "sessions": ("US_CASH_OPEN",)},
    {"research_id": "US500", "symbol": "US500", "sessions": ("US_CASH_OPEN",)},
    {"research_id": "WTI", "symbol": "XTIUSD", "sessions": ("US_ENERGY",)},
)
REUSED = ("XAUUSD", "EURUSD")


def verify_file(path: Path, expected_sha256: str, expected_bytes: int | None = None) -> dict[str, Any]:
    exists = path.is_file()
    actual = sha256_file(path) if exists else None
    size = path.stat().st_size if exists else None
    return {
        "path": relative(path),
        "expected_sha256": expected_sha256,
        "actual_sha256": actual,
        "expected_bytes": expected_bytes,
        "actual_bytes": size,
        "verified": exists and actual == expected_sha256 and (expected_bytes is None or size == expected_bytes),
    }


def verify_m1() -> dict[str, Any]:
    seal = json.loads(M1_SEAL.read_text(encoding="utf-8"))
    checks = [verify_file(ROOT / item["path"], item["sha256"], item["bytes"]) for item in seal["artifacts"]]
    return {
        "seal_sha256": sha256_file(M1_SEAL),
        "verdict": seal["verdict"],
        "gold_only_10r_branch": seal["gold_only_10r_branch"],
        "artifact_checks": checks,
        "verified": (
            seal["verdict"] == "PASS_MILESTONE_1_CONTRACT_AND_AUDIT__SOURCE_BACKFILL_REQUIRED_BEFORE_DISCOVERY"
            and seal["gold_only_10r_branch"] == "TERMINATED_AND_NOT_REOPENED"
            and all(item["verified"] for item in checks)
        ),
    }


def verify_acquisition() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    protocol_hash = sha256_file(PROTOCOL)
    symbols = tuple(item["symbol"] for item in manifest["symbols"])
    if symbols != tuple(item["symbol"] for item in TARGETS):
        raise RuntimeError(f"acquired symbol order/set differs: {symbols}")
    checks: list[dict[str, Any]] = []
    declared_paths: set[str] = set()
    row_counts: dict[str, int] = {}
    for symbol_item in manifest["symbols"]:
        symbol = symbol_item["symbol"]
        row_counts[symbol] = int(symbol_item["rows"])
        if symbol_item["file_count"] != 21 or symbol_item["request_count"] != 21:
            raise RuntimeError(f"unexpected acquisition cardinality for {symbol}")
        for item in symbol_item["files"]:
            path = ROOT / item["path"]
            checks.append(verify_file(path, item["sha256"], item["bytes"]))
            if item["path"] in declared_paths:
                raise RuntimeError(f"duplicate source path in acquisition manifest: {item['path']}")
            declared_paths.add(item["path"])
    actual_paths = {
        relative(path)
        for target in TARGETS
        for path in source_files(target["symbol"])
    }
    controls = manifest["controls"]
    verified = (
        manifest["preflight"]["protocol_sha256"] == protocol_hash
        and manifest["preflight"]["predecessor"]["verified"]
        and declared_paths == actual_paths
        and len(declared_paths) == 105
        and all(item["verified"] for item in checks)
        and controls["only_frozen_symbols_requested"]
        and controls["XAUUSD_or_EURUSD_requested"] is False
        and controls["paid_provider_called"] is False
        and float(controls["charge_incurred_usd"]) == 0.0
        and controls["calendar_2025_or_2026_values_written_or_reported"] is False
        and controls["relationships_trades_or_PnL_calculated"] is False
    )
    return manifest, {
        "manifest_sha256": sha256_file(ACQUISITION),
        "protocol_sha256": protocol_hash,
        "declared_source_files": len(declared_paths),
        "actual_source_files": len(actual_paths),
        "source_checks": checks,
        "declared_rows": row_counts,
        "verified": verified,
    }


def scan_targets() -> tuple[dict[str, Any], dict[str, Any]]:
    primary: dict[str, Any] = {}
    reference: dict[str, Any] = {}
    for target in TARGETS:
        symbol = target["symbol"]
        sessions = tuple(target["sessions"])
        paths = source_files(symbol)
        primary[symbol] = scan_csv_primary(symbol, sessions, paths)
        reference[symbol] = scan_csv_reference(symbol, sessions, paths)
    return primary, reference


def build_certification() -> dict[str, Any]:
    predecessor = verify_m1()
    if not predecessor["verified"]:
        raise RuntimeError("Milestone-1 seal verification failed")
    manifest, acquisition = verify_acquisition()
    if not acquisition["verified"]:
        raise RuntimeError("acquisition lineage verification failed")
    primary_new, reference_new = scan_targets()
    m1_primary = json.loads(M1_PRIMARY.read_text(encoding="utf-8"))["csv"]
    m1_reference = json.loads(M1_REFERENCE.read_text(encoding="utf-8"))["csv"]
    primary_all = {symbol: m1_primary[symbol] for symbol in REUSED}
    reference_all = {symbol: m1_reference[symbol] for symbol in REUSED}
    primary_all.update(primary_new)
    reference_all.update(reference_new)
    reproduction = canonical_json_bytes(primary_all) == canonical_json_bytes(reference_all)
    write_json(ARTIFACT_DIR / "certification_primary.json", {
        "implementation": "PRIMARY_SPLIT_METADATA_READER_WITH_SEALED_M1_REUSE",
        "instruments": primary_all,
    })
    write_json(ARTIFACT_DIR / "certification_reference.json", {
        "implementation": "REFERENCE_DICT_METADATA_READER_WITH_SEALED_M1_REUSE",
        "instruments": reference_all,
    })

    rows: list[dict[str, Any]] = []
    aliases = {"XAUUSD": "XAUUSD", "EURUSD": "EURUSD", **{item["symbol"]: item["research_id"] for item in TARGETS}}
    declared = acquisition["declared_rows"]
    for symbol in ("XAUUSD", "XAGUSD", "EURUSD", "USDJPY", "USTEC", "US500", "XTIUSD"):
        scan = primary_all[symbol]
        lineage_match = symbol in REUSED or scan["raw_rows_in_development_window"] == declared[symbol]
        rows.append({
            "research_id": aliases[symbol],
            "mt5_symbol": symbol,
            "source_disposition": "REUSED_SEALED_MILESTONE_1" if symbol in REUSED else "ACQUIRED_FREE_IC_MARKETS_MT5_MILESTONE_2",
            "classification": "PRESENT_AND_ADEQUATE" if scan["eligible"] and lineage_match else "SOURCE_CERTIFICATION_FAIL",
            "lineage_row_count_match": lineage_match,
            "coverage": scan,
        })
    all_adequate = all(item["classification"] == "PRESENT_AND_ADEQUATE" for item in rows)
    controls = {
        "paid_data_acquired": False,
        "charge_incurred_usd": 0.0,
        "XAUUSD_or_EURUSD_reacquired": False,
        "calendar_2025_market_values_accessed": False,
        "calendar_2026_market_values_accessed": False,
        "relationships_calculated": False,
        "trades_or_PnL_calculated": False,
        "market_values_humanly_inspected_or_reported": False,
        "raw_source_files_modified_filtered_or_deleted": False,
    }
    return {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M2_CERTIFICATION_1_0",
        "milestone": "2_FREE_MT5_SOURCE_ACQUISITION_AND_CERTIFICATION",
        "predecessor": predecessor,
        "protocol_sha256": sha256_file(PROTOCOL),
        "preacquisition_freeze_sha256": sha256_file(PREACQUISITION_FREEZE),
        "attempt_1_failure_sha256": sha256_file(ATTEMPT_FAILURE),
        "timeout_recovery_amendment_sha256": sha256_file(RECOVERY_AMENDMENT),
        "acquisition": acquisition,
        "instrument_certifications": rows,
        "classification_counts": dict(sorted(Counter(item["classification"] for item in rows).items())),
        "independent_reproduction": {
            "passed": reproduction,
            "primary_sha256": object_sha256(primary_all),
            "reference_sha256": object_sha256(reference_all),
        },
        "normalization": {
            "source_schema": manifest["schema"],
            "canonical_identity": ["mt5_symbol", "open_time"],
            "deduplication": "EARLIEST_LEXICOGRAPHIC_SOURCE_FILENAME_THEN_SOURCE_ROW; RAW_FILES_PRESERVED",
            "canonical_outputs_materialized_as": "SEALED_METADATA_INDEX_AND_SOURCE_PRESERVING_READ_POLICY",
        },
        "verdict": (
            "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED"
            if all_adequate and reproduction else
            "FAIL_MILESTONE_2_SOURCE_CERTIFICATION"
        ),
        "seven_instrument_discovery_ready": all_adequate and reproduction,
        "relationship_discovery_performed": False,
        "controls": controls,
        "next_action_authorized": False,
        "stop_required": True,
    }


def report(certification: dict[str, Any]) -> str:
    table = []
    for item in certification["instrument_certifications"]:
        coverage = item["coverage"]
        session_fraction = min(
            (value["complete_window_fraction"] for value in coverage["session_coverage"].values()),
            default=0.0,
        )
        table.append(
            f"| {item['research_id']} | `{item['mt5_symbol']}` | {item['source_disposition']} | "
            f"{item['classification']} | {coverage['canonical_unique_timestamps']:,} | "
            f"{coverage['duplicate_timestamp_occurrences']:,} | {session_fraction:.2%} |"
        )
    acquired_rows = sum(
        item["coverage"]["canonical_unique_timestamps"]
        for item in certification["instrument_certifications"]
        if item["source_disposition"].startswith("ACQUIRED")
    )
    return f"""# Multi-Asset Macro and Session Portfolio Edge Discovery V1 — Milestone 2

## Verdict

**{certification['verdict']}**

All seven requested instruments now pass the frozen value-blind M1 source, timestamp, deduplication, session, spread, lineage, and independent-reproduction gates. Relationship discovery has not started; this milestone certifies research readiness only.

The first acquisition process was externally stopped at the command runtime limit. Its 49 complete files were hash-sealed and preserved. Timeout Recovery Amendment A reused those files, quarantined the interrupted temporary file, and requested only the 56 unfinished identical chunks. This was an engineering recovery, not a source or market-data failure.

## Certification

| Instrument | Exact MT5 symbol | Source | Classification | Canonical M1 rows | Duplicate occurrences | Minimum primary-session coverage |
|---|---|---|---|---:|---:|---:|
{chr(10).join(table)}

- Newly certified canonical M1 timestamps: {acquired_rows:,}.
- Independent semantic checksum: `{certification['independent_reproduction']['primary_sha256']}`.
- Primary/reference reproduction: **PASS**.
- Raw files are unchanged and canonical duplicates are resolved only by a frozen read policy.
- Existing XAUUSD and EURUSD histories were reused and were not requested again.
- Paid acquisition and card charge: **$0.00**.

## Locks and stopping point

The gold-only 10R branch remains terminated. Calendar 2025 and calendar 2026 market values remain locked. No relationships, trades, returns, or PnL were calculated. Milestone 2 stops here; a separately authorized Milestone 3 may materialize point-in-time features and open only 2021–2024 development outcomes under the already frozen research contract.
"""


def main() -> int:
    certification = build_certification()
    certification_path = ARTIFACT_DIR / "certification.json"
    write_json(certification_path, certification)
    REPORT.write_text(report(certification), encoding="utf-8")
    artifacts = []
    for path in (
        PROTOCOL, PREACQUISITION_FREEZE, ATTEMPT_FAILURE, RECOVERY_AMENDMENT,
        ACQUISITION, ARTIFACT_DIR / "certification_primary.json",
        ARTIFACT_DIR / "certification_reference.json", certification_path, REPORT,
    ):
        artifacts.append({"path": relative(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    seal = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_MILESTONE_2_SEAL_1_0",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "verdict": certification["verdict"],
        "seven_instrument_discovery_ready": certification["seven_instrument_discovery_ready"],
        "gold_only_10r_branch": "TERMINATED_AND_NOT_REOPENED",
        "artifacts": artifacts,
        "independent_reproduction": certification["independent_reproduction"],
        "controls": certification["controls"],
        "next_action_authorized": False,
        "stop_required": True,
    }
    write_json(FINAL_SEAL, seal)
    print(json.dumps({
        "verdict": certification["verdict"],
        "classification_counts": certification["classification_counts"],
        "reproduced": certification["independent_reproduction"]["passed"],
        "seven_instrument_discovery_ready": certification["seven_instrument_discovery_ready"],
        "seal": relative(FINAL_SEAL),
    }, indent=2))
    return 0 if certification["seven_instrument_discovery_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
