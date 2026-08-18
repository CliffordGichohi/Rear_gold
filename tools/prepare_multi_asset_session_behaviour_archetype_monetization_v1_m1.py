#!/usr/bin/env python3
"""Prepare and seal Multi-Asset Session Behaviour V1 Milestone 1.

This program is deliberately outcome-neutral.  Its only semantic access to MT5
CSV sources is the ``open_time`` column, used to certify the frozen session
identity universe and timestamp completeness.  It never selects OHLC, spread,
volume, returns, directions, excursions, trades, or PnL.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
SCHEMAS = ROOT / "research_schemas"
ARTIFACTS = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1"

CONTRACT = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_DISCOVERY_CONTRACT_V1.md"
TRACEABILITY_MD = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_TRACEABILITY.md"
CASE_MATRIX_MD = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_CASE_MATRIX.md"
COVERAGE_MD = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_COVERAGE.md"
MILESTONE_MD = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_MILESTONE_1.md"

PROTOCOL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_protocol.json"
TRACEABILITY = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_traceability.json"
DESIGN_FREEZE = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m1_design_freeze.json"
FINAL_SEAL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_milestone1_seal.json"
CASE_SCHEMA = SCHEMAS / "multi_asset_session_behaviour_archetype_monetization_v1_case_matrix.schema.json"

IDENTITIES = ARTIFACTS / "session_identity_registry.json"
COVERAGE_PRIMARY = ARTIFACTS / "coverage_primary.json"
COVERAGE_REFERENCE = ARTIFACTS / "coverage_reference.json"
COVERAGE_AUDIT = ARTIFACTS / "coverage_audit.json"
STATE = ARTIFACTS / "state.json"
VALIDATION = ARTIFACTS / "validation.json"

M1_SEAL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_milestone1_seal.json"
M2_SEAL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_milestone2_seal.json"
M3_SEAL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_milestone3_seal.json"
M2_CERTIFICATION = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json"
M1_COVERAGE = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m1/coverage_audit.json"
GOLD_FREEZE = MANIFESTS / "gold_h4_liquidity_target_capture_falsification_v1_final_freeze.json"
GOLD_RESULT = ROOT / "research_artifacts/gold_h4_liquidity_target_capture_falsification_v1/final_result.json"
REFERENCE_BOOK = ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf"
IMPLEMENTATION = Path(__file__).resolve()

START = datetime(2021, 8, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)
VERSION = "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_MONETIZATION_V1"

INSTRUMENTS: dict[str, dict[str, Any]] = {
    "XAGUSD": {"research_id": "XAGUSD", "asset_class": "PRECIOUS_METAL_CFD", "cluster": "PRECIOUS_METALS"},
    "EURUSD": {"research_id": "EURUSD", "asset_class": "FX", "cluster": "USD_FX"},
    "USDJPY": {"research_id": "USDJPY", "asset_class": "FX", "cluster": "USD_FX"},
    "USTEC": {"research_id": "NAS100", "asset_class": "US_EQUITY_INDEX_CFD", "cluster": "US_EQUITY_INDICES"},
    "US500": {"research_id": "US500", "asset_class": "US_EQUITY_INDEX_CFD", "cluster": "US_EQUITY_INDICES"},
    "XTIUSD": {"research_id": "WTI", "asset_class": "ENERGY_CFD", "cluster": "ENERGY"},
}

SESSIONS: dict[str, dict[str, Any]] = {
    "ASIA_SESSION": {
        "timezone": "Europe/London", "start": "00:00", "end": "07:00",
        "instruments": ["XAGUSD", "EURUSD", "USDJPY"], "role": "ASIA_BUILD_AND_DECISION_UNIT",
    },
    "LONDON_SESSION": {
        "timezone": "Europe/London", "start": "07:00", "end": "12:00",
        "instruments": list(INSTRUMENTS), "role": "EUROPEAN_MORNING_DECISION_UNIT",
    },
    "NEW_YORK_SESSION": {
        "timezone": "America/New_York", "start": "08:00", "end": "12:00",
        "instruments": ["XAGUSD", "EURUSD", "USDJPY"], "role": "NEW_YORK_MORNING_DECISION_UNIT",
    },
    "US_CASH_SESSION": {
        "timezone": "America/New_York", "start": "09:30", "end": "16:00",
        "instruments": ["USTEC", "US500"], "role": "FULL_US_CASH_SESSION",
    },
    "US_ENERGY_SESSION": {
        "timezone": "America/New_York", "start": "08:00", "end": "14:30",
        "instruments": ["XTIUSD"], "role": "US_ENERGY_DECISION_UNIT",
    },
}

FORBIDDEN_SOURCE_COLUMNS = {
    "open", "high", "low", "close", "volume", "tick_volume", "real_volume", "spread_points",
    "return", "direction", "mfe", "mae", "pnl", "r_multiple",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload.rstrip() + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def verify_sealed_artifact_set(seal_path: Path) -> dict[str, Any]:
    seal = load_json(seal_path)
    for item in seal.get("artifacts", []):
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Predecessor artifact seal failed: {item['path']}")
    return seal


def verify_predecessors() -> dict[str, Any]:
    m1 = verify_sealed_artifact_set(M1_SEAL)
    m2 = verify_sealed_artifact_set(M2_SEAL)
    m3 = verify_sealed_artifact_set(M3_SEAL)
    gold = load_json(GOLD_FREEZE)
    for key, item in gold.items():
        if isinstance(item, dict) and {"path", "bytes", "sha256"} <= set(item):
            path = ROOT / item["path"]
            if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
                raise ValueError(f"Gold freeze binding failed: {key}")
    gold_result = load_json(GOLD_RESULT)
    if gold_result["best_observed_policy"]["policy_id"] != "TARGET_TAKE_25_RUN_75":
        raise ValueError("Held gold policy identity changed")
    if m2.get("verdict") != "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED":
        raise ValueError("Milestone-2 source predecessor did not pass")
    if m3.get("verdict") != "REJECT_NO_MULTI_ASSET_PORTFOLIO_EDGE":
        raise ValueError("Milestone-3 negative result was not preserved")
    return {
        "milestone_1_seal": file_record(M1_SEAL), "milestone_1_status": m1.get("verdict"),
        "milestone_2_seal": file_record(M2_SEAL), "milestone_2_status": m2.get("verdict"),
        "milestone_3_seal": file_record(M3_SEAL), "milestone_3_status": m3.get("verdict"),
        "held_gold_freeze": file_record(GOLD_FREEZE), "held_gold_final_result": file_record(GOLD_RESULT),
        "held_gold_policy": {
            "policy_id": "TARGET_TAKE_25_RUN_75", "observed_development_r_per_month": 1.1888167031,
            "status": "HELD_UNCHANGED_EXCLUDED_FROM_BRANCH", "validation_claim": "NONE",
        },
        "all_verified": True,
    }


def parse_clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def session_clock(session_code: str, local_day: date) -> tuple[datetime, datetime, datetime]:
    spec = SESSIONS[session_code]
    zone = ZoneInfo(spec["timezone"])
    decision = datetime.combine(local_day, parse_clock(spec["start"]), zone).astimezone(UTC)
    end = datetime.combine(local_day, parse_clock(spec["end"]), zone).astimezone(UTC)
    observation_start = decision + timedelta(minutes=1)
    return decision, observation_start, end


def session_units() -> list[tuple[str, str]]:
    return sorted(
        (instrument, session)
        for session, spec in SESSIONS.items()
        for instrument in spec["instruments"]
    )


def build_identity_registry() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    day = START.date()
    while day < END.date():
        if day.weekday() < 5:
            for instrument, session in session_units():
                decision, observation_start, end = session_clock(session, day)
                identity = [VERSION, instrument, session, day.isoformat(), decision.isoformat(), observation_start.isoformat(), end.isoformat()]
                rows.append({
                    "case_id": f"MSBAM-V1::{canonical_hash(identity)[:24]}",
                    "instrument": instrument, "research_id": INSTRUMENTS[instrument]["research_id"],
                    "cluster": INSTRUMENTS[instrument]["cluster"], "session_code": session,
                    "session_date_local": day.isoformat(), "timezone": SESSIONS[session]["timezone"],
                    "decision_at_utc": decision.isoformat().replace("+00:00", "Z"),
                    "observation_start_utc": observation_start.isoformat().replace("+00:00", "Z"),
                    "observation_end_utc": end.isoformat().replace("+00:00", "Z"),
                    "expected_path_minutes": int((end - observation_start).total_seconds() // 60),
                    "partition": "DEVELOPMENT", "coverage_or_outcome_attached": False,
                })
        day += timedelta(days=1)
    rows.sort(key=lambda row: (row["session_date_local"], row["instrument"], row["session_code"]))
    expected = 892 * len(session_units())
    if len(rows) != expected or any(row["instrument"] == "XAUUSD" for row in rows):
        raise ValueError("Frozen identity universe is invalid")
    return {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_IDENTITY_REGISTRY_1_0",
        "status": "FROZEN_BEFORE_BEHAVIOUR_OR_OUTCOME_MATERIALIZATION",
        "development_start_inclusive": START.isoformat().replace("+00:00", "Z"),
        "development_end_exclusive": END.isoformat().replace("+00:00", "Z"),
        "weekday_session_dates": 892, "instrument_session_units": len(session_units()),
        "expected_identity_count": len(rows), "identity_hash": canonical_hash(rows),
        "eligibility_policy": "EVERY_EXPECTED_IDENTITY_RETAINED; COMPLETE_PATH_ELIGIBILITY_CERTIFIED_SEPARATELY; NO_HOLIDAY_INFERENCE_FROM_ABSENCE",
        "rows": rows,
        "controls": {"XAUUSD_included": False, "market_values_accessed": False, "outcomes_calculated": False},
    }


def build_traceability() -> dict[str, Any]:
    decision: list[dict[str, Any]] = []
    outcome: list[dict[str, Any]] = []

    def add_decision(field_id: str, group: str, classification: str, source: str, coverage: str, applicability: Sequence[str] | str = "ALL") -> None:
        decision.append({
            "field_id": field_id, "branch": "decision_state", "group": group,
            "epistemic_classification": classification, "source_or_method": source,
            "development_coverage": coverage, "applicability": applicability,
            "point_in_time_gate": "available_at_lte_decision_at", "materialized_in_milestone_1": False,
        })

    def add_outcome(field_id: str, group: str, method: str) -> None:
        outcome.append({
            "field_id": field_id, "branch": "subsequent_behaviour", "group": group,
            "epistemic_classification": "CALCULATED", "method": method,
            "decision_eligible": False, "materialized_in_milestone_1": False,
        })

    for field_id, group, classification, source, coverage in [
        ("instrument_identity", "mechanics", "OBSERVED", "IC_MARKETS_SYMBOL_METADATA", "PRESENT_AND_ADEQUATE"),
        ("m1_timestamp_quality", "mechanics", "CALCULATED", "SEALED_MT5_OPEN_TIME", "PRESENT_AND_ADEQUATE"),
        ("broker_spread", "mechanics", "OBSERVED", "IC_MARKETS_M1_SPREAD_POINTS", "PRESENT_AND_ADEQUATE"),
        ("broker_tick_volume", "mechanics", "OBSERVED", "IC_MARKETS_M1_TICK_VOLUME", "PRESENT_AND_ADEQUATE"),
        ("centralized_futures_volume", "mechanics", "OBSERVED", "EXCHANGE_DATA_NOT_PRESENT_FOR_ALL_ASSETS", "MISSING"),
        ("order_book_depth_resilience_impact", "mechanics", "OBSERVED", "MBO_MBP_NOT_PRESENT_FOR_SIX_ASSET_UNIVERSE", "MISSING"),
        ("session_calendar_and_phase", "sessions", "CALCULATED", "IANA_DST_SESSION_REGISTRY", "PRESENT_AND_ADEQUATE"),
        ("minutes_to_from_tier1_event", "catalysts", "CALCULATED", "SEALED_MT5_EVENT_METADATA", "PRESENT_BUT_PARTIAL"),
        ("historical_pre_release_consensus", "expectations", "OBSERVED", "VERIFIED_VINTAGE_FORECAST_SOURCE", "MISSING"),
        ("economic_surprise_and_revision", "expectations", "CALCULATED", "POINT_IN_TIME_ACTUAL_FORECAST_PREVIOUS_REVISION", "PRESENT_BUT_PARTIAL"),
        ("fed_policy_path_proxy", "expectations", "CALCULATED", "ZQ_SR3_AND_FRED_ALFRED", "PRESENT_BUT_PARTIAL"),
        ("exact_meeting_probabilities", "expectations", "OBSERVED", "LICENSED_HISTORICAL_CURVE_NOT_PRESENT", "MISSING"),
        ("inflation_state", "macro", "INFERRED", "CPI_CORE_CPI_PCE_CORE_PCE_VINTAGES", "PRESENT_AND_ADEQUATE"),
        ("growth_state", "macro", "INFERRED", "GDP_RETAIL_SALES", "PRESENT_AND_ADEQUATE"),
        ("labour_state", "macro", "INFERRED", "NFP_UNEMPLOYMENT_CLAIMS_WAGES_WHERE_AVAILABLE", "PRESENT_BUT_PARTIAL"),
        ("fed_rate_state", "macro", "CALCULATED", "FED_POLICY_RATE_VINTAGES", "PRESENT_AND_ADEQUATE"),
        ("us_2y_yield_state", "cross_market", "CALCULATED", "FRED_2Y_AND_ZT_PROXY", "PRESENT_AND_ADEQUATE"),
        ("us_10y_yield_state", "cross_market", "CALCULATED", "FRED_10Y_AND_ZN_PROXY", "PRESENT_AND_ADEQUATE"),
        ("us_10y_real_yield_state", "cross_market", "CALCULATED", "FRED_REAL_10Y", "PRESENT_AND_ADEQUATE"),
        ("breakeven_inflation_state", "cross_market", "CALCULATED", "FRED_BREAKEVEN", "PRESENT_AND_ADEQUATE"),
        ("yield_curve_state", "cross_market", "CALCULATED", "2Y_10Y_POINT_IN_TIME_DIFFERENCE", "DERIVABLE_NOT_MATERIALIZED"),
        ("usd_proxy_state", "cross_market", "CALCULATED", "FRED_BROAD_USD_AND_EURUSD_PROXY_NOT_DXY", "PRESENT_AND_ADEQUATE"),
        ("equity_risk_state", "cross_market", "CALCULATED", "US500_USTEC_AND_PUBLIC_EQUITY_SERIES", "PRESENT_AND_ADEQUATE"),
        ("volatility_state", "cross_market", "CALCULATED", "US_VOLATILITY_INDEX", "PRESENT_AND_ADEQUATE"),
        ("financial_stress_state", "cross_market", "CALCULATED", "US_FINANCIAL_STRESS", "PRESENT_AND_ADEQUATE"),
        ("credit_risk_state", "cross_market", "CALCULATED", "US_HIGH_YIELD_SPREAD", "PRESENT_AND_ADEQUATE"),
        ("unscheduled_news_state", "catalysts", "OBSERVED", "LICENSED_POINT_IN_TIME_NEWS_NOT_PRESENT", "MISSING"),
        ("options_iv_strikes_gamma", "positioning", "OBSERVED", "HISTORICAL_OPTIONS_SOURCE_NOT_PRESENT", "MISSING"),
        ("etf_and_central_bank_flows", "positioning", "OBSERVED", "VERSIONED_POINT_IN_TIME_SOURCE_NOT_PRESENT", "MISSING"),
    ]:
        add_decision(field_id, group, classification, source, coverage)

    add_decision("gold_cot_context_for_silver", "positioning", "OBSERVED_CALCULATED", "SEALED_GOLD_COT_FRIDAY_PUBLICATION", "PRESENT_BUT_PARTIAL", ["XAGUSD"])
    add_decision("japanese_rate_differential", "cross_market", "CALCULATED", "US_RATES_PRESENT_JAPANESE_CURVE_MISSING", "PRESENT_BUT_PARTIAL", ["USDJPY"])
    add_decision("euro_rate_differential", "cross_market", "CALCULATED", "US_RATES_PRESENT_EURO_CURVE_INCOMPLETE", "PRESENT_BUT_PARTIAL", ["EURUSD"])
    add_decision("energy_inventory_context", "catalysts", "OBSERVED", "VERIFIED_EIA_HISTORY_NOT_PRESENT", "MISSING", ["XTIUSD"])
    add_decision("silver_gold_relative_state", "cross_market", "CALCULATED", "XAGUSD_AND_XAUUSD_POINT_IN_TIME", "PRESENT_AND_ADEQUATE", ["XAGUSD"])

    for timeframe in ("W1", "D1", "H4", "H1", "M15", "M5"):
        for suffix in ("completed_candle_state", "atr_and_displacement", "range_compression_expansion"):
            add_decision(f"structure_{timeframe}_{suffix}", "structure", "CALCULATED", "COMPLETED_MT5_BARS_ONLY", "DERIVABLE_NOT_MATERIALIZED")
    for timeframe in ("H4", "H1", "M15"):
        add_decision(f"confirmed_swings_{timeframe}", "structure", "CALCULATED", "STRICT_2_LEFT_2_RIGHT_KNOWN_AFTER_SECOND_RIGHT_CLOSE", "DERIVABLE_NOT_MATERIALIZED")
        add_decision(f"bos_mss_{timeframe}", "structure", "INFERRED", "COMPLETED_CLOSE_VS_CONFIRMED_SWING", "DERIVABLE_NOT_MATERIALIZED")
    for field_id in (
        "prior_week_high_low", "prior_day_high_low", "prior_eligible_session_high_low",
        "confirmed_H4_H1_M15_swing_levels", "round_number_levels", "session_open_gap",
        "nearest_known_support_resistance", "known_liquidity_level_registry",
    ):
        add_decision(field_id, "levels", "CALCULATED" if "liquidity" not in field_id else "INFERRED", "COMPLETED_PRE_DECISION_PRICE_ONLY", "DERIVABLE_NOT_MATERIALIZED")
    for field_id in (
        "macro_regime_synthesis", "fundamental_direction_context", "macro_confidence",
        "supporting_evidence", "contradicting_evidence", "highest_risk_assumption", "unknown_driver_registry",
    ):
        add_decision(field_id, "synthesis", "INFERRED", "TRANSPARENT_BOOK_TRACEABLE_RULES", "DERIVABLE_NOT_MATERIALIZED")

    for horizon in (5, 15, 30, 60, 120):
        add_outcome(f"signed_displacement_{horizon}m", "fixed_horizons", f"close_at_or_before_reference_plus_{horizon}m_minus_reference_open")
        add_outcome(f"absolute_displacement_{horizon}m", "fixed_horizons", f"absolute_signed_displacement_{horizon}m")
    for field_id, group, method in [
        ("session_close_displacement", "fixed_horizons", "last_complete_M1_close_before_observation_end_minus_reference_open"),
        ("session_range", "path", "maximum_high_minus_minimum_low"),
        ("maximum_upward_excursion", "excursions", "maximum_high_minus_reference_open"),
        ("maximum_downward_excursion", "excursions", "reference_open_minus_minimum_low"),
        ("long_mfe", "excursions", "max_0_maximum_high_minus_reference_open"),
        ("long_mae", "excursions", "max_0_reference_open_minus_minimum_low"),
        ("short_mfe", "excursions", "long_mae_by_symmetric_fixed_reference_definition"),
        ("short_mae", "excursions", "long_mfe_by_symmetric_fixed_reference_definition"),
        ("session_high_timestamp", "timing", "first_timestamp_of_session_maximum_high"),
        ("session_low_timestamp", "timing", "first_timestamp_of_session_minimum_low"),
        ("high_low_order", "timing", "HIGH_FIRST_LOW_FIRST_OR_SAME_M1_AMBIGUOUS"),
        ("close_location", "path", "close_minus_low_divided_by_high_minus_low"),
        ("path_efficiency", "path", "absolute_close_displacement_divided_by_sum_absolute_completed_M5_close_changes"),
        ("turning_point_count", "path", "strict_completed_M5_2L2R_turns"),
        ("realized_path_volatility", "path", "root_sum_squared_M1_log_changes"),
        ("decision_known_level_interactions", "levels", "touch_breach_accept_reject_failed_break_retest_only_for_preexisting_levels"),
        ("descriptive_archetype", "archetype", "frozen_precedence_and_threshold_taxonomy"),
    ]:
        add_outcome(field_id, group, method)
    for threshold in ("0P25", "0P50", "1P00", "1P50", "2P00", "3P00"):
        add_outcome(f"first_passage_up_{threshold}_ATR", "first_passage", f"first_M1_high_at_or_above_reference_plus_{threshold}_predecision_ATR")
        add_outcome(f"first_passage_down_{threshold}_ATR", "first_passage", f"first_M1_low_at_or_below_reference_minus_{threshold}_predecision_ATR")

    coverage_counts = Counter(row["development_coverage"] for row in decision)
    return {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_TRACEABILITY_1_0",
        "status": "FROZEN_BEFORE_CASE_OR_BEHAVIOUR_MATERIALIZATION",
        "reference_book": file_record(REFERENCE_BOOK),
        "field_count": len(decision) + len(outcome), "decision_field_count": len(decision),
        "outcome_field_count": len(outcome), "decision_coverage_counts": dict(sorted(coverage_counts.items())),
        "decision_fields": sorted(decision, key=lambda row: row["field_id"]),
        "subsequent_behaviour_fields": sorted(outcome, key=lambda row: row["field_id"]),
        "epistemic_states": ["OBSERVED", "CALCULATED", "INFERRED", "UNKNOWN"],
        "rules": {
            "missing_is_unknown_not_neutral": True, "institutional_motive_never_observed_without_direct_source": True,
            "outcome_branch_decision_eligible": False, "execution_fields_included": False,
            "XAUUSD_as_target_instrument": False,
        },
    }


def fact_schema(decision_eligible: bool) -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["field_id", "value", "unit", "epistemic_status", "as_of", "available_at", "quality", "method", "source_hashes", "decision_eligible"],
        "properties": {
            "field_id": {"type": "string", "minLength": 1},
            "value": {}, "unit": {"type": ["string", "null"]},
            "epistemic_status": {"enum": ["OBSERVED", "CALCULATED", "INFERRED", "UNKNOWN"]},
            "as_of": {"type": ["string", "null"], "format": "date-time"},
            "available_at": {"type": ["string", "null"], "format": "date-time"},
            "quality": {"enum": ["VALID", "PARTIAL", "STALE", "UNAVAILABLE_TECHNICAL", "UNKNOWN"]},
            "method": {"type": "string"}, "explanation": {"type": ["string", "null"]},
            "source_hashes": {"type": "array", "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "uniqueItems": True},
            "decision_eligible": {"const": decision_eligible},
        },
        "allOf": [{"if": {"properties": {"epistemic_status": {"const": "UNKNOWN"}}}, "then": {"properties": {"value": {"type": "null"}}}}],
    }


def build_case_schema(traceability: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:gold-intel:multi-asset-session-behaviour-v1:case",
        "title": "Multi-Asset Session Behaviour, Archetype and Monetization V1 Case Matrix",
        "type": "object", "additionalProperties": False,
        "required": ["case_metadata", "lineage", "decision_state", "subsequent_behaviour", "quality", "research_policy"],
        "$defs": {"decisionFact": fact_schema(True), "outcomeFact": fact_schema(False)},
        "properties": {
            "case_metadata": {
                "type": "object", "additionalProperties": False,
                "required": ["case_id", "instrument", "research_id", "cluster", "session_code", "session_date_local", "timezone", "decision_at", "observation_start", "observation_end", "partition"],
                "properties": {
                    "case_id": {"type": "string", "pattern": "^MSBAM-V1::[0-9a-f]{24}$"},
                    "instrument": {"enum": list(INSTRUMENTS)},
                    "research_id": {"enum": [item["research_id"] for item in INSTRUMENTS.values()]},
                    "cluster": {"enum": sorted({item["cluster"] for item in INSTRUMENTS.values()})},
                    "session_code": {"enum": list(SESSIONS)}, "session_date_local": {"type": "string", "format": "date"},
                    "timezone": {"enum": sorted({item["timezone"] for item in SESSIONS.values()})},
                    "decision_at": {"type": "string", "format": "date-time"},
                    "observation_start": {"type": "string", "format": "date-time"},
                    "observation_end": {"type": "string", "format": "date-time"},
                    "partition": {"enum": ["DEVELOPMENT", "LOCKED_2025", "LOCKED_2026", "PROSPECTIVE"]},
                },
            },
            "lineage": {
                "type": "object", "additionalProperties": False,
                "required": ["contract_sha256", "protocol_sha256", "traceability_sha256", "identity_registry_sha256", "source_hashes", "transform_versions"],
                "properties": {
                    "contract_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "protocol_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "traceability_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "identity_registry_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "source_hashes": {"type": "array", "items": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "uniqueItems": True},
                    "transform_versions": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                },
            },
            "decision_state": {
                "type": "object", "additionalProperties": False, "required": ["facts", "unknown_field_ids"],
                "properties": {
                    "facts": {"type": "array", "items": {"$ref": "#/$defs/decisionFact"}, "minItems": len(traceability["decision_fields"])},
                    "unknown_field_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                },
            },
            "subsequent_behaviour": {
                "type": "object", "additionalProperties": False,
                "required": ["decision_eligible", "neutral_reference", "facts", "first_passage", "archetype"],
                "properties": {
                    "decision_eligible": {"const": False},
                    "neutral_reference": {
                        "type": "object", "additionalProperties": False,
                        "required": ["timestamp", "coordinate", "not_an_entry"],
                        "properties": {"timestamp": {"type": "string", "format": "date-time"}, "coordinate": {"type": "number"}, "not_an_entry": {"const": True}},
                    },
                    "facts": {"type": "array", "items": {"$ref": "#/$defs/outcomeFact"}},
                    "first_passage": {"type": "array", "items": {"$ref": "#/$defs/outcomeFact"}},
                    "archetype": {
                        "type": "object", "additionalProperties": False,
                        "required": ["family", "direction", "classification_version", "decision_eligible"],
                        "properties": {
                            "family": {"enum": ["DATA_UNAVAILABLE", "SWEEP_REVERSAL", "FAILED_BREAK", "BREAKOUT_HOLD", "ONE_SIDED", "TWO_SIDED_EXPANSION", "TREND", "BALANCED_COMPRESSION", "ROTATIONAL", "MIXED_UNCLASSIFIED"]},
                            "direction": {"enum": ["UP", "DOWN", "BOTH", "NONE", "UNKNOWN"]},
                            "classification_version": {"const": "ARCHETYPE_TAXONOMY_V1_0"}, "decision_eligible": {"const": False},
                        },
                    },
                },
            },
            "quality": {
                "type": "object", "additionalProperties": False,
                "required": ["status", "expected_m1_bars", "observed_m1_bars", "point_in_time_pass", "DST_pass", "duplicate_identity_pass", "path_completeness_pass"],
                "properties": {
                    "status": {"enum": ["VALID", "PARTIAL", "UNAVAILABLE_TECHNICAL"]},
                    "expected_m1_bars": {"type": "integer", "minimum": 1}, "observed_m1_bars": {"type": "integer", "minimum": 0},
                    "point_in_time_pass": {"type": "boolean"}, "DST_pass": {"type": "boolean"},
                    "duplicate_identity_pass": {"type": "boolean"}, "path_completeness_pass": {"type": "boolean"},
                },
            },
            "research_policy": {
                "type": "object", "additionalProperties": False,
                "required": ["relationship_calculated", "candidate_created", "entry_assumed", "exit_assumed", "position_sized", "execution_optimized", "pnl_calculated", "account_return_calculated"],
                "properties": {key: {"const": False} for key in ["relationship_calculated", "candidate_created", "entry_assumed", "exit_assumed", "position_sized", "execution_optimized", "pnl_calculated", "account_return_calculated"]},
            },
        },
    }


def build_protocol(contract_record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_MONETIZATION_V1_PROTOCOL_1_0",
        "status": "FROZEN_BEFORE_BEHAVIOUR_OR_OUTCOME_ACCESS",
        "contract": dict(contract_record), "development": {"start_inclusive": "2021-08-01T00:00:00Z", "end_exclusive": "2025-01-01T00:00:00Z"},
        "forward_locks": {"calendar_2025": "LOCKED", "calendar_2026": "LOCKED"},
        "instruments": INSTRUMENTS, "XAUUSD": "EXCLUDED_HELD_GOLD_POLICY_UNCHANGED",
        "sessions": SESSIONS, "session_units": [{"instrument": instrument, "session_code": session} for instrument, session in session_units()],
        "identity": {
            "grain": "ONE_INSTRUMENT_X_SESSION_CODE_X_LOCAL_SESSION_DATE_WEEKDAY_IDENTITY",
            "decision_at": "SESSION_LOCAL_START_CONVERTED_WITH_IANA_TZ",
            "observation_start": "DECISION_AT_PLUS_ONE_MINUTE",
            "observation_end": "SESSION_LOCAL_END_EXCLUSIVE",
            "all_expected_identities_retained": True, "absence_not_automatically_holiday": True,
        },
        "eligibility": {
            "complete_path": "EVERY_EXPECTED_M1_OPEN_TIME_FROM_OBSERVATION_START_INCLUSIVE_TO_OBSERVATION_END_EXCLUSIVE_PRESENT",
            "complete": "ELIGIBLE_COMPLETE", "fraction_gte_0p90_but_lt_1": "PARTIAL_NOT_ELIGIBLE_COMPLETE_PATH",
            "fraction_lt_0p90": "INSUFFICIENT_NOT_ELIGIBLE", "zero": "NO_SOURCE_TIMESTAMPS_NOT_INFERRED_AS_HOLIDAY",
            "unit_readiness": "COMPLETE_IDENTITY_FRACTION_GTE_0P90",
        },
        "point_in_time": {
            "completed_candles_only": True, "decision_fact_gate": "available_at_lte_decision_at",
            "swing_known_after_second_right_close": True, "COT_publication_not_observation": True,
            "revision_available_only_at_revision_release": True, "unverified_forecast": "UNKNOWN",
            "continuous_future_roll_crossing": "UNKNOWN", "missing": "UNKNOWN_NOT_ZERO_OR_NEUTRAL",
        },
        "neutral_reference": {
            "definition": "OPEN_OF_EXACT_M1_BAR_AT_OBSERVATION_START", "not_entry_or_fill": True,
            "fixed_horizons_minutes": [5, 15, 30, 60, 120], "session_close": True,
        },
        "excursions": {
            "normalizer": "PRE_DECISION_14_BAR_M15_ATR_USING_COMPLETED_BARS_ONLY",
            "long_mfe": "MAX_0_MAX_HIGH_MINUS_REFERENCE", "long_mae": "MAX_0_REFERENCE_MINUS_MIN_LOW",
            "short_mfe": "LONG_MAE", "short_mae": "LONG_MFE", "trade_claim": False,
        },
        "first_passage": {
            "ATR_thresholds": [0.25, 0.50, 1.00, 1.50, 2.00, 3.00],
            "up": "FIRST_M1_HIGH_GTE_REFERENCE_PLUS_THRESHOLD_ATR", "down": "FIRST_M1_LOW_LTE_REFERENCE_MINUS_THRESHOLD_ATR",
            "same_bar_two_sided": "AMBIGUOUS_SAME_BAR_NO_STOP_FIRST_ASSUMPTION", "censor_at_observation_end": True,
        },
        "archetype_taxonomy": {
            "version": "ARCHETYPE_TAXONOMY_V1_0",
            "precedence": ["DATA_UNAVAILABLE", "SWEEP_REVERSAL", "FAILED_BREAK", "BREAKOUT_HOLD", "ONE_SIDED", "TWO_SIDED_EXPANSION", "TREND", "BALANCED_COMPRESSION", "ROTATIONAL", "MIXED_UNCLASSIFIED"],
            "thresholds_ATR": {"level_sweep": 0.05, "level_break": 0.10, "one_sided_favourable": 1.00, "one_sided_adverse_max": 0.25, "two_sided_each": 0.75, "trend_close": 0.50, "compression_range_max": 0.75, "compression_close_abs_max": 0.25},
            "close_location": {"up": 0.75, "down": 0.25}, "path_efficiency": {"trend_min": 0.35, "rotational_max": 0.20},
            "acceptance": "THREE_CONSECUTIVE_COMPLETED_M5_CLOSES_BEYOND_KNOWN_LEVEL",
            "reclaim": "COMPLETED_M5_CLOSE_BACK_INSIDE_WITHIN_THREE_M5_BARS",
            "taxonomy_is_descriptive_not_signal": True,
        },
        "future_milestone_order": [
            "M2_MATERIALIZE_COMPLETE_CASE_MATRIX_AND_DESCRIPTIVE_ATLAS",
            "M3_ARCHETYPE_FREQUENCY_AND_HYPOTHETICAL_CAPTURE_CEILINGS",
            "M4_RELATIONSHIP_DISCOVERY_AND_BOUNDED_RULE_DERIVATION",
            "M5_FREEZE_AND_TEST_EXECUTION_ECONOMICS_ON_DEVELOPMENT",
            "M6_OPEN_LOCKED_FORWARD_SEGMENTS_ONCE_IF_CANDIDATES_PASS",
        ],
        "milestone_1_forbidden": ["OHLC_ACCESS", "BEHAVIOUR_CALCULATION", "OUTCOME_JOIN", "RELATIONSHIP", "HYPOTHETICAL_RETURN", "ENTRY", "PNL", "CANDIDATE", "2025_VALUE_ACCESS", "2026_VALUE_ACCESS", "PAID_ACQUISITION"],
        "charges_authorized": False,
    }


def contract_markdown(predecessors: Mapping[str, Any]) -> str:
    units = "\n".join(f"| {INSTRUMENTS[i]['research_id']} (`{i}`) | `{s}` |" for i, s in session_units())
    return f"""# Multi-Asset Session Behaviour, Archetype and Monetization Discovery Contract V1

