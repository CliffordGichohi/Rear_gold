from __future__ import annotations

import bisect
import gc
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import run_gold_h4_continuation_tradable_ceiling_v1 as ceiling
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


CONTRACT = ROOT / "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_CONTRACT_V1.md"
PROTOCOL = ROOT / "research_manifests/gold_h4_liquidity_target_capture_falsification_v1_protocol.json"
IMPLEMENTATION = Path(__file__).resolve()
TESTS = ROOT / "tests/test_gold_h4_liquidity_target_capture_falsification_v1.py"
PREDECESSOR_FINAL_SEAL = ROOT / "research_manifests/gold_h4_continuation_tradable_ceiling_v1_final_freeze.json"
PREDECESSOR_CASES_PRIMARY = ROOT / "research_artifacts/gold_h4_continuation_tradable_ceiling_v1/primary_h4_ceiling_cases.parquet"
PREDECESSOR_CASES_REFERENCE = ROOT / "research_artifacts/gold_h4_continuation_tradable_ceiling_v1/reference_h4_ceiling_cases.parquet"

PREPATH_FREEZE = ROOT / "research_manifests/gold_h4_liquidity_target_capture_falsification_v1_prepath_freeze.json"
FINAL_FREEZE = ROOT / "research_manifests/gold_h4_liquidity_target_capture_falsification_v1_final_freeze.json"
OUTPUT = ROOT / "research_artifacts/gold_h4_liquidity_target_capture_falsification_v1"
OPENING = OUTPUT / "post_target_path_opening.json"
PRIMARY_CASES = OUTPUT / "primary_policy_cases.parquet"
REFERENCE_CASES = OUTPUT / "reference_policy_cases.parquet"
PRIMARY_RESULTS = OUTPUT / "primary_results.json"
REFERENCE_RESULTS = OUTPUT / "reference_results.json"
CERTIFICATION = OUTPUT / "reproduction_certification.json"
FINAL_RESULT = OUTPUT / "final_result.json"
REPORT = ROOT / "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_REPORT.md"

POLICIES: tuple[tuple[str, float], ...] = (
    ("TARGET_TAKE_25_RUN_75", 0.25),
    ("TARGET_TAKE_50_RUN_50", 0.50),
    ("TARGET_TAKE_75_RUN_25", 0.75),
)
CONTROL = "CONTROL_FULL_CLOSE"
ALL_POLICIES = (CONTROL,) + tuple(item[0] for item in POLICIES)
MONTHS = 39
RISK_USD = 50.0
ACCOUNT_USD = 10_000.0
TARGET_R_MONTH = 10.0
BOOTSTRAPS = 5_000
SEED = 884_271
INFINITY_NS = np.iinfo(np.int64).max


CASE_SCHEMA = pa.schema(
    [
        pa.field("row_id", pa.string(), False),
        pa.field("pullback_id", pa.string(), False),
        pa.field("policy_id", pa.string(), False),
        pa.field("fold", pa.int16(), False),
        pa.field("decision_date", pa.string(), False),
        pa.field("entry_session", pa.string(), False),
        pa.field("direction", pa.string(), False),
        pa.field("entry_at_utc", pa.string(), False),
        pa.field("final_exit_at_utc", pa.string(), False),
        pa.field("deadline_at_utc", pa.string(), False),
        pa.field("original_exit_reason", pa.string(), False),
        pa.field("overlap_disposition", pa.string(), False),
        pa.field("retained_after_overlap", pa.bool_(), False),
        pa.field("whole_ounces", pa.int64(), False),
        pa.field("take_ounces", pa.int64(), False),
        pa.field("runner_ounces", pa.int64(), False),
        pa.field("target_first", pa.bool_(), False),
        pa.field("management_activated", pa.bool_(), False),
        pa.field("target_touch_at_utc", pa.string()),
        pa.field("atr14_m15_e8", pa.int64()),
        pa.field("next_liquidity_timeframe", pa.string()),
        pa.field("next_liquidity_e8", pa.int64()),
        pa.field("next_liquidity_distance_r", pa.float64()),
        pa.field("target_state", pa.string(), False),
        pa.field("target_state_sequence", pa.string(), False),
        pa.field("acceptance_at_utc", pa.string()),
        pa.field("runner_exit_reason", pa.string(), False),
        pa.field("runner_exit_at_utc", pa.string()),
        pa.field("gross_pnl_usd", pa.float64(), False),
        pa.field("net_pnl_usd", pa.float64(), False),
        pa.field("net_pnl_usd_cost_1p5x", pa.float64(), False),
        pa.field("net_pnl_usd_cost_2x", pa.float64(), False),
        pa.field("net_r", pa.float64(), False),
        pa.field("net_r_cost_1p5x", pa.float64(), False),
        pa.field("net_r_cost_2x", pa.float64(), False),
        pa.field("post_overlap_pnl_usd", pa.float64(), False),
        pa.field("post_overlap_pnl_usd_cost_1p5x", pa.float64(), False),
        pa.field("post_overlap_pnl_usd_cost_2x", pa.float64(), False),
        pa.field("post_overlap_r", pa.float64(), False),
        pa.field("incremental_post_overlap_r_vs_control", pa.float64(), False),
        pa.field("target_only_perfect_fixed_overlap_usd", pa.float64(), False),
        pa.field("target_only_perfect_fixed_overlap_usd_cost_1p5x", pa.float64(), False),
        pa.field("plan_lineage_hash", pa.string(), False),
        pa.field("row_lineage_hash", pa.string(), False),
    ]
)


@dataclass(frozen=True, slots=True)
class Pivot:
    pivot_id: str
    timeframe: str
    kind: str
    price_e8: int
    known_ns: int
    broken_ns: int


def rounded(value: Any, places: int = 10) -> float | None:
    if value is None:
        return None
    result = float(value)
    return round(result, places) if math.isfinite(result) else None


def verify_record(record: Mapping[str, Any]) -> Path:
    path = ROOT / str(record["path"])
    if not path.exists() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != str(record["sha256"]):
        raise ValueError(f"Sealed record changed: {record}")
    return path


def preflight() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_2021_2024_POST_TARGET_PATH_ACCESS" or protocol.get("post_target_paths_accessed") is not False:
        raise ValueError("Target-capture protocol is not frozen")
    ceiling.verify_predecessor_seal()
    prior = json.loads(PREDECESSOR_FINAL_SEAL.read_text(encoding="utf-8"))
    if prior.get("status") != "SEALED_FINAL_AUDIT_UNDER_AMENDMENT_A" or prior.get("verdict") != "UPPER_BOUND_CAPACITY_PRESENT_NOT_DEMONSTRATED":
        raise ValueError("Tradable-ceiling predecessor verdict changed")
    if prior.get("calendar_2025_values_accessed") is not False or prior.get("calendar_2026_values_accessed") is not False:
        raise ValueError("Forward lock changed")
    for key in (
        "contract", "protocol", "original_prepath_freeze", "original_failure", "amendment_a",
        "recovery_freeze", "final_result", "certification", "report",
    ):
        verify_record(prior[key])
    for path, expected, label in (
        (ceiling.PRIMARY_PLANS, ceiling.EXPECTED["primary_plans"], "primary plans"),
        (ceiling.REFERENCE_PLANS, ceiling.EXPECTED["reference_plans"], "reference plans"),
        (ceiling.PRIMARY_OOF, ceiling.EXPECTED["primary_oof"], "primary OOF"),
        (ceiling.REFERENCE_OOF, ceiling.EXPECTED["reference_oof"], "reference OOF"),
        (ceiling.RAW_PRICE, ceiling.EXPECTED["raw_price"], "raw price"),
    ):
        ceiling.verify_record(path, expected, label)
    if sha256_file(PREDECESSOR_CASES_PRIMARY) != sha256_file(PREDECESSOR_CASES_REFERENCE):
        raise ValueError("Predecessor case payloads differ")
    if sha256_file(PREDECESSOR_CASES_PRIMARY) != "03a9717aa18fa3bd464b91ac9baea891b6ba685bb043fb976118d6026f1f20ee":
        raise ValueError("Predecessor matched-case payload changed")
    for required in (CONTRACT, PROTOCOL, IMPLEMENTATION, TESTS):
        if not required.exists():
            raise FileNotFoundError(required)
    if any(path.exists() for path in (PREPATH_FREEZE, FINAL_FREEZE, OUTPUT, FINAL_RESULT, REPORT)):
        raise FileExistsError("Target-capture branch already exists")
    return {"protocol": protocol, "predecessor": prior}


