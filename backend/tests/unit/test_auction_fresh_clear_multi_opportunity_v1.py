from __future__ import annotations

from copy import deepcopy

import gold_intel.analytics.auction_fresh_clear_multi_opportunity_v1 as subject


def _compiled(
    identity: str,
    *,
    decision_at: str,
    direction: str = "LONG",
    admitted: bool = True,
    alias: str = "CBR-2022-001",
) -> dict:
    return {
        "event_identity": identity,
        "case_alias": alias,
        "trading_date_utc": decision_at[:10],
        "decision_at": decision_at,
        "session": "NEW_YORK",
        "direction": direction,
        "event_class": "INITIAL_CONTROL",
        "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
        "admitted": admitted,
        "disposition": "ADMIT_FRESH_AND_CLEAR" if admitted else "SELECTOR_REJECT",
        "reasons": [],
        "admission_sha256": "admission" if admitted else None,
        "plan": {"event_identity": identity, "case_alias": alias, "direction": direction} if admitted else None,
        "plan_sha256": f"plan-{identity}",
        "compile_row_sha256": f"compile-{identity}",
    }


def _resolved(
    identity: str,
    *,
    fill_at: str,
    exit_at: str,
    net_r: float,
    planned_risk_usd: float = 50.0,
) -> dict:
    return {
        "event_identity": identity,
        "execution": {
            "fill_at": fill_at,
            "exit_at": exit_at,
            "displayed_planned_risk_usd": planned_risk_usd,
            "net_r50": net_r,
        },
    }


def test_compile_population_preserves_every_same_day_event_without_a_daily_cap():
    original_compile = subject.compile_trade_plan
    original_admission = subject.admission_decision
    try:
        subject.compile_trade_plan = lambda event, overlay: {
            "event_identity": event["event_identity"],
            "case_alias": "CBR-2022-001",
            "trading_date_utc": "2022-01-03",
            "decision_at": event["decision_at"],
            "session": "NEW_YORK",
            "direction": event["direction"],
            "event_class": "INITIAL_CONTROL",
            "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
            "eligible": True,
            "reasons": [],
            "plan_sha256": f"plan-{event['event_identity']}",
        }
        subject.admission_decision = lambda plan, policy: {
            "admitted": True,
            "reasons": [],
            "decision_sha256": f"admit-{plan['event_identity']}",
        }
        events = [
            {"event_identity": "e1", "decision_at": "2022-01-03T13:05:00Z", "direction": "LONG"},
            {"event_identity": "e2", "decision_at": "2022-01-03T13:10:00Z", "direction": "SHORT"},
            {"event_identity": "e3", "decision_at": "2022-01-03T13:15:00Z", "direction": "LONG"},
        ]
        overlays = [{"event_identity": identity} for identity in ("e1", "e2", "e3")]
        rows = subject.compile_transition_population(events, overlays)
        assert [row["event_identity"] for row in rows] == ["e1", "e2", "e3"]
        assert all(row["admitted"] for row in rows)
    finally:
        subject.compile_trade_plan = original_compile
        subject.admission_decision = original_admission


def test_all_valid_execution_keeps_overlapping_setups():
    compiled = [
        _compiled("e1", decision_at="2022-01-03T13:05:00Z"),
        _compiled("e2", decision_at="2022-01-03T13:10:00Z"),
    ]
    resolved = {
        "e1": _resolved("e1", fill_at="2022-01-03T13:06:00Z", exit_at="2022-01-03T13:30:00Z", net_r=1.0),
        "e2": _resolved("e2", fill_at="2022-01-03T13:11:00Z", exit_at="2022-01-03T13:20:00Z", net_r=-1.0),
    }
    calls: list[str] = []

    def resolver(plan, rows):
        calls.append(plan["event_identity"])
        return deepcopy(resolved[plan["event_identity"]])

    streams = {"CBR-2022-001": {"timeframes": {"1m": []}}}
    rows = subject.execute_all_admitted(compiled, streams, resolver)
    assert calls == ["e1", "e2"]
    assert [row["execution_disposition"] for row in rows] == [
        "EXECUTED_ALL_VALID_SIGNALS",
        "EXECUTED_ALL_VALID_SIGNALS",
    ]


def test_long_and_short_use_the_identical_execution_lifecycle():
    compiled = [
        _compiled("long", decision_at="2022-01-03T13:05:00Z", direction="LONG"),
        _compiled("short", decision_at="2022-01-03T13:10:00Z", direction="SHORT"),
    ]

    def resolver(plan, rows):
        identity = plan["event_identity"]
        minute = "06" if identity == "long" else "11"
        return _resolved(
            identity,
            fill_at=f"2022-01-03T13:{minute}:00Z",
            exit_at="2022-01-03T13:30:00Z",
            net_r=0.5,
        )

    streams = {"CBR-2022-001": {"timeframes": {"1m": []}}}
    rows = subject.execute_all_admitted(compiled, streams, resolver)
    assert [row["direction"] for row in rows] == ["LONG", "SHORT"]
    assert [row["execution_disposition"] for row in rows] == [
        "EXECUTED_ALL_VALID_SIGNALS",
        "EXECUTED_ALL_VALID_SIGNALS",
    ]


def test_nonoverlap_is_diagnostic_only_and_never_mutates_primary_rows():
    primary = []
    for identity, decision, fill, exit_at, result in (
        ("e1", "2022-01-03T13:05:00Z", "2022-01-03T13:06:00Z", "2022-01-03T13:30:00Z", 1.0),
        ("e2", "2022-01-03T13:10:00Z", "2022-01-03T13:11:00Z", "2022-01-03T13:20:00Z", -1.0),
        ("e3", "2022-01-03T13:35:00Z", "2022-01-03T13:36:00Z", "2022-01-03T13:45:00Z", 2.0),
    ):
        row = _compiled(identity, decision_at=decision)
        row.update(
            {
                "execution_disposition": "EXECUTED_ALL_VALID_SIGNALS",
                "result": _resolved(identity, fill_at=fill, exit_at=exit_at, net_r=result),
                "net_r50": result,
            }
        )
        primary.append(row)
    before = deepcopy(primary)
    diagnostic = subject.nonoverlap_diagnostic(primary)
    assert [row["disposition"] for row in diagnostic] == [
        "EXECUTED_NONOVERLAP_DIAGNOSTIC",
        "OVERLAP_SKIPPED_DIAGNOSTIC_ONLY",
        "EXECUTED_NONOVERLAP_DIAGNOSTIC",
    ]
    assert primary == before


def test_concurrency_reports_all_simultaneous_positions_and_planned_risk():
    rows = []
    for identity, fill, exit_at, risk in (
        ("e1", "2022-01-03T13:06:00Z", "2022-01-03T13:30:00Z", 40.0),
        ("e2", "2022-01-03T13:11:00Z", "2022-01-03T13:20:00Z", 50.0),
        ("e3", "2022-01-03T13:16:00Z", "2022-01-03T13:25:00Z", 45.0),
    ):
        row = _compiled(identity, decision_at=fill)
        row.update(
            {
                "execution_disposition": "EXECUTED_ALL_VALID_SIGNALS",
                "result": _resolved(identity, fill_at=fill, exit_at=exit_at, net_r=0.0, planned_risk_usd=risk),
                "net_r50": 0.0,
            }
        )
        rows.append(row)
    summary = subject.concurrency_summary(rows)
    assert summary["maximum_concurrent_positions"] == 3
    assert summary["maximum_concurrent_planned_risk_usd"] == 135.0
    assert summary["maximum_concurrent_planned_risk_r50"] == 2.7
