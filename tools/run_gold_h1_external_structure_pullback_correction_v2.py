#!/usr/bin/env python3
"""Run the frozen exposed H1 external-structure correction regression."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    load_certified_streams,
    require,
    sha256_file,
)
from gold_intel.analytics.auction_liquidity_range_semantics_v1 import (  # noqa: E402
    structure_state,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    confirmed_swings,
    parse_dt,
)
from gold_intel.analytics.early_m5_curvature_entry_v1 import (  # noqa: E402
    trigger_direction,
)
from gold_intel.analytics.h1_external_structure_pullback_v2 import (  # noqa: E402
    RULESET,
    scan_stream,
    synthetic_proof,
)
from gold_intel.analytics.h1_governed_trade_outcome_v1 import (  # noqa: E402
    evaluate_plans,
)
from gold_intel.analytics.h1_governed_trade_plan_v1 import (  # noqa: E402
    assert_outcome_blind,
)
from gold_intel.analytics.h1_governed_trade_scanner_v1 import (  # noqa: E402
    PointInTimeInventoryTimeline,
    _first_valid_retest,
    _is_unconsumed,
    _latest,
    _states,
    h1_context_at,
    m15_context_at,
)
from gold_intel.analytics.swing_curvature_entry_v1 import (  # noqa: E402
    overlaps_zone,
)
from render_gold_january_h1_continuous_swing_atlas_v1 import (  # noqa: E402
    canonical_h1,
)
from render_gold_january_h1_governed_trade_outcomes_v1 import (  # noqa: E402
    canonical_rows,
)
from render_gold_january_h1_governed_trade_plans_v1 import (  # noqa: E402
    canonical_stream,
)


SPEC = ROOT / "GOLD_H1_EXTERNAL_STRUCTURE_PULLBACK_CORRECTION_V2.md"
MODULE = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "h1_external_structure_pullback_v2.py"
)
RUNNER = Path(__file__).resolve()
CERTIFICATION = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "stream_materialization_certification.json"
)
V1_PLANS = (
    ROOT
    / "research_artifacts"
    / "gold_january_h1_governed_trade_plans_v1"
    / "outcome_blind_plans.json"
)
V1_OUTCOMES = (
    ROOT
    / "research_artifacts"
    / "gold_january_h1_governed_trade_outcomes_v1"
    / "january_outcomes.json"
)
OUT = ROOT / "research_artifacts" / "gold_h1_external_structure_pullback_correction_v2"
PLANS = OUT / "corrected_outcome_blind_plans.json"
PREOUTCOME = OUT / "preoutcome_plan_seal.json"
RESULT = OUT / "exposed_regression_result.json"
REPORT = OUT / "exposed_regression_report.md"
MANIFEST = OUT / "manifest.json"

MARKED = (
    {
        "label": "A",
        "pivot_at": "2022-01-10T16:00:00Z",
        "window_start": "2022-01-10T14:00:00Z",
        "window_end": "2022-01-10T20:00:00Z",
    },
    {
        "label": "B",
        "pivot_at": "2022-01-11T16:00:00Z",
        "window_start": "2022-01-11T14:00:00Z",
        "window_end": "2022-01-11T20:00:00Z",
    },
    {
        "label": "C",
        "pivot_at": "2022-01-12T10:00:00Z",
        "window_start": "2022-01-12T08:00:00Z",
        "window_end": "2022-01-12T14:00:00Z",
    },
)


def _h1_failure_reason(
    stream: Mapping[str, Any],
    timeline: PointInTimeInventoryTimeline,
    *,
    cutoff: str,
    direction: str,
    price: float,
) -> str:
    inventory, states = _states(
        stream["timeframes"]["1h"], cutoff, "H1", timeline
    )
    structure = structure_state(inventory)
    wanted = "UPTREND" if direction == "LONG" else "DOWNTREND"
    if structure["state"] != wanted:
        return f"STATE_{structure['state']}"
    control_kind = "LOW" if direction == "LONG" else "HIGH"
    destination_kind = "HIGH" if direction == "LONG" else "LOW"
    control = _latest(states, control_kind)
    if control is None:
        return "CONTROL_ABSENT"
    if not _is_unconsumed(control):
        return "LATEST_CONTROL_CONSUMED"
    behind = (
        float(control["level"]) < price
        if direction == "LONG"
        else float(control["level"]) > price
    )
    if not behind:
        return "LATEST_CONTROL_NOT_BEHIND_PRICE"
    destinations = [
        item
        for item in states
        if item["kind"] == destination_kind
        and _is_unconsumed(item)
        and (
            float(item["level"]) > price
            if direction == "LONG"
            else float(item["level"]) < price
        )
    ]
    return "NO_UNCONSUMED_H1_DESTINATION_AHEAD" if not destinations else "UNKNOWN"


def _v1_gate_counts(
    stream: Mapping[str, Any], *, start: str, end: str
) -> dict[str, int]:
    h1_timeline = PointInTimeInventoryTimeline(
        stream["timeframes"]["1h"], end="2022-02-01T00:00:00Z", timeframe="1h"
    )
    m15_timeline = PointInTimeInventoryTimeline(
        stream["timeframes"]["15m"], end="2022-02-01T00:00:00Z", timeframe="15m"
    )
    m5 = stream["timeframes"]["5m"]
    gates: Counter[str] = Counter()
    for index in range(3, len(m5)):
        turn = m5[index]
        cutoff = str(turn["available_at"])
        if not (start <= cutoff < end):
            continue
        direction = trigger_direction(m5[index - 3 : index], turn)
        if direction != "LONG":
            continue
        price = float(turn["close"])
        h1 = h1_context_at(
            stream,
            cutoff=cutoff,
            direction="LONG",
            price=price,
            timeline=h1_timeline,
        )
        if h1 is None:
            gates[
                _h1_failure_reason(
                    stream,
                    h1_timeline,
                    cutoff=cutoff,
                    direction="LONG",
                    price=price,
                )
            ] += 1
            continue
        m15 = m15_context_at(
            stream,
            cutoff=cutoff,
            direction="LONG",
            h1_context=h1,
            timeline=m15_timeline,
        )
        if m15 is None:
            gates["M15_CONTEXT_FAIL"] += 1
            continue
        zone = dict(m15["zone"])
        if not any(overlaps_zone(row, zone) for row in [*m5[index - 3 : index], turn]):
            gates["M15_ZONE_NOT_ENGAGED"] += 1
            continue
        if not float(zone["lower"]) <= float(turn["low"]) <= float(zone["upper"]):
            gates["M5_TURN_EXTREME_OUTSIDE_ZONE"] += 1
            continue
        retest = _first_valid_retest(
            m5,
            turn_index=index,
            direction="LONG",
            zone=zone,
            control=m15["control"],
        )
        gates["PASS" if retest is not None else "M5_RETEST_FAIL"] += 1
    return dict(sorted(gates.items()))


def _marked_swings(h1_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, swings = confirmed_swings(h1_rows, "2022-02-03T00:00:00Z", "H1")
    by_pivot = {
        str(item["pivot_at"]): item
        for item in swings
        if item["kind"] == "LOW"
    }
    output: list[dict[str, Any]] = []
    for definition in MARKED:
        swing = by_pivot.get(definition["pivot_at"])
        require(swing is not None, f"Marked H1 low absent: {definition['pivot_at']}")
        output.append(
            {
                **definition,
                "identity": swing["identity"],
                "known_at": swing["detected_at"],
                "level": swing["level"],
                "prominence_atr": swing["prominence_atr"],
            }
        )
    return output


def _summary(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in outcomes if row["disposition"] != "MONTH_END_MARK"]
    target = sum(row["disposition"] == "TARGET" for row in outcomes)
    stop = sum(row["disposition"] in {"STOP", "STOP_FIRST_AMBIGUOUS"} for row in outcomes)
    gross = sum(float(row["gross_r"]) for row in outcomes)
    wins = sum(float(row["gross_r"]) > 0 for row in outcomes)
    return {
        "plans": len(outcomes),
        "targets": target,
        "stops": stop,
        "month_end_marks": len(outcomes) - len(resolved),
        "strict_target_first_rate": target / len(outcomes) if outcomes else 0.0,
        "positive_r_rate": wins / len(outcomes) if outcomes else 0.0,
        "gross_r": gross,
        "average_gross_r": gross / len(outcomes) if outcomes else 0.0,
    }


def main() -> None:
    for path in (SPEC, MODULE, CERTIFICATION, V1_PLANS, V1_OUTCOMES):
        require(path.is_file(), f"Required input absent: {path}")
    require(synthetic_proof()["passed"] is True, "Synthetic semantic proof failed")
    OUT.mkdir(parents=True, exist_ok=True)

    primary_sources, primary_lineage = load_certified_streams(CERTIFICATION, "primary")
    reference_sources, reference_lineage = load_certified_streams(CERTIFICATION, "reference")
    primary, _ = canonical_stream(primary_sources, "primary")
    reference, _ = canonical_stream(reference_sources, "reference")
    require(primary == reference, "Primary/reference predecision stream differs")

    primary_plans = scan_stream(primary)
    reference_plans = scan_stream(reference)
    assert_outcome_blind(primary_plans)
    assert_outcome_blind(reference_plans)
    require(primary_plans == reference_plans, "Corrected primary/reference plans differ")
    PLANS.write_text(
        json.dumps(primary_plans, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    h1_primary = canonical_h1(primary_sources)
    h1_reference = canonical_h1(reference_sources)
    require(h1_primary == h1_reference, "Primary/reference H1 rows differ")
    marked = _marked_swings(h1_primary)
    marked_diagnostics = []
    for item in marked:
        captured = [
            plan
            for plan in primary_plans
            if plan["direction"] == "LONG"
            and item["pivot_at"] <= plan["decision_at"] < item["window_end"]
        ]
        marked_diagnostics.append(
            {
                **item,
                "v1_long_turn_gate_counts": _v1_gate_counts(
                    primary,
                    start=item["window_start"],
                    end=item["window_end"],
                ),
                "v2_captured_plan_ids": [plan["sample_id"] for plan in captured],
                "v2_decision_times": [plan["decision_at"] for plan in captured],
                "v2_captured": bool(captured),
            }
        )

    preoutcome = {
        "version": "GOLD_H1_EXTERNAL_STRUCTURE_PULLBACK_CORRECTION_V2_PREOUTCOME",
        "verdict": "PASS_CORRECTED_OUTCOME_BLIND_PLAN_REPRODUCTION",
        "ruleset": RULESET,
        "synthetic_proof": synthetic_proof(),
        "plans": {
            "count": len(primary_plans),
            "trend": sum(row["family"] == "TREND" for row in primary_plans),
            "range": sum(row["family"] == "RANGE" for row in primary_plans),
            "long": sum(row["direction"] == "LONG" for row in primary_plans),
            "short": sum(row["direction"] == "SHORT" for row in primary_plans),
            "sha256": sha256_file(PLANS),
        },
        "marked_diagnostics": marked_diagnostics,
        "primary_reference_exact": True,
        "outcomes_joined": False,
        "source_stream_sha256": primary["stream_sha256"],
        "source_lineage": {
            "primary": canonical_hash(primary_lineage),
            "reference": canonical_hash(reference_lineage),
        },
        "files": {
            "spec": sha256_file(SPEC),
            "module": sha256_file(MODULE),
            "runner": sha256_file(RUNNER),
            "certification": sha256_file(CERTIFICATION),
        },
    }
    preoutcome["seal_sha256"] = canonical_hash(preoutcome)
    PREOUTCOME.write_text(
        json.dumps(preoutcome, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Outcome access begins only after the corrected plan file and pre-outcome
    # seal exist. January is already exposed and receives no validation credit.
    primary_rows, _ = canonical_rows(primary_sources, "primary")
    reference_rows, _ = canonical_rows(reference_sources, "reference")
    primary_outcomes = evaluate_plans(primary_plans, primary_rows["1m"])
    reference_outcomes = evaluate_plans(reference_plans, reference_rows["1m"])
    require(primary_outcomes == reference_outcomes, "Corrected outcomes differ")

    v1_outcome_payload = json.loads(V1_OUTCOMES.read_text(encoding="utf-8"))
    frozen_v1 = dict(v1_outcome_payload["summary"])
    v1_summary = {
        "plans": int(frozen_v1["plans"]),
        "targets": int(frozen_v1["target_hits"]),
        "stops": int(frozen_v1["stops"]),
        "month_end_marks": int(frozen_v1["month_end_marks"]),
        "strict_target_first_rate": (
            float(frozen_v1["target_hits"]) / float(frozen_v1["plans"])
        ),
        "gross_r": float(frozen_v1["gross_r_sum"]),
        "average_gross_r": float(frozen_v1["gross_r_average"]),
    }
    v2_summary = _summary(primary_outcomes)
    result = {
        "version": "GOLD_H1_EXTERNAL_STRUCTURE_PULLBACK_CORRECTION_V2_RESULT",
        "verdict": "PASS_EXPOSED_SEMANTIC_CORRECTION_REPRODUCTION",
        "research_credit": "ZERO_EXPOSED_JANUARY_SEMANTIC_REGRESSION",
        "v1_control": v1_summary,
        "v2_corrected": v2_summary,
        "marked_diagnostics": marked_diagnostics,
        "outcomes": primary_outcomes,
        "primary_reference_exact": True,
        "later_period_opened": False,
        "costs_included": False,
        "edge_claimed": False,
        "preoutcome_seal_sha256": sha256_file(PREOUTCOME),
    }
    result["result_sha256"] = canonical_hash(result)
    RESULT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = [
        "# H1 external-structure pullback correction - exposed January regression",
        "",
        "## Verdict",
        "",
        "`PASS_EXPOSED_SEMANTIC_CORRECTION_REPRODUCTION`",
        "",
        "The original V1 result remains unchanged. This is an exposed semantic",
        "regression and is not validation or an edge claim.",
        "",
        "## Marked-turn diagnosis",
        "",
        "| Mark | H1 pivot UTC | Known UTC | Original V1 gates | Corrected plan times |",
        "|---|---|---|---|---|",
    ]
    for row in marked_diagnostics:
        gates = ", ".join(
            f"{name}={count}" for name, count in row["v1_long_turn_gate_counts"].items()
        )
        decisions = ", ".join(row["v2_decision_times"]) or "none"
        lines.append(
            f"| {row['label']} | {row['pivot_at']} | {row['known_at']} | {gates} | {decisions} |"
        )
    lines.extend(
        [
            "",
            "## Outcome comparison",
            "",
            "| Version | Plans | Targets | Stops | Strict target-first | Gross R |",
            "|---|---:|---:|---:|---:|---:|",
            (
                f"| V1 control | {v1_summary['plans']} | {v1_summary['targets']} | "
                f"{v1_summary['stops']} | {v1_summary['strict_target_first_rate']:.1%} | "
                f"{v1_summary['gross_r']:+.3f} |"
            ),
            (
                f"| V2 corrected | {v2_summary['plans']} | {v2_summary['targets']} | "
                f"{v2_summary['stops']} | {v2_summary['strict_target_first_rate']:.1%} | "
                f"{v2_summary['gross_r']:+.3f} |"
            ),
            "",
            "Gross geometric R excludes costs and overlap. No later period was opened.",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    manifest = {
        "version": "GOLD_H1_EXTERNAL_STRUCTURE_PULLBACK_CORRECTION_V2_MANIFEST",
        "verdict": result["verdict"],
        "primary_reference_exact": True,
        "plans": len(primary_plans),
        "marked_captured": sum(row["v2_captured"] for row in marked_diagnostics),
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (SPEC, MODULE, RUNNER, PLANS, PREOUTCOME, RESULT, REPORT)
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "marked_captured": manifest["marked_captured"],
                "marked_total": len(marked_diagnostics),
                "v1": v1_summary,
                "v2": v2_summary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
