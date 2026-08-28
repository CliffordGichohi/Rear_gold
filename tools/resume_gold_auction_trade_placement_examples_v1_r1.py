#!/usr/bin/env python3
"""Resume the trade-placement atlas after its filename/path presentation bug."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import render_gold_auction_trade_placement_examples_v1 as original  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


AMENDMENT = ROOT / "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_ENGINEERING_RESUME_R1.md"
RUNNER = Path(__file__).resolve()
RESUME_FREEZE = original.OUT / "engineering_resume_r1_freeze.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _chart_paths() -> list[Path]:
    return sorted(original.CHARTS.glob("*.svg"), key=lambda path: int(path.name.split("_", 1)[0]))


def freeze() -> None:
    require(original.FREEZE.exists(), "Original pre-outcome freeze is missing")
    require(original.PRIMARY.exists() and original.REFERENCE.exists(), "Interrupted plan payloads are missing")
    require(not original.ATLAS.exists(), "Atlas already exists; resume is not applicable")
    require(not original.CERTIFICATION.exists(), "Certification already exists")
    charts = _chart_paths()
    require(len(charts) == 10, f"Expected ten interrupted charts, found {len(charts)}")
    frozen = original.load_json(original.FREEZE)
    require(
        canonical_hash({key: value for key, value in frozen.items() if key != "freeze_sha256"})
        == frozen["freeze_sha256"],
        "Original freeze hash differs",
    )
    original.verify_source_seal()
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_ENGINEERING_RESUME_R1_FREEZE_1_0",
        "frozen_at": original.now(),
        "original_freeze_sha256": frozen["freeze_sha256"],
        "failure": {
            "stage": "ATLAS_HTML_CONSTRUCTION_AFTER_PRIMARY_REFERENCE_EXACTNESS_CHECK",
            "exception": "KeyError: filename",
            "root_cause": "FILE_RECORD_STORES_PATH_WHILE_ATLAS_HELPER_EXPECTED_FILENAME",
        },
        "permitted_change": "DERIVE_FILENAME_FROM_PATH_BASENAME_ONLY",
        "governing_files": [
            original.file_record(AMENDMENT),
            original.file_record(RUNNER),
            original.file_record(original.RUNNER),
        ],
        "interrupted_artifacts": [
            original.file_record(original.PRIMARY),
            original.file_record(original.REFERENCE),
            *[original.file_record(path) for path in charts],
        ],
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    payload["resume_freeze_sha256"] = canonical_hash(payload)
    original.write_json(RESUME_FREEZE, payload)


def resume() -> None:
    require(RESUME_FREEZE.exists(), "Run the resume freeze first")
    resumed = original.load_json(RESUME_FREEZE)
    require(
        canonical_hash({key: value for key, value in resumed.items() if key != "resume_freeze_sha256"})
        == resumed["resume_freeze_sha256"],
        "Resume freeze hash differs",
    )
    for record in resumed["governing_files"] + resumed["interrupted_artifacts"]:
        path = ROOT / record["path"]
        require(path.exists(), f"Resume input missing: {path}")
        require(path.stat().st_size == record["bytes"], f"Resume input size changed: {path}")
        require(original.sha256_file(path) == record["sha256"], f"Resume input hash changed: {path}")
    original.verify_source_seal()

    saved_primary = original.load_json(original.PRIMARY)
    saved_reference = original.load_json(original.REFERENCE)
    calculated_primary, primary_charts, primary_diagnostics = original._side_payload("primary")
    calculated_reference, reference_charts, reference_diagnostics = original._side_payload("reference")
    require(saved_primary == calculated_primary, "Preserved primary plans do not reproduce")
    require(saved_reference == calculated_reference, "Preserved reference plans do not reproduce")
    require(saved_primary["plans"] == saved_reference["plans"], "Primary/reference plans differ")
    require(primary_charts.keys() == reference_charts.keys(), "Primary/reference chart names differ")
    require(
        all(primary_charts[name] == reference_charts[name] for name in primary_charts),
        "Primary/reference recomputed chart bytes differ",
    )
    require(primary_diagnostics == reference_diagnostics, "Primary/reference diagnostics differ")

    chart_paths = _chart_paths()
    require([path.name for path in chart_paths] == list(primary_charts), "Preserved chart ordering differs")
    for path in chart_paths:
        require(path.read_bytes() == primary_charts[path.name], f"Preserved chart differs: {path.name}")

    plans = saved_primary["plans"]
    records = [original.file_record(path) for path in chart_paths]
    atlas_records = [
        {**record, "filename": Path(record["path"]).name}
        for record in records
    ]
    original.write_text(original.ATLAS, original._atlas(plans, atlas_records))

    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_CERTIFICATION_R1_1_0",
        "completed_at": original.now(),
        "verdict": "PASS_OUTCOME_BLIND_TEN_TRADE_PLACEMENT_EXAMPLES_AFTER_PRESENTATION_RESUME",
        "freeze_sha256": original.load_json(original.FREEZE)["freeze_sha256"],
        "resume_freeze_sha256": resumed["resume_freeze_sha256"],
        "plans_sha256": saved_primary["plans_sha256"],
        "plan_identities": [item["event_identity"] for item in plans],
        "counts": {
            "plans": len(plans),
            "directions": dict(Counter(item["direction"] for item in plans)),
            "contexts": dict(Counter(item["context_family"] for item in plans)),
        },
        "planned_r_range": [
            min(float(item["planned_r"]) for item in plans),
            max(float(item["planned_r"]) for item in plans),
        ],
        "primary_reference_plans_exact": True,
        "primary_reference_charts_byte_exact": True,
        "primary_reference_diagnostics_exact": True,
        "preserved_interrupted_charts_byte_exact": True,
        "presentation_correction_only": True,
        "chart_records": records,
        "chart_diagnostics": primary_diagnostics,
        "atlas": original.file_record(original.ATLAS),
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    certification["certification_sha256"] = canonical_hash(certification)
    original.write_json(original.CERTIFICATION, certification)
    report = (
        "# Gold Auction Trade Placement Examples V1 Report\n\n"
        f"Verdict: `{certification['verdict']}`\n\n"
        "Ten outcome-blind plans were rendered: five LONG and five SHORT. Each direction contains one range rotation, two trend-pullback, and two transitional-context examples.\n\n"
        f"Planned target geometry ranges from {certification['planned_r_range'][0]:.2f}R to {certification['planned_r_range'][1]:.2f}R. This is planned geometry, not achieved performance.\n\n"
        "The interrupted plans and charts reproduced byte-for-byte after a presentation-only filename/path correction. Primary and reference plans, diagnostics, and SVG bytes match exactly. No post-decision candles, outcomes, PnL, fresh periods, or paid data were accessed.\n"
    )
    original.write_text(original.REPORT, report)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_SEAL_R1_1_0",
        "sealed_at": original.now(),
        "verdict": certification["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [
            original.file_record(original.FREEZE),
            original.file_record(RESUME_FREEZE),
            original.file_record(original.PRIMARY),
            original.file_record(original.REFERENCE),
            original.file_record(original.ATLAS),
            original.file_record(original.CERTIFICATION),
            original.file_record(original.REPORT),
            *records,
        ],
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    original.write_json(original.SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "counts": certification["counts"],
                "planned_r_range": certification["planned_r_range"],
                "atlas": original.ATLAS.relative_to(ROOT).as_posix(),
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
