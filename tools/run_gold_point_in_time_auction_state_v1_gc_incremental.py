from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import sparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_gold_point_in_time_auction_state_v1_development as core  # noqa: E402


OUTPUT = core.ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental"
FREEZE = core.MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_protocol_freeze.json"
FINAL = core.MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_final_freeze.json"
BASE_RESULT = core.OUTPUT / "development_results.json"
BASE_MODELS = core.OUTPUT / "primary_fold_models.json"
BASE_PREDICTIONS = core.OUTPUT / "primary_oof_predictions.parquet"
GC_DIR = core.ARTIFACTS / "gc_session_trigger_edge_v2r1_v01"
GC_MANIFEST = GC_DIR / "manifest.json"
GC_SOURCES = {
    "LONDON": GC_DIR / "primary_london_one_second_features.parquet",
    "NEW_YORK": GC_DIR / "primary_new_york_one_second_features.parquet",
}

GC_FIELDS = (
    "gc_aggression_aligned_w60",
    "gc_quote_ofi_aligned_w60",
    "gc_depth_imbalance_aligned_w60",
    "gc_microprice_pressure_aligned_t0",
    "gc_absorption_aligned_w60",
    "gc_liquidity_fragility_60_900",
)
GC_REQUIRED_COLUMNS = (
    "bucket_end_ns",
    "market_state",
    "state_available",
    "book_two_sided",
    "book_locked",
    "book_crossed",
    "trade_qty_buy",
    "trade_qty_sell",
    "quote_ofi_raw",
    "quote_ofi_transition_count",
    "depth_imbalance_l5_ppb",
    "microprice_fixed_1e9",
    "midpoint_fixed_1e9",
    "spread_fixed_1e9",
)
W60 = 60
W900 = 900
MIN_W60_VALID = 57
MIN_W900_VALID = 855
GC_TICK_FIXED_1E9 = 100_000_000
COMPARATORS = ("BASE_MATCHED_RECALIBRATED", "BASE_PLUS_GC")
INCREMENTAL_BOOTSTRAPS = 5_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def rounded(value: float | None, digits: int = 12) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    result = round(float(value), digits)
    return 0.0 if result == 0 else result


