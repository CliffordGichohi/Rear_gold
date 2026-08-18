#!/usr/bin/env python3
"""Acquire the sealed pre-2025 CME rates dataset used by edge research.

The script is deliberately idempotent: after a batch job is submitted, its ID
and exact request fingerprint are persisted before any polling or download.
Re-running the script resumes that job instead of submitting another chargeable
request.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import databento as db
import pandas as pd

REQUEST: dict[str, Any] = {
    "dataset": "GLBX.MDP3",
    "symbols": ["ZT.v.0", "ZN.v.0", "ZQ.v.0", "SR3.v.0"],
    "schema": "ohlcv-1m",
    "stype_in": "continuous",
    "stype_out": "instrument_id",
    "start": "2021-07-01T00:00:00Z",
    "end": "2025-01-01T00:00:00Z",
    "encoding": "dbn",
    "compression": "zstd",
    "split_duration": "year",
}
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "raw" / "databento_cme_pre2025"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("estimate", "submit", "recover", "status", "download", "normalize"),
        help="Operation to perform. 'submit' safely resumes an existing job.",
    )
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--max-cost",
        type=float,
        default=15.0,
        help="Refuse a new submission above this USD amount.",
    )
    return parser.parse_args()


def api_key(env_file: Path) -> str:
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


def request_fingerprint() -> str:
    encoded = json.dumps(REQUEST, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("request_fingerprint") != request_fingerprint():
        raise RuntimeError(
            "Existing manifest belongs to a different request; "
            "use a different output directory.",
        )
    return manifest


def get_cost(client: db.Historical) -> float:
    return float(
        client.metadata.get_cost(
            dataset=REQUEST["dataset"],
            symbols=REQUEST["symbols"],
            schema=REQUEST["schema"],
            stype_in=REQUEST["stype_in"],
            start=REQUEST["start"],
            end=REQUEST["end"],
        ),
    )


def job_id_from(response: dict[str, Any]) -> str:
    value = response.get("id") or response.get("job_id")
    if not value:
        raise RuntimeError("Databento returned no batch job ID")
    return str(value)


def submit_or_resume(
    client: db.Historical,
    manifest_path: Path,
    max_cost: float,
) -> dict[str, Any]:
    existing = read_manifest(manifest_path)
    if existing and existing.get("job_id"):
        print(f"RESUME job_id={existing['job_id']}")
        return existing

    estimated_cost = get_cost(client)
    print(f"ESTIMATED_COST_USD={estimated_cost:.6f}")
    if estimated_cost > max_cost:
        raise RuntimeError(
            f"Estimated cost ${estimated_cost:.6f} exceeds ${max_cost:.2f} cap",
        )

    response = client.batch.submit_job(
        dataset=REQUEST["dataset"],
        symbols=REQUEST["symbols"],
        schema=REQUEST["schema"],
        stype_in=REQUEST["stype_in"],
        stype_out=REQUEST["stype_out"],
        start=REQUEST["start"],
        end=REQUEST["end"],
        encoding=REQUEST["encoding"],
        compression=REQUEST["compression"],
        split_duration=REQUEST["split_duration"],
        split_symbols=False,
    )
    manifest = {
        "request": REQUEST,
        "request_fingerprint": request_fingerprint(),
        "estimated_cost_usd": estimated_cost,
        "job_id": job_id_from(response),
        "submitted_at": datetime.now(UTC).isoformat(),
        "submission_response": response,
    }
    write_manifest(manifest_path, manifest)
    print(f"SUBMITTED job_id={manifest['job_id']}")
    return manifest


def recover_submitted_job(
    client: db.Historical,
    manifest_path: Path,
) -> dict[str, Any]:
    existing = read_manifest(manifest_path)
    if existing and existing.get("job_id"):
        print(f"RESUME job_id={existing['job_id']}")
        return existing

    matches = [
        job
        for job in client.batch.list_jobs(since="2026-07-01T00:00:00Z")
        if job.get("dataset") == REQUEST["dataset"]
        and job.get("symbols") == ",".join(REQUEST["symbols"])
        and job.get("schema") == REQUEST["schema"]
        and job.get("stype_in") == REQUEST["stype_in"]
        and str(job.get("start", "")).startswith("2021-07-01T00:00:00")
        and str(job.get("end", "")).startswith("2025-01-01T00:00:00")
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one matching batch job; found {len(matches)}"
        )

    details = matches[0]
    manifest = {
        "request": REQUEST,
        "request_fingerprint": request_fingerprint(),
        "estimated_cost_usd": 11.255905,
        "job_id": job_id_from(details),
        "recovered_at": datetime.now(UTC).isoformat(),
        "job_details": details,
    }
    write_manifest(manifest_path, manifest)
    print(f"RECOVERED job_id={manifest['job_id']}")
    return manifest


def update_status(
    client: db.Historical,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    details = client.batch.get_job_details(str(manifest["job_id"]))
    manifest["last_status_at"] = datetime.now(UTC).isoformat()
    manifest["job_details"] = details
    write_manifest(manifest_path, manifest)
    state = details.get("state", "unknown")
    print(f"JOB_STATE={state}")
    return manifest


def download(
    client: db.Historical,
    output_dir: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    manifest = update_status(client, manifest_path, manifest)
    state = str(manifest["job_details"].get("state", "")).lower()
    if state != "done":
        raise RuntimeError(f"Batch job is not ready (state={state or 'unknown'})")

    job_id = str(manifest["job_id"])
    remote_files = client.batch.list_files(job_id)
    downloaded = client.batch.download(job_id=job_id, output_dir=output_dir)
    local_files = [
        {
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(downloaded)
        if path.is_file()
    ]
    manifest["remote_files"] = remote_files
    manifest["local_files"] = local_files
    manifest["downloaded_at"] = datetime.now(UTC).isoformat()
    write_manifest(manifest_path, manifest)
    print(f"DOWNLOADED_FILES={len(local_files)}")
    print(f"DOWNLOADED_BYTES={sum(item['size_bytes'] for item in local_files)}")


def normalize(output_dir: Path, manifest_path: Path, manifest: dict[str, Any]) -> None:
    job_dir = output_dir / str(manifest["job_id"])
    source_files = sorted(
        path for pattern in ("*.dbn", "*.dbn.zst") for path in job_dir.glob(pattern)
    )
    if not source_files:
        raise RuntimeError("No downloaded DBN files were found")

    normalized_dir = job_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    expected_symbols = set(REQUEST["symbols"])
    boundary = pd.Timestamp(REQUEST["end"])
    summaries: list[dict[str, Any]] = []
    total_rows = 0

    for source in source_files:
        suffix = ".dbn.zst" if source.name.endswith(".dbn.zst") else ".dbn"
        destination = normalized_dir / f"{source.name.removesuffix(suffix)}.csv.gz"
        temporary = destination.with_suffix(".tmp")
        store = db.DBNStore.from_file(source)
        if str(store.schema) != REQUEST["schema"]:
            raise RuntimeError(f"Unexpected schema in {source.name}: {store.schema}")

        rows = 0
        first_open: pd.Timestamp | None = None
        last_open: pd.Timestamp | None = None
        symbols_seen: set[str] = set()
        instruments: dict[str, set[int]] = {}
        last_instrument: dict[str, int] = {}
        roll_transitions: dict[str, int] = {}
        write_header = True

        with gzip.open(temporary, mode="wt", encoding="utf-8", newline="") as handle:
            chunks = store.to_df(
                pretty_ts=True,
                map_symbols=True,
                count=250_000,
            )
            for chunk in chunks:
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
                missing = required.difference(frame.columns)
                if missing:
                    raise RuntimeError(
                        f"{source.name} is missing columns: {sorted(missing)}",
                    )
                if (
                    (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
                    or (frame["low"] > frame[["open", "close"]].min(axis=1)).any()
                    or (frame["volume"] < 0).any()
                ):
                    raise RuntimeError(f"Invalid OHLCV values in {source.name}")
                if (frame["ts_event"] >= boundary).any():
                    raise RuntimeError(f"Locked 2025 data found in {source.name}")

                frame = frame[
                    [
                        "ts_event",
                        "instrument_id",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "symbol",
                    ]
                ].rename(columns={"ts_event": "open_time"})
                frame["available_at"] = frame["open_time"] + pd.Timedelta(minutes=1)
                frame = frame[
                    [
                        "open_time",
                        "available_at",
                        "symbol",
                        "instrument_id",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    ]
                ]
                current_symbols = set(frame["symbol"].astype(str).unique())
                unexpected = current_symbols.difference(expected_symbols)
                if unexpected:
                    raise RuntimeError(
                        f"Unexpected mapped symbols in {source.name}: {sorted(unexpected)}",
                    )
                symbols_seen.update(current_symbols)
                for symbol, group in frame.groupby("symbol", sort=False):
                    symbol_name = str(symbol)
                    ids = [int(value) for value in group["instrument_id"]]
                    instruments.setdefault(symbol_name, set()).update(ids)
                    for instrument_id in ids:
                        previous = last_instrument.get(symbol_name)
                        if previous is not None and previous != instrument_id:
                            roll_transitions[symbol_name] = (
                                roll_transitions.get(symbol_name, 0) + 1
                            )
                        last_instrument[symbol_name] = instrument_id

                chunk_first = pd.Timestamp(frame["open_time"].iloc[0])
                chunk_last = pd.Timestamp(frame["open_time"].iloc[-1])
                first_open = (
                    chunk_first if first_open is None else min(first_open, chunk_first)
                )
                last_open = (
                    chunk_last if last_open is None else max(last_open, chunk_last)
                )
                rows += len(frame)
                frame.to_csv(handle, index=False, header=write_header)
                write_header = False

        temporary.replace(destination)
        total_rows += rows
        summaries.append(
            {
                "source": str(source.resolve()),
                "source_sha256": sha256(source),
                "normalized": str(destination.resolve()),
                "normalized_sha256": sha256(destination),
                "rows": rows,
                "first_open": first_open.isoformat()
                if first_open is not None
                else None,
                "last_open": last_open.isoformat() if last_open is not None else None,
                "symbols": sorted(symbols_seen),
                "instrument_ids": {
                    symbol: sorted(values)
                    for symbol, values in sorted(instruments.items())
                },
                "roll_transitions": dict(sorted(roll_transitions.items())),
            },
        )

    normalization = {
        "request_fingerprint": request_fingerprint(),
        "normalized_at": datetime.now(UTC).isoformat(),
        "availability_rule": "available_at = OHLCV interval start + 1 minute",
        "locked_holdout": "2025 not loaded",
        "total_rows": total_rows,
        "files": summaries,
    }
    write_manifest(normalized_dir / "normalization.json", normalization)
    manifest["normalization"] = normalization
    write_manifest(manifest_path, manifest)
    print(f"NORMALIZED_ROWS={total_rows}")
    print(f"NORMALIZED_FILES={len(summaries)}")


def main() -> None:
    args = parse_args()
    manifest_path = args.output_dir / "manifest.json"
    client = db.Historical(api_key(args.env_file))

    if args.action == "estimate":
        print(f"ESTIMATED_COST_USD={get_cost(client):.6f}")
        return

    manifest = read_manifest(manifest_path)
    if args.action == "submit":
        manifest = submit_or_resume(client, manifest_path, args.max_cost)
        update_status(client, manifest_path, manifest)
        return
    if args.action == "recover":
        manifest = recover_submitted_job(client, manifest_path)
        update_status(client, manifest_path, manifest)
        return

    if not manifest or not manifest.get("job_id"):
        raise RuntimeError("No submitted job exists; run the 'submit' action first")

    if args.action == "status":
        update_status(client, manifest_path, manifest)
        return
    if args.action == "normalize":
        normalize(args.output_dir, manifest_path, manifest)
        return

    download(client, args.output_dir, manifest_path, manifest)


if __name__ == "__main__":
    main()
