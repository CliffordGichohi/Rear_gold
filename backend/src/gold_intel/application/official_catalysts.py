from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.application.economic_events import (
    EventBundleIngestionResult,
    ingest_economic_event_bundle,
)
from gold_intel.infrastructure.models import Provider
from gold_intel.providers.official_catalysts import (
    FEDERAL_RESERVE_DATASET_CODE,
    FEDERAL_RESERVE_PROVIDER_CODE,
    US_TREASURY_DATASET_CODE,
    US_TREASURY_PROVIDER_CODE,
    OfficialCatalystProvider,
    fed_communication_event_payload,
    treasury_event_payload,
)


@dataclass(frozen=True, slots=True)
class OfficialCatalystSyncResult:
    start: date
    end: date
    retrieved_at: datetime
    fetched_treasury_auctions: int
    inserted_treasury_auctions: int
    treasury_batch_id: UUID | None
    treasury_duplicate_batch: bool | None
    fetched_fed_communications: int
    inserted_fed_communications: int
    fed_batch_id: UUID | None
    fed_duplicate_batch: bool | None


async def sync_official_catalysts(
    session: AsyncSession,
    *,
    raw_store_root: Path,
    start: date,
    end: date,
    provider: OfficialCatalystProvider | None = None,
) -> OfficialCatalystSyncResult:
    adapter = provider or OfficialCatalystProvider()
    dataset = await adapter.fetch(start=start, end=end)

    treasury_raw_path = _persist_raw(
        raw_store_root=raw_store_root,
        provider_code=US_TREASURY_PROVIDER_CODE,
        dataset_code=US_TREASURY_DATASET_CODE,
        content_hash=dataset.treasury_source_sha256,
        filename="source.json",
        payload=dataset.treasury_raw_bytes,
    )
    speeches_raw_path = _persist_raw(
        raw_store_root=raw_store_root,
        provider_code=FEDERAL_RESERVE_PROVIDER_CODE,
        dataset_code="SPEECHES_RSS",
        content_hash=dataset.fed_speeches_source_sha256,
        filename="source.xml",
        payload=dataset.fed_speeches_raw_bytes,
    )
    monetary_raw_path = _persist_raw(
        raw_store_root=raw_store_root,
        provider_code=FEDERAL_RESERVE_PROVIDER_CODE,
        dataset_code="MONETARY_POLICY_RSS",
        content_hash=dataset.fed_monetary_source_sha256,
        filename="source.xml",
        payload=dataset.fed_monetary_raw_bytes,
    )

    await _ensure_official_provider(
        session,
        code=US_TREASURY_PROVIDER_CODE,
        name="U.S. Treasury Fiscal Data",
        source_url="https://fiscaldata.treasury.gov/",
        timing_contract=(
            "Auction competitive close is converted from America/New_York. "
            "Announcement availability is conservatively end-of-day New York "
            "because the dataset exposes a date but no announcement timestamp."
        ),
    )
    await _ensure_official_provider(
        session,
        code=FEDERAL_RESERVE_PROVIDER_CODE,
        name="Federal Reserve Board RSS",
        source_url="https://www.federalreserve.gov/feeds/feeds.htm",
        timing_contract=(
            "RSS pubDate is exact release availability. The feed describes "
            "published communications and is not a forward speech calendar."
        ),
    )

    auctions = tuple(
        auction
        for auction in dataset.treasury_auctions
        if start <= auction.auction_date <= end
    )
    communications = tuple(
        communication
        for communication in dataset.fed_communications
        if start <= communication.published_at.date() <= end
    )

    treasury_result: EventBundleIngestionResult | None = None
    if auctions:
        treasury_events = [
            treasury_event_payload(
                auction,
                source_url=dataset.treasury_source_url,
                source_sha256=dataset.treasury_source_sha256,
                raw_object_path=str(treasury_raw_path),
            )
            for auction in auctions
        ]
        treasury_result = await ingest_economic_event_bundle(
            session,
            payload={
                "provider_code": US_TREASURY_PROVIDER_CODE,
                "dataset_code": US_TREASURY_DATASET_CODE,
                "schema_version": "1.0",
                "is_synthetic": False,
                "source_published_at": max(
                    auction.available_at for auction in auctions
                ),
                "events": treasury_events,
            },
            raw_store_root=raw_store_root,
        )

    fed_result: EventBundleIngestionResult | None = None
    if communications:
        fed_events = []
        for communication in communications:
            is_speech = communication.event_type in {"FED_SPEECH", "FED_TESTIMONY"}
            fed_events.append(
                fed_communication_event_payload(
                    communication,
                    source_url=(
                        dataset.fed_speeches_source_url
                        if is_speech
                        else dataset.fed_monetary_source_url
                    ),
                    source_sha256=(
                        dataset.fed_speeches_source_sha256
                        if is_speech
                        else dataset.fed_monetary_source_sha256
                    ),
                    raw_object_path=str(
                        speeches_raw_path if is_speech else monetary_raw_path
                    ),
                )
            )
        fed_result = await ingest_economic_event_bundle(
            session,
            payload={
                "provider_code": FEDERAL_RESERVE_PROVIDER_CODE,
                "dataset_code": FEDERAL_RESERVE_DATASET_CODE,
                "schema_version": "1.0",
                "is_synthetic": False,
                "source_published_at": max(
                    communication.published_at for communication in communications
                ),
                "events": fed_events,
            },
            raw_store_root=raw_store_root,
        )

    return OfficialCatalystSyncResult(
        start=start,
        end=end,
        retrieved_at=dataset.retrieved_at,
        fetched_treasury_auctions=len(auctions),
        inserted_treasury_auctions=(
            treasury_result.event_count if treasury_result is not None else 0
        ),
        treasury_batch_id=(
            treasury_result.batch.id if treasury_result is not None else None
        ),
        treasury_duplicate_batch=(
            treasury_result.duplicate if treasury_result is not None else None
        ),
        fetched_fed_communications=len(communications),
        inserted_fed_communications=(
            fed_result.event_count if fed_result is not None else 0
        ),
        fed_batch_id=fed_result.batch.id if fed_result is not None else None,
        fed_duplicate_batch=fed_result.duplicate if fed_result is not None else None,
    )


async def _ensure_official_provider(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    source_url: str,
    timing_contract: str,
) -> None:
    if await session.get(Provider, code) is not None:
        return
    session.add(
        Provider(
            code=code,
            name=name,
            provider_type="OFFICIAL_PUBLIC_CATALYST_FEED",
            license_class="OFFICIAL_PUBLIC",
            enabled=True,
            metadata_json={
                "source_url": source_url,
                "point_in_time_policy": timing_contract,
            },
        )
    )
    await session.flush()


def _persist_raw(
    *,
    raw_store_root: Path,
    provider_code: str,
    dataset_code: str,
    content_hash: str,
    filename: str,
    payload: bytes,
) -> Path:
    destination = (
        raw_store_root
        / provider_code.lower()
        / dataset_code.lower()
        / content_hash
        / filename
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(payload)
    return destination
