#!/usr/bin/env python3
"""Run the exposed January H1 probe-confirm-reclaim milestone."""

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
    TICK_FLOOR,
    canonical_hash,
    confirmed_swings,
    iso,
    parse_dt,
)
from render_gold_january_h1_continuous_swing_atlas_v1 import canonical_h1  # noqa: E402
from render_gold_january_h1_governed_trade_outcomes_v1 import canonical_rows  # noqa: E402
from run_gold_january_h1_swing_loss_attribution_v1 import CONFIRM_CUTOFF, END  # noqa: E402

SPEC = ROOT / "GOLD_JANUARY_H1_PROBE_CONFIRM_RECLAIM_MILESTONE_V1.md"
CERT = ROOT / "research_artifacts/gold_matched_human_replay_v1/stream_materialization_certification.json"
PRIOR_RESULT = ROOT / "research_artifacts/gold_january_h1_swing_loss_attribution_v1/attribution_result.json"
PRIOR_MANIFEST = ROOT / "research_artifacts/gold_january_h1_swing_loss_attribution_v1/manifest.json"
OUT = ROOT / "research_artifacts/gold_january_h1_probe_confirm_reclaim_v1"
PROOF = OUT / "synthetic_state_machine_proof.json"
RESULT = OUT / "result.json"
LEDGER = OUT / "case_ledger.csv"
REPORT = OUT / "report.md"
MANIFEST = OUT / "manifest.json"

PROBE_FRACTION = 0.25
ADD_FRACTION = 0.75
RECOVERY_BUFFER = 0.02
CONTROL_NET_R = 11.4687555
CONTROL_WINNER_R = 61.4687555


def beyond_control(close: float, level: float, direction: str) -> bool:
    return close > level if direction == "LONG" else close < level


def valid_side(close: float, swing: float, direction: str) -> bool:
    return close > swing if direction == "LONG" else close < swing


def h1_breached(close: float, swing: float, direction: str) -> bool:
    return close < swing if direction == "LONG" else close > swing


def valid_geometry(entry: float, stop: float, target: float, direction: str) -> bool:
    return stop < entry < target if direction == "LONG" else target < entry < stop


def signed_move(entry: float, exit_price: float, direction: str) -> float:
    return exit_price - entry if direction == "LONG" else entry - exit_price


def target_multiple(entry: float, stop: float, target: float) -> float:
    return abs(target - entry) / abs(entry - stop)


def latest_control(
    swings: Sequence[Mapping[str, Any]], cutoff: datetime, direction: str
) -> Mapping[str, Any] | None:
    kind = "HIGH" if direction == "LONG" else "LOW"
    eligible = [
        row
        for row in swings
        if str(row["kind"]) == kind and parse_dt(str(row["detected_at"])) <= cutoff
    ]
    return max(eligible, key=lambda row: (parse_dt(str(row["detected_at"])), str(row["identity"]))) if eligible else None


def first_confirmation(
    m5_rows: Sequence[Mapping[str, Any]],
    *,
    after: datetime,
    through: datetime,
    direction: str,
    control_level: float,
    required_valid_side: float | None = None,
) -> Mapping[str, Any] | None:
    for row in m5_rows:
        available = parse_dt(str(row["available_at"]))
        if row.get("complete") is not True or available <= after or available > through:
            continue
        close = float(row["close"])
        if not beyond_control(close, control_level, direction):
            continue
        if required_valid_side is not None and not valid_side(close, required_valid_side, direction):
            continue
        return row
    return None


def first_m1_at_or_after(
    rows: Sequence[Mapping[str, Any]], point: datetime
) -> Mapping[str, Any] | None:
    for row in rows:
        if row.get("complete") is True and parse_dt(str(row["open_at"])) >= point and parse_dt(str(row["available_at"])) <= END:
            return row
    return None


def first_target_after(
    rows: Sequence[Mapping[str, Any]],
    *,
    after: datetime,
    direction: str,
    target: float,
) -> datetime | None:
    for row in rows:
        opened = parse_dt(str(row["open_at"]))
        if opened <= after or parse_dt(str(row["available_at"])) > END:
            continue
        target_hit = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if target_hit:
            return opened
    return None


