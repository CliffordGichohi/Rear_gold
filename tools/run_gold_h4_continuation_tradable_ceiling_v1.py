from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

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


CONTRACT = ROOT / "GOLD_H4_CONTINUATION_TRADABLE_CEILING_AND_MONETIZATION_AUDIT_CONTRACT_V1.md"
PROTOCOL = ROOT / "research_manifests/gold_h4_continuation_tradable_ceiling_v1_protocol.json"
IMPLEMENTATION = Path(__file__).resolve()
TESTS = ROOT / "tests/test_gold_h4_continuation_tradable_ceiling_v1.py"
PREDECESSOR_SEAL = ROOT / "research_manifests/gold_bidirectional_auction_resolution_v1_final_freeze.json"
PREDECESSOR_RESULTS = ROOT / "research_artifacts/gold_bidirectional_auction_resolution_v1/final_results.json"
PRIMARY_PLANS = ROOT / "research_artifacts/gold_bidirectional_auction_resolution_v1/primary_case_plans.parquet"
REFERENCE_PLANS = ROOT / "research_artifacts/gold_bidirectional_auction_resolution_v1/reference_case_plans.parquet"
PRIMARY_OOF = ROOT / "research_artifacts/gold_bidirectional_auction_resolution_v1/primary_oof_cases.parquet"
REFERENCE_OOF = ROOT / "research_artifacts/gold_bidirectional_auction_resolution_v1/reference_oof_cases.parquet"
ATLAS = ROOT / "research_artifacts/gold_pullback_behavioural_archetypes_v1/primary_archetypes.parquet"
RAW_PRICE = ROOT / "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz"

PREPATH_FREEZE = ROOT / "research_manifests/gold_h4_continuation_tradable_ceiling_v1_prepath_freeze.json"
FINAL_FREEZE = ROOT / "research_manifests/gold_h4_continuation_tradable_ceiling_v1_final_freeze.json"
OUTPUT = ROOT / "research_artifacts/gold_h4_continuation_tradable_ceiling_v1"
OPENING = OUTPUT / "h4_path_opening.json"
PRIMARY_CASES = OUTPUT / "primary_h4_ceiling_cases.parquet"
REFERENCE_CASES = OUTPUT / "reference_h4_ceiling_cases.parquet"
PRIMARY_RESULT = OUTPUT / "primary_result.json"
REFERENCE_RESULT = OUTPUT / "reference_result.json"
FINAL_RESULT = OUTPUT / "final_result.json"
CERTIFICATION = OUTPUT / "reproduction_certification.json"
REPORT = ROOT / "GOLD_H4_CONTINUATION_TRADABLE_CEILING_AND_MONETIZATION_AUDIT_V1_REPORT.md"

EXPECTED = {
    "primary_plans": (5_934_634, "6b2b169629fff1d39ce0cf8dcb786fd60ed102068fa12b51d2929bebc62ff9fd"),
    "reference_plans": (5_934_634, "6b2b169629fff1d39ce0cf8dcb786fd60ed102068fa12b51d2929bebc62ff9fd"),
    "primary_oof": (2_637_838, "88147e2c4ceddd26673af3b0a1cda677d0c578ed31ac04a734d3f40af1a37ff4"),
    "reference_oof": (2_637_838, "88147e2c4ceddd26673af3b0a1cda677d0c578ed31ac04a734d3f40af1a37ff4"),
    "atlas": (1_906_259, "1b48075bbaa4c14873a84cd66f570259eca044813a008e768f9d1ecca41ba856"),
    "raw_price": (258_834_096, "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"),
}

MONTHS = 39
RISK_USD = 50.0
TARGET_R_MONTH = 10.0
MODEL_ID = "CONTINUATION_ONLY_CONTROL"
TIMEFRAME = "H4"

PLAN_COLUMNS = [
    "pullback_id",
    "timeframe",
    "original_direction",
    "decision_date",
    "known_at_utc",
    "deadline_at_utc",
    "model_id",
    "risk_split_id",
    "plan_available",
    "unavailable_reason",
    "traded",
    "first_side",
    "first_direction",
    "first_trigger_at_utc",
    "first_entry_at_utc",
    "first_exit_at_utc",
    "first_exit_reason",
    "first_budget_usd",
    "first_ounces",
    "first_entry_e8",
    "first_stop_e8",
    "first_target_e8",
    "first_risk_e8",
    "first_cost_usd_oz",
    "first_mfe_r",
    "first_mae_r",
    "first_pnl_usd",
    "total_pnl_usd",
    "case_net_r",
    "first_entry_session",
    "final_exit_at_utc",
    "plan_lineage_hash",
]

OOF_COLUMNS = [
    "pullback_id",
    "timeframe",
    "model_id",
    "fold",
    "selected_risk_split_id",
    "decision_date",
    "first_entry_at_utc",
    "final_exit_at_utc",
    "entry_session",
    "traded",
    "retained_after_overlap",
    "overlap_disposition",
    "case_net_r",
    "total_pnl_usd",
    "plan_lineage_hash",
]


