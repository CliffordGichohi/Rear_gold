from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from gold_intel.backtesting.casebook_baseline import BaselineTrade

VALIDATION_VERSION = "GOLD_CASEBOOK_CHRONOLOGICAL_VALIDATION_V0_1"
VALIDATION_SCHEMA_VERSION = "gold-casebook-chronological-validation-schema-0.1.0"
PASS_VERDICT = "PASS_CHRONOLOGICAL_VALIDATION"
REJECT_VERDICT = "REJECT_CHRONOLOGICAL_VALIDATION"


def apply_cost_multiplier(
    trade: BaselineTrade,
    *,
    multiplier: float,
) -> BaselineTrade:
    if not math.isfinite(multiplier) or multiplier < 0:
        raise ValueError("Cost multiplier must be finite and non-negative")
    direction = 1 if trade.side == "LONG" else -1
    entry_adverse = abs(
        trade.executed_entry_price - trade.reference_entry_price
    )
    exit_adverse = abs(
        trade.executed_exit_price - trade.reference_exit_price
    )
    spread_cost = trade.spread_cost_usd * multiplier
    slippage_cost = trade.slippage_cost_usd * multiplier
    commission = trade.commission_usd * multiplier
    total_cost = spread_cost + slippage_cost + commission
    net_pnl = trade.gross_pnl_usd - total_cost
    entry_notional = trade.reference_entry_price * trade.quantity_ounces
    net_return = 10_000 * net_pnl / entry_notional if entry_notional else 0.0
    output = replace(
        trade,
        executed_entry_price=(
            trade.reference_entry_price
            + direction * entry_adverse * multiplier
        ),
        executed_exit_price=(
            trade.reference_exit_price
            - direction * exit_adverse * multiplier
        ),
        spread_cost_usd=spread_cost,
        slippage_cost_usd=slippage_cost,
        commission_usd=commission,
        total_cost_usd=total_cost,
        net_pnl_usd=net_pnl,
        net_return_basis_points=net_return,
    )
    if not math.isclose(
        output.gross_pnl_usd - output.net_pnl_usd,
        output.total_cost_usd,
        abs_tol=1e-9,
    ):
        raise AssertionError("Stressed execution cost identity failed")
    return output


