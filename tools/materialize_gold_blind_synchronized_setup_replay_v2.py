#!/usr/bin/env python3
"""Materialize independently reproduced, practice-only synchronized replay timelines."""

from __future__ import annotations

import gzip
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import materialize_gold_blind_discretionary_replay_v1 as base
import materialize_gold_blind_discretionary_replay_v1_1 as v11


ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "research_artifacts/gold_blind_discretionary_replay_v1"
OUT = ROOT / "research_artifacts/gold_blind_synchronized_setup_replay_v2"
FREEZE = ROOT / "research_manifests/gold_blind_synchronized_setup_replay_v2_preimplementation_freeze.json"
REGISTRY = V1 / "population_registry_v1_1.private.json"
DISPLAY_PRIMARY = V1 / "display_payloads_v1_1.primary.jsonl.gz"
DISPLAY_REFERENCE = V1 / "display_payloads_v1_1.reference.jsonl.gz"
PRACTICE_PRIMARY = V1 / "practice_future_paths_v1_1.primary.jsonl.gz"
PRACTICE_REFERENCE = V1 / "practice_future_paths_v1_1.reference.jsonl.gz"
TIMELINE_PRIMARY = OUT / "practice_timelines_v2.primary.jsonl.gz"
TIMELINE_REFERENCE = OUT / "practice_timelines_v2.reference.jsonl.gz"
CERTIFICATION = OUT / "timeline_materialization_certification.json"

TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")
MINUTES = {"1w": 10_080, "1d": 1_440, "4h": 240, "1h": 60, "15m": 15, "5m": 5, "1m": 1}
INTRADAY_AGGREGATES = ("5m", "15m", "1h", "4h")


