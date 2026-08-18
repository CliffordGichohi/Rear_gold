from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
STAGE1 = ARTIFACTS / "gold_structural_stop_geometry_v1_stage1"
STAGE1_SEAL = STAGE1 / "stage1_seal.json"
STAGE1_SUMMARY = STAGE1 / "primary_stage1_summary.json"
PROTOCOL = MANIFESTS / "gold_structural_stop_geometry_v1_protocol.json"
IMPLEMENTATION = MANIFESTS / "gold_structural_stop_geometry_v1_implementation_freeze.json"
OUTPUT = MANIFESTS / "gold_structural_stop_geometry_v1_stage2_pre_economic_freeze.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    seal = json.loads(STAGE1_SEAL.read_text(encoding="utf-8"))
    summary = json.loads(STAGE1_SUMMARY.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if seal.get("status") != "PASS_STAGE1_INDEPENDENT_REPRODUCTION":
        raise ValueError("Stage 1 did not pass")
    for item in seal["artifacts"].values():
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Stage-1 artifact changed: {item['path']}")
    if seal["result_hash"] != hashlib.sha256(
        json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest():
        raise ValueError("Stage-1 result hash changed")
    evaluated = [row["candidate_id"] for row in summary["stage1_gate_results"] if row["advances_to_economics"]]
    controls = [row["candidate_id"] for row in summary["stage1_gate_results"] if row["control"]]
    alternatives = [row["candidate_id"] for row in summary["stage1_gate_results"] if not row["control"] and row["advances_to_economics"]]
    if len(controls) != 18 or len(alternatives) != 35 or len(evaluated) != 53:
        raise ValueError("Stage-2 registry population changed")
    payload = {
        "version": "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_STAGE2_PRE_ECONOMIC_FREEZE_1_0",
        "status": "FROZEN_BEFORE_STAGE_2_ECONOMIC_VALUES",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "predecessors": {
            "stage1_seal": record(STAGE1_SEAL),
            "stage1_summary": record(STAGE1_SUMMARY),
            "protocol": record(PROTOCOL),
            "implementation_freeze": record(IMPLEMENTATION),
        },
        "evaluated_candidate_ids": evaluated,
        "baseline_control_ids": controls,
        "stage1_eligible_alternative_ids": alternatives,
        "stage1_rejected_alternatives_remain_rejected": 19,
        "population": {
            "primary": "BLOCKED_OOF_VALIDATION_UNION_2022_07_01_THROUGH_2024_12_31",
            "full_development": "DESCRIPTIVE_ONLY_2021_08_01_THROUGH_2024_12_31",
            "candidate_filter": "AVAILABLE_STOP_AND_AT_LEAST_ONE_WHOLE_OUNCE",
        },
        "overlap": {
            "scope": "SEPARATELY_PER_TIMEFRAME_MODEL_STOP_OR_NEIGHBOUR",
            "formal_oof": "APPLY_WITHIN_COMPLETE_CONTIGUOUS_OOF_UNION",
            "full_development": "APPLY_WITHIN_COMPLETE_DEVELOPMENT_PERIOD",
            "sort": ["ENTRY_AT_UTC_ASC", "TRADE_ID_ASC"],
            "acceptance": "ENTRY_AT_UTC_GTE_CURRENT_OPEN_UNTIL",
            "same_timestamp": "LOWEST_TRADE_ID_WINS",
            "open_until": "COUNTERFACTUAL_EXIT_AT_UTC",
        },
        "economics": {
            "gross_r": "SIGNED_EXIT_MINUS_ENTRY_DIVIDED_BY_STOP_DISTANCE",
            "cost_r": "FROZEN_ROUNDTRIP_COST_USD_OZ_DIVIDED_BY_STOP_DISTANCE_USD_OZ",
            "net_r": "GROSS_R_MINUS_COST_R",
            "cost_stress_r": "GROSS_R_MINUS_MULTIPLIER_TIMES_COST_R",
            "normalized_pnl_usd": "50_TIMES_NET_R",
            "whole_ounce_pnl_usd": "PLANNED_OUNCES_TIMES_SIGNED_PRICE_CHANGE_MINUS_FROZEN_COST",
            "planned_ounces": "FLOOR_50_DIVIDED_BY_STOP_DISTANCE_PLUS_BASE_COST",
            "compounding": False,
        },
        "performance": {
            "win": "NET_R_GT_ZERO",
            "loss": "NET_R_LT_ZERO",
            "profit_factor": "SUM_POSITIVE_NET_R_DIVIDED_BY_ABS_SUM_NEGATIVE_NET_R",
            "drawdown": "MAX_PEAK_TO_TROUGH_OF_CHRONOLOGICAL_CUMULATIVE_NET_R_OR_PNL",
            "annual_year": "KNOWN_AT_UTC_CALENDAR_YEAR",
            "cluster": "FROZEN_CLUSTER_DATE",
            "week": "ISO_WEEK_OF_FROZEN_CLUSTER_DATE",
            "session": "FROZEN_SESSION_STATE",
        },
        "bootstrap": {
            "resamples": 5000,
            "cluster": "TRADING_DATE",
            "sampling": "DATES_WITH_REPLACEMENT_EQUAL_PROBABILITY",
            "candidate_seed": "861301_PLUS_FIRST_8_HEX_SHA256_CANDIDATE_ID_MOD_2_POW_31_MINUS_1",
            "ci": "EMPIRICAL_2P5_AND_97P5_PERCENTILES",
            "p_one_sided": "ONE_PLUS_COUNT_EXPECTANCY_LTE_ZERO_DIVIDED_BY_5001",
        },
        "multiplicity": {
            "method": "BENJAMINI_HOCHBERG",
            "family": "ALL_53_EVALUATED_TESTS_SEPARATED_BY_TIMEFRAME",
            "missing_or_ineligible_p": 1.0,
            "q_lte": 0.10,
        },
        "stability": {
            "positive_fold": "MEAN_NET_R_GT_ZERO",
            "positive_year": "SUM_NET_R_GT_ZERO",
            "positive_session": "SUM_NET_R_GT_ZERO",
            "maximum_positive_share": "MAX_POSITIVE_GROUP_SUM_DIVIDED_BY_SUM_ALL_POSITIVE_GROUP_SUMS",
        },
        "neighbours": {
            "STOP_CONFIRMATION_EXTREME_0P25_ATR": [0.15, 0.35],
            "STOP_PIVOT_0P25_ATR": [0.15, 0.35],
            "STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR": [0.00, 0.20],
            "BASELINE_CONFIRMATION_EXTREME_BUFFER_0P05_ATR": [0.00, 0.15],
            "BASELINE_PIVOT_BUFFER_0P15_ATR": [0.05, 0.25],
            "evaluation": "OWN_STOP_AVAILABILITY_SIZING_EXIT_AND_OVERLAP_PATH",
            "candidate_gate": "BOTH_OOF_NET_EXPECTANCIES_STRICTLY_POSITIVE",
        },
        "ranking_and_limit": protocol["ranking"],
        "maximum_candidates_per_timeframe": protocol["maximum_candidates_per_timeframe"],
        "baseline_controls_cannot_receive_candidate_credit": True,
        "stage1_rejected_stops_cannot_be_economically_resurrected": True,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_exclusive(OUTPUT, payload)
    print(json.dumps({"status": payload["status"], "evaluated": len(evaluated), "freeze": record(OUTPUT)}, sort_keys=True))


if __name__ == "__main__":
    main()