def verify_predecessors() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base = json.loads(BASE_RESULT.read_text(encoding="utf-8"))
    protocol = json.loads(core.PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(GC_MANIFEST.read_text(encoding="utf-8"))
    if base.get("development_verdict") != "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE":
        raise ValueError("Unexpected base development disposition")
    if base.get("passing_candidates") or base.get("forward_disposition") != "KEEP_2025_2026_LOCKED":
        raise ValueError("Base candidate or forward lock changed")
    if not all(base.get("reproduction", {}).values()):
        raise ValueError("Base independent reproduction did not pass")
    if manifest.get("status") != "PASS_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION":
        raise ValueError("GC technical predecessor did not pass")
    expected = {Path(str(item["path"])).name: item for item in manifest["artifacts"]}
    for path in GC_SOURCES.values():
        record = expected.get(path.name)
        if record is None or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise ValueError(f"GC source seal failed: {path.name}")
    for path in (BASE_RESULT, BASE_MODELS, BASE_PREDICTIONS, core.FEATURES, core.OUTCOMES, core.CONTRACT, core.PROTOCOL):
        if not path.is_file():
            raise FileNotFoundError(path)
    if any(path.exists() for path in (OUTPUT, FREEZE, FINAL)):
        raise FileExistsError("GC incremental output or freeze already exists")
    return base, protocol, manifest


def freeze_payload(base: Mapping[str, Any], protocol: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": "GOLD_PIT_AUCTION_STATE_V1_GC_INCREMENTAL_PROTOCOL_1_0",
        "status": "FROZEN_BEFORE_GC_BOOK_VALUES_ARE_JOINED_TO_OPEN_DEVELOPMENT_OUTCOMES",
        "sealed_at_utc": core.utc_now(),
        "predecessors": {
            "contract": file_record(core.CONTRACT),
            "base_result": file_record(BASE_RESULT),
            "base_models": file_record(BASE_MODELS),
            "base_predictions": file_record(BASE_PREDICTIONS),
            "decision_tape": file_record(core.FEATURES),
            "development_outcomes": file_record(core.OUTCOMES),
            "gc_manifest": file_record(GC_MANIFEST),
            "gc_source_certification_status": manifest["status"],
            "base_development_verdict": base["development_verdict"],
        },
        "population": {
            "sources": {session: file_record(path) for session, path in GC_SOURCES.items()},
            "eligible_sessions": ["LONDON", "NEW_YORK"],
            "covered_date_design": "EXISTING_OUTCOME_BLIND_SECOND_COMPLETE_CME_TRADING_WEEK_MONTHLY_SAMPLE;GOOD_FRIDAY_UNAVAILABLE_RETAINED",
            "matched_comparison": "BOTH_COMPARATORS_USE_IDENTICAL_EXACT_TIMESTAMP_ROWS_CASES_FOLDS_AND_OUTCOME_DEFINITIONS",
            "standalone_candidate_or_validation_credit": False,
        },
        "features": {
            "window_interval": "LAST_N_ONE_SECOND_BUCKETS_ENDING_EXACTLY_AT_CHECKPOINT;RIGHT_CLOSED_BY_BUCKET_IDENTITY",
            "technical_valid_state": "CONTINUOUS_MATCHING_AND_STATE_AVAILABLE_AND_TWO_SIDED_AND_NOT_LOCKED_AND_NOT_CROSSED",
            "minimum_valid_states": {"W60": MIN_W60_VALID, "W900": MIN_W900_VALID},
            "aggression": "DIRECTION_SIGN_TIMES_SUM_BUY_MINUS_SUM_SELL_DIVIDED_BY_SUM_BUY_PLUS_SUM_SELL_OVER_W60;UNKNOWN_IF_ZERO",
            "quote_ofi": "DIRECTION_SIGN_TIMES_SUM_VALID_QUOTE_OFI_RAW_DIVIDED_BY_SUM_VALID_TRANSITIONS_OVER_W60",
            "depth_imbalance": "DIRECTION_SIGN_TIMES_MEDIAN_VALID_L5_DEPTH_IMBALANCE_PPB_OVER_W60_DIVIDED_BY_1E9",
            "microprice_pressure": "DIRECTION_SIGN_TIMES_TERMINAL_MICROPRICE_MINUS_MIDPOINT_DIVIDED_BY_SPREAD",
            "absorption": "PLUS_ONE_IF_FROZEN_ABSORPTION_STATE_SUPPORTS_SETUP_DIRECTION;MINUS_ONE_IF_OPPOSES;ZERO_IF_NONE;UNKNOWN_IF_REQUIRED_FLOW_OR_VALID_BOOK_STATE_MISSING",
            "liquidity_fragility": "LOG_OF_MEDIAN_VALID_W60_SPREAD_PLUS_ONE_TICK_DIVIDED_BY_MEDIAN_VALID_W900_SPREAD_PLUS_ONE_TICK",
            "absorption_state": "BEARISH_IF_BUY_GT_SELL_AND_MIDPOINT_PROGRESS_LE_ZERO_AND_OFI_OR_DEPTH_LT_ZERO;BULLISH_SYMMETRIC;ELSE_NONE",
            "alignment": "SIGNED_FIELDS_ARE_MULTIPLIED_BY_THE_ORIGINAL_SETUP_DIRECTION_AVAILABLE_AT_THE_CHECKPOINT",
            "numeric_rounding": "IEEE_FLOAT64_THEN_CANONICAL_ROUND_TO_12_DECIMALS",
            "missing": "TRAINING_MEDIAN_PLUS_MISSING_INDICATOR;NO_ROW_DROPPED_FOR_AN_INDIVIDUAL_MISSING_GC_FIELD",
            "registered_fields": list(GC_FIELDS),
        },
        "models": {
            "base_offset": "THE_SEALED_FULL-DEVELOPMENT BASE FOLD MODEL;RECONSTRUCTED_FROM_ITS SEALED COEFFICIENTS AND TRANSFORMER",
            "base_offset_reproduction_gate": "ALL EIGHT SEALED OOF PREDICTION FIELDS MUST AGREE WITHIN 1E-8;TOLERANCE ONLY COVERS 12-DECIMAL JSON COEFFICIENT SERIALIZATION",
            "base_comparator": "BASE OFFSET PLUS AN INTERCEPT-ONLY TRAINING-FOLD RECALIBRATION",
            "plus_gc_comparator": "SAME BASE OFFSET PLUS FIT-ONLY STANDARDIZED SIX GC FIELDS, SIX MISSING INDICATORS, AND INTERCEPT",
            "classification": "DETERMINISTIC WEIGHTED OFFSET MULTINOMIAL/BINARY ADAM;SAME 200 EPOCH,4096 BATCH,0P01 LEARNING-RATE AND L2 C GRID AS BASE",
            "regression": "WEIGHTED RIDGE ON RESIDUAL TRANSFORMED TARGETS;SAME ALPHA GRID AS BASE",
            "temperature_grid": list(protocol["models"]["temperature_grid"]),
            "logistic_c_grid": list(protocol["models"]["logistic_c_grid"]),
            "ridge_alpha_grid": list(protocol["models"]["ridge_alpha_grid"]),
            "folds": protocol["folds"],
            "training_and_calibration_case_support": protocol["training"],
            "policy_grid_selection_and_economics": "UNCHANGED BASE POLICY GRID, CALIBRATION SUPPORT, COSTS, OVERLAP, RISK, TARGETS, STOPS AND FIRST-PASSAGE OUTCOMES",
        },
        "incremental_disposition": {
            "family": "TWELVE PAIRED TIMEFRAME_X_MODEL_FAMILY_X_TRACK COMPARISONS",
            "support": "BOTH COMPARATORS MEET ORIGINAL TIMEFRAME TRADE_AND_DATE FLOORS AND AT_LEAST_THREE EVALUABLE OUTER_FOLDS",
            "required_joint_improvements": [
                "PLUS_GC_BRIER_LT_BASE_BRIER",
                "PLUS_GC_EXPECTANCY_R_GT_BASE",
                "PLUS_GC_PROFIT_FACTOR_GT_BASE",
                "PLUS_GC_NET_PNL_GT_BASE",
                "PAIRED_DATE_DELTA_CLUSTER_BOOTSTRAP_CI95_LOW_GT_ZERO",
                "HOLM_ADJUSTED_ONE_SIDED_P_LTE_0P10_ACROSS_ALL_12_COMPARISONS",
                "PLUS_GC_1P5X_COST_EXPECTANCY_GT_ZERO_AND_GT_BASE",
                "AT_LEAST_THREE_POSITIVE_FOLD_PNL_DELTAS",
                "AT_LEAST_TWO_POSITIVE_CALENDAR_YEAR_PNL_DELTAS",
            ],
            "bootstrap": {"resamples": INCREMENTAL_BOOTSTRAPS, "cluster": "COVERED_TRADING_DATE", "seed": core.BASE_SEED},
            "possible_verdicts": ["ADDS_INCREMENTAL_VALUE", "NO_PROVEN_INCREMENTAL_VALUE", "SUPPORT_FAIL"],
            "standalone_candidate_credit": False,
        },
        "forward": {
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "opening_forbidden_because_base_has_zero_development_passes": True,
        },
        "paid_acquisition_usd": 0.0,
        "implementation": file_record(Path(__file__).resolve()),
    }


def canon_float(value: float | None) -> float | None:
    return rounded(value, 12)


def numpy_valid(arrays: Mapping[str, np.ndarray], start: int, end: int) -> np.ndarray:
    return (
        (arrays["market_state"][start:end] == "CONTINUOUS_MATCHING")
        & arrays["state_available"][start:end]
        & arrays["book_two_sided"][start:end]
        & ~arrays["book_locked"][start:end]
        & ~arrays["book_crossed"][start:end]
    )


def primary_gc_features(arrays: Mapping[str, np.ndarray], end: int, direction: int) -> tuple[list[float | None], list[str]]:
    start60, start900 = end - W60, end - W900
    valid60 = numpy_valid(arrays, start60, end)
    valid900 = numpy_valid(arrays, start900, end)
    values: list[float | None] = [None] * len(GC_FIELDS)
    reasons = ["AVAILABLE"] * len(GC_FIELDS)

    buy = int(np.asarray(arrays["trade_qty_buy"][start60:end], dtype=np.int64).sum())
    sell = int(np.asarray(arrays["trade_qty_sell"][start60:end], dtype=np.int64).sum())
    if buy + sell:
        values[0] = canon_float(direction * (buy - sell) / (buy + sell))
    else:
        reasons[0] = "UNKNOWN_ZERO_TRADE_DENOMINATOR"

    if int(valid60.sum()) >= MIN_W60_VALID:
        transitions = int(np.asarray(arrays["quote_ofi_transition_count"][start60:end][valid60], dtype=np.int64).sum())
        if transitions > 0:
            raw = int(np.asarray(arrays["quote_ofi_raw"][start60:end][valid60], dtype=np.int64).sum())
            values[1] = canon_float(direction * raw / transitions)
        else:
            reasons[1] = "UNKNOWN_ZERO_OFI_TRANSITIONS"
        depth = np.asarray(arrays["depth_imbalance_l5_ppb"][start60:end], dtype=np.float64)
        depth_mask = valid60 & np.isfinite(depth)
        if int(depth_mask.sum()) >= MIN_W60_VALID:
            values[2] = canon_float(direction * float(np.median(depth[depth_mask])) / 1_000_000_000)
        else:
            reasons[2] = "UNAVAILABLE_W60_VALID_DEPTH"
    else:
        reasons[1] = "UNAVAILABLE_W60_VALID_STATE"
        reasons[2] = "UNAVAILABLE_W60_VALID_STATE"

    terminal = end - 1
    terminal_valid = bool(numpy_valid(arrays, terminal, end)[0])
    micro = float(arrays["microprice_fixed_1e9"][terminal])
    midpoint = float(arrays["midpoint_fixed_1e9"][terminal])
    spread = float(arrays["spread_fixed_1e9"][terminal])
    if terminal_valid and all(math.isfinite(value) for value in (micro, midpoint, spread)) and spread > 0:
        values[3] = canon_float(direction * (micro - midpoint) / spread)
    else:
        reasons[3] = "UNAVAILABLE_TERMINAL_BOOK_STATE_OR_SPREAD"

    midpoint_window = np.asarray(arrays["midpoint_fixed_1e9"][start60:end], dtype=np.float64)
    valid_midpoint = valid60 & np.isfinite(midpoint_window)
    if buy + sell > 0 and terminal_valid and np.any(valid_midpoint):
        earliest = float(midpoint_window[np.flatnonzero(valid_midpoint)[0]])
        progress = midpoint - earliest
        transitions = int(np.asarray(arrays["quote_ofi_transition_count"][start60:end][valid60], dtype=np.int64).sum())
        ofi = int(np.asarray(arrays["quote_ofi_raw"][start60:end][valid60], dtype=np.int64).sum()) if transitions else None
        depth = np.asarray(arrays["depth_imbalance_l5_ppb"][start60:end], dtype=np.float64)
        depth_mask = valid60 & np.isfinite(depth)
        depth_value = float(np.median(depth[depth_mask])) if np.any(depth_mask) else None
        bearish = buy > sell and progress <= 0 and ((ofi is not None and ofi < 0) or (depth_value is not None and depth_value < 0))
        bullish = sell > buy and progress >= 0 and ((ofi is not None and ofi > 0) or (depth_value is not None and depth_value > 0))
        absorption_direction = -1 if bearish else 1 if bullish else 0
        values[4] = float(direction * absorption_direction)
    else:
        reasons[4] = "UNAVAILABLE_ABSORPTION_INPUT"

    spread60 = np.asarray(arrays["spread_fixed_1e9"][start60:end], dtype=np.float64)
    spread900 = np.asarray(arrays["spread_fixed_1e9"][start900:end], dtype=np.float64)
    mask60 = valid60 & np.isfinite(spread60) & (spread60 > 0)
    mask900 = valid900 & np.isfinite(spread900) & (spread900 > 0)
    if int(mask60.sum()) >= MIN_W60_VALID and int(mask900.sum()) >= MIN_W900_VALID:
        med60 = float(np.median(spread60[mask60])); med900 = float(np.median(spread900[mask900]))
        values[5] = canon_float(math.log((med60 + GC_TICK_FIXED_1E9) / (med900 + GC_TICK_FIXED_1E9)))
    else:
        reasons[5] = "UNAVAILABLE_W60_OR_W900_VALID_SPREAD"
    return values, reasons


def reference_valid(values: Mapping[str, Sequence[Any]], index: int) -> bool:
    return bool(
        values["market_state"][index] == "CONTINUOUS_MATCHING"
        and values["state_available"][index]
        and values["book_two_sided"][index]
        and not values["book_locked"][index]
        and not values["book_crossed"][index]
    )


def reference_median(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) & 1 else (ordered[middle - 1] + ordered[middle]) / 2.0


def reference_gc_features(values: Mapping[str, Sequence[Any]], end: int, direction: int) -> tuple[list[float | None], list[str]]:
    indexes60 = list(range(end - W60, end)); indexes900 = list(range(end - W900, end))
    valid60 = [index for index in indexes60 if reference_valid(values, index)]
    valid900 = [index for index in indexes900 if reference_valid(values, index)]
    output: list[float | None] = [None] * len(GC_FIELDS); reasons = ["AVAILABLE"] * len(GC_FIELDS)
    buy = sum(int(values["trade_qty_buy"][index]) for index in indexes60)
    sell = sum(int(values["trade_qty_sell"][index]) for index in indexes60)
    if buy + sell:
        output[0] = canon_float(direction * (buy - sell) / (buy + sell))
    else:
        reasons[0] = "UNKNOWN_ZERO_TRADE_DENOMINATOR"
    if len(valid60) >= MIN_W60_VALID:
        transitions = sum(int(values["quote_ofi_transition_count"][index]) for index in valid60)
        if transitions:
            raw = sum(int(values["quote_ofi_raw"][index]) for index in valid60)
            output[1] = canon_float(direction * raw / transitions)
        else:
            reasons[1] = "UNKNOWN_ZERO_OFI_TRANSITIONS"
        depth = [float(values["depth_imbalance_l5_ppb"][index]) for index in valid60 if values["depth_imbalance_l5_ppb"][index] is not None]
        if len(depth) >= MIN_W60_VALID:
            output[2] = canon_float(direction * reference_median(depth) / 1_000_000_000)
        else:
            reasons[2] = "UNAVAILABLE_W60_VALID_DEPTH"
    else:
        reasons[1] = "UNAVAILABLE_W60_VALID_STATE"; reasons[2] = "UNAVAILABLE_W60_VALID_STATE"
    terminal = end - 1
    raw_terminal = (values["microprice_fixed_1e9"][terminal], values["midpoint_fixed_1e9"][terminal], values["spread_fixed_1e9"][terminal])
    terminal_valid = reference_valid(values, terminal)
    if terminal_valid and all(item is not None for item in raw_terminal) and float(raw_terminal[2]) > 0:
        micro, midpoint, spread = (float(item) for item in raw_terminal)
        output[3] = canon_float(direction * (micro - midpoint) / spread)
    else:
        reasons[3] = "UNAVAILABLE_TERMINAL_BOOK_STATE_OR_SPREAD"
        midpoint = float(raw_terminal[1]) if raw_terminal[1] is not None else math.nan
    midpoints = [float(values["midpoint_fixed_1e9"][index]) for index in valid60 if values["midpoint_fixed_1e9"][index] is not None]
    if buy + sell > 0 and terminal_valid and midpoints and math.isfinite(midpoint):
        progress = midpoint - midpoints[0]
        transitions = sum(int(values["quote_ofi_transition_count"][index]) for index in valid60)
        ofi = sum(int(values["quote_ofi_raw"][index]) for index in valid60) if transitions else None
        depth = [float(values["depth_imbalance_l5_ppb"][index]) for index in valid60 if values["depth_imbalance_l5_ppb"][index] is not None]
        depth_value = reference_median(depth) if depth else None
        bearish = buy > sell and progress <= 0 and ((ofi is not None and ofi < 0) or (depth_value is not None and depth_value < 0))
        bullish = sell > buy and progress >= 0 and ((ofi is not None and ofi > 0) or (depth_value is not None and depth_value > 0))
        output[4] = float(direction * (-1 if bearish else 1 if bullish else 0))
    else:
        reasons[4] = "UNAVAILABLE_ABSORPTION_INPUT"
    spreads60 = [float(values["spread_fixed_1e9"][index]) for index in valid60 if values["spread_fixed_1e9"][index] is not None and float(values["spread_fixed_1e9"][index]) > 0]
    spreads900 = [float(values["spread_fixed_1e9"][index]) for index in valid900 if values["spread_fixed_1e9"][index] is not None and float(values["spread_fixed_1e9"][index]) > 0]
    if len(spreads60) >= MIN_W60_VALID and len(spreads900) >= MIN_W900_VALID:
        output[5] = canon_float(math.log((reference_median(spreads60) + GC_TICK_FIXED_1E9) / (reference_median(spreads900) + GC_TICK_FIXED_1E9)))
    else:
        reasons[5] = "UNAVAILABLE_W60_OR_W900_VALID_SPREAD"
    return output, reasons


def source_arrays(table: pa.Table) -> dict[str, np.ndarray]:
    output: dict[str, np.ndarray] = {}
    for name in GC_REQUIRED_COLUMNS:
        values = table[name].combine_chunks().to_pylist()
        if name in {"market_state"}:
            output[name] = np.asarray(values, dtype=object)
        elif name in {"state_available", "book_two_sided", "book_locked", "book_crossed"}:
            output[name] = np.asarray(values, dtype=bool)
        elif name in {"depth_imbalance_l5_ppb", "microprice_fixed_1e9", "midpoint_fixed_1e9", "spread_fixed_1e9"}:
            output[name] = np.asarray([math.nan if value is None else value for value in values], dtype=np.float64)
        else:
            output[name] = np.asarray(values, dtype=np.int64)
    return output


def source_lists(table: pa.Table) -> dict[str, list[Any]]:
    return {name: table[name].combine_chunks().to_pylist() for name in GC_REQUIRED_COLUMNS}


def feature_schema() -> pa.Schema:
    fields = [
        pa.field("row_id", pa.string(), False), pa.field("timeframe", pa.string(), False),
        pa.field("checkpoint_ns", pa.int64(), False), pa.field("gc_session", pa.string(), False),
        pa.field("direction_sign", pa.int8(), False), pa.field("source_sha256", pa.string(), False),
    ]
    fields.extend(pa.field(name, pa.float64()) for name in GC_FIELDS)
    fields.extend(pa.field(f"{name}__availability", pa.string(), False) for name in GC_FIELDS)
    return pa.schema(fields)


def materialize_features(label: str, implementation: str) -> tuple[Path, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    diagnostics = Counter()
    for timeframe in core.TIMEFRAMES:
        table = pq.read_table(
            core.FEATURES,
            columns=["row_id", "checkpoint_at_utc", "direction", "session_state"],
            filters=[("timeframe", "=", timeframe)],
        ).combine_chunks()
        timestamps = np.asarray([core.parse_ns(value) for value in table["checkpoint_at_utc"].to_pylist()], dtype=np.int64)
        row_ids = table["row_id"].to_pylist(); directions = table["direction"].to_pylist(); sessions = table["session_state"].to_pylist()
        for session, source in GC_SOURCES.items():
            eligible = np.flatnonzero(np.asarray([value == session for value in sessions], dtype=bool))
            if not len(eligible):
                continue
            ordered = eligible[np.argsort(timestamps[eligible], kind="mergesort")]
            ordered_times = timestamps[ordered]
            parquet = pq.ParquetFile(source); source_sha = sha256_file(source)
            for group in range(parquet.metadata.num_row_groups):
                source_table = parquet.read_row_group(group, columns=list(GC_REQUIRED_COLUMNS)).combine_chunks()
                bucket = np.asarray(source_table["bucket_end_ns"].to_numpy(), dtype=np.int64)
                left = int(np.searchsorted(ordered_times, bucket[W900 - 1], side="left"))
                right = int(np.searchsorted(ordered_times, bucket[-1], side="right"))
                if right <= left:
                    continue
                candidates = ordered[left:right]
                prepared = source_arrays(source_table) if implementation == "PRIMARY_NUMPY" else source_lists(source_table)
                feature_cache: dict[tuple[int, int], tuple[list[float | None], list[str]]] = {}
                for index in candidates:
                    checkpoint = int(timestamps[index]); position = int(np.searchsorted(bucket, checkpoint, side="left"))
                    if position >= len(bucket) or int(bucket[position]) != checkpoint:
                        diagnostics["NONEXACT_TIMESTAMP"] += 1
                        continue
                    end = position + 1
                    if end < W900:
                        diagnostics["INSUFFICIENT_SOURCE_WARMUP"] += 1
                        continue
                    direction = 1 if directions[index] == "UP" else -1
                    cache_key = (checkpoint, direction)
                    if cache_key not in feature_cache:
                        if implementation == "PRIMARY_NUMPY":
                            feature_cache[cache_key] = primary_gc_features(prepared, end, direction)
                        else:
                            feature_cache[cache_key] = reference_gc_features(prepared, end, direction)
                    values, reasons = feature_cache[cache_key]
                    row = {
                        "row_id": str(row_ids[index]), "timeframe": timeframe, "checkpoint_ns": checkpoint,
                        "gc_session": session, "direction_sign": direction, "source_sha256": source_sha,
                    }
                    for name, value, reason in zip(GC_FIELDS, values, reasons, strict=True):
                        row[name] = value; row[f"{name}__availability"] = reason; diagnostics[f"{name}::{reason}"] += 1
                    rows.append(row); diagnostics[f"COVERED::{timeframe}::{session}"] += 1
    rows.sort(key=lambda row: (core.TIMEFRAMES.index(row["timeframe"]), int(row["checkpoint_ns"]), str(row["row_id"])))
    if len({row["row_id"] for row in rows}) != len(rows):
        raise ValueError("GC feature row identity is not unique")
    path = OUTPUT / f"{label}_gc_checkpoint_features.parquet"
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=feature_schema()), temporary, compression="zstd", use_dictionary=False, write_statistics=True, version="2.6", data_page_version="1.0", row_group_size=16_384)
    temporary.replace(path)
    return path, {"rows": len(rows), "row_identity_hash": canonical_hash([row["row_id"] for row in rows]), "diagnostics": dict(sorted(diagnostics.items()))}


