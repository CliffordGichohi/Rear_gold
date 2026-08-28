#!/usr/bin/env python3
"""Certify corrected liquidity and range semantics over sealed auction events."""

from __future__ import annotations

import argparse
import gc
import hashlib
import html
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import render_gold_all_transition_auction_semantic_atlas_v1_a as visual_a  # noqa: E402
import run_gold_all_transition_auction_scanner_semantic_review_v1 as base  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.all_transition_auction_scanner_v1 import (  # noqa: E402
    _assert_outcome_blind,
)
from gold_intel.analytics.auction_liquidity_range_semantics_v1 import (  # noqa: E402
    RANGE_MAX_WIDTH_ATR,
    RANGE_REJECTION_PROXIMITY_ATR,
    RANGE_WINDOW_BARS,
    RULESET,
    event_semantic_overlay,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    confirmed_swings,
    parse_dt,
)


AMENDMENT = ROOT / "GOLD_ALL_TRANSITION_AUCTION_SCANNER_LIQUIDITY_AND_RANGE_SEMANTICS_AMENDMENT_B.md"
IMPLEMENTATION = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "auction_liquidity_range_semantics_v1.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_liquidity_range_semantics_v1.py"
RUNNER = Path(__file__).resolve()
GOVERNING_DIAGRAM = Path(r"C:\Users\USER\Downloads\market instructs.svg")

OUT = base.OUT
FREEZE = OUT / "liquidity_range_amendment_b_freeze.json"
PRIMARY = OUT / "liquidity_range_amendment_b.primary.json"
REFERENCE = OUT / "liquidity_range_amendment_b.reference.json"
CHART_ROOT = OUT / "predecision_charts_v1_b"
ATLAS = OUT / "predecision_atlas_v1_b.html"
CERTIFICATION = OUT / "liquidity_range_amendment_b_certification.json"
SEAL = OUT / "liquidity_range_amendment_b_seal.json"
REPORT = ROOT / "GOLD_ALL_TRANSITION_AUCTION_SCANNER_LIQUIDITY_AND_RANGE_SEMANTICS_AMENDMENT_B_REPORT.md"

DEFAULT_LIMITS = {"4h": 42, "1h": 64, "15m": 84, "5m": 96}
MAXIMUM_LIMITS = {"4h": 100, "1h": 160, "15m": 240, "5m": 300}
TIMEFRAME_LABELS = {"4h": "H4", "1h": "H1", "15m": "M15", "5m": "M5"}
ROLE_PRIORITY = {
    "PROTECTED_INTERNAL_PIVOT": 5,
    "CONSUMED_CONTROL_PIVOT": 4,
    "ACTIVE_RANGE_HIGH": 3,
    "ACTIVE_RANGE_LOW": 3,
    "UNCONSUMED_DESTINATION": 2,
}
ROLE_COLORS = {
    "PROTECTED_INTERNAL_PIVOT": "#dc2626",
    "CONSUMED_CONTROL_PIVOT": "#2563eb",
    "ACTIVE_RANGE_HIGH": "#0f766e",
    "ACTIVE_RANGE_LOW": "#0f766e",
    "UNCONSUMED_DESTINATION": "#7c3aed",
}


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


def external_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def verify_record(record: dict[str, Any]) -> None:
    base.verify_file_record(record)


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


def verify_visual_a() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    original_seal, original_certification = visual_a.verify_original()
    amendment_seal = load_json(visual_a.SEAL)
    submitted = str(amendment_seal.pop("seal_sha256"))
    require(canonical_hash(amendment_seal) == submitted, "Visualization Amendment A seal differs")
    for record in amendment_seal["files"]:
        verify_record(record)
    amendment_seal["seal_sha256"] = submitted
    require(
        amendment_seal["verdict"] == "PASS_PIVOT_ANCHORED_VISUALIZATION_STOP_FOR_USER_REVIEW",
        "Visualization Amendment A verdict differs",
    )
    return original_seal, original_certification, amendment_seal


