from __future__ import annotations

from datetime import date, timedelta

import pytest

from gold_intel.analytics.session_behaviour_v3_discovery import FeatureObservation
from gold_intel.analytics.session_behaviour_v3_relationships import (
    DiscoveryCase,
    NeutralOutcome,
    apply_benjamini_hochberg,
    apply_candidate_gates,
    evaluate_condition,
    extract_neutral_outcome,
    fisher_exact_two_sided,
    newcombe_difference_interval,
    normalize_registered_feature_states,
    odds_ratio,
    path_profile,
    wilson_interval,
)


def _case(
    index: int,
    *,
    close_direction: str,
    feature_state: str,
    signed_close: float | None = None,
) -> DiscoveryCase:
    signed = (
        signed_close
        if signed_close is not None
        else 1.0
        if close_direction == "UP"
        else -1.0
        if close_direction == "DOWN"
        else 0.0
    )
    return DiscoveryCase(
        case_id=f"CASE-{index:03d}",
        record_hash=f"{index:064x}",
        session_code="LONDON",
        session_date=date(2022, 1, 3) + timedelta(days=index),
        features={
            "FEATURE": FeatureObservation(
                state=feature_state,
                source_signature=f"SOURCE-{index // 2:03d}",
                epistemic_status="CALCULATED",
                quality="VALID",
            )
        },
        outcome=NeutralOutcome(
            close_direction=close_direction,
            signed_close_displacement=signed,
            absolute_close_displacement=abs(signed),
            sixty_minute_direction=close_direction,
            maximum_upward_displacement=max(0.0, signed) + 1.0,
            maximum_downward_displacement_magnitude=max(0.0, -signed) + 1.0,
            session_range=abs(signed) + 2.0,
            extreme_order="LOW_FIRST" if close_direction == "UP" else "HIGH_FIRST",
        ),
    )


def test_neutral_outcome_uses_frozen_flat_threshold() -> None:
    subsequent = {
        "decision_eligible": False,
        "fixed_horizons": [
            {
                "horizon": "60m",
                "signed_displacement": {"value": 0.01},
            },
            {
                "horizon": "SESSION_CLOSE",
                "signed_displacement": {"value": -2.5},
            },
        ],
        "neutral_excursions": {
            "absolute_close_displacement": {"value": 2.5},
            "maximum_downward_displacement": {"value": -3.0},
            "maximum_upward_displacement": {"value": 1.5},
            "session_range": {"value": 4.5},
        },
        "extremes": {
            "extreme_order": {"value": "HIGH_FIRST"},
        },
    }

    outcome = extract_neutral_outcome(subsequent)

    assert outcome.close_direction == "DOWN"
    assert outcome.sixty_minute_direction == "FLAT"
    assert outcome.maximum_downward_displacement_magnitude == 3.0


def test_source_labels_are_normalized_only_to_frozen_registry_states() -> None:
    observations = {
        "MACRO_REACTION_FUNCTION": FeatureObservation(
            state="MIXED_MACRO_REACTION_FUNCTION",
            source_signature="macro",
            epistemic_status="INFERRED",
            quality="VALID",
        ),
        "STRUCT_1M_TREND": FeatureObservation(
            state="RANGE",
            source_signature="structure",
            epistemic_status="CALCULATED",
            quality="VALID",
        ),
    }

    normalized = normalize_registered_feature_states(observations)

    assert (
        normalized["MACRO_REACTION_FUNCTION"].state
        == "BALANCED_REACTION_FUNCTION"
    )
    assert normalized["STRUCT_1M_TREND"].state == "MIXED_OR_TRANSITIONING"
    assert (
        normalized["MACRO_REACTION_FUNCTION"].source_signature
        == observations["MACRO_REACTION_FUNCTION"].source_signature
    )


def test_fisher_wilson_newcombe_and_odds_ratio_are_deterministic() -> None:
    assert fisher_exact_two_sided(1, 9, 11, 3) == pytest.approx(
        0.0027594561852200836
    )
    assert wilson_interval(50, 100) == pytest.approx(
        [0.4038315303659957, 0.5961684696340044]
    )
    difference = newcombe_difference_interval(60, 100, 40, 100)
    assert difference[0] > 0
    assert difference[1] > difference[0]
    assert odds_ratio(10, 0, 5, 5) == pytest.approx(
        (10.5 * 5.5) / (0.5 * 5.5)
    )


