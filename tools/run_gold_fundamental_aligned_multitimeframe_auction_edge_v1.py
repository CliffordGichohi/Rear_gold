from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_gc_session_state_transition_v1 as prior  # noqa: E402


ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_v02"
CONTRACT = ROOT / "GOLD_FUNDAMENTAL_ALIGNED_MULTITIMEFRAME_AUCTION_EDGE_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_protocol.json"
TRACEABILITY = MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_traceability.json"
TEST_REGISTRY = MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_test_registry.json"
FREEZE = MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_preoutcome_freeze.json"
AMENDMENT_A = MANIFESTS / "gold_fundamental_aligned_multitimeframe_auction_edge_v1_preoutcome_amendment_a.json"
CASE_PATH = ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz"
PRICE_PATH = ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz"
GC_PRIMARY = ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/primary_events.parquet"
GC_REFERENCE = ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/reference_events.parquet"
GC_ROWS = MANIFESTS / "gc_session_trigger_edge_m2_row_registry_v01.json"

SCALE = 100_000_000
SESSIONS = ("LONDON", "NEW_YORK")
ZONES = {"LONDON": ZoneInfo("Europe/London"), "NEW_YORK": ZoneInfo("America/New_York")}
SETUPS = (
    "FAMAE_ALIGNED_SWEEP_RECLAIM",
    "FAMAE_ALIGNED_BREAK_RETEST",
    "FAMAE_ALIGNED_FAILED_ACCEPTANCE",
)
_CLOSE_CACHE: dict[int, list[datetime]] = {}
_PRESSURE_CACHE: dict[tuple[int, datetime], dict[str, Any]] = {}
ENGINEERING_DATES = {
    "2024-01-05", "2024-01-09", "2024-01-11",
    "2024-01-30", "2024-01-31", "2024-03-20",
}


SIGNAL_SCHEMA = pa.schema(
    [
        pa.field("signal_id", pa.string(), False),
        pa.field("case_id", pa.string(), False),
        pa.field("session_date", pa.string(), False),
        pa.field("session_code", pa.string(), False),
        pa.field("iso_week", pa.string(), False),
        pa.field("setup_id", pa.string(), False),
        pa.field("direction", pa.string(), False),
        pa.field("signal_at_utc", pa.string(), False),
        pa.field("fundamental_score", pa.float64(), False),
        pa.field("fundamental_confidence", pa.float64(), False),
        pa.field("fundamental_coverage", pa.float64(), False),
        pa.field("fundamental_direction", pa.string(), False),
        pa.field("htf_states_json", pa.string(), False),
        pa.field("htf_alignment", pa.bool_(), False),
        pa.field("trigger_level_ids_json", pa.string(), False),
        pa.field("known_levels_json", pa.string(), False),
        pa.field("trigger_low_e8", pa.int64(), False),
        pa.field("trigger_high_e8", pa.int64(), False),
        pa.field("atr20_5m_e8", pa.int64(), False),
        pa.field("gc_covered", pa.bool_(), False),
        pa.field("gc_confirmed", pa.bool_(), True),
        pa.field("gc_event_ids_json", pa.string(), False),
        pa.field("context_hash", pa.string(), False),
        pa.field("lineage_hash", pa.string(), False),
    ]
)


@dataclass(frozen=True, slots=True)
class Context:
    prior_context: prior.CaseContext
    score: float
    confidence: float
    coverage: float
    record_hash: str

    @property
    def session_date(self) -> str:
        return self.prior_context.session_date

    @property
    def session_code(self) -> str:
        return self.prior_context.session_code

    @property
    def session_open(self) -> datetime:
        return self.prior_context.session_open

    @property
    def case_id(self) -> str:
        return self.prior_context.case_id

    @property
    def iso_week(self) -> str:
        return self.prior_context.iso_week

    @property
    def direction(self) -> str:
        if self.coverage < 50.0 or self.confidence < 35.0:
            return "NEUTRAL_OR_UNKNOWN"
        if self.score >= 20.0:
            return "UP"
        if self.score <= -20.0:
            return "DOWN"
        return "NEUTRAL_OR_UNKNOWN"


@dataclass(frozen=True, slots=True)
class HTFBar:
    timeframe: str
    open_at: datetime
    close_at: datetime
    open_e8: int
    high_e8: int
    low_e8: int
    close_e8: int
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class Level:
    level_id: str
    family: str
    side: str
    price_e8: int
    known_at: datetime
    evidence_hash: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
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
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


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


def write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(list(rows), schema=schema)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        table, temporary, compression="zstd", use_dictionary=False,
        write_statistics=True, data_page_version="1.0", version="2.6",
        row_group_size=65_536,
    )
    temporary.replace(path)


def verify_freeze() -> dict[str, Any]:
    freeze = load_json(FREEZE)
    if freeze.get("status") != "SEALED_BEFORE_NEW_BRANCH_OUTCOME_COMPUTATION":
        raise ValueError("Pre-outcome freeze is not valid")
    paths = {
        "contract": CONTRACT,
        "protocol": PROTOCOL,
        "traceability": TRACEABILITY,
        "test_registry": TEST_REGISTRY,
    }
    for name, path in paths.items():
        if sha256_file(path) != freeze["controls"][name]["sha256"]:
            raise ValueError(f"Frozen control changed: {name}")
    for item in freeze["source_bindings"].values():
        path = ROOT / item["path"]
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"Frozen source binding changed: {item['path']}")
    return freeze


