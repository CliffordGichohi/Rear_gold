from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from gold_intel.analytics.casebook import json_ready
from gold_intel.analytics.casebook_discovery_v3 import (
    AUDIT_VERSION,
    EXPOSED_2025_END,
    EXPOSED_2025_START,
    LOCKED_2026_YTD_END,
    LOCKED_2026_YTD_START,
    add_deterministic_hash,
    assert_metadata_only_sql,
    audit_timestamp_only_session_coverage,
    mt5_xau_files_overlapping,
    overlapping_filename_pairs,
    sha256_file,
    source_file_metadata,
    timestamp_ranges_from_filenames,
    verify_embedded_hash,
)
from gold_intel.infrastructure.database import session_factory

CONTRACT_HASH = "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b"
TRACEABILITY_HASH = "8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4"
REFERENCE_BOOK_HASH = "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a"

PRICE_METADATA_SQL = """
SELECT
    provider_code,
    instrument_code,
    timeframe,
    count(*) AS rows,
    count(DISTINCT open_time) AS distinct_open_times,
    min(open_time) AS first_open_time,
    max(open_time) AS last_open_time,
    min(available_at) AS first_available_at,
    max(available_at) AS last_available_at,
    count(*) FILTER (
        WHERE spread_price IS NOT NULL OR spread_points IS NOT NULL
    ) AS spread_present_rows,
    count(*) FILTER (WHERE volume IS NOT NULL) AS volume_present_rows,
    count(*) FILTER (WHERE available_at <= close_time) AS valid_availability_rows,
    count(*) FILTER (WHERE NOT is_complete) AS incomplete_rows,
    count(*) FILTER (WHERE is_synthetic) AS synthetic_rows
FROM market.price_bars
WHERE open_time >= :start
  AND open_time < :end
GROUP BY provider_code, instrument_code, timeframe
ORDER BY instrument_code, provider_code, timeframe
"""

XAU_FIVE_MINUTE_TIMESTAMPS_SQL = """
WITH canonical_timestamps AS (
    SELECT DISTINCT open_time
    FROM market.price_bars
    WHERE provider_code = 'IC_MARKETS_MT5'
      AND instrument_code = 'XAUUSD'
      AND timeframe = '1m'
      AND is_complete
      AND NOT is_synthetic
      AND open_time >= :start
      AND open_time < :end
      AND available_at <= close_time
)
SELECT time_bucket('5 minutes', open_time) AS bucket_open_time
FROM canonical_timestamps
GROUP BY 1
HAVING count(*) = 5
ORDER BY 1
"""

OBSERVATION_METADATA_SQL = """
SELECT
    series_code,
    count(*) AS rows_available_in_interval,
    count(DISTINCT observation_time) AS observation_periods,
    min(observation_time) AS first_observation_time,
    max(observation_time) AS last_observation_time,
    min(available_at) AS first_available_at,
    max(available_at) AS last_available_at,
    count(*) FILTER (WHERE is_revision) AS revision_rows,
    count(*) FILTER (WHERE available_at >= observation_time) AS valid_availability_rows,
    count(*) FILTER (WHERE is_synthetic) AS synthetic_rows
FROM market.observations
WHERE available_at >= :start
  AND available_at < :end
GROUP BY series_code
ORDER BY series_code
"""

COT_METADATA_SQL = """
SELECT
    provider_code,
    report_type,
    contract_market_code,
    count(*) AS reports,
    count(DISTINCT observation_date) AS observation_dates,
    min(observation_date) AS first_observation_date,
    max(observation_date) AS last_observation_date,
    min(publication_at) AS first_publication_at,
    max(publication_at) AS last_publication_at,
    count(*) FILTER (WHERE publication_at > observation_date) AS valid_availability_rows
FROM market.cot_reports
WHERE publication_at >= :start
  AND publication_at < :end
GROUP BY provider_code, report_type, contract_market_code
ORDER BY provider_code, report_type, contract_market_code
"""

EVENT_METADATA_SQL = """
SELECT
    provider_code,
    count(*) AS rows,
    count(DISTINCT source_event_key) AS distinct_events,
    min(scheduled_at) AS first_scheduled_at,
    max(scheduled_at) AS last_scheduled_at,
    min(available_at) AS first_available_at,
    max(available_at) AS last_available_at,
    count(*) FILTER (WHERE is_scheduled) AS scheduled_rows,
    count(*) FILTER (WHERE is_synthetic) AS synthetic_rows
FROM market.economic_events
WHERE scheduled_at >= :start
  AND scheduled_at < :end
GROUP BY provider_code
ORDER BY provider_code
"""

FORECAST_METADATA_SQL = """
SELECT
    provider_code,
    count(*) AS rows,
    count(DISTINCT (event_code, scheduled_at, component_code)) AS components,
    min(scheduled_at) AS first_scheduled_at,
    max(scheduled_at) AS last_scheduled_at,
    min(forecast_as_of) AS first_forecast_as_of,
    max(forecast_as_of) AS last_forecast_as_of,
    min(available_at) AS first_available_at,
    max(available_at) AS last_available_at,
    count(*) FILTER (
        WHERE forecast_as_of <= scheduled_at
          AND available_at <= scheduled_at
    ) AS timestamp_pre_release_rows,
    count(*) FILTER (
        WHERE metadata_json->>'pre_event_use_allowed' = 'true'
    ) AS verified_pre_event_rows,
    count(*) FILTER (WHERE is_synthetic) AS synthetic_rows
FROM market.forecast_snapshots
WHERE scheduled_at >= :start
  AND scheduled_at < :end
GROUP BY provider_code
ORDER BY provider_code
"""

