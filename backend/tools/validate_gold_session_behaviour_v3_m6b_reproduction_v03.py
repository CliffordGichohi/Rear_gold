from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

import validate_gold_session_behaviour_v3_m6b as sealed
from validate_gold_session_behaviour_v3_m6b_reproduction_v02 import (
    _compare_segment,
)

VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M6B_INDEPENDENT_REPRODUCTION_V0_3_"
    "DECIMAL_SIGNATURE_FIX"
)


def _validate_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    segment_code: str,
) -> list[dict[str, Any]]:
    hash_valid = True
    feature_valid = True
    outcome_valid = True
    boundary_valid = True
    for case in cases:
        hash_valid &= (
            case["segment_code"] == segment_code
            and sealed.forward_case_hash(case) == case["case_hash"]
        )
        decision = case["decision_state"]
        sources = decision["source_records"]
        state = str(decision["feature_state"])
        if state == "UNKNOWN":
            feature_valid &= sources == []
        else:
            feature_valid &= len(sources) == 2
            if len(sources) == 2:
                change = Decimal(str(sources[1]["value"])) - Decimal(
                    str(sources[0]["value"])
                )
                expected_state = (
                    "RISING"
                    if change > 0
                    else "FALLING"
                    if change < 0
                    else "UNCHANGED"
                )
                expected_signature = sealed.canonical_hash(
                    {
                        "absolute_change": float(change),
                        "previous_record_id": sources[0]["record_id"],
                        "record_id": sources[1]["record_id"],
                    }
                )
                feature_valid &= (
                    state == expected_state
                    and decision["source_signature"] == expected_signature
                )
        outcome = case["subsequent_behaviour"]
        signed = Decimal(str(outcome["session_close"])) - Decimal(
            str(outcome["neutral_reference_open"])
        )
        sixty = Decimal(str(outcome["sixty_minute_close"])) - Decimal(
            str(outcome["neutral_reference_open"])
        )
        expected_direction = _direction(signed)
        expected_sixty = _direction(sixty)
        outcome_valid &= (
            sealed._same_number(
                float(signed),
                outcome["signed_close_displacement"],
            )
            and sealed._same_number(
                float(abs(signed)),
                outcome["absolute_close_displacement"],
            )
            and outcome["close_direction"] == expected_direction
            and outcome["sixty_minute_direction"] == expected_sixty
            and int(case["lineage"]["measurement_bar_count"]) == 239
        )
        boundary = case["research_boundary"]
        boundary_valid &= (
            boundary["trade_direction_assigned"] is False
            and boundary[
                "entry_exit_stop_target_or_size_assigned"
            ]
            is False
            and boundary["pnl_r_multiple_or_return_calculated"] is False
        )
    return [
        sealed._check(f"{segment_code}::ALL_CASE_HASHES_VALID", hash_valid),
        sealed._check(
            f"{segment_code}::FEATURE_STATES_AND_SIGNATURES_REPRODUCED",
            feature_valid,
        ),
        sealed._check(
            f"{segment_code}::NEUTRAL_OUTCOMES_REPRODUCED",
            outcome_valid,
        ),
        sealed._check(
            f"{segment_code}::NO_TRADE_OR_RETURN_FIELDS",
            boundary_valid,
        ),
    ]


def _direction(value: Decimal) -> str:
    if value > Decimal("0.01"):
        return "UP"
    if value < Decimal("-0.01"):
        return "DOWN"
    return "FLAT"


if __name__ == "__main__":
    sealed.VALIDATION_VERSION = VALIDATION_VERSION
    sealed._compare_segment = _compare_segment
    sealed._validate_cases = _validate_cases
    sealed.main()
