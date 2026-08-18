#!/usr/bin/env python3
"""Materialize date/price-blinded, point-in-time replay payloads."""

from __future__ import annotations

import bisect
import gzip
import hashlib
import io
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
ARTIFACT_DIR = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1"
PRIVATE_REGISTRY = ARTIFACT_DIR / "population_registry.private.json"
POPULATION_FREEZE = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_population_freeze.json"
PRIMARY_PAYLOAD = ARTIFACT_DIR / "display_payloads.primary.jsonl.gz"
REFERENCE_PAYLOAD = ARTIFACT_DIR / "display_payloads.reference.jsonl.gz"
PRIMARY_PRACTICE = ARTIFACT_DIR / "practice_future_paths.primary.jsonl.gz"
REFERENCE_PRACTICE = ARTIFACT_DIR / "practice_future_paths.reference.jsonl.gz"
CERTIFICATION = ARTIFACT_DIR / "materialization_certification.json"
GC_PRIMARY = ROOT / "research_artifacts" / "gc_microstructure_step5c_v01" / "primary_decision_features.parquet"
GC_REFERENCE = ROOT / "research_artifacts" / "gc_microstructure_step5c_v01" / "reference_decision_features.parquet"

BAR_LIMITS = {"1d": 120, "4h": 90, "1h": 120, "15m": 160, "5m": 180, "1m": 180}
WINDOW_DAYS = {"1d": 420, "4h": 60, "1h": 21, "15m": 14, "5m": 7, "1m": 7}
GC_STATES = (
    "FLOW_PRESSURE_W60", "FLOW_PRESSURE_W900", "DEPTH_PRESSURE_W60", "DEPTH_PRESSURE_W900",
    "LIQUIDITY_ACTIVITY_SHIFT", "LIQUIDITY_FRAGILITY", "ABSORPTION_STATE_W60", "FLOW_DEPTH_ALIGNMENT",
)

ISO_DATE = re.compile(r"\b20(?:21|22|23|24|25|26)-\d{2}-\d{2}\b")
ISO_TIMESTAMP = re.compile(r"\b20(?:21|22|23|24|25|26)[-.]\d{2}[-.]\d{2}[T ]\d{2}:\d{2}(?::\d{2})?")
NUMBER = r"(?:null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
REF_PATTERNS = {
    "available_at": re.compile(r'"available_at":"([^"]+)"'),
    "close_time": re.compile(r'"close_time":"([^"]+)"'),
    "complete": re.compile(r'"complete":(true|false)'),
    "ohlc": re.compile(rf'"ohlc":\{{"close":({NUMBER}),"high":({NUMBER}),"low":({NUMBER}),"open":({NUMBER})\}}'),
    "open_time": re.compile(r'"open_time":"([^"]+)"'),
    "timeframe": re.compile(r'"timeframe":"([^"]+)"'),
    "volume": re.compile(rf'"volume":({NUMBER})'),
}
REF_SPREAD_POINTS = re.compile(rf'"spread_points":(?:\{{"average":({NUMBER}),"maximum":{NUMBER}\}}|({NUMBER}))')
REF_SPREAD_PRICE = re.compile(rf'"spread_price":(?:\{{"average":({NUMBER}),"maximum":{NUMBER}\}}|({NUMBER}))')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda item: item.isoformat() if isinstance(item, (datetime, pd.Timestamp)) else str(item),
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def rounded(value: Any, digits: int = 8) -> Any:
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, digits)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): rounded(item, digits) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(item, digits) for item in value]
    return value


def redact_text(value: Any) -> str | None:
    if value is None:
        return None
    text = ISO_TIMESTAMP.sub("[HIDDEN_TIME]", str(value))
    return ISO_DATE.sub("[HIDDEN_DATE]", text)


