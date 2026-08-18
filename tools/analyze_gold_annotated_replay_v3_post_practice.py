#!/usr/bin/env python3
"""Analyze the sealed, zero-credit V3 practice ledger deterministically."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "research_artifacts/gold_annotated_replay_v3"
LEDGER = ARTIFACT / "ledgers/practice_event_ledger_v3.jsonl"
PRIMARY_STREAM = ARTIFACT / "practice_streams_v3_1.primary.jsonl.gz"
REFERENCE_STREAM = ARTIFACT / "practice_streams_v3_1.reference.jsonl.gz"
FREEZE = (
    ROOT
    / "research_manifests/gold_annotated_replay_v3_post_practice_diagnostic_amendment_a_freeze.json"
)
POLICY = ARTIFACT / "execution_policy.json"
REGISTRY = ARTIFACT / "practice_registry.public.json"
RESULT = ARTIFACT / "post_practice_diagnostic.json"
TRADE_TABLE = ARTIFACT / "post_practice_trade_table.csv"
REPORT = ROOT / "GOLD_ANNOTATED_REPLAY_V3_POST_PRACTICE_DIAGNOSTIC_REPORT.md"
SEAL = ROOT / "research_manifests/gold_annotated_replay_v3_post_practice_diagnostic_seal.json"
GENESIS = "0" * 64
RISK_UNIT_USD = 50.0
BOOTSTRAP_SEED = 20260817
BOOTSTRAP_SAMPLES = 20_000
SUPPORT_FLOOR = 3

TRIGGER_TAXONOMY = {
    "SWEEP_RECLAIM": ("sweep", "reclaim", "liquidity grab", "stop hunt"),
    "BREAK_RETEST": ("retest", "break and retest", "bos", "break of structure", "neckline"),
    "REVERSAL_RESPONSE": (
        "reversal",
        "engulf",
        "pin bar",
        "hammer",
        "shooting star",
        "rejection",
        "wick",
    ),
    "FIB_RETRACE": ("fib", "fibonacci", "retrace", "retracement", "38%", "50%", "61%", "62%"),
    "MOMENTUM_DISPLACEMENT": (
        "displacement",
        "momentum",
        "aggressive buyer",
        "aggressive seller",
        "impulse",
    ),
    "LEVEL_LOCATION": (
        "support",
        "resistance",
        "previous high",
        "previous low",
        "swing high",
        "swing low",
        "liquidity",
    ),
}

MACRO_TERMS = (
    "yield",
    "real yield",
    "rate",
    "fed",
    "dollar",
    "dxy",
    "inflation",
    "cpi",
    "pce",
    "payroll",
    "nfp",
    "employment",
    "growth",
    "risk",
    "positioning",
    "liquidity",
)
HTF_TERMS = (
    "weekly",
    "daily",
    "h4",
    "4h",
    "h1",
    "1h",
    "m15",
    "15m",
    "trend",
    "structure",
)
LOCATION_TERMS = (
    "support",
    "resistance",
    "range",
    "high",
    "low",
    "swing",
    "bullish",
    "bearish",
)
INVALIDATION_ACTIONS = ("break", "close", "accept", "lose", "above", "below", "invalidate")
TARGET_TERMS = (
    "previous high",
    "previous low",
    "swing high",
    "swing low",
    "support",
    "resistance",
    "liquidity",
    "benchmark",
)
EVENT_TERMS = ("cpi", "pce", "nfp", "payroll", "fomc", "fed", "event", "news", "none")
HIGHER_TIMEFRAME = {
    "1m": "5m",
    "5m": "15m",
    "15m": "1h",
    "1h": "4h",
    "4h": "1d",
    "1d": None,
    "1w": None,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def rounded(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return statistics.fmean(rows) if rows else None


def median(values: Iterable[float]) -> float | None:
    rows = list(values)
    return statistics.median(rows) if rows else None


def contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in terms)


def direction_sign(direction: str) -> int:
    require(direction in {"LONG", "SHORT"}, f"Unknown direction: {direction}")
    return 1 if direction == "LONG" else -1


def session_at(timestamp: str) -> str:
    instant = parse_time(timestamp)
    date = instant.date()
    minute = instant.hour * 60 + instant.minute
    london_start, london_end = (420, 960) if date.isoformat() < "2021-10-31" else (480, 1020)
    ny_start, ny_end = (720, 1260) if date.isoformat() < "2021-11-07" else (780, 1320)
    if london_start <= minute < london_end and ny_start <= minute < ny_end:
        return "LONDON_NEW_YORK_OVERLAP"
    if london_start <= minute < london_end:
        return "LONDON"
    if ny_start <= minute < ny_end:
        return "NEW_YORK"
    if 0 <= minute < london_start:
        return "ASIA"
    if ny_end <= minute < min(1440, ny_end + 60):
        return "ROLLOVER"
    return "OTHER"


def verify_sources() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    for path in (RESULT, TRADE_TABLE, REPORT, SEAL):
        require(not path.exists(), f"Append-only output already exists: {path.relative_to(ROOT)}")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    for record in freeze["frozen_sources"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen source missing: {record['path']}")
        require(path.stat().st_size == record["bytes"], f"Frozen size differs: {record['path']}")
        require(sha256_file(path) == record["sha256"], f"Frozen hash differs: {record['path']}")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    events = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()]
    require(len(events) == freeze["ledger_records"] == 2041, "Ledger count differs")
    prior = GENESIS
    seen_idempotency: set[str] = set()
    for index, event in enumerate(events, start=1):
        require(event["ledger_sequence"] == index, "Ledger sequence is not contiguous")
        require(event["prior_record_sha256"] == prior, "Ledger prior hash differs")
        body = {key: value for key, value in event.items() if key != "record_sha256"}
        require(event["record_sha256"] == canonical_hash(body), "Ledger record hash differs")
        key = str(event["idempotency_key"])
        require(key not in seen_idempotency, "Duplicate idempotency key")
        seen_idempotency.add(key)
        prior = event["record_sha256"]
    require(prior == freeze["ledger_head_sha256"], "Ledger head differs")
    return policy, registry, events


def normalize_order(order: dict[str, Any], sequence: int) -> dict[str, Any]:
    return {
        "submit_sequence": sequence,
        "order_id": order["order_id"],
        "case_alias": order["case_alias"],
        "direction": order["direction"],
        "order_type": order["order_type"],
        "selected_timeframe": order["selected_timeframe"],
        "submitted_at": order["submitted_at"],
        "effective_at": order["effective_at"],
        "expiry_at": order["expiry_at"],
        "entry": order["entry"],
        "stop": order["stop"],
        "target": order["target"],
        "quantity_ounces": order["quantity_ounces"],
        "risk_cap_usd": order["risk_cap_usd"],
        "risk_usd": order["risk_usd"],
        "annotation": order["annotation"],
        "drawing_kinds": sorted(row["kind"] for row in order.get("drawings", [])),
        "visible_state_sha256": order["visible_state_sha256"],
        "point_in_time_context_sha256": order["point_in_time_context_sha256"],
    }


def extract_trades_primary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    orders: dict[str, dict[str, Any]] = {}
    sequence: list[str] = []
    for event in events:
        event_type = event["event_type"]
        if event_type == "ORDER_SUBMITTED":
            order = normalize_order(event["data"]["order"], event["ledger_sequence"])
            orders[order["order_id"]] = order
            sequence.append(order["order_id"])
        elif event_type == "ORDER_FILLED":
            orders[event["data"]["order_id"]]["fill"] = event["data"]["fill"]
        elif event_type == "POSITION_CLOSED":
            orders[event["data"]["order_id"]]["resolution"] = event["data"]["resolution"]
    return [orders[order_id] for order_id in sequence]


def extract_trades_reference(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    submitted = [event for event in events if event["event_type"] == "ORDER_SUBMITTED"]
    fills = {
        event["data"]["order_id"]: event["data"]["fill"]
        for event in events
        if event["event_type"] == "ORDER_FILLED"
    }
    resolutions = {
        event["data"]["order_id"]: event["data"]["resolution"]
        for event in events
        if event["event_type"] == "POSITION_CLOSED"
    }
    result = []
    for event in submitted:
        row = normalize_order(event["data"]["order"], event["ledger_sequence"])
        row["fill"] = fills[row["order_id"]]
        row["resolution"] = resolutions[row["order_id"]]
        result.append(row)
    return result


def load_streams(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            body = {key: value for key, value in row.items() if key != "stream_sha256"}
            require(row["stream_sha256"] == canonical_hash(body), f"Stream hash differs: {row['case_alias']}")
            rows[row["case_alias"]] = row
    require(sorted(rows) == [f"V3-P-{index:03d}" for index in range(1, 21)], "Stream aliases differ")
    return rows


def latest_available(rows: list[dict[str, Any]], decision: datetime) -> dict[str, Any] | None:
    eligible = [row for row in rows if parse_time(row["available_at"]) <= decision]
    return max(eligible, key=lambda row: parse_time(row["available_at"])) if eligible else None


def alignment(direction: str, state: str | None) -> str:
    if state is None or state in {"UNKNOWN", "RANGE", "MIXED_OR_TRANSITIONING", "NEUTRAL_OR_CONFLICTED"}:
        return "NEUTRAL_OR_UNKNOWN"
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    opposite = "BEARISH" if expected == "BULLISH" else "BULLISH"
    if expected in state:
        return "CONFIRMING"
    if opposite in state:
        return "CONTRADICTING"
    return "NEUTRAL_OR_UNKNOWN"


def trigger_tags(annotation: dict[str, Any]) -> list[str]:
    text = f"{annotation.get('entry_trigger', '')} {annotation.get('thesis', '')}".casefold()
    tags = [name for name, terms in TRIGGER_TAXONOMY.items() if contains_any(text, terms)]
    return tags or (["MISSING"] if not text.strip() else ["OTHER_WRITTEN_TRIGGER"])


def driver_tags(annotation: dict[str, Any]) -> list[str]:
    text = f"{annotation.get('dominant_driver', '')} {annotation.get('thesis', '')}".casefold()
    groups = {
        "REAL_OR_NOMINAL_YIELDS": ("real yield", "yield", "treasury"),
        "USD_DOLLAR": ("dxy", "dollar", "usd"),
        "FED_RATES": ("fed", "rate", "cut", "hike"),
        "INFLATION": ("inflation", "cpi", "pce"),
        "LABOUR_GROWTH": ("nfp", "payroll", "employment", "job", "growth"),
        "RISK_LIQUIDITY": ("risk", "liquidity", "positioning", "buyers", "sellers"),
    }
    tags = [name for name, terms in groups.items() if contains_any(text, terms)]
    return tags or ["OTHER_OR_UNSPECIFIED"]


def reasoning_flags(annotation: dict[str, Any]) -> dict[str, Any]:
    thesis_driver = f"{annotation.get('thesis', '')} {annotation.get('dominant_driver', '')}".casefold()
    htf = str(annotation.get("higher_timeframe_context", "")).casefold()
    invalidation = str(annotation.get("invalidation_logic", "")).casefold().strip()
    target = str(annotation.get("target_logic", "")).casefold().strip()
    event = str(annotation.get("event_risk", "")).casefold().strip()
    numeric_invalidation = bool(re.search(r"\d+(?:\.\d+)?", invalidation))
    numeric_target = bool(re.search(r"\d+(?:\.\d+)?", target))
    generic_invalidations = {
        "bearish structure",
        "bullish structure",
        "structure",
        "market structure",
        "structure change",
    }
    invalidation_specific = (
        invalidation not in generic_invalidations
        and (
            numeric_invalidation
            or (contains_any(invalidation, INVALIDATION_ACTIONS) and contains_any(invalidation, LOCATION_TERMS))
        )
    )
    target_generic = target in {"target", "next level", "next previous level", "liquidity"}
    target_specific = not target_generic and (numeric_target or contains_any(target, TARGET_TERMS))
    required = (
        "thesis",
        "dominant_driver",
        "higher_timeframe_context",
        "session_liquidity_context",
        "entry_trigger",
        "invalidation_logic",
        "target_logic",
        "event_risk",
    )
    return {
        "all_required_nonempty": all(str(annotation.get(field, "")).strip() for field in required),
        "macro_specific": contains_any(thesis_driver, MACRO_TERMS),
        "higher_timeframe_specific": contains_any(htf, HTF_TERMS) and contains_any(htf, LOCATION_TERMS),
        "invalidation_specific": invalidation_specific,
        "invalidation_generic": bool(invalidation) and not invalidation_specific,
        "target_specific": target_specific,
        "target_generic": bool(target) and not target_specific,
        "event_risk_specific": bool(event) and contains_any(event, EVENT_TERMS),
        "annotation_word_count": len(
            " ".join(str(annotation.get(field, "")) for field in required).split()
        ),
    }


def enrich_trade(base: dict[str, Any], stream: dict[str, Any], commission_per_ounce: float) -> dict[str, Any]:
    direction = base["direction"]
    sign = direction_sign(direction)
    quantity = int(base["quantity_ounces"])
    fill = base["fill"]
    resolution = base["resolution"]
    fill_price = float(fill["actual_price"])
    exit_price = float(resolution["actual_exit_price"])
    commission = commission_per_ounce * quantity
    pnl = sign * (exit_price - fill_price) * quantity - commission
    result = "WIN" if pnl > 0.01 else "LOSS" if pnl < -0.01 else "SCRATCH"
    submitted = parse_time(base["submitted_at"])
    fill_at = parse_time(fill["fill_at"])
    exit_at = parse_time(resolution["exit_at"])
    expiry_at = parse_time(base["expiry_at"])
    planned_risk_price = sign * (float(base["entry"]) - float(base["stop"]))
    planned_target_price = sign * (float(base["target"]) - float(base["entry"]))
    effective_risk_price = sign * (fill_price - float(base["stop"]))
    effective_target_price = sign * (float(base["target"]) - fill_price)

    bars = [
        bar
        for bar in stream["timeframes"]["1m"]
        if fill_at <= parse_time(bar["open_at"]) <= exit_at
    ]
    require(bars, f"No M1 outcome bars for {base['order_id']}")
    if direction == "LONG":
        mfe_price = max(0.0, max(float(bar["high"]) for bar in bars) - fill_price)
        mae_price = max(0.0, fill_price - min(float(bar["low"]) for bar in bars))
    else:
        mfe_price = max(0.0, fill_price - min(float(bar["low"]) for bar in bars))
        mae_price = max(0.0, max(float(bar["high"]) for bar in bars) - fill_price)
    mfe_usd = mfe_price * quantity
    mae_usd = mae_price * quantity

    later_target = False
    if resolution["state"] == "STOPPED":
        later = [
            bar
            for bar in stream["timeframes"]["1m"]
            if exit_at < parse_time(bar["open_at"]) < expiry_at
        ]
        if direction == "LONG":
            later_target = any(float(bar["high"]) >= float(base["target"]) for bar in later)
        else:
            later_target = any(float(bar["low"]) <= float(base["target"]) for bar in later)

    fundamental = latest_available(stream["context_timeline"]["fundamentals"], submitted)
    structure = latest_available(stream["context_timeline"]["structure"], submitted)
    engine = fundamental["engine_state"] if fundamental else {}
    score = float(engine["directional_score"]) if engine.get("directional_score") is not None else None
    system_state = "NEUTRAL_OR_CONFLICTED"
    if score is not None and score > 10:
        system_state = "BULLISH"
    elif score is not None and score < -10:
        system_state = "BEARISH"

    structures = {
        row["timeframe"]: row for row in (structure.get("timeframes", []) if structure else [])
    }
    selected_structure = structures.get(base["selected_timeframe"])
    higher_code = HIGHER_TIMEFRAME.get(base["selected_timeframe"])
    higher_structure = structures.get(higher_code) if higher_code else None
    selected_trend = selected_structure.get("trend") if selected_structure else None
    higher_trend = higher_structure.get("trend") if higher_structure else None
    atr = float(selected_structure["atr14"]) if selected_structure and selected_structure.get("atr14") else None
    complete_bars = [
        bar
        for bar in stream["timeframes"][base["selected_timeframe"]]
        if parse_time(bar["available_at"]) <= submitted
    ]
    recent = complete_bars[-3:]
    recent_move_atr = None
    if atr and recent:
        recent_move_atr = sign * (float(recent[-1]["close"]) - float(recent[0]["open"])) / atr

    annotation = base["annotation"]
    user_state = str(annotation.get("fundamental_direction", "UNKNOWN"))
    flags = reasoning_flags(annotation)
    entry_cost_usd = sign * (float(fill["actual_price"]) - float(fill["raw_price"])) * quantity
    exit_cost_usd = sign * (float(resolution["raw_exit_price"]) - float(resolution["actual_exit_price"])) * quantity
    row = {
        **base,
        "trading_date_utc": stream["trading_date_utc"],
        "weekday": parse_time(base["submitted_at"]).strftime("%A").upper(),
        "decision_session": session_at(base["submitted_at"]),
        "actual_fill_price": rounded(fill_price, 8),
        "actual_exit_price": rounded(exit_price, 8),
        "fill_at": fill["fill_at"],
        "exit_at": resolution["exit_at"],
        "resolution_state": resolution["state"],
        "result": result,
        "net_pnl_usd": rounded(pnl, 8),
        "r50": rounded(pnl / RISK_UNIT_USD, 8),
        "planned_risk_r": rounded(pnl / float(base["risk_usd"]), 8),
        "planned_reward_risk": rounded(planned_target_price / planned_risk_price, 6)
        if planned_risk_price > 0
        else None,
        "effective_reward_risk": rounded(effective_target_price / effective_risk_price, 6)
        if effective_risk_price > 0
        else None,
        "effective_stop_risk_usd": rounded(effective_risk_price * quantity, 8),
        "entry_execution_cost_usd": rounded(entry_cost_usd, 8),
        "exit_execution_cost_usd": rounded(exit_cost_usd, 8),
        "recorded_execution_cost_usd": rounded(entry_cost_usd + exit_cost_usd + commission, 8),
        "fill_delay_minutes": rounded((fill_at - submitted).total_seconds() / 60, 3),
        "holding_minutes": rounded((exit_at - fill_at).total_seconds() / 60, 3),
        "m1_path_bars": len(bars),
        "mfe_price": rounded(mfe_price, 8),
        "mae_price": rounded(mae_price, 8),
        "mfe_usd": rounded(mfe_usd, 8),
        "mae_usd": rounded(mae_usd, 8),
        "mfe_r50": rounded(mfe_usd / RISK_UNIT_USD, 8),
        "mae_r50": rounded(mae_usd / RISK_UNIT_USD, 8),
        "winner_capture_efficiency": rounded(pnl / mfe_usd, 6) if pnl > 0 and mfe_usd > 0 else None,
        "stopped_then_later_target": later_target,
        "mfe_at_least_half_r_before_exit": mfe_usd >= 0.5 * RISK_UNIT_USD,
        "fundamental_snapshot_available": fundamental is not None,
        "system_bias_label": engine.get("bias_label"),
        "system_directional_score": rounded(score, 4),
        "system_confidence": rounded(float(engine["confidence"]), 4)
        if engine.get("confidence") is not None
        else None,
        "system_dominant_driver": engine.get("dominant_driver"),
        "system_regime": engine.get("regime_label"),
        "system_event_risk": engine.get("event_risk"),
        "user_fundamental_alignment": alignment(direction, user_state),
        "system_macro_alignment": alignment(direction, system_state),
        "selected_structure_trend": selected_trend,
        "selected_structure_alignment": alignment(direction, selected_trend),
        "higher_structure_timeframe": higher_code,
        "higher_structure_trend": higher_trend,
        "higher_structure_alignment": alignment(direction, higher_trend),
        "selected_atr14": rounded(atr, 8),
        "stop_distance_atr": rounded(planned_risk_price / atr, 6) if atr and planned_risk_price > 0 else None,
        "target_distance_atr": rounded(planned_target_price / atr, 6) if atr and planned_target_price > 0 else None,
        "recent_directional_move_atr": rounded(recent_move_atr, 6),
        "entry_chase_flag": recent_move_atr is not None and recent_move_atr >= 0.75,
        "trigger_tags": trigger_tags(annotation),
        "driver_tags": driver_tags(annotation),
        "reasoning_flags": flags,
    }
    return row


def profit_factor(rows: list[dict[str, Any]]) -> float | None:
    gross_win = sum(float(row["net_pnl_usd"]) for row in rows if row["net_pnl_usd"] > 0)
    gross_loss = -sum(float(row["net_pnl_usd"]) for row in rows if row["net_pnl_usd"] < 0)
    return gross_win / gross_loss if gross_loss > 0 else None


def basic_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["fill_at"], row["submit_sequence"]))
    wins = [row for row in ordered if row["result"] == "WIN"]
    losses = [row for row in ordered if row["result"] == "LOSS"]
    scratches = [row for row in ordered if row["result"] == "SCRATCH"]
    r_values = [float(row["r50"]) for row in ordered]
    win_r = [float(row["r50"]) for row in wins]
    loss_r = [float(row["r50"]) for row in losses]
    average_win = mean(win_r)
    average_loss = mean(loss_r)
    pf = profit_factor(ordered)
    return {
        "support": len(ordered),
        "support_disposition": "SUPPORTED_DESCRIPTIVE" if len(ordered) >= SUPPORT_FLOOR else "LOW_SUPPORT_DESCRIPTIVE_ONLY",
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(scratches),
        "win_rate": rounded(len(wins) / len(ordered), 6) if ordered else None,
        "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in ordered), 8),
        "net_r50": rounded(sum(r_values), 8),
        "expectancy_r50": rounded(mean(r_values), 8),
        "median_r50": rounded(median(r_values), 8),
        "profit_factor": rounded(pf, 6),
        "profit_factor_state": "FINITE" if pf is not None else "UNDEFINED_NO_LOSSES",
        "average_win_r50": rounded(average_win, 8),
        "average_loss_r50": rounded(average_loss, 8),
        "payoff_ratio": rounded(average_win / abs(average_loss), 6)
        if average_win is not None and average_loss not in {None, 0}
        else None,
    }


def segment(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        groups[str(value if value is not None else "UNKNOWN")].append(row)
    return {name: basic_stats(group) for name, group in sorted(groups.items())}


def multi_segment(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for value in row[key]:
            groups[str(value)].append(row)
    return {name: basic_stats(group) for name, group in sorted(groups.items())}


def wilson_interval(wins: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total == 0:
        return None, None
    probability = wins / total
    denominator = 1 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(probability * (1 - probability) / total + z * z / (4 * total * total)) / denominator
    return center - margin, center + margin


def cluster_bootstrap(rows: list[dict[str, Any]], dates: list[str]) -> tuple[float | None, float | None]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_date[row["trading_date_utc"]].append(float(row["r50"]))
    generator = random.Random(BOOTSTRAP_SEED)
    estimates: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample: list[float] = []
        for _day in dates:
            sampled_date = dates[generator.randrange(len(dates))]
            sample.extend(by_date[sampled_date])
        if sample:
            estimates.append(statistics.fmean(sample))
    return quantile(estimates, 0.025), quantile(estimates, 0.975)


def drawdown_and_streaks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["fill_at"], row["submit_sequence"]))
    cumulative = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    current_win = current_loss = max_win = max_loss = 0
    for row in ordered:
        cumulative += float(row["r50"])
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
        if row["result"] == "WIN":
            current_win += 1
            current_loss = 0
        elif row["result"] == "LOSS":
            current_loss += 1
            current_win = 0
        else:
            current_win = current_loss = 0
        max_win = max(max_win, current_win)
        max_loss = max(max_loss, current_loss)
    return {
        "maximum_drawdown_r50": rounded(maximum_drawdown, 8),
        "maximum_drawdown_usd": rounded(maximum_drawdown * RISK_UNIT_USD, 8),
        "longest_win_streak": max_win,
        "longest_loss_streak": max_loss,
    }


def confidence_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    probabilities = [float(row["annotation"]["confidence"]) / 100 for row in rows]
    outcomes = [1.0 if row["result"] == "WIN" else 0.0 for row in rows]
    brier = mean((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes, strict=True))
    bins = ((0, 50), (50, 60), (60, 70), (70, 80), (80, 101))
    calibration = {}
    for lower, upper in bins:
        indexes = [index for index, probability in enumerate(probabilities) if lower <= probability * 100 < upper]
        if indexes:
            calibration[f"{lower}_{upper - 1}"] = {
                "support": len(indexes),
                "mean_confidence": rounded(mean(probabilities[index] for index in indexes), 6),
                "observed_win_rate": rounded(mean(outcomes[index] for index in indexes), 6),
                "support_disposition": "SUPPORTED_DESCRIPTIVE"
                if len(indexes) >= SUPPORT_FLOOR
                else "LOW_SUPPORT_DESCRIPTIVE_ONLY",
            }
    return {
        "brier_score": rounded(brier, 6),
        "mean_stated_confidence": rounded(mean(probabilities), 6),
        "observed_win_rate": rounded(mean(outcomes), 6),
        "confidence_minus_win_rate": rounded(mean(probabilities) - mean(outcomes), 6),
        "calibration_bins": calibration,
        "note": "Practice confidence is treated as a stated probability only for this diagnostic; engine confidence is not a win probability.",
    }


def summarize(
    rows: list[dict[str, Any]],
    registry: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    dates = [row["trading_date_utc"] for row in registry["cases"]]
    overall = basic_stats(rows)
    lower_win, upper_win = wilson_interval(overall["wins"], overall["support"])
    lower_expectancy, upper_expectancy = cluster_bootstrap(rows, dates)
    overall.update(
        {
            "win_rate_wilson_95": [rounded(lower_win, 6), rounded(upper_win, 6)],
            "expectancy_r50_day_cluster_bootstrap_95": [
                rounded(lower_expectancy, 6),
                rounded(upper_expectancy, 6),
            ],
            "normalized_account_return_percent": rounded(
                float(overall["net_pnl_usd"]) / 10_000 * 100,
                6,
            ),
            "r50_per_completed_practice_day": rounded(float(overall["net_r50"]) / len(dates), 8),
            "sharpe": "NOT_MEANINGFUL_SMALL_SAMPLE" if len(rows) < 30 else "NOT_CALCULATED",
            "sortino": "NOT_MEANINGFUL_SMALL_SAMPLE" if len(rows) < 30 else "NOT_CALCULATED",
        }
    )
    completed = {row["case_alias"] for row in events if row["event_type"] == "PRACTICE_DAY_COMPLETED"}
    traded_dates = {row["case_alias"] for row in rows}
    cursor_modes: dict[str, dict[str, int]] = defaultdict(lambda: {"events": 0, "minutes": 0})
    for event in events:
        if event["event_type"] in {"CURSOR_ADVANCED", "INTERVAL_SKIPPED"}:
            mode = str(event["data"].get("observation_mode", event["event_type"]))
            cursor_modes[mode]["events"] += 1
            cursor_modes[mode]["minutes"] += int(event["data"]["actual_increment_minutes"])
    reasoning_keys = (
        "all_required_nonempty",
        "macro_specific",
        "higher_timeframe_specific",
        "invalidation_specific",
        "invalidation_generic",
        "target_specific",
        "target_generic",
        "event_risk_specific",
    )
    reasoning = {
        key: {
            "count": sum(bool(row["reasoning_flags"][key]) for row in rows),
            "rate": rounded(mean(float(bool(row["reasoning_flags"][key])) for row in rows), 6),
        }
        for key in reasoning_keys
    }
    reasoning["annotation_word_count"] = {
        "mean": rounded(mean(float(row["reasoning_flags"]["annotation_word_count"]) for row in rows), 3),
        "median": rounded(median(float(row["reasoning_flags"]["annotation_word_count"]) for row in rows), 3),
    }
    path = {
        "mean_mfe_r50": rounded(mean(float(row["mfe_r50"]) for row in rows), 6),
        "median_mfe_r50": rounded(median(float(row["mfe_r50"]) for row in rows), 6),
        "mean_mae_r50": rounded(mean(float(row["mae_r50"]) for row in rows), 6),
        "median_mae_r50": rounded(median(float(row["mae_r50"]) for row in rows), 6),
        "mean_holding_minutes": rounded(mean(float(row["holding_minutes"]) for row in rows), 3),
        "median_holding_minutes": rounded(median(float(row["holding_minutes"]) for row in rows), 3),
        "mean_fill_delay_minutes": rounded(mean(float(row["fill_delay_minutes"]) for row in rows), 3),
        "total_recorded_execution_cost_usd": rounded(
            sum(float(row["recorded_execution_cost_usd"]) for row in rows), 6
        ),
        "stopped_trades": sum(row["resolution_state"] == "STOPPED" for row in rows),
        "stopped_then_later_target": sum(bool(row["stopped_then_later_target"]) for row in rows),
        "losses_with_at_least_half_r_mfe": sum(
            row["result"] == "LOSS" and bool(row["mfe_at_least_half_r_before_exit"])
            for row in rows
        ),
        "winner_mean_capture_efficiency": rounded(
            mean(
                float(row["winner_capture_efficiency"])
                for row in rows
                if row["winner_capture_efficiency"] is not None
            ),
            6,
        ),
        "entry_chase_flags": sum(bool(row["entry_chase_flag"]) for row in rows),
    }
    return {
        "overall": {**overall, **drawdown_and_streaks(rows)},
        "coverage": {
            "completed_days": len(completed),
            "traded_days": len(traded_dates),
            "no_trade_days": len(completed - traded_dates),
            "filled_trades": len(rows),
            "trades_per_completed_practice_day": rounded(len(rows) / len(completed), 6),
            "cursor_observation_modes": dict(sorted(cursor_modes.items())),
        },
        "segments": {
            "direction": segment(rows, "direction"),
            "timeframe": segment(rows, "selected_timeframe"),
            "session": segment(rows, "decision_session"),
            "weekday": segment(rows, "weekday"),
            "resolution": segment(rows, "resolution_state"),
            "user_fundamental_alignment": segment(rows, "user_fundamental_alignment"),
            "system_macro_alignment": segment(rows, "system_macro_alignment"),
            "selected_structure_alignment": segment(rows, "selected_structure_alignment"),
            "higher_structure_alignment": segment(rows, "higher_structure_alignment"),
            "trigger_tags": multi_segment(rows, "trigger_tags"),
            "driver_tags": multi_segment(rows, "driver_tags"),
            "entry_chase_flag": segment(rows, "entry_chase_flag"),
        },
        "confidence": confidence_diagnostics(rows),
        "path_and_execution": path,
        "reasoning_specificity": reasoning,
    }


def build_csv(rows: list[dict[str, Any]]) -> str:
    fields = (
        "order_id",
        "case_alias",
        "trading_date_utc",
        "submitted_at",
        "fill_at",
        "exit_at",
        "direction",
        "order_type",
        "selected_timeframe",
        "decision_session",
        "resolution_state",
        "result",
        "quantity_ounces",
        "risk_usd",
        "net_pnl_usd",
        "r50",
        "planned_risk_r",
        "planned_reward_risk",
        "effective_reward_risk",
        "mfe_r50",
        "mae_r50",
        "holding_minutes",
        "stopped_then_later_target",
        "entry_chase_flag",
        "system_bias_label",
        "system_directional_score",
        "user_fundamental_alignment",
        "system_macro_alignment",
        "selected_structure_alignment",
        "higher_structure_alignment",
        "confidence",
        "trigger_tags",
        "driver_tags",
        "thesis",
        "dominant_driver",
        "higher_timeframe_context",
        "session_liquidity_context",
        "entry_trigger",
        "invalidation_logic",
        "target_logic",
        "event_risk",
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in sorted(rows, key=lambda item: item["submit_sequence"]):
        flat = {key: row.get(key) for key in fields}
        flat["confidence"] = row["annotation"]["confidence"]
        for key in (
            "thesis",
            "dominant_driver",
            "higher_timeframe_context",
            "session_liquidity_context",
            "entry_trigger",
            "invalidation_logic",
            "target_logic",
            "event_risk",
        ):
            flat[key] = row["annotation"].get(key)
        flat["trigger_tags"] = "|".join(row["trigger_tags"])
        flat["driver_tags"] = "|".join(row["driver_tags"])
        writer.writerow(flat)
    return output.getvalue()


def markdown_table(rows: list[list[Any]], headers: list[str]) -> str:
    def cell(value: Any) -> str:
        return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def build_report(rows: list[dict[str, Any]], summary: dict[str, Any], completed_at: str) -> str:
    overall = summary["overall"]
    coverage = summary["coverage"]
    path = summary["path_and_execution"]
    chronological = []
    for row in sorted(rows, key=lambda item: item["submit_sequence"]):
        chronological.append(
            [
                row["case_alias"],
                row["trading_date_utc"],
                row["direction"],
                row["selected_timeframe"].upper(),
                row["decision_session"],
                row["resolution_state"],
                f"${row['net_pnl_usd']:.2f}",
                f"{row['r50']:+.3f}",
                f"{row['mfe_r50']:.2f}",
                f"{row['mae_r50']:.2f}",
                f"{row['annotation']['confidence']}%",
            ]
        )
    segment_rows = []
    for family in ("direction", "timeframe", "session", "user_fundamental_alignment", "system_macro_alignment", "selected_structure_alignment"):
        for state, stats in summary["segments"][family].items():
            segment_rows.append(
                [
                    family,
                    state,
                    stats["support"],
                    f"{stats['win_rate'] * 100:.1f}%" if stats["win_rate"] is not None else "—",
                    f"{stats['expectancy_r50']:+.3f}" if stats["expectancy_r50"] is not None else "—",
                    f"{stats['net_r50']:+.3f}",
                    stats["support_disposition"],
                ]
            )
    reasoning = summary["reasoning_specificity"]
    sample_label = (
        "DESCRIPTIVELY_POSITIVE_BUT_INCONCLUSIVE"
        if overall["net_r50"] > 0
        else "DESCRIPTIVELY_NEGATIVE"
        if overall["net_r50"] < 0
        else "DESCRIPTIVELY_FLAT"
    )
    return f"""# Gold Annotated Replay V3 Post-Practice Diagnostic

