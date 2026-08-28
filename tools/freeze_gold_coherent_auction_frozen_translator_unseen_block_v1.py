#!/usr/bin/env python3
"""Seal the one-shot unseen-block wrapper without opening stream values."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_frozen_translator_unseen_block_v1"
)
FREEZE = OUT / "prevalue_freeze.json"
CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_FROZEN_TRANSLATOR_UNSEEN_BLOCK_V1.md"
RUNNER = ROOT / "tools" / "run_gold_coherent_auction_frozen_translator_unseen_block_v1.py"
VALIDATION = ROOT / "research_artifacts" / "gold_coherent_auction_blind_validation_v1"
REGISTRY = VALIDATION / "population_registry.private.json"
CERTIFICATION = VALIDATION / "stream_materialization_certification.json"
PRIMARY = VALIDATION / "validation_streams.primary.jsonl.gz"
REFERENCE = VALIDATION / "validation_streams.reference.jsonl.gz"
FRESH_LEDGER = VALIDATION / "ledgers" / "validation_event_ledger.jsonl"
STATE = VALIDATION / "state_prelabel_ready.json"

POPULATION_SHA256 = "36a60ccfccedda19a39a48e6c38326b5f0d54f8bd7380cfd1595aa27d8c791f3"
STATIC_HASHES = {
    "research_artifacts/gold_coherent_auction_end_to_end_same_month_v1/translator.json": "c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841",
    "research_artifacts/gold_coherent_auction_end_to_end_same_month_v1/autonomous_result.json": "c2ff398eaf3cb865191e85bace5542a79a9d23063fe51d164c4b31bc7979637d",
    "research_artifacts/gold_coherent_auction_blind_validation_v1/population_registry.private.json": "2faef0abde0bd677ec9712bb676c7114dcd39037d4d2da40b417d9ec4ff912ad",
    "research_artifacts/gold_coherent_auction_blind_validation_v1/stream_materialization_certification.json": "7d079c11c3b55dce81d0972ac82102cf8c8963e5e6ae4644e48fb4291e57014a",
    "research_artifacts/gold_coherent_auction_blind_validation_v1/validation_streams.primary.jsonl.gz": "b3f1628e30f1549253478fb45d628bd09eab3abf95fed492c715e030a9b819ef",
    "research_artifacts/gold_coherent_auction_blind_validation_v1/validation_streams.reference.jsonl.gz": "b3f1628e30f1549253478fb45d628bd09eab3abf95fed492c715e030a9b819ef",
    "tools/run_gold_coherent_auction_end_to_end_v1_inference.py": "eff0abf5dac037668764b93c8435a0dffd00e7d5bd581a36af133e013d25aba8",
    "tools/gold_coherent_auction_end_to_end_v1_common.py": "10e17637bc90da02dd5b37ead0a6615347856808285b2d97a03b5950877330d2",
    "backend/src/gold_intel/analytics/coherent_auction_human_policy_v2.py": "694b441ddf8174921a4e2e689d892018473f075fa638225a805e76d25b43412f",
    "backend/src/gold_intel/analytics/coherent_auction_correction_v1.py": "5d037652eff5148af05e7ab401c40c2374749c07af9901a80c4ff4b671d2b14d",
}
DEPENDENCY_PATHS = [
    "tools/calibrate_gold_coherent_auction_autonomous_semantics_v1.py",
    "backend/src/gold_intel/analytics/liquidity_shift_v2.py",
    "backend/src/gold_intel/analytics/liquidity_shift_v3.py",
    "backend/src/gold_intel/application/market_structure.py",
]


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> int:
    require(not FREEZE.exists(), "Prevalue freeze already exists")
    require(CONTRACT.is_file(), "Contract is absent")
    require(RUNNER.is_file(), "Runner is absent")
    require(
        "AUTHORIZED_AND_FROZEN_BEFORE_UNSEEN_STREAM_OPEN"
        in CONTRACT.read_text(encoding="utf-8"),
        "Contract status differs",
    )
    for relative, expected in STATIC_HASHES.items():
        path = ROOT / relative
        require(path.is_file(), f"Frozen predecessor absent: {relative}")
        require(sha256_file(path) == expected, f"Frozen predecessor differs: {relative}")

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    require(registry["case_count"] == 50, "Population count differs")
    require(registry["population_sha256"] == POPULATION_SHA256, "Population differs")
    require(
        [row["case_alias"] for row in registry["cases"]]
        == [f"GAV-2022-{index:03d}" for index in range(1, 51)],
        "Population aliases differ",
    )
    require(
        Counter(row["session_code"] for row in registry["cases"])
        == Counter({"LONDON": 25, "NEW_YORK": 25}),
        "Session balance differs",
    )
    dates = [row["trading_date_utc"] for row in registry["cases"]]
    require(min(dates) == "2022-08-08", "Minimum date differs")
    require(max(dates) == "2022-12-30", "Maximum date differs")

    certification = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
    require(
        certification["verdict"] == "PASS_BLIND_VALIDATION_STREAM_MATERIALIZATION",
        "Validation source certification is not PASS",
    )
    require(certification["case_count"] == 50, "Certification count differs")
    require(
        certification["population_sha256"] == POPULATION_SHA256,
        "Certification population differs",
    )
    require(
        certification["primary_sha256"] == STATIC_HASHES[PRIMARY.relative_to(ROOT).as_posix()],
        "Primary certification hash differs",
    )
    require(
        certification["reference_sha256"] == STATIC_HASHES[REFERENCE.relative_to(ROOT).as_posix()],
        "Reference certification hash differs",
    )
    require(not FRESH_LEDGER.exists(), "Fresh human decision ledger is present")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    require(state["decisions_collected"] == 0, "Fresh decisions already exist")

    paths = [
        CONTRACT,
        RUNNER,
        *(ROOT / relative for relative in STATIC_HASHES),
        *(ROOT / relative for relative in DEPENDENCY_PATHS),
        STATE,
    ]
    records = {path.relative_to(ROOT).as_posix(): file_record(path) for path in paths}
    payload: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_FROZEN_TRANSLATOR_UNSEEN_BLOCK_V1_PREVALUE_FREEZE_1_0",
        "sealed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "SEALED_BEFORE_UNSEEN_STREAM_OPEN",
        "population_sha256": POPULATION_SHA256,
        "case_count": 50,
        "session_counts": {"LONDON": 25, "NEW_YORK": 25},
        "date_min": min(dates),
        "date_max": max(dates),
        "translator_fitting_permitted": False,
        "retuning_permitted": False,
        "fresh_decisions_collected": 0,
        "fresh_results_calculated": False,
        "stream_values_opened_by_this_branch": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "files": records,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    OUT.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "freeze_sha256": payload["freeze_sha256"],
                "case_count": payload["case_count"],
                "date_min": payload["date_min"],
                "date_max": payload["date_max"],
                "fresh_decisions_collected": 0,
                "stream_values_opened_by_this_branch": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
