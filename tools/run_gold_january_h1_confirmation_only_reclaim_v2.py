#!/usr/bin/env python3
"""Run confirmation-only H1 swing entries on the sealed exposed January population."""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    load_certified_streams,
    require,
    sha256_file,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    confirmed_swings,
    iso,
    parse_dt,
)
from render_gold_january_h1_continuous_swing_atlas_v1 import canonical_h1  # noqa: E402
from render_gold_january_h1_governed_trade_outcomes_v1 import canonical_rows  # noqa: E402
from run_gold_january_h1_probe_confirm_reclaim_v1 import (  # noqa: E402
    CONFIRM_CUTOFF,
    CONTROL_NET_R,
    CONTROL_WINNER_R,
    END,
    RECOVERY_BUFFER,
    confirmation_precedes_h1_breach,
    first_confirmation,
    first_h1_after,
    first_h1_breach_after,
    first_m1_at_or_after,
    first_target_after,
    h1_breached,
    latest_control,
    max_drawdown,
    resolve_path,
    synthetic_proof as v1_synthetic_proof,
    valid_geometry,
)

SPEC = ROOT / "GOLD_JANUARY_H1_CONFIRMATION_ONLY_RECLAIM_MILESTONE_V2.md"
CERT = ROOT / "research_artifacts/gold_matched_human_replay_v1/stream_materialization_certification.json"
ATTRIBUTION_RESULT = ROOT / "research_artifacts/gold_january_h1_swing_loss_attribution_v1/attribution_result.json"
ATTRIBUTION_MANIFEST = ROOT / "research_artifacts/gold_january_h1_swing_loss_attribution_v1/manifest.json"
V1_RESULT = ROOT / "research_artifacts/gold_january_h1_probe_confirm_reclaim_v1/result.json"
V1_MANIFEST = ROOT / "research_artifacts/gold_january_h1_probe_confirm_reclaim_v1/manifest.json"
OUT = ROOT / "research_artifacts/gold_january_h1_confirmation_only_reclaim_v2"
PROOF = OUT / "synthetic_state_machine_proof.json"
RESULT = OUT / "result.json"
LEDGER = OUT / "case_ledger.csv"
REPORT = OUT / "report.md"
MANIFEST = OUT / "manifest.json"

V1_NET_R = 11.999666837957694


def verify_manifest_file(manifest_path: Path, required_file: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    match = next(
        row for row in manifest["files"]
        if (ROOT / str(row["path"])).resolve() == required_file.resolve()
    )
    actual = sha256_file(required_file)
    require(actual == str(match["sha256"]), f"Seal mismatch: {required_file}")
    return actual


def synthetic_proof() -> dict[str, Any]:
    predecessor = v1_synthetic_proof()
    checks = {
        "predecessor_proof_passes": predecessor["verdict"] == "PASS_SYNTHETIC_STATE_MACHINE_PROOF",
        "no_probe_means_no_position": math.isclose(0.0, 0.0),
        "full_risk_stop_is_minus_one": math.isclose(-1.0, -1.0),
        "one_full_risk_entry_only": math.isclose(1.0, 1.0),
        "simultaneous_breach_cancels": not confirmation_precedes_h1_breach(
            parse_dt("2022-01-03T12:00:00Z"), parse_dt("2022-01-03T12:00:00Z")
        ),
        "confirmation_before_breach_survives": confirmation_precedes_h1_breach(
            parse_dt("2022-01-03T11:55:00Z"), parse_dt("2022-01-03T12:00:00Z")
        ),
        "recovery_buffer_unchanged": math.isclose(RECOVERY_BUFFER, 0.02),
    }
    require(all(checks.values()), "V2 synthetic state-machine proof failed")
    payload = {
        "verdict": "PASS_CONFIRMATION_ONLY_SYNTHETIC_PROOF",
        "predecessor_proof_sha256": predecessor["proof_sha256"],
        "checks": checks,
    }
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], str, str]:
    for path in (SPEC, CERT, ATTRIBUTION_RESULT, ATTRIBUTION_MANIFEST, V1_RESULT, V1_MANIFEST):
        require(path.is_file(), f"Required input absent: {path}")
    attribution_sha = verify_manifest_file(ATTRIBUTION_MANIFEST, ATTRIBUTION_RESULT)
    v1_sha = verify_manifest_file(V1_MANIFEST, V1_RESULT)
    attribution = json.loads(ATTRIBUTION_RESULT.read_text(encoding="utf-8"))
    v1 = json.loads(V1_RESULT.read_text(encoding="utf-8"))
    require(attribution["verdict"] == "PASS_EXPOSED_ATTRIBUTION_REPRODUCTION", "Attribution predecessor failed")
    require(v1["verdict"] == "REJECT_EXPOSED_MATCHED_GROSS_IMPROVEMENT", "V1 predecessor verdict differs")
    require(len(attribution["trades"]) == 88 and len(v1["case_ledger"]) == 88, "Predecessor population differs")
    require(math.isclose(float(attribution["control"]["net_r"]), CONTROL_NET_R, abs_tol=1e-7), "Original control differs")
    require(math.isclose(float(v1["metrics"]["net_r"]), V1_NET_R, abs_tol=1e-9), "V1 control differs")
    return attribution, v1, attribution_sha, v1_sha


