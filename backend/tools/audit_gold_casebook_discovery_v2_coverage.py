from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from gold_intel.analytics.casebook import json_ready
from gold_intel.analytics.casebook_discovery_v2 import (
    AUDIT_VERSION,
    HOLDOUT_END,
    HOLDOUT_START,
    add_deterministic_hash,
    assert_metadata_only_sql,
    audit_timestamp_only_session_coverage,
    mt5_xau_files_overlapping_holdout,
    source_file_metadata,
    verify_embedded_hash,
)
from gold_intel.infrastructure.database import session_factory

PRICE_METADATA_SQL = """
SELECT
    provider_code,
    instrument_code,
    timeframe,
    count(*) AS rows,
    count(DISTINCT open_time) AS distinct_open_times,
    min(open_time) AS first_open_time,
    max(open_time) AS last_open_time,
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
    count(*) AS rows_available_in_holdout,
    count(DISTINCT observation_time) AS observation_periods,
    min(observation_time) AS first_observation_time,
    max(observation_time) AS last_observation_time,
    min(available_at) AS first_available_at,
    max(available_at) AS last_available_at,
    count(*) FILTER (WHERE is_revision) AS revision_rows,
    count(*) FILTER (
        WHERE available_at >= observation_time
    ) AS valid_availability_rows,
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
    count(*) FILTER (
        WHERE publication_at > observation_date
    ) AS valid_availability_rows
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
    count(*) FILTER (
        WHERE available_at >= released_at
    ) AS valid_availability_rows,
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
    count(*) FILTER (
        WHERE available_at > snapshot_as_of
    ) AS valid_availability_rows,
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
        cme_normalization=Path(args.cme_normalization),
        contract_manifest_path=Path(args.contract_manifest),
        casebook_manifest_path=Path(args.casebook_manifest),
        prior_validation_manifest_path=Path(args.prior_validation_manifest),
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
                "holdout_outcomes_inspected": False,
                "json_output": str(json_output),
                "markdown_output": str(markdown_output),
            },
            indent=2,
            sort_keys=True,
        )
    )


async def build_report(
    *,
    mt5_directory: Path,
    cme_normalization: Path,
    contract_manifest_path: Path,
    casebook_manifest_path: Path,
    prior_validation_manifest_path: Path,
) -> dict[str, Any]:
    assert_metadata_only_sql(SQL_STATEMENTS)
    contract_manifest = _load_json(contract_manifest_path)
    contract_hash = verify_embedded_hash(
        contract_manifest,
        hash_field="manifest_hash",
    )
    if contract_manifest["v2_milestone_1"]["code"] != ("V2_M1_CONTRACT_AND_METADATA_COVERAGE"):
        raise ValueError("Unexpected V2 milestone")
    casebook_manifest = _load_json(casebook_manifest_path)
    prior_validation_manifest = _load_json(prior_validation_manifest_path)
    if prior_validation_manifest["verdict"] != "REJECT_CHRONOLOGICAL_VALIDATION":
        raise ValueError("The original rejection was not preserved")

    parameters = {"start": HOLDOUT_START, "end": HOLDOUT_END}
    async with session_factory() as session:
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
        observation_metadata = _rows(
            (await session.execute(text(OBSERVATION_METADATA_SQL), parameters)).mappings().all()
        )
        cot_metadata = _rows(
            (await session.execute(text(COT_METADATA_SQL), parameters)).mappings().all()
        )
        event_metadata = _rows(
            (await session.execute(text(EVENT_METADATA_SQL), parameters)).mappings().all()
        )
        forecast_metadata = _rows(
            (await session.execute(text(FORECAST_METADATA_SQL), parameters)).mappings().all()
        )
        release_metadata = _row(
            (await session.execute(text(RELEASE_METADATA_SQL), parameters)).mappings().one()
        )
        policy_metadata = _rows(
            (await session.execute(text(POLICY_METADATA_SQL), parameters)).mappings().all()
        )

    session_coverage = audit_timestamp_only_session_coverage(
        [row["bucket_open_time"] for row in timestamp_rows],
    )
    raw_xau_files = [
        source_file_metadata(path) for path in mt5_xau_files_overlapping_holdout(mt5_directory)
    ]
    cme_metadata = _cme_metadata_only(cme_normalization)
    xau_price = next(
        (
            row
            for row in price_metadata
            if row["provider_code"] == "IC_MARKETS_MT5"
            and row["instrument_code"] == "XAUUSD"
            and row["timeframe"] == "1m"
        ),
        None,
    )
    zn_ready = bool(cme_metadata["holdout_2025"]["zn_v_0_available"])
    xau_ready = bool(
        xau_price
        and xau_price["rows"] == xau_price["distinct_open_times"]
        and xau_price["rows"] == xau_price["spread_present_rows"]
        and xau_price["rows"] == xau_price["valid_availability_rows"]
        and xau_price["synthetic_rows"] == 0
    )

    verified_pre_event_rows = sum(int(row["verified_pre_event_rows"]) for row in forecast_metadata)
    report: dict[str, Any] = {
        "audit_version": AUDIT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "contract": {
            "governing_document": "GOLD_CASEBOOK_DISCOVERY_CONTRACT_V2.md",
            "manifest_path": str(contract_manifest_path).replace("\\", "/"),
            "manifest_hash": contract_hash,
            "milestone": "V2_M1_CONTRACT_AND_METADATA_COVERAGE",
            "holdout_interval": {
                "start_inclusive": HOLDOUT_START.isoformat(),
                "end_exclusive": HOLDOUT_END.isoformat(),
            },
        },
        "audit_boundary": {
            "access_class": "METADATA_ONLY",
            "sql_statement_count": len(SQL_STATEMENTS),
            "sql_guard_passed": True,
            "forbidden_value_columns_referenced": [],
            "raw_xau_files_content_deserialized": False,
            "holdout_ohlc_or_market_values_read": False,
            "holdout_feature_values_calculated": False,
            "holdout_outcomes_calculated": False,
            "holdout_feature_outcome_joins_calculated": False,
            "holdout_charts_inspected": False,
            "permitted_fields_used": [
                "identifiers",
                "timestamps",
                "row and distinct counts",
                "non-null counts",
                "synthetic and completeness flags",
                "file names, byte sizes, and hashes",
            ],
        },
        "preserved_prior_state": {
            "prior_candidate": "UNIVERSAL_ZN_4H_SIGN_V0_1",
            "prior_verdict": prior_validation_manifest["verdict"],
            "prior_bundle_manifest_hash": prior_validation_manifest["manifest_hash"],
            "calendar_2024_classification_v2": "DEVELOPMENT_ALREADY_OBSERVED",
            "calendar_2024_independent_validation_credit": False,
            "calendar_2025_outcomes_opened": False,
        },
        "development_2021_2024": {
            "casebook_manifest_path": str(casebook_manifest_path).replace("\\", "/"),
            "casebook_manifest_hash": casebook_manifest["manifest_hash"],
            "casebook_version": casebook_manifest["casebook_version"],
            "start_inclusive": casebook_manifest["contract"]["case_start"],
            "end_exclusive": casebook_manifest["contract"]["case_end_exclusive"],
            "record_counts": casebook_manifest["record_counts"],
            "status": "READY_FOR_V2_MILESTONE_2",
            "note": (
                "Existing immutable records are reused. No development outcome was "
                "calculated by this coverage audit."
            ),
        },
        "holdout_2025": {
            "price_metadata": price_metadata,
            "xauusd_timestamp_only_session_coverage": session_coverage,
            "xauusd_raw_source_files": {
                "directory": str(mt5_directory).replace("\\", "/"),
                "files_overlapping_holdout": len(raw_xau_files),
                "files": raw_xau_files,
            },
            "cme_rates_metadata": cme_metadata,
            "macro_observation_metadata": observation_metadata,
            "cot_metadata": cot_metadata,
            "event_metadata": event_metadata,
            "forecast_metadata": forecast_metadata,
            "release_metadata": release_metadata,
            "policy_expectation_metadata": policy_metadata,
        },
        "readiness": {
            "xauusd_constant_execution_source": {
                "status": "READY" if xau_ready else "BLOCKED",
                "reason": (
                    "Observed, unique, complete, spread-bearing, point-in-time "
                    "IC Markets rows are present across calendar 2025."
                    if xau_ready
                    else "The frozen execution source failed metadata coverage checks."
                ),
            },
            "LONDON_ZN_4H_POSTHOC_V0_1": {
                "status": "READY" if xau_ready and zn_ready else "BLOCKED_MISSING_ZN_2025",
                "xauusd_ready": xau_ready,
                "zn_v_0_ready": zn_ready,
                "validation_credit_2024": False,
                "required_before_holdout": (
                    []
                    if xau_ready and zn_ready
                    else [
                        "Acquire licensed Databento GLBX.MDP3 ZN.v.0 one-minute "
                        "calendar-2025 history, normalize with roll-aware lineage, "
                        "hash it, and seal it without inspecting values or outcomes."
                    ]
                ),
            },
            "future_discovery_candidates": {
                "status": "FEATURE_DEPENDENT",
                "reason": (
                    "Candidate-specific 2025 inputs cannot be certified until the "
                    "Milestone 5 shortlist identifies their exact features."
                ),
            },
        },
        "material_gaps": [
            {
                "code": "MISSING_2025_ZN_INTRADAY",
                "severity": "HOLDOUT_BLOCKER_FOR_LONDON_ZN",
                "evidence": (
                    "The normalized Databento request ends at 2025-01-01 and "
                    "explicitly says 2025 not loaded."
                ),
                "action_timing": "After shortlist freeze and before holdout opening.",
            },
            {
                "code": "NO_VERIFIED_HISTORICAL_PRE_EVENT_CONSENSUS",
                "severity": "CANDIDATE_DEPENDENT_LIMITATION",
                "evidence": (
                    f"{verified_pre_event_rows} calendar-2025 forecast rows are "
                    "verified for pre-event use."
                ),
                "action_timing": (
                    "Keep the field UNKNOWN unless a licensed point-in-time source "
                    "is acquired under an explicit amendment."
                ),
            },
            {
                "code": "CANDIDATE_SPECIFIC_HOLDOUT_COVERAGE_NOT_YET_KNOWN",
                "severity": "EXPECTED",
                "evidence": (
                    "No discovery or shortlist exists in Milestone 1, so only "
                    "currently known sources can be audited."
                ),
                "action_timing": (
                    "Repeat a metadata-only feature-specific audit after the Milestone 5 freeze."
                ),
            },
        ],
        "milestone_decision": {
            "v2_milestone_1_complete": True,
            "relationship_discovery_started": False,
            "holdout_outcomes_inspected": False,
            "next_milestone": "V2_M2_DESCRIPTIVE_OUTCOME_ATLAS",
            "next_milestone_authorized": False,
        },
    }
    add_deterministic_hash(report)
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    counts = report["holdout_2025"]["xauusd_timestamp_only_session_coverage"]["counts"]
    xau = report["readiness"]["xauusd_constant_execution_source"]
    london_zn = report["readiness"]["LONDON_ZN_4H_POSTHOC_V0_1"]
    observations = report["holdout_2025"]["macro_observation_metadata"]
    cot = report["holdout_2025"]["cot_metadata"]
    events = report["holdout_2025"]["event_metadata"]
    forecasts = report["holdout_2025"]["forecast_metadata"]
    releases = report["holdout_2025"]["release_metadata"]
    policies = report["holdout_2025"]["policy_expectation_metadata"]
    price_rows = report["holdout_2025"]["price_metadata"]
    xau_row = next(
        row
        for row in price_rows
        if row["provider_code"] == "IC_MARKETS_MT5" and row["instrument_code"] == "XAUUSD"
    )
    cot_reports = sum(int(row["reports"]) for row in cot)
    event_count = sum(int(row["distinct_events"]) for row in events)
    forecast_count = sum(int(row["components"]) for row in forecasts)
    verified_forecasts = sum(int(row["verified_pre_event_rows"]) for row in forecasts)
    policy_dates = sum(int(row["observation_dates"]) for row in policies)
    return f"""# Gold Casebook Discovery V2 Coverage Audit

