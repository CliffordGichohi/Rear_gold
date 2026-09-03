#!/usr/bin/env python3
"""Attribute the exposed January confirmed-H1 swing rotation outcomes."""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    load_certified_streams,
    require,
    sha256_file,
)
from render_gold_january_h1_continuous_swing_atlas_v1 import canonical_h1  # noqa: E402
from render_gold_january_h1_governed_trade_outcomes_v1 import canonical_rows  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    confirmed_swings,
    iso,
    parse_dt,
)
from gold_intel.analytics.h1_external_structure_pullback_v2 import (  # noqa: E402
    external_structure_state,
)

SPEC = ROOT / "GOLD_JANUARY_H1_SWING_LOSS_ATTRIBUTION_V1.md"
CERT = ROOT / "research_artifacts/gold_matched_human_replay_v1/stream_materialization_certification.json"
OUT = ROOT / "research_artifacts/gold_january_h1_swing_loss_attribution_v1"
RESULT = OUT / "attribution_result.json"
REPORT = OUT / "attribution_report.md"
MANIFEST = OUT / "manifest.json"

START = parse_dt("2022-01-01T00:00:00Z")
END = parse_dt("2022-02-01T00:00:00Z")
CONFIRM_CUTOFF = "2022-02-03T00:00:00Z"
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


