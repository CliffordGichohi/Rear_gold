"""Apply the frozen Fresh-and-Clear selector to every auction transition."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from gold_intel.analytics.auction_ten_case_reusable_optimization_v1 import admission_decision
from gold_intel.analytics.auction_trade_placement_examples_v1 import compile_trade_plan
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt

RULESET = "GOLD_AUCTION_FRESH_CLEAR_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V1"
SELECTOR_ID = "A3_FRESH_AND_CLEAR::E0::R0"
ADMISSION_POLICY = "A3_FRESH_AND_CLEAR"
RISK_USD = 50.0


def compile_transition_population(
    events: Sequence[Mapping[str, Any]], overlays: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Compile all events without a daily selection cap."""

    overlay_by_identity = {str(row["event_identity"]): row for row in overlays}
    if len(overlay_by_identity) != len(overlays):
        raise ValueError("Duplicate overlay identity")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in sorted(events, key=lambda row: (parse_dt(str(row["decision_at"])), str(row["event_identity"]))):
        identity = str(event["event_identity"])
        if identity in seen:
            raise ValueError(f"Duplicate event identity: {identity}")
        seen.add(identity)
        if identity not in overlay_by_identity:
            raise ValueError(f"Missing overlay: {identity}")
        plan = compile_trade_plan(event, overlay_by_identity[identity])
        if not plan["eligible"]:
            disposition = "ORIGINAL_PLAN_INELIGIBLE"
            reasons = list(plan["reasons"])
            admitted = False
            admission_hash = None
        else:
            decision = admission_decision(plan, ADMISSION_POLICY)
            admitted = bool(decision["admitted"])
            reasons = list(decision["reasons"])
            disposition = "ADMIT_FRESH_AND_CLEAR" if admitted else "SELECTOR_REJECT"
            admission_hash = decision["decision_sha256"]
        row: dict[str, Any] = {
            "event_identity": identity,
            "case_alias": str(plan["case_alias"]),
            "trading_date_utc": str(plan["trading_date_utc"]),
            "decision_at": str(plan["decision_at"]),
            "session": str(plan["session"]),
            "direction": str(plan["direction"]),
            "event_class": str(plan["event_class"]),
            "context_family": str(plan["context_family"]),
            "admitted": admitted,
            "disposition": disposition,
            "reasons": reasons,
            "admission_sha256": admission_hash,
            "plan": plan if admitted else None,
            "plan_sha256": plan["plan_sha256"],
        }
        row["compile_row_sha256"] = canonical_hash(row)
        rows.append(row)
    return rows


def execute_all_admitted(
    compiled_rows: Sequence[Mapping[str, Any]],
    streams: Mapping[str, Mapping[str, Any]],
    resolver: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute every admitted event, including simultaneous open positions."""

    output: list[dict[str, Any]] = []
    for row in compiled_rows:
        payload = {key: value for key, value in row.items() if key != "plan"}
        if not row["admitted"]:
            payload.update({"execution_disposition": "NOT_ADMITTED", "result": None, "net_r50": 0.0})
        else:
            alias = str(row["case_alias"])
            if alias not in streams:
                raise RuntimeError(f"Missing daily stream: {alias}")
            result = resolver(dict(row["plan"]), list(streams[alias]["timeframes"]["1m"]))
            payload.update(
                {
                    "execution_disposition": "EXECUTED_ALL_VALID_SIGNALS",
                    "result": result,
                    "net_r50": float(result["execution"]["net_r50"]),
                }
            )
        payload["execution_row_sha256"] = canonical_hash(payload)
        output.append(payload)
    return output


def nonoverlap_diagnostic(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Apply the old no-deferral overlap policy only as a matched diagnostic."""

    active_until = None
    output: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (parse_dt(str(item["decision_at"])), str(item["event_identity"]))):
        if row["execution_disposition"] != "EXECUTED_ALL_VALID_SIGNALS":
            continue
        decision = parse_dt(str(row["decision_at"]))
        if active_until is not None and decision < active_until:
            disposition = "OVERLAP_SKIPPED_DIAGNOSTIC_ONLY"
            net_r = 0.0
        else:
            disposition = "EXECUTED_NONOVERLAP_DIAGNOSTIC"
            net_r = float(row["net_r50"])
            active_until = parse_dt(str(row["result"]["execution"]["exit_at"]))
        payload = {
            "event_identity": str(row["event_identity"]),
            "case_alias": str(row["case_alias"]),
            "trading_date_utc": str(row["trading_date_utc"]),
            "decision_at": str(row["decision_at"]),
            "direction": str(row["direction"]),
            "disposition": disposition,
            "net_r50": net_r,
        }
        payload["diagnostic_row_sha256"] = canonical_hash(payload)
        output.append(payload)
    return output


