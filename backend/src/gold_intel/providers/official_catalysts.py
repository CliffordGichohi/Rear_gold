from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

US_TREASURY_PROVIDER_CODE = "US_TREASURY_FISCAL_DATA"
US_TREASURY_DATASET_CODE = "TREASURY_AUCTION_CALENDAR"
FEDERAL_RESERVE_PROVIDER_CODE = "FEDERAL_RESERVE_RSS"
FEDERAL_RESERVE_DATASET_CODE = "FED_COMMUNICATIONS"

TREASURY_AUCTIONS_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
    "v1/accounting/od/auctions_query"
)
FED_SPEECHES_RSS_URL = "https://www.federalreserve.gov/feeds/speeches.xml"
FED_MONETARY_POLICY_RSS_URL = (
    "https://www.federalreserve.gov/feeds/press_monetary.xml"
)

_NEW_YORK = ZoneInfo("America/New_York")
_TREASURY_FIELDS = (
    "record_date",
    "cusip",
    "security_type",
    "security_term",
    "auction_date",
    "announcemt_date",
    "closing_time_comp",
    "closing_time_noncomp",
    "offering_amt",
    "pdf_filenm_announcemt",
)
_FED_METADATA_ONLY_EVENT_TYPES = frozenset(
    {
        "FED_SPEECH",
        "FED_TESTIMONY",
        "FED_MONETARY_POLICY_RELEASE",
        "FOMC_MINUTES",
        "FOMC_PROJECTIONS",
        "FOMC_STATEMENT",
    }
)


@dataclass(frozen=True, slots=True)
class TreasuryAuction:
    cusip: str
    security_type: str
    security_term: str
    auction_date: date
    competitive_close_at: datetime
    noncompetitive_close_at: datetime | None
    announcement_date: date
    available_at: datetime
    offering_amount_usd: int | None
    announcement_pdf_filename: str | None
    source_record_key: str


@dataclass(frozen=True, slots=True)
class FedCommunication:
    title: str
    description: str
    category: str
    url: str
    published_at: datetime
    event_type: str
    importance: int
    source_record_key: str


@dataclass(frozen=True, slots=True)
class OfficialCatalystDataset:
    retrieved_at: datetime
    treasury_source_url: str
    treasury_source_sha256: str
    treasury_raw_bytes: bytes
    fed_speeches_source_url: str
    fed_speeches_source_sha256: str
    fed_speeches_raw_bytes: bytes
    fed_monetary_source_url: str
    fed_monetary_source_sha256: str
    fed_monetary_raw_bytes: bytes
    treasury_auctions: tuple[TreasuryAuction, ...]
    fed_communications: tuple[FedCommunication, ...]