def test_condition_support_and_all_path_metrics_reconcile() -> None:
    cases = [
        *[
            _case(i, close_direction="UP" if i < 70 else "DOWN", feature_state="ON")
            for i in range(100)
        ],
        *[
            _case(
                i,
                close_direction="UP" if i < 130 else "DOWN",
                feature_state="OFF",
            )
            for i in range(100, 200)
        ],
    ]
    condition = [case for case in cases if case.features["FEATURE"].state == "ON"]
    record = evaluate_condition(
        cases=cases,
        known_cases=cases,
        condition_cases=condition,
        condition_id="SINGLE__FEATURE__ON",
        conditions=[{"feature_id": "FEATURE", "state": "ON"}],
        stage="SINGLE",
        source_signatures=[
            case.features["FEATURE"].source_signature for case in condition
        ],
        state_episodes=10,
        support_policy={
            "condition_cases_minimum": 80,
            "condition_prevalence_pct_minimum": 10.0,
            "distinct_source_signatures_minimum": 8,
            "feature_known_coverage_pct_minimum": 50.0,
            "known_complement_cases_minimum": 80,
            "state_episodes_minimum": 8,
        },
    )

    assert record["support_eligible"] is True
    assert record["contingency"] == {
        "condition_up": 70,
        "condition_down": 30,
        "complement_up": 30,
        "complement_down": 70,
    }
    assert record["up_rate_difference_pp"] == 40.0
    assert record["condition_path_profile"]["case_count"] == 100
    assert record["known_complement_path_profile"]["case_count"] == 100
    assert path_profile(cases)["case_count"] == 200


def test_bh_and_candidate_gate_use_frozen_order_and_thresholds() -> None:
    records = []
    for index, p_value in enumerate((0.001, 0.02, 0.20), start=1):
        records.append(
            {
                "condition_id": f"CONDITION-{index}",
                "support_eligible": True,
                "fisher_exact_two_sided_p_value": p_value,
                "benjamini_hochberg_q_value": None,
            }
        )
    apply_benjamini_hochberg(records)
    assert [record["benjamini_hochberg_q_value"] for record in records] == [
        0.003,
        0.03,
        0.2,
    ]

    candidate = {
        "benjamini_hochberg_q_value": 0.03,
        "condition_id": "SINGLE__FEATURE__ON",
        "condition_path_profile": {"median_signed_close_displacement": 1.0},
        "conditions": [{"feature_id": "FEATURE", "state": "ON"}],
        "empirical_direction": "BULLISH",
        "newcombe_wilson_95pct_difference_pp": [1.0, 20.0],
        "stage": "SINGLE",
        "support_failures": [],
        "up_rate_difference_pp": 10.0,
    }
    apply_candidate_gates(
        [candidate],
        feature_map={
            "FEATURE": {
                "direction_hints": {"ON": 1},
            }
        },
        candidate_policy={},
    )
    assert candidate["candidate_gate_pass"] is True
    assert candidate["book_direction_hint_alignment"] == "ALIGNED"


def test_unknown_features_cannot_satisfy_a_condition() -> None:
    cases = [
        _case(
            index,
            close_direction="UP" if index % 2 == 0 else "DOWN",
            feature_state="UNKNOWN",
        )
        for index in range(100)
    ]
    record = evaluate_condition(
        cases=cases,
        known_cases=[],
        condition_cases=[],
        condition_id="SINGLE__FEATURE__ON",
        conditions=[{"feature_id": "FEATURE", "state": "ON"}],
        stage="SINGLE",
        source_signatures=[],
        state_episodes=0,
        support_policy={
            "condition_cases_minimum": 80,
            "condition_prevalence_pct_minimum": 10.0,
            "distinct_source_signatures_minimum": 8,
            "feature_known_coverage_pct_minimum": 50.0,
            "known_complement_cases_minimum": 80,
            "state_episodes_minimum": 8,
        },
    )

    assert record["support_eligible"] is False
    assert "FEATURE_KNOWN_COVERAGE_BELOW_MINIMUM" in record["support_failures"]
    assert record["fisher_exact_two_sided_p_value"] is None
