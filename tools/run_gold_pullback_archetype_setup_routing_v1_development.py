from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import discover_gold_trend_pullback_movement_anatomy_edge_v1 as execution  # noqa: E402
import materialize_gold_trend_pullback_continuation_edge_v1 as feature_impl  # noqa: E402
import materialize_gold_trend_pullback_movement_anatomy_edge_v1 as anatomy_impl  # noqa: E402
import run_gold_trend_pullback_continuation_economic_v1_development as econ  # noqa: E402


ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"
CONTRACT = ROOT / "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_AND_RISK_ALLOCATION_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_pullback_archetype_setup_routing_v1_protocol.json"
PRE_FREEZE = MANIFESTS / "gold_pullback_archetype_setup_routing_v1_preperformance_freeze.json"
IMPLEMENTATION_FREEZE = MANIFESTS / "gold_pullback_archetype_setup_routing_v1_implementation_freeze.json"
IMPLEMENTATION_CORRECTION = MANIFESTS / "gold_pullback_archetype_setup_routing_v1_implementation_correction_a.json"
IMPLEMENTATION_CORRECTION_B = MANIFESTS / "gold_pullback_archetype_setup_routing_v1_implementation_correction_b.json"
REPORT = ROOT / "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_AND_RISK_ALLOCATION_V1_DEVELOPMENT_R1.md"

ARCHETYPE_DIR = ARTIFACTS / "gold_pullback_behavioural_archetypes_v1"
FEATURE_DIR = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
ANATOMY_DIR = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
CENSUS_DIR = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"

TIMEFRAMES = ("M15", "H1", "H4")
TF_MINUTES = {"M15": 15, "H1": 60, "H4": 240}
TIMEFRAME_PRIORITY = {"H4": 0, "H1": 1, "M15": 2}
CLASSES = (
    "RUNAWAY_CONTINUATION",
    "BREAK_RETEST_CONTINUATION",
    "DEEP_RETRACE_CONTINUATION",
    "FALSE_CONTINUATION",
    "IMMEDIATE_FAILURE",
    "TWO_SIDED_CHOPPY",
)
CLASS_INDEX = {name: index for index, name in enumerate(CLASSES)}
SCALE = 100_000_000

FOLDS = (
    (1, "2021-08-01", "2022-06-30", "2022-07-01", "2023-03-31"),
    (2, "2021-08-01", "2023-03-31", "2023-04-01", "2023-12-31"),
    (3, "2021-08-01", "2023-12-31", "2024-01-01", "2024-12-31"),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def ns(value: str) -> int:
    return int(parse_dt(value).timestamp() * 1_000_000_000)


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).isoformat().replace("+00:00", "Z")


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    output = round(float(value), 12)
    return 0.0 if output == 0 else output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    table = pa.Table.from_pylist(list(rows))
    temporary = path.with_suffix(path.suffix + ".tmp")
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


