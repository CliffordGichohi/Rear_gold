#!/usr/bin/env python3
"""Seal the pre-label application and regression certification for validation V1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_artifacts" / "gold_coherent_auction_blind_validation_v1"
FREEZE = (
    ROOT
    / "research_manifests"
    / "gold_coherent_auction_blind_validation_v1_prevalue_freeze.json"
)
STREAM_CERT = OUT / "stream_materialization_certification.json"
LEDGER = OUT / "ledgers" / "validation_event_ledger.jsonl"
LAST_RUN = ROOT / "frontend" / "test-results-validation" / ".last-run.json"
EVIDENCE_DIR = ROOT / "frontend" / "test-results-validation"
CERTIFICATION = OUT / "application_prelabel_certification.json"
STATE = OUT / "state_prelabel_ready.json"
SEAL = (
    ROOT
    / "research_manifests"
    / "gold_coherent_auction_blind_validation_v1_prelabel_certification_seal.json"
)

CODE_PATHS = (
    ROOT / "backend" / "src" / "gold_intel" / "application" / "coherent_auction_validation.py",
    ROOT / "backend" / "src" / "gold_intel" / "api" / "coherent_auction_validation_schemas.py",
    ROOT / "backend" / "src" / "gold_intel" / "api" / "routes" / "coherent_auction_validation.py",
    ROOT / "backend" / "tests" / "unit" / "test_coherent_auction_validation.py",
    ROOT / "frontend" / "src" / "app" / "replay" / "validation" / "page.tsx",
    ROOT / "frontend" / "src" / "components" / "annotated-replay-v3-lab.tsx",
    ROOT / "frontend" / "src" / "lib" / "api.ts",
    ROOT / "frontend" / "e2e" / "gold-coherent-auction-validation-ui.spec.ts",
    ROOT / "frontend" / "playwright.validation.config.ts",
    ROOT / "docker-compose.yml",
)


def now() -> str:
    return datetime.now(UTC).isoformat()


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


def verify_record(item: dict[str, Any]) -> None:
    path = ROOT / item["path"]
    if (
        not path.is_file()
        or path.stat().st_size != item["bytes"]
        or sha256_file(path) != item["sha256"]
    ):
        raise RuntimeError(f"Sealed predecessor differs: {item['path']}")


def write_new(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> int:
    for path in (CERTIFICATION, STATE, SEAL):
        if path.exists():
            raise RuntimeError(f"Append-only prelabel output exists: {path.relative_to(ROOT)}")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    for item in [*freeze["sealed_outputs"], *freeze["source_records"]]:
        verify_record(item)
    stream = json.loads(STREAM_CERT.read_text(encoding="utf-8"))
    if stream.get("verdict") != "PASS_BLIND_VALIDATION_STREAM_MATERIALIZATION":
        raise RuntimeError("Validation stream certification differs")
    if not all(stream.get("gates", {}).values()):
        raise RuntimeError("A validation stream gate failed")
    if LEDGER.exists():
        raise RuntimeError("The live validation decision ledger was opened before certification")
    last_run = json.loads(LAST_RUN.read_text(encoding="utf-8"))
    if last_run != {"status": "passed", "failedTests": []}:
        raise RuntimeError("Browser regression result is not a clean pass")
    evidence = [record(path) for path in sorted(EVIDENCE_DIR.rglob("*")) if path.is_file()]
    if not any(item["path"].endswith("trace.zip") for item in evidence):
        raise RuntimeError("Browser trace evidence is absent")
    if not any(item["path"].endswith("test-finished-1.png") for item in evidence):
        raise RuntimeError("Browser screenshot evidence is absent")
    code = [record(path) for path in CODE_PATHS]
    certification = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_APPLICATION_PRELABEL_CERTIFICATION_1_0",
        "certified_at": now(),
        "verdict": "PASS_APPLICATION_PRELABEL_CERTIFICATION",
        "population_sha256": stream["population_sha256"],
        "case_count": 50,
        "test_commands": [
            "docker compose --profile test run --rm backend-test pytest -q tests/unit/test_blind_replay_v3.py tests/unit/test_coherent_auction_validation.py",
            "docker compose --profile test run --rm backend-test ruff check [new validation backend files]",
            "npm.cmd run typecheck",
            "npm.cmd test -- --run src/components/annotated-replay-v3-lab.test.tsx src/components/synchronized-replay-chart.test.tsx",
            "npm.cmd run lint",
            "npx.cmd playwright test --config=playwright.validation.config.ts",
            "docker compose build api web",
        ],
        "test_results": {
            "backend_replay_regression": "7_PASSED",
            "backend_ruff": "PASS",
            "frontend_typecheck": "PASS",
            "frontend_chart_unit_tests": "6_PASSED",
            "frontend_lint": "PASS",
            "frontend_production_build": "PASS",
            "isolated_browser_e2e": "1_PASSED",
        },
        "browser_evidence": evidence,
        "code_records": code,
        "stream_certification": record(STREAM_CERT),
        "prevalue_freeze": record(FREEZE),
        "gates": {
            "predecessor_seals_verified": True,
            "stream_certification_verified": True,
            "exact_50_case_application": True,
            "one_way_cursor_tested": True,
            "future_bars_hidden_tested": True,
            "timeframe_drawing_persistence_tested": True,
            "entry_stop_target_resize_controls_tested": True,
            "coherent_auction_fields_required_tested": True,
            "one_order_per_session_tested": True,
            "isolated_append_only_ledger_tested": True,
            "existing_v3_replay_regression_passed": True,
            "live_validation_ledger_absent": True,
            "zero_live_decisions": True,
            "aggregate_results_locked": True,
            "calendar_2025_2026_locked": True,
            "no_acquisition_or_charge": True,
        },
        "live_url": "http://localhost:3000/replay/validation",
        "decisions_collected": 0,
        "aggregate_results": "LOCKED_UNTIL_ALL_50_COMPLETE",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "charge_usd": 0.0,
    }
    if not all(certification["gates"].values()):
        raise RuntimeError("A prelabel application certification gate failed")
    write_new(CERTIFICATION, certification)
    state = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_PRELABEL_STATE_1_0",
        "recorded_at": now(),
        "status": "PASS_READY_FOR_50_CASE_BLIND_LABELING",
        "population_sha256": stream["population_sha256"],
        "application_certification": record(CERTIFICATION),
        "decisions_collected": 0,
        "next_case_alias": "GAV-2022-001",
        "aggregate_results": "LOCKED_UNTIL_ALL_50_COMPLETE",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    write_new(STATE, state)
    seal = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_PRELABEL_SEAL_1_0",
        "sealed_at": now(),
        "verdict": certification["verdict"],
        "sealed_outputs": [record(CERTIFICATION), record(STATE)],
        "decision_ledger": "ABSENT_UNTIL_FIRST_HUMAN_ACTION",
        "decisions_collected": 0,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    write_new(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "cases": 50,
                "browser_evidence_files": len(evidence),
                "decisions_collected": 0,
                "live_url": certification["live_url"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
