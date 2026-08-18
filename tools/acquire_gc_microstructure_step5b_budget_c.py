#!/usr/bin/env python3
"""Acquire and seal the Step 5B Budget Amendment C research sources.

The program is deliberately stage-based and resumable. Preflight and the
immediate submission recheck use metadata and symbology only. Market values
are never printed or inspected; raw DBN files are preserved byte-for-byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import time as sleep_time
from datetime import UTC, date, datetime, time, timedelta
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tools import databento_gc_mbo_engineering_pilot as mbo_normalizer
from tools import databento_gc_mbp10_step3b2 as mbp10_normalizer
from tools import quote_gc_microstructure_step5a as quote_tool


REPO_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = REPO_ROOT / "research_manifests/gc_microstructure_step_5b_budget_amendment_c_v01.json"
REGISTRY_PATH = REPO_ROOT / "research_manifests/gc_microstructure_step_5b_budget_c_request_registry_v01.json"
FREEZE_PATH = REPO_ROOT / "research_manifests/gc_microstructure_step_5b_budget_c_freeze_v01.json"
ORIGINAL_AUTHORIZATION_PATH = REPO_ROOT / "research_manifests/gc_microstructure_step_5b_authorization_v01.json"
STEP5A_MANIFEST_PATH = REPO_ROOT / "research_artifacts/gc_microstructure_step_5a_v01/manifest.json"
ATTEMPT1_MANIFEST_PATH = REPO_ROOT / "research_artifacts/gc_microstructure_step_5b_v01/manifest.json"
ATTEMPT2_MANIFEST_PATH = REPO_ROOT / "research_artifacts/gc_microstructure_step_5b_resume_v01/manifest.json"
ATTEMPT2_PREFLIGHT_PATH = REPO_ROOT / "research_artifacts/gc_microstructure_step_5b_resume_v01/pre_submission_quote.json"
DEFAULT_DESTINATION_ROOT = Path("/home/wapi/rear_gold_step5b_v01")
DEFAULT_OUTPUT = DEFAULT_DESTINATION_ROOT / "data/databento_gc_microstructure_budget_c_v01"
DEFAULT_ARTIFACTS = DEFAULT_DESTINATION_ROOT / "artifacts/step5b_budget_c_final"
REPORT_PATH = DEFAULT_DESTINATION_ROOT / "artifacts/GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_REPORT.md"

EXPECTED_AMENDMENT_SHA256 = "60ae7fa1bdca50461ab2f1089040996f8f99ad6e7def1dbb9dc7ab181c30f246"
EXPECTED_REGISTRY_SHA256 = "d8dfe8a04e0f824c98ec4e88b6c75b7e56214616e56124b76bdbfe0b20b0dd99"
EXPECTED_ORIGINAL_AUTHORIZATION_SHA256 = "653c37f265ab055ff42928d1fb60853593a8556e0d744d6b671630a5e933e76a"
EXPECTED_STEP5A_MANIFEST_SHA256 = "4fbc2b8365badb5c44f35201524629782873b43eb3b06861e4d289f8449b51c9"
EXPECTED_ATTEMPT1_MANIFEST_SHA256 = "ac1418b0e8b5db020fa3c20319c6eec597dfa4898cffb51f6b6b0397520fddec"
EXPECTED_ATTEMPT2_MANIFEST_SHA256 = "b635c6cd0d195e1bd21c50417bcd1396c7c2f0f4993c40ae0f20d91fbd8bd711"
EXPECTED_ATTEMPT2_PREFLIGHT_SHA256 = "9c4a83c9502d8915a12a526fcaa3784ad348af98eaa42700b1283560fb77a701"
EXPECTED_QUOTE_TOOL_SHA256 = "1d84e69e44ded71e11dfc4648b93c39b86984bab20f4dac7aaef50beca851dbf"
EXPECTED_MBO_NORMALIZER_SHA256 = (
    "ddb4225576c2b37370712cf7b1d20707f1aa0b91bcdbb4acf6a369bd51bc590c"
)
EXPECTED_MBP10_NORMALIZER_SHA256 = (
    "551fc9a76036739f3dc24adbe8b754e63971953614279de93bd162590e3486c5"
)
EXPECTED_SDK_VERSION = "0.82.0"
EXPECTED_PACKAGES = {
    "databento": "0.82.0",
    "databento-dbn": "0.63.0",
    "numpy": "2.5.1",
    "pandas": "3.0.5",
    "pyarrow": "25.0.0",
    "zstandard": "0.25.0",
}
AVAILABLE_CREDITS_USD = 108.78
MAXIMUM_COMBINED_CHARGE_USD = 108.78
MINIMUM_FREE_STORAGE_BYTES = 375_809_638_400
EXPECTED_REQUEST_COUNT = 80
EXPECTED_DATE_COUNT = 188
F_SNAPSHOT = 1 << 5
F_BAD_TS_RECV = 1 << 3
F_MAYBE_BAD_BOOK = 1 << 7
UNDEFINED_FIXED_PRICE = 9_223_372_036_854_775_807

COMMON_REQUEST = {
    "dataset": "GLBX.MDP3",
    "symbols": ["GC.v.0"],
    "stype_in": "continuous",
    "stype_out": "instrument_id",
    "encoding": "dbn",
    "compression": "zstd",
    "pretty_px": False,
    "pretty_ts": False,
    "map_symbols": False,
    "split_duration": "day",
    "split_symbols": False,
    "delivery": "download",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("preflight", "submit", "status", "download", "normalize", "seal", "verify"),
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--artifacts", default=str(DEFAULT_ARTIFACTS))
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env"))
    args = parser.parse_args()
    run_stage(
        args.action,
        output=Path(args.output),
        artifacts=Path(args.artifacts),
        env_file=Path(args.env_file),
    )


def run_stage(action: str, *, output: Path, artifacts: Path, env_file: Path) -> None:
    context = _verified_context()
    _assert_registry_matches_code(context["registry"])
    acquisition_path = output / "acquisition_manifest.json"

    if action == "verify":
        _verify_seal(artifacts)
        return
    if action == "seal":
        _seal(output, acquisition_path, artifacts, context)
        return

    key = quote_tool._api_key(env_file)
    client, sdk_version = quote_tool._client(key)
    if sdk_version != EXPECTED_SDK_VERSION:
        raise RuntimeError(
            f"Databento SDK changed: expected {EXPECTED_SDK_VERSION}, got {sdk_version}"
        )

    if action == "preflight":
        _preflight(client, sdk_version, output, acquisition_path, context)
        return
    acquisition = _load_acquisition(acquisition_path)
    if action == "submit":
        _submit(client, output, acquisition_path, acquisition, context)
        return
    if action == "status":
        _status(client, acquisition_path, acquisition)
        return
    if action == "download":
        _download(client, output, acquisition_path, acquisition)
        return
    if action == "normalize":
        _normalize_all(output, acquisition_path, acquisition)
        return
    raise AssertionError(action)


def _requests(
    registry: dict[str, Any], instrument_metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    mappings = {
        row["trade_date"]: int(row["instrument_id"])
        for row in instrument_metadata["selected_date_mappings"]
        if row["instrument_id"] is not None and row["match_count"] == 1
    }
    intervals = {
        row["interval_id"]: row for row in registry["request_intervals"]
    }
    date_rows = {row["trade_date"]: row for row in registry["selected_dates"]}
    requests: list[dict[str, Any]] = []
    for item in registry["provider_quote_requests"]:
        interval = intervals[item["interval_id"]]
        selected_dates = list(interval["selected_dates"])
        if any(day not in mappings for day in selected_dates):
            raise ValueError(f"Incomplete instrument mapping: {item['request_id']}")
        request = {
            **COMMON_REQUEST,
            "schema": item["request"]["schema"],
            "start": item["request"]["start"],
            "end": item["request"]["end"],
        }
        requests.append(
            {
                "request_id": item["request_id"],
                "interval_id": item["interval_id"],
                "selected_month_week_id": item["selected_month_week_id"],
                "schema": item["schema"],
                "selected_dates": selected_dates,
                "selected_date_rows": [date_rows[day] for day in selected_dates],
                "expected_instrument_ids": sorted({mappings[day] for day in selected_dates}),
                "expected_instrument_id_by_date": {
                    day: mappings[day] for day in selected_dates
                },
                "request": request,
                "request_fingerprint": _canonical_hash(request),
            }
        )
    return requests


def _instrument_metadata(client: Any, registry: dict[str, Any]) -> dict[str, Any]:
    """Resolve only continuous-contract metadata for the amended dates."""
    request = registry["symbology_request"]
    response = _json_safe(
        _retry("symbology.resolve", lambda: client.symbology.resolve(**request))
    )
    items = response.get("result", {}).get("GC.v.0", [])
    intervals = sorted(
        (
            {
                "start_date_inclusive": str(item["d0"]),
                "end_date_exclusive": str(item["d1"]),
                "instrument_id": int(item["s"]),
            }
            for item in items
        ),
        key=lambda item: (
            item["start_date_inclusive"],
            item["end_date_exclusive"],
            item["instrument_id"],
        ),
    )
    mappings: list[dict[str, Any]] = []
    invalid: list[str] = []
    for row in registry["selected_dates"]:
        day = row["trade_date"]
        matches = [
            item
            for item in intervals
            if item["start_date_inclusive"] <= day < item["end_date_exclusive"]
        ]
        instrument_id = matches[0]["instrument_id"] if len(matches) == 1 else None
        if len(matches) != 1:
            invalid.append(day)
        mappings.append(
            {
                "trade_date": day,
                "instrument_id": instrument_id,
                "match_count": len(matches),
            }
        )
    return {
        "request": request,
        "response_status": int(response.get("status", -1)),
        "partial": sorted(response.get("partial") or []),
        "not_found": sorted(response.get("not_found") or []),
        "mapping_intervals": intervals,
        "selected_date_mappings": mappings,
        "selected_date_mapping_hash": _canonical_hash(mappings),
        "response_complete": (
            response.get("status") == 0
            and not response.get("partial")
            and not response.get("not_found")
            and bool(intervals)
        ),
        "all_selected_dates_map_exactly_once": (
            not invalid and len(mappings) == EXPECTED_DATE_COUNT
        ),
        "invalid_selected_dates": invalid,
        "market_values_returned_or_used": False,
    }


def _interval_estimates(
    client: Any, registry: dict[str, Any], implementation: str
) -> dict[str, Any]:
    """Quote every frozen request using metadata endpoints only."""
    quotes: list[dict[str, Any]] = []
    for index, frozen in enumerate(registry["provider_quote_requests"], start=1):
        request = frozen["request"]
        cost = float(
            _retry(
                "metadata.get_cost",
                lambda request=request: client.metadata.get_cost(**request),
            )
        )
        records = int(
            _retry(
                "metadata.get_record_count",
                lambda request=request: client.metadata.get_record_count(**request),
            )
        )
        billable = int(
            _retry(
                "metadata.get_billable_size",
                lambda request=request: client.metadata.get_billable_size(**request),
            )
        )
        quotes.append(
            {
                "request_id": frozen["request_id"],
                "interval_id": frozen["interval_id"],
                "selected_month_week_id": frozen["selected_month_week_id"],
                "schema": frozen["schema"],
                "request": request,
                "cost_usd": cost,
                "record_count": records,
                "billable_size": billable,
            }
        )
        if index % 10 == 0 or index == EXPECTED_REQUEST_COUNT:
            print(
                json.dumps(
                    {
                        "stage": "STEP_5B_BUDGET_C_METADATA_PROGRESS",
                        "implementation": implementation,
                        "completed": index,
                        "total": EXPECTED_REQUEST_COUNT,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    schema_totals = {
        schema: _quote_totals([item for item in quotes if item["schema"] == schema])
        for schema in ("mbo", "mbp-10")
    }
    return {
        "request_count": len(quotes),
        "quotes": quotes,
        "schema_totals": schema_totals,
        "combined_totals": _quote_totals(quotes),
        "estimate_is_purchase_authorization": False,
        "metadata_only": True,
    }


def _quote_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cost_usd": math.fsum(float(row["cost_usd"]) for row in rows),
        "record_count": sum(int(row["record_count"]) for row in rows),
        "billable_size": sum(int(row["billable_size"]) for row in rows),
    }


def _retry(label: str, operation: Any, attempts: int = 5) -> Any:
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception:
            if attempt == attempts:
                raise
            print(
                json.dumps(
                    {
                        "stage": "STEP_5B_BUDGET_C_PROVIDER_RETRY",
                        "operation": label,
                        "attempt_completed": attempt,
                        "next_delay_seconds": delay,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            sleep_time.sleep(delay)
            delay = min(delay * 2.0, 16.0)


def _preflight(
    client: Any,
    sdk_version: str,
    output: Path,
    acquisition_path: Path,
    context: dict[str, Any],
) -> None:
    if output.exists() or acquisition_path.exists():
        raise FileExistsError("Refusing to overwrite an existing Step 5B Budget C acquisition")
    output.parent.mkdir(parents=True, exist_ok=True)
    free_storage = int(shutil.disk_usage(output.parent).free)
    registry = context["registry"]
    instrument_metadata = _instrument_metadata(client, registry)
    estimates = _interval_estimates(client, registry, "budget_c_preflight")
    requests = _requests(registry, instrument_metadata)
    quote_by_id = {
        str(item["request_id"]): item for item in estimates["quotes"]
    }
    intent_rows: list[dict[str, Any]] = []
    for request in requests:
        quote = quote_by_id.get(request["request_id"])
        if quote is None:
            raise ValueError(f"Fresh quote missing: {request['request_id']}")
        metadata_request = {
            key: request["request"][key]
            for key in ("dataset", "symbols", "schema", "stype_in", "start", "end")
        }
        if quote["request"] != metadata_request:
            raise ValueError(f"Fresh quote request differs: {request['request_id']}")
        intent_rows.append({**request, "fresh_quote": quote})

    combined_cost = float(estimates["combined_totals"]["cost_usd"])
    prior_mappings = {
        row["trade_date"]: row
        for row in context["attempt2_preflight"]["instrument_metadata"]["selected_date_mappings"]
    }
    expected_mappings = [prior_mappings[row["trade_date"]] for row in registry["selected_dates"]]
    package_versions = {
        name: importlib_metadata.version(name) for name in EXPECTED_PACKAGES
    }
    gates = {
        "all_predecessor_and_budget_c_seals_valid": bool(context["predecessor_seals_valid"]),
        "databento_sdk_version_exact": sdk_version == EXPECTED_SDK_VERSION,
        "normalization_packages_exact": package_versions == EXPECTED_PACKAGES,
        "all_80_request_fingerprints_exact": len(intent_rows) == EXPECTED_REQUEST_COUNT,
        "all_188_dates_map_exactly_once": instrument_metadata["all_selected_dates_map_exactly_once"],
        "selected_date_continuous_symbology_unchanged": instrument_metadata["selected_date_mappings"] == expected_mappings,
        "free_storage_at_or_above_frozen_minimum": free_storage >= MINIMUM_FREE_STORAGE_BYTES,
        "each_fresh_cost_finite_and_nonnegative": all(
            math.isfinite(float(row["fresh_quote"]["cost_usd"]))
            and float(row["fresh_quote"]["cost_usd"]) >= 0
            for row in intent_rows
        ),
        "each_fresh_record_count_positive": all(
            int(row["fresh_quote"]["record_count"]) > 0 for row in intent_rows
        ),
        "each_fresh_billable_size_positive": all(
            int(row["fresh_quote"]["billable_size"]) > 0 for row in intent_rows
        ),
        "fresh_combined_cost_at_or_below_authorized_cap": (
            math.isfinite(combined_cost)
            and combined_cost <= MAXIMUM_COMBINED_CHARGE_USD
        ),
        "fresh_combined_cost_within_observed_credits": combined_cost <= AVAILABLE_CREDITS_USD,
        "card_charge_not_required_or_permitted": combined_cost <= AVAILABLE_CREDITS_USD,
        "no_existing_incompatible_or_duplicate_intent": True,
    }
    if not all(gates.values()):
        raise RuntimeError(f"Step 5B Budget C pre-submission readiness failed: {gates}")

    intent_time = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    acquisition = {
        "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_ACQUISITION_V0_1",
        "status": "PREFLIGHT_PASS_SUBMISSION_INTENT_RECORDED",
        "classification": "RESEARCH_DEVELOPMENT_SOURCE_ACQUISITION_VALUE_BLIND",
        "development_credit": "ELIGIBLE_ONLY_AFTER_LATER_CASE_CONSTRUCTION_AND_INTEGRITY_GATES",
        "original_authorization": _file_record(ORIGINAL_AUTHORIZATION_PATH),
        "budget_amendment_c": _file_record(AMENDMENT_PATH),
        "amended_request_registry": _file_record(REGISTRY_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "step5a_manifest_hash": "ec869c52c223d460a086a2aeb19265777761a9b9296fbe012f96f62bdf174706",
        "attempt1_manifest_hash": "27f9826516160ef7e60a42d444158b5a62bf8d666acf7adde454783b9ec54402",
        "attempt2_manifest_hash": "1c6eb28ab2e02dfe3c840244edea1af1c9fec0a92537a8e13879c1f6ef503648",
        "acquisition_tool_sha256": _sha256(Path(__file__)),
        "quote_tool_sha256": _sha256(Path(quote_tool.__file__)),
        "mbo_normalizer_sha256": _sha256(Path(mbo_normalizer.__file__)),
        "mbp10_normalizer_sha256": _sha256(Path(mbp10_normalizer.__file__)),
        "sdk_version": sdk_version,
        "package_versions": package_versions,
        "available_credits_usd_from_user_portal_evidence": AVAILABLE_CREDITS_USD,
        "card_charge_permitted": False,
        "maximum_combined_charge_usd": MAXIMUM_COMBINED_CHARGE_USD,
        "minimum_free_storage_bytes": MINIMUM_FREE_STORAGE_BYTES,
        "free_storage_bytes_at_preflight": free_storage,
        "instrument_metadata": instrument_metadata,
        "fresh_estimates": estimates,
        "pre_submission_gates": gates,
        "submission_intent_recorded_at_utc": intent_time,
        "requests": intent_rows,
        "batch_jobs_submitted": 0,
        "data_downloaded": False,
        "market_values_human_or_model_inspected": False,
        "features_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_PREFLIGHT_PASS",
                "request_count": len(intent_rows),
                "fresh_combined_estimate_usd": combined_cost,
                "authorized_cap_usd": MAXIMUM_COMBINED_CHARGE_USD,
                "free_storage_bytes": free_storage,
                "minimum_free_storage_bytes": MINIMUM_FREE_STORAGE_BYTES,
                "available_credits_usd": AVAILABLE_CREDITS_USD,
                "estimated_credit_headroom_usd": AVAILABLE_CREDITS_USD - combined_cost,
                "card_charge_permitted": False,
                "batch_jobs_submitted": 0,
                "data_downloaded": False,
            },
            sort_keys=True,
        )
    )


def _submit(
    client: Any,
    output: Path,
    acquisition_path: Path,
    acquisition: dict[str, Any],
    context: dict[str, Any],
) -> None:
    if not all(acquisition["pre_submission_gates"].values()):
        raise RuntimeError("Sealed pre-submission gates did not pass")
    if (
        float(acquisition["fresh_estimates"]["combined_totals"]["cost_usd"])
        > MAXIMUM_COMBINED_CHARGE_USD
    ):
        raise RuntimeError("Fresh estimate exceeds authorized cap")
    if int(shutil.disk_usage(output.parent).free) < MINIMUM_FREE_STORAGE_BYTES:
        raise RuntimeError("Free storage fell below the frozen threshold")
    if acquisition["acquisition_tool_sha256"] != _sha256(Path(__file__)):
        raise ValueError("Acquisition tool changed after preflight")

    recorded = sum(int(bool(row.get("job_id"))) for row in acquisition["requests"])
    if recorded == 0:
        registry = context["registry"]
        instrument_metadata = _instrument_metadata(client, registry)
        estimates = _interval_estimates(client, registry, "immediate_pre_submission_recheck")
        refreshed_requests = _requests(registry, instrument_metadata)
        frozen_by_id = {row["request_id"]: row for row in acquisition["requests"]}
        quote_by_id = {row["request_id"]: row for row in estimates["quotes"]}
        request_exact = len(refreshed_requests) == EXPECTED_REQUEST_COUNT
        for refreshed in refreshed_requests:
            frozen = frozen_by_id.get(refreshed["request_id"])
            quote = quote_by_id.get(refreshed["request_id"])
            if frozen is None or quote is None:
                request_exact = False
                continue
            request_exact = request_exact and all(
                refreshed[key] == frozen[key]
                for key in (
                    "request_id",
                    "interval_id",
                    "selected_month_week_id",
                    "schema",
                    "selected_dates",
                    "selected_date_rows",
                    "expected_instrument_ids",
                    "expected_instrument_id_by_date",
                    "request",
                    "request_fingerprint",
                )
            )
            metadata_request = {
                key: frozen["request"][key]
                for key in ("dataset", "symbols", "schema", "stype_in", "start", "end")
            }
            request_exact = request_exact and quote["request"] == metadata_request
        combined = float(estimates["combined_totals"]["cost_usd"])
        packages = {
            name: importlib_metadata.version(name) for name in EXPECTED_PACKAGES
        }
        recheck_gates = {
            "predecessor_and_budget_c_seals_still_valid": bool(
                context["predecessor_seals_valid"]
            ),
            "all_80_requests_exactly_unchanged": request_exact,
            "all_188_symbology_mappings_exactly_unchanged": (
                instrument_metadata == acquisition["instrument_metadata"]
            ),
            "all_188_dates_still_map_exactly_once": instrument_metadata[
                "all_selected_dates_map_exactly_once"
            ],
            "normalization_packages_still_exact": packages == EXPECTED_PACKAGES,
            "destination_free_storage_still_sufficient": (
                int(shutil.disk_usage(output.parent).free)
                >= MINIMUM_FREE_STORAGE_BYTES
            ),
            "all_fresh_costs_finite_and_nonnegative": all(
                math.isfinite(float(row["cost_usd"]))
                and float(row["cost_usd"]) >= 0
                for row in estimates["quotes"]
            ),
            "all_fresh_counts_and_sizes_positive": all(
                int(row["record_count"]) > 0 and int(row["billable_size"]) > 0
                for row in estimates["quotes"]
            ),
            "complete_amended_estimate_at_or_below_credit_cap": (
                math.isfinite(combined)
                and combined <= AVAILABLE_CREDITS_USD
                and combined <= MAXIMUM_COMBINED_CHARGE_USD
            ),
            "card_charge_not_required_or_permitted": combined <= AVAILABLE_CREDITS_USD,
            "no_job_previously_submitted_under_this_intent": recorded == 0,
        }
        recheck = {
            "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_SUBMISSION_RECHECK_V0_1",
            "checked_at_utc": _now(),
            "classification": "METADATA_AND_SYMBOLOGY_ONLY",
            "instrument_metadata": instrument_metadata,
            "estimates": estimates,
            "free_storage_bytes": int(shutil.disk_usage(output.parent).free),
            "available_credits_usd_from_user_portal_evidence": AVAILABLE_CREDITS_USD,
            "estimated_credit_headroom_usd": AVAILABLE_CREDITS_USD - combined,
            "card_charge_permitted": False,
            "gates": recheck_gates,
            "market_values_or_outcomes_accessed": False,
            "batch_jobs_submitted_at_recheck": 0,
        }
        recheck["recheck_hash"] = _canonical_hash(recheck)
        acquisition["submission_recheck"] = recheck
        acquisition["status"] = (
            "IMMEDIATE_SUBMISSION_RECHECK_PASS"
            if all(recheck_gates.values())
            else "STOP_IMMEDIATE_SUBMISSION_RECHECK_GATE"
        )
        for row in acquisition["requests"]:
            row["submission_quote"] = quote_by_id.get(row["request_id"])
        _write_json_atomic(acquisition_path, acquisition)
        if not all(recheck_gates.values()):
            raise RuntimeError(
                f"Step 5B Budget C immediate submission recheck failed: {recheck_gates}"
            )
        print(
            json.dumps(
                {
                    "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_IMMEDIATE_RECHECK_PASS",
                    "request_count": EXPECTED_REQUEST_COUNT,
                    "fresh_combined_estimate_usd": combined,
                    "available_credits_usd": AVAILABLE_CREDITS_USD,
                    "estimated_credit_headroom_usd": AVAILABLE_CREDITS_USD - combined,
                    "card_charge_permitted": False,
                    "market_values_accessed": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    elif not acquisition.get("submission_recheck") or not all(
        acquisition["submission_recheck"]["gates"].values()
    ):
        raise RuntimeError("Submission cannot resume without the passing sealed recheck")

    for row in acquisition["requests"]:
        if row.get("job_id"):
            continue
        matches = _matching_jobs(
            client,
            row["request"],
            since=acquisition["submission_intent_recorded_at_utc"],
        )
        if len(matches) > 1:
            raise RuntimeError(f"Multiple matching jobs for {row['request_id']}")
        if matches:
            response = matches[0]
            mode = "RECOVERED_EXISTING_JOB"
        else:
            response, mode = _submit_once_or_recover(
                client,
                row["request"],
                since=acquisition["submission_intent_recorded_at_utc"],
            )
        row["job_id"] = _job_id(response)
        row["submission_mode"] = mode
        row["submission_response"] = response
        row["submitted_or_recovered_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        acquisition["batch_jobs_submitted"] = sum(
            int(bool(item.get("job_id"))) for item in acquisition["requests"]
        )
        acquisition["status"] = "BATCH_SUBMISSION_IN_PROGRESS"
        _write_json_atomic(acquisition_path, acquisition)
        print(
            json.dumps(
                {
                    "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_JOB_RECORDED",
                    "request_id": row["request_id"],
                    "job_id": row["job_id"],
                    "submission_mode": mode,
                    "jobs_recorded": acquisition["batch_jobs_submitted"],
                    "maximum_jobs": EXPECTED_REQUEST_COUNT,
                    "card_charge_permitted": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if acquisition["batch_jobs_submitted"] != EXPECTED_REQUEST_COUNT:
        raise RuntimeError("Not all 80 jobs were recorded")
    acquisition["status"] = "ALL_BATCH_JOBS_RECORDED"
    acquisition["all_jobs_recorded_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_json_atomic(acquisition_path, acquisition)


def _status(client: Any, acquisition_path: Path, acquisition: dict[str, Any]) -> None:
    states: dict[str, int] = {}
    known_cost = 0.0
    for row in acquisition["requests"]:
        if not row.get("job_id"):
            raise RuntimeError(f"Missing job ID: {row['request_id']}")
        details = _json_safe(
            _retry(
                "batch.get_job_details",
                lambda row=row: client.batch.get_job_details(str(row["job_id"])),
            )
        )
        row["job_details"] = details
        row["last_status_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        state = str(details.get("state", "unknown")).lower()
        states[state] = states.get(state, 0) + 1
        if details.get("cost_usd") is not None:
            known_cost += float(details["cost_usd"])
    acquisition["job_state_counts"] = states
    acquisition["known_actual_cost_usd"] = known_cost
    acquisition["last_status_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    all_done = states == {"done": EXPECTED_REQUEST_COUNT}
    acquisition["status"] = "ALL_BATCH_JOBS_DONE" if all_done else "BATCH_JOBS_PENDING"
    _write_json_atomic(acquisition_path, acquisition)
    if known_cost > MAXIMUM_COMBINED_CHARGE_USD:
        raise RuntimeError("Known aggregate batch cost exceeds authorization")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_BATCH_STATUS",
                "job_state_counts": states,
                "known_actual_cost_usd": known_cost,
                "authorized_cap_usd": MAXIMUM_COMBINED_CHARGE_USD,
                "all_done": all_done,
                "estimated_remaining_credits_usd": AVAILABLE_CREDITS_USD - known_cost,
                "card_charge_permitted": False,
                "market_values_accessed": False,
            },
            sort_keys=True,
        )
    )


def _download(
    client: Any,
    output: Path,
    acquisition_path: Path,
    acquisition: dict[str, Any],
) -> None:
    _status(client, acquisition_path, acquisition)
    acquisition = _load_acquisition(acquisition_path)
    if acquisition.get("job_state_counts") != {"done": EXPECTED_REQUEST_COUNT}:
        raise RuntimeError("All 80 batch jobs must be done before download")
    if float(acquisition.get("known_actual_cost_usd", 0.0)) > MAXIMUM_COMBINED_CHARGE_USD:
        raise RuntimeError("Actual cost exceeds authorization")
    for row in acquisition["requests"]:
        if row.get("local_files"):
            continue
        job_id = str(row["job_id"])
        request_dir_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", row["request_id"])
        requests_root = output / "requests"
        requests_root.mkdir(parents=True, exist_ok=True)
        job_dir = requests_root / request_dir_name
        staging = output / f".downloading-{request_dir_name}-{job_id}"
        if job_dir.exists():
            raise FileExistsError(
                f"Downloaded directory exists without a recorded seal: {job_dir}"
            )
        staging.mkdir(parents=True, exist_ok=True)
        remote_files = [
            _json_safe(item)
            for item in _retry(
                "batch.list_files",
                lambda job_id=job_id: list(client.batch.list_files(job_id)),
            )
        ]
        staging_job_dir = staging / job_id
        staging_job_dir.mkdir(parents=True, exist_ok=True)
        for remote in remote_files:
            filename = str(remote["filename"])
            if Path(filename).name != filename:
                raise ValueError(f"Unsafe provider filename: {filename}")
            target = staging_job_dir / filename
            expected_size = int(remote["size"])
            expected_hash = str(remote["hash"]).removeprefix("sha256:")
            if target.exists() and (
                target.stat().st_size != expected_size
                or _sha256(target) != expected_hash
            ):
                target.unlink()
            if not target.exists():
                _retry(
                    "batch.download_file",
                    lambda job_id=job_id, staging=staging, filename=filename: client.batch.download(
                        job_id=job_id,
                        output_dir=staging,
                        filename_to_download=filename,
                    ),
                    attempts=3,
                )
            if (
                not target.is_file()
                or target.stat().st_size != expected_size
                or _sha256(target) != expected_hash
            ):
                raise ValueError(
                    f"Downloaded file does not match provider inventory: {filename}"
                )
        staged_files = sorted(path for path in staging.rglob("*") if path.is_file())
        staged_names = sorted(path.name for path in staged_files)
        remote_names = sorted(str(item["filename"]) for item in remote_files)
        if not staged_files or staged_names != remote_names:
            raise RuntimeError(
                f"Downloaded inventory differs from provider inventory for {row['request_id']}"
            )
        os.replace(staging, job_dir)
        local_files = [
            _file_record(path)
            for path in sorted(path for path in job_dir.rglob("*") if path.is_file())
        ]
        if not local_files:
            raise RuntimeError(f"No files downloaded for {row['request_id']}")
        row["remote_files"] = remote_files
        row["local_files"] = local_files
        row["download_directory"] = str(job_dir.resolve())
        row["downloaded_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        acquisition["status"] = "DOWNLOAD_IN_PROGRESS"
        acquisition["data_downloaded"] = True
        _write_json_atomic(acquisition_path, acquisition)
        print(
            json.dumps(
                {
                    "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_REQUEST_DOWNLOADED",
                    "request_id": row["request_id"],
                    "job_id": job_id,
                    "files": len(local_files),
                    "downloaded_bytes": sum(int(item["bytes"]) for item in local_files),
                    "market_values_inspected": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    acquisition["status"] = "ALL_RAW_SOURCES_DOWNLOADED_AND_HASHED"
    acquisition["all_downloads_completed_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_json_atomic(acquisition_path, acquisition)


def _normalize_all(
    output: Path,
    acquisition_path: Path,
    acquisition: dict[str, Any],
) -> None:
    if acquisition.get("status") not in {
        "ALL_RAW_SOURCES_DOWNLOADED_AND_HASHED",
        "NORMALIZATION_IN_PROGRESS",
    }:
        raise RuntimeError("All raw sources must be downloaded before normalization")
    for row in acquisition["requests"]:
        if row.get("normalization"):
            continue
        job_dir = Path(row["download_directory"])
        raw_files = sorted(
            path
            for path in job_dir.rglob("*")
            if path.is_file()
            and (path.name.endswith(".dbn") or path.name.endswith(".dbn.zst"))
        )
        if not raw_files:
            raise RuntimeError(f"No DBN source for {row['request_id']}")
        expected_hashes = {
            str(Path(item["path"]).resolve()): item["sha256"]
            for item in row["local_files"]
        }
        for raw in raw_files:
            if expected_hashes.get(str(raw.resolve())) != _sha256(raw):
                raise ValueError(f"Raw source hash mismatch: {raw}")
        normalized_dir = job_dir / "normalized"
        if normalized_dir.exists():
            raise FileExistsError(f"Normalized directory already exists: {normalized_dir}")
        temporary = Path(
            tempfile.mkdtemp(prefix=".step5b-budget-c-normalizing-", dir=job_dir)
        )
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", row["interval_id"])
        suffix = "mbo" if row["schema"] == "mbo" else "mbp10"
        parquet = temporary / f"gc_v_0_{safe_name}_{suffix}.parquet"
        expected_records = int(_authoritative_quote(row)["record_count"])
        expected_instrument_ids = {
            int(value) for value in row["expected_instrument_ids"]
        }
        original_request: dict[str, Any]
        if row["schema"] == "mbo":
            original_request = mbo_normalizer.REQUEST
            mbo_normalizer.REQUEST = dict(row["request"])
            try:
                base_quality = mbo_normalizer._normalize_dbn(
                    raw_files,
                    parquet_path=parquet,
                    expected_instrument_ids=expected_instrument_ids,
                    expected_record_count=expected_records,
                )
            finally:
                mbo_normalizer.REQUEST = original_request
        else:
            original_request = mbp10_normalizer.REQUEST
            mbp10_normalizer.REQUEST = dict(row["request"])
            try:
                base_quality = mbp10_normalizer._normalize_dbn(
                    raw_files,
                    parquet_path=parquet,
                    expected_instrument_ids=expected_instrument_ids,
                    expected_record_count=expected_records,
                )
            finally:
                mbp10_normalizer.REQUEST = original_request

        base_quality["upstream_engineering_classification_preserved_as_provenance"] = (
            base_quality.get("classification")
        )
        base_quality["classification"] = "RESEARCH_DEVELOPMENT_SOURCE_VALUE_BLIND"
        base_quality["research_and_validation_exclusion"] = (
            "ELIGIBILITY_DEPENDS_ON_LATER_CASE_AND_RESEARCH_GATES"
        )
        supplemental = _supplemental_validation(parquet, row, raw_files)
        formal_checks = _formal_quality_checks(base_quality, supplemental, row)
        final_parquet = normalized_dir / parquet.name
        final_lineage = normalized_dir / "lineage.json"
        final_quality = normalized_dir / "data_quality.json"
        lineage = {
            "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_LINEAGE_V0_1",
            "classification": "RESEARCH_DEVELOPMENT_SOURCE_VALUE_BLIND",
            "request_id": row["request_id"],
            "interval_id": row["interval_id"],
            "request": row["request"],
            "request_fingerprint": row["request_fingerprint"],
            "job_id": row["job_id"],
            "selected_dates": row["selected_dates"],
            "expected_instrument_ids": row["expected_instrument_ids"],
            "expected_instrument_id_by_date": row[
                "expected_instrument_id_by_date"
            ],
            "authoritative_provider_quote": _authoritative_quote(row),
            "raw_sources": [_file_record(path) for path in raw_files],
            "normalized_payload": _relocated_file_record(parquet, final_parquet),
            "normalizer_tool": _file_record(
                Path(
                    mbo_normalizer.__file__
                    if row["schema"] == "mbo"
                    else mbp10_normalizer.__file__
                )
            ),
            "source_rows_filtered_dropped_repaired_or_relabeled": False,
            "market_values_human_or_model_inspected": False,
        }
        quality = {
            "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_DATA_QUALITY_V0_1",
            "classification": "VALUE_BLIND_SOURCE_INTEGRITY",
            "request_id": row["request_id"],
            "schema": row["schema"],
            "base_normalizer_quality": base_quality,
            "supplemental_validation": supplemental,
            "formal_checks": formal_checks,
            "quality_gate": "PASS" if all(formal_checks.values()) else "FAIL",
            "market_values_reported_or_inspected": False,
            "features_calculated": False,
            "signals_calculated": False,
            "outcomes_accessed": False,
        }
        _write_json_atomic(temporary / "lineage.json", lineage)
        _write_json_atomic(temporary / "data_quality.json", quality)
        seal = {
            "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_SOURCE_SEAL_V0_1",
            "classification": "RESEARCH_DEVELOPMENT_SOURCE_VALUE_BLIND",
            "request_id": row["request_id"],
            "quality_gate": quality["quality_gate"],
            "raw_sources": lineage["raw_sources"],
            "normalized_payload": _relocated_file_record(parquet, final_parquet),
            "lineage": _relocated_file_record(
                temporary / "lineage.json", final_lineage
            ),
            "data_quality": _relocated_file_record(
                temporary / "data_quality.json", final_quality
            ),
        }
        seal["seal_hash"] = _canonical_hash(seal)
        _write_json_atomic(temporary / "seal.json", seal)
        os.replace(temporary, normalized_dir)
        row["normalization"] = {
            "normalized_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "quality_gate": quality["quality_gate"],
            "normalized_payload": _file_record(normalized_dir / parquet.name),
            "lineage": _file_record(normalized_dir / "lineage.json"),
            "data_quality": _file_record(normalized_dir / "data_quality.json"),
            "seal": _file_record(normalized_dir / "seal.json"),
            "seal_hash": seal["seal_hash"],
        }
        acquisition["status"] = "NORMALIZATION_IN_PROGRESS"
        _write_json_atomic(acquisition_path, acquisition)
        print(
            json.dumps(
                {
                    "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_REQUEST_NORMALIZED",
                    "request_id": row["request_id"],
                    "normalized_records": supplemental["record_count"],
                    "quality_gate": quality["quality_gate"],
                    "daily_snapshot_records": supplemental[
                        "pre_daily_start_event_rows"
                    ],
                    "snapshot_semantic_violations": supplemental[
                        "pre_daily_start_snapshot_semantic_violations"
                    ],
                    "adjacent_exact_duplicate_records": supplemental["adjacent_exact_duplicate_records"],
                    "complete_prediction_windows": supplemental[
                        "complete_prediction_window_count"
                    ],
                    "documented_unavailable_prediction_windows": supplemental[
                        "documented_unavailable_prediction_window_count"
                    ],
                    "market_values_reported": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    acquisition["status"] = "ALL_SOURCES_NORMALIZED_HASHED_AND_SEALED"
    acquisition["all_normalizations_completed_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_json_atomic(acquisition_path, acquisition)


def _supplemental_validation(
    parquet: Path, row: dict[str, Any], raw_files: list[Path]
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    start_ns = int(pd.Timestamp(row["request"]["start"]).value)
    end_ns = int(pd.Timestamp(row["request"]["end"]).value)
    parquet_file = pq.ParquetFile(parquet)
    total = 0
    receive_outside = 0
    event_at_or_after_end = 0
    pre_daily_start = 0
    pre_daily_start_violations = 0
    live_cross_midnight_latency_rows = 0
    bad_flag_rows = 0
    bad_flag_semantic_violations = 0
    snapshot_rows = 0
    snapshot_semantic_violations = 0
    reset_rows = 0
    unknown_action_rows = 0
    publisher_mismatches = 0
    instrument_mismatches = 0
    ordinal_regressions = 0
    source_file_order_regressions = 0
    adjacent_duplicates = 0
    prior_file: int | None = None
    prior_ordinal: int | None = None
    prior_source_row: Any | None = None
    state_counts = {
        "CONTINUOUS_MATCHING": 0,
        "MAINTENANCE": 0,
        "PRE_OPEN": 0,
    }
    day_stats = {
        item["trade_date"]: {
            "rows": 0,
            "first_receive_ns": None,
            "last_receive_ns": None,
            "instrument_mismatch_rows": 0,
        }
        for item in row["selected_date_rows"]
    }
    source_columns = [
        name
        for name in parquet_file.schema_arrow.names
        if name not in {"source_file_index", "source_row_ordinal"}
    ]
    for batch in parquet_file.iter_batches(batch_size=50_000):
        frame = batch.to_pandas()
        if frame.empty:
            continue
        count = len(frame)
        total += count
        recv_ns = frame["ts_recv"].astype("int64").to_numpy()
        event_ns = frame["ts_event"].astype("int64").to_numpy()
        flags = frame["flags"].astype("int64").to_numpy()
        actions = frame["action"].astype(str).to_numpy()
        publishers = frame["publisher_id"].astype("int64").to_numpy()
        instruments = frame["instrument_id"].astype("int64").to_numpy()
        files = frame["source_file_index"].astype("int64").to_numpy()
        ordinals = frame["source_row_ordinal"].astype("int64").to_numpy()
        receive_outside += int(((recv_ns < start_ns) | (recv_ns >= end_ns)).sum())
        event_at_or_after_end += int((event_ns >= end_ns).sum())
        day_start_ns = recv_ns - (recv_ns % 86_400_000_000_000)
        pre = (event_ns < day_start_ns) & (recv_ns == day_start_ns)
        pre_daily_start += int(pre.sum())
        live_cross_midnight_latency_rows += int(
            ((event_ns < day_start_ns) & (recv_ns > day_start_ns)).sum()
        )
        pre_violation = pre & (
            ((flags & F_SNAPSHOT) == 0)
            | (recv_ns != day_start_ns)
            | ~np.isin(actions, np.asarray(["A", "R"]))
        )
        pre_daily_start_violations += int(pre_violation.sum())
        bad = (flags & F_BAD_TS_RECV) != 0
        bad_flag_rows += int(bad.sum())
        bad_violation = bad & (
            ((flags & F_SNAPSHOT) == 0)
            | (recv_ns != day_start_ns)
            | (event_ns >= day_start_ns)
            | (event_ns > recv_ns)
            | ~np.isin(actions, np.asarray(["A", "R"]))
        )
        bad_flag_semantic_violations += int(bad_violation.sum())
        snapshot = (flags & F_SNAPSHOT) != 0
        snapshot_rows += int(snapshot.sum())
        snapshot_semantic_violations += int(
            (
                snapshot
                & (
                    (recv_ns != day_start_ns)
                    | (event_ns > recv_ns)
                    | ~np.isin(actions, np.asarray(["A", "R"]))
                )
            ).sum()
        )
        reset_rows += int((actions == "R").sum())
        unknown_action_rows += int(
            (~np.isin(actions, np.asarray(["A", "C", "M", "T", "F", "R", "N"]))).sum()
        )
        publisher_mismatches += int((publishers != 1).sum())
        for selected_date, expected_id in row[
            "expected_instrument_id_by_date"
        ].items():
            selected_start = int(pd.Timestamp(f"{selected_date}T00:00:00Z").value)
            selected_end = selected_start + 86_400_000_000_000
            date_mask = (recv_ns >= selected_start) & (recv_ns < selected_end)
            date_rows = int(date_mask.sum())
            if not date_rows:
                continue
            mismatches = int((instruments[date_mask] != int(expected_id)).sum())
            instrument_mismatches += mismatches
            stats = day_stats[selected_date]
            stats["rows"] += date_rows
            stats["instrument_mismatch_rows"] += mismatches
            first_ns = int(recv_ns[date_mask][0])
            last_ns = int(recv_ns[date_mask][-1])
            stats["first_receive_ns"] = (
                first_ns
                if stats["first_receive_ns"] is None
                else min(int(stats["first_receive_ns"]), first_ns)
            )
            stats["last_receive_ns"] = (
                last_ns
                if stats["last_receive_ns"] is None
                else max(int(stats["last_receive_ns"]), last_ns)
            )

        for index in range(count):
            file_index = int(files[index])
            ordinal = int(ordinals[index])
            if prior_file == file_index:
                ordinal_regressions += int(
                    prior_ordinal is not None and ordinal <= prior_ordinal
                )
            else:
                if prior_file is not None and file_index <= prior_file:
                    source_file_order_regressions += 1
                if ordinal != 1:
                    ordinal_regressions += 1
            prior_file = file_index
            prior_ordinal = ordinal

        classified = np.zeros(count, dtype=bool)
        for selected_date in row["selected_dates"]:
            selected = date.fromisoformat(selected_date)
            selected_start = int(pd.Timestamp(f"{selected_date}T00:00:00Z").value)
            selected_end = selected_start + 86_400_000_000_000
            chicago = ZoneInfo("America/Chicago")
            maintenance_at = datetime.combine(
                selected, time(16, 0), chicago
            ).astimezone(UTC)
            preopen_at = datetime.combine(
                selected, time(16, 45), chicago
            ).astimezone(UTC)
            reopen_at = datetime.combine(
                selected, time(17, 0), chicago
            ).astimezone(UTC)
            maintenance_start = int(pd.Timestamp(maintenance_at).value)
            preopen_start = int(pd.Timestamp(preopen_at).value)
            reopen = int(pd.Timestamp(reopen_at).value)
            in_date = (recv_ns >= selected_start) & (recv_ns < selected_end)
            maintenance = in_date & (recv_ns >= maintenance_start) & (
                recv_ns < preopen_start
            )
            preopen = in_date & (recv_ns >= preopen_start) & (recv_ns < reopen)
            continuous = in_date & ~maintenance & ~preopen
            state_counts["MAINTENANCE"] += int(maintenance.sum())
            state_counts["PRE_OPEN"] += int(preopen.sum())
            state_counts["CONTINUOUS_MATCHING"] += int(continuous.sum())
            classified |= in_date
        receive_outside += int((~classified).sum())

        duplicate_frame = frame[source_columns]
        hashes = pd.util.hash_pandas_object(duplicate_frame, index=False).to_numpy()
        if prior_source_row is not None and duplicate_frame.iloc[0].equals(prior_source_row):
            adjacent_duplicates += 1
        candidates = np.flatnonzero(hashes[1:] == hashes[:-1]) + 1
        for index in candidates.tolist():
            if duplicate_frame.iloc[index].equals(duplicate_frame.iloc[index - 1]):
                adjacent_duplicates += 1
        prior_source_row = duplicate_frame.iloc[-1].copy()

    prediction_windows: list[dict[str, Any]] = []
    for selected in row["selected_date_rows"]:
        stats = day_stats[selected["trade_date"]]
        for session, cutoff_key in (
            ("LONDON", "london_decision_at_utc"),
            ("NEW_YORK", "new_york_decision_at_utc"),
        ):
            cutoff_ns = int(pd.Timestamp(selected[cutoff_key]).value)
            start_15m_ns = cutoff_ns - 900_000_000_000
            first_ns = stats["first_receive_ns"]
            last_ns = stats["last_receive_ns"]
            if stats["rows"] == 0:
                disposition = "UNAVAILABLE_DOCUMENTED"
            elif (
                first_ns is not None
                and last_ns is not None
                and int(first_ns) <= start_15m_ns
                and int(last_ns) >= cutoff_ns
            ):
                disposition = "COMPLETE"
            else:
                disposition = "INCOMPLETE_SOURCE"
            prediction_windows.append(
                {
                    "trade_date": selected["trade_date"],
                    "session": session,
                    "cutoff_at_utc": selected[cutoff_key],
                    "required_lookback_seconds": 900,
                    "coverage_disposition": disposition,
                    "market_values_accessed_or_reported": False,
                }
            )

    raw_file_dates: list[str] = []
    unclassified_raw_dbn_files: list[str] = []
    for source in raw_files:
        match = re.search(r"(?<!\d)(20\d{6})(?!\d)", source.name)
        if match:
            raw_file_dates.append(
                datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
            )
        else:
            unclassified_raw_dbn_files.append(source.name)
    expected_dates = sorted(row["selected_dates"])
    complete_windows = sum(
        item["coverage_disposition"] == "COMPLETE" for item in prediction_windows
    )
    unavailable_windows = sum(
        item["coverage_disposition"] == "UNAVAILABLE_DOCUMENTED"
        for item in prediction_windows
    )
    incomplete_windows = sum(
        item["coverage_disposition"] == "INCOMPLETE_SOURCE"
        for item in prediction_windows
    )
    return {
        "record_count": total,
        "receive_timestamp_outside_request_rows": receive_outside,
        "event_timestamp_at_or_after_end_rows": event_at_or_after_end,
        "pre_daily_start_event_rows": pre_daily_start,
        "pre_daily_start_snapshot_semantic_violations": pre_daily_start_violations,
        "live_cross_midnight_latency_rows": live_cross_midnight_latency_rows,
        "bad_ts_recv_flag_rows": bad_flag_rows,
        "bad_ts_recv_snapshot_semantic_violations": bad_flag_semantic_violations,
        "snapshot_rows": snapshot_rows,
        "snapshot_semantic_violations": snapshot_semantic_violations,
        "reset_rows_preserved": reset_rows,
        "unknown_action_rows": unknown_action_rows,
        "publisher_id_mismatch_rows": publisher_mismatches,
        "instrument_id_mismatch_rows": instrument_mismatches,
        "source_ordinal_regressions": ordinal_regressions,
        "source_file_order_regressions": source_file_order_regressions,
        "market_state_row_counts": state_counts,
        "market_state_classified_rows": sum(state_counts.values()),
        "adjacent_exact_duplicate_records": adjacent_duplicates,
        "duplicate_scan_rows": total,
        "raw_dbn_file_count": len(raw_files),
        "raw_dbn_file_dates": raw_file_dates,
        "unclassified_raw_dbn_files": unclassified_raw_dbn_files,
        "raw_dbn_dates_match_selected_dates_exactly": (
            sorted(raw_file_dates) == expected_dates
            and not unclassified_raw_dbn_files
        ),
        "selected_date_technical_coverage": [
            {
                "trade_date": key,
                "record_count": int(value["rows"]),
                "instrument_mismatch_rows": int(
                    value["instrument_mismatch_rows"]
                ),
                "coverage_disposition": (
                    "AVAILABLE" if int(value["rows"]) > 0 else "UNAVAILABLE_DOCUMENTED"
                ),
            }
            for key, value in day_stats.items()
        ],
        "prediction_window_coverage": prediction_windows,
        "complete_prediction_window_count": complete_windows,
        "documented_unavailable_prediction_window_count": unavailable_windows,
        "incomplete_prediction_window_count": incomplete_windows,
        "expected_prediction_window_count": len(row["selected_dates"]) * 2,
        "market_values_reported_or_inspected": False,
    }


def _formal_quality_checks(
    base_quality: dict[str, Any],
    supplemental: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, bool]:
    checks = base_quality["checks"]
    expected_records = int(_authoritative_quote(row)["record_count"])
    shared = {
        "provider_record_count_matches_normalized_rows": (
            supplemental["record_count"] == expected_records
        ),
        "parquet_record_count_matches_normalization": bool(
            checks.get("parquet_record_count_matches_normalization")
        ),
        "required_columns_present_and_nonnull": bool(
            checks.get("required_fields_complete")
        ),
        "publisher_id_exactly_1": supplemental["publisher_id_mismatch_rows"] == 0,
        "instrument_id_matches_frozen_mapping": (
            supplemental["instrument_id_mismatch_rows"] == 0
            and bool(checks.get("instrument_lineage_complete"))
        ),
        "receive_timestamps_inside_frozen_utc_day": (
            supplemental["receive_timestamp_outside_request_rows"] == 0
        ),
        "receive_timestamps_nondecreasing": bool(
            checks.get("receive_timestamps_nondecreasing")
        ),
        "source_ordinals_strictly_increasing": supplemental["source_ordinal_regressions"] == 0,
        "source_files_processed_once_in_original_order": supplemental[
            "source_file_order_regressions"
        ]
        == 0,
        "event_timestamps_before_request_end": supplemental["event_timestamp_at_or_after_end_rows"] == 0,
        "pre_daily_start_rows_follow_snapshot_semantics": supplemental[
            "pre_daily_start_snapshot_semantic_violations"
        ]
        == 0,
        "bad_ts_recv_rows_follow_snapshot_semantics": supplemental["bad_ts_recv_snapshot_semantic_violations"] == 0,
        "all_snapshot_rows_follow_frozen_semantics": supplemental[
            "snapshot_semantic_violations"
        ]
        == 0,
        "all_action_codes_follow_frozen_registry": supplemental[
            "unknown_action_rows"
        ]
        == 0,
        "every_row_classified_once_into_dst_aware_market_state": (
            supplemental["market_state_classified_rows"] == supplemental["record_count"]
        ),
        "adjacent_duplicate_scan_complete": supplemental["duplicate_scan_rows"] == supplemental["record_count"],
        "daily_split_dbn_coverage_exact": supplemental[
            "raw_dbn_dates_match_selected_dates_exactly"
        ],
        "all_prediction_windows_complete_or_documented_unknown": supplemental[
            "incomplete_prediction_window_count"
        ]
        == 0,
        "all_prediction_windows_receive_a_disposition": len(
            supplemental["prediction_window_coverage"]
        )
        == supplemental["expected_prediction_window_count"],
        "no_source_filter_drop_repair_relabel_or_market_value_inspection": True,
    }
    if row["schema"] == "mbo":
        shared.update(
            {
                "DBN_schema_matches_mbo": bool(checks.get("schema_is_mbo")),
                "sizes_nonnegative": bool(checks.get("sizes_nonnegative")),
                "receive_does_not_precede_event": bool(checks.get("no_receive_timestamp_precedes_event_timestamp")),
            }
        )
    else:
        shared.update(
            {
                "DBN_schema_and_rtype_match_mbp10": bool(checks.get("schema_is_mbp10")),
                "sizes_and_book_counts_nonnegative": bool(checks.get("sizes_and_order_counts_nonnegative")),
                "empty_level_coupling_valid": bool(checks.get("empty_levels_use_frozen_canonical_values")),
                "no_internal_level_gaps": bool(checks.get("no_internal_level_gaps")),
                "bid_levels_strictly_descending": bool(checks.get("bid_levels_strictly_descending")),
                "ask_levels_strictly_ascending": bool(checks.get("ask_levels_strictly_ascending")),
                "no_maybe_bad_book_flags": bool(checks.get("no_maybe_bad_book_flags")),
            }
        )
    return shared


def _seal(
    output: Path,
    acquisition_path: Path,
    artifacts: Path,
    context: dict[str, Any],
) -> None:
    acquisition = _load_acquisition(acquisition_path)
    if artifacts.exists():
        raise FileExistsError("Refusing to overwrite Step 5B Budget C artifacts")
    request_count = len(acquisition["requests"])
    jobs_done = sum(
        int(str(row.get("job_details", {}).get("state", "")).lower() == "done")
        for row in acquisition["requests"]
    )
    downloaded = sum(
        int(bool(row.get("local_files"))) for row in acquisition["requests"]
    )
    normalized = sum(
        int(bool(row.get("normalization"))) for row in acquisition["requests"]
    )
    quality_pass = sum(
        int(row.get("normalization", {}).get("quality_gate") == "PASS")
        for row in acquisition["requests"]
    )
    actual_cost = math.fsum(
        float(row.get("job_details", {}).get("cost_usd") or 0.0)
        for row in acquisition["requests"]
    )
    recheck = acquisition.get("submission_recheck", {})
    selected_dates = sorted(
        {day for row in acquisition["requests"] for day in row["selected_dates"]}
    )
    acquisition_gates = {
        "all_predecessor_and_budget_c_seals_valid": bool(
            context["predecessor_seals_valid"]
        ),
        "all_initial_pre_submission_gates_passed": all(
            acquisition["pre_submission_gates"].values()
        ),
        "immediate_pre_submission_recheck_passed": bool(recheck)
        and all(recheck.get("gates", {}).values()),
        "exactly_80_frozen_jobs_recorded": (
            request_count == EXPECTED_REQUEST_COUNT
            and acquisition["batch_jobs_submitted"] == EXPECTED_REQUEST_COUNT
        ),
        "all_80_jobs_done": jobs_done == EXPECTED_REQUEST_COUNT,
        "actual_combined_cost_at_or_below_credit_only_cap": (
            actual_cost <= MAXIMUM_COMBINED_CHARGE_USD
            and actual_cost <= AVAILABLE_CREDITS_USD
        ),
        "card_charge_not_authorized_or_required_by_frozen_budget": (
            not acquisition.get("card_charge_permitted", True)
            and float(recheck.get("estimates", {}).get("combined_totals", {}).get("cost_usd", math.inf))
            <= AVAILABLE_CREDITS_USD
        ),
        "all_80_raw_sources_downloaded_and_hashed": (
            downloaded == EXPECTED_REQUEST_COUNT
        ),
        "all_80_sources_normalized_hashed_and_sealed": (
            normalized == EXPECTED_REQUEST_COUNT
        ),
        "all_80_value_blind_source_integrity_gates_pass": (
            quality_pass == EXPECTED_REQUEST_COUNT
        ),
        "exactly_188_amended_dates_covered": (
            len(selected_dates) == EXPECTED_DATE_COUNT
            and selected_dates[0] == "2021-11-08"
            and selected_dates[-1] == "2024-12-13"
        ),
        "no_prohibited_research_or_execution_work": all(
            not acquisition[key]
            for key in (
                "market_values_human_or_model_inspected",
                "features_calculated",
                "signals_calculated",
                "outcomes_accessed",
                "execution_optimized",
                "pnl_calculated",
            )
        ),
    }
    if not all(
        acquisition_gates[key]
        for key in (
            "all_predecessor_and_budget_c_seals_valid",
            "all_initial_pre_submission_gates_passed",
            "immediate_pre_submission_recheck_passed",
            "actual_combined_cost_at_or_below_credit_only_cap",
            "card_charge_not_authorized_or_required_by_frozen_budget",
        )
    ):
        status = "FAIL_STEP_5B_BUDGET_C_AUTHORIZATION_OR_COST_GATE"
    elif not all(
        acquisition_gates[key]
        for key in (
            "exactly_80_frozen_jobs_recorded",
            "all_80_jobs_done",
            "all_80_raw_sources_downloaded_and_hashed",
            "all_80_sources_normalized_hashed_and_sealed",
            "exactly_188_amended_dates_covered",
        )
    ):
        status = "FAIL_STEP_5B_BUDGET_C_ACQUISITION_COMPLETENESS"
    elif not all(acquisition_gates.values()):
        status = "FAIL_STEP_5B_BUDGET_C_SOURCE_INTEGRITY"
    else:
        status = "PASS_STEP_5B_BUDGET_C_SOURCE_INTEGRITY_CERTIFICATION"

    source_summary: list[dict[str, Any]] = []
    all_file_records: list[dict[str, Any]] = []
    total_provider_records = 0
    total_raw_bytes = 0
    total_normalized_bytes = 0
    for row in acquisition["requests"]:
        normalization = row.get("normalization", {})
        raw_records = list(row.get("local_files", []))
        normalized_records = [
            normalization[key]
            for key in ("normalized_payload", "lineage", "data_quality", "seal")
            if key in normalization
        ]
        for record in [*raw_records, *normalized_records]:
            _verify_file_record(record)
        all_file_records.extend(raw_records)
        all_file_records.extend(normalized_records)
        provider_records = int(_authoritative_quote(row)["record_count"])
        raw_bytes = sum(int(item["bytes"]) for item in raw_records)
        normalized_bytes = int(
            normalization.get("normalized_payload", {}).get("bytes", 0)
        )
        total_provider_records += provider_records
        total_raw_bytes += raw_bytes
        total_normalized_bytes += normalized_bytes
        source_summary.append(
            {
                "request_id": row["request_id"],
                "interval_id": row["interval_id"],
                "schema": row["schema"],
                "selected_date_count": len(row["selected_dates"]),
                "first_selected_date": row["selected_dates"][0],
                "last_selected_date": row["selected_dates"][-1],
                "job_id": row.get("job_id"),
                "actual_cost_usd": float(
                    row.get("job_details", {}).get("cost_usd") or 0.0
                ),
                "provider_record_count": provider_records,
                "raw_file_count": len(raw_records),
                "raw_bytes": raw_bytes,
                "normalized_bytes": normalized_bytes,
                "quality_gate": normalization.get("quality_gate", "MISSING"),
                "normalized_payload_sha256": normalization.get(
                    "normalized_payload", {}
                ).get("sha256"),
                "source_seal_hash": normalization.get("seal_hash"),
            }
        )

    acquisition["status"] = "SEALED"
    acquisition["actual_combined_cost_usd"] = actual_cost
    acquisition["estimated_credits_remaining_usd"] = AVAILABLE_CREDITS_USD - actual_cost
    acquisition["card_charge_permitted"] = False
    acquisition["sealed_at_utc"] = _now()
    _write_json_atomic(acquisition_path, acquisition)

    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_VERDICT_V0_1",
        "status": status,
        "formal_pass": status
        == "PASS_STEP_5B_BUDGET_C_SOURCE_INTEGRITY_CERTIFICATION",
        "classification": "RESEARCH_DEVELOPMENT_SOURCE_ACQUISITION_VALUE_BLIND",
        "research_credit": "SOURCE_ELIGIBLE_FOR_LATER_FROZEN_DISCOVERY_ONLY",
        "validation_credit": "NONE",
        "all_prior_verdicts_and_seals_preserved": True,
        "removed_months_only": ["2021-08", "2021-09", "2021-10"],
        "selected_monthly_weeks": 38,
        "selected_dates": EXPECTED_DATE_COUNT,
        "first_selected_date": selected_dates[0],
        "last_selected_date": selected_dates[-1],
        "request_count": request_count,
        "jobs_done": jobs_done,
        "sources_downloaded": downloaded,
        "sources_normalized": normalized,
        "quality_pass_count": quality_pass,
        "initial_fresh_estimate_usd": acquisition["fresh_estimates"][
            "combined_totals"
        ]["cost_usd"],
        "immediate_pre_submission_estimate_usd": recheck.get("estimates", {})
        .get("combined_totals", {})
        .get("cost_usd"),
        "actual_combined_cost_usd": actual_cost,
        "available_credits_usd_from_user_portal_evidence": AVAILABLE_CREDITS_USD,
        "estimated_credits_remaining_usd": AVAILABLE_CREDITS_USD - actual_cost,
        "authorized_credit_only_cap_usd": MAXIMUM_COMBINED_CHARGE_USD,
        "card_charge_permitted": False,
        "card_charge_verified_by_provider_api": False,
        "card_charge_safety_basis": "The immediately rechecked full estimate and actual aggregate job cost did not exceed the frozen observed credit balance; no card charge was authorized.",
        "total_provider_records": total_provider_records,
        "total_raw_bytes": total_raw_bytes,
        "total_normalized_bytes": total_normalized_bytes,
        "acquisition_gates": acquisition_gates,
        "passed_gates": sum(acquisition_gates.values()),
        "total_gates": len(acquisition_gates),
        "source_summary": source_summary,
        "market_values_or_outcomes_accessed_or_reported": False,
        "features_calculated": False,
        "relationships_or_candidates_calculated": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "trades_or_pnl_calculated": False,
        "completion_policy": "Stop after acquisition and value-blind source-integrity certification; Step 5C requires separate authorization.",
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    artifacts.mkdir(parents=True, exist_ok=False)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    verdict_path = artifacts / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_text_atomic(REPORT_PATH, _render_report(verdict))
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": _now(),
        "classification": verdict["classification"],
        "research_credit": verdict["research_credit"],
        "validation_credit": "NONE",
        "records": {
            "original_authorization": _file_record(ORIGINAL_AUTHORIZATION_PATH),
            "budget_amendment_c": _file_record(AMENDMENT_PATH),
            "amended_request_registry": _file_record(REGISTRY_PATH),
            "budget_c_freeze": _file_record(FREEZE_PATH),
            "step5a_manifest": _file_record(STEP5A_MANIFEST_PATH),
            "attempt1_manifest": _file_record(ATTEMPT1_MANIFEST_PATH),
            "attempt2_manifest": _file_record(ATTEMPT2_MANIFEST_PATH),
            "attempt2_preflight": _file_record(ATTEMPT2_PREFLIGHT_PATH),
            "acquisition_manifest": _file_record(acquisition_path),
            "acquisition_tool": _file_record(Path(__file__)),
            "quote_tool": _file_record(Path(quote_tool.__file__)),
            "mbo_normalizer": _file_record(Path(mbo_normalizer.__file__)),
            "mbp10_normalizer": _file_record(Path(mbp10_normalizer.__file__)),
        },
        "source_and_normalized_files": all_file_records,
        "artifacts": [_file_record(verdict_path), _file_record(REPORT_PATH)],
        "verdict_hash": verdict["verdict_hash"],
        "all_prior_verdicts_and_seals_preserved": True,
        "card_charge_permitted": False,
        "market_values_or_outcomes_accessed_or_reported": False,
        "features_calculated": False,
        "relationships_or_candidates_calculated": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "trades_or_pnl_calculated": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(artifacts / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_SEALED",
                "status": status,
                "formal_pass": verdict["formal_pass"],
                "request_count": request_count,
                "selected_dates": EXPECTED_DATE_COUNT,
                "quality_pass_count": quality_pass,
                "actual_combined_cost_usd": actual_cost,
                "estimated_credits_remaining_usd": AVAILABLE_CREDITS_USD
                - actual_cost,
                "card_charge_permitted": False,
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "features_calculated": False,
            },
            sort_keys=True,
        )
    )


def _render_report(verdict: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# GC Microstructure Step 5B Budget Amendment C",
            "",
            "## Formal verdict",
            "",
            f"`{verdict['status']}`",
            "",
            "## Credit-only acquisition",
            "",
            f"- Frozen available-credit evidence: `${verdict['available_credits_usd_from_user_portal_evidence']:.2f}`.",
            f"- Immediate pre-submission estimate: `${verdict['immediate_pre_submission_estimate_usd']:.6f}`.",
            f"- Actual aggregate data cost: `${verdict['actual_combined_cost_usd']:.6f}`.",
            f"- Estimated credits remaining: `${verdict['estimated_credits_remaining_usd']:.6f}`.",
            "- Card charge was not authorized. The provider API does not independently expose a card-charge receipt; the safety gate required the complete estimate and aggregate job cost to fit within the observed credits.",
            "",
            "## Certified scope",
            "",
            f"- Development dates: `{verdict['selected_dates']}` from `{verdict['first_selected_date']}` through `{verdict['last_selected_date']}`.",
            f"- Provider requests: `{verdict['request_count']}` (MBO and MBP-10 retained).",
            f"- Completed jobs: `{verdict['jobs_done']}`.",
            f"- Downloaded, hashed sources: `{verdict['sources_downloaded']}`.",
            f"- Normalized, hashed sources: `{verdict['sources_normalized']}`.",
            f"- Passing value-blind source-integrity gates: `{verdict['quality_pass_count']}`.",
            "",
            "August, September, and October 2021 were removed as complete outcome-blind monthly blocks. Every prior verdict and seal remains unchanged.",
            "",
            "Raw provider payloads were preserved unchanged. No source row was filtered, dropped, repaired, substituted, deduplicated, or relabeled.",
            "",
            "No market value, price, depth, order-flow value, outcome, relationship, candidate, signal, feature, execution result, trade, PnL, R multiple, or account return was inspected or reported.",
            "",
            "Step 5B stops here. Any feature calculation or conditional-edge discovery requires a separately authorized Step 5C.",
            "",
        ]
    )


def _verify_seal(artifacts: Path) -> None:
    _verified_context()
    manifest = _read_json(artifacts / "manifest.json")
    verdict = _read_json(artifacts / "verdict.json")
    if manifest["manifest_hash"] != _canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    ):
        raise ValueError("Step 5B Budget C manifest canonical hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash(
        {key: value for key, value in verdict.items() if key != "verdict_hash"}
    ):
        raise ValueError("Step 5B Budget C verdict canonical hash mismatch")
    for record in manifest["records"].values():
        _verify_file_record(record)
    for record in manifest["source_and_normalized_files"]:
        _verify_file_record(record)
    for record in manifest["artifacts"]:
        _verify_file_record(record)
    if manifest["status"] != verdict["status"]:
        raise ValueError("Step 5B Budget C manifest/verdict status mismatch")
    if manifest["verdict_hash"] != verdict["verdict_hash"]:
        raise ValueError("Step 5B Budget C verdict binding changed")
    if not manifest["all_prior_verdicts_and_seals_preserved"]:
        raise ValueError("Prior-verdict preservation declaration changed")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "source_and_normalized_files_verified": len(
                    manifest["source_and_normalized_files"]
                ),
                "all_prior_verdicts_and_seals_preserved": True,
                "card_charge_permitted": False,
                "market_values_or_outcomes_accessed_or_reported": False,
                "features_calculated": False,
                "trades_or_pnl_calculated": False,
            },
            sort_keys=True,
        )
    )


def _verified_context() -> dict[str, Any]:
    expected_files = {
        AMENDMENT_PATH: EXPECTED_AMENDMENT_SHA256,
        REGISTRY_PATH: EXPECTED_REGISTRY_SHA256,
        ORIGINAL_AUTHORIZATION_PATH: EXPECTED_ORIGINAL_AUTHORIZATION_SHA256,
        STEP5A_MANIFEST_PATH: EXPECTED_STEP5A_MANIFEST_SHA256,
        ATTEMPT1_MANIFEST_PATH: EXPECTED_ATTEMPT1_MANIFEST_SHA256,
        ATTEMPT2_MANIFEST_PATH: EXPECTED_ATTEMPT2_MANIFEST_SHA256,
        ATTEMPT2_PREFLIGHT_PATH: EXPECTED_ATTEMPT2_PREFLIGHT_SHA256,
        Path(quote_tool.__file__): EXPECTED_QUOTE_TOOL_SHA256,
        Path(mbo_normalizer.__file__): EXPECTED_MBO_NORMALIZER_SHA256,
        Path(mbp10_normalizer.__file__): EXPECTED_MBP10_NORMALIZER_SHA256,
    }
    for path, expected in expected_files.items():
        if not path.exists() or _sha256(path) != expected:
            raise ValueError(f"Frozen predecessor or dependency changed: {path}")
    if not FREEZE_PATH.exists():
        raise FileNotFoundError("Step 5B Budget C freeze receipt is missing")
    amendment = _read_json(AMENDMENT_PATH)
    registry = _read_json(REGISTRY_PATH)
    freeze = _read_json(FREEZE_PATH)
    original_authorization = _read_json(ORIGINAL_AUTHORIZATION_PATH)
    step5a = _read_json(STEP5A_MANIFEST_PATH)
    attempt1 = _read_json(ATTEMPT1_MANIFEST_PATH)
    attempt2 = _read_json(ATTEMPT2_MANIFEST_PATH)
    attempt2_preflight = _read_json(ATTEMPT2_PREFLIGHT_PATH)
    if amendment["amendment_hash"] != _canonical_hash(
        {key: value for key, value in amendment.items() if key != "amendment_hash"}
    ):
        raise ValueError("Budget Amendment C canonical hash mismatch")
    if registry["registry_hash"] != _canonical_hash(
        {key: value for key, value in registry.items() if key != "registry_hash"}
    ):
        raise ValueError("Budget C request registry canonical hash mismatch")
    if freeze["freeze_hash"] != _canonical_hash(
        {key: value for key, value in freeze.items() if key != "freeze_hash"}
    ):
        raise ValueError("Budget C freeze canonical hash mismatch")
    for record in freeze["records"].values():
        _verify_repo_record(record)
    internal_checks = (
        step5a.get("manifest_hash")
        == "ec869c52c223d460a086a2aeb19265777761a9b9296fbe012f96f62bdf174706"
        and step5a.get("status") == "PASS_STEP_5A_METADATA_READINESS"
        and attempt1.get("manifest_hash")
        == "27f9826516160ef7e60a42d444158b5a62bf8d666acf7adde454783b9ec54402"
        and attempt1.get("status") == "STOP_STEP_5B_PRE_SUBMISSION_STORAGE_GATE"
        and attempt2.get("manifest_hash")
        == "1c6eb28ab2e02dfe3c840244edea1af1c9fec0a92537a8e13879c1f6ef503648"
        and attempt2.get("status") == "STOP_STEP_5B_PRE_SUBMISSION_CREDIT_GATE"
        and attempt2_preflight.get("preflight_hash")
        == "a52a66ac24e5fd1d9682e2f35e016454b3e915ccb114027f05046297576302ec"
    )
    if not internal_checks:
        raise ValueError("A predecessor internal verdict or seal changed")
    if (
        freeze["amendment_hash"] != amendment["amendment_hash"]
        or freeze["registry_hash"] != registry["registry_hash"]
        or freeze["selected_dates"] != EXPECTED_DATE_COUNT
        or freeze["provider_requests"] != EXPECTED_REQUEST_COUNT
        or freeze["maximum_combined_estimate_usd"]
        != MAXIMUM_COMBINED_CHARGE_USD
        or freeze["available_credits_usd"] != AVAILABLE_CREDITS_USD
        or freeze["minimum_destination_free_bytes"]
        != MINIMUM_FREE_STORAGE_BYTES
        or freeze["card_charge_permitted"]
    ):
        raise ValueError("Budget C freeze differs from the executable policy")
    if (
        original_authorization["classification"]
        != "ACQUISITION_AND_VALUE_BLIND_SOURCE_INTEGRITY_ONLY"
        or original_authorization["minimum_usable_destination_bytes"]
        != MINIMUM_FREE_STORAGE_BYTES
        or "using 2025 or 2026 values" not in original_authorization["prohibited"]
    ):
        raise ValueError("Original Step 5B restrictions changed")
    _assert_registry_matches_code(registry)
    return {
        "amendment": amendment,
        "registry": registry,
        "freeze": freeze,
        "original_authorization": original_authorization,
        "step5a": step5a,
        "attempt1": attempt1,
        "attempt2": attempt2,
        "attempt2_preflight": attempt2_preflight,
        "predecessor_seals_valid": True,
    }


def _assert_registry_matches_code(registry: dict[str, Any]) -> None:
    dates = registry["selected_dates"]
    intervals = registry["request_intervals"]
    requests = registry["provider_quote_requests"]
    if (
        registry["provider_quote_request_count"] != EXPECTED_REQUEST_COUNT
        or registry["daily_coverage_check_count"] != EXPECTED_DATE_COUNT * 2
        or registry["sample_counts"]
        != {
            "daily_coverage_checks": 376,
            "provider_requests": 80,
            "removed_dates": 15,
            "removed_monthly_weeks": 3,
            "removed_provider_requests": 6,
            "request_intervals": 40,
            "selected_dates": 188,
            "selected_monthly_weeks": 38,
        }
        or len(dates) != EXPECTED_DATE_COUNT
        or len(intervals) != 40
        or len(requests) != EXPECTED_REQUEST_COUNT
        or dates[0]["trade_date"] != "2021-11-08"
        or dates[-1]["trade_date"] != "2024-12-13"
        or registry["selection_amendment"]["removed_months"]
        != ["2021-08", "2021-09", "2021-10"]
        or registry["card_charge_permitted"]
        or registry["maximum_total_cost_usd"] != MAXIMUM_COMBINED_CHARGE_USD
    ):
        raise ValueError("Amended request registry cardinality or policy changed")
    if len({row["trade_date"] for row in dates}) != EXPECTED_DATE_COUNT:
        raise ValueError("Amended selected dates are not unique")
    interval_by_id = {row["interval_id"]: row for row in intervals}
    for index in range(0, len(requests), 2):
        pair = requests[index : index + 2]
        if [row["schema"] for row in pair] != ["mbo", "mbp-10"]:
            raise ValueError("Every amended interval must retain MBO and MBP-10")
        if pair[0]["interval_id"] != pair[1]["interval_id"]:
            raise ValueError("Schema pair interval mismatch")
        interval = interval_by_id[pair[0]["interval_id"]]
        for row in pair:
            request = row["request"]
            if (
                request
                != {
                    "dataset": "GLBX.MDP3",
                    "symbols": ["GC.v.0"],
                    "schema": row["schema"],
                    "stype_in": "continuous",
                    "start": interval["start"],
                    "end": interval["end"],
                }
            ):
                raise ValueError(f"Frozen request changed: {row['request_id']}")


def _verify_repo_record(record: dict[str, Any]) -> None:
    path = REPO_ROOT / record["path"]
    if (
        not path.exists()
        or path.stat().st_size != int(record["bytes"])
        or _sha256(path) != record["sha256"]
    ):
        raise ValueError(f"Frozen repository record changed: {path}")


def _authoritative_quote(row: dict[str, Any]) -> dict[str, Any]:
    quote = row.get("submission_quote") or row.get("fresh_quote")
    if not quote:
        raise ValueError(f"No provider quote is sealed for {row['request_id']}")
    return quote


def _relocated_file_record(source: Path, destination: Path) -> dict[str, Any]:
    return {
        "path": str(destination.resolve()),
        "bytes": source.stat().st_size,
        "sha256": _sha256(source),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _submit_once_or_recover(
    client: Any, request: dict[str, Any], *, since: str
) -> tuple[dict[str, Any], str]:
    """Never blindly retry an ambiguous paid submission."""
    try:
        return _json_safe(client.batch.submit_job(**request)), "NEW_JOB_SUBMITTED"
    except Exception:
        sleep_time.sleep(3.0)
        matches = _matching_jobs(client, request, since=since)
        if len(matches) == 1:
            return matches[0], "RECOVERED_AFTER_AMBIGUOUS_SUBMISSION_RESPONSE"
        if len(matches) > 1:
            raise RuntimeError("Ambiguous submission produced duplicate matching jobs")
        raise RuntimeError(
            "Batch submission response was ambiguous and no matching job is yet visible; "
            "stopped without resubmission to prevent a duplicate paid job"
        )


def _matching_jobs(client: Any, request: dict[str, Any], *, since: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    jobs = _retry(
        "batch.list_jobs",
        lambda: list(client.batch.list_jobs(since=since)),
    )
    for raw in jobs:
        job = _json_safe(raw)
        symbols = job.get("symbols")
        normalized_symbols = (
            [item.strip() for item in str(symbols).split(",")]
            if isinstance(symbols, str)
            else list(symbols or [])
        )
        if (
            job.get("dataset") == request["dataset"]
            and normalized_symbols == request["symbols"]
            and job.get("schema") == request["schema"]
            and job.get("stype_in") == request["stype_in"]
            and str(job.get("start", "")).startswith(request["start"][:19])
            and str(job.get("end", "")).startswith(request["end"][:19])
        ):
            matches.append(job)
    return matches


def _load_acquisition(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError("Step 5B Budget C acquisition manifest does not exist")
    value = _read_json(path)
    if (
        value.get("original_authorization", {}).get("sha256")
        != EXPECTED_ORIGINAL_AUTHORIZATION_SHA256
        or value.get("budget_amendment_c", {}).get("sha256")
        != EXPECTED_AMENDMENT_SHA256
        or value.get("amended_request_registry", {}).get("sha256")
        != EXPECTED_REGISTRY_SHA256
        or value.get("freeze_receipt", {}).get("sha256") != _sha256(FREEZE_PATH)
        or value.get("acquisition_tool_sha256") != _sha256(Path(__file__))
        or value.get("card_charge_permitted")
        or len(value.get("requests", [])) != EXPECTED_REQUEST_COUNT
    ):
        raise ValueError("Step 5B Budget C acquisition binding changed")
    if float(value["fresh_estimates"]["combined_totals"]["cost_usd"]) > AVAILABLE_CREDITS_USD:
        raise ValueError("Sealed acquisition estimate exceeds the credit-only cap")
    recheck = value.get("submission_recheck")
    if recheck and recheck.get("recheck_hash") != _canonical_hash(
        {key: item for key, item in recheck.items() if key != "recheck_hash"}
    ):
        raise ValueError("Immediate submission recheck hash changed")
    registry = _read_json(REGISTRY_PATH)
    frozen_requests = registry["provider_quote_requests"]
    for stored, frozen in zip(value["requests"], frozen_requests, strict=True):
        if (
            stored["request_id"] != frozen["request_id"]
            or stored["interval_id"] != frozen["interval_id"]
            or stored["schema"] != frozen["schema"]
            or {
                key: stored["request"][key]
                for key in ("dataset", "symbols", "schema", "stype_in", "start", "end")
            }
            != frozen["request"]
        ):
            raise ValueError(f"Stored acquisition request changed: {stored['request_id']}")
    return value


def _job_id(value: dict[str, Any]) -> str:
    job_id = value.get("id") or value.get("job_id")
    if not job_id:
        raise ValueError("Databento returned no batch job ID")
    return str(job_id)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


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
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


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