RELEASE_METADATA_SQL = """
SELECT
    count(*) AS rows,
    count(DISTINCT event_id) AS distinct_events,
    count(DISTINCT component_code) AS component_codes,
    min(released_at) AS first_released_at,
    max(released_at) AS last_released_at,
    min(available_at) AS first_available_at,
    max(available_at) AS last_available_at,
    count(*) FILTER (WHERE is_revision) AS revision_rows,
    count(*) FILTER (WHERE available_at >= released_at) AS valid_availability_rows,
    count(*) FILTER (WHERE is_synthetic) AS synthetic_rows
FROM market.economic_releases
WHERE released_at >= :start
  AND released_at < :end
"""

POLICY_METADATA_SQL = """
SELECT
    provider_code,
    count(*) AS rows,
    count(DISTINCT observation_date) AS observation_dates,
    min(snapshot_as_of) AS first_snapshot_at,
    max(snapshot_as_of) AS last_snapshot_at,
    min(available_at) AS first_available_at,
    max(available_at) AS last_available_at,
    count(*) FILTER (WHERE available_at >= snapshot_as_of) AS valid_availability_rows,
    count(*) FILTER (WHERE is_synthetic) AS synthetic_rows
FROM market.policy_expectation_windows
WHERE available_at >= :start
  AND available_at < :end
GROUP BY provider_code
ORDER BY provider_code
"""

SQL_STATEMENTS = {
    "price_metadata": PRICE_METADATA_SQL,
    "xau_five_minute_timestamps": XAU_FIVE_MINUTE_TIMESTAMPS_SQL,
    "observation_metadata": OBSERVATION_METADATA_SQL,
    "cot_metadata": COT_METADATA_SQL,
    "event_metadata": EVENT_METADATA_SQL,
    "forecast_metadata": FORECAST_METADATA_SQL,
    "release_metadata": RELEASE_METADATA_SQL,
    "policy_metadata": POLICY_METADATA_SQL,
}