def verify_freezes() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    freeze = json.loads(PRE_FREEZE.read_text(encoding="utf-8"))
    implementation = json.loads(IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
    correction = json.loads(IMPLEMENTATION_CORRECTION.read_text(encoding="utf-8"))
    correction_b = json.loads(IMPLEMENTATION_CORRECTION_B.read_text(encoding="utf-8"))
    expected = "FROZEN_BEFORE_NEW_MODEL_BY_ARCHETYPE_PERFORMANCE_MEASUREMENT"
    if protocol["status"] != expected or freeze["status"] != expected:
        raise ValueError("Routing protocol is not frozen")
    if implementation["status"] != "FROZEN_BEFORE_DEVELOPMENT_PAYOFF_OR_CLASSIFICATION_CALCULATION":
        raise ValueError("Implementation registry is not frozen")
    if correction["status"] != "FROZEN_BEFORE_FIRST_PERFORMANCE_RESULT" or correction["outcomes_measured_before_correction"]:
        raise ValueError("Implementation correction record is invalid")
    if correction_b["status"] != "FROZEN_BEFORE_CORRECTED_DEVELOPMENT_RERUN" or correction_b["calendar_2025_values_accessed"] or correction_b["calendar_2026_values_accessed"]:
        raise ValueError("Second implementation correction record is invalid")
    failed_path = ROOT / correction_b["preserved_failed_result"]["path"]
    if not failed_path.is_file() or sha256_file(failed_path) != correction_b["preserved_failed_result"]["sha256"]:
        raise ValueError("Preserved failed development result changed")
    for item in [*freeze["controls"].values(), *freeze["sources"].values()]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Frozen input changed: {item['path']}")
    if sha256_file(CONTRACT) != freeze["controls"]["contract"]["sha256"]:
        raise ValueError("Contract changed after freeze")
    if sha256_file(PROTOCOL) != freeze["controls"]["protocol"]["sha256"]:
        raise ValueError("Protocol changed after freeze")
    return protocol, freeze, implementation


def load_rows(implementation: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
    archetypes = pq.read_table(ARCHETYPE_DIR / f"{implementation}_archetypes.parquet").to_pylist()
    features = pq.read_table(FEATURE_DIR / f"{implementation}_features.parquet").to_pylist()
    anatomy = pq.read_table(ANATOMY_DIR / f"{implementation}_movement_anatomy.parquet").to_pylist()
    triggers = pq.read_table(ANATOMY_DIR / f"{implementation}_trigger_facts.parquet").to_pylist()
    cases = pq.read_table(CENSUS_DIR / f"{implementation}_pullback_cases.parquet").to_pylist()
    feature_map = {str(row["pullback_id"]): row for row in features}
    anatomy_map = {str(row["pullback_id"]): row for row in anatomy}
    trigger_map = {(str(row["pullback_id"]), str(row["trigger"])): row for row in triggers}
    case_map = {str(row["pullback_id"]): row for row in cases}
    if len(archetypes) != 8_653 or len({str(row["pullback_id"]) for row in archetypes}) != 8_653:
        raise ValueError("Archetype population changed")
    if sum(bool(row["technical_available"]) for row in archetypes) != 8_205:
        raise ValueError("Archetype technical coverage changed")
    for row in archetypes:
        identity = str(row["pullback_id"])
        if identity not in feature_map or identity not in anatomy_map or identity not in case_map:
            raise ValueError(f"Missing predecessor row: {identity}")
    archetypes.sort(key=lambda row: (str(row["known_at_utc"]), TIMEFRAME_PRIORITY[str(row["timeframe"])], str(row["pullback_id"])))
    return archetypes, feature_map, anatomy_map, trigger_map, case_map


def model_specification(model: Mapping[str, Any]) -> str:
    return execution.spec_code(
        str(model["trigger"]),
        str(model["stop"]),
        str(model["target"]),
        int(model["time_exit_parent_bars"]),
    )


def no_trade_for_model(case: Mapping[str, Any], model: Mapping[str, Any], reason: str) -> dict[str, Any]:
    specification = f"{model['trigger']}::{model['stop']}::{model['target']}::TIME_{model['time_exit_parent_bars']}_PARENT_BARS"
    return execution.no_trade(case, specification, reason)


def reverse_trigger(
    case: Mapping[str, Any],
    immediate: Mapping[str, Any],
    prices: anatomy_impl.PriceData,
    max_delay_minutes: int,
) -> dict[str, Any] | None:
    resolved = case.get("resolved_at_utc")
    if not resolved:
        return None
    resolved_ns = ns(str(resolved))
    index = int(np.searchsorted(prices.open_ns, resolved_ns, side="left"))
    if index >= len(prices.open_ns):
        return None
    delay = (int(prices.open_ns[index]) - resolved_ns) / 60_000_000_000
    if delay < 0 or delay > max_delay_minutes:
        return None
    spread = float(prices.spread[index])
    spread_value = None if not math.isfinite(spread) or spread < 0 else spread
    return {
        "pullback_id": case["pullback_id"],
        "timeframe": case["timeframe"],
        "direction": "DOWN" if case["direction"] == "UP" else "UP",
        "known_at_utc": case["known_at_utc"],
        "trigger": "OPPOSING_STRUCTURE_SWITCH",
        "status": "FORMED",
        "reason": "",
        "entry_index": index,
        "entry_at_utc": ns_iso(int(prices.open_ns[index])),
        "entry_e8": int(prices.open_e8[index]),
        "entry_delay_minutes": rounded((int(prices.open_ns[index]) - ns(str(case["known_at_utc"]))) / 60_000_000_000),
        "entry_spread_usd_oz": spread_value,
        "confirmation_high_e8": int(immediate["confirmation_high_e8"]),
        "confirmation_low_e8": int(immediate["confirmation_low_e8"]),
        "decision_close_e8": int(immediate["decision_close_e8"]),
        "pivot_price_e8": int(case["pivot_price_e8"]),
        "reference_level_e8": int(case["reference_level_e8"]),
        "atr14_e8": float(case["atr14_e8"]),
        "trigger_lineage_hash": canonical_hash([
            case["decision_facts_hash"],
            "OPPOSING_STRUCTURE_SWITCH",
            case["resolved_at_utc"],
            index,
            int(prices.open_e8[index]),
        ]),
    }


def checkpoint_signal(
    archetype_row: Mapping[str, Any],
    feature: Mapping[str, Any],
    anatomy: Mapping[str, Any],
    model: Mapping[str, Any],
    trigger: Mapping[str, Any] | None,
    trade: Mapping[str, Any],
) -> dict[str, Any]:
    entry_at = trade.get("entry_at_utc") or (trigger.get("entry_at_utc") if trigger else None)
    entry_e8 = trade.get("entry_e8") if trade.get("entry_e8") is not None else (trigger.get("entry_e8") if trigger else None)
    original_sign = 1 if str(archetype_row["direction"]) == "UP" else -1
    atr = float(feature["atr14_e8"])
    decision_close = trigger.get("decision_close_e8") if trigger else None
    pivot = trigger.get("pivot_price_e8") if trigger else None
    known = str(archetype_row["known_at_utc"])
    delay_parent = None
    checkpoint_session = "UNKNOWN"
    if entry_at:
        delay_parent = (parse_dt(str(entry_at)) - parse_dt(known)).total_seconds() / 60 / TF_MINUTES[str(archetype_row["timeframe"])]
        checkpoint_session = feature_impl.session_state(parse_dt(str(entry_at)))
    htf_known = int(feature.get("higher_timeframe_known_count") or 0)
    htf_fraction = (int(feature.get("higher_timeframe_alignment_count") or 0) / htf_known) if htf_known else None
    signal = dict(feature)
    signal.update({
        "model_id": str(model["model_id"]),
        "intended_archetype": str(model["intended_archetype"]),
        "archetype": str(archetype_row["archetype"]),
        "technical_available": bool(archetype_row["technical_available"]),
        "pullback_id": str(archetype_row["pullback_id"]),
        "timeframe": str(archetype_row["timeframe"]),
        "known_at_utc": known,
        "checkpoint_at_utc": entry_at,
        "checkpoint_session_state": checkpoint_session,
        "checkpoint_delay_parent_bars": rounded(delay_parent),
        "checkpoint_entry_progress_atr": rounded(original_sign * (int(entry_e8) - int(decision_close)) / atr) if entry_e8 is not None and decision_close is not None else None,
        "checkpoint_distance_from_pivot_atr": rounded(original_sign * (int(entry_e8) - int(pivot)) / atr) if entry_e8 is not None and pivot is not None else None,
        "higher_timeframe_alignment_fraction": rounded(htf_fraction),
        "barrier_0p5_order_observed_by_resolution": anatomy.get("barrier_0p5_order"),
        "trade_status": str(trade["status"]),
        "trade_no_trade_reason": str(trade["no_trade_reason"]),
    })
    return signal


def build_model_trades(
    implementation: str,
    protocol: Mapping[str, Any],
    rows: tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]],
    prices: anatomy_impl.PriceData,
    swings: Mapping[str, Sequence[Mapping[str, Any]]],
    broken_at: Mapping[str, datetime],
    reverse_delay: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    archetypes, features, anatomies, triggers, cases = rows
    trades: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    for archetype_row in archetypes:
        pullback_id = str(archetype_row["pullback_id"])
        feature = features[pullback_id]
        anatomy = anatomies[pullback_id]
        census = cases[pullback_id]
        case = dict(feature)
        case.update({
            "pivot_price_e8": int(census["pivot_price_e8"]),
            "reference_level_e8": int(census["reference_level_e8"]),
            "resolution": str(census["resolution"]),
            "resolved_at_utc": census.get("resolved_at_utc"),
            "decision_facts_hash": str(census["decision_facts_hash"]),
        })
        immediate = triggers.get((pullback_id, "IMMEDIATE"))
        confirmation_break = triggers.get((pullback_id, "CONFIRMATION_EXTREME_BREAK"))
        for model in protocol["entry_models"]:
            model_id = str(model["model_id"])
            trigger: dict[str, Any] | None = None
            simulation_case = dict(case)
            if model["trade_direction"] == "TREND":
                trigger = triggers.get((pullback_id, str(model["trigger"])))
                result = execution.simulate_core(
                    simulation_case,
                    trigger,
                    str(model["stop"]),
                    str(model["target"]),
                    prices,
                    swings,
                    broken_at,
                    implementation,
                )[int(model["time_exit_parent_bars"])]
            else:
                if census["resolution"] != "FAILED_STRUCTURE_SWITCH" or immediate is None:
                    result = no_trade_for_model(simulation_case, model, "NO_OPPOSING_STRUCTURE_SWITCH")
                else:
                    resolved_at = str(census.get("resolved_at_utc") or "")
                    break_before_switch = bool(
                        confirmation_break
                        and confirmation_break["status"] == "FORMED"
                        and confirmation_break.get("entry_at_utc")
                        and str(confirmation_break["entry_at_utc"]) <= resolved_at
                    )
                    required_break_state = model_id == "FALSE_CONTINUATION_REVERSAL"
                    if break_before_switch != required_break_state:
                        reason = "PRIOR_CONFIRMATION_BREAK_REQUIRED" if required_break_state else "PRIOR_CONFIRMATION_BREAK_PRESENT"
                        result = no_trade_for_model(simulation_case, model, reason)
                    else:
                        trigger = reverse_trigger(simulation_case, immediate, prices, reverse_delay)
                        if trigger is None:
                            result = no_trade_for_model(simulation_case, model, "NO_M1_OPEN_WITHIN_REVERSE_CHECKPOINT_DELAY")
                        else:
                            simulation_case["direction"] = trigger["direction"]
                            result = execution.simulate_core(
                                simulation_case,
                                trigger,
                                str(model["stop"]),
                                str(model["target"]),
                                prices,
                                swings,
                                broken_at,
                                implementation,
                            )[int(model["time_exit_parent_bars"])]
            result = dict(result)
            result.update({
                "trade_id": f"GPAR-{canonical_hash([model_id, pullback_id, result.get('entry_at_utc')])[:24]}",
                "model_id": model_id,
                "intended_archetype": str(model["intended_archetype"]),
                "archetype": str(archetype_row["archetype"]),
                "technical_available": bool(archetype_row["technical_available"]),
                "original_direction": str(archetype_row["direction"]),
                "trade_direction": str(simulation_case["direction"]),
                "session_state": str(feature["session_state"]),
                "calendar_year": int(str(archetype_row["known_at_utc"])[:4]),
                "model_rank": protocol["router_tie_priority"].index(model_id),
            })
            trades.append(result)
            signals.append(checkpoint_signal(archetype_row, feature, anatomy, model, trigger, result))
    trades.sort(key=lambda row: (str(row["known_at_utc"]), TIMEFRAME_PRIORITY[str(row["timeframe"])], int(row["model_rank"]), str(row["pullback_id"])))
    signals.sort(key=lambda row: (str(row["known_at_utc"]), TIMEFRAME_PRIORITY[str(row["timeframe"])], protocol["router_tie_priority"].index(str(row["model_id"])), str(row["pullback_id"])))
    return trades, signals


def safe_float(value: Any) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return output if math.isfinite(output) else float("nan")


def predictor_arrays(rows: Sequence[Mapping[str, Any]], implementation: Mapping[str, Any]) -> dict[str, np.ndarray]:
    output: dict[str, np.ndarray] = {}
    for name in implementation["numeric_predictors"]:
        output[name] = np.asarray([safe_float(row.get(name)) for row in rows], dtype=np.float64)
    for name in implementation["boolean_predictors"]:
        values = []
        for row in rows:
            value = row.get(name)
            values.append(float("nan") if value is None else (1.0 if bool(value) else 0.0))
        output[name] = np.asarray(values, dtype=np.float64)
    for name in implementation["categorical_predictors"]:
        output[name] = np.asarray(["UNKNOWN" if row.get(name) is None else str(row.get(name)) for row in rows], dtype=object)
    return output


def entropy(labels: np.ndarray) -> float:
    if len(labels) == 0:
        return 0.0
    counts = np.bincount(labels, minlength=len(CLASSES)).astype(np.float64)
    probabilities = counts[counts > 0] / len(labels)
    return float(-np.sum(probabilities * np.log(probabilities)))


def leaf_probabilities(labels: np.ndarray) -> list[float]:
    counts = np.bincount(labels, minlength=len(CLASSES)).astype(np.float64) + 1.0
    return [rounded(value) or 0.0 for value in (counts / counts.sum()).tolist()]


def fit_probability_tree(
    rows: Sequence[Mapping[str, Any]],
    labels: np.ndarray,
    registry: Mapping[str, Any],
    timeframe: str,
) -> dict[str, Any]:
    arrays = predictor_arrays(rows, registry)
    numeric = [*registry["numeric_predictors"], *registry["boolean_predictors"]]
    categorical = list(registry["categorical_predictors"])
    min_leaf = int(json.loads(PROTOCOL.read_text(encoding="utf-8"))["probability_tree"]["minimum_leaf"][timeframe])
    max_depth = int(json.loads(PROTOCOL.read_text(encoding="utf-8"))["probability_tree"]["maximum_depth"])
    min_gain = float(json.loads(PROTOCOL.read_text(encoding="utf-8"))["probability_tree"]["minimum_entropy_gain"])
    quantiles = json.loads(PROTOCOL.read_text(encoding="utf-8"))["probability_tree"]["numeric_quantiles"]
    registry_order = {name: index for index, name in enumerate([*numeric, *categorical])}

    def build(indices: np.ndarray, depth: int) -> dict[str, Any]:
        node_labels = labels[indices]
        counts = np.bincount(node_labels, minlength=len(CLASSES)).astype(int)
        base = {
            "n": int(len(indices)),
            "counts": {name: int(counts[index]) for index, name in enumerate(CLASSES)},
            "probabilities": leaf_probabilities(node_labels),
        }
        if depth >= max_depth or len(indices) < 2 * min_leaf or np.count_nonzero(counts) <= 1:
            return {"type": "leaf", **base}
        parent_entropy = entropy(node_labels)
        best: tuple[float, int, str, str, Any, np.ndarray, np.ndarray] | None = None
        for name in numeric:
            values = arrays[name][indices]
            finite_values = values[np.isfinite(values)]
            if len(finite_values) < min_leaf:
                continue
            thresholds = sorted({float(value) for value in np.quantile(finite_values, quantiles).tolist()})
            for threshold in thresholds:
                left_mask = ~np.isfinite(values) | (values <= threshold)
                left = indices[left_mask]
                right = indices[~left_mask]
                if len(left) < min_leaf or len(right) < min_leaf:
                    continue
                weighted = len(left) / len(indices) * entropy(labels[left]) + len(right) / len(indices) * entropy(labels[right])
                gain = parent_entropy - weighted
                candidate = (gain, -registry_order[name], name, "numeric", threshold, left, right)
                if best is None or candidate[:5] > best[:5]:
                    best = candidate
        for name in categorical:
            values = arrays[name][indices]
            for category in sorted(set(str(value) for value in values)):
                left_mask = values == category
                left = indices[left_mask]
                right = indices[~left_mask]
                if len(left) < min_leaf or len(right) < min_leaf:
                    continue
                weighted = len(left) / len(indices) * entropy(labels[left]) + len(right) / len(indices) * entropy(labels[right])
                gain = parent_entropy - weighted
                candidate = (gain, -registry_order[name], name, "categorical", category, left, right)
                if best is None or candidate[:5] > best[:5]:
                    best = candidate
        if best is None or best[0] < min_gain:
            return {"type": "leaf", **base}
        gain, _order, name, split_type, value, left, right = best
        return {
            "type": "node",
            **base,
            "depth": depth,
            "feature": name,
            "split_type": split_type,
            "threshold": rounded(float(value)) if split_type == "numeric" else None,
            "category": str(value) if split_type == "categorical" else None,
            "entropy_gain": rounded(gain),
            "missing_route": "LEFT" if split_type == "numeric" else "RIGHT",
            "left": build(left, depth + 1),
            "right": build(right, depth + 1),
        }

    return build(np.arange(len(rows), dtype=np.int64), 0)


def predict_tree_row(tree: Mapping[str, Any], row: Mapping[str, Any]) -> np.ndarray:
    node = tree
    while node["type"] == "node":
        name = str(node["feature"])
        if node["split_type"] == "numeric":
            value = safe_float(row.get(name))
            go_left = not math.isfinite(value) or value <= float(node["threshold"])
        else:
            value = "UNKNOWN" if row.get(name) is None else str(row.get(name))
            go_left = value == str(node["category"])
        node = node["left"] if go_left else node["right"]
    return np.asarray(node["probabilities"], dtype=np.float64)


def apply_temperature(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-12, 1.0)
    powered = np.exp(np.log(clipped) / temperature)
    return powered / powered.sum()


def multiclass_log_loss(probabilities: np.ndarray, labels: np.ndarray) -> float:
    if len(labels) == 0:
        return float("nan")
    return float(-np.mean(np.log(np.clip(probabilities[np.arange(len(labels)), labels], 1e-12, 1.0))))


def fit_tree_with_temperature(
    rows: Sequence[Mapping[str, Any]],
    labels: np.ndarray,
    registry: Mapping[str, Any],
    timeframe: str,
    protocol: Mapping[str, Any],
) -> tuple[dict[str, Any], float, dict[str, Any]]:
    order = sorted(range(len(rows)), key=lambda index: (str(rows[index]["known_at_utc"]), str(rows[index]["pullback_id"])))
    split = max(1, min(len(order) - 1, int(math.floor(len(order) * (1 - float(protocol["probability_tree"]["calibration_fraction"]))))))
    fit_indices = order[:split]
    calibration_indices = order[split:]
    fit_rows = [rows[index] for index in fit_indices]
    fit_labels = labels[np.asarray(fit_indices, dtype=np.int64)]
    calibration_rows = [rows[index] for index in calibration_indices]
    calibration_labels = labels[np.asarray(calibration_indices, dtype=np.int64)]
    calibration_tree = fit_probability_tree(fit_rows, fit_labels, registry, timeframe)
    raw = np.vstack([predict_tree_row(calibration_tree, row) for row in calibration_rows]) if calibration_rows else np.empty((0, len(CLASSES)))
    scored = []
    for temperature in protocol["probability_tree"]["temperature_grid"]:
        adjusted = np.vstack([apply_temperature(row, float(temperature)) for row in raw]) if len(raw) else raw
        scored.append((multiclass_log_loss(adjusted, calibration_labels), float(temperature)))
    scored.sort(key=lambda item: (item[0], item[1]))
    selected = scored[0][1] if scored else 1.0
    final_tree = fit_probability_tree(rows, labels, registry, timeframe)
    diagnostics = {
        "fit_rows": len(fit_rows),
        "calibration_rows": len(calibration_rows),
        "temperature_scores": [{"temperature": item[1], "log_loss": rounded(item[0])} for item in sorted(scored, key=lambda item: item[1])],
        "selected_temperature": selected,
    }
    return final_tree, selected, diagnostics


def deterministic_failure_probabilities(signal: Mapping[str, Any]) -> np.ndarray | None:
    model_id = str(signal["model_id"])
    if model_id == "FALSE_CONTINUATION_REVERSAL":
        output = np.zeros(len(CLASSES), dtype=np.float64)
        output[CLASS_INDEX["FALSE_CONTINUATION"]] = 1.0
        return output
    if model_id == "IMMEDIATE_FAILURE_REVERSAL":
        output = np.zeros(len(CLASSES), dtype=np.float64)
        label = "IMMEDIATE_FAILURE" if signal.get("barrier_0p5_order_observed_by_resolution") == "ADVERSE_FIRST" else "TWO_SIDED_CHOPPY"
        output[CLASS_INDEX[label]] = 1.0
        return output
    return None


def payoff_estimate(
    training_trades: Sequence[Mapping[str, Any]],
    probabilities: np.ndarray,
    shrinkage: float,
) -> tuple[float, float, dict[str, Any]]:
    values = np.asarray([float(row["net_r"]) for row in training_trades], dtype=np.float64)
    if len(values) == 0:
        return float("nan"), float("nan"), {}
    overall_mean = float(np.mean(values))
    overall_variance = float(np.var(values, ddof=1)) if len(values) > 1 else 1.0
    expected = 0.0
    variance_of_mean = 0.0
    cells: dict[str, Any] = {}
    for index, archetype in enumerate(CLASSES):
        cell_values = np.asarray([float(row["net_r"]) for row in training_trades if row["archetype"] == archetype], dtype=np.float64)
        count = len(cell_values)
        mean = float(np.mean(cell_values)) if count else overall_mean
        shrunk = (count * mean + shrinkage * overall_mean) / (count + shrinkage)
        variance = float(np.var(cell_values, ddof=1)) if count > 1 else overall_variance
        cell_se2 = variance / max(1, count)
        expected += float(probabilities[index]) * shrunk
        variance_of_mean += float(probabilities[index]) ** 2 * cell_se2
        cells[archetype] = {"n": count, "mean_r": rounded(mean), "shrunk_mean_r": rounded(shrunk), "variance": rounded(variance)}
    se = math.sqrt(max(0.0, variance_of_mean))
    return expected, se, cells


def risk_tier(score: float, protocol: Mapping[str, Any]) -> float:
    if not math.isfinite(score) or score <= 0:
        return 0.0
    if score <= 0.1:
        return 25.0
    if score <= 0.2:
        return 50.0
    if score <= 0.3:
        return 75.0
    return 100.0


def probability_metrics(rows: Sequence[Mapping[str, Any]], protocol: Mapping[str, Any], timeframe: str) -> dict[str, Any]:
    rows = [row for row in rows if str(row["actual_archetype"]) in CLASS_INDEX]
    if not rows:
        return {"rows": 0, "eligible": False, "failed_gates": ["NO_OOF_ROWS"]}
    actual = np.asarray([CLASS_INDEX[str(row["actual_archetype"])] for row in rows], dtype=np.int64)
    probabilities = np.asarray([[float(row[f"p_{name}"]) for name in CLASSES] for row in rows], dtype=np.float64)
    priors = np.asarray([[float(row[f"prior_{name}"]) for name in CLASSES] for row in rows], dtype=np.float64)
    one_hot = np.eye(len(CLASSES))[actual]
    predicted = np.argmax(probabilities, axis=1)
    prior_predicted = np.argmax(priors, axis=1)
    accuracy = float(np.mean(predicted == actual))
    prior_accuracy = float(np.mean(prior_predicted == actual))
    brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))
    prior_brier = float(np.mean(np.sum((priors - one_hot) ** 2, axis=1)))
    skill = 1 - brier / prior_brier if prior_brier > 0 else float("nan")
    log_loss = multiclass_log_loss(probabilities, actual)
    prior_log_loss = multiclass_log_loss(priors, actual)
    confidence = np.max(probabilities, axis=1)
    correctness = (predicted == actual).astype(np.float64)
    bins = []
    ece = 0.0
    for index in range(10):
        lower = index / 10
        upper = (index + 1) / 10
        mask = (confidence >= lower) & (confidence < upper if index < 9 else confidence <= upper)
        count = int(mask.sum())
        if count:
            mean_confidence = float(confidence[mask].mean())
            observed = float(correctness[mask].mean())
            ece += count / len(rows) * abs(mean_confidence - observed)
        else:
            mean_confidence = observed = None
        bins.append({"lower": lower, "upper": upper, "n": count, "mean_confidence": rounded(mean_confidence), "observed_accuracy": rounded(observed)})
    confusion = {actual_name: {predicted_name: 0 for predicted_name in CLASSES} for actual_name in CLASSES}
    for actual_index, predicted_index in zip(actual, predicted):
        confusion[CLASSES[int(actual_index)]][CLASSES[int(predicted_index)]] += 1
    gates = protocol["probability_tree"]["calibration_gates"]
    failures = []
    if len(rows) < int(gates["minimum_oof_rows"][timeframe]):
        failures.append("OOF_SUPPORT_BELOW_FLOOR")
    if not math.isfinite(skill) or skill <= float(gates["brier_skill_gt"]):
        failures.append("BRIER_SKILL_NOT_POSITIVE")
    if log_loss > prior_log_loss:
        failures.append("LOG_LOSS_WORSE_THAN_PRIOR")
    if accuracy < prior_accuracy:
        failures.append("TOP1_ACCURACY_WORSE_THAN_PRIOR")
    if ece > float(gates["ece_lte"]):
        failures.append("ECE_ABOVE_0P12")
    return {
        "rows": len(rows),
        "accuracy": rounded(accuracy),
        "prior_accuracy": rounded(prior_accuracy),
        "brier": rounded(brier),
        "prior_brier": rounded(prior_brier),
        "brier_skill": rounded(skill),
        "log_loss": rounded(log_loss),
        "prior_log_loss": rounded(prior_log_loss),
        "ece": rounded(ece),
        "reliability": bins,
        "confusion": confusion,
        "eligible": not failures,
        "failed_gates": failures,
    }


