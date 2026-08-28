#!/usr/bin/env python3
"""Render ten outcome-blind auction trade-placement examples."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import run_gold_all_transition_auction_scanner_semantic_review_v1 as base  # noqa: E402
import run_gold_all_transition_liquidity_range_semantics_amendment_b as visual  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.auction_trade_placement_examples_v1 import (  # noqa: E402
    MINIMUM_PLANNED_R,
    RULESET,
    select_ten_examples,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    parse_dt,
)


CONTRACT = ROOT / "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1.md"
IMPLEMENTATION = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "auction_trade_placement_examples_v1.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_trade_placement_examples_v1.py"
RUNNER = Path(__file__).resolve()
SOURCE_ROOT = base.OUT
EVENTS_PRIMARY = SOURCE_ROOT / "events.primary.json"
EVENTS_REFERENCE = SOURCE_ROOT / "events.reference.json"
OVERLAYS_PRIMARY = SOURCE_ROOT / "liquidity_range_amendment_b.primary.json"
OVERLAYS_REFERENCE = SOURCE_ROOT / "liquidity_range_amendment_b.reference.json"
SOURCE_SEAL = SOURCE_ROOT / "liquidity_range_amendment_b_seal.json"

OUT = ROOT / "research_artifacts" / "gold_auction_trade_placement_examples_v1"
FREEZE = OUT / "preoutcome_freeze.json"
PRIMARY = OUT / "plans.primary.json"
REFERENCE = OUT / "plans.reference.json"
CHARTS = OUT / "charts"
ATLAS = OUT / "trade_placement_atlas.html"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_REPORT.md"

FRAME_ORDER = (("4h", "H4"), ("1h", "H1"), ("15m", "M15"), ("5m", "M5"))
PANEL_HEIGHT = 190
PANEL_GAP = 16
HEADER = 174
WIDTH = 1500
HEIGHT = 1045


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


def atomic_create(path: Path, payload: bytes) -> None:
    require(not path.exists(), f"Append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary output already exists: {temporary}")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    atomic_create(
        path,
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def write_text(path: Path, payload: str) -> None:
    atomic_create(path, payload.encode("utf-8"))


def verify_source_seal() -> dict[str, Any]:
    seal = load_json(SOURCE_SEAL)
    for record in seal["files"]:
        path = ROOT / record["path"]
        require(path.exists(), f"Missing sealed source artifact: {path}")
        require(path.stat().st_size == record["bytes"], f"Source size changed: {path}")
        require(sha256_file(path) == record["sha256"], f"Source hash changed: {path}")
    require(seal["outcomes_accessed"] is False, "Source branch already accessed outcomes")
    return seal


def freeze() -> None:
    require(not FREEZE.exists(), f"Freeze already exists: {FREEZE}")
    source_seal = verify_source_seal()
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_FREEZE_1_0",
        "frozen_at": now(),
        "ruleset": RULESET,
        "minimum_planned_r": MINIMUM_PLANNED_R,
        "selection": {
            "directions": ["LONG", "SHORT"],
            "per_direction": {
                "RANGE_ROTATION_WITH_LTF_CONTROL": 1,
                "TREND_PULLBACK_WITH_LTF_CONTROL": 2,
                "TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL": 2,
            },
            "chronology": "EARLIEST_ELIGIBLE_UNUSED_DATE_WITHIN_DIRECTION_AND_STRATUM",
            "outcome_fields_used": False,
        },
        "placement": {
            "entry": "COMPLETED_M5_SIGNAL_DECISION_PRICE",
            "stop": "M5_PROTECTED_INTERNAL_PIVOT_PLUS_EXISTING_BREAK_BUFFER",
            "target": "NEAREST_UNCONSUMED_H1_OR_H4_DIRECTIONAL_PIVOT",
            "maximum_distance_from_m5_break_atr": 1.0,
            "required_protected_state_prefix": "UNCONSUMED_",
        },
        "sources": [
            file_record(EVENTS_PRIMARY),
            file_record(EVENTS_REFERENCE),
            file_record(OVERLAYS_PRIMARY),
            file_record(OVERLAYS_REFERENCE),
            file_record(SOURCE_SEAL),
        ],
        "predecessor_seal_sha256": source_seal["seal_sha256"],
        "governing_files": [
            file_record(CONTRACT),
            file_record(IMPLEMENTATION),
            file_record(TESTS),
            file_record(RUNNER),
        ],
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_json(FREEZE, payload)


def _text(
    x: float,
    y: float,
    value: str,
    *,
    size: int = 11,
    color: str = "#334155",
    weight: int = 400,
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{color}">{html.escape(value)}</text>'
    )


def _fmt(value: Any) -> str:
    return "UNKNOWN" if value is None else f"{float(value):.2f}"


def _anchor_label(anchor: dict[str, Any]) -> str:
    roles = "/".join(role.lower().replace("_", " ") for role in anchor["roles"])
    return f"{roles}: {anchor['kind'].lower()} {_fmt(anchor['level'])}"


def render_trade_chart(
    stream: dict[str, Any], event: dict[str, Any], overlay: dict[str, Any], plan: dict[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    direction_color = "#059669" if plan["direction"] == "LONG" else "#dc2626"
    macro = plan["macro_context"]
    target = plan["target"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _text(
            28,
            29,
            f"{plan['trading_date_utc']} {plan['decision_at'][11:16]} UTC | {plan['direction']} {plan['event_class']}",
            size=19,
            color=direction_color,
            weight=700,
        ),
        _text(28, 53, f"Auction context: {plan['context_family']}", size=13, color="#0f172a", weight=700),
        _text(
            28,
            75,
            f"Macro context only: {macro.get('state')} score={_fmt(macro.get('score'))} driver={macro.get('dominant_driver') or 'UNKNOWN'}",
            size=11,
        ),
        _text(
            28,
            97,
            f"ENTRY {_fmt(plan['entry'])} | SL {_fmt(plan['stop'])} | TARGET {_fmt(target['level'])} ({target['timeframe']}) | planned {plan['planned_r']:.2f}R",
            size=13,
            color="#0f172a",
            weight=700,
        ),
        _text(
            28,
            119,
            f"Trigger: completed M5 {plan['event_class'].lower().replace('_', ' ')}; invalidation beyond protected {plan['protected_pivot']['kind'].lower()} {_fmt(plan['protected_pivot']['level'])}",
            size=11,
        ),
        _text(
            28,
            141,
            f"Destination: exact unconsumed {target['timeframe']} {target['kind'].lower()} from {target['pivot_at'][0:16].replace('T', ' ')}; local M15 liquidity is marked separately",
            size=11,
        ),
        _text(
            28,
            161,
            "All candles stop at the decision timestamp. The blank M5 area shows placement only; no future path or outcome is displayed.",
            size=10,
            color="#64748b",
        ),
    ]
    diagnostics: dict[str, Any] = {
        "event_identity": plan["event_identity"],
        "plan_sha256": plan["plan_sha256"],
        "future_bars": 0,
        "maximum_semantic_ray_fraction": 0.0,
        "timeframes": {},
    }

    for panel_index, (key, timeframe) in enumerate(FRAME_ORDER):
        y0 = HEADER + panel_index * (PANEL_HEIGHT + PANEL_GAP)
        chart_top = y0 + 23
        chart_bottom = y0 + PANEL_HEIGHT - 22
        chart_left = 77.0
        panel_right = 1458.0
        candle_right = 1132.0 if timeframe == "M5" else panel_right
        candle_width = candle_right - chart_left
        anchors, unresolved = visual.resolve_anchors(stream, overlay, timeframe, key)
        bars, visible_index, omitted = visual.visible_window(
            stream["timeframes"][key], overlay["decision_at"], anchors, key
        )
        require(bars, f"No visible {timeframe} bars")
        displayed = [item for item in anchors if item["pivot_at"] in visible_index]
        prices = [float(value) for row in bars for value in (row["low"], row["high"])]
        prices.extend(float(item["level"]) for item in displayed)
        if timeframe == "M5":
            prices.extend((float(plan["entry"]), float(plan["stop"]), float(target["level"])))
        low, high = min(prices), max(prices)
        span = max(high - low, 0.01)
        low -= span * 0.06
        high += span * 0.06

        def py(price: float) -> float:
            return chart_bottom - (price - low) / (high - low) * (chart_bottom - chart_top)

        structure = overlay["timeframes"][timeframe]["structure"]["state"]
        range_state = overlay["timeframes"][timeframe].get("range", {}).get("state")
        caption = f"{timeframe} | {structure}"
        if range_state is not None:
            caption += f" | {range_state}"
        parts.append(_text(17, y0 + 16, caption, size=11, color="#0f172a", weight=700))
        parts.append(
            f'<rect x="{chart_left:.1f}" y="{chart_top:.1f}" width="{panel_right-chart_left:.1f}" height="{chart_bottom-chart_top:.1f}" fill="#f8fafc" stroke="#e2e8f0"/>'
        )
        for grid in range(1, 4):
            gy = chart_top + grid * (chart_bottom - chart_top) / 4
            parts.append(
                f'<line x1="{chart_left:.1f}" y1="{gy:.1f}" x2="{panel_right:.1f}" y2="{gy:.1f}" stroke="#e2e8f0" stroke-width="1"/>'
            )
        step = candle_width / len(bars)
        body_width = max(1.7, min(8.0, step * 0.62))
        for index, bar in enumerate(bars):
            x = chart_left + (index + 0.5) * step
            open_price = float(bar["open"])
            close_price = float(bar["close"])
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
            ray_end = min(candle_right - 5, x + min(candle_width * 0.18, max(62.0, step * 12)))
            diagnostics["maximum_semantic_ray_fraction"] = max(
                diagnostics["maximum_semantic_ray_fraction"], (ray_end - x) / candle_width
            )
            parts.append(
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{ray_end:.1f}" y2="{y:.1f}" stroke="{anchor["color"]}" stroke-width="1.5" stroke-dasharray="6 4"/>'
            )
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{anchor["color"]}" stroke="#ffffff" stroke-width="1"/>'
            )
            labels.append(
                {
                    "x": min(ray_end + 4, candle_right - 250),
                    "y": y,
                    "color": anchor["color"],
                    "text": _anchor_label(anchor),
                }
            )
        labels.sort(key=lambda item: (item["y"], item["text"]))
        previous_y = chart_top - 12
        for item in labels:
            item["label_y"] = max(item["y"], previous_y + 12)
            previous_y = item["label_y"]
        overflow = max([0.0, *(item["label_y"] - (chart_bottom - 2) for item in labels)])
        for item in labels:
            label_y = item["label_y"] - overflow
            parts.append(
                f'<rect x="{item["x"]-2:.1f}" y="{label_y-11:.1f}" width="245" height="13" fill="#ffffff" fill-opacity="0.90"/>'
            )
            parts.append(_text(item["x"], label_y, item["text"], size=8, color=item["color"], weight=600))

        if timeframe == "M5":
            x1, x2 = candle_right + 13, panel_right - 9
            y_entry = py(float(plan["entry"]))
            y_stop = py(float(plan["stop"]))
            y_target = py(float(target["level"]))
            reward_top, reward_bottom = sorted((y_target, y_entry))
            risk_top, risk_bottom = sorted((y_entry, y_stop))
            parts.append(
                f'<rect x="{x1:.1f}" y="{reward_top:.1f}" width="{x2-x1:.1f}" height="{max(1.0,reward_bottom-reward_top):.1f}" fill="#22c55e" fill-opacity="0.18" stroke="#16a34a" stroke-width="1"/>'
            )
            parts.append(
                f'<rect x="{x1:.1f}" y="{risk_top:.1f}" width="{x2-x1:.1f}" height="{max(1.0,risk_bottom-risk_top):.1f}" fill="#ef4444" fill-opacity="0.18" stroke="#dc2626" stroke-width="1"/>'
            )
            for value, label, color in (
                (float(target["level"]), f"TARGET {_fmt(target['level'])}  +{plan['planned_r']:.2f}R", "#15803d"),
                (float(plan["entry"]), f"ENTRY {_fmt(plan['entry'])}", "#1d4ed8"),
                (float(plan["stop"]), f"STOP {_fmt(plan['stop'])}  -1.00R", "#b91c1c"),
            ):
                y = py(value)
                parts.append(
                    f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="2"/>'
                )
                parts.append(_text(x1 + 5, y - 4, label, size=9, color=color, weight=700))
            parts.append(
                f'<line x1="{candle_right:.1f}" y1="{chart_top:.1f}" x2="{candle_right:.1f}" y2="{chart_bottom:.1f}" stroke="#475569" stroke-width="1.5" stroke-dasharray="4 4"/>'
            )
            parts.append(_text(candle_right - 58, chart_top + 12, "DECISION", size=8, color="#475569", weight=700))

        first_at = str(bars[0]["open_at"])[5:16].replace("T", " ")
        last_at = str(bars[-1]["available_at"])[5:16].replace("T", " ")
        parts.append(_text(chart_left, chart_bottom + 15, first_at, size=9, color="#64748b"))
        parts.append(_text(candle_right - 100, chart_bottom + 15, last_at, size=9, color="#64748b"))
        diagnostics["timeframes"][timeframe] = {
            "bars": len(bars),
            "last_available_at": bars[-1]["available_at"],
            "displayed_anchors": len(displayed),
            "unresolved_anchors": unresolved,
            "omitted_anchors": omitted,
        }

    parts.append("</svg>")
    payload = "\n".join(parts).encode("utf-8")
    require(b"pnl" not in payload.lower() and b"outcome:" not in payload.lower(), "Outcome text leaked")
    require(diagnostics["maximum_semantic_ray_fraction"] <= 0.1800001, "Semantic ray too long")
    diagnostics["diagnostics_sha256"] = canonical_hash(diagnostics)
    return payload, diagnostics


def _side_payload(side: str) -> tuple[dict[str, Any], dict[str, bytes], list[dict[str, Any]]]:
    events_payload = load_json(EVENTS_PRIMARY if side == "primary" else EVENTS_REFERENCE)
    overlays_payload = load_json(OVERLAYS_PRIMARY if side == "primary" else OVERLAYS_REFERENCE)
    plans = select_ten_examples(events_payload["events"], overlays_payload["overlays"])
    event_by_identity = {item["event_identity"]: item for item in events_payload["events"]}
    overlay_by_identity = {item["event_identity"]: item for item in overlays_payload["overlays"]}
    streams = source.load_streams(side)
    charts: dict[str, bytes] = {}
    diagnostics: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        event = event_by_identity[plan["event_identity"]]
        overlay = overlay_by_identity[plan["event_identity"]]
        stream = streams[str(plan["case_alias"])]
        svg, diagnostic = render_trade_chart(stream, event, overlay, plan)
        filename = (
            f"{index:02d}_{plan['direction'].lower()}_{plan['context_family'].lower()}_"
            f"{plan['trading_date_utc']}_{plan['event_identity'][:10]}.svg"
        )
        charts[filename] = svg
        diagnostics.append(diagnostic)
        print(f"{side} chart {index:02d}/10", flush=True)
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_SIDE_1_0",
        "side": side,
        "plans": plans,
        "plans_sha256": canonical_hash(plans),
        "outcomes_accessed": False,
        "performance_calculated": False,
    }
    return payload, charts, diagnostics


def _atlas(plans: list[dict[str, Any]], records: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for plan, record in zip(plans, records, strict=True):
        target = plan["target"]
        cards.append(
            "<section class='card'>"
            f"<h2>{html.escape(plan['direction'])} · {html.escape(plan['context_family'])}</h2>"
            f"<p>{html.escape(plan['trading_date_utc'])} {html.escape(plan['decision_at'][11:16])} UTC · "
            f"entry {_fmt(plan['entry'])} · stop {_fmt(plan['stop'])} · target {_fmt(target['level'])} · {plan['planned_r']:.2f}R planned</p>"
            f"<img src='charts/{html.escape(record['filename'])}' alt='Outcome-blind trade placement chart'>"
            "</section>"
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gold Auction Trade Placement Examples V1</title>
<style>
body{margin:0;background:#f1f5f9;color:#0f172a;font-family:Arial,sans-serif}main{max-width:1540px;margin:0 auto;padding:28px}
h1{margin:0 0 8px}.note{background:#fff;border-left:5px solid #2563eb;padding:14px 16px;margin:16px 0 24px;line-height:1.45}
.card{background:#fff;border:1px solid #cbd5e1;border-radius:12px;padding:16px;margin:0 0 24px;box-shadow:0 2px 8px #0f172a12}
.card h2{margin:0 0 5px;font-size:18px}.card p{margin:0 0 12px;color:#475569}.card img{display:block;width:100%;height:auto;border:1px solid #e2e8f0}
</style></head><body><main>
<h1>Gold Auction Trade Placement Examples V1</h1>
<div class="note"><strong>Placement demonstration only.</strong> Each chart stops at its decision timestamp. The colored position box is drawn in blank space and shows the planned entry, structural stop and pre-existing liquidity target. No future candles, outcomes or PnL were opened.</div>
""" + "\n".join(cards) + "\n</main></body></html>\n"


