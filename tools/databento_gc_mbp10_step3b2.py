#!/usr/bin/env python3
"""Acquire, normalize, and seal the Step 3B.2 GC MBP-10 benchmark.

The request, $0.40 hard cap, engineering-only classification, and predecessor
hashes are frozen in Amendment A. Human-readable market values are never
printed. The utility is restart-safe at the batch-job boundary.
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
AMENDMENT_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3b2_amendment_a_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3b2_freeze_v01.json"
)
EXPECTED_AMENDMENT_SHA256 = (
    "dc437c6f8a6f01c9c6c04a28133d9dfed5b9eeff9f87b8f62e87f113651a2709"
)
EXPECTED_FREEZE_SHA256 = (
    "5f13cf74f8598fcb15e21202bafee9a0f42211cfffa577aff355688f5b63053f"
)
EXPECTED_SDK_VERSION = "0.82.0"
MAXIMUM_CHARGE_USD = 0.40
UNDEFINED_FIXED_PRICE = 9_223_372_036_854_775_807
F_SNAPSHOT = 1 << 5
F_MAYBE_BAD_BOOK = 1 << 2
REQUEST: dict[str, Any] = {
    "dataset": "GLBX.MDP3",
    "symbols": ["GC.v.0"],
    "schema": "mbp-10",
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
METADATA_REQUEST: dict[str, Any] = {
    key: REQUEST[key]
    for key in ("dataset", "symbols", "schema", "stype_in", "start", "end")
}
DEFAULT_OUTPUT = (
    REPO_ROOT / "data" / "raw" / "databento_gc_mbp10_engineering_benchmark"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("estimate", "submit", "status", "download", "normalize", "verify"),
    )
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env"))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    context = _verify_frozen_context()
    output = Path(args.output_dir)
    acquisition_path = output / "acquisition_manifest.json"

    if args.action == "verify":
        _verify_seal(output, acquisition_path)
        return

    key = _api_key(Path(args.env_file))
    client, sdk_version = _client(key)
    if sdk_version != EXPECTED_SDK_VERSION:
        raise RuntimeError(
            f"Databento SDK changed: expected {EXPECTED_SDK_VERSION}, "
            f"got {sdk_version}"
        )

    if args.action == "estimate":
        quote = _metadata_quote(client)
        print(
            json.dumps(
                {
                    "stage": "GC_MBP10_STEP_3B2_FRESH_METADATA_QUOTE",
                    **quote,
                    "maximum_charge_usd": MAXIMUM_CHARGE_USD,
                    "within_authorized_cap": (
                        quote["estimated_cost_usd"] <= MAXIMUM_CHARGE_USD
                    ),
                    "frozen_context": context,
                    "batch_job_submitted": False,
                    "data_downloaded": False,
                    "charge_incurred": False,
                    "mbp10_values_accessed": False,
                    "market_outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return

    output.mkdir(parents=True, exist_ok=True)
    if args.action == "submit":
        acquisition = _submit_or_resume(
            client,
            output=output,
            acquisition_path=acquisition_path,
            sdk_version=sdk_version,
            context=context,
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


def _verify_frozen_context() -> dict[str, Any]:
    if _sha256(AMENDMENT_PATH) != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Step 3B.2 Amendment A changed after freeze")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 3B.2 freeze receipt changed")
    amendment = _load_json(AMENDMENT_PATH)
    freeze = _load_json(FREEZE_PATH)
    if amendment.get("status") != "FROZEN_BEFORE_MBP10_VALUE_ACCESS":
        raise ValueError("Step 3B.2 Amendment A is not frozen")
    if amendment.get("exact_request") != REQUEST:
        raise ValueError("Acquisition request differs from Amendment A")
    if amendment.get("authorization") != {
        "maximum_charge_usd": MAXIMUM_CHARGE_USD,
        "fresh_quote_required_immediately_before_submission": True,
        "stop_before_submission_if_fresh_quote_exceeds_cap": True,
        "acquisition_permitted_only_for_exact_frozen_request": True,
    }:
        raise ValueError("Step 3B.2 cost authorization changed")
    if freeze.get("status") != "AMENDMENT_A_SEALED_BEFORE_MBP10_VALUE_ACCESS":
        raise ValueError("Step 3B.2 freeze receipt is invalid")
    if freeze.get("amendment") != {
        "path": "research_manifests/gc_microstructure_step_3b2_amendment_a_v01.json",
        "bytes": 8326,
        "sha256": EXPECTED_AMENDMENT_SHA256,
    }:
        raise ValueError("Freeze receipt does not bind Amendment A")

    predecessor = amendment["predecessor_preservation"]
    for item in predecessor["frozen_files"]:
        path = REPO_ROOT / str(item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"Frozen predecessor changed: {path}")
    step_3b1 = _load_json(
        REPO_ROOT
        / "research_artifacts"
        / "gc_microstructure_step_3b1_v01"
        / "manifest.json"
    )
    if (
        step_3b1.get("status") != "FAIL_PRE_ACQUISITION_READINESS"
        or step_3b1.get("manifest_hash")
        != predecessor["step_3b1"]["declared_manifest_hash"]
    ):
        raise ValueError("Step 3B.1 readiness FAIL was not preserved")
    return {
        "amendment_sha256": EXPECTED_AMENDMENT_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "predecessor_files_verified": len(predecessor["frozen_files"]),
        "step_3a_formal_verdict": "FAIL",
        "step_3a1_formal_verdict": "PASS",
        "step_3b1_formal_verdict": "FAIL_PRE_ACQUISITION_READINESS",
    }


def _metadata_quote(client: Any) -> dict[str, Any]:
    cost = float(client.metadata.get_cost(**METADATA_REQUEST))
    records = int(client.metadata.get_record_count(**METADATA_REQUEST))
    billable_size = int(client.metadata.get_billable_size(**METADATA_REQUEST))
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("Databento returned an invalid estimated cost")
    if records <= 0 or billable_size <= 0:
        raise ValueError("Databento returned invalid metadata counts")
    return {
        "estimated_cost_usd": cost,
        "expected_record_count": records,
        "expected_billable_size_bytes": billable_size,
        "observed_at_utc": datetime.now(UTC).isoformat(),
    }


def _submit_or_resume(
    client: Any,
    *,
    output: Path,
    acquisition_path: Path,
    sdk_version: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    if acquisition_path.exists():
        existing = _load_acquisition(acquisition_path)
        if existing.get("job_id"):
            print(
                json.dumps(
                    {
                        "stage": "GC_MBP10_STEP_3B2_BATCH_RESUME",
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
    if quote["estimated_cost_usd"] > MAXIMUM_CHARGE_USD:
        raise RuntimeError(
            f"Fresh estimate ${quote['estimated_cost_usd']:.12f} exceeds "
            f"the authorized ${MAXIMUM_CHARGE_USD:.2f} cap"
        )
    intent = existing or {
        "version": "GC_MBP10_STEP_3B2_ACQUISITION_V0_1",
        "status": "SUBMISSION_INTENT_RECORDED",
        "request": REQUEST,
        "request_fingerprint": _canonical_hash(REQUEST),
        "amendment_path": str(AMENDMENT_PATH.resolve()),
        "amendment_sha256": EXPECTED_AMENDMENT_SHA256,
        "freeze_path": str(FREEZE_PATH.resolve()),
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "frozen_context": context,
        "sdk_version": sdk_version,
        "fresh_quote": quote,
        "maximum_charge_usd": MAXIMUM_CHARGE_USD,
        "submission_intent_recorded_at": datetime.now(UTC).isoformat(),
        "classification": "ENGINEERING_ONLY",
        "research_and_validation_exclusion": "PERMANENT",
        "market_values_human_or_model_inspected": False,
        "features_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    _write_json_atomic(acquisition_path, intent)

    matches = _matching_jobs(
        client,
        since=str(intent["submission_intent_recorded_at"]),
    )
    if len(matches) > 1:
        raise RuntimeError("Multiple matching jobs found; refusing submission")
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
                "stage": "GC_MBP10_STEP_3B2_BATCH_JOB_RECORDED",
                "job_id": job_id,
                "submission_mode": submission_mode,
                "fresh_estimated_cost_usd": quote["estimated_cost_usd"],
                "maximum_charge_usd": MAXIMUM_CHARGE_USD,
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
    cost = details.get("cost_usd")
    if cost is not None and float(cost) > MAXIMUM_CHARGE_USD:
        raise RuntimeError("Recorded batch cost exceeds authorized cap")
    acquisition["job_details"] = details
    acquisition["last_status_at"] = datetime.now(UTC).isoformat()
    acquisition["status"] = f"BATCH_{str(details.get('state', 'UNKNOWN')).upper()}"
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "GC_MBP10_STEP_3B2_BATCH_STATUS",
                "job_id": acquisition["job_id"],
                "job_state": details.get("state", "unknown"),
                "cost_usd": cost,
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
    if actual_cost > MAXIMUM_CHARGE_USD:
        raise RuntimeError("Batch cost exceeds authorized cap")
    if acquisition.get("status") == "DOWNLOADED_AND_RAW_HASHED":
        raise RuntimeError("Raw source is already downloaded and sealed")
    job_id = str(acquisition["job_id"])
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
            "signals_calculated": False,
            "outcomes_accessed": False,
        }
    )
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "GC_MBP10_STEP_3B2_RAW_DOWNLOADED_AND_HASHED",
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
        raise RuntimeError("Raw source has not been downloaded and sealed")
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
        for item in acquisition["local_files"]
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
        parquet_path = staging / "gc_v_0_2024_01_09_mbp10.parquet"
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
            "version": "GC_MBP10_STEP_3B2_SOURCE_SEAL_V0_1",
            "sealed_at_utc": datetime.now(UTC).isoformat(),
            "classification": "ENGINEERING_ONLY",
            "research_and_validation_exclusion": "PERMANENT",
            "request": REQUEST,
            "request_fingerprint": _canonical_hash(REQUEST),
            "amendment_sha256": EXPECTED_AMENDMENT_SHA256,
            "freeze_sha256": EXPECTED_FREEZE_SHA256,
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
                "records": quality["normalized_record_count"],
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
                "quality_gate": quality["quality_gate"],
                "contains_directional_analysis": False,
            },
            "quality_gate": quality["quality_gate"],
            "market_values_human_or_model_inspected": False,
            "features_calculated": False,
            "signals_calculated": False,
            "outcomes_accessed": False,
            "execution_optimized": False,
            "pnl_calculated": False,
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
            "signals_calculated": False,
            "outcomes_accessed": False,
            "execution_optimized": False,
            "pnl_calculated": False,
        }
    )
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "GC_MBP10_STEP_3B2_NORMALIZED_HASHED_AND_SEALED",
                "job_id": acquisition["job_id"],
                "normalized_records": quality["normalized_record_count"],
                "quality_gate": quality["quality_gate"],
                "seal_hash": seal["seal_hash"],
                "market_values_human_or_model_inspected": False,
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

    base_fields = [
        ("source_file_index", pa.int16()),
        ("source_row_ordinal", pa.int64()),
        ("ts_recv", pa.timestamp("ns", tz="UTC")),
        ("ts_event", pa.timestamp("ns", tz="UTC")),
        ("rtype", pa.int16()),
        ("publisher_id", pa.int32()),
        ("instrument_id", pa.int64()),
        ("action", pa.string()),
        ("side", pa.string()),
        ("depth", pa.int16()),
        ("price_fixed_1e9", pa.int64()),
        ("size", pa.int64()),
        ("flags", pa.int32()),
        ("ts_in_delta", pa.int64()),
        ("sequence", pa.int64()),
    ]
    level_names: list[str] = []
    level_fields: list[tuple[str, Any]] = []
    for level in range(10):
        suffix = f"{level:02d}"
        for side in ("bid", "ask"):
            for kind, field_type in (
                ("px", pa.int64()),
                ("sz", pa.int64()),
                ("ct", pa.int64()),
            ):
                name = f"{side}_{kind}_{suffix}"
                level_names.append(name)
                level_fields.append((name, field_type))
    schema = pa.schema(base_fields + level_fields)

    writer: Any | None = None
    total_rows = 0
    prior_recv_ns: int | None = None
    nonmonotonic_recv = 0
    receive_outside_request = 0
    event_at_or_after_end = 0
    pre_start_event = 0
    invalid_pre_start_snapshot = 0
    null_required = 0
    bad_book_flags = 0
    empty_level_coupling_violations = 0
    level_gap_violations = 0
    bid_ordering_violations = 0
    ask_ordering_violations = 0
    negative_size_or_count = 0
    instrument_ids: set[int] = set()
    action_codes: set[str] = set()
    side_codes: set[str] = set()
    rtypes: set[int] = set()
    first_event: pd.Timestamp | None = None
    last_event: pd.Timestamp | None = None
    first_recv: pd.Timestamp | None = None
    last_recv: pd.Timestamp | None = None
    source_summaries: list[dict[str, Any]] = []
    start = pd.Timestamp(REQUEST["start"])
    end = pd.Timestamp(REQUEST["end"])

    try:
        for file_index, source in enumerate(raw_files):
            store = db.DBNStore.from_file(source)
            if str(store.schema).lower() != REQUEST["schema"]:
                raise ValueError(
                    f"Unexpected DBN schema in {source.name}: {store.schema}"
                )
            source_rows = 0
            source_ordinal = 0
            for chunk in store.to_df(
                price_type="fixed",
                pretty_ts=True,
                map_symbols=False,
                count=50_000,
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
                    "depth",
                    "price",
                    "size",
                    "flags",
                    "ts_in_delta",
                    "sequence",
                    *level_names,
                }
                missing = required.difference(frame.columns)
                if missing:
                    raise ValueError(
                        f"DBN columns missing in {source.name}: {sorted(missing)}"
                    )
                frame["ts_recv"] = pd.to_datetime(frame["ts_recv"], utc=True)
                frame["ts_event"] = pd.to_datetime(frame["ts_event"], utc=True)
                null_required += int(frame[list(required)].isna().sum().sum())
                receive_outside_request += int(
                    ((frame["ts_recv"] < start) | (frame["ts_recv"] >= end)).sum()
                )
                event_at_or_after_end += int((frame["ts_event"] >= end).sum())
                pre_mask = frame["ts_event"] < start
                pre_start_event += int(pre_mask.sum())
                if bool(pre_mask.any()):
                    flags = frame.loc[pre_mask, "flags"].astype("int64")
                    receives = frame.loc[pre_mask, "ts_recv"]
                    invalid_pre_start_snapshot += int(
                        (
                            ((flags & F_SNAPSHOT) == 0)
                            | (receives != start)
                        ).sum()
                    )
                flag_values = frame["flags"].astype("int64")
                bad_book_flags += int(
                    ((flag_values & F_MAYBE_BAD_BOOK) != 0).sum()
                )
                recv_ns = frame["ts_recv"].astype("int64").to_numpy()
                if prior_recv_ns is not None and int(recv_ns[0]) < prior_recv_ns:
                    nonmonotonic_recv += 1
                if len(recv_ns) > 1:
                    nonmonotonic_recv += int((recv_ns[1:] < recv_ns[:-1]).sum())
                prior_recv_ns = int(recv_ns[-1])

                for side in ("bid", "ask"):
                    undefined_seen = None
                    prior_price = None
                    for level in range(10):
                        suffix = f"{level:02d}"
                        price = frame[f"{side}_px_{suffix}"].astype("int64")
                        size = frame[f"{side}_sz_{suffix}"].astype("int64")
                        count = frame[f"{side}_ct_{suffix}"].astype("int64")
                        undefined = price == UNDEFINED_FIXED_PRICE
                        empty_level_coupling_violations += int(
                            (undefined & ((size != 0) | (count != 0))).sum()
                        )
                        negative_size_or_count += int(
                            ((size < 0) | (count < 0)).sum()
                        )
                        if undefined_seen is not None:
                            level_gap_violations += int(
                                (undefined_seen & ~undefined).sum()
                            )
                            both_defined = ~undefined_seen & ~undefined
                            if side == "bid":
                                bid_ordering_violations += int(
                                    (both_defined & (prior_price <= price)).sum()
                                )
                            else:
                                ask_ordering_violations += int(
                                    (both_defined & (prior_price >= price)).sum()
                                )
                        undefined_seen = (
                            undefined
                            if undefined_seen is None
                            else undefined_seen | undefined
                        )
                        prior_price = price

                instrument_ids.update(
                    int(value) for value in frame["instrument_id"].unique()
                )
                action_codes.update(str(value) for value in frame["action"].unique())
                side_codes.update(str(value) for value in frame["side"].unique())
                rtypes.update(int(value) for value in frame["rtype"].unique())
                first_event = (
                    frame["ts_event"].iloc[0] if first_event is None else first_event
                )
                last_event = frame["ts_event"].iloc[-1]
                first_recv = (
                    frame["ts_recv"].iloc[0] if first_recv is None else first_recv
                )
                last_recv = frame["ts_recv"].iloc[-1]

                count_rows = len(frame)
                ordinals = range(
                    source_ordinal + 1,
                    source_ordinal + count_rows + 1,
                )
                arrays = [
                    pa.array([file_index] * count_rows, type=pa.int16()),
                    pa.array(ordinals, type=pa.int64()),
                    pa.array(frame["ts_recv"], type=schema.field("ts_recv").type),
                    pa.array(frame["ts_event"], type=schema.field("ts_event").type),
                    pa.array(frame["rtype"], type=pa.int16()),
                    pa.array(frame["publisher_id"], type=pa.int32()),
                    pa.array(frame["instrument_id"], type=pa.int64()),
                    pa.array(frame["action"].astype(str), type=pa.string()),
                    pa.array(frame["side"].astype(str), type=pa.string()),
                    pa.array(frame["depth"], type=pa.int16()),
                    pa.array(frame["price"], type=pa.int64()),
                    pa.array(frame["size"], type=pa.int64()),
                    pa.array(frame["flags"], type=pa.int32()),
                    pa.array(frame["ts_in_delta"], type=pa.int64()),
                    pa.array(frame["sequence"], type=pa.int64()),
                ]
                arrays.extend(
                    pa.array(frame[name], type=schema.field(name).type)
                    for name in level_names
                )
                table = pa.Table.from_arrays(arrays, schema=schema)
                if writer is None:
                    writer = pq.ParquetWriter(
                        parquet_path,
                        schema,
                        compression="zstd",
                        use_dictionary=["action", "side"],
                    )
                writer.write_table(table)
                source_ordinal += count_rows
                source_rows += count_rows
                total_rows += count_rows
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
        raise ValueError("No MBP-10 records were normalized")
    parquet_rows = pq.ParquetFile(parquet_path).metadata.num_rows
    checks = {
        "schema_is_mbp10": rtypes == {10},
        "record_count_matches_fresh_provider_metadata": (
            total_rows == expected_record_count
        ),
        "parquet_record_count_matches_normalization": parquet_rows == total_rows,
        "all_receive_timestamps_inside_frozen_request": (
            receive_outside_request == 0
        ),
        "no_event_timestamps_at_or_after_request_end": (
            event_at_or_after_end == 0
        ),
        "pre_start_events_follow_snapshot_semantics": (
            invalid_pre_start_snapshot == 0
        ),
        "receive_timestamps_nondecreasing": nonmonotonic_recv == 0,
        "required_fields_complete": null_required == 0,
        "instrument_lineage_complete": (
            instrument_ids == expected_instrument_ids and bool(instrument_ids)
        ),
        "no_maybe_bad_book_flags": bad_book_flags == 0,
        "empty_levels_use_frozen_canonical_values": (
            empty_level_coupling_violations == 0
        ),
        "no_internal_level_gaps": level_gap_violations == 0,
        "bid_levels_strictly_descending": bid_ordering_violations == 0,
        "ask_levels_strictly_ascending": ask_ordering_violations == 0,
        "sizes_and_order_counts_nonnegative": negative_size_or_count == 0,
    }
    return {
        "version": "GC_MBP10_STEP_3B2_DATA_QUALITY_V0_1",
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
        "record_types_present": sorted(rtypes),
        "action_codes_present": sorted(action_codes),
        "side_codes_present": sorted(side_codes),
        "pre_start_snapshot_records": pre_start_event,
        "invalid_pre_start_snapshot_records": invalid_pre_start_snapshot,
        "receive_timestamp_out_of_range_records": receive_outside_request,
        "event_timestamp_at_or_after_end_records": event_at_or_after_end,
        "nonmonotonic_receive_timestamp_transitions": nonmonotonic_recv,
        "null_required_field_values": null_required,
        "maybe_bad_book_flag_records": bad_book_flags,
        "empty_level_coupling_violations": empty_level_coupling_violations,
        "internal_level_gap_violations": level_gap_violations,
        "bid_ordering_violations": bid_ordering_violations,
        "ask_ordering_violations": ask_ordering_violations,
        "negative_size_or_count_values": negative_size_or_count,
        "source_summaries": source_summaries,
        "checks": checks,
        "quality_gate": "PASS" if all(checks.values()) else "FAIL",
        "book_comparison_performed": False,
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
        "version": "GC_MBP10_STEP_3B2_POINT_IN_TIME_SYMBOLOGY_V0_1",
        "resolved_at_utc": datetime.now(UTC).isoformat(),
        "request": REQUEST,
        "mappings": mappings,
        "contains_market_values": False,
    }


def _verify_seal(output: Path, acquisition_path: Path) -> None:
    import pyarrow.parquet as pq

    _verify_frozen_context()
    acquisition = _load_acquisition(acquisition_path)
    if acquisition.get("status") != "NORMALIZED_HASHED_AND_SEALED":
        raise ValueError("Acquisition is not in the sealed state")
    if float(acquisition["actual_cost_usd"]) > MAXIMUM_CHARGE_USD:
        raise ValueError("Actual cost exceeds authorized cap")
    seal_path = Path(str(acquisition["normalization"]["path"]))
    if _sha256(seal_path) != acquisition["normalization"]["sha256"]:
        raise ValueError("Source seal file hash mismatch")
    seal = _load_json(seal_path)
    seal_without_hash = {
        key: value for key, value in seal.items() if key != "seal_hash"
    }
    if seal["seal_hash"] != _canonical_hash(seal_without_hash):
        raise ValueError("Canonical source seal hash mismatch")
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
    for item in seal["raw_sources"]:
        path = Path(str(item["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError("Raw source seal mismatch")
    parquet = base / str(seal["normalized_payload"]["path"])
    rows = pq.ParquetFile(parquet).metadata.num_rows
    if rows != int(seal["normalized_payload"]["records"]):
        raise ValueError("Normalized record count mismatch")
    print(
        json.dumps(
            {
                "stage": "GC_MBP10_STEP_3B2_SOURCE_SEAL_VERIFIED",
                "quality_gate": seal["quality_gate"],
                "normalized_records_verified": rows,
                "raw_files_verified": len(seal["raw_sources"]),
                "seal_hash": seal["seal_hash"],
                "actual_cost_usd": acquisition["actual_cost_usd"],
                "classification": seal["classification"],
                "market_values_human_or_model_inspected": False,
                "market_outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _load_acquisition(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Acquisition manifest not found: {path}")
    value = _load_json(path)
    if value.get("request") != REQUEST:
        raise ValueError("Acquisition request changed")
    if value.get("request_fingerprint") != _canonical_hash(REQUEST):
        raise ValueError("Acquisition request hash mismatch")
    if value.get("amendment_sha256") != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Acquisition Amendment A hash mismatch")
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
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


if __name__ == "__main__":
    main()
