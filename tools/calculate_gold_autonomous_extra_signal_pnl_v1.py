#!/usr/bin/env python3
"""Exposed same-month PnL attribution for the nine autonomous extra signals.

The frozen protocol is GOLD_AUTONOMOUS_EXTRA_SIGNAL_PNL_ATTRIBUTION_V1.md.
This script intentionally does not rerun or repair the failed semantic model.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    confirmed_swings,
    event_is_active,
    iso,
    latest_atr,
    parse_dt,
    structural_breaks,
    zone_registry,
)


CONTRACT = ROOT / "GOLD_AUTONOMOUS_EXTRA_SIGNAL_PNL_ATTRIBUTION_V1.md"
CONTRACT_SHA256 = "3e92ff48017dc968f11feef30daa3d81e8d66e4092cbce7d13df400313dca61e"
CERTIFICATION = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "stream_materialization_certification.json"
)
AUTONOMOUS_SEAL = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_autonomous_translation_v1"
    / "final_seal.json"
)
OUT = (
    ROOT
    / "research_artifacts"
    / "gold_autonomous_extra_signal_pnl_attribution_v1"
)
RESULT = OUT / "result.json"
REPORT = ROOT / "GOLD_AUTONOMOUS_EXTRA_SIGNAL_PNL_ATTRIBUTION_V1_REPORT.md"
SEAL = OUT / "final_seal.json"

SIGNALS = {
    "CBR-2022-004": "2022-01-10T14:10:00Z",
    "CBR-2022-008": "2022-01-14T13:40:00Z",
    "CBR-2022-011": "2022-01-19T14:10:00Z",
    "CBR-2022-016": "2022-01-27T13:40:00Z",
    "CBR-2022-017": "2022-01-28T16:10:00Z",
    "CBR-2022-018": "2022-01-31T15:55:00Z",
    "CBR-2022-021": "2022-02-03T13:40:00Z",
    "CBR-2022-022": "2022-02-04T14:45:00Z",
    "CBR-2022-029": "2022-02-15T16:10:00Z",
}

RISK_USD = 50.0
SLIPPAGE_USD_PER_OUNCE = 0.05
SPREAD_FALLBACK = 0.20
STOP_BUFFER_ATR = 0.10
PROTECTION_R = 1.25
HUMAN_OVERLAY_R = 10.68184658
ACTIVE_ZONE_STATES = {
    "ACTIVE_UNTOUCHED",
    "ACTIVE_ENGAGED",
    "REACTIVATED_REVERSE",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_stream(path: Path, expected_file_hash: str) -> dict[str, Any]:
    require(sha256_file(path) == expected_file_hash, f"Source seal differs: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    submitted = payload.pop("stream_sha256")
    require(canonical_hash(payload) == submitted, f"Payload seal differs: {path}")
    payload["stream_sha256"] = submitted
    return payload


def spread(bar: dict[str, Any]) -> float:
    value = bar.get("spread_price")
    if value is None or not math.isfinite(float(value)) or float(value) < 0:
        return SPREAD_FALLBACK
    return float(value)


def next_fill_bar(stream: dict[str, Any], signal_at: str) -> dict[str, Any] | None:
    signal = parse_dt(signal_at)
    candidates = [
        row
        for row in complete_rows(stream["timeframes"]["1m"], stream["end_exclusive"])
        if parse_dt(row["open_at"]) > signal
    ]
    return candidates[0] if candidates else None


def stop_geometry(
    stream: dict[str, Any], signal_at: str, raw_entry: float
) -> dict[str, Any] | None:
    atr = latest_atr(stream["timeframes"]["15m"], signal_at)
    if atr is None or atr <= 0:
        return None
    events = structural_breaks(
        stream["timeframes"]["15m"], signal_at, "M15", "LONG"
    )
    active = [
        row
        for row in events
        if event_is_active(row, stream["timeframes"]["15m"], signal_at)
        and float(row["protected_level"]) < raw_entry
    ]
    if active:
        owner = max(active, key=lambda row: (parse_dt(row["break_at"]), row["identity"]))
        reference = float(owner["protected_level"])
        source = "LATEST_ACTIVE_BULLISH_M15_BREAK_PROTECTED_LOW"
        identity = str(owner["protected_identity"])
        known_at = str(owner["break_at"])
    else:
        _, swings = confirmed_swings(
            stream["timeframes"]["15m"], signal_at, "M15"
        )
        lows = [
            row
            for row in swings
            if row["kind"] == "LOW" and float(row["level"]) < raw_entry
        ]
        if not lows:
            return None
        owner = max(
            lows,
            key=lambda row: (
                parse_dt(row["detected_at"]),
                int(row["pivot_index"]),
                row["identity"],
            ),
        )
        reference = float(owner["level"])
        source = "LATEST_CONFIRMED_M15_SWING_LOW_FALLBACK"
        identity = str(owner["identity"])
        known_at = str(owner["detected_at"])
    return {
        "source": source,
        "identity": identity,
        "known_at": iso(known_at),
        "reference": reference,
        "m15_atr14": float(atr),
        "raw_stop": reference - STOP_BUFFER_ATR * float(atr),
    }


def target_geometry(
    stream: dict[str, Any], signal_at: str, actual_entry: float
) -> dict[str, Any] | None:
    zones = zone_registry(stream, signal_at, "LONG")
    for source in ("H1", "H4"):
        choices = sorted(
            (
                zone
                for zone in zones
                if zone["source"] == source
                and zone["state"] in ACTIVE_ZONE_STATES
                and float(zone["level"]) > actual_entry
            ),
            key=lambda zone: (float(zone["level"]), str(zone["identity"])),
        )
        if choices:
            selected = choices[0]
            return {
                "source": source,
                "identity": str(selected["identity"]),
                "known_at": iso(selected["known_at"]),
                "state": str(selected["state"]),
                "raw_target": float(selected["level"]),
            }
    return None


def completed_m15_between(
    stream: dict[str, Any], prior: datetime, current: datetime
) -> Iterable[dict[str, Any]]:
    for row in complete_rows(stream["timeframes"]["15m"], current):
        available = parse_dt(row["available_at"])
        if prior < available <= current:
            yield row


def non_executable(
    alias: str,
    signal_at: str,
    reason: str,
    **extra: Any,
) -> dict[str, Any]:
    row = {
        "case_alias": alias,
        "signal_at": signal_at,
        "direction": "LONG",
        "executable": False,
        "reason": reason,
        "net_usd": 0.0,
        "net_r50": 0.0,
        **extra,
    }
    row["row_sha256"] = canonical_hash(row)
    return row


def evaluate_one(
    alias: str, signal_at: str, stream: dict[str, Any]
) -> dict[str, Any]:
    fill_bar = next_fill_bar(stream, signal_at)
    if fill_bar is None:
        return non_executable(alias, signal_at, "NEXT_M1_FILL_UNAVAILABLE")
    entry_spread = spread(fill_bar)
    raw_entry = float(fill_bar["open"])
    actual_entry = raw_entry + entry_spread / 2.0 + SLIPPAGE_USD_PER_OUNCE
    stop = stop_geometry(stream, signal_at, raw_entry)
    if stop is None:
        return non_executable(
            alias,
            signal_at,
            "POINT_IN_TIME_M15_STOP_UNAVAILABLE",
            fill_at=iso(fill_bar["open_at"]),
            raw_entry=raw_entry,
            actual_entry=actual_entry,
        )
    target = target_geometry(stream, signal_at, actual_entry)
    if target is None:
        return non_executable(
            alias,
            signal_at,
            "POINT_IN_TIME_FORWARD_HTF_TARGET_UNAVAILABLE",
            fill_at=iso(fill_bar["open_at"]),
            raw_entry=raw_entry,
            actual_entry=actual_entry,
            stop=stop,
        )

    raw_stop = float(stop["raw_stop"])
    raw_target = float(target["raw_target"])
    if not raw_stop < actual_entry < raw_target:
        return non_executable(
            alias,
            signal_at,
            "UNORDERED_CONTROL_GEOMETRY",
            fill_at=iso(fill_bar["open_at"]),
            raw_entry=raw_entry,
            actual_entry=actual_entry,
            stop=stop,
            target=target,
        )
    planned_stop_fill = raw_stop - entry_spread / 2.0 - SLIPPAGE_USD_PER_OUNCE
    planned_loss_per_ounce = actual_entry - planned_stop_fill
    quantity = math.floor(RISK_USD / planned_loss_per_ounce)
    if quantity < 1:
        return non_executable(
            alias,
            signal_at,
            "MINIMUM_ONE_OUNCE_EXCEEDS_RISK_CAP",
            fill_at=iso(fill_bar["open_at"]),
            raw_entry=raw_entry,
            actual_entry=actual_entry,
            stop=stop,
            target=target,
            planned_loss_per_ounce=planned_loss_per_ounce,
        )

    fill_time = parse_dt(fill_bar["open_at"])
    path = [
        row
        for row in complete_rows(stream["timeframes"]["1m"], stream["end_exclusive"])
        if parse_dt(row["open_at"]) >= fill_time
    ]
    require(path, f"Missing outcome path for {alias}")
    structural_risk = actual_entry - raw_stop
    protection_price = actual_entry + PROTECTION_R * structural_risk
    current_stop = raw_stop
    protection_at: str | None = None
    last_m15_processed = fill_time
    path_high = actual_entry
    path_low = actual_entry
    resolution = "UTC_DAY_TIME_EXIT"
    exit_at = iso(path[-1]["close_at"])
    exit_raw = float(path[-1]["close"])
    exit_actual = exit_raw - spread(path[-1]) / 2.0 - SLIPPAGE_USD_PER_OUNCE

    for bar in path:
        now = parse_dt(bar["open_at"])
        for completed in completed_m15_between(stream, last_m15_processed, now):
            last_m15_processed = parse_dt(completed["available_at"])
            if protection_at is None and float(completed["close"]) >= protection_price:
                # This raw stop estimates a net-flat exit using only the spread
                # visible when protection becomes effective.
                current_stop = max(
                    current_stop,
                    actual_entry
                    + spread(bar) / 2.0
                    + SLIPPAGE_USD_PER_OUNCE,
                )
                protection_at = iso(completed["available_at"])

        high = float(bar["high"])
        low = float(bar["low"])
        path_high = max(path_high, high)
        path_low = min(path_low, low)
        current_spread = spread(bar)

        gap_stopped = float(bar["open"]) <= current_stop
        stop_touched = low <= current_stop
        target_touched = high >= raw_target
        if gap_stopped or stop_touched:
            exit_raw = min(current_stop, float(bar["open"]))
            exit_actual = (
                exit_raw - current_spread / 2.0 - SLIPPAGE_USD_PER_OUNCE
            )
            exit_at = iso(bar["close_at"])
            resolution = (
                "GAP_PROTECTED_STOP"
                if gap_stopped and protection_at is not None
                else "GAP_STRUCTURAL_STOP"
                if gap_stopped
                else "PROTECTED_STOP"
                if protection_at is not None
                else "STRUCTURAL_STOP"
            )
            break
        if target_touched:
            exit_raw = raw_target
            exit_actual = raw_target
            exit_at = iso(bar["close_at"])
            resolution = "HTF_LIQUIDITY_TARGET"
            break

    net_usd = (exit_actual - actual_entry) * quantity
    result = {
        "case_alias": alias,
        "signal_at": signal_at,
        "direction": "LONG",
        "executable": True,
        "fill_at": iso(fill_bar["open_at"]),
        "raw_entry": raw_entry,
        "actual_entry": actual_entry,
        "entry_spread": entry_spread,
        "stop": stop,
        "target": target,
        "planned_loss_per_ounce": planned_loss_per_ounce,
        "planned_risk_usd": planned_loss_per_ounce * quantity,
        "quantity_ounces": quantity,
        "structural_risk_per_ounce": structural_risk,
        "protection_threshold_price": protection_price,
        "protection_at": protection_at,
        "resolution": resolution,
        "exit_at": exit_at,
        "raw_exit": exit_raw,
        "actual_exit": exit_actual,
        "net_usd": net_usd,
        "net_r50": net_usd / RISK_USD,
        "mfe_usd": max(0.0, path_high - actual_entry) * quantity,
        "mae_usd": max(0.0, actual_entry - path_low) * quantity,
    }
    result["row_sha256"] = canonical_hash(result)
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    executable = [row for row in rows if row["executable"]]
    wins = [row for row in executable if float(row["net_usd"]) > 0.01]
    losses = [row for row in executable if float(row["net_usd"]) < -0.01]
    standalone_usd = sum(float(row["net_usd"]) for row in rows)
    standalone_r = standalone_usd / RISK_USD
    return {
        "signals": len(rows),
        "executable": len(executable),
        "non_executable": len(rows) - len(executable),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(executable) - len(wins) - len(losses),
        "win_rate_excluding_scratches": (
            len(wins) / (len(wins) + len(losses))
            if wins or losses
            else None
        ),
        "standalone_net_usd": standalone_usd,
        "standalone_net_r50": standalone_r,
        "human_overlay_net_r50": HUMAN_OVERLAY_R,
        "hybrid_net_r50": HUMAN_OVERLAY_R + standalone_r,
        "hybrid_net_usd_at_50_per_r": (HUMAN_OVERLAY_R + standalone_r) * RISK_USD,
        "row_set_sha256": canonical_hash(rows),
    }


def render_report(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Gold Autonomous Extra-Signal PnL Attribution V1 Report",
        "",
        "Verdict: `EXPOSED_CONTROL_ATTRIBUTION_COMPLETE`",
        "",
        "This does not reverse the autonomous semantic FAIL. The nine extra",
        "detections had no original geometry, so this report applies the one",
        "pre-path frozen control geometry in the accompanying protocol.",
        "",
        "| Case | Signal UTC | Status | Resolution | Net R | Net USD |",
        "|---|---|---|---|---:|---:|",
    ]
    for row in result["rows"]:
        status = "EXECUTED" if row["executable"] else row["reason"]
        resolution = row.get("resolution", "—")
        lines.append(
            f"| {row['case_alias']} | {row['signal_at']} | {status} | "
            f"{resolution} | {float(row['net_r50']):+.4f} | "
            f"${float(row['net_usd']):+.2f} |"
        )
    lines += [
        "",
        "## Totals",
        "",
        f"- Extra scanner signals: {summary['signals']} detected, "
        f"{summary['executable']} executable, {summary['non_executable']} non-executable.",
        f"- Executed outcomes: {summary['wins']} wins, {summary['losses']} losses, "
        f"{summary['scratches']} scratches.",
        f"- Nine-signal standalone contribution: `{summary['standalone_net_r50']:+.4f}R` "
        f"/ `${summary['standalone_net_usd']:+.2f}`.",
        f"- Existing human-input V2 result: `{summary['human_overlay_net_r50']:+.4f}R`.",
        f"- Requested arithmetic hybrid: `{summary['hybrid_net_r50']:+.4f}R` / "
        f"`${summary['hybrid_net_usd_at_50_per_r']:+.2f}` at $50 per R.",
        "",
        "## Interpretation limit",
        "",
        "The hybrid is not a homogeneous autonomous backtest: its original",
        "component uses human-selected entries/stops/targets, while these nine",
        "rows use the frozen control geometry. It answers the counterfactual",
        "money question, not whether the failed scanner is deployable.",
        "",
        "Primary and reference sealed streams produced identical row and summary hashes.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    require(sha256_file(CONTRACT) == CONTRACT_SHA256, "Frozen protocol changed")
    certification = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
    require(
        certification["verdict"] == "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION",
        "Source certification is not PASS",
    )
    autonomous_seal = json.loads(AUTONOMOUS_SEAL.read_text(encoding="utf-8"))
    require(
        autonomous_seal["status"] == "SEALED_FAIL_AUTONOMOUS_SEMANTICS",
        "Preserved autonomous verdict changed",
    )
    require(
        int(autonomous_seal["semantic_metrics"]["false_positive_no_trade_days"]) == 9,
        "Preserved false-positive count changed",
    )
    records = {row["case_alias"]: row for row in certification["case_files"]}
    require(set(SIGNALS).issubset(records), "A frozen case source is missing")

    primary_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    source_lineage: list[dict[str, Any]] = []
    for alias, signal_at in SIGNALS.items():
        record = records[alias]
        primary_path = ROOT / record["primary"]["path"]
        reference_path = ROOT / record["reference"]["path"]
        primary = load_stream(primary_path, record["primary"]["sha256"])
        reference = load_stream(reference_path, record["reference"]["sha256"])
        left = evaluate_one(alias, signal_at, primary)
        right = evaluate_one(alias, signal_at, reference)
        require(left == right, f"Primary/reference result differs for {alias}")
        primary_rows.append(left)
        reference_rows.append(right)
        source_lineage.append(
            {
                "case_alias": alias,
                "primary_path": record["primary"]["path"],
                "primary_sha256": record["primary"]["sha256"],
                "reference_path": record["reference"]["path"],
                "reference_sha256": record["reference"]["sha256"],
                "bytes_exact": record["bytes_exact"],
            }
        )
    primary_summary = summarize(primary_rows)
    reference_summary = summarize(reference_rows)
    require(primary_summary == reference_summary, "Summary reproduction differs")

    result = {
        "version": "GOLD_AUTONOMOUS_EXTRA_SIGNAL_PNL_ATTRIBUTION_V1_RESULT_1_0",
        "status": "EXPOSED_CONTROL_ATTRIBUTION_COMPLETE",
        "evidence_status": "SAME_MONTH_EXPOSED_COUNTERFACTUAL_ZERO_VALIDATION_CREDIT",
        "preserved_autonomous_verdict": autonomous_seal["status"],
        "protocol_sha256": CONTRACT_SHA256,
        "signal_registry_sha256": canonical_hash(SIGNALS),
        "source_certification_sha256": sha256_file(CERTIFICATION),
        "source_lineage_sha256": canonical_hash(source_lineage),
        "primary_reference_exact": True,
        "rows": primary_rows,
        "summary": primary_summary,
        "limitations": [
            "NINE_ROWS_WERE_SIGNALS_WITHOUT_ORIGINAL_EXECUTION_GEOMETRY",
            "CONTROL_GEOMETRY_WAS_FROZEN_BEFORE_THIS_PATH_OPEN",
            "HYBRID_COMBINES_HUMAN_AND_CONTROL_GEOMETRY",
            "SEMANTIC_PAYLOAD_WAS_OVERWRITTEN_AFTER_FINAL_SEAL",
            "NO_VALIDATION_CREDIT",
        ],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    result["payload_sha256"] = canonical_hash(result)
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    REPORT.write_text(render_report(result), encoding="utf-8", newline="\n")
    seal = {
        "version": "GOLD_AUTONOMOUS_EXTRA_SIGNAL_PNL_ATTRIBUTION_V1_FINAL_SEAL_1_0",
        "status": result["status"],
        "protocol": {
            "path": CONTRACT.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(CONTRACT),
        },
        "result": {
            "path": RESULT.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(RESULT),
        },
        "report": {
            "path": REPORT.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(REPORT),
        },
        "summary": primary_summary,
        "preserved_autonomous_verdict": autonomous_seal["status"],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "sealed_at_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
    }
    SEAL.write_text(
        json.dumps(seal, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(primary_summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
