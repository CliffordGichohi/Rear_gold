#!/usr/bin/env python3
"""Attribute sealed Mar-May coherent-auction wins and losses without retuning."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    parse_dt,
)


PROTOCOL = ROOT / "GOLD_COHERENT_AUCTION_MAR_MAY_2022_OUTCOME_ATTRIBUTION_V1.md"
AMENDMENT = ROOT / "GOLD_COHERENT_AUCTION_MAR_MAY_2022_OUTCOME_ATTRIBUTION_V1_AMENDMENT_A.md"
SOURCE_ROOT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_consecutive_months_mar_may_2022_v1"
)
SOURCE_RESULT = SOURCE_ROOT / "final_result.json"
SOURCE_SEAL = SOURCE_ROOT / "final_seal.json"
PRIMARY_STREAM = SOURCE_ROOT / "daily_streams.primary.jsonl.gz"
REFERENCE_STREAM = SOURCE_ROOT / "daily_streams.reference.jsonl.gz"
PRESERVED_OUT = ROOT / "research_artifacts" / "gold_coherent_auction_mar_may_2022_outcome_attribution_v1"
PRESERVED_SEAL = PRESERVED_OUT / "final_seal.json"
PRESERVED_RESULT = PRESERVED_OUT / "final_result.json"
OUT = ROOT / "research_artifacts" / "gold_coherent_auction_mar_may_2022_outcome_attribution_v1_r1"
PRIMARY = OUT / "attribution.primary.json"
REFERENCE = OUT / "attribution.reference.json"
RESULT = OUT / "final_result.json"
SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_COHERENT_AUCTION_MAR_MAY_2022_OUTCOME_ATTRIBUTION_V1_R1_REPORT.md"

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
WIN_THRESHOLD_R50 = 0.05
PROFIT_GIVEBACK_MFE_R = 1.0
PATH_SENSITIVE_OVERSHOOT_R = 0.15
FRAGILE_WIN_MAE_R = 0.75
UNDERCAPTURE_EXTRA_R = 1.0


def now() -> str:
    return datetime.now().astimezone().isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    require(PROTOCOL.is_file(), "Frozen attribution protocol is absent")
    require(AMENDMENT.is_file(), "Reporting Amendment A is absent")
    require(PRESERVED_SEAL.is_file(), "Preserved first-pass attribution seal is absent")
    require(SOURCE_SEAL.is_file(), "Source seal is absent")
    seal = json.loads(SOURCE_SEAL.read_text(encoding="utf-8"))
    require(seal["verdict"] == "COMPLETE_UNCHANGED_THREE_CALENDAR_MONTH_TEST", "Source verdict differs")
    for record in seal["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Sealed predecessor absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Sealed predecessor size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Sealed predecessor hash differs: {path}")
    source = json.loads(SOURCE_RESULT.read_text(encoding="utf-8"))
    submitted = source.pop("result_sha256")
    require(canonical_hash(source) == submitted, "Source result payload differs")
    source["result_sha256"] = submitted
    require(source["primary_reference_exact"] is True, "Source inference did not reproduce")
    require(source["stream_bytes_exact"] is True, "Source stream bytes did not reproduce")
    require(source["fitting_performed"] is False and source["retuning_performed"] is False, "Source was fitted or retuned")
    require(source["calendar_2025_opened"] is False and source["calendar_2026_opened"] is False, "Fresh years differ")
    return seal, source


def load_streams(path: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            submitted = row.pop("stream_sha256")
            require(canonical_hash(row) == submitted, f"Stream payload differs: {row.get('case_alias')}")
            row["stream_sha256"] = submitted
            alias = str(row["case_alias"])
            require(alias not in output, f"Duplicate stream alias: {alias}")
            output[alias] = row
    require(len(output) == 65, "Expected 65 daily streams")
    return output


def complete_rows(stream: dict[str, Any], timeframe: str) -> list[dict[str, Any]]:
    end = parse_dt(stream["end_exclusive"])
    return [
        row
        for row in stream["timeframes"][timeframe]
        if row.get("complete") is True and parse_dt(row["available_at"]) <= end
    ]


def session_minute(signal_at: str, session: str) -> int:
    point = parse_dt(signal_at)
    zone = LONDON if session == "LONDON" else NEW_YORK
    local = point.astimezone(zone)
    return (local.hour - 8) * 60 + local.minute


def structural_r_from_r50(value_r50: float, quantity: int, risk_per_ounce: float) -> float:
    return float(value_r50) * 50.0 / float(quantity) / risk_per_ounce


def after_exit_flags(
    *,
    m1_path: list[dict[str, Any]],
    exit_at: datetime,
    fill: float,
    stop: float,
    target: float,
    risk: float,
    stop_resolution: bool,
) -> dict[str, Any]:
    exit_bar = next((row for row in m1_path if parse_dt(row["open_at"]) == exit_at), None)
    later = [row for row in m1_path if parse_dt(row["open_at"]) > exit_at]
    same_bar_target = bool(
        stop_resolution
        and exit_bar is not None
        and float(exit_bar["low"]) <= stop
        and float(exit_bar["high"]) >= target
    )
    later_target_rows = [row for row in later if float(row["high"]) >= target]
    later_fill_rows = [row for row in later if float(row["high"]) >= fill]
    later_one_r_rows = [row for row in later if float(row["high"]) >= fill + risk]
    overshoot = None
    if stop_resolution and exit_bar is not None:
        overshoot = max(0.0, (stop - float(exit_bar["low"])) / risk)
    return {
        "same_exit_bar_target_touch_ambiguous": same_bar_target,
        "later_target_hit": bool(later_target_rows),
        "later_target_at": later_target_rows[0]["open_at"] if later_target_rows else None,
        "later_fill_reclaim": bool(later_fill_rows),
        "later_plus_one_r_reach": bool(later_one_r_rows),
        "stop_overshoot_r": overshoot,
    }


def shadow_m5_break_even(
    *,
    stream: dict[str, Any],
    result_row: dict[str, Any],
    fill: float,
    target: float,
    risk: float,
    cost_per_ounce: float,
) -> dict[str, Any]:
    result = result_row["result"]
    fill_at = parse_dt(result_row["geometry"]["fill_at"])
    final_at = parse_dt(result["final_at"])
    activation_level = fill + risk
    activations = [
        row
        for row in complete_rows(stream, "5m")
        if fill_at < parse_dt(row["available_at"]) <= final_at
        and float(row["close"]) >= activation_level
    ]
    if not activations:
        return {"activated": False, "activation_at": None, "be_exit_at": None, "disposition": "UNCHANGED", "shadow_net_r50": float(result["net_r50"])}
    activation_at = parse_dt(activations[0]["available_at"])
    path = [
        row
        for row in complete_rows(stream, "1m")
        if fill_at <= parse_dt(row["open_at"]) <= final_at
    ]
    target_before_activation = any(
        parse_dt(row["open_at"]) < activation_at and float(row["high"]) >= target
        for row in path
    )
    if target_before_activation:
        return {"activated": True, "activation_at": activations[0]["available_at"], "be_exit_at": None, "disposition": "TARGET_PRECEDED_OVERLAY", "shadow_net_r50": float(result["net_r50"])}
    be_price = fill + cost_per_ounce
    be_exit_at: str | None = None
    target_first = False
    for row in path:
        if parse_dt(row["open_at"]) < activation_at:
            continue
        if float(row["low"]) <= be_price:
            be_exit_at = row["open_at"]
            break
        if float(row["high"]) >= target:
            target_first = True
            break
    if be_exit_at is None:
        return {
            "activated": True,
            "activation_at": activations[0]["available_at"],
            "be_exit_at": None,
            "disposition": "TARGET_PRECEDED_OVERLAY" if target_first else "UNCHANGED",
            "shadow_net_r50": float(result["net_r50"]),
        }
    baseline = float(result["net_r50"])
    if baseline < -WIN_THRESHOLD_R50:
        disposition = "LOSS_SAVED_TO_BREAK_EVEN"
    elif baseline > WIN_THRESHOLD_R50:
        disposition = "WINNER_CLIPPED_TO_BREAK_EVEN"
    else:
        disposition = "SCRATCH_REMAINED_BREAK_EVEN"
    return {
        "activated": True,
        "activation_at": activations[0]["available_at"],
        "be_exit_at": be_exit_at,
        "disposition": disposition,
        "shadow_net_r50": 0.0,
    }


def analyze_trade(result_row: dict[str, Any], stream: dict[str, Any]) -> dict[str, Any]:
    classification = result_row["classification"]
    result = result_row["result"]
    geometry = result_row["geometry"]
    quantity = int(result["quantity_ounces"])
    fill = float(classification["fill"])
    stop = float(classification["stop"])
    target = float(classification["target"])
    risk = float(classification["structural_price_risk_per_ounce"])
    require(risk > 0 and quantity > 0, f"Invalid risk geometry: {result_row['case_alias']}")
    fill_at = parse_dt(geometry["fill_at"])
    exit_at = parse_dt(result["final_at"])
    m1_path = [
        row
        for row in complete_rows(stream, "1m")
        if fill_at <= parse_dt(row["open_at"]) < parse_dt(stream["end_exclusive"])
    ]
    require(m1_path, f"Post-fill path absent: {result_row['case_alias']}")
    pre_mfe_r = structural_r_from_r50(float(result["mfe_r50"]), quantity, risk)
    pre_mae_r = structural_r_from_r50(float(result["mae_r50"]), quantity, risk)
    full_mfe_r = max(0.0, (max(float(row["high"]) for row in m1_path) - fill) / risk)
    full_mae_r = max(0.0, (fill - min(float(row["low"]) for row in m1_path)) / risk)
    target_room_r = (target - fill) / risk
    realised_gross_r = float(result["gross_usd"]) / quantity / risk
    resolution = str(result["resolution"])
    stop_resolution = resolution in {"STRUCTURAL_STOP", "GAP_STOP"}
    after = after_exit_flags(
        m1_path=m1_path,
        exit_at=exit_at,
        fill=fill,
        stop=stop,
        target=target,
        risk=risk,
        stop_resolution=stop_resolution,
    )
    net_r50 = float(result["net_r50"])
    profit_giveback = net_r50 < -WIN_THRESHOLD_R50 and pre_mfe_r >= PROFIT_GIVEBACK_MFE_R
    stop_then_target = net_r50 < -WIN_THRESHOLD_R50 and stop_resolution and after["later_target_hit"]
    path_sensitive = (
        net_r50 < -WIN_THRESHOLD_R50
        and stop_resolution
        and after["stop_overshoot_r"] is not None
        and float(after["stop_overshoot_r"]) <= PATH_SENSITIVE_OVERSHOOT_R
        and after["later_fill_reclaim"]
        and after["later_plus_one_r_reach"]
        and not stop_then_target
    )
    unresolved_negative = net_r50 < -WIN_THRESHOLD_R50 and resolution == "UTC_DAY_TIME_EXIT"
    if net_r50 < -WIN_THRESHOLD_R50:
        if profit_giveback:
            primary_attribution = "PROFIT_GIVEBACK_LOSS"
        elif stop_then_target:
            primary_attribution = "STOP_THEN_TARGET"
        elif path_sensitive:
            primary_attribution = "PATH_SENSITIVE_STOP_REVERSAL"
        elif unresolved_negative:
            primary_attribution = "UNRESOLVED_NEGATIVE_TIME_EXIT"
        else:
            primary_attribution = "NORMAL_THESIS_FAILURE"
        outcome_class = "LOSS"
    elif abs(net_r50) <= WIN_THRESHOLD_R50:
        primary_attribution = "CONTROLLED_SCRATCH"
        outcome_class = "SCRATCH"
    else:
        fragile = pre_mae_r >= FRAGILE_WIN_MAE_R
        if fragile:
            primary_attribution = "FRAGILE_WIN"
        elif bool(result.get("target_touched")):
            primary_attribution = "CLEAN_TARGET_WIN"
        elif "PROTECTED_STOP" in resolution:
            primary_attribution = "PROTECTED_WIN"
        else:
            primary_attribution = "POSITIVE_TIME_EXIT"
        outcome_class = "WIN"
    fragile_win = outcome_class == "WIN" and pre_mae_r >= FRAGILE_WIN_MAE_R
    undercaptured = outcome_class == "WIN" and full_mfe_r - max(0.0, realised_gross_r) >= UNDERCAPTURE_EXTRA_R
    decision_at = parse_dt(classification["decision_at"])
    latest_break = classification["m15_structure"].get("latest_break_at")
    break_age = None if latest_break is None else (decision_at - parse_dt(latest_break)).total_seconds() / 60.0
    session = str(result_row["signal_session"])
    screens = {
        "MACRO_NOT_OPPOSED": float(classification["macro"]["score"]) > -10.0,
        "H4_BULLISH_SEQUENCE": classification["h4"]["swing_sequence"] == "BULLISH_SWING_SEQUENCE",
        "M15_BREAK_AGE_LE_60M": break_age is not None and 0.0 <= break_age <= 60.0,
        "NOT_LAST_SESSION_HOUR": session_minute(result_row["signal_at"], session) < 180,
        "TARGET_ROOM_GE_1P5R": target_room_r >= 1.5,
    }
    overlay = shadow_m5_break_even(
        stream=stream,
        result_row=result_row,
        fill=fill,
        target=target,
        risk=risk,
        cost_per_ounce=float(classification["cost_per_ounce"]),
    )
    row: dict[str, Any] = {
        "case_alias": result_row["case_alias"],
        "trading_date_utc": result_row["trading_date_utc"],
        "signal_at": result_row["signal_at"],
        "signal_session": session,
        "session_minute": session_minute(result_row["signal_at"], session),
        "family": classification["family"],
        "resolution": resolution,
        "outcome_class": outcome_class,
        "primary_attribution": primary_attribution,
        "net_r50": net_r50,
        "pre_exit_mfe_structural_r": pre_mfe_r,
        "pre_exit_mae_structural_r": pre_mae_r,
        "full_day_mfe_structural_r": full_mfe_r,
        "full_day_mae_structural_r": full_mae_r,
        "realised_gross_structural_r": realised_gross_r,
        "target_room_structural_r": target_room_r,
        "macro_score": float(classification["macro"]["score"]),
        "macro_state": classification["macro"]["state"],
        "h4_swing_sequence": classification["h4"]["swing_sequence"],
        "m15_break_age_minutes": break_age,
        "flags": {
            "profit_giveback": profit_giveback,
            "stop_then_target": stop_then_target,
            "path_sensitive_stop_reversal": path_sensitive,
            "unresolved_negative_time_exit": unresolved_negative,
            "fragile_win": fragile_win,
            "undercaptured_win": undercaptured,
            **after,
        },
        "screens": screens,
        "shadow_m5_close_1r_break_even": overlay,
    }
    row["attribution_sha256"] = canonical_hash(row)
    return row


def aggregate_screen(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    baseline_positive = sum(float(row["net_r50"]) for row in rows if float(row["net_r50"]) > WIN_THRESHOLD_R50)
    baseline_negative = abs(sum(float(row["net_r50"]) for row in rows if float(row["net_r50"]) < -WIN_THRESHOLD_R50))
    kept = [row for row in rows if row["screens"][name]]
    excluded = [row for row in rows if not row["screens"][name]]
    positive_kept = sum(float(row["net_r50"]) for row in kept if float(row["net_r50"]) > WIN_THRESHOLD_R50)
    negative_removed = abs(sum(float(row["net_r50"]) for row in excluded if float(row["net_r50"]) < -WIN_THRESHOLD_R50))
    baseline_net = sum(float(row["net_r50"]) for row in rows)
    kept_net = sum(float(row["net_r50"]) for row in kept)
    winning_retention = positive_kept / baseline_positive if baseline_positive else 1.0
    losing_removal = negative_removed / baseline_negative if baseline_negative else 0.0
    low_choke = kept_net > baseline_net and winning_retention >= 0.90 and losing_removal >= 0.20
    return {
        "screen": name,
        "kept_trades": len(kept),
        "excluded_trades": len(excluded),
        "excluded_winners": sum(row["outcome_class"] == "WIN" for row in excluded),
        "excluded_losses": sum(row["outcome_class"] == "LOSS" for row in excluded),
        "winning_r_retention": winning_retention,
        "losing_r_removal": losing_removal,
        "baseline_net_r50": baseline_net,
        "screened_net_r50": kept_net,
        "net_change_r50": kept_net - baseline_net,
        "low_choke_diagnostic": low_choke,
    }


def group_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    return {
        name: {
            "count": len(group),
            "wins": sum(row["outcome_class"] == "WIN" for row in group),
            "losses": sum(row["outcome_class"] == "LOSS" for row in group),
            "scratches": sum(row["outcome_class"] == "SCRATCH" for row in group),
            "net_r50": sum(float(row["net_r50"]) for row in group),
        }
        for name, group in sorted(groups.items())
    }


def analyze(source: dict[str, Any], streams: dict[str, dict[str, Any]], side: str) -> dict[str, Any]:
    executed = [row for row in source["rows"] if row.get("result") is not None and row["result"].get("executed")]
    require(len(executed) == 27, "Expected 27 executed trades")
    rows = [analyze_trade(row, streams[str(row["case_alias"])]) for row in executed]
    screens = [
        aggregate_screen(rows, name)
        for name in (
            "MACRO_NOT_OPPOSED",
            "H4_BULLISH_SEQUENCE",
            "M15_BREAK_AGE_LE_60M",
            "NOT_LAST_SESSION_HOUR",
            "TARGET_ROOM_GE_1P5R",
        )
    ]
    overlay_net = sum(float(row["shadow_m5_close_1r_break_even"]["shadow_net_r50"]) for row in rows)
    baseline_net = sum(float(row["net_r50"]) for row in rows)
    output: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_MAR_MAY_2022_OUTCOME_ATTRIBUTION_V1_PASS_1_0",
        "side": side,
        "source_result_sha256": source["result_sha256"],
        "rows": rows,
        "summary": {
            "trades": len(rows),
            "wins": sum(row["outcome_class"] == "WIN" for row in rows),
            "losses": sum(row["outcome_class"] == "LOSS" for row in rows),
            "scratches": sum(row["outcome_class"] == "SCRATCH" for row in rows),
            "net_r50": baseline_net,
            "primary_attribution": group_summary(rows, "primary_attribution"),
            "by_month": group_summary([{**row, "month": row["trading_date_utc"][:7]} for row in rows], "month"),
            "by_family": group_summary(rows, "family"),
            "by_resolution": group_summary(rows, "resolution"),
            "flag_counts": {
                name: sum(bool(row["flags"][name]) for row in rows)
                for name in (
                    "profit_giveback",
                    "stop_then_target",
                    "path_sensitive_stop_reversal",
                    "unresolved_negative_time_exit",
                    "fragile_win",
                    "undercaptured_win",
                    "same_exit_bar_target_touch_ambiguous",
                )
            },
            "screens": screens,
            "shadow_m5_close_1r_break_even": {
                "baseline_net_r50": baseline_net,
                "shadow_net_r50": overlay_net,
                "net_change_r50": overlay_net - baseline_net,
                "activation_count": sum(bool(row["shadow_m5_close_1r_break_even"]["activated"]) for row in rows),
                "losses_saved": sum(row["shadow_m5_close_1r_break_even"]["disposition"] == "LOSS_SAVED_TO_BREAK_EVEN" for row in rows),
                "winners_clipped": sum(row["shadow_m5_close_1r_break_even"]["disposition"] == "WINNER_CLIPPED_TO_BREAK_EVEN" for row in rows),
                "scratches_changed": sum(row["shadow_m5_close_1r_break_even"]["disposition"] == "SCRATCH_REMAINED_BREAK_EVEN" for row in rows),
                "dispositions": dict(sorted(Counter(row["shadow_m5_close_1r_break_even"]["disposition"] for row in rows).items())),
            },
        },
        "fitting_performed": False,
        "retuning_performed": False,
        "baseline_algorithm_modified": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    output["payload_sha256"] = canonical_hash(output)
    return output


def correction_comparable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = json.loads(json.dumps(rows))
    for row in output:
        row.pop("attribution_sha256", None)
        row["flags"].pop("same_exit_bar_target_touch_ambiguous", None)
    return output


def correction_comparable_summary(summary: dict[str, Any]) -> dict[str, Any]:
    output = json.loads(json.dumps(summary))
    output["flag_counts"].pop("same_exit_bar_target_touch_ambiguous", None)
    return output


def markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Gold Coherent-Auction March--May 2022 Outcome Attribution V1 — Report",
        "",
        "Verdict: `PASS_EXPOSED_OUTCOME_ATTRIBUTION_NO_RULE_CHANGE`",
        "",
        f"- Trades: `{summary['trades']}`; wins/losses/scratches: `{summary['wins']}` / `{summary['losses']}` / `{summary['scratches']}`.",
        f"- Baseline: `{summary['net_r50']:+.6f}R`.",
        "- Primary/reference attribution reproduced exactly.",
        "",
        "## Primary attribution",
        "",
        "| Attribution | Trades | Wins | Losses | Scratches | Net R |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, row in summary["primary_attribution"].items():
        lines.append(f"| {name} | {row['count']} | {row['wins']} | {row['losses']} | {row['scratches']} | {row['net_r50']:+.4f} |")
    lines.extend(["", "## Independent flags", ""])
    for name, count in summary["flag_counts"].items():
        lines.append(f"- `{name}`: `{count}`")
    lines.extend([
        "",
        "## Low-choke standalone screens",
        "",
        "| Screen | Kept | Winners excluded | Losses excluded | Win-R retained | Loss-R removed | Net R | Change R | Flag |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in summary["screens"]:
        lines.append(
            f"| {row['screen']} | {row['kept_trades']} | {row['excluded_winners']} | {row['excluded_losses']} | "
            f"{100 * row['winning_r_retention']:.1f}% | {100 * row['losing_r_removal']:.1f}% | "
            f"{row['screened_net_r50']:+.4f} | {row['net_change_r50']:+.4f} | "
            f"{'LOW_CHOKE_DIAGNOSTIC' if row['low_choke_diagnostic'] else 'NO'} |"
        )
    overlay = summary["shadow_m5_close_1r_break_even"]
    lines.extend([
        "",
        "## Shadow M5 +1R break-even overlay",
        "",
        f"- Activations: `{overlay['activation_count']}`.",
        f"- Losses saved / winners clipped: `{overlay['losses_saved']}` / `{overlay['winners_clipped']}`.",
        f"- Baseline / shadow net: `{overlay['baseline_net_r50']:+.4f}R` / `{overlay['shadow_net_r50']:+.4f}R`.",
        f"- Net change: `{overlay['net_change_r50']:+.4f}R`.",
        "",
        "## Every trade",
        "",
        "| Date | Session | Family | Resolution | Outcome | Attribution | Net R | MFE R | MAE R | Later target | Path-sensitive | Undercaptured |",
        "|---|---|---|---|---|---|---:|---:|---:|---|---|---|",
    ])
    for row in result["rows"]:
        lines.append(
            f"| {row['trading_date_utc']} | {row['signal_session']} | {row['family']} | {row['resolution']} | "
            f"{row['outcome_class']} | {row['primary_attribution']} | {row['net_r50']:+.4f} | "
            f"{row['pre_exit_mfe_structural_r']:.2f} | {row['pre_exit_mae_structural_r']:.2f} | "
            f"{'YES' if row['flags']['later_target_hit'] else 'NO'} | "
            f"{'YES' if row['flags']['path_sensitive_stop_reversal'] else 'NO'} | "
            f"{'YES' if row['flags']['undercaptured_win'] else 'NO'} |"
        )
    lines.extend(["", "No baseline rule, trade or result was changed. All screen and overlay results are exposed diagnostics only.", ""])
    return "\n".join(lines)


def main() -> int:
    for path in (PRIMARY, REFERENCE, RESULT, SEAL, REPORT):
        require(not path.exists(), f"Append-only attribution output already exists: {path}")
    source_seal, source = verify_sources()
    primary_streams = load_streams(PRIMARY_STREAM)
    primary = analyze(source, primary_streams, "primary")
    del primary_streams
    reference_streams = load_streams(REFERENCE_STREAM)
    reference = analyze(source, reference_streams, "reference")
    del reference_streams
    require(primary["rows"] == reference["rows"], "Primary/reference trade attribution differs")
    require(primary["summary"] == reference["summary"], "Primary/reference attribution summary differs")
    preserved = json.loads(PRESERVED_RESULT.read_text(encoding="utf-8"))
    require(
        correction_comparable_rows(primary["rows"])
        == correction_comparable_rows(preserved["rows"]),
        "Amendment changed a non-flag trade field",
    )
    require(
        correction_comparable_summary(primary["summary"])
        == correction_comparable_summary(preserved["summary"]),
        "Amendment changed a non-flag summary field",
    )
    require(
        preserved["summary"]["flag_counts"]["same_exit_bar_target_touch_ambiguous"] == 1
        and primary["summary"]["flag_counts"]["same_exit_bar_target_touch_ambiguous"] == 0,
        "Expected ambiguity-flag correction did not reproduce",
    )
    write_new_json(PRIMARY, primary)
    write_new_json(REFERENCE, reference)
    final: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_MAR_MAY_2022_OUTCOME_ATTRIBUTION_V1_RESULT_1_0",
        "completed_at": now(),
        "verdict": "PASS_EXPOSED_OUTCOME_ATTRIBUTION_NO_RULE_CHANGE",
        "protocol_sha256": sha256_file(PROTOCOL),
        "amendment_sha256": sha256_file(AMENDMENT),
        "preserved_first_pass_seal_sha256": sha256_file(PRESERVED_SEAL),
        "source_seal_sha256": source_seal["seal_sha256"],
        "source_result_sha256": source["result_sha256"],
        "primary_reference_exact": True,
        "rows": primary["rows"],
        "summary": primary["summary"],
        "fitting_performed": False,
        "retuning_performed": False,
        "baseline_algorithm_modified": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    final["result_sha256"] = canonical_hash(final)
    write_new_json(RESULT, final)
    REPORT.write_text(markdown(final), encoding="utf-8", newline="\n")
    seal: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_MAR_MAY_2022_OUTCOME_ATTRIBUTION_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "files": [file_record(path) for path in (PROTOCOL, AMENDMENT, PRESERVED_SEAL, PRIMARY, REFERENCE, RESULT, REPORT)],
        "primary_reference_exact": True,
        "baseline_algorithm_modified": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(SEAL, seal)
    print(json.dumps({"verdict": final["verdict"], "summary": final["summary"]}, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
