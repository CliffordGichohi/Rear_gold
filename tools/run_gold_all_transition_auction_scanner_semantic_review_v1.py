#!/usr/bin/env python3
"""Freeze, reproduce, and seal the outcome-blind all-transition review."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import html
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.all_transition_auction_scanner_v1 import (  # noqa: E402
    RULESET,
    _assert_outcome_blind,
    enumerate_transition_observations,
    scan_new_york_stream,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
)


CONTRACT = ROOT / "GOLD_ALL_TRANSITION_AUCTION_SCANNER_SEMANTIC_REVIEW_V1.md"
IMPLEMENTATION = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "all_transition_auction_scanner_v1.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_all_transition_auction_scanner_v1.py"
RUNNER = Path(__file__).resolve()
V2_RESULT = (
    ROOT
    / "research_artifacts"
    / "gold_direction_symmetric_control_router_v2"
    / "final_result.json"
)
V2_SEAL = V2_RESULT.with_name("final_seal.json")

OUT = ROOT / "research_artifacts" / "gold_all_transition_auction_scanner_semantic_review_v1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "events.primary.json"
REFERENCE = OUT / "events.reference.json"
CERTIFICATION = OUT / "semantic_certification.json"
EVENT_LEDGER = OUT / "event_ledger.csv"
CHART_ROOT = OUT / "predecision_charts"
ATLAS = OUT / "predecision_atlas.html"
SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_ALL_TRANSITION_AUCTION_SCANNER_SEMANTIC_REVIEW_V1_REPORT.md"

TIMEFRAME_LIMITS = {"4h": 42, "1h": 64, "15m": 84, "5m": 96}
TRANSITION_CLASSES = (
    "INITIAL_CONTROL",
    "REVERSAL_TRANSFER",
    "CONTROL_REASSERTION",
    "CONTINUATION_REFRESH",
)
DIRECTIONS = ("LONG", "SHORT")


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def verify_file_record(record: dict[str, Any]) -> None:
    path = ROOT / str(record["path"])
    require(path.is_file(), f"Sealed file absent: {path}")
    require(path.stat().st_size == int(record["bytes"]), f"Sealed size differs: {path}")
    require(sha256_file(path) == str(record["sha256"]), f"Sealed hash differs: {path}")


def _atomic_create(path: Path, data: bytes) -> None:
    require(not path.exists(), f"Append-only output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary output exists: {temporary}")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    require(not path.exists(), f"Append-only output appeared concurrently: {path}")
    os.replace(temporary, path)


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_create(
        path,
        (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
    )


def write_new_text(path: Path, value: str) -> None:
    _atomic_create(path, value.encode("utf-8"))


def verify_v2_seal() -> dict[str, Any]:
    require(V2_RESULT.is_file() and V2_SEAL.is_file(), "Sealed V2 diagnostic is absent")
    seal = load_json(V2_SEAL)
    submitted = str(seal.pop("seal_sha256"))
    require(canonical_hash(seal) == submitted, "V2 seal payload differs")
    for record in seal["files"]:
        verify_file_record(record)
    seal["seal_sha256"] = submitted
    return seal


def frozen_population() -> list[dict[str, Any]]:
    result = load_json(V2_RESULT)
    require(result["days"] == 117, "V2 exposed population differs")
    rows = sorted(
        result["rows"], key=lambda item: (item["trading_date_utc"], item["case_alias"])
    )
    population = [
        {
            "ordinal": index,
            "case_alias": str(row["case_alias"]),
            "trading_date_utc": str(row["trading_date_utc"]),
        }
        for index, row in enumerate(rows, start=1)
    ]
    require(len(population) == len({item["case_alias"] for item in population}) == 117, "Population identities differ")
    return population


def _synthetic_break(identity: str, direction: str, at: str) -> dict[str, Any]:
    return {"identity": identity, "direction": direction, "break_at": at}


def _synthetic_observation(
    minute: int,
    state: str,
    m5: dict[str, Any] | None,
    m15: dict[str, Any] | None,
) -> dict[str, Any]:
    at = f"2022-01-03T13:{minute:02d}:00Z"
    row = {
        "at": at,
        "raw_state": state,
        "state": state,
        "transition": False,
        "m5_event": m5,
        "m15_event": m15,
    }
    row["observation_sha256"] = canonical_hash(row)
    return row


def synthetic_proof() -> dict[str, Any]:
    long_a = _synthetic_break("LONG-A", "LONG", "2022-01-03T13:05:00Z")
    long_b = _synthetic_break("LONG-B", "LONG", "2022-01-03T13:15:00Z")
    long_15 = _synthetic_break("LONG-15", "LONG", "2022-01-03T13:05:00Z")
    short_a = _synthetic_break("SHORT-A", "SHORT", "2022-01-03T13:35:00Z")
    short_15 = _synthetic_break("SHORT-15", "SHORT", "2022-01-03T13:35:00Z")
    observations = [
        _synthetic_observation(0, "UNRESOLVED", None, None),
        _synthetic_observation(5, "BUYER_CONTROL", long_a, long_15),
        _synthetic_observation(10, "BUYER_CONTROL", long_a, long_15),
        _synthetic_observation(15, "BUYER_CONTROL", long_b, long_15),
        _synthetic_observation(20, "CONFLICTED", long_b, short_15),
        _synthetic_observation(25, "BUYER_CONTROL", long_b, long_15),
        _synthetic_observation(30, "UNRESOLVED", short_a, long_15),
        _synthetic_observation(35, "SELLER_CONTROL", short_a, short_15),
    ]
    events = enumerate_transition_observations(observations)
    classes = [item["event_class"] for item in events]
    directions = [item["direction"] for item in events]
    future_rows = [
        {"available_at": "2022-01-03T13:00:00Z"},
        {"available_at": "2022-01-03T13:05:00Z"},
        {"available_at": "2022-01-03T13:10:00Z"},
    ]
    visible = visible_rows(future_rows, "2022-01-03T13:05:00Z", 10)
    checks = {
        "all_four_semantic_events_emitted": classes
        == [
            "INITIAL_CONTROL",
            "CONTINUATION_REFRESH",
            "CONTROL_REASSERTION",
            "REVERSAL_TRANSFER",
        ],
        "both_directions_emitted": directions == ["LONG", "LONG", "LONG", "SHORT"],
        "unchanged_state_deduplicated": len(events) == 4,
        "chart_boundary_is_inclusive_and_future_blind": len(visible) == 2
        and visible[-1]["available_at"] == "2022-01-03T13:05:00Z",
    }
    require(all(checks.values()), f"Synthetic scanner proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory exists: {OUT}")
    source_lineage = source.verify_sources()
    v2_seal = verify_v2_seal()
    population = frozen_population()
    payload: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_AUCTION_SCANNER_SEMANTIC_REVIEW_V1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_OUTCOME_BLIND_ALL_TRANSITION_MATERIALIZATION",
        "ruleset": RULESET,
        "files": [file_record(path) for path in (CONTRACT, IMPLEMENTATION, TESTS, RUNNER)],
        "source_lineage": source_lineage,
        "v2_failed_diagnostic": {
            "result": file_record(V2_RESULT),
            "seal": file_record(V2_SEAL),
            "seal_sha256": v2_seal["seal_sha256"],
        },
        "population": population,
        "population_sha256": canonical_hash(population),
        "session": {
            "code": "NEW_YORK",
            "timezone": "America/New_York",
            "bar_open_interval": "[08:00,12:00)",
            "last_m5_decision_boundary": "12:00",
        },
        "event_classes": list(TRANSITION_CLASSES),
        "directions": list(DIRECTIONS),
        "thresholds_reused_unchanged": {
            "pivot_width": 2,
            "pivot_prominence_atr": 0.25,
            "break_buffer_atr": 0.05,
            "m5_minimum_range_atr": 0.80,
            "m15_minimum_range_atr": 0.90,
            "minimum_body_ratio": 0.55,
            "active_invalidation_buffer_atr": 0.10,
            "acceptance_m5_closes": 2,
        },
        "forbidden_gates": [
            "FAILED_BUYER_ANTECEDENT",
            "FAILED_SELLER_ANTECEDENT",
            "RETEST_REQUIRED",
            "TARGET_ROOM_REQUIRED",
            "MACRO_VETO",
            "HIGHER_TIMEFRAME_VETO",
            "ONE_CANDIDATE_PER_DAY",
        ],
        "chart_limits": TIMEFRAME_LIMITS,
        "example_selection": "UP_TO_THREE_EARLIEST_DISTINCT_MONTHS_PER_DIRECTION_AND_EVENT_CLASS",
        "synthetic_proof": synthetic_proof(),
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(json.dumps({"status": payload["status"], "days": 117, "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Prevalue freeze is absent")
    payload = load_json(FREEZE)
    submitted = str(payload.pop("freeze_sha256"))
    require(canonical_hash(payload) == submitted, "Freeze payload differs")
    payload["freeze_sha256"] = submitted
    for record in payload["files"]:
        verify_file_record(record)
    require(source.verify_sources() == payload["source_lineage"], "Source lineage differs")
    v2 = verify_v2_seal()
    require(v2["seal_sha256"] == payload["v2_failed_diagnostic"]["seal_sha256"], "V2 seal differs")
    require(frozen_population() == payload["population"], "Frozen population differs")
    return payload


def scan_side(side: str, frozen: dict[str, Any]) -> dict[str, Any]:
    streams = source.load_streams(side)
    ordered = [streams[item["case_alias"]] for item in frozen["population"]]
    events: list[dict[str, Any]] = []
    daily_counts: list[dict[str, Any]] = []
    for index, stream in enumerate(ordered, start=1):
        day_events = scan_new_york_stream(stream)
        events.extend(day_events)
        daily_counts.append(
            {
                "ordinal": index,
                "case_alias": stream["case_alias"],
                "trading_date_utc": stream["trading_date_utc"],
                "events": len(day_events),
                "long": sum(item["direction"] == "LONG" for item in day_events),
                "short": sum(item["direction"] == "SHORT" for item in day_events),
            }
        )
        print(
            f"{side} {index:03d}/117 {stream['trading_date_utc']} "
            f"events={len(day_events)} cumulative={len(events)}",
            flush=True,
        )
    require(len({item["event_identity"] for item in events}) == len(events), f"Duplicate {side} event identities")
    payload = {
        "version": "GOLD_ALL_TRANSITION_AUCTION_SCANNER_SEMANTIC_REVIEW_V1_SIDE_1_0",
        "side": side,
        "population_sha256": frozen["population_sha256"],
        "daily_counts": daily_counts,
        "events": events,
        "events_sha256": canonical_hash(events),
    }
    return payload


def nested_counts(events: list[dict[str, Any]], first: str, second: str) -> dict[str, Any]:
    output: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        output[str(event[first])][str(event[second])] += 1
    return {key: dict(sorted(value.items())) for key, value in sorted(output.items())}


def htf_label(event: dict[str, Any], timeframe: str) -> str:
    relations = event["higher_timeframe_context"][timeframe]["swing_relations"]
    return f"{relations['high']}/{relations['low']}"


def summarize(events: list[dict[str, Any]], daily: list[dict[str, Any]]) -> dict[str, Any]:
    daily_values = [int(item["events"]) for item in daily]
    trigger_counts: Counter[str] = Counter()
    for event in events:
        changed = event["new_break_timeframes"]
        trigger_counts["+".join(changed) if changed else "ACCEPTED_STATE"] += 1
    months = Counter(str(item["decision_at"])[:7] for item in events)
    h4 = Counter(htf_label(item, "H4") for item in events)
    h1 = Counter(htf_label(item, "H1") for item in events)
    macro = Counter(str(item["macro_context"]["state"]) for item in events)
    return {
        "eligible_days": len(daily),
        "total_events": len(events),
        "days_with_events": sum(value > 0 for value in daily_values),
        "zero_event_days": sum(value == 0 for value in daily_values),
        "events_per_day": {
            "mean": statistics.fmean(daily_values),
            "median": statistics.median(daily_values),
            "minimum": min(daily_values),
            "maximum": max(daily_values),
            "histogram": dict(sorted(Counter(str(value) for value in daily_values).items(), key=lambda item: int(item[0]))),
        },
        "direction": dict(sorted(Counter(str(item["direction"]) for item in events).items())),
        "event_class": dict(sorted(Counter(str(item["event_class"]) for item in events).items())),
        "direction_by_class": nested_counts(events, "direction", "event_class"),
        "month": dict(sorted(months.items())),
        "direction_by_month": {
            direction: dict(
                sorted(
                    Counter(str(item["decision_at"])[:7] for item in events if item["direction"] == direction).items()
                )
            )
            for direction in DIRECTIONS
        },
        "new_break_trigger": dict(sorted(trigger_counts.items())),
        "macro_alignment_context_only": dict(sorted(macro.items())),
        "h1_swing_relations_context_only": dict(sorted(h1.items())),
        "h4_swing_relations_context_only": dict(sorted(h4.items())),
        "events_with_local_destination": sum(item["liquidity_destinations"]["nearest_local"] is not None for item in events),
        "events_with_higher_timeframe_destination": sum(item["liquidity_destinations"]["nearest_higher_timeframe"] is not None for item in events),
    }


def select_examples(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for direction in DIRECTIONS:
        for event_class in TRANSITION_CLASSES:
            pool = sorted(
                [
                    item
                    for item in events
                    if item["direction"] == direction and item["event_class"] == event_class
                ],
                key=lambda item: (item["decision_at"], item["event_identity"]),
            )
            by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in pool:
                by_month[str(item["decision_at"])[:7]].append(item)
            months = sorted(by_month)
            if len(months) <= 3:
                chosen_months = months
            else:
                chosen_months = [months[0], months[len(months) // 2], months[-1]]
            selected.extend(by_month[month][0] for month in chosen_months)
    selected.sort(key=lambda item: (item["direction"], item["event_class"], item["decision_at"]))
    require(len({item["event_identity"] for item in selected}) == len(selected), "Duplicate selected examples")
    return selected


def visible_rows(rows: list[dict[str, Any]], cutoff: str, limit: int) -> list[dict[str, Any]]:
    point = parse_dt(cutoff)
    visible = [row for row in rows if parse_dt(row["available_at"]) <= point]
    output = visible[-limit:]
    require(all(parse_dt(row["available_at"]) <= point for row in output), "Future chart bar leaked")
    return output


def _fmt(value: float | None) -> str:
    return "UNKNOWN" if value is None else f"{float(value):.2f}"


def _svg_text(x: float, y: float, value: str, *, size: int = 12, color: str = "#334155", weight: int = 400) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{color}">{html.escape(value)}</text>'
    )


def _panel_levels(event: dict[str, Any], timeframe: str) -> list[tuple[float, str, str]]:
    levels: list[tuple[float, str, str]] = []
    if timeframe in {"M5", "M15"}:
        active = event["active_breaks"][timeframe]
        if active is not None:
            levels.append((float(active["broken_level"]), "consumed pivot", "#2563eb"))
            levels.append((float(active["protected_level"]), "protected swing", "#dc2626"))
    destination = event["liquidity_destinations"]["by_timeframe"].get(timeframe)
    if destination is not None:
        levels.append((float(destination["level"]), "unconsumed destination", "#7c3aed"))
    if timeframe in {"H1", "H4"}:
        context = event["higher_timeframe_context"][timeframe]
        if context["latest_high_level"] is not None:
            levels.append((float(context["latest_high_level"]), "known swing high", "#64748b"))
        if context["latest_low_level"] is not None:
            levels.append((float(context["latest_low_level"]), "known swing low", "#64748b"))
    return levels


def render_svg(stream: dict[str, Any], event: dict[str, Any]) -> bytes:
    width, height = 1440, 940
    left, right = 72, 36
    header = 112
    panel_height = 188
    panel_gap = 16
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    macro = event["macro_context"]
    h4 = htf_label(event, "H4")
    h1 = htf_label(event, "H1")
    title = (
        f"{event['trading_date_utc']} {event['decision_at'][11:16]} UTC | "
        f"{event['direction']} {event['event_class']} | M5/M15 accepted control"
    )
    subtitle = (
        f"Macro {macro['state']} score={_fmt(macro.get('score'))} confidence={_fmt(macro.get('confidence'))} "
        f"driver={macro.get('dominant_driver') or 'UNKNOWN'} | H4 {h4} | H1 {h1}"
    )
    parts.append(_svg_text(30, 34, title, size=19, color="#0f172a", weight=700))
    parts.append(_svg_text(30, 61, subtitle, size=13, color="#334155"))
    parts.append(
        _svg_text(
            30,
            86,
            "Chart ends at decision time. Blue=consumed pivot, red=protected swing, purple=known unconsumed destination.",
            size=12,
            color="#475569",
        )
    )
    for panel_index, (key, limit) in enumerate(TIMEFRAME_LIMITS.items()):
        timeframe = {"4h": "H4", "1h": "H1", "15m": "M15", "5m": "M5"}[key]
        y0 = header + panel_index * (panel_height + panel_gap)
        bars = visible_rows(stream["timeframes"][key], event["decision_at"], limit)
        require(bars, f"No visible {timeframe} bars: {event['event_identity']}")
        levels = _panel_levels(event, timeframe)
        prices = [float(value) for row in bars for value in (row["low"], row["high"])]
        raw_low, raw_high = min(prices), max(prices)
        raw_span = max(raw_high - raw_low, 0.01)
        in_view_levels = [
            item for item in levels if raw_low - raw_span * 0.30 <= item[0] <= raw_high + raw_span * 0.30
        ]
        all_prices = [*prices, *(item[0] for item in in_view_levels)]
        low, high = min(all_prices), max(all_prices)
        span = max(high - low, 0.01)
        low -= span * 0.06
        high += span * 0.06
        chart_left, chart_right = left, width - right
        chart_top, chart_bottom = y0 + 24, y0 + panel_height - 25
        chart_width = chart_right - chart_left
        chart_height = chart_bottom - chart_top

        def py(price: float) -> float:
            return chart_bottom - (price - low) / (high - low) * chart_height

        parts.append(f'<rect x="{chart_left}" y="{chart_top}" width="{chart_width}" height="{chart_height}" fill="#f8fafc" stroke="#e2e8f0"/>')
        parts.append(_svg_text(18, y0 + 18, timeframe, size=13, color="#0f172a", weight=700))
        for grid in range(1, 4):
            gy = chart_top + grid * chart_height / 4
            parts.append(f'<line x1="{chart_left}" y1="{gy:.1f}" x2="{chart_right}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
        step = chart_width / max(len(bars), 1)
        body_width = max(2.0, min(9.0, step * 0.62))
        for index, bar in enumerate(bars):
            x = chart_left + (index + 0.5) * step
            open_price = float(bar["open"])
            close_price = float(bar["close"])
            color = "#089981" if close_price >= open_price else "#f23645"
            parts.append(f'<line x1="{x:.1f}" y1="{py(float(bar["high"])):.1f}" x2="{x:.1f}" y2="{py(float(bar["low"])):.1f}" stroke="{color}" stroke-width="1"/>')
            top = min(py(open_price), py(close_price))
            body_height = max(1.2, abs(py(open_price) - py(close_price)))
            parts.append(f'<rect x="{x-body_width/2:.1f}" y="{top:.1f}" width="{body_width:.1f}" height="{body_height:.1f}" fill="{color}"/>')
        for level, label, color in in_view_levels:
            y = py(level)
            parts.append(f'<line x1="{chart_left}" y1="{y:.1f}" x2="{chart_right}" y2="{y:.1f}" stroke="{color}" stroke-width="1.2" stroke-dasharray="7 5"/>')
            parts.append(_svg_text(chart_right - 245, y - 3, f"{label} {_fmt(level)}", size=10, color=color, weight=600))
        first_at = str(bars[0]["open_at"])[5:16].replace("T", " ")
        last_at = str(bars[-1]["available_at"])[5:16].replace("T", " ")
        parts.append(_svg_text(chart_left, chart_bottom + 17, first_at, size=10, color="#64748b"))
        parts.append(_svg_text(chart_right - 105, chart_bottom + 17, last_at, size=10, color="#64748b"))
        parts.append(_svg_text(chart_left + 6, chart_top + 14, f"high {_fmt(raw_high)}", size=9, color="#64748b"))
        parts.append(_svg_text(chart_left + 6, chart_bottom - 5, f"low {_fmt(raw_low)}", size=9, color="#64748b"))
    parts.append("</svg>")
    payload = "\n".join(parts).encode("utf-8")
    require(b"outcome" not in payload.lower() and b"pnl" not in payload.lower(), "Outcome text leaked into chart")
    return payload


def render_chart_set(
    *, side: str, events: list[dict[str, Any]], selected: list[dict[str, Any]]
) -> dict[str, bytes]:
    streams = source.load_streams(side)
    by_identity = {item["event_identity"]: item for item in events}
    output: dict[str, bytes] = {}
    for index, selected_event in enumerate(selected, start=1):
        event = by_identity[selected_event["event_identity"]]
        stream = streams[event["case_alias"]]
        filename = f"{index:02d}_{event['direction'].lower()}_{event['event_class'].lower()}_{event['trading_date_utc']}_{event['event_identity'][:10]}.svg"
        output[filename] = render_svg(stream, event)
    del streams
    gc.collect()
    return output


def atlas_html(selected: list[dict[str, Any]], chart_records: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for event, record in zip(selected, chart_records, strict=True):
        cards.append(
            '<article class="card">'
            f"<h2>{html.escape(event['direction'])} · {html.escape(event['event_class'])} · {html.escape(event['decision_at'])}</h2>"
            f"<p>Event <code>{html.escape(event['event_identity'])}</code></p>"
            f"<img src=\"predecision_charts/{html.escape(record['filename'])}\" alt=\"Pre-decision auction chart\">"
            "</article>"
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gold all-transition pre-decision semantic atlas</title>
<style>body{margin:0;padding:24px;background:#eef2f6;color:#0f172a;font:14px Arial,sans-serif}.notice{max-width:1440px;margin:0 auto 20px;padding:16px;background:#fff;border:1px solid #cbd5e1}.card{max-width:1440px;margin:20px auto;padding:16px;background:#fff;border:1px solid #cbd5e1;box-shadow:0 3px 12px #0f172a18}.card img{display:block;width:100%;height:auto;border:1px solid #e2e8f0}h1,h2{margin:0 0 10px}code{font-size:11px}</style></head>
<body><section class="notice"><h1>Outcome-blind New York auction-transition atlas</h1><p>Every chart ends at its decision timestamp. No future candle or performance result is displayed. Examples were selected by direction, event class and month before any outcome calculation.</p></section>
""" + "\n".join(cards) + "\n</body></html>\n"


