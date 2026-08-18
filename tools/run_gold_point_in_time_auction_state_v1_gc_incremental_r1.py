from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_gold_point_in_time_auction_state_v1_development as core  # noqa: E402
import run_gold_point_in_time_auction_state_v1_gc_incremental as attempt  # noqa: E402


ATTEMPT_OUTPUT = attempt.OUTPUT
ATTEMPT_FREEZE = attempt.FREEZE
ATTEMPT_FAILURE = ATTEMPT_OUTPUT / "attempt_1_failure.json"
PRIMARY_FEATURES = ATTEMPT_OUTPUT / "primary_gc_checkpoint_features.parquet"
REFERENCE_FEATURES = ATTEMPT_OUTPUT / "reference_gc_checkpoint_features.parquet"

OUTPUT = core.ARTIFACTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_r1"
AMENDMENT = core.MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_amendment_a.json"
FINAL = core.MANIFESTS / "gold_point_in_time_auction_state_adaptive_management_v1_gc_incremental_r1_final_freeze.json"

EXPECTED = {
    "attempt_freeze": "92b15d83a8203d34942c5da6b7765af646fd5629f582f38a74b4d52b671e39e0",
    "primary_features": "eae9e88b893b319f3446691c455f02a280696b499aee6f2cb8e99834a99417cb",
    "reference_features": "eae9e88b893b319f3446691c455f02a280696b499aee6f2cb8e99834a99417cb",
}

