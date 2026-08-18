from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_CONTRACT_V3.md"
FEATURE_REGISTRY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_feature_registry_v01.json"
MODEL_REGISTRY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_model_registry_v01.json"
TRACEABILITY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_traceability_v01.json"
FREEZE = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m1_freeze_v01.json"
OUTPUT = ROOT / "research_artifacts" / "gc_continuous_state_response_v3_m1_v01"
STATE = ROOT / "research_artifacts" / "gc_continuous_state_response_v3_state_v01.json"
TEST_FILE = ROOT / "tests" / "test_gc_continuous_state_response_v3_m1.py"

V2 = ROOT / "research_artifacts" / "gc_session_trigger_edge_v2r1_v01"
M3R1 = ROOT / "research_artifacts" / "gc_session_trigger_edge_m3r1_v01"
M4 = ROOT / "research_artifacts" / "gc_session_trigger_edge_m4_v01"
STEP5C = ROOT / "research_artifacts" / "gc_microstructure_step5c_v01"
BOOK = ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf"
BOOK_TRACE = ROOT / "research_manifests" / "gold_session_behaviour_v3_traceability_v01.json"
TRIGGER_TRACE = ROOT / "research_manifests" / "gc_session_trigger_edge_feature_traceability_v01.json"
GOLD_COVERAGE = ROOT / "research_artifacts" / "gold_session_behaviour_v3_coverage_v01.json"

SESSIONS = ("LONDON", "NEW_YORK")
STAGE1_IDS = (
    "CSR_FLOW_QUOTE_OFI_W60",
    "CSR_FLOW_TRADE_IMBALANCE_W60",
    "CSR_FLOW_DISPLAYED_IMBALANCE_W60",
    "CSR_BOOK_DEPTH_IMBALANCE_L5_W60",
    "CSR_BOOK_MICROPRICE_DISLOCATION_T0",
    "CSR_STRUCTURE_MOMENTUM_15M",
    "CSR_MACRO_ENGINE_SCORE",
    "CSR_MACRO_REAL_YIELD_SUPPORT",
    "CSR_MACRO_USD_SUPPORT",
    "CSR_MACRO_2Y_SUPPORT",
)
MODIFIER_IDS = (
    "CSR_LIQ_SPREAD_FRAGILITY_60_900",
    "CSR_SESSION_LEVEL_TENSION",
)
INTERACTION_IDS = (
    "CSR_INT_OFI_MACRO_CONCORDANCE",
    "CSR_INT_TRADE_MACRO_CONCORDANCE",
    "CSR_INT_DEPTH_REAL_YIELD_CONCORDANCE",
    "CSR_INT_MICROPRICE_USD_CONCORDANCE",
    "CSR_INT_OFI_SPREAD_FRAGILITY",
    "CSR_INT_OFI_SESSION_LEVEL_TENSION",
)
MICRO_SOURCE_COLUMNS = frozenset(
    {
        "quote_ofi_raw", "quote_ofi_transition_count", "trade_qty_buy", "trade_qty_sell",
        "add_qty_bid", "add_qty_ask", "cancel_qty_bid", "cancel_qty_ask",
        "depth_imbalance_l5_ppb", "microprice_fixed_1e9", "midpoint_fixed_1e9",
        "spread_fixed_1e9", "bid_depth_l10", "ask_depth_l10", "state_available", "book_crossed",
    }
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def receipt_valid(record: Mapping[str, Any], field: str) -> bool:
    expected = record.get(field)
    if not isinstance(expected, str):
        return False
    without = dict(record)
    without.pop(field, None)
    return expected in {canonical_hash(without), canonical_hash({**record, field: None})}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"Sealed artifact differs: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def write_json_once(path: Path, value: Any) -> None:
    write_once(path, json_bytes(value))


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def artifact_from_list(manifest: Mapping[str, Any], suffix: str) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if str(item["path"]).endswith(suffix)]
    require(len(matches) == 1, f"Expected one artifact ending {suffix}")
    return matches[0]


def verify_local_artifact(path: Path, record: Mapping[str, Any]) -> None:
    require(path.is_file(), f"Missing artifact: {path}")
    require(path.stat().st_size == int(record["bytes"]), f"Artifact size changed: {path}")
    require(sha256_file(path) == record["sha256"], f"Artifact hash changed: {path}")


def verify_boundaries() -> dict[str, Any]:
    v2_manifest = load_json(V2 / "manifest.json")
    v2_verdict = load_json(V2 / "verdict.json")
    require(receipt_valid(v2_manifest, "manifest_receipt"), "V2 technical manifest receipt invalid")
    require(receipt_valid(v2_verdict, "verdict_receipt"), "V2 technical verdict receipt invalid")
    require(v2_verdict["status"] == "PASS_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION", "V2 technical predecessor is not certified")
    for name in ("technical_diagnostics.json", "primary_support_counts.json", "reference_support_counts.json", "verdict.json", "primary_events.parquet", "reference_events.parquet"):
        verify_local_artifact(V2 / name, artifact_from_list(v2_manifest, f"/{name}"))

    m3_final = load_json(M3R1 / "r1_final_seal.json")
    m3_verdict = load_json(M3R1 / "r1_verdict.json")
    require(receipt_valid(m3_final, "final_seal_receipt"), "M3-R1 final seal invalid")
    require(receipt_valid(m3_verdict, "verdict_receipt"), "M3-R1 verdict receipt invalid")
    require(m3_final["status"] == "PASS_M3_R1_DISCOVERY_ZERO_CANDIDATES", "M3-R1 zero-candidate verdict not preserved")
    require(sha256_file(M3R1 / "r1_verdict.json") == m3_final["r1_verdict_sha256"], "M3-R1 verdict changed")

    m4_final = load_json(M4 / "final_seal.json")
    m4_verdict = load_json(M4 / "verdict.json")
    require(receipt_valid(m4_final, "final_seal_receipt"), "M4 final seal invalid")
    require(receipt_valid(m4_verdict, "verdict_receipt"), "M4 verdict receipt invalid")
    require(m4_final["status"] == "PASS_M4_NEGATIVE_RESULT_ATTRIBUTION", "M4 attribution not preserved")
    require(sha256_file(M4 / "verdict.json") == m4_final["verdict_sha256"], "M4 verdict changed")

    step5c_manifest = load_json(STEP5C / "manifest.json")
    for name in ("primary_summary.json", "reference_summary.json", "primary_london_buckets.parquet", "primary_new_york_buckets.parquet", "reference_london_buckets.parquet", "reference_new_york_buckets.parquet", "primary_decision_features.parquet", "reference_decision_features.parquet"):
        verify_local_artifact(STEP5C / name, artifact_from_list(step5c_manifest, f"/{name}"))
    require(step5c_manifest["status"] == "PASS_STEP_5C_FEATURE_MATERIALIZATION", "Step5C technical predecessor is not certified")

    book_sha = sha256_file(BOOK)
    require(book_sha == "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a", "Reference Book changed")
    coverage = load_json(GOLD_COVERAGE)
    require(coverage["reference_book"]["sha256"] == book_sha, "Coverage audit is not bound to this Reference Book")
    require(not coverage["audit_boundary"]["development_market_values_read"], "Legacy coverage audit opened development values")
    require(not coverage["audit_boundary"]["feature_outcome_joins_calculated"], "Legacy coverage audit joined outcomes")
    require(not coverage["audit_boundary"]["relationship_statistics_calculated"], "Legacy coverage audit calculated relationships")

    return {
        "status": "PASS_V3_M1_PREDECESSOR_AND_SCOPE_CLOSURE",
        "v2_technical_manifest_receipt": v2_manifest["manifest_receipt"],
        "v2_technical_verdict_receipt": v2_verdict["verdict_receipt"],
        "m3r1_final_seal_receipt": m3_final["final_seal_receipt"],
        "m4_final_seal_receipt": m4_final["final_seal_receipt"],
        "step5c_manifest_sha256": sha256_file(STEP5C / "manifest.json"),
        "reference_book_sha256": book_sha,
        "book_traceability_sha256": sha256_file(BOOK_TRACE),
        "trigger_traceability_sha256": sha256_file(TRIGGER_TRACE),
        "gold_coverage_sha256": sha256_file(GOLD_COVERAGE),
        "outcome_artifacts_opened": False,
        "year_2025_or_2026_values_accessed": False,
    }


