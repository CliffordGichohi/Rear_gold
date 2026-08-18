from __future__ import annotations

import argparse
import asyncio
import bisect
import csv
import gzip
import hashlib
import json
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.casebook_discovery_v2 import (
    HOLDOUT_END,
    HOLDOUT_START,
    assert_metadata_only_sql,
)
from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    EXPECTED_READINESS_GATE_IDS,
    EXPECTED_ZN_BATCH_REQUEST,
    validate_holdout_manifest,
)
from gold_intel.infrastructure.database import session_factory

READINESS_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_M6_READINESS_V0_1"
READINESS_SCHEMA_VERSION = "gold-casebook-discovery-v2-m6-readiness-schema-0.1.0"
LONDON = ZoneInfo("Europe/London")

XAU_EXECUTION_METADATA_SQL = """
SELECT
    p.open_time,
    p.close_time,
    p.available_at,
    p.provider_code,
    p.instrument_code,
    p.timeframe,
    p.batch_id,
    p.source_record_key,
    (p.spread_price IS NOT NULL OR p.spread_points IS NOT NULL) AS spread_present,
    p.is_complete,
    p.is_synthetic,
    b.provider_code AS batch_provider_code,
    b.dataset_code,
    b.content_hash AS batch_content_hash,
    b.raw_object_path,
    b.is_synthetic AS batch_is_synthetic
FROM market.price_bars AS p
JOIN raw.ingestion_batches AS b ON b.id = p.batch_id
WHERE p.provider_code = 'IC_MARKETS_MT5'
  AND p.instrument_code = 'XAUUSD'
  AND p.timeframe = '1m'
  AND p.open_time >= :start
  AND p.open_time < :end
ORDER BY p.open_time
"""


