"""Reusable exposed-fit policies for the sealed ten-case auction population.

The module intentionally contains no file access.  Admission reads only a
compiled point-in-time plan.  Management reads only completed bars that become
available after the decision and preserves the original stop, target, and
deadline.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from gold_intel.analytics.auction_trade_placement_outcomes_v1 import (
    RISK_BUDGET_USD,
    SLIPPAGE_PRICE,
    session_deadline,
    spread,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt

RULESET = "GOLD_AUCTION_TEN_CASE_REUSABLE_OPTIMIZATION_AND_REPLAY_V1"
LOCAL_PATH_MINIMUM_R = 1.0

ADMISSION_POLICIES: tuple[str, ...] = (
    "A0_ORIGINAL",
    "A1_FRESH_TRANSFER_OR_CONTROL",
    "A2_CLEAR_LOCAL_PATH",
    "A3_FRESH_AND_CLEAR",
)

EARLY_FRACTIONS: tuple[float, ...] = (0.0, 0.25, 1.0 / 3.0, 0.50)
RUNNER_FRACTIONS: tuple[float, ...] = (0.0, 0.25, 1.0 / 3.0)

FORBIDDEN_SELECTOR_FIELDS: tuple[str, ...] = (
    "case_alias",
    "event_identity",
    "decision_at",
    "trading_date_utc",
    "mfe_r",
    "mae_r",
    "resolution",
    "net_r50",
    "net_pnl_usd",
    "outcome_category",
)


def direction_sign(direction: str) -> float:
    if direction == "LONG":
        return 1.0
    if direction == "SHORT":
        return -1.0
    raise ValueError(f"Unsupported direction: {direction}")


def local_liquidity_room_r(plan: Mapping[str, Any]) -> float | None:
    entry = float(plan["entry"])
    stop = float(plan["stop"])
    risk = abs(entry - stop)
    local = plan.get("local_m15_liquidity")
    if risk <= 0 or not isinstance(local, Mapping) or local.get("distance_price") is None:
        return None
    return float(local["distance_price"]) / risk


def admission_decision(plan: Mapping[str, Any], policy: str) -> dict[str, Any]:
    """Apply one symmetric, plan-only admission policy."""

    if policy not in ADMISSION_POLICIES:
        raise ValueError(f"Unsupported admission policy: {policy}")
    reasons: list[str] = []
    if not bool(plan.get("eligible")):
        reasons.append("ORIGINAL_PLAN_INELIGIBLE")
    if (
        policy in {"A1_FRESH_TRANSFER_OR_CONTROL", "A3_FRESH_AND_CLEAR"}
        and str(plan.get("event_class")) == "CONTINUATION_REFRESH"
    ):
        reasons.append("SAME_DIRECTION_CONTINUATION_REFRESH")
    room = local_liquidity_room_r(plan)
    if policy in {"A2_CLEAR_LOCAL_PATH", "A3_FRESH_AND_CLEAR"}:
        if room is None:
            reasons.append("LOCAL_M15_LIQUIDITY_ROOM_UNKNOWN")
        elif room < LOCAL_PATH_MINIMUM_R:
            reasons.append("LOCAL_M15_LIQUIDITY_ROOM_BELOW_1R")
    payload: dict[str, Any] = {
        "policy": policy,
        "admitted": not reasons,
        "reasons": reasons,
        "event_class": str(plan.get("event_class")),
        "local_m15_liquidity_room_r": room,
    }
    payload["decision_sha256"] = canonical_hash(payload)
    return payload


def _fraction_label(value: float) -> str:
    if abs(value) <= 1e-12:
        return "0"
    if abs(value - 0.25) <= 1e-12:
        return "25"
    if abs(value - (1.0 / 3.0)) <= 1e-12:
        return "33"
    if abs(value - 0.50) <= 1e-12:
        return "50"
    raise ValueError(f"Unregistered fraction: {value}")


def candidate_identity(admission: str, early_fraction: float, runner_fraction: float) -> str:
    return f"{admission}::E{_fraction_label(early_fraction)}::R{_fraction_label(runner_fraction)}"


def candidate_registry() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for admission in ADMISSION_POLICIES:
        for early in EARLY_FRACTIONS:
            for runner in RUNNER_FRACTIONS:
                row = {
                    "candidate_id": candidate_identity(admission, early, runner),
                    "admission_policy": admission,
                    "early_realization_fraction": early,
                    "target_runner_fraction": runner,
                    "selector_fields": (
                        []
                        if admission == "A0_ORIGINAL"
                        else ["event_class"]
                        if admission == "A1_FRESH_TRANSFER_OR_CONTROL"
                        else ["local_m15_liquidity.distance_price", "entry", "stop"]
                        if admission == "A2_CLEAR_LOCAL_PATH"
                        else ["event_class", "local_m15_liquidity.distance_price", "entry", "stop"]
                    ),
                    "direction_symmetric": True,
                }
                row["candidate_sha256"] = canonical_hash(row)
                rows.append(row)
    if len(rows) != 48:
        raise RuntimeError("Frozen candidate registry must contain 48 policies")
    return rows


def _allocate_fraction(quantity: int, fraction: float) -> int:
    if fraction <= 0 or quantity < 2:
        return 0
    allocated = math.floor(quantity * fraction)
    if allocated < 1 or allocated >= quantity:
        return 0
    return allocated


def _adverse_exit_at_open(row: Mapping[str, Any], direction: str) -> tuple[float, float]:
    raw = float(row["open"])
    half_spread = spread(dict(row)) / 2.0
    actual = raw - half_spread - SLIPPAGE_PRICE if direction == "LONG" else raw + half_spread + SLIPPAGE_PRICE
    return raw, actual


def _adverse_exit_at_close(row: Mapping[str, Any], direction: str) -> tuple[float, float]:
    raw = float(row["close"])
    half_spread = spread(dict(row)) / 2.0
    actual = raw - half_spread - SLIPPAGE_PRICE if direction == "LONG" else raw + half_spread + SLIPPAGE_PRICE
    return raw, actual


def _partial_checkpoint(
    *,
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    m1_rows: Sequence[Mapping[str, Any]],
    m5_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    direction = str(plan["direction"])
    sign = direction_sign(direction)
    fill_at = parse_dt(str(execution["fill_at"]))
    baseline_exit_at = parse_dt(str(execution["exit_at"]))
    fill = float(execution["actual_fill"])
    stop = float(plan["stop"])
    activation_level = fill + sign * abs(fill - stop)
    activations = sorted(
        (
            row
            for row in m5_rows
            if row.get("complete") is True
            and fill_at < parse_dt(str(row["available_at"])) < baseline_exit_at
            and sign * (float(row["close"]) - activation_level) >= 0
        ),
        key=lambda row: parse_dt(str(row["available_at"])),
    )
    if not activations:
        return None
    known_at = parse_dt(str(activations[0]["available_at"]))
    execution_rows = sorted(
        (
            row
            for row in m1_rows
            if row.get("complete") is True
            and known_at <= parse_dt(str(row["open_at"])) < baseline_exit_at
        ),
        key=lambda row: parse_dt(str(row["open_at"])),
    )
    if not execution_rows:
        return None
    row = execution_rows[0]
    raw, actual = _adverse_exit_at_open(row, direction)
    return {
        "known_at": str(activations[0]["available_at"]),
        "executed_at": str(row["open_at"]),
        "activation_level": activation_level,
        "raw_exit": raw,
        "actual_exit": actual,
    }


def _runner_exit(
    *,
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    m1_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    direction = str(plan["direction"])
    target = float(plan["target"]["level"])
    start = parse_dt(str(execution["exit_at"]))
    deadline = session_deadline(str(plan["decision_at"]))
    path = sorted(
        (
            row
            for row in m1_rows
            if row.get("complete") is True
            and start <= parse_dt(str(row["open_at"])) < deadline
            and parse_dt(str(row["available_at"])) <= deadline
        ),
        key=lambda row: parse_dt(str(row["open_at"])),
    )
    if not path:
        return {
            "resolution": "TARGET_FLOOR_NO_POST_TARGET_BAR",
            "exit_at": str(execution["exit_at"]),
            "raw_exit": target,
            "actual_exit": target,
            "bars": 0,
        }
    for index, row in enumerate(path):
        touched = float(row["low"]) <= target if direction == "LONG" else float(row["high"]) >= target
        if not touched:
            continue
        raw_open = float(row["open"])
        raw = min(target, raw_open) if direction == "LONG" else max(target, raw_open)
        half_spread = spread(dict(row)) / 2.0
        actual = raw - half_spread - SLIPPAGE_PRICE if direction == "LONG" else raw + half_spread + SLIPPAGE_PRICE
        return {
            "resolution": "TARGET_FLOOR_RETURN",
            "exit_at": str(row["open_at"]),
            "raw_exit": raw,
            "actual_exit": actual,
            "bars": index + 1,
        }
    row = path[-1]
    raw, actual = _adverse_exit_at_close(row, direction)
    return {
        "resolution": "UNCHANGED_DEADLINE",
        "exit_at": str(row["close_at"]),
        "raw_exit": raw,
        "actual_exit": actual,
        "bars": len(path),
    }


def managed_execution(
    *,
    plan: Mapping[str, Any],
    baseline_result: Mapping[str, Any],
    m1_rows: Sequence[Mapping[str, Any]],
    m5_rows: Sequence[Mapping[str, Any]],
    early_fraction: float,
    runner_fraction: float,
) -> dict[str, Any]:
    """Apply a frozen management candidate without changing direction or geometry."""

    if early_fraction not in EARLY_FRACTIONS or runner_fraction not in RUNNER_FRACTIONS:
        raise ValueError("Management fraction is outside the frozen registry")
    execution = baseline_result["execution"]
    direction = str(plan["direction"])
    sign = direction_sign(direction)
    fill = float(execution["actual_fill"])
    quantity = int(execution["quantity_ounces"])
    remaining = quantity
    legs: list[dict[str, Any]] = []
    partial = None
    early_quantity = _allocate_fraction(quantity, early_fraction)
    if early_quantity:
        partial = _partial_checkpoint(plan=plan, execution=execution, m1_rows=m1_rows, m5_rows=m5_rows)
        if partial is not None:
            pnl = sign * (float(partial["actual_exit"]) - fill) * early_quantity
            legs.append({"kind": "M5_PLUS_1R_PARTIAL", "quantity": early_quantity, "pnl_usd": pnl, **partial})
            remaining -= early_quantity

    runner = None
    runner_quantity = 0
    baseline_resolution = str(execution["resolution"])
    if baseline_resolution == "TARGET_HIT":
        runner_quantity = _allocate_fraction(remaining, runner_fraction)
        target_quantity = remaining - runner_quantity
        target = float(plan["target"]["level"])
        if target_quantity:
            pnl = sign * (target - fill) * target_quantity
            legs.append(
                {
                    "kind": "ORIGINAL_LIQUIDITY_TARGET",
                    "quantity": target_quantity,
                    "exit_at": str(execution["exit_at"]),
                    "raw_exit": target,
                    "actual_exit": target,
                    "pnl_usd": pnl,
                }
            )
        if runner_quantity:
            runner = _runner_exit(plan=plan, execution=execution, m1_rows=m1_rows)
            pnl = sign * (float(runner["actual_exit"]) - fill) * runner_quantity
            legs.append({"kind": "POST_TARGET_RUNNER", "quantity": runner_quantity, "pnl_usd": pnl, **runner})
    else:
        pnl = sign * (float(execution["actual_exit"]) - fill) * remaining
        legs.append(
            {
                "kind": "ORIGINAL_STOP_OR_TIME_EXIT",
                "quantity": remaining,
                "exit_at": str(execution["exit_at"]),
                "raw_exit": float(execution["raw_exit"]),
                "actual_exit": float(execution["actual_exit"]),
                "pnl_usd": pnl,
                "resolution": baseline_resolution,
            }
        )
    if sum(int(leg["quantity"]) for leg in legs) != quantity:
        raise RuntimeError("Managed execution quantity allocation differs")
    net_pnl = sum(float(leg["pnl_usd"]) for leg in legs)
    payload: dict[str, Any] = {
        "early_realization_fraction": early_fraction,
        "target_runner_fraction": runner_fraction,
        "baseline_resolution": baseline_resolution,
        "baseline_net_r50": float(execution["net_r50"]),
        "quantity_ounces": quantity,
        "early_realization_activated": partial is not None,
        "early_realization_quantity": early_quantity if partial is not None else 0,
        "target_runner_activated": runner_quantity > 0,
        "target_runner_quantity": runner_quantity,
        "legs": legs,
        "net_pnl_usd": net_pnl,
        "net_r50": net_pnl / RISK_BUDGET_USD,
    }
    payload["management_sha256"] = canonical_hash(payload)
    return payload


def maximum_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def summarize_candidate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (parse_dt(str(row["decision_at"])), str(row["event_identity"])))
    admitted = [row for row in ordered if bool(row["admitted"])]
    values = [float(row["net_r50"]) for row in admitted]
    chronological_all = [float(row["net_r50"]) if bool(row["admitted"]) else 0.0 for row in ordered]
    positive = sum(value for value in values if value > 0)
    negative = -sum(value for value in values if value < 0)
    net = sum(values)
    leave_one_out = [net - value for value in values]
    return {
        "population": len(ordered),
        "trades": len(admitted),
        "rejected": len(ordered) - len(admitted),
        "directions": dict(sorted(Counter(str(row["direction"]) for row in admitted).items())),
        "wins": sum(value > 0 for value in values),
        "losses": sum(value < 0 for value in values),
        "scratches": sum(abs(value) <= 1e-12 for value in values),
        "win_rate": None if not values else sum(value > 0 for value in values) / len(values),
        "net_r50": net,
        "net_pnl_usd": net * RISK_BUDGET_USD,
        "expectancy_r50": None if not values else net / len(values),
        "profit_factor": math.inf if negative <= 0 and positive > 0 else (positive / negative if negative > 0 else 0.0),
        "maximum_drawdown_r50": maximum_drawdown(chronological_all),
        "minimum_leave_one_trade_out_net_r50": None if not leave_one_out else min(leave_one_out),
        "early_realization_activations": sum(bool(row.get("management", {}).get("early_realization_activated")) for row in admitted),
        "target_runner_activations": sum(bool(row.get("management", {}).get("target_runner_activated")) for row in admitted),
        "retained_baseline_winners": sum(bool(row["admitted"]) and float(row["baseline_net_r50"]) > 0 for row in ordered),
    }


def evaluate_candidate(
    *,
    plans: Sequence[Mapping[str, Any]],
    baseline_results: Sequence[Mapping[str, Any]],
    streams: Mapping[str, Mapping[str, Any]],
    specification: Mapping[str, Any],
) -> dict[str, Any]:
    result_by_identity = {str(row["event_identity"]): row for row in baseline_results}
    rows: list[dict[str, Any]] = []
    for plan in plans:
        identity = str(plan["event_identity"])
        baseline = result_by_identity[identity]
        decision = admission_decision(plan, str(specification["admission_policy"]))
        row: dict[str, Any] = {
            "event_identity": identity,
            "case_alias": str(plan["case_alias"]),
            "decision_at": str(plan["decision_at"]),
            "direction": str(plan["direction"]),
            "event_class": str(plan["event_class"]),
            "baseline_net_r50": float(baseline["execution"]["net_r50"]),
            "admitted": bool(decision["admitted"]),
            "rejection_reasons": list(decision["reasons"]),
            "admission_sha256": decision["decision_sha256"],
        }
        if decision["admitted"]:
            stream = streams[str(plan["case_alias"])]
            management = managed_execution(
                plan=plan,
                baseline_result=baseline,
                m1_rows=stream["timeframes"]["1m"],
                m5_rows=stream["timeframes"]["5m"],
                early_fraction=float(specification["early_realization_fraction"]),
                runner_fraction=float(specification["target_runner_fraction"]),
            )
            row["management"] = management
            row["net_r50"] = float(management["net_r50"])
        else:
            row["management"] = None
            row["net_r50"] = 0.0
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
    summary = summarize_candidate(rows)
    payload: dict[str, Any] = {
        "candidate_id": str(specification["candidate_id"]),
        "specification_sha256": str(specification["candidate_sha256"]),
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
        "summary": summary,
        "summary_sha256": canonical_hash(summary),
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def _neighbor_values(values: Sequence[float], selected: float) -> list[float]:
    index = list(values).index(selected)
    output: list[float] = []
    if index > 0:
        output.append(float(values[index - 1]))
    if index + 1 < len(values):
        output.append(float(values[index + 1]))
    return output


def finalize_candidate_matrix(
    matrix: Sequence[Mapping[str, Any]], specifications: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    by_id = {str(row["candidate_id"]): row for row in matrix}
    spec_by_id = {str(row["candidate_id"]): row for row in specifications}
    finalized: list[dict[str, Any]] = []
    for candidate_id in sorted(by_id):
        row = dict(by_id[candidate_id])
        spec = spec_by_id[candidate_id]
        summary = row["summary"]
        failures: list[str] = []
        if int(summary["trades"]) < 4:
            failures.append("FEWER_THAN_FOUR_TRADES")
        directions = summary["directions"]
        if int(directions.get("LONG", 0)) < 1 or int(directions.get("SHORT", 0)) < 1:
            failures.append("BOTH_DIRECTIONS_NOT_RETAINED")
        if int(summary["retained_baseline_winners"]) < 3:
            failures.append("FEWER_THAN_THREE_BASELINE_WINNERS_RETAINED")
        if float(summary["net_r50"]) <= 0:
            failures.append("NONPOSITIVE_NET_R")
        minimum_loo = summary["minimum_leave_one_trade_out_net_r50"]
        if minimum_loo is None or float(minimum_loo) <= 0:
            failures.append("NONPOSITIVE_LEAVE_ONE_TRADE_OUT_NET")
        early = float(spec["early_realization_fraction"])
        runner = float(spec["target_runner_fraction"])
        if early > 0 and int(summary["early_realization_activations"]) < 2:
            failures.append("EARLY_REALIZATION_SUPPORT_BELOW_TWO")
        if runner > 0 and int(summary["target_runner_activations"]) < 2:
            failures.append("TARGET_RUNNER_SUPPORT_BELOW_TWO")
        neighbor_ids: list[str] = []
        for neighbor in _neighbor_values(EARLY_FRACTIONS, early) if early > 0 else []:
            neighbor_ids.append(candidate_identity(str(spec["admission_policy"]), neighbor, runner))
        for neighbor in _neighbor_values(RUNNER_FRACTIONS, runner) if runner > 0 else []:
            neighbor_ids.append(candidate_identity(str(spec["admission_policy"]), early, neighbor))
        bad_neighbors = [item for item in neighbor_ids if float(by_id[item]["summary"]["net_r50"]) <= 0]
        if bad_neighbors:
            failures.append("NONPOSITIVE_REGISTERED_PARAMETER_NEIGHBOR")
        row["neighbor_candidate_ids"] = neighbor_ids
        row["selection_eligible"] = not failures
        row["selection_failures"] = failures
        row["finalized_sha256"] = canonical_hash(row)
        finalized.append(row)
    eligible = [row for row in finalized if row["selection_eligible"]]
    if not eligible:
        raise RuntimeError("No reusable exposed-fit candidate passed the frozen selection gates")

    def ranking(row: Mapping[str, Any]) -> tuple[Any, ...]:
        summary = row["summary"]
        spec = spec_by_id[str(row["candidate_id"])]
        pf = float(summary["profit_factor"])
        components = int(float(spec["early_realization_fraction"]) > 0) + int(float(spec["target_runner_fraction"]) > 0)
        return (
            -float(summary["net_r50"]),
            -pf,
            float(summary["maximum_drawdown_r50"]),
            components,
            -int(summary["trades"]),
            str(row["candidate_id"]),
        )

    selected = min(eligible, key=ranking)
    return finalized, str(selected["candidate_id"])
