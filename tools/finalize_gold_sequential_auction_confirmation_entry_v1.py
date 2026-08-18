from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MATERIALIZATION = ARTIFACTS / "gold_sequential_auction_confirmation_entry_v1_materialization"
DEVELOPMENT = ARTIFACTS / "gold_sequential_auction_confirmation_entry_v1_development"
DEVELOPMENT_SEAL = DEVELOPMENT / "development_seal.json"
DEVELOPMENT_RESULTS = DEVELOPMENT / "development_results.json"
MATERIALIZATION_SUMMARY = MATERIALIZATION / "materialization_summary.json"
REPORT = ROOT / "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_RESEARCH_V1_FINAL.md"
FINAL_SEAL = DEVELOPMENT / "final_seal.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def write_exclusive(path: Path, value: str | dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            if isinstance(value, str):
                handle.write(value)
            else:
                json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if REPORT.exists() or FINAL_SEAL.exists():
        raise FileExistsError(REPORT if REPORT.exists() else FINAL_SEAL)
    seal = json.loads(DEVELOPMENT_SEAL.read_text(encoding="utf-8"))
    results = json.loads(DEVELOPMENT_RESULTS.read_text(encoding="utf-8"))
    materialization = json.loads(MATERIALIZATION_SUMMARY.read_text(encoding="utf-8"))
    if seal.get("status") != "REJECT_NO_DEVELOPMENT_ECONOMIC_CANDIDATE" or results.get("shortlisted_candidates"):
        raise ValueError("Zero-shortlist finalizer may only seal an honestly rejected development branch")
    for item in [*seal["controls"].values(), *seal["artifacts"].values()]:
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Development artifact changed: {item['path']}")
    rows = results["candidate_results"]
    supported = [row for row in rows if row["disposition"] == "REJECT"]
    positive = [row for row in rows if (row["oof_validation_union"]["net_expectancy_r"] or -999) > 0]
    closest = max(supported, key=lambda row: float(row["oof_validation_union"]["net_expectancy_r"]))
    metric = closest["oof_validation_union"]
    diagnostics = materialization["materialization_diagnostics"]["diagnostics"]
    formed = (
        diagnostics.get("PRIMARY|TRACK_A_ORIGINAL_STOP|ENTRY_ELIGIBLE", 0)
        + diagnostics.get("PRIMARY|TRACK_A_ORIGINAL_STOP|NO_TRADE_GATE|ORIGINAL_TARGET_TOUCHED_BEFORE_DELAYED_ENTRY", 0)
        + diagnostics.get("PRIMARY|TRACK_A_ORIGINAL_STOP|NO_TRADE_GATE|STOP_NOT_ADVERSE_TO_DELAYED_ENTRY", 0)
        + diagnostics.get("PRIMARY|TRACK_A_ORIGINAL_STOP|NO_TRADE_GATE|TARGET_NOT_FAVOURABLE_TO_DELAYED_ENTRY", 0)
        + diagnostics.get("PRIMARY|TRACK_A_ORIGINAL_STOP|NO_TRADE_GATE|GROSS_TARGET_ROOM_BELOW_1R", 0)
        + diagnostics.get("PRIMARY|TRACK_A_ORIGINAL_STOP|NO_TRADE_GATE|WHOLE_OUNCE_RISK_INFEASIBLE", 0)
    )
    setup_count = 22_193
    report = f"""# Gold Sequential Auction-Confirmation Entry Research V1 — Final

Status: **REJECT_NO_DEVELOPMENT_ECONOMIC_CANDIDATE**

## Verdict

The sequential auction-confirmation idea did not produce a tradable development candidate under the preregistered rules. The result does **not** say that gold is random. It says that these exact completed-candle sequences, source-model assignments, unchanged targets/deadlines, two stop tracks, costs and robustness gates did not monetize the frozen pullback population.

- Frozen development setups: {setup_count:,}.
- A primary confirmation sequence formed in {formed:,} setups ({formed / setup_count:.2%}).
- Entry-eligible after Track-A gates: {diagnostics.get('PRIMARY|TRACK_A_ORIGINAL_STOP|ENTRY_ELIGIBLE', 0):,}.
- Entry-eligible after Track-B gates: {diagnostics.get('PRIMARY|TRACK_B_CONFIRMED_RETEST_STOP|ENTRY_ELIGIBLE', 0):,}.
- Formal candidates tested: 36.
- Supported but economically rejected: {len(supported)}.
- Support failures: {results['candidate_counts'].get('SUPPORT_FAIL', 0)}.
- Positive-expectancy results: {len(positive)}, all too small/unstable to satisfy support and robustness gates.
- Passing candidates: 0.

## Closest supported result

`{closest['candidate_id']}` was the least-negative supported candidate:

- OOF trades: {metric['trades']} across {metric['trading_dates']} dates and {metric['iso_weeks']} weeks.
- Win rate: {metric['win_rate']}.
- Net expectancy: {metric['net_expectancy_r']} R/trade.
- Profit factor: {metric['profit_factor']}.
- Clustered 95% interval: [{closest['bootstrap']['ci95_low']}, {closest['bootstrap']['ci95_high']}].
- 1.5x-cost expectancy: {metric['net_expectancy_r_cost_1p5x']} R/trade.
- Normalized $50-risk PnL: ${metric['normalized_pnl_usd']}.
- Whole-ounce PnL: ${metric['whole_ounce_pnl_usd']}.

It failed positive expectancy, PF, confidence, multiplicity, stressed-cost, fold-stability and neighbour-sensitivity gates.

## What the test learned

Waiting for a visible sequence reduced the population materially, but the surviving entries still did not have positive net expectancy. Track B's post-confirmation retest stop was generally worse: among supported Track-B tests, stop rates were roughly 82%–85%, compared with about 44%–62% for supported Track-A tests. The confirmation did not solve the selection problem, and tightening the stop after confirmation amplified it.

Every one of the 36 candidates failed the frozen lenient/strict neighbour requirement. No threshold was repaired, inverted or retuned after outcomes.

## Locked actions

- The GC MBO/MBP-10 incremental study was not run because the contract forbids order flow from rescuing a rejected base candidate.
- Calendar 2025 and 2026 remained locked and received no access.
- No forward robustness test was run.
- No prospective paper ledger was initialized because there is no frozen passing system.
- No data was acquired and no charge was incurred.

Complete candidate metrics, skipped reasons, MFE/MAE, stop/target diagnostics, folds, years, sessions, cost stresses and sensitivity bundles are sealed in `research_artifacts/gold_sequential_auction_confirmation_entry_v1_development/development_results.json` and the independently reproduced economic-row Parquet files.
"""
    write_exclusive(REPORT, report)
    payload = {
        "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_FINAL_SEAL_1_0",
        "status": "REJECT_NO_DEVELOPMENT_ECONOMIC_CANDIDATE",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "development_seal": record(DEVELOPMENT_SEAL), "final_report": record(REPORT),
        "result_hash": canonical_hash(results), "sequence_formed": formed, "candidate_counts": results["candidate_counts"],
        "shortlisted_candidates": [], "gc_incremental_evaluated": False,
        "gc_non_evaluation_reason": "NO_BASE_DEVELOPMENT_CANDIDATE_AND_GC_MAY_NOT_RESCUE_REJECTION",
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
        "forward_robustness_evaluated": False, "prospective_ledger_initialized": False,
        "paid_acquisition_usd": 0.0,
    }
    write_exclusive(FINAL_SEAL, payload)
    print(json.dumps({"status": payload["status"], "sequence_formed": formed, "candidate_counts": payload["candidate_counts"], "report": record(REPORT), "final_seal": record(FINAL_SEAL)}, sort_keys=True))


if __name__ == "__main__":
    main()
