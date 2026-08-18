from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from materialize_gold_point_in_time_auction_state_v1_tape import (
    ROOT, ARTIFACTS, MANIFESTS, SCALE, Frame, Checksums, canonical_hash, file_record,
    load_price, ns_iso, parse_ns, sha256_file, utc_now, write_json_exclusive,
)


TAPE_DIR = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape"
TAPE_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_freeze.json"
EXECUTION_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_outcome_model_policy_execution_freeze.json"
OUTPUT = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_development"
IMPLEMENTATION_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_outcome_implementation_freeze.json"
OPENING = OUTPUT / "development_outcome_opening.json"
PRIMARY = OUTPUT / "primary_checkpoint_outcomes.parquet"
REFERENCE = OUTPUT / "reference_checkpoint_outcomes.parquet"
CERTIFICATION = OUTPUT / "outcome_materialization_certification.json"
OUTCOME_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_outcome_freeze.json"


class RangeTree:
    def __init__(self, high: np.ndarray, low: np.ndarray) -> None:
        size = 1
        while size < len(high): size *= 2
        self.size = size; self.length = len(high)
        self.maximum = np.full(2 * size, np.iinfo(np.int64).min, dtype=np.int64)
        self.minimum = np.full(2 * size, np.iinfo(np.int64).max, dtype=np.int64)
        self.maximum[size:size + len(high)] = high; self.minimum[size:size + len(low)] = low
        for node in range(size - 1, 0, -1):
            self.maximum[node] = max(self.maximum[node * 2], self.maximum[node * 2 + 1])
            self.minimum[node] = min(self.minimum[node * 2], self.minimum[node * 2 + 1])

    def first_high_primary(self, left: int, right: int, threshold: int) -> int | None:
        def search(node: int, node_left: int, node_right: int) -> int | None:
            if node_right <= left or node_left >= right or int(self.maximum[node]) < threshold: return None
            if node_right - node_left == 1: return node_left if node_left < self.length else None
            middle = (node_left + node_right) // 2
            found = search(node * 2, node_left, middle)
            return found if found is not None else search(node * 2 + 1, middle, node_right)
        return search(1, 0, self.size)

    def first_low_primary(self, left: int, right: int, threshold: int) -> int | None:
        def search(node: int, node_left: int, node_right: int) -> int | None:
            if node_right <= left or node_left >= right or int(self.minimum[node]) > threshold: return None
            if node_right - node_left == 1: return node_left if node_left < self.length else None
            middle = (node_left + node_right) // 2
            found = search(node * 2, node_left, middle)
            return found if found is not None else search(node * 2 + 1, middle, node_right)
        return search(1, 0, self.size)

    def _first_reference(self, left: int, right: int, threshold: int, high: bool) -> int | None:
        stack = [(1, 0, self.size)]
        values = self.maximum if high else self.minimum
        while stack:
            node, node_left, node_right = stack.pop()
            impossible = int(values[node]) < threshold if high else int(values[node]) > threshold
            if node_right <= left or node_left >= right or impossible: continue
            if node_right - node_left == 1: return node_left if node_left < self.length else None
            middle = (node_left + node_right) // 2
            stack.append((node * 2 + 1, middle, node_right)); stack.append((node * 2, node_left, middle))
        return None

    def first_high_reference(self, left: int, right: int, threshold: int) -> int | None:
        return self._first_reference(left, right, threshold, True)

    def first_low_reference(self, left: int, right: int, threshold: int) -> int | None:
        return self._first_reference(left, right, threshold, False)

    def extrema_primary(self, left: int, right: int) -> tuple[int, int]:
        maximum = np.iinfo(np.int64).min; minimum = np.iinfo(np.int64).max; left += self.size; right += self.size
        while left < right:
            if left & 1: maximum = max(maximum, int(self.maximum[left])); minimum = min(minimum, int(self.minimum[left])); left += 1
            if right & 1: right -= 1; maximum = max(maximum, int(self.maximum[right])); minimum = min(minimum, int(self.minimum[right]))
            left //= 2; right //= 2
        return int(maximum), int(minimum)

    def extrema_reference(self, left: int, right: int) -> tuple[int, int]:
        def query(node: int, node_left: int, node_right: int) -> tuple[int, int]:
            if node_right <= left or node_left >= right: return np.iinfo(np.int64).min, np.iinfo(np.int64).max
            if left <= node_left and node_right <= right: return int(self.maximum[node]), int(self.minimum[node])
            middle = (node_left + node_right) // 2; a = query(node * 2, node_left, middle); b = query(node * 2 + 1, middle, node_right)
            return max(a[0], b[0]), min(a[1], b[1])
        return query(1, 0, self.size)