def fact_eligible(fact: Mapping[str, Any], decision: datetime) -> bool:
    if not fact or fact.get("epistemic_status") == "UNKNOWN" or fact.get("value") is None:
        return False
    available = fact.get("available_at")
    return (
        isinstance(available, str)
        and parse_dt(available) <= decision
        and fact.get("quality") not in {"MISSING", "NOT_LICENSED", "UNVERIFIED_AVAILABILITY"}
    )


def load_contexts() -> tuple[list[Context], dict[str, Any]]:
    contexts: list[Context] = []
    seen: set[tuple[str, str]] = set()
    rows_seen = verified = engineering = 0
    with gzip.open(CASE_PATH, "rb") as handle:
        for raw in handle:
            rows_seen += 1
            dm, sm = prior.DATE_RE.search(raw), prior.SESSION_RE.search(raw)
            if dm is None or sm is None:
                raise ValueError(f"Case identity missing at row {rows_seen}")
            session_date = dm.group(1).decode("ascii")
            session_code = sm.group(1).decode("ascii")
            if session_date > "2024-12-31":
                raise ValueError("Forward record entered development context")
            case = json.loads(raw)
            metadata = case["case_metadata"]
            if prior.case_record_hash(case) != metadata["record_hash"]:
                raise ValueError(f"Case hash failed: {session_date} {session_code}")
            verified += 1
            if session_date in ENGINEERING_DATES:
                engineering += 1
                continue
            key = (session_date, session_code)
            if key in seen:
                raise ValueError(f"Duplicate case: {key}")
            seen.add(key)
            decision = parse_dt(str(metadata["decision_at"]))
            state = case["decision_state"]
            levels: dict[str, int] = {}
            for item in state.get("levels", []):
                kind = str(item.get("level_type"))
                price = item.get("price") if isinstance(item.get("price"), Mapping) else {}
                if kind in {"ASIA_HIGH", "ASIA_LOW", "PRIOR_DAY_HIGH", "PRIOR_DAY_LOW"} and fact_eligible(price, decision):
                    levels[kind] = scaled(price["value"])
            regime = state["layers"]["market_regime"]["regime_state"]
            value = regime.get("value") if fact_eligible(regime, decision) and isinstance(regime.get("value"), Mapping) else {}
            score = float(value.get("directional_score", 0.0))
            confidence = float(value.get("confidence", 0.0))
            coverage = float(value.get("coverage", 0.0))
            macro = "BULLISH" if score >= 20 else "BEARISH" if score <= -20 else "NEUTRAL"
            iso = date.fromisoformat(session_date).isocalendar()
            payload = {
                "case_id": metadata["case_id"], "session_date": session_date,
                "session_code": session_code, "decision": iso_z(decision),
                "levels": levels, "score": score, "confidence": confidence,
                "coverage": coverage, "record_hash": metadata["record_hash"],
            }
            prior_context = prior.CaseContext(
                case_id=str(metadata["case_id"]), session_date=session_date,
                session_code=session_code, session_open=decision,
                iso_week=f"{iso.year}-W{iso.week:02d}", levels=levels,
                macro_state=macro, real_usd_state="NOT_USED_V1",
                structure_state="NOT_USED_V1", context_hash=canonical_hash(payload),
            )
            contexts.append(Context(prior_context, score, confidence, coverage, str(metadata["record_hash"])))
    contexts.sort(key=lambda item: (item.session_date, item.session_code))
    return contexts, {
        "rows_seen": rows_seen,
        "record_hashes_verified": verified,
        "engineering_rows_excluded": engineering,
        "research_rows": len(contexts),
        "london_rows": sum(item.session_code == "LONDON" for item in contexts),
        "new_york_rows": sum(item.session_code == "NEW_YORK" for item in contexts),
        "macro_bullish_rows": sum(item.direction == "UP" for item in contexts),
        "macro_bearish_rows": sum(item.direction == "DOWN" for item in contexts),
        "macro_neutral_or_unknown_rows": sum(item.direction == "NEUTRAL_OR_UNKNOWN" for item in contexts),
        "subsequent_behaviour_selected": False,
    }


def htf_bar_from_record(record: Mapping[str, Any]) -> HTFBar:
    ohlc = record["ohlc"]
    opened, closed = parse_dt(str(record["open_time"])), parse_dt(str(record["close_time"]))
    available = parse_dt(str(record["available_at"]))
    if available > closed:
        raise ValueError(f"Late HTF bar: {record['record_id']}")
    return HTFBar(
        timeframe=str(record["timeframe"]), open_at=opened, close_at=closed,
        open_e8=scaled(ohlc["open"]), high_e8=scaled(ohlc["high"]),
        low_e8=scaled(ohlc["low"]), close_e8=scaled(ohlc["close"]),
        evidence_hash=str(record["record_hash"]),
    )