def reconstruct_bundle(record: Mapping[str, Any]) -> core.ModelBundle:
    transformer_record = record["transformer"]
    transformer = core.Transformer(
        family=str(record["family"]),
        clip_low=np.asarray(transformer_record["clip_low"], dtype=np.float64),
        clip_high=np.asarray(transformer_record["clip_high"], dtype=np.float64),
        median=np.asarray(transformer_record["median"], dtype=np.float64),
        mean=np.asarray(transformer_record["mean"], dtype=np.float64),
        std=np.asarray(transformer_record["std"], dtype=np.float64),
        quintiles=np.asarray(transformer_record["quintiles"], dtype=np.float64),
        categorical_sizes=[int(value) for value in transformer_record["categorical_sizes"]],
        feature_names=list(transformer_record["feature_names"]),
    )
    selection = record["selection"]
    return core.ModelBundle(
        transformer=transformer,
        response=core.Classifier(np.asarray(record["coefficients"]["response"], dtype=np.float64), 3),
        two_r=core.Classifier(np.asarray(record["coefficients"]["two_r"], dtype=np.float64).reshape(-1, 1), 2),
        temperature=float(selection["temperature"]),
        ridge=np.asarray(record["coefficients"]["ridge"], dtype=np.float64),
        c_value=float(selection["c"]), alpha=float(selection["alpha"]),
        training_base_rate=float(record["training_base_rate"]), selection=dict(selection),
    )


