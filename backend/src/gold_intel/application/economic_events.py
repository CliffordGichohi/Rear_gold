from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.events import (
    SURPRISE_RULESET_VERSION,
    EventReleaseFact,
    ForecastFact,
    SurpriseBatch,
    calculate_economic_surprises,
)
from gold_intel.infrastructure.models import (
    EconomicEvent,
    EconomicRelease,
    EconomicSurprise,
    ForecastSnapshot,
    IngestionBatch,
    Provider,
    RawRecord,
)


@dataclass(frozen=True, slots=True)
class SurprisePersistenceResult:
    batch: SurpriseBatch
    models: tuple[EconomicSurprise, ...]
    inserted_count: int
    data_mode: str


@dataclass(frozen=True, slots=True)
class EventBundleIngestionResult:
    batch: IngestionBatch
    duplicate: bool
    event_count: int
    forecast_count: int
    release_count: int
    surprise_result: SurprisePersistenceResult


async def ingest_economic_event_bundle(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    raw_store_root: Path,
) -> EventBundleIngestionResult:
    """Persist a validated event bundle without mutating prior source facts."""

    provider_code = str(payload["provider_code"])
    dataset_code = str(payload["dataset_code"])
    schema_version = str(payload["schema_version"])
    is_synthetic = bool(payload["is_synthetic"])
    canonical_payload = _canonical_json(payload)
    content_hash = hashlib.sha256(canonical_payload.encode()).hexdigest()
    existing_batch = await session.scalar(
        select(IngestionBatch).where(
            IngestionBatch.provider_code == provider_code,
            IngestionBatch.dataset_code == dataset_code,
            IngestionBatch.content_hash == content_hash,
        )
    )
    data_mode = "SYNTHETIC_ONLY" if is_synthetic else "REAL_ONLY"
    if existing_batch is not None:
        surprise_result = await calculate_and_store_economic_surprises(
            session,
            as_of=datetime.now(UTC),
            data_mode=data_mode,
        )
        return EventBundleIngestionResult(
            batch=existing_batch,
            duplicate=True,
            event_count=0,
            forecast_count=0,
            release_count=0,
            surprise_result=surprise_result,
        )

    await _ensure_provider(
        session,
        code=provider_code,
        name=f"{provider_code} economic-event source",
        provider_type="MANUAL_OR_LICENSED_EVENT_FEED",
    )
    forecast_provider_codes = {
        str(forecast["provider_code"])
        for event in payload["events"]
        for forecast in event["forecasts"]
    }
    for forecast_provider in sorted(forecast_provider_codes):
        await _ensure_provider(
            session,
            code=forecast_provider,
            name=f"{forecast_provider} consensus source",
            provider_type="MANUAL_OR_LICENSED_FORECAST_FEED",
        )

    destination = (
        raw_store_root / provider_code.lower() / dataset_code.lower() / content_hash / "bundle.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_text(canonical_payload + "\n", encoding="utf-8")

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
        source_published_at=payload.get("source_published_at"),
    )
    session.add(batch)
    await session.flush()

    inserted_events = 0
    inserted_forecasts = 0
    inserted_releases = 0
    for record_number, event_payload in enumerate(payload["events"], start=1):
        session.add(
            RawRecord(
                id=uuid4(),
                batch_id=batch.id,
                record_number=record_number,
                source_record_key=str(event_payload["source_event_key"]),
                payload=_jsonable(event_payload),
                parsed_ok=True,
            )
        )
        event = await session.scalar(
            select(EconomicEvent).where(
                EconomicEvent.provider_code == provider_code,
                EconomicEvent.source_event_key == event_payload["source_event_key"],
                EconomicEvent.available_at == event_payload["available_at"],
            )
        )
        if event is None:
            event = EconomicEvent(
                id=uuid4(),
                event_code=event_payload["event_code"],
                name=event_payload["name"],
                event_type=event_payload["event_type"],
                scheduled_at=event_payload["scheduled_at"],
                released_at=event_payload.get("released_at"),
                importance=event_payload["importance"],
                is_scheduled=event_payload["is_scheduled"],
                status=event_payload["status"],
                provider_code=provider_code,
                source_event_key=event_payload["source_event_key"],
                available_at=event_payload["available_at"],
                batch_id=batch.id,
                is_synthetic=is_synthetic,
                metadata_json=event_payload["metadata"],
            )
            session.add(event)
            await session.flush()
            inserted_events += 1

        for forecast_payload in event_payload["forecasts"]:
            existing_forecast = await session.scalar(
                select(ForecastSnapshot).where(
                    ForecastSnapshot.event_code == event_payload["event_code"],
                    ForecastSnapshot.scheduled_at == event_payload["scheduled_at"],
                    ForecastSnapshot.component_code == forecast_payload["component_code"],
                    ForecastSnapshot.provider_code == forecast_payload["provider_code"],
                    ForecastSnapshot.available_at == forecast_payload["available_at"],
                    ForecastSnapshot.vintage == forecast_payload["vintage"],
                )
            )
            if existing_forecast is not None:
                continue
            session.add(
                ForecastSnapshot(
                    id=uuid4(),
                    event_code=event_payload["event_code"],
                    scheduled_at=event_payload["scheduled_at"],
                    component_code=forecast_payload["component_code"],
                    forecast_value=_decimal(forecast_payload["forecast_value"]),
                    unit=forecast_payload["unit"],
                    forecast_as_of=forecast_payload["forecast_as_of"],
                    available_at=forecast_payload["available_at"],
                    provider_code=forecast_payload["provider_code"],
                    vintage=forecast_payload["vintage"],
                    batch_id=batch.id,
                    is_synthetic=is_synthetic,
                    metadata_json=forecast_payload["metadata"],
                )
            )
            inserted_forecasts += 1

        for release_payload in event_payload["releases"]:
            existing_release = await session.scalar(
                select(EconomicRelease).where(
                    EconomicRelease.event_id == event.id,
                    EconomicRelease.component_code == release_payload["component_code"],
                    EconomicRelease.available_at == release_payload["available_at"],
                    EconomicRelease.vintage == release_payload["vintage"],
                )
            )
            if existing_release is not None:
                continue
            session.add(
                EconomicRelease(
                    id=uuid4(),
                    event_id=event.id,
                    component_code=release_payload["component_code"],
                    observation_period=release_payload["observation_period"],
                    actual_value=_decimal(release_payload["actual_value"]),
                    previous_value=_optional_decimal(release_payload.get("previous_value")),
                    revised_previous_value=_optional_decimal(
                        release_payload.get("revised_previous_value")
                    ),
                    unit=release_payload["unit"],
                    released_at=release_payload["released_at"],
                    available_at=release_payload["available_at"],
                    is_revision=release_payload["is_revision"],
                    vintage=release_payload["vintage"],
                    batch_id=batch.id,
                    is_synthetic=is_synthetic,
                    metadata_json=release_payload["metadata"],
                )
            )
            inserted_releases += 1

    batch.record_count = len(payload["events"])
    batch.status = "COMPLETED"
    await session.flush()
    surprise_result = await calculate_and_store_economic_surprises(
        session,
        as_of=datetime.now(UTC),
        data_mode=data_mode,
    )
    return EventBundleIngestionResult(
        batch=batch,
        duplicate=False,
        event_count=inserted_events,
        forecast_count=inserted_forecasts,
        release_count=inserted_releases,
        surprise_result=surprise_result,
    )


