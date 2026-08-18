from __future__ import annotations

import bisect
import gc
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from materialize_gold_point_in_time_auction_state_v1_outcomes import RangeTree
from materialize_gold_point_in_time_auction_state_v1_tape import (
    ROOT,
    SCALE,
    Frame,
    canonical_hash,
    canonical_json,
    file_record,
    load_price,
    ns_iso,
    parse_ns,
    sha256_file,
    utc_now,
    write_json_exclusive,
)


CONTRACT = ROOT / "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = ROOT / "research_manifests/gold_bidirectional_auction_resolution_v1_protocol.json"
PREOUTCOME_FREEZE = ROOT / "research_manifests/gold_bidirectional_auction_resolution_v1_preoutcome_freeze.json"
MATERIALIZATION_FREEZE = ROOT / "research_manifests/gold_bidirectional_auction_resolution_v1_materialization_freeze.json"
DEVELOPMENT_FREEZE = ROOT / "research_manifests/gold_bidirectional_auction_resolution_v1_development_freeze.json"
FINAL_FREEZE = ROOT / "research_manifests/gold_bidirectional_auction_resolution_v1_final_freeze.json"

ATLAS = ROOT / "research_artifacts/gold_pullback_behavioural_archetypes_v1/primary_archetypes.parquet"
ATLAS_SEAL = ROOT / "research_artifacts/gold_pullback_behavioural_archetypes_v1/final_seal.json"
TAPE_DIR = ROOT / "research_artifacts/gold_point_in_time_auction_state_adaptive_management_v1_tape"
PRIMARY_TAPE = TAPE_DIR / "primary_checkpoint_features.parquet"
REFERENCE_TAPE = TAPE_DIR / "reference_checkpoint_features.parquet"
TAPE_FREEZE = ROOT / "research_manifests/gold_point_in_time_auction_state_adaptive_management_v1_tape_freeze.json"
REGISTRY = ROOT / "research_artifacts/gold_point_in_time_auction_state_adaptive_management_v1_preoutcome/primary_case_tape_registry.parquet"
RAW_PRICE = ROOT / "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz"
PRIOR_CLOSURE = ROOT / "research_manifests/gold_point_in_time_auction_state_adaptive_management_v1_closure_freeze.json"

OUTPUT = ROOT / "research_artifacts/gold_bidirectional_auction_resolution_v1"
OPENING = OUTPUT / "development_source_opening.json"
PRIMARY_PLANS = OUTPUT / "primary_case_plans.parquet"
REFERENCE_PLANS = OUTPUT / "reference_case_plans.parquet"
MATERIALIZATION_CERT = OUTPUT / "materialization_certification.json"
PRIMARY_OOF = OUTPUT / "primary_oof_cases.parquet"
REFERENCE_OOF = OUTPUT / "reference_oof_cases.parquet"
PRIMARY_RESULTS = OUTPUT / "primary_results.json"
REFERENCE_RESULTS = OUTPUT / "reference_results.json"
DEVELOPMENT_RESULTS = OUTPUT / "development_results.json"
FINAL_RESULTS = OUTPUT / "final_results.json"
REPORT = ROOT / "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_EDGE_DISCOVERY_V1_REPORT.md"
TESTS = ROOT / "tests/test_gold_bidirectional_auction_resolution_v1.py"

EXPECTED = {
    "atlas": (1_906_259, "1b48075bbaa4c14873a84cd66f570259eca044813a008e768f9d1ecca41ba856"),
    "primary_tape": (277_244_945, "3f52606c3ab83788e9a9a486b30d8ac1d93286e58b81e9e92b5923c618fb8166"),
    "reference_tape": (277_244_945, "3f52606c3ab83788e9a9a486b30d8ac1d93286e58b81e9e92b5923c618fb8166"),
    "raw_price": (258_834_096, "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"),
}

SIGNAL_FRAME = {"M15": "M1", "H1": "M5", "H4": "M15"}
MODELS = ("CONTINUATION_ONLY_CONTROL", "REVERSAL_ONLY", "BIDIRECTIONAL_ONE_FLIP")
SPLITS = (
    ("SPLIT_15_35", 15.0, 35.0),
    ("SPLIT_25_25", 25.0, 25.0),
    ("SPLIT_35_15", 35.0, 15.0),
)
FULL_SPLIT = ("FULL_50", 50.0, 0.0)
MONTHS = 39
SEED = 621907
FOLDS = (
    (1, "2021-10-01", "2021-12-31"),
    (2, "2022-01-01", "2022-06-30"),
    (3, "2022-07-01", "2022-12-31"),
    (4, "2023-01-01", "2023-06-30"),
    (5, "2023-07-01", "2023-12-31"),
    (6, "2024-01-01", "2024-06-30"),
    (7, "2024-07-01", "2024-12-31"),
)
SELECTION_SUPPORT = {
    "M15": (50, 34),
    "H1": (20, 17),
    "H4": (10, 9),
}
FINAL_SUPPORT = {
    "M15": (150, 100),
    "H1": (60, 50),
    "H4": (30, 25),
}

TAPE_COLUMNS = [
    "row_id",
    "pullback_id",
    "timeframe",
    "direction",
    "decision_date",
    "known_at_utc",
    "deadline_at_utc",
    "checkpoint_at_utc",
    "checkpoint_index",
    "checkpoint_feature_available",
    "unavailable_reason",
    "setup_atr_e8",
    "structural_stop_e8",
    "liquidity_target_e8",
    "geometry_available_at_decision_mark",
    "current_displacement_atr",
    "acceptance_state",
    "sweep_reclaim_state",
    "local_structure_score",
    "fundamental_alignment_state",
    "higher_timeframe_alignment_fraction",
    "session_state",
    "feature_lineage_hash",
]


PLAN_SCHEMA = pa.schema(
    [
        pa.field("case_plan_id", pa.string(), False),
        pa.field("pullback_id", pa.string(), False),
        pa.field("timeframe", pa.string(), False),
        pa.field("original_direction", pa.string(), False),
        pa.field("decision_date", pa.string(), False),
        pa.field("known_at_utc", pa.string(), False),
        pa.field("deadline_at_utc", pa.string(), False),
        pa.field("model_id", pa.string(), False),
        pa.field("risk_split_id", pa.string(), False),
        pa.field("plan_available", pa.bool_(), False),
        pa.field("unavailable_reason", pa.string(), False),
        pa.field("traded", pa.bool_(), False),
        pa.field("first_side", pa.string()),
        pa.field("first_direction", pa.string()),
        pa.field("first_trigger_at_utc", pa.string()),
        pa.field("first_entry_at_utc", pa.string()),
        pa.field("first_exit_at_utc", pa.string()),
        pa.field("first_exit_reason", pa.string()),
        pa.field("first_budget_usd", pa.float64()),
        pa.field("first_ounces", pa.int64()),
        pa.field("first_entry_e8", pa.int64()),
        pa.field("first_stop_e8", pa.int64()),
        pa.field("first_target_e8", pa.int64()),
        pa.field("first_risk_e8", pa.int64()),
        pa.field("first_cost_usd_oz", pa.float64()),
        pa.field("first_mfe_r", pa.float64()),
        pa.field("first_mae_r", pa.float64()),
        pa.field("first_pnl_usd", pa.float64()),
        pa.field("first_pnl_usd_cost_1p5x", pa.float64()),
        pa.field("first_pnl_usd_cost_2x", pa.float64()),
        pa.field("first_attempt_stopped", pa.bool_(), False),
        pa.field("flip_taken", pa.bool_(), False),
        pa.field("flip_success", pa.bool_(), False),
        pa.field("second_side", pa.string()),
        pa.field("second_direction", pa.string()),
        pa.field("second_trigger_at_utc", pa.string()),
        pa.field("second_entry_at_utc", pa.string()),
        pa.field("second_exit_at_utc", pa.string()),
        pa.field("second_exit_reason", pa.string()),
        pa.field("second_budget_usd", pa.float64()),
        pa.field("second_ounces", pa.int64()),
        pa.field("second_entry_e8", pa.int64()),
        pa.field("second_stop_e8", pa.int64()),
        pa.field("second_target_e8", pa.int64()),
        pa.field("second_risk_e8", pa.int64()),
        pa.field("second_cost_usd_oz", pa.float64()),
        pa.field("second_mfe_r", pa.float64()),
        pa.field("second_mae_r", pa.float64()),
        pa.field("second_pnl_usd", pa.float64()),
        pa.field("second_pnl_usd_cost_1p5x", pa.float64()),
        pa.field("second_pnl_usd_cost_2x", pa.float64()),
        pa.field("first_entry_session", pa.string()),
        pa.field("final_exit_at_utc", pa.string()),
        pa.field("planned_loss_usd", pa.float64()),
        pa.field("continuation_pnl_usd", pa.float64(), False),
        pa.field("continuation_pnl_usd_cost_1p5x", pa.float64(), False),
        pa.field("continuation_pnl_usd_cost_2x", pa.float64(), False),
        pa.field("reversal_pnl_usd", pa.float64(), False),
        pa.field("reversal_pnl_usd_cost_1p5x", pa.float64(), False),
        pa.field("reversal_pnl_usd_cost_2x", pa.float64(), False),
        pa.field("total_pnl_usd", pa.float64()),
        pa.field("total_pnl_usd_cost_1p5x", pa.float64()),
        pa.field("total_pnl_usd_cost_2x", pa.float64()),
        pa.field("case_net_r", pa.float64()),
        pa.field("case_net_r_cost_1p5x", pa.float64()),
        pa.field("case_net_r_cost_2x", pa.float64()),
        pa.field("plan_lineage_hash", pa.string(), False),
    ]
)