def aggregate_weeks(daily: Sequence[HTFBar]) -> list[HTFBar]:
    groups: dict[tuple[int, int], list[HTFBar]] = defaultdict(list)
    for bar in daily:
        iso = bar.close_at.date().isocalendar()
        groups[(iso.year, iso.week)].append(bar)
    output: list[HTFBar] = []
    for key, values in sorted(groups.items()):
        values = sorted(values, key=lambda item: item.open_at)
        if len(values) < 4:
            continue
        output.append(HTFBar(
            timeframe="W1", open_at=values[0].open_at, close_at=values[-1].close_at,
            open_e8=values[0].open_e8, high_e8=max(item.high_e8 for item in values),
            low_e8=min(item.low_e8 for item in values), close_e8=values[-1].close_e8,
            evidence_hash=canonical_hash([key, [item.evidence_hash for item in values]]),
        ))
    return output


def load_high_timeframes() -> tuple[dict[str, list[HTFBar]], dict[str, Any]]:
    wanted = {"1h": "H1", "4h": "H4", "1d": "D1"}
    output: dict[str, list[HTFBar]] = {"H1": [], "H4": [], "D1": []}
    source_lines = selected = complete_true = component_incomplete = 0
    with gzip.open(PRICE_PATH, "rt", encoding="utf-8") as handle:
        for line in handle:
            source_lines += 1
            if not any(f'"timeframe":"{name}"' in line for name in wanted):
                continue
            record = json.loads(line)
            if record.get("instrument_code") != "XAUUSD":
                continue
            raw_tf = str(record.get("timeframe"))
            if raw_tf not in wanted:
                continue
            bar = htf_bar_from_record(record)
            if record.get("complete") is True:
                complete_true += 1
            else:
                component_incomplete += 1
            output[wanted[raw_tf]].append(HTFBar(
                timeframe=wanted[raw_tf], open_at=bar.open_at, close_at=bar.close_at,
                open_e8=bar.open_e8, high_e8=bar.high_e8, low_e8=bar.low_e8,
                close_e8=bar.close_e8, evidence_hash=bar.evidence_hash,
            ))
            selected += 1
    for values in output.values():
        values.sort(key=lambda item: item.close_at)
    output["W1"] = aggregate_weeks(output["D1"])
    return output, {
        "source_lines_scanned": source_lines,
        "selected_h1_h4_d1": selected,
        "component_complete_true": complete_true,
        "closed_periods_with_missing_wall_clock_components": component_incomplete,
        "component_completeness_is_not_candle_formation_status": True,
        "counts": {key: len(value) for key, value in output.items()},
        "outcome_fields_selected": False,
    }


def latest_index(values: Sequence[HTFBar], decision: datetime) -> int:
    key = id(values)
    closes = _CLOSE_CACHE.get(key)
    if closes is None:
        closes = [item.close_at for item in values]
        _CLOSE_CACHE[key] = closes
    return bisect.bisect_right(closes, decision) - 1


def true_range_htf(current: HTFBar, previous: HTFBar) -> int:
    return max(current.high_e8 - current.low_e8, abs(current.high_e8 - previous.close_e8), abs(current.low_e8 - previous.close_e8))


def pressure_state(values: Sequence[HTFBar], decision: datetime) -> dict[str, Any]:
    cache_key = (id(values), decision)
    cached = _PRESSURE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    index = latest_index(values, decision)
    if index < 14:
        result = {"state": "UNKNOWN", "displacement": False, "bar_hash": "UNKNOWN", "atr14_e8": None}
        _PRESSURE_CACHE[cache_key] = result
        return result
    bar = values[index]
    window = values[index - 14:index + 1]
    atr = int((Decimal(sum(true_range_htf(window[item], window[item - 1]) for item in range(1, 15))) / Decimal(14)).to_integral_value(rounding=ROUND_HALF_UP))
    width = bar.high_e8 - bar.low_e8
    body = bar.close_e8 - bar.open_e8
    if width <= 0 or atr <= 0:
        result = {"state": "UNKNOWN", "displacement": False, "bar_hash": bar.evidence_hash, "atr14_e8": atr}
        _PRESSURE_CACHE[cache_key] = result
        return result
    location_num = bar.close_e8 - bar.low_e8
    upper = 3 * location_num >= 2 * width
    lower = 3 * location_num <= width
    state = "BULLISH" if body > 0 and upper else "BEARISH" if body < 0 and lower else "NEUTRAL"
    displacement = (bar.high_e8 - bar.low_e8) >= atr and 2 * abs(body) >= width
    result = {
        "state": state, "displacement": displacement, "bar_hash": bar.evidence_hash,
        "atr14_e8": atr, "bar_close": iso_z(bar.close_at),
    }
    _PRESSURE_CACHE[cache_key] = result
    return result


def htf_alignment(htf: Mapping[str, Sequence[HTFBar]], decision: datetime, direction: str) -> tuple[bool, dict[str, Any]]:
    states = {name: pressure_state(htf[name], decision) for name in ("W1", "D1", "H4", "H1")}
    wanted = "BULLISH" if direction == "UP" else "BEARISH"
    opposed = "BEARISH" if direction == "UP" else "BULLISH"
    votes = sum(states[name]["state"] == wanted for name in ("W1", "D1", "H4"))
    strong_opposition = any(states[name]["state"] == opposed and states[name]["displacement"] for name in ("W1", "D1", "H4"))
    h1_opposition = states["H1"]["state"] == opposed and states["H1"]["displacement"]
    return votes >= 2 and not strong_opposition and not h1_opposition, states


def business_days_between(left: date, right: date) -> int:
    if right <= left:
        return 0
    return int(np.busday_count(left.isoformat(), right.isoformat()))