CASE_SCHEMA = pa.schema(
    [
        pa.field("audit_id", pa.string(), False),
        pa.field("pullback_id", pa.string(), False),
        pa.field("fold", pa.int32(), False),
        pa.field("decision_date", pa.string(), False),
        pa.field("case_status", pa.string(), False),
        pa.field("overlap_disposition", pa.string(), False),
        pa.field("retained_after_overlap", pa.bool_(), False),
        pa.field("entry_session", pa.string()),
        pa.field("direction", pa.string()),
        pa.field("entry_at_utc", pa.string()),
        pa.field("deadline_at_utc", pa.string()),
        pa.field("entry_e8", pa.int64()),
        pa.field("stop_e8", pa.int64()),
        pa.field("target_e8", pa.int64()),
        pa.field("risk_e8", pa.int64()),
        pa.field("whole_ounces", pa.int64()),
        pa.field("round_trip_cost_usd_oz", pa.float64()),
        pa.field("oracle_r", pa.float64()),
        pa.field("behavioural_oracle_usd", pa.float64()),
        pa.field("observable_entry_perfect_gross_usd", pa.float64()),
        pa.field("stop_feasible_perfect_gross_usd", pa.float64()),
        pa.field("stop_feasible_net_base_usd", pa.float64()),
        pa.field("stop_feasible_net_1p5x_usd", pa.float64()),
        pa.field("stop_feasible_net_base_after_overlap_usd", pa.float64()),
        pa.field("stop_feasible_net_1p5x_after_overlap_usd", pa.float64()),
        pa.field("frozen_execution_gross_pre_overlap_usd", pa.float64()),
        pa.field("frozen_execution_net_pre_overlap_usd", pa.float64()),
        pa.field("frozen_execution_net_after_overlap_usd", pa.float64()),
        pa.field("exit_reason", pa.string()),
        pa.field("exit_at_utc", pa.string()),
        pa.field("first_stop_at_utc", pa.string()),
        pa.field("first_target_at_utc", pa.string()),
        pa.field("full_path_mfe_r", pa.float64()),
        pa.field("full_path_mae_r", pa.float64()),
        pa.field("mfe_before_invalidation_r", pa.float64()),
        pa.field("stopped", pa.bool_()),
        pa.field("stopped_then_plus_1r", pa.bool_()),
        pa.field("stopped_then_plus_2r", pa.bool_()),
        pa.field("stopped_then_original_target", pa.bool_()),
        pa.field("target_truncation_usd", pa.float64()),
        pa.field("time_truncation_usd", pa.float64()),
        pa.field("stop_management_gap_usd", pa.float64()),
        pa.field("structural_stop_constraint_usd", pa.float64()),
        pa.field("transaction_cost_usd", pa.float64()),
        pa.field("signed_overlap_effect_usd", pa.float64()),
        pa.field("plan_lineage_hash", pa.string(), False),
        pa.field("audit_lineage_hash", pa.string(), False),
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
        raise FileNotFoundError(f"Missing {label}: {path}")
    if path.stat().st_size != expected[0] or sha256_file(path) != expected[1]:
        raise ValueError(f"Frozen {label} changed")


def verify_predecessor_seal() -> dict[str, Any]:
    seal = json.loads(PREDECESSOR_SEAL.read_text(encoding="utf-8"))
    if seal.get("status") != "SEALED_FINAL_REJECTION" or seal.get("verdict") != "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE":
        raise ValueError("Predecessor rejection is not intact")
    if seal.get("calendar_2025_values_accessed") is not False or seal.get("calendar_2026_values_accessed") is not False:
        raise ValueError("Predecessor forward lock changed")
    for key in ("contract", "protocol", "preoutcome", "materialization", "development", "final_results", "report"):
        record = seal[key]
        path = ROOT / str(record["path"])
        if not path.exists() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"Predecessor seal record changed: {key}")
    return seal


def preflight() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_H4_PATH_REOPENING" or protocol.get("h4_paths_accessed") is not False:
        raise ValueError("Audit protocol is not frozen")
    seal = verify_predecessor_seal()
    verify_record(PRIMARY_PLANS, EXPECTED["primary_plans"], "primary plans")
    verify_record(REFERENCE_PLANS, EXPECTED["reference_plans"], "reference plans")
    verify_record(PRIMARY_OOF, EXPECTED["primary_oof"], "primary OOF")
    verify_record(REFERENCE_OOF, EXPECTED["reference_oof"], "reference OOF")
    verify_record(ATLAS, EXPECTED["atlas"], "behavioural atlas")
    verify_record(RAW_PRICE, EXPECTED["raw_price"], "raw price")
    if sha256_file(PRIMARY_PLANS) != sha256_file(REFERENCE_PLANS) or sha256_file(PRIMARY_OOF) != sha256_file(REFERENCE_OOF):
        raise ValueError("Predecessor primary/reference payloads differ")
    for required in (CONTRACT, IMPLEMENTATION, TESTS, PREDECESSOR_RESULTS):
        if not required.exists():
            raise FileNotFoundError(required)
    if any(path.exists() for path in (PREPATH_FREEZE, FINAL_FREEZE, OUTPUT, FINAL_RESULT, REPORT)):
        raise FileExistsError("Audit branch already exists")
    return {"protocol": protocol, "predecessor_seal": seal}


def locate(values: Sequence[int], target: int, implementation: str, side: str = "left") -> int:
    if implementation == "primary":
        return int(np.searchsorted(values, target, side=side))
    return bisect.bisect_left(values, target) if side == "left" else bisect.bisect_right(values, target)


def directional_event(
    tree: RangeTree,
    direction: str,
    kind: str,
    left: int,
    right: int,
    level: int,
    implementation: str,
) -> int | None:
    high = (direction == "UP" and kind == "FAVOURABLE") or (direction == "DOWN" and kind == "STOP")
    if high:
        return tree.first_high_primary(left, right, level) if implementation == "primary" else tree.first_high_reference(left, right, level)
    return tree.first_low_primary(left, right, level) if implementation == "primary" else tree.first_low_reference(left, right, level)


def extrema(tree: RangeTree, left: int, right: int, implementation: str) -> tuple[int, int]:
    return tree.extrema_primary(left, right) if implementation == "primary" else tree.extrema_reference(left, right)


def synthetic_proof() -> dict[str, Any]:
    unit = SCALE
    high = np.asarray([111, 108, 105, 112, 109], dtype=np.int64) * unit
    low = np.asarray([89, 99, 88, 100, 101], dtype=np.int64) * unit
    tree = RangeTree(high, low)
    for direction, kind, level in (("UP", "STOP", 90), ("UP", "FAVOURABLE", 110), ("DOWN", "STOP", 110), ("DOWN", "FAVOURABLE", 90)):
        primary = directional_event(tree, direction, kind, 0, len(high), level * unit, "primary")
        reference = directional_event(tree, direction, kind, 0, len(high), level * unit, "reference")
        assert primary == reference
    assert extrema(tree, 0, 5, "primary") == extrema(tree, 0, 5, "reference")
    # Entry-bar stop overrides the favourable extreme in that bar.
    assert directional_event(tree, "UP", "STOP", 0, 5, 90 * unit, "primary") == 0
    # A later stop permits only extrema from complete prior bars.
    later_stop = directional_event(tree, "UP", "STOP", 1, 5, 90 * unit, "primary")
    assert later_stop == 2
    before_high, _ = extrema(tree, 1, later_stop, "primary")
    assert before_high == 108 * unit
    return {"status": "PASS_SYNTHETIC_STOP_FIRST_AND_PREINVALIDATION_CEILING_PROOF", "event_comparisons": 4, "extrema_comparisons": 1}


def seal_prepath(audit: Mapping[str, Any], proof: Mapping[str, Any]) -> None:
    write_json_exclusive(
        PREPATH_FREEZE,
        {
            "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_PREPATH_FREEZE_1_0",
            "status": "SEALED_BEFORE_H4_PATH_REOPENING",
            "sealed_at_utc": utc_now(),
            "controls": {
                "contract": file_record(CONTRACT),
                "protocol": file_record(PROTOCOL),
                "implementation": file_record(IMPLEMENTATION),
                "tests": file_record(TESTS),
                "predecessor_final_seal": file_record(PREDECESSOR_SEAL),
            },
            "sources": {
                "primary_plans": file_record(PRIMARY_PLANS),
                "reference_plans": file_record(REFERENCE_PLANS),
                "primary_oof": file_record(PRIMARY_OOF),
                "reference_oof": file_record(REFERENCE_OOF),
                "atlas": file_record(ATLAS),
                "raw_price": file_record(RAW_PRICE),
            },
            "expected_population": {"oof": 424, "no_trade": 176, "executable": 248, "overlap_skips": 50, "retained": 198},
            "synthetic_proof": dict(proof),
            "h4_paths_accessed": False,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )


def write_parquet(rows: Sequence[Mapping[str, Any]], destination: Path) -> None:
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
        row_group_size=512,
    )
    temporary.replace(destination)


def ns_event(frame: Frame, index: int | None) -> str | None:
    return None if index is None else ns_iso(int(frame.close_ns[index]))


def load_population(plan_path: Path, oof_path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, float | None], dict[str, Any]]:
    plan_rows = [
        row
        for row in pq.read_table(plan_path, columns=PLAN_COLUMNS).to_pylist()
        if str(row["timeframe"]) == TIMEFRAME and str(row["model_id"]) == MODEL_ID
    ]
    oof_rows = [
        row
        for row in pq.read_table(oof_path, columns=OOF_COLUMNS).to_pylist()
        if str(row["timeframe"]) == TIMEFRAME and str(row["model_id"]) == MODEL_ID
    ]
    if len(plan_rows) != 444 or len(oof_rows) != 424:
        raise ValueError({"H4_control_plans": len(plan_rows), "H4_control_oof": len(oof_rows)})
    plans = {str(row["pullback_id"]): row for row in plan_rows}
    if len(plans) != 444 or len({str(row["pullback_id"]) for row in oof_rows}) != 424:
        raise ValueError("H4 population identities are duplicated")
    for row in oof_rows:
        identity = str(row["pullback_id"])
        plan = plans.get(identity)
        if plan is None:
            raise ValueError(f"Missing H4 plan: {identity}")
        if str(row["selected_risk_split_id"]) != "FULL_50" or str(plan["risk_split_id"]) != "FULL_50":
            raise ValueError("Continuation control risk identity changed")
        if str(row["plan_lineage_hash"]) != str(plan["plan_lineage_hash"]):
            raise ValueError(f"OOF/plan lineage mismatch: {identity}")
        if bool(row["traded"]) != bool(plan["traded"]):
            raise ValueError(f"OOF/plan trade mismatch: {identity}")
    counts = Counter(
        "RETAINED" if bool(row["retained_after_overlap"]) else "OVERLAP" if str(row["overlap_disposition"]) == "SKIPPED_OVERLAP" else "NO_TRADE" if not bool(row["traded"]) else "OTHER"
        for row in oof_rows
    )
    if counts != Counter({"RETAINED": 198, "NO_TRADE": 176, "OVERLAP": 50}):
        raise ValueError(f"Frozen H4 disposition changed: {counts}")
    atlas_rows = pq.read_table(ATLAS, columns=["pullback_id", "oracle_r"]).to_pylist()
    oracle = {str(row["pullback_id"]): finite(row.get("oracle_r")) for row in atlas_rows}
    if len(oracle) != 8653:
        raise ValueError("Oracle identity population changed")
    oof_rows.sort(key=lambda row: (str(row["decision_date"]), str(row["pullback_id"])))
    return oof_rows, plans, oracle, {"plan_rows": len(plan_rows), "oof_rows": len(oof_rows), "dispositions": dict(sorted(counts.items()))}