def first_h1_after(rows: Sequence[Mapping[str, Any]], point: datetime) -> Mapping[str, Any] | None:
    eligible = [
        row
        for row in rows
        if row.get("complete") is True and parse_dt(str(row["available_at"])) > point and parse_dt(str(row["available_at"])) <= END
    ]
    return min(eligible, key=lambda row: parse_dt(str(row["available_at"]))) if eligible else None


def first_h1_breach_after(
    rows: Sequence[Mapping[str, Any]], *, after: datetime, swing: float, direction: str
) -> datetime | None:
    for row in rows:
        available = parse_dt(str(row["available_at"]))
        if row.get("complete") is not True or available <= after or available > END:
            continue
        if h1_breached(float(row["close"]), swing, direction):
            return available
    return None


def confirmation_precedes_h1_breach(
    confirmation_at: datetime, breach_at: datetime | None
) -> bool:
    return breach_at is None or confirmation_at < breach_at


def resolve_path(
    rows: Sequence[Mapping[str, Any]],
    *,
    entry_at: datetime,
    entry: float,
    stop: float,
    target: float,
    direction: str,
) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if row.get("complete") is True and parse_dt(str(row["open_at"])) >= entry_at and parse_dt(str(row["available_at"])) <= END
    ]
    require(eligible, f"No M1 recovery path at {iso(entry_at)}")
    for row in eligible:
        stop_hit = float(row["low"]) <= stop if direction == "LONG" else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if stop_hit:
            return {"outcome": "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP", "at": iso(str(row["open_at"])), "raw_r": -1.0}
        if target_hit:
            return {"outcome": "TARGET", "at": iso(str(row["open_at"])), "raw_r": target_multiple(entry, stop, target)}
    final = eligible[-1]
    raw_r = signed_move(entry, float(final["close"]), direction) / abs(entry - stop)
    return {"outcome": "TIME_EXIT", "at": iso(str(final["available_at"])), "raw_r": raw_r}


def max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row["net_r"]) for row in rows]
    positive = sum(value for value in returns if value > 0)
    negative = -sum(value for value in returns if value < 0)
    winners = sum(value > 0 for value in returns)
    return {
        "cases": len(rows),
        "winning_cases": winners,
        "losing_cases": sum(value < 0 for value in returns),
        "flat_cases": sum(value == 0 for value in returns),
        "win_rate": winners / len(rows) if rows else None,
        "gross_positive_r": positive,
        "gross_negative_r": -negative,
        "net_r": sum(returns),
        "profit_factor": positive / negative if negative else None,
        "expectancy_r": sum(returns) / len(rows) if rows else None,
        "maximum_drawdown_r": max_drawdown(returns),
        "dollars_at_50_per_r": 50.0 * sum(returns),
    }


