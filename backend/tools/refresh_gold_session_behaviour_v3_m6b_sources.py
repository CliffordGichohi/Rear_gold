from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from gold_intel.application.public_data import (
    _ensure_catalog,
    _persist_observations,
)
from gold_intel.infrastructure.database import session_factory
from gold_intel.providers.public_data import (
    FRED_CSV_URL,
    FRED_MARKET_SERIES,
    PublicDataProvider,
)

AUTHORIZED_SERIES = (
    "US_VOLATILITY_INDEX",
    "US_FINANCIAL_STRESS",
)
REFRESH_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6B_SOURCE_REFRESH_V0_1"


async def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    raw_store_root = (root / args.raw_store).resolve()
    _assert_within(root, raw_store_root)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start > end:
        raise ValueError("start must not follow end")
    if end > date(2026, 7, 29):
        raise ValueError("M6B source refresh cannot pass 2026-07-29")
    if "fred.stlouisfed.org" not in FRED_CSV_URL:
        raise ValueError("Only the free FRED public graph endpoint is authorized")

    specifications = tuple(
        specification
        for specification in FRED_MARKET_SERIES
        if specification.internal_code in AUTHORIZED_SERIES
    )
    if tuple(item.internal_code for item in specifications) != AUTHORIZED_SERIES:
        raise ValueError("Authorized FRED series registry mismatch")

    adapter = PublicDataProvider()
    records = []
    async with httpx.AsyncClient(
        timeout=adapter._timeout,  # noqa: SLF001 - bounded research adapter reuse
        follow_redirects=True,
    ) as client:
        for specification in specifications:
            records.extend(
                await adapter._fetch_fred_series(  # noqa: SLF001
                    client,
                    spec=specification,
                    start=start,
                    end=end,
                )
            )
    records.sort(key=lambda item: (item.series_code, item.observation_time))
    if {item.series_code for item in records} - set(AUTHORIZED_SERIES):
        raise ValueError("Unauthorized series returned by targeted refresh")

    async with session_factory() as session:
        await _ensure_catalog(session)
        batch, duplicate, inserted = await _persist_observations(
            session,
            raw_store_root=raw_store_root,
            records=tuple(records),
            start=start,
            end=end,
        )
        await session.commit()

    fetched_by_series = {
        code: sum(item.series_code == code for item in records)
        for code in AUTHORIZED_SERIES
    }
    result: dict[str, Any] = {
        "refresh_version": REFRESH_VERSION,
        "authorized_free_endpoint": FRED_CSV_URL,
        "paid_acquisition": False,
        "series": list(AUTHORIZED_SERIES),
        "requested_start": start.isoformat(),
        "requested_end_inclusive": end.isoformat(),
        "fetched_record_counts": fetched_by_series,
        "inserted_observations": inserted,
        "duplicate_batch": duplicate,
        "batch_id": str(batch.id),
        "batch_content_hash": batch.content_hash,
        "raw_object_path": batch.raw_object_path,
        "values_printed_or_human_inspected": False,
        "record_payload_fields": sorted(
            set().union(*(asdict(record).keys() for record in records))
        )
        if records
        else [],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def _assert_within(root: Path, path: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError(f"Path must remain inside repository root: {path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh only the two free public series authorized for V3 "
            "Milestone 6B; never emit market values."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--raw-store", default="data/raw")
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--end", default="2026-07-29")
    return parser


if __name__ == "__main__":
    asyncio.run(main())