Status: **FROZEN BEFORE SESSION-BEHAVIOUR OR OUTCOME ACCESS**  
Branch: `{VERSION}`

## Authority and preserved history

This branch was authorized to census how six non-gold markets actually behave before proposing another strategy. It preserves every prior result and seal. In particular:

- Multi-asset Milestone 3 remains **`REJECT_NO_MULTI_ASSET_PORTFOLIO_EDGE`**.
- The observed gold policy `TARGET_TAKE_25_RUN_75` remains frozen, excluded, and carries no independent-validation claim.
- XAUUSD is not a target instrument or case in this branch.
- No negative result is inverted, renamed, filtered, or granted new validation credit.

The held gold result remains bound to `{predecessors['held_gold_final_result']['sha256']}` and the multi-asset Milestone-3 seal to `{predecessors['milestone_3_seal']['sha256']}`.

## Research question

For each eligible instrument and session, what complete path repeatedly occurs; how large, frequent, and stable is each path archetype; what conditions were genuinely observable beforehand; and only afterward, how much of that behaviour could a fixed point-in-time execution policy plausibly retain?

This is discovery, not an attempt to prove the four rejected Milestone-3 concepts. No predefined trigger receives privileged status.

## Partitions and lock

- Development: `2021-08-01T00:00:00Z <= t < 2025-01-01T00:00:00Z`.
- Calendar 2025: locked until a complete policy is frozen; never used to define an archetype, relationship, threshold, or execution rule.
- Calendar 2026: locked for later robustness and prospective tracking.
- Milestone 1 accesses development timestamp metadata only. It creates no session behaviour values.

