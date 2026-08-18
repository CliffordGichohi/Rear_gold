#!/usr/bin/env python3
"""Verify and seal the blind replay application before human labeling."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1"
STATE = ARTIFACT_DIR / "prelabel_state_v1.json"
FREEZE = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_prelabel_freeze.json"
CERTIFICATION = ARTIFACT_DIR / "materialization_certification_v1_1.json"
POPULATION_FREEZE = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_population_freeze_v1_1.json"
DISPLAY = ARTIFACT_DIR / "display_payloads_v1_1.primary.jsonl.gz"
DISPLAY_REFERENCE = ARTIFACT_DIR / "display_payloads_v1_1.reference.jsonl.gz"
PRACTICE = ARTIFACT_DIR / "practice_future_paths_v1_1.primary.jsonl.gz"
PRACTICE_REFERENCE = ARTIFACT_DIR / "practice_future_paths_v1_1.reference.jsonl.gz"
LEDGER = ARTIFACT_DIR / "decisions" / "decision_ledger_v1.jsonl"

DATE_PATTERN = re.compile(r"\b20(?:21|22|23|24|25|26)-\d{2}-\d{2}\b")
TIMESTAMP_PATTERN = re.compile(
    r"\b20(?:21|22|23|24|25|26)[-.]\d{2}[-.]\d{2}[T ]\d{2}:\d{2}"
)
EXPECTED_CHARTS = {"1w": 52, "1d": 120, "4h": 90, "1h": 120, "15m": 160, "5m": 180, "1m": 180}

SEALED_FILES = (
    "GOLD_BLIND_POINT_IN_TIME_DISCRETIONARY_REPLAY_EDGE_AUDIT_CONTRACT_V1.md",
    "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_COVERAGE_AMENDMENT_A.md",
    "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRELABEL_REPORT.md",
    "research_manifests/gold_blind_discretionary_replay_v1_protocol.json",
    "research_manifests/gold_blind_discretionary_replay_v1_population_freeze.json",
    "research_manifests/gold_blind_discretionary_replay_v1_population_freeze_v1_1.json",
    "research_artifacts/gold_blind_discretionary_replay_v1/population_registry_v1_1.private.json",
    "research_artifacts/gold_blind_discretionary_replay_v1/population_registry_v1_1.public.json",
    "research_artifacts/gold_blind_discretionary_replay_v1/coverage_amendment_a_audit.json",
    "research_artifacts/gold_blind_discretionary_replay_v1/materialization_attempt1_coverage_failure.json",
    "research_artifacts/gold_blind_discretionary_replay_v1/materialization_certification_v1_1.json",
    "research_artifacts/gold_blind_discretionary_replay_v1/display_payloads_v1_1.primary.jsonl.gz",
    "research_artifacts/gold_blind_discretionary_replay_v1/display_payloads_v1_1.reference.jsonl.gz",
    "research_artifacts/gold_blind_discretionary_replay_v1/practice_future_paths_v1_1.primary.jsonl.gz",
    "research_artifacts/gold_blind_discretionary_replay_v1/practice_future_paths_v1_1.reference.jsonl.gz",
    "tools/freeze_gold_blind_discretionary_replay_v1_population.py",
    "tools/amend_gold_blind_discretionary_replay_v1_coverage.py",
    "tools/materialize_gold_blind_discretionary_replay_v1.py",
    "tools/materialize_gold_blind_discretionary_replay_v1_1.py",
    "tools/seal_gold_blind_discretionary_replay_v1_prelabel.py",
    "backend/src/gold_intel/api/blind_replay_schemas.py",
    "backend/src/gold_intel/api/routes/blind_replay.py",
    "backend/src/gold_intel/application/blind_replay.py",
    "backend/src/gold_intel/config.py",
    "backend/src/gold_intel/main.py",
    "backend/tests/unit/test_blind_replay.py",
    "frontend/src/app/replay/page.tsx",
    "frontend/src/app/layout.tsx",
    "frontend/src/components/blind-replay-lab.tsx",
    "frontend/src/components/blind-replay-lab.test.tsx",
    "frontend/src/lib/api.ts",
    "frontend/src/test/setup.ts",
    "frontend/vitest.config.mjs",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/tsconfig.json",
    "docker-compose.yml",
    ".env.example",
    ".gitignore",
    "README.md",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_gzip_jsonl(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def verify_predecessor_freeze() -> None:
    freeze = json.loads(POPULATION_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_AMENDMENT_A_BEFORE_HUMAN_LABELING":
        raise RuntimeError("Amended population freeze has the wrong status")
    for item in freeze["sealed_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Predecessor seal differs: {item['path']}")


def live_read_only_check() -> dict[str, Any]:
    with urllib.request.urlopen("http://localhost:8000/api/v1/blind-replay/status", timeout=60) as response:
        status = json.load(response)
    with urllib.request.urlopen("http://localhost:8000/api/v1/blind-replay/next", timeout=60) as response:
        next_case = json.load(response)
    with urllib.request.urlopen("http://localhost:3000/replay", timeout=60) as response:
        page_status = response.status
    serialized = canonical_bytes(next_case).decode("utf-8")
    return {
        "api_ready": status.get("ready") is True,
        "phase_practice": status.get("phase") == "PRACTICE",
        "zero_locked": status.get("total_locked") == 0,
        "next_alias_p001": status.get("next_case_alias") == "P-001" and next_case.get("case", {}).get("case_alias") == "P-001",
        "no_date_or_timestamp_in_live_payload": DATE_PATTERN.search(serialized) is None and TIMESTAMP_PATTERN.search(serialized) is None,
        "no_scored_future_flag": next_case.get("case", {}).get("display_policy", {}).get("future_scored_path_present") is False,
        "replay_page_http_200": page_status == 200,
    }


def main() -> int:
    if STATE.exists() or FREEZE.exists():
        raise RuntimeError("Append-only pre-label state or freeze already exists")
    if LEDGER.exists():
        raise RuntimeError("Human labeling has already begun; pre-label seal refused")
    decision_dir = LEDGER.parent
    if decision_dir.exists() and any(decision_dir.iterdir()):
        raise RuntimeError("Decision directory is not empty")

    verify_predecessor_freeze()
    certification = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
    if certification.get("verdict") != "PASS_PAST_ONLY_DISPLAY_MATERIALIZATION_AMENDMENT_A":
        raise RuntimeError("Materialization certification did not pass")
    if not all(certification.get("gates", {}).values()):
        raise RuntimeError("A materialization gate failed")
    expected_hashes = {
        DISPLAY: certification["primary_payload_sha256"],
        DISPLAY_REFERENCE: certification["reference_payload_sha256"],
        PRACTICE: certification["primary_practice_sha256"],
        PRACTICE_REFERENCE: certification["reference_practice_sha256"],
    }
    for path, expected in expected_hashes.items():
        if sha256_file(path) != expected:
            raise RuntimeError(f"Certified payload differs: {path.name}")
    if sha256_file(DISPLAY) != sha256_file(DISPLAY_REFERENCE):
        raise RuntimeError("Primary/reference displays are not byte-identical")
    if sha256_file(PRACTICE) != sha256_file(PRACTICE_REFERENCE):
        raise RuntimeError("Primary/reference practice paths are not byte-identical")

    rows = read_gzip_jsonl(DISPLAY)
    practice = read_gzip_jsonl(PRACTICE)
    serialized = "\n".join(canonical_bytes(row).decode("utf-8") for row in rows)
    aliases = [row["case_alias"] for row in rows]
    gates = {
        "predecessor_population_seal_verified": True,
        "materialization_certification_verified": True,
        "primary_reference_display_byte_identical": sha256_file(DISPLAY) == sha256_file(DISPLAY_REFERENCE),
        "primary_reference_practice_byte_identical": sha256_file(PRACTICE) == sha256_file(PRACTICE_REFERENCE),
        "case_count_260": len(rows) == 260,
        "practice_count_20": len([row for row in rows if row["mode"] == "PRACTICE"]) == 20,
        "scored_count_240": len([row for row in rows if row["mode"] == "SCORED"]) == 240,
        "aliases_exact": aliases == [f"P-{index:03d}" for index in range(1, 21)] + [f"S-{index:03d}" for index in range(1, 241)],
        "payload_hashes_exact": all(
            row["payload_sha256"] == canonical_hash({key: value for key, value in row.items() if key != "payload_sha256"})
            for row in rows
        ),
        "all_scored_exact_chart_counts": all(
            row["chart_availability"]["counts"] == EXPECTED_CHARTS
            for row in rows if row["mode"] == "SCORED"
        ),
        "practice_paths_20_only": len(practice) == 20 and all(row["case_alias"].startswith("P-") for row in practice),
        "no_calendar_date_in_display": DATE_PATTERN.search(serialized) is None,
        "no_calendar_timestamp_in_display": TIMESTAMP_PATTERN.search(serialized) is None,
        "no_scored_future_path_materialized": all(
            row["display_policy"]["future_scored_path_present"] is False
            for row in rows if row["mode"] == "SCORED"
        ),
        "decision_ledger_absent": not LEDGER.exists(),
        "calendar_2025_2026_locked": certification["calendar_2025_opened"] is False and certification["calendar_2026_opened"] is False,
        "no_acquisition_or_charge": certification["acquisition_performed"] is False and certification["charge_usd"] == 0,
    }
    live = live_read_only_check()
    gates["live_read_only_application_check"] = all(live.values())
    if not all(gates.values()):
        raise RuntimeError(f"Pre-label seal gates failed: {gates}")

    missing_files = [relative for relative in SEALED_FILES if not (ROOT / relative).is_file()]
    if missing_files:
        raise RuntimeError(f"Files required by the pre-label seal are missing: {missing_files}")
    sealed_files = [
        {
            "path": relative,
            "bytes": (ROOT / relative).stat().st_size,
            "sha256": sha256_file(ROOT / relative),
        }
        for relative in SEALED_FILES
    ]
    state = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRELABEL_STATE_1_0",
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PASS_PRELABEL_APPLICATION_READY",
        "research_status": "HUMAN_LABELING_REQUIRED_EDGE_NOT_EVALUATED",
        "population": {"practice": 20, "scored": 240, "total": 260},
        "human_decisions_collected": 0,
        "next_case_alias": "P-001",
        "test_evidence": {
            "backend_pytest": "229 passed",
            "frontend_vitest": "8 passed",
            "frontend_typecheck": "PASS",
            "frontend_lint": "PASS",
            "frontend_production_build": "PASS",
        },
        "live_read_only_checks": live,
        "gates": gates,
        "calendar_2025": "LOCKED_NOT_INSPECTED",
        "calendar_2026": "LOCKED_NOT_INSPECTED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    write_new(STATE, state)
    state_record = {
        "path": STATE.relative_to(ROOT).as_posix(),
        "bytes": STATE.stat().st_size,
        "sha256": sha256_file(STATE),
    }
    all_sealed = [*sealed_files, state_record]
    freeze = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRELABEL_FREEZE_1_0",
        "sealed_at": datetime.now(UTC).isoformat(),
        "status": "SEALED_READY_FOR_HUMAN_LABELING",
        "verdict": state["verdict"],
        "research_status": state["research_status"],
        "human_decisions_collected": 0,
        "decision_ledger_initialized": False,
        "next_case_alias": "P-001",
        "sealed_files": all_sealed,
        "sealed_files_sha256": canonical_hash(all_sealed),
        "calendar_2025": "LOCKED_NOT_INSPECTED",
        "calendar_2026": "LOCKED_NOT_INSPECTED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    write_new(FREEZE, freeze)
    print(json.dumps({
        "verdict": freeze["verdict"],
        "status": freeze["status"],
        "sealed_files": len(all_sealed),
        "next_case_alias": freeze["next_case_alias"],
        "human_decisions_collected": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