def h1_swings(values: Sequence[HTFBar], decision: datetime) -> list[Level]:
    known_index = latest_index(values, decision)
    highs: list[Level] = []
    lows: list[Level] = []
    # Ten calendar days safely contains every bar that can satisfy the frozen
    # five-business-day expiry, including a weekend and exchange closure.
    start = max(2, known_index - 24 * 10)
    for center in range(start, max(start, known_index - 1)):
        known_at = values[center + 2].close_at
        if known_at > decision:
            continue
        pivot = values[center]
        if business_days_between(pivot.close_at.date(), decision.date()) > 5:
            continue
        neighbours = [values[item] for item in (center - 2, center - 1, center + 1, center + 2)]
        if all(pivot.high_e8 > item.high_e8 for item in neighbours):
            highs.append(Level(
                f"H1_SWING_HIGH::{iso_z(pivot.close_at)}", "H1_CONFIRMED_SWING", "UPPER",
                pivot.high_e8, known_at, canonical_hash([pivot.evidence_hash, values[center + 1].evidence_hash, values[center + 2].evidence_hash]),
            ))
        if all(pivot.low_e8 < item.low_e8 for item in neighbours):
            lows.append(Level(
                f"H1_SWING_LOW::{iso_z(pivot.close_at)}", "H1_CONFIRMED_SWING", "LOWER",
                pivot.low_e8, known_at, canonical_hash([pivot.evidence_hash, values[center + 1].evidence_hash, values[center + 2].evidence_hash]),
            ))
    return sorted(highs, key=lambda item: item.known_at)[-2:] + sorted(lows, key=lambda item: item.known_at)[-2:]


def completed_bar(values: Sequence[HTFBar], decision: datetime) -> HTFBar | None:
    index = latest_index(values, decision)
    return values[index] if index >= 0 else None


def make_range_levels(family: str, upper: int, lower: int, known_at: datetime, evidence: Any) -> list[Level]:
    if upper <= lower:
        return []
    signature = canonical_hash(evidence)
    return [
        Level(f"{family}_HIGH::{iso_z(known_at)}", family, "UPPER", upper, known_at, canonical_hash([signature, "UPPER", upper])),
        Level(f"{family}_LOW::{iso_z(known_at)}", family, "LOWER", lower, known_at, canonical_hash([signature, "LOWER", lower])),
    ]


def base_levels(context: Context, htf: Mapping[str, Sequence[HTFBar]], bars: Mapping[datetime, prior.Bar]) -> list[Level]:
    decision = context.session_open
    levels: list[Level] = []
    raw = context.prior_context.levels
    if raw.get("ASIA_HIGH", 0) > raw.get("ASIA_LOW", 0):
        levels.extend(make_range_levels("ASIA_RANGE", raw["ASIA_HIGH"], raw["ASIA_LOW"], decision, [context.record_hash, "ASIA"]))
    daily = completed_bar(htf["D1"], decision)
    if daily is not None:
        levels.extend(make_range_levels("PRIOR_DAY_RANGE", daily.high_e8, daily.low_e8, daily.close_at, daily.evidence_hash))
    weekly = completed_bar(htf["W1"], decision)
    if weekly is not None:
        levels.extend(make_range_levels("PRIOR_WEEK_RANGE", weekly.high_e8, weekly.low_e8, weekly.close_at, weekly.evidence_hash))
    levels.extend(h1_swings(htf["H1"], decision))
    or_end = context.session_open + timedelta(minutes=15)
    opening = prior.contiguous_bars(bars, context.session_open, or_end)
    if opening:
        levels.extend(make_range_levels(
            "SESSION_OPENING_RANGE_15", max(item.high_e8 for item in opening),
            min(item.low_e8 for item in opening), or_end,
            [item.record_hash for item in opening],
        ))
    if context.session_code == "NEW_YORK":
        local_day = date.fromisoformat(context.session_date)
        london_open = datetime.combine(local_day, time(8, 0), tzinfo=ZONES["LONDON"]).astimezone(UTC)
        members = prior.contiguous_bars(bars, london_open, decision)
        if members:
            levels.extend(make_range_levels(
                "LONDON_PRE_NEW_YORK_RANGE", max(item.high_e8 for item in members),
                min(item.low_e8 for item in members), decision,
                [item.record_hash for item in members],
            ))
    unique: dict[tuple[str, str, int], Level] = {}
    for level in levels:
        unique.setdefault((level.family, level.side, level.price_e8), level)
    return sorted(unique.values(), key=lambda item: (item.side, item.price_e8, item.level_id))


def levels_at(base: Sequence[Level], context: Context, bars: Mapping[datetime, prior.Bar], decision: datetime) -> list[Level]:
    del context, bars
    return sorted(
        [item for item in base if item.known_at <= decision],
        key=lambda item: (item.side, item.price_e8, item.level_id),
    )


def raw_candidate(setup: str, direction: str, decision: datetime, members: Sequence[Any], levels: Sequence[Level]) -> dict[str, Any]:
    return {
        "setup": setup, "direction": direction, "decision": decision,
        "trigger_low_e8": min(int(item.low_e8) for item in members),
        "trigger_high_e8": max(int(item.high_e8) for item in members),
        "levels": tuple(sorted(levels, key=lambda item: item.level_id)),
        "trigger_hashes": tuple(str(item.evidence_hash if hasattr(item, "evidence_hash") else item.record_hash) for item in members),
    }


