from __future__ import annotations

import gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2_r1 as subject


def _plan(event: dict, reasons: list[str]) -> dict:
    return {
        "event_identity": event["event_identity"],
        "case_alias": "CBR-2022-001",
        "trading_date_utc": "2022-01-03",
        "decision_at": event["decision_at"],
        "session": "NEW_YORK",
        "direction": "LONG",
        "event_class": "CONTINUATION_REFRESH",
        "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
        "entry": 100.0,
        "stop": 99.0,
        "target": {"level": 100.5},
        "risk_price": 1.0,
        "reward_price": 0.5,
        "planned_r": 0.5,
        "eligible": not reasons,
        "reasons": reasons,
        "plan_sha256": f"plan-{event['event_identity']}",
    }


def _compile(decision_at: str, reasons: list[str]) -> dict:
    original = subject.compile_executable_population
    try:
        subject.compile_executable_population = lambda events, overlays: [
            {
                "event_identity": "event",
                "case_alias": "CBR-2022-001",
                "trading_date_utc": "2022-01-03",
                "decision_at": decision_at,
                "session": "NEW_YORK",
                "direction": "LONG",
                "event_class": "CONTINUATION_REFRESH",
                "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
                "mechanically_executable": True,
                "disposition": "EXECUTABLE_ALL_TRANSITION",
                "hard_inexecutable_reasons": [],
                "ignored_former_quality_filters": reasons,
                "classification_sha256": "old",
                "plan": _plan({"event_identity": "event", "decision_at": decision_at}, reasons),
                "plan_sha256": "plan-event",
                "compile_row_sha256": "old",
            }
        ]
        return subject.compile_executable_population_r1(
            [{"event_identity": "event"}], [{"event_identity": "event"}]
        )[0]
    finally:
        subject.compile_executable_population = original


def test_before_noon_remains_executable():
    row = _compile("2022-01-03T16:55:00Z", [])
    assert row["has_time_remaining_before_noon_deadline"] is True
    assert row["mechanically_executable"] is True
    assert row["plan"] is not None


def test_exactly_noon_is_hard_inexecutable_without_extending_deadline():
    row = _compile("2022-01-03T17:00:00Z", [])
    assert row["noon_deadline"] == "2022-01-03T17:00:00Z"
    assert row["has_time_remaining_before_noon_deadline"] is False
    assert row["mechanically_executable"] is False
    assert row["hard_inexecutable_reasons"] == [subject.NO_TIME_REASON]
    assert row["plan"] is None


def test_former_quality_filters_remain_ignored_before_noon():
    reasons = ["DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR", "TARGET_ROOM_BELOW_1P5R"]
    row = _compile("2022-01-03T16:55:00Z", reasons)
    assert row["mechanically_executable"] is True
    assert row["ignored_former_quality_filters"] == reasons
