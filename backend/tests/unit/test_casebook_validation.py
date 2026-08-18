from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from gold_intel.backtesting.casebook_baseline import BaselineTrade
from gold_intel.backtesting.casebook_validation import (
    PASS_VERDICT,
    REJECT_VERDICT,
    apply_cost_multiplier,
    evaluate_validation_gates,
)


def _trade() -> BaselineTrade:
    return BaselineTrade(
        case_id="CASE-1",
        case_record_hash="a" * 64,
        session_code="LONDON",
        session_date=date(2024, 1, 2),
        control_code="ALWAYS_LONG",
        side="LONG",
        decision_at=datetime(2024, 1, 2, 8, tzinfo=UTC),
        entry_time=datetime(2024, 1, 2, 8, 1, tzinfo=UTC),
        exit_time=datetime(2024, 1, 2, 12, tzinfo=UTC),
        holding_minutes=239,
        entry_bar_id="ENTRY",
        entry_bar_hash="b" * 64,
        exit_bar_id="EXIT",
        exit_bar_hash="c" * 64,
        reference_entry_price=2000.0,
        reference_exit_price=2002.0,
        executed_entry_price=2000.10,
        executed_exit_price=2001.90,
        entry_spread_price=0.10,
        exit_spread_price=0.10,
        quantity_ounces=1.0,
        quantity_lots=0.01,
        gross_pnl_usd=2.0,
        spread_cost_usd=0.10,
        slippage_cost_usd=0.10,
        commission_usd=0.07,
        total_cost_usd=0.27,
        net_pnl_usd=1.73,
        gross_return_basis_points=10.0,
        net_return_basis_points=8.65,
        execution_manifest_hash="d" * 64,
    )


def test_cost_multiplier_scales_every_declared_cost() -> None:
    stressed = apply_cost_multiplier(_trade(), multiplier=1.5)

    assert stressed.spread_cost_usd == pytest.approx(0.15)
    assert stressed.slippage_cost_usd == pytest.approx(0.15)
    assert stressed.commission_usd == pytest.approx(0.105)
    assert stressed.total_cost_usd == pytest.approx(0.405)
    assert stressed.net_pnl_usd == pytest.approx(1.595)
    assert stressed.net_return_basis_points == pytest.approx(7.975)
    assert stressed.executed_entry_price == pytest.approx(2000.15)
    assert stressed.executed_exit_price == pytest.approx(2001.85)


def test_cost_multiplier_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        apply_cost_multiplier(_trade(), multiplier=-1)


def _session_report() -> dict[str, object]:
    return {
        "selector_metrics": {
            "observations": 120,
            "mean_net_return_basis_points": 2.0,
            "profit_factor": 1.2,
        },
        "selector_excess_mean_net_return_vs_best_control_bps": 1.0,
        "best_validation_unconditional_control": "ALWAYS_LONG",
        "directional_state_results": {
            "POSITIVE": {
                "case_count": 60,
                "iso_week_cluster_count": 30,
                "metrics": {"mean_net_return_basis_points": 2.0},
            },
            "NEGATIVE": {
                "case_count": 60,
                "iso_week_cluster_count": 30,
                "metrics": {"mean_net_return_basis_points": 1.0},
            },
        },
        "chronological_halves": {
            "EARLY": {"mean_net_return_basis_points": 1.0},
            "LATE": {"mean_net_return_basis_points": 2.0},
        },
        "cost_stress_1_5x": {"mean_net_pnl_usd_per_ounce": 0.2},
    }


def test_all_frozen_gates_must_pass() -> None:
    reports = {
        "LONDON": _session_report(),
        "NEW_YORK": _session_report(),
    }

    verdict = evaluate_validation_gates(
        reports,
        integrity_passed=True,
        minimum_directional_cases=100,
        minimum_state_cases=40,
        minimum_state_week_clusters=20,
    )

    assert verdict["all_gates_passed"] is True
    assert verdict["verdict"] == PASS_VERDICT
    assert verdict["passed_gate_count"] == 10


def test_one_failed_half_rejects_without_partial_promotion() -> None:
    london = _session_report()
    new_york = _session_report()
    new_york["chronological_halves"]["LATE"][  # type: ignore[index]
        "mean_net_return_basis_points"
    ] = -0.1

    verdict = evaluate_validation_gates(
        {"LONDON": london, "NEW_YORK": new_york},
        integrity_passed=True,
        minimum_directional_cases=100,
        minimum_state_cases=40,
        minimum_state_week_clusters=20,
    )

    assert verdict["all_gates_passed"] is False
    assert verdict["verdict"] == REJECT_VERDICT
    assert verdict["failed_gate_ids"] == [
        "G09_CHRONOLOGICAL_HALF_STABILITY"
    ]
