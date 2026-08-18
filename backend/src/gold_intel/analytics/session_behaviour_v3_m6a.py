from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from statistics import NormalDist
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.analytics.session_behaviour_v3_m5 import candidate_registry

M6A_PROTOCOL_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6A_FORWARD_PROTOCOL_V0_1"
M6A_AUDIT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6A_METADATA_AUDIT_V0_1"

M5_RESULT_HASH = "e399534950756933905d2cbfb69bc03e69c5fba60910830b879da08db138f508"
M5_REGISTRY_FINGERPRINT = (
    "8be5f55d427958e68a70350f59357522ef802fa802e3e456455120f7383cc45f"
)
M5_SHORTLIST_CODES = (
    "LONDON_VOLATILITY_DIRECTION_V0_1",
    "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1",
)

PLANNING_EFFECT_PP = 7.5
PLANNING_CONDITION_PROBABILITY = 0.5375
PLANNING_COMPLEMENT_PROBABILITY = 0.4625
PLANNING_ALPHA = 0.05


def forward_candidate_registry() -> list[dict[str, Any]]:
    m5_by_code = {
        str(item["candidate_code"]): item for item in candidate_registry()
    }
    return [
        {
            "candidate_code": "LONDON_VOLATILITY_DIRECTION_V0_1",
            "session_code": "LONDON",
            "decision_clock": {
                "timezone": "Europe/London",
                "decision_time": "08:00:00",
                "reference_bar_open_time": "08:01:00",
                "observation_end_time": "12:00:00",
            },
            "feature_id": "MACRO_VOLATILITY_CHANGE",
            "source_series_code": "US_VOLATILITY_INDEX",
            "transform": "LATEST_POINT_IN_TIME_OBSERVATION_TO_OBSERVATION_CHANGE_SIGN",
            "condition_state": "FALLING",
            "complement_state": "RISING",
            "excluded_known_states": ["UNCHANGED"],
            "unknown_policy": "INELIGIBLE_NEVER_NEUTRAL_OR_CONFIRMING",
            "minimum_material_effect_pp": 7.5,
            "material_reverse_effect_pp": -7.5,
            "m5_definition": m5_by_code[
                "LONDON_VOLATILITY_DIRECTION_V0_1"
            ],
            "m5_internal_rank": 1,
            "m5_status": (
                "INTERNALLY_STABLE_POST_HOC_NO_FORWARD_VALIDATION_CREDIT"
            ),
        },
        {
            "candidate_code": "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1",
            "session_code": "NEW_YORK",
            "decision_clock": {
                "timezone": "America/New_York",
                "decision_time": "08:00:00",
                "reference_bar_open_time": "08:01:00",
                "observation_end_time": "12:00:00",
            },
            "feature_id": "MACRO_FINANCIAL_STRESS_CHANGE",
            "source_series_code": "US_FINANCIAL_STRESS",
            "transform": "LATEST_POINT_IN_TIME_OBSERVATION_TO_OBSERVATION_CHANGE_SIGN",
            "condition_state": "FALLING",
            "complement_state": "RISING",
            "excluded_known_states": ["UNCHANGED"],
            "unknown_policy": "INELIGIBLE_NEVER_NEUTRAL_OR_CONFIRMING",
            "minimum_material_effect_pp": 7.5,
            "material_reverse_effect_pp": -7.5,
            "m5_definition": m5_by_code[
                "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1"
            ],
            "m5_internal_rank": 1,
            "m5_status": (
                "INTERNALLY_STABLE_POST_HOC_NO_FORWARD_VALIDATION_CREDIT"
            ),
        },
    ]


