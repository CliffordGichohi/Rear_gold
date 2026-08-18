from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3_discovery import FeatureObservation
from gold_intel.analytics.session_behaviour_v3_m5 import (
    apply_holm_bonferroni,
    evaluate_candidate_slice,
)
from gold_intel.analytics.session_behaviour_v3_m6a import (
    M5_SHORTLIST_CODES,
    forward_candidate_registry,
    forward_protocol,
    protocol_fingerprint,
)
from gold_intel.analytics.session_behaviour_v3_relationships import (
    DiscoveryCase,
    NeutralOutcome,
)

M6B_ENGINE_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6B_EVALUATOR_V0_1"
M6B_CASE_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6B_FORWARD_CASE_V0_1"
M6B_RESULT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6B_RESULT_V0_1"
ROUND_DECIMALS = 8

SEGMENTS = (
    {
        "segment_code": "EXPOSED_CALENDAR_2025",
        "session_date_start_inclusive": "2025-01-01",
        "session_date_end_inclusive": "2025-12-31",
        "classification": "EXPOSED_HISTORICAL_FORWARD_NO_INDEPENDENT_CREDIT",
        "positive_validation_credit": False,
    },
    {
        "segment_code": "LOCKED_2026_YTD",
        "session_date_start_inclusive": "2026-01-01",
        "session_date_end_inclusive": "2026-07-29",
        "classification": "LOCKED_INDEPENDENT_HOLDOUT",
        "positive_validation_credit": True,
    },
)


def validate_m6b_freeze() -> list[str]:
    failures: list[str] = []
    candidates = forward_candidate_registry()
    protocol = forward_protocol()
    if tuple(item["candidate_code"] for item in candidates) != M5_SHORTLIST_CODES:
        failures.append("FROZEN_CANDIDATES_CHANGED")
    if protocol_fingerprint() != (
        "308ff594d85b478b755f85397d19ed7e76faad50fa447af29f7ee8692dcd54de"
    ):
        failures.append("AMENDMENT_B_PROTOCOL_FINGERPRINT_CHANGED")
    if [item["segment_code"] for item in SEGMENTS] != [
        item["segment_code"]
        for item in protocol["segments_in_fixed_reporting_order"][:2]
    ]:
        failures.append("HISTORICAL_SEGMENT_ORDER_CHANGED")
    if any(
        item["condition_state"] != "FALLING"
        or item["complement_state"] != "RISING"
        or item["excluded_known_states"] != ["UNCHANGED"]
        for item in candidates
    ):
        failures.append("CANDIDATE_STATE_DEFINITION_CHANGED")
    return failures


