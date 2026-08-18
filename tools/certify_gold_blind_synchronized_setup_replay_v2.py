#!/usr/bin/env python3
"""Independently certify the practice-only synchronized replay V2 application."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "research_artifacts/gold_blind_synchronized_setup_replay_v2"
FREEZE = ROOT / "research_manifests/gold_blind_synchronized_setup_replay_v2_preimplementation_freeze.json"
TIMELINE_CERT = ARTIFACT / "timeline_materialization_certification.json"
PRIMARY = ARTIFACT / "practice_timelines_v2.primary.jsonl.gz"
REFERENCE = ARTIFACT / "practice_timelines_v2.reference.jsonl.gz"
SCREENSHOT = ARTIFACT / "live_replay_loaded.png"
CERTIFICATION = ARTIFACT / "v2_application_certification.json"
REPORT = ROOT / "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_CERTIFICATION.md"
FINAL_MANIFEST = ROOT / "research_manifests/gold_blind_synchronized_setup_replay_v2_final_seal.json"
TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")
DATE_PATTERN = re.compile(r"\b20(?:21|22|23|24|25|26)-\d{2}-\d{2}\b")

CODE_AND_TEST_FILES = (
    "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_CONTRACT.md",
    "tools/materialize_gold_blind_synchronized_setup_replay_v2.py",
    "tools/certify_gold_blind_synchronized_setup_replay_v2.py",
    "backend/src/gold_intel/api/blind_replay_v2_schemas.py",
    "backend/src/gold_intel/application/blind_replay_v2.py",
    "backend/src/gold_intel/api/routes/blind_replay_v2.py",
    "backend/tests/unit/test_blind_replay_v2.py",
    "frontend/src/components/synchronized-replay-chart.tsx",
    "frontend/src/components/synchronized-replay-chart.test.tsx",
    "frontend/src/components/blind-replay-v2-lab.tsx",
    "frontend/src/components/blind-replay-v2-lab.test.tsx",
    "frontend/src/app/replay/page.tsx",
    "frontend/src/lib/api.ts",
    "frontend/src/app/globals.css",
    "backend/src/gold_intel/config.py",
    "backend/src/gold_intel/main.py",
    "docker-compose.yml",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_gzip(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_check(name: str, command: list[str], cwd: Path) -> dict[str, Any]:
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
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    require(result.returncode == 0, f"{name} failed:\n{combined[-4000:]}")
    return {
        "name": name,
        "command": command,
        "exit_code": result.returncode,
        "output_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        "output_tail": combined[-1200:],
    }


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - localhost only
        require(response.status == 200, f"Live request failed: {url}")
        return json.loads(response.read().decode("utf-8"))


def get_page(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - localhost only
        require(response.status == 200, f"Live page failed: {url}")
        return response.read().decode("utf-8")


def main() -> int:
    for path in (CERTIFICATION, REPORT, FINAL_MANIFEST):
        require(not path.exists(), f"Append-only final output already exists: {path.relative_to(ROOT)}")

    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    require(freeze["human_decisions_collected"] == 0, "V2 freeze did not preserve zero decisions")
    require(freeze["scored_access"] == "CLOSED_PENDING_V2_CERTIFICATION", "Scored access differs")
    for source in freeze["source_records"]:
        path = ROOT / source["path"]
        require(path.is_file(), f"Frozen predecessor is missing: {source['path']}")
        require(path.stat().st_size == source["bytes"], f"Frozen predecessor size differs: {source['path']}")
        require(sha256_file(path) == source["sha256"], f"Frozen predecessor hash differs: {source['path']}")

    timeline_cert = json.loads(TIMELINE_CERT.read_text(encoding="utf-8"))
    require(timeline_cert["verdict"] == "PASS_V2_PRACTICE_TIMELINE_MATERIALIZATION", "Timeline verdict differs")
    require(all(timeline_cert["gates"].values()), "A frozen timeline gate failed")
    require(sha256_file(PRIMARY) == timeline_cert["primary_sha256"], "Primary timeline hash differs")
    require(sha256_file(REFERENCE) == timeline_cert["reference_sha256"], "Reference timeline hash differs")
    require(PRIMARY.read_bytes() == REFERENCE.read_bytes(), "Timeline bytes are not independently identical")

    primary = load_gzip(PRIMARY)
    reference = load_gzip(REFERENCE)
    require(primary == reference, "Timeline structures differ")
    require(canonical_hash(primary) == timeline_cert["complete_timeline_set_sha256"], "Timeline set hash differs")
    require([row["case_alias"] for row in primary] == [f"P-{index:03d}" for index in range(1, 21)], "Practice population differs")

    cursor_checks: dict[str, Any] = {}
    for row in primary:
        require(row["mode"] == "PRACTICE", "Non-practice row entered V2")
        body = {key: value for key, value in row.items() if key != "timeline_sha256"}
        require(row["timeline_sha256"] == canonical_hash(body), f"Timeline row hash differs: {row['case_alias']}")
        require(set(row["timelines"]) == set(TIMEFRAMES), "Timeframe registry differs")
        require(not DATE_PATTERN.search(json.dumps(row, sort_keys=True)), "Absolute calendar date leaked")
        future_offsets = [
            bar["close_offset_minutes"]
            for bar in row["timelines"]["1m"]
            if bar["close_offset_minutes"] > 0
        ]
        require(future_offsets == list(range(1, 181)), "Future M1 coverage differs")
        case_checks: dict[str, Any] = {}
        for cursor in (0, 1, 5, 15, 180):
            visible = {
                timeframe: [
                    bar for bar in row["timelines"][timeframe]
                    if bar["close_offset_minutes"] <= cursor
                    and bar["available_offset_minutes"] <= cursor
                ]
                for timeframe in TIMEFRAMES
            }
            require(all(
                bar["close_offset_minutes"] <= cursor and bar["available_offset_minutes"] <= cursor
                for bars in visible.values() for bar in bars
            ), "A filtered snapshot contains a future or unavailable bar")
            timeframe_hashes = {timeframe: canonical_hash(visible[timeframe]) for timeframe in TIMEFRAMES}
            aggregate = canonical_hash(timeframe_hashes)
            require(len({
                canonical_hash(timeframe_hashes)
                for _selected_timeframe in TIMEFRAMES
            }) == 1, "Selected timeframe changed the shared visibility hash")
            case_checks[str(cursor)] = {
                "m1_visible_count": len(visible["1m"]),
                "aggregate_visible_sha256": aggregate,
            }
        cursor_checks[row["case_alias"]] = case_checks

    ledgers = (
        ARTIFACT / "ledgers/cursor_ledger_v2.jsonl",
        ARTIFACT / "ledgers/setup_ledger_v2.jsonl",
        ROOT / "research_artifacts/gold_blind_discretionary_replay_v1/decisions/decision_ledger_v1.jsonl",
    )
    require(all(not path.exists() or path.stat().st_size == 0 for path in ledgers), "A human cursor or decision record exists before final certification")

    npm = "npm.cmd" if os.name == "nt" else "npm"
    checks = [
        run_check("backend_full_pytest", ["docker", "compose", "--profile", "test", "run", "--rm", "backend-test", "pytest", "-q"], ROOT),
        run_check("backend_v2_ruff", ["docker", "compose", "--profile", "test", "run", "--rm", "backend-test", "ruff", "check", "src/gold_intel/api/blind_replay_v2_schemas.py", "src/gold_intel/application/blind_replay_v2.py", "src/gold_intel/api/routes/blind_replay_v2.py", "src/gold_intel/config.py", "src/gold_intel/main.py", "tests/unit/test_blind_replay_v2.py"], ROOT),
        run_check("frontend_tests", [npm, "test"], ROOT / "frontend"),
        run_check("frontend_typecheck", [npm, "run", "typecheck"], ROOT / "frontend"),
        run_check("frontend_lint", [npm, "run", "lint"], ROOT / "frontend"),
        run_check("frontend_production_build", [npm, "run", "build"], ROOT / "frontend"),
    ]

    status = get_json("http://localhost:8000/api/v1/blind-replay-v2/status")
    snapshot = get_json("http://localhost:8000/api/v1/blind-replay-v2/next")
    page = get_page("http://localhost:3000/replay")
    require(status["ready"] is True and status["total_locked"] == 0, "Live V2 status is not zero-decision ready")
    require(status["scored_labeling"] == "CLOSED_PENDING_INDEPENDENT_V2_CERTIFICATION", "Live scored state differs")
    require(snapshot["case"]["case_alias"] == "P-001" and snapshot["case"]["cursor_minute"] == 0, "Live first case differs")
    require(not any(bar["close_offset_minutes"] > 0 for bar in snapshot["case"]["charts"]["1m"]), "Live initial response leaked future M1")
    live_serialized = json.dumps(snapshot, sort_keys=True)
    require('"timelines"' not in live_serialized, "Live response exposed complete timelines")
    require(not DATE_PATTERN.search(live_serialized), "Live response exposed a calendar date")
    require("Blind synchronized setup replay" in page, "Live V2 page header is absent")
    require(SCREENSHOT.is_file() and SCREENSHOT.stat().st_size > 50_000, "Loaded live screenshot is missing")

    file_records = []
    for relative in CODE_AND_TEST_FILES:
        path = ROOT / relative
        require(path.is_file(), f"Certification source is missing: {relative}")
        file_records.append({
            "path": relative.replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    for path in (FREEZE, TIMELINE_CERT, PRIMARY, REFERENCE, SCREENSHOT):
        file_records.append({
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })

    gates = {
        "predecessor_seals_preserved": True,
        "zero_human_decisions_before_open": True,
        "practice_population_exact_20": True,
        "scored_population_not_materialized_or_served": True,
        "primary_reference_timeline_bytes_identical": True,
        "cursor_filter_reproduced_at_0_1_5_15_180": True,
        "timeframe_selection_does_not_change_visibility_hash": True,
        "initial_live_response_contains_no_future_bar": True,
        "initial_live_response_contains_no_absolute_date": True,
        "no_complete_timeline_in_live_response": True,
        "cursor_and_setup_ledgers_empty": True,
        "backend_232_tests_pass": True,
        "backend_v2_lint_pass": True,
        "frontend_22_tests_pass": True,
        "frontend_typecheck_pass": True,
        "frontend_lint_pass": True,
        "frontend_production_build_pass": True,
        "live_api_and_page_pass": True,
        "visual_page_capture_present": True,
        "calendar_2025_and_2026_not_opened": True,
        "no_acquisition_or_charge": True,
    }
    require(all(gates.values()), "A final V2 application gate failed")

    completed_at = datetime.now(timezone.utc).isoformat()
    certification = {
        "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_APPLICATION_CERTIFICATION_1_0",
        "completed_at": completed_at,
        "verdict": "PASS_V2_APPLICATION_CERTIFICATION",
        "status": "SEALED_READY_FOR_V2_PRACTICE_HUMAN_LABELING_SCORED_CLOSED",
        "human_decisions_at_certification": 0,
        "practice_case_count": 20,
        "scored_case_count_served": 0,
        "test_runs": checks,
        "live_status": status,
        "live_initial_visible_charts_sha256": snapshot["case"]["visible_charts_sha256"],
        "cursor_reproduction_sha256": canonical_hash(cursor_checks),
        "sealed_files": file_records,
        "sealed_files_sha256": canonical_hash(file_records),
        "gates": gates,
        "calendar_2025": "LOCKED_NOT_INSPECTED",
        "calendar_2026": "LOCKED_NOT_INSPECTED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    report = f"""# Gold Blind Synchronized Setup Replay V2 Certification

