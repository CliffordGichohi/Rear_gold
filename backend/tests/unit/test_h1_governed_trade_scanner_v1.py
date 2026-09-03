from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from gold_intel.analytics.auction_liquidity_range_semantics_v1 import (
    active_range_context,
    build_timeframe_inventory,
)
from gold_intel.analytics.h1_governed_trade_scanner_v1 import (
    PointInTimeInventoryTimeline,
    _first_valid_retest,
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _rows(count: int = 42) -> list[dict]:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    rows: list[dict] = []
    for index in range(count):
        open_at = start + timedelta(hours=index)
        center = 100.0 + 4.0 * math.sin(index * math.pi / 4.0) + 0.04 * index
        rows.append(
            {
                "bar_id": f"H1-{index:03d}",
                "open_at": _iso(open_at),
                "available_at": _iso(open_at + timedelta(hours=1)),
                "open": center - 0.15,
                "high": center + 0.9,
                "low": center - 0.9,
                "close": center + 0.15,
                "complete": True,
            }
        )
    return rows


def _state_core(inventory: dict) -> list[tuple]:
    return [
        (
            item["identity"],
            item["kind"],
            item["pivot_at"],
            item["known_at"],
            item["level"],
            item["state"],
            item["engaged_at"],
            item["consumed_at"],
        )
        for item in inventory["states"]
    ]


def test_timeline_inventory_matches_frozen_cutoff_semantics() -> None:
    rows = _rows()
    end = rows[-1]["available_at"]
    timeline = PointInTimeInventoryTimeline(rows, end=end, timeframe="1h")
    for index in (20, 25, 31, 40):
        cutoff = rows[index]["available_at"]
        expected = build_timeframe_inventory(rows, cutoff, "H1")
        actual = timeline.inventory(cutoff)
        assert actual["completed_bars"] == expected["completed_bars"]
        assert actual["state_counts"] == expected["state_counts"]
        assert _state_core(actual) == _state_core(expected)


def test_timeline_range_disposition_matches_reference_implementation() -> None:
    rows = _rows()
    end = rows[-1]["available_at"]
    timeline = PointInTimeInventoryTimeline(rows, end=end, timeframe="1h")
    cutoff = rows[40]["available_at"]
    price = float(rows[40]["close"])
    inventory = timeline.inventory(cutoff)
    for direction in ("LONG", "SHORT"):
        expected = active_range_context(
            rows,
            cutoff=cutoff,
            timeframe="H1",
            direction=direction,
            price=price,
        )
        actual = timeline.active_range(
            cutoff=cutoff,
            direction=direction,
            price=price,
            inventory=inventory,
        )
        assert actual["state"] == expected["state"]
        assert actual.get("reason") == expected.get("reason")
        if actual["state"] == "ACTIVE_RANGE":
            assert actual["lower_boundary"] == expected["lower_boundary"]
            assert actual["upper_boundary"] == expected["upper_boundary"]
            assert actual["range_identity"] == expected["range_identity"]


def test_first_valid_retest_is_completed_and_better_extreme() -> None:
    start = datetime(2022, 1, 3, 10, 0, tzinfo=UTC)

    def bar(index: int, open_: float, high: float, low: float, close: float) -> dict:
        open_at = start + timedelta(minutes=5 * index)
        return {
            "bar_id": f"M5-{index}",
            "open_at": _iso(open_at),
            "available_at": _iso(open_at + timedelta(minutes=5)),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "complete": True,
        }

    rows = [
        bar(0, 100.0, 102.0, 99.0, 101.0),
        bar(1, 100.1, 101.8, 99.4, 101.5),
        bar(2, 101.5, 102.1, 100.8, 101.9),
    ]
    result = _first_valid_retest(
        rows,
        turn_index=0,
        direction="LONG",
        zone={"lower": 99.0, "upper": 100.0, "invalidation": 98.5},
        control={"level": 98.8},
    )
    assert result is not None
    assert result["index"] == 1
    assert result["bar"]["bar_id"] == "M5-1"
    assert result["better_extreme"] is True

