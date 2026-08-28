from __future__ import annotations

from copy import deepcopy

import gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 as subject


def _plan(event: dict, reasons: list[str]) -> dict:
    return {
        "event_identity": event["event_identity"],
        "case_alias": "CBR-2022-001",
        "trading_date_utc": "2022-01-03",
        "decision_at": event["decision_at"],
        "session": "NEW_YORK",
        "direction": event["direction"],
        "event_class": event.get("event_class", "CONTINUATION_REFRESH"),
        "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
        "entry": 100.0,
        "stop": 99.0 if event["direction"] == "LONG" else 101.0,
        "target": {"level": 100.5 if event["direction"] == "LONG" else 99.5},
        "risk_price": 1.0,
        "reward_price": 0.5,
        "planned_r": 0.5,
        "eligible": not reasons,
        "reasons": reasons,
        "plan_sha256": f"plan-{event['event_identity']}",
    }


def _compiled(identity: str, decision_at: str, direction: str = "LONG") -> dict:
    event = {"event_identity": identity, "decision_at": decision_at, "direction": direction}
    plan = _plan(event, ["TARGET_ROOM_BELOW_1P5R"])
    return {
        "event_identity": identity,
        "case_alias": "CBR-2022-001",
        "trading_date_utc": "2022-01-03",
        "decision_at": decision_at,
        "session": "NEW_YORK",
        "direction": direction,
        "event_class": "CONTINUATION_REFRESH",
        "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
        "mechanically_executable": True,
        "disposition": "EXECUTABLE_ALL_TRANSITION",
        "hard_inexecutable_reasons": [],
        "ignored_former_quality_filters": ["TARGET_ROOM_BELOW_1P5R"],
        "classification_sha256": "classification",
        "plan": plan,
        "plan_sha256": plan["plan_sha256"],
        "compile_row_sha256": f"compile-{identity}",
    }


def _resolved(identity: str, fill_at: str, exit_at: str, net_r: float, risk: float = 50.0) -> dict:
    return {
        "event_identity": identity,
        "execution": {
            "fill_at": fill_at,
            "exit_at": exit_at,
            "displayed_planned_risk_usd": risk,
            "net_r50": net_r,
        },
    }