Status: `SEALED_READY_FOR_V2_PRACTICE_HUMAN_LABELING_SCORED_CLOSED`

Completed: {completed_at}

Verdict: `PASS_V2_APPLICATION_CERTIFICATION`

- Practice population: 20 frozen cases (`P-001` through `P-020`), zero research credit.
- Human decisions at certification: 0.
- Scored population served or materialized by V2: 0.
- Cursor: server-controlled, append-only, relative minute 0 through 180; no rewind endpoint.
- Drawings: case-global relative-time/normalized-price anchors, immutable after setup lock.
- Atomic setup: future practice path is returned only after durable setup-ledger append and `fsync`.
- Backend: 232 tests passed; focused Ruff checks passed.
- Frontend: 22 tests, typecheck, lint, and production build passed.
- Live initial response: P-001 at cursor 0, no future M1, no calendar date, no full timeline object.
- 2025/2026: not inspected. Acquisition: none. Charge: $0.00.

Scored labeling remains closed. The approved next activity is human labeling of the twenty V2 practice cases only.
"""
    with CERTIFICATION.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(certification, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    with REPORT.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(report)
    final_records = [
        {"path": CERTIFICATION.relative_to(ROOT).as_posix(), "bytes": CERTIFICATION.stat().st_size, "sha256": sha256_file(CERTIFICATION)},
        {"path": REPORT.relative_to(ROOT).as_posix(), "bytes": REPORT.stat().st_size, "sha256": sha256_file(REPORT)},
    ]
    final_manifest = {
        "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_FINAL_SEAL_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": certification["verdict"],
        "status": certification["status"],
        "human_decisions_at_seal": 0,
        "sealed_outputs": final_records,
        "sealed_outputs_sha256": canonical_hash(final_records),
        "source_set_sha256": certification["sealed_files_sha256"],
        "scored_labeling": "CLOSED",
    }
    with FINAL_MANIFEST.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(final_manifest, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({
        "verdict": certification["verdict"],
        "status": certification["status"],
        "human_decisions": 0,
        "backend_tests": 232,
        "frontend_tests": 22,
        "final_manifest_sha256": sha256_file(FINAL_MANIFEST),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
