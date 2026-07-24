from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from gold_intel.analytics.sessions import (
    SessionPause,
    SessionPriceBar,
    calculate_session_ranges,
    session_at,
)


def test_london_new_york_overlap_respects_summer_offsets() -> None:
    context = session_at(datetime(2026, 7, 17, 15, 0, tzinfo=UTC))
    assert context.primary == "LONDON_NEW_YORK_OVERLAP"
    assert context.active == ("LONDON", "NEW_YORK")


def test_london_new_york_overlap_respects_winter_offsets() -> None:
    context = session_at(datetime(2026, 1, 15, 15, 0, tzinfo=UTC))
    assert context.primary == "LONDON_NEW_YORK_OVERLAP"


def test_lbma_window_uses_london_daylight_saving_time() -> None:
    context = session_at(datetime(2026, 7, 17, 9, 30, tzinfo=UTC))
    assert "LBMA_AM_WINDOW" in context.special_windows


def test_london_range_is_complete_and_dst_anchored() -> None:
    start = datetime(2026, 7, 17, 7, 0, tzinfo=UTC)
    bars = [
        SessionPriceBar(
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            open=2400 + index / 100,
            high=2401 + index / 100,
            low=2399 + index / 100,
            close=2400.5 + index / 100,
            available_at=start + timedelta(minutes=index + 1),
        )
        for index in range(540)
    ]
    ranges = calculate_session_ranges(
        bars,
        datetime(2026, 7, 17, 16, 0, tzinfo=UTC),
    )
    london = next(item for item in ranges if item.name == "LONDON")
    assert london.start_at == start
    assert london.end_at == datetime(2026, 7, 17, 16, 0, tzinfo=UTC)
    assert london.status == "COMPLETE"
    assert london.completeness_pct == 100


def test_scheduled_provider_pause_is_not_reported_as_missing_data() -> None:
    start = datetime(2026, 7, 16, 23, 0, tzinfo=UTC)
    bars = [
        SessionPriceBar(
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            open=2400,
            high=2401,
            low=2399,
            close=2400.5,
            available_at=start + timedelta(minutes=index + 1),
        )
        for index in range(540)
        if not 59 <= index < 120
    ]
    pauses = (
        SessionPause(
            name="PROVIDER_PAUSE",
            timezone=ZoneInfo("UTC"),
            start=datetime.min.time().replace(hour=23, minute=59),
            end=datetime.min.time().replace(hour=1),
        ),
    )
    ranges = calculate_session_ranges(
        bars,
        datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
        scheduled_pauses=pauses,
    )
    asia = next(item for item in ranges if item.name == "ASIA")
    assert asia.status == "COMPLETE"
    assert asia.completeness_pct == 100
