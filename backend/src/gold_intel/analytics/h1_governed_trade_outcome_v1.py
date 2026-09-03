"""Deterministic first-passage outcomes for frozen H1-governed plans.

This module does not discover, filter, or alter plans.  It applies the frozen
entry, stop, and target geometry to completed M1 bars after each decision.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    iso,
    parse_dt,
)

RULESET = "GOLD_JANUARY_H1_GOVERNED_TRADE_OUTCOME_V1"
END_EXCLUSIVE = "2022-02-01T00:00:00Z"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _signed_move(direction: str, start: float, end: float) -> float:
    return end - start if direction == "LONG" else start - end


def evaluate_plan(
    plan: Mapping[str, Any],
    m1_rows: Sequence[Mapping[str, Any]],
    *,
    end_exclusive: str = END_EXCLUSIVE,
) -> dict[str, Any]:
    """Evaluate one frozen plan with an M1 stop-first first-passage rule."""

    direction = str(plan["direction"])
    _require(direction in {"LONG", "SHORT"}, "Unsupported direction")
    decision_at = iso(str(plan["decision_at"]))
    entry = float(plan["entry"]["level"])
    stop = float(plan["invalidation"]["level"])
    target = float(plan["destination"]["level"])
    if direction == "LONG":
        _require(stop < entry < target, "Invalid LONG geometry")
    else:
        _require(target < entry < stop, "Invalid SHORT geometry")
    risk = abs(entry - stop)
    _require(risk > 0.0, "Nonpositive frozen stop distance")
    target_r = abs(target - entry) / risk

    eligible = [
        dict(row)
        for row in m1_rows
        if row.get("complete") is True
        and parse_dt(str(row["open_at"])) >= parse_dt(decision_at)
        and parse_dt(str(row["available_at"])) <= parse_dt(end_exclusive)
    ]
    eligible.sort(
        key=lambda row: (
            parse_dt(str(row["open_at"])),
            parse_dt(str(row["available_at"])),
            str(row["bar_id"]),
        )
    )
    _require(eligible, f"No post-decision M1 path for {plan['plan_identity']}")
    _require(
        iso(str(eligible[0]["open_at"])) == decision_at,
        f"First M1 bar does not open at decision for {plan['plan_identity']}",
    )
    _require(
        len({str(row["bar_id"]) for row in eligible}) == len(eligible),
        f"Duplicate M1 bar identity for {plan['plan_identity']}",
    )

    resolution = "MONTH_END_MARK"
    resolution_row = eligible[-1]
    resolution_price = float(resolution_row["close"])
    gross_r = _signed_move(direction, entry, resolution_price) / risk
    same_bar_ambiguous = False
    bars_observed = len(eligible)

    for index, row in enumerate(eligible):
        if direction == "LONG":
            stop_hit = float(row["low"]) <= stop
            target_hit = float(row["high"]) >= target
        else:
            stop_hit = float(row["high"]) >= stop
            target_hit = float(row["low"]) <= target
        if not (stop_hit or target_hit):
            continue
        resolution_row = row
        bars_observed = index + 1
        if stop_hit:
            same_bar_ambiguous = target_hit
            resolution = "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP"
            resolution_price = stop
            gross_r = -1.0
        else:
            resolution = "TARGET"
            resolution_price = target
            gross_r = target_r
        break

    duration_minutes = int(
        (
            parse_dt(str(resolution_row["available_at"]))
            - parse_dt(decision_at)
        ).total_seconds()
        // 60
    )
    _require(duration_minutes >= 1, "Outcome duration is not positive")
    payload: dict[str, Any] = {
        "ruleset": RULESET,
        "plan_identity": str(plan["plan_identity"]),
        "sample_id": str(plan["sample_id"]),
        "decision_at": decision_at,
        "direction": direction,
        "family": str(plan["family"]),
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_price": risk,
        "target_r": target_r,
        "disposition": resolution,
        "gross_r": gross_r,
        "resolution_price": resolution_price,
        "resolution_bar_open_at": iso(str(resolution_row["open_at"])),
        "resolution_known_at": iso(str(resolution_row["available_at"])),
        "resolution_bar_id": str(resolution_row["bar_id"]),
        "bars_observed": bars_observed,
        "duration_minutes": duration_minutes,
        "same_bar_ambiguous": same_bar_ambiguous,
        "period_end_exclusive": iso(end_exclusive),
        "execution_scope": "GROSS_GEOMETRIC_PLAN_OUTCOME_NO_COSTS_NO_OVERLAP",
    }
    payload["outcome_sha256"] = canonical_hash(payload)
    return payload


def evaluate_plans(
    plans: Sequence[Mapping[str, Any]],
    m1_rows: Sequence[Mapping[str, Any]],
    *,
    end_exclusive: str = END_EXCLUSIVE,
) -> list[dict[str, Any]]:
    """Evaluate a frozen population without filtering or reordering it."""

    _require(plans, "Frozen plan population is empty")
    identities = [str(plan["plan_identity"]) for plan in plans]
    _require(len(set(identities)) == len(identities), "Duplicate plan identity")
    outcomes = [
        evaluate_plan(plan, m1_rows, end_exclusive=end_exclusive) for plan in plans
    ]
    _require(
        [item["plan_identity"] for item in outcomes] == identities,
        "Outcome order differs from frozen plan order",
    )
    return outcomes
