#!/usr/bin/env python3
"""Freeze Multi-Asset Session Behaviour V1 Milestones 2 and 3."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
R2_SEAL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m1_r2_seal.json"
R2_RESULT = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2/recertification.json"
SOURCE_CERT = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json"
M1_PROTOCOL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_protocol.json"
TRACEABILITY = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_traceability.json"
CONTRACT = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_DISCOVERY_CONTRACT_V1.md"
ENGINE = ROOT / "tools/msbam_v1_m2_m3_engine.py"
RUNNER = ROOT / "tools/run_multi_asset_session_behaviour_archetype_monetization_v1_m2_m3.py"
TESTS = ROOT / "tests/test_msbam_v1_m2_m3_engine.py"
LEGACY = ROOT / "tools/run_multi_asset_macro_session_portfolio_v1_m3.py"
M2_PROTOCOL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m2_protocol.json"
M3_PROTOCOL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m3_feasibility_protocol.json"
M2_FREEZE = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m2_preoutcome_freeze.json"
M3_FREEZE = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m3_feasibility_freeze.json"
SYMBOLS = ("XAGUSD", "EURUSD", "USDJPY", "USTEC", "US500", "XTIUSD")
UTC = timezone.utc


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


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


def verify_record(item: Mapping[str, Any]) -> None:
    path = ROOT / str(item["path"])
    if not path.is_file() or path.stat().st_size != int(item["bytes"]) or sha256_file(path) != str(item["sha256"]):
        raise ValueError(f"Predecessor changed: {item['path']}")


def source_records() -> list[dict[str, Any]]:
    certification = load(SOURCE_CERT)
    output: list[dict[str, Any]] = [record(SOURCE_CERT)]
    found: set[str] = set()
    for item in certification.get("instrument_certifications", []):
        symbol = str(item.get("mt5_symbol"))
        if symbol not in SYMBOLS:
            continue
        if item.get("classification") != "PRESENT_AND_ADEQUATE":
            raise ValueError(f"Inadequate source certification: {symbol}")
        found.add(symbol)
        for source in item.get("coverage", {}).get("source_files", []):
            verify_record(source)
            if "2025" in str(source["path"]) or "2026" in str(source["path"]):
                raise ValueError(f"Forward source selected: {source['path']}")
            output.append(dict(source))
    if found != set(SYMBOLS):
        raise ValueError(f"Missing certified symbols: {sorted(set(SYMBOLS) - found)}")
    for path in (
        ROOT / "research_artifacts/gold_casebook_v01/fundamentals.jsonl.gz",
        ROOT / "research_artifacts/gold_casebook_v01/events.jsonl.gz",
        ROOT / "research_artifacts/gold_casebook_v01/positioning.jsonl.gz",
    ):
        output.append(record(path))
    unique = {item["path"]: item for item in output}
    return [unique[key] for key in sorted(unique)]


def main() -> int:
    r2_seal = load(R2_SEAL)
    if r2_seal.get("verdict") != "PASS_M1_R2_BRANCH_READY" or not r2_seal.get("branch_ready"):
        raise ValueError("Milestone 1-R2 branch PASS is required")
    for item in r2_seal.get("artifacts", []):
        verify_record(item)
    r2_result = load(R2_RESULT)
    if len(r2_result.get("passing_units", [])) != 12:
        raise ValueError("Expected 12 passing units")
    sources = source_records()

    m2_protocol = {
        "version": "MSBAM_V1_M2_PROTOCOL_1_0",
        "status": "FROZEN_BEFORE_M2_MARKET_VALUE_ACCESS",
        "frozen_at_utc": now(),
        "development": {"start_inclusive": "2021-08-01T00:00:00Z", "end_exclusive": "2025-01-01T00:00:00Z", "months": 41},
        "population": {
            "selection": "R2_ELIGIBLE_FOR_MILESTONE_2_TRUE_AND_UNIT_IN_12_PASSING_UNITS",
            "expected_case_count": 10388,
            "failed_units_retained_as": "TECHNICALLY_UNAVAILABLE_NOT_SELECTED_FOR_M2",
            "passing_units": r2_result["passing_units"],
            "XAUUSD": "EXCLUDED_HELD_POLICY_UNCHANGED",
        },
        "neutral_path": {
            "reference": "EXACT_M1_OPEN_AT_OBSERVATION_START",
            "session_path": "OBSERVED_M1_BARS_FROM_START_INCLUSIVE_TO_END_EXCLUSIVE",
            "ATR": "MEAN_TRUE_RANGE_OF_14_COMPLETED_M15_BARS_AVAILABLE_AT_DECISION",
            "fixed_horizons_minutes": [5, 15, 30, 60, 120],
            "MFE_MAE": "SYMMETRIC_FROM_NEUTRAL_REFERENCE_WITH_NO_ENTRY_OR_TRADE_CLAIM",
            "first_passage_ATR": [0.25, 0.5, 1.0, 1.5, 2.0, 3.0],
            "same_M1_two_sided": "AMBIGUOUS_SAME_BAR",
        },
        "timing": ["SESSION_HIGH_MINUTE", "SESSION_LOW_MINUTE", "HIGH_LOW_ORDER", "FIXED_HORIZON_DISPLACEMENTS", "TURNING_POINT_COUNT", "PATH_EFFICIENCY"],
        "point_in_time_context": {
            "completed_candles": ["W1", "D1", "H4", "H1", "M15", "M5"],
            "confirmed_swings": "STRICT_2_LEFT_2_RIGHT_KNOWN_AFTER_SECOND_RIGHT_CLOSE",
            "preexisting_levels": ["PRIOR_DAY", "PRIOR_WEEK", "PRIOR_SAME_SESSION", "M15_SWINGS", "H1_SWINGS", "H4_SWINGS", "ROUND_NUMBER"],
            "macro": "SEALED_POINT_IN_TIME_MACROBOOK_AVAILABLE_AT_LTE_DECISION",
            "events": "SCHEDULED_TIER1_EVENT_METADATA_AVAILABLE_AT_LTE_DECISION",
            "missing_or_unlicensed": "UNKNOWN_NEVER_ZERO_OR_NEUTRAL",
        },
        "level_interactions": {
            "sweep": "0.05_ATR_BEYOND_PREEXISTING_LEVEL",
            "break": "0.10_ATR_BEYOND_PREEXISTING_LEVEL",
            "acceptance": "THREE_CONSECUTIVE_COMPLETED_M5_CLOSES_BEYOND_LEVEL",
            "reclaim": "COMPLETED_M5_CLOSE_BACK_INSIDE_WITHIN_THREE_M5_BARS",
        },
        "archetype_precedence": ["DATA_UNAVAILABLE", "SWEEP_REVERSAL", "FAILED_BREAK", "BREAKOUT_HOLD", "ONE_SIDED", "TWO_SIDED_EXPANSION", "TREND", "BALANCED_COMPRESSION", "ROTATIONAL", "MIXED_UNCLASSIFIED"],
        "archetype_thresholds_ATR": {"one_sided_favourable": 1.0, "one_sided_adverse_max": 0.25, "two_sided_each": 0.75, "trend_close": 0.5, "compression_range_max": 0.75, "compression_close_abs_max": 0.25, "trend_efficiency_min": 0.35, "rotational_efficiency_max": 0.20},
        "reproduction": "PRIMARY_AND_REFERENCE_EXACT_ROW_IDENTITIES_SEMANTICS_AND_BYTE_IDENTICAL_JSON",
        "forbidden": ["ENTRY_OPTIMIZATION", "STRATEGY_SELECTION", "CANDIDATE", "EDGE_CLAIM", "2025_VALUE_ACCESS", "2026_VALUE_ACCESS", "PAID_ACQUISITION"],
    }
    write(M2_PROTOCOL, m2_protocol)

    m3_protocol = {
        "version": "MSBAM_V1_M3_FEASIBILITY_PROTOCOL_1_0",
        "status": "FROZEN_BEFORE_M3_HYPOTHETICAL_CAPTURE_CALCULATION",
        "frozen_at_utc": now(),
        "purpose": "TARGET_CAPACITY_FALSIFICATION_NOT_EDGE_OR_STRATEGY_DISCOVERY",
        "timeframes_separate": {"M15": 15, "H1": 60, "H4": 240},
        "four_stage_waterfall": {
            "stage_1": "MAX_OF_UP_AND_DOWN_SESSION_EXCURSION_DIVIDED_BY_PREDECISION_ATR; DIRECTION_CHOSEN_WITH HINDSIGHT; NONTRADABLE_CEILING",
            "stage_2": "FIRST_COMPLETED_TRACK_BAR_CLOSING_AT_LEAST_0.25_ATR_FROM_REFERENCE_AND_IN_OUTER_QUARTER; DIRECTION_FIXED_THEN SUBSEQUENT_MFE",
            "stage_3": "NEXT_OBSERVED_M1_OPEN_AFTER_ONE_MINUTE_LATENCY; FIXED_1_ATR_STOP_AND_1_ATR_TARGET; SESSION_TIME_EXIT; STOP_FIRST_ON_AMBIGUOUS_M1",
            "stage_4": "STAGE_3_AFTER_COSTS_POSITION_FEASIBILITY_AND_ONE_CONCURRENT_POSITION_PER_CORRELATION_CLUSTER",
        },
        "constant_trigger": {
            "threshold_ATR": 0.25, "close_location_bullish_min": 0.75, "close_location_bearish_max": 0.25,
            "completed_relative_bars_only": True, "entry_latency_minutes": 1, "maximum_no_tick_entry_delay_minutes": 2,
            "first_qualifying_bar_only": True, "optimization": False,
        },
        "constant_resolution": {"stop_ATR": 1.0, "target_ATR": 1.0, "deadline": "FROZEN_SESSION_END", "ambiguous_bar": "STOP_FIRST", "gap": "NEXT_M1_OPEN"},
        "costs": {"spread": "MAX_ENTRY_OR_EXIT_BROKER_SPREAD_POINTS_CONVERTED_TO_PRICE_DIVIDED_BY_ATR", "commission_slippage_latency_R": 0.03, "minimum_total_cost_R": 0.05, "formula": "MAX(SPREAD_R_PLUS_0.03,0.05)"},
        "risk": {
            "account_usd": 10000.0, "maximum_planned_risk_usd_per_cluster": 100.0,
            "sizing": "FLOOR_TO_FROZEN_BROKER_VOLUME_STEP_NEVER_ABOVE_100_USD",
            "clusters": {"PRECIOUS_METALS": ["XAGUSD"], "USD_FX": ["EURUSD", "USDJPY"], "US_EQUITY_INDICES": ["USTEC", "US500"], "ENERGY": ["XTIUSD"]},
            "overlap_priority": "EARLIEST_ENTRY_THEN_INSTRUMENT_CASE_TIMEFRAME_LEXICOGRAPHIC",
        },
        "combined_portfolio": "EARLIEST_OF_M15_H1_H4_PER_CASE_THEN_CLUSTER_OVERLAP_POLICY",
        "reporting": ["INSTRUMENT", "SESSION", "TIMEFRAME", "ARCHETYPE", "OCCURRENCES_PER_MONTH", "DIRECTION_FREQUENCIES", "MFE_MAE", "FIRST_PASSAGE", "STAGE1_R_PER_MONTH", "STAGE2_R_PER_MONTH", "STAGE3_R_PER_MONTH", "STAGE4_NET_R_PER_MONTH", "DOLLARS_PER_MONTH", "EXACT_RETENTION_LOSS"],
        "decision_rule": {"PASS_CAPACITY": "COMBINED_STAGE4_NET_R_PER_MONTH_GTE_10", "FAIL_CAPACITY": "COMBINED_STAGE4_NET_R_PER_MONTH_LT_10", "edge_claim": False},
        "forbidden": ["OPTIMIZE_ENTRY", "SELECT_STRATEGY", "CREATE_CANDIDATE", "CLAIM_EDGE", "REMOVE_LOSSES", "2025_VALUE_ACCESS", "2026_VALUE_ACCESS", "PAID_ACQUISITION"],
        "reproduction": "PRIMARY_AND_REFERENCE_EXACT_BYTE_IDENTICAL_FEASIBILITY_PAYLOADS",
    }
    write(M3_PROTOCOL, m3_protocol)

    bindings = {
        "contract": record(CONTRACT), "m1_protocol": record(M1_PROTOCOL), "traceability": record(TRACEABILITY),
        "coverage_r2_seal": record(R2_SEAL), "coverage_r2_result": record(R2_RESULT),
        "m2_protocol": record(M2_PROTOCOL), "m3_protocol": record(M3_PROTOCOL),
        "engine": record(ENGINE), "runner": record(RUNNER), "synthetic_tests": record(TESTS),
        "sealed_legacy_utility": record(LEGACY),
    }
    common = {
        "bindings": bindings, "source_bindings": sources,
        "synthetic_preaccess_proof": {"tests": 4, "status": "PASS", "pytest_package_available": False, "direct_assertion_runner": "PASS"},
        "controls": {"calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "charge_usd": 0.0, "paid_acquisition_authorized": False},
        "XAUUSD": "EXCLUDED_HELD_POLICY_UNCHANGED",
    }
    write(M2_FREEZE, {"version": "MSBAM_V1_M2_FREEZE_1_0", "status": "SEALED_BEFORE_M2_MARKET_VALUE_ACCESS", "sealed_at_utc": now(), **common})
    write(M3_FREEZE, {"version": "MSBAM_V1_M3_FREEZE_1_0", "status": "SEALED_BEFORE_M3_HYPOTHETICAL_CAPTURE_CALCULATION", "sealed_at_utc": now(), **common})
    print(json.dumps({
        "m2_protocol": record(M2_PROTOCOL), "m3_protocol": record(M3_PROTOCOL),
        "m2_freeze": record(M2_FREEZE), "m3_freeze": record(M3_FREEZE),
        "source_bindings": len(sources), "passing_units": 12, "expected_cases": 10388,
        "market_values_accessed": False, "forward_values_accessed": False, "charge_usd": 0.0,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

