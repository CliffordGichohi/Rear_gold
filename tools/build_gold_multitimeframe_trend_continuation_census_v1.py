from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
CONTRACT = ROOT / "GOLD_MULTITIMEFRAME_TREND_CONTINUATION_CENSUS_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_multitimeframe_trend_continuation_census_v1_protocol.json"
DESIGN_FREEZE = MANIFESTS / "gold_multitimeframe_trend_continuation_census_v1_design_freeze.json"
AMENDMENT_A = MANIFESTS / "gold_multitimeframe_trend_continuation_census_v1_amendment_a.json"
AMENDMENT_B = MANIFESTS / "gold_multitimeframe_trend_continuation_census_v1_amendment_b.json"
PRICE = ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz"
REPORT = ROOT / "GOLD_MULTITIMEFRAME_TREND_CONTINUATION_CENSUS_V1_REPORT_V2.md"
FINAL_SEAL = OUTPUT / "final_seal.json"

START = datetime(2021, 8, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)
SCALE = 100_000_000
TIMEFRAMES = {"15m": "M15", "1h": "H1", "4h": "H4"}
SCALES = {"MICRO": 1, "STANDARD": 2, "MAJOR": 3}
ENGINEERING_DATES = {"2024-01-05", "2024-01-09", "2024-01-11", "2024-01-30", "2024-01-31", "2024-03-20"}


SWING_SCHEMA = pa.schema([
    pa.field("swing_id", pa.string(), False), pa.field("timeframe", pa.string(), False),
    pa.field("scale", pa.string(), False), pa.field("span", pa.int64(), False),
    pa.field("side", pa.string(), False), pa.field("pivot_at_utc", pa.string(), False),
    pa.field("known_at_utc", pa.string(), False), pa.field("price_e8", pa.int64(), False),
    pa.field("pivot_component_complete", pa.bool_(), False), pa.field("research_eligible", pa.bool_(), False),
    pa.field("evidence_hash", pa.string(), False),
])
EVENT_SCHEMA = pa.schema([
    pa.field("event_id", pa.string(), False), pa.field("timeframe", pa.string(), False),
    pa.field("scale", pa.string(), False), pa.field("span", pa.int64(), False),
    pa.field("event_type", pa.string(), False), pa.field("direction", pa.string(), False),
    pa.field("prior_state", pa.string(), False), pa.field("new_state", pa.string(), False),
    pa.field("event_at_utc", pa.string(), False), pa.field("segment_id", pa.string(), False),
    pa.field("broken_swing_ids_json", pa.string(), False), pa.field("broken_level_count", pa.int64(), False),
    pa.field("broken_level_min_e8", pa.int64(), False), pa.field("broken_level_max_e8", pa.int64(), False),
    pa.field("protected_level_e8", pa.int64(), True), pa.field("associated_pullback_ids_json", pa.string(), False),
    pa.field("bar_component_complete", pa.bool_(), False), pa.field("research_eligible", pa.bool_(), False),
    pa.field("evidence_hash", pa.string(), False),
])
PULLBACK_SCHEMA = pa.schema([
    pa.field("pullback_id", pa.string(), False), pa.field("timeframe", pa.string(), False),
    pa.field("scale", pa.string(), False), pa.field("span", pa.int64(), False),
    pa.field("direction", pa.string(), False), pa.field("segment_id", pa.string(), False),
    pa.field("pivot_swing_id", pa.string(), False), pa.field("pivot_at_utc", pa.string(), False),
    pa.field("known_at_utc", pa.string(), False), pa.field("pivot_price_e8", pa.int64(), False),
    pa.field("reference_event_id", pa.string(), False), pa.field("reference_level_e8", pa.int64(), False),
    pa.field("resolution", pa.string(), False), pa.field("resolved_at_utc", pa.string(), True),
    pa.field("resolution_event_id", pa.string(), True), pa.field("bars_to_resolution", pa.int64(), True),
    pa.field("actionable_at_known", pa.bool_(), False), pa.field("research_eligible", pa.bool_(), False),
    pa.field("decision_facts_hash", pa.string(), False), pa.field("resolution_hash", pa.string(), False),
])
SEGMENT_SCHEMA = pa.schema([
    pa.field("segment_id", pa.string(), False), pa.field("timeframe", pa.string(), False),
    pa.field("scale", pa.string(), False), pa.field("span", pa.int64(), False),
    pa.field("direction", pa.string(), False), pa.field("start_at_utc", pa.string(), False),
    pa.field("end_at_utc", pa.string(), True), pa.field("status", pa.string(), False),
    pa.field("start_event_id", pa.string(), False), pa.field("end_event_id", pa.string(), True),
    pa.field("bar_count", pa.int64(), False), pa.field("structure_event_count", pa.int64(), False),
    pa.field("continuation_event_count", pa.int64(), False), pa.field("pullback_case_count", pa.int64(), False),
    pa.field("research_start_clipped", pa.bool_(), False), pa.field("research_eligible", pa.bool_(), False),
    pa.field("evidence_hash", pa.string(), False),
])


