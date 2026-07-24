from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.infrastructure.models import (
    CotPosition,
    CotReport,
    IngestionBatch,
    Observation,
    Provider,
    RawRecord,
    Series,
)
from gold_intel.providers.public_data import (
    CFTC_GOLD_CONTRACT_CODE,
    FRED_MARKET_SERIES,
    PublicCotPosition,
    PublicCotReport,
    PublicDataProvider,
    PublicObservation,
)

FRED_PROVIDER = "FRED_PUBLIC"
CFTC_PROVIDER = "CFTC_PUBLIC"
FRED_DATASET = "MARKET_FACTORS_DAILY"
CFTC_DATASET = "GOLD_COT_DISAGG_FUTURES_ONLY"


@dataclass(frozen=True, slots=True)
class PublicSyncResult:
    start: date
    end: date
    fetched_observations: int
    inserted_observations: int
    fetched_cot_reports: int
    inserted_cot_reports: int
    fred_batch_id: UUID
    cftc_batch_id: UUID
    fred_duplicate_batch: bool
    cftc_duplicate_batch: bool


async def sync_public_data(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    start: date,
    end: date,
    provider: PublicDataProvider | None = None,
) -> PublicSyncResult:
    if start >= end:
        raise ValueError("start must precede end")
    if (end - start).days > 3650:
        raise ValueError("one public sync is limited to ten years")

    adapter = provider or PublicDataProvider()
    bundle = await adapter.fetch(start=start, end=end)
    await _ensure_catalog(session)
    fred_batch, fred_duplicate, inserted_observations = await _persist_observations(
        session,
        raw_store_root=raw_store_root,
        records=bundle.observations,
        start=start,
        end=end,
    )
    cftc_batch, cftc_duplicate, inserted_cot = await _persist_cot(
        session,
        raw_store_root=raw_store_root,
        records=bundle.cot_reports,
        start=start,
        end=end,
    )
    return PublicSyncResult(
        start=start,
        end=end,
        fetched_observations=len(bundle.observations),
        inserted_observations=inserted_observations,
        fetched_cot_reports=len(bundle.cot_reports),
        inserted_cot_reports=inserted_cot,
        fred_batch_id=fred_batch.id,
        cftc_batch_id=cftc_batch.id,
        fred_duplicate_batch=fred_duplicate,
        cftc_duplicate_batch=cftc_duplicate,
    )


async def _ensure_catalog(session: AsyncSession) -> None:
    providers = (
        Provider(
            code=FRED_PROVIDER,
            name="Federal Reserve Economic Data",
            provider_type="PUBLIC_OFFICIAL_AGGREGATOR",
            license_class="PUBLIC",
            enabled=True,
            metadata_json={
                "scope": "market-derived daily series only",
                "vintage_policy": "Do not use this adapter for revisable macro releases.",
            },
        ),
        Provider(
            code=CFTC_PROVIDER,
            name="Commodity Futures Trading Commission",
            provider_type="PUBLIC_OFFICIAL",
            license_class="PUBLIC",
            enabled=True,
            metadata_json={
                "dataset": "Disaggregated Futures Only",
                "contract_market_code": CFTC_GOLD_CONTRACT_CODE,
            },
        ),
        Provider(
            code="IC_MARKETS_MT5",
            name="IC Markets MetaTrader 5",
            provider_type="BROKER",
            license_class="ACCOUNT_ACCESS",
            enabled=True,
            metadata_json={"bridge_policy": "READ_ONLY"},
        ),
    )
    for model in providers:
        if await session.get(Provider, model.code) is None:
            session.add(model)

    for spec in FRED_MARKET_SERIES:
        existing = await session.get(Series, spec.internal_code)
        if existing is None:
            session.add(
                Series(
                    code=spec.internal_code,
                    name=spec.name,
                    unit=spec.unit,
                    frequency=spec.frequency,
                    expected_lag_seconds=spec.expected_lag_seconds,
                    metadata_json={
                        "external_code": spec.external_code,
                        "provider": FRED_PROVIDER,
                        "availability_policy": "NEXT_CALENDAR_DAY_00_ET",
                    },
                )
            )
        else:
            existing.name = spec.name
            existing.unit = spec.unit
            existing.frequency = spec.frequency
            existing.expected_lag_seconds = spec.expected_lag_seconds
            existing.metadata_json = {
                **existing.metadata_json,
                "external_code": spec.external_code,
                "provider": FRED_PROVIDER,
                "availability_policy": "NEXT_CALENDAR_DAY_00_ET",
            }
    await session.flush()