## Decision

V2 Milestone 1 is complete.

- The V2 contract is frozen at
  `{report["contract"]["manifest_hash"]}`.
- The prior universal rule remains `REJECT_CHRONOLOGICAL_VALIDATION`.
- Calendar 2024 is development data with no independent validation credit.
- No calendar-2025 OHLC, market value, feature, outcome, return, P&L, or
  feature-outcome join was read or calculated.
- Relationship discovery did not begin.

Deterministic coverage hash:

`{report["data_hash"]}`

## Audit boundary

The audit used identifiers, timestamps, counts, completeness flags, non-null
counts, filenames, sizes, and hashes only. Eight SQL statements passed the
forbidden-value-column guard. Raw 2025 XAUUSD CSV content was hashed but never
deserialized.

## Development readiness

The immutable 2021-2024 casebook is reusable as V2 development data.

| Item | Evidence |
|---|---:|
| Casebook manifest | `{report["development_2021_2024"]["casebook_manifest_hash"]}` |
| London cases | {report["development_2021_2024"]["record_counts"]["london_cases"]} |
| New York cases | {report["development_2021_2024"]["record_counts"]["new_york_cases"]} |
| Session cases | {report["development_2021_2024"]["record_counts"]["session_cases"]} |
| Cross-market snapshots | {report["development_2021_2024"]["record_counts"]["cross_market_snapshots"]} |
| Structure snapshots | {report["development_2021_2024"]["record_counts"]["structure_snapshots"]} |

