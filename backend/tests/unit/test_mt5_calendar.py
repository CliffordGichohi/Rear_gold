from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gold_intel.api.schemas import EconomicEventBundleRequest
from gold_intel.providers.mt5_calendar import (
    MT5_COMPONENT_BY_EVENT_ID,
    MT5_KE_TIMEZONE_POLICY,
    mt5_calendar_bundles,
    parse_mt5_calendar_export,
)

FIELDNAMES = (
    "schema_version",
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
)


def _row(
    event_id: str,
    value_id: str,
    *,
    actual: str,
    forecast: str,
) -> dict[str, str]:
    specification = MT5_COMPONENT_BY_EVENT_ID[event_id]
    return {
        "schema_version": "1.0",
        "exported_at_server": "2026.07.24 12:03:45",
        "exported_at_gmt": "2026.07.24 09:03:45",
        "current_server_utc_offset_seconds": "10800",
        "value_id": value_id,
        "event_id": event_id,
        "event_time_server": "2021.08.11 15:30:00",
        "observation_period_server": "2021.07.01 00:00:00",
        "revision": "0",
        "actual_value": actual,
        "previous_value": "0.3",
        "revised_previous_value": "",
        "forecast_value": forecast,
        "country_code": "US",
        "currency": "USD",
        "unit": str(specification.source_unit),
        "importance": "3",
        "multiplier": str(specification.source_multiplier),
        "event_code": specification.source_code,
        "event_name": specification.source_name,
        "source_url": "https://www.bls.gov",
    }


def _write_export(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def test_mt5_calendar_groups_components_and_preserves_point_in_time_boundary(
    tmp_path: Path,
) -> None:
    export = tmp_path / "calendar.csv"
    _write_export(
        export,
        [
            _row("840030005", "1001", actual="0.5", forecast="0.4"),
            _row("840030006", "1002", actual="0.3", forecast="0.2"),
            _row("840030007", "1003", actual="5.4", forecast="5.3"),
            _row("840030008", "1004", actual="4.3", forecast="4.2"),
        ],
    )

    calendar = parse_mt5_calendar_export(
        export,
        server_utc_offset_seconds=10_800,
        timezone_policy=MT5_KE_TIMEZONE_POLICY,
    )

    assert calendar.raw_row_count == 4
    assert calendar.selected_row_count == 4
    assert calendar.excluded_row_count == 0
    assert calendar.retrieved_at == datetime(2026, 7, 24, 9, 3, 45, tzinfo=UTC)
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.event_code == "US_CPI"
    assert event.scheduled_at == datetime(2021, 8, 11, 12, 30, tzinfo=UTC)
    assert event.status == "RELEASED"
    assert len(event.components) == 4

    bundles = mt5_calendar_bundles(calendar)
    assert len(bundles) == 1
    payload = EconomicEventBundleRequest.model_validate(bundles[0])
    uploaded_event = payload.events[0]
    assert len(uploaded_event.forecasts) == 4
    assert len(uploaded_event.releases) == 4
    assert all(
        forecast.available_at == uploaded_event.released_at
        for forecast in uploaded_event.forecasts
    )
    assert all(
        forecast.metadata["pre_event_use_allowed"] is False
        for forecast in uploaded_event.forecasts
    )


def test_mt5_calendar_rejects_unvalidated_timezone_policy(tmp_path: Path) -> None:
    export = tmp_path / "calendar.csv"
    _write_export(export, [_row("840030005", "1001", actual="0.5", forecast="0.4")])

    with pytest.raises(ValueError, match="timezone policy"):
        parse_mt5_calendar_export(
            export,
            server_utc_offset_seconds=10_800,
            timezone_policy="UNVALIDATED",
        )


def test_mt5_calendar_rejects_source_contract_drift(tmp_path: Path) -> None:
    export = tmp_path / "calendar.csv"
    row = _row("840030005", "1001", actual="0.5", forecast="0.4")
    row["event_name"] = "Renamed CPI"
    _write_export(export, [row])

    with pytest.raises(ValueError, match="contract drift"):
        parse_mt5_calendar_export(
            export,
            server_utc_offset_seconds=10_800,
            timezone_policy=MT5_KE_TIMEZONE_POLICY,
        )
