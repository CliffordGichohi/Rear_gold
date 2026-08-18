from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_gc_session_state_transition_v1 as prior  # noqa: E402
import run_gold_fundamental_aligned_multitimeframe_auction_edge_v1 as famae  # noqa: E402


MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_structural_trend_retracement_continuation_v1_v01"
CONTRACT = ROOT / "GOLD_STRUCTURAL_TREND_RETRACEMENT_CONTINUATION_EDGE_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_structural_trend_retracement_continuation_v1_protocol.json"
TEST_REGISTRY = MANIFESTS / "gold_structural_trend_retracement_continuation_v1_test_registry.json"
DESIGN_FREEZE = MANIFESTS / "gold_structural_trend_retracement_continuation_v1_design_freeze.json"
AMENDMENT_A = MANIFESTS / "gold_structural_trend_retracement_continuation_v1_design_amendment_a.json"
PREOUTCOME_FREEZE = MANIFESTS / "gold_structural_trend_retracement_continuation_v1_preoutcome_freeze.json"

SETUPS = (
    "STRC_BREAK_LEVEL_RETEST_REJECTION",
    "STRC_IMPULSE_ZONE_INTERNAL_BOS",
    "STRC_ASIA_SWEEP_CONTINUATION",
)
SESSIONS = famae.SESSIONS
SCALE = famae.SCALE


SIGNAL_SCHEMA = pa.schema([
    pa.field("signal_id", pa.string(), False), pa.field("case_id", pa.string(), False),
    pa.field("session_date", pa.string(), False), pa.field("session_code", pa.string(), False),
    pa.field("iso_week", pa.string(), False), pa.field("setup_id", pa.string(), False),
    pa.field("direction", pa.string(), False), pa.field("touch_at_utc", pa.string(), False),
    pa.field("signal_at_utc", pa.string(), False), pa.field("fundamental_score", pa.float64(), False),
    pa.field("fundamental_confidence", pa.float64(), False), pa.field("fundamental_coverage", pa.float64(), False),
    pa.field("h1_state_json", pa.string(), False), pa.field("h4_state_json", pa.string(), False),
    pa.field("zones_json", pa.string(), False), pa.field("target_levels_json", pa.string(), False),
    pa.field("sequence_low_e8", pa.int64(), False), pa.field("sequence_high_e8", pa.int64(), False),
    pa.field("atr20_5m_e8", pa.int64(), False), pa.field("gc_covered", pa.bool_(), False),
    pa.field("gc_confirmed", pa.bool_(), True), pa.field("gc_event_ids_json", pa.string(), False),
    pa.field("context_hash", pa.string(), False), pa.field("lineage_hash", pa.string(), False),
])


@dataclass(frozen=True, slots=True)
class Swing:
    side: str
    pivot_index: int
    known_index: int
    price_e8: int
    pivot_at: datetime
    known_at: datetime
    evidence_hash: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(list(rows), schema=SIGNAL_SCHEMA)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6")
    temporary.replace(path)


def verify_design() -> dict[str, Any]:
    freeze = load_json(DESIGN_FREEZE)
    if freeze.get("status") != "SEALED_BEFORE_ANY_BRANCH_OUTCOME_ACCESS":
        raise ValueError("Design freeze invalid")
    for name, path in {"contract": CONTRACT, "protocol": PROTOCOL, "test_registry": TEST_REGISTRY}.items():
        if sha256_file(path) != freeze["controls"][name]["sha256"]:
            raise ValueError(f"Frozen control changed: {name}")
    amendment = load_json(AMENDMENT_A)
    if amendment.get("status") != "SEALED_BEFORE_MARKET_MATERIALIZATION_OR_OUTCOME_ACCESS":
        raise ValueError("Amendment A invalid")
    prior_seal = ROOT / freeze["sources"]["prior_branch_final_seal"]["path"]
    if sha256_file(prior_seal) != freeze["sources"]["prior_branch_final_seal"]["sha256"]:
        raise ValueError("Prior rejection seal changed")
    return freeze


def round_half_up(numerator: int, denominator: int) -> int:
    return int((Decimal(numerator) / Decimal(denominator)).to_integral_value(rounding=ROUND_HALF_UP))


