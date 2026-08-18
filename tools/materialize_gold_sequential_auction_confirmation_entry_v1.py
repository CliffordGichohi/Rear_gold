from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import materialize_gold_trend_pullback_movement_anatomy_edge_v1 as anatomy_impl  # noqa: E402


ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_sequential_auction_confirmation_entry_v1_materialization"
PROTOCOL = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_protocol.json"
PRE_FREEZE = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_pre_outcome_freeze.json"
IMPLEMENTATION_FREEZE = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_materialization_implementation_freeze.json"

ROUTING = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"
ANATOMY = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
FEATURES = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"

SCALE = 100_000_000
MINUTE_NS = 60_000_000_000
TF_PRIORITY = {"H4": 0, "H1": 1, "M15": 2}
VARIANT_ORDER = {"PRIMARY": 0, "LENIENT": 1, "STRICT": 2}
TRACKS = ("TRACK_A_ORIGINAL_STOP", "TRACK_B_CONFIRMED_RETEST_STOP")
FAMILY_BY_MODEL = {
    "RUNAWAY_BREAKOUT": "BREAKOUT_ACCEPTANCE_FIRST_RETEST",
    "BREAK_RETEST_CONTINUATION": "BREAKOUT_ACCEPTANCE_FIRST_RETEST",
    "DEEP_RETRACE_CONTINUATION": "DEEP_PULLBACK_DISPLACEMENT_FIRST_RETEST",
    "FALSE_CONTINUATION_REVERSAL": "SWEEP_RECLAIM_STRUCTURE_FIRST_RETEST",
    "IMMEDIATE_FAILURE_REVERSAL": "SWEEP_RECLAIM_STRUCTURE_FIRST_RETEST",
    "TWO_SIDED_REFERENCE_RETEST": "SWEEP_RECLAIM_STRUCTURE_FIRST_RETEST",
}


