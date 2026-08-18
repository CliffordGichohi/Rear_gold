from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_artifacts" / "gold_trend_pullback_continuation_economic_v1_v01"
DEVELOPMENT_SEAL = OUTPUT / "development_seal.json"
DEVELOPMENT_RESULTS = OUTPUT / "primary_development_economic_results.json"
REFERENCE_RESULTS = OUTPUT / "reference_development_economic_results.json"
TRADES = OUTPUT / "primary_development_trades.parquet"
REFERENCE_TRADES = OUTPUT / "reference_development_trades.parquet"
PORTFOLIO = OUTPUT / "primary_development_portfolio_decisions.parquet"
REFERENCE_PORTFOLIO = OUTPUT / "reference_development_portfolio_decisions.parquet"
FROZEN_CANDIDATES = OUTPUT / "frozen_development_economic_candidates.json"

COMPLETE_RESULTS = OUTPUT / "complete_development_performance.json"
FORWARD_DISPOSITION = OUTPUT / "forward_disposition.json"
LEDGER_SCHEMA = OUTPUT / "prospective_ledger_schema.json"
LEDGER = OUTPUT / "prospective_decision_ledger.jsonl"
FINAL_REPORT = ROOT / "GOLD_TREND_PULLBACK_CONTINUATION_ECONOMIC_EDGE_VALIDATION_V1_FINAL.md"
FINAL_SEAL = OUTPUT / "final_seal.json"
FINAL_STATE = OUTPUT / "state_final.json"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, payload: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    result = round(float(value), 12)
    return 0.0 if result == 0 else result