def synthetic_proof() -> dict[str, Any]:
    from backend.tests.unit import test_auction_liquidity_range_semantics_v1 as tests

    names = sorted(name for name in dir(tests) if name.startswith("test_"))
    for name in names:
        getattr(tests, name)()
    payload = {"tests": names, "passed": len(names), "failed": 0}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def freeze() -> None:
    for path in (FREEZE, PRIMARY, REFERENCE, ATLAS, CERTIFICATION, SEAL, REPORT):
        require(not path.exists(), f"Amendment B output exists: {path}")
    require(not CHART_ROOT.exists(), f"Amendment B chart root exists: {CHART_ROOT}")
    require(GOVERNING_DIAGRAM.is_file(), "Governing market-structure diagram is absent")
    original_seal, original_certification, amendment_a_seal = verify_visual_a()
    frozen: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_LIQUIDITY_RANGE_AMENDMENT_B_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_CORRECTED_OUTCOME_BLIND_SEMANTIC_OVERLAY",
        "ruleset": RULESET,
        "files": [file_record(path) for path in (AMENDMENT, IMPLEMENTATION, TESTS, RUNNER)],
        "governing_diagram": external_record(GOVERNING_DIAGRAM),
        "predecessors": {
            "original_seal_sha256": original_seal["seal_sha256"],
            "original_certification_sha256": original_certification["certification_sha256"],
            "original_events_sha256": original_certification["events_sha256"],
            "visualization_amendment_a_seal_sha256": amendment_a_seal["seal_sha256"],
        },
        "event_count_unchanged": 729,
        "selected_example_identities": original_certification["selected_example_identities"],
        "selected_example_identities_sha256": original_certification[
            "selected_example_identities_sha256"
        ],
        "liquidity_rule": {
            "high_consumed": "LATER_OBSERVED_TRADED_PRICE_STRICTLY_ABOVE_CONFIRMED_HIGH",
            "low_consumed": "LATER_OBSERVED_TRADED_PRICE_STRICTLY_BELOW_CONFIRMED_LOW",
            "equal_price": "ENGAGED_NOT_CONSUMED",
            "atr_buffer": None,
            "close_required": False,
            "acceptance_required": False,
            "permanent_after_consumption": True,
        },
        "range_rule": {
            "window_bars": RANGE_WINDOW_BARS,
            "minimum_confirmed_highs": 2,
            "minimum_confirmed_lows": 2,
            "rejection_proximity_atr": RANGE_REJECTION_PROXIMITY_ATR,
            "maximum_width_atr": RANGE_MAX_WIDTH_ATR,
            "exact_boundaries_must_be_unconsumed": True,
            "decision_price_must_be_inside": True,
            "same_m5_m15_control_trigger": True,
        },
        "chart_rules": {
            "exact_pivot_identity_required": True,
            "maximum_ray_fraction": 0.22,
            "full_width_lines_forbidden": True,
            "generic_unqualified_levels_forbidden": True,
        },
        "synthetic_proof": synthetic_proof(),
        "original_events_changed": False,
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    frozen["freeze_sha256"] = canonical_hash(frozen)
    write_new_json(FREEZE, frozen)
    print(
        json.dumps(
            {
                "status": frozen["status"],
                "event_count": frozen["event_count_unchanged"],
                "synthetic_tests": frozen["synthetic_proof"]["passed"],
                "freeze_sha256": frozen["freeze_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Amendment B freeze is absent")
    frozen = load_json(FREEZE)
    submitted = str(frozen.pop("freeze_sha256"))
    require(canonical_hash(frozen) == submitted, "Amendment B freeze payload differs")
    frozen["freeze_sha256"] = submitted
    for record in frozen["files"]:
        verify_record(record)
    require(external_record(GOVERNING_DIAGRAM) == frozen["governing_diagram"], "Governing diagram differs")
    original_seal, original_certification, amendment_a_seal = verify_visual_a()
    require(original_seal["seal_sha256"] == frozen["predecessors"]["original_seal_sha256"], "Original seal changed")
    require(
        original_certification["certification_sha256"]
        == frozen["predecessors"]["original_certification_sha256"],
        "Original certification changed",
    )
    require(
        original_certification["events_sha256"] == frozen["predecessors"]["original_events_sha256"],
        "Original events changed",
    )
    require(
        amendment_a_seal["seal_sha256"]
        == frozen["predecessors"]["visualization_amendment_a_seal_sha256"],
        "Visualization Amendment A seal changed",
    )
    return frozen


def level_requests(overlay: dict[str, Any], timeframe: str) -> list[dict[str, Any]]:
    frame = overlay["timeframes"][timeframe]
    requests: list[dict[str, Any]] = []

    def append(item: dict[str, Any] | None, role: str) -> None:
        if item is None:
            return
        requests.append(
            {
                "identity": str(item["identity"]),
                "expected_level": float(item["level"]),
                "state": str(item["state"]),
                "consumed_at": item.get("consumed_at"),
                "role": role,
            }
        )

    active = frame.get("active_control_roles")
    if active is not None:
        append(active.get("broken_control_pivot"), "CONSUMED_CONTROL_PIVOT")
        append(active.get("protected_internal_pivot"), "PROTECTED_INTERNAL_PIVOT")
    append(frame.get("nearest_unconsumed_destination"), "UNCONSUMED_DESTINATION")
    range_context = frame.get("range")
    if range_context is not None and range_context["state"] == "ACTIVE_RANGE":
        append(range_context["lower_boundary"], "ACTIVE_RANGE_LOW")
        append(range_context["upper_boundary"], "ACTIVE_RANGE_HIGH")
    return requests


def resolve_anchors(
    stream: dict[str, Any], overlay: dict[str, Any], timeframe: str, key: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, swings = confirmed_swings(stream["timeframes"][key], overlay["decision_at"], timeframe)
    swing_by_identity = {str(item["identity"]): item for item in swings}
    grouped: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for request in level_requests(overlay, timeframe):
        swing = swing_by_identity.get(request["identity"])
        if swing is None:
            unresolved.append({**request, "reason": "IDENTITY_NOT_FOUND_POINT_IN_TIME"})
            continue
        require(
            float(swing["level"]) == float(request["expected_level"]),
            f"Pivot level differs: {request['identity']}",
        )
        anchor = grouped.setdefault(
            request["identity"],
            {
                "identity": request["identity"],
                "kind": str(swing["kind"]),
                "level": float(swing["level"]),
                "pivot_at": str(swing["pivot_at"]),
                "known_at": str(swing["detected_at"]),
                "state": request["state"],
                "consumed_at": request["consumed_at"],
                "roles": [],
            },
        )
        require(anchor["state"] == request["state"], f"Conflicting lifecycle: {request['identity']}")
        anchor["roles"].append(request["role"])
    output: list[dict[str, Any]] = []
    for anchor in grouped.values():
        anchor["roles"] = sorted(
            set(anchor["roles"]), key=lambda role: (-ROLE_PRIORITY[role], role)
        )
        anchor["color"] = ROLE_COLORS[anchor["roles"][0]]
        output.append(anchor)
    output.sort(key=lambda item: (parse_dt(item["pivot_at"]), item["identity"]))
    return output, unresolved


def visible_window(
    rows: list[dict[str, Any]], cutoff: str, anchors: list[dict[str, Any]], key: str
) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    bars = complete_rows(rows, cutoff)
    open_index = {str(row["open_at"]): index for index, row in enumerate(bars)}
    indices = [open_index[item["pivot_at"]] for item in anchors if item["pivot_at"] in open_index]
    default_start = max(0, len(bars) - DEFAULT_LIMITS[key])
    requested_start = min([default_start, *(max(0, index - 3) for index in indices)])
    start = max(requested_start, len(bars) - MAXIMUM_LIMITS[key])
    visible = bars[start:]
    visible_index = {str(row["open_at"]): index for index, row in enumerate(visible)}
    omitted = [
        {**item, "reason": "PIVOT_PRECEDES_MAXIMUM_VISIBLE_WINDOW"}
        for item in anchors
        if item["pivot_at"] not in visible_index
    ]
    require(
        all(parse_dt(row["available_at"]) <= parse_dt(cutoff) for row in visible),
        "Future chart bar leaked",
    )
    return visible, visible_index, omitted


def svg_text(
    x: float,
    y: float,
    value: str,
    *,
    size: int = 12,
    color: str = "#334155",
    weight: int = 400,
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{color}">{html.escape(value)}</text>'
    )


def fmt(value: Any) -> str:
    return "UNKNOWN" if value is None else f"{float(value):.2f}"


def render_chart(
    stream: dict[str, Any], event: dict[str, Any], overlay: dict[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    width, height = 1500, 1035
    left, right = 78, 42
    header = 145
    panel_height = 198
    panel_gap = 17
    macro = event["macro_context"]
    h4_range = overlay["timeframes"]["H4"].get("range", {})
    h1_range = overlay["timeframes"]["H1"].get("range", {})
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        svg_text(
            30,
            32,
            f"{event['trading_date_utc']} {event['decision_at'][11:16]} UTC | {event['direction']} {event['event_class']}",
            size=19,
            color="#0f172a",
            weight=700,
        ),
        svg_text(30, 58, f"Context: {overlay['context_family']}", size=14, color="#0f172a", weight=700),
        svg_text(
            30,
            82,
            f"Macro context only: {macro['state']} score={fmt(macro.get('score'))} driver={macro.get('dominant_driver') or 'UNKNOWN'}",
            size=12,
        ),
        svg_text(
            30,
            104,
            f"H4 range={h4_range.get('state', 'N/A')} | H1 range={h1_range.get('state', 'N/A')}",
            size=12,
            color="#475569",
        ),
        svg_text(
            30,
            126,
            "Consumption = later traded price strictly beyond the exact pivot. Equality is engagement. Short rays start at source pivots.",
            size=11,
            color="#475569",
        ),
    ]
    diagnostics: dict[str, Any] = {
        "event_identity": event["event_identity"],
        "timeframes": {},
        "future_bars": 0,
        "maximum_ray_fraction": 0.0,
    }

    for panel_index, (key, default_limit) in enumerate(DEFAULT_LIMITS.items()):
        timeframe = TIMEFRAME_LABELS[key]
        y0 = header + panel_index * (panel_height + panel_gap)
        anchors, unresolved = resolve_anchors(stream, overlay, timeframe, key)
        bars, visible_index, omitted = visible_window(
            stream["timeframes"][key], overlay["decision_at"], anchors, key
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
        structure = overlay["timeframes"][timeframe]["structure"]["state"]
        range_state = overlay["timeframes"][timeframe].get("range", {}).get("state")
        caption = f"{timeframe} | {structure}"
        if range_state is not None:
            caption += f" | {range_state}"
        parts.append(svg_text(18, y0 + 18, caption, size=12, color="#0f172a", weight=700))
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

        labels: list[dict[str, Any]] = []
        for anchor in displayed:
            index = visible_index[anchor["pivot_at"]]
            x = chart_left + (index + 0.5) * step
            y = py(float(anchor["level"]))
            ray = min(chart_width * 0.22, max(72.0, step * 14))
            ray_end = min(chart_right - 8, x + ray)
            diagnostics["maximum_ray_fraction"] = max(
                diagnostics["maximum_ray_fraction"], (ray_end - x) / chart_width
            )
            parts.append(
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{ray_end:.1f}" y2="{y:.1f}" stroke="{anchor["color"]}" stroke-width="1.6" stroke-dasharray="7 4"/>'
            )
            diamond = f"{x:.1f},{y-5:.1f} {x+5:.1f},{y:.1f} {x:.1f},{y+5:.1f} {x-5:.1f},{y:.1f}"
            parts.append(
                f'<polygon points="{diamond}" fill="{anchor["color"]}" stroke="#ffffff" stroke-width="1"/>'
            )
            role = "/".join(item.lower().replace("_", " ") for item in anchor["roles"])
            pivot = str(anchor["pivot_at"])[5:16].replace("T", " ")
            state = str(anchor["state"]).lower().replace("_", " ")
            suffix = (
                f" consumed {str(anchor['consumed_at'])[5:16].replace('T', ' ')}"
                if anchor["consumed_at"] is not None
                else ""
            )
            labels.append(
                {
                    "x": min(ray_end + 6, chart_right - 405),
                    "actual_y": y,
                    "label_y": y,
                    "color": anchor["color"],
                    "text": f"{role} | {anchor['kind'].lower()} {fmt(anchor['level'])} @ {pivot} | {state}{suffix}",
                }
            )
        labels.sort(key=lambda item: (item["label_y"], item["text"]))
        prior_y = chart_top - 14
        for spec in labels:
            spec["label_y"] = max(spec["label_y"], prior_y + 14)
            prior_y = spec["label_y"]
        overflow = max([0.0, *(item["label_y"] - (chart_bottom - 3) for item in labels)])
        if overflow > 0:
            for spec in labels:
                spec["label_y"] -= overflow
        for spec in labels:
            label_y = spec["label_y"]
            parts.append(
                f'<line x1="{spec["x"]-5:.1f}" y1="{spec["actual_y"]:.1f}" x2="{spec["x"]:.1f}" y2="{label_y-4:.1f}" stroke="{spec["color"]}" stroke-width="1"/>'
            )
            box_width = min(400, max(180, len(spec["text"]) * 5.4))
            parts.append(
                f'<rect x="{spec["x"]-2:.1f}" y="{label_y-13:.1f}" width="{box_width:.1f}" height="15" rx="2" fill="#ffffff" fill-opacity="0.92"/>'
            )
            parts.append(svg_text(spec["x"], label_y - 2, spec["text"], size=8, color=spec["color"], weight=600))
        if not displayed:
            parts.append(
                svg_text(
                    chart_left + 8,
                    chart_top + 14,
                    "No qualified semantic pivot for this panel at the decision timestamp",
                    size=9,
                    color="#64748b",
                )
            )
        if unresolved or omitted:
            parts.append(
                svg_text(
                    chart_left + 8,
                    chart_top + 28,
                    f"Not plotted: {len(unresolved)} unresolved, {len(omitted)} before visible cap",
                    size=9,
                    color="#b45309",
                    weight=600,
                )
            )
        first_at = str(bars[0]["open_at"])[5:16].replace("T", " ")
        last_at = str(bars[-1]["available_at"])[5:16].replace("T", " ")
        parts.append(svg_text(chart_left, chart_bottom + 17, first_at, size=10, color="#64748b"))
        parts.append(svg_text(chart_right - 105, chart_bottom + 17, last_at, size=10, color="#64748b"))
        diagnostics["timeframes"][timeframe] = {
            "default_bars": default_limit,
            "rendered_bars": len(bars),
            "requested_levels": len(level_requests(overlay, timeframe)),
            "resolved_unique_anchors": len(anchors),
            "displayed_unique_anchors": len(displayed),
            "unresolved": unresolved,
            "omitted": omitted,
        }
    parts.append("</svg>")
    payload = "\n".join(parts).encode("utf-8")
    require(b"pnl" not in payload.lower() and b"win rate" not in payload.lower(), "Performance text leaked")
    require(diagnostics["maximum_ray_fraction"] <= 0.2200001, "Ray exceeds bounded-span gate")
    diagnostics["diagnostics_sha256"] = canonical_hash(diagnostics)
    return payload, diagnostics


def chart_filename(index: int, event: dict[str, Any]) -> str:
    return (
        f"{index:02d}_{event['direction'].lower()}_{event['event_class'].lower()}_"
        f"{event['trading_date_utc']}_{event['event_identity'][:10]}.svg"
    )


def materialize_side(
    side: str, frozen: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bytes], list[dict[str, Any]]]:
    original = load_json(base.PRIMARY if side == "primary" else base.REFERENCE)
    require(original["events_sha256"] == frozen["predecessors"]["original_events_sha256"], f"{side} event hash differs")
    require(len(original["events"]) == 729, f"{side} event count differs")
    streams = source.load_streams(side)
    selected = list(frozen["selected_example_identities"])
    selected_order = {identity: index for index, identity in enumerate(selected, start=1)}
    overlays: list[dict[str, Any]] = []
    charts: dict[str, bytes] = {}
    diagnostics_by_identity: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(original["events"], start=1):
        stream = streams[str(event["case_alias"])]
        overlay = event_semantic_overlay(stream, event)
        _assert_outcome_blind(overlay)
        overlays.append(overlay)
        identity = str(event["event_identity"])
        if identity in selected_order:
            payload, diagnostic = render_chart(stream, event, overlay)
            charts[chart_filename(selected_order[identity], event)] = payload
            diagnostics_by_identity[identity] = diagnostic
        if index % 50 == 0 or index == len(original["events"]):
            print(f"{side} overlay {index:03d}/729", flush=True)
    require(len({item["event_identity"] for item in overlays}) == 729, f"Duplicate {side} overlays")
    ordered_diagnostics = [diagnostics_by_identity[identity] for identity in selected]
    payload = {
        "version": "GOLD_ALL_TRANSITION_LIQUIDITY_RANGE_AMENDMENT_B_SIDE_1_0",
        "side": side,
        "original_events_sha256": original["events_sha256"],
        "event_identities_sha256": canonical_hash([item["event_identity"] for item in original["events"]]),
        "overlays": overlays,
        "overlays_sha256": canonical_hash(overlays),
    }
    del streams
    gc.collect()
    return payload, charts, ordered_diagnostics


def summary(overlays: list[dict[str, Any]]) -> dict[str, Any]:
    context = Counter(item["context_family"] for item in overlays)
    direction_context: dict[str, Counter[str]] = defaultdict(Counter)
    protected = Counter()
    broken = Counter()
    destinations: dict[str, Counter[str]] = defaultdict(Counter)
    active_ranges: dict[str, Counter[str]] = defaultdict(Counter)
    technical_unknowns = 0
    unresolved_active_roles = 0
    for item in overlays:
        direction_context[item["direction"]][item["context_family"]] += 1
        for timeframe, frame in item["timeframes"].items():
            technical_unknowns += int(
                frame["inventory_summary"]["state_counts"]["UNKNOWN_TECHNICAL"]
            )
            destination = frame["nearest_unconsumed_destination"]
            destinations[timeframe]["present" if destination is not None else "absent"] += 1
            active = frame["active_control_roles"]
            if active is not None:
                for role, counter in (
                    ("broken_control_pivot", broken),
                    ("protected_internal_pivot", protected),
                ):
                    value = active.get(role)
                    if value is None:
                        unresolved_active_roles += 1
                    else:
                        counter[str(value["state"])] += 1
            range_context = frame.get("range")
            if range_context is not None:
                active_ranges[timeframe][str(range_context["state"])] += 1
    return {
        "events": len(overlays),
        "context_family": dict(sorted(context.items())),
        "direction_by_context": {
            key: dict(sorted(value.items())) for key, value in sorted(direction_context.items())
        },
        "broken_control_pivot_state": dict(sorted(broken.items())),
        "protected_internal_pivot_state": dict(sorted(protected.items())),
        "destination_availability": {
            key: dict(sorted(value.items())) for key, value in sorted(destinations.items())
        },
        "range_state": {
            key: dict(sorted(value.items())) for key, value in sorted(active_ranges.items())
        },
        "technical_unknown_pivot_classifications": technical_unknowns,
        "unresolved_active_roles": unresolved_active_roles,
    }


def atlas_html(
    selected: list[str], events: dict[str, dict[str, Any]], chart_records: list[dict[str, Any]]
) -> str:
    cards: list[str] = []
    for identity, record in zip(selected, chart_records, strict=True):
        event = events[identity]
        cards.append(
            '<article class="card">'
            f"<h2>{html.escape(event['direction'])} - {html.escape(event['event_class'])} - {html.escape(event['decision_at'])}</h2>"
            f"<p>Only exact qualified pivots are marked. Event <code>{html.escape(identity)}</code></p>"
            f'<img src="predecision_charts_v1_b/{html.escape(record["filename"])}" alt="Corrected liquidity and range chart">'
            "</article>"
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gold corrected liquidity and range semantic atlas</title>
<style>body{margin:0;padding:24px;background:#eef2f6;color:#0f172a;font:14px Arial,sans-serif}.notice{max-width:1500px;margin:0 auto 20px;padding:16px;background:#fff;border:1px solid #cbd5e1}.card{max-width:1500px;margin:20px auto;padding:16px;background:#fff;border:1px solid #cbd5e1;box-shadow:0 3px 12px #0f172a18}.card img{display:block;width:100%;height:auto;border:1px solid #e2e8f0}h1,h2{margin:0 0 10px}code{font-size:11px}</style></head>
<body><section class="notice"><h1>Outcome-blind liquidity and range semantic atlas</h1><p>Consumption means a later traded price strictly beyond an exact confirmed pivot. Equality is engagement. Structural acceptance is separate. An active range requires repeated two-sided confirmed pivots and exact unconsumed boundaries. No generic full-width lines are drawn.</p></section>
""" + "\n".join(cards) + "\n</body></html>\n"


def markdown(certification: dict[str, Any]) -> str:
    summary_data = certification["summary"]
    return "\n".join(
        [
            "# Gold All-Transition Auction Scanner Liquidity and Range Semantics Amendment B Report",
            "",
            f"Verdict: `{certification['verdict']}`",
            "",
            "- The original 729 control events and 24 review identities remain unchanged.",
            "- Consumption now uses only a later observed traded price strictly beyond the exact confirmed pivot.",
            "- Equality is classified as engagement, not consumption.",
            "- Structural acceptance remains independent from pivot-liquidity consumption.",
            "- The same M5/M15 control transition is described in both trend and qualified range contexts.",
            f"- Context counts: `{json.dumps(summary_data['context_family'], sort_keys=True)}`.",
            f"- Protected internal-pivot states: `{json.dumps(summary_data['protected_internal_pivot_state'], sort_keys=True)}`.",
            f"- Range states: `{json.dumps(summary_data['range_state'], sort_keys=True)}`.",
            f"- Technical unknown classifications: `{summary_data['technical_unknown_pivot_classifications']}`.",
            "- Primary/reference overlays, diagnostics and chart bytes match exactly.",
            "- No outcomes or performance fields were accessed.",
            "",
            f"Corrected atlas: `{ATLAS.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )


def materialize() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY, REFERENCE, ATLAS, CERTIFICATION, SEAL, REPORT):
        require(not path.exists(), f"Amendment B one-shot output exists: {path}")
    require(not CHART_ROOT.exists(), f"Amendment B chart root exists: {CHART_ROOT}")

    primary, primary_charts, primary_diagnostics = materialize_side("primary", frozen)
    write_new_json(PRIMARY, primary)
    reference, reference_charts, reference_diagnostics = materialize_side("reference", frozen)
    write_new_json(REFERENCE, reference)
    require(primary["event_identities_sha256"] == reference["event_identities_sha256"], "Event identities differ")
    require(primary["overlays"] == reference["overlays"], "Primary/reference overlays differ")
    require(primary["overlays_sha256"] == reference["overlays_sha256"], "Overlay hashes differ")
    require(primary_charts.keys() == reference_charts.keys(), "Chart filename sets differ")
    require(all(primary_charts[name] == reference_charts[name] for name in primary_charts), "Chart bytes differ")
    require(primary_diagnostics == reference_diagnostics, "Chart diagnostics differ")

    summary_data = summary(primary["overlays"])
    require(summary_data["events"] == 729, "Overlay event count differs")
    require(summary_data["technical_unknown_pivot_classifications"] == 0, "Technical pivot classifications unresolved")
    require(summary_data["unresolved_active_roles"] == 0, "Active pivot roles unresolved")
    require(
        set(summary_data["broken_control_pivot_state"]) == {"CONSUMED"},
        "A structurally broken control pivot was not strictly consumed",
    )

    selected = list(frozen["selected_example_identities"])
    records: list[dict[str, Any]] = []
    ordered_chart_names = sorted(primary_charts, key=lambda name: int(name.split("_", 1)[0]))
    for filename in ordered_chart_names:
        payload = primary_charts[filename]
        path = CHART_ROOT / filename
        _atomic_create(path, payload)
        records.append(
            {"filename": filename, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    original_events = load_json(base.PRIMARY)["events"]
    event_map = {item["event_identity"]: item for item in original_events}
    write_new_text(ATLAS, atlas_html(selected, event_map, records))

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
    require(unresolved == 0, f"Chart pivot identities unresolved: {unresolved}")
    certification: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_LIQUIDITY_RANGE_AMENDMENT_B_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": "PASS_CORRECTED_LIQUIDITY_RANGE_SEMANTICS_STOP_FOR_USER_REVIEW",
        "freeze_sha256": frozen["freeze_sha256"],
        "ruleset": RULESET,
        "original_event_count_unchanged": 729,
        "original_events_sha256": frozen["predecessors"]["original_events_sha256"],
        "selected_example_identities": selected,
        "selected_example_identities_sha256": frozen["selected_example_identities_sha256"],
        "primary_reference_overlays_exact": True,
        "overlays_sha256": primary["overlays_sha256"],
        "summary": summary_data,
        "chart_records": records,
        "chart_diagnostics": primary_diagnostics,
        "chart_diagnostic_totals": {
            "unresolved_identities": unresolved,
            "omitted_pivots": omitted,
            "maximum_ray_fraction": max(item["maximum_ray_fraction"] for item in primary_diagnostics),
        },
        "chart_bytes_primary_reference_exact": True,
        "atlas": file_record(ATLAS),
        "original_events_changed": False,
        "outcomes_accessed": False,
        "performance_calculated": False,
        "execution_constructed": False,
        "february_17_28_opened": False,
        "july_2022_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    certification["certification_sha256"] = canonical_hash(certification)
    write_new_json(CERTIFICATION, certification)
    write_new_text(REPORT, markdown(certification))
    seal: dict[str, Any] = {
        "version": "GOLD_ALL_TRANSITION_LIQUIDITY_RANGE_AMENDMENT_B_SEAL_1_0",
        "sealed_at": now(),
        "verdict": certification["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "predecessor_visualization_a_seal_sha256": frozen["predecessors"][
            "visualization_amendment_a_seal_sha256"
        ],
        "files": [
            file_record(FREEZE),
            file_record(PRIMARY),
            file_record(REFERENCE),
            file_record(ATLAS),
            file_record(CERTIFICATION),
            file_record(REPORT),
            *[file_record(CHART_ROOT / record["filename"]) for record in records],
        ],
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "summary": summary_data,
                "chart_diagnostics": certification["chart_diagnostic_totals"],
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