def executed_signal_rows(
    trades: Sequence[Mapping[str, Any]],
    signals: Sequence[Mapping[str, Any]],
    require_archetype_label: bool,
) -> list[dict[str, Any]]:
    trade_map = {(str(row["model_id"]), str(row["pullback_id"])): row for row in trades}
    output = []
    for signal in signals:
        trade = trade_map[(str(signal["model_id"]), str(signal["pullback_id"]))]
        if trade["status"] != "EXECUTED":
            continue
        if require_archetype_label and not signal["technical_available"]:
            continue
        row = dict(signal)
        row["trade"] = trade
        output.append(row)
    return output


def run_oof(
    trades: Sequence[Mapping[str, Any]],
    signals: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
    implementation: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    labeled = executed_signal_rows(trades, signals, True)
    all_executed = executed_signal_rows(trades, signals, False)
    predictions: list[dict[str, Any]] = []
    fold_models: list[dict[str, Any]] = []
    shrinkage = float(protocol["payoff_estimator"]["cell_shrinkage_observations"])
    for timeframe in TIMEFRAMES:
        for model in protocol["entry_models"]:
            model_id = str(model["model_id"])
            labeled_population = [row for row in labeled if row["timeframe"] == timeframe and row["model_id"] == model_id]
            live_population = [row for row in all_executed if row["timeframe"] == timeframe and row["model_id"] == model_id]
            for fold_id, train_start, train_end, validate_start, validate_end in FOLDS:
                training = [row for row in labeled_population if train_start <= str(row["known_at_utc"])[:10] <= train_end]
                validation = [row for row in live_population if validate_start <= str(row["known_at_utc"])[:10] <= validate_end]
                if not training or not validation:
                    fold_models.append({
                        "timeframe": timeframe,
                        "model_id": model_id,
                        "fold": fold_id,
                        "training_rows": len(training),
                        "validation_rows": len(validation),
                        "status": "SUPPORT_FAIL_EMPTY_FOLD",
                    })
                    continue
                train_labels = np.asarray([CLASS_INDEX[str(row["archetype"])] for row in training], dtype=np.int64)
                counts = np.bincount(train_labels, minlength=len(CLASSES)).astype(np.float64) + 1.0
                prior = counts / counts.sum()
                deterministic = model_id in {"FALSE_CONTINUATION_REVERSAL", "IMMEDIATE_FAILURE_REVERSAL"}
                tree = None
                temperature = 1.0
                diagnostics: dict[str, Any] = {"deterministic_state_model": deterministic}
                if not deterministic:
                    tree, temperature, calibration = fit_tree_with_temperature(training, train_labels, implementation, timeframe, protocol)
                    diagnostics.update(calibration)
                training_trades = [row["trade"] for row in training]
                model_record = {
                    "timeframe": timeframe,
                    "model_id": model_id,
                    "fold": fold_id,
                    "training_rows": len(training),
                    "validation_rows": len(validation),
                    "training_class_counts": {name: int(counts[index] - 1) for index, name in enumerate(CLASSES)},
                    "prior": {name: rounded(prior[index]) for index, name in enumerate(CLASSES)},
                    "tree": tree,
                    "tree_hash": canonical_hash(tree) if tree is not None else None,
                    "temperature": temperature,
                    "calibration": diagnostics,
                    "status": "FITTED",
                }
                fold_models.append(model_record)
                for signal in validation:
                    deterministic_probabilities = deterministic_failure_probabilities(signal)
                    if deterministic_probabilities is not None:
                        probabilities = deterministic_probabilities
                    else:
                        probabilities = apply_temperature(predict_tree_row(tree, signal), temperature)  # type: ignore[arg-type]
                    expected, standard_error, cells = payoff_estimate(training_trades, probabilities, shrinkage)
                    conservative = expected - float(protocol["payoff_estimator"]["conservative_standard_errors"]) * standard_error
                    risk = risk_tier(conservative, protocol)
                    trade = signal["trade"]
                    row = {
                        "prediction_id": f"GPARP-{canonical_hash([fold_id, timeframe, model_id, signal['pullback_id']])[:24]}",
                        "fold": fold_id,
                        "timeframe": timeframe,
                        "model_id": model_id,
                        "pullback_id": str(signal["pullback_id"]),
                        "known_at_utc": str(signal["known_at_utc"]),
                        "checkpoint_at_utc": str(signal["checkpoint_at_utc"]),
                        "session_state": str(signal["session_state"]),
                        "checkpoint_session_state": str(signal["checkpoint_session_state"]),
                        "actual_archetype": str(signal["archetype"]) if signal["technical_available"] else "UNAVAILABLE_TECHNICAL",
                        "predicted_archetype": CLASSES[int(np.argmax(probabilities))],
                        "prediction_confidence": rounded(float(np.max(probabilities))),
                        "expected_net_r": rounded(expected),
                        "expected_standard_error_r": rounded(standard_error),
                        "conservative_score_r": rounded(conservative),
                        "assigned_risk_usd": risk,
                        "trade_id": str(trade["trade_id"]),
                        "entry_at_utc": str(trade["entry_at_utc"]),
                        "exit_at_utc": str(trade["exit_at_utc"]),
                        "net_r": float(trade["net_r"]),
                        "net_r_cost_1p5x": float(trade["net_r_cost_1p5x"]),
                        "net_r_cost_2x": float(trade["net_r_cost_2x"]),
                        "payoff_training_cells_hash": canonical_hash(cells),
                    }
                    row.update({f"p_{name}": rounded(float(probabilities[index])) for index, name in enumerate(CLASSES)})
                    row.update({f"prior_{name}": rounded(float(prior[index])) for index, name in enumerate(CLASSES)})
                    predictions.append(row)
    predictions.sort(key=lambda row: (str(row["entry_at_utc"]), int(row["fold"]), TIMEFRAME_PRIORITY[str(row["timeframe"])], protocol["router_tie_priority"].index(str(row["model_id"])), str(row["pullback_id"])))
    metrics: dict[str, Any] = {}
    calibration_eligible: dict[str, bool] = {}
    for timeframe in TIMEFRAMES:
        metrics[timeframe] = {}
        for model in protocol["entry_models"]:
            model_id = str(model["model_id"])
            selected = [row for row in predictions if row["timeframe"] == timeframe and row["model_id"] == model_id]
            item = probability_metrics(selected, protocol, timeframe)
            metrics[timeframe][model_id] = item
            calibration_eligible[f"{timeframe}|{model_id}"] = bool(item["eligible"])
    return predictions, {"by_timeframe_model": metrics, "calibration_eligible": calibration_eligible}, {"fold_models": fold_models}


def scale_trade(trade: Mapping[str, Any], planned_risk_usd: float) -> dict[str, Any] | None:
    if planned_risk_usd <= 0 or trade["status"] != "EXECUTED":
        return None
    entry = int(trade["entry_e8"])
    stop = int(trade["stop_e8"])
    risk_per_ounce = abs(entry - stop) / SCALE
    if risk_per_ounce <= 0:
        return None
    cost_per_ounce = float(trade["cost_r"]) * risk_per_ounce
    ounces = math.floor((planned_risk_usd / (risk_per_ounce + cost_per_ounce)) + 1e-12)
    if ounces < 1:
        return None
    gross_per_ounce = float(trade["gross_r"]) * risk_per_ounce
    net_pnl = (gross_per_ounce - cost_per_ounce) * ounces
    stress_1p5 = (gross_per_ounce - 1.5 * cost_per_ounce) * ounces
    stress_2x = (gross_per_ounce - 2.0 * cost_per_ounce) * ounces
    output = dict(trade)
    output.update({
        "planned_risk_usd": planned_risk_usd,
        "ounces": ounces,
        "actual_stop_plus_cost_risk_usd": rounded((risk_per_ounce + cost_per_ounce) * ounces),
        "net_pnl_usd": rounded(net_pnl),
        "net_pnl_cost_1p5x_usd": rounded(stress_1p5),
        "net_pnl_cost_2x_usd": rounded(stress_2x),
        "planned_risk_return_r": rounded(net_pnl / planned_risk_usd),
    })
    return output


def route_predictions(
    predictions: Sequence[Mapping[str, Any]],
    trade_map: Mapping[str, Mapping[str, Any]],
    eligible: Mapping[str, bool],
    protocol: Mapping[str, Any],
    equal_risk: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = []
    for prediction in predictions:
        key = f"{prediction['timeframe']}|{prediction['model_id']}"
        if not equal_risk and not eligible.get(key, False):
            continue
        risk = 50.0 if equal_risk else float(prediction["assigned_risk_usd"])
        if risk <= 0:
            continue
        trade = trade_map[str(prediction["trade_id"])]
        scaled = scale_trade(trade, risk)
        if scaled is None:
            continue
        scaled.update({
            "fold": int(prediction["fold"]),
            "prediction_id": str(prediction["prediction_id"]),
            "predicted_archetype": str(prediction["predicted_archetype"]),
            "prediction_confidence": float(prediction["prediction_confidence"]),
            "expected_net_r": float(prediction["expected_net_r"]),
            "conservative_score_r": float(prediction["conservative_score_r"]),
            "router_mode": "ALL_MODEL_EQUAL_RISK" if equal_risk else "CALIBRATED_VARIABLE_RISK",
        })
        candidates.append(scaled)
    if equal_risk:
        candidates.sort(key=lambda row: (str(row["entry_at_utc"]), int(row["model_rank"]), TIMEFRAME_PRIORITY[str(row["timeframe"])], str(row["pullback_id"])))
    else:
        candidates.sort(key=lambda row: (str(row["entry_at_utc"]), -float(row["conservative_score_r"]), int(row["model_rank"]), TIMEFRAME_PRIORITY[str(row["timeframe"])], str(row["pullback_id"])))
    accepted: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    open_until: str | None = None
    current_timestamp: str | None = None
    timestamp_winner_selected = False
    for row in candidates:
        entry_at = str(row["entry_at_utc"])
        if entry_at != current_timestamp:
            current_timestamp = entry_at
            timestamp_winner_selected = False
        decision = dict(row)
        if open_until is not None and entry_at < open_until:
            decision["portfolio_status"] = "SKIPPED_OVERLAPPING_POSITION"
            decision["portfolio_reason"] = "ONE_OPEN_XAUUSD_POSITION"
        elif timestamp_winner_selected:
            decision["portfolio_status"] = "SKIPPED_SAME_TIMESTAMP_LOWER_PRIORITY"
            decision["portfolio_reason"] = "ONE_DECISION_PER_TIMESTAMP"
        else:
            decision["portfolio_status"] = "ACCEPTED"
            decision["portfolio_reason"] = ""
            timestamp_winner_selected = True
            open_until = str(row["exit_at_utc"])
            accepted.append(decision)
        decisions.append(decision)
    accepted.sort(key=lambda row: (str(row["entry_at_utc"]), str(row["trade_id"])))
    return decisions, accepted


def expectation(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    return statistics.fmean(float(row[field]) for row in rows) if rows else None


def portfolio_summary(rows: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row["entry_at_utc"]), str(row["trade_id"])))
    metrics = econ.basic_metrics(ordered)
    bootstrap = econ.cluster_bootstrap(ordered, "net_r", seed, resamples=5000)
    folds = []
    for fold_id in (1, 2, 3):
        selected = [row for row in ordered if int(row.get("fold") or 0) == fold_id]
        folds.append({
            "fold": fold_id,
            "trades": len(selected),
            "expectancy_r": rounded(expectation(selected, "net_r")),
            "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected)),
        })
    annual = []
    for year in (2022, 2023, 2024):
        selected = [row for row in ordered if str(row["entry_at_utc"]).startswith(str(year))]
        annual.append({
            "year": year,
            "trades": len(selected),
            "expectancy_r": rounded(expectation(selected, "net_r")),
            "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected)),
        })
    by_model = {}
    for model_id in sorted({str(row["model_id"]) for row in ordered}):
        selected = [row for row in ordered if row["model_id"] == model_id]
        by_model[model_id] = {
            "trades": len(selected),
            "expectancy_r": rounded(expectation(selected, "net_r")),
            "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected)),
        }
    by_timeframe = {}
    for timeframe in TIMEFRAMES:
        selected = [row for row in ordered if row["timeframe"] == timeframe]
        by_timeframe[timeframe] = {
            "trades": len(selected),
            "expectancy_r": rounded(expectation(selected, "net_r")),
            "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected)),
        }
    sessions = {}
    for session in sorted({str(row["session_state"]) for row in ordered}):
        selected = [row for row in ordered if row["session_state"] == session]
        sessions[session] = {
            "trades": len(selected),
            "expectancy_r": rounded(expectation(selected, "net_r")),
            "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected)),
        }
    positive_by_model = defaultdict(float)
    for row in ordered:
        positive_by_model[str(row["model_id"])] += max(0.0, float(row["net_r"]))
    total_positive = sum(positive_by_model.values())
    concentration = max(positive_by_model.values()) / total_positive if total_positive else None
    return {
        "metrics": metrics,
        "bootstrap": bootstrap,
        "stress": {
            "cost_1p5x_expectancy_r": rounded(expectation(ordered, "net_r_cost_1p5x")),
            "cost_2x_expectancy_r": rounded(expectation(ordered, "net_r_cost_2x")),
            "cost_1p5x_net_pnl_usd": rounded(sum(float(row["net_pnl_cost_1p5x_usd"]) for row in ordered)),
            "cost_2x_net_pnl_usd": rounded(sum(float(row["net_pnl_cost_2x_usd"]) for row in ordered)),
        },
        "folds": folds,
        "annual": annual,
        "by_model": by_model,
        "by_timeframe": by_timeframe,
        "sessions": sessions,
        "maximum_positive_gross_r_share_per_model": rounded(concentration),
        "ending_balance_usd": rounded(10_000 + sum(float(row["net_pnl_usd"]) for row in ordered)),
        "total_return_pct": rounded(sum(float(row["net_pnl_usd"]) for row in ordered) / 10_000 * 100),
    }


def compact_trade_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row["entry_at_utc"]), str(row["trade_id"])))
    if not ordered:
        return {
            "trades": 0,
            "win_rate_pct": None,
            "expectancy_r": None,
            "profit_factor": None,
            "average_win_r": None,
            "average_loss_r": None,
            "average_mfe_r": None,
            "average_mae_r": None,
            "median_holding_minutes": None,
            "net_pnl_usd": 0.0,
        }
    metrics = econ.basic_metrics(ordered)
    return {name: metrics.get(name) for name in (
        "trades",
        "win_rate_pct",
        "expectancy_r",
        "profit_factor",
        "average_win_r",
        "average_loss_r",
        "average_mfe_r",
        "average_mae_r",
        "median_holding_minutes",
        "net_pnl_usd",
        "average_cost_r",
        "max_drawdown_r",
    )}