async def main() -> None:
    args = _parser().parse_args()
    research = _load_json(Path(args.research_manifest))
    research_hash = validate_holdout_manifest(research)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite readiness bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    assert_metadata_only_sql({"xau_execution_metadata": XAU_EXECUTION_METADATA_SQL})
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    text(XAU_EXECUTION_METADATA_SQL),
                    {"start": HOLDOUT_START, "end": HOLDOUT_END},
                )
            )
            .mappings()
            .all()
        )
    xau = _audit_xau_timestamps(rows, minimum_pct=95.0)
    raw_xau = _verify_xau_raw_sources(
        Path(args.mt5_directory),
        coverage_path=Path(args.coverage),
    )
    zn = _audit_zn_archive(
        Path(args.acquisition_root),
        research=research,
    )
    timestamp_coverage = _audit_zn_timestamp_coverage(
        zn["lineage_rows"],
        xau_case_dates=xau["complete_case_dates"],
        minimum_pct=95.0,
    )

    gates = [
        _gate(
            "R01_XAUUSD_TIMESTAMP_COVERAGE",
            bool(xau["passed"] and raw_xau["passed"]),
            {
                "requested_weekdays": xau["requested_weekdays"],
                "timestamp_complete_cases": xau["timestamp_complete_cases"],
                "coverage_pct": xau["coverage_pct"],
                "minimum_pct": 95.0,
                "missing_dates": xau["missing_dates"],
                "raw_source_files_verified": raw_xau["files_verified"],
            },
        ),
        _gate(
            "R02_ZN_LICENSED_ARCHIVE_SEALED",
            bool(zn["archive_sealed"]),
            {
                "provider": zn["provider"],
                "job_id": zn["job_id"],
                "job_state": zn["job_state"],
                "actual_cost_usd": zn["actual_cost_usd"],
                "maximum_cost_usd": zn["maximum_cost_usd"],
                "raw_files_verified": zn["raw_files_verified"],
                "normalized_rows": zn["normalized_rows"],
                "first_open_time": zn["first_open_time"],
                "last_open_time": zn["last_open_time"],
            },
        ),
        _gate(
            "R03_ZN_ROLL_LINEAGE_SEALED",
            bool(zn["roll_lineage_sealed"]),
            {
                "timestamp_lineage_rows": len(zn["lineage_rows"]),
                "underlying_contract_count": zn["underlying_contract_count"],
                "underlying_raw_symbols": zn["underlying_raw_symbols"],
                "roll_transition_count": zn["roll_transition_count"],
                "duplicate_rows": zn["duplicate_rows"],
                "availability_rule": zn["availability_rule"],
                "duplicate_policy": zn["duplicate_policy"],
                "roll_crossing_policy": zn["roll_crossing_policy"],
            },
        ),
        _gate(
            "R04_ZN_TIMESTAMP_ONLY_CASE_COVERAGE",
            bool(timestamp_coverage["passed"]),
            {
                "xau_timestamp_complete_cases": timestamp_coverage["requested_cases"],
                "zn_timestamp_complete_cases": timestamp_coverage["complete_cases"],
                "coverage_pct": timestamp_coverage["coverage_pct"],
                "minimum_pct": 95.0,
                "missing_dates": timestamp_coverage["missing_dates"],
                "market_values_deserialized": False,
            },
        ),
        _gate(
            "R05_PREOPEN_AUDIT_CLEAN",
            bool(
                xau["passed"]
                and raw_xau["passed"]
                and zn["archive_sealed"]
                and zn["roll_lineage_sealed"]
                and timestamp_coverage["passed"]
            ),
            {
                "source_hashes_verified": (
                    raw_xau["files_verified"] + zn["raw_files_verified"] + 4
                ),
                "xau_metadata_rows_audited": xau["metadata_rows"],
                "zn_timestamp_rows_audited": len(zn["lineage_rows"]),
                "timestamp_ordering_valid": True,
                "provider_identities_valid": True,
                "synthetic_rows_admitted": 0,
                "calendar_2025_ohlc_values_deserialized": False,
                "feature_values_calculated": False,
                "directions_calculated": False,
                "returns_or_pnl_calculated": False,
                "charts_inspected": False,
            },
        ),
    ]
    if tuple(item["gate_id"] for item in gates) != EXPECTED_READINESS_GATE_IDS:
        raise AssertionError("Readiness gate order changed")
    failures = [str(item["gate_id"]) for item in gates if not item["passed"]]
    status = "READY_FOR_ONE_TIME_HOLDOUT_OPEN" if not failures else "BLOCKED_PREOPEN_READINESS"
    readiness: dict[str, Any] = {
        "readiness_version": READINESS_VERSION,
        "schema_version": READINESS_SCHEMA_VERSION,
        "milestone": "V2_M6_PREOPEN_METADATA_READINESS",
        "research_manifest_hash": research_hash,
        "status": status,
        "passed": not failures,
        "failed_gate_ids": failures,
        "gates": gates,
        "case_population": {
            "timestamp_complete_case_count": len(xau["complete_case_dates"]),
            "session_dates": [item.isoformat() for item in xau["complete_case_dates"]],
        },
        "source_seals": {
            "xau_raw_sources": raw_xau["source_seals"],
            "zn_acquisition_manifest_sha256": zn["acquisition_manifest_sha256"],
            "zn_normalization_sha256": zn["normalization_sha256"],
            "zn_normalization_hash": zn["normalization_hash"],
            "zn_payload_sha256": zn["normalized_payload_sha256"],
            "zn_timestamp_lineage_sha256": zn["timestamp_lineage_sha256"],
            "zn_symbology_lineage_sha256": zn["symbology_lineage_sha256"],
        },
        "audit_boundary": {
            "access_class": "METADATA_AND_TIMESTAMPS_ONLY",
            "sql_statements": 1,
            "forbidden_value_columns_selected": [],
            "xau_ohlc_values_read": False,
            "zn_ohlc_values_read": False,
            "feature_values_calculated": False,
            "feature_directions_calculated": False,
            "holdout_outcomes_calculated": False,
            "holdout_charts_inspected": False,
        },
        "next_action": {
            "authorized": not failures,
            "action": (
                "OPEN_CALENDAR_2025_HOLDOUT_ONCE" if not failures else "STOP_WITHOUT_HOLDOUT_ACCESS"
            ),
        },
    }
    readiness["readiness_hash"] = canonical_hash(readiness)
    del zn["lineage_rows"]

    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.staging-",
    ) as temporary:
        staging = Path(temporary)
        readiness_path = staging / "readiness.json"
        _write_json(readiness_path, readiness)
        bundle: dict[str, Any] = {
            "readiness_version": READINESS_VERSION,
            "schema_version": READINESS_SCHEMA_VERSION,
            "milestone": "V2_M6_PREOPEN_METADATA_READINESS",
            "status": status,
            "source": {
                "research_manifest_hash": research_hash,
                "acquisition_manifest_sha256": zn["acquisition_manifest_sha256"],
                "normalization_hash": zn["normalization_hash"],
            },
            "artifacts": [
                {
                    "path": "readiness.json",
                    "sha256": _sha256(readiness_path),
                    "bytes": readiness_path.stat().st_size,
                    "document_hash": readiness["readiness_hash"],
                }
            ],
            "integrity": {
                "all_five_gates_passed": not failures,
                "calendar_2025_values_accessed": False,
                "holdout_features_calculated": False,
                "holdout_outcomes_calculated": False,
            },
        }
        bundle["manifest_hash"] = canonical_hash(bundle)
        _write_json(staging / "manifest.json", bundle)
        staging.rename(output)

    print(
        json.dumps(
            {
                "stage": "V2_M6_PREOPEN_READINESS_COMPLETE",
                "status": status,
                "passed": not failures,
                "failed_gate_ids": failures,
                "readiness_hash": readiness["readiness_hash"],
                "bundle_manifest_hash": bundle["manifest_hash"],
                "calendar_2025_values_accessed": False,
                "holdout_outcomes_calculated": False,
                "output": str(output),
            },
            sort_keys=True,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--research-manifest",
        default=("research_manifests/gold_casebook_discovery_v2_m6_holdout_v01.json"),
    )
    parser.add_argument(
        "--acquisition-root",
        default="data/raw/databento_cme_2025_zn",
    )
    parser.add_argument("--mt5-directory", default="data/mt5")
    parser.add_argument(
        "--coverage",
        default="research_artifacts/gold_casebook_discovery_v2_coverage.json",
    )
    parser.add_argument(
        "--output",
        default=("research_artifacts/gold_casebook_discovery_v2_m6_readiness_v01"),
    )
    return parser


def _audit_xau_timestamps(
    rows: list[Mapping[str, Any]],
    *,
    minimum_pct: float,
) -> dict[str, Any]:
    by_open: dict[datetime, Mapping[str, Any]] = {}
    for row in rows:
        open_time = row["open_time"].astimezone(UTC)
        if open_time in by_open:
            raise ValueError(f"Duplicate XAU metadata time: {open_time.isoformat()}")
        by_open[open_time] = row
    complete_dates: list[date] = []
    missing: list[str] = []
    requested = 0
    current = date(2025, 1, 1)
    while current < date(2026, 1, 1):
        if current.weekday() < 5:
            requested += 1
            decision = datetime.combine(
                current,
                time(8),
                tzinfo=LONDON,
            ).astimezone(UTC)
            required = (
                decision,
                decision + timedelta(minutes=1),
                datetime.combine(
                    current,
                    time(11, 59),
                    tzinfo=LONDON,
                ).astimezone(UTC),
            )
            if all(_valid_xau_metadata(by_open.get(timestamp)) for timestamp in required):
                complete_dates.append(current)
            else:
                missing.append(current.isoformat())
        current += timedelta(days=1)
    coverage = round(100 * len(complete_dates) / requested, 4)
    return {
        "passed": coverage >= minimum_pct,
        "metadata_rows": len(rows),
        "requested_weekdays": requested,
        "timestamp_complete_cases": len(complete_dates),
        "coverage_pct": coverage,
        "missing_dates": missing,
        "complete_case_dates": complete_dates,
    }


def _valid_xau_metadata(row: Mapping[str, Any] | None) -> bool:
    if row is None:
        return False
    open_time = row["open_time"].astimezone(UTC)
    close_time = row["close_time"].astimezone(UTC)
    available_at = row["available_at"].astimezone(UTC)
    return bool(
        row["provider_code"] == "IC_MARKETS_MT5"
        and row["instrument_code"] == "XAUUSD"
        and row["timeframe"] == "1m"
        and close_time == open_time + timedelta(minutes=1)
        and available_at <= close_time
        and row["spread_present"]
        and row["is_complete"]
        and not row["is_synthetic"]
        and row["batch_provider_code"] == "IC_MARKETS_MT5"
        and not row["batch_is_synthetic"]
        and row["batch_content_hash"]
        and row["source_record_key"]
    )


def _verify_xau_raw_sources(
    mt5_directory: Path,
    *,
    coverage_path: Path,
) -> dict[str, Any]:
    coverage = _load_json(coverage_path)
    expected = coverage["holdout_2025"]["xauusd_raw_source_files"]["files"]
    seals: list[dict[str, Any]] = []
    for item in expected:
        path = mt5_directory / str(item["name"])
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"XAU raw source seal failed: {path.name}")
        seals.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": item["sha256"],
                "content_deserialized": False,
            }
        )
    return {
        "passed": len(seals)
        == int(coverage["holdout_2025"]["xauusd_raw_source_files"]["files_overlapping_holdout"]),
        "files_verified": len(seals),
        "source_seals": seals,
    }


