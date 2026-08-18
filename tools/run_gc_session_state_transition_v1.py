#!/usr/bin/env python3
"""Run GC Session State-Transition Edge Discovery V1.

The analytical design is sealed separately before this program may deserialize
market rows. This runner has two irreversible stages:

1. materialize and independently reproduce point-in-time event identities,
   then seal those identities and this implementation before any outcome join;
2. open the development XAUUSD path once, calculate the frozen first-passage
   and excursion endpoints, run all frozen tests twice, and seal the verdict.

It never reads 2025/2026, acquires data, constructs trades, or calculates PnL.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import NormalDist
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gc_session_state_transition_v1_v01"
REPORT = ROOT / "GC_SESSION_STATE_TRANSITION_EDGE_DISCOVERY_V1_REPORT.md"

CONTRACT = ROOT / "GC_SESSION_STATE_TRANSITION_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gc_session_state_transition_v1_protocol_v01.json"
TEST_REGISTRY = MANIFESTS / "gc_session_state_transition_v1_test_registry_v01.json"
DESIGN_FREEZE = MANIFESTS / "gc_session_state_transition_v1_design_freeze_v01.json"
PREOUTCOME_FREEZE = MANIFESTS / "gc_session_state_transition_v1_preoutcome_freeze_v01.json"

CASE_PATH = ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz"
PRICE_PATH = ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz"
GC_PRIMARY = ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/primary_events.parquet"
GC_REFERENCE = ARTIFACTS / "gc_session_trigger_edge_v2r1_v01/reference_events.parquet"
GC_ROWS = MANIFESTS / "gc_session_trigger_edge_m2_row_registry_v01.json"

EXPECTED = {
    CONTRACT: None,
    PROTOCOL: None,
    TEST_REGISTRY: None,
    DESIGN_FREEZE: None,
    CASE_PATH: "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9",
    PRICE_PATH: "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
    GC_PRIMARY: "9557731bbc45d985d06227b3b15451f69e31f069697ab7cc5fae66293965a87b",
    GC_REFERENCE: "9557731bbc45d985d06227b3b15451f69e31f069697ab7cc5fae66293965a87b",
    GC_ROWS: "a7a36ae82d92ce91a25e36fcb7f1c95807de67c996d01198648246daa345dc5d",
}

ENGINEERING_DATES = {
    "2024-01-05", "2024-01-09", "2024-01-11",
    "2024-01-30", "2024-01-31", "2024-03-20",
}
SESSIONS = ("LONDON", "NEW_YORK")
SESSION_ZONES = {"LONDON": ZoneInfo("Europe/London"), "NEW_YORK": ZoneInfo("America/New_York")}
XAU_FAMILIES = (
    "LEVEL_SWEEP_RECLAIM", "LEVEL_BREAK_ACCEPT", "LEVEL_FAILED_ACCEPTANCE",
    "STRUCTURE_BREAK_CONTINUATION", "STRUCTURE_STATE_REVERSAL",
    "COMPRESSION_EXPANSION_BREAK",
)
GC_FAMILIES = ("FLOW_DEPTH_ALIGNMENT_ONSET", "ABSORPTION_ONSET", "FRAGILITY_FLOW_ONSET")
EVENT_FAMILIES = (*XAU_FAMILIES, *GC_FAMILIES)
CONTEXTS = (
    "MACRO_CONCORDANT", "MACRO_REAL_USD_CONCORDANT",
    "SESSION_OPEN_STRUCTURE_CONCORDANT", "GC_CONFIRMING_WITHIN_5M",
)
LEVEL_FAMILIES = ("ASIA_RANGE", "PRIOR_DAY_RANGE", "SESSION_OPENING_RANGE_15", "LONDON_PRE_NEW_YORK_RANGE")
SCALE = 100_000_000
HOLDOUT_RE = re.compile(r'"open_time"\s*:\s*"202(?:5|6)-')
DATE_RE = re.compile(rb'"session_date":"(\d{4}-\d{2}-\d{2})"')
SESSION_RE = re.compile(rb'"session_code":"(LONDON|NEW_YORK)"')


EVENT_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), False),
        pa.field("source_event_id", pa.string(), False),
        pa.field("case_id", pa.string(), False),
        pa.field("session_date", pa.string(), False),
        pa.field("session_code", pa.string(), False),
        pa.field("iso_week", pa.string(), False),
        pa.field("event_family", pa.string(), False),
        pa.field("source_domain", pa.string(), False),
        pa.field("direction", pa.string(), False),
        pa.field("decision_at_utc", pa.string(), False),
        pa.field("anchor_open_utc", pa.string(), False),
        pa.field("anchor_close_e8", pa.int64(), False),
        pa.field("atr20_5m_e8", pa.int64(), False),
        pa.field("level_families_json", pa.string(), False),
        pa.field("evidence_hash", pa.string(), False),
        pa.field("macro_state", pa.string(), False),
        pa.field("real_usd_state", pa.string(), False),
        pa.field("session_open_structure_state", pa.string(), False),
        pa.field("gc_covered", pa.bool_(), False),
        *[pa.field(f"context__{name}", pa.string(), False) for name in CONTEXTS],
        pa.field("lineage_hash", pa.string(), False),
    ]
)

OUTCOME_SCHEMA = pa.schema(
    [
        *EVENT_SCHEMA,
        pa.field("path_quality_30m", pa.string(), False),
        pa.field("path_quality_60m", pa.string(), False),
        pa.field("path_quality_120m", pa.string(), False),
        pa.field("first_passage_30m", pa.string(), False),
        pa.field("first_passage_60m", pa.string(), False),
        pa.field("first_passage_120m", pa.string(), False),
        pa.field("score_30m", pa.int64(), True),
        pa.field("score_60m", pa.int64(), True),
        pa.field("score_120m", pa.int64(), True),
        pa.field("favorable_excursion_atr_60m", pa.float64(), True),
        pa.field("adverse_excursion_atr_60m", pa.float64(), True),
        pa.field("path_dominance_atr_60m", pa.float64(), True),
        pa.field("outcome_lineage_hash", pa.string(), False),
    ]
)


@dataclass(frozen=True, slots=True)
class Bar:
    open_at: datetime
    close_at: datetime
    open_e8: int
    high_e8: int
    low_e8: int
    close_e8: int
    record_id: str
    record_hash: str


@dataclass(frozen=True, slots=True)
class FiveBar:
    open_at: datetime
    close_at: datetime
    open_e8: int
    high_e8: int
    low_e8: int
    close_e8: int
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class CaseContext:
    case_id: str
    session_date: str
    session_code: str
    session_open: datetime
    iso_week: str
    levels: Mapping[str, int]
    macro_state: str
    real_usd_state: str
    structure_state: str
    context_hash: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
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
    table = pa.Table.from_pylist(list(rows), schema=schema)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=65_536)
    temporary.replace(path)


def scaled(value: Any) -> int:
    number = Decimal(str(value)) * SCALE
    return int(number.to_integral_value(rounding=ROUND_HALF_UP))


def fact_eligible(fact: Mapping[str, Any], decision: datetime) -> bool:
    if not fact or fact.get("epistemic_status") == "UNKNOWN" or fact.get("value") is None:
        return False
    available = fact.get("available_at")
    return isinstance(available, str) and parse_dt(available) <= decision and fact.get("quality") not in {"MISSING", "NOT_LICENSED", "UNVERIFIED_AVAILABILITY"}


def nested(value: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def case_record_hash(case: Mapping[str, Any]) -> str:
    copy = deepcopy(case)
    metadata = copy.get("case_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Missing case metadata")
    metadata.pop("record_hash", None)
    return canonical_hash(copy)


def session_bounds(context: CaseContext) -> tuple[datetime, datetime]:
    return context.session_open + timedelta(minutes=15), context.session_open + timedelta(hours=3)


def history_start(context: CaseContext) -> datetime:
    default = context.session_open - timedelta(minutes=130)
    if context.session_code == "LONDON":
        return default
    local_day = date.fromisoformat(context.session_date)
    london = datetime.combine(local_day, time(8, 0), tzinfo=SESSION_ZONES["LONDON"]).astimezone(UTC)
    return min(default, london)


def verify_design() -> dict[str, Any]:
    design = load_json(DESIGN_FREEZE)
    if design.get("status") != "SEALED_BEFORE_ANY_V1_OUTCOME_ACCESS":
        raise ValueError("V1 design is not sealed")
    controls = design.get("controls", {})
    for name, path in (("contract", CONTRACT), ("protocol", PROTOCOL), ("test_registry", TEST_REGISTRY)):
        if sha256_file(path) != controls[name]["sha256"]:
            raise ValueError(f"Frozen control changed: {name}")
    for path, expected in EXPECTED.items():
        if expected is not None and sha256_file(path) != expected:
            raise ValueError(f"Frozen source changed: {path}")
    registry = load_json(TEST_REGISTRY)
    if registry.get("counts", {}).get("total") != 90:
        raise ValueError("Frozen test registry changed")
    return design


def load_case_contexts() -> tuple[list[CaseContext], dict[str, Any]]:
    contexts: list[CaseContext] = []
    seen: set[tuple[str, str]] = set()
    raw_rows = excluded = verified = 0
    with gzip.open(CASE_PATH, "rb") as handle:
        for raw in handle:
            raw_rows += 1
            dm, sm = DATE_RE.search(raw), SESSION_RE.search(raw)
            if dm is None or sm is None:
                raise ValueError(f"Case identity missing at row {raw_rows}")
            session_date = dm.group(1).decode("ascii")
            session_code = sm.group(1).decode("ascii")
            if session_date > "2024-12-31":
                raise ValueError("Forward year entered case projection")
            case = json.loads(raw)
            metadata = case["case_metadata"]
            if case_record_hash(case) != metadata["record_hash"]:
                raise ValueError(f"Case record hash failed: {session_date} {session_code}")
            verified += 1
            if session_date in ENGINEERING_DATES:
                excluded += 1
                continue
            key = (session_date, session_code)
            if key in seen:
                raise ValueError(f"Duplicate case key: {key}")
            seen.add(key)
            if metadata.get("data_partition") != "DEVELOPMENT_2021_2024" or metadata.get("access_class") != "DEVELOPMENT":
                raise ValueError(f"Non-development case: {key}")
            decision = parse_dt(str(metadata["decision_at"]))
            state = case["decision_state"]
            levels: dict[str, int] = {}
            for item in state.get("levels", []):
                kind = str(item.get("level_type"))
                price = item.get("price") if isinstance(item.get("price"), Mapping) else {}
                if kind in {"ASIA_HIGH", "ASIA_LOW", "PRIOR_DAY_HIGH", "PRIOR_DAY_LOW"} and fact_eligible(price, decision):
                    levels[kind] = scaled(price["value"])
            regime = nested(state, "layers", "market_regime", "regime_state")
            score: float | None = None
            if fact_eligible(regime, decision) and isinstance(regime.get("value"), Mapping):
                raw_score = regime["value"].get("directional_score")
                if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
                    score = float(raw_score)
            macro = "UNKNOWN" if score is None else "BULLISH" if score >= 20 else "BEARISH" if score <= -20 else "NEUTRAL"
            real = nested(state, "layers", "market_regime", "rates", "real_yield_10y")
            usd = nested(state, "layers", "market_regime", "usd")
            changes: list[float | None] = []
            for fact in (real, usd):
                value = fact.get("value") if isinstance(fact.get("value"), Mapping) else {}
                change = value.get("absolute_change") if fact_eligible(fact, decision) and value.get("change_epistemic_status") != "UNKNOWN" else None
                changes.append(float(change) if isinstance(change, (int, float)) and not isinstance(change, bool) else None)
            real_usd = "UNKNOWN"
            if all(item is not None for item in changes):
                real_usd = "GOLD_BULLISH" if max(float(changes[0]), float(changes[1])) < 0 else "GOLD_BEARISH" if min(float(changes[0]), float(changes[1])) > 0 else "CONFLICTED"
            trends: dict[str, str] = {}
            for frame in nested(state, "market_structure").get("timeframes", []):
                if frame.get("timeframe") not in {"15m", "1h"}:
                    continue
                trend = frame.get("trend_state") if isinstance(frame.get("trend_state"), Mapping) else {}
                if fact_eligible(trend, decision):
                    trends[str(frame["timeframe"])] = str(trend["value"])
            structure = "BULLISH" if trends.get("15m") == trends.get("1h") == "BULLISH" else "BEARISH" if trends.get("15m") == trends.get("1h") == "BEARISH" else "MIXED" if set(trends) == {"15m", "1h"} else "UNKNOWN"
            iso = date.fromisoformat(session_date).isocalendar()
            payload = {
                "case_id": metadata["case_id"], "session_date": session_date, "session_code": session_code,
                "decision": iso_z(decision), "levels": levels, "macro": macro, "real_usd": real_usd,
                "structure": structure, "record_hash": metadata["record_hash"],
            }
            contexts.append(CaseContext(
                case_id=str(metadata["case_id"]), session_date=session_date, session_code=session_code,
                session_open=decision, iso_week=f"{iso.year}-W{iso.week:02d}", levels=levels,
                macro_state=macro, real_usd_state=real_usd, structure_state=structure,
                context_hash=canonical_hash(payload),
            ))
            # The pre-existing subsequent_behaviour object is deliberately not retained or joined here.
            del case
    contexts.sort(key=lambda item: (item.session_date, item.session_code))
    diagnostics = {
        "case_rows_seen": raw_rows, "case_record_hashes_verified": verified,
        "engineering_session_rows_excluded": excluded, "research_session_rows": len(contexts),
        "london_rows": sum(item.session_code == "LONDON" for item in contexts),
        "new_york_rows": sum(item.session_code == "NEW_YORK" for item in contexts),
        "context_projection_only": True, "subsequent_behaviour_joined": False,
    }
    return contexts, diagnostics


def bar_from_record(record: Mapping[str, Any]) -> Bar | None:
    if record.get("timeframe") != "1m" or record.get("instrument_code") != "XAUUSD" or record.get("complete") is not True:
        return None
    opened, closed = parse_dt(str(record["open_time"])), parse_dt(str(record["close_time"]))
    available = parse_dt(str(record["available_at"]))
    if closed != opened + timedelta(minutes=1) or available > closed:
        return None
    ohlc = record.get("ohlc") if isinstance(record.get("ohlc"), Mapping) else {}
    if any(ohlc.get(name) is None for name in ("open", "high", "low", "close")):
        return None
    bar = Bar(opened, closed, scaled(ohlc["open"]), scaled(ohlc["high"]), scaled(ohlc["low"]), scaled(ohlc["close"]), str(record["record_id"]), str(record["record_hash"]))
    if not (bar.low_e8 <= min(bar.open_e8, bar.close_e8) <= max(bar.open_e8, bar.close_e8) <= bar.high_e8):
        raise ValueError(f"Invalid OHLC: {bar.record_id}")
    return bar


def load_preoutcome_bars(contexts: Sequence[CaseContext]) -> tuple[dict[tuple[str, str], dict[datetime, Bar]], dict[str, Any]]:
    intervals: list[tuple[datetime, datetime, tuple[str, str]]] = []
    output: dict[tuple[str, str], dict[datetime, Bar]] = {}
    for context in contexts:
        key = (context.session_date, context.session_code)
        intervals.append((history_start(context), context.session_open + timedelta(hours=3), key))
        output[key] = {}
    intervals.sort(key=lambda item: (item[0], item[2]))
    active: list[tuple[datetime, datetime, tuple[str, str]]] = []
    index = source_rows = selected_rows = duplicates = invalid = 0
    saw_one_minute = False
    with gzip.open(PRICE_PATH, "rt", encoding="utf-8") as handle:
        for line in handle:
            if HOLDOUT_RE.search(line):
                break
            record = json.loads(line)
            timeframe = record.get("timeframe")
            if timeframe != "1m":
                if saw_one_minute:
                    break
                continue
            saw_one_minute = True
            if record.get("instrument_code") != "XAUUSD":
                continue
            source_rows += 1
            opened = parse_dt(str(record["open_time"]))
            while index < len(intervals) and intervals[index][0] <= opened:
                active.append(intervals[index])
                index += 1
            active = [item for item in active if item[1] > opened]
            if not active:
                if index >= len(intervals):
                    break
                continue
            targets = [item for item in active if item[0] <= opened < item[1]]
            if not targets:
                continue
            bar = bar_from_record(record)
            if bar is None:
                invalid += len(targets)
                continue
            for _, _, key in targets:
                if opened in output[key]:
                    duplicates += 1
                    continue
                output[key][opened] = bar
                selected_rows += 1
    return output, {
        "source_1m_rows_deserialized_before_2025": source_rows,
        "selected_session_bar_allocations": selected_rows,
        "duplicate_allocations": duplicates, "invalid_allocations": invalid,
        "first_2025_or_2026_row_deserialized": False,
        "outcomes_joined": False,
    }


def contiguous_bars(values: Mapping[datetime, Bar], start: datetime, end: datetime) -> list[Bar] | None:
    expected = int((end - start).total_seconds() // 60)
    bars = [values.get(start + timedelta(minutes=index)) for index in range(expected)]
    if any(item is None for item in bars):
        return None
    typed = [item for item in bars if item is not None]
    return typed if all(left.close_at == right.open_at for left, right in zip(typed, typed[1:])) else None


def five_minute_bars(values: Mapping[datetime, Bar], start: datetime, end: datetime) -> list[FiveBar]:
    aligned = start.replace(minute=(start.minute // 5) * 5, second=0, microsecond=0)
    if aligned < start:
        aligned += timedelta(minutes=5)
    output: list[FiveBar] = []
    while aligned + timedelta(minutes=5) <= end:
        bars = contiguous_bars(values, aligned, aligned + timedelta(minutes=5))
        if bars is not None:
            output.append(FiveBar(
                aligned, aligned + timedelta(minutes=5), bars[0].open_e8,
                max(item.high_e8 for item in bars), min(item.low_e8 for item in bars),
                bars[-1].close_e8, canonical_hash([item.record_hash for item in bars]),
            ))
        aligned += timedelta(minutes=5)
    return output


def true_range(current: FiveBar, previous: FiveBar) -> int:
    return max(current.high_e8 - current.low_e8, abs(current.high_e8 - previous.close_e8), abs(current.low_e8 - previous.close_e8))


def atr_at(five: Sequence[FiveBar], decision: datetime, *, exclude_equal: bool = False) -> int | None:
    eligible = [item for item in five if item.close_at < decision or (item.close_at == decision and not exclude_equal)]
    if len(eligible) < 21:
        return None
    window = eligible[-21:]
    if any(left.close_at != right.open_at for left, right in zip(window, window[1:])):
        return None
    total = sum(true_range(window[index], window[index - 1]) for index in range(1, 21))
    value = int((Decimal(total) / Decimal(20)).to_integral_value(rounding=ROUND_HALF_UP))
    return value if value > 0 else None


def dynamic_levels(context: CaseContext, bars: Mapping[datetime, Bar]) -> dict[str, tuple[int, int, str]]:
    output: dict[str, tuple[int, int, str]] = {}
    if context.levels.get("ASIA_HIGH", 0) > context.levels.get("ASIA_LOW", 0):
        output["ASIA_RANGE"] = (
            context.levels["ASIA_HIGH"], context.levels["ASIA_LOW"],
            canonical_hash([context.context_hash, "ASIA_RANGE", context.levels["ASIA_HIGH"], context.levels["ASIA_LOW"]]),
        )
    if context.levels.get("PRIOR_DAY_HIGH", 0) > context.levels.get("PRIOR_DAY_LOW", 0):
        output["PRIOR_DAY_RANGE"] = (
            context.levels["PRIOR_DAY_HIGH"], context.levels["PRIOR_DAY_LOW"],
            canonical_hash([context.context_hash, "PRIOR_DAY_RANGE", context.levels["PRIOR_DAY_HIGH"], context.levels["PRIOR_DAY_LOW"]]),
        )
    opening = contiguous_bars(bars, context.session_open, context.session_open + timedelta(minutes=15))
    if opening is not None:
        high, low = max(item.high_e8 for item in opening), min(item.low_e8 for item in opening)
        if high > low:
            output["SESSION_OPENING_RANGE_15"] = (high, low, canonical_hash([item.record_hash for item in opening]))
    if context.session_code == "NEW_YORK":
        local_day = date.fromisoformat(context.session_date)
        london_open = datetime.combine(local_day, time(8, 0), tzinfo=SESSION_ZONES["LONDON"]).astimezone(UTC)
        london = contiguous_bars(bars, london_open, context.session_open)
        if london is not None:
            high, low = max(item.high_e8 for item in london), min(item.low_e8 for item in london)
            if high > low:
                output["LONDON_PRE_NEW_YORK_RANGE"] = (high, low, canonical_hash([item.record_hash for item in london]))
    return output


def candidate(
    family: str,
    direction: str,
    decision: datetime,
    evidence: Sequence[str],
    *,
    source_domain: str,
    level_family: str | None = None,
    source_event_id: str = "",
) -> dict[str, Any]:
    return {
        "family": family, "direction": direction, "decision": decision,
        "evidence": tuple(str(item) for item in evidence), "source_domain": source_domain,
        "level_family": level_family, "source_event_id": source_event_id,
    }


def level_candidates_primary(context: CaseContext, bars: Mapping[datetime, Bar]) -> list[dict[str, Any]]:
    levels = dynamic_levels(context, bars)
    scan_start, scan_end = session_bounds(context)
    emitted: set[tuple[str, str, str]] = set()
    pending: dict[tuple[str, str], tuple[int, str, str]] = {}
    previous: dict[str, Bar | None] = {}
    raw: list[dict[str, Any]] = []
    for minute in range(1, 181):
        decision = context.session_open + timedelta(minutes=minute)
        bar = bars.get(decision - timedelta(minutes=1))
        for name, (upper, lower, signature) in sorted(levels.items()):
            prior = previous.get(name)
            if bar is None:
                previous[name] = None
                pending.pop((name, "UPPER"), None)
                pending.pop((name, "LOWER"), None)
                continue
            adjacent = prior is not None and prior.close_at == bar.open_at
            in_scan = scan_start <= decision <= scan_end
            tests = (
                ("DOWN", bar.high_e8 > upper and bar.close_e8 <= upper or adjacent and prior.high_e8 > upper and prior.close_e8 > upper and bar.close_e8 <= upper, "UPPER_RECLAIM"),
                ("UP", bar.low_e8 < lower and bar.close_e8 >= lower or adjacent and prior.low_e8 < lower and prior.close_e8 < lower and bar.close_e8 >= lower, "LOWER_RECLAIM"),
            )
            for direction, passed, code in tests:
                key = ("LEVEL_SWEEP_RECLAIM", direction, name)
                if passed and in_scan and key not in emitted:
                    raw.append(candidate(key[0], direction, decision, (signature, bar.record_hash, code), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
                    emitted.add(key)
            accept_upper = adjacent and prior.close_e8 > upper and bar.close_e8 > upper
            accept_lower = adjacent and prior.close_e8 < lower and bar.close_e8 < lower
            if accept_upper:
                key = ("LEVEL_BREAK_ACCEPT", "UP", name)
                evidence = canonical_hash([signature, prior.record_hash, bar.record_hash, "UPPER_ACCEPT"])
                if in_scan and key not in emitted:
                    raw.append(candidate(key[0], key[1], decision, (signature, prior.record_hash, bar.record_hash, "UPPER_ACCEPT"), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
                    emitted.add(key)
                pending[(name, "UPPER")] = (minute, signature, evidence)
            if accept_lower:
                key = ("LEVEL_BREAK_ACCEPT", "DOWN", name)
                evidence = canonical_hash([signature, prior.record_hash, bar.record_hash, "LOWER_ACCEPT"])
                if in_scan and key not in emitted:
                    raw.append(candidate(key[0], key[1], decision, (signature, prior.record_hash, bar.record_hash, "LOWER_ACCEPT"), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
                    emitted.add(key)
                pending[(name, "LOWER")] = (minute, signature, evidence)
            for side, direction, returned, code in (
                ("UPPER", "DOWN", bar.close_e8 <= upper, "UPPER_FAILED"),
                ("LOWER", "UP", bar.close_e8 >= lower, "LOWER_FAILED"),
            ):
                state = pending.get((name, side))
                if state is None or minute <= state[0]:
                    continue
                elapsed = minute - state[0]
                key = ("LEVEL_FAILED_ACCEPTANCE", direction, name)
                if elapsed <= 5 and returned:
                    if in_scan and key not in emitted:
                        raw.append(candidate(key[0], direction, decision, (state[1], bar.record_hash, code), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
                        emitted.add(key)
                    pending.pop((name, side), None)
                elif elapsed >= 5:
                    pending.pop((name, side), None)
            previous[name] = bar
    return raw


def level_candidates_reference(context: CaseContext, bars: Mapping[datetime, Bar]) -> list[dict[str, Any]]:
    levels = dynamic_levels(context, bars)
    scan_start, scan_end = session_bounds(context)
    decisions = [context.session_open + timedelta(minutes=index) for index in range(1, 181)]
    raw: list[dict[str, Any]] = []
    for name, (upper, lower, signature) in sorted(levels.items()):
        found: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        accepts: dict[str, list[tuple[int, str]]] = {"UPPER": [], "LOWER": []}
        for index, decision in enumerate(decisions):
            bar = bars.get(decision - timedelta(minutes=1))
            prior = bars.get(decisions[index - 1] - timedelta(minutes=1)) if index else None
            if bar is None:
                continue
            adjacent = prior is not None and prior.close_at == bar.open_at
            in_scan = scan_start <= decision <= scan_end
            if in_scan and (bar.high_e8 > upper and bar.close_e8 <= upper or adjacent and prior.high_e8 > upper and prior.close_e8 > upper and bar.close_e8 <= upper):
                found[("LEVEL_SWEEP_RECLAIM", "DOWN")].append(candidate("LEVEL_SWEEP_RECLAIM", "DOWN", decision, (signature, bar.record_hash, "UPPER_RECLAIM"), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
            if in_scan and (bar.low_e8 < lower and bar.close_e8 >= lower or adjacent and prior.low_e8 < lower and prior.close_e8 < lower and bar.close_e8 >= lower):
                found[("LEVEL_SWEEP_RECLAIM", "UP")].append(candidate("LEVEL_SWEEP_RECLAIM", "UP", decision, (signature, bar.record_hash, "LOWER_RECLAIM"), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
            if adjacent and prior.close_e8 > upper and bar.close_e8 > upper:
                evidence = canonical_hash([signature, prior.record_hash, bar.record_hash, "UPPER_ACCEPT"])
                accepts["UPPER"].append((index, evidence))
                if in_scan:
                    found[("LEVEL_BREAK_ACCEPT", "UP")].append(candidate("LEVEL_BREAK_ACCEPT", "UP", decision, (signature, prior.record_hash, bar.record_hash, "UPPER_ACCEPT"), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
            if adjacent and prior.close_e8 < lower and bar.close_e8 < lower:
                evidence = canonical_hash([signature, prior.record_hash, bar.record_hash, "LOWER_ACCEPT"])
                accepts["LOWER"].append((index, evidence))
                if in_scan:
                    found[("LEVEL_BREAK_ACCEPT", "DOWN")].append(candidate("LEVEL_BREAK_ACCEPT", "DOWN", decision, (signature, prior.record_hash, bar.record_hash, "LOWER_ACCEPT"), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
        for side, direction in (("UPPER", "DOWN"), ("LOWER", "UP")):
            for accepted_index, accepted_evidence in accepts[side]:
                for return_index in range(accepted_index + 1, min(accepted_index + 6, len(decisions))):
                    decision = decisions[return_index]
                    bar = bars.get(decision - timedelta(minutes=1))
                    if bar is None:
                        break
                    returned = bar.close_e8 <= upper if side == "UPPER" else bar.close_e8 >= lower
                    if returned:
                        if scan_start <= decision <= scan_end:
                            code = "UPPER_FAILED" if side == "UPPER" else "LOWER_FAILED"
                            found[("LEVEL_FAILED_ACCEPTANCE", direction)].append(candidate("LEVEL_FAILED_ACCEPTANCE", direction, decision, (signature, bar.record_hash, code), source_domain="XAUUSD_PRICE_LEVEL", level_family=name))
                        break
        for items in found.values():
            if items:
                raw.append(min(items, key=lambda item: (item["decision"], item["evidence"])))
    return raw


def structure_candidates(context: CaseContext, five: Sequence[FiveBar], implementation: str) -> list[dict[str, Any]]:
    scan_start, scan_end = session_bounds(context)
    pivots_high: dict[int, tuple[int, str]] = {}
    pivots_low: dict[int, tuple[int, str]] = {}
    if implementation == "reference":
        for center in range(2, len(five) - 2):
            window = five[center - 2:center + 3]
            if any(left.close_at != right.open_at for left, right in zip(window, window[1:])):
                continue
            neighbours = [five[index] for index in (center - 2, center - 1, center + 1, center + 2)]
            if all(five[center].high_e8 > item.high_e8 for item in neighbours):
                pivots_high[center + 2] = (five[center].high_e8, five[center].evidence_hash)
            if all(five[center].low_e8 < item.low_e8 for item in neighbours):
                pivots_low[center + 2] = (five[center].low_e8, five[center].evidence_hash)
    latest_high: tuple[int, str] | None = None
    latest_low: tuple[int, str] | None = None
    broken_high: set[str] = set()
    broken_low: set[str] = set()
    regime = "UNKNOWN"
    emitted: set[tuple[str, str]] = set()
    raw: list[dict[str, Any]] = []
    for index, current in enumerate(five):
        if index >= 4:
            center = index - 2
            if implementation == "primary":
                window = five[center - 2:center + 3]
                if not any(left.close_at != right.open_at for left, right in zip(window, window[1:])):
                    neighbours = [five[item] for item in (center - 2, center - 1, center + 1, center + 2)]
                    if all(five[center].high_e8 > item.high_e8 for item in neighbours):
                        latest_high = (five[center].high_e8, five[center].evidence_hash)
                    if all(five[center].low_e8 < item.low_e8 for item in neighbours):
                        latest_low = (five[center].low_e8, five[center].evidence_hash)
            else:
                latest_high = pivots_high.get(index, latest_high)
                latest_low = pivots_low.get(index, latest_low)
        if index == 0 or five[index - 1].close_at != current.open_at:
            continue
        prior = five[index - 1]
        up = latest_high is not None and latest_high[1] not in broken_high and prior.close_e8 <= latest_high[0] < current.close_e8
        down = latest_low is not None and latest_low[1] not in broken_low and prior.close_e8 >= latest_low[0] > current.close_e8
        if up and down:
            continue
        direction: str | None = "UP" if up else "DOWN" if down else None
        if direction is None:
            continue
        pivot = latest_high if direction == "UP" else latest_low
        assert pivot is not None
        if direction == "UP":
            broken_high.add(pivot[1])
        else:
            broken_low.add(pivot[1])
        prior_regime = regime
        family = "STRUCTURE_STATE_REVERSAL" if prior_regime not in {"UNKNOWN", direction} else "STRUCTURE_BREAK_CONTINUATION"
        regime = direction
        if scan_start <= current.close_at <= scan_end and (family, direction) not in emitted:
            raw.append(candidate(family, direction, current.close_at, (pivot[1], current.evidence_hash, f"REGIME_{prior_regime}_TO_{direction}"), source_domain="XAUUSD_MARKET_STRUCTURE"))
            emitted.add((family, direction))
    return raw


def compression_candidates(context: CaseContext, five: Sequence[FiveBar], implementation: str) -> list[dict[str, Any]]:
    scan_start, scan_end = session_bounds(context)
    emitted: set[str] = set()
    output: list[dict[str, Any]] = []
    indices: Iterable[int] = range(21, len(five)) if implementation == "primary" else list(range(21, len(five)))
    for index in indices:
        current = five[index]
        history = five[index - 21:index]
        if len(history) != 21 or any(left.close_at != right.open_at for left, right in zip(history, history[1:])) or history[-1].close_at != current.open_at:
            continue
        atr = int((Decimal(sum(true_range(history[item], history[item - 1]) for item in range(1, 21))) / Decimal(20)).to_integral_value(rounding=ROUND_HALF_UP))
        if atr <= 0:
            continue
        prior_six = history[-6:]
        high, low = max(item.high_e8 for item in prior_six), min(item.low_e8 for item in prior_six)
        width = high - low
        current_tr = true_range(current, history[-1])
        compressed = 2 * width <= 5 * atr
        expanded = 2 * current_tr >= 3 * atr
        direction = "UP" if compressed and expanded and current.close_e8 > high else "DOWN" if compressed and expanded and current.close_e8 < low else None
        if direction is None or direction in emitted or not (scan_start <= current.close_at <= scan_end):
            continue
        output.append(candidate("COMPRESSION_EXPANSION_BREAK", direction, current.close_at, tuple([item.evidence_hash for item in prior_six] + [current.evidence_hash, "COMPRESSION_2P5_EXPANSION_1P5"]), source_domain="XAUUSD_SESSION_LIQUIDITY_PROXY"))
        emitted.add(direction)
    return output


def canonicalize_xau_candidates(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    level_raw = [dict(item) for item in raw if item["family"] in XAU_FAMILIES[:3]]
    nonlevel = [dict(item) for item in raw if item["family"] not in XAU_FAMILIES[:3]]
    first_per_level: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in sorted(level_raw, key=lambda value: (value["decision"], value["family"], value["direction"], str(value["level_family"]), value["evidence"])):
        key = (str(item["family"]), str(item["direction"]), str(item["level_family"]))
        first_per_level.setdefault(key, item)
    grouped: dict[tuple[str, str, datetime], list[dict[str, Any]]] = defaultdict(list)
    for item in first_per_level.values():
        grouped[(str(item["family"]), str(item["direction"]), item["decision"])].append(item)
    merged: list[dict[str, Any]] = []
    for (family, direction, decision), items in grouped.items():
        merged.append({
            "family": family, "direction": direction, "decision": decision,
            "evidence": tuple(sorted(canonical_hash(item["evidence"]) for item in items)),
            "source_domain": "XAUUSD_PRICE_LEVEL",
            "level_families": tuple(sorted(str(item["level_family"]) for item in items)),
            "source_event_id": "",
        })
    retained: list[dict[str, Any]] = []
    for family in XAU_FAMILIES[:3]:
        retained.extend(sorted((item for item in merged if item["family"] == family), key=lambda item: (item["decision"], item["direction"], item["level_families"], item["evidence"]))[:3])
    first_nonlevel: dict[tuple[str, str], dict[str, Any]] = {}
    for item in sorted(nonlevel, key=lambda value: (value["decision"], value["family"], value["direction"], value["evidence"])):
        item["level_families"] = ()
        first_nonlevel.setdefault((str(item["family"]), str(item["direction"])), item)
    retained.extend(first_nonlevel.values())
    return sorted(retained, key=lambda item: (item["decision"], item["family"], item["direction"], item["evidence"]))


def gc_coverage_keys() -> set[tuple[str, str]]:
    registry = load_json(GC_ROWS)
    return {
        (str(row["session_date"]), str(row["session_code"]))
        for row in registry["rows"]
        if int(row["expected_bucket_rows"]) > 0 and row.get("availability_disposition") == "EXPECTED_AVAILABLE"
    }


def load_gc_candidates(path: Path, contexts: Mapping[tuple[str, str], CaseContext]) -> list[dict[str, Any]]:
    rows = pq.read_table(path).to_pylist()
    output: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["session_date"]), str(row["session_code"]))
        context = contexts.get(key)
        if context is None or key[0] in ENGINEERING_DATES or row["event_family"] not in GC_FAMILIES or row.get("quality_state") != "ELIGIBLE":
            continue
        decision = parse_dt(str(row["decision_at_utc"]))
        start, end = session_bounds(context)
        if not start <= decision <= end:
            continue
        item = candidate(
            str(row["event_family"]), str(row["directional_prior"]), decision,
            (str(row["event_id"]), str(row["confirmation_evidence"]), str(row["lineage_hash"])),
            source_domain="GC_MICROSTRUCTURE", source_event_id=str(row["event_id"]),
        )
        item["session_date"] = key[0]
        item["session_code"] = key[1]
        output.append(item)
    return sorted(output, key=lambda item: (item["decision"], item["family"], item["direction"], item["source_event_id"]))


def truth_for_direction(state: str, direction: str, bullish: str, bearish: str) -> str:
    if state == "UNKNOWN":
        return "UNKNOWN"
    return "TRUE" if (direction == "UP" and state == bullish) or (direction == "DOWN" and state == bearish) else "FALSE"


def build_event_rows(
    contexts: Sequence[CaseContext],
    bars_by_key: Mapping[tuple[str, str], Mapping[datetime, Bar]],
    gc_path: Path,
    implementation: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context_by_key = {(item.session_date, item.session_code): item for item in contexts}
    covered = gc_coverage_keys()
    raw_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    diagnostics = Counter()
    for context in contexts:
        key = (context.session_date, context.session_code)
        bars = bars_by_key[key]
        five = five_minute_bars(bars, history_start(context), context.session_open + timedelta(hours=3))
        level = level_candidates_primary(context, bars) if implementation == "primary" else level_candidates_reference(context, bars)
        structure = structure_candidates(context, five, implementation)
        compression = compression_candidates(context, five, implementation)
        raw_by_key[key].extend(canonicalize_xau_candidates([*level, *structure, *compression]))
        diagnostics["raw_xau_candidates"] += len(level) + len(structure) + len(compression)
        diagnostics["canonical_xau_candidates"] += len(raw_by_key[key])
    for item in load_gc_candidates(gc_path, context_by_key):
        key = (str(item.pop("session_date")), str(item.pop("session_code")))
        if key not in context_by_key:
            raise ValueError(f"GC event did not map to a research session: {item['source_event_id']} {key}")
        raw_by_key[key].append(item)
        diagnostics["canonical_gc_candidates"] += 1

    provisional: list[dict[str, Any]] = []
    for key in sorted(raw_by_key):
        context = context_by_key[key]
        bars = bars_by_key[key]
        five = five_minute_bars(bars, history_start(context), context.session_open + timedelta(hours=3))
        for item in sorted(raw_by_key[key], key=lambda value: (value["decision"], value["family"], value["direction"], value.get("source_event_id", ""), value["evidence"])):
            decision = item["decision"]
            anchor = bars.get(decision - timedelta(minutes=1))
            atr = atr_at(five, decision)
            if anchor is None or anchor.close_at != decision or atr is None:
                diagnostics["technical_unavailable_event_candidates"] += 1
                continue
            levels = tuple(item.get("level_families", ()))
            evidence_hash = canonical_hash(item["evidence"])
            source_event_id = str(item.get("source_event_id") or canonical_hash([context.case_id, item["family"], item["direction"], iso_z(decision), evidence_hash]))
            event_id = canonical_hash([context.case_id, item["family"], item["direction"], iso_z(decision), levels, evidence_hash, source_event_id])
            macro = truth_for_direction(context.macro_state, item["direction"], "BULLISH", "BEARISH")
            real_usd = truth_for_direction(context.real_usd_state, item["direction"], "GOLD_BULLISH", "GOLD_BEARISH")
            structure = truth_for_direction(context.structure_state, item["direction"], "BULLISH", "BEARISH")
            provisional.append({
                "event_id": event_id, "source_event_id": source_event_id, "case_id": context.case_id,
                "session_date": context.session_date, "session_code": context.session_code, "iso_week": context.iso_week,
                "event_family": item["family"], "source_domain": item["source_domain"], "direction": item["direction"],
                "decision_at_utc": iso_z(decision), "anchor_open_utc": iso_z(anchor.open_at),
                "anchor_close_e8": anchor.close_e8, "atr20_5m_e8": atr,
                "level_families_json": json.dumps(list(levels), separators=(",", ":")), "evidence_hash": evidence_hash,
                "macro_state": context.macro_state, "real_usd_state": context.real_usd_state,
                "session_open_structure_state": context.structure_state,
                "gc_covered": key in covered, "context__MACRO_CONCORDANT": macro,
                "context__MACRO_REAL_USD_CONCORDANT": "TRUE" if macro == real_usd == "TRUE" else "UNKNOWN" if "UNKNOWN" in {macro, real_usd} else "FALSE",
                "context__SESSION_OPEN_STRUCTURE_CONCORDANT": structure,
                "context__GC_CONFIRMING_WITHIN_5M": "UNKNOWN", "lineage_hash": "",
            })

    gc_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in provisional:
        if row["source_domain"] == "GC_MICROSTRUCTURE":
            gc_by_key[(row["session_date"], row["session_code"])].append(row)
    for row in provisional:
        key = (row["session_date"], row["session_code"])
        if not row["gc_covered"]:
            state = "UNKNOWN"
        else:
            decision = parse_dt(row["decision_at_utc"])
            confirmations = [
                other for other in gc_by_key.get(key, [])
                if other["event_id"] != row["event_id"] and other["direction"] == row["direction"]
                and decision - timedelta(minutes=5) <= parse_dt(other["decision_at_utc"]) <= decision
                and (row["source_domain"] != "GC_MICROSTRUCTURE" or other["event_family"] != row["event_family"])
            ]
            state = "TRUE" if confirmations else "FALSE"
        row["context__GC_CONFIRMING_WITHIN_5M"] = state
        row["lineage_hash"] = canonical_hash({**row, "lineage_hash": ""})
    provisional.sort(key=lambda row: (row["session_date"], row["session_code"], row["decision_at_utc"], row["event_family"], row["direction"], row["event_id"]))
    if len({row["event_id"] for row in provisional}) != len(provisional):
        raise ValueError("Duplicate event IDs")
    diagnostics.update({
        "event_rows": len(provisional),
        "london_event_rows": sum(row["session_code"] == "LONDON" for row in provisional),
        "new_york_event_rows": sum(row["session_code"] == "NEW_YORK" for row in provisional),
        "gc_covered_session_keys": len(covered),
    })
    return provisional, dict(sorted(diagnostics.items()))


def event_support_snapshot(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {"stage1": [], "stage2": []}
    for session in SESSIONS:
        for family in EVENT_FAMILIES:
            selected = [row for row in rows if row["session_code"] == session and row["event_family"] == family]
            output["stage1"].append({
                "session": session, "event_family": family, "events": len(selected),
                "dates": len({row["session_date"] for row in selected}),
                "weeks": len({row["iso_week"] for row in selected}),
                "up_events": sum(row["direction"] == "UP" for row in selected),
                "down_events": sum(row["direction"] == "DOWN" for row in selected),
            })
            for context in CONTEXTS:
                condition = [row for row in selected if row[f"context__{context}"] == "TRUE"]
                comparison = [row for row in selected if row[f"context__{context}"] == "FALSE"]
                output["stage2"].append({
                    "session": session, "event_family": family, "context": context,
                    "condition_events": len(condition), "comparison_events": len(comparison),
                    "condition_dates": len({row["session_date"] for row in condition}),
                    "comparison_dates": len({row["session_date"] for row in comparison}),
                    "unknown_events": len(selected) - len(condition) - len(comparison),
                })
    output["receipt"] = canonical_hash(output)
    return output


def event_rows_checksum(rows: Sequence[Mapping[str, Any]]) -> str:
    return canonical_hash([dict(row) for row in rows])


def materialize_preoutcome() -> dict[str, Any]:
    verify_design()
    if OUTPUT.exists() or PREOUTCOME_FREEZE.exists() or REPORT.exists():
        raise FileExistsError("State-transition V1 output already exists")
    OUTPUT.mkdir(parents=True)
    write_json_exclusive(OUTPUT / "attempt_started.json", {
        "version": "GC_SESSION_STATE_TRANSITION_V1_ATTEMPT_1_0", "started_at_utc": utc_now(),
        "status": "STARTED_AFTER_DESIGN_FREEZE", "outcomes_opened": False,
    })
    contexts, context_diagnostics = load_case_contexts()
    bars, price_diagnostics = load_preoutcome_bars(contexts)
    primary, primary_diagnostics = build_event_rows(contexts, bars, GC_PRIMARY, "primary")
    reference, reference_diagnostics = build_event_rows(contexts, bars, GC_REFERENCE, "reference")
    primary_checksum, reference_checksum = event_rows_checksum(primary), event_rows_checksum(reference)
    if primary != reference or primary_checksum != reference_checksum:
        failure = {
            "version": "GC_SESSION_STATE_TRANSITION_V1_PREOUTCOME_FAILURE_1_0",
            "status": "FAIL_EVENT_REPRODUCTION_BEFORE_OUTCOME_ACCESS",
            "primary_rows": len(primary), "reference_rows": len(reference),
            "primary_checksum": primary_checksum, "reference_checksum": reference_checksum,
            "outcomes_opened": False, "year_2025_or_2026_accessed": False,
        }
        write_json_exclusive(OUTPUT / "preoutcome_failure.json", failure)
        raise RuntimeError(failure["status"])
    write_parquet_exclusive(OUTPUT / "primary_events.parquet", primary, EVENT_SCHEMA)
    write_parquet_exclusive(OUTPUT / "reference_events.parquet", reference, EVENT_SCHEMA)
    support = event_support_snapshot(primary)
    write_json_exclusive(OUTPUT / "preoutcome_support_snapshot.json", support)
    diagnostics = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_MATERIALIZATION_DIAGNOSTICS_1_0",
        "status": "PASS_POINT_IN_TIME_EVENT_MATERIALIZATION_REPRODUCTION",
        "context": context_diagnostics, "price": price_diagnostics,
        "primary": primary_diagnostics, "reference": reference_diagnostics,
        "primary_reference_event_rows_exact": True,
        "primary_reference_event_checksum": primary_checksum,
        "outcomes_opened_or_joined": False, "year_2025_or_2026_accessed": False,
    }
    write_json_exclusive(OUTPUT / "materialization_diagnostics.json", diagnostics)
    controls = {
        "contract": file_record(CONTRACT), "protocol": file_record(PROTOCOL),
        "test_registry": file_record(TEST_REGISTRY), "design_freeze": file_record(DESIGN_FREEZE),
        "implementation": file_record(Path(__file__).resolve()),
        "primary_events": file_record(OUTPUT / "primary_events.parquet"),
        "reference_events": file_record(OUTPUT / "reference_events.parquet"),
        "support_snapshot": file_record(OUTPUT / "preoutcome_support_snapshot.json"),
        "materialization_diagnostics": file_record(OUTPUT / "materialization_diagnostics.json"),
    }
    freeze: dict[str, Any] = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_PREOUTCOME_FREEZE_1_0",
        "status": "SEALED_EXACT_EVENT_POPULATION_AND_IMPLEMENTATION_BEFORE_OUTCOMES",
        "sealed_at_utc": utc_now(), "controls": controls,
        "population": {
            "research_sessions": len(contexts), "event_rows": len(primary),
            "event_ids_checksum": canonical_hash([row["event_id"] for row in primary]),
            "event_rows_checksum": primary_checksum,
            "first_session_date": contexts[0].session_date, "last_session_date": contexts[-1].session_date,
        },
        "outcome_values_accessed": False, "relationships_calculated": False,
        "year_2025_or_2026_accessed": False, "data_acquired": False, "charge_incurred_usd": 0.0,
    }
    freeze["freeze_receipt"] = canonical_hash(freeze)
    write_json_exclusive(PREOUTCOME_FREEZE, freeze)
    write_json_exclusive(OUTPUT / "preoutcome_readiness.json", {
        "version": "GC_SESSION_STATE_TRANSITION_V1_PREOUTCOME_READINESS_1_0",
        "status": "PASS_READY_FOR_SINGLE_CONTROLLED_DEVELOPMENT_OUTCOME_OPENING",
        "completed_at_utc": utc_now(), "preoutcome_freeze": file_record(PREOUTCOME_FREEZE),
        "event_rows": len(primary), "outcomes_opened": False,
    })
    return freeze


def verify_preoutcome() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    verify_design()
    freeze = load_json(PREOUTCOME_FREEZE)
    if freeze.get("status") != "SEALED_EXACT_EVENT_POPULATION_AND_IMPLEMENTATION_BEFORE_OUTCOMES":
        raise ValueError("Pre-outcome freeze missing")
    for name, path in (
        ("contract", CONTRACT), ("protocol", PROTOCOL), ("test_registry", TEST_REGISTRY),
        ("design_freeze", DESIGN_FREEZE), ("implementation", Path(__file__).resolve()),
        ("primary_events", OUTPUT / "primary_events.parquet"),
        ("reference_events", OUTPUT / "reference_events.parquet"),
        ("support_snapshot", OUTPUT / "preoutcome_support_snapshot.json"),
        ("materialization_diagnostics", OUTPUT / "materialization_diagnostics.json"),
    ):
        if sha256_file(path) != freeze["controls"][name]["sha256"]:
            raise ValueError(f"Pre-outcome bound artifact changed: {name}")
    primary = pq.read_table(OUTPUT / "primary_events.parquet").to_pylist()
    reference = pq.read_table(OUTPUT / "reference_events.parquet").to_pylist()
    if primary != reference or event_rows_checksum(primary) != freeze["population"]["event_rows_checksum"]:
        raise ValueError("Sealed event population no longer reproduces")
    return freeze, primary


def load_outcome_bars(events: Sequence[Mapping[str, Any]]) -> tuple[dict[datetime, Bar], dict[str, Any]]:
    targets: set[datetime] = set()
    for event in events:
        decision = parse_dt(str(event["decision_at_utc"]))
        targets.add(decision - timedelta(minutes=1))
        targets.update(decision + timedelta(minutes=index) for index in range(120))
    found: dict[datetime, Bar] = {}
    source_rows = selected = duplicates = invalid = 0
    saw_one_minute = False
    with gzip.open(PRICE_PATH, "rt", encoding="utf-8") as handle:
        for line in handle:
            if HOLDOUT_RE.search(line):
                break
            record = json.loads(line)
            timeframe = record.get("timeframe")
            if timeframe != "1m":
                if saw_one_minute:
                    break
                continue
            saw_one_minute = True
            if record.get("instrument_code") != "XAUUSD":
                continue
            source_rows += 1
            opened = parse_dt(str(record["open_time"]))
            if opened not in targets:
                continue
            bar = bar_from_record(record)
            if bar is None:
                invalid += 1
                continue
            if opened in found:
                duplicates += 1
                continue
            found[opened] = bar
            selected += 1
    return found, {
        "logical_source_opening_count": 1,
        "source_1m_rows_deserialized_before_2025": source_rows,
        "target_timestamps": len(targets), "found_timestamps": selected,
        "missing_timestamps": len(targets.difference(found)), "duplicates": duplicates,
        "invalid_target_rows": invalid, "first_2025_or_2026_row_deserialized": False,
    }


def passage_for_path(event: Mapping[str, Any], path: Sequence[Bar], implementation: str) -> tuple[str, int]:
    anchor, atr = int(event["anchor_close_e8"]), int(event["atr20_5m_e8"])
    direction = str(event["direction"])
    if implementation == "primary":
        favorable_at: int | None = None
        adverse_at: int | None = None
        for index, bar in enumerate(path):
            favorable = bar.high_e8 >= anchor + atr if direction == "UP" else bar.low_e8 <= anchor - atr
            adverse = bar.low_e8 <= anchor - atr if direction == "UP" else bar.high_e8 >= anchor + atr
            if favorable and favorable_at is None:
                favorable_at = index
            if adverse and adverse_at is None:
                adverse_at = index
            if favorable_at is not None or adverse_at is not None:
                if favorable and adverse:
                    return "BOTH_SAME_BAR", 0
                if favorable_at is not None and adverse_at is None:
                    return "FAVORABLE_FIRST", 1
                if adverse_at is not None and favorable_at is None:
                    return "ADVERSE_FIRST", -1
        return "NEITHER", 0
    highs = np.asarray([bar.high_e8 for bar in path], dtype=np.int64)
    lows = np.asarray([bar.low_e8 for bar in path], dtype=np.int64)
    fav_mask = highs >= anchor + atr if direction == "UP" else lows <= anchor - atr
    adv_mask = lows <= anchor - atr if direction == "UP" else highs >= anchor + atr
    fav_indices, adv_indices = np.flatnonzero(fav_mask), np.flatnonzero(adv_mask)
    if not len(fav_indices) and not len(adv_indices):
        return "NEITHER", 0
    fav = int(fav_indices[0]) if len(fav_indices) else math.inf
    adv = int(adv_indices[0]) if len(adv_indices) else math.inf
    return ("BOTH_SAME_BAR", 0) if fav == adv else ("FAVORABLE_FIRST", 1) if fav < adv else ("ADVERSE_FIRST", -1)


def calculate_outcomes(events: Sequence[Mapping[str, Any]], bars: Mapping[datetime, Bar], implementation: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        decision = parse_dt(str(event["decision_at_utc"]))
        anchor = bars.get(decision - timedelta(minutes=1))
        if anchor is None or anchor.close_at != decision or anchor.close_e8 != int(event["anchor_close_e8"]):
            raise ValueError(f"Frozen event anchor failed: {event['event_id']}")
        row = dict(event)
        lineage: dict[str, Any] = {"event_id": event["event_id"], "anchor_record_hash": anchor.record_hash, "horizons": {}}
        paths: dict[int, list[Bar] | None] = {}
        for horizon in (30, 60, 120):
            expected = [decision + timedelta(minutes=index) for index in range(horizon)]
            values = [bars.get(stamp) for stamp in expected]
            valid = not any(value is None for value in values)
            typed = [value for value in values if value is not None]
            valid = valid and all(left.close_at == right.open_at for left, right in zip(typed, typed[1:]))
            paths[horizon] = typed if valid else None
            row[f"path_quality_{horizon}m"] = "VALID" if valid else "UNKNOWN_MISSING_OR_INVALID_BAR"
            if valid:
                state, score = passage_for_path(event, typed, implementation)
                row[f"first_passage_{horizon}m"] = state
                row[f"score_{horizon}m"] = score
                lineage["horizons"][str(horizon)] = canonical_hash([item.record_hash for item in typed])
            else:
                row[f"first_passage_{horizon}m"] = "UNKNOWN"
                row[f"score_{horizon}m"] = None
                lineage["horizons"][str(horizon)] = "UNKNOWN"
        path60 = paths[60]
        if path60 is None:
            row["favorable_excursion_atr_60m"] = None
            row["adverse_excursion_atr_60m"] = None
            row["path_dominance_atr_60m"] = None
        else:
            anchor_value, atr = int(event["anchor_close_e8"]), int(event["atr20_5m_e8"])
            if event["direction"] == "UP":
                favorable = max(item.high_e8 for item in path60) - anchor_value
                adverse = anchor_value - min(item.low_e8 for item in path60)
            else:
                favorable = anchor_value - min(item.low_e8 for item in path60)
                adverse = max(item.high_e8 for item in path60) - anchor_value
            fav = round(favorable / atr, 12)
            adv = round(adverse / atr, 12)
            row["favorable_excursion_atr_60m"] = 0.0 if fav == 0 else fav
            row["adverse_excursion_atr_60m"] = 0.0 if adv == 0 else adv
            dominance = round(fav - adv, 12)
            row["path_dominance_atr_60m"] = 0.0 if dominance == 0 else dominance
        row["outcome_lineage_hash"] = canonical_hash(lineage)
        rows.append(row)
    rows.sort(key=lambda row: (row["session_date"], row["session_code"], row["decision_at_utc"], row["event_family"], row["direction"], row["event_id"]))
    return rows


def support_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    directions = {}
    for direction in ("UP", "DOWN"):
        selected = [row for row in rows if row["direction"] == direction]
        directions[direction] = {"events": len(selected), "dates": len({row["session_date"] for row in selected})}
    years = {
        str(year): len({row["session_date"] for row in rows if str(row["session_date"]).startswith(str(year))})
        for year in (2021, 2022, 2023, 2024)
    }
    return {
        "events": len(rows), "dates": len({row["session_date"] for row in rows}),
        "iso_weeks": len({row["iso_week"] for row in rows}), "directions": directions,
        "year_dates": years,
    }


def stage1_support(counts: Mapping[str, Any]) -> tuple[bool, list[str]]:
    failed: list[str] = []
    if counts["events"] < 100: failed.append("EVENTS_LT_100")
    if counts["dates"] < 80: failed.append("DATES_LT_80")
    if counts["iso_weeks"] < 24: failed.append("ISO_WEEKS_LT_24")
    for direction in ("UP", "DOWN"):
        if counts["directions"][direction]["events"] < 30: failed.append(f"{direction}_EVENTS_LT_30")
        if counts["directions"][direction]["dates"] < 25: failed.append(f"{direction}_DATES_LT_25")
    for year in (2022, 2023, 2024):
        if counts["year_dates"][str(year)] < 12: failed.append(f"YEAR_{year}_DATES_LT_12")
    return not failed, failed


def stage2_support(condition: Mapping[str, Any], comparison: Mapping[str, Any]) -> tuple[bool, list[str]]:
    failed: list[str] = []
    if condition["events"] < 50: failed.append("CONDITION_EVENTS_LT_50")
    if condition["dates"] < 40: failed.append("CONDITION_DATES_LT_40")
    if condition["iso_weeks"] < 16: failed.append("CONDITION_WEEKS_LT_16")
    if comparison["events"] < 75: failed.append("COMPARISON_EVENTS_LT_75")
    if comparison["dates"] < 60: failed.append("COMPARISON_DATES_LT_60")
    if comparison["iso_weeks"] < 20: failed.append("COMPARISON_WEEKS_LT_20")
    for direction in ("UP", "DOWN"):
        if condition["directions"][direction]["events"] < 15: failed.append(f"CONDITION_{direction}_EVENTS_LT_15")
        if condition["directions"][direction]["dates"] < 12: failed.append(f"CONDITION_{direction}_DATES_LT_12")
    for year in (2022, 2023, 2024):
        if condition["year_dates"][str(year)] < 8: failed.append(f"CONDITION_YEAR_{year}_DATES_LT_8")
    return not failed, failed


def cluster_ols(rows: Sequence[Mapping[str, Any]], stage: int, context: str | None, implementation: str) -> dict[str, float | int | None]:
    ordered = sorted(rows, key=lambda row: (row["session_date"], row["decision_at_utc"], row["event_id"]))
    y = np.asarray([float(row["score_60m"]) for row in ordered], dtype=np.float64)
    if stage == 1:
        x = np.ones((len(ordered), 1), dtype=np.float64)
        coefficient_index = 0
    else:
        assert context is not None
        condition = np.asarray([1.0 if row[f"context__{context}"] == "TRUE" else 0.0 for row in ordered], dtype=np.float64)
        x = np.column_stack((np.ones(len(ordered), dtype=np.float64), condition))
        coefficient_index = 1
    xtx = x.T @ x
    inverse = np.linalg.inv(xtx) if implementation == "primary" else np.linalg.solve(xtx, np.eye(xtx.shape[0]))
    beta = inverse @ x.T @ y
    residual = y - x @ beta
    groups = sorted({str(row["session_date"]) for row in ordered})
    meat = np.zeros((x.shape[1], x.shape[1]), dtype=np.float64)
    for group in groups:
        mask = np.asarray([str(row["session_date"]) == group for row in ordered], dtype=bool)
        score = x[mask].T @ residual[mask]
        meat += np.outer(score, score)
    n, k, g = len(ordered), x.shape[1], len(groups)
    correction = (g / (g - 1)) * ((n - 1) / (n - k))
    covariance = correction * inverse @ meat @ inverse
    variance = max(0.0, float(covariance[coefficient_index, coefficient_index]))
    standard_error = math.sqrt(variance)
    coefficient = float(beta[coefficient_index])
    statistic = coefficient / standard_error if standard_error > 0 else math.inf if coefficient > 0 else -math.inf
    p_value = 0.0 if statistic == math.inf else 1.0 if statistic == -math.inf else 1.0 - NormalDist().cdf(statistic)
    return {
        "coefficient": round(coefficient, 12), "cluster_standard_error": round(standard_error, 12),
        "one_sided_p": round(max(0.0, min(1.0, p_value)), 12), "clusters": g, "observations": n,
    }


def percentile_interval(values: np.ndarray[Any, Any]) -> list[float]:
    lower, upper = np.quantile(values, [0.025, 0.975], method="linear")
    return [round(float(lower), 12), round(float(upper), 12)]


def bootstrap_metrics(
    rows: Sequence[Mapping[str, Any]], stage: int, context: str | None, seed: int,
) -> dict[str, Any]:
    dates = sorted({str(row["session_date"]) for row in rows})
    index_by_date = {value: index for index, value in enumerate(dates)}
    clusters = np.asarray([index_by_date[str(row["session_date"])] for row in rows], dtype=np.int64)
    scores = np.asarray([float(row["score_60m"]) for row in rows], dtype=np.float64)
    dominance = np.asarray([float(row["path_dominance_atr_60m"]) for row in rows], dtype=np.float64)
    if stage == 1:
        condition = np.ones(len(rows), dtype=bool)
        comparison = np.zeros(len(rows), dtype=bool)
    else:
        assert context is not None
        condition = np.asarray([row[f"context__{context}"] == "TRUE" for row in rows], dtype=bool)
        comparison = np.asarray([row[f"context__{context}"] == "FALSE" for row in rows], dtype=bool)
    g = len(dates)
    sum_condition = np.bincount(clusters[condition], weights=scores[condition], minlength=g)
    count_condition = np.bincount(clusters[condition], minlength=g)
    sum_comparison = np.bincount(clusters[comparison], weights=scores[comparison], minlength=g)
    count_comparison = np.bincount(clusters[comparison], minlength=g)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, g, size=(5000, g), dtype=np.int32)
    condition_means = sum_condition[draws].sum(axis=1) / count_condition[draws].sum(axis=1)
    if stage == 2:
        comparison_means = sum_comparison[draws].sum(axis=1) / count_comparison[draws].sum(axis=1)
        lifts = condition_means - comparison_means
    else:
        lifts = np.full(5000, np.nan)
    dom_by_cluster = [dominance[condition & (clusters == index)] for index in range(g)]
    medians = np.empty(5000, dtype=np.float64)
    for index, draw in enumerate(draws):
        values = [dom_by_cluster[int(cluster)] for cluster in draw if len(dom_by_cluster[int(cluster)])]
        medians[index] = float(np.median(np.concatenate(values)))
    return {
        "resamples": 5000,
        "condition_absolute_effect_ci95": percentile_interval(condition_means),
        "lift_ci95": None if stage == 1 else percentile_interval(lifts),
        "condition_median_path_dominance_ci95": percentile_interval(medians),
        "bootstrap_checksum": canonical_hash({
            "condition": [round(float(value), 12) for value in condition_means],
            "lift": None if stage == 1 else [round(float(value), 12) for value in lifts],
            "median": [round(float(value), 12) for value in medians],
        }),
    }


def effect_for(rows: Sequence[Mapping[str, Any]], stage: int, context: str | None, horizon: int = 60) -> float | None:
    available = [row for row in rows if row.get(f"score_{horizon}m") is not None]
    if not available:
        return None
    if stage == 1:
        return round(float(np.mean([row[f"score_{horizon}m"] for row in available])), 12)
    assert context is not None
    condition = [row[f"score_{horizon}m"] for row in available if row[f"context__{context}"] == "TRUE"]
    comparison = [row[f"score_{horizon}m"] for row in available if row[f"context__{context}"] == "FALSE"]
    if not condition or not comparison:
        return None
    return round(float(np.mean(condition) - np.mean(comparison)), 12)


def stability_metrics(rows: Sequence[Mapping[str, Any]], stage: int, context: str | None, overall_effect: float) -> dict[str, Any]:
    annual: dict[str, Any] = {}
    annual_pass = True
    for year in (2021, 2022, 2023, 2024):
        selected = [row for row in rows if str(row["session_date"]).startswith(str(year))]
        value = effect_for(selected, stage, context)
        if stage == 1:
            adequate = len({row["session_date"] for row in selected}) >= (12 if year >= 2022 else 1)
        else:
            assert context is not None
            cond_dates = len({row["session_date"] for row in selected if row[f"context__{context}"] == "TRUE"})
            comp_dates = len({row["session_date"] for row in selected if row[f"context__{context}"] == "FALSE"})
            adequate = cond_dates >= (8 if year >= 2022 else 1) and comp_dates >= (8 if year >= 2022 else 1)
        annual[str(year)] = {"effect": value, "adequate": adequate}
        if year >= 2022 and (not adequate or value is None or value <= 0):
            annual_pass = False
    dates = sorted({str(row["session_date"]) for row in rows})
    blocks: list[dict[str, Any]] = []
    for number, date_values in enumerate(np.array_split(np.asarray(dates, dtype=object), 4), start=1):
        date_set = {str(value) for value in date_values.tolist()}
        selected = [row for row in rows if row["session_date"] in date_set]
        value = effect_for(selected, stage, context)
        if stage == 1:
            adequate = len(date_set) >= 10
        else:
            assert context is not None
            adequate = len({row["session_date"] for row in selected if row[f"context__{context}"] == "TRUE"}) >= 5 and len({row["session_date"] for row in selected if row[f"context__{context}"] == "FALSE"}) >= 5
        blocks.append({"block": number, "first_date": min(date_set) if date_set else None, "last_date": max(date_set) if date_set else None, "effect": value, "adequate": adequate})
    adequate_blocks = [item for item in blocks if item["adequate"] and item["effect"] is not None]
    block_pass = sum(float(item["effect"]) > 0 for item in adequate_blocks) >= 3 and all(float(item["effect"]) > -0.05 for item in adequate_blocks)
    directional: dict[str, Any] = {}
    direction_pass = True
    for direction in ("UP", "DOWN"):
        selected = [row for row in rows if row["direction"] == direction]
        if stage == 1:
            value = effect_for(selected, 1, None)
        else:
            assert context is not None
            condition = [row for row in selected if row[f"context__{context}"] == "TRUE"]
            value = round(float(np.mean([row["score_60m"] for row in condition])), 12) if condition else None
        directional[direction] = value
        if value is None or value <= 0:
            direction_pass = False
    earliest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in sorted(rows, key=lambda item: (item["decision_at_utc"], item["event_id"])):
        earliest.setdefault((str(row["session_date"]), str(row["event_family"])), row)
    first_rows = list(earliest.values())
    first_effect = effect_for(first_rows, stage, context)
    first_pass = first_effect is not None and first_effect > 0 and first_effect >= 0.5 * overall_effect
    diagnostics = {str(horizon): effect_for(rows, stage, context, horizon) for horizon in (30, 120)}
    diagnostic_pass = all(value is None or value > -0.05 for value in diagnostics.values())
    return {
        "annual": annual, "annual_pass": annual_pass, "chronological_blocks": blocks,
        "block_pass": block_pass, "directional_effects": directional,
        "directional_symmetry_pass": direction_pass, "first_event_effect": first_effect,
        "first_event_ratio": None if overall_effect == 0 or first_effect is None else round(first_effect / overall_effect, 12),
        "first_event_pass": first_pass, "diagnostic_effects": diagnostics,
        "diagnostic_pass": diagnostic_pass,
    }


def test_seed(session: str, stage: int, test_id: str) -> int:
    raw = f"GC_SESSION_STATE_TRANSITION_EDGE_DISCOVERY_V1_0|{session}|S{stage}|{test_id}|SESSION_DATE_CLUSTER_BOOTSTRAP"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)


def evaluate_test(test: Mapping[str, Any], all_rows: Sequence[Mapping[str, Any]], implementation: str) -> dict[str, Any]:
    session, family, stage = str(test["session"]), str(test["event_family"]), int(test["stage"])
    context = str(test["context"]) if test.get("context") is not None else None
    family_rows = [
        row for row in all_rows
        if row["session_code"] == session and row["event_family"] == family and row["score_60m"] is not None
        and row["path_dominance_atr_60m"] is not None
    ]
    if stage == 1:
        analysis_rows = family_rows
        support = {"population": support_counts(analysis_rows)}
        eligible, support_failures = stage1_support(support["population"])
    else:
        assert context is not None
        analysis_rows = [row for row in family_rows if row[f"context__{context}"] in {"TRUE", "FALSE"}]
        condition = [row for row in analysis_rows if row[f"context__{context}"] == "TRUE"]
        comparison = [row for row in analysis_rows if row[f"context__{context}"] == "FALSE"]
        support = {"condition": support_counts(condition), "comparison": support_counts(comparison), "unknown_events": len(family_rows) - len(analysis_rows)}
        eligible, support_failures = stage2_support(support["condition"], support["comparison"])
    base: dict[str, Any] = {
        "test_id": str(test["test_id"]), "session": session, "stage": stage,
        "event_family": family, "context": context, "support": support,
        "support_eligible": eligible, "support_failures": support_failures,
        "raw_p": None, "bh_q": None, "verdict": "SUPPORT_FAIL" if not eligible else "PENDING_MULTIPLICITY",
        "failed_gates": list(support_failures),
    }
    if not eligible:
        return base
    effect = effect_for(analysis_rows, stage, context)
    assert effect is not None
    if stage == 1:
        condition_rows = analysis_rows
        condition_mean = effect
        lift = None
    else:
        assert context is not None
        condition_rows = [row for row in analysis_rows if row[f"context__{context}"] == "TRUE"]
        condition_mean = round(float(np.mean([row["score_60m"] for row in condition_rows])), 12)
        lift = effect
    favorable = sum(row["first_passage_60m"] == "FAVORABLE_FIRST" for row in condition_rows)
    adverse = sum(row["first_passage_60m"] == "ADVERSE_FIRST" for row in condition_rows)
    incidence_pp = round(100.0 * (favorable - adverse) / len(condition_rows), 12)
    median_dominance = round(float(np.median([row["path_dominance_atr_60m"] for row in condition_rows])), 12)
    ols = cluster_ols(analysis_rows, stage, context, implementation)
    bootstrap = bootstrap_metrics(analysis_rows, stage, context, test_seed(session, stage, str(test["test_id"])))
    stability = stability_metrics(analysis_rows, stage, context, effect)
    gates = {
        "condition_mean_at_least_0p10": condition_mean >= 0.10,
        "lift_at_least_0p10": True if stage == 1 else float(lift) >= 0.10,
        "absolute_effect_ci_lower_positive": bootstrap["condition_absolute_effect_ci95"][0] > 0,
        "lift_ci_lower_positive": True if stage == 1 else bootstrap["lift_ci95"][0] > 0,
        "median_path_dominance_positive": median_dominance > 0,
        "median_path_dominance_ci_lower_positive": bootstrap["condition_median_path_dominance_ci95"][0] > 0,
        "favorable_minus_adverse_incidence_at_least_10pp": incidence_pp >= 10.0,
        "annual_stability": stability["annual_pass"],
        "chronological_block_stability": stability["block_pass"],
        "directional_symmetry": stability["directional_symmetry_pass"],
        "first_event_robustness": stability["first_event_pass"],
        "horizon_consistency": stability["diagnostic_pass"],
        "bh_q_at_most_0p05": None,
    }
    base.update({
        "analysis_events": len(analysis_rows), "condition_events": len(condition_rows),
        "condition_mean_score": condition_mean, "primary_effect": effect, "stage2_lift": lift,
        "favorable_first": favorable, "adverse_first": adverse,
        "favorable_minus_adverse_incidence_pp": incidence_pp,
        "condition_median_path_dominance": median_dominance,
        "cluster_ols": ols, "raw_p": ols["one_sided_p"], "bootstrap": bootstrap,
        "stability": stability, "gates": gates,
    })
    return base


def bh_adjust(results: Sequence[dict[str, Any]]) -> None:
    for session in SESSIONS:
        for stage in (1, 2):
            selected = [row for row in results if row["session"] == session and row["stage"] == stage and row["support_eligible"]]
            ordered = sorted(selected, key=lambda row: (float(row["raw_p"]), row["test_id"]))
            m = len(ordered)
            running = 1.0
            for reverse_index in range(m - 1, -1, -1):
                rank = reverse_index + 1
                candidate_q = min(1.0, float(ordered[reverse_index]["raw_p"]) * m / rank)
                running = min(running, candidate_q)
                ordered[reverse_index]["bh_q"] = round(running, 12)
            for row in ordered:
                row["gates"]["bh_q_at_most_0p05"] = float(row["bh_q"]) <= 0.05


def complete_verdicts(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    bh_adjust(results)
    for row in results:
        if not row["support_eligible"]:
            continue
        failures = [name for name, passed in row["gates"].items() if passed is not True]
        row["failed_gates"] = failures
        row["all_gates_pass"] = not failures
        row["verdict"] = "PENDING_CANDIDATE_LIMIT" if not failures else "REJECT"
    candidates: dict[str, list[dict[str, Any]]] = {}
    for session in SESSIONS:
        passed = [row for row in results if row["session"] == session and row.get("all_gates_pass")]
        passed.sort(key=lambda row: (
            float(row["bh_q"]), -float(row["bootstrap"]["condition_absolute_effect_ci95"][0]),
            -float(row["primary_effect"]), -float(row["bootstrap"]["condition_median_path_dominance_ci95"][0]),
            -int(row["condition_events"]), row["test_id"],
        ))
        selected = passed[:3]
        for row in selected:
            row["verdict"] = "PROVISIONAL_UNVALIDATED_CANDIDATE"
        for row in passed[3:]:
            row["verdict"] = "REJECT"
            row["failed_gates"] = ["CANDIDATE_LIMIT_RANK"]
        candidates[session] = selected
    return candidates


def run_tests(rows: Sequence[Mapping[str, Any]], implementation: str) -> dict[str, Any]:
    registry = load_json(TEST_REGISTRY)
    results = [evaluate_test(test, rows, implementation) for test in registry["tests"]]
    candidates = complete_verdicts(results)
    payload: dict[str, Any] = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_COMPLETE_RESULTS_1_0",
        "implementation": implementation, "registered_tests": len(results),
        "support_eligible_tests": sum(row["support_eligible"] for row in results),
        "support_fail_tests": sum(not row["support_eligible"] for row in results),
        "rejected_tests": sum(row["verdict"] == "REJECT" for row in results),
        "candidate_counts": {session: len(candidates[session]) for session in SESSIONS},
        "candidate_ids": {session: [row["test_id"] for row in candidates[session]] for session in SESSIONS},
        "tests": results,
    }
    comparable = dict(payload)
    comparable.pop("implementation")
    payload["results_checksum"] = canonical_hash(comparable)
    return payload


def report_markdown(verdict: Mapping[str, Any], results: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# GC Session State-Transition Edge Discovery V1 Report",
        "",
        f"Formal status: `{verdict['status']}`",
        "",
        "This report is a development discovery result, not a backtest and not a claim of a validated trading edge. No execution, trades, PnL, R multiples, or account returns were calculated.",
        "",
        "## Research population",
        "",
        f"- Sealed event rows: **{len(rows):,}**.",
        f"- Primary-endpoint-valid event rows: **{sum(row['score_60m'] is not None for row in rows):,}**.",
        f"- Registered tests: **{results['registered_tests']}**.",
        f"- Support eligible: **{results['support_eligible_tests']}**; support failures: **{results['support_fail_tests']}**.",
        f"- Provisional London candidates: **{results['candidate_counts']['LONDON']}**.",
        f"- Provisional New York candidates: **{results['candidate_counts']['NEW_YORK']}**.",
        "- 2025/2026 accessed: **no**.",
        "",
        "## Frozen-family event counts",
        "",
        "| Session | Event family | Events | Valid 60m |",
        "|---|---|---:|---:|",
    ]
    for session in SESSIONS:
        for family in EVENT_FAMILIES:
            selected = [row for row in rows if row["session_code"] == session and row["event_family"] == family]
            lines.append(f"| {session} | {family} | {len(selected)} | {sum(row['score_60m'] is not None for row in selected)} |")
    lines.extend(["", "## Provisional candidates", ""])
    candidate_ids = {item for values in results["candidate_ids"].values() for item in values}
    candidates = [row for row in results["tests"] if row["test_id"] in candidate_ids]
    if not candidates:
        lines.append("No test passed every preregistered support, effect, uncertainty, multiplicity, stability, symmetry, first-event, and horizon gate.")
    else:
        lines.extend(["| Session | Test | Effect | q | 95% lower effect bound | Median dominance |", "|---|---|---:|---:|---:|---:|"])
        for row in candidates:
            lines.append(
                f"| {row['session']} | {row['test_id']} | {row['primary_effect']:.4f} | {row['bh_q']:.4g} | "
                f"{row['bootstrap']['condition_absolute_effect_ci95'][0]:.4f} | {row['condition_median_path_dominance']:.4f} |"
            )
    rejected = [row for row in results["tests"] if row["support_eligible"] and row["verdict"] == "REJECT"]
    rejected.sort(key=lambda row: (len(row["failed_gates"]), float(row["bh_q"]), -float(row["primary_effect"]), row["test_id"]))
    lines.extend(["", "## Closest rejected relationships", "", "These remain rejected and receive no candidate or validation credit.", "", "| Test | Effect | q | Failed gates |", "|---|---:|---:|---|"])
    for row in rejected[:10]:
        lines.append(f"| {row['test_id']} | {row['primary_effect']:.4f} | {row['bh_q']:.4g} | {', '.join(row['failed_gates'])} |")
    failure_counts = Counter(gate for row in results["tests"] for gate in row.get("failed_gates", []))
    lines.extend(["", "## Complete negative-result accounting", ""])
    for gate, count in sorted(failure_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{gate}`: {count} tests.")
    lines.extend([
        "", "## Integrity",
        "",
        "- Primary and reference event populations matched exactly.",
        "- Primary and reference first-passage and path outcomes matched exactly.",
        "- Primary and reference test results and verdict checksums matched exactly.",
        "- Every registered test, support failure, rejection, and negative result is retained in `complete_results.json`.",
        "- No new market data was acquired and no charge was incurred.",
        "",
        "## Stop",
        "",
        "The V1 development branch is sealed and stopped. Any provisional candidate requires a separately frozen forward-validation protocol; it is not authorized for execution.",
        "",
    ])
    return "\n".join(lines)


def run_discovery() -> dict[str, Any]:
    freeze, events = verify_preoutcome()
    forbidden = [
        OUTPUT / "outcome_opening_authorization.json", OUTPUT / "primary_outcomes.parquet",
        OUTPUT / "reference_outcomes.parquet", OUTPUT / "complete_results.json", OUTPUT / "verdict.json",
    ]
    if any(path.exists() for path in forbidden):
        raise FileExistsError("Development outcomes were already opened for V1")
    authorization = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_OUTCOME_OPENING_AUTHORIZATION_1_0",
        "status": "AUTHORIZED_EXACTLY_ONE_CONTROLLED_DEVELOPMENT_SOURCE_OPENING",
        "authorized_at_utc": utc_now(), "preoutcome_freeze_sha256": sha256_file(PREOUTCOME_FREEZE),
        "event_population_checksum": freeze["population"]["event_rows_checksum"],
        "source": file_record(PRICE_PATH), "opening_ordinal": 1,
        "year_2025_or_2026_access_authorized": False,
    }
    write_json_exclusive(OUTPUT / "outcome_opening_authorization.json", authorization)
    bars, opening_diagnostics = load_outcome_bars(events)
    primary_outcomes = calculate_outcomes(events, bars, "primary")
    reference_outcomes = calculate_outcomes(events, bars, "reference")
    if primary_outcomes != reference_outcomes:
        failure = {
            "version": "GC_SESSION_STATE_TRANSITION_V1_OUTCOME_FAILURE_1_0",
            "status": "FAIL_INDEPENDENT_OUTCOME_REPRODUCTION", "opening_ordinal": 1,
            "primary_checksum": canonical_hash(primary_outcomes), "reference_checksum": canonical_hash(reference_outcomes),
            "year_2025_or_2026_accessed": False,
        }
        write_json_exclusive(OUTPUT / "outcome_failure.json", failure)
        raise RuntimeError(failure["status"])
    write_parquet_exclusive(OUTPUT / "primary_outcomes.parquet", primary_outcomes, OUTCOME_SCHEMA)
    write_parquet_exclusive(OUTPUT / "reference_outcomes.parquet", reference_outcomes, OUTCOME_SCHEMA)
    if sha256_file(OUTPUT / "primary_outcomes.parquet") != sha256_file(OUTPUT / "reference_outcomes.parquet"):
        raise RuntimeError("Outcome Parquet payloads are not byte-identical")
    opening_certification = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_OUTCOME_OPENING_CERTIFICATION_1_0",
        "status": "PASS_SINGLE_CONTROLLED_DEVELOPMENT_OUTCOME_OPENING",
        "completed_at_utc": utc_now(), "opening_ordinal": 1, "diagnostics": opening_diagnostics,
        "event_rows": len(events), "primary_endpoint_valid_rows": sum(row["score_60m"] is not None for row in primary_outcomes),
        "primary_reference_exact": True, "outcome_rows_checksum": canonical_hash(primary_outcomes),
        "year_2025_or_2026_accessed": False,
    }
    write_json_exclusive(OUTPUT / "outcome_opening_certification.json", opening_certification)
    primary_results = run_tests(primary_outcomes, "primary")
    reference_results = run_tests(reference_outcomes, "reference")
    primary_comparable, reference_comparable = dict(primary_results), dict(reference_results)
    primary_comparable.pop("implementation")
    reference_comparable.pop("implementation")
    if primary_comparable != reference_comparable or primary_results["results_checksum"] != reference_results["results_checksum"]:
        failure = {
            "version": "GC_SESSION_STATE_TRANSITION_V1_RESEARCH_FAILURE_1_0",
            "status": "FAIL_INDEPENDENT_RELATIONSHIP_REPRODUCTION",
            "primary_checksum": primary_results["results_checksum"], "reference_checksum": reference_results["results_checksum"],
            "year_2025_or_2026_accessed": False,
        }
        write_json_exclusive(OUTPUT / "research_failure.json", failure)
        raise RuntimeError(failure["status"])
    write_json_exclusive(OUTPUT / "primary_complete_results.json", primary_results)
    write_json_exclusive(OUTPUT / "reference_complete_results.json", reference_results)
    complete = dict(primary_results)
    complete["independent_reproduction"] = {
        "exact": True, "primary_checksum": primary_results["results_checksum"],
        "reference_checksum": reference_results["results_checksum"],
    }
    write_json_exclusive(OUTPUT / "complete_results.json", complete)
    total_candidates = sum(complete["candidate_counts"].values())
    status = "PASS_RESEARCH_COMPLETE_PROVISIONAL_CANDIDATES_FOUND" if total_candidates else "PASS_RESEARCH_COMPLETE_ZERO_CANDIDATES"
    verdict: dict[str, Any] = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_VERDICT_1_0", "status": status,
        "completed_at_utc": utc_now(), "formal_research_completion_pass": True,
        "event_rows": len(primary_outcomes), "primary_endpoint_valid_rows": sum(row["score_60m"] is not None for row in primary_outcomes),
        "registered_tests": complete["registered_tests"], "support_eligible_tests": complete["support_eligible_tests"],
        "support_fail_tests": complete["support_fail_tests"], "rejected_tests": complete["rejected_tests"],
        "candidate_counts": complete["candidate_counts"], "candidate_ids": complete["candidate_ids"],
        "development_candidates_are_validated_edges": False,
        "primary_reference_events_outcomes_and_results_exact": True,
        "source_opening_count": 1, "data_acquired": False, "charge_incurred_usd": 0.0,
        "year_2025_or_2026_accessed": False,
        "execution_trades_pnl_r_multiples_or_returns_calculated": False,
    }
    verdict["verdict_receipt"] = canonical_hash(verdict)
    write_json_exclusive(OUTPUT / "verdict.json", verdict)
    write_text_exclusive(REPORT, report_markdown(verdict, complete, primary_outcomes))
    artifacts = [
        OUTPUT / "attempt_started.json", OUTPUT / "preoutcome_readiness.json",
        OUTPUT / "primary_events.parquet", OUTPUT / "reference_events.parquet",
        OUTPUT / "preoutcome_support_snapshot.json", OUTPUT / "materialization_diagnostics.json",
        OUTPUT / "outcome_opening_authorization.json", OUTPUT / "outcome_opening_certification.json",
        OUTPUT / "primary_outcomes.parquet", OUTPUT / "reference_outcomes.parquet",
        OUTPUT / "primary_complete_results.json", OUTPUT / "reference_complete_results.json",
        OUTPUT / "complete_results.json", OUTPUT / "verdict.json", REPORT,
    ]
    manifest: dict[str, Any] = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_MANIFEST_1_0", "status": status,
        "sealed_at_utc": utc_now(), "controls": {
            "contract": file_record(CONTRACT), "protocol": file_record(PROTOCOL),
            "test_registry": file_record(TEST_REGISTRY), "design_freeze": file_record(DESIGN_FREEZE),
            "preoutcome_freeze": file_record(PREOUTCOME_FREEZE), "implementation": file_record(Path(__file__).resolve()),
        },
        "artifacts": [file_record(path) for path in artifacts],
        "verdict_receipt": verdict["verdict_receipt"], "results_checksum": complete["results_checksum"],
        "year_2025_or_2026_accessed": False, "data_acquired": False, "charge_incurred_usd": 0.0,
    }
    manifest["manifest_receipt"] = canonical_hash(manifest)
    write_json_exclusive(OUTPUT / "manifest.json", manifest)
    final_seal: dict[str, Any] = {
        "version": "GC_SESSION_STATE_TRANSITION_V1_FINAL_SEAL_1_0", "status": status,
        "sealed_at_utc": utc_now(), "manifest": file_record(OUTPUT / "manifest.json"),
        "verdict": file_record(OUTPUT / "verdict.json"), "complete_results": file_record(OUTPUT / "complete_results.json"),
        "report": file_record(REPORT), "preoutcome_freeze": file_record(PREOUTCOME_FREEZE),
        "implementation": file_record(Path(__file__).resolve()),
    }
    final_seal["final_seal_receipt"] = canonical_hash(final_seal)
    write_json_exclusive(OUTPUT / "final_seal.json", final_seal)
    write_json_exclusive(OUTPUT / "state_v01.json", {
        "version": "GC_SESSION_STATE_TRANSITION_V1_STATE_1_0", "status": "COMPLETE_AND_STOPPED",
        "branch_verdict": status, "final_seal": file_record(OUTPUT / "final_seal.json"),
        "candidate_counts": complete["candidate_counts"], "next_step_authorized": False,
        "year_2025_or_2026_remain_locked": True,
    })
    return verdict


def selftest() -> None:
    now = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
    base = {
        "anchor_close_e8": 2000 * SCALE, "atr20_5m_e8": SCALE, "direction": "UP",
    }
    bars = [Bar(now + timedelta(minutes=i), now + timedelta(minutes=i + 1), 2000 * SCALE, 2000 * SCALE, 2000 * SCALE, 2000 * SCALE, str(i), str(i)) for i in range(3)]
    favorable = list(bars)
    favorable[1] = Bar(favorable[1].open_at, favorable[1].close_at, 2000 * SCALE, 2001 * SCALE, 2000 * SCALE, 2001 * SCALE, "f", "f")
    assert passage_for_path(base, favorable, "primary") == ("FAVORABLE_FIRST", 1)
    assert passage_for_path(base, favorable, "reference") == ("FAVORABLE_FIRST", 1)
    both = list(bars)
    both[0] = Bar(both[0].open_at, both[0].close_at, 2000 * SCALE, 2001 * SCALE, 1999 * SCALE, 2000 * SCALE, "b", "b")
    assert passage_for_path(base, both, "primary") == ("BOTH_SAME_BAR", 0)
    assert passage_for_path(base, both, "reference") == ("BOTH_SAME_BAR", 0)
    dummy = [
        {"session": "LONDON", "stage": 1, "support_eligible": True, "raw_p": p, "test_id": str(index), "gates": {"bh_q_at_most_0p05": None}}
        for index, p in enumerate((0.01, 0.02, 0.20))
    ]
    bh_adjust(dummy)
    assert [row["bh_q"] for row in dummy] == [0.03, 0.03, 0.2]
    synthetic: list[dict[str, Any]] = []
    ordinal = 0
    for year in (2022, 2023, 2024):
        start = date(year, 1, 3)
        for day_index in range(60):
            session_date = (start + timedelta(days=day_index)).isoformat()
            is_condition = day_index % 3 == 0
            direction = "UP" if day_index % 2 == 0 else "DOWN"
            score = 1 if is_condition else -1
            iso = date.fromisoformat(session_date).isocalendar()
            synthetic.append({
                "session_code": "LONDON", "session_date": session_date,
                "iso_week": f"{iso.year}-W{iso.week:02d}", "event_family": "LEVEL_SWEEP_RECLAIM",
                "direction": direction, "decision_at_utc": f"{session_date}T08:30:00Z",
                "event_id": f"SYNTHETIC_{ordinal:04d}", "score_30m": score,
                "score_60m": score, "score_120m": score,
                "path_dominance_atr_60m": 1.0 if is_condition else -0.25,
                "first_passage_60m": "FAVORABLE_FIRST" if score > 0 else "ADVERSE_FIRST",
                **{f"context__{name}": "TRUE" if is_condition else "FALSE" for name in CONTEXTS},
            })
            ordinal += 1
    synthetic_test = {
        "test_id": "LONDON|S2|LEVEL_SWEEP_RECLAIM|MACRO_CONCORDANT",
        "session": "LONDON", "stage": 2, "event_family": "LEVEL_SWEEP_RECLAIM",
        "context": "MACRO_CONCORDANT",
    }
    synthetic_result = evaluate_test(synthetic_test, synthetic, "primary")
    assert synthetic_result["support_eligible"] is True
    assert synthetic_result["condition_mean_score"] == 1.0
    assert synthetic_result["primary_effect"] == 2.0
    assert synthetic_result["bootstrap"]["lift_ci95"] == [2.0, 2.0]
    verify_design()
    print(json.dumps({"status": "PASS_SYNTHETIC_AND_SEAL_SELFTEST", "outcomes_opened": False}, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("selftest", "materialize", "discover", "all"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "selftest":
        selftest()
        return
    if args.command in {"materialize", "all"}:
        freeze = materialize_preoutcome()
        print(json.dumps({"status": freeze["status"], "event_rows": freeze["population"]["event_rows"]}, sort_keys=True))
    if args.command in {"discover", "all"}:
        verdict = run_discovery()
        print(json.dumps(verdict, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