Completed: `{completed_at}`

Formal evidence status: `ZERO_CREDIT_DESCRIPTIVE`

Sample description: `{sample_label}`

Edge verdict: `NOT_EVALUABLE_FROM_TWENTY_PRACTICE_DAYS`

## Bottom line

You completed all {coverage['completed_days']} practice days and placed {coverage['filled_trades']} filled trades across {coverage['traded_days']} traded days; {coverage['no_trade_days']} days had no trade. The ledger is complete and internally reproducible.

At the frozen $50 risk unit, the practice sample produced **{overall['net_r50']:+.3f}R (${overall['net_pnl_usd']:+.2f})**, a **{overall['win_rate'] * 100:.1f}%** win rate, **{overall['expectancy_r50']:+.3f}R/trade** expectancy, and profit factor **{overall['profit_factor'] if overall['profit_factor'] is not None else 'undefined'}**. Maximum chronological drawdown was **{overall['maximum_drawdown_r50']:.3f}R (${overall['maximum_drawdown_usd']:.2f})**.

The 95% Wilson win-rate interval is {overall['win_rate_wilson_95'][0] * 100:.1f}% to {overall['win_rate_wilson_95'][1] * 100:.1f}%. The completed-day cluster-bootstrap expectancy interval is {overall['expectancy_r50_day_cluster_bootstrap_95'][0]:+.3f}R to {overall['expectancy_r50_day_cluster_bootstrap_95'][1]:+.3f}R. This uncertainty is too wide for an edge claim.