def new_forward_case(
    *,
    segment_code: str,
    session_code: str,
    session_date: date,
    decision_at: datetime,
    observation_end: datetime,
    feature_id: str,
    feature_state: str,
    feature_source_signature: str,
    feature_source_records: Sequence[Mapping[str, Any]],
    neutral_reference_open: Decimal | float,
    sixty_minute_close: Decimal | float,
    session_close: Decimal | float,
    session_high: Decimal | float,
    session_high_at: datetime,
    session_low: Decimal | float,
    session_low_at: datetime,
    measurement_bar_count: int,
    measurement_bar_ids_hash: str,
    measurement_bar_payload_hash: str,
    price_batch_content_hashes: Sequence[str],
) -> dict[str, Any]:
    if segment_code not in {item["segment_code"] for item in SEGMENTS}:
        raise ValueError(f"Unsupported segment: {segment_code}")
    if session_code not in {"LONDON", "NEW_YORK"}:
        raise ValueError(f"Unsupported session: {session_code}")
    if feature_state not in {"FALLING", "RISING", "UNCHANGED", "UNKNOWN"}:
        raise ValueError(f"Unsupported feature state: {feature_state}")
    if measurement_bar_count != 239:
        raise ValueError("A forward case requires exactly 239 outcome bars")
    if decision_at.tzinfo is None or observation_end.tzinfo is None:
        raise ValueError("Forward timestamps must be timezone-aware")

    reference = Decimal(str(neutral_reference_open))
    close = Decimal(str(session_close))
    sixty_close = Decimal(str(sixty_minute_close))
    high = Decimal(str(session_high))
    low = Decimal(str(session_low))
    signed_close = close - reference
    signed_sixty = sixty_close - reference
    maximum_up = high - reference
    maximum_down = low - reference
    session_range = high - low
    if high < max(reference, close) or low > min(reference, close):
        raise ValueError("Forward case OHLC geometry is invalid")
    close_direction = _direction(signed_close)
    sixty_direction = _direction(signed_sixty)
    if session_high_at < session_low_at:
        extreme_order = "HIGH_FIRST"
    elif session_low_at < session_high_at:
        extreme_order = "LOW_FIRST"
    else:
        extreme_order = "SAME_BAR"

    case_id = f"M6B-{segment_code}-{session_code}-{session_date.isoformat()}"
    document: dict[str, Any] = {
        "case_version": M6B_CASE_VERSION,
        "case_id": case_id,
        "case_hash": "",
        "segment_code": segment_code,
        "session_code": session_code,
        "session_date": session_date.isoformat(),
        "decision_at": decision_at.isoformat(),
        "observation_end": observation_end.isoformat(),
        "decision_state": {
            "point_in_time": True,
            "feature_id": feature_id,
            "feature_state": feature_state,
            "source_signature": feature_source_signature,
            "epistemic_status": (
                "UNKNOWN" if feature_state == "UNKNOWN" else "CALCULATED"
            ),
            "quality": "MISSING" if feature_state == "UNKNOWN" else "VALID",
            "source_records": [dict(item) for item in feature_source_records],
        },
        "subsequent_behaviour": {
            "is_trade": False,
            "neutral_reference_open": float(reference),
            "sixty_minute_close": float(sixty_close),
            "session_close": float(close),
            "session_high": float(high),
            "session_high_at": session_high_at.isoformat(),
            "session_low": float(low),
            "session_low_at": session_low_at.isoformat(),
            "signed_close_displacement": float(signed_close),
            "absolute_close_displacement": float(abs(signed_close)),
            "close_direction": close_direction,
            "sixty_minute_direction": sixty_direction,
            "maximum_upward_displacement": float(maximum_up),
            "maximum_downward_displacement": float(maximum_down),
            "session_range": float(session_range),
            "extreme_order": extreme_order,
        },
        "lineage": {
            "measurement_bar_count": measurement_bar_count,
            "measurement_bar_ids_hash": measurement_bar_ids_hash,
            "measurement_bar_payload_hash": measurement_bar_payload_hash,
            "price_batch_content_hashes": sorted(set(price_batch_content_hashes)),
            "candidate_protocol_fingerprint": protocol_fingerprint(),
        },
        "research_boundary": {
            "neutral_descriptive_outcome": True,
            "trade_direction_assigned": False,
            "entry_exit_stop_target_or_size_assigned": False,
            "pnl_r_multiple_or_return_calculated": False,
        },
    }
    document["case_hash"] = forward_case_hash(document)
    return document


def forward_case_hash(document: Mapping[str, Any]) -> str:
    return canonical_hash(
        {key: value for key, value in document.items() if key != "case_hash"}
    )


def materialize_forward_case(document: Mapping[str, Any]) -> DiscoveryCase:
    if document.get("case_version") != M6B_CASE_VERSION:
        raise ValueError("Unexpected M6B forward case version")
    if forward_case_hash(document) != document.get("case_hash"):
        raise ValueError(f"Forward case hash mismatch: {document.get('case_id')}")
    feature = _mapping(document["decision_state"])
    outcome = _mapping(document["subsequent_behaviour"])
    feature_id = str(feature["feature_id"])
    return DiscoveryCase(
        case_id=str(document["case_id"]),
        record_hash=str(document["case_hash"]),
        session_code=str(document["session_code"]),
        session_date=date.fromisoformat(str(document["session_date"])),
        features={
            feature_id: FeatureObservation(
                state=str(feature["feature_state"]),
                source_signature=str(feature["source_signature"]),
                epistemic_status=str(feature["epistemic_status"]),
                quality=str(feature["quality"]),
            )
        },
        outcome=NeutralOutcome(
            close_direction=str(outcome["close_direction"]),
            signed_close_displacement=float(outcome["signed_close_displacement"]),
            absolute_close_displacement=float(
                outcome["absolute_close_displacement"]
            ),
            sixty_minute_direction=str(outcome["sixty_minute_direction"]),
            maximum_upward_displacement=float(
                outcome["maximum_upward_displacement"]
            ),
            maximum_downward_displacement_magnitude=abs(
                float(outcome["maximum_downward_displacement"])
            ),
            session_range=float(outcome["session_range"]),
            extreme_order=str(outcome["extreme_order"]),
        ),
    )


