from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "raw" / "databento_gold_fade_validation_v01"
AUTHORIZATION = ROOT / "GOLD_TRIPLE_MACRO_ACCEPTANCE_FADE_ACQUISITION_AUTHORIZATION_V1.md"
CONTRACT = ROOT / "GOLD_TRIPLE_MACRO_ACCEPTANCE_FADE_VALIDATION_CONTRACT_V1.md"
FREEZE = ROOT / "research_manifests" / "gold_triple_macro_acceptance_fade_validation_v01.json"
CALENDAR_RAW = ROOT / "data" / "mt5" / "calendar" / "mt5_us_calendar_raw.csv"
CALENDAR_STATUS = ROOT / "data" / "mt5" / "calendar" / "mt5_us_calendar_status.csv"
CALENDAR_AUDIT = ROOT / "data" / "mt5" / "calendar" / "mt5_us_calendar_audit.json"
EXISTING_ZN_2025 = ROOT / "data" / "raw" / "databento_cme_2025_zn" / "acquisition_manifest.json"

VERSION = "GOLD_FADE_VALIDATION_DATABENTO_ACQUISITION_V0_1"
EXPECTED_SDK_VERSION = "0.82.0"
MAXIMUM_COMBINED_COST_USD = 2.50
REQUIRED_CALENDAR_END_SERVER = "2026.07.30 03:00:00"

EXPECTED_CONTRACT_SHA256 = "68554b9a1169ad50d8f89d63a65db3d9c87a390020ba1d2e1b7868c4c36bddd9"
EXPECTED_FREEZE_SHA256 = "7c16670df2e6361c81c762ae34903fd27fc2427a53ec1ff900fe8e1f2b128c3f"
EXPECTED_EXISTING_ZN_MANIFEST_SHA256 = "f6cfafd4fae3058b8f740e5e92a739d656b53936ba15859f3c38d9ae329ecfd0"

REQUESTS: tuple[dict[str, Any], ...] = (
    {
        "request_id": "ZT_2025",
        "dataset": "GLBX.MDP3",
        "symbols": ["ZT.v.0"],
        "schema": "ohlcv-1m",
        "stype_in": "continuous",
        "stype_out": "instrument_id",
        "start": "2025-01-01T00:00:00Z",
        "end": "2026-01-01T00:00:00Z",
        "encoding": "dbn",
        "compression": "zstd",
        "split_duration": "year",
        "split_symbols": False,
        "delivery": "download",
    },
    {
        "request_id": "ZT_ZN_2026_YTD",
        "dataset": "GLBX.MDP3",
        "symbols": ["ZT.v.0", "ZN.v.0"],
        "schema": "ohlcv-1m",
        "stype_in": "continuous",
        "stype_out": "instrument_id",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-07-30T00:00:00Z",
        "encoding": "dbn",
        "compression": "zstd",
        "split_duration": "year",
        "split_symbols": False,
        "delivery": "download",
    },
)