def detect_primary(context: Context, bars: Mapping[datetime, prior.Bar], htf: Mapping[str, Sequence[HTFBar]], base: Sequence[Level]) -> list[dict[str, Any]]:
    direction = context.direction
    if direction not in {"UP", "DOWN"}:
        return []
    scan_end = context.session_open + timedelta(minutes=150)
    minutes = [bars.get(context.session_open + timedelta(minutes=index)) for index in range(150)]
    minutes = [item for item in minutes if item is not None]
    five = prior.five_minute_bars(bars, context.session_open - timedelta(minutes=110), scan_end)
    candidates: list[dict[str, Any]] = []

    for index, current in enumerate(minutes):
        decision = current.close_at
        if decision > scan_end:
            break
        eligible = levels_at(base, context, bars, decision)
        side = "LOWER" if direction == "UP" else "UPPER"
        selected_levels: list[Level] = []
        previous = minutes[index - 1] if index else None
        for level in eligible:
            if level.side != side:
                continue
            if direction == "UP":
                same = current.low_e8 < level.price_e8 <= current.close_e8
                next_bar = previous is not None and previous.low_e8 < level.price_e8 and previous.close_e8 < level.price_e8 <= current.close_e8
            else:
                same = current.high_e8 > level.price_e8 >= current.close_e8
                next_bar = previous is not None and previous.high_e8 > level.price_e8 and previous.close_e8 > level.price_e8 >= current.close_e8
            if same or next_bar:
                selected_levels.append(level)
        if selected_levels:
            aligned, states = htf_alignment(htf, decision, direction)
            if not aligned:
                continue
            members = [current] if previous is None or not any(
                previous.low_e8 < level.price_e8 if direction == "UP" else previous.high_e8 > level.price_e8
                for level in selected_levels
            ) else [previous, current]
            item = raw_candidate(SETUPS[0], direction, decision, members, selected_levels)
            item["htf_states"] = states
            candidates.append(item)
            break

    expanded_levels = list(base)
    for level in expanded_levels:
        if (direction == "UP" and level.side != "LOWER") or (direction == "DOWN" and level.side != "UPPER"):
            continue
        for index in range(1, len(minutes)):
            first, second = minutes[index - 1], minutes[index]
            accepted = first.close_e8 < level.price_e8 and second.close_e8 < level.price_e8 if direction == "UP" else first.close_e8 > level.price_e8 and second.close_e8 > level.price_e8
            if not accepted or level.known_at > second.close_at:
                continue
            for offset in range(1, 6):
                if index + offset >= len(minutes):
                    break
                current = minutes[index + offset]
                returned = current.close_e8 >= level.price_e8 if direction == "UP" else current.close_e8 <= level.price_e8
                if returned:
                    aligned, states = htf_alignment(htf, current.close_at, direction)
                    if aligned:
                        item = raw_candidate(SETUPS[2], direction, current.close_at, minutes[index - 1:index + offset + 1], [level])
                        item["htf_states"] = states
                        candidates.append(item)
                    break
            if any(item["setup"] == SETUPS[2] and level in item["levels"] for item in candidates):
                break

    for level in expanded_levels:
        if (direction == "UP" and level.side != "UPPER") or (direction == "DOWN" and level.side != "LOWER"):
            continue
        eligible_five = [item for item in five if context.session_open <= item.close_at <= scan_end and level.known_at <= item.close_at]
        for index in range(1, len(eligible_five)):
            first, second = eligible_five[index - 1], eligible_five[index]
            accepted = first.close_e8 > level.price_e8 and second.close_e8 > level.price_e8 if direction == "UP" else first.close_e8 < level.price_e8 and second.close_e8 < level.price_e8
            if not accepted:
                continue
            for offset in range(1, 7):
                if index + offset >= len(eligible_five):
                    break
                current = eligible_five[index + offset]
                if direction == "UP":
                    failed = index + offset >= index + 2 and all(item.close_e8 <= level.price_e8 for item in eligible_five[index + offset - 1:index + offset + 1])
                    retest = current.low_e8 <= level.price_e8 < current.close_e8 and current.close_e8 > current.open_e8
                else:
                    failed = index + offset >= index + 2 and all(item.close_e8 >= level.price_e8 for item in eligible_five[index + offset - 1:index + offset + 1])
                    retest = current.high_e8 >= level.price_e8 > current.close_e8 and current.close_e8 < current.open_e8
                if failed:
                    break
                if retest:
                    aligned, states = htf_alignment(htf, current.close_at, direction)
                    if aligned:
                        item = raw_candidate(SETUPS[1], direction, current.close_at, eligible_five[index - 1:index + offset + 1], [level])
                        item["htf_states"] = states
                        candidates.append(item)
                    break
            if any(item["setup"] == SETUPS[1] and level in item["levels"] for item in candidates):
                break
    # Preserve every level participating at the earliest eligible decision for
    # a setup.  The reference implementation reaches the same result through
    # per-level enumeration rather than this state-oriented scan.
    output: list[dict[str, Any]] = []
    for setup in SETUPS:
        values = [item for item in candidates if item["setup"] == setup]
        if not values:
            continue
        first_time = min(item["decision"] for item in values)
        same = [item for item in values if item["decision"] == first_time]
        merged_levels = sorted(
            {level.level_id: level for item in same for level in item["levels"]}.values(),
            key=lambda item: item.level_id,
        )
        representative = dict(min(same, key=lambda item: [level.level_id for level in item["levels"]]))
        representative["levels"] = tuple(merged_levels)
        representative["trigger_low_e8"] = min(item["trigger_low_e8"] for item in same)
        representative["trigger_high_e8"] = max(item["trigger_high_e8"] for item in same)
        representative["trigger_hashes"] = tuple(sorted({value for item in same for value in item["trigger_hashes"]}))
        output.append(representative)
    return sorted(output, key=lambda item: (item["decision"], item["setup"]))


