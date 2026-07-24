from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.infrastructure.models import (
    IngestionBatch,
    PolicyExpectationWindow,
    Provider,
    RawRecord,
)
from gold_intel.providers.atlanta_fed_mpt import (
    ATLANTA_FED_MPT_DATASET_CODE,
    ATLANTA_FED_MPT_PROVIDER_CODE,
    AtlantaFedMptDataset,
    AtlantaFedMptProvider,
    AtlantaFedMptWindow,
)


@dataclass(frozen=True, slots=True)
class AtlantaFedMptSyncResult:
    earliest_observation_date: date
    latest_observation_date: date
    fetched_observation_dates: int
    fetched_windows: int
    inserted_windows: int
    batch_id: UUID
    duplicate_batch: bool
    retrieved_at: datetime
    source_sha256: str
    license_class: str
    availability_quality: str


async def sync_atlanta_fed_mpt(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    provider: AtlantaFedMptProvider | None = None,
) -> AtlantaFedMptSyncResult:
    dataset = await (provider or AtlantaFedMptProvider()).fetch()
    batch, duplicate, inserted_windows = await ingest_atlanta_fed_mpt_dataset(
        session,
        dataset=dataset,
        raw_store_root=raw_store_root,
    )
    return AtlantaFedMptSyncResult(
        earliest_observation_date=dataset.earliest_observation_date,
        latest_observation_date=dataset.latest_observation_date,
        fetched_observation_dates=dataset.observation_count,
        fetched_windows=len(dataset.windows),
        inserted_windows=inserted_windows,
        batch_id=batch.id,
        duplicate_batch=duplicate,
        retrieved_at=dataset.retrieved_at,
        source_sha256=dataset.source_sha256,
        license_class=dataset.license_class,
        availability_quality=dataset.availability_quality,
    )


