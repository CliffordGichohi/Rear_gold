from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
CONTRACT = ROOT / "GOLD_POINT_IN_TIME_AUCTION_STATE_AND_ADAPTIVE_TRADE_MANAGEMENT_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_protocol.json"
DEFINITIONS = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_feature_definition_freeze.json"
READINESS_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_preoutcome_freeze.json"
ORIGINAL_IMPLEMENTATION_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_implementation_freeze.json"
AMENDMENT_A = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_implementation_amendment_a.json"
AMENDMENT_A_IMPLEMENTATION_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_implementation_freeze_a1.json"
AMENDMENT_B = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_implementation_amendment_b.json"
AMENDMENT_B_IMPLEMENTATION_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_implementation_freeze_b1.json"
BASELINE_AUDIT_SEAL = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_setup_baseline_metadata_audit_seal.json"
AMENDMENT_C = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_implementation_amendment_c.json"
IMPLEMENTATION_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_implementation_freeze_c1.json"

READINESS = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_preoutcome"
OUTPUT = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape"
ATLAS = ARTIFACTS / "gold_pullback_behavioural_archetypes_v1"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
STATIC = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
CASEBOOK = ARTIFACTS / "gold_casebook_v01"
PRICE = CASEBOOK / "price_bars.jsonl.gz"
FUNDAMENTALS = CASEBOOK / "fundamentals.jsonl.gz"
POSITIONING = CASEBOOK / "positioning.jsonl.gz"

PRIMARY_OUTPUT = OUTPUT / "primary_checkpoint_features.parquet"
REFERENCE_OUTPUT = OUTPUT / "reference_checkpoint_features.parquet"
CERTIFICATION = OUTPUT / "materialization_certification.json"
FINAL_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_freeze.json"

SCALE = 100_000_000
END_NS = 1_735_689_600_000_000_000  # 2025-01-01T00:00:00Z
RAW_TO_CANONICAL = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4"}
SIGNAL_FRAME = {"M15": "M1", "H1": "M5", "H4": "M15"}
INTERVAL_NS = {"M1": 60_000_000_000, "M5": 300_000_000_000, "M15": 900_000_000_000, "H1": 3_600_000_000_000, "H4": 14_400_000_000_000}
NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
TOKYO = ZoneInfo("Asia/Tokyo")

