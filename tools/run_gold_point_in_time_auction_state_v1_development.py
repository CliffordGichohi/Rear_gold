from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from scipy import sparse


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
TAPE_DIR = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape"
DEV_DIR = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_development"
OUTPUT = ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_results"

CONTRACT = ROOT / "GOLD_POINT_IN_TIME_AUCTION_STATE_AND_ADAPTIVE_TRADE_MANAGEMENT_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_protocol.json"
EXECUTION_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_outcome_model_policy_execution_freeze.json"
TAPE_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_tape_freeze.json"
OUTCOME_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_outcome_freeze.json"
IMPLEMENTATION_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_development_implementation_freeze.json"
FINAL_FREEZE = MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_development_freeze.json"

FEATURES = TAPE_DIR / "primary_checkpoint_features.parquet"
OUTCOMES = DEV_DIR / "primary_checkpoint_outcomes.parquet"
ATLAS = ARTIFACTS / "gold_pullback_behavioural_archetypes_v1" / "primary_archetypes.parquet"

SCALE = 100_000_000
TIMEFRAMES = ("M15", "H1", "H4")
TIMEFRAME_PRIORITY = {"H4": 0, "H1": 1, "M15": 2}
MODEL_FAMILIES = ("LINEAR_COMPETING_RISK_V1", "ADDITIVE_BINNED_COMPETING_RISK_V1")
TRACKS = ("CONSTANT_50", "ADAPTIVE_12P5_PLUS_37P5")
CLASSES = ("CONTINUATION_1R_FIRST", "FAILURE_STOP_FIRST", "UNRESOLVED")
CLASS_INDEX = {value: index for index, value in enumerate(CLASSES)}
BASE_SEED = 621_907
BOOTSTRAPS = 5_000


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def parse_ns(value: str | None) -> int:
    if not value:
        return np.iinfo(np.int64).max
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1_000_000_000)


def day_int(value: str) -> int:
    return int(np.datetime64(value, "D").astype(np.int64))


def day_string(value: int) -> str:
    return str(np.datetime64(int(value), "D"))


def stable_seed(*parts: Any) -> int:
    return BASE_SEED ^ int(canonical_hash(list(parts))[:8], 16)


def verify_record(record: Mapping[str, Any]) -> None:
    path = ROOT / str(record["path"])
    if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
        raise ValueError(f"Frozen artifact changed: {record['path']}")


