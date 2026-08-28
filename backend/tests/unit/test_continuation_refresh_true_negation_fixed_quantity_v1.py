from __future__ import annotations

import math

import gold_intel.analytics.auction_trade_placement_outcomes_v1 as base
from gold_intel.analytics.continuation_refresh_direct_inversion_v1 import (
    apply_inversion_population,
)
from gold_intel.analytics.continuation_refresh_true_negation_fixed_quantity_v1 import (
    attach_original_quantities,
    resolve_plan_fixed_original_quantity,
)


def _plan(
    direction: str,
    *,
    event_class: str = "CONTINUATION_REFRESH",
    tiny_original_target: bool = True,
) -> dict:
    if direction == "LONG":
        stop = 98.0
        target = 100.01 if tiny_original_target else 106.0
    else:
        stop = 102.0
        target = 99.99 if tiny_original_target else 94.0
    return {
        "event_identity": f"{direction.lower()}-{event_class.lower()}",
        "case_alias": "CBR-SYNTHETIC-001",
        "trading_date_utc": "2022-01-03",
        "decision_at": "2022-01-03T15:00:00Z",
        "session": "NEW_YORK",
        "direction": direction,
        "event_class": event_class,
        "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
        "entry": 100.0,
        "stop": stop,
        "target": {"level": target},
        "risk_price": 2.0,
        "reward_price": abs(target - 100.0),
        "planned_r": abs(target - 100.0) / 2.0,
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


def _inverted_with_fixed_quantity(direction: str) -> dict:
    inverted = apply_inversion_population([_compiled(_plan(direction))])
    return attach_original_quantities(inverted)[0]


def test_long_origin_freezes_25_ounces_instead_of_resizing_to_5000():
    row = _inverted_with_fixed_quantity("LONG")
    plan = row["plan"]
    fixed = plan["fixed_original_quantity"]
    assert plan["direction"] == "SHORT"
    assert plan["stop"] == 100.01
    assert plan["target"]["level"] == 98.0
    assert fixed["quantity_ounces"] == 25
    assert fixed["quantity_ounces"] == math.floor(50.0 / abs(100.0 - 98.0))
    assert fixed["quantity_ounces"] != math.floor(50.0 / abs(100.01 - 100.0))
    assert fixed["quantity_recalculated_after_inversion"] is False


def test_fixed_quantity_executor_uses_original_25_ounces_not_5000():
    plan = _inverted_with_fixed_quantity("LONG")["plan"]
    rows = [
        _bar("15:00", open_price=100.0, high=100.005, low=99.9, close=100.0),
        _bar("15:01", open_price=100.0, high=100.005, low=97.9, close=98.0),
    ]
    result = resolve_plan_fixed_original_quantity(plan, rows)
    execution = result["execution"]
    assert execution["resolution"] == "TARGET_HIT"
    assert execution["quantity_ounces"] == 25
    assert math.isclose(execution["displayed_planned_risk_usd"], 0.25)
    assert math.isclose(execution["original_displayed_planned_risk_usd"], 50.0)
    assert math.isclose(execution["net_pnl_usd"], 48.75)
    assert math.isclose(execution["net_r50"], 0.975)
    assert execution["quantity_recalculated_after_inversion"] is False


def test_short_origin_freezes_original_quantity_after_becoming_long():
    row = _inverted_with_fixed_quantity("SHORT")
    plan = row["plan"]
    fixed = plan["fixed_original_quantity"]
    assert plan["direction"] == "LONG"
    assert plan["stop"] == 99.99
    assert plan["target"]["level"] == 102.0
    assert fixed["quantity_ounces"] == 25
    assert fixed["quantity_recalculated_after_inversion"] is False


def test_non_continuation_execution_delegates_unchanged_to_frozen_control():
    plan = _plan(
        "LONG",
        event_class="REVERSAL_TRANSFER",
        tiny_original_target=False,
    )
    row = attach_original_quantities(
        apply_inversion_population([_compiled(plan)])
    )[0]
    rows = [
        _bar("15:00", open_price=100.0, high=100.5, low=99.5, close=100.0),
        _bar("15:01", open_price=100.0, high=106.1, low=99.5, close=106.0),
    ]
    assert row["continuation_directly_inverted"] is False
    assert resolve_plan_fixed_original_quantity(row["plan"], rows) == base.resolve_plan(
        row["plan"], rows
    )
