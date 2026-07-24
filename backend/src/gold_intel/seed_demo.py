from __future__ import annotations

import asyncio
import csv
import json
import math
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.application.intelligence import calculate_intelligence
from gold_intel.config import get_settings
from gold_intel.infrastructure.database import session_factory
from gold_intel.infrastructure.models import Instrument, Provider, Series
from gold_intel.ingestion.service import (
    PRICE_DATASET,
    REAL_YIELD_DATASET,
    ingest_csv_path,
)

UTC = UTC
CALCULATION_AS_OF = datetime(2026, 7, 17, 16, 0, tzinfo=UTC)


async def seed_demo() -> dict[str, object]:
    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="gold-intel-seed-") as temp_dir:
        temp_root = Path(temp_dir)
        price_path = temp_root / "xauusd_1m.v1.csv"
        real_yield_path = temp_root / "us_real_yield_10y_daily.v1.csv"
        _write_price_fixture(price_path)
        _write_real_yield_fixture(real_yield_path)

        async with session_factory() as session:
            async with session.begin():
                await _seed_catalog(session)
                price = await ingest_csv_path(
                    session,
                    source_path=price_path,
                    original_filename=price_path.name,
                    raw_store_root=Path(settings.raw_store_path),
                    provider_code="DEMO_XAUUSD",
                    dataset_code=PRICE_DATASET,
                    schema_version="1",
                    is_synthetic=True,
                )
                real_yield = await ingest_csv_path(
                    session,
                    source_path=real_yield_path,
                    original_filename=real_yield_path.name,
                    raw_store_root=Path(settings.raw_store_path),
                    provider_code="DEMO_MACRO",
                    dataset_code=REAL_YIELD_DATASET,
                    schema_version="1",
                    is_synthetic=True,
                )
            async with session.begin():
                snapshot = await calculate_intelligence(
                    session, instrument_code="XAUUSD", as_of=CALCULATION_AS_OF
                )

        return {
            "price_batch_id": str(price.batch.id),
            "price_duplicate": price.duplicate,
            "price_records": price.valid_records,
            "real_yield_batch_id": str(real_yield.batch.id),
            "real_yield_duplicate": real_yield.duplicate,
            "real_yield_records": real_yield.valid_records,
            "snapshot_id": str(snapshot.id),
            "as_of": snapshot.as_of.isoformat(),
            "bias": snapshot.bias_label,
            "score": float(snapshot.overall_score),
            "coverage": float(snapshot.coverage),
        }


async def _seed_catalog(session: AsyncSession) -> None:
    await session.merge(
        Provider(
            code="DEMO_XAUUSD",
            name="Synthetic XAUUSD Fixture",
            provider_type="FILE",
            license_class="SYNTHETIC",
            enabled=True,
            metadata_json={"volume_scope": "TICK", "global_volume": False},
        )
    )
    await session.merge(
        Provider(
            code="DEMO_MACRO",
            name="Synthetic Macro Fixture",
            provider_type="FILE",
            license_class="SYNTHETIC",
            enabled=True,
            metadata_json={},
        )
    )
    await session.merge(
        Instrument(
            code="XAUUSD",
            name="Gold / US Dollar",
            asset_class="COMMODITY_CFD_REFERENCE",
            price_currency="USD",
            tick_size=0.01,
            metadata_json={"fragmented_spot_market": True},
        )
    )
    await session.merge(
        Series(
            code="US_REAL_YIELD_10Y",
            name="United States 10-Year Real Yield",
            unit="PERCENT",
            frequency="DAILY",
            expected_lag_seconds=0,
            metadata_json={"synthetic_fixture": True},
        )
    )


def _write_price_fixture(path: Path) -> None:
    start = CALCULATION_AS_OF - timedelta(days=5)
    total_minutes = 5 * 24 * 60
    rows: list[dict[str, str]] = []
    prior_close = 2380.0
    for index in range(total_minutes):
        if index == 100:
            continue
        open_time = start + timedelta(minutes=index)
        close_time = open_time + timedelta(minutes=1)
        baseline = 2380 + index * 0.004 + math.sin(index / 29) * 0.18
        close = baseline + math.sin(index / 7) * 0.035
        open_price = prior_close
        high = max(open_price, close) + 0.08
        low = min(open_price, close) - 0.08
        prior_close = close
        rows.append(
            {
                "open_time": open_time.isoformat(),
                "close_time": close_time.isoformat(),
                "open": f"{open_price:.4f}",
                "high": f"{high:.4f}",
                "low": f"{low:.4f}",
                "close": f"{close:.4f}",
                "volume": str(100 + index % 37),
                "volume_type": "TICK",
                "available_at": close_time.isoformat(),
            }
        )

    _overlay_acceptance_sequence(rows)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _overlay_acceptance_sequence(rows: list[dict[str, str]]) -> None:
    group_closes = [
        2411.0,
        2412.0,
        2413.0,
        2415.0,
        2413.4,
        2412.8,
        2413.0,
        2413.2,
        2413.4,
        2413.6,
        2413.8,
        2414.0,
        2414.1,
        2416.2,
        2417.0,
    ]
    start = len(rows) - len(group_closes) * 5
    prior_close = float(rows[start - 1]["close"])
    for group_index, group_close in enumerate(group_closes):
        for minute in range(5):
            row = rows[start + group_index * 5 + minute]
            fraction = (minute + 1) / 5
            close = prior_close + (group_close - prior_close) * fraction
            open_price = (
                prior_close
                if minute == 0
                else float(rows[start + group_index * 5 + minute - 1]["close"])
            )
            high = max(open_price, close) + 0.10
            low = min(open_price, close) - 0.10
            if group_index == 3 and minute == 2:
                high = 2415.55
            row.update(
                {
                    "open": f"{open_price:.4f}",
                    "high": f"{high:.4f}",
                    "low": f"{low:.4f}",
                    "close": f"{close:.4f}",
                }
            )
        prior_close = group_close


def _write_real_yield_fixture(path: Path) -> None:
    dates: list[datetime] = []
    candidate = datetime(2026, 3, 16, 0, 0, tzinfo=UTC)
    while len(dates) < 90:
        if candidate.weekday() < 5:
            dates.append(candidate)
        candidate += timedelta(days=1)
    rows: list[dict[str, str]] = []
    for index, observation_time in enumerate(dates):
        value = 2.30 - index * 0.002
        if index >= len(dates) - 6:
            value = 2.10 - (index - (len(dates) - 6)) * 0.03
        available_at = observation_time.replace(hour=13)
        rows.append(
            {
                "observation_time": observation_time.isoformat(),
                "value_percent": f"{value:.4f}",
                "available_at": available_at.isoformat(),
                "vintage": "initial",
                "is_revision": "false",
            }
        )

    revised_period = dates[-3]
    rows.append(
        {
            "observation_time": revised_period.isoformat(),
            "value_percent": "2.9900",
            "available_at": (CALCULATION_AS_OF + timedelta(days=1)).isoformat(),
            "vintage": "revision-1",
            "is_revision": "true",
        }
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    print(json.dumps(asyncio.run(seed_demo()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