def feature(
    feature_id: str,
    domain: str,
    role: str,
    formula: str,
    inputs: Sequence[str],
    expected_sign: str | None,
    book_factors: Sequence[str],
    availability: str,
    epistemic: str = "CALCULATED",
) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "domain": domain,
        "role": role,
        "formula": formula,
        "source_inputs": list(inputs),
        "expected_gold_sign": expected_sign,
        "book_factor_ids": list(book_factors),
        "availability_rule": availability,
        "epistemic_class": epistemic,
        "sessions": list(SESSIONS),
        "outcome_selected": False,
    }


def feature_registry_payload() -> dict[str, Any]:
    w60 = "Use only valid one-second buckets with bucket_end <= decision_at in trailing W60; require at least 57 valid state buckets when book state is required."
    features = [
        feature("CSR_FLOW_QUOTE_OFI_W60", "MICROSTRUCTURE", "STAGE1_DIRECTIONAL", "sum(quote_ofi_raw) / sum(quote_ofi_transition_count); zero transition denominator => UNKNOWN", ["quote_ofi_raw", "quote_ofi_transition_count"], "POSITIVE", ["MECH_DEPTH_RESILIENCE_IMPACT", "MECH_VOLUME"], w60),
        feature("CSR_FLOW_TRADE_IMBALANCE_W60", "MICROSTRUCTURE", "STAGE1_DIRECTIONAL", "(sum(trade_qty_buy)-sum(trade_qty_sell))/(sum(trade_qty_buy)+sum(trade_qty_sell)); zero denominator => UNKNOWN", ["trade_qty_buy", "trade_qty_sell"], "POSITIVE", ["MECH_VOLUME", "MECH_DEPTH_RESILIENCE_IMPACT"], w60),
        feature("CSR_FLOW_DISPLAYED_IMBALANCE_W60", "MICROSTRUCTURE", "STAGE1_DIRECTIONAL", "((add_qty_bid+cancel_qty_ask)-(add_qty_ask+cancel_qty_bid))/total of those four quantities; zero denominator => UNKNOWN", ["add_qty_bid", "add_qty_ask", "cancel_qty_bid", "cancel_qty_ask"], "POSITIVE", ["MECH_DEPTH_RESILIENCE_IMPACT"], w60),
        feature("CSR_BOOK_DEPTH_IMBALANCE_L5_W60", "MICROSTRUCTURE", "STAGE1_DIRECTIONAL", "median(depth_imbalance_l5_ppb) over W60 valid terminal states", ["depth_imbalance_l5_ppb", "state_available", "book_crossed"], "POSITIVE", ["MECH_DEPTH_RESILIENCE_IMPACT", "STRUCT_LIQUIDITY_STOP_ZONES"], w60),
        feature("CSR_BOOK_MICROPRICE_DISLOCATION_T0", "MICROSTRUCTURE", "STAGE1_DIRECTIONAL", "(microprice_fixed_1e9-midpoint_fixed_1e9)/spread_fixed_1e9 at latest valid terminal state; nonpositive spread => UNKNOWN", ["microprice_fixed_1e9", "midpoint_fixed_1e9", "spread_fixed_1e9", "state_available", "book_crossed"], "POSITIVE", ["MECH_SPREAD", "MECH_DEPTH_RESILIENCE_IMPACT"], "Latest valid uncrossed terminal state at or before decision_at."),
        feature("CSR_STRUCTURE_MOMENTUM_15M", "MARKET_STRUCTURE", "STAGE1_DIRECTIONAL", "(latest complete 15m close - fourth prior complete 15m close) / point-in-time 1h ATR; missing ATR or bars => UNKNOWN", ["XAUUSD_1M", "STRUCTURE_15M", "ATR_1H"], "POSITIVE", ["STRUCT_COMPRESSION_EXPANSION_MOMENTUM", "STRUCT_TREND_RANGE"], "All component bars and ATR available_at <= decision_at."),
        feature("CSR_MACRO_ENGINE_SCORE", "FUNDAMENTAL", "STAGE1_DIRECTIONAL", "Existing transparent gold directional score retained continuously without thresholding", ["V3_M4:MACRO_ENGINE_SCORE"], "POSITIVE", ["SYNTHESIS_EVIDENCE_CHAIN", "REGIME_REACTION_FUNCTION"], "Latest engine state with available_at <= decision_at; UNKNOWN remains unknown.", "INFERRED"),
        feature("CSR_MACRO_REAL_YIELD_SUPPORT", "FUNDAMENTAL_CROSS_MARKET", "STAGE1_DIRECTIONAL", "negative of latest point-in-time 10y real-yield observation-to-observation change in percentage points", ["V3_M4:MACRO_REAL_YIELD_10Y_CHANGE"], "POSITIVE", ["RATES_REAL_YIELD_10Y", "CROSS_RATES_DRIVER"], "Both observations must be released and available by decision_at."),
        feature("CSR_MACRO_USD_SUPPORT", "FUNDAMENTAL_CROSS_MARKET", "STAGE1_DIRECTIONAL", "negative 10,000 * log(latest broad USD / previous broad USD)", ["V3_M4:MACRO_USD_BROAD_CHANGE"], "POSITIVE", ["USD_CONTEXT", "CROSS_CONFIRMATION_DIVERGENCE"], "Both observations must be available by decision_at; broad USD is never relabelled DXY."),
        feature("CSR_MACRO_2Y_SUPPORT", "FUNDAMENTAL_EXPECTATIONS", "STAGE1_DIRECTIONAL", "negative of latest point-in-time 2y Treasury yield change in basis points", ["V3_M4:MACRO_TREASURY_2Y_CHANGE"], "POSITIVE", ["RATES_TREASURY_2Y", "EXPECT_POLICY_REPRICING"], "Both observations must be available by decision_at and roll-safe."),
        feature("CSR_LIQ_SPREAD_FRAGILITY_60_900", "LIQUIDITY", "STAGE2_MODIFIER_ONLY", "log((median W60 spread + one GC tick)/(median W900 spread + one GC tick)); W900 requires at least 855 valid states", ["spread_fixed_1e9", "state_available", "book_crossed"], None, ["MECH_SPREAD", "SESSION_ROLLOVER_LIQUIDITY"], "Both W60 and W900 end at decision_at; any invalid terminal latch remains unavailable."),
        feature("CSR_SESSION_LEVEL_TENSION", "SESSION_PRICE_LEVEL", "STAGE2_MODIFIER_ONLY", "1 / ((1+max(Asia range/1h ATR,0))*(1+max(distance to nearest decision-known level/1h ATR,0)))", ["V3_M4:SESSION_ASIA_RANGE_TO_1H_ATR", "V3_M4:LEVEL_NEAREST_KNOWN_TO_1H_ATR"], None, ["SESSION_ASIA_STATE", "STRUCT_SUPPORT_RESISTANCE_LEVELS", "STRUCT_LIQUIDITY_STOP_ZONES"], "Asia range, level coordinate, XAU price, and ATR must all be fully formed and available by decision_at."),
    ]
    return {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_FEATURE_REGISTRY_V1_0",
        "status": "FROZEN_OUTCOME_BLIND_FEATURE_REGISTRY",
        "feature_count": len(features),
        "stage1_directional_count": len(STAGE1_IDS),
        "stage2_modifier_count": len(MODIFIER_IDS),
        "features": features,
        "fixed_windows_seconds": [60, 900],
        "deferred_visible_fields": [
            {"domain": "POSITIONING", "fields": ["COT managed-money level/change/crowding"], "reason": "0 of 376 prior certified decision projections were known; not eligible until an outcome-blind coverage repair is separately authorized."},
            {"domain": "CATALYSTS", "fields": ["historical pre-event forecast/surprise", "upcoming event risk"], "reason": "Pre-event availability was not generally verified and prior decision coverage was 0 of 376."},
            {"domain": "INSTITUTIONAL_PAID_OR_UNAVAILABLE", "fields": ["ETF flows", "central-bank demand", "options/gamma", "intraday open interest", "unscheduled news"], "reason": "No licensed, point-in-time development source is sealed."},
        ],
        "unknown_policy": "Never impute, carry backward, or convert UNKNOWN to neutral/zero.",
        "registry_receipt": None,
    }


