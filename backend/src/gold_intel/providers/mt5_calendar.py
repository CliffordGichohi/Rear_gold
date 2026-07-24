from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MT5_CALENDAR_PROVIDER_CODE = "METAQUOTES_MT5_CALENDAR"
MT5_CONSENSUS_PROVIDER_CODE = "METAQUOTES_MT5_CONSENSUS"
MT5_CALENDAR_SCHEMA_VERSION = "1.0"
MT5_DATETIME_FORMAT = "%Y.%m.%d %H:%M:%S"
MT5_KE_TIMEZONE_POLICY = "IC_MARKETS_KE_FIXED_UTC_PLUS_3_V1"


@dataclass(frozen=True, slots=True)
class Mt5ComponentSpec:
    event_id: str
    source_name: str
    source_code: str
    event_code: str
    release_name: str
    event_type: str
    component_code: str
    unit: str
    source_unit: int
    source_multiplier: int


MT5_COMPONENT_SPECS: tuple[Mt5ComponentSpec, ...] = (
    Mt5ComponentSpec(
        "840030005",
        "CPI m/m",
        "consumer-price-index-mm",
        "US_CPI",
        "US Consumer Price Index",
        "CPI",
        "CPI_HEADLINE_MOM",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840030007",
        "CPI y/y",
        "consumer-price-index-yy",
        "US_CPI",
        "US Consumer Price Index",
        "CPI",
        "CPI_HEADLINE_YOY",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840030006",
        "Core CPI m/m",
        "consumer-price-index-ex-food-energy-mm",
        "US_CPI",
        "US Consumer Price Index",
        "CPI",
        "CPI_CORE_MOM",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840030008",
        "Core CPI y/y",
        "consumer-price-index-ex-food-energy-yy",
        "US_CPI",
        "US Consumer Price Index",
        "CPI",
        "CPI_CORE_YOY",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840010003",
        "PCE Price Index m/m",
        "pce-price-index-mm",
        "US_PCE",
        "US Personal Income and Outlays",
        "PCE",
        "PCE_HEADLINE_MOM",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840010004",
        "PCE Price Index y/y",
        "pce-price-index-yy",
        "US_PCE",
        "US Personal Income and Outlays",
        "PCE",
        "PCE_HEADLINE_YOY",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840010001",
        "Core PCE Price Index m/m",
        "core-pce-price-index-mm",
        "US_PCE",
        "US Personal Income and Outlays",
        "PCE",
        "PCE_CORE_MOM",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840010002",
        "Core PCE Price Index y/y",
        "core-pce-price-index-yy",
        "US_PCE",
        "US Personal Income and Outlays",
        "PCE",
        "PCE_CORE_YOY",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840030016",
        "Nonfarm Payrolls",
        "nonfarm-payrolls",
        "US_EMPLOYMENT_SITUATION",
        "US Employment Situation",
        "NFP",
        "NFP_CHANGE",
        "THOUSAND_JOBS",
        4,
        1,
    ),
    Mt5ComponentSpec(
        "840030015",
        "Unemployment Rate",
        "unemployment-rate",
        "US_EMPLOYMENT_SITUATION",
        "US Employment Situation",
        "NFP",
        "UNEMPLOYMENT_RATE",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840030018",
        "Average Hourly Earnings m/m",
        "average-hourly-earnings-mm",
        "US_EMPLOYMENT_SITUATION",
        "US Employment Situation",
        "NFP",
        "AVERAGE_HOURLY_EARNINGS_MOM",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840030019",
        "Average Hourly Earnings y/y",
        "average-hourly-earnings-yy",
        "US_EMPLOYMENT_SITUATION",
        "US Employment Situation",
        "NFP",
        "AVERAGE_HOURLY_EARNINGS_YOY",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840140001",
        "Initial Jobless Claims",
        "initial-jobless-claims",
        "US_INITIAL_JOBLESS_CLAIMS",
        "US Initial Jobless Claims",
        "JOBLESS_CLAIMS",
        "INITIAL_JOBLESS_CLAIMS",
        "THOUSAND_PEOPLE",
        0,
        1,
    ),
    Mt5ComponentSpec(
        "840010007",
        "GDP q/q",
        "gross-domestic-product-qq",
        "US_GDP",
        "US Gross Domestic Product",
        "GDP",
        "GDP_QOQ_ANNUALIZED",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840020010",
        "Retail Sales m/m",
        "retail-sales-mm",
        "US_RETAIL_SALES",
        "US Retail Sales",
        "RETAIL_SALES",
        "RETAIL_SALES_MOM",
        "PERCENT",
        1,
        0,
    ),
    Mt5ComponentSpec(
        "840050014",
        "Fed Interest Rate Decision",
        "fed-interest-rate-decision",
        "US_FOMC_RATE_DECISION",
        "Federal Reserve Interest Rate Decision",
        "FOMC",
        "FED_TARGET_RATE",
        "PERCENT",
        1,
        0,
    ),
)
MT5_COMPONENT_BY_EVENT_ID = {
    specification.event_id: specification for specification in MT5_COMPONENT_SPECS
}


