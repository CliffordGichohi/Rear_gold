"""Direct direction and barrier inversion for continuation-refresh plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash

RULESET = "GOLD_CONTINUATION_REFRESH_DIRECT_INVERSION_EXPOSED_DIAGNOSTIC_V1"
INVERTED_EVENT_CLASS = "CONTINUATION_REFRESH"


def opposite(direction: str) -> str:
    if direction == "LONG":
        return "SHORT"
    if direction == "SHORT":
        return "LONG"
    raise ValueError(f"Unsupported direction: {direction}")


def invert_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if str(plan["event_class"]) != INVERTED_EVENT_CLASS:
        raise ValueError("Only continuation-refresh plans may be inverted")
    original = deepcopy(dict(plan))
    original_direction = str(original["direction"])
    original_entry = float(original["entry"])
    original_stop = float(original["stop"])
    original_target = float(original["target"]["level"])
    new_direction = opposite(original_direction)
    new_stop = original_target
    new_target = original_stop
    new_risk = abs(new_stop - original_entry)
    new_reward = abs(original_entry - new_target)
    if new_risk <= 0 or new_reward <= 0:
        raise RuntimeError(f"Invalid inverted geometry: {original['event_identity']}")
    inverted = deepcopy(original)
    inverted.update(
        {
            "ruleset": RULESET,
            "direction": new_direction,
            "stop": new_stop,
            "stop_rule": "ORIGINAL_ABSOLUTE_LIQUIDITY_TARGET_BECOMES_STOP",
            "target": {
                "identity": f"INVERTED_ORIGINAL_STOP::{original['event_identity']}",
                "level": new_target,
                "known_at": str(original["decision_at"]),
                "source_rule": "ORIGINAL_ABSOLUTE_STRUCTURAL_STOP_BECOMES_TARGET",
            },
            "target_rule": "ORIGINAL_ABSOLUTE_STRUCTURAL_STOP_BECOMES_TARGET",
            "risk_price": new_risk,
            "reward_price": new_reward,
            "planned_r": new_reward / new_risk,
            "direct_inversion": {
                "original_direction": original_direction,
                "inverted_direction": new_direction,
                "original_stop": original_stop,
                "original_target": original_target,
                "new_stop": new_stop,
                "new_target": new_target,
                "tp_became_sl": True,
                "sl_became_tp": True,
            },
        }
    )
    inverted.pop("plan_sha256", None)
    inverted["plan_sha256"] = canonical_hash(inverted)
    return inverted


def apply_inversion_population(
    compiled_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in compiled_rows:
        row = deepcopy(dict(source))
        row.pop("compile_row_sha256", None)
        source_direction = str(row["direction"])
        invert = bool(
            row["mechanically_executable"]
            and str(row["event_class"]) == INVERTED_EVENT_CLASS
        )
        if invert:
            if row["plan"] is None:
                raise RuntimeError(f"Executable inversion lacks plan: {row['event_identity']}")
            row["plan"] = invert_plan(row["plan"])
            row["direction"] = str(row["plan"]["direction"])
            row["plan_sha256"] = str(row["plan"]["plan_sha256"])
        row["source_direction"] = source_direction
        row["execution_direction"] = str(row["direction"])
        row["continuation_directly_inverted"] = invert
        row["compile_row_sha256"] = canonical_hash(row)
        output.append(row)
    return output