class OfficialCatalystProvider:
    """Official, credential-free U.S. Treasury and Federal Reserve adapter.

    Treasury rows provide a forward auction calendar with an exact competitive
    close in Eastern Time. Federal Reserve RSS feeds provide exact publication
    timestamps for already-released communications; they are deliberately not
    treated as a forward speech calendar.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._transport = transport

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def fetch(
        self,
        *,
        start: date,
        end: date,
        retrieved_at: datetime | None = None,
    ) -> OfficialCatalystDataset:
        if start > end:
            raise ValueError("official catalyst start cannot follow end")
        retrieval_clock = (retrieved_at or datetime.now(UTC)).astimezone(UTC)
        treasury_params = {
            "filter": f"auction_date:gte:{start.isoformat()},auction_date:lte:{end.isoformat()}",
            "fields": ",".join(_TREASURY_FIELDS),
            "sort": "auction_date,cusip",
            "format": "json",
            "page[size]": "10000",
        }
        headers = {
            "Accept": "application/json, application/rss+xml, application/xml",
            "User-Agent": "gold-market-intelligence-engine/0.1.0",
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            treasury_response, speeches_response, monetary_response = await asyncio.gather(
                client.get(TREASURY_AUCTIONS_URL, params=treasury_params, headers=headers),
                client.get(FED_SPEECHES_RSS_URL, headers=headers),
                client.get(FED_MONETARY_POLICY_RSS_URL, headers=headers),
            )
        for response in (treasury_response, speeches_response, monetary_response):
            response.raise_for_status()

        treasury_bytes = treasury_response.content
        speech_bytes = speeches_response.content
        monetary_bytes = monetary_response.content
        auctions = parse_treasury_auction_response(treasury_bytes)
        communications = tuple(
            sorted(
                (
                    *parse_federal_reserve_rss(speech_bytes, expected_category="SPEECH"),
                    *parse_federal_reserve_rss(
                        monetary_bytes,
                        expected_category="MONETARY_POLICY",
                    ),
                ),
                key=lambda item: (item.published_at, item.source_record_key),
            )
        )
        return OfficialCatalystDataset(
            retrieved_at=retrieval_clock,
            treasury_source_url=str(treasury_response.request.url),
            treasury_source_sha256=hashlib.sha256(treasury_bytes).hexdigest(),
            treasury_raw_bytes=treasury_bytes,
            fed_speeches_source_url=FED_SPEECHES_RSS_URL,
            fed_speeches_source_sha256=hashlib.sha256(speech_bytes).hexdigest(),
            fed_speeches_raw_bytes=speech_bytes,
            fed_monetary_source_url=FED_MONETARY_POLICY_RSS_URL,
            fed_monetary_source_sha256=hashlib.sha256(monetary_bytes).hexdigest(),
            fed_monetary_raw_bytes=monetary_bytes,
            treasury_auctions=auctions,
            fed_communications=communications,
        )


def parse_treasury_auction_response(payload: bytes) -> tuple[TreasuryAuction, ...]:
    if not payload:
        raise ValueError("Treasury auction response is empty.")
    try:
        document = httpx.Response(200, content=payload).json()
    except ValueError as exc:
        raise ValueError("Treasury auction response is not valid JSON.") from exc
    rows = document.get("data") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Treasury auction response has no data array.")

    auctions: list[TreasuryAuction] = []
    keys: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Treasury auction row {row_number} is not an object.")
        try:
            cusip = _required_text(row, "cusip")
            security_type = _required_text(row, "security_type")
            security_term = _required_text(row, "security_term")
            auction_date = date.fromisoformat(_required_text(row, "auction_date"))
            announcement_date = date.fromisoformat(
                _required_text(row, "announcemt_date")
            )
            competitive_close = _new_york_timestamp(
                auction_date,
                _required_text(row, "closing_time_comp"),
            )
            noncompetitive_text = _optional_text(row.get("closing_time_noncomp"))
            noncompetitive_close = (
                _new_york_timestamp(auction_date, noncompetitive_text)
                if noncompetitive_text is not None
                else None
            )
            offering_amount = _optional_integer(row.get("offering_amt"))
            announcement_filename = _optional_text(row.get("pdf_filenm_announcemt"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid Treasury auction row {row_number}.") from exc

        # The API exposes the announcement date but not its publication time.
        # End-of-day New York availability is conservative for historical replay.
        available_at = datetime.combine(
            announcement_date,
            time.max,
            _NEW_YORK,
        ).astimezone(UTC)
        key = (
            f"TREASURY_AUCTION:{cusip}:{auction_date.isoformat()}:"
            f"{competitive_close.isoformat()}"
        )
        if key in keys:
            raise ValueError(f"Duplicate Treasury auction source key at row {row_number}.")
        keys.add(key)
        auctions.append(
            TreasuryAuction(
                cusip=cusip,
                security_type=security_type,
                security_term=security_term,
                auction_date=auction_date,
                competitive_close_at=competitive_close,
                noncompetitive_close_at=noncompetitive_close,
                announcement_date=announcement_date,
                available_at=available_at,
                offering_amount_usd=offering_amount,
                announcement_pdf_filename=announcement_filename,
                source_record_key=key,
            )
        )
    return tuple(
        sorted(
            auctions,
            key=lambda item: (item.competitive_close_at, item.cusip),
        )
    )


def parse_federal_reserve_rss(
    payload: bytes,
    *,
    expected_category: str,
) -> tuple[FedCommunication, ...]:
    if expected_category not in {"SPEECH", "MONETARY_POLICY"}:
        raise ValueError("unsupported Federal Reserve RSS category")
    if not payload:
        raise ValueError("Federal Reserve RSS response is empty.")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError("Federal Reserve RSS response is not valid XML.") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("Federal Reserve RSS response has no RSS channel.")

    communications: list[FedCommunication] = []
    keys: set[str] = set()
    for item_number, item in enumerate(channel.findall("item"), start=1):
        title = _xml_text(item, "title")
        description = _xml_text(item, "description")
        category = _xml_text(item, "category")
        link = _xml_text(item, "link")
        guid = _xml_text(item, "guid")
        published_text = _xml_text(item, "pubDate")
        if not all((title, link, guid, published_text)):
            raise ValueError(
                f"Federal Reserve RSS item {item_number} lacks a required field."
            )
        if not link.startswith("https://www.federalreserve.gov/"):
            raise ValueError(
                f"Federal Reserve RSS item {item_number} has an unexpected link host."
            )
        try:
            published_at = parsedate_to_datetime(published_text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Federal Reserve RSS item {item_number} has an invalid pubDate."
            ) from exc
        if published_at.tzinfo is None:
            raise ValueError(
                f"Federal Reserve RSS item {item_number} pubDate lacks a timezone."
            )
        published_at = published_at.astimezone(UTC)
        key = guid
        if key in keys:
            raise ValueError(f"Duplicate Federal Reserve RSS guid at item {item_number}.")
        keys.add(key)
        event_type, importance = _fed_event_classification(
            title=title,
            category=expected_category,
        )
        communications.append(
            FedCommunication(
                title=title,
                description=description,
                category=category,
                url=link,
                published_at=published_at,
                event_type=event_type,
                importance=importance,
                source_record_key=key,
            )
        )
    return tuple(communications)


def treasury_event_payload(
    auction: TreasuryAuction,
    *,
    source_url: str,
    source_sha256: str,
    raw_object_path: str,
) -> dict[str, object]:
    security_label = f"{auction.security_term} {auction.security_type}".strip()
    return {
        "event_code": "US_TREASURY_AUCTION",
        "name": f"U.S. Treasury {security_label} auction",
        "event_type": "TREASURY_AUCTION",
        "scheduled_at": auction.competitive_close_at,
        "released_at": None,
        "importance": _treasury_importance(auction),
        "is_scheduled": True,
        "status": "SCHEDULED",
        "source_event_key": auction.source_record_key,
        "available_at": auction.available_at,
        "forecasts": [],
        "releases": [],
        "metadata": {
            "epistemic_status": "OBSERVED",
            "time_semantics": "COMPETITIVE_BID_CLOSE_ET",
            "availability_quality": "ANNOUNCEMENT_DATE_END_OF_DAY_ET",
            "announcement_date": auction.announcement_date.isoformat(),
            "cusip": auction.cusip,
            "security_type": auction.security_type,
            "security_term": auction.security_term,
            "noncompetitive_close_at": (
                auction.noncompetitive_close_at.isoformat()
                if auction.noncompetitive_close_at is not None
                else None
            ),
            "offering_amount_usd": auction.offering_amount_usd,
            "announcement_pdf_filename": auction.announcement_pdf_filename,
            "source_url": source_url,
            "source_sha256": source_sha256,
            "raw_object_path": raw_object_path,
            "importance_method": "DETERMINISTIC_SECURITY_TERM_V1",
        },
    }


def fed_communication_event_payload(
    communication: FedCommunication,
    *,
    source_url: str,
    source_sha256: str,
    raw_object_path: str,
) -> dict[str, object]:
    return {
        "event_code": communication.event_type,
        "name": communication.title,
        "event_type": communication.event_type,
        "scheduled_at": communication.published_at,
        "released_at": communication.published_at,
        "importance": communication.importance,
        "is_scheduled": False,
        "status": "RELEASED",
        "source_event_key": communication.source_record_key,
        "available_at": communication.published_at,
        "forecasts": [],
        "releases": [],
        "metadata": {
            "epistemic_status": "OBSERVED",
            "time_semantics": "RSS_PUBLICATION_TIMESTAMP",
            "forward_calendar_eligible": False,
            "description": communication.description,
            "category": communication.category,
            "url": communication.url,
            "source_url": source_url,
            "source_sha256": source_sha256,
            "raw_object_path": raw_object_path,
            "importance_method": "DETERMINISTIC_COMMUNICATION_CLASS_V1",
            "directional_interpretation": "UNKNOWN",
        },
    }


def metadata_only_fed_event_types() -> frozenset[str]:
    return _FED_METADATA_ONLY_EVENT_TYPES


def _fed_event_classification(*, title: str, category: str) -> tuple[str, int]:
    normalized = title.casefold()
    if category == "MONETARY_POLICY":
        if "economic projections" in normalized:
            return "FOMC_PROJECTIONS", 5
        if "issues fomc statement" in normalized:
            return "FOMC_STATEMENT", 5
        if "minutes of the federal open market committee" in normalized:
            return "FOMC_MINUTES", 4
        return "FED_MONETARY_POLICY_RELEASE", 3
    if "testimony" in normalized:
        return "FED_TESTIMONY", 3
    high_relevance = (
        "monetary policy",
        "economic outlook",
        "inflation",
        "employment",
        "u.s. economy",
        "federal reserve",
    )
    importance = 4 if any(term in normalized for term in high_relevance) else 2
    if normalized.startswith("powell,") and importance < 4:
        importance = 3
    return "FED_SPEECH", importance


def _treasury_importance(auction: TreasuryAuction) -> int:
    normalized = f"{auction.security_term} {auction.security_type}".casefold()
    if any(term in normalized for term in ("10-year", "20-year", "30-year")):
        return 5
    if auction.security_type.casefold() in {"note", "bond", "tips"}:
        return 4
    if auction.security_type.casefold() in {"floating rate note", "frn"}:
        return 3
    return 2


def _required_text(row: dict[object, object], field: str) -> str:
    value = _optional_text(row.get(field))
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() == "null":
        return None
    return text


def _optional_integer(value: object) -> int | None:
    text = _optional_text(value)
    if text is None:
        return None
    parsed = int(text)
    if parsed < 0:
        raise ValueError("integer cannot be negative")
    return parsed


def _new_york_timestamp(value: date, clock: str) -> datetime:
    parsed_time = datetime.strptime(clock.strip().upper(), "%I:%M %p").time()
    return datetime.combine(value, parsed_time, _NEW_YORK).astimezone(UTC)


def _xml_text(item: ElementTree.Element, field: str) -> str:
    value = item.findtext(field)
    return (value or "").strip()