def build_payoff_matrix(trades: Sequence[Mapping[str, Any]], protocol: Mapping[str, Any]) -> dict[str, Any]:
    executed = [row for row in trades if row["status"] == "EXECUTED" and row["technical_available"]]
    output: dict[str, Any] = {}
    for timeframe in TIMEFRAMES:
        output[timeframe] = {}
        for model in protocol["entry_models"]:
            model_id = str(model["model_id"])
            model_rows = [row for row in executed if row["timeframe"] == timeframe and row["model_id"] == model_id]
            cells = {}
            for archetype in CLASSES:
                selected = [row for row in model_rows if row["archetype"] == archetype]
                cells[archetype] = compact_trade_metrics(selected)
            output[timeframe][model_id] = {
                "intended_archetype": str(model["intended_archetype"]),
                "all_archetypes": compact_trade_metrics(model_rows),
                "cells": cells,
            }
    return output


def one_model_nonoverlap(trades: Sequence[Mapping[str, Any]], model_id: str) -> list[dict[str, Any]]:
    candidates = []
    for trade in trades:
        if trade["model_id"] != model_id or trade["status"] != "EXECUTED" or not trade["technical_available"]:
            continue
        scaled = scale_trade(trade, 50.0)
        if scaled is not None:
            candidates.append(scaled)
    candidates.sort(key=lambda row: (str(row["entry_at_utc"]), TIMEFRAME_PRIORITY[str(row["timeframe"])], str(row["pullback_id"])))
    accepted = []
    open_until: str | None = None
    for row in candidates:
        if open_until is not None and str(row["entry_at_utc"]) < open_until:
            continue
        accepted.append(row)
        open_until = str(row["exit_at_utc"])
    return accepted