def forward_protocol() -> dict[str, Any]:
    return {
        "protocol_version": M6A_PROTOCOL_VERSION,
        "interpretation_boundary": {
            "m5_candidates_are_post_hoc": True,
            "m6a_opens_forward_values": False,
            "directional_bias_only": True,
            "trade_or_profit_claim_permitted": False,
        },
        "segments_in_fixed_reporting_order": [
            {
                "segment_code": "EXPOSED_CALENDAR_2025",
                "session_date_start_inclusive": "2025-01-01",
                "session_date_end_inclusive": "2025-12-31",
                "classification": (
                    "EXPOSED_HISTORICAL_FORWARD_NO_INDEPENDENT_CREDIT"
                ),
                "positive_validation_credit": False,
                "material_reverse_rejection_is_terminal": True,
            },
            {
                "segment_code": "LOCKED_2026_YTD",
                "session_date_start_inclusive": "2026-01-01",
                "session_date_end_inclusive": "2026-07-29",
                "classification": "LOCKED_INDEPENDENT_HOLDOUT",
                "positive_validation_credit": True,
                "material_reverse_rejection_is_terminal": True,
            },
            {
                "segment_code": "PROSPECTIVE_2026_POST_FREEZE",
                "session_date_start_inclusive": "2026-07-31",
                "session_date_end_inclusive": "2026-12-31",
                "classification": "GENUINELY_PROSPECTIVE_FIXED_CALENDAR",
                "positive_validation_credit": True,
                "material_reverse_rejection_is_terminal": True,
                "interim_inferential_testing_permitted": False,
            },
        ],
        "outcome": {
            "type": "NEUTRAL_SESSION_CLOSE_DIRECTION",
            "reference": (
                "Open of first complete observed XAUUSD one-minute bar "
                "timestamped 08:01 in the session IANA timezone."
            ),
            "observation_end": "12:00 in the session IANA timezone",
            "up": "SIGNED_CLOSE_DISPLACEMENT_GT_POSITIVE_0_01_USD_PER_OZ",
            "down": "SIGNED_CLOSE_DISPLACEMENT_LT_NEGATIVE_0_01_USD_PER_OZ",
            "flat": "ABS_SIGNED_CLOSE_DISPLACEMENT_LE_0_01_USD_PER_OZ",
            "flat_binary_policy": "RETAIN_DESCRIPTIVELY_EXCLUDE_FROM_UP_DOWN",
            "is_trade": False,
        },
        "case_eligibility": {
            "observed_complete_nonsynthetic_unique_xau_bars_required": True,
            "point_in_time_feature_requires_two_eligible_observations": True,
            "condition_or_exact_complement_required": True,
            "up_or_down_outcome_required_for_binary_test": True,
            "source_record_ids_and_availability_timestamps_required": True,
            "prospective_decision_sealed_before_08_01_local": True,
        },
        "support_floors_per_candidate_segment": {
            "joint_known_feature_coverage_pct_minimum": 50.0,
            "condition_binary_cases_minimum": 25,
            "complement_binary_cases_minimum": 25,
            "combined_binary_cases_minimum": 80,
            "condition_distinct_source_signatures_minimum": 4,
            "complement_distinct_source_signatures_minimum": 4,
            "condition_state_episodes_minimum": 4,
            "complement_state_episodes_minimum": 4,
            "duplicate_source_records_or_case_keys_maximum": 0,
        },
        "effect_and_uncertainty": {
            "primary_effect": (
                "Condition UP rate minus exact complement UP rate in "
                "percentage points among non-flat outcomes."
            ),
            "minimum_material_positive_effect_pp": 7.5,
            "material_reverse_effect_pp": -7.5,
            "contingency_test": "TWO_SIDED_FISHER_EXACT",
            "effect_interval": "NEWCOMBE_WILSON_95_PERCENT",
            "pass_interval_requirement": "LOWER_BOUND_GT_ZERO",
            "reject_interval_requirement": "UPPER_BOUND_LT_ZERO",
            "pass_median_requirements": {
                "condition_signed_close": "GT_ZERO",
                "complement_signed_close": "LT_ZERO",
            },
            "reject_median_requirements": {
                "condition_signed_close": "LT_ZERO",
                "complement_signed_close": "GT_ZERO",
            },
        },
        "multiplicity": {
            "method": "HOLM_BONFERRONI_STEP_DOWN",
            "family": "EXACT_TWO_FROZEN_CANDIDATES_PER_SEGMENT",
            "family_size_fixed": 2,
            "family_alpha": 0.10,
            "unsupported_candidate_raw_p_value": 1.0,
            "candidate_or_segment_removal_permitted": False,
        },
        "segment_verdicts": {
            "PASS_MATERIAL_POSITIVE_REPLICATION": {
                "all_support_gates_pass": True,
                "effect_pp_minimum": 7.5,
                "newcombe_95pct_lower_bound_gt": 0.0,
                "holm_adjusted_p_value_maximum": 0.10,
                "condition_median_signed_close_gt": 0.0,
                "complement_median_signed_close_lt": 0.0,
                "conjunctive": True,
            },
            "REJECT_MATERIAL_REVERSE_REPLICATION": {
                "all_support_gates_pass": True,
                "effect_pp_maximum": -7.5,
                "newcombe_95pct_upper_bound_lt": 0.0,
                "holm_adjusted_p_value_maximum": 0.10,
                "condition_median_signed_close_lt": 0.0,
                "complement_median_signed_close_gt": 0.0,
                "conjunctive": True,
            },
            "INCONCLUSIVE_INSUFFICIENT_SUPPORT": {
                "condition": "ANY_SUPPORT_GATE_FAILS"
            },
            "INCONCLUSIVE_MIXED_OR_UNDERPOWERED": {
                "condition": "SUPPORT_PASSES_AND_NEITHER_COMPLETE_PASS_NOR_REJECT"
            },
        },
        "candidate_overall_verdict": {
            "rejected": (
                "Any segment receives "
                "REJECT_MATERIAL_REVERSE_REPLICATION."
            ),
            "current_directional_bias_edge_candidate": (
                "No segment rejects, LOCKED_2026_YTD passes, and "
                "PROSPECTIVE_2026_POST_FREEZE passes."
            ),
            "inconclusive": (
                "No segment rejects and both clean-forward PASS requirements "
                "are not present."
            ),
            "calendar_2025_pass_label": (
                "EXPOSED_FORWARD_SUPPORTIVE_NO_INDEPENDENT_CREDIT"
            ),
        },
        "power_planning": {
            "planned_effect_pp": PLANNING_EFFECT_PP,
            "condition_probability": PLANNING_CONDITION_PROBABILITY,
            "complement_probability": PLANNING_COMPLEMENT_PROBABILITY,
            "two_sided_alpha": PLANNING_ALPHA,
            "reason_for_alpha": (
                "Conservative first Holm threshold and 95% interval "
                "requirement."
            ),
            "method": "NORMAL_APPROXIMATION_TWO_INDEPENDENT_PROPORTIONS",
            "balanced_allocation_is_best_case": True,
            "forward_values_or_state_prevalence_used": False,
            "power_changes_verdict_gate": False,
        },
        "metadata_readiness": {
            "exact_series_identifier_present": True,
            "pre_segment_observation_periods_minimum": 2,
            "interval_observation_periods_minimum": 1,
            "synthetic_candidate_series_rows_maximum": 0,
            "invalid_availability_order_rows_maximum": 0,
            "potential_complete_session_cases_minimum": 80,
            "xau_source": {
                "provider_code": "IC_MARKETS_MT5",
                "instrument_code": "XAUUSD",
                "timeframe": "1m",
            },
            "low_power_threshold": 0.80,
            "ready_low_power_label": "READY_WITH_LOW_POWER_EXPECTED",
        },
        "missing_data_policy": {
            "missing_or_stale": "UNKNOWN",
            "unverified_availability": "UNKNOWN",
            "synthetic": "UNKNOWN",
            "later_revision_replaces_original": False,
            "unknown_counts_as_confirmation": False,
            "unchanged_feature_state": "KNOWN_EXCLUDED",
            "flat_outcome": "KNOWN_EXCLUDED_FROM_BINARY",
            "missing_session_synthesis_permitted": False,
            "source_substitution_after_open_permitted": False,
            "overlapping_mt5_exports": (
                "DEDUPE_BY_CANONICAL_DATABASE_IDENTITY_AND_SOURCE_HASH"
            ),
        },
        "prospective_tracking": {
            "start_session_date": "2026-07-31",
            "end_session_date": "2026-12-31",
            "decision_must_precede_outcome": True,
            "retroactive_decision_records_permitted": False,
            "interim_inferential_tests_permitted": False,
            "year_end_gate": "SAME_EXACT_PER_SEGMENT_GATE",
            "required_ledger_fields": [
                "candidate_code",
                "protocol_hash",
                "session_date",
                "session_code",
                "decision_clock",
                "decision_as_of",
                "candidate_state_or_unknown",
                "source_record_ids",
                "source_available_at_timestamps",
                "source_hashes",
                "decision_record_hash",
                "sealed_at",
                "eligibility",
                "missing_reason",
                "append_only_neutral_outcome",
            ],
        },
        "prohibited": {
            "candidate_add_remove_repair_invert_rename_or_retune": True,
            "confirming_variable_addition": True,
            "cot_as_pass_gate": True,
            "execution_optimization": True,
            "holdout_values_or_outcomes_in_m6a": True,
            "interim_prospective_inference": True,
            "rejected_candidate_or_zn_reopen": True,
            "source_substitution_after_open": True,
            "trades_returns_pnl_or_r_multiples": True,
        },
    }