def base_offsets(bundle: core.ModelBundle, data: core.DataSet, indices: np.ndarray) -> dict[str, np.ndarray]:
    prediction = bundle.predict(data.numeric[indices], data.categorical[indices])
    eps = 1e-12
    response = np.column_stack((prediction["p_cont"], prediction["p_fail"], prediction["p_unresolved"]))
    response_logits = np.log(np.clip(response, eps, 1.0))
    p_two = np.clip(prediction["p_two"], eps, 1 - eps)
    two_logits = np.log(p_two / (1 - p_two))[:, None]
    regression = np.column_stack((
        np.log1p(np.maximum(0.0, prediction["expected_mfe"])),
        np.log1p(np.maximum(0.0, prediction["expected_mae"])),
        np.log1p(np.maximum(0.0, prediction["expected_time"])),
        prediction["expected_net"],
    ))
    return {"response": response_logits, "two": two_logits, "regression": regression}


class GCTransformer:
    def __init__(self, median: np.ndarray, low: np.ndarray, high: np.ndarray, mean: np.ndarray, std: np.ndarray) -> None:
        self.median = median; self.low = low; self.high = high; self.mean = mean; self.std = std

    @classmethod
    def fit(cls, values: np.ndarray, weights: np.ndarray) -> "GCTransformer":
        low = np.nanquantile(values, 0.01, axis=0); high = np.nanquantile(values, 0.99, axis=0); median = np.nanmedian(values, axis=0)
        low = np.where(np.isfinite(low), low, 0.0); high = np.where(np.isfinite(high), high, low); median = np.where(np.isfinite(median), median, 0.0)
        filled = np.clip(np.where(np.isfinite(values), values, median), low, high)
        total = weights.sum(); mean = (filled * weights[:, None]).sum(axis=0) / total
        variance = ((filled - mean) ** 2 * weights[:, None]).sum(axis=0) / total
        std = np.sqrt(np.maximum(variance, 0.0)); std = np.where(std > 1e-12, std, 1.0)
        return cls(median, low, high, mean, std)

    def transform(self, values: np.ndarray, plus_gc: bool) -> sparse.csr_matrix:
        n = len(values)
        if not plus_gc:
            return sparse.csr_matrix(np.ones((n, 1), dtype=np.float64))
        missing = ~np.isfinite(values)
        filled = np.clip(np.where(missing, self.median, values), self.low, self.high)
        standardized = (filled - self.mean) / self.std
        return sparse.csr_matrix(np.column_stack((np.ones(n), standardized, missing.astype(np.float64))))


