"""Deterministic bidirectional scanner for coherent gold auction plans."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from gold_intel.analytics.auction_plan_compiler_v1_semantic_amendment_a import (
    compile_auction_plan_v1_semantic_amendment_a,
    plan_integrity_violations,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
    structural_breaks,
)

RULESET = "gold-autonomous-coherent-auction-detector-v1"
Direction = Literal["LONG", "SHORT"]
CompileFunction = Callable[..., dict[str, Any]]


def _candidate_times(
    stream: dict[str, Any],
    *,
    maximum: str | None = None,
    implementation: Literal["primary", "reference"] = "primary",
) -> list[str]:
    start = parse_dt(stream["start_inclusive"])
    end = parse_dt(stream["end_exclusive"])
    cutoff = min(end, parse_dt(maximum)) if maximum is not None else end
    timeframe_order = (("15m", "M15"), ("5m", "M5"))
    direction_order: tuple[Direction, ...] = ("LONG", "SHORT")
    if implementation == "reference":
        timeframe_order = tuple(reversed(timeframe_order))
        direction_order = tuple(reversed(direction_order))
    values: set[str] = set()
    for key, label in timeframe_order:
        for direction in direction_order:
            for event in structural_breaks(
                stream["timeframes"][key], iso(cutoff), label, direction
            ):
                event_at = parse_dt(event["break_at"])
                if start < event_at < end and event_at <= cutoff:
                    values.add(iso(event_at))
    return sorted(values, key=parse_dt)


def _entry_reference(stream: dict[str, Any], checkpoint: str) -> float | None:
    rows = complete_rows(stream["timeframes"]["1m"], checkpoint)
    return float(rows[-1]["close"]) if rows else None


def _qualifies(plan: dict[str, Any], checkpoint: str) -> tuple[bool, list[str]]:
    violations = plan_integrity_violations(plan)
    if plan.get("disposition") != "EXECUTABLE_PLAN":
        return False, violations
    trigger = plan["components"]["local_trigger"]
    anchor = trigger.get("execution_anchor") if isinstance(trigger, dict) else None
    if not isinstance(anchor, dict) or iso(anchor.get("break_at")) != iso(checkpoint):
        return False, [*violations, "EXECUTION_ANCHOR_NOT_CURRENT_CHECKPOINT"]
    return not violations, violations


def _detect_core(
    stream: dict[str, Any],
    *,
    maximum: str | None,
    implementation: Literal["primary", "reference"],
    compiler: CompileFunction,
) -> dict[str, Any]:
    candidates = _candidate_times(
        stream, maximum=maximum, implementation=implementation
    )
    direction_order: tuple[Direction, ...] = (
        ("LONG", "SHORT") if implementation == "primary" else ("SHORT", "LONG")
    )
    evaluated: list[dict[str, Any]] = []
    ambiguous_count = 0
    for checkpoint in candidates:
        entry = _entry_reference(stream, checkpoint)
        if entry is None:
            evaluated.append(
                {
                    "checkpoint_at": checkpoint,
                    "disposition": "NO_M1_ENTRY_REFERENCE",
                    "qualified_directions": [],
                    "plan_hashes": {},
                }
            )
            continue
        plans: dict[str, dict[str, Any]] = {}
        qualifications: dict[str, bool] = {}
        integrity: dict[str, list[str]] = {}
        for direction in direction_order:
            plan = compiler(
                stream=stream,
                decision_at=checkpoint,
                direction=direction,
                entry_reference=entry,
            )
            plans[direction] = plan
            qualifications[direction], integrity[direction] = _qualifies(plan, checkpoint)
        qualified = sorted(
            direction for direction, value in qualifications.items() if value
        )
        audit = {
            "checkpoint_at": checkpoint,
            "disposition": (
                "UNIQUE_PLAN"
                if len(qualified) == 1
                else "AMBIGUOUS_TWO_SIDED"
                if len(qualified) == 2
                else "NO_COMPLETE_CURRENT_PLAN"
            ),
            "qualified_directions": qualified,
            "plan_hashes": {
                direction: plans[direction]["plan_sha256"]
                for direction in sorted(plans)
            },
            "integrity": {direction: integrity[direction] for direction in sorted(integrity)},
        }
        evaluated.append(audit)
        if len(qualified) == 2:
            ambiguous_count += 1
            continue
        if len(qualified) != 1:
            continue
        direction = qualified[0]
        plan = plans[direction]
        payload = {
            "ruleset": RULESET,
            "case_alias": stream["case_alias"],
            "session_code": stream["session_code"],
            "trading_date_utc": stream["trading_date_utc"],
            "disposition": "SIGNAL",
            "signal_at": checkpoint,
            "direction": direction,
            "entry_reference": entry,
            "plan": plan,
            "candidate_checkpoint_count": len(candidates),
            "evaluated_checkpoint_count": len(evaluated),
            "ambiguous_checkpoint_count": ambiguous_count,
            "checkpoint_audit": evaluated,
            "signal_sha256": None,
        }
        payload["signal_sha256"] = canonical_hash(
            {key: value for key, value in payload.items() if key != "signal_sha256"}
        )
        return payload
    payload = {
        "ruleset": RULESET,
        "case_alias": stream["case_alias"],
        "session_code": stream["session_code"],
        "trading_date_utc": stream["trading_date_utc"],
        "disposition": "NO_SIGNAL",
        "signal_at": None,
        "direction": None,
        "entry_reference": None,
        "plan": None,
        "candidate_checkpoint_count": len(candidates),
        "evaluated_checkpoint_count": len(evaluated),
        "ambiguous_checkpoint_count": ambiguous_count,
        "checkpoint_audit": evaluated,
        "signal_sha256": None,
    }
    payload["signal_sha256"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "signal_sha256"}
    )
    return payload


def detect_autonomous_auction_signal_v1(
    stream: dict[str, Any],
    *,
    implementation: Literal["primary", "reference"] = "primary",
    verify_prefix: bool = True,
    compiler: CompileFunction = compile_auction_plan_v1_semantic_amendment_a,
) -> dict[str, Any]:
    """Return the first unique causal plan, or an explicit no-signal."""

    result = _detect_core(
        stream,
        maximum=None,
        implementation=implementation,
        compiler=compiler,
    )
    prefix_exact: bool | None = None
    if verify_prefix and result["disposition"] == "SIGNAL":
        prefix = _detect_core(
            stream,
            maximum=result["signal_at"],
            implementation=implementation,
            compiler=compiler,
        )
        prefix_exact = all(
            prefix.get(key) == result.get(key)
            for key in ("disposition", "signal_at", "direction", "entry_reference")
        ) and prefix["plan"]["plan_sha256"] == result["plan"]["plan_sha256"]
        if not prefix_exact:
            raise RuntimeError(
                f"Prefix-only signal reproduction failed: {stream['case_alias']}"
            )
    result["prefix_reproduction_exact"] = prefix_exact
    result["signal_sha256"] = None
    result["signal_sha256"] = canonical_hash(
        {key: value for key, value in result.items() if key != "signal_sha256"}
    )
    return result

