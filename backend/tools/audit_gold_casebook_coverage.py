from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from typing import Any
from uuid import UUID

from sqlalchemy import text

from gold_intel.analytics.casebook_coverage import (
    AUDIT_VERSION,
    add_deterministic_hash,
    audit_session_windows,
    build_field_registry,
    eligible_record_coverage,
    validate_development_period,
)
from gold_intel.infrastructure.database import session_factory

PRICE_COVERAGE_SQL = text(
    """
    SELECT
        provider_code,
        instrument_code,
        timeframe,
        count(*) AS rows,
        min(open_time) AS first_open,
        max(open_time) AS last_open,
        count(*) FILTER (WHERE is_complete) AS complete_rows,
        count(*) FILTER (WHERE spread_price IS NOT NULL) AS spread_rows,
        count(*) FILTER (WHERE volume IS NOT NULL) AS volume_rows,
        count(*) FILTER (WHERE available_at <= close_time) AS point_in_time_rows
    FROM market.price_bars
    WHERE open_time >= :start
      AND open_time < :end
      AND available_at < :end
      AND NOT is_synthetic
    GROUP BY 1, 2, 3
    ORDER BY 2, 1, 3
    """
)

XAU_FIVE_MINUTE_SQL = text(
    """
    WITH canonical AS (
        SELECT DISTINCT ON (open_time)
            open_time,
            close_time,
            available_at
        FROM market.price_bars
        WHERE provider_code = 'IC_MARKETS_MT5'
          AND instrument_code = 'XAUUSD'
          AND timeframe = '1m'
          AND is_complete
          AND NOT is_synthetic
          AND open_time >= :start
          AND open_time < :end
          AND available_at <= close_time
        ORDER BY open_time, available_at
    )
    SELECT time_bucket('5 minutes', open_time) AS open_time
    FROM canonical
    GROUP BY 1
    HAVING count(*) = 5
    ORDER BY 1
    """
)

SERIES_COVERAGE_SQL = text(
    """
    SELECT
        s.code AS series_code,
        s.frequency,
        s.expected_lag_seconds,
        s.metadata_json,
        count(o.*) AS rows,
        min(o.observation_time) AS first_observation,
        max(o.observation_time) AS last_observation,
        min(o.available_at) AS first_available,
        max(o.available_at) AS last_available,
        count(*) FILTER (WHERE o.is_revision) AS revision_rows,
        count(*) FILTER (WHERE o.available_at >= o.observation_time) AS valid_order_rows
    FROM catalog.series s
    LEFT JOIN market.observations o
      ON o.series_code = s.code
     AND o.available_at < :end
     AND NOT o.is_synthetic
    GROUP BY 1, 2, 3, 4
    ORDER BY 1
    """
)

OBSERVATION_AVAILABILITY_SQL = text(
    """
    SELECT series_code, available_at, source_record_key
    FROM market.observations
    WHERE available_at < :end
      AND NOT is_synthetic
    ORDER BY series_code, available_at
    """
)

