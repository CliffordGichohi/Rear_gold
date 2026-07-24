import json
from datetime import UTC, date, datetime

import httpx

from gold_intel.providers.official_catalysts import (
    OfficialCatalystProvider,
    fed_communication_event_payload,
    parse_federal_reserve_rss,
    parse_treasury_auction_response,
    treasury_event_payload,
)


def _treasury_payload() -> bytes:
    return json.dumps(
        {
            "data": [
                {
                    "record_date": "2026-07-31",
                    "cusip": "91282CRB9",
                    "security_type": "Note",
                    "security_term": "2-Year",
                    "auction_date": "2026-07-27",
                    "announcemt_date": "2026-07-23",
                    "closing_time_comp": "11:30 AM",
                    "closing_time_noncomp": "11:00 AM",
                    "offering_amt": "69000000000",
                    "pdf_filenm_announcemt": "A_20260723_1.pdf",
                }
            ]
        }
    ).encode()


def _rss(
    *,
    title: str,
    category: str,
    path: str,
    published: str,
) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel><title>FRB</title><item>'
        f"<title>{title}</title>"
        f"<link>https://www.federalreserve.gov/{path}</link>"
        f"<guid>https://www.federalreserve.gov/{path}</guid>"
        f"<description>{title}</description>"
        f"<category>{category}</category>"
        f"<pubDate>{published}</pubDate>"
        "</item></channel></rss>"
    ).encode()


def test_treasury_calendar_uses_dst_and_conservative_announcement_availability() -> None:
    auctions = parse_treasury_auction_response(_treasury_payload())

    assert len(auctions) == 1
    auction = auctions[0]
    assert auction.auction_date == date(2026, 7, 27)
    # 11:30 New York is 15:30 UTC during daylight-saving time.
    assert auction.competitive_close_at == datetime(2026, 7, 27, 15, 30, tzinfo=UTC)
    # The source gives only an announcement date, so availability is end-of-day ET.
    assert auction.available_at == datetime(
        2026,
        7,
        24,
        3,
        59,
        59,
        999999,
        tzinfo=UTC,
    )
    event = treasury_event_payload(
        auction,
        source_url="https://api.fiscaldata.treasury.gov/example",
        source_sha256="a" * 64,
        raw_object_path="raw/treasury/source.json",
    )
    assert event["status"] == "SCHEDULED"
    assert event["importance"] == 4
    assert event["metadata"]["time_semantics"] == "COMPETITIVE_BID_CLOSE_ET"


def test_fed_rss_is_released_metadata_not_a_forward_calendar() -> None:
    communications = parse_federal_reserve_rss(
        _rss(
            title=(
                "Federal Reserve Board and Federal Open Market Committee "
                "release economic projections"
            ),
            category="Monetary Policy",
            path="newsevents/pressreleases/monetary20260617b.htm",
            published="Wed, 17 Jun 2026 18:00:00 GMT",
        ),
        expected_category="MONETARY_POLICY",
    )

    assert len(communications) == 1
    communication = communications[0]
    assert communication.event_type == "FOMC_PROJECTIONS"
    assert communication.importance == 5
    event = fed_communication_event_payload(
        communication,
        source_url="https://www.federalreserve.gov/feeds/press_monetary.xml",
        source_sha256="b" * 64,
        raw_object_path="raw/fed/source.xml",
    )
    assert event["status"] == "RELEASED"
    assert event["is_scheduled"] is False
    assert event["metadata"]["forward_calendar_eligible"] is False
    assert event["metadata"]["directional_interpretation"] == "UNKNOWN"


async def test_provider_calls_only_documented_official_sources() -> None:
    speech_rss = _rss(
        title="Waller, Monetary Policy at a Crossroads",
        category="Speech",
        path="newsevents/speech/waller20260713a.htm",
        published="Mon, 13 Jul 2026 16:30:00 GMT",
    )
    monetary_rss = _rss(
        title="Federal Reserve issues FOMC statement",
        category="Monetary Policy",
        path="newsevents/pressreleases/monetary20260617a.htm",
        published="Wed, 17 Jun 2026 18:00:00 GMT",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auctions_query"):
            assert request.url.params["filter"] == (
                "auction_date:gte:2026-07-01,auction_date:lte:2026-07-31"
            )
            assert "closing_time_comp" in request.url.params["fields"]
            return httpx.Response(200, content=_treasury_payload())
        if request.url.path.endswith("/speeches.xml"):
            return httpx.Response(200, content=speech_rss)
        if request.url.path.endswith("/press_monetary.xml"):
            return httpx.Response(200, content=monetary_rss)
        return httpx.Response(404)

    dataset = await OfficialCatalystProvider(
        transport=httpx.MockTransport(handler)
    ).fetch(
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        retrieved_at=datetime(2026, 7, 24, 12, tzinfo=UTC),
    )

    assert len(dataset.treasury_auctions) == 1
    assert len(dataset.fed_communications) == 2
    assert dataset.fed_communications[-1].event_type == "FED_SPEECH"
    assert dataset.retrieved_at == datetime(2026, 7, 24, 12, tzinfo=UTC)