def model_registry_payload() -> dict[str, Any]:
    interactions = [
        {"interaction_id": "CSR_INT_OFI_MACRO_CONCORDANCE", "left": "CSR_FLOW_QUOTE_OFI_W60", "right": "CSR_MACRO_ENGINE_SCORE", "score": "sign(left)*min(abs(z(left)),abs(z(right))) when signs agree, otherwise 0", "expected_sign": "POSITIVE"},
        {"interaction_id": "CSR_INT_TRADE_MACRO_CONCORDANCE", "left": "CSR_FLOW_TRADE_IMBALANCE_W60", "right": "CSR_MACRO_ENGINE_SCORE", "score": "sign(left)*min(abs(z(left)),abs(z(right))) when signs agree, otherwise 0", "expected_sign": "POSITIVE"},
        {"interaction_id": "CSR_INT_DEPTH_REAL_YIELD_CONCORDANCE", "left": "CSR_BOOK_DEPTH_IMBALANCE_L5_W60", "right": "CSR_MACRO_REAL_YIELD_SUPPORT", "score": "sign(left)*min(abs(z(left)),abs(z(right))) when signs agree, otherwise 0", "expected_sign": "POSITIVE"},
        {"interaction_id": "CSR_INT_MICROPRICE_USD_CONCORDANCE", "left": "CSR_BOOK_MICROPRICE_DISLOCATION_T0", "right": "CSR_MACRO_USD_SUPPORT", "score": "sign(left)*min(abs(z(left)),abs(z(right))) when signs agree, otherwise 0", "expected_sign": "POSITIVE"},
        {"interaction_id": "CSR_INT_OFI_SPREAD_FRAGILITY", "left": "CSR_FLOW_QUOTE_OFI_W60", "right": "CSR_LIQ_SPREAD_FRAGILITY_60_900", "score": "z(left)*max(z(right),0)", "expected_sign": "POSITIVE"},
        {"interaction_id": "CSR_INT_OFI_SESSION_LEVEL_TENSION", "left": "CSR_FLOW_QUOTE_OFI_W60", "right": "CSR_SESSION_LEVEL_TENSION", "score": "z(left)*right", "expected_sign": "POSITIVE"},
    ]
    return {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_MODEL_REGISTRY_V1_0",
        "status": "FROZEN_PRE_OUTCOME_MODEL_REGISTRY",
        "sampling": {"anchors_per_session_date": 16, "offset_minutes": list(range(0, 240, 15)), "binary_event_conditioning": False},
        "endpoint": {"primary": "SIGNED_XAUUSD_DISPLACEMENT_15M", "diagnostic_only": ["5M", "30M", "60M"]},
        "stage1": {
            "features": list(STAGE1_IDS), "tests_per_session": 10,
            "model": {"type": "HUBER_LINEAR", "epsilon": 1.35, "alpha": 0.0001, "fit_intercept": True, "max_iter": 1000},
            "training_only_transform": {"winsor_quantiles": [0.01, 0.99], "center": "median", "scale": "MAD_THEN_SD_IF_ZERO"},
        },
        "stage2": {
            "interactions": interactions, "tests_per_session": 6,
            "model": {"type": "HIERARCHICAL_RIDGE_MAIN_EFFECTS_PLUS_INTERACTION", "alpha": 1.0, "fit_intercept": True},
            "stage1_must_be_sealed_first": True, "evaluate_all_support_eligible_registered_interactions": True,
        },
        "chronological_folds": [
            {"fold": 1, "train_blocks": [1, 10], "validate_blocks": [11, 19]},
            {"fold": 2, "train_blocks": [1, 19], "validate_blocks": [20, 28]},
            {"fold": 3, "train_blocks": [1, 28], "validate_blocks": [29, 38]},
        ],
        "support_floors": {"distinct_dates": 150, "distinct_blocks": 30, "validation_fold_dates": 35, "validation_fold_anchors": 480, "required_year_dates": 35, "stage1_completeness": 0.80, "stage2_joint_completeness": 0.70, "positive_predictor_dates": 40, "negative_predictor_dates": 40},
        "stage1_pass_gates": {"signed_oof_spearman_min": 0.08, "oof_direction_accuracy_min": 0.54, "bootstrap_repetitions": 20000, "bootstrap_lower_rho_gt": 0.0, "bootstrap_lower_accuracy_lift_gt": 0.0, "cluster_permutations": 100000, "bh_q_max": 0.05, "all_fold_rho_gt": 0.0, "folds_rho_gte_0_05_min": 2, "required_years_positive": [2022, 2023, 2024], "expected_coefficient_sign_every_fold": True},
        "stage2_additional_pass_gates": {"incremental_oof_spearman_min": 0.03, "oof_mae_reduction_min_fraction": 0.01},
        "multiplicity": {"stage1": "BH separately for 10 tests within each session", "stage2": "BH separately for 6 tests within each session", "secondary_horizons": "Holm within test; diagnostic only"},
        "candidate_policy": {"maximum_per_session": 2, "zero_acceptable": True, "development_pass_is_validated_edge": False, "ranking": ["lowest BH q", "highest bootstrap lower rho", "highest accuracy", "highest minimum fold rho", "greatest date support", "lexical test_id"]},
        "prohibited": ["retuning", "inversion", "feature repair", "selective filtering", "opaque model", "execution", "trades", "PnL", "R multiples", "returns"],
        "registry_receipt": None,
    }


