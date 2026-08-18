from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
M1_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_milestone1_seal.json"
M1_PROTOCOL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_protocol.json"
M1_IDENTITIES = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1/session_identity_registry.json"
M1_FAILURE = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1/failure_disposition.json"
M2_CERTIFICATION = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json"
M2_ACQUISITION = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/acquisition_manifest.json"

PROTOCOL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_protocol.json"
SCHEDULE_EVIDENCE = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_schedule_evidence.json"
PROTOCOL_MD = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_MILESTONE_1_R1_PROTOCOL.md"
PREACCESS_FREEZE = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_preaccess_freeze.json"
DIAGNOSTIC_IMPLEMENTATION = ROOT / "tools/diagnose_multi_asset_session_behaviour_archetype_monetization_v1_m1_r1.py"
TEST_IMPLEMENTATION = ROOT / "tests/test_multi_asset_session_behaviour_archetype_monetization_v1_m1_r1.py"
IMPLEMENTATION = Path(__file__).resolve()

TARGET_UNITS = [
    "EURUSD|ASIA_SESSION",
    "USDJPY|ASIA_SESSION",
    "XAGUSD|ASIA_SESSION",
    "US500|LONDON_SESSION",
    "XTIUSD|LONDON_SESSION",
]
CONTROL_UNITS = [
    "EURUSD|LONDON_SESSION",
    "EURUSD|NEW_YORK_SESSION",
    "USDJPY|LONDON_SESSION",
    "USDJPY|NEW_YORK_SESSION",
    "XAGUSD|LONDON_SESSION",
    "XAGUSD|NEW_YORK_SESSION",
    "USTEC|LONDON_SESSION",
    "USTEC|US_CASH_SESSION",
    "US500|US_CASH_SESSION",
    "XTIUSD|US_ENERGY_SESSION",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value.rstrip() + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def verify_artifacts(seal: Mapping[str, Any]) -> None:
    for item in seal["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise ValueError(f"Predecessor seal mismatch: {item['path']}")


def schedule_evidence() -> dict[str, Any]:
    core = {
        "version": "MSBAM_V1_M1_R1_SCHEDULE_EVIDENCE_1_0",
        "frozen_before_timestamp_row_access": True,
        "documents": [
            {
                "id": "METAQUOTES_MQL5_TIMESERIES",
                "authority": "METAQUOTES",
                "url": "https://www.mql5.com/en/book/applications/timeseries",
                "retrieved_on": "2026-08-12",
                "admissible_claim": "MT5 quote bars require at least one tick; a potential M1 interval with no tick does not generate a bar; Forex and CFD bars use Bid prices.",
                "historical_schedule_evidence": False,
                "platform_semantics_evidence": True,
            },
            {
                "id": "IC_CURRENT_TRADING_HOURS",
                "authority": "IC_MARKETS_GLOBAL_RAW_TRADING_LTD",
                "url": "https://www.ic.com/en/trading-pricing/trading-hours",
                "retrieved_on": "2026-08-12",
                "admissible_claim": "Current IC server charts use GMT+2 or GMT+3; currency, metals, energy and index instruments have instrument-specific daily hours and breaks.",
                "provider_caveat": "Hours are subject to change and the platform is the most accurate current source.",
                "historical_schedule_evidence": "CONTEXT_ONLY_UNLESS_THE_FROZEN_RECURRENCE_GATE_CONFIRMS_EACH_DEVELOPMENT_YEAR",
                "platform_semantics_evidence": False,
            },
        ],
        "provider_clock_proxy": {
            "zone": "Europe/Athens",
            "reason": "Operational proxy for documented GMT+2/GMT+3 with European DST.",
            "limitation": "The proxy cannot itself prove historical IC server-transition dates.",
        },
        "current_documented_tradable_minute_ranges_server_time": {
            "EURUSD": [{"start": "00:01", "end_exclusive": "23:59"}],
            "USDJPY": [{"start": "00:01", "end_exclusive": "23:59"}],
            "XAGUSD": [{"start": "01:02", "end_exclusive": "23:59"}],
            "US500": [{"start": "01:00", "end_exclusive": "23:59"}],
            "USTEC": [{"start": "01:00", "end_exclusive": "23:59"}],
            "XTIUSD": [{"start": "01:00", "end_exclusive": "23:59"}],
        },
        "current_documented_closed_minute_ranges_server_time": {
            "EURUSD": [{"start": "23:59", "end_exclusive": "00:01", "crosses_midnight": True}],
            "USDJPY": [{"start": "23:59", "end_exclusive": "00:01", "crosses_midnight": True}],
            "XAGUSD": [{"start": "23:59", "end_exclusive": "01:02", "crosses_midnight": True}],
            "US500": [{"start": "23:59", "end_exclusive": "01:00", "crosses_midnight": True}],
            "USTEC": [{"start": "23:59", "end_exclusive": "01:00", "crosses_midnight": True}],
            "XTIUSD": [{"start": "23:59", "end_exclusive": "01:00", "crosses_midnight": True}],
        },
        "historical_promotion_gate": {
            "all_required": True,
            "requirements": [
                "EVERY_MINUTE_IN_RUN_MATCHES_CURRENT_PROVIDER_DOCUMENTED_CLOSED_RANGE",
                "SAME_PROVIDER_SERVER_CLOCK_RUN_SIGNATURE_PRESENT_ON_AT_LEAST_80_PERCENT_OF_EXPECTED_UNIT_DATES_IN_EACH_DEVELOPMENT_CALENDAR_YEAR",
                "UTC_SHIFT_IS_CONSISTENT_WITH_THE_FROZEN_GMT_PLUS_2_GMT_PLUS_3_PROXY",
                "NO_EXPLICIT_ACQUISITION_OR_LINEAGE_FAILURE_OVERLAPS_THE_RUN",
            ],
            "effect": "ONLY_THEN_MAY_CURRENT_DOCUMENTATION_PLUS_RECURRING_METADATA_SUPPORT_DOCUMENTED_MARKET_UNAVAILABLE_FOR_2021_2024",
        },
        "limitations": [
            "EXCHANGE_HOURS_ALONE_CANNOT_ESTABLISH_IC_CFD_AVAILABILITY",
            "CURRENT_PROVIDER_HOURS_ALONE_CANNOT_REWRITE_HISTORICAL_EXPECTATIONS",
            "ABSENCE_OF_AN_M1_BAR_ALONE_CANNOT_PROVE_A_SOURCE_GAP",
        ],
    }
    return {**core, "evidence_hash": canonical_hash(core)}


def protocol() -> dict[str, Any]:
    core = {
        "version": "MSBAM_V1_M1_R1_PROTOCOL_1_0",
        "status": "FROZEN_BEFORE_TIMESTAMP_LEVEL_METADATA_ACCESS",
        "branch": "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_MONETIZATION_V1",
        "milestone": "1-R1",
        "preserved_verdict": "FAIL_MILESTONE_1_COVERAGE_STOP",
        "target_units": TARGET_UNITS,
        "passing_control_units": CONTROL_UNITS,
        "development_interval": {"start_inclusive": "2021-08-01T00:00:00Z", "end_exclusive": "2025-01-01T00:00:00Z"},
        "identity_policy": "USE_ALL_13380_FROZEN_IDENTITIES_UNCHANGED; DIAGNOSE_ONLY_TARGET_INCOMPLETE_IDENTITIES; CONTROLS_ARE_METADATA_ONLY",
        "permitted_source_fields": ["open_time"],
        "permitted_lineage_fields": ["path", "bytes", "sha256", "request status", "empty chunk status", "source row ordering and duplicate counts"],
        "forbidden_source_fields": ["open", "high", "low", "close", "spread_points", "tick_volume", "real_volume", "volume"],
        "forbidden_calculations": ["direction", "return", "path", "MFE", "MAE", "first passage", "archetype", "relationship", "hypothetical return", "strategy", "entry", "trade", "PnL"],
        "diagnostic_tests_in_order": [
            "T01_VERIFY_ALL_PREDECESSOR_AND_SOURCE_SEALS",
            "T02_VERIFY_FROZEN_IDENTITY_COUNT_KEYS_AND_SESSION_CLOCKS_UNCHANGED",
            "T03_READ_ONLY_OPEN_TIME_AND_CERTIFY_DUPLICATES_ORDER_FIRST_LAST_AND_DEVELOPMENT_FILTER",
            "T04_EXTRACT_EVERY_MAXIMAL_CONSECUTIVE_MISSING_MINUTE_RUN_IN_START_INCLUSIVE_END_EXCLUSIVE",
            "T05_CLASSIFY_RUN_BOUNDARY_POSITION_AND_LENGTH_BIN",
            "T06_MAP_RUNS_TO_FROZEN_SESSION_LOCAL_CLOCK_WEEKDAY_AND_DST_STATE",
            "T07_MAP_RUNS_TO_PROVIDER_SERVER_CLOCK_PROXY_AND_CURRENT_DOCUMENTED_SCHEDULE_SHAPE",
            "T08_MEASURE_EXACT_RUN_SIGNATURE_RECURRENCE_BY_CALENDAR_YEAR_WITH_ALL_FROZEN_UNIT_DATES_AS_DENOMINATOR",
            "T09_MEASURE_CROSS_INSTRUMENT_SAME_UTC_MINUTE_ABSENCE",
            "T10_AUDIT_ACQUISITION_CHUNK_AND_LINEAGE_FAILURE_METADATA",
            "T11_APPLY_CLASSIFICATION_PRECEDENCE_WITHOUT_VALUE_ACCESS",
            "T12_COMPARE_ALL_TEN_PASSING_UNITS_AS_CONTROLS",
            "T13_REQUIRE_PRIMARY_REFERENCE_EXACT_RECORD_SUMMARY_CLASSIFICATION_AND_CHECKSUM_PARITY",
        ],
        "run_fields": [
            "run_id", "case_id", "instrument", "session_code", "session_date_local", "weekday",
            "session_dst_state", "start_utc", "end_exclusive_utc", "length_minutes", "length_bin",
            "boundary_position", "session_start_offset_minutes", "provider_server_start_local",
            "provider_server_end_exclusive_local", "provider_server_dst_state", "current_schedule_shape",
            "preceding_minute_present", "following_minute_present", "cross_instrument_missing_minimum",
            "cross_instrument_missing_maximum", "exact_signature_total_count", "exact_signature_year_counts",
            "exact_signature_year_denominators", "classification", "evidence_grade", "evidence_codes",
        ],
        "classification_precedence": [
            "DOCUMENTED_MARKET_UNAVAILABLE",
            "RECOVERABLE_EXISTING_SEALED_SOURCE",
            "GENUINE_SOURCE_GAP",
            "NORMAL_NO_TICK_BAR_EMISSION",
            "UNRESOLVED",
        ],
        "classification_rules": {
            "DOCUMENTED_MARKET_UNAVAILABLE": {
                "all_required": True,
                "criteria": [
                    "RUN_ENTIRELY_MATCHES_CURRENT_PROVIDER_DOCUMENTED_CLOSED_MINUTES",
                    "EXACT_PROVIDER_SERVER_CLOCK_SIGNATURE_RECURRENCE_GTE_0P80_IN_EACH_DEVELOPMENT_YEAR",
                    "DST_PROXY_CONSISTENCY_PASSES",
                    "NO_EXPLICIT_ACQUISITION_OR_LINEAGE_FAILURE",
                ],
            },
            "RECOVERABLE_EXISTING_SEALED_SOURCE": {
                "all_required": True,
                "criteria": [
                    "TIMESTAMP_ABSENT_FROM_CERTIFIED_CANONICAL_UNION",
                    "SAME_TIMESTAMP_PRESENT_IN_A_PREACCESS_FROZEN_SEALED_SAME_SYMBOL_M1_RECOVERY_SOURCE",
                ],
                "recovery_universe": "NO_ADDITIONAL_COMPATIBLE_SOURCE_WAS_BOUND_BEFORE_ACCESS; EXPECTED_COUNT_ZERO",
            },
            "GENUINE_SOURCE_GAP": {
                "all_required": True,
                "criteria": [
                    "EXPLICIT_PROVIDER_REQUEST_FAILURE_EMPTY_CHUNK_OR_TRUNCATION_OVERLAPS_RUN",
                    "RUN_NOT_DOCUMENTED_CLOSED",
                ],
            },
            "NORMAL_NO_TICK_BAR_EMISSION": {
                "all_required": True,
                "criteria": [
                    "RUN_LENGTH_LTE_2_MINUTES",
                    "RUN_IS_INTERIOR_AND_BOTH_ADJACENT_MINUTES_EXIST",
                    "RUN_IS_IN_CURRENT_DOCUMENTED_TRADING_TIME",
                    "EXACT_RUN_SIGNATURE_RECURRENCE_LT_0P10_OVERALL",
                    "CROSS_INSTRUMENT_MISSING_MAXIMUM_LT_4",
                    "NO_EXPLICIT_ACQUISITION_OR_LINEAGE_FAILURE",
                    "METAQUOTES_TICK_DEPENDENT_BAR_SEMANTICS_IS_ADMISSIBLE",
                ],
                "semantic_limit": "TECHNICAL_DISPOSITION_CONSISTENT_WITH_NO_TICK_BAR_FORMATION; NOT_PROOF_ABOUT_UNSEEN_TICKS",
            },
            "UNRESOLVED": {"criteria": ["NO_PRIOR_CLASSIFICATION_RULE_PASSES"]},
        },
        "length_bins": {"1": [1, 1], "2": [2, 2], "3_5": [3, 5], "6_15": [6, 15], "16_60": [16, 60], "61_PLUS": [61, None]},
        "recurrence": {
            "signature": ["instrument", "session_code", "provider_server_start_HHMM", "provider_server_end_exclusive_HHMM", "length_minutes", "boundary_position"],
            "year_denominator": "ALL_FROZEN_WEEKDAY_IDENTITIES_FOR_THE_SAME_INSTRUMENT_SESSION_AND_CALENDAR_YEAR",
        },
        "cross_instrument_test": "FOR_EACH_MISSING_MINUTE_COUNT_ABSENCE_ACROSS_ALL_SIX_CERTIFIED_INSTRUMENT_TIMESTAMP_UNIONS",
        "recommendation_limit": {
            "maximum": 1,
            "implementation_authorized": False,
            "must_preserve": ["all identities", "session definitions", "90 percent unit readiness floor", "UNKNOWN semantics", "no imputation", "outcome locks"],
            "must_be_outcome_blind": True,
        },
        "independent_reproduction": {
            "primary": "PANDAS_OPEN_TIME_CHUNK_READER_AND_FORWARD_IDENTITY_SCAN",
            "reference": "PYTHON_CSV_OPEN_TIME_READER_AND_REVERSE_IDENTITY_SCAN",
            "exact_required": ["timestamp inventories", "run records", "classifications", "unit summaries", "recurrence tables", "complete semantic checksum"],
        },
        "pass_rule": "PASS_DIAGNOSTIC_REPRODUCTION_ONLY_IF_ALL_SEALS_PASS_AND_PRIMARY_REFERENCE_OUTPUTS_MATCH_EXACTLY; THIS_DOES_NOT_REVERSE_M1_RESEARCH_READINESS_FAILURE",
        "stop_rule": "DOCUMENT_AND_SEAL_R1; DO_NOT_IMPLEMENT_RECOMMENDATION_OR_BEGIN_M2",
        "controls": {"acquire_data": False, "charge_usd": 0.0, "open_2025": False, "open_2026": False, "outcomes": False},
    }
    return {**core, "protocol_hash": canonical_hash(core)}


def protocol_markdown(proto: Mapping[str, Any], evidence: Mapping[str, Any]) -> str:
    targets = "\n".join(f"- `{value}`" for value in proto["target_units"])
    controls = "\n".join(f"- `{value}`" for value in proto["passing_control_units"])
    tests = "\n".join(f"{index}. `{value}`" for index, value in enumerate(proto["diagnostic_tests_in_order"], 1))
    return f"""# Multi-Asset Session Behaviour V1 — Milestone 1-R1 Protocol

Status: **frozen before timestamp-level metadata access**

The Milestone 1 verdict `FAIL_MILESTONE_1_COVERAGE_STOP` remains unchanged. This protocol diagnoses only why the universal every-minute rule failed.

## Failed units

{targets}

## Passing metadata controls

{controls}

## Ordered tests

{tests}

## Classification discipline

The frozen precedence is documented closure, recoverable sealed source, explicit source failure, normal no-tick bar emission, then unresolved. A current IC schedule is not sufficient historical proof by itself. It can support `DOCUMENTED_MARKET_UNAVAILABLE` only when the identical provider-clock pattern recurs on at least 80% of frozen dates in **every** development year and all other frozen gates pass.

MetaTrader's official timeseries documentation establishes that an M1 interval without a tick does not produce a bar. `NORMAL_NO_TICK_BAR_EMISSION` is therefore permitted only for an interior one- or two-minute gap with both adjacent minutes present, low exact-clock recurrence, no broad cross-instrument outage, and no lineage failure. It is a technical disposition, not a claim about unseen prices.

Protocol hash: `{proto['protocol_hash']}`  
Schedule-evidence hash: `{evidence['evidence_hash']}`

No market value, outcome, behaviour, edge or PnL may be accessed or calculated. R1 can recommend one bounded correction but cannot implement it.
"""


def main() -> None:
    for path in [PROTOCOL, SCHEDULE_EVIDENCE, PROTOCOL_MD, PREACCESS_FREEZE]:
        if path.exists():
            raise FileExistsError(path)
    for path in [DIAGNOSTIC_IMPLEMENTATION, TEST_IMPLEMENTATION]:
        if not path.is_file():
            raise FileNotFoundError(path)

    seal = load(M1_SEAL)
    verify_artifacts(seal)
    failure = load(M1_FAILURE)
    identities = load(M1_IDENTITIES)
    if seal["verdict"] != "FAIL_MILESTONE_1_COVERAGE_STOP" or failure["verdict"] != seal["verdict"]:
        raise ValueError("Milestone 1 failure was not preserved")
    if len(identities["rows"]) != 13_380 or any(row["coverage_or_outcome_attached"] for row in identities["rows"]):
        raise ValueError("Frozen identity registry changed")

    evidence = schedule_evidence()
    proto = protocol()
    write_json_exclusive(SCHEDULE_EVIDENCE, evidence)
    write_json_exclusive(PROTOCOL, proto)
    write_text_exclusive(PROTOCOL_MD, protocol_markdown(proto, evidence))

    freeze_core = {
        "version": "MSBAM_V1_M1_R1_PREACCESS_FREEZE_1_0",
        "status": "SEALED_BEFORE_TIMESTAMP_LEVEL_METADATA_ACCESS",
        "preserved_verdict": seal["verdict"],
        "predecessor": record(M1_SEAL),
        "predecessor_artifact_set_hash": seal["artifact_set_hash"],
        "source_certification": record(M2_CERTIFICATION),
        "source_acquisition_manifest": record(M2_ACQUISITION),
        "frozen_identity_registry": record(M1_IDENTITIES),
        "m1_protocol": record(M1_PROTOCOL),
        "r1_protocol": record(PROTOCOL),
        "schedule_evidence": record(SCHEDULE_EVIDENCE),
        "protocol_markdown": record(PROTOCOL_MD),
        "preparation_implementation": record(IMPLEMENTATION),
        "diagnostic_implementation": record(DIAGNOSTIC_IMPLEMENTATION),
        "test_implementation": record(TEST_IMPLEMENTATION),
        "target_units": TARGET_UNITS,
        "control_units": CONTROL_UNITS,
        "frozen_recovery_source_inventory": [],
        "controls": {
            "timestamp_rows_accessed_before_freeze": False,
            "market_values_accessed": False,
            "outcomes_accessed": False,
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "paid_acquisition_usd": 0.0,
        },
    }
    freeze = {**freeze_core, "freeze_hash": canonical_hash(freeze_core), "sealed_at_utc": now()}
    write_json_exclusive(PREACCESS_FREEZE, freeze)
    print(json.dumps({
        "status": freeze["status"],
        "protocol_hash": proto["protocol_hash"],
        "schedule_evidence_hash": evidence["evidence_hash"],
        "target_units": len(TARGET_UNITS),
        "control_units": len(CONTROL_UNITS),
        "freeze": record(PREACCESS_FREEZE),
    }, indent=2))


if __name__ == "__main__":
    main()
