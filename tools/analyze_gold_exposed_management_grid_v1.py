#!/usr/bin/env python3
"""Bounded exposed-data management grid for the corrected Router V1 population."""

from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402
from gold_intel.analytics.coherent_auction_human_policy_v2 import simulate_track  # noqa: E402


V1_RESULT = ROOT / "research_artifacts" / "gold_auction_family_router_exposed_regression_v1" / "final_result.json"
CORRECTED_RESULT = ROOT / "research_artifacts" / "gold_auction_family_router_v1_r1_mechanical_correction" / "final_result.json"
OUTPUT = ROOT / "research_artifacts" / "gold_exposed_management_grid_v1" / "final_result.json"

TARGET_CAPS_R: tuple[float | None, ...] = (None, 1.5, 2.0, 2.5, 3.0, 4.0)
POLICIES: tuple[tuple[str, float | None], ...] = (
    ("FAITHFUL_FIXED_GEOMETRY", None),
    ("PROTECTED_FIXED_GEOMETRY", 1.25),
    ("PROTECTED_FIXED_GEOMETRY", 1.50),
    ("PROTECTED_FIXED_GEOMETRY", 2.00),
    ("PROTECTED_FIXED_GEOMETRY", 2.50),
    ("COMPLETE_V2_POLICY", 1.25),
    ("COMPLETE_V2_POLICY", 1.50),
    ("COMPLETE_V2_POLICY", 2.00),
    ("COMPLETE_V2_POLICY", 2.50),
)
WIN_EPSILON = 1e-12


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def adjusted_classification(
    classification: dict[str, Any], target_cap_r: float | None
) -> dict[str, Any]:
    output = copy.deepcopy(classification)
    if target_cap_r is not None:
        sign = 1.0 if output["direction"] == "LONG" else -1.0
        fill = float(output["fill"])
        structural_risk = float(output["structural_price_risk_per_ounce"])
        capped = fill + sign * float(target_cap_r) * structural_risk
        original = float(output["target"])
        output["target"] = min(original, capped) if sign > 0 else max(original, capped)
    output["classification_hash"] = canonical_hash(
        {key: value for key, value in output.items() if key != "classification_hash"}
    )
    return output


def metrics(values: list[tuple[str, float]]) -> dict[str, Any]:
    numbers = [value for _, value in values]
    wins = [value for value in numbers if value > WIN_EPSILON]
    losses = [value for value in numbers if value < -WIN_EPSILON]
    equity = peak = drawdown = 0.0
    for value in numbers:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    months = sorted({date[:7] for date, _ in values})
    monthly = {
        month: sum(value for date, value in values if date.startswith(month))
        for month in months
    }
    positive = sum(wins)
    negative = abs(sum(losses))
    return {
        "trades": len(numbers),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(numbers) - len(wins) - len(losses),
        "win_rate": len(wins) / len(numbers) if numbers else None,
        "net_r": sum(numbers),
        "r_per_month": sum(numbers) / len(months) if months else 0.0,
        "expectancy_r": sum(numbers) / len(numbers) if numbers else 0.0,
        "profit_factor": positive / negative if negative else None,
        "maximum_drawdown_r": drawdown,
        "monthly": monthly,
        "positive_months": sum(value > 0 for value in monthly.values()),
        "minimum_month_r": min(monthly.values()) if monthly else None,
        "maximum_month_r": max(monthly.values()) if monthly else None,
    }


def main() -> int:
    v1 = load_json(V1_RESULT)
    corrected = load_json(CORRECTED_RESULT)
    v1_by_alias = {str(row["case_alias"]): row for row in v1["rows"]}
    admitted = [
        row
        for row in corrected["rows"]
        if row["corrected"].get("effective_result") is not None
    ]
    aliases = [str(row["case_alias"]) for row in admitted]
    streams = baseline.load_all_streams("primary")
    results: list[dict[str, Any]] = []
    baseline_reproduced = True
    for target_cap in TARGET_CAPS_R:
        for track, threshold in POLICIES:
            values: list[tuple[str, float]] = []
            result_hashes: list[str] = []
            for corrected_row in admitted:
                alias = str(corrected_row["case_alias"])
                source = v1_by_alias[alias]["family_router"]
                classification = adjusted_classification(
                    source["classification"], target_cap
                )
                kwargs: dict[str, Any] = {
                    "classification": classification,
                    "stream": streams[alias],
                    "fill_at": source["geometry"]["fill_at"],
                    "track": track,
                }
                if threshold is not None:
                    kwargs["protection_threshold_r"] = threshold
                result = simulate_track(**kwargs)
                values.append(
                    (str(corrected_row["trading_date_utc"]), float(result["net_r50"]))
                )
                result_hashes.append(str(result["result_hash"]))
                if target_cap is None and track == "COMPLETE_V2_POLICY" and threshold == 1.25:
                    sealed = corrected_row["corrected"]["effective_result"]
                    baseline_reproduced = baseline_reproduced and (
                        result["result_hash"] == sealed["result_hash"]
                    )
            block = {
                "target_cap_r": target_cap,
                "track": track,
                "protection_threshold_r": threshold,
                **metrics(values),
                "result_set_sha256": canonical_hash(result_hashes),
            }
            results.append(block)
    if not baseline_reproduced:
        raise RuntimeError("Sealed corrected baseline did not reproduce")
    results.sort(
        key=lambda row: (
            -float(row["net_r"]),
            float(row["maximum_drawdown_r"]),
            str(row["track"]),
            str(row["target_cap_r"]),
        )
    )
    active_results = [row["corrected"]["effective_result"] for row in admitted]
    control_results = [
        row["control"]["result"]
        for row in load_json(
            ROOT
            / "research_artifacts"
            / "gold_day_by_day_auction_confirmation_exposed_regression_v1"
            / "final_result.json"
        )["rows"]
        if row["control"].get("result")
        and row["control"]["result"].get("executed")
    ]
    payload = {
        "version": "GOLD_EXPOSED_MANAGEMENT_GRID_V1_1_0",
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "population": {
            "corrected_trades": len(admitted),
            "aliases_sha256": canonical_hash(aliases),
            "months": 5,
        },
        "baseline_reproduced": baseline_reproduced,
        "ceilings": {
            "corrected_trade_sum_mfe_r": sum(float(row["mfe_r50"]) for row in active_results),
            "corrected_trade_perfect_mfe_r_per_month": sum(float(row["mfe_r50"]) for row in active_results) / 5.0,
            "all_control_trade_sum_mfe_r": sum(float(row["mfe_r50"]) for row in control_results),
            "all_control_trade_perfect_mfe_r_per_month": sum(float(row["mfe_r50"]) for row in control_results) / 5.0,
        },
        "grid_size": len(results),
        "top_results": results[:15],
        "all_results": results,
        "fresh_data_opened": False,
        "validation_credit": 0,
    }
    payload["result_sha256"] = canonical_hash(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "result_sha256": payload["result_sha256"],
                "baseline_reproduced": baseline_reproduced,
                "grid_size": len(results),
                "best": results[0],
                "ceilings": payload["ceilings"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
