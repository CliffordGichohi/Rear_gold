from __future__ import annotations

from gold_intel.analytics.early_m5_curvature_entry_v1 import (
    match_to_census,
    resolve_decision,
    synthetic_proof,
    trigger_direction,
)


def _m5(minute: int, o: float, h: float, low: float, c: float) -> dict:
    return {
        "open_at": f"2022-01-03T00:{minute:02d}:00Z",
        "available_at": f"2022-01-03T00:{minute + 5:02d}:00Z",
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "complete": True,
    }


def test_synthetic_proof_passes() -> None:
    assert all(synthetic_proof().values())


def test_trigger_is_directionally_symmetric() -> None:
    long_rows = [
        _m5(0, 10.0, 10.2, 9.8, 10.1),
        _m5(5, 10.1, 10.15, 9.7, 9.8),
        _m5(10, 9.8, 9.85, 9.5, 9.6),
        _m5(15, 9.55, 10.0, 9.45, 9.9),
    ]
    short_rows = [
        _m5(0, 10.0, 10.2, 9.8, 9.9),
        _m5(5, 9.9, 10.3, 9.85, 10.2),
        _m5(10, 10.2, 10.5, 10.15, 10.4),
        _m5(15, 10.45, 10.55, 10.0, 10.1),
    ]
    assert trigger_direction(long_rows[:3], long_rows[3]) == "LONG"
    assert trigger_direction(short_rows[:3], short_rows[3]) == "SHORT"


def test_attribution_keeps_unmatched_false_triggers() -> None:
    decisions = [
        {
            "decision_identity": "MATCH",
            "trading_date_utc": "2022-01-03",
            "decision_at": "2022-01-03T10:05:00Z",
            "direction": "LONG",
        },
        {
            "decision_identity": "FALSE_POSITIVE",
            "trading_date_utc": "2022-01-03",
            "decision_at": "2022-01-03T12:05:00Z",
            "direction": "SHORT",
        },
    ]
    census = [
        {
            "combined_case_id": "CASE",
            "pivot_at_utc": "2022-01-03T10:15:00Z",
            "known_at_utc": "2022-01-03T10:45:00Z",
            "direction": "UP",
        }
    ]
    result = match_to_census(decisions, census)
    assert result["matched_count"] == 1
    assert result["unmatched_decision_ids"] == ["FALSE_POSITIVE"]


def test_lifecycle_uses_next_m1_and_stop_first_on_ambiguous_bar() -> None:
    decision = {
        "decision_identity": "D1",
        "case_alias": "SYNTHETIC",
        "trading_date_utc": "2022-01-03",
        "decision_at": "2022-01-03T10:00:00Z",
        "direction": "LONG",
        "family": "TREND_PULLBACK",
        "higher_timeframe_context": {"combined_alignment": "BOTH_ALIGNED"},
        "disposition": "ELIGIBLE_FOR_NEXT_M1_ENTRY",
        "geometry_at_decision": {
            "stop": 99.0,
            "destination": {"level": 102.0},
        },
    }
    stream = {
        "end_exclusive": "2022-01-04T00:00:00Z",
        "timeframes": {
            "1m": [
                {
                    "open_at": "2022-01-03T10:00:00Z",
                    "available_at": "2022-01-03T10:01:00Z",
                    "open": 100.0,
                    "high": 100.2,
                    "low": 99.8,
                    "close": 100.1,
                    "complete": True,
                    "spread_price": 0.2,
                },
                {
                    "open_at": "2022-01-03T10:01:00Z",
                    "available_at": "2022-01-03T10:02:00Z",
                    "open": 100.0,
                    "high": 102.1,
                    "low": 98.9,
                    "close": 101.0,
                    "complete": True,
                    "spread_price": 0.2,
                },
            ]
        },
    }
    result = resolve_decision(stream, decision)
    assert result["fill_at"] == "2022-01-03T10:01:00Z"
    assert result["resolution"] == "STOP_FIRST_AMBIGUOUS_M1"
    assert result["gross_unit_r"] == -1.0
