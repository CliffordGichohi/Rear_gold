from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

import run_gold_trend_pullback_continuation_economic_v1_development as econ


ROOT = Path(__file__).resolve().parents[1]
FEATURES_PRIMARY = ROOT / "research_artifacts/gold_trend_pullback_continuation_edge_v1_v01/primary_features.parquet"
FEATURES_REFERENCE = ROOT / "research_artifacts/gold_trend_pullback_continuation_edge_v1_v01/reference_features.parquet"
CENSUS_PRIMARY = ROOT / "research_artifacts/gold_multitimeframe_trend_continuation_census_v1_v02/primary_pullback_cases.parquet"
CENSUS_REFERENCE = ROOT / "research_artifacts/gold_multitimeframe_trend_continuation_census_v1_v02/reference_pullback_cases.parquet"
EXECUTION_PROTOCOL = ROOT / "research_manifests/gold_trend_pullback_continuation_economic_v1_protocol.json"
EXECUTION_FREEZE = ROOT / "research_manifests/gold_trend_pullback_continuation_economic_v1_design_freeze.json"
OUTPUT = ROOT / "research_artifacts/gold_pullback_constant_execution_baseline_v1"
REPORT = ROOT / "GOLD_PULLBACK_CONSTANT_EXECUTION_BASELINE_V1.md"

TIMEFRAMES = ("M15", "H1", "H4")


def load_pullbacks(path: Path) -> dict[str, dict[str, Any]]:
    columns = [
        "pullback_id",
        "pivot_price_e8",
        "resolution",
        "actionable_at_known",
        "research_eligible",
        "decision_facts_hash",
    ]
    return {str(row["pullback_id"]): row for row in pq.read_table(path, columns=columns).to_pylist()}


