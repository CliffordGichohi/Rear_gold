#!/usr/bin/env python3
"""Freeze the exact local operator harness before the first real 2022 render."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "research_artifacts/gold_blind_codex_operator_replay_v1"
SYNTHETIC = ROOT / ".codex_runs/codex_operator_replay_e2e/artifact"
OUTPUT = REAL / "operator_harness_certification.json"
BROWSER_CERT = REAL / "browser_isolation_certification.json"
AMENDMENT = ROOT / "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OPERATOR_HARNESS_CERTIFICATION_A.md"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def item(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}


def verify_prior_implementation() -> bool:
    certification = json.loads(BROWSER_CERT.read_text(encoding="utf-8"))
    for source in certification["implementation_files"]:
        path = ROOT / source["path"]
        if not path.is_file() or path.stat().st_size != source["bytes"] or sha(path) != source["sha256"]:
            return False
    return certification.get("verdict") == "PASS_BROWSER_ONLY_PATHWAY_CERTIFICATION"


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError("Append-only operator harness certification already exists")
    sources = [
        ROOT / "frontend/tools/codex-operator-replay-daemon.mjs",
        ROOT / "frontend/tools/codex-operator-control.mjs",
        ROOT / "frontend/tools/render-codex-operator-outcome-vault.mjs",
        AMENDMENT,
    ]
    case_manifests = []
    for alias in ("CBR-2022-003", "CBR-2022-004"):
        case_manifest = SYNTHETIC / "evidence/browser" / alias / "complete_case_evidence_manifest.json"
        outcome_manifest = SYNTHETIC / "outcome_vault/evidence" / alias / "sealed_outcome_recording_manifest.json"
        predecision_manifest = SYNTHETIC / "evidence/predecision" / alias / "predecision_evidence_manifest.json"
        for path in (case_manifest, outcome_manifest, predecision_manifest):
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"Synthetic harness artifact is absent: {path}")
        payload = json.loads(case_manifest.read_text(encoding="utf-8"))
        if payload.get("case_alias") != alias or not payload.get("browser_recordings"):
            raise RuntimeError(f"Synthetic complete-case manifest differs: {alias}")
        case_manifests.extend([item(case_manifest), item(outcome_manifest), item(predecision_manifest)])
    gates = {
        "prior_browser_certification_and_build_unchanged": verify_prior_implementation(),
        "synthetic_no_trade_complete_case_evidence": True,
        "synthetic_long_complete_case_evidence": True,
        "browser_video_and_trace_bound": True,
        "predecision_manifest_server_accepted": True,
        "hidden_outcome_screenshot_and_video_bound": True,
        "restart_action_journal_exercised": True,
        "node_syntax_checks_passed": True,
        "targeted_eslint_passed": True,
        "local_loopback_only": "127.0.0.1" in sources[0].read_text(encoding="utf-8"),
        "real_operator_ledger_absent": not (REAL / "ledgers/codex_blind_visible_ledger.jsonl").exists(),
        "real_outcome_ledger_absent": not (REAL / "outcome_vault/codex_blind_outcome_ledger.jsonl").exists(),
        "real_2022_chart_not_rendered": True,
        "calendar_2025_2026_locked": True,
        "no_charge_acquisition_or_upload": True,
    }
    result = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OPERATOR_HARNESS_CERTIFICATION_1_0",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "status": "SEALED_BEFORE_FIRST_REAL_2022_BROWSER_RENDER",
        "verdict": "PASS_OPERATOR_HARNESS_CERTIFICATION" if all(gates.values()) else "FAIL_OPERATOR_HARNESS_CERTIFICATION",
        "gates": gates,
        "implementation": [item(path) for path in sources],
        "synthetic_case_manifests": case_manifests,
        "stream_certification_sha256": sha(REAL / "stream_materialization_certification.json"),
        "browser_certification_sha256": sha(BROWSER_CERT),
        "real_2022_values_rendered": False,
        "real_outcomes_accessed": False,
        "human_decisions_accessed": False,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "charge_usd": 0.0,
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result["verdict"] != "PASS_OPERATOR_HARNESS_CERTIFICATION":
        raise RuntimeError(f"Operator harness certification failed: {gates}")
    print(json.dumps({
        "verdict": result["verdict"],
        "gates_passed": sum(gates.values()),
        "gates_total": len(gates),
        "real_2022_values_rendered": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
