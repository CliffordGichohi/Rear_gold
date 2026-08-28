#!/usr/bin/env python3
"""Fit and seal the outcome-blind same-month policy translator."""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    fit_preprocessing,
    load_certified_streams,
    materialize_case,
    prepare_features,
    require,
    rounded,
    serialize_tree,
    sha256_file,
    transform_rows,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    h4_damage_state,
    parse_dt,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    thesis_family,
)


CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_END_TO_END_SAME_MONTH_REPLICATION_V1.md"
CONTRACT_SHA256 = "8a3d3301ec5f382dc378e7554d313b95657a00adeaeb17826e5edf7b677fcd39"
CERTIFICATION = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "stream_materialization_certification.json"
)
LEDGER = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "ledgers"
    / "matched_human_visible_ledger.jsonl"
)
V2_SEAL = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_human_policy_v2"
    / "final_seal_v2.json"
)
AUTONOMOUS_V1_SEAL = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_autonomous_translation_v1"
    / "final_seal.json"
)
OUT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
)
TRANSLATOR = OUT / "translator.json"
CALIBRATION = OUT / "translator_calibration.json"
RANDOM_SEED = 20220821


def load_decisions() -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["event_type"] not in {"DECISION_SEALED", "NO_TRADE_SEALED"}:
            continue
        decision = dict(row["data"]["decision"])
        alias = str(decision["case_alias"])
        require(alias not in output, f"Duplicate human decision: {alias}")
        output[alias] = decision
    require(len(output) == 30, "Expected 30 visible human decisions")
    require(
        Counter(row["action"] for row in output.values())
        == Counter({"LONG": 16, "NO_TRADE": 14}),
        "Visible action population differs",
    )
    return output


def semantic_metrics(
    rows: list[dict[str, Any]], probabilities: np.ndarray, threshold: float
) -> dict[str, Any]:
    by_case: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_case.setdefault(str(row["case_alias"]), []).append(index)
    cases: list[dict[str, Any]] = []
    errors: list[float] = []
    for alias in sorted(by_case):
        indexes = sorted(by_case[alias], key=lambda index: rows[index]["checkpoint_at"])
        signal_index = next(
            (index for index in indexes if float(probabilities[index]) >= threshold),
            None,
        )
        first = rows[indexes[0]]
        action = str(first["human_action"])
        expected = (
            parse_dt(first["human_decision_at"]) if action == "LONG" else None
        )
        signalled = (
            parse_dt(rows[signal_index]["checkpoint_at"])
            if signal_index is not None
            else None
        )
        difference = (
            (expected - signalled).total_seconds() / 60.0
            if expected is not None and signalled is not None
            else None
        )
        matched = bool(
            action == "LONG"
            and difference is not None
            and 0.0 <= difference <= 1.0
        )
        false_positive = action == "NO_TRADE" and signalled is not None
        if matched:
            errors.append(float(difference))
        cases.append(
            {
                "case_alias": alias,
                "human_action": action,
                "human_decision_at": (
                    first["human_decision_at"] if action == "LONG" else None
                ),
                "scanner_signal_at": (
                    rows[signal_index]["checkpoint_at"]
                    if signal_index is not None
                    else None
                ),
                "difference_minutes": difference,
                "matched": matched,
                "false_positive": false_positive,
            }
        )
    matched = sum(row["matched"] for row in cases)
    false_positives = sum(row["false_positive"] for row in cases)
    median = float(np.median(errors)) if errors else math.inf
    maximum = max(errors) if errors else math.inf
    return {
        "matched_trade_days": matched,
        "false_positive_no_trade_days": false_positives,
        "median_timing_error_minutes": median,
        "maximum_timing_error_minutes": maximum,
        "semantic_pass": bool(
            matched == 16
            and false_positives == 0
            and median <= 1.0
            and maximum <= 1.0
        ),
        "cases": cases,
    }


def rank_candidate(record: dict[str, Any]) -> tuple[Any, ...]:
    metrics = record["metrics"]
    return (
        int(metrics["semantic_pass"]),
        int(metrics["matched_trade_days"]),
        -int(metrics["false_positive_no_trade_days"]),
        -float(metrics["median_timing_error_minutes"]),
        -float(metrics["maximum_timing_error_minutes"]),
        -int(record["node_count"]),
        -int(record["actual_depth"]),
        float(record["threshold"]),
    )


