from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

NEW_YORK = ZoneInfo("America/New_York")
ALFRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


@dataclass(frozen=True, slots=True)
class VintageSeriesSpec:
    external_code: str
    internal_code: str
    name: str
    unit: str
    frequency: str
    expected_lag_seconds: int
    family: str


ALFRED_MACRO_SERIES: tuple[VintageSeriesSpec, ...] = (
    VintageSeriesSpec(
        "CPIAUCSL",
        "US_CPI_HEADLINE",
        "US Consumer Price Index, all urban consumers",
        "INDEX",
        "MONTHLY",
        45 * 86_400,
        "INFLATION",
    ),
    VintageSeriesSpec(
        "CPILFESL",
        "US_CPI_CORE",
        "US Consumer Price Index excluding food and energy",
        "INDEX",
        "MONTHLY",
        45 * 86_400,
        "INFLATION",
    ),
    VintageSeriesSpec(
        "PCEPI",
        "US_PCE_HEADLINE",
        "US Personal Consumption Expenditures Price Index",
        "INDEX",
        "MONTHLY",
        60 * 86_400,
        "INFLATION",
    ),
    VintageSeriesSpec(
        "PCEPILFE",
        "US_PCE_CORE",
        "US PCE Price Index excluding food and energy",
        "INDEX",
        "MONTHLY",
        60 * 86_400,
        "INFLATION",
    ),
    VintageSeriesSpec(
        "GDPC1",
        "US_REAL_GDP",
        "US real gross domestic product",
        "BILLIONS_CHAINED_DOLLARS",
        "QUARTERLY",
        120 * 86_400,
        "GROWTH",
    ),
    VintageSeriesSpec(
        "RSAFS",
        "US_RETAIL_SALES",
        "US advance retail and food services sales",
        "MILLIONS_DOLLARS",
        "MONTHLY",
        45 * 86_400,
        "GROWTH",
    ),
    VintageSeriesSpec(
        "PAYEMS",
        "US_NONFARM_PAYROLLS",
        "US total nonfarm payroll employment",
        "THOUSANDS_PERSONS",
        "MONTHLY",
        45 * 86_400,
        "LABOUR",
    ),
    VintageSeriesSpec(
        "UNRATE",
        "US_UNEMPLOYMENT_RATE",
        "US civilian unemployment rate",
        "PERCENT",
        "MONTHLY",
        45 * 86_400,
        "LABOUR",
    ),
    VintageSeriesSpec(
        "CES0500000003",
        "US_AVERAGE_HOURLY_EARNINGS",
        "US average hourly earnings, total private",
        "DOLLARS_PER_HOUR",
        "MONTHLY",
        45 * 86_400,
        "LABOUR",
    ),
    VintageSeriesSpec(
        "ICSA",
        "US_INITIAL_JOBLESS_CLAIMS",
        "US initial unemployment insurance claims",
        "PERSONS",
        "WEEKLY",
        14 * 86_400,
        "LABOUR",
    ),
)


@dataclass(frozen=True, slots=True)
class VintageObservation:
    series_code: str
    observation_time: datetime
    value: Decimal
    unit: str
    available_at: datetime
    vintage: str
    is_revision: bool
    source_record_key: str
    payload: dict[str, Any]


