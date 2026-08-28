"""Hard-feasibility-only execution of every sealed auction transition."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from gold_intel.analytics.auction_trade_placement_examples_v1 import compile_trade_plan
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt

RULESET = "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V2"
RISK_USD = 50.0

HARD_INEXECUTABLE_REASONS = frozenset(
    {
        "M15_CONTROL_NOT_ALIGNED",
        "M5_CONTROL_NOT_ALIGNED",
        "M5_PROTECTED_PIVOT_UNRESOLVED",
        "M5_PROTECTED_PIVOT_ALREADY_CONSUMED",
        "NONPOSITIVE_STRUCTURAL_RISK",
        "NO_UNCONSUMED_H1_OR_H4_DESTINATION",
        "TARGET_NOT_BEYOND_ENTRY",
    }
)

IGNORED_FORMER_QUALITY_FILTERS = frozenset(
    {
        "DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR",
        "TARGET_ROOM_BELOW_1P5R",
    }
)

KNOWN_PLAN_REASONS = HARD_INEXECUTABLE_REASONS | IGNORED_FORMER_QUALITY_FILTERS


def classify_reasons(reasons: Sequence[str]) -> dict[str, Any]:
    values = [str(reason) for reason in reasons]
    unknown = sorted(set(values) - KNOWN_PLAN_REASONS)
    if unknown:
        raise RuntimeError(f"Unknown plan reason cannot be silently classified: {unknown}")
    hard = sorted(set(values) & HARD_INEXECUTABLE_REASONS)
    ignored = sorted(set(values) & IGNORED_FORMER_QUALITY_FILTERS)
    payload: dict[str, Any] = {
        "mechanically_executable": not hard,
        "hard_inexecutable_reasons": hard,
        "ignored_former_quality_filters": ignored,
    }
    payload["classification_sha256"] = canonical_hash(payload)
    return payload


def compile_executable_population(
    events: Sequence[Mapping[str, Any]], overlays: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Compile all events and exclude only hard execution impossibilities."""

    overlay_by_identity = {str(row["event_identity"]): row for row in overlays}
    if len(overlay_by_identity) != len(overlays):
        raise ValueError("Duplicate overlay identity")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in sorted(
        events,
        key=lambda row: (parse_dt(str(row["decision_at"])), str(row["event_identity"])),
    ):
        identity = str(event["event_identity"])
        if identity in seen:
            raise ValueError(f"Duplicate event identity: {identity}")
        if identity not in overlay_by_identity:
            raise ValueError(f"Missing overlay: {identity}")
        seen.add(identity)
        plan = compile_trade_plan(event, overlay_by_identity[identity])
        classification = classify_reasons(plan["reasons"])
        executable = bool(classification["mechanically_executable"])
        if executable:
            if plan["stop"] is None or plan["target"] is None:
                raise RuntimeError(f"Executable plan lacks stop or target: {identity}")
            if plan["risk_price"] is None or float(plan["risk_price"]) <= 0:
                raise RuntimeError(f"Executable plan lacks positive structural risk: {identity}")
            if plan["reward_price"] is None or float(plan["reward_price"]) <= 0:
                raise RuntimeError(f"Executable plan lacks positive liquidity reward: {identity}")
        row: dict[str, Any] = {
            "event_identity": identity,
            "case_alias": str(plan["case_alias"]),
            "trading_date_utc": str(plan["trading_date_utc"]),
            "decision_at": str(plan["decision_at"]),
            "session": str(plan["session"]),
            "direction": str(plan["direction"]),
            "event_class": str(plan["event_class"]),
            "context_family": str(plan["context_family"]),
            "mechanically_executable": executable,
            "disposition": "EXECUTABLE_ALL_TRANSITION" if executable else "HARD_INEXECUTABLE",
            "hard_inexecutable_reasons": classification["hard_inexecutable_reasons"],
            "ignored_former_quality_filters": classification["ignored_former_quality_filters"],
            "classification_sha256": classification["classification_sha256"],
            "plan": plan if executable else None,
            "plan_sha256": str(plan["plan_sha256"]),
        }
        row["compile_row_sha256"] = canonical_hash(row)
        output.append(row)
    return output