def build_signals(feature_path: Path, census_path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    features = pq.read_table(feature_path).to_pylist()
    pullbacks = load_pullbacks(census_path)
    signals: list[dict[str, Any]] = []
    resolutions: dict[str, str] = {}
    for feature in features:
        pullback_id = str(feature["pullback_id"])
        pullback = pullbacks.get(pullback_id)
        if pullback is None:
            raise ValueError(f"Missing pullback: {pullback_id}")
        if not (
            feature["scale"] == "STANDARD"
            and feature["feature_available"]
            and feature["actionable_at_known"]
            and feature["research_eligible"]
            and str(feature["known_at_utc"]) < "2025-01-01T00:00:00Z"
            and pullback["actionable_at_known"]
            and pullback["research_eligible"]
            and pullback["resolution"] in {"CONTINUED", "FAILED_STRUCTURE_SWITCH"}
        ):
            continue
        timeframe = str(feature["timeframe"])
        candidate_id = f"{timeframe}|BASELINE_ALL_STANDARD_PULLBACKS"
        identity = [candidate_id, pullback_id, feature["known_at_utc"]]
        signals.append(
            {
                "signal_id": f"TPCE-BASELINE::{econ.canonical_hash(identity)[:24]}",
                "candidate_id": candidate_id,
                "candidate_rank": 0,
                "pullback_id": pullback_id,
                "timeframe": timeframe,
                "scale": "STANDARD",
                "direction": str(feature["direction"]),
                "segment_id": str(feature["segment_id"]),
                "pivot_swing_id": str(feature["pivot_swing_id"]),
                "pivot_at_utc": str(feature["pivot_at_utc"]),
                "known_at_utc": str(feature["known_at_utc"]),
                "pivot_price_e8": int(pullback["pivot_price_e8"]),
                "atr14_e8": float(feature["atr14_e8"]),
                "feature_lineage_hash": str(feature["feature_lineage_hash"]),
                "signal_lineage_hash": econ.canonical_hash(
                    [identity, feature["feature_lineage_hash"], pullback["decision_facts_hash"]]
                ),
            }
        )
        resolutions[pullback_id] = str(pullback["resolution"])
    signals.sort(key=lambda row: (row["known_at_utc"], econ.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"]))
    return signals, resolutions


def accepted(decisions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in decisions if row["portfolio_status"] == "ACCEPTED"]
    rows.sort(key=lambda row: (row["entry_at_utc"], row["trade_id"]))
    return rows


def summarize(rows: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    values = list(rows)
    metrics = econ.basic_metrics(values)
    gross_pnl = sum(
        float(row["net_pnl_usd"]) + float(row["total_cost_usd_oz"]) * int(row["ounces"])
        for row in values
    )
    total_cost = sum(float(row["total_cost_usd_oz"]) * int(row["ounces"]) for row in values)
    return {
        "metrics": metrics,
        "gross_pnl_usd": econ.rounded(gross_pnl),
        "total_cost_usd": econ.rounded(total_cost),
        "ending_balance_usd": econ.rounded(10_000.0 + float(metrics.get("net_pnl_usd") or 0.0)),
        "total_return_pct": econ.rounded(float(metrics.get("net_pnl_usd") or 0.0) / 10_000.0 * 100.0),
        "bootstrap": econ.cluster_bootstrap(values, "net_r", seed),
        "stress": {
            "cost_1p5x_expectancy_r": econ.rounded(econ.expectation(values, "net_r_cost_1p5x")),
            "cost_2x_expectancy_r": econ.rounded(econ.expectation(values, "net_r_cost_2x")),
        },
    }


def parquet_bytes(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    table = pa.Table.from_pylist(list(rows))
    pq.write_table(
        table,
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=16_384,
    )


def markdown(results: Mapping[str, Any]) -> str:
    def n(value: Any, suffix: str = "") -> str:
        if value is None:
            return "NA"
        if isinstance(value, (int, str)):
            return f"{value}{suffix}"
        return f"{float(value):.4f}{suffix}"

    lines = [
        "# Gold Pullback Constant-Execution Baseline V1",
        "",
        "Status: **COMPLETE_DEVELOPMENT_BASELINE — NOT AN EDGE**",
        "",
        "This applies the already sealed constant execution to every eligible 2021-2024 STANDARD pullback before behavioural grouping. Calendar 2025 and 2026 were not accessed.",
        "",
        "## Constant execution",
        "",
        "- Next available M1 open, maximum five-minute delay.",
        "- Stop beyond the confirmed pullback pivot by 0.15 ATR14.",
        "- Target at the nearest known, unbroken trend-side STANDARD swing.",
        "- Exit after 16 parent bars if neither stop nor target is reached; stop first on an ambiguous M1 bar.",
        "- Observed spread (or $0.30/oz fallback), plus $0.07/oz commission and $0.10/oz slippage.",
        "- $50 planned risk on a $10,000 account, whole-ounce sizing, no compounding and one open XAUUSD position.",
        "",
        "## Standalone timeframe baselines",
        "",
        "| TF | Signals | Accepted trades | Win rate | Exp. R | PF | Net PnL | Avg/month | Ending balance | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for timeframe in TIMEFRAMES:
        item = results["standalone"][timeframe]
        metrics = item["performance"]["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    timeframe,
                    str(item["signals"]),
                    str(metrics["trades"]),
                    n(metrics.get("win_rate_pct"), "%"),
                    n(metrics.get("expectancy_r")),
                    n(metrics.get("profit_factor")),
                    "$" + n(metrics.get("net_pnl_usd")),
                    "$" + n(metrics.get("average_monthly_pnl_usd")),
                    "$" + n(item["performance"]["ending_balance_usd"]),
                    n(metrics.get("max_drawdown_pct"), "%"),
                ]
            )
            + " |"
        )
    portfolio = results["non_overlapping_portfolio"]
    metrics = portfolio["performance"]["metrics"]
    lines += [
        "",
        "## Combined non-overlapping account",
        "",
        f"Signals: **{results['signal_rows']}**; accepted trades: **{metrics['trades']}**; skipped overlaps: **{portfolio['decision_counts'].get('SKIPPED_OVERLAPPING_POSITION', 0)}**.",
        "",
        "| Win rate | Expectancy | Profit factor | Gross PnL | Costs | Net PnL | Avg monthly | Total return | Ending balance | Max DD |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        "| "
        + " | ".join(
            [
                n(metrics.get("win_rate_pct"), "%"),
                n(metrics.get("expectancy_r"), "R"),
                n(metrics.get("profit_factor")),
                "$" + n(portfolio["performance"]["gross_pnl_usd"]),
                "$" + n(portfolio["performance"]["total_cost_usd"]),
                "$" + n(metrics.get("net_pnl_usd")),
                "$" + n(metrics.get("average_monthly_pnl_usd")),
                n(portfolio["performance"]["total_return_pct"], "%"),
                "$" + n(portfolio["performance"]["ending_balance_usd"]),
                n(metrics.get("max_drawdown_pct"), "%"),
            ]
        )
        + " |",
        "",
        "## Hindsight outcome attribution",
        "",
        "These rows explain the baseline; the structural outcome is not known at entry and cannot be used as a live filter.",
        "",
        "| Outcome | Trades | Win rate | Exp. R | PF | Net PnL |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for outcome in ("CONTINUED", "FAILED_STRUCTURE_SWITCH"):
        item = results["outcome_attribution"][outcome]
        outcome_metrics = item["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    outcome,
                    str(outcome_metrics["trades"]),
                    n(outcome_metrics.get("win_rate_pct"), "%"),
                    n(outcome_metrics.get("expectancy_r"), "R"),
                    n(outcome_metrics.get("profit_factor")),
                    "$" + n(outcome_metrics.get("net_pnl_usd")),
                ]
            )
            + " |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "This is the honest no-grouping control. It establishes the account result when every objective pullback is treated alike. Behavioural grouping must improve this result out of sample; otherwise it has not identified an economic edge.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    freeze = json.loads(EXECUTION_FREEZE.read_text(encoding="utf-8"))
    if econ.sha256_file(EXECUTION_PROTOCOL) != freeze["controls"]["protocol"]["sha256"]:
        raise ValueError("Sealed execution protocol changed")
    primary_signals, primary_resolutions = build_signals(FEATURES_PRIMARY, CENSUS_PRIMARY)
    reference_signals, reference_resolutions = build_signals(FEATURES_REFERENCE, CENSUS_REFERENCE)
    if primary_signals != reference_signals or primary_resolutions != reference_resolutions:
        raise ValueError("Primary/reference baseline signal population differs")
    if len(primary_signals) != 8_653:
        raise ValueError(f"Baseline population changed: {len(primary_signals)}")

    prices = econ.load_price()
    if prices.diagnostics["forward_rows_deserialized"] != 0:
        raise ValueError("Forward rows were deserialized")
    swings, broken_at = econ.load_target_registry()
    sessions = econ.load_sessions()
    primary_trades = [
        econ.simulate(signal, prices, swings, broken_at, "primary", sessions[signal["pullback_id"]])
        for signal in primary_signals
    ]
    reference_trades = [
        econ.simulate(signal, prices, swings, broken_at, "reference", sessions[signal["pullback_id"]])
        for signal in reference_signals
    ]
    primary_trades.sort(key=lambda row: (row["known_at_utc"], econ.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"]))
    reference_trades.sort(key=lambda row: (row["known_at_utc"], econ.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"]))
    if primary_trades != reference_trades:
        raise ValueError("Primary/reference constant execution differs")

    standalone: dict[str, Any] = {}
    for index, timeframe in enumerate(TIMEFRAMES):
        rows = [row for row in primary_trades if row["timeframe"] == timeframe]
        decisions = econ.portfolio_decisions(rows)
        standalone[timeframe] = {
            "signals": len(rows),
            "decision_counts": dict(sorted(Counter(row["portfolio_status"] for row in decisions).items())),
            "performance": summarize(accepted(decisions), 710_000 + index),
        }

    decisions = econ.portfolio_decisions(primary_trades)
    accepted_rows = accepted(decisions)
    outcome_attribution: dict[str, Any] = {}
    for index, outcome in enumerate(("CONTINUED", "FAILED_STRUCTURE_SWITCH")):
        selected = [row for row in accepted_rows if primary_resolutions[row["pullback_id"]] == outcome]
        outcome_attribution[outcome] = summarize(selected, 720_000 + index)

    results = {
        "version": "GOLD_PULLBACK_CONSTANT_EXECUTION_BASELINE_V1_1_0",
        "status": "COMPLETE_DEVELOPMENT_BASELINE_NOT_AN_EDGE",
        "classification": "POST_HOC_ALL_CASE_CONSTANT_EXECUTION_CONTROL",
        "development_period": ["2021-08-01", "2024-12-31"],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "execution_protocol": econ.file_record(EXECUTION_PROTOCOL),
        "input_lineage": {
            str(path.relative_to(ROOT)).replace("\\", "/"): {
                "bytes": path.stat().st_size,
                "sha256": econ.sha256_file(path),
            }
            for path in (FEATURES_PRIMARY, FEATURES_REFERENCE, CENSUS_PRIMARY, CENSUS_REFERENCE)
        },
        "signal_rows": len(primary_signals),
        "executed_before_overlap": sum(row["status"] == "EXECUTED" for row in primary_trades),
        "no_trade_reasons": dict(sorted(Counter(row["no_trade_reason"] for row in primary_trades if row["status"] != "EXECUTED").items())),
        "standalone": standalone,
        "non_overlapping_portfolio": {
            "decision_counts": dict(sorted(Counter(row["portfolio_status"] for row in decisions).items())),
            "performance": summarize(accepted_rows, 730_000),
        },
        "outcome_attribution": outcome_attribution,
        "primary_reference_exact": True,
        "price_diagnostics": prices.diagnostics,
        "limitations": [
            "This control uses every eligible pullback and no behavioural grouping.",
            "Outcome attribution is hindsight-only and is not a live filter.",
            "No compounding is used; $50 planned risk is maintained throughout.",
            "Calendar 2025 and 2026 were not accessed.",
        ],
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    primary_path = OUTPUT / "primary_trades.parquet"
    reference_path = OUTPUT / "reference_trades.parquet"
    portfolio_path = OUTPUT / "portfolio_decisions.parquet"
    parquet_bytes(primary_path, primary_trades)
    parquet_bytes(reference_path, reference_trades)
    parquet_bytes(portfolio_path, decisions)
    if econ.sha256_file(primary_path) != econ.sha256_file(reference_path):
        raise ValueError("Primary/reference Parquet bytes differ")
    results_path = OUTPUT / "results.json"
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(markdown(results), encoding="utf-8")
    seal = {
        "status": "PASS_CONSTANT_EXECUTION_BASELINE_REPRODUCTION",
        "forward_values_accessed": False,
        "artifacts": {
            str(path.relative_to(ROOT)).replace("\\", "/"): {
                "bytes": path.stat().st_size,
                "sha256": econ.sha256_file(path),
            }
            for path in (primary_path, reference_path, portfolio_path, results_path, REPORT)
        },
    }
    (OUTPUT / "final_seal.json").write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": seal["status"],
        "signals": len(primary_signals),
        "portfolio": results["non_overlapping_portfolio"],
        "forward_values_accessed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