def write_new_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(rounded(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def write_jsonl_gzip(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as text:
                for row in rows:
                    text.write(canonical_bytes(rounded(dict(row))).decode("utf-8") + "\n")


def verify_population_freeze() -> dict[str, Any]:
    freeze = json.loads(POPULATION_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_BEFORE_CASE_VALUE_MATERIALIZATION":
        raise RuntimeError("Population freeze is not authorized")
    failures = []
    for item in freeze["sealed_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            failures.append(item["path"])
    if failures:
        raise RuntimeError(f"Population freeze verification failed: {failures}")
    return freeze


def parse_number(value: str) -> float | None:
    return None if value == "null" else float(value)


def scalar_or_average(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("average")
    return None if value is None else float(value)


def parse_price_primary(line: str) -> dict[str, Any]:
    row = json.loads(line)
    return {
        "available_at": str(row["available_at"]), "close_time": str(row["close_time"]),
        "complete": bool(row["complete"]), "close": float(row["ohlc"]["close"]),
        "high": float(row["ohlc"]["high"]), "low": float(row["ohlc"]["low"]),
        "open": float(row["ohlc"]["open"]), "open_time": str(row["open_time"]),
        "spread_points": scalar_or_average(row.get("spread_points")),
        "spread_price": scalar_or_average(row.get("spread_price")),
        "timeframe": str(row["timeframe"]), "volume": None if row.get("volume") is None else float(row["volume"]),
    }


def parse_price_reference(line: str) -> dict[str, Any]:
    matches = {key: pattern.search(line) for key, pattern in REF_PATTERNS.items()}
    if any(match is None for match in matches.values()):
        raise RuntimeError("Reference price parser failed required-field extraction")
    spread_points, spread_price = REF_SPREAD_POINTS.search(line), REF_SPREAD_PRICE.search(line)
    if spread_points is None or spread_price is None:
        raise RuntimeError("Reference price parser failed spread extraction")
    ohlc = matches["ohlc"]
    assert ohlc is not None
    return {
        "available_at": matches["available_at"].group(1),
        "close_time": matches["close_time"].group(1),
        "complete": matches["complete"].group(1) == "true",
        "close": float(ohlc.group(1)), "high": float(ohlc.group(2)),
        "low": float(ohlc.group(3)), "open": float(ohlc.group(4)),
        "open_time": matches["open_time"].group(1),
        "spread_points": parse_number(spread_points.group(1) if spread_points.group(1) is not None else spread_points.group(2)),
        "spread_price": parse_number(spread_price.group(1) if spread_price.group(1) is not None else spread_price.group(2)),
        "timeframe": matches["timeframe"].group(1),
        "volume": parse_number(matches["volume"].group(1)),
    }


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def build_price_inputs(
    cases: list[dict[str, Any]], parser: Callable[[str], dict[str, Any]]
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, list[dict[str, Any]]]]:
    charts = {row["case_alias"]: {timeframe: [] for timeframe in BAR_LIMITS} for row in cases}
    practice = {row["case_alias"]: [] for row in cases if row["mode"] == "PRACTICE"}
    cutoff_index: dict[str, tuple[list[datetime], list[tuple[datetime, str]]]] = {}
    for timeframe in BAR_LIMITS:
        entries = sorted((parse_timestamp(row["checkpoint_at"]), row["case_alias"]) for row in cases)
        cutoff_index[timeframe] = ([item[0] for item in entries], entries)
    practice_entries = sorted(
        (parse_timestamp(row["checkpoint_at"]), parse_timestamp(row["session_end"]), row["case_alias"])
        for row in cases if row["mode"] == "PRACTICE"
    )

    with gzip.open(CASEBOOK / "price_bars.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = parser(line)
            timeframe = row["timeframe"]
            if timeframe not in BAR_LIMITS or not row["complete"]:
                continue
            open_at, available_at = parse_timestamp(row["open_time"]), parse_timestamp(row["available_at"])
            cutoffs, entries = cutoff_index[timeframe]
            left = bisect.bisect_left(cutoffs, available_at)
            right = bisect.bisect_right(cutoffs, open_at + timedelta(days=WINDOW_DAYS[timeframe]))
            source = {**row, "_open_at": open_at, "_available_at": available_at}
            for cutoff, alias in entries[left:right]:
                if open_at < cutoff and available_at <= cutoff and open_at >= cutoff - timedelta(days=WINDOW_DAYS[timeframe]):
                    charts[alias][timeframe].append(source)
            if timeframe == "1m":
                for cutoff, end, alias in practice_entries:
                    if cutoff <= open_at < end and available_at <= end:
                        practice[alias].append(source)

    for alias in charts:
        for timeframe, limit in BAR_LIMITS.items():
            charts[alias][timeframe].sort(key=lambda item: (item["_open_at"], item["_available_at"]))
            keep = 400 if timeframe == "1d" else max(limit, 121 if timeframe == "15m" else limit)
            charts[alias][timeframe] = charts[alias][timeframe][-keep:]
    for alias in practice:
        practice[alias].sort(key=lambda item: item["_open_at"])
    return charts, practice


def latest_atr(bars: list[dict[str, Any]], length: int = 14) -> float | None:
    if len(bars) < length + 1:
        return None
    ranges = []
    for index in range(1, len(bars)):
        row, prior = bars[index], bars[index - 1]
        ranges.append(max(row["high"] - row["low"], abs(row["high"] - prior["close"]), abs(row["low"] - prior["close"])))
    return statistics.fmean(ranges[-length:]) if len(ranges) >= length else None


def normalized_price(value: Any, reference: float) -> float | None:
    return None if value is None else round(float(value) / reference * 100.0, 6)


def chart_view(rows: list[dict[str, Any]], reference: float, limit: int) -> list[dict[str, Any]]:
    selected = rows[-limit:]
    output = []
    for index, row in enumerate(selected, start=1 - len(selected)):
        output.append({
            "ordinal": index,
            "open": normalized_price(row["open"], reference), "high": normalized_price(row["high"], reference),
            "low": normalized_price(row["low"], reference), "close": normalized_price(row["close"], reference),
            "volume": row["volume"],
        })
    return output


def weekly_view(daily_rows: list[dict[str, Any]], reference: float, cutoff: datetime) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    cutoff_iso = cutoff.date().isocalendar()
    cutoff_week = (cutoff_iso.year, cutoff_iso.week)
    for row in daily_rows:
        iso_calendar = row["_open_at"].date().isocalendar()
        key = (iso_calendar.year, iso_calendar.week)
        if key < cutoff_week:
            grouped[key].append(row)
    weeks = []
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=lambda item: item["_open_at"])
        weeks.append({
            "open": rows[0]["open"], "high": max(item["high"] for item in rows),
            "low": min(item["low"] for item in rows), "close": rows[-1]["close"],
            "volume": sum(item["volume"] or 0 for item in rows),
        })
    weeks = weeks[-52:]
    return [{
        "ordinal": index + 1 - len(weeks),
        "open": normalized_price(row["open"], reference), "high": normalized_price(row["high"], reference),
        "low": normalized_price(row["low"], reference), "close": normalized_price(row["close"], reference),
        "volume": row["volume"],
    } for index, row in enumerate(weeks)]


def safe_component(item: Mapping[str, Any]) -> dict[str, Any]:
    return rounded({key: item.get(key) for key in (
        "code", "layer", "direction", "strength", "confidence", "freshness", "data_quality",
        "epistemic_status", "contribution", "weight"
    )} | {"explanation": redact_text(item.get("explanation"))})


def fundamental_view(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if snapshot is None:
        return {"status": "UNKNOWN", "reason": "NO_POINT_IN_TIME_SNAPSHOT"}
    engine = snapshot["engine_state"]
    series = []
    for code, item in sorted(snapshot.get("series_state", {}).items()):
        series.append(rounded({
            "code": code, "status": item.get("status"), "value": item.get("value"), "unit": item.get("unit"),
            "absolute_change": item.get("absolute_change"), "percent_change": item.get("percent_change"),
            "change_per_day": item.get("change_per_day"), "epistemic_status": item.get("epistemic_status"),
            "change_epistemic_status": item.get("change_epistemic_status"), "staleness_seconds": item.get("staleness_seconds"),
        }))
    reasoning = engine.get("reasoning", {})
    return rounded({
        "status": "AVAILABLE", "epistemic_status": snapshot.get("epistemic_status"),
        "bias_label": engine.get("bias_label"), "directional_score": engine.get("directional_score"),
        "confidence": engine.get("confidence"), "coverage": engine.get("coverage"),
        "regime_label": engine.get("regime_label"), "dominant_driver": engine.get("dominant_driver"),
        "main_contradiction": engine.get("main_contradiction"), "event_risk": engine.get("event_risk"),
        "reaction_function": engine.get("reaction_function"),
        "summary": redact_text(reasoning.get("summary")),
        "contradictions": [redact_text(item) for item in reasoning.get("contradictions", [])],
        "missing_drivers": [redact_text(item) for item in reasoning.get("missing_drivers", [])],
        "components": [safe_component(item) for item in engine.get("components", [])],
        "layers": [{key: item.get(key) for key in ("layer", "status", "known_components", "unknown_components")} for item in engine.get("layers", [])],
        "series": series,
        "warning": "Score is context, not a trade signal; confidence is not win probability.",
    })


def structure_view(snapshot: Mapping[str, Any] | None, reference: float, cutoff: datetime) -> dict[str, Any]:
    if snapshot is None:
        return {"status": "UNKNOWN", "timeframes": []}
    timeframes = []
    for item in snapshot.get("timeframes", []):
        detections = [{
            "kind": row.get("kind"), "direction": row.get("direction"), "timeframe": row.get("timeframe"),
            "level": normalized_price(row.get("price_level"), reference), "confidence": row.get("confidence"),
            "epistemic_status": row.get("epistemic_status"), "method": row.get("detection_method"),
        } for row in item.get("detections", []) if parse_timestamp(str(row["detected_at"])) <= cutoff][-20:]
        timeframes.append(rounded({
            "timeframe": item.get("timeframe"), "status": item.get("status"), "trend": item.get("trend"),
            "last_close": normalized_price(item.get("last_close"), reference),
            "atr14_index": float(item["atr14"]) / reference * 100 if item.get("atr14") is not None else None,
            "support": normalized_price(item.get("support"), reference), "resistance": normalized_price(item.get("resistance"), reference),
            "range_low": normalized_price(item.get("range_low"), reference), "range_high": normalized_price(item.get("range_high"), reference),
            "compression_ratio": item.get("compression_ratio"), "momentum_atr": item.get("momentum_atr"),
            "detections": detections,
        }))
    return {"status": "AVAILABLE", "ruleset_version": snapshot.get("ruleset_version"), "timeframes": timeframes}


def session_context_view(session: Mapping[str, Any], reference: float) -> dict[str, Any]:
    decision = session["decision_state"]
    levels = [{
        "code": row.get("code"), "side": row.get("side"), "level": normalized_price(row.get("price"), reference)
    } for row in decision.get("known_levels", [])]
    windows = []
    for code, row in decision.get("windows", {}).items():
        if not isinstance(row, dict):
            windows.append({"code": code.upper(), "status": "UNKNOWN"})
            continue
        windows.append(rounded({
            "code": str(row.get("code", code)).upper(), "status": row.get("status"),
            "epistemic_status": row.get("epistemic_status"), "bar_count": row.get("bar_count"),
            "open": normalized_price(row.get("open"), reference), "high": normalized_price(row.get("high"), reference),
            "low": normalized_price(row.get("low"), reference), "close": normalized_price(row.get("close"), reference),
            "range_index": None if row.get("range") is None else float(row["range"]) / reference * 100,
            "tick_volume": row.get("tick_volume"), "average_spread": row.get("average_spread"),
        }))
    return {"known_levels": levels, "windows_at_session_open": windows}


def cross_market_view(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if snapshot is None:
        return {"status": "UNKNOWN", "instruments": []}
    instruments = []
    for code, item in sorted(snapshot.get("instruments", {}).items()):
        if not isinstance(item, dict):
            instruments.append({"code": code, "status": "UNKNOWN"})
            continue
        changes = {}
        for horizon, change in sorted((item.get("changes") or {}).items()):
            if isinstance(change, dict):
                changes[horizon] = rounded({key: change.get(key) for key in ("status", "absolute_change", "percent_change", "epistemic_status", "reason")})
        instruments.append(rounded({
            "code": code, "status": item.get("status"), "epistemic_status": item.get("epistemic_status"),
            "value": item.get("value"), "implied_rate_percent": item.get("implied_rate_percent"),
            "staleness_seconds": item.get("staleness_seconds"), "changes": changes,
        }))
    return {"status": "AVAILABLE", "instruments": instruments, "quality": snapshot.get("quality")}


def positioning_view(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if snapshot is None:
        return {"status": "UNKNOWN", "reason": "NO_PUBLISHED_COT_AVAILABLE"}
    calculated, inferred = snapshot.get("calculated", {}), snapshot.get("inferred", {})
    return rounded({
        "status": "AVAILABLE", "epistemic_status": snapshot.get("epistemic_status"),
        "availability_quality": snapshot.get("availability_quality"), "open_interest": snapshot.get("open_interest"),
        "managed_money_net": calculated.get("managed_money_net"), "managed_money_net_change": calculated.get("managed_money_net_change"),
        "managed_money_net_percentile": calculated.get("managed_money_net_percentile"), "producer_net": calculated.get("producer_net"),
        "crowding_state": inferred.get("crowding_state"), "participation_state": inferred.get("participation_state"),
        "long_liquidation_risk": inferred.get("long_liquidation_risk"), "short_covering_risk": inferred.get("short_covering_risk"),
        "warning": redact_text(inferred.get("warning")),
    })


def event_view(event: Mapping[str, Any], cutoff: datetime) -> dict[str, Any]:
    releases = []
    for row in event.get("releases", []):
        if parse_timestamp(str(row["available_at"])) <= cutoff:
            releases.append({key: row.get(key) for key in (
                "component_code", "actual_value", "previous_value", "revised_previous_value", "unit", "epistemic_status", "is_revision"
            )})
    surprises = []
    for row in event.get("standardized_surprises", []):
        if parse_timestamp(str(row["available_at"])) <= cutoff:
            surprises.append({key: row.get(key) for key in (
                "component_code", "raw_surprise", "standardized_surprise", "gold_direction", "strength", "confidence", "epistemic_status", "history_count", "method"
            )})
    available = parse_timestamp(str(event["event_available_at"]))
    return rounded({
        "minutes_before_checkpoint": int((cutoff - available).total_seconds() // 60),
        "event_code": event.get("event_code"), "name": redact_text(event.get("name")),
        "event_type": event.get("event_type"), "importance": event.get("importance"),
        "epistemic_status": event.get("epistemic_status"), "releases": releases, "surprises": surprises,
    })


def gc_views(primary_path: Path, reference_path: Path) -> tuple[dict[tuple[str, str], Any], dict[str, Any]]:
    primary, reference = pd.read_parquet(primary_path), pd.read_parquet(reference_path)
    columns = ["session_date", "session_code", "decision_at_utc", "availability_disposition"]
    for state in GC_STATES:
        columns.extend([f"{state}__state", f"{state}__epistemic_status", f"{state}__quality"])
    p_records = primary[columns].where(pd.notna(primary[columns]), None).to_dict("records")
    r_records = reference[columns].where(pd.notna(reference[columns]), None).to_dict("records")
    p_records, r_records = rounded(p_records), rounded(r_records)
    if p_records != r_records:
        raise RuntimeError("GC primary/reference decision states differ")
    output = {}
    for row in p_records:
        states = []
        for state in GC_STATES:
            states.append({
                "code": state, "state": row.get(f"{state}__state"),
                "epistemic_status": row.get(f"{state}__epistemic_status"), "quality": row.get(f"{state}__quality"),
            })
        output[(str(row["session_date"]), str(row["session_code"]))] = {
            "status": row.get("availability_disposition"), "states": states,
            "warning": "GC futures context is present only on the sealed 188-date sample and is not a case-selection gate.",
        }
    return output, {"rows": len(p_records), "primary_reference_exact": True, "state_checksum": canonical_hash(p_records)}


def load_contexts(cases: list[dict[str, Any]]) -> dict[str, Any]:
    session_ids = {row["session_record_id"] for row in cases}
    sessions = {row["record_id"]: row for row in read_jsonl(CASEBOOK / "sessions.jsonl.gz") if row["record_id"] in session_ids}
    ids = {"fundamental": set(), "structure": set(), "cross": set(), "positioning": set()}
    for session in sessions.values():
        state = session["decision_state"]
        ids["fundamental"].add(state.get("fundamental_snapshot_id"))
        ids["structure"].add(state.get("market_structure_snapshot_id"))
        ids["cross"].add(state.get("cross_market_snapshot_id"))
        if state.get("positioning_record_id"):
            ids["positioning"].add(state["positioning_record_id"])
    fundamentals = {row["record_id"]: row for row in read_jsonl(CASEBOOK / "fundamentals.jsonl.gz") if row.get("record_type") == "FUNDAMENTAL_SNAPSHOT" and row["record_id"] in ids["fundamental"]}
    structures = {row["record_id"]: row for row in read_jsonl(CASEBOOK / "structure_snapshots.jsonl.gz") if row["record_id"] in ids["structure"]}
    crosses = {row["record_id"]: row for row in read_jsonl(CASEBOOK / "cross_market_snapshots.jsonl.gz") if row["record_id"] in ids["cross"]}
    positioning = {row["record_id"]: row for row in read_jsonl(CASEBOOK / "positioning.jsonl.gz") if row["record_id"] in ids["positioning"]}
    events = list(read_jsonl(CASEBOOK / "events.jsonl.gz"))
    return {"sessions": sessions, "fundamentals": fundamentals, "structures": structures, "crosses": crosses, "positioning": positioning, "events": events}


def liquidity_view(m1: list[dict[str, Any]], reference: float) -> dict[str, Any]:
    rows = m1[-120:]
    current, baseline = rows[-15:], rows[:-15]
    def median(items: list[dict[str, Any]], key: str) -> float | None:
        values = [float(row[key]) for row in items if row.get(key) is not None]
        return statistics.median(values) if values else None
    current_range = [((row["high"] - row["low"]) / reference * 10_000) for row in current]
    baseline_range = [((row["high"] - row["low"]) / reference * 10_000) for row in baseline]
    return rounded({
        "status": "AVAILABLE" if len(rows) >= 114 else "PARTIAL",
        "epistemic_status": "OBSERVED", "window_rows": len(rows),
        "current_spread_points": median(current, "spread_points"), "baseline_spread_points": median(baseline, "spread_points"),
        "current_spread_index": None if median(current, "spread_price") is None else median(current, "spread_price") / reference * 100,
        "current_range_bps": statistics.median(current_range) if current_range else None,
        "baseline_range_bps": statistics.median(baseline_range) if baseline_range else None,
        "current_tick_volume": median(current, "volume"), "baseline_tick_volume": median(baseline, "volume"),
        "warning": "Spread and tick activity are IC Markets broker observations, not centralized COMEX liquidity.",
    })


def make_payloads(
    cases: list[dict[str, Any]], charts: dict[str, dict[str, list[dict[str, Any]]]], contexts: dict[str, Any], gc: dict[tuple[str, str], Any]
) -> list[dict[str, Any]]:
    output = []
    for case in sorted(cases, key=lambda item: item["global_sequence"]):
        alias, cutoff = case["case_alias"], parse_timestamp(case["checkpoint_at"])
        case_charts = charts[alias]
        m1, m15 = case_charts["1m"], case_charts["15m"]
        if not m1 or m1[-1]["_available_at"] > cutoff:
            raise RuntimeError(f"Missing point-in-time M1 reference for {alias}")
        reference, atr = float(m1[-1]["close"]), latest_atr(m15)
        if reference <= 0 or atr is None or atr <= 0:
            raise RuntimeError(f"Technically unavailable reference/ATR for frozen case {alias}")
        session = contexts["sessions"][case["session_record_id"]]
        state = session["decision_state"]
        fundamental = contexts["fundamentals"].get(state.get("fundamental_snapshot_id"))
        structure = contexts["structures"].get(state.get("market_structure_snapshot_id"))
        cross = contexts["crosses"].get(state.get("cross_market_snapshot_id"))
        positioning = contexts["positioning"].get(state.get("positioning_record_id"))
        temporal_records = [session, fundamental, structure, cross]
        for record in temporal_records:
            if record is None:
                continue
            available_field = "availability_at" if record.get("record_type") == "SESSION_CASE" else "available_at"
            if parse_timestamp(str(record[available_field])) > cutoff:
                raise RuntimeError(f"Point-in-time context leakage for {alias}: {record.get('record_type')}")
        if positioning is not None and parse_timestamp(str(positioning["publication_at"])) > cutoff:
            raise RuntimeError(f"Point-in-time COT leakage for {alias}")
        released = []
        for event in contexts["events"]:
            available = parse_timestamp(str(event["event_available_at"]))
            if cutoff - timedelta(hours=6) <= available <= cutoff:
                released.append(event_view(event, cutoff))
        charts_view = {timeframe: chart_view(case_charts[timeframe], reference, limit) for timeframe, limit in BAR_LIMITS.items()}
        charts_view["1w"] = weekly_view(case_charts["1d"], reference, cutoff)
        payload = rounded({
            "case_alias": alias, "mode": case["mode"], "mode_sequence": case["mode_sequence"],
            "global_sequence": case["global_sequence"], "session_code": case["session_code"],
            "checkpoint_label": "SESSION_OPEN_PLUS_60_MINUTES", "reference_index": 100.0,
            "m15_atr_index": atr / reference * 100.0,
            "charts": charts_view,
            "session": session_context_view(session, reference),
            "structure": structure_view(structure, reference, cutoff),
            "fundamental": fundamental_view(fundamental),
            "cross_market": cross_market_view(cross),
            "positioning": positioning_view(positioning),
            "released_events": released,
            "liquidity": liquidity_view(m1, reference),
            "gc_order_flow": gc.get((case["session_date"], case["session_code"]), {
                "status": "UNKNOWN_NOT_IN_SEALED_188_DATE_SAMPLE", "states": [],
                "warning": "No GC MBO/MBP-10 context exists for this date; nothing was imputed.",
            }),
            "display_policy": {
                "absolute_date_hidden": True, "absolute_time_hidden": True, "absolute_price_hidden": True,
                "completed_candles_only": True, "future_scored_path_present": False,
            },
        })
        payload["payload_sha256"] = canonical_hash(payload)
        output.append(payload)
    return output


def make_practice_paths(cases: list[dict[str, Any]], paths: dict[str, list[dict[str, Any]]], charts: dict[str, dict[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    output = []
    by_alias = {row["case_alias"]: row for row in cases}
    for alias in sorted(paths):
        reference = float(charts[alias]["1m"][-1]["close"])
        cutoff = parse_timestamp(by_alias[alias]["checkpoint_at"])
        bars = []
        for row in paths[alias]:
            bars.append({
                "minutes_after_checkpoint": int((row["_open_at"] - cutoff).total_seconds() // 60) + 1,
                "open": normalized_price(row["open"], reference), "high": normalized_price(row["high"], reference),
                "low": normalized_price(row["low"], reference), "close": normalized_price(row["close"], reference),
                "spread_price_index": None if row["spread_price"] is None else row["spread_price"] / reference * 100,
            })
        output.append({
            "case_alias": alias, "mode": "PRACTICE", "session_code": by_alias[alias]["session_code"],
            "reference_index": 100.0, "bars": rounded(bars),
        })
    return output


def leakage_audit(payloads: list[dict[str, Any]], practice: list[dict[str, Any]]) -> dict[str, Any]:
    serialized = "\n".join(canonical_bytes(row).decode("utf-8") for row in payloads)
    scored_aliases = {row["case_alias"] for row in payloads if row["mode"] == "SCORED"}
    practice_aliases = {row["case_alias"] for row in practice}
    checks = {
        "payload_count_260": len(payloads) == 260,
        "practice_future_count_20": len(practice) == 20,
        "practice_future_aliases_only": all(alias.startswith("P-") for alias in practice_aliases),
        "no_scored_future_path": scored_aliases.isdisjoint(practice_aliases),
        "no_iso_calendar_date_in_display": ISO_DATE.search(serialized) is None,
        "no_iso_timestamp_in_display": ISO_TIMESTAMP.search(serialized) is None,
        "all_reference_indices_100": all(row["reference_index"] == 100.0 for row in payloads),
        "all_scored_future_flags_false": all(not row["display_policy"]["future_scored_path_present"] for row in payloads if row["mode"] == "SCORED"),
        "all_case_payload_hashes_valid": all(canonical_hash({key: value for key, value in row.items() if key != "payload_sha256"}) == row["payload_sha256"] for row in payloads),
    }
    return {"checks": checks, "pass": all(checks.values())}


def main() -> int:
    for path in (PRIMARY_PAYLOAD, REFERENCE_PAYLOAD, PRIMARY_PRACTICE, REFERENCE_PRACTICE, CERTIFICATION):
        if path.exists():
            raise RuntimeError(f"Append-only target already exists: {path.relative_to(ROOT)}")
    freeze = verify_population_freeze()
    registry = json.loads(PRIVATE_REGISTRY.read_text(encoding="utf-8"))
    cases = registry["cases"]
    if canonical_hash(cases) != freeze["population_sha256"]:
        raise RuntimeError("Private population hash differs from frozen population")

    contexts = load_contexts(cases)
    gc, gc_diagnostics = gc_views(GC_PRIMARY, GC_REFERENCE)
    primary_charts, primary_future = build_price_inputs(cases, parse_price_primary)
    reference_charts, reference_future = build_price_inputs(cases, parse_price_reference)
    primary_inputs_hash = canonical_hash(primary_charts)
    reference_inputs_hash = canonical_hash(reference_charts)
    primary_future_hash = canonical_hash(primary_future)
    reference_future_hash = canonical_hash(reference_future)
    if primary_inputs_hash != reference_inputs_hash or primary_future_hash != reference_future_hash:
        raise RuntimeError("Independent price materialization differs")

    primary_payloads = make_payloads(cases, primary_charts, contexts, gc)
    reference_payloads = make_payloads(cases, reference_charts, contexts, gc)
    primary_practice = make_practice_paths(cases, primary_future, primary_charts)
    reference_practice = make_practice_paths(cases, reference_future, reference_charts)
    if primary_payloads != reference_payloads or primary_practice != reference_practice:
        raise RuntimeError("Independent replay payload reproduction differs")
    leakage = leakage_audit(primary_payloads, primary_practice)
    if not leakage["pass"]:
        raise RuntimeError(f"Replay leakage audit failed: {leakage}")

    write_jsonl_gzip(PRIMARY_PAYLOAD, primary_payloads)
    write_jsonl_gzip(REFERENCE_PAYLOAD, reference_payloads)
    write_jsonl_gzip(PRIMARY_PRACTICE, primary_practice)
    write_jsonl_gzip(REFERENCE_PRACTICE, reference_practice)
    gates = {
        "population_freeze_verified": True,
        "case_count_260": len(primary_payloads) == 260,
        "price_inputs_independently_reproduced": primary_inputs_hash == reference_inputs_hash,
        "practice_inputs_independently_reproduced": primary_future_hash == reference_future_hash,
        "display_payloads_exact": primary_payloads == reference_payloads,
        "practice_payloads_exact": primary_practice == reference_practice,
        "display_gzip_byte_identical": sha256_file(PRIMARY_PAYLOAD) == sha256_file(REFERENCE_PAYLOAD),
        "practice_gzip_byte_identical": sha256_file(PRIMARY_PRACTICE) == sha256_file(REFERENCE_PRACTICE),
        "gc_primary_reference_exact": gc_diagnostics["primary_reference_exact"],
        "leakage_audit_pass": leakage["pass"],
        "scored_outcomes_not_materialized": True,
        "calendar_2025_2026_not_opened": True,
        "no_acquisition_or_charge": True,
    }
    certification = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_MATERIALIZATION_CERTIFICATION_1_0",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS_PAST_ONLY_DISPLAY_MATERIALIZATION" if all(gates.values()) else "FAIL_DISPLAY_MATERIALIZATION",
        "case_count": len(primary_payloads), "practice_future_case_count": len(primary_practice),
        "primary_inputs_sha256": primary_inputs_hash, "reference_inputs_sha256": reference_inputs_hash,
        "primary_payload_sha256": sha256_file(PRIMARY_PAYLOAD), "reference_payload_sha256": sha256_file(REFERENCE_PAYLOAD),
        "primary_practice_sha256": sha256_file(PRIMARY_PRACTICE), "reference_practice_sha256": sha256_file(REFERENCE_PRACTICE),
        "gc_diagnostics": gc_diagnostics, "leakage_audit": leakage, "gates": gates,
        "outcomes_calculated": False, "scored_future_paths_opened": False,
        "calendar_2025_opened": False, "calendar_2026_opened": False,
        "acquisition_performed": False, "charge_usd": 0.0,
    }
    write_new_json(CERTIFICATION, certification)
    print(json.dumps({"verdict": certification["verdict"], "cases": len(primary_payloads), "gates": gates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
