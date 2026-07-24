from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.application.economic_events import ingest_economic_event_bundle
from gold_intel.providers.trading_economics import (
    TradingEconomicsCalendar,
    TradingEconomicsCalendarProvider,
    TradingEconomicsEvent,
)


@dataclass(frozen=True, slots=True)
class TradingEconomicsSyncResult:
    start: date
    end: date
    fetched_rows: int
    supported_rows: int
    excluded_rows: int
    inserted_events: int
    inserted_forecasts: int
    inserted_releases: int
    calculated_surprises: int
    batch_id: UUID
    duplicate_batch: bool
    retrieved_at: datetime


async def sync_trading_economics_calendar(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    start: date,
    end: date,
    api_key: str,
    provider: TradingEconomicsCalendarProvider | None = None,
) -> TradingEconomicsSyncResult:
    calendar_provider = provider or TradingEconomicsCalendarProvider(api_key=api_key)
    calendar = await calendar_provider.fetch(start=start, end=end)
    if not calendar.events:
        raise ValueError("Trading Economics returned no supported US gold-macro calendar rows.")
    payload = trading_economics_bundle(calendar)
    result = await ingest_economic_event_bundle(
        session,
        payload=payload,
        raw_store_root=raw_store_root,
    )
    return TradingEconomicsSyncResult(
        start=start,
        end=end,
        fetched_rows=calendar.fetched_count,
        supported_rows=len(calendar.events),
        excluded_rows=calendar.excluded_count,
        inserted_events=result.event_count,
        inserted_forecasts=result.forecast_count,
        inserted_releases=result.release_count,
        calculated_surprises=len(result.surprise_result.models),
        batch_id=result.batch.id,
        duplicate_batch=result.duplicate,
        retrieved_at=calendar.retrieved_at,
    )


def trading_economics_bundle(
    calendar: TradingEconomicsCalendar,
) -> dict[str, Any]:
    source_published_at = max(
        (event.event_available_at for event in calendar.events),
        default=calendar.retrieved_at,
    )
    return {
        "provider_code": "TRADING_ECONOMICS",
        "dataset_code": "US_GOLD_MACRO_CALENDAR",
        "schema_version": "1.0",
        "is_synthetic": False,
        "source_published_at": source_published_at,
        "events": [_event_payload(event) for event in calendar.events],
    }


def _event_payload(event: TradingEconomicsEvent) -> dict[str, Any]:
    forecasts: list[dict[str, Any]] = []
    if (
        event.forecast_value is not None
        and event.forecast_as_of is not None
        and event.forecast_available_at is not None
    ):
        forecasts.append(
            {
                "component_code": event.component_code,
                "forecast_value": event.forecast_value,
                "unit": event.unit,
                "forecast_as_of": event.forecast_as_of,
                "available_at": event.forecast_available_at,
                "provider_code": "TRADING_ECONOMICS_CONSENSUS",
                "vintage": _vintage(
                    event,
                    "forecast",
                    event.forecast_available_at,
                ),
                "metadata": {
                    "consensus_definition": (
                        "Trading Economics representative-economist consensus."
                    ),
                    "availability_quality": event.availability_quality,
                    "pre_event_use_allowed": (
                        event.availability_quality == "OBSERVED_LIVE_SNAPSHOT"
                    ),
                    "license_class": "LICENSED_SINGLE_USER_OR_ENTERPRISE",
                },
            }
        )

    releases: list[dict[str, Any]] = []
    if (
        event.actual_value is not None
        and event.released_at is not None
        and event.release_available_at is not None
    ):
        releases.append(
            {
                "component_code": event.component_code,
                "observation_period": event.observation_period,
                "actual_value": event.actual_value,
                "previous_value": event.previous_value,
                "revised_previous_value": event.revised_previous_value,
                "unit": event.unit,
                "released_at": event.released_at,
                "available_at": event.release_available_at,
                "is_revision": False,
                "vintage": _vintage(
                    event,
                    "release",
                    event.release_available_at,
                ),
                "metadata": {
                    "availability_quality": event.availability_quality,
                    "license_class": "LICENSED_SINGLE_USER_OR_ENTERPRISE",
                    "revision_semantics": (
                        "previous_value is the originally reported prior value; "
                        "revised_previous_value is the provider's updated prior value."
                    ),
                },
            }
        )

    return {
        "event_code": event.event_code,
        "name": event.name,
        "event_type": event.event_type,
        "scheduled_at": event.scheduled_at,
        "released_at": event.released_at,
        "importance": event.importance,
        "is_scheduled": True,
        "status": event.status,
        "source_event_key": event.source_event_key,
        "available_at": event.event_available_at,
        "forecasts": forecasts,
        "releases": releases,
        "metadata": {
            "country": "United States",
            "component_code": event.component_code,
            "availability_quality": event.availability_quality,
            "retrieval_endpoint": "Trading Economics Economic Calendar API",
            "source_payload": event.raw_payload,
            "point_in_time_warning": (
                "Historical consensus has no first-publication timestamp and is "
                "eligible only at the release boundary. Live snapshots use their "
                "observed retrieval time."
            ),
        },
    }


def _vintage(
    event: TradingEconomicsEvent,
    kind: str,
    available_at: datetime,
) -> str:
    clock = available_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"TE:{kind}:{clock}"[:64]
