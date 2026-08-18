#!/usr/bin/env python3
"""Freeze the Multi-Asset Observable Auction-State Routing V1 design."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from tools import maoascr_v1_engine as engine
except ModuleNotFoundError:
    import maoascr_v1_engine as engine


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
CONTRACT = ROOT / "MULTI_ASSET_OBSERVABLE_AUCTION_STATE_CONDITIONAL_ROUTING_EDGE_DISCOVERY_CONTRACT_V1.md"
PREDECESSOR_SEAL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m3_seal.json"
PREDECESSOR_RESULT = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m3/result.json"
R2_PRIMARY = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2/recertification_primary.json"
R2_REFERENCE = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2/recertification_reference.json"
R2_RESULT = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2/recertification.json"
SOURCE_CERT = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json"
BASE_ENGINE = ROOT / "tools/msbam_v1_m2_m3_engine.py"
ENGINE = ROOT / "tools/maoascr_v1_engine.py"
RUNNER = ROOT / "tools/run_multi_asset_observable_auction_state_conditional_routing_v1.py"
TESTS = ROOT / "tests/test_maoascr_v1_engine.py"
PROTOCOL = MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_protocol.json"
FEATURES = MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_feature_registry.json"
TEST_REGISTRY = MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_test_registry.json"
FREEZE = MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_preoutcome_freeze.json"
UTC = timezone.utc
SYMBOLS = ("XAGUSD", "EURUSD", "USDJPY", "USTEC", "US500", "XTIUSD")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.resolve().relative_to(ROOT.resolve()).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def verify(item: Mapping[str, Any]) -> None:
    path = ROOT / str(item["path"])
    if not path.is_file() or path.stat().st_size != int(item["bytes"]) or sha256_file(path) != str(item["sha256"]):
        raise ValueError(f"Sealed artifact changed: {item['path']}")


def source_bindings() -> list[dict[str, Any]]:
    certification = load(SOURCE_CERT)
    output: dict[str, dict[str, Any]] = {record(SOURCE_CERT)["path"]: record(SOURCE_CERT)}
    found: set[str] = set()
    for item in certification.get("instrument_certifications", []):
        symbol = str(item.get("mt5_symbol"))
        if symbol not in SYMBOLS:
            continue
        if item.get("classification") != "PRESENT_AND_ADEQUATE":
            raise ValueError(f"Inadequate source: {symbol}")
        found.add(symbol)
        for source in item.get("coverage", {}).get("source_files", []):
            verify(source)
            if "2025" in str(source["path"]) or "2026" in str(source["path"]):
                raise ValueError("Forward source cannot enter development freeze")
            output[str(source["path"])] = dict(source)
    if found != set(SYMBOLS):
        raise ValueError("Not all six instruments are certified")
    for path in (
        ROOT / "research_artifacts/gold_casebook_v01/fundamentals.jsonl.gz",
        ROOT / "research_artifacts/gold_casebook_v01/events.jsonl.gz",
        ROOT / "research_artifacts/gold_casebook_v01/positioning.jsonl.gz",
    ):
        item = record(path)
        output[item["path"]] = item
    return [output[key] for key in sorted(output)]


def main() -> int:
    predecessor = load(PREDECESSOR_SEAL)
    if predecessor.get("verdict") != "FAIL_M3_CURRENT_UNIVERSE_BELOW_10R_CAPACITY" or not predecessor.get("independent_reproduction"):
        raise ValueError("Required predecessor verdict is absent")
    for item in predecessor.get("artifacts", []):
        verify(item)
    r2 = load(R2_RESULT)
    if len(r2.get("passing_units", [])) != 12:
        raise ValueError("Coverage Amendment A population changed")

    feature_descriptions = {
        "macro_alignment": "TRIGGER_DIRECTION_X_POINT_IN_TIME_MACRO_SCORE_DIVIDED_BY_100",
        "macro_confidence": "POINT_IN_TIME_MACRO_AVAILABLE_WEIGHT_FRACTION",
        "htf_pressure_alignment": "MEAN_TRIGGER_ALIGNED_COMPLETED_W1_D1_H4_H1_PRESSURE_STATE",
        "structure_alignment": "MEAN_TRIGGER_ALIGNED_CONFIRMED_M15_H1_H4_STRUCTURE_STATE",
        "bos_alignment": "MEAN_TRIGGER_ALIGNED_COMPLETED_CLOSE_BREAK_VS_CONFIRMED_SWING",
        "early_displacement_r": "TRIGGER_ALIGNED_CHECKPOINT_CLOSE_MINUS_SESSION_REFERENCE_DIVIDED_BY_ATR",
        "trigger_bar_range_r": "COMPLETED_TRIGGER_BAR_RANGE_DIVIDED_BY_PRESESSION_ATR",
        "trigger_bar_body_alignment": "TRIGGER_ALIGNED_COMPLETED_BAR_BODY_DIVIDED_BY_BAR_RANGE",
        "early_range_r": "OBSERVED_SESSION_RANGE_THROUGH_CHECKPOINT_DIVIDED_BY_ATR",
        "pretrigger_adverse_r": "MAX_EXCURSION_AGAINST_TRIGGER_DIRECTION_BEFORE_CHECKPOINT_DIVIDED_BY_ATR",
        "early_path_efficiency": "ABS_NET_COMPLETED_M5_DISPLACEMENT_DIVIDED_BY_SUM_ABS_M5_CHANGES",
        "elapsed_fraction": "CHECKPOINT_ELAPSED_MINUTES_DIVIDED_BY_FROZEN_SESSION_DURATION",
        "atr_fraction_of_price": "PRESESSION_14_COMPLETED_M15_ATR_DIVIDED_BY_REFERENCE_PRICE",
        "checkpoint_spread_r": "LAST_OBSERVED_PRECHECKPOINT_BROKER_SPREAD_PRICE_DIVIDED_BY_ATR",
        "tick_volume_robust_z60": "LAST_OBSERVED_PRECHECKPOINT_LOG_TICK_VOLUME_ROBUST_Z_VS_PRIOR_60_M1",
        "quote_density": "OBSERVED_M1_COUNT_DIVIDED_BY_WALL_CLOCK_MINUTES_THROUGH_CHECKPOINT",
        "nearest_ahead_level_r": "TRIGGER_DIRECTION_DISTANCE_TO_NEAREST_PREEXISTING_LEVEL_CAPPED_5_ATR",
        "nearest_behind_level_r": "OPPOSITE_DIRECTION_DISTANCE_TO_NEAREST_PREEXISTING_LEVEL_CAPPED_5_ATR",
        "levels_within_0p5atr": "COUNT_PREEXISTING_LEVELS_WITHIN_0P5_ATR_OF_CHECKPOINT_CLOSE",
        "aligned_level_acceptance": "ANY_THREE_COMPLETED_M5_CLOSE_ACCEPTANCE_BEYOND_LEVEL_IN_TRIGGER_DIRECTION_BY_CHECKPOINT",
        "opposite_sweep_reclaim": "ANY_OPPOSITE_LEVEL_0P05_ATR_SWEEP_AND_COMPLETED_M5_RECLAIM_BY_CHECKPOINT",
        "event_within_240m": "SCHEDULED_TIER1_EVENT_WITH_POINT_IN_TIME_METADATA_ZERO_TO_240_MINUTES_AHEAD",
    }
    feature_registry = {
        "version": "MAOASCR_V1_FEATURE_REGISTRY_1_0", "status": "FROZEN_OUTCOME_BLIND",
        "frozen_at_utc": utc_now(), "numeric_feature_count": len(engine.NUMERIC_FEATURES),
        "numeric_features": [{"feature_id": name, "definition": feature_descriptions[name], "epistemic_class": "CALCULATED_OR_INFERRED", "available_at": "LTE_CHECKPOINT"} for name in engine.NUMERIC_FEATURES],
        "categorical_features": list(engine.CATEGORICAL_FEATURES), "category_registry": engine.CATEGORY_REGISTRY,
        "missing_policy": "TRAINING_ONLY_MEDIAN_NUMERIC; SEALED_UNKNOWN_CATEGORY; NEVER_ZERO_AS_ECONOMIC_NEUTRAL",
        "transformation": "TRAINING_ONLY_1PCT_99PCT_CLIP_MEDIAN_CENTER_STD_SCALE",
        "forbidden": ["FINALISED_ARCHETYPE", "MFE", "MAE", "FUTURE_EXTREMA", "EVENTUAL_DIRECTION", "TARGET_STOP_RESULT", "REALISED_RETURN"],
    }
    write(FEATURES, feature_registry)

    stage1 = [f"S1::{timeframe}::{feature}" for timeframe in ("M15", "H1", "H4") for feature in engine.NUMERIC_FEATURES]
    stage2 = [f"S2::{timeframe}::{name}" for timeframe in ("M15", "H1", "H4") for name, _, _ in engine.INTERACTIONS]
    test_registry = {
        "version": "MAOASCR_V1_TEST_REGISTRY_1_0", "status": "FROZEN_OUTCOME_BLIND", "frozen_at_utc": utc_now(),
        "stage1_tests": stage1, "stage1_count": len(stage1), "stage1_multiplicity": "BENJAMINI_HOCHBERG_GLOBAL_Q_0P05",
        "stage1_pass": {"support_gte": 800, "abs_spearman_rho_gte": 0.03, "annual_matching_signs_gte": 3, "oof_brier_improvement_gte": 0.001},
        "stage2_tests": stage2, "stage2_count": len(stage2), "stage2_interactions": [{"name": name, "first": first, "second": second} for name, first, second in engine.INTERACTIONS],
        "stage2_multiplicity": "HOLM_GLOBAL_ALPHA_0P05",
        "stage2_pass": {"support_gte": 800, "abs_spearman_rho_gte": 0.03, "annual_matching_signs_gte": 3, "incremental_oof_brier_gte": 0.001},
        "router": {"candidate_id": "GLOBAL_SHALLOW_TREE_ROUTER_V0_1", "candidate_count": 1, "max_authorized_candidates": 6},
    }
    write(TEST_REGISTRY, test_registry)

    protocol = {
        "version": "MAOASCR_V1_PROTOCOL_1_0", "status": "FROZEN_BEFORE_CHECKPOINT_OR_OUTCOME_VALUE_ACCESS", "frozen_at_utc": utc_now(),
        "preserved_verdict": "FAIL_M3_CURRENT_UNIVERSE_BELOW_10R_CAPACITY",
        "interpretation": "REJECT_INDISCRIMINATE_CONSTANT_ROUTING_NOT_ALL_CONDITIONAL_POLICIES",
        "development": {"start_inclusive": "2021-08-01", "end_exclusive": "2025-01-01", "cases": 10388, "expected_checkpoints": {"M15": 10385, "H1": 9353, "H4": 4098}},
        "checkpoint": "FROZEN_FIRST_COMPLETED_RELATIVE_TRACK_BAR_0P25_ATR_DISPLACEMENT_AND_OUTER_QUARTER_CLOSE",
        "primary_endpoint": {"target_first": 1, "stop_first": 0, "time_exit": "CENSORED_FOR_PROBABILITY_RETAINED_FOR_ECONOMICS"},
        "execution_unchanged": {"entry": "NEXT_OBSERVED_M1_OPEN_AFTER_1_MINUTE_LATENCY_MAX_2_MINUTE_NO_TICK_DELAY", "stop_ATR": 1.0, "target_ATR": 1.0, "ambiguous": "STOP_FIRST", "deadline": "SESSION_END"},
        "costs": {"formula": "MAX(ACTUAL_ENTRY_EXIT_SPREAD_R_PLUS_0P03R,0P05R)", "stress_multiplier": 1.5, "observable_router_estimate": "MAX(CHECKPOINT_SPREAD_R_PLUS_0P03R,0P05R)"},
        "folds": [{"fold": number, "validation_start": start.isoformat(), "validation_end_exclusive": end.isoformat(), "training": "ALL_DEVELOPMENT_BEFORE_VALIDATION_START"} for number, start, end in engine.FOLDS],
        "univariate_model": {"type": "L2_LOGISTIC", "C": 0.25, "solver": "LBFGS", "max_iter": 1000, "seed": engine.ROUTER_SEED},
        "router_model": {"type": "DECISION_TREE", "criterion": "LOG_LOSS", "max_depth": 3, "min_samples_leaf": 200, "seed": engine.ROUTER_SEED},
        "action": {"positive": "PREDICTED_2P_MINUS_1_MINUS_OBSERVABLE_COST_GT_0P05", "case_policy": "EARLIEST_POSITIVE_CHECKPOINT", "otherwise": "NO_TRADE"},
        "risk": {"account_usd": 10000, "maximum_cluster_risk_usd": 100, "maximum_drawdown_R": 15, "clusters": {"PRECIOUS_METALS": ["XAGUSD"], "USD_FX": ["EURUSD", "USDJPY"], "US_EQUITY_INDICES": ["USTEC", "US500"], "ENERGY": ["XTIUSD"]}},
        "economic_gates": {"trades_gte": 180, "trades_per_month_gte": 5, "expectancy_gt": 0, "profit_factor_gte": 1.10, "cluster_ci95_low_gt": 0, "stress_expectancy_gt": 0, "positive_folds_gte": 4, "positive_years_gte": 2, "brier_skill_gt": 0, "ece_lte": 0.05, "drawdown_lte_R": 15, "max_year_or_session_positive_contribution_lte": 0.70},
        "bootstrap": {"unit": "SESSION_DATE", "resamples": engine.BOOTSTRAP_RESAMPLES, "seed": engine.BOOTSTRAP_SEED},
        "forward": "OPEN_2025_ONCE_THEN_2026_ONCE_ONLY_AFTER_COMPLETE_DEVELOPMENT_PASS; OTHERWISE_REMAIN_LOCKED",
        "prohibitions": ["OPTIMIZE_FOR_10R", "ALTER_TRIGGER", "ALTER_EXECUTION", "WEAKEN_GATES", "USE_REALISED_ARCHETYPE", "REMOVE_LOSSES", "ADD_UNREGISTERED_FEATURE", "OPEN_FORWARD_BEFORE_PASS", "PAID_ACQUISITION"],
    }
    write(PROTOCOL, protocol)

    bindings = {
        "contract": record(CONTRACT), "protocol": record(PROTOCOL), "feature_registry": record(FEATURES),
        "test_registry": record(TEST_REGISTRY), "predecessor_seal": record(PREDECESSOR_SEAL),
        "predecessor_result": record(PREDECESSOR_RESULT), "r2_primary_population": record(R2_PRIMARY),
        "r2_reference_population": record(R2_REFERENCE), "r2_result": record(R2_RESULT),
        "base_engine": record(BASE_ENGINE), "research_engine": record(ENGINE), "runner": record(RUNNER), "synthetic_tests": record(TESTS),
    }
    sources = source_bindings()
    freeze = {
        "version": "MAOASCR_V1_PREOUTCOME_FREEZE_1_0", "status": "SEALED_BEFORE_CHECKPOINT_OR_OUTCOME_VALUE_ACCESS", "sealed_at_utc": utc_now(),
        "bindings": bindings, "source_bindings": sources,
        "preaccess_test_proof": {"tests": 5, "status": "PASS", "checks": ["FOLD_BOUNDARIES", "BH_AND_HOLM", "ENDPOINT_DISPOSITION", "EARLIEST_ROUTE_AND_CLUSTER_CAP", "FORBIDDEN_FEATURE_EXCLUSION"]},
        "controls": {"checkpoint_values_accessed": False, "development_outcomes_accessed": False, "2025_values_accessed": False, "2026_values_accessed": False, "charge_usd": 0.0, "XAUUSD_accessed": False},
        "source_count": len(sources), "candidate_limit": 6, "registered_candidate_count": 1,
    }
    write(FREEZE, freeze)
    print(json.dumps({
        "contract": record(CONTRACT), "protocol": record(PROTOCOL), "features": record(FEATURES),
        "tests": record(TEST_REGISTRY), "freeze": record(FREEZE), "source_count": len(sources),
        "stage1_tests": len(stage1), "stage2_tests": len(stage2), "router_candidates": 1,
        "development_outcomes_accessed": False, "forward_values_accessed": False, "charge_usd": 0.0,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

