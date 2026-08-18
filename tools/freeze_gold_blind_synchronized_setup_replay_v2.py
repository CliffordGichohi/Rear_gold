#!/usr/bin/env python3
"""Freeze Gold Blind Synchronized Setup Replay V2 before materialization."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_CONTRACT.md"
PREDECESSOR = ROOT / "research_manifests/gold_blind_discretionary_replay_v1_prelabel_ui_amendment_f_freeze.json"
ARTIFACT = ROOT / "research_artifacts/gold_blind_discretionary_replay_v1"
LEDGER = ARTIFACT / "decisions/decision_ledger_v1.jsonl"
PRIVATE_REGISTRY = ARTIFACT / "population_registry_v1_1.private.json"
STATE = ROOT / "research_artifacts/gold_blind_synchronized_setup_replay_v2/preimplementation_state.json"
FREEZE = ROOT / "research_manifests/gold_blind_synchronized_setup_replay_v2_preimplementation_freeze.json"

SOURCES = (
    PREDECESSOR,
    PRIVATE_REGISTRY,
    ROOT / "research_manifests/gold_blind_discretionary_replay_v1_population_freeze_v1_1.json",
    ARTIFACT / "display_payloads_v1_1.primary.jsonl.gz",
    ARTIFACT / "display_payloads_v1_1.reference.jsonl.gz",
    ARTIFACT / "practice_future_paths_v1_1.primary.jsonl.gz",
    ARTIFACT / "practice_future_paths_v1_1.reference.jsonl.gz",
    ARTIFACT / "materialization_certification_v1_1.json",
    ROOT / "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> int:
    if STATE.exists() or FREEZE.exists():
        raise RuntimeError("V2 preimplementation state already exists")
    if LEDGER.exists():
        raise RuntimeError("V1 decisions exist; V2 zero-decision freeze refused")
    if any(not path.is_file() for path in (CONTRACT, *SOURCES)):
        raise RuntimeError("A required V2 predecessor or source is missing")

    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("status") != "SEALED_READY_FOR_HUMAN_LABELING_UI_AMENDMENT_F":
        raise RuntimeError("V1 UI Amendment F predecessor is not sealed")
    certification = json.loads((ARTIFACT / "materialization_certification_v1_1.json").read_text(encoding="utf-8"))
    if certification.get("verdict") != "PASS_PAST_ONLY_DISPLAY_MATERIALIZATION_AMENDMENT_A" or not all(certification.get("gates", {}).values()):
        raise RuntimeError("V1.1 display/practice sources are not certified")
    registry = json.loads(PRIVATE_REGISTRY.read_text(encoding="utf-8"))
    practice = [row for row in registry["cases"] if row["mode"] == "PRACTICE"]
    scored = [row for row in registry["cases"] if row["mode"] == "SCORED"]
    aliases = [row["case_alias"] for row in practice]
    expected = [f"P-{index:03d}" for index in range(1, 21)]
    if aliases != expected or len(scored) != 240:
        raise RuntimeError("V1.1 population identities differ")

    gates = {
        "contract_frozen": True,
        "predecessor_sealed": True,
        "zero_decisions": not LEDGER.exists(),
        "practice_population_exact_20": aliases == expected,
        "scored_population_identified_but_closed": len(scored) == 240,
        "v1_1_sources_certified": True,
        "calendar_2025_locked": predecessor.get("calendar_2025") == "LOCKED_NOT_INSPECTED",
        "calendar_2026_locked": predecessor.get("calendar_2026") == "LOCKED_NOT_INSPECTED",
        "no_acquisition_or_charge": predecessor.get("acquisition_performed") is False and predecessor.get("charge_usd") == 0,
    }
    if not all(gates.values()):
        raise RuntimeError(f"V2 freeze gate failure: {gates}")

    state = {
        "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_PREIMPLEMENTATION_STATE_1_0",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "FROZEN_BEFORE_V2_VALUE_MATERIALIZATION_OR_IMPLEMENTATION",
        "contract": file_record(CONTRACT),
        "sources": [file_record(path) for path in SOURCES],
        "population": {
            "practice_aliases": aliases,
            "practice_population_sha256": canonical_hash(practice),
            "scored_count_closed": len(scored),
            "initial_cursor_minute": 0,
            "maximum_cursor_minute": 180,
        },
        "gates": gates,
        "human_decisions_collected": 0,
        "scored_access": "CLOSED_PENDING_V2_CERTIFICATION",
        "calendar_2025": "LOCKED_NOT_INSPECTED",
        "calendar_2026": "LOCKED_NOT_INSPECTED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    write_new(STATE, state)
    freeze = {
        "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_PREIMPLEMENTATION_FREEZE_1_0",
        "sealed_at": datetime.now(UTC).isoformat(),
        "status": state["status"],
        "contract_sha256": state["contract"]["sha256"],
        "source_records": state["sources"],
        "source_records_sha256": canonical_hash(state["sources"]),
        "practice_population_sha256": state["population"]["practice_population_sha256"],
        "practice_aliases": aliases,
        "human_decisions_collected": 0,
        "scored_access": state["scored_access"],
        "calendar_2025": state["calendar_2025"],
        "calendar_2026": state["calendar_2026"],
        "acquisition_performed": False,
        "charge_usd": 0.0,
        "sealed_files": [file_record(CONTRACT), file_record(Path(__file__).resolve()), file_record(STATE)],
    }
    freeze["sealed_files_sha256"] = canonical_hash(freeze["sealed_files"])
    write_new(FREEZE, freeze)
    print(json.dumps({"status": freeze["status"], "practice_cases": len(aliases), "scored_access": freeze["scored_access"], "human_decisions": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