def schema() -> pa.Schema:
    return pa.schema([
        pa.field("row_id", pa.string(), False), pa.field("pullback_id", pa.string(), False), pa.field("timeframe", pa.string(), False),
        pa.field("direction", pa.string(), False), pa.field("decision_date", pa.string(), False), pa.field("checkpoint_at_utc", pa.string(), False),
        pa.field("deadline_at_utc", pa.string(), False), pa.field("outcome_available", pa.bool_(), False), pa.field("unavailable_reason", pa.string(), False),
        pa.field("entry_e8", pa.int64()), pa.field("stop_e8", pa.int64()), pa.field("target_e8", pa.int64()), pa.field("risk_e8", pa.int64()),
        pa.field("actual_target_r", pa.float64()), pa.field("spread_usd_oz", pa.float64()), pa.field("spread_fallback", pa.bool_()),
        pa.field("round_trip_cost_usd_oz", pa.float64()), pa.field("whole_ounces_at_50", pa.int64()),
        pa.field("primary_class", pa.string(), False), pa.field("continuation_1r_before_stop", pa.bool_()), pa.field("two_r_before_stop", pa.bool_()),
        pa.field("mfe_r", pa.float64()), pa.field("mae_r", pa.float64()), pa.field("time_to_first_passage_minutes", pa.float64()),
        pa.field("first_passage_censored", pa.bool_()), pa.field("first_stop_at_utc", pa.string()), pa.field("first_1r_at_utc", pa.string()),
        pa.field("first_2r_at_utc", pa.string()), pa.field("first_target_at_utc", pa.string()), pa.field("stop_then_1r_before_deadline", pa.bool_()),
        pa.field("stop_then_target_before_deadline", pa.bool_()), pa.field("terminal_exit_at_utc", pa.string()), pa.field("terminal_exit_reason", pa.string()),
        pa.field("first_stop_fill_e8", pa.int64()), pa.field("terminal_exit_e8", pa.int64()), pa.field("gross_terminal_r", pa.float64()), pa.field("terminal_net_r", pa.float64()),
        pa.field("terminal_net_r_cost_1p5x", pa.float64()), pa.field("terminal_net_r_cost_2x", pa.float64()), pa.field("outcome_lineage_hash", pa.string(), False),
    ])


def preflight() -> dict[str, Any]:
    tape = json.loads(TAPE_FREEZE.read_text(encoding="utf-8"))
    execution = json.loads(EXECUTION_FREEZE.read_text(encoding="utf-8"))
    if tape.get("status") != "PASS_OUTCOME_BLIND_DECISION_TAPE_MATERIALIZATION" or not tape.get("byte_identical"):
        raise ValueError("Outcome-blind tape has not passed")
    if execution.get("status") != "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_OPENING" or execution.get("development_outcomes_accessed") is not False:
        raise ValueError("Outcome/model/policy freeze invalid")
    for key, path in (("primary", TAPE_DIR / "primary_checkpoint_features.parquet"), ("reference", TAPE_DIR / "reference_checkpoint_features.parquet")):
        frozen = tape["artifacts"][key]
        if path.stat().st_size != frozen["bytes"] or sha256_file(path) != frozen["sha256"]: raise ValueError(f"Tape source changed: {key}")
    if any(path.exists() for path in (OPENING, PRIMARY, REFERENCE, CERTIFICATION, OUTCOME_FREEZE, IMPLEMENTATION_FREEZE)):
        raise FileExistsError("Outcome materialization or opening already exists")
    return tape


