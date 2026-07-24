from datetime import UTC, datetime, timedelta
from uuid import uuid4

from gold_intel.analytics.structure import (
    AggregateBar,
    MinuteBar,
    StructureConfig,
    aggregate_five_minutes,
    aggregate_trading_days,
    analyze_timeframe_structure,
)


def test_incomplete_five_minute_bucket_is_flagged() -> None:
    start = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
    bars = [
        MinuteBar(
            id=uuid4(),
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            open=2400,
            high=2401,
            low=2399,
            close=2400,
            volume=1,
            available_at=start + timedelta(minutes=index + 1),
        )
        for index in (0, 1, 3, 4)
    ]
    aggregated = aggregate_five_minutes(bars, start + timedelta(minutes=5))
    assert len(aggregated) == 1
    assert aggregated[0].complete is False


def _aggregate_bar(
    start: datetime,
    index: int,
    *,
    high: float = 101,
    low: float = 99,
    open_price: float = 100,
    close: float = 100,
) -> AggregateBar:
    open_time = start + timedelta(minutes=5 * index)
    return AggregateBar(
        open_time=open_time,
        close_time=open_time + timedelta(minutes=5),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100,
        complete=True,
        source_ids=(str(uuid4()),),
    )


def test_swing_is_not_visible_before_right_side_confirmation() -> None:
    start = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    bars = [_aggregate_bar(start, index) for index in range(25)]
    bars[17] = _aggregate_bar(start, 17, high=110)
    config = StructureConfig()

    before = analyze_timeframe_structure(
        bars,
        timeframe="5m",
        as_of=bars[18].close_time,
        config=config,
    )
    after = analyze_timeframe_structure(
        bars,
        timeframe="5m",
        as_of=bars[19].close_time,
        config=config,
    )

    assert not any(
        item.price_level == 110 and item.kind in {"SWING_HIGH", "HIGHER_HIGH"}
        for item in before.detections
    )
    detected = next(
        item
        for item in after.detections
        if item.price_level == 110 and item.kind in {"SWING_HIGH", "HIGHER_HIGH"}
    )
    assert detected.detected_at == bars[19].close_time
    assert detected.epistemic_status == "CALCULATED"


def test_two_closes_above_confirmed_resistance_are_inferred_acceptance() -> None:
    start = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    bars = [_aggregate_bar(start, index) for index in range(25)]
    bars[10] = _aggregate_bar(start, 10, high=105)
    bars[23] = _aggregate_bar(
        start,
        23,
        high=107,
        low=103.8,
        open_price=104.2,
        close=106,
    )
    bars[24] = _aggregate_bar(
        start,
        24,
        high=107.2,
        low=105.2,
        open_price=105.8,
        close=106.4,
    )

    result = analyze_timeframe_structure(
        bars,
        timeframe="5m",
        as_of=bars[-1].close_time,
        config=StructureConfig(),
    )

    acceptance = next(
        item for item in result.detections if item.kind == "ACCEPTANCE_ABOVE_RESISTANCE"
    )
    assert acceptance.price_level == 105
    assert acceptance.epistemic_status == "INFERRED"
    assert "close back below" in acceptance.invalidation_condition


def test_daily_aggregation_uses_new_york_trading_session_and_detects_gaps() -> None:
    start = datetime(2026, 7, 16, 22, 0, tzinfo=UTC)
    bars = [
        MinuteBar(
            id=uuid4(),
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            open=2400,
            high=2401,
            low=2399,
            close=2400.5,
            volume=1,
            available_at=start + timedelta(minutes=index + 1),
        )
        for index in range(23 * 60)
        if not 119 <= index < 180
    ]
    cutoff = datetime(2026, 7, 17, 21, 0, tzinfo=UTC)
    complete = aggregate_trading_days(
        bars,
        as_of=cutoff,
        pause_start_minute=19 * 60 + 59,
        pause_end_minute=21 * 60,
    )
    incomplete = aggregate_trading_days(
        bars[:700] + bars[701:],
        as_of=cutoff,
        pause_start_minute=19 * 60 + 59,
        pause_end_minute=21 * 60,
    )

    assert len(complete) == 1
    assert complete[0].open_time == start
    assert complete[0].close_time == cutoff
    assert complete[0].complete is True
    assert incomplete[0].complete is False