def execute_every_executable(
    compiled_rows: Sequence[Mapping[str, Any]],
    streams: Mapping[str, Mapping[str, Any]],
    resolver: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute every feasible signal; open positions never suppress later signals."""

    output: list[dict[str, Any]] = []
    for row in compiled_rows:
        payload = {key: value for key, value in row.items() if key != "plan"}
        if not row["mechanically_executable"]:
            payload.update(
                {
                    "execution_disposition": "NOT_EXECUTABLE_HARD_REASON",
                    "result": None,
                    "net_r50": 0.0,
                }
            )
        else:
            alias = str(row["case_alias"])
            if alias not in streams:
                raise RuntimeError(f"Missing daily stream: {alias}")
            result = resolver(dict(row["plan"]), list(streams[alias]["timeframes"]["1m"]))
            payload.update(
                {
                    "execution_disposition": "EXECUTED_UNRESTRICTED_ALL_SIGNALS",
                    "result": result,
                    "net_r50": float(result["execution"]["net_r50"]),
                }
            )
        payload["execution_row_sha256"] = canonical_hash(payload)
        output.append(payload)
    return output


def matched_nonoverlap_diagnostic(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Measure a wait-for-resolution policy without changing the primary track."""

    active_until = None
    output: list[dict[str, Any]] = []
    executed = sorted(
        (row for row in rows if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"),
        key=lambda row: (parse_dt(str(row["result"]["execution"]["fill_at"])), str(row["event_identity"])),
    )
    for row in executed:
        fill = parse_dt(str(row["result"]["execution"]["fill_at"]))
        if active_until is not None and fill < active_until:
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
            "fill_at": str(row["result"]["execution"]["fill_at"]),
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
    drawdown = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


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
        if row["execution_disposition"] != "EXECUTED_UNRESTRICTED_ALL_SIGNALS":
            continue
        execution = row["result"]["execution"]
        risk = float(execution["displayed_planned_risk_usd"])
        events.append((parse_dt(str(execution["fill_at"])), 1, risk))
        events.append((parse_dt(str(execution["exit_at"])), -1, -risk))
    events.sort(key=lambda item: (item[0], item[1]))
    positions = 0
    risk = 0.0
    maximum_positions = 0
    maximum_risk = 0.0
    for _, position_delta, risk_delta in events:
        positions += position_delta
        risk += risk_delta
        maximum_positions = max(maximum_positions, positions)
        maximum_risk = max(maximum_risk, risk)
    if positions != 0 or abs(risk) > 1e-7:
        raise RuntimeError("Concurrency sweep did not close")
    return {
        "maximum_concurrent_positions": maximum_positions,
        "maximum_concurrent_planned_risk_usd": maximum_risk,
        "maximum_concurrent_planned_risk_r50": maximum_risk / RISK_USD,
    }


def summarize(
    rows: Sequence[Mapping[str, Any]], diagnostic_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    executed = sorted(
        (row for row in rows if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"),
        key=lambda row: (parse_dt(str(row["result"]["execution"]["fill_at"])), str(row["event_identity"])),
    )
    diagnostic_executed = [
        row for row in diagnostic_rows if row["disposition"] == "EXECUTED_NONOVERLAP_DIAGNOSTIC"
    ]
    by_month: dict[str, list[float]] = defaultdict(list)
    by_direction: dict[str, list[float]] = defaultdict(list)
    by_event_class: dict[str, list[float]] = defaultdict(list)
    by_day: Counter[str] = Counter()
    for row in executed:
        value = float(row["net_r50"])
        by_month[str(row["trading_date_utc"])[:7]].append(value)
        by_direction[str(row["direction"])].append(value)
        by_event_class[str(row["event_class"])].append(value)
        by_day[str(row["trading_date_utc"])] += 1
    months = sorted({str(row["trading_date_utc"])[:7] for row in rows})
    return {
        "event_population": len(rows),
        "preoutcome_dispositions": dict(sorted(Counter(str(row["disposition"]) for row in rows).items())),
        "hard_reason_counts": dict(
            sorted(Counter(reason for row in rows for reason in row["hard_inexecutable_reasons"]).items())
        ),
        "ignored_former_quality_filter_counts": dict(
            sorted(Counter(reason for row in rows for reason in row["ignored_former_quality_filters"]).items())
        ),
        "trading_days_in_population": len({str(row["trading_date_utc"]) for row in rows}),
        "days_with_trade": len(by_day),
        "maximum_trades_one_day": max(by_day.values(), default=0),
        "average_trades_per_calendar_month": len(executed) / len(months),
        "all_executable_signals": economic_summary([float(row["net_r50"]) for row in executed]),
        "matched_nonoverlap_diagnostic": economic_summary([float(row["net_r50"]) for row in diagnostic_executed]),
        "overlap_signals_retained_by_primary": len(executed) - len(diagnostic_executed),
        "concurrency": concurrency_summary(rows),
        "by_month": {month: economic_summary(by_month.get(month, [])) for month in months},
        "by_direction": {key: economic_summary(by_direction[key]) for key in sorted(by_direction)},
        "by_event_class": {key: economic_summary(by_event_class[key]) for key in sorted(by_event_class)},
    }
