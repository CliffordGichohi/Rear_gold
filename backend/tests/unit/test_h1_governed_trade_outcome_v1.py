from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gold_intel.analytics.h1_governed_trade_outcome_v1 import evaluate_plan


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _plan(direction: str = "LONG") -> dict:
    if direction == "LONG":
        entry, stop, target = 100.0, 99.0, 102.0
    else:
        entry, stop, target = 100.0, 101.0, 98.0
    return {
        "plan_identity": f"PLAN-{direction}",
        "sample_id": f"SAMPLE-{direction}",
        "decision_at": "2022-01-03T10:00:00Z",
        "direction": direction,
        "family": "TREND",
        "entry": {"level": entry},
        "invalidation": {"level": stop},
        "destination": {"level": target},
    }


def _bar(index: int, high: float, low: float, close: float) -> dict:
    opened = datetime(2022, 1, 3, 10, 0, tzinfo=UTC) + timedelta(minutes=index)
    return {
        "bar_id": f"M1-{index}",
        "open_at": _iso(opened),
        "available_at": _iso(opened + timedelta(minutes=1)),
        "open": 100.0,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
    }


def test_long_target_first_returns_frozen_reward_r() -> None:
    outcome = evaluate_plan(
        _plan("LONG"),
        [_bar(0, 101.0, 99.5, 100.7), _bar(1, 102.1, 100.4, 102.0)],
        end_exclusive="2022-01-03T10:02:00Z",
    )
    assert outcome["disposition"] == "TARGET"
    assert outcome["gross_r"] == 2.0
    assert outcome["bars_observed"] == 2


def test_short_stop_first_returns_minus_one_r() -> None:
    outcome = evaluate_plan(
        _plan("SHORT"),
        [_bar(0, 100.4, 99.2, 99.5), _bar(1, 101.2, 99.0, 101.0)],
        end_exclusive="2022-01-03T10:02:00Z",
    )
    assert outcome["disposition"] == "STOP"
    assert outcome["gross_r"] == -1.0


def test_same_bar_stop_and_target_is_stop_first_ambiguous() -> None:
    outcome = evaluate_plan(
        _plan("LONG"),
        [_bar(0, 102.2, 98.8, 101.0)],
        end_exclusive="2022-01-03T10:01:00Z",
    )
    assert outcome["disposition"] == "STOP_FIRST_AMBIGUOUS"
    assert outcome["same_bar_ambiguous"] is True
    assert outcome["gross_r"] == -1.0


def test_month_end_mark_uses_signed_close_displacement() -> None:
    outcome = evaluate_plan(
        _plan("SHORT"),
        [_bar(0, 100.4, 99.4, 99.5), _bar(1, 100.0, 99.2, 99.25)],
        end_exclusive="2022-01-03T10:02:00Z",
    )
    assert outcome["disposition"] == "MONTH_END_MARK"
    assert outcome["gross_r"] == 0.75


def test_exact_decision_minute_is_required() -> None:
    with pytest.raises(ValueError, match="does not open at decision"):
        evaluate_plan(
            _plan("LONG"),
            [_bar(1, 101.0, 99.5, 100.5)],
            end_exclusive="2022-01-03T10:02:00Z",
        )