@dataclass(frozen=True, slots=True)
class Mt5CalendarComponent:
    specification: Mt5ComponentSpec
    source_value_id: str
    observation_period: date
    actual_value: float | None
    forecast_value: float | None
    previous_value: float | None
    revised_previous_value: float | None
    source_revision: int
    source_importance: int
    source_url: str
    raw_payload: dict[str, str]


@dataclass(frozen=True, slots=True)
class Mt5CalendarEvent:
    event_code: str
    name: str
    event_type: str
    scheduled_at: datetime
    released_at: datetime | None
    importance: int
    status: str
    source_event_key: str
    available_at: datetime
    components: tuple[Mt5CalendarComponent, ...]


@dataclass(frozen=True, slots=True)
class Mt5Calendar:
    retrieved_at: datetime
    source_sha256: str
    raw_row_count: int
    selected_row_count: int
    excluded_row_count: int
    server_utc_offset_seconds: int
    timezone_policy: str
    events: tuple[Mt5CalendarEvent, ...]


def parse_mt5_calendar_export(
    path: Path,
    *,
    server_utc_offset_seconds: int,
    timezone_policy: str,
) -> Mt5Calendar:
    if timezone_policy != MT5_KE_TIMEZONE_POLICY:
        raise ValueError(
            "The MT5 calendar timezone policy must be explicitly validated for the "
            "connected broker server."
        )
    if server_utc_offset_seconds != 10_800:
        raise ValueError(
            "IC Markets KE calendar history requires the validated fixed UTC+03:00 "
            "server offset."
        )
    raw_rows = _read_csv(path)
    if not raw_rows:
        raise ValueError("The MT5 calendar export contains no rows.")
    source_hash = _sha256(path)
    retrieved_at = _validate_export_clock(
        raw_rows,
        server_utc_offset_seconds=server_utc_offset_seconds,
    )
    source_timezone = timezone(timedelta(seconds=server_utc_offset_seconds))

    selected: dict[str, tuple[datetime, Mt5CalendarComponent]] = {}
    for raw in raw_rows:
        specification = MT5_COMPONENT_BY_EVENT_ID.get(raw["event_id"])
        if specification is None:
            continue
        _validate_source_contract(raw, specification)
        value_id = raw["value_id"].strip()
        scheduled_at = _parse_server_datetime(
            raw["event_time_server"],
            source_timezone=source_timezone,
        )
        component = Mt5CalendarComponent(
            specification=specification,
            source_value_id=value_id,
            observation_period=_observation_period(
                raw["observation_period_server"],
                fallback=scheduled_at.date(),
            ),
            actual_value=_optional_float(raw["actual_value"]),
            forecast_value=_optional_float(raw["forecast_value"]),
            previous_value=_optional_float(raw["previous_value"]),
            revised_previous_value=_optional_float(raw["revised_previous_value"]),
            source_revision=_integer(raw["revision"], field="revision"),
            source_importance=_integer(raw["importance"], field="importance"),
            source_url=raw["source_url"].strip(),
            raw_payload=raw,
        )
        existing = selected.get(value_id)
        candidate = (scheduled_at, component)
        if existing is not None and existing != candidate:
            raise ValueError(f"MT5 calendar value {value_id} has conflicting rows.")
        selected[value_id] = candidate

    grouped: dict[tuple[str, datetime], list[Mt5CalendarComponent]] = {}
    for scheduled_at, component in selected.values():
        key = (component.specification.event_code, scheduled_at)
        grouped.setdefault(key, []).append(component)

    events: list[Mt5CalendarEvent] = []
    for (event_code, scheduled_at), components in grouped.items():
        components.sort(key=lambda item: item.specification.component_code)
        names = {component.specification.release_name for component in components}
        event_types = {component.specification.event_type for component in components}
        if len(names) != 1 or len(event_types) != 1:
            raise ValueError(f"MT5 grouped event {event_code} has inconsistent definitions.")
        has_release = any(component.actual_value is not None for component in components)
        if has_release:
            status = "RELEASED"
            released_at: datetime | None = scheduled_at
            available_at = scheduled_at
        elif scheduled_at <= retrieved_at:
            status = "CANCELLED"
            released_at = None
            available_at = scheduled_at
        else:
            status = "SCHEDULED"
            released_at = None
            available_at = retrieved_at
        events.append(
            Mt5CalendarEvent(
                event_code=event_code,
                name=next(iter(names)),
                event_type=next(iter(event_types)),
                scheduled_at=scheduled_at,
                released_at=released_at,
                importance=max(
                    _importance(component.source_importance) for component in components
                ),
                status=status,
                source_event_key=(
                    f"MT5:{event_code}:{scheduled_at.astimezone(UTC):%Y%m%dT%H%M%SZ}"
                ),
                available_at=available_at,
                components=tuple(components),
            )
        )
    events.sort(key=lambda item: (item.scheduled_at, item.event_code))
    return Mt5Calendar(
        retrieved_at=retrieved_at,
        source_sha256=source_hash,
        raw_row_count=len(raw_rows),
        selected_row_count=len(selected),
        excluded_row_count=len(raw_rows) - len(selected),
        server_utc_offset_seconds=server_utc_offset_seconds,
        timezone_policy=timezone_policy,
        events=tuple(events),
    )