def detect_reference(context: Context, bars: Mapping[datetime, prior.Bar], htf: Mapping[str, Sequence[HTFBar]], base: Sequence[Level]) -> list[dict[str, Any]]:
    # Deliberately enumerate per level and use exhaustive slices rather than the
    # primary state-oriented ordering.
    direction = context.direction
    if direction not in {"UP", "DOWN"}:
        return []
    scan_end = context.session_open + timedelta(minutes=150)
    minutes = [bars.get(context.session_open + timedelta(minutes=index)) for index in range(150)]
    minutes = [item for item in minutes if item is not None]
    all_levels = levels_at(base, context, bars, context.session_open + timedelta(minutes=15))
    five = prior.five_minute_bars(bars, context.session_open - timedelta(minutes=110), scan_end)
    by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for level in all_levels:
        if level.side == ("LOWER" if direction == "UP" else "UPPER"):
            for index, current in enumerate(minutes):
                if level.known_at > current.close_at:
                    continue
                previous = minutes[index - 1] if index else None
                passed = (
                    current.low_e8 < level.price_e8 <= current.close_e8
                    or previous is not None and previous.low_e8 < level.price_e8 and previous.close_e8 < level.price_e8 <= current.close_e8
                ) if direction == "UP" else (
                    current.high_e8 > level.price_e8 >= current.close_e8
                    or previous is not None and previous.high_e8 > level.price_e8 and previous.close_e8 > level.price_e8 >= current.close_e8
                )
                if passed:
                    aligned, states = htf_alignment(htf, current.close_at, direction)
                    if aligned:
                        members = [previous, current] if previous is not None and (
                            previous.low_e8 < level.price_e8 if direction == "UP" else previous.high_e8 > level.price_e8
                        ) else [current]
                        item = raw_candidate(SETUPS[0], direction, current.close_at, members, [level])
                        item["htf_states"] = states
                        by_setup[SETUPS[0]].append(item)
                        break

            for accepted_at in range(1, len(minutes)):
                pair = minutes[accepted_at - 1:accepted_at + 1]
                if level.known_at > pair[-1].close_at:
                    continue
                accepted = all(item.close_e8 < level.price_e8 for item in pair) if direction == "UP" else all(item.close_e8 > level.price_e8 for item in pair)
                if not accepted:
                    continue
                returns = minutes[accepted_at + 1:min(len(minutes), accepted_at + 6)]
                match = next((item for item in returns if item.close_e8 >= level.price_e8), None) if direction == "UP" else next((item for item in returns if item.close_e8 <= level.price_e8), None)
                if match is not None:
                    end = minutes.index(match)
                    aligned, states = htf_alignment(htf, match.close_at, direction)
                    if aligned:
                        item = raw_candidate(SETUPS[2], direction, match.close_at, minutes[accepted_at - 1:end + 1], [level])
                        item["htf_states"] = states
                        by_setup[SETUPS[2]].append(item)
                        break

        if level.side == ("UPPER" if direction == "UP" else "LOWER"):
            eligible = [item for item in five if context.session_open <= item.close_at <= scan_end and level.known_at <= item.close_at]
            for accepted_at in range(1, len(eligible)):
                pair = eligible[accepted_at - 1:accepted_at + 1]
                accepted = all(item.close_e8 > level.price_e8 for item in pair) if direction == "UP" else all(item.close_e8 < level.price_e8 for item in pair)
                if not accepted:
                    continue
                selected = False
                for current_at in range(accepted_at + 1, min(len(eligible), accepted_at + 7)):
                    current = eligible[current_at]
                    pair_back = eligible[max(0, current_at - 1):current_at + 1]
                    failed = len(pair_back) == 2 and (all(item.close_e8 <= level.price_e8 for item in pair_back) if direction == "UP" else all(item.close_e8 >= level.price_e8 for item in pair_back))
                    retest = current.low_e8 <= level.price_e8 < current.close_e8 and current.close_e8 > current.open_e8 if direction == "UP" else current.high_e8 >= level.price_e8 > current.close_e8 and current.close_e8 < current.open_e8
                    if failed:
                        break
                    if retest:
                        aligned, states = htf_alignment(htf, current.close_at, direction)
                        if aligned:
                            item = raw_candidate(SETUPS[1], direction, current.close_at, eligible[accepted_at - 1:current_at + 1], [level])
                            item["htf_states"] = states
                            by_setup[SETUPS[1]].append(item)
                            selected = True
                        break
                if selected:
                    break

    output: list[dict[str, Any]] = []
    for setup, values in by_setup.items():
        first_time = min(item["decision"] for item in values)
        same = [item for item in values if item["decision"] == first_time]
        merged_levels = sorted({level.level_id: level for item in same for level in item["levels"]}.values(), key=lambda item: item.level_id)
        representative = min(same, key=lambda item: [level.level_id for level in item["levels"]])
        representative = dict(representative)
        representative["levels"] = tuple(merged_levels)
        representative["trigger_low_e8"] = min(item["trigger_low_e8"] for item in same)
        representative["trigger_high_e8"] = max(item["trigger_high_e8"] for item in same)
        representative["trigger_hashes"] = tuple(sorted({value for item in same for value in item["trigger_hashes"]}))
        output.append(representative)
    return sorted(output, key=lambda item: (item["decision"], item["setup"]))


