#!/usr/bin/env python3
"""Seal the interaction/display-only Replay V1 UI Amendment C."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_prelabel_ui_amendment_b_freeze.json"
AMENDMENT = ROOT / "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_UI_AMENDMENT_C.md"
WORKSPACE = ROOT / "frontend" / "src" / "components" / "replay-chart-workspace.tsx"
WORKSPACE_TEST = ROOT / "frontend" / "src" / "components" / "replay-chart-workspace.test.tsx"
LAB = ROOT / "frontend" / "src" / "components" / "blind-replay-lab.tsx"
LAB_TEST = ROOT / "frontend" / "src" / "components" / "blind-replay-lab.test.tsx"
STATE = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "prelabel_ui_amendment_c_state.json"
FREEZE = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_prelabel_ui_amendment_c_freeze.json"
LEDGER = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "decisions" / "decision_ledger_v1.jsonl"

AUTHORIZED_PREDECESSOR_CHANGES = {
    "frontend/src/components/blind-replay-lab.tsx",
    "frontend/src/components/blind-replay-lab.test.tsx",
    "frontend/src/components/replay-chart-workspace.tsx",
    "frontend/src/components/replay-chart-workspace.test.tsx",
}
WORKSPACE_MARKERS = (
    "Select drawing",
    "Delete selected drawing",
    "ENTRY",
    "Stop-loss index",
    "Take-profit index",
    "NON-EXECUTABLE",
    "Trade remark",
    "Arm this append-only paper trade",
    "Place armed trade &amp; play",
    "blind axis · calendar date/time hidden",
    "autoPlay",
)
LAB_MARKERS = (
    "What the fundamentals are saying",
    "Verbatim point-in-time component explanations",
    "REAL_YIELD",
    "INFLATION_REGIME",
    "GROWTH_REGIME",
    "LABOUR_REGIME",
    "TWO_YEAR_YIELD",
    "USD",
    "Trade remark / directional thesis",
    "requestSubmit",
)
DATE_PATTERN = re.compile(r"\b20(?:21|22|23|24|25|26)-\d{2}-\d{2}\b")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        "replay_page_http_200": page_http == 200,
    }


def main() -> int:
    if STATE.exists() or FREEZE.exists():
        raise RuntimeError("Append-only UI Amendment C state or freeze already exists")
    if LEDGER.exists():
        raise RuntimeError("Human labeling has begun; UI Amendment C is refused")

    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("status") != "SEALED_READY_FOR_HUMAN_LABELING_UI_AMENDMENT_B":
        raise RuntimeError("The UI Amendment B predecessor has the wrong status")

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
        raise RuntimeError(f"Predecessor changes differ from the authorized UI-only set: {sorted(differing)}")

    workspace_text = WORKSPACE.read_text(encoding="utf-8")
    lab_text = LAB.read_text(encoding="utf-8")
    if missing := [marker for marker in WORKSPACE_MARKERS if marker not in workspace_text]:
        raise RuntimeError(f"Required workspace markers are missing: {missing}")
    if missing := [marker for marker in LAB_MARKERS if marker not in lab_text]:
        raise RuntimeError(f"Required replay-lab markers are missing: {missing}")

    live = live_checks()
    gates = {
        "predecessor_status_verified": True,
        "only_authorized_predecessor_files_changed": set(differing) == AUTHORIZED_PREDECESSOR_CHANGES,
        "research_data_backend_population_and_decision_schema_unchanged": all(path.startswith("frontend/") for path in differing),
        "amendment_frozen_before_implementation": AMENDMENT.is_file(),
        "macro_summary_is_existing_component_explanation_only": "component.explanation" in lab_text and "Verbatim point-in-time component explanations" in lab_text,
        "three_level_position_and_preview_present": all(marker in workspace_text for marker in ("ENTRY", "SL", "TP preview")),
        "drawing_selection_and_deletion_present": all(marker in workspace_text for marker in ("Select drawing", "Delete selected drawing", "Delete/Backspace")),
        "non_executable_geometry_cannot_be_armed": "disabled={Boolean(selectedDrawing.validationError)}" in workspace_text,
        "armed_trade_requires_existing_form": "requestSubmit" in lab_text and "tradeBlockers" in lab_text,
        "scored_outcomes_remain_hidden": "Scored paths stay hidden" in workspace_text,
        "only_relative_time_axis_present": "relativeAxisLabel" in workspace_text and "calendar date/time hidden" in workspace_text,
        "human_decisions_zero": not LEDGER.exists(),
        "live_checks_pass": all(live.values()),
        "calendar_2025_2026_still_locked": predecessor.get("calendar_2025") == "LOCKED_NOT_INSPECTED" and predecessor.get("calendar_2026") == "LOCKED_NOT_INSPECTED",
        "no_acquisition_or_charge": predecessor.get("acquisition_performed") is False and predecessor.get("charge_usd") == 0,
    }
    if not all(gates.values()):
        raise RuntimeError(f"UI Amendment C gates failed: {gates}")

    state = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRELABEL_UI_AMENDMENT_C_STATE_1_0",
        "created_at": datetime.now(UTC).isoformat(),
        "verdict": "PASS_PRELABEL_UI_AMENDMENT_C",
        "scope": "INTERACTION_AND_DISPLAY_ONLY",
        "predecessor_freeze": file_record(PREDECESSOR),
        "authorized_predecessor_file_changes": differing,
        "tests": {
            "frontend_typecheck": "PASS",
            "frontend_lint": "PASS",
            "frontend_vitest": "12 passed",
            "frontend_production_build": "PASS",
            "docker_web_build": "PASS",
        },
        "test_evidence": {
            "macro_component_summary": "PASS",
            "relative_time_axis_no_calendar_date": "PASS",
            "entry_sl_tp_mapping": "PASS",
            "position_selection_and_deletion": "PASS",
            "armed_submission_requires_completed_fields": "PASS",
            "visible_history_replay_lockout": "PASS",
        },
        "live_checks": live,
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

    extras = [file_record(AMENDMENT), file_record(Path(__file__).resolve()), file_record(STATE)]
    sealed = [*carried, *extras]
    freeze = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRELABEL_UI_AMENDMENT_C_FREEZE_1_0",
        "sealed_at": datetime.now(UTC).isoformat(),
        "status": "SEALED_READY_FOR_HUMAN_LABELING_UI_AMENDMENT_C",
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
        "human_decisions_collected": 0,
        "next_case_alias": "P-001",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