def render() -> None:
    require(FREEZE.exists(), "Run freeze first")
    frozen = load_json(FREEZE)
    require(canonical_hash({k: v for k, v in frozen.items() if k != "freeze_sha256"}) == frozen["freeze_sha256"], "Freeze hash differs")
    verify_source_seal()
    for record in frozen["governing_files"] + frozen["sources"]:
        path = ROOT / record["path"]
        require(sha256_file(path) == record["sha256"], f"Frozen input changed: {path}")

    primary, primary_charts, primary_diagnostics = _side_payload("primary")
    reference, reference_charts, reference_diagnostics = _side_payload("reference")
    require(primary["plans"] == reference["plans"], "Primary/reference plans differ")
    require(primary_charts.keys() == reference_charts.keys(), "Primary/reference chart names differ")
    require(
        all(primary_charts[name] == reference_charts[name] for name in primary_charts),
        "Primary/reference chart bytes differ",
    )
    require(primary_diagnostics == reference_diagnostics, "Primary/reference diagnostics differ")

    plans = primary["plans"]
    require(len(plans) == 10, "Expected ten plans")
    require(Counter(item["direction"] for item in plans) == {"LONG": 5, "SHORT": 5}, "Direction balance differs")
    for direction in ("LONG", "SHORT"):
        contexts = Counter(item["context_family"] for item in plans if item["direction"] == direction)
        require(
            contexts
            == {
                "RANGE_ROTATION_WITH_LTF_CONTROL": 1,
                "TREND_PULLBACK_WITH_LTF_CONTROL": 2,
                "TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL": 2,
            },
            f"Context balance differs for {direction}: {contexts}",
        )
    require(all(item["eligible"] for item in plans), "An ineligible plan was selected")

    write_json(PRIMARY, primary)
    write_json(REFERENCE, reference)
    records: list[dict[str, Any]] = []
    for filename, payload in primary_charts.items():
        path = CHARTS / filename
        atomic_create(path, payload)
        records.append(file_record(path))
    write_text(ATLAS, _atlas(plans, records))

    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": "PASS_OUTCOME_BLIND_TEN_TRADE_PLACEMENT_EXAMPLES",
        "freeze_sha256": frozen["freeze_sha256"],
        "plans_sha256": primary["plans_sha256"],
        "plan_identities": [item["event_identity"] for item in plans],
        "counts": {
            "plans": len(plans),
            "directions": dict(Counter(item["direction"] for item in plans)),
            "contexts": dict(Counter(item["context_family"] for item in plans)),
        },
        "planned_r_range": [
            min(float(item["planned_r"]) for item in plans),
            max(float(item["planned_r"]) for item in plans),
        ],
        "primary_reference_plans_exact": True,
        "primary_reference_charts_byte_exact": True,
        "primary_reference_diagnostics_exact": True,
        "chart_records": records,
        "chart_diagnostics": primary_diagnostics,
        "atlas": file_record(ATLAS),
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    certification["certification_sha256"] = canonical_hash(certification)
    write_json(CERTIFICATION, certification)
    report = (
        "# Gold Auction Trade Placement Examples V1 Report\n\n"
        f"Verdict: `{certification['verdict']}`\n\n"
        "Ten outcome-blind plans were rendered: five LONG and five SHORT. Each direction contains one range rotation, two trend-pullback, and two transitional-context examples.\n\n"
        f"Planned target geometry ranges from {certification['planned_r_range'][0]:.2f}R to {certification['planned_r_range'][1]:.2f}R. This is planned geometry, not achieved performance.\n\n"
        "Primary and reference plans, diagnostics, and SVG bytes match exactly. No post-decision candles, outcomes, PnL, fresh periods, or paid data were accessed.\n"
    )
    write_text(REPORT, report)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": certification["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [
            file_record(FREEZE),
            file_record(PRIMARY),
            file_record(REFERENCE),
            file_record(ATLAS),
            file_record(CERTIFICATION),
            file_record(REPORT),
            *records,
        ],
        "outcomes_accessed": False,
        "performance_calculated": False,
        "fresh_periods_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_json(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "counts": certification["counts"],
                "planned_r_range": certification["planned_r_range"],
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
    parser.add_argument("action", choices=("freeze", "render", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"render", "all"}:
        render()


if __name__ == "__main__":
    main()
