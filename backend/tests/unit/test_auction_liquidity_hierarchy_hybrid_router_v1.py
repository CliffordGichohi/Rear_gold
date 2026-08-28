from __future__ import annotations

import math

from gold_intel.analytics.auction_liquidity_hierarchy_hybrid_router_v1 import (
    resolve_risk_controlled,
    route_population,
)


def _plan(
    *,
    context: str = "TREND_PULLBACK_WITH_LTF_CONTROL",
    target_timeframe: str = "H1",
    target_level: float = 106.0,
    local_level: float | None = 104.0,
    target_known_at: str = "2022-01-03T08:00:00Z",
    event_class: str = "CONTINUATION_REFRESH",
) -> dict:
    local = None if local_level is None else {"level": local_level}
    return {
        "event_identity": "synthetic-event",
        "case_alias": "CBR-SYNTHETIC-001",
        "trading_date_utc": "2022-01-03",
        "decision_at": "2022-01-03T15:00:00Z",
        "session": "NEW_YORK",
        "direction": "LONG",
        "event_class": event_class,
        "context_family": context,
        "entry": 100.0,
        "stop": 98.0,
        "target": {
            "level": target_level,
            "timeframe": target_timeframe,
            "known_at": target_known_at,
        },
        "local_m15_liquidity": local,
        "risk_price": 2.0,
        "reward_price": target_level - 100.0,
        "planned_r": (target_level - 100.0) / 2.0,
        "plan_sha256": "original-plan",
    }


def _compiled(plan: dict) -> dict:
    return {
        "event_identity": plan["event_identity"],
        "case_alias": plan["case_alias"],
        "trading_date_utc": plan["trading_date_utc"],
        "decision_at": plan["decision_at"],
        "session": plan["session"],
        "direction": plan["direction"],
        "event_class": plan["event_class"],
        "context_family": plan["context_family"],
        "mechanically_executable": True,
        "disposition": "EXECUTABLE_ALL_TRANSITION",
        "hard_inexecutable_reasons": [],
        "ignored_former_quality_filters": [],
        "classification_sha256": "classification",
        "plan": plan,
        "plan_sha256": plan["plan_sha256"],
        "compile_row_sha256": "old",
    }


def _routed(**kwargs) -> dict:
    return route_population([_compiled(_plan(**kwargs))])[0]


def _bar(
    minute: str,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> dict:
    return {
        "open_at": f"2022-01-03T{minute}:00Z",
        "close_at": f"2022-01-03T{minute}:59Z",
        "available_at": f"2022-01-03T{minute}:59Z",
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "spread_price": 0.0,
        "complete": True,
    }


def test_range_context_preserves_before_all_later_rules():
    row = _routed(context="RANGE_OPPOSITE_HALF_WITH_LTF_CONTROL")
    assert row["hybrid_route_reason"] == "RANGE_CONTEXT_PRESERVE"
    assert row["hybrid_route_action"] == "PRESERVE"
    assert row["direction"] == "LONG"


def test_h4_destination_preserves_original_direction():
    row = _routed(target_timeframe="H4")
    assert row["hybrid_route_reason"] == "H4_DESTINATION_PRESERVE"
    assert row["hybrid_route_action"] == "PRESERVE"


def test_exact_local_m15_destination_match_preserves():
    row = _routed(target_level=104.0, local_level=104.0)
    assert (
        row["hybrid_route_reason"]
        == "LOCAL_M15_LEVEL_CONFIRMS_DESTINATION_PRESERVE"
    )
    assert row["direction"] == "LONG"


def test_destination_younger_than_four_hours_preserves():
    row = _routed(target_known_at="2022-01-03T12:00:01Z")
    assert row["hybrid_route_reason"] == "DESTINATION_AGE_LT_240M_PRESERVE"
    assert row["direction"] == "LONG"


def test_old_unconfirmed_h1_destination_negates_geometry_once():
    row = _routed()
    plan = row["plan"]
    assert row["hybrid_route_reason"] == "H1_UNCONFIRMED_AGE_GTE_240M_NEGATE"
    assert row["hybrid_route_action"] == "NEGATE"
    assert plan["direction"] == "SHORT"
    assert plan["stop"] == 106.0
    assert plan["target"]["level"] == 98.0
    assert plan["fixed_original_quantity"]["quantity_ounces"] == 25


def test_no_upsize_track_caps_selected_stop_exposure_and_executes_quantity():
    row = _routed()
    plan = row["plan"]
    route = plan["hybrid_route"]
    assert route["original_quantity_ounces"] == 25
    assert route["risk_controlled_quantity_ounces"] == 8
    assert route["risk_controlled_quantity_ounces"] <= route["original_quantity_ounces"]
    assert route["risk_controlled_stop_exposure_usd"] <= 50.0
    rows = [
        _bar("15:00", open_price=100.0, high=100.1, low=99.9, close=100.0),
        _bar("15:01", open_price=100.0, high=100.1, low=97.9, close=98.0),
    ]
    execution = resolve_risk_controlled(plan, rows)["execution"]
    assert execution["resolution"] == "TARGET_HIT"
    assert execution["quantity_ounces"] == 8
    assert math.isclose(execution["displayed_planned_risk_usd"], 48.0)
    assert execution["quantity_increased_after_routing"] is False


def test_non_continuation_plan_is_not_routed_or_rehashed():
    original = _plan(event_class="REVERSAL_TRANSFER")
    row = route_population([_compiled(original)])[0]
    assert row["hybrid_route_reason"] == "NON_CONTINUATION_UNCHANGED"
    assert row["hybrid_route_action"] == "PRESERVE"
    assert row["plan"] == original
    assert row["risk_controlled_quantity_ounces"] == 25