def development_gates(summary: Mapping[str, Any], protocol: Mapping[str, Any]) -> tuple[str, list[str]]:
    gates = protocol["development_pass_gates"]
    metrics = summary["metrics"]
    failures = []
    if int(metrics.get("trades") or 0) < int(gates["minimum_oof_trades"]):
        failures.append("OOF_TRADES_LT_100")
    if metrics.get("expectancy_r") is None or float(metrics["expectancy_r"]) <= float(gates["expectancy_r_gt"]):
        failures.append("NET_EXPECTANCY_NOT_POSITIVE")
    pf = metrics.get("profit_factor")
    if pf != "INF" and (pf is None or float(pf) < float(gates["profit_factor_gte"])):
        failures.append("PROFIT_FACTOR_LT_1P05")
    ci_low = summary["bootstrap"]["ci95"][0]
    if ci_low is None or float(ci_low) <= float(gates["cluster_bootstrap_ci95_low_gt"]):
        failures.append("CLUSTER_CI95_LOWER_NOT_POSITIVE")
    stress = summary["stress"]["cost_1p5x_expectancy_r"]
    if stress is None or float(stress) <= float(gates["cost_1p5x_expectancy_r_gt"]):
        failures.append("COST_1P5X_EXPECTANCY_NOT_POSITIVE")
    positive_folds = sum(item["expectancy_r"] is not None and float(item["expectancy_r"]) > 0 for item in summary["folds"])
    if positive_folds < int(gates["positive_validation_folds_gte"]):
        failures.append("POSITIVE_VALIDATION_FOLDS_LT_2")
    concentration = summary["maximum_positive_gross_r_share_per_model"]
    if concentration is None or float(concentration) > float(gates["maximum_positive_gross_r_share_per_model"]):
        failures.append("MODEL_POSITIVE_GROSS_R_CONCENTRATION_GT_70PCT")
    return ("PASS_DEVELOPMENT_ROUTED_SYSTEM" if not failures else "REJECT_DEVELOPMENT_ROUTED_SYSTEM"), failures