## Frozen instrument-session census

Every Monday-Friday local session identity remains in the registry, including incomplete and unavailable identities. Missing timestamps are not silently called holidays.

| Instrument | Session unit |
|---|---|
{units}

Decision time is the local session start converted with its IANA timezone. The neutral path coordinate is the open of the exact M1 bar one minute after that decision. Observation ends at the frozen local session close. This coordinate is not an entry or fill.

## Decision-state boundary

Only facts with `available_at <= decision_at` may enter `decision_state`. All weekly, daily, H4, H1, M15, and M5 candles must be completed. Strict two-left/two-right swings become known only after the second right candle closes. COT becomes usable on publication, never Tuesday observation. Revisions enter only at their own release. Missing and unverified data are `UNKNOWN`, never neutral.

The state includes book-traceable mechanics, higher-timeframe structure, pre-existing levels, macro regime, expectations, catalysts, positioning where applicable, session context, and cross-market context. Institutional motives remain `INFERRED` unless directly sourced.

## Frozen outcome-neutral measurements

Future Milestone 2 may calculate, but Milestone 1 only defines:

- signed and absolute displacement at 5, 15, 30, 60, 120 minutes and session close;
- range, maximum upward and downward excursion, high/low timing and order;
- symmetric long/short MFE and MAE from the fixed neutral coordinate;
- first passage to ±0.25, ±0.50, ±1.00, ±1.50, ±2.00, and ±3.00 pre-decision ATR;
- close location, path efficiency, completed-M5 turns, and realized path volatility;
- interactions with levels already known at the decision; and
- deterministic descriptive archetypes.