def synthetic_proof() -> dict[str, Any]:
    high = np.asarray([100, 104, 110, 106, 120], dtype=np.int64); low = np.asarray([90, 88, 95, 80, 100], dtype=np.int64)
    tree = RangeTree(high, low)
    for left, right, threshold in ((0, 5, 109), (1, 4, 103), (3, 5, 119)):
        assert tree.first_high_primary(left, right, threshold) == tree.first_high_reference(left, right, threshold)
    for left, right, threshold in ((0, 5, 89), (2, 5, 85), (0, 3, 89)):
        assert tree.first_low_primary(left, right, threshold) == tree.first_low_reference(left, right, threshold)
    for left, right in ((0, 5), (1, 4), (2, 3)):
        assert tree.extrema_primary(left, right) == tree.extrema_reference(left, right)
    return {"status": "PASS_SYNTHETIC_FIRST_PASSAGE_AND_EXTREMA_PROOF", "cases": 9}


def implementation_freeze(tape: Mapping[str, Any], proof: Mapping[str, Any]) -> None:
    write_json_exclusive(IMPLEMENTATION_FREEZE, {
        "version": "GOLD_PIT_AUCTION_STATE_V1_OUTCOME_IMPLEMENTATION_FREEZE_1_0", "status": "SEALED_BEFORE_DEVELOPMENT_OUTCOME_OPENING", "sealed_at_utc": utc_now(),
        "controls": {"tape": file_record(TAPE_FREEZE), "execution": file_record(EXECUTION_FREEZE)}, "implementation": file_record(Path(__file__).resolve()),
        "synthetic_proof": dict(proof), "checkpoint_rows": tape["checkpoint_rows"], "development_outcomes_accessed": False,
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    })


def empty_outcome(row: Mapping[str, Any], reason: str, facts: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "row_id": str(row["row_id"]), "pullback_id": str(row["pullback_id"]), "timeframe": str(row["timeframe"]), "direction": str(row["direction"]),
        "decision_date": str(row["decision_date"]), "checkpoint_at_utc": str(row["checkpoint_at_utc"]), "deadline_at_utc": str(row["deadline_at_utc"]),
        "outcome_available": False, "unavailable_reason": reason, "primary_class": "UNAVAILABLE_TECHNICAL", "outcome_lineage_hash": canonical_hash([row["row_id"], reason]),
    }
    if facts:
        result.update(facts)
    for field in schema():
        if field.name not in result: result[field.name] = None
    return result


def event_time(frame: Frame, index: int | None) -> str | None:
    return ns_iso(int(frame.close_ns[index])) if index is not None else None