def test_reason_taxonomy_ignores_only_former_quality_filters_and_blocks_hard_failures():
    soft = subject.classify_reasons(
        ["DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR", "TARGET_ROOM_BELOW_1P5R"]
    )
    hard = subject.classify_reasons(["M5_PROTECTED_PIVOT_ALREADY_CONSUMED"])
    assert soft["mechanically_executable"] is True
    assert hard["mechanically_executable"] is False
    try:
        subject.classify_reasons(["UNREGISTERED_REASON"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("An unknown filter was silently accepted")


def test_compile_keeps_every_same_day_transition_without_a_daily_cap():
    original = subject.compile_trade_plan
    try:
        subject.compile_trade_plan = lambda event, overlay: _plan(
            event, ["TARGET_ROOM_BELOW_1P5R"]
        )
        events = [
            {"event_identity": "e1", "decision_at": "2022-01-03T13:05:00Z", "direction": "LONG"},
            {"event_identity": "e2", "decision_at": "2022-01-03T13:10:00Z", "direction": "SHORT"},
            {"event_identity": "e3", "decision_at": "2022-01-03T13:15:00Z", "direction": "LONG"},
        ]
        overlays = [{"event_identity": identity} for identity in ("e1", "e2", "e3")]
        rows = subject.compile_executable_population(events, overlays)
        assert [row["event_identity"] for row in rows] == ["e1", "e2", "e3"]
        assert all(row["mechanically_executable"] for row in rows)
    finally:
        subject.compile_trade_plan = original


def test_continuation_low_room_and_chased_entry_are_not_admission_filters():
    original = subject.compile_trade_plan
    try:
        subject.compile_trade_plan = lambda event, overlay: _plan(
            event,
            ["DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR", "TARGET_ROOM_BELOW_1P5R"],
        )
        event = {
            "event_identity": "continuation",
            "decision_at": "2022-01-03T13:05:00Z",
            "direction": "LONG",
            "event_class": "CONTINUATION_REFRESH",
        }
        row = subject.compile_executable_population([event], [{"event_identity": "continuation"}])[0]
        assert row["mechanically_executable"] is True
        assert row["event_class"] == "CONTINUATION_REFRESH"
        assert set(row["ignored_former_quality_filters"]) == {
            "DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR",
            "TARGET_ROOM_BELOW_1P5R",
        }
    finally:
        subject.compile_trade_plan = original


def test_every_executable_long_and_short_runs_even_when_holding_periods_overlap():
    rows = [
        _compiled("long", "2022-01-03T13:05:00Z", "LONG"),
        _compiled("short", "2022-01-03T13:10:00Z", "SHORT"),
    ]
    resolved = {
        "long": _resolved("long", "2022-01-03T13:06:00Z", "2022-01-03T13:30:00Z", 1.0),
        "short": _resolved("short", "2022-01-03T13:11:00Z", "2022-01-03T13:20:00Z", -1.0),
    }
    calls: list[str] = []

    def resolver(plan, bars):
        calls.append(plan["event_identity"])
        return deepcopy(resolved[plan["event_identity"]])

    streams = {"CBR-2022-001": {"timeframes": {"1m": []}}}
    output = subject.execute_every_executable(rows, streams, resolver)
    assert calls == ["long", "short"]
    assert all(row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS" for row in output)


def test_nonoverlap_comparison_skips_overlap_without_mutating_primary_execution():
    primary = []
    for identity, decision, fill, exit_at in (
        ("e1", "2022-01-03T13:05:00Z", "2022-01-03T13:06:00Z", "2022-01-03T13:30:00Z"),
        ("e2", "2022-01-03T13:10:00Z", "2022-01-03T13:11:00Z", "2022-01-03T13:20:00Z"),
        ("e3", "2022-01-03T13:35:00Z", "2022-01-03T13:36:00Z", "2022-01-03T13:45:00Z"),
    ):
        row = _compiled(identity, decision)
        row.update(
            {
                "execution_disposition": "EXECUTED_UNRESTRICTED_ALL_SIGNALS",
                "result": _resolved(identity, fill, exit_at, 1.0),
                "net_r50": 1.0,
            }
        )
        primary.append(row)
    before = deepcopy(primary)
    diagnostic = subject.matched_nonoverlap_diagnostic(primary)
    assert [row["disposition"] for row in diagnostic] == [
        "EXECUTED_NONOVERLAP_DIAGNOSTIC",
        "OVERLAP_SKIPPED_DIAGNOSTIC_ONLY",
        "EXECUTED_NONOVERLAP_DIAGNOSTIC",
    ]
    assert primary == before


def test_concurrency_counts_every_simultaneous_position_and_risk_budget():
    rows = []
    for identity, fill, exit_at, risk in (
        ("e1", "2022-01-03T13:06:00Z", "2022-01-03T13:30:00Z", 40.0),
        ("e2", "2022-01-03T13:11:00Z", "2022-01-03T13:20:00Z", 50.0),
        ("e3", "2022-01-03T13:16:00Z", "2022-01-03T13:25:00Z", 45.0),
    ):
        row = _compiled(identity, fill)
        row.update(
            {
                "execution_disposition": "EXECUTED_UNRESTRICTED_ALL_SIGNALS",
                "result": _resolved(identity, fill, exit_at, 0.0, risk),
                "net_r50": 0.0,
            }
        )
        rows.append(row)
    summary = subject.concurrency_summary(rows)
    assert summary["maximum_concurrent_positions"] == 3
    assert summary["maximum_concurrent_planned_risk_usd"] == 135.0
    assert summary["maximum_concurrent_planned_risk_r50"] == 2.7