def write_event_ledger(events: list[dict[str, Any]]) -> None:
    require(not EVENT_LEDGER.exists(), f"Append-only ledger exists: {EVENT_LEDGER}")
    rows: list[dict[str, Any]] = []
    for event in events:
        macro = event["macro_context"]
        rows.append(
            {
                "event_identity": event["event_identity"],
                "case_alias": event["case_alias"],
                "trading_date_utc": event["trading_date_utc"],
                "decision_at": event["decision_at"],
                "direction": event["direction"],
                "event_class": event["event_class"],
                "new_break_timeframes": "+".join(event["new_break_timeframes"]),
                "macro_state": macro["state"],
                "macro_score": macro.get("score"),
                "h1_relations": htf_label(event, "H1"),
                "h4_relations": htf_label(event, "H4"),
                "local_destination_known": event["liquidity_destinations"]["nearest_local"] is not None,
                "htf_destination_known": event["liquidity_destinations"]["nearest_higher_timeframe"] is not None,
                "event_sha256": event["event_sha256"],
            }
        )
    EVENT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    temporary = EVENT_LEDGER.with_name(f".{EVENT_LEDGER.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary ledger exists: {temporary}")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["event_identity"])
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, EVENT_LEDGER)


def markdown(certification: dict[str, Any]) -> str:
    summary = certification["summary"]
    direction_class = summary["direction_by_class"]
    lines = [
        "# Gold All-Transition Auction Scanner Semantic Review V1 Report",
        "",
        f"Verdict: `{certification['verdict']}`",
        "",
        "This is an outcome-blind semantic checkpoint. No trades, outcomes, R, PnL, MFE, MAE, 2025, or 2026 data were opened.",
        "",
        "## Frequency",
        "",
        f"- Eligible New York days: **{summary['eligible_days']}**",
        f"- Total accepted auction events: **{summary['total_events']}**",
        f"- Days with at least one event: **{summary['days_with_events']}**",
        f"- Zero-event days: **{summary['zero_event_days']}**",
        f"- Mean / median events per day: **{summary['events_per_day']['mean']:.2f} / {summary['events_per_day']['median']:.2f}**",
        f"- Maximum events in one day: **{summary['events_per_day']['maximum']}**",
        "",
        "| Direction | Initial | Reversal | Reassertion | Continuation refresh | Total |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for direction in DIRECTIONS:
        values = direction_class.get(direction, {})
        total = sum(int(value) for value in values.values())
        lines.append(
            f"| {direction} | {values.get('INITIAL_CONTROL', 0)} | {values.get('REVERSAL_TRANSFER', 0)} | "
            f"{values.get('CONTROL_REASSERTION', 0)} | {values.get('CONTINUATION_REFRESH', 0)} | {total} |"
        )
    lines.extend(
        [
            "",
            "## Semantic disposition",
            "",
            "- LONG and SHORT use the same structural and acceptance definitions.",
            "- Normal same-direction continuation is emitted without requiring a failed opposite auction.",
            "- Macro and H1/H4 state are recorded as context, not used as vetoes.",
            "- Every chart and event ends at its completed-candle decision timestamp.",
            "- User semantic confirmation is required before any economic regression.",
            "",
            f"Review atlas: `{ATLAS.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    return "\n".join(lines)


def materialize() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY, REFERENCE, CERTIFICATION, EVENT_LEDGER, ATLAS, SEAL, REPORT):
        require(not path.exists(), f"One-shot output exists: {path}")
    require(not CHART_ROOT.exists(), f"Chart output exists: {CHART_ROOT}")

    primary = scan_side("primary", frozen)
    write_new_json(PRIMARY, primary)
    reference = scan_side("reference", frozen)
    write_new_json(REFERENCE, reference)
    require(primary["daily_counts"] == reference["daily_counts"], "Primary/reference daily counts differ")
    require(primary["events"] == reference["events"], "Primary/reference event fields differ")
    require(primary["events_sha256"] == reference["events_sha256"], "Primary/reference event hashes differ")

    events = primary["events"]
    summary = summarize(events, primary["daily_counts"])
    selected = select_examples(events)
    selected_identities = [item["event_identity"] for item in selected]
    print(
        json.dumps(
            {
                "checkpoint": "PRIMARY_REFERENCE_EVENTS_EXACT",
                "total_events": len(events),
                "direction": summary["direction"],
                "selected_examples": len(selected),
            },
            indent=2,
        ),
        flush=True,
    )

    primary_charts = render_chart_set(side="primary", events=primary["events"], selected=selected)
    reference_charts = render_chart_set(side="reference", events=reference["events"], selected=selected)
    require(primary_charts.keys() == reference_charts.keys(), "Chart filename sets differ")
    require(all(primary_charts[name] == reference_charts[name] for name in primary_charts), "Primary/reference chart bytes differ")
    chart_records: list[dict[str, Any]] = []
    for name, payload in primary_charts.items():
        path = CHART_ROOT / name
        _atomic_create(path, payload)
        chart_records.append(
            {
                "filename": name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    atlas = atlas_html(selected, chart_records)
    write_new_text(ATLAS, atlas)
    write_event_ledger(events)

    certification: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_AUCTION_SCANNER_SEMANTIC_REVIEW_V1_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": "PASS_OUTCOME_BLIND_ALL_TRANSITION_SEMANTIC_MATERIALIZATION_STOP_FOR_USER_REVIEW",
        "freeze_sha256": frozen["freeze_sha256"],
        "ruleset": RULESET,
        "primary_reference_exact": True,
        "events_sha256": primary["events_sha256"],
        "summary": summary,
        "selected_example_identities": selected_identities,
        "selected_example_identities_sha256": canonical_hash(selected_identities),
        "chart_records": chart_records,
        "chart_bytes_primary_reference_exact": True,
        "atlas": file_record(ATLAS),
        "outcomes_accessed": False,
        "performance_calculated": False,
        "execution_constructed": False,
        "february_17_28_opened": False,
        "july_2022_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    _assert_outcome_blind(
        {
            "summary": summary,
            "selected_example_identities": selected_identities,
            "performance_calculated": False,
        }
    )
    certification["certification_sha256"] = canonical_hash(certification)
    write_new_json(CERTIFICATION, certification)
    write_new_text(REPORT, markdown(certification))
    seal: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_AUCTION_SCANNER_SEMANTIC_REVIEW_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": certification["verdict"],
        "primary_reference_exact": True,
        "certification_sha256": certification["certification_sha256"],
        "files": [
            file_record(FREEZE),
            file_record(PRIMARY),
            file_record(REFERENCE),
            file_record(CERTIFICATION),
            file_record(EVENT_LEDGER),
            file_record(ATLAS),
            file_record(REPORT),
            *[file_record(CHART_ROOT / record["filename"]) for record in chart_records],
        ],
        "outcomes_accessed": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "summary": summary,
                "atlas": ATLAS.relative_to(ROOT).as_posix(),
                "certification_sha256": certification["certification_sha256"],
                "seal_sha256": seal["seal_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "materialize", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"materialize", "all"}:
        materialize()


if __name__ == "__main__":
    main()

