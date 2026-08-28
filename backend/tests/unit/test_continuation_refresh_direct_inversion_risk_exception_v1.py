from __future__ import annotations

import gold_intel.analytics.continuation_refresh_direct_inversion_risk_exception_v1 as subject


def _plan(identity: str, stop: float = 152.0) -> dict:
    return {
        "event_identity": identity,
        "case_alias": "CBR-2022-001",
        "decision_at": "2022-01-03T15:00:00Z",
        "direction": "SHORT",
        "event_class": "CONTINUATION_REFRESH",
        "entry": 100.0,
        "stop": stop,
        "target": {"level": 90.0},
        "planned_r": 10.0 / abs(stop - 100.0),
        "plan_sha256": "plan",
        "direct_inversion": {"tp_became_sl": True, "sl_became_tp": True},
    }


def _bars() -> list[dict]:
    return [
        {
            "open_at": "2022-01-03T15:01:00Z",
            "close_at": "2022-01-03T15:02:00Z",
            "available_at": "2022-01-03T15:02:00Z",
            "open": 100.0,
            "high": 101.0,
            "low": 89.0,
            "close": 90.0,
            "spread_price": 0.20,
            "complete": True,
        }
    ]


def test_exact_exception_uses_one_ounce_and_preserves_50_dollar_r_reporting():
    identity = sorted(subject.EXCEPTION_IDENTITIES)[0]
    result = subject.resolve_plan_with_bounded_exception(_plan(identity), _bars())
    execution = result["execution"]
    assert execution["quantity_ounces"] == 1
    assert execution["displayed_planned_risk_usd"] == 52.0
    assert execution["bounded_risk_exception_applied"] is True
    assert execution["net_r50"] == execution["net_pnl_usd"] / 50.0


def test_exception_above_53_01_is_rejected():
    identity = sorted(subject.EXCEPTION_IDENTITIES)[0]
    try:
        subject.resolve_plan_with_bounded_exception(_plan(identity, stop=154.0), _bars())
    except RuntimeError as exc:
        assert "exceeds $53.01 cap" in str(exc)
    else:
        raise AssertionError("Risk above the authorized cap was accepted")


def test_non_exception_delegates_to_the_unchanged_resolver():
    original = subject.base.resolve_plan
    try:
        subject.base.resolve_plan = lambda plan, rows: {"delegated": plan["event_identity"]}
        assert subject.resolve_plan_with_bounded_exception(_plan("ordinary"), []) == {
            "delegated": "ordinary"
        }
    finally:
        subject.base.resolve_plan = original


def test_exception_registry_is_exactly_three_frozen_identities():
    assert len(subject.EXCEPTION_IDENTITIES) == 3
    assert subject.MAX_EXCEPTION_DISPLAYED_RISK_USD == 53.01
    assert subject.EXCEPTION_QUANTITY_OUNCES == 1
