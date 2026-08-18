#!/usr/bin/env python3
"""Obtain the frozen Step 3B.1 MBP-10 metadata quote.

This utility exposes no batch submission, time-series retrieval, or download
action. It validates the frozen protocol and predecessor hashes, then calls
only Databento metadata cost, record-count, and billable-size endpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3b1_protocol_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3b1_freeze_v01.json"
)
EXPECTED_PROTOCOL_SHA256 = (
    "07860e02cf4f76487a0f334faa2987e0a0cf97f8977ca61f995c533f617022c5"
)
EXPECTED_FREEZE_SHA256 = (
    "b418883b2c94ff3b7efcf3e8bc4bf3bd121760cd036aeef0adae7806a099f681"
)
EXPECTED_SDK_VERSION = "0.82.0"
REQUEST: dict[str, Any] = {
    "dataset": "GLBX.MDP3",
    "symbols": ["GC.v.0"],
    "schema": "mbp-10",
    "stype_in": "continuous",
    "start": "2024-01-09T00:00:00Z",
    "end": "2024-01-10T00:00:00Z",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env"))
    args = parser.parse_args()

    verification = _verify_frozen_context()
    key = _api_key(Path(args.env_file))
    client, sdk_version = _client(key)
    if sdk_version != EXPECTED_SDK_VERSION:
        raise RuntimeError(
            f"Databento SDK changed: expected {EXPECTED_SDK_VERSION}, "
            f"got {sdk_version}"
        )

    cost = float(client.metadata.get_cost(**REQUEST))
    record_count = int(client.metadata.get_record_count(**REQUEST))
    billable_size = int(client.metadata.get_billable_size(**REQUEST))
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("Databento returned an invalid estimated cost")
    if record_count <= 0:
        raise ValueError("Databento returned a nonpositive record count")
    if billable_size <= 0:
        raise ValueError("Databento returned a nonpositive billable size")

    result = {
        "version": "GC_MICROSTRUCTURE_STEP_3B1_METADATA_QUOTE_V0_1",
        "stage": "STEP_3B1_METADATA_ONLY_QUOTE",
        "status": "QUOTE_RECEIVED",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "request": REQUEST,
        "estimated_cost_usd": cost,
        "expected_record_count": record_count,
        "expected_billable_size_bytes": billable_size,
        "sdk_version": sdk_version,
        "frozen_context": verification,
        "api_calls_performed": [
            "metadata.get_cost",
            "metadata.get_record_count",
            "metadata.get_billable_size",
        ],
        "batch_api_called": False,
        "timeseries_api_called": False,
        "batch_job_submitted": False,
        "data_downloaded": False,
        "charge_incurred": False,
        "mbp10_values_accessed": False,
        "market_outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    result["quote_hash"] = _canonical_hash(result)
    print(json.dumps(result, sort_keys=True))


def _verify_frozen_context() -> dict[str, Any]:
    if _sha256(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 3B.1 protocol changed after freeze")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 3B.1 freeze receipt changed")

    protocol = _load_json(PROTOCOL_PATH)
    freeze = _load_json(FREEZE_PATH)
    if protocol.get("status") != (
        "FROZEN_BEFORE_MBP10_METADATA_QUOTE_AND_VALUE_ACCESS"
    ):
        raise ValueError("Step 3B.1 protocol is not frozen")
    if protocol.get("metadata_quote_request") != REQUEST:
        raise ValueError("Metadata request differs from frozen request")
    if freeze.get("status") != "SEALED_BEFORE_METADATA_QUOTE":
        raise ValueError("Step 3B.1 freeze receipt is invalid")
    if freeze.get("protocol") != {
        "path": "research_manifests/gc_microstructure_step_3b1_protocol_v01.json",
        "bytes": 12576,
        "sha256": EXPECTED_PROTOCOL_SHA256,
    }:
        raise ValueError("Freeze receipt does not bind the frozen protocol")

    predecessor = protocol["predecessor_preservation"]
    for item in predecessor["frozen_files"]:
        path = REPO_ROOT / str(item["path"])
        if not path.is_file():
            raise FileNotFoundError(f"Frozen predecessor missing: {path}")
        if path.stat().st_size != int(item["bytes"]):
            raise ValueError(f"Frozen predecessor byte count changed: {path}")
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"Frozen predecessor hash changed: {path}")

    step_3a_manifest = _load_json(
        REPO_ROOT / predecessor["step_3a"]["manifest_path"]
    )
    step_3a1_manifest = _load_json(
        REPO_ROOT / predecessor["step_3a1"]["manifest_path"]
    )
    if (
        step_3a_manifest.get("status") != "FAIL"
        or step_3a_manifest.get("manifest_hash")
        != predecessor["step_3a"]["declared_manifest_hash"]
    ):
        raise ValueError("Step 3A formal FAIL or manifest hash changed")
    if (
        step_3a1_manifest.get("status") != "PASS"
        or step_3a1_manifest.get("manifest_hash")
        != predecessor["step_3a1"]["declared_manifest_hash"]
        or step_3a1_manifest.get("predecessor_formal_verdict_preserved")
        is not True
    ):
        raise ValueError("Step 3A.1 PASS or predecessor preservation changed")

    return {
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "predecessor_files_verified": len(predecessor["frozen_files"]) + 2,
        "step_3a_formal_verdict": "FAIL",
        "step_3a_declared_manifest_hash": step_3a_manifest["manifest_hash"],
        "step_3a1_formal_verdict": "PASS",
        "step_3a1_declared_manifest_hash": step_3a1_manifest["manifest_hash"],
    }


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


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


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


if __name__ == "__main__":
    main()
