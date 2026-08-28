#!/usr/bin/env python3
"""Visualization-only pivot-anchored amendment for the sealed V1 atlas."""

from __future__ import annotations

import argparse
import gc
import hashlib
import html
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_all_transition_auction_scanner_semantic_review_v1 as base  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    confirmed_swings,
    parse_dt,
)


AMENDMENT = ROOT / "GOLD_ALL_TRANSITION_AUCTION_SCANNER_VISUALIZATION_AMENDMENT_A.md"
RUNNER = Path(__file__).resolve()
OUT = base.OUT
FREEZE = OUT / "visualization_amendment_a_freeze.json"
CHART_ROOT = OUT / "predecision_charts_v1_a"
ATLAS = OUT / "predecision_atlas_v1_a.html"
CERTIFICATION = OUT / "visualization_amendment_a_certification.json"
SEAL = OUT / "visualization_amendment_a_seal.json"
REPORT = ROOT / "GOLD_ALL_TRANSITION_AUCTION_SCANNER_VISUALIZATION_AMENDMENT_A_REPORT.md"

DEFAULT_LIMITS = {"4h": 42, "1h": 64, "15m": 84, "5m": 96}
MAXIMUM_LIMITS = {"4h": 100, "1h": 160, "15m": 240, "5m": 300}
TIMEFRAME_LABELS = {"4h": "H4", "1h": "H1", "15m": "M15", "5m": "M5"}
ROLE_PRIORITY = {
    "PROTECTED_SWING": 4,
    "CONSUMED_PIVOT": 3,
    "UNCONSUMED_DESTINATION": 2,
    "KNOWN_SWING_HIGH": 1,
    "KNOWN_SWING_LOW": 1,
}
ROLE_COLORS = {
    "PROTECTED_SWING": "#dc2626",
    "CONSUMED_PIVOT": "#2563eb",
    "UNCONSUMED_DESTINATION": "#7c3aed",
    "KNOWN_SWING_HIGH": "#64748b",
    "KNOWN_SWING_LOW": "#64748b",
}


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": base.sha256_file(path),
    }


