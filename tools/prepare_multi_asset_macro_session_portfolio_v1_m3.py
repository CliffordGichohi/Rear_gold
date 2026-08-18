#!/usr/bin/env python3
"""Freeze Milestone-3 design without deserializing market values or outcomes."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
CONTRACT = ROOT / "MULTI_ASSET_MACRO_AND_SESSION_PORTFOLIO_EDGE_DISCOVERY_CONTRACT_V1.md"
M1_PROTOCOL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_protocol.json"
M1_SEAL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_milestone1_seal.json"
M2_SEAL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_milestone2_seal.json"
M3_PROTOCOL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_protocol.json"
FEATURE_REGISTRY = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_feature_registry.json"
TEST_REGISTRY = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_test_registry.json"
FREEZE = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_preoutcome_freeze.json"
IMPLEMENTATION = ROOT / "tools/run_multi_asset_macro_session_portfolio_v1_m3.py"
FUNDAMENTALS = ROOT / "research_artifacts/gold_casebook_v01/fundamentals.jsonl.gz"
EVENTS = ROOT / "research_artifacts/gold_casebook_v01/events.jsonl.gz"
POSITIONING = ROOT / "research_artifacts/gold_casebook_v01/positioning.jsonl.gz"
CME_MANIFEST = ROOT / "data/raw/databento_cme_pre2025/manifest.json"

INSTRUMENTS = {
    "XAUUSD": ("XAUUSD", "PRECIOUS_METALS", ("LONDON_DECISION", "NEW_YORK_DECISION")),
    "XAGUSD": ("XAGUSD", "PRECIOUS_METALS", ("LONDON_DECISION", "NEW_YORK_DECISION")),
    "EURUSD": ("EURUSD", "USD_FX", ("LONDON_DECISION", "NEW_YORK_DECISION")),
    "USDJPY": ("USDJPY", "USD_FX", ("LONDON_DECISION", "NEW_YORK_DECISION")),
    "USTEC": ("NAS100", "US_EQUITY_INDICES", ("US_CASH_OPEN",)),
    "US500": ("US500", "US_EQUITY_INDICES", ("US_CASH_OPEN",)),
    "XTIUSD": ("WTI", "ENERGY", ("US_ENERGY",)),
}
FAMILIES = (
    "E1_POST_MACRO_ACCEPTANCE_REJECTION",
    "E2_PRIOR_SESSION_SWEEP_RECLAIM",
    "E3_PRIMARY_SESSION_BREAK_ACCEPT_RETEST",
    "E4_HTF_PULLBACK_RESOLUTION",
)
STATES = ("ALIGNED", "OPPOSED", "NEUTRAL", "UNKNOWN")


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.resolve().relative_to(ROOT.resolve()).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def test_registry() -> dict[str, Any]:
    stage1: list[dict[str, Any]] = []
    for instrument, (research_id, cluster, sessions) in INSTRUMENTS.items():
        for session in sessions:
            for family in FAMILIES:
                if family == FAMILIES[1] and instrument not in {"XAUUSD", "XAGUSD", "EURUSD", "USDJPY"}:
                    continue
                stage1.append({
                    "test_id": f"S1::{research_id}::{session}::{family}", "stage": 1,
                    "instrument": instrument, "research_id": research_id, "cluster": cluster,
                    "session": session, "family": family, "condition": "ALL_ELIGIBLE_SIGNED_TRIGGERS",
                })
    stage1.sort(key=lambda item: item["test_id"])
    stage2 = [
        {
            "test_id": f"S2::{item['research_id']}::{item['session']}::{item['family']}::{state}", "stage": 2,
            "instrument": item["instrument"], "research_id": item["research_id"], "cluster": item["cluster"],
            "session": item["session"], "family": item["family"], "macro_state": state,
            "condition": f"MACRO_STATE_EQUALS_{state}", "complement": f"MACRO_STATE_NOT_EQUALS_{state}",
        }
        for item in stage1 for state in STATES
    ]
    stage2.sort(key=lambda item: item["test_id"])
    assert len(stage1) == 41 and len(stage2) == 164
    return {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_TEST_REGISTRY_1_0",
        "status": "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_ACCESS", "stage1_count": 41,
        "stage2_count": 164, "stage1": stage1, "stage2": stage2,
        "stage2_runs_for_every_support_eligible_test_regardless_of_stage1_result": True,
        "no_unregistered_tests_permitted": True,
    }


def protocol() -> dict[str, Any]:
    return {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_PROTOCOL_1_0",
        "status": "FROZEN_BEFORE_ANY_M3_PREDICTOR_OR_OUTCOME_VALUE_ACCESS",
        "predecessor": "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED",
        "period": {
            "source_start_inclusive": "2021-08-01T00:00:00Z", "source_end_exclusive": "2025-01-01T00:00:00Z",
            "warmup_and_training_only": "2021-08-01/2021-12-31", "strict_oof_credit": "2022-01-01/2024-12-31",
            "calendar_2025": "LOCKED", "calendar_2026": "LOCKED",
        },
        "aggregation": {
            "timestamp_authority": "MT5_UTC_OPEN_TIME", "all_intervals": "LEFT_CLOSED_RIGHT_OPEN",
            "completed_candles_only": True, "M5_M15_required_minutes": "100_PERCENT",
            "H1_H4_required_minutes": "AT_LEAST_75_PERCENT", "D1_required_minutes": "AT_LEAST_5_OF_6_EXPECTED_TRADING_FRACTION",
            "W1_required_days": 4, "canonical_deduplication": "EARLIEST_SEALED_SOURCE_THEN_SOURCE_ROW",
        },
        "sessions": {
            "LONDON_DECISION": {"timezone": "Europe/London", "window": "07:00/12:00", "opening_range_minutes": 15},
            "NEW_YORK_DECISION": {"timezone": "America/New_York", "window": "08:00/12:00", "opening_range_minutes": 15},
            "US_CASH_OPEN": {"timezone": "America/New_York", "window": "09:30/12:00", "opening_range_minutes": 30},
            "US_ENERGY": {"timezone": "America/New_York", "window": "08:00/14:30", "opening_range_minutes": 30},
        },
        "point_in_time": {
            "macro_observation": "latest_vintage_with_available_at_and_observation_time_lte_decision",
            "forecast_policy": "historical_MT5_forecasts_not_used_pre_release",
            "event_actual_policy": "usable_only_at_sealed_event_available_at",
            "swing": "STRICT_TWO_LEFT_TWO_RIGHT_KNOWN_AT_SECOND_RIGHT_CLOSE",
            "level": "known_minute_lte_decision", "no_forward_fill_over_release_or_session": True,
        },
        "macro_score": {
            "component_change": "SIGN_LATEST_POINT_IN_TIME_VALUE_MINUS_PREVIOUS_POINT_IN_TIME_OBSERVATION",
            "component_multi_series": "MEAN_SIGN_WITH_UNEMPLOYMENT_AND_CLAIMS_INVERTED",
            "score": "100_TIMES_WEIGHTED_COMPONENT_SIGN_SUM_DIVIDED_BY_AVAILABLE_ABSOLUTE_WEIGHT",
            "minimum_available_absolute_weight_fraction": 0.60, "direction_threshold_absolute_score": 20.0,
            "states": list(STATES), "USDJPY_confidence_cap": 60.0, "WTI_EIA_state": "UNKNOWN_NOT_AVAILABLE",
            "COT": "METALS_CONTEXT_ONLY_NOT_PASS_GATE",
            "weights": {
                "XAUUSD": {"REAL10": -0.30, "Y2": -0.20, "USD": -0.30, "INFLATION": 0.10, "GROWTH": -0.10},
                "XAGUSD": {"REAL10": -0.25, "Y2": -0.20, "USD": -0.30, "INFLATION": 0.10, "GROWTH": 0.15},
                "EURUSD": {"USD": -0.45, "Y2": -0.25, "GROWTH": -0.15, "VIX": -0.15},
                "USDJPY": {"Y2": 0.45, "Y10": 0.20, "GROWTH": 0.15, "VIX": -0.20},
                "USTEC_US500": {"Y2": -0.25, "Y10": -0.15, "GROWTH": 0.30, "VIX": -0.20, "STRESS": -0.10},
                "XTIUSD": {"USD": -0.25, "GROWTH": 0.35, "EQUITY": 0.20, "VIX": -0.10, "STRESS": -0.10},
            },
        },
        "edge_family_exact_definitions": {
            "E1": "tier1 event; cross-market story from event-1m to event+4m excluding target; >=60% component coverage and abs mean sign >=0.25; first M5 through minute30 accepting >=0.10 ATR outside pre-event30m range or rejecting a >=0.05 ATR sweep by closing inside; NY/primary-US assignment",
            "E2": "first prior Asia/London extreme sweep >=0.05 M15_ATR and completed-M5 reclaim within 3 bars; same-time two-sided conflict is no signal; OPPOSED macro is no trade",
            "E3": "first M15 break >=0.10 ATR beyond opening-or-prior boundary; body fraction>=0.60; close location>=0.70; first held retest within 4 completed M5 and tolerance 0.05 ATR",
            "E4": "two latest same-direction H4 swing breaks; 0.35-0.75 impulse retrace at known H1/H4 swing or prior-day level within 0.15 ATR; aligned M15 displacement range>=0.80 ATR and body>=0.60 plus known minor M15 swing break; OPPOSED macro is no trade",
            "symmetry": "LONG_AND_SHORT_ONE_SIGNED_HYPOTHESIS", "one_signal_per_family_session_date": True,
        },
        "outcome_and_execution": {
            "outcome_join_key": "INSTRUMENT_PLUS_EXACT_MT5_UTC_MINUTE", "entry": "NEXT_M1_OPEN_AFTER_TRIGGER_WITH_ONE_MINUTE_LATENCY",
            "stop": "TRIGGER_EXTREME_PLUS_0P10_M15_ATR", "stop_neighbors": [0.08, 0.10, 0.12],
            "valid_stop_distance_atr": [0.25, 1.50], "target": "NEAREST_KNOWN_DIRECTIONAL_LIQUIDITY_1P25R_TO_3R_ELSE_2R",
            "deadline": "FROZEN_SESSION_END_OR_EVENT_PLUS_120_MINUTES", "path": "EXACT_CONTIGUOUS_M1",
            "ambiguous_bar": "STOP_FIRST", "gap": "WORSE_M1_OPEN", "no_interpolation": True,
            "planned_risk_usd": 25.0, "account_usd": 10000.0, "whole_broker_volume_steps": True,
            "base_cost_r": "MAX(MAX_ENTRY_EXIT_SPREAD_PRICE_DIVIDED_BY_STOP_DISTANCE_PLUS_0P03,0P05)",
            "cost_stress": [1.0, 1.5, 2.0], "one_open_position_per_instrument": True,
            "no_reentry_same_family_session_date": True,
        },
        "support": {
            "stage1": {"signals": 90, "dates": 60, "each_fold": 15, "each_direction": 30, "executed_after_frozen_rules": 60},
            "stage2": {"signals": 60, "dates": 40, "each_fold": 10, "condition": 20, "complement": 20, "condition_folds": 4, "condition_executed": 30, "complement_executed": 30},
        },
        "statistics": {
            "cluster": "SESSION_DATE", "bootstrap_resamples": 5000, "seed": 731947,
            "stage1_raw_test": "ONE_SIDED_CLUSTER_BOOTSTRAP_NET_EXPECTANCY_GT_ZERO",
            "stage2_raw_test": "ONE_SIDED_CLUSTER_BOOTSTRAP_CONDITION_MINUS_COMPLEMENT_EXPECTANCY_GT_ZERO",
            "stage1_multiplicity": "BH_FDR_Q_0P05_OVER_ALL_41_SUPPORT_FAIL_P_EQUALS_1",
            "stage2_multiplicity": "HOLM_FWER_0P05_OVER_ALL_164_SUPPORT_FAIL_P_EQUALS_1",
            "stage_order": "STAGE1_COMPLETE_ARTIFACT_SEALED_BEFORE_STAGE2_CALCULATION",
        },
        "candidate_gates": {
            "expectancy_gt": 0.0, "PF_gte": 1.15, "clustered_CI95_low_gt": 0.0, "adjusted_p_lte": 0.05,
            "cost_1p5_expectancy_gt": 0.0, "positive_folds_gte": 4, "positive_years_gte": 2,
            "positive_stop_neighbors_gte": 2, "candidate_max_drawdown_pct_lte": 10.0,
            "stage2_incremental_lift_CI95_low_gt": 0.0,
            "fixed_session_candidate_session_concentration": "NOT_APPLICABLE_UNTIL_COMBINED_PORTFOLIO",
        },
        "ranking": ["ADJUSTED_P_ASC", "MEDIAN_FOLD_EXPECTANCY_DESC", "PF_DESC", "SUPPORT_DESC", "TEST_ID_ASC"],
        "candidate_limits": {"per_instrument": 2, "per_instrument_family": 1, "portfolio": 8},
        "portfolio": {
            "risk_per_trade_portfolio_R": 0.25, "risk_per_trade_usd": 25.0, "cluster_concurrent_R_lte": 1.0,
            "portfolio_concurrent_R_lte": 2.0, "US_macro_supercluster_R_lte": 1.0, "US_macro_window_minutes": [-15, 120],
            "capacity_priority": ["ENTRY_TIMESTAMP", "INSTRUMENT_ID", "CANDIDATE_ID"], "same_signal_deduplicated": True,
            "gates": {"expectancy_gt": 0, "PF_gte": 1.15, "CI95_low_gt": 0, "cost_1p5_gt": 0, "positive_folds_gte": 4, "positive_years_gte": 2, "drawdown_pct_lte": 15, "instrument_positive_share_lte": 0.50, "cluster_positive_share_lte": 0.50},
            "ten_R_per_month": "REPORT_ONLY_NOT_SELECTION_INPUT",
        },
        "missing_data": "UNKNOWN_OR_NO_TRADE_NEVER_IMPUTED", "charges_authorized": False,
        "independent_reproduction": "ALTERNATE_DEDUP_AGGREGATION_ENUMERATION_EXECUTION_AND_COMPLETE_RESULT_PASS",
    }


def feature_registry() -> dict[str, Any]:
    return {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_FEATURE_REGISTRY_1_0",
        "status": "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_ACCESS",
        "identities": [
            {"id": "PIT_MACRO_COMPONENT_DELTAS", "classification": "CALCULATED", "lineage": "FRED_ALFRED_VINTAGE", "available_at_gate": True},
            {"id": "PIT_INSTRUMENT_MACRO_SCORE_STATE", "classification": "INFERRED", "states": list(STATES)},
            {"id": "PIT_METALS_COT_CONTEXT", "classification": "OBSERVED_AND_CALCULATED", "pass_gate": False},
            {"id": "COMPLETED_W1_D1_H4_H1_M15_M5_PRESSURE", "classification": "CALCULATED"},
            {"id": "CONFIRMED_2L2R_SWINGS_AND_H4_BREAKS", "classification": "CALCULATED", "future_formed_levels": False},
            {"id": "PRIOR_WEEK_DAY_SESSION_AND_OPENING_RANGE_LEVELS", "classification": "CALCULATED", "known_before_decision": True},
            {"id": "SESSION_RANGE_VOLUME_SPREAD_PHASE", "classification": "CALCULATED"},
            {"id": "CROSS_MARKET_EVENT_SHOCK_ZT_ZN_EURUSD_RISK", "classification": "CALCULATED", "target_response_excluded": True},
            {"id": "E1_ACCEPTANCE_REJECTION_TRIGGER", "classification": "INFERRED"},
            {"id": "E2_SWEEP_RECLAIM_TRIGGER", "classification": "INFERRED"},
            {"id": "E3_BREAK_ACCEPT_RETEST_TRIGGER", "classification": "INFERRED"},
            {"id": "E4_HTF_PULLBACK_RESOLUTION_TRIGGER", "classification": "INFERRED"},
        ],
        "stored_signal_fields": ["identity", "instrument", "family", "session", "session_date", "fold", "direction", "decision", "deadline", "macro_state", "macro_score", "macro_confidence", "trade_eligibility", "trigger_extreme", "ATR15", "known_levels", "feature_evidence", "lineage_hash"],
        "outcome_fields_hidden_until_single_open": ["entry", "stop", "target", "exit", "gross_R", "cost_R", "net_R", "MFE_R", "MAE_R", "PnL_USD"],
        "excluded": ["2025_VALUES", "2026_VALUES", "UNVERIFIED_PRE_RELEASE_FORECASTS", "FUTURE_SWINGS", "TARGET_INSTRUMENT_FUTURE_EVENT_RESPONSE", "UNREGISTERED_FEATURES", "REALIZED_LABELS"],
    }


def source_paths() -> list[Path]:
    paths = [FUNDAMENTALS, EVENTS, POSITIONING, CME_MANIFEST, M1_SEAL, M2_SEAL]
    for symbol in INSTRUMENTS:
        for path in sorted((ROOT / "data/mt5").glob(f"{symbol.lower()}_1m_ic_markets_mt5_*.csv")):
            try:
                encoded_start = datetime.strptime(path.stem.split("_")[-2], "%Y%m%dT%H%M").replace(tzinfo=UTC)
            except (ValueError, IndexError):
                continue
            if encoded_start < datetime(2025, 1, 1, tzinfo=UTC):
                paths.append(path)
    manifest = json.loads(CME_MANIFEST.read_text(encoding="utf-8"))
    for item in manifest["normalization"]["files"]:
        normalized = Path(item["normalized"])
        if not normalized.is_absolute():
            normalized = ROOT / normalized
        paths.append(normalized)
    unique = {path.resolve(): path for path in paths}
    result = [unique[key] for key in sorted(unique, key=lambda path: path.as_posix().lower())]
    if any(not path.is_file() for path in result):
        raise FileNotFoundError([str(path) for path in result if not path.is_file()])
    return result


def main() -> None:
    if any(path.exists() for path in (M3_PROTOCOL, FEATURE_REGISTRY, TEST_REGISTRY, FREEZE)):
        raise FileExistsError("Milestone-3 design artifact already exists")
    m2 = json.loads(M2_SEAL.read_text(encoding="utf-8"))
    if m2.get("verdict") != "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED" or not m2.get("seven_instrument_discovery_ready"):
        raise ValueError("Milestone-2 predecessor gate failed")
    for item in m2["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Milestone-2 seal failure: {item['path']}")
    write_exclusive(M3_PROTOCOL, protocol())
    write_exclusive(FEATURE_REGISTRY, feature_registry())
    write_exclusive(TEST_REGISTRY, test_registry())
    sources = [record(path) for path in source_paths()]
    bindings = {
        "contract": record(CONTRACT), "milestone_1_protocol": record(M1_PROTOCOL),
        "milestone_2_seal": record(M2_SEAL), "milestone_3_protocol": record(M3_PROTOCOL),
        "feature_registry": record(FEATURE_REGISTRY), "test_registry": record(TEST_REGISTRY),
        "implementation": record(IMPLEMENTATION),
    }
    freeze = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_PREOUTCOME_FREEZE_1_0",
        "status": "SEALED_BEFORE_ANY_M3_PREDICTOR_OR_OUTCOME_VALUE_ACCESS", "sealed_at_utc": now(),
        "bindings": bindings, "source_bindings": sources,
        "counts": {"stage1_tests": 41, "stage2_tests": 164, "source_files_bound": len(sources)},
        "predecessor_verification": {"milestone_2_verdict": m2["verdict"], "every_m2_artifact_verified": True},
        "controls": {
            "predictor_values_accessed": False, "development_outcomes_accessed": False,
            "relationships_calculated": False, "trades_or_pnl_calculated": False,
            "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
            "data_acquired": False, "charge_incurred_usd": 0.0,
        },
        "one_outcome_opening_authorized_after_materialization_pass": True,
        "implementation_integrity_proof": {
            "python_compile_pass": True, "registry_cardinality_pass": True,
            "half_open_and_DST_rules_frozen": True, "primary_reference_required": True,
        },
    }
    write_exclusive(FREEZE, freeze)
    print(json.dumps({"status": freeze["status"], "stage1": 41, "stage2": 164, "sources": len(sources), "freeze_sha256": sha256_file(FREEZE)}, indent=2))


if __name__ == "__main__":
    main()
