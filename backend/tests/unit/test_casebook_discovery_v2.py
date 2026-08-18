from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gold_intel.analytics.casebook_discovery_v2 import (
    HOLDOUT_END,
    HOLDOUT_START,
    SessionWindow,
    assert_metadata_only_sql,
    audit_timestamp_only_session_coverage,
    mt5_xau_files_overlapping_holdout,
)


def test_metadata_sql_guard_rejects_price_and_outcome_values() -> None:
    with pytest.raises(ValueError, match="forbidden column 'close'"):
        assert_metadata_only_sql({"bad": "SELECT close FROM market.price_bars"})
    with pytest.raises(ValueError, match="forbidden column 'pnl'"):
        assert_metadata_only_sql({"bad": "SELECT pnl FROM results"})


def test_metadata_sql_guard_allows_timestamp_and_presence_counts() -> None:
    assert_metadata_only_sql(
        {
            "safe": """
                SELECT min(open_time), max(close_time),
                       count(*) FILTER (WHERE spread_price IS NOT NULL)
                FROM market.price_bars
            """
        }
    )


def test_mt5_file_inventory_uses_filename_bounds_only(tmp_path: Path) -> None:
    names = (
        "xauusd_1m_ic_markets_mt5_20241201T0000_20250103T1404.csv",
        "xauusd_1m_ic_markets_mt5_20250103T1405_20251231T2358.csv",
        "xauusd_1m_ic_markets_mt5_20251215T0100_20260113T1404.csv",
        "xauusd_1m_ic_markets_mt5_20260113T1405_20260212T1404.csv",
        "eurusd_1m_ic_markets_mt5_20250103T1405_20251231T2358.csv",
    )
    for name in names:
        (tmp_path / name).touch()

    assert [path.name for path in mt5_xau_files_overlapping_holdout(tmp_path)] == [
        names[0],
        names[1],
        names[2],
    ]


def test_timestamp_only_session_audit_handles_iana_dst() -> None:
    buckets: set[datetime] = set()
    for session_date in (date(2025, 3, 28), date(2025, 3, 31)):
        for spec in (
            SessionWindow(
                "ASIA",
                ZoneInfo("Asia/Tokyo"),
                time(10, 5),
                time(16),
            ),
            SessionWindow(
                "LONDON",
                ZoneInfo("Europe/London"),
                time(8),
                time(12),
            ),
            SessionWindow(
                "NEW_YORK",
                ZoneInfo("America/New_York"),
                time(8),
                time(12),
            ),
        ):
            start = datetime.combine(
                session_date,
                spec.start,
                tzinfo=spec.timezone,
            ).astimezone(UTC)
            end = datetime.combine(
                session_date,
                spec.end,
                tzinfo=spec.timezone,
            ).astimezone(UTC)
            current = start
            while current < end:
                buckets.add(current)
                current += timedelta(minutes=5)

    report = audit_timestamp_only_session_coverage(
        buckets,
        start=HOLDOUT_START,
        end=HOLDOUT_END,
    )

    assert report["data_access_class"] == "TIMESTAMPS_ONLY"
    assert report["counts"]["london_case_complete"] == 2
    assert report["counts"]["new_york_case_complete"] == 2
    assert "2025-03-28" not in report["missing_dates"]["LONDON_CASE"]
    assert "2025-03-31" not in report["missing_dates"]["LONDON_CASE"]


def test_timestamp_only_session_audit_rejects_non_holdout_interval() -> None:
    with pytest.raises(ValueError, match="restricted to calendar 2025"):
        audit_timestamp_only_session_coverage(
            [],
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=HOLDOUT_END,
        )
