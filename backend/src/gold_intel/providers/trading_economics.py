from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

TRADING_ECONOMICS_CALENDAR_URL = "https://api.tradingeconomics.com/calendar/country/united%20states"


@dataclass(frozen=True, slots=True)
class EventComponentSpec:
    event_code: str
    event_type: str
    component_code: str


EVENT_COMPONENTS: dict[str, EventComponentSpec] = {
    "inflation rate mom": EventComponentSpec(
        "US_CPI",
        "CPI",
        "CPI_HEADLINE_MOM",
    ),
    "inflation rate yoy": EventComponentSpec(
        "US_CPI",
        "CPI",
        "CPI_HEADLINE_YOY",
    ),
    "core inflation rate mom": EventComponentSpec(
        "US_CPI",
        "CPI",
        "CPI_CORE_MOM",
    ),
    "core inflation rate yoy": EventComponentSpec(
        "US_CPI",
        "CPI",
        "CPI_CORE_YOY",
    ),
    "pce price index mom": EventComponentSpec(
        "US_PCE",
        "PCE",
        "PCE_HEADLINE_MOM",
    ),
    "pce price index yoy": EventComponentSpec(
        "US_PCE",
        "PCE",
        "PCE_HEADLINE_YOY",
    ),
    "core pce price index mom": EventComponentSpec(
        "US_PCE",
        "PCE",
        "PCE_CORE_MOM",
    ),
    "core pce price index yoy": EventComponentSpec(
        "US_PCE",
        "PCE",
        "PCE_CORE_YOY",
    ),
    "non farm payrolls": EventComponentSpec(
        "US_EMPLOYMENT_SITUATION",
        "NFP",
        "NFP_CHANGE",
    ),
    "nonfarm payrolls": EventComponentSpec(
        "US_EMPLOYMENT_SITUATION",
        "NFP",
        "NFP_CHANGE",
    ),
    "unemployment rate": EventComponentSpec(
        "US_EMPLOYMENT_SITUATION",
        "NFP",
        "UNEMPLOYMENT_RATE",
    ),
    "average hourly earnings mom": EventComponentSpec(
        "US_EMPLOYMENT_SITUATION",
        "NFP",
        "AVERAGE_HOURLY_EARNINGS_MOM",
    ),
    "initial jobless claims": EventComponentSpec(
        "US_INITIAL_JOBLESS_CLAIMS",
        "JOBLESS_CLAIMS",
        "INITIAL_JOBLESS_CLAIMS",
    ),
    "gdp growth rate qoq": EventComponentSpec(
        "US_GDP",
        "GDP",
        "GDP_QOQ_ANNUALIZED",
    ),
    "gdp growth rate": EventComponentSpec(
        "US_GDP",
        "GDP",
        "GDP_QOQ_ANNUALIZED",
    ),
    "retail sales mom": EventComponentSpec(
        "US_RETAIL_SALES",
        "RETAIL_SALES",
        "RETAIL_SALES_MOM",
    ),
    "fed interest rate decision": EventComponentSpec(
        "US_FOMC_RATE_DECISION",
        "FOMC",
        "FED_TARGET_RATE",
    ),
}


@dataclass(frozen=True, slots=True)
class TradingEconomicsEvent:
    source_event_key: str
    event_code: str
    event_type: str
    component_code: str
    name: str
    scheduled_at: datetime
    released_at: datetime | None
    observation_period: date
    importance: int
    status: str
    event_available_at: datetime
    forecast_value: float | None
    forecast_as_of: datetime | None
    forecast_available_at: datetime | None
    actual_value: float | None
    previous_value: float | None
    revised_previous_value: float | None
    release_available_at: datetime | None
    unit: str
    availability_quality: str
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TradingEconomicsCalendar:
    retrieved_at: datetime
    fetched_count: int
    excluded_count: int
    events: tuple[TradingEconomicsEvent, ...]


