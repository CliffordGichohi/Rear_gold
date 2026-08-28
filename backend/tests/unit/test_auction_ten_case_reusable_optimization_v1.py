from __future__ import annotations

from gold_intel.analytics.auction_ten_case_reusable_optimization_v1 import (
    ADMISSION_POLICIES,
    FORBIDDEN_SELECTOR_FIELDS,
    admission_decision,
    candidate_registry,
    managed_execution,
)


def _plan(direction: str = "LONG", *, event_class: str = "INITIAL_CONTROL", room_r: float = 2.0):
    entry = 100.0
    stop = 99.0 if direction == "LONG" else 101.0
    target = 103.0 if direction == "LONG" else 97.0
    return {
        "event_identity": "synthetic-event",
        "case_alias": "SYNTHETIC",
        "decision_at": "2022-01-03T13:00:00Z",
        "trading_date_utc": "2022-01-03",
        "direction": direction,
        "event_class": event_class,
        "entry": entry,
        "stop": stop,
        "target": {"level": target},
        "local_m15_liquidity": {"distance_price": room_r},
        "eligible": True,
    }


def _result(direction: str = "LONG", *, resolution: str = "TARGET_HIT"):
    actual_exit = 103.0 if direction == "LONG" else 97.0
    if resolution != "TARGET_HIT":
        actual_exit = 98.85 if direction == "LONG" else 101.15
    sign = 1.0 if direction == "LONG" else -1.0
    pnl = sign * (actual_exit - 100.0) * 50
    return {
        "execution": {
            "resolution": resolution,
            "fill_at": "2022-01-03T13:01:00Z",
            "exit_at": "2022-01-03T13:10:00Z",
            "actual_fill": 100.0,
            "actual_exit": actual_exit,
            "raw_exit": actual_exit,
            "quantity_ounces": 50,
            "net_pnl_usd": pnl,
            "net_r50": pnl / 50.0,
        }
    }


def _m1(direction: str = "LONG"):
    if direction == "LONG":
        return [
            {"open_at": "2022-01-03T13:05:00Z", "close_at": "2022-01-03T13:06:00Z", "available_at": "2022-01-03T13:06:00Z", "open": 101.20, "high": 101.40, "low": 101.10, "close": 101.30, "spread_price": 0.20, "complete": True},
            {"open_at": "2022-01-03T13:10:00Z", "close_at": "2022-01-03T13:11:00Z", "available_at": "2022-01-03T13:11:00Z", "open": 103.20, "high": 103.50, "low": 103.10, "close": 103.40, "spread_price": 0.20, "complete": True},
            {"open_at": "2022-01-03T13:11:00Z", "close_at": "2022-01-03T13:12:00Z", "available_at": "2022-01-03T13:12:00Z", "open": 103.10, "high": 103.20, "low": 102.90, "close": 103.00, "spread_price": 0.20, "complete": True},
        ]
    return [
        {"open_at": "2022-01-03T13:05:00Z", "close_at": "2022-01-03T13:06:00Z", "available_at": "2022-01-03T13:06:00Z", "open": 98.80, "high": 98.90, "low": 98.60, "close": 98.70, "spread_price": 0.20, "complete": True},
        {"open_at": "2022-01-03T13:10:00Z", "close_at": "2022-01-03T13:11:00Z", "available_at": "2022-01-03T13:11:00Z", "open": 96.80, "high": 96.90, "low": 96.50, "close": 96.60, "spread_price": 0.20, "complete": True},
        {"open_at": "2022-01-03T13:11:00Z", "close_at": "2022-01-03T13:12:00Z", "available_at": "2022-01-03T13:12:00Z", "open": 96.90, "high": 97.10, "low": 96.80, "close": 97.00, "spread_price": 0.20, "complete": True},
    ]


def _m5(direction: str = "LONG"):
    return [
        {
            "open_at": "2022-01-03T13:00:00Z",
            "close_at": "2022-01-03T13:05:00Z",
            "available_at": "2022-01-03T13:05:00Z",
            "close": 101.10 if direction == "LONG" else 98.90,
            "complete": True,
        }
    ]


def test_registry_is_bounded_symmetric_and_contains_no_forbidden_selector():
    registry = candidate_registry()
    assert len(registry) == 48
    assert len({row["candidate_id"] for row in registry}) == 48
    for row in registry:
        assert row["direction_symmetric"] is True
        assert not (set(row["selector_fields"]) & set(FORBIDDEN_SELECTOR_FIELDS))


def test_admission_uses_same_logic_for_long_and_short():
    for policy in ADMISSION_POLICIES:
        long = admission_decision(_plan("LONG", event_class="CONTINUATION_REFRESH", room_r=0.75), policy)
        short = admission_decision(_plan("SHORT", event_class="CONTINUATION_REFRESH", room_r=0.75), policy)
        assert long["admitted"] == short["admitted"]
        assert long["reasons"] == short["reasons"]


def test_zero_management_reproduces_baseline_execution_exactly():
    plan = _plan("LONG")
    result = _result("LONG")
    managed = managed_execution(
        plan=plan,
        baseline_result=result,
        m1_rows=_m1("LONG"),
        m5_rows=_m5("LONG"),
        early_fraction=0.0,
        runner_fraction=0.0,
    )
    assert managed["net_pnl_usd"] == result["execution"]["net_pnl_usd"]
    assert managed["net_r50"] == result["execution"]["net_r50"]


def test_completed_m5_partial_is_whole_ounce_and_direction_symmetric():
    outputs = []
    for direction in ("LONG", "SHORT"):
        output = managed_execution(
            plan=_plan(direction),
            baseline_result=_result(direction),
            m1_rows=_m1(direction),
            m5_rows=_m5(direction),
            early_fraction=0.25,
            runner_fraction=0.0,
        )
        outputs.append(output)
        assert output["early_realization_activated"] is True
        assert output["early_realization_quantity"] == 12
        assert sum(leg["quantity"] for leg in output["legs"]) == 50
    assert outputs[0]["net_r50"] == outputs[1]["net_r50"]


def test_target_runner_starts_after_target_bar_and_is_direction_symmetric():
    outputs = []
    for direction in ("LONG", "SHORT"):
        output = managed_execution(
            plan=_plan(direction),
            baseline_result=_result(direction),
            m1_rows=_m1(direction),
            m5_rows=_m5(direction),
            early_fraction=0.0,
            runner_fraction=0.25,
        )
        outputs.append(output)
        runner = next(leg for leg in output["legs"] if leg["kind"] == "POST_TARGET_RUNNER")
        assert output["target_runner_activated"] is True
        assert runner["exit_at"] == "2022-01-03T13:11:00Z"
        assert runner["resolution"] == "TARGET_FLOOR_RETURN"
        assert sum(leg["quantity"] for leg in output["legs"]) == 50
    assert outputs[0]["net_r50"] == outputs[1]["net_r50"]