def gc_events(path: Path, contexts: Mapping[tuple[str, str], Context]) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], set[tuple[str, str]]]:
    prior_contexts = {key: value.prior_context for key, value in contexts.items()}
    rows = prior.load_gc_candidates(path, prior_contexts)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["session_date"]), str(row["session_code"]))].append(row)
    return grouped, prior.gc_coverage_keys()


def signal_row(
    context: Context,
    candidate: Mapping[str, Any],
    bars: Mapping[datetime, prior.Bar],
    base: Sequence[Level],
    gc_by_key: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    covered: set[tuple[str, str]],
) -> dict[str, Any] | None:
    decision = candidate["decision"]
    five = prior.five_minute_bars(bars, context.session_open - timedelta(minutes=110), decision)
    atr = prior.atr_at(five, decision)
    if atr is None:
        return None
    known = levels_at(base, context, bars, decision)
    key = (context.session_date, context.session_code)
    matches = [
        item for item in gc_by_key.get(key, [])
        if item["direction"] == candidate["direction"]
        and decision - timedelta(minutes=5) <= item["decision"] <= decision
    ]
    is_covered = key in covered
    htf_payload = candidate["htf_states"]
    level_payload = [
        {"level_id": item.level_id, "family": item.family, "side": item.side, "price_e8": item.price_e8, "known_at": iso_z(item.known_at), "evidence_hash": item.evidence_hash}
        for item in known
    ]
    trigger_levels = sorted(item.level_id for item in candidate["levels"])
    identity = {
        "case_id": context.case_id, "setup": candidate["setup"],
        "direction": candidate["direction"], "decision": iso_z(decision),
        "trigger_levels": trigger_levels, "trigger_hashes": sorted(candidate["trigger_hashes"]),
    }
    signal_id = f"FAMAE::{canonical_hash(identity)[:24]}"
    lineage = canonical_hash({
        **identity, "context_hash": context.prior_context.context_hash,
        "htf": htf_payload, "known_levels": level_payload,
        "gc_events": sorted(item["source_event_id"] for item in matches),
    })
    return {
        "signal_id": signal_id,
        "case_id": context.case_id,
        "session_date": context.session_date,
        "session_code": context.session_code,
        "iso_week": context.iso_week,
        "setup_id": candidate["setup"],
        "direction": candidate["direction"],
        "signal_at_utc": iso_z(decision),
        "fundamental_score": context.score,
        "fundamental_confidence": context.confidence,
        "fundamental_coverage": context.coverage,
        "fundamental_direction": context.direction,
        "htf_states_json": canonical_json(htf_payload),
        "htf_alignment": True,
        "trigger_level_ids_json": canonical_json(trigger_levels),
        "known_levels_json": canonical_json(level_payload),
        "trigger_low_e8": int(candidate["trigger_low_e8"]),
        "trigger_high_e8": int(candidate["trigger_high_e8"]),
        "atr20_5m_e8": int(atr),
        "gc_covered": is_covered,
        "gc_confirmed": bool(matches) if is_covered else None,
        "gc_event_ids_json": canonical_json(sorted(item["source_event_id"] for item in matches)),
        "context_hash": context.prior_context.context_hash,
        "lineage_hash": lineage,
    }


