#!/usr/bin/env python3
"""Freeze V3 post-practice diagnostics before full outcome access."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "research_artifacts/gold_annotated_replay_v3"
LEDGER = ARTIFACT / "ledgers/practice_event_ledger_v3.jsonl"
AMENDMENT = ROOT / "GOLD_ANNOTATED_REPLAY_V3_POST_PRACTICE_DIAGNOSTIC_AMENDMENT_A.md"
PREDECESSOR = ROOT / "research_manifests/gold_annotated_replay_v3_practice_certification_seal.json"
PRIMARY = ARTIFACT / "practice_streams_v3_1.primary.jsonl.gz"
REFERENCE = ARTIFACT / "practice_streams_v3_1.reference.jsonl.gz"
OUTPUT = ROOT / "research_manifests/gold_annotated_replay_v3_post_practice_diagnostic_amendment_a_freeze.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    require(not OUTPUT.exists(), "Append-only diagnostic freeze already exists")
    for path in (LEDGER, AMENDMENT, PREDECESSOR, PRIMARY, REFERENCE):
        require(path.is_file(), f"Missing required source: {path.relative_to(ROOT)}")

    events = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()]
    require(len(events) == 2041, "Human ledger record count differs from authorization")
    require([row["ledger_sequence"] for row in events] == list(range(1, 2042)), "Ledger sequence differs")
    require(
        events[-1]["record_sha256"]
        == "fd347277b2cd312469689fd142fa78b30836208a60d26561baa478287f60a416",
        "Ledger head differs from authorization",
    )
    completed = sorted(
        row["case_alias"] for row in events if row["event_type"] == "PRACTICE_DAY_COMPLETED"
    )
    require(completed == [f"V3-P-{index:03d}" for index in range(1, 21)], "Practice completion set differs")
    require(sha256_file(PRIMARY) == sha256_file(REFERENCE), "Certified stream hashes differ")

    payload = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_POST_PRACTICE_DIAGNOSTIC_AMENDMENT_A_FREEZE_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "status": "SEALED_BEFORE_FULL_PRACTICE_OUTCOME_ANALYSIS",
        "authorization": "USER_EXPLICIT_POST_COMPLETION_ANALYSIS_REQUEST_2026_08_17",
        "research_credit": "ZERO_CREDIT_DESCRIPTIVE",
        "practice_cases": 20,
        "ledger_records": len(events),
        "ledger_head_sha256": events[-1]["record_sha256"],
        "pre_analysis_exposure": "FIRST_TWO_INDIVIDUAL_LIFECYCLES_ONLY_FOR_CAPTURE_CONFIRMATION",
        "frozen_sources": [record(path) for path in (AMENDMENT, PREDECESSOR, LEDGER, PRIMARY, REFERENCE)],
        "frozen_methods": {
            "primary_return": "NET_PNL_DIVIDED_BY_50_USD",
            "secondary_return": "NET_PNL_DIVIDED_BY_SUBMITTED_PLANNED_RISK",
            "mfe_mae": "ACTUAL_FILL_THROUGH_ACTUAL_EXIT_INCLUSIVE_M1",
            "same_bar": "RECORDED_STOP_FIRST",
            "win_rate_interval": "WILSON_95",
            "expectancy_interval": "COMPLETED_DAY_CLUSTER_BOOTSTRAP_20000_SEED_20260817",
            "segment_support_floor": 3,
            "sharpe_sortino_minimum_trades": 30,
            "independent_reproduction": True,
        },
        "one_year_collection": "CLOSED_NOT_MATERIALIZED_OR_ACCESSIBLE",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    with OUTPUT.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "practice_cases": 20,
                "ledger_records": len(events),
                "freeze_sha256": sha256_file(OUTPUT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