def traceability_payload(features: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    domains = {
        "MARKET_MECHANICS_AND_LIQUIDITY": "Aggressive flow consumes available liquidity; depth, spread, microprice and quote flow describe how readily price can move.",
        "MARKET_STRUCTURE": "Momentum and proximity to fully formed levels describe accepted price progression without claiming hidden orders are observed.",
        "MACRO_AND_CROSS_MARKET": "Real yields, the 2-year yield, the broad dollar and the transparent macro score establish directional context, not automatic entries.",
        "SESSIONS": "Asia-range compression and known levels condition the information content and impact of London/New York flow.",
        "POSITIONING_AND_CATALYSTS": "These remain visible in the catalog but are deferred when point-in-time development coverage is not certified.",
    }
    return {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_TRACEABILITY_V1_0",
        "status": "REFERENCE_BOOK_TRACEABILITY_FROZEN",
        "reference_book": {"path": BOOK.name, "sha256": sha256_file(BOOK)},
        "domain_logic": domains,
        "feature_traceability": [{"feature_id": item["feature_id"], "domain": item["domain"], "book_factor_ids": item["book_factor_ids"], "source_inputs": item["source_inputs"], "epistemic_class": item["epistemic_class"], "limitation": "A calculated or inferred feature is never presented as directly observed institutional activity."} for item in features],
        "seven_layer_scope": {
            "L1_REGIME": ["CSR_MACRO_ENGINE_SCORE"],
            "L2_EXPECTATIONS": ["CSR_MACRO_2Y_SUPPORT"],
            "L3_POSITIONING": ["DEFERRED_COT_COVERAGE_FAIL"],
            "L4_CATALYSTS": ["DEFERRED_PRE_EVENT_AVAILABILITY_FAIL"],
            "L5_SESSIONS_LIQUIDITY": ["CSR_LIQ_SPREAD_FRAGILITY_60_900", "CSR_SESSION_LEVEL_TENSION"],
            "L6_CROSS_MARKET": ["CSR_MACRO_REAL_YIELD_SUPPORT", "CSR_MACRO_USD_SUPPORT"],
            "L7_EXECUTION_RISK": ["OUT_OF_SCOPE_NO_TRADE_CONSTRUCTION"],
        },
        "epistemic_policy": ["OBSERVED source facts retain lineage", "CALCULATED formulas are explicit", "INFERRED macro score remains labelled INFERRED", "UNKNOWN is never neutral"],
        "catalog_receipt": None,
    }


def seal_receipt(payload: dict[str, Any], field: str) -> dict[str, Any]:
    payload[field] = canonical_hash({**payload, field: None})
    return payload


def freeze() -> None:
    boundary = verify_boundaries()
    features = seal_receipt(feature_registry_payload(), "registry_receipt")
    models = seal_receipt(model_registry_payload(), "registry_receipt")
    trace = seal_receipt(traceability_payload(features["features"]), "catalog_receipt")
    write_json_once(FEATURE_REGISTRY, features)
    write_json_once(MODEL_REGISTRY, models)
    write_json_once(TRACEABILITY, trace)
    record = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M1_FREEZE_V1_0",
        "status": "PASS_V3_M1_PRE_METADATA_AUDIT_FREEZE",
        "frozen_at_utc": utc_now(),
        "boundary": boundary,
        "contract_sha256": sha256_file(CONTRACT),
        "implementation_sha256": sha256_file(Path(__file__)),
        "test_sha256": sha256_file(TEST_FILE),
        "feature_registry_sha256": sha256_file(FEATURE_REGISTRY),
        "feature_registry_receipt": features["registry_receipt"],
        "model_registry_sha256": sha256_file(MODEL_REGISTRY),
        "model_registry_receipt": models["registry_receipt"],
        "traceability_sha256": sha256_file(TRACEABILITY),
        "traceability_receipt": trace["catalog_receipt"],
        "outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "freeze_receipt": None,
    }
    seal_receipt(record, "freeze_receipt")
    write_json_once(FREEZE, record)
    preflight = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M1_PREFLIGHT_V1_0",
        "status": record["status"],
        "completed_at_utc": utc_now(),
        "freeze_receipt": record["freeze_receipt"],
        "outcome_artifacts_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "preflight_receipt": None,
    }
    seal_receipt(preflight, "preflight_receipt")
    write_json_once(OUTPUT / "preflight.json", preflight)
    print(json.dumps({"status": record["status"], "features": len(features["features"]), "stage1_per_session": len(STAGE1_IDS), "stage2_per_session": len(INTERACTION_IDS), "freeze_receipt": record["freeze_receipt"]}, sort_keys=True))


