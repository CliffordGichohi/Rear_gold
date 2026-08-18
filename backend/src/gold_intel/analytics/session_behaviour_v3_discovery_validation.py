from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.analytics.session_behaviour_v3_relationships import (
    candidate_rank_key,
)

VALIDATION_RULESET_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M4_DISCOVERY_SEMANTICS_V0_1"
)
EXPECTED_CASE_COUNTS = {"LONDON": 833, "NEW_YORK": 826, "total": 1659}


def validate_discovery_semantics(
    discovery: Mapping[str, Any],
    *,
    frozen_manifest: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    _validate_document_header(discovery, frozen_manifest, errors)

    sessions = _mapping(discovery.get("sessions"))
    if set(sessions) != {"LONDON", "NEW_YORK"}:
        errors.append("SESSION_KEYS_NOT_EXACT")
        return errors

    features = list(_sequence(frozen_manifest.get("feature_registry")))
    interactions = list(_sequence(frozen_manifest.get("interaction_registry")))
    all_selected_codes: set[str] = set()
    total_selected = 0
    for session_code in ("LONDON", "NEW_YORK"):
        session = _mapping(sessions.get(session_code))
        expected_total = EXPECTED_CASE_COUNTS[session_code]
        applicable_features = [
            item for item in features if session_code in _sequence(item.get("sessions"))
        ]
        applicable_interactions = [
            item
            for item in interactions
            if session_code in _sequence(item.get("sessions"))
        ]
        _validate_baseline(
            session_code,
            _mapping(session.get("baseline")),
            expected_total,
            errors,
        )
        _validate_coverage(
            session_code,
            _sequence(session.get("feature_coverage")),
            applicable_features,
            expected_total,
            errors,
        )

        singles = _sequence(session.get("single_condition_results"))
        interactions_result = _sequence(session.get("interaction_results"))
        expected_single_ids = [
            f"SINGLE__{feature['feature_id']}__{state}"
            for feature in applicable_features
            for state in _sequence(feature.get("tested_states"))
        ]
        expected_interaction_ids = [
            str(item["interaction_id"]) for item in applicable_interactions
        ]
        if [item.get("condition_id") for item in singles] != expected_single_ids:
            errors.append(f"{session_code}:SINGLE_RESULT_REGISTRY_MISMATCH")
        if [
            item.get("condition_id") for item in interactions_result
        ] != expected_interaction_ids:
            errors.append(f"{session_code}:INTERACTION_RESULT_REGISTRY_MISMATCH")

        for record in singles:
            _validate_relationship_record(
                session_code,
                _mapping(record),
                expected_stage="SINGLE",
                expected_total=expected_total,
                errors=errors,
            )
        for record in interactions_result:
            _validate_relationship_record(
                session_code,
                _mapping(record),
                expected_stage="INTERACTION",
                expected_total=expected_total,
                errors=errors,
            )
        _validate_bh_family(session_code, "SINGLE", singles, errors)
        _validate_bh_family(
            session_code,
            "INTERACTION",
            interactions_result,
            errors,
        )

        summary = _mapping(session.get("summary"))
        expected_summary = {
            "interaction_conditions_registered": len(applicable_interactions),
            "interaction_conditions_support_eligible": sum(
                bool(item.get("support_eligible"))
                for item in interactions_result
            ),
            "interaction_conditions_tested": len(applicable_interactions),
            "single_conditions_registered": len(expected_single_ids),
            "single_conditions_support_eligible": sum(
                bool(item.get("support_eligible")) for item in singles
            ),
            "single_conditions_tested": len(expected_single_ids),
        }
        if dict(summary) != expected_summary:
            errors.append(f"{session_code}:SUMMARY_RECONCILIATION_FAILED")

        selected = _sequence(session.get("provisional_candidates"))
        maximum = int(
            _mapping(frozen_manifest.get("candidate_policy")).get(
                "maximum_per_session",
                0,
            )
        )
        if len(selected) > maximum:
            errors.append(f"{session_code}:CANDIDATE_MAXIMUM_EXCEEDED")
        all_records = [*_mappings(singles), *_mappings(interactions_result)]
        passing = [item for item in all_records if item.get("candidate_gate_pass")]
        expected_selected = sorted(passing, key=candidate_rank_key)[:maximum]
        selected_condition_ids = [
            str(item.get("condition_id")) for item in selected
        ]
        if selected_condition_ids != [
            str(item.get("condition_id")) for item in expected_selected
        ]:
            errors.append(f"{session_code}:CANDIDATE_RANKING_MISMATCH")
        if int(session.get("candidate_gate_pass_count", -1)) != len(passing):
            errors.append(f"{session_code}:CANDIDATE_GATE_COUNT_MISMATCH")

        advanced_codes = {
            str(item.get("provisional_candidate_code"))
            for item in all_records
            if item.get("advanced_as_provisional_candidate") is True
        }
        selected_codes: set[str] = set()
        for rank, candidate in enumerate(selected, start=1):
            item = _mapping(candidate)
            code = str(item.get("candidate_code"))
            selected_codes.add(code)
            if item.get("provisional_rank") != rank:
                errors.append(f"{session_code}:CANDIDATE_RANK_NOT_SEQUENTIAL")
            if (
                item.get("status")
                != "PROVISIONAL_M4_CANDIDATE_NO_VALIDATION_CREDIT"
            ):
                errors.append(f"{session_code}:CANDIDATE_STATUS_INVALID")
            matching = [
                record
                for record in all_records
                if record.get("condition_id") == item.get("condition_id")
            ]
            if (
                len(matching) != 1
                or matching[0].get("candidate_gate_pass") is not True
                or matching[0].get("advanced_as_provisional_candidate") is not True
                or matching[0].get("provisional_candidate_code") != code
            ):
                errors.append(f"{session_code}:CANDIDATE_RECORD_LINK_INVALID")
        if advanced_codes != selected_codes:
            errors.append(f"{session_code}:ADVANCED_CANDIDATE_SET_MISMATCH")
        if all_selected_codes.intersection(selected_codes):
            errors.append("CANDIDATE_CODE_NOT_UNIQUE")
        all_selected_codes.update(selected_codes)
        total_selected += len(selected)

    if discovery.get("provisional_candidate_count") != total_selected:
        errors.append("TOTAL_CANDIDATE_COUNT_MISMATCH")
    return sorted(set(errors))


def _validate_document_header(
    discovery: Mapping[str, Any],
    frozen_manifest: Mapping[str, Any],
    errors: list[str],
) -> None:
    supplied = str(discovery.get("discovery_hash", ""))
    calculated = canonical_hash(
        {
            key: value
            for key, value in discovery.items()
            if key != "discovery_hash"
        }
    )
    if not supplied or supplied != calculated:
        errors.append("DISCOVERY_HASH_MISMATCH")
    if dict(_mapping(discovery.get("case_counts"))) != EXPECTED_CASE_COUNTS:
        errors.append("CASE_COUNTS_NOT_EXACT")
    pre_result = _mapping(discovery.get("pre_result_manifest"))
    if (
        pre_result.get("manifest_hash") != frozen_manifest.get("manifest_hash")
        or pre_result.get("registry_fingerprint")
        != _mapping(frozen_manifest.get("implementation_freeze")).get(
            "registry_fingerprint"
        )
    ):
        errors.append("PRE_RESULT_MANIFEST_LINK_MISMATCH")
    boundary = _mapping(discovery.get("interpretation_boundary"))
    expected_boundary = {
        "calendar_2025_values_opened": False,
        "calendar_2026_values_opened": False,
        "causal_claims": False,
        "combined_session_result": False,
        "development_only": True,
        "execution_variants": 0,
        "provisional_candidates_have_validation_credit": False,
        "rejected_zn_rules_reopened": False,
        "trades_or_returns": 0,
    }
    if dict(boundary) != expected_boundary:
        errors.append("RESEARCH_BOUNDARY_VIOLATION")


def _validate_baseline(
    session_code: str,
    baseline: Mapping[str, Any],
    expected_total: int,
    errors: list[str],
) -> None:
    if baseline.get("case_count") != expected_total:
        errors.append(f"{session_code}:BASELINE_COUNT_MISMATCH")
    close = _mapping(baseline.get("close_direction"))
    counts = [
        int(_mapping(close.get(direction)).get("count", -1))
        for direction in ("DOWN", "FLAT", "UP")
    ]
    if any(value < 0 for value in counts) or sum(counts) != expected_total:
        errors.append(f"{session_code}:BASELINE_DIRECTION_COUNTS_MISMATCH")
    if _mapping(baseline.get("path_profile")).get("case_count") != expected_total:
        errors.append(f"{session_code}:BASELINE_PATH_COUNT_MISMATCH")


def _validate_coverage(
    session_code: str,
    coverage: Sequence[Any],
    features: Sequence[Any],
    expected_total: int,
    errors: list[str],
) -> None:
    expected_ids = [str(item["feature_id"]) for item in features]
    if [str(_mapping(item).get("feature_id")) for item in coverage] != expected_ids:
        errors.append(f"{session_code}:FEATURE_COVERAGE_REGISTRY_MISMATCH")
        return
    feature_map = {str(item["feature_id"]): _mapping(item) for item in features}
    for raw in coverage:
        item = _mapping(raw)
        feature_id = str(item.get("feature_id"))
        known = int(item.get("known", -1))
        unknown = int(item.get("unknown", -1))
        if (
            item.get("total") != expected_total
            or known < 0
            or unknown < 0
            or known + unknown != expected_total
        ):
            errors.append(f"{session_code}:{feature_id}:COVERAGE_COUNT_MISMATCH")
        state_counts = _mapping(item.get("state_counts"))
        if sum(int(value) for value in state_counts.values()) != expected_total:
            errors.append(f"{session_code}:{feature_id}:STATE_COUNT_MISMATCH")
        allowed_states = {
            *map(str, _sequence(feature_map[feature_id].get("states"))),
            "UNKNOWN",
        }
        if not set(map(str, state_counts)).issubset(allowed_states):
            errors.append(f"{session_code}:{feature_id}:UNDECLARED_STATE")
        if int(state_counts.get("UNKNOWN", 0)) != unknown:
            errors.append(f"{session_code}:{feature_id}:UNKNOWN_COUNT_MISMATCH")


def _validate_relationship_record(
    session_code: str,
    record: Mapping[str, Any],
    *,
    expected_stage: str,
    expected_total: int,
    errors: list[str],
) -> None:
    condition_id = str(record.get("condition_id"))
    prefix = f"{session_code}:{condition_id}"
    if record.get("stage") != expected_stage:
        errors.append(f"{prefix}:STAGE_MISMATCH")
    condition_path = _mapping(record.get("condition_path_profile"))
    complement_path = _mapping(record.get("known_complement_path_profile"))
    condition_counts = _mapping(condition_path.get("close_direction_counts"))
    complement_counts = _mapping(complement_path.get("close_direction_counts"))
    contingency = _mapping(record.get("contingency"))
    condition_up = int(contingency.get("condition_up", -1))
    condition_down = int(contingency.get("condition_down", -1))
    complement_up = int(contingency.get("complement_up", -1))
    complement_down = int(contingency.get("complement_down", -1))
    if min(condition_up, condition_down, complement_up, complement_down) < 0:
        errors.append(f"{prefix}:NEGATIVE_CONTINGENCY_COUNT")
        return
    if (
        condition_up != int(condition_counts.get("UP", 0))
        or condition_down != int(condition_counts.get("DOWN", 0))
        or complement_up != int(complement_counts.get("UP", 0))
        or complement_down != int(complement_counts.get("DOWN", 0))
    ):
        errors.append(f"{prefix}:CONTINGENCY_PATH_RECONCILIATION_FAILED")
    condition_cases = int(condition_path.get("case_count", -1))
    complement_cases = int(complement_path.get("case_count", -1))
    if condition_cases < 0 or complement_cases < 0:
        errors.append(f"{prefix}:NEGATIVE_PATH_CASE_COUNT")
    if record.get("feature_known_cases") != condition_cases + complement_cases:
        errors.append(f"{prefix}:KNOWN_CASE_COUNT_MISMATCH")
    binary_total = condition_up + condition_down + complement_up + complement_down
    if record.get("known_binary_cases") != binary_total:
        errors.append(f"{prefix}:KNOWN_BINARY_COUNT_MISMATCH")
    if int(record.get("feature_known_cases", 0)) > expected_total:
        errors.append(f"{prefix}:KNOWN_CASES_EXCEED_SESSION")
    expected_coverage = _rounded(
        100 * int(record.get("feature_known_cases", 0)) / expected_total
    )
    if not _same_number(record.get("feature_known_coverage_pct"), expected_coverage):
        errors.append(f"{prefix}:KNOWN_COVERAGE_MISMATCH")
    expected_prevalence = _rounded(
        100 * (condition_up + condition_down) / expected_total
    )
    if not _same_number(
        record.get("condition_prevalence_pct_of_all_session_cases"),
        expected_prevalence,
    ):
        errors.append(f"{prefix}:PREVALENCE_MISMATCH")

    condition_binary = condition_up + condition_down
    complement_binary = complement_up + complement_down
    expected_condition_rate = (
        _rounded(100 * condition_up / condition_binary)
        if condition_binary
        else None
    )
    expected_complement_rate = (
        _rounded(100 * complement_up / complement_binary)
        if complement_binary
        else None
    )
    rates = _mapping(record.get("up_rate_pct"))
    if not _same_number(rates.get("condition"), expected_condition_rate):
        errors.append(f"{prefix}:CONDITION_RATE_MISMATCH")
    if not _same_number(rates.get("complement"), expected_complement_rate):
        errors.append(f"{prefix}:COMPLEMENT_RATE_MISMATCH")
    expected_effect = (
        _rounded(
            100
            * (
                condition_up / condition_binary
                - complement_up / complement_binary
            )
        )
        if condition_binary and complement_binary
        else None
    )
    if not _same_number(record.get("up_rate_difference_pp"), expected_effect):
        errors.append(f"{prefix}:EFFECT_MISMATCH")

    support_eligible = record.get("support_eligible") is True
    support_failures = _sequence(record.get("support_failures"))
    p_value = _number(record.get("fisher_exact_two_sided_p_value"))
    q_value = _number(record.get("benjamini_hochberg_q_value"))
    if support_eligible == bool(support_failures):
        errors.append(f"{prefix}:SUPPORT_STATUS_FAILURE_MISMATCH")
    if support_eligible:
        if p_value is None or q_value is None:
            errors.append(f"{prefix}:ELIGIBLE_TEST_MISSING_P_OR_Q")
        elif not (0 <= p_value <= 1 and 0 <= q_value <= 1):
            errors.append(f"{prefix}:P_OR_Q_OUT_OF_RANGE")
    elif p_value is not None or q_value is not None:
        errors.append(f"{prefix}:INELIGIBLE_TEST_HAS_P_OR_Q")
    gate_failures = _sequence(record.get("candidate_gate_failures"))
    if bool(record.get("candidate_gate_pass")) == bool(gate_failures):
        errors.append(f"{prefix}:CANDIDATE_GATE_STATUS_MISMATCH")
    if record.get("advanced_as_provisional_candidate") is True and not bool(
        record.get("candidate_gate_pass")
    ):
        errors.append(f"{prefix}:INELIGIBLE_CANDIDATE_ADVANCED")


def _validate_bh_family(
    session_code: str,
    stage: str,
    records: Sequence[Any],
    errors: list[str],
) -> None:
    eligible = [
        _mapping(item)
        for item in records
        if _mapping(item).get("support_eligible") is True
    ]
    ordered = sorted(
        eligible,
        key=lambda item: (
            float(item["fisher_exact_two_sided_p_value"]),
            str(item["condition_id"]),
        ),
    )
    total = len(ordered)
    expected: dict[str, float] = {}
    running = 1.0
    for index in range(total - 1, -1, -1):
        rank = index + 1
        raw = float(ordered[index]["fisher_exact_two_sided_p_value"])
        running = min(running, raw * total / rank, 1.0)
        expected[str(ordered[index]["condition_id"])] = _rounded(running)
    for item in eligible:
        condition_id = str(item["condition_id"])
        if not _same_number(
            item.get("benjamini_hochberg_q_value"),
            expected[condition_id],
        ):
            errors.append(
                f"{session_code}:{stage}:{condition_id}:BH_Q_VALUE_MISMATCH"
            )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mappings(values: Sequence[Any]) -> list[Mapping[str, Any]]:
    return [_mapping(value) for value in values]


def _sequence(value: Any) -> list[Any]:
    return (
        list(value)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes)
        else []
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _rounded(value: float) -> float:
    return round(value, 8)


def _same_number(left: Any, right: float | None) -> bool:
    left_number = _number(left)
    if left_number is None or right is None:
        return left_number is right
    return abs(left_number - right) <= 1e-8
