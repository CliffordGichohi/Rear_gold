from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.analytics.session_behaviour_v3_relationships import (
    DiscoveryCase,
    fisher_exact_two_sided,
    newcombe_difference_interval,
    path_profile,
)

M5_ENGINE_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M5_STABILITY_V0_1"
M5_REGISTRY_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M5_CANDIDATES_V0_1"
ROUND_DECIMALS = 8


def candidate_registry() -> list[dict[str, Any]]:
    return [
        {
            "candidate_code": "LONDON_ASIA_DIRECTION_REVERSAL_V0_1",
            "session_code": "LONDON",
            "stage": "SINGLE_FEATURE_COMPLEMENTARY_STATES",
            "post_hoc_status": "POST_HOC_NO_DEVELOPMENT_VALIDATION_CREDIT",
            "condition": [
                {"feature_id": "SESSION_ASIA_DIRECTION", "state": "DOWN"}
            ],
            "complement": {
                "type": "EXACT_CONDITION",
                "conditions": [
                    {"feature_id": "SESSION_ASIA_DIRECTION", "state": "UP"}
                ],
                "excluded_known_states": ["FLAT"],
            },
            "joint_known_feature_ids": ["SESSION_ASIA_DIRECTION"],
            "expected_effect_direction": "POSITIVE",
            "interpretation": (
                "An Asian DOWN state is associated with a more bullish London "
                "session close than the exact Asian UP complement."
            ),
            "m4_relationship_ids": [
                "SINGLE__SESSION_ASIA_DIRECTION__DOWN",
                "SINGLE__SESSION_ASIA_DIRECTION__UP",
            ],
            "minimum_full_effect_pp": 7.5,
            "require_complement_median_opposite": True,
        },
        {
            "candidate_code": "LONDON_VOLATILITY_DIRECTION_V0_1",
            "session_code": "LONDON",
            "stage": "SINGLE_FEATURE_COMPLEMENTARY_STATES",
            "post_hoc_status": "POST_HOC_NO_DEVELOPMENT_VALIDATION_CREDIT",
            "condition": [
                {"feature_id": "MACRO_VOLATILITY_CHANGE", "state": "FALLING"}
            ],
            "complement": {
                "type": "EXACT_CONDITION",
                "conditions": [
                    {"feature_id": "MACRO_VOLATILITY_CHANGE", "state": "RISING"}
                ],
                "excluded_known_states": ["UNCHANGED"],
            },
            "joint_known_feature_ids": ["MACRO_VOLATILITY_CHANGE"],
            "expected_effect_direction": "POSITIVE",
            "interpretation": (
                "Falling volatility is associated with a more bullish London "
                "session close than the exact rising-volatility complement."
            ),
            "m4_relationship_ids": [
                "SINGLE__MACRO_VOLATILITY_CHANGE__FALLING",
                "SINGLE__MACRO_VOLATILITY_CHANGE__RISING",
            ],
            "minimum_full_effect_pp": 7.5,
            "require_complement_median_opposite": True,
        },
        {
            "candidate_code": "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1",
            "session_code": "NEW_YORK",
            "stage": "SINGLE_FEATURE_COMPLEMENTARY_STATES",
            "post_hoc_status": "POST_HOC_NO_DEVELOPMENT_VALIDATION_CREDIT",
            "condition": [
                {
                    "feature_id": "MACRO_FINANCIAL_STRESS_CHANGE",
                    "state": "FALLING",
                }
            ],
            "complement": {
                "type": "EXACT_CONDITION",
                "conditions": [
                    {
                        "feature_id": "MACRO_FINANCIAL_STRESS_CHANGE",
                        "state": "RISING",
                    }
                ],
                "excluded_known_states": ["UNCHANGED"],
            },
            "joint_known_feature_ids": ["MACRO_FINANCIAL_STRESS_CHANGE"],
            "expected_effect_direction": "POSITIVE",
            "interpretation": (
                "Falling financial stress is associated with a more bullish "
                "New York session close than the exact rising-stress complement."
            ),
            "m4_relationship_ids": [
                "SINGLE__MACRO_FINANCIAL_STRESS_CHANGE__FALLING",
                "SINGLE__MACRO_FINANCIAL_STRESS_CHANGE__RISING",
            ],
            "minimum_full_effect_pp": 7.5,
            "require_complement_median_opposite": True,
        },
        {
            "candidate_code": "NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1",
            "session_code": "NEW_YORK",
            "stage": "EXACT_TWO_CONDITION_INTERACTION",
            "post_hoc_status": "POST_HOC_NO_DEVELOPMENT_VALIDATION_CREDIT",
            "condition": [
                {
                    "feature_id": "EXPECT_SOFR_WINDOW_CUT_HIKE_BALANCE",
                    "state": "CUT_DOMINANT",
                },
                {
                    "feature_id": "MACRO_TREASURY_2Y_CHANGE",
                    "state": "FALLING",
                },
            ],
            "complement": {
                "type": "ALL_OTHER_JOINT_KNOWN_CASES",
                "conditions": [],
                "excluded_known_states": [],
            },
            "joint_known_feature_ids": [
                "EXPECT_SOFR_WINDOW_CUT_HIKE_BALANCE",
                "MACRO_TREASURY_2Y_CHANGE",
            ],
            "expected_effect_direction": "POSITIVE",
            "interpretation": (
                "Cut-dominant SOFR expectations together with a falling "
                "2-year yield are associated with a more bullish New York "
                "session close than all other jointly known combinations."
            ),
            "m4_relationship_ids": ["INT_SOFR_CUT_2Y_FALLING"],
            "minimum_full_effect_pp": 10.0,
            "require_complement_median_opposite": False,
        },
    ]