MFE/MAE here are symmetric descriptive coordinates. They assume no trade, entry, stop, target, size, fill, or PnL. If both passage thresholds occur within the same M1 bar, the order is `AMBIGUOUS_SAME_BAR`; no stop-first convention is imported.

## Frozen archetype taxonomy

Classification order is fixed before outcomes:

1. data unavailable;
2. sweep and reversal;
3. failed break;
4. breakout and hold;
5. one-sided auction;
6. two-sided expansion;
7. directional trend;
8. balanced compression;
9. rotational path; and
10. mixed/unclassified.

Each directional family records `UP`, `DOWN`, `BOTH`, `NONE`, or `UNKNOWN`. Exact ATR, close-location, acceptance, reclaim, and efficiency thresholds are in the machine protocol. The taxonomy describes realised paths; it is never supplied to a decision checkpoint.

## Milestone sequence

1. **Milestone 1 — current:** contract, traceability, identity registry, case schema, metadata-only coverage audit, state, and seal.
2. Milestone 2: materialize all eligible decision states and descriptive session paths once.
3. Milestone 3: describe archetype frequencies and matched hypothetical capture ceilings without selecting execution.
4. Milestone 4: inspect simple conditions, then bounded interactions, and derive a small frozen shortlist.
5. Milestone 5: test point-in-time execution and economics on development only.
6. Milestone 6: if candidates survive, open locked forward segments once and unchanged.