def outcome_row(row: Mapping[str, Any], frame: Frame, tree: RangeTree, invalid_prefix: np.ndarray, implementation: str) -> dict[str, Any]:
    checkpoint = parse_ns(str(row["checkpoint_at_utc"])); deadline = parse_ns(str(row["deadline_at_utc"])); direction = str(row["direction"]); sign = 1 if direction == "UP" else -1
    entry_index = int(np.searchsorted(frame.open_ns, checkpoint, side="left")) if implementation == "primary" else bisect.bisect_left(frame.open_ns, checkpoint)
    if entry_index >= len(frame.open_ns) or int(frame.open_ns[entry_index]) != checkpoint: return empty_outcome(row, "MISSING_EXACT_ENTRY_M1")
    entry = int(frame.open_e8[entry_index]); raw_spread = float(frame.spread[entry_index]); fallback = not math.isfinite(raw_spread) or raw_spread < 0; spread = 0.30 if fallback else raw_spread
    cost = spread + 0.07 + 0.10; entry_facts = {"entry_e8": entry, "spread_usd_oz": spread, "spread_fallback": fallback, "round_trip_cost_usd_oz": cost}
    right = int(np.searchsorted(frame.close_ns, deadline, side="right")) if implementation == "primary" else bisect.bisect_right(frame.close_ns, deadline)
    if right <= entry_index or int(frame.close_ns[right - 1]) != deadline: return empty_outcome(row, "INCOMPLETE_M1_DEADLINE_PATH", entry_facts)
    if int(invalid_prefix[right] - invalid_prefix[entry_index]) != 0: return empty_outcome(row, "INVALID_M1_IN_PATH", entry_facts)
    if row.get("structural_stop_e8") is None or row.get("liquidity_target_e8") is None: return empty_outcome(row, "MISSING_POINT_IN_TIME_GEOMETRY", entry_facts)
    stop = int(row["structural_stop_e8"]); target = int(row["liquidity_target_e8"]); geometry_facts = {**entry_facts, "stop_e8": stop, "target_e8": target}
    risk = sign * (entry - stop); room = sign * (target - entry)
    if risk <= 0: return empty_outcome(row, "STOP_NOT_ADVERSE_TO_ACTUAL_FILL", geometry_facts)
    if room < risk: return empty_outcome(row, "ACTUAL_TARGET_ROOM_BELOW_1R", {**geometry_facts, "risk_e8": risk, "actual_target_r": room / risk})
    risk_usd = risk / SCALE; ounces = math.floor(50.0 / (risk_usd + cost) + 1e-12)
    if ounces < 1: return empty_outcome(row, "MINIMUM_ONE_OUNCE_EXCEEDS_50_RISK", {**geometry_facts, "risk_e8": risk, "actual_target_r": room / risk, "whole_ounces_at_50": ounces})
    one = entry + sign * risk; two = entry + sign * 2 * risk
    if direction == "UP":
        stop_index = tree.first_low_primary(entry_index, right, stop) if implementation == "primary" else tree.first_low_reference(entry_index, right, stop)
        one_index = tree.first_high_primary(entry_index, right, one) if implementation == "primary" else tree.first_high_reference(entry_index, right, one)
        two_index = tree.first_high_primary(entry_index, right, two) if implementation == "primary" else tree.first_high_reference(entry_index, right, two)
        target_index = tree.first_high_primary(entry_index, right, target) if implementation == "primary" else tree.first_high_reference(entry_index, right, target)
    else:
        stop_index = tree.first_high_primary(entry_index, right, stop) if implementation == "primary" else tree.first_high_reference(entry_index, right, stop)
        one_index = tree.first_low_primary(entry_index, right, one) if implementation == "primary" else tree.first_low_reference(entry_index, right, one)
        two_index = tree.first_low_primary(entry_index, right, two) if implementation == "primary" else tree.first_low_reference(entry_index, right, two)
        target_index = tree.first_low_primary(entry_index, right, target) if implementation == "primary" else tree.first_low_reference(entry_index, right, target)
    stop_order = stop_index if stop_index is not None else math.inf; one_order = one_index if one_index is not None else math.inf; two_order = two_index if two_index is not None else math.inf; target_order = target_index if target_index is not None else math.inf
    continuation = one_order < stop_order; failure = stop_order <= one_order and stop_order != math.inf
    primary_class = "CONTINUATION_1R_FIRST" if continuation else "FAILURE_STOP_FIRST" if failure else "UNRESOLVED"
    two_before = bool(two_order < stop_order)
    maximum, minimum = tree.extrema_primary(entry_index, right) if implementation == "primary" else tree.extrema_reference(entry_index, right)
    mfe = ((maximum - entry) if sign > 0 else (entry - minimum)) / risk; mae = ((entry - minimum) if sign > 0 else (maximum - entry)) / risk
    passage_index = min(stop_order, one_order)
    censored = passage_index == math.inf
    passage_minutes = (deadline - checkpoint) / 60_000_000_000 if censored else (int(frame.close_ns[int(passage_index)]) - checkpoint) / 60_000_000_000
    if stop_order <= target_order and stop_order != math.inf:
        exit_index = int(stop_order); opened = int(frame.open_e8[exit_index]); exit_price = min(stop, opened) if direction == "UP" else max(stop, opened); exit_reason = "STRUCTURAL_EXIT"
    elif target_order != math.inf:
        exit_index = int(target_order); exit_price = target; exit_reason = "LIQUIDITY_TARGET_EXIT"
    else:
        exit_index = right - 1; exit_price = int(frame.close_e8[exit_index]); exit_reason = "TIME_EXIT"
    gross = sign * (exit_price - entry) / risk; cost_r = cost / risk_usd
    later_left = int(stop_order) + 1 if stop_order != math.inf else right
    if later_left < right:
        if direction == "UP":
            later_one = tree.first_high_primary(later_left, right, one) if implementation == "primary" else tree.first_high_reference(later_left, right, one)
            later_target = tree.first_high_primary(later_left, right, target) if implementation == "primary" else tree.first_high_reference(later_left, right, target)
        else:
            later_one = tree.first_low_primary(later_left, right, one) if implementation == "primary" else tree.first_low_reference(later_left, right, one)
            later_target = tree.first_low_primary(later_left, right, target) if implementation == "primary" else tree.first_low_reference(later_left, right, target)
    else: later_one = later_target = None
    result = {
        "row_id": str(row["row_id"]), "pullback_id": str(row["pullback_id"]), "timeframe": str(row["timeframe"]), "direction": direction,
        "decision_date": str(row["decision_date"]), "checkpoint_at_utc": str(row["checkpoint_at_utc"]), "deadline_at_utc": str(row["deadline_at_utc"]),
        "outcome_available": True, "unavailable_reason": "", "entry_e8": entry, "stop_e8": stop, "target_e8": target, "risk_e8": risk,
        "actual_target_r": room / risk, "spread_usd_oz": spread, "spread_fallback": fallback, "round_trip_cost_usd_oz": cost, "whole_ounces_at_50": ounces,
        "primary_class": primary_class, "continuation_1r_before_stop": continuation, "two_r_before_stop": two_before, "mfe_r": mfe, "mae_r": mae,
        "time_to_first_passage_minutes": passage_minutes, "first_passage_censored": censored, "first_stop_at_utc": event_time(frame, stop_index),
        "first_1r_at_utc": event_time(frame, one_index), "first_2r_at_utc": event_time(frame, two_index), "first_target_at_utc": event_time(frame, target_index),
        "stop_then_1r_before_deadline": later_one is not None, "stop_then_target_before_deadline": later_target is not None,
        "terminal_exit_at_utc": event_time(frame, exit_index), "terminal_exit_reason": exit_reason,
        "first_stop_fill_e8": (min(stop, int(frame.open_e8[int(stop_order)])) if direction == "UP" else max(stop, int(frame.open_e8[int(stop_order)]))) if stop_order != math.inf else None,
        "terminal_exit_e8": exit_price, "gross_terminal_r": gross,
        "terminal_net_r": gross - cost_r, "terminal_net_r_cost_1p5x": gross - 1.5 * cost_r, "terminal_net_r_cost_2x": gross - 2.0 * cost_r,
        "outcome_lineage_hash": canonical_hash([row["row_id"], entry_index, right, stop, target, primary_class, two_before, exit_index, exit_price, cost]),
    }
    return result