def stability_protocol() -> dict[str, Any]:
    return {
        "primary_effect": (
            "Condition UP rate minus frozen complement UP rate among non-flat "
            "SESSION_CLOSE outcomes, in percentage points."
        ),
        "full_development_support": {
            "joint_known_coverage_pct_minimum": 50.0,
            "condition_binary_cases_minimum_single": 80,
            "condition_binary_cases_minimum_interaction": 60,
            "complement_binary_cases_minimum": 80,
            "condition_distinct_source_signatures_minimum": 8,
            "complement_distinct_source_signatures_minimum": 8,
            "condition_state_episodes_minimum": 8,
            "complement_state_episodes_minimum": 8,
        },
        "full_development_gates": {
            "minimum_effect_pp": (
                "Candidate-specific: 7.5 for complementary-state singles and "
                "10.0 for the SOFR/2Y interaction."
            ),
            "newcombe_wilson_95pct_interval_excludes_zero": True,
            "condition_median_signed_close_positive": True,
            "paired_candidate_complement_median_signed_close_negative": True,
        },
        "calendar_year_blocks": {
            "blocks": [
                {
                    "block_id": "CALENDAR_2021_PARTIAL",
                    "start": "2021-08-01",
                    "end": "2021-12-31",
                },
                {
                    "block_id": "CALENDAR_2022",
                    "start": "2022-01-01",
                    "end": "2022-12-31",
                },
                {
                    "block_id": "CALENDAR_2023",
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                },
                {
                    "block_id": "CALENDAR_2024",
                    "start": "2024-01-01",
                    "end": "2024-12-31",
                },
            ],
            "block_support": {
                "condition_binary_cases_minimum": 12,
                "complement_binary_cases_minimum": 20,
                "combined_binary_cases_minimum": 50,
                "joint_known_coverage_pct_minimum": 35.0,
            },
            "gates": {
                "eligible_blocks_minimum": 3,
                "positive_effect_fraction_minimum": 0.75,
                "median_effect_pp_minimum": 3.0,
                "catastrophic_reversal_threshold": (
                    "No eligible annual effect may be at or below the negative "
                    "of the candidate's full-development minimum effect."
                ),
                "latest_eligible_block_effect_must_be_positive": True,
            },
        },
        "rolling_blocks": {
            "window_session_rows": 126,
            "step_session_rows": 63,
            "append_terminal_window": True,
            "block_support": {
                "condition_binary_cases_minimum_single": 20,
                "condition_binary_cases_minimum_interaction": 12,
                "complement_binary_cases_minimum": 30,
                "combined_binary_cases_minimum": 60,
                "joint_known_coverage_pct_minimum": 35.0,
            },
            "gates": {
                "eligible_blocks_minimum": 6,
                "positive_effect_fraction_minimum": 0.70,
                "median_effect_pp_minimum": 3.0,
                "maximum_consecutive_opposite_effect_blocks": 2,
                "latest_eligible_block_effect_must_be_positive": True,
            },
            "warning": (
                "Overlapping rolling blocks are stability diagnostics, not "
                "independent observations or a source of p-values."
            ),
        },
        "multiplicity": {
            "method": "HOLM_BONFERRONI_STEP_DOWN",
            "family": "ALL_FOUR_AUTHORIZED_POST_HOC_CANDIDATE_FAMILIES",
            "family_size_fixed": 4,
            "alpha": 0.10,
            "raw_p_value": (
                "Two-sided Fisher exact test on the full development condition "
                "versus complement UP/DOWN table."
            ),
            "unsupported_candidate_p_value_for_family": 1.0,
            "validation_credit": False,
        },
        "ranking_order": [
            "all frozen gates pass descending",
            "Holm-adjusted p-value ascending",
            "rolling positive-effect fraction descending",
            "annual positive-effect fraction descending",
            "full-development effect descending",
            "condition binary support descending",
            "candidate_code lexicographically ascending",
        ],
        "shortlist": {
            "maximum_per_session": 2,
            "zero_acceptable": True,
            "label": "INTERNALLY_STABLE_POST_HOC_NO_FORWARD_VALIDATION_CREDIT",
        },
        "prohibited": {
            "candidate_addition_or_substitution": True,
            "candidate_definition_or_direction_change": True,
            "cot_as_pass_gate": True,
            "execution_optimization": True,
            "holdout_2025_or_2026_access": True,
            "rejected_zn_rule_reopen": True,
        },
    }