def protocol_fingerprint() -> str:
    return canonical_hash(
        {
            "candidates": forward_candidate_registry(),
            "protocol": forward_protocol(),
        }
    )


def validate_forward_protocol() -> list[str]:
    candidates = forward_candidate_registry()
    protocol = forward_protocol()
    failures: list[str] = []

    codes = tuple(str(item["candidate_code"]) for item in candidates)
    if codes != M5_SHORTLIST_CODES:
        failures.append("CANDIDATE_CODES_DIFFER_FROM_M5_SHORTLIST")
    if len(candidates) != 2:
        failures.append("CANDIDATE_FAMILY_SIZE_NOT_TWO")
    if {str(item["session_code"]) for item in candidates} != {
        "LONDON",
        "NEW_YORK",
    }:
        failures.append("SESSION_ASSIGNMENT_NOT_ONE_PER_SESSION")
    if {
        str(item["feature_id"]) for item in candidates
    } != {
        "MACRO_VOLATILITY_CHANGE",
        "MACRO_FINANCIAL_STRESS_CHANGE",
    }:
        failures.append("UNAUTHORIZED_FEATURE_PRESENT")
    if {
        str(item["source_series_code"]) for item in candidates
    } != {"US_VOLATILITY_INDEX", "US_FINANCIAL_STRESS"}:
        failures.append("UNAUTHORIZED_SOURCE_SERIES_PRESENT")
    if any(
        item["condition_state"] != "FALLING"
        or item["complement_state"] != "RISING"
        or item["excluded_known_states"] != ["UNCHANGED"]
        for item in candidates
    ):
        failures.append("CONDITION_COMPLEMENT_OR_EXCLUSION_CHANGED")
    if any(
        float(item["minimum_material_effect_pp"]) != 7.5
        or float(item["material_reverse_effect_pp"]) != -7.5
        for item in candidates
    ):
        failures.append("MATERIAL_EFFECT_THRESHOLD_CHANGED")

    multiplicity = _mapping(protocol["multiplicity"])
    if (
        multiplicity["method"] != "HOLM_BONFERRONI_STEP_DOWN"
        or int(multiplicity["family_size_fixed"]) != 2
        or float(multiplicity["family_alpha"]) != 0.10
    ):
        failures.append("MULTIPLICITY_PROTOCOL_INVALID")

    segments = _sequence(protocol["segments_in_fixed_reporting_order"])
    if [item["segment_code"] for item in segments] != [
        "EXPOSED_CALENDAR_2025",
        "LOCKED_2026_YTD",
        "PROSPECTIVE_2026_POST_FREEZE",
    ]:
        failures.append("SEGMENT_ORDER_CHANGED")
    if protocol_fingerprint() == "":
        failures.append("EMPTY_PROTOCOL_FINGERPRINT")
    return failures