@dataclass(frozen=True, slots=True)
class SignalBars:
    minutes: int
    open_ns: np.ndarray
    open_e8: np.ndarray
    high_e8: np.ndarray
    low_e8: np.ndarray
    close_e8: np.ndarray
    prior_atr14_e8: np.ndarray

    @property
    def duration_ns(self) -> int:
        return self.minutes * MINUTE_NS


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * 1_000_000_000 + parsed.microsecond * 1_000


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z")


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


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    result = round(float(value), 12)
    return 0.0 if result == 0 else result


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        table = pa.Table.from_pylist(list(rows))
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            use_dictionary=False,
            write_statistics=True,
            data_page_version="1.0",
            version="2.6",
            row_group_size=16_384,
        )
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def verify_controls() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    freeze = json.loads(PRE_FREEZE.read_text(encoding="utf-8"))
    implementation = json.loads(IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_DELAYED_ENTRY_MATERIALIZATION_OR_OUTCOMES":
        raise ValueError("Protocol status changed")
    if freeze.get("status") != "FROZEN_READY_FOR_OUTCOME_BLIND_CONFIRMATION_MATERIALIZATION":
        raise ValueError("Pre-outcome freeze status changed")
    if implementation.get("status") != "FROZEN_BEFORE_DEVELOPMENT_SEQUENCE_VALUES":
        raise ValueError("Materialization implementation is not frozen")
    for item in [*freeze["controls"].values(), *freeze["predecessor_seals"].values(), freeze["development_xauusd"], freeze["gc_full_session_technical_manifest"]]:
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Frozen predecessor changed: {item['path']}")
    for pair in freeze["source_pairs"].values():
        for side in ("primary", "reference"):
            item = pair[side]
            path = ROOT / item["path"]
            if not path.is_file() or record(path) != item:
                raise ValueError(f"Frozen source changed: {item['path']}")
    script_record = implementation["implementation"]
    if record(ROOT / script_record["path"]) != script_record:
        raise ValueError("Frozen materializer implementation changed")
    if protocol["family_mapping"] != FAMILY_BY_MODEL:
        raise ValueError("Family mapping changed")
    return protocol, freeze, implementation


def aggregate_signal_bars_primary(prices: anatomy_impl.PriceData, minutes: int) -> SignalBars:
    if minutes == 1:
        opens = prices.open_ns.copy()
        o = prices.open_e8.copy(); h = prices.high_e8.copy(); low = prices.low_e8.copy(); close = prices.close_e8.copy()
    else:
        duration = minutes * MINUTE_NS
        bucket = (prices.open_ns // duration) * duration
        change = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
        ends = np.r_[change[1:], len(bucket)]
        out: list[tuple[int, int, int, int, int]] = []
        expected_offsets = np.arange(minutes, dtype=np.int64) * MINUTE_NS
        for start, end in zip(change.tolist(), ends.tolist(), strict=True):
            if end - start != minutes:
                continue
            expected = int(bucket[start]) + expected_offsets
            if not np.array_equal(prices.open_ns[start:end], expected):
                continue
            out.append((int(bucket[start]), int(prices.open_e8[start]), int(np.max(prices.high_e8[start:end])), int(np.min(prices.low_e8[start:end])), int(prices.close_e8[end - 1])))
        values = np.asarray(out, dtype=np.int64)
        opens, o, h, low, close = (values[:, index] for index in range(5))
    atr = prior_atr_primary(opens, h, low, close, minutes)
    return SignalBars(minutes, opens, o, h, low, close, atr)


def aggregate_signal_bars_reference(prices: anatomy_impl.PriceData, minutes: int) -> SignalBars:
    duration = minutes * MINUTE_NS
    source = {
        int(timestamp): (int(prices.open_e8[index]), int(prices.high_e8[index]), int(prices.low_e8[index]), int(prices.close_e8[index]))
        for index, timestamp in enumerate(prices.open_ns.tolist())
    }
    starts = sorted({(timestamp // duration) * duration for timestamp in source})
    output: list[tuple[int, int, int, int, int]] = []
    for start in starts:
        rows = [source.get(start + offset * MINUTE_NS) for offset in range(minutes)]
        if any(row is None for row in rows):
            continue
        complete = [row for row in rows if row is not None]
        output.append((start, complete[0][0], max(row[1] for row in complete), min(row[2] for row in complete), complete[-1][3]))
    values = np.asarray(output, dtype=np.int64)
    opens, o, h, low, close = (values[:, index] for index in range(5))
    atr = prior_atr_reference(opens, h, low, close, minutes)
    return SignalBars(minutes, opens, o, h, low, close, atr)


def prior_atr_primary(opens: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, minutes: int) -> np.ndarray:
    result = np.full(len(opens), np.nan, dtype=np.float64)
    duration = minutes * MINUTE_NS
    if len(opens) < 16:
        return result
    tr = np.full(len(opens), np.nan, dtype=np.float64)
    contiguous = np.r_[False, np.diff(opens) == duration]
    valid = np.flatnonzero(contiguous)
    tr[valid] = np.maximum.reduce([
        (high[valid] - low[valid]).astype(np.float64),
        np.abs(high[valid] - close[valid - 1]).astype(np.float64),
        np.abs(low[valid] - close[valid - 1]).astype(np.float64),
    ])
    for index in range(15, len(opens)):
        if int(opens[index]) - int(opens[index - 15]) != 15 * duration:
            continue
        window = tr[index - 14:index]
        if np.all(np.isfinite(window)):
            result[index] = float(np.mean(window))
    return result


def prior_atr_reference(opens: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, minutes: int) -> np.ndarray:
    result = np.full(len(opens), np.nan, dtype=np.float64)
    duration = minutes * MINUTE_NS
    for index in range(len(opens)):
        if index < 15:
            continue
        expected = [int(opens[index]) - offset * duration for offset in range(15, -1, -1)]
        actual = [int(value) for value in opens[index - 15:index + 1]]
        if actual != expected:
            continue
        ranges = []
        for bar in range(index - 14, index):
            previous_close = int(close[bar - 1])
            ranges.append(max(int(high[bar]) - int(low[bar]), abs(int(high[bar]) - previous_close), abs(int(low[bar]) - previous_close)))
        result[index] = sum(ranges) / 14.0
    return result


def load_inputs(side: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    trades = [dict(row) for row in pq.read_table(ROUTING / f"{side}_model_trades.parquet").to_pylist() if row["status"] == "EXECUTED"]
    if len(trades) != 22_193:
        raise ValueError(f"Executed population changed: {side}")
    features = {str(row["pullback_id"]): dict(row) for row in pq.read_table(FEATURES / f"{side}_features.parquet").to_pylist()}
    facts_by_pullback: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pq.read_table(ANATOMY / f"{side}_trigger_facts.parquet").to_pylist():
        facts_by_pullback[str(row["pullback_id"])].append(dict(row))
    facts: dict[str, dict[str, Any]] = {}
    fields = ("confirmation_high_e8", "confirmation_low_e8", "pivot_price_e8", "reference_level_e8", "atr14_e8")
    for identity, rows in facts_by_pullback.items():
        if len({tuple(row[field] for field in fields) for row in rows}) != 1:
            raise ValueError(f"Structural facts differ within pullback: {identity}")
        facts[identity] = next((row for row in rows if row["trigger"] == "IMMEDIATE"), rows[0])
    for trade in trades:
        identity = str(trade["pullback_id"])
        if identity not in features or identity not in facts:
            raise ValueError(f"Missing setup input: {trade['trade_id']}")
    return trades, features, facts


def model_time_bars() -> dict[str, int]:
    source = json.loads((MANIFESTS / "gold_pullback_archetype_setup_routing_v1_protocol.json").read_text(encoding="utf-8"))
    return {str(row["model_id"]): int(row["time_exit_parent_bars"]) for row in source["entry_models"]}


def deadline_ns(trade: Mapping[str, Any], prices: anatomy_impl.PriceData, time_bars: int, implementation: str) -> int:
    entry_ns = parse_ns(str(trade["entry_at_utc"]))
    closes = prices.parents[str(trade["timeframe"])].close_ns
    first = int(np.searchsorted(closes, entry_ns, side="right")) if implementation == "primary" else bisect.bisect_right(closes, entry_ns)
    deadline_index = first + time_bars - 1
    if deadline_index >= len(closes):
        raise ValueError(f"Missing frozen deadline: {trade['trade_id']}")
    return int(closes[deadline_index])


def fundamental_state(feature: Mapping[str, Any], trade_direction: str) -> str:
    if not feature.get("fundamental_available") or feature.get("fundamental_score") is None:
        return "UNKNOWN"
    try:
        score = float(feature["fundamental_score"])
        coverage = float(feature["fundamental_coverage"])
        confidence = float(feature["fundamental_confidence"])
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not all(math.isfinite(value) for value in (score, coverage, confidence)):
        return "UNKNOWN"
    aligned = score if trade_direction == "UP" else -score
    if coverage >= 50.0 and confidence >= 35.0 and aligned >= 20.0:
        return "ALIGNED"
    if coverage >= 50.0 and confidence >= 35.0 and aligned <= -20.0:
        return "OPPOSED"
    return "NEUTRAL_OR_WEAK"


def higher_timeframe_state(feature: Mapping[str, Any], timeframe: str, trade_direction: str) -> tuple[int, int, str]:
    original_direction = str(feature["direction"])
    values: list[bool] = []
    if timeframe == "M15":
        for field in ("h1_structure_state", "h4_structure_state"):
            state = feature.get(field)
            if state in {"UP", "DOWN"}:
                values.append(state == trade_direction)
    elif timeframe == "H1":
        state = feature.get("h4_structure_state")
        if state in {"UP", "DOWN"}:
            values.append(state == trade_direction)
    for field in ("daily_3bar_alignment", "weekly_2bar_alignment"):
        value = feature.get(field)
        if value is not None:
            aligned_to_original = bool(value)
            values.append(aligned_to_original if trade_direction == original_direction else not aligned_to_original)
    aligned = sum(values)
    known = len(values)
    return aligned, known, "ELIGIBLE" if aligned >= 1 else "NO_ALIGNED_HIGHER_TIMEFRAME_COMPONENT"


def parameter_bundles(protocol: Mapping[str, Any]) -> dict[str, dict[str, float | int]]:
    primary = dict(protocol["primary_parameters"])
    output = {"PRIMARY": primary}
    for name in ("LENIENT", "STRICT"):
        bundle = dict(primary)
        bundle.update(protocol["sensitivity_bundles"][name])
        output[name] = bundle
    return output


def first_aligned_start(anchor_ns: int, duration_ns: int) -> int:
    return ((anchor_ns + duration_ns - 1) // duration_ns) * duration_ns


def primary_indexer(bars: SignalBars) -> Callable[[int], int | None]:
    def lookup(timestamp: int) -> int | None:
        index = int(np.searchsorted(bars.open_ns, timestamp, side="left"))
        return index if index < len(bars.open_ns) and int(bars.open_ns[index]) == timestamp else None
    return lookup


def reference_indexer(bars: SignalBars) -> Callable[[int], int | None]:
    mapping = {int(timestamp): index for index, timestamp in enumerate(bars.open_ns.tolist())}
    return mapping.get


def bar_is_displacement(bars: SignalBars, index: int, sign: int, parameters: Mapping[str, Any], lookup: Callable[[int], int | None]) -> tuple[bool, int | None, str | None]:
    atr = float(bars.prior_atr14_e8[index])
    if not math.isfinite(atr) or atr <= 0:
        return False, None, "SIGNAL_ATR_UNAVAILABLE"
    high = int(bars.high_e8[index]); low = int(bars.low_e8[index]); opened = int(bars.open_e8[index]); close = int(bars.close_e8[index])
    range_e8 = high - low
    if range_e8 <= 0 or range_e8 < float(parameters["displacement_range_signal_atr"]) * atr:
        return False, None, None
    if abs(close - opened) / range_e8 < float(parameters["displacement_body_fraction"]):
        return False, None, None
    if (sign > 0 and close <= opened) or (sign < 0 and close >= opened):
        return False, None, None
    close_location = (close - low) / range_e8 if sign > 0 else (high - close) / range_e8
    if close_location < float(parameters["directional_close_location"]):
        return False, None, None
    lookback = int(parameters["micro_lookback_signal_bars"])
    previous: list[int] = []
    for offset in range(lookback, 0, -1):
        prior = lookup(int(bars.open_ns[index]) - offset * bars.duration_ns)
        if prior is None:
            return False, None, "MISSING_MICRO_LOOKBACK_BAR"
        previous.append(prior)
    broken = max(int(bars.high_e8[item]) for item in previous) if sign > 0 else min(int(bars.low_e8[item]) for item in previous)
    if (sign > 0 and close <= broken) or (sign < 0 and close >= broken):
        return False, None, None
    return True, broken, None


def common_retest(bars: SignalBars, index: int, level: int, sign: int, parent_atr: float, parameters: Mapping[str, Any]) -> bool:
    tolerance = float(parameters["retest_tolerance_parent_atr"]) * parent_atr
    closing = float(parameters["retest_close_parent_atr"]) * parent_atr
    invalid = float(parameters["clearance_parent_atr"]) * parent_atr
    opened = int(bars.open_e8[index]); high = int(bars.high_e8[index]); low = int(bars.low_e8[index]); close = int(bars.close_e8[index])
    if sign > 0:
        return low <= level + tolerance and close >= level + closing and close > opened and close >= level - invalid
    return high >= level - tolerance and close <= level - closing and close < opened and close <= level + invalid


def search_sequence(
    bars: SignalBars,
    anchor_ns: int,
    deadline: int,
    family: str,
    model_id: str,
    fact: Mapping[str, Any],
    trade_direction: str,
    parameters: Mapping[str, Any],
    implementation: str,
    lookup_override: Callable[[int], int | None] | None = None,
) -> dict[str, Any]:
    sign = 1 if trade_direction == "UP" else -1
    lookup = lookup_override or (primary_indexer(bars) if implementation == "primary" else reference_indexer(bars))
    start = first_aligned_start(anchor_ns, bars.duration_ns)
    parent_atr = float(fact["atr14_e8"])
    if not math.isfinite(parent_atr) or parent_atr <= 0:
        return {"status": "UNAVAILABLE", "reason": "PARENT_ATR_UNAVAILABLE"}

    def get(offset: int) -> tuple[int | None, str | None]:
        timestamp = start + offset * bars.duration_ns
        if timestamp + bars.duration_ns > deadline:
            return None, "ORIGINAL_DEADLINE_REACHED"
        index = lookup(timestamp)
        return (index, None) if index is not None else (None, "MISSING_REQUIRED_SIGNAL_BAR")

    transition_index: int | None = None
    retest_level: int | None = None
    sequence_evidence: list[tuple[str, int]] = []
    if family == "BREAKOUT_ACCEPTANCE_FIRST_RETEST":
        level = int(fact["confirmation_high_e8"] if sign > 0 else fact["confirmation_low_e8"])
        if level <= 0:
            return {"status": "UNAVAILABLE", "reason": "CONFIRMATION_LEVEL_UNAVAILABLE"}
        first_window = int(parameters["initial_window_signal_bars"])
        for offset in range(first_window - 1):
            left, reason = get(offset); right, reason2 = get(offset + 1)
            if left is None or right is None:
                return {"status": "UNAVAILABLE", "reason": reason or reason2}
            left_close = int(bars.close_e8[left]); right_close = int(bars.close_e8[right])
            accepted = (left_close > level and right_close >= level + float(parameters["clearance_parent_atr"]) * parent_atr) if sign > 0 else (left_close < level and right_close <= level - float(parameters["clearance_parent_atr"]) * parent_atr)
            if accepted:
                transition_index = right
                retest_level = level
                sequence_evidence.extend([("ACCEPTANCE_1", left), ("ACCEPTANCE_2", right)])
                break
        if transition_index is None:
            return {"status": "NO_CONFIRMATION", "reason": "NO_TWO_CLOSE_ACCEPTANCE"}
    elif family == "SWEEP_RECLAIM_STRUCTURE_FIRST_RETEST":
        if model_id == "TWO_SIDED_REFERENCE_RETEST":
            level = int(fact["reference_level_e8"])
        else:
            level = int(fact["confirmation_low_e8"] if sign > 0 else fact["confirmation_high_e8"])
        if level <= 0:
            return {"status": "UNAVAILABLE", "reason": "SWEEP_LEVEL_UNAVAILABLE"}
        sweep_index = None
        first_window = int(parameters["initial_window_signal_bars"])
        for offset in range(first_window):
            index, reason = get(offset)
            if index is None:
                return {"status": "UNAVAILABLE", "reason": reason}
            high = int(bars.high_e8[index]); low = int(bars.low_e8[index]); close = int(bars.close_e8[index])
            swept = (low <= level - float(parameters["sweep_parent_atr"]) * parent_atr and close >= level + float(parameters["reclaim_parent_atr"]) * parent_atr) if sign > 0 else (high >= level + float(parameters["sweep_parent_atr"]) * parent_atr and close <= level - float(parameters["reclaim_parent_atr"]) * parent_atr)
            if swept:
                sweep_index = index
                sequence_evidence.append(("SWEEP_RECLAIM", index))
                break
        if sweep_index is None:
            return {"status": "NO_CONFIRMATION", "reason": "NO_SWEEP_RECLAIM"}
        sweep_offset = (int(bars.open_ns[sweep_index]) - start) // bars.duration_ns
        for offset in range(int(sweep_offset) + 1, int(sweep_offset) + 1 + int(parameters["transition_window_signal_bars"])):
            index, reason = get(offset)
            if index is None:
                return {"status": "UNAVAILABLE", "reason": reason}
            valid, broken, failure = bar_is_displacement(bars, index, sign, parameters, lookup)
            if failure is not None:
                return {"status": "UNAVAILABLE", "reason": failure}
            if valid:
                transition_index = index; retest_level = broken
                sequence_evidence.append(("STRUCTURE_DISPLACEMENT", index))
                break
        if transition_index is None:
            return {"status": "NO_CONFIRMATION", "reason": "NO_ALIGNED_STRUCTURE_DISPLACEMENT"}
    elif family == "DEEP_PULLBACK_DISPLACEMENT_FIRST_RETEST":
        for offset in range(int(parameters["initial_window_signal_bars"])):
            index, reason = get(offset)
            if index is None:
                return {"status": "UNAVAILABLE", "reason": reason}
            valid, broken, failure = bar_is_displacement(bars, index, sign, parameters, lookup)
            if failure is not None:
                return {"status": "UNAVAILABLE", "reason": failure}
            if valid:
                transition_index = index; retest_level = broken
                sequence_evidence.append(("DEEP_PULLBACK_DISPLACEMENT", index))
                break
        if transition_index is None:
            return {"status": "NO_CONFIRMATION", "reason": "NO_ALIGNED_STRUCTURE_DISPLACEMENT"}
    else:
        raise ValueError(family)

    assert transition_index is not None and retest_level is not None
    transition_offset = (int(bars.open_ns[transition_index]) - start) // bars.duration_ns
    retest_index = None
    for offset in range(int(transition_offset) + 1, int(transition_offset) + 1 + int(parameters["retest_window_signal_bars"])):
        index, reason = get(offset)
        if index is None:
            return {"status": "UNAVAILABLE", "reason": reason}
        if common_retest(bars, index, retest_level, sign, parent_atr, parameters):
            retest_index = index
            sequence_evidence.append(("VALID_RETEST", index))
            break
    if retest_index is None:
        return {"status": "NO_CONFIRMATION", "reason": "NO_VALID_FIRST_RETEST"}
    entry_timestamp = int(bars.open_ns[retest_index]) + bars.duration_ns
    entry_index = lookup(entry_timestamp)
    if entry_index is None:
        return {"status": "UNAVAILABLE", "reason": "MISSING_ENTRY_SIGNAL_BAR"}
    if entry_timestamp >= deadline:
        return {"status": "UNAVAILABLE", "reason": "ENTRY_NOT_BEFORE_ORIGINAL_DEADLINE"}
    return {
        "status": "SEQUENCE_FORMED",
        "reason": "",
        "transition_index": transition_index,
        "retest_index": retest_index,
        "entry_signal_index": entry_index,
        "entry_at_ns": entry_timestamp,
        "retest_level_e8": retest_level,
        "evidence_hash": canonical_hash([(name, ns_iso(int(bars.open_ns[index]))) for name, index in sequence_evidence]),
    }


def original_target_touched_before_entry(prices: anatomy_impl.PriceData, start_ns: int, end_ns: int, target: int, sign: int, implementation: str) -> tuple[bool, str | None]:
    if implementation == "primary":
        start = int(np.searchsorted(prices.open_ns, start_ns, side="left")); end = int(np.searchsorted(prices.open_ns, end_ns, side="left"))
        if start >= len(prices.open_ns) or int(prices.open_ns[start]) != start_ns or end >= len(prices.open_ns) or int(prices.open_ns[end]) != end_ns:
            return False, "MISSING_EXACT_M1_ENTRY_BOUNDARY"
        timestamps = prices.open_ns[start:end]
        if len(timestamps) and (int(timestamps[-1]) - int(timestamps[0]) != (len(timestamps) - 1) * MINUTE_NS):
            return False, "MISSING_PRE_ENTRY_M1_BAR"
        touched = bool(np.any(prices.high_e8[start:end] >= target)) if sign > 0 else bool(np.any(prices.low_e8[start:end] <= target))
        return touched, None
    timestamps = prices.open_ns
    start = bisect.bisect_left(timestamps, start_ns); end = bisect.bisect_left(timestamps, end_ns)
    if start >= len(timestamps) or timestamps[start] != start_ns or end >= len(timestamps) or timestamps[end] != end_ns:
        return False, "MISSING_EXACT_M1_ENTRY_BOUNDARY"
    for offset, index in enumerate(range(start, end)):
        if timestamps[index] != start_ns + offset * MINUTE_NS:
            return False, "MISSING_PRE_ENTRY_M1_BAR"
        if (sign > 0 and int(prices.high_e8[index]) >= target) or (sign < 0 and int(prices.low_e8[index]) <= target):
            return True, None
    return False, None


def base_row(trade: Mapping[str, Any], family: str, variant: str, track: str, deadline: int, fundamental: str, htf_aligned: int, htf_known: int) -> dict[str, Any]:
    candidate_id = f"{trade['timeframe']}::{trade['model_id']}::{track}"
    return {
        "sequence_row_id": canonical_hash([str(trade["trade_id"]), variant, track]),
        "trade_id": str(trade["trade_id"]),
        "pullback_id": str(trade["pullback_id"]),
        "timeframe": str(trade["timeframe"]),
        "model_id": str(trade["model_id"]),
        "family_id": family,
        "variant": variant,
        "track_id": track,
        "candidate_id": candidate_id,
        "trade_direction": str(trade["trade_direction"]),
        "original_direction": str(trade["original_direction"]),
        "known_at_utc": str(trade["known_at_utc"]),
        "original_entry_at_utc": str(trade["entry_at_utc"]),
        "cluster_date": str(trade["cluster_date"]),
        "calendar_year": int(trade["calendar_year"]),
        "session_state": str(trade["session_state"]),
        "original_deadline_at_utc": ns_iso(deadline),
        "fundamental_state_actual_direction": fundamental,
        "higher_timeframe_aligned_count": htf_aligned,
        "higher_timeframe_known_count": htf_known,
        "status": "UNAVAILABLE",
        "reason": "",
        "sequence_evidence_hash": None,
        "transition_at_utc": None,
        "retest_at_utc": None,
        "delayed_entry_at_utc": None,
        "entry_delay_minutes": None,
        "entry_improvement_usd_oz": None,
        "retest_level_e8": None,
        "entry_e8": None,
        "stop_e8": None,
        "target_e8": int(trade["target_e8"]),
        "stop_distance_usd_oz": None,
        "target_distance_usd_oz": None,
        "gross_target_r": None,
        "spread_usd_oz": None,
        "total_cost_usd_oz": None,
        "planned_ounces": None,
        "track_b_retest_extreme_e8": None,
        "point_in_time_lineage_hash": None,
    }


def materialize(side: str, implementation: str, prices: anatomy_impl.PriceData, bars_by_tf: Mapping[str, SignalBars], protocol: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trades, features, facts = load_inputs(side)
    deadlines = model_time_bars()
    variants = parameter_bundles(protocol)
    lookups = {
        timeframe: (primary_indexer(bars) if implementation == "primary" else reference_indexer(bars))
        for timeframe, bars in bars_by_tf.items()
    }
    output: list[dict[str, Any]] = []
    diagnostics: Counter[str] = Counter()
    trades.sort(key=lambda row: (str(row["entry_at_utc"]), TF_PRIORITY[str(row["timeframe"])], int(row["model_rank"]), str(row["trade_id"])))
    for trade in trades:
        identity = str(trade["pullback_id"]); feature = features[identity]; fact = facts[identity]
        timeframe = str(trade["timeframe"]); model_id = str(trade["model_id"]); trade_direction = str(trade["trade_direction"])
        family = FAMILY_BY_MODEL[model_id]
        deadline = deadline_ns(trade, prices, deadlines[model_id], implementation)
        fundamental = fundamental_state(feature, trade_direction)
        aligned, known, htf_status = higher_timeframe_state(feature, timeframe, trade_direction)
        for variant in ("PRIMARY", "LENIENT", "STRICT"):
            parameters = variants[variant]
            sequence: dict[str, Any]
            if fundamental in {"OPPOSED", "UNKNOWN"}:
                sequence = {"status": "NO_TRADE_GATE", "reason": f"FUNDAMENTAL_{fundamental}"}
            elif htf_status != "ELIGIBLE":
                sequence = {"status": "NO_TRADE_GATE", "reason": htf_status}
            else:
                sequence = search_sequence(
                    bars_by_tf[timeframe], parse_ns(str(trade["entry_at_utc"])), deadline, family, model_id,
                    fact, trade_direction, parameters, implementation, lookups[timeframe],
                )
            for track in TRACKS:
                row = base_row(trade, family, variant, track, deadline, fundamental, aligned, known)
                row["status"] = sequence["status"]; row["reason"] = sequence["reason"]
                if sequence["status"] != "SEQUENCE_FORMED":
                    diagnostics[f"{variant}|{track}|{sequence['status']}|{sequence['reason']}"] += 1
                    output.append(row)
                    continue
                bars = bars_by_tf[timeframe]
                entry_ns = int(sequence["entry_at_ns"]); entry_signal_index = int(sequence["entry_signal_index"])
                m1_index = int(np.searchsorted(prices.open_ns, entry_ns, side="left")) if implementation == "primary" else bisect.bisect_left(prices.open_ns, entry_ns)
                if m1_index >= len(prices.open_ns) or int(prices.open_ns[m1_index]) != entry_ns:
                    row["status"] = "UNAVAILABLE"; row["reason"] = "MISSING_DELAYED_ENTRY_M1_BAR"
                    diagnostics[f"{variant}|{track}|UNAVAILABLE|MISSING_DELAYED_ENTRY_M1_BAR"] += 1; output.append(row); continue
                sign = 1 if trade_direction == "UP" else -1
                target = int(trade["target_e8"]); entry = int(prices.open_e8[m1_index])
                touched, touch_failure = original_target_touched_before_entry(prices, parse_ns(str(trade["entry_at_utc"])), entry_ns, target, sign, implementation)
                if touch_failure is not None:
                    row["status"] = "UNAVAILABLE"; row["reason"] = touch_failure
                    diagnostics[f"{variant}|{track}|UNAVAILABLE|{touch_failure}"] += 1; output.append(row); continue
                if touched:
                    row["status"] = "NO_TRADE_GATE"; row["reason"] = "ORIGINAL_TARGET_TOUCHED_BEFORE_DELAYED_ENTRY"
                    diagnostics[f"{variant}|{track}|NO_TRADE_GATE|ORIGINAL_TARGET_TOUCHED_BEFORE_DELAYED_ENTRY"] += 1; output.append(row); continue
                parent_atr = float(fact["atr14_e8"])
                retest_index = int(sequence["retest_index"])
                retest_extreme = int(bars.low_e8[retest_index] if sign > 0 else bars.high_e8[retest_index])
                if track == "TRACK_A_ORIGINAL_STOP":
                    stop = int(trade["stop_e8"])
                else:
                    buffer_e8 = int(round(float(parameters["track_b_stop_buffer_parent_atr"]) * parent_atr))
                    stop = retest_extreme - buffer_e8 if sign > 0 else retest_extreme + buffer_e8
                invalid_reason = None
                if (sign > 0 and stop >= entry) or (sign < 0 and stop <= entry):
                    invalid_reason = "STOP_NOT_ADVERSE_TO_DELAYED_ENTRY"
                elif (sign > 0 and target <= entry) or (sign < 0 and target >= entry):
                    invalid_reason = "TARGET_NOT_FAVOURABLE_TO_DELAYED_ENTRY"
                risk_e8 = abs(entry - stop); reward_e8 = sign * (target - entry)
                gross_target_r = reward_e8 / risk_e8 if risk_e8 > 0 else -math.inf
                if invalid_reason is None and gross_target_r < float(parameters["minimum_gross_target_r"]):
                    invalid_reason = "GROSS_TARGET_ROOM_BELOW_1R"
                spread = float(prices.spread[m1_index]); spread = 0.30 if not math.isfinite(spread) or spread < 0 else spread
                total_cost = spread + float(protocol["economics"]["commission_usd_oz"]) + float(protocol["economics"]["slippage_usd_oz"])
                risk_usd_oz = risk_e8 / SCALE
                ounces = math.floor((float(protocol["economics"]["planned_risk_usd"]) / (risk_usd_oz + total_cost)) + 1e-12) if risk_usd_oz + total_cost > 0 else 0
                if invalid_reason is None and ounces < 1:
                    invalid_reason = "WHOLE_OUNCE_RISK_INFEASIBLE"
                if invalid_reason is not None:
                    row["status"] = "NO_TRADE_GATE"; row["reason"] = invalid_reason
                    diagnostics[f"{variant}|{track}|NO_TRADE_GATE|{invalid_reason}"] += 1; output.append(row); continue
                transition = int(sequence["transition_index"]); retest = int(sequence["retest_index"])
                original_entry = int(trade["entry_e8"])
                row.update({
                    "status": "ENTRY_ELIGIBLE", "reason": "", "sequence_evidence_hash": str(sequence["evidence_hash"]),
                    "transition_at_utc": ns_iso(int(bars.open_ns[transition]) + bars.duration_ns),
                    "retest_at_utc": ns_iso(int(bars.open_ns[retest]) + bars.duration_ns),
                    "delayed_entry_at_utc": ns_iso(entry_ns),
                    "entry_delay_minutes": rounded((entry_ns - parse_ns(str(trade["entry_at_utc"]))) / MINUTE_NS),
                    "entry_improvement_usd_oz": rounded(sign * (original_entry - entry) / SCALE),
                    "retest_level_e8": int(sequence["retest_level_e8"]), "entry_e8": entry, "stop_e8": stop,
                    "stop_distance_usd_oz": rounded(risk_usd_oz), "target_distance_usd_oz": rounded(reward_e8 / SCALE),
                    "gross_target_r": rounded(gross_target_r), "spread_usd_oz": rounded(spread),
                    "total_cost_usd_oz": rounded(total_cost), "planned_ounces": ounces,
                    "track_b_retest_extreme_e8": retest_extreme if track == "TRACK_B_CONFIRMED_RETEST_STOP" else None,
                    "point_in_time_lineage_hash": canonical_hash([
                        str(trade["trade_id"]), str(feature["feature_lineage_hash"]), str(fact["trigger_lineage_hash"]),
                        variant, track, ns_iso(entry_ns), int(sequence["retest_level_e8"]), entry, stop, target,
                    ]),
                })
                diagnostics[f"{variant}|{track}|ENTRY_ELIGIBLE"] += 1
                output.append(row)
    output.sort(key=lambda row: (str(row["original_entry_at_utc"]), TF_PRIORITY[str(row["timeframe"])], str(row["model_id"]), VARIANT_ORDER[str(row["variant"])], str(row["track_id"]), str(row["trade_id"])))
    expected_rows = 22_193 * 3 * 2
    if len(output) != expected_rows or len({str(row["sequence_row_id"]) for row in output}) != expected_rows:
        raise ValueError(f"Sequence row population invalid: {side}:{len(output)}")
    return output, {"rows": len(output), "diagnostics": dict(sorted(diagnostics.items())), "row_identity_hash": canonical_hash([row["sequence_row_id"] for row in output]), "complete_row_hash": canonical_hash(output)}


def compare_signal_bars(left: Mapping[str, SignalBars], right: Mapping[str, SignalBars]) -> None:
    for timeframe in ("M15", "H1", "H4"):
        a = left[timeframe]; b = right[timeframe]
        for field in ("open_ns", "open_e8", "high_e8", "low_e8", "close_e8"):
            if not np.array_equal(getattr(a, field), getattr(b, field)):
                raise ValueError(f"Signal aggregation differs: {timeframe}:{field}")
        if not np.array_equal(a.prior_atr14_e8, b.prior_atr14_e8, equal_nan=True):
            raise ValueError(f"Signal ATR differs: {timeframe}")


def run_self_test() -> None:
    minute = MINUTE_NS
    count = 80
    timestamps = np.arange(count, dtype=np.int64) * minute
    base = 2000 * SCALE
    close = np.full(count, base, dtype=np.int64)
    opened = close.copy(); high = close + 10_000_000; low = close - 10_000_000
    spread = np.full(count, 0.20)
    prices = anatomy_impl.PriceData(timestamps, opened, high, low, close, spread, {}, {})
    for minutes in (1, 5, 15):
        primary = aggregate_signal_bars_primary(prices, minutes)
        reference = aggregate_signal_bars_reference(prices, minutes)
        compare_signal_bars({"M15": primary, "H1": primary, "H4": primary}, {"M15": reference, "H1": reference, "H4": reference})
    fact = {"confirmation_high_e8": base, "confirmation_low_e8": base, "pivot_price_e8": base, "reference_level_e8": base, "atr14_e8": 100_000_000.0}
    bars = aggregate_signal_bars_primary(prices, 1)
    parameters = {
        "clearance_parent_atr": 0.0, "sweep_parent_atr": 0.0, "reclaim_parent_atr": 0.0,
        "retest_tolerance_parent_atr": 0.15, "retest_close_parent_atr": 0.0,
        "initial_window_signal_bars": 12, "transition_window_signal_bars": 8, "retest_window_signal_bars": 8,
        "displacement_range_signal_atr": 1.0, "displacement_body_fraction": 0.5,
        "directional_close_location": 2 / 3, "micro_lookback_signal_bars": 3,
    }
    # Synthetic flat bars intentionally form no accepted/retested breakout under strict directional bodies.
    result_a = search_sequence(bars, 20 * minute, 60 * minute, "BREAKOUT_ACCEPTANCE_FIRST_RETEST", "RUNAWAY_BREAKOUT", fact, "UP", parameters, "primary")
    result_b = search_sequence(bars, 20 * minute, 60 * minute, "BREAKOUT_ACCEPTANCE_FIRST_RETEST", "RUNAWAY_BREAKOUT", fact, "UP", parameters, "reference")
    if result_a != result_b or result_a["status"] != "NO_CONFIRMATION":
        raise ValueError("Synthetic sequence implementations differ")
    print(json.dumps({"status": "PASS_SYNTHETIC_MATERIALIZER_PROOF", "aggregation_minutes": [1, 5, 15], "sequence_result": result_a}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_test(); return
    protocol, freeze, implementation = verify_controls()
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    OUTPUT.mkdir(parents=True)
    try:
        prices = anatomy_impl.load_price()
        primary_bars = {"M15": aggregate_signal_bars_primary(prices, 1), "H1": aggregate_signal_bars_primary(prices, 5), "H4": aggregate_signal_bars_primary(prices, 15)}
        reference_bars = {"M15": aggregate_signal_bars_reference(prices, 1), "H1": aggregate_signal_bars_reference(prices, 5), "H4": aggregate_signal_bars_reference(prices, 15)}
        compare_signal_bars(primary_bars, reference_bars)
        primary_rows, primary_diagnostics = materialize("primary", "primary", prices, primary_bars, protocol)
        reference_rows, reference_diagnostics = materialize("reference", "reference", prices, reference_bars, protocol)
        if primary_rows != reference_rows or primary_diagnostics != reference_diagnostics:
            raise ValueError("Independent sequence materializations differ")
        primary_path = OUTPUT / "primary_sequences.parquet"; reference_path = OUTPUT / "reference_sequences.parquet"
        write_parquet_exclusive(primary_path, primary_rows); write_parquet_exclusive(reference_path, reference_rows)
        if sha256_file(primary_path) != sha256_file(reference_path):
            raise ValueError("Independent Parquet payloads are not byte-identical")
        signal_diagnostics = {
            timeframe: {
                "minutes": bars.minutes, "bars": len(bars.open_ns), "atr_available": int(np.count_nonzero(np.isfinite(bars.prior_atr14_e8))),
                "first_open": ns_iso(int(bars.open_ns[0])), "last_open": ns_iso(int(bars.open_ns[-1])),
                "checksum": canonical_hash([bars.open_ns.tolist(), bars.open_e8.tolist(), bars.high_e8.tolist(), bars.low_e8.tolist(), bars.close_e8.tolist(), [None if not math.isfinite(float(value)) else rounded(float(value)) for value in bars.prior_atr14_e8]]),
            }
            for timeframe, bars in primary_bars.items()
        }
        summary = {
            "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_MATERIALIZATION_1_0",
            "status": "PASS_OUTCOME_BLIND_SEQUENCE_MATERIALIZATION",
            "generated_at_utc": utc_now(), "rows": len(primary_rows),
            "primary_reference_exact": True, "price_diagnostics": prices.diagnostics,
            "signal_diagnostics": signal_diagnostics, "materialization_diagnostics": primary_diagnostics,
            "entry_eligible": sum(row["status"] == "ENTRY_ELIGIBLE" for row in primary_rows),
            "entry_eligible_primary": sum(row["status"] == "ENTRY_ELIGIBLE" and row["variant"] == "PRIMARY" for row in primary_rows),
            "outcomes_opened": False, "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        }
        summary_path = OUTPUT / "materialization_summary.json"; write_json_exclusive(summary_path, summary)
        seal = {
            "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_MATERIALIZATION_SEAL_1_0",
            "status": summary["status"], "sealed_at_utc": utc_now(),
            "controls": {"protocol": record(PROTOCOL), "pre_outcome_freeze": record(PRE_FREEZE), "implementation_freeze": record(IMPLEMENTATION_FREEZE)},
            "artifacts": {"primary": record(primary_path), "reference": record(reference_path), "summary": record(summary_path)},
            "result_hash": canonical_hash(summary), "outcomes_opened": False,
            "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
        }
        write_json_exclusive(OUTPUT / "materialization_seal.json", seal)
        print(json.dumps({"status": seal["status"], "rows": len(primary_rows), "entry_eligible_primary": summary["entry_eligible_primary"], "seal": record(OUTPUT / "materialization_seal.json")}, sort_keys=True))
    except Exception:
        if OUTPUT.exists() and not any(OUTPUT.iterdir()):
            OUTPUT.rmdir()
        raise


if __name__ == "__main__":
    main()