def evaluate_segment(
    case_documents: Sequence[Mapping[str, Any]],
    *,
    segment_code: str,
    source_integrity: Mapping[str, Any],
) -> dict[str, Any]:
    if validate_m6b_freeze():
        raise ValueError(f"M6B freeze invalid: {validate_m6b_freeze()}")
    segment = next(
        (item for item in SEGMENTS if item["segment_code"] == segment_code),
        None,
    )
    if segment is None:
        raise ValueError(f"Unsupported segment: {segment_code}")
    cases = [materialize_forward_case(item) for item in case_documents]
    case_documents_by_id = {
        str(item["case_id"]): item for item in case_documents
    }
    duplicate_case_keys = len(cases) - len(
        {(case.session_code, case.session_date) for case in cases}
    )
    integrity_duplicate_count = sum(
        int(source_integrity.get(key, 0))
        for key in (
            "duplicate_price_natural_keys",
            "duplicate_observation_natural_keys",
        )
    )
    protocol = forward_protocol()
    support = _mapping(protocol["support_floors_per_candidate_segment"])
    records: list[dict[str, Any]] = []
    for candidate in forward_candidate_registry():
        session_cases = sorted(
            [
                case
                for case in cases
                if case.session_code == candidate["session_code"]
            ],
            key=lambda item: (item.session_date, item.case_id),
        )
        metrics = evaluate_candidate_slice(
            session_cases,
            definition=_mapping(candidate["m5_definition"]),
            support_policy={
                "joint_known_coverage_pct_minimum": support[
                    "joint_known_feature_coverage_pct_minimum"
                ],
                "condition_binary_cases_minimum": support[
                    "condition_binary_cases_minimum"
                ],
                "complement_binary_cases_minimum": support[
                    "complement_binary_cases_minimum"
                ],
                "combined_binary_cases_minimum": support[
                    "combined_binary_cases_minimum"
                ],
                "condition_distinct_source_signatures_minimum": support[
                    "condition_distinct_source_signatures_minimum"
                ],
                "complement_distinct_source_signatures_minimum": support[
                    "complement_distinct_source_signatures_minimum"
                ],
                "condition_state_episodes_minimum": support[
                    "condition_state_episodes_minimum"
                ],
                "complement_state_episodes_minimum": support[
                    "complement_state_episodes_minimum"
                ],
            },
            include_signature_and_episode_floors=True,
        )
        duplicate_total = duplicate_case_keys + integrity_duplicate_count
        if duplicate_total > int(
            support["duplicate_source_records_or_case_keys_maximum"]
        ):
            metrics["support_failures"] = sorted(
                {
                    *metrics["support_failures"],
                    "DUPLICATE_SOURCE_RECORDS_OR_CASE_KEYS_ABOVE_MAXIMUM",
                }
            )
            metrics["support_eligible"] = False
            metrics["fisher_exact_two_sided_p_value"] = None
        metrics["duplicate_source_records_or_case_keys"] = duplicate_total
        metrics["condition_source_record_ids_hash"] = _membership_source_hash(
            session_cases,
            case_documents_by_id=case_documents_by_id,
            target_state=str(candidate["condition_state"]),
        )
        metrics["complement_source_record_ids_hash"] = _membership_source_hash(
            session_cases,
            case_documents_by_id=case_documents_by_id,
            target_state=str(candidate["complement_state"]),
        )
        records.append(
            {
                "candidate_code": candidate["candidate_code"],
                "session_code": candidate["session_code"],
                "feature_id": candidate["feature_id"],
                "source_series_code": candidate["source_series_code"],
                "condition_state": candidate["condition_state"],
                "complement_state": candidate["complement_state"],
                "excluded_known_states": candidate["excluded_known_states"],
                "full_development": metrics,
                "holm_adjusted_p_value": None,
                "segment_verdict": None,
                "verdict_reasons": [],
            }
        )

    apply_holm_bonferroni(records, family_size=2)
    for record in records:
        _apply_segment_verdict(record)
    result: dict[str, Any] = {
        "result_version": M6B_RESULT_VERSION,
        "engine_version": M6B_ENGINE_VERSION,
        "segment": dict(segment),
        "protocol_fingerprint": protocol_fingerprint(),
        "candidate_reporting_order": list(M5_SHORTLIST_CODES),
        "case_count": len(cases),
        "case_count_by_session": dict(
            sorted(Counter(case.session_code for case in cases).items())
        ),
        "case_hashes_hash": canonical_hash(
            sorted(case.record_hash for case in cases)
        ),
        "source_integrity": dict(source_integrity),
        "candidate_results": records,
        "research_boundary": {
            "candidate_count": 2,
            "both_candidates_evaluated": len(records) == 2,
            "execution_variants": 0,
            "trades_or_returns": 0,
            "cot_used_as_pass_gate": False,
            "new_variables_or_candidates": 0,
            "thresholds_retuned": False,
            "rejected_candidates_or_zn_rules_reopened": False,
        },
        "segment_hash": "",
    }
    result["segment_hash"] = embedded_hash(result, "segment_hash")
    return result


