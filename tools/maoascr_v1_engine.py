from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.tree import DecisionTreeClassifier, export_text

try:
    from tools import msbam_v1_m2_m3_engine as base
except ModuleNotFoundError:
    import msbam_v1_m2_m3_engine as base


NUMERIC_FEATURES = (
    "macro_alignment",
    "macro_confidence",
    "htf_pressure_alignment",
    "structure_alignment",
    "bos_alignment",
    "early_displacement_r",
    "trigger_bar_range_r",
    "trigger_bar_body_alignment",
    "early_range_r",
    "pretrigger_adverse_r",
    "early_path_efficiency",
    "elapsed_fraction",
    "atr_fraction_of_price",
    "checkpoint_spread_r",
    "tick_volume_robust_z60",
    "quote_density",
    "nearest_ahead_level_r",
    "nearest_behind_level_r",
    "levels_within_0p5atr",
    "aligned_level_acceptance",
    "opposite_sweep_reclaim",
    "event_within_240m",
)

CATEGORICAL_FEATURES = ("instrument", "session", "timeframe", "trigger_direction")

CATEGORY_REGISTRY = {
    "instrument": tuple(base.INSTRUMENTS),
    "session": ("LONDON_SESSION", "NEW_YORK_SESSION", "US_CASH_SESSION", "US_ENERGY_SESSION"),
    "timeframe": ("M15", "H1", "H4"),
    "trigger_direction": ("SHORT", "LONG"),
}

INTERACTIONS = (
    ("INT_MACRO_HTF", "macro_alignment", "htf_pressure_alignment"),
    ("INT_MACRO_STRUCTURE", "macro_alignment", "structure_alignment"),
    ("INT_MACRO_LEVEL_ACCEPTANCE", "macro_alignment", "aligned_level_acceptance"),
    ("INT_MACRO_SWEEP_RECLAIM", "macro_alignment", "opposite_sweep_reclaim"),
    ("INT_EFFICIENCY_STRUCTURE", "early_path_efficiency", "structure_alignment"),
    ("INT_VOLATILITY_LIQUIDITY", "early_range_r", "checkpoint_spread_r"),
)

FOLDS = (
    (1, date(2022, 1, 1), date(2022, 7, 1)),
    (2, date(2022, 7, 1), date(2023, 1, 1)),
    (3, date(2023, 1, 1), date(2023, 7, 1)),
    (4, date(2023, 7, 1), date(2024, 1, 1)),
    (5, date(2024, 1, 1), date(2024, 7, 1)),
    (6, date(2024, 7, 1), date(2025, 1, 1)),
)

TIMEFRAME_PRIORITY = {"M15": 0, "H1": 1, "H4": 2}
ROUTER_SEED = 932_771
BOOTSTRAP_SEED = 932_773
BOOTSTRAP_RESAMPLES = 2_000


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rounded(value: float | int | None) -> float | int | None:
    return base.rounded(value)


def sign_state(value: Any, positive: str, negative: str) -> int | None:
    if value == positive:
        return 1
    if value == negative:
        return -1
    if value in {"NEUTRAL", "RANGE_OR_TRANSITION", "NONE"}:
        return 0
    return None