def merge_timeframe(streams: Mapping[str, Mapping[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    by_open: dict[str, dict[str, Any]] = {}
    for alias in sorted(streams):
        for source in streams[alias]["timeframes"][timeframe]:
            row = dict(source)
            key = str(row["open_at"])
            if key in by_open:
                require(by_open[key] == row, f"Conflicting {timeframe} overlap at {key}")
            else:
                by_open[key] = row
    return sorted(by_open.values(), key=lambda row: (parse_dt(str(row["open_at"])), str(row["bar_id"])))


def structure_input(swings: Sequence[Mapping[str, Any]], decision: datetime) -> list[dict[str, Any]]:
    return [
        {
            "identity": str(row["identity"]),
            "kind": str(row["kind"]),
            "pivot_at": iso(str(row["pivot_at"])),
            "known_at": iso(str(row["detected_at"])),
            "level": float(row["level"]),
            "state": "OBSERVED_CONFIRMED",
        }
        for row in swings
        if parse_dt(str(row["detected_at"])) <= decision
    ]


def alignment(swings: Sequence[Mapping[str, Any]], decision: datetime, direction: str) -> str:
    state = external_structure_state(structure_input(swings, decision))
    inferred = state["direction"]
    if inferred is None:
        return "TRANSITIONING"
    return "ALIGNED" if inferred == direction else "OPPOSED"


def pivot_role(swings: Sequence[Mapping[str, Any]], current: Mapping[str, Any]) -> str:
    decision = parse_dt(str(current["detected_at"]))
    prior = [
        row
        for row in swings
        if str(row["identity"]) != str(current["identity"])
        and parse_dt(str(row["detected_at"])) <= decision
    ]
    state = external_structure_state(structure_input(prior, decision))
    boundary = state["external_high"] if current["kind"] == "HIGH" else state["external_low"]
    if boundary is None:
        return "INITIAL_BOUNDARY"
    if current["kind"] == "HIGH":
        return "EXTERNAL_BREAK" if float(current["level"]) > float(boundary["level"]) else "INTERNAL_OR_CONTAINED"
    return "EXTERNAL_BREAK" if float(current["level"]) < float(boundary["level"]) else "INTERNAL_OR_CONTAINED"


def swing_relation(swings: Sequence[Mapping[str, Any]], current: Mapping[str, Any]) -> str:
    previous = [
        row
        for row in swings
        if row["kind"] == current["kind"]
        and parse_dt(str(row["pivot_at"])) < parse_dt(str(current["pivot_at"]))
        and parse_dt(str(row["detected_at"])) <= parse_dt(str(current["detected_at"]))
    ]
    if not previous:
        return "FIRST"
    prior = max(previous, key=lambda row: parse_dt(str(row["pivot_at"])))
    now = float(current["level"])
    before = float(prior["level"])
    if current["kind"] == "HIGH":
        return "HH" if now > before else "LH" if now < before else "EH"
    return "HL" if now > before else "LL" if now < before else "EL"


def session_at(point: datetime) -> str:
    london = point.astimezone(LONDON)
    new_york = point.astimezone(NEW_YORK)
    if 8 <= london.hour < 12:
        return "LONDON"
    if 8 <= new_york.hour < 12:
        return "NEW_YORK"
    return "OTHER"


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    wins = [row for row in rows if row["outcome"] == "TARGET"]
    losses = [row for row in rows if row["outcome"].startswith("STOP")]
    positive = sum(float(row["realized_r"]) for row in wins)
    negative = -sum(float(row["realized_r"]) for row in losses)
    net = positive - negative
    return {
        "support": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(rows) if rows else None,
        "gross_winning_r": positive,
        "gross_losing_r": -negative,
        "net_r": net,
        "profit_factor": positive / negative if negative else None,
        "expectancy_r": net / len(rows) if rows else None,
        "average_winner_r": positive / len(wins) if wins else None,
    }


def group_metrics(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {key: metrics(groups[key]) for key in sorted(groups)}


def side(side_name: str) -> dict[str, Any]:
    streams, lineage = load_certified_streams(CERT, side_name)
    h1_rows = canonical_h1(streams)
    h4_rows = merge_timeframe(streams, "4h")
    merged, diagnostics = canonical_rows(streams, side_name)
    m1 = merged["1m"]
    _, h1_swings = confirmed_swings(
        [row for row in h1_rows if parse_dt(str(row["open_at"])) < parse_dt(CONFIRM_CUTOFF)],
        CONFIRM_CUTOFF,
        "H1",
    )
    _, h4_swings = confirmed_swings(h4_rows, CONFIRM_CUTOFF, "H4")
    january = [row for row in h1_swings if START <= parse_dt(str(row["pivot_at"])) < END]
    dispositions = Counter()
    trades: list[dict[str, Any]] = []
    for swing in sorted(january, key=lambda row: (parse_dt(str(row["pivot_at"])), str(row["kind"]), str(row["identity"]))):
        decision = parse_dt(str(swing["detected_at"]))
        direction = "LONG" if swing["kind"] == "LOW" else "SHORT"
        prior_opposite = [
            row
            for row in h1_swings
            if row["kind"] != swing["kind"]
            and parse_dt(str(row["pivot_at"])) < parse_dt(str(swing["pivot_at"]))
            and parse_dt(str(row["detected_at"])) <= decision
        ]
        if decision >= END:
            dispositions["CONFIRMED_AFTER_MONTH"] += 1
            continue
        if not prior_opposite:
            dispositions["NO_CAUSAL_TARGET"] += 1
            continue
        target_swing = max(prior_opposite, key=lambda row: parse_dt(str(row["pivot_at"])))
        future = [
            row
            for row in m1
            if row.get("complete") is True
            and parse_dt(str(row["open_at"])) >= decision
            and parse_dt(str(row["available_at"])) <= END
        ]
        require(future, f"No M1 path at {iso(decision)}")
        entry_row = future[0]
        entry = float(entry_row["open"])
        stop = float(swing["level"])
        target = float(target_swing["level"])
        valid = stop < entry < target if direction == "LONG" else target < entry < stop
        if not valid:
            dispositions["NON_EXECUTABLE_GEOMETRY"] += 1
            continue
        risk = abs(entry - stop)
        target_r = abs(target - entry) / risk
        outcome = "MONTH_END_OPEN"
        resolution_index = len(future) - 1
        for index, row in enumerate(future):
            stop_hit = float(row["low"]) <= stop if direction == "LONG" else float(row["high"]) >= stop
            target_hit = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
            if stop_hit:
                outcome = "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP"
                resolution_index = index
                break
            if target_hit:
                outcome = "TARGET"
                resolution_index = index
                break
        require(outcome != "MONTH_END_OPEN", "Executable January swing remained unresolved")
        prior_to_resolution = future[:resolution_index]
        if direction == "LONG":
            mfe_price = max([0.0] + [float(row["high"]) - entry for row in prior_to_resolution])
        else:
            mfe_price = max([0.0] + [entry - float(row["low"]) for row in prior_to_resolution])
        later_target = False
        if outcome.startswith("STOP"):
            after_stop = future[resolution_index + 1 :]
            later_target = any(
                float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
                for row in after_stop
            )
        target_history = [
            row
            for row in h1_rows
            if parse_dt(str(row["open_at"])) > parse_dt(str(target_swing["pivot_at"]))
            and parse_dt(str(row["available_at"])) <= decision
        ]
        target_close_consumed = any(
            float(row["close"]) > target if direction == "LONG" else float(row["close"]) < target
            for row in target_history
        )
        h1_align = alignment(h1_swings, decision, direction)
        h4_align = alignment(h4_swings, decision, direction)
        trades.append(
            {
                "trade_identity": canonical_hash(["H1_SWING_ROTATION", swing["identity"], iso(decision), entry, stop, target]),
                "pivot_at": iso(str(swing["pivot_at"])),
                "decision_at": iso(decision),
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "target": target,
                "target_r": target_r,
                "outcome": outcome,
                "realized_r": target_r if outcome == "TARGET" else -1.0,
                "stopped_then_target": later_target,
                "mfe_before_stop_or_target_r": mfe_price / risk,
                "swing_relation": swing_relation(h1_swings, swing),
                "pivot_role": pivot_role(h1_swings, swing),
                "h1_external_alignment": h1_align,
                "h4_external_alignment": h4_align,
                "target_close_consumed_at_entry": target_close_consumed,
                "session": session_at(decision),
                "pivot_prominence_atr": float(swing["prominence_atr"]),
                "stop_distance_h1_atr": risk / float(swing["atr"]),
                "resolution_at": iso(str(future[resolution_index]["open_at"])),
            }
        )
        dispositions[outcome] += 1
    require(len(trades) == 88, f"Expected 88 executable trades, got {len(trades)}")
    require(sum(row["outcome"] == "TARGET" for row in trades) == 38, "Target count differs")
    require(sum(row["outcome"].startswith("STOP") for row in trades) == 50, "Stop count differs")
    losses = [row for row in trades if row["outcome"].startswith("STOP")]
    loss_mfe_buckets = Counter()
    for row in losses:
        mfe = float(row["mfe_before_stop_or_target_r"])
        bucket = "GE_1R" if mfe >= 1 else "0P5_TO_1R" if mfe >= 0.5 else "0P25_TO_0P5R" if mfe >= 0.25 else "LT_0P25R"
        loss_mfe_buckets[bucket] += 1
    control = metrics(trades)
    thresholds: dict[str, Any] = {}
    for label, floor in (("TARGET_R_GTE_1P5", 1.5), ("TARGET_R_GTE_2P0", 2.0)):
        admitted = [row for row in trades if float(row["target_r"]) >= floor]
        rejected = [row for row in trades if float(row["target_r"]) < floor]
        thresholds[label] = {
            **metrics(admitted),
            "floor_r": floor,
            "admitted_fraction": len(admitted) / len(trades),
            "winners_rejected": sum(row["outcome"] == "TARGET" for row in rejected),
            "winning_r_rejected": sum(float(row["realized_r"]) for row in rejected if row["outcome"] == "TARGET"),
            "losses_avoided": sum(row["outcome"].startswith("STOP") for row in rejected),
        }
    return {
        "population": {
            "january_local_h1_pivots": len(january),
            "executable": len(trades),
            "nonexecuted_dispositions": dict(sorted(dispositions.items())),
        },
        "control": control,
        "thresholds": thresholds,
        "loss_path": {
            "stops": len(losses),
            "stopped_then_target": sum(bool(row["stopped_then_target"]) for row in losses),
            "stopped_never_target": sum(not bool(row["stopped_then_target"]) for row in losses),
            "pre_stop_mfe_buckets": dict(sorted(loss_mfe_buckets.items())),
        },
        "entry_time_comparisons": {
            field: group_metrics(trades, field)
            for field in (
                "swing_relation",
                "pivot_role",
                "h1_external_alignment",
                "h4_external_alignment",
                "target_close_consumed_at_entry",
                "session",
            )
        },
        "trades": trades,
        "lineage_sha256": canonical_hash(lineage),
        "diagnostics_sha256": canonical_hash(diagnostics),
    }


def fmt(value: Any, digits: int = 2) -> str:
    return "n/a" if value is None or not math.isfinite(float(value)) else f"{float(value):.{digits}f}"


def main() -> None:
    for path in (SPEC, CERT):
        require(path.is_file(), f"Required input absent: {path}")
    OUT.mkdir(parents=True, exist_ok=True)
    primary = side("primary")
    reference = side("reference")
    comparable = ("population", "control", "thresholds", "loss_path", "entry_time_comparisons", "trades")
    require(all(primary[key] == reference[key] for key in comparable), "Primary/reference attribution differs")
    result = {
        "version": "GOLD_JANUARY_H1_SWING_LOSS_ATTRIBUTION_V1",
        "verdict": "PASS_EXPOSED_ATTRIBUTION_REPRODUCTION",
        "research_credit": "EXPOSED_JANUARY_DIAGNOSTIC_ONLY",
        **{key: primary[key] for key in comparable},
        "primary_lineage_sha256": primary["lineage_sha256"],
        "reference_lineage_sha256": reference["lineage_sha256"],
        "primary_reference_exact": True,
        "retuning_performed": False,
    }
    result["result_sha256"] = canonical_hash(result)
    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    rows = []
    for label, values in (("All executable", result["control"]), ("Target room >= 1.5R", result["thresholds"]["TARGET_R_GTE_1P5"]), ("Target room >= 2.0R", result["thresholds"]["TARGET_R_GTE_2P0"])):
        rows.append(
            f"| {label} | {values['support']} | {values['wins']} | {values['losses']} | {100*values['win_rate']:.1f}% | {values['net_r']:+.2f}R | {fmt(values['profit_factor'], 3)} | {values['expectancy_r']:+.3f}R |"
        )
    report = [
        "# January H1 swing loss attribution",
        "",
        "## Result",
        "",
        "| View | Trades | Wins | Stops | Win rate | Net gross | PF | Expectancy |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        "All figures are exposed January gross geometry before costs and overlap controls.",
        "",
        "## Stop-path diagnosis",
        "",
        f"- Stopped, then unchanged target reached later: **{result['loss_path']['stopped_then_target']}/50**.",
        f"- Stopped and target never reached by month-end: **{result['loss_path']['stopped_never_target']}/50**.",
        f"- Favorable movement before stop: `{json.dumps(result['loss_path']['pre_stop_mfe_buckets'], sort_keys=True)}`.",
        "",
        "## Threshold retention",
        "",
        f"- >=1.5R rejects {result['thresholds']['TARGET_R_GTE_1P5']['winners_rejected']} winners ({result['thresholds']['TARGET_R_GTE_1P5']['winning_r_rejected']:.2f}R) and avoids {result['thresholds']['TARGET_R_GTE_1P5']['losses_avoided']} losses.",
        f"- >=2.0R rejects {result['thresholds']['TARGET_R_GTE_2P0']['winners_rejected']} winners ({result['thresholds']['TARGET_R_GTE_2P0']['winning_r_rejected']:.2f}R) and avoids {result['thresholds']['TARGET_R_GTE_2P0']['losses_avoided']} losses.",
        "",
        "No admission or execution rule was changed.",
    ]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "version": "GOLD_JANUARY_H1_SWING_LOSS_ATTRIBUTION_V1_MANIFEST",
        "verdict": result["verdict"],
        "result_sha256": result["result_sha256"],
        "primary_reference_exact": True,
        "files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in (SPEC, RESULT, REPORT)
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "verdict": result["verdict"],
        "control": result["control"],
        "thresholds": result["thresholds"],
        "loss_path": result["loss_path"],
    }, indent=2))


if __name__ == "__main__":
    main()