async def _persist_observations(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    records: tuple[PublicObservation, ...],
    start: date,
    end: date,
) -> tuple[IngestionBatch, bool, int]:
    payload = [_jsonable(asdict(record)) for record in records]
    batch, duplicate = await _batch(
        session,
        raw_store_root=raw_store_root,
        provider_code=FRED_PROVIDER,
        dataset_code=FRED_DATASET,
        start=start,
        end=end,
        payload=payload,
    )
    if duplicate:
        return batch, True, 0

    existing_keys = {
        tuple(row)
        for row in (
            await session.execute(
                select(
                    Observation.series_code,
                    Observation.observation_time,
                    Observation.available_at,
                    Observation.vintage,
                ).where(
                    Observation.series_code.in_([spec.internal_code for spec in FRED_MARKET_SERIES])
                )
            )
        ).all()
    }
    inserted = 0
    for number, record in enumerate(records, start=1):
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
        session.add(
            Observation(
                id=uuid4(),
                observation_time=record.observation_time,
                series_code=record.series_code,
                value=record.value,
                unit=record.unit,
                available_at=record.available_at,
                vintage=record.vintage,
                is_revision=False,
                supersedes_id=None,
                batch_id=batch.id,
                source_record_key=record.source_record_key,
                is_synthetic=False,
            )
        )
        existing_keys.add(key)
        inserted += 1
    batch.record_count = inserted
    batch.status = "COMPLETED"
    await session.flush()
    return batch, False, inserted


async def _persist_cot(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    records: tuple[PublicCotReport, ...],
    start: date,
    end: date,
) -> tuple[IngestionBatch, bool, int]:
    payload = [_jsonable(asdict(record)) for record in records]
    batch, duplicate = await _batch(
        session,
        raw_store_root=raw_store_root,
        provider_code=CFTC_PROVIDER,
        dataset_code=CFTC_DATASET,
        start=start,
        end=end,
        payload=payload,
    )
    if duplicate:
        return batch, True, 0

    existing_keys = {
        tuple(row)
        for row in (
            await session.execute(
                select(
                    CotReport.report_type,
                    CotReport.contract_market_code,
                    CotReport.observation_date,
                    CotReport.publication_at,
                ).where(
                    CotReport.provider_code == CFTC_PROVIDER,
                    CotReport.contract_market_code == CFTC_GOLD_CONTRACT_CODE,
                )
            )
        ).all()
    }
    inserted = 0
    pending_positions: list[tuple[CotReport, tuple[PublicCotPosition, ...]]] = []
    for number, record in enumerate(records, start=1):
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
            "DISAGGREGATED_FUTURES_ONLY",
            CFTC_GOLD_CONTRACT_CODE,
            record.observation_date,
            record.publication_at,
        )
        if key in existing_keys:
            continue
        report = CotReport(
            id=uuid4(),
            provider_code=CFTC_PROVIDER,
            report_type="DISAGGREGATED_FUTURES_ONLY",
            contract_market_code=CFTC_GOLD_CONTRACT_CODE,
            market_name=record.market_name,
            observation_date=record.observation_date,
            publication_at=record.publication_at,
            open_interest=record.open_interest,
            source_record_key=record.source_record_key,
            availability_quality=record.availability_quality,
            batch_id=batch.id,
            metadata_json={
                "observation_day": "TUESDAY",
                "publication_timezone": "America/New_York",
            },
        )
        session.add(report)
        pending_positions.append((report, record.positions))
        existing_keys.add(key)
        inserted += 1

    # Flush parent reports before their position rows. These models use explicit
    # UUID foreign keys rather than ORM relationships, so making the dependency
    # boundary explicit keeps insert ordering deterministic across dialects.
    batch.record_count = inserted
    batch.status = "COMPLETED"
    await session.flush()
    for report, positions in pending_positions:
        for position in positions:
            session.add(
                CotPosition(
                    id=uuid4(),
                    report_id=report.id,
                    category=position.category,
                    long_contracts=position.long_contracts,
                    short_contracts=position.short_contracts,
                    spreading_contracts=position.spreading_contracts,
                    percent_open_interest_long=position.percent_open_interest_long,
                    percent_open_interest_short=position.percent_open_interest_short,
                    traders_long=position.traders_long,
                    traders_short=position.traders_short,
                    metadata_json={},
                )
            )
    await session.flush()
    return batch, False, inserted


async def _batch(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    provider_code: str,
    dataset_code: str,
    start: date,
    end: date,
    payload: list[dict[str, Any]],
) -> tuple[IngestionBatch, bool]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = await session.scalar(
        select(IngestionBatch).where(
            IngestionBatch.provider_code == provider_code,
            IngestionBatch.dataset_code == dataset_code,
            IngestionBatch.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing, True

    destination = (
        raw_store_root
        / provider_code.lower()
        / dataset_code.lower()
        / content_hash
        / f"{start.isoformat()}_{end.isoformat()}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical, encoding="utf-8")
    batch = IngestionBatch(
        id=uuid4(),
        provider_code=provider_code,
        dataset_code=dataset_code,
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
    return batch, False


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value