def main() -> None:
    predecessors = verify_predecessors()
    key = api_key(ROOT / ".env")
    import databento as db

    if str(db.__version__) != EXPECTED_SDK_VERSION:
        raise RuntimeError(
            f"Databento SDK changed: {db.__version__} != {EXPECTED_SDK_VERSION}"
        )
    client = db.Historical(key)
    estimates = quote(client)
    combined_estimate = sum(float(item["estimated_cost_usd"]) for item in estimates)
    if combined_estimate > MAXIMUM_COMBINED_COST_USD:
        raise RuntimeError(
            f"Fresh combined estimate ${combined_estimate:.12f} exceeds "
            f"the ${MAXIMUM_COMBINED_COST_USD:.2f} cap"
        )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT / "acquisition_manifest.json"
    manifest = load_or_initialize_manifest(
        manifest_path,
        predecessors=predecessors,
        estimates=estimates,
        combined_estimate=combined_estimate,
    )
    jobs = dict(manifest.get("jobs", {}))
    for request in REQUESTS:
        request_id = str(request["request_id"])
        if request_id not in jobs:
            jobs[request_id] = submit_or_recover(
                client,
                request=request,
                since=str(manifest["submission_intent_recorded_at"]),
            )
            manifest["jobs"] = jobs
            manifest["status"] = "BATCH_JOBS_PARTIALLY_OR_FULLY_RECORDED"
            write_json_atomic(manifest_path, manifest)

    complete_jobs: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + 300
    for request in REQUESTS:
        request_id = str(request["request_id"])
        job_id = str(jobs[request_id]["job_id"])
        while True:
            details = safe_mapping(client.batch.get_job_details(job_id))
            state = str(details.get("state", "UNKNOWN")).lower()
            if state == "done":
                complete_jobs[request_id] = details
                break
            if state in {"expired", "failed", "cancelled"}:
                raise RuntimeError(f"Databento job {job_id} ended in state {state}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for Databento job {job_id}")
            time.sleep(5)

    actual_combined_cost = sum(
        float(item.get("cost_usd") or 0.0) for item in complete_jobs.values()
    )
    if actual_combined_cost > MAXIMUM_COMBINED_COST_USD:
        raise RuntimeError(
            f"Actual combined cost ${actual_combined_cost:.12f} exceeded the "
            f"authorized ${MAXIMUM_COMBINED_COST_USD:.2f} cap"
        )
    manifest["completed_job_details"] = complete_jobs
    manifest["actual_combined_cost_usd"] = actual_combined_cost
    manifest["status"] = "BATCH_JOBS_COMPLETE"
    write_json_atomic(manifest_path, manifest)

    downloads: dict[str, Any] = dict(manifest.get("downloads", {}))
    normalizations: dict[str, Any] = dict(manifest.get("normalizations", {}))
    for request in REQUESTS:
        request_id = str(request["request_id"])
        request_dir = OUTPUT / request_id
        if request_id not in downloads:
            request_dir.mkdir(parents=True, exist_ok=True)
            job_id = str(jobs[request_id]["job_id"])
            remote_files = [safe_mapping(item) for item in client.batch.list_files(job_id)]
            downloaded = client.batch.download(job_id=job_id, output_dir=request_dir)
            local_files = inventory_paths(Path(item) for item in downloaded)
            downloads[request_id] = {
                "job_id": job_id,
                "downloaded_at": datetime.now(UTC).isoformat(),
                "remote_files": remote_files,
                "local_files": local_files,
            }
            manifest["downloads"] = downloads
            manifest["status"] = "RAW_DOWNLOADS_PARTIALLY_OR_FULLY_HASHED"
            write_json_atomic(manifest_path, manifest)

        if request_id not in normalizations:
            raw_files = sorted(request_dir.rglob("*.dbn")) + sorted(
                request_dir.rglob("*.dbn.zst")
            )
            if not raw_files:
                raise RuntimeError(f"No DBN payload found for {request_id}")
            expected_hashes = {
                Path(str(item["path"])).resolve(): str(item["sha256"])
                for item in downloads[request_id]["local_files"]
                if str(item["path"]).endswith((".dbn", ".dbn.zst"))
            }
            for raw_file in raw_files:
                if expected_hashes.get(raw_file.resolve()) != sha256(raw_file):
                    raise RuntimeError(f"Raw source hash mismatch: {raw_file}")
            normalizations[request_id] = normalize_twice(
                raw_files,
                request=request,
                output_dir=request_dir / "normalized",
            )
            manifest["normalizations"] = normalizations
            manifest["status"] = "NORMALIZATIONS_PARTIALLY_OR_FULLY_SEALED"
            write_json_atomic(manifest_path, manifest)

    manifest.update(
        {
            "status": "NORMALIZED_HASHED_AND_SEALED",
            "sealed_at": datetime.now(UTC).isoformat(),
            "api_key_recorded": False,
            "card_charge_authorized": False,
            "credit_only_authorization": True,
            "market_values_human_or_model_inspected": False,
            "relationships_calculated": False,
            "outcomes_calculated": False,
        }
    )
    manifest["seal_sha256"] = canonical_hash(
        {key: value for key, value in manifest.items() if key != "seal_sha256"}
    )
    write_json_atomic(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "combined_estimated_cost_usd": combined_estimate,
                "actual_combined_cost_usd": actual_combined_cost,
                "request_count": len(REQUESTS),
                "job_ids": {
                    key: value["job_id"] for key, value in jobs.items()
                },
                "normalization_rows": {
                    key: value["total_rows"]
                    for key, value in normalizations.items()
                },
                "seal_sha256": manifest["seal_sha256"],
                "card_charge_authorized": False,
                "market_values_human_or_model_inspected": False,
                "relationships_calculated": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


def verify_predecessors() -> dict[str, Any]:
    hashes = {
        "authorization": sha256(AUTHORIZATION),
        "contract": sha256(CONTRACT),
        "freeze": sha256(FREEZE),
        "calendar_raw": sha256(CALENDAR_RAW),
        "calendar_status": sha256(CALENDAR_STATUS),
        "calendar_audit": sha256(CALENDAR_AUDIT),
        "existing_zn_2025_manifest": sha256(EXISTING_ZN_2025),
    }
    if hashes["contract"] != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("Frozen validation contract hash changed")
    if hashes["freeze"] != EXPECTED_FREEZE_SHA256:
        raise RuntimeError("Frozen validation manifest hash changed")
    if hashes["existing_zn_2025_manifest"] != EXPECTED_EXISTING_ZN_MANIFEST_SHA256:
        raise RuntimeError("Existing sealed ZN-2025 manifest hash changed")

    with CALENDAR_STATUS.open("r", encoding="utf-8-sig", newline="") as handle:
        status_rows = list(csv.DictReader(handle))
    if len(status_rows) != 1:
        raise RuntimeError("MT5 calendar status must contain exactly one row")
    status = status_rows[0]
    if int(status["chunks_failed"]) != 0:
        raise RuntimeError("MT5 calendar exporter reported failed chunks")
    if status["date_to_server"] != REQUIRED_CALENDAR_END_SERVER:
        raise RuntimeError(
            f"MT5 calendar end is {status['date_to_server']}; required "
            f"{REQUIRED_CALENDAR_END_SERVER}"
        )
    audit = load_json(CALENDAR_AUDIT)
    if audit.get("valid") is not True or audit.get("source_sha256") != hashes["calendar_raw"]:
        raise RuntimeError("MT5 calendar audit or raw-source lineage failed")
    existing_zn = load_json(EXISTING_ZN_2025)
    if existing_zn.get("status") != "NORMALIZED_HASHED_AND_SEALED":
        raise RuntimeError("Existing ZN-2025 source is not sealed")
    return {
        "hashes": hashes,
        "calendar_status": status,
        "calendar_audit_valid": True,
        "existing_zn_2025_reused": True,
    }


def quote(client: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for request in REQUESTS:
        minimal = {
            key: request[key]
            for key in ("dataset", "symbols", "schema", "stype_in", "start", "end")
        }
        cost = float(client.metadata.get_cost(**minimal))
        count = int(client.metadata.get_record_count(**minimal))
        size = int(client.metadata.get_billable_size(**minimal))
        if not math.isfinite(cost) or cost < 0 or count <= 0 or size <= 0:
            raise RuntimeError(f"Invalid metadata quote for {request['request_id']}")
        output.append(
            {
                "request_id": request["request_id"],
                "request_fingerprint": canonical_hash(request),
                "estimated_cost_usd": cost,
                "estimated_record_count": count,
                "estimated_billable_size": size,
            }
        )
    return output


def load_or_initialize_manifest(
    path: Path,
    *,
    predecessors: dict[str, Any],
    estimates: list[dict[str, Any]],
    combined_estimate: float,
) -> dict[str, Any]:
    if path.exists():
        manifest = load_json(path)
        if manifest.get("version") != VERSION:
            raise RuntimeError("Existing acquisition manifest version changed")
        if manifest.get("requests") != list(REQUESTS):
            raise RuntimeError("Existing acquisition requests changed")
        if manifest.get("maximum_combined_cost_usd") != MAXIMUM_COMBINED_COST_USD:
            raise RuntimeError("Existing acquisition cap changed")
        return manifest
    manifest = {
        "version": VERSION,
        "status": "SUBMISSION_INTENT_RECORDED",
        "submission_intent_recorded_at": datetime.now(UTC).isoformat(),
        "requests": list(REQUESTS),
        "fresh_estimates": estimates,
        "fresh_combined_estimated_cost_usd": combined_estimate,
        "maximum_combined_cost_usd": MAXIMUM_COMBINED_COST_USD,
        "credit_sufficiency_basis": "USER_ATTESTED_NEW_ACCOUNT_WITH_FRESH_CREDITS",
        "credit_only_authorization": True,
        "card_charge_authorized": False,
        "api_key_recorded": False,
        "predecessors": predecessors,
        "jobs": {},
        "downloads": {},
        "normalizations": {},
        "market_values_human_or_model_inspected": False,
        "relationships_calculated": False,
        "outcomes_calculated": False,
    }
    write_json_atomic(path, manifest)
    return manifest


def submit_or_recover(client: Any, *, request: dict[str, Any], since: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for raw in client.batch.list_jobs(since=since):
        item = safe_mapping(raw)
        symbols = item.get("symbols")
        actual_symbols = (
            [part.strip() for part in str(symbols).split(",")]
            if isinstance(symbols, str)
            else list(symbols or [])
        )
        if (
            item.get("dataset") == request["dataset"]
            and actual_symbols == request["symbols"]
            and item.get("schema") == request["schema"]
            and item.get("stype_in") == request["stype_in"]
            and str(item.get("start", "")).startswith(request["start"].replace("Z", ""))
            and str(item.get("end", "")).startswith(request["end"].replace("Z", ""))
        ):
            matches.append(item)
    if len(matches) > 1:
        raise RuntimeError(f"Multiple matching jobs found for {request['request_id']}")
    if matches:
        response = matches[0]
        mode = "RECOVERED_EXISTING_JOB"
    else:
        kwargs = {key: value for key, value in request.items() if key != "request_id"}
        response = safe_mapping(client.batch.submit_job(**kwargs))
        mode = "NEW_JOB_SUBMITTED"
    job_id = str(response.get("id") or response.get("job_id") or "")
    if not job_id:
        raise RuntimeError(f"Databento returned no job ID for {request['request_id']}")
    return {
        "job_id": job_id,
        "submission_mode": mode,
        "response": response,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def normalize_twice(
    raw_files: list[Path],
    *,
    request: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite normalization: {output_dir}")
    with tempfile.TemporaryDirectory(prefix="gold-fade-normalize-", dir=output_dir.parent) as raw_temp:
        temporary = Path(raw_temp)
        primary = temporary / "primary"
        reference = temporary / "reference"
        first = normalize_once(raw_files, request=request, destination=primary)
        second = normalize_once(raw_files, request=request, destination=reference)
        first_inventory = directory_inventory(primary)
        second_inventory = directory_inventory(reference)
        if first != second or first_inventory != second_inventory:
            raise RuntimeError(f"Normalization reproduction failed for {request['request_id']}")
        shutil.copytree(primary, output_dir)
    payload = {
        "version": "GOLD_FADE_VALIDATION_NORMALIZATION_V0_1",
        "request_id": request["request_id"],
        "request": request,
        "request_fingerprint": canonical_hash(request),
        "source_files": inventory_paths(raw_files),
        "total_rows": first["total_rows"],
        "rows_by_symbol": first["rows_by_symbol"],
        "first_open_by_symbol": first["first_open_by_symbol"],
        "last_open_by_symbol": first["last_open_by_symbol"],
        "instrument_ids_by_symbol": first["instrument_ids_by_symbol"],
        "roll_transition_count_by_symbol": first["roll_transition_count_by_symbol"],
        "normalized_files": directory_inventory(output_dir),
        "reproduction": "TWO_COMPLETE_RUNS_BYTE_IDENTICAL",
        "market_values_human_or_model_inspected": False,
        "features_calculated": False,
        "relationships_calculated": False,
        "outcomes_calculated": False,
    }
    payload["normalization_hash"] = canonical_hash(payload)
    write_json_atomic(output_dir / "normalization.json", payload)
    payload["normalization_json_sha256"] = sha256(output_dir / "normalization.json")
    return payload


def normalize_once(
    raw_files: list[Path],
    *,
    request: dict[str, Any],
    destination: Path,
) -> dict[str, Any]:
    import databento as db
    import pandas as pd

    frames: list[Any] = []
    source_hash_by_file = {path: sha256(path) for path in raw_files}
    for source in raw_files:
        store = db.DBNStore.from_file(source)
        if str(store.schema) != request["schema"]:
            raise RuntimeError(f"Unexpected DBN schema in {source.name}: {store.schema}")
        frame = store.to_df(pretty_ts=True, map_symbols=True).reset_index()
        if frame.empty:
            continue
        required = (
            "ts_event",
            "instrument_id",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
        )
        missing = set(required).difference(frame.columns)
        if missing:
            raise RuntimeError(f"DBN fields missing in {source.name}: {sorted(missing)}")
        frame = frame[list(required)].copy()
        frame["source_file_sha256"] = source_hash_by_file[source]
        frame["source_row_ordinal"] = range(1, len(frame) + 1)
        frames.append(frame)
    if not frames:
        raise RuntimeError(f"No rows normalized for {request['request_id']}")
    combined = pd.concat(frames, ignore_index=True)
    combined["open_time"] = pd.to_datetime(combined.pop("ts_event"), utc=True)
    combined["available_at"] = combined["open_time"] + pd.Timedelta(minutes=1)
    combined["symbol"] = combined["symbol"].astype(str)
    expected_symbols = set(request["symbols"])
    observed_symbols = set(combined["symbol"].unique())
    if observed_symbols != expected_symbols:
        raise RuntimeError(
            f"Symbol mapping changed for {request['request_id']}: {observed_symbols}"
        )
    start = pd.Timestamp(request["start"])
    end = pd.Timestamp(request["end"])
    if not ((combined["open_time"] >= start) & (combined["open_time"] < end)).all():
        raise RuntimeError(f"Out-of-range row in {request['request_id']}")
    if (
        (combined["high"] < combined[["open", "close"]].max(axis=1)).any()
        or (combined["low"] > combined[["open", "close"]].min(axis=1)).any()
        or (combined["volume"] < 0).any()
    ):
        raise RuntimeError(f"Invalid OHLCV geometry in {request['request_id']}")
    combined.sort_values(["symbol", "open_time"], inplace=True, kind="mergesort")
    if combined.duplicated(["symbol", "open_time"]).any():
        raise RuntimeError(f"Duplicate symbol/open_time in {request['request_id']}")

    destination.mkdir(parents=True, exist_ok=False)
    rows_by_symbol: dict[str, int] = {}
    first_by_symbol: dict[str, str] = {}
    last_by_symbol: dict[str, str] = {}
    ids_by_symbol: dict[str, list[int]] = {}
    rolls_by_symbol: dict[str, int] = {}
    for symbol in request["symbols"]:
        selected = combined[combined["symbol"] == symbol].copy()
        rows_by_symbol[symbol] = int(len(selected))
        first_by_symbol[symbol] = selected["open_time"].iloc[0].isoformat()
        last_by_symbol[symbol] = selected["open_time"].iloc[-1].isoformat()
        ids_by_symbol[symbol] = sorted(int(value) for value in selected["instrument_id"].unique())
        rolls_by_symbol[symbol] = int((selected["instrument_id"].diff().fillna(0) != 0).sum())
        path = destination / f"{symbol.lower().replace('.', '_')}_ohlcv_1m.csv.gz"
        fields = (
            "source_record_id",
            "source_file_sha256",
            "source_row_ordinal",
            "open_time",
            "available_at",
            "continuous_symbol",
            "instrument_id",
            "open",
            "high",
            "low",
            "close",
            "volume",
        )
        with gzip_text_writer(path) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in selected.itertuples(index=False):
                record_id = canonical_hash(
                    {
                        "source_file_sha256": row.source_file_sha256,
                        "source_row_ordinal": int(row.source_row_ordinal),
                        "symbol": row.symbol,
                        "instrument_id": int(row.instrument_id),
                        "open_time": row.open_time.isoformat(),
                    }
                )
                writer.writerow(
                    {
                        "source_record_id": record_id,
                        "source_file_sha256": row.source_file_sha256,
                        "source_row_ordinal": int(row.source_row_ordinal),
                        "open_time": row.open_time.isoformat(),
                        "available_at": row.available_at.isoformat(),
                        "continuous_symbol": row.symbol,
                        "instrument_id": int(row.instrument_id),
                        "open": row.open,
                        "high": row.high,
                        "low": row.low,
                        "close": row.close,
                        "volume": row.volume,
                    }
                )
    return {
        "total_rows": int(len(combined)),
        "rows_by_symbol": rows_by_symbol,
        "first_open_by_symbol": first_by_symbol,
        "last_open_by_symbol": last_by_symbol,
        "instrument_ids_by_symbol": ids_by_symbol,
        "roll_transition_count_by_symbol": rolls_by_symbol,
    }


def inventory_paths(paths: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for path in sorted((Path(item).resolve() for item in paths), key=lambda item: str(item).lower()):
        if path.is_file():
            output.append(
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    return output


def directory_inventory(path: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(item.relative_to(path)).replace("\\", "/"),
            "bytes": item.stat().st_size,
            "sha256": sha256(item),
        }
        for item in sorted(path.rglob("*"), key=lambda value: str(value).lower())
        if item.is_file()
    ]


def gzip_text_writer(path: Path) -> io.TextIOWrapper:
    binary = path.open("wb")
    compressed = gzip.GzipFile(filename="", mode="wb", fileobj=binary, mtime=0)
    return io.TextIOWrapper(compressed, encoding="utf-8", newline="")


def api_key(env_file: Path) -> str:
    value = os.getenv("DATABENTO_API_KEY", "").strip()
    if value:
        return value
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("DATABENTO_API_KEY="):
            value = raw.split("=", 1)[1].strip().strip("\"").strip("'")
            if value:
                return value
    raise RuntimeError("DATABENTO_API_KEY is unavailable")


def safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        value = dict(value)
    return {
        str(key): json_safe(item)
        for key, item in value.items()
        if str(key).lower() not in {"api_key", "key", "secret", "token"}
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
            if str(key).lower() not in {"api_key", "key", "secret", "token"}
        }
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    main()
