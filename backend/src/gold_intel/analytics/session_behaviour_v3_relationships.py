from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.analytics.session_behaviour_v3_discovery import (
    FeatureObservation,
    extract_case_features,
)

RELATIONSHIP_ENGINE_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M4_RELATIONSHIPS_V0_1"
ROUND_DECIMALS = 8
Z_95 = 1.959963984540054
FLAT_EPSILON = 0.01


@dataclass(frozen=True, slots=True)
class NeutralOutcome:
    close_direction: str
    signed_close_displacement: float
    absolute_close_displacement: float
    sixty_minute_direction: str
    maximum_upward_displacement: float
    maximum_downward_displacement_magnitude: float
    session_range: float
    extreme_order: str


@dataclass(frozen=True, slots=True)
class DiscoveryCase:
    case_id: str
    record_hash: str
    session_code: str
    session_date: date
    features: Mapping[str, FeatureObservation]
    outcome: NeutralOutcome


def materialize_discovery_case(
    case: Mapping[str, Any],
    *,
    features: Sequence[Mapping[str, Any]],
) -> DiscoveryCase:
    metadata = _mapping(case.get("case_metadata"))
    if metadata.get("data_partition") != "DEVELOPMENT_2021_2024":
        raise ValueError(f"Non-development case: {metadata.get('case_id')}")
    if metadata.get("access_class") != "DEVELOPMENT":
        raise ValueError(f"Wrong access class: {metadata.get('case_id')}")
    session_code = str(metadata["session_code"])
    if session_code not in {"LONDON", "NEW_YORK"}:
        raise ValueError(f"Unsupported session: {session_code}")
    parsed_date = date.fromisoformat(str(metadata["session_date"]))
    if not date(2021, 8, 1) <= parsed_date <= date(2024, 12, 31):
        raise ValueError(f"Case outside development dates: {metadata.get('case_id')}")
    decision_state = _mapping(case.get("decision_state"))
    if decision_state.get("decision_eligible") is not True:
        raise ValueError(f"Decision state is not eligible: {metadata.get('case_id')}")
    outcome = extract_neutral_outcome(_mapping(case.get("subsequent_behaviour")))
    observations = extract_case_features(
        decision_state,
        session_code=session_code,
        features=features,
    )
    observations = normalize_registered_feature_states(observations)
    return DiscoveryCase(
        case_id=str(metadata["case_id"]),
        record_hash=str(metadata["record_hash"]),
        session_code=session_code,
        session_date=parsed_date,
        features=observations,
        outcome=outcome,
    )


def normalize_registered_feature_states(
    observations: Mapping[str, FeatureObservation],
) -> dict[str, FeatureObservation]:
    output: dict[str, FeatureObservation] = {}
    for feature_id, observation in observations.items():
        normalized_state = observation.state
        if (
            feature_id == "MACRO_REACTION_FUNCTION"
            and observation.state == "MIXED_MACRO_REACTION_FUNCTION"
        ):
            normalized_state = "BALANCED_REACTION_FUNCTION"
        elif (
            feature_id.startswith("STRUCT_")
            and feature_id.endswith("_TREND")
            and observation.state == "RANGE"
        ):
            normalized_state = "MIXED_OR_TRANSITIONING"
        output[feature_id] = (
            observation
            if normalized_state == observation.state
            else FeatureObservation(
                state=normalized_state,
                source_signature=observation.source_signature,
                epistemic_status=observation.epistemic_status,
                quality=observation.quality,
            )
        )
    return output