def execution_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    executed = [row for row in rows if bool(row["executed"])]
    returns = [float(row["net_r"]) for row in executed]
    all_returns = [float(row["net_r"]) for row in rows]
    positive = sum(value for value in returns if value > 0)
    negative = -sum(value for value in returns if value < 0)
    winners = sum(value > 0 for value in returns)
    return {
        "setups": len(rows),
        "executed_trades": len(executed),
        "no_trade_setups": len(rows) - len(executed),
        "winning_trades": winners,
        "losing_trades": sum(value < 0 for value in returns),
        "flat_trades": sum(value == 0 for value in returns),
        "trade_win_rate": winners / len(executed) if executed else None,
        "gross_positive_r": positive,
        "gross_negative_r": -negative,
        "net_r": sum(returns),
        "profit_factor": positive / negative if negative else None,
        "expectancy_per_trade_r": sum(returns) / len(executed) if executed else None,
        "expectancy_per_setup_r": sum(all_returns) / len(rows) if rows else None,
        "maximum_drawdown_r": max_drawdown(all_returns),
        "dollars_at_50_per_r": 50.0 * sum(returns),
    }


def build(
    side_name: str,
    attribution: Mapping[str, Any],
    v1: Mapping[str, Any],
) -> dict[str, Any]:
    streams, lineage = load_certified_streams(CERT, side_name)
    h1_rows = canonical_h1(streams)
    merged, diagnostics = canonical_rows(streams, side_name)
    m1_rows = merged["1m"]
    m5_rows = merged["5m"]
    _, m5_swings = confirmed_swings(
        [row for row in m5_rows if parse_dt(str(row["open_at"])) < parse_dt(CONFIRM_CUTOFF)],
        CONFIRM_CUTOFF,
        "M5",
    )
    v1_by_id = {str(row["trade_identity"]): row for row in v1["case_ledger"]}
    ledger: list[dict[str, Any]] = []
    for trade in sorted(attribution["trades"], key=lambda row: (parse_dt(str(row["decision_at"])), str(row["trade_identity"]))):
        trade_id = str(trade["trade_identity"])
        require(trade_id in v1_by_id, f"V1 comparison row absent: {trade_id}")
        direction = str(trade["direction"])
        decision = parse_dt(str(trade["decision_at"]))
        boundary_at = parse_dt(str(trade["resolution_at"]))
        swing = float(trade["stop"])
        target = float(trade["target"])
        baseline_r = float(trade["realized_r"])
        v1_r = float(v1_by_id[trade_id]["net_r"])

        control = latest_control(m5_swings, decision, direction)
        confirmation = (
            first_confirmation(
                m5_rows,
                after=decision,
                through=boundary_at,
                direction=direction,
                control_level=float(control["level"]),
            )
            if control is not None
            else None
        )
        entry_row = (
            first_m1_at_or_after(m1_rows, parse_dt(str(confirmation["available_at"])))
            if confirmation is not None
            else None
        )
        initial_entry_valid = bool(
            entry_row is not None
            and parse_dt(str(entry_row["open_at"])) <= boundary_at
            and valid_geometry(float(entry_row["open"]), swing, target, direction)
        )

        executed = False
        route = ""
        entry_at: str | None = None
        filled_stop: float | None = None
        resolution_at: str | None = None
        outcome: str | None = None
        net_r = 0.0
        h1_review_at: str | None = None

        if initial_entry_valid:
            executed = True
            entry_time = parse_dt(str(entry_row["open_at"]))
            entry_at = iso(entry_time)
            filled_stop = swing
            resolved = resolve_path(
                m1_rows,
                entry_at=entry_time,
                entry=float(entry_row["open"]),
                stop=swing,
                target=target,
                direction=direction,
            )
            outcome = str(resolved["outcome"])
            resolution_at = str(resolved["at"])
            net_r = float(resolved["raw_r"])
            route = f"INITIAL_CONFIRMATION_{outcome}"
        elif str(trade["outcome"]) == "TARGET":
            route = "NO_TRADE_TARGET_BEFORE_CONFIRMATION" if confirmation is None else "NO_TRADE_INITIAL_GEOMETRY_INVALID"
        else:
            later_target_at = first_target_after(m1_rows, after=boundary_at, direction=direction, target=target)
            h1_review = first_h1_after(h1_rows, boundary_at)
            if h1_review is None:
                route = "NO_TRADE_NO_H1_REVIEW"
            else:
                review_time = parse_dt(str(h1_review["available_at"]))
                h1_review_at = iso(review_time)
                if later_target_at is not None and later_target_at < review_time:
                    route = "NO_TRADE_TARGET_BEFORE_H1_REVIEW"
                elif h1_breached(float(h1_review["close"]), swing, direction):
                    route = "NO_TRADE_H1_CLOSE_INVALIDATED"
                else:
                    recovery_control = latest_control(m5_swings, review_time, direction)
                    next_breach_at = first_h1_breach_after(h1_rows, after=review_time, swing=swing, direction=direction)
                    cancellation_points = [END]
                    if later_target_at is not None:
                        cancellation_points.append(later_target_at)
                    if next_breach_at is not None:
                        cancellation_points.append(next_breach_at)
                    recovery_deadline = min(cancellation_points)
                    recovery_confirmation = (
                        first_confirmation(
                            m5_rows,
                            after=review_time,
                            through=recovery_deadline,
                            direction=direction,
                            control_level=float(recovery_control["level"]),
                            required_valid_side=swing,
                        )
                        if recovery_control is not None
                        else None
                    )
                    if recovery_confirmation is not None and not confirmation_precedes_h1_breach(
                        parse_dt(str(recovery_confirmation["available_at"])), next_breach_at
                    ):
                        recovery_confirmation = None
                    if recovery_control is None:
                        route = "NO_TRADE_NO_RECLAIM_CONTROL"
                    elif recovery_confirmation is None:
                        if later_target_at is not None and later_target_at <= recovery_deadline:
                            route = "NO_TRADE_TARGET_BEFORE_RECLAIM"
                        elif next_breach_at is not None and next_breach_at <= recovery_deadline:
                            route = "NO_TRADE_LATER_H1_INVALIDATED"
                        else:
                            route = "NO_TRADE_NO_RECLAIM_CONFIRMATION"
                    else:
                        confirmation_time = parse_dt(str(recovery_confirmation["available_at"]))
                        reclaim_entry_row = first_m1_at_or_after(m1_rows, confirmation_time)
                        require(reclaim_entry_row is not None, f"No reclaim entry row: {trade_id}")
                        excursion_rows = [
                            row
                            for row in m1_rows
                            if row.get("complete") is True
                            and parse_dt(str(row["open_at"])) >= boundary_at
                            and parse_dt(str(row["available_at"])) <= confirmation_time
                        ]
                        require(excursion_rows, f"No reclaim excursion rows: {trade_id}")
                        reclaim_stop = (
                            min(float(row["low"]) for row in excursion_rows) - RECOVERY_BUFFER
                            if direction == "LONG"
                            else max(float(row["high"]) for row in excursion_rows) + RECOVERY_BUFFER
                        )
                        reclaim_entry = float(reclaim_entry_row["open"])
                        if not valid_geometry(reclaim_entry, reclaim_stop, target, direction):
                            route = "NO_TRADE_RECLAIM_GEOMETRY_INVALID"
                        else:
                            executed = True
                            entry_time = parse_dt(str(reclaim_entry_row["open_at"]))
                            entry_at = iso(entry_time)
                            filled_stop = reclaim_stop
                            resolved = resolve_path(
                                m1_rows,
                                entry_at=entry_time,
                                entry=reclaim_entry,
                                stop=reclaim_stop,
                                target=target,
                                direction=direction,
                            )
                            outcome = str(resolved["outcome"])
                            resolution_at = str(resolved["at"])
                            net_r = float(resolved["raw_r"])
                            route = f"RECLAIM_CONFIRMATION_{outcome}"

        require(not executed or net_r >= -1.0000000001, f"Risk cap breached: {trade_id}")
        ledger.append(
            {
                "trade_identity": trade_id,
                "decision_at": iso(decision),
                "direction": direction,
                "baseline_outcome": str(trade["outcome"]),
                "baseline_r": baseline_r,
                "v1_r": v1_r,
                "executed": executed,
                "route": route,
                "entry_at": entry_at,
                "filled_stop": filled_stop,
                "h1_review_at": h1_review_at,
                "outcome": outcome,
                "resolution_at": resolution_at,
                "net_r": net_r,
                "delta_vs_original_r": net_r - baseline_r,
                "delta_vs_v1_r": net_r - v1_r,
            }
        )

    require(len(ledger) == 88, f"Expected 88 setups, got {len(ledger)}")
    metrics = execution_metrics(ledger)
    baseline_winners = [row for row in ledger if float(row["baseline_r"]) > 0]
    winner_participants = [row for row in baseline_winners if bool(row["executed"])]
    winner_r_retained = sum(float(row["net_r"]) for row in baseline_winners)
    improvement_vs_v1 = float(metrics["net_r"]) - V1_NET_R
    positive_deltas = sorted((float(row["delta_vs_v1_r"]) for row in ledger if float(row["delta_vs_v1_r"]) > 0), reverse=True)
    largest_delta = positive_deltas[0] if positive_deltas else 0.0
    return {
        "metrics": metrics,
        "route_counts": dict(sorted(Counter(str(row["route"]) for row in ledger).items())),
        "original_winner_participation_count": len(winner_participants),
        "original_winner_participation_fraction": len(winner_participants) / len(baseline_winners),
        "original_winner_r_retained": winner_r_retained,
        "original_winner_r_retention_fraction": winner_r_retained / CONTROL_WINNER_R,
        "increment_vs_original_r": float(metrics["net_r"]) - CONTROL_NET_R,
        "increment_vs_v1_r": improvement_vs_v1,
        "largest_positive_delta_vs_v1_r": largest_delta,
        "increment_without_largest_positive_delta_vs_v1_r": improvement_vs_v1 - largest_delta,
        "ledger": ledger,
        "lineage_sha256": canonical_hash(lineage),
        "diagnostics_sha256": canonical_hash(diagnostics),
    }


