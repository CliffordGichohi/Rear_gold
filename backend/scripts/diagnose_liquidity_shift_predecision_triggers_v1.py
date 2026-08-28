from __future__ import annotations

import argparse
import asyncio
import bisect
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from calibrate_liquidity_shift_v2_matched_replay import (
    EXPECTED_CASES,
    EXPECTED_HUMAN_TRADES,
    aggregate_study_inputs,
    canonical_hash,
    iso,
    load_minutes,
    parse_time,
    read_json,
    read_jsonl,
    sha256_file,
    verify_chain,
    write_csv_exclusive,
    write_json_exclusive,
)
from calibrate_persistent_liquidity_shift_v3 import active_session
from calibrate_persistent_liquidity_shift_v3_correction_a import (
    corrected_intent_available_at,
)

from gold_intel.analytics.liquidity_shift_v2 import (
    Direction,
    LiquidityPivotV2,
    LiquidityShiftStudyV2,
    LiquidityShiftV2Config,
    build_liquidity_shift_study_v2,
    latest_swing_range_at,
    trend_state_at,
)
from gold_intel.analytics.liquidity_shift_v3 import (
    PersistentLiquidityShiftStudyV3,
    PersistentLiquidityShiftV3Config,
    build_persistent_liquidity_shift_study_v3,
)
from gold_intel.analytics.structure import AggregateBar

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


def verify_diagnostic_freeze(root: Path) -> dict[str, Any]:
    path = (
        root
        / "research_manifests"
        / "gold_liquidity_shift_predecision_trigger_diagnostic_v1_freeze.json"
    )
    freeze = read_json(path)
    if freeze.get("status") != "SEALED_BEFORE_PREDECISION_VALUE_ACCESS":
        raise RuntimeError("Pre-decision diagnostic freeze is invalid")
    for record in freeze["files"].values():
        source = root / record["path"]
        if sha256_file(source) != record["sha256"]:
            raise RuntimeError(f"Frozen diagnostic input changed: {record['path']}")
    if freeze.get("outcomes_opened") is not False:
        raise RuntimeError("Diagnostic freeze records outcome access")
    return freeze


def canonical_bars(values: Sequence[AggregateBar]) -> list[AggregateBar]:
    output: dict[datetime, AggregateBar] = {}
    for bar in sorted(values, key=lambda item: (item.open_time, item.close_time)):
        output[bar.open_time.astimezone(UTC)] = bar
    return sorted(output.values(), key=lambda item: item.open_time)


def true_range(bars: Sequence[AggregateBar], index: int) -> float:
    bar = bars[index]
    if index == 0:
        return max(bar.high - bar.low, 0.01)
    previous = bars[index - 1].close
    return max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous), 0.01)


def rolling_atr(bars: Sequence[AggregateBar], window: int = 14) -> list[float]:
    values = [true_range(bars, index) for index in range(len(bars))]
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    output: list[float] = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        output.append((prefix[index + 1] - prefix[start]) / (index - start + 1))
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
            aligned = bar.close > bar.open if direction == "BULLISH" else bar.close < bar.open
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


def last_at_or_before[T](values: Sequence[T], times: Sequence[datetime], cutoff: datetime) -> T | None:
    index = bisect.bisect_right(times, cutoff) - 1
    return values[index] if index >= 0 else None