def preflight() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    execution = json.loads(EXECUTION_FREEZE.read_text(encoding="utf-8"))
    tape = json.loads(TAPE_FREEZE.read_text(encoding="utf-8"))
    outcome = json.loads(OUTCOME_FREEZE.read_text(encoding="utf-8"))
    if tape.get("status") != "PASS_OUTCOME_BLIND_DECISION_TAPE_MATERIALIZATION" or not tape.get("byte_identical"):
        raise ValueError("Decision-tape predecessor has not passed")
    if outcome.get("status") != "PASS_DEVELOPMENT_CHECKPOINT_OUTCOME_MATERIALIZATION" or not outcome.get("byte_identical"):
        raise ValueError("Outcome predecessor has not passed")
    if execution.get("status") != "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_OPENING":
        raise ValueError("Frozen model/policy protocol changed")
    verify_record(tape["artifacts"]["primary"])
    verify_record(outcome["artifacts"]["primary"])
    verify_record(outcome["controls"]["execution"])
    if sha256_file(CONTRACT) != json.loads((MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_preoutcome_freeze.json").read_text(encoding="utf-8"))["controls"]["contract"]["sha256"]:
        raise ValueError("Contract changed after freeze")
    if any(path.exists() for path in (IMPLEMENTATION_FREEZE, FINAL_FREEZE, OUTPUT / "development_results.json")):
        raise FileExistsError("Development implementation or result already exists")
    return protocol, execution, outcome


def synthetic_proof() -> dict[str, Any]:
    logits = np.asarray([[0.0, 1.0, -1.0], [1000.0, 999.0, 998.0]], dtype=np.float64)
    shifted = logits - logits.max(axis=1, keepdims=True)
    p = np.exp(shifted); p /= p.sum(axis=1, keepdims=True)
    if not np.allclose(p.sum(axis=1), 1.0, atol=1e-15):
        raise AssertionError("Softmax proof failed")
    dates = np.asarray([1, 1, 2, 3, 3, 3], dtype=np.int64)
    weights = case_weights(np.asarray([0, 0, 1, 2, 2, 2], dtype=np.int32))
    if not np.allclose([weights[:2].sum(), weights[2:3].sum(), weights[3:].sum()], 1.0):
        raise AssertionError("Case weighting proof failed")
    fit, calibration = split_training_dates(np.asarray([1, 2, 3, 4, 5], dtype=np.int64), 0.2)
    if fit.tolist() != [1, 2, 3, 4] or calibration.tolist() != [5]:
        raise AssertionError("Chronological split proof failed")
    grid = policy_grid()
    if len(grid) != 96 or len({item["grid_id"] for item in grid}) != 96:
        raise AssertionError("Policy grid proof failed")
    infinity = np.iinfo(np.int64).max; checkpoints = np.arange(4, dtype=np.int64) * 60_000_000_000
    synthetic = DataSet(
        timeframe="M15", n=4, row_id=np.asarray([f"R{i}" for i in range(4)], object), pullback_id=np.asarray(["P"] * 4, object),
        case_code=np.zeros(4, np.int32), decision_day=np.ones(4, np.int32), checkpoint_ns=checkpoints,
        deadline_ns=np.full(4, checkpoints[-1], np.int64), training_checkpoint=np.ones(4, bool), feature_available=np.ones(4, bool),
        numeric=np.zeros((4, len(NUMERIC))), categorical=np.zeros((4, len(CATEGORICAL)), np.int16), session=np.asarray(["LONDON"] * 4, object),
        direction_sign=np.ones(4, np.int8), structural_stop=np.full(4, 99 * SCALE, np.int64), outcome_available=np.ones(4, bool),
        entry=np.full(4, 100 * SCALE, np.int64), stop=np.full(4, 99 * SCALE, np.int64), target=np.full(4, 102 * SCALE, np.int64),
        risk=np.full(4, SCALE, np.int64), cost=np.full(4, 0.17), primary_class=np.asarray([CLASSES[0]] * 4, object), two_r=np.ones(4, bool),
        mfe=np.full(4, 2.0), mae=np.full(4, 0.5), passage_minutes=np.full(4, 2.0), terminal_net_r=np.full(4, 1.83),
        first_stop_ns=np.full(4, infinity, np.int64), first_target_ns=np.full(4, checkpoints[2], np.int64),
        first_stop_fill=np.full(4, np.iinfo(np.int64).min, np.int64), terminal_exit_ns=np.full(4, checkpoints[2], np.int64),
        terminal_exit_price=np.full(4, 102 * SCALE, np.int64), stop_then_target=np.zeros(4, bool), oracle_r_by_case={"P": 2.0},
    )
    synthetic_predictions = {name: np.full(4, value) for name, value in {
        "p_cont": 0.8, "p_fail": 0.1, "p_unresolved": 0.1, "p_two": 0.4,
        "expected_mfe": 2.0, "expected_mae": 0.5, "expected_time": 2.0, "expected_net": 0.2,
    }.items()}
    synthetic_trades, _ = simulate_policy(synthetic, np.ones(4, bool), synthetic_predictions, grid[0], "CONSTANT_50")
    if len(synthetic_trades) != 1 or synthetic_trades[0]["exit_reason"] != "LIQUIDITY_TARGET_EXIT" or float(synthetic_trades[0]["pnl_usd_1x"]) <= 0:
        raise AssertionError("Policy first-passage proof failed")
    return {
        "status": "PASS_SYNTHETIC_MODEL_POLICY_PRIMITIVES",
        "softmax_rows": 2,
        "case_weight_groups": 3,
        "chronological_split_dates": 5,
        "policy_grid_size": 96, "policy_first_passage_trades": 1,
    }


def implementation_policy() -> dict[str, Any]:
    return {
        "version": "GOLD_PIT_AUCTION_STATE_V1_DEVELOPMENT_IMPLEMENTATION_1_0",
        "status": "SEALED_BEFORE_MODEL_FITTING_OR_POLICY_PERFORMANCE_CALCULATION",
        "sealed_at_utc": utc_now(),
        "controls": {
            "contract": file_record(CONTRACT), "protocol": file_record(PROTOCOL),
            "execution_freeze": file_record(EXECUTION_FREEZE), "tape_freeze": file_record(TAPE_FREEZE),
            "outcome_freeze": file_record(OUTCOME_FREEZE),
        },
        "implementation": file_record(Path(__file__).resolve()),
        "interpretations_frozen_without_performance_selection": {
            "preprocessing_quantiles": "UNWEIGHTED_FIT_ROWS;WEIGHTED_MEAN_AND_STD_AFTER_CLIP_AND_IMPUTATION",
            "classification_selection": "SHARED_C_AND_TEMPERATURE_MINIMIZING_EQUAL_WEIGHT_MEAN_OF_MULTICLASS_AND_TWO_R_CALIBRATION_CROSS_ENTROPY",
            "regression_selection": "SHARED_ALPHA_MINIMIZING_EQUAL_WEIGHT_MEAN_OF_FOUR_TRANSFORMED_TARGET_NMSE_VALUES",
            "policy_selection_track": "CONSTANT_50_ONLY;THE_SAME_SELECTED_GRID_IS_APPLIED_TO_BOTH_TRACKS",
            "policy_expected_net": "MODEL_PREDICTED_TERMINAL_NET_R_AT_ONE_X_COST",
            "scratch_condition": "TWO_CONSECUTIVE_POST_ENTRY_CHECKPOINTS_EACH_SATISFYING_P_CONT_LT_THRESHOLD_OR_EXPECTED_NET_R_LE_ZERO",
            "hard_event_priority": "STOP_THEN_TARGET_BEFORE_ANY_MODEL_ACTION_AT_THE_SAME_OR_LATER_CHECKPOINT",
            "constant_track_add_signal": "VIRTUAL_ADD_SIGNAL_MAY_TIGHTEN_STOP_BUT_ADDS_NO_OUNCES",
            "adaptive_add_sizing": "WHOLE_OUNCES_CAPPED_BY_37P50_INCREMENT_AND_50_USD_TOTAL_STOP_PLUS_COST_RISK_AT_THE_TIGHTENED_STOP",
            "candidate_overlap": "ONE_POSITION_WITHIN_EACH_TIMEFRAME_CANDIDATE;COMBINED_PORTFOLIO_USES_H4_H1_M15_THEN_PULLBACK_ID",
            "r_normalization": "NET_DOLLARS_DIVIDED_BY_50_USD_ACCOUNT_SETUP_RISK_CAP",
            "brier_weighting": "EQUAL_CASE_WEIGHT_WITHIN_EACH_OUTER_VALIDATION_FOLD",
            "policy_neighbours": "AGGREGATE_IDENTICAL_DIMENSION_AND_ORDINAL_DIRECTION_NEIGHBOURS_ACROSS_FOLDS_THEN_COUNT_POSITIVE_EXPECTANCY",
            "bootstrap": "SAMPLE_TRADING_DATE_CLUSTERS_WITH_REPLACEMENT;UNWEIGHTED_TRADES_WITHIN_SAMPLED_CLUSTER",
            "candidate_limit_ranking": "EXPECTANCY_DESC_THEN_PROFIT_FACTOR_DESC_THEN_SUPPORT_DESC_THEN_CANDIDATE_ID",
        },
        "synthetic_proof": synthetic_proof(),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }


def split_training_dates(unique_dates: np.ndarray, calibration_fraction: float) -> tuple[np.ndarray, np.ndarray]:
    ordered = np.unique(unique_dates)
    count = max(1, int(math.ceil(len(ordered) * calibration_fraction)))
    return ordered[:-count], ordered[-count:]


def case_weights(case_codes: np.ndarray) -> np.ndarray:
    _, inverse, counts = np.unique(case_codes, return_inverse=True, return_counts=True)
    return 1.0 / counts[inverse].astype(np.float64)


def policy_grid() -> list[dict[str, Any]]:
    values = {
        "p_cont_min": (0.50, 0.575, 0.65), "p_fail_max": (0.35, 0.45),
        "p_two_min": (0.20, 0.35), "ev_min": (0.0, 0.10),
        "add_improvement": (0.05, 0.10), "scratch_p": (0.40, 0.475),
    }
    result = []
    for ordinal, combination in enumerate(product(*values.values())):
        item = dict(zip(values, combination, strict=True))
        item["grid_id"] = f"GRID_{ordinal:03d}"
        item["ordinals"] = {name: values[name].index(item[name]) for name in values}
        result.append(item)
    return result


NUMERIC: tuple[str, ...] = (
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
)
CATEGORICAL: tuple[str, ...] = (
    "fundamental_alignment_state", "fundamental_regime", "reaction_function", "event_risk",
    "session_state", "h1_relative_state", "h4_relative_state",
)


def global_vocabularies() -> dict[str, list[str]]:
    table = pq.read_table(FEATURES, columns=list(CATEGORICAL))
    result: dict[str, list[str]] = {}
    for name in CATEGORICAL:
        values = {str(value) for value in pc.unique(table[name]).to_pylist() if value is not None}
        values.update(("UNKNOWN", "OTHER"))
        result[name] = sorted(values)
    return result


@dataclass
class DataSet:
    timeframe: str
    n: int
    row_id: np.ndarray
    pullback_id: np.ndarray
    case_code: np.ndarray
    decision_day: np.ndarray
    checkpoint_ns: np.ndarray
    deadline_ns: np.ndarray
    training_checkpoint: np.ndarray
    feature_available: np.ndarray
    numeric: np.ndarray
    categorical: np.ndarray
    session: np.ndarray
    direction_sign: np.ndarray
    structural_stop: np.ndarray
    outcome_available: np.ndarray
    entry: np.ndarray
    stop: np.ndarray
    target: np.ndarray
    risk: np.ndarray
    cost: np.ndarray
    primary_class: np.ndarray
    two_r: np.ndarray
    mfe: np.ndarray
    mae: np.ndarray
    passage_minutes: np.ndarray
    terminal_net_r: np.ndarray
    first_stop_ns: np.ndarray
    first_target_ns: np.ndarray
    first_stop_fill: np.ndarray
    terminal_exit_ns: np.ndarray
    terminal_exit_price: np.ndarray
    stop_then_target: np.ndarray
    oracle_r_by_case: dict[str, float]

    def case_ranges(self, mask: np.ndarray | None = None) -> list[tuple[int, int]]:
        if self.n == 0:
            return []
        boundaries = np.flatnonzero(np.r_[True, self.case_code[1:] != self.case_code[:-1], True])
        ranges = [(int(boundaries[i]), int(boundaries[i + 1])) for i in range(len(boundaries) - 1)]
        if mask is None:
            return ranges
        return [(a, b) for a, b in ranges if bool(np.any(mask[a:b]))]


def arrow_strings(array: pa.ChunkedArray) -> np.ndarray:
    return np.asarray(array.to_pylist(), dtype=object)


def arrow_numeric(array: pa.ChunkedArray, dtype: Any, null: Any = np.nan) -> np.ndarray:
    return np.asarray(array.to_pylist(), dtype=dtype) if null is None else np.asarray([null if x is None else x for x in array.to_pylist()], dtype=dtype)


def load_timeframe(timeframe: str, vocab: Mapping[str, Sequence[str]]) -> DataSet:
    feature_columns = [
        "row_id", "pullback_id", "decision_date", "checkpoint_at_utc", "deadline_at_utc",
        "training_checkpoint", "checkpoint_feature_available", "direction", "structural_stop_e8",
        *NUMERIC, *CATEGORICAL,
    ]
    outcome_columns = [
        "row_id", "outcome_available", "entry_e8", "stop_e8", "target_e8", "risk_e8",
        "round_trip_cost_usd_oz", "primary_class", "two_r_before_stop", "mfe_r", "mae_r",
        "time_to_first_passage_minutes", "terminal_net_r", "first_stop_at_utc", "first_target_at_utc",
        "first_stop_fill_e8", "terminal_exit_at_utc", "terminal_exit_e8", "stop_then_target_before_deadline",
    ]
    ft = pq.read_table(FEATURES, columns=feature_columns, filters=[("timeframe", "=", timeframe)]).combine_chunks()
    ot = pq.read_table(OUTCOMES, columns=outcome_columns, filters=[("timeframe", "=", timeframe)]).combine_chunks()
    if len(ft) != len(ot) or not pc.all(pc.equal(ft["row_id"], ot["row_id"])).as_py():
        raise ValueError(f"Feature/outcome identity mismatch for {timeframe}")
    row_id = arrow_strings(ft["row_id"]); pullback_id = arrow_strings(ft["pullback_id"])
    unique_ids: dict[str, int] = {}; case_code = np.empty(len(ft), dtype=np.int32)
    for index, identity in enumerate(pullback_id):
        code = unique_ids.setdefault(str(identity), len(unique_ids)); case_code[index] = code
    decision_day = np.asarray([day_int(str(value)) for value in ft["decision_date"].to_pylist()], dtype=np.int32)
    checkpoint_ns = np.asarray([parse_ns(str(value)) for value in ft["checkpoint_at_utc"].to_pylist()], dtype=np.int64)
    deadline_ns = np.asarray([parse_ns(str(value)) for value in ft["deadline_at_utc"].to_pylist()], dtype=np.int64)
    numeric = np.column_stack([arrow_numeric(ft[name], np.float64) for name in NUMERIC])
    categorical = np.empty((len(ft), len(CATEGORICAL)), dtype=np.int16)
    for j, name in enumerate(CATEGORICAL):
        mapping = {value: index for index, value in enumerate(vocab[name])}; other = mapping["OTHER"]
        categorical[:, j] = np.asarray([mapping.get("UNKNOWN" if value is None else str(value), other) for value in ft[name].to_pylist()], dtype=np.int16)
    atlas = pq.read_table(ATLAS, columns=["pullback_id", "timeframe", "oracle_r"], filters=[("timeframe", "=", timeframe)])
    oracle = {str(identity): float(value) for identity, value in zip(atlas["pullback_id"].to_pylist(), atlas["oracle_r"].to_pylist(), strict=True) if value is not None}
    parse_optional_ns = lambda column: np.asarray([parse_ns(value) for value in ot[column].to_pylist()], dtype=np.int64)
    parse_int = lambda column: arrow_numeric(ot[column], np.int64, np.iinfo(np.int64).min)
    return DataSet(
        timeframe=timeframe, n=len(ft), row_id=row_id, pullback_id=pullback_id, case_code=case_code,
        decision_day=decision_day, checkpoint_ns=checkpoint_ns, deadline_ns=deadline_ns,
        training_checkpoint=np.asarray(ft["training_checkpoint"].to_numpy(), dtype=bool),
        feature_available=np.asarray(ft["checkpoint_feature_available"].to_numpy(), dtype=bool),
        numeric=numeric, categorical=categorical,
        session=np.asarray([str(value) for value in ft["session_state"].to_pylist()], dtype=object),
        direction_sign=np.asarray([1 if value == "UP" else -1 for value in ft["direction"].to_pylist()], dtype=np.int8),
        structural_stop=arrow_numeric(ft["structural_stop_e8"], np.int64, np.iinfo(np.int64).min),
        outcome_available=np.asarray(ot["outcome_available"].to_numpy(), dtype=bool),
        entry=parse_int("entry_e8"), stop=parse_int("stop_e8"), target=parse_int("target_e8"), risk=parse_int("risk_e8"),
        cost=arrow_numeric(ot["round_trip_cost_usd_oz"], np.float64),
        primary_class=np.asarray([str(value) for value in ot["primary_class"].to_pylist()], dtype=object),
        two_r=np.asarray([False if value is None else bool(value) for value in ot["two_r_before_stop"].to_pylist()], dtype=bool),
        mfe=arrow_numeric(ot["mfe_r"], np.float64), mae=arrow_numeric(ot["mae_r"], np.float64),
        passage_minutes=arrow_numeric(ot["time_to_first_passage_minutes"], np.float64),
        terminal_net_r=arrow_numeric(ot["terminal_net_r"], np.float64),
        first_stop_ns=parse_optional_ns("first_stop_at_utc"), first_target_ns=parse_optional_ns("first_target_at_utc"),
        first_stop_fill=parse_int("first_stop_fill_e8"), terminal_exit_ns=parse_optional_ns("terminal_exit_at_utc"),
        terminal_exit_price=parse_int("terminal_exit_e8"),
        stop_then_target=np.asarray([False if value is None else bool(value) for value in ot["stop_then_target_before_deadline"].to_pylist()], dtype=bool),
        oracle_r_by_case=oracle,
    )


@dataclass
class Transformer:
    family: str
    clip_low: np.ndarray
    clip_high: np.ndarray
    median: np.ndarray
    mean: np.ndarray
    std: np.ndarray
    quintiles: np.ndarray
    categorical_sizes: list[int]
    feature_names: list[str]

    @classmethod
    def fit(cls, family: str, numeric: np.ndarray, categorical_sizes: list[int], weights: np.ndarray) -> "Transformer":
        low = np.nanquantile(numeric, 0.01, axis=0); high = np.nanquantile(numeric, 0.99, axis=0)
        median = np.nanmedian(numeric, axis=0)
        low = np.where(np.isfinite(low), low, 0.0); high = np.where(np.isfinite(high), high, low)
        median = np.where(np.isfinite(median), median, 0.0)
        clipped = np.clip(np.where(np.isfinite(numeric), numeric, median), low, high)
        total = weights.sum(); mean = (clipped * weights[:, None]).sum(axis=0) / total
        variance = ((clipped - mean) ** 2 * weights[:, None]).sum(axis=0) / total
        std = np.sqrt(np.maximum(variance, 0.0)); std = np.where(std > 1e-12, std, 1.0)
        quintiles = np.empty((len(NUMERIC), 4), dtype=np.float64)
        for j in range(len(NUMERIC)):
            finite = numeric[:, j][np.isfinite(numeric[:, j])]
            quintiles[j] = np.quantile(finite, (0.2, 0.4, 0.6, 0.8)) if len(finite) else 0.0
        names = cls.names(family, categorical_sizes)
        return cls(family, low, high, median, mean, std, quintiles, categorical_sizes, names)

    @staticmethod
    def names(family: str, categorical_sizes: list[int]) -> list[str]:
        names = ["INTERCEPT"]
        if family == MODEL_FAMILIES[0]:
            names.extend(f"NUM::{name}" for name in NUMERIC)
            names.extend(f"MISS::{name}" for name in NUMERIC)
        else:
            for name in NUMERIC:
                names.extend(f"BIN::{name}::{i}" for i in range(6))
        for name, size in zip(CATEGORICAL, categorical_sizes, strict=True):
            names.extend(f"CAT::{name}::{i}" for i in range(size))
        if family == MODEL_FAMILIES[1]:
            for pair in ((14, 25), (30, 42), (28, 41)):
                names.extend(f"INT::{NUMERIC[pair[0]]}::{NUMERIC[pair[1]]}::{a}::{b}" for a in range(6) for b in range(6))
            session_size = categorical_sizes[CATEGORICAL.index("session_state")]
            names.extend(f"INT::session_state::elapsed_fraction::{a}::{b}" for a in range(session_size) for b in range(6))
        return names

    def transform(self, numeric: np.ndarray, categorical: np.ndarray) -> sparse.csr_matrix:
        n = len(numeric); rows: list[np.ndarray] = []; cols: list[np.ndarray] = []; vals: list[np.ndarray] = []
        rows.append(np.arange(n, dtype=np.int32)); cols.append(np.zeros(n, dtype=np.int32)); vals.append(np.ones(n, dtype=np.float64))
        offset = 1
        if self.family == MODEL_FAMILIES[0]:
            missing = ~np.isfinite(numeric)
            values = np.clip(np.where(missing, self.median, numeric), self.clip_low, self.clip_high)
            values = (values - self.mean) / self.std
            rr = np.repeat(np.arange(n, dtype=np.int32), len(NUMERIC))
            cc = np.tile(np.arange(len(NUMERIC), dtype=np.int32), n) + offset
            rows.append(rr); cols.append(cc); vals.append(values.reshape(-1))
            offset += len(NUMERIC)
            missing_columns = np.tile(np.arange(len(NUMERIC), dtype=np.int32), n) + offset
            rows.append(rr); cols.append(missing_columns); vals.append(missing.astype(np.float64).reshape(-1))
            offset += len(NUMERIC)
            bins = None
        else:
            bins = np.empty_like(numeric, dtype=np.int8)
            for j in range(len(NUMERIC)):
                finite = np.isfinite(numeric[:, j]); bins[:, j] = 5
                bins[finite, j] = np.searchsorted(self.quintiles[j], numeric[finite, j], side="right").astype(np.int8)
            rr = np.repeat(np.arange(n, dtype=np.int32), len(NUMERIC))
            cc = (np.tile(np.arange(len(NUMERIC), dtype=np.int32), n) * 6 + bins.reshape(-1)) + offset
            rows.append(rr); cols.append(cc); vals.append(np.ones(len(rr), dtype=np.float64)); offset += len(NUMERIC) * 6
        for j, size in enumerate(self.categorical_sizes):
            rows.append(np.arange(n, dtype=np.int32)); cols.append(offset + categorical[:, j].astype(np.int32)); vals.append(np.ones(n, dtype=np.float64)); offset += size
        if self.family == MODEL_FAMILIES[1]:
            assert bins is not None
            for left, right in ((14, 25), (30, 42), (28, 41)):
                rows.append(np.arange(n, dtype=np.int32)); cols.append(offset + bins[:, left].astype(np.int32) * 6 + bins[:, right].astype(np.int32)); vals.append(np.ones(n)); offset += 36
            session_index = CATEGORICAL.index("session_state"); session_size = self.categorical_sizes[session_index]
            rows.append(np.arange(n, dtype=np.int32)); cols.append(offset + categorical[:, session_index].astype(np.int32) * 6 + bins[:, 26].astype(np.int32)); vals.append(np.ones(n)); offset += session_size * 6
        matrix = sparse.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, len(self.feature_names)), dtype=np.float64).tocsr()
        matrix.sum_duplicates(); matrix.sort_indices()
        return matrix


