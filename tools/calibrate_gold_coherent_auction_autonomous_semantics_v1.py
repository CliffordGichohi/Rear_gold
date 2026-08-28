#!/usr/bin/env python3
"""Outcome-blind imitation of the operator's coherent-auction setup timing.

This calibration uses only certified pre-decision streams and the human visible
ledger.  It never imports the matched outcome comparison or post-decision path
artifacts.  The result has zero validation credit; its purpose is to determine
whether a deterministic transparent scanner can represent the operator's
already-exposed chart semantics before another month is opened.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
import bisect
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier, export_text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    event_lock_state,
    macro_state,
    parse_dt,
)
from gold_intel.analytics.liquidity_shift_v2 import (  # noqa: E402
    Direction,
    LiquidityPivotV2,
    LiquidityShiftV2Config,
    build_liquidity_shift_study_v2,
    latest_swing_range_at,
    trend_state_at,
)
from gold_intel.analytics.liquidity_shift_v3 import (  # noqa: E402
    PersistentLiquidityShiftV3Config,
    build_persistent_liquidity_shift_study_v3,
)
from gold_intel.analytics.structure import AggregateBar  # noqa: E402


ARTIFACT = ROOT / "research_artifacts" / "gold_matched_human_replay_v1"
STREAM_ROOT = (
    ROOT
    / "research_artifacts"
    / "gold_blind_codex_operator_replay_v1"
    / "private_streams_recovery_a"
)
CERTIFICATION = ARTIFACT / "stream_materialization_certification.json"
LEDGER = ARTIFACT / "ledgers" / "matched_human_visible_ledger.jsonl"
OUT = ROOT / "research_artifacts" / "gold_coherent_auction_autonomous_translation_v1"
ROWS = OUT / "semantic_checkpoint_rows.parquet"
RESULT = OUT / "semantic_calibration.json"

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
CHECKPOINT_MINUTES = 5
POSITIVE_WINDOW_MINUTES = 15
MAX_MATCH_ERROR_MINUTES = 45
RANDOM_SEED = 20220820
PivotKind = Literal["HIGH", "LOW"]


@dataclass(frozen=True, slots=True)
class CausalBreak:
    direction: Direction
    pivot_identity: str
    detected_at: datetime
    close: float
    margin_atr: float
    range_atr: float
    body_ratio: float


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


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def load_stream(path: Path, expected_hash: str) -> dict[str, Any]:
    if sha256_file(path) != expected_hash:
        raise RuntimeError(f"Certified stream changed: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    submitted = payload.pop("stream_sha256")
    if canonical_hash(payload) != submitted:
        raise RuntimeError(f"Stream payload hash changed: {path}")
    payload["stream_sha256"] = submitted
    return payload


def load_decisions() -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["event_type"] not in {"DECISION_SEALED", "NO_TRADE_SEALED"}:
            continue
        decision = row["data"]["decision"]
        decisions[decision["case_alias"]] = decision
    if len(decisions) != 30:
        raise RuntimeError("Matched-human decision population changed")
    if Counter(row["action"] for row in decisions.values()) != Counter(
        {"LONG": 16, "NO_TRADE": 14}
    ):
        raise RuntimeError("Matched-human action population changed")
    return decisions


def aggregate_bar(row: dict[str, Any]) -> AggregateBar:
    return AggregateBar(
        open_time=parse_dt(row["open_at"]),
        close_time=parse_dt(row["close_at"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]) if row.get("volume") is not None else None,
        complete=bool(row.get("complete")),
        source_ids=(str(row.get("bar_id") or row.get("source_record_id")),),
    )


def true_range(bars: Sequence[AggregateBar], index: int) -> float:
    bar = bars[index]
    if index == 0:
        return max(bar.high - bar.low, 0.01)
    previous = bars[index - 1].close
    return max(
        bar.high - bar.low,
        abs(bar.high - previous),
        abs(bar.low - previous),
        0.01,
    )


def rolling_atr(bars: Sequence[AggregateBar], window: int = 14) -> list[float]:
    values = [true_range(bars, index) for index in range(len(bars))]
    prefix_sum = [0.0]
    for value in values:
        prefix_sum.append(prefix_sum[-1] + value)
    output: list[float] = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        output.append(
            (prefix_sum[index + 1] - prefix_sum[start]) / (index - start + 1)
        )
    return output


def causal_breaks(
    bars: Sequence[AggregateBar],
    pivots: Sequence[LiquidityPivotV2],
    atrs: Sequence[float],
) -> list[CausalBreak]:
    available = sorted(pivots, key=lambda item: (item.detected_at, item.identity))
    pointer = 0
    latest: dict[PivotKind, LiquidityPivotV2] = {}
    used: set[tuple[Direction, str]] = set()
    output: list[CausalBreak] = []
    for index, bar in enumerate(bars):
        while pointer < len(available) and available[pointer].detected_at <= bar.open_time:
            pivot = available[pointer]
            current = latest.get(pivot.kind)
            if current is None or (pivot.pivot_at, pivot.detected_at) > (
                current.pivot_at,
                current.detected_at,
            ):
                latest[pivot.kind] = pivot
            pointer += 1
        atr = max(atrs[index], 0.01)
        bar_range = max(bar.high - bar.low, 0.01)
        for direction, kind in (("BULLISH", "HIGH"), ("BEARISH", "LOW")):
            pivot = latest.get(kind)
            if pivot is None or (direction, pivot.identity) in used:
                continue
            margin = (
                bar.close - pivot.level
                if direction == "BULLISH"
                else pivot.level - bar.close
            )
            if margin <= 0:
                continue
            aligned = (
                bar.close > bar.open
                if direction == "BULLISH"
                else bar.close < bar.open
            )
            output.append(
                CausalBreak(
                    direction=direction,
                    pivot_identity=pivot.identity,
                    detected_at=bar.close_time.astimezone(UTC),
                    close=bar.close,
                    margin_atr=margin / atr,
                    range_atr=true_range(bars, index) / atr,
                    body_ratio=(abs(bar.close - bar.open) / bar_range if aligned else 0.0),
                )
            )
            used.add((direction, pivot.identity))
    return output


def timeframe_features(
    *,
    timeframe: str,
    bars: Sequence[AggregateBar],
    closes: Sequence[datetime],
    atrs: Sequence[float],
    pivots: Sequence[LiquidityPivotV2],
    breaks: Sequence[CausalBreak],
    decision_at: datetime,
) -> dict[str, Any]:
    end = bisect.bisect_right(closes, decision_at)
    observed = bars[:end]
    prefix_name = f"{timeframe}_"
    if not observed:
        return {prefix_name + "available": False}
    index = len(observed) - 1
    bar = observed[-1]
    atr = max(atrs[index], 0.01)
    known = [item for item in pivots if item.detected_at <= decision_at]
    highs = sorted(
        (item for item in known if item.kind == "HIGH"),
        key=lambda item: (item.pivot_at, item.detected_at),
    )
    lows = sorted(
        (item for item in known if item.kind == "LOW"),
        key=lambda item: (item.pivot_at, item.detected_at),
    )
    latest_high = highs[-1] if highs else None
    latest_low = lows[-1] if lows else None
    swing_range = latest_swing_range_at(known, decision_at)
    range_position = None
    if swing_range is not None and swing_range[1] > swing_range[0]:
        range_position = (bar.close - swing_range[0]) / (
            swing_range[1] - swing_range[0]
        )
    returns: dict[int, float | None] = {}
    for length in (1, 3, 6):
        returns[length] = (
            (bar.close - observed[-1 - length].close) / atr
            if len(observed) > length
            else None
        )
    recent = list(observed[-7:])
    path = sum(
        abs(right.close - left.close)
        for left, right in zip(recent, recent[1:])
    )
    efficiency = (
        abs(recent[-1].close - recent[0].close) / path
        if path > 0 and len(recent) > 1
        else None
    )
    signs = [
        1 if item.close > item.open else -1 if item.close < item.open else 0
        for item in observed[-6:]
    ]
    alternations = sum(
        left != 0 and right != 0 and left != right
        for left, right in zip(signs, signs[1:])
    )
    latest_breaks: dict[Direction, CausalBreak | None] = {}
    for direction in ("BULLISH", "BEARISH"):
        eligible = [
            item
            for item in breaks
            if item.direction == direction and item.detected_at <= decision_at
        ]
        latest_breaks[direction] = eligible[-1] if eligible else None
    body_ratio = abs(bar.close - bar.open) / max(bar.high - bar.low, 0.01)
    output: dict[str, Any] = {
        prefix_name + "available": True,
        prefix_name + "candle_direction": (
            "BULLISH"
            if bar.close > bar.open
            else "BEARISH"
            if bar.close < bar.open
            else "DOJI"
        ),
        prefix_name + "body_ratio": round(body_ratio, 8),
        prefix_name + "true_range_atr": round(true_range(observed, index) / atr, 8),
        prefix_name + "trend": trend_state_at(known, decision_at),
        prefix_name + "swing_range_position": (
            round(range_position, 8) if range_position is not None else None
        ),
        prefix_name + "latest_high_age_minutes": (
            round((decision_at - latest_high.detected_at).total_seconds() / 60, 4)
            if latest_high
            else None
        ),
        prefix_name + "latest_low_age_minutes": (
            round((decision_at - latest_low.detected_at).total_seconds() / 60, 4)
            if latest_low
            else None
        ),
        prefix_name + "close_below_latest_high_atr": (
            round((latest_high.level - bar.close) / atr, 8) if latest_high else None
        ),
        prefix_name + "close_above_latest_low_atr": (
            round((bar.close - latest_low.level) / atr, 8) if latest_low else None
        ),
        prefix_name + "return_1_atr": (
            round(returns[1], 8) if returns[1] is not None else None
        ),
        prefix_name + "return_3_atr": (
            round(returns[3], 8) if returns[3] is not None else None
        ),
        prefix_name + "return_6_atr": (
            round(returns[6], 8) if returns[6] is not None else None
        ),
        prefix_name + "efficiency_6": (
            round(efficiency, 8) if efficiency is not None else None
        ),
        prefix_name + "alternations_6": alternations,
        prefix_name + "bullish_sweep_reclaim": bool(
            latest_low is not None
            and bar.low < latest_low.level
            and bar.close > latest_low.level
        ),
        prefix_name + "bearish_sweep_reclaim": bool(
            latest_high is not None
            and bar.high > latest_high.level
            and bar.close < latest_high.level
        ),
    }
    for direction, event in latest_breaks.items():
        label = direction.lower()
        output[prefix_name + label + "_break_age_minutes"] = (
            round((decision_at - event.detected_at).total_seconds() / 60, 4)
            if event
            else None
        )
        output[prefix_name + label + "_break_margin_atr"] = (
            round(event.margin_atr, 8) if event else None
        )
        output[prefix_name + label + "_break_range_atr"] = (
            round(event.range_atr, 8) if event else None
        )
        output[prefix_name + label + "_break_body_ratio"] = (
            round(event.body_ratio, 8) if event else None
        )
    return output


def chain_features(
    *, v2: Any, v3: Any, decision_at: datetime, direction: Direction
) -> dict[str, Any]:
    contacts = [
        item
        for item in v2.contacts
        if item.direction == direction and item.reaction_at <= decision_at
    ]
    transitions = [
        item
        for item in v2.transitions
        if item.direction == direction and item.transition_at <= decision_at
    ]
    active_states = [
        item
        for item in v3.states
        if item.direction == direction and item.started_at <= decision_at < item.terminal_at
    ]
    active_ids = {item.identity for item in active_states}
    impulses = [
        item
        for item in v3.impulses
        if item.direction == direction
        and item.state_identity in active_ids
        and item.detected_at <= decision_at
    ]
    return {
        "latest_zone_contact_age_minutes": (
            round((decision_at - contacts[-1].contact_at).total_seconds() / 60, 4)
            if contacts
            else None
        ),
        "latest_m15_transition_age_minutes": (
            round(
                (decision_at - transitions[-1].transition_at).total_seconds() / 60,
                4,
            )
            if transitions
            else None
        ),
        "active_v3_state_count": len(active_states),
        "latest_active_state_age_minutes": (
            round(
                (decision_at - active_states[-1].started_at).total_seconds() / 60,
                4,
            )
            if active_states
            else None
        ),
        "latest_active_m5_impulse_age_minutes": (
            round((decision_at - impulses[-1].detected_at).total_seconds() / 60, 4)
            if impulses
            else None
        ),
    }


def study_inputs(stream: dict[str, Any]) -> dict[str, list[AggregateBar]]:
    output: dict[str, list[AggregateBar]] = {}
    for timeframe in ("1m", "5m", "15m", "1h", "4h"):
        values: dict[datetime, AggregateBar] = {}
        for row in stream["timeframes"][timeframe]:
            bar = aggregate_bar(row)
            values[bar.open_time] = bar
        output[timeframe] = sorted(values.values(), key=lambda item: item.open_time)
    return output


def merged_study_inputs(streams: Iterable[dict[str, Any]]) -> dict[str, list[AggregateBar]]:
    merged: dict[str, dict[datetime, AggregateBar]] = {
        key: {} for key in ("1m", "5m", "15m", "1h", "4h")
    }
    for stream in streams:
        for timeframe, bars in study_inputs(stream).items():
            for bar in bars:
                prior = merged[timeframe].get(bar.open_time)
                if prior is not None and prior != bar:
                    raise RuntimeError(
                        f"Overlapping certified bar differs: {timeframe} {bar.open_time}"
                    )
                merged[timeframe][bar.open_time] = bar
    return {
        key: sorted(values.values(), key=lambda item: item.open_time)
        for key, values in merged.items()
    }


def prepare_study(inputs: dict[str, list[AggregateBar]]) -> dict[str, Any]:
    v2 = build_liquidity_shift_study_v2(
        inputs, config=LiquidityShiftV2Config(maximum_stop_m15_atr=6.5)
    )
    v3 = build_persistent_liquidity_shift_study_v3(
        inputs, config=PersistentLiquidityShiftV3Config()
    )
    closes = {
        key: [item.close_time.astimezone(UTC) for item in values]
        for key, values in inputs.items()
    }
    atrs = {key: rolling_atr(values) for key, values in inputs.items()}
    breaks = {
        key: causal_breaks(inputs[key], v2.pivots[key], atrs[key])
        for key in ("5m", "15m", "1h", "4h")
    }
    return {
        "inputs": inputs,
        "v2": v2,
        "v3": v3,
        "closes": closes,
        "atrs": atrs,
        "breaks": breaks,
    }


def checkpoints_for_day(calendar_date: date) -> list[tuple[str, datetime, float]]:
    result: list[tuple[str, datetime, float]] = []
    for session, timezone in (("LONDON", LONDON), ("NEW_YORK", NEW_YORK)):
        local_open = datetime(
            calendar_date.year,
            calendar_date.month,
            calendar_date.day,
            8,
            tzinfo=timezone,
        )
        for offset in range(0, 4 * 60, CHECKPOINT_MINUTES):
            timestamp = (local_open + timedelta(minutes=offset)).astimezone(UTC)
            result.append((session, timestamp, float(offset)))
    return sorted(result, key=lambda item: item[1])


def prefix(values: dict[str, Any], label: str) -> dict[str, Any]:
    return {f"{label}{key}": value for key, value in values.items()}


def snapshot_features(
    *,
    stream: dict[str, Any],
    inputs: dict[str, list[AggregateBar]],
    v2: Any,
    v3: Any,
    closes: dict[str, list[datetime]],
    atrs: dict[str, list[float]],
    breaks: dict[str, Any],
    timestamp: datetime,
    session: str,
    session_offset: float,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "checkpoint_at": iso(timestamp),
        "session": session,
        "session_offset_minutes": session_offset,
        "session_remaining_minutes": 240.0 - session_offset,
    }
    for timeframe in ("5m", "15m", "1h", "4h"):
        values = timeframe_features(
            timeframe=timeframe,
            bars=inputs[timeframe],
            closes=closes[timeframe],
            atrs=atrs[timeframe],
            pivots=v2.pivots[timeframe],
            breaks=breaks[timeframe],
            decision_at=timestamp,
        )
        # Absolute prices and their timestamps identify the historical case and
        # are unnecessary for a portable chart-semantic rule.
        for key in list(values):
            if key.endswith("_close") or key.endswith("_last_close_at"):
                values.pop(key)
        row.update(values)

    for direction, label in (("BULLISH", "bull_"), ("BEARISH", "bear_")):
        row.update(
            prefix(
                chain_features(
                    v2=v2, v3=v3, decision_at=timestamp, direction=direction
                ),
                label,
            )
        )

    for direction, label in (("LONG", "long_"), ("SHORT", "short_")):
        row.update(
            {
                f"{label}event_locked": event_lock_state(
                    stream, iso(timestamp), direction
                )["locked"],
                f"{label}macro_state": macro_state(
                    stream, iso(timestamp), direction
                )["state"],
            }
        )
    return row


def materialize_one(
    *, stream: dict[str, Any], decision: dict[str, Any], prepared: dict[str, Any]
) -> list[dict[str, Any]]:
    inputs = prepared["inputs"]
    v2 = prepared["v2"]
    v3 = prepared["v3"]
    closes = prepared["closes"]
    atrs = prepared["atrs"]
    breaks = prepared["breaks"]
    day = parse_dt(stream["start_inclusive"])
    calendar_date = date.fromisoformat(stream["trading_date_utc"])
    human_at = parse_dt(decision["expected_cursor_at"])
    action = decision["action"]
    rows: list[dict[str, Any]] = []
    for session, timestamp, offset in checkpoints_for_day(calendar_date):
        if timestamp < day or timestamp >= parse_dt(stream["end_exclusive"]):
            continue
        # After an operator trade the case was no longer available for another
        # first-decision signal.  This is an eligibility boundary, not an
        # outcome filter.
        if action != "NO_TRADE" and timestamp > human_at:
            continue
        feature = snapshot_features(
            stream=stream,
            inputs=inputs,
            v2=v2,
            v3=v3,
            closes=closes,
            atrs=atrs,
            breaks=breaks,
            timestamp=timestamp,
            session=session,
            session_offset=offset,
        )
        feature.update(
            {
                "case_alias": decision["case_alias"],
                "human_action": action,
                "human_decision_at": decision["expected_cursor_at"],
                "semantic_positive": bool(
                    action != "NO_TRADE"
                    and 0
                    <= (human_at - timestamp).total_seconds() / 60.0
                    <= POSITIVE_WINDOW_MINUTES
                ),
            }
        )
        rows.append(feature)
    return rows


def materialize() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    certification = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
    records = {row["case_alias"]: row for row in certification["case_files"]}
    decisions = load_decisions()
    primary_streams: dict[str, dict[str, Any]] = {}
    reference_streams: dict[str, dict[str, Any]] = {}
    source_records: list[dict[str, Any]] = []
    for alias in sorted(decisions):
        record = records[alias]
        primary_streams[alias] = load_stream(
            ROOT / record["primary"]["path"], record["primary"]["sha256"]
        )
        reference_streams[alias] = load_stream(
            ROOT / record["reference"]["path"], record["reference"]["sha256"]
        )
        source_records.append(
            {
                "case_alias": alias,
                "primary_sha256": record["primary"]["sha256"],
                "reference_sha256": record["reference"]["sha256"],
            }
        )

    primary_prepared = prepare_study(merged_study_inputs(primary_streams.values()))
    reference_prepared = prepare_study(
        merged_study_inputs(reference_streams.values())
    )
    primary_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    for source_record in source_records:
        alias = source_record["case_alias"]
        left = materialize_one(
            stream=primary_streams[alias],
            decision=decisions[alias],
            prepared=primary_prepared,
        )
        right = materialize_one(
            stream=reference_streams[alias],
            decision=decisions[alias],
            prepared=reference_prepared,
        )
        if canonical_hash(left) != canonical_hash(right):
            raise RuntimeError(f"Primary/reference semantic rows differ: {alias}")
        primary_rows.extend(left)
        reference_rows.extend(right)
        source_record["row_count"] = len(left)
        source_record["rows_sha256"] = canonical_hash(left)
    if canonical_hash(primary_rows) != canonical_hash(reference_rows):
        raise RuntimeError("Complete primary/reference semantic materialization differs")
    diagnostics = {
        "rows": len(primary_rows),
        "positive_rows": sum(row["semantic_positive"] for row in primary_rows),
        "cases": len(source_records),
        "source_records_sha256": canonical_hash(source_records),
        "primary_rows_sha256": canonical_hash(primary_rows),
        "reference_rows_sha256": canonical_hash(reference_rows),
        "primary_reference_identical": True,
    }
    return primary_rows, reference_rows, diagnostics


def model_matrix(rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, np.ndarray]:
    excluded = {
        "case_alias",
        "checkpoint_at",
        "human_action",
        "human_decision_at",
        "semantic_positive",
    }
    frame = pd.DataFrame([{k: v for k, v in row.items() if k not in excluded} for row in rows])
    bool_columns = [name for name in frame if frame[name].dtype == bool]
    for name in bool_columns:
        frame[name] = frame[name].astype(int)
    categorical = [
        name
        for name in frame
        if frame[name].dtype == object or isinstance(frame[name].dropna().iloc[0] if not frame[name].dropna().empty else None, str)
    ]
    numeric = [name for name in frame if name not in categorical]
    for name in numeric:
        values = pd.to_numeric(frame[name], errors="coerce")
        frame[f"{name}__missing"] = values.isna().astype(int)
        frame[name] = values.fillna(-999.0)
    frame = pd.get_dummies(frame, columns=categorical, prefix_sep="=")
    frame = frame.reindex(sorted(frame.columns), axis=1).astype(float)
    target = np.asarray([int(row["semantic_positive"]) for row in rows], dtype=int)
    return frame, target


def consecutive_signals(
    indexes: list[int], probabilities: np.ndarray, threshold: float, count: int
) -> list[int]:
    result: list[int] = []
    run: list[int] = []
    for index in indexes:
        if probabilities[index] >= threshold:
            run.append(index)
            if len(run) >= count:
                result.append(run[-1])
        else:
            run = []
    return result


def evaluate(
    *,
    rows: list[dict[str, Any]],
    probabilities: np.ndarray,
    threshold: float,
    consecutive: int,
) -> dict[str, Any]:
    by_case: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_case.setdefault(row["case_alias"], []).append(index)
    cases: list[dict[str, Any]] = []
    for alias in sorted(by_case):
        indexes = sorted(by_case[alias], key=lambda item: rows[item]["checkpoint_at"])
        signal_indexes = consecutive_signals(indexes, probabilities, threshold, consecutive)
        first = signal_indexes[0] if signal_indexes else None
        action = rows[indexes[0]]["human_action"]
        expected_at = parse_dt(rows[indexes[0]]["human_decision_at"])
        signal_at = parse_dt(rows[first]["checkpoint_at"]) if first is not None else None
        difference = (
            (expected_at - signal_at).total_seconds() / 60.0
            if signal_at is not None
            else None
        )
        matched = bool(
            action != "NO_TRADE"
            and difference is not None
            and 0 <= difference <= MAX_MATCH_ERROR_MINUTES
        )
        false_positive = bool(action == "NO_TRADE" and signal_at is not None)
        cases.append(
            {
                "case_alias": alias,
                "human_action": action,
                "human_decision_at": iso(expected_at),
                "scanner_signal_at": iso(signal_at) if signal_at else None,
                "checkpoint_difference_minutes": difference,
                "matched_trade": matched,
                "false_positive_no_trade": false_positive,
                "signal_probability": (
                    float(probabilities[first]) if first is not None else None
                ),
            }
        )
    trade_rows = [row for row in cases if row["human_action"] != "NO_TRADE"]
    no_trade_rows = [row for row in cases if row["human_action"] == "NO_TRADE"]
    errors = sorted(
        float(row["checkpoint_difference_minutes"])
        for row in trade_rows
        if row["matched_trade"]
    )
    median_error = float(np.median(errors)) if errors else math.inf
    maximum_error = max(errors) if errors else math.inf
    return {
        "trade_population": len(trade_rows),
        "matched_trades": sum(row["matched_trade"] for row in trade_rows),
        "no_trade_population": len(no_trade_rows),
        "false_positive_no_trade_days": sum(
            row["false_positive_no_trade"] for row in no_trade_rows
        ),
        "median_checkpoint_difference_minutes": median_error,
        "maximum_matched_checkpoint_difference_minutes": maximum_error,
        "cases": cases,
    }


def ranking_key(record: dict[str, Any]) -> tuple[Any, ...]:
    metrics = record["metrics"]
    passes = (
        metrics["matched_trades"] >= 14
        and metrics["false_positive_no_trade_days"] <= 2
        and metrics["median_checkpoint_difference_minutes"] <= 15
        and metrics["maximum_matched_checkpoint_difference_minutes"] <= 45
    )
    return (
        int(passes),
        metrics["matched_trades"],
        -metrics["false_positive_no_trade_days"],
        -metrics["median_checkpoint_difference_minutes"],
        -record["max_depth"],
        -record["max_leaf_nodes"],
        record["min_samples_leaf"],
        record["threshold"],
        -record["consecutive"],
    )


def calibrate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matrix, target = model_matrix(rows)
    positive_weight = max(1.0, (len(target) - target.sum()) / max(target.sum(), 1))
    candidates: list[dict[str, Any]] = []
    fitted: dict[str, DecisionTreeClassifier] = {}
    for depth in (3, 4, 5, 6):
        for leaves in (8, 12, 16, 24):
            for minimum_leaf in (2, 4, 8):
                model = DecisionTreeClassifier(
                    criterion="gini",
                    max_depth=depth,
                    max_leaf_nodes=leaves,
                    min_samples_leaf=minimum_leaf,
                    class_weight={0: 1.0, 1: positive_weight},
                    random_state=RANDOM_SEED,
                )
                model.fit(matrix, target)
                probabilities = model.predict_proba(matrix)[:, 1]
                model_key = f"d{depth}_l{leaves}_m{minimum_leaf}"
                fitted[model_key] = model
                for threshold in (0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
                    for consecutive in (1, 2, 3):
                        metrics = evaluate(
                            rows=rows,
                            probabilities=probabilities,
                            threshold=threshold,
                            consecutive=consecutive,
                        )
                        candidates.append(
                            {
                                "model_key": model_key,
                                "max_depth": depth,
                                "max_leaf_nodes": leaves,
                                "min_samples_leaf": minimum_leaf,
                                "threshold": threshold,
                                "consecutive": consecutive,
                                "metrics": metrics,
                            }
                        )
    selected = max(candidates, key=ranking_key)
    model = fitted[selected["model_key"]]
    selected["transparent_tree"] = export_text(
        model, feature_names=list(matrix.columns), decimals=8
    )
    selected["tree_node_count"] = int(model.tree_.node_count)
    selected["tree_depth"] = int(model.tree_.max_depth)
    selected["feature_names"] = list(matrix.columns)
    selected["feature_importances"] = {
        name: float(value)
        for name, value in sorted(
            zip(matrix.columns, model.feature_importances_, strict=True),
            key=lambda item: (-item[1], item[0]),
        )
        if value > 0
    }
    selected["positive_class_weight"] = positive_weight
    selected["bounded_search_count"] = len(candidates)
    selected["semantic_pass"] = bool(ranking_key(selected)[0])
    selected["matrix_sha256"] = canonical_hash(
        {
            "columns": list(matrix.columns),
            "values": matrix.to_numpy().tolist(),
            "target": target.tolist(),
        }
    )
    selected["candidate_registry_sha256"] = canonical_hash(
        [
            {
                key: value
                for key, value in candidate.items()
                if key != "metrics"
            }
            | {
                "metrics": {
                    key: value
                    for key, value in candidate["metrics"].items()
                    if key != "cases"
                }
            }
            for candidate in candidates
        ]
    )
    return selected


def normalize_for_parquet(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    return frame.reindex(sorted(frame.columns), axis=1)


def main() -> None:
    primary_rows, reference_rows, materialization = materialize()
    calibration = calibrate(primary_rows)
    result = {
        "version": "GOLD_COHERENT_AUCTION_AUTONOMOUS_TRANSLATION_V1_SEMANTIC_CALIBRATION_1_0",
        "status": (
            "PASS_AUTONOMOUS_SIGNAL_SEMANTICS"
            if calibration["semantic_pass"]
            else "FAIL_AUTONOMOUS_SIGNAL_SEMANTICS"
        ),
        "evidence_status": "EXPOSED_OUTCOME_BLIND_SEMANTIC_CALIBRATION_ZERO_VALIDATION_CREDIT",
        "population": "CBR-2022-001_THROUGH_CBR-2022-030",
        "materialization": materialization,
        "calibration": calibration,
        "outcomes_opened": False,
        "postdecision_paths_opened": False,
        "fresh_block_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "geometry_gate_run": False,
        "economic_gate_run": False,
    }
    result["payload_sha256"] = canonical_hash(
        {key: value for key, value in result.items() if key != "payload_sha256"}
    )
    OUT.mkdir(parents=True, exist_ok=True)
    normalize_for_parquet(primary_rows).to_parquet(ROWS, index=False)
    RESULT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "rows": materialization["rows"],
                "positive_rows": materialization["positive_rows"],
                "model": calibration["model_key"],
                "threshold": calibration["threshold"],
                "consecutive": calibration["consecutive"],
                **{
                    key: value
                    for key, value in calibration["metrics"].items()
                    if key != "cases"
                },
                "outcomes_opened": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