OOF_SCHEMA = pa.schema(
    [
        pa.field("oof_id", pa.string(), False),
        pa.field("pullback_id", pa.string(), False),
        pa.field("timeframe", pa.string(), False),
        pa.field("model_id", pa.string(), False),
        pa.field("fold", pa.int32(), False),
        pa.field("selected_risk_split_id", pa.string(), False),
        pa.field("decision_date", pa.string(), False),
        pa.field("first_entry_at_utc", pa.string()),
        pa.field("final_exit_at_utc", pa.string()),
        pa.field("entry_session", pa.string()),
        pa.field("traded", pa.bool_(), False),
        pa.field("retained_after_overlap", pa.bool_(), False),
        pa.field("overlap_disposition", pa.string(), False),
        pa.field("case_net_r", pa.float64()),
        pa.field("case_net_r_cost_1p5x", pa.float64()),
        pa.field("case_net_r_cost_2x", pa.float64()),
        pa.field("total_pnl_usd", pa.float64()),
        pa.field("total_pnl_usd_cost_1p5x", pa.float64()),
        pa.field("total_pnl_usd_cost_2x", pa.float64()),
        pa.field("first_side", pa.string()),
        pa.field("first_attempt_stopped", pa.bool_(), False),
        pa.field("flip_taken", pa.bool_(), False),
        pa.field("flip_success", pa.bool_(), False),
        pa.field("continuation_pnl_usd", pa.float64(), False),
        pa.field("reversal_pnl_usd", pa.float64(), False),
        pa.field("first_mfe_r", pa.float64()),
        pa.field("first_mae_r", pa.float64()),
        pa.field("second_mfe_r", pa.float64()),
        pa.field("second_mae_r", pa.float64()),
        pa.field("plan_lineage_hash", pa.string(), False),
    ]
)