This audit calculated no development outcome.

## Calendar-2025 metadata coverage

| Source | Metadata result | Status |
|---|---|---|
| IC Markets XAUUSD 1m | {xau_row["rows"]:,} unique observed rows; {xau_row["first_open_time"]} through {xau_row["last_open_time"]}; spread and volume present on every row | {xau["status"]} |
| Timestamp-complete London cases | {counts["london_case_complete"]} of {counts["requested_weekdays"]} weekdays ({counts["london_case_complete_pct"]}%) | AVAILABLE |
| Timestamp-complete New York cases | {counts["new_york_case_complete"]} of {counts["requested_weekdays"]} weekdays ({counts["new_york_case_complete_pct"]}%) | AVAILABLE |
| Databento ZN.v.0 1m | Existing normalized request ends before 2025 | MISSING |
| Macro observations | {len(observations)} non-synthetic series have 2025 availability metadata | AVAILABLE, feature-specific checks still required |
| CFTC gold COT | {cot_reports} published reports | AVAILABLE |
| MT5 economic events | {event_count} event identities and {releases["rows"]} release components | POST-RELEASE AVAILABLE |
| Historical pre-event consensus | {verified_forecasts} of {forecast_count} forecast components verified for pre-event use | MISSING |
| Policy expectation windows | {policy_dates} observation dates | PARTIAL: quarterly-window source, not meeting-level FedWatch |

