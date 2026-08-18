from __future__ import annotations

from copy import deepcopy

from gold_intel.backtesting.casebook_discovery_v2_relationships import (
    apply_v2_stability_and_lead_flags,
    hypothesis_classification,
    v2_relationship_rank_key,
)


def _record(*, session: str = "LONDON", feature: str = "macro_bias") -> dict:
    return {
        "relationship_type": "SINGLE",
        "relationship_id": feature,
        "state": "POSITIVE",
        "feature_ids": [feature],
        "session_code": session,
        "case_count": 100,
        "support_eligible": True,
        "selected_metrics": {
            "mean_net_return_basis_points": 2.0,
            "profit_factor": 1.2,
        },
        "excess_mean_net_return_vs_baseline_bps": 3.0,
        "cluster_bootstrap_95pct_ci_basis_points": [0.2, 3.8],
        "benjamini_hochberg_q_value": 0.05,
        "development_years": {
            "2021": {"adequate_support": True, "positive_mean": True},
            "2022": {"adequate_support": True, "positive_mean": True},
            "2023": {"adequate_support": True, "positive_mean": True},
            "2024": {"adequate_support": True, "positive_mean": False},
        },
        "positive_development_year_count": 3,
        "positive_chronological_half_count": 2,
    }


def test_v2_lead_requires_all_frozen_gates() -> None:
    record = _record()
    apply_v2_stability_and_lead_flags(
        [record],
        q_threshold=0.10,
        minimum_positive_years=3,
    )
    assert record["discovery_lead"] is True
    assert record["lead_gate_failures"] == []

    failed = _record()
    failed["cluster_bootstrap_95pct_ci_basis_points"][0] = 0.0
    apply_v2_stability_and_lead_flags(
        [failed],
        q_threshold=0.10,
        minimum_positive_years=3,
    )
    assert failed["discovery_lead"] is False
    assert "BOOTSTRAP_LOWER_BOUND_NOT_POSITIVE" in failed["lead_gate_failures"]


def test_known_single_zn_states_cannot_be_new_discovery_leads() -> None:
    for session, expected in (
        ("LONDON", "KNOWN_POSTHOC"),
        ("NEW_YORK", "PRIOR_REJECTED_RULE_COMPONENT"),
    ):
        record = _record(
            session=session,
            feature="cross_zn_v_0_4_hours",
        )
        apply_v2_stability_and_lead_flags(
            [record],
            q_threshold=0.10,
            minimum_positive_years=3,
        )
        assert record["hypothesis_classification"] == expected
        assert record["discovery_lead"] is False
        assert "KNOWN_HYPOTHESIS_EXCLUDED" in record["lead_gate_failures"]


def test_interaction_with_zn_is_not_the_excluded_single_rule() -> None:
    record = _record(feature="eurusd_4h_x_zn_4h")
    record["relationship_type"] = "INTERACTION"
    record["feature_ids"] = [
        "cross_eurusd_4_hours",
        "cross_zn_v_0_4_hours",
    ]
    classification, excluded, reason = hypothesis_classification(record)
    assert classification == "INHERITED_PREDECLARED_DEVELOPMENT_SCREEN"
    assert excluded is False
    assert reason is None


def test_v2_ranking_prefers_lead_then_lower_q() -> None:
    lead = _record(feature="lead")
    apply_v2_stability_and_lead_flags(
        [lead],
        q_threshold=0.10,
        minimum_positive_years=3,
    )
    nonlead = deepcopy(lead)
    nonlead["relationship_id"] = "nonlead"
    nonlead["discovery_lead"] = False
    assert v2_relationship_rank_key(lead) < v2_relationship_rank_key(nonlead)

    lower_q = deepcopy(lead)
    lower_q["relationship_id"] = "lower"
    lower_q["benjamini_hochberg_q_value"] = 0.01
    assert v2_relationship_rank_key(lower_q) < v2_relationship_rank_key(lead)
