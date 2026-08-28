#!/usr/bin/env python3
"""Matched-trade attribution for the exposed Router V1-R1 population.

This is hypothesis-generation only.  It compares one globally selected management
policy (fixed 2R target, no protection/runner) with the sealed corrected baseline
without changing setup admission, entry, stop, risk, costs, or overlap.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import analyze_gold_exposed_management_grid_v1 as grid  # noqa: E402
import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402
from gold_intel.analytics.coherent_auction_human_policy_v2 import simulate_track  # noqa: E402


V1_RESULT = ROOT / "research_artifacts" / "gold_auction_family_router_exposed_regression_v1" / "final_result.json"
CORRECTED_RESULT = ROOT / "research_artifacts" / "gold_auction_family_router_v1_r1_mechanical_correction" / "final_result.json"
OUTPUT = ROOT / "research_artifacts" / "gold_exposed_trade_attribution_v1" / "final_result.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_path(baseline_r: float, mfe_r: float, best_r: float) -> str:
    epsilon = 1e-10
    if baseline_r <= epsilon and best_r > epsilon:
        return "PROFITABLE_EXCURSION_RECOVERED_BY_REMOVING_PROTECTION"
    if baseline_r < -epsilon and mfe_r >= 1.5 and best_r <= epsilon:
        return "HIGH_MFE_BUT_STOP_PRECEDED_2R"
    if baseline_r < -epsilon and mfe_r < 0.5:
        return "EARLY_OR_CLEAN_INVALIDATION"
    if baseline_r < -epsilon:
        return "FAILED_AFTER_PARTIAL_FAVOURABLE_MOVE"
    if abs(baseline_r) <= epsilon:
        return "SCRATCH_LOW_EXCURSION"
    if best_r > baseline_r + 0.05:
        return "WINNER_UNDER_RETAINED_BY_BASELINE"
    if best_r < baseline_r - 0.05:
        return "WINNER_TRUNCATED_BY_2R_CAP"
    return "WINNER_STABLE"


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [float(row[field]) for row in rows]
    positive = sum(value for value in values if value > 1e-12)
    negative = abs(sum(value for value in values if value < -1e-12))
    equity = peak = maximum_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    return {
        "trades": len(values),
        "wins": sum(value > 1e-12 for value in values),
        "losses": sum(value < -1e-12 for value in values),
        "scratches": sum(abs(value) <= 1e-12 for value in values),
        "net_r": sum(values),
        "r_per_month": sum(values) / 5.0,
        "profit_factor": positive / negative if negative else None,
        "maximum_drawdown_r": maximum_drawdown,
    }


def main() -> int:
    v1 = load_json(V1_RESULT)
    corrected = load_json(CORRECTED_RESULT)
    v1_by_alias = {str(row["case_alias"]): row for row in v1["rows"]}
    admitted = [
        row for row in corrected["rows"]
        if row["corrected"].get("effective_result") is not None
    ]
    streams = baseline.load_all_streams("primary")
    rows: list[dict[str, Any]] = []
    for corrected_row in admitted:
        alias = str(corrected_row["case_alias"])
        source = v1_by_alias[alias]["family_router"]
        classification = grid.adjusted_classification(source["classification"], 2.0)
        best = simulate_track(
            classification=classification,
            stream=streams[alias],
            fill_at=source["geometry"]["fill_at"],
            track="FAITHFUL_FIXED_GEOMETRY",
        )
        sealed = corrected_row["corrected"]["effective_result"]
        baseline_r = float(sealed["net_r50"])
        best_r = float(best["net_r50"])
        mfe_r = float(sealed["mfe_r50"])
        row = {
            "trading_date_utc": str(corrected_row["trading_date_utc"]),
            "case_alias": alias,
            "session": str(source["session"]),
            "direction": str(source["classification"]["direction"]),
            "family": str(source["classification"]["family"]),
            "baseline_net_r": baseline_r,
            "baseline_resolution": str(sealed["resolution"]),
            "mfe_r": mfe_r,
            "mae_r": float(sealed["mae_r50"]),
            "fixed_2r_net_r": best_r,
            "fixed_2r_resolution": str(best["resolution"]),
            "incremental_r": best_r - baseline_r,
            "path_classification": classify_path(baseline_r, mfe_r, best_r),
            "fixed_2r_result_sha256": str(best["result_hash"]),
        }
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)

    control_2r_rows: list[dict[str, Any]] = []
    corrected_aliases = {row["case_alias"] for row in rows}
    for source_row in v1["rows"]:
        control = source_row.get("control") or {}
        sealed_result = control.get("result") or {}
        if not sealed_result.get("executed"):
            continue
        alias = str(source_row["case_alias"])
        classification = grid.adjusted_classification(control["classification"], 2.0)
        result = simulate_track(
            classification=classification,
            stream=streams[alias],
            fill_at=control["geometry"]["fill_at"],
            track="FAITHFUL_FIXED_GEOMETRY",
        )
        control_2r_rows.append({
            "trading_date_utc": str(source_row["trading_date_utc"]),
            "case_alias": alias,
            "retained_by_corrected_router": alias in corrected_aliases,
            "fixed_2r_net_r": float(result["net_r50"]),
            "mfe_r": float(result["mfe_r50"]),
            "mae_r": float(result["mae_r50"]),
            "resolution": str(result["resolution"]),
            "result_sha256": str(result["result_hash"]),
        })

    category = defaultdict(lambda: {"count": 0, "baseline_r": 0.0, "fixed_2r_r": 0.0, "incremental_r": 0.0})
    for row in rows:
        item = category[row["path_classification"]]
        item["count"] += 1
        item["baseline_r"] += float(row["baseline_net_r"])
        item["fixed_2r_r"] += float(row["fixed_2r_net_r"])
        item["incremental_r"] += float(row["incremental_r"])

    payload = {
        "version": "GOLD_EXPOSED_TRADE_ATTRIBUTION_V1_1_0",
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "EXPOSED_HYPOTHESIS_GENERATION_ONLY",
        "population": {
            "trades": len(rows),
            "dates": [row["trading_date_utc"] for row in rows],
            "directions": dict(Counter(row["direction"] for row in rows)),
            "sessions": dict(Counter(row["session"] for row in rows)),
            "families": dict(Counter(row["family"] for row in rows)),
        },
        "baseline": metrics(rows, "baseline_net_r"),
        "fixed_2r": metrics(rows, "fixed_2r_net_r"),
        "all_control_fixed_2r": metrics(control_2r_rows, "fixed_2r_net_r"),
        "router_excluded_control_fixed_2r": metrics(
            [row for row in control_2r_rows if not row["retained_by_corrected_router"]],
            "fixed_2r_net_r",
        ),
        "category_attribution": dict(sorted(category.items())),
        "largest_improvements": sorted(rows, key=lambda row: -float(row["incremental_r"]))[:10],
        "largest_deteriorations": sorted(rows, key=lambda row: float(row["incremental_r"]))[:10],
        "rows": rows,
        "all_control_fixed_2r_rows": control_2r_rows,
        "fresh_data_opened": False,
        "validation_credit": 0,
    }
    payload["result_sha256"] = canonical_hash(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "result_sha256": payload["result_sha256"],
        "baseline": payload["baseline"],
        "fixed_2r": payload["fixed_2r"],
        "all_control_fixed_2r": payload["all_control_fixed_2r"],
        "router_excluded_control_fixed_2r": payload["router_excluded_control_fixed_2r"],
        "categories": payload["category_attribution"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