async def calculate_and_store_economic_surprises(
    session: AsyncSession,
    *,
    as_of: datetime,
    data_mode: str = "REAL_ONLY",
) -> SurprisePersistenceResult:
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    if data_mode not in {"REAL_ONLY", "SYNTHETIC_ONLY"}:
        raise ValueError("data_mode must be REAL_ONLY or SYNTHETIC_ONLY")
    cutoff = as_of.astimezone(UTC)
    synthetic = data_mode == "SYNTHETIC_ONLY"

    release_rows = list(
        (
            await session.execute(
                select(EconomicEvent, EconomicRelease)
                .join(EconomicRelease, EconomicRelease.event_id == EconomicEvent.id)
                .where(
                    EconomicEvent.available_at <= cutoff,
                    EconomicRelease.available_at <= cutoff,
                    EconomicEvent.is_synthetic.is_(synthetic),
                    EconomicRelease.is_synthetic.is_(synthetic),
                )
                .order_by(
                    EconomicRelease.released_at,
                    EconomicRelease.available_at,
                )
            )
        ).all()
    )
    forecast_rows = list(
        (
            await session.scalars(
                select(ForecastSnapshot)
                .where(
                    ForecastSnapshot.available_at <= cutoff,
                    ForecastSnapshot.is_synthetic.is_(synthetic),
                )
                .order_by(
                    ForecastSnapshot.scheduled_at,
                    ForecastSnapshot.component_code,
                    ForecastSnapshot.available_at,
                )
            )
        ).all()
    )
    releases = [
        EventReleaseFact(
            event_id=event.id,
            release_id=release.id,
            event_code=event.event_code,
            event_name=event.name,
            scheduled_at=event.scheduled_at,
            importance=event.importance,
            component_code=release.component_code,
            observation_period=release.observation_period,
            actual_value=float(release.actual_value),
            previous_value=(
                float(release.previous_value) if release.previous_value is not None else None
            ),
            revised_previous_value=(
                float(release.revised_previous_value)
                if release.revised_previous_value is not None
                else None
            ),
            unit=release.unit,
            released_at=release.released_at,
            available_at=release.available_at,
            is_revision=release.is_revision,
            vintage=release.vintage,
            is_synthetic=event.is_synthetic or release.is_synthetic,
        )
        for event, release in release_rows
    ]
    forecasts = [
        ForecastFact(
            forecast_id=forecast.id,
            event_code=forecast.event_code,
            scheduled_at=forecast.scheduled_at,
            component_code=forecast.component_code,
            forecast_value=float(forecast.forecast_value),
            unit=forecast.unit,
            forecast_as_of=forecast.forecast_as_of,
            available_at=forecast.available_at,
            provider_code=forecast.provider_code,
            vintage=forecast.vintage,
            is_synthetic=forecast.is_synthetic,
        )
        for forecast in forecast_rows
    ]
    calculations = calculate_economic_surprises(
        releases,
        forecasts,
        as_of=cutoff,
        include_synthetic=synthetic,
    )

    stored: list[EconomicSurprise] = []
    inserted = 0
    for calculation in calculations.calculations:
        existing = await session.scalar(
            select(EconomicSurprise).where(
                EconomicSurprise.release_id == calculation.release_id,
                EconomicSurprise.forecast_id == calculation.forecast_id,
                EconomicSurprise.ruleset_version == SURPRISE_RULESET_VERSION,
                EconomicSurprise.data_hash == calculation.data_hash,
            )
        )
        if existing is not None:
            stored.append(existing)
            continue
        model = EconomicSurprise(
            id=uuid4(),
            event_id=calculation.event_id,
            release_id=calculation.release_id,
            forecast_id=calculation.forecast_id,
            component_code=calculation.component_code,
            released_at=calculation.released_at,
            available_at=calculation.available_at,
            raw_surprise=_decimal(calculation.raw_surprise),
            standardized_surprise=_decimal(calculation.standardized_surprise),
            gold_direction=_decimal(calculation.gold_direction),
            strength=_decimal(calculation.strength),
            confidence=_decimal(calculation.confidence),
            history_count=calculation.history_count,
            method=calculation.method,
            epistemic_status=calculation.epistemic_status,
            explanation=calculation.explanation,
            evidence=calculation.evidence,
            ruleset_version=SURPRISE_RULESET_VERSION,
            data_hash=calculation.data_hash,
            is_synthetic=calculation.is_synthetic,
        )
        session.add(model)
        stored.append(model)
        inserted += 1
    await session.flush()
    return SurprisePersistenceResult(
        batch=calculations,
        models=tuple(stored),
        inserted_count=inserted,
        data_mode=data_mode,
    )