_BASE_AVAILABILITY: dict[str, np.ndarray] = {}
_EXACT_TRANSFORMERS: dict[tuple[int, str, str], core.Transformer] = {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


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


def preflight() -> tuple[dict[str, Any], dict[str, Any]]:
    required = (ATTEMPT_FREEZE, ATTEMPT_FAILURE, PRIMARY_FEATURES, REFERENCE_FEATURES, attempt.BASE_RESULT, attempt.BASE_MODELS, attempt.BASE_PREDICTIONS)
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(ATTEMPT_FREEZE) != EXPECTED["attempt_freeze"]:
        raise ValueError("Attempt-1 protocol freeze changed")
    if sha256_file(PRIMARY_FEATURES) != EXPECTED["primary_features"] or sha256_file(REFERENCE_FEATURES) != EXPECTED["reference_features"]:
        raise ValueError("Attempt-1 GC feature payload changed")
    if sha256_file(PRIMARY_FEATURES) != sha256_file(REFERENCE_FEATURES):
        raise ValueError("Attempt-1 primary/reference GC features are not identical")
    failure = json.loads(ATTEMPT_FAILURE.read_text(encoding="utf-8"))
    if failure.get("status") != "FAIL_BASE_MODEL_SERIALIZATION_REPRODUCTION_GATE" or failure.get("analytical_result_produced") is True:
        raise ValueError("Unexpected Attempt-1 failure disposition")
    base = json.loads(attempt.BASE_RESULT.read_text(encoding="utf-8"))
    if base.get("development_verdict") != "REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE" or base.get("passing_candidates"):
        raise ValueError("Base development disposition changed")
    if any(path.exists() for path in (OUTPUT, AMENDMENT, FINAL)):
        raise FileExistsError("R1 output or freeze already exists")
    return failure, base


def amendment_payload(failure: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": "GOLD_PIT_AUCTION_STATE_V1_GC_INCREMENTAL_AMENDMENT_A_1_0",
        "status": "FROZEN_SERIALIZATION_ONLY_CORRECTION_BEFORE_R1_GC_OUTCOME_JOIN",
        "sealed_at_utc": core.utc_now(),
        "preserved": {
            "attempt_1_formal_failure": file_record(ATTEMPT_FAILURE),
            "attempt_1_protocol": file_record(ATTEMPT_FREEZE),
            "primary_gc_features": file_record(PRIMARY_FEATURES),
            "reference_gc_features": file_record(REFERENCE_FEATURES),
            "gc_features_byte_identical": True,
            "base_development_verdict": base["development_verdict"],
        },
        "confirmed_failure": failure["diagnosis"],
        "single_correction": {
            "old": "EXECUTE THE 12-DECIMAL TRANSFORMER QUANTILES AND MOMENTS STORED IN FOLD_MODELS.JSON",
            "new": "DETERMINISTICALLY RECOMPUTE ONLY THE ORIGINAL TRANSFORMER QUANTILES AND MOMENTS FROM THE IDENTICAL SEALED TRAINING-FOLD ROWS;REUSE THE SEALED MODEL COEFFICIENTS, HYPERPARAMETERS AND BASE RATE UNCHANGED",
            "reason": "ADDITIVE VALUES AT A ROUNDED QUANTILE BOUNDARY CAN CHANGE BIN;THE ORIGINAL TRAINING SOURCES AND EXACT TRANSFORMER ALGORITHM ARE SEALED AND AVAILABLE",
            "base_prediction_reproduction_gate": {
                "probabilities_and_expected_net": "ABSOLUTE_ERROR_LTE_1E-8",
                "MFE_MAE_TIME": "ABSOLUTE_ERROR_DIVIDED_BY_MAX_1_ABS_SEALED_VALUE_LTE_1E-8",
                "scope": "EVERY MATCHED VALIDATION ROW_AND_ALL_EIGHT_OOF_FIELDS",
            },
        },
        "unchanged": [
            "GC_FEATURE_PAYLOADS_AND_DEFINITIONS", "BASE_MODEL_COEFFICIENTS", "HYPERPARAMETERS", "FOLDS",
            "OUTCOMES", "SUPPORT_GATES", "POLICY_GRID", "POLICY_SELECTION", "EXECUTION", "COSTS",
            "RISK", "OVERLAP", "INCREMENTAL_MULTIPLICITY_AND_PASS_GATES", "NO_STANDALONE_CREDIT",
        ],
        "implementation": file_record(Path(__file__).resolve()),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }


def base_availability(data: core.DataSet) -> np.ndarray:
    cached = _BASE_AVAILABILITY.get(data.timeframe)
    if cached is not None:
        return cached
    table = pq.read_table(core.FEATURES, columns=["row_id", "checkpoint_feature_available"], filters=[("timeframe", "=", data.timeframe)]).combine_chunks()
    identities = np.asarray(table["row_id"].to_pylist(), dtype=object)
    if len(identities) != data.n or not np.array_equal(identities, data.row_id):
        raise ValueError(f"Base-availability identity mismatch for {data.timeframe}")
    cached = np.asarray(table["checkpoint_feature_available"].to_numpy(), dtype=bool)
    _BASE_AVAILABILITY[data.timeframe] = cached
    return cached


def exact_transformer(bundle: core.ModelBundle, data: core.DataSet, fold: int, family: str) -> core.Transformer:
    key = (fold, data.timeframe, family)
    cached = _EXACT_TRANSFORMERS.get(key)
    if cached is not None:
        return cached
    protocol = json.loads(core.PROTOCOL.read_text(encoding="utf-8"))
    fold_record = next(item for item in protocol["folds"] if int(item["fold"]) == fold)
    validation_start = core.day_int(fold_record["validate"][0])
    training_days = np.unique(data.decision_day[data.decision_day < validation_start])
    fit_days, _calibration_days = core.split_training_dates(training_days, 0.2)
    eligible = data.training_checkpoint & base_availability(data) & data.outcome_available
    fit_indices = np.flatnonzero(eligible & np.isin(data.decision_day, fit_days))
    weights = core.case_weights(data.case_code[fit_indices])
    cached = core.Transformer.fit(family, data.numeric[fit_indices], list(bundle.transformer.categorical_sizes), weights)
    _EXACT_TRANSFORMERS[key] = cached
    return cached


def corrected_verify_base_bundle(
    bundle: core.ModelBundle,
    data: core.DataSet,
    indices: np.ndarray,
    fold: int,
    family: str,
) -> dict[str, Any]:
    bundle.transformer = exact_transformer(bundle, data, fold, family)
    available_indices = indices[data.feature_available[indices]]
    predicted = bundle.predict(data.numeric[available_indices], data.categorical[available_indices])
    sealed = pq.read_table(
        attempt.BASE_PREDICTIONS,
        columns=["row_id", "p_cont", "p_fail", "p_unresolved", "p_two", "expected_mfe", "expected_mae", "expected_time", "expected_net"],
        filters=[("fold", "=", fold), ("timeframe", "=", data.timeframe), ("model_family", "=", family)],
    ).combine_chunks()
    lookup = {str(identity): index for index, identity in enumerate(sealed["row_id"].to_pylist())}
    fields = ("p_cont", "p_fail", "p_unresolved", "p_two", "expected_mfe", "expected_mae", "expected_time", "expected_net")
    absolute: dict[str, float] = {}; scaled: dict[str, float] = {}
    for name in fields:
        expected = np.asarray([sealed[name][lookup[str(data.row_id[index])]].as_py() for index in available_indices], dtype=np.float64)
        difference = np.abs(expected - predicted[name])
        absolute[name] = float(np.max(difference)) if len(difference) else 0.0
        scaled[name] = float(np.max(difference / np.maximum(1.0, np.abs(expected)))) if len(difference) else 0.0
    direct_fields = ("p_cont", "p_fail", "p_unresolved", "p_two", "expected_net")
    if any(absolute[name] > 1e-8 for name in direct_fields) or any(scaled[name] > 1e-8 for name in ("expected_mfe", "expected_mae", "expected_time")):
        raise ValueError(f"Corrected base reproduction failed for {fold}/{data.timeframe}/{family}: absolute={absolute}, scaled={scaled}")
    return {
        "rows": len(available_indices), "status": "PASS_EXACT_TRANSFORMER_RECONSTRUCTION",
        "maximum_absolute_error": {key: rounded(value) for key, value in absolute.items()},
        "maximum_scaled_error": {key: rounded(value) for key, value in scaled.items()},
        "tolerance": 1e-8,
    }


def strip_trades(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in evaluation.items() if key != "trades"}


def main() -> None:
    failure, base = preflight()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(AMENDMENT, amendment_payload(failure, base))

    # Bounded monkeypatch: the frozen attempt implementation calls this verifier before
    # fitting either incremental comparator. It mutates only the reconstructed transformer.
    attempt.verify_base_bundle_reconstruction = corrected_verify_base_bundle

    protocol = json.loads(core.PROTOCOL.read_text(encoding="utf-8"))
    primary = attempt.run_evaluation("primary_r1", PRIMARY_FEATURES, protocol)
    reference = attempt.run_evaluation("reference_r1", REFERENCE_FEATURES, protocol)
    primary_serial = strip_trades(primary); reference_serial = strip_trades(reference)
    reproduction = canonical_hash(primary_serial) == canonical_hash(reference_serial)
    if not reproduction:
        raise ValueError("R1 primary/reference evaluation differs")
    comparisons = attempt.comparison_results(primary, protocol)
    passing = [row["candidate_id"] for row in comparisons if row["verdict"] == "ADDS_INCREMENTAL_VALUE"]
    verdict = "ADDS_PROVEN_INCREMENTAL_GC_VALUE_NO_STANDALONE_CREDIT" if passing else "NO_PROVEN_INCREMENTAL_GC_VALUE"
    result = {
        "version": "GOLD_PIT_AUCTION_STATE_V1_GC_INCREMENTAL_R1_FINAL_1_0",
        "status": "PASS_R1_INDEPENDENT_GC_INCREMENTAL_REPRODUCTION",
        "verdict": verdict, "completed_at_utc": core.utc_now(), "passing_incremental_comparisons": passing,
        "comparisons": comparisons, "coverage": primary["coverage"], "support_failures": primary["support_failures"],
        "attempt_1_failure_preserved": file_record(ATTEMPT_FAILURE), "amendment": file_record(AMENDMENT),
        "gc_feature_payloads_reused_unchanged": True, "evaluation_reproduction": reproduction,
        "base_development_verdict_preserved": base["development_verdict"], "standalone_candidate_credit": False,
        "forward_disposition": "KEEP_2025_2026_LOCKED", "prospective_ledger_initialized": False,
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    primary_path = OUTPUT / "primary_evaluation.json"; reference_path = OUTPUT / "reference_evaluation.json"
    write_json_exclusive(primary_path, primary_serial); write_json_exclusive(reference_path, reference_serial)
    report = ROOT / "GOLD_POINT_IN_TIME_AUCTION_STATE_AND_ADAPTIVE_MANAGEMENT_V1_GC_INCREMENTAL_R1_RESULTS.md"
    report.write_text(attempt.report_markdown(result), encoding="utf-8", newline="\n")
    result["artifacts"] = {
        "amendment": file_record(AMENDMENT), "attempt_1_failure": file_record(ATTEMPT_FAILURE),
        "primary_gc_features": file_record(PRIMARY_FEATURES), "reference_gc_features": file_record(REFERENCE_FEATURES),
        "primary_evaluation": file_record(primary_path), "reference_evaluation": file_record(reference_path), "report": file_record(report),
    }
    result_path = OUTPUT / "gc_incremental_r1_results.json"; write_json_exclusive(result_path, result); result["artifacts"]["result"] = file_record(result_path)
    write_json_exclusive(FINAL, result)
    print(canonical_json({"status": "COMPLETE", "verdict": verdict, "passing_incremental_comparisons": passing, "evaluation_reproduction": reproduction}), flush=True)


if __name__ == "__main__":
    main()
