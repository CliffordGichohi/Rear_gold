from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gold_intel.analytics.auction_liquidity_range_semantics_v1 import (
    active_range_context,
    build_timeframe_inventory,
    classify_pivot_liquidity,
)


def _bar(index: int, *, high: float, low: float, close: float | None = None) -> dict:
    opened = datetime(2022, 1, 3, tzinfo=UTC) + timedelta(hours=index)
    value = (high + low) / 2 if close is None else close
    return {
        "open_at": opened.isoformat().replace("+00:00", "Z"),
        "available_at": (opened + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "open": value,
        "high": high,
        "low": low,
        "close": value,
        "complete": True,
    }


def _swing(kind: str, level: float, pivot_index: int = 1) -> dict:
    pivot = datetime(2022, 1, 3, tzinfo=UTC) + timedelta(hours=pivot_index)
    return {
        "identity": f"{kind}-{level}",
        "kind": kind,
        "timeframe": "H1",
        "pivot_at": pivot.isoformat().replace("+00:00", "Z"),
        "detected_at": (pivot + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        "level": level,
    }


def test_equal_price_engages_but_does_not_consume_high() -> None:
    rows = [
        _bar(0, high=99.0, low=98.0),
        _bar(1, high=100.0, low=98.5),
        _bar(2, high=99.5, low=98.5),
        _bar(3, high=99.0, low=98.0),
        _bar(4, high=100.0, low=99.0),
    ]
    result = classify_pivot_liquidity(rows, _swing("HIGH", 100.0), rows[-1]["available_at"])
    assert result["state"] == "UNCONSUMED_ENGAGED"
    assert result["engaged_at"] == rows[-1]["available_at"]
    assert result["consumed_at"] is None


def test_strict_later_price_above_consumes_without_close_or_atr_condition() -> None:
    rows = [
        _bar(0, high=99.0, low=98.0),
        _bar(1, high=100.0, low=98.5),
        _bar(2, high=99.5, low=98.5),
        _bar(3, high=99.0, low=98.0),
        _bar(4, high=100.01, low=98.0, close=98.2),
    ]
    result = classify_pivot_liquidity(rows, _swing("HIGH", 100.0), rows[-1]["available_at"])
    assert result["state"] == "CONSUMED"
    assert result["consumed_at"] == rows[-1]["available_at"]
    assert result["close_or_atr_required"] is False


def test_strict_later_price_below_is_direction_symmetric() -> None:
    rows = [
        _bar(0, high=102.0, low=101.0),
        _bar(1, high=101.5, low=100.0),
        _bar(2, high=101.5, low=100.5),
        _bar(3, high=102.0, low=101.0),
        _bar(4, high=102.0, low=99.99, close=101.8),
    ]
    result = classify_pivot_liquidity(rows, _swing("LOW", 100.0), rows[-1]["available_at"])
    assert result["state"] == "CONSUMED"
    assert result["strict_beyond_rule"] == "LATER_LOW_LT_LEVEL"


def test_price_after_cutoff_cannot_change_the_state() -> None:
    rows = [
        _bar(0, high=99.0, low=98.0),
        _bar(1, high=100.0, low=98.5),
        _bar(2, high=99.5, low=98.5),
        _bar(3, high=99.0, low=98.0),
        _bar(4, high=99.9, low=98.0),
        _bar(5, high=101.0, low=98.0),
    ]
    result = classify_pivot_liquidity(rows, _swing("HIGH", 100.0), rows[4]["available_at"])
    assert result["state"] == "UNCONSUMED_UNTOUCHED"


def _range_rows() -> list[dict]:
    centers = [102.5] * 30
    for index in (12, 18, 24):
        centers[index] = 105.0
    for index in (15, 21, 27):
        centers[index] = 100.0
    rows: list[dict] = []
    for index, center in enumerate(centers):
        rows.append(_bar(index, high=center + 0.2, low=center - 0.2, close=center))
    return rows


def test_repeated_exact_unconsumed_boundaries_form_active_range() -> None:
    rows = _range_rows()
    cutoff = rows[-1]["available_at"]
    inventory = build_timeframe_inventory(rows, cutoff, "H1")
    result = active_range_context(
        rows,
        cutoff=cutoff,
        timeframe="H1",
        direction="LONG",
        price=102.5,
        inventory=inventory,
    )
    assert result["state"] == "ACTIVE_RANGE"
    assert result["context_family"] == "RANGE_ROTATION_WITH_LTF_CONTROL"
    assert result["lower_boundary"]["state"].startswith("UNCONSUMED_")
    assert result["upper_boundary"]["state"].startswith("UNCONSUMED_")
    assert len(result["lower_interaction_identities"]) >= 2
    assert len(result["upper_interaction_identities"]) >= 2


def test_range_stops_being_active_when_boundary_price_is_consumed() -> None:
    rows = _range_rows()
    rows.append(_bar(30, high=105.3, low=102.0, close=102.5))
    cutoff = rows[-1]["available_at"]
    result = active_range_context(
        rows,
        cutoff=cutoff,
        timeframe="H1",
        direction="SHORT",
        price=102.5,
    )
    assert result["state"] == "NO_ACTIVE_RANGE"
    assert result["reason"] == "EXACT_RANGE_BOUNDARY_CONSUMED"