def mt5_calendar_bundles(
    calendar: Mt5Calendar,
    *,
    maximum_events: int = 500,
) -> tuple[dict[str, Any], ...]:
    if not 1 <= maximum_events <= 500:
        raise ValueError("maximum_events must be between 1 and 500.")
    by_year: dict[int, list[Mt5CalendarEvent]] = {}
    for event in calendar.events:
        by_year.setdefault(event.scheduled_at.year, []).append(event)

    bundles: list[dict[str, Any]] = []
    for year, year_events in sorted(by_year.items()):
        for part, start in enumerate(range(0, len(year_events), maximum_events), start=1):
            selected = year_events[start : start + maximum_events]
            bundles.append(
                {
                    "provider_code": MT5_CALENDAR_PROVIDER_CODE,
                    "dataset_code": f"US_GOLD_MACRO_CALENDAR_{year}_P{part}",
                    "schema_version": MT5_CALENDAR_SCHEMA_VERSION,
                    "is_synthetic": False,
                    "source_published_at": calendar.retrieved_at.isoformat(),
                    "events": [
                        _event_payload(event, calendar=calendar) for event in selected
                    ],
                }
            )
    return tuple(bundles)


def _event_payload(
    event: Mt5CalendarEvent,
    *,
    calendar: Mt5Calendar,
) -> dict[str, Any]:
    historical_boundary = event.scheduled_at <= calendar.retrieved_at
    forecasts: list[dict[str, Any]] = []
    releases: list[dict[str, Any]] = []
    for component in event.components:
        if component.forecast_value is not None:
            forecast_clock = (
                event.scheduled_at if historical_boundary else calendar.retrieved_at
            )
            forecasts.append(
                {
                    "component_code": component.specification.component_code,
                    "forecast_value": component.forecast_value,
                    "unit": component.specification.unit,
                    "forecast_as_of": forecast_clock.isoformat(),
                    "available_at": forecast_clock.isoformat(),
                    "provider_code": MT5_CONSENSUS_PROVIDER_CODE,
                    "vintage": f"MT5:forecast:{component.source_value_id}"[:64],
                    "metadata": {
                        "availability_quality": (
                            "HISTORICAL_RELEASE_BOUNDARY"
                            if historical_boundary
                            else "OBSERVED_LIVE_EXPORT"
                        ),
                        "pre_event_use_allowed": not historical_boundary,
                        "source_value_id": component.source_value_id,
                        "source_event_id": component.specification.event_id,
                        "source_url": component.source_url,
                        "license_class": "METAQUOTES_PLATFORM_CALENDAR_LOCAL_RESEARCH",
                    },
                }
            )
        if component.actual_value is not None and event.released_at is not None:
            releases.append(
                {
                    "component_code": component.specification.component_code,
                    "observation_period": component.observation_period.isoformat(),
                    "actual_value": component.actual_value,
                    "previous_value": component.previous_value,
                    "revised_previous_value": component.revised_previous_value,
                    "unit": component.specification.unit,
                    "released_at": event.released_at.isoformat(),
                    "available_at": event.released_at.isoformat(),
                    "is_revision": False,
                    "vintage": (
                        f"MT5:release:{component.source_value_id}:"
                        f"r{component.source_revision}"
                    )[:64],
                    "metadata": {
                        "availability_quality": "HISTORICAL_RELEASE_BOUNDARY",
                        "source_value_id": component.source_value_id,
                        "source_event_id": component.specification.event_id,
                        "source_revision_ordinal": component.source_revision,
                        "source_url": component.source_url,
                        "revision_semantics": (
                            "previous_value is the prior originally reported value; "
                            "revised_previous_value is the updated prior value when supplied."
                        ),
                        "license_class": "METAQUOTES_PLATFORM_CALENDAR_LOCAL_RESEARCH",
                    },
                }
            )
    return {
        "event_code": event.event_code,
        "name": event.name,
        "event_type": event.event_type,
        "scheduled_at": event.scheduled_at.isoformat(),
        "released_at": (
            event.released_at.isoformat() if event.released_at is not None else None
        ),
        "importance": event.importance,
        "is_scheduled": True,
        "status": event.status,
        "source_event_key": event.source_event_key,
        "available_at": event.available_at.isoformat(),
        "forecasts": forecasts,
        "releases": releases,
        "metadata": {
            "country": "United States",
            "transport": "IC Markets KE MetaTrader 5 terminal",
            "source": "MetaQuotes MT5 Economic Calendar",
            "source_sha256": calendar.source_sha256,
            "source_value_ids": [
                component.source_value_id for component in event.components
            ],
            "source_event_ids": [
                component.specification.event_id for component in event.components
            ],
            "server_utc_offset_seconds": calendar.server_utc_offset_seconds,
            "timezone_policy": calendar.timezone_policy,
            "point_in_time_warning": (
                "Historical consensus has no first-publication timestamp and is "
                "eligible only at the release boundary. Future exports use the "
                "actual retrieval clock."
            ),
        },
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "exported_at_server",
            "exported_at_gmt",
            "current_server_utc_offset_seconds",
            "value_id",
            "event_id",
            "event_time_server",
            "observation_period_server",
            "revision",
            "actual_value",
            "previous_value",
            "revised_previous_value",
            "forecast_value",
            "country_code",
            "currency",
            "unit",
            "importance",
            "multiplier",
            "event_code",
            "event_name",
            "source_url",
        }
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"MT5 calendar export is missing fields: {sorted(missing)}")
        return [dict(row) for row in reader]