def offset_probabilities(offset: np.ndarray, matrix: sparse.csr_matrix, coefficient: np.ndarray, temperature: float) -> np.ndarray:
    logits = offset + np.asarray(matrix @ coefficient)
    return core.probabilities(logits, temperature)


def offset_objective(matrix: sparse.csr_matrix, offset: np.ndarray, labels: np.ndarray, weights: np.ndarray, coefficient: np.ndarray, classes: int, c_value: float) -> float:
    probability = offset_probabilities(offset, matrix, coefficient, 1.0)
    if classes == 2:
        p = np.clip(probability.reshape(-1), 1e-12, 1 - 1e-12)
        loss = -(weights * (labels * np.log(p) + (1 - labels) * np.log(1 - p))).sum() / weights.sum()
    else:
        p = np.clip(probability, 1e-12, 1.0)
        loss = -(weights * np.log(p[np.arange(len(labels)), labels])).sum() / weights.sum()
    penalty = np.sum(coefficient[1:] ** 2) / (2.0 * c_value * weights.sum())
    return float(loss + penalty)


def fit_offset_adam(matrix: sparse.csr_matrix, offset: np.ndarray, labels: np.ndarray, weights: np.ndarray, classes: int, c_value: float, seed: int) -> np.ndarray:
    n, p = matrix.shape; width = 1 if classes == 2 else classes
    coefficient = np.zeros((p, width), dtype=np.float64); moment = np.zeros_like(coefficient); variance = np.zeros_like(coefficient)
    best = coefficient.copy(); best_objective = math.inf; stale = 0; step = 0; rng = np.random.default_rng(seed)
    for _epoch in range(200):
        order = rng.permutation(n)
        for begin in range(0, n, 4096):
            indices = order[begin:begin + 4096]; batch = matrix[indices]; w = weights[indices]; denominator = w.sum()
            logits = offset[indices] + np.asarray(batch @ coefficient)
            if classes == 2:
                probability = core.probabilities(logits, 1.0)
                residual = ((probability.reshape(-1) - labels[indices]) * w)[:, None]
            else:
                probability = core.probabilities(logits, 1.0)
                residual = probability.copy(); residual[np.arange(len(indices)), labels[indices]] -= 1.0; residual *= w[:, None]
            gradient = np.asarray(batch.T @ residual) / denominator
            gradient[1:] += coefficient[1:] / (c_value * weights.sum())
            step += 1; moment = 0.9 * moment + 0.1 * gradient; variance = 0.999 * variance + 0.001 * gradient * gradient
            coefficient -= 0.01 * (moment / (1 - 0.9 ** step)) / (np.sqrt(variance / (1 - 0.999 ** step)) + 1e-8)
        objective = offset_objective(matrix, offset, labels, weights, coefficient, classes, c_value)
        relative = (best_objective - objective) / max(1.0, abs(best_objective)) if math.isfinite(best_objective) else math.inf
        if objective < best_objective:
            best_objective = objective; best = coefficient.copy()
        stale = stale + 1 if relative < 1e-7 else 0
        if stale >= 10:
            break
    return best


def fit_offset_ridge(matrix: sparse.csr_matrix, residual_targets: np.ndarray, weights: np.ndarray, alpha: float) -> np.ndarray:
    root = np.sqrt(weights); weighted = matrix.multiply(root[:, None])
    gram = np.asarray((weighted.T @ weighted).toarray()); rhs = np.asarray(weighted.T @ (residual_targets * root[:, None]))
    penalty = np.eye(matrix.shape[1], dtype=np.float64) * alpha; penalty[0, 0] = 0.0
    return np.linalg.solve(gram + penalty, rhs)


def fit_incremental(
    comparator: str,
    base_bundle: core.ModelBundle,
    data: core.DataSet,
    gc_values: np.ndarray,
    fit_indices: np.ndarray,
    cal_indices: np.ndarray,
    fold: int,
    family: str,
) -> dict[str, Any]:
    weights_fit = core.case_weights(data.case_code[fit_indices]); weights_cal = core.case_weights(data.case_code[cal_indices])
    transformer = GCTransformer.fit(gc_values[fit_indices], weights_fit)
    plus_gc = comparator == "BASE_PLUS_GC"
    x_fit = transformer.transform(gc_values[fit_indices], plus_gc); x_cal = transformer.transform(gc_values[cal_indices], plus_gc)
    offset_fit = base_offsets(base_bundle, data, fit_indices); offset_cal = base_offsets(base_bundle, data, cal_indices)
    y_response = np.asarray([core.CLASS_INDEX[value] for value in data.primary_class[fit_indices]], dtype=np.int8)
    y_response_cal = np.asarray([core.CLASS_INDEX[value] for value in data.primary_class[cal_indices]], dtype=np.int8)
    y_two = data.two_r[fit_indices].astype(np.int8); y_two_cal = data.two_r[cal_indices].astype(np.int8)
    c_grid = (0.1, 1.0, 10.0) if plus_gc else (1.0,)
    choices = []
    for c_value in c_grid:
        response = fit_offset_adam(x_fit, offset_fit["response"], y_response, weights_fit, 3, c_value, core.stable_seed("GC", comparator, fold, data.timeframe, family, c_value, "response"))
        two = fit_offset_adam(x_fit, offset_fit["two"], y_two, weights_fit, 2, c_value, core.stable_seed("GC", comparator, fold, data.timeframe, family, c_value, "two"))
        for temperature in (0.75, 1.0, 1.25, 1.5):
            response_p = offset_probabilities(offset_cal["response"], x_cal, response, temperature)
            two_p = offset_probabilities(offset_cal["two"], x_cal, two, temperature)
            loss = 0.5 * (core.cross_entropy_multi(y_response_cal, response_p, weights_cal) + core.cross_entropy_binary(y_two_cal, two_p, weights_cal))
            choices.append((loss, c_value, temperature, response, two))
    choices.sort(key=lambda item: (item[0], item[1], item[2])); loss, c_value, temperature, response, two = choices[0]
    targets_fit = np.column_stack((np.log1p(data.mfe[fit_indices]), np.log1p(data.mae[fit_indices]), np.log1p(data.passage_minutes[fit_indices]), data.terminal_net_r[fit_indices]))
    targets_cal = np.column_stack((np.log1p(data.mfe[cal_indices]), np.log1p(data.mae[cal_indices]), np.log1p(data.passage_minutes[cal_indices]), data.terminal_net_r[cal_indices]))
    residual_fit = targets_fit - offset_fit["regression"]
    variance = np.average((targets_fit - np.average(targets_fit, axis=0, weights=weights_fit)) ** 2, axis=0, weights=weights_fit)
    ridge_choices = []
    for alpha in ((1.0, 10.0, 100.0) if plus_gc else (1.0,)):
        ridge = fit_offset_ridge(x_fit, residual_fit, weights_fit, alpha)
        predicted = offset_cal["regression"] + np.asarray(x_cal @ ridge)
        mse = np.average((predicted - targets_cal) ** 2, axis=0, weights=weights_cal)
        score = float(np.mean(mse / np.maximum(variance, 1e-12)))
        ridge_choices.append((score, -alpha, ridge))
    ridge_choices.sort(key=lambda item: (item[0], item[1])); regression_score, negative_alpha, ridge = ridge_choices[0]
    return {
        "transformer": transformer, "plus_gc": plus_gc, "response": response, "two": two,
        "temperature": temperature, "ridge": ridge,
        "selection": {"c": c_value, "temperature": temperature, "alpha": -negative_alpha, "classification_calibration_loss": rounded(loss), "regression_calibration_nmse": rounded(regression_score)},
        "training_base_rate": float(np.average((y_response == 0).astype(float), weights=weights_fit)),
    }


