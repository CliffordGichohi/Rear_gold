from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_artifacts" / "gold_h4_half_retrace_final_falsification_v1"
CONTRACT = ROOT / "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_V1.md"
SOURCE_SCRIPT = ROOT / "tools" / "run_gold_conditional_movement_policy_edge_v1.py"
SOURCE_FREEZE = ROOT / "research_manifests" / "gold_conditional_movement_policy_edge_v1_design_freeze.json"
SOURCE_PROTOCOL = ROOT / "research_manifests" / "gold_conditional_movement_policy_edge_v1_protocol.json"
SOURCE_RESULTS = ROOT / "research_artifacts" / "gold_trend_pullback_movement_anatomy_edge_v1_v01" / "primary_conditional_policy_results.json"
SOURCE_FINAL_SEAL = ROOT / "research_artifacts" / "gold_trend_pullback_movement_anatomy_edge_v1_v01" / "conditional_policy_final_seal.json"
SOURCE_MATRIX = ROOT / "research_artifacts" / "gold_trend_pullback_movement_anatomy_edge_v1_v01" / "trade_matrix_checkpoint_h4.npz"
SOURCE_FEATURES = ROOT / "research_artifacts" / "gold_trend_pullback_continuation_edge_v1_v01" / "primary_features.parquet"

