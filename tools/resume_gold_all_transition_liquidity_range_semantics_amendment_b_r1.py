#!/usr/bin/env python3
"""Resume Amendment B after interruption, reusing its sealed primary payload."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_all_transition_auction_scanner_semantic_review_v1 as base  # noqa: E402
import run_gold_all_transition_liquidity_range_semantics_amendment_b as b  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


AMENDMENT = ROOT / "GOLD_ALL_TRANSITION_AUCTION_SCANNER_LIQUIDITY_RANGE_AMENDMENT_B_ENGINEERING_RESUME_R1.md"
RUNNER = Path(__file__).resolve()
RESUME_FREEZE = b.OUT / "liquidity_range_amendment_b_resume_r1_freeze.json"


def verify_primary(frozen: dict[str, Any]) -> dict[str, Any]:
    b.require(b.PRIMARY.is_file(), "Complete primary overlay is absent")
    primary = b.load_json(b.PRIMARY)
    b.require(primary["side"] == "primary", "Primary side label differs")
    b.require(len(primary["overlays"]) == 729, "Primary overlay count differs")
    b.require(
        primary["original_events_sha256"] == frozen["predecessors"]["original_events_sha256"],
        "Primary predecessor event hash differs",
    )
    b.require(canonical_hash(primary["overlays"]) == primary["overlays_sha256"], "Primary overlay hash differs")
    original = b.load_json(base.PRIMARY)
    identities = [item["event_identity"] for item in original["events"]]
    b.require(canonical_hash(identities) == primary["event_identities_sha256"], "Primary identities differ")
    b.require(
        [item["event_identity"] for item in primary["overlays"]] == identities,
        "Primary overlay order differs",
    )
    return primary


def freeze() -> None:
    b.require(not RESUME_FREEZE.exists(), "Resume freeze exists")
    for path in (b.REFERENCE, b.ATLAS, b.CERTIFICATION, b.SEAL, b.REPORT):
        b.require(not path.exists(), f"Post-primary output already exists: {path}")
    b.require(not b.CHART_ROOT.exists(), "Post-primary chart root already exists")
    frozen = b.verify_freeze()
    primary = verify_primary(frozen)
    payload: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_LIQUIDITY_RANGE_AMENDMENT_B_RESUME_R1_FREEZE_1_0",
        "sealed_at": b.now(),
        "status": "SEALED_BEFORE_REFERENCE_RESTART_FROM_COMPLETE_PRIMARY",
        "files": [b.file_record(AMENDMENT), b.file_record(RUNNER)],
        "original_freeze_sha256": frozen["freeze_sha256"],
        "complete_primary": b.file_record(b.PRIMARY),
        "complete_primary_overlays_sha256": primary["overlays_sha256"],
        "interrupted_checkpoint": "REFERENCE_050_OF_729_EMITTED_NO_REFERENCE_ARTIFACT",
        "semantic_rules_changed": False,
        "primary_recomputed": False,
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    payload["resume_freeze_sha256"] = canonical_hash(payload)
    b.write_new_json(RESUME_FREEZE, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "primary_overlays": len(primary["overlays"]),
                "resume_freeze_sha256": payload["resume_freeze_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def verify_resume_freeze() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    b.require(RESUME_FREEZE.is_file(), "Resume freeze is absent")
    resumed = b.load_json(RESUME_FREEZE)
    submitted = str(resumed.pop("resume_freeze_sha256"))
    b.require(canonical_hash(resumed) == submitted, "Resume freeze differs")
    resumed["resume_freeze_sha256"] = submitted
    for record in resumed["files"]:
        b.verify_record(record)
    frozen = b.verify_freeze()
    b.require(frozen["freeze_sha256"] == resumed["original_freeze_sha256"], "Original freeze changed")
    primary = verify_primary(frozen)
    b.require(b.file_record(b.PRIMARY) == resumed["complete_primary"], "Complete primary file changed")
    b.require(
        primary["overlays_sha256"] == resumed["complete_primary_overlays_sha256"],
        "Complete primary overlay hash changed",
    )
    return resumed, frozen, primary


def render_primary_examples(
    frozen: dict[str, Any], primary: dict[str, Any]
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    original = b.load_json(base.PRIMARY)
    event_map = {item["event_identity"]: item for item in original["events"]}
    overlay_map = {item["event_identity"]: item for item in primary["overlays"]}
    streams = source.load_streams("primary")
    charts: dict[str, bytes] = {}
    diagnostics: list[dict[str, Any]] = []
    for index, identity in enumerate(frozen["selected_example_identities"], start=1):
        event = event_map[identity]
        overlay = overlay_map[identity]
        payload, diagnostic = b.render_chart(streams[event["case_alias"]], event, overlay)
        charts[b.chart_filename(index, event)] = payload
        diagnostics.append(diagnostic)
        print(f"primary chart {index:02d}/24", flush=True)
    del streams
    gc.collect()
    return charts, diagnostics


def resume() -> None:
    resumed, frozen, primary = verify_resume_freeze()
    for path in (b.REFERENCE, b.ATLAS, b.CERTIFICATION, b.SEAL, b.REPORT):
        b.require(not path.exists(), f"Resume output exists: {path}")
    b.require(not b.CHART_ROOT.exists(), "Resume chart root exists")

    primary_charts, primary_diagnostics = render_primary_examples(frozen, primary)
    reference, reference_charts, reference_diagnostics = b.materialize_side("reference", frozen)
    b.write_new_json(b.REFERENCE, reference)
    b.require(primary["event_identities_sha256"] == reference["event_identities_sha256"], "Event identities differ")
    b.require(primary["overlays"] == reference["overlays"], "Primary/reference overlays differ")
    b.require(primary["overlays_sha256"] == reference["overlays_sha256"], "Overlay hashes differ")
    b.require(primary_charts.keys() == reference_charts.keys(), "Chart filename sets differ")
    b.require(all(primary_charts[name] == reference_charts[name] for name in primary_charts), "Chart bytes differ")
    b.require(primary_diagnostics == reference_diagnostics, "Chart diagnostics differ")

    summary_data = b.summary(primary["overlays"])
    b.require(summary_data["events"] == 729, "Overlay event count differs")
    b.require(summary_data["technical_unknown_pivot_classifications"] == 0, "Technical pivots unresolved")
    b.require(summary_data["unresolved_active_roles"] == 0, "Active roles unresolved")
    b.require(
        set(summary_data["broken_control_pivot_state"]) == {"CONSUMED"},
        "A structurally broken control pivot was not strictly consumed",
    )

    selected = list(frozen["selected_example_identities"])
    records: list[dict[str, Any]] = []
    names = sorted(primary_charts, key=lambda name: int(name.split("_", 1)[0]))
    for filename in names:
        payload = primary_charts[filename]
        path = b.CHART_ROOT / filename
        b._atomic_create(path, payload)
        records.append(
            {"filename": filename, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    original_events = b.load_json(base.PRIMARY)["events"]
    event_map = {item["event_identity"]: item for item in original_events}
    b.write_new_text(b.ATLAS, b.atlas_html(selected, event_map, records))

    unresolved = sum(
        len(frame["unresolved"])
        for item in primary_diagnostics
        for frame in item["timeframes"].values()
    )
    omitted = sum(
        len(frame["omitted"])
        for item in primary_diagnostics
        for frame in item["timeframes"].values()
    )
    b.require(unresolved == 0, f"Chart identities unresolved: {unresolved}")
    certification: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_LIQUIDITY_RANGE_AMENDMENT_B_CERTIFICATION_R1_1_0",
        "completed_at": b.now(),
        "verdict": "PASS_CORRECTED_LIQUIDITY_RANGE_SEMANTICS_AFTER_ENGINEERING_RESUME_STOP_FOR_USER_REVIEW",
        "freeze_sha256": frozen["freeze_sha256"],
        "resume_freeze_sha256": resumed["resume_freeze_sha256"],
        "interrupted_checkpoint_preserved": resumed["interrupted_checkpoint"],
        "ruleset": frozen["ruleset"],
        "original_event_count_unchanged": 729,
        "original_events_sha256": frozen["predecessors"]["original_events_sha256"],
        "selected_example_identities": selected,
        "selected_example_identities_sha256": frozen["selected_example_identities_sha256"],
        "primary_recomputed": False,
        "primary_reference_overlays_exact": True,
        "overlays_sha256": primary["overlays_sha256"],
        "summary": summary_data,
        "chart_records": records,
        "chart_diagnostics": primary_diagnostics,
        "chart_diagnostic_totals": {
            "unresolved_identities": unresolved,
            "omitted_pivots": omitted,
            "maximum_ray_fraction": max(item["maximum_ray_fraction"] for item in primary_diagnostics),
        },
        "chart_bytes_primary_reference_exact": True,
        "atlas": b.file_record(b.ATLAS),
        "semantic_rules_changed_during_resume": False,
        "original_events_changed": False,
        "outcomes_accessed": False,
        "performance_calculated": False,
        "execution_constructed": False,
        "february_17_28_opened": False,
        "july_2022_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    certification["certification_sha256"] = canonical_hash(certification)
    b.write_new_json(b.CERTIFICATION, certification)
    report = b.markdown(certification) + "\nThe primary pass was reused unchanged after the sealed R1 engineering resume.\n"
    b.write_new_text(b.REPORT, report)
    seal: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_LIQUIDITY_RANGE_AMENDMENT_B_SEAL_R1_1_0",
        "sealed_at": b.now(),
        "verdict": certification["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "original_freeze_sha256": frozen["freeze_sha256"],
        "resume_freeze_sha256": resumed["resume_freeze_sha256"],
        "files": [
            b.file_record(b.FREEZE),
            b.file_record(RESUME_FREEZE),
            b.file_record(b.PRIMARY),
            b.file_record(b.REFERENCE),
            b.file_record(b.ATLAS),
            b.file_record(b.CERTIFICATION),
            b.file_record(b.REPORT),
            *[b.file_record(b.CHART_ROOT / record["filename"]) for record in records],
        ],
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    b.write_new_json(b.SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "summary": summary_data,
                "chart_diagnostics": certification["chart_diagnostic_totals"],
                "atlas": b.ATLAS.relative_to(ROOT).as_posix(),
                "certification_sha256": certification["certification_sha256"],
                "seal_sha256": seal["seal_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "resume", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"resume", "all"}:
        resume()


if __name__ == "__main__":
    main()