def predict_incremental(model: Mapping[str, Any], base_bundle: core.ModelBundle, data: core.DataSet, gc_values: np.ndarray, indices: np.ndarray) -> dict[str, np.ndarray]:
    offsets = base_offsets(base_bundle, data, indices)
    matrix = model["transformer"].transform(gc_values[indices], bool(model["plus_gc"]))
    response = offset_probabilities(offsets["response"], matrix, model["response"], float(model["temperature"]))
    two = offset_probabilities(offsets["two"], matrix, model["two"], float(model["temperature"]))
    regression = offsets["regression"] + np.asarray(matrix @ model["ridge"])
    return {
        "p_cont": response[:, 0], "p_fail": response[:, 1], "p_unresolved": response[:, 2], "p_two": two,
        "expected_mfe": np.maximum(0.0, np.expm1(regression[:, 0])),
        "expected_mae": np.maximum(0.0, np.expm1(regression[:, 1])),
        "expected_time": np.maximum(0.0, np.expm1(regression[:, 2])),
        "expected_net": regression[:, 3],
    }


def feature_map(path: Path, timeframe: str) -> tuple[dict[str, list[float | None]], dict[str, Any]]:
    table = pq.read_table(path, filters=[("timeframe", "=", timeframe)]).combine_chunks()
    output: dict[str, list[float | None]] = {}
    for index, identity in enumerate(table["row_id"].to_pylist()):
        output[str(identity)] = [table[name][index].as_py() for name in GC_FIELDS]
    return output, {"rows": len(table), "row_identity_hash": canonical_hash(sorted(output))}


def augmented_dataset(timeframe: str, vocab: Mapping[str, Sequence[str]], path: Path) -> tuple[core.DataSet, np.ndarray, dict[str, Any]]:
    data = core.load_timeframe(timeframe, vocab)
    lookup, diagnostics = feature_map(path, timeframe)
    gc_values = np.full((data.n, len(GC_FIELDS)), np.nan, dtype=np.float64); covered = np.zeros(data.n, dtype=bool)
    for index, identity in enumerate(data.row_id):
        values = lookup.get(str(identity))
        if values is not None:
            covered[index] = True
            gc_values[index] = [math.nan if value is None else float(value) for value in values]
    data = replace(data, feature_available=data.feature_available & covered)
    diagnostics.update({
        "covered_rows": int(covered.sum()), "covered_cases": len(np.unique(data.case_code[covered])),
        "base_and_gc_feature_available_rows": int(data.feature_available.sum()),
        "gc_field_available_counts": {name: int(np.isfinite(gc_values[:, index]).sum()) for index, name in enumerate(GC_FIELDS)},
    })
    return data, gc_values, diagnostics


def model_lookup() -> dict[tuple[int, str, str], Mapping[str, Any]]:
    records = json.loads(BASE_MODELS.read_text(encoding="utf-8"))["records"]
    return {(int(row["fold"]), str(row["timeframe"]), str(row["family"])): row for row in records if row.get("status") == "FITTED"}


def verify_base_bundle_reconstruction(
    bundle: core.ModelBundle,
    data: core.DataSet,
    indices: np.ndarray,
    fold: int,
    family: str,
) -> dict[str, Any]:
    available_indices = indices[data.feature_available[indices]]
    predicted = bundle.predict(data.numeric[available_indices], data.categorical[available_indices])
    sealed = pq.read_table(
        BASE_PREDICTIONS,
        columns=["row_id", "p_cont", "p_fail", "p_unresolved", "p_two", "expected_mfe", "expected_mae", "expected_time", "expected_net"],
        filters=[("fold", "=", fold), ("timeframe", "=", data.timeframe), ("model_family", "=", family)],
    ).combine_chunks()
    lookup = {str(identity): index for index, identity in enumerate(sealed["row_id"].to_pylist())}
    fields = ("p_cont", "p_fail", "p_unresolved", "p_two", "expected_mfe", "expected_mae", "expected_time", "expected_net")
    maximum: dict[str, float] = {}
    for name in fields:
        expected = np.asarray([sealed[name][lookup[str(data.row_id[index])]].as_py() for index in available_indices], dtype=np.float64)
        maximum[name] = float(np.max(np.abs(expected - predicted[name]))) if len(expected) else 0.0
    overall = max(maximum.values(), default=0.0)
    if overall > 1e-8:
        raise ValueError(f"Sealed base model reproduction exceeds tolerance for {fold}/{data.timeframe}/{family}: {overall}")
    return {"rows": len(available_indices), "maximum_absolute_error": rounded(overall), "per_field_maximum_absolute_error": {key: rounded(value) for key, value in maximum.items()}, "tolerance": 1e-8}