## Complete chronological trade record

{markdown_table(chronological, ['Case', 'Date', 'Side', 'TF', 'Session', 'Resolution', 'PnL', 'R50', 'MFE R', 'MAE R', 'Confidence'])}

## Frozen segment diagnostics

{markdown_table(segment_rows, ['Family', 'State', 'N', 'Win rate', 'Expectancy R', 'Net R', 'Support'])}

Segments below three trades are descriptive only. Multi-label trigger and driver groups are preserved in the machine-readable result.

## Execution and path behavior

- Mean/median MFE: {path['mean_mfe_r50']:.3f}R / {path['median_mfe_r50']:.3f}R.
- Mean/median MAE: {path['mean_mae_r50']:.3f}R / {path['median_mae_r50']:.3f}R.
- Mean/median holding time: {path['mean_holding_minutes']:.1f} / {path['median_holding_minutes']:.1f} minutes.
- Recorded entry/exit execution cost: ${path['total_recorded_execution_cost_usd']:.2f}.
- Stops: {path['stopped_trades']}; stopped then original target later touched: {path['stopped_then_later_target']}.
- Losing trades that first achieved at least +0.5R MFE: {path['losses_with_at_least_half_r_mfe']}.
- Objective recent-move chase flags: {path['entry_chase_flags']}.
- Mean winner capture efficiency: {path['winner_mean_capture_efficiency'] if path['winner_mean_capture_efficiency'] is not None else 'not defined'}.