def _validate_export_clock(
    rows: list[dict[str, str]],
    *,
    server_utc_offset_seconds: int,
) -> datetime:
    server_clocks = {row["exported_at_server"] for row in rows}
    gmt_clocks = {row["exported_at_gmt"] for row in rows}
    offsets = {row["current_server_utc_offset_seconds"] for row in rows}
    if len(server_clocks) != 1 or len(gmt_clocks) != 1 or len(offsets) != 1:
        raise ValueError("MT5 export clock metadata is inconsistent across rows.")
    exported_server = datetime.strptime(next(iter(server_clocks)), MT5_DATETIME_FORMAT)
    exported_gmt = datetime.strptime(next(iter(gmt_clocks)), MT5_DATETIME_FORMAT).replace(
        tzinfo=UTC
    )
    source_offset = _integer(next(iter(offsets)), field="server UTC offset")
    if source_offset != server_utc_offset_seconds:
        raise ValueError("MT5 export offset does not match the selected timezone policy.")
    expected_gmt = (
        exported_server.replace(
            tzinfo=timezone(timedelta(seconds=server_utc_offset_seconds))
        )
        .astimezone(UTC)
    )
    if abs((expected_gmt - exported_gmt).total_seconds()) > 2:
        raise ValueError("MT5 server and GMT export clocks do not reconcile.")
    return exported_gmt


def _validate_source_contract(
    raw: dict[str, str],
    specification: Mt5ComponentSpec,
) -> None:
    checks = {
        "event_name": specification.source_name,
        "event_code": specification.source_code,
        "country_code": "US",
        "currency": "USD",
        "unit": str(specification.source_unit),
        "multiplier": str(specification.source_multiplier),
    }
    mismatches = {
        field: {"expected": expected, "received": raw.get(field)}
        for field, expected in checks.items()
        if raw.get(field) != expected
    }
    if mismatches:
        raise ValueError(
            f"MT5 calendar contract drift for event {specification.event_id}: "
            f"{mismatches}"
        )


def _parse_server_datetime(value: str, *, source_timezone: timezone) -> datetime:
    parsed = datetime.strptime(value, MT5_DATETIME_FORMAT)
    return parsed.replace(tzinfo=source_timezone).astimezone(UTC)


def _observation_period(value: str, *, fallback: date) -> date:
    parsed = datetime.strptime(value, MT5_DATETIME_FORMAT).date()
    return fallback if parsed.year <= 1970 else parsed


def _optional_float(value: str) -> float | None:
    stripped = value.strip()
    return float(stripped) if stripped else None


def _integer(value: str, *, field: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"MT5 {field} must be an integer.") from exc


def _importance(source_importance: int) -> int:
    return {0: 1, 1: 1, 2: 3, 3: 5}.get(source_importance, 1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