class TradingEconomicsCalendarProvider:
    """Licensed economic-calendar adapter with explicit source clocks.

    Historical rows expose a release timestamp and a source ``LastUpdate`` but
    not the exact time at which their consensus was first published. Historical
    consensus is therefore made eligible only at the release boundary. It can
    support post-release surprise research, but never a pre-event decision.
    Future snapshots use the actual retrieval clock and become useful for
    pre-event risk only after this service has observed them.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 45.0,
        request_interval_seconds: float = 0.55,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("A TRADING_ECONOMICS_API_KEY is required for calendar sync.")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=15.0)
        self._request_interval_seconds = request_interval_seconds
        self._transport = transport

    async def fetch(
        self,
        *,
        start: date,
        end: date,
        retrieved_at: datetime | None = None,
    ) -> TradingEconomicsCalendar:
        if start > end:
            raise ValueError("Trading Economics start cannot follow end.")
        retrieval_clock = (retrieved_at or datetime.now(UTC)).astimezone(UTC)
        raw_rows: list[dict[str, Any]] = []
        chunks = list(_date_chunks(start, end, days=28))
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            for index, (chunk_start, chunk_end) in enumerate(chunks):
                if index and self._request_interval_seconds > 0:
                    await asyncio.sleep(self._request_interval_seconds)
                raw_rows.extend(
                    await self._fetch_chunk(
                        client,
                        start=chunk_start,
                        end=chunk_end,
                    )
                )

        canonical: dict[str, dict[str, Any]] = {}
        for row in raw_rows:
            calendar_id = str(row.get("CalendarId") or row.get("CalendarID") or "").strip()
            source_key = calendar_id or _fallback_source_key(row)
            canonical[source_key] = row

        events: list[TradingEconomicsEvent] = []
        excluded = 0
        for source_key, row in canonical.items():
            normalized = _normalize_row(
                row,
                source_key=source_key,
                retrieved_at=retrieval_clock,
            )
            if normalized is None:
                excluded += 1
                continue
            events.append(normalized)
        events.sort(
            key=lambda item: (
                item.scheduled_at,
                item.component_code,
                item.source_event_key,
            )
        )
        return TradingEconomicsCalendar(
            retrieved_at=retrieval_clock,
            fetched_count=len(canonical),
            excluded_count=excluded,
            events=tuple(events),
        )

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _fetch_chunk(
        self,
        client: httpx.AsyncClient,
        *,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        response = await client.get(
            f"{TRADING_ECONOMICS_CALENDAR_URL}/{start.isoformat()}/{end.isoformat()}",
            params={
                "c": self._api_key,
                "values": "true",
                "f": "json",
            },
        )
        if response.status_code in {401, 403, 410}:
            raise ValueError("Trading Economics rejected the API key or subscription entitlement.")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("error")
            raise ValueError(
                "Trading Economics returned an error object" + (f": {message}" if message else ".")
            )
        if not isinstance(payload, list):
            raise ValueError("Trading Economics returned a non-list calendar response.")
        if len(payload) >= 1_000:
            raise ValueError(
                "Trading Economics reached the 1,000-row calendar limit; "
                "request a smaller date range."
            )
        if not all(isinstance(row, dict) for row in payload):
            raise ValueError("Trading Economics calendar rows must be objects.")
        return payload


def _normalize_row(
    row: dict[str, Any],
    *,
    source_key: str,
    retrieved_at: datetime,
) -> TradingEconomicsEvent | None:
    if _normalized_label(row.get("Country")) != "united states":
        return None
    specification = _event_spec(row)
    if specification is None:
        return None
    scheduled_at = _parse_utc_datetime(row.get("Date"))
    if scheduled_at is None:
        raise ValueError(f"Trading Economics row {source_key} has no valid UTC Date.")
    last_update = _parse_utc_datetime(row.get("LastUpdate"))
    observation_period = (_parse_utc_datetime(row.get("ReferenceDate")) or scheduled_at).date()
    unit = _canonical_unit(specification.component_code, str(row.get("Unit") or ""))
    actual_value = _component_value(
        row,
        numeric_field="ActualValue",
        text_field="Actual",
        component_code=specification.component_code,
    )
    forecast_value = _component_value(
        row,
        numeric_field="ForecastValue",
        text_field="Forecast",
        component_code=specification.component_code,
    )
    previous = _component_value(
        row,
        numeric_field="PreviousValue",
        text_field="Previous",
        component_code=specification.component_code,
    )
    originally_reported_previous = _parse_number(row.get("Revised"))
    previous_value: float | None
    revised_previous_value: float | None
    if originally_reported_previous is not None:
        originally_reported_previous = _normalize_component_value(
            originally_reported_previous,
            component_code=specification.component_code,
            source_unit=str(row.get("Unit") or ""),
        )
        previous_value = originally_reported_previous
        revised_previous_value = previous
    else:
        previous_value = previous
        revised_previous_value = None

    if actual_value is None:
        event_available_at = retrieved_at
        forecast_as_of = min(last_update or retrieved_at, retrieved_at)
        forecast_available_at = retrieved_at if forecast_value is not None else None
        release_available_at = None
        released_at = None
        status = "SCHEDULED"
        availability_quality = "OBSERVED_LIVE_SNAPSHOT"
    else:
        release_available_at = max(scheduled_at, last_update or scheduled_at)
        event_available_at = release_available_at
        # The historical endpoint documents the consensus value but does not
        # expose its pre-release publication clock. Equality with the release
        # boundary permits post-release surprise calculation without allowing
        # the forecast into any earlier simulated decision.
        forecast_as_of = scheduled_at
        forecast_available_at = scheduled_at if forecast_value is not None else None
        released_at = scheduled_at
        status = "RELEASED"
        availability_quality = "HISTORICAL_RELEASE_BOUNDARY"

    importance = {1: 1, 2: 3, 3: 5}.get(_integer(row.get("Importance")), 3)
    return TradingEconomicsEvent(
        source_event_key=f"TE:{source_key}",
        event_code=specification.event_code,
        event_type=specification.event_type,
        component_code=specification.component_code,
        name=str(row.get("Event") or row.get("Category") or specification.event_type),
        scheduled_at=scheduled_at,
        released_at=released_at,
        observation_period=observation_period,
        importance=importance,
        status=status,
        event_available_at=event_available_at,
        forecast_value=forecast_value,
        forecast_as_of=forecast_as_of if forecast_value is not None else None,
        forecast_available_at=forecast_available_at,
        actual_value=actual_value,
        previous_value=previous_value,
        revised_previous_value=revised_previous_value,
        release_available_at=release_available_at,
        unit=unit,
        availability_quality=availability_quality,
        raw_payload=row,
    )


def _event_spec(row: dict[str, Any]) -> EventComponentSpec | None:
    for candidate in (row.get("Category"), row.get("Event")):
        normalized = _normalized_label(candidate)
        if normalized in EVENT_COMPONENTS:
            return EVENT_COMPONENTS[normalized]
    return None


def _component_value(
    row: dict[str, Any],
    *,
    numeric_field: str,
    text_field: str,
    component_code: str,
) -> float | None:
    raw = row.get(numeric_field)
    value = _parse_number(raw)
    if value is None:
        value = _parse_number(row.get(text_field))
    if value is None:
        return None
    return _normalize_component_value(
        value,
        component_code=component_code,
        source_unit=str(row.get("Unit") or ""),
    )


def _normalize_component_value(
    value: float,
    *,
    component_code: str,
    source_unit: str,
) -> float:
    if component_code in {"NFP_CHANGE", "INITIAL_JOBLESS_CLAIMS"}:
        normalized_unit = source_unit.strip().upper()
        if normalized_unit in {"K", "THOUSAND", "THOUSANDS"} or abs(value) >= 10_000:
            return value / 1_000
    return value


def _canonical_unit(component_code: str, source_unit: str) -> str:
    if component_code in {"NFP_CHANGE", "INITIAL_JOBLESS_CLAIMS"}:
        return "THOUSANDS"
    if component_code in {
        "CPI_HEADLINE_MOM",
        "CPI_HEADLINE_YOY",
        "CPI_CORE_MOM",
        "CPI_CORE_YOY",
        "PCE_HEADLINE_MOM",
        "PCE_HEADLINE_YOY",
        "PCE_CORE_MOM",
        "PCE_CORE_YOY",
        "UNEMPLOYMENT_RATE",
        "AVERAGE_HOURLY_EARNINGS_MOM",
        "GDP_QOQ_ANNUALIZED",
        "RETAIL_SALES_MOM",
        "FED_TARGET_RATE",
    }:
        return "PERCENT"
    return source_unit.strip().upper() or "UNSPECIFIED"


def _parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        return number if number == number else None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "na", "-"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = (
        text.replace(",", "").replace("%", "").replace("−", "-").replace("–", "-").strip("() ")
    )
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", cleaned)
    if match is None:
        return None
    try:
        number = float(Decimal(match.group(0)))
    except InvalidOperation:
        return None
    suffix = cleaned[match.end() :].strip().upper()
    multiplier = (
        1_000
        if suffix.startswith("K")
        else 1_000_000
        if suffix.startswith("M")
        else 1_000_000_000
        if suffix.startswith("B")
        else 1_000_000_000_000
        if suffix.startswith("T")
        else 1
    )
    result = number * multiplier
    return -result if negative else result


def _parse_utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalized_label(value: Any) -> str:
    text = str(value or "").lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _integer(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 2


def _date_chunks(
    start: date,
    end: date,
    *,
    days: int,
) -> tuple[tuple[date, date], ...]:
    output: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=days - 1), end)
        output.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return tuple(output)


def _fallback_source_key(row: dict[str, Any]) -> str:
    fields = (
        row.get("Date"),
        row.get("Country"),
        row.get("Category"),
        row.get("Event"),
        row.get("Ticker"),
    )
    return "|".join(str(value or "").strip() for value in fields)
