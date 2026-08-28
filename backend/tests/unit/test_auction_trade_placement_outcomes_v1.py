from gold_intel.analytics.auction_trade_placement_outcomes_v1 import (
    execution_outcome,
    structural_first_passage,
)


def _plan(direction: str = "LONG") -> dict:
    return {
        "event_identity": "event-1",
        "case_alias": "case-1",
        "decision_at": "2022-01-03T13:10:00Z",
        "direction": direction,
        "entry": 100.0,
        "stop": 98.0 if direction == "LONG" else 102.0,
        "target": {"level": 104.0 if direction == "LONG" else 96.0},
        "planned_r": 2.0,
        "plan_sha256": "plan",
    }


def _bar(minute: int, *, open_: float, high: float, low: float, close: float) -> dict:
    stamp = f"2022-01-03T13:{minute:02d}:00Z"
    close_at = f"2022-01-03T13:{minute + 1:02d}:00Z"
    return {
        "open_at": stamp,
        "close_at": close_at,
        "available_at": close_at,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "spread_price": 0.20,
    }


def test_structural_target_first_long() -> None:
    rows = [_bar(10, open_=100, high=101, low=99, close=100.5), _bar(11, open_=100.5, high=104, low=100, close=103)]
    result = structural_first_passage(_plan("LONG"), rows)
    assert result["resolution"] == "TARGET_FIRST"
    assert result["gross_r"] == 2.0


def test_same_bar_is_stop_first() -> None:
    rows = [_bar(10, open_=100, high=105, low=97, close=101)]
    result = structural_first_passage(_plan("LONG"), rows)
    assert result["resolution"] == "STOP_FIRST"
    assert result["ambiguous_stop_first"] is True


def test_structural_short_is_direction_symmetric() -> None:
    rows = [_bar(10, open_=100, high=101, low=95, close=96)]
    result = structural_first_passage(_plan("SHORT"), rows)
    assert result["resolution"] == "TARGET_FIRST"
    assert result["gross_r"] == 2.0


def test_execution_applies_latency_spread_slippage_and_whole_ounces() -> None:
    rows = [
        _bar(10, open_=100, high=101, low=99, close=100),
        _bar(11, open_=100, high=101, low=99, close=100),
        _bar(12, open_=100, high=104, low=100, close=103),
    ]
    result = execution_outcome(_plan("LONG"), rows)
    assert result["fill_at"] == "2022-01-03T13:11:00Z"
    assert abs(result["actual_fill"] - 100.15) < 1e-9
    assert result["quantity_ounces"] == 25
    assert result["resolution"] == "TARGET_HIT"
