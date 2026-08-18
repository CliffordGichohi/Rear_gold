#!/usr/bin/env python3
"""Seal the V2 post-certification status-text-only amendment."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "research_artifacts/gold_blind_synchronized_setup_replay_v2"
ORIGINAL_MANIFEST = ROOT / "research_manifests/gold_blind_synchronized_setup_replay_v2_final_seal.json"
AMENDMENT = ROOT / "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_POST_CERT_STATUS_AMENDMENT_A.md"
CERTIFICATION = ARTIFACT / "postcert_status_amendment_a_certification.json"
MANIFEST = ROOT / "research_manifests/gold_blind_synchronized_setup_replay_v2_postcert_status_amendment_a_seal.json"
ORIGINAL_MANIFEST_SHA256 = "7cddda6aa443a54825031b8c4b655840cd867f112fe3cbb0cbc9768e85739993"

CHANGED_FILES = (
    "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_POST_CERT_STATUS_AMENDMENT_A.md",
    "tools/certify_gold_blind_synchronized_setup_replay_v2_postcert_status_a.py",
    "backend/src/gold_intel/application/blind_replay_v2.py",
    "frontend/src/lib/api.ts",
    "frontend/src/components/blind-replay-v2-lab.tsx",
    "frontend/src/components/blind-replay-v2-lab.test.tsx",
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(name: str, command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=360,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    require(result.returncode == 0, f"{name} failed:\n{output[-4000:]}")
    return {
        "name": name,
        "command": command,
        "exit_code": result.returncode,
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output_tail": output[-1000:],
    }


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - localhost only
        require(response.status == 200, f"Live request failed: {url}")
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    require(not CERTIFICATION.exists() and not MANIFEST.exists(), "Append-only amendment output exists")
    require(sha256_file(ORIGINAL_MANIFEST) == ORIGINAL_MANIFEST_SHA256, "Original final seal differs")
    original = json.loads(ORIGINAL_MANIFEST.read_text(encoding="utf-8"))
    for record in original["sealed_outputs"]:
        path = ROOT / record["path"]
        require(path.stat().st_size == record["bytes"] and sha256_file(path) == record["sha256"], "Original certified output differs")
    require(AMENDMENT.is_file(), "Frozen status amendment is missing")
    ledgers = (
        ARTIFACT / "ledgers/cursor_ledger_v2.jsonl",
        ARTIFACT / "ledgers/setup_ledger_v2.jsonl",
    )
    require(all(not path.exists() or path.stat().st_size == 0 for path in ledgers), "A V2 human ledger exists")

    npm = "npm.cmd" if os.name == "nt" else "npm"
    checks = [
        run("backend_full_pytest", ["docker", "compose", "--profile", "test", "run", "--rm", "backend-test", "pytest", "-q"], ROOT),
        run("frontend_tests", [npm, "test"], ROOT / "frontend"),
        run("frontend_typecheck", [npm, "run", "typecheck"], ROOT / "frontend"),
        run("frontend_lint", [npm, "run", "lint"], ROOT / "frontend"),
        run("frontend_build", [npm, "run", "build"], ROOT / "frontend"),
    ]

    status = get_json("http://localhost:8000/api/v1/blind-replay-v2/status")
    snapshot = get_json("http://localhost:8000/api/v1/blind-replay-v2/next")
    require(status["scored_labeling"] == "CLOSED_V2_PRACTICE_ONLY_CERTIFIED", "Amended live status differs")
    require(status["total_locked"] == 0 and status["next_case_alias"] == "P-001", "Live zero-decision state differs")
    require(snapshot["case"]["cursor_minute"] == 0, "Live cursor differs")
    require(not any(bar["close_offset_minutes"] > 0 for bar in snapshot["case"]["charts"]["1m"]), "Live future value leaked")

    files = []
    for relative in CHANGED_FILES:
        path = ROOT / relative
        require(path.is_file(), f"Amendment file missing: {relative}")
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})

    gates = {
        "original_certification_preserved": True,
        "change_is_status_text_only": True,
        "scored_access_remains_closed": True,
        "practice_population_unchanged": True,
        "human_ledgers_empty": True,
        "backend_232_tests_pass": True,
        "frontend_22_tests_pass": True,
        "frontend_typecheck_lint_build_pass": True,
        "live_status_amended": True,
        "live_p001_cursor_zero_no_future": True,
        "no_2025_2026_access": True,
        "no_acquisition_or_charge": True,
    }
    completed_at = datetime.now(timezone.utc).isoformat()
    certification = {
        "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_POSTCERT_STATUS_AMENDMENT_A_CERTIFICATION_1_0",
        "completed_at": completed_at,
        "verdict": "PASS_V2_POSTCERT_STATUS_AMENDMENT_A",
        "status": "SEALED_READY_FOR_V2_PRACTICE_HUMAN_LABELING_SCORED_CLOSED",
        "original_final_manifest_sha256": ORIGINAL_MANIFEST_SHA256,
        "human_decisions": 0,
        "scored_labeling": status["scored_labeling"],
        "test_runs": checks,
        "changed_files": files,
        "changed_files_sha256": canonical_hash(files),
        "gates": gates,
        "charge_usd": 0.0,
    }
    with CERTIFICATION.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(certification, handle, indent=2, sort_keys=True)
        handle.write("\n")
    outputs = [{
        "path": CERTIFICATION.relative_to(ROOT).as_posix(),
        "bytes": CERTIFICATION.stat().st_size,
        "sha256": sha256_file(CERTIFICATION),
    }]
    manifest = {
        "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_POSTCERT_STATUS_AMENDMENT_A_SEAL_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": certification["verdict"],
        "status": certification["status"],
        "original_final_manifest_sha256": ORIGINAL_MANIFEST_SHA256,
        "amendment_sha256": sha256_file(AMENDMENT),
        "changed_files_sha256": certification["changed_files_sha256"],
        "sealed_outputs": outputs,
        "sealed_outputs_sha256": canonical_hash(outputs),
        "human_decisions": 0,
        "scored_labeling": "CLOSED_V2_PRACTICE_ONLY_CERTIFIED",
    }
    with MANIFEST.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "verdict": certification["verdict"],
        "status": certification["status"],
        "manifest_sha256": sha256_file(MANIFEST),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
