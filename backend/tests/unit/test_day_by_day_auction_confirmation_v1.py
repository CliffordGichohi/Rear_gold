from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gold_intel.analytics.day_by_day_auction_confirmation_v1 import (
    find_first_m5_confirmation,
    first_complete_m1_after,
    m5_close_one_r_break_even,
    m5_pair_qualifies,
    pre_entry_disposition,
    target_room,
)


def bar(
    opened: datetime,
    minutes: int,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> dict:
    closed = opened + timedelta(minutes=minutes)
    return {
        "open_at": opened.isoformat().replace("+00:00", "Z"),
        "close_at": closed.isoformat().replace("+00:00", "Z"),
        "available_at": closed.isoformat().replace("+00:00", "Z"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "source_record_hash": f"{opened.timestamp()}-{minutes}",
    }


def test_m5_confirmation_is_adjacent_and_mirrored() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    long_a = bar(point, 5, 100.0, 102.0, 98.0, 101.0)
    long_b = bar(point + timedelta(minutes=5), 5, 100.8, 103.0, 99.0, 102.0)
    assert m5_pair_qualifies(long_a, long_b, "LONG")
    assert not m5_pair_qualifies(long_a, long_b, "SHORT")

    short_a = bar(point, 5, 100.0, 102.0, 98.0, 99.0)
    short_b = bar(point + timedelta(minutes=5), 5, 99.2, 101.0, 97.0, 98.0)
    assert m5_pair_qualifies(short_a, short_b, "SHORT")
    assert not m5_pair_qualifies(short_a, short_b, "LONG")

    # A missing M5 interval cannot be silently skipped.
    delayed_b = dict(long_b)
    delayed_b["open_at"] = (point + timedelta(minutes=10)).isoformat().replace(
        "+00:00", "Z"
    )
    assert not m5_pair_qualifies(long_a, delayed_b, "LONG")


def test_first_confirmation_and_next_m1_latency_are_strict() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    first = bar(point, 5, 100.0, 102.0, 98.0, 101.0)
    second = bar(point + timedelta(minutes=5), 5, 100.8, 103.0, 99.0, 102.0)
    confirmation = find_first_m5_confirmation(
        [first, second],
        signal_at=point.isoformat(),
        session_end=(point + timedelta(hours=4)).isoformat(),
        direction="LONG",
    )
    assert confirmation is not None
    assert confirmation["confirmation_at"] == "2022-01-03T08:10:00Z"

    at_confirmation = bar(point + timedelta(minutes=10), 1, 102, 103, 101, 102)
    after_confirmation = bar(point + timedelta(minutes=11), 1, 102, 103, 101, 102)
    selected = first_complete_m1_after(
        [at_confirmation, after_confirmation], confirmation["confirmation_at"]
    )
    assert selected is not None
    assert selected["open_at"] == "2022-01-03T08:11:00Z"


def test_pre_entry_first_passage_is_stop_first() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    ambiguous = bar(point + timedelta(minutes=1), 1, 100, 112, 88, 101)
    result = pre_entry_disposition(
        [ambiguous],
        signal_at=point,
        fill_at=point + timedelta(minutes=2),
        stop=90,
        target=110,
        direction="LONG",
    )
    assert result["disposition"] == "ORIGINAL_STOP_TOUCHED_PRE_ENTRY"
    assert result["same_bar_target_touch"] is True


def test_target_room_requires_ordered_geometry_and_1p5r() -> None:
    passing = target_room(fill=100, stop=98, target=103, direction="LONG")
    assert passing["geometry_valid"] is True
    assert passing["target_room_r"] == 1.5
    assert passing["passes_1p5r"] is True

    failing = target_room(fill=102, stop=98, target=103, direction="LONG")
    assert failing["target_room_r"] == 0.25
    assert failing["passes_1p5r"] is False

    invalid = target_room(fill=97, stop=98, target=103, direction="LONG")
    assert invalid["geometry_valid"] is False


def test_m5_close_at_one_r_arms_net_break_even_stop_first() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    m5 = [bar(point, 5, 100, 102.5, 99.5, 102.1)]
    m1 = [
        bar(point, 1, 100, 101, 99.5, 100.5),
        bar(point + timedelta(minutes=5), 1, 102.1, 103, 100.1, 102),
    ]
    result = m5_close_one_r_break_even(
        m1_rows=m1,
        m5_rows=m5,
        fill_at=point,
        baseline_final_at=point + timedelta(minutes=6),
        fill=100,
        stop=98,
        target=105,
        cost_per_ounce=0.2,
        direction="LONG",
    )
    assert result["activated"] is True
    assert result["changed"] is True
    assert result["disposition"] == "M5_1R_NET_BREAK_EVEN"
    assert result["exit_at"] == "2022-01-03T08:05:00Z"


def test_target_before_activation_is_not_rewritten() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    m5 = [bar(point, 5, 100, 106, 99, 102.1)]
    m1 = [bar(point + timedelta(minutes=1), 1, 100, 105.5, 99.5, 105)]
    result = m5_close_one_r_break_even(
        m1_rows=m1,
        m5_rows=m5,
        fill_at=point,
        baseline_final_at=point + timedelta(minutes=5),
        fill=100,
        stop=98,
        target=105,
        cost_per_ounce=0.2,
        direction="LONG",
    )
    assert result["changed"] is False
    assert result["disposition"] == "TARGET_PRECEDED_OVERLAY"

