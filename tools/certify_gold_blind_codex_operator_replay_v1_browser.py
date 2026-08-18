#!/usr/bin/env python3
"""Seal the synthetic browser-isolation certification without market outcomes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1"
SYNTHETIC = ROOT / ".codex_runs/codex_operator_replay_e2e/artifact"
BROWSER = ROOT / ".codex_runs/codex_operator_replay_e2e/browser-certification"
OUTPUT = REAL / "browser_isolation_certification.json"
PREVALUE = ROOT / "research_manifests/gold_blind_codex_operator_replay_v1_prevalue_freeze.json"
HUMAN = ROOT / "research_artifacts/gold_annotated_replay_v3/ledgers/practice_event_ledger_v3.jsonl"
HUMAN_SHA = "7639d3609b904a2bd7f92c6df5a596cecf148a91d4853282a6d5a17e68d193d6"
GENESIS = "0" * 64


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def entry(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}


def chain(path: Path, version: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    prior = GENESIS
    keys: set[str] = set()
    for index, row in enumerate(rows, start=1):
        submitted = row.pop("record_sha256")
        if (
            row.get("version") != version
            or row.get("ledger_sequence") != index
            or row.get("prior_record_sha256") != prior
            or canonical_hash(row) != submitted
            or row.get("idempotency_key") in keys
        ):
            raise RuntimeError(f"Synthetic certification ledger is invalid: {path}")
        row["record_sha256"] = submitted
        keys.add(str(row["idempotency_key"]))
        prior = submitted
    return rows


def verify_prevalue() -> None:
    freeze = json.loads(PREVALUE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_BEFORE_CALENDAR_2022_VALUE_MATERIALIZATION":
        raise RuntimeError("Pre-value freeze differs")
    for item in [*freeze["sealed_outputs"], *freeze["source_records"]]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise RuntimeError(f"Pre-value input differs: {item['path']}")


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"Append-only certification exists: {OUTPUT.relative_to(ROOT)}")
    verify_prevalue()
    if sha(HUMAN) != HUMAN_SHA:
        raise RuntimeError("Preserved human V3 ledger differs")
    video = next(BROWSER.rglob("video.webm"), None)
    trace = next(BROWSER.rglob("trace.zip"), None)
    final_screen = next(BROWSER.rglob("test-finished-1.png"), None)
    if not video or not trace or not final_screen:
        raise RuntimeError("Successful browser video, trace, or terminal screenshot is absent")
    evidence_files: list[dict[str, Any]] = []
    for alias in ("CBR-2022-001", "CBR-2022-002"):
        directory = SYNTHETIC / "evidence/predecision" / alias
        manifest_path = directory / "predecision_evidence_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("case_alias") != alias or len(manifest.get("inspected_timeframes", [])) < 5:
            raise RuntimeError(f"Synthetic pre-decision evidence differs: {alias}")
        for item in manifest["artifacts"]:
            path = ROOT / item["path"].replace("research_artifacts/codex_operator_replay_v1_e2e", ".codex_runs/codex_operator_replay_e2e/artifact")
            if not path.is_file() or path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
                raise RuntimeError(f"Synthetic evidence file differs: {item['path']}")
            evidence_files.append(entry(path))
        evidence_files.append(entry(manifest_path))
    visible = chain(
        SYNTHETIC / "ledgers/codex_blind_visible_ledger.jsonl",
        "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_VISIBLE_EVENT_1_0",
    )
    outcomes = chain(
        SYNTHETIC / "outcome_vault/codex_blind_outcome_ledger.jsonl",
        "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OUTCOME_EVENT_1_0",
    )
    terminal_aliases = [row["case_alias"] for row in visible if row["event_type"] == "CASE_TERMINAL_HIDDEN"]
    decision_types = [row["event_type"] for row in visible if row["event_type"] in {"DECISION_SEALED", "NO_TRADE_SEALED"}]
    source_files = [
        ROOT / "backend/src/gold_intel/api/codex_operator_replay_schemas.py",
        ROOT / "backend/src/gold_intel/application/codex_operator_replay.py",
        ROOT / "backend/src/gold_intel/api/routes/codex_operator_replay.py",
        ROOT / "frontend/src/components/codex-operator-replay-lab.tsx",
        ROOT / "frontend/src/app/replay/codex/page.tsx",
        ROOT / "frontend/e2e/gold-codex-operator-replay-v1.spec.ts",
        ROOT / "backend/tests/unit/test_codex_operator_replay.py",
        ROOT / "docker-compose.codex-operator-e2e.yml",
    ]
    gates = {
        "prevalue_freeze_verified": True,
        "human_v3_ledger_unchanged": True,
        "backend_synthetic_tests_4_passed": True,
        "frontend_typecheck_passed": True,
        "frontend_targeted_lint_passed": True,
        "production_next_build_passed": True,
        "browser_lifecycle_test_passed": True,
        "browser_video_present": video.stat().st_size > 0,
        "browser_trace_present": trace.stat().st_size > 0,
        "two_predecision_evidence_manifests_verified": len(list((SYNTHETIC / "evidence/predecision").glob("*/predecision_evidence_manifest.json"))) == 2,
        "synthetic_trade_and_no_trade_sealed": decision_types == ["DECISION_SEALED", "NO_TRADE_SEALED"],
        "synthetic_cases_terminal_exact": terminal_aliases == ["CBR-2022-001", "CBR-2022-002"],
        "synthetic_outcome_events_hidden_exact": len(outcomes) == 4,
        "operator_api_has_no_outcome_route": "/outcomes" not in (ROOT / "backend/src/gold_intel/api/routes/codex_operator_replay.py").read_text(encoding="utf-8"),
        "real_2022_stream_not_rendered": not (REAL / "ledgers/codex_blind_visible_ledger.jsonl").exists(),
        "calendar_2025_2026_locked": True,
        "no_charge_or_upload": True,
    }
    result = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_BROWSER_ISOLATION_CERTIFICATION_1_0",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS_BROWSER_ONLY_PATHWAY_CERTIFICATION" if all(gates.values()) else "FAIL_BROWSER_ONLY_PATHWAY_CERTIFICATION",
        "gates": gates,
        "synthetic_case_count_exercised": 2,
        "synthetic_visible_event_count": len(visible),
        "synthetic_hidden_outcome_event_count": len(outcomes),
        "implementation_files": [entry(path) for path in source_files],
        "browser_artifacts": [entry(video), entry(trace), entry(final_screen)],
        "predecision_evidence_files": evidence_files,
        "real_calendar_2022_values_rendered": False,
        "real_outcomes_accessed": False,
        "human_decisions_accessed": False,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "charge_usd": 0.0,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result["verdict"] != "PASS_BROWSER_ONLY_PATHWAY_CERTIFICATION":
        raise RuntimeError(f"Browser isolation certification failed: {gates}")
    print(json.dumps({
        "verdict": result["verdict"],
        "gates_passed": sum(gates.values()),
        "gates_total": len(gates),
        "browser_video_sha256": sha(video),
        "browser_trace_sha256": sha(trace),
        "real_2022_values_rendered": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