def maximum_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    result = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        result = max(result, peak - equity)
    return result


def economic_summary(values: Sequence[float]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    positive = sum(value for value in numbers if value > 0)
    negative = -sum(value for value in numbers if value < 0)
    return {
        "trades": len(numbers),
        "wins": sum(value > 0 for value in numbers),
        "losses": sum(value < 0 for value in numbers),
        "scratches": sum(abs(value) <= 1e-12 for value in numbers),
        "win_rate": None if not numbers else sum(value > 0 for value in numbers) / len(numbers),
        "net_r50": sum(numbers),
        "net_pnl_usd": sum(numbers) * RISK_USD,
        "expectancy_r50": None if not numbers else sum(numbers) / len(numbers),
        "gross_profit_r50": positive,
        "gross_loss_r50": negative,
        "profit_factor": positive / negative if negative > 0 else None,
        "profit_factor_infinite": negative <= 0 and positive > 0,
        "maximum_drawdown_r50": maximum_drawdown(numbers),
    }


def concurrency_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    events: list[tuple[Any, int, float]] = []
    for row in rows:
        if row["execution_disposition"] != "EXECUTED_ALL_VALID_SIGNALS":
            continue
        execution = row["result"]["execution"]
        planned_risk = float(execution["displayed_planned_risk_usd"])
        events.append((parse_dt(str(execution["fill_at"])), 1, planned_risk))
        events.append((parse_dt(str(execution["exit_at"])), -1, -planned_risk))
    # Close positions before opening new ones at an identical timestamp.
    events.sort(key=lambda item: (item[0], item[1]))
    positions = 0
    planned_risk = 0.0
    max_positions = 0
    max_risk = 0.0
    for _, delta_positions, delta_risk in events:
        positions += delta_positions
        planned_risk += delta_risk
        max_positions = max(max_positions, positions)
        max_risk = max(max_risk, planned_risk)
    if positions != 0 or abs(planned_risk) > 1e-7:
        raise RuntimeError("Concurrency sweep did not close")
    return {
        "maximum_concurrent_positions": max_positions,
        "maximum_concurrent_planned_risk_usd": max_risk,
        "maximum_concurrent_planned_risk_r50": max_risk / RISK_USD,
    }


def summarize(
    rows: Sequence[Mapping[str, Any]], nonoverlap_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    executions = [row for row in rows if row["execution_disposition"] == "EXECUTED_ALL_VALID_SIGNALS"]
    executions = sorted(executions, key=lambda row: (parse_dt(str(row["decision_at"])), str(row["event_identity"])))
    all_summary = economic_summary([float(row["net_r50"]) for row in executions])
    nonoverlap_executed = [row for row in nonoverlap_rows if row["disposition"] == "EXECUTED_NONOVERLAP_DIAGNOSTIC"]
    nonoverlap_summary = economic_summary([float(row["net_r50"]) for row in nonoverlap_executed])
    by_month: dict[str, list[float]] = defaultdict(list)
    by_direction: dict[str, list[float]] = defaultdict(list)
    by_day: Counter[str] = Counter()
    for row in executions:
        by_month[str(row["trading_date_utc"])[:7]].append(float(row["net_r50"]))
        by_direction[str(row["direction"])].append(float(row["net_r50"]))
        by_day[str(row["trading_date_utc"])] += 1
    months = sorted({str(row["trading_date_utc"])[:7] for row in rows})
    return {
        "event_population": len(rows),
        "event_dispositions": dict(sorted(Counter(str(row["disposition"]) for row in rows).items())),
        "eligible_signals": len(executions),
        "trading_days_in_population": len({str(row["trading_date_utc"]) for row in rows}),
        "days_with_trade": len(by_day),
        "maximum_trades_one_day": max(by_day.values(), default=0),
        "average_trades_per_calendar_month": len(executions) / len(months),
        "all_valid_signals": all_summary,
        "nonoverlap_diagnostic": nonoverlap_summary,
        "overlap_signals_retained_by_primary": len(executions) - len(nonoverlap_executed),
        "concurrency": concurrency_summary(rows),
        "by_month": {month: economic_summary(by_month.get(month, [])) for month in months},
        "by_direction": {direction: economic_summary(by_direction[direction]) for direction in sorted(by_direction)},
    }