def average(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def profit_factor(values: Sequence[float]) -> float | str | None:
    positive = sum(value for value in values if value > 0)
    negative = abs(sum(value for value in values if value < 0))
    if negative:
        return rounded(positive / negative)
    return "INF" if positive else None


def maximum_consecutive_losses(values: Sequence[float]) -> int:
    current = maximum = 0
    for value in values:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    all_rows = list(rows)
    executed = sorted(
        (row for row in all_rows if row["status"] == "EXECUTED"),
        key=lambda row: (str(row["entry_at_utc"]), str(row["trade_id"])),
    )
    net = [float(row["net_r"]) for row in executed]
    gross = [float(row["gross_r"]) for row in executed]
    stress_1p5 = [float(row["net_r_cost_1p5x"]) for row in executed]
    stress_2x = [float(row["net_r_cost_2x"]) for row in executed]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    directions = {}
    for direction in ("UP", "DOWN"):
        selected = [row for row in executed if row["direction"] == direction]
        directions[direction] = {
            "trades": len(selected),
            "expectancy_r": rounded(average([float(row["net_r"]) for row in selected])),
            "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected)),
        }
    sessions = {}
    for session in ("ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP", "OTHER"):
        selected = [row for row in executed if row["session_state"] == session]
        sessions[session] = {
            "trades": len(selected),
            "expectancy_r": rounded(average([float(row["net_r"]) for row in selected])),
            "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected)),
        }
    cost_usd = [float(row["total_cost_usd_oz"]) * int(row["ounces"]) for row in executed]
    return {
        "signals": len(all_rows),
        "executed_trades": len(executed),
        "no_trades": len(all_rows) - len(executed),
        "no_trade_reasons": dict(sorted(Counter(str(row["no_trade_reason"]) for row in all_rows if row["status"] != "EXECUTED").items())),
        "trade_dates": len({str(row["cluster_date"]) for row in executed}),
        "trade_iso_weeks": len({datetime.fromisoformat(str(row["known_at_utc"]).replace("Z", "+00:00")).isocalendar()[:2] for row in executed}),
        "winners": len(wins),
        "losers": len(losses),
        "flat": len(net) - len(wins) - len(losses),
        "win_rate_pct": rounded(100 * len(wins) / len(net)) if net else None,
        "gross_expectancy_r": rounded(average(gross)),
        "baseline_net_expectancy_r": rounded(average(net)),
        "cost_1p5x_expectancy_r": rounded(average(stress_1p5)),
        "cost_2x_expectancy_r": rounded(average(stress_2x)),
        "total_gross_r": rounded(sum(gross)),
        "total_net_r": rounded(sum(net)),
        "average_win_r": rounded(average(wins)),
        "median_win_r": rounded(median(wins)),
        "average_loss_r": rounded(average(losses)),
        "median_loss_r": rounded(median(losses)),
        "baseline_profit_factor": profit_factor(net),
        "cost_1p5x_profit_factor": profit_factor(stress_1p5),
        "cost_2x_profit_factor": profit_factor(stress_2x),
        "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in executed)),
        "total_baseline_friction_usd": rounded(sum(cost_usd)),
        "average_cost_r": rounded(average([float(row["cost_r"]) for row in executed])),
        "spread_fallback_trades": sum(bool(row["spread_fallback_used"]) for row in executed),
        "average_entry_delay_minutes": rounded(average([float(row["entry_delay_minutes"]) for row in executed])),
        "median_entry_delay_minutes": rounded(median([float(row["entry_delay_minutes"]) for row in executed])),
        "maximum_entry_delay_minutes": rounded(max((float(row["entry_delay_minutes"]) for row in executed), default=math.nan)),
        "average_target_r": rounded(average([float(row["target_r"]) for row in executed])),
        "median_target_r": rounded(median([float(row["target_r"]) for row in executed])),
        "average_mfe_r": rounded(average([float(row["mfe_r"]) for row in executed])),
        "average_mae_r": rounded(average([float(row["mae_r"]) for row in executed])),
        "average_holding_minutes": rounded(average([float(row["holding_minutes"]) for row in executed])),
        "median_holding_minutes": rounded(median([float(row["holding_minutes"]) for row in executed])),
        "maximum_consecutive_losses": maximum_consecutive_losses(net),
        "exit_reasons": dict(sorted(Counter(str(row["exit_reason"]) for row in executed).items())),
        "directions": directions,
        "sessions": sessions,
    }


def verify_development() -> tuple[dict[str, Any], dict[str, Any]]:
    seal = json.loads(DEVELOPMENT_SEAL.read_text(encoding="utf-8"))
    if seal["status"] != "REJECT_NO_DEVELOPMENT_ECONOMIC_CANDIDATE":
        raise ValueError("Unexpected development verdict")
    for item in seal["artifacts"].values():
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Development seal failure: {item['path']}")
    if sha256_file(TRADES) != sha256_file(REFERENCE_TRADES):
        raise ValueError("Primary/reference trade payloads differ")
    if sha256_file(PORTFOLIO) != sha256_file(REFERENCE_PORTFOLIO):
        raise ValueError("Primary/reference portfolio payloads differ")
    if sha256_file(DEVELOPMENT_RESULTS) != sha256_file(REFERENCE_RESULTS):
        raise ValueError("Primary/reference development results differ")
    results = json.loads(DEVELOPMENT_RESULTS.read_text(encoding="utf-8"))
    frozen = json.loads(FROZEN_CANDIDATES.read_text(encoding="utf-8"))
    if results["passing_candidate_count"] != 0 or frozen["candidate_count"] != 0 or frozen["candidate_ids"]:
        raise ValueError("Forward disposition requires zero frozen candidates")
    if results["calendar_2025_values_accessed"] or results["calendar_2026_values_accessed"]:
        raise ValueError("Forward values were unexpectedly accessed")
    return seal, results


def report_text(complete: Mapping[str, Any], development: Mapping[str, Any], forward: Mapping[str, Any]) -> str:
    lines = [
        "# Gold Trend-Pullback Continuation Economic Edge Validation V1 — Final",
        "",
        "Verdict: **REJECT — no frozen candidate demonstrated a tradable economic edge.**",
        "",
        "The nine relationship candidates were preserved unchanged and tested with the precommitted entry, structural stop, known-liquidity target, time exit, costs, sizing, and overlap policy. None passed the development gates. Calendar 2025 and 2026 were therefore not opened for this branch; testing rejected rules there would violate the contract.",
        "",
        "## Standalone development results (2021–2024)",
        "",
        "| Candidate | Trades | Win rate | Net exp. | PF | Net PnL | 95% CI | Verdict |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    by_id = complete["standalone_candidates"]
    for item in development["candidates"]:
        metrics = by_id[item["candidate_id"]]
        ci = item["bootstrap"]["ci95"]
        ci_text = "NA" if ci[0] is None else f"[{ci[0]:.4f}, {ci[1]:.4f}]"
        lines.append(
            f"| {item['candidate_id']} | {metrics['executed_trades']} | {metrics['win_rate_pct']:.2f}% | "
            f"{metrics['baseline_net_expectancy_r']:.4f}R | {metrics['baseline_profit_factor']} | "
            f"${metrics['net_pnl_usd']:.2f} | {ci_text} | {item['verdict']} |"
        )
    portfolio = complete["non_overlapping_portfolio"]
    lines.extend([
        "",
        "## Non-overlapping portfolio",
        "",
        f"The fixed portfolio accepted **{portfolio['executed_trades']:,} trades**. Win rate was **{portfolio['win_rate_pct']:.2f}%**, but average win was **{portfolio['average_win_r']:.3f}R** versus an average loss of **{portfolio['average_loss_r']:.3f}R**. Net expectancy was **{portfolio['baseline_net_expectancy_r']:.4f}R per trade**, profit factor **{portfolio['baseline_profit_factor']}**, net PnL **${portfolio['net_pnl_usd']:.2f}**, and baseline friction **${portfolio['total_baseline_friction_usd']:.2f}**.",
        "",
        "This is the key economic distinction: frequent continuation was observable, but the frozen nearby-liquidity targets were too small relative to structural-stop losses and costs. A high hit rate alone was not an edge.",
        "",
        "## Closest result and negative evidence",
        "",
    ])
    closest = max(development["candidates"], key=lambda item: item["metrics"]["expectancy_r"] if item["metrics"]["expectancy_r"] is not None else -math.inf)
    lines.extend([
        f"The closest candidate was `{closest['candidate_id']}` at **{closest['metrics']['expectancy_r']:.4f}R** expectancy and **{closest['metrics']['profit_factor']}** profit factor across **{closest['metrics']['trades']} trades**. It still failed: **{', '.join(closest['failed_gates'])}**.",
        "",
        "Every candidate, no-trade reason, cost stress, annual/block/session/side diagnostic, bootstrap interval, multiplicity result, and failed gate is retained in the sealed JSON and Parquet artifacts.",
        "",
        "## Forward and prospective disposition",
        "",
        f"Forward status: **{forward['status']}**. The 2025 and 2026 values remained unopened. The prospective paper ledger was initialized with zero eligible candidates and is dormant; it authorizes no live trading and forbids backfilling.",
        "",
        "## Integrity",
        "",
        "Primary and reference paths, trades, portfolio decisions, statistics, and byte-level artifacts matched. No paid data was acquired, and no execution rule or candidate was retuned after outcomes were opened.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    outputs = (COMPLETE_RESULTS, FORWARD_DISPOSITION, LEDGER_SCHEMA, LEDGER, FINAL_REPORT, FINAL_SEAL, FINAL_STATE)
    if any(path.exists() for path in outputs):
        raise FileExistsError("Final economic-validation artifact already exists")
    development_seal, development = verify_development()
    trade_rows = pq.read_table(TRADES).to_pylist()
    portfolio_rows = pq.read_table(PORTFOLIO).to_pylist()
    standalone = {
        candidate["candidate_id"]: summarize([row for row in trade_rows if row["candidate_id"] == candidate["candidate_id"]])
        for candidate in development["candidates"]
    }
    accepted = [row for row in portfolio_rows if row["portfolio_status"] == "ACCEPTED"]
    portfolio_summary = summarize(accepted)
    portfolio_summary["portfolio_decision_counts"] = dict(sorted(Counter(str(row["portfolio_status"]) for row in portfolio_rows).items()))
    complete = {
        "version": "GOLD_TPCE_ECONOMIC_V1_COMPLETE_DEVELOPMENT_PERFORMANCE_1_0",
        "status": "REJECT_NO_ECONOMIC_EDGE_UNDER_FROZEN_EXECUTION",
        "development_period": ["2021-08-01T00:00:00Z", "2025-01-01T00:00:00Z"],
        "standalone_candidates": standalone,
        "non_overlapping_portfolio": portfolio_summary,
        "candidate_gate_results": {
            item["candidate_id"]: {
                "verdict": item["verdict"],
                "failed_gates": item["failed_gates"],
                "bootstrap": item["bootstrap"],
                "holm_p": item["holm_p"],
                "annual": item["annual"],
                "chronological_blocks": item["blocks"],
                "stress": item["stress"],
            }
            for item in development["candidates"]
        },
        "development_seal_sha256": sha256_file(DEVELOPMENT_SEAL),
        "primary_reference_exact": True,
    }
    write_json_exclusive(COMPLETE_RESULTS, complete)
    forward = {
        "version": "GOLD_TPCE_ECONOMIC_V1_FORWARD_DISPOSITION_1_0",
        "status": "NOT_OPENED_ZERO_DEVELOPMENT_CANDIDATES",
        "development_candidate_count": 0,
        "development_candidate_ids": [],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "reason": "The frozen contract permits forward opening only for development candidates passing every economic gate.",
        "forward_credit": "NONE",
        "retuning_permitted": False,
    }
    write_json_exclusive(FORWARD_DISPOSITION, forward)
    initialized = utc_now()
    schema = {
        "version": "GOLD_TPCE_ECONOMIC_V1_PROSPECTIVE_LEDGER_SCHEMA_1_0",
        "status": "DORMANT_ZERO_ELIGIBLE_CANDIDATES",
        "format": "APPEND_ONLY_JSONL",
        "initialized_at_utc": initialized,
        "do_not_backfill_before_utc": initialized,
        "eligible_candidate_ids": [],
        "paper_only": True,
        "live_trading_authorized": False,
        "record_types": {
            "GENESIS": ["record_type", "recorded_at_utc", "status", "eligible_candidate_ids", "predecessor_sha256", "record_hash"],
            "DECISION": ["record_type", "recorded_at_utc", "session", "candidate_id", "decision", "evidence_hash", "record_hash"],
        },
        "append_rule": "Never edit or delete an existing line; never backfill a missed decision.",
    }
    write_json_exclusive(LEDGER_SCHEMA, schema)
    genesis = {
        "record_type": "GENESIS",
        "recorded_at_utc": initialized,
        "status": "DORMANT_ZERO_ELIGIBLE_CANDIDATES",
        "eligible_candidate_ids": [],
        "predecessor_sha256": sha256_file(DEVELOPMENT_SEAL),
        "paper_only": True,
        "live_trading_authorized": False,
        "backfill_permitted": False,
    }
    genesis["record_hash"] = canonical_hash(genesis)
    write_text_exclusive(LEDGER, canonical_json(genesis) + "\n")
    write_text_exclusive(FINAL_REPORT, report_text(complete, development, forward))
    sealed_paths = [DEVELOPMENT_SEAL, COMPLETE_RESULTS, FORWARD_DISPOSITION, LEDGER_SCHEMA, LEDGER, FINAL_REPORT]
    final_seal = {
        "version": "GOLD_TPCE_ECONOMIC_V1_FINAL_SEAL_1_0",
        "status": "REJECT_NO_ECONOMIC_EDGE_UNDER_FROZEN_EXECUTION",
        "sealed_at_utc": utc_now(),
        "artifacts": {path.name: record(path) for path in sealed_paths},
        "artifact_set_hash": canonical_hash({path.name: sha256_file(path) for path in sealed_paths}),
        "development_candidates": [],
        "forward_values_accessed": False,
        "prospective_eligible_candidates": [],
        "primary_reference_exact": True,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FINAL_SEAL, final_seal)
    write_json_exclusive(FINAL_STATE, {
        "version": "GOLD_TPCE_ECONOMIC_V1_FINAL_STATE_1_0",
        "status": final_seal["status"],
        "recorded_at_utc": utc_now(),
        "final_seal": record(FINAL_SEAL),
        "forward_values_accessed": False,
        "prospective_ledger_status": "DORMANT_ZERO_ELIGIBLE_CANDIDATES",
        "next_step": "STOP_CONTRACT_COMPLETE",
    })
    print(json.dumps({
        "status": final_seal["status"],
        "portfolio": complete["non_overlapping_portfolio"],
        "forward": forward["status"],
        "ledger": schema["status"],
        "final_seal": record(FINAL_SEAL),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