def _apply_segment_verdict(record: dict[str, Any]) -> None:
    metrics = _mapping(record["full_development"])
    if not metrics["support_eligible"]:
        record["segment_verdict"] = "INCONCLUSIVE_INSUFFICIENT_SUPPORT"
        record["verdict_reasons"] = list(metrics["support_failures"])
        return
    effect = _number(metrics.get("effect_pp"))
    interval = list(metrics["newcombe_wilson_95pct_effect_pp"])
    lower = _number(interval[0])
    upper = _number(interval[1])
    adjusted = _number(record.get("holm_adjusted_p_value"))
    condition_median = _number(
        _mapping(metrics["condition_path_profile"]).get(
            "median_signed_close_displacement"
        )
    )
    complement_median = _number(
        _mapping(metrics["complement_path_profile"]).get(
            "median_signed_close_displacement"
        )
    )
    pass_checks = {
        "EFFECT_AT_LEAST_POSITIVE_7_5_PP": effect is not None and effect >= 7.5,
        "NEWCOMBE_LOWER_BOUND_ABOVE_ZERO": lower is not None and lower > 0,
        "HOLM_ADJUSTED_P_AT_MOST_0_10": (
            adjusted is not None and adjusted <= 0.10
        ),
        "CONDITION_MEDIAN_POSITIVE": (
            condition_median is not None and condition_median > 0
        ),
        "COMPLEMENT_MEDIAN_NEGATIVE": (
            complement_median is not None and complement_median < 0
        ),
    }
    reject_checks = {
        "EFFECT_AT_MOST_NEGATIVE_7_5_PP": (
            effect is not None and effect <= -7.5
        ),
        "NEWCOMBE_UPPER_BOUND_BELOW_ZERO": upper is not None and upper < 0,
        "HOLM_ADJUSTED_P_AT_MOST_0_10": (
            adjusted is not None and adjusted <= 0.10
        ),
        "CONDITION_MEDIAN_NEGATIVE": (
            condition_median is not None and condition_median < 0
        ),
        "COMPLEMENT_MEDIAN_POSITIVE": (
            complement_median is not None and complement_median > 0
        ),
    }
    record["pass_gate_checks"] = pass_checks
    record["reject_gate_checks"] = reject_checks
    if all(pass_checks.values()):
        record["segment_verdict"] = "PASS_MATERIAL_POSITIVE_REPLICATION"
        record["verdict_reasons"] = []
    elif all(reject_checks.values()):
        record["segment_verdict"] = "REJECT_MATERIAL_REVERSE_REPLICATION"
        record["verdict_reasons"] = []
    else:
        record["segment_verdict"] = "INCONCLUSIVE_MIXED_OR_UNDERPOWERED"
        record["verdict_reasons"] = sorted(
            [
                f"PASS_GATE_FAILED::{key}"
                for key, passed in pass_checks.items()
                if not passed
            ]
            + [
                f"REJECT_GATE_FAILED::{key}"
                for key, passed in reject_checks.items()
                if not passed
            ]
        )


