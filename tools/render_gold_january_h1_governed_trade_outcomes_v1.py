#!/usr/bin/env python3
"""Resolve the frozen January plans and render one continuous month chart."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    load_certified_streams,
    require,
    sha256_file,
)

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    parse_dt,
)
from gold_intel.analytics.h1_governed_trade_outcome_v1 import (  # noqa: E402
    END_EXCLUSIVE,
    RULESET,
    evaluate_plans,
)
from gold_intel.analytics.h1_governed_trade_plan_v1 import (  # noqa: E402
    assert_outcome_blind,
)

START = "2022-01-01T00:00:00Z"
SPEC = ROOT / "GOLD_JANUARY_H1_GOVERNED_TRADE_OUTCOMES_V1.md"
EVALUATOR = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "h1_governed_trade_outcome_v1.py"
)
RENDERER = Path(__file__).resolve()
CERTIFICATION = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "stream_materialization_certification.json"
)
PLAN_DIR = ROOT / "research_artifacts" / "gold_january_h1_governed_trade_plans_v1"
PLANS = PLAN_DIR / "outcome_blind_plans.json"
PLAN_MANIFEST = PLAN_DIR / "visual_manifest.json"
OUT = ROOT / "research_artifacts" / "gold_january_h1_governed_trade_outcomes_v1"
TEMPLATE = OUT / "january-h1-governed-trade-outcomes.template.html"
FRAGMENT = OUT / "gold-january-h1-governed-trade-outcomes.html"
OUTCOMES = OUT / "january_outcomes.json"
COVERAGE = OUT / "outcome_coverage_certification.json"
MANIFEST = OUT / "outcome_visual_manifest.json"

DISPLAY_TIMEFRAMES = ("1h", "15m", "5m")
REQUIRED_TIMEFRAMES = ("1m", *DISPLAY_TIMEFRAMES)


def sec(value: str) -> int:
    return int(parse_dt(value).timestamp())


def compact_bar(row: Mapping[str, Any]) -> list[float | int]:
    return [
        sec(str(row["open_at"])),
        round(float(row["open"]), 4),
        round(float(row["high"]), 4),
        round(float(row["low"]), 4),
        round(float(row["close"]), 4),
    ]


def canonical_rows(
    streams: Mapping[str, Mapping[str, Any]], side: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    diagnostics: dict[str, Any] = {}
    for timeframe in REQUIRED_TIMEFRAMES:
        by_open: dict[str, dict[str, Any]] = {}
        duplicate_equal = 0
        for alias in sorted(streams):
            for source in streams[alias]["timeframes"][timeframe]:
                row = dict(source)
                key = str(row["open_at"])
                if key in by_open:
                    require(
                        by_open[key] == row,
                        f"{side} conflicting {timeframe} overlap at {key}",
                    )
                    duplicate_equal += 1
                else:
                    by_open[key] = row
        rows = sorted(
            by_open.values(),
            key=lambda row: (
                parse_dt(str(row["open_at"])),
                parse_dt(str(row["available_at"])),
                str(row["bar_id"]),
            ),
        )
        require(rows, f"{side} {timeframe} rows absent")
        require(
            len({str(row["bar_id"]) for row in rows}) == len(rows),
            f"{side} duplicate {timeframe} bar identity",
        )
        january = [
            row
            for row in rows
            if parse_dt(START) <= parse_dt(str(row["open_at"]))
            and parse_dt(str(row["available_at"])) <= parse_dt(END_EXCLUSIVE)
        ]
        require(january, f"{side} January {timeframe} rows absent")
        merged[timeframe] = rows
        diagnostics[timeframe] = {
            "merged_rows": len(rows),
            "january_rows": len(january),
            "first_january_open_at": str(january[0]["open_at"]),
            "last_january_available_at": str(january[-1]["available_at"]),
            "duplicate_equal_overlap_emissions": duplicate_equal,
            "conflicting_overlaps": 0,
            "january_rows_sha256": canonical_hash(january),
        }
    return merged, diagnostics


def frozen_plan_source_is_sealed() -> dict[str, Any]:
    manifest = json.loads(PLAN_MANIFEST.read_text(encoding="utf-8"))
    require(
        manifest["verdict"]
        == "PASS_OUTCOME_BLIND_JANUARY_PLAN_ATLAS_REPRODUCTION",
        "Frozen plan manifest is not PASS",
    )
    matches = [
        item
        for item in manifest["files"]
        if str(item["path"]).endswith("outcome_blind_plans.json")
    ]
    require(len(matches) == 1, "Frozen plan file seal is ambiguous")
    require(
        sha256_file(PLANS) == str(matches[0]["sha256"]),
        "Frozen plan payload differs from its seal",
    )
    return manifest


def compact_plan(plan: Mapping[str, Any], outcome: Mapping[str, Any], index: int) -> dict[str, Any]:
    return {
        "number": index + 1,
        "planIdentity": str(plan["plan_identity"]),
        "sampleId": str(plan["sample_id"]),
        "decision": sec(str(plan["decision_at"])),
        "resolution": sec(str(outcome["resolution_bar_open_at"])),
        "resolutionKnown": sec(str(outcome["resolution_known_at"])),
        "direction": str(plan["direction"]),
        "family": str(plan["family"]),
        "h1State": str(plan["governing_h1_auction"]["state"]),
        "setupFamily": str(plan["m15_setup"]["setup_family"]),
        "entry": round(float(plan["entry"]["level"]), 4),
        "stop": round(float(plan["invalidation"]["level"]), 4),
        "target": round(float(plan["destination"]["level"]), 4),
        "targetTimeframe": str(plan["destination"]["timeframe"]),
        "targetRole": str(plan["destination"]["role"]),
        "disposition": str(outcome["disposition"]),
        "grossR": round(float(outcome["gross_r"]), 6),
        "targetR": round(float(outcome["target_r"]), 6),
        "durationMinutes": int(outcome["duration_minutes"]),
        "ambiguous": bool(outcome["same_bar_ambiguous"]),
        "outcomeSha256": str(outcome["outcome_sha256"]),
    }


def main() -> None:
    for path in (SPEC, EVALUATOR, CERTIFICATION, PLANS, PLAN_MANIFEST, TEMPLATE):
        require(path.is_file(), f"Required input absent: {path}")
    OUT.mkdir(parents=True, exist_ok=True)
    frozen_manifest = frozen_plan_source_is_sealed()
    plans = json.loads(PLANS.read_text(encoding="utf-8"))
    assert_outcome_blind(plans)
    require(len(plans) == 12, "Frozen January population is not twelve plans")

    primary_streams, primary_lineage = load_certified_streams(CERTIFICATION, "primary")
    reference_streams, reference_lineage = load_certified_streams(
        CERTIFICATION, "reference"
    )
    primary, primary_diagnostics = canonical_rows(primary_streams, "primary")
    reference, reference_diagnostics = canonical_rows(reference_streams, "reference")
    require(primary == reference, "Primary/reference merged rows differ")

    primary_outcomes = evaluate_plans(plans, primary["1m"])
    reference_outcomes = evaluate_plans(plans, reference["1m"])
    require(primary_outcomes == reference_outcomes, "Primary/reference outcomes differ")
    require(
        [item["plan_identity"] for item in primary_outcomes]
        == [str(plan["plan_identity"]) for plan in plans],
        "Outcome population differs from frozen plan population",
    )

    counts = {
        name: sum(item["disposition"] == name for item in primary_outcomes)
        for name in ("TARGET", "STOP", "STOP_FIRST_AMBIGUOUS", "MONTH_END_MARK")
    }
    resolved = counts["TARGET"] + counts["STOP"] + counts["STOP_FIRST_AMBIGUOUS"]
    summary = {
        "plans": len(plans),
        "target_hits": counts["TARGET"],
        "stops": counts["STOP"],
        "stop_first_ambiguous": counts["STOP_FIRST_AMBIGUOUS"],
        "month_end_marks": counts["MONTH_END_MARK"],
        "resolved_hit_rate": counts["TARGET"] / resolved if resolved else None,
        "gross_r_sum": sum(float(item["gross_r"]) for item in primary_outcomes),
        "gross_r_average": sum(float(item["gross_r"]) for item in primary_outcomes)
        / len(primary_outcomes),
    }
    outcomes_payload = {
        "version": "GOLD_JANUARY_H1_GOVERNED_TRADE_OUTCOMES_V1",
        "period": {"start": START, "endExclusive": END_EXCLUSIVE},
        "population": "FROZEN_12_JANUARY_H1_GOVERNED_PLANS",
        "ruleset": RULESET,
        "summary": summary,
        "outcomes": primary_outcomes,
    }
    outcomes_payload["outcomes_sha256"] = canonical_hash(outcomes_payload)
    OUTCOMES.write_text(
        json.dumps(outcomes_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    january_bars = {
        timeframe: [
            compact_bar(row)
            for row in primary[timeframe]
            if parse_dt(START) <= parse_dt(str(row["open_at"]))
            and parse_dt(str(row["available_at"])) <= parse_dt(END_EXCLUSIVE)
        ]
        for timeframe in DISPLAY_TIMEFRAMES
    }
    display_plans = [
        compact_plan(plan, outcome, index)
        for index, (plan, outcome) in enumerate(zip(plans, primary_outcomes, strict=True))
    ]
    dataset: dict[str, Any] = {
        "version": "GOLD_JANUARY_H1_GOVERNED_CONTINUOUS_OUTCOME_CHART_V1",
        "period": {"start": START, "endExclusive": END_EXCLUSIVE},
        "summary": summary,
        "bars": {"H1": january_bars["1h"], "M15": january_bars["15m"], "M5": january_bars["5m"]},
        "plans": display_plans,
        "guards": {
            "continuousMonthNotCases": True,
            "frozenPlanPopulation": True,
            "noPlanRetuning": True,
            "m1FirstPassage": True,
            "sameBarStopFirst": True,
            "grossBeforeCosts": True,
            "overlapUnconstrained": True,
            "primaryReferenceExact": True,
        },
        "sourceHashes": {
            "spec": sha256_file(SPEC),
            "evaluator": sha256_file(EVALUATOR),
            "renderer": sha256_file(RENDERER),
            "certification": sha256_file(CERTIFICATION),
            "plans": sha256_file(PLANS),
            "planManifest": sha256_file(PLAN_MANIFEST),
            "outcomes": sha256_file(OUTCOMES),
            "primaryLineage": canonical_hash(primary_lineage),
            "referenceLineage": canonical_hash(reference_lineage),
        },
    }
    dataset["dataSha256"] = canonical_hash(dataset)
    marker = "__JANUARY_H1_GOVERNED_OUTCOME_DATA__"
    template = TEMPLATE.read_text(encoding="utf-8")
    require(template.count(marker) == 1, "Template marker differs")
    encoded = json.dumps(dataset, separators=(",", ":"), allow_nan=False).replace(
        "</", "<\\/"
    )
    fragment = template.replace(marker, encoded)
    require(len(fragment.encode("utf-8")) < 1_000_000, "Fragment exceeds 1 MB")
    FRAGMENT.write_text(fragment, encoding="utf-8", newline="\n")

    coverage = {
        "version": "GOLD_JANUARY_H1_GOVERNED_TRADE_OUTCOME_COVERAGE_V1",
        "verdict": "PASS_PRIMARY_REFERENCE_OUTCOME_REPRODUCTION",
        "period": {"start": START, "endExclusive": END_EXCLUSIVE},
        "frozen_plan_manifest_sha256": frozen_manifest["manifest_sha256"],
        "frozen_plan_count": len(plans),
        "primary": primary_diagnostics,
        "reference": reference_diagnostics,
        "primary_reference_rows_exact": True,
        "primary_reference_outcomes_exact": True,
        "outcomes_sha256": outcomes_payload["outcomes_sha256"],
        "summary": summary,
    }
    coverage["coverage_sha256"] = canonical_hash(coverage)
    COVERAGE.write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest = {
        "version": "GOLD_JANUARY_H1_GOVERNED_CONTINUOUS_OUTCOME_CHART_V1_MANIFEST",
        "verdict": "PASS_CONTINUOUS_JANUARY_OUTCOME_CHART_REPRODUCTION",
        "summary": summary,
        "data_sha256": dataset["dataSha256"],
        "outcomes_sha256": outcomes_payload["outcomes_sha256"],
        "primary_reference_exact": True,
        "fragment_bytes": FRAGMENT.stat().st_size,
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (
                SPEC,
                EVALUATOR,
                RENDERER,
                CERTIFICATION,
                PLANS,
                PLAN_MANIFEST,
                OUTCOMES,
                COVERAGE,
                TEMPLATE,
                FRAGMENT,
            )
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"verdict": manifest["verdict"], **summary}, indent=2))


if __name__ == "__main__":
    main()
