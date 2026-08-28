from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from gold_intel.analytics.coherent_auction_correction_v1 import (
    balance_boxes,
    canonical_hash,
    confirmed_swings,
    event_lock_state,
    level_lifecycle,
    simulate_policy_path,
    structural_breaks,
)


def bar(
    opened: datetime,
    minutes: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    timeframe: str,
) -> dict[str, object]:
    closed = opened + timedelta(minutes=minutes)
    return {
        "open_at": opened.isoformat().replace("+00:00", "Z"),
        "close_at": closed.isoformat().replace("+00:00", "Z"),
        "available_at": closed.isoformat().replace("+00:00", "Z"),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "timeframe": timeframe,
    }


def bars_from_centres(
    centres: list[float], *, start: datetime, minutes: int, timeframe: str
) -> list[dict[str, object]]:
    output = []
    prior = centres[0]
    for index, centre in enumerate(centres):
        output.append(
            bar(
                start + timedelta(minutes=minutes * index),
                minutes,
                prior,
                centre + 0.30,
                centre - 0.30,
                centre,
                timeframe,
            )
        )
        prior = centre
    return output


def test_future_formed_swing_is_unavailable_until_second_right_bar() -> None:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    centres = [100.0 + (index % 3) * 0.05 for index in range(22)]
    centres[15] = 102.0
    rows = bars_from_centres(centres, start=start, minutes=15, timeframe="15m")
    before = rows[16]["available_at"]
    after = rows[17]["available_at"]
    _, early = confirmed_swings(rows, str(before), "M15")
    _, ready = confirmed_swings(rows, str(after), "M15")
    assert not any(item["pivot_index"] == 15 and item["kind"] == "HIGH" for item in early)
    assert any(item["pivot_index"] == 15 and item["kind"] == "HIGH" for item in ready)


def test_level_lifecycle_distinguishes_engaged_consumed_and_reactivated() -> None:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    base = [99.5] * 14
    engaged_rows = bars_from_centres(base + [100.0], start=start, minutes=15, timeframe="15m")
    engaged_rows[-1]["high"] = 100.2
    engaged_rows[-1]["close"] = 99.9
    engaged = level_lifecycle(
        engaged_rows,
        level=100.0,
        known_at=engaged_rows[13]["available_at"],
        cutoff=engaged_rows[-1]["available_at"],
        direction="LONG",
    )
    assert engaged["state"] == "ACTIVE_ENGAGED"

    consumed_rows = bars_from_centres(
        base + [100.8, 100.9], start=start, minutes=15, timeframe="15m"
    )
    consumed = level_lifecycle(
        consumed_rows,
        level=100.0,
        known_at=consumed_rows[13]["available_at"],
        cutoff=consumed_rows[-1]["available_at"],
        direction="LONG",
    )
    assert consumed["state"] == "CONSUMED_ACCEPTED"

    reverse_rows = bars_from_centres(
        base + [100.8, 100.9, 99.0, 98.9], start=start, minutes=15, timeframe="15m"
    )
    reactivated = level_lifecycle(
        reverse_rows,
        level=100.0,
        known_at=reverse_rows[13]["available_at"],
        cutoff=reverse_rows[-1]["available_at"],
        direction="LONG",
    )
    assert reactivated["state"] == "REACTIVATED_REVERSE"


def test_balance_requires_two_confirmed_highs_and_lows() -> None:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    centres = [100.0, 100.6, 101.0, 100.4, 99.5, 99.0, 99.6] * 6
    rows = bars_from_centres(centres, start=start, minutes=60, timeframe="1h")
    _, boxes = balance_boxes(rows, rows[-1]["available_at"], "H1")
    assert boxes
    assert all(box.high > box.low for box in boxes)


def test_structural_break_is_long_short_symmetric() -> None:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    centres = [100.0, 100.3, 100.7, 100.2, 99.6, 99.2, 99.8] * 3
    centres += [100.2, 100.5, 101.5, 102.5]
    long_rows = bars_from_centres(centres, start=start, minutes=15, timeframe="15m")
    short_rows = []
    for row in long_rows:
        short_rows.append(
            {
                **row,
                "open": 200.0 - float(row["open"]),
                "high": 200.0 - float(row["low"]),
                "low": 200.0 - float(row["high"]),
                "close": 200.0 - float(row["close"]),
            }
        )
    long_breaks = structural_breaks(
        long_rows, long_rows[-1]["available_at"], "M15", "LONG"
    )
    short_breaks = structural_breaks(
        short_rows, short_rows[-1]["available_at"], "M15", "SHORT"
    )
    assert long_breaks
    assert len(long_breaks) == len(short_breaks)
    assert [item["break_at"] for item in long_breaks] == [
        item["break_at"] for item in short_breaks
    ]


def test_tier_one_event_lock_cannot_be_bypassed_without_retest() -> None:
    start = datetime(2022, 1, 1, 13, 0, tzinfo=UTC)
    m1 = bars_from_centres([100.0] * 70, start=start, minutes=1, timeframe="1m")
    m5 = bars_from_centres([100.0] * 20, start=start, minutes=5, timeframe="5m")
    event_at = start + timedelta(minutes=30)
    stream = {
        "timeframes": {"1m": m1, "5m": m5},
        "context_timeline": {
            "events": [
                {
                    "event_type": "CPI",
                    "event_code": "US_CPI",
                    "scheduled_at": event_at.isoformat().replace("+00:00", "Z"),
                    "released_at": event_at.isoformat().replace("+00:00", "Z"),
                    "event_available_at": event_at.isoformat().replace("+00:00", "Z"),
                }
            ]
        },
    }
    decision = event_at + timedelta(minutes=35)
    result = event_lock_state(stream, decision.isoformat(), "LONG")
    assert result["locked"] is True
    assert result["reason"] == "TIER1_DIRECTIONAL_ACCEPTANCE_RETEST_MISSING"


def test_range_management_partial_and_final_target_are_economic_legs() -> None:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    history_start = start - timedelta(hours=8)
    m15 = bars_from_centres([100.0] * 32, start=history_start, minutes=15, timeframe="15m")
    m1 = bars_from_centres([100.0] * 60, start=start, minutes=1, timeframe="1m")
    m1[2].update({"high": 102.2, "low": 99.8, "close": 102.0})
    m1[20].update({"open": 102.2, "high": 104.2, "low": 102.0, "close": 104.0})
    stream = {
        "end_exclusive": (start + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "timeframes": {"1m": m1, "15m": m15},
    }
    classification = {
        "admitted": True,
        "primary_disposition": "ADMIT",
        "classification_hash": "synthetic",
        "direction": "LONG",
        "fill": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "first_realization": 102.0,
        "quantity_ounces": 10,
        "cost_per_ounce": 0.10,
        "thesis": "RANGE_ROTATION",
    }
    result = simulate_policy_path(
        classification=classification,
        stream=stream,
        fill_at=start.isoformat().replace("+00:00", "Z"),
    )
    assert result["executed"] is True
    assert [leg["resolution"] for leg in result["legs"]] == [
        "RANGE_MIDPOINT_REALIZATION",
        "RANGE_ROTATION_TARGET",
    ]
    assert sum(leg["quantity_ounces"] for leg in result["legs"]) == 10
    assert result["net_usd"] == pytest.approx(29.0)


def test_identical_payloads_produce_identical_checksums() -> None:
    payload = {"rows": [{"at": "2022-01-01T00:00:00Z", "value": 1.25}]}
    assert canonical_hash(payload) == canonical_hash(deepcopy(payload))

