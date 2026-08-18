from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import validate_gold_session_behaviour_v3_m6b as sealed

VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M6B_INDEPENDENT_REPRODUCTION_V0_2_"
    "RESULT_FIELD_MAPPING_FIX"
)


def _compare_segment(
    *,
    recorded: Mapping[str, Any],
    reproduced: Mapping[str, Any],
    segment_code: str,
) -> list[dict[str, Any]]:
    recorded_by_code = {
        item["candidate_code"]: item for item in recorded["candidate_results"]
    }
    output = []
    for item in reproduced["candidate_results"]:
        code = item["candidate_code"]
        actual = recorded_by_code[code]
        metrics = actual["full_development"]
        exact_fields = (
            "case_count",
            "joint_known_cases",
            "excluded_known_cases",
            "condition_all_cases",
            "complement_all_cases",
            "condition_distinct_source_signatures",
            "complement_distinct_source_signatures",
            "condition_state_episodes",
            "complement_state_episodes",
            "contingency",
            "support_eligible",
            "support_failures",
        )
        exact = all(metrics[field] == item[field] for field in exact_fields)
        numeric_pairs = (
            (
                metrics["joint_known_coverage_pct"],
                item["joint_known_coverage_pct"],
            ),
            (
                metrics["condition_up_rate_pct"],
                item["condition_up_rate_pct"],
            ),
            (
                metrics["complement_up_rate_pct"],
                item["complement_up_rate_pct"],
            ),
            (metrics["effect_pp"], item["effect_pp"]),
            (
                metrics["fisher_exact_two_sided_p_value"],
                item["p_value"],
            ),
        )
        numeric = all(
            sealed._same_number(left, right)
            for left, right in numeric_pairs
        )
        numeric &= all(
            sealed._same_number(left, right)
            for left, right in zip(
                metrics["newcombe_wilson_95pct_effect_pp"],
                item["interval"],
                strict=True,
            )
        )
        numeric &= sealed._same_number(
            metrics["condition_path_profile"][
                "median_signed_close_displacement"
            ],
            item["condition_median"],
        )
        numeric &= sealed._same_number(
            metrics["complement_path_profile"][
                "median_signed_close_displacement"
            ],
            item["complement_median"],
        )
        verdict = (
            sealed._same_number(
                actual["holm_adjusted_p_value"],
                item["holm_adjusted_p_value"],
            )
            and actual["segment_verdict"] == item["segment_verdict"]
        )
        output.extend(
            [
                sealed._check(
                    f"{segment_code}::{code}::"
                    "SUPPORT_AND_CONTINGENCY_REPRODUCED",
                    exact,
                ),
                sealed._check(
                    f"{segment_code}::{code}::"
                    "EFFECT_UNCERTAINTY_AND_MEDIANS_REPRODUCED",
                    numeric,
                ),
                sealed._check(
                    f"{segment_code}::{code}::"
                    "HOLM_AND_VERDICT_REPRODUCED",
                    verdict,
                ),
            ]
        )
    return output


if __name__ == "__main__":
    sealed.VALIDATION_VERSION = VALIDATION_VERSION
    sealed._compare_segment = _compare_segment
    sealed.main()