def materialize_implementation(
    implementation: str,
    contexts: Sequence[Context],
    htf: Mapping[str, Sequence[HTFBar]],
    bars_by_key: Mapping[tuple[str, str], Mapping[datetime, prior.Bar]],
    gc_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context_map = {(item.session_date, item.session_code): item for item in contexts}
    gc_by_key, covered = gc_events(gc_path, context_map)
    rows: list[dict[str, Any]] = []
    level_counts: dict[str, int] = defaultdict(int)
    detector = detect_primary if implementation == "primary" else detect_reference
    macro_sessions = htf_aligned_signals = 0
    for context in contexts:
        if context.direction not in {"UP", "DOWN"}:
            continue
        macro_sessions += 1
        key = (context.session_date, context.session_code)
        bars = bars_by_key[key]
        base = base_levels(context, htf, bars)
        for level in base:
            level_counts[level.family] += 1
        candidates = detector(context, bars, htf, base)
        htf_aligned_signals += len(candidates)
        for candidate in candidates:
            row = signal_row(context, candidate, bars, base, gc_by_key, covered)
            if row is not None:
                rows.append(row)
    rows.sort(key=lambda row: (row["session_date"], row["session_code"], row["signal_at_utc"], row["setup_id"], row["signal_id"]))
    identities = [row["signal_id"] for row in rows]
    return rows, {
        "implementation": implementation,
        "macro_directional_sessions": macro_sessions,
        "aligned_candidates_before_atr_gate": htf_aligned_signals,
        "materialized_signals": len(rows),
        "signals_by_session": {session: sum(row["session_code"] == session for row in rows) for session in SESSIONS},
        "signals_by_setup": {setup: sum(row["setup_id"] == setup for row in rows) for setup in SETUPS},
        "signals_by_session_setup": {
            f"{session}|{setup}": sum(row["session_code"] == session and row["setup_id"] == setup for row in rows)
            for session in SESSIONS for setup in SETUPS
        },
        "gc_covered_signals": sum(row["gc_covered"] for row in rows),
        "gc_confirmed_signals": sum(row["gc_confirmed"] is True for row in rows),
        "level_availability_counts": dict(sorted(level_counts.items())),
        "signal_identity_hash": canonical_hash(identities),
        "complete_rows_hash": canonical_hash(rows),
        "outcomes_joined": False,
    }


def materialize() -> dict[str, Any]:
    freeze = verify_freeze()
    amendment = load_json(AMENDMENT_A)
    if amendment.get("status") != "SEALED_BEFORE_ANY_NEW_BRANCH_OUTCOME_ACCESS":
        raise ValueError("Pre-outcome Amendment A is not sealed")
    if (OUTPUT / "primary_signals.parquet").exists():
        raise FileExistsError("Materialization already exists")
    contexts, context_diagnostics = load_contexts()
    htf, htf_diagnostics = load_high_timeframes()
    prior_contexts = [item.prior_context for item in contexts]
    bars_by_key, bar_diagnostics = prior.load_preoutcome_bars(prior_contexts)
    primary, primary_diagnostics = materialize_implementation("primary", contexts, htf, bars_by_key, GC_PRIMARY)
    reference, reference_diagnostics = materialize_implementation("reference", contexts, htf, bars_by_key, GC_REFERENCE)
    if primary != reference:
        left = {row["signal_id"]: row for row in primary}
        right = {row["signal_id"]: row for row in reference}
        mismatch = {
            "only_primary": sorted(set(left).difference(right))[:20],
            "only_reference": sorted(set(right).difference(left))[:20],
            "shared_different": [key for key in sorted(set(left).intersection(right)) if left[key] != right[key]][:20],
        }
        attempt = 1
        mismatch_path = OUTPUT / "materialization_mismatch.json"
        while mismatch_path.exists():
            attempt += 1
            mismatch_path = OUTPUT / f"materialization_mismatch_attempt_{attempt}.json"
        write_json_exclusive(mismatch_path, mismatch)
        raise ValueError(f"Primary/reference signal mismatch: {mismatch}")
    write_parquet_exclusive(OUTPUT / "primary_signals.parquet", primary, SIGNAL_SCHEMA)
    write_parquet_exclusive(OUTPUT / "reference_signals.parquet", reference, SIGNAL_SCHEMA)
    if sha256_file(OUTPUT / "primary_signals.parquet") != sha256_file(OUTPUT / "reference_signals.parquet"):
        raise ValueError("Materialized Parquet outputs are not byte-identical")
    certification = {
        "version": "GOLD_FAMAE_V1_MATERIALIZATION_CERTIFICATION_1_0",
        "status": "PASS_OUTCOME_BLIND_MATERIALIZATION" if primary else "PASS_OUTCOME_BLIND_MATERIALIZATION_ZERO_SIGNALS",
        "certified_at_utc": utc_now(),
        "preoutcome_freeze_sha256": sha256_file(FREEZE),
        "preoutcome_amendment_a": file_record(AMENDMENT_A),
        "context_diagnostics": context_diagnostics,
        "htf_diagnostics": htf_diagnostics,
        "bar_diagnostics": bar_diagnostics,
        "primary_diagnostics": primary_diagnostics,
        "reference_diagnostics": reference_diagnostics,
        "exact_primary_reference_rows": primary == reference,
        "byte_identical_parquet": True,
        "primary_parquet": file_record(OUTPUT / "primary_signals.parquet"),
        "reference_parquet": file_record(OUTPUT / "reference_signals.parquet"),
        "new_branch_outcomes_accessed": False,
        "forward_values_accessed": False,
        "paid_acquisition_usd": 0.0,
        "freeze_receipt": freeze["branch_rules_hash"],
    }
    write_json_exclusive(OUTPUT / "materialization_certification.json", certification)
    return certification


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("materialize", "selftest"))
    return parser.parse_args()


def selftest() -> None:
    synthetic = [
        HTFBar("H1", datetime(2024, 1, 1, hour, tzinfo=UTC), datetime(2024, 1, 1, hour + 1, tzinfo=UTC),
               100 * SCALE, (102 + hour) * SCALE, (99 - hour) * SCALE, (101 + hour) * SCALE, str(hour))
        for hour in range(15)
    ]
    state = pressure_state(synthetic, synthetic[-1].close_at)
    if state["state"] not in {"BULLISH", "BEARISH", "NEUTRAL"} or state["atr14_e8"] is None:
        raise AssertionError(state)
    if canonical_hash({"b": 1, "a": 2}) != canonical_hash({"a": 2, "b": 1}):
        raise AssertionError("Canonical hashing is not stable")
    print(json.dumps({"status": "PASS_SELFTEST", "pressure_state": state["state"]}, sort_keys=True))


def main() -> None:
    args = parse_args()
    if args.phase == "selftest":
        selftest()
    else:
        print(json.dumps(materialize(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