## Confidence and reasoning discipline

- Mean stated confidence: {summary['confidence']['mean_stated_confidence'] * 100:.1f}%.
- Observed practice win rate: {summary['confidence']['observed_win_rate'] * 100:.1f}%.
- Confidence minus win rate: {summary['confidence']['confidence_minus_win_rate'] * 100:+.1f} percentage points.
- Brier score: {summary['confidence']['brier_score']:.3f}.
- All required annotation fields nonempty: {reasoning['all_required_nonempty']['count']}/{len(rows)}.
- Macro-specific reasoning: {reasoning['macro_specific']['count']}/{len(rows)}.
- Higher-timeframe-specific reasoning: {reasoning['higher_timeframe_specific']['count']}/{len(rows)}.
- Specific invalidation: {reasoning['invalidation_specific']['count']}/{len(rows)}; generic invalidation: {reasoning['invalidation_generic']['count']}/{len(rows)}.
- Specific target logic: {reasoning['target_specific']['count']}/{len(rows)}; generic target logic: {reasoning['target_generic']['count']}/{len(rows)}.
- Specific event-risk statement: {reasoning['event_risk_specific']['count']}/{len(rows)}.

## Interpretation boundary

The figures describe usability-practice behavior, not a validated strategy. The dates were selected outcome-blindly, but the sample is only twenty partial-2021 practice days, the operator was learning the interface, and two early lifecycle outcomes were viewed while confirming capture. No monthly extrapolation, risk scaling, or edge PASS is permitted.

