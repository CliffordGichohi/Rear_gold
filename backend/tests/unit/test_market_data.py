from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from gold_intel.api.routes.market_data import _select_canonical_observations
from gold_intel.infrastructure.models import Observation
from gold_intel.ingestion.service import (
    _insert_price_models_idempotently,
    _insert_raw_records,
    _parse_price_row,
)


def _observation(
    *,
    code: str,
    observed_at: datetime,
    available_at: datetime,
    value: str,
) -> Observation:
    return Observation(
        observation_time=observed_at,
        series_code=code,
        value=Decimal(value),
        unit="PERCENT",
        available_at=available_at,
        vintage=available_at.date().isoformat(),
        is_revision=available_at > observed_at + timedelta(days=1),
        supersedes_id=None,
        batch_id=uuid4(),
        source_record_key=f"{code}:{observed_at.date()}:{available_at.date()}",
        is_synthetic=False,
    )


def test_cross_market_observations_use_latest_eligible_vintage_and_limit() -> None:
    first = datetime(2026, 1, 1, tzinfo=UTC)
    second = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [
        _observation(
            code="US_REAL_YIELD_10Y",
            observed_at=first,
            available_at=first + timedelta(hours=1),
            value="1.80",
        ),
        _observation(
            code="US_REAL_YIELD_10Y",
            observed_at=first,
            available_at=first + timedelta(days=2),
            value="1.85",
        ),
        _observation(
            code="US_REAL_YIELD_10Y",
            observed_at=second,
            available_at=second + timedelta(hours=1),
            value="1.90",
        ),
        _observation(
            code="USD_BROAD_NOMINAL",
            observed_at=second,
            available_at=second + timedelta(hours=1),
            value="120",
        ),
    ]

    selected = _select_canonical_observations(
        rows,
        requested=("US_REAL_YIELD_10Y", "USD_BROAD_NOMINAL"),
        limit_per_series=1,
    )

    assert [(row.series_code, float(row.value)) for row in selected] == [
        ("USD_BROAD_NOMINAL", 120.0),
        ("US_REAL_YIELD_10Y", 1.9),
    ]


def test_mt5_price_row_preserves_observed_spread_with_versioned_point_size() -> None:
    row = {
        "open_time": "2026-07-24T14:59:00Z",
        "close_time": "2026-07-24T15:00:00Z",
        "available_at": "2026-07-24T15:00:00Z",
        "open": "2400.00",
        "high": "2400.50",
        "low": "2399.50",
        "close": "2400.25",
        "volume": "123",
        "volume_type": "TICK",
        "spread_points": "7",
    }

    bar = _parse_price_row(
        row,
        batch_id=uuid4(),
        provider_code="IC_MARKETS_MT5",
        is_synthetic=False,
    )

    assert bar.spread_points == 7
    assert bar.spread_price == Decimal("0.07")
    assert bar.volume == Decimal("123")
    assert bar.volume_type == "TICK"


def test_mt5_eurusd_row_uses_instrument_specific_point_size() -> None:
    row = {
        "open_time": "2022-01-05T00:00:00Z",
        "close_time": "2022-01-05T00:01:00Z",
        "available_at": "2022-01-05T00:01:00Z",
        "open": "1.12855",
        "high": "1.12860",
        "low": "1.12810",
        "close": "1.12818",
        "volume": "6",
        "volume_type": "TICK",
        "spread_points": "18",
    }

    bar = _parse_price_row(
        row,
        batch_id=uuid4(),
        provider_code="IC_MARKETS_MT5",
        dataset_code="EURUSD_1M",
        is_synthetic=False,
    )

    assert bar.instrument_code == "EURUSD"
    assert bar.spread_points == 18
    assert bar.spread_price == Decimal("0.00018")