async def ingest_atlanta_fed_mpt_dataset(
    session: AsyncSession,
    *,
    dataset: AtlantaFedMptDataset,
    raw_store_root: Path,
) -> tuple[IngestionBatch, bool, int]:
    existing_batch = await session.scalar(
        select(IngestionBatch).where(
            IngestionBatch.provider_code == ATLANTA_FED_MPT_PROVIDER_CODE,
            IngestionBatch.dataset_code == ATLANTA_FED_MPT_DATASET_CODE,
            IngestionBatch.content_hash == dataset.source_sha256,
        )
    )
    if existing_batch is not None:
        return existing_batch, True, 0

    if await session.get(Provider, ATLANTA_FED_MPT_PROVIDER_CODE) is None:
        session.add(
            Provider(
                code=ATLANTA_FED_MPT_PROVIDER_CODE,
                name="Federal Reserve Bank of Atlanta Market Probability Tracker",
                provider_type="OFFICIAL_PUBLIC_DOWNLOAD",
                license_class=dataset.license_class,
                enabled=True,
                metadata_json={
                    "source_url": dataset.source_url,
                    "data_semantics": (
                        "CME SOFR-options-implied distributions for future "
                        "three-month average SOFR reference windows."
                    ),
                    "not_equivalent_to": "EXACT_FOMC_MEETING_FEDWATCH_PROBABILITIES",
                    "permitted_use": "PERSONAL_AND_EDUCATIONAL_ONLY",
                    "commercial_use": "SEPARATE_PERMISSION_OR_LICENSE_REQUIRED",
                },
            )
        )
        await session.flush()

    destination = (
        raw_store_root
        / ATLANTA_FED_MPT_PROVIDER_CODE.lower()
        / ATLANTA_FED_MPT_DATASET_CODE.lower()
        / dataset.source_sha256
        / "mpt_histdata.xlsx"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(dataset.workbook_bytes)

    batch = IngestionBatch(
        id=uuid4(),
        provider_code=ATLANTA_FED_MPT_PROVIDER_CODE,
        dataset_code=ATLANTA_FED_MPT_DATASET_CODE,
        schema_version="1.0",
        content_hash=dataset.source_sha256,
        raw_object_path=str(destination),
        status="PROCESSING",
        record_count=0,
        is_synthetic=False,
        source_published_at=None,
    )
    session.add(batch)
    await session.flush()

    existing_rows = (
        await session.execute(
            select(
                PolicyExpectationWindow.observation_date,
                PolicyExpectationWindow.reference_start,
                PolicyExpectationWindow.available_at,
            ).where(PolicyExpectationWindow.provider_code == ATLANTA_FED_MPT_PROVIDER_CODE)
        )
    ).all()
    existing_keys: set[tuple[date, date, datetime]] = {
        (row[0], row[1], row[2]) for row in existing_rows
    }
    raw_rows: list[RawRecord] = []
    normalized_rows: list[PolicyExpectationWindow] = []
    for record_number, window in enumerate(dataset.windows, start=1):
        payload = _window_payload(window, dataset)
        raw_rows.append(
            RawRecord(
                id=uuid4(),
                batch_id=batch.id,
                record_number=record_number,
                source_record_key=window.source_record_key,
                payload=payload,
                parsed_ok=True,
            )
        )
        key = (
            window.observation_date,
            window.reference_start,
            window.available_at,
        )
        if key in existing_keys:
            continue
        existing_keys.add(key)
        normalized_rows.append(
            PolicyExpectationWindow(
                id=uuid4(),
                provider_code=ATLANTA_FED_MPT_PROVIDER_CODE,
                observation_date=window.observation_date,
                snapshot_as_of=window.snapshot_as_of,
                reference_start=window.reference_start,
                reference_end=window.reference_end,
                target_lower_basis_points=window.target_lower_basis_points,
                target_upper_basis_points=window.target_upper_basis_points,
                rate_p25_basis_points=_decimal(window.rate_p25_basis_points),
                rate_mean_basis_points=_decimal(window.rate_mean_basis_points),
                rate_mode_basis_points=_decimal(window.rate_mode_basis_points),
                rate_p75_basis_points=_decimal(window.rate_p75_basis_points),
                probability_cut=_optional_decimal(window.probability_cut),
                probability_hike=_optional_decimal(window.probability_hike),
                probability_bins=[
                    {
                        "lower_basis_points": item.lower_basis_points,
                        "upper_basis_points": item.upper_basis_points,
                        "probability": item.probability,
                    }
                    for item in window.probability_bins
                ],
                distribution_probability_sum=_optional_decimal(window.distribution_probability_sum),
                available_at=window.available_at,
                availability_quality=dataset.availability_quality,
                source_record_key=window.source_record_key,
                batch_id=batch.id,
                is_synthetic=False,
                metadata_json={
                    "source_url": dataset.source_url,
                    "source_sha256": dataset.source_sha256,
                    "source_etag": dataset.source_etag,
                    "source_last_modified": dataset.source_last_modified,
                    "retrieved_at": dataset.retrieved_at.isoformat(),
                    "license_class": dataset.license_class,
                    "epistemic_status": "CALCULATED",
                    "market_input": "OBSERVED_CME_SOFR_OPTION_PRICES_USED_BY_ATLANTA_FED",
                    "horizon_semantics": "THREE_MONTH_AVERAGE_SOFR_REFERENCE_WINDOW",
                    "exact_fomc_meeting_probability": False,
                    "availability_policy": (
                        "Observation-date data becomes eligible only at the end "
                        "of the next US federal business day because the official "
                        "download provides dates but no historical publication times."
                    ),
                },
            )
        )
    session.add_all(raw_rows)
    session.add_all(normalized_rows)
    batch.record_count = len(dataset.windows)
    batch.status = "COMPLETED"
    await session.flush()
    return batch, False, len(normalized_rows)


def policy_expectation_window_to_dict(
    window: PolicyExpectationWindow,
) -> dict[str, Any]:
    return {
        "provider_code": window.provider_code,
        "observation_date": window.observation_date,
        "snapshot_as_of": window.snapshot_as_of,
        "available_at": window.available_at,
        "availability_quality": window.availability_quality,
        "reference_start": window.reference_start,
        "reference_end": window.reference_end,
        "target_range_basis_points": [
            window.target_lower_basis_points,
            window.target_upper_basis_points,
        ],
        "rate_distribution_basis_points": {
            "p25": float(window.rate_p25_basis_points),
            "mean": float(window.rate_mean_basis_points),
            "mode": float(window.rate_mode_basis_points),
            "p75": float(window.rate_p75_basis_points),
        },
        "probability_cut": (
            float(window.probability_cut) if window.probability_cut is not None else None
        ),
        "probability_hike": (
            float(window.probability_hike) if window.probability_hike is not None else None
        ),
        "probability_bins": window.probability_bins,
        "distribution_probability_sum": (
            float(window.distribution_probability_sum)
            if window.distribution_probability_sum is not None
            else None
        ),
        "source_record_key": window.source_record_key,
        "is_synthetic": window.is_synthetic,
        "semantics": "QUARTERLY_AVERAGE_SOFR_DISTRIBUTION",
        "is_exact_fomc_meeting_probability": False,
    }


def _window_payload(
    window: AtlantaFedMptWindow,
    dataset: AtlantaFedMptDataset,
) -> dict[str, Any]:
    payload = asdict(window)
    payload.update(
        {
            "source_url": dataset.source_url,
            "source_sha256": dataset.source_sha256,
            "retrieved_at": dataset.retrieved_at,
            "license_class": dataset.license_class,
            "availability_quality": dataset.availability_quality,
        }
    )
    return {str(key): _jsonable(value) for key, value in payload.items()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: float | None) -> Decimal | None:
    return None if value is None else _decimal(value)