def derive_swings(bars: Sequence[famae.HTFBar], implementation: str) -> list[Swing]:
    output: list[Swing] = []
    indices = range(2, len(bars) - 2) if implementation == "primary" else (known - 2 for known in range(4, len(bars)))
    for pivot in indices:
        known = pivot + 2
        current = bars[pivot]
        highs = [bars[index].high_e8 for index in range(pivot - 2, pivot + 3)]
        lows = [bars[index].low_e8 for index in range(pivot - 2, pivot + 3)]
        if current.high_e8 == max(highs) and highs.count(current.high_e8) == 1:
            output.append(Swing("UPPER", pivot, known, current.high_e8, current.close_at, bars[known].close_at, canonical_hash(["UPPER", current.evidence_hash, bars[known].evidence_hash])))
        if current.low_e8 == min(lows) and lows.count(current.low_e8) == 1:
            output.append(Swing("LOWER", pivot, known, current.low_e8, current.close_at, bars[known].close_at, canonical_hash(["LOWER", current.evidence_hash, bars[known].evidence_hash])))
    return sorted(output, key=lambda item: (item.known_index, item.side, item.pivot_index))


def atr_series(bars: Sequence[famae.HTFBar]) -> list[int | None]:
    true_ranges = [None]
    for index in range(1, len(bars)):
        true_ranges.append(famae.true_range_htf(bars[index], bars[index - 1]))
    output: list[int | None] = [None] * len(bars)
    for index in range(14, len(bars)):
        output[index] = round_half_up(sum(int(value) for value in true_ranges[index - 13:index + 1]), 14)
    return output


def directional_displacement(bar: famae.HTFBar, atr: int | None, direction: str) -> bool:
    if atr is None or atr <= 0 or bar.high_e8 <= bar.low_e8:
        return False
    body = bar.close_e8 - bar.open_e8
    width = bar.high_e8 - bar.low_e8
    if direction == "UP":
        return body > 0 and body >= 0.50 * width and bar.close_e8 >= bar.low_e8 + (2.0 / 3.0) * width and width >= atr
    return body < 0 and -body >= 0.50 * width and bar.close_e8 <= bar.low_e8 + (1.0 / 3.0) * width and width >= atr


def neutral_state(timeframe: str, at: datetime, atr: int | None, reason: str) -> dict[str, Any]:
    return {
        "timeframe": timeframe, "direction": "NEUTRAL", "as_of": iso_z(at),
        "confirmed_at": None, "breakout_e8": None, "protected_e8": None,
        "impulse_e8": None, "impulse_at": None, "atr14_e8": atr,
        "reason": reason, "state_hash": canonical_hash([timeframe, iso_z(at), "NEUTRAL", reason, atr]),
    }