async def main() -> None:
    args = _parser().parse_args()
    report = await build_report(
        mt5_directory=Path(args.mt5_directory),
        cme_2025_normalization=Path(args.cme_2025_normalization),
        cme_2026_directory=Path(args.cme_2026_directory),
        contract_manifest_path=Path(args.contract_manifest),
        traceability_catalog_path=Path(args.traceability_catalog),
        case_matrix_schema_path=Path(args.case_matrix_schema),
        casebook_manifest_path=Path(args.casebook_manifest),
        original_rejection_manifest_path=Path(args.original_rejection_manifest),
        v2_rejection_manifest_path=Path(args.v2_rejection_manifest),
        reference_book_path=Path(args.reference_book),
    )
    json_output = Path(args.json_output)
    markdown_output = Path(args.markdown_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(json_ready(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "audit_version": AUDIT_VERSION,
                "contract_manifest_hash": report["contract"]["manifest_hash"],
                "data_hash": report["data_hash"],
                "json_output": str(json_output),
                "markdown_output": str(markdown_output),
                "relationship_calculations": 0,
                "values_or_outcomes_inspected_2025": False,
                "values_or_outcomes_inspected_2026": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


async def build_report(
    *,
    mt5_directory: Path,
    cme_2025_normalization: Path,
    cme_2026_directory: Path,
    contract_manifest_path: Path,
    traceability_catalog_path: Path,
    case_matrix_schema_path: Path,
    casebook_manifest_path: Path,
    original_rejection_manifest_path: Path,
    v2_rejection_manifest_path: Path,
    reference_book_path: Path,
) -> dict[str, Any]:
    assert_metadata_only_sql(SQL_STATEMENTS)

    contract = _load_json(contract_manifest_path)
    contract_hash = verify_embedded_hash(contract, hash_field="manifest_hash")
    if contract_hash != CONTRACT_HASH:
        raise ValueError("Unexpected V3 contract hash")
    if contract["v3_milestone_1"]["code"] != (
        "V3_M1_CONTRACT_TRACEABILITY_METADATA_SCHEMA_STATE"
    ):
        raise ValueError("Unexpected V3 milestone")

    traceability = _load_json(traceability_catalog_path)
    traceability_hash = verify_embedded_hash(
        traceability,
        hash_field="catalog_hash",
    )
    if traceability_hash != TRACEABILITY_HASH:
        raise ValueError("Unexpected V3 traceability hash")

    casebook_manifest = _load_json(casebook_manifest_path)
    original_rejection = _load_json(original_rejection_manifest_path)
    v2_rejection = _load_json(v2_rejection_manifest_path)
    _validate_preserved_history(
        casebook_manifest=casebook_manifest,
        original_rejection=original_rejection,
        v2_rejection=v2_rejection,
    )

    if sha256_file(reference_book_path) != REFERENCE_BOOK_HASH:
        raise ValueError("Reference Book hash mismatch")

    partitions = (
        (
            "exposed_2025",
            EXPOSED_2025_START,
            EXPOSED_2025_END,
            date(2025, 1, 1),
            date(2025, 12, 31),
        ),
        (
            "locked_2026_ytd",
            LOCKED_2026_YTD_START,
            LOCKED_2026_YTD_END,
            date(2026, 1, 1),
            date(2026, 7, 29),
        ),
    )

    database_metadata: dict[str, Any] = {}
    async with session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        for code, start, end, session_start, session_end in partitions:
            database_metadata[code] = await _query_partition_metadata(
                session=session,
                start=start,
                end=end,
                session_date_start=session_start,
                session_date_end=session_end,
            )
        await session.rollback()

    file_cache: dict[Path, dict[str, Any]] = {}
    raw_xau_metadata: dict[str, Any] = {}
    for code, start, end, _, _ in partitions:
        files = mt5_xau_files_overlapping(
            mt5_directory,
            start=start,
            end=end,
        )
        metadata: list[dict[str, Any]] = []
        for path in files:
            if path not in file_cache:
                file_cache[path] = source_file_metadata(path)
            metadata.append(file_cache[path])
        raw_xau_metadata[code] = {
            "directory": _portable_path(mt5_directory),
            "files_overlapping_interval": len(files),
            "files": metadata,
            "declared_timestamp_ranges": timestamp_ranges_from_filenames(files),
            "overlapping_filename_pairs": overlapping_filename_pairs(files),
            "file_content_deserialized": False,
            "hashing_method": "Raw bytes streamed through SHA-256; no CSV parser or value column was invoked.",
        }

    cme_2025 = _cme_2025_metadata_only(cme_2025_normalization)
    cme_2026 = _cme_2026_metadata_only(cme_2026_directory)
    coverage_counts = Counter(
        item["development_coverage"] for item in traceability["field_requirements"]
    )

    exposed_xau = _find_xau_1m(
        database_metadata["exposed_2025"]["price_metadata"]
    )
    locked_xau = _find_xau_1m(
        database_metadata["locked_2026_ytd"]["price_metadata"]
    )

    report: dict[str, Any] = {
        "audit_version": AUDIT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "contract": {
            "governing_document": "GOLD_SESSION_BEHAVIOUR_DISCOVERY_CONTRACT_V3.md",
            "manifest_path": _portable_path(contract_manifest_path),
            "manifest_hash": contract_hash,
            "milestone": "V3_M1_CONTRACT_TRACEABILITY_METADATA_SCHEMA_STATE",
        },
        "audit_boundary": {
            "access_class": "METADATA_ONLY",
            "database_transaction_read_only": True,
            "sql_statement_count": len(SQL_STATEMENTS),
            "sql_guard_passed": True,
            "sql_statement_sha256": {
                name: hashlib.sha256(statement.encode()).hexdigest()
                for name, statement in sorted(SQL_STATEMENTS.items())
            },
            "forbidden_value_columns_referenced": [],
            "permitted_database_fields": [
                "provider, series, instrument, timeframe, event, component, and source identifiers",
                "observation, publication, schedule, release, availability, and bar timestamps",
                "row and distinct-timestamp counts",
                "non-null spread and volume counts without retrieving their values",
                "revision, synthetic, completeness, and point-in-time ordering counts",
            ],
            "permitted_file_operations": [
                "filename parsing",
                "byte size",
                "last-write timestamp",
                "SHA-256 byte streaming",
                "metadata-manifest parsing",
            ],
            "development_market_values_read": False,
            "exposed_2025_market_or_macro_values_read": False,
            "exposed_2025_outcomes_calculated": False,
            "locked_2026_market_or_macro_values_read": False,
            "locked_2026_outcomes_calculated": False,
            "feature_values_calculated": False,
            "feature_outcome_joins_calculated": False,
            "relationship_statistics_calculated": False,
            "candidate_discovery_started": False,
            "charts_or_row_payloads_inspected": False,
        },
        "reference_book": {
            "path": _portable_path(reference_book_path),
            "bytes": reference_book_path.stat().st_size,
            "sha256": REFERENCE_BOOK_HASH,
            "traceability_catalog_path": _portable_path(traceability_catalog_path),
            "traceability_catalog_hash": traceability_hash,
            "field_requirements": len(traceability["field_requirements"]),
            "development_coverage_counts": dict(sorted(coverage_counts.items())),
        },
        "case_matrix_schema": {
            "path": _portable_path(case_matrix_schema_path),
            "bytes": case_matrix_schema_path.stat().st_size,
            "sha256": sha256_file(case_matrix_schema_path),
            "case_rows_materialized": 0,
        },
        "preserved_prior_state": {
            "casebook_manifest_path": _portable_path(casebook_manifest_path),
            "casebook_manifest_hash": casebook_manifest["manifest_hash"],
            "original_candidate": original_rejection["selector_code"],
            "original_verdict": original_rejection["verdict"],
            "original_result_manifest_hash": original_rejection["manifest_hash"],
            "v2_candidate": v2_rejection["candidate_code"],
            "v2_verdict": v2_rejection["verdict"],
            "v2_result_manifest_hash": v2_rejection["manifest_hash"],
            "prior_results_reinterpreted": False,
        },
        "development_2021_2024": {
            "start_inclusive": casebook_manifest["contract"]["case_start"],
            "end_exclusive": casebook_manifest["contract"]["case_end_exclusive"],
            "casebook_version": casebook_manifest["casebook_version"],
            "record_counts": casebook_manifest["record_counts"],
            "artifact_metadata": casebook_manifest["artifacts"],
            "known_limits": casebook_manifest["known_limits"],
            "status": "SOURCE_BUNDLE_PRESENT_V3_CASE_ROWS_NOT_MATERIALIZED",
            "outcomes_or_relationships_calculated_by_audit": False,
        },
        "exposed_2025": {
            "classification": "EXPOSED_HISTORICAL_FORWARD_TEST_NO_INDEPENDENT_CREDIT",
            "start_inclusive": EXPOSED_2025_START.isoformat(),
            "end_exclusive": EXPOSED_2025_END.isoformat(),
            "database_metadata": database_metadata["exposed_2025"],
            "raw_xauusd_file_metadata": raw_xau_metadata["exposed_2025"],
            "databento_zn_metadata": cme_2025,
            "values_or_outcomes_read_by_v3_m1": False,
        },
        "locked_2026_ytd": {
            "classification": "LOCKED_INDEPENDENT_HOLDOUT",
            "session_date_start_inclusive": "2026-01-01",
            "session_date_end_inclusive": "2026-07-29",
            "database_metadata_interval": {
                "start_inclusive": LOCKED_2026_YTD_START.isoformat(),
                "end_exclusive": LOCKED_2026_YTD_END.isoformat(),
            },
            "database_metadata": database_metadata["locked_2026_ytd"],
            "raw_xauusd_file_metadata": raw_xau_metadata["locked_2026_ytd"],
            "cme_rates_metadata": cme_2026,
            "values_or_outcomes_read_by_v3_m1": False,
            "value_access_state": "LOCKED",
        },
        "source_family_status": _source_family_status(
            exposed_metadata=database_metadata["exposed_2025"],
            locked_metadata=database_metadata["locked_2026_ytd"],
            exposed_xau=exposed_xau,
            locked_xau=locked_xau,
            cme_2025=cme_2025,
            cme_2026=cme_2026,
        ),
        "material_gaps": _material_gaps(
            traceability=traceability,
            exposed_metadata=database_metadata["exposed_2025"],
            locked_metadata=database_metadata["locked_2026_ytd"],
            cme_2026=cme_2026,
        ),
        "milestone_decision": {
            "v3_milestone_1_coverage_audit_complete": True,
            "case_matrix_rows_built": 0,
            "relationship_calculations": 0,
            "candidates_created": 0,
            "2025_values_inspected": False,
            "2026_values_inspected": False,
            "next_milestone": "V3_M2_DEVELOPMENT_CASE_MATRIX",
            "next_milestone_authorized": False,
            "mandatory_stop": True,
        },
    }
    add_deterministic_hash(report)
    return report


async def _query_partition_metadata(
    *,
    session: Any,
    start: datetime,
    end: datetime,
    session_date_start: date,
    session_date_end: date,
) -> dict[str, Any]:
    parameters = {"start": start, "end": end}
    price_metadata = _rows(
        (await session.execute(text(PRICE_METADATA_SQL), parameters)).mappings().all()
    )
    timestamp_rows = (
        (
            await session.execute(
                text(XAU_FIVE_MINUTE_TIMESTAMPS_SQL),
                parameters,
            )
        )
        .mappings()
        .all()
    )
    return {
        "price_metadata": price_metadata,
        "xauusd_timestamp_only_session_coverage": (
            audit_timestamp_only_session_coverage(
                [row["bucket_open_time"] for row in timestamp_rows],
                session_date_start=session_date_start,
                session_date_end_inclusive=session_date_end,
            )
        ),
        "macro_observation_metadata": _rows(
            (
                await session.execute(
                    text(OBSERVATION_METADATA_SQL),
                    parameters,
                )
            )
            .mappings()
            .all()
        ),
        "cot_metadata": _rows(
            (await session.execute(text(COT_METADATA_SQL), parameters)).mappings().all()
        ),
        "event_metadata": _rows(
            (await session.execute(text(EVENT_METADATA_SQL), parameters)).mappings().all()
        ),
        "forecast_metadata": _rows(
            (
                await session.execute(
                    text(FORECAST_METADATA_SQL),
                    parameters,
                )
            )
            .mappings()
            .all()
        ),
        "release_metadata": _row(
            (
                await session.execute(
                    text(RELEASE_METADATA_SQL),
                    parameters,
                )
            )
            .mappings()
            .one()
        ),
        "policy_expectation_metadata": _rows(
            (
                await session.execute(
                    text(POLICY_METADATA_SQL),
                    parameters,
                )
            )
            .mappings()
            .all()
        ),
    }


def _validate_preserved_history(
    *,
    casebook_manifest: Mapping[str, Any],
    original_rejection: Mapping[str, Any],
    v2_rejection: Mapping[str, Any],
) -> None:
    if (
        casebook_manifest["manifest_hash"]
        != "d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f"
    ):
        raise ValueError("Unexpected immutable casebook manifest")
    if original_rejection["verdict"] != "REJECT_CHRONOLOGICAL_VALIDATION":
        raise ValueError("Original rejection was not preserved")
    if original_rejection["selector_code"] != "UNIVERSAL_ZN_4H_SIGN_V0_1":
        raise ValueError("Unexpected original selector")
    if v2_rejection["verdict"] != "REJECT_CALENDAR_2025_HOLDOUT":
        raise ValueError("V2 rejection was not preserved")
    if v2_rejection["candidate_code"] != "LONDON_ZN_4H_POSTHOC_V0_1":
        raise ValueError("Unexpected V2 candidate")


def _cme_2025_metadata_only(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    normalized_payload = payload["normalized_payload"]
    timestamp_lineage = payload["timestamp_lineage"]
    return {
        "normalization_manifest_path": _portable_path(path),
        "normalization_manifest_file_sha256": sha256_file(path),
        "normalization_hash": payload["normalization_hash"],
        "provider": payload["provider"],
        "dataset": payload["request"]["dataset"],
        "schema": payload["request"]["schema"],
        "continuous_symbol": payload["continuous_symbol"],
        "request_start": payload["request"]["start"],
        "request_end": payload["request"]["end"],
        "request_fingerprint": payload["request_fingerprint"],
        "total_rows_declared": payload["total_rows"],
        "distinct_open_times_declared": payload["distinct_open_times"],
        "duplicate_rows_declared": payload["duplicate_rows"],
        "first_open_time_declared": payload["first_open_time"],
        "last_open_time_declared": payload["last_open_time"],
        "underlying_contract_count": payload["underlying_contract_count"],
        "observed_roll_transition_count": payload["observed_roll_transition_count"],
        "availability_rule": payload["availability_rule"],
        "roll_crossing_policy": payload["roll_crossing_policy"],
        "normalized_payload_metadata": {
            "name": Path(normalized_payload["path"]).name,
            "bytes": normalized_payload["bytes"],
            "sha256": normalized_payload["sha256"],
            "contains_market_values": normalized_payload["contains_market_values"],
            "deserialized_by_v3_milestone_1": False,
        },
        "timestamp_lineage_metadata": {
            "name": Path(timestamp_lineage["path"]).name,
            "bytes": timestamp_lineage["bytes"],
            "sha256": timestamp_lineage["sha256"],
            "contains_market_values": timestamp_lineage["contains_market_values"],
            "deserialized_by_v3_milestone_1": False,
        },
        "classification": "EXPOSED_BY_COMPLETED_V2_HOLDOUT",
    }


def _cme_2026_metadata_only(directory: Path) -> dict[str, Any]:
    if not directory.exists():
        return {
            "directory": _portable_path(directory),
            "exists": False,
            "matching_metadata_files": [],
            "market_value_payloads_deserialized": False,
            "status": "NOT_PRESENT",
        }
    files = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file()
        and path.name.lower()
        in {
            "manifest.json",
            "metadata.json",
            "normalization.json",
            "symbology_lineage.json",
        }
    )
    return {
        "directory": _portable_path(directory),
        "exists": True,
        "matching_metadata_files": [
            {
                "path": _portable_path(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "content_deserialized": False,
            }
            for path in files
        ],
        "market_value_payloads_deserialized": False,
        "status": "METADATA_FILES_PRESENT" if files else "NO_METADATA_FILES",
    }


def _source_family_status(
    *,
    exposed_metadata: Mapping[str, Any],
    locked_metadata: Mapping[str, Any],
    exposed_xau: Mapping[str, Any] | None,
    locked_xau: Mapping[str, Any] | None,
    cme_2025: Mapping[str, Any],
    cme_2026: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "source_family": "XAUUSD_1M_AND_SESSION_TIMESTAMPS",
            "development": "PRESENT_IMMUTABLE_CASEBOOK",
            "exposed_2025": _xau_status(exposed_xau),
            "locked_2026_ytd": _xau_status(locked_xau),
            "candidate_readiness_claim": False,
        },
        {
            "source_family": "MACRO_VINTAGE_METADATA",
            "development": "PRESENT",
            "exposed_2025": (
                "IDENTIFIERS_AND_TIMESTAMPS_PRESENT"
                if exposed_metadata["macro_observation_metadata"]
                else "NO_METADATA_ROWS"
            ),
            "locked_2026_ytd": (
                "IDENTIFIERS_AND_TIMESTAMPS_PRESENT"
                if locked_metadata["macro_observation_metadata"]
                else "NO_METADATA_ROWS"
            ),
            "candidate_readiness_claim": False,
        },
        {
            "source_family": "CFTC_GOLD_COT_METADATA",
            "development": "PRESENT",
            "exposed_2025": (
                "PUBLICATION_METADATA_PRESENT"
                if exposed_metadata["cot_metadata"]
                else "NO_METADATA_ROWS"
            ),
            "locked_2026_ytd": (
                "PUBLICATION_METADATA_PRESENT"
                if locked_metadata["cot_metadata"]
                else "NO_METADATA_ROWS"
            ),
            "candidate_readiness_claim": False,
        },
        {
            "source_family": "ECONOMIC_EVENTS_RELEASES_FORECASTS",
            "development": "PARTIAL_PRE_EVENT_AVAILABILITY",
            "exposed_2025": _event_status(exposed_metadata),
            "locked_2026_ytd": _event_status(locked_metadata),
            "candidate_readiness_claim": False,
        },
        {
            "source_family": "POLICY_EXPECTATION_WINDOWS",
            "development": "PARTIAL_NOT_MEETING_LEVEL_FEDWATCH",
            "exposed_2025": (
                "METADATA_PRESENT"
                if exposed_metadata["policy_expectation_metadata"]
                else "NO_METADATA_ROWS"
            ),
            "locked_2026_ytd": (
                "METADATA_PRESENT"
                if locked_metadata["policy_expectation_metadata"]
                else "NO_METADATA_ROWS"
            ),
            "candidate_readiness_claim": False,
        },
        {
            "source_family": "INTRADAY_CME_TREASURY_FUTURES",
            "development": "PRESENT_ROLL_AWARE",
            "exposed_2025": (
                "SEALED_METADATA_PRESENT"
                if cme_2025["total_rows_declared"] > 0
                else "NO_METADATA_ROWS"
            ),
            "locked_2026_ytd": cme_2026["status"],
            "candidate_readiness_claim": False,
        },
        {
            "source_family": "ETF_CENTRAL_BANK_OPTIONS_DEPTH_UNSCHEDULED_NEWS",
            "development": "UNAVAILABLE",
            "exposed_2025": "NOT_CERTIFIED",
            "locked_2026_ytd": "NOT_CERTIFIED",
            "candidate_readiness_claim": False,
        },
    ]


def _material_gaps(
    *,
    traceability: Mapping[str, Any],
    exposed_metadata: Mapping[str, Any],
    locked_metadata: Mapping[str, Any],
    cme_2026: Mapping[str, Any],
) -> list[dict[str, Any]]:
    unavailable = [
        item["factor_id"]
        for item in traceability["field_requirements"]
        if item["development_coverage"] == "UNAVAILABLE"
    ]
    exposed_forecasts = sum(
        int(row["verified_pre_event_rows"])
        for row in exposed_metadata["forecast_metadata"]
    )
    locked_forecasts = sum(
        int(row["verified_pre_event_rows"])
        for row in locked_metadata["forecast_metadata"]
    )
    locked_counts = locked_metadata["xauusd_timestamp_only_session_coverage"]["counts"]
    return [
        {
            "code": "BOOK_FIELDS_UNAVAILABLE_IN_DEVELOPMENT",
            "severity": "VISIBLE_LIMITATION",
            "factor_ids": unavailable,
            "policy": "Remain UNKNOWN; no proxy substitution or neutral imputation.",
        },
        {
            "code": "HISTORICAL_PRE_EVENT_CONSENSUS_NOT_GENERALLY_VERIFIED",
            "severity": "FEATURE_ELIGIBILITY_LIMITATION",
            "exposed_2025_verified_rows_metadata": exposed_forecasts,
            "locked_2026_ytd_verified_rows_metadata": locked_forecasts,
            "policy": "Only independently verified pre-event availability may enter a decision state.",
        },
        {
            "code": "LOCKED_2026_YTD_XAU_TIMESTAMP_COVERAGE_NOT_FULL_WEEKDAY_SET",
            "severity": "CASE_CONSTRUCTION_COVERAGE_GAP",
            "requested_weekdays": locked_counts["requested_weekdays"],
            "london_complete": locked_counts["london_case_complete"],
            "new_york_complete": locked_counts["new_york_case_complete"],
            "policy": "Do not synthesize missing sessions; repeat metadata audit before holdout opening.",
        },
        {
            "code": "NO_2026_CME_RATES_ARCHIVE",
            "severity": "FUTURE_FEATURE_DEPENDENT",
            "metadata_status": cme_2026["status"],
            "policy": "Acquire only after a frozen candidate demonstrates that the source is required; acquisition is not value-access authorization.",
        },
        {
            "code": "RAW_2026_XAU_FILES_OVERLAP",
            "severity": "INGESTION_LINEAGE_WARNING",
            "policy": "Use canonical database uniqueness and source hashes; never double-count overlapping exports.",
        },
        {
            "code": "NO_CANDIDATE_SPECIFIC_FORWARD_READINESS_IN_MILESTONE_1",
            "severity": "EXPECTED",
            "policy": "Candidate-specific coverage cannot be certified before a candidate and exact fields exist.",
        },
    ]


def _xau_status(row: Mapping[str, Any] | None) -> str:
    if row is None:
        return "NO_METADATA_ROWS"
    if (
        int(row["rows"]) == int(row["distinct_open_times"])
        and int(row["incomplete_rows"]) == 0
        and int(row["synthetic_rows"]) == 0
        and int(row["valid_availability_rows"]) == int(row["rows"])
    ):
        return "OBSERVED_UNIQUE_POINT_IN_TIME_METADATA_PRESENT"
    return "METADATA_PRESENT_WITH_QUALITY_GAPS"


def _event_status(metadata: Mapping[str, Any]) -> str:
    event_rows = sum(int(row["rows"]) for row in metadata["event_metadata"])
    release_rows = int(metadata["release_metadata"]["rows"])
    verified_forecasts = sum(
        int(row["verified_pre_event_rows"]) for row in metadata["forecast_metadata"]
    )
    if event_rows == 0 and release_rows == 0:
        return "NO_METADATA_ROWS"
    if verified_forecasts == 0:
        return "POST_RELEASE_METADATA_PRESENT_PRE_EVENT_UNVERIFIED"
    return "METADATA_PRESENT_WITH_SOME_VERIFIED_PRE_EVENT_ROWS"


def _find_xau_1m(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return next(
        (
            row
            for row in rows
            if row["provider_code"] == "IC_MARKETS_MT5"
            and row["instrument_code"] == "XAUUSD"
            and row["timeframe"] == "1m"
        ),
        None,
    )


def render_markdown(report: Mapping[str, Any]) -> str:
    development = report["development_2021_2024"]
    exposed = report["exposed_2025"]
    locked = report["locked_2026_ytd"]
    exposed_db = exposed["database_metadata"]
    locked_db = locked["database_metadata"]
    exposed_xau = _find_xau_1m(exposed_db["price_metadata"])
    locked_xau = _find_xau_1m(locked_db["price_metadata"])
    exposed_counts = exposed_db["xauusd_timestamp_only_session_coverage"]["counts"]
    locked_counts = locked_db["xauusd_timestamp_only_session_coverage"]["counts"]
    exposed_observations = exposed_db["macro_observation_metadata"]
    locked_observations = locked_db["macro_observation_metadata"]
    exposed_cot = sum(int(row["reports"]) for row in exposed_db["cot_metadata"])
    locked_cot = sum(int(row["reports"]) for row in locked_db["cot_metadata"])
    exposed_events = sum(
        int(row["distinct_events"]) for row in exposed_db["event_metadata"]
    )
    locked_events = sum(
        int(row["distinct_events"]) for row in locked_db["event_metadata"]
    )
    exposed_verified = sum(
        int(row["verified_pre_event_rows"])
        for row in exposed_db["forecast_metadata"]
    )
    locked_verified = sum(
        int(row["verified_pre_event_rows"])
        for row in locked_db["forecast_metadata"]
    )
    exposed_xau_rows = int(exposed_xau["rows"]) if exposed_xau else 0
    locked_xau_rows = int(locked_xau["rows"]) if locked_xau else 0

    return f"""# Gold Session Behaviour V3 — Metadata-Only Coverage Audit

## Decision

The V3 Milestone 1 coverage audit is complete.

- Contract hash:
  `{report["contract"]["manifest_hash"]}`
- Traceability hash:
  `{report["reference_book"]["traceability_catalog_hash"]}`
- Deterministic coverage hash:
  `{report["data_hash"]}`
- 2025 values or outcomes inspected: **no**
- 2026 values or outcomes inspected: **no**
- Relationships calculated: **zero**
- Candidates created: **zero**

This audit does not authorize Milestone 2.

## Audit boundary

The database transaction was read-only. Eight SQL statements passed a
forbidden-value-column guard. They selected identifiers, timestamps, counts,
completeness/synthetic/revision flags, point-in-time ordering counts, and
non-null spread/volume counts only.

Raw XAUUSD files were byte-streamed only to calculate SHA-256, size, filename
time bounds, and overlap metadata. No CSV parser was invoked. The sealed 2025
Databento normalization manifest was read, but its OHLCV payload was not
deserialized.

No market, macro, release, forecast, positioning, probability, feature,
direction, return, excursion, P&L, or outcome value was selected.

## Development: 2021-08-01 through 2024-12-31

The immutable source bundle is present:

| Item | Metadata |
|---|---:|
| Casebook manifest | `{development["casebook_version"]}` / `{report["preserved_prior_state"]["casebook_manifest_hash"]}` |
| London cases already recorded | {development["record_counts"]["london_cases"]} |
| New York cases already recorded | {development["record_counts"]["new_york_cases"]} |
| Session cases | {development["record_counts"]["session_cases"]} |
| Structure snapshots | {development["record_counts"]["structure_snapshots"]} |
| Cross-market snapshots | {development["record_counts"]["cross_market_snapshots"]} |
| Positioning reports | {development["record_counts"]["positioning_reports"]} |
| Event cases | {development["record_counts"]["event_cases"]} |

V3 case rows were not materialized. No development outcome or relationship was
calculated by this audit.

## Exposed calendar 2025

Calendar 2025 is real but already exposed by V2. This run inspected metadata
only.

| Source family | Metadata observed |
|---|---:|
| IC Markets XAUUSD 1m rows | {exposed_xau_rows:,} |
| XAUUSD timestamp-complete London cases | {exposed_counts["london_case_complete"]} / {exposed_counts["requested_weekdays"]} weekdays |
| XAUUSD timestamp-complete New York cases | {exposed_counts["new_york_case_complete"]} / {exposed_counts["requested_weekdays"]} weekdays |
| Macro series identifiers | {len(exposed_observations)} |
| Published COT report metadata rows | {exposed_cot} |
| Economic event identities | {exposed_events} |
| Verified pre-event forecast rows | {exposed_verified} |
| Raw XAU files overlapping interval | {exposed["raw_xauusd_file_metadata"]["files_overlapping_interval"]} |
| Sealed Databento ZN rows declared by metadata | {exposed["databento_zn_metadata"]["total_rows_declared"]:,} |

These counts do not grant 2025 independent-validation status and do not expose
the underlying values.

## Locked 2026 YTD

The independent YTD date boundary is session dates 1 January through
29 July 2026. Values remain locked.

| Source family | Metadata observed |
|---|---:|
| IC Markets XAUUSD 1m rows | {locked_xau_rows:,} |
| XAUUSD timestamp-complete London cases | {locked_counts["london_case_complete"]} / {locked_counts["requested_weekdays"]} weekdays |
| XAUUSD timestamp-complete New York cases | {locked_counts["new_york_case_complete"]} / {locked_counts["requested_weekdays"]} weekdays |
| Macro series identifiers | {len(locked_observations)} |
| Published COT report metadata rows | {locked_cot} |
| Economic event identities | {locked_events} |
| Verified pre-event forecast rows | {locked_verified} |
| Raw XAU files overlapping interval | {locked["raw_xauusd_file_metadata"]["files_overlapping_interval"]} |
| Overlapping raw-XAU filename pairs | {len(locked["raw_xauusd_file_metadata"]["overlapping_filename_pairs"])} |
| 2026 CME rates archive | {locked["cme_rates_metadata"]["status"]} |

The timestamp audit shows that the locked YTD source is not yet a complete
weekday set. Missing sessions are retained in the JSON artifact and may not be
synthesized. Several raw 2026 MT5 exports overlap; canonical database
uniqueness and source hashes must prevent double counting.

## Book-field coverage

The 75 frozen Reference Book requirements have the following development
status:

| Status | Count |
|---|---:|
| Present | {report["reference_book"]["development_coverage_counts"].get("PRESENT", 0)} |
| Derivable, not calculated | {report["reference_book"]["development_coverage_counts"].get("DERIVABLE", 0)} |
| Partial | {report["reference_book"]["development_coverage_counts"].get("PARTIAL", 0)} |
| Unavailable | {report["reference_book"]["development_coverage_counts"].get("UNAVAILABLE", 0)} |
| Execution out of scope | {report["reference_book"]["development_coverage_counts"].get("OUT_OF_SCOPE", 0)} |

The unavailable fields remain order-book depth/resilience/impact, exact
meeting-level Fed probabilities, ETF flows, central-bank demand, options/gamma,
and unscheduled-news history.

## Preserved negative evidence

- `UNIVERSAL_ZN_4H_SIGN_V0_1` remains
  `{report["preserved_prior_state"]["original_verdict"]}`.
- `LONDON_ZN_4H_POSTHOC_V0_1` remains
  `{report["preserved_prior_state"]["v2_verdict"]}`.

The 2025 ZN archive remains a sealed real source, but the rejected rule is not
reopened, inverted, filtered, or renamed.

## Readiness interpretation

This is a source-family audit, not candidate readiness:

- the development bundle is available for a separately authorized V3
  Milestone 2;
- 2025 remains excluded from discovery;
- 2026 source coverage is incomplete and its values remain locked;
- exact future candidate coverage cannot be certified before candidates exist;
  and
- no paid 2026 acquisition is justified in Milestone 1.

## Mandatory stop

V3 Milestone 1 ends after governance validation and state sealing. V3
Milestone 2 is not authorized and was not started.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${{PWD}}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/audit_gold_session_behaviour_v3_coverage.py `
  --mt5-directory /workspace/data/mt5 `
  --cme-2025-normalization /workspace/data/raw/databento_cme_2025_zn/GLBX-20260729-4KJJLBXRRH/normalized/normalization.json `
  --cme-2026-directory /workspace/data/raw/databento_cme_2026 `
  --contract-manifest /workspace/research_manifests/gold_session_behaviour_discovery_contract_v03.json `
  --traceability-catalog /workspace/research_manifests/gold_session_behaviour_v3_traceability_v01.json `
  --case-matrix-schema /workspace/research_schemas/gold_session_behaviour_v3_case_matrix.schema.json `
  --casebook-manifest /workspace/research_artifacts/gold_casebook_v01/manifest.json `
  --original-rejection-manifest /workspace/research_artifacts/gold_casebook_chronological_validation_v01/manifest.json `
  --v2-rejection-manifest /workspace/research_artifacts/gold_casebook_discovery_v2_holdout_v01/manifest.json `
  --reference-book /workspace/Gold_USD_Market_Intelligence_Reference_Book.pdf `
  --json-output /workspace/research_artifacts/gold_session_behaviour_v3_coverage_v01.json `
  --markdown-output /workspace/GOLD_SESSION_BEHAVIOUR_V3_COVERAGE.md
```
"""


def _row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): json_ready(value) for key, value in row.items()}


def _rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Gold Session Behaviour V3 metadata-only coverage audit."
    )
    parser.add_argument("--mt5-directory", required=True)
    parser.add_argument("--cme-2025-normalization", required=True)
    parser.add_argument("--cme-2026-directory", required=True)
    parser.add_argument("--contract-manifest", required=True)
    parser.add_argument("--traceability-catalog", required=True)
    parser.add_argument("--case-matrix-schema", required=True)
    parser.add_argument("--casebook-manifest", required=True)
    parser.add_argument("--original-rejection-manifest", required=True)
    parser.add_argument("--v2-rejection-manifest", required=True)
    parser.add_argument("--reference-book", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    return parser


if __name__ == "__main__":
    asyncio.run(main())