NUMERIC_PREDICTORS = [
    "setup_retracement_depth_atr", "setup_compression_ratio", "setup_pullback_efficiency",
    "setup_impulse_efficiency", "setup_impulse_extension_atr", "setup_trend_age_log1p",
    "setup_prior_continuations_log1p", "setup_pivot_rejection_wick", "setup_confirmation_range_atr",
    "setup_confirmation_body_fraction", "setup_confirmation_close_location", "setup_response_displacement_atr",
    "setup_response_efficiency", "setup_confirmation_volume_ratio", "fundamental_score_aligned",
    "fundamental_confidence_01", "fundamental_coverage_01", "real_yield_contribution_aligned",
    "fed_path_contribution_aligned", "usd_contribution_aligned", "two_year_contribution_aligned",
    "positioning_contribution_aligned", "financial_stress_contribution_aligned", "cot_percentile_01",
    "cot_net_change_aligned_signed_log", "higher_timeframe_alignment_fraction", "elapsed_fraction",
    "time_remaining_fraction", "current_displacement_atr", "pivot_distance_atr", "reference_distance_atr",
    "running_favourable_atr", "running_adverse_atr", "recent_3_displacement_atr",
    "recent_5_efficiency", "current_range_atr", "current_body_fraction", "current_close_location",
    "current_rejection_wick", "volume_ratio_20", "spread_atr", "rolling_volatility_ratio",
    "acceptance_state", "sweep_reclaim_state", "local_structure_score", "liquidity_target_r",
]
CATEGORICAL_PREDICTORS = [
    "fundamental_alignment_state", "fundamental_regime", "reaction_function", "event_risk",
    "session_state", "h1_relative_state", "h4_relative_state",
]
STATIC_MAPPING = {
    "setup_retracement_depth_atr": "retracement_depth_atr",
    "setup_compression_ratio": "compression_ratio",
    "setup_pullback_efficiency": "pullback_efficiency",
    "setup_impulse_efficiency": "impulse_efficiency",
    "setup_impulse_extension_atr": "impulse_extension_atr",
    "setup_pivot_rejection_wick": "pivot_rejection_wick_fraction",
    "setup_confirmation_range_atr": "confirmation_range_atr",
    "setup_confirmation_body_fraction": "confirmation_body_fraction",
    "setup_confirmation_close_location": "confirmation_close_location_trend",
    "setup_response_displacement_atr": "response_displacement_atr",
    "setup_response_efficiency": "response_efficiency",
    "setup_confirmation_volume_ratio": "confirmation_volume_ratio_20",
}
COMPONENT_COLUMNS = {
    "REAL_YIELD": "real_yield_contribution_aligned",
    "FED_PATH": "fed_path_contribution_aligned",
    "USD": "usd_contribution_aligned",
    "TWO_YEAR_YIELD": "two_year_contribution_aligned",
    "POSITIONING_FLOW": "positioning_contribution_aligned",
    "FINANCIAL_STRESS": "financial_stress_contribution_aligned",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    parsed = parsed.astimezone(UTC)
    return int(parsed.timestamp()) * 1_000_000_000 + parsed.microsecond * 1_000


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z")


def scaled(value: Any) -> int:
    return int((Decimal(str(value)) * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


@dataclass(slots=True)
class Frame:
    name: str
    open_ns: np.ndarray
    close_ns: np.ndarray
    available_ns: np.ndarray
    open_e8: np.ndarray
    high_e8: np.ndarray
    low_e8: np.ndarray
    close_e8: np.ndarray
    volume: np.ndarray
    spread: np.ndarray
    missing_minutes: np.ndarray
    valid: np.ndarray


@dataclass(slots=True)
class MacroRows:
    rows: list[dict[str, Any]]
    times: np.ndarray


@dataclass(slots=True)
class DailyState:
    completed_ns: list[int]
    close_e8: list[int]


@dataclass(slots=True)
class Fractals:
    low_known: np.ndarray
    low_level: np.ndarray
    high_known: np.ndarray
    high_level: np.ndarray


@dataclass(slots=True)
class FrameDerived:
    volume_ratio_20: np.ndarray
    volatility_ratio: np.ndarray


class IntervalPriceIndex:
    """Price-ordered interval stabbing index for point-in-time active swings."""

    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        grouped: dict[int, list[tuple[int, int, str, str]]] = defaultdict(list)
        for row in rows:
            grouped[int(row["price_e8"])].append((int(row["known_ns"]), int(row["broken_ns"]), str(row["swing_id"]), str(row["evidence_hash"])))
        self.prices = sorted(grouped)
        self.groups = [sorted(grouped[price], key=lambda item: (item[0], item[2])) for price in self.prices]
        size = 1
        while size < len(self.prices):
            size *= 2
        self.size = size
        intervals: list[list[tuple[int, int]]] = [[] for _ in range(2 * size)]
        for index, group in enumerate(self.groups):
            intervals[size + index] = [(item[0], item[1]) for item in group]
        for node in range(size - 1, 0, -1):
            intervals[node] = intervals[node * 2] + intervals[node * 2 + 1]
        self.known: list[list[int]] = [[] for _ in intervals]
        self.prefix_broken: list[list[int]] = [[] for _ in intervals]
        for node, values in enumerate(intervals):
            values.sort(key=lambda item: (item[0], item[1]))
            self.known[node] = [item[0] for item in values]
            running = -1
            prefix: list[int] = []
            for _, broken in values:
                running = max(running, broken)
                prefix.append(running)
            self.prefix_broken[node] = prefix

    def _node_active(self, node: int, timestamp: int) -> bool:
        index = bisect.bisect_right(self.known[node], timestamp) - 1
        return index >= 0 and self.prefix_broken[node][index] > timestamp

    def _leaf_choice(self, index: int, timestamp: int) -> tuple[int, str, str] | None:
        active = [item for item in self.groups[index] if item[0] <= timestamp < item[1]]
        if not active:
            return None
        chosen = min(active, key=lambda item: (item[0], item[2]))
        return self.prices[index], chosen[2], chosen[3]

    def primary(self, direction: str, mark: int, timestamp: int) -> tuple[int, str, str] | None:
        if not self.prices:
            return None
        lower = bisect.bisect_right(self.prices, mark) if direction == "UP" else 0
        upper = len(self.prices) if direction == "UP" else bisect.bisect_left(self.prices, mark)

        def search(node: int, left: int, right: int) -> int | None:
            if right <= lower or left >= upper or not self._node_active(node, timestamp):
                return None
            if right - left == 1:
                return left if left < len(self.prices) else None
            middle = (left + right) // 2
            order = ((node * 2, left, middle), (node * 2 + 1, middle, right)) if direction == "UP" else ((node * 2 + 1, middle, right), (node * 2, left, middle))
            for child, child_left, child_right in order:
                found = search(child, child_left, child_right)
                if found is not None:
                    return found
            return None

        index = search(1, 0, self.size)
        return self._leaf_choice(index, timestamp) if index is not None else None

    def reference(self, direction: str, mark: int, timestamp: int) -> tuple[int, str, str] | None:
        if direction == "UP":
            start = bisect.bisect_right(self.prices, mark)
            indexes: Iterable[int] = range(start, len(self.prices))
        else:
            start = bisect.bisect_left(self.prices, mark) - 1
            indexes = range(start, -1, -1)
        for index in indexes:
            chosen = self._leaf_choice(index, timestamp)
            if chosen is not None:
                return chosen
        return None


def verify_file(path: Path, frozen: Mapping[str, Any]) -> None:
    if path.stat().st_size != int(frozen["bytes"]) or sha256_file(path) != str(frozen["sha256"]):
        raise ValueError(f"Frozen source changed: {path}")


def preflight() -> dict[str, Any]:
    readiness = json.loads(READINESS_FREEZE.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    definitions = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    if readiness.get("status") != "FROZEN_READY_FOR_OUTCOME_BLIND_TAPE_FEATURES":
        raise ValueError("Readiness freeze status changed")
    if protocol.get("status") != "FROZEN_BEFORE_DECISION_TAPE_MARKET_VALUES_OR_OUTCOMES":
        raise ValueError("Protocol status changed")
    if definitions.get("status") != "FROZEN_BEFORE_CHECKPOINT_MARKET_VALUES_OR_OUTCOMES":
        raise ValueError("Feature-definition freeze status changed")
    original_implementation = json.loads(ORIGINAL_IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
    amendment = json.loads(AMENDMENT_A.read_text(encoding="utf-8"))
    amendment_a_implementation = json.loads(AMENDMENT_A_IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
    amendment_b = json.loads(AMENDMENT_B.read_text(encoding="utf-8"))
    amendment_b_implementation = json.loads(AMENDMENT_B_IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
    baseline_audit = json.loads(BASELINE_AUDIT_SEAL.read_text(encoding="utf-8"))
    amendment_c = json.loads(AMENDMENT_C.read_text(encoding="utf-8"))
    if original_implementation.get("status") != "SEALED_BEFORE_CHECKPOINT_MARKET_VALUE_ACCESS":
        raise ValueError("Original implementation freeze changed")
    if amendment.get("status") != "FROZEN_BEFORE_AMENDED_IMPLEMENTATION_OR_RERUN":
        raise ValueError("Implementation Amendment A changed")
    if amendment_a_implementation.get("status") != "SEALED_BEFORE_CHECKPOINT_MARKET_VALUE_ACCESS":
        raise ValueError("Amendment A implementation freeze changed")
    if amendment_b.get("status") != "FROZEN_BEFORE_AMENDED_IMPLEMENTATION_OR_RERUN":
        raise ValueError("Implementation Amendment B changed")
    if amendment_b_implementation.get("status") != "SEALED_BEFORE_CHECKPOINT_MARKET_VALUE_ACCESS":
        raise ValueError("Amendment B implementation freeze changed")
    if baseline_audit.get("status") != "PASS_REPRODUCED_BASELINE_METADATA_AUDIT" or baseline_audit.get("classification_hash") != "b9faf50e048622ea35bd958f200d217f6482584ce7d983f653966173c1e38733":
        raise ValueError("Complete setup-baseline metadata audit changed")
    if amendment_c.get("status") != "FROZEN_AFTER_COMPLETE_METADATA_AUDIT_BEFORE_AMENDED_IMPLEMENTATION_OR_RERUN":
        raise ValueError("Implementation Amendment C changed")
    if readiness.get("checkpoint_rows") != 2_095_849 or readiness.get("checkpoint_identity_hash") != "7810c672637655ebfbca5bf9f73a0f3b8e74029087f2f24ed4b33e831eeb5559":
        raise ValueError("Checkpoint population changed")
    verify_file(CONTRACT, readiness["controls"]["contract"])
    verify_file(PROTOCOL, readiness["controls"]["protocol"])
    for name, frozen in readiness["casebook_sources"].items():
        verify_file(CASEBOOK / name, frozen)
    for key, filename in (("primary_registry", "primary_case_tape_registry.parquet"), ("reference_registry", "reference_case_tape_registry.parquet")):
        verify_file(READINESS / filename, readiness["artifacts"][key])
    if sha256_file(READINESS / "primary_case_tape_registry.parquet") != sha256_file(READINESS / "reference_case_tape_registry.parquet"):
        raise ValueError("Readiness registries differ")
    if any(path.exists() for path in (PRIMARY_OUTPUT, REFERENCE_OUTPUT, CERTIFICATION, FINAL_FREEZE)):
        raise FileExistsError("Tape materialization already exists")
    return readiness


def synthetic_proof() -> dict[str, Any]:
    rows = [
        (100, 90, 95, 105), (104, 92, 96, 110), (108, 94, 100, 115),
        (107, 93, 101, 114), (106, 91, 102, 113), (109, 98, 103, 116),
        (112, 101, 105, 118), (114, 104, 108, 119),
    ]
    high = np.asarray([item[3] for item in rows], dtype=np.int64)
    low = np.asarray([item[1] for item in rows], dtype=np.int64)
    fractals = derive_fractals(list(range(8)), high, low)
    assert fractals.low_known.tolist() == [6] and fractals.low_level.tolist() == [91]
    sample = sorted(checkpoint_sample_indexes(240))
    assert len(sample) == 32 and sample[0] == 0 and sample[-1] == 239 and len(set(sample)) == 32
    index = IntervalPriceIndex([
        {"price_e8": 120, "known_ns": 1, "broken_ns": 10, "swing_id": "a", "evidence_hash": "x"},
        {"price_e8": 130, "known_ns": 1, "broken_ns": 100, "swing_id": "b", "evidence_hash": "y"},
        {"price_e8": 80, "known_ns": 1, "broken_ns": 100, "swing_id": "c", "evidence_hash": "z"},
    ])
    assert index.primary("UP", 110, 20) == index.reference("UP", 110, 20) == (130, "b", "y")
    assert index.primary("DOWN", 110, 20) == index.reference("DOWN", 110, 20) == (80, "c", "z")
    return {"status": "PASS_SYNTHETIC_POINT_IN_TIME_FEATURE_PROOF", "fractal_known_index": int(fractals.low_known[0]), "sample_count": len(sample), "interval_queries_match": True}


def write_or_verify_implementation_freeze(readiness: Mapping[str, Any], proof: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_TAPE_IMPLEMENTATION_FREEZE_C1_1_0",
        "status": "SEALED_BEFORE_CHECKPOINT_MARKET_VALUE_ACCESS",
        "sealed_at_utc": utc_now(),
        "controls": {"contract": file_record(CONTRACT), "protocol": file_record(PROTOCOL), "definitions": file_record(DEFINITIONS), "readiness": file_record(READINESS_FREEZE)},
        "preserved_original_implementation": file_record(ORIGINAL_IMPLEMENTATION_FREEZE),
        "amendment_a": file_record(AMENDMENT_A),
        "preserved_amendment_a_implementation": file_record(AMENDMENT_A_IMPLEMENTATION_FREEZE),
        "amendment_b": file_record(AMENDMENT_B),
        "preserved_amendment_b_implementation": file_record(AMENDMENT_B_IMPLEMENTATION_FREEZE),
        "baseline_metadata_audit": file_record(BASELINE_AUDIT_SEAL),
        "amendment_c": file_record(AMENDMENT_C),
        "implementation": file_record(Path(__file__).resolve()),
        "synthetic_proof": dict(proof),
        "checkpoint_identity_hash": readiness["checkpoint_identity_hash"],
        "checkpoint_rows": readiness["checkpoint_rows"],
        "development_outcomes_accessed": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    if IMPLEMENTATION_FREEZE.exists():
        existing = json.loads(IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
        for key in ("contract", "protocol", "definitions", "readiness"):
            if existing["controls"][key]["sha256"] != payload["controls"][key]["sha256"]:
                raise ValueError(f"Existing implementation freeze differs: {key}")
        if existing["implementation"]["sha256"] != payload["implementation"]["sha256"]:
            raise ValueError("Implementation changed after freeze")
        return existing
    write_json_exclusive(IMPLEMENTATION_FREEZE, payload)
    return payload


def load_price() -> tuple[dict[str, Frame], dict[str, Any]]:
    fields: dict[str, dict[str, list[Any]]] = {
        name: {key: [] for key in ("open_ns", "close_ns", "available_ns", "open_e8", "high_e8", "low_e8", "close_e8", "volume", "spread", "missing", "valid")}
        for name in RAW_TO_CANONICAL.values()
    }
    scanned = selected = incomplete = malformed = duplicate = 0
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            scanned += 1
            row = json.loads(line)
            raw_tf = str(row.get("timeframe"))
            if row.get("record_type") != "PRICE_BAR" or row.get("instrument_code") != "XAUUSD" or raw_tf not in RAW_TO_CANONICAL:
                continue
            opened = parse_ns(str(row["open_time"])); closed = parse_ns(str(row["close_time"])); available = parse_ns(str(row["available_at"]))
            if opened >= END_NS or closed > END_NS:
                raise ValueError("Calendar-2025/2026 price value encountered")
            if row.get("complete") is not True:
                incomplete += 1
                continue
            ohlc = row.get("ohlc") if isinstance(row.get("ohlc"), Mapping) else {}
            if any(ohlc.get(key) is None for key in ("open", "high", "low", "close")):
                malformed += 1
                continue
            opened_price, high, low, close = (scaled(ohlc[key]) for key in ("open", "high", "low", "close"))
            valid_ohlc = low <= min(opened_price, close) <= max(opened_price, close) <= high
            name = RAW_TO_CANONICAL[raw_tf]; target = fields[name]
            target["open_ns"].append(opened); target["close_ns"].append(closed); target["available_ns"].append(available)
            target["open_e8"].append(opened_price); target["high_e8"].append(high); target["low_e8"].append(low); target["close_e8"].append(close)
            target["volume"].append(finite(row.get("volume")) if finite(row.get("volume")) is not None else math.nan)
            spread = finite(row.get("spread_price")); target["spread"].append(spread if spread is not None and spread >= 0 else math.nan)
            missing = int(row.get("missing_source_minutes") or 0); target["missing"].append(missing)
            target["valid"].append(bool(valid_ohlc and available <= closed and missing == 0 and closed - opened == INTERVAL_NS[name]))
            selected += 1
    output: dict[str, Frame] = {}
    for name, values in fields.items():
        order = np.argsort(np.asarray(values["close_ns"], dtype=np.int64), kind="stable")
        ordered = {key: np.asarray(value)[order] for key, value in values.items()}
        keep = np.ones(len(order), dtype=bool)
        if len(order) > 1:
            repeated = ordered["close_ns"][1:] == ordered["close_ns"][:-1]
            duplicate += int(np.sum(repeated)); keep[1:] &= ~repeated
        ordered = {key: value[keep] for key, value in ordered.items()}
        output[name] = Frame(
            name,
            ordered["open_ns"].astype(np.int64), ordered["close_ns"].astype(np.int64), ordered["available_ns"].astype(np.int64),
            ordered["open_e8"].astype(np.int64), ordered["high_e8"].astype(np.int64), ordered["low_e8"].astype(np.int64), ordered["close_e8"].astype(np.int64),
            ordered["volume"].astype(np.float64), ordered["spread"].astype(np.float64), ordered["missing"].astype(np.int16), ordered["valid"].astype(bool),
        )
        if not len(output[name].close_ns) or np.any(np.diff(output[name].close_ns) <= 0):
            raise ValueError(f"Invalid price ordering: {name}")
    return output, {
        "rows_scanned": scanned, "rows_selected": selected, "incomplete_skipped": incomplete,
        "malformed_skipped": malformed, "duplicate_close_times": duplicate,
        "counts": {name: len(frame.close_ns) for name, frame in output.items()}, "source": file_record(PRICE),
    }


def load_macro(path: Path, record_type: str) -> MacroRows:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if record_type == "FUNDAMENTAL_SNAPSHOT" and row.get("record_type") != record_type:
                continue
            available_raw = row.get("available_at") or row.get("publication_at")
            if available_raw is None:
                continue
            available = parse_ns(str(available_raw))
            if available >= END_NS:
                raise ValueError(f"Calendar-2025/2026 {record_type} value encountered")
            if record_type == "FUNDAMENTAL_SNAPSHOT":
                engine = row.get("engine_state") if isinstance(row.get("engine_state"), Mapping) else {}
                components = {str(item.get("code")): dict(item) for item in engine.get("components", []) if isinstance(item, Mapping) and item.get("code") is not None}
                rows.append({
                    "available_ns": available, "record_id": str(row.get("record_id")), "record_hash": str(row.get("record_hash")),
                    "score": finite(engine.get("directional_score")), "confidence": finite(engine.get("confidence")), "coverage": finite(engine.get("coverage")),
                    "regime": str(engine.get("regime_label") or "UNKNOWN"), "reaction_function": str(engine.get("reaction_function") or "UNKNOWN"),
                    "event_risk": str(engine.get("event_risk") or "UNKNOWN"), "components": components,
                })
            else:
                calculated = row.get("calculated") if isinstance(row.get("calculated"), Mapping) else {}
                rows.append({
                    "available_ns": available, "record_id": str(row.get("record_id")), "record_hash": str(row.get("record_hash")),
                    "percentile": finite(calculated.get("managed_money_net_percentile")), "net_change": finite(calculated.get("managed_money_net_change")),
                })
    rows.sort(key=lambda item: (item["available_ns"], item["record_id"]))
    return MacroRows(rows, np.asarray([int(item["available_ns"]) for item in rows], dtype=np.int64))


def derive_fractals(known_times: Sequence[int], high: np.ndarray, low: np.ndarray) -> Fractals:
    low_known: list[int] = []; low_level: list[int] = []; high_known: list[int] = []; high_level: list[int] = []
    for center in range(2, len(high) - 2):
        known = int(known_times[center + 2])
        if low[center] < low[center - 1] and low[center] < low[center - 2] and low[center] <= low[center + 1] and low[center] <= low[center + 2]:
            low_known.append(known); low_level.append(int(low[center]))
        if high[center] > high[center - 1] and high[center] > high[center - 2] and high[center] >= high[center + 1] and high[center] >= high[center + 2]:
            high_known.append(known); high_level.append(int(high[center]))
    return Fractals(
        np.asarray(low_known, dtype=np.int64), np.asarray(low_level, dtype=np.int64),
        np.asarray(high_known, dtype=np.int64), np.asarray(high_level, dtype=np.int64),
    )


def checkpoint_sample_indexes(count: int) -> set[int]:
    if count <= 32:
        return set(range(count))
    return {int(math.floor(index * (count - 1) / 31 + 0.5)) for index in range(32)}


def build_daily_weekly(m15: Frame) -> tuple[DailyState, DailyState]:
    groups: dict[date, list[int]] = defaultdict(list)
    for index, opened in enumerate(m15.open_ns):
        value = datetime.fromtimestamp(int(opened) / 1_000_000_000, UTC)
        key = (value.astimezone(NY) - timedelta(hours=17)).date()
        groups[key].append(index)
    daily_completed: list[int] = []; daily_close: list[int] = []
    week_groups: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for key in sorted(groups):
        indexes = groups[key]
        completed = datetime.combine(key + timedelta(days=1), time(17), NY).astimezone(UTC)
        completed_ns = int(completed.timestamp()) * 1_000_000_000
        close = int(m15.close_e8[indexes[-1]])
        daily_completed.append(completed_ns); daily_close.append(close)
        iso = key.isocalendar(); week_groups[(iso.year, iso.week)].append((completed_ns, close))
    weekly_completed: list[int] = []; weekly_close: list[int] = []
    for key in sorted(week_groups):
        values = sorted(week_groups[key])
        weekly_completed.append(values[-1][0]); weekly_close.append(values[-1][1])
    return DailyState(daily_completed, daily_close), DailyState(weekly_completed, weekly_close)


def relative_state(times: Sequence[int], directions: Sequence[str], checkpoint: int, direction: str, implementation: str) -> str:
    index = int(np.searchsorted(times, checkpoint, side="right")) - 1 if implementation == "primary" else bisect.bisect_right(times, checkpoint) - 1
    if index < 0:
        return "UNKNOWN"
    return "ALIGNED" if directions[index] == direction else "OPPOSED"


def dynamic_alignment(case_tf: str, direction: str, checkpoint: int, timelines: Mapping[str, tuple[Sequence[int], list[str]]], daily: DailyState, weekly: DailyState, implementation: str) -> tuple[float | None, str, str]:
    h1 = relative_state(*timelines["H1"], checkpoint, direction, implementation)
    h4 = relative_state(*timelines["H4"], checkpoint, direction, implementation)
    values: list[bool] = []
    if case_tf == "M15" and h1 != "UNKNOWN": values.append(h1 == "ALIGNED")
    if case_tf in {"M15", "H1"} and h4 != "UNKNOWN": values.append(h4 == "ALIGNED")
    sign = 1 if direction == "UP" else -1
    day_index = bisect.bisect_right(daily.completed_ns, checkpoint) - 1
    if day_index >= 2: values.append(sign * (daily.close_e8[day_index] - daily.close_e8[day_index - 2]) > 0)
    week_index = bisect.bisect_right(weekly.completed_ns, checkpoint) - 1
    if week_index >= 1: values.append(sign * (weekly.close_e8[week_index] - weekly.close_e8[week_index - 1]) > 0)
    return (sum(values) / len(values) if values else None), h1, h4


def session_state(timestamp: int) -> str:
    value = datetime.fromtimestamp(timestamp / 1_000_000_000, UTC)
    ny_time = value.astimezone(NY).time(); london_time = value.astimezone(LONDON).time(); tokyo_time = value.astimezone(TOKYO).time()
    rollover = time(16, 55) <= ny_time < time(17, 10)
    london = time(8) <= london_time < time(12); new_york = time(8) <= ny_time < time(12); asia = time(10) <= tokyo_time < time(16)
    if rollover: return "ROLLOVER"
    if london and new_york: return "LONDON_NEW_YORK_OVERLAP"
    if london: return "LONDON"
    if new_york: return "NEW_YORK"
    if asia: return "ASIA"
    return "OTHER"


def normalized_01(value: float | None) -> float | None:
    if value is None: return None
    return value / 100.0 if abs(value) > 1.0 else value


def select_macro(source: MacroRows, checkpoint: int, max_age_ns: int, implementation: str) -> dict[str, Any] | None:
    index = int(np.searchsorted(source.times, checkpoint, side="right")) - 1 if implementation == "primary" else bisect.bisect_right(source.times, checkpoint) - 1
    if index < 0: return None
    row = source.rows[index]
    return row if 0 <= checkpoint - int(row["available_ns"]) <= max_age_ns else None


def latest_adverse_fractal(fractals: Fractals, direction: str, checkpoint: int, mark: int, implementation: str) -> int | None:
    times, levels = (fractals.low_known, fractals.low_level) if direction == "UP" else (fractals.high_known, fractals.high_level)
    index = int(np.searchsorted(times, checkpoint, side="right")) - 1 if implementation == "primary" else bisect.bisect_right(times, checkpoint) - 1
    while index >= 0:
        level = levels[index]
        if (direction == "UP" and level < mark) or (direction == "DOWN" and level > mark):
            return level
        index -= 1
    return None


def latest_fractal_level(times: Sequence[int], levels: Sequence[int], checkpoint: int, implementation: str) -> int | None:
    index = int(np.searchsorted(times, checkpoint, side="right")) - 1 if implementation == "primary" else bisect.bisect_right(times, checkpoint) - 1
    return levels[index] if index >= 0 else None


def precompute_frame_derived(frame: Frame) -> FrameDerived:
    count = len(frame.close_e8)
    volume_ratio = np.full(count, np.nan, dtype=np.float64)
    for index in range(count):
        value = float(frame.volume[index]); prior = frame.volume[max(0, index - 20):index]
        finite_prior = prior[np.isfinite(prior)]
        if math.isfinite(value) and len(finite_prior):
            denominator = float(np.median(finite_prior))
            if denominator != 0: volume_ratio[index] = value / denominator
    closes = frame.close_e8.astype(np.float64) / SCALE
    returns = np.zeros(count, dtype=np.float64)
    returns[1:] = np.diff(np.log(closes))
    prefix = np.concatenate(([0.0], np.cumsum(returns)))
    prefix_sq = np.concatenate(([0.0], np.cumsum(returns * returns)))

    def sample_std(left: int, right: int) -> float | None:
        observations = right - left
        if observations < 2: return None
        total = prefix[right] - prefix[left]; total_sq = prefix_sq[right] - prefix_sq[left]
        variance = max(0.0, (total_sq - total * total / observations) / (observations - 1))
        return math.sqrt(variance)

    volatility = np.full(count, np.nan, dtype=np.float64)
    for index in range(50, count):
        long_left = max(1, index - 99); recent_left = max(1, index - 19); right = index + 1
        denominator = sample_std(long_left, right); numerator = sample_std(recent_left, right)
        if denominator is not None and numerator is not None and denominator > 0: volatility[index] = numerator / denominator
    return FrameDerived(volume_ratio, volatility)


def candle_values(frame: Frame, index: int, direction: str, atr: float) -> dict[str, float | None]:
    high = int(frame.high_e8[index]); low = int(frame.low_e8[index]); opened = int(frame.open_e8[index]); close = int(frame.close_e8[index]); width = high - low
    sign = 1 if direction == "UP" else -1
    if width <= 0:
        return {"range": 0.0, "body": None, "location": None, "rejection": None}
    location = (close - low) / width if sign > 0 else (high - close) / width
    rejection = (min(opened, close) - low) / width if sign > 0 else (high - max(opened, close)) / width
    return {"range": width / atr, "body": abs(close - opened) / width, "location": location, "rejection": rejection}


def path_efficiency(frame: Frame, index: int, direction: str) -> tuple[float | None, float | None]:
    sign = 1 if direction == "UP" else -1
    displacement3 = None
    if index >= 3:
        displacement3 = sign * (int(frame.close_e8[index]) - int(frame.close_e8[index - 3]))
    efficiency = None
    if index >= 5:
        closes = frame.close_e8[index - 5:index + 1]
        path = int(np.sum(np.abs(np.diff(closes))))
        net = sign * (int(closes[-1]) - int(closes[0]))
        efficiency = net / path if path else 0.0
    return displacement3, efficiency


def acceptance_and_sweep(frame: Frame, index: int, direction: str, atr: float) -> tuple[float, float]:
    if index < 6: return 0.0, 0.0
    prior_high = int(np.max(frame.high_e8[index - 6:index - 1])); prior_low = int(np.min(frame.low_e8[index - 6:index - 1]))
    current_close = int(frame.close_e8[index]); prior_close = int(frame.close_e8[index - 1]); threshold = 0.05 * atr
    if direction == "UP":
        acceptance = 1.0 if current_close > prior_high + threshold and prior_close > prior_high + threshold else -1.0 if current_close < prior_low - threshold and prior_close < prior_low - threshold else 0.0
        sweep = 1.0 if int(frame.low_e8[index]) < prior_low - threshold and current_close > prior_low else -1.0 if int(frame.high_e8[index]) > prior_high + threshold and current_close < prior_high else 0.0
    else:
        acceptance = 1.0 if current_close < prior_low - threshold and prior_close < prior_low - threshold else -1.0 if current_close > prior_high + threshold and prior_close > prior_high + threshold else 0.0
        sweep = 1.0 if int(frame.high_e8[index]) > prior_high + threshold and current_close < prior_high else -1.0 if int(frame.low_e8[index]) < prior_low - threshold and current_close > prior_low else 0.0
    return acceptance, sweep


def static_rows() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    registry = pq.read_table(READINESS / "primary_case_tape_registry.parquet").to_pylist()
    feature_columns = ["pullback_id", "feature_available", "feature_lineage_hash", "atr14_e8", "trend_age_bars", "prior_continuation_count"] + list(STATIC_MAPPING.values())
    features = {str(row["pullback_id"]): dict(row) for row in pq.read_table(STATIC / "primary_features.parquet", columns=feature_columns).to_pylist()}
    case_columns = ["pullback_id", "segment_id", "pivot_swing_id", "reference_event_id", "pivot_price_e8", "reference_level_e8", "decision_facts_hash"]
    cases = {str(row["pullback_id"]): dict(row) for row in pq.read_table(CENSUS / "primary_pullback_cases.parquet", columns=case_columns).to_pylist()}
    merged: dict[str, dict[str, Any]] = {}
    for item in registry:
        identity = str(item["pullback_id"])
        if identity not in features or identity not in cases: raise ValueError(f"Missing static case: {identity}")
        merged[identity] = {**dict(item), **cases[identity], **features[identity]}
    if len(merged) != 8653: raise ValueError("Static population changed")
    return [dict(item) for item in registry], merged, {"static_rows": len(merged), "static_feature_available": sum(bool(item.get("feature_available")) for item in merged.values())}


def structure_sources() -> tuple[dict[str, tuple[np.ndarray, list[str]]], dict[tuple[str, str], IntervalPriceIndex], dict[str, Any]]:
    events = pq.read_table(CENSUS / "primary_structure_events.parquet", columns=["event_at_utc", "timeframe", "scale", "direction", "broken_swing_ids_json"]).to_pylist()
    broken: dict[str, int] = {}
    timelines_raw: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in events:
        timestamp = parse_ns(str(row["event_at_utc"]))
        if timestamp >= END_NS: raise ValueError("Forward structure event encountered")
        for swing_id in json.loads(str(row["broken_swing_ids_json"])): broken.setdefault(str(swing_id), timestamp)
        if row["scale"] == "STANDARD" and row["timeframe"] in {"H1", "H4"}: timelines_raw[str(row["timeframe"])].append((timestamp, str(row["direction"])))
    timelines: dict[str, tuple[np.ndarray, list[str]]] = {}
    for timeframe in ("H1", "H4"):
        values = sorted(timelines_raw[timeframe]); timelines[timeframe] = (np.asarray([item[0] for item in values], dtype=np.int64), [item[1] for item in values])
    swings = pq.read_table(CENSUS / "primary_swings.parquet", columns=["swing_id", "timeframe", "scale", "side", "known_at_utc", "price_e8", "evidence_hash"]).to_pylist()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in swings:
        if row["scale"] != "STANDARD" or row["timeframe"] not in {"M15", "H1", "H4"}: continue
        known = parse_ns(str(row["known_at_utc"])); swing_id = str(row["swing_id"])
        grouped[(str(row["timeframe"]), str(row["side"]))].append({
            "price_e8": int(row["price_e8"]), "known_ns": known, "broken_ns": broken.get(swing_id, END_NS),
            "swing_id": swing_id, "evidence_hash": str(row["evidence_hash"]),
        })
    indexes = {key: IntervalPriceIndex(value) for key, value in grouped.items()}
    return timelines, indexes, {"structure_events": len(events), "standard_swing_indexes": {f"{key[0]}|{key[1]}": len(value.prices) for key, value in indexes.items()}}


def schema() -> pa.Schema:
    fields = [
        pa.field("row_id", pa.string(), False), pa.field("pullback_id", pa.string(), False), pa.field("timeframe", pa.string(), False),
        pa.field("direction", pa.string(), False), pa.field("decision_date", pa.string(), False), pa.field("known_at_utc", pa.string(), False),
        pa.field("deadline_at_utc", pa.string(), False), pa.field("checkpoint_at_utc", pa.string(), False), pa.field("checkpoint_index", pa.int32(), False),
        pa.field("training_checkpoint", pa.bool_(), False), pa.field("checkpoint_feature_available", pa.bool_(), False), pa.field("unavailable_reason", pa.string(), False),
        pa.field("fill_open_at_utc", pa.string(), False), pa.field("setup_atr_e8", pa.float64()), pa.field("setup_pivot_e8", pa.int64()),
        pa.field("reference_level_e8", pa.int64()), pa.field("decision_close_e8", pa.int64()), pa.field("structural_stop_e8", pa.int64()),
        pa.field("liquidity_target_e8", pa.int64()), pa.field("target_swing_id", pa.string()), pa.field("geometry_available_at_decision_mark", pa.bool_(), False),
    ]
    fields.extend(pa.field(name, pa.float64()) for name in NUMERIC_PREDICTORS)
    fields.extend(pa.field(name, pa.string(), False) for name in CATEGORICAL_PREDICTORS)
    fields.extend([pa.field("static_feature_lineage_hash", pa.string(), False), pa.field("feature_lineage_hash", pa.string(), False)])
    return pa.schema(fields)


class Checksums:
    def __init__(self, output_schema: pa.Schema) -> None:
        self.columns = {name: hashlib.sha256() for name in output_schema.names}
        self.complete = hashlib.sha256(); self.nulls = Counter(); self.rows = 0

    def update(self, table: pa.Table) -> None:
        self.complete.update(len(table).to_bytes(8, "little")); self.rows += len(table)
        for name in table.schema.names:
            array = table[name].combine_chunks(); digest = self.columns[name]
            digest.update(len(array).to_bytes(8, "little")); digest.update(str(array.type).encode("utf-8"))
            for buffer in array.buffers():
                if buffer is None: digest.update(b"<NONE>")
                else:
                    payload = buffer.to_pybytes(); digest.update(len(payload).to_bytes(8, "little")); digest.update(payload)
            column_hash = hashlib.sha256()
            column_hash.update(name.encode("utf-8")); column_hash.update(digest.copy().digest())
            self.complete.update(column_hash.digest()); self.nulls[name] += array.null_count

    def result(self) -> dict[str, Any]:
        return {"rows": self.rows, "per_column": {name: value.hexdigest() for name, value in self.columns.items()}, "complete": self.complete.hexdigest(), "null_counts": dict(sorted(self.nulls.items()))}


def exact_checkpoint_indexes(case: Mapping[str, Any], frame: Frame, m1: Frame, implementation: str) -> list[int]:
    known = parse_ns(str(case["known_at_utc"])); deadline = parse_ns(str(case["deadline_at_utc"]))
    left = int(np.searchsorted(frame.close_ns, known, side="left")) if implementation == "primary" else bisect.bisect_left(frame.close_ns, known)
    right = int(np.searchsorted(frame.close_ns, deadline, side="left")) if implementation == "primary" else bisect.bisect_left(frame.close_ns, deadline)
    indexes: list[int] = []
    for index in range(left, right):
        timestamp = int(frame.close_ns[index])
        signal_open_index = int(np.searchsorted(frame.open_ns, timestamp, side="left")) if implementation == "primary" else bisect.bisect_left(frame.open_ns, timestamp)
        m1_index = int(np.searchsorted(m1.open_ns, timestamp, side="left")) if implementation == "primary" else bisect.bisect_left(m1.open_ns, timestamp)
        if signal_open_index < len(frame.open_ns) and int(frame.open_ns[signal_open_index]) == timestamp and m1_index < len(m1.open_ns) and int(m1.open_ns[m1_index]) == timestamp:
            indexes.append(index)
    return indexes


def verify_checkpoint_parity(registry: Sequence[Mapping[str, Any]], cases: Mapping[str, Mapping[str, Any]], frames: Mapping[str, Frame], implementation: str) -> dict[str, Any]:
    digest = hashlib.sha256(); baseline_digest = hashlib.sha256(); rows = available_cases = baseline_available = baseline_unavailable = 0
    for registry_row in registry:
        case = cases[str(registry_row["pullback_id"])]; frame = frames[SIGNAL_FRAME[str(case["timeframe"])]]; known = parse_ns(str(case["known_at_utc"])); parent = frames[str(case["timeframe"])]
        signal_index = int(np.searchsorted(frame.close_ns, known, side="left")) if implementation == "primary" else bisect.bisect_left(frame.close_ns, known)
        parent_index = int(np.searchsorted(parent.close_ns, known, side="left")) if implementation == "primary" else bisect.bisect_left(parent.close_ns, known)
        signal_exact = signal_index < len(frame.close_ns) and int(frame.close_ns[signal_index]) == known
        parent_exact = parent_index < len(parent.close_ns) and int(parent.close_ns[parent_index]) == known
        first_exact = str(registry_row.get("first_checkpoint_at_utc")) == str(registry_row["known_at_utc"]) if registry_row["tape_status"] == "AVAILABLE" else False
        baseline_available += int(signal_exact); baseline_unavailable += int(not signal_exact)
        baseline_digest.update(canonical_json([str(case["pullback_id"]), known, signal_exact, parent_exact, first_exact]).encode("utf-8")); baseline_digest.update(b"\n")
        if registry_row["tape_status"] != "AVAILABLE": continue
        available_cases += 1
        indexes = exact_checkpoint_indexes(case, frame, frames["M1"], implementation)
        timestamps = [int(frame.close_ns[index]) for index in indexes]
        if len(timestamps) != int(registry_row["checkpoint_rows"]) or canonical_hash(timestamps) != str(registry_row["checkpoint_timestamp_hash"]):
            raise ValueError(f"Checkpoint identity changed: {case['pullback_id']}")
        for timestamp in timestamps:
            digest.update(canonical_json([str(case["pullback_id"]), timestamp]).encode("utf-8")); digest.update(b"\n")
        rows += len(timestamps)
    result = {"implementation": implementation, "available_cases": available_cases, "checkpoint_rows": rows, "checkpoint_identity_hash": digest.hexdigest(), "setup_baseline_available": baseline_available, "setup_baseline_unavailable": baseline_unavailable, "baseline_classification_hash": baseline_digest.hexdigest()}
    if available_cases != 8650 or rows != 2_095_849 or result["checkpoint_identity_hash"] != "7810c672637655ebfbca5bf9f73a0f3b8e74029087f2f24ed4b33e831eeb5559" or baseline_available != 8418 or baseline_unavailable != 235 or result["baseline_classification_hash"] != "b9faf50e048622ea35bd958f200d217f6482584ce7d983f653966173c1e38733":
        raise ValueError(f"Global checkpoint parity failed: {result}")
    return result


def checkpoint_row(
    case: Mapping[str, Any], frame: Frame, index: int, checkpoint_number: int, sampled: bool,
    setup_close: int | None, running_high: int, running_low: int,
    frames: Mapping[str, Frame], derived: Mapping[str, FrameDerived], fundamentals: MacroRows, positioning: MacroRows,
    timelines: Mapping[str, tuple[Sequence[int], list[str]]], targets: Mapping[tuple[str, str], IntervalPriceIndex],
    fractals: Mapping[str, Fractals], daily: DailyState, weekly: DailyState, definition_hash: str, implementation: str,
) -> dict[str, Any]:
    checkpoint = int(frame.close_ns[index]); direction = str(case["direction"]); sign = 1 if direction == "UP" else -1
    known = parse_ns(str(case["known_at_utc"])); deadline = parse_ns(str(case["deadline_at_utc"])); atr = finite(case.get("atr14_e8"))
    pivot = int(case["pivot_price_e8"]); reference = int(case["reference_level_e8"]); mark = int(frame.close_e8[index])
    reasons: list[str] = []
    if not bool(frame.valid[index]): reasons.append("INVALID_OR_INCOMPLETE_CHECKPOINT_BAR")
    m1 = frames["M1"]; fill_index = int(np.searchsorted(m1.open_ns, checkpoint, side="left")) if implementation == "primary" else bisect.bisect_left(m1.open_ns, checkpoint)
    if fill_index >= len(m1.open_ns) or int(m1.open_ns[fill_index]) != checkpoint: reasons.append("MISSING_EXACT_M1_FILL_TIMESTAMP")
    if atr is None or atr <= 0: reasons.append("SETUP_ATR_UNAVAILABLE")

    row: dict[str, Any] = {
        "row_id": canonical_hash([str(case["pullback_id"]), checkpoint]), "pullback_id": str(case["pullback_id"]), "timeframe": str(case["timeframe"]),
        "direction": direction, "decision_date": str(case["decision_date"]), "known_at_utc": str(case["known_at_utc"]), "deadline_at_utc": str(case["deadline_at_utc"]),
        "checkpoint_at_utc": ns_iso(checkpoint), "checkpoint_index": checkpoint_number, "training_checkpoint": sampled,
        "fill_open_at_utc": ns_iso(checkpoint), "setup_atr_e8": atr, "setup_pivot_e8": pivot, "reference_level_e8": reference,
        "decision_close_e8": mark, "structural_stop_e8": None, "liquidity_target_e8": None, "target_swing_id": None,
        "geometry_available_at_decision_mark": False,
    }
    for output_name, source_name in STATIC_MAPPING.items(): row[output_name] = finite(case.get(source_name))
    row["setup_trend_age_log1p"] = math.log1p(max(0, int(case.get("trend_age_bars") or 0)))
    row["setup_prior_continuations_log1p"] = math.log1p(max(0, int(case.get("prior_continuation_count") or 0)))

    fundamental = select_macro(fundamentals, checkpoint, 96 * 3_600_000_000_000, implementation)
    score = fundamental.get("score") if fundamental else None; confidence = fundamental.get("confidence") if fundamental else None; coverage = fundamental.get("coverage") if fundamental else None
    aligned_score = sign * score if score is not None else None
    row["fundamental_score_aligned"] = aligned_score; row["fundamental_confidence_01"] = normalized_01(confidence); row["fundamental_coverage_01"] = normalized_01(coverage)
    if fundamental is None or aligned_score is None or confidence is None or coverage is None: alignment_state = "UNKNOWN"
    elif aligned_score >= 20 and coverage >= 50 and confidence >= 35: alignment_state = "ALIGNED"
    elif aligned_score <= -20 and coverage >= 50 and confidence >= 35: alignment_state = "OPPOSED"
    else: alignment_state = "NEUTRAL_OR_WEAK"
    row["fundamental_alignment_state"] = alignment_state; row["fundamental_regime"] = str(fundamental.get("regime") if fundamental else "UNKNOWN")
    row["reaction_function"] = str(fundamental.get("reaction_function") if fundamental else "UNKNOWN"); row["event_risk"] = str(fundamental.get("event_risk") if fundamental else "UNKNOWN")
    for code, column in COMPONENT_COLUMNS.items():
        component = fundamental["components"].get(code) if fundamental else None
        contribution = finite(component.get("contribution")) if isinstance(component, Mapping) else None
        row[column] = sign * contribution if contribution is not None else None

    cot = select_macro(positioning, checkpoint, 14 * 86_400_000_000_000, implementation)
    percentile = cot.get("percentile") if cot else None; net_change = cot.get("net_change") if cot else None
    row["cot_percentile_01"] = normalized_01(percentile)
    aligned_change = sign * net_change if net_change is not None else None
    row["cot_net_change_aligned_signed_log"] = math.copysign(math.log1p(abs(aligned_change)), aligned_change) if aligned_change not in (None, 0) else (0.0 if aligned_change == 0 else None)

    alignment_fraction, h1_state, h4_state = dynamic_alignment(str(case["timeframe"]), direction, checkpoint, timelines, daily, weekly, implementation)
    row["higher_timeframe_alignment_fraction"] = alignment_fraction; row["h1_relative_state"] = h1_state; row["h4_relative_state"] = h4_state
    elapsed = (checkpoint - known) / (deadline - known) if deadline > known else None
    row["elapsed_fraction"] = elapsed; row["time_remaining_fraction"] = 1.0 - elapsed if elapsed is not None else None

    if atr is not None and atr > 0:
        row["current_displacement_atr"] = sign * (mark - setup_close) / atr if setup_close is not None else None
        row["pivot_distance_atr"] = sign * (mark - pivot) / atr; row["reference_distance_atr"] = sign * (mark - reference) / atr
        row["running_favourable_atr"] = (((running_high - setup_close) if sign > 0 else (setup_close - running_low)) / atr) if setup_close is not None else None
        row["running_adverse_atr"] = (((setup_close - running_low) if sign > 0 else (running_high - setup_close)) / atr) if setup_close is not None else None
        displacement3, efficiency5 = path_efficiency(frame, index, direction)
        row["recent_3_displacement_atr"] = displacement3 / atr if displacement3 is not None else None; row["recent_5_efficiency"] = efficiency5
        candle = candle_values(frame, index, direction, atr)
        row["current_range_atr"] = candle["range"]; row["current_body_fraction"] = candle["body"]; row["current_close_location"] = candle["location"]; row["current_rejection_wick"] = candle["rejection"]
        row["spread_atr"] = float(frame.spread[index]) / (atr / SCALE) if math.isfinite(float(frame.spread[index])) and atr > 0 else None
        acceptance, sweep = acceptance_and_sweep(frame, index, direction, atr); row["acceptance_state"] = acceptance; row["sweep_reclaim_state"] = sweep
    else:
        for name in ("current_displacement_atr", "pivot_distance_atr", "reference_distance_atr", "running_favourable_atr", "running_adverse_atr", "recent_3_displacement_atr", "recent_5_efficiency", "current_range_atr", "current_body_fraction", "current_close_location", "current_rejection_wick", "spread_atr"): row[name] = None
        row["acceptance_state"] = 0.0; row["sweep_reclaim_state"] = 0.0
    volume_ratio = float(derived[frame.name].volume_ratio_20[index]); volatility_ratio = float(derived[frame.name].volatility_ratio[index])
    row["volume_ratio_20"] = volume_ratio if math.isfinite(volume_ratio) else None
    row["rolling_volatility_ratio"] = volatility_ratio if math.isfinite(volatility_ratio) else None
    row["session_state"] = session_state(checkpoint)

    local = fractals[frame.name]
    latest_high = latest_fractal_level(local.high_known, local.high_level, checkpoint, implementation); latest_low = latest_fractal_level(local.low_known, local.low_level, checkpoint, implementation)
    if direction == "UP": local_score = 1.0 if latest_high is not None and mark > latest_high else -1.0 if latest_low is not None and mark < latest_low else 0.0
    else: local_score = 1.0 if latest_low is not None and mark < latest_low else -1.0 if latest_high is not None and mark > latest_high else 0.0
    row["local_structure_score"] = local_score

    target_hash = None
    if atr is not None and atr > 0:
        base_stop = int(round(pivot - 0.15 * atr if direction == "UP" else pivot + 0.15 * atr))
        adverse = latest_adverse_fractal(local, direction, checkpoint, mark, implementation)
        if adverse is not None:
            fractal_stop = int(round(adverse - 0.10 * atr if direction == "UP" else adverse + 0.10 * atr))
            stop = max(base_stop, fractal_stop) if direction == "UP" else min(base_stop, fractal_stop)
        else: stop = base_stop
        if (direction == "UP" and stop >= mark) or (direction == "DOWN" and stop <= mark): stop = base_stop
        if (direction == "UP" and stop < mark) or (direction == "DOWN" and stop > mark): row["structural_stop_e8"] = stop
        side = "UPPER" if direction == "UP" else "LOWER"; indexer = targets[(str(case["timeframe"]), side)]
        target = indexer.primary(direction, mark, checkpoint) if implementation == "primary" else indexer.reference(direction, mark, checkpoint)
        if target is not None:
            target_price, target_id, target_hash = target; row["liquidity_target_e8"] = target_price; row["target_swing_id"] = target_id
        if row["structural_stop_e8"] is not None and row["liquidity_target_e8"] is not None:
            risk = sign * (mark - int(row["structural_stop_e8"])); room = sign * (int(row["liquidity_target_e8"]) - mark)
            row["liquidity_target_r"] = room / risk if risk > 0 and room > 0 else None
        else: row["liquidity_target_r"] = None
    else: row["liquidity_target_r"] = None
    row["geometry_available_at_decision_mark"] = bool(row["structural_stop_e8"] is not None and row["liquidity_target_e8"] is not None and row["liquidity_target_r"] is not None and row["liquidity_target_r"] >= 1.0)

    row["checkpoint_feature_available"] = not reasons; row["unavailable_reason"] = "|".join(sorted(set(reasons)))
    row["static_feature_lineage_hash"] = str(case.get("feature_lineage_hash") or "")
    row["feature_lineage_hash"] = canonical_hash([
        row["row_id"], str(case.get("decision_facts_hash")), row["static_feature_lineage_hash"],
        fundamental.get("record_hash") if fundamental else None, cot.get("record_hash") if cot else None,
        h1_state, h4_state, setup_close, row["target_swing_id"], target_hash, definition_hash,
    ])
    for name in NUMERIC_PREDICTORS:
        if name not in row: row[name] = None
    return row


def materialize_side(
    implementation: str, destination: Path, registry: Sequence[Mapping[str, Any]], cases: Mapping[str, Mapping[str, Any]],
    frames: Mapping[str, Frame], derived: Mapping[str, FrameDerived], fundamentals: MacroRows, positioning: MacroRows,
    timelines: Mapping[str, tuple[Sequence[int], list[str]]], targets: Mapping[tuple[str, str], IntervalPriceIndex],
    fractals: Mapping[str, Fractals], daily: DailyState, weekly: DailyState,
) -> dict[str, Any]:
    output_schema = schema(); temporary = destination.with_suffix(destination.suffix + ".tmp")
    if destination.exists() or temporary.exists(): raise FileExistsError(destination if destination.exists() else temporary)
    checksums = Checksums(output_schema); batch: list[dict[str, Any]] = []; reasons = Counter(); categories = {name: Counter() for name in CATEGORICAL_PREDICTORS}; geometry = Counter(); training_rows = 0
    writer = pq.ParquetWriter(temporary, output_schema, compression="zstd", use_dictionary=False, write_statistics=True, version="2.6", data_page_version="1.0")
    definition_hash = sha256_file(DEFINITIONS)
    try:
        for registry_row in registry:
            if registry_row["tape_status"] != "AVAILABLE": continue
            case = cases[str(registry_row["pullback_id"])]; frame = frames[SIGNAL_FRAME[str(case["timeframe"])]]
            known = parse_ns(str(case["known_at_utc"])); deadline = parse_ns(str(case["deadline_at_utc"]))
            left = int(np.searchsorted(frame.close_ns, known, side="left")) if implementation == "primary" else bisect.bisect_left(frame.close_ns, known)
            right = int(np.searchsorted(frame.close_ns, deadline, side="left")) if implementation == "primary" else bisect.bisect_left(frame.close_ns, deadline)
            expected_count = int(registry_row["checkpoint_rows"])
            indexes = exact_checkpoint_indexes(case, frame, frames["M1"], implementation)
            if len(indexes) != expected_count or canonical_hash([int(frame.close_ns[index]) for index in indexes]) != str(registry_row["checkpoint_timestamp_hash"]):
                raise ValueError(f"Checkpoint identity changed: {case['pullback_id']}")
            sampled_indexes = checkpoint_sample_indexes(len(indexes))
            if not indexes: raise ValueError(f"No actionable checkpoint: {case['pullback_id']}")
            signal_index = int(np.searchsorted(frame.close_ns, known, side="left")) if implementation == "primary" else bisect.bisect_left(frame.close_ns, known)
            setup_close = int(frame.close_e8[signal_index]) if signal_index < len(frame.close_ns) and int(frame.close_ns[signal_index]) == known else None
            if implementation == "primary":
                all_highs = np.maximum.accumulate(frame.high_e8[left:right]); all_lows = np.minimum.accumulate(frame.low_e8[left:right])
                running_highs = np.asarray([all_highs[index - left] for index in indexes], dtype=np.int64)
                running_lows = np.asarray([all_lows[index - left] for index in indexes], dtype=np.int64)
            else:
                high_running = -2**63; low_running = 2**63 - 1; high_values: list[int] = []; low_values: list[int] = []
                wanted = set(indexes)
                for frame_index in range(left, right):
                    high_running = max(high_running, int(frame.high_e8[frame_index])); low_running = min(low_running, int(frame.low_e8[frame_index]))
                    if frame_index in wanted: high_values.append(high_running); low_values.append(low_running)
                running_highs = np.asarray(high_values, dtype=np.int64); running_lows = np.asarray(low_values, dtype=np.int64)
            for checkpoint_number, frame_index in enumerate(indexes):
                row = checkpoint_row(
                    case, frame, frame_index, checkpoint_number, checkpoint_number in sampled_indexes,
                    setup_close, int(running_highs[checkpoint_number]), int(running_lows[checkpoint_number]),
                    frames, derived, fundamentals, positioning, timelines, targets, fractals, daily, weekly, definition_hash, implementation,
                )
                reasons[row["unavailable_reason"] or "AVAILABLE"] += 1; geometry[str(bool(row["geometry_available_at_decision_mark"]))] += 1; training_rows += int(row["training_checkpoint"])
                for name in CATEGORICAL_PREDICTORS: categories[name][str(row[name])] += 1
                batch.append(row)
                if len(batch) >= 8192:
                    table = pa.Table.from_pylist(batch, schema=output_schema); checksums.update(table); writer.write_table(table, row_group_size=8192); batch.clear()
        if batch:
            table = pa.Table.from_pylist(batch, schema=output_schema); checksums.update(table); writer.write_table(table, row_group_size=8192); batch.clear()
    except Exception:
        writer.close(); temporary.unlink(missing_ok=True); raise
    writer.close(); temporary.replace(destination)
    result = checksums.result()
    if result["rows"] != 2_095_849: raise ValueError(f"Tape row count changed: {result['rows']}")
    result.update({
        "implementation": implementation, "output": file_record(destination), "training_checkpoint_rows": training_rows,
        "unavailable_reasons": dict(sorted(reasons.items())), "geometry_available": dict(sorted(geometry.items())),
        "categorical_vocabularies": {name: sorted(values) for name, values in categories.items()},
    })
    return result


def main() -> None:
    readiness = preflight(); proof = synthetic_proof(); implementation_freeze = write_or_verify_implementation_freeze(readiness, proof)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    frames, price_diagnostics = load_price()
    derived = {name: precompute_frame_derived(frames[name]) for name in ("M1", "M5", "M15")}
    registry, cases, static_diagnostics = static_rows()
    primary_parity = verify_checkpoint_parity(registry, cases, frames, "primary")
    reference_parity = verify_checkpoint_parity(registry, cases, frames, "reference")
    if primary_parity != {**reference_parity, "implementation": "primary"}:
        raise ValueError("Primary/reference amended checkpoint parity differs")
    fundamentals = load_macro(FUNDAMENTALS, "FUNDAMENTAL_SNAPSHOT"); positioning = load_macro(POSITIONING, "POSITIONING")
    timelines, targets, structure_diagnostics = structure_sources()
    fractals = {name: derive_fractals(frame.close_ns, frame.high_e8, frame.low_e8) for name, frame in frames.items()}
    daily, weekly = build_daily_weekly(frames["M15"])

    primary = materialize_side("primary", PRIMARY_OUTPUT, registry, cases, frames, derived, fundamentals, positioning, timelines, targets, fractals, daily, weekly)
    reference = materialize_side("reference", REFERENCE_OUTPUT, registry, cases, frames, derived, fundamentals, positioning, timelines, targets, fractals, daily, weekly)
    comparison_fields = ("rows", "per_column", "complete", "null_counts", "training_checkpoint_rows", "unavailable_reasons", "geometry_available", "categorical_vocabularies")
    differences = [name for name in comparison_fields if primary[name] != reference[name]]
    byte_identical = sha256_file(PRIMARY_OUTPUT) == sha256_file(REFERENCE_OUTPUT)
    status = "PASS_OUTCOME_BLIND_DECISION_TAPE_MATERIALIZATION" if not differences and byte_identical else "FAIL_DECISION_TAPE_REPRODUCTION"
    certification = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_TAPE_CERTIFICATION_1_0", "status": status, "certified_at_utc": utc_now(),
        "checkpoint_rows": primary["rows"], "available_cases": 8650, "population": 8653, "differences": differences,
        "byte_identical": byte_identical, "primary": primary, "reference": reference,
        "amendment_c_checkpoint_and_baseline_parity": {"primary": primary_parity, "reference": reference_parity},
        "price_diagnostics": price_diagnostics, "static_diagnostics": static_diagnostics, "structure_diagnostics": structure_diagnostics,
        "fundamental_rows": len(fundamentals.rows), "positioning_rows": len(positioning.rows), "daily_states": len(daily.completed_ns), "weekly_states": len(weekly.completed_ns),
        "implementation_freeze": file_record(IMPLEMENTATION_FREEZE), "development_outcomes_accessed": False,
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(CERTIFICATION, certification)
    final = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_TAPE_FREEZE_1_0", "status": status, "sealed_at_utc": utc_now(),
        "controls": {"contract": file_record(CONTRACT), "protocol": file_record(PROTOCOL), "definitions": file_record(DEFINITIONS), "readiness": file_record(READINESS_FREEZE), "original_implementation": file_record(ORIGINAL_IMPLEMENTATION_FREEZE), "amendment_a": file_record(AMENDMENT_A), "implementation_a1": file_record(AMENDMENT_A_IMPLEMENTATION_FREEZE), "amendment_b": file_record(AMENDMENT_B), "implementation_b1": file_record(AMENDMENT_B_IMPLEMENTATION_FREEZE), "baseline_audit": file_record(BASELINE_AUDIT_SEAL), "amendment_c": file_record(AMENDMENT_C), "implementation_c1": file_record(IMPLEMENTATION_FREEZE)},
        "artifacts": {"primary": file_record(PRIMARY_OUTPUT), "reference": file_record(REFERENCE_OUTPUT), "certification": file_record(CERTIFICATION)},
        "checkpoint_rows": primary["rows"], "complete_row_checksum": primary["complete"], "byte_identical": byte_identical,
        "development_outcomes_accessed": False, "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FINAL_FREEZE, final)
    print(json.dumps({"status": status, "rows": primary["rows"], "training_rows": primary["training_checkpoint_rows"], "geometry": primary["geometry_available"], "unavailable": primary["unavailable_reasons"], "byte_identical": byte_identical, "differences": differences}, sort_keys=True))
    if status != "PASS_OUTCOME_BLIND_DECISION_TAPE_MATERIALIZATION": raise SystemExit(2)


if __name__ == "__main__":
    main()