def build_state_timeline(bars: Sequence[famae.HTFBar], implementation: str, timeframe: str) -> tuple[list[dict[str, Any]], list[Swing]]:
    swings = derive_swings(bars, implementation)
    by_known: dict[int, list[Swing]] = defaultdict(list)
    for swing in swings:
        by_known[swing.known_index].append(swing)
    atrs = atr_series(bars)
    latest_high: Swing | None = None
    latest_low: Swing | None = None
    known_highs: list[Swing] = []
    known_lows: list[Swing] = []
    up_arm: dict[str, Any] | None = None
    down_arm: dict[str, Any] | None = None
    active: dict[str, Any] | None = None
    timeline: list[dict[str, Any]] = []

    for index, bar in enumerate(bars):
        newly_known = by_known.get(index, [])
        if implementation == "primary":
            for swing in newly_known:
                if swing.side == "UPPER":
                    latest_high = swing
                    known_highs.append(swing)
                else:
                    latest_low = swing
                    known_lows.append(swing)
        else:
            known_highs.extend(item for item in newly_known if item.side == "UPPER")
            known_lows.extend(item for item in newly_known if item.side == "LOWER")
            latest_high = known_highs[-1] if known_highs else None
            latest_low = known_lows[-1] if known_lows else None

        if active is not None and bar.close_at - active["impulse_at_dt"] > timedelta(days=15):
            active = None
        if active is not None:
            if active["direction"] == "UP" and bar.close_e8 < active["protected_e8"]:
                active = None
            elif active["direction"] == "DOWN" and bar.close_e8 > active["protected_e8"]:
                active = None
        if active is not None:
            for swing in newly_known:
                if active["direction"] == "UP" and swing.side == "LOWER" and active["protected_e8"] < swing.price_e8 < active["impulse_e8"]:
                    active["protected_e8"] = swing.price_e8
                    active["protected_hash"] = swing.evidence_hash
                elif active["direction"] == "DOWN" and swing.side == "UPPER" and active["impulse_e8"] < swing.price_e8 < active["protected_e8"]:
                    active["protected_e8"] = swing.price_e8
                    active["protected_hash"] = swing.evidence_hash
            if active["direction"] == "UP" and bar.high_e8 > active["impulse_e8"]:
                active["impulse_e8"] = bar.high_e8
                active["impulse_at_dt"] = bar.close_at
                active["impulse_hash"] = bar.evidence_hash
            elif active["direction"] == "DOWN" and bar.low_e8 < active["impulse_e8"]:
                active["impulse_e8"] = bar.low_e8
                active["impulse_at_dt"] = bar.close_at
                active["impulse_hash"] = bar.evidence_hash

        if up_arm is not None and index - up_arm["sweep_index"] > 12:
            up_arm = None
        if down_arm is not None and index - down_arm["sweep_index"] > 12:
            down_arm = None
        if latest_low is not None and latest_high is not None and bar.low_e8 < latest_low.price_e8 < bar.close_e8:
            up_arm = {"sweep_index": index, "sweep_level": latest_low.price_e8, "breakout": latest_high.price_e8, "sweep_hash": bar.evidence_hash, "reference_hash": latest_high.evidence_hash}
        if latest_high is not None and latest_low is not None and bar.high_e8 > latest_high.price_e8 > bar.close_e8:
            down_arm = {"sweep_index": index, "sweep_level": latest_high.price_e8, "breakout": latest_low.price_e8, "sweep_hash": bar.evidence_hash, "reference_hash": latest_low.evidence_hash}

        up_confirm = up_arm is not None and index > up_arm["sweep_index"] and bar.close_e8 > up_arm["breakout"] and directional_displacement(bar, atrs[index], "UP")
        down_confirm = down_arm is not None and index > down_arm["sweep_index"] and bar.close_e8 < down_arm["breakout"] and directional_displacement(bar, atrs[index], "DOWN")
        if up_confirm and down_confirm:
            active = None
            up_arm = down_arm = None
        elif up_confirm:
            start = int(up_arm["sweep_index"])
            active = {
                "direction": "UP", "confirmed_at_dt": bar.close_at, "breakout_e8": int(up_arm["breakout"]),
                "protected_e8": min(item.low_e8 for item in bars[start:index + 1]), "impulse_e8": max(item.high_e8 for item in bars[start:index + 1]),
                "impulse_at_dt": bar.close_at, "transition_hash": canonical_hash([up_arm, bar.evidence_hash]),
                "protected_hash": canonical_hash([item.evidence_hash for item in bars[start:index + 1]]), "impulse_hash": bar.evidence_hash,
            }
            up_arm = down_arm = None
        elif down_confirm:
            start = int(down_arm["sweep_index"])
            active = {
                "direction": "DOWN", "confirmed_at_dt": bar.close_at, "breakout_e8": int(down_arm["breakout"]),
                "protected_e8": max(item.high_e8 for item in bars[start:index + 1]), "impulse_e8": min(item.low_e8 for item in bars[start:index + 1]),
                "impulse_at_dt": bar.close_at, "transition_hash": canonical_hash([down_arm, bar.evidence_hash]),
                "protected_hash": canonical_hash([item.evidence_hash for item in bars[start:index + 1]]), "impulse_hash": bar.evidence_hash,
            }
            up_arm = down_arm = None

        if active is None:
            snapshot = neutral_state(timeframe, bar.close_at, atrs[index], "NO_ACTIVE_CONFIRMED_TRANSITION")
        else:
            payload = {
                "timeframe": timeframe, "direction": active["direction"], "as_of": iso_z(bar.close_at),
                "confirmed_at": iso_z(active["confirmed_at_dt"]), "breakout_e8": active["breakout_e8"],
                "protected_e8": active["protected_e8"], "impulse_e8": active["impulse_e8"],
                "impulse_at": iso_z(active["impulse_at_dt"]), "atr14_e8": atrs[index],
                "transition_hash": active["transition_hash"], "protected_hash": active["protected_hash"],
                "impulse_hash": active["impulse_hash"], "reason": "ACTIVE_CONFIRMED_STRUCTURE",
            }
            payload["state_hash"] = canonical_hash(payload)
            snapshot = payload
        timeline.append(snapshot)
    return timeline, swings