## Milestone 1 prohibition and stop

Milestone 1 may inspect identifiers, hashes, filenames, timestamps, schema metadata, and counts. It may not inspect OHLC, spread values, volume values, outcomes, excursions, directions, relationships, hypothetical returns, trades, R, PnL, or 2025/2026 market values. It incurs no charge.

Completion of the Milestone-1 state and seal is a mandatory stop. No case matrix is materialized in this milestone.
"""


def traceability_markdown(trace: Mapping[str, Any]) -> str:
    counts = trace["decision_coverage_counts"]
    rows = "\n".join(f"| {key} | {value} |" for key, value in sorted(counts.items()))
    return f"""# Multi-Asset Session Behaviour V1 — Traceability Registry

The Reference Book is bound at `{trace['reference_book']['sha256']}`. The registry freezes **{trace['field_count']}** fields: {trace['decision_field_count']} point-in-time decision fields and {trace['outcome_field_count']} subsequent-behaviour fields.

| Development source status | Decision fields |
|---|---:|
{rows}

Every decision fact carries value, unit, epistemic classification, `as_of`, `available_at`, quality, method, explanation, and source hashes. Every subsequent-behaviour field is permanently `decision_eligible=false`.

Important limitations remain visible: no complete cross-asset exchange order book, no exact historical meeting-probability curve, no verified full historical consensus feed, no options/gamma surface, no versioned ETF/central-bank flow panel, no licensed unscheduled-news history, incomplete Japan/euro rate differentials, and no verified EIA inventory history. These are `UNKNOWN` or partial—not neutral.