async def load_event_surprise_context(
    session: AsyncSession,
    surprises: list[EconomicSurprise],
) -> dict[UUID, EconomicEvent]:
    event_ids = {surprise.event_id for surprise in surprises}
    if not event_ids:
        return {}
    events = list(
        (await session.scalars(select(EconomicEvent).where(EconomicEvent.id.in_(event_ids)))).all()
    )
    return {event.id: event for event in events}


def surprise_to_dict(
    surprise: EconomicSurprise,
    event: EconomicEvent,
) -> dict[str, Any]:
    return {
        "id": surprise.id,
        "event_id": surprise.event_id,
        "release_id": surprise.release_id,
        "forecast_id": surprise.forecast_id,
        "event_code": event.event_code,
        "event_name": event.name,
        "component_code": surprise.component_code,
        "released_at": surprise.released_at,
        "available_at": surprise.available_at,
        "raw_surprise": float(surprise.raw_surprise),
        "standardized_surprise": float(surprise.standardized_surprise),
        "gold_direction": float(surprise.gold_direction),
        "strength": float(surprise.strength),
        "confidence": float(surprise.confidence),
        "history_count": surprise.history_count,
        "method": surprise.method,
        "epistemic_status": surprise.epistemic_status,
        "explanation": surprise.explanation,
        "evidence": surprise.evidence,
        "ruleset_version": surprise.ruleset_version,
        "data_hash": surprise.data_hash,
        "is_synthetic": surprise.is_synthetic,
    }


async def _ensure_provider(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    provider_type: str,
) -> None:
    if await session.get(Provider, code) is not None:
        return
    session.add(
        Provider(
            code=code,
            name=name,
            provider_type=provider_type,
            license_class="USER_SUPPLIED_OR_LICENSED",
            enabled=True,
            metadata_json={
                "point_in_time_policy": (
                    "Source timestamps are preserved; credentials and licensing "
                    "remain the operator's responsibility."
                )
            },
        )
    )
    await session.flush()


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: Any | None) -> Decimal | None:
    return None if value is None else _decimal(value)