def _audit_zn_archive(
    root: Path,
    *,
    research: Mapping[str, Any],
) -> dict[str, Any]:
    acquisition_path = root / "acquisition_manifest.json"
    acquisition = _load_json(acquisition_path)
    if acquisition["research_manifest_hash"] != research["manifest_hash"]:
        raise ValueError("ZN acquisition belongs to another M6 manifest")
    if acquisition["request"] != EXPECTED_ZN_BATCH_REQUEST:
        raise ValueError("ZN acquisition request changed")
    if acquisition["status"] != "NORMALIZED_HASHED_AND_SEALED":
        raise ValueError("ZN acquisition is not sealed")
    if acquisition["job_details"]["state"] != "done":
        raise ValueError("ZN provider job is not done")
    if float(acquisition["actual_cost_usd"]) > float(research["acquisition"]["maximum_cost_usd"]):
        raise ValueError("ZN actual cost exceeded the authorized cap")
    raw_verified = 0
    for item in acquisition["local_files"]:
        path = root / str(acquisition["job_id"]) / PureWindowsPath(str(item["path"])).name
        if (
            not path.is_file()
            or path.stat().st_size != int(item["size_bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"ZN raw file seal failed: {path.name}")
        raw_verified += 1

    normalized_dir = root / str(acquisition["job_id"]) / "normalized"
    normalization_path = normalized_dir / "normalization.json"
    if _sha256(normalization_path) != acquisition["normalization"]["sha256"]:
        raise ValueError("ZN normalization file hash mismatch")
    normalization = _load_json(normalization_path)
    supplied_hash = str(normalization["normalization_hash"])
    content = {key: value for key, value in normalization.items() if key != "normalization_hash"}
    if canonical_hash(content) != supplied_hash:
        raise ValueError("ZN normalization document hash mismatch")
    if normalization["request"] != EXPECTED_ZN_BATCH_REQUEST:
        raise ValueError("ZN normalization request changed")
    artifacts: dict[str, Path] = {}
    for key in (
        "normalized_payload",
        "timestamp_lineage",
        "symbology_lineage",
    ):
        item = normalization[key]
        path = normalized_dir / str(item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"ZN normalized artifact seal failed: {path.name}")
        artifacts[key] = path
    if normalization["normalized_payload"]["human_or_model_inspected"] is not False:
        raise ValueError("ZN value payload inspection guard failed")
    if (
        normalization["market_values_human_or_model_inspected"] is not False
        or normalization["features_calculated"] is not False
        or normalization["outcomes_accessed"] is not False
    ):
        raise ValueError("ZN normalization pre-open guard failed")

    symbology = _load_json(artifacts["symbology_lineage"])
    lineage_rows = _read_and_validate_lineage(
        artifacts["timestamp_lineage"],
        normalization=normalization,
    )
    if symbology["contains_market_values"] is not False:
        raise ValueError("Symbology artifact unexpectedly contains values")
    return {
        "archive_sealed": True,
        "roll_lineage_sealed": True,
        "provider": normalization["provider"],
        "job_id": acquisition["job_id"],
        "job_state": acquisition["job_details"]["state"],
        "actual_cost_usd": acquisition["actual_cost_usd"],
        "maximum_cost_usd": acquisition["maximum_cost_usd"],
        "raw_files_verified": raw_verified,
        "normalized_rows": normalization["total_rows"],
        "first_open_time": normalization["first_open_time"],
        "last_open_time": normalization["last_open_time"],
        "underlying_contract_count": normalization["underlying_contract_count"],
        "underlying_raw_symbols": normalization["underlying_raw_symbols"],
        "roll_transition_count": normalization["observed_roll_transition_count"],
        "duplicate_rows": normalization["duplicate_rows"],
        "availability_rule": normalization["availability_rule"],
        "duplicate_policy": normalization["duplicate_policy"],
        "roll_crossing_policy": normalization["roll_crossing_policy"],
        "lineage_rows": lineage_rows,
        "acquisition_manifest_sha256": _sha256(acquisition_path),
        "normalization_sha256": _sha256(normalization_path),
        "normalization_hash": supplied_hash,
        "normalized_payload_sha256": normalization["normalized_payload"]["sha256"],
        "timestamp_lineage_sha256": normalization["timestamp_lineage"]["sha256"],
        "symbology_lineage_sha256": normalization["symbology_lineage"]["sha256"],
    }


def _read_and_validate_lineage(
    path: Path,
    *,
    normalization: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prior_open: datetime | None = None
    observed_transitions: list[dict[str, Any]] = []
    prior_id: int | None = None
    prior_symbol: str | None = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if set(raw) != {
                "source_record_id",
                "source_file_sha256",
                "source_row_ordinal",
                "open_time",
                "available_at",
                "continuous_symbol",
                "instrument_id",
                "underlying_raw_symbol",
            }:
                raise ValueError("ZN timestamp-lineage columns changed")
            open_time = datetime.fromisoformat(raw["open_time"]).astimezone(UTC)
            available_at = datetime.fromisoformat(raw["available_at"]).astimezone(UTC)
            instrument_id = int(raw["instrument_id"])
            if (
                not HOLDOUT_START <= open_time < HOLDOUT_END
                or available_at != open_time + timedelta(minutes=1)
                or raw["continuous_symbol"] != "ZN.v.0"
                or not raw["underlying_raw_symbol"]
                or not raw["source_record_id"]
                or not raw["source_file_sha256"]
            ):
                raise ValueError("ZN timestamp-lineage row failed")
            if prior_open is not None and open_time <= prior_open:
                raise ValueError("ZN timestamp lineage is not strictly ordered")
            if prior_id is not None and prior_id != instrument_id:
                observed_transitions.append(
                    {
                        "effective_open_time": open_time.isoformat(),
                        "from_instrument_id": prior_id,
                        "from_underlying_raw_symbol": prior_symbol,
                        "to_instrument_id": instrument_id,
                        "to_underlying_raw_symbol": raw["underlying_raw_symbol"],
                        "source_record_id": raw["source_record_id"],
                    }
                )
            rows.append(
                {
                    "open_time": open_time,
                    "available_at": available_at,
                    "instrument_id": instrument_id,
                    "underlying_raw_symbol": raw["underlying_raw_symbol"],
                    "source_record_id": raw["source_record_id"],
                }
            )
            prior_open = open_time
            prior_id = instrument_id
            prior_symbol = raw["underlying_raw_symbol"]
    if len(rows) != int(normalization["total_rows"]):
        raise ValueError("ZN timestamp-lineage row count mismatch")
    if observed_transitions != normalization["observed_roll_transitions"]:
        raise ValueError("ZN observed roll-transition ledger mismatch")
    return rows


def _audit_zn_timestamp_coverage(
    rows: list[Mapping[str, Any]],
    *,
    xau_case_dates: list[date],
    minimum_pct: float,
) -> dict[str, Any]:
    available = [item["available_at"] for item in rows]
    complete = 0
    missing: list[str] = []
    for session_date in xau_case_dates:
        decision = datetime.combine(
            session_date,
            time(8),
            tzinfo=LONDON,
        ).astimezone(UTC)
        reference_target = decision - timedelta(hours=4)
        current_index = bisect.bisect_right(available, decision) - 1
        reference_index = bisect.bisect_right(available, reference_target) - 1
        valid = bool(
            current_index >= 0
            and reference_index >= 0
            and decision - available[current_index] <= timedelta(hours=8)
            and reference_target - available[reference_index] <= timedelta(days=3)
        )
        if valid:
            complete += 1
        else:
            missing.append(session_date.isoformat())
    requested = len(xau_case_dates)
    coverage = round(100 * complete / requested, 4) if requested else 0.0
    return {
        "passed": coverage >= minimum_pct,
        "requested_cases": requested,
        "complete_cases": complete,
        "coverage_pct": coverage,
        "missing_dates": missing,
    }


def _gate(
    gate_id: str,
    passed: bool,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "passed": bool(passed),
        "evidence": dict(evidence),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    asyncio.run(main())
