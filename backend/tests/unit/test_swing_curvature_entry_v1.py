from __future__ import annotations

import pytest

from gold_intel.analytics.swing_curvature_entry_v1 import (
    assert_outcome_blind,
    curvature_zone,
    directional_half_close,
    first_confirmed_retest,
    overlaps_zone,
    pivot_consumed,
    pivot_engaged,
    retracement_zone,
    synthetic_proof,
)


def bar(
    open_at: str,
    available_at: str,
    *,
    high: float,
    low: float,
    open_: float,
    close: float,
) -> dict[str, object]:
    return {
        "open_at": open_at,
        "available_at": available_at,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
    }


PIVOT_LOW = {
    "identity": "PIVOT-LOW",
    "kind": "LOW",
    "level": 99.0,
    "pivot_candle_completed_at": "2022-01-01T00:01:00Z",
    "detected_at": "2022-01-01T00:05:00Z",
}


def test_range_curvature_zone_is_directional_half_and_symmetric() -> None:
    candle = {"low": 98.0, "high": 102.0}
    assert curvature_zone(candle, "LONG") == {
        "lower": 98.0,
        "upper": 100.0,
        "midpoint": 100.0,
        "invalidation": 98.0,
    }
    assert curvature_zone(candle, "SHORT") == {
        "lower": 100.0,
        "upper": 102.0,
        "midpoint": 100.0,
        "invalidation": 102.0,
    }


def test_trend_retracement_zone_uses_exact_video_levels_symmetrically() -> None:
    long_zone = retracement_zone(100.0, 110.0, "LONG")
    short_zone = retracement_zone(110.0, 100.0, "SHORT")
    assert long_zone["lower"] == pytest.approx(101.14)
    assert long_zone["midpoint"] == pytest.approx(102.12)
    assert long_zone["upper"] == pytest.approx(102.95)
    assert short_zone["lower"] == pytest.approx(107.05)
    assert short_zone["midpoint"] == pytest.approx(107.88)
    assert short_zone["upper"] == pytest.approx(108.86)


def test_zone_overlap_is_inclusive_but_not_unbounded() -> None:
    zone = {"lower": 99.0, "upper": 100.0}
    assert overlaps_zone({"low": 100.0, "high": 101.0}, zone)
    assert overlaps_zone({"low": 98.5, "high": 99.0}, zone)
    assert not overlaps_zone({"low": 100.01, "high": 101.0}, zone)


def test_equality_engages_but_strict_beyond_consumes() -> None:
    equal = bar(
        "2022-01-01T00:05:00Z",
        "2022-01-01T00:06:00Z",
        high=100.0,
        low=99.0,
        open_=99.5,
        close=99.7,
    )
    assert pivot_engaged([equal], PIVOT_LOW, str(equal["available_at"]))
    assert not pivot_consumed([equal], PIVOT_LOW, str(equal["available_at"]))
    beyond = {**equal, "low": 98.99}
    assert pivot_consumed([beyond], PIVOT_LOW, str(beyond["available_at"]))


def test_directional_half_turn_requires_colour_and_close_location() -> None:
    bullish_upper = bar(
        "2022-01-01T00:10:00Z",
        "2022-01-01T00:15:00Z",
        high=101.9,
        low=101.0,
        open_=101.2,
        close=101.7,
    )
    bullish_lower = {**bullish_upper, "close": 101.3}
    bearish = {**bullish_upper, "open": 101.8, "close": 101.2}
    assert directional_half_close(bullish_upper, "LONG")
    assert not directional_half_close(bullish_lower, "LONG")
    assert not directional_half_close(bearish, "LONG")


def test_first_valid_retest_is_selected() -> None:
    turn = bar(
        "2022-01-01T00:10:00Z",
        "2022-01-01T00:15:00Z",
        high=101.9,
        low=101.0,
        open_=101.2,
        close=101.7,
    )
    first = bar(
        "2022-01-01T00:15:00Z",
        "2022-01-01T00:20:00Z",
        high=101.9,
        low=101.1,
        open_=101.6,
        close=101.8,
    )
    selected = first_confirmed_retest(
        [turn, first],
        direction="LONG",
        turn_bar=turn,
        zone={"lower": 100.9, "upper": 102.0, "invalidation": 100.5},
        session_end="2022-01-01T01:00:00Z",
        controlling_swing=PIVOT_LOW,
    )
    assert selected is not None
    assert selected["bar"]["open_at"] == "2022-01-01T00:15:00Z"


def test_failed_first_retest_cannot_be_repaired_by_later_bar() -> None:
    turn = bar(
        "2022-01-01T00:10:00Z",
        "2022-01-01T00:15:00Z",
        high=101.9,
        low=101.0,
        open_=101.2,
        close=101.7,
    )
    failed = bar(
        "2022-01-01T00:15:00Z",
        "2022-01-01T00:20:00Z",
        high=101.8,
        low=100.95,
        open_=101.6,
        close=101.5,
    )
    later = bar(
        "2022-01-01T00:20:00Z",
        "2022-01-01T00:25:00Z",
        high=102.1,
        low=101.3,
        open_=101.5,
        close=102.0,
    )
    assert first_confirmed_retest(
        [turn, failed, later],
        direction="LONG",
        turn_bar=turn,
        zone={"lower": 100.9, "upper": 102.0, "invalidation": 100.5},
        session_end="2022-01-01T01:00:00Z",
        controlling_swing=PIVOT_LOW,
    ) is None


def test_outcome_fields_are_impossible_in_semantic_payload() -> None:
    assert_outcome_blind({"entry": 100.0, "invalidation": 99.0, "destination": 102.0})
    with pytest.raises(RuntimeError):
        assert_outcome_blind({"net_r": 2.0})


def test_complete_synthetic_proof() -> None:
    proof = synthetic_proof()
    assert all(proof["checks"].values())