def overall_candidate_verdicts(
    segment_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if [item["segment"]["segment_code"] for item in segment_results] != [
        "EXPOSED_CALENDAR_2025",
        "LOCKED_2026_YTD",
    ]:
        raise ValueError("Historical segment result order changed")
    by_segment = {
        str(result["segment"]["segment_code"]): {
            str(record["candidate_code"]): record
            for record in result["candidate_results"]
        }
        for result in segment_results
    }
    output: list[dict[str, Any]] = []
    for code in M5_SHORTLIST_CODES:
        exposed = by_segment["EXPOSED_CALENDAR_2025"][code]
        locked = by_segment["LOCKED_2026_YTD"][code]
        verdicts = [
            str(exposed["segment_verdict"]),
            str(locked["segment_verdict"]),
        ]
        if "REJECT_MATERIAL_REVERSE_REPLICATION" in verdicts:
            overall = "REJECTED_MATERIAL_REVERSE_IN_HISTORICAL_FORWARD_SEGMENT"
        elif locked["segment_verdict"] == "PASS_MATERIAL_POSITIVE_REPLICATION":
            overall = "INCONCLUSIVE_PENDING_PROSPECTIVE_REPLICATION"
        else:
            overall = "INCONCLUSIVE_NO_LOCKED_2026_PASS"
        output.append(
            {
                "candidate_code": code,
                "exposed_2025_verdict": exposed["segment_verdict"],
                "exposed_2025_positive_validation_credit": False,
                "locked_2026_ytd_verdict": locked["segment_verdict"],
                "locked_2026_ytd_positive_validation_credit": True,
                "prospective_2026_verdict": "PENDING_NO_DECISIONS_YET",
                "overall_verdict": overall,
                "current_directional_bias_edge_candidate": False,
            }
        )
    return output


def stream_rows_hash(rows: Iterable[Mapping[str, Any]]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        payload = json.dumps(
            json_ready(dict(row)),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(payload)
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def embedded_hash(
    document: Mapping[str, Any],
    field: str,
    *,
    excluded: Sequence[str] = (),
) -> str:
    return canonical_hash(
        {
            key: value
            for key, value in document.items()
            if key != field and key not in set(excluded)
        }
    )


def _membership_source_hash(
    cases: Sequence[DiscoveryCase],
    *,
    case_documents_by_id: Mapping[str, Mapping[str, Any]],
    target_state: str,
) -> str:
    records: list[dict[str, Any]] = []
    for case in cases:
        feature = next(iter(case.features.values()))
        if feature.state != target_state:
            continue
        document = case_documents_by_id[case.case_id]
        decision = _mapping(document["decision_state"])
        records.extend(
            {
                "record_id": item.get("record_id"),
                "source_record_key": item.get("source_record_key"),
                "available_at": item.get("available_at"),
                "vintage": item.get("vintage"),
            }
            for item in decision["source_records"]
        )
    return canonical_hash(records)


def _direction(value: Decimal) -> str:
    if value > Decimal("0.01"):
        return "UP"
    if value < Decimal("-0.01"):
        return "DOWN"
    return "FLAT"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _rounded(value: float | None) -> float | None:
    return round(value, ROUND_DECIMALS) if value is not None else None