def finite(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def rounded(value: Any, places: int = 10) -> float | None:
    number = finite(value)
    return None if number is None else round(number, places)


def verify_record(path: Path, expected: tuple[int, str], label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing frozen {label}: {path}")
    if path.stat().st_size != expected[0] or sha256_file(path) != expected[1]:
        raise ValueError(f"Frozen {label} changed")


def preflight() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_ACCESS":
        raise ValueError("Protocol is not frozen")
    closure = json.loads(PRIOR_CLOSURE.read_text(encoding="utf-8"))
    if closure.get("verdict") != "REJECT_NO_ECONOMICALLY_PROVEN_DEVELOPMENT_EDGE":
        raise ValueError("Prior rejection was not preserved")
    if closure.get("forward_disposition", {}).get("calendar_2025_values_accessed") is not False or closure.get("forward_disposition", {}).get("calendar_2026_values_accessed") is not False:
        raise ValueError("Prior forward lock has changed")
    tape = json.loads(TAPE_FREEZE.read_text(encoding="utf-8"))
    if tape.get("status") != "PASS_OUTCOME_BLIND_DECISION_TAPE_MATERIALIZATION" or not tape.get("byte_identical"):
        raise ValueError("Outcome-blind tape certification is invalid")
    atlas_seal = json.loads(ATLAS_SEAL.read_text(encoding="utf-8"))
    if atlas_seal.get("status") != "PASS_COMPLETE_DEVELOPMENT_ARCHETYPE_ATLAS":
        raise ValueError("Population atlas is not sealed")
    verify_record(ATLAS, EXPECTED["atlas"], "population atlas")
    verify_record(PRIMARY_TAPE, EXPECTED["primary_tape"], "primary tape")
    verify_record(REFERENCE_TAPE, EXPECTED["reference_tape"], "reference tape")
    verify_record(RAW_PRICE, EXPECTED["raw_price"], "raw price source")
    if sha256_file(PRIMARY_TAPE) != sha256_file(REFERENCE_TAPE):
        raise ValueError("Primary/reference tape bytes differ")
    if not CONTRACT.exists() or not REGISTRY.exists() or not TESTS.exists():
        raise FileNotFoundError("Contract or complete registry missing")
    terminal_paths = (MATERIALIZATION_FREEZE, DEVELOPMENT_FREEZE, FINAL_FREEZE, DEVELOPMENT_RESULTS, FINAL_RESULTS, REPORT)
    if any(path.exists() for path in terminal_paths):
        raise FileExistsError("This branch already has terminal artifacts")
    return {"protocol": protocol, "closure": closure, "tape": tape, "atlas_seal": atlas_seal}


def synthetic_proof() -> dict[str, Any]:
    high = np.asarray([100, 104, 110, 106, 120], dtype=np.int64)
    low = np.asarray([90, 88, 95, 80, 100], dtype=np.int64)
    tree = RangeTree(high, low)
    comparisons = 0
    for left, right, threshold in ((0, 5, 109), (1, 4, 103), (3, 5, 119)):
        assert tree.first_high_primary(left, right, threshold) == tree.first_high_reference(left, right, threshold)
        comparisons += 1
    for left, right, threshold in ((0, 5, 89), (2, 5, 85), (0, 3, 89)):
        assert tree.first_low_primary(left, right, threshold) == tree.first_low_reference(left, right, threshold)
        comparisons += 1
    for left, right in ((0, 5), (1, 4), (2, 3)):
        assert tree.extrema_primary(left, right) == tree.extrema_reference(left, right)
        comparisons += 1
    assert math.floor(25.0 / (4.0 + 0.5)) == 5
    assert math.floor(15.0 / (20.0 + 0.5)) == 0
    attempt_seen = False
    synthetic = [
        {"acceptance_state": 1.0, "sweep_reclaim_state": 0.0},
        {"acceptance_state": -1.0, "sweep_reclaim_state": 0.0},
    ]
    reverse_eligible = []
    for row in synthetic:
        reverse_eligible.append(attempt_seen and row["acceptance_state"] == -1.0)
        if row["acceptance_state"] == 1.0 or row["sweep_reclaim_state"] == -1.0:
            attempt_seen = True
    assert reverse_eligible == [False, True]
    return {
        "status": "PASS_SYNTHETIC_RANGE_SIZE_AND_STRICT_PRIOR_ATTEMPT_PROOF",
        "range_comparisons": comparisons,
        "risk_size_cases": 2,
        "strict_prior_attempt_cases": 2,
    }


def seal_preoutcome(audit: Mapping[str, Any], proof: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "version": "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_V1_PREOUTCOME_FREEZE_1_0",
        "status": "SEALED_BEFORE_DEVELOPMENT_OUTCOME_ACCESS",
        "sealed_at_utc": utc_now(),
        "controls": {
            "contract": file_record(CONTRACT),
            "protocol": file_record(PROTOCOL),
            "implementation": file_record(Path(__file__).resolve()),
            "tests": file_record(TESTS),
            "prior_closure": file_record(PRIOR_CLOSURE),
            "tape_freeze": file_record(TAPE_FREEZE),
            "atlas_seal": file_record(ATLAS_SEAL),
        },
        "sources": {
            "population": file_record(ATLAS),
            "registry": file_record(REGISTRY),
            "primary_tape": file_record(PRIMARY_TAPE),
            "reference_tape": file_record(REFERENCE_TAPE),
            "raw_price": file_record(RAW_PRICE),
        },
        "population": {"cases": 8653, "available_tapes": 8650, "checkpoint_rows": 2_095_849},
        "synthetic_proof": dict(proof),
        "development_outcomes_accessed": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(PREOUTCOME_FREEZE, payload)
    return payload


def locate(values: Sequence[int], target: int, implementation: str, side: str = "left") -> int:
    if implementation == "primary":
        return int(np.searchsorted(values, target, side=side))
    return bisect.bisect_left(values, target) if side == "left" else bisect.bisect_right(values, target)


def iter_case_groups(path: Path) -> Iterable[list[dict[str, Any]]]:
    current_id: str | None = None
    current: list[dict[str, Any]] = []
    seen: set[str] = set()
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(columns=TAPE_COLUMNS, batch_size=8192):
        for row in batch.to_pylist():
            identity = str(row["pullback_id"])
            if current_id is None:
                current_id = identity
            if identity != current_id:
                if identity in seen:
                    raise ValueError(f"Non-contiguous tape identity: {identity}")
                seen.add(current_id)
                yield current
                current = []
                current_id = identity
            current.append(row)
    if current:
        if current_id in seen:
            raise ValueError(f"Repeated terminal tape identity: {current_id}")
        yield current


def context_permitted(row: Mapping[str, Any], side: str) -> bool:
    fundamental = str(row.get("fundamental_alignment_state") or "UNKNOWN")
    htf = finite(row.get("higher_timeframe_alignment_fraction"))
    if side == "TREND":
        return fundamental in {"ALIGNED", "NEUTRAL_OR_WEAK", "UNKNOWN"} and (htf is None or htf >= 0.50)
    return fundamental in {"OPPOSED", "NEUTRAL_OR_WEAK", "UNKNOWN"} and (htf is None or htf <= 0.50)


def direction_for_side(original: str, side: str) -> str:
    if side == "TREND":
        return original
    return "DOWN" if original == "UP" else "UP"


def preview_leg(
    row: Mapping[str, Any],
    side: str,
    budget: float,
    frames: Mapping[str, Frame],
    implementation: str,
) -> tuple[dict[str, Any] | None, str]:
    checkpoint = parse_ns(str(row["checkpoint_at_utc"]))
    timeframe = str(row["timeframe"])
    original = str(row["direction"])
    direction = direction_for_side(original, side)
    sign = 1 if direction == "UP" else -1
    m1 = frames["M1"]
    entry_index = locate(m1.open_ns, checkpoint, implementation, "left")
    if entry_index >= len(m1.open_ns) or int(m1.open_ns[entry_index]) != checkpoint:
        return None, "MISSING_EXACT_ENTRY_M1"
    entry = int(m1.open_e8[entry_index])
    spread_raw = float(m1.spread[entry_index])
    spread = spread_raw if math.isfinite(spread_raw) and spread_raw >= 0 else 0.30
    cost = spread + 0.07 + 0.10
    atr = finite(row.get("setup_atr_e8"))
    if atr is None or atr <= 0:
        return None, "MISSING_SETUP_ATR"
    if side == "TREND":
        if not bool(row.get("geometry_available_at_decision_mark")):
            return None, "MISSING_TREND_GEOMETRY"
        if row.get("structural_stop_e8") is None or row.get("liquidity_target_e8") is None:
            return None, "MISSING_TREND_STOP_OR_TARGET"
        stop = int(row["structural_stop_e8"])
        target = int(row["liquidity_target_e8"])
    else:
        if row.get("structural_stop_e8") is None:
            return None, "MISSING_REVERSAL_STRUCTURAL_TARGET"
        signal = frames[SIGNAL_FRAME[timeframe]]
        signal_index = locate(signal.close_ns, checkpoint, implementation, "left")
        if signal_index >= len(signal.close_ns) or int(signal.close_ns[signal_index]) != checkpoint:
            return None, "MISSING_REVERSAL_TRIGGER_CANDLE"
        if direction == "UP":
            stop = int(round(int(signal.low_e8[signal_index]) - 0.10 * atr))
        else:
            stop = int(round(int(signal.high_e8[signal_index]) + 0.10 * atr))
        target = int(row["structural_stop_e8"])
    risk = sign * (entry - stop)
    room = sign * (target - entry)
    if risk <= 0:
        return None, "STOP_NOT_ADVERSE_TO_FILL"
    if room < risk:
        return None, "TARGET_ROOM_BELOW_1R"
    risk_usd_oz = risk / SCALE
    ounces = math.floor(budget / (risk_usd_oz + cost) + 1e-12)
    if ounces < 1:
        return None, "MINIMUM_ONE_OUNCE_EXCEEDS_ATTEMPT_BUDGET"
    return {
        "side": side,
        "direction": direction,
        "checkpoint_ns": checkpoint,
        "entry_index": entry_index,
        "entry_e8": entry,
        "stop_e8": stop,
        "target_e8": target,
        "risk_e8": risk,
        "cost_usd_oz": cost,
        "spread_fallback": spread != spread_raw,
        "ounces": ounces,
        "budget_usd": budget,
        "session": str(row.get("session_state") or "UNKNOWN"),
        "row_id": str(row["row_id"]),
        "feature_lineage_hash": str(row.get("feature_lineage_hash") or ""),
    }, ""


def trend_signal(row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("checkpoint_feature_available"))
        and finite(row.get("acceptance_state")) == 1.0
        and finite(row.get("local_structure_score")) == 1.0
        and (finite(row.get("current_displacement_atr")) or 0.0) > 0.0
        and context_permitted(row, "TREND")
    )


def reverse_signal(row: Mapping[str, Any], prior_attempt_seen: bool) -> bool:
    return (
        prior_attempt_seen
        and bool(row.get("checkpoint_feature_available"))
        and finite(row.get("acceptance_state")) == -1.0
        and finite(row.get("local_structure_score")) == -1.0
        and (finite(row.get("current_displacement_atr")) or 0.0) < 0.0
        and context_permitted(row, "REVERSAL")
    )


def attempt_marker(row: Mapping[str, Any]) -> bool:
    return bool(row.get("checkpoint_feature_available")) and (
        finite(row.get("acceptance_state")) == 1.0 or finite(row.get("sweep_reclaim_state")) == -1.0
    )


def find_trigger(
    rows: Sequence[Mapping[str, Any]],
    permitted_sides: set[str],
    budget: float,
    frames: Mapping[str, Frame],
    implementation: str,
    start_ns: int | None = None,
    initial_attempt_seen: bool = False,
) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None, Counter[str]]:
    attempt_seen = initial_attempt_seen
    rejected: Counter[str] = Counter()
    for row in rows:
        timestamp = parse_ns(str(row["checkpoint_at_utc"]))
        if start_ns is not None and timestamp < start_ns:
            if attempt_marker(row):
                attempt_seen = True
            continue
        candidates: list[str] = []
        if "TREND" in permitted_sides and trend_signal(row):
            candidates.append("TREND")
        if "REVERSAL" in permitted_sides and reverse_signal(row, attempt_seen):
            candidates.append("REVERSAL")
        for side in candidates:
            preview, reason = preview_leg(row, side, budget, frames, implementation)
            if preview is not None:
                return row, preview, rejected
            rejected[f"{side}::{reason}"] += 1
        if attempt_marker(row):
            attempt_seen = True
    return None, None, rejected


def event_index(
    tree: RangeTree,
    direction: str,
    kind: str,
    left: int,
    right: int,
    price: int,
    implementation: str,
) -> int | None:
    high = (direction == "UP" and kind == "TARGET") or (direction == "DOWN" and kind == "STOP")
    if high:
        return tree.first_high_primary(left, right, price) if implementation == "primary" else tree.first_high_reference(left, right, price)
    return tree.first_low_primary(left, right, price) if implementation == "primary" else tree.first_low_reference(left, right, price)


def simulate_leg(
    preview: Mapping[str, Any],
    deadline_ns: int,
    m1: Frame,
    tree: RangeTree,
    invalid_prefix: np.ndarray,
    implementation: str,
) -> tuple[dict[str, Any] | None, str]:
    left = int(preview["entry_index"])
    right = locate(m1.close_ns, deadline_ns, implementation, "right")
    if right <= left or int(m1.close_ns[right - 1]) != deadline_ns:
        return None, "INCOMPLETE_M1_DEADLINE_PATH"
    if int(invalid_prefix[right] - invalid_prefix[left]) != 0:
        return None, "INVALID_M1_IN_ENTRY_TO_DEADLINE_PATH"
    direction = str(preview["direction"])
    stop = int(preview["stop_e8"])
    target = int(preview["target_e8"])
    stop_index = event_index(tree, direction, "STOP", left, right, stop, implementation)
    target_index = event_index(tree, direction, "TARGET", left, right, target, implementation)
    stop_order = stop_index if stop_index is not None else math.inf
    target_order = target_index if target_index is not None else math.inf
    sign = 1 if direction == "UP" else -1
    if stop_order <= target_order and stop_order != math.inf:
        exit_index = int(stop_order)
        opened = int(m1.open_e8[exit_index])
        exit_price = min(stop, opened) if direction == "UP" else max(stop, opened)
        exit_reason = "STRUCTURAL_STOP"
    elif target_order != math.inf:
        exit_index = int(target_order)
        exit_price = target
        exit_reason = "KNOWN_TARGET"
    else:
        exit_index = right - 1
        exit_price = int(m1.close_e8[exit_index])
        exit_reason = "TIME_EXIT"
    maximum, minimum = tree.extrema_primary(left, right) if implementation == "primary" else tree.extrema_reference(left, right)
    risk = int(preview["risk_e8"])
    entry = int(preview["entry_e8"])
    mfe = ((maximum - entry) if sign > 0 else (entry - minimum)) / risk
    mae = ((entry - minimum) if sign > 0 else (maximum - entry)) / risk
    ounces = int(preview["ounces"])
    gross_usd = ounces * sign * (exit_price - entry) / SCALE
    cost_usd = ounces * float(preview["cost_usd_oz"])
    net = gross_usd - cost_usd
    net_1p5 = gross_usd - 1.5 * cost_usd
    net_2 = gross_usd - 2.0 * cost_usd
    planned_loss = ounces * (risk / SCALE + float(preview["cost_usd_oz"]))
    result = {
        **dict(preview),
        "exit_index": exit_index,
        "exit_ns": int(m1.close_ns[exit_index]),
        "exit_e8": exit_price,
        "exit_reason": exit_reason,
        "stopped": exit_reason == "STRUCTURAL_STOP",
        "target_hit": exit_reason == "KNOWN_TARGET",
        "mfe_r": float(mfe),
        "mae_r": float(mae),
        "gross_pnl_usd": float(gross_usd),
        "net_pnl_usd": float(net),
        "net_pnl_usd_cost_1p5x": float(net_1p5),
        "net_pnl_usd_cost_2x": float(net_2),
        "planned_loss_usd": float(planned_loss),
    }
    result["leg_lineage_hash"] = canonical_hash(
        [
            preview["row_id"],
            preview["side"],
            preview["budget_usd"],
            left,
            right,
            stop,
            target,
            exit_index,
            exit_price,
            preview["cost_usd_oz"],
        ]
    )
    return result, ""


def base_plan(meta: Mapping[str, Any], model: str, split_id: str) -> dict[str, Any]:
    row: dict[str, Any] = {field.name: None for field in PLAN_SCHEMA}
    row.update(
        {
            "case_plan_id": canonical_hash([meta["pullback_id"], model, split_id]),
            "pullback_id": str(meta["pullback_id"]),
            "timeframe": str(meta["timeframe"]),
            "original_direction": str(meta["direction"]),
            "decision_date": str(meta["decision_date"]),
            "known_at_utc": str(meta["known_at_utc"]),
            "deadline_at_utc": str(meta["deadline_at_utc"]),
            "model_id": model,
            "risk_split_id": split_id,
            "plan_available": True,
            "unavailable_reason": "",
            "traded": False,
            "first_attempt_stopped": False,
            "flip_taken": False,
            "flip_success": False,
            "continuation_pnl_usd": 0.0,
            "continuation_pnl_usd_cost_1p5x": 0.0,
            "continuation_pnl_usd_cost_2x": 0.0,
            "reversal_pnl_usd": 0.0,
            "reversal_pnl_usd_cost_1p5x": 0.0,
            "reversal_pnl_usd_cost_2x": 0.0,
        }
    )
    return row


def leg_fields(prefix: str, leg: Mapping[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_side": str(leg["side"]),
        f"{prefix}_direction": str(leg["direction"]),
        f"{prefix}_trigger_at_utc": ns_iso(int(leg["checkpoint_ns"])),
        f"{prefix}_entry_at_utc": ns_iso(int(leg["checkpoint_ns"])),
        f"{prefix}_exit_at_utc": ns_iso(int(leg["exit_ns"])),
        f"{prefix}_exit_reason": str(leg["exit_reason"]),
        f"{prefix}_budget_usd": float(leg["budget_usd"]),
        f"{prefix}_ounces": int(leg["ounces"]),
        f"{prefix}_entry_e8": int(leg["entry_e8"]),
        f"{prefix}_stop_e8": int(leg["stop_e8"]),
        f"{prefix}_target_e8": int(leg["target_e8"]),
        f"{prefix}_risk_e8": int(leg["risk_e8"]),
        f"{prefix}_cost_usd_oz": float(leg["cost_usd_oz"]),
        f"{prefix}_mfe_r": float(leg["mfe_r"]),
        f"{prefix}_mae_r": float(leg["mae_r"]),
        f"{prefix}_pnl_usd": float(leg["net_pnl_usd"]),
        f"{prefix}_pnl_usd_cost_1p5x": float(leg["net_pnl_usd_cost_1p5x"]),
        f"{prefix}_pnl_usd_cost_2x": float(leg["net_pnl_usd_cost_2x"]),
    }


def finalize_plan(
    meta: Mapping[str, Any],
    model: str,
    split_id: str,
    first: Mapping[str, Any] | None,
    second: Mapping[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    row = base_plan(meta, model, split_id)
    if first is None:
        row["unavailable_reason"] = reason
        row["plan_available"] = not reason.startswith("UNAVAILABLE::")
        row["plan_lineage_hash"] = canonical_hash([row["case_plan_id"], row["plan_available"], reason])
        return row
    row.update(leg_fields("first", first))
    row["traded"] = True
    row["first_attempt_stopped"] = bool(first["stopped"])
    row["first_entry_session"] = str(first["session"])
    row["final_exit_at_utc"] = ns_iso(int(first["exit_ns"]))
    legs = [first]
    if second is not None:
        row.update(leg_fields("second", second))
        row["flip_taken"] = True
        row["flip_success"] = float(second["net_pnl_usd"]) > 0.0
        row["final_exit_at_utc"] = ns_iso(int(second["exit_ns"]))
        legs.append(second)
    row["planned_loss_usd"] = float(sum(float(leg["planned_loss_usd"]) for leg in legs))
    for leg in legs:
        prefix = "continuation" if leg["side"] == "TREND" else "reversal"
        row[f"{prefix}_pnl_usd"] += float(leg["net_pnl_usd"])
        row[f"{prefix}_pnl_usd_cost_1p5x"] += float(leg["net_pnl_usd_cost_1p5x"])
        row[f"{prefix}_pnl_usd_cost_2x"] += float(leg["net_pnl_usd_cost_2x"])
    row["total_pnl_usd"] = float(sum(float(leg["net_pnl_usd"]) for leg in legs))
    row["total_pnl_usd_cost_1p5x"] = float(sum(float(leg["net_pnl_usd_cost_1p5x"]) for leg in legs))
    row["total_pnl_usd_cost_2x"] = float(sum(float(leg["net_pnl_usd_cost_2x"]) for leg in legs))
    row["case_net_r"] = row["total_pnl_usd"] / 50.0
    row["case_net_r_cost_1p5x"] = row["total_pnl_usd_cost_1p5x"] / 50.0
    row["case_net_r_cost_2x"] = row["total_pnl_usd_cost_2x"] / 50.0
    row["plan_lineage_hash"] = canonical_hash(
        [row["case_plan_id"], first["leg_lineage_hash"], second["leg_lineage_hash"] if second else None, row["total_pnl_usd"]]
    )
    return row


def simulate_case_plan(
    rows: Sequence[Mapping[str, Any]],
    model: str,
    split: tuple[str, float, float],
    frames: Mapping[str, Frame],
    tree: RangeTree,
    invalid_prefix: np.ndarray,
    implementation: str,
) -> dict[str, Any]:
    meta = rows[0]
    split_id, first_budget, reserve_budget = split
    sides = {"TREND"} if model == "CONTINUATION_ONLY_CONTROL" else {"REVERSAL"} if model == "REVERSAL_ONLY" else {"TREND", "REVERSAL"}
    trigger_row, preview, rejected = find_trigger(rows, sides, first_budget, frames, implementation)
    if trigger_row is None or preview is None:
        reason = "NO_EXECUTABLE_TRIGGER" if not rejected else "NO_EXECUTABLE_TRIGGER::" + ",".join(f"{key}={value}" for key, value in sorted(rejected.items()))
        return finalize_plan(meta, model, split_id, None, None, reason)
    deadline = parse_ns(str(meta["deadline_at_utc"]))
    first, failure = simulate_leg(preview, deadline, frames["M1"], tree, invalid_prefix, implementation)
    if first is None:
        return finalize_plan(meta, model, split_id, None, None, f"UNAVAILABLE::{failure}")
    second: dict[str, Any] | None = None
    if model == "BIDIRECTIONAL_ONE_FLIP" and bool(first["stopped"]):
        next_side = "REVERSAL" if first["side"] == "TREND" else "TREND"
        second_row, second_preview, _ = find_trigger(
            rows,
            {next_side},
            reserve_budget,
            frames,
            implementation,
            start_ns=int(first["exit_ns"]),
            initial_attempt_seen=True,
        )
        if second_row is not None and second_preview is not None:
            second, failure = simulate_leg(second_preview, deadline, frames["M1"], tree, invalid_prefix, implementation)
            if second is None:
                return finalize_plan(meta, model, split_id, None, None, f"UNAVAILABLE::SECOND_LEG::{failure}")
    return finalize_plan(meta, model, split_id, first, second, "")


def registry_rows() -> list[dict[str, Any]]:
    columns = ["pullback_id", "timeframe", "direction", "decision_date", "known_at_utc", "deadline_at_utc", "tape_status"]
    rows = pq.read_table(REGISTRY, columns=columns).to_pylist()
    if len(rows) != 8653 or len({str(row["pullback_id"]) for row in rows}) != 8653:
        raise ValueError("Complete population registry changed")
    return rows


def write_parquet(rows: Sequence[Mapping[str, Any]], schema: pa.Schema, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    table = pa.Table.from_pylist(list(rows), schema=schema)
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        row_group_size=8192,
    )
    temporary.replace(destination)


def materialize_plans(
    tape_path: Path,
    destination: Path,
    frames: Mapping[str, Frame],
    implementation: str,
    registry: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    m1 = frames["M1"]
    tree = RangeTree(m1.high_e8, m1.low_e8)
    invalid_prefix = np.concatenate(([0], np.cumsum(~m1.valid.astype(bool), dtype=np.int64)))
    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    trigger_counts: Counter[str] = Counter()
    unavailable: Counter[str] = Counter()
    for rows in iter_case_groups(tape_path):
        identity = str(rows[0]["pullback_id"])
        if identity in seen:
            raise ValueError(f"Duplicate case group: {identity}")
        seen.add(identity)
        if any(str(row["pullback_id"]) != identity for row in rows):
            raise ValueError("Mixed case group")
        indexes = [int(row["checkpoint_index"]) for row in rows]
        if indexes != sorted(indexes) or len(indexes) != len(set(indexes)):
            raise ValueError(f"Checkpoint ordering failure: {identity}")
        for model in ("CONTINUATION_ONLY_CONTROL", "REVERSAL_ONLY"):
            plan = simulate_case_plan(rows, model, FULL_SPLIT, frames, tree, invalid_prefix, implementation)
            plans.append(plan)
            trigger_counts[f"{model}::{bool(plan['traded'])}"] += 1
            unavailable[str(plan["unavailable_reason"] or "AVAILABLE")] += int(not bool(plan["plan_available"]))
        for split in SPLITS:
            plan = simulate_case_plan(rows, "BIDIRECTIONAL_ONE_FLIP", split, frames, tree, invalid_prefix, implementation)
            plans.append(plan)
            trigger_counts[f"BIDIRECTIONAL_ONE_FLIP::{split[0]}::{bool(plan['traded'])}"] += 1
            unavailable[str(plan["unavailable_reason"] or "AVAILABLE")] += int(not bool(plan["plan_available"]))
    missing = [row for row in registry if str(row["pullback_id"]) not in seen]
    if len(seen) != 8650 or len(missing) != 3:
        raise ValueError({"seen": len(seen), "missing": len(missing)})
    for meta in missing:
        for model, splits in (
            ("CONTINUATION_ONLY_CONTROL", (FULL_SPLIT,)),
            ("REVERSAL_ONLY", (FULL_SPLIT,)),
            ("BIDIRECTIONAL_ONE_FLIP", SPLITS),
        ):
            for split in splits:
                plan = finalize_plan(meta, model, split[0], None, None, "UNAVAILABLE::SEALED_CASE_TAPE_UNAVAILABLE")
                plans.append(plan)
                unavailable["UNAVAILABLE::SEALED_CASE_TAPE_UNAVAILABLE"] += 1
    plans.sort(key=lambda row: (row["decision_date"], row["timeframe"], row["pullback_id"], row["model_id"], row["risk_split_id"]))
    if len(plans) != 43_265 or len({row["case_plan_id"] for row in plans}) != 43_265:
        raise ValueError("Plan denominator or identities changed")
    if any(float(row.get("planned_loss_usd") or 0.0) > 50.0 + 1e-9 for row in plans):
        raise ValueError("Planned case loss exceeds $50")
    write_parquet(plans, PLAN_SCHEMA, destination)
    complete_hash = canonical_hash([[row[name] for name in PLAN_SCHEMA.names] for row in plans])
    result = {
        "implementation": implementation,
        "cases_with_tape": len(seen),
        "missing_cases": len(missing),
        "plan_rows": len(plans),
        "traded_plan_rows": sum(bool(row["traded"]) for row in plans),
        "flip_plan_rows": sum(bool(row["flip_taken"]) for row in plans),
        "unavailable_plan_rows": sum(not bool(row["plan_available"]) for row in plans),
        "trigger_counts": dict(sorted(trigger_counts.items())),
        "unavailable_reasons": dict(sorted((key, value) for key, value in unavailable.items() if value)),
        "complete_row_checksum": complete_hash,
        "output": file_record(destination),
    }
    del tree, invalid_prefix, plans
    gc.collect()
    return result


def profit_factor(values: Sequence[float]) -> float | None:
    positive = sum(value for value in values if value > 0)
    negative = -sum(value for value in values if value < 0)
    if negative == 0:
        # A finite sentinel keeps the sealed JSON standards-compliant while
        # preserving the ordering and gate meaning of an unbounded PF.
        return 1_000_000_000.0 if positive > 0 else None
    return positive / negative


def apply_overlap(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    trade_indexes = [
        index
        for index, row in enumerate(output)
        if bool(row.get("plan_available")) and bool(row.get("traded")) and row.get("first_entry_at_utc") and row.get("final_exit_at_utc")
    ]
    trade_indexes.sort(
        key=lambda index: (
            parse_ns(str(output[index]["first_entry_at_utc"])),
            str(output[index]["pullback_id"]),
        )
    )
    active_until: int | None = None
    for index, row in enumerate(output):
        row["_retained"] = False
        if not bool(row.get("plan_available")):
            row["_overlap"] = "UNAVAILABLE_TECHNICAL"
        elif not bool(row.get("traded")):
            row["_overlap"] = "NO_TRADE"
        else:
            row["_overlap"] = "PENDING"
    for index in trade_indexes:
        row = output[index]
        entry = parse_ns(str(row["first_entry_at_utc"]))
        exit_at = parse_ns(str(row["final_exit_at_utc"]))
        if exit_at < entry:
            raise ValueError("Case exits before entry")
        if active_until is not None and entry < active_until:
            row["_overlap"] = "SKIPPED_OVERLAP"
            continue
        row["_retained"] = True
        row["_overlap"] = "RETAINED"
        active_until = exit_at
    return output


def basic_selection_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    annotated = apply_overlap(rows)
    retained = [row for row in annotated if row["_retained"]]
    pnl = [float(row["total_pnl_usd"]) for row in retained]
    pnl_1p5 = [float(row["total_pnl_usd_cost_1p5x"]) for row in retained]
    return {
        "cases": len(retained),
        "dates": len({str(row["decision_date"]) for row in retained}),
        "expectancy_r": (sum(pnl) / 50.0 / len(retained)) if retained else None,
        "profit_factor": profit_factor(pnl),
        "cost_1p5x_expectancy_r": (sum(pnl_1p5) / 50.0 / len(retained)) if retained else None,
    }


def select_training_split(
    all_rows: Sequence[Mapping[str, Any]],
    timeframe: str,
    validation_start: str,
) -> tuple[str, dict[str, Any]]:
    support_cases, support_dates = SELECTION_SUPPORT[timeframe]
    records: list[dict[str, Any]] = []
    for split_id, _, _ in SPLITS:
        subset = [
            row
            for row in all_rows
            if row["timeframe"] == timeframe
            and row["model_id"] == "BIDIRECTIONAL_ONE_FLIP"
            and row["risk_split_id"] == split_id
            and str(row["decision_date"]) < validation_start
        ]
        metrics = basic_selection_metrics(subset)
        supported = metrics["cases"] >= support_cases and metrics["dates"] >= support_dates
        pf = metrics["profit_factor"]
        qualified = bool(
            supported
            and metrics["expectancy_r"] is not None
            and pf is not None
            and pf >= 1.05
            and metrics["cost_1p5x_expectancy_r"] is not None
            and metrics["cost_1p5x_expectancy_r"] > 0
        )
        records.append({"split_id": split_id, **metrics, "supported": supported, "qualified": qualified})
    qualified_rows = [row for row in records if row["qualified"]]
    supported_rows = [row for row in records if row["supported"]]
    pool = qualified_rows or supported_rows
    if pool:
        selected = sorted(pool, key=lambda row: (-float(row["expectancy_r"]), str(row["split_id"])))[0]
        disposition = "QUALIFIED_BEST" if qualified_rows else "SUPPORTED_FALLBACK_BEST"
        split_id = str(selected["split_id"])
    else:
        disposition = "DEFAULT_NO_SUPPORTED_TRAINING_SPLIT"
        split_id = "SPLIT_25_25"
    return split_id, {"validation_start": validation_start, "disposition": disposition, "selected": split_id, "splits": records}


def fold_for_date(value: str) -> int | None:
    for fold, start, end in FOLDS:
        if start <= value <= end:
            return fold
    return None


def build_oof_population(all_rows: Sequence[Mapping[str, Any]], timeframe: str, model: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_rows: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    for fold, start, end in FOLDS:
        if model == "BIDIRECTIONAL_ONE_FLIP":
            split_id, detail = select_training_split(all_rows, timeframe, start)
        else:
            split_id = "FULL_50"
            detail = {"validation_start": start, "disposition": "FIXED_POLICY_NO_SELECTION", "selected": split_id, "splits": []}
        detail = {"fold": fold, **detail}
        selections.append(detail)
        for row in all_rows:
            if row["timeframe"] != timeframe or row["model_id"] != model or row["risk_split_id"] != split_id:
                continue
            if start <= str(row["decision_date"]) <= end:
                item = dict(row)
                item["_fold"] = fold
                item["_selected_split"] = split_id
                selected_rows.append(item)
    if len({str(row["pullback_id"]) for row in selected_rows}) != len(selected_rows):
        raise ValueError(f"Duplicate OOF case selection: {timeframe} {model}")
    return apply_overlap(selected_rows), selections


def group_sums(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
    values: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        values[str(row[key])] += float(row["total_pnl_usd"])
    return {name: rounded(value, 6) for name, value in sorted(values.items())}


def positive_share(values: Mapping[str, float]) -> float:
    positive = [float(value) for value in values.values() if float(value) > 0]
    return max(positive) / sum(positive) if positive else 1.0


def maximum_drawdown(values: Sequence[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return drawdown


def clustered_bootstrap(rows: Sequence[Mapping[str, Any]], timeframe: str, model: str) -> dict[str, Any]:
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row["decision_date"])].append(float(row["case_net_r"]))
    keys = sorted(grouped)
    if not keys:
        return {"ci95_low": None, "ci95_high": None, "one_sided_p": None, "clusters": 0, "resamples": 5000}
    seed_material = hashlib.sha256(f"{SEED}|{timeframe}|{model}".encode("utf-8")).digest()
    rng = np.random.default_rng(int.from_bytes(seed_material[:8], "little"))
    samples = np.empty(5000, dtype=np.float64)
    arrays = [np.asarray(grouped[key], dtype=np.float64) for key in keys]
    for index in range(5000):
        picks = rng.integers(0, len(arrays), size=len(arrays))
        total = 0.0
        count = 0
        for pick in picks:
            values = arrays[int(pick)]
            total += float(values.sum())
            count += len(values)
        samples[index] = total / count
    return {
        "ci95_low": rounded(float(np.quantile(samples, 0.025))),
        "ci95_high": rounded(float(np.quantile(samples, 0.975))),
        "one_sided_p": rounded((1 + int(np.sum(samples <= 0.0))) / 5001.0),
        "clusters": len(keys),
        "resamples": 5000,
    }


def fixed_split_neighbours(all_rows: Sequence[Mapping[str, Any]], timeframe: str) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    for split_id, _, _ in SPLITS:
        subset = [
            dict(row)
            for row in all_rows
            if row["timeframe"] == timeframe
            and row["model_id"] == "BIDIRECTIONAL_ONE_FLIP"
            and row["risk_split_id"] == split_id
            and fold_for_date(str(row["decision_date"])) is not None
        ]
        retained = [row for row in apply_overlap(subset) if row["_retained"]]
        expectancy = sum(float(row["case_net_r"]) for row in retained) / len(retained) if retained else None
        details.append({"split_id": split_id, "cases": len(retained), "expectancy_r": rounded(expectancy), "positive": bool(expectancy is not None and expectancy > 0)})
    fraction = sum(row["positive"] for row in details) / len(details)
    return {"positive_fraction": fraction, "splits": details}


def candidate_metrics(
    annotated: Sequence[Mapping[str, Any]],
    timeframe: str,
    model: str,
    oracle: Mapping[str, float | None],
    neighbour: Mapping[str, Any] | None,
) -> dict[str, Any]:
    retained = sorted(
        [row for row in annotated if row["_retained"]],
        key=lambda row: (parse_ns(str(row["first_entry_at_utc"])), str(row["pullback_id"])),
    )
    pnl = [float(row["total_pnl_usd"]) for row in retained]
    pnl_1p5 = [float(row["total_pnl_usd_cost_1p5x"]) for row in retained]
    pnl_2 = [float(row["total_pnl_usd_cost_2x"]) for row in retained]
    case_r = [float(row["case_net_r"]) for row in retained]
    dates = {str(row["decision_date"]) for row in retained}
    years = group_sums([{**row, "calendar_year": str(row["decision_date"])[:4]} for row in retained], "calendar_year")
    folds = group_sums(retained, "_fold")
    sessions = group_sums([{**row, "entry_session_key": str(row.get("first_entry_session") or "UNKNOWN")} for row in retained], "entry_session_key")
    bootstrap = clustered_bootstrap(retained, timeframe, model)
    oracle_values = [oracle.get(str(row["pullback_id"])) for row in retained]
    matched_oracle = [float(value) for value in oracle_values if value is not None and math.isfinite(float(value))]
    oracle_usd = 50.0 * sum(matched_oracle)
    first_mfe = [float(row["first_mfe_r"]) for row in retained if row.get("first_mfe_r") is not None]
    first_mae = [float(row["first_mae_r"]) for row in retained if row.get("first_mae_r") is not None]
    second_mfe = [float(row["second_mfe_r"]) for row in retained if row.get("second_mfe_r") is not None]
    second_mae = [float(row["second_mae_r"]) for row in retained if row.get("second_mae_r") is not None]
    total = sum(pnl)
    total_r = total / 50.0
    wins = [value / 50.0 for value in pnl if value > 0]
    losses = [value / 50.0 for value in pnl if value < 0]
    legs = len(retained) + sum(bool(row["flip_taken"]) for row in retained)
    metric = {
        "candidate_id": f"{timeframe}::{model}",
        "timeframe": timeframe,
        "model_id": model,
        "validation_population_rows": len(annotated),
        "unavailable_rows": sum(not bool(row["plan_available"]) for row in annotated),
        "no_trade_rows": sum(bool(row["plan_available"]) and not bool(row["traded"]) for row in annotated),
        "overlap_skips": sum(row["_overlap"] == "SKIPPED_OVERLAP" for row in annotated),
        "support_cases": len(retained),
        "support_dates": len(dates),
        "cases_per_month": rounded(len(retained) / MONTHS),
        "legs": legs,
        "legs_per_month": rounded(legs / MONTHS),
        "win_rate": rounded(sum(value > 0 for value in pnl) / len(pnl) if pnl else None),
        "average_win_r": rounded(float(np.mean(wins)) if wins else None),
        "average_loss_r": rounded(float(np.mean(losses)) if losses else None),
        "net_expectancy_r": rounded(float(np.mean(case_r)) if case_r else None),
        "profit_factor": rounded(profit_factor(pnl)),
        "net_r": rounded(total_r),
        "net_pnl_usd_at_50_case_risk": rounded(total, 6),
        "average_monthly_pnl_usd_at_50_case_risk": rounded(total / MONTHS, 6),
        "r_per_month": rounded(total_r / MONTHS),
        "pnl_usd_per_month_at_1pct_case_risk_linear": rounded(total_r * 100.0 / MONTHS, 6),
        "net_expectancy_r_cost_1p5x": rounded(sum(pnl_1p5) / 50.0 / len(retained) if retained else None),
        "net_expectancy_r_cost_2x": rounded(sum(pnl_2) / 50.0 / len(retained) if retained else None),
        "maximum_drawdown_usd_at_50": rounded(maximum_drawdown(pnl), 6),
        "maximum_drawdown_pct_of_10000_at_50": rounded(maximum_drawdown(pnl) / 100.0),
        "maximum_drawdown_pct_of_10000_at_1pct_linear": rounded(maximum_drawdown(pnl) / 50.0),
        "continuation_pnl_usd": rounded(sum(float(row["continuation_pnl_usd"]) for row in retained), 6),
        "reversal_pnl_usd": rounded(sum(float(row["reversal_pnl_usd"]) for row in retained), 6),
        "first_attempt_stop_rate": rounded(sum(bool(row["first_attempt_stopped"]) for row in retained) / len(retained) if retained else None),
        "flip_frequency": rounded(sum(bool(row["flip_taken"]) for row in retained) / len(retained) if retained else None),
        "successful_flip_rate": rounded(sum(bool(row["flip_success"]) for row in retained) / sum(bool(row["flip_taken"]) for row in retained) if sum(bool(row["flip_taken"]) for row in retained) else None),
        "average_first_mfe_r": rounded(float(np.mean(first_mfe)) if first_mfe else None),
        "average_first_mae_r": rounded(float(np.mean(first_mae)) if first_mae else None),
        "average_second_mfe_r": rounded(float(np.mean(second_mfe)) if second_mfe else None),
        "average_second_mae_r": rounded(float(np.mean(second_mae)) if second_mae else None),
        "annual_pnl_usd": years,
        "fold_pnl_usd": folds,
        "entry_session_pnl_usd": sessions,
        "positive_folds": sum(value > 0 for value in folds.values()),
        "positive_years": sum(value > 0 for value in years.values()),
        "maximum_positive_year_share": rounded(positive_share(years)),
        "maximum_positive_session_share": rounded(positive_share(sessions)),
        "bootstrap": bootstrap,
        "fixed_split_neighbours": neighbour,
        "oracle_matched_cases": len(matched_oracle),
        "frozen_behavioural_oracle_usd": rounded(oracle_usd, 6),
        "frozen_behavioural_oracle_capture_pct": rounded(100.0 * total / oracle_usd if oracle_usd else None),
    }
    return metric


def holm_adjust(metrics: Sequence[dict[str, Any]]) -> None:
    # The family is frozen at three tests. Unsupported tests enter as p=1;
    # they may not silently reduce the multiplicity penalty on the others.
    ordered = sorted(metrics, key=lambda metric: (float(metric["bootstrap"]["one_sided_p"] if metric["bootstrap"]["one_sided_p"] is not None else 1.0), metric["model_id"]))
    running = 0.0
    adjusted: dict[str, float] = {}
    total = len(ordered)
    for index, metric in enumerate(ordered):
        raw = float(metric["bootstrap"]["one_sided_p"] if metric["bootstrap"]["one_sided_p"] is not None else 1.0)
        candidate = min(1.0, (total - index) * raw)
        running = max(running, candidate)
        adjusted[metric["candidate_id"]] = running
    for metric in metrics:
        metric["holm_adjusted_p"] = rounded(adjusted.get(metric["candidate_id"]))


def apply_gates(metric: dict[str, Any]) -> None:
    support_cases, support_dates = FINAL_SUPPORT[str(metric["timeframe"])]
    neighbour = metric.get("fixed_split_neighbours")
    neighbour_ok = True if metric["model_id"] != "BIDIRECTIONAL_ONE_FLIP" else bool(neighbour and float(neighbour["positive_fraction"]) >= 2.0 / 3.0)
    gates = {
        "support": metric["support_cases"] >= support_cases and metric["support_dates"] >= support_dates,
        "net_expectancy_gt_zero": metric["net_expectancy_r"] is not None and metric["net_expectancy_r"] > 0,
        "profit_factor_gte_1p10": metric["profit_factor"] is not None and metric["profit_factor"] >= 1.10,
        "cluster_ci95_low_gt_zero": metric["bootstrap"]["ci95_low"] is not None and metric["bootstrap"]["ci95_low"] > 0,
        "holm_p_lte_0p10": metric["holm_adjusted_p"] is not None and metric["holm_adjusted_p"] <= 0.10,
        "cost_1p5x_expectancy_gt_zero": metric["net_expectancy_r_cost_1p5x"] is not None and metric["net_expectancy_r_cost_1p5x"] > 0,
        "positive_validation_folds_gte_3": metric["positive_folds"] >= 3,
        "positive_calendar_years_gte_2": metric["positive_years"] >= 2,
        "maximum_positive_year_share_lte_0p70": metric["maximum_positive_year_share"] <= 0.70,
        "maximum_positive_session_share_lte_0p70": metric["maximum_positive_session_share"] <= 0.70,
        "maximum_drawdown_pct_lte_15": metric["maximum_drawdown_pct_of_10000_at_50"] <= 15.0,
        "bidirectional_positive_fixed_split_fraction_gte_2_of_3": neighbour_ok,
    }
    metric["gates"] = gates
    metric["failed_gates"] = [name for name, passed in gates.items() if not passed]
    metric["economic_gate_pass"] = all(gates.values())
    metric["can_responsibly_reach_10r_per_month_at_1pct"] = bool(
        metric["economic_gate_pass"]
        and metric["r_per_month"] is not None
        and metric["r_per_month"] >= 10.0
        and metric["maximum_drawdown_pct_of_10000_at_1pct_linear"] <= 15.0
    )


def oof_record(row: Mapping[str, Any], timeframe: str, model: str) -> dict[str, Any]:
    return {
        "oof_id": canonical_hash([row["pullback_id"], timeframe, model, row["_fold"], row["_selected_split"]]),
        "pullback_id": str(row["pullback_id"]),
        "timeframe": timeframe,
        "model_id": model,
        "fold": int(row["_fold"]),
        "selected_risk_split_id": str(row["_selected_split"]),
        "decision_date": str(row["decision_date"]),
        "first_entry_at_utc": row.get("first_entry_at_utc"),
        "final_exit_at_utc": row.get("final_exit_at_utc"),
        "entry_session": row.get("first_entry_session"),
        "traded": bool(row["traded"]),
        "retained_after_overlap": bool(row["_retained"]),
        "overlap_disposition": str(row["_overlap"]),
        "case_net_r": row.get("case_net_r"),
        "case_net_r_cost_1p5x": row.get("case_net_r_cost_1p5x"),
        "case_net_r_cost_2x": row.get("case_net_r_cost_2x"),
        "total_pnl_usd": row.get("total_pnl_usd"),
        "total_pnl_usd_cost_1p5x": row.get("total_pnl_usd_cost_1p5x"),
        "total_pnl_usd_cost_2x": row.get("total_pnl_usd_cost_2x"),
        "first_side": row.get("first_side"),
        "first_attempt_stopped": bool(row.get("first_attempt_stopped")),
        "flip_taken": bool(row.get("flip_taken")),
        "flip_success": bool(row.get("flip_success")),
        "continuation_pnl_usd": float(row.get("continuation_pnl_usd") or 0.0),
        "reversal_pnl_usd": float(row.get("reversal_pnl_usd") or 0.0),
        "first_mfe_r": row.get("first_mfe_r"),
        "first_mae_r": row.get("first_mae_r"),
        "second_mfe_r": row.get("second_mfe_r"),
        "second_mae_r": row.get("second_mae_r"),
        "plan_lineage_hash": str(row["plan_lineage_hash"]),
    }


def evaluate(plan_path: Path, oracle: Mapping[str, float | None]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = pq.read_table(plan_path).to_pylist()
    if len(rows) != 43_265:
        raise ValueError("Plan population changed before evaluation")
    metrics: list[dict[str, Any]] = []
    oof_rows: list[dict[str, Any]] = []
    split_selections: dict[str, Any] = {}
    for timeframe in ("M15", "H1", "H4"):
        timeframe_metrics: list[dict[str, Any]] = []
        for model in MODELS:
            annotated, selections = build_oof_population(rows, timeframe, model)
            key = f"{timeframe}::{model}"
            split_selections[key] = selections
            neighbour = fixed_split_neighbours(rows, timeframe) if model == "BIDIRECTIONAL_ONE_FLIP" else None
            metric = candidate_metrics(annotated, timeframe, model, oracle, neighbour)
            timeframe_metrics.append(metric)
            oof_rows.extend(oof_record(row, timeframe, model) for row in annotated)
        holm_adjust(timeframe_metrics)
        for metric in timeframe_metrics:
            apply_gates(metric)
        passing = sorted(
            [metric for metric in timeframe_metrics if metric["economic_gate_pass"]],
            key=lambda metric: (-float(metric["net_expectancy_r"]), -float(metric["profit_factor"]), -int(metric["support_cases"]), str(metric["model_id"])),
        )
        advanced = {metric["candidate_id"] for metric in passing[:2]}
        for metric in timeframe_metrics:
            metric["advanced_within_candidate_limit"] = metric["candidate_id"] in advanced
            metric["verdict"] = "PASS_ADVANCED" if metric["candidate_id"] in advanced else "PASS_NOT_ADVANCED_CANDIDATE_LIMIT" if metric["economic_gate_pass"] else "REJECT"
            metrics.append(metric)
    oof_rows.sort(key=lambda row: (row["decision_date"], row["timeframe"], row["pullback_id"], row["model_id"]))
    advanced_candidates = [metric["candidate_id"] for metric in metrics if metric["advanced_within_candidate_limit"]]
    result = {
        "version": "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_V1_DEVELOPMENT_RESULT_1_0",
        "verdict": "PASS_DEVELOPMENT_CANDIDATES" if advanced_candidates else "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE",
        "population": {"cases": 8653, "available_tapes": 8650, "plan_rows": 43_265, "validation_months": MONTHS},
        "candidate_metrics": metrics,
        "split_selections": split_selections,
        "advanced_candidates": advanced_candidates,
        "forward_disposition": {
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "status": "REQUIRED_AFTER_DEVELOPMENT_FREEZE" if advanced_candidates else "LOCKED_ZERO_DEVELOPMENT_PASS",
        },
        "prospective_ledger_initialized": False,
        "paid_acquisition_usd": 0.0,
    }
    return result, oof_rows


def load_oracle_after_decisions() -> dict[str, float | None]:
    rows = pq.read_table(ATLAS, columns=["pullback_id", "oracle_r"]).to_pylist()
    if len(rows) != 8653:
        raise ValueError("Oracle population changed")
    return {str(row["pullback_id"]): finite(row.get("oracle_r")) for row in rows}


def fmt(value: Any, places: int = 3) -> str:
    number = finite(value)
    if number is None:
        return "n/a"
    if math.isinf(number):
        return "inf"
    return f"{number:.{places}f}"


def render_report(result: Mapping[str, Any], materialization: Mapping[str, Any]) -> str:
    lines = [
        "# Gold Bidirectional Auction-Resolution Edge Discovery V1",
        "",
        f"Development verdict: **{result['verdict']}**",
        "",
        "The study compared the continuation-only control, reversal-only resolution, and a bidirectional one-flip policy on the same sealed 2021–2024 pullback population. Rules and risk splits were frozen before the price paths were opened. 2025 and 2026 remained locked throughout development.",
        "",
        "## Development economics",
        "",
        "| Timeframe | Model | Cases | Cases/mo | Win % | Exp R | PF | Net R | $/mo at $50 | DD $ | CI95 low | Flips | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for metric in result["candidate_metrics"]:
        lines.append(
            "| {tf} | {model} | {cases} | {cpm} | {win} | {exp} | {pf} | {net} | {monthly} | {dd} | {ci} | {flip} | {verdict} |".format(
                tf=metric["timeframe"],
                model=metric["model_id"],
                cases=metric["support_cases"],
                cpm=fmt(metric["cases_per_month"], 2),
                win=fmt((metric["win_rate"] or 0) * 100, 1) if metric["win_rate"] is not None else "n/a",
                exp=fmt(metric["net_expectancy_r"], 4),
                pf=fmt(metric["profit_factor"], 3),
                net=fmt(metric["net_r"], 2),
                monthly=fmt(metric["average_monthly_pnl_usd_at_50_case_risk"], 2),
                dd=fmt(metric["maximum_drawdown_usd_at_50"], 2),
                ci=fmt(metric["bootstrap"]["ci95_low"], 4),
                flip=fmt((metric["flip_frequency"] or 0) * 100, 1) if metric["flip_frequency"] is not None else "n/a",
                verdict=metric["verdict"],
            )
        )
    lines.extend(["", "## Contribution and gate findings", ""])
    for metric in result["candidate_metrics"]:
        lines.append(
            f"- `{metric['candidate_id']}`: continuation ${fmt(metric['continuation_pnl_usd'], 2)}, reversal ${fmt(metric['reversal_pnl_usd'], 2)}, "
            f"1.5x-cost expectancy {fmt(metric['net_expectancy_r_cost_1p5x'], 4)}R, successful flips {fmt((metric['successful_flip_rate'] or 0) * 100, 1) if metric['successful_flip_rate'] is not None else 'n/a'}%, "
            f"oracle captured {fmt(metric['frozen_behavioural_oracle_capture_pct'], 3)}%; failed gates: {', '.join(metric['failed_gates']) or 'none'}.")
    lines.extend(
        [
            "",
            "## Integrity and disposition",
            "",
            f"- Population: 8,653 cases; 8,650 certified tapes; 43,265 frozen case-policy plans.",
            f"- Primary/reference plan payloads byte-identical: {str(materialization['byte_identical']).lower()}.",
            f"- Advanced development candidates: {', '.join(result['advanced_candidates']) if result['advanced_candidates'] else 'none'}.",
            f"- 2025 accessed: false. 2026 accessed: false. Paid acquisition: $0.00.",
            "- The reported oracle is the previously sealed original-direction visual-pivot ceiling; it is not a tradable or two-sided oracle.",
            "",
        ]
    )
    if result["advanced_candidates"]:
        lines.append("Development candidates passed and must be frozen before the separately controlled exposed-period application.")
    else:
        lines.append("Because no development candidate passed every gate, the forward periods remain locked and no prospective ledger is initialized.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    audit = preflight()
    proof = synthetic_proof()
    preoutcome = seal_preoutcome(audit, proof)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        OPENING,
        {
            "version": "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_V1_DEVELOPMENT_OPENING_1_0",
            "status": "OPENED_ONCE_AFTER_PREOUTCOME_FREEZE",
            "opened_at_utc": utc_now(),
            "preoutcome_freeze": file_record(PREOUTCOME_FREEZE),
            "source_opening_count_for_branch": 1,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    frames, price_diagnostics = load_price()
    registry = registry_rows()
    primary = materialize_plans(PRIMARY_TAPE, PRIMARY_PLANS, frames, "primary", registry)
    reference = materialize_plans(REFERENCE_TAPE, REFERENCE_PLANS, frames, "reference", registry)
    compare_fields = (
        "cases_with_tape",
        "missing_cases",
        "plan_rows",
        "traded_plan_rows",
        "flip_plan_rows",
        "unavailable_plan_rows",
        "trigger_counts",
        "unavailable_reasons",
        "complete_row_checksum",
    )
    differences = [name for name in compare_fields if primary[name] != reference[name]]
    byte_identical = sha256_file(PRIMARY_PLANS) == sha256_file(REFERENCE_PLANS)
    status = "PASS_BIDIRECTIONAL_PLAN_MATERIALIZATION" if not differences and byte_identical else "FAIL_BIDIRECTIONAL_PLAN_REPRODUCTION"
    materialization = {
        "version": "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_V1_MATERIALIZATION_CERT_1_0",
        "status": status,
        "certified_at_utc": utc_now(),
        "primary": primary,
        "reference": reference,
        "differences": differences,
        "byte_identical": byte_identical,
        "price_diagnostics": price_diagnostics,
        "preoutcome_freeze": file_record(PREOUTCOME_FREEZE),
        "opening": file_record(OPENING),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(MATERIALIZATION_CERT, materialization)
    write_json_exclusive(
        MATERIALIZATION_FREEZE,
        {
            "version": "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_V1_MATERIALIZATION_FREEZE_1_0",
            "status": status,
            "sealed_at_utc": utc_now(),
            "certification": file_record(MATERIALIZATION_CERT),
            "primary_plans": file_record(PRIMARY_PLANS),
            "reference_plans": file_record(REFERENCE_PLANS),
            "byte_identical": byte_identical,
            "development_outcomes_accessed": True,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    if status != "PASS_BIDIRECTIONAL_PLAN_MATERIALIZATION":
        raise RuntimeError(status)
    del frames
    gc.collect()

    oracle = load_oracle_after_decisions()
    primary_result, primary_oof = evaluate(PRIMARY_PLANS, oracle)
    reference_result, reference_oof = evaluate(REFERENCE_PLANS, oracle)
    if canonical_json(primary_result) != canonical_json(reference_result):
        raise RuntimeError("FAIL_DEVELOPMENT_RESULT_REPRODUCTION")
    write_parquet(primary_oof, OOF_SCHEMA, PRIMARY_OOF)
    write_parquet(reference_oof, OOF_SCHEMA, REFERENCE_OOF)
    if sha256_file(PRIMARY_OOF) != sha256_file(REFERENCE_OOF):
        raise RuntimeError("FAIL_OOF_PAYLOAD_REPRODUCTION")
    write_json_exclusive(PRIMARY_RESULTS, primary_result)
    write_json_exclusive(REFERENCE_RESULTS, reference_result)
    if sha256_file(PRIMARY_RESULTS) != sha256_file(REFERENCE_RESULTS):
        raise RuntimeError("FAIL_RESULT_BYTE_REPRODUCTION")
    development = {
        **primary_result,
        "completed_at_utc": utc_now(),
        "reproduction": {
            "primary_results": file_record(PRIMARY_RESULTS),
            "reference_results": file_record(REFERENCE_RESULTS),
            "result_bytes_identical": True,
            "primary_oof": file_record(PRIMARY_OOF),
            "reference_oof": file_record(REFERENCE_OOF),
            "oof_bytes_identical": True,
        },
        "materialization": file_record(MATERIALIZATION_FREEZE),
    }
    write_json_exclusive(DEVELOPMENT_RESULTS, development)
    write_json_exclusive(
        DEVELOPMENT_FREEZE,
        {
            "version": "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_V1_DEVELOPMENT_FREEZE_1_0",
            "status": development["verdict"],
            "sealed_at_utc": utc_now(),
            "preoutcome": file_record(PREOUTCOME_FREEZE),
            "materialization": file_record(MATERIALIZATION_FREEZE),
            "development_results": file_record(DEVELOPMENT_RESULTS),
            "advanced_candidates": development["advanced_candidates"],
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    REPORT.write_text(render_report(development, materialization), encoding="utf-8", newline="\n")
    if development["advanced_candidates"]:
        print(canonical_json({"status": "PASS_DEVELOPMENT_CANDIDATES_FORWARD_APPLICATION_REQUIRED", "advanced_candidates": development["advanced_candidates"], "results": file_record(DEVELOPMENT_RESULTS)}))
        return
    final = {
        **development,
        "final_verdict": "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE",
        "forward_disposition": {
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "status": "LOCKED_ZERO_DEVELOPMENT_PASS",
        },
        "prospective_ledger_initialized": False,
    }
    write_json_exclusive(FINAL_RESULTS, final)
    write_json_exclusive(
        FINAL_FREEZE,
        {
            "version": "GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_V1_FINAL_FREEZE_1_0",
            "status": "SEALED_FINAL_REJECTION",
            "sealed_at_utc": utc_now(),
            "verdict": final["final_verdict"],
            "contract": file_record(CONTRACT),
            "protocol": file_record(PROTOCOL),
            "preoutcome": file_record(PREOUTCOME_FREEZE),
            "materialization": file_record(MATERIALIZATION_FREEZE),
            "development": file_record(DEVELOPMENT_FREEZE),
            "final_results": file_record(FINAL_RESULTS),
            "report": file_record(REPORT),
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "prospective_ledger_initialized": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    print(canonical_json({"status": "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE", "advanced_candidates": [], "results": file_record(FINAL_RESULTS)}))


if __name__ == "__main__":
    main()
