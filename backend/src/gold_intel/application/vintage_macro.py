from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.infrastructure.models import (
    IngestionBatch,
    Observation,
    Provider,
    RawRecord,
    Series,
)
from gold_intel.providers.alfred import (
    ALFRED_MACRO_SERIES,
    AlfredVintageProvider,
    VintageObservation,
)

ALFRED_PROVIDER = "ALFRED_OFFICIAL"
ALFRED_DATASET = "US_MACRO_VINTAGES"


@dataclass(frozen=True, slots=True)
class VintageMacroSyncResult:
    start: date
    end: date
    fetched_observations: int
    inserted_observations: int
    batch_id: UUID
    duplicate_batch: bool


async def sync_vintage_macro(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    start: date,
    end: date,
    api_key: str,
    provider: AlfredVintageProvider | None = None,
) -> VintageMacroSyncResult:
    if start >= end:
        raise ValueError("start must precede end")
    if (end - start).days > 3650:
        raise ValueError("one vintage sync is limited to ten years")
    adapter = provider or AlfredVintageProvider(api_key=api_key)
    records = await adapter.fetch(start=start, end=end)
    await _ensure_catalog(session)
    batch, duplicate, inserted = await _persist_vintages(
        session,
        raw_store_root=raw_store_root,
        records=records,
        start=start,
        end=end,
    )
    return VintageMacroSyncResult(
        start=start,
        end=end,
        fetched_observations=len(records),
        inserted_observations=inserted,
        batch_id=batch.id,
        duplicate_batch=duplicate,
    )


async def _ensure_catalog(session: AsyncSession) -> None:
    if await session.get(Provider, ALFRED_PROVIDER) is None:
        session.add(
            Provider(
                code=ALFRED_PROVIDER,
                name="ALFRED, Federal Reserve Bank of St. Louis",
                provider_type="PUBLIC_OFFICIAL_VINTAGE_AGGREGATOR",
                license_class="PUBLIC_API_KEY",
                enabled=True,
                metadata_json={
                    "endpoint": "fred/series/observations",
                    "output_type": 1,
                    "availability_policy": ("ALFRED real-time date plus one day at 00:00 ET"),
                    "intraday_warning": (
                        "ALFRED dates are not treated as exact release timestamps."
                    ),
                },
            )
        )
    for specification in ALFRED_MACRO_SERIES:
        existing = await session.get(Series, specification.internal_code)
        metadata = {
            "external_code": specification.external_code,
            "provider": ALFRED_PROVIDER,
            "family": specification.family,
            "vintage_aware": True,
            "availability_policy": "ALFRED_REALTIME_DATE_PLUS_1_AT_00_ET",
        }
        if existing is None:
            session.add(
                Series(
                    code=specification.internal_code,
                    name=specification.name,
                    unit=specification.unit,
                    frequency=specification.frequency,
                    expected_lag_seconds=specification.expected_lag_seconds,
                    metadata_json=metadata,
                )
            )
        else:
            existing.name = specification.name
            existing.unit = specification.unit
            existing.frequency = specification.frequency
            existing.expected_lag_seconds = specification.expected_lag_seconds
            existing.metadata_json = {**existing.metadata_json, **metadata}
    await session.flush()


async def _persist_vintages(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    records: tuple[VintageObservation, ...],
    start: date,
    end: date,
) -> tuple[IngestionBatch, bool, int]:
    payload = [_jsonable(asdict(record)) for record in records]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    existing_batch = await session.scalar(
        select(IngestionBatch).where(
            IngestionBatch.provider_code == ALFRED_PROVIDER,
            IngestionBatch.dataset_code == ALFRED_DATASET,
            IngestionBatch.content_hash == content_hash,
        )
    )
    if existing_batch is not None:
        return existing_batch, True, 0

    destination = (
        raw_store_root
        / ALFRED_PROVIDER.lower()
        / ALFRED_DATASET.lower()
        / content_hash
        / f"{start.isoformat()}_{end.isoformat()}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical + "\n", encoding="utf-8")
    batch = IngestionBatch(
        id=uuid4(),
        provider_code=ALFRED_PROVIDER,
        dataset_code=ALFRED_DATASET,
        schema_version="1",
        content_hash=content_hash,
        raw_object_path=str(destination),
        status="PROCESSING",
        record_count=0,
        is_synthetic=False,
        source_published_at=None,
    )
    session.add(batch)
    await session.flush()

    series_codes = [specification.internal_code for specification in ALFRED_MACRO_SERIES]
    existing_rows = list(
        (
            await session.scalars(
                select(Observation)
                .where(Observation.series_code.in_(series_codes))
                .order_by(
                    Observation.series_code,
                    Observation.observation_time,
                    Observation.available_at,
                )
            )
        ).all()
    )
    existing_keys = {
        (
            row.series_code,
            row.observation_time,
            row.available_at,
            row.vintage,
        )
        for row in existing_rows
    }
    versions_by_period: dict[
        tuple[str, datetime],
        list[Observation],
    ] = {}
    for row in existing_rows:
        versions_by_period.setdefault(
            (row.series_code, row.observation_time),
            [],
        ).append(row)

    inserted = 0
    ordered = sorted(
        records,
        key=lambda record: (
            record.series_code,
            record.observation_time,
            record.available_at,
        ),
    )
    for number, record in enumerate(ordered, start=1):
        session.add(
            RawRecord(
                id=uuid4(),
                batch_id=batch.id,
                record_number=number,
                source_record_key=record.source_record_key,
                payload=record.payload,
                parsed_ok=True,
            )
        )
        key = (
            record.series_code,
            record.observation_time,
            record.available_at,
            record.vintage,
        )
        if key in existing_keys:
            continue
        period_key = (record.series_code, record.observation_time)
        prior_versions = [
            version
            for version in versions_by_period.get(period_key, [])
            if version.available_at < record.available_at
        ]
        predecessor = prior_versions[-1] if prior_versions else None
        model = Observation(
            id=uuid4(),
            observation_time=record.observation_time,
            series_code=record.series_code,
            value=record.value,
            unit=record.unit,
            available_at=record.available_at,
            vintage=record.vintage,
            is_revision=record.is_revision or predecessor is not None,
            supersedes_id=predecessor.id if predecessor is not None else None,
            batch_id=batch.id,
            source_record_key=record.source_record_key,
            is_synthetic=False,
        )
        session.add(model)
        versions_by_period.setdefault(period_key, []).append(model)
        existing_keys.add(key)
        inserted += 1
    batch.record_count = inserted
    batch.status = "COMPLETED"
    await session.flush()
    return batch, False, inserted


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if value.__class__.__name__ == "Decimal" else value
