#!/usr/bin/env python3
"""Freeze Recovery A after the shell timeout and before source-value access."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1"
PROTOCOL = OUT / "materialization_recovery_a_protocol.json"
IMPLEMENTATION = ROOT / "tools/materialize_gold_blind_codex_operator_replay_v1.py"
AMENDMENT = ROOT / "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_MATERIALIZATION_RECOVERY_A.md"
PREVALUE = ROOT / "research_manifests/gold_blind_codex_operator_replay_v1_prevalue_freeze.json"
BROWSER = OUT / "browser_isolation_certification.json"
PARTIAL = OUT / "private_streams/primary"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if PROTOCOL.exists():
        raise RuntimeError("Append-only Recovery A protocol already exists")
    files = sorted(PARTIAL.glob("*.json.gz"))
    aliases = [path.stem.removesuffix(".json") for path in files]
    if aliases != [f"CBR-2022-{index:03d}" for index in range(1, 15)]:
        raise RuntimeError("Attempt-1 metadata prefix differs")
    if (OUT / "private_streams/reference").exists() or (OUT / "stream_materialization_certification.json").exists():
        raise RuntimeError("Attempt-1 metadata disposition differs")
    payload = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_MATERIALIZATION_RECOVERY_A_PROTOCOL_1_0",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "status": "SEALED_BEFORE_RECOVERY_A_SOURCE_VALUE_ACCESS",
        "failure_metadata": {
            "shell_exit_code": 124,
            "timeout_seconds": 120,
            "partial_primary_files": 14,
            "reference_started": False,
            "certification_written": False,
        },
        "implementation_sha256": sha(IMPLEMENTATION),
        "amendment_sha256": sha(AMENDMENT),
        "prevalue_freeze_sha256": sha(PREVALUE),
        "browser_certification_sha256": sha(BROWSER),
        "correction": "BINARY_SEARCH_CLOSE_TIME_INDEX_ONLY",
        "output_root": "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams_recovery_a",
        "research_definitions_changed": False,
        "market_values_inspected_or_reported": False,
        "outcomes_accessed": False,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "charge_usd": 0.0,
    }
    PROTOCOL.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "partial_primary_files": 14,
        "research_definitions_changed": False,
        "implementation_sha256": payload["implementation_sha256"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