def run_evaluation(label: str, feature_path: Path, protocol: Mapping[str, Any]) -> dict[str, Any]:
    vocab = core.global_vocabularies(); records = model_lookup()
    fold_specs = [(int(item["fold"]), core.day_int(item["validate"][0]), core.day_int(item["validate"][1])) for item in protocol["folds"]]
    candidate_trades: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    calibrations = {(timeframe, family, comparator): core.CalibrationAccumulator() for timeframe in core.TIMEFRAMES for family in core.MODEL_FAMILIES for comparator in COMPARATORS}
    support_failures: list[dict[str, Any]] = []; fold_records: list[dict[str, Any]] = []; coverage: dict[str, Any] = {}
    for timeframe in core.TIMEFRAMES:
        print(canonical_json({"status": "GC_EVALUATION_TIMEFRAME", "implementation": label, "timeframe": timeframe, "at": core.utc_now()}), flush=True)
        data, gc_values, coverage[timeframe] = augmented_dataset(timeframe, vocab, feature_path)
        for fold, validation_start, validation_end in fold_specs:
            training_days = np.unique(data.decision_day[(data.decision_day < validation_start) & data.feature_available])
            fit_days, cal_days = core.split_training_dates(training_days, 0.2) if len(training_days) >= 2 else (np.asarray([], dtype=np.int32), np.asarray([], dtype=np.int32))
            eligible = data.training_checkpoint & data.feature_available & data.outcome_available
            fit_indices = np.flatnonzero(eligible & np.isin(data.decision_day, fit_days)); cal_indices = np.flatnonzero(eligible & np.isin(data.decision_day, cal_days))
            calibration_indices = np.flatnonzero(data.feature_available & np.isin(data.decision_day, cal_days))
            validation_indices = np.flatnonzero(data.feature_available & (data.decision_day >= validation_start) & (data.decision_day <= validation_end))
            fit_cases = len(np.unique(data.case_code[fit_indices])); cal_cases = len(np.unique(data.case_code[cal_indices]))
            support = {
                "fit_rows": len(fit_indices), "fit_cases": fit_cases, "calibration_rows": len(cal_indices), "calibration_cases": cal_cases,
                "validation_rows": len(validation_indices), "validation_cases": len(np.unique(data.case_code[validation_indices])) if len(validation_indices) else 0,
                "fit_dates": len(fit_days), "calibration_dates": len(cal_days),
            }
            required_fit = int(protocol["training"]["minimum_fit_cases"][timeframe]); required_cal = int(protocol["training"]["minimum_calibration_cases"][timeframe])
            if fit_cases < required_fit or cal_cases < required_cal or not len(validation_indices):
                failure = {"fold": fold, "timeframe": timeframe, "status": "SUPPORT_FAIL", "support": support, "required_fit_cases": required_fit, "required_calibration_cases": required_cal}
                support_failures.append(failure); fold_records.append(failure); continue
            for family in core.MODEL_FAMILIES:
                base_record = records[(fold, timeframe, family)]; base_bundle = reconstruct_bundle(base_record)
                base_reconstruction = verify_base_bundle_reconstruction(base_bundle, data, validation_indices, fold, family)
                for comparator in COMPARATORS:
                    model = fit_incremental(comparator, base_bundle, data, gc_values, fit_indices, cal_indices, fold, family)
                    calibration_prediction = predict_incremental(model, base_bundle, data, gc_values, calibration_indices)
                    full_calibration = core.full_prediction_arrays(data, calibration_indices, calibration_prediction)
                    calibration_mask = np.zeros(data.n, dtype=bool); calibration_mask[calibration_indices] = True
                    selected_grid, selection = core.select_policy(data, calibration_mask, full_calibration, timeframe)
                    validation_prediction = predict_incremental(model, base_bundle, data, gc_values, validation_indices)
                    calibrations[(timeframe, family, comparator)].add(data, validation_indices, validation_prediction, float(model["training_base_rate"]))
                    full_validation = core.full_prediction_arrays(data, validation_indices, validation_prediction)
                    validation_mask = np.zeros(data.n, dtype=bool); validation_mask[validation_indices] = True
                    if selected_grid is not None:
                        for track in core.TRACKS:
                            candidate_id = f"{timeframe}::{family}::{track}"
                            trades, diagnostics = core.simulate_policy(data, validation_mask, full_validation, selected_grid, track)
                            core.annotate_trades(trades, fold, family, candidate_id)
                            for row in trades:
                                row["comparator"] = comparator
                            candidate_trades[(candidate_id, comparator)].extend(trades)
                    fold_records.append({
                        "fold": fold, "timeframe": timeframe, "family": family, "comparator": comparator,
                        "status": "FITTED", "support": support, "selection": model["selection"],
                        "base_reconstruction": base_reconstruction,
                        "selected_policy": selected_grid, "policy_selection": selection,
                        "gc_transformer": {
                            "median": [rounded(value) for value in model["transformer"].median],
                            "low": [rounded(value) for value in model["transformer"].low],
                            "high": [rounded(value) for value in model["transformer"].high],
                            "mean": [rounded(value) for value in model["transformer"].mean],
                            "std": [rounded(value) for value in model["transformer"].std],
                        },
                        "coefficient_hash": canonical_hash({
                            "response": np.asarray(model["response"]).round(12).tolist(),
                            "two": np.asarray(model["two"]).round(12).tolist(),
                            "ridge": np.asarray(model["ridge"]).round(12).tolist(),
                        }),
                    })
        del data, gc_values
    retained: dict[tuple[str, str], list[dict[str, Any]]] = {}
    results: dict[str, dict[str, Any]] = {}
    for timeframe in core.TIMEFRAMES:
        for family in core.MODEL_FAMILIES:
            for track in core.TRACKS:
                candidate_id = f"{timeframe}::{family}::{track}"
                for comparator in COMPARATORS:
                    trades, overlap_skipped = core.enforce_overlap(candidate_trades.get((candidate_id, comparator), []))
                    retained[(candidate_id, comparator)] = trades
                    metrics = core.candidate_summary(
                        trades,
                        calibrations[(timeframe, family, comparator)].result(),
                        None,
                        0.0,
                        core.stable_seed("GC", label, candidate_id, comparator),
                    )
                    metrics["final_overlap_skipped"] = overlap_skipped
                    results[f"{candidate_id}::{comparator}"] = metrics
    return {"implementation": label, "coverage": coverage, "support_failures": support_failures, "fold_records": fold_records, "metrics": results, "trades": retained}


