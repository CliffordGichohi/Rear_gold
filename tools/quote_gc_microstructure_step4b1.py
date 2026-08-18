#!/usr/bin/env python3
"""Run the frozen Step 4B.1 metadata-only multi-day readiness quote.

This utility contains no batch submission, time-series retrieval, or download
path. It calls only Databento symbology resolution and metadata cost,
record-count, and billable-size endpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4b1_protocol_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4b1_freeze_v01.json"
)
STEP4A3_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4a3_v01"
    / "manifest.json"
)
CALENDAR_PATH = (
    REPO_ROOT
    / "data"
    / "mt5"
    / "calendar"
    / "us_gold_macro_calendar_2024_p1.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4b1_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_4B1_REPORT.md"

EXPECTED_PROTOCOL_SHA256 = (
    "a3945d747d0a20aa0143ab03fb65e3bb5bdf8d750c2018a3e2fd6de6090c1be9"
)
EXPECTED_FREEZE_SHA256 = (
    "e8031f3a9a6b0e6c4a86df4bae9ba2f4a1c481b1529a0449eabb4f0a387b3656"
)
EXPECTED_STEP4A3_MANIFEST_HASH = (
    "879a4321c535a02ad89905a3a4d926e052a8c611b36af9774d5ba403485e610e"
)
EXPECTED_STEP4A3_VERDICT_HASH = (
    "f959516ceea67ca69648850196dc6bdd24f2b8229ea61222059a7f5b52729a0b"
)
EXPECTED_CALENDAR_SHA256 = (
    "cd8bf6a3e83bf29389136e6fd596acd788779980fbcba12f517fca4fd467df0c"
)
EXPECTED_CALENDAR_BYTES = 518_063
EXPECTED_CALENDAR_EVENTS = 118
EXPECTED_SELECTED_EVENT_SHA256 = (
    "8c40d99008efb3d319af4cd3dfc70ae6c848007cc47becfff4ba92069c22fee8"
)

DATASET = "GLBX.MDP3"
SYMBOLS = ["GC.v.0"]
STYPE_IN = "continuous"
SCHEMAS = ("mbo", "mbp-10")
SELECTED_DATES = (
    "2024-01-05",
    "2024-01-11",
    "2024-01-30",
    "2024-01-31",
    "2024-03-20",
)
ALLOWED_CALENDAR_FIELDS = (
    "event_code",
    "event_type",
    "importance",
    "is_scheduled",
    "name",
    "scheduled_at",
    "source_event_key",
)
EXPECTED_EVENT_ROWS = (
    {
        "event_code": "US_EMPLOYMENT_SITUATION",
        "event_type": "NFP",
        "importance": 5,
        "is_scheduled": True,
        "name": "US Employment Situation",
        "scheduled_at": "2024-01-05T13:30:00+00:00",
        "source_event_key": "MT5:US_EMPLOYMENT_SITUATION:20240105T133000Z",
    },
    {
        "event_code": "US_CPI",
        "event_type": "CPI",
        "importance": 5,
        "is_scheduled": True,
        "name": "US Consumer Price Index",
        "scheduled_at": "2024-01-11T13:30:00+00:00",
        "source_event_key": "MT5:US_CPI:20240111T133000Z",
    },
    {
        "event_code": "US_FOMC_RATE_DECISION",
        "event_type": "FOMC",
        "importance": 5,
        "is_scheduled": True,
        "name": "Federal Reserve Interest Rate Decision",
        "scheduled_at": "2024-03-20T18:00:00+00:00",
        "source_event_key": "MT5:US_FOMC_RATE_DECISION:20240320T180000Z",
    },
)
EXPECTED_INSTRUMENT_INTERVALS = (
    {"start_date_inclusive": "2024-01-01", "end_date_exclusive": "2024-01-31", "instrument_id": 41512},
    {"start_date_inclusive": "2024-01-31", "end_date_exclusive": "2024-03-28", "instrument_id": 44740},
    {"start_date_inclusive": "2024-03-28", "end_date_exclusive": "2024-05-31", "instrument_id": 669},
    {"start_date_inclusive": "2024-05-31", "end_date_exclusive": "2024-07-31", "instrument_id": 2017},
    {"start_date_inclusive": "2024-07-31", "end_date_exclusive": "2024-11-29", "instrument_id": 393},
    {"start_date_inclusive": "2024-11-29", "end_date_exclusive": "2025-01-01", "instrument_id": 1551},
)
EXPECTED_ROLL_PAIR = {
    "2024-01-30": {"instrument_id": 41512, "raw_symbol": "GCG4"},
    "2024-01-31": {"instrument_id": 44740, "raw_symbol": "GCJ4"},
}
EXPECTED_OFFSET_CLASSES = {
    "2024-01-05": "UTC-06:00_CST",
    "2024-01-11": "UTC-06:00_CST",
    "2024-01-30": "UTC-06:00_CST",
    "2024-01-31": "UTC-06:00_CST",
    "2024-03-20": "UTC-05:00_CDT",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("primary", "reference", "seal", "verify"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env"))
    args = parser.parse_args()
    run_stage(args.action, Path(args.output), Path(args.env_file))


def run_stage(action: str, output: Path, env_file: Path) -> None:
    context = _verified_context()
    _assert_protocol_matches_code(context["protocol"])
    output.mkdir(parents=True, exist_ok=True)

    if action in {"primary", "reference"}:
        quote_path = output / f"{action}_quote.json"
        if quote_path.exists():
            raise FileExistsError(f"Refusing to overwrite Step 4B.1 {action} quote")
        api_key = _api_key(env_file)
        client, sdk_version = _client(api_key)
        calendar_selection = _calendar_selection(context["protocol"])
        instrument_metadata = _instrument_metadata(client)
        estimates = _metadata_estimates(client)
        readiness = _run_readiness(
            context=context,
            calendar_selection=calendar_selection,
            instrument_metadata=instrument_metadata,
            estimates=estimates,
        )
        result = {
            "version": "GC_MICROSTRUCTURE_STEP_4B1_QUOTE_RUN_V0_1",
            "implementation": action,
            "classification": "METADATA_ONLY_MULTI_DAY_ENGINEERING_READINESS",
            "research_or_validation_credit": "NONE",
            "queried_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "provider": "Databento",
            "sdk_version": sdk_version,
            "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
            "freeze_sha256": EXPECTED_FREEZE_SHA256,
            "tool_sha256": _sha256(Path(__file__)),
            "calendar_selection": calendar_selection,
            "instrument_metadata": instrument_metadata,
            "estimates": estimates,
            "readiness_checks": readiness,
            "formal_readiness_pass": all(readiness.values()),
            "api_methods_called": [
                "symbology.resolve",
                "metadata.get_cost",
                "metadata.get_record_count",
                "metadata.get_billable_size",
            ],
            "batch_api_called": False,
            "timeseries_api_called": False,
            "data_downloaded": False,
            "charge_incurred": False,
            "market_values_or_outcomes_accessed": False,
            "signals_calculated": False,
            "execution_optimized": False,
            "pnl_calculated": False,
        }
        _write_json_atomic(quote_path, result)
        print(
            json.dumps(
                {
                    "stage": f"GC_MICROSTRUCTURE_STEP_4B1_{action.upper()}_QUOTE_COMPLETE",
                    "implementation": action,
                    "request_count": estimates["request_count"],
                    "mbo_cost_usd": estimates["schema_totals"]["mbo"]["cost_usd"],
                    "mbp10_cost_usd": estimates["schema_totals"]["mbp-10"]["cost_usd"],
                    "combined_cost_usd": estimates["combined_totals"]["cost_usd"],
                    "combined_records": estimates["combined_totals"]["record_count"],
                    "combined_billable_size": estimates["combined_totals"]["billable_size"],
                    "readiness_pass": all(readiness.values()),
                    "batch_api_called": False,
                    "timeseries_api_called": False,
                    "data_downloaded": False,
                    "charge_incurred": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return
    if action == "seal":
        _seal(output, context)
        return
    if action == "verify":
        _verify_seal(output)
        return
    raise AssertionError(action)


def _calendar_selection(protocol: dict[str, Any]) -> dict[str, Any]:
    payload = _read_json(CALENDAR_PATH)
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("Calendar events are missing")
    allowed = [
        {name: event.get(name) for name in ALLOWED_CALENDAR_FIELDS}
        for event in events
    ]

    def eligible(event: dict[str, Any], code: str, offset_class: str) -> bool:
        if event["event_code"] != code or event["importance"] != 5 or event["is_scheduled"] is not True:
            return False
        event_date = str(event["scheduled_at"])[:10]
        return event_date.startswith("2024-") and event_date != "2024-01-09" and _offset_class(event_date) == offset_class

    labour = min(
        (event for event in allowed if eligible(event, "US_EMPLOYMENT_SITUATION", "UTC-06:00_CST")),
        key=lambda event: (str(event["scheduled_at"]), str(event["source_event_key"])),
    )
    inflation = min(
        (
            event
            for event in allowed
            if eligible(event, "US_CPI", "UTC-06:00_CST")
            and str(event["scheduled_at"])[:10] != str(labour["scheduled_at"])[:10]
        ),
        key=lambda event: (str(event["scheduled_at"]), str(event["source_event_key"])),
    )
    fomc = min(
        (
            event
            for event in allowed
            if eligible(event, "US_FOMC_RATE_DECISION", "UTC-05:00_CDT")
            and str(event["scheduled_at"])[:10]
            not in {str(labour["scheduled_at"])[:10], str(inflation["scheduled_at"])[:10]}
        ),
        key=lambda event: (str(event["scheduled_at"]), str(event["source_event_key"])),
    )
    selected_rows = sorted((labour, inflation, fomc), key=lambda event: str(event["scheduled_at"]))
    selected_hash = hashlib.sha256(
        json.dumps(selected_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    offsets = {day: _offset_class(day) for day in SELECTED_DATES}
    selected_dates = sorted(
        {
            str(labour["scheduled_at"])[:10],
            str(inflation["scheduled_at"])[:10],
            str(fomc["scheduled_at"])[:10],
            "2024-01-30",
            "2024-01-31",
        }
    )
    return {
        "calendar_source_sha256": _sha256(CALENDAR_PATH),
        "calendar_source_bytes": CALENDAR_PATH.stat().st_size,
        "calendar_event_count": len(events),
        "allowed_fields_read": list(ALLOWED_CALENDAR_FIELDS),
        "selected_event_rows": selected_rows,
        "selected_event_metadata_sha256": selected_hash,
        "selected_dates_chronological": selected_dates,
        "selected_date_offsets": offsets,
        "selection_matches_frozen_protocol": (
            selected_rows == list(EXPECTED_EVENT_ROWS)
            and selected_hash == EXPECTED_SELECTED_EVENT_SHA256
            and selected_dates == list(SELECTED_DATES)
            and offsets == EXPECTED_OFFSET_CLASSES
            and protocol["exact_selection_rules"]["selected_dates_chronological"] == list(SELECTED_DATES)
        ),
        "prohibited_calendar_fields_read": False,
        "market_values_or_outcomes_used": False,
    }


def _instrument_metadata(client: Any) -> dict[str, Any]:
    response = _json_safe(
        client.symbology.resolve(
            dataset=DATASET,
            symbols=SYMBOLS,
            stype_in="continuous",
            stype_out="instrument_id",
            start_date="2024-01-01",
            end_date="2025-01-01",
        )
    )
    raw_intervals = list(response.get("result", {}).get("GC.v.0", []))
    intervals = [
        {
            "start_date_inclusive": str(item["d0"]),
            "end_date_exclusive": str(item["d1"]),
            "instrument_id": int(item["s"]),
        }
        for item in raw_intervals
    ]
    roll_pair: dict[str, dict[str, Any]] = {}
    for day, expected in EXPECTED_ROLL_PAIR.items():
        instrument_id = str(expected["instrument_id"])
        next_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        raw = _json_safe(
            client.symbology.resolve(
                dataset=DATASET,
                symbols=[instrument_id],
                stype_in="instrument_id",
                stype_out="raw_symbol",
                start_date=day,
                end_date=next_day,
            )
        )
        raw_result = list(raw.get("result", {}).get(instrument_id, []))
        if raw.get("status") != 0 or raw.get("partial") or raw.get("not_found") or len(raw_result) != 1:
            raise ValueError(f"Incomplete raw-symbol resolution for {day}")
        roll_pair[day] = {
            "instrument_id": int(instrument_id),
            "raw_symbol": str(raw_result[0]["s"]),
        }
    complete = (
        response.get("status") == 0
        and not response.get("partial")
        and not response.get("not_found")
        and intervals == list(EXPECTED_INSTRUMENT_INTERVALS)
        and roll_pair == EXPECTED_ROLL_PAIR
    )
    return {
        "request": {
            "dataset": DATASET,
            "symbols": SYMBOLS,
            "stype_in": "continuous",
            "stype_out": "instrument_id",
            "start_date": "2024-01-01",
            "end_date": "2025-01-01",
        },
        "response_status": int(response.get("status", -1)),
        "partial": list(response.get("partial") or []),
        "not_found": list(response.get("not_found") or []),
        "intervals": intervals,
        "selected_roll_pair": roll_pair,
        "complete_and_matches_frozen_protocol": complete,
        "market_values_returned_or_used": False,
    }


def _metadata_estimates(client: Any) -> dict[str, Any]:
    quotes: list[dict[str, Any]] = []
    for day in SELECTED_DATES:
        end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        for schema in SCHEMAS:
            request = {
                "dataset": DATASET,
                "symbols": SYMBOLS,
                "schema": schema,
                "stype_in": STYPE_IN,
                "start": f"{day}T00:00:00Z",
                "end": f"{end}T00:00:00Z",
            }
            cost = float(client.metadata.get_cost(**request))
            records = int(client.metadata.get_record_count(**request))
            billable = int(client.metadata.get_billable_size(**request))
            if not math.isfinite(cost):
                raise ValueError(f"Non-finite metadata cost for {day} {schema}")
            quote = {
                "request_id": f"{day}:{schema}",
                "engineering_date": day,
                "schema": schema,
                "request": request,
                "cost_usd": cost,
                "record_count": records,
                "billable_size": billable,
            }
            quotes.append(quote)
            print(
                json.dumps(
                    {
                        "stage": "GC_MICROSTRUCTURE_STEP_4B1_METADATA_REQUEST_COMPLETE",
                        "request_id": quote["request_id"],
                        "cost_usd": cost,
                        "record_count": records,
                        "billable_size": billable,
                        "batch_api_called": False,
                        "data_downloaded": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    schema_totals: dict[str, dict[str, Any]] = {}
    for schema in SCHEMAS:
        subset = [item for item in quotes if item["schema"] == schema]
        schema_totals[schema] = _quote_totals(subset)
    return {
        "request_count": len(quotes),
        "quotes": quotes,
        "schema_totals": schema_totals,
        "combined_totals": _quote_totals(quotes),
        "estimates_are_not_purchase_authorization": True,
    }


def _quote_totals(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    total_cost = sum((Decimal(str(item["cost_usd"])) for item in quotes), Decimal("0"))
    return {
        "request_count": len(quotes),
        "cost_usd": float(total_cost),
        "record_count": sum(int(item["record_count"]) for item in quotes),
        "billable_size": sum(int(item["billable_size"]) for item in quotes),
    }


def _run_readiness(
    *,
    context: dict[str, Any],
    calendar_selection: dict[str, Any],
    instrument_metadata: dict[str, Any],
    estimates: dict[str, Any],
) -> dict[str, bool]:
    quotes = estimates["quotes"]
    request_ids = {item["request_id"] for item in quotes}
    expected_ids = {f"{day}:{schema}" for day in SELECTED_DATES for schema in SCHEMAS}
    return {
        "step_4a3_and_earlier_seals_valid": bool(context["predecessor_seals_valid"]),
        "calendar_source_hash_bytes_and_event_count_exact": (
            calendar_selection["calendar_source_sha256"] == EXPECTED_CALENDAR_SHA256
            and calendar_selection["calendar_source_bytes"] == EXPECTED_CALENDAR_BYTES
            and calendar_selection["calendar_event_count"] == EXPECTED_CALENDAR_EVENTS
        ),
        "calendar_selection_reads_only_allowed_fields": (
            calendar_selection["allowed_fields_read"] == list(ALLOWED_CALENDAR_FIELDS)
            and not calendar_selection["prohibited_calendar_fields_read"]
        ),
        "calendar_selection_and_metadata_checksum_exact": bool(calendar_selection["selection_matches_frozen_protocol"]),
        "symbology_and_front_contract_transition_exact": bool(instrument_metadata["complete_and_matches_frozen_protocol"]),
        "five_engineering_dates_standard_daylight_and_all_strata_covered": (
            calendar_selection["selected_dates_chronological"] == list(SELECTED_DATES)
            and set(calendar_selection["selected_date_offsets"].values()) == {"UTC-06:00_CST", "UTC-05:00_CDT"}
        ),
        "ten_frozen_quote_requests_exact": estimates["request_count"] == 10 and request_ids == expected_ids,
        "each_cost_finite_and_nonnegative": all(math.isfinite(float(item["cost_usd"])) and float(item["cost_usd"]) >= 0.0 for item in quotes),
        "each_record_count_positive": all(int(item["record_count"]) > 0 for item in quotes),
        "each_billable_size_positive": all(int(item["billable_size"]) > 0 for item in quotes),
        "both_schemas_present_for_every_date": all(sum(item["engineering_date"] == day for item in quotes) == 2 and {item["schema"] for item in quotes if item["engineering_date"] == day} == set(SCHEMAS) for day in SELECTED_DATES),
        "all_dates_permanently_engineering_only": True,
        "no_job_timeseries_download_charge_market_value_outcome_signal_execution_or_pnl": True,
    }


def _seal(output: Path, context: dict[str, Any]) -> None:
    primary = _read_json(output / "primary_quote.json")
    reference = _read_json(output / "reference_quote.json")
    current_tool_hash = _sha256(Path(__file__))
    for run in (primary, reference):
        if run["tool_sha256"] != current_tool_hash:
            raise ValueError("Step 4B.1 quote tool changed between query and seal")
        _verify_quote_run(run)

    compared_sections = (
        "calendar_selection",
        "instrument_metadata",
        "estimates",
        "readiness_checks",
        "formal_readiness_pass",
        "api_methods_called",
        "batch_api_called",
        "timeseries_api_called",
        "data_downloaded",
        "charge_incurred",
        "market_values_or_outcomes_accessed",
        "signals_calculated",
        "execution_optimized",
        "pnl_calculated",
    )
    matching_sections = {name: primary[name] == reference[name] for name in compared_sections}
    reproduction_pass = all(matching_sections.values())
    predecessor_selection_pass = bool(
        context["predecessor_seals_valid"]
        and primary["readiness_checks"]["calendar_selection_and_metadata_checksum_exact"]
        and primary["readiness_checks"]["symbology_and_front_contract_transition_exact"]
    )
    if not predecessor_selection_pass:
        status = "FAIL_PREDECESSOR_OR_SELECTION_INTEGRITY"
    elif not primary["formal_readiness_pass"] or not reference["formal_readiness_pass"]:
        status = "FAIL_METADATA_QUOTE_READINESS"
    elif not reproduction_pass:
        status = "FAIL_METADATA_QUOTE_REPRODUCTION"
    else:
        status = "PASS_METADATA_QUOTE_READINESS"

    formal_gates = {
        "predecessor_and_selection_integrity_pass": predecessor_selection_pass,
        "primary_metadata_readiness_pass": bool(primary["formal_readiness_pass"]),
        "reference_metadata_readiness_pass": bool(reference["formal_readiness_pass"]),
        "calendar_selection_reproduced": matching_sections["calendar_selection"],
        "instrument_metadata_reproduced": matching_sections["instrument_metadata"],
        "all_ten_estimates_reproduced_exactly": matching_sections["estimates"],
        "readiness_checks_reproduced": matching_sections["readiness_checks"],
        "no_job_submission_timeseries_download_or_charge": all(
            not run[key]
            for run in (primary, reference)
            for key in ("batch_api_called", "timeseries_api_called", "data_downloaded", "charge_incurred")
        ),
        "no_market_value_outcome_signal_execution_or_pnl_access": all(
            not run[key]
            for run in (primary, reference)
            for key in ("market_values_or_outcomes_accessed", "signals_calculated", "execution_optimized", "pnl_calculated")
        ),
    }
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_4B1_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS_METADATA_QUOTE_READINESS",
        "classification": "METADATA_ONLY_MULTI_DAY_ENGINEERING_READINESS",
        "research_or_validation_credit": "NONE",
        "predecessor_step_4a3_status": "PASS_FEATURE_INTEGRITY_RECERTIFICATION",
        "predecessor_verdicts_preserved": True,
        "selected_dates_chronological": list(SELECTED_DATES),
        "selection_reasons": _selection_reasons(),
        "selected_date_offsets": primary["calendar_selection"]["selected_date_offsets"],
        "roll_transition": primary["instrument_metadata"]["selected_roll_pair"],
        "estimates": primary["estimates"],
        "formal_gates": formal_gates,
        "passed_formal_gates": sum(formal_gates.values()),
        "total_formal_gates": len(formal_gates),
        "reproduction": {"pass": reproduction_pass, "matching_sections": matching_sections},
        "all_dates_permanently_engineering_only": True,
        "batch_job_submitted": False,
        "timeseries_api_called": False,
        "data_downloaded": False,
        "charge_incurred": False,
        "market_values_or_outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
        "completion_policy": "Preserve the quote and stop before submission, download, or charge.",
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    verdict_path = output / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_text_atomic(REPORT_PATH, _render_report(verdict))
    artifacts = (
        output / "primary_quote.json",
        output / "reference_quote.json",
        verdict_path,
        REPORT_PATH,
    )
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_4B1_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "classification": "METADATA_ONLY_MULTI_DAY_ENGINEERING_READINESS",
        "research_or_validation_credit": "NONE",
        "protocol": _file_record(PROTOCOL_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "step4a3_manifest": _file_record(STEP4A3_MANIFEST_PATH),
        "calendar_source": _file_record(CALENDAR_PATH),
        "quote_tool": _file_record(Path(__file__)),
        "artifacts": [_file_record(path) for path in artifacts],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
        "selected_dates_changed_after_freeze": False,
        "batch_job_submitted": False,
        "timeseries_api_called": False,
        "data_downloaded": False,
        "charge_incurred": False,
        "market_values_or_outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4B1_SEALED",
                "status": status,
                "formal_pass": verdict["formal_pass"],
                "reproduction_pass": reproduction_pass,
                "request_count": verdict["estimates"]["request_count"],
                "mbo_cost_usd": verdict["estimates"]["schema_totals"]["mbo"]["cost_usd"],
                "mbp10_cost_usd": verdict["estimates"]["schema_totals"]["mbp-10"]["cost_usd"],
                "combined_cost_usd": verdict["estimates"]["combined_totals"]["cost_usd"],
                "manifest_hash": manifest["manifest_hash"],
                "batch_job_submitted": False,
                "data_downloaded": False,
                "charge_incurred": False,
            },
            sort_keys=True,
        )
    )


def _selection_reasons() -> dict[str, list[str]]:
    return {
        "2024-01-05": ["LABOUR_STANDARD_TIME"],
        "2024-01-11": ["INFLATION_STANDARD_TIME"],
        "2024-01-30": ["FIRST_FRONT_CONTRACT_TRANSITION_PAIR_PREVIOUS_DAY"],
        "2024-01-31": ["FIRST_FRONT_CONTRACT_TRANSITION_PAIR_EFFECTIVE_DAY"],
        "2024-03-20": ["FOMC_DAYLIGHT_TIME"],
    }


def _render_report(verdict: dict[str, Any]) -> str:
    lines = [
        "# GC Microstructure Step 4B.1 — Multi-Day Metadata Readiness",
        "",
        "## Formal verdict",
        "",
        f"`{verdict['status']}`",
        "",
        "## Frozen engineering dates",
        "",
    ]
    for day in SELECTED_DATES:
        reasons = ", ".join(verdict["selection_reasons"][day])
        lines.append(f"- `{day}` — {reasons}; {verdict['selected_date_offsets'][day]}.")
    lines.extend(
        [
            "",
            "Roll metadata: `GCG4` / instrument `41512` on 2024-01-30, changing to `GCJ4` / instrument `44740` on 2024-01-31.",
            "",
            "## Metadata estimates",
            "",
            "| Date | Schema | Cost (USD) | Records | Billable bytes |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for item in verdict["estimates"]["quotes"]:
        lines.append(
            f"| {item['engineering_date']} | {item['schema']} | {item['cost_usd']:.6f} | {item['record_count']:,} | {item['billable_size']:,} |"
        )
    lines.extend(["", "## Totals", ""])
    for schema in SCHEMAS:
        total = verdict["estimates"]["schema_totals"][schema]
        lines.append(
            f"- {schema}: `${total['cost_usd']:.6f}`, {total['record_count']:,} records, {total['billable_size']:,} billable bytes."
        )
    combined = verdict["estimates"]["combined_totals"]
    lines.extend(
        [
            f"- Combined: `${combined['cost_usd']:.6f}`, {combined['record_count']:,} records, {combined['billable_size']:,} billable bytes.",
            "",
            "## Restrictions honored",
            "",
            "Only calendar metadata, instrument symbology, and Databento metadata estimate endpoints were used. No batch job, time-series request, download, charge, market value, outcome, signal, execution, or PnL was accessed.",
            "",
            "All five dates are permanently engineering-only and receive zero research or validation credit.",
            "",
        ]
    )
    return "\n".join(lines)


def _verify_quote_run(run: dict[str, Any]) -> None:
    if run["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256 or run["freeze_sha256"] != EXPECTED_FREEZE_SHA256:
        raise ValueError("Quote run protocol/freeze hash mismatch")
    if run["estimates"]["request_count"] != 10:
        raise ValueError("Quote run request count mismatch")
    if run["batch_api_called"] or run["timeseries_api_called"] or run["data_downloaded"] or run["charge_incurred"]:
        raise ValueError("Quote run exceeded metadata-only authorization")


def _verify_seal(output: Path) -> None:
    context = _verified_context()
    _assert_protocol_matches_code(context["protocol"])
    manifest = _read_json(output / "manifest.json")
    verdict = _read_json(output / "verdict.json")
    if manifest["manifest_hash"] != _canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}):
        raise ValueError("Step 4B.1 manifest canonical hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash({key: value for key, value in verdict.items() if key != "verdict_hash"}):
        raise ValueError("Step 4B.1 verdict canonical hash mismatch")
    for record in manifest["artifacts"]:
        _verify_file_record(record)
    for key, expected in (
        ("protocol", EXPECTED_PROTOCOL_SHA256),
        ("freeze_receipt", EXPECTED_FREEZE_SHA256),
        ("calendar_source", EXPECTED_CALENDAR_SHA256),
    ):
        if manifest[key]["sha256"] != expected:
            raise ValueError(f"Manifest {key} declaration mismatch")
        _verify_file_record(manifest[key])
    _verify_file_record(manifest["step4a3_manifest"])
    if manifest["quote_tool"]["sha256"] != _sha256(Path(__file__)):
        raise ValueError("Step 4B.1 quote tool changed")
    if manifest["status"] != verdict["status"]:
        raise ValueError("Step 4B.1 manifest/verdict status mismatch")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4B1_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]),
                "predecessor_verdicts_preserved": manifest["predecessor_verdicts_preserved"],
                "selected_dates_changed_after_freeze": manifest["selected_dates_changed_after_freeze"],
                "batch_job_submitted": manifest["batch_job_submitted"],
                "timeseries_api_called": manifest["timeseries_api_called"],
                "data_downloaded": manifest["data_downloaded"],
                "charge_incurred": manifest["charge_incurred"],
                "market_values_or_outcomes_accessed": manifest["market_values_or_outcomes_accessed"],
                "signals_calculated": manifest["signals_calculated"],
                "pnl_calculated": manifest["pnl_calculated"],
                "research_or_validation_credit": manifest["research_or_validation_credit"],
            },
            sort_keys=True,
        )
    )


def _verified_context() -> dict[str, Any]:
    if _sha256(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 4B.1 protocol changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 4B.1 freeze receipt changed")
    protocol = _read_json(PROTOCOL_PATH)
    freeze = _read_json(FREEZE_PATH)
    if freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 4B.1 freeze does not bind protocol")
    if CALENDAR_PATH.stat().st_size != EXPECTED_CALENDAR_BYTES or _sha256(CALENDAR_PATH) != EXPECTED_CALENDAR_SHA256:
        raise ValueError("Frozen calendar metadata changed")
    manifest = _read_json(STEP4A3_MANIFEST_PATH)
    if (
        manifest.get("manifest_hash") != EXPECTED_STEP4A3_MANIFEST_HASH
        or _canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}) != EXPECTED_STEP4A3_MANIFEST_HASH
        or manifest.get("verdict_hash") != EXPECTED_STEP4A3_VERDICT_HASH
        or manifest.get("status") != "PASS_FEATURE_INTEGRITY_RECERTIFICATION"
    ):
        raise ValueError("Step 4A.3 predecessor changed")
    for record in manifest["artifacts"]:
        _verify_file_record(record)
    return {
        "protocol": protocol,
        "freeze": freeze,
        "predecessor_seals_valid": True,
    }


def _assert_protocol_matches_code(protocol: dict[str, Any]) -> None:
    quote = protocol["metadata_quote_contract"]
    if (
        quote["dataset"] != DATASET
        or quote["symbols"] != SYMBOLS
        or quote["stype_in"] != STYPE_IN
        or tuple(quote["schemas_in_fixed_order"]) != SCHEMAS
        or quote["request_count"] != 10
        or tuple(protocol["exact_selection_rules"]["selected_dates_chronological"]) != SELECTED_DATES
        or protocol["exact_selection_rules"]["maximum_distinct_utc_dates"] != 5
        or protocol["dst_aware_market_state_contract"]["selected_date_offsets"] != EXPECTED_OFFSET_CLASSES
    ):
        raise ValueError("Step 4B.1 protocol differs from quote implementation")


def _offset_class(day: str) -> str:
    local = datetime.fromisoformat(f"{day}T12:00:00").replace(tzinfo=ZoneInfo("America/Chicago"))
    offset = local.utcoffset()
    if offset == timedelta(hours=-6) and local.tzname() == "CST":
        return "UTC-06:00_CST"
    if offset == timedelta(hours=-5) and local.tzname() == "CDT":
        return "UTC-05:00_CDT"
    raise ValueError(f"Unexpected America/Chicago offset for {day}: {offset} {local.tzname()}")


def _client(key: str) -> tuple[Any, str]:
    try:
        import databento as db
    except ModuleNotFoundError as exc:
        raise RuntimeError("Databento SDK is required") from exc
    return db.Historical(key), str(getattr(db, "__version__", "UNKNOWN"))


def _api_key(env_file: Path) -> str:
    key = os.getenv("DATABENTO_API_KEY", "").strip()
    if key:
        return key
    if env_file.exists():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "DATABENTO_API_KEY":
                key = value.strip().strip("\"'")
                if key:
                    return key
    raise RuntimeError("DATABENTO_API_KEY is missing")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _verify_file_record(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if not path.exists() or path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
        raise ValueError(f"Sealed file changed: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