EVENT_BY_CODE_SQL = text(
    """
    SELECT
        provider_code,
        event_code,
        count(*) AS versions,
        count(DISTINCT scheduled_at) AS events,
        min(scheduled_at) AS first_event,
        max(scheduled_at) AS last_event,
        count(*) FILTER (WHERE released_at IS NOT NULL) AS released_versions,
        count(*) FILTER (
            WHERE metadata_json ? 'point_in_time_warning'
        ) AS point_in_time_warning_rows
    FROM market.economic_events
    WHERE scheduled_at >= :start
      AND scheduled_at < :end
      AND available_at < :end
      AND NOT is_synthetic
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
)

FORECAST_SUMMARY_SQL = text(
    """
    SELECT
        count(*) AS rows,
        count(DISTINCT (event_code, scheduled_at, component_code)) AS components,
        min(scheduled_at) AS first_event,
        max(scheduled_at) AS last_event,
        count(*) FILTER (
            WHERE forecast_as_of <= scheduled_at
              AND available_at <= scheduled_at
        ) AS timestamp_pre_release_rows,
        count(*) FILTER (
            WHERE metadata_json->>'pre_event_use_allowed' = 'true'
        ) AS pre_event_allowed_rows,
        count(*) FILTER (
            WHERE metadata_json->>'availability_quality'
                = 'HISTORICAL_RELEASE_BOUNDARY'
        ) AS release_boundary_rows
    FROM market.forecast_snapshots
    WHERE scheduled_at >= :start
      AND scheduled_at < :end
      AND available_at < :end
      AND NOT is_synthetic
    """
)

RELEASE_SUMMARY_SQL = text(
    """
    SELECT
        count(*) AS rows,
        count(DISTINCT event_id) AS events,
        count(DISTINCT component_code) AS component_codes,
        min(released_at) AS first_release,
        max(released_at) AS last_release,
        count(*) FILTER (WHERE previous_value IS NOT NULL) AS previous_value_rows,
        count(*) FILTER (
            WHERE revised_previous_value IS NOT NULL
        ) AS revised_previous_rows,
        count(*) FILTER (WHERE is_revision) AS revision_rows,
        count(*) FILTER (WHERE available_at >= released_at) AS valid_order_rows
    FROM market.economic_releases
    WHERE released_at >= :start
      AND released_at < :end
      AND available_at < :end
      AND NOT is_synthetic
    """
)

RELEASE_COMPONENT_SQL = text(
    """
    SELECT
        r.component_code,
        count(*) AS rows,
        count(*) FILTER (WHERE r.previous_value IS NOT NULL) AS previous_value_rows,
        count(*) FILTER (
            WHERE r.revised_previous_value IS NOT NULL
        ) AS revised_previous_rows,
        count(*) FILTER (
            WHERE EXISTS (
                SELECT 1
                FROM market.forecast_snapshots f
                WHERE f.event_code = e.event_code
                  AND f.scheduled_at = e.scheduled_at
                  AND f.component_code = r.component_code
                  AND f.available_at <= r.released_at
                  AND NOT f.is_synthetic
            )
        ) AS release_boundary_forecast_rows,
        count(*) FILTER (
            WHERE EXISTS (
                SELECT 1
                FROM market.forecast_snapshots f
                WHERE f.event_code = e.event_code
                  AND f.scheduled_at = e.scheduled_at
                  AND f.component_code = r.component_code
                  AND f.metadata_json->>'pre_event_use_allowed' = 'true'
                  AND f.available_at <= e.scheduled_at
                  AND NOT f.is_synthetic
            )
        ) AS verified_pre_event_forecast_rows
    FROM market.economic_releases r
    JOIN market.economic_events e ON e.id = r.event_id
    WHERE r.released_at >= :start
      AND r.released_at < :end
      AND r.available_at < :end
      AND NOT r.is_synthetic
    GROUP BY 1
    ORDER BY 1
    """
)

COT_REPORT_SQL = text(
    """
    SELECT
        provider_code,
        report_type,
        contract_market_code,
        count(*) AS reports,
        count(DISTINCT observation_date) AS effective_observations,
        min(observation_date) AS first_observation,
        max(observation_date) AS last_observation,
        min(publication_at) AS first_publication,
        max(publication_at) AS last_publication,
        count(*) FILTER (
            WHERE publication_at > observation_date
        ) AS valid_availability_rows
    FROM market.cot_reports
    WHERE publication_at < :end
    GROUP BY 1, 2, 3
    ORDER BY 1, 2, 3
    """
)

COT_POSITION_SQL = text(
    """
    SELECT
        cp.category,
        count(*) AS rows,
        count(DISTINCT cr.observation_date) AS effective_observations,
        count(*) FILTER (
            WHERE cp.spreading_contracts IS NOT NULL
        ) AS spreading_rows,
        count(*) FILTER (
            WHERE cp.percent_open_interest_long IS NOT NULL
              AND cp.percent_open_interest_short IS NOT NULL
        ) AS percent_open_interest_rows,
        count(*) FILTER (
            WHERE cp.traders_long IS NOT NULL
              AND cp.traders_short IS NOT NULL
        ) AS trader_count_rows
    FROM market.cot_positions cp
    JOIN market.cot_reports cr ON cr.id = cp.report_id
    WHERE cr.publication_at < :end
    GROUP BY 1
    ORDER BY 1
    """
)

COT_AVAILABILITY_SQL = text(
    """
    SELECT publication_at, observation_date
    FROM market.cot_reports
    WHERE publication_at < :end
    ORDER BY publication_at
    """
)

POLICY_SUMMARY_SQL = text(
    """
    SELECT
        provider_code,
        count(*) AS rows,
        count(DISTINCT observation_date) AS effective_observations,
        min(observation_date) AS first_observation,
        max(observation_date) AS last_observation,
        count(*) FILTER (
            WHERE available_at > snapshot_as_of
        ) AS valid_availability_rows,
        count(*) FILTER (
            WHERE probability_cut IS NOT NULL
        ) AS cut_probability_rows,
        count(*) FILTER (
            WHERE probability_hike IS NOT NULL
        ) AS hike_probability_rows
    FROM market.policy_expectation_windows
    WHERE available_at < :end
    GROUP BY 1
    ORDER BY 1
    """
)

POLICY_AVAILABILITY_SQL = text(
    """
    SELECT available_at, observation_date
    FROM market.policy_expectation_windows
    WHERE available_at < :end
    ORDER BY available_at
    """
)

PROVENANCE_INCONSISTENCY_SQL = text(
    """
    SELECT
        s.code AS series_code,
        s.metadata_json->>'synthetic_fixture' AS catalog_synthetic_fixture,
        bool_or(o.is_synthetic) AS any_normalized_synthetic,
        array_agg(DISTINCT b.provider_code) AS batch_providers,
        count(*) AS rows
    FROM catalog.series s
    JOIN market.observations o ON o.series_code = s.code
    JOIN raw.ingestion_batches b ON b.id = o.batch_id
    WHERE s.metadata_json ? 'synthetic_fixture'
      AND o.available_at < :end
    GROUP BY 1, 2
    ORDER BY 1
    """
)


async def main() -> None:
    args = _parser().parse_args()
    start = _parse_date_boundary(args.start)
    end = _parse_date_boundary(args.end)
    validate_development_period(start, end)

    report = await _build_report(
        start=start,
        end=end,
        cme_normalization=Path(args.cme_normalization),
    )
    json_output = Path(args.json_output)
    markdown_output = Path(args.markdown_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_output.write_text(_render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "audit_version": AUDIT_VERSION,
                "json_output": str(json_output),
                "markdown_output": str(markdown_output),
                "data_hash": report["data_hash"],
                "holdout_loaded": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _build_report(
    *,
    start: datetime,
    end: datetime,
    cme_normalization: Path,
) -> dict[str, Any]:
    parameters = {"start": start, "end": end}
    async with session_factory() as session:
        price_sources = _rows(
            (await session.execute(PRICE_COVERAGE_SQL, parameters)).mappings().all()
        )
        five_minute_open_times = [
            row["open_time"]
            for row in (
                await session.execute(XAU_FIVE_MINUTE_SQL, parameters)
            ).mappings()
        ]
        series_sources = _rows(
            (await session.execute(SERIES_COVERAGE_SQL, {"end": end})).mappings().all()
        )
        observation_rows = (
            await session.execute(OBSERVATION_AVAILABILITY_SQL, {"end": end})
        ).mappings().all()
        events_by_code = _rows(
            (await session.execute(EVENT_BY_CODE_SQL, parameters)).mappings().all()
        )
        forecast_summary = _row(
            (await session.execute(FORECAST_SUMMARY_SQL, parameters)).mappings().one()
        )
        release_summary = _row(
            (await session.execute(RELEASE_SUMMARY_SQL, parameters)).mappings().one()
        )
        release_components = _rows(
            (await session.execute(RELEASE_COMPONENT_SQL, parameters)).mappings().all()
        )
        cot_reports = _rows(
            (await session.execute(COT_REPORT_SQL, {"end": end})).mappings().all()
        )
        cot_positions = _rows(
            (await session.execute(COT_POSITION_SQL, {"end": end})).mappings().all()
        )
        cot_times = (
            await session.execute(COT_AVAILABILITY_SQL, {"end": end})
        ).mappings().all()
        policy_rows = _rows(
            (await session.execute(POLICY_SUMMARY_SQL, {"end": end})).mappings().all()
        )
        policy_times = (
            await session.execute(POLICY_AVAILABILITY_SQL, {"end": end})
        ).mappings().all()
        provenance_inconsistencies = _rows(
            (
                await session.execute(PROVENANCE_INCONSISTENCY_SQL, {"end": end})
            ).mappings().all()
        )

    session_coverage, decision_times = audit_session_windows(
        five_minute_open_times,
        start=start,
        end=end,
    )
    observations_by_series: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for row in observation_rows:
        observations_by_series[str(row["series_code"])].append(
            (row["available_at"], str(row["source_record_key"]))
        )
    series_eligibility = {
        series_code: {
            session_code: eligible_record_coverage(decisions, records)
            for session_code, decisions in decision_times.items()
        }
        for series_code, records in sorted(observations_by_series.items())
    }

    cot_records = [
        (row["publication_at"], str(row["observation_date"])) for row in cot_times
    ]
    cot_eligibility = {
        session_code: eligible_record_coverage(decisions, cot_records)
        for session_code, decisions in decision_times.items()
    }
    policy_records = [
        (row["available_at"], str(row["observation_date"])) for row in policy_times
    ]
    policy_eligibility = {
        session_code: eligible_record_coverage(decisions, policy_records)
        for session_code, decisions in decision_times.items()
    }

    cme_summary = _scan_cme_normalization(
        cme_normalization,
        start=start,
        end=end,
    )
    event_summary = {
        "event_versions": sum(int(item["versions"]) for item in events_by_code),
        "events": sum(int(item["events"]) for item in events_by_code),
        "forecast_rows": int(forecast_summary["rows"]),
        "forecast_components": int(forecast_summary["components"]),
        "timestamp_pre_release_forecasts": int(
            forecast_summary["timestamp_pre_release_rows"]
        ),
        "pre_event_allowed_forecasts": int(
            forecast_summary["pre_event_allowed_rows"]
        ),
        "release_boundary_forecasts": int(forecast_summary["release_boundary_rows"]),
        "release_rows": int(release_summary["rows"]),
        "release_events": int(release_summary["events"]),
        "release_components": int(release_summary["component_codes"]),
        "previous_value_rows": int(release_summary["previous_value_rows"]),
        "revised_previous_rows": int(release_summary["revised_previous_rows"]),
        "valid_release_availability_rows": int(release_summary["valid_order_rows"]),
    }
    policy_summary = _combine_policy_summary(policy_rows)
    field_registry = build_field_registry(
        session_coverage=session_coverage,
        series_eligibility=series_eligibility,
        price_sources=price_sources,
        cot_reports=cot_reports,
        event_summary=event_summary,
        policy_summary=policy_summary,
        cme_summary=cme_summary,
    )

    gaps = _gaps(
        price_sources=price_sources,
        event_summary=event_summary,
        policy_summary=policy_summary,
        provenance_inconsistencies=provenance_inconsistencies,
    )
    status_counts: dict[str, int] = defaultdict(int)
    for item in field_registry:
        status_counts[item["status"]] += 1

    report: dict[str, Any] = {
        "contract": {
            "version": AUDIT_VERSION,
            "governing_document": "GOLD_CASEBOOK_RESEARCH_CONTRACT.md",
            "milestone": "1_COVERAGE_AUDIT",
            "start": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "locked_holdout": "calendar year 2025",
            "holdout_loaded": False,
            "purpose": (
                "Read-only source, field, session-completeness, and point-in-time "
                "eligibility audit. No directional outcomes or execution results."
            ),
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "session_coverage": session_coverage,
        "source_coverage": {
            "price": price_sources,
            "macro_series": series_sources,
            "events_by_code": events_by_code,
            "forecast_summary": forecast_summary,
            "release_summary": release_summary,
            "release_components": release_components,
            "cot_reports": cot_reports,
            "cot_positions": cot_positions,
            "policy_expectation_windows": policy_rows,
            "cme_intraday": cme_summary,
        },
        "point_in_time_eligibility": {
            "macro_series_by_coverage_probe": series_eligibility,
            "cot_by_coverage_probe": cot_eligibility,
            "policy_expectations_by_coverage_probe": policy_eligibility,
            "event_consensus": {
                "timestamp_appears_pre_release": event_summary[
                    "timestamp_pre_release_forecasts"
                ],
                "verified_for_pre_event_use": event_summary[
                    "pre_event_allowed_forecasts"
                ],
                "post_release_only": event_summary["release_boundary_forecasts"],
                "interpretation": (
                    "Historical MT5 consensus is eligible at the release boundary "
                    "for post-release surprise research, not for pre-event decisions."
                ),
            },
        },
        "field_registry": field_registry,
        "field_status_counts": dict(sorted(status_counts.items())),
        "provenance_inconsistencies": provenance_inconsistencies,
        "gaps": gaps,
        "next_milestone": {
            "code": "2_IMMUTABLE_CASEBOOK",
            "authorized": False,
            "reason": "This run completes and reports milestone 1 only.",
        },
    }
    add_deterministic_hash(report)
    return report


def _scan_cme_normalization(
    path: Path,
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("locked_holdout") != "2025 not loaded":
        raise ValueError("CME normalization manifest does not preserve the 2025 lock")
    symbols: dict[str, dict[str, Any]] = {}
    files: list[dict[str, Any]] = []
    total_rows = 0
    invalid_availability_rows = 0
    rows_before_audit_start = 0
    for item in payload["files"]:
        normalized_path = path.parent / PureWindowsPath(item["normalized"]).name
        expected_hash = item["normalized_sha256"]
        actual_hash = _sha256(normalized_path)
        if actual_hash != expected_hash:
            raise ValueError(f"CME normalized hash mismatch: {normalized_path.name}")
        file_rows = 0
        with gzip.open(normalized_path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                open_time = datetime.fromisoformat(row["open_time"]).astimezone(UTC)
                available_at = datetime.fromisoformat(row["available_at"]).astimezone(UTC)
                if open_time >= end or available_at > end:
                    raise ValueError(
                        f"CME normalized row crosses locked boundary: {open_time.isoformat()}"
                    )
                if available_at < open_time:
                    invalid_availability_rows += 1
                if open_time < start:
                    rows_before_audit_start += 1
                symbol = row["symbol"]
                summary = symbols.setdefault(
                    symbol,
                    {
                        "rows": 0,
                        "first_open": open_time,
                        "last_open": open_time,
                        "volume_rows": 0,
                        "instrument_ids": set(),
                    },
                )
                summary["rows"] += 1
                summary["first_open"] = min(summary["first_open"], open_time)
                summary["last_open"] = max(summary["last_open"], open_time)
                summary["volume_rows"] += int(bool(row["volume"]))
                summary["instrument_ids"].add(row["instrument_id"])
                file_rows += 1
        if file_rows != int(item["rows"]):
            raise ValueError(
                f"CME normalized row-count mismatch: {normalized_path.name}"
            )
        files.append(
            {
                "name": normalized_path.name,
                "rows": file_rows,
                "first_open": item["first_open"],
                "last_open": item["last_open"],
                "sha256": actual_hash,
                "roll_transitions": item["roll_transitions"],
            }
        )
        total_rows += file_rows
    if total_rows != int(payload["total_rows"]):
        raise ValueError("CME normalization total-row mismatch")

    return {
        "manifest": path.name,
        "availability_rule": payload["availability_rule"],
        "locked_holdout": payload["locked_holdout"],
        "total_rows": total_rows,
        "rows_before_audit_start": rows_before_audit_start,
        "invalid_availability_rows": invalid_availability_rows,
        "files": files,
        "symbols": {
            symbol: {
                **summary,
                "first_open": summary["first_open"].isoformat(),
                "last_open": summary["last_open"].isoformat(),
                "instrument_ids": len(summary["instrument_ids"]),
            }
            for symbol, summary in sorted(symbols.items())
        },
    }


def _gaps(
    *,
    price_sources: Sequence[Mapping[str, Any]],
    event_summary: Mapping[str, Any],
    policy_summary: Mapping[str, Any],
    provenance_inconsistencies: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    price_by_instrument = {
        str(item["instrument_code"]): item for item in price_sources
    }
    gaps = [
        {
            "code": "NO_VERIFIED_HISTORICAL_PRE_EVENT_CALENDAR",
            "severity": "MATERIAL",
            "effect": (
                "Upcoming-event risk and historical consensus must be UNKNOWN "
                "before release; release-boundary consensus remains usable afterward."
            ),
        },
        {
            "code": "NO_CENTRALIZED_INTRADAY_GC_VOLUME_OPEN_INTEREST",
            "severity": "LIMITATION",
            "effect": (
                "Broker tick activity and weekly CFTC open interest cannot be "
                "represented as centralized intraday COMEX activity."
            ),
        },
        {
            "code": "NO_LICENSED_UNSCHEDULED_EVENT_HISTORY",
            "severity": "LIMITATION",
            "effect": "Historical unscheduled-event state remains UNKNOWN.",
        },
        {
            "code": "FED_PATH_IS_QUARTERLY_WINDOW",
            "severity": "LIMITATION",
            "effect": (
                f"{policy_summary.get('effective_observations', 0)} Atlanta Fed "
                "observation dates do not equal meeting-level FedWatch history."
            ),
        },
    ]
    us500 = price_by_instrument.get("US500")
    if us500 and str(us500["last_open"]) < "2024-12-01":
        gaps.append(
            {
                "code": "PARTIAL_INTRADAY_US500",
                "severity": "MATERIAL",
                "effect": f"Observed US500 minute history ends at {us500['last_open']}.",
            }
        )
    if event_summary["pre_event_allowed_forecasts"]:
        raise ValueError("Expected historical MT5 forecasts to remain post-release only")
    for item in provenance_inconsistencies:
        if (
            item.get("catalog_synthetic_fixture") == "true"
            and not item.get("any_normalized_synthetic")
        ):
            gaps.append(
                {
                    "code": "CATALOG_PROVENANCE_METADATA_MISMATCH",
                    "severity": "DATA_QUALITY",
                    "effect": (
                        f"{item['series_code']} catalog metadata says synthetic_fixture "
                        "while normalized rows and FRED batches are non-synthetic."
                    ),
                }
            )
    return gaps


def _combine_policy_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "effective_observations": 0}
    return {
        "rows": sum(int(item["rows"]) for item in rows),
        "effective_observations": sum(
            int(item["effective_observations"]) for item in rows
        ),
        "providers": [item["provider_code"] for item in rows],
    }


def _render_markdown(report: Mapping[str, Any]) -> str:
    contract = report["contract"]
    sessions = report["session_coverage"]["counts"]
    sources = report["source_coverage"]
    eligibility = report["point_in_time_eligibility"]
    lines = [
        "# Gold Casebook Coverage Audit",
        "",
        "## Decision",
        "",
        (
            "Milestone 1 is complete for the development interval "
            f"`{contract['start']}` through `{contract['end_exclusive']}`. "
            "This audit loaded no calendar-2025 row and calculated no directional "
            "or execution outcome."
        ),
        "",
        f"Deterministic evidence hash: `{report['data_hash']}`.",
        "",
        "## Session completeness",
        "",
        "| Slice | Weekdays | Asia | London | New York | London cases | New York cases |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for slice_code, item in sessions.items():
        lines.append(
            "| "
            + " | ".join(
                (
                    slice_code,
                    str(item["requested_weekdays"]),
                    str(item["asia_complete"]),
                    str(item["london_complete"]),
                    str(item["new_york_complete"]),
                    str(item["london_case_complete"]),
                    str(item["new_york_case_complete"]),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "A London case requires complete Asia and London windows. A New York "
            "case requires complete Asia, London, and New York windows. Exchange "
            "holidays remain recorded as incomplete weekdays.",
            "",
            "## Observed market sources",
            "",
            "| Instrument | Provider | Rows | First | Last | Spread | Volume | PIT-valid |",
            "|---|---|---:|---|---|---:|---:|---:|",
        ]
    )
    for item in sources["price"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    str(item["instrument_code"]),
                    str(item["provider_code"]),
                    str(item["rows"]),
                    str(item["first_open"]),
                    str(item["last_open"]),
                    str(item["spread_rows"]),
                    str(item["volume_rows"]),
                    str(item["point_in_time_rows"]),
                )
            )
            + " |"
        )
    cme = sources["cme_intraday"]
    lines.extend(
        [
            "",
            (
                f"Databento CME rates contain **{cme['total_rows']:,}** normalized "
                "pre-2025 one-minute rows. File hashes and row counts match the "
                "normalization manifest."
            ),
            "",
            "| CME symbol | Rows | First | Last | Contract IDs |",
            "|---|---:|---|---|---:|",
        ]
    )
    for symbol, item in cme["symbols"].items():
        lines.append(
            f"| {symbol} | {item['rows']} | {item['first_open']} | "
            f"{item['last_open']} | {item['instrument_ids']} |"
        )

    lines.extend(
        [
            "",
            "## Point-in-time fundamental coverage",
            "",
            "| Series | London eligible | New York eligible | Effective London records |",
            "|---|---:|---:|---:|",
        ]
    )
    for code, item in eligibility["macro_series_by_coverage_probe"].items():
        london = item["LONDON"]
        new_york = item["NEW_YORK"]
        lines.append(
            f"| {code} | {london['eligible_pct']}% | "
            f"{new_york['eligible_pct']}% | "
            f"{london['effective_distinct_records']} |"
        )
    cot_london = eligibility["cot_by_coverage_probe"]["LONDON"]
    cot_new_york = eligibility["cot_by_coverage_probe"]["NEW_YORK"]
    policy_london = eligibility["policy_expectations_by_coverage_probe"]["LONDON"]
    event = eligibility["event_consensus"]
    lines.extend(
        [
            "",
            "## Positioning, expectations, and events",
            "",
            (
                f"- COT is eligible for {cot_london['eligible_pct']}% of complete "
                f"London cases and {cot_new_york['eligible_pct']}% of complete "
                f"New York cases. The London cases use "
                f"{cot_london['effective_distinct_records']} distinct published "
                "weekly observations."
            ),
            (
                f"- Atlanta Fed expectation windows are eligible for "
                f"{policy_london['eligible_pct']}% of London coverage probes; they "
                "are quarterly policy distributions, not meeting-level FedWatch."
            ),
            (
                f"- The store has {event['post_release_only']} historical "
                "release-boundary consensus rows and "
                f"{event['verified_for_pre_event_use']} verified pre-event rows. "
                "Consequently historical catalyst schedules and consensus remain "
                "UNKNOWN before release."
            ),
            "",
            "## Field status",
            "",
        ]
    )
    for status, count in report["field_status_counts"].items():
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Material gaps", ""])
    for item in report["gaps"]:
        lines.append(
            f"- **{item['code']}** (`{item['severity']}`): {item['effect']}"
        )
    lines.extend(
        [
            "",
            "These gaps are recorded, not filled or treated as neutral. They do not "
            "prevent materializing price, structure, macro, COT, and post-release "
            "case facts, but they limit pre-event and some cross-market cases.",
            "",
            "## Next contracted step",
            "",
            "Milestone 2 is the immutable casebook and data dictionary. It was not "
            "started by this audit run.",
            "",
            "## Reproduce",
            "",
            "```powershell",
            "docker compose --profile test run --rm `",
            '  -v "${PWD}:/workspace" `',
            "  backend-test python tools/audit_gold_casebook_coverage.py `",
            "  --start 2021-08-01 --end 2025-01-01 `",
            "  --cme-normalization /workspace/data/raw/databento_cme_pre2025/"
            "GLBX-20260728-3SHU3737P8/normalized/normalization.json `",
            "  --json-output /workspace/research_artifacts/"
            "gold_casebook_coverage_v01.json `",
            "  --markdown-output /workspace/GOLD_CASEBOOK_COVERAGE.md",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--cme-normalization", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    return parser


def _parse_date_boundary(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def _row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in row.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    asyncio.run(main())