def synthetic_proof() -> dict[str, Any]:
    synthetic_m5 = [
        {"open_at": "2022-01-03T10:00:00Z", "available_at": "2022-01-03T10:05:00Z", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.9, "complete": True},
        {"open_at": "2022-01-03T10:05:00Z", "available_at": "2022-01-03T10:10:00Z", "open": 100.9, "high": 101.3, "low": 100.7, "close": 101.1, "complete": True},
    ]
    synthetic_m1 = [
        {"open_at": "2022-01-03T10:09:00Z", "available_at": "2022-01-03T10:10:00Z", "open": 101.0, "high": 101.1, "low": 100.9, "close": 101.0, "complete": True},
        {"open_at": "2022-01-03T10:10:00Z", "available_at": "2022-01-03T10:11:00Z", "open": 101.1, "high": 103.1, "low": 100.9, "close": 103.0, "complete": True},
    ]
    confirmation = first_confirmation(
        synthetic_m5,
        after=parse_dt("2022-01-03T10:00:00Z"),
        through=parse_dt("2022-01-03T10:10:00Z"),
        direction="LONG",
        control_level=101.0,
    )
    exact_entry = first_m1_at_or_after(synthetic_m1, parse_dt("2022-01-03T10:10:00Z"))
    target_resolution = resolve_path(
        synthetic_m1,
        entry_at=parse_dt("2022-01-03T10:10:00Z"),
        entry=101.1,
        stop=100.0,
        target=103.0,
        direction="LONG",
    )
    ambiguous_resolution = resolve_path(
        [
            {"open_at": "2022-01-03T11:00:00Z", "available_at": "2022-01-03T11:01:00Z", "open": 101.0, "high": 103.1, "low": 99.9, "close": 102.0, "complete": True},
        ],
        entry_at=parse_dt("2022-01-03T11:00:00Z"),
        entry=101.0,
        stop=100.0,
        target=103.0,
        direction="LONG",
    )
    checks = {
        "long_control_strict": beyond_control(101.0, 100.0, "LONG") and not beyond_control(100.0, 100.0, "LONG"),
        "short_control_strict": beyond_control(99.0, 100.0, "SHORT") and not beyond_control(100.0, 100.0, "SHORT"),
        "wick_not_close_breach_long": not h1_breached(100.1, 100.0, "LONG"),
        "wick_not_close_breach_short": not h1_breached(99.9, 100.0, "SHORT"),
        "close_breach_long": h1_breached(99.9, 100.0, "LONG"),
        "close_breach_short": h1_breached(100.1, 100.0, "SHORT"),
        "long_geometry": valid_geometry(101.0, 100.0, 103.0, "LONG"),
        "short_geometry": valid_geometry(99.0, 100.0, 97.0, "SHORT"),
        "risk_budget": math.isclose(PROBE_FRACTION + ADD_FRACTION, 1.0),
        "confirmed_stop_accounting": math.isclose(-PROBE_FRACTION - ADD_FRACTION, -1.0),
        "recovery_stop_accounting": math.isclose(-PROBE_FRACTION - ADD_FRACTION, -1.0),
        "target_multiple_long": math.isclose(target_multiple(101.0, 100.0, 103.0), 2.0),
        "target_multiple_short": math.isclose(target_multiple(99.0, 100.0, 97.0), 2.0),
        "buffer_frozen": math.isclose(RECOVERY_BUFFER, TICK_FLOOR),
        "confirmation_available_at_boundary": confirmation is not None and iso(str(confirmation["available_at"])) == "2022-01-03T10:10:00Z",
        "entry_uses_first_m1_at_boundary": exact_entry is not None and iso(str(exact_entry["open_at"])) == "2022-01-03T10:10:00Z",
        "target_first_passage": target_resolution["outcome"] == "TARGET" and target_resolution["at"] == "2022-01-03T10:10:00Z",
        "ambiguous_bar_is_stop_first": ambiguous_resolution["outcome"] == "STOP_FIRST_AMBIGUOUS" and math.isclose(float(ambiguous_resolution["raw_r"]), -1.0),
        "simultaneous_h1_breach_cancels_recovery": not confirmation_precedes_h1_breach(
            parse_dt("2022-01-03T12:00:00Z"), parse_dt("2022-01-03T12:00:00Z")
        ),
        "earlier_confirmation_precedes_h1_breach": confirmation_precedes_h1_breach(
            parse_dt("2022-01-03T11:55:00Z"), parse_dt("2022-01-03T12:00:00Z")
        ),
    }
    require(all(checks.values()), "Synthetic state-machine proof failed")
    payload = {"verdict": "PASS_SYNTHETIC_STATE_MACHINE_PROOF", "checks": checks}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def load_prior() -> tuple[dict[str, Any], str]:
    for path in (SPEC, CERT, PRIOR_RESULT, PRIOR_MANIFEST):
        require(path.is_file(), f"Required input absent: {path}")
    manifest = json.loads(PRIOR_MANIFEST.read_text(encoding="utf-8"))
    expected = next(row["sha256"] for row in manifest["files"] if str(row["path"]).endswith("attribution_result.json"))
    require(sha256_file(PRIOR_RESULT) == expected, "Prior attribution seal mismatch")
    prior = json.loads(PRIOR_RESULT.read_text(encoding="utf-8"))
    require(prior["verdict"] == "PASS_EXPOSED_ATTRIBUTION_REPRODUCTION", "Prior attribution verdict is not PASS")
    require(len(prior["trades"]) == 88, "Prior population is not 88")
    require(math.isclose(float(prior["control"]["net_r"]), CONTROL_NET_R, rel_tol=0.0, abs_tol=1e-7), "Control R differs")
    return prior, expected


