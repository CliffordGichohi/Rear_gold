#!/usr/bin/env python3
"""Acquire and seal the frozen calendar-2025 ZN holdout input.

The command is deliberately split into idempotent actions. It never prints
market values, feature directions, or outcomes. A paid submission is possible
only when the immutable M6 manifest validates and the provider's fresh quote
does not exceed the frozen user-authorized cap.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    EXPECTED_ZN_BATCH_REQUEST,
    batch_request_fingerprint,
    validate_holdout_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "raw" / "databento_cme_2025_zn"
ACQUISITION_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_M6_ZN_ACQUISITION_V0_1"
NORMALIZATION_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_M6_ZN_NORMALIZATION_V0_1"
EXPECTED_SDK_VERSION = "0.82.0"


def main() -> None:
    args = _parser().parse_args()
    research = _load_json(Path(args.research_manifest))
    research_hash = validate_holdout_manifest(research)
    _verify_research_sources(research)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    acquisition_path = output / "acquisition_manifest.json"

    if args.action == "reseal":
        acquisition = _load_acquisition(
            acquisition_path,
            expected_research_hash=research_hash,
        )
        _reseal_normalization_paths(
            output=output,
            acquisition_path=acquisition_path,
            acquisition=acquisition,
        )
        return

    key = _api_key(Path(args.env_file))
    client, sdk_version = _client(key)
    if sdk_version != EXPECTED_SDK_VERSION:
        raise RuntimeError(
            f"Databento SDK changed: expected {EXPECTED_SDK_VERSION}, got {sdk_version}"
        )

    if args.action == "estimate":
        estimate = _get_cost(client)
        print(
            json.dumps(
                {
                    "stage": "V2_M6_FRESH_COST_ESTIMATE",
                    "estimated_cost_usd": estimate,
                    "maximum_cost_usd": research["acquisition"]["maximum_cost_usd"],
                    "within_cap": estimate
                    <= float(research["acquisition"]["maximum_cost_usd"]),
                    "batch_job_submitted": False,
                    "market_values_accessed": False,
                    "holdout_outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return

    if args.action == "submit":
        acquisition = _submit_or_resume(
            client,
            acquisition_path=acquisition_path,
            research=research,
            research_hash=research_hash,
            sdk_version=sdk_version,
        )
        _update_status(client, acquisition_path, acquisition)
        return

    acquisition = _load_acquisition(
        acquisition_path,
        expected_research_hash=research_hash,
    )
    if args.action == "status":
        _update_status(client, acquisition_path, acquisition)
        return
    if args.action == "download":
        _download(
            client,
            output=output,
            acquisition_path=acquisition_path,
            acquisition=acquisition,
            maximum_cost=float(research["acquisition"]["maximum_cost_usd"]),
        )
        return
    if args.action == "normalize":
        _normalize(
            client,
            output=output,
            acquisition_path=acquisition_path,
            acquisition=acquisition,
            research_hash=research_hash,
        )
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
            "reseal",
        ),
    )
    parser.add_argument(
        "--research-manifest",
        default=("research_manifests/gold_casebook_discovery_v2_m6_holdout_v01.json"),
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def _submit_or_resume(
    client: Any,
    *,
    acquisition_path: Path,
    research: Mapping[str, Any],
    research_hash: str,
    sdk_version: str,
) -> dict[str, Any]:
    maximum_cost = float(research["acquisition"]["maximum_cost_usd"])
    if research["acquisition"]["paid_submission_authorized"] is not True:
        raise RuntimeError("Paid submission is not authorized")
    existing = (
        _load_acquisition(
            acquisition_path,
            expected_research_hash=research_hash,
        )
        if acquisition_path.exists()
        else None
    )
    if existing and existing.get("job_id"):
        print(
            json.dumps(
                {
                    "stage": "V2_M6_BATCH_RESUME",
                    "job_id": existing["job_id"],
                    "new_job_submitted": False,
                },
                sort_keys=True,
            )
        )
        return existing

    estimate = _get_cost(client)
    if estimate > maximum_cost:
        raise RuntimeError(
            f"Fresh estimate ${estimate:.12f} exceeds ${maximum_cost:.2f} cap"
        )
    intent = existing or {
        "acquisition_version": ACQUISITION_VERSION,
        "research_manifest_hash": research_hash,
        "request": EXPECTED_ZN_BATCH_REQUEST,
        "request_fingerprint": batch_request_fingerprint(),
        "sdk_version": sdk_version,
        "maximum_cost_usd": maximum_cost,
        "submission_intent_recorded_at": datetime.now(UTC).isoformat(),
        "fresh_estimated_cost_usd": estimate,
        "status": "SUBMISSION_INTENT_RECORDED",
        "api_key_recorded": False,
        "market_values_inspected": False,
        "holdout_outcomes_accessed": False,
    }
    _write_json_atomic(acquisition_path, intent)

    recovered = _matching_jobs(
        client,
        since=str(intent["submission_intent_recorded_at"]),
    )
    if len(recovered) > 1:
        raise RuntimeError(
            "Multiple matching calendar-2025 ZN jobs found; refusing submission"
        )
    if recovered:
        response = recovered[0]
        submission_mode = "RECOVERED_EXISTING_JOB"
    else:
        request = EXPECTED_ZN_BATCH_REQUEST
        response = client.batch.submit_job(
            dataset=request["dataset"],
            symbols=request["symbols"],
            schema=request["schema"],
            stype_in=request["stype_in"],
            stype_out=request["stype_out"],
            start=request["start"],
            end=request["end"],
            encoding=request["encoding"],
            compression=request["compression"],
            split_duration=request["split_duration"],
            split_symbols=request["split_symbols"],
            delivery=request["delivery"],
        )
        submission_mode = "NEW_JOB_SUBMITTED"
    safe_response = _safe_mapping(response)
    job_id = _job_id(safe_response)
    intent.update(
        {
            "job_id": job_id,
            "submission_mode": submission_mode,
            "submitted_or_recovered_at": datetime.now(UTC).isoformat(),
            "submission_response": safe_response,
            "status": "BATCH_JOB_RECORDED",
        }
    )
    _write_json_atomic(acquisition_path, intent)
    print(
        json.dumps(
            {
                "stage": "V2_M6_BATCH_JOB_RECORDED",
                "job_id": job_id,
                "submission_mode": submission_mode,
                "fresh_estimated_cost_usd": estimate,
                "maximum_cost_usd": maximum_cost,
                "market_values_accessed": False,
                "holdout_outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )
    return intent


def _matching_jobs(client: Any, *, since: str) -> list[dict[str, Any]]:
    request = EXPECTED_ZN_BATCH_REQUEST
    matches: list[dict[str, Any]] = []
    for raw in client.batch.list_jobs(since=since):
        job = _safe_mapping(raw)
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
            and str(job.get("start", "")).startswith("2025-01-01T00:00:00")
            and str(job.get("end", "")).startswith("2026-01-01T00:00:00")
        ):
            matches.append(job)
    return matches


def _update_status(
    client: Any,
    acquisition_path: Path,
    acquisition: dict[str, Any],
) -> dict[str, Any]:
    details = _safe_mapping(client.batch.get_job_details(str(acquisition["job_id"])))
    acquisition["job_details"] = details
    acquisition["last_status_at"] = datetime.now(UTC).isoformat()
    acquisition["status"] = f"BATCH_{str(details.get('state', 'UNKNOWN')).upper()}"
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "V2_M6_BATCH_STATUS",
                "job_id": acquisition["job_id"],
                "job_state": details.get("state", "unknown"),
                "cost_usd": details.get("cost_usd"),
                "market_values_accessed": False,
                "holdout_outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )
    return acquisition


def _download(
    client: Any,
    *,
    output: Path,
    acquisition_path: Path,
    acquisition: dict[str, Any],
    maximum_cost: float,
) -> None:
    acquisition = _update_status(client, acquisition_path, acquisition)
    details = acquisition["job_details"]
    if str(details.get("state", "")).lower() != "done":
        raise RuntimeError("Databento batch job is not complete")
    actual_cost = float(details.get("cost_usd") or 0.0)
    if actual_cost > maximum_cost:
        raise RuntimeError(
            f"Completed job cost ${actual_cost:.12f} exceeds ${maximum_cost:.2f} authorized cap"
        )
    job_id = str(acquisition["job_id"])
    remote_files = [_safe_mapping(item) for item in client.batch.list_files(job_id)]
    downloaded = client.batch.download(job_id=job_id, output_dir=output)
    local_files = [
        {
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(Path(item) for item in downloaded)
        if path.is_file()
    ]
    acquisition.update(
        {
            "remote_files": remote_files,
            "local_files": local_files,
            "downloaded_at": datetime.now(UTC).isoformat(),
            "actual_cost_usd": actual_cost,
            "status": "DOWNLOADED_AND_RAW_HASHED",
            "market_values_inspected": False,
            "holdout_outcomes_accessed": False,
        }
    )
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "V2_M6_RAW_ARCHIVE_DOWNLOADED_AND_HASHED",
                "job_id": job_id,
                "actual_cost_usd": actual_cost,
                "downloaded_files": len(local_files),
                "downloaded_bytes": sum(
                    int(item["size_bytes"]) for item in local_files
                ),
                "market_values_inspected": False,
                "holdout_outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _normalize(
    client: Any,
    *,
    output: Path,
    acquisition_path: Path,
    acquisition: dict[str, Any],
    research_hash: str,
) -> None:
    if acquisition.get("status") not in {
        "DOWNLOADED_AND_RAW_HASHED",
        "BATCH_DONE",
    }:
        raise RuntimeError("Raw archive has not been downloaded and sealed")
    job_dir = output / str(acquisition["job_id"])
    raw_files = sorted(
        path for pattern in ("*.dbn", "*.dbn.zst") for path in job_dir.glob(pattern)
    )
    if not raw_files:
        raise RuntimeError("No downloaded DBN payload was found")
    expected_hashes = {
        Path(str(item["path"])).name: str(item["sha256"])
        for item in acquisition.get("local_files", [])
    }
    for path in raw_files:
        expected = expected_hashes.get(path.name)
        if expected is None or _sha256(path) != expected:
            raise ValueError(f"Raw archive hash mismatch: {path.name}")

    normalized_dir = job_dir / "normalized"
    if normalized_dir.exists():
        raise FileExistsError(
            f"Refusing to overwrite sealed normalization: {normalized_dir}"
        )
    symbology = _resolve_symbology(client)
    continuous_intervals = _continuous_intervals(symbology)
    raw_symbol_intervals = _raw_symbol_intervals(symbology)

    with tempfile.TemporaryDirectory(
        dir=job_dir,
        prefix=".normalized-staging-",
    ) as temporary:
        staging = Path(temporary)
        values_path = staging / "zn_v_0_2025_ohlcv_1m.csv.gz"
        lineage_path = staging / "zn_v_0_2025_timestamp_lineage.csv.gz"
        symbology_path = staging / "symbology_lineage.json"
        _write_json(symbology_path, symbology)
        summary = _normalize_payloads(
            raw_files,
            values_path=values_path,
            lineage_path=lineage_path,
            continuous_intervals=continuous_intervals,
            raw_symbol_intervals=raw_symbol_intervals,
        )
        normalization: dict[str, Any] = {
            "normalization_version": NORMALIZATION_VERSION,
            "research_manifest_hash": research_hash,
            "acquisition_manifest_hash": canonical_hash(acquisition),
            "request": EXPECTED_ZN_BATCH_REQUEST,
            "request_fingerprint": batch_request_fingerprint(),
            "provider": "DATABENTO_GLBX_MDP3",
            "continuous_symbol": "ZN.v.0",
            "schema": "OHLCV_1M",
            "normalized_at": datetime.now(UTC).isoformat(),
            "availability_rule": (
                "available_at = OHLCV interval start plus one minute"
            ),
            "duplicate_policy": (
                "continuous_symbol plus open_time must be unique; any duplicate blocks the holdout"
            ),
            "ordering_policy": (
                "Rows must be strictly increasing by open_time across the complete sealed payload"
            ),
            "roll_crossing_policy": (
                "A four-hour change whose endpoint instrument IDs differ is "
                "UNKNOWN and produces NO_BIAS"
            ),
            "underlying_contract_definition": (
                "Point-in-time Databento continuous-to-instrument mapping "
                "plus instrument-to-raw-symbol mapping"
            ),
            "source_files": [
                {
                    "path": str(path.resolve()),
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in raw_files
            ],
            "normalized_payload": {
                "path": values_path.name,
                "sha256": _sha256(values_path),
                "bytes": values_path.stat().st_size,
                "contains_market_values": True,
                "human_or_model_inspected": False,
            },
            "timestamp_lineage": {
                "path": lineage_path.name,
                "sha256": _sha256(lineage_path),
                "bytes": lineage_path.stat().st_size,
                "contains_market_values": False,
            },
            "symbology_lineage": {
                "path": symbology_path.name,
                "sha256": _sha256(symbology_path),
                "bytes": symbology_path.stat().st_size,
                "contains_market_values": False,
            },
            **summary,
            "market_values_human_or_model_inspected": False,
            "features_calculated": False,
            "outcomes_accessed": False,
        }
        normalization["normalization_hash"] = canonical_hash(normalization)
        _write_json(staging / "normalization.json", normalization)
        staging.rename(normalized_dir)

    acquisition["normalization"] = {
        "path": str((normalized_dir / "normalization.json").resolve()),
        "sha256": _sha256(normalized_dir / "normalization.json"),
        "normalization_hash": normalization["normalization_hash"],
        "total_rows": normalization["total_rows"],
        "status": "SEALED",
    }
    acquisition["status"] = "NORMALIZED_HASHED_AND_SEALED"
    acquisition["market_values_inspected"] = False
    acquisition["holdout_outcomes_accessed"] = False
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "V2_M6_ZN_NORMALIZED_HASHED_AND_SEALED",
                "job_id": acquisition["job_id"],
                "normalization_hash": normalization["normalization_hash"],
                "total_rows": normalization["total_rows"],
                "underlying_contract_count": normalization["underlying_contract_count"],
                "roll_transition_count": normalization[
                    "observed_roll_transition_count"
                ],
                "market_values_human_or_model_inspected": False,
                "features_calculated": False,
                "holdout_outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _reseal_normalization_paths(
    *,
    output: Path,
    acquisition_path: Path,
    acquisition: dict[str, Any],
) -> None:
    if acquisition.get("status") != "NORMALIZED_HASHED_AND_SEALED":
        raise RuntimeError("Normalization is not in a sealable state")
    normalized_dir = output / str(acquisition["job_id"]) / "normalized"
    normalization_path = normalized_dir / "normalization.json"
    normalization = _load_json(normalization_path)
    if (
        normalization.get("market_values_human_or_model_inspected") is not False
        or normalization.get("features_calculated") is not False
        or normalization.get("outcomes_accessed") is not False
    ):
        raise ValueError("Normalization guardrails do not permit metadata reseal")
    old_hash = str(normalization["normalization_hash"])
    for key in (
        "normalized_payload",
        "timestamp_lineage",
        "symbology_lineage",
    ):
        entry = normalization[key]
        filename = Path(str(entry["path"])).name
        final_path = normalized_dir / filename
        if (
            not final_path.is_file()
            or _sha256(final_path) != entry["sha256"]
            or final_path.stat().st_size != int(entry["bytes"])
        ):
            raise ValueError(f"Cannot reseal missing or changed artifact: {filename}")
        entry["path"] = filename
    normalization["metadata_reseal"] = {
        "reason": (
            "Replace temporary staging locators with immutable relative "
            "filenames after the atomic directory rename."
        ),
        "prior_normalization_hash": old_hash,
        "market_value_payload_changed": False,
        "market_values_human_or_model_inspected": False,
        "features_calculated": False,
        "outcomes_accessed": False,
        "resealed_at": datetime.now(UTC).isoformat(),
    }
    normalization_without_hash = {
        key: value
        for key, value in normalization.items()
        if key != "normalization_hash"
    }
    normalization["normalization_hash"] = canonical_hash(normalization_without_hash)
    _write_json_atomic(normalization_path, normalization)
    acquisition["normalization"] = {
        "path": str(normalization_path.resolve()),
        "sha256": _sha256(normalization_path),
        "normalization_hash": normalization["normalization_hash"],
        "total_rows": normalization["total_rows"],
        "status": "SEALED",
    }
    acquisition["metadata_reseal"] = {
        "prior_normalization_hash": old_hash,
        "normalization_hash": normalization["normalization_hash"],
        "market_value_payload_changed": False,
        "market_values_inspected": False,
        "holdout_outcomes_accessed": False,
    }
    _write_json_atomic(acquisition_path, acquisition)
    print(
        json.dumps(
            {
                "stage": "V2_M6_ZN_NORMALIZATION_METADATA_RESEALED",
                "prior_normalization_hash": old_hash,
                "normalization_hash": normalization["normalization_hash"],
                "market_value_payload_changed": False,
                "market_values_inspected": False,
                "features_calculated": False,
                "holdout_outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _normalize_payloads(
    raw_files: list[Path],
    *,
    values_path: Path,
    lineage_path: Path,
    continuous_intervals: list[dict[str, Any]],
    raw_symbol_intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    import databento as db
    import pandas as pd

    value_fields = (
        "source_record_id",
        "source_file_sha256",
        "source_row_ordinal",
        "open_time",
        "available_at",
        "continuous_symbol",
        "instrument_id",
        "underlying_raw_symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )
    lineage_fields = value_fields[:8]
    total_rows = 0
    first_open: pd.Timestamp | None = None
    last_open: pd.Timestamp | None = None
    prior_open: pd.Timestamp | None = None
    prior_instrument: int | None = None
    prior_raw_symbol: str | None = None
    instruments: set[int] = set()
    raw_symbols: set[str] = set()
    roll_transitions: list[dict[str, Any]] = []

    with (
        _gzip_text_writer(values_path) as values_handle,
        _gzip_text_writer(lineage_path) as lineage_handle,
    ):
        values_writer = csv.DictWriter(values_handle, fieldnames=value_fields)
        lineage_writer = csv.DictWriter(
            lineage_handle,
            fieldnames=lineage_fields,
        )
        values_writer.writeheader()
        lineage_writer.writeheader()
        for source in raw_files:
            source_hash = _sha256(source)
            store = db.DBNStore.from_file(source)
            if str(store.schema) != EXPECTED_ZN_BATCH_REQUEST["schema"]:
                raise ValueError(f"Unexpected DBN schema in {source.name}")
            ordinal = 0
            for chunk in store.to_df(
                pretty_ts=True,
                map_symbols=True,
                count=250_000,
            ):
                frame = chunk.reset_index()
                if frame.empty:
                    continue
                required = {
                    "ts_event",
                    "instrument_id",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "symbol",
                }
                if required.difference(frame.columns):
                    raise ValueError(f"DBN columns are incomplete in {source.name}")
                if (
                    (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
                    or (frame["low"] > frame[["open", "close"]].min(axis=1)).any()
                    or (frame["volume"] < 0).any()
                ):
                    raise ValueError(f"Invalid OHLCV geometry in {source.name}")
                for row in frame.itertuples(index=False):
                    ordinal += 1
                    open_time = pd.Timestamp(row.ts_event)
                    if open_time.tzinfo is None:
                        open_time = open_time.tz_localize("UTC")
                    else:
                        open_time = open_time.tz_convert("UTC")
                    if not (
                        pd.Timestamp("2025-01-01T00:00:00Z")
                        <= open_time
                        < pd.Timestamp("2026-01-01T00:00:00Z")
                    ):
                        raise ValueError("Normalized row is outside calendar 2025")
                    if prior_open is not None and open_time <= prior_open:
                        raise ValueError(
                            "Duplicate or non-monotonic ZN open_time encountered"
                        )
                    instrument_id = int(row.instrument_id)
                    expected_instrument = _mapped_instrument(
                        open_time.date(),
                        continuous_intervals,
                    )
                    if instrument_id != expected_instrument:
                        raise ValueError(
                            "DBN row disagrees with continuous-contract lineage"
                        )
                    raw_symbol = _mapped_raw_symbol(
                        open_time.date(),
                        instrument_id,
                        raw_symbol_intervals,
                    )
                    symbol = str(row.symbol)
                    if symbol != "ZN.v.0":
                        raise ValueError("Unexpected continuous symbol in ZN payload")
                    available_at = open_time + pd.Timedelta(minutes=1)
                    source_record_id = f"{source_hash}:{ordinal}:{instrument_id}:{open_time.isoformat()}"
                    common = {
                        "source_record_id": source_record_id,
                        "source_file_sha256": source_hash,
                        "source_row_ordinal": ordinal,
                        "open_time": open_time.isoformat(),
                        "available_at": available_at.isoformat(),
                        "continuous_symbol": symbol,
                        "instrument_id": instrument_id,
                        "underlying_raw_symbol": raw_symbol,
                    }
                    values_writer.writerow(
                        {
                            **common,
                            "open": row.open,
                            "high": row.high,
                            "low": row.low,
                            "close": row.close,
                            "volume": row.volume,
                        }
                    )
                    lineage_writer.writerow(common)
                    if (
                        prior_instrument is not None
                        and prior_instrument != instrument_id
                    ):
                        roll_transitions.append(
                            {
                                "effective_open_time": open_time.isoformat(),
                                "from_instrument_id": prior_instrument,
                                "from_underlying_raw_symbol": prior_raw_symbol,
                                "to_instrument_id": instrument_id,
                                "to_underlying_raw_symbol": raw_symbol,
                                "source_record_id": source_record_id,
                            }
                        )
                    instruments.add(instrument_id)
                    raw_symbols.add(raw_symbol)
                    first_open = open_time if first_open is None else first_open
                    last_open = open_time
                    prior_open = open_time
                    prior_instrument = instrument_id
                    prior_raw_symbol = raw_symbol
                    total_rows += 1
    if total_rows == 0 or first_open is None or last_open is None:
        raise ValueError("No calendar-2025 ZN rows were normalized")
    return {
        "total_rows": total_rows,
        "distinct_open_times": total_rows,
        "duplicate_rows": 0,
        "first_open_time": first_open.isoformat(),
        "last_open_time": last_open.isoformat(),
        "underlying_contract_count": len(instruments),
        "instrument_ids": sorted(instruments),
        "underlying_raw_symbols": sorted(raw_symbols),
        "observed_roll_transition_count": len(roll_transitions),
        "observed_roll_transitions": roll_transitions,
        "continuous_mapping_intervals": continuous_intervals,
        "raw_symbol_mapping_intervals": raw_symbol_intervals,
    }


def _resolve_symbology(client: Any) -> dict[str, Any]:
    request = EXPECTED_ZN_BATCH_REQUEST
    continuous = _safe_mapping(
        client.symbology.resolve(
            dataset=request["dataset"],
            symbols=request["symbols"],
            stype_in="continuous",
            stype_out="instrument_id",
            start_date="2025-01-01",
            end_date="2026-01-01",
        )
    )
    intervals = list(continuous.get("result", {}).get("ZN.v.0", []))
    if (
        continuous.get("status") != 0
        or continuous.get("partial")
        or continuous.get("not_found")
        or not intervals
    ):
        raise ValueError("Incomplete ZN continuous symbology resolution")
    raw_resolutions: list[dict[str, Any]] = []
    for interval in intervals:
        instrument_id = str(interval["s"])
        resolved = _safe_mapping(
            client.symbology.resolve(
                dataset=request["dataset"],
                symbols=[instrument_id],
                stype_in="instrument_id",
                stype_out="raw_symbol",
                start_date=interval["d0"],
                end_date=interval["d1"],
            )
        )
        if (
            resolved.get("status") != 0
            or resolved.get("partial")
            or resolved.get("not_found")
        ):
            raise ValueError("Incomplete ZN underlying raw-symbol resolution")
        raw_resolutions.append(
            {
                "instrument_id": int(instrument_id),
                "continuous_interval": {
                    "d0": interval["d0"],
                    "d1": interval["d1"],
                },
                "response": resolved,
            }
        )
    return {
        "version": "DATABENTO_POINT_IN_TIME_SYMBOLOGY_V0_1",
        "resolved_at": datetime.now(UTC).isoformat(),
        "continuous_to_instrument": continuous,
        "instrument_to_raw_symbol": raw_resolutions,
        "contains_market_values": False,
    }


def _continuous_intervals(symbology: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries = symbology["continuous_to_instrument"]["result"]["ZN.v.0"]
    return [
        {
            "start_date_inclusive": str(item["d0"]),
            "end_date_exclusive": str(item["d1"]),
            "instrument_id": int(item["s"]),
        }
        for item in entries
    ]


def _raw_symbol_intervals(symbology: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in symbology["instrument_to_raw_symbol"]:
        instrument_id = int(item["instrument_id"])
        result = item["response"]["result"].get(str(instrument_id), [])
        if not result:
            raise ValueError("No raw symbol returned for ZN instrument ID")
        output.extend(
            {
                "start_date_inclusive": str(mapping["d0"]),
                "end_date_exclusive": str(mapping["d1"]),
                "instrument_id": instrument_id,
                "raw_symbol": str(mapping["s"]),
            }
            for mapping in result
        )
    return output


def _mapped_instrument(
    value: date,
    intervals: Iterable[Mapping[str, Any]],
) -> int:
    for item in intervals:
        if (
            date.fromisoformat(str(item["start_date_inclusive"]))
            <= value
            < date.fromisoformat(str(item["end_date_exclusive"]))
        ):
            return int(item["instrument_id"])
    raise ValueError(f"No continuous ZN instrument mapping for {value.isoformat()}")


def _mapped_raw_symbol(
    value: date,
    instrument_id: int,
    intervals: Iterable[Mapping[str, Any]],
) -> str:
    for item in intervals:
        if int(item["instrument_id"]) == instrument_id and date.fromisoformat(
            str(item["start_date_inclusive"])
        ) <= value < date.fromisoformat(str(item["end_date_exclusive"])):
            return str(item["raw_symbol"])
    raise ValueError(
        f"No ZN raw-symbol mapping for instrument {instrument_id} on {value.isoformat()}"
    )


def _get_cost(client: Any) -> float:
    request = EXPECTED_ZN_BATCH_REQUEST
    value = float(
        client.metadata.get_cost(
            dataset=request["dataset"],
            symbols=request["symbols"],
            schema=request["schema"],
            stype_in=request["stype_in"],
            start=request["start"],
            end=request["end"],
        )
    )
    if not math.isfinite(value) or value < 0:
        raise ValueError("Databento returned an invalid cost estimate")
    return value


def _client(key: str) -> tuple[Any, str]:
    try:
        import databento as db
    except ModuleNotFoundError as exc:
        raise RuntimeError("Databento SDK 0.82.0 is required") from exc
    return db.Historical(key), str(getattr(db, "__version__", "UNKNOWN"))


def _api_key(env_file: Path) -> str:
    existing = os.getenv("DATABENTO_API_KEY", "").strip()
    if existing:
        return existing
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


def _load_acquisition(
    path: Path,
    *,
    expected_research_hash: str,
) -> dict[str, Any]:
    value = _load_json(path)
    if value.get("acquisition_version") != ACQUISITION_VERSION:
        raise ValueError("Unexpected acquisition version")
    if value.get("research_manifest_hash") != expected_research_hash:
        raise ValueError("Acquisition belongs to another M6 manifest")
    if value.get("request") != EXPECTED_ZN_BATCH_REQUEST:
        raise ValueError("Acquisition request changed")
    if value.get("request_fingerprint") != batch_request_fingerprint():
        raise ValueError("Acquisition request fingerprint changed")
    return value


def _verify_research_sources(research: Mapping[str, Any]) -> None:
    for item in research["verified_sources"]:
        path = Path(str(item["path"]))
        if not path.is_file() or _sha256(path) != item["sha256"]:
            raise ValueError(f"M6 source hash mismatch: {path}")


def _job_id(response: Mapping[str, Any]) -> str:
    value = response.get("id") or response.get("job_id")
    if not value:
        raise RuntimeError("Databento returned no batch job ID")
    return str(value)


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        value = dict(value)
    return {
        str(key): _json_safe(item)
        for key, item in value.items()
        if str(key).lower() not in {"api_key", "key", "secret", "token"}
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if str(key).lower() not in {"api_key", "key", "secret", "token"}
        }
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _gzip_text_writer(path: Path) -> io.TextIOWrapper:
    binary = path.open("wb")
    compressed = gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=binary,
        mtime=0,
    )
    return io.TextIOWrapper(compressed, encoding="utf-8", newline="")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    _write_json(temporary, value)
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
