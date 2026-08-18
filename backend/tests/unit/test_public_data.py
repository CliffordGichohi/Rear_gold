from datetime import date

import httpx

from gold_intel.providers.public_data import FRED_MARKET_SERIES, PublicDataProvider


async def test_fred_adapter_enforces_requested_dates_when_upstream_ignores_them() -> None:
    csv_payload = (
        "observation_date,DGS2\n"
        "2022-12-30,4.41\n"
        "2026-07-20,4.21\n"
        "2026-07-23,4.37\n"
        "2026-07-28,4.40\n"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["cosd"] == "2026-07-20"
        assert request.url.params["coed"] == "2026-07-27"
        return httpx.Response(200, text=csv_payload)

    provider = PublicDataProvider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await provider._fetch_fred_series(
            client,
            spec=FRED_MARKET_SERIES[0],
            start=date(2026, 7, 20),
            end=date(2026, 7, 27),
        )

    assert [row.observation_time.date() for row in rows] == [
        date(2026, 7, 20),
        date(2026, 7, 23),
    ]
