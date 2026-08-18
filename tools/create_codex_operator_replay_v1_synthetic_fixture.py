#!/usr/bin/env python3
"""Create an outcome-free 249-case fixture for isolated browser certification."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def timestamps(day: str, minute: int) -> tuple[str, str]:
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00") + timedelta(minutes=minute)
    end = start + timedelta(minutes=1)
    return (
        start.isoformat().replace("+00:00", "Z"),
        end.isoformat().replace("+00:00", "Z"),
    )


def bar(alias: str, timeframe: str, sequence: int, open_at: str, close_at: str, value: float) -> dict[str, Any]:
    return {
        "bar_id": digest([alias, timeframe, sequence, close_at]),
        "timeframe": timeframe,
        "open_at": open_at,
        "close_at": close_at,
        "available_at": close_at,
        "open": value,
        "high": value + 0.45,
        "low": value - 0.45,
        "close": value + 0.10,
        "volume": 10.0,
        "spread_price": 0.20,
        "complete": True,
        "missing_source_minutes": 0,
    }


def make_stream(alias: str, day: str, sequence: int) -> dict[str, Any]:
    start = f"{day}T00:00:00Z"
    end = f"{day}T00:05:00Z"
    charts: dict[str, list[dict[str, Any]]] = {}
    for timeframe in TIMEFRAMES:
        charts[timeframe] = [bar(alias, timeframe, 0, start, start, 100.0)]
    charts["1m"] = [bar(alias, "1m", 0, start, start, 100.0)]
    for minute, value in enumerate((100.0, 100.5, 101.5, 102.5), start=0):
        open_at, close_at = timestamps(day, minute)
        charts["1m"].append(bar(alias, "1m", minute + 1, open_at, close_at, value))
    sessions = [
        {
            "record_id": f"{alias}-LONDON",
            "session_code": "LONDON",
            "session_date": day,
            "session_timezone": "UTC",
            "available_at": start,
            "decision_at": start,
            "observation_end": f"{day}T00:03:00Z",
            "epistemic_status": "OBSERVED",
            "known_levels": [{"code": "SYNTHETIC_SUPPORT", "price": 99.0}],
            "windows": {},
            "record_hash": digest([alias, "LONDON"]),
        },
        {
            "record_id": f"{alias}-NEW_YORK",
            "session_code": "NEW_YORK",
            "session_date": day,
            "session_timezone": "UTC",
            "available_at": f"{day}T00:02:00Z",
            "decision_at": f"{day}T00:02:00Z",
            "observation_end": f"{day}T00:04:00Z",
            "epistemic_status": "OBSERVED",
            "known_levels": [{"code": "SYNTHETIC_RESISTANCE", "price": 102.0}],
            "windows": {},
            "record_hash": digest([alias, "NEW_YORK"]),
        },
    ]
    body = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PRIVATE_STREAM_1_0",
        "case_alias": alias,
        "mode": "CODEX_BLIND",
        "mode_sequence": sequence,
        "trading_date_utc": day,
        "start_inclusive": start,
        "end_exclusive": end,
        "initial_cursor_at": start,
        "maximum_cursor_at": end,
        "research_credit": "SYNTHETIC_BROWSER_CERTIFICATION_ONLY",
        "timeframes": charts,
        "context_timeline": {
            "fundamentals": [{
                "available_at": start,
                "epistemic_status": "CALCULATED",
                "engine_state": {
                    "bias_label": "NEUTRAL",
                    "directional_score": 0.0,
                    "confidence": 50.0,
                    "regime_label": "SYNTHETIC_CERTIFICATION",
                    "dominant_driver": "Synthetic rates context",
                    "main_contradiction": "Synthetic dollar context",
                    "event_risk": "LOW",
                    "components": [{
                        "code": "SYNTHETIC_COMPONENT",
                        "direction": 0.0,
                        "explanation": "Synthetic neutral context for browser isolation only.",
                        "epistemic_status": "CALCULATED",
                    }],
                },
            }],
            "structure": [],
            "cross_market": [],
            "positioning": [],
            "events": [],
            "sessions": sessions,
        },
        "source_lineage": {"synthetic_browser_certification": True},
    }
    body["stream_sha256"] = digest(body)
    return body


def business_days() -> list[str]:
    output: list[str] = []
    cursor = date(2022, 1, 3)
    while len(output) < 249:
        if cursor.weekday() < 5:
            output.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--logical-root", default="research_artifacts/codex_operator_replay_v1_e2e")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Synthetic fixture destination is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    primary = output / "private_streams" / "primary"
    reference = output / "private_streams" / "reference"
    primary.mkdir(parents=True)
    reference.mkdir(parents=True)
    cases = []
    case_files = []
    for sequence, day in enumerate(business_days(), start=1):
        alias = f"CBR-2022-{sequence:03d}"
        record = make_stream(alias, day, sequence)
        payload = canonical_bytes(record) + b"\n"
        file_items = []
        for label, directory in (("primary", primary), ("reference", reference)):
            path = directory / f"{alias}.json.gz"
            with path.open("xb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                    zipped.write(payload)
            file_items.append({
                "path": f"{args.logical_root}/private_streams/{label}/{alias}.json.gz",
                "bytes": path.stat().st_size,
                "sha256": file_digest(path),
                "stream_sha256": record["stream_sha256"],
            })
        case_files.append({
            "case_alias": alias,
            "primary": file_items[0],
            "reference": file_items[1],
            "bytes_exact": file_items[0]["sha256"] == file_items[1]["sha256"],
        })
        cases.append({
            "case_alias": alias,
            "mode_sequence": sequence,
            "trading_date_utc": day,
            "start_inclusive": record["start_inclusive"],
            "end_exclusive": record["end_exclusive"],
        })
    population_sha = digest(cases)
    write_json(output / "population_registry.private.json", {
        "version": "SYNTHETIC_CODEX_OPERATOR_REPLAY_V1_POPULATION_1_0",
        "case_count": 249,
        "population_sha256": population_sha,
        "outcomes": "LOCKED_UNTIL_COMPLETE_POPULATION",
        "cases": cases,
    })
    write_json(output / "stream_materialization_certification.json", {
        "version": "SYNTHETIC_CODEX_OPERATOR_REPLAY_V1_STREAM_CERTIFICATION_1_0",
        "verdict": "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION",
        "case_count": 249,
        "population_sha256": population_sha,
        "gates": {"synthetic_only": True, "primary_reference_exact": all(item["bytes_exact"] for item in case_files)},
        "case_files": case_files,
    })
    write_json(output / "decision_policy.json", {"version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_DECISION_POLICY_1_0"})
    write_json(output / "execution_policy.json", {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EXECUTION_POLICY_1_0",
        "latency_minutes": 1,
        "market_and_stop_slippage_price": 0.05,
        "maximum_planned_risk_usd": 50.0,
        "maximum_effective_fill_to_stop_risk_usd": 55.0,
        "minimum_quantity_ounces": 1,
    })
    write_json(output / "ledger_policy.json", {"version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_LEDGER_POLICY_1_0"})
    print(json.dumps({"verdict": "PASS_SYNTHETIC_FIXTURE", "case_count": 249, "outcome_values": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