def main() -> None:
    require(sha256_file(CONTRACT) == CONTRACT_SHA256, "Frozen contract changed")
    v2_seal = json.loads(V2_SEAL.read_text(encoding="utf-8"))
    require(
        v2_seal["verdict"] == "PROMISING_EXPOSED_CALIBRATION_NOT_VALIDATED",
        "V2 predecessor verdict changed",
    )
    prior = json.loads(AUTONOMOUS_V1_SEAL.read_text(encoding="utf-8"))
    require(
        prior["status"] == "SEALED_FAIL_AUTONOMOUS_SEMANTICS",
        "Prior autonomous failure changed",
    )
    decisions = load_decisions()
    streams, lineage = load_certified_streams(CERTIFICATION, "primary")
    require(set(streams) == set(decisions), "Decision/source identities differ")
    prepared = prepare_features(streams.values())

    rows: list[dict[str, Any]] = []
    positive_rows: dict[str, dict[str, Any]] = {}
    for alias in sorted(streams):
        decision = decisions[alias]
        action = str(decision["action"])
        human_at = parse_dt(decision["expected_cursor_at"])
        case_rows = materialize_case(
            alias=alias,
            stream=streams[alias],
            prepared=prepared,
            end_at=human_at if action == "LONG" else None,
        )
        exact_positive = 0
        for row in case_rows:
            row["human_action"] = action
            row["human_decision_at"] = decision["expected_cursor_at"]
            row["label"] = bool(
                action == "LONG"
                and parse_dt(row["checkpoint_at"]) == human_at
            )
            if row["label"]:
                exact_positive += 1
                positive_rows[alias] = row
        require(
            exact_positive == (1 if action == "LONG" else 0),
            f"Decision timestamp is not represented exactly: {alias}",
        )
        rows.extend(case_rows)
    require(len(positive_rows) == 16, "Expected 16 positive calibration rows")

    schema = fit_preprocessing(rows)
    matrix = transform_rows(rows, schema)
    target = np.asarray([int(row["label"]) for row in rows], dtype=int)
    positive_weight = float((len(target) - target.sum()) / target.sum())
    candidates: list[dict[str, Any]] = []
    fitted: dict[str, DecisionTreeClassifier] = {}
    for depth in (6, 8, 10, 12, 16, None):
        for leaves in (16, 32, 64, 128, None):
            model = DecisionTreeClassifier(
                criterion="gini",
                max_depth=depth,
                max_leaf_nodes=leaves,
                min_samples_leaf=1,
                class_weight={0: 1.0, 1: positive_weight},
                random_state=RANDOM_SEED,
            )
            model.fit(matrix, target)
            probabilities = model.predict_proba(matrix)[:, list(model.classes_).index(1)]
            key = f"depth_{depth}_leaves_{leaves}"
            fitted[key] = model
            for threshold in (0.50, 0.75, 0.90):
                metrics = semantic_metrics(rows, probabilities, threshold)
                candidates.append(
                    {
                        "key": key,
                        "max_depth": depth,
                        "max_leaf_nodes": leaves,
                        "threshold": threshold,
                        "node_count": int(model.tree_.node_count),
                        "actual_depth": int(model.tree_.max_depth),
                        "metrics": metrics,
                    }
                )
    selected = max(candidates, key=rank_candidate)
    semantic_model = fitted[selected["key"]]
    semantic_tree = serialize_tree(
        semantic_model, schema["feature_names"], "BINARY_CLASSIFIER"
    )

    positive_aliases = sorted(positive_rows)
    geometry_rows = [positive_rows[alias] for alias in positive_aliases]
    geometry_matrix = transform_rows(geometry_rows, schema)
    stop_targets: list[float] = []
    target_targets: list[float] = []
    family_targets: list[str] = []
    geometry_labels: list[dict[str, Any]] = []
    for alias, row in zip(positive_aliases, geometry_rows, strict=True):
        decision = decisions[alias]
        reference = float(row["m1_reference_close"])
        atr = float(row["m15_atr_scale"])
        require(atr > 0, f"M15 ATR unavailable: {alias}")
        stop_distance = (reference - float(decision["stop"])) / atr
        target_distance = (float(decision["target"]) - reference) / atr
        require(
            stop_distance > 0 and target_distance > 0,
            f"Human geometry is not LONG ordered from observable reference: {alias}",
        )
        translated = dict(decision)
        translated["direction"] = "LONG"
        damage = h4_damage_state(
            streams[alias], decision["expected_cursor_at"], "LONG"
        )
        family = thesis_family(translated, damage)
        stop_targets.append(stop_distance)
        target_targets.append(target_distance)
        family_targets.append(family)
        geometry_labels.append(
            {
                "case_alias": alias,
                "checkpoint_at": row["checkpoint_at"],
                "reference_close": reference,
                "m15_atr": atr,
                "stop_distance_atr": stop_distance,
                "target_distance_atr": target_distance,
                "family": family,
            }
        )

    stop_model = DecisionTreeRegressor(
        max_depth=None, min_samples_leaf=1, random_state=RANDOM_SEED
    ).fit(geometry_matrix, np.asarray(stop_targets))
    target_model = DecisionTreeRegressor(
        max_depth=None, min_samples_leaf=1, random_state=RANDOM_SEED
    ).fit(geometry_matrix, np.asarray(target_targets))
    family_model = DecisionTreeClassifier(
        criterion="gini",
        max_depth=None,
        min_samples_leaf=1,
        random_state=RANDOM_SEED,
    ).fit(geometry_matrix, np.asarray(family_targets))
    predicted_stops = stop_model.predict(geometry_matrix)
    predicted_targets = target_model.predict(geometry_matrix)
    predicted_families = family_model.predict(geometry_matrix)
    geometry_checks: list[dict[str, Any]] = []
    for index, label in enumerate(geometry_labels):
        predicted_stop = float(label["reference_close"]) - float(
            predicted_stops[index]
        ) * float(label["m15_atr"])
        predicted_target = float(label["reference_close"]) + float(
            predicted_targets[index]
        ) * float(label["m15_atr"])
        original_stop = float(decisions[label["case_alias"]]["stop"])
        original_target = float(decisions[label["case_alias"]]["target"])
        geometry_checks.append(
            {
                "case_alias": label["case_alias"],
                "stop_absolute_error": abs(predicted_stop - original_stop),
                "target_absolute_error": abs(predicted_target - original_target),
                "family_expected": label["family"],
                "family_predicted": str(predicted_families[index]),
                "pass": bool(
                    abs(predicted_stop - original_stop) <= 0.01
                    and abs(predicted_target - original_target) <= 0.01
                    and str(predicted_families[index]) == label["family"]
                ),
            }
        )
    geometry_pass = all(row["pass"] for row in geometry_checks)
    semantic_pass = bool(selected["metrics"]["semantic_pass"])

    translator = {
        "version": "GOLD_COHERENT_AUCTION_END_TO_END_TRANSLATOR_V1_1_0",
        "status": (
            "PASS_PREPATH_TRANSLATOR_FREEZE"
            if semantic_pass and geometry_pass
            else "FAIL_PREPATH_TRANSLATOR_GATE"
        ),
        "evidence_status": "EXPOSED_IN_SAMPLE_TRANSLATION_ZERO_VALIDATION_CREDIT",
        "contract_sha256": CONTRACT_SHA256,
        "random_seed": RANDOM_SEED,
        "direction": "LONG",
        "preprocessing": schema,
        "semantic": {
            "tree": semantic_tree,
            "threshold": float(selected["threshold"]),
            "selected_configuration": {
                key: selected[key]
                for key in (
                    "key",
                    "max_depth",
                    "max_leaf_nodes",
                    "node_count",
                    "actual_depth",
                )
            },
            "metrics": selected["metrics"],
        },
        "geometry": {
            "reference": "LATEST_COMPLETED_M1_CLOSE",
            "scale": "COMPLETED_M15_ATR14",
            "stop_distance_tree": serialize_tree(
                stop_model, schema["feature_names"], "REGRESSOR"
            ),
            "target_distance_tree": serialize_tree(
                target_model, schema["feature_names"], "REGRESSOR"
            ),
            "family_tree": serialize_tree(
                family_model, schema["feature_names"], "MULTICLASS_CLASSIFIER"
            ),
            "checks": geometry_checks,
            "geometry_pass": geometry_pass,
        },
        "calibration": {
            "rows": len(rows),
            "positive_rows": int(target.sum()),
            "feature_count": len(schema["feature_names"]),
            "row_identity_sha256": canonical_hash(
                [
                    [row["case_alias"], row["checkpoint_at"], bool(row["label"])]
                    for row in rows
                ]
            ),
            "matrix_sha256": canonical_hash(
                {
                    "shape": list(matrix.shape),
                    "columns": schema["feature_names"],
                    "values": matrix.tolist(),
                    "target": target.tolist(),
                }
            ),
            "visible_ledger_sha256": sha256_file(LEDGER),
            "source_lineage_sha256": canonical_hash(lineage),
            "candidate_count": len(candidates),
            "candidate_registry_sha256": canonical_hash(
                [
                    {
                        key: value
                        for key, value in candidate.items()
                        if key != "metrics"
                    }
                    | {
                        "metrics": {
                            key: value
                            for key, value in candidate["metrics"].items()
                            if key != "cases"
                        }
                    }
                    for candidate in candidates
                ]
            ),
        },
        "outcome_ledger_opened": False,
        "postdecision_paths_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    translator["payload_sha256"] = canonical_hash(translator)
    OUT.mkdir(parents=True, exist_ok=True)
    TRANSLATOR.write_text(
        json.dumps(translator, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    calibration = {
        "version": "GOLD_COHERENT_AUCTION_END_TO_END_TRANSLATOR_CALIBRATION_V1_1_0",
        "status": translator["status"],
        "selected_semantic_metrics": selected["metrics"],
        "geometry_checks": geometry_checks,
        "geometry_label_distribution": dict(Counter(family_targets)),
        "translator_path": TRANSLATOR.relative_to(ROOT).as_posix(),
        "translator_sha256": sha256_file(TRANSLATOR),
        "outcomes_opened": False,
    }
    CALIBRATION.write_text(
        json.dumps(calibration, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": translator["status"],
                "rows": len(rows),
                "features": len(schema["feature_names"]),
                "selected_model": selected["key"],
                "selected_threshold": selected["threshold"],
                **{
                    key: value
                    for key, value in selected["metrics"].items()
                    if key != "cases"
                },
                "geometry_pass": geometry_pass,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