def completed_bars(
    bars: Sequence[AggregateBar], closes: Sequence[datetime], cutoff: datetime
) -> Sequence[AggregateBar]:
    return bars[: bisect.bisect_right(closes, cutoff)]


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
    observed = completed_bars(bars, closes, decision_at)
    prefix = f"{timeframe}_"
    if not observed:
        return {prefix + "available": False}
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
        range_position = (bar.close - swing_range[0]) / (swing_range[1] - swing_range[0])
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
        for left, right in zip(recent, recent[1:], strict=False)
    )
    efficiency = (
        abs(recent[-1].close - recent[0].close) / path if path > 0 and len(recent) > 1 else None
    )
    signs = [
        1 if item.close > item.open else -1 if item.close < item.open else 0
        for item in observed[-6:]
    ]
    alternations = sum(
        left != 0 and right != 0 and left != right
        for left, right in zip(signs, signs[1:], strict=False)
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
    bullish_reclaim = bool(
        latest_low is not None
        and bar.low < latest_low.level
        and bar.close > latest_low.level
    )
    bearish_reclaim = bool(
        latest_high is not None
        and bar.high > latest_high.level
        and bar.close < latest_high.level
    )
    output: dict[str, Any] = {
        prefix + "available": True,
        prefix + "last_close_at": iso(bar.close_time),
        prefix + "close": round(bar.close, 8),
        prefix + "atr14": round(atr, 8),
        prefix + "candle_direction": (
            "BULLISH" if bar.close > bar.open else "BEARISH" if bar.close < bar.open else "DOJI"
        ),
        prefix + "body_ratio": round(body_ratio, 8),
        prefix + "true_range_atr": round(true_range(observed, index) / atr, 8),
        prefix + "trend": trend_state_at(known, decision_at),
        prefix + "swing_range_position": (
            round(range_position, 8) if range_position is not None else None
        ),
        prefix + "latest_high_age_minutes": (
            round((decision_at - latest_high.detected_at).total_seconds() / 60, 4)
            if latest_high
            else None
        ),
        prefix + "latest_low_age_minutes": (
            round((decision_at - latest_low.detected_at).total_seconds() / 60, 4)
            if latest_low
            else None
        ),
        prefix + "close_below_latest_high_atr": (
            round((latest_high.level - bar.close) / atr, 8) if latest_high else None
        ),
        prefix + "close_above_latest_low_atr": (
            round((bar.close - latest_low.level) / atr, 8) if latest_low else None
        ),
        prefix + "return_1_atr": round(returns[1], 8) if returns[1] is not None else None,
        prefix + "return_3_atr": round(returns[3], 8) if returns[3] is not None else None,
        prefix + "return_6_atr": round(returns[6], 8) if returns[6] is not None else None,
        prefix + "efficiency_6": round(efficiency, 8) if efficiency is not None else None,
        prefix + "alternations_6": alternations,
        prefix + "bullish_sweep_reclaim": bullish_reclaim,
        prefix + "bearish_sweep_reclaim": bearish_reclaim,
    }
    for direction, event in latest_breaks.items():
        label = direction.lower()
        output[prefix + label + "_break_age_minutes"] = (
            round((decision_at - event.detected_at).total_seconds() / 60, 4)
            if event
            else None
        )
        output[prefix + label + "_break_margin_atr"] = (
            round(event.margin_atr, 8) if event else None
        )
        output[prefix + label + "_break_range_atr"] = (
            round(event.range_atr, 8) if event else None
        )
        output[prefix + label + "_break_body_ratio"] = (
            round(event.body_ratio, 8) if event else None
        )
    return output


def chain_features(
    *,
    v2: LiquidityShiftStudyV2,
    v3: PersistentLiquidityShiftStudyV3,
    decision_at: datetime,
    direction: Direction,
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
    available_intents = []
    for intent in v3.entry_intents:
        if intent.direction != direction:
            continue
        matched, state, available_at = corrected_intent_available_at(intent, v3, decision_at)
        if matched:
            available_intents.append((intent, state, available_at))
    return {
        "latest_zone_contact_age_minutes": (
            round((decision_at - contacts[-1].contact_at).total_seconds() / 60, 4)
            if contacts
            else None
        ),
        "latest_m15_transition_age_minutes": (
            round((decision_at - transitions[-1].transition_at).total_seconds() / 60, 4)
            if transitions
            else None
        ),
        "active_v3_state_count": len(active_states),
        "latest_active_state_age_minutes": (
            round((decision_at - active_states[-1].started_at).total_seconds() / 60, 4)
            if active_states
            else None
        ),
        "latest_active_m5_impulse_age_minutes": (
            round((decision_at - impulses[-1].detected_at).total_seconds() / 60, 4)
            if impulses
            else None
        ),
        "corrected_available_v3_intents": len(available_intents),
    }


def build_rows(
    inputs: Mapping[str, Sequence[AggregateBar]],
    v2: LiquidityShiftStudyV2,
    v3: PersistentLiquidityShiftStudyV3,
    decisions: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    bars = {key: canonical_bars(value) for key, value in inputs.items()}
    closes = {
        key: [item.close_time.astimezone(UTC) for item in value]
        for key, value in bars.items()
    }
    atrs = {key: rolling_atr(value) for key, value in bars.items()}
    breaks = {
        key: causal_breaks(bars[key], v2.pivots[key], atrs[key])
        for key in ("5m", "15m", "1h", "4h")
    }
    rows: list[dict[str, Any]] = []
    for source in decisions:
        decision = source["data"]["decision"]
        decision_at = parse_time(decision["expected_cursor_at"])
        session, remaining = active_session(decision_at)
        action = decision["action"]
        row: dict[str, Any] = {
            "case_alias": source["case_alias"],
            "action": action,
            "decision_at": iso(decision_at),
            "session": session or "SESSION_TERMINAL_OR_OUTSIDE",
            "minutes_to_session_close": round(remaining, 4),
            "human_entry": decision.get("entry"),
            "human_stop": decision.get("stop"),
            "human_target": decision.get("target"),
        }
        for timeframe in ("5m", "15m", "1h", "4h"):
            row.update(
                timeframe_features(
                    timeframe=timeframe,
                    bars=bars[timeframe],
                    closes=closes[timeframe],
                    atrs=atrs[timeframe],
                    pivots=v2.pivots[timeframe],
                    breaks=breaks[timeframe],
                    decision_at=decision_at,
                )
            )
        if action in {"LONG", "SHORT"}:
            direction: Direction = "BULLISH" if action == "LONG" else "BEARISH"
            row.update(
                chain_features(v2=v2, v3=v3, decision_at=decision_at, direction=direction)
            )
            atr = float(row["5m_atr14"])
            current = float(row["5m_close"])
            entry = float(decision["entry"])
            stop = float(decision["stop"])
            target = float(decision["target"])
            row.update(
                {
                    "human_entry_minus_visible_close_m5_atr": round(
                        (entry - current) / atr, 8
                    ),
                    "human_stop_distance_m5_atr": round(abs(entry - stop) / atr, 8),
                    "human_target_distance_m5_atr": round(abs(target - entry) / atr, 8),
                }
            )
        rows.append(row)
    return rows


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    trades = [row for row in rows if row["action"] in {"LONG", "SHORT"}]
    def distribution(field: str) -> dict[str, Any]:
        values = sorted(float(row[field]) for row in trades if row.get(field) is not None)
        if not values:
            return {"support": 0}
        middle = len(values) // 2
        median = (
            values[middle]
            if len(values) % 2
            else (values[middle - 1] + values[middle]) / 2
        )
        return {
            "support": len(values),
            "minimum": round(values[0], 8),
            "median": round(median, 8),
            "maximum": round(values[-1], 8),
        }
    return {
        "decisions": len(rows),
        "trades": len(trades),
        "no_trades": len(rows) - len(trades),
        "actions": dict(Counter(row["action"] for row in rows)),
        "trade_m5_trends": dict(Counter(row.get("5m_trend") for row in trades)),
        "trade_m15_trends": dict(Counter(row.get("15m_trend") for row in trades)),
        "trade_h1_trends": dict(Counter(row.get("1h_trend") for row in trades)),
        "trade_h4_trends": dict(Counter(row.get("4h_trend") for row in trades)),
        "active_v3_state_at_trade": sum(row["active_v3_state_count"] > 0 for row in trades),
        "corrected_v3_entry_at_trade": sum(
            row["corrected_available_v3_intents"] > 0 for row in trades
        ),
        "distributions": {
            field: distribution(field)
            for field in (
                "5m_bullish_break_age_minutes",
                "5m_return_1_atr",
                "5m_return_3_atr",
                "5m_return_6_atr",
                "5m_efficiency_6",
                "5m_swing_range_position",
                "latest_zone_contact_age_minutes",
                "latest_m15_transition_age_minutes",
                "human_entry_minus_visible_close_m5_atr",
                "human_stop_distance_m5_atr",
                "human_target_distance_m5_atr",
            )
        },
    }


async def run(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    freeze = verify_diagnostic_freeze(root)
    ledger_path = (
        root
        / "research_artifacts"
        / "gold_matched_human_replay_v1"
        / "ledgers"
        / "matched_human_visible_ledger.jsonl"
    )
    ledger = read_jsonl(ledger_path)
    head = verify_chain(ledger)
    decisions = [
        row
        for row in ledger
        if row.get("event_type") in {"DECISION_SEALED", "NO_TRADE_SEALED"}
    ]
    if len(decisions) != EXPECTED_CASES:
        raise RuntimeError(f"Expected {EXPECTED_CASES} decisions, found {len(decisions)}")
    if sum(row["event_type"] == "DECISION_SEALED" for row in decisions) != EXPECTED_HUMAN_TRADES:
        raise RuntimeError("Human-trade population changed")
    minutes, source = await load_minutes()
    inputs = aggregate_study_inputs(minutes)
    v2_config = LiquidityShiftV2Config(maximum_stop_m15_atr=6.5)
    v3_config = PersistentLiquidityShiftV3Config()
    primary_v2 = build_liquidity_shift_study_v2(inputs, config=v2_config)
    primary_v3 = build_persistent_liquidity_shift_study_v3(inputs, config=v3_config)
    primary_rows = build_rows(inputs, primary_v2, primary_v3, decisions)
    reversed_inputs = {key: list(reversed(value)) for key, value in inputs.items()}
    reference_v2 = build_liquidity_shift_study_v2(reversed_inputs, config=v2_config)
    reference_v3 = build_persistent_liquidity_shift_study_v3(
        reversed_inputs, config=v3_config
    )
    reference_rows = build_rows(
        reversed_inputs, reference_v2, reference_v3, decisions
    )
    primary_hash = canonical_hash(primary_rows)
    reference_hash = canonical_hash(reference_rows)
    if primary_hash != reference_hash:
        raise RuntimeError("Pre-decision diagnostic reproduction mismatch")
    result = {
        "version": "GOLD_LIQUIDITY_SHIFT_PREDECISION_TRIGGER_DIAGNOSTIC_V1_RESULT_1_0",
        "status": "PASS_OUTCOME_BLIND_DIAGNOSTIC_REPRODUCTION",
        "freeze_sha256": sha256_file(
            root
            / "research_manifests"
            / "gold_liquidity_shift_predecision_trigger_diagnostic_v1_freeze.json"
        ),
        "freeze_status": freeze["status"],
        "human_visible_ledger_head_sha256": head,
        "source": source,
        "summary": summarize(primary_rows),
        "reproduction": {
            "primary_sha256": primary_hash,
            "reference_sha256": reference_hash,
            "identical": True,
        },
        "postdecision_market_values_opened": False,
        "outcomes_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    return result, primary_rows


async def run_and_dispose(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from gold_intel.infrastructure.database import engine

    try:
        return await run(root)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/workspace"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "diagnostic.json"
    rows_path = output / "predecision_rows.csv"
    seal_path = output / "seal.json"
    if any(path.exists() for path in (result_path, rows_path, seal_path)):
        raise FileExistsError("Pre-decision diagnostic artifacts already exist")
    result, rows = asyncio.run(run_and_dispose(args.root.resolve()))
    write_json_exclusive(result_path, result)
    write_csv_exclusive(rows_path, rows)
    seal = {
        "version": "GOLD_LIQUIDITY_SHIFT_PREDECISION_TRIGGER_DIAGNOSTIC_V1_SEAL_1_0",
        "status": result["status"],
        "files": {
            result_path.name: {
                "bytes": result_path.stat().st_size,
                "sha256": sha256_file(result_path),
            },
            rows_path.name: {
                "bytes": rows_path.stat().st_size,
                "sha256": sha256_file(rows_path),
            },
        },
    }
    write_json_exclusive(seal_path, seal)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
