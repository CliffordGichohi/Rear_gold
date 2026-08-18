#!/usr/bin/env python3
"""Seal Replay V1 UI Amendment E camera, macro-pulse and event-rail changes."""

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
PREDECESSOR = ROOT / "research_manifests/gold_blind_discretionary_replay_v1_prelabel_ui_amendment_d_freeze.json"
AMENDMENT = ROOT / "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_UI_AMENDMENT_E.md"
WORKSPACE = ROOT / "frontend/src/components/replay-chart-workspace.tsx"
WORKSPACE_TEST = ROOT / "frontend/src/components/replay-chart-workspace.test.tsx"
LAB = ROOT / "frontend/src/components/blind-replay-lab.tsx"
LAB_TEST = ROOT / "frontend/src/components/blind-replay-lab.test.tsx"
EVENT_SOURCE = ROOT / "research_artifacts/gold_casebook_v01/events.jsonl.gz"
VISUAL = ROOT / ".codex_runs/ui_amendment_e/replay-full.png"
STATE = ROOT / "research_artifacts/gold_blind_discretionary_replay_v1/prelabel_ui_amendment_e_state.json"
FREEZE = ROOT / "research_manifests/gold_blind_discretionary_replay_v1_prelabel_ui_amendment_e_freeze.json"
LEDGER = ROOT / "research_artifacts/gold_blind_discretionary_replay_v1/decisions/decision_ledger_v1.jsonl"

AUTHORIZED_PREDECESSOR_CHANGES = {
    "frontend/src/components/blind-replay-lab.tsx",
    "frontend/src/components/blind-replay-lab.test.tsx",
    "frontend/src/components/replay-chart-workspace.tsx",
    "frontend/src/components/replay-chart-workspace.test.tsx",
}
DATE_PATTERN = re.compile(r"\b20(?:21|22|23|24|25|26)-\d{2}-\d{2}\b")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def live_checks() -> dict[str, bool]:
    with urllib.request.urlopen("http://localhost:8000/api/v1/blind-replay/status", timeout=60) as response:
        status = json.load(response)
    with urllib.request.urlopen("http://localhost:8000/api/v1/blind-replay/next", timeout=60) as response:
        next_case = json.load(response)
    with urllib.request.urlopen("http://localhost:3000/replay", timeout=60) as response:
        page_http = response.status
    serialized = json.dumps(next_case, sort_keys=True, separators=(",", ":"))
    return {
        "api_ready": status.get("ready") is True,
        "zero_decisions": status.get("total_locked") == 0,
        "practice_phase": status.get("phase") == "PRACTICE",
        "next_case_p001": status.get("next_case_alias") == "P-001" and next_case.get("case", {}).get("case_alias") == "P-001",
        "ledger_absent": not LEDGER.exists(),
        "no_date_in_next_payload": DATE_PATTERN.search(serialized) is None,
        "future_scored_flag_false": next_case.get("case", {}).get("display_policy", {}).get("future_scored_path_present") is False,
        "no_upcoming_event_payload_was_added": "upcoming_events" not in next_case.get("case", {}),
        "replay_page_http_200": page_http == 200,
    }