def evaluate_validation_gates(
    sessions: Mapping[str, Mapping[str, Any]],
    *,
    integrity_passed: bool,
    minimum_directional_cases: int,
    minimum_state_cases: int,
    minimum_state_week_clusters: int,
) -> dict[str, Any]:
    expected_sessions = ("LONDON", "NEW_YORK")
    if set(sessions) != set(expected_sessions):
        raise ValueError("Validation gates require London and New York")

    gates = [
        _gate(
            "G01_POINT_IN_TIME_INTEGRITY",
            {"integrity_passed": integrity_passed},
            integrity_passed,
        ),
        _session_gate(
            "G02_DIRECTIONAL_SESSION_SUPPORT",
            sessions,
            lambda report: int(report["selector_metrics"]["observations"])
            >= minimum_directional_cases,
            lambda report: {
                "directional_cases": report["selector_metrics"]["observations"],
                "minimum": minimum_directional_cases,
            },
        ),
        _state_gate(
            "G03_DIRECTIONAL_STATE_SUPPORT",
            sessions,
            lambda cell: int(cell["case_count"]) >= minimum_state_cases,
            lambda cell: {
                "case_count": cell["case_count"],
                "minimum": minimum_state_cases,
            },
        ),
        _state_gate(
            "G04_STATE_WEEK_SUPPORT",
            sessions,
            lambda cell: int(cell["iso_week_cluster_count"])
            >= minimum_state_week_clusters,
            lambda cell: {
                "iso_week_cluster_count": cell["iso_week_cluster_count"],
                "minimum": minimum_state_week_clusters,
            },
        ),
        _session_gate(
            "G05_SESSION_MEAN_POSITIVE",
            sessions,
            lambda report: _positive(
                report["selector_metrics"]["mean_net_return_basis_points"]
            ),
            lambda report: {
                "mean_net_return_basis_points": report["selector_metrics"][
                    "mean_net_return_basis_points"
                ]
            },
        ),
        _session_gate(
            "G06_SESSION_PROFIT_FACTOR",
            sessions,
            lambda report: _greater_than_one(
                report["selector_metrics"]["profit_factor"]
            ),
            lambda report: {
                "profit_factor": report["selector_metrics"]["profit_factor"]
            },
        ),
        _session_gate(
            "G07_BEATS_BEST_UNCONDITIONAL_CONTROL",
            sessions,
            lambda report: _positive(
                report[
                    "selector_excess_mean_net_return_vs_best_control_bps"
                ]
            ),
            lambda report: {
                "best_control": report[
                    "best_validation_unconditional_control"
                ],
                "excess_mean_net_return_basis_points": report[
                    "selector_excess_mean_net_return_vs_best_control_bps"
                ],
            },
        ),
        _state_gate(
            "G08_DIRECTION_MAPPING_CONSISTENCY",
            sessions,
            lambda cell: _positive(
                cell["metrics"]["mean_net_return_basis_points"]
            ),
            lambda cell: {
                "mean_net_return_basis_points": cell["metrics"][
                    "mean_net_return_basis_points"
                ]
            },
        ),
        _half_gate(sessions),
        _session_gate(
            "G10_COST_STRESS",
            sessions,
            lambda report: _positive(
                report["cost_stress_1_5x"]["mean_net_pnl_usd_per_ounce"]
            ),
            lambda report: {
                "mean_net_pnl_usd_per_ounce": report[
                    "cost_stress_1_5x"
                ]["mean_net_pnl_usd_per_ounce"]
            },
        ),
    ]
    failed = [
        str(gate["gate_id"]) for gate in gates if not bool(gate["passed"])
    ]
    return {
        "all_gates_passed": not failed,
        "failed_gate_ids": failed,
        "gates": gates,
        "passed_gate_count": len(gates) - len(failed),
        "total_gate_count": len(gates),
        "verdict": PASS_VERDICT if not failed else REJECT_VERDICT,
    }


def _session_gate(
    gate_id: str,
    sessions: Mapping[str, Mapping[str, Any]],
    predicate: Any,
    evidence: Any,
) -> dict[str, Any]:
    details = {
        session: {
            **evidence(report),
            "passed": bool(predicate(report)),
        }
        for session, report in sorted(sessions.items())
    }
    return _gate(
        gate_id,
        details,
        all(item["passed"] for item in details.values()),
    )


def _state_gate(
    gate_id: str,
    sessions: Mapping[str, Mapping[str, Any]],
    predicate: Any,
    evidence: Any,
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for session, report in sorted(sessions.items()):
        details[session] = {}
        for state in ("POSITIVE", "NEGATIVE"):
            cell = report["directional_state_results"][state]
            details[session][state] = {
                **evidence(cell),
                "passed": bool(predicate(cell)),
            }
    passed = all(
        cell["passed"]
        for session in details.values()
        for cell in session.values()
    )
    return _gate(gate_id, details, passed)


def _half_gate(
    sessions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for session, report in sorted(sessions.items()):
        details[session] = {}
        for half in ("EARLY", "LATE"):
            mean = report["chronological_halves"][half][
                "mean_net_return_basis_points"
            ]
            details[session][half] = {
                "mean_net_return_basis_points": mean,
                "passed": _positive(mean),
            }
    passed = all(
        half["passed"]
        for session in details.values()
        for half in session.values()
    )
    return _gate("G09_CHRONOLOGICAL_HALF_STABILITY", details, passed)


def _gate(
    gate_id: str,
    evidence: Mapping[str, Any],
    passed: bool,
) -> dict[str, Any]:
    return {
        "evidence": dict(evidence),
        "gate_id": gate_id,
        "passed": bool(passed),
    }


def _positive(value: Any) -> bool:
    return value is not None and float(value) > 0


def _greater_than_one(value: Any) -> bool:
    return value is not None and float(value) > 1