def registry_fingerprint() -> str:
    return canonical_hash(
        {
            "candidate_registry": candidate_registry(),
            "stability_protocol": stability_protocol(),
        }
    )


def build_m5_results(
    cases: Sequence[DiscoveryCase],
    *,
    frozen_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    definitions = list(frozen_manifest["candidate_registry"])
    protocol = _mapping(frozen_manifest["stability_protocol"])
    expected_codes = [item["candidate_code"] for item in candidate_registry()]
    if [item["candidate_code"] for item in definitions] != expected_codes:
        raise ValueError("Frozen M5 candidate registry differs from implementation")
    by_session = {
        session: sorted(
            [case for case in cases if case.session_code == session],
            key=lambda item: (item.session_date, item.case_id),
        )
        for session in ("LONDON", "NEW_YORK")
    }
    if len(by_session["LONDON"]) != 833 or len(by_session["NEW_YORK"]) != 826:
        raise ValueError("Unexpected M5 development case counts")

    records: list[dict[str, Any]] = []
    for definition in definitions:
        session_cases = by_session[str(definition["session_code"])]
        record = evaluate_candidate(
            session_cases,
            definition=definition,
            protocol=protocol,
        )
        records.append(record)
    apply_holm_bonferroni(records, family_size=4)
    for record, definition in zip(records, definitions, strict=True):
        apply_stability_gates(
            record,
            definition=definition,
            protocol=protocol,
        )

    sessions: dict[str, Any] = {}
    for session_code in ("LONDON", "NEW_YORK"):
        session_records = [
            record
            for record in records
            if record["session_code"] == session_code
        ]
        passing = [record for record in session_records if record["gate_pass"]]
        ranked = sorted(passing, key=stability_rank_key)
        maximum = int(_mapping(protocol["shortlist"])["maximum_per_session"])
        shortlisted: list[dict[str, Any]] = []
        for rank, record in enumerate(ranked[:maximum], start=1):
            item = {
                "candidate_code": record["candidate_code"],
                "internal_rank": rank,
                "status": _mapping(protocol["shortlist"])["label"],
                "forward_validation_credit": False,
            }
            shortlisted.append(item)
            record["shortlisted"] = True
            record["internal_rank"] = rank
        sessions[session_code] = {
            "candidate_records": session_records,
            "candidates_authorized": len(session_records),
            "candidates_passing_all_gates": len(passing),
            "shortlist": shortlisted,
        }

    result: dict[str, Any] = {
        "m5_version": M5_ENGINE_VERSION,
        "milestone": "V3_M5_INTERNAL_STABILITY_AND_SHORTLIST_FREEZE",
        "created_at": str(frozen_manifest["recorded_at"]),
        "m5_hash": "",
        "case_counts": {"LONDON": 833, "NEW_YORK": 826, "total": 1659},
        "candidate_family_count": 4,
        "pre_result_manifest": {
            "manifest_hash": frozen_manifest["manifest_hash"],
            "registry_fingerprint": frozen_manifest["registry_fingerprint"],
        },
        "multiplicity": dict(_mapping(protocol["multiplicity"])),
        "sessions": sessions,
        "total_passing_all_gates": sum(
            item["gate_pass"] for item in records
        ),
        "total_shortlisted": sum(
            len(sessions[session]["shortlist"])
            for session in ("LONDON", "NEW_YORK")
        ),
        "interpretation_boundary": {
            "calendar_2025_values_opened": False,
            "calendar_2026_values_opened": False,
            "cot_used_as_pass_gate": False,
            "development_validation_credit": False,
            "execution_variants": 0,
            "new_candidates_added_after_freeze": 0,
            "rejected_zn_rules_reopened": False,
            "trades_or_returns": 0,
        },
    }
    result["m5_hash"] = _embedded_hash(result, "m5_hash")
    return result


def evaluate_candidate(
    cases: Sequence[DiscoveryCase],
    *,
    definition: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    full_support = _mapping(protocol["full_development_support"])
    full = evaluate_candidate_slice(
        cases,
        definition=definition,
        support_policy={
            "joint_known_coverage_pct_minimum": full_support[
                "joint_known_coverage_pct_minimum"
            ],
            "condition_binary_cases_minimum": (
                full_support["condition_binary_cases_minimum_interaction"]
                if definition["stage"] == "EXACT_TWO_CONDITION_INTERACTION"
                else full_support["condition_binary_cases_minimum_single"]
            ),
            "complement_binary_cases_minimum": full_support[
                "complement_binary_cases_minimum"
            ],
            "combined_binary_cases_minimum": 0,
            "condition_distinct_source_signatures_minimum": full_support[
                "condition_distinct_source_signatures_minimum"
            ],
            "complement_distinct_source_signatures_minimum": full_support[
                "complement_distinct_source_signatures_minimum"
            ],
            "condition_state_episodes_minimum": full_support[
                "condition_state_episodes_minimum"
            ],
            "complement_state_episodes_minimum": full_support[
                "complement_state_episodes_minimum"
            ],
        },
        include_signature_and_episode_floors=True,
    )
    calendar = calendar_blocks(
        cases,
        definition=definition,
        policy=_mapping(protocol["calendar_year_blocks"]),
    )
    rolling = rolling_blocks(
        cases,
        definition=definition,
        policy=_mapping(protocol["rolling_blocks"]),
    )
    return {
        "candidate_code": definition["candidate_code"],
        "session_code": definition["session_code"],
        "stage": definition["stage"],
        "post_hoc_status": definition["post_hoc_status"],
        "condition": list(definition["condition"]),
        "complement": dict(definition["complement"]),
        "m4_relationship_ids": list(definition["m4_relationship_ids"]),
        "minimum_full_effect_pp": definition["minimum_full_effect_pp"],
        "full_development": full,
        "calendar_blocks": calendar,
        "rolling_blocks": rolling,
        "holm_adjusted_p_value": None,
        "gate_failures": [],
        "gate_pass": False,
        "shortlisted": False,
        "internal_rank": None,
    }


def evaluate_candidate_slice(
    cases: Sequence[DiscoveryCase],
    *,
    definition: Mapping[str, Any],
    support_policy: Mapping[str, Any],
    include_signature_and_episode_floors: bool,
) -> dict[str, Any]:
    memberships = [
        (case, candidate_membership(case, definition)) for case in cases
    ]
    joint_known = [
        case
        for case, membership in memberships
        if membership != "JOINT_UNKNOWN"
    ]
    condition_all = [
        case for case, membership in memberships if membership == "CONDITION"
    ]
    complement_all = [
        case for case, membership in memberships if membership == "COMPLEMENT"
    ]
    condition = [
        case for case in condition_all if case.outcome.close_direction != "FLAT"
    ]
    complement = [
        case for case in complement_all if case.outcome.close_direction != "FLAT"
    ]
    condition_up = sum(case.outcome.close_direction == "UP" for case in condition)
    condition_down = len(condition) - condition_up
    complement_up = sum(
        case.outcome.close_direction == "UP" for case in complement
    )
    complement_down = len(complement) - complement_up
    condition_rate = condition_up / len(condition) if condition else None
    complement_rate = complement_up / len(complement) if complement else None
    effect = (
        100 * (condition_rate - complement_rate)
        if condition_rate is not None and complement_rate is not None
        else None
    )
    failures: list[str] = []
    coverage = _percentage(len(joint_known), len(cases))
    if coverage < float(support_policy["joint_known_coverage_pct_minimum"]):
        failures.append("JOINT_KNOWN_COVERAGE_BELOW_MINIMUM")
    if len(condition) < int(support_policy["condition_binary_cases_minimum"]):
        failures.append("CONDITION_BINARY_CASES_BELOW_MINIMUM")
    if len(complement) < int(support_policy["complement_binary_cases_minimum"]):
        failures.append("COMPLEMENT_BINARY_CASES_BELOW_MINIMUM")
    if len(condition) + len(complement) < int(
        support_policy["combined_binary_cases_minimum"]
    ):
        failures.append("COMBINED_BINARY_CASES_BELOW_MINIMUM")

    condition_signatures = {
        candidate_source_signature(case, definition)
        for case in condition_all
    }
    complement_signatures = {
        candidate_source_signature(case, definition)
        for case in complement_all
    }
    condition_episodes = _membership_episodes(memberships, "CONDITION")
    complement_episodes = _membership_episodes(memberships, "COMPLEMENT")
    if include_signature_and_episode_floors:
        if len(condition_signatures) < int(
            support_policy["condition_distinct_source_signatures_minimum"]
        ):
            failures.append("CONDITION_SOURCE_SIGNATURES_BELOW_MINIMUM")
        if len(complement_signatures) < int(
            support_policy["complement_distinct_source_signatures_minimum"]
        ):
            failures.append("COMPLEMENT_SOURCE_SIGNATURES_BELOW_MINIMUM")
        if condition_episodes < int(
            support_policy["condition_state_episodes_minimum"]
        ):
            failures.append("CONDITION_EPISODES_BELOW_MINIMUM")
        if complement_episodes < int(
            support_policy["complement_state_episodes_minimum"]
        ):
            failures.append("COMPLEMENT_EPISODES_BELOW_MINIMUM")
    support_eligible = not failures
    interval = (
        newcombe_difference_interval(
            condition_up,
            len(condition),
            complement_up,
            len(complement),
        )
        if condition and complement
        else [None, None]
    )
    p_value = (
        fisher_exact_two_sided(
            condition_up,
            condition_down,
            complement_up,
            complement_down,
        )
        if support_eligible
        else None
    )
    return {
        "case_count": len(cases),
        "joint_known_cases": len(joint_known),
        "joint_known_coverage_pct": coverage,
        "excluded_known_cases": sum(
            membership == "EXCLUDED_KNOWN"
            for _, membership in memberships
        ),
        "condition_all_cases": len(condition_all),
        "complement_all_cases": len(complement_all),
        "condition_path_profile": path_profile(condition_all),
        "complement_path_profile": path_profile(complement_all),
        "condition_distinct_source_signatures": len(condition_signatures),
        "complement_distinct_source_signatures": len(complement_signatures),
        "condition_state_episodes": condition_episodes,
        "complement_state_episodes": complement_episodes,
        "contingency": {
            "condition_up": condition_up,
            "condition_down": condition_down,
            "complement_up": complement_up,
            "complement_down": complement_down,
        },
        "condition_up_rate_pct": (
            _rounded(100 * condition_rate)
            if condition_rate is not None
            else None
        ),
        "complement_up_rate_pct": (
            _rounded(100 * complement_rate)
            if complement_rate is not None
            else None
        ),
        "effect_pp": _rounded(effect),
        "newcombe_wilson_95pct_effect_pp": [
            _rounded(100 * item) if item is not None else None
            for item in interval
        ],
        "fisher_exact_two_sided_p_value": _rounded(p_value),
        "support_eligible": support_eligible,
        "support_failures": sorted(set(failures)),
    }


def candidate_membership(
    case: DiscoveryCase,
    definition: Mapping[str, Any],
) -> str:
    joint_ids = [str(item) for item in definition["joint_known_feature_ids"]]
    if any(case.features[feature_id].state == "UNKNOWN" for feature_id in joint_ids):
        return "JOINT_UNKNOWN"
    condition = list(definition["condition"])
    if _conditions_match(case, condition):
        return "CONDITION"
    complement = _mapping(definition["complement"])
    if complement["type"] == "ALL_OTHER_JOINT_KNOWN_CASES":
        return "COMPLEMENT"
    if complement["type"] == "EXACT_CONDITION" and _conditions_match(
        case,
        list(complement["conditions"]),
    ):
        return "COMPLEMENT"
    return "EXCLUDED_KNOWN"


def candidate_source_signature(
    case: DiscoveryCase,
    definition: Mapping[str, Any],
) -> str:
    return canonical_hash(
        [
            {
                "feature_id": feature_id,
                "source_signature": case.features[feature_id].source_signature,
            }
            for feature_id in definition["joint_known_feature_ids"]
        ]
    )


def calendar_blocks(
    cases: Sequence[DiscoveryCase],
    *,
    definition: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    support = _mapping(policy["block_support"])
    output: list[dict[str, Any]] = []
    for block in policy["blocks"]:
        start = str(block["start"])
        end = str(block["end"])
        selected = [
            case
            for case in cases
            if start <= case.session_date.isoformat() <= end
        ]
        metrics = evaluate_candidate_slice(
            selected,
            definition=definition,
            support_policy={
                **support,
                "condition_distinct_source_signatures_minimum": 0,
                "complement_distinct_source_signatures_minimum": 0,
                "condition_state_episodes_minimum": 0,
                "complement_state_episodes_minimum": 0,
            },
            include_signature_and_episode_floors=False,
        )
        output.append(
            {
                "block_id": block["block_id"],
                "start": start,
                "end": end,
                "metrics": metrics,
            }
        )
    return output


def rolling_blocks(
    cases: Sequence[DiscoveryCase],
    *,
    definition: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    width = int(policy["window_session_rows"])
    step = int(policy["step_session_rows"])
    starts = list(range(0, len(cases) - width + 1, step))
    terminal = len(cases) - width
    if policy["append_terminal_window"] and terminal not in starts:
        starts.append(terminal)
    starts = sorted(set(starts))
    support = _mapping(policy["block_support"])
    minimum_condition = (
        support["condition_binary_cases_minimum_interaction"]
        if definition["stage"] == "EXACT_TWO_CONDITION_INTERACTION"
        else support["condition_binary_cases_minimum_single"]
    )
    output: list[dict[str, Any]] = []
    for index, start in enumerate(starts, start=1):
        selected = list(cases[start : start + width])
        metrics = evaluate_candidate_slice(
            selected,
            definition=definition,
            support_policy={
                "joint_known_coverage_pct_minimum": support[
                    "joint_known_coverage_pct_minimum"
                ],
                "condition_binary_cases_minimum": minimum_condition,
                "complement_binary_cases_minimum": support[
                    "complement_binary_cases_minimum"
                ],
                "combined_binary_cases_minimum": support[
                    "combined_binary_cases_minimum"
                ],
                "condition_distinct_source_signatures_minimum": 0,
                "complement_distinct_source_signatures_minimum": 0,
                "condition_state_episodes_minimum": 0,
                "complement_state_episodes_minimum": 0,
            },
            include_signature_and_episode_floors=False,
        )
        output.append(
            {
                "block_id": f"ROLLING_{index:02d}",
                "start_row_zero_based": start,
                "end_row_zero_based_inclusive": start + width - 1,
                "start_date": selected[0].session_date.isoformat(),
                "end_date": selected[-1].session_date.isoformat(),
                "metrics": metrics,
            }
        )
    return output


def apply_holm_bonferroni(
    records: Sequence[dict[str, Any]],
    *,
    family_size: int,
) -> None:
    if len(records) != family_size:
        raise ValueError("Holm family size must remain fixed")
    ordered = sorted(
        records,
        key=lambda record: (
            _p_for_multiplicity(record),
            str(record["candidate_code"]),
        ),
    )
    running = 0.0
    for index, record in enumerate(ordered):
        raw = _p_for_multiplicity(record)
        adjusted = min(1.0, raw * (family_size - index))
        running = max(running, adjusted)
        record["holm_adjusted_p_value"] = _rounded(running)


def apply_stability_gates(
    record: dict[str, Any],
    *,
    definition: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    failures: list[str] = []
    full = _mapping(record["full_development"])
    if not full["support_eligible"]:
        failures.extend(full["support_failures"])
    effect = _number(full.get("effect_pp"))
    minimum_effect = float(definition["minimum_full_effect_pp"])
    if effect is None or effect < minimum_effect:
        failures.append("FULL_EFFECT_BELOW_FROZEN_MINIMUM")
    interval = list(full["newcombe_wilson_95pct_effect_pp"])
    if (
        _number(interval[0]) is None
        or _number(interval[1]) is None
        or float(interval[0]) <= 0
    ):
        failures.append("FULL_NEWCOMBE_INTERVAL_DOES_NOT_EXCLUDE_ZERO")
    condition_median = _number(
        _mapping(full["condition_path_profile"]).get(
            "median_signed_close_displacement"
        )
    )
    if condition_median is None or condition_median <= 0:
        failures.append("CONDITION_MEDIAN_NOT_POSITIVE")
    if definition["require_complement_median_opposite"]:
        complement_median = _number(
            _mapping(full["complement_path_profile"]).get(
                "median_signed_close_displacement"
            )
        )
        if complement_median is None or complement_median >= 0:
            failures.append("COMPLEMENT_MEDIAN_NOT_NEGATIVE")
    multiplicity = _mapping(protocol["multiplicity"])
    adjusted = _number(record.get("holm_adjusted_p_value"))
    if adjusted is None or adjusted > float(multiplicity["alpha"]):
        failures.append("HOLM_ADJUSTED_P_ABOVE_0_10")

    annual_summary = stability_summary(
        record["calendar_blocks"],
        minimum_effect_pp=minimum_effect,
    )
    rolling_summary = stability_summary(
        record["rolling_blocks"],
        minimum_effect_pp=minimum_effect,
    )
    record["calendar_stability"] = annual_summary
    record["rolling_stability"] = rolling_summary
    _apply_calendar_gates(
        failures,
        annual_summary,
        _mapping(_mapping(protocol["calendar_year_blocks"])["gates"]),
    )
    _apply_rolling_gates(
        failures,
        rolling_summary,
        _mapping(_mapping(protocol["rolling_blocks"])["gates"]),
    )
    record["gate_failures"] = sorted(set(failures))
    record["gate_pass"] = not record["gate_failures"]


def stability_summary(
    blocks: Sequence[Mapping[str, Any]],
    *,
    minimum_effect_pp: float,
) -> dict[str, Any]:
    eligible = [
        block
        for block in blocks
        if _mapping(block["metrics"])["support_eligible"]
    ]
    effects = [
        float(_mapping(block["metrics"])["effect_pp"])
        for block in eligible
        if _number(_mapping(block["metrics"]).get("effect_pp")) is not None
    ]
    positive = sum(effect > 0 for effect in effects)
    opposite_flags = [effect < 0 for effect in effects]
    return {
        "total_blocks": len(blocks),
        "eligible_blocks": len(eligible),
        "eligible_block_ids": [block["block_id"] for block in eligible],
        "positive_effect_blocks": positive,
        "positive_effect_fraction": (
            _rounded(positive / len(effects)) if effects else None
        ),
        "median_effect_pp": (
            _rounded(statistics.median(effects)) if effects else None
        ),
        "minimum_effect_pp": min(effects) if effects else None,
        "maximum_effect_pp": max(effects) if effects else None,
        "catastrophic_reversal_count": sum(
            effect <= -minimum_effect_pp for effect in effects
        ),
        "maximum_consecutive_opposite_effect_blocks": (
            _maximum_consecutive_true(opposite_flags)
        ),
        "latest_eligible_block_id": (
            eligible[-1]["block_id"] if eligible else None
        ),
        "latest_eligible_effect_pp": (
            _mapping(eligible[-1]["metrics"]).get("effect_pp")
            if eligible
            else None
        ),
    }


def stability_rank_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    rolling = _mapping(record["rolling_stability"])
    annual = _mapping(record["calendar_stability"])
    full = _mapping(record["full_development"])
    contingency = _mapping(full["contingency"])
    return (
        -int(bool(record["gate_pass"])),
        float(record["holm_adjusted_p_value"]),
        -float(rolling["positive_effect_fraction"]),
        -float(annual["positive_effect_fraction"]),
        -float(full["effect_pp"]),
        -(
            int(contingency["condition_up"])
            + int(contingency["condition_down"])
        ),
        str(record["candidate_code"]),
    )


def validate_m5_semantics(
    result: Mapping[str, Any],
    *,
    frozen_manifest: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if _embedded_hash(result, "m5_hash") != result.get("m5_hash"):
        errors.append("M5_HASH_MISMATCH")
    if result.get("candidate_family_count") != 4:
        errors.append("CANDIDATE_FAMILY_COUNT_NOT_FOUR")
    if set(_mapping(result.get("sessions"))) != {"LONDON", "NEW_YORK"}:
        errors.append("SESSION_KEYS_NOT_EXACT")
        return errors
    codes: list[str] = []
    shortlisted = 0
    for session_code, expected_count in (("LONDON", 2), ("NEW_YORK", 2)):
        session = _mapping(_mapping(result["sessions"])[session_code])
        records = list(session["candidate_records"])
        if len(records) != expected_count:
            errors.append(f"{session_code}:CANDIDATE_COUNT_NOT_TWO")
        for record in records:
            codes.append(str(record["candidate_code"]))
            _validate_candidate_record(record, errors)
        shortlist = list(session["shortlist"])
        if len(shortlist) > 2:
            errors.append(f"{session_code}:SHORTLIST_CAP_EXCEEDED")
        passing = [record for record in records if record["gate_pass"]]
        expected = sorted(passing, key=stability_rank_key)[:2]
        if [item["candidate_code"] for item in shortlist] != [
            item["candidate_code"] for item in expected
        ]:
            errors.append(f"{session_code}:SHORTLIST_RANKING_MISMATCH")
        shortlisted += len(shortlist)
    expected_codes = [
        item["candidate_code"] for item in frozen_manifest["candidate_registry"]
    ]
    if codes != expected_codes:
        errors.append("CANDIDATE_REGISTRY_ORDER_OR_ID_MISMATCH")
    if result.get("total_shortlisted") != shortlisted:
        errors.append("TOTAL_SHORTLIST_COUNT_MISMATCH")
    boundary = _mapping(result.get("interpretation_boundary"))
    if dict(boundary) != {
        "calendar_2025_values_opened": False,
        "calendar_2026_values_opened": False,
        "cot_used_as_pass_gate": False,
        "development_validation_credit": False,
        "execution_variants": 0,
        "new_candidates_added_after_freeze": 0,
        "rejected_zn_rules_reopened": False,
        "trades_or_returns": 0,
    }:
        errors.append("RESEARCH_BOUNDARY_VIOLATION")
    return sorted(set(errors))


def _validate_candidate_record(
    record: Mapping[str, Any],
    errors: list[str],
) -> None:
    code = str(record.get("candidate_code"))
    full = _mapping(record.get("full_development"))
    contingency = _mapping(full.get("contingency"))
    if min(int(value) for value in contingency.values()) < 0:
        errors.append(f"{code}:NEGATIVE_CONTINGENCY")
    if bool(record.get("gate_pass")) == bool(record.get("gate_failures")):
        errors.append(f"{code}:GATE_STATUS_MISMATCH")
    if record.get("shortlisted") and not record.get("gate_pass"):
        errors.append(f"{code}:FAILED_CANDIDATE_SHORTLISTED")
    annual = list(record.get("calendar_blocks", []))
    rolling = list(record.get("rolling_blocks", []))
    if len(annual) != 4:
        errors.append(f"{code}:ANNUAL_BLOCK_COUNT_NOT_FOUR")
    expected_rolling = 13
    if len(rolling) != expected_rolling:
        errors.append(f"{code}:ROLLING_BLOCK_COUNT_NOT_{expected_rolling}")
    for block in [*annual, *rolling]:
        metrics = _mapping(block["metrics"])
        block_contingency = _mapping(metrics["contingency"])
        condition_binary = int(block_contingency["condition_up"]) + int(
            block_contingency["condition_down"]
        )
        complement_binary = int(block_contingency["complement_up"]) + int(
            block_contingency["complement_down"]
        )
        condition_rate = (
            100 * int(block_contingency["condition_up"]) / condition_binary
            if condition_binary
            else None
        )
        complement_rate = (
            100 * int(block_contingency["complement_up"]) / complement_binary
            if complement_binary
            else None
        )
        expected_effect = (
            _rounded(condition_rate - complement_rate)
            if condition_rate is not None and complement_rate is not None
            else None
        )
        if not _same_number(metrics.get("effect_pp"), expected_effect):
            errors.append(f"{code}:{block['block_id']}:EFFECT_MISMATCH")
    adjusted = _number(record.get("holm_adjusted_p_value"))
    if adjusted is None or not 0 <= adjusted <= 1:
        errors.append(f"{code}:HOLM_VALUE_INVALID")


def _apply_calendar_gates(
    failures: list[str],
    summary: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> None:
    eligible = int(summary["eligible_blocks"])
    if eligible < int(gates["eligible_blocks_minimum"]):
        failures.append("ANNUAL_ELIGIBLE_BLOCKS_BELOW_MINIMUM")
    fraction = _number(summary.get("positive_effect_fraction"))
    if (
        fraction is None
        or fraction < float(gates["positive_effect_fraction_minimum"])
    ):
        failures.append("ANNUAL_POSITIVE_EFFECT_FRACTION_BELOW_MINIMUM")
    median = _number(summary.get("median_effect_pp"))
    if median is None or median < float(gates["median_effect_pp_minimum"]):
        failures.append("ANNUAL_MEDIAN_EFFECT_BELOW_MINIMUM")
    if int(summary["catastrophic_reversal_count"]) > 0:
        failures.append("ANNUAL_CATASTROPHIC_REVERSAL_PRESENT")
    latest = _number(summary.get("latest_eligible_effect_pp"))
    if latest is None or latest <= 0:
        failures.append("LATEST_ELIGIBLE_ANNUAL_EFFECT_NOT_POSITIVE")


def _apply_rolling_gates(
    failures: list[str],
    summary: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> None:
    eligible = int(summary["eligible_blocks"])
    if eligible < int(gates["eligible_blocks_minimum"]):
        failures.append("ROLLING_ELIGIBLE_BLOCKS_BELOW_MINIMUM")
    fraction = _number(summary.get("positive_effect_fraction"))
    if (
        fraction is None
        or fraction < float(gates["positive_effect_fraction_minimum"])
    ):
        failures.append("ROLLING_POSITIVE_EFFECT_FRACTION_BELOW_MINIMUM")
    median = _number(summary.get("median_effect_pp"))
    if median is None or median < float(gates["median_effect_pp_minimum"]):
        failures.append("ROLLING_MEDIAN_EFFECT_BELOW_MINIMUM")
    if int(summary["maximum_consecutive_opposite_effect_blocks"]) > int(
        gates["maximum_consecutive_opposite_effect_blocks"]
    ):
        failures.append("ROLLING_CONSECUTIVE_OPPOSITE_BLOCKS_EXCEEDED")
    latest = _number(summary.get("latest_eligible_effect_pp"))
    if latest is None or latest <= 0:
        failures.append("LATEST_ELIGIBLE_ROLLING_EFFECT_NOT_POSITIVE")


def _conditions_match(
    case: DiscoveryCase,
    conditions: Sequence[Mapping[str, Any]],
) -> bool:
    return all(
        case.features[str(condition["feature_id"])].state
        == str(condition["state"])
        for condition in conditions
    )


def _membership_episodes(
    memberships: Sequence[tuple[DiscoveryCase, str]],
    target: str,
) -> int:
    episodes = 0
    previous = False
    for _, membership in memberships:
        current = membership == target
        if current and not previous:
            episodes += 1
        previous = current
    return episodes


def _maximum_consecutive_true(values: Sequence[bool]) -> int:
    maximum = 0
    current = 0
    for value in values:
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def _p_for_multiplicity(record: Mapping[str, Any]) -> float:
    p_value = _number(
        _mapping(record["full_development"]).get(
            "fisher_exact_two_sided_p_value"
        )
    )
    return p_value if p_value is not None else 1.0


def _embedded_hash(document: Mapping[str, Any], field: str) -> str:
    return canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )


def _percentage(numerator: int, denominator: int) -> float:
    return _rounded(100 * numerator / denominator) if denominator else 0.0


def _rounded(value: float | None) -> float | None:
    return round(value, ROUND_DECIMALS) if value is not None else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _same_number(left: Any, right: float | None) -> bool:
    left_number = _number(left)
    if left_number is None or right is None:
        return left_number is right
    return abs(left_number - right) <= 1e-8
