from __future__ import annotations

import csv
import hashlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.infrastructure.models import (
    DataQualityIssue,
    IngestionBatch,
    Observation,
    PriceBar,
    RawRecord,
)

PRICE_DATASET = "XAUUSD_1M"
REAL_YIELD_DATASET = "US_REAL_YIELD_10Y_DAILY"
SUPPORTED_DATASETS = {PRICE_DATASET, REAL_YIELD_DATASET}


@dataclass(frozen=True, slots=True)
class IngestionResult:
    batch: IngestionBatch
    duplicate: bool
    valid_records: int
    invalid_records: int
    quality_issue_count: int


async def ingest_csv_path(
    session: AsyncSession,
    *,
    source_path: Path,
    original_filename: str,
    raw_store_root: Path,
    provider_code: str,
    dataset_code: str,
    schema_version: str,
    is_synthetic: bool,
    source_published_at: datetime | None = None,
) -> IngestionResult:
    if dataset_code not in SUPPORTED_DATASETS:
        raise ValueError(f"Unsupported dataset_code: {dataset_code}")

    content_hash = _sha256(source_path)
    existing = await session.scalar(
        select(IngestionBatch).where(
            IngestionBatch.provider_code == provider_code,
            IngestionBatch.dataset_code == dataset_code,
            IngestionBatch.content_hash == content_hash,
        )
    )
    if existing:
        return IngestionResult(
            batch=existing,
            duplicate=True,
            valid_records=existing.record_count,
            invalid_records=0,
            quality_issue_count=0,
        )

    safe_filename = Path(original_filename).name
    destination = (
        raw_store_root / provider_code.lower() / dataset_code.lower() / content_hash / safe_filename
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copyfile(source_path, destination)

    batch = IngestionBatch(
        id=uuid4(),
        provider_code=provider_code,
        dataset_code=dataset_code,
        schema_version=schema_version,
        content_hash=content_hash,
        raw_object_path=str(destination),
        status="PROCESSING",
        record_count=0,
        is_synthetic=is_synthetic,
        source_published_at=source_published_at,
    )
    session.add(batch)
    await session.flush()

    valid = 0
    invalid = 0
    issue_count = 0
    normalized_open_times: list[datetime] = []
    with destination.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row")
        for record_number, row in enumerate(reader, start=1):
            payload = {str(key): value for key, value in row.items()}
            raw_record = RawRecord(
                id=uuid4(),
                batch_id=batch.id,
                record_number=record_number,
                source_record_key=None,
                payload=payload,
                parsed_ok=False,
            )
            session.add(raw_record)
            try:
                model: PriceBar | Observation
                if dataset_code == PRICE_DATASET:
                    model = _parse_price_row(
                        row,
                        batch_id=batch.id,
                        provider_code=provider_code,
                        is_synthetic=is_synthetic,
                    )
                    normalized_open_times.append(model.open_time)
                else:
                    model = _parse_real_yield_row(
                        row,
                        batch_id=batch.id,
                        is_synthetic=is_synthetic,
                    )
                raw_record.source_record_key = model.source_record_key
                raw_record.parsed_ok = True
                session.add(model)
                valid += 1
            except (KeyError, ValueError, InvalidOperation) as exc:
                raw_record.parse_error = str(exc)
                invalid += 1
                issue_count += 1
                session.add(
                    DataQualityIssue(
                        id=uuid4(),
                        batch_id=batch.id,
                        code="INVALID_CSV_RECORD",
                        severity="ERROR",
                        status="OPEN",
                        message=f"Record {record_number} could not be normalized: {exc}",
                        context={"record_number": record_number},
                    )
                )

    if dataset_code == PRICE_DATASET and normalized_open_times:
        missing = _missing_minutes(normalized_open_times)
        if missing:
            issue_count += 1
            session.add(
                DataQualityIssue(
                    id=uuid4(),
                    batch_id=batch.id,
                    code="MISSING_MINUTE_BARS",
                    severity="WARNING",
                    status="OPEN",
                    message=f"Detected {len(missing)} missing one-minute bar(s).",
                    context={
                        "missing_count": len(missing),
                        "first_missing": missing[0].isoformat(),
                        "sample": [item.isoformat() for item in missing[:10]],
                    },
                )
            )

    batch.record_count = valid
    batch.status = "COMPLETED_WITH_ISSUES" if invalid or issue_count else "COMPLETED"
    await session.flush()
    return IngestionResult(
        batch=batch,
        duplicate=False,
        valid_records=valid,
        invalid_records=invalid,
        quality_issue_count=issue_count,
    )


def _parse_price_row(
    row: dict[str, str | None],
    *,
    batch_id: Any,
    provider_code: str,
    is_synthetic: bool,
) -> PriceBar:
    open_time = _timestamp(_required(row, "open_time"))
    close_time = _timestamp(_required(row, "close_time"))
    available_at = _timestamp(_required(row, "available_at"))
    open_price = Decimal(_required(row, "open"))
    high = Decimal(_required(row, "high"))
    low = Decimal(_required(row, "low"))
    close = Decimal(_required(row, "close"))
    if close_time != open_time + timedelta(minutes=1):
        raise ValueError("one-minute bar close_time must be exactly one minute after open_time")
    if available_at < close_time:
        raise ValueError("available_at cannot precede bar close_time")
    if high < max(open_price, close, low) or low > min(open_price, close, high):
        raise ValueError("invalid OHLC geometry")
    volume_raw = row.get("volume")
    volume = Decimal(str(volume_raw)) if volume_raw not in (None, "") else None
    spread_points = _optional_nonnegative_integer(row.get("spread_points"), "spread_points")
    spread_price: Decimal | None = None
    if spread_points is not None:
        if provider_code != "IC_MARKETS_MT5":
            raise ValueError("spread_points require an explicit provider point-size contract")
        # Versioned source contract:
        # IC Markets KE XAUUSD, terminal build 5833, SYMBOL_POINT=0.01.
        spread_price = Decimal(spread_points) * Decimal("0.01")
    key = open_time.isoformat()
    return PriceBar(
        id=uuid4(),
        open_time=open_time,
        close_time=close_time,
        provider_code=provider_code,
        instrument_code="XAUUSD",
        timeframe="1m",
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        volume_type=row.get("volume_type") or "TICK",
        spread_points=spread_points,
        spread_price=spread_price,
        available_at=available_at,
        batch_id=batch_id,
        source_record_key=key,
        is_complete=True,
        is_synthetic=is_synthetic,
    )


def _parse_real_yield_row(
    row: dict[str, str | None], *, batch_id: Any, is_synthetic: bool
) -> Observation:
    observation_time = _timestamp(_required(row, "observation_time"))
    available_at = _timestamp(_required(row, "available_at"))
    if available_at < observation_time:
        raise ValueError("available_at cannot precede observation_time")
    vintage = _required(row, "vintage")
    key = f"US_REAL_YIELD_10Y:{observation_time.isoformat()}:{vintage}"
    return Observation(
        id=uuid4(),
        observation_time=observation_time,
        series_code="US_REAL_YIELD_10Y",
        value=Decimal(_required(row, "value_percent")),
        unit="PERCENT",
        available_at=available_at,
        vintage=vintage,
        is_revision=_boolean(row.get("is_revision", "false")),
        supersedes_id=None,
        batch_id=batch_id,
        source_record_key=key,
        is_synthetic=is_synthetic,
    )


def _required(row: dict[str, str | None], field: str) -> str:
    value = row.get(field)
    if value is None or not value.strip():
        raise ValueError(f"missing required field: {field}")
    return value.strip()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include an explicit timezone")
    return parsed.astimezone(UTC)


def _boolean(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _optional_nonnegative_integer(value: str | None, field: str) -> int | None:
    if value is None or not value.strip():
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{field} cannot be negative")
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _missing_minutes(open_times: list[datetime]) -> list[datetime]:
    ordered = sorted(set(open_times))
    missing: list[datetime] = []
    for prior, current in zip(ordered, ordered[1:], strict=False):
        # The first slice does not yet carry an exchange-session calendar. Ignore
        # obvious daily/weekend closures while still detecting short intraday gaps.
        if current - prior > timedelta(minutes=30):
            continue
        candidate = prior + timedelta(minutes=1)
        while candidate < current:
            missing.append(candidate)
            candidate += timedelta(minutes=1)
    return missing