@dataclass(frozen=True, slots=True)
class Bar:
    timeframe: str
    open_at: datetime
    close_at: datetime
    open_e8: int
    high_e8: int
    low_e8: int
    close_e8: int
    component_complete: bool
    record_hash: str


@dataclass(frozen=True, slots=True)
class Swing:
    swing_id: str
    timeframe: str
    scale: str
    span: int
    side: str
    pivot_index: int
    known_index: int
    pivot_at: datetime
    known_at: datetime
    price_e8: int
    component_complete: bool
    evidence_hash: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError(value)
    return parsed.astimezone(UTC)


def scaled(value: Any) -> int:
    return int((Decimal(str(value)) * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20): digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False); handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True); raise


def write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle: handle.write(value)
    except Exception:
        path.unlink(missing_ok=True); raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    table = pa.Table.from_pylist(list(rows), schema=schema)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=65_536)
    temporary.replace(path)


def verify_design() -> dict[str, Any]:
    freeze = json.loads(DESIGN_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_BEFORE_CENSUS_MATERIALIZATION": raise ValueError("Design freeze invalid")
    for name, path in {"contract": CONTRACT, "protocol": PROTOCOL}.items():
        if sha256_file(path) != freeze["controls"][name]["sha256"]: raise ValueError(f"Control changed: {name}")
    amendment = json.loads(AMENDMENT_A.read_text(encoding="utf-8"))
    if amendment.get("status") != "SEALED_BEFORE_CENSUS_MATERIALIZATION": raise ValueError("Amendment invalid")
    amendment_b = json.loads(AMENDMENT_B.read_text(encoding="utf-8"))
    if amendment_b.get("status") != "SEALED_BEFORE_LINEAGE_RECERTIFICATION": raise ValueError("Amendment B invalid")
    if PRICE.stat().st_size != freeze["sources"]["price_bars"]["bytes"]: raise ValueError("Price source size changed")
    return freeze


def load_bars() -> tuple[dict[str, list[Bar]], dict[str, Any]]:
    output = {value: [] for value in TIMEFRAMES.values()}
    rows_seen = selected = malformed = duplicates = forward_deserialized = 0
    component = Counter()
    with gzip.open(PRICE, "rb") as handle:
        for raw in handle:
            rows_seen += 1
            if not any(f'"timeframe":"{name}"'.encode() in raw for name in TIMEFRAMES): continue
            if b'"open_time":"2025' in raw or b'"open_time":"2026' in raw:
                continue
            record = json.loads(raw)
            if record.get("instrument_code") != "XAUUSD" or record.get("timeframe") not in TIMEFRAMES: continue
            opened, closed, available = parse_dt(str(record["open_time"])), parse_dt(str(record["close_time"])), parse_dt(str(record["available_at"]))
            if closed > END or available > closed: continue
            ohlc = record.get("ohlc") if isinstance(record.get("ohlc"), Mapping) else {}
            if any(ohlc.get(key) is None for key in ("open", "high", "low", "close")):
                malformed += 1; continue
            bar = Bar(TIMEFRAMES[str(record["timeframe"])], opened, closed, scaled(ohlc["open"]), scaled(ohlc["high"]), scaled(ohlc["low"]), scaled(ohlc["close"]), record.get("complete") is True, str(record["record_hash"]))
            if not (bar.low_e8 <= min(bar.open_e8, bar.close_e8) <= max(bar.open_e8, bar.close_e8) <= bar.high_e8):
                malformed += 1; continue
            output[bar.timeframe].append(bar); selected += 1
            component[f"{bar.timeframe}|{'COMPLETE' if bar.component_complete else 'CLOSED_WITH_MISSING_COMPONENTS'}"] += 1
    for timeframe, bars in output.items():
        bars.sort(key=lambda item: (item.close_at, item.open_at, item.record_hash))
        unique: dict[datetime, Bar] = {}
        for bar in bars:
            if bar.open_at in unique: duplicates += 1
            else: unique[bar.open_at] = bar
        output[timeframe] = list(unique.values())
    return output, {
        "source_rows_scanned": rows_seen, "selected_rows": selected, "malformed_rows": malformed,
        "duplicate_open_times": duplicates, "forward_market_rows_deserialized": forward_deserialized,
        "counts": {key: len(value) for key, value in output.items()}, "component_quality": dict(sorted(component.items())),
        "first_open": {key: iso_z(value[0].open_at) if value else None for key, value in output.items()},
        "last_close": {key: iso_z(value[-1].close_at) if value else None for key, value in output.items()},
    }


def derive_swings(bars: Sequence[Bar], timeframe: str, scale_name: str, span: int, implementation: str) -> list[Swing]:
    pivots = range(span, len(bars) - span) if implementation == "primary" else (known - span for known in range(2 * span, len(bars)))
    output: list[Swing] = []
    for pivot in pivots:
        known = pivot + span
        current = bars[pivot]
        highs = [bars[index].high_e8 for index in range(pivot - span, pivot + span + 1)]
        lows = [bars[index].low_e8 for index in range(pivot - span, pivot + span + 1)]
        sides = []
        if current.high_e8 == max(highs) and highs.count(current.high_e8) == 1: sides.append(("UPPER", current.high_e8))
        if current.low_e8 == min(lows) and lows.count(current.low_e8) == 1: sides.append(("LOWER", current.low_e8))
        for side, price in sides:
            identity = [timeframe, scale_name, span, side, iso_z(current.close_at), iso_z(bars[known].close_at), price, current.record_hash]
            output.append(Swing(f"SWING::{canonical_hash(identity)[:24]}", timeframe, scale_name, span, side, pivot, known, current.close_at, bars[known].close_at, price, current.component_complete, canonical_hash(identity)))
    return sorted(output, key=lambda item: (item.known_index, item.side, item.pivot_index, item.swing_id))


def swing_row(item: Swing) -> dict[str, Any]:
    return {"swing_id": item.swing_id, "timeframe": item.timeframe, "scale": item.scale, "span": item.span, "side": item.side, "pivot_at_utc": iso_z(item.pivot_at), "known_at_utc": iso_z(item.known_at), "price_e8": item.price_e8, "pivot_component_complete": item.component_complete, "research_eligible": START <= item.pivot_at < END and item.pivot_at.date().isoformat() not in ENGINEERING_DATES, "evidence_hash": item.evidence_hash}


def enumerate_structure(bars: Sequence[Bar], swings: Sequence[Swing], timeframe: str, scale_name: str, span: int, implementation: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_known: dict[int, list[Swing]] = defaultdict(list)
    for swing in swings: by_known[swing.known_index].append(swing)
    known_highs: list[Swing] = []
    known_lows: list[Swing] = []
    broken: set[str] = set()
    state = "NEUTRAL"
    current_segment: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    event_internal: list[dict[str, Any]] = []
    pullbacks: list[dict[str, Any]] = []
    pullback_internal: dict[str, dict[str, Any]] = {}
    active_pullbacks: set[str] = set()
    segments: list[dict[str, Any]] = []
    state_after: list[str] = []
    event_after: list[str | None] = []
    segment_after: list[str | None] = []
    high_pointer = -1
    low_pointer = -1

    def latest_unbroken(values: Sequence[Swing], index: int) -> Swing | None:
        nonlocal high_pointer, low_pointer
        if implementation == "primary":
            return next((item for item in reversed(values) if item.swing_id not in broken), None)
        pointer = high_pointer if values is known_highs else low_pointer
        while pointer >= 0 and values[pointer].swing_id in broken:
            pointer -= 1
        if values is known_highs:
            high_pointer = pointer
        else:
            low_pointer = pointer
        return values[pointer] if pointer >= 0 else None

    for index, bar in enumerate(bars):
        high_boundary = latest_unbroken(known_highs, index)
        low_boundary = latest_unbroken(known_lows, index)
        high_breach = high_boundary is not None and bar.close_e8 > high_boundary.price_e8
        low_breach = low_boundary is not None and bar.close_e8 < low_boundary.price_e8
        direction: str | None = None
        if high_breach and low_breach:
            high_key = (high_boundary.known_index, high_boundary.pivot_index)
            low_key = (low_boundary.known_index, low_boundary.pivot_index)
            direction = "UP" if high_key > low_key else "DOWN" if low_key > high_key else None
        elif high_breach: direction = "UP"
        elif low_breach: direction = "DOWN"

        if direction is not None:
            side = "UPPER" if direction == "UP" else "LOWER"
            candidates = [item for item in (known_highs if direction == "UP" else known_lows) if item.swing_id not in broken and (bar.close_e8 > item.price_e8 if direction == "UP" else bar.close_e8 < item.price_e8)]
            candidates.sort(key=lambda item: (item.known_index, item.pivot_index, item.swing_id))
            prior_state = state
            event_type = f"{'BULLISH' if direction == 'UP' else 'BEARISH'}_{'CONTINUATION_BREAK' if state == direction else 'STRUCTURE_SWITCH'}"
            identity = [timeframe, scale_name, direction, iso_z(bar.close_at), [item.swing_id for item in candidates], event_type]
            event_id = f"STRUCT::{canonical_hash(identity)[:24]}"
            associated = []
            for pullback_id in sorted(active_pullbacks):
                case = pullback_internal[pullback_id]
                case["resolution"] = "CONTINUED" if case["direction"] == direction else "FAILED_STRUCTURE_SWITCH"
                case["resolved_at_utc"] = iso_z(bar.close_at)
                case["resolution_event_id"] = event_id
                case["bars_to_resolution"] = index - case["known_index"]
                case["resolution_hash"] = canonical_hash([pullback_id, case["resolution"], event_id, iso_z(bar.close_at)])
                associated.append(pullback_id)
            active_pullbacks.clear()

            if state != direction:
                if current_segment is not None:
                    current_segment["end_at_utc"] = iso_z(bar.close_at)
                    current_segment["end_index"] = index
                    current_segment["end_event_id"] = event_id
                    current_segment["status"] = "CLOSED_BY_OPPOSITE_SWITCH"
                segment_id = f"SEGMENT::{canonical_hash([timeframe, scale_name, direction, event_id])[:24]}"
                current_segment = {"segment_id": segment_id, "timeframe": timeframe, "scale": scale_name, "span": span, "direction": direction, "start_at_utc": iso_z(bar.close_at), "start_index": index, "end_at_utc": None, "end_index": None, "status": "OPEN_AT_BOUNDARY", "start_event_id": event_id, "end_event_id": None}
                segments.append(current_segment)
            assert current_segment is not None
            state = direction
            opposite_values = known_lows if direction == "UP" else known_highs
            protected = opposite_values[-1].price_e8 if opposite_values else None
            levels = [item.price_e8 for item in candidates]
            event = {"event_id": event_id, "timeframe": timeframe, "scale": scale_name, "span": span, "event_type": event_type, "direction": direction, "prior_state": prior_state, "new_state": state, "event_at_utc": iso_z(bar.close_at), "segment_id": current_segment["segment_id"], "broken_swing_ids_json": canonical_json([item.swing_id for item in candidates]), "broken_level_count": len(candidates), "broken_level_min_e8": min(levels), "broken_level_max_e8": max(levels), "protected_level_e8": protected, "associated_pullback_ids_json": canonical_json(associated), "bar_component_complete": bar.component_complete, "research_eligible": START <= bar.close_at < END and bar.close_at.date().isoformat() not in ENGINEERING_DATES, "evidence_hash": canonical_hash([identity, bar.record_hash])}
            events.append(event)
            event_internal.append({**event, "bar_index": index})
            broken.update(item.swing_id for item in candidates)

        state_after.append(state)
        event_after.append(event_internal[-1]["event_id"] if event_internal else None)
        segment_after.append(current_segment["segment_id"] if current_segment else None)

        for swing in by_known.get(index, []):
            if swing.side == "UPPER":
                known_highs.append(swing)
                high_pointer = len(known_highs) - 1
            else:
                known_lows.append(swing)
                low_pointer = len(known_lows) - 1
            pivot_state = state_after[swing.pivot_index]
            required_side = "LOWER" if pivot_state == "UP" else "UPPER" if pivot_state == "DOWN" else None
            pivot_event_id = event_after[swing.pivot_index]
            pivot_segment_id = segment_after[swing.pivot_index]
            if swing.side != required_side or pivot_event_id is None or pivot_segment_id is None: continue
            reference_event = next(item for item in reversed(event_internal) if item["event_id"] == pivot_event_id)
            if swing.pivot_index <= reference_event["bar_index"]: continue
            future_events = [item for item in event_internal if swing.pivot_index < item["bar_index"] <= index]
            first_resolution = future_events[0] if future_events else None
            pullback_identity = [timeframe, scale_name, pivot_state, swing.swing_id, pivot_event_id, pivot_segment_id]
            pullback_id = f"PULLBACK::{canonical_hash(pullback_identity)[:24]}"
            reference_level = reference_event["broken_level_max_e8"] if pivot_state == "UP" else reference_event["broken_level_min_e8"]
            decision_hash = canonical_hash([pullback_identity, iso_z(swing.known_at), swing.price_e8, reference_level])
            case = {"pullback_id": pullback_id, "timeframe": timeframe, "scale": scale_name, "span": span, "direction": pivot_state, "segment_id": pivot_segment_id, "pivot_swing_id": swing.swing_id, "pivot_at_utc": iso_z(swing.pivot_at), "known_at_utc": iso_z(swing.known_at), "pivot_price_e8": swing.price_e8, "reference_event_id": pivot_event_id, "reference_level_e8": reference_level, "resolution": "UNRESOLVED_AT_BOUNDARY", "resolved_at_utc": None, "resolution_event_id": None, "bars_to_resolution": None, "known_index": index, "actionable_at_known": True, "research_eligible": swing.pivot_at.date().isoformat() not in ENGINEERING_DATES, "decision_facts_hash": decision_hash, "resolution_hash": canonical_hash([pullback_id, "UNRESOLVED_AT_BOUNDARY"])}
            if first_resolution is not None:
                same = first_resolution["direction"] == pivot_state
                case["resolution"] = "RESOLVED_BEFORE_CONFIRMATION" if same else "FAILED_STRUCTURE_SWITCH"
                case["resolved_at_utc"] = first_resolution["event_at_utc"]
                case["resolution_event_id"] = first_resolution["event_id"]
                case["bars_to_resolution"] = first_resolution["bar_index"] - index
                case["actionable_at_known"] = False
                case["resolution_hash"] = canonical_hash([pullback_id, case["resolution"], first_resolution["event_id"]])
            else:
                active_pullbacks.add(pullback_id)
            pullbacks.append(case)
            pullback_internal[pullback_id] = case

    for case in pullbacks:
        case.pop("known_index", None)
    segment_events = defaultdict(list)
    for event in events: segment_events[event["segment_id"]].append(event)
    segment_pullbacks = defaultdict(list)
    for case in pullbacks: segment_pullbacks[case["segment_id"]].append(case)
    segment_rows = []
    for segment in segments:
        end_index = segment["end_index"] if segment["end_index"] is not None else len(bars)
        event_values = segment_events[segment["segment_id"]]
        pull_values = segment_pullbacks[segment["segment_id"]]
        start_at = parse_dt(segment["start_at_utc"])
        segment_rows.append({"segment_id": segment["segment_id"], "timeframe": timeframe, "scale": scale_name, "span": span, "direction": segment["direction"], "start_at_utc": segment["start_at_utc"], "end_at_utc": segment["end_at_utc"], "status": segment["status"], "start_event_id": segment["start_event_id"], "end_event_id": segment["end_event_id"], "bar_count": max(0, end_index - segment["start_index"]), "structure_event_count": len(event_values), "continuation_event_count": sum("CONTINUATION" in item["event_type"] for item in event_values), "pullback_case_count": len(pull_values), "research_start_clipped": start_at < START, "research_eligible": START <= start_at < END and start_at.date().isoformat() not in ENGINEERING_DATES, "evidence_hash": canonical_hash([segment["segment_id"], [item["event_id"] for item in event_values], [item["pullback_id"] for item in pull_values], segment["end_event_id"]])})

    event_rows = [item for item in events if parse_dt(item["event_at_utc"]) < END]
    pullback_rows = [item for item in pullbacks if START <= parse_dt(item["pivot_at_utc"]) < END]
    segment_rows = [item for item in segment_rows if parse_dt(item["start_at_utc"]) < END and (item["end_at_utc"] is None or parse_dt(item["end_at_utc"]) > START)]
    event_rows.sort(key=lambda item: (item["event_at_utc"], item["event_id"]))
    pullback_rows.sort(key=lambda item: (item["known_at_utc"], item["pullback_id"]))
    segment_rows.sort(key=lambda item: (item["start_at_utc"], item["segment_id"]))
    return event_rows, pullback_rows, segment_rows


def counts(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(item[field]) for item in rows).items()))