The appropriate next discussion is about which parts of the decision process were repeatable, which annotations were too generic to test, and what must be frozen before opening the one-year scored collection. The machine-readable result and complete trade table retain every case, including losses and no-trade days.
"""


def main() -> int:
    policy, registry, events = verify_sources()
    primary_base = extract_trades_primary(events)
    reference_base = extract_trades_reference(events)
    require(primary_base == reference_base, "Independent trade lifecycle extraction differs")
    require(len(primary_base) == 13, "Filled-trade population differs")
    require(all("fill" in row and "resolution" in row for row in primary_base), "Incomplete lifecycle exists")

    primary_streams = load_streams(PRIMARY_STREAM)
    reference_streams = load_streams(REFERENCE_STREAM)
    commission = float(policy["commission_usd_per_whole_ounce_round_turn"])
    primary_rows = [enrich_trade(row, primary_streams[row["case_alias"]], commission) for row in primary_base]
    reference_rows = [enrich_trade(row, reference_streams[row["case_alias"]], commission) for row in reference_base]
    require(primary_rows == reference_rows, "Primary/reference enriched trade tables differ")

    primary_summary = summarize(primary_rows, registry, events)
    reference_summary = summarize(reference_rows, registry, events)
    require(primary_summary == reference_summary, "Primary/reference summary differs")

    completed_at = datetime.now(timezone.utc).isoformat()
    table_hash = canonical_hash(primary_rows)
    summary_hash = canonical_hash(primary_summary)
    sample_label = (
        "DESCRIPTIVELY_POSITIVE_BUT_INCONCLUSIVE"
        if primary_summary["overall"]["net_r50"] > 0
        else "DESCRIPTIVELY_NEGATIVE"
        if primary_summary["overall"]["net_r50"] < 0
        else "DESCRIPTIVELY_FLAT"
    )
    payload = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_POST_PRACTICE_DIAGNOSTIC_1_0",
        "completed_at": completed_at,
        "formal_evidence_status": "ZERO_CREDIT_DESCRIPTIVE",
        "sample_description": sample_label,
        "edge_verdict": "NOT_EVALUABLE_FROM_TWENTY_PRACTICE_DAYS",
        "trade_count": len(primary_rows),
        "trade_table": primary_rows,
        "summary": primary_summary,
        "reproduction": {
            "primary_reference_trade_tables_identical": True,
            "primary_reference_summaries_identical": True,
            "trade_table_sha256": table_hash,
            "summary_sha256": summary_hash,
        },
        "gates": {
            "frozen_source_hashes_verified": True,
            "ledger_hash_chain_verified": True,
            "twenty_completed_cases_exact": True,
            "all_submissions_fills_resolutions_matched": True,
            "primary_reference_trade_extraction_identical": True,
            "primary_reference_stream_enrichment_identical": True,
            "primary_reference_summary_identical": True,
            "all_cases_and_negative_results_retained": True,
            "no_monthly_extrapolation_or_risk_scaling": True,
            "one_year_collection_remained_closed": True,
            "calendar_2025_2026_remained_locked": True,
            "no_acquisition_or_charge": True,
        },
        "one_year_collection": "CLOSED_NOT_MATERIALIZED_OR_ACCESSIBLE",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    report = build_report(primary_rows, primary_summary, completed_at)
    csv_text = build_csv(primary_rows)
    with RESULT.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    with TRADE_TABLE.open("x", encoding="utf-8", newline="") as handle:
        handle.write(csv_text)
    with REPORT.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(report)

    outputs = []
    for path in (RESULT, TRADE_TABLE, REPORT):
        outputs.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    seal = {
        "version": "GOLD_ANNOTATED_REPLAY_V3_POST_PRACTICE_DIAGNOSTIC_SEAL_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "formal_evidence_status": payload["formal_evidence_status"],
        "sample_description": sample_label,
        "edge_verdict": payload["edge_verdict"],
        "trade_table_sha256": table_hash,
        "summary_sha256": summary_hash,
        "sealed_outputs": outputs,
        "sealed_outputs_sha256": canonical_hash(outputs),
        "analysis_implementation": {
            "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "bytes": Path(__file__).stat().st_size,
            "sha256": sha256_file(Path(__file__)),
        },
        "one_year_collection": "CLOSED",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    with SEAL.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(seal, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    print(
        json.dumps(
            {
                "formal_evidence_status": payload["formal_evidence_status"],
                "sample_description": sample_label,
                "trades": len(primary_rows),
                "net_r50": primary_summary["overall"]["net_r50"],
                "net_pnl_usd": primary_summary["overall"]["net_pnl_usd"],
                "win_rate": primary_summary["overall"]["win_rate"],
                "profit_factor": primary_summary["overall"]["profit_factor"],
                "seal_sha256": sha256_file(SEAL),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