def write_parquet(rows: Sequence[Mapping[str, Any]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    table = pa.Table.from_pylist(list(rows), schema=CASE_SCHEMA)
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        row_group_size=1024,
    )
    temporary.replace(destination)


def frame_index(values: Sequence[int], target: int, implementation: str, side: str = "left") -> int:
    if implementation == "primary":
        return int(np.searchsorted(values, target, side=side))
    return bisect.bisect_left(values, target) if side == "left" else bisect.bisect_right(values, target)


def first_break(tree: RangeTree, kind: str, start: int, right: int, level: int, implementation: str) -> int | None:
    if start >= right:
        return None
    if kind == "HIGH":
        threshold = level + 1
        return tree.first_high_primary(start, right, threshold) if implementation == "primary" else tree.first_high_reference(start, right, threshold)
    threshold = level - 1
    return tree.first_low_primary(start, right, threshold) if implementation == "primary" else tree.first_low_reference(start, right, threshold)


def build_pivots(frame: Frame, timeframe: str, implementation: str) -> list[Pivot]:
    count = len(frame.close_ns)
    if implementation == "primary":
        centers = np.arange(2, count - 2, dtype=np.int64)
        valid = (
            frame.valid[centers - 2] & frame.valid[centers - 1] & frame.valid[centers]
            & frame.valid[centers + 1] & frame.valid[centers + 2]
        )
        high_mask = valid & (frame.high_e8[centers] > frame.high_e8[centers - 1]) & (frame.high_e8[centers] > frame.high_e8[centers - 2]) & (frame.high_e8[centers] >= frame.high_e8[centers + 1]) & (frame.high_e8[centers] >= frame.high_e8[centers + 2])
        low_mask = valid & (frame.low_e8[centers] < frame.low_e8[centers - 1]) & (frame.low_e8[centers] < frame.low_e8[centers - 2]) & (frame.low_e8[centers] <= frame.low_e8[centers + 1]) & (frame.low_e8[centers] <= frame.low_e8[centers + 2])
        candidates = [(int(index), "HIGH") for index in centers[high_mask]] + [(int(index), "LOW") for index in centers[low_mask]]
    else:
        candidates: list[tuple[int, str]] = []
        for center in range(2, count - 2):
            if not all(bool(frame.valid[index]) for index in range(center - 2, center + 3)):
                continue
            if int(frame.high_e8[center]) > int(frame.high_e8[center - 1]) and int(frame.high_e8[center]) > int(frame.high_e8[center - 2]) and int(frame.high_e8[center]) >= int(frame.high_e8[center + 1]) and int(frame.high_e8[center]) >= int(frame.high_e8[center + 2]):
                candidates.append((center, "HIGH"))
            if int(frame.low_e8[center]) < int(frame.low_e8[center - 1]) and int(frame.low_e8[center]) < int(frame.low_e8[center - 2]) and int(frame.low_e8[center]) <= int(frame.low_e8[center + 1]) and int(frame.low_e8[center]) <= int(frame.low_e8[center + 2]):
                candidates.append((center, "LOW"))
    tree = RangeTree(frame.high_e8, frame.low_e8)
    pivots: list[Pivot] = []
    for center, kind in candidates:
        price = int(frame.high_e8[center] if kind == "HIGH" else frame.low_e8[center])
        known = int(frame.close_ns[center + 2])
        broken_index = first_break(tree, kind, center + 3, count, price, implementation)
        broken = INFINITY_NS if broken_index is None else int(frame.close_ns[broken_index])
        identity = canonical_hash([timeframe, kind, center, price, known])
        pivots.append(Pivot(identity, timeframe, kind, price, known, broken))
    pivots.sort(key=lambda item: (item.known_ns, item.kind, item.price_e8, item.pivot_id))
    return pivots


def pivot_checksum(pivots: Sequence[Pivot]) -> str:
    return canonical_hash([[p.pivot_id, p.timeframe, p.kind, p.price_e8, p.known_ns, p.broken_ns] for p in pivots])


def atr14_m15(frame: Frame, cutoff_ns: int, implementation: str) -> int | None:
    stop = frame_index(frame.close_ns, cutoff_ns, implementation, "right")
    if stop < 15:
        return None
    start = stop - 15
    if implementation == "primary":
        indexes = np.arange(start + 1, stop, dtype=np.int64)
        if not bool(np.all(frame.valid[start:stop])):
            return None
        ranges = frame.high_e8[indexes] - frame.low_e8[indexes]
        high_gap = np.abs(frame.high_e8[indexes] - frame.close_e8[indexes - 1])
        low_gap = np.abs(frame.low_e8[indexes] - frame.close_e8[indexes - 1])
        total = int(np.maximum(ranges, np.maximum(high_gap, low_gap)).sum(dtype=np.int64))
    else:
        if any(not bool(frame.valid[index]) for index in range(start, stop)):
            return None
        total = 0
        for index in range(start + 1, stop):
            total += max(
                int(frame.high_e8[index]) - int(frame.low_e8[index]),
                abs(int(frame.high_e8[index]) - int(frame.close_e8[index - 1])),
                abs(int(frame.low_e8[index]) - int(frame.close_e8[index - 1])),
            )
    value = total // 14
    return value if value > 0 else None


def active(pivot: Pivot, timestamp: int) -> bool:
    return pivot.known_ns <= timestamp < pivot.broken_ns


def choose_next_liquidity(
    catalogs: Mapping[str, Sequence[Pivot]],
    direction: str,
    original_target: int,
    atr_e8: int,
    cutoff_ns: int,
) -> Pivot | None:
    sign = 1 if direction == "UP" else -1
    minimum_gap = (atr_e8 + 3) // 4
    candidates: list[tuple[int, int, int, str, Pivot]] = []
    wanted = "HIGH" if sign > 0 else "LOW"
    for timeframe in ("H1", "H4"):
        for pivot in catalogs[timeframe]:
            distance = sign * (pivot.price_e8 - original_target)
            if pivot.kind != wanted or distance < minimum_gap or not active(pivot, cutoff_ns):
                continue
            candidates.append((distance, 0 if timeframe == "H1" else 1, -pivot.known_ns, pivot.pivot_id, pivot))
    return min(candidates, default=None, key=lambda item: item[:4])[-1] if candidates else None


def latest_trail_pivot(
    pivots: Sequence[Pivot], direction: str, current_close: int, cutoff_ns: int
) -> Pivot | None:
    wanted = "LOW" if direction == "UP" else "HIGH"
    candidates = [
        pivot for pivot in pivots
        if pivot.kind == wanted and active(pivot, cutoff_ns)
        and ((pivot.price_e8 < current_close) if direction == "UP" else (pivot.price_e8 > current_close))
    ]
    if not candidates:
        return None
    if direction == "UP":
        return min(candidates, key=lambda item: (-item.known_ns, -item.price_e8, item.pivot_id))
    return min(candidates, key=lambda item: (-item.known_ns, item.price_e8, item.pivot_id))


def classify_target_bar(frame: Frame, index: int, direction: str, target: int, atr_e8: int) -> str:
    if not bool(frame.valid[index]):
        return "UNKNOWN"
    sign = 1 if direction == "UP" else -1
    opened = int(frame.open_e8[index]); high = int(frame.high_e8[index]); low = int(frame.low_e8[index]); close = int(frame.close_e8[index])
    signed_distance = sign * (close - target)
    accept_buffer = (atr_e8 + 9) // 10
    reject_buffer = (atr_e8 + 19) // 20
    candle_range = high - low
    body_aligned = sign * (close - opened) > 0
    close_numerator = close - low if sign > 0 else high - close
    close_location = candle_range > 0 and close_numerator * 100 >= candle_range * 60
    if signed_distance >= accept_buffer and body_aligned and close_location:
        return "ACCEPTED"
    if signed_distance <= -reject_buffer:
        return "REJECTED"
    return "NEUTRAL"


def trail_candidate(
    pivots: Sequence[Pivot], direction: str, current_close: int, cutoff_ns: int, atr_e8: int, current_stop: int
) -> tuple[int, bool, str | None]:
    pivot = latest_trail_pivot(pivots, direction, current_close, cutoff_ns)
    if pivot is None:
        return current_stop, False, None
    buffer_e8 = (atr_e8 + 9) // 10
    minimum_distance = (atr_e8 + 19) // 20
    if direction == "UP":
        proposed = max(current_stop, pivot.price_e8 - buffer_e8)
        invalid = current_close - proposed < minimum_distance
    else:
        proposed = min(current_stop, pivot.price_e8 + buffer_e8)
        invalid = proposed - current_close < minimum_distance
    return proposed, invalid, pivot.pivot_id


def synthetic_proof() -> dict[str, Any]:
    unit = SCALE
    close_ns = np.asarray([(index + 1) * 900_000_000_000 for index in range(20)], dtype=np.int64)
    open_ns = close_ns - 900_000_000_000
    closes = np.asarray([100, 101, 102, 103, 104, 103, 102, 104, 106, 105, 107, 108, 107, 109, 110, 111, 112, 113, 114, 115], dtype=np.int64) * unit
    highs = closes + unit
    lows = closes - unit
    frame = Frame(
        "M15", open_ns, close_ns, close_ns, closes, highs, lows, closes,
        np.ones(20), np.zeros(20), np.zeros(20, dtype=np.int16), np.ones(20, dtype=bool),
    )
    primary_atr = atr14_m15(frame, int(close_ns[-1]), "primary")
    reference_atr = atr14_m15(frame, int(close_ns[-1]), "reference")
    if primary_atr != reference_atr or primary_atr is None or primary_atr <= 0:
        raise AssertionError((primary_atr, reference_atr))
    primary_pivots = build_pivots(frame, "M15", "primary")
    reference_pivots = build_pivots(frame, "M15", "reference")
    if pivot_checksum(primary_pivots) != pivot_checksum(reference_pivots):
        raise AssertionError("Pivot implementations differ")
    accepted = Frame(
        "M15", np.asarray([0]), np.asarray([1]), np.asarray([1]), np.asarray([100 * unit]),
        np.asarray([103 * unit]), np.asarray([99 * unit]), np.asarray([102 * unit]),
        np.ones(1), np.zeros(1), np.zeros(1, dtype=np.int16), np.ones(1, dtype=bool),
    )
    if classify_target_bar(accepted, 0, "UP", 100 * unit, 10 * unit) != "ACCEPTED":
        raise AssertionError("Acceptance classification failed")
    rejected = Frame(
        "M15", np.asarray([0]), np.asarray([1]), np.asarray([1]), np.asarray([100 * unit]),
        np.asarray([101 * unit]), np.asarray([98 * unit]), np.asarray([99 * unit]),
        np.ones(1), np.zeros(1), np.zeros(1, dtype=np.int16), np.ones(1, dtype=bool),
    )
    if classify_target_bar(rejected, 0, "UP", 100 * unit, 10 * unit) != "REJECTED":
        raise AssertionError("Rejection classification failed")
    allocations = [(ounces, fraction, max(1, math.ceil(fraction * ounces))) for ounces in (1, 2, 5) for fraction in (0.25, 0.5, 0.75)]
    if any(take > ounces or ounces - take < 0 for ounces, _, take in allocations):
        raise AssertionError("Whole-ounce allocation failed")
    return {
        "status": "PASS_SYNTHETIC_TARGET_STATE_AND_LIQUIDITY_PROOF",
        "atr_primary_reference_equal": True,
        "pivot_primary_reference_equal": True,
        "acceptance_rejection_cases": 2,
        "whole_ounce_allocation_cases": len(allocations),
    }


def seal_prepath(audit: Mapping[str, Any], proof: Mapping[str, Any]) -> None:
    write_json_exclusive(
        PREPATH_FREEZE,
        {
            "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_PREPATH_FREEZE_1_0",
            "status": "SEALED_BEFORE_2021_2024_POST_TARGET_PATH_ACCESS",
            "sealed_at_utc": utc_now(),
            "controls": {
                "contract": file_record(CONTRACT),
                "protocol": file_record(PROTOCOL),
                "implementation": file_record(IMPLEMENTATION),
                "tests": file_record(TESTS),
                "predecessor_final_seal": file_record(PREDECESSOR_FINAL_SEAL),
            },
            "sources": {
                "primary_plans": file_record(ceiling.PRIMARY_PLANS),
                "reference_plans": file_record(ceiling.REFERENCE_PLANS),
                "primary_oof": file_record(ceiling.PRIMARY_OOF),
                "reference_oof": file_record(ceiling.REFERENCE_OOF),
                "predecessor_cases_primary": file_record(PREDECESSOR_CASES_PRIMARY),
                "predecessor_cases_reference": file_record(PREDECESSOR_CASES_REFERENCE),
                "raw_price": file_record(ceiling.RAW_PRICE),
            },
            "registered_policies": [item[0] for item in POLICIES],
            "expected_population": {"oof": 424, "no_trade": 176, "executable": 248},
            "synthetic_proof": dict(proof),
            "post_target_paths_accessed": False,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )


def load_prior_cases(path: Path) -> dict[str, dict[str, Any]]:
    rows = pq.read_table(path).to_pylist()
    result = {str(row["pullback_id"]): row for row in rows if row["case_status"] == "EXECUTABLE"}
    if len(rows) != 424 or len(result) != 248:
        raise ValueError("Predecessor matched population changed")
    return result


def control_payload(base_row: Mapping[str, Any], cost_multiplier: float) -> float:
    gross = float(base_row["frozen_execution_gross_pre_overlap_usd"])
    cost = float(base_row["transaction_cost_usd"])
    return gross - cost_multiplier * cost


def locate_m1_path(m1: Frame, plan: Mapping[str, Any], implementation: str) -> tuple[int, int]:
    entry_ns = parse_ns(str(plan["first_entry_at_utc"]))
    deadline_ns = parse_ns(str(plan["deadline_at_utc"]))
    left = frame_index(m1.open_ns, entry_ns, implementation, "left")
    right = frame_index(m1.close_ns, deadline_ns, implementation, "right")
    if left >= len(m1.open_ns) or int(m1.open_ns[left]) != entry_ns:
        raise ValueError(f"Missing exact entry M1: {plan['pullback_id']}")
    if right <= left or int(m1.close_ns[right - 1]) != deadline_ns:
        raise ValueError(f"Incomplete exact deadline M1: {plan['pullback_id']}")
    if not bool(np.all(m1.valid[left:right])):
        raise ValueError(f"Invalid M1 path: {plan['pullback_id']}")
    return left, right


def stop_hit(frame: Frame, index: int, direction: str, level: int) -> bool:
    return int(frame.low_e8[index]) <= level if direction == "UP" else int(frame.high_e8[index]) >= level


def favourable_hit(frame: Frame, index: int, direction: str, level: int) -> bool:
    return int(frame.high_e8[index]) >= level if direction == "UP" else int(frame.low_e8[index]) <= level


def stop_fill(frame: Frame, index: int, direction: str, level: int) -> int:
    opened = int(frame.open_e8[index])
    return min(level, opened) if direction == "UP" else max(level, opened)


def simulate_runner(
    base_row: Mapping[str, Any],
    plan: Mapping[str, Any],
    frames: Mapping[str, Frame],
    catalogs: Mapping[str, Sequence[Pivot]],
    implementation: str,
    take_fraction: float,
) -> dict[str, Any]:
    m1 = frames["M1"]; m15 = frames["M15"]
    direction = str(plan["first_direction"]); sign = 1 if direction == "UP" else -1
    entry = int(plan["first_entry_e8"]); original_stop = int(plan["first_stop_e8"]); original_target = int(plan["first_target_e8"])
    risk_e8 = int(plan["first_risk_e8"]); ounces = int(plan["first_ounces"])
    left, right = locate_m1_path(m1, plan, implementation)
    tree = RangeTree(m1.high_e8, m1.low_e8)
    target_index = ceiling.directional_event(tree, direction, "FAVOURABLE", left, right, original_target, implementation)
    stop_index = ceiling.directional_event(tree, direction, "STOP", left, right, original_stop, implementation)
    stop_order = math.inf if stop_index is None else stop_index
    target_order = math.inf if target_index is None else target_index
    if not (target_order < stop_order and target_order != math.inf):
        raise ValueError("Runner called for non-target-first case")
    target_index = int(target_index)
    target_touch_at = ns_iso(int(m1.close_ns[target_index]))
    target_cutoff = int(m1.open_ns[target_index])
    atr_e8 = atr14_m15(m15, target_cutoff, implementation)
    take_ounces = max(1, math.ceil(take_fraction * ounces))
    take_ounces = min(ounces, take_ounces)
    runner_ounces = ounces - take_ounces
    next_pivot = None if atr_e8 is None else choose_next_liquidity(catalogs, direction, original_target, atr_e8, target_cutoff)
    if runner_ounces == 0 or atr_e8 is None or next_pivot is None:
        reason = "FULL_CLOSE_ZERO_RUNNER" if runner_ounces == 0 else "FULL_CLOSE_ATR_UNAVAILABLE" if atr_e8 is None else "FULL_CLOSE_NEXT_LIQUIDITY_UNAVAILABLE"
        gross = ounces * sign * (original_target - entry) / SCALE
        return {
            "take_ounces": ounces,
            "runner_ounces": 0,
            "management_activated": False,
            "target_touch_at_utc": target_touch_at,
            "atr14_m15_e8": atr_e8,
            "next_liquidity_timeframe": None if next_pivot is None else next_pivot.timeframe,
            "next_liquidity_e8": None if next_pivot is None else next_pivot.price_e8,
            "next_liquidity_distance_r": None if next_pivot is None else sign * (next_pivot.price_e8 - original_target) / risk_e8,
            "target_state": reason,
            "target_state_sequence": reason,
            "acceptance_at_utc": None,
            "runner_exit_reason": reason,
            "runner_exit_at_utc": target_touch_at,
            "final_exit_at_utc": target_touch_at,
            "gross_pnl_usd": float(gross),
        }

    next_level = int(next_pivot.price_e8)
    partial_gross = take_ounces * sign * (original_target - entry) / SCALE
    trail_stop = original_stop
    accepted = False
    acceptance_at: str | None = None
    decision_count = 0
    pending_exit: tuple[str, int] | None = None
    states: list[str] = []
    runner_exit_reason: str | None = None
    runner_exit_at: str | None = None
    runner_exit_price: int | None = None
    close_to_m15 = {int(value): index for index, value in enumerate(m15.close_ns)}

    for index in range(target_index, right):
        opened_ns = int(m1.open_ns[index])
        if pending_exit is not None:
            reason, effective_ns = pending_exit
            if opened_ns != effective_ns:
                raise ValueError(f"Missing exact next-M1 execution open: {plan['pullback_id']}")
            runner_exit_reason = reason
            runner_exit_at = ns_iso(opened_ns)
            runner_exit_price = int(m1.open_e8[index])
            break

        hit_stop = stop_hit(m1, index, direction, trail_stop)
        hit_next = favourable_hit(m1, index, direction, next_level)
        if hit_stop and hit_next:
            runner_exit_reason = "PROTECTIVE_STOP_SAME_BAR_FIRST"
            runner_exit_at = ns_iso(int(m1.close_ns[index]))
            runner_exit_price = stop_fill(m1, index, direction, trail_stop)
            break
        if hit_stop:
            runner_exit_reason = "PROTECTIVE_STOP"
            runner_exit_at = ns_iso(int(m1.close_ns[index]))
            runner_exit_price = stop_fill(m1, index, direction, trail_stop)
            break
        if hit_next:
            runner_exit_reason = "NEXT_KNOWN_LIQUIDITY"
            runner_exit_at = ns_iso(int(m1.close_ns[index]))
            runner_exit_price = next_level
            break
        if index == right - 1:
            runner_exit_reason = "ORIGINAL_DEADLINE"
            runner_exit_at = ns_iso(int(m1.close_ns[index]))
            runner_exit_price = int(m1.close_e8[index])
            break

        completed_ns = int(m1.close_ns[index])
        m15_index = close_to_m15.get(completed_ns)
        if m15_index is None or completed_ns < int(m1.close_ns[target_index]):
            continue
        if not bool(m15.valid[m15_index]):
            states.append("UNKNOWN")
            pending_exit = ("TECHNICAL_EXIT", completed_ns)
            continue
        classification = classify_target_bar(m15, m15_index, direction, original_target, atr_e8)
        states.append(classification)
        signed_close = sign * (int(m15.close_e8[m15_index]) - original_target)
        reject_buffer = (atr_e8 + 19) // 20
        if not accepted:
            decision_count += 1
            if classification == "ACCEPTED":
                accepted = True
                acceptance_at = ns_iso(completed_ns)
                proposed, invalid, _ = trail_candidate(catalogs["M15"], direction, int(m15.close_e8[m15_index]), completed_ns, atr_e8, trail_stop)
                if invalid:
                    pending_exit = ("STRUCTURAL_TRAIL_MARKET_EXIT", completed_ns)
                else:
                    trail_stop = proposed
            elif classification == "REJECTED":
                pending_exit = ("TARGET_REJECTION_EXIT", completed_ns)
            elif decision_count >= 2:
                pending_exit = ("NEUTRAL_TIMEOUT_EXIT", completed_ns)
        else:
            if signed_close <= -reject_buffer:
                pending_exit = ("POST_ACCEPTANCE_REJECTION_EXIT", completed_ns)
            else:
                proposed, invalid, _ = trail_candidate(catalogs["M15"], direction, int(m15.close_e8[m15_index]), completed_ns, atr_e8, trail_stop)
                if invalid:
                    pending_exit = ("STRUCTURAL_TRAIL_MARKET_EXIT", completed_ns)
                else:
                    trail_stop = proposed

    if runner_exit_price is None or runner_exit_reason is None or runner_exit_at is None:
        raise RuntimeError(f"Runner failed to resolve: {plan['pullback_id']}")
    runner_gross = runner_ounces * sign * (runner_exit_price - entry) / SCALE
    final_state = "ACCEPTED" if accepted else states[-1] if states else "NEXT_LIQUIDITY_BEFORE_CLASSIFICATION"
    return {
        "take_ounces": take_ounces,
        "runner_ounces": runner_ounces,
        "management_activated": True,
        "target_touch_at_utc": target_touch_at,
        "atr14_m15_e8": atr_e8,
        "next_liquidity_timeframe": next_pivot.timeframe,
        "next_liquidity_e8": next_level,
        "next_liquidity_distance_r": sign * (next_level - original_target) / risk_e8,
        "target_state": final_state,
        "target_state_sequence": "|".join(states) if states else "NEXT_LIQUIDITY_BEFORE_CLASSIFICATION",
        "acceptance_at_utc": acceptance_at,
        "runner_exit_reason": runner_exit_reason,
        "runner_exit_at_utc": runner_exit_at,
        "final_exit_at_utc": runner_exit_at,
        "gross_pnl_usd": float(partial_gross + runner_gross),
    }


def base_case_row(
    identity: str,
    oof: Mapping[str, Any],
    plan: Mapping[str, Any],
    prior: Mapping[str, Any],
    baseline: Mapping[str, Any],
    policy_id: str,
    take_fraction: float | None,
    frames: Mapping[str, Frame],
    catalogs: Mapping[str, Sequence[Pivot]],
    implementation: str,
) -> dict[str, Any]:
    direction = str(plan["first_direction"]); ounces = int(plan["first_ounces"]); cost = float(plan["first_cost_usd_oz"]) * ounces
    target_first = str(baseline["exit_reason"]) == "KNOWN_TARGET"
    if policy_id == CONTROL or not target_first:
        gross = float(baseline["frozen_execution_gross_pre_overlap_usd"])
        payload = {
            "take_ounces": ounces if target_first else 0,
            "runner_ounces": 0,
            "management_activated": False,
            "target_touch_at_utc": baseline["first_target_at_utc"] if target_first else None,
            "atr14_m15_e8": None,
            "next_liquidity_timeframe": None,
            "next_liquidity_e8": None,
            "next_liquidity_distance_r": None,
            "target_state": "CONTROL_FULL_CLOSE" if policy_id == CONTROL and target_first else "TARGET_NOT_FIRST_CONTROL_REPRODUCTION",
            "target_state_sequence": "CONTROL_FULL_CLOSE" if policy_id == CONTROL and target_first else "TARGET_NOT_FIRST_CONTROL_REPRODUCTION",
            "acceptance_at_utc": None,
            "runner_exit_reason": str(baseline["exit_reason"]),
            "runner_exit_at_utc": str(baseline["exit_at_utc"]),
            "final_exit_at_utc": str(baseline["exit_at_utc"]),
            "gross_pnl_usd": gross,
        }
    else:
        if take_fraction is None:
            raise ValueError(policy_id)
        payload = simulate_runner(baseline, plan, frames, catalogs, implementation, take_fraction)
        gross = float(payload["gross_pnl_usd"])
    net = gross - cost
    net_1p5 = gross - 1.5 * cost
    net_2 = gross - 2.0 * cost
    perfect_gross = float(prior["stop_feasible_perfect_gross_usd"]) if str(prior["exit_reason"]) == "KNOWN_TARGET" else float(prior["frozen_execution_gross_pre_overlap_usd"])
    fixed_retained = bool(prior["retained_after_overlap"])
    perfect_base = (perfect_gross - cost) if fixed_retained else 0.0
    perfect_1p5 = (perfect_gross - 1.5 * cost) if fixed_retained else 0.0
    row: dict[str, Any] = {
        "row_id": canonical_hash([identity, policy_id, "H4_TARGET_CAPTURE_V1"]),
        "pullback_id": identity,
        "policy_id": policy_id,
        "fold": int(oof["fold"]),
        "decision_date": str(oof["decision_date"]),
        "entry_session": str(oof.get("entry_session") or plan.get("first_entry_session") or "UNKNOWN"),
        "direction": direction,
        "entry_at_utc": str(plan["first_entry_at_utc"]),
        "final_exit_at_utc": str(payload["final_exit_at_utc"]),
        "deadline_at_utc": str(plan["deadline_at_utc"]),
        "original_exit_reason": str(baseline["exit_reason"]),
        "overlap_disposition": "PENDING",
        "retained_after_overlap": False,
        "whole_ounces": ounces,
        "take_ounces": int(payload["take_ounces"]),
        "runner_ounces": int(payload["runner_ounces"]),
        "target_first": target_first,
        "management_activated": bool(payload["management_activated"]),
        "target_touch_at_utc": payload["target_touch_at_utc"],
        "atr14_m15_e8": payload["atr14_m15_e8"],
        "next_liquidity_timeframe": payload["next_liquidity_timeframe"],
        "next_liquidity_e8": payload["next_liquidity_e8"],
        "next_liquidity_distance_r": rounded(payload["next_liquidity_distance_r"]),
        "target_state": str(payload["target_state"]),
        "target_state_sequence": str(payload["target_state_sequence"]),
        "acceptance_at_utc": payload["acceptance_at_utc"],
        "runner_exit_reason": str(payload["runner_exit_reason"]),
        "runner_exit_at_utc": payload["runner_exit_at_utc"],
        "gross_pnl_usd": float(gross),
        "net_pnl_usd": float(net),
        "net_pnl_usd_cost_1p5x": float(net_1p5),
        "net_pnl_usd_cost_2x": float(net_2),
        "net_r": float(net / RISK_USD),
        "net_r_cost_1p5x": float(net_1p5 / RISK_USD),
        "net_r_cost_2x": float(net_2 / RISK_USD),
        "post_overlap_pnl_usd": 0.0,
        "post_overlap_pnl_usd_cost_1p5x": 0.0,
        "post_overlap_pnl_usd_cost_2x": 0.0,
        "post_overlap_r": 0.0,
        "incremental_post_overlap_r_vs_control": 0.0,
        "target_only_perfect_fixed_overlap_usd": float(perfect_base),
        "target_only_perfect_fixed_overlap_usd_cost_1p5x": float(perfect_1p5),
        "plan_lineage_hash": str(plan["plan_lineage_hash"]),
        "row_lineage_hash": "",
    }
    return row


def apply_overlap(rows: list[dict[str, Any]], expected_oof: Mapping[str, Mapping[str, Any]]) -> None:
    for policy_id in ALL_POLICIES:
        group = [row for row in rows if row["policy_id"] == policy_id]
        group.sort(key=lambda row: (parse_ns(str(row["entry_at_utc"])), str(row["pullback_id"])))
        active_until: int | None = None
        for row in group:
            entry_ns = parse_ns(str(row["entry_at_utc"])); exit_ns = parse_ns(str(row["final_exit_at_utc"]))
            if exit_ns < entry_ns:
                raise ValueError("Policy exit before entry")
            if active_until is not None and entry_ns < active_until:
                row["overlap_disposition"] = "SKIPPED_OVERLAP"
                row["retained_after_overlap"] = False
            else:
                row["overlap_disposition"] = "RETAINED"
                row["retained_after_overlap"] = True
                active_until = exit_ns
            multiplier = 1.0 if row["retained_after_overlap"] else 0.0
            row["post_overlap_pnl_usd"] = multiplier * float(row["net_pnl_usd"])
            row["post_overlap_pnl_usd_cost_1p5x"] = multiplier * float(row["net_pnl_usd_cost_1p5x"])
            row["post_overlap_pnl_usd_cost_2x"] = multiplier * float(row["net_pnl_usd_cost_2x"])
            row["post_overlap_r"] = float(row["post_overlap_pnl_usd"]) / RISK_USD
        if policy_id == CONTROL:
            for row in group:
                frozen = expected_oof[str(row["pullback_id"])]
                expected_retained = bool(frozen["retained_after_overlap"])
                expected_disposition = "RETAINED" if expected_retained else "SKIPPED_OVERLAP"
                if bool(row["retained_after_overlap"]) != expected_retained or str(row["overlap_disposition"]) != expected_disposition:
                    raise ValueError(f"Control overlap reproduction failed: {row['pullback_id']}")
    controls = {str(row["pullback_id"]): row for row in rows if row["policy_id"] == CONTROL}
    for row in rows:
        control = controls[str(row["pullback_id"])]
        row["incremental_post_overlap_r_vs_control"] = float(row["post_overlap_r"]) - float(control["post_overlap_r"])
        row["row_lineage_hash"] = canonical_hash(
            [
                row["row_id"], row["plan_lineage_hash"], row["final_exit_at_utc"], row["target_state_sequence"],
                row["runner_exit_reason"], row["gross_pnl_usd"], row["overlap_disposition"], row["post_overlap_pnl_usd"],
            ]
        )


def materialize(
    plan_path: Path,
    oof_path: Path,
    prior_path: Path,
    frames: Mapping[str, Frame],
    catalogs: Mapping[str, Sequence[Pivot]],
    destination: Path,
    implementation: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    oof_rows, plans, _, population = ceiling.load_population(plan_path, oof_path)
    prior = load_prior_cases(prior_path)
    m1 = frames["M1"]
    tree = RangeTree(m1.high_e8, m1.low_e8)
    invalid_prefix = np.concatenate(([0], np.cumsum(~m1.valid.astype(bool), dtype=np.int64)))
    expected_oof = {str(row["pullback_id"]): row for row in oof_rows if bool(row["traded"])}
    rows: list[dict[str, Any]] = []
    for oof in oof_rows:
        if not bool(oof["traded"]):
            continue
        identity = str(oof["pullback_id"]); plan = plans[identity]
        baseline = ceiling.audit_executable_case(oof, plan, None, m1, tree, invalid_prefix, implementation)
        sealed = prior[identity]
        for name in ("exit_reason", "exit_at_utc"):
            if str(baseline[name]) != str(sealed[name]):
                raise ValueError(f"Baseline {name} changed: {identity}")
        if abs(float(baseline["frozen_execution_net_pre_overlap_usd"]) - float(sealed["frozen_execution_net_pre_overlap_usd"])) > 1e-9:
            raise ValueError(f"Baseline PnL changed: {identity}")
        rows.append(base_case_row(identity, oof, plan, sealed, baseline, CONTROL, None, frames, catalogs, implementation))
        for policy_id, take_fraction in POLICIES:
            rows.append(base_case_row(identity, oof, plan, sealed, baseline, policy_id, take_fraction, frames, catalogs, implementation))
    if len(rows) != 248 * 4:
        raise ValueError(f"Policy row population changed: {len(rows)}")
    apply_overlap(rows, expected_oof)
    rows.sort(key=lambda row: (str(row["policy_id"]), str(row["decision_date"]), str(row["pullback_id"])))
    control_rows = [row for row in rows if row["policy_id"] == CONTROL]
    control_total = sum(float(row["post_overlap_pnl_usd"]) for row in control_rows)
    if abs(control_total - 1893.817786) > 1e-6:
        raise ValueError(f"Frozen control PnL not reproduced: {control_total}")
    write_parquet(rows, destination)
    diagnostics = {
        "implementation": implementation,
        "population": population,
        "rows": len(rows),
        "cases_per_policy": {policy: sum(row["policy_id"] == policy for row in rows) for policy in ALL_POLICIES},
        "control_retained": sum(row["policy_id"] == CONTROL and row["retained_after_overlap"] for row in rows),
        "control_skipped": sum(row["policy_id"] == CONTROL and not row["retained_after_overlap"] for row in rows),
        "target_first_cases": sum(row["policy_id"] == CONTROL and row["target_first"] for row in rows),
        "complete_row_checksum": canonical_hash([[row[field.name] for field in CASE_SCHEMA] for row in rows]),
        "output": file_record(destination),
    }
    return rows, diagnostics


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return 1_000_000_000.0 if gains > 0 else None
    return gains / losses


def maximum_drawdown(values: Sequence[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def positive_share(values: Mapping[str, float]) -> float:
    positives = [float(value) for value in values.values() if float(value) > 0]
    return max(positives) / sum(positives) if positives else 1.0


def group_pnl(rows: Sequence[Mapping[str, Any]], key_fn: Any) -> dict[str, float]:
    values: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        values[str(key_fn(row))] += float(row["post_overlap_pnl_usd"])
    return {key: round(value, 6) for key, value in sorted(values.items())}


def clustered_bootstrap(rows: Sequence[Mapping[str, Any]], value_field: str, policy_id: str, label: str) -> dict[str, Any]:
    groups: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(row["decision_date"])].append(float(row[value_field]))
    keys = sorted(groups)
    arrays = [np.asarray(groups[key], dtype=np.float64) for key in keys]
    if not arrays:
        return {"ci95_low": None, "ci95_high": None, "one_sided_p": None, "clusters": 0, "resamples": BOOTSTRAPS}
    material = hashlib.sha256(f"{SEED}|{policy_id}|{label}".encode("utf-8")).digest()
    rng = np.random.default_rng(int.from_bytes(material[:8], "little"))
    samples = np.empty(BOOTSTRAPS, dtype=np.float64)
    for sample_index in range(BOOTSTRAPS):
        selected = rng.integers(0, len(arrays), size=len(arrays))
        total = 0.0; count = 0
        for index in selected:
            values = arrays[int(index)]
            total += float(values.sum()); count += len(values)
        samples[sample_index] = total / count
    return {
        "ci95_low": rounded(float(np.quantile(samples, 0.025))),
        "ci95_high": rounded(float(np.quantile(samples, 0.975))),
        "one_sided_p": rounded((1 + int(np.sum(samples <= 0.0))) / (BOOTSTRAPS + 1)),
        "clusters": len(arrays),
        "resamples": BOOTSTRAPS,
    }


def policy_metric(rows: Sequence[Mapping[str, Any]], policy_id: str) -> dict[str, Any]:
    group = [row for row in rows if row["policy_id"] == policy_id]
    retained = sorted([row for row in group if bool(row["retained_after_overlap"])], key=lambda row: (parse_ns(str(row["entry_at_utc"])), str(row["pullback_id"])))
    pnl = [float(row["post_overlap_pnl_usd"]) for row in retained]
    pnl_1p5 = [float(row["post_overlap_pnl_usd_cost_1p5x"]) for row in retained]
    pnl_2 = [float(row["post_overlap_pnl_usd_cost_2x"]) for row in retained]
    wins = [value / RISK_USD for value in pnl if value > 0]; losses = [value / RISK_USD for value in pnl if value < 0]
    years = group_pnl(group, lambda row: str(row["decision_date"])[:4])
    folds = group_pnl(group, lambda row: row["fold"])
    sessions = group_pnl(group, lambda row: row["entry_session"])
    total = sum(pnl); total_1p5 = sum(pnl_1p5); total_2 = sum(pnl_2)
    dd = maximum_drawdown(pnl)
    managed = [row for row in group if bool(row["management_activated"])]
    absolute = clustered_bootstrap(group, "post_overlap_r", policy_id, "ABSOLUTE")
    incremental = clustered_bootstrap(group, "incremental_post_overlap_r_vs_control", policy_id, "INCREMENTAL")
    return {
        "policy_id": policy_id,
        "executable_cases": len(group),
        "retained_cases": len(retained),
        "overlap_skips": len(group) - len(retained),
        "target_first_cases": sum(bool(row["target_first"]) for row in group),
        "managed_runner_cases": len(managed),
        "managed_runner_dates": len({str(row["decision_date"]) for row in managed}),
        "target_state_counts": dict(sorted(Counter(str(row["target_state"]) for row in group if row["target_first"]).items())),
        "runner_exit_counts": dict(sorted(Counter(str(row["runner_exit_reason"]) for row in managed).items())),
        "net_pnl_usd_at_50": rounded(total, 6),
        "net_r": rounded(total / RISK_USD),
        "r_per_month": rounded(total / RISK_USD / MONTHS),
        "usd_per_month_at_50": rounded(total / MONTHS, 6),
        "usd_per_month_at_1pct": rounded(2.0 * total / MONTHS, 6),
        "net_expectancy_r_retained": rounded(total / RISK_USD / len(retained) if retained else None),
        "win_rate": rounded(sum(value > 0 for value in pnl) / len(pnl) if pnl else None),
        "average_win_r": rounded(float(np.mean(wins)) if wins else None),
        "average_loss_r": rounded(float(np.mean(losses)) if losses else None),
        "profit_factor": rounded(profit_factor(pnl)),
        "net_r_cost_1p5x": rounded(total_1p5 / RISK_USD),
        "r_per_month_cost_1p5x": rounded(total_1p5 / RISK_USD / MONTHS),
        "expectancy_r_cost_1p5x": rounded(total_1p5 / RISK_USD / len(retained) if retained else None),
        "net_r_cost_2x": rounded(total_2 / RISK_USD),
        "r_per_month_cost_2x": rounded(total_2 / RISK_USD / MONTHS),
        "maximum_drawdown_usd_at_50": rounded(dd, 6),
        "maximum_drawdown_pct_at_1pct": rounded(dd / 50.0),
        "incremental_net_r_vs_control": rounded(sum(float(row["incremental_post_overlap_r_vs_control"]) for row in group)),
        "incremental_r_per_month_vs_control": rounded(sum(float(row["incremental_post_overlap_r_vs_control"]) for row in group) / MONTHS),
        "incremental_expectancy_r_all_248": rounded(float(np.mean([float(row["incremental_post_overlap_r_vs_control"]) for row in group]))),
        "absolute_bootstrap": absolute,
        "incremental_bootstrap": incremental,
        "annual_pnl_usd": years,
        "fold_pnl_usd": folds,
        "session_pnl_usd": sessions,
        "positive_folds": sum(value > 0 for value in folds.values()),
        "positive_years": sum(value > 0 for value in years.values()),
        "maximum_positive_year_share": rounded(positive_share(years)),
        "maximum_positive_session_share": rounded(positive_share(sessions)),
    }


def holm_adjust(metrics: Sequence[dict[str, Any]]) -> None:
    candidates = [metric for metric in metrics if metric["policy_id"] != CONTROL]
    ordered = sorted(candidates, key=lambda metric: (float(metric["incremental_bootstrap"]["one_sided_p"]), str(metric["policy_id"])))
    running = 0.0; adjusted: dict[str, float] = {}
    for index, metric in enumerate(ordered):
        raw = float(metric["incremental_bootstrap"]["one_sided_p"])
        running = max(running, min(1.0, (len(ordered) - index) * raw))
        adjusted[str(metric["policy_id"])] = running
    for metric in metrics:
        metric["holm_incremental_p"] = rounded(adjusted.get(str(metric["policy_id"])))


def apply_gates(metric: dict[str, Any]) -> None:
    if metric["policy_id"] == CONTROL:
        metric["gates"] = {}; metric["failed_gates"] = []; metric["verdict"] = "CONTROL"
        return
    gates = {
        "all_248_paths_and_control_reproduce": metric["executable_cases"] == 248,
        "managed_support": metric["managed_runner_cases"] >= 30 and metric["managed_runner_dates"] >= 20,
        "r_per_month_gte_10": float(metric["r_per_month"]) >= 10.0,
        "net_expectancy_gt_zero": float(metric["net_expectancy_r_retained"]) > 0,
        "incremental_expectancy_gt_zero": float(metric["incremental_expectancy_r_all_248"]) > 0,
        "profit_factor_gte_1p10": metric["profit_factor"] is not None and float(metric["profit_factor"]) >= 1.10,
        "absolute_ci95_low_gt_zero": metric["absolute_bootstrap"]["ci95_low"] is not None and float(metric["absolute_bootstrap"]["ci95_low"]) > 0,
        "incremental_ci95_low_gt_zero": metric["incremental_bootstrap"]["ci95_low"] is not None and float(metric["incremental_bootstrap"]["ci95_low"]) > 0,
        "holm_incremental_p_lte_0p05": metric["holm_incremental_p"] is not None and float(metric["holm_incremental_p"]) <= 0.05,
        "cost_1p5x_expectancy_gt_zero": float(metric["expectancy_r_cost_1p5x"]) > 0,
        "positive_folds_gte_4": int(metric["positive_folds"]) >= 4,
        "positive_years_gte_3": int(metric["positive_years"]) >= 3,
        "maximum_positive_year_share_lte_0p70": float(metric["maximum_positive_year_share"]) <= 0.70,
        "maximum_positive_session_share_lte_0p70": float(metric["maximum_positive_session_share"]) <= 0.70,
        "maximum_drawdown_pct_at_1pct_lte_15": float(metric["maximum_drawdown_pct_at_1pct"]) <= 15.0,
    }
    metric["gates"] = gates
    metric["failed_gates"] = [name for name, passed in gates.items() if not passed]
    metric["verdict"] = "PASS" if all(gates.values()) else "REJECT"


def summarize(rows: Sequence[Mapping[str, Any]], catalog_diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    metrics = [policy_metric(rows, policy_id) for policy_id in ALL_POLICIES]
    holm_adjust(metrics)
    for metric in metrics:
        apply_gates(metric)
    control = next(metric for metric in metrics if metric["policy_id"] == CONTROL)
    candidates = [metric for metric in metrics if metric["policy_id"] != CONTROL]
    passing = [metric for metric in candidates if metric["verdict"] == "PASS"]
    passing.sort(key=lambda metric: (-float(metric["r_per_month"]), -float(metric["profit_factor"]), -float(metric["incremental_bootstrap"]["ci95_low"]), -next(f for p, f in POLICIES if p == metric["policy_id"])))
    target_ceiling_base = sum(float(row["target_only_perfect_fixed_overlap_usd"]) for row in rows if row["policy_id"] == CONTROL)
    target_ceiling_1p5 = sum(float(row["target_only_perfect_fixed_overlap_usd_cost_1p5x"]) for row in rows if row["policy_id"] == CONTROL)
    best_observed = sorted(candidates, key=lambda metric: (-float(metric["r_per_month"]), str(metric["policy_id"])))[0]
    if passing:
        verdict = "PROVISIONAL_TARGET_POLICY_REQUIRES_FORWARD_EVIDENCE"
        selected = str(passing[0]["policy_id"])
        disposition = "FREEZE_EXACTLY_ONE_PROVISIONAL_POLICY_NO_FORWARD_ACCESS_IN_THIS_STUDY"
    else:
        verdict = "TERMINATE_GOLD_ONLY_10R_BRANCH"
        selected = None
        disposition = "NO_NEW_GOLD_RESEARCH_BRANCH"
    if not passing and any(float(metric["r_per_month"]) >= 10.0 for metric in candidates):
        termination_reason = "AT_LEAST_ONE_POLICY_REACHED_10R_BUT_FAILED_CREDIBILITY_GATES"
    elif not passing:
        termination_reason = "NO_OPERATIONAL_POLICY_REACHED_10R_AND_PASSED_ALL_GATES"
    else:
        termination_reason = None
    return {
        "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_RESULT_1_0",
        "verdict": verdict,
        "population": {"oof_cases": 424, "no_trade": 176, "executable": 248, "months": MONTHS},
        "policy_metrics": metrics,
        "target_only_hindsight_ceiling": {
            "description": "FIXED_ORIGINAL_OVERLAP_STOP_FEASIBLE_PERFECT_EXIT_SUBSTITUTED_ONLY_FOR_ORIGINAL_TARGET_FIRST_CASES",
            "base_cost_total_r": rounded(target_ceiling_base / RISK_USD),
            "base_cost_r_per_month": rounded(target_ceiling_base / RISK_USD / MONTHS),
            "base_cost_usd_per_month_at_1pct": rounded(2.0 * target_ceiling_base / MONTHS, 6),
            "cost_1p5x_total_r": rounded(target_ceiling_1p5 / RISK_USD),
            "cost_1p5x_r_per_month": rounded(target_ceiling_1p5 / RISK_USD / MONTHS),
            "hindsight_only": True,
        },
        "control_reproduction": {
            "expected_total_usd": 1893.817786,
            "reproduced_total_usd": control["net_pnl_usd_at_50"],
            "expected_r_per_month": 0.971188608,
            "reproduced_r_per_month": control["r_per_month"],
        },
        "best_observed_policy": {
            "policy_id": best_observed["policy_id"],
            "r_per_month": best_observed["r_per_month"],
            "usd_per_month_at_1pct": best_observed["usd_per_month_at_1pct"],
            "verdict": best_observed["verdict"],
            "failed_gates": best_observed["failed_gates"],
        },
        "selected_policy": selected,
        "termination_reason": termination_reason,
        "required_disposition": disposition,
        "catalog_diagnostics": dict(catalog_diagnostics),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }


def render_report(result: Mapping[str, Any], certification: Mapping[str, Any]) -> str:
    lines = [
        "# Gold H4 Liquidity-Target Capture Falsification V1", "",
        f"Verdict: **{result['verdict']}**", "",
        "This final bounded study changed only management after the already-frozen original liquidity target. All 248 executable cases were evaluated; stop-first and time-exit cases remained in the denominator. Calendar 2025 and 2026 stayed locked.", "",
        "## Economics", "",
        "| Policy | Managed | Retained | R/month | $/month at 1% | PF | Incremental R/month | Absolute CI low | Incremental CI low | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for metric in result["policy_metrics"]:
        def fmt(value: Any, digits: int = 3) -> str:
            return "n/a" if value is None else f"{float(value):.{digits}f}"
        lines.append(
            f"| {metric['policy_id']} | {metric['managed_runner_cases']} | {metric['retained_cases']} | {fmt(metric['r_per_month'])} | ${fmt(metric['usd_per_month_at_1pct'], 2)} | {fmt(metric['profit_factor'])} | {fmt(metric['incremental_r_per_month_vs_control'])} | {fmt(metric['absolute_bootstrap']['ci95_low'])} | {fmt(metric['incremental_bootstrap']['ci95_low'])} | {metric['verdict']} |"
        )
    ceiling_result = result["target_only_hindsight_ceiling"]
    lines.extend(
        [
            "", "## Target-only ceiling", "",
            f"- Fixed-disposition target-only perfect-exit ceiling: **{ceiling_result['base_cost_r_per_month']:.3f}R/month** (${ceiling_result['base_cost_usd_per_month_at_1pct']:.2f}/month at 1% risk).",
            f"- The same hindsight ceiling at 1.5x costs: **{ceiling_result['cost_1p5x_r_per_month']:.3f}R/month**.",
            "- This ceiling is not tradable performance; it is an impossibility diagnostic that changes only original target-first cases.",
            "", "## Decision", "",
            f"- Best observed policy: `{result['best_observed_policy']['policy_id']}` at {result['best_observed_policy']['r_per_month']:.3f}R/month.",
            f"- Selected provisional policy: `{result['selected_policy']}`.",
            f"- Required disposition: `{result['required_disposition']}`.",
        ]
    )
    if result.get("termination_reason"):
        lines.append(f"- Termination reason: `{result['termination_reason']}`.")
    for metric in result["policy_metrics"]:
        if metric["policy_id"] != CONTROL:
            lines.append(f"- `{metric['policy_id']}` failed gates: {', '.join(metric['failed_gates']) if metric['failed_gates'] else 'none'}.")
    lines.extend(
        [
            "", "## Integrity", "",
            f"- Primary/reference case payloads byte-identical: {str(certification['case_payloads_byte_identical']).lower()}.",
            f"- Primary/reference result payloads byte-identical: {str(certification['results_byte_identical']).lower()}.",
            "- The predecessor control PnL and overlap dispositions reproduced exactly.",
            "- Calendar 2025/2026 accessed: false. Paid acquisition: $0.00.", "",
        ]
    )
    return "\n".join(lines)


def run_implementation(
    label: str,
    frames: Mapping[str, Frame],
    plan_path: Path,
    oof_path: Path,
    prior_path: Path,
    destination: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    catalogs = {name: build_pivots(frames[name], name, label) for name in ("M15", "H1", "H4")}
    catalog_diagnostics = {
        name: {"count": len(values), "checksum": pivot_checksum(values)} for name, values in catalogs.items()
    }
    rows, materialization = materialize(plan_path, oof_path, prior_path, frames, catalogs, destination, label)
    return rows, materialization, catalog_diagnostics


def main() -> None:
    audit = preflight()
    proof = synthetic_proof()
    seal_prepath(audit, proof)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        OPENING,
        {
            "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_PATH_OPENING_1_0",
            "status": "CONTROLLED_2021_2024_POST_TARGET_PATH_OPENING",
            "opened_at_utc": utc_now(),
            "prepath_freeze": file_record(PREPATH_FREEZE),
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    frames, price_diagnostics = load_price()
    primary_rows, primary_materialization, primary_catalogs = run_implementation(
        "primary", frames, ceiling.PRIMARY_PLANS, ceiling.PRIMARY_OOF, PREDECESSOR_CASES_PRIMARY, PRIMARY_CASES
    )
    reference_rows, reference_materialization, reference_catalogs = run_implementation(
        "reference", frames, ceiling.REFERENCE_PLANS, ceiling.REFERENCE_OOF, PREDECESSOR_CASES_REFERENCE, REFERENCE_CASES
    )
    if primary_catalogs != reference_catalogs:
        raise RuntimeError("FAIL_PIVOT_CATALOG_REPRODUCTION")
    compare_materialization = [
        key for key in ("rows", "cases_per_policy", "control_retained", "control_skipped", "target_first_cases", "complete_row_checksum")
        if primary_materialization[key] != reference_materialization[key]
    ]
    case_bytes_identical = sha256_file(PRIMARY_CASES) == sha256_file(REFERENCE_CASES)
    if compare_materialization or not case_bytes_identical:
        raise RuntimeError({"status": "FAIL_CASE_REPRODUCTION", "differences": compare_materialization, "byte_identical": case_bytes_identical})
    primary_result = summarize(primary_rows, primary_catalogs)
    reference_result = summarize(reference_rows, reference_catalogs)
    if canonical_json(primary_result) != canonical_json(reference_result):
        raise RuntimeError("FAIL_RESULT_REPRODUCTION")
    write_json_exclusive(PRIMARY_RESULTS, primary_result)
    write_json_exclusive(REFERENCE_RESULTS, reference_result)
    results_identical = sha256_file(PRIMARY_RESULTS) == sha256_file(REFERENCE_RESULTS)
    if not results_identical:
        raise RuntimeError("FAIL_RESULT_BYTE_REPRODUCTION")
    certification = {
        "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_CERTIFICATION_1_0",
        "status": "PASS_INDEPENDENT_REPRODUCTION",
        "certified_at_utc": utc_now(),
        "primary_materialization": primary_materialization,
        "reference_materialization": reference_materialization,
        "catalogs": primary_catalogs,
        "materialization_differences": compare_materialization,
        "case_payloads_byte_identical": case_bytes_identical,
        "results_byte_identical": results_identical,
        "price_diagnostics": price_diagnostics,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(CERTIFICATION, certification)
    final = {
        **primary_result,
        "completed_at_utc": utc_now(),
        "primary_cases": file_record(PRIMARY_CASES),
        "reference_cases": file_record(REFERENCE_CASES),
        "primary_results": file_record(PRIMARY_RESULTS),
        "reference_results": file_record(REFERENCE_RESULTS),
        "certification": file_record(CERTIFICATION),
    }
    write_json_exclusive(FINAL_RESULT, final)
    REPORT.write_text(render_report(final, certification), encoding="utf-8", newline="\n")
    write_json_exclusive(
        FINAL_FREEZE,
        {
            "version": "GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1_FINAL_FREEZE_1_0",
            "status": "SEALED_FINAL_FALSIFICATION",
            "sealed_at_utc": utc_now(),
            "verdict": final["verdict"],
            "contract": file_record(CONTRACT),
            "protocol": file_record(PROTOCOL),
            "prepath_freeze": file_record(PREPATH_FREEZE),
            "predecessor_final_seal": file_record(PREDECESSOR_FINAL_SEAL),
            "path_opening": file_record(OPENING),
            "final_result": file_record(FINAL_RESULT),
            "certification": file_record(CERTIFICATION),
            "report": file_record(REPORT),
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    print(canonical_json({"status": final["verdict"], "best": final["best_observed_policy"], "ceiling": final["target_only_hindsight_ceiling"], "result": file_record(FINAL_RESULT)}))
    del frames, primary_rows, reference_rows
    gc.collect()


if __name__ == "__main__":
    main()