CANDIDATE = "CMP::H4::RESPONSE_HALF_RETRACE_LIMIT::PIVOT_BUFFER_0P05_ATR::FIXED_2P0_R::TIME_8_PARENT_BARS"
EXECUTION = "RESPONSE_HALF_RETRACE_LIMIT::PIVOT_BUFFER_0P05_ATR::FIXED_2P0_R::TIME_8_PARENT_BARS"
FIT_ARTIFACT = OUTPUT / "full_development_model.json"
PRE_FORWARD_SEAL = OUTPUT / "pre_forward_model_seal.json"
STATE = OUTPUT / "state_pre_forward.json"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def load_source_module():
    spec = importlib.util.spec_from_file_location("cmp_v1_frozen", SOURCE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load frozen conditional-policy implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_predecessors() -> dict[str, dict[str, Any]]:
    paths = {
        "contract": CONTRACT,
        "source_script": SOURCE_SCRIPT,
        "source_freeze": SOURCE_FREEZE,
        "source_protocol": SOURCE_PROTOCOL,
        "source_results": SOURCE_RESULTS,
        "source_final_seal": SOURCE_FINAL_SEAL,
        "source_matrix_h4": SOURCE_MATRIX,
        "source_features": SOURCE_FEATURES,
    }
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    freeze = json.loads(SOURCE_FREEZE.read_text(encoding="utf-8"))
    if freeze["status"] != "FROZEN_BEFORE_CONDITIONAL_MODEL_OUTCOMES":
        raise ValueError("Conditional-policy design freeze is invalid")
    for item in freeze["sources"].values():
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Predecessor seal mismatch: {item['path']}")
    final_seal = json.loads(SOURCE_FINAL_SEAL.read_text(encoding="utf-8"))
    if final_seal["status"] != "REJECT_NO_CONDITIONAL_ECONOMIC_EDGE" or final_seal.get("forward_values_accessed") is not False:
        raise ValueError("Prior zero-candidate rejection or forward lock was not preserved")
    for item in final_seal["artifacts"].values():
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Prior final artifact changed: {item['path']}")
    return {name: record(path) for name, path in paths.items()}


def main() -> None:
    if FIT_ARTIFACT.exists() or PRE_FORWARD_SEAL.exists() or STATE.exists():
        raise FileExistsError("Final falsification pre-forward artifact already exists")

    sources = verify_predecessors()
    source_results = json.loads(SOURCE_RESULTS.read_text(encoding="utf-8"))
    prior = next(item for item in source_results["policies"] if item["policy_id"] == CANDIDATE)
    if prior["verdict"] != "REJECT_CONDITIONAL_POLICY":
        raise ValueError("The preserved development rejection is missing")

    module = load_source_module()
    module.selftest()
    protocol = json.loads(SOURCE_PROTOCOL.read_text(encoding="utf-8"))
    expected_model = {
        "type": "DecisionTreeRegressor",
        "max_depth": 3,
        "criterion": "squared_error",
        "splitter": "best",
        "random_state": 731911,
        "min_samples_leaf": {"M15": 120, "H1": 40, "H4": 15},
        "min_impurity_decrease": 0.0005,
        "prediction_trade_threshold_r": 0.05,
        "numeric_clip_quantiles": [0.01, 0.99],
        "numeric_imputation": "TRAINING_MEDIAN",
        "categorical_encoding": "TRAINING_ONE_HOT_HANDLE_UNKNOWN_IGNORE",
    }
    if protocol["model"] != expected_model:
        raise ValueError("Frozen model hyperparameters changed")

    case_ids, net, _stress, _pnl, _gross = module.load_payload("H4")
    specs = module.full_specs()
    column = specs.index(EXECUTION)
    features = module.feature_rows()
    indices = np.asarray(
        [index for index, case_id in enumerate(case_ids) if case_id in features and math.isfinite(float(net[index, column]))],
        dtype=np.int64,
    )
    rows = [features[case_ids[index]] for index in indices]
    state_primary = module.fit_transform_state(rows)
    matrix_primary = module.transform(rows, state_primary)
    tree_primary = module.fit_tree(
        matrix_primary,
        net[indices, column],
        state_primary["column_names"],
        min_leaf=15,
        max_depth=3,
        min_decrease=0.0005,
    )

    # Independent deterministic repeat over fresh objects.
    rows_reference = [dict(features[case_ids[index]]) for index in indices]
    state_reference = module.fit_transform_state(rows_reference)
    matrix_reference = module.transform(rows_reference, state_reference)
    tree_reference = module.fit_tree(
        matrix_reference,
        np.array(net[indices, column], copy=True),
        state_reference["column_names"],
        min_leaf=15,
        max_depth=3,
        min_decrease=0.0005,
    )
    if canonical_hash(state_primary) != canonical_hash(state_reference) or canonical_hash(tree_primary) != canonical_hash(tree_reference):
        raise ValueError("Independent full-development fits differ")
    prediction_primary = module.predict_tree(tree_primary, matrix_primary, "primary")
    prediction_reference = module.predict_tree(tree_reference, matrix_reference, "reference")
    if not np.array_equal(prediction_primary, prediction_reference):
        raise ValueError("Independent fitted predictions differ")

    training_ids = [case_ids[index] for index in indices]
    training_identity_hash = canonical_hash(training_ids)
    selected = prediction_primary >= 0.05
    fitted = {
        "version": "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_MODEL_1_0",
        "status": "FROZEN_FULL_DEVELOPMENT_MODEL_BEFORE_FORWARD_VALUES",
        "candidate_id": CANDIDATE,
        "execution": EXECUTION,
        "timeframe": "H4",
        "development_period": ["2021-08-01", "2024-12-31"],
        "development_evidence_classification": "HYPOTHESIS_GENERATION_ONLY",
        "prior_development_verdict_preserved": prior["verdict"],
        "predictor_registry": {"numeric": module.NUMERIC, "categorical": module.CATEGORICAL},
        "hyperparameters": expected_model,
        "transform": state_primary,
        "tree": tree_primary,
        "tree_hash": canonical_hash(tree_primary),
        "split_features": sorted(set(module.split_features(tree_primary))),
        "training_executable_rows": len(indices),
        "training_identity_hash": training_identity_hash,
        "training_prediction_checksum": hashlib.sha256(prediction_primary.astype("<f8").tobytes()).hexdigest(),
        "training_selected_rows_at_frozen_threshold": int(selected.sum()),
        "forward_protocol": {
            "segments": {"2025": ["2025-01-01", "2025-12-31"], "2026": ["2026-01-01", "2026-07-29"]},
            "support": {"2025": {"trades": 20, "dates": 15}, "2026": {"trades": 10, "dates": 8}},
            "bootstrap": {"resamples": 5000, "seed": 731911, "cluster": "NEW_YORK_TRADING_DATE", "interval": 0.90},
            "pass_gates": {
                "each_segment_expectancy_r_gt": 0.0,
                "combined_expectancy_r_gt": 0.0,
                "combined_ci90_lower_gt": 0.0,
                "combined_profit_factor_gte": 1.15,
                "combined_cost_1p5x_expectancy_r_gt": 0.0,
                "combined_max_drawdown_pct_lte": 15.0,
            },
            "support_failure_verdict": "INCONCLUSIVE_FORWARD_SUPPORT",
            "supported_failure_verdict": "REJECT_EXPOSED_FORWARD_ROBUSTNESS",
            "all_gates_pass_verdict": "PASS_EXPOSED_FORWARD_ROBUSTNESS",
        },
        "retuning_permitted": False,
        "alternative_execution_permitted": False,
        "second_candidate_permitted": False,
        "forward_values_accessed": False,
        "primary_reference_exact": True,
    }
    write_json_exclusive(FIT_ARTIFACT, fitted)

    seal = {
        "version": "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_PRE_FORWARD_SEAL_1_0",
        "status": fitted["status"],
        "sealed_at_utc": utc_now(),
        "authorization": "ONE_FINAL_POST_HOC_H4_HALF_RETRACE_FALSIFICATION",
        "sources": sources,
        "model_artifact": record(FIT_ARTIFACT),
        "model_content_hash": canonical_hash(fitted),
        "tree_hash": fitted["tree_hash"],
        "training_identity_hash": training_identity_hash,
        "forward_values_accessed": False,
        "retuning_permitted": False,
    }
    write_json_exclusive(PRE_FORWARD_SEAL, seal)
    write_json_exclusive(
        STATE,
        {
            "version": "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_STATE_1_0",
            "status": "READY_TO_OPEN_FORWARD_ONCE",
            "pre_forward_seal": record(PRE_FORWARD_SEAL),
            "forward_values_accessed": False,
            "next_step": "VERIFY_FORWARD_SOURCE_METADATA_THEN_OPEN_2025_AND_2026_ONCE",
        },
    )
    print(
        json.dumps(
            {
                "status": "READY_TO_OPEN_FORWARD_ONCE",
                "training_executable_rows": len(indices),
                "training_selected_rows": int(selected.sum()),
                "split_features": fitted["split_features"],
                "tree_hash": fitted["tree_hash"],
                "pre_forward_seal": record(PRE_FORWARD_SEAL),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