def test_mt5_cross_market_rows_use_explicit_symbol_contracts() -> None:
    expected = (
        ("XAGUSD_1M", "XAGUSD", "25.125", "25", Decimal("0.025")),
        ("US500_1M", "US500", "5000.25", "4", Decimal("0.04")),
        ("TLT.NAS_1M", "TLT.NAS", "92.15", "3", Decimal("0.03")),
    )
    for dataset, instrument, price, spread_points, spread_price in expected:
        row = {
            "open_time": "2022-01-05T15:00:00Z",
            "close_time": "2022-01-05T15:01:00Z",
            "available_at": "2022-01-05T15:01:00Z",
            "open": price,
            "high": str(Decimal(price) + Decimal("0.10")),
            "low": str(Decimal(price) - Decimal("0.10")),
            "close": price,
            "volume": "10",
            "volume_type": "TICK",
            "spread_points": spread_points,
        }

        bar = _parse_price_row(
            row,
            batch_id=uuid4(),
            provider_code="IC_MARKETS_MT5",
            dataset_code=dataset,
            is_synthetic=False,
        )

        assert bar.instrument_code == instrument
        assert bar.spread_price == spread_price


@pytest.mark.asyncio
async def test_price_ingestion_uses_natural_key_conflict_tolerance() -> None:
    row = {
        "open_time": "2022-01-05T15:00:00Z",
        "close_time": "2022-01-05T15:01:00Z",
        "available_at": "2022-01-05T15:01:00Z",
        "open": "25.125",
        "high": "25.130",
        "low": "25.120",
        "close": "25.127",
        "volume": "10",
        "volume_type": "TICK",
        "spread_points": "5",
    }
    bar = _parse_price_row(
        row,
        batch_id=uuid4(),
        provider_code="IC_MARKETS_MT5",
        dataset_code="XAGUSD_1M",
        is_synthetic=False,
    )
    session = AsyncMock()

    await _insert_price_models_idempotently(session, [bar, bar])

    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql
    assert "provider_code" in sql
    assert "available_at" in sql


@pytest.mark.asyncio
async def test_price_ingestion_chunks_below_asyncpg_parameter_limit() -> None:
    row = {
        "open_time": "2022-01-05T15:00:00Z",
        "close_time": "2022-01-05T15:01:00Z",
        "available_at": "2022-01-05T15:01:00Z",
        "open": "25.125",
        "high": "25.130",
        "low": "25.120",
        "close": "25.127",
        "volume": "10",
        "volume_type": "TICK",
        "spread_points": "5",
    }
    bar = _parse_price_row(
        row,
        batch_id=uuid4(),
        provider_code="IC_MARKETS_MT5",
        dataset_code="XAGUSD_1M",
        is_synthetic=False,
    )
    session = AsyncMock()

    await _insert_price_models_idempotently(session, [bar] * 1_501)

    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_raw_audit_ingestion_uses_bounded_bulk_chunks() -> None:
    raw_value = {
        "id": uuid4(),
        "batch_id": uuid4(),
        "record_number": 1,
        "source_record_key": "row-1",
        "payload": {"value": "1"},
        "parsed_ok": True,
        "parse_error": None,
    }
    session = AsyncMock()

    await _insert_raw_records(session, [raw_value] * 4_001)

    assert session.execute.await_count == 2


def test_spread_points_are_rejected_without_provider_point_size_contract() -> None:
    row = {
        "open_time": "2026-07-24T14:59:00Z",
        "close_time": "2026-07-24T15:00:00Z",
        "available_at": "2026-07-24T15:00:00Z",
        "open": "2400.00",
        "high": "2400.50",
        "low": "2399.50",
        "close": "2400.25",
        "volume": "123",
        "volume_type": "TICK",
        "spread_points": "7",
    }

    try:
        _parse_price_row(
            row,
            batch_id=uuid4(),
            provider_code="UNVERSIONED_PROVIDER",
            is_synthetic=False,
        )
    except ValueError as error:
        assert "point-size contract" in str(error)
    else:
        raise AssertionError("Unversioned provider spread must be rejected")


def test_negative_spread_points_are_rejected() -> None:
    row = {
        "open_time": "2026-07-24T14:59:00Z",
        "close_time": "2026-07-24T15:00:00Z",
        "available_at": "2026-07-24T15:00:00Z",
        "open": "2400.00",
        "high": "2400.50",
        "low": "2399.50",
        "close": "2400.25",
        "volume": "123",
        "volume_type": "TICK",
        "spread_points": "-1",
    }

    try:
        _parse_price_row(
            row,
            batch_id=uuid4(),
            provider_code="IC_MARKETS_MT5",
            is_synthetic=False,
        )
    except ValueError as error:
        assert "cannot be negative" in str(error)
    else:
        raise AssertionError("Negative spread must be rejected")