def mean_available(values: Sequence[int | float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(np.mean(usable)) if usable else None


def robust_z(current: float, history: np.ndarray) -> float | None:
    values = np.log1p(np.maximum(history.astype(float), 0.0))
    if len(values) < 30:
        return None
    center = float(np.median(values))
    mad = float(np.median(np.abs(values - center)))
    if mad <= 0:
        return 0.0
    return float((math.log1p(max(current, 0.0)) - center) / (1.4826 * mad))


def level_distances(
    levels: Sequence[Mapping[str, Any]], current: float, atr: float, direction: int
) -> tuple[float | None, float | None, int]:
    signed = [direction * (float(item["price"]) - current) / atr for item in levels]
    ahead = [value for value in signed if value >= 0]
    behind = [-value for value in signed if value < 0]
    nearby = sum(abs(value) <= 0.5 for value in signed)
    return (min(ahead) if ahead else None, min(behind) if behind else None, nearby)


def feature_row(
    legacy: Any,
    bundle: Any,
    macro_book: Any,
    case: Mapping[str, Any],
    prior_case: Mapping[str, Any] | None,
    timeframe: str,
) -> dict[str, Any] | None:
    start = base.minute_of(str(case["observation_start_utc"]))
    end = base.minute_of(str(case["observation_end_utc"]))
    predecision = base.minute_of(str(case["decision_at_utc"]))
    reference_index = bundle.m1.exact_index(start)
    if reference_index is None:
        return None
    atr = legacy.atr_at(bundle.m15, predecision, length=14)
    if atr is None or atr <= 0:
        return None
    reference = float(bundle.m1.open[reference_index])
    trigger_case = {
        "observation_start_minute": start,
        "observation_end_minute": end,
        "reference_open": reference,
        "atr15": atr,
    }
    trigger = base.trigger_for_track(bundle.m1, trigger_case, timeframe)
    if trigger is None:
        return None
    direction = int(trigger["direction"])
    checkpoint = int(trigger["trigger_available_minute"])
    left, right = base.raw_slice(bundle.m1, start, checkpoint)
    if right <= left:
        return None
    last_index = right - 1
    current = float(bundle.m1.close[last_index])
    maximum = float(np.max(bundle.m1.high[left:right]))
    minimum = float(np.min(bundle.m1.low[left:right]))
    early_range = maximum - minimum
    m5 = base.relative_bars(bundle.m1, start, checkpoint, 5)
    track_bars = base.relative_bars(bundle.m1, start, checkpoint, base.TIMEFRAMES[timeframe])
    if not track_bars or int(track_bars[-1]["end"]) != checkpoint:
        return None
    trigger_bar = track_bars[-1]
    bar_range = float(trigger_bar["high"] - trigger_bar["low"])
    bar_body_alignment = direction * float(trigger_bar["close"] - trigger_bar["open"]) / bar_range if bar_range > 0 else 0.0

    levels = base.known_levels(bundle, case, prior_case)
    interactions = base.level_interactions(levels, bundle.m1, left, right, m5, atr, current)
    aligned_acceptance = int(any(int(item["direction"]) == direction and bool(item["accepted"]) for item in interactions))
    opposite_reclaim = int(any(int(item["direction"]) == -direction and bool(item["reclaimed"]) for item in interactions))
    ahead, behind, nearby = level_distances(levels, current, atr, direction)

    htf_states: dict[str, dict[str, Any]] = {
        "W1": base.pressure_payload(legacy, bundle.w1, checkpoint),
        "D1": base.pressure_payload(legacy, bundle.d1, checkpoint),
        "H4": base.pressure_payload(legacy, bundle.h4, checkpoint),
        "H1": base.pressure_payload(legacy, bundle.h1, checkpoint),
    }
    pressure = mean_available([
        None if sign_state(htf_states[key]["state"], "BULLISH", "BEARISH") is None
        else direction * int(sign_state(htf_states[key]["state"], "BULLISH", "BEARISH"))
        for key in ("W1", "D1", "H4", "H1")
    ])
    structures = {name: base.structure_payload(bundle, size, checkpoint) for name, size in (("M15", 15), ("H1", 60), ("H4", 240))}
    structure_alignment = mean_available([
        None if sign_state(structures[key]["state"], "UPTREND", "DOWNTREND") is None
        else direction * int(sign_state(structures[key]["state"], "UPTREND", "DOWNTREND"))
        for key in ("M15", "H1", "H4")
    ])
    bos_alignment = mean_available([
        None if sign_state(structures[key]["bos_mss"], "BULLISH_BREAK", "BEARISH_BREAK") is None
        else direction * int(sign_state(structures[key]["bos_mss"], "BULLISH_BREAK", "BEARISH_BREAK"))
        for key in ("M15", "H1", "H4")
    ])

    macro = macro_book.context(str(case["instrument"]), checkpoint, direction)
    macro_score = macro.get("score")
    event = base.event_context(macro_book, checkpoint)
    minutes_to_event = event.get("minutes_to_event")
    history_left = max(0, last_index - 60)
    volume_z = robust_z(float(bundle.m1.volume[last_index]), bundle.m1.volume[history_left:last_index])
    point = float(base.INSTRUMENTS[str(case["instrument"])]["point"])
    spread_r = float(bundle.m1.spread[last_index]) * point / atr
    adverse = (reference - minimum) / atr if direction == 1 else (maximum - reference) / atr
    elapsed = checkpoint - start
    checkpoint_id = "MAOASCR-V1::" + hashlib.sha256(
        f"{case['case_id']}|{timeframe}|{checkpoint}|{direction}".encode("utf-8")
    ).hexdigest()[:24]

    row: dict[str, Any] = {
        "checkpoint_id": checkpoint_id,
        "case_id": str(case["case_id"]),
        "instrument": str(case["instrument"]),
        "research_id": str(case["research_id"]),
        "cluster": str(base.INSTRUMENTS[str(case["instrument"])]["cluster"]),
        "session": str(case["session_code"]),
        "session_date": str(case["session_date_local"]),
        "timeframe": timeframe,
        "trigger_direction": "LONG" if direction == 1 else "SHORT",
        "direction": direction,
        "checkpoint_minute": checkpoint,
        "entry_minute": int(trigger["entry_minute"]),
        "observation_end_minute": end,
        "estimated_cost_r": rounded(max(spread_r + 0.03, 0.05)),
        "macro_alignment": rounded(direction * float(macro_score) / 100.0) if macro_score is not None else None,
        "macro_confidence": rounded(float(macro.get("confidence", 0.0)) / 100.0),
        "htf_pressure_alignment": rounded(pressure),
        "structure_alignment": rounded(structure_alignment),
        "bos_alignment": rounded(bos_alignment),
        "early_displacement_r": rounded(direction * (current - reference) / atr),
        "trigger_bar_range_r": rounded(bar_range / atr),
        "trigger_bar_body_alignment": rounded(bar_body_alignment),
        "early_range_r": rounded(early_range / atr),
        "pretrigger_adverse_r": rounded(max(0.0, adverse)),
        "early_path_efficiency": rounded(base.path_efficiency(m5)),
        "elapsed_fraction": rounded(elapsed / (end - start)),
        "atr_fraction_of_price": rounded(atr / reference),
        "checkpoint_spread_r": rounded(spread_r),
        "tick_volume_robust_z60": rounded(volume_z),
        "quote_density": rounded((right - left) / elapsed) if elapsed > 0 else None,
        "nearest_ahead_level_r": rounded(min(ahead, 5.0)) if ahead is not None else None,
        "nearest_behind_level_r": rounded(min(behind, 5.0)) if behind is not None else None,
        "levels_within_0p5atr": nearby,
        "aligned_level_acceptance": aligned_acceptance,
        "opposite_sweep_reclaim": opposite_reclaim,
        "event_within_240m": int(minutes_to_event is not None and 0 <= int(minutes_to_event) <= 240),
        "point_in_time": True,
        "unavailable_contexts": [
            "EXACT_MEETING_PROBABILITIES", "OPTIONS_DEALER_GAMMA",
            "CENTRALIZED_ORDER_FLOW_EXCEPT_EXISTING_GOLD_SUBSET", "UNSCHEDULED_NEWS_SENTIMENT",
        ],
    }
    row = base.normalize_payload(row)
    row["feature_lineage_hash"] = canonical_hash(row)
    return row


def fold_for(session_date: str) -> int | None:
    day = date.fromisoformat(session_date)
    for number, start, end in FOLDS:
        if start <= day < end:
            return number
    return None


def resolved_label(row: Mapping[str, Any]) -> int | None:
    reason = str(row.get("exit_reason", ""))
    if reason in {"TARGET", "TARGET_GAP"}:
        return 1
    if reason in {"STOP", "STOP_GAP", "STOP_FIRST_AMBIGUOUS"}:
        return 0
    return None


def benjamini_hochberg(pairs: Sequence[tuple[str, float | None]]) -> dict[str, float | None]:
    valid = sorted(((key, float(value)) for key, value in pairs if value is not None and math.isfinite(float(value))), key=lambda item: item[1])
    result: dict[str, float | None] = {key: None for key, _ in pairs}
    running = 1.0
    total = len(valid)
    for rank in range(total, 0, -1):
        key, value = valid[rank - 1]
        running = min(running, value * total / rank)
        result[key] = min(1.0, running)
    return result


def holm_adjust(pairs: Sequence[tuple[str, float | None]]) -> dict[str, float | None]:
    valid = sorted(((key, float(value)) for key, value in pairs if value is not None and math.isfinite(float(value))), key=lambda item: item[1])
    result: dict[str, float | None] = {key: None for key, _ in pairs}
    running = 0.0
    total = len(valid)
    for index, (key, value) in enumerate(valid):
        running = max(running, (total - index) * value)
        result[key] = min(1.0, running)
    return result


def training_transform(train_values: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    finite = train_values[np.isfinite(train_values)]
    if len(finite) == 0:
        median, low, high, scale = 0.0, -1.0, 1.0, 1.0
    else:
        median = float(np.median(finite))
        low, high = float(np.quantile(finite, 0.01)), float(np.quantile(finite, 0.99))
        clipped = np.clip(finite, low, high)
        scale = float(np.std(clipped))
        if scale <= 1e-12:
            scale = 1.0
    filled = np.where(np.isfinite(values), values, median)
    transformed = (np.clip(filled, low, high) - median) / scale
    return transformed, {"median": median, "low": low, "high": high, "scale": scale}


def oof_univariate(rows: Sequence[Mapping[str, Any]], feature: str, interaction: tuple[str, str] | None = None) -> dict[str, Any]:
    predictions: list[float] = []
    labels: list[int] = []
    baselines: list[float] = []
    for _, valid_start, valid_end in FOLDS:
        train = [row for row in rows if date.fromisoformat(str(row["session_date"])) < valid_start and row.get("target_before_stop") is not None]
        valid = [row for row in rows if valid_start <= date.fromisoformat(str(row["session_date"])) < valid_end and row.get("target_before_stop") is not None]
        if len(train) < 400 or len(valid) < 100:
            continue
        fields = [feature] if interaction is None else [interaction[0], interaction[1]]
        train_columns: list[np.ndarray] = []
        valid_columns: list[np.ndarray] = []
        for field in fields:
            train_raw = np.asarray([float(row[field]) if row.get(field) is not None else np.nan for row in train])
            valid_raw = np.asarray([float(row[field]) if row.get(field) is not None else np.nan for row in valid])
            train_transformed, fitted = training_transform(train_raw, train_raw)
            valid_filled = np.where(np.isfinite(valid_raw), valid_raw, fitted["median"])
            valid_transformed = (np.clip(valid_filled, fitted["low"], fitted["high"]) - fitted["median"]) / fitted["scale"]
            train_columns.append(train_transformed)
            valid_columns.append(valid_transformed)
        if interaction is not None:
            train_columns.append(train_columns[0] * train_columns[1])
            valid_columns.append(valid_columns[0] * valid_columns[1])
        x_train = np.column_stack(train_columns)
        x_valid = np.column_stack(valid_columns)
        y_train = np.asarray([int(row["target_before_stop"]) for row in train])
        y_valid = np.asarray([int(row["target_before_stop"]) for row in valid])
        if len(np.unique(y_train)) < 2:
            continue
        model = LogisticRegression(C=0.25, solver="lbfgs", max_iter=1_000, random_state=ROUTER_SEED)
        model.fit(x_train, y_train)
        probabilities = model.predict_proba(x_valid)[:, 1]
        predictions.extend(probabilities.tolist())
        labels.extend(y_valid.tolist())
        baselines.extend([float(np.mean(y_train))] * len(y_valid))
    if not labels:
        return {"oof_support": 0, "brier": None, "baseline_brier": None, "brier_improvement": None}
    y = np.asarray(labels)
    p = np.asarray(predictions)
    b = np.asarray(baselines)
    score = float(brier_score_loss(y, p))
    baseline = float(np.mean((y - b) ** 2))
    return {"oof_support": len(labels), "brier": rounded(score), "baseline_brier": rounded(baseline), "brier_improvement": rounded(baseline - score)}


def annual_spearman(rows: Sequence[Mapping[str, Any]], values: Sequence[float]) -> dict[str, Any]:
    by_year: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for row, value in zip(rows, values):
        if math.isfinite(value) and row.get("target_before_stop") is not None:
            by_year[str(row["session_date"])[:4]].append((value, int(row["target_before_stop"])))
    output: dict[str, Any] = {}
    for year, pairs in sorted(by_year.items()):
        if len(pairs) < 100 or len({item[1] for item in pairs}) < 2:
            output[year] = {"support": len(pairs), "rho": None, "p": None}
            continue
        rho, p_value = stats.spearmanr([item[0] for item in pairs], [item[1] for item in pairs])
        output[year] = {"support": len(pairs), "rho": rounded(float(rho)), "p": rounded(float(p_value))}
    return output


def stage1_tests(joined: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for timeframe in base.TIMEFRAMES:
        rows = [row for row in joined if row["timeframe"] == timeframe and row.get("target_before_stop") is not None]
        for feature in NUMERIC_FEATURES:
            usable = [row for row in rows if row.get(feature) is not None and math.isfinite(float(row[feature]))]
            test_id = f"S1::{timeframe}::{feature}"
            if len(usable) < 800 or len({int(row["target_before_stop"]) for row in usable}) < 2:
                results.append({"test_id": test_id, "timeframe": timeframe, "feature": feature, "support": len(usable), "verdict": "SUPPORT_FAIL", "raw_p": None})
                continue
            values = [float(row[feature]) for row in usable]
            labels = [int(row["target_before_stop"]) for row in usable]
            rho, p_value = stats.spearmanr(values, labels)
            annual = annual_spearman(usable, values)
            oof = oof_univariate(usable, feature)
            results.append({
                "test_id": test_id, "timeframe": timeframe, "feature": feature, "support": len(usable),
                "rho": rounded(float(rho)), "raw_p": rounded(float(p_value)), "annual": annual,
                "oof": oof, "verdict": "PENDING_MULTIPLICITY",
            })
    adjusted = benjamini_hochberg([(row["test_id"], row.get("raw_p")) for row in results])
    for row in results:
        row["bh_q"] = rounded(adjusted[row["test_id"]])
        if row["verdict"] == "SUPPORT_FAIL":
            row["failed_gates"] = ["SUPPORT_LT_800"]
            continue
        rho = float(row["rho"])
        annual_rhos = [float(item["rho"]) for item in row["annual"].values() if item["rho"] is not None]
        stable = sum(np.sign(value) == np.sign(rho) for value in annual_rhos)
        failures: list[str] = []
        if row["bh_q"] is None or float(row["bh_q"]) > 0.05:
            failures.append("BH_Q_GT_0P05")
        if abs(rho) < 0.03:
            failures.append("ABS_RHO_LT_0P03")
        if stable < 3:
            failures.append("ANNUAL_SIGN_STABILITY_LT_3")
        if row["oof"]["brier_improvement"] is None or float(row["oof"]["brier_improvement"]) < 0.001:
            failures.append("OOF_BRIER_IMPROVEMENT_LT_0P001")
        row["annual_matching_signs"] = stable
        row["failed_gates"] = failures
        row["verdict"] = "PASS_RELATIONSHIP" if not failures else "REJECT"
    return base.normalize_payload(results)


def stage2_tests(joined: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for timeframe in base.TIMEFRAMES:
        rows = [row for row in joined if row["timeframe"] == timeframe and row.get("target_before_stop") is not None]
        for name, first, second in INTERACTIONS:
            usable = [row for row in rows if row.get(first) is not None and row.get(second) is not None]
            test_id = f"S2::{timeframe}::{name}"
            if len(usable) < 800 or len({int(row["target_before_stop"]) for row in usable}) < 2:
                results.append({"test_id": test_id, "timeframe": timeframe, "interaction": name, "fields": [first, second], "support": len(usable), "verdict": "SUPPORT_FAIL", "raw_p": None})
                continue
            first_values = np.asarray([float(row[first]) for row in usable])
            second_values = np.asarray([float(row[second]) for row in usable])
            first_scaled, _ = training_transform(first_values, first_values)
            second_scaled, _ = training_transform(second_values, second_values)
            interaction_values = first_scaled * second_scaled
            labels = np.asarray([int(row["target_before_stop"]) for row in usable])
            rho, p_value = stats.spearmanr(interaction_values, labels)
            annual = annual_spearman(usable, interaction_values.tolist())
            oof_main = oof_univariate(usable, first, interaction=None)
            oof_interaction = oof_univariate(usable, first, interaction=(first, second))
            incremental = None
            if oof_main["brier"] is not None and oof_interaction["brier"] is not None:
                incremental = float(oof_main["brier"]) - float(oof_interaction["brier"])
            results.append({
                "test_id": test_id, "timeframe": timeframe, "interaction": name, "fields": [first, second],
                "support": len(usable), "rho": rounded(float(rho)), "raw_p": rounded(float(p_value)),
                "annual": annual, "oof_main": oof_main, "oof_interaction": oof_interaction,
                "incremental_brier_improvement": rounded(incremental), "verdict": "PENDING_MULTIPLICITY",
            })
    adjusted = holm_adjust([(row["test_id"], row.get("raw_p")) for row in results])
    for row in results:
        row["holm_p"] = rounded(adjusted[row["test_id"]])
        if row["verdict"] == "SUPPORT_FAIL":
            row["failed_gates"] = ["SUPPORT_LT_800"]
            continue
        rho = float(row["rho"])
        annual_rhos = [float(item["rho"]) for item in row["annual"].values() if item["rho"] is not None]
        stable = sum(np.sign(value) == np.sign(rho) for value in annual_rhos)
        failures: list[str] = []
        if row["holm_p"] is None or float(row["holm_p"]) > 0.05:
            failures.append("HOLM_P_GT_0P05")
        if abs(rho) < 0.03:
            failures.append("ABS_RHO_LT_0P03")
        if stable < 3:
            failures.append("ANNUAL_SIGN_STABILITY_LT_3")
        if row["incremental_brier_improvement"] is None or float(row["incremental_brier_improvement"]) < 0.001:
            failures.append("INCREMENTAL_OOF_BRIER_LT_0P001")
        row["annual_matching_signs"] = stable
        row["failed_gates"] = failures
        row["verdict"] = "PASS_RELATIONSHIP" if not failures else "REJECT"
    return base.normalize_payload(results)


def numeric_matrix_fit(rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, dict[str, dict[str, float]]]:
    columns: list[np.ndarray] = []
    transforms: dict[str, dict[str, float]] = {}
    for feature in NUMERIC_FEATURES:
        raw = np.asarray([float(row[feature]) if row.get(feature) is not None else np.nan for row in rows])
        transformed, fitted = training_transform(raw, raw)
        columns.append(transformed)
        transforms[feature] = fitted
    return np.column_stack(columns), transforms


def numeric_matrix_apply(rows: Sequence[Mapping[str, Any]], transforms: Mapping[str, Mapping[str, float]]) -> np.ndarray:
    columns: list[np.ndarray] = []
    for feature in NUMERIC_FEATURES:
        fitted = transforms[feature]
        raw = np.asarray([float(row[feature]) if row.get(feature) is not None else np.nan for row in rows])
        filled = np.where(np.isfinite(raw), raw, float(fitted["median"]))
        columns.append((np.clip(filled, float(fitted["low"]), float(fitted["high"])) - float(fitted["median"])) / float(fitted["scale"]))
    return np.column_stack(columns)


def categorical_matrix(rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, list[str]]:
    columns: list[np.ndarray] = []
    names: list[str] = []
    for field in CATEGORICAL_FEATURES:
        for category in CATEGORY_REGISTRY[field]:
            columns.append(np.asarray([1.0 if str(row[field]) == category else 0.0 for row in rows]))
            names.append(f"{field}=={category}")
    return np.column_stack(columns), names


def design_fit(rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, dict[str, dict[str, float]], list[str]]:
    numeric, transforms = numeric_matrix_fit(rows)
    categorical, names = categorical_matrix(rows)
    return np.column_stack((numeric, categorical)), transforms, list(NUMERIC_FEATURES) + names


def design_apply(rows: Sequence[Mapping[str, Any]], transforms: Mapping[str, Mapping[str, float]]) -> np.ndarray:
    numeric = numeric_matrix_apply(rows, transforms)
    categorical, _ = categorical_matrix(rows)
    return np.column_stack((numeric, categorical))


def oof_router(joined: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    fold_models: list[dict[str, Any]] = []
    for number, valid_start, valid_end in FOLDS:
        train = [row for row in joined if date.fromisoformat(str(row["session_date"])) < valid_start and row.get("target_before_stop") is not None]
        valid = [row for row in joined if valid_start <= date.fromisoformat(str(row["session_date"])) < valid_end]
        if len(train) < 1_000 or len(valid) < 500:
            raise ValueError(f"Router fold {number} lacks frozen support")
        x_train, transforms, feature_names = design_fit(train)
        x_valid = design_apply(valid, transforms)
        y_train = np.asarray([int(row["target_before_stop"]) for row in train])
        model = DecisionTreeClassifier(
            criterion="log_loss", max_depth=3, min_samples_leaf=200,
            random_state=ROUTER_SEED,
        )
        model.fit(x_train, y_train)
        probabilities = model.predict_proba(x_valid)[:, 1]
        leaves = model.apply(x_valid)
        prevalence = float(np.mean(y_train))
        fold_models.append({
            "fold": number, "train_rows": len(train), "validation_rows": len(valid),
            "training_prevalence": rounded(prevalence), "tree": export_text(model, feature_names=feature_names, decimals=6),
            "tree_hash": canonical_hash({"children_left": model.tree_.children_left.tolist(), "children_right": model.tree_.children_right.tolist(), "feature": model.tree_.feature.tolist(), "threshold": base.normalize_payload(model.tree_.threshold.tolist()), "value": base.normalize_payload(model.tree_.value.tolist())}),
            "transforms_hash": canonical_hash(transforms),
        })
        for row, probability, leaf in zip(valid, probabilities, leaves):
            item = dict(row)
            item["fold"] = number
            item["predicted_probability"] = rounded(float(probability))
            item["training_prevalence"] = rounded(prevalence)
            item["router_leaf"] = int(leaf)
            item["predicted_net_ev_r"] = rounded(2.0 * float(probability) - 1.0 - float(row["estimated_cost_r"]))
            item["router_positive"] = bool(float(item["predicted_net_ev_r"]) > 0.05 and item.get("size_executable", False))
            predictions.append(item)
    predictions.sort(key=lambda row: (row["session_date"], row["instrument"], row["session"], row["case_id"], TIMEFRAME_PRIORITY[row["timeframe"]]))
    return base.normalize_payload(predictions), {"fold_models": fold_models}


def route_portfolio(predictions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in predictions:
        if row.get("router_positive"):
            by_case[str(row["case_id"])].append(row)
    chosen: list[dict[str, Any]] = []
    for values in by_case.values():
        row = min(values, key=lambda item: (int(item["entry_minute"]), TIMEFRAME_PRIORITY[str(item["timeframe"])]))
        item = dict(row)
        item["case_route_disposition"] = "EARLIEST_POSITIVE_CHECKPOINT"
        item["portfolio_accepted"] = False
        item["portfolio_net_r"] = 0.0
        item["portfolio_stress_net_r"] = 0.0
        item["portfolio_net_pnl_usd"] = 0.0
        chosen.append(item)
    chosen.sort(key=lambda row: (int(row["entry_minute"]), row["instrument"], row["case_id"], TIMEFRAME_PRIORITY[row["timeframe"]]))
    active_until: dict[str, int] = {}
    for row in chosen:
        cluster = str(row["cluster"])
        if int(row["entry_minute"]) < active_until.get(cluster, -1):
            row["portfolio_rejection"] = "CONCURRENT_CLUSTER_RISK_CAP"
            continue
        row["portfolio_accepted"] = True
        row["portfolio_net_r"] = row["realized_net_r"]
        row["portfolio_stress_net_r"] = row["realized_stress_net_r"]
        row["portfolio_net_pnl_usd"] = row["realized_net_pnl_usd"]
        active_until[cluster] = int(row["exit_minute"]) + 1
    return base.normalize_payload(chosen)


def maximum_drawdown(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    equity = peak = drawdown = 0.0
    for row in sorted(rows, key=lambda item: (int(item["entry_minute"]), item["instrument"], item["case_id"])):
        equity += float(row[field])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def profit_factor(values: Sequence[float]) -> float | None:
    positive = sum(value for value in values if value > 0)
    negative = -sum(value for value in values if value < 0)
    return positive / negative if negative > 0 else None


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(row["session_date"])].append(float(row["portfolio_net_r"]))
    dates = sorted(groups)
    if len(dates) < 30:
        return {"clusters": len(dates), "ci95": [None, None], "p_mean_lte_zero": None, "checksum": None}
    values = np.asarray([sum(groups[key]) for key in dates], dtype=float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(BOOTSTRAP_RESAMPLES)
    for index in range(BOOTSTRAP_RESAMPLES):
        means[index] = float(np.mean(rng.choice(values, size=len(values), replace=True)))
    return {
        "clusters": len(dates), "resamples": BOOTSTRAP_RESAMPLES,
        "ci95": [rounded(float(np.quantile(means, 0.025))), rounded(float(np.quantile(means, 0.975)))],
        "p_mean_lte_zero": rounded(float(np.mean(means <= 0))),
        "checksum": hashlib.sha256(means.tobytes()).hexdigest(),
    }


def calibration_metrics(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [row for row in predictions if row.get("target_before_stop") is not None]
    if not rows:
        return {"support": 0}
    y = np.asarray([int(row["target_before_stop"]) for row in rows])
    p = np.asarray([float(row["predicted_probability"]) for row in rows])
    baseline = np.asarray([float(row["training_prevalence"]) for row in rows])
    brier = float(np.mean((y - p) ** 2))
    reference = float(np.mean((y - baseline) ** 2))
    ece = 0.0
    bins: list[dict[str, Any]] = []
    for lower in np.linspace(0.0, 0.9, 10):
        upper = lower + 0.1
        mask = (p >= lower) & (p < upper if upper < 1.0 else p <= upper)
        if not np.any(mask):
            continue
        observed = float(np.mean(y[mask]))
        predicted = float(np.mean(p[mask]))
        weight = float(np.mean(mask))
        ece += weight * abs(observed - predicted)
        bins.append({"lower": rounded(lower), "upper": rounded(upper), "support": int(np.sum(mask)), "predicted": rounded(predicted), "observed": rounded(observed)})
    return {
        "support": len(rows), "brier": rounded(brier), "reference_brier": rounded(reference),
        "brier_skill": rounded(1.0 - brier / reference) if reference > 0 else None,
        "ece": rounded(ece), "bins": bins,
    }


def group_performance(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {
        key: {"trades": len(values), "net_r": rounded(sum(float(row["portfolio_net_r"]) for row in values)), "stress_net_r": rounded(sum(float(row["portfolio_stress_net_r"]) for row in values))}
        for key, values in sorted(groups.items())
    }


def router_metrics(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    routed = route_portfolio(predictions)
    accepted = [row for row in routed if row["portfolio_accepted"]]
    values = [float(row["portfolio_net_r"]) for row in accepted]
    stress = [float(row["portfolio_stress_net_r"]) for row in accepted]
    years = group_performance(accepted, "calendar_year")
    folds = group_performance(accepted, "fold")
    sessions = group_performance(accepted, "session")
    instruments = group_performance(accepted, "instrument")
    clusters = group_performance(accepted, "cluster")
    positive_years = [item["net_r"] for item in years.values() if float(item["net_r"]) > 0]
    positive_sessions = [item["net_r"] for item in sessions.values() if float(item["net_r"]) > 0]
    concentration_year = max(positive_years) / sum(positive_years) if positive_years else None
    concentration_session = max(positive_sessions) / sum(positive_sessions) if positive_sessions else None
    bootstrap = cluster_bootstrap(accepted)
    calibration = calibration_metrics(predictions)
    metrics = {
        "candidate_id": "GLOBAL_SHALLOW_TREE_ROUTER_V0_1",
        "prediction_rows": len(predictions), "router_positive_rows": sum(bool(row["router_positive"]) for row in predictions),
        "routed_cases": len(routed), "accepted_trades": len(accepted), "trades_per_month": rounded(len(accepted) / 36.0),
        "win_rate": rounded(sum(value > 0 for value in values) / len(values)) if values else None,
        "net_expectancy_r": rounded(float(np.mean(values))) if values else None,
        "stress_expectancy_r": rounded(float(np.mean(stress))) if stress else None,
        "profit_factor": rounded(profit_factor(values)), "stress_profit_factor": rounded(profit_factor(stress)),
        "net_r": rounded(sum(values)), "net_r_per_month": rounded(sum(values) / 36.0),
        "net_pnl_usd": rounded(sum(float(row["portfolio_net_pnl_usd"]) for row in accepted)),
        "dollars_per_month": rounded(sum(float(row["portfolio_net_pnl_usd"]) for row in accepted) / 36.0),
        "maximum_drawdown_r": rounded(maximum_drawdown(accepted, "portfolio_net_r")),
        "bootstrap": bootstrap, "calibration": calibration,
        "years": years, "folds": folds, "sessions": sessions, "instruments": instruments, "clusters": clusters,
        "positive_year_count": len(positive_years),
        "positive_fold_count": sum(float(item["net_r"]) > 0 for item in folds.values()),
        "maximum_positive_year_contribution_fraction": rounded(concentration_year),
        "maximum_positive_session_contribution_fraction": rounded(concentration_session),
    }
    gates = {
        "accepted_trades_gte_180": len(accepted) >= 180,
        "trades_per_month_gte_5": len(accepted) / 36.0 >= 5.0,
        "net_expectancy_gt_zero": bool(values) and float(np.mean(values)) > 0,
        "profit_factor_gte_1p10": profit_factor(values) is not None and float(profit_factor(values)) >= 1.10,
        "cluster_ci95_low_gt_zero": bootstrap["ci95"][0] is not None and float(bootstrap["ci95"][0]) > 0,
        "stress_expectancy_gt_zero": bool(stress) and float(np.mean(stress)) > 0,
        "positive_folds_gte_4": metrics["positive_fold_count"] >= 4,
        "positive_years_gte_2": metrics["positive_year_count"] >= 2,
        "brier_skill_gt_zero": calibration.get("brier_skill") is not None and float(calibration["brier_skill"]) > 0,
        "ece_lte_0p05": calibration.get("ece") is not None and float(calibration["ece"]) <= 0.05,
        "maximum_drawdown_lte_15r": float(metrics["maximum_drawdown_r"]) <= 15.0,
        "year_concentration_lte_0p70": concentration_year is not None and concentration_year <= 0.70,
        "session_concentration_lte_0p70": concentration_session is not None and concentration_session <= 0.70,
    }
    metrics["gates"] = gates
    metrics["failed_gates"] = [key for key, passed in gates.items() if not passed]
    metrics["verdict"] = "PASS_PROVISIONAL_UNVALIDATED_CANDIDATE" if all(gates.values()) else "REJECT_ROUTER"
    return {"metrics": base.normalize_payload(metrics), "routed_rows": routed}
