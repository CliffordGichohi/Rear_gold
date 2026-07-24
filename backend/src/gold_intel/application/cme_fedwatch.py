from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.application.policy_paths import ingest_policy_path_bundle
from gold_intel.providers.cme_fedwatch import (
    CmeFedWatchPath,
    CmeFedWatchProvider,
    CmeFedWatchSnapshot,
)


@dataclass(frozen=True, slots=True)
class CmeFedWatchSyncResult:
    start: date
    end: date
    fetched_forecast_records: int
    inserted_snapshots: int
    inserted_points: int
    batch_id: UUID
    duplicate_batch: bool
    retrieved_at: datetime


async def sync_cme_fedwatch(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    start: date,
    end: date,
    client_id: str,
    client_secret: str,
    provider: CmeFedWatchProvider | None = None,
) -> CmeFedWatchSyncResult:
    fedwatch_provider = provider or CmeFedWatchProvider(
        client_id=client_id,
        client_secret=client_secret,
    )
    path = await fedwatch_provider.fetch(start=start, end=end)
    payload = cme_fedwatch_bundle(path)
    result = await ingest_policy_path_bundle(
        session,
        payload=payload,
        raw_store_root=raw_store_root,
    )
    return CmeFedWatchSyncResult(
        start=start,
        end=end,
        fetched_forecast_records=path.fetched_forecast_records,
        inserted_snapshots=result.snapshot_count,
        inserted_points=result.point_count,
        batch_id=result.batch.id,
        duplicate_batch=result.duplicate,
        retrieved_at=path.retrieved_at,
    )


def cme_fedwatch_bundle(path: CmeFedWatchPath) -> dict[str, Any]:
    return {
        "provider_code": "CME_FEDWATCH_EOD",
        "dataset_code": "FED_POLICY_PATH",
        "schema_version": "1.0",
        "is_synthetic": False,
        "snapshots": [_snapshot_payload(snapshot, path) for snapshot in path.snapshots],
    }


def _snapshot_payload(
    snapshot: CmeFedWatchSnapshot,
    path: CmeFedWatchPath,
) -> dict[str, Any]:
    return {
        "snapshot_as_of": snapshot.snapshot_as_of,
        "available_at": snapshot.available_at,
        "outcomes": [
            {
                # The integer outcome key is CME's target-range upper bound.
                # expected_rate preserves the exact 12.5bp midpoint.
                "meeting_date": outcome.meeting_date,
                "outcome_basis_points": outcome.upper_basis_points,
                "probability": outcome.probability,
                "expected_rate": outcome.expected_rate,
                "source_record_key": (
                    "CME:"
                    f"{snapshot.reporting_date.isoformat()}:"
                    f"{outcome.meeting_date.isoformat()}:"
                    f"{outcome.lower_basis_points}-{outcome.upper_basis_points}"
                ),
                "metadata": {
                    "lower_bound_basis_points": outcome.lower_basis_points,
                    "upper_bound_basis_points": outcome.upper_basis_points,
                    "outcome_semantics": "TARGET_RANGE_UPPER_BOUND_BASIS_POINTS",
                    "expected_rate_semantics": "TARGET_RANGE_MIDPOINT_PERCENT",
                    "source_payload": outcome.raw_payload,
                },
            }
            for outcome in snapshot.outcomes
        ],
        "metadata": {
            "reporting_date": snapshot.reporting_date.isoformat(),
            "availability_quality": snapshot.availability_quality,
            "official_publication_time": "01:45:00Z",
            "retrieved_at": path.retrieved_at.isoformat(),
            "source": "CME FedWatch End-of-Day API",
            "license_class": "LICENSED_CME_MARKET_DATA_API",
            "point_in_time_contract": (
                "snapshot_as_of and available_at use CME's documented "
                "business-day 01:45 UTC publication clock."
            ),
        },
    }