def snapshot_at(bars: Sequence[famae.HTFBar], timeline: Sequence[Mapping[str, Any]], decision: datetime) -> dict[str, Any]:
    closes = [item.close_at for item in bars]
    index = bisect.bisect_right(closes, decision) - 1
    if index < 0:
        return neutral_state("UNKNOWN", decision, None, "NO_COMPLETED_BAR")
    return dict(timeline[index])


def recent_target_swings(swings: Sequence[Swing], decision: datetime) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for side in ("UPPER", "LOWER"):
        values = [item for item in swings if item.side == side and item.known_at <= decision and decision - item.known_at <= timedelta(days=20)]
        for item in values[-4:]:
            selected.append({"level_id": f"H1_SWING::{item.side}::{iso_z(item.pivot_at)}", "side": item.side, "price_e8": item.price_e8, "known_at": iso_z(item.known_at), "evidence_hash": item.evidence_hash})
    return selected


def candle_qualifies(bar: prior.FiveBar, atr: int, direction: str, body_fraction: float, range_atr: float | None, outer: float) -> bool:
    width = bar.high_e8 - bar.low_e8
    if width <= 0 or atr <= 0 or (range_atr is not None and width < range_atr * atr):
        return False
    body = bar.close_e8 - bar.open_e8
    if direction == "UP":
        return body > 0 and body >= body_fraction * width and bar.close_e8 >= bar.high_e8 - outer * width
    return body < 0 and -body >= body_fraction * width and bar.close_e8 <= bar.low_e8 + outer * width


def zones_for_state(state: Mapping[str, Any]) -> dict[str, Any] | None:
    if state["direction"] not in {"UP", "DOWN"} or state.get("atr14_e8") is None:
        return None
    protected, impulse, breakout, atr = int(state["protected_e8"]), int(state["impulse_e8"]), int(state["breakout_e8"]), int(state["atr14_e8"])
    width = abs(impulse - protected)
    if width <= 0:
        return None
    half = round_half_up(15 * atr, 100)
    if state["direction"] == "UP":
        retrace_low, retrace_high = impulse - round_half_up(786 * width, 1000), impulse - round_half_up(382 * width, 1000)
    else:
        retrace_low, retrace_high = impulse + round_half_up(382 * width, 1000), impulse + round_half_up(786 * width, 1000)
    return {
        "break_zone_low_e8": breakout - half, "break_zone_high_e8": breakout + half,
        "impulse_zone_low_e8": min(retrace_low, retrace_high), "impulse_zone_high_e8": max(retrace_low, retrace_high),
        "protected_e8": protected, "impulse_e8": impulse, "breakout_e8": breakout,
    }


def invalidated(bar: prior.FiveBar, state: Mapping[str, Any]) -> bool:
    return bar.close_e8 < int(state["protected_e8"]) if state["direction"] == "UP" else bar.close_e8 > int(state["protected_e8"])


