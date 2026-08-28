"""Narrow noon-deadline disposition for the V2 all-transition population."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 import (
    compile_executable_population,
)
from gold_intel.analytics.auction_trade_placement_outcomes_v1 import session_deadline
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, iso, parse_dt

RULESET = "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_V2_R1"
NO_TIME_REASON = "NO_TIME_REMAINING_BEFORE_NOON_DEADLINE"


def compile_executable_population_r1(
    events: Sequence[Mapping[str, Any]], overlays: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows = compile_executable_population(events, overlays)
    output: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        row.pop("compile_row_sha256", None)
        decision = parse_dt(str(row["decision_at"]))
        deadline = session_deadline(str(row["decision_at"]))
        has_time_remaining = decision < deadline
        row["noon_deadline"] = iso(deadline)
        row["has_time_remaining_before_noon_deadline"] = has_time_remaining
        if row["mechanically_executable"] and not has_time_remaining:
            row["mechanically_executable"] = False
            row["disposition"] = "HARD_INEXECUTABLE"
            row["hard_inexecutable_reasons"] = [NO_TIME_REASON]
            row["plan"] = None
        classification = {
            "mechanically_executable": bool(row["mechanically_executable"]),
            "hard_inexecutable_reasons": list(row["hard_inexecutable_reasons"]),
            "ignored_former_quality_filters": list(row["ignored_former_quality_filters"]),
            "has_time_remaining_before_noon_deadline": has_time_remaining,
        }
        row["classification_sha256"] = canonical_hash(classification)
        row["compile_row_sha256"] = canonical_hash(row)
        output.append(row)
    return output