def approximate_two_proportion_power(
    condition_cases: int,
    complement_cases: int,
    *,
    condition_probability: float = PLANNING_CONDITION_PROBABILITY,
    complement_probability: float = PLANNING_COMPLEMENT_PROBABILITY,
    alpha: float = PLANNING_ALPHA,
) -> float:
    if condition_cases < 2 or complement_cases < 2:
        return 0.0
    if not 0.0 < condition_probability < 1.0:
        raise ValueError("condition_probability must be between zero and one")
    if not 0.0 < complement_probability < 1.0:
        raise ValueError("complement_probability must be between zero and one")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between zero and one")

    n_condition = float(condition_cases)
    n_complement = float(complement_cases)
    delta = condition_probability - complement_probability
    pooled = (
        n_condition * condition_probability
        + n_complement * complement_probability
    ) / (n_condition + n_complement)
    null_se = math.sqrt(
        pooled
        * (1.0 - pooled)
        * ((1.0 / n_condition) + (1.0 / n_complement))
    )
    alternative_se = math.sqrt(
        condition_probability
        * (1.0 - condition_probability)
        / n_condition
        + complement_probability
        * (1.0 - complement_probability)
        / n_complement
    )
    normal = NormalDist()
    critical = normal.inv_cdf(1.0 - alpha / 2.0)
    upper_tail = 1.0 - normal.cdf(
        (critical * null_se - delta) / alternative_se
    )
    lower_tail = normal.cdf(
        (-critical * null_se - delta) / alternative_se
    )
    return min(max(upper_tail + lower_tail, 0.0), 1.0)