def extract_neutral_outcome(
    subsequent: Mapping[str, Any],
) -> NeutralOutcome:
    if subsequent.get("decision_eligible") is not False:
        raise ValueError("Subsequent behaviour must be outcome-only")
    horizons = {
        str(item["horizon"]): _mapping(item)
        for item in _sequence(subsequent.get("fixed_horizons"))
    }
    close = _fact_number(
        horizons.get("SESSION_CLOSE", {}).get("signed_displacement")
    )
    sixty = _fact_number(horizons.get("60m", {}).get("signed_displacement"))
    excursions = _mapping(subsequent.get("neutral_excursions"))
    extremes = _mapping(subsequent.get("extremes"))
    required = {
        "absolute_close": _fact_number(
            excursions.get("absolute_close_displacement")
        ),
        "close": close,
        "max_down": _fact_number(
            excursions.get("maximum_downward_displacement")
        ),
        "max_up": _fact_number(excursions.get("maximum_upward_displacement")),
        "range": _fact_number(excursions.get("session_range")),
        "sixty": sixty,
    }
    missing = sorted(key for key, value in required.items() if value is None)
    if missing:
        raise ValueError(f"Incomplete neutral outcome: {missing}")
    max_down = float(required["max_down"])
    if max_down > 0:
        raise ValueError("Maximum downward displacement must be non-positive")
    extreme_order = str(_mapping(extremes.get("extreme_order")).get("value"))
    if extreme_order not in {"HIGH_FIRST", "LOW_FIRST", "SAME_BAR"}:
        raise ValueError(f"Invalid extreme order: {extreme_order}")
    return NeutralOutcome(
        close_direction=_direction(float(required["close"])),
        signed_close_displacement=float(required["close"]),
        absolute_close_displacement=float(required["absolute_close"]),
        sixty_minute_direction=_direction(float(required["sixty"])),
        maximum_upward_displacement=float(required["max_up"]),
        maximum_downward_displacement_magnitude=abs(max_down),
        session_range=float(required["range"]),
        extreme_order=extreme_order,
    )


