from datetime import UTC, date, datetime

import httpx
import pytest

from gold_intel.api.schemas import EconomicEventBundleRequest
from gold_intel.application.trading_economics import trading_economics_bundle
from gold_intel.providers.trading_economics import (
    TradingEconomicsCalendarProvider,
)


@pytest.mark.asyncio
async def test_calendar_normalizes_historical_and_live_point_in_time_clocks() -> None:
    retrieved_at = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["c"] == "test-key"
        assert request.url.params["values"] == "true"
        return httpx.Response(
            200,
            json=[
                {
                    "CalendarId": "100",
                    "Date": "2026-06-10T12:30:00",
                    "Country": "United States",
                    "Category": "Core Inflation Rate MoM",
                    "Event": "Core Inflation Rate MoM",
                    "ReferenceDate": "2026-05-31T00:00:00",
                    "Actual": "0.2%",
                    "Previous": "0.3%",
                    "Forecast": "0.3%",
                    "ActualValue": 0.2,
                    "PreviousValue": 0.3,
                    "ForecastValue": 0.3,
                    "Importance": 3,
                    "LastUpdate": "2026-06-10T12:30:02",
                    "Revised": "0.4%",
                    "Unit": "%",
                },
                {
                    "CalendarId": "101",
                    "Date": "2026-07-03T12:30:00",
                    "Country": "United States",
                    "Category": "Non Farm Payrolls",
                    "Event": "Non Farm Payrolls",
                    "ReferenceDate": "2026-06-30T00:00:00",
                    "Actual": "",
                    "Previous": "150K",
                    "Forecast": "175K",
                    "ActualValue": None,
                    "PreviousValue": 150000,
                    "ForecastValue": 175000,
                    "Importance": 3,
                    "LastUpdate": "2026-06-19T15:00:00",
                    "Revised": "",
                    "Unit": "K",
                },
                {
                    "CalendarId": "102",
                    "Date": "2026-06-15T14:00:00",
                    "Country": "United States",
                    "Category": "Manufacturing PMI",
                    "Event": "Manufacturing PMI",
                    "Importance": 2,
                },
            ],
        )

    provider = TradingEconomicsCalendarProvider(
        api_key="test-key",
        request_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    calendar = await provider.fetch(
        start=date(2026, 6, 1),
        end=date(2026, 7, 10),
        retrieved_at=retrieved_at,
    )

    assert calendar.fetched_count == 3
    assert calendar.excluded_count == 1
    assert len(calendar.events) == 2
    cpi = next(event for event in calendar.events if event.component_code == "CPI_CORE_MOM")
    assert cpi.status == "RELEASED"
    assert cpi.forecast_available_at == cpi.scheduled_at
    assert cpi.release_available_at == datetime(2026, 6, 10, 12, 30, 2, tzinfo=UTC)
    assert cpi.previous_value == pytest.approx(0.4)
    assert cpi.revised_previous_value == pytest.approx(0.3)
    assert cpi.availability_quality == "HISTORICAL_RELEASE_BOUNDARY"

    payrolls = next(event for event in calendar.events if event.component_code == "NFP_CHANGE")
    assert payrolls.status == "SCHEDULED"
    assert payrolls.event_available_at == retrieved_at
    assert payrolls.forecast_available_at == retrieved_at
    assert payrolls.forecast_value == pytest.approx(175)
    assert payrolls.previous_value == pytest.approx(150)
    assert payrolls.unit == "THOUSANDS"

    parsed = EconomicEventBundleRequest.model_validate(trading_economics_bundle(calendar))
    assert len(parsed.events) == 2
    assert parsed.events[0].forecasts[0].available_at <= (
        parsed.events[0].released_at or parsed.events[0].scheduled_at
    )


@pytest.mark.asyncio
async def test_calendar_rejects_discontinued_or_unentitled_credentials() -> None:
    provider = TradingEconomicsCalendarProvider(
        api_key="guest:guest",
        request_interval_seconds=0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                410,
                text="The guest account has been discontinued.",
            )
        ),
    )

    with pytest.raises(ValueError, match="rejected the API key"):
        await provider.fetch(
            start=date(2026, 6, 1),
            end=date(2026, 6, 2),
        )
