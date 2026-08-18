#!/usr/bin/env python3
"""Freeze and run the Step 5A metadata-only GC research cost audit.

The provider path in this utility is deliberately limited to Databento
symbology and metadata endpoints.  It contains no batch submission,
time-series retrieval, DBN decoding, or download path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time as sleep_time
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "research_manifests" / "gc_microstructure_conditional_edge_discovery_contract_v01.json"
FEATURE_REGISTRY = ROOT / "research_manifests" / "gc_microstructure_step_5a_feature_hypothesis_registry_v01.json"
REQUEST_REGISTRY = ROOT / "research_manifests" / "gc_microstructure_step_5a_request_registry_v01.json"
FREEZE = ROOT / "research_manifests" / "gc_microstructure_step_5a_freeze_v01.json"
STEP4A = ROOT / "research_manifests" / "gc_microstructure_step_4a_protocol_v01.json"
STEP4B3 = ROOT / "research_artifacts" / "gc_microstructure_step_4b3_v01" / "manifest.json"
V3_CONTRACT = ROOT / "research_manifests" / "gold_session_behaviour_discovery_contract_v03.json"
V3_TRACE = ROOT / "research_manifests" / "gold_session_behaviour_v3_traceability_v01.json"
V3_CASES = ROOT / "research_artifacts" / "gold_session_behaviour_v3_case_matrix_v01" / "manifest.json"
V3_M4 = ROOT / "research_manifests" / "gold_session_behaviour_v3_m4_discovery_v01.json"
V3_COVERAGE = ROOT / "research_artifacts" / "gold_session_behaviour_v3_coverage_v01.json"
BOOK = ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf"
DEFAULT_OUTPUT = ROOT / "research_artifacts" / "gc_microstructure_step_5a_v01"
REPORT = ROOT / "GC_MICROSTRUCTURE_STEP_5A_REPORT.md"
CONTRACT_DOC = ROOT / "GC_MICROSTRUCTURE_CONDITIONAL_EDGE_DISCOVERY_CONTRACT_V1.md"

DATASET = "GLBX.MDP3"
SYMBOL = "GC.v.0"
STYPE_IN = "continuous"
SCHEMAS = ("mbo", "mbp-10")
ENGINEERING_DATES = (
    "2024-01-05",
    "2024-01-09",
    "2024-01-11",
    "2024-01-30",
    "2024-01-31",
    "2024-03-20",
)
EXPECTED_FILES = {
    BOOK: "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a",
    STEP4A: "8f1ba7230919b7422344253d4f3e55fea1e86495551cbbbf53f3e1bdcb9ec3a2",
    STEP4B3: "54ba09d63c6c791bfdcd2047112b15a431c686a12f6e1f7a82beae9e5a3e6249",
    V3_CONTRACT: "993e91610992c62fd97c3c9aeb81b8a46ed422f025fac441b629ce35985ca591",
    V3_TRACE: "9690360ed1c9eceac1b26428460e54ec4326b7ffb0ef94c73dd1574589a2bd92",
    V3_CASES: "dddbe125d11afef2094b7843f5521b7bbfcc95178e3fa376b60af8bdd2efc3b5",
    V3_M4: "e11b86385c1d7594a48ef1d11fc04b65ac979c952251078528ed727f0fd91127",
}
EXPECTED_INTERNAL = {
    "step4b3_manifest_hash": "6252b239c4962fd8dcf3bce1a712b416e67af8303bbea7cd40de2ab6a3522bbe",
    "step4b3_status": "PASS_MULTIDAY_FEATURE_ROBUSTNESS",
    "v3_contract_hash": "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b",
    "v3_trace_hash": "8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4",
    "v3_cases_hash": "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7",
    "feature_schema_hash": "dfaf74cdc55b37469966857fc1ed2279b3d18c98f90454ced65859cb32494232",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "preflight", "primary", "reference", "seal", "verify"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    args = parser.parse_args()
    run(args.action, Path(args.output), Path(args.env_file))


def run(action: str, output: Path, env_file: Path) -> None:
    if action == "prepare":
        _prepare()
        return
    context = _frozen_context()
    output.mkdir(parents=True, exist_ok=True)
    if action == "preflight":
        _preflight(output, context)
    elif action in {"primary", "reference"}:
        _quote(output, env_file, action, context)
    elif action == "seal":
        _seal(output, context)
    elif action == "verify":
        _verify(output)
    else:
        raise AssertionError(action)


def _prepare() -> None:
    context = _design_context()
    if REQUEST_REGISTRY.exists() or FREEZE.exists():
        raise FileExistsError("Refusing to overwrite an existing Step 5A request registry or freeze receipt")
    registry = _build_request_registry()
    _write_json(REQUEST_REGISTRY, registry)
    freeze = {
        "version": "GC_MICROSTRUCTURE_STEP_5A_FREEZE_V0_1",
        "status": "FROZEN_BEFORE_PROVIDER_METADATA_CALLS_OR_RESEARCH_VALUE_ACCESS",
        "frozen_at_utc": _now(),
        "classification": "RESEARCH_DESIGN_AND_METADATA_ONLY_COST_AUDIT",
        "records": {
            "contract": _record(CONTRACT),
            "feature_hypothesis_registry": _record(FEATURE_REGISTRY),
            "request_registry": _record(REQUEST_REGISTRY),
            "quote_tool": _record(Path(__file__)),
        },
        "predecessor_checks": context["checks"],
        "sample_counts": registry["sample_counts"],
        "provider_request_count": registry["provider_quote_request_count"],
        "daily_coverage_check_count": registry["daily_coverage_check_count"],
        "engineering_dates_permanently_excluded": list(ENGINEERING_DATES),
        "market_values_or_outcomes_accessed": False,
        "provider_metadata_called": False,
        "data_acquired": False,
        "charge_incurred": False,
        "research_relationships_calculated": False,
        "trade_or_execution_calculations_performed": False,
    }
    freeze["freeze_hash"] = _canonical_hash(freeze)
    _write_json(FREEZE, freeze)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_5A_DESIGN_FROZEN",
        "freeze_hash": freeze["freeze_hash"],
        "selected_dates": registry["sample_counts"]["post_exclusion_dates"],
        "selected_weeks": registry["sample_counts"]["selected_monthly_weeks"],
        "request_intervals": registry["sample_counts"]["request_intervals"],
        "provider_quote_requests": registry["provider_quote_request_count"],
        "data_acquired": False,
        "charge_incurred": False,
    }, sort_keys=True))


def _build_request_registry() -> dict[str, Any]:
    excluded = {date.fromisoformat(item) for item in ENGINEERING_DATES}
    selected_rows: list[dict[str, Any]] = []
    weeks: list[dict[str, Any]] = []
    cursor = date(2021, 8, 1)
    end_month = date(2024, 12, 1)
    pre_exclusion = 0
    intersecting: list[str] = []
    while cursor <= end_month:
        next_month = _next_month(cursor)
        mondays: list[date] = []
        day = cursor
        while day < next_month:
            if day.weekday() == 0 and (day + timedelta(days=4)).month == cursor.month:
                mondays.append(day)
            day += timedelta(days=1)
        if len(mondays) < 2:
            raise ValueError(f"No second complete Monday-Friday block in {cursor:%Y-%m}")
        monday = mondays[1]
        week_id = f"{cursor:%Y-%m}:SECOND_COMPLETE_CME_WEEK"
        raw_dates = [monday + timedelta(days=offset) for offset in range(5)]
        pre_exclusion += len(raw_dates)
        retained: list[date] = []
        removed: list[str] = []
        for selected in raw_dates:
            if selected in excluded:
                removed.append(selected.isoformat())
                intersecting.append(selected.isoformat())
                continue
            retained.append(selected)
            london = _cutoff(selected, "Europe/London")
            new_york = _cutoff(selected, "America/New_York")
            selected_rows.append({
                "trade_date": selected.isoformat(),
                "selected_month_week_id": week_id,
                "weekday": selected.strftime("%A").upper(),
                "london_decision_at_utc": _iso(london),
                "london_utc_offset": _offset_text(london.astimezone(ZoneInfo("Europe/London"))),
                "new_york_decision_at_utc": _iso(new_york),
                "new_york_utc_offset": _offset_text(new_york.astimezone(ZoneInfo("America/New_York"))),
                "permanently_engineering_only": False,
            })
        weeks.append({
            "selected_month": f"{cursor:%Y-%m}",
            "selected_month_week_id": week_id,
            "monday": monday.isoformat(),
            "friday": (monday + timedelta(days=4)).isoformat(),
            "pre_exclusion_dates": [item.isoformat() for item in raw_dates],
            "removed_engineering_dates": removed,
            "retained_dates": [item.isoformat() for item in retained],
        })
        cursor = next_month

    intervals: list[dict[str, Any]] = []
    for week in weeks:
        dates = [date.fromisoformat(item) for item in week["retained_dates"]]
        for run_index, run_dates in enumerate(_consecutive_runs(dates), start=1):
            start = run_dates[0]
            end = run_dates[-1] + timedelta(days=1)
            intervals.append({
                "interval_id": f"{week['selected_month_week_id']}:RUN_{run_index:02d}",
                "selected_month_week_id": week["selected_month_week_id"],
                "start": f"{start.isoformat()}T00:00:00Z",
                "end": f"{end.isoformat()}T00:00:00Z",
                "selected_dates": [item.isoformat() for item in run_dates],
            })

    requests: list[dict[str, Any]] = []
    for interval in intervals:
        for schema in SCHEMAS:
            requests.append({
                "request_id": f"Q{len(requests) + 1:03d}:{schema}",
                "interval_id": interval["interval_id"],
                "selected_month_week_id": interval["selected_month_week_id"],
                "schema": schema,
                "request": {
                    "dataset": DATASET,
                    "symbols": [SYMBOL],
                    "schema": schema,
                    "stype_in": STYPE_IN,
                    "start": interval["start"],
                    "end": interval["end"],
                },
            })
    daily_checks = [
        {
            "coverage_id": f"{row['trade_date']}:{schema}",
            "trade_date": row["trade_date"],
            "schema": schema,
            "start": f"{row['trade_date']}T00:00:00Z",
            "end": f"{(date.fromisoformat(row['trade_date']) + timedelta(days=1)).isoformat()}T00:00:00Z",
        }
        for row in selected_rows
        for schema in SCHEMAS
    ]
    if len(weeks) != 41 or pre_exclusion != 205 or len(selected_rows) != 203:
        raise ValueError("Frozen sample count mismatch")
    if sorted(intersecting) != ["2024-01-09", "2024-01-11"]:
        raise ValueError("Engineering exclusion intersection mismatch")
    if len(intervals) != 43 or len(requests) != 86 or len(daily_checks) != 406:
        raise ValueError("Frozen request count mismatch")
    if selected_rows[0]["trade_date"] != "2021-08-09" or selected_rows[-1]["trade_date"] != "2024-12-13":
        raise ValueError("Frozen sample endpoints mismatch")
    payload = {
        "version": "GC_MICROSTRUCTURE_STEP_5A_REQUEST_REGISTRY_V0_1",
        "status": "FROZEN_OUTCOME_BLIND_BEFORE_PROVIDER_METADATA_CALLS",
        "classification": "CALENDAR_AND_INSTRUMENT_METADATA_ONLY",
        "selection_algorithm": _read_json(CONTRACT)["outcome_blind_development_sample"],
        "permanent_engineering_exclusions": list(ENGINEERING_DATES),
        "sample_counts": {
            "selected_monthly_weeks": len(weeks),
            "pre_exclusion_dates": pre_exclusion,
            "intersecting_engineering_exclusions": len(intersecting),
            "post_exclusion_dates": len(selected_rows),
            "request_intervals": len(intervals),
        },
        "weeks": weeks,
        "selected_dates": selected_rows,
        "request_intervals": intervals,
        "provider_quote_requests": requests,
        "provider_quote_request_count": len(requests),
        "daily_coverage_checks": daily_checks,
        "daily_coverage_check_count": len(daily_checks),
        "symbology_request": {
            "dataset": DATASET,
            "symbols": [SYMBOL],
            "stype_in": STYPE_IN,
            "stype_out": "instrument_id",
            "start_date": "2021-08-01",
            "end_date": "2025-01-01",
        },
        "market_values_or_outcomes_used_to_select_dates": False,
        "data_acquisition_authorized": False,
        "charge_authorized": False,
    }
    payload["registry_hash"] = _canonical_hash(payload)
    return payload


def _preflight(output: Path, context: dict[str, Any]) -> None:
    path = output / "preflight.json"
    if path.exists():
        raise FileExistsError("Refusing to overwrite Step 5A preflight")
    trace = _read_json(V3_TRACE)
    coverage_counts = dict(sorted(Counter(item["development_coverage"] for item in trace["field_requirements"]).items()))
    cases = _read_json(V3_CASES)
    prior_coverage = _read_json(V3_COVERAGE)
    result = {
        "version": "GC_MICROSTRUCTURE_STEP_5A_PREFLIGHT_V0_1",
        "created_at_utc": _now(),
        "classification": "METADATA_ONLY_NO_RESEARCH_VALUES",
        "freeze_hash": context["freeze"]["freeze_hash"],
        "checks": {
            **context["checks"],
            "v3_case_manifest_reports_1659_sealed_cases": cases["case_counts"]["total"] == 1659,
            "traceability_has_75_book_requirements": len(trace["field_requirements"]) == 75,
            "request_registry_has_203_dates": context["requests"]["sample_counts"]["post_exclusion_dates"] == 203,
            "request_registry_has_86_provider_quotes": context["requests"]["provider_quote_request_count"] == 86,
            "request_registry_has_406_daily_coverage_checks": context["requests"]["daily_coverage_check_count"] == 406,
            "2025_values_remain_unopened_by_step_5a": True,
            "2026_values_remain_locked": True,
        },
        "existing_source_metadata": {
            "v3_case_counts": cases["case_counts"],
            "v3_development_partition": cases["development_partition"],
            "book_traceability_coverage_counts": coverage_counts,
            "source_family_status": prior_coverage["source_family_status"],
            "material_gaps": prior_coverage["material_gaps"],
            "selected_date_row_level_case_coverage_certified_in_step_5a": False,
            "reason": "Step 5A may read sealed manifests but not deserialize development case values. Exact joins remain a later value-blind construction audit.",
        },
        "microstructure_source_status_before_quote": "NOT_ACQUIRED_METADATA_QUOTE_REQUIRED",
        "formal_preflight_pass": all(context["checks"].values()),
        "case_values_deserialized": False,
        "market_values_or_outcomes_accessed": False,
        "data_acquired": False,
        "charge_incurred": False,
    }
    _write_json(path, result)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_5A_PREFLIGHT_COMPLETE",
        "formal_preflight_pass": result["formal_preflight_pass"],
        "selected_dates": context["requests"]["sample_counts"]["post_exclusion_dates"],
        "case_values_deserialized": False,
        "market_values_or_outcomes_accessed": False,
    }, sort_keys=True))


def _quote(output: Path, env_file: Path, implementation: str, context: dict[str, Any]) -> None:
    path = output / f"{implementation}_quote.json"
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite Step 5A {implementation} quote")
    if not (output / "preflight.json").exists():
        raise FileNotFoundError("Run Step 5A preflight before provider metadata calls")
    client, sdk_version = _client(_api_key(env_file))
    instrument = _instrument_metadata(client, context["requests"])
    estimates = _interval_estimates(client, context["requests"], implementation)
    daily = _daily_coverage(client, context["requests"], implementation)
    checks = {
        "frozen_context_valid": all(context["checks"].values()),
        "symbology_response_complete": instrument["response_complete"],
        "every_selected_date_maps_to_one_instrument": instrument["all_selected_dates_map_exactly_once"],
        "all_86_quote_requests_returned": estimates["request_count"] == 86,
        "all_quote_costs_finite_nonnegative": all(math.isfinite(item["cost_usd"]) and item["cost_usd"] >= 0 for item in estimates["quotes"]),
        "all_quote_record_counts_positive": all(item["record_count"] > 0 for item in estimates["quotes"]),
        "all_quote_billable_sizes_positive": all(item["billable_size"] > 0 for item in estimates["quotes"]),
        "all_406_daily_checks_returned": daily["check_count"] == 406,
        "both_schemas_positive_for_every_selected_date": daily["fully_covered_date_count"] == 203 and not daily["uncovered_dates"],
        "metadata_endpoints_only": True,
        "no_job_download_charge_or_value_access": True,
    }
    result = {
        "version": "GC_MICROSTRUCTURE_STEP_5A_METADATA_QUOTE_V0_1",
        "implementation": implementation,
        "queried_at_utc": _now(),
        "classification": "METADATA_ONLY_COST_AND_COVERAGE_AUDIT",
        "provider": "Databento",
        "sdk_version": sdk_version,
        "freeze_hash": context["freeze"]["freeze_hash"],
        "tool_sha256": _sha(Path(__file__)),
        "instrument_metadata": instrument,
        "estimates": estimates,
        "daily_coverage": daily,
        "readiness_checks": checks,
        "formal_metadata_readiness_pass": all(checks.values()),
        "api_methods_called": ["symbology.resolve", "metadata.get_cost", "metadata.get_record_count", "metadata.get_billable_size"],
        "batch_api_called": False,
        "timeseries_api_called": False,
        "data_downloaded": False,
        "charge_incurred": False,
        "market_values_or_outcomes_accessed": False,
        "relationships_or_signals_calculated": False,
        "execution_or_pnl_calculated": False,
    }
    _write_json(path, result)
    print(json.dumps({
        "stage": f"GC_MICROSTRUCTURE_STEP_5A_{implementation.upper()}_QUOTE_COMPLETE",
        "formal_metadata_readiness_pass": result["formal_metadata_readiness_pass"],
        "request_count": estimates["request_count"],
        "selected_dates_with_both_schemas": daily["fully_covered_date_count"],
        "mbo_cost_usd": estimates["schema_totals"]["mbo"]["cost_usd"],
        "mbp10_cost_usd": estimates["schema_totals"]["mbp-10"]["cost_usd"],
        "combined_cost_usd": estimates["combined_totals"]["cost_usd"],
        "data_downloaded": False,
        "charge_incurred": False,
    }, sort_keys=True))


def _instrument_metadata(client: Any, registry: dict[str, Any]) -> dict[str, Any]:
    request = registry["symbology_request"]
    response = _json_safe(_retry("symbology.resolve", lambda: client.symbology.resolve(**request)))
    items = response.get("result", {}).get(SYMBOL, [])
    intervals = sorted(
        ({"start_date_inclusive": str(item["d0"]), "end_date_exclusive": str(item["d1"]), "instrument_id": int(item["s"])} for item in items),
        key=lambda item: (item["start_date_inclusive"], item["end_date_exclusive"], item["instrument_id"]),
    )
    mappings: list[dict[str, Any]] = []
    invalid: list[str] = []
    for row in registry["selected_dates"]:
        day = row["trade_date"]
        matches = [item for item in intervals if item["start_date_inclusive"] <= day < item["end_date_exclusive"]]
        if len(matches) != 1:
            invalid.append(day)
            instrument_id = None
        else:
            instrument_id = matches[0]["instrument_id"]
        mappings.append({"trade_date": day, "instrument_id": instrument_id, "match_count": len(matches)})
    return {
        "request": request,
        "response_status": int(response.get("status", -1)),
        "partial": sorted(response.get("partial") or []),
        "not_found": sorted(response.get("not_found") or []),
        "mapping_intervals": intervals,
        "selected_date_mappings": mappings,
        "selected_date_mapping_hash": _canonical_hash(mappings),
        "response_complete": response.get("status") == 0 and not response.get("partial") and not response.get("not_found") and bool(intervals),
        "all_selected_dates_map_exactly_once": not invalid and len(mappings) == 203,
        "invalid_selected_dates": invalid,
        "market_values_returned_or_used": False,
    }


def _interval_estimates(client: Any, registry: dict[str, Any], implementation: str) -> dict[str, Any]:
    quotes: list[dict[str, Any]] = []
    for index, frozen in enumerate(registry["provider_quote_requests"], start=1):
        request = frozen["request"]
        cost = float(_retry("metadata.get_cost", lambda request=request: client.metadata.get_cost(**request)))
        records = int(_retry("metadata.get_record_count", lambda request=request: client.metadata.get_record_count(**request)))
        billable = int(_retry("metadata.get_billable_size", lambda request=request: client.metadata.get_billable_size(**request)))
        quotes.append({
            "request_id": frozen["request_id"],
            "interval_id": frozen["interval_id"],
            "selected_month_week_id": frozen["selected_month_week_id"],
            "schema": frozen["schema"],
            "request": request,
            "cost_usd": cost,
            "record_count": records,
            "billable_size": billable,
        })
        if index % 10 == 0 or index == len(registry["provider_quote_requests"]):
            print(json.dumps({"stage": "STEP_5A_INTERVAL_METADATA_PROGRESS", "implementation": implementation, "completed": index, "total": 86}), flush=True)
    schema_totals = {schema: _totals([item for item in quotes if item["schema"] == schema]) for schema in SCHEMAS}
    return {
        "request_count": len(quotes),
        "quotes": quotes,
        "schema_totals": schema_totals,
        "combined_totals": _totals(quotes),
        "estimate_is_not_purchase_authorization": True,
    }


def _daily_coverage(client: Any, registry: dict[str, Any], implementation: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for index, frozen in enumerate(registry["daily_coverage_checks"], start=1):
        request = {
            "dataset": DATASET,
            "symbols": [SYMBOL],
            "schema": frozen["schema"],
            "stype_in": STYPE_IN,
            "start": frozen["start"],
            "end": frozen["end"],
        }
        records = int(_retry("metadata.get_record_count", lambda request=request: client.metadata.get_record_count(**request)))
        checks.append({
            "coverage_id": frozen["coverage_id"],
            "trade_date": frozen["trade_date"],
            "schema": frozen["schema"],
            "record_count": records,
            "positive": records > 0,
        })
        if index % 50 == 0 or index == len(registry["daily_coverage_checks"]):
            print(json.dumps({"stage": "STEP_5A_DAILY_COVERAGE_PROGRESS", "implementation": implementation, "completed": index, "total": 406}), flush=True)
    by_date: dict[str, dict[str, int]] = {}
    for item in checks:
        by_date.setdefault(item["trade_date"], {})[item["schema"]] = item["record_count"]
    uncovered = [day for day, values in sorted(by_date.items()) if set(values) != set(SCHEMAS) or any(values[schema] <= 0 for schema in SCHEMAS)]
    schema_totals = {schema: sum(item["record_count"] for item in checks if item["schema"] == schema) for schema in SCHEMAS}
    return {
        "check_count": len(checks),
        "checks": checks,
        "schema_record_count_totals": schema_totals,
        "fully_covered_date_count": len(by_date) - len(uncovered),
        "uncovered_dates": uncovered,
        "daily_counts_certify_prediction_window_completeness": False,
        "reason": "Positive full-UTC-day counts do not prove both frozen 15-minute prediction windows are complete.",
    }


def _seal(output: Path, context: dict[str, Any]) -> None:
    preflight = _read_json(output / "preflight.json")
    primary = _read_json(output / "primary_quote.json")
    reference = _read_json(output / "reference_quote.json")
    current_tool = _sha(Path(__file__))
    for item in (primary, reference):
        if item["freeze_hash"] != context["freeze"]["freeze_hash"] or item["tool_sha256"] != current_tool:
            raise ValueError("Quote run no longer matches the frozen Step 5A context/tool")
        if item["batch_api_called"] or item["timeseries_api_called"] or item["data_downloaded"] or item["charge_incurred"]:
            raise ValueError("Metadata-only boundary was exceeded")
    compared = ("instrument_metadata", "estimates", "daily_coverage", "readiness_checks", "formal_metadata_readiness_pass", "api_methods_called")
    matching = {key: primary[key] == reference[key] for key in compared}
    reproduction = all(matching.values())
    if not preflight["formal_preflight_pass"]:
        status = "FAIL_STEP_5A_PREDECESSOR_OR_DESIGN_INTEGRITY"
    elif not reproduction:
        status = "FAIL_STEP_5A_METADATA_REPRODUCTION"
    elif not primary["formal_metadata_readiness_pass"] or not reference["formal_metadata_readiness_pass"]:
        status = "FAIL_STEP_5A_SOURCE_COVERAGE_READINESS"
    else:
        status = "PASS_STEP_5A_METADATA_READINESS"
    coverage = {
        "version": "GC_MICROSTRUCTURE_STEP_5A_SOURCE_COVERAGE_AUDIT_V0_1",
        "status": status,
        "classification": "METADATA_ONLY",
        "development_sample": context["requests"]["sample_counts"],
        "existing_casebook": preflight["existing_source_metadata"],
        "gc_microstructure": {
            "provider": "Databento",
            "dataset": DATASET,
            "symbol": SYMBOL,
            "schemas": list(SCHEMAS),
            "selected_dates": 203,
            "selected_dates_with_positive_daily_counts_both_schemas": primary["daily_coverage"]["fully_covered_date_count"],
            "uncovered_dates": primary["daily_coverage"]["uncovered_dates"],
            "front_instrument_mapping_complete": primary["instrument_metadata"]["all_selected_dates_map_exactly_once"],
            "prediction_window_completeness_certified": False,
            "prediction_window_status": "CONDITIONAL_UNTIL_SEPARATELY_AUTHORIZED_ACQUISITION_AND_VALUE_BLIND_INTEGRITY_AUDIT",
        },
        "field_family_readiness": [
            {"family": "85_SEALED_GC_MICROSTRUCTURE_COLUMNS", "status": "PROVIDER_METADATA_COVERED_NOT_ACQUIRED" if status == "PASS_STEP_5A_METADATA_READINESS" else "METADATA_COVERAGE_FAIL"},
            {"family": "XAUUSD_NEUTRAL_SESSION_OUTCOMES", "status": "SEALED_DEVELOPMENT_CASEBOOK_PRESENT_EXACT_SELECTED_DATE_JOIN_NOT_OPENED"},
            {"family": "FUNDAMENTAL_AND_CROSS_MARKET_CONTEXT", "status": "PRESENT_OR_PARTIAL_PER_V3_TRACEABILITY_UNKNOWN_POLICY_RETAINED"},
            {"family": "COT_CONTEXT", "status": "PRESENT_WEEKLY_PUBLICATION_METADATA_AVAILABILITY_LIMITS_RETAINED"},
            {"family": "HISTORICAL_PRE_EVENT_CONSENSUS", "status": "PARTIAL_UNVERIFIED_ROWS_MUST_REMAIN_UNKNOWN"},
            {"family": "ETF_CENTRAL_BANK_OPTIONS_NEWS", "status": "UNAVAILABLE_AND_NOT_ELIGIBLE_IN_V1"},
        ],
        "readiness_verdict": "READY_FOR_SEPARATE_CAPPED_ACQUISITION_PROTOCOL" if status == "PASS_STEP_5A_METADATA_READINESS" else "NOT_READY",
        "data_acquired": False,
        "charge_incurred": False,
        "market_values_or_outcomes_accessed": False,
    }
    coverage["coverage_hash"] = _canonical_hash(coverage)
    coverage_path = output / "source_coverage_audit.json"
    _write_json(coverage_path, coverage)
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5A_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS_STEP_5A_METADATA_READINESS",
        "classification": "RESEARCH_DESIGN_AND_METADATA_ONLY_COST_AUDIT",
        "freeze_hash": context["freeze"]["freeze_hash"],
        "contract_frozen": True,
        "feature_hypothesis_registry_frozen": True,
        "sample_request_registry_frozen": True,
        "support_and_multiplicity_gates_frozen": True,
        "selected_monthly_weeks": 41,
        "selected_dates": 203,
        "permanent_engineering_exclusions": list(ENGINEERING_DATES),
        "provider_quote_requests": primary["estimates"]["request_count"],
        "estimates": primary["estimates"],
        "daily_coverage_summary": {key: value for key, value in primary["daily_coverage"].items() if key != "checks"},
        "reproduction": {"pass": reproduction, "matching_sections": matching},
        "source_coverage_hash": coverage["coverage_hash"],
        "readiness_limit": "Daily metadata counts do not certify cutoff-window completeness; acquisition and a value-blind integrity audit require separate authorization.",
        "2025_values_or_outcomes_accessed": False,
        "2026_values_or_outcomes_accessed": False,
        "development_values_or_outcomes_accessed_in_step_5a": False,
        "data_acquired": False,
        "charge_incurred": False,
        "relationships_signals_trades_execution_or_pnl_calculated": False,
        "mandatory_stop": True,
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    verdict_path = output / "verdict.json"
    _write_json(verdict_path, verdict)
    _write_text(REPORT, _report(verdict, coverage))
    _write_text(CONTRACT_DOC, _contract_doc(context, verdict))
    artifacts = [
        output / "preflight.json",
        output / "primary_quote.json",
        output / "reference_quote.json",
        coverage_path,
        verdict_path,
        REPORT,
        CONTRACT_DOC,
    ]
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5A_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": _now(),
        "classification": "RESEARCH_DESIGN_AND_METADATA_ONLY_COST_AUDIT",
        "records": {
            "contract": _record(CONTRACT),
            "feature_hypothesis_registry": _record(FEATURE_REGISTRY),
            "request_registry": _record(REQUEST_REGISTRY),
            "freeze_receipt": _record(FREEZE),
            "quote_tool": _record(Path(__file__)),
        },
        "artifacts": [_record(path) for path in artifacts],
        "verdict_hash": verdict["verdict_hash"],
        "source_coverage_hash": coverage["coverage_hash"],
        "all_prior_verdicts_preserved": True,
        "engineering_dates_research_credit": "ZERO_PERMANENTLY",
        "data_acquired": False,
        "charge_incurred": False,
        "market_values_or_outcomes_accessed": False,
        "relationships_or_candidates_calculated": False,
        "trades_execution_or_pnl_calculated": False,
        "mandatory_stop": True,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json(output / "manifest.json", manifest)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_5A_SEALED",
        "status": status,
        "formal_pass": verdict["formal_pass"],
        "combined_estimated_cost_usd": verdict["estimates"]["combined_totals"]["cost_usd"],
        "fully_covered_dates_metadata_only": verdict["daily_coverage_summary"]["fully_covered_date_count"],
        "manifest_hash": manifest["manifest_hash"],
        "data_acquired": False,
        "charge_incurred": False,
    }, sort_keys=True))


def _report(verdict: dict[str, Any], coverage: dict[str, Any]) -> str:
    estimates = verdict["estimates"]
    return "\n".join([
        "# GC Microstructure Step 5A — Design and Metadata Cost Audit",
        "",
        "## Formal verdict",
        "",
        f"`{verdict['status']}`",
        "",
        "## Frozen development sample",
        "",
        f"- Monthly sample weeks: `{verdict['selected_monthly_weeks']}`.",
        f"- Selected session dates after permanent engineering exclusions: `{verdict['selected_dates']}`.",
        "- Rule: second complete Monday–Friday CME trade-date block wholly inside each calendar month, August 2021 through December 2024.",
        "- Engineering dates remain permanently excluded with zero research and validation credit.",
        "",
        "## Metadata-only Databento estimate",
        "",
        f"- MBO: `${estimates['schema_totals']['mbo']['cost_usd']:.6f}` for {estimates['schema_totals']['mbo']['record_count']:,} estimated records.",
        f"- MBP-10: `${estimates['schema_totals']['mbp-10']['cost_usd']:.6f}` for {estimates['schema_totals']['mbp-10']['record_count']:,} estimated records.",
        f"- Combined frozen acquisition request: `${estimates['combined_totals']['cost_usd']:.6f}` for {estimates['combined_totals']['record_count']:,} estimated records and {estimates['combined_totals']['billable_size']:,} billable bytes.",
        "- This estimate is not purchase authorization. No job was submitted, no file was downloaded, and no charge was incurred.",
        "",
        "## Coverage verdict",
        "",
        f"- Dates with positive full-day metadata counts for both schemas: `{coverage['gc_microstructure']['selected_dates_with_positive_daily_counts_both_schemas']}/203`.",
        f"- Front-contract symbology complete: `{coverage['gc_microstructure']['front_instrument_mapping_complete']}`.",
        "- Full-day metadata cannot prove that each London/New York 15-minute prediction window is complete. That remains a mandatory value-blind gate after separately authorized acquisition.",
        "- Historical pre-event consensus remains partial/unverified and therefore UNKNOWN where unavailable; unavailable ETF, central-bank, options, and news fields are not eligible V1 substitutes.",
        "",
        "## Research boundary",
        "",
        "The contract, all 85 feature roles, eight derived microstructure states, eligible point-in-time contexts, neutral outcomes, support gates, uncertainty, multiplicity, and ranking order are frozen. No market values, outcomes, relationships, candidates, signals, trades, execution variants, PnL, R multiples, or account returns were calculated.",
        "",
        "Step 5A stops here.",
        "",
    ])


def _contract_doc(context: dict[str, Any], verdict: dict[str, Any]) -> str:
    return "\n".join([
        "# GC Microstructure Conditional Edge Discovery Contract V1",
        "",
        "The machine-readable contract is `research_manifests/gc_microstructure_conditional_edge_discovery_contract_v01.json`.",
        "",
        f"Freeze receipt: `{context['freeze']['freeze_hash']}`.",
        "",
        "London and New York are independent research units. Their decision clock is 08:00 local in `Europe/London` and `America/New_York`, converted with IANA timezone rules. Features use only complete one-second GC buckets before the cutoff. The neutral XAUUSD outcome begins at the frozen 08:01 local reference and ends at 12:00 local; it is not a trade or assumed fill.",
        "",
        "The development sample is the second complete Monday–Friday block of every calendar month from August 2021 through December 2024. Six microstructure engineering dates are permanently excluded. Calendar 2025 remains exposed historical forward data, and every 2026 value remains locked.",
        "",
        "Only registered standalone microstructure states and explicitly enumerated two-condition interactions may later be tested. Support uses selected-week clustering; uncertainty uses a year-stratified week-cluster bootstrap and permutation test; multiplicity uses Benjamini–Hochberg at q=0.05 separately by session and stage. Zero candidates is acceptable. Development evidence can only create a provisional, unvalidated candidate.",
        "",
        "Trade construction, entry/exit logic, execution optimization, and PnL are outside this contract.",
        "",
        f"Step 5A result: `{verdict['status']}`. No acquisition or research-value access occurred.",
        "",
    ])


def _verify(output: Path) -> None:
    context = _frozen_context()
    manifest = _read_json(output / "manifest.json")
    verdict = _read_json(output / "verdict.json")
    coverage = _read_json(output / "source_coverage_audit.json")
    if manifest["manifest_hash"] != _canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}):
        raise ValueError("Step 5A manifest canonical hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash({key: value for key, value in verdict.items() if key != "verdict_hash"}):
        raise ValueError("Step 5A verdict canonical hash mismatch")
    if coverage["coverage_hash"] != _canonical_hash({key: value for key, value in coverage.items() if key != "coverage_hash"}):
        raise ValueError("Step 5A coverage canonical hash mismatch")
    for record in [*manifest["records"].values(), *manifest["artifacts"]]:
        _verify_record(record)
    if manifest["records"]["freeze_receipt"]["sha256"] != _sha(FREEZE):
        raise ValueError("Step 5A freeze record mismatch")
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_5A_SEAL_VERIFIED",
        "status": manifest["status"],
        "manifest_hash": manifest["manifest_hash"],
        "freeze_hash": context["freeze"]["freeze_hash"],
        "sealed_artifacts_verified": len(manifest["artifacts"]),
        "data_acquired": manifest["data_acquired"],
        "charge_incurred": manifest["charge_incurred"],
        "market_values_or_outcomes_accessed": manifest["market_values_or_outcomes_accessed"],
    }, sort_keys=True))


def _design_context() -> dict[str, Any]:
    if not CONTRACT.exists() or not FEATURE_REGISTRY.exists():
        raise FileNotFoundError("Step 5A contract and feature registry must exist before freeze")
    checks: dict[str, bool] = {}
    for path, expected in EXPECTED_FILES.items():
        checks[f"sha256:{_rel(path)}"] = path.exists() and _sha(path) == expected
    contract = _read_json(CONTRACT)
    features = _read_json(FEATURE_REGISTRY)
    step4a = _read_json(STEP4A)
    step4b3 = _read_json(STEP4B3)
    v3_contract = _read_json(V3_CONTRACT)
    v3_trace = _read_json(V3_TRACE)
    v3_cases = _read_json(V3_CASES)
    checks.update({
        "contract_status_frozen": contract["status"] == "FROZEN_BEFORE_METADATA_QUOTE_OR_RESEARCH_VALUE_ACCESS",
        "step4b3_manifest_internal_hash": step4b3.get("manifest_hash") == EXPECTED_INTERNAL["step4b3_manifest_hash"],
        "step4b3_status_preserved": step4b3.get("status") == EXPECTED_INTERNAL["step4b3_status"],
        "v3_contract_internal_hash": v3_contract.get("manifest_hash") == EXPECTED_INTERNAL["v3_contract_hash"],
        "v3_trace_internal_hash": v3_trace.get("catalog_hash") == EXPECTED_INTERNAL["v3_trace_hash"],
        "v3_cases_internal_hash": v3_cases.get("manifest_hash") == EXPECTED_INTERNAL["v3_cases_hash"],
        "reference_book_bytes": BOOK.stat().st_size == 971812,
    })
    step4_columns = _step4_columns(step4a)
    registry_columns = _registry_columns(features)
    dispositions = [item for values in features["column_dispositions"].values() for item in values]
    checks.update({
        "step4a_feature_count_85": len(step4_columns) == len(set(step4_columns)) == 85,
        "step5a_registry_count_85": len(registry_columns) == len(set(registry_columns)) == 85,
        "step5a_columns_exact_step4a_order_and_names": registry_columns == step4_columns,
        "dispositions_disjoint_union_85": len(dispositions) == len(set(dispositions)) == 85 and set(dispositions) == set(step4_columns),
        "eight_microstructure_states_frozen": len(features["derived_microstructure_states"]) == 8,
        "eight_fundamental_contexts_frozen": len(features["eligible_fundamental_bias_contexts"]) == 8,
        "seven_price_session_contexts_frozen": len(features["eligible_price_level_and_session_contexts"]) == 7,
        "all_interactions_two_condition": all(len(pair) == 2 for family in features["hypothesis_families"] for pair in family.get("eligible_two_condition_interactions", [])),
        "no_trade_or_execution_scope": any("trade direction" in item for item in features["prohibited"]),
    })
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError(f"Step 5A design/predecessor checks failed: {failed}")
    return {"contract": contract, "features": features, "checks": checks}


def _frozen_context() -> dict[str, Any]:
    context = _design_context()
    freeze = _read_json(FREEZE)
    if freeze["freeze_hash"] != _canonical_hash({key: value for key, value in freeze.items() if key != "freeze_hash"}):
        raise ValueError("Step 5A freeze canonical hash mismatch")
    for record in freeze["records"].values():
        _verify_record(record)
    requests = _read_json(REQUEST_REGISTRY)
    if requests["registry_hash"] != _canonical_hash({key: value for key, value in requests.items() if key != "registry_hash"}):
        raise ValueError("Step 5A request registry canonical hash mismatch")
    if requests["provider_quote_request_count"] != 86 or requests["daily_coverage_check_count"] != 406:
        raise ValueError("Step 5A frozen request counts changed")
    context["freeze"] = freeze
    context["requests"] = requests
    return context


def _step4_columns(protocol: dict[str, Any]) -> list[str]:
    registry = protocol["feature_registry"]
    return [
        *registry["identity_and_time"],
        *registry["mbo_counts"],
        *registry["mbo_side_flow"],
        *[key for key in registry["mbo_ratios_ppb"] if key != "null_rule"],
        *registry["mbp_counts_and_state"],
        *registry["mbp_price_features_fixed_1e9"].keys(),
        *registry["mbp_depth_features"],
    ]


def _registry_columns(registry: dict[str, Any]) -> list[str]:
    columns = registry["sealed_feature_columns"]
    return [item for key, values in columns.items() if key != "expected_count" for item in values]


def _client(key: str) -> tuple[Any, str]:
    try:
        import databento as db
    except ModuleNotFoundError as exc:
        raise RuntimeError("Databento SDK is required") from exc
    return db.Historical(key), str(getattr(db, "__version__", "UNKNOWN"))


def _api_key(env_file: Path) -> str:
    value = os.getenv("DATABENTO_API_KEY", "").strip()
    if value:
        return value
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, candidate = line.split("=", 1)
            if name.strip() == "DATABENTO_API_KEY":
                value = candidate.strip().strip("\"'")
                if value:
                    return value
    raise RuntimeError("DATABENTO_API_KEY is missing")


def _retry(name: str, operation: Callable[[], Any]) -> Any:
    error: Exception | None = None
    for attempt in range(5):
        try:
            return operation()
        except Exception as exc:  # provider exceptions vary by SDK release
            error = exc
            if attempt == 4:
                break
            sleep_time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"Databento metadata call failed after retries: {name}") from error


def _totals(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    cost = sum((Decimal(str(item["cost_usd"])) for item in quotes), Decimal("0"))
    return {
        "request_count": len(quotes),
        "cost_usd": float(cost),
        "record_count": sum(item["record_count"] for item in quotes),
        "billable_size": sum(item["billable_size"] for item in quotes),
    }


def _consecutive_runs(days: list[date]) -> list[list[date]]:
    if not days:
        return []
    runs = [[days[0]]]
    for day in days[1:]:
        if day == runs[-1][-1] + timedelta(days=1):
            runs[-1].append(day)
        else:
            runs.append([day])
    return runs


def _cutoff(day: date, zone: str) -> datetime:
    return datetime.combine(day, time(8, 0), tzinfo=ZoneInfo(zone)).astimezone(UTC)


def _offset_text(local: datetime) -> str:
    offset = local.utcoffset()
    if offset is None:
        raise ValueError("Timezone offset is unavailable")
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _next_month(day: date) -> date:
    return date(day.year + (1 if day.month == 12 else 0), 1 if day.month == 12 else day.month + 1, 1)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _now() -> str:
    return _iso(datetime.now(UTC))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _record(path: Path) -> dict[str, Any]:
    return {"path": _rel(path), "bytes": path.stat().st_size, "sha256": _sha(path)}


def _verify_record(record: dict[str, Any]) -> None:
    path = ROOT / record["path"]
    if not path.exists() or path.stat().st_size != record["bytes"] or _sha(path) != record["sha256"]:
        raise ValueError(f"Sealed file changed: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