class AlfredVintageProvider:
    """Read ALFRED revisions with a conservative date-only availability clock."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("A FRED_API_KEY is required for ALFRED vintage sync.")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=15.0)
        self._transport = transport

    async def fetch(
        self,
        *,
        start: date,
        end: date,
    ) -> tuple[VintageObservation, ...]:
        if start >= end:
            raise ValueError("start must precede end")
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            rows: list[VintageObservation] = []
            for specification in ALFRED_MACRO_SERIES:
                rows.extend(
                    await self._fetch_series(
                        client,
                        specification=specification,
                        start=start,
                        end=end,
                    )
                )
        output = tuple(
            sorted(
                rows,
                key=lambda row: (
                    row.series_code,
                    row.observation_time,
                    row.available_at,
                ),
            )
        )
        if not output:
            raise ValueError(
                "ALFRED returned no eligible vintage observations for the requested range."
            )
        return output

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _fetch_series(
        self,
        client: httpx.AsyncClient,
        *,
        specification: VintageSeriesSpec,
        start: date,
        end: date,
    ) -> list[VintageObservation]:
        try:
            response = await client.get(
                ALFRED_OBSERVATIONS_URL,
                params={
                    "series_id": specification.external_code,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "observation_start": start.isoformat(),
                    "observation_end": end.isoformat(),
                    "realtime_start": start.isoformat(),
                    "realtime_end": end.isoformat(),
                    # Output type 1 is the four-column real-time-period format:
                    # observation date, value, realtime start, realtime end. It
                    # preserves every revision and matches this parser. Types 2
                    # and 3 are vintage-date cross-tabulations with dynamic
                    # series/vintage column names.
                    "output_type": "1",
                    "sort_order": "asc",
                    "limit": "100000",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"ALFRED rejected a vintage request with HTTP {exc.response.status_code}."
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("ALFRED returned a non-object response.")
        if "error_code" in payload:
            raise ValueError("ALFRED returned an API error; verify the key and requested dates.")
        observations = payload.get("observations")
        if not isinstance(observations, list):
            raise ValueError(
                f"ALFRED returned no observation list for {specification.external_code}."
            )
        normalized: list[VintageObservation] = []
        seen_versions: dict[date, int] = {}
        if not all(isinstance(raw, dict) for raw in observations):
            raise ValueError("ALFRED observation rows must be objects.")
        ordered_observations = sorted(
            observations,
            key=lambda raw: (
                str(raw.get("date", "")),
                str(raw.get("realtime_start", "")),
            ),
        )
        for raw in ordered_observations:
            if not isinstance(raw, dict):
                raise ValueError("ALFRED observation rows must be objects.")
            value_text = str(raw.get("value", "")).strip()
            if not value_text or value_text == ".":
                continue
            try:
                value = Decimal(value_text)
                observation_date = date.fromisoformat(str(raw["date"]))
                realtime_start = date.fromisoformat(str(raw["realtime_start"]))
                realtime_end = date.fromisoformat(str(raw["realtime_end"]))
            except (InvalidOperation, KeyError, ValueError) as exc:
                raise ValueError(f"Invalid ALFRED row for {specification.external_code}.") from exc
            version_index = seen_versions.get(observation_date, 0)
            seen_versions[observation_date] = version_index + 1
            observation_time = datetime.combine(
                observation_date,
                time(0, 0),
                tzinfo=UTC,
            )
            # ALFRED exposes a real-time date, not a guaranteed intraday release
            # timestamp. T+1 midnight ET fails closed for intraday backtests.
            available_at = datetime.combine(
                realtime_start + timedelta(days=1),
                time(0, 0),
                tzinfo=NEW_YORK,
            ).astimezone(UTC)
            source_key = (
                f"{specification.external_code}:{observation_date.isoformat()}:"
                f"{realtime_start.isoformat()}:{value_text}"
            )
            normalized.append(
                VintageObservation(
                    series_code=specification.internal_code,
                    observation_time=observation_time,
                    value=value,
                    unit=specification.unit,
                    available_at=available_at,
                    vintage=(f"ALFRED:{realtime_start.isoformat()}:{realtime_end.isoformat()}"),
                    is_revision=version_index > 0,
                    source_record_key=source_key,
                    payload={
                        "provider": "ALFRED_OFFICIAL",
                        "external_series_code": specification.external_code,
                        "internal_series_code": specification.internal_code,
                        "family": specification.family,
                        "date": observation_date.isoformat(),
                        "value": value_text,
                        "realtime_start": realtime_start.isoformat(),
                        "realtime_end": realtime_end.isoformat(),
                        "output_type": 1,
                        "availability_policy": ("ALFRED_REALTIME_DATE_PLUS_1_AT_00_ET"),
                        "retrieval_endpoint": ALFRED_OBSERVATIONS_URL,
                    },
                )
            )
        return normalized