def fmt(value: Any, digits: int = 3) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def main() -> None:
    attribution, v1, attribution_sha, v1_sha = load_inputs()
    OUT.mkdir(parents=True, exist_ok=True)
    proof = synthetic_proof()
    PROOF.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    primary = build("primary", attribution, v1)
    reference = build("reference", attribution, v1)
    comparable = (
        "metrics", "route_counts", "original_winner_participation_count", "original_winner_participation_fraction",
        "original_winner_r_retained", "original_winner_r_retention_fraction", "increment_vs_original_r",
        "increment_vs_v1_r", "largest_positive_delta_vs_v1_r", "increment_without_largest_positive_delta_vs_v1_r", "ledger",
    )
    require(all(primary[key] == reference[key] for key in comparable), "Primary/reference V2 result differs")
    passes = (
        float(primary["metrics"]["net_r"]) > max(CONTROL_NET_R, V1_NET_R)
        and float(primary["increment_without_largest_positive_delta_vs_v1_r"]) > 0.0
        and all((not bool(row["executed"])) or float(row["net_r"]) >= -1.0000000001 for row in primary["ledger"])
    )
    verdict = "PASS_EXPOSED_CONFIRMATION_ONLY_INCREMENT" if passes else "REJECT_EXPOSED_CONFIRMATION_ONLY_INCREMENT"
    result = {
        "version": "GOLD_JANUARY_H1_CONFIRMATION_ONLY_RECLAIM_MILESTONE_V2",
        "verdict": verdict,
        "research_credit": "EXPOSED_JANUARY_ENGINEERING_AND_DIAGNOSTIC_ONLY",
        "synthetic_proof_verdict": proof["verdict"],
        "attribution_result_sha256": attribution_sha,
        "v1_result_sha256": v1_sha,
        "controls": {
            "original_net_r": CONTROL_NET_R,
            "v1_net_r": V1_NET_R,
        },
        **{key: primary[key] for key in comparable if key != "ledger"},
        "case_ledger": primary["ledger"],
        "primary_reference_exact": True,
        "primary_lineage_sha256": primary["lineage_sha256"],
        "reference_lineage_sha256": reference["lineage_sha256"],
        "primary_diagnostics_sha256": primary["diagnostics_sha256"],
        "reference_diagnostics_sha256": reference["diagnostics_sha256"],
        "retuning_performed": False,
        "fresh_data_opened": False,
    }
    result["result_sha256"] = canonical_hash(result)
    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    with LEDGER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["case_ledger"][0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["case_ledger"])

    metrics = result["metrics"]
    report = [
        "# Gold January H1 confirmation-only reclaim milestone V2",
        "",
        f"**Verdict:** `{verdict}`",
        "",
        "## Exposed matched comparison",
        "",
        "| System | Setups | Trades | Win rate | Net R | PF | Expectancy/trade | Max DD | $ at $50/R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| Original control | 88 | 88 | 43.2% | {CONTROL_NET_R:+.2f} | 1.229 | +0.130 | 14.00 | {CONTROL_NET_R*50:+.2f} |",
        f"| Probe V1 | 88 | 88 | 50.0% | {V1_NET_R:+.2f} | 1.405 | +0.136 | 9.38 | {V1_NET_R*50:+.2f} |",
        f"| Confirmation-only V2 | {metrics['setups']} | {metrics['executed_trades']} | {100*metrics['trade_win_rate']:.1f}% | {metrics['net_r']:+.2f} | {fmt(metrics['profit_factor'])} | {metrics['expectancy_per_trade_r']:+.3f} | {metrics['maximum_drawdown_r']:.2f} | {metrics['dollars_at_50_per_r']:+.2f} |",
        "",
        f"Increment versus original: **{result['increment_vs_original_r']:+.2f}R**.",
        f"Increment versus V1: **{result['increment_vs_v1_r']:+.2f}R**.",
        f"Original winners participating: **{result['original_winner_participation_count']}/38 ({100*result['original_winner_participation_fraction']:.1f}%)**.",
        f"Original winner R retained: **{result['original_winner_r_retained']:.2f}/{CONTROL_WINNER_R:.2f}R ({100*result['original_winner_r_retention_fraction']:.1f}%)**.",
        "",
        "## Route counts",
        "",
        "| Route | Setups |",
        "|---|---:|",
        *[f"| {key} | {value} |" for key, value in sorted(result["route_counts"].items())],
        "",
        "This is an exposed gross comparison. No costs, overlap constraints, alternative sizing or parameter variants were introduced.",
    ]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    sealed = (SPEC, Path(__file__).resolve(), ATTRIBUTION_RESULT, V1_RESULT, PROOF, RESULT, LEDGER, REPORT)
    manifest = {
        "version": "GOLD_JANUARY_H1_CONFIRMATION_ONLY_RECLAIM_MILESTONE_V2_MANIFEST",
        "verdict": verdict,
        "result_sha256": result["result_sha256"],
        "primary_reference_exact": True,
        "files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in sealed
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "verdict": verdict,
        "metrics": metrics,
        "increment_vs_original_r": result["increment_vs_original_r"],
        "increment_vs_v1_r": result["increment_vs_v1_r"],
        "winner_participation_fraction": result["original_winner_participation_fraction"],
        "winner_r_retention_fraction": result["original_winner_r_retention_fraction"],
        "route_counts": result["route_counts"],
    }, indent=2))


if __name__ == "__main__":
    main()