XAUUSD may appear only as a contemporaneous cross-market context for silver where point-in-time coverage permits. It is not a target instrument and the held gold policy is not reopened.
"""


def case_matrix_markdown(trace: Mapping[str, Any]) -> str:
    return f"""# Multi-Asset Session Behaviour V1 — Comprehensive Case Matrix

Schema: `research_schemas/{CASE_SCHEMA.name}`  
Frozen fields: **{trace['field_count']}**

One future row represents one frozen `instrument × session_code × local_session_date` identity.

```text
case
├── case_metadata
├── lineage
├── decision_state                 available_at <= decision_at
│   ├── mechanics and quality
│   ├── completed W1/D1/H4/H1/M15/M5 structure
│   ├── pre-existing levels
│   ├── macro, expectations, positioning and catalysts
│   ├── session and cross-market context
│   └── synthesis, contradictions and unknowns
├── subsequent_behaviour           decision_eligible = false
│   ├── fixed neutral reference
│   ├── fixed-horizon displacement
│   ├── range and symmetric MFE/MAE
│   ├── first-passage clocks
│   ├── high/low timing and path statistics
│   ├── known-level interactions
│   └── deterministic archetype
├── quality
└── research_policy                all execution/PnL flags false
```

The neutral reference is the exact M1 open at `decision_at + 1 minute`. It is not an assumed fill. `long_mfe`, `long_mae`, `short_mfe`, and `short_mae` are symmetric path coordinates; no trade direction is assigned.

A future case may be `VALID` only if its identity is frozen, its observation path has every expected M1 timestamp, IANA/DST conversion passes, duplicate identity checks pass, all decision facts satisfy availability, and source hashes match. Incomplete identities remain in the coverage ledger and cannot be silently deleted.

Milestone 1 defines this schema but creates **zero case rows**.
"""


def source_inventory(certification: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in certification["instrument_certifications"]:
        symbol = item["mt5_symbol"]
        if symbol not in INSTRUMENTS:
            continue
        coverage = item["coverage"]
        if item["classification"] != "PRESENT_AND_ADEQUATE" or not coverage["eligible"]:
            raise ValueError(f"Certified source is not adequate: {symbol}")
        output[symbol] = {
            "research_id": INSTRUMENTS[symbol]["research_id"], "classification": item["classification"],
            "canonical_unique_timestamps": coverage["canonical_unique_timestamps"],
            "first_timestamp": coverage["first_timestamp"], "last_timestamp": coverage["last_timestamp"],
            "covered_month_count": coverage["covered_month_count"], "source_files": coverage["source_files"],
            "source_file_inventory_sha256": coverage["source_file_inventory_sha256"],
            "semantic_market_values_accessed_in_certification": coverage["semantic_market_values_accessed"],
        }
    if set(output) != set(INSTRUMENTS):
        raise ValueError(f"Wrong certified instrument set: {set(output)}")
    return output


def verify_source_files(inventory: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for symbol in sorted(inventory):
        for item in inventory[symbol]["source_files"]:
            path = ROOT / item["path"]
            verified = path.is_file() and path.stat().st_size == item["bytes"] and sha256_file(path) == item["sha256"]
            checks.append({"symbol": symbol, **item, "verified": verified})
            if not verified:
                raise ValueError(f"Certified source changed: {item['path']}")
    return checks


def timestamp_minutes_primary(files: Sequence[Mapping[str, Any]]) -> set[int]:
    output: set[int] = set()
    start_ns = int(START.timestamp() * 1_000_000_000)
    end_ns = int(END.timestamp() * 1_000_000_000)
    for item in files:
        path = ROOT / item["path"]
        for chunk in pd.read_csv(path, usecols=["open_time"], chunksize=200_000, dtype={"open_time": "string"}):
            values = pd.to_datetime(chunk["open_time"], utc=True, errors="raise").dt.as_unit("ns").astype("int64")
            values = values[(values >= start_ns) & (values < end_ns)] // 60_000_000_000
            output.update(int(value) for value in values)
    return output


def timestamp_minutes_reference(files: Sequence[Mapping[str, Any]]) -> set[int]:
    output: set[int] = set()
    start_minute, end_minute = int(START.timestamp() // 60), int(END.timestamp() // 60)
    for item in reversed(list(files)):
        path = ROOT / item["path"]
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if "open_time" not in (reader.fieldnames or []):
                raise ValueError(path)
            for row in reader:
                raw = row["open_time"]
                timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                minute = int(timestamp.astimezone(UTC).timestamp() // 60)
                if start_minute <= minute < end_minute:
                    output.add(minute)
    return output


def audit_identity_coverage(identity_rows: Sequence[Mapping[str, Any]], timestamp_sets: Mapping[str, set[int]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    unit_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for identity in identity_rows:
        start = int(datetime.fromisoformat(str(identity["observation_start_utc"]).replace("Z", "+00:00")).timestamp() // 60)
        end = int(datetime.fromisoformat(str(identity["observation_end_utc"]).replace("Z", "+00:00")).timestamp() // 60)
        timestamps = timestamp_sets[str(identity["instrument"])]
        expected = end - start
        present = sum(minute in timestamps for minute in range(start, end))
        fraction = present / expected if expected else 0.0
        if present == expected:
            classification = "ELIGIBLE_COMPLETE"
        elif fraction >= 0.90:
            classification = "PARTIAL_NOT_ELIGIBLE_COMPLETE_PATH"
        elif present == 0:
            classification = "NO_SOURCE_TIMESTAMPS_NOT_INFERRED_AS_HOLIDAY"
        else:
            classification = "INSUFFICIENT_NOT_ELIGIBLE"
        missing = [minute for minute in range(start, end) if minute not in timestamps]
        row = {
            "case_id": identity["case_id"], "instrument": identity["instrument"], "research_id": identity["research_id"],
            "session_code": identity["session_code"], "session_date_local": identity["session_date_local"],
            "expected_path_minutes": expected, "present_path_minutes": present, "coverage_fraction": round(fraction, 12),
            "classification": classification, "missing_timestamp_count": len(missing),
            "missing_timestamp_hash": canonical_hash(missing),
            "first_missing_utc": datetime.fromtimestamp(missing[0] * 60, UTC).isoformat().replace("+00:00", "Z") if missing else None,
            "last_missing_utc": datetime.fromtimestamp(missing[-1] * 60, UTC).isoformat().replace("+00:00", "Z") if missing else None,
        }
        rows.append(row)
        unit_counts[f"{identity['instrument']}|{identity['session_code']}"][classification] += 1
    rows.sort(key=lambda row: (row["session_date_local"], row["instrument"], row["session_code"]))
    for unit, counts in sorted(unit_counts.items()):
        total = sum(counts.values())
        complete = counts["ELIGIBLE_COMPLETE"]
        summaries[unit] = {
            "expected_identities": total, "complete_eligible": complete,
            "complete_fraction": round(complete / total, 12), "classifications": dict(sorted(counts.items())),
            "readiness_gate_complete_fraction_gte_0p90": complete / total >= 0.90,
        }
    return rows, summaries


def implementation_coverage(name: str, identity_registry: Mapping[str, Any], inventory: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    timestamp_sets: dict[str, set[int]] = {}
    for symbol in sorted(inventory):
        files = inventory[symbol]["source_files"]
        timestamps = timestamp_minutes_primary(files) if name == "primary" else timestamp_minutes_reference(files)
        timestamp_sets[symbol] = timestamps
    rows, summaries = audit_identity_coverage(identity_registry["rows"], timestamp_sets)
    canonical_timestamp_counts = {symbol: len(values) for symbol, values in timestamp_sets.items()}
    result = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_COVERAGE_IMPLEMENTATION_1_0",
        "implementation": name, "access_mode": "OPEN_TIME_COLUMN_ONLY_NO_MARKET_VALUES",
        "identity_count": len(rows), "canonical_timestamp_counts": canonical_timestamp_counts,
        "session_units": summaries, "coverage_rows": rows, "coverage_rows_hash": canonical_hash(rows),
        "semantic_checksum": canonical_hash({"counts": canonical_timestamp_counts, "summaries": summaries, "rows": rows}),
        "controls": {"OHLC_accessed": False, "spread_or_volume_values_accessed": False, "outcomes_calculated": False, "2025_or_2026_values_accessed": False},
    }
    del timestamp_sets
    return result


def macro_coverage() -> list[dict[str, Any]]:
    audit = load_json(M1_COVERAGE)
    output: list[dict[str, Any]] = []
    for item in audit["macro_and_context_sources_reused"]:
        output.append({
            "id": item["id"], "classification": item["classification"], "lineage": item["lineage"],
            "fitness": item["fitness"], "coverage_metadata": item["coverage"], "hashes": item["hashes"],
        })
    return output


def coverage_markdown(audit: Mapping[str, Any]) -> str:
    table = []
    for unit, item in audit["session_units"].items():
        instrument, session = unit.split("|")
        table.append(f"| {INSTRUMENTS[instrument]['research_id']} | `{session}` | {item['expected_identities']} | {item['complete_eligible']} | {item['complete_fraction']:.2%} | {'PASS' if item['readiness_gate_complete_fraction_gte_0p90'] else 'FAIL'} |")
    timestamps = "\n".join(f"| {INSTRUMENTS[symbol]['research_id']} | {count:,} |" for symbol, count in audit["canonical_timestamp_counts"].items())
    return f"""# Multi-Asset Session Behaviour V1 — Metadata-Only Coverage Audit