def build(side_name: str, prior: Mapping[str, Any]) -> dict[str, Any]:
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
    ledger: list[dict[str, Any]] = []
    for trade in sorted(prior["trades"], key=lambda row: (parse_dt(str(row["decision_at"])), str(row["trade_identity"]))):
        direction = str(trade["direction"])
        decision = parse_dt(str(trade["decision_at"]))
        resolution = parse_dt(str(trade["resolution_at"]))
        entry = float(trade["entry"])
        swing = float(trade["stop"])
        target = float(trade["target"])
        baseline_r = float(trade["realized_r"])
        control = latest_control(m5_swings, decision, direction)
        initial_confirmation = (
            first_confirmation(
                m5_rows,
                after=decision,
                through=resolution,
                direction=direction,
                control_level=float(control["level"]),
            )
            if control is not None
            else None
        )
        addition_entry_row = (
            first_m1_at_or_after(m1_rows, parse_dt(str(initial_confirmation["available_at"])))
            if initial_confirmation is not None
            else None
        )
        addition_valid = bool(
            addition_entry_row is not None
            and parse_dt(str(addition_entry_row["open_at"])) <= resolution
            and valid_geometry(float(addition_entry_row["open"]), swing, target, direction)
        )

        route = ""
        net_r = 0.0
        addition_r = 0.0
        recovery_r = 0.0
        recovery_entry_at: str | None = None
        recovery_stop: float | None = None
        recovery_outcome: str | None = None
        recovery_resolution_at: str | None = None
        h1_review_at: str | None = None

        if str(trade["outcome"]) == "TARGET":
            probe_r = PROBE_FRACTION * float(trade["target_r"])
            if addition_valid:
                add_entry = float(addition_entry_row["open"])
                addition_r = ADD_FRACTION * target_multiple(add_entry, swing, target)
                net_r = probe_r + addition_r
                route = "CONFIRMED_ADDITION_TARGET"
            else:
                net_r = probe_r
                route = "PROBE_ONLY_TARGET"
        else:
            probe_r = -PROBE_FRACTION
            if addition_valid:
                addition_r = -ADD_FRACTION
                net_r = -1.0
                route = "CONFIRMED_ADDITION_STOP"
            else:
                net_r = probe_r
                later_target_at = first_target_after(m1_rows, after=resolution, direction=direction, target=target)
                h1_review = first_h1_after(h1_rows, resolution)
                if h1_review is None:
                    route = "PROBE_STOP_NO_H1_REVIEW"
                else:
                    h1_review_time = parse_dt(str(h1_review["available_at"]))
                    h1_review_at = iso(h1_review_time)
                    if later_target_at is not None and later_target_at < h1_review_time:
                        route = "PROBE_STOP_TARGET_BEFORE_H1_REVIEW"
                    elif h1_breached(float(h1_review["close"]), swing, direction):
                        route = "PROBE_STOP_H1_CLOSE_INVALIDATED"
                    else:
                        recovery_control = latest_control(m5_swings, h1_review_time, direction)
                        next_breach_at = first_h1_breach_after(h1_rows, after=h1_review_time, swing=swing, direction=direction)
                        cancellation_points = [END]
                        if later_target_at is not None:
                            cancellation_points.append(later_target_at)
                        if next_breach_at is not None:
                            cancellation_points.append(next_breach_at)
                        recovery_deadline = min(cancellation_points)
                        recovery_confirmation = (
                            first_confirmation(
                                m5_rows,
                                after=h1_review_time,
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
                            route = "PROBE_STOP_NO_RECOVERY_CONTROL"
                        elif recovery_confirmation is None:
                            if later_target_at is not None and later_target_at <= recovery_deadline:
                                route = "PROBE_STOP_TARGET_BEFORE_RECOVERY"
                            elif next_breach_at is not None and next_breach_at <= recovery_deadline:
                                route = "PROBE_STOP_LATER_H1_INVALIDATED"
                            else:
                                route = "PROBE_STOP_NO_RECOVERY_CONFIRMATION"
                        else:
                            confirmation_at = parse_dt(str(recovery_confirmation["available_at"]))
                            recovery_entry_row = first_m1_at_or_after(m1_rows, confirmation_at)
                            require(recovery_entry_row is not None, f"No recovery entry row for {trade['trade_identity']}")
                            excursion_rows = [
                                row
                                for row in m1_rows
                                if row.get("complete") is True
                                and parse_dt(str(row["open_at"])) >= resolution
                                and parse_dt(str(row["available_at"])) <= confirmation_at
                            ]
                            require(excursion_rows, f"No recovery excursion rows for {trade['trade_identity']}")
                            recovery_stop = (
                                min(float(row["low"]) for row in excursion_rows) - RECOVERY_BUFFER
                                if direction == "LONG"
                                else max(float(row["high"]) for row in excursion_rows) + RECOVERY_BUFFER
                            )
                            recovery_entry = float(recovery_entry_row["open"])
                            if not valid_geometry(recovery_entry, recovery_stop, target, direction):
                                route = "PROBE_STOP_RECOVERY_GEOMETRY_INVALID"
                            else:
                                recovery_entry_time = parse_dt(str(recovery_entry_row["open_at"]))
                                recovery_entry_at = iso(recovery_entry_time)
                                recovered = resolve_path(
                                    m1_rows,
                                    entry_at=recovery_entry_time,
                                    entry=recovery_entry,
                                    stop=recovery_stop,
                                    target=target,
                                    direction=direction,
                                )
                                recovery_outcome = str(recovered["outcome"])
                                recovery_resolution_at = str(recovered["at"])
                                recovery_r = ADD_FRACTION * float(recovered["raw_r"])
                                net_r = probe_r + recovery_r
                                route = f"RECOVERY_{recovery_outcome}"

        require(net_r >= -1.0000000001, f"Risk cap breached for {trade['trade_identity']}: {net_r}")
        ledger.append(
            {
                "trade_identity": str(trade["trade_identity"]),
                "decision_at": iso(decision),
                "direction": direction,
                "baseline_outcome": str(trade["outcome"]),
                "baseline_r": baseline_r,
                "route": route,
                "initial_control_identity": str(control["identity"]) if control is not None else None,
                "initial_confirmation_at": iso(str(initial_confirmation["available_at"])) if initial_confirmation is not None else None,
                "addition_entry_at": iso(str(addition_entry_row["open_at"])) if addition_valid else None,
                "h1_review_at": h1_review_at,
                "recovery_entry_at": recovery_entry_at,
                "recovery_stop": recovery_stop,
                "recovery_outcome": recovery_outcome,
                "recovery_resolution_at": recovery_resolution_at,
                "probe_r": probe_r,
                "addition_r": addition_r,
                "recovery_r": recovery_r,
                "net_r": net_r,
                "delta_vs_control_r": net_r - baseline_r,
            }
        )

    require(len(ledger) == 88, f"Expected 88 cases, got {len(ledger)}")
    result_metrics = metrics(ledger)
    baseline_winners = [row for row in ledger if float(row["baseline_r"]) > 0]
    retained_from_baseline_winners = sum(float(row["net_r"]) for row in baseline_winners)
    positive_deltas = sorted((float(row["delta_vs_control_r"]) for row in ledger if float(row["delta_vs_control_r"]) > 0), reverse=True)
    increment = result_metrics["net_r"] - CONTROL_NET_R
    return {
        "metrics": result_metrics,
        "route_counts": dict(sorted(Counter(str(row["route"]) for row in ledger).items())),
        "baseline_winner_r_retained": retained_from_baseline_winners,
        "baseline_winner_r_retention_fraction": retained_from_baseline_winners / CONTROL_WINNER_R,
        "increment_vs_control_r": increment,
        "largest_positive_case_delta_r": positive_deltas[0] if positive_deltas else 0.0,
        "largest_positive_case_share_of_increment": positive_deltas[0] / increment if positive_deltas and increment > 0 else None,
        "ledger": ledger,
        "lineage_sha256": canonical_hash(lineage),
        "diagnostics_sha256": canonical_hash(diagnostics),
    }


def format_number(value: Any, digits: int = 3) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def main() -> None:
    prior, prior_sha = load_prior()
    OUT.mkdir(parents=True, exist_ok=True)
    proof = synthetic_proof()
    PROOF.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    primary = build("primary", prior)
    reference = build("reference", prior)
    comparable = (
        "metrics", "route_counts", "baseline_winner_r_retained", "baseline_winner_r_retention_fraction",
        "increment_vs_control_r", "largest_positive_case_delta_r", "largest_positive_case_share_of_increment", "ledger",
    )
    require(all(primary[key] == reference[key] for key in comparable), "Primary/reference milestone result differs")
    improved = float(primary["increment_vs_control_r"]) > 0
    not_one_case = primary["largest_positive_case_share_of_increment"] is None or float(primary["largest_positive_case_share_of_increment"]) < 1.0
    verdict = "PASS_EXPOSED_MATCHED_GROSS_IMPROVEMENT" if improved and not_one_case else "REJECT_EXPOSED_MATCHED_GROSS_IMPROVEMENT"
    result = {
        "version": "GOLD_JANUARY_H1_PROBE_CONFIRM_RECLAIM_MILESTONE_V1",
        "verdict": verdict,
        "research_credit": "EXPOSED_JANUARY_ENGINEERING_AND_DIAGNOSTIC_ONLY",
        "synthetic_proof_verdict": proof["verdict"],
        "prior_attribution_sha256": prior_sha,
        "control": {
            "cases": 88,
            "net_r": CONTROL_NET_R,
            "winner_r": CONTROL_WINNER_R,
            "maximum_drawdown_r": max_drawdown([float(row["baseline_r"]) for row in primary["ledger"]]),
            "dollars_at_50_per_r": CONTROL_NET_R * 50.0,
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

    fields = list(result["case_ledger"][0].keys())
    with LEDGER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["case_ledger"])

    metrics_out = result["metrics"]
    report = [
        "# Gold January H1 probe-confirm-reclaim milestone V1",
        "",
        f"**Verdict:** `{verdict}`",
        "",
        "## Matched exposed-January comparison",
        "",
        "| System | Cases | Wins | Win rate | Net R | PF | Expectancy | Max DD | $ at $50/R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| Original control | 88 | 38 | 43.2% | {CONTROL_NET_R:+.2f} | 1.229 | +0.130 | {result['control']['maximum_drawdown_r']:.2f} | {CONTROL_NET_R * 50:+.2f} |",
        f"| Probe-confirm-reclaim | {metrics_out['cases']} | {metrics_out['winning_cases']} | {100*metrics_out['win_rate']:.1f}% | {metrics_out['net_r']:+.2f} | {format_number(metrics_out['profit_factor'])} | {metrics_out['expectancy_r']:+.3f} | {metrics_out['maximum_drawdown_r']:.2f} | {metrics_out['dollars_at_50_per_r']:+.2f} |",
        "",
        f"Increment versus matched control: **{result['increment_vs_control_r']:+.2f}R**.",
        f"Baseline winner R retained: **{result['baseline_winner_r_retained']:.2f}/{CONTROL_WINNER_R:.2f}R ({100*result['baseline_winner_r_retention_fraction']:.1f}%)**.",
        "",
        "## Route counts",
        "",
        "| Route | Cases |",
        "|---|---:|",
        *[f"| {key} | {value} |" for key, value in sorted(result["route_counts"].items())],
        "",
        "The comparison is gross, matched-population and exposed. Costs, overlap and whole-ounce sizing remain outside both sides of this isolated test.",
        "No threshold or alternative implementation was tested after outcomes were opened.",
    ]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")

    sealed = (SPEC, Path(__file__).resolve(), PRIOR_RESULT, PROOF, RESULT, LEDGER, REPORT)
    manifest = {
        "version": "GOLD_JANUARY_H1_PROBE_CONFIRM_RECLAIM_MILESTONE_V1_MANIFEST",
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
        "control_net_r": CONTROL_NET_R,
        "metrics": metrics_out,
        "increment_vs_control_r": result["increment_vs_control_r"],
        "winner_retention_fraction": result["baseline_winner_r_retention_fraction"],
        "route_counts": result["route_counts"],
    }, indent=2))


if __name__ == "__main__":
    main()
