#!/usr/bin/env python3
"""Acquire and seal the frozen Step 4B.2 multi-day engineering sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools import databento_gc_mbo_engineering_pilot as mbo_normalizer
from tools import databento_gc_mbp10_step3b2 as mbp10_normalizer
from tools import quote_gc_microstructure_step4b1 as quote_tool


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4b2_authorization_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4b2_freeze_v01.json"
)
AMENDMENT_A_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4b2_pre_submission_amendment_a_v01.json"
)
AMENDMENT_A_FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4b2_pre_submission_amendment_a_freeze_v01.json"
)
STEP4B1_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4b1_v01"
    / "manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "data" / "raw" / "databento_gc_multiday_engineering_v01"
)
DEFAULT_ARTIFACTS = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4b2_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_4B2_REPORT.md"

EXPECTED_AUTHORIZATION_SHA256 = (
    "db0eeb999708cd815af5064a92f8e7722013bd9396e2c321572fd0ae0e208bda"
)
EXPECTED_FREEZE_SHA256 = (
    "d7bb8167b35149d67da3882a290c700c5de8c2c47a668f2e54e00e7b2e026b61"
)
EXPECTED_AMENDMENT_A_SHA256 = (
    "c0e9bd9422c8687439f99155c6c3c31dd8fe5d85350c7e46c2ed0f3969dd5006"
)
EXPECTED_AMENDMENT_A_FREEZE_SHA256 = (
    "a10578f62ca612d0566aa0f2ab8460d37e3bc3ec4e140ef2140f230b259acd5f"
)
EXPECTED_STEP4B1_MANIFEST_HASH = (
    "d58fb44b18af6173f597b3a99feba69e68ac0a7de265151e40799cb286d69d0d"
)
EXPECTED_STEP4B1_VERDICT_HASH = (
    "95b31c2921e1aef834d36eeb7768b807ed956a2e13c837670fc68b2b4dcaa082"
)
EXPECTED_QUOTE_TOOL_SHA256 = (
    "70fcd1e5672b5e19484e5ccef6849c0595938bcb72e48bf7b4606b7acb806d95"
)
EXPECTED_MBO_NORMALIZER_SHA256 = (
    "ddb4225576c2b37370712cf7b1d20707f1aa0b91bcdbb4acf6a369bd51bc590c"
)
EXPECTED_MBP10_NORMALIZER_SHA256 = (
    "551fc9a76036739f3dc24adbe8b754e63971953614279de93bd162590e3486c5"
)
EXPECTED_SDK_VERSION = "0.82.0"
MAXIMUM_COMBINED_CHARGE_USD = 3.50
MINIMUM_FREE_STORAGE_BYTES = 21_474_836_480
F_SNAPSHOT = 1 << 5
F_BAD_TS_RECV = 1 << 3
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
    authorization = context["authorization"]
    _assert_authorization_matches_code(authorization)
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
        _submit(client, output, acquisition_path, acquisition)
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


def _requests(authorization: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for item in authorization["exact_requests_in_submission_order"]:
        request = {
            **COMMON_REQUEST,
            "schema": item["schema"],
            "start": item["start"],
            "end": item["end"],
        }
        requests.append(
            {
                "request_id": item["request_id"],
                "engineering_date": item["engineering_date"],
                "schema": item["schema"],
                "expected_instrument_id": int(item["expected_instrument_id"]),
                "dst_window_class": item["dst_window_class"],
                "request": request,
                "request_fingerprint": _canonical_hash(request),
            }
        )
    return requests


def _preflight(
    client: Any,
    sdk_version: str,
    output: Path,
    acquisition_path: Path,
    context: dict[str, Any],
) -> None:
    if output.exists() or acquisition_path.exists():
        raise FileExistsError("Refusing to overwrite an existing Step 4B.2 acquisition")
    requests = _requests(context["authorization"])
    free_storage = int(shutil.disk_usage(REPO_ROOT).free)
    instrument_metadata = quote_tool._instrument_metadata(client)
    estimates = quote_tool._metadata_estimates(client)
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
    gates = {
        "step_4b1_and_earlier_seals_valid": bool(context["predecessor_seals_valid"]),
        "databento_sdk_version_exact": sdk_version == EXPECTED_SDK_VERSION,
        "all_ten_request_fingerprints_exact": len(intent_rows) == 10,
        "continuous_symbol_intervals_and_roll_pair_match_step_4b1": bool(
            instrument_metadata["complete_and_matches_frozen_protocol"]
        ),
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
        "no_existing_incompatible_or_duplicate_intent": True,
    }
    if not all(gates.values()):
        raise RuntimeError(f"Step 4B.2 pre-submission readiness failed: {gates}")

    intent_time = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    acquisition = {
        "version": "GC_MICROSTRUCTURE_STEP_4B2_ACQUISITION_V0_1",
        "status": "PREFLIGHT_PASS_SUBMISSION_INTENT_RECORDED",
        "classification": "ENGINEERING_ONLY_MULTI_DAY_SOURCE_ACQUISITION",
        "research_or_validation_credit": "NONE",
        "authorization": _file_record(AUTHORIZATION_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "pre_submission_amendment_a": _file_record(AMENDMENT_A_PATH),
        "pre_submission_amendment_a_freeze": _file_record(
            AMENDMENT_A_FREEZE_PATH
        ),
        "step4b1_manifest_hash": EXPECTED_STEP4B1_MANIFEST_HASH,
        "acquisition_tool_sha256": _sha256(Path(__file__)),
        "quote_tool_sha256": _sha256(Path(quote_tool.__file__)),
        "mbo_normalizer_sha256": _sha256(Path(mbo_normalizer.__file__)),
        "mbp10_normalizer_sha256": _sha256(Path(mbp10_normalizer.__file__)),
        "sdk_version": sdk_version,
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
                "stage": "GC_MICROSTRUCTURE_STEP_4B2_PREFLIGHT_PASS",
                "request_count": len(intent_rows),
                "fresh_combined_estimate_usd": combined_cost,
                "authorized_cap_usd": MAXIMUM_COMBINED_CHARGE_USD,
                "free_storage_bytes": free_storage,
                "minimum_free_storage_bytes": MINIMUM_FREE_STORAGE_BYTES,
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
) -> None:
    if not all(acquisition["pre_submission_gates"].values()):
        raise RuntimeError("Sealed pre-submission gates did not pass")
    if float(acquisition["fresh_estimates"]["combined_totals"]["cost_usd"]) > MAXIMUM_COMBINED_CHARGE_USD:
        raise RuntimeError("Fresh estimate exceeds authorized cap")
    if int(shutil.disk_usage(REPO_ROOT).free) < MINIMUM_FREE_STORAGE_BYTES:
        raise RuntimeError("Free storage fell below the frozen threshold")
    if acquisition["acquisition_tool_sha256"] != _sha256(Path(__file__)):
        raise ValueError("Acquisition tool changed after preflight")

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
            response = _json_safe(client.batch.submit_job(**row["request"]))
            mode = "NEW_JOB_SUBMITTED"
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
                    "stage": "GC_MICROSTRUCTURE_STEP_4B2_JOB_RECORDED",
                    "request_id": row["request_id"],
                    "job_id": row["job_id"],
                    "submission_mode": mode,
                    "jobs_recorded": acquisition["batch_jobs_submitted"],
                    "maximum_jobs": 10,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if acquisition["batch_jobs_submitted"] != 10:
        raise RuntimeError("Not all ten jobs were recorded")
    acquisition["status"] = "ALL_BATCH_JOBS_RECORDED"
    acquisition["all_jobs_recorded_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_json_atomic(acquisition_path, acquisition)


def _status(client: Any, acquisition_path: Path, acquisition: dict[str, Any]) -> None:
    states: dict[str, int] = {}
    known_cost = 0.0
    for row in acquisition["requests"]:
        if not row.get("job_id"):
            raise RuntimeError(f"Missing job ID: {row['request_id']}")
        details = _json_safe(client.batch.get_job_details(str(row["job_id"])))
        row["job_details"] = details
        row["last_status_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        state = str(details.get("state", "unknown")).lower()
        states[state] = states.get(state, 0) + 1
        if details.get("cost_usd") is not None:
            known_cost += float(details["cost_usd"])
    acquisition["job_state_counts"] = states
    acquisition["known_actual_cost_usd"] = known_cost
    acquisition["last_status_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    acquisition["status"] = "ALL_BATCH_JOBS_DONE" if states == {"done": 10} else "BATCH_JOBS_PENDING"
    _write_json_atomic(acquisition_path, acquisition)
    if known_cost > MAXIMUM_COMBINED_CHARGE_USD:
        raise RuntimeError("Known aggregate batch cost exceeds authorization")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4B2_BATCH_STATUS",
                "job_state_counts": states,
                "known_actual_cost_usd": known_cost,
                "authorized_cap_usd": MAXIMUM_COMBINED_CHARGE_USD,
                "all_done": states == {"done": 10},
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
    if acquisition.get("job_state_counts") != {"done": 10}:
        raise RuntimeError("All ten batch jobs must be done before download")
    if float(acquisition.get("known_actual_cost_usd", 0.0)) > MAXIMUM_COMBINED_CHARGE_USD:
        raise RuntimeError("Actual cost exceeds authorization")
    for row in acquisition["requests"]:
        if row.get("local_files"):
            continue
        job_id = str(row["job_id"])
        job_dir = output / job_id
        if job_dir.exists():
            raise FileExistsError(f"Unexpected pre-existing job directory: {job_dir}")
        remote_files = [_json_safe(item) for item in client.batch.list_files(job_id)]
        downloaded = client.batch.download(job_id=job_id, output_dir=output)
        local_files = [
            _file_record(Path(item))
            for item in sorted(Path(item) for item in downloaded)
            if Path(item).is_file()
        ]
        if not local_files:
            raise RuntimeError(f"No files downloaded for {row['request_id']}")
        row["remote_files"] = remote_files
        row["local_files"] = local_files
        row["downloaded_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        acquisition["status"] = "DOWNLOAD_IN_PROGRESS"
        acquisition["data_downloaded"] = True
        _write_json_atomic(acquisition_path, acquisition)
        print(
            json.dumps(
                {
                    "stage": "GC_MICROSTRUCTURE_STEP_4B2_REQUEST_DOWNLOADED",
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
        job_dir = output / str(row["job_id"])
        raw_files = sorted(
            {
                path
                for pattern in ("*.dbn", "*.dbn.zst")
                for path in job_dir.glob(pattern)
            }
        )
        if not raw_files:
            raise RuntimeError(f"No DBN source for {row['request_id']}")
        expected_hashes = {
            Path(item["path"]).name: item["sha256"] for item in row["local_files"]
        }
        for raw in raw_files:
            if expected_hashes.get(raw.name) != _sha256(raw):
                raise ValueError(f"Raw source hash mismatch: {raw}")
        normalized_dir = job_dir / "normalized"
        if normalized_dir.exists():
            raise FileExistsError(f"Normalized directory already exists: {normalized_dir}")
        temporary = Path(tempfile.mkdtemp(prefix=".step4b2-normalizing-", dir=job_dir))
        safe_name = row["engineering_date"].replace("-", "_")
        suffix = "mbo" if row["schema"] == "mbo" else "mbp10"
        parquet = temporary / f"gc_v_0_{safe_name}_{suffix}.parquet"
        expected_records = int(row["fresh_quote"]["record_count"])
        original_request: dict[str, Any]
        if row["schema"] == "mbo":
            original_request = mbo_normalizer.REQUEST
            mbo_normalizer.REQUEST = dict(row["request"])
            try:
                base_quality = mbo_normalizer._normalize_dbn(
                    raw_files,
                    parquet_path=parquet,
                    expected_instrument_ids={int(row["expected_instrument_id"])},
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
                    expected_instrument_ids={int(row["expected_instrument_id"])},
                    expected_record_count=expected_records,
                )
            finally:
                mbp10_normalizer.REQUEST = original_request

        supplemental = _supplemental_validation(parquet, row)
        formal_checks = _formal_quality_checks(base_quality, supplemental, row)
        lineage = {
            "version": "GC_MICROSTRUCTURE_STEP_4B2_LINEAGE_V0_1",
            "request_id": row["request_id"],
            "request": row["request"],
            "request_fingerprint": row["request_fingerprint"],
            "job_id": row["job_id"],
            "expected_instrument_id": row["expected_instrument_id"],
            "dst_window_class": row["dst_window_class"],
            "raw_sources": [_file_record(path) for path in raw_files],
            "normalized_payload": _file_record(parquet),
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
            "version": "GC_MICROSTRUCTURE_STEP_4B2_DATA_QUALITY_V0_1",
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
            "version": "GC_MICROSTRUCTURE_STEP_4B2_SOURCE_SEAL_V0_1",
            "request_id": row["request_id"],
            "quality_gate": quality["quality_gate"],
            "raw_sources": lineage["raw_sources"],
            "normalized_payload": _file_record(parquet),
            "lineage": _file_record(temporary / "lineage.json"),
            "data_quality": _file_record(temporary / "data_quality.json"),
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
                    "stage": "GC_MICROSTRUCTURE_STEP_4B2_REQUEST_NORMALIZED",
                    "request_id": row["request_id"],
                    "normalized_records": supplemental["record_count"],
                    "quality_gate": quality["quality_gate"],
                    "pre_start_snapshot_records": supplemental["pre_start_event_rows"],
                    "snapshot_semantic_violations": supplemental["pre_start_snapshot_semantic_violations"],
                    "adjacent_exact_duplicate_records": supplemental["adjacent_exact_duplicate_records"],
                    "market_values_reported": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    acquisition["status"] = "ALL_SOURCES_NORMALIZED_HASHED_AND_SEALED"
    acquisition["all_normalizations_completed_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_json_atomic(acquisition_path, acquisition)


def _supplemental_validation(parquet: Path, row: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    start_ns = int(pd.Timestamp(row["request"]["start"]).value)
    end_ns = int(pd.Timestamp(row["request"]["end"]).value)
    parquet_file = pq.ParquetFile(parquet)
    total = 0
    receive_outside = 0
    event_at_or_after_end = 0
    pre_start = 0
    pre_start_violations = 0
    bad_flag_rows = 0
    bad_flag_semantic_violations = 0
    publisher_mismatches = 0
    instrument_mismatches = 0
    ordinal_regressions = 0
    adjacent_duplicates = 0
    prior_file: int | None = None
    prior_ordinal: int | None = None
    prior_source_row: Any | None = None
    state_counts = {
        "CONTINUOUS_MATCHING": 0,
        "MAINTENANCE": 0,
        "PRE_OPEN": 0,
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
        pre = event_ns < start_ns
        pre_start += int(pre.sum())
        pre_violation = pre & (
            ((flags & F_SNAPSHOT) == 0)
            | (recv_ns != start_ns)
            | ~np.isin(actions, np.asarray(["A", "R"]))
        )
        pre_start_violations += int(pre_violation.sum())
        bad = (flags & F_BAD_TS_RECV) != 0
        bad_flag_rows += int(bad.sum())
        bad_violation = bad & (
            ((flags & F_SNAPSHOT) == 0)
            | (recv_ns != start_ns)
            | (event_ns >= start_ns)
            | (event_ns > recv_ns)
            | ~np.isin(actions, np.asarray(["A", "R"]))
        )
        bad_flag_semantic_violations += int(bad_violation.sum())
        publisher_mismatches += int((publishers != 1).sum())
        instrument_mismatches += int(
            (instruments != int(row["expected_instrument_id"])).sum()
        )

        for index in range(count):
            file_index = int(files[index])
            ordinal = int(ordinals[index])
            if prior_file == file_index:
                ordinal_regressions += int(
                    prior_ordinal is not None and ordinal <= prior_ordinal
                )
            elif ordinal != 1:
                ordinal_regressions += 1
            prior_file = file_index
            prior_ordinal = ordinal

        relative = recv_ns - start_ns
        if row["dst_window_class"] == "UTC-06:00_CST":
            maintenance_start = 22 * 3_600_000_000_000
            preopen_start = maintenance_start + 45 * 60_000_000_000
            reopen = 23 * 3_600_000_000_000
        else:
            maintenance_start = 21 * 3_600_000_000_000
            preopen_start = maintenance_start + 45 * 60_000_000_000
            reopen = 22 * 3_600_000_000_000
        maintenance = (relative >= maintenance_start) & (relative < preopen_start)
        preopen = (relative >= preopen_start) & (relative < reopen)
        continuous = ~maintenance & ~preopen & (relative >= 0) & (relative < end_ns - start_ns)
        state_counts["MAINTENANCE"] += int(maintenance.sum())
        state_counts["PRE_OPEN"] += int(preopen.sum())
        state_counts["CONTINUOUS_MATCHING"] += int(continuous.sum())

        duplicate_frame = frame[source_columns]
        hashes = pd.util.hash_pandas_object(duplicate_frame, index=False).to_numpy()
        if prior_source_row is not None and duplicate_frame.iloc[0].equals(prior_source_row):
            adjacent_duplicates += 1
        candidates = np.flatnonzero(hashes[1:] == hashes[:-1]) + 1
        for index in candidates.tolist():
            if duplicate_frame.iloc[index].equals(duplicate_frame.iloc[index - 1]):
                adjacent_duplicates += 1
        prior_source_row = duplicate_frame.iloc[-1].copy()

    return {
        "record_count": total,
        "receive_timestamp_outside_request_rows": receive_outside,
        "event_timestamp_at_or_after_end_rows": event_at_or_after_end,
        "pre_start_event_rows": pre_start,
        "pre_start_snapshot_semantic_violations": pre_start_violations,
        "bad_ts_recv_flag_rows": bad_flag_rows,
        "bad_ts_recv_snapshot_semantic_violations": bad_flag_semantic_violations,
        "publisher_id_mismatch_rows": publisher_mismatches,
        "instrument_id_mismatch_rows": instrument_mismatches,
        "source_ordinal_regressions": ordinal_regressions,
        "market_state_row_counts": state_counts,
        "market_state_classified_rows": sum(state_counts.values()),
        "adjacent_exact_duplicate_records": adjacent_duplicates,
        "duplicate_scan_rows": total,
        "market_values_reported_or_inspected": False,
    }


def _formal_quality_checks(
    base_quality: dict[str, Any],
    supplemental: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, bool]:
    checks = base_quality["checks"]
    shared = {
        "provider_record_count_matches_normalized_rows": (
            supplemental["record_count"] == int(row["fresh_quote"]["record_count"])
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
        "event_timestamps_before_request_end": supplemental["event_timestamp_at_or_after_end_rows"] == 0,
        "pre_start_rows_follow_snapshot_semantics": supplemental["pre_start_snapshot_semantic_violations"] == 0,
        "bad_ts_recv_rows_follow_snapshot_semantics": supplemental["bad_ts_recv_snapshot_semantic_violations"] == 0,
        "every_row_classified_once_into_dst_aware_market_state": (
            supplemental["market_state_classified_rows"] == supplemental["record_count"]
        ),
        "adjacent_duplicate_scan_complete": supplemental["duplicate_scan_rows"] == supplemental["record_count"],
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
        raise FileExistsError("Refusing to overwrite Step 4B.2 research artifacts")
    request_count = len(acquisition["requests"])
    jobs_done = sum(
        int(str(row.get("job_details", {}).get("state", "")).lower() == "done")
        for row in acquisition["requests"]
    )
    downloaded = sum(int(bool(row.get("local_files"))) for row in acquisition["requests"])
    normalized = sum(int(bool(row.get("normalization"))) for row in acquisition["requests"])
    quality_pass = sum(
        int(row.get("normalization", {}).get("quality_gate") == "PASS")
        for row in acquisition["requests"]
    )
    actual_cost = sum(
        float(row.get("job_details", {}).get("cost_usd") or 0.0)
        for row in acquisition["requests"]
    )
    acquisition_gates = {
        "predecessor_and_authorization_seals_valid": bool(context["predecessor_seals_valid"]),
        "all_pre_submission_gates_passed": all(acquisition["pre_submission_gates"].values()),
        "exactly_ten_frozen_jobs_recorded": request_count == 10 and acquisition["batch_jobs_submitted"] == 10,
        "all_ten_jobs_done": jobs_done == 10,
        "actual_combined_cost_at_or_below_authorized_cap": actual_cost <= MAXIMUM_COMBINED_CHARGE_USD,
        "all_ten_raw_sources_downloaded_and_hashed": downloaded == 10,
        "all_ten_sources_normalized_and_sealed": normalized == 10,
        "all_ten_quality_gates_pass": quality_pass == 10,
        "no_source_repair_market_value_outcome_feature_signal_execution_or_pnl_work": all(
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
    if not acquisition_gates["predecessor_and_authorization_seals_valid"] or not acquisition_gates["all_pre_submission_gates_passed"]:
        status = "FAIL_PRE_SUBMISSION_READINESS"
    elif not all(
        acquisition_gates[key]
        for key in (
            "exactly_ten_frozen_jobs_recorded",
            "all_ten_jobs_done",
            "actual_combined_cost_at_or_below_authorized_cap",
            "all_ten_raw_sources_downloaded_and_hashed",
        )
    ):
        status = "FAIL_ACQUISITION_COMPLETENESS_OR_CAP"
    elif not all(acquisition_gates.values()):
        status = "FAIL_NORMALIZATION_OR_SOURCE_INTEGRITY"
    else:
        status = "PASS_ENGINEERING_SOURCE_ACQUISITION"

    source_summary = []
    all_file_records: list[dict[str, Any]] = []
    for row in acquisition["requests"]:
        normalization = row.get("normalization", {})
        raw_records = list(row.get("local_files", []))
        normalized_records = [
            normalization[key]
            for key in ("normalized_payload", "lineage", "data_quality", "seal")
            if key in normalization
        ]
        all_file_records.extend(raw_records)
        all_file_records.extend(normalized_records)
        source_summary.append(
            {
                "request_id": row["request_id"],
                "job_id": row.get("job_id"),
                "schema": row["schema"],
                "engineering_date": row["engineering_date"],
                "actual_cost_usd": float(row.get("job_details", {}).get("cost_usd") or 0.0),
                "provider_record_count": int(row["fresh_quote"]["record_count"]),
                "raw_file_count": len(raw_records),
                "raw_bytes": sum(int(item["bytes"]) for item in raw_records),
                "normalized_bytes": int(normalization.get("normalized_payload", {}).get("bytes", 0)),
                "quality_gate": normalization.get("quality_gate", "MISSING"),
                "normalized_payload_sha256": normalization.get("normalized_payload", {}).get("sha256"),
                "source_seal_hash": normalization.get("seal_hash"),
            }
        )
    acquisition["status"] = "SEALED"
    acquisition["actual_combined_cost_usd"] = actual_cost
    acquisition["sealed_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_json_atomic(acquisition_path, acquisition)

    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_4B2_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS_ENGINEERING_SOURCE_ACQUISITION",
        "classification": "ENGINEERING_ONLY_MULTI_DAY_SOURCE_ACQUISITION",
        "research_or_validation_credit": "NONE",
        "predecessor_step_4b1_status": "PASS_METADATA_QUOTE_READINESS",
        "predecessor_verdicts_preserved": True,
        "request_count": request_count,
        "jobs_done": jobs_done,
        "sources_downloaded": downloaded,
        "sources_normalized": normalized,
        "quality_pass_count": quality_pass,
        "fresh_estimated_combined_cost_usd": acquisition["fresh_estimates"]["combined_totals"]["cost_usd"],
        "actual_combined_cost_usd": actual_cost,
        "authorized_cap_usd": MAXIMUM_COMBINED_CHARGE_USD,
        "acquisition_gates": acquisition_gates,
        "passed_gates": sum(acquisition_gates.values()),
        "total_gates": len(acquisition_gates),
        "source_summary": source_summary,
        "all_dates_permanently_engineering_only": True,
        "market_values_or_outcomes_accessed_or_reported": False,
        "features_calculated": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
        "completion_policy": "Preserve the sealed engineering sources and stop before feature calculation or research.",
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    artifacts.mkdir(parents=True, exist_ok=False)
    verdict_path = artifacts / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_text_atomic(REPORT_PATH, _render_report(verdict))
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_4B2_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "classification": "ENGINEERING_ONLY_MULTI_DAY_SOURCE_ACQUISITION",
        "research_or_validation_credit": "NONE",
        "authorization": _file_record(AUTHORIZATION_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "pre_submission_amendment_a": _file_record(AMENDMENT_A_PATH),
        "pre_submission_amendment_a_freeze": _file_record(
            AMENDMENT_A_FREEZE_PATH
        ),
        "step4b1_manifest": _file_record(STEP4B1_MANIFEST_PATH),
        "acquisition_manifest": _file_record(acquisition_path),
        "acquisition_tool": _file_record(Path(__file__)),
        "quote_tool": _file_record(Path(quote_tool.__file__)),
        "mbo_normalizer": _file_record(Path(mbo_normalizer.__file__)),
        "mbp10_normalizer": _file_record(Path(mbp10_normalizer.__file__)),
        "source_and_normalized_files": all_file_records,
        "artifacts": [_file_record(verdict_path), _file_record(REPORT_PATH)],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
        "market_values_or_outcomes_accessed_or_reported": False,
        "features_calculated": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(artifacts / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4B2_SEALED",
                "status": status,
                "formal_pass": verdict["formal_pass"],
                "request_count": request_count,
                "quality_pass_count": quality_pass,
                "actual_combined_cost_usd": actual_cost,
                "authorized_cap_usd": MAXIMUM_COMBINED_CHARGE_USD,
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "features_calculated": False,
            },
            sort_keys=True,
        )
    )


def _render_report(verdict: dict[str, Any]) -> str:
    lines = [
        "# GC Microstructure Step 4B.2 — Multi-Day Engineering Acquisition",
        "",
        "## Formal verdict",
        "",
        f"`{verdict['status']}`",
        "",
        f"- Authorized cap: `${verdict['authorized_cap_usd']:.2f}`.",
        f"- Fresh estimate: `${verdict['fresh_estimated_combined_cost_usd']:.6f}`.",
        f"- Actual combined cost: `${verdict['actual_combined_cost_usd']:.6f}`.",
        f"- Completed jobs: {verdict['jobs_done']} of {verdict['request_count']}.",
        f"- Downloaded sources: {verdict['sources_downloaded']} of {verdict['request_count']}.",
        f"- Normalized sources: {verdict['sources_normalized']} of {verdict['request_count']}.",
        f"- Passing quality gates: {verdict['quality_pass_count']} of {verdict['request_count']}.",
        "",
        "## Sealed sources",
        "",
        "| Date | Schema | Records | Raw bytes | Normalized bytes | Cost USD | Quality |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in verdict["source_summary"]:
        lines.append(
            f"| {item['engineering_date']} | {item['schema']} | {item['provider_record_count']:,} | {item['raw_bytes']:,} | {item['normalized_bytes']:,} | {item['actual_cost_usd']:.6f} | {item['quality_gate']} |"
        )
    lines.extend(
        [
            "",
            "## Restrictions honored",
            "",
            "Raw provider files were preserved byte-for-byte. No source row was filtered, dropped, repaired, substituted, or relabeled.",
            "",
            "No market value, depth, order-flow value, outcome, signal, feature, execution result, trade, PnL, R multiple, or account return was inspected or reported.",
            "",
            "All five dates remain permanently engineering-only and receive zero research or validation credit.",
            "",
        ]
    )
    return "\n".join(lines)


def _verify_seal(artifacts: Path) -> None:
    context = _verified_context()
    manifest = _read_json(artifacts / "manifest.json")
    verdict = _read_json(artifacts / "verdict.json")
    if manifest["manifest_hash"] != _canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    ):
        raise ValueError("Step 4B.2 manifest canonical hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash(
        {key: value for key, value in verdict.items() if key != "verdict_hash"}
    ):
        raise ValueError("Step 4B.2 verdict canonical hash mismatch")
    for key, expected in (
        ("authorization", EXPECTED_AUTHORIZATION_SHA256),
        ("freeze_receipt", EXPECTED_FREEZE_SHA256),
        ("pre_submission_amendment_a", EXPECTED_AMENDMENT_A_SHA256),
        (
            "pre_submission_amendment_a_freeze",
            EXPECTED_AMENDMENT_A_FREEZE_SHA256,
        ),
        ("quote_tool", EXPECTED_QUOTE_TOOL_SHA256),
        ("mbo_normalizer", EXPECTED_MBO_NORMALIZER_SHA256),
        ("mbp10_normalizer", EXPECTED_MBP10_NORMALIZER_SHA256),
    ):
        if manifest[key]["sha256"] != expected:
            raise ValueError(f"Step 4B.2 manifest {key} declaration mismatch")
        _verify_file_record(manifest[key])
    for record in manifest["source_and_normalized_files"]:
        _verify_file_record(record)
    for record in manifest["artifacts"]:
        _verify_file_record(record)
    _verify_file_record(manifest["step4b1_manifest"])
    _verify_file_record(manifest["acquisition_manifest"])
    if manifest["acquisition_tool"]["sha256"] != _sha256(Path(__file__)):
        raise ValueError("Step 4B.2 acquisition tool changed")
    if manifest["status"] != verdict["status"]:
        raise ValueError("Step 4B.2 manifest/verdict status mismatch")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4B2_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "source_and_normalized_files_verified": len(
                    manifest["source_and_normalized_files"]
                ),
                "predecessor_verdicts_preserved": manifest[
                    "predecessor_verdicts_preserved"
                ],
                "market_values_or_outcomes_accessed_or_reported": manifest[
                    "market_values_or_outcomes_accessed_or_reported"
                ],
                "features_calculated": manifest["features_calculated"],
                "signals_calculated": manifest["signals_calculated"],
                "pnl_calculated": manifest["pnl_calculated"],
                "research_or_validation_credit": manifest[
                    "research_or_validation_credit"
                ],
            },
            sort_keys=True,
        )
    )


def _verified_context() -> dict[str, Any]:
    if _sha256(AUTHORIZATION_PATH) != EXPECTED_AUTHORIZATION_SHA256:
        raise ValueError("Step 4B.2 authorization changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 4B.2 freeze receipt changed")
    if _sha256(AMENDMENT_A_PATH) != EXPECTED_AMENDMENT_A_SHA256:
        raise ValueError("Step 4B.2 pre-submission Amendment A changed")
    if (
        _sha256(AMENDMENT_A_FREEZE_PATH)
        != EXPECTED_AMENDMENT_A_FREEZE_SHA256
    ):
        raise ValueError("Step 4B.2 pre-submission Amendment A freeze changed")
    authorization = _read_json(AUTHORIZATION_PATH)
    freeze = _read_json(FREEZE_PATH)
    amendment_a = _read_json(AMENDMENT_A_PATH)
    amendment_a_freeze = _read_json(AMENDMENT_A_FREEZE_PATH)
    if freeze["authorization"]["sha256"] != EXPECTED_AUTHORIZATION_SHA256:
        raise ValueError("Step 4B.2 freeze does not bind authorization")
    if (
        amendment_a_freeze["amendment"]["sha256"]
        != EXPECTED_AMENDMENT_A_SHA256
        or amendment_a["replaces_only"]["authorization_pointer"]
        != "/normalization_contract/mbp10_book_columns"
        or amendment_a["binding_dependency"]["sha256"]
        != EXPECTED_MBP10_NORMALIZER_SHA256
    ):
        raise ValueError("Step 4B.2 Amendment A binding changed")
    if _sha256(Path(quote_tool.__file__)) != EXPECTED_QUOTE_TOOL_SHA256:
        raise ValueError("Step 4B.1 quote tool changed")
    if _sha256(Path(mbo_normalizer.__file__)) != EXPECTED_MBO_NORMALIZER_SHA256:
        raise ValueError("Frozen MBO normalization dependency changed")
    if _sha256(Path(mbp10_normalizer.__file__)) != EXPECTED_MBP10_NORMALIZER_SHA256:
        raise ValueError("Frozen MBP-10 normalization dependency changed")
    manifest = _read_json(STEP4B1_MANIFEST_PATH)
    if (
        manifest.get("manifest_hash") != EXPECTED_STEP4B1_MANIFEST_HASH
        or _canonical_hash(
            {key: value for key, value in manifest.items() if key != "manifest_hash"}
        )
        != EXPECTED_STEP4B1_MANIFEST_HASH
        or manifest.get("verdict_hash") != EXPECTED_STEP4B1_VERDICT_HASH
        or manifest.get("status") != "PASS_METADATA_QUOTE_READINESS"
    ):
        raise ValueError("Step 4B.1 predecessor changed")
    for record in manifest["artifacts"]:
        _verify_file_record(record)
    return {
        "authorization": authorization,
        "freeze": freeze,
        "amendment_a": amendment_a,
        "amendment_a_freeze": amendment_a_freeze,
        "predecessor_seals_valid": True,
    }


def _assert_authorization_matches_code(authorization: dict[str, Any]) -> None:
    if (
        authorization["authorization"]["maximum_combined_charge_usd"]
        != MAXIMUM_COMBINED_CHARGE_USD
        or authorization["authorization"]["minimum_free_storage_bytes_before_submission"]
        != MINIMUM_FREE_STORAGE_BYTES
        or authorization["authorization"]["maximum_batch_jobs"] != 10
        or authorization["common_batch_request"] != COMMON_REQUEST
        or len(authorization["exact_requests_in_submission_order"]) != 10
    ):
        raise ValueError("Step 4B.2 authorization differs from implementation")
    expected_ids = [
        "2024-01-05:mbo",
        "2024-01-05:mbp-10",
        "2024-01-11:mbo",
        "2024-01-11:mbp-10",
        "2024-01-30:mbo",
        "2024-01-30:mbp-10",
        "2024-01-31:mbo",
        "2024-01-31:mbp-10",
        "2024-03-20:mbo",
        "2024-03-20:mbp-10",
    ]
    if [item["request_id"] for item in authorization["exact_requests_in_submission_order"]] != expected_ids:
        raise ValueError("Step 4B.2 request order differs")


def _matching_jobs(client: Any, request: dict[str, Any], *, since: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for raw in client.batch.list_jobs(since=since):
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
        raise FileNotFoundError("Step 4B.2 acquisition manifest does not exist")
    value = _read_json(path)
    if value.get("authorization", {}).get("sha256") != EXPECTED_AUTHORIZATION_SHA256:
        raise ValueError("Acquisition authorization fingerprint changed")
    if value.get("freeze_receipt", {}).get("sha256") != EXPECTED_FREEZE_SHA256:
        raise ValueError("Acquisition freeze fingerprint changed")
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