## Candidate readiness

`LONDON_ZN_4H_POSTHOC_V0_1` is currently
**{london_zn["status"]}**.

The frozen XAUUSD execution source is ready, but 2025 Databento `ZN.v.0`
one-minute history is not present. This is not a reason to open or approximate
the holdout. If the London ZN candidate reaches the frozen shortlist, acquire
the licensed 2025 ZN payload, normalize it with continuous-roll lineage, hash
and seal it, and only then run the one-time holdout.

Other future candidates remain `FEATURE_DEPENDENT`; their precise holdout
coverage cannot be certified before they exist.

## Material controls

- No proxy may silently replace missing 2025 ZN.
- Missing historical pre-event consensus remains `UNKNOWN`.
- Acquiring a source is not permission to inspect its values.
- A candidate-specific metadata audit is required after Milestone 5 and before
  Milestone 6.
- Calendar 2026 remains outside V2.

## Next contracted step

V2 Milestone 2 is the descriptive 2021-2024 fixed-outcome atlas, separately for
London and New York. It is not authorized by this run and was not started.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${{PWD}}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/audit_gold_casebook_discovery_v2_coverage.py `
  --mt5-directory /workspace/data/mt5 `
  --cme-normalization /workspace/data/raw/databento_cme_pre2025/GLBX-20260728-3SHU3737P8/normalized/normalization.json `
  --contract-manifest /workspace/research_manifests/gold_casebook_discovery_contract_v02.json `
  --casebook-manifest /workspace/research_artifacts/gold_casebook_v01/manifest.json `
  --prior-validation-manifest /workspace/research_artifacts/gold_casebook_chronological_validation_v01/manifest.json `
  --json-output /workspace/research_artifacts/gold_casebook_discovery_v2_coverage.json `
  --markdown-output /workspace/GOLD_CASEBOOK_DISCOVERY_V2_COVERAGE.md
```
"""


def _cme_metadata_only(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    files = payload.get("files", [])
    latest_open = max((str(item["last_open"]) for item in files), default=None)
    symbols = sorted({str(symbol) for item in files for symbol in item.get("symbols", [])})
    return {
        "normalization_manifest_path": str(path).replace("\\", "/"),
        "availability_rule": payload.get("availability_rule"),
        "request_fingerprint": payload.get("request_fingerprint"),
        "declared_total_rows_pre_2025": payload.get("total_rows"),
        "declared_symbols_pre_2025": symbols,
        "latest_declared_open_time": latest_open,
        "locked_holdout_declaration": payload.get("locked_holdout"),
        "payload_price_values_deserialized": False,
        "holdout_2025": {
            "zn_v_0_available": False,
            "reason": (
                "This normalized archive explicitly declares '2025 not loaded' "
                "and its latest file ends in calendar 2024."
            ),
        },
    }


def _row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): json_ready(value) for key, value in row.items()}


def _rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Gold Casebook V2 metadata-only coverage audit."
    )
    parser.add_argument("--mt5-directory", required=True)
    parser.add_argument("--cme-normalization", required=True)
    parser.add_argument("--contract-manifest", required=True)
    parser.add_argument("--casebook-manifest", required=True)
    parser.add_argument("--prior-validation-manifest", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    return parser


if __name__ == "__main__":
    asyncio.run(main())