def paired_delta(base_trades: Sequence[Mapping[str, Any]], plus_trades: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    by_date_base: dict[str, float] = defaultdict(float); by_date_plus: dict[str, float] = defaultdict(float)
    by_fold_base: dict[str, float] = defaultdict(float); by_fold_plus: dict[str, float] = defaultdict(float)
    by_year_base: dict[str, float] = defaultdict(float); by_year_plus: dict[str, float] = defaultdict(float)
    for row in base_trades:
        by_date_base[str(row["decision_date"])] += float(row["pnl_usd_1x"]); by_fold_base[str(row["fold"])] += float(row["pnl_usd_1x"]); by_year_base[str(row["calendar_year"])] += float(row["pnl_usd_1x"])
    for row in plus_trades:
        by_date_plus[str(row["decision_date"])] += float(row["pnl_usd_1x"]); by_fold_plus[str(row["fold"])] += float(row["pnl_usd_1x"]); by_year_plus[str(row["calendar_year"])] += float(row["pnl_usd_1x"])
    dates = sorted(set(by_date_base) | set(by_date_plus)); delta = np.asarray([by_date_plus[day] - by_date_base[day] for day in dates], dtype=np.float64)
    if not len(delta):
        return {"covered_trade_dates": 0, "total_pnl_delta_usd": 0.0, "mean_date_delta_usd": None, "ci95_low_mean_date_delta_usd": None, "ci95_high_mean_date_delta_usd": None, "one_sided_p": 1.0, "positive_fold_deltas": 0, "positive_year_deltas": 0}
    rng = np.random.default_rng(seed); samples = np.empty(INCREMENTAL_BOOTSTRAPS, dtype=np.float64)
    for begin in range(0, INCREMENTAL_BOOTSTRAPS, 250):
        size = min(250, INCREMENTAL_BOOTSTRAPS - begin); indexes = rng.integers(0, len(delta), size=(size, len(delta)))
        samples[begin:begin + size] = delta[indexes].mean(axis=1)
    fold_keys = sorted(set(by_fold_base) | set(by_fold_plus)); year_keys = sorted(set(by_year_base) | set(by_year_plus))
    return {
        "covered_trade_dates": len(dates), "total_pnl_delta_usd": rounded(float(delta.sum())), "mean_date_delta_usd": rounded(float(delta.mean())),
        "ci95_low_mean_date_delta_usd": rounded(float(np.quantile(samples, 0.025))), "ci95_high_mean_date_delta_usd": rounded(float(np.quantile(samples, 0.975))),
        "one_sided_p": rounded(float((np.sum(samples <= 0) + 1) / (INCREMENTAL_BOOTSTRAPS + 1))),
        "positive_fold_deltas": sum(by_fold_plus[key] - by_fold_base[key] > 0 for key in fold_keys),
        "positive_year_deltas": sum(by_year_plus[key] - by_year_base[key] > 0 for key in year_keys),
        "fold_deltas_usd": {key: rounded(by_fold_plus[key] - by_fold_base[key]) for key in fold_keys},
        "year_deltas_usd": {key: rounded(by_year_plus[key] - by_year_base[key]) for key in year_keys},
    }


def comparison_results(evaluation: Mapping[str, Any], protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for timeframe in core.TIMEFRAMES:
        support_floor = protocol["support_floors"][timeframe]
        for family in core.MODEL_FAMILIES:
            for track in core.TRACKS:
                candidate_id = f"{timeframe}::{family}::{track}"
                base_metrics = evaluation["metrics"][f"{candidate_id}::BASE_MATCHED_RECALIBRATED"]
                plus_metrics = evaluation["metrics"][f"{candidate_id}::BASE_PLUS_GC"]
                delta = paired_delta(
                    evaluation["trades"][(candidate_id, "BASE_MATCHED_RECALIBRATED")],
                    evaluation["trades"][(candidate_id, "BASE_PLUS_GC")],
                    core.stable_seed("GC_DELTA", candidate_id),
                )
                rows.append({"candidate_id": candidate_id, "timeframe": timeframe, "model_family": family, "track": track, "base": base_metrics, "plus_gc": plus_metrics, "delta": delta, "support_floor": support_floor})
    ordered = sorted(enumerate(rows), key=lambda item: (float(item[1]["delta"]["one_sided_p"]), str(item[1]["candidate_id"])))
    running = 0.0; total = len(rows)
    for rank, (index, row) in enumerate(ordered):
        adjusted = min(1.0, (total - rank) * float(row["delta"]["one_sided_p"])); running = max(running, adjusted); rows[index]["holm_adjusted_p"] = rounded(running)
    for row in rows:
        base_metrics = row["base"]; plus = row["plus_gc"]; delta = row["delta"]; floor = row["support_floor"]
        pf_base = base_metrics.get("profit_factor"); pf_plus = plus.get("profit_factor")
        folds_evaluable = len(set(str(trade["fold"]) for comparator in COMPARATORS for trade in evaluation["trades"][(row["candidate_id"], comparator)]))
        gates = {
            "both_support_original_trade_floor": int(base_metrics["trades"]) >= int(floor["trades"]) and int(plus["trades"]) >= int(floor["trades"]),
            "both_support_original_date_floor": int(base_metrics["dates"]) >= int(floor["dates"]) and int(plus["dates"]) >= int(floor["dates"]),
            "at_least_three_evaluable_folds": folds_evaluable >= 3,
            "brier_improves": plus["calibration"].get("brier") is not None and base_metrics["calibration"].get("brier") is not None and float(plus["calibration"]["brier"]) < float(base_metrics["calibration"]["brier"]),
            "expectancy_improves": plus.get("expectancy_r") is not None and base_metrics.get("expectancy_r") is not None and float(plus["expectancy_r"]) > float(base_metrics["expectancy_r"]),
            "profit_factor_improves": pf_plus is not None and pf_base is not None and float(pf_plus) > float(pf_base),
            "net_pnl_improves": float(plus["net_pnl_usd"]) > float(base_metrics["net_pnl_usd"]),
            "paired_ci95_low_gt_zero": delta["ci95_low_mean_date_delta_usd"] is not None and float(delta["ci95_low_mean_date_delta_usd"]) > 0,
            "holm_p_lte_0p10": float(row["holm_adjusted_p"]) <= 0.10,
            "plus_1p5x_positive_and_improves": plus.get("expectancy_1p5x_r") is not None and base_metrics.get("expectancy_1p5x_r") is not None and float(plus["expectancy_1p5x_r"]) > 0 and float(plus["expectancy_1p5x_r"]) > float(base_metrics["expectancy_1p5x_r"]),
            "positive_fold_deltas_gte_3": int(delta["positive_fold_deltas"]) >= 3,
            "positive_year_deltas_gte_2": int(delta["positive_year_deltas"]) >= 2,
        }
        row["gates"] = gates; row["failed_gates"] = [name for name, passed in gates.items() if not passed]
        support_ok = gates["both_support_original_trade_floor"] and gates["both_support_original_date_floor"] and gates["at_least_three_evaluable_folds"]
        row["verdict"] = "SUPPORT_FAIL" if not support_ok else "ADDS_INCREMENTAL_VALUE" if all(gates.values()) else "NO_PROVEN_INCREMENTAL_VALUE"
    return rows


def remove_trades_for_serialization(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in evaluation.items() if key != "trades"}


def report_markdown(final: Mapping[str, Any]) -> str:
    lines = [
        "# Gold PIT Auction-State V1 — GC Incremental Comparison", "",
        f"Status: **{final['verdict']}**", "",
        "This is a matched, sparse-date incremental study only. It cannot create a standalone candidate or unlock 2025/2026.", "",
        "| Comparison | Base trades | Base Exp R | Base PF | +GC trades | +GC Exp R | +GC PF | PnL delta | Brier delta | Paired CI low/day | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in final["comparisons"]:
        base = row["base"]; plus = row["plus_gc"]; delta = row["delta"]
        brier_delta = None if base["calibration"].get("brier") is None or plus["calibration"].get("brier") is None else float(plus["calibration"]["brier"]) - float(base["calibration"]["brier"])
        lines.append(f"| {row['candidate_id']} | {base['trades']} | {base.get('expectancy_r')} | {base.get('profit_factor')} | {plus['trades']} | {plus.get('expectancy_r')} | {plus.get('profit_factor')} | ${delta.get('total_pnl_delta_usd')} | {rounded(brier_delta)} | ${delta.get('ci95_low_mean_date_delta_usd')} | {row['verdict']} |")
    lines.extend(["", "Calendar 2025 and 2026 were not accessed. No paid data was acquired.", ""])
    return "\n".join(lines)


def main() -> None:
    base, protocol, manifest = verify_predecessors()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(FREEZE, freeze_payload(base, protocol, manifest))
    primary_features, primary_feature_diagnostics = materialize_features("primary", "PRIMARY_NUMPY")
    reference_features, reference_feature_diagnostics = materialize_features("reference", "REFERENCE_PYTHON")
    feature_reproduction = {
        "byte_identical": sha256_file(primary_features) == sha256_file(reference_features),
        "diagnostics_equal": primary_feature_diagnostics == reference_feature_diagnostics,
        "primary": primary_feature_diagnostics, "reference": reference_feature_diagnostics,
    }
    if not feature_reproduction["byte_identical"] or not feature_reproduction["diagnostics_equal"]:
        raise ValueError(f"GC feature reproduction failed: {feature_reproduction}")
    primary = run_evaluation("primary", primary_features, protocol)
    reference = run_evaluation("reference", reference_features, protocol)
    primary_serial = remove_trades_for_serialization(primary); reference_serial = remove_trades_for_serialization(reference)
    evaluation_reproduction = canonical_hash(primary_serial) == canonical_hash(reference_serial)
    if not evaluation_reproduction:
        raise ValueError("GC incremental primary/reference evaluation differs")
    comparisons = comparison_results(primary, protocol)
    passing = [row["candidate_id"] for row in comparisons if row["verdict"] == "ADDS_INCREMENTAL_VALUE"]
    verdict = "ADDS_PROVEN_INCREMENTAL_GC_VALUE_NO_STANDALONE_CREDIT" if passing else "NO_PROVEN_INCREMENTAL_GC_VALUE"
    result = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_GC_INCREMENTAL_FINAL_1_0", "status": "PASS_INDEPENDENT_GC_INCREMENTAL_REPRODUCTION",
        "verdict": verdict, "completed_at_utc": core.utc_now(), "passing_incremental_comparisons": passing,
        "comparisons": comparisons, "coverage": primary["coverage"], "support_failures": primary["support_failures"],
        "feature_reproduction": feature_reproduction, "evaluation_reproduction": evaluation_reproduction,
        "base_development_verdict_preserved": base["development_verdict"], "standalone_candidate_credit": False,
        "forward_disposition": "KEEP_2025_2026_LOCKED", "prospective_ledger_initialized": False,
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    primary_path = OUTPUT / "primary_evaluation.json"; reference_path = OUTPUT / "reference_evaluation.json"
    write_json_exclusive(primary_path, primary_serial); write_json_exclusive(reference_path, reference_serial)
    report = ROOT / "GOLD_POINT_IN_TIME_AUCTION_STATE_AND_ADAPTIVE_MANAGEMENT_V1_GC_INCREMENTAL_RESULTS.md"
    report.write_text(report_markdown(result), encoding="utf-8", newline="\n")
    result["artifacts"] = {
        "protocol_freeze": file_record(FREEZE), "primary_features": file_record(primary_features), "reference_features": file_record(reference_features),
        "primary_evaluation": file_record(primary_path), "reference_evaluation": file_record(reference_path), "report": file_record(report),
    }
    result_path = OUTPUT / "gc_incremental_results.json"; write_json_exclusive(result_path, result); result["artifacts"]["result"] = file_record(result_path)
    write_json_exclusive(FINAL, result)
    print(canonical_json({"status": "COMPLETE", "verdict": verdict, "passing_incremental_comparisons": passing, "feature_reproduction": feature_reproduction["byte_identical"], "evaluation_reproduction": evaluation_reproduction}), flush=True)


if __name__ == "__main__":
    main()