def detect_signals(context: famae.Context, bars: Mapping[datetime, prior.Bar], state: Mapping[str, Any], zones: Mapping[str, Any], implementation: str) -> list[dict[str, Any]]:
    start, end = context.session_open, context.session_open + timedelta(hours=3)
    five = prior.five_minute_bars(bars, start - timedelta(minutes=110), end)
    scan_indices = [index for index, item in enumerate(five) if start <= item.open_at and item.close_at <= end]
    direction = str(state["direction"])
    output: list[dict[str, Any]] = []

    break_touch: int | None = None
    for index in scan_indices:
        bar = five[index]
        overlap = bar.high_e8 >= int(zones["break_zone_low_e8"]) and bar.low_e8 <= int(zones["break_zone_high_e8"])
        if break_touch is None and overlap:
            break_touch = index
        if break_touch is None:
            continue
        if invalidated(bar, state):
            break
        atr = prior.atr_at(five, bar.close_at)
        if atr is not None and candle_qualifies(bar, atr, direction, 0.50, 0.80, 1.0 / 3.0):
            output.append({"setup": SETUPS[0], "touch": five[break_touch].open_at, "decision": bar.close_at, "members": five[break_touch:index + 1], "atr": atr})
            break

    impulse_touch: int | None = None
    for index in scan_indices:
        bar = five[index]
        overlap = bar.high_e8 >= int(zones["impulse_zone_low_e8"]) and bar.low_e8 <= int(zones["impulse_zone_high_e8"])
        if overlap and index >= 3:
            impulse_touch = index
            break
    if impulse_touch is not None:
        preceding = five[impulse_touch - 3:impulse_touch]
        threshold = max(item.high_e8 for item in preceding) if direction == "UP" else min(item.low_e8 for item in preceding)
        candidate_indices = range(impulse_touch + 1, min(len(five), impulse_touch + 7))
        if implementation == "reference":
            candidate_indices = iter(list(candidate_indices))
        for index in candidate_indices:
            bar = five[index]
            if bar.open_at < start or bar.close_at > end or invalidated(bar, state):
                if invalidated(bar, state):
                    break
                continue
            atr = prior.atr_at(five, bar.close_at)
            broke = bar.close_e8 > threshold if direction == "UP" else bar.close_e8 < threshold
            if atr is not None and broke and candle_qualifies(bar, atr, direction, 0.40, None, 0.40):
                output.append({"setup": SETUPS[1], "touch": five[impulse_touch].open_at, "decision": bar.close_at, "members": five[impulse_touch:index + 1], "atr": atr})
                break

    asia_key = "ASIA_LOW" if direction == "UP" else "ASIA_HIGH"
    asia = context.prior_context.levels.get(asia_key)
    if asia is not None:
        for index in scan_indices:
            bar = five[index]
            swept = bar.low_e8 < asia < bar.close_e8 if direction == "UP" else bar.high_e8 > asia > bar.close_e8
            if not swept or invalidated(bar, state):
                continue
            atr = prior.atr_at(five, bar.close_at)
            if atr is not None and candle_qualifies(bar, atr, direction, 0.40, None, 1.0 / 3.0):
                output.append({"setup": SETUPS[2], "touch": bar.open_at, "decision": bar.close_at, "members": [bar], "atr": atr})
                break
    return sorted(output, key=lambda item: (item["decision"], item["setup"]))


def target_levels(context: famae.Context, state: Mapping[str, Any], swings: Sequence[Swing]) -> list[dict[str, Any]]:
    output = recent_target_swings(swings, context.session_open)
    for key, price in sorted(context.prior_context.levels.items()):
        if key not in {"ASIA_HIGH", "ASIA_LOW", "PRIOR_DAY_HIGH", "PRIOR_DAY_LOW"}:
            continue
        output.append({"level_id": key, "side": "UPPER" if key.endswith("HIGH") else "LOWER", "price_e8": int(price), "known_at": iso_z(context.session_open), "evidence_hash": context.record_hash})
    output.append({"level_id": "ACTIVE_IMPULSE_EXTREME", "side": "UPPER" if state["direction"] == "UP" else "LOWER", "price_e8": int(state["impulse_e8"]), "known_at": str(state["impulse_at"]), "evidence_hash": str(state["impulse_hash"])})
    unique: dict[tuple[str, int], dict[str, Any]] = {}
    for item in output:
        unique.setdefault((str(item["side"]), int(item["price_e8"])), item)
    return sorted(unique.values(), key=lambda item: (item["side"], item["price_e8"], item["level_id"]))