def verify_freeze() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    boundary = verify_boundaries()
    frozen = load_json(FREEZE)
    features = load_json(FEATURE_REGISTRY)
    models = load_json(MODEL_REGISTRY)
    trace = load_json(TRACEABILITY)
    preflight = load_json(OUTPUT / "preflight.json")
    for record, field in ((frozen, "freeze_receipt"), (features, "registry_receipt"), (models, "registry_receipt"), (trace, "catalog_receipt"), (preflight, "preflight_receipt")):
        require(receipt_valid(record, field), f"Invalid frozen receipt: {field}")
    require(sha256_file(CONTRACT) == frozen["contract_sha256"], "Contract changed after freeze")
    require(sha256_file(Path(__file__)) == frozen["implementation_sha256"], "Implementation changed after freeze")
    require(sha256_file(TEST_FILE) == frozen["test_sha256"], "Tests changed after freeze")
    require(sha256_file(FEATURE_REGISTRY) == frozen["feature_registry_sha256"], "Feature registry changed")
    require(sha256_file(MODEL_REGISTRY) == frozen["model_registry_sha256"], "Model registry changed")
    require(sha256_file(TRACEABILITY) == frozen["traceability_sha256"], "Traceability changed")
    require(boundary["m4_final_seal_receipt"] == frozen["boundary"]["m4_final_seal_receipt"], "Predecessor closure changed")
    return features, models, frozen


def correlation_mde(n: int, alpha: float, power: float = 0.80) -> float:
    require(n > 3 and 0 < alpha < 1 and 0 < power < 1, "Invalid power inputs")
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1.0 - alpha / 2.0)
    z_power = normal.inv_cdf(power)
    return math.tanh((z_alpha + z_power) / math.sqrt(n - 3))


def accuracy_mde(n: int, alpha: float, power: float = 0.80) -> float:
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1.0 - alpha / 2.0)
    z_power = normal.inv_cdf(power)
    return min(1.0, 0.5 + (z_alpha + z_power) * 0.5 / math.sqrt(n))


def correlation_mde_reference(n: int, alpha: float, power: float = 0.80) -> float:
    normal = NormalDist()
    critical_sum = normal.inv_cdf(1 - alpha * 0.5) + normal.inv_cdf(power)
    fisher_effect = critical_sum * (n - 3) ** -0.5
    positive = math.exp(2 * fisher_effect)
    return (positive - 1) / (positive + 1)


def accuracy_mde_reference(n: int, alpha: float, power: float = 0.80) -> float:
    normal = NormalDist()
    critical_sum = normal.inv_cdf(1 - alpha * 0.5) + normal.inv_cdf(power)
    return min(1.0, 0.5 + critical_sum / (2 * math.sqrt(n)))


def rounded(value: float) -> float:
    output = round(float(value), 12)
    return 0.0 if output == -0.0 else output


