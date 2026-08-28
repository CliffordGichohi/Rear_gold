from __future__ import annotations

import math

from gold_intel.analytics.hybrid_structural_execution_research_v1 import (
    POLICY_IDS,
    apply_sweep_reclaim_confirmation,
    completed_m5_bars,
    prepare_static_plan,
    resolve_prepared_plan,
    selected_quantity,
)


def _plan(*, direction: str = "LONG", local: bool = True) -> dict:
    stop = 90.0 if direction == "LONG" else 110.0
    target = 106.0 if direction == "LONG" else 94.0
    local_level = 98.0 if direction == "LONG" else 102.0
    return {
        "event_identity": "synthetic-event",
        "case_alias": "CBR-SYNTHETIC-001",
        "trading_date_utc": "2022-01-03",
        "decision_at": "2022-01-03T15:00:00Z",
        "session": "NEW_YORK",
        "direction": direction,
        "event_class": "CONTINUATION_REFRESH",
        "context_family": "TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL",
        "entry": 100.0,
        "stop": stop,
        "target": {"level": target, "known_at": "2022-01-03T14:00:00Z"},
        "local_m15_liquidity": (
            None
            if not local
            else {
                "level": local_level,
                "known_at": "2022-01-03T14:45:00Z",
                "kind": "LOW" if direction == "LONG" else "HIGH",
            }
        ),
        "risk_price": 10.0,
        "reward_price": 6.0,
        "planned_r": 0.6,
        "hybrid_route": {
            "action": "NEGATE",
            "risk_controlled_quantity_ounces": 5,
            "original_quantity_ounces": 25,
        },
        "plan_sha256": "old-plan",
    }


def _row(*, direction: str = "LONG", action: str = "NEGATE", local: bool = True) -> dict:
    plan = _plan(direction=direction, local=local)
    if action == "PRESERVE":
        plan["hybrid_route"] = {
            "action": "PRESERVE",
            "risk_controlled_quantity_ounces": 5,
            "original_quantity_ounces": 25,
        }
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
        "hybrid_route_reason": "SYNTHETIC",
        "hybrid_route_action": action,
        "original_direction": "SHORT" if direction == "LONG" else "LONG",
        "selected_direction": direction,
        "original_quantity_ounces": 25,
        "risk_controlled_quantity_ounces": 5,
        "risk_controlled_disposition": "EXECUTABLE_NO_UPSIZE",
    }


def _event() -> dict:
    return {
        "event_identity": "synthetic-event",
        "active_breaks": {"M15": {"buffer": 0.25}},
    }