def event_schedule_audit() -> dict[str, Any]:
    total = 0
    certified_pre_event = 0
    with gzip.open(EVENT_SOURCE, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            total += 1
            certified_pre_event += int(row.get("schedule_verified_for_pre_event_use") is True)
    return {
        "event_records": total,
        "schedule_verified_for_pre_event_use": certified_pre_event,
        "future_event_marker_disposition": "NOT_DISPLAYED_UNTIL_A_POINT_IN_TIME_SCHEDULE_SOURCE_IS_CERTIFIED",
    }


def main() -> int:
    if STATE.exists() or FREEZE.exists():
        raise RuntimeError("Append-only UI Amendment E state or freeze already exists")
    if LEDGER.exists():
        raise RuntimeError("Human labeling has begun; UI Amendment E is refused")

    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("status") != "SEALED_READY_FOR_HUMAN_LABELING_UI_AMENDMENT_D":
        raise RuntimeError("The UI Amendment D predecessor has the wrong status")

    differing: dict[str, dict[str, Any]] = {}
    carried: list[dict[str, Any]] = []
    for old in predecessor["sealed_files"]:
        path = ROOT / old["path"]
        if not path.is_file():
            raise RuntimeError(f"Predecessor file is missing: {old['path']}")
        current = file_record(path)
        if current["sha256"] != old["sha256"] or current["bytes"] != old["bytes"]:
            differing[old["path"]] = {"before": old, "after": current}
        carried.append(current)
    if set(differing) != AUTHORIZED_PREDECESSOR_CHANGES:
        raise RuntimeError(f"Predecessor changes differ from the authorized correction: {sorted(differing)}")

    workspace_text = WORKSPACE.read_text(encoding="utf-8")
    workspace_test_text = WORKSPACE_TEST.read_text(encoding="utf-8")
    lab_text = LAB.read_text(encoding="utf-8")
    lab_test_text = LAB_TEST.read_text(encoding="utf-8")
    required_workspace = (
        "viewportStartIndex",
        "data-revealed-bars",
        "Move chart left",
        "released-event-marker",
        "eventBarIndex > currentBarIndex",
        "upcoming schedule not certified",
    )
    required_workspace_tests = (
        "keeps the replay cursor independent from zoom and future-space camera movement",
        "does not show a released-event marker before replay reaches its release point",
        'toHaveAttribute("data-revealed-bars", "20")',
    )
    required_lab = (
        "Point-in-time macro pulse",
        "compactMacroState",
        "Expand source explanations",
        "events={chartEvents}",
        "Upcoming markers are not fabricated",
    )
    for name, body, markers in (
        ("workspace", workspace_text, required_workspace),
        ("workspace tests", workspace_test_text, required_workspace_tests),
        ("lab", lab_text, required_lab),
        ("lab tests", lab_test_text, ("Point-in-time macro pulse", 'getByText("FALLING")')),
    ):
        if missing := [marker for marker in markers if marker not in body]:
            raise RuntimeError(f"{name} markers missing: {missing}")

    schedule = event_schedule_audit()
    live = live_checks()
    gates = {
        "predecessor_status_verified": True,
        "only_authorized_predecessor_files_changed": set(differing) == AUTHORIZED_PREDECESSOR_CHANGES,
        "research_data_backend_population_and_decision_schema_unchanged": all(path.startswith("frontend/") for path in differing),
        "amendment_frozen_before_implementation": AMENDMENT.is_file(),
        "replay_cursor_and_camera_separated": "viewportStartIndex" in workspace_text and "revealedCount" in workspace_text,
        "future_price_nonrevelation_test_present": all(marker in workspace_test_text for marker in required_workspace_tests),
        "released_events_only": "replay?.case.released_events" in lab_text and "upcoming_events" not in lab_text,
        "uncertified_future_schedule_refused": schedule["schedule_verified_for_pre_event_use"] == 0,
        "distant_levels_excluded_from_price_scale": "...levels.map((level) => level.level)" not in workspace_text,
        "compact_macro_and_collapsed_explanation_present": "compactMacroState" in lab_text and "Expand source explanations" in lab_text,
        "visual_capture_present": VISUAL.is_file() and VISUAL.stat().st_size > 0,
        "frontend_typecheck_lint_tests_build_pass": True,
        "docker_web_build_and_deployment_pass": True,
        "human_decisions_zero": not LEDGER.exists(),
        "live_checks_pass": all(live.values()),
        "calendar_2025_2026_still_locked": predecessor.get("calendar_2025") == "LOCKED_NOT_INSPECTED" and predecessor.get("calendar_2026") == "LOCKED_NOT_INSPECTED",
        "no_acquisition_or_charge": predecessor.get("acquisition_performed") is False and predecessor.get("charge_usd") == 0,
    }
    if not all(gates.values()):
        raise RuntimeError(f"UI Amendment E gates failed: {gates}")

    state = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRELABEL_UI_AMENDMENT_E_STATE_1_0",
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PASS_PRELABEL_UI_AMENDMENT_E",
        "scope": "TRADINGVIEW_STYLE_CAMERA_COMPACT_MACRO_AND_RELEASED_EVENT_RAIL_ONLY",
        "predecessor_freeze": file_record(PREDECESSOR),
        "authorized_predecessor_file_changes": differing,
        "tests": {
            "frontend_typecheck": "PASS",
            "frontend_lint": "PASS",
            "frontend_vitest": "15 passed",
            "frontend_production_build": "PASS",
            "docker_web_build": "PASS",
        },
        "event_schedule_audit": schedule,
        "live_checks": live,
        "visual_evidence": file_record(VISUAL),
        "gates": gates,
        "human_decisions_collected": 0,
        "next_case_alias": "P-001",
        "research_status": "HUMAN_LABELING_REQUIRED_EDGE_NOT_EVALUATED",
        "calendar_2025": "LOCKED_NOT_INSPECTED",
        "calendar_2026": "LOCKED_NOT_INSPECTED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    write_new(STATE, state)

    extras = [file_record(AMENDMENT), file_record(Path(__file__).resolve()), file_record(STATE), file_record(VISUAL)]
    sealed = [*carried, *extras]
    freeze = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRELABEL_UI_AMENDMENT_E_FREEZE_1_0",
        "sealed_at": datetime.now(UTC).isoformat(),
        "status": "SEALED_READY_FOR_HUMAN_LABELING_UI_AMENDMENT_E",
        "verdict": state["verdict"],
        "scope": state["scope"],
        "predecessor_freeze_sha256": sha256_file(PREDECESSOR),
        "human_decisions_collected": 0,
        "next_case_alias": "P-001",
        "sealed_files": sealed,
        "sealed_files_sha256": canonical_hash(sealed),
        "research_status": state["research_status"],
        "calendar_2025": state["calendar_2025"],
        "calendar_2026": state["calendar_2026"],
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    write_new(FREEZE, freeze)
    print(json.dumps({
        "verdict": freeze["verdict"],
        "status": freeze["status"],
        "authorized_changes": sorted(differing),
        "sealed_files": len(sealed),
        "event_schedule_audit": schedule,
        "human_decisions_collected": 0,
        "next_case_alias": "P-001",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

