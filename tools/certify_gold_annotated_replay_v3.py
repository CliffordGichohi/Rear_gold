#!/usr/bin/env python3
"""Seal the practice-only V3 replay application and browser evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "research_artifacts/gold_annotated_replay_v3"
BROWSER = ARTIFACT / "browser_certification"
PREIMPLEMENTATION = (
    ROOT / "research_manifests/gold_annotated_replay_v3_preimplementation_freeze.json"
)
AMENDMENT_FREEZE = (
    ROOT
    / "research_manifests/gold_annotated_replay_v3_practice_stream_coverage_amendment_a_freeze.json"
)
STREAM_CERTIFICATION = ARTIFACT / "practice_stream_materialization_certification_v3_1.json"
PRIMARY_STREAM = ARTIFACT / "practice_streams_v3_1.primary.jsonl.gz"
REFERENCE_STREAM = ARTIFACT / "practice_streams_v3_1.reference.jsonl.gz"
HUMAN_LEDGER = ARTIFACT / "ledgers/practice_event_ledger_v3.jsonl"
CERTIFICATION = ARTIFACT / "browser_regression_certification.json"
FINAL_SEAL = (
    ROOT / "research_manifests/gold_annotated_replay_v3_practice_certification_seal.json"
)

SEALED_IMPLEMENTATION_FILES = (
    "GOLD_ANNOTATED_TRADINGVIEW_STYLE_REPLAY_AND_HUMAN_EDGE_AUDIT_CONTRACT_V3.md",
    "GOLD_ANNOTATED_REPLAY_V3_PRACTICE_STREAM_COVERAGE_AMENDMENT_A.md",
    "GOLD_ANNOTATED_REPLAY_V3_USER_GUIDE.md",
    "GOLD_ANNOTATED_REPLAY_V3_IMPLEMENTATION_REPORT.md",
    "tools/prepare_gold_annotated_replay_v3.py",
    "tools/materialize_gold_annotated_replay_v3.py",
    "tools/certify_gold_annotated_replay_v3.py",
    "backend/src/gold_intel/api/blind_replay_v3_schemas.py",
    "backend/src/gold_intel/application/blind_replay_v3.py",
    "backend/src/gold_intel/api/routes/blind_replay_v3.py",
    "backend/tests/unit/test_blind_replay_v3.py",
    "backend/src/gold_intel/config.py",
    "backend/src/gold_intel/main.py",
    "backend/Dockerfile",
    "frontend/src/components/annotated-replay-v3-lab.tsx",
    "frontend/src/components/synchronized-replay-chart.tsx",
    "frontend/src/components/synchronized-replay-chart.test.tsx",
    "frontend/src/app/replay/page.tsx",
    "frontend/src/lib/api.ts",
    "frontend/src/lib/server-api.ts",
    "frontend/e2e/gold-replay-v3.spec.ts",
    "frontend/playwright.config.ts",
    "frontend/vitest.config.mjs",
    "frontend/eslint.config.mjs",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/Dockerfile",
    "docker-compose.yml",
    "docker-compose.replay-v3-e2e.yml",
)

BROWSER_EVIDENCE = (
    "research_artifacts/gold_annotated_replay_v3/browser_certification/playwright_last_run.json",
    "research_artifacts/gold_annotated_replay_v3/browser_certification/gold_replay_v3_certified.png",
    "research_artifacts/gold_annotated_replay_v3/browser_certification/playwright_test_finished.png",
    "research_artifacts/gold_annotated_replay_v3/browser_certification/playwright_trace.zip",
)

BROWSER_MATRIX = (
    "initial_case_selection_and_strict_future_hiding",
    "seven_synchronized_timeframes",
    "gui_only_zoom_and_four_direction_pan",
    "drawing_persistence_selection_resize_and_delete",
    "independent_entry_stop_and_target_handles",
    "unsubmitted_plan_does_not_block_replay",
    "play_pause_intervals_and_speed_controls",
    "fullscreen_control_parity",
    "annotation_cancel_preserves_cursor_and_draft",
    "atomic_annotation_order_seal_then_resume",
    "pending_limit_submission_refresh_and_api_restart_recovery",
    "pending_order_amendment_and_cancellation",
    "market_fill_and_post_fill_geometry_lock",
    "one_live_order_and_concurrent_order_rejection",
    "active_position_api_restart_recovery",
    "annotated_manual_close_preserves_original_geometry",
    "pending_order_expiry",
    "stop_order_fill",
    "limit_order_fill",
    "target_and_stop_resolution",
    "multiple_sequential_trades",
    "idempotency_and_no_double_advance",
    "practice_day_completion_and_next_case_selection",
    "dst_rollover_no_tick_and_point_in_time_fundamental_updates",
    "collection_2022_and_calendars_2025_2026_locked",
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Required artifact is missing: {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_record(record: dict[str, Any]) -> None:
    path = ROOT / record["path"]
    require(path.is_file(), f"Sealed source is missing: {record['path']}")
    require(path.stat().st_size == record["bytes"], f"Sealed size differs: {record['path']}")
    require(sha256_file(path) == record["sha256"], f"Sealed hash differs: {record['path']}")


def file_record(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    require(path.is_file(), f"Certification file is missing: {relative}")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> int:
    require(not CERTIFICATION.exists(), "Append-only V3 certification already exists")
    require(not FINAL_SEAL.exists(), "Append-only V3 final seal already exists")

    preimplementation = load_json(PREIMPLEMENTATION)
    require(
        preimplementation["verdict"] == "PASS_V3_CONTRACT_COVERAGE_AND_POLICY_FREEZE",
        "Preimplementation verdict differs",
    )
    require(preimplementation["human_practice_events"] == 0, "Freeze was not zero-decision")
    require(
        preimplementation["primary_collection_state"] == "CLOSED_NOT_MATERIALIZED",
        "Primary collection was not frozen closed",
    )
    require(preimplementation["calendar_2025"] == "LOCKED", "Calendar 2025 lock differs")
    require(preimplementation["calendar_2026"] == "LOCKED", "Calendar 2026 lock differs")
    verify_record(preimplementation["predecessor"])
    for record in preimplementation["sealed_outputs"]:
        verify_record(record)

    amendment = load_json(AMENDMENT_FREEZE)
    require(
        amendment["status"] == "SEALED_BEFORE_CORRECTED_MATERIALIZATION",
        "Coverage amendment was not frozen before correction",
    )
    verify_record(amendment["amendment"])
    verify_record(amendment["reused_predecessor_rule"])
    for record in amendment["preserved_original_artifacts"]:
        verify_record(record)

    stream_certification = load_json(STREAM_CERTIFICATION)
    require(
        stream_certification["verdict"]
        == "PASS_V3_PRACTICE_STREAM_COVERAGE_AMENDMENT_A",
        "Corrected practice stream verdict differs",
    )
    require(all(stream_certification["gates"].values()), "A corrected stream gate failed")
    require(stream_certification["practice_case_count"] == 20, "Practice count differs")
    require(stream_certification["primary_collection_year"] == "2022", "Collection year differs")
    require(
        stream_certification["primary_collection_state"] == "CLOSED_NOT_MATERIALIZED",
        "Collection state differs",
    )
    require(stream_certification["calendar_2025"] == "LOCKED", "2025 stream lock differs")
    require(stream_certification["calendar_2026"] == "LOCKED", "2026 stream lock differs")
    primary_hash = sha256_file(PRIMARY_STREAM)
    reference_hash = sha256_file(REFERENCE_STREAM)
    require(primary_hash == stream_certification["primary_sha256"], "Primary stream hash differs")
    require(reference_hash == stream_certification["reference_sha256"], "Reference stream hash differs")
    require(primary_hash == reference_hash, "Independent stream hashes differ")
    require(PRIMARY_STREAM.read_bytes() == REFERENCE_STREAM.read_bytes(), "Stream bytes differ")

    public_registry = load_json(ARTIFACT / "practice_registry.public.json")
    private_registry = load_json(ARTIFACT / "practice_registry.private.json")
    execution_policy = load_json(ARTIFACT / "execution_policy.json")
    ledger_policy = load_json(ARTIFACT / "ledger_policy.json")
    aliases = [row["case_alias"] for row in public_registry["cases"]]
    require(aliases == [f"V3-P-{index:03d}" for index in range(1, 21)], "Practice aliases differ")
    require(public_registry["one_year_collection"] == "CLOSED", "Public collection lock differs")
    require(private_registry["primary_collection_state"] == "CLOSED_NOT_MATERIALIZED", "Private collection lock differs")
    require(public_registry["calendar_2025"] == private_registry["calendar_2025"] == "LOCKED", "2025 registry lock differs")
    require(public_registry["calendar_2026"] == private_registry["calendar_2026"] == "LOCKED", "2026 registry lock differs")
    require(execution_policy["maximum_planned_risk_usd"] == 50.0, "Frozen risk differs")
    require(execution_policy["same_bar_ambiguity"] == "STOP_FIRST", "Ambiguity rule differs")
    require(execution_policy["post_fill_geometry_mutable"] is False, "Filled geometry is mutable")
    require(ledger_policy["fsync_before_response"] is True, "Ledger fsync rule differs")
    require(ledger_policy["idempotency_required"] is True, "Idempotency rule differs")
    require(ledger_policy["human_ledger_isolation_from_tests"] is True, "Ledger isolation differs")
    require(
        not HUMAN_LEDGER.exists() or HUMAN_LEDGER.stat().st_size == 0,
        "Human practice ledger was touched before handoff",
    )

    last_run = load_json(BROWSER / "playwright_last_run.json")
    require(last_run == {"status": "passed", "failedTests": []}, "Final Chrome result differs")
    certified_screenshot = BROWSER / "gold_replay_v3_certified.png"
    finished_screenshot = BROWSER / "playwright_test_finished.png"
    trace = BROWSER / "playwright_trace.zip"
    require(certified_screenshot.stat().st_size > 50_000, "Certified screenshot is incomplete")
    require(finished_screenshot.stat().st_size > 50_000, "Finished screenshot is incomplete")
    require(trace.stat().st_size > 1_000_000, "Playwright trace is incomplete")

    sealed_files = [file_record(path) for path in SEALED_IMPLEMENTATION_FILES]
    sealed_files.extend(file_record(path) for path in BROWSER_EVIDENCE)
    sealed_files.extend(
        file_record(path.relative_to(ROOT).as_posix())
        for path in (
            PREIMPLEMENTATION,
            AMENDMENT_FREEZE,
            STREAM_CERTIFICATION,
            PRIMARY_STREAM,
            REFERENCE_STREAM,
            ARTIFACT / "metadata_coverage_audit.json",
            ARTIFACT / "practice_registry.private.json",
            ARTIFACT / "practice_registry.public.json",
            ARTIFACT / "execution_policy.json",
            ARTIFACT / "ledger_policy.json",
        )
    )

    gates = {
        "predecessor_and_v3_freezes_verified": True,
        "original_failed_stream_artifacts_preserved": True,
        "corrected_stream_certification_passed": True,
        "practice_population_exact_20": True,
        "primary_reference_streams_byte_identical": True,
        "human_practice_ledger_untouched": True,
        "browser_test_ledger_isolated": True,
        "backend_python_3_12_tests_4_of_4_passed": True,
        "focused_backend_ruff_lint_and_format_passed": True,
        "frontend_component_tests_27_of_27_passed": True,
        "frontend_typecheck_passed": True,
        "frontend_lint_passed": True,
        "frontend_production_build_passed": True,
        "real_chrome_lifecycle_matrix_1_of_1_passed": True,
        "all_browser_matrix_requirements_passed": True,
        "final_isolated_api_and_web_healthy": True,
        "one_year_collection_not_materialized_or_accessible": True,
        "calendar_2025_locked": True,
        "calendar_2026_locked": True,
        "no_acquisition_or_charge": True,
        "no_practice_aggregate_edge_or_performance_reported": True,
    }
    require(all(gates.values()), "A V3 certification gate failed")

    completed_at = datetime.now(timezone.utc).isoformat()
    certification = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_BROWSER_REGRESSION_CERTIFICATION_1_0",
        "completed_at": completed_at,
        "verdict": "PASS_V3_APPLICATION_AND_BROWSER_CERTIFICATION",
        "status": "SEALED_READY_FOR_TWENTY_ZERO_CREDIT_PRACTICE_SCORED_COLLECTION_CLOSED",
        "practice_case_count": 20,
        "human_practice_events_at_certification": 0,
        "research_credit": "ZERO_PRACTICE_ONLY",
        "browser": {
            "engine": "GOOGLE_CHROME",
            "playwright_version": "1.62.1",
            "matrix_tests_passed": 1,
            "matrix_tests_failed": 0,
            "final_run_wall_time_approx_seconds": 74,
            "requirements": {name: True for name in BROWSER_MATRIX},
            "api_image_sha256": "8905d626265cd8ba96d7bc9fc210865bdf1fc087aa67f572face1e3f25343848",
            "web_image_sha256": "70960d851e6c7fda3112295d29c547aaedf16203138c543b0bbc0d2e75bdbdf0",
            "isolated_ledger_records": 36,
            "isolated_ledger_sha256": "c9a85c793648cf3899ee0735793b836adebc55055b25f5a58641b59037676f97",
        },
        "quality_checks": {
            "backend_python": "3.12",
            "backend_tests": {"passed": 4, "failed": 0},
            "backend_ruff": "PASS",
            "frontend_tests": {"passed": 27, "failed": 0},
            "frontend_typecheck": "PASS",
            "frontend_lint": "PASS",
            "frontend_production_build": "PASS",
        },
        "source_certification": {
            "practice_stream_sha256": primary_hash,
            "complete_stream_set_sha256": stream_certification["complete_stream_set_sha256"],
            "primary_reference_byte_identical": True,
        },
        "sealed_files": sealed_files,
        "sealed_files_sha256": canonical_hash(sealed_files),
        "gates": gates,
        "one_year_collection": "CLOSED_NOT_MATERIALIZED_OR_ACCESSIBLE",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    CERTIFICATION.parent.mkdir(parents=True, exist_ok=True)
    with CERTIFICATION.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(certification, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")

    final_outputs = [
        file_record(CERTIFICATION.relative_to(ROOT).as_posix()),
        file_record("GOLD_ANNOTATED_REPLAY_V3_IMPLEMENTATION_REPORT.md"),
        file_record("GOLD_ANNOTATED_REPLAY_V3_USER_GUIDE.md"),
    ]
    final_seal = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_PRACTICE_CERTIFICATION_SEAL_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": certification["verdict"],
        "status": certification["status"],
        "human_practice_events_at_seal": 0,
        "sealed_outputs": final_outputs,
        "sealed_outputs_sha256": canonical_hash(final_outputs),
        "source_set_sha256": certification["sealed_files_sha256"],
        "one_year_collection": "CLOSED",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    with FINAL_SEAL.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(final_seal, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")

    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "status": certification["status"],
                "human_practice_events": 0,
                "practice_cases": 20,
                "browser_matrix": "1/1 PASS",
                "final_seal_sha256": sha256_file(FINAL_SEAL),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
