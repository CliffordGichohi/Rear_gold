from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from gold_intel.analytics.casebook_coverage import (
    HOLDOUT_START,
    SessionWindow,
    audit_session_windows,
    eligible_record_coverage,
    validate_development_period,
)


def _window_times(
    session_date: date,
    *,
    timezone: ZoneInfo,
    start: time,
    end: time,
) -> list[datetime]:
    start_at = datetime.combine(session_date, start, tzinfo=timezone).astimezone(UTC)
    end_at = datetime.combine(session_date, end, tzinfo=timezone).astimezone(UTC)
    return [
        start_at + timedelta(minutes=5 * offset)
        for offset in range(int((end_at - start_at).total_seconds() // 300))
    ]


def test_holdout_guard_rejects_loading_after_2025() -> None:
    with pytest.raises(ValueError, match="locked 2025 holdout"):
        validate_development_period(
            datetime(2024, 1, 1, tzinfo=UTC),
            HOLDOUT_START + timedelta(minutes=1),
        )


def test_session_audit_records_incomplete_window_without_filling_it() -> None:
    session_date = date(2024, 7, 1)
    tokyo = ZoneInfo("Asia/Tokyo")
    london = ZoneInfo("Europe/London")
    new_york = ZoneInfo("America/New_York")
    bars = (
        _window_times(
            session_date,
            timezone=tokyo,
            start=time(10, 5),
            end=time(16, 0),
        )
        + _window_times(
            session_date,
            timezone=london,
            start=time(8, 0),
            end=time(12, 0),
        )
        + _window_times(
            session_date,
            timezone=new_york,
            start=time(8, 0),
            end=time(12, 0),
        )
    )
    bars.remove(
        datetime.combine(session_date, time(9, 0), tzinfo=new_york).astimezone(UTC)
    )

    report, decisions = audit_session_windows(
        bars,
        start=datetime(2024, 7, 1, tzinfo=UTC),
        end=datetime(2024, 7, 2, tzinfo=UTC),
    )

    assert report["counts"]["all"]["london_case_complete"] == 1
    assert report["counts"]["all"]["new_york_case_complete"] == 0
    assert report["missing_dates"]["NEW_YORK"] == ["2024-07-01"]
    assert len(decisions["LONDON"]) == 1
    assert decisions["NEW_YORK"] == ()


def test_eligible_coverage_uses_only_records_available_by_decision() -> None:
    decisions = [
        datetime(2024, 1, 8, 8, tzinfo=UTC),
        datetime(2024, 1, 9, 8, tzinfo=UTC),
    ]
    records = [
        (datetime(2024, 1, 8, 9, tzinfo=UTC), "late-first"),
        (datetime(2024, 1, 9, 7, tzinfo=UTC), "eligible-second"),
    ]

    result = eligible_record_coverage(decisions, records)

    assert result["eligible_sessions"] == 1
    assert result["eligible_pct"] == 50.0
    assert result["effective_distinct_records"] == 1


def test_session_window_dataclass_is_explicit_about_timezone() -> None:
    window = SessionWindow(
        code="TEST",
        timezone=ZoneInfo("Europe/London"),
        start=time(8),
        end=time(12),
    )
    assert window.timezone.key == "Europe/London"