Verdict: **`{audit['verdict']}`**

No OHLC, spread value, volume value, direction, return, excursion, relationship, hypothetical return, trade, PnL, or 2025/2026 market value was accessed. Only sealed source metadata and the `open_time` column for development files were used.

## Timestamp source inventory

| Instrument | Unique development M1 timestamps |
|---|---:|
{timestamps}

## Frozen session identity coverage

| Instrument | Session | Expected weekday identities | Complete eligible paths | Complete fraction | Unit gate |
|---|---|---:|---:|---:|---|
{chr(10).join(table)}

Every expected identity remains recorded. A session is complete only when every exact M1 timestamp from `decision + 1 minute` through the frozen session end is present. Partial sessions and zero-timestamp dates are not deleted or automatically labelled holidays.

Primary and reference coverage checksum: `{audit['independent_reproduction']['primary_semantic_checksum']}`  
Exact reproduction: **{str(audit['independent_reproduction']['passed']).lower()}**

## Context-source disposition

The existing sealed macro inventory is reused without value access. Missing or partial sources—including exact meeting probabilities, complete historical consensus, non-gold COT, options/gamma, ETF/central-bank flows, Japan/euro differential curves, EIA inventories, and unscheduled news—remain explicit `UNKNOWN` or partial fields.

## Boundary

This audit certifies that the six-market development census is technically ready for a separately authorized Milestone 2. It does not calculate a single behaviour, archetype, relationship, hypothetical return, signal, or trade, and does not authorize Milestone 2.
"""


def milestone_markdown(audit: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    return f"""# Multi-Asset Session Behaviour, Archetype and Monetization V1 — Milestone 1

## Verdict

**`{state['verdict']}`**

Milestone 1 is complete and stopped. The branch contains six non-gold instruments, {len(session_units())} frozen instrument-session units, {audit['expected_identity_count']:,} expected weekday identities, and {audit['complete_eligible_identity_count']:,} timestamp-complete identities eligible for future case construction.

No market outcome, path metric, relationship, hypothetical return, strategy, entry, PnL, 2025 value, or 2026 value was calculated. Paid acquisition: **$0.00**.

## Completed deliverables

- Contract: `{CONTRACT.name}`
- Machine protocol: `research_manifests/{PROTOCOL.name}`
- Traceability registry: `research_manifests/{TRACEABILITY.name}`
- Comprehensive schema: `research_schemas/{CASE_SCHEMA.name}`
- Frozen identity registry: `research_artifacts/{ARTIFACTS.name}/{IDENTITIES.name}`
- Coverage audit: `research_artifacts/{ARTIFACTS.name}/{COVERAGE_AUDIT.name}`
- State: `research_artifacts/{ARTIFACTS.name}/{STATE.name}`

## Preserved gold result

`TARGET_TAKE_25_RUN_75` remains held unchanged and excluded. Its observed 1.1888R/month development result has not been opened, retuned, or called independently validated by this branch.

## Next boundary