def balanced_cases_per_group_for_power(
    target_power: float,
    *,
    condition_probability: float = PLANNING_CONDITION_PROBABILITY,
    complement_probability: float = PLANNING_COMPLEMENT_PROBABILITY,
    alpha: float = PLANNING_ALPHA,
) -> int:
    if not 0.0 < target_power < 1.0:
        raise ValueError("target_power must be between zero and one")
    low = 2
    high = 2
    while (
        approximate_two_proportion_power(
            high,
            high,
            condition_probability=condition_probability,
            complement_probability=complement_probability,
            alpha=alpha,
        )
        < target_power
    ):
        high *= 2
        if high > 1_000_000:
            raise RuntimeError("Power target search exceeded safety bound")
    while low < high:
        middle = (low + high) // 2
        power = approximate_two_proportion_power(
            middle,
            middle,
            condition_probability=condition_probability,
            complement_probability=complement_probability,
            alpha=alpha,
        )
        if power >= target_power:
            high = middle
        else:
            low = middle + 1
    return low


def build_power_audit(potential_complete_session_cases: int) -> dict[str, Any]:
    if potential_complete_session_cases < 0:
        raise ValueError("potential_complete_session_cases cannot be negative")
    best_condition = potential_complete_session_cases // 2
    best_complement = potential_complete_session_cases - best_condition
    eighty_pct_total = math.floor(potential_complete_session_cases * 0.8)
    eighty_condition = eighty_pct_total // 2
    eighty_complement = eighty_pct_total - eighty_condition
    best_power = approximate_two_proportion_power(
        best_condition,
        best_complement,
    )
    eighty_power = approximate_two_proportion_power(
        eighty_condition,
        eighty_complement,
    )
    required_80 = balanced_cases_per_group_for_power(0.80)
    required_90 = balanced_cases_per_group_for_power(0.90)
    return {
        "method": "NORMAL_APPROXIMATION_TWO_INDEPENDENT_PROPORTIONS",
        "forward_values_or_candidate_states_used": False,
        "planned_effect_pp": PLANNING_EFFECT_PP,
        "condition_probability": PLANNING_CONDITION_PROBABILITY,
        "complement_probability": PLANNING_COMPLEMENT_PROBABILITY,
        "two_sided_alpha": PLANNING_ALPHA,
        "potential_complete_session_case_upper_bound": (
            potential_complete_session_cases
        ),
        "best_case_balanced": {
            "condition_cases": best_condition,
            "complement_cases": best_complement,
            "approximate_power": _rounded(best_power),
        },
        "eighty_percent_binary_eligible_balanced_scenario": {
            "condition_cases": eighty_condition,
            "complement_cases": eighty_complement,
            "approximate_power": _rounded(eighty_power),
        },
        "balanced_cases_per_group_required": {
            "power_80pct": required_80,
            "power_90pct": required_90,
        },
        "best_case_reaches_80pct_power": best_power >= 0.80,
        "interpretation": (
            "BEST_CASE_POWER_AT_FROZEN_EFFECT_IS_BELOW_80_PERCENT"
            if best_power < 0.80
            else "BEST_CASE_POWER_AT_FROZEN_EFFECT_REACHES_80_PERCENT"
        ),
    }