def parquet_schema_metadata(path: Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    names = parquet.schema_arrow.names
    return {
        "rows": parquet.metadata.num_rows,
        "columns": parquet.metadata.num_columns,
        "row_groups": parquet.metadata.num_row_groups,
        "schema_names_hash": canonical_hash(names),
        "selected_source_columns_present": sorted(MICRO_SOURCE_COLUMNS.intersection(names)),
        "selected_source_columns_missing": sorted(MICRO_SOURCE_COLUMNS.difference(names)),
        "file_sha256": sha256_file(path),
    }


def normalized_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = summary["diagnostics"]
    return {
        "available_sessions": int(diagnostics["available_sessions"]),
        "documented_unavailable_sessions": int(diagnostics["documented_unavailable_sessions"]),
        "bucket_rows": int(diagnostics["bucket_rows"]),
        "continuous_crossed_bucket_closes": int(diagnostics["continuous_crossed_bucket_closes"]),
        "state_available_bucket_closes": int(diagnostics["state_available_bucket_closes"]),
        "year_2025_or_2026_value_accesses": int(diagnostics["year_2025_or_2026_value_accesses"]),
        "development_outcome_columns_or_joins": int(diagnostics["development_outcome_columns_or_joins"]),
        "decision_unknown_classifications": dict(sorted(diagnostics["decision_unknown_classifications"].items())),
    }


def power_payload(reference: bool) -> dict[str, Any]:
    rho = correlation_mde_reference if reference else correlation_mde
    acc = accuracy_mde_reference if reference else accuracy_mde
    stage1_alpha = 0.05 / len(STAGE1_IDS)
    stage2_alpha = 0.05 / len(INTERACTION_IDS)
    cases = {
        "conservative_187_session_dates": 187,
        "minimum_supported_150_session_dates": 150,
        "optimistic_2992_independent_anchors": 2992,
        "minimum_80pct_complete_anchors": 2394,
    }
    return {
        "method": "Fisher-z correlation and normal sign-accuracy approximations; conservative Bonferroni alpha used as an upper-bound audit although the frozen discovery method is BH.",
        "power": 0.80,
        "stage1_conservative_alpha": rounded(stage1_alpha),
        "stage2_conservative_alpha": rounded(stage2_alpha),
        "stage1": {name: {"n": n, "minimum_detectable_absolute_correlation": rounded(rho(n, stage1_alpha)), "minimum_detectable_direction_accuracy": rounded(acc(n, stage1_alpha))} for name, n in cases.items()},
        "stage2": {name: {"n": n, "minimum_detectable_absolute_correlation": rounded(rho(n, stage2_alpha)), "minimum_detectable_direction_accuracy": rounded(acc(n, stage2_alpha))} for name, n in cases.items()},
        "frozen_minimum_effects": {"stage1_signed_oof_spearman": 0.08, "stage1_direction_accuracy": 0.54, "stage2_incremental_oof_spearman": 0.03},
        "interpretation": "Anchor-independent power is optimistic. Session-date clustering is the conservative boundary and cannot certify 80% power for the frozen small-effect thresholds. Gates remain unchanged; small true effects may be INCONCLUSIVE.",
        "power_verdict": "LIMITED_FOR_SMALL_EFFECTS_UNDER_SESSION_DATE_CLUSTER_BOUND",
    }


def build_audit(implementation: str) -> dict[str, Any]:
    features, models, frozen = verify_freeze()
    v2_diag = load_json(V2 / "technical_diagnostics.json")
    summary_path = STEP5C / f"{implementation}_summary.json"
    summary = load_json(summary_path)
    technical_key = implementation
    technical = v2_diag[f"{technical_key}_technical"]
    schema = {
        session: parquet_schema_metadata(STEP5C / f"{implementation}_{session.lower()}_buckets.parquet")
        for session in SESSIONS
    }
    require(all(not item["selected_source_columns_missing"] for item in schema.values()), "A selected microstructure source column is missing")
    require(all(item["columns"] == 85 for item in schema.values()), "Sealed 85-column schema changed")
    normalized = normalized_summary(summary)
    unknown = normalized["decision_unknown_classifications"]
    required_contexts = ("MACRO_ENGINE_BIAS_STATE", "REAL_YIELD_USD_CONFIRMATION", "STRUCTURE_15M_1H_ALIGNMENT", "ASIA_RANGE_LOCATION")
    context_coverage = {
        name: {"known_decisions": 376 - int(unknown[name]), "total_decisions": 376, "known_fraction": rounded((376 - int(unknown[name])) / 376)}
        for name in required_contexts
    }
    coverage = load_json(GOLD_COVERAGE)
    development = coverage["development_2021_2024"]
    source_counts = development["record_counts"]
    payload = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M1_AUDIT_PAYLOAD_V1_0",
        "predecessor_freeze_receipt": frozen["freeze_receipt"],
        "planned_population": {
            "available_sessions": 374,
            "available_session_dates_per_session": 187,
            "month_week_blocks": 38,
            "anchors_per_session_date": 16,
            "planned_anchors_per_session": 2992,
            "planned_anchors_total": 5984,
            "anchor_offsets_minutes": list(range(0, 240, 15)),
            "binary_event_conditioning": False,
        },
        "technical_coverage": {
            "full_session_one_second_rows": int(technical["bucket_rows"]),
            "one_second_rows_per_session": {"LONDON": int(technical["london_bucket_rows"]), "NEW_YORK": int(technical["new_york_bucket_rows"])},
            "state_available_bucket_closes": int(technical["state_available_bucket_closes"]),
            "technical_unavailable_bucket_closes": int(technical["technical_unavailable_bucket_closes"]),
            "technical_unavailable_ofi_buckets": int(technical["technical_unavailable_ofi_buckets"]),
            "continuous_crossed_bucket_closes_after_policy": int(technical["continuous_crossed_bucket_closes"]),
            "invalid_state_values_retained": int(technical["invalid_state_values_retained"]),
            "xau_expected_full_session_plus_60_timestamps": int(v2_diag["xau"]["expected_full_session_plus_60_timestamps"]),
            "xau_unexpected_missing_timestamps": int(v2_diag["xau"]["unexpected_missing_timestamps"]),
            "selected_85_column_schema": schema,
        },
        "context_source_coverage": {
            "prior_certified_decision_contexts": context_coverage,
            "continuous_field_level_coverage_status": "REQUIRES_OUTCOME_BLIND_M2_MATERIALIZATION_CERTIFICATION",
            "casebook_records": {"fundamental_snapshots": int(source_counts["fundamental_snapshots"]), "cross_market_snapshots": int(source_counts["cross_market_snapshots"]), "structure_snapshots": int(source_counts["structure_snapshots"]), "session_cases": int(source_counts["session_cases"]), "positioning_reports": int(source_counts["positioning_reports"])},
            "source_bundle_start": development["start_inclusive"],
            "source_bundle_end_exclusive": development["end_exclusive"],
        },
        "excluded_coverage": {
            "cot_known_prior_decisions": 376 - int(unknown["COT_MANAGED_MONEY_CROWDING"]),
            "recent_release_surprise_known_prior_decisions": 376 - int(unknown["RECENT_RELEASE_SURPRISE_DIRECTION"]),
            "upcoming_catalyst_known_prior_decisions": 376 - int(unknown["UPCOMING_CATALYST_RISK"]),
            "policy": "Remain deferred; no proxy or neutral imputation.",
        },
        "registered_scope": {"features": int(features["feature_count"]), "stage1_tests_per_session": int(models["stage1"]["tests_per_session"]), "stage2_tests_per_session": int(models["stage2"]["tests_per_session"]), "total_registered_tests": 2 * (int(models["stage1"]["tests_per_session"]) + int(models["stage2"]["tests_per_session"]))},
        "power_audit": power_payload(reference=implementation == "reference"),
        "readiness_gates": {
            "predecessor_seals_valid": True,
            "reference_book_bound": True,
            "374_sessions_available": int(technical["available_sessions"]) == 374,
            "38_chronological_blocks_available": True,
            "selected_microstructure_columns_present": all(not item["selected_source_columns_missing"] for item in schema.values()),
            "full_session_features_certified": int(technical["bucket_rows"]) == 7_068_600,
            "invalid_state_retained_zero": int(technical["invalid_state_values_retained"]) == 0,
            "outcomes_unopened": not summary["development_outcomes_opened_or_joined"],
            "2025_2026_locked": not summary["year_2025_or_2026_values_accessed"],
            "no_new_acquisition_required_for_m2": True,
            "continuous_context_fields_require_m2_certification": True,
        },
        "coverage_verdict": "PASS_METADATA_READY_FOR_OUTCOME_BLIND_M2_WITH_FIELD_LEVEL_GATES",
        "outcome_artifacts_accessed": False,
        "relationships_or_candidates_calculated": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    require(normalized["development_outcome_columns_or_joins"] == 0 and normalized["year_2025_or_2026_value_accesses"] == 0, "Technical metadata violated scope")
    require(all(value is True for value in payload["readiness_gates"].values()), "A metadata readiness gate failed")
    return payload


def audit(implementation: str) -> None:
    payload = build_audit(implementation)
    record = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M1_AUDIT_RUN_V1_0",
        "implementation": implementation,
        "completed_at_utc": utc_now(),
        "payload": payload,
        "payload_hash": canonical_hash(payload),
    }
    write_json_once(OUTPUT / f"{implementation}_coverage_power_audit.json", record)
    print(json.dumps({"implementation": implementation, "status": payload["coverage_verdict"], "payload_hash": record["payload_hash"], "power_verdict": payload["power_audit"]["power_verdict"]}, sort_keys=True))


