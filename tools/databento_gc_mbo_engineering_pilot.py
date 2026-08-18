#!/usr/bin/env python3
"""Acquire and seal the one-day GC MBO engineering-only pilot.

This utility has a frozen request and an immutable exclusion policy. It can
submit at most one matching Databento batch job, refuses a fresh quote above
the authorized hard cap, and never calculates market signals or outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_2_authorization_v01.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "raw" / "databento_gc_mbo_engineering_pilot"
EXPECTED_SDK_VERSION = "0.82.0"
REQUEST: dict[str, Any] = {
    "dataset": "GLBX.MDP3",
    "symbols": ["GC.v.0"],
    "schema": "mbo",
    "stype_in": "continuous",
    "stype_out": "instrument_id",
    "start": "2024-01-09T00:00:00Z",
    "end": "2024-01-10T00:00:00Z",
    "encoding": "dbn",
    "compression": "zstd",
    "pretty_px": False,
    "pretty_ts": False,
    "map_symbols": False,
    "split_duration": "day",
    "split_symbols": False,
    "delivery": "download",
}
EXPECTED_CEILING_USD = 0.25
ABSOLUTE_HARD_CAP_USD = 1.0
UNDEFINED_FIXED_PRICE = 9_223_372_036_854_775_807


def main() -> None:
    args = _parser().parse_args()
    authorization = _load_and_validate_authorization(Path(args.authorization))
    output = Path(args.output_dir)
    acquisition_path = output / "acquisition_manifest.json"

    if args.action == "verify":
        _verify_seal(output, acquisition_path)
        return
    if args.action == "amend-snapshot-quality":
        _amend_snapshot_quality(output, acquisition_path)
        return

    output.mkdir(parents=True, exist_ok=True)
    key = _api_key(Path(args.env_file))
    client, sdk_version = _client(key)
    if sdk_version != EXPECTED_SDK_VERSION:
        raise RuntimeError(
            f"Databento SDK changed: expected {EXPECTED_SDK_VERSION}, got {sdk_version}"
        )

    if args.action == "estimate":
        quote = _metadata_quote(client)
        print(
            json.dumps(
                {
                    "stage": "GC_MBO_ENGINEERING_FRESH_METADATA_QUOTE",
                    **quote,
                    "expected_ceiling_usd": EXPECTED_CEILING_USD,
                    "absolute_hard_cap_usd": ABSOLUTE_HARD_CAP_USD,
                    "within_expected_ceiling": (
                        quote["estimated_cost_usd"] <= EXPECTED_CEILING_USD
                    ),
                    "within_absolute_hard_cap": (
                        quote["estimated_cost_usd"] <= ABSOLUTE_HARD_CAP_USD
                    ),
                    "batch_job_submitted": False,
                    "market_values_accessed": False,
                },
                sort_keys=True,
            )
        )
        return

    if args.action == "submit":
        acquisition = _submit_or_resume(
            client,
            output=output,
            acquisition_path=acquisition_path,
            authorization=authorization,
            sdk_version=sdk_version,
        )
        _update_status(client, acquisition_path, acquisition)
        return

    acquisition = _load_acquisition(acquisition_path)
    if args.action == "status":
        _update_status(client, acquisition_path, acquisition)
        return
    if args.action == "download":
        _download(client, output, acquisition_path, acquisition)
        return
    if args.action == "normalize":
        _normalize(client, output, acquisition_path, acquisition)
        return
    raise AssertionError(f"Unhandled action: {args.action}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "estimate",
            "submit",
            "status",
            "download",
            "normalize",
            "amend-snapshot-quality",
            "verify",
        ),
    )
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env"))
    parser.add_argument("--authorization", default=str(AUTHORIZATION_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def _load_and_validate_authorization(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    if value.get("status") != "PAID_ENGINEERING_PILOT_AUTHORIZED":
        raise ValueError("Engineering pilot is not authorized")
    if value.get("request") != REQUEST:
        raise ValueError("Authorization request does not match the frozen request")
    if value.get("cost_policy") != {
        "expected_ceiling_usd": EXPECTED_CEILING_USD,
        "absolute_hard_cap_usd": ABSOLUTE_HARD_CAP_USD,
        "refresh_quote_immediately_before_submission": True,
        "stop_if_fresh_quote_exceeds_absolute_hard_cap": True,
    }:
        raise ValueError("Authorization cost policy changed")
    policy = value.get("data_policy", {})
    required = {
        "classification": "ENGINEERING_ONLY",
        "permanently_excluded_from_relationship_discovery": True,
        "permanently_excluded_from_candidate_selection": True,
        "permanently_excluded_from_validation": True,
        "edge_discovery_permitted": False,
        "signal_testing_permitted": False,
        "execution_optimization_permitted": False,
        "market_outcome_analysis_permitted": False,
    }
    if policy != required:
        raise ValueError("Engineering-only exclusion policy changed")
    return value


def _metadata_quote(client: Any) -> dict[str, Any]:
    common = {
        "dataset": REQUEST["dataset"],
        "symbols": REQUEST["symbols"],
        "schema": REQUEST["schema"],
        "stype_in": REQUEST["stype_in"],
        "start": REQUEST["start"],
        "end": REQUEST["end"],
    }
    cost = float(client.metadata.get_cost(**common))
    records = int(client.metadata.get_record_count(**common))
    billable_size = int(client.metadata.get_billable_size(**common))
    if not math.isfinite(cost) or cost < 0 or records <= 0 or billable_size <= 0:
        raise ValueError("Databento returned invalid metadata")
    return {
        "estimated_cost_usd": cost,
        "expected_record_count": records,
        "expected_billable_size_bytes": billable_size,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _submit_or_resume(
    client: Any,
    *,
    output: Path,
    acquisition_path: Path,
    authorization: dict[str, Any],
    sdk_version: str,
) -> dict[str, Any]:
    if acquisition_path.exists():
        existing = _load_acquisition(acquisition_path)
        if existing.get("job_id"):
            print(
                json.dumps(
                    {
                        "stage": "GC_MBO_ENGINEERING_BATCH_RESUME",
                        "job_id": existing["job_id"],
                        "new_job_submitted": False,
                    },
                    sort_keys=True,
                )
            )
            return existing
    else:
        existing = None

    quote = _metadata_quote(client)
    if quote["estimated_cost_usd"] > ABSOLUTE_HARD_CAP_USD:
        raise RuntimeError(
            "Fresh estimate "
            f"${quote['estimated_cost_usd']:.12f} exceeds "
            f"${ABSOLUTE_HARD_CAP_USD:.2f} hard cap"
        )
    intent = existing or {
        "acquisition_version": "GC_MBO_ENGINEERING_ACQUISITION_V0_1",
        "status": "SUBMISSION_INTENT_RECORDED",
        "request": REQUEST,
        "request_fingerprint": _canonical_hash(REQUEST),
        "authorization_path": str(AUTHORIZATION_PATH.resolve()),
        "authorization_sha256": _sha256(AUTHORIZATION_PATH),
        "authorization_hash": _canonical_hash(authorization),
        "sdk_version": sdk_version,
        "fresh_quote": quote,
        "expected_ceiling_usd": EXPECTED_CEILING_USD,
        "absolute_hard_cap_usd": ABSOLUTE_HARD_CAP_USD,
        "fresh_quote_above_expected_ceiling": (
            quote["estimated_cost_usd"] > EXPECTED_CEILING_USD
        ),
        "submission_intent_recorded_at": datetime.now(UTC).isoformat(),
        "classification": "ENGINEERING_ONLY",
        "research_and_validation_exclusion": "PERMANENT",
        "market_values_human_or_model_inspected": False,
        "features_calculated": False,
        "outcomes_accessed": False,
    }
    _write_json_atomic(acquisition_path, intent)

    matches = _matching_jobs(
        client,
        since=str(intent["submission_intent_recorded_at"]),
    )
    if len(matches) > 1:
        raise RuntimeError("Multiple matching jobs found; refusing a new submission")
    if matches:
        response = matches[0]
        submission_mode = "RECOVERED_EXISTING_JOB"
    else:
        response = client.batch.submit_job(**REQUEST)
        submission_mode = "NEW_JOB_SUBMITTED"
    safe_response = _json_safe(response)
    job_id = _job_id(safe_response)
    intent.update(
        {
            "job_id": job_id,
            "submission_mode": submission_mode,
            "submission_response": safe_response,
            "submitted_or_recovered_at": datetime.now(UTC).isoformat(),
            "status": "BATCH_JOB_RECORDED",
        }
    )
    _write_json_atomic(acquisition_path, intent)
    print(
        json.dumps(
            {
                "stage": "GC_MBO_ENGINEERING_BATCH_JOB_RECORDED",
                "job_id": job_id,
                "submission_mode": submission_mode,
                "fresh_estimated_cost_usd": quote["estimated_cost_usd"],
                "expected_ceiling_usd": EXPECTED_CEILING_USD,
                "absolute_hard_cap_usd": ABSOLUTE_HARD_CAP_USD,
                "market_values_accessed": False,
            },
            sort_keys=True,
        )
    )
    return intent


def _matching_jobs(client: Any, *, since: str) -> list[dict[str, Any]]:
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
            job.get("dataset") == REQUEST["dataset"]
            and normalized_symbols == REQUEST["symbols"]
            and job.get("schema") == REQUEST["schema"]
            and job.get("stype_in") == REQUEST["stype_in"]
            and str(job.get("start", "")).startswith("2024-01-09T00:00:00")
            and str(job.get("end", "")).startswith("2024-01-10T00:00:00")
        ):
            matches.append(job)
    return matches


def _update_status(
    client: Any,
    acquisition_path: Path,
    acquisition: dict[str, Any],
) -> dict[str, Any]:
    details = _json_safe(client.batch.get_job_details(str(acquisition["job_id"])))
    acquisition["job_details"] = details
    acquisition["last_status_at"] = datetime.now(UTC).isoformat()
    acquisition["status"] = f"BATCH_{str(details.get('state', 'UNKNOWN')).upper()}"
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "GC_MBO_ENGINEERING_BATCH_STATUS",
                "job_id": acquisition["job_id"],
                "job_state": details.get("state", "unknown"),
                "cost_usd": details.get("cost_usd"),
                "market_values_accessed": False,
            },
            sort_keys=True,
        )
    )
    return acquisition


def _download(
    client: Any,
    output: Path,
    acquisition_path: Path,
    acquisition: dict[str, Any],
) -> None:
    acquisition = _update_status(client, acquisition_path, acquisition)
    details = acquisition["job_details"]
    if str(details.get("state", "")).lower() != "done":
        raise RuntimeError("Databento batch job is not complete")
    actual_cost = float(details.get("cost_usd") or 0.0)
    if actual_cost > ABSOLUTE_HARD_CAP_USD:
        raise RuntimeError(
            f"Job cost ${actual_cost:.12f} exceeds the authorized hard cap"
        )
    job_id = str(acquisition["job_id"])
    if acquisition.get("status") == "DOWNLOADED_AND_RAW_HASHED":
        raise RuntimeError("Raw source is already downloaded and sealed")
    remote_files = [_json_safe(item) for item in client.batch.list_files(job_id)]
    downloaded = client.batch.download(job_id=job_id, output_dir=output)
    local_files = [
        {
            "path": str(path.resolve()),
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(Path(item) for item in downloaded)
        if path.is_file()
    ]
    if not local_files:
        raise RuntimeError("Databento returned no downloaded files")
    acquisition.update(
        {
            "remote_files": remote_files,
            "local_files": local_files,
            "downloaded_at": datetime.now(UTC).isoformat(),
            "actual_cost_usd": actual_cost,
            "status": "DOWNLOADED_AND_RAW_HASHED",
            "market_values_human_or_model_inspected": False,
            "features_calculated": False,
            "outcomes_accessed": False,
        }
    )
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "GC_MBO_ENGINEERING_RAW_DOWNLOADED_AND_HASHED",
                "job_id": job_id,
                "actual_cost_usd": actual_cost,
                "downloaded_files": len(local_files),
                "downloaded_bytes": sum(int(item["bytes"]) for item in local_files),
                "market_values_human_or_model_inspected": False,
            },
            sort_keys=True,
        )
    )


def _normalize(
    client: Any,
    output: Path,
    acquisition_path: Path,
    acquisition: dict[str, Any],
) -> None:
    if acquisition.get("status") != "DOWNLOADED_AND_RAW_HASHED":
        raise RuntimeError("Raw archive has not been downloaded and sealed")
    job_dir = output / str(acquisition["job_id"])
    raw_files = sorted(
        path
        for pattern in ("*.dbn", "*.dbn.zst")
        for path in job_dir.glob(pattern)
    )
    if not raw_files:
        raise RuntimeError("No DBN source payload found")
    expected_hashes = {
        str(item["name"]): str(item["sha256"])
        for item in acquisition.get("local_files", [])
    }
    for source in raw_files:
        if expected_hashes.get(source.name) != _sha256(source):
            raise ValueError(f"Raw source hash mismatch: {source.name}")

    normalized_dir = job_dir / "normalized"
    if normalized_dir.exists():
        raise FileExistsError("Refusing to overwrite sealed normalization")
    lineage = _resolve_symbology(client)
    expected_instrument_ids = {
        int(item["instrument_id"]) for item in lineage["mappings"]
    }

    with tempfile.TemporaryDirectory(
        dir=job_dir,
        prefix=".normalized-staging-",
    ) as temporary:
        staging = Path(temporary)
        parquet_path = staging / "gc_v_0_2024_01_09_mbo.parquet"
        lineage_path = staging / "lineage.json"
        quality_path = staging / "data_quality.json"
        _write_json(lineage_path, lineage)
        quality = _normalize_dbn(
            raw_files,
            parquet_path=parquet_path,
            expected_instrument_ids=expected_instrument_ids,
            expected_record_count=int(
                acquisition["fresh_quote"]["expected_record_count"]
            ),
        )
        _write_json(quality_path, quality)
        seal: dict[str, Any] = {
            "seal_version": "GC_MBO_ENGINEERING_SEAL_V0_1",
            "sealed_at": datetime.now(UTC).isoformat(),
            "classification": "ENGINEERING_ONLY",
            "research_and_validation_exclusion": "PERMANENT",
            "request": REQUEST,
            "request_fingerprint": _canonical_hash(REQUEST),
            "authorization_sha256": _sha256(AUTHORIZATION_PATH),
            "acquisition_manifest_hash": _canonical_hash(acquisition),
            "raw_sources": [
                {
                    "path": str(source.resolve()),
                    "bytes": source.stat().st_size,
                    "sha256": _sha256(source),
                }
                for source in raw_files
            ],
            "normalized_payload": {
                "path": parquet_path.name,
                "bytes": parquet_path.stat().st_size,
                "sha256": _sha256(parquet_path),
                "contains_market_values": True,
                "human_or_model_inspected": False,
            },
            "lineage": {
                "path": lineage_path.name,
                "bytes": lineage_path.stat().st_size,
                "sha256": _sha256(lineage_path),
                "contains_market_values": False,
            },
            "data_quality": {
                "path": quality_path.name,
                "bytes": quality_path.stat().st_size,
                "sha256": _sha256(quality_path),
                "contains_directional_analysis": False,
            },
            "quality_gate": quality["quality_gate"],
            "market_values_human_or_model_inspected": False,
            "features_calculated": False,
            "outcomes_accessed": False,
        }
        seal["seal_hash"] = _canonical_hash(seal)
        _write_json(staging / "seal.json", seal)
        staging.rename(normalized_dir)

    acquisition.update(
        {
            "normalization": {
                "path": str((normalized_dir / "seal.json").resolve()),
                "sha256": _sha256(normalized_dir / "seal.json"),
                "seal_hash": seal["seal_hash"],
                "normalized_records": quality["normalized_record_count"],
                "quality_gate": quality["quality_gate"],
            },
            "status": "NORMALIZED_HASHED_AND_SEALED",
            "market_values_human_or_model_inspected": False,
            "features_calculated": False,
            "outcomes_accessed": False,
        }
    )
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "GC_MBO_ENGINEERING_NORMALIZED_HASHED_AND_SEALED",
                "job_id": acquisition["job_id"],
                "normalized_records": quality["normalized_record_count"],
                "quality_gate": quality["quality_gate"],
                "seal_hash": seal["seal_hash"],
                "market_values_human_or_model_inspected": False,
                "features_calculated": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _normalize_dbn(
    raw_files: list[Path],
    *,
    parquet_path: Path,
    expected_instrument_ids: set[int],
    expected_record_count: int,
) -> dict[str, Any]:
    import databento as db
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            ("source_file_index", pa.int16()),
            ("source_row_ordinal", pa.int64()),
            ("ts_recv", pa.timestamp("ns", tz="UTC")),
            ("ts_event", pa.timestamp("ns", tz="UTC")),
            ("rtype", pa.int16()),
            ("publisher_id", pa.int32()),
            ("instrument_id", pa.int64()),
            ("action", pa.string()),
            ("side", pa.string()),
            ("price_fixed_1e9", pa.int64()),
            ("size", pa.int64()),
            ("channel_id", pa.int32()),
            ("order_id", pa.uint64()),
            ("flags", pa.int32()),
            ("ts_in_delta", pa.int64()),
            ("sequence", pa.int64()),
        ]
    )
    writer: Any | None = None
    total_rows = 0
    first_event: pd.Timestamp | None = None
    last_event: pd.Timestamp | None = None
    first_recv: pd.Timestamp | None = None
    last_recv: pd.Timestamp | None = None
    prior_recv_ns: int | None = None
    nonmonotonic_recv = 0
    event_outside_request = 0
    receive_before_event = 0
    negative_size = 0
    null_required = 0
    undefined_price = 0
    instrument_ids: set[int] = set()
    action_codes: set[str] = set()
    side_codes: set[str] = set()
    source_summaries: list[dict[str, Any]] = []
    start = pd.Timestamp(REQUEST["start"])
    end = pd.Timestamp(REQUEST["end"])

    try:
        for file_index, source in enumerate(raw_files):
            store = db.DBNStore.from_file(source)
            if str(store.schema).lower() != REQUEST["schema"]:
                raise ValueError(f"Unexpected DBN schema in {source.name}: {store.schema}")
            source_rows = 0
            source_ordinal = 0
            for chunk in store.to_df(
                price_type="fixed",
                pretty_ts=True,
                map_symbols=False,
                count=250_000,
            ):
                frame = chunk.reset_index()
                if frame.empty:
                    continue
                if "ts_recv" not in frame.columns and "index" in frame.columns:
                    frame = frame.rename(columns={"index": "ts_recv"})
                required = {
                    "ts_recv",
                    "ts_event",
                    "rtype",
                    "publisher_id",
                    "instrument_id",
                    "action",
                    "side",
                    "price",
                    "size",
                    "channel_id",
                    "order_id",
                    "flags",
                    "ts_in_delta",
                    "sequence",
                }
                missing = required.difference(frame.columns)
                if missing:
                    raise ValueError(
                        f"DBN columns missing in {source.name}: {sorted(missing)}"
                    )
                frame["ts_recv"] = pd.to_datetime(frame["ts_recv"], utc=True)
                frame["ts_event"] = pd.to_datetime(frame["ts_event"], utc=True)
                null_required += int(frame[list(required)].isna().sum().sum())
                event_outside_request += int(
                    ((frame["ts_event"] < start) | (frame["ts_event"] >= end)).sum()
                )
                receive_before_event += int(
                    (frame["ts_recv"] < frame["ts_event"]).sum()
                )
                negative_size += int((frame["size"] < 0).sum())
                undefined_price += int(
                    (frame["price"].astype("int64") == UNDEFINED_FIXED_PRICE).sum()
                )
                recv_ns = frame["ts_recv"].astype("int64").to_numpy()
                if prior_recv_ns is not None and int(recv_ns[0]) < prior_recv_ns:
                    nonmonotonic_recv += 1
                if len(recv_ns) > 1:
                    nonmonotonic_recv += int((recv_ns[1:] < recv_ns[:-1]).sum())
                prior_recv_ns = int(recv_ns[-1])
                instrument_ids.update(
                    int(value) for value in frame["instrument_id"].unique()
                )
                action_codes.update(str(value) for value in frame["action"].unique())
                side_codes.update(str(value) for value in frame["side"].unique())
                first_event = (
                    frame["ts_event"].iloc[0] if first_event is None else first_event
                )
                last_event = frame["ts_event"].iloc[-1]
                first_recv = (
                    frame["ts_recv"].iloc[0] if first_recv is None else first_recv
                )
                last_recv = frame["ts_recv"].iloc[-1]

                count = len(frame)
                ordinals = range(source_ordinal + 1, source_ordinal + count + 1)
                table = pa.Table.from_arrays(
                    [
                        pa.array([file_index] * count, type=pa.int16()),
                        pa.array(ordinals, type=pa.int64()),
                        pa.array(frame["ts_recv"], type=schema.field("ts_recv").type),
                        pa.array(frame["ts_event"], type=schema.field("ts_event").type),
                        pa.array(frame["rtype"], type=pa.int16()),
                        pa.array(frame["publisher_id"], type=pa.int32()),
                        pa.array(frame["instrument_id"], type=pa.int64()),
                        pa.array(frame["action"].astype(str), type=pa.string()),
                        pa.array(frame["side"].astype(str), type=pa.string()),
                        pa.array(frame["price"], type=pa.int64()),
                        pa.array(frame["size"], type=pa.int64()),
                        pa.array(frame["channel_id"], type=pa.int32()),
                        pa.array(frame["order_id"], type=pa.uint64()),
                        pa.array(frame["flags"], type=pa.int32()),
                        pa.array(frame["ts_in_delta"], type=pa.int64()),
                        pa.array(frame["sequence"], type=pa.int64()),
                    ],
                    schema=schema,
                )
                if writer is None:
                    writer = pq.ParquetWriter(
                        parquet_path,
                        schema,
                        compression="zstd",
                        use_dictionary=["action", "side"],
                    )
                writer.write_table(table)
                source_ordinal += count
                source_rows += count
                total_rows += count
            source_summaries.append(
                {
                    "source_file_index": file_index,
                    "name": source.name,
                    "sha256": _sha256(source),
                    "rows": source_rows,
                }
            )
    finally:
        if writer is not None:
            writer.close()

    if total_rows == 0 or not parquet_path.is_file():
        raise ValueError("No MBO records were normalized")
    parquet_rows = pq.ParquetFile(parquet_path).metadata.num_rows
    checks = {
        "schema_is_mbo": True,
        "record_count_matches_provider_metadata": total_rows == expected_record_count,
        "parquet_record_count_matches_normalization": parquet_rows == total_rows,
        "all_events_inside_frozen_request": event_outside_request == 0,
        "receive_timestamps_nondecreasing": nonmonotonic_recv == 0,
        "no_receive_timestamp_precedes_event_timestamp": receive_before_event == 0,
        "required_fields_complete": null_required == 0,
        "sizes_nonnegative": negative_size == 0,
        "instrument_lineage_complete": (
            instrument_ids == expected_instrument_ids and bool(instrument_ids)
        ),
    }
    return {
        "quality_version": "GC_MBO_ENGINEERING_DATA_QUALITY_V0_1",
        "classification": "ENGINEERING_ONLY",
        "research_and_validation_exclusion": "PERMANENT",
        "normalized_record_count": total_rows,
        "provider_expected_record_count": expected_record_count,
        "parquet_record_count": parquet_rows,
        "first_event_timestamp": first_event.isoformat() if first_event else None,
        "last_event_timestamp": last_event.isoformat() if last_event else None,
        "first_receive_timestamp": first_recv.isoformat() if first_recv else None,
        "last_receive_timestamp": last_recv.isoformat() if last_recv else None,
        "instrument_ids": sorted(instrument_ids),
        "action_codes_present": sorted(action_codes),
        "side_codes_present": sorted(side_codes),
        "undefined_fixed_price_records": undefined_price,
        "event_timestamp_out_of_range_records": event_outside_request,
        "receive_before_event_records": receive_before_event,
        "nonmonotonic_receive_timestamp_transitions": nonmonotonic_recv,
        "negative_size_records": negative_size,
        "null_required_field_values": null_required,
        "source_summaries": source_summaries,
        "checks": checks,
        "quality_gate": "PASS" if all(checks.values()) else "FAIL",
        "book_reconstruction_performed": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
    }


def _resolve_symbology(client: Any) -> dict[str, Any]:
    response = _json_safe(
        client.symbology.resolve(
            dataset=REQUEST["dataset"],
            symbols=REQUEST["symbols"],
            stype_in="continuous",
            stype_out="instrument_id",
            start_date="2024-01-09",
            end_date="2024-01-10",
        )
    )
    intervals = list(response.get("result", {}).get("GC.v.0", []))
    if (
        response.get("status") != 0
        or response.get("partial")
        or response.get("not_found")
        or not intervals
    ):
        raise ValueError("Incomplete GC continuous-symbol resolution")
    mappings: list[dict[str, Any]] = []
    for interval in intervals:
        instrument_id = str(interval["s"])
        raw = _json_safe(
            client.symbology.resolve(
                dataset=REQUEST["dataset"],
                symbols=[instrument_id],
                stype_in="instrument_id",
                stype_out="raw_symbol",
                start_date=interval["d0"],
                end_date=interval["d1"],
            )
        )
        raw_intervals = list(raw.get("result", {}).get(instrument_id, []))
        if (
            raw.get("status") != 0
            or raw.get("partial")
            or raw.get("not_found")
            or not raw_intervals
        ):
            raise ValueError("Incomplete GC underlying-symbol resolution")
        mappings.append(
            {
                "continuous_symbol": "GC.v.0",
                "instrument_id": int(instrument_id),
                "continuous_interval": {
                    "start_date_inclusive": interval["d0"],
                    "end_date_exclusive": interval["d1"],
                },
                "raw_symbol_intervals": [
                    {
                        "start_date_inclusive": item["d0"],
                        "end_date_exclusive": item["d1"],
                        "raw_symbol": item["s"],
                    }
                    for item in raw_intervals
                ],
            }
        )
    return {
        "lineage_version": "GC_MBO_POINT_IN_TIME_SYMBOLOGY_V0_1",
        "resolved_at": datetime.now(UTC).isoformat(),
        "request": REQUEST,
        "mappings": mappings,
        "contains_market_values": False,
    }


def _amend_snapshot_quality(output: Path, acquisition_path: Path) -> None:
    """Correct the request-window gate for documented MBO UTC-day snapshots.

    The original normalized bytes and failed V0_1 seal remain immutable. This
    amendment reads only timestamps and action codes to prove that pre-start
    event timestamps belong exclusively to the synthetic snapshot received at
    the requested start.
    """
    import pandas as pd
    import pyarrow.parquet as pq

    acquisition = _load_acquisition(acquisition_path)
    if acquisition.get("status") != "NORMALIZED_HASHED_AND_SEALED":
        raise ValueError("A sealed V0_1 normalization is required")
    prior_seal_path = Path(str(acquisition["normalization"]["path"]))
    if _sha256(prior_seal_path) != acquisition["normalization"]["sha256"]:
        raise ValueError("Prior seal hash mismatch")
    prior_seal = _load_json(prior_seal_path)
    if prior_seal.get("quality_gate") != "FAIL":
        raise ValueError("Snapshot amendment is only valid for the frozen failed gate")
    base = prior_seal_path.parent
    amended_quality_path = base / "data_quality_amendment_v02.json"
    amended_seal_path = base / "seal_v02.json"
    if amended_quality_path.exists() or amended_seal_path.exists():
        raise FileExistsError("Refusing to overwrite the quality amendment")

    prior_quality_path = base / str(prior_seal["data_quality"]["path"])
    prior_quality = _load_json(prior_quality_path)
    parquet_path = base / str(prior_seal["normalized_payload"]["path"])
    if (
        _sha256(parquet_path) != prior_seal["normalized_payload"]["sha256"]
        or _sha256(prior_quality_path) != prior_seal["data_quality"]["sha256"]
    ):
        raise ValueError("Prior sealed artifacts changed")

    frame = pq.read_table(
        parquet_path,
        columns=["ts_recv", "ts_event", "action"],
    ).to_pandas()
    start = pd.Timestamp(REQUEST["start"])
    end = pd.Timestamp(REQUEST["end"])
    receive_outside = (frame["ts_recv"] < start) | (frame["ts_recv"] >= end)
    pre_start = frame["ts_event"] < start
    post_end = frame["ts_event"] >= end
    snapshot = frame.loc[pre_start, ["ts_recv", "action"]]
    snapshot_action_counts = {
        str(key): int(value)
        for key, value in snapshot["action"].value_counts().sort_index().items()
    }
    snapshot_checks = {
        "all_receive_timestamps_inside_frozen_request": int(receive_outside.sum()) == 0,
        "no_event_timestamps_at_or_after_request_end": int(post_end.sum()) == 0,
        "pre_start_events_received_exactly_at_request_start": (
            len(snapshot) > 0 and bool((snapshot["ts_recv"] == start).all())
        ),
        "snapshot_starts_with_single_book_reset": (
            str(frame.iloc[0]["action"]) == "R"
            and frame.iloc[0]["ts_recv"] == start
            and snapshot_action_counts.get("R") == 1
        ),
        "snapshot_contains_only_reset_and_add_actions": (
            set(snapshot_action_counts).issubset({"R", "A"})
        ),
    }
    corrected_checks = dict(prior_quality["checks"])
    corrected_checks.pop("all_events_inside_frozen_request", None)
    corrected_checks.update(snapshot_checks)
    quality_gate = "PASS" if all(corrected_checks.values()) else "FAIL"
    amendment: dict[str, Any] = {
        "quality_version": "GC_MBO_ENGINEERING_DATA_QUALITY_V0_2",
        "amended_at": datetime.now(UTC).isoformat(),
        "classification": "ENGINEERING_ONLY",
        "research_and_validation_exclusion": "PERMANENT",
        "amendment_type": "MBO_SNAPSHOT_TIMESTAMP_SEMANTICS_CORRECTION",
        "reason": (
            "Historical MBO includes a synthetic book snapshot received at the "
            "start of each UTC day. Resting snapshot orders retain earlier "
            "ts_event values, so the requested-window gate must use ts_recv."
        ),
        "provider_documentation": (
            "https://databento.com/docs/schemas-and-data-formats/mbo"
        ),
        "prior_quality_path": prior_quality_path.name,
        "prior_quality_sha256": _sha256(prior_quality_path),
        "prior_quality_gate": prior_quality["quality_gate"],
        "normalized_payload_changed": False,
        "normalized_payload_sha256": _sha256(parquet_path),
        "normalized_record_count": len(frame),
        "pre_start_snapshot_record_count": int(pre_start.sum()),
        "post_end_event_record_count": int(post_end.sum()),
        "receive_timestamp_out_of_range_records": int(receive_outside.sum()),
        "snapshot_action_counts": snapshot_action_counts,
        "checks": corrected_checks,
        "quality_gate": quality_gate,
        "book_reconstruction_performed": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
    }
    amendment["amendment_hash"] = _canonical_hash(amendment)
    _write_json_atomic(amended_quality_path, amendment)

    amended_seal: dict[str, Any] = {
        "seal_version": "GC_MBO_ENGINEERING_SEAL_V0_2",
        "sealed_at": datetime.now(UTC).isoformat(),
        "classification": "ENGINEERING_ONLY",
        "research_and_validation_exclusion": "PERMANENT",
        "request": REQUEST,
        "request_fingerprint": _canonical_hash(REQUEST),
        "authorization_sha256": _sha256(AUTHORIZATION_PATH),
        "acquisition_manifest_hash_before_amendment": _canonical_hash(acquisition),
        "prior_seal": {
            "path": prior_seal_path.name,
            "bytes": prior_seal_path.stat().st_size,
            "sha256": _sha256(prior_seal_path),
            "seal_hash": prior_seal["seal_hash"],
            "quality_gate": prior_seal["quality_gate"],
        },
        "raw_sources": prior_seal["raw_sources"],
        "normalized_payload": prior_seal["normalized_payload"],
        "lineage": prior_seal["lineage"],
        "prior_data_quality": {
            "path": prior_quality_path.name,
            "bytes": prior_quality_path.stat().st_size,
            "sha256": _sha256(prior_quality_path),
            "quality_gate": prior_quality["quality_gate"],
        },
        "data_quality": {
            "path": amended_quality_path.name,
            "bytes": amended_quality_path.stat().st_size,
            "sha256": _sha256(amended_quality_path),
            "amendment_hash": amendment["amendment_hash"],
            "contains_directional_analysis": False,
        },
        "quality_gate": quality_gate,
        "normalized_payload_changed": False,
        "market_values_human_or_model_inspected": False,
        "features_calculated": False,
        "outcomes_accessed": False,
    }
    amended_seal["seal_hash"] = _canonical_hash(amended_seal)
    _write_json_atomic(amended_seal_path, amended_seal)

    acquisition["prior_normalization"] = dict(acquisition["normalization"])
    acquisition["normalization"] = {
        "path": str(amended_seal_path.resolve()),
        "sha256": _sha256(amended_seal_path),
        "seal_hash": amended_seal["seal_hash"],
        "normalized_records": len(frame),
        "quality_gate": quality_gate,
        "normalized_payload_changed": False,
    }
    acquisition["quality_amendment"] = {
        "version": amendment["quality_version"],
        "reason": amendment["amendment_type"],
        "prior_quality_gate": prior_quality["quality_gate"],
        "quality_gate": quality_gate,
        "normalized_payload_changed": False,
        "market_values_human_or_model_inspected": False,
    }
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "GC_MBO_ENGINEERING_SNAPSHOT_QUALITY_AMENDED_AND_SEALED",
                "prior_quality_gate": prior_quality["quality_gate"],
                "quality_gate": quality_gate,
                "pre_start_snapshot_records": int(pre_start.sum()),
                "snapshot_action_counts": snapshot_action_counts,
                "receive_timestamp_out_of_range_records": int(
                    receive_outside.sum()
                ),
                "normalized_payload_changed": False,
                "market_values_human_or_model_inspected": False,
                "features_calculated": False,
                "outcomes_accessed": False,
                "seal_hash": amended_seal["seal_hash"],
            },
            sort_keys=True,
        )
    )


def _verify_seal(output: Path, acquisition_path: Path) -> None:
    import pyarrow.parquet as pq

    acquisition = _load_acquisition(acquisition_path)
    if acquisition.get("status") != "NORMALIZED_HASHED_AND_SEALED":
        raise ValueError("Acquisition is not in the sealed state")
    if (
        acquisition.get("classification") != "ENGINEERING_ONLY"
        or acquisition.get("research_and_validation_exclusion") != "PERMANENT"
    ):
        raise ValueError("Engineering-only exclusion is missing")
    seal_path = Path(str(acquisition["normalization"]["path"]))
    if _sha256(seal_path) != acquisition["normalization"]["sha256"]:
        raise ValueError("Seal hash mismatch")
    seal = _load_json(seal_path)
    if seal.get("seal_hash") != _canonical_hash(
        {key: value for key, value in seal.items() if key != "seal_hash"}
    ):
        raise ValueError("Canonical seal hash mismatch")
    base = seal_path.parent
    for section in ("normalized_payload", "lineage", "data_quality"):
        item = seal[section]
        path = base / str(item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"Sealed artifact mismatch: {section}")
    raw_count = 0
    for item in seal["raw_sources"]:
        path = Path(str(item["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError("Raw source seal mismatch")
        raw_count += 1
    parquet_path = base / seal["normalized_payload"]["path"]
    parquet_rows = pq.ParquetFile(parquet_path).metadata.num_rows
    expected_rows = int(acquisition["normalization"]["normalized_records"])
    if parquet_rows != expected_rows:
        raise ValueError("Sealed Parquet record count mismatch")
    print(
        json.dumps(
            {
                "stage": "GC_MBO_ENGINEERING_SEAL_VERIFIED",
                "quality_gate": seal["quality_gate"],
                "raw_files_verified": raw_count,
                "normalized_records_verified": parquet_rows,
                "classification": seal["classification"],
                "research_and_validation_exclusion": seal[
                    "research_and_validation_exclusion"
                ],
                "market_values_inspected": False,
            },
            sort_keys=True,
        )
    )


def _load_acquisition(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Acquisition manifest not found: {path}")
    value = _load_json(path)
    if value.get("request") != REQUEST:
        raise ValueError("Acquisition request fingerprint changed")
    if value.get("request_fingerprint") != _canonical_hash(REQUEST):
        raise ValueError("Acquisition request hash mismatch")
    return value


def _client(key: str) -> tuple[Any, str]:
    try:
        import databento as db
    except ModuleNotFoundError as exc:
        raise RuntimeError("Databento SDK 0.82.0 is required") from exc
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


def _job_id(value: dict[str, Any]) -> str:
    job_id = value.get("id") or value.get("job_id")
    if not job_id:
        raise ValueError("Databento returned no batch job ID")
    return str(job_id)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    _write_json(temporary, value)
    temporary.replace(path)


if __name__ == "__main__":
    main()
