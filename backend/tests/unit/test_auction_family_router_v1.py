from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gold_intel.analytics.auction_family_router_v1 import (
    first_range_reclaim,
    first_structural_repair_retest,
    range_reclaim_qualifies,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, iso


def bar(
    opened: datetime,
    minutes: int,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> dict[str, object]:
    closed = opened + timedelta(minutes=minutes)
    return {
        "open_at": iso(opened),
        "close_at": iso(closed),
        "available_at": iso(closed),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "source_record_hash": canonical_hash(
            [iso(opened), minutes, open_, high, low, close]
        ),
    }


def event(direction: str) -> dict[str, object]:
    return {
        "identity": f"synthetic-{direction.lower()}-break",
        "direction": direction,
        "broken_level": 100.0,
        "protected_level": 95.0 if direction == "LONG" else 105.0,
        "atr": 2.0,
    }


def warmup(point: datetime, close: float = 101.0) -> list[dict[str, object]]:
    return [
        bar(
            point - timedelta(minutes=5 * (14 - index)),
            5,
            close,
            close + 0.5,
            close - 0.5,
            close,
        )
        for index in range(14)
    ]


def test_range_reclaim_is_mirrored_and_rejects_body_without_wick() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    long = bar(point, 5, 100.0, 102.0, 98.0, 101.0)
    short = bar(point, 5, 100.0, 102.0, 98.0, 99.0)
    no_long_wick = bar(point, 5, 100.0, 102.0, 100.0, 101.0)
    no_short_wick = bar(point, 5, 100.0, 100.0, 98.0, 99.0)
    assert range_reclaim_qualifies(long, "LONG")
    assert not range_reclaim_qualifies(long, "SHORT")
    assert range_reclaim_qualifies(short, "SHORT")
    assert not range_reclaim_qualifies(short, "LONG")
    assert not range_reclaim_qualifies(no_long_wick, "LONG")
    assert not range_reclaim_qualifies(no_short_wick, "SHORT")


def test_range_route_takes_first_bar_and_honours_six_bar_expiry() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    ordinary = [
        bar(point + timedelta(minutes=5 * index), 5, 100.0, 101.0, 99.0, 100.0)
        for index in range(7)
    ]
    first = bar(point + timedelta(minutes=5), 5, 100.0, 102.0, 98.0, 101.0)
    second = bar(point + timedelta(minutes=10), 5, 101.0, 103.0, 99.0, 102.0)
    routed = first_range_reclaim(
        [ordinary[0], first, second],
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    )
    assert routed is not None
    assert routed["confirmation_at"] == iso(point + timedelta(minutes=10))
    assert routed["within_route_occurrence"] == 2

    seventh = bar(point + timedelta(minutes=30), 5, 100.0, 102.0, 98.0, 101.0)
    assert (
        first_range_reclaim(
            ordinary[:6] + [seventh],
            signal_at=point,
            session_end=point + timedelta(hours=4),
            direction="LONG",
        )
        is None
    )


def test_structural_repair_long_and_short_are_mirrored() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    long_rows = warmup(point)
    long_rows.append(bar(point, 5, 100.3, 101.2, 99.9, 100.8))
    long_result = first_structural_repair_retest(
        long_rows,
        event=event("LONG"),
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    )
    assert long_result["disposition"] == "CONFIRMED"
    assert long_result["confirmation_at"] == iso(point + timedelta(minutes=5))

    short_rows = warmup(point, 99.0)
    short_rows.append(bar(point, 5, 99.7, 100.1, 98.8, 99.2))
    short_result = first_structural_repair_retest(
        short_rows,
        event=event("SHORT"),
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="SHORT",
    )
    assert short_result["disposition"] == "CONFIRMED"
    assert short_result["confirmation_at"] == iso(point + timedelta(minutes=5))


def test_structural_repair_invalidates_before_later_retest() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    rows = warmup(point)
    rows.extend(
        [
            bar(point, 5, 96.0, 96.2, 94.0, 94.7),
            bar(point + timedelta(minutes=5), 5, 100.2, 101.0, 99.9, 100.8),
        ]
    )
    result = first_structural_repair_retest(
        rows,
        event=event("LONG"),
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    )
    assert result["disposition"] == "REPAIR_STRUCTURE_INVALIDATED"
    assert result["invalidated_at"] == iso(point + timedelta(minutes=5))


def test_structural_repair_honours_twelve_bar_expiry() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    rows = warmup(point)
    rows.extend(
        bar(point + timedelta(minutes=5 * index), 5, 101.0, 102.0, 100.8, 101.0)
        for index in range(12)
    )
    rows.append(bar(point + timedelta(minutes=60), 5, 100.3, 101.2, 99.9, 100.8))
    result = first_structural_repair_retest(
        rows,
        event=event("LONG"),
        signal_at=point,
        session_end=point + timedelta(hours=4),
        direction="LONG",
    )
    assert result["disposition"] == "NO_REPAIR_RETEST_WITHIN_12_M5"
    assert result["confirmation_at"] is None