def materialize_impl(
    implementation: str, contexts: Sequence[famae.Context], h1_bars: Sequence[famae.HTFBar], h4_bars: Sequence[famae.HTFBar],
    h1_timeline: Sequence[Mapping[str, Any]], h4_timeline: Sequence[Mapping[str, Any]], h1_swings: Sequence[Swing],
    bars_by_key: Mapping[tuple[str, str], Mapping[datetime, prior.Bar]], gc_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context_map = {(item.session_date, item.session_code): item for item in contexts}
    gc_by_key, covered = famae.gc_events(gc_path, context_map)
    rows: list[dict[str, Any]] = []
    counts = defaultdict(int)
    for context in contexts:
        if context.direction not in {"UP", "DOWN"}:
            continue
        counts["macro_directional"] += 1
        h1 = snapshot_at(h1_bars, h1_timeline, context.session_open)
        h4 = snapshot_at(h4_bars, h4_timeline, context.session_open)
        if h1["direction"] != context.direction:
            continue
        counts["h1_aligned"] += 1
        opposed = "DOWN" if context.direction == "UP" else "UP"
        if h4["direction"] == opposed:
            counts["h4_vetoed"] += 1
            continue
        zones = zones_for_state(h1)
        if zones is None:
            continue
        levels = target_levels(context, h1, h1_swings)
        key = (context.session_date, context.session_code)
        for item in detect_signals(context, bars_by_key[key], h1, zones, implementation):
            decision = item["decision"]
            matches = [event for event in gc_by_key.get(key, []) if event["direction"] == context.direction and decision - timedelta(minutes=5) <= event["decision"] <= decision]
            identity = {"case_id": context.case_id, "setup": item["setup"], "direction": context.direction, "touch": iso_z(item["touch"]), "decision": iso_z(decision), "state_hash": h1["state_hash"], "member_hashes": [member.evidence_hash for member in item["members"]]}
            signal_id = f"STRC::{canonical_hash(identity)[:24]}"
            lineage = canonical_hash({**identity, "context_hash": context.prior_context.context_hash, "h4": h4, "zones": zones, "targets": levels, "gc": sorted(event["source_event_id"] for event in matches)})
            rows.append({
                "signal_id": signal_id, "case_id": context.case_id, "session_date": context.session_date,
                "session_code": context.session_code, "iso_week": context.iso_week, "setup_id": item["setup"],
                "direction": context.direction, "touch_at_utc": iso_z(item["touch"]), "signal_at_utc": iso_z(decision),
                "fundamental_score": context.score, "fundamental_confidence": context.confidence, "fundamental_coverage": context.coverage,
                "h1_state_json": canonical_json(h1), "h4_state_json": canonical_json(h4), "zones_json": canonical_json(zones),
                "target_levels_json": canonical_json(levels), "sequence_low_e8": min(member.low_e8 for member in item["members"]),
                "sequence_high_e8": max(member.high_e8 for member in item["members"]), "atr20_5m_e8": int(item["atr"]),
                "gc_covered": key in covered, "gc_confirmed": bool(matches) if key in covered else None,
                "gc_event_ids_json": canonical_json(sorted(event["source_event_id"] for event in matches)),
                "context_hash": context.prior_context.context_hash, "lineage_hash": lineage,
            })
    rows.sort(key=lambda row: (row["session_date"], row["session_code"], row["signal_at_utc"], row["setup_id"], row["signal_id"]))
    return rows, {
        "implementation": implementation, **dict(sorted(counts.items())), "signals": len(rows),
        "by_session": {session: sum(row["session_code"] == session for row in rows) for session in SESSIONS},
        "by_test": {f"{session}|{setup}": sum(row["session_code"] == session and row["setup_id"] == setup for row in rows) for session in SESSIONS for setup in SETUPS},
        "directions": {direction: sum(row["direction"] == direction for row in rows) for direction in ("UP", "DOWN")},
        "gc_covered": sum(row["gc_covered"] for row in rows), "gc_confirmed": sum(row["gc_confirmed"] is True for row in rows),
        "rows_hash": canonical_hash(rows), "outcomes_accessed": False,
    }


def materialize() -> dict[str, Any]:
    design = verify_design()
    if PREOUTCOME_FREEZE.exists() or (OUTPUT / "primary_signals.parquet").exists():
        raise FileExistsError("STRC materialization already exists")
    contexts, context_diag = famae.load_contexts()
    htf, htf_diag = famae.load_high_timeframes()
    primary_h1, primary_swings = build_state_timeline(htf["H1"], "primary", "H1")
    reference_h1, reference_swings = build_state_timeline(htf["H1"], "reference", "H1")
    primary_h4, primary_h4_swings = build_state_timeline(htf["H4"], "primary", "H4")
    reference_h4, reference_h4_swings = build_state_timeline(htf["H4"], "reference", "H4")
    if primary_h1 != reference_h1 or primary_h4 != reference_h4 or primary_swings != reference_swings or primary_h4_swings != reference_h4_swings:
        raise ValueError("Independent structural-state implementations disagree")
    bars_by_key, bar_diag = prior.load_preoutcome_bars([item.prior_context for item in contexts])
    primary, primary_diag = materialize_impl("primary", contexts, htf["H1"], htf["H4"], primary_h1, primary_h4, primary_swings, bars_by_key, famae.GC_PRIMARY)
    reference, reference_diag = materialize_impl("reference", contexts, htf["H1"], htf["H4"], reference_h1, reference_h4, reference_swings, bars_by_key, famae.GC_REFERENCE)
    if primary != reference:
        left, right = {row["signal_id"]: row for row in primary}, {row["signal_id"]: row for row in reference}
        mismatch = {"only_primary": sorted(set(left) - set(right))[:20], "only_reference": sorted(set(right) - set(left))[:20], "shared_different": [key for key in sorted(set(left) & set(right)) if left[key] != right[key]][:20]}
        write_json_exclusive(OUTPUT / "materialization_mismatch.json", mismatch)
        raise ValueError(mismatch)
    write_parquet_exclusive(OUTPUT / "primary_signals.parquet", primary)
    write_parquet_exclusive(OUTPUT / "reference_signals.parquet", reference)
    if sha256_file(OUTPUT / "primary_signals.parquet") != sha256_file(OUTPUT / "reference_signals.parquet"):
        raise ValueError("Signal Parquet outputs differ")
    certification = {
        "version": "GOLD_STRC_V1_PREOUTCOME_CERTIFICATION_1_0",
        "status": "PASS_OUTCOME_BLIND_MATERIALIZATION" if primary else "PASS_OUTCOME_BLIND_MATERIALIZATION_ZERO_SIGNALS",
        "completed_at_utc": utc_now(), "design_freeze": file_record(DESIGN_FREEZE), "amendment_a": file_record(AMENDMENT_A),
        "context_diagnostics": context_diag, "htf_diagnostics": htf_diag, "bar_diagnostics": bar_diag,
        "structure_counts": {"h1_bars": len(htf["H1"]), "h1_swings": len(primary_swings), "h4_bars": len(htf["H4"]), "h4_swings": len(primary_h4_swings)},
        "primary_diagnostics": primary_diag, "reference_diagnostics": reference_diag,
        "primary_signals": file_record(OUTPUT / "primary_signals.parquet"), "reference_signals": file_record(OUTPUT / "reference_signals.parquet"),
        "exact_reproduction": True, "development_outcomes_accessed": False, "forward_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(OUTPUT / "materialization_certification.json", certification)
    freeze = {
        "version": "GOLD_STRC_V1_PREOUTCOME_FREEZE_1_0", "status": "SEALED_EXACT_SIGNAL_POPULATION_BEFORE_OUTCOMES",
        "sealed_at_utc": utc_now(), "design_rules_hash": design["rules_hash"],
        "controls": {"contract": file_record(CONTRACT), "protocol": file_record(PROTOCOL), "test_registry": file_record(TEST_REGISTRY), "design_freeze": file_record(DESIGN_FREEZE), "amendment_a": file_record(AMENDMENT_A)},
        "implementation": file_record(Path(__file__).resolve()), "certification": file_record(OUTPUT / "materialization_certification.json"),
        "primary_signals": file_record(OUTPUT / "primary_signals.parquet"), "reference_signals": file_record(OUTPUT / "reference_signals.parquet"),
        "signal_count": len(primary), "signal_rows_hash": canonical_hash(primary),
        "development_outcomes_accessed": False, "forward_values_accessed": False, "paid_acquisition_authorized": False,
    }
    write_json_exclusive(PREOUTCOME_FREEZE, freeze)
    return certification


def selftest() -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    highs = [10, 11, 14, 12, 11, 13, 12]
    lows = [8, 7, 9, 8, 6, 8, 7]
    bars = [famae.HTFBar("H1", now + timedelta(hours=i), now + timedelta(hours=i + 1), 9 * SCALE, highs[i] * SCALE, lows[i] * SCALE, 10 * SCALE, str(i)) for i in range(len(highs))]
    first, second = derive_swings(bars, "primary"), derive_swings(bars, "reference")
    if first != second or not first:
        raise AssertionError((first, second))
    if not candle_qualifies(prior.FiveBar(now, now + timedelta(minutes=5), 100, 120, 95, 118, "x"), 20, "UP", 0.5, 0.8, 1 / 3):
        raise AssertionError("Candle predicate failed")
    print(json.dumps({"status": "PASS_SELFTEST", "swings": len(first), "checksum": canonical_hash([item.evidence_hash for item in first])}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("selftest", "materialize"))
    args = parser.parse_args()
    if args.phase == "selftest":
        selftest()
    else:
        print(json.dumps(materialize(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