def fit_final_system(
    trades: Sequence[Mapping[str, Any]],
    signals: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
    implementation: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    eligible = executed_signal_rows(trades, signals, True)
    models = []
    shrinkage = float(protocol["payoff_estimator"]["cell_shrinkage_observations"])
    for timeframe in TIMEFRAMES:
        for model in protocol["entry_models"]:
            model_id = str(model["model_id"])
            population = [row for row in eligible if row["timeframe"] == timeframe and row["model_id"] == model_id]
            labels = np.asarray([CLASS_INDEX[str(row["archetype"])] for row in population], dtype=np.int64)
            deterministic = model_id in {"FALSE_CONTINUATION_REVERSAL", "IMMEDIATE_FAILURE_REVERSAL"}
            tree = None
            temperature = 1.0
            temperature_diagnostics: dict[str, Any] = {"deterministic_state_model": deterministic}
            if population and not deterministic:
                tree, temperature, temperature_diagnostics = fit_tree_with_temperature(population, labels, implementation, timeframe, protocol)
            model_trades = [row["trade"] for row in population]
            overall_values = np.asarray([float(row["net_r"]) for row in model_trades], dtype=np.float64)
            overall_mean = float(np.mean(overall_values)) if len(overall_values) else 0.0
            overall_variance = float(np.var(overall_values, ddof=1)) if len(overall_values) > 1 else 1.0
            payoff_cells = {}
            for archetype in CLASSES:
                values = np.asarray([float(row["net_r"]) for row in model_trades if row["archetype"] == archetype], dtype=np.float64)
                count = len(values)
                mean = float(np.mean(values)) if count else overall_mean
                variance = float(np.var(values, ddof=1)) if count > 1 else overall_variance
                shrunk = (count * mean + shrinkage * overall_mean) / (count + shrinkage)
                payoff_cells[archetype] = {
                    "n": count,
                    "mean_r": rounded(mean),
                    "variance": rounded(variance),
                    "shrunk_mean_r": rounded(shrunk),
                }
            models.append({
                "timeframe": timeframe,
                "model_id": model_id,
                "entry_model": model,
                "training_rows": len(population),
                "training_class_counts": dict(sorted(Counter(str(row["archetype"]) for row in population).items())),
                "deterministic_state_model": deterministic,
                "tree": tree,
                "tree_hash": canonical_hash(tree) if tree is not None else None,
                "temperature": temperature,
                "temperature_diagnostics": temperature_diagnostics,
                "calibration_eligible": bool(calibration["calibration_eligible"].get(f"{timeframe}|{model_id}", False)),
                "payoff_overall_mean_r": rounded(overall_mean),
                "payoff_overall_variance": rounded(overall_variance),
                "payoff_cells": payoff_cells,
            })
    return {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_FROZEN_SYSTEM_1_0",
        "status": "FROZEN_FULL_DEVELOPMENT_SYSTEM_BEFORE_FORWARD_VALUES",
        "frozen_at_utc": utc_now(),
        "classes": list(CLASSES),
        "predictor_registry": {
            "numeric": implementation["numeric_predictors"],
            "boolean": implementation["boolean_predictors"],
            "categorical": implementation["categorical_predictors"],
        },
        "models": models,
        "risk": protocol["risk"],
        "costs": protocol["costs_usd_per_ounce_roundtrip"],
        "router_tie_priority": protocol["router_tie_priority"],
        "payoff_estimator": protocol["payoff_estimator"],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "retuning_permitted": False,
    }


def report_text(results: Mapping[str, Any], payoff: Mapping[str, Any], classifier: Mapping[str, Any]) -> str:
    routed = results["variable_risk_router"]
    equal = results["equal_risk_all_model"]
    lines = [
        "# Gold Pullback Archetype Setup Routing and Risk Allocation V1 — Development",
        "",
        f"Status: **{results['verdict']}**",
        "",
        "The six observable entry models were frozen before this model-by-archetype calculation. Calendar 2025 and 2026 were not accessed in this development stage.",
        "",
        "## OOF portfolio comparison",
        "",
        "| Portfolio | Trades | Win rate | Expectancy | PF | Net PnL | Avg/month | Max DD | 1.5x-cost expectancy |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in (("All models, equal $50 risk", equal), ("Calibrated probability router", routed)):
        metrics = item["metrics"]
        lines.append(
            f"| {name} | {metrics.get('trades')} | {metrics.get('win_rate_pct')}% | {metrics.get('expectancy_r')}R | "
            f"{metrics.get('profit_factor')} | ${metrics.get('net_pnl_usd')} | ${metrics.get('average_monthly_pnl_usd')} | "
            f"{metrics.get('max_drawdown_pct')}% | {item['stress'].get('cost_1p5x_expectancy_r')}R |"
        )
    lines += [
        "",
        "## Constant-risk standalone entry models",
        "",
        "| Entry model | Trades | Win rate | Expectancy | PF | Net PnL |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model_id, item in results["standalone_models"].items():
        metrics = item["metrics"]
        lines.append(f"| `{model_id}` | {metrics.get('trades')} | {metrics.get('win_rate_pct')}% | {metrics.get('expectancy_r')}R | {metrics.get('profit_factor')} | ${metrics.get('net_pnl_usd')} |")
    lines += [
        "",
        "## Classifier calibration",
        "",
        "| TF | Model | Rows | Accuracy/prior | Brier skill | ECE | Eligible |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for timeframe in TIMEFRAMES:
        for model_id, item in classifier["by_timeframe_model"][timeframe].items():
            lines.append(
                f"| {timeframe} | `{model_id}` | {item.get('rows')} | {item.get('accuracy')}/{item.get('prior_accuracy')} | "
                f"{item.get('brier_skill')} | {item.get('ece')} | {item.get('eligible')} |"
            )
    lines += [
        "",
        "## Intended-archetype payoff cells",
        "",
        "| TF | Entry model | Intended archetype | Trades | Win rate | Expectancy | PF |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for timeframe in TIMEFRAMES:
        for model_id, item in payoff[timeframe].items():
            intended = item["intended_archetype"]
            cell = item["cells"][intended]
            lines.append(f"| {timeframe} | `{model_id}` | {intended} | {cell.get('trades')} | {cell.get('win_rate_pct')}% | {cell.get('expectancy_r')}R | {cell.get('profit_factor')} |")
    lines += [
        "",
        "## Verdict",
        "",
        f"Failed development gates: `{', '.join(results['failed_gates']) if results['failed_gates'] else 'NONE'}`.",
        "",
        "The payoff matrix is descriptive because the realised archetype is not available at entry. The routed result uses only expanding-window out-of-fold probabilities and training-only payoff estimates.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    protocol, freeze, implementation = verify_freezes()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    primary_rows = load_rows("primary")
    reference_rows = load_rows("reference")
    prices = anatomy_impl.load_price()
    if "forward_rows_not_deserialized" not in prices.diagnostics:
        raise ValueError("Forward-exclusion diagnostic is unavailable")
    swings, broken_at = execution.load_target_registry()
    reverse_delay = int(implementation["reverse_checkpoint_max_m1_delay_minutes"])

    primary_trades, primary_signals = build_model_trades("primary", protocol, primary_rows, prices, swings, broken_at, reverse_delay)
    reference_trades, reference_signals = build_model_trades("reference", protocol, reference_rows, prices, swings, broken_at, reverse_delay)
    if canonical_hash(primary_trades) != canonical_hash(reference_trades):
        raise ValueError("Primary/reference entry model trades differ")
    if canonical_hash(primary_signals) != canonical_hash(reference_signals):
        raise ValueError("Primary/reference checkpoint signals differ")

    primary_predictions, primary_classifier, primary_models = run_oof(primary_trades, primary_signals, protocol, implementation)
    reference_predictions, reference_classifier, reference_models = run_oof(reference_trades, reference_signals, protocol, implementation)
    if canonical_hash(primary_predictions) != canonical_hash(reference_predictions):
        raise ValueError("Primary/reference OOF predictions differ")
    if canonical_hash(primary_classifier) != canonical_hash(reference_classifier):
        raise ValueError("Primary/reference classifier metrics differ")
    if canonical_hash(primary_models) != canonical_hash(reference_models):
        raise ValueError("Primary/reference fitted fold models differ")

    trade_map = {str(row["trade_id"]): row for row in primary_trades}
    equal_decisions, equal_accepted = route_predictions(primary_predictions, trade_map, primary_classifier["calibration_eligible"], protocol, True)
    routed_decisions, routed_accepted = route_predictions(primary_predictions, trade_map, primary_classifier["calibration_eligible"], protocol, False)
    equal_summary = portfolio_summary(equal_accepted, 861017)
    routed_summary = portfolio_summary(routed_accepted, 861018)
    verdict, failed_gates = development_gates(routed_summary, protocol)

    payoff = build_payoff_matrix(primary_trades, protocol)
    standalone = {}
    for model in protocol["entry_models"]:
        model_id = str(model["model_id"])
        accepted = one_model_nonoverlap(primary_trades, model_id)
        standalone[model_id] = portfolio_summary(accepted, 862000 + protocol["router_tie_priority"].index(model_id))

    results = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_DEVELOPMENT_RESULTS_1_0",
        "verdict": verdict,
        "failed_gates": failed_gates,
        "development_period": ["2021-08-01", "2024-12-31"],
        "entry_model_trade_rows": len(primary_trades),
        "executed_entry_model_trades": sum(row["status"] == "EXECUTED" for row in primary_trades),
        "technical_archetype_rows": 8_205,
        "technical_unavailable_rows": 448,
        "oof_prediction_rows": len(primary_predictions),
        "equal_risk_all_model": equal_summary,
        "variable_risk_router": routed_summary,
        "equal_risk_decision_counts": dict(sorted(Counter(str(row["portfolio_status"]) for row in equal_decisions).items())),
        "variable_risk_decision_counts": dict(sorted(Counter(str(row["portfolio_status"]) for row in routed_decisions).items())),
        "standalone_models": standalone,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
        "primary_reference_exact": True,
        "price_diagnostics": prices.diagnostics,
        "preserved_failed_implementation": file_record(ROOT / "research_artifacts/gold_pullback_archetype_setup_routing_v1/development_seal.json"),
    }

    frozen_system = fit_final_system(primary_trades, primary_signals, protocol, implementation, primary_classifier)
    frozen_system["development_verdict"] = verdict
    frozen_system["development_failed_gates"] = failed_gates
    frozen_system["preperformance_freeze"] = file_record(PRE_FREEZE)
    frozen_system["implementation_freeze"] = file_record(IMPLEMENTATION_FREEZE)
    frozen_system["implementation_correction_a"] = file_record(IMPLEMENTATION_CORRECTION)
    frozen_system["implementation_correction_b"] = file_record(IMPLEMENTATION_CORRECTION_B)
    frozen_system["preserved_failed_development_seal"] = file_record(ROOT / "research_artifacts/gold_pullback_archetype_setup_routing_v1/development_seal.json")

    paths = {
        "primary_trades": OUTPUT / "primary_model_trades.parquet",
        "reference_trades": OUTPUT / "reference_model_trades.parquet",
        "primary_predictions": OUTPUT / "primary_oof_predictions.parquet",
        "reference_predictions": OUTPUT / "reference_oof_predictions.parquet",
        "primary_equal_decisions": OUTPUT / "primary_equal_risk_oof_decisions.parquet",
        "reference_equal_decisions": OUTPUT / "reference_equal_risk_oof_decisions.parquet",
        "primary_router_decisions": OUTPUT / "primary_variable_risk_oof_decisions.parquet",
        "reference_router_decisions": OUTPUT / "reference_variable_risk_oof_decisions.parquet",
    }
    write_parquet_exclusive(paths["primary_trades"], primary_trades)
    write_parquet_exclusive(paths["reference_trades"], reference_trades)
    write_parquet_exclusive(paths["primary_predictions"], primary_predictions)
    write_parquet_exclusive(paths["reference_predictions"], reference_predictions)
    write_parquet_exclusive(paths["primary_equal_decisions"], equal_decisions)
    write_parquet_exclusive(paths["reference_equal_decisions"], equal_decisions)
    write_parquet_exclusive(paths["primary_router_decisions"], routed_decisions)
    write_parquet_exclusive(paths["reference_router_decisions"], routed_decisions)
    for left, right in (("primary_trades", "reference_trades"), ("primary_predictions", "reference_predictions"), ("primary_equal_decisions", "reference_equal_decisions"), ("primary_router_decisions", "reference_router_decisions")):
        if sha256_file(paths[left]) != sha256_file(paths[right]):
            raise ValueError(f"Primary/reference Parquet bytes differ: {left}")

    payoff_path = OUTPUT / "payoff_matrix.json"
    classifier_path = OUTPUT / "classifier_results.json"
    fold_models_path = OUTPUT / "fold_models.json"
    results_path = OUTPUT / "development_results.json"
    frozen_path = OUTPUT / "frozen_system_pre_forward.json"
    write_json_exclusive(payoff_path, payoff)
    write_json_exclusive(classifier_path, primary_classifier)
    write_json_exclusive(fold_models_path, primary_models)
    write_json_exclusive(results_path, results)
    write_json_exclusive(frozen_path, frozen_system)
    write_text_exclusive(REPORT, report_text(results, payoff, primary_classifier))

    artifact_paths = [*paths.values(), payoff_path, classifier_path, fold_models_path, results_path, frozen_path, REPORT]
    seal = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_DEVELOPMENT_SEAL_1_0",
        "status": verdict,
        "sealed_at_utc": utc_now(),
        "artifacts": {str(path.relative_to(ROOT)).replace("\\", "/"): file_record(path) for path in artifact_paths},
        "artifact_set_hash": canonical_hash({str(path.relative_to(ROOT)).replace("\\", "/"): sha256_file(path) for path in artifact_paths}),
        "primary_reference_exact": True,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
        "preserved_failed_implementation": file_record(ROOT / "research_artifacts/gold_pullback_archetype_setup_routing_v1/development_seal.json"),
    }
    seal_path = OUTPUT / "development_seal.json"
    write_json_exclusive(seal_path, seal)
    state = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_STATE_PRE_FORWARD_1_0",
        "status": "READY_FOR_SINGLE_EXPOSED_FORWARD_APPLICATION",
        "development_verdict": verdict,
        "development_seal": file_record(seal_path),
        "frozen_system": file_record(frozen_path),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "next_step": "VERIFY_EXISTING_FORWARD_SOURCE_HASHES_THEN_APPLY_FROZEN_SYSTEM_ONCE",
    }
    write_json_exclusive(OUTPUT / "state_pre_forward.json", state)
    print(json.dumps({
        "status": verdict,
        "failed_gates": failed_gates,
        "executed_entry_model_trades": results["executed_entry_model_trades"],
        "oof_prediction_rows": len(primary_predictions),
        "equal_risk": equal_summary,
        "variable_risk": routed_summary,
        "calibration_eligible": primary_classifier["calibration_eligible"],
        "development_seal": file_record(seal_path),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