@dataclass
class Classifier:
    weights: np.ndarray
    classes: int

    def logits(self, matrix: sparse.csr_matrix) -> np.ndarray:
        return np.asarray(matrix @ self.weights)


def probabilities(logits: np.ndarray, temperature: float) -> np.ndarray:
    if logits.ndim == 1 or logits.shape[1] == 1:
        value = np.clip(logits.reshape(-1) / temperature, -50.0, 50.0)
        return 1.0 / (1.0 + np.exp(-value))
    value = logits / temperature; value -= value.max(axis=1, keepdims=True)
    output = np.exp(value); output /= output.sum(axis=1, keepdims=True)
    return output


def classification_objective(matrix: sparse.csr_matrix, labels: np.ndarray, weights: np.ndarray, model: Classifier, c_value: float) -> float:
    logits = model.logits(matrix)
    if model.classes == 2:
        p = np.clip(probabilities(logits, 1.0), 1e-12, 1 - 1e-12)
        loss = -(weights * (labels * np.log(p) + (1 - labels) * np.log(1 - p))).sum() / weights.sum()
    else:
        p = np.clip(probabilities(logits, 1.0), 1e-12, 1.0)
        loss = -(weights * np.log(p[np.arange(len(labels)), labels])).sum() / weights.sum()
    penalty = np.sum(model.weights[1:] ** 2) / (2.0 * c_value * weights.sum())
    return float(loss + penalty)


def fit_adam(matrix: sparse.csr_matrix, labels: np.ndarray, sample_weights: np.ndarray, classes: int, c_value: float, seed: int) -> Classifier:
    n, p = matrix.shape; width = 1 if classes == 2 else classes
    coefficient = np.zeros((p, width), dtype=np.float64); m = np.zeros_like(coefficient); v = np.zeros_like(coefficient)
    best = coefficient.copy(); best_objective = math.inf; stale = 0; step = 0
    rng = np.random.default_rng(seed)
    for _epoch in range(200):
        order = rng.permutation(n)
        for begin in range(0, n, 4096):
            indices = order[begin:begin + 4096]; batch = matrix[indices]; w = sample_weights[indices]; denominator = w.sum()
            logits = np.asarray(batch @ coefficient)
            if classes == 2:
                p_hat = probabilities(logits, 1.0)
                residual = ((p_hat - labels[indices]) * w)[:, None]
            else:
                p_hat = probabilities(logits, 1.0)
                residual = p_hat; residual[np.arange(len(indices)), labels[indices]] -= 1.0; residual *= w[:, None]
            gradient = np.asarray(batch.T @ residual) / denominator
            gradient[1:] += coefficient[1:] / (c_value * sample_weights.sum())
            step += 1; m = 0.9 * m + 0.1 * gradient; v = 0.999 * v + 0.001 * gradient * gradient
            m_hat = m / (1.0 - 0.9 ** step); v_hat = v / (1.0 - 0.999 ** step)
            coefficient -= 0.01 * m_hat / (np.sqrt(v_hat) + 1e-8)
        model = Classifier(coefficient, classes); objective = classification_objective(matrix, labels, sample_weights, model, c_value)
        relative = (best_objective - objective) / max(1.0, abs(best_objective)) if math.isfinite(best_objective) else math.inf
        if objective < best_objective:
            best_objective = objective; best = coefficient.copy()
        stale = stale + 1 if relative < 1e-7 else 0
        if stale >= 10:
            break
    return Classifier(best, classes)


