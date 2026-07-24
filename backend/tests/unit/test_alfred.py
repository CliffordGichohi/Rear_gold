from datetime import UTC, date, datetime

import httpx
import pytest

from gold_intel.providers.alfred import (
    ALFRED_MACRO_SERIES,
    AlfredVintageProvider,
)


@pytest.mark.asyncio
async def test_alfred_provider_preserves_vintages_with_conservative_availability() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        series_id = request.url.params["series_id"]
        assert request.url.params["output_type"] == "1"
        assert request.url.params["api_key"] == "test-key"
        rows = [
            {
                "realtime_start": "2026-01-10",
                "realtime_end": "2026-02-09",
                "date": "2026-01-01",
                "value": "100.0",
            }
        ]
        if series_id == "CPIAUCSL":
            rows.append(
                {
                    "realtime_start": "2026-02-10",
                    "realtime_end": "9999-12-31",
                    "date": "2026-01-01",
                    "value": "100.1",
                }
            )
        return httpx.Response(
            200,
            json={"observations": rows},
            request=request,
        )

    provider = AlfredVintageProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    rows = await provider.fetch(
        start=date(2026, 1, 1),
        end=date(2026, 3, 1),
    )

    assert len(rows) == len(ALFRED_MACRO_SERIES) + 1
    cpi = [row for row in rows if row.series_code == "US_CPI_HEADLINE"]
    assert len(cpi) == 2
    assert not cpi[0].is_revision
    assert cpi[1].is_revision
    assert cpi[0].available_at == datetime(2026, 1, 11, 5, 0, tzinfo=UTC)
    assert cpi[1].available_at == datetime(2026, 2, 11, 5, 0, tzinfo=UTC)
    assert "test-key" not in str(cpi[0].payload)


def test_alfred_provider_requires_api_key() -> None:
    with pytest.raises(ValueError, match="FRED_API_KEY"):
        AlfredVintageProvider(api_key="")


@pytest.mark.asyncio
async def test_alfred_provider_rejects_empty_success_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": []}, request=request)

    provider = AlfredVintageProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ValueError, match="no eligible vintage observations"):
        await provider.fetch(
            start=date(2026, 1, 1),
            end=date(2026, 3, 1),
        )