def _atomic_create(path: Path, payload: bytes) -> None:
    require(not path.exists(), f"Append-only output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary output exists: {temporary}")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_create(
        path,
        (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
    )


def write_new_text(path: Path, payload: str) -> None:
    _atomic_create(path, payload.encode("utf-8"))


def verify_original() -> tuple[dict[str, Any], dict[str, Any]]:
    original_seal = load_json(base.SEAL)
    submitted = str(original_seal.pop("seal_sha256"))
    require(canonical_hash(original_seal) == submitted, "Original seal payload differs")
    for record in original_seal["files"]:
        base.verify_file_record(record)
    original_seal["seal_sha256"] = submitted
    certification = load_json(base.CERTIFICATION)
    cert_hash = str(certification.pop("certification_sha256"))
    require(canonical_hash(certification) == cert_hash, "Original certification differs")
    certification["certification_sha256"] = cert_hash
    require(certification["outcomes_accessed"] is False, "Original review accessed outcomes")
    require(certification["performance_calculated"] is False, "Original review calculated performance")
    return original_seal, certification


def freeze() -> None:
    for path in (FREEZE, CERTIFICATION, SEAL, REPORT, ATLAS):
        require(not path.exists(), f"Visualization amendment output exists: {path}")
    require(not CHART_ROOT.exists(), f"Visualization chart root exists: {CHART_ROOT}")
    original_seal, certification = verify_original()
    selected = list(certification["selected_example_identities"])
    payload: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_AUCTION_SCANNER_VISUALIZATION_AMENDMENT_A_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_VISUALIZATION_ONLY_RERENDER",
        "files": [file_record(AMENDMENT), file_record(RUNNER)],
        "original_seal_sha256": original_seal["seal_sha256"],
        "original_certification_sha256": certification["certification_sha256"],
        "original_events_sha256": certification["events_sha256"],
        "selected_example_identities": selected,
        "selected_example_identities_sha256": canonical_hash(selected),
        "default_limits": DEFAULT_LIMITS,
        "maximum_limits": MAXIMUM_LIMITS,
        "renderer_rules": {
            "level_requires_resolved_swing_identity": True,
            "marker_at_exact_pivot_candle_and_level": True,
            "ray_starts_at_pivot": True,
            "maximum_ray_fraction_of_panel": 0.22,
            "full_panel_level_lines_forbidden": True,
            "future_bars_forbidden": True,
        },
        "events_changed": False,
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(json.dumps({"status": payload["status"], "examples": len(selected), "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    require(FREEZE.is_file(), "Visualization amendment freeze is absent")
    frozen = load_json(FREEZE)
    submitted = str(frozen.pop("freeze_sha256"))
    require(canonical_hash(frozen) == submitted, "Visualization amendment freeze differs")
    frozen["freeze_sha256"] = submitted
    for record in frozen["files"]:
        base.verify_file_record(record)
    original_seal, certification = verify_original()
    require(original_seal["seal_sha256"] == frozen["original_seal_sha256"], "Original seal changed")
    require(certification["certification_sha256"] == frozen["original_certification_sha256"], "Original certification changed")
    require(certification["events_sha256"] == frozen["original_events_sha256"], "Original event payload changed")
    require(certification["selected_example_identities"] == frozen["selected_example_identities"], "Selected examples changed")
    return frozen, certification


def requested_levels(event: dict[str, Any], timeframe: str) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []

    def append(identity: Any, level: Any, role: str) -> None:
        if identity is None or level is None:
            return
        requests.append(
            {
                "identity": str(identity),
                "expected_level": float(level),
                "role": role,
            }
        )

    if timeframe in {"M5", "M15"}:
        active = event["active_breaks"][timeframe]
        if active is not None:
            append(active["broken_identity"], active["broken_level"], "CONSUMED_PIVOT")
            append(active["protected_identity"], active["protected_level"], "PROTECTED_SWING")
    else:
        context = event["higher_timeframe_context"][timeframe]
        append(context["latest_high_identity"], context["latest_high_level"], "KNOWN_SWING_HIGH")
        append(context["latest_low_identity"], context["latest_low_level"], "KNOWN_SWING_LOW")
    destination = event["liquidity_destinations"]["by_timeframe"].get(timeframe)
    if destination is not None:
        append(destination["identity"], destination["level"], "UNCONSUMED_DESTINATION")
    return requests


def resolve_anchors(
    stream: dict[str, Any], event: dict[str, Any], timeframe: str, key: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, swings = confirmed_swings(stream["timeframes"][key], event["decision_at"], timeframe)
    swing_by_identity = {str(item["identity"]): item for item in swings}
    grouped: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for request in requested_levels(event, timeframe):
        swing = swing_by_identity.get(request["identity"])
        if swing is None:
            unresolved.append({**request, "reason": "IDENTITY_NOT_FOUND_POINT_IN_TIME"})
            continue
        require(
            abs(float(swing["level"]) - float(request["expected_level"])) <= 1e-8,
            f"Level differs for {request['identity']}",
        )
        anchor = grouped.setdefault(
            request["identity"],
            {
                "identity": request["identity"],
                "kind": str(swing["kind"]),
                "level": float(swing["level"]),
                "pivot_at": str(swing["pivot_at"]),
                "known_at": str(swing["detected_at"]),
                "roles": [],
            },
        )
        anchor["roles"].append(request["role"])
    output: list[dict[str, Any]] = []
    for anchor in grouped.values():
        anchor["roles"] = sorted(set(anchor["roles"]), key=lambda role: (-ROLE_PRIORITY[role], role))
        primary_role = anchor["roles"][0]
        anchor["color"] = ROLE_COLORS[primary_role]
        output.append(anchor)
    output.sort(key=lambda item: (parse_dt(item["pivot_at"]), item["identity"]))
    return output, unresolved


def visible_window(
    rows: list[dict[str, Any]], cutoff: str, anchors: list[dict[str, Any]], key: str
) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    bars = complete_rows(rows, cutoff)
    open_index = {str(row["open_at"]): index for index, row in enumerate(bars)}
    anchor_indices = [open_index[item["pivot_at"]] for item in anchors if item["pivot_at"] in open_index]
    default_start = max(0, len(bars) - DEFAULT_LIMITS[key])
    requested_start = min([default_start, *(max(0, index - 3) for index in anchor_indices)])
    start = max(requested_start, len(bars) - MAXIMUM_LIMITS[key])
    visible = bars[start:]
    visible_index = {str(row["open_at"]): index for index, row in enumerate(visible)}
    omitted = [
        {**item, "reason": "PIVOT_PRECEDES_MAXIMUM_VISIBLE_WINDOW"}
        for item in anchors
        if item["pivot_at"] not in visible_index
    ]
    require(all(parse_dt(row["available_at"]) <= parse_dt(cutoff) for row in visible), "Future chart bar leaked")
    return visible, visible_index, omitted


def text(x: float, y: float, value: str, *, size: int = 12, color: str = "#334155", weight: int = 400) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{color}">{html.escape(value)}</text>'
    )


def fmt(value: Any) -> str:
    return "UNKNOWN" if value is None else f"{float(value):.2f}"


def render(stream: dict[str, Any], event: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    width, height = 1500, 980
    left, right = 78, 42
    header = 116
    panel_height = 198
    panel_gap = 17
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    macro = event["macro_context"]
    parts.append(
        text(
            30,
            34,
            f"{event['trading_date_utc']} {event['decision_at'][11:16]} UTC | {event['direction']} {event['event_class']} | M5/M15 accepted control",
            size=19,
            color="#0f172a",
            weight=700,
        )
    )
    parts.append(
        text(
            30,
            61,
            f"Macro {macro['state']} score={fmt(macro.get('score'))} confidence={fmt(macro.get('confidence'))} driver={macro.get('dominant_driver') or 'UNKNOWN'}",
            size=13,
        )
    )
    parts.append(
        text(
            30,
            87,
            "Each diamond marks the exact source pivot candle. The short ray begins there; no full-width level lines are used.",
            size=12,
            color="#475569",
        )
    )
    diagnostics: dict[str, Any] = {
        "event_identity": event["event_identity"],
        "timeframes": {},
        "future_bars": 0,
        "maximum_ray_fraction": 0.0,
    }
    for panel_index, (key, default_limit) in enumerate(DEFAULT_LIMITS.items()):
        timeframe = TIMEFRAME_LABELS[key]
        y0 = header + panel_index * (panel_height + panel_gap)
        anchors, unresolved = resolve_anchors(stream, event, timeframe, key)
        bars, visible_index, omitted = visible_window(
            stream["timeframes"][key], event["decision_at"], anchors, key
        )
        require(bars, f"No visible {timeframe} bars")
        displayed = [item for item in anchors if item["pivot_at"] in visible_index]
        prices = [float(value) for row in bars for value in (row["low"], row["high"])]
        prices.extend(float(item["level"]) for item in displayed)
        low, high = min(prices), max(prices)
        span = max(high - low, 0.01)
        low -= span * 0.06
        high += span * 0.06
        chart_left, chart_right = left, width - right
        chart_top, chart_bottom = y0 + 25, y0 + panel_height - 25
        chart_width = chart_right - chart_left
        chart_height = chart_bottom - chart_top

        def py(price: float) -> float:
            return chart_bottom - (price - low) / (high - low) * chart_height

        parts.append(
            f'<rect x="{chart_left}" y="{chart_top}" width="{chart_width}" height="{chart_height}" fill="#f8fafc" stroke="#e2e8f0"/>'
        )
        parts.append(text(18, y0 + 18, timeframe, size=13, color="#0f172a", weight=700))
        for grid in range(1, 4):
            gy = chart_top + grid * chart_height / 4
            parts.append(
                f'<line x1="{chart_left}" y1="{gy:.1f}" x2="{chart_right}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="1"/>'
            )
        step = chart_width / len(bars)
        body_width = max(1.8, min(9.0, step * 0.62))
        for index, bar in enumerate(bars):
            x = chart_left + (index + 0.5) * step
            open_price, close_price = float(bar["open"]), float(bar["close"])
            color = "#089981" if close_price >= open_price else "#f23645"
            parts.append(
                f'<line x1="{x:.1f}" y1="{py(float(bar["high"])):.1f}" x2="{x:.1f}" y2="{py(float(bar["low"])):.1f}" stroke="{color}" stroke-width="1"/>'
            )
            top = min(py(open_price), py(close_price))
            body_height = max(1.2, abs(py(open_price) - py(close_price)))
            parts.append(
                f'<rect x="{x-body_width/2:.1f}" y="{top:.1f}" width="{body_width:.1f}" height="{body_height:.1f}" fill="{color}"/>'
            )

        label_specs: list[dict[str, Any]] = []
        for anchor in displayed:
            index = visible_index[anchor["pivot_at"]]
            x = chart_left + (index + 0.5) * step
            y = py(float(anchor["level"]))
            ray = min(chart_width * 0.22, max(72.0, step * 14))
            ray_end = min(chart_right - 8, x + ray)
            actual_fraction = (ray_end - x) / chart_width
            diagnostics["maximum_ray_fraction"] = max(
                diagnostics["maximum_ray_fraction"], actual_fraction
            )
            parts.append(
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{ray_end:.1f}" y2="{y:.1f}" stroke="{anchor["color"]}" stroke-width="1.6" stroke-dasharray="7 4"/>'
            )
            diamond = f"{x:.1f},{y-5:.1f} {x+5:.1f},{y:.1f} {x:.1f},{y+5:.1f} {x-5:.1f},{y:.1f}"
            parts.append(
                f'<polygon points="{diamond}" fill="{anchor["color"]}" stroke="#ffffff" stroke-width="1"/>'
            )
            role_text = "/".join(role.lower().replace("_", " ") for role in anchor["roles"])
            pivot_text = str(anchor["pivot_at"])[5:16].replace("T", " ")
            label_specs.append(
                {
                    "x": min(ray_end + 6, chart_right - 315),
                    "actual_y": y,
                    "label_y": y,
                    "color": anchor["color"],
                    "text": f"{role_text} {anchor['kind'].lower()} {fmt(anchor['level'])} @ {pivot_text}",
                }
            )
        # Deterministic collision avoidance moves labels, not their level rays
        # or source markers. A connector retains the exact association.
        label_specs.sort(key=lambda item: (item["label_y"], item["text"]))
        prior_y = chart_top - 14
        for spec in label_specs:
            spec["label_y"] = max(spec["label_y"], prior_y + 14)
            prior_y = spec["label_y"]
        overflow = max([0.0, *(spec["label_y"] - (chart_bottom - 3) for spec in label_specs)])
        if overflow > 0:
            for spec in label_specs:
                spec["label_y"] -= overflow
        for spec in label_specs:
            label_y = spec["label_y"]
            parts.append(
                f'<line x1="{spec["x"]-5:.1f}" y1="{spec["actual_y"]:.1f}" x2="{spec["x"]:.1f}" y2="{label_y-4:.1f}" stroke="{spec["color"]}" stroke-width="1"/>'
            )
            box_width = min(310, max(150, len(spec["text"]) * 5.8))
            parts.append(
                f'<rect x="{spec["x"]-2:.1f}" y="{label_y-13:.1f}" width="{box_width:.1f}" height="15" rx="2" fill="#ffffff" fill-opacity="0.90"/>'
            )
            parts.append(
                text(spec["x"], label_y - 2, spec["text"], size=9, color=spec["color"], weight=600)
            )
        if unresolved or omitted:
            message = f"Not plotted: {len(unresolved)} unresolved identities, {len(omitted)} pivots before visible cap"
            parts.append(text(chart_left + 8, chart_top + 14, message, size=9, color="#b45309", weight=600))
        first_at = str(bars[0]["open_at"])[5:16].replace("T", " ")
        last_at = str(bars[-1]["available_at"])[5:16].replace("T", " ")
        parts.append(text(chart_left, chart_bottom + 17, first_at, size=10, color="#64748b"))
        parts.append(text(chart_right - 105, chart_bottom + 17, last_at, size=10, color="#64748b"))
        diagnostics["timeframes"][timeframe] = {
            "default_bars": default_limit,
            "rendered_bars": len(bars),
            "requested_levels": len(requested_levels(event, timeframe)),
            "resolved_unique_anchors": len(anchors),
            "displayed_unique_anchors": len(displayed),
            "unresolved": unresolved,
            "omitted": omitted,
        }
    parts.append("</svg>")
    payload = "\n".join(parts).encode("utf-8")
    require(b"outcome" not in payload.lower() and b"pnl" not in payload.lower(), "Performance text leaked")
    require(diagnostics["maximum_ray_fraction"] <= 0.2200001, "Ray exceeds frozen short-span gate")
    diagnostics["diagnostics_sha256"] = canonical_hash(diagnostics)
    return payload, diagnostics


def render_side(
    side: str,
    selected: list[str],
    event_payload: dict[str, Any],
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    events = {item["event_identity"]: item for item in event_payload["events"]}
    streams = source.load_streams(side)
    charts: dict[str, bytes] = {}
    diagnostics: list[dict[str, Any]] = []
    for index, identity in enumerate(selected, start=1):
        event = events[identity]
        filename = (
            f"{index:02d}_{event['direction'].lower()}_{event['event_class'].lower()}_"
            f"{event['trading_date_utc']}_{identity[:10]}.svg"
        )
        payload, diagnostic = render(streams[event["case_alias"]], event)
        charts[filename] = payload
        diagnostics.append(diagnostic)
    del streams
    gc.collect()
    return charts, diagnostics


def atlas_html(
    selected: list[str], events: dict[str, dict[str, Any]], records: list[dict[str, Any]]
) -> str:
    cards: list[str] = []
    for identity, record in zip(selected, records, strict=True):
        event = events[identity]
        cards.append(
            '<article class="card">'
            f"<h2>{html.escape(event['direction'])} · {html.escape(event['event_class'])} · {html.escape(event['decision_at'])}</h2>"
            f"<p>Diamonds identify the precise pivot candles. Event <code>{html.escape(identity)}</code></p>"
            f"<img src=\"predecision_charts_v1_a/{html.escape(record['filename'])}\" alt=\"Pivot-anchored pre-decision chart\">"
            "</article>"
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pivot-anchored gold auction semantic atlas</title>
<style>body{margin:0;padding:24px;background:#eef2f6;color:#0f172a;font:14px Arial,sans-serif}.notice{max-width:1500px;margin:0 auto 20px;padding:16px;background:#fff;border:1px solid #cbd5e1}.card{max-width:1500px;margin:20px auto;padding:16px;background:#fff;border:1px solid #cbd5e1;box-shadow:0 3px 12px #0f172a18}.card img{display:block;width:100%;height:auto;border:1px solid #e2e8f0}h1,h2{margin:0 0 10px}code{font-size:11px}</style></head>
<body><section class="notice"><h1>Pivot-anchored outcome-blind New York atlas</h1><p>Every structural label begins at the exact swing candle marked by a diamond. Rays are deliberately short. All charts end at the decision timestamp and contain no future candle or performance result.</p></section>
""" + "\n".join(cards) + "\n</body></html>\n"


def markdown(certification: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Gold All-Transition Auction Scanner Visualization Amendment A Report",
            "",
            f"Verdict: `{certification['verdict']}`",
            "",
            "- The sealed 729-event census is unchanged.",
            "- All 24 selected example identities are unchanged.",
            "- Every plotted structural level is anchored to its exact confirmed pivot candle.",
            "- Every ray begins at that pivot and spans no more than 22% of its panel.",
            f"- Unresolved identities: `{certification['diagnostic_totals']['unresolved_identities']}`.",
            f"- Pivots omitted by the display cap: `{certification['diagnostic_totals']['omitted_pivots']}`.",
            "- Primary/reference SVG bytes and diagnostics match exactly.",
            "- No outcomes or performance fields were accessed.",
            "",
            f"Corrected atlas: `{ATLAS.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )


def render_all() -> None:
    frozen, original_certification = verify_freeze()
    for path in (ATLAS, CERTIFICATION, SEAL, REPORT):
        require(not path.exists(), f"Visualization output exists: {path}")
    require(not CHART_ROOT.exists(), f"Visualization chart root exists: {CHART_ROOT}")
    primary_events = load_json(base.PRIMARY)
    reference_events = load_json(base.REFERENCE)
    require(primary_events["events"] == reference_events["events"], "Original event reproductions differ")
    selected = list(frozen["selected_example_identities"])
    primary_charts, primary_diagnostics = render_side("primary", selected, primary_events)
    reference_charts, reference_diagnostics = render_side("reference", selected, reference_events)
    require(primary_charts.keys() == reference_charts.keys(), "Chart names differ")
    require(all(primary_charts[name] == reference_charts[name] for name in primary_charts), "Chart bytes differ")
    require(primary_diagnostics == reference_diagnostics, "Chart diagnostics differ")

    unresolved = sum(
        len(frame["unresolved"])
        for item in primary_diagnostics
        for frame in item["timeframes"].values()
    )
    omitted = sum(
        len(frame["omitted"])
        for item in primary_diagnostics
        for frame in item["timeframes"].values()
    )
    require(unresolved == 0, f"Unresolved pivot identities: {unresolved}")
    records: list[dict[str, Any]] = []
    for filename, payload in primary_charts.items():
        path = CHART_ROOT / filename
        _atomic_create(path, payload)
        records.append(
            {
                "filename": filename,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    event_map = {item["event_identity"]: item for item in primary_events["events"]}
    write_new_text(ATLAS, atlas_html(selected, event_map, records))
    certification: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_AUCTION_SCANNER_VISUALIZATION_AMENDMENT_A_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": "PASS_PIVOT_ANCHORED_VISUALIZATION_STOP_FOR_USER_REVIEW",
        "freeze_sha256": frozen["freeze_sha256"],
        "original_certification_sha256": original_certification["certification_sha256"],
        "original_events_sha256": original_certification["events_sha256"],
        "selected_example_identities_sha256": frozen["selected_example_identities_sha256"],
        "event_count_unchanged": 729,
        "selected_examples": len(selected),
        "primary_reference_chart_bytes_exact": True,
        "primary_reference_diagnostics_exact": True,
        "chart_records": records,
        "diagnostics": primary_diagnostics,
        "diagnostic_totals": {
            "unresolved_identities": unresolved,
            "omitted_pivots": omitted,
            "maximum_ray_fraction": max(item["maximum_ray_fraction"] for item in primary_diagnostics),
        },
        "atlas": file_record(ATLAS),
        "events_changed": False,
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    certification["certification_sha256"] = canonical_hash(certification)
    write_new_json(CERTIFICATION, certification)
    write_new_text(REPORT, markdown(certification))
    seal: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_AUCTION_SCANNER_VISUALIZATION_AMENDMENT_A_SEAL_1_0",
        "sealed_at": now(),
        "verdict": certification["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "original_seal_sha256": frozen["original_seal_sha256"],
        "files": [
            file_record(FREEZE),
            file_record(ATLAS),
            file_record(CERTIFICATION),
            file_record(REPORT),
            *[file_record(CHART_ROOT / record["filename"]) for record in records],
        ],
        "outcomes_accessed": False,
        "performance_calculated": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "event_count_unchanged": 729,
                "selected_examples": len(selected),
                "diagnostic_totals": certification["diagnostic_totals"],
                "atlas": ATLAS.relative_to(ROOT).as_posix(),
                "certification_sha256": certification["certification_sha256"],
                "seal_sha256": seal["seal_sha256"],
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "render", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"render", "all"}:
        render_all()


if __name__ == "__main__":
    main()