def assess_candidate_partition_metadata(
    *,
    candidate: Mapping[str, Any],
    partition: Mapping[str, Any],
    protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rules = _mapping((protocol or forward_protocol())["metadata_readiness"])
    session_code = str(candidate["session_code"])
    session_key = (
        "london_case_complete"
        if session_code == "LONDON"
        else "new_york_case_complete"
    )
    session_coverage = _mapping(partition["session_timestamp_coverage"])
    counts = _mapping(session_coverage["counts"])
    potential_cases = int(counts[session_key])

    source_code = str(candidate["source_series_code"])
    series_rows = [
        _mapping(item)
        for item in _sequence(partition["candidate_series_metadata"])
        if str(_mapping(item).get("series_code")) == source_code
    ]
    series = series_rows[0] if len(series_rows) == 1 else {}
    xau = _mapping(partition.get("xau_price_metadata"))

    interval_rows = int(series.get("rows_available_in_interval", 0))
    interval_periods = int(series.get("observation_periods_in_interval", 0))
    prior_periods = int(series.get("pre_segment_observation_periods", 0))
    synthetic_rows = int(series.get("synthetic_rows_in_interval", 0))
    valid_rows = int(series.get("valid_availability_rows_in_interval", 0))
    xau_rows = int(xau.get("rows", 0))

    gates = [
        _gate("EXACT_SERIES_IDENTIFIER_PRESENT", len(series_rows) == 1),
        _gate(
            "PRE_SEGMENT_OBSERVATION_PERIODS_MINIMUM",
            prior_periods
            >= int(rules["pre_segment_observation_periods_minimum"]),
            observed=prior_periods,
            required=int(rules["pre_segment_observation_periods_minimum"]),
        ),
        _gate(
            "INTERVAL_OBSERVATION_PERIODS_MINIMUM",
            interval_periods
            >= int(rules["interval_observation_periods_minimum"]),
            observed=interval_periods,
            required=int(rules["interval_observation_periods_minimum"]),
        ),
        _gate(
            "NO_SYNTHETIC_CANDIDATE_SERIES_ROWS",
            synthetic_rows
            <= int(rules["synthetic_candidate_series_rows_maximum"]),
            observed=synthetic_rows,
            maximum=int(rules["synthetic_candidate_series_rows_maximum"]),
        ),
        _gate(
            "ALL_INTERVAL_SERIES_ROWS_HAVE_VALID_AVAILABILITY_ORDER",
            interval_rows > 0 and valid_rows == interval_rows,
            interval_rows=interval_rows,
            valid_rows=valid_rows,
        ),
        _gate(
            "EXACT_XAU_SOURCE_PRESENT",
            xau.get("provider_code")
            == rules["xau_source"]["provider_code"]
            and xau.get("instrument_code")
            == rules["xau_source"]["instrument_code"]
            and xau.get("timeframe") == rules["xau_source"]["timeframe"],
        ),
        _gate(
            "XAU_ROWS_UNIQUE_COMPLETE_NONSYNTHETIC_POINT_IN_TIME",
            xau_rows > 0
            and int(xau.get("distinct_open_times", 0)) == xau_rows
            and int(xau.get("incomplete_rows", 0)) == 0
            and int(xau.get("synthetic_rows", 0)) == 0
            and int(xau.get("valid_availability_rows", 0)) == xau_rows,
            rows=xau_rows,
            distinct_open_times=int(xau.get("distinct_open_times", 0)),
        ),
        _gate(
            "POTENTIAL_COMPLETE_SESSION_CASES_MINIMUM",
            potential_cases
            >= int(rules["potential_complete_session_cases_minimum"]),
            observed=potential_cases,
            required=int(rules["potential_complete_session_cases_minimum"]),
        ),
    ]
    failures = [str(item["code"]) for item in gates if not item["passed"]]
    power = build_power_audit(potential_cases)
    if failures:
        readiness = "NOT_READY_METADATA_GATE_FAILURE"
    elif power["best_case_reaches_80pct_power"]:
        readiness = "READY_METADATA_AND_BEST_CASE_POWER_AT_LEAST_80_PERCENT"
    else:
        readiness = str(rules["ready_low_power_label"])
    return {
        "candidate_code": candidate["candidate_code"],
        "session_code": session_code,
        "source_series_code": source_code,
        "partition_code": partition["partition_code"],
        "metadata_gates": gates,
        "metadata_gate_failures": failures,
        "metadata_ready": not failures,
        "readiness_status": readiness,
        "potential_complete_session_cases": potential_cases,
        "exact_condition_cases_known": False,
        "exact_complement_cases_known": False,
        "candidate_states_calculated": False,
        "outcomes_calculated": False,
        "series_metadata": dict(series),
        "power_audit": power,
    }


def prospective_metadata_plan(
    protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected = protocol or forward_protocol()
    segment = next(
        item
        for item in _sequence(selected["segments_in_fixed_reporting_order"])
        if item["segment_code"] == "PROSPECTIVE_2026_POST_FREEZE"
    )
    start = date.fromisoformat(str(segment["session_date_start_inclusive"]))
    end = date.fromisoformat(str(segment["session_date_end_inclusive"]))
    weekdays = weekday_count(start, end)
    return {
        "segment_code": "PROSPECTIVE_2026_POST_FREEZE",
        "session_date_start_inclusive": start.isoformat(),
        "session_date_end_inclusive": end.isoformat(),
        "weekday_upper_bound": weekdays,
        "market_values_or_outcomes_read": False,
        "decision_records_created_by_m6a": 0,
        "retroactive_decisions_permitted": False,
        "fixed_endpoint": end.isoformat(),
        "interim_inferential_testing_permitted": False,
        "power_upper_bound_per_candidate": build_power_audit(weekdays),
        "readiness_status": "PROTOCOL_FROZEN_NO_PROSPECTIVE_DECISIONS_YET",
    }


def weekday_count(start: date, end_inclusive: date) -> int:
    if end_inclusive < start:
        raise ValueError("end_inclusive must not precede start")
    current = start
    count = 0
    while current <= end_inclusive:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _gate(code: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {
        "code": code,
        "passed": bool(passed),
        "evidence": evidence,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return list(value)
    return []


def _rounded(value: float) -> float:
    return round(value, 8)