def _bar(
    open_at: str,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> dict:
    from datetime import timedelta

    from gold_intel.analytics.coherent_auction_correction_v1 import iso, parse_dt

    point = parse_dt(open_at)
    close_at = point + timedelta(minutes=1)
    return {
        "bar_id": f"bar-{open_at}",
        "open_at": open_at,
        "close_at": iso(close_at),
        "available_at": iso(close_at),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "spread_price": 0.0,
        "complete": True,
    }


def test_registry_is_exact_three_by_three():
    assert len(POLICY_IDS) == 9
    assert len(set(POLICY_IDS)) == 9


def test_immediate_negated_plan_uses_local_m15_far_side_stop():
    prepared = prepare_static_plan(
        _row(),
        _event(),
        entry_mode="E1_IMMEDIATE_LOCAL_M15_INVALIDATION",
        exit_mode="T0_PRIMARY_LIQUIDITY_FULL",
    )
    assert prepared["disposition"] == "STATIC_PLAN_READY"
    assert prepared["plan"]["stop"] == 97.75
    assert math.isclose(prepared["plan"]["planned_r"], 6.0 / 2.25)


def test_missing_local_reference_is_no_trade_not_fabricated():
    prepared = prepare_static_plan(
        _row(local=False),
        _event(),
        entry_mode="E1_IMMEDIATE_LOCAL_M15_INVALIDATION",
        exit_mode="T0_PRIMARY_LIQUIDITY_FULL",
    )
    assert prepared["disposition"] == "NO_TRADE_UNRESOLVED_LOCAL_INVALIDATION"
    assert prepared["plan"] is None


def test_local_first_target_only_changes_preserved_direction():
    row = _row(action="PRESERVE")
    row["plan"]["local_m15_liquidity"]["level"] = 103.0
    prepared = prepare_static_plan(
        row,
        _event(),
        entry_mode="E0_CONTROL_MECHANICAL",
        exit_mode="T1_LOCAL_M15_FIRST_FULL",
    )
    assert prepared["plan"]["target"]["level"] == 103.0
    assert prepared["plan"]["target_replaced_by_local_m15"] is True


def test_m5_builder_requires_five_exact_consecutive_minutes():
    rows = [
        _bar(
            f"2022-01-03T15:0{minute}:00Z",
            open_price=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
        )
        for minute in range(5)
    ]
    bars = completed_m5_bars(
        rows,
        start_at="2022-01-03T15:00:00Z",
        end_at="2022-01-03T17:00:00Z",
    )
    assert len(bars) == 1
    assert bars[0]["close_at"] == "2022-01-03T15:05:00Z"
    assert completed_m5_bars(
        rows[:-1],
        start_at="2022-01-03T15:00:00Z",
        end_at="2022-01-03T17:00:00Z",
    ) == []


def test_sweep_reclaim_is_strict_and_uses_confirmation_extreme():
    prepared = prepare_static_plan(
        _row(),
        _event(),
        entry_mode="E2_M5_SWEEP_RECLAIM_POST_STRUCTURE",
        exit_mode="T0_PRIMARY_LIQUIDITY_FULL",
    )
    prices = [100.0, 99.0, 97.5, 98.2, 98.5]
    rows = [
        _bar(
            f"2022-01-03T15:0{minute}:00Z",
            open_price=prices[minute],
            high=prices[minute] + 0.2,
            low=prices[minute] - 0.2,
            close=prices[minute],
        )
        for minute in range(5)
    ]
    confirmed = apply_sweep_reclaim_confirmation(prepared["plan"], rows)
    assert confirmed is not None
    assert confirmed["decision_at"] == "2022-01-03T15:05:00Z"
    assert math.isclose(confirmed["entry"], 98.5)
    assert math.isclose(confirmed["stop"], 97.05)


def test_no_close_reclaim_produces_no_confirmation():
    prepared = prepare_static_plan(
        _row(),
        _event(),
        entry_mode="E2_M5_SWEEP_RECLAIM_POST_STRUCTURE",
        exit_mode="T0_PRIMARY_LIQUIDITY_FULL",
    )
    rows = [
        _bar(
            f"2022-01-03T15:0{minute}:00Z",
            open_price=97.5,
            high=97.9,
            low=97.0,
            close=97.5,
        )
        for minute in range(5)
    ]
    assert apply_sweep_reclaim_confirmation(prepared["plan"], rows) is None


def test_selected_quantity_caps_risk_and_never_upsizes():
    prepared = prepare_static_plan(
        _row(),
        _event(),
        entry_mode="E1_IMMEDIATE_LOCAL_M15_INVALIDATION",
        exit_mode="T0_PRIMARY_LIQUIDITY_FULL",
    )
    assert selected_quantity(prepared["plan"]) == 22
    assert selected_quantity(prepared["plan"]) <= 25
    assert selected_quantity(prepared["plan"]) * 2.25 <= 50.0


def test_partial_at_one_r_retains_half_after_later_stop():
    prepared = prepare_static_plan(
        _row(),
        _event(),
        entry_mode="E1_IMMEDIATE_LOCAL_M15_INVALIDATION",
        exit_mode="T2_HALF_AT_1R_THEN_PRIMARY",
    )
    rows = [
        _bar(
            "2022-01-03T15:01:00Z",
            open_price=100.0,
            high=100.1,
            low=99.9,
            close=100.0,
        ),
        _bar(
            "2022-01-03T15:02:00Z",
            open_price=100.0,
            high=102.5,
            low=99.9,
            close=102.2,
        ),
        _bar(
            "2022-01-03T15:03:00Z",
            open_price=102.2,
            high=102.3,
            low=97.5,
            close=97.8,
        ),
    ]
    resolved = resolve_prepared_plan(prepared, rows)
    execution = resolved["result"]["execution"]
    assert execution["resolution"] == "PARTIAL_THEN_STOPPED"
    assert execution["partial_filled"] is True
    assert execution["partial_quantity_ounces"] == 11
    assert execution["quantity_ounces"] == 22
    assert execution["displayed_planned_risk_usd"] <= 50.0