The next possible step is **Milestone 2: complete decision-state and descriptive session-path materialization** using only the frozen complete identities. It requires separate authorization. Milestone 2 was not started.
"""


def ensure_outputs_absent() -> None:
    outputs = [CONTRACT, TRACEABILITY_MD, CASE_MATRIX_MD, COVERAGE_MD, MILESTONE_MD, PROTOCOL, TRACEABILITY, DESIGN_FREEZE, FINAL_SEAL, CASE_SCHEMA, IDENTITIES, COVERAGE_PRIMARY, COVERAGE_REFERENCE, COVERAGE_AUDIT, STATE, VALIDATION]
    present = [str(path) for path in outputs if path.exists()]
    if present:
        raise FileExistsError(present)


def main() -> None:
    ensure_outputs_absent()
    predecessors = verify_predecessors()
    write_text_exclusive(CONTRACT, contract_markdown(predecessors))
    protocol = build_protocol(file_record(CONTRACT))
    write_json_exclusive(PROTOCOL, protocol)
    traceability = build_traceability()
    traceability["contract"] = file_record(CONTRACT)
    traceability["protocol"] = file_record(PROTOCOL)
    traceability["catalog_hash"] = canonical_hash({"decision": traceability["decision_fields"], "outcome": traceability["subsequent_behaviour_fields"]})
    write_json_exclusive(TRACEABILITY, traceability)
    write_text_exclusive(TRACEABILITY_MD, traceability_markdown(traceability))
    schema = build_case_schema(traceability)
    schema["x-traceability-sha256"] = sha256_file(TRACEABILITY)
    write_json_exclusive(CASE_SCHEMA, schema)
    write_text_exclusive(CASE_MATRIX_MD, case_matrix_markdown(traceability))
    identity_registry = build_identity_registry()
    identity_registry["contract_sha256"] = sha256_file(CONTRACT)
    identity_registry["protocol_sha256"] = sha256_file(PROTOCOL)
    write_json_exclusive(IDENTITIES, identity_registry)

    certification = load_json(M2_CERTIFICATION)
    inventory = source_inventory(certification)
    source_checks = verify_source_files(inventory)
    design_files = [CONTRACT, PROTOCOL, TRACEABILITY, CASE_SCHEMA, IDENTITIES, TRACEABILITY_MD, CASE_MATRIX_MD]
    design_freeze = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_M1_DESIGN_FREEZE_1_0",
        "status": "SEALED_BEFORE_TIMESTAMP_COVERAGE_AUDIT_AND_ANY_BEHAVIOUR_ACCESS",
        "sealed_at_utc": utc_now(), "artifacts": [file_record(path) for path in design_files],
        "predecessors": predecessors, "source_certification": file_record(M2_CERTIFICATION),
        "source_file_count": len(source_checks), "every_source_hash_verified": all(item["verified"] for item in source_checks),
        "controls": {"OHLC_accessed": False, "outcomes_calculated": False, "relationships_calculated": False, "2025_values_accessed": False, "2026_values_accessed": False, "charge_usd": 0.0},
    }
    write_json_exclusive(DESIGN_FREEZE, design_freeze)

    primary = implementation_coverage("primary", identity_registry, inventory)
    reference = implementation_coverage("reference", identity_registry, inventory)
    if primary["semantic_checksum"] != reference["semantic_checksum"] or primary["coverage_rows"] != reference["coverage_rows"]:
        raise ValueError("Independent timestamp coverage implementations disagree")
    write_json_exclusive(COVERAGE_PRIMARY, primary)
    write_json_exclusive(COVERAGE_REFERENCE, reference)
    all_units_pass = all(item["readiness_gate_complete_fraction_gte_0p90"] for item in primary["session_units"].values())
    complete = sum(row["classification"] == "ELIGIBLE_COMPLETE" for row in primary["coverage_rows"])
    audit = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_M1_COVERAGE_AUDIT_1_0",
        "verdict": "PASS_M1_METADATA_COVERAGE_READY" if all_units_pass else "FAIL_M1_SESSION_UNIT_COVERAGE",
        "audit_mode": "DEVELOPMENT_OPEN_TIME_ONLY_NO_MARKET_VALUES",
        "expected_identity_count": len(primary["coverage_rows"]), "complete_eligible_identity_count": complete,
        "incomplete_identity_count": len(primary["coverage_rows"]) - complete,
        "canonical_timestamp_counts": primary["canonical_timestamp_counts"], "session_units": primary["session_units"],
        "coverage_rows": primary["coverage_rows"], "coverage_rows_hash": primary["coverage_rows_hash"],
        "source_inventory": inventory, "source_checks_count": len(source_checks), "every_source_hash_verified": True,
        "macro_and_context_sources": macro_coverage(),
        "independent_reproduction": {"passed": True, "primary_semantic_checksum": primary["semantic_checksum"], "reference_semantic_checksum": reference["semantic_checksum"], "coverage_parity": True},
        "controls": {
            "OHLC_accessed": False, "spread_or_volume_values_accessed": False, "outcomes_calculated": False,
            "archetypes_calculated": False, "relationships_calculated": False, "hypothetical_returns_calculated": False,
            "trades_or_PnL_calculated": False, "XAUUSD_target_cases": 0,
            "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    }
    write_json_exclusive(COVERAGE_AUDIT, audit)
    write_text_exclusive(COVERAGE_MD, coverage_markdown(audit))

    state_core = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_STATE_1_0",
        "verdict": "PASS_MILESTONE_1_MANDATORY_STOP" if all_units_pass else "FAIL_MILESTONE_1_COVERAGE_STOP",
        "status": "COMPLETE_MANDATORY_STOP", "current_milestone": 1, "next_milestone_authorized": False,
        "branch": VERSION, "development": "2021-08-01/2024-12-31",
        "calendar_2025": "LOCKED", "calendar_2026": "LOCKED", "XAUUSD": "EXCLUDED_HELD_UNCHANGED",
        "instrument_count": len(INSTRUMENTS), "instrument_session_units": len(session_units()),
        "expected_identities": audit["expected_identity_count"], "complete_eligible_identities": complete,
        "artifacts": [file_record(path) for path in [CONTRACT, PROTOCOL, TRACEABILITY, CASE_SCHEMA, IDENTITIES, DESIGN_FREEZE, COVERAGE_PRIMARY, COVERAGE_REFERENCE, COVERAGE_AUDIT, TRACEABILITY_MD, CASE_MATRIX_MD, COVERAGE_MD]],
        "predecessors": predecessors,
        "controls": audit["controls"],
    }
    state = {**state_core, "state_hash": canonical_hash(state_core), "completed_at_utc": utc_now()}
    write_json_exclusive(STATE, state)
    write_text_exclusive(MILESTONE_MD, milestone_markdown(audit, state))

    checks = {
        "predecessor_seals_verified": predecessors["all_verified"],
        "gold_policy_held_unchanged": predecessors["held_gold_policy"]["status"] == "HELD_UNCHANGED_EXCLUDED_FROM_BRANCH",
        "XAUUSD_excluded": all(row["instrument"] != "XAUUSD" for row in identity_registry["rows"]),
        "identity_count_exact": len(identity_registry["rows"]) == 13_380,
        "identity_keys_unique": len({row["case_id"] for row in identity_registry["rows"]}) == len(identity_registry["rows"]),
        "all_identity_timestamps_pre_2025": all(row["observation_end_utc"] <= "2025-01-01T00:00:00Z" for row in identity_registry["rows"]),
        "primary_reference_exact": primary["semantic_checksum"] == reference["semantic_checksum"],
        "all_session_units_ready": all_units_pass,
        "schema_json_valid": isinstance(load_json(CASE_SCHEMA), dict),
        "decision_outcome_separation": all(row["decision_eligible"] is False for row in traceability["subsequent_behaviour_fields"]),
        "no_case_rows_materialized": True,
        "no_outcomes_relationships_hypothetical_returns_or_PnL": not any([audit["controls"]["outcomes_calculated"], audit["controls"]["relationships_calculated"], audit["controls"]["hypothetical_returns_calculated"], audit["controls"]["trades_or_PnL_calculated"]]),
        "forward_locks_intact": not audit["controls"]["calendar_2025_values_accessed"] and not audit["controls"]["calendar_2026_values_accessed"],
        "no_charge": audit["controls"]["paid_acquisition_usd"] == 0.0,
    }
    validation = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_M1_VALIDATION_1_0",
        "passed": all(checks.values()), "checks": checks,
        "passed_count": sum(checks.values()), "total_count": len(checks), "validation_hash": canonical_hash(checks),
    }
    if not validation["passed"]:
        raise ValueError(validation)
    write_json_exclusive(VALIDATION, validation)
    final_files = [CONTRACT, PROTOCOL, TRACEABILITY, CASE_SCHEMA, IDENTITIES, DESIGN_FREEZE, COVERAGE_PRIMARY, COVERAGE_REFERENCE, COVERAGE_AUDIT, STATE, VALIDATION, TRACEABILITY_MD, CASE_MATRIX_MD, COVERAGE_MD, MILESTONE_MD, IMPLEMENTATION]
    records = [file_record(path) for path in final_files]
    seal = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_MILESTONE1_SEAL_1_0",
        "status": "SEALED_MILESTONE_1_COMPLETE_MANDATORY_STOP", "verdict": state["verdict"],
        "sealed_at_utc": utc_now(), "artifacts": records, "artifact_set_hash": canonical_hash(records),
        "predecessors": predecessors, "state_hash": state["state_hash"], "validation_hash": validation["validation_hash"],
        "next_milestone_authorized": False, "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FINAL_SEAL, seal)
    print(json.dumps({
        "verdict": seal["verdict"], "instruments": len(INSTRUMENTS), "session_units": len(session_units()),
        "expected_identities": audit["expected_identity_count"], "complete_eligible": complete,
        "validation": f"{validation['passed_count']}/{validation['total_count']}",
        "coverage_checksum": primary["semantic_checksum"], "seal": file_record(FINAL_SEAL),
    }, indent=2))


if __name__ == "__main__":
    main()
