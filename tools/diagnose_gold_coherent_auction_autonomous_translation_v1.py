#!/usr/bin/env python3
"""Outcome-free geometry diagnostic for autonomous coherent-auction translation.

This tool reads only the sealed visible human ledger and the independently
certified replay streams. It deliberately never opens the outcome ledger or
post-decision comparison payload.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "research_artifacts" / "gold_matched_human_replay_v1"
STREAM_ROOT = (
    ROOT
    / "research_artifacts"
    / "gold_blind_codex_operator_replay_v1"
    / "private_streams_recovery_a"
)
OUT = ROOT / "research_artifacts" / "gold_coherent_auction_autonomous_translation_v1"
LEDGER = ARTIFACT / "ledgers" / "matched_human_visible_ledger.jsonl"
CERTIFICATION = ARTIFACT / "stream_materialization_certification.json"
TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_stream(path: Path, expected_file_hash: str) -> dict[str, Any]:
    if sha256_file(path) != expected_file_hash:
        raise RuntimeError(f"Sealed replay stream differs: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    submitted = payload.pop("stream_sha256")
    if canonical_hash(payload) != submitted:
        raise RuntimeError(f"Replay stream payload hash differs: {path}")
    payload["stream_sha256"] = submitted
    return payload


def visible_decisions() -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line
    ]
    decisions: list[dict[str, Any]] = []
    for row in rows:
        if row["event_type"] not in {"DECISION_SEALED", "NO_TRADE_SEALED"}:
            continue
        decisions.append(row["data"]["decision"])
    if len(decisions) != 30 or Counter(row["action"] for row in decisions) != Counter(
        {"LONG": 16, "NO_TRADE": 14}
    ):
        raise RuntimeError("Visible matched-human decision population differs")
    return decisions


def eligible_bars(
    stream: dict[str, Any], timeframe: str, cutoff: datetime
) -> list[dict[str, Any]]:
    return [
        row
        for row in stream["timeframes"][timeframe]
        if row.get("complete") is True
        and parse_time(row["available_at"]) <= cutoff
        and parse_time(row["close_at"]) <= cutoff
    ]


def true_ranges(rows: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for index, row in enumerate(rows):
        high = float(row["high"])
        low = float(row["low"])
        if index == 0:
            values.append(high - low)
        else:
            prior = float(rows[index - 1]["close"])
            values.append(max(high - low, abs(high - prior), abs(low - prior)))
    return values


def rolling_atr(values: list[float], index: int, window: int = 14) -> float:
    members = values[max(0, index - window + 1) : index + 1]
    return sum(members) / len(members) if members else 0.0


def confirmed_pivots(rows: list[dict[str, Any]], width: int = 2) -> list[dict[str, Any]]:
    ranges = true_ranges(rows)
    output: list[dict[str, Any]] = []
    for index in range(width, len(rows) - width):
        row = rows[index]
        left = rows[index - width : index]
        right = rows[index + 1 : index + width + 1]
        high = float(row["high"])
        low = float(row["low"])
        atr = rolling_atr(ranges, index)
        if all(high > float(member["high"]) for member in left + right):
            shoulder = max(
                max(float(member["high"]) for member in left),
                max(float(member["high"]) for member in right),
            )
            output.append(
                {
                    "kind": "HIGH",
                    "price": high,
                    "pivot_at": row["open_at"],
                    "detected_at": rows[index + width]["available_at"],
                    "atr14": atr,
                    "prominence_atr": (high - shoulder) / max(atr, 1e-9),
                }
            )
        if all(low < float(member["low"]) for member in left + right):
            shoulder = min(
                min(float(member["low"]) for member in left),
                min(float(member["low"]) for member in right),
            )
            output.append(
                {
                    "kind": "LOW",
                    "price": low,
                    "pivot_at": row["open_at"],
                    "detected_at": rows[index + width]["available_at"],
                    "atr14": atr,
                    "prominence_atr": (shoulder - low) / max(atr, 1e-9),
                }
            )
    return output


def nearest_candidate(
    pivots: list[dict[str, Any]], *, kind: str, price: float, side: str
) -> dict[str, Any] | None:
    eligible = [
        row
        for row in pivots
        if row["kind"] == kind
        and ((side == "BELOW" and row["price"] < price) or (side == "ABOVE" and row["price"] > price))
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda row: abs(float(row["price"]) - price))


def latest_candidate(
    pivots: list[dict[str, Any]], *, kind: str, price: float, side: str
) -> dict[str, Any] | None:
    eligible = [
        row
        for row in pivots
        if row["kind"] == kind
        and ((side == "BELOW" and row["price"] < price) or (side == "ABOVE" and row["price"] > price))
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda row: parse_time(row["detected_at"]))


def diagnostic_row(decision: dict[str, Any], stream: dict[str, Any]) -> dict[str, Any]:
    cutoff = parse_time(decision["expected_cursor_at"])
    output: dict[str, Any] = {
        "case_alias": decision["case_alias"],
        "decision_at": decision["expected_cursor_at"],
        "action": decision["action"],
    }
    if decision["action"] == "NO_TRADE":
        return output
    entry = float(decision["entry"])
    stop = float(decision["stop"])
    target = float(decision["target"])
    position = next(
        row for row in decision["drawings"] if row["kind"] == "LONG_POSITION"
    )
    output.update(
        {
            "human_entry": entry,
            "human_stop": stop,
            "human_target": target,
            "human_entry_frame": position["anchors"][0]["source_timeframe"],
            "human_stop_frame": position["anchors"][1]["source_timeframe"],
            "human_target_frame": position["anchors"][2]["source_timeframe"],
        }
    )
    for timeframe in TIMEFRAMES:
        bars = eligible_bars(stream, timeframe, cutoff)
        if not bars:
            continue
        ranges = true_ranges(bars)
        current_atr = rolling_atr(ranges, len(ranges) - 1)
        current_close = float(bars[-1]["close"])
        output[f"{timeframe}_visible_close"] = current_close
        output[f"{timeframe}_atr14"] = current_atr
        output[f"entry_minus_{timeframe}_close_atr"] = (entry - current_close) / max(
            current_atr, 1e-9
        )
        pivots = confirmed_pivots(bars)
        stop_nearest = nearest_candidate(pivots, kind="LOW", price=entry, side="BELOW")
        stop_latest = latest_candidate(pivots, kind="LOW", price=entry, side="BELOW")
        target_nearest = nearest_candidate(pivots, kind="HIGH", price=entry, side="ABOVE")
        target_latest = latest_candidate(pivots, kind="HIGH", price=entry, side="ABOVE")
        for label, candidate, human in (
            ("stop_nearest", stop_nearest, stop),
            ("stop_latest", stop_latest, stop),
            ("target_nearest", target_nearest, target),
            ("target_latest", target_latest, target),
        ):
            if candidate is None:
                output[f"{timeframe}_{label}_price"] = None
                output[f"{timeframe}_{label}_error_atr"] = None
                output[f"{timeframe}_{label}_age_minutes"] = None
            else:
                output[f"{timeframe}_{label}_price"] = candidate["price"]
                output[f"{timeframe}_{label}_error_atr"] = abs(
                    float(candidate["price"]) - human
                ) / max(current_atr, 1e-9)
                output[f"{timeframe}_{label}_age_minutes"] = (
                    cutoff - parse_time(candidate["detected_at"])
                ).total_seconds() / 60.0
    return output


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trades = [row for row in rows if row["action"] == "LONG"]
    candidates: dict[str, dict[str, Any]] = {}
    for timeframe in TIMEFRAMES:
        for family in ("stop_nearest", "stop_latest", "target_nearest", "target_latest"):
            key = f"{timeframe}_{family}_error_atr"
            values = sorted(float(row[key]) for row in trades if row.get(key) is not None)
            candidates[key] = {
                "support": len(values),
                "within_0p10_atr": sum(value <= 0.10 for value in values),
                "within_0p25_atr": sum(value <= 0.25 for value in values),
                "within_0p50_atr": sum(value <= 0.50 for value in values),
                "median_error_atr": values[len(values) // 2] if values else None,
            }
    return {
        "decisions": len(rows),
        "trades": len(trades),
        "no_trades": len(rows) - len(trades),
        "human_entry_frames": dict(Counter(row["human_entry_frame"] for row in trades)),
        "human_stop_frames": dict(Counter(row["human_stop_frame"] for row in trades)),
        "human_target_frames": dict(Counter(row["human_target_frame"] for row in trades)),
        "candidate_fit": candidates,
    }


def write_outputs(rows: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "geometry_diagnostic_rows.csv"
    json_path = OUT / "geometry_diagnostic.json"
    fields = sorted({key for row in rows for key in row})
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    certification = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
    records = {row["case_alias"]: row for row in certification["case_files"]}
    decisions = visible_decisions()
    primary_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    for decision in decisions:
        alias = decision["case_alias"]
        record = records[alias]
        primary = load_stream(
            ROOT / record["primary"]["path"], record["primary"]["sha256"]
        )
        reference = load_stream(
            ROOT / record["reference"]["path"], record["reference"]["sha256"]
        )
        primary_rows.append(diagnostic_row(decision, primary))
        reference_rows.append(diagnostic_row(decision, reference))
    if canonical_hash(primary_rows) != canonical_hash(reference_rows):
        raise RuntimeError("Primary/reference geometry diagnostics differ")
    payload = {
        "version": "GOLD_COHERENT_AUCTION_AUTONOMOUS_TRANSLATION_V1_GEOMETRY_DIAGNOSTIC_1_0",
        "evidence_status": "EXPOSED_PREDECISION_SEMANTIC_CALIBRATION_ONLY",
        "population": "CBR-2022-001_THROUGH_CBR-2022-030",
        "visible_ledger_sha256": sha256_file(LEDGER),
        "outcome_ledger_opened": False,
        "postdecision_paths_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "summary": summarize(primary_rows),
        "rows_sha256": canonical_hash(primary_rows),
        "primary_reference_identical": True,
    }
    write_outputs(primary_rows, payload)
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
