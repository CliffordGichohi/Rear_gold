from copy import deepcopy

from gold_intel.analytics.auction_trade_placement_examples_v1 import compile_trade_plan


def _event(direction: str) -> dict:
    long = direction == "LONG"
    return {
        "event_identity": "event-1",
        "case_alias": "case-1",
        "trading_date_utc": "2022-01-03",
        "decision_at": "2022-01-03T13:10:00Z",
        "decision_price": 100.0,
        "direction": direction,
        "event_class": "INITIAL_CONTROL",
        "session": "NEW_YORK",
        "macro_context": {"state": "NEUTRAL_OR_CONFLICTED"},
        "higher_timeframe_context": {},
        "active_breaks": {
            "M15": {"direction": direction},
            "M5": {
                "direction": direction,
                "broken_identity": "broken",
                "broken_level": 99.5 if long else 100.5,
                "break_at": "2022-01-03T13:05:00Z",
                "atr": 1.0,
                "buffer": 0.1,
            },
        },
    }


def _overlay(direction: str) -> dict:
    long = direction == "LONG"
    protected_level = 98.0 if long else 102.0
    target_level = 104.0 if long else 96.0
    protected = {
        "identity": "protected",
        "kind": "LOW" if long else "HIGH",
        "timeframe": "M5",
        "pivot_at": "2022-01-03T12:55:00Z",
        "known_at": "2022-01-03T13:05:00Z",
        "level": protected_level,
        "state": "UNCONSUMED_UNTOUCHED",
    }
    target = {
        "identity": "target",
        "kind": "HIGH" if long else "LOW",
        "timeframe": "H1",
        "pivot_at": "2022-01-03T10:00:00Z",
        "known_at": "2022-01-03T12:00:00Z",
        "level": target_level,
        "distance_price": 4.0,
        "state": "UNCONSUMED_UNTOUCHED",
    }
    return {
        "event_identity": "event-1",
        "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
        "timeframes": {
            "M5": {"active_control_roles": {"protected_internal_pivot": protected}},
            "M15": {"nearest_unconsumed_destination": target},
            "H1": {"nearest_unconsumed_destination": target},
            "H4": {"nearest_unconsumed_destination": None},
        },
    }


def test_long_stop_is_beyond_protected_low_and_target_is_above() -> None:
    plan = compile_trade_plan(_event("LONG"), _overlay("LONG"))
    assert plan["eligible"] is True
    assert plan["stop"] == 97.9
    assert plan["target"]["level"] == 104.0
    assert plan["planned_r"] > 1.5


def test_short_stop_is_beyond_protected_high_and_target_is_below() -> None:
    plan = compile_trade_plan(_event("SHORT"), _overlay("SHORT"))
    assert plan["eligible"] is True
    assert plan["stop"] == 102.1
    assert plan["target"]["level"] == 96.0
    assert plan["planned_r"] > 1.5


def test_consumed_protected_pivot_rejects_plan() -> None:
    overlay = deepcopy(_overlay("LONG"))
    overlay["timeframes"]["M5"]["active_control_roles"]["protected_internal_pivot"][
        "state"
    ] = "CONSUMED"
    plan = compile_trade_plan(_event("LONG"), overlay)
    assert plan["eligible"] is False
    assert "M5_PROTECTED_PIVOT_ALREADY_CONSUMED" in plan["reasons"]


def test_chased_decision_price_rejects_plan() -> None:
    event = _event("LONG")
    event["active_breaks"]["M5"]["broken_level"] = 95.0
    plan = compile_trade_plan(event, _overlay("LONG"))
    assert plan["eligible"] is False
    assert "DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR" in plan["reasons"]