@dataclass
class ModelBundle:
    transformer: Transformer
    response: Classifier
    two_r: Classifier
    temperature: float
    ridge: np.ndarray
    c_value: float
    alpha: float
    training_base_rate: float
    selection: dict[str, Any]

    def predict(self, numeric: np.ndarray, categorical: np.ndarray) -> dict[str, np.ndarray]:
        matrix = self.transformer.transform(numeric, categorical)
        response = probabilities(self.response.logits(matrix), self.temperature)
        two = probabilities(self.two_r.logits(matrix), self.temperature)
        regressions = np.asarray(matrix @ self.ridge)
        return {
            "p_cont": response[:, 0], "p_fail": response[:, 1], "p_unresolved": response[:, 2], "p_two": two,
            "expected_mfe": np.maximum(0.0, np.expm1(regressions[:, 0])),
            "expected_mae": np.maximum(0.0, np.expm1(regressions[:, 1])),
            "expected_time": np.maximum(0.0, np.expm1(regressions[:, 2])),
            "expected_net": regressions[:, 3],
        }


def cross_entropy_multi(labels: np.ndarray, probability: np.ndarray, weights: np.ndarray) -> float:
    value = np.clip(probability[np.arange(len(labels)), labels], 1e-12, 1.0)
    return float(-(weights * np.log(value)).sum() / weights.sum())


def cross_entropy_binary(labels: np.ndarray, probability: np.ndarray, weights: np.ndarray) -> float:
    value = np.clip(probability, 1e-12, 1 - 1e-12)
    return float(-(weights * (labels * np.log(value) + (1 - labels) * np.log(1 - value))).sum() / weights.sum())


def fit_ridge(matrix: sparse.csr_matrix, targets: np.ndarray, weights: np.ndarray, alpha: float) -> np.ndarray:
    root = np.sqrt(weights); weighted = matrix.multiply(root[:, None])
    gram = np.asarray((weighted.T @ weighted).toarray()); rhs = np.asarray(weighted.T @ (targets * root[:, None]))
    penalty = np.eye(matrix.shape[1], dtype=np.float64) * alpha; penalty[0, 0] = 0.0
    return np.linalg.solve(gram + penalty, rhs)


def fit_bundle(data: DataSet, fit_indices: np.ndarray, cal_indices: np.ndarray, family: str, fold: int, categorical_sizes: list[int]) -> ModelBundle:
    fit_cases = data.case_code[fit_indices]; cal_cases = data.case_code[cal_indices]
    fit_weights = case_weights(fit_cases); cal_weights = case_weights(cal_cases)
    transformer = Transformer.fit(family, data.numeric[fit_indices], categorical_sizes, fit_weights)
    x_fit = transformer.transform(data.numeric[fit_indices], data.categorical[fit_indices]); x_cal = transformer.transform(data.numeric[cal_indices], data.categorical[cal_indices])
    y_response = np.asarray([CLASS_INDEX[value] for value in data.primary_class[fit_indices]], dtype=np.int8)
    y_response_cal = np.asarray([CLASS_INDEX[value] for value in data.primary_class[cal_indices]], dtype=np.int8)
    y_two = data.two_r[fit_indices].astype(np.int8); y_two_cal = data.two_r[cal_indices].astype(np.int8)
    choices: list[tuple[float, float, float, Classifier, Classifier]] = []
    for c_value in (0.1, 1.0, 10.0):
        response = fit_adam(x_fit, y_response, fit_weights, 3, c_value, stable_seed(fold, data.timeframe, family, c_value, "response"))
        two = fit_adam(x_fit, y_two, fit_weights, 2, c_value, stable_seed(fold, data.timeframe, family, c_value, "two_r"))
        response_logits = response.logits(x_cal); two_logits = two.logits(x_cal)
        for temperature in (0.75, 1.0, 1.25, 1.5):
            loss = 0.5 * (cross_entropy_multi(y_response_cal, probabilities(response_logits, temperature), cal_weights) + cross_entropy_binary(y_two_cal, probabilities(two_logits, temperature), cal_weights))
            choices.append((loss, c_value, temperature, response, two))
    choices.sort(key=lambda item: (item[0], item[1], item[2])); loss, c_value, temperature, response, two = choices[0]
    transformed_targets = np.column_stack((np.log1p(data.mfe[fit_indices]), np.log1p(data.mae[fit_indices]), np.log1p(data.passage_minutes[fit_indices]), data.terminal_net_r[fit_indices]))
    transformed_cal = np.column_stack((np.log1p(data.mfe[cal_indices]), np.log1p(data.mae[cal_indices]), np.log1p(data.passage_minutes[cal_indices]), data.terminal_net_r[cal_indices]))
    variance = np.average((transformed_targets - np.average(transformed_targets, axis=0, weights=fit_weights)) ** 2, axis=0, weights=fit_weights)
    regression_choices: list[tuple[float, float, np.ndarray]] = []
    for alpha in (1.0, 10.0, 100.0):
        ridge = fit_ridge(x_fit, transformed_targets, fit_weights, alpha); predicted = np.asarray(x_cal @ ridge)
        mse = np.average((predicted - transformed_cal) ** 2, axis=0, weights=cal_weights); score = float(np.mean(mse / np.maximum(variance, 1e-12)))
        regression_choices.append((score, -alpha, ridge))
    regression_choices.sort(key=lambda item: (item[0], item[1])); regression_score, negative_alpha, ridge = regression_choices[0]; alpha = -negative_alpha
    base_rate = float(np.average((y_response == 0).astype(float), weights=fit_weights))
    return ModelBundle(transformer, response, two, temperature, ridge, c_value, alpha, base_rate, {
        "classification_calibration_loss": rounded(loss), "regression_calibration_nmse": rounded(regression_score),
        "c": c_value, "temperature": temperature, "alpha": alpha,
        "fit_rows": len(fit_indices), "fit_cases": len(np.unique(fit_cases)), "calibration_rows": len(cal_indices), "calibration_cases": len(np.unique(cal_cases)),
    })


def bundle_record(bundle: ModelBundle, fold: int, timeframe: str, family: str, policy: Mapping[str, Any] | None, support: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fold": fold, "timeframe": timeframe, "family": family, "status": "FITTED",
        "selection": bundle.selection, "training_base_rate": rounded(bundle.training_base_rate),
        "selected_policy": dict(policy) if policy is not None else None, "support": dict(support),
        "transformer": {
            "feature_names": bundle.transformer.feature_names,
            "clip_low": [rounded(x) for x in bundle.transformer.clip_low],
            "clip_high": [rounded(x) for x in bundle.transformer.clip_high],
            "median": [rounded(x) for x in bundle.transformer.median],
            "mean": [rounded(x) for x in bundle.transformer.mean],
            "std": [rounded(x) for x in bundle.transformer.std],
            "quintiles": [[rounded(x) for x in row] for row in bundle.transformer.quintiles],
            "categorical_sizes": bundle.transformer.categorical_sizes,
        },
        "coefficients": {
            "response": [[rounded(x) for x in row] for row in bundle.response.weights],
            "two_r": [rounded(x) for x in bundle.two_r.weights.reshape(-1)],
            "ridge": [[rounded(x) for x in row] for row in bundle.ridge],
        },
    }


def prediction_schema() -> pa.Schema:
    return pa.schema([
        pa.field("row_id", pa.string(), False), pa.field("pullback_id", pa.string(), False),
        pa.field("timeframe", pa.string(), False), pa.field("decision_date", pa.string(), False),
        pa.field("checkpoint_ns", pa.int64(), False), pa.field("fold", pa.int16(), False),
        pa.field("model_family", pa.string(), False), pa.field("feature_available", pa.bool_(), False),
        pa.field("outcome_available", pa.bool_(), False), pa.field("p_cont", pa.float64()),
        pa.field("p_fail", pa.float64()), pa.field("p_unresolved", pa.float64()), pa.field("p_two", pa.float64()),
        pa.field("expected_mfe", pa.float64()), pa.field("expected_mae", pa.float64()),
        pa.field("expected_time", pa.float64()), pa.field("expected_net", pa.float64()),
        pa.field("training_base_rate", pa.float64(), False),
    ])


