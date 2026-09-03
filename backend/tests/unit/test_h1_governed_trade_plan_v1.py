from __future__ import annotations

import copy

import pytest

from gold_intel.analytics.h1_governed_trade_plan_v1 import (
    assert_outcome_blind,
    compile_trade_plan,
    synthetic_plan_specs,
    synthetic_proof,
)


def specs_by_id() -> dict[str, dict]:
    return {item["sample_id"]: item for item in synthetic_plan_specs()}


def test_four_synthetic_plans_compile_symmetrically() -> None:
    proof = synthetic_proof()
    assert all(proof["checks"].values())


@pytest.mark.parametrize(
    ("sample_id", "timeframe", "kind", "policy"),
    [
        ("SYN_TREND_SHORT", "H1", "LOW", "PREEXISTING_UNCONSUMED_H1_LIQUIDITY_SWING"),
        ("SYN_TREND_LONG", "H1", "HIGH", "PREEXISTING_UNCONSUMED_H1_LIQUIDITY_SWING"),
        ("SYN_RANGE_SHORT", "M15", "LOW", "PREEXISTING_INTERNAL_M15_LIQUIDITY_NOT_RANGE_EXTREME"),
        ("SYN_RANGE_LONG", "M15", "HIGH", "PREEXISTING_INTERNAL_M15_LIQUIDITY_NOT_RANGE_EXTREME"),
    ],
)
def test_target_routing_is_exact(
    sample_id: str, timeframe: str, kind: str, policy: str
) -> None:
    plan = compile_trade_plan(specs_by_id()[sample_id])
    assert plan["destination"]["timeframe"] == timeframe
    assert plan["destination"]["kind"] == kind
    assert plan["destination"]["target_policy"] == policy


def test_range_target_cannot_be_opposite_extreme() -> None:
    spec = copy.deepcopy(specs_by_id()["SYN_RANGE_SHORT"])
    spec["destination"]["level"] = spec["h1_context"]["lower_boundary"]
    spec["destination"]["is_range_boundary"] = True
    with pytest.raises(ValueError):
        compile_trade_plan(spec)


def test_trend_target_must_be_h1() -> None:
    spec = copy.deepcopy(specs_by_id()["SYN_TREND_SHORT"])
    spec["destination"]["timeframe"] = "M15"
    with pytest.raises(ValueError, match="Trend destination must be an H1 swing"):
        compile_trade_plan(spec)


def test_future_known_destination_is_rejected() -> None:
    spec = copy.deepcopy(specs_by_id()["SYN_TREND_LONG"])
    spec["destination"]["known_at"] = "2024-01-09T14:31:00Z"
    with pytest.raises(ValueError, match="not known"):
        compile_trade_plan(spec)


def test_h1_is_not_allowed_to_be_the_entry_source() -> None:
    spec = copy.deepcopy(specs_by_id()["SYN_TREND_LONG"])
    spec["entry"]["source"] = "H1_PIVOT_CONFIRMATION"
    with pytest.raises(ValueError, match="completed M5 retest"):
        compile_trade_plan(spec)


def test_local_stop_must_be_beyond_m5_curvature() -> None:
    spec = copy.deepcopy(specs_by_id()["SYN_TREND_SHORT"])
    spec["invalidation"]["level"] = spec["m5_trigger"]["turn_extreme"]
    with pytest.raises(ValueError, match="local curvature"):
        compile_trade_plan(spec)


def test_outcome_fields_are_forbidden() -> None:
    assert_outcome_blind({"entry": 100.0, "target": 103.0})
    with pytest.raises(RuntimeError):
        assert_outcome_blind({"pnl": 2.0})