def empty_case(oof: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {field.name: None for field in CASE_SCHEMA}
    row.update(
        {
            "audit_id": canonical_hash([oof["pullback_id"], "H4_CEILING_V1"]),
            "pullback_id": str(oof["pullback_id"]),
            "fold": int(oof["fold"]),
            "decision_date": str(oof["decision_date"]),
            "case_status": "NO_TRADE",
            "overlap_disposition": str(oof["overlap_disposition"]),
            "retained_after_overlap": False,
            "entry_session": oof.get("entry_session"),
            "plan_lineage_hash": str(plan["plan_lineage_hash"]),
        }
    )
    row["audit_lineage_hash"] = canonical_hash([row["audit_id"], row["case_status"], row["plan_lineage_hash"]])
    return row


def audit_executable_case(
    oof: Mapping[str, Any],
    plan: Mapping[str, Any],
    oracle_r: float | None,
    m1: Frame,
    tree: RangeTree,
    invalid_prefix: np.ndarray,
    implementation: str,
) -> dict[str, Any]:
    identity = str(oof["pullback_id"])
    entry_ns = parse_ns(str(plan["first_entry_at_utc"]))
    deadline_ns = parse_ns(str(plan["deadline_at_utc"]))
    left = locate(m1.open_ns, entry_ns, implementation, "left")
    right = locate(m1.close_ns, deadline_ns, implementation, "right")
    if left >= len(m1.open_ns) or int(m1.open_ns[left]) != entry_ns:
        raise ValueError(f"Missing exact M1 entry: {identity}")
    if right <= left or int(m1.close_ns[right - 1]) != deadline_ns:
        raise ValueError(f"Incomplete deadline path: {identity}")
    if int(invalid_prefix[right] - invalid_prefix[left]) != 0:
        raise ValueError(f"Invalid M1 path: {identity}")
    direction = str(plan["first_direction"])
    if direction not in {"UP", "DOWN"} or str(plan["first_side"]) != "TREND":
        raise ValueError(f"Invalid continuation direction: {identity}")
    sign = 1 if direction == "UP" else -1
    entry = int(plan["first_entry_e8"])
    stop = int(plan["first_stop_e8"])
    target = int(plan["first_target_e8"])
    risk = int(plan["first_risk_e8"])
    ounces = int(plan["first_ounces"])
    cost_per_ounce = float(plan["first_cost_usd_oz"])
    if int(m1.open_e8[left]) != entry or risk != sign * (entry - stop) or risk <= 0 or ounces <= 0:
        raise ValueError(f"Frozen execution geometry changed: {identity}")
    maximum, minimum = extrema(tree, left, right, implementation)
    favourable_e8 = max(0, (maximum - entry) if sign > 0 else (entry - minimum))
    adverse_e8 = max(0, (entry - minimum) if sign > 0 else (maximum - entry))
    observable_gross = ounces * favourable_e8 / SCALE
    stop_index = directional_event(tree, direction, "STOP", left, right, stop, implementation)
    target_index = directional_event(tree, direction, "FAVOURABLE", left, right, target, implementation)
    stop_order = stop_index if stop_index is not None else math.inf
    target_order = target_index if target_index is not None else math.inf
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
    actual_gross = ounces * sign * (exit_price - entry) / SCALE
    transaction_cost = ounces * cost_per_ounce
    actual_net = actual_gross - transaction_cost
    if exit_reason != str(plan["first_exit_reason"]) or ns_iso(int(m1.close_ns[exit_index])) != str(plan["first_exit_at_utc"]):
        raise ValueError(f"Frozen exit reproduction failed: {identity}")
    if abs(actual_net - float(plan["total_pnl_usd"])) > 1e-6 or abs(actual_net - float(oof["total_pnl_usd"])) > 1e-6:
        raise ValueError(f"Frozen net PnL reproduction failed: {identity}")

    if stop_index is None:
        before_invalidation_e8 = favourable_e8
        stop_feasible_gross = observable_gross
    elif stop_index == left:
        before_invalidation_e8 = 0
        stop_feasible_gross = ounces * sign * (exit_price - entry) / SCALE
    else:
        before_maximum, before_minimum = extrema(tree, left, int(stop_index), implementation)
        before_invalidation_e8 = max(0, (before_maximum - entry) if sign > 0 else (entry - before_minimum))
        stop_feasible_gross = ounces * before_invalidation_e8 / SCALE
    stop_feasible_net = stop_feasible_gross - transaction_cost
    stop_feasible_net_1p5 = stop_feasible_gross - 1.5 * transaction_cost
    retained = bool(oof["retained_after_overlap"])
    actual_after_overlap = actual_net if retained else 0.0
    stop_feasible_after_overlap = stop_feasible_net if retained else 0.0
    stop_feasible_1p5_after_overlap = stop_feasible_net_1p5 if retained else 0.0

    later_left = int(stop_index) + 1 if stop_index is not None else right
    plus_1r = entry + sign * risk
    plus_2r = entry + sign * 2 * risk
    later_1r = directional_event(tree, direction, "FAVOURABLE", later_left, right, plus_1r, implementation) if later_left < right else None
    later_2r = directional_event(tree, direction, "FAVOURABLE", later_left, right, plus_2r, implementation) if later_left < right else None
    later_target = directional_event(tree, direction, "FAVOURABLE", later_left, right, target, implementation) if later_left < right else None
    oracle_usd = None if oracle_r is None else oracle_r * RISK_USD
    target_truncation = max(0.0, observable_gross - actual_gross) if exit_reason == "KNOWN_TARGET" else 0.0
    time_truncation = max(0.0, observable_gross - actual_gross) if exit_reason == "TIME_EXIT" else 0.0
    stop_gap = max(0.0, stop_feasible_gross - actual_gross) if exit_reason == "STRUCTURAL_STOP" else 0.0
    row = {
        "audit_id": canonical_hash([identity, "H4_CEILING_V1"]),
        "pullback_id": identity,
        "fold": int(oof["fold"]),
        "decision_date": str(oof["decision_date"]),
        "case_status": "EXECUTABLE",
        "overlap_disposition": str(oof["overlap_disposition"]),
        "retained_after_overlap": retained,
        "entry_session": str(oof.get("entry_session") or plan.get("first_entry_session") or "UNKNOWN"),
        "direction": direction,
        "entry_at_utc": ns_iso(entry_ns),
        "deadline_at_utc": ns_iso(deadline_ns),
        "entry_e8": entry,
        "stop_e8": stop,
        "target_e8": target,
        "risk_e8": risk,
        "whole_ounces": ounces,
        "round_trip_cost_usd_oz": cost_per_ounce,
        "oracle_r": oracle_r,
        "behavioural_oracle_usd": oracle_usd,
        "observable_entry_perfect_gross_usd": float(observable_gross),
        "stop_feasible_perfect_gross_usd": float(stop_feasible_gross),
        "stop_feasible_net_base_usd": float(stop_feasible_net),
        "stop_feasible_net_1p5x_usd": float(stop_feasible_net_1p5),
        "stop_feasible_net_base_after_overlap_usd": float(stop_feasible_after_overlap),
        "stop_feasible_net_1p5x_after_overlap_usd": float(stop_feasible_1p5_after_overlap),
        "frozen_execution_gross_pre_overlap_usd": float(actual_gross),
        "frozen_execution_net_pre_overlap_usd": float(actual_net),
        "frozen_execution_net_after_overlap_usd": float(actual_after_overlap),
        "exit_reason": exit_reason,
        "exit_at_utc": ns_iso(int(m1.close_ns[exit_index])),
        "first_stop_at_utc": ns_event(m1, stop_index),
        "first_target_at_utc": ns_event(m1, target_index),
        "full_path_mfe_r": favourable_e8 / risk,
        "full_path_mae_r": adverse_e8 / risk,
        "mfe_before_invalidation_r": before_invalidation_e8 / risk,
        "stopped": stop_index is not None and stop_order <= target_order,
        "stopped_then_plus_1r": bool(stop_index is not None and later_1r is not None),
        "stopped_then_plus_2r": bool(stop_index is not None and later_2r is not None),
        "stopped_then_original_target": bool(stop_index is not None and later_target is not None),
        "target_truncation_usd": float(target_truncation),
        "time_truncation_usd": float(time_truncation),
        "stop_management_gap_usd": float(stop_gap),
        "structural_stop_constraint_usd": float(observable_gross - stop_feasible_gross),
        "transaction_cost_usd": float(transaction_cost),
        "signed_overlap_effect_usd": float(actual_after_overlap - actual_net),
        "plan_lineage_hash": str(plan["plan_lineage_hash"]),
        "audit_lineage_hash": "",
    }
    row["audit_lineage_hash"] = canonical_hash(
        [
            row["audit_id"],
            plan["plan_lineage_hash"],
            left,
            right,
            stop_index,
            target_index,
            exit_index,
            row["observable_entry_perfect_gross_usd"],
            row["stop_feasible_perfect_gross_usd"],
            row["frozen_execution_net_after_overlap_usd"],
        ]
    )
    return row


def materialize(
    plan_path: Path,
    oof_path: Path,
    destination: Path,
    m1: Frame,
    implementation: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    oof_rows, plans, oracle, population = load_population(plan_path, oof_path)
    tree = RangeTree(m1.high_e8, m1.low_e8)
    invalid_prefix = np.concatenate(([0], np.cumsum(~m1.valid.astype(bool), dtype=np.int64)))
    output: list[dict[str, Any]] = []
    exits: Counter[str] = Counter()
    for oof in oof_rows:
        identity = str(oof["pullback_id"])
        plan = plans[identity]
        if not bool(oof["traded"]):
            output.append(empty_case(oof, plan))
            continue
        row = audit_executable_case(oof, plan, oracle.get(identity), m1, tree, invalid_prefix, implementation)
        output.append(row)
        exits[str(row["exit_reason"])] += 1
    if len(output) != 424 or sum(row["case_status"] == "EXECUTABLE" for row in output) != 248:
        raise ValueError("Audit population changed during materialization")
    if sum(bool(row["retained_after_overlap"]) for row in output) != 198:
        raise ValueError("Retained population changed")
    if any(row["case_status"] == "EXECUTABLE" and row["oracle_r"] is None for row in output):
        raise ValueError("Executable case lacks sealed oracle")
    output.sort(key=lambda row: (row["decision_date"], row["pullback_id"]))
    write_parquet(output, destination)
    checksum = canonical_hash([[row[name] for name in CASE_SCHEMA.names] for row in output])
    diagnostics = {
        "implementation": implementation,
        "population": population,
        "output_rows": len(output),
        "executable": sum(row["case_status"] == "EXECUTABLE" for row in output),
        "retained": sum(bool(row["retained_after_overlap"]) for row in output),
        "exit_counts": dict(sorted(exits.items())),
        "complete_row_checksum": checksum,
        "output": file_record(destination),
    }
    return output, diagnostics


def distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p25": None, "p75": None, "minimum": None, "maximum": None}
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": len(values),
        "mean": rounded(float(np.mean(array))),
        "median": rounded(float(np.median(array))),
        "p25": rounded(float(np.quantile(array, 0.25))),
        "p75": rounded(float(np.quantile(array, 0.75))),
        "minimum": rounded(float(np.min(array))),
        "maximum": rounded(float(np.max(array))),
    }


def stage(name: str, values: Sequence[float], oracle_total: float) -> dict[str, Any]:
    total = float(sum(values))
    total_r = total / RISK_USD
    return {
        "stage": name,
        "cases": len(values),
        "total_usd_at_50_risk": rounded(total, 6),
        "total_r": rounded(total_r),
        "r_per_month": rounded(total_r / MONTHS),
        "usd_per_month_at_50_risk": rounded(total / MONTHS, 6),
        "usd_per_month_at_1pct_risk_linear": rounded(2.0 * total / MONTHS, 6),
        "retention_of_behavioural_oracle_pct": rounded(100.0 * total / oracle_total if oracle_total else None),
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    executable = [row for row in rows if row["case_status"] == "EXECUTABLE"]
    no_trade = [row for row in rows if row["case_status"] == "NO_TRADE"]
    retained = [row for row in executable if bool(row["retained_after_overlap"])]
    skipped = [row for row in executable if not bool(row["retained_after_overlap"])]
    if (len(rows), len(executable), len(no_trade), len(retained), len(skipped)) != (424, 248, 176, 198, 50):
        raise ValueError("Summary population changed")
    fields = {
        "BEHAVIOURAL_ORACLE": "behavioural_oracle_usd",
        "OBSERVABLE_ENTRY_PERFECT_EXIT_GROSS": "observable_entry_perfect_gross_usd",
        "STOP_FEASIBLE_PERFECT_EXIT_GROSS": "stop_feasible_perfect_gross_usd",
        "FROZEN_EXECUTION_GROSS_PRE_OVERLAP": "frozen_execution_gross_pre_overlap_usd",
        "FROZEN_EXECUTION_NET_PRE_OVERLAP": "frozen_execution_net_pre_overlap_usd",
        "FROZEN_EXECUTION_NET_AFTER_OVERLAP": "frozen_execution_net_after_overlap_usd",
    }
    oracle_total = sum(float(row["behavioural_oracle_usd"]) for row in executable)
    main_waterfall = [stage(name, [float(row[column]) for row in executable], oracle_total) for name, column in fields.items()]
    upper_fields = {
        "STOP_FEASIBLE_NET_BASE_COST": "stop_feasible_net_base_usd",
        "STOP_FEASIBLE_NET_1P5X_COST": "stop_feasible_net_1p5x_usd",
        "STOP_FEASIBLE_NET_BASE_COST_AFTER_OVERLAP": "stop_feasible_net_base_after_overlap_usd",
        "STOP_FEASIBLE_NET_1P5X_COST_AFTER_OVERLAP": "stop_feasible_net_1p5x_after_overlap_usd",
    }
    upper_bound = [stage(name, [float(row[column]) for row in executable], oracle_total) for name, column in upper_fields.items()]
    by_stage = {item["stage"]: item for item in main_waterfall + upper_bound}

    exit_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in executable:
        exit_groups[str(row["exit_reason"])].append(row)
    exit_attribution: dict[str, Any] = {}
    for reason, group in sorted(exit_groups.items()):
        gaps = [float(row["stop_feasible_perfect_gross_usd"]) - float(row["frozen_execution_gross_pre_overlap_usd"]) for row in group]
        exit_attribution[reason] = {
            "cases": len(group),
            "stage_c_to_d_gap_usd": rounded(sum(gaps), 6),
            "stage_c_to_d_gap_r": rounded(sum(gaps) / RISK_USD),
            "mean_gap_r_per_case": rounded(sum(gaps) / RISK_USD / len(group)),
        }
    stopped = [row for row in executable if bool(row["stopped"])]
    target_cases = exit_groups.get("KNOWN_TARGET", [])
    time_cases = exit_groups.get("TIME_EXIT", [])
    stopped_count = len(stopped)
    stop_diagnostics = {
        "stopped_cases": stopped_count,
        "stopped_fraction": rounded(stopped_count / len(executable)),
        "stopped_then_plus_1r_cases": sum(bool(row["stopped_then_plus_1r"]) for row in stopped),
        "stopped_then_plus_1r_fraction": rounded(sum(bool(row["stopped_then_plus_1r"]) for row in stopped) / stopped_count if stopped_count else None),
        "stopped_then_plus_2r_cases": sum(bool(row["stopped_then_plus_2r"]) for row in stopped),
        "stopped_then_plus_2r_fraction": rounded(sum(bool(row["stopped_then_plus_2r"]) for row in stopped) / stopped_count if stopped_count else None),
        "stopped_then_original_target_cases": sum(bool(row["stopped_then_original_target"]) for row in stopped),
        "stopped_then_original_target_fraction": rounded(sum(bool(row["stopped_then_original_target"]) for row in stopped) / stopped_count if stopped_count else None),
        "full_path_mfe_r": distribution([float(row["full_path_mfe_r"]) for row in executable]),
        "full_path_mae_r": distribution([float(row["full_path_mae_r"]) for row in executable]),
        "mfe_before_invalidation_r_all": distribution([float(row["mfe_before_invalidation_r"]) for row in executable]),
        "mfe_before_invalidation_r_stopped": distribution([float(row["mfe_before_invalidation_r"]) for row in stopped]),
    }
    truncation = {
        "target_exit_cases": len(target_cases),
        "target_truncation_total_usd": rounded(sum(float(row["target_truncation_usd"]) for row in target_cases), 6),
        "target_truncation_total_r": rounded(sum(float(row["target_truncation_usd"]) for row in target_cases) / RISK_USD),
        "target_truncation_per_case_r": distribution([float(row["target_truncation_usd"]) / RISK_USD for row in target_cases]),
        "time_exit_cases": len(time_cases),
        "time_truncation_total_usd": rounded(sum(float(row["time_truncation_usd"]) for row in time_cases), 6),
        "time_truncation_total_r": rounded(sum(float(row["time_truncation_usd"]) for row in time_cases) / RISK_USD),
        "time_truncation_per_case_r": distribution([float(row["time_truncation_usd"]) / RISK_USD for row in time_cases]),
    }
    losses = {
        "STRUCTURAL_STOP_CONSTRAINT": sum(float(row["structural_stop_constraint_usd"]) for row in executable) / RISK_USD,
        "STOP_EXIT_CAPTURE_GAP": sum(float(row["stop_management_gap_usd"]) for row in stopped) / RISK_USD,
        "TARGET_EXIT_CAPTURE_GAP": sum(float(row["stop_feasible_perfect_gross_usd"]) - float(row["frozen_execution_gross_pre_overlap_usd"]) for row in target_cases) / RISK_USD,
        "TIME_EXIT_CAPTURE_GAP": sum(float(row["stop_feasible_perfect_gross_usd"]) - float(row["frozen_execution_gross_pre_overlap_usd"]) for row in time_cases) / RISK_USD,
        "TRANSACTION_COST": sum(float(row["transaction_cost_usd"]) for row in executable) / RISK_USD,
        "OVERLAP": max(0.0, sum(float(row["frozen_execution_net_pre_overlap_usd"]) - float(row["frozen_execution_net_after_overlap_usd"]) for row in executable) / RISK_USD),
    }
    losses = {name: rounded(value) for name, value in losses.items()}
    operational_r_month = float(by_stage["STOP_FEASIBLE_NET_BASE_COST_AFTER_OVERLAP"]["r_per_month"])
    mathematical = float(by_stage["OBSERVABLE_ENTRY_PERFECT_EXIT_GROSS"]["r_per_month"]) >= TARGET_R_MONTH
    operational = operational_r_month >= TARGET_R_MONTH
    demonstrated = float(by_stage["FROZEN_EXECUTION_NET_AFTER_OVERLAP"]["r_per_month"]) >= TARGET_R_MONTH
    if operational:
        dominant = sorted(losses.items(), key=lambda item: (-float(item[1]), item[0]))[0]
        mapping = {
            "STRUCTURAL_STOP_CONSTRAINT": "H4_STOPPED_THEN_CONTINUATION_REENTRY_RESEARCH",
            "STOP_EXIT_CAPTURE_GAP": "H4_STOPPED_THEN_CONTINUATION_REENTRY_RESEARCH",
            "TARGET_EXIT_CAPTURE_GAP": "H4_LIQUIDITY_TARGET_CAPTURE_RESEARCH",
            "TIME_EXIT_CAPTURE_GAP": "H4_TIME_EXIT_CAPTURE_RESEARCH",
            "TRANSACTION_COST": "H4_EXECUTION_COST_REDUCTION_RESEARCH",
            "OVERLAP": "H4_CAMPAIGN_OVERLAP_ALLOCATION_RESEARCH",
        }
        verdict = "UPPER_BOUND_CAPACITY_PRESENT_NOT_DEMONSTRATED"
        recommendation = {
            "action": "RECOMMEND_EXACTLY_ONE_BOUNDED_DIRECTION_WITHOUT_IMPLEMENTATION",
            "dominant_bottleneck": dominant[0],
            "loss_r": dominant[1],
            "bounded_direction": mapping[dominant[0]],
        }
    else:
        verdict = "TERMINATE_GOLD_ONLY_OPTIMIZATION_BRANCH"
        recommendation = {
            "action": "TERMINATE_GOLD_ONLY_OPTIMIZATION_BRANCH",
            "reason": "STOP_FEASIBLE_NET_BASE_COST_AFTER_OVERLAP_BELOW_10R_PER_MONTH",
            "bounded_direction": None,
        }
    predecessor = json.loads(PREDECESSOR_RESULTS.read_text(encoding="utf-8"))
    previous_metric = next(item for item in predecessor["candidate_metrics"] if item["candidate_id"] == "H4::CONTINUATION_ONLY_CONTROL")
    actual_stage = by_stage["FROZEN_EXECUTION_NET_AFTER_OVERLAP"]
    if abs(float(actual_stage["total_usd_at_50_risk"]) - float(previous_metric["net_pnl_usd_at_50_case_risk"])) > 1e-6:
        raise ValueError("Predecessor H4 result was not exactly reproduced")
    result = {
        "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_RESULT_1_0",
        "verdict": verdict,
        "population": {"oof_cases": 424, "no_trade": 176, "matched_executable": 248, "overlap_skips": 50, "retained": 198, "months": MONTHS},
        "main_waterfall": main_waterfall,
        "operational_upper_bound": upper_bound,
        "incremental_loss_r": {
            "behavioural_oracle_to_observable_entry": rounded((oracle_total - sum(float(row["observable_entry_perfect_gross_usd"]) for row in executable)) / RISK_USD),
            "observable_entry_to_stop_feasible": losses["STRUCTURAL_STOP_CONSTRAINT"],
            "stop_feasible_to_frozen_gross": rounded(sum(float(row["stop_feasible_perfect_gross_usd"]) - float(row["frozen_execution_gross_pre_overlap_usd"]) for row in executable) / RISK_USD),
            "frozen_gross_to_net_cost": losses["TRANSACTION_COST"],
            "net_pre_overlap_to_after_overlap": rounded(sum(float(row["frozen_execution_net_pre_overlap_usd"]) - float(row["frozen_execution_net_after_overlap_usd"]) for row in executable) / RISK_USD),
        },
        "exit_attribution": exit_attribution,
        "stop_diagnostics": stop_diagnostics,
        "target_and_time_truncation": truncation,
        "bottleneck_loss_r": losses,
        "feasibility": {
            "target_r_per_month": TARGET_R_MONTH,
            "mathematical_capacity_present": mathematical,
            "stop_feasible_operational_capacity_present": operational,
            "demonstrated_10r_present": demonstrated,
            "observable_entry_ceiling_r_per_month": by_stage["OBSERVABLE_ENTRY_PERFECT_EXIT_GROSS"]["r_per_month"],
            "stop_feasible_net_after_overlap_r_per_month": operational_r_month,
            "frozen_actual_r_per_month": actual_stage["r_per_month"],
        },
        "recommendation": recommendation,
        "predecessor_reproduction": {
            "expected_total_usd": previous_metric["net_pnl_usd_at_50_case_risk"],
            "reproduced_total_usd": actual_stage["total_usd_at_50_risk"],
            "expected_r_per_month": previous_metric["r_per_month"],
            "reproduced_r_per_month": actual_stage["r_per_month"],
        },
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    return result


def fmt(value: Any, places: int = 3) -> str:
    number = finite(value)
    return "n/a" if number is None else f"{number:.{places}f}"


def render_report(result: Mapping[str, Any], certification: Mapping[str, Any]) -> str:
    lines = [
        "# Gold H4 Continuation Tradable-Ceiling and Monetization Audit V1",
        "",
        f"Verdict: **{result['verdict']}**",
        "",
        "This audit did not create or test a new strategy. It measured the frozen H4 continuation control against increasingly realistic ceilings on the same 248 executable OOF cases; 176 no-trigger cases remained visible, and the 50 overlap-skipped cases received zero at post-overlap stages.",
        "",
        "## Matched-case waterfall",
        "",
        "| Stage | Total R | R/month | $/month at $50 | $/month at 1% | Oracle retained |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in result["main_waterfall"]:
        lines.append(
            f"| {item['stage']} | {fmt(item['total_r'], 2)} | {fmt(item['r_per_month'], 3)} | ${fmt(item['usd_per_month_at_50_risk'], 2)} | ${fmt(item['usd_per_month_at_1pct_risk_linear'], 2)} | {fmt(item['retention_of_behavioural_oracle_pct'], 2)}% |"
        )
    lines.extend(["", "## Stop-feasible operational upper bound", ""])
    for item in result["operational_upper_bound"]:
        lines.append(
            f"- `{item['stage']}`: {fmt(item['total_r'], 2)}R total, {fmt(item['r_per_month'], 3)}R/month, ${fmt(item['usd_per_month_at_1pct_risk_linear'], 2)}/month at 1% linear risk."
        )
    stop = result["stop_diagnostics"]
    lines.extend(
        [
            "",
            "## Path findings",
            "",
            f"- Stopped cases: {stop['stopped_cases']} ({fmt(100 * stop['stopped_fraction'], 1)}%).",
            f"- Stopped then +1R: {stop['stopped_then_plus_1r_cases']} ({fmt(100 * stop['stopped_then_plus_1r_fraction'], 1)}% of stopped cases).",
            f"- Stopped then +2R: {stop['stopped_then_plus_2r_cases']} ({fmt(100 * stop['stopped_then_plus_2r_fraction'], 1)}%).",
            f"- Stopped then original target: {stop['stopped_then_original_target_cases']} ({fmt(100 * stop['stopped_then_original_target_fraction'], 1)}%).",
            f"- Full-path MFE: mean {fmt(stop['full_path_mfe_r']['mean'], 2)}R, median {fmt(stop['full_path_mfe_r']['median'], 2)}R.",
            f"- MFE before invalidation: mean {fmt(stop['mfe_before_invalidation_r_all']['mean'], 2)}R; stopped-case median {fmt(stop['mfe_before_invalidation_r_stopped']['median'], 2)}R.",
            "",
            "## Feasibility decision",
            "",
            f"- Mathematical observable-entry ceiling >=10R/month: **{str(result['feasibility']['mathematical_capacity_present']).lower()}** ({fmt(result['feasibility']['observable_entry_ceiling_r_per_month'], 3)}R/month).",
            f"- Stop-feasible, costed, post-overlap ceiling >=10R/month: **{str(result['feasibility']['stop_feasible_operational_capacity_present']).lower()}** ({fmt(result['feasibility']['stop_feasible_net_after_overlap_r_per_month'], 3)}R/month).",
            f"- Demonstrated frozen execution >=10R/month: **{str(result['feasibility']['demonstrated_10r_present']).lower()}** ({fmt(result['feasibility']['frozen_actual_r_per_month'], 3)}R/month).",
            f"- Required disposition: `{result['recommendation']['action']}`.",
        ]
    )
    if result["recommendation"].get("bounded_direction"):
        lines.append(f"- Exactly one bounded direction, not implemented: `{result['recommendation']['bounded_direction']}`.")
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            f"- Primary/reference per-case payloads byte-identical: {str(certification['case_payloads_byte_identical']).lower()}.",
            f"- Primary/reference result JSON byte-identical: {str(certification['results_byte_identical']).lower()}.",
            "- Predecessor H4 PnL reproduced exactly. Calendar 2025/2026 remained locked. Paid acquisition: $0.00.",
            "- Perfect-exit stages are diagnostic hindsight ceilings, not tradable performance.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    audit = preflight()
    proof = synthetic_proof()
    seal_prepath(audit, proof)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        OPENING,
        {
            "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_PATH_OPENING_1_0",
            "status": "OPENED_ONCE_AFTER_PREPATH_FREEZE",
            "opened_at_utc": utc_now(),
            "prepath_freeze": file_record(PREPATH_FREEZE),
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    frames, price_diagnostics = load_price()
    m1 = frames["M1"]
    primary_rows, primary_diagnostics = materialize(PRIMARY_PLANS, PRIMARY_OOF, PRIMARY_CASES, m1, "primary")
    reference_rows, reference_diagnostics = materialize(REFERENCE_PLANS, REFERENCE_OOF, REFERENCE_CASES, m1, "reference")
    compare_fields = ("population", "output_rows", "executable", "retained", "exit_counts", "complete_row_checksum")
    differences = [name for name in compare_fields if primary_diagnostics[name] != reference_diagnostics[name]]
    case_bytes_identical = sha256_file(PRIMARY_CASES) == sha256_file(REFERENCE_CASES)
    if differences or not case_bytes_identical:
        raise RuntimeError({"status": "FAIL_H4_CEILING_CASE_REPRODUCTION", "differences": differences, "byte_identical": case_bytes_identical})
    primary_result = summarize(primary_rows)
    reference_result = summarize(reference_rows)
    if canonical_json(primary_result) != canonical_json(reference_result):
        raise RuntimeError("FAIL_H4_CEILING_RESULT_REPRODUCTION")
    write_json_exclusive(PRIMARY_RESULT, primary_result)
    write_json_exclusive(REFERENCE_RESULT, reference_result)
    result_bytes_identical = sha256_file(PRIMARY_RESULT) == sha256_file(REFERENCE_RESULT)
    if not result_bytes_identical:
        raise RuntimeError("FAIL_H4_CEILING_RESULT_BYTE_REPRODUCTION")
    certification = {
        "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_CERTIFICATION_1_0",
        "status": "PASS_INDEPENDENT_REPRODUCTION",
        "certified_at_utc": utc_now(),
        "primary": primary_diagnostics,
        "reference": reference_diagnostics,
        "differences": differences,
        "case_payloads_byte_identical": case_bytes_identical,
        "results_byte_identical": result_bytes_identical,
        "price_diagnostics": price_diagnostics,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(CERTIFICATION, certification)
    final = {
        **primary_result,
        "completed_at_utc": utc_now(),
        "reproduction": file_record(CERTIFICATION),
        "primary_cases": file_record(PRIMARY_CASES),
        "reference_cases": file_record(REFERENCE_CASES),
        "primary_result": file_record(PRIMARY_RESULT),
        "reference_result": file_record(REFERENCE_RESULT),
    }
    write_json_exclusive(FINAL_RESULT, final)
    REPORT.write_text(render_report(final, certification), encoding="utf-8", newline="\n")
    write_json_exclusive(
        FINAL_FREEZE,
        {
            "version": "GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1_FINAL_FREEZE_1_0",
            "status": "SEALED_FINAL_AUDIT",
            "sealed_at_utc": utc_now(),
            "verdict": final["verdict"],
            "contract": file_record(CONTRACT),
            "protocol": file_record(PROTOCOL),
            "prepath_freeze": file_record(PREPATH_FREEZE),
            "final_result": file_record(FINAL_RESULT),
            "certification": file_record(CERTIFICATION),
            "report": file_record(REPORT),
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    )
    print(canonical_json({"status": final["verdict"], "feasibility": final["feasibility"], "recommendation": final["recommendation"], "result": file_record(FINAL_RESULT)}))


if __name__ == "__main__":
    main()