def materialize(source: Path, destination: Path, frame: Frame, implementation: str) -> dict[str, Any]:
    output_schema = schema(); temporary = destination.with_suffix(destination.suffix + ".tmp"); checksums = Checksums(output_schema); reasons = Counter(); classes = Counter(); exits = Counter()
    invalid_prefix = np.concatenate(([0], np.cumsum(~frame.valid.astype(bool), dtype=np.int64))); tree = RangeTree(frame.high_e8, frame.low_e8)
    writer = pq.ParquetWriter(temporary, output_schema, compression="zstd", use_dictionary=False, write_statistics=True, version="2.6", data_page_version="1.0")
    try:
        parquet = pq.ParquetFile(source)
        for batch in parquet.iter_batches(batch_size=8192):
            rows = [outcome_row(row, frame, tree, invalid_prefix, implementation) for row in batch.to_pylist()]
            for row in rows:
                reasons[row["unavailable_reason"] or "AVAILABLE"] += 1; classes[row["primary_class"]] += 1; exits[str(row["terminal_exit_reason"])] += 1
            table = pa.Table.from_pylist(rows, schema=output_schema); checksums.update(table); writer.write_table(table, row_group_size=8192)
    except Exception:
        writer.close(); temporary.unlink(missing_ok=True); raise
    writer.close(); temporary.replace(destination)
    result = checksums.result(); result.update({"implementation": implementation, "output": file_record(destination), "unavailable_reasons": dict(sorted(reasons.items())), "classes": dict(sorted(classes.items())), "terminal_exits": dict(sorted(exits.items()))})
    if result["rows"] != 2_095_849: raise ValueError("Outcome denominator changed")
    return result


