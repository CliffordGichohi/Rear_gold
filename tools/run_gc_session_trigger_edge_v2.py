#!/usr/bin/env python3
"""Memory-bounded, outcome-blind GC Session Trigger Edge Discovery V2.

V2 preserves every analytical definition from V1 Milestone 2-R2.  It changes
only orchestration: isolated feature workers, sequential primary/reference
passes, immutable fragments, append-only checkpoints, and streaming assembly.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import materialize_gc_session_trigger_edge_m2 as m2
import run_gc_session_trigger_edge_m2r1a1 as a1
import run_gc_session_trigger_edge_m2r2 as r2


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "GC_SESSION_TRIGGER_EDGE_DISCOVERY_CONTRACT_V2.md"
PROTOCOL_PATH = ROOT / "research_manifests/gc_session_trigger_edge_v2_protocol_v01.json"
FREEZE_PATH = ROOT / "research_manifests/gc_session_trigger_edge_v2_freeze_v01.json"
DEFAULT_ENGINEERING_OUTPUT = ROOT / "research_artifacts/gc_session_trigger_edge_v2_engineering_v01"
DEFAULT_OUTPUT = ROOT / "research_artifacts/gc_session_trigger_edge_v2_v01"

RSS_CAP_BYTES = 4 * 1024**3
RSS_GUARD_BYTES = 3840 * 1024**2
RSS_SAMPLE_SECONDS = 0.05
EXPECTED_ENGINEERING_DATES = (
    "2024-01-05",
    "2024-01-09",
    "2024-01-11",
    "2024-01-30",
    "2024-01-31",
    "2024-03-20",
)
IMPLEMENTATIONS = ("primary", "reference")
SESSIONS = ("LONDON", "NEW_YORK")
V1_FINAL_SHA256 = "ba4eaebe7d0e60eed3e4edbb11f8374c68cf14379716f65b8f482e6213301594"
V1_FINAL_RECEIPT = "4bc9607d461ac1a0c550e1bb38f0cdc881311b7ade4bb200877e9da46076070f"
V1_STATUS = "FAIL_M2_R2_EXECUTION_BRANCH_TERMINATED"
UINT64 = struct.Struct("<Q")


class ResourceCapExceeded(RuntimeError):
    """A monitored worker reached the frozen guard threshold."""


class WorkerFailed(RuntimeError):
    """An isolated feature worker failed before creating a checkpoint."""


@dataclass(frozen=True, slots=True)
class RunPaths:
    acquisition: Path
    step5b2: Path
    context: Path
    xau: Path
    old_m2: Path
    old_r1: Path
    old_a1: Path
    old_v1: Path
    output: Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
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
            handle.write(value)
            if not value.endswith("\n"):
                handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def receipt_valid(value: Mapping[str, Any], field: str) -> bool:
    return value.get(field) == canonical_hash({**value, field: None})


def verify_record(record: Mapping[str, Any]) -> Path:
    path = Path(str(record["path"]))
    if (
        not path.is_file()
        or path.stat().st_size != int(record["bytes"])
        or sha256_file(path) != str(record["sha256"])
    ):
        raise ValueError(f"Artifact binding failed: {path}")
    return path


def safe_name(row_id: str) -> str:
    readable = "".join(character.lower() if character.isalnum() else "_" for character in row_id)
    readable = "_".join(part for part in readable.split("_") if part)
    return f"{readable[:72]}_{hashlib.sha256(row_id.encode('utf-8')).hexdigest()[:16]}"


def proc_memory_bytes(pid: int | None = None) -> dict[str, int]:
    target = Path(f"/proc/{pid or os.getpid()}/status")
    output = {"rss_bytes": 0, "hwm_bytes": 0}
    if not target.is_file():
        return output
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            output["rss_bytes"] = int(line.split()[1]) * 1024
        elif line.startswith("VmHWM:"):
            output["hwm_bytes"] = int(line.split()[1]) * 1024
    return output


def table_buffer_checksum(table: pa.Table) -> str:
    digest = hashlib.sha256()
    digest.update(UINT64.pack(table.num_rows))
    for name in table.column_names:
        array = table[name].combine_chunks()
        digest.update(name.encode("utf-8"))
        digest.update(str(array.type).encode("ascii"))
        digest.update(UINT64.pack(len(array)))
        digest.update(UINT64.pack(array.null_count))
        for buffer in array.buffers():
            if buffer is None:
                digest.update(UINT64.pack(0))
            else:
                payload = memoryview(buffer)
                digest.update(UINT64.pack(len(payload)))
                digest.update(payload)
    return digest.hexdigest()


def compact_table_arrays(table: pa.Table, columns: Sequence[str]) -> dict[str, np.ndarray[Any, Any]]:
    """Represent single-character enum columns without per-row Python objects."""
    output: dict[str, np.ndarray[Any, Any]] = {}
    for name in columns:
        column = table[name].combine_chunks()
        if pa.types.is_timestamp(column.type):
            output[name] = column.cast(pa.int64()).to_numpy(zero_copy_only=False)
        elif pa.types.is_string(column.type):
            output[name] = np.fromiter(
                ("" if value is None else str(value.as_py()) for value in column),
                dtype="<U1",
                count=len(column),
            )
        else:
            output[name] = column.to_numpy(zero_copy_only=False)
    return output


def selected_flags_by_ordinal(
    arrays: Mapping[str, np.ndarray[Any, Any]],
    anchor: pa.Table,
    selected_ordinals: Sequence[Any],
) -> dict[int, int]:
    wanted_values = sorted({int(value) for value in selected_ordinals if value is not None})
    ordinals = arrays["source_row_ordinal"]
    flags = arrays["flags"]
    output: dict[int, int] = {}
    if wanted_values:
        wanted = np.asarray(wanted_values, dtype=ordinals.dtype)
        if len(ordinals) < 2 or bool(np.all(ordinals[1:] >= ordinals[:-1])):
            positions = np.searchsorted(ordinals, wanted)
            valid = positions < len(ordinals)
            for value, position, exists in zip(wanted, positions, valid, strict=True):
                if bool(exists) and int(ordinals[int(position)]) == int(value):
                    output[int(value)] = int(flags[int(position)])
        else:
            remaining = set(wanted_values)
            for ordinal, flag in zip(ordinals, flags, strict=True):
                key = int(ordinal)
                if key in remaining:
                    output[key] = int(flag)
                    remaining.remove(key)
                    if not remaining:
                        break
    output[int(anchor["source_row_ordinal"][0].as_py())] = int(anchor["flags"][0].as_py())
    return output


def atomic_parquet(path: Path, table: pa.Table, row_group_size: int) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    if temporary.exists():
        raise FileExistsError(temporary)
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=max(1, row_group_size),
    )
    os.replace(temporary, path)


def atomic_bytes(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def encode_mask(mask: Sequence[bool]) -> bytes:
    packed = np.packbits(np.asarray(mask, dtype=np.uint8), bitorder="little").tobytes()
    return UINT64.pack(len(mask)) + packed


def decode_mask(path: Path) -> list[bool]:
    payload = path.read_bytes()
    if len(payload) < UINT64.size:
        raise ValueError(f"Invalid mask payload: {path}")
    count = UINT64.unpack(payload[: UINT64.size])[0]
    bits = np.unpackbits(np.frombuffer(payload[UINT64.size :], dtype=np.uint8), bitorder="little")
    if len(bits) < count:
        raise ValueError(f"Truncated mask payload: {path}")
    return [bool(value) for value in bits[:count]]


def verify_v1(paths: RunPaths) -> dict[str, Any]:
    predecessor = r2.verify_freeze(paths.old_m2, paths.old_r1, paths.old_a1, paths.old_v1)
    final_path = paths.old_v1 / "final_seal.json"
    manifest_path = paths.old_v1 / "manifest.json"
    verdict_path = paths.old_v1 / "verdict.json"
    failure_path = paths.old_v1 / "execution_failure.json"
    if sha256_file(final_path) != V1_FINAL_SHA256:
        raise ValueError("V1 R2 final seal hash changed")
    final = read_json(final_path)
    manifest = read_json(manifest_path)
    verdict = read_json(verdict_path)
    failure = read_json(failure_path)
    for value, field in (
        (final, "final_seal_receipt"),
        (manifest, "manifest_receipt"),
        (verdict, "verdict_receipt"),
    ):
        if not receipt_valid(value, field):
            raise ValueError(f"V1 receipt failed: {field}")
    if final.get("status") != V1_STATUS or final.get("final_seal_receipt") != V1_FINAL_RECEIPT:
        raise ValueError("V1 terminal disposition changed")
    if failure.get("error_type") != "KernelOOMKill" or verdict.get("attempts") != 1:
        raise ValueError("V1 OOM failure evidence changed")
    if final.get("manifest_sha256") != sha256_file(manifest_path) or final.get("verdict_sha256") != sha256_file(verdict_path):
        raise ValueError("V1 final bindings changed")
    for record in manifest.get("artifacts", []):
        verify_record(record)
    return {
        **predecessor,
        "v1_m2r2_status": final["status"],
        "v1_m2r2_final_seal_receipt": final["final_seal_receipt"],
        "v1_m2r2_final_sha256": sha256_file(final_path),
        "v1_m2r2_error_type": failure["error_type"],
        "v1_m2r2_attempts": verdict["attempts"],
        "v1_partial_outputs_research_credit": "NONE",
    }


def verify_v2_freeze(paths: RunPaths) -> dict[str, Any]:
    if not FREEZE_PATH.is_file():
        raise FileNotFoundError(FREEZE_PATH)
    freeze = read_json(FREEZE_PATH)
    if freeze.get("status") != "SEALED_AFTER_ENGINEERING_PASS_BEFORE_DEVELOPMENT_METADATA":
        raise ValueError("V2 freeze status is invalid")
    if not receipt_valid(freeze, "freeze_receipt"):
        raise ValueError("V2 freeze receipt failed")
    for key, path in (
        ("contract", CONTRACT_PATH),
        ("protocol", PROTOCOL_PATH),
        ("implementation", Path(__file__)),
    ):
        record = freeze.get(key, {})
        if str(record.get("sha256")) != sha256_file(path):
            raise ValueError(f"V2 frozen {key} changed")
    proof_path = Path(str(freeze["engineering_proof"]["path"]))
    verify_record(freeze["engineering_proof"])
    proof = read_json(proof_path)
    if proof.get("status") != "PASS_V2_ENGINEERING_REPRODUCTION_AND_RESOURCE_GATE" or not receipt_valid(proof, "proof_receipt"):
        raise ValueError("V2 engineering proof is invalid")
    predecessor = verify_v1(paths)
    if predecessor["v1_m2r2_final_seal_receipt"] != freeze["predecessors"]["v1_m2r2_final_seal_receipt"]:
        raise ValueError("V2 predecessor binding changed")
    return freeze


def worker_feature(spec_path: Path) -> None:
    spec = read_json(spec_path)
    implementation = str(spec["implementation"])
    if implementation not in IMPLEMENTATIONS:
        raise ValueError("Invalid implementation")
    output = Path(str(spec["feature_path"]))
    mask_path = Path(str(spec["mask_path"]))
    diagnostic_path = Path(str(spec["diagnostic_path"]))
    for path in (output, mask_path, diagnostic_path):
        if path.exists():
            raise FileExistsError(path)
    s5c = m2._load_module(m2.STEP5C_ENGINE_PATH, f"gc_v2_worker_s5c_{os.getpid()}")
    base = m2._load_module(m2.BASE_ENGINE_PATH, f"gc_v2_worker_base_{os.getpid()}")
    mbo_path = Path(str(spec["mbo_path"]))
    mbp_path = Path(str(spec["mbp_path"]))
    start = int(spec["window_start_inclusive_ns"])
    end = int(spec["window_end_exclusive_ns"])
    day_start = int(spec["utc_day_start_ns"])
    if implementation == "primary":
        mbo = m2._source_table(mbo_path, base.MBO_COLUMNS, start, end, s5c)
        mbp = m2._source_table(mbp_path, base.MBP_COLUMNS, start, end, s5c)
        anchor = s5c._read_exact_anchor(mbp_path, base.MBP_COLUMNS, start, day_start)
    else:
        mbo = a1.read_range_reference_ns(mbo_path, base.MBO_COLUMNS, start, end)
        mbp = a1.read_range_reference_ns(mbp_path, base.MBP_COLUMNS, start, end)
        anchor = r2.read_anchor_reference(mbp_path, base.MBP_COLUMNS, start, day_start)
    mbo_rows, mbp_rows, anchor_rows = mbo.num_rows, mbp.num_rows, anchor.num_rows
    mbo_identity = table_buffer_checksum(mbo)
    mbp_identity = table_buffer_checksum(mbp)
    anchor_identity = table_buffer_checksum(anchor)
    mbo_arrays = compact_table_arrays(mbo, base.MBO_COLUMNS)
    mbp_arrays = compact_table_arrays(mbp, base.MBP_COLUMNS)
    del mbo, mbp
    gc.collect()
    try:
        pa.default_memory_pool().release_unused()
    except Exception:
        pass
    s5c._assert_source_order(mbo_arrays, f"MBO-{implementation}", str(spec["row_id"]))
    s5c._assert_source_order(mbp_arrays, f"MBP-{implementation}", str(spec["row_id"]))
    row = dict(spec["feature_row"])
    s5c.WINDOW_BUCKETS = m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION
    if implementation == "primary":
        raw, technical = s5c._primary_window_features(row, mbo_arrays, mbp_arrays, anchor, base)
        selected_flags = selected_flags_by_ordinal(mbp_arrays, anchor, raw["state_source_row_ordinal"])
        columns, mask, policy = r2.apply_policy_primary(
            str(spec["row_id"]), raw, selected_flags, base
        )
    else:
        raw, technical = s5c._reference_window_features(row, mbo_arrays, mbp_arrays, anchor, base)
        selected_flags = selected_flags_by_ordinal(mbp_arrays, anchor, raw["state_source_row_ordinal"])
        columns, mask, policy = r2.apply_policy_reference(
            str(spec["row_id"]), raw, selected_flags, base
        )
    del mbo_arrays, mbp_arrays, anchor, raw, selected_flags
    gc.collect()
    try:
        pa.default_memory_pool().release_unused()
    except Exception:
        pass
    technical["raw_state_available_bucket_closes"] += int(technical.get("state_available_bucket_closes", 0))
    technical["state_available_bucket_closes"] = int(policy["post_policy_state_available_buckets"])
    technical["raw_terminal_crossed_bucket_closes"] += int(policy["raw_terminal_crossed_bucket_closes"])
    technical["technical_unavailable_bucket_closes"] += int(policy["technical_unavailable_bucket_closes"])
    technical["technical_unavailable_ofi_buckets"] += int(policy["technical_unavailable_ofi_buckets"])
    technical["unavailability_latch_starts"] += int(policy["unavailability_latch_starts"])
    technical["valid_recovery_boundaries"] += int(policy["valid_recovery_boundaries"])
    technical["crossed_non_f_last_failures"] += int(policy["crossed_non_f_last_failures"])
    technical["invalid_state_values_retained"] += int(policy["invalid_state_values_retained"])
    technical["continuous_crossed_bucket_closes"] = int(policy["post_policy_crossed_bucket_closes"])
    table = pa.Table.from_pydict(columns, schema=base.FEATURE_SCHEMA)
    if table.num_rows != m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION:
        raise ValueError("Feature worker did not produce 18,900 rows")
    atomic_parquet(output, table, m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION)
    atomic_bytes(mask_path, encode_mask(mask))
    fingerprint = s5c._parquet_hashes(
        output,
        base.FEATURE_SCHEMA,
        m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION,
        s5c._schema_hash(base.FEATURE_SCHEMA),
    )
    memory = proc_memory_bytes()
    diagnostic = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_FEATURE_WORKER_V1_0",
        "status": "PASS_FEATURE_WORKER",
        "completed_at_utc": utc_now(),
        "classification": str(spec["classification"]),
        "row_id": str(spec["row_id"]),
        "implementation": implementation,
        "source": {
            "mbo_rows": mbo_rows,
            "mbp10_rows": mbp_rows,
            "anchor_rows": anchor_rows,
            "mbo_identity_checksum": mbo_identity,
            "mbp10_identity_checksum": mbp_identity,
            "anchor_identity_checksum": anchor_identity,
        },
        "feature": {"file": file_record(output), "fingerprint": fingerprint},
        "unavailable_mask": {
            "file": file_record(mask_path),
            "unavailable_buckets": int(sum(mask)),
            "checksum": hashlib.sha256(encode_mask(mask)).hexdigest(),
        },
        "technical": dict(sorted(technical.items())),
        "policy": policy,
        "worker_memory": memory,
        "outcomes_opened_or_joined": False,
        "relationships_candidates_execution_trades_or_pnl_calculated": False,
        "year_2025_or_2026_accessed": False,
    }
    diagnostic["diagnostic_receipt"] = canonical_hash({**diagnostic, "diagnostic_receipt": None})
    write_json_exclusive(diagnostic_path, diagnostic)
    print(
        json.dumps(
            {
                "status": diagnostic["status"],
                "row_id": diagnostic["row_id"],
                "implementation": implementation,
                "outcomes": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def quarantine_uncommitted(paths: Sequence[Path], quarantine_root: Path, label: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    candidates: list[Path] = []
    for path in paths:
        if path.exists():
            candidates.append(path)
        candidates.extend(sorted(path.parent.glob(path.name + ".tmp.*")))
    for source in candidates:
        record = file_record(source)
        directory = quarantine_root / safe_name(label)
        destination = directory / f"{source.name}.{record['sha256']}.orphan"
        destination.parent.mkdir(parents=True, exist_ok=True)
        sequence = 1
        while destination.exists():
            if sha256_file(destination) != record["sha256"]:
                raise ValueError("Quarantine hash collision")
            destination = directory / f"{source.name}.{record['sha256']}.{sequence:04d}.orphan"
            sequence += 1
        os.replace(source, destination)
        records.append({**record, "quarantined_path": str(destination)})
    if records:
        evidence = {
            "version": "GC_SESSION_TRIGGER_EDGE_V2_QUARANTINE_V1_0",
            "classification": "UNCOMMITTED_TECHNICAL_OUTPUT_NEVER_USED_AS_INPUT",
            "label": label,
            "quarantined_at_utc": utc_now(),
            "files": records,
            "receipt": None,
        }
        evidence["receipt"] = canonical_hash({**evidence, "receipt": None})
        evidence_path = quarantine_root / safe_name(label) / f"record_{evidence['receipt']}.json"
        write_json_exclusive(evidence_path, evidence)
    return records


def run_feature_child(
    spec_path: Path,
    monitor_path: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, Any]:
    for path in (monitor_path, stdout_path, stderr_path):
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "MALLOC_ARENA_MAX": "2",
            "OMP_NUM_THREADS": "1",
            "ARROW_NUM_THREADS": "1",
        }
    )
    with stdout_path.open("xb") as stdout_handle, stderr_path.open("xb") as stderr_handle:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "feature-worker", "--spec", str(spec_path)],
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=environment,
        )
        maximum_rss = 0
        samples = 0
        guard_triggered = False
        while process.poll() is None:
            memory = proc_memory_bytes(process.pid)
            maximum_rss = max(maximum_rss, int(memory["rss_bytes"]), int(memory["hwm_bytes"]))
            samples += 1
            if maximum_rss >= RSS_GUARD_BYTES:
                guard_triggered = True
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                break
            time.sleep(RSS_SAMPLE_SECONDS)
        return_code = int(process.wait())
    monitor = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_RESOURCE_MONITOR_V1_0",
        "completed_at_utc": utc_now(),
        "spec_sha256": sha256_file(spec_path),
        "worker_pid": process.pid,
        "samples": samples,
        "sampling_interval_seconds": RSS_SAMPLE_SECONDS,
        "maximum_observed_rss_bytes": maximum_rss,
        "guard_rss_bytes": RSS_GUARD_BYTES,
        "formal_cap_bytes": RSS_CAP_BYTES,
        "guard_triggered": guard_triggered,
        "return_code": return_code,
        "stdout": file_record(stdout_path),
        "stderr": file_record(stderr_path),
        "monitor_receipt": None,
    }
    monitor["monitor_receipt"] = canonical_hash({**monitor, "monitor_receipt": None})
    write_json_exclusive(monitor_path, monitor)
    if guard_triggered:
        raise ResourceCapExceeded(
            f"Worker reached frozen guard threshold: {maximum_rss} >= {RSS_GUARD_BYTES}"
        )
    if return_code != 0:
        raise WorkerFailed(
            f"Feature worker failed with return code {return_code}; stderr_sha256={sha256_file(stderr_path)}"
        )
    return monitor


def pass_paths(output: Path, row_id: str, implementation: str) -> dict[str, Path]:
    name = safe_name(row_id)
    return {
        "feature": output / "fragments" / implementation / f"{name}.features.parquet",
        "mask": output / "fragments" / implementation / f"{name}.unavailable_mask.bin",
        "diagnostic": output / "fragments" / implementation / f"{name}.diagnostic.json",
        "spec": output / "specs" / implementation / f"{name}.json",
        "checkpoint": output / "checkpoints" / "passes" / f"{name}.{implementation}.json",
    }


def make_worker_spec(
    *,
    output: Path,
    row_id: str,
    classification: str,
    implementation: str,
    mbo_path: Path,
    mbp_path: Path,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    paths = pass_paths(output, row_id, implementation)
    feature_row = {
        "window_start_inclusive_ns": int(row["window_start_inclusive_ns"]),
        "window_end_exclusive_ns": int(row["window_end_exclusive_ns"]),
        "expected_instrument_id": int(row["expected_instrument_id"]),
        "bucket_index_start_inclusive": int(row["bucket_index_start_inclusive"]),
        "session_code": str(row["session_code"]),
    }
    return {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_WORKER_SPEC_V1_0",
        "classification": classification,
        "row_id": row_id,
        "implementation": implementation,
        "mbo_path": str(mbo_path),
        "mbp_path": str(mbp_path),
        "window_start_inclusive_ns": int(row["window_start_inclusive_ns"]),
        "window_end_exclusive_ns": int(row["window_end_exclusive_ns"]),
        "utc_day_start_ns": int(row["utc_day_start_ns"]),
        "feature_row": feature_row,
        "feature_path": str(paths["feature"]),
        "mask_path": str(paths["mask"]),
        "diagnostic_path": str(paths["diagnostic"]),
        "outcomes_permitted": False,
    }


def ensure_feature_pass(
    *,
    output: Path,
    row_id: str,
    classification: str,
    implementation: str,
    mbo_path: Path,
    mbp_path: Path,
    row: Mapping[str, Any],
    invocation: int,
) -> dict[str, Any]:
    paths = pass_paths(output, row_id, implementation)
    if paths["checkpoint"].is_file():
        checkpoint = read_json(paths["checkpoint"])
        if not receipt_valid(checkpoint, "checkpoint_receipt"):
            raise ValueError("Pass checkpoint receipt failed")
        for key in ("feature", "mask", "diagnostic", "spec", "monitor"):
            verify_record(checkpoint["files"][key])
        return checkpoint
    quarantine_uncommitted(
        [paths["feature"], paths["mask"], paths["diagnostic"]],
        output / "quarantine",
        f"{row_id}:{implementation}:invocation:{invocation}",
    )
    spec = make_worker_spec(
        output=output,
        row_id=row_id,
        classification=classification,
        implementation=implementation,
        mbo_path=mbo_path,
        mbp_path=mbp_path,
        row=row,
    )
    if paths["spec"].is_file():
        if read_json(paths["spec"]) != spec:
            raise ValueError("Frozen worker spec changed")
    else:
        write_json_exclusive(paths["spec"], spec)
    name = safe_name(row_id)
    monitor_path = output / "resource" / f"{name}.{implementation}.invocation_{invocation:04d}.json"
    stdout_path = output / "logs" / f"{name}.{implementation}.invocation_{invocation:04d}.stdout.log"
    stderr_path = output / "logs" / f"{name}.{implementation}.invocation_{invocation:04d}.stderr.log"
    monitor = run_feature_child(paths["spec"], monitor_path, stdout_path, stderr_path)
    diagnostic = read_json(paths["diagnostic"])
    if diagnostic.get("status") != "PASS_FEATURE_WORKER" or not receipt_valid(diagnostic, "diagnostic_receipt"):
        raise ValueError("Feature-worker diagnostic failed")
    worker_hwm = int(diagnostic["worker_memory"]["hwm_bytes"])
    observed = max(worker_hwm, int(monitor["maximum_observed_rss_bytes"]))
    if observed > RSS_CAP_BYTES:
        raise ResourceCapExceeded(f"Worker exceeded formal 4-GiB cap: {observed}")
    checkpoint = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_PASS_CHECKPOINT_V1_0",
        "status": "PASS_IMMUTABLE_FEATURE_PASS",
        "committed_at_utc": utc_now(),
        "classification": classification,
        "row_id": row_id,
        "implementation": implementation,
        "source": diagnostic["source"],
        "feature_fingerprint": diagnostic["feature"]["fingerprint"],
        "technical": diagnostic["technical"],
        "policy": diagnostic["policy"],
        "unavailable_buckets": diagnostic["unavailable_mask"]["unavailable_buckets"],
        "maximum_observed_rss_bytes": observed,
        "files": {
            "feature": file_record(paths["feature"]),
            "mask": file_record(paths["mask"]),
            "diagnostic": file_record(paths["diagnostic"]),
            "spec": file_record(paths["spec"]),
            "monitor": file_record(monitor_path),
        },
        "outcomes_opened_or_joined": False,
        "checkpoint_receipt": None,
    }
    checkpoint["checkpoint_receipt"] = canonical_hash({**checkpoint, "checkpoint_receipt": None})
    write_json_exclusive(paths["checkpoint"], checkpoint)
    return checkpoint


def engineering_sources(data_root: Path, artifact_root: Path) -> dict[str, dict[str, Any]]:
    protocol = read_json(ROOT / "research_manifests/gc_microstructure_step_4b3_protocol_v01.json")
    output: dict[str, dict[str, Any]] = {}
    for selected_date, item in protocol["frozen_dates"].items():
        output[selected_date] = {
            "day_start_ns": int(item["day_start_inclusive_ns"]),
            "instrument_id": int(item["expected_instrument_id"]),
            "mbo": data_root / str(item["mbo"]["path"]),
            "mbo_sha256": str(item["mbo"]["sha256"]),
            "mbp": data_root / str(item["mbp10"]["path"]),
            "mbp_sha256": str(item["mbp10"]["sha256"]),
            "known": artifact_root / "gc_microstructure_step_4b3_v01" / selected_date / "primary_features.parquet",
        }
    output["2024-01-09"] = {
        "day_start_ns": 1704758400000000000,
        "instrument_id": 41512,
        "mbo": data_root
        / "data/raw/databento_gc_mbo_engineering_pilot/GLBX-20260730-WB9AXCVFET/normalized/gc_v_0_2024_01_09_mbo.parquet",
        "mbo_sha256": r2.EXPECTED["engineering_mbo"],
        "mbp": data_root
        / "data/raw/databento_gc_mbp10_engineering_benchmark/GLBX-20260731-UJHWEDQUSX/normalized/gc_v_0_2024_01_09_mbp10.parquet",
        "mbp_sha256": r2.EXPECTED["engineering_mbp"],
        "known": artifact_root / "gc_microstructure_step_4a3_v01/primary_features.parquet",
    }
    if tuple(sorted(output)) != tuple(sorted(EXPECTED_ENGINEERING_DATES)):
        raise ValueError("Engineering-date registry changed")
    return output


def engineering_row(selected_date: str, session_code: str, source: Mapping[str, Any]) -> dict[str, Any]:
    zone = ZoneInfo("Europe/London" if session_code == "LONDON" else "America/New_York")
    local_open = datetime.combine(date.fromisoformat(selected_date), clock_time(8, 0), zone)
    start = local_open.astimezone(UTC) - timedelta(minutes=15)
    end = start + timedelta(seconds=m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION)
    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns = int(end.timestamp() * 1_000_000_000)
    day_start = int(source["day_start_ns"])
    if not (day_start <= start_ns < end_ns <= day_start + 86_400 * m2.BUCKET_NS):
        raise ValueError("Engineering window escaped its UTC date")
    return {
        "row_id": f"V2_ENGINEERING:{selected_date}:{session_code}",
        "session_code": session_code,
        "window_start_inclusive_ns": start_ns,
        "window_end_exclusive_ns": end_ns,
        "utc_day_start_ns": day_start,
        "bucket_index_start_inclusive": int((start_ns - day_start) // m2.BUCKET_NS),
        "expected_instrument_id": int(source["instrument_id"]),
    }


def verify_engineering_commit(commit_path: Path) -> dict[str, Any]:
    commit = read_json(commit_path)
    if not receipt_valid(commit, "commit_receipt"):
        raise ValueError("Engineering commit receipt failed")
    for record in commit["files"].values():
        verify_record(record)
    for implementation in IMPLEMENTATIONS:
        checkpoint = read_json(Path(str(commit["files"][f"{implementation}_checkpoint"]["path"])))
        if not receipt_valid(checkpoint, "checkpoint_receipt"):
            raise ValueError("Engineering pass checkpoint receipt failed")
        for record in checkpoint["files"].values():
            verify_record(record)
    if not all(commit["gates"].values()):
        raise ValueError("Engineering commit gate failed")
    return commit


def run_engineering_proof(
    *,
    paths: RunPaths,
    data_root: Path,
    artifact_root: Path,
    engineering_output: Path,
) -> dict[str, Any]:
    if FREEZE_PATH.exists():
        raise FileExistsError("V2 freeze already exists")
    predecessor = verify_v1(paths)
    sources = engineering_sources(data_root, artifact_root)
    source_bindings: dict[str, Any] = {}
    for selected_date, source in sorted(sources.items()):
        for key in ("mbo", "mbp"):
            path = Path(source[key])
            expected = str(source[f"{key}_sha256"])
            if not path.is_file() or sha256_file(path) != expected:
                raise ValueError(f"Engineering source binding failed: {selected_date} {key}")
        known = Path(source["known"])
        if not known.is_file():
            raise FileNotFoundError(known)
        source_bindings[selected_date] = {
            "mbo": file_record(Path(source["mbo"])),
            "mbp10": file_record(Path(source["mbp"])),
            "known_features": file_record(known),
        }
    engineering_output.mkdir(parents=True, exist_ok=True)
    marker = engineering_output / "attempt_started.json"
    if not marker.exists():
        write_json_exclusive(
            marker,
            {
                "version": "GC_SESSION_TRIGGER_EDGE_V2_ENGINEERING_ATTEMPT_V1_0",
                "started_at_utc": utc_now(),
                "development_metadata_opened": False,
                "outcomes_opened": False,
            },
        )
    commits: list[dict[str, Any]] = []
    for selected_date in EXPECTED_ENGINEERING_DATES:
        source = sources[selected_date]
        for session_code in SESSIONS:
            row = engineering_row(selected_date, session_code, source)
            name = safe_name(str(row["row_id"]))
            commit_path = engineering_output / "checkpoints" / "sessions" / f"{name}.json"
            if commit_path.is_file():
                commits.append(verify_engineering_commit(commit_path))
                continue
            checkpoints = {
                implementation: ensure_feature_pass(
                    output=engineering_output,
                    row_id=str(row["row_id"]),
                    classification="ENGINEERING_ONLY_ZERO_RESEARCH_OR_VALIDATION_CREDIT",
                    implementation=implementation,
                    mbo_path=Path(source["mbo"]),
                    mbp_path=Path(source["mbp"]),
                    row=row,
                    invocation=1,
                )
                for implementation in IMPLEMENTATIONS
            }
            primary = pass_paths(engineering_output, str(row["row_id"]), "primary")
            reference = pass_paths(engineering_output, str(row["row_id"]), "reference")
            expected_path = engineering_output / "expected_slices" / f"{name}.parquet"
            if not expected_path.exists():
                full = pq.read_table(Path(source["known"]))
                offset = int(row["bucket_index_start_inclusive"])
                expected_table = full.slice(offset, m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION)
                if expected_table.num_rows != m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION:
                    raise ValueError("Engineering expected slice row count changed")
                atomic_parquet(expected_path, expected_table, m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION)
                del full, expected_table
                gc.collect()
            p_table = pq.read_table(primary["feature"])
            r_table = pq.read_table(reference["feature"])
            expected_table = pq.read_table(expected_path)
            source_exact = checkpoints["primary"]["source"] == checkpoints["reference"]["source"]
            feature_exact = p_table.equals(r_table, check_metadata=True)
            existing_exact = p_table.equals(expected_table, check_metadata=True)
            masks_exact = primary["mask"].read_bytes() == reference["mask"].read_bytes()
            zero_unavailable = not any(decode_mask(primary["mask"]))
            technical_exact = checkpoints["primary"]["technical"] == checkpoints["reference"]["technical"]
            policy_exact = checkpoints["primary"]["policy"] == checkpoints["reference"]["policy"]
            resource_pass = max(
                checkpoints["primary"]["maximum_observed_rss_bytes"],
                checkpoints["reference"]["maximum_observed_rss_bytes"],
                proc_memory_bytes()["hwm_bytes"],
            ) <= RSS_CAP_BYTES
            del p_table, r_table, expected_table
            gc.collect()
            gates = {
                "primary_reference_source_identities_exact": source_exact,
                "primary_reference_features_exact": feature_exact,
                "existing_sealed_engineering_slice_exact": existing_exact,
                "primary_reference_unavailable_masks_exact": masks_exact,
                "continuous_engineering_window_has_zero_unavailable_buckets": zero_unavailable,
                "primary_reference_technical_diagnostics_exact": technical_exact,
                "primary_reference_policy_exact": policy_exact,
                "all_processes_below_4_gib_rss": resource_pass,
            }
            commit = {
                "version": "GC_SESSION_TRIGGER_EDGE_V2_ENGINEERING_COMMIT_V1_0",
                "status": "PASS_ENGINEERING_WINDOW" if all(gates.values()) else "FAIL_ENGINEERING_WINDOW",
                "committed_at_utc": utc_now(),
                "classification": "ENGINEERING_ONLY_ZERO_RESEARCH_OR_VALIDATION_CREDIT",
                "row_id": row["row_id"],
                "engineering_date": selected_date,
                "session_code": session_code,
                "gates": gates,
                "maximum_observed_rss_bytes": max(
                    checkpoints["primary"]["maximum_observed_rss_bytes"],
                    checkpoints["reference"]["maximum_observed_rss_bytes"],
                ),
                "files": {
                    "primary_checkpoint": file_record(primary["checkpoint"]),
                    "reference_checkpoint": file_record(reference["checkpoint"]),
                    "expected_slice": file_record(expected_path),
                },
                "development_metadata_opened": False,
                "outcomes_opened": False,
                "commit_receipt": None,
            }
            commit["commit_receipt"] = canonical_hash({**commit, "commit_receipt": None})
            write_json_exclusive(commit_path, commit)
            if not all(gates.values()):
                raise ValueError(f"Engineering gate failed: {row['row_id']}")
            commits.append(commit)
            print(
                json.dumps(
                    {
                        "stage": "V2_ENGINEERING_WINDOW_COMPLETE",
                        "completed": len(commits),
                        "total": 12,
                        "row_id": row["row_id"],
                        "outcomes": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    if len(commits) != 12:
        raise ValueError("Engineering proof did not commit twelve windows")
    no_op_resume = [
        verify_engineering_commit(
            engineering_output / "checkpoints" / "sessions" / f"{safe_name(str(item['row_id']))}.json"
        )["commit_receipt"]
        for item in commits
    ]
    max_rss = max(int(item["maximum_observed_rss_bytes"]) for item in commits)
    proof = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_ENGINEERING_PROOF_V1_0",
        "status": "PASS_V2_ENGINEERING_REPRODUCTION_AND_RESOURCE_GATE",
        "completed_at_utc": utc_now(),
        "classification": "ENGINEERING_ONLY_ZERO_RESEARCH_OR_VALIDATION_CREDIT",
        "dates": list(EXPECTED_ENGINEERING_DATES),
        "sessions": list(SESSIONS),
        "windows": 12,
        "commits": [
            {
                "row_id": item["row_id"],
                "commit_receipt": item["commit_receipt"],
                "maximum_observed_rss_bytes": item["maximum_observed_rss_bytes"],
            }
            for item in commits
        ],
        "source_bindings": source_bindings,
        "maximum_observed_rss_bytes": max_rss,
        "formal_rss_cap_bytes": RSS_CAP_BYTES,
        "exact_no_op_resume_commits": len(no_op_resume),
        "all_primary_reference_and_existing_payload_comparisons_exact": True,
        "development_metadata_opened": False,
        "outcomes_opened": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "predecessors": predecessor,
        "proof_receipt": None,
    }
    proof["proof_receipt"] = canonical_hash({**proof, "proof_receipt": None})
    proof_path = engineering_output / "engineering_proof.json"
    write_json_exclusive(proof_path, proof)
    freeze = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_FREEZE_V1_0",
        "status": "SEALED_AFTER_ENGINEERING_PASS_BEFORE_DEVELOPMENT_METADATA",
        "sealed_at_utc": utc_now(),
        "contract": file_record(CONTRACT_PATH),
        "protocol": file_record(PROTOCOL_PATH),
        "implementation": file_record(Path(__file__)),
        "engineering_proof": file_record(proof_path),
        "predecessors": predecessor,
        "resource_policy": {
            "formal_rss_cap_bytes": RSS_CAP_BYTES,
            "child_guard_rss_bytes": RSS_GUARD_BYTES,
            "sampling_interval_seconds": RSS_SAMPLE_SECONDS,
        },
        "analytical_definitions_changed": False,
        "development_metadata_opened": False,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = canonical_hash({**freeze, "freeze_receipt": None})
    write_json_exclusive(FREEZE_PATH, freeze)
    print(
        json.dumps(
            {
                "status": freeze["status"],
                "engineering_windows": 12,
                "max_rss_bytes": max_rss,
                "outcomes": False,
            },
            sort_keys=True,
        )
    )
    return proof


def next_invocation(output: Path) -> int:
    directory = output / "invocations"
    directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(directory.glob("*_started.json"))
    return len(existing) + 1


def start_invocation(output: Path, freeze: Mapping[str, Any]) -> tuple[int, Path]:
    attempt_path = output / "attempt_started.json"
    if not attempt_path.exists():
        write_json_exclusive(
            attempt_path,
            {
                "version": "GC_SESSION_TRIGGER_EDGE_V2_LOGICAL_ATTEMPT_V1_0",
                "logical_attempt": 1,
                "maximum_logical_attempts": 1,
                "started_at_utc": utc_now(),
                "append_only_resume_permitted": True,
                "outcomes_opened": False,
            },
        )
    attempt = read_json(attempt_path)
    if attempt.get("logical_attempt") != 1 or attempt.get("maximum_logical_attempts") != 1:
        raise ValueError("V2 logical-attempt marker changed")
    invocation = next_invocation(output)
    path = output / "invocations" / f"{invocation:04d}_started.json"
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_INVOCATION_V1_0",
        "invocation": invocation,
        "logical_attempt": 1,
        "started_at_utc": utc_now(),
        "freeze_receipt": freeze["freeze_receipt"],
        "process_id": os.getpid(),
        "outcomes_opened": False,
    }
    write_json_exclusive(path, record)
    return invocation, path


def session_commit_path(output: Path, row_id: str) -> Path:
    return output / "checkpoints" / "sessions" / f"{safe_name(row_id)}.json"


def decision_event_paths(output: Path, row_id: str, implementation: str) -> dict[str, Path]:
    name = safe_name(row_id)
    return {
        "decision": output / "fragments" / implementation / f"{name}.decisions.parquet",
        "event": output / "fragments" / implementation / f"{name}.events.parquet",
    }


def verify_session_commit(path: Path) -> dict[str, Any]:
    commit = read_json(path)
    if not receipt_valid(commit, "commit_receipt"):
        raise ValueError("Session commit receipt failed")
    for group in ("primary", "reference"):
        for record in commit["files"][group].values():
            verify_record(record)
    if not all(commit["gates"].values()):
        raise ValueError("Committed session contains a failed gate")
    return commit


def materialize_decisions_and_events(
    *,
    output: Path,
    row: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    context: Mapping[str, Any],
    history: Mapping[str, Any],
    session: Any,
    s5c: Any,
    base: Any,
    invocation: int,
) -> dict[str, Any]:
    row_id = str(row["row_id"])
    commit_path = session_commit_path(output, row_id)
    if commit_path.is_file():
        return verify_session_commit(commit_path)
    all_paths = {
        implementation: decision_event_paths(output, row_id, implementation)
        for implementation in IMPLEMENTATIONS
    }
    quarantine_uncommitted(
        [path for values in all_paths.values() for path in values.values()],
        output / "quarantine",
        f"{row_id}:decision_event:invocation:{invocation}",
    )
    summaries: dict[str, dict[str, Any]] = {}
    original_future_quality = m2._future_timestamp_quality
    m2._future_timestamp_quality = r2.future_quality_r2
    try:
        for implementation in IMPLEMENTATIONS:
            feature_path = Path(str(checkpoints[implementation]["files"]["feature"]["path"]))
            mask_path = Path(str(checkpoints[implementation]["files"]["mask"]["path"]))
            columns = pq.read_table(feature_path).to_pydict()
            mask = decode_mask(mask_path)
            micro = m2._minute_micro_states(s5c, base, columns, implementation)
            decisions, levels = r2.decision_rows_r2(
                s5c,
                base,
                row,
                columns,
                micro,
                context,
                history,
                session,
                implementation,
                mask,
            )
            events = m2._detect_events(row, session, decisions, levels, micro, implementation)
            events = sorted(
                events,
                key=lambda item: (
                    item["decision_at_utc"],
                    item["event_family"],
                    item["directional_prior"],
                    item["event_id"],
                ),
            )
            decision_table = pa.Table.from_pylist(decisions, schema=m2.DECISION_SCHEMA)
            event_table = pa.Table.from_pylist(events, schema=m2.EVENT_SCHEMA)
            if decision_table.num_rows != m2.EXPECTED_DECISIONS_PER_SESSION:
                raise ValueError("Session decision count changed")
            atomic_parquet(all_paths[implementation]["decision"], decision_table, m2.EXPECTED_DECISIONS_PER_SESSION)
            atomic_parquet(all_paths[implementation]["event"], event_table, max(1, event_table.num_rows))
            summaries[implementation] = {
                "decision_rows": decision_table.num_rows,
                "event_rows": event_table.num_rows,
                "decision_file": file_record(all_paths[implementation]["decision"]),
                "event_file": file_record(all_paths[implementation]["event"]),
            }
            del columns, mask, micro, decisions, levels, events, decision_table, event_table
            gc.collect()
            try:
                pa.default_memory_pool().release_unused()
            except Exception:
                pass
    finally:
        m2._future_timestamp_quality = original_future_quality
    source_exact = checkpoints["primary"]["source"] == checkpoints["reference"]["source"]
    feature_exact = (
        checkpoints["primary"]["feature_fingerprint"] == checkpoints["reference"]["feature_fingerprint"]
        and checkpoints["primary"]["files"]["feature"]["sha256"]
        == checkpoints["reference"]["files"]["feature"]["sha256"]
    )
    mask_exact = checkpoints["primary"]["files"]["mask"]["sha256"] == checkpoints["reference"]["files"]["mask"]["sha256"]
    technical_exact = checkpoints["primary"]["technical"] == checkpoints["reference"]["technical"]
    policy_exact = checkpoints["primary"]["policy"] == checkpoints["reference"]["policy"]
    decision_exact = summaries["primary"]["decision_file"]["sha256"] == summaries["reference"]["decision_file"]["sha256"]
    event_exact = summaries["primary"]["event_file"]["sha256"] == summaries["reference"]["event_file"]["sha256"]
    parent_hwm = proc_memory_bytes()["hwm_bytes"]
    max_rss = max(
        parent_hwm,
        int(checkpoints["primary"]["maximum_observed_rss_bytes"]),
        int(checkpoints["reference"]["maximum_observed_rss_bytes"]),
    )
    gates = {
        "source_identities_exact": source_exact,
        "feature_rows_missingness_and_checksums_exact": feature_exact and mask_exact,
        "technical_and_policy_diagnostics_exact": technical_exact and policy_exact,
        "decision_rows_and_checksums_exact": decision_exact,
        "event_identities_and_checksums_exact": event_exact,
        "all_processes_below_4_gib_rss": max_rss <= RSS_CAP_BYTES,
    }
    commit = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_SESSION_COMMIT_V1_0",
        "status": "PASS_IMMUTABLE_SESSION_COMMIT" if all(gates.values()) else "FAIL_SESSION_COMMIT",
        "committed_at_utc": utc_now(),
        "row_id": row_id,
        "session_date": str(row["session_date"]),
        "session_code": str(row["session_code"]),
        "gates": gates,
        "maximum_observed_rss_bytes": max_rss,
        "technical": checkpoints["primary"]["technical"],
        "policy": checkpoints["primary"]["policy"],
        "files": {
            implementation: {
                "pass_checkpoint": file_record(pass_paths(output, row_id, implementation)["checkpoint"]),
                "feature": checkpoints[implementation]["files"]["feature"],
                "mask": checkpoints[implementation]["files"]["mask"],
                "decision": summaries[implementation]["decision_file"],
                "event": summaries[implementation]["event_file"],
            }
            for implementation in IMPLEMENTATIONS
        },
        "decision_rows": summaries["primary"]["decision_rows"],
        "event_rows": summaries["primary"]["event_rows"],
        "outcomes_opened_or_joined": False,
        "relationships_hit_rates_candidates_execution_trades_or_pnl_calculated": False,
        "commit_receipt": None,
    }
    commit["commit_receipt"] = canonical_hash({**commit, "commit_receipt": None})
    write_json_exclusive(commit_path, commit)
    if not all(gates.values()):
        raise ValueError(f"Session reproduction failed: {row_id}")
    return commit


def assemble_parquet(
    output_path: Path,
    fragment_paths: Sequence[Path],
    schema: pa.Schema,
    expected_rows: int,
) -> None:
    if output_path.exists():
        raise FileExistsError(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + f".tmp.{os.getpid()}")
    writer = pq.ParquetWriter(
        temporary,
        schema,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
    )
    rows = 0
    try:
        for fragment in fragment_paths:
            table = pq.read_table(fragment)
            if table.schema != schema:
                raise ValueError(f"Fragment schema changed: {fragment}")
            writer.write_table(table, row_group_size=max(1, table.num_rows))
            rows += table.num_rows
            del table
    finally:
        writer.close()
    if rows != expected_rows:
        raise ValueError(f"Assembled row count changed: {rows} != {expected_rows}")
    os.replace(temporary, output_path)


def normalized_support(value: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(value)
    output.pop("implementation", None)
    output.pop("support_receipt", None)
    return output


def finalize_development(
    *,
    paths: RunPaths,
    freeze: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    commits: Sequence[Mapping[str, Any]],
    xau_diagnostics: Mapping[str, Any],
    missing_keys: Sequence[str],
    invocation: int,
) -> dict[str, Any]:
    output = paths.output
    assembly_checkpoint = output / "checkpoints/final_assembly.json"
    final_names = [
        f"{implementation}_{session.lower()}_one_second_features.parquet"
        for implementation in IMPLEMENTATIONS
        for session in SESSIONS
    ] + [
        f"{implementation}_minute_contexts.parquet" for implementation in IMPLEMENTATIONS
    ] + [f"{implementation}_events.parquet" for implementation in IMPLEMENTATIONS]
    if not assembly_checkpoint.exists():
        quarantine_uncommitted(
            [output / name for name in final_names],
            output / "quarantine",
            f"final_assembly:invocation:{invocation}",
        )
        commit_by_id = {str(commit["row_id"]): commit for commit in commits}
        available_rows = [row for row in rows if int(row["expected_bucket_rows"]) > 0]
        for implementation in IMPLEMENTATIONS:
            for session_code in SESSIONS:
                fragments = [
                    Path(str(commit_by_id[str(row["row_id"])]["files"][implementation]["feature"]["path"]))
                    for row in available_rows
                    if str(row["session_code"]) == session_code
                ]
                assemble_parquet(
                    output / f"{implementation}_{session_code.lower()}_one_second_features.parquet",
                    fragments,
                    m2._load_module(m2.BASE_ENGINE_PATH, f"gc_v2_assembly_base_{implementation}_{session_code}").FEATURE_SCHEMA,
                    m2.EXPECTED_FEATURE_ROWS // 2,
                )
            decision_fragments = [
                Path(str(commit_by_id[str(row["row_id"])]["files"][implementation]["decision"]["path"]))
                for row in available_rows
            ]
            assemble_parquet(
                output / f"{implementation}_minute_contexts.parquet",
                decision_fragments,
                m2.DECISION_SCHEMA,
                m2.EXPECTED_DECISION_ROWS,
            )
            event_rows: list[dict[str, Any]] = []
            for row in available_rows:
                event_path = Path(str(commit_by_id[str(row["row_id"])]["files"][implementation]["event"]["path"]))
                event_rows.extend(pq.read_table(event_path).to_pylist())
            event_rows.sort(
                key=lambda item: (
                    item["session_date"],
                    item["session_code"],
                    item["decision_at_utc"],
                    item["event_family"],
                    item["directional_prior"],
                    item["event_id"],
                )
            )
            event_table = pa.Table.from_pylist(event_rows, schema=m2.EVENT_SCHEMA)
            atomic_parquet(output / f"{implementation}_events.parquet", event_table, max(1, event_table.num_rows))
            support = m2._support_report(event_rows, implementation)
            write_json_exclusive(output / f"{implementation}_support_counts.json", support)
            del event_rows, event_table
            gc.collect()
        assembly = {
            "version": "GC_SESSION_TRIGGER_EDGE_V2_ASSEMBLY_CHECKPOINT_V1_0",
            "status": "PASS_STREAMING_FINAL_ASSEMBLY",
            "completed_at_utc": utc_now(),
            "files": {
                name: file_record(output / name)
                for name in final_names
            },
            "support_files": {
                implementation: file_record(output / f"{implementation}_support_counts.json")
                for implementation in IMPLEMENTATIONS
            },
            "checkpoint_receipt": None,
        }
        assembly["checkpoint_receipt"] = canonical_hash({**assembly, "checkpoint_receipt": None})
        write_json_exclusive(assembly_checkpoint, assembly)
    assembly = read_json(assembly_checkpoint)
    if not receipt_valid(assembly, "checkpoint_receipt"):
        raise ValueError("Final assembly checkpoint failed")
    for record in assembly["files"].values():
        verify_record(record)
    for record in assembly["support_files"].values():
        verify_record(record)
    s5c = m2._load_module(m2.STEP5C_ENGINE_PATH, "gc_v2_final_s5c")
    base = m2._load_module(m2.BASE_ENGINE_PATH, "gc_v2_final_base")
    feature_fingerprints: dict[str, dict[str, Any]] = {implementation: {} for implementation in IMPLEMENTATIONS}
    for implementation in IMPLEMENTATIONS:
        for session_code in SESSIONS:
            feature_fingerprints[implementation][session_code] = s5c._parquet_hashes(
                output / f"{implementation}_{session_code.lower()}_one_second_features.parquet",
                base.FEATURE_SCHEMA,
                m2.EXPECTED_FEATURE_ROWS // 2,
                s5c._schema_hash(base.FEATURE_SCHEMA),
            )
    decision_fingerprints = {
        implementation: s5c._parquet_hashes(
            output / f"{implementation}_minute_contexts.parquet",
            m2.DECISION_SCHEMA,
            m2.EXPECTED_DECISION_ROWS,
            s5c._schema_hash(m2.DECISION_SCHEMA),
        )
        for implementation in IMPLEMENTATIONS
    }
    event_counts = {
        implementation: pq.ParquetFile(output / f"{implementation}_events.parquet").metadata.num_rows
        for implementation in IMPLEMENTATIONS
    }
    event_fingerprints = {
        implementation: s5c._parquet_hashes(
            output / f"{implementation}_events.parquet",
            m2.EVENT_SCHEMA,
            int(event_counts[implementation]),
            s5c._schema_hash(m2.EVENT_SCHEMA),
        )
        for implementation in IMPLEMENTATIONS
    }
    supports = {
        implementation: read_json(output / f"{implementation}_support_counts.json")
        for implementation in IMPLEMENTATIONS
    }
    aggregate: Counter[str] = Counter({"documented_unavailable_sessions": 2})
    policy_rows: list[dict[str, Any]] = []
    max_rss = proc_memory_bytes()["hwm_bytes"]
    fragment_manifest_rows: list[dict[str, Any]] = []
    for commit in commits:
        aggregate.update(commit["technical"])
        policy_rows.append({"row_id": commit["row_id"], **commit["policy"]})
        max_rss = max(max_rss, int(commit["maximum_observed_rss_bytes"]))
        for implementation in IMPLEMENTATIONS:
            for label, record in commit["files"][implementation].items():
                fragment_manifest_rows.append(
                    {"row_id": commit["row_id"], "implementation": implementation, "label": label, **record}
                )
    fragment_manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_FRAGMENT_MANIFEST_V1_0",
        "session_commits": len(commits),
        "records": fragment_manifest_rows,
        "records_receipt": canonical_hash(fragment_manifest_rows),
    }
    write_json_exclusive(output / "fragment_manifest.json", fragment_manifest)
    diagnostics = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_DIAGNOSTICS_V1_0",
        "available_sessions": len(commits),
        "documented_unavailable_sessions": 2,
        "unresolved_xau_keys_count": len(missing_keys),
        "unresolved_xau_keys_checksum": canonical_hash(list(missing_keys)),
        "xau": xau_diagnostics,
        "primary_technical": dict(sorted(aggregate.items())),
        "reference_technical": dict(sorted(aggregate.items())),
        "primary_missingness_checksum": canonical_hash(policy_rows),
        "reference_missingness_checksum": canonical_hash(policy_rows),
        "maximum_observed_rss_bytes": max_rss,
        "formal_rss_cap_bytes": RSS_CAP_BYTES,
        "outcomes_opened": False,
    }
    write_json_exclusive(output / "technical_diagnostics.json", diagnostics)
    primary_events = pq.read_table(
        output / "primary_events.parquet",
        columns=["source_domain", "decision_id", "quality_state"],
    ).to_pylist()
    decision_table = pq.read_table(
        output / "primary_minute_contexts.parquet",
        columns=["decision_id", "gc_state_quality"],
    )
    decision_quality = dict(
        zip(decision_table["decision_id"].to_pylist(), decision_table["gc_state_quality"].to_pylist(), strict=True)
    )
    invalid_eligible_micro = sum(
        event["quality_state"] == "ELIGIBLE"
        and event["source_domain"] == "GC_MICROSTRUCTURE"
        and decision_quality.get(event["decision_id"]) != r2.VALID_GC
        for event in primary_events
    )
    stage1_all = (
        supports["primary"]["stage1_tests"] == 12
        and supports["primary"]["stage1_support_eligible"] == 12
        and all(item["support_status"] == "SUPPORT_ELIGIBLE" for item in supports["primary"]["stage1"])
    )
    feature_exact = all(
        feature_fingerprints["primary"][session_code] == feature_fingerprints["reference"][session_code]
        and sha256_file(output / f"primary_{session_code.lower()}_one_second_features.parquet")
        == sha256_file(output / f"reference_{session_code.lower()}_one_second_features.parquet")
        for session_code in SESSIONS
    )
    decisions_exact = (
        decision_fingerprints["primary"] == decision_fingerprints["reference"]
        and sha256_file(output / "primary_minute_contexts.parquet")
        == sha256_file(output / "reference_minute_contexts.parquet")
    )
    events_exact = (
        event_fingerprints["primary"] == event_fingerprints["reference"]
        and sha256_file(output / "primary_events.parquet") == sha256_file(output / "reference_events.parquet")
    )
    technical = diagnostics["primary_technical"]
    gates = {
        "freeze_and_predecessor_seals_valid": True,
        "exact_374_session_commits": len(commits) == m2.EXPECTED_AVAILABLE_SESSIONS,
        "exact_three_unresolved_xau_timestamps": len(missing_keys) == r2.EXPECTED_UNRESOLVED_XAU,
        "raw_terminal_crossed_count_exactly_15": int(technical.get("raw_terminal_crossed_bucket_closes", -1)) == 15,
        "post_policy_crossed_count_zero": int(technical.get("continuous_crossed_bucket_closes", -1)) == 0,
        "state_availability_drop_matches_unavailable_latch": (
            int(technical.get("raw_state_available_bucket_closes", -1))
            - int(technical.get("state_available_bucket_closes", -1))
            == int(technical.get("technical_unavailable_bucket_closes", -2))
        ),
        "zero_crossed_non_f_last_failures": int(technical.get("crossed_non_f_last_failures", -1)) == 0,
        "zero_invalid_state_values_retained": int(technical.get("invalid_state_values_retained", -1)) == 0,
        "feature_rows_schemas_nulls_and_checksums_exact": feature_exact,
        "decision_rows_and_checksums_exact": decisions_exact,
        "event_identities_and_checksums_exact": events_exact,
        "support_counts_exact": normalized_support(supports["primary"]) == normalized_support(supports["reference"]),
        "all_frozen_session_event_families_retain_support": stage1_all,
        "no_invalid_state_contributed_to_eligible_micro_event": invalid_eligible_micro == 0,
        "all_processes_below_4_gib_rss": max_rss <= RSS_CAP_BYTES,
        "one_logical_attempt": read_json(output / "attempt_started.json").get("logical_attempt") == 1,
        "no_outcomes_relationships_candidates_forward_years_execution_trades_or_pnl": True,
        "zero_acquisition_and_charge": True,
    }
    status = (
        "PASS_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION"
        if all(gates.values())
        else "FAIL_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION"
    )
    verdict = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_VERDICT_V1_0",
        "status": status,
        "formal_pass": all(gates.values()),
        "completed_at_utc": utc_now(),
        "formal_gates": gates,
        "passed_gates": sum(gates.values()),
        "total_gates": len(gates),
        "session_commits": len(commits),
        "feature_rows_per_implementation": m2.EXPECTED_FEATURE_ROWS,
        "decision_rows_per_implementation": m2.EXPECTED_DECISION_ROWS,
        "event_rows_per_implementation": event_counts,
        "stage1_support_eligible": supports["primary"]["stage1_support_eligible"],
        "stage1_tests": supports["primary"]["stage1_tests"],
        "maximum_observed_rss_bytes": max_rss,
        "development_outcomes_opened_or_joined": False,
        "relationships_hit_rates_effects_candidates_execution_trades_pnl_or_returns_calculated": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "completion_policy": (
            "PASS: stop before separately authorized relationship discovery."
            if all(gates.values())
            else "FAIL: stop without automatic repair or research inference."
        ),
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = canonical_hash({**verdict, "verdict_receipt": None})
    write_json_exclusive(output / "verdict.json", verdict)
    report = "\n".join(
        [
            "# GC Session Trigger Edge Discovery V2 — Technical Certification",
            "",
            f"Formal status: `{status}`",
            "",
            f"Committed sessions: {len(commits)} of {m2.EXPECTED_AVAILABLE_SESSIONS}.",
            f"Stage-1 support-eligible tests: {supports['primary']['stage1_support_eligible']} of 12.",
            f"Maximum observed RSS: {max_rss:,} bytes against a {RSS_CAP_BYTES:,}-byte cap.",
            "",
            "No outcome, relationship, hit rate, candidate, 2025/2026 value, execution rule, trade, or PnL was accessed or calculated.",
            "",
            verdict["completion_policy"],
        ]
    )
    write_text_exclusive(output / "GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION.md", report)
    artifact_names = [
        "attempt_started.json",
        "preflight.json",
        "fragment_manifest.json",
        "technical_diagnostics.json",
        "primary_london_one_second_features.parquet",
        "primary_new_york_one_second_features.parquet",
        "reference_london_one_second_features.parquet",
        "reference_new_york_one_second_features.parquet",
        "primary_minute_contexts.parquet",
        "reference_minute_contexts.parquet",
        "primary_events.parquet",
        "reference_events.parquet",
        "primary_support_counts.json",
        "reference_support_counts.json",
        "verdict.json",
        "GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION.md",
    ]
    manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_MANIFEST_V1_0",
        "status": status,
        "sealed_at_utc": utc_now(),
        "contract": file_record(CONTRACT_PATH),
        "protocol": file_record(PROTOCOL_PATH),
        "freeze": file_record(FREEZE_PATH),
        "implementation": file_record(Path(__file__)),
        "artifacts": [file_record(output / name) for name in artifact_names],
        "checkpoint_index_receipt": canonical_hash([commit["commit_receipt"] for commit in commits]),
        "verdict_receipt": verdict["verdict_receipt"],
        "outcomes_or_prohibited_work": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = canonical_hash({**manifest, "manifest_receipt": None})
    write_json_exclusive(output / "manifest.json", manifest)
    final = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_FINAL_SEAL_V1_0",
        "status": status,
        "sealed_at_utc": utc_now(),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "verdict_sha256": sha256_file(output / "verdict.json"),
        "manifest_sha256": sha256_file(output / "manifest.json"),
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = canonical_hash({**final, "final_seal_receipt": None})
    write_json_exclusive(output / "final_seal.json", final)
    return verdict


def seal_execution_failure(paths: RunPaths, error: Exception) -> None:
    if (paths.output / "final_seal.json").exists():
        raise RuntimeError("Refusing to replace an existing V2 final seal")
    failure = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_EXECUTION_FAILURE_V1_0",
        "status": "FAIL_GC_SESSION_TRIGGER_EDGE_V2_EXECUTION",
        "failed_at_utc": utc_now(),
        "error_type": type(error).__name__,
        "error_sha256": hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
        "committed_sessions": len(list((paths.output / "checkpoints/sessions").glob("*.json"))),
        "logical_attempts": 1,
        "outcomes_or_market_values_reported": False,
    }
    write_json_exclusive(paths.output / "execution_failure.json", failure)
    verdict = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_VERDICT_V1_0",
        "status": failure["status"],
        "formal_pass": False,
        "completed_at_utc": utc_now(),
        "failure": failure,
        "development_outcomes_opened_or_joined": False,
        "relationships_hit_rates_candidates_execution_trades_or_pnl_calculated": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "completion_policy": "Stop without automatic repair or research inference.",
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = canonical_hash({**verdict, "verdict_receipt": None})
    write_json_exclusive(paths.output / "verdict.json", verdict)
    artifacts = [
        path
        for path in (
            paths.output / "attempt_started.json",
            paths.output / "preflight.json",
            paths.output / "execution_failure.json",
            paths.output / "verdict.json",
        )
        if path.is_file()
    ]
    manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_FAILURE_MANIFEST_V1_0",
        "status": failure["status"],
        "sealed_at_utc": utc_now(),
        "freeze": file_record(FREEZE_PATH),
        "implementation": file_record(Path(__file__)),
        "artifacts": [file_record(path) for path in artifacts],
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = canonical_hash({**manifest, "manifest_receipt": None})
    write_json_exclusive(paths.output / "manifest.json", manifest)
    final = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_FINAL_SEAL_V1_0",
        "status": failure["status"],
        "sealed_at_utc": utc_now(),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "verdict_sha256": sha256_file(paths.output / "verdict.json"),
        "manifest_sha256": sha256_file(paths.output / "manifest.json"),
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = canonical_hash({**final, "final_seal_receipt": None})
    write_json_exclusive(paths.output / "final_seal.json", final)


def run_development(paths: RunPaths) -> None:
    freeze = verify_v2_freeze(paths)
    paths.output.mkdir(parents=True, exist_ok=True)
    if (paths.output / "final_seal.json").exists():
        raise RuntimeError("V2 already has a final seal")
    mp = m2.Paths(paths.acquisition, paths.step5b2, paths.context, paths.xau, paths.output)
    s5c, base, registry, acquisition = m2._verified_control(mp, verify_payload_hashes=True)
    contexts, history, context_summary = m2._load_contexts(mp)
    if context_summary.get("status") != "PASS_OUTCOME_BLIND_CONTEXT_PROJECTION":
        raise ValueError("Step 5C context projection failed")
    rows = list(registry["rows"])
    sessions, xau_diagnostics = m2._load_xau(mp, rows)
    missing_keys = r2.xau_missing_keys(rows, sessions)
    request_by_id = m2._request_map(acquisition)
    disk = shutil.disk_usage(paths.output)
    gates = {
        "v2_freeze_and_engineering_proof_valid": True,
        "v1_terminal_failure_preserved": freeze["predecessors"]["v1_m2r2_status"] == V1_STATUS,
        "exact_80_sealed_requests_hash_verified": len(acquisition["requests"]) == 80,
        "exact_376_registry_rows": len(rows) == 376,
        "exact_374_available_sessions": sum(int(row["expected_bucket_rows"]) > 0 for row in rows) == 374,
        "exact_three_unresolved_xau_timestamps": len(missing_keys) == 3,
        "no_2025_or_2026_registry_rows": all(str(row["session_date"]) < "2025-01-01" for row in rows),
        "minimum_20_gib_free_output_storage": disk.free >= 20 * 1024**3,
        "no_outcome_source_opened": True,
        "zero_acquisition_and_charge": True,
    }
    preflight = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_PREFLIGHT_V1_0",
        "status": "PASS_V2_PRE_MATERIALIZATION_READINESS" if all(gates.values()) else "FAIL_V2_PRE_MATERIALIZATION_READINESS",
        "completed_at_utc": utc_now(),
        "formal_gates": gates,
        "free_storage_bytes": disk.free,
        "development_outcomes_opened_or_joined": False,
        "year_2025_or_2026_accessed": False,
    }
    if not (paths.output / "preflight.json").exists():
        write_json_exclusive(paths.output / "preflight.json", preflight)
    elif read_json(paths.output / "preflight.json")["formal_gates"] != gates:
        raise ValueError("V2 preflight changed across resume")
    if not all(gates.values()):
        raise ValueError("V2 preflight failed")
    invocation, invocation_path = start_invocation(paths.output, freeze)
    commits: list[dict[str, Any]] = []
    try:
        available = 0
        for row in rows:
            if int(row["expected_bucket_rows"]) == 0:
                continue
            available += 1
            row_id = str(row["row_id"])
            commit_path = session_commit_path(paths.output, row_id)
            resumed_commit = commit_path.is_file()
            if commit_path.is_file():
                commit = verify_session_commit(commit_path)
            else:
                mbo_request = request_by_id[str(row["mbo_request_id"])]
                mbp_request = request_by_id[str(row["mbp10_request_id"])]
                mbo_path = Path(str(mbo_request["normalization"]["normalized_payload"]["path"]))
                mbp_path = Path(str(mbp_request["normalization"]["normalized_payload"]["path"]))
                checkpoints = {
                    implementation: ensure_feature_pass(
                        output=paths.output,
                        row_id=row_id,
                        classification="OUTCOME_BLIND_2021_2024_DEVELOPMENT_TECHNICAL",
                        implementation=implementation,
                        mbo_path=mbo_path,
                        mbp_path=mbp_path,
                        row=row,
                        invocation=invocation,
                    )
                    for implementation in IMPLEMENTATIONS
                }
                commit = materialize_decisions_and_events(
                    output=paths.output,
                    row=row,
                    checkpoints=checkpoints,
                    context=contexts[str(row["source_step5c_row_id"])],
                    history=history,
                    session=sessions[row_id],
                    s5c=s5c,
                    base=base,
                    invocation=invocation,
                )
            commits.append(commit)
            print(
                json.dumps(
                    {
                        "stage": "V2_DEVELOPMENT_SESSION_COMMITTED",
                        "completed": available,
                        "total": 374,
                        "row_id": row_id,
                        "resumed": resumed_commit,
                        "outcomes": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        verdict = finalize_development(
            paths=paths,
            freeze=freeze,
            rows=rows,
            commits=commits,
            xau_diagnostics=xau_diagnostics,
            missing_keys=missing_keys,
            invocation=invocation,
        )
        write_json_exclusive(
            paths.output / "invocations" / f"{invocation:04d}_completed.json",
            {
                "version": "GC_SESSION_TRIGGER_EDGE_V2_INVOCATION_COMPLETION_V1_0",
                "invocation": invocation,
                "completed_at_utc": utc_now(),
                "committed_sessions": len(commits),
                "final_status": verdict["status"],
                "outcomes_opened": False,
            },
        )
        print(
            json.dumps(
                {
                    "status": verdict["status"],
                    "sessions": len(commits),
                    "stage1_support": f"{verdict['stage1_support_eligible']}/12",
                    "max_rss_bytes": verdict["maximum_observed_rss_bytes"],
                    "outcomes": False,
                },
                sort_keys=True,
            )
        )
    except Exception as error:
        if not (paths.output / "final_seal.json").exists():
            seal_execution_failure(paths, error)
        raise


def verify_final(paths: RunPaths) -> dict[str, Any]:
    freeze = verify_v2_freeze(paths)
    verdict = read_json(paths.output / "verdict.json")
    manifest = read_json(paths.output / "manifest.json")
    final = read_json(paths.output / "final_seal.json")
    for value, field in (
        (verdict, "verdict_receipt"),
        (manifest, "manifest_receipt"),
        (final, "final_seal_receipt"),
    ):
        if not receipt_valid(value, field):
            raise ValueError(f"V2 final receipt failed: {field}")
    if (
        final.get("freeze_sha256") != sha256_file(FREEZE_PATH)
        or final.get("verdict_sha256") != sha256_file(paths.output / "verdict.json")
        or final.get("manifest_sha256") != sha256_file(paths.output / "manifest.json")
    ):
        raise ValueError("V2 final seal bindings failed")
    for record in manifest.get("artifacts", []):
        verify_record(record)
    result = {
        "status": final["status"],
        "final_seal_receipt": final["final_seal_receipt"],
        "verified_artifacts": len(manifest["artifacts"]),
        "engineering_freeze_receipt": freeze["freeze_receipt"],
    }
    print(json.dumps(result, sort_keys=True))
    return result


def build_paths(args: argparse.Namespace) -> RunPaths:
    return RunPaths(
        acquisition=Path(args.acquisition),
        step5b2=Path(args.step5b2),
        context=Path(args.context),
        xau=Path(args.xau),
        old_m2=Path(args.old_m2),
        old_r1=Path(args.old_r1),
        old_a1=Path(args.old_a1),
        old_v1=Path(args.old_v1),
        output=Path(args.output),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("feature-worker", "prove-freeze", "execute", "verify"))
    parser.add_argument("--spec")
    parser.add_argument("--acquisition", default=str(m2.DEFAULT_ACQUISITION))
    parser.add_argument("--step5b2", default=str(m2.DEFAULT_STEP5B2))
    parser.add_argument("--context", default=str(m2.DEFAULT_CONTEXT))
    parser.add_argument("--xau", default=str(m2.DEFAULT_XAU))
    parser.add_argument("--old-m2", default=str(r2.DEFAULT_OLD_M2))
    parser.add_argument("--old-r1", default=str(r2.DEFAULT_OLD_R1))
    parser.add_argument("--old-a1", default=str(r2.DEFAULT_OLD_A1))
    parser.add_argument("--old-v1", default=str(r2.DEFAULT_OUTPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--engineering-output", default=str(DEFAULT_ENGINEERING_OUTPUT))
    parser.add_argument("--data-root", default=str(ROOT))
    parser.add_argument("--artifact-root", default=str(ROOT / "research_artifacts"))
    args = parser.parse_args()
    if args.action == "feature-worker":
        if not args.spec:
            parser.error("feature-worker requires --spec")
        worker_feature(Path(args.spec))
        return
    paths = build_paths(args)
    if args.action == "prove-freeze":
        run_engineering_proof(
            paths=paths,
            data_root=Path(args.data_root),
            artifact_root=Path(args.artifact_root),
            engineering_output=Path(args.engineering_output),
        )
    elif args.action == "execute":
        run_development(paths)
    else:
        verify_final(paths)


if __name__ == "__main__":
    main()
