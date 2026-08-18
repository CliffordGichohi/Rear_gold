from __future__ import annotations

from datetime import UTC, date, datetime

from gold_intel.backtesting.casebook_discovery_v2_walk_forward import (
    WalkForwardCase,
    build_window_report,
    cluster_sign_flip_p_value,
    evaluate_aggregate_gates,
    evaluate_test_gates,
    selected_observation,
)


def _case(
    number: int,
    *,
    state: str,
    gross: float,
    cost: float = 0.2,
) -> WalkForwardCase:
    side_pnl = gross - cost if state == "POSITIVE" else -gross - cost
    opposite_pnl = -gross - cost if state == "POSITIVE" else gross - cost
    return WalkForwardCase(
        case_id=f"CASE-{number}",
        case_record_hash=f"HASH-{number}",
        session_date=date(2022, 1, number),
        decision_at=datetime(2022, 1, number, 8, tzinfo=UTC),
        feature_state=state,
        raw_percent_change=0.1 if state == "POSITIVE" else -0.1,
        feature_source_key=f"SOURCE-{number}",
        reference_entry_price=2000.0,
        gross_move_usd_per_ounce=gross,
        cost_usd_per_ounce=cost,
        long_net_pnl_usd_per_ounce=(side_pnl if state == "POSITIVE" else opposite_pnl),
        long_net_return_basis_points=(5 * (side_pnl if state == "POSITIVE" else opposite_pnl)),
        short_net_pnl_usd_per_ounce=(opposite_pnl if state == "POSITIVE" else side_pnl),
        short_net_return_basis_points=(5 * (opposite_pnl if state == "POSITIVE" else side_pnl)),
    )


def test_selected_observation_applies_frozen_mapping_and_cost_stress() -> None:
    positive = _case(1, state="POSITIVE", gross=1.0)
    negative = _case(2, state="NEGATIVE", gross=-1.0)
    assert selected_observation(positive).side == "LONG"
    assert selected_observation(negative).side == "SHORT"
    assert (
        selected_observation(
            positive,
            cost_multiplier=1.5,
        ).net_pnl_usd_per_ounce
        == 0.7
    )


def test_window_and_test_gates_are_directionally_symmetric() -> None:
    cases = [
        _case(1, state="POSITIVE", gross=1.0),
        _case(2, state="NEGATIVE", gross=-1.0),
        _case(3, state="POSITIVE", gross=-0.1),
        _case(4, state="NEGATIVE", gross=0.1),
    ]
    report = build_window_report(
        cases,
        manifest_hash="manifest",
        candidate_code="candidate",
        window_id="window",
        bootstrap_replications=20,
        sign_flip_replications=20,
        stress_multiplier=1.5,
    )
    gates = evaluate_test_gates(
        report,
        minimum_directional_cases=4,
        minimum_state_cases=2,
        minimum_state_week_clusters=1,
    )
    assert report["selector_metrics"]["mean_net_pnl_usd_per_ounce"] == 0.25
    assert report["state_results"]["POSITIVE"]["bias"] == "LONG"
    assert report["state_results"]["NEGATIVE"]["bias"] == "SHORT"
    assert gates["passed"] is True


def test_cluster_sign_flip_is_deterministic() -> None:
    observations = [
        selected_observation(_case(1, state="POSITIVE", gross=1.0)),
        selected_observation(_case(2, state="NEGATIVE", gross=-1.0)),
    ]
    usable = [item for item in observations if item is not None]
    first = cluster_sign_flip_p_value(
        usable,
        replications=100,
        seed_material="frozen",
    )
    second = cluster_sign_flip_p_value(
        usable,
        replications=100,
        seed_material="frozen",
    )
    assert first == second


def test_aggregate_verdict_requires_every_fold() -> None:
    report = {
        "cluster_bootstrap_95pct_ci_mean_net_return_basis_points": [0.1, 1.0],
        "benjamini_hochberg_q_value": 0.05,
    }
    passed = evaluate_aggregate_gates(
        [
            {
                "fold_id": "F01",
                "training_gates": {"passed": True},
                "test_gates": {"passed": True},
            }
        ],
        aggregate_report=report,
        q_threshold=0.1,
        integrity_passed=True,
    )
    assert passed["passed"] is True

    failed = evaluate_aggregate_gates(
        [
            {
                "fold_id": "F01",
                "training_gates": {"passed": True},
                "test_gates": {"passed": False},
            }
        ],
        aggregate_report=report,
        q_threshold=0.1,
        integrity_passed=True,
    )
    assert failed["passed"] is False