def main() -> None:
    tape = preflight(); proof = synthetic_proof(); implementation_freeze(tape, proof)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_json_exclusive(OPENING, {
        "version": "GOLD_PIT_AUCTION_STATE_V1_DEVELOPMENT_OUTCOME_OPENING_1_0", "status": "OPENED_ONCE_AFTER_ALL_PREOUTCOME_GATES_PASS", "opened_at_utc": utc_now(),
        "source_opening_count": 1, "tape": file_record(TAPE_FREEZE), "execution_freeze": file_record(EXECUTION_FREEZE), "implementation_freeze": file_record(IMPLEMENTATION_FREEZE),
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    })
    frames, price_diagnostics = load_price(); m1 = frames["M1"]
    primary = materialize(TAPE_DIR / "primary_checkpoint_features.parquet", PRIMARY, m1, "primary")
    reference = materialize(TAPE_DIR / "reference_checkpoint_features.parquet", REFERENCE, m1, "reference")
    fields = ("rows", "per_column", "complete", "null_counts", "unavailable_reasons", "classes", "terminal_exits")
    differences = [name for name in fields if primary[name] != reference[name]]; byte_identical = sha256_file(PRIMARY) == sha256_file(REFERENCE)
    status = "PASS_DEVELOPMENT_CHECKPOINT_OUTCOME_MATERIALIZATION" if not differences and byte_identical else "FAIL_DEVELOPMENT_OUTCOME_REPRODUCTION"
    result = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_OUTCOME_CERTIFICATION_1_0", "status": status, "certified_at_utc": utc_now(), "primary": primary, "reference": reference,
        "differences": differences, "byte_identical": byte_identical, "price_diagnostics": price_diagnostics, "opening": file_record(OPENING),
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(CERTIFICATION, result)
    write_json_exclusive(OUTCOME_FREEZE, {
        "version": "GOLD_PIT_AUCTION_STATE_V1_OUTCOME_FREEZE_1_0", "status": status, "sealed_at_utc": utc_now(),
        "controls": {"tape": file_record(TAPE_FREEZE), "execution": file_record(EXECUTION_FREEZE), "implementation": file_record(IMPLEMENTATION_FREEZE), "opening": file_record(OPENING)},
        "artifacts": {"primary": file_record(PRIMARY), "reference": file_record(REFERENCE), "certification": file_record(CERTIFICATION)},
        "rows": primary["rows"], "complete_checksum": primary["complete"], "byte_identical": byte_identical,
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    })
    print(json.dumps({"status": status, "rows": primary["rows"], "classes": primary["classes"], "unavailable": primary["unavailable_reasons"], "byte_identical": byte_identical}, sort_keys=True))
    if status != "PASS_DEVELOPMENT_CHECKPOINT_OUTCOME_MATERIALIZATION": raise SystemExit(2)


if __name__ == "__main__":
    main()