def build_discovery_results(
    cases: Sequence[DiscoveryCase],
    *,
    frozen_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    features = list(frozen_manifest["feature_registry"])
    interactions = list(frozen_manifest["interaction_registry"])
    feature_map = {str(item["feature_id"]): item for item in features}
    support = _mapping(frozen_manifest["support_floors"])
    candidate_policy = _mapping(frozen_manifest["candidate_policy"])
    statistical = _mapping(frozen_manifest["statistical_policy"])
    by_session = {
        session: sorted(
            [case for case in cases if case.session_code == session],
            key=lambda item: (item.session_date, item.case_id),
        )
        for session in ("LONDON", "NEW_YORK")
    }
    if len(by_session["LONDON"]) != 833 or len(by_session["NEW_YORK"]) != 826:
        raise ValueError("Unexpected development case counts")

    sessions: dict[str, Any] = {}
    all_candidates: list[dict[str, Any]] = []
    for session_code in ("LONDON", "NEW_YORK"):
        session_cases = by_session[session_code]
        baseline = _baseline(session_cases)
        coverage = feature_coverage(
            session_cases,
            [
                feature
                for feature in features
                if session_code in feature["sessions"]
            ],
        )
        singles = evaluate_single_conditions(
            session_cases,
            features=features,
            support_policy=_mapping(support["single_condition"]),
        )
        apply_benjamini_hochberg(singles)
        interactions_result = evaluate_interactions(
            session_cases,
            interactions=interactions,
            single_records=singles,
            support_policy=_mapping(support["interaction"]),
        )
        apply_benjamini_hochberg(interactions_result)
        apply_candidate_gates(
            singles,
            feature_map=feature_map,
            candidate_policy=candidate_policy,
        )
        apply_candidate_gates(
            interactions_result,
            feature_map=feature_map,
            candidate_policy=candidate_policy,
        )
        eligible_candidates = [
            record
            for record in [*singles, *interactions_result]
            if record["candidate_gate_pass"]
        ]
        ranked = sorted(eligible_candidates, key=candidate_rank_key)
        selected: list[dict[str, Any]] = []
        for rank, record in enumerate(
            ranked[: int(candidate_policy["maximum_per_session"])],
            start=1,
        ):
            candidate = {
                "candidate_code": (
                    f"V3_M4_{session_code}_{record['condition_id']}_V0_1"
                ),
                "condition_id": record["condition_id"],
                "direction": record["empirical_direction"],
                "evidence_stage": record["stage"],
                "provisional_rank": rank,
                "status": str(candidate_policy["advance_label"]),
            }
            selected.append(candidate)
            all_candidates.append(candidate)
            record["advanced_as_provisional_candidate"] = True
            record["provisional_candidate_code"] = candidate["candidate_code"]
        sessions[session_code] = {
            "baseline": baseline,
            "candidate_gate_pass_count": len(eligible_candidates),
            "feature_coverage": coverage,
            "interaction_results": interactions_result,
            "provisional_candidates": selected,
            "single_condition_results": singles,
            "summary": {
                "interaction_conditions_registered": sum(
                    session_code in item["sessions"] for item in interactions
                ),
                "interaction_conditions_support_eligible": sum(
                    bool(item["support_eligible"]) for item in interactions_result
                ),
                "interaction_conditions_tested": len(interactions_result),
                "single_conditions_registered": sum(
                    len(item["tested_states"])
                    for item in features
                    if session_code in item["sessions"]
                ),
                "single_conditions_support_eligible": sum(
                    bool(item["support_eligible"]) for item in singles
                ),
                "single_conditions_tested": len(singles),
            },
        }
    result: dict[str, Any] = {
        "candidate_policy": dict(candidate_policy),
        "case_counts": {"LONDON": 833, "NEW_YORK": 826, "total": 1659},
        "created_at": str(frozen_manifest["recorded_at"]),
        "discovery_hash": "",
        "discovery_version": RELATIONSHIP_ENGINE_VERSION,
        "interpretation_boundary": {
            "calendar_2025_values_opened": False,
            "calendar_2026_values_opened": False,
            "causal_claims": False,
            "combined_session_result": False,
            "development_only": True,
            "execution_variants": 0,
            "provisional_candidates_have_validation_credit": False,
            "rejected_zn_rules_reopened": False,
            "trades_or_returns": 0,
        },
        "milestone": "V3_M4_BOUNDED_CONDITIONAL_BIAS_DISCOVERY",
        "multiplicity_policy": dict(_mapping(statistical["multiplicity"])),
        "pre_result_manifest": {
            "manifest_hash": str(frozen_manifest["manifest_hash"]),
            "registry_fingerprint": str(
                frozen_manifest["implementation_freeze"]["registry_fingerprint"]
            ),
        },
        "provisional_candidate_count": len(all_candidates),
        "sessions": sessions,
        "source_case_matrix": dict(frozen_manifest["frozen_inputs"]["case_matrix"]),
        "support_floors": dict(support),
    }
    result["discovery_hash"] = _embedded_hash(result, "discovery_hash")
    return result


def feature_coverage(
    cases: Sequence[DiscoveryCase],
    features: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for feature in features:
        feature_id = str(feature["feature_id"])
        observations = [case.features[feature_id] for case in cases]
        states = Counter(item.state for item in observations)
        qualities = Counter(item.quality for item in observations)
        epistemic = Counter(item.epistemic_status for item in observations)
        known = sum(item.state != "UNKNOWN" for item in observations)
        output.append(
            {
                "coverage_pct": _percentage(known, len(cases)),
                "epistemic_status_counts": dict(sorted(epistemic.items())),
                "feature_id": feature_id,
                "known": known,
                "quality_counts": dict(sorted(qualities.items())),
                "state_counts": dict(sorted(states.items())),
                "total": len(cases),
                "unknown": len(cases) - known,
            }
        )
    return output


def evaluate_single_conditions(
    cases: Sequence[DiscoveryCase],
    *,
    features: Sequence[Mapping[str, Any]],
    support_policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    session_code = cases[0].session_code
    for definition in features:
        if session_code not in definition["sessions"]:
            continue
        feature_id = str(definition["feature_id"])
        for state in definition["tested_states"]:
            known = [
                case
                for case in cases
                if case.features[feature_id].state != "UNKNOWN"
            ]
            condition = [
                case for case in known if case.features[feature_id].state == state
            ]
            record = evaluate_condition(
                cases=cases,
                known_cases=known,
                condition_cases=condition,
                condition_id=f"SINGLE__{feature_id}__{state}",
                conditions=[{"feature_id": feature_id, "state": state}],
                stage="SINGLE",
                source_signatures=[
                    case.features[feature_id].source_signature for case in condition
                ],
                state_episodes=_state_episodes(
                    known,
                    lambda case, fid=feature_id, expected=state: (
                        case.features[fid].state == expected
                    ),
                ),
                support_policy=support_policy,
            )
            record["feature_family"] = str(definition["family"])
            record["feature_layer"] = str(definition["layer"])
            records.append(record)
    return records


def evaluate_interactions(
    cases: Sequence[DiscoveryCase],
    *,
    interactions: Sequence[Mapping[str, Any]],
    single_records: Sequence[Mapping[str, Any]],
    support_policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    singles = {
        (
            str(record["conditions"][0]["feature_id"]),
            str(record["conditions"][0]["state"]),
        ): record
        for record in single_records
    }
    records: list[dict[str, Any]] = []
    session_code = cases[0].session_code
    for interaction in interactions:
        if session_code not in interaction["sessions"]:
            continue
        left, right = list(interaction["conditions"])
        left_id = str(left["feature_id"])
        right_id = str(right["feature_id"])
        left_state = str(left["state"])
        right_state = str(right["state"])
        known = [
            case
            for case in cases
            if case.features[left_id].state != "UNKNOWN"
            and case.features[right_id].state != "UNKNOWN"
        ]
        condition = [
            case
            for case in known
            if case.features[left_id].state == left_state
            and case.features[right_id].state == right_state
        ]
        record = evaluate_condition(
            cases=cases,
            known_cases=known,
            condition_cases=condition,
            condition_id=str(interaction["interaction_id"]),
            conditions=[
                {"feature_id": left_id, "state": left_state},
                {"feature_id": right_id, "state": right_state},
            ],
            stage="INTERACTION",
            source_signatures=[
                canonical_hash(
                    [
                        case.features[left_id].source_signature,
                        case.features[right_id].source_signature,
                    ]
                )
                for case in condition
            ],
            state_episodes=_state_episodes(
                known,
                lambda case, lid=left_id, ls=left_state, rid=right_id, rs=right_state: (
                    case.features[lid].state == ls
                    and case.features[rid].state == rs
                ),
            ),
            support_policy=support_policy,
        )
        left_record = singles[(left_id, left_state)]
        right_record = singles[(right_id, right_state)]
        constituent_effects = [
            _number(left_record.get("up_rate_difference_pp")),
            _number(right_record.get("up_rate_difference_pp")),
        ]
        available_effects = [abs(value) for value in constituent_effects if value is not None]
        effect = _number(record.get("up_rate_difference_pp"))
        record["constituent_single_conditions"] = [
            {
                "condition_id": left_record["condition_id"],
                "support_eligible": left_record["support_eligible"],
                "up_rate_difference_pp": left_record["up_rate_difference_pp"],
            },
            {
                "condition_id": right_record["condition_id"],
                "support_eligible": right_record["support_eligible"],
                "up_rate_difference_pp": right_record["up_rate_difference_pp"],
            },
        ]
        record["incremental_absolute_effect_pp"] = (
            _rounded(abs(effect) - max(available_effects))
            if effect is not None and len(available_effects) == 2
            else None
        )
        record["rationale"] = str(interaction["rationale"])
        records.append(record)
    return records


def evaluate_condition(
    *,
    cases: Sequence[DiscoveryCase],
    known_cases: Sequence[DiscoveryCase],
    condition_cases: Sequence[DiscoveryCase],
    condition_id: str,
    conditions: Sequence[Mapping[str, str]],
    stage: str,
    source_signatures: Sequence[str],
    state_episodes: int,
    support_policy: Mapping[str, Any],
) -> dict[str, Any]:
    condition_binary = [
        case for case in condition_cases if case.outcome.close_direction != "FLAT"
    ]
    condition_ids = {case.case_id for case in condition_cases}
    complement_all = [
        case for case in known_cases if case.case_id not in condition_ids
    ]
    complement_binary = [
        case for case in complement_all if case.outcome.close_direction != "FLAT"
    ]
    known_binary = [
        case for case in known_cases if case.outcome.close_direction != "FLAT"
    ]
    condition_up = sum(
        case.outcome.close_direction == "UP" for case in condition_binary
    )
    condition_down = len(condition_binary) - condition_up
    complement_up = sum(
        case.outcome.close_direction == "UP" for case in complement_binary
    )
    complement_down = len(complement_binary) - complement_up
    condition_rate = (
        condition_up / len(condition_binary) if condition_binary else None
    )
    complement_rate = (
        complement_up / len(complement_binary) if complement_binary else None
    )
    difference = (
        100 * (condition_rate - complement_rate)
        if condition_rate is not None and complement_rate is not None
        else None
    )
    failures: list[str] = []
    coverage_pct = _percentage(len(known_cases), len(cases))
    prevalence_pct = _percentage(len(condition_binary), len(cases))
    if stage == "SINGLE":
        if coverage_pct < float(support_policy["feature_known_coverage_pct_minimum"]):
            failures.append("FEATURE_KNOWN_COVERAGE_BELOW_MINIMUM")
        minimum_cases = int(support_policy["condition_cases_minimum"])
        minimum_prevalence = float(
            support_policy["condition_prevalence_pct_minimum"]
        )
        minimum_complement = int(support_policy["known_complement_cases_minimum"])
        minimum_signatures = int(
            support_policy["distinct_source_signatures_minimum"]
        )
        minimum_episodes = int(support_policy["state_episodes_minimum"])
    else:
        minimum_cases = int(support_policy["condition_cases_minimum"])
        minimum_prevalence = float(
            support_policy["condition_prevalence_pct_minimum"]
        )
        minimum_complement = int(support_policy["known_complement_cases_minimum"])
        minimum_signatures = int(
            support_policy["distinct_joint_source_signatures_minimum"]
        )
        minimum_episodes = int(support_policy["state_episodes_minimum"])
    if len(condition_binary) < minimum_cases:
        failures.append("CONDITION_CASES_BELOW_MINIMUM")
    if prevalence_pct < minimum_prevalence:
        failures.append("CONDITION_PREVALENCE_BELOW_MINIMUM")
    if len(complement_binary) < minimum_complement:
        failures.append("KNOWN_COMPLEMENT_CASES_BELOW_MINIMUM")
    distinct_signatures = len(set(source_signatures))
    if distinct_signatures < minimum_signatures:
        failures.append("DISTINCT_SOURCE_SIGNATURES_BELOW_MINIMUM")
    if state_episodes < minimum_episodes:
        failures.append("STATE_EPISODES_BELOW_MINIMUM")
    support_eligible = not failures

    condition_ci = (
        wilson_interval(condition_up, len(condition_binary))
        if condition_binary
        else [None, None]
    )
    complement_ci = (
        wilson_interval(complement_up, len(complement_binary))
        if complement_binary
        else [None, None]
    )
    difference_ci = (
        newcombe_difference_interval(
            condition_up,
            len(condition_binary),
            complement_up,
            len(complement_binary),
        )
        if condition_binary and complement_binary
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
        "advanced_as_provisional_candidate": False,
        "book_direction_hint": None,
        "book_direction_hint_alignment": "NOT_APPLICABLE",
        "candidate_gate_failures": [],
        "candidate_gate_pass": False,
        "condition_id": condition_id,
        "condition_path_profile": path_profile(condition_cases),
        "condition_prevalence_pct_of_all_session_cases": prevalence_pct,
        "conditions": [dict(item) for item in conditions],
        "contingency": {
            "complement_down": complement_down,
            "complement_up": complement_up,
            "condition_down": condition_down,
            "condition_up": condition_up,
        },
        "distinct_source_signatures": distinct_signatures,
        "empirical_direction": (
            "BULLISH"
            if difference is not None and difference > 0
            else "BEARISH"
            if difference is not None and difference < 0
            else "NEUTRAL"
        ),
        "feature_known_cases": len(known_cases),
        "feature_known_coverage_pct": coverage_pct,
        "fisher_exact_two_sided_p_value": _rounded(p_value),
        "known_binary_cases": len(known_binary),
        "known_complement_path_profile": path_profile(complement_all),
        "newcombe_wilson_95pct_difference_pp": [
            _rounded(100 * value) if value is not None else None
            for value in difference_ci
        ],
        "odds_ratio": _rounded(
            odds_ratio(
                condition_up,
                condition_down,
                complement_up,
                complement_down,
            )
        ),
        "provisional_candidate_code": None,
        "stage": stage,
        "state_episodes": state_episodes,
        "support_eligible": support_eligible,
        "support_failures": failures,
        "up_rate_difference_pp": _rounded(difference),
        "up_rate_pct": {
            "complement": (
                _rounded(100 * complement_rate)
                if complement_rate is not None
                else None
            ),
            "condition": (
                _rounded(100 * condition_rate)
                if condition_rate is not None
                else None
            ),
        },
        "wilson_95pct_up_rate_pct": {
            "complement": [
                _rounded(100 * value) if value is not None else None
                for value in complement_ci
            ],
            "condition": [
                _rounded(100 * value) if value is not None else None
                for value in condition_ci
            ],
        },
        "benjamini_hochberg_q_value": None,
    }


def apply_benjamini_hochberg(records: Sequence[dict[str, Any]]) -> None:
    eligible = [
        record
        for record in records
        if record["support_eligible"]
        and record["fisher_exact_two_sided_p_value"] is not None
    ]
    ordered = sorted(
        eligible,
        key=lambda record: (
            float(record["fisher_exact_two_sided_p_value"]),
            str(record["condition_id"]),
        ),
    )
    running = 1.0
    total = len(ordered)
    for index in range(total - 1, -1, -1):
        rank = index + 1
        raw = float(ordered[index]["fisher_exact_two_sided_p_value"]) * total / rank
        running = min(running, raw, 1.0)
        ordered[index]["benjamini_hochberg_q_value"] = _rounded(running)


def apply_candidate_gates(
    records: Sequence[dict[str, Any]],
    *,
    feature_map: Mapping[str, Mapping[str, Any]],
    candidate_policy: Mapping[str, Any],
) -> None:
    q_threshold = 0.10
    for record in records:
        failures = list(record["support_failures"])
        effect = _number(record.get("up_rate_difference_pp"))
        q_value = _number(record.get("benjamini_hochberg_q_value"))
        minimum_effect = 7.5 if record["stage"] == "SINGLE" else 10.0
        interval = record["newcombe_wilson_95pct_difference_pp"]
        lower = _number(interval[0])
        upper = _number(interval[1])
        median_signed = _number(
            record["condition_path_profile"].get(
                "median_signed_close_displacement"
            )
        )
        if q_value is None or q_value > q_threshold:
            failures.append("BH_Q_VALUE_ABOVE_0_10")
        if effect is None or abs(effect) < minimum_effect:
            failures.append("ABSOLUTE_EFFECT_BELOW_FROZEN_MINIMUM")
        if (
            effect is None
            or lower is None
            or upper is None
            or (effect > 0 and lower <= 0)
            or (effect < 0 and upper >= 0)
            or effect == 0
        ):
            failures.append("NEWCOMBE_WILSON_INTERVAL_INCLUDES_ZERO")
        if (
            effect is None
            or median_signed is None
            or (effect > 0 and median_signed <= 0)
            or (effect < 0 and median_signed >= 0)
            or effect == 0
        ):
            failures.append("MEDIAN_SIGN_DOES_NOT_MATCH_ASSOCIATION")
        if record["stage"] == "INTERACTION":
            constituent = record["constituent_single_conditions"]
            if not all(item["support_eligible"] for item in constituent):
                failures.append("CONSTITUENT_SINGLE_SUPPORT_INELIGIBLE")
            incremental = _number(record.get("incremental_absolute_effect_pp"))
            if incremental is None or incremental < 3.0:
                failures.append("INTERACTION_INCREMENTAL_EFFECT_BELOW_3PP")
        record["candidate_gate_failures"] = sorted(set(failures))
        record["candidate_gate_pass"] = not record["candidate_gate_failures"]
        hint = _condition_direction_hint(record["conditions"], feature_map)
        record["book_direction_hint"] = hint
        record["book_direction_hint_alignment"] = (
            "NOT_SPECIFIED"
            if hint is None
            else "ALIGNED"
            if (hint == 1 and record["empirical_direction"] == "BULLISH")
            or (hint == -1 and record["empirical_direction"] == "BEARISH")
            else "CONTRADICTED"
        )


def candidate_rank_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    q_value = _number(record.get("benjamini_hochberg_q_value"))
    effect = abs(float(record["up_rate_difference_pp"]))
    support = int(record["contingency"]["condition_up"]) + int(
        record["contingency"]["condition_down"]
    )
    return (
        -int(bool(record["candidate_gate_pass"])),
        q_value if q_value is not None else float("inf"),
        -effect,
        -support,
        str(record["condition_id"]),
    )


def path_profile(cases: Sequence[DiscoveryCase]) -> dict[str, Any]:
    if not cases:
        return {
            "case_count": 0,
            "close_direction_counts": {"DOWN": 0, "FLAT": 0, "UP": 0},
            "extreme_order_counts": {
                "HIGH_FIRST": 0,
                "LOW_FIRST": 0,
                "SAME_BAR": 0,
            },
            "median_absolute_close_displacement": None,
            "median_maximum_downward_displacement_magnitude": None,
            "median_maximum_upward_displacement": None,
            "median_session_range": None,
            "median_signed_close_displacement": None,
            "sixty_minute_direction_counts": {"DOWN": 0, "FLAT": 0, "UP": 0},
        }
    outcomes = [case.outcome for case in cases]
    return {
        "case_count": len(cases),
        "close_direction_counts": dict(
            sorted(Counter(item.close_direction for item in outcomes).items())
        ),
        "extreme_order_counts": dict(
            sorted(Counter(item.extreme_order for item in outcomes).items())
        ),
        "median_absolute_close_displacement": _rounded(
            statistics.median(item.absolute_close_displacement for item in outcomes)
        ),
        "median_maximum_downward_displacement_magnitude": _rounded(
            statistics.median(
                item.maximum_downward_displacement_magnitude for item in outcomes
            )
        ),
        "median_maximum_upward_displacement": _rounded(
            statistics.median(
                item.maximum_upward_displacement for item in outcomes
            )
        ),
        "median_session_range": _rounded(
            statistics.median(item.session_range for item in outcomes)
        ),
        "median_signed_close_displacement": _rounded(
            statistics.median(
                item.signed_close_displacement for item in outcomes
            )
        ),
        "sixty_minute_direction_counts": dict(
            sorted(
                Counter(item.sixty_minute_direction for item in outcomes).items()
            )
        ),
    }


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    if min(a, b, c, d) < 0:
        raise ValueError("Contingency counts cannot be negative")
    row_one = a + b
    row_two = c + d
    column_one = a + c
    total = row_one + row_two
    if total == 0:
        return 1.0
    lower = max(0, column_one - row_two)
    upper = min(row_one, column_one)

    def probability(x: int) -> float:
        return (
            math.comb(column_one, x)
            * math.comb(total - column_one, row_one - x)
            / math.comb(total, row_one)
        )

    observed = probability(a)
    return min(
        1.0,
        math.fsum(
            probability(x)
            for x in range(lower, upper + 1)
            if probability(x) <= observed + 1e-15
        ),
    )


def wilson_interval(successes: int, total: int) -> list[float]:
    if total <= 0:
        return [None, None]  # type: ignore[list-item]
    proportion = successes / total
    denominator = 1 + Z_95**2 / total
    center = (proportion + Z_95**2 / (2 * total)) / denominator
    half = (
        Z_95
        * math.sqrt(
            proportion * (1 - proportion) / total
            + Z_95**2 / (4 * total**2)
        )
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def newcombe_difference_interval(
    successes_one: int,
    total_one: int,
    successes_two: int,
    total_two: int,
) -> list[float]:
    p_one = successes_one / total_one
    p_two = successes_two / total_two
    lower_one, upper_one = wilson_interval(successes_one, total_one)
    lower_two, upper_two = wilson_interval(successes_two, total_two)
    difference = p_one - p_two
    lower = difference - math.sqrt(
        (p_one - lower_one) ** 2 + (upper_two - p_two) ** 2
    )
    upper = difference + math.sqrt(
        (upper_one - p_one) ** 2 + (p_two - lower_two) ** 2
    )
    return [max(-1.0, lower), min(1.0, upper)]


def odds_ratio(a: int, b: int, c: int, d: int) -> float | None:
    if a + b == 0 or c + d == 0:
        return None
    if 0 in {a, b, c, d}:
        return (a + 0.5) * (d + 0.5) / ((b + 0.5) * (c + 0.5))
    return a * d / (b * c)


def _baseline(cases: Sequence[DiscoveryCase]) -> dict[str, Any]:
    profile = path_profile(cases)
    counts = Counter(case.outcome.close_direction for case in cases)
    nonflat = counts["UP"] + counts["DOWN"]
    return {
        "case_count": len(cases),
        "close_direction": {
            "DOWN": {
                "count": counts["DOWN"],
                "percentage_of_nonflat": _percentage(counts["DOWN"], nonflat),
            },
            "FLAT": {
                "count": counts["FLAT"],
                "percentage_of_all": _percentage(counts["FLAT"], len(cases)),
            },
            "UP": {
                "count": counts["UP"],
                "percentage_of_nonflat": _percentage(counts["UP"], nonflat),
            },
        },
        "path_profile": profile,
    }


def _state_episodes(
    cases: Sequence[DiscoveryCase],
    predicate: Any,
) -> int:
    episodes = 0
    previous = False
    for case in sorted(cases, key=lambda item: (item.session_date, item.case_id)):
        current = bool(predicate(case))
        if current and not previous:
            episodes += 1
        previous = current
    return episodes


def _condition_direction_hint(
    conditions: Sequence[Mapping[str, Any]],
    feature_map: Mapping[str, Mapping[str, Any]],
) -> int | None:
    hints = [
        feature_map[str(condition["feature_id"])]
        .get("direction_hints", {})
        .get(str(condition["state"]))
        for condition in conditions
    ]
    known = [int(hint) for hint in hints if hint in {-1, 1}]
    if not known or len(set(known)) != 1:
        return None
    return known[0]


def _direction(value: float) -> str:
    if value > FLAT_EPSILON:
        return "UP"
    if value < -FLAT_EPSILON:
        return "DOWN"
    return "FLAT"


def _embedded_hash(document: Mapping[str, Any], field: str) -> str:
    return canonical_hash({key: value for key, value in document.items() if key != field})


def _percentage(numerator: int, denominator: int) -> float:
    return _rounded(100 * numerator / denominator) if denominator else 0.0


def _rounded(value: float | None) -> float | None:
    return round(value, ROUND_DECIMALS) if value is not None else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _fact_number(value: Any) -> float | None:
    return _number(_mapping(value).get("value"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    return (
        list(value)
        if isinstance(value, Sequence) and not isinstance(value, str)
        else []
    )
