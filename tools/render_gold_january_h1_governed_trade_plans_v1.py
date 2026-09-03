#!/usr/bin/env python3
"""Scan and render outcome-blind H1-governed January 2022 trade plans."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

from gold_coherent_auction_end_to_end_v1_common import (
    load_certified_streams,
    require,
    sha256_file,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (
    canonical_hash,
    parse_dt,
)
from gold_intel.analytics.h1_governed_trade_plan_v1 import (
    assert_outcome_blind,
)
from gold_intel.analytics.h1_governed_trade_scanner_v1 import (
    END,
    RULESET,
    START,
    scan_stream,
)

SPEC = ROOT / "GOLD_JANUARY_H1_GOVERNED_TRADE_PLAN_ATLAS_V1.md"
PLAN_COMPILER = (
    ROOT / "backend" / "src" / "gold_intel" / "analytics" / "h1_governed_trade_plan_v1.py"
)
SCANNER = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "h1_governed_trade_scanner_v1.py"
)
RENDERER = Path(__file__).resolve()
CERTIFICATION = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "stream_materialization_certification.json"
)
OUT = ROOT / "research_artifacts" / "gold_january_h1_governed_trade_plans_v1"
TEMPLATE = OUT / "january-h1-governed-trade-plans.template.html"
FRAGMENT = OUT / "gold-january-h1-governed-trade-plans.html"
PLANS = OUT / "outcome_blind_plans.json"
COVERAGE = OUT / "coverage_certification.json"
MANIFEST = OUT / "visual_manifest.json"

TIMEFRAMES = ("1h", "15m", "5m")
WINDOWS = {"1h": (84, 124), "15m": (72, 104), "5m": (64, 72)}


def sec(value: str) -> int:
    return int(parse_dt(value).timestamp())


def compact_bar(row: Mapping[str, Any]) -> list[float | int]:
    return [
        sec(str(row["open_at"])),
        sec(str(row["available_at"])),
        round(float(row["open"]), 4),
        round(float(row["high"]), 4),
        round(float(row["low"]), 4),
        round(float(row["close"]), 4),
    ]


def canonical_stream(
    streams: Mapping[str, Mapping[str, Any]], side: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    diagnostics: dict[str, Any] = {}
    for timeframe in TIMEFRAMES:
        by_open: dict[str, dict[str, Any]] = {}
        duplicate_emissions = 0
        for alias in sorted(streams):
            for source in streams[alias]["timeframes"][timeframe]:
                row = dict(source)
                key = str(row["open_at"])
                if key in by_open:
                    require(
                        by_open[key] == row,
                        f"{side} conflicting {timeframe} overlap at {key}",
                    )
                    duplicate_emissions += 1
                else:
                    by_open[key] = row
        rows = sorted(
            by_open.values(),
            key=lambda item: (
                parse_dt(str(item["open_at"])),
                parse_dt(str(item["available_at"])),
            ),
        )
        require(rows, f"{side} {timeframe} rows absent")
        require(
            len({str(row["bar_id"]) for row in rows}) == len(rows),
            f"{side} duplicate {timeframe} bar identity",
        )
        merged[timeframe] = rows
        january = [
            row
            for row in rows
            if parse_dt(START) <= parse_dt(str(row["open_at"])) < parse_dt(END)
        ]
        require(january, f"{side} January {timeframe} coverage absent")
        diagnostics[timeframe] = {
            "merged_rows": len(rows),
            "january_rows": len(january),
            "first_open_at": str(rows[0]["open_at"]),
            "last_open_at": str(rows[-1]["open_at"]),
            "duplicate_equal_overlap_emissions": duplicate_emissions,
            "conflicting_overlaps": 0,
            "rows_sha256": canonical_hash(rows),
        }
    core = {
        "case_alias": "JANUARY_2022_UNIFIED_REPLAY",
        "trading_date_utc": "2022-01",
        "timeframes": merged,
    }
    core["stream_sha256"] = canonical_hash(core)
    return core, diagnostics


def relevant_times(plan: Mapping[str, Any], timeframe: str) -> list[str]:
    evidence = plan["source_evidence"]
    if timeframe == "1h":
        values = [
            evidence["h1_governing_control"]["pivot_at"],
            evidence["selected_destination"]["pivot_at"]
            if plan["destination"]["timeframe"] == "H1"
            else None,
        ]
        if evidence.get("h1_range"):
            values.extend(
                [
                    evidence["h1_range"]["lower_boundary"]["pivot_at"],
                    evidence["h1_range"]["upper_boundary"]["pivot_at"],
                ]
            )
        return [str(value) for value in values if value is not None]
    if timeframe == "15m":
        values = [
            evidence["m15_control"]["pivot_at"],
            evidence["m15_terminal"]["pivot_at"]
            if evidence.get("m15_terminal")
            else None,
            evidence["selected_destination"]["pivot_at"]
            if plan["destination"]["timeframe"] == "M15"
            else None,
        ]
        return [str(value) for value in values if value is not None]
    return [
        str(evidence["m5_turn"]["open_at"]),
        str(evidence["m5_retest"]["open_at"]),
    ]


def predecision_window(
    rows: Sequence[dict[str, Any]],
    *,
    decision_at: str,
    timeframe: str,
    required_times: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    eligible = [
        row
        for row in rows
        if row.get("complete") is True
        and parse_dt(str(row["available_at"])) <= parse_dt(decision_at)
    ]
    require(eligible, f"No completed {timeframe} rows at {decision_at}")
    default_count, maximum_count = WINDOWS[timeframe]
    start = max(0, len(eligible) - default_count)
    by_open = {str(row["open_at"]): index for index, row in enumerate(eligible)}
    missing: list[str] = []
    for timestamp in required_times:
        index = by_open.get(timestamp)
        if index is None:
            missing.append(timestamp)
            continue
        if index < start and len(eligible) - index <= maximum_count:
            start = max(0, index - 4)
    if len(eligible) - start > maximum_count:
        start = len(eligible) - maximum_count
    return eligible[start:], missing


def visual_sample(
    stream: Mapping[str, Any], plan: Mapping[str, Any]
) -> dict[str, Any]:
    charts: dict[str, Any] = {}
    for key, label in (("1h", "H1"), ("15m", "M15"), ("5m", "M5")):
        required = relevant_times(plan, key)
        rows, missing = predecision_window(
            stream["timeframes"][key],
            decision_at=str(plan["decision_at"]),
            timeframe=key,
            required_times=required,
        )
        charts[label] = {
            "bars": [compact_bar(row) for row in rows],
            "requiredPivotTimes": [sec(value) for value in required],
            "requiredPivotsOutsideWindow": [sec(value) for value in missing],
        }
    return {"plan": dict(plan), "charts": charts}


def main() -> None:
    for path in (SPEC, PLAN_COMPILER, SCANNER, CERTIFICATION, TEMPLATE):
        require(path.is_file(), f"Required input absent: {path}")
    OUT.mkdir(parents=True, exist_ok=True)

    primary_streams, primary_lineage = load_certified_streams(
        CERTIFICATION, "primary"
    )
    reference_streams, reference_lineage = load_certified_streams(
        CERTIFICATION, "reference"
    )
    primary, primary_diagnostics = canonical_stream(primary_streams, "primary")
    reference, reference_diagnostics = canonical_stream(reference_streams, "reference")
    require(
        primary["timeframes"] == reference["timeframes"],
        "Primary/reference merged XAUUSD rows differ",
    )
    require(
        primary["stream_sha256"] == reference["stream_sha256"],
        "Primary/reference merged stream hash differs",
    )

    primary_plans = scan_stream(primary)
    reference_plans = scan_stream(reference)
    assert_outcome_blind(primary_plans)
    assert_outcome_blind(reference_plans)
    require(primary_plans, "No H1-governed January plans were admitted")
    require(primary_plans == reference_plans, "Primary/reference plans differ")

    samples = [visual_sample(primary, plan) for plan in primary_plans]
    summary = {
        "plans": len(primary_plans),
        "trend": sum(plan["family"] == "TREND" for plan in primary_plans),
        "range": sum(plan["family"] == "RANGE" for plan in primary_plans),
        "long": sum(plan["direction"] == "LONG" for plan in primary_plans),
        "short": sum(plan["direction"] == "SHORT" for plan in primary_plans),
        "first_decision_at": primary_plans[0]["decision_at"],
        "last_decision_at": primary_plans[-1]["decision_at"],
    }
    coverage = {
        "version": "GOLD_JANUARY_H1_GOVERNED_TRADE_PLAN_COVERAGE_V1",
        "verdict": "PASS_PRIMARY_REFERENCE_SOURCE_AND_PLAN_REPRODUCTION",
        "period": {"start": START, "endExclusive": END},
        "primary": primary_diagnostics,
        "reference": reference_diagnostics,
        "primary_lineage_sha256": canonical_hash(primary_lineage),
        "reference_lineage_sha256": canonical_hash(reference_lineage),
        "merged_stream_sha256": primary["stream_sha256"],
        "plans_sha256": canonical_hash(primary_plans),
        "plan_compiler_sha256": sha256_file(PLAN_COMPILER),
        "scanner_sha256": sha256_file(SCANNER),
        "renderer_sha256": sha256_file(RENDERER),
        "template_sha256": sha256_file(TEMPLATE),
        "summary": summary,
    }
    coverage["coverage_sha256"] = canonical_hash(coverage)
    COVERAGE.write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    PLANS.write_text(
        json.dumps(primary_plans, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    dataset: dict[str, Any] = {
        "version": "GOLD_JANUARY_H1_GOVERNED_TRADE_PLAN_ATLAS_V1",
        "period": {"start": START, "endExclusive": END},
        "summary": summary,
        "samples": samples,
        "guards": {
            "observedSealedPrices": True,
            "allCandlesPredecision": True,
            "h1Governs": True,
            "m15SetsUp": True,
            "m5Executes": True,
            "trendTargetsH1Swing": True,
            "rangeTargetsInternalM15Liquidity": True,
            "rangeTargetsOppositeBoundary": False,
            "outcomesIncluded": False,
            "pnlCalculated": False,
            "fixedLightTheme": True,
        },
        "sourceHashes": {
            "spec": sha256_file(SPEC),
            "planCompiler": sha256_file(PLAN_COMPILER),
            "scanner": sha256_file(SCANNER),
            "renderer": sha256_file(RENDERER),
            "template": sha256_file(TEMPLATE),
            "certification": sha256_file(CERTIFICATION),
            "coverage": sha256_file(COVERAGE),
            "plans": sha256_file(PLANS),
            "scannerRuleset": RULESET,
        },
    }
    assert_outcome_blind(dataset)
    dataset["dataSha256"] = canonical_hash(dataset)
    marker = "__JANUARY_H1_GOVERNED_PLAN_DATA__"
    template = TEMPLATE.read_text(encoding="utf-8")
    require(template.count(marker) == 1, "Template marker differs")
    encoded = json.dumps(dataset, separators=(",", ":"), allow_nan=False).replace(
        "</", "<\\/"
    )
    fragment = template.replace(marker, encoded)
    require(len(fragment.encode("utf-8")) < 1_000_000, "Fragment exceeds 1 MB")
    FRAGMENT.write_text(fragment, encoding="utf-8", newline="\n")

    manifest = {
        "version": "GOLD_JANUARY_H1_GOVERNED_TRADE_PLAN_ATLAS_V1_MANIFEST",
        "verdict": "PASS_OUTCOME_BLIND_JANUARY_PLAN_ATLAS_REPRODUCTION",
        "summary": summary,
        "data_sha256": dataset["dataSha256"],
        "plans_sha256": coverage["plans_sha256"],
        "merged_stream_sha256": coverage["merged_stream_sha256"],
        "primary_reference_exact": True,
        "guards": dataset["guards"],
        "fragment_bytes": FRAGMENT.stat().st_size,
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (
                SPEC,
                PLAN_COMPILER,
                SCANNER,
                RENDERER,
                CERTIFICATION,
                COVERAGE,
                PLANS,
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