def read_gzip(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def offset_close(value: datetime, cutoff: datetime) -> int:
    minutes = (value - cutoff).total_seconds() / 60
    rounded = round(minutes)
    if abs(minutes - rounded) > 1e-6:
        raise RuntimeError(f"Close timestamp is not minute-aligned: {minutes}")
    return int(rounded)


def offset_available(value: datetime, cutoff: datetime) -> int:
    return int(math.ceil((value - cutoff).total_seconds() / 60 - 1e-9))


def normalized_bar(
    *,
    alias: str,
    timeframe: str,
    close_offset: int,
    available_offset: int,
    open_value: float,
    high_value: float,
    low_value: float,
    close_value: float,
    volume: float | None,
    reference: float,
) -> dict[str, Any]:
    body = {
        "close_offset_minutes": close_offset,
        "available_offset_minutes": available_offset,
        "open": base.normalized_price(open_value, reference),
        "high": base.normalized_price(high_value, reference),
        "low": base.normalized_price(low_value, reference),
        "close": base.normalized_price(close_value, reference),
        "volume": volume,
    }
    return {"bar_id": base.canonical_hash({"case_alias": alias, "timeframe": timeframe, **body}), **body}


def pre_chart(
    *, alias: str, timeframe: str, rows: list[dict[str, Any]], cutoff: datetime, reference: float
) -> list[dict[str, Any]]:
    selected = rows[-base.BAR_LIMITS[timeframe]:]
    return [
        normalized_bar(
            alias=alias,
            timeframe=timeframe,
            close_offset=offset_close(base.parse_timestamp(str(row["close_time"])), cutoff),
            available_offset=offset_available(row["_available_at"], cutoff),
            open_value=float(row["open"]),
            high_value=float(row["high"]),
            low_value=float(row["low"]),
            close_value=float(row["close"]),
            volume=None if row.get("volume") is None else float(row["volume"]),
            reference=reference,
        )
        for row in selected
    ]


def weekly_chart(
    *, alias: str, daily_rows: list[dict[str, Any]], cutoff: datetime, reference: float
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    cutoff_iso = cutoff.date().isocalendar()
    cutoff_week = (cutoff_iso.year, cutoff_iso.week)
    for row in daily_rows:
        iso = row["_open_at"].date().isocalendar()
        key = (iso.year, iso.week)
        if key < cutoff_week:
            grouped[key].append(row)
    weeks: list[list[dict[str, Any]]] = []
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=lambda item: item["_open_at"])
        if len(rows) >= 4:
            weeks.append(rows)
    output = []
    for rows in weeks[-52:]:
        output.append(normalized_bar(
            alias=alias,
            timeframe="1w",
            close_offset=offset_close(base.parse_timestamp(str(rows[-1]["close_time"])), cutoff),
            available_offset=max(offset_available(row["_available_at"], cutoff) for row in rows),
            open_value=float(rows[0]["open"]),
            high_value=max(float(row["high"]) for row in rows),
            low_value=min(float(row["low"]) for row in rows),
            close_value=float(rows[-1]["close"]),
            volume=sum(float(row.get("volume") or 0) for row in rows),
            reference=reference,
        ))
    return output


def aggregate_future(
    *,
    alias: str,
    timeframe: str,
    rows: list[dict[str, Any]],
    cutoff: datetime,
    end: datetime,
    reference: float,
) -> list[dict[str, Any]]:
    duration = MINUTES[timeframe]
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        open_at = row["_open_at"]
        epoch_minutes = int((open_at - epoch).total_seconds() // 60)
        bucket_start = epoch + timedelta(minutes=(epoch_minutes // duration) * duration)
        grouped[bucket_start].append(row)
    output = []
    for start in sorted(grouped):
        close = start + timedelta(minutes=duration)
        if not (cutoff < close <= end):
            continue
        source = sorted(grouped[start], key=lambda item: item["_open_at"])
        expected = [start + timedelta(minutes=index) for index in range(duration)]
        observed = [row["_open_at"] for row in source]
        if observed != expected:
            continue
        output.append(normalized_bar(
            alias=alias,
            timeframe=timeframe,
            close_offset=offset_close(close, cutoff),
            available_offset=max(offset_available(row["_available_at"], cutoff) for row in source),
            open_value=float(source[0]["open"]),
            high_value=max(float(row["high"]) for row in source),
            low_value=min(float(row["low"]) for row in source),
            close_value=float(source[-1]["close"]),
            volume=sum(float(row.get("volume") or 0) for row in source),
            reference=reference,
        ))
    return output


def public_values(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: row.get(key) for key in ("open", "high", "low", "close", "volume")} for row in rows]


def public_ohlc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare the sealed V1.1 practice path, which intentionally omits volume."""
    return [{key: row.get(key) for key in ("open", "high", "low", "close")} for row in rows]


def build_timelines(
    cases: list[dict[str, Any]],
    charts: dict[str, dict[str, list[dict[str, Any]]]],
    future: dict[str, list[dict[str, Any]]],
    displays: dict[str, dict[str, Any]],
    practice_paths: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for case in sorted(cases, key=lambda item: item["mode_sequence"]):
        alias = case["case_alias"]
        cutoff = base.parse_timestamp(case["checkpoint_at"])
        end = base.parse_timestamp(case["session_end"])
        if offset_close(end, cutoff) != 180:
            raise RuntimeError(f"Practice horizon differs for {alias}")
        reference = float(charts[alias]["1m"][-1]["close"])
        timelines: dict[str, list[dict[str, Any]]] = {}
        for timeframe in TIMEFRAMES:
            if timeframe == "1w":
                initial = weekly_chart(alias=alias, daily_rows=charts[alias]["1d"], cutoff=cutoff, reference=reference)
            else:
                initial = pre_chart(alias=alias, timeframe=timeframe, rows=charts[alias][timeframe], cutoff=cutoff, reference=reference)
            certified = displays[alias]["charts"][timeframe]
            if public_values(initial) != public_values(certified):
                raise RuntimeError(f"V2 initial chart differs from sealed V1.1 display: {alias} {timeframe}")
            additions: list[dict[str, Any]] = []
            if timeframe == "1m":
                additions = [
                    normalized_bar(
                        alias=alias,
                        timeframe="1m",
                        close_offset=offset_close(base.parse_timestamp(str(row["close_time"])), cutoff),
                        available_offset=offset_available(row["_available_at"], cutoff),
                        open_value=float(row["open"]),
                        high_value=float(row["high"]),
                        low_value=float(row["low"]),
                        close_value=float(row["close"]),
                        volume=None if row.get("volume") is None else float(row["volume"]),
                        reference=reference,
                    )
                    for row in future[alias]
                ]
                if public_ohlc(additions) != public_ohlc(practice_paths[alias]["bars"]):
                    raise RuntimeError(f"V2 future M1 differs from sealed V1.1 practice path: {alias}")
            elif timeframe in INTRADAY_AGGREGATES:
                source_m1 = [*charts[alias]["1m"], *future[alias]]
                additions = aggregate_future(
                    alias=alias,
                    timeframe=timeframe,
                    rows=source_m1,
                    cutoff=cutoff,
                    end=end,
                    reference=reference,
                )
            rows = [*initial, *additions]
            identities = [(row["close_offset_minutes"], row["bar_id"]) for row in rows]
            if identities != sorted(identities) or len({item[0] for item in identities}) != len(identities):
                raise RuntimeError(f"Timeline order/identity failure: {alias} {timeframe}")
            if any(row["available_offset_minutes"] > 180 for row in rows):
                raise RuntimeError(f"Timeline contains post-horizon availability: {alias} {timeframe}")
            timelines[timeframe] = rows

        future_offsets = [row["close_offset_minutes"] for row in timelines["1m"] if row["close_offset_minutes"] > 0]
        if future_offsets != list(range(1, 181)):
            raise RuntimeError(f"Future M1 offset coverage failure: {alias}")
        context = {key: value for key, value in displays[alias].items() if key not in {"charts", "payload_sha256", "chart_availability"}}
        context["display_policy"] = {
            **context["display_policy"],
            "protocol": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2",
            "shared_cursor": True,
            "future_bars_server_side_only": True,
            "scored_access_closed": True,
        }
        context_sha = base.canonical_hash(context)
        body = {
            "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_TIMELINE_1_0",
            "case_alias": alias,
            "mode": "PRACTICE",
            "mode_sequence": case["mode_sequence"],
            "session_code": case["session_code"],
            "initial_cursor_minute": 0,
            "maximum_cursor_minute": 180,
            "reference_index": 100.0,
            "context": context,
            "context_sha256": context_sha,
            "timelines": timelines,
            "source_lineage": {
                "v1_1_display_payload_sha256": displays[alias]["payload_sha256"],
                "v1_1_practice_path_sha256": base.canonical_hash(practice_paths[alias]),
                "session_record_hash": case["session_record_hash"],
            },
        }
        body["timeline_sha256"] = base.canonical_hash(body)
        output.append(base.rounded(body))
    return output


def main() -> int:
    for path in (TIMELINE_PRIMARY, TIMELINE_REFERENCE, CERTIFICATION):
        if path.exists():
            raise RuntimeError(f"Append-only V2 output exists: {path.relative_to(ROOT)}")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_V2_VALUE_MATERIALIZATION_OR_IMPLEMENTATION":
        raise RuntimeError("V2 preimplementation freeze differs")
    for source in freeze["source_records"]:
        path = ROOT / source["path"]
        if not path.is_file() or path.stat().st_size != source["bytes"] or base.sha256_file(path) != source["sha256"]:
            raise RuntimeError(f"V2 frozen source differs: {source['path']}")

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    cases = [row for row in registry["cases"] if row["mode"] == "PRACTICE"]
    if [row["case_alias"] for row in cases] != freeze["practice_aliases"]:
        raise RuntimeError("V2 practice population differs from freeze")
    display_primary_rows = read_gzip(DISPLAY_PRIMARY)
    display_reference_rows = read_gzip(DISPLAY_REFERENCE)
    if display_primary_rows != display_reference_rows:
        raise RuntimeError("V1.1 public display primary/reference differ")
    displays = {row["case_alias"]: row for row in display_primary_rows if row["mode"] == "PRACTICE"}
    practice_primary_rows = read_gzip(PRACTICE_PRIMARY)
    practice_reference_rows = read_gzip(PRACTICE_REFERENCE)
    if practice_primary_rows != practice_reference_rows:
        raise RuntimeError("V1.1 practice path primary/reference differ")
    practice = {row["case_alias"]: row for row in practice_primary_rows}

    primary_charts, primary_future = v11.build_price_inputs(cases, v11.parse_price_primary)
    reference_charts, reference_future = v11.build_price_inputs(cases, v11.parse_price_reference)
    if base.canonical_hash(primary_charts) != base.canonical_hash(reference_charts):
        raise RuntimeError("V2 initial source primary/reference parse differs")
    if base.canonical_hash(primary_future) != base.canonical_hash(reference_future):
        raise RuntimeError("V2 future source primary/reference parse differs")
    primary = build_timelines(cases, primary_charts, primary_future, displays, practice)
    reference = build_timelines(cases, reference_charts, reference_future, displays, practice)
    if primary != reference:
        raise RuntimeError("V2 timeline primary/reference materializations differ")

    base.write_jsonl_gzip(TIMELINE_PRIMARY, primary)
    base.write_jsonl_gzip(TIMELINE_REFERENCE, reference)
    timeframe_counts = {
        timeframe: {
            "minimum": min(len(row["timelines"][timeframe]) for row in primary),
            "maximum": max(len(row["timelines"][timeframe]) for row in primary),
            "future_minimum": min(sum(item["close_offset_minutes"] > 0 for item in row["timelines"][timeframe]) for row in primary),
            "future_maximum": max(sum(item["close_offset_minutes"] > 0 for item in row["timelines"][timeframe]) for row in primary),
        }
        for timeframe in TIMEFRAMES
    }
    gates = {
        "preimplementation_freeze_verified": True,
        "practice_cases_exact_20": len(primary) == 20 and [row["case_alias"] for row in primary] == freeze["practice_aliases"],
        "no_scored_timeline": all(row["mode"] == "PRACTICE" and row["case_alias"].startswith("P-") for row in primary),
        "initial_v1_1_display_values_exact": True,
        "future_v1_1_m1_values_exact": True,
        "future_m1_offsets_exact_1_through_180": all(
            [item["close_offset_minutes"] for item in row["timelines"]["1m"] if item["close_offset_minutes"] > 0] == list(range(1, 181))
            for row in primary
        ),
        "all_bars_ordered_unique_and_within_horizon": True,
        "primary_reference_structures_exact": primary == reference,
        "primary_reference_bytes_exact": base.sha256_file(TIMELINE_PRIMARY) == base.sha256_file(TIMELINE_REFERENCE),
        "absolute_calendar_fields_absent_from_public_bar_rows": all(
            set(item) == {"bar_id", "close_offset_minutes", "available_offset_minutes", "open", "high", "low", "close", "volume"}
            for row in primary for timeframe in TIMEFRAMES for item in row["timelines"][timeframe]
        ),
        "scored_access_remains_closed": freeze["scored_access"] == "CLOSED_PENDING_V2_CERTIFICATION",
        "calendar_2025_2026_not_opened": True,
        "no_acquisition_or_charge": True,
    }
    if not all(gates.values()):
        raise RuntimeError(f"V2 timeline gate failure: {gates}")
    certification = {
        "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_TIMELINE_CERTIFICATION_1_0",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS_V2_PRACTICE_TIMELINE_MATERIALIZATION",
        "practice_case_count": len(primary),
        "timeframe_counts": timeframe_counts,
        "primary_sha256": base.sha256_file(TIMELINE_PRIMARY),
        "reference_sha256": base.sha256_file(TIMELINE_REFERENCE),
        "complete_timeline_set_sha256": base.canonical_hash(primary),
        "gates": gates,
        "scored_timelines_materialized": False,
        "outcomes_calculated": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    base.write_new_json(CERTIFICATION, certification)
    print(json.dumps({"verdict": certification["verdict"], "practice_cases": len(primary), "timeframe_counts": timeframe_counts, "gates": gates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