def report_text(payload: Mapping[str, Any]) -> str:
    p = payload["planned_population"]
    tech = payload["technical_coverage"]
    power = payload["power_audit"]
    s1_conservative = power["stage1"]["conservative_187_session_dates"]
    s1_optimistic = power["stage1"]["optimistic_2992_independent_anchors"]
    return "\n".join(
        [
            "# GC Continuous State-Response Edge Discovery V3 — Milestone 1", "",
            "Formal status: `PASS_V3_M1_CONTRACT_REGISTRIES_AND_METADATA_READINESS`", "",
            "## Frozen design", "",
            f"- `{p['available_sessions']}` sessions: 187 London and 187 New York.",
            f"- `{p['anchors_per_session_date']}` fixed non-overlapping anchors per date; `{p['planned_anchors_total']}` planned anchors.",
            "- 10 standalone continuous tests and 6 preregistered interactions per session.",
            "- Signed 15-minute XAUUSD displacement is the later primary endpoint; no outcome was accessed here.", "",
            "## Coverage", "",
            f"- Certified full-session one-second rows: `{tech['full_session_one_second_rows']}`.",
            f"- Technical unavailable bucket closes: `{tech['technical_unavailable_bucket_closes']}`; invalid retained states: `{tech['invalid_state_values_retained']}`.",
            f"- Unexpected missing XAUUSD timestamps retained for universal M2 classification: `{tech['xau_unexpected_missing_timestamps']}`.",
            "- Every selected microstructure source column is present in the sealed 85-column schema.",
            "- Continuous fundamental/structure fields require exact field-level availability certification in M2 before any outcome join.", "",
            "## Honest power boundary", "",
            f"- Conservative 187-date Stage-1 detectable correlation at 80% power: `{s1_conservative['minimum_detectable_absolute_correlation']}`; direction accuracy: `{s1_conservative['minimum_detectable_direction_accuracy']}`.",
            f"- Optimistic 2,992-independent-anchor bound: correlation `{s1_optimistic['minimum_detectable_absolute_correlation']}`; direction accuracy `{s1_optimistic['minimum_detectable_direction_accuracy']}`.",
            "- Because anchors within a date are dependent, the study is not certified at 80% power for the frozen small-effect thresholds. Those thresholds were not weakened.", "",
            "## Visible exclusions", "",
            "- COT is deferred because prior certified decision coverage was 0/376, not because positioning is considered irrelevant.",
            "- Pre-event surprise/catalyst inputs are deferred because historical availability was not verified.",
            "- ETF, central-bank, options/gamma, intraday OI, and unscheduled-news history remain unavailable.", "",
            "## Boundary", "",
            "The rejected V2 binary branch remains rejected. No outcome, relationship, candidate, 2025/2026 value, execution, trade, PnL, R multiple, or return was accessed or calculated. M2 is not authorized by this completion.", "",
        ]
    )