def report_text(summary: Mapping[str, Any]) -> str:
    lines = ["# Gold Multi-Timeframe Trend and Continuation Census V1", "", "Status: **PASS_COMPLETE_DESCRIPTIVE_CENSUS**", "", "This is a denominator census, not an edge or trading result. Fundamentals, sessions, candles, costs and execution removed zero cases.", "", "## Counts", "", "| Timeframe | Scale | Swings | Structure events | Continuation breaks | Pullbacks | Continued | Failed | Pre-confirmation | Unresolved |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in summary["matrix"]:
        lines.append(f"| {item['timeframe']} | {item['scale']} | {item['swings']} | {item['events']} | {item['continuations']} | {item['pullbacks']} | {item['continued']} | {item['failed']} | {item['preconfirmation']} | {item['unresolved']} |")
    lines.extend(["", "2025 and 2026 were not inspected. No relationship, signal, execution, trade, R or PnL calculation was performed. Primary and reference outputs are byte-identical.", ""])
    return "\n".join(lines)


def build() -> dict[str, Any]:
    verify_design()
    if FINAL_SEAL.exists() or (OUTPUT / "primary_swings.parquet").exists(): raise FileExistsError("Census output exists")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    bars_by_tf, coverage = load_bars()
    all_primary_swings: list[dict[str, Any]] = []
    all_reference_swings: list[dict[str, Any]] = []
    all_primary_events: list[dict[str, Any]] = []
    all_reference_events: list[dict[str, Any]] = []
    all_primary_pullbacks: list[dict[str, Any]] = []
    all_reference_pullbacks: list[dict[str, Any]] = []
    all_primary_segments: list[dict[str, Any]] = []
    all_reference_segments: list[dict[str, Any]] = []
    matrix = []
    for timeframe in ("M15", "H1", "H4"):
        bars = bars_by_tf[timeframe]
        for scale_name, span in SCALES.items():
            primary_swings = derive_swings(bars, timeframe, scale_name, span, "primary")
            reference_swings = derive_swings(bars, timeframe, scale_name, span, "reference")
            if primary_swings != reference_swings: raise ValueError(f"Swing reproduction failed: {timeframe} {scale_name}")
            primary_events, primary_pullbacks, primary_segments = enumerate_structure(bars, primary_swings, timeframe, scale_name, span, "primary")
            reference_events, reference_pullbacks, reference_segments = enumerate_structure(bars, reference_swings, timeframe, scale_name, span, "reference")
            if primary_events != reference_events or primary_pullbacks != reference_pullbacks or primary_segments != reference_segments:
                raise ValueError(f"Structure reproduction failed: {timeframe} {scale_name}")
            swing_rows = [swing_row(item) for item in primary_swings if item.known_at <= END]
            reference_swing_rows = [swing_row(item) for item in reference_swings if item.known_at <= END]
            all_primary_swings.extend(swing_rows); all_reference_swings.extend(reference_swing_rows)
            all_primary_events.extend(primary_events); all_reference_events.extend(reference_events)
            all_primary_pullbacks.extend(primary_pullbacks); all_reference_pullbacks.extend(reference_pullbacks)
            all_primary_segments.extend(primary_segments); all_reference_segments.extend(reference_segments)
            development_swings = [item for item in swing_rows if START <= parse_dt(item["pivot_at_utc"]) < END]
            development_events = [item for item in primary_events if START <= parse_dt(item["event_at_utc"]) < END]
            resolution = Counter(item["resolution"] for item in primary_pullbacks)
            matrix.append({"timeframe": timeframe, "scale": scale_name, "span": span, "swings": len(development_swings), "events": len(development_events), "continuations": sum("CONTINUATION" in item["event_type"] for item in development_events), "pullbacks": len(primary_pullbacks), "continued": resolution["CONTINUED"], "failed": resolution["FAILED_STRUCTURE_SWITCH"], "preconfirmation": resolution["RESOLVED_BEFORE_CONFIRMATION"], "unresolved": resolution["UNRESOLVED_AT_BOUNDARY"]})
    sort_specs = [
        (all_primary_swings, all_reference_swings, lambda item: (item["timeframe"], item["scale"], item["known_at_utc"], item["swing_id"])),
        (all_primary_events, all_reference_events, lambda item: (item["timeframe"], item["scale"], item["event_at_utc"], item["event_id"])),
        (all_primary_pullbacks, all_reference_pullbacks, lambda item: (item["timeframe"], item["scale"], item["known_at_utc"], item["pullback_id"])),
        (all_primary_segments, all_reference_segments, lambda item: (item["timeframe"], item["scale"], item["start_at_utc"], item["segment_id"])),
    ]
    for primary, reference, key in sort_specs:
        primary.sort(key=key); reference.sort(key=key)
        if primary != reference: raise ValueError("Combined reproduction failed")
    outputs = [
        ("swings", all_primary_swings, all_reference_swings, SWING_SCHEMA),
        ("structure_events", all_primary_events, all_reference_events, EVENT_SCHEMA),
        ("pullback_cases", all_primary_pullbacks, all_reference_pullbacks, PULLBACK_SCHEMA),
        ("trend_segments", all_primary_segments, all_reference_segments, SEGMENT_SCHEMA),
    ]
    artifact_records = {}
    for name, primary, reference, schema in outputs:
        p, r = OUTPUT / f"primary_{name}.parquet", OUTPUT / f"reference_{name}.parquet"
        write_parquet_exclusive(p, primary, schema); write_parquet_exclusive(r, reference, schema)
        if sha256_file(p) != sha256_file(r): raise ValueError(f"Byte reproduction failed: {name}")
        artifact_records[name] = {"rows": len(primary), "primary": file_record(p), "reference": file_record(r), "rows_hash": canonical_hash(primary)}
    development_events = [item for item in all_primary_events if START <= parse_dt(item["event_at_utc"]) < END]
    development_swings = [item for item in all_primary_swings if START <= parse_dt(item["pivot_at_utc"]) < END]
    year_direction_counts: dict[str, int] = Counter(
        f"{item['event_at_utc'][:4]}|{item['timeframe']}|{item['scale']}|{item['direction']}|{item['event_type']}"
        for item in development_events
    )
    swing_ids = {item["swing_id"] for item in all_primary_swings}
    event_ids = {item["event_id"] for item in all_primary_events}
    missing_swing_refs = sorted({swing_id for item in all_primary_events for swing_id in json.loads(item["broken_swing_ids_json"]) if swing_id not in swing_ids})
    missing_reference_events = sorted({item["reference_event_id"] for item in all_primary_pullbacks if item["reference_event_id"] not in event_ids})
    missing_resolution_events = sorted({item["resolution_event_id"] for item in all_primary_pullbacks if item["resolution_event_id"] is not None and item["resolution_event_id"] not in event_ids})
    if missing_swing_refs or missing_reference_events or missing_resolution_events:
        raise ValueError({"missing_swings": len(missing_swing_refs), "missing_reference_events": len(missing_reference_events), "missing_resolution_events": len(missing_resolution_events)})
    summary = {
        "version": "GOLD_MT_CENSUS_V1_SUMMARY_1_0", "status": "PASS_COMPLETE_DESCRIPTIVE_CENSUS",
        "completed_at_utc": utc_now(), "development": [iso_z(START), iso_z(END)], "coverage": coverage,
        "matrix": matrix,
        "development_totals": {"swings": len(development_swings), "structure_events": len(development_events), "pullback_cases": len(all_primary_pullbacks), "trend_segments": len(all_primary_segments)},
        "registry_totals_including_warmup_lineage": {name: value["rows"] for name, value in artifact_records.items()},
        "event_types": counts(development_events, "event_type"), "pullback_resolutions": counts(all_primary_pullbacks, "resolution"),
        "directions": counts(development_events, "direction"), "year_timeframe_scale_direction_event_counts": dict(sorted(year_direction_counts.items())),
        "referential_integrity": {"missing_broken_swing_refs": 0, "missing_pullback_reference_events": 0, "missing_resolution_events": 0},
        "research_ineligible_records_including_warmup_and_engineering": {
            "swings": sum(not item["research_eligible"] for item in all_primary_swings),
            "events": sum(not item["research_eligible"] for item in all_primary_events),
            "pullbacks": sum(not item["research_eligible"] for item in all_primary_pullbacks),
        },
        "artifacts": artifact_records, "primary_reference_exact": True,
        "fundamentals_or_sessions_used_as_filters": False, "relationships_or_edges_calculated": False,
        "execution_trades_r_or_pnl_calculated": False, "forward_2025_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(OUTPUT / "census_summary.json", summary)
    write_text_exclusive(REPORT, report_text(summary))
    seal_inputs = [OUTPUT / "census_summary.json", REPORT, DESIGN_FREEZE, AMENDMENT_A, AMENDMENT_B, *[OUTPUT / f"primary_{name}.parquet" for name, *_ in outputs], *[OUTPUT / f"reference_{name}.parquet" for name, *_ in outputs]]
    seal = {"version": "GOLD_MT_CENSUS_V1_FINAL_SEAL_1_0", "status": summary["status"], "sealed_at_utc": utc_now(), "artifacts": {path.name: file_record(path) for path in seal_inputs}, "artifact_set_hash": canonical_hash({path.name: sha256_file(path) for path in seal_inputs}), "primary_reference_exact": True, "forward_values_accessed": False, "relationships_or_pnl_calculated": False}
    write_json_exclusive(FINAL_SEAL, seal)
    return {"status": summary["status"], "development_totals": summary["development_totals"], "registry_totals": summary["registry_totals_including_warmup_lineage"], "event_types": summary["event_types"], "pullback_resolutions": summary["pullback_resolutions"], "referential_integrity": summary["referential_integrity"], "matrix": matrix, "final_seal": file_record(FINAL_SEAL)}


def selftest() -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    highs = [10, 11, 14, 12, 11, 13, 12]
    lows = [8, 7, 9, 8, 6, 8, 7]
    bars = [Bar("H1", now, now.replace(hour=0) if False else now, 9, highs[i], lows[i], 10, True, str(i)) for i in range(len(highs))]
    bars = [Bar("H1", now.replace(hour=0), now.replace(hour=0), item.open_e8, item.high_e8, item.low_e8, item.close_e8, True, item.record_hash) for item in bars]
    first = derive_swings(bars, "H1", "STANDARD", 2, "primary")
    second = derive_swings(bars, "H1", "STANDARD", 2, "reference")
    if first != second or not first: raise AssertionError((first, second))
    print(json.dumps({"status": "PASS_SELFTEST", "swings": len(first), "hash": canonical_hash([item.swing_id for item in first])}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("phase", choices=("selftest", "build")); args = parser.parse_args()
    if args.phase == "selftest": selftest()
    else: print(json.dumps(build(), indent=2, sort_keys=True))


if __name__ == "__main__": main()