class PredictionWriter:
    def __init__(self, path: Path) -> None:
        self.path = path; self.temporary = path.with_suffix(path.suffix + ".tmp")
        if path.exists() or self.temporary.exists():
            raise FileExistsError(path)
        self.writer = pq.ParquetWriter(self.temporary, prediction_schema(), compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6")

    def write(self, data: DataSet, indices: np.ndarray, fold: int, family: str, predictions: Mapping[str, np.ndarray], base_rate: float) -> None:
        available = data.feature_available[indices]
        def nullable(values: np.ndarray) -> list[float | None]:
            return [float(value) if enabled and math.isfinite(float(value)) else None for value, enabled in zip(values, available, strict=True)]
        rows = {
            "row_id": data.row_id[indices].tolist(), "pullback_id": data.pullback_id[indices].tolist(),
            "timeframe": [data.timeframe] * len(indices), "decision_date": [day_string(x) for x in data.decision_day[indices]],
            "checkpoint_ns": data.checkpoint_ns[indices], "fold": np.full(len(indices), fold, dtype=np.int16),
            "model_family": [family] * len(indices), "feature_available": available,
            "outcome_available": data.outcome_available[indices],
            "p_cont": nullable(predictions["p_cont"]), "p_fail": nullable(predictions["p_fail"]),
            "p_unresolved": nullable(predictions["p_unresolved"]), "p_two": nullable(predictions["p_two"]),
            "expected_mfe": nullable(predictions["expected_mfe"]), "expected_mae": nullable(predictions["expected_mae"]),
            "expected_time": nullable(predictions["expected_time"]), "expected_net": nullable(predictions["expected_net"]),
            "training_base_rate": np.full(len(indices), base_rate, dtype=np.float64),
        }
        self.writer.write_table(pa.Table.from_pydict(rows, schema=prediction_schema()), row_group_size=16_384)

    def close(self) -> None:
        self.writer.close(); self.temporary.replace(self.path)


def dense_predictions(data: DataSet, indices: np.ndarray, bundle: ModelBundle) -> dict[str, np.ndarray]:
    result = {name: np.full(len(indices), np.nan, dtype=np.float64) for name in ("p_cont", "p_fail", "p_unresolved", "p_two", "expected_mfe", "expected_mae", "expected_time", "expected_net")}
    available = data.feature_available[indices]; local = np.flatnonzero(available)
    if len(local):
        predicted = bundle.predict(data.numeric[indices[local]], data.categorical[indices[local]])
        for name, values in predicted.items(): result[name][local] = values
    return result


def full_prediction_arrays(data: DataSet, indices: np.ndarray, compact: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    output = {name: np.full(data.n, np.nan, dtype=np.float64) for name in compact}
    for name, values in compact.items(): output[name][indices] = values
    return output


def event_choice(stop_time: int, target_time: int) -> str | None:
    infinity = np.iinfo(np.int64).max
    if stop_time == infinity and target_time == infinity: return None
    return "STRUCTURAL_EXIT" if stop_time <= target_time else "LIQUIDITY_TARGET_EXIT"


def trade_pnl(tranches: Sequence[tuple[int, int, float]], exit_price: int, sign: int, cost_multiplier: float) -> float:
    return float(sum(ounces * (sign * (exit_price - entry) / SCALE - cost_multiplier * cost) for entry, ounces, cost in tranches))


def simulate_case(data: DataSet, row_indices: np.ndarray, prediction: Mapping[str, np.ndarray], grid: Mapping[str, Any], track: str, forced_entry_i: int | None = None) -> dict[str, Any] | None:
    qualify = (
        data.feature_available[row_indices] & data.outcome_available[row_indices]
        & np.isfinite(prediction["p_cont"][row_indices])
        & (prediction["p_cont"][row_indices] >= float(grid["p_cont_min"]))
        & (prediction["p_fail"][row_indices] <= float(grid["p_fail_max"]))
        & (prediction["p_two"][row_indices] >= float(grid["p_two_min"]))
        & (prediction["expected_net"][row_indices] > float(grid["ev_min"]))
    )
    positions = np.flatnonzero(qualify)
    if not len(positions): return None
    if forced_entry_i is None:
        entry_i = int(row_indices[int(positions[0])])
    else:
        matching = np.flatnonzero(row_indices == int(forced_entry_i))
        if not len(matching) or not bool(qualify[int(matching[0])]): return None
        entry_i = int(forced_entry_i)
    sign = int(data.direction_sign[entry_i])
    entry = int(data.entry[entry_i]); stop = int(data.stop[entry_i]); target = int(data.target[entry_i]); cost = float(data.cost[entry_i])
    per_ounce_risk = sign * (entry - stop) / SCALE + cost
    initial_budget = 50.0 if track == "CONSTANT_50" else 12.5
    ounces = math.floor(initial_budget / per_ounce_risk + 1e-12)
    if ounces < 1: return None
    tranches: list[tuple[int, int, float]] = [(entry, ounces, cost)]
    stop_time = int(data.first_stop_ns[entry_i]); stop_fill = int(data.first_stop_fill[entry_i])
    target_time = int(data.first_target_ns[entry_i]); deadline = int(data.deadline_ns[entry_i])
    entry_p = float(prediction["p_cont"][entry_i]); bad_streak = 0; add_signal = False; added = False
    action_counts = Counter({"OPEN_PROBE": 1}); exit_reason = "TIME_EXIT"; exit_price = int(data.terminal_exit_price[entry_i]); exit_time = int(data.terminal_exit_ns[entry_i])
    entry_position = int(np.where(row_indices == entry_i)[0][0])
    for current_i in row_indices[entry_position + 1:]:
        current_i = int(current_i); current_time = int(data.checkpoint_ns[current_i])
        hard = event_choice(stop_time, target_time)
        hard_time = min(stop_time, target_time)
        if hard is not None and hard_time <= current_time:
            exit_reason = hard; exit_time = hard_time; exit_price = stop_fill if hard == "STRUCTURAL_EXIT" else target
            break
        if not data.feature_available[current_i] or not math.isfinite(float(prediction["p_cont"][current_i])):
            action_counts["HOLD"] += 1; continue
        if (not added and float(prediction["p_cont"][current_i]) - entry_p >= float(grid["add_improvement"])
                and float(prediction["expected_net"][current_i]) > 0 and data.outcome_available[current_i]):
            proposed_stop = int(data.stop[current_i]); add_fill = int(data.entry[current_i])
            protective = proposed_stop > stop if sign > 0 else proposed_stop < stop
            adverse = proposed_stop < add_fill if sign > 0 else proposed_stop > add_fill
            if protective and adverse:
                stop = proposed_stop; stop_time = int(data.first_stop_ns[current_i]); stop_fill = int(data.first_stop_fill[current_i])
            add_signal = True; added = True; action_counts["ADD_TO_NORMAL_RISK"] += 1
            if track == "ADAPTIVE_12P5_PLUS_37P5":
                probe_current_loss = ounces * (max(0.0, sign * (entry - stop) / SCALE) + cost)
                remaining = max(0.0, 50.0 - probe_current_loss)
                add_budget = min(37.5, remaining)
                add_cost = float(data.cost[current_i]); add_per_ounce = sign * (add_fill - stop) / SCALE + add_cost
                add_ounces = math.floor(add_budget / add_per_ounce + 1e-12) if add_per_ounce > 0 else 0
                if add_ounces > 0: tranches.append((add_fill, add_ounces, add_cost))
        bad = float(prediction["p_cont"][current_i]) < float(grid["scratch_p"]) or float(prediction["expected_net"][current_i]) <= 0
        bad_streak = bad_streak + 1 if bad else 0
        if bad_streak >= 2 and data.entry[current_i] != np.iinfo(np.int64).min:
            exit_reason = "SCRATCH"; exit_time = current_time; exit_price = int(data.entry[current_i]); action_counts["SCRATCH"] += 1
            break
        action_counts["HOLD"] += 1
    else:
        hard = event_choice(stop_time, target_time)
        if hard is not None and min(stop_time, target_time) <= deadline:
            exit_reason = hard; exit_time = min(stop_time, target_time); exit_price = stop_fill if hard == "STRUCTURAL_EXIT" else target
    pnl_1 = trade_pnl(tranches, exit_price, sign, 1.0); pnl_15 = trade_pnl(tranches, exit_price, sign, 1.5); pnl_2 = trade_pnl(tranches, exit_price, sign, 2.0)
    return {
        "trade_id": canonical_hash([data.pullback_id[entry_i], int(data.checkpoint_ns[entry_i]), grid["grid_id"], track])[:32],
        "pullback_id": str(data.pullback_id[entry_i]), "timeframe": data.timeframe,
        "decision_date": day_string(int(data.decision_day[entry_i])), "entry_ns": int(data.checkpoint_ns[entry_i]), "exit_ns": int(exit_time),
        "entry_session": str(data.session[entry_i]), "grid_id": str(grid["grid_id"]), "track": track,
        "exit_reason": exit_reason, "tranches": len(tranches), "initial_ounces": ounces,
        "total_ounces": sum(value[1] for value in tranches), "add_signal": add_signal,
        "p_cont_entry": rounded(entry_p), "p_fail_entry": rounded(float(prediction["p_fail"][entry_i])),
        "p_two_entry": rounded(float(prediction["p_two"][entry_i])), "expected_net_entry": rounded(float(prediction["expected_net"][entry_i])),
        "pnl_usd_1x": rounded(pnl_1), "pnl_usd_1p5x": rounded(pnl_15), "pnl_usd_2x": rounded(pnl_2),
        "net_r_1x": rounded(pnl_1 / 50.0), "mfe_r": rounded(float(data.mfe[entry_i])), "mae_r": rounded(float(data.mae[entry_i])),
        "stop_then_target": bool(data.stop_then_target[entry_i]), "oracle_r": rounded(data.oracle_r_by_case.get(str(data.pullback_id[entry_i]))),
        "actions": dict(sorted(action_counts.items())),
    }


def enforce_overlap(trades: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    ordered = sorted((dict(row) for row in trades), key=lambda row: (int(row["entry_ns"]), TIMEFRAME_PRIORITY[str(row["timeframe"])], str(row["pullback_id"])))
    selected: list[dict[str, Any]] = []; unavailable_until = np.iinfo(np.int64).min; skipped = 0
    for row in ordered:
        if int(row["entry_ns"]) < unavailable_until:
            skipped += 1; continue
        selected.append(row); unavailable_until = int(row["exit_ns"])
    return selected, skipped


def simulate_policy(data: DataSet, row_mask: np.ndarray, prediction: Mapping[str, np.ndarray], grid: Mapping[str, Any], track: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: list[tuple[np.ndarray, np.ndarray]] = []
    heap: list[tuple[int, str, int, int]] = []
    for begin, end in data.case_ranges(row_mask):
        indices = np.flatnonzero(row_mask[begin:end]) + begin
        qualify = (
            data.feature_available[indices] & data.outcome_available[indices]
            & np.isfinite(prediction["p_cont"][indices])
            & (prediction["p_cont"][indices] >= float(grid["p_cont_min"]))
            & (prediction["p_fail"][indices] <= float(grid["p_fail_max"]))
            & (prediction["p_two"][indices] >= float(grid["p_two_min"]))
            & (prediction["expected_net"][indices] > float(grid["ev_min"]))
        )
        eligible = indices[np.flatnonzero(qualify)]
        if len(eligible):
            case_index = len(cases); cases.append((indices, eligible))
            first = int(eligible[0]); heapq.heappush(heap, (int(data.checkpoint_ns[first]), str(data.pullback_id[first]), case_index, 0))
    selected: list[dict[str, Any]] = []; unavailable_until = np.iinfo(np.int64).min; deferred = 0; exhausted = 0
    while heap:
        entry_time, identity, case_index, position = heapq.heappop(heap); indices, eligible = cases[case_index]
        if entry_time < unavailable_until:
            times = data.checkpoint_ns[eligible]
            next_position = int(np.searchsorted(times, unavailable_until, side="left"))
            deferred += 1
            if next_position < len(eligible):
                next_entry = int(eligible[next_position]); heapq.heappush(heap, (int(data.checkpoint_ns[next_entry]), str(data.pullback_id[next_entry]), case_index, next_position))
            else: exhausted += 1
            continue
        trade = simulate_case(data, indices, prediction, grid, track, int(eligible[position]))
        if trade is None:
            exhausted += 1; continue
        selected.append(trade); unavailable_until = int(trade["exit_ns"])
    return selected, {"eligible_cases": len(cases), "overlap_deferrals": deferred, "overlap_exhausted": exhausted, "selected_trades": len(selected)}


def basic_metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "dates": 0, "expectancy_r": None, "net_pnl_usd": 0.0, "profit_factor": None, "expectancy_1p5x_r": None, "expectancy_2x_r": None}
    pnl = np.asarray([float(row["pnl_usd_1x"]) for row in trades]); pnl15 = np.asarray([float(row["pnl_usd_1p5x"]) for row in trades]); pnl2 = np.asarray([float(row["pnl_usd_2x"]) for row in trades])
    wins = pnl[pnl > 0]; losses = pnl[pnl < 0]; gross_profit = wins.sum(); gross_loss = -losses.sum()
    return {
        "trades": len(trades), "dates": len({str(row["decision_date"]) for row in trades}),
        "win_rate": rounded(float(np.mean(pnl > 0))), "expectancy_r": rounded(float(np.mean(pnl / 50.0))),
        "net_pnl_usd": rounded(float(pnl.sum())), "profit_factor": rounded(float(gross_profit / gross_loss)) if gross_loss > 0 else (1e308 if gross_profit > 0 else None),
        "average_win_usd": rounded(float(wins.mean())) if len(wins) else None, "average_loss_usd": rounded(float(losses.mean())) if len(losses) else None,
        "expectancy_1p5x_r": rounded(float(np.mean(pnl15 / 50.0))), "expectancy_2x_r": rounded(float(np.mean(pnl2 / 50.0))),
    }


def select_policy(data: DataSet, row_mask: np.ndarray, prediction: Mapping[str, np.ndarray], timeframe: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    support = json.loads(PROTOCOL.read_text(encoding="utf-8"))["training"]["minimum_calibration_cases"]
    calibration_support = json.loads(EXECUTION_FREEZE.read_text(encoding="utf-8"))["policy"]["calibration_support"][timeframe]
    records: list[dict[str, Any]] = []
    for grid in policy_grid():
        trades, diagnostics = simulate_policy(data, row_mask, prediction, grid, "CONSTANT_50"); metrics = basic_metrics(trades)
        supported = metrics["trades"] >= int(calibration_support["trades"]) and metrics["dates"] >= int(calibration_support["dates"])
        qualified = supported and metrics["profit_factor"] is not None and metrics["profit_factor"] >= 1.05 and metrics["expectancy_1p5x_r"] is not None and metrics["expectancy_1p5x_r"] > 0
        records.append({"grid": grid, "metrics": metrics, "diagnostics": diagnostics, "supported": supported, "qualified": qualified})
    pool = [row for row in records if row["qualified"]]
    disposition = "QUALIFIED_SELECTION"
    if not pool:
        pool = [row for row in records if row["supported"]]; disposition = "SUPPORTED_FAILURE_SELECTION"
    if not pool:
        return None, {"disposition": "NO_SUPPORTED_POLICY", "tested": len(records), "support_floor": calibration_support, "unused_minimum_calibration_cases": support}
    pool.sort(key=lambda row: (-float(row["metrics"]["expectancy_r"]), str(row["grid"]["grid_id"])))
    chosen = pool[0]
    return dict(chosen["grid"]), {
        "disposition": disposition, "tested": len(records), "qualified": sum(row["qualified"] for row in records),
        "supported": sum(row["supported"] for row in records), "selected_metrics": chosen["metrics"], "selected_diagnostics": chosen["diagnostics"],
    }


def neighbours(grid: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    all_grid = policy_grid(); dimensions = ("p_cont_min", "p_fail_max", "p_two_min", "ev_min", "add_improvement", "scratch_p")
    lookup = {tuple(item[name] for name in dimensions): item for item in all_grid}; current = tuple(grid[name] for name in dimensions)
    result = []
    for index, name in enumerate(dimensions):
        values = sorted({item[name] for item in all_grid}); ordinal = values.index(current[index])
        for delta in (-1, 1):
            target = ordinal + delta
            if 0 <= target < len(values):
                key = list(current); key[index] = values[target]
                result.append((f"{name}:{delta:+d}", dict(lookup[tuple(key)])))
    return result


@dataclass
class CalibrationAccumulator:
    weighted_error: float = 0.0
    weighted_reference_error: float = 0.0
    weight: float = 0.0
    bin_weight: np.ndarray | None = None
    bin_probability: np.ndarray | None = None
    bin_outcome: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.bin_weight is None: self.bin_weight = np.zeros(10, dtype=np.float64)
        if self.bin_probability is None: self.bin_probability = np.zeros(10, dtype=np.float64)
        if self.bin_outcome is None: self.bin_outcome = np.zeros(10, dtype=np.float64)

    def add(self, data: DataSet, indices: np.ndarray, prediction: Mapping[str, np.ndarray], base_rate: float) -> None:
        eligible_local = np.flatnonzero(data.feature_available[indices] & data.outcome_available[indices] & np.isfinite(prediction["p_cont"]))
        if not len(eligible_local): return
        selected = indices[eligible_local]; probability = prediction["p_cont"][eligible_local]
        outcome = (data.primary_class[selected] == "CONTINUATION_1R_FIRST").astype(np.float64)
        weights = case_weights(data.case_code[selected]); total = float(weights.sum())
        self.weight += total; self.weighted_error += float(np.sum(weights * (probability - outcome) ** 2))
        self.weighted_reference_error += float(np.sum(weights * (base_rate - outcome) ** 2))
        bins = np.minimum((probability * 10).astype(np.int8), 9)
        for value in range(10):
            mask = bins == value
            if np.any(mask):
                self.bin_weight[value] += float(weights[mask].sum())
                self.bin_probability[value] += float(np.sum(weights[mask] * probability[mask]))
                self.bin_outcome[value] += float(np.sum(weights[mask] * outcome[mask]))

    def result(self) -> dict[str, Any]:
        if self.weight <= 0: return {"brier": None, "reference_brier": None, "brier_skill": None, "ece": None, "weight": 0}
        brier = self.weighted_error / self.weight; reference = self.weighted_reference_error / self.weight
        ece = 0.0; bins = []
        assert self.bin_weight is not None and self.bin_probability is not None and self.bin_outcome is not None
        for index in range(10):
            weight = float(self.bin_weight[index])
            confidence = float(self.bin_probability[index] / weight) if weight else None
            frequency = float(self.bin_outcome[index] / weight) if weight else None
            if weight: ece += weight / self.weight * abs(confidence - frequency)
            bins.append({"bin": index, "weight": rounded(weight), "mean_probability": rounded(confidence), "observed_frequency": rounded(frequency)})
        return {"brier": rounded(brier), "reference_brier": rounded(reference), "brier_skill": rounded(1.0 - brier / reference) if reference > 0 else None, "ece": rounded(ece), "weight": rounded(self.weight), "bins": bins}


def maximum_drawdown(trades: Sequence[Mapping[str, Any]]) -> float:
    if not trades: return 0.0
    pnl = np.asarray([float(row["pnl_usd_1x"]) for row in sorted(trades, key=lambda row: (int(row["exit_ns"]), str(row["trade_id"])))])
    equity = np.r_[0.0, np.cumsum(pnl)]; peak = np.maximum.accumulate(equity)
    return float(np.max(peak - equity))


def grouped_metrics(trades: Sequence[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in trades: groups[str(row[field])].append(row)
    return [{field: key, **basic_metrics(groups[key])} for key in sorted(groups)]


def cluster_bootstrap(trades: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    if not trades: return {"ci95_low_r": None, "ci95_high_r": None, "one_sided_p": 1.0, "clusters": 0, "resamples": BOOTSTRAPS}
    groups: dict[str, list[float]] = defaultdict(list)
    for row in trades: groups[str(row["decision_date"])].append(float(row["pnl_usd_1x"]) / 50.0)
    keys = sorted(groups); sums = np.asarray([sum(groups[key]) for key in keys]); counts = np.asarray([len(groups[key]) for key in keys], dtype=np.int64)
    rng = np.random.default_rng(seed); values = np.empty(BOOTSTRAPS, dtype=np.float64)
    for begin in range(0, BOOTSTRAPS, 250):
        size = min(250, BOOTSTRAPS - begin); sampled = rng.integers(0, len(keys), size=(size, len(keys)))
        values[begin:begin + size] = sums[sampled].sum(axis=1) / counts[sampled].sum(axis=1)
    return {
        "ci95_low_r": rounded(float(np.quantile(values, 0.025))), "ci95_high_r": rounded(float(np.quantile(values, 0.975))),
        "one_sided_p": rounded(float((np.sum(values <= 0) + 1) / (BOOTSTRAPS + 1))), "clusters": len(keys), "resamples": BOOTSTRAPS,
    }


def positive_contribution_share(rows: Sequence[Mapping[str, Any]]) -> float | None:
    positive = [max(0.0, float(row.get("net_pnl_usd") or 0.0)) for row in rows]; total = sum(positive)
    return max(positive) / total if total > 0 else None


def candidate_summary(trades: Sequence[Mapping[str, Any]], calibration: Mapping[str, Any], neighbour_fraction: float | None, oracle_denominator: float, seed: int) -> dict[str, Any]:
    metrics = basic_metrics(trades); bootstrap = cluster_bootstrap(trades, seed); drawdown = maximum_drawdown(trades)
    years = grouped_metrics(trades, "calendar_year"); folds = grouped_metrics(trades, "fold"); sessions = grouped_metrics(trades, "entry_session")
    action_counts = Counter()
    for row in trades: action_counts.update(row.get("actions") or {})
    metrics.update({
        "bootstrap": bootstrap, "maximum_drawdown_usd": rounded(drawdown), "maximum_drawdown_pct": rounded(drawdown / 100.0),
        "average_monthly_pnl_usd": rounded(float(metrics["net_pnl_usd"]) / 39.0),
        "required_linear_risk_scale_to_1000_month": rounded(1000.0 / (float(metrics["net_pnl_usd"]) / 39.0)) if float(metrics["net_pnl_usd"]) > 0 else None,
        "oracle_denominator_usd": rounded(oracle_denominator), "oracle_retained_pct": rounded(100.0 * float(metrics["net_pnl_usd"]) / oracle_denominator) if oracle_denominator > 0 else None,
        "average_mfe_r": rounded(float(np.mean([float(row["mfe_r"]) for row in trades]))) if trades else None,
        "average_mae_r": rounded(float(np.mean([float(row["mae_r"]) for row in trades]))) if trades else None,
        "stopped_then_target_rate": rounded(float(np.mean([row["exit_reason"] == "STRUCTURAL_EXIT" and bool(row["stop_then_target"]) for row in trades]))) if trades else None,
        "average_holding_minutes": rounded(float(np.mean([(int(row["exit_ns"]) - int(row["entry_ns"])) / 60_000_000_000 for row in trades]))) if trades else None,
        "folds": folds, "years": years, "sessions": sessions,
        "positive_validation_folds": sum(row["expectancy_r"] is not None and float(row["expectancy_r"]) > 0 for row in folds),
        "positive_calendar_years": sum(row["expectancy_r"] is not None and float(row["expectancy_r"]) > 0 for row in years),
        "maximum_positive_year_share": rounded(positive_contribution_share(years)), "maximum_positive_session_share": rounded(positive_contribution_share(sessions)),
        "policy_neighbour_positive_fraction": rounded(neighbour_fraction), "calibration": dict(calibration), "action_counts": dict(sorted(action_counts.items())),
        "risk_scaling_to_1000_permitted": bool(
            float(metrics["net_pnl_usd"]) > 0
            and 1000.0 / (float(metrics["net_pnl_usd"]) / 39.0) <= 1.0
            and drawdown * (1000.0 / (float(metrics["net_pnl_usd"]) / 39.0)) <= 1500.0
        ),
    })
    return metrics


def holm_adjust(candidates: list[dict[str, Any]]) -> None:
    ordered = sorted(enumerate(candidates), key=lambda item: (float(item[1]["metrics"]["bootstrap"]["one_sided_p"]), str(item[1]["candidate_id"])))
    running = 0.0; m = len(candidates)
    for rank, (index, candidate) in enumerate(ordered):
        raw = float(candidate["metrics"]["bootstrap"]["one_sided_p"]); adjusted = min(1.0, (m - rank) * raw); running = max(running, adjusted)
        candidates[index]["metrics"]["holm_adjusted_p"] = rounded(running)


def apply_gates(candidate: dict[str, Any], support_floor: Mapping[str, Any]) -> None:
    m = candidate["metrics"]; calibration = m["calibration"]
    gates = {
        "support_trades": int(m["trades"]) >= int(support_floor["trades"]),
        "support_dates": int(m["dates"]) >= int(support_floor["dates"]),
        "positive_net_expectancy": m["expectancy_r"] is not None and float(m["expectancy_r"]) > 0,
        "profit_factor_gte_1p10": m["profit_factor"] is not None and float(m["profit_factor"]) >= 1.10,
        "cluster_ci95_low_gt_zero": m["bootstrap"]["ci95_low_r"] is not None and float(m["bootstrap"]["ci95_low_r"]) > 0,
        "holm_p_lte_0p10": m.get("holm_adjusted_p") is not None and float(m["holm_adjusted_p"]) <= 0.10,
        "positive_1p5x_cost_expectancy": m["expectancy_1p5x_r"] is not None and float(m["expectancy_1p5x_r"]) > 0,
        "positive_validation_folds_gte_3": int(m["positive_validation_folds"]) >= 3,
        "positive_calendar_years_gte_2": int(m["positive_calendar_years"]) >= 2,
        "maximum_positive_year_share_lte_0p70": m["maximum_positive_year_share"] is not None and float(m["maximum_positive_year_share"]) <= 0.70,
        "maximum_positive_session_share_lte_0p70": m["maximum_positive_session_share"] is not None and float(m["maximum_positive_session_share"]) <= 0.70,
        "brier_skill_gt_zero": calibration.get("brier_skill") is not None and float(calibration["brier_skill"]) > 0,
        "ece_lte_0p10": calibration.get("ece") is not None and float(calibration["ece"]) <= 0.10,
        "positive_policy_neighbour_fraction_gte_0p60": m["policy_neighbour_positive_fraction"] is not None and float(m["policy_neighbour_positive_fraction"]) >= 0.60,
        "maximum_drawdown_lte_15pct": float(m["maximum_drawdown_pct"]) <= 15.0,
    }
    candidate["gates"] = gates; candidate["failed_gates"] = [name for name, passed in gates.items() if not passed]
    candidate["verdict"] = "PASS" if all(gates.values()) else "REJECT"


def oracle_denominator(data: DataSet, validation_mask: np.ndarray) -> float:
    identities = {str(value) for value in data.pullback_id[np.flatnonzero(validation_mask)]}
    return 50.0 * sum(data.oracle_r_by_case.get(identity, 0.0) for identity in identities)


def serialize_trades(path: Path, trades: Sequence[Mapping[str, Any]]) -> None:
    rows = []
    for raw in sorted(trades, key=lambda row: (str(row["candidate_id"]), int(row["entry_ns"]), str(row["pullback_id"]))):
        row = dict(raw); row["actions_json"] = canonical_json(row.pop("actions", {})); rows.append(row)
    table = pa.Table.from_pylist(rows) if rows else pa.table({"candidate_id": pa.array([], type=pa.string())})
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=16_384)
    temporary.replace(path)


def write_model_records(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    write_json_exclusive(path, {"version": "GOLD_PIT_V1_FOLD_MODELS_1_0", "records": list(records)})


def annotate_trades(trades: Sequence[dict[str, Any]], fold: int, family: str, candidate_id: str) -> None:
    for row in trades:
        row["fold"] = fold; row["model_family"] = family; row["candidate_id"] = candidate_id
        row["calendar_year"] = int(str(row["decision_date"])[:4])


def run_pass(label: str, protocol: Mapping[str, Any]) -> dict[str, Any]:
    print(canonical_json({"status": "PASS_STARTED", "implementation": label, "at": utc_now()}), flush=True)
    vocab = global_vocabularies(); categorical_sizes = [len(vocab[name]) for name in CATEGORICAL]
    prediction_path = OUTPUT / f"{label}_oof_predictions.parquet"; writer = PredictionWriter(prediction_path)
    candidate_trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
    neighbour_trades: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    calibration: dict[tuple[str, str], CalibrationAccumulator] = {(timeframe, family): CalibrationAccumulator() for timeframe in TIMEFRAMES for family in MODEL_FAMILIES}
    model_records: list[dict[str, Any]] = []; support_failures: list[dict[str, Any]] = []; oracle_by_timeframe: dict[str, float] = {}
    fold_specs = [(int(item["fold"]), day_int(item["validate"][0]), day_int(item["validate"][1])) for item in protocol["folds"]]
    try:
        for timeframe in TIMEFRAMES:
            print(canonical_json({"status": "LOADING_TIMEFRAME", "implementation": label, "timeframe": timeframe, "at": utc_now()}), flush=True)
            data = load_timeframe(timeframe, vocab)
            all_validation = np.zeros(data.n, dtype=bool)
            for _, start, end in fold_specs: all_validation |= (data.decision_day >= start) & (data.decision_day <= end)
            oracle_by_timeframe[timeframe] = oracle_denominator(data, all_validation)
            for fold, validation_start, validation_end in fold_specs:
                training_days = np.unique(data.decision_day[data.decision_day < validation_start])
                fit_days, cal_days = split_training_dates(training_days, 0.2)
                training_eligible = data.training_checkpoint & data.feature_available & data.outcome_available
                fit_indices = np.flatnonzero(training_eligible & np.isin(data.decision_day, fit_days))
                cal_indices = np.flatnonzero(training_eligible & np.isin(data.decision_day, cal_days))
                calibration_all_indices = np.flatnonzero(np.isin(data.decision_day, cal_days))
                validation_indices = np.flatnonzero((data.decision_day >= validation_start) & (data.decision_day <= validation_end))
                fit_cases = len(np.unique(data.case_code[fit_indices])); cal_cases = len(np.unique(data.case_code[cal_indices]))
                required_fit = int(protocol["training"]["minimum_fit_cases"][timeframe]); required_cal = int(protocol["training"]["minimum_calibration_cases"][timeframe])
                support = {
                    "outer_training_dates": len(training_days), "fit_dates": len(fit_days), "calibration_dates": len(cal_days),
                    "fit_rows": len(fit_indices), "fit_cases": fit_cases, "calibration_rows": len(cal_indices), "calibration_cases": cal_cases,
                    "validation_rows": len(validation_indices), "required_fit_cases": required_fit, "required_calibration_cases": required_cal,
                }
                if fit_cases < required_fit or cal_cases < required_cal:
                    for family in MODEL_FAMILIES:
                        failure = {"fold": fold, "timeframe": timeframe, "family": family, "status": "SUPPORT_FAIL", "support": support}
                        support_failures.append(failure); model_records.append(failure)
                    print(canonical_json({"status": "FOLD_SUPPORT_FAIL", "implementation": label, "timeframe": timeframe, "fold": fold, **support}), flush=True)
                    continue
                for family in MODEL_FAMILIES:
                    print(canonical_json({"status": "FITTING", "implementation": label, "timeframe": timeframe, "fold": fold, "family": family, "at": utc_now()}), flush=True)
                    bundle = fit_bundle(data, fit_indices, cal_indices, family, fold, categorical_sizes)
                    compact_cal = dense_predictions(data, calibration_all_indices, bundle); full_cal = full_prediction_arrays(data, calibration_all_indices, compact_cal)
                    calibration_mask = np.zeros(data.n, dtype=bool); calibration_mask[calibration_all_indices] = True
                    selected_grid, selection_record = select_policy(data, calibration_mask, full_cal, timeframe)
                    compact_validation = dense_predictions(data, validation_indices, bundle)
                    writer.write(data, validation_indices, fold, family, compact_validation, bundle.training_base_rate)
                    calibration[(timeframe, family)].add(data, validation_indices, compact_validation, bundle.training_base_rate)
                    full_validation = full_prediction_arrays(data, validation_indices, compact_validation)
                    validation_mask = np.zeros(data.n, dtype=bool); validation_mask[validation_indices] = True
                    if selected_grid is not None:
                        for track in TRACKS:
                            candidate_id = f"{timeframe}::{family}::{track}"
                            trades, _diagnostics = simulate_policy(data, validation_mask, full_validation, selected_grid, track)
                            annotate_trades(trades, fold, family, candidate_id); candidate_trades[candidate_id].extend(trades)
                            for neighbour_label, neighbour_grid in neighbours(selected_grid):
                                nearby, _ = simulate_policy(data, validation_mask, full_validation, neighbour_grid, track)
                                annotate_trades(nearby, fold, family, candidate_id); neighbour_trades[(candidate_id, neighbour_label)].extend(nearby)
                    model_records.append(bundle_record(bundle, fold, timeframe, family, selected_grid, {**support, "policy_selection": selection_record}))
                    print(canonical_json({"status": "FOLD_FAMILY_COMPLETE", "implementation": label, "timeframe": timeframe, "fold": fold, "family": family, "policy": selected_grid["grid_id"] if selected_grid else None, "at": utc_now()}), flush=True)
                    del compact_cal, full_cal, compact_validation, full_validation, bundle
            del data
    finally:
        writer.close()

    all_trades: list[dict[str, Any]] = []; candidates: list[dict[str, Any]] = []
    for timeframe in TIMEFRAMES:
        timeframe_candidates: list[dict[str, Any]] = []
        for family in MODEL_FAMILIES:
            calibration_metrics = calibration[(timeframe, family)].result()
            for track in TRACKS:
                candidate_id = f"{timeframe}::{family}::{track}"
                trades, overlap_skipped = enforce_overlap(candidate_trades.get(candidate_id, []))
                for row in trades: row["final_overlap_retained"] = True
                all_trades.extend(trades)
                neighbour_results = []
                for (identity, neighbour_label), values in sorted(neighbour_trades.items()):
                    if identity != candidate_id: continue
                    retained, _ = enforce_overlap(values); neighbour_results.append({"neighbour": neighbour_label, **basic_metrics(retained)})
                fraction = (sum(row["expectancy_r"] is not None and float(row["expectancy_r"]) > 0 for row in neighbour_results) / len(neighbour_results)) if neighbour_results else None
                metrics = candidate_summary(trades, calibration_metrics, fraction, oracle_by_timeframe[timeframe], stable_seed(candidate_id, "bootstrap"))
                metrics["final_overlap_skipped"] = overlap_skipped; metrics["neighbours"] = neighbour_results
                candidate = {"candidate_id": candidate_id, "timeframe": timeframe, "model_family": family, "track": track, "metrics": metrics}
                timeframe_candidates.append(candidate)
        holm_adjust(timeframe_candidates)
        for candidate in timeframe_candidates: apply_gates(candidate, protocol["support_floors"][timeframe])
        passing = [candidate for candidate in timeframe_candidates if candidate["verdict"] == "PASS"]
        passing.sort(key=lambda row: (-float(row["metrics"]["expectancy_r"]), -float(row["metrics"]["profit_factor"]), -int(row["metrics"]["trades"]), str(row["candidate_id"])))
        for candidate in passing[2:]:
            candidate["verdict"] = "REJECT_CANDIDATE_LIMIT"; candidate["failed_gates"].append("maximum_two_candidates_per_timeframe")
        candidates.extend(timeframe_candidates)
    candidates.sort(key=lambda row: (TIMEFRAMES.index(str(row["timeframe"])), MODEL_FAMILIES.index(str(row["model_family"])), TRACKS.index(str(row["track"]))))
    results = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_DEVELOPMENT_RESULTS_1_0", "implementation": label,
        "status": "PASS_DEVELOPMENT_EVALUATION_COMPLETED", "completed_at_utc": utc_now(),
        "candidates": candidates, "passing_candidates": [row["candidate_id"] for row in candidates if row["verdict"] == "PASS"],
        "support_failures": support_failures, "oracle_denominator_by_timeframe_usd": {key: rounded(value) for key, value in oracle_by_timeframe.items()},
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    trade_path = OUTPUT / f"{label}_oof_trades.parquet"; model_path = OUTPUT / f"{label}_fold_models.json"; result_path = OUTPUT / f"{label}_results.json"
    serialize_trades(trade_path, all_trades); write_model_records(model_path, model_records); write_json_exclusive(result_path, results)
    results["artifacts"] = {"predictions": file_record(prediction_path), "trades": file_record(trade_path), "models": file_record(model_path), "results": file_record(result_path)}
    return results


def result_without_nondeterminism(result: Mapping[str, Any]) -> dict[str, Any]:
    output = json.loads(canonical_json(result)); output.pop("completed_at_utc", None); output.pop("implementation", None); output.pop("artifacts", None)
    return output


def report_markdown(result: Mapping[str, Any], reproduction: Mapping[str, Any]) -> str:
    lines = [
        "# Gold Point-in-Time Auction-State and Adaptive Management V1 — Development Verdict", "",
        f"Status: **{result['development_verdict']}**", "",
        "The figures below are strictly out-of-fold 2021–2024 development evidence. Calendar 2025 and 2026 remained locked.", "",
        "| Candidate | Trades | Win rate | Exp. R | PF | Net PnL | Avg/month | Max DD | Brier skill | ECE | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["candidates"]:
        m = row["metrics"]; cal = m["calibration"]
        lines.append(f"| {row['candidate_id']} | {m['trades']} | {m.get('win_rate')} | {m.get('expectancy_r')} | {m.get('profit_factor')} | ${m.get('net_pnl_usd')} | ${m.get('average_monthly_pnl_usd')} | ${m.get('maximum_drawdown_usd')} | {cal.get('brier_skill')} | {cal.get('ece')} | {row['verdict']} |")
    lines.extend(["", "## Reproduction", "", f"Primary/reference exact result agreement: **{reproduction['result_equal']}**.", f"Prediction files byte-identical: **{reproduction['predictions_byte_identical']}**.", f"Trade files byte-identical: **{reproduction['trades_byte_identical']}**.", "", "## Forward disposition", ""])
    if result["passing_candidates"]:
        lines.append("At least one development candidate passed. Its complete development system must be frozen before the one-time exposed 2025/2026 robustness run.")
    else:
        lines.append("No development candidate passed every frozen economic and robustness gate. Calendar 2025/2026 therefore remains locked and no prospective ledger is initialized.")
    return "\n".join(lines) + "\n"


def main() -> None:
    protocol, _execution, _outcome = preflight(); OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(IMPLEMENTATION_FREEZE, implementation_policy())
    primary = run_pass("primary", protocol)
    reference = run_pass("reference", protocol)
    primary_result_path = OUTPUT / "primary_results.json"; reference_result_path = OUTPUT / "reference_results.json"
    result_equal = result_without_nondeterminism(primary) == result_without_nondeterminism(reference)
    reproduction = {
        "result_equal": result_equal,
        "predictions_byte_identical": sha256_file(OUTPUT / "primary_oof_predictions.parquet") == sha256_file(OUTPUT / "reference_oof_predictions.parquet"),
        "trades_byte_identical": sha256_file(OUTPUT / "primary_oof_trades.parquet") == sha256_file(OUTPUT / "reference_oof_trades.parquet"),
        "models_equal": json.loads((OUTPUT / "primary_fold_models.json").read_text(encoding="utf-8")) == json.loads((OUTPUT / "reference_fold_models.json").read_text(encoding="utf-8")),
    }
    if not all(reproduction.values()): raise ValueError(f"Independent development reproduction failed: {reproduction}")
    passing = list(primary["passing_candidates"]); verdict = "PASS_DEVELOPMENT_ECONOMIC_EDGE" if passing else "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE"
    final = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_FINAL_DEVELOPMENT_1_0", "status": "PASS_INDEPENDENT_DEVELOPMENT_REPRODUCTION",
        "development_verdict": verdict, "completed_at_utc": utc_now(), "candidates": primary["candidates"], "passing_candidates": passing,
        "reproduction": reproduction, "forward_disposition": "FREEZE_AND_OPEN_EXPOSED_FORWARD" if passing else "KEEP_2025_2026_LOCKED",
        "gc_incremental_disposition": "PENDING_SEPARATE_COVERED_SUBSET_EVALUATION_WITH_NO_STANDALONE_CREDIT",
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    report = ROOT / "GOLD_POINT_IN_TIME_AUCTION_STATE_AND_ADAPTIVE_MANAGEMENT_V1_DEVELOPMENT_RESULTS.md"
    report.write_text(report_markdown(final, reproduction), encoding="utf-8", newline="\n")
    final["artifacts"] = {
        "implementation_freeze": file_record(IMPLEMENTATION_FREEZE), "primary_results": file_record(primary_result_path),
        "reference_results": file_record(reference_result_path), "primary_predictions": file_record(OUTPUT / "primary_oof_predictions.parquet"),
        "reference_predictions": file_record(OUTPUT / "reference_oof_predictions.parquet"), "primary_trades": file_record(OUTPUT / "primary_oof_trades.parquet"),
        "reference_trades": file_record(OUTPUT / "reference_oof_trades.parquet"), "report": file_record(report),
    }
    write_json_exclusive(OUTPUT / "development_results.json", final); final["artifacts"]["development_results"] = file_record(OUTPUT / "development_results.json")
    write_json_exclusive(FINAL_FREEZE, final)
    print(canonical_json({"status": "COMPLETE", "development_verdict": verdict, "passing_candidates": passing, "reproduction": reproduction}), flush=True)


if __name__ == "__main__":
    main()