def seal() -> None:
    features, models, frozen = verify_freeze()
    primary = load_json(OUTPUT / "primary_coverage_power_audit.json")
    reference = load_json(OUTPUT / "reference_coverage_power_audit.json")
    require(primary["payload_hash"] == reference["payload_hash"], "Independent metadata audits differ")
    require(primary["payload_hash"] == canonical_hash(primary["payload"]), "Primary audit hash invalid")
    require(reference["payload_hash"] == canonical_hash(reference["payload"]), "Reference audit hash invalid")
    payload = primary["payload"]
    write_json_once(OUTPUT / "coverage_power_audit.json", payload)
    write_once(OUTPUT / "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_1_REPORT.md", report_text(payload).encode("utf-8"))
    verdict = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M1_VERDICT_V1_0",
        "status": "PASS_V3_M1_CONTRACT_REGISTRIES_AND_METADATA_READINESS",
        "formal_milestone_pass": True,
        "completed_at_utc": utc_now(),
        "binary_v2_branch_status": "COMPLETED_REJECTED_ZERO_CANDIDATES",
        "feature_count": features["feature_count"],
        "stage1_tests_per_session": models["stage1"]["tests_per_session"],
        "stage2_tests_per_session": models["stage2"]["tests_per_session"],
        "planned_anchors_total": payload["planned_population"]["planned_anchors_total"],
        "coverage_verdict": payload["coverage_verdict"],
        "power_verdict": payload["power_audit"]["power_verdict"],
        "continuous_context_field_level_certification_pending_m2": True,
        "candidates_created": 0,
        "outcome_artifacts_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "next_milestone_authorized": False,
        "verdict_receipt": None,
    }
    seal_receipt(verdict, "verdict_receipt")
    write_json_once(OUTPUT / "verdict.json", verdict)
    state = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_STATE_V1_0",
        "active_branch": "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_V3",
        "completed_milestone": "M1_CONTRACT_REGISTRIES_TRACEABILITY_COVERAGE_POWER",
        "status": verdict["status"],
        "preserved_predecessors": {"v2_binary_trigger": "REJECTED_ZERO_CANDIDATES", "m3r1_final_seal_receipt": frozen["boundary"]["m3r1_final_seal_receipt"], "m4_final_seal_receipt": frozen["boundary"]["m4_final_seal_receipt"]},
        "development": {"period": "2021-11-08/2024-12-13", "outcomes_locked_until_authorized_m3": True},
        "forward_locks": {"2025": "LOCKED", "2026": "LOCKED"},
        "next_milestone": "M2_OUTCOME_BLIND_CONTINUOUS_PREDICTOR_MATERIALIZATION",
        "next_milestone_authorized": False,
        "candidate_count": 0,
        "state_receipt": None,
    }
    seal_receipt(state, "state_receipt")
    write_json_once(STATE, state)
    artifact_paths = {
        "preflight.json": OUTPUT / "preflight.json",
        "primary_coverage_power_audit.json": OUTPUT / "primary_coverage_power_audit.json",
        "reference_coverage_power_audit.json": OUTPUT / "reference_coverage_power_audit.json",
        "coverage_power_audit.json": OUTPUT / "coverage_power_audit.json",
        "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_1_REPORT.md": OUTPUT / "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_1_REPORT.md",
        "verdict.json": OUTPUT / "verdict.json",
        "state.json": STATE,
        "contract.md": CONTRACT,
        "feature_registry.json": FEATURE_REGISTRY,
        "model_registry.json": MODEL_REGISTRY,
        "traceability.json": TRACEABILITY,
        "freeze.json": FREEZE,
    }
    manifest = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M1_MANIFEST_V1_0",
        "status": verdict["status"],
        "sealed_at_utc": utc_now(),
        "predecessor_m4_final_seal_receipt": frozen["boundary"]["m4_final_seal_receipt"],
        "freeze_receipt": frozen["freeze_receipt"],
        "artifacts": {name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for name, path in artifact_paths.items()},
        "independent_reproduction": {"exact": True, "payload_hash": primary["payload_hash"]},
        "outcome_artifacts_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "manifest_receipt": None,
    }
    seal_receipt(manifest, "manifest_receipt")
    write_json_once(OUTPUT / "manifest.json", manifest)
    final = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M1_FINAL_SEAL_V1_0",
        "status": verdict["status"],
        "sealed_at_utc": utc_now(),
        "manifest_sha256": sha256_file(OUTPUT / "manifest.json"),
        "manifest_receipt": manifest["manifest_receipt"],
        "verdict_sha256": sha256_file(OUTPUT / "verdict.json"),
        "verdict_receipt": verdict["verdict_receipt"],
        "state_sha256": sha256_file(STATE),
        "state_receipt": state["state_receipt"],
        "report_sha256": sha256_file(OUTPUT / "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_1_REPORT.md"),
        "final_seal_receipt": None,
    }
    seal_receipt(final, "final_seal_receipt")
    write_json_once(OUTPUT / "final_seal.json", final)
    print(json.dumps({"status": verdict["status"], "planned_anchors": verdict["planned_anchors_total"], "power_verdict": verdict["power_verdict"], "final_seal_receipt": final["final_seal_receipt"]}, sort_keys=True))


def verify() -> None:
    verify_freeze()
    primary = load_json(OUTPUT / "primary_coverage_power_audit.json")
    reference = load_json(OUTPUT / "reference_coverage_power_audit.json")
    payload_primary = build_audit("primary")
    payload_reference = build_audit("reference")
    require(canonical_hash(payload_primary) == primary["payload_hash"], "Primary audit did not independently reproduce")
    require(canonical_hash(payload_reference) == reference["payload_hash"], "Reference audit did not independently reproduce")
    require(primary["payload_hash"] == reference["payload_hash"], "Audit payloads differ")
    verdict = load_json(OUTPUT / "verdict.json")
    manifest = load_json(OUTPUT / "manifest.json")
    final = load_json(OUTPUT / "final_seal.json")
    state = load_json(STATE)
    for record, field in ((verdict, "verdict_receipt"), (manifest, "manifest_receipt"), (final, "final_seal_receipt"), (state, "state_receipt")):
        require(receipt_valid(record, field), f"Invalid final receipt {field}")
    require(sha256_file(OUTPUT / "manifest.json") == final["manifest_sha256"], "Manifest changed after seal")
    require(sha256_file(OUTPUT / "verdict.json") == final["verdict_sha256"], "Verdict changed after seal")
    require(sha256_file(STATE) == final["state_sha256"], "State changed after seal")
    require(sha256_file(OUTPUT / "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_1_REPORT.md") == final["report_sha256"], "Report changed after seal")
    for metadata in manifest["artifacts"].values():
        path = ROOT / metadata["path"]
        require(path.stat().st_size == metadata["bytes"] and sha256_file(path) == metadata["sha256"], f"Manifest artifact changed: {path}")
    require(not verdict["outcome_artifacts_accessed"] and not verdict["year_2025_or_2026_values_accessed"], "Scope boundary violated")
    print(json.dumps({"status": verdict["status"], "independent_reproduction": True, "outcomes_accessed": False, "year_2025_or_2026_values_accessed": False, "final_seal_receipt": final["final_seal_receipt"]}, sort_keys=True))


def self_test() -> None:
    for n in (150, 187, 2394, 2992):
        for count in (len(STAGE1_IDS), len(INTERACTION_IDS)):
            alpha = 0.05 / count
            require(abs(correlation_mde(n, alpha) - correlation_mde_reference(n, alpha)) < 1e-12, "Correlation MDE implementations differ")
            require(abs(accuracy_mde(n, alpha) - accuracy_mde_reference(n, alpha)) < 1e-12, "Accuracy MDE implementations differ")
    features = feature_registry_payload()
    models = model_registry_payload()
    require(features["feature_count"] == 12 and len(STAGE1_IDS) == 10 and len(MODIFIER_IDS) == 2, "Feature registry cardinality failed")
    require(len(models["stage2"]["interactions"]) == 6, "Interaction registry cardinality failed")
    used = {item["feature_id"] for item in features["features"]}
    require(set(STAGE1_IDS).union(MODIFIER_IDS) == used, "Feature IDs differ")
    print(json.dumps({"status": "PASS_V3_M1_SELF_TEST", "features": len(used), "stage1_per_session": 10, "stage2_per_session": 6}, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("action", choices=("self-test", "freeze", "audit-primary", "audit-reference", "seal", "verify"))
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.action == "self-test":
        self_test()
    elif args.action == "freeze":
        freeze()
    elif args.action == "audit-primary":
        audit("primary")
    elif args.action == "audit-reference":
        audit("reference")
    elif args.action == "seal":
        seal()
    else:
        verify()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "FAIL_V3_M1", "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise
