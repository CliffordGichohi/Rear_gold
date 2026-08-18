from __future__ import annotations

from copy import deepcopy

from gold_intel.analytics.session_behaviour_v3_m6a import (
    M5_SHORTLIST_CODES,
    approximate_two_proportion_power,
    assess_candidate_partition_metadata,
    balanced_cases_per_group_for_power,
    forward_candidate_registry,
    forward_protocol,
    prospective_metadata_plan,
    protocol_fingerprint,
    validate_forward_protocol,
)


def test_forward_registry_preserves_exact_m5_shortlist() -> None:
    candidates = forward_candidate_registry()

    assert tuple(item["candidate_code"] for item in candidates) == (
        M5_SHORTLIST_CODES
    )
    assert [item["session_code"] for item in candidates] == [
        "LONDON",
        "NEW_YORK",
    ]
    assert {item["feature_id"] for item in candidates} == {
        "MACRO_VOLATILITY_CHANGE",
        "MACRO_FINANCIAL_STRESS_CHANGE",
    }
    assert all(item["condition_state"] == "FALLING" for item in candidates)
    assert all(item["complement_state"] == "RISING" for item in candidates)
    assert all(item["excluded_known_states"] == ["UNCHANGED"] for item in candidates)
    assert all(item["minimum_material_effect_pp"] == 7.5 for item in candidates)
    assert validate_forward_protocol() == []
    assert len(protocol_fingerprint()) == 64


def test_forward_protocol_freezes_symmetric_verdicts_and_two_member_holm() -> None:
    protocol = forward_protocol()

    assert protocol["multiplicity"] == {
        "method": "HOLM_BONFERRONI_STEP_DOWN",
        "family": "EXACT_TWO_FROZEN_CANDIDATES_PER_SEGMENT",
        "family_size_fixed": 2,
        "family_alpha": 0.10,
        "unsupported_candidate_raw_p_value": 1.0,
        "candidate_or_segment_removal_permitted": False,
    }
    verdicts = protocol["segment_verdicts"]
    assert verdicts["PASS_MATERIAL_POSITIVE_REPLICATION"]["effect_pp_minimum"] == 7.5
    assert (
        verdicts["REJECT_MATERIAL_REVERSE_REPLICATION"]["effect_pp_maximum"]
        == -7.5
    )
    assert protocol["prohibited"]["holdout_values_or_outcomes_in_m6a"] is True
    assert protocol["prohibited"]["execution_optimization"] is True
    assert protocol["prohibited"]["cot_as_pass_gate"] is True


def test_power_audit_is_monotonic_and_required_n_reaches_target() -> None:
    low_power = approximate_two_proportion_power(50, 50)
    higher_power = approximate_two_proportion_power(250, 250)
    required = balanced_cases_per_group_for_power(0.80)

    assert 0.0 < low_power < higher_power < 1.0
    assert approximate_two_proportion_power(required, required) >= 0.80
    assert approximate_two_proportion_power(required - 1, required - 1) < 0.80


def test_metadata_assessment_never_claims_state_support() -> None:
    candidate = forward_candidate_registry()[0]
    partition = _partition_metadata()

    result = assess_candidate_partition_metadata(
        candidate=candidate,
        partition=partition,
    )

    assert result["metadata_ready"] is True
    assert result["readiness_status"] == "READY_WITH_LOW_POWER_EXPECTED"
    assert result["potential_complete_session_cases"] == 140
    assert result["exact_condition_cases_known"] is False
    assert result["exact_complement_cases_known"] is False
    assert result["candidate_states_calculated"] is False
    assert result["outcomes_calculated"] is False

    broken = deepcopy(partition)
    broken["candidate_series_metadata"][0]["synthetic_rows_in_interval"] = 1
    failed = assess_candidate_partition_metadata(
        candidate=candidate,
        partition=broken,
    )
    assert failed["metadata_ready"] is False
    assert "NO_SYNTHETIC_CANDIDATE_SERIES_ROWS" in failed[
        "metadata_gate_failures"
    ]


def test_prospective_plan_is_fixed_and_contains_no_decisions() -> None:
    plan = prospective_metadata_plan()

    assert plan["session_date_start_inclusive"] == "2026-07-31"
    assert plan["session_date_end_inclusive"] == "2026-12-31"
    assert plan["weekday_upper_bound"] == 110
    assert plan["decision_records_created_by_m6a"] == 0
    assert plan["market_values_or_outcomes_read"] is False
    assert plan["interim_inferential_testing_permitted"] is False


def _partition_metadata() -> dict[str, object]:
    return {
        "partition_code": "LOCKED_2026_YTD",
        "session_timestamp_coverage": {
            "counts": {
                "london_case_complete": 140,
                "new_york_case_complete": 139,
                "requested_weekdays": 150,
            }
        },
        "candidate_series_metadata": [
            {
                "series_code": "US_VOLATILITY_INDEX",
                "rows_available_in_interval": 145,
                "observation_periods_in_interval": 145,
                "pre_segment_observation_periods": 250,
                "synthetic_rows_in_interval": 0,
                "valid_availability_rows_in_interval": 145,
            },
            {
                "series_code": "US_FINANCIAL_STRESS",
                "rows_available_in_interval": 29,
                "observation_periods_in_interval": 29,
                "pre_segment_observation_periods": 52,
                "synthetic_rows_in_interval": 0,
                "valid_availability_rows_in_interval": 29,
            },
        ],
        "xau_price_metadata": {
            "provider_code": "IC_MARKETS_MT5",
            "instrument_code": "XAUUSD",
            "timeframe": "1m",
            "rows": 199_032,
            "distinct_open_times": 199_032,
            "incomplete_rows": 0,
            "synthetic_rows": 0,
            "valid_availability_rows": 199_032,
        },
    }
