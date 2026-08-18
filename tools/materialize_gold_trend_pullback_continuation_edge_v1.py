from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"

CONTRACT = ROOT / "GOLD_TREND_PULLBACK_CONTINUATION_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_protocol.json"
FEATURE_REGISTRY = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_feature_registry.json"
TEST_REGISTRY = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_test_registry.json"
DESIGN_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_design_freeze.json"
PREOUTCOME_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_preoutcome_freeze.json"

CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
CASEBOOK = ARTIFACTS / "gold_casebook_v01"
PRICE = CASEBOOK / "price_bars.jsonl.gz"
FUNDAMENTALS = CASEBOOK / "fundamentals.jsonl.gz"
POSITIONING = CASEBOOK / "positioning.jsonl.gz"

PRIMARY_FEATURES = OUTPUT / "primary_features.parquet"
REFERENCE_FEATURES = OUTPUT / "reference_features.parquet"
CERTIFICATION = OUTPUT / "materialization_certification.json"
STATE = OUTPUT / "state_m2.json"

START = datetime(2021, 8, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)
SCALE = 100_000_000
TIMEFRAMES = {"15m": "M15", "1h": "H1", "4h": "H4"}
TF_SECONDS = {"M15": 900, "H1": 3600, "H4": 14_400}
NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
TOKYO = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True, slots=True)
class Bar:
    timeframe: str
    open_at: datetime
    close_at: datetime
    open_e8: int
    high_e8: int
    low_e8: int
    close_e8: int
    volume: float | None
    complete: bool
    record_hash: str


@dataclass(frozen=True, slots=True)
class DailyBar:
    trading_date: date
    open_e8: int
    high_e8: int
    low_e8: int
    close_e8: int
    completed_at: datetime
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class AsiaRange:
    local_date: date
    high_e8: int
    low_e8: int
    completed_at: datetime
    evidence_hash: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def scaled(value: Any) -> int:
    return int((Decimal(str(value)) * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def finite(value: Any) -> float | None:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if math.isfinite(output) else None


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
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


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
    table = pa.Table.from_pylist(list(rows))
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=16_384,
    )
    temporary.replace(path)


def verify_design() -> dict[str, Any]:
    freeze = json.loads(DESIGN_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_BEFORE_CONDITIONAL_FEATURE_OR_OUTCOME_ACCESS":
        raise ValueError("TPCE design freeze invalid")
    controls = {
        "contract": CONTRACT,
        "protocol": PROTOCOL,
        "feature_registry": FEATURE_REGISTRY,
        "test_registry": TEST_REGISTRY,
    }
    for name, path in controls.items():
        if sha256_file(path) != freeze["controls"][name]["sha256"]:
            raise ValueError(f"Frozen control changed: {name}")
    paths = {
        "census_pullbacks_primary": CENSUS / "primary_pullback_cases.parquet",
        "census_pullbacks_reference": CENSUS / "reference_pullback_cases.parquet",
        "census_events_primary": CENSUS / "primary_structure_events.parquet",
        "census_events_reference": CENSUS / "reference_structure_events.parquet",
        "price_bars": PRICE,
        "fundamentals": FUNDAMENTALS,
        "positioning": POSITIONING,
    }
    for name, path in paths.items():
        frozen = freeze["sources"][name]
        if path.stat().st_size != frozen["bytes"] or sha256_file(path) != frozen["sha256"]:
            raise ValueError(f"Frozen source changed: {name}")
    return freeze


def volume_value(value: Any) -> float | None:
    if isinstance(value, Mapping):
        for key in ("tick", "tick_volume", "volume", "real", "value"):
            if key in value:
                return finite(value[key])
        return None
    return finite(value)


def load_bars() -> tuple[dict[str, list[Bar]], dict[str, Any]]:
    output = {name: [] for name in TIMEFRAMES.values()}
    scanned = selected = malformed = duplicates = forward_deserialized = 0
    with gzip.open(PRICE, "rb") as handle:
        for raw in handle:
            scanned += 1
            if not any(f'"timeframe":"{tf}"'.encode() in raw for tf in TIMEFRAMES):
                continue
            if b'"open_time":"2025' in raw or b'"open_time":"2026' in raw:
                continue
            record = json.loads(raw)
            if record.get("instrument_code") != "XAUUSD" or record.get("timeframe") not in TIMEFRAMES:
                continue
            opened = parse_dt(str(record["open_time"]))
            closed = parse_dt(str(record["close_time"]))
            available = parse_dt(str(record["available_at"]))
            if closed > END or available > closed:
                malformed += 1
                continue
            ohlc = record.get("ohlc") if isinstance(record.get("ohlc"), Mapping) else {}
            if any(ohlc.get(key) is None for key in ("open", "high", "low", "close")):
                malformed += 1
                continue
            bar = Bar(
                TIMEFRAMES[str(record["timeframe"])],
                opened,
                closed,
                scaled(ohlc["open"]),
                scaled(ohlc["high"]),
                scaled(ohlc["low"]),
                scaled(ohlc["close"]),
                volume_value(record.get("volume")),
                record.get("complete") is True,
                str(record["record_hash"]),
            )
            if not (bar.low_e8 <= min(bar.open_e8, bar.close_e8) <= max(bar.open_e8, bar.close_e8) <= bar.high_e8):
                malformed += 1
                continue
            output[bar.timeframe].append(bar)
            selected += 1
    for timeframe, bars in output.items():
        bars.sort(key=lambda item: (item.close_at, item.open_at, item.record_hash))
        unique: dict[datetime, Bar] = {}
        for item in bars:
            if item.close_at in unique:
                duplicates += 1
            else:
                unique[item.close_at] = item
        output[timeframe] = list(unique.values())
    return output, {
        "source_rows_scanned": scanned,
        "selected_rows": selected,
        "malformed_rows": malformed,
        "duplicate_close_times": duplicates,
        "forward_market_rows_deserialized": forward_deserialized,
        "counts": {key: len(value) for key, value in output.items()},
        "first_close": {key: iso_z(value[0].close_at) if value else None for key, value in output.items()},
        "last_close": {key: iso_z(value[-1].close_at) if value else None for key, value in output.items()},
    }


CASE_COLUMNS = [
    "pullback_id", "timeframe", "scale", "span", "direction", "segment_id",
    "pivot_swing_id", "pivot_at_utc", "known_at_utc", "pivot_price_e8",
    "reference_event_id", "reference_level_e8", "actionable_at_known",
    "research_eligible", "decision_facts_hash",
]


EVENT_COLUMNS = [
    "event_id", "timeframe", "scale", "event_type", "direction", "event_at_utc",
    "segment_id", "broken_level_min_e8", "broken_level_max_e8", "protected_level_e8",
    "bar_component_complete", "evidence_hash",
]


def load_registry(path: Path, columns: Sequence[str]) -> list[dict[str, Any]]:
    return pq.read_table(path, columns=list(columns)).to_pylist()


def load_fundamentals() -> tuple[list[dict[str, Any]], list[datetime], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scanned = forward = malformed = 0
    with gzip.open(FUNDAMENTALS, "rt", encoding="utf-8") as handle:
        for line in handle:
            scanned += 1
            record = json.loads(line)
            if record.get("record_type") != "FUNDAMENTAL_SNAPSHOT":
                continue
            available = parse_dt(str(record["available_at"]))
            if available >= END:
                forward += 1
                continue
            engine = record.get("engine_state")
            if not isinstance(engine, Mapping):
                malformed += 1
                continue
            components = {
                str(item.get("code")): item
                for item in engine.get("components", [])
                if isinstance(item, Mapping) and item.get("code") is not None
            }
            rows.append(
                {
                    "available_at": available,
                    "record_id": str(record["record_id"]),
                    "record_hash": str(record["record_hash"]),
                    "score": finite(engine.get("directional_score")),
                    "confidence": finite(engine.get("confidence")),
                    "coverage": finite(engine.get("coverage")),
                    "regime": str(engine.get("regime_label") or "UNKNOWN"),
                    "reaction_function": str(engine.get("reaction_function") or "UNKNOWN"),
                    "event_risk": str(engine.get("event_risk") or "UNKNOWN"),
                    "components": components,
                }
            )
    rows.sort(key=lambda row: (row["available_at"], row["record_id"]))
    return rows, [row["available_at"] for row in rows], {
        "rows_scanned": scanned,
        "snapshots_selected": len(rows),
        "forward_snapshots_skipped": forward,
        "malformed_snapshots": malformed,
    }


def load_positioning() -> tuple[list[dict[str, Any]], list[datetime], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scanned = forward = malformed = 0
    with gzip.open(POSITIONING, "rt", encoding="utf-8") as handle:
        for line in handle:
            scanned += 1
            record = json.loads(line)
            available_raw = record.get("available_at") or record.get("publication_at")
            if available_raw is None:
                malformed += 1
                continue
            available = parse_dt(str(available_raw))
            if available >= END:
                forward += 1
                continue
            calculated = record.get("calculated") if isinstance(record.get("calculated"), Mapping) else {}
            inferred = record.get("inferred") if isinstance(record.get("inferred"), Mapping) else {}
            rows.append(
                {
                    "available_at": available,
                    "record_id": str(record["record_id"]),
                    "record_hash": str(record["record_hash"]),
                    "percentile": finite(calculated.get("managed_money_net_percentile")),
                    "net_change": finite(calculated.get("managed_money_net_change")),
                    "crowding": str(inferred.get("crowding_state") or "UNKNOWN"),
                    "long_liquidation": str(inferred.get("long_liquidation_risk") or "UNKNOWN"),
                    "short_covering": str(inferred.get("short_covering_risk") or "UNKNOWN"),
                }
            )
    rows.sort(key=lambda row: (row["available_at"], row["record_id"]))
    return rows, [row["available_at"] for row in rows], {
        "rows_scanned": scanned,
        "reports_selected": len(rows),
        "forward_reports_skipped": forward,
        "malformed_reports": malformed,
    }


def rolling_atr(bars: Sequence[Bar], window: int = 14) -> list[float | None]:
    trs: list[int] = []
    output: list[float | None] = []
    running = 0
    for index, bar in enumerate(bars):
        previous = bars[index - 1].close_e8 if index else bar.open_e8
        tr = max(bar.high_e8 - bar.low_e8, abs(bar.high_e8 - previous), abs(bar.low_e8 - previous))
        trs.append(tr)
        running += tr
        if len(trs) > window:
            running -= trs[-window - 1]
        output.append(running / window if len(trs) >= window else None)
    return output


def trading_day(value: datetime) -> date:
    return (value.astimezone(NY) - timedelta(hours=17)).date()


def build_daily_and_weekly(m15: Sequence[Bar]) -> tuple[list[DailyBar], dict[date, DailyBar], dict[tuple[int, int], DailyBar]]:
    groups: dict[date, list[Bar]] = defaultdict(list)
    for bar in m15:
        groups[trading_day(bar.open_at)].append(bar)
    daily: list[DailyBar] = []
    for key in sorted(groups):
        values = sorted(groups[key], key=lambda item: item.open_at)
        completed = datetime.combine(key + timedelta(days=1), time(17), NY).astimezone(UTC)
        daily.append(
            DailyBar(
                key,
                values[0].open_e8,
                max(item.high_e8 for item in values),
                min(item.low_e8 for item in values),
                values[-1].close_e8,
                completed,
                canonical_hash([key.isoformat(), [item.record_hash for item in values]]),
            )
        )
    daily_map = {item.trading_date: item for item in daily}
    week_groups: dict[tuple[int, int], list[DailyBar]] = defaultdict(list)
    for item in daily:
        iso = item.trading_date.isocalendar()
        week_groups[(iso.year, iso.week)].append(item)
    weekly: dict[tuple[int, int], DailyBar] = {}
    for key, values in week_groups.items():
        values.sort(key=lambda item: item.trading_date)
        weekly[key] = DailyBar(
            values[0].trading_date,
            values[0].open_e8,
            max(item.high_e8 for item in values),
            min(item.low_e8 for item in values),
            values[-1].close_e8,
            values[-1].completed_at,
            canonical_hash([key, [item.evidence_hash for item in values]]),
        )
    return daily, daily_map, weekly


def build_asia_ranges(m15: Sequence[Bar]) -> tuple[list[AsiaRange], list[datetime]]:
    groups: dict[date, list[Bar]] = defaultdict(list)
    for bar in m15:
        local = bar.open_at.astimezone(TOKYO)
        if time(10, 0) <= local.time() < time(16, 0):
            groups[local.date()].append(bar)
    output: list[AsiaRange] = []
    for key in sorted(groups):
        values = sorted(groups[key], key=lambda item: item.open_at)
        completed = datetime.combine(key, time(16), TOKYO).astimezone(UTC)
        output.append(
            AsiaRange(
                key,
                max(item.high_e8 for item in values),
                min(item.low_e8 for item in values),
                completed,
                canonical_hash([key.isoformat(), [item.record_hash for item in values]]),
            )
        )
    return output, [item.completed_at for item in output]


def session_state(value: datetime) -> str:
    london = time(8) <= value.astimezone(LONDON).time() < time(12)
    new_york = time(8) <= value.astimezone(NY).time() < time(12)
    asia = time(10) <= value.astimezone(TOKYO).time() < time(16)
    if london and new_york:
        return "LONDON_NEW_YORK_OVERLAP"
    if london:
        return "LONDON"
    if new_york:
        return "NEW_YORK"
    if asia:
        return "ASIA"
    return "OTHER"


def ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    value = float(numerator) / float(denominator)
    return value if math.isfinite(value) else None


def direction_sign(direction: str) -> int:
    if direction == "UP":
        return 1
    if direction == "DOWN":
        return -1
    raise ValueError(direction)


def candle_geometry(current: Bar, previous: Bar | None, direction: str, atr: float | None) -> dict[str, Any]:
    sign = direction_sign(direction)
    range_e8 = current.high_e8 - current.low_e8
    body = current.close_e8 - current.open_e8
    signed_body = sign * body
    body_state = "ALIGNED" if signed_body > 0 else "OPPOSED" if signed_body < 0 else "DOJI"
    body_fraction = ratio(abs(body), range_e8)
    if range_e8:
        close_location = (current.close_e8 - current.low_e8) / range_e8 if sign > 0 else (current.high_e8 - current.close_e8) / range_e8
        rejection = (min(current.open_e8, current.close_e8) - current.low_e8) / range_e8 if sign > 0 else (current.high_e8 - max(current.open_e8, current.close_e8)) / range_e8
        opposite = (current.high_e8 - max(current.open_e8, current.close_e8)) / range_e8 if sign > 0 else (min(current.open_e8, current.close_e8) - current.low_e8) / range_e8
    else:
        close_location = rejection = opposite = None
    engulf = inside = outside = close_through = None
    if previous is not None:
        current_body = (min(current.open_e8, current.close_e8), max(current.open_e8, current.close_e8))
        prior_body = (min(previous.open_e8, previous.close_e8), max(previous.open_e8, previous.close_e8))
        engulf = bool(
            signed_body > 0
            and current_body[0] <= prior_body[0]
            and current_body[1] >= prior_body[1]
            and current_body != prior_body
        )
        inside = bool(current.high_e8 <= previous.high_e8 and current.low_e8 >= previous.low_e8 and (current.high_e8 < previous.high_e8 or current.low_e8 > previous.low_e8))
        outside = bool(current.high_e8 >= previous.high_e8 and current.low_e8 <= previous.low_e8 and (current.high_e8 > previous.high_e8 or current.low_e8 < previous.low_e8))
        close_through = current.close_e8 > previous.high_e8 if sign > 0 else current.close_e8 < previous.low_e8
    return {
        "range_atr": ratio(range_e8, atr),
        "body_fraction": body_fraction,
        "close_location": close_location,
        "rejection_wick": rejection,
        "opposite_wick": opposite,
        "body_state": body_state,
        "engulfing_aligned": engulf,
        "inside_bar": inside,
        "outside_bar": outside,
        "close_through_prior_extreme": close_through,
    }


def retracement_zone(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value < 0.236:
        return "RET_LT_236"
    if value < 0.382:
        return "RET_236_382"
    if value < 0.5:
        return "RET_382_500"
    if value < 0.618:
        return "RET_500_618"
    if value < 0.786:
        return "RET_618_786"
    return "RET_GT_786"


def structure_timelines(events: Sequence[Mapping[str, Any]]) -> dict[str, tuple[list[datetime], list[str]]]:
    output: dict[str, tuple[list[datetime], list[str]]] = {}
    for timeframe in ("H1", "H4"):
        selected = sorted(
            (
                (parse_dt(str(item["event_at_utc"])), str(item["direction"]))
                for item in events
                if item["timeframe"] == timeframe and item["scale"] == "STANDARD"
            ),
            key=lambda item: item[0],
        )
        output[timeframe] = ([item[0] for item in selected], [item[1] for item in selected])
    return output


def state_at(timelines: Mapping[str, tuple[list[datetime], list[str]]], timeframe: str, decision: datetime) -> str:
    times, states = timelines[timeframe]
    index = bisect.bisect_right(times, decision) - 1
    return states[index] if index >= 0 else "UNKNOWN"


def previous_daily(daily: Sequence[DailyBar], decision: datetime) -> tuple[int, DailyBar | None]:
    completed = [item.completed_at for item in daily]
    index = bisect.bisect_right(completed, decision) - 1
    return index, daily[index] if index >= 0 else None


def weekly_completed(weekly: Mapping[tuple[int, int], DailyBar], decision: datetime) -> list[DailyBar]:
    return sorted((item for item in weekly.values() if item.completed_at <= decision), key=lambda item: item.completed_at)


def level_flags(pivot: Bar, confirmation: Bar, direction: str, upper: int | None, lower: int | None) -> tuple[bool | None, bool | None]:
    if upper is None or lower is None:
        return None, None
    touch = pivot.low_e8 <= upper <= pivot.high_e8 or pivot.low_e8 <= lower <= pivot.high_e8
    if direction == "UP":
        reclaim = pivot.low_e8 < lower and confirmation.close_e8 > lower
    else:
        reclaim = pivot.high_e8 > upper and confirmation.close_e8 < upper
    return bool(touch), bool(reclaim)


COMPONENT_COLUMNS = {
    "REAL_YIELD": "real_yield_contribution_aligned",
    "FED_PATH": "fed_path_contribution_aligned",
    "USD": "usd_contribution_aligned",
    "TWO_YEAR_YIELD": "two_year_contribution_aligned",
    "POSITIONING_FLOW": "positioning_contribution_aligned",
    "FINANCIAL_STRESS": "financial_stress_contribution_aligned",
}


def feature_row(
    case: Mapping[str, Any],
    bars: Mapping[str, Sequence[Bar]],
    close_times: Mapping[str, Sequence[datetime]],
    close_indexes: Mapping[str, Mapping[datetime, int]],
    atrs: Mapping[str, Sequence[float | None]],
    events_by_id: Mapping[str, Mapping[str, Any]],
    segment_events: Mapping[str, Sequence[Mapping[str, Any]]],
    timelines: Mapping[str, tuple[list[datetime], list[str]]],
    daily: Sequence[DailyBar],
    weekly: Mapping[tuple[int, int], DailyBar],
    asia: Sequence[AsiaRange],
    asia_times: Sequence[datetime],
    fundamentals: Sequence[Mapping[str, Any]],
    fundamental_times: Sequence[datetime],
    positioning: Sequence[Mapping[str, Any]],
    positioning_times: Sequence[datetime],
    implementation: str,
) -> dict[str, Any]:
    timeframe = str(case["timeframe"])
    direction = str(case["direction"])
    sign = direction_sign(direction)
    decision = parse_dt(str(case["known_at_utc"]))
    pivot_at = parse_dt(str(case["pivot_at_utc"]))
    values = bars[timeframe]
    if implementation == "primary":
        known_index = close_indexes[timeframe].get(decision)
        pivot_index = close_indexes[timeframe].get(pivot_at)
    else:
        known_index = bisect.bisect_left(close_times[timeframe], decision)
        pivot_index = bisect.bisect_left(close_times[timeframe], pivot_at)
        known_index = known_index if known_index < len(values) and values[known_index].close_at == decision else None
        pivot_index = pivot_index if pivot_index < len(values) and values[pivot_index].close_at == pivot_at else None
    base = {
        "pullback_id": str(case["pullback_id"]),
        "timeframe": timeframe,
        "scale": str(case["scale"]),
        "span": int(case["span"]),
        "direction": direction,
        "segment_id": str(case["segment_id"]),
        "pivot_swing_id": str(case["pivot_swing_id"]),
        "reference_event_id": str(case["reference_event_id"]),
        "pivot_at_utc": iso_z(pivot_at),
        "known_at_utc": iso_z(decision),
        "actionable_at_known": bool(case["actionable_at_known"]),
        "research_eligible": bool(case["research_eligible"]),
        "primary_research_scale": str(case["scale"]) == "STANDARD",
        "feature_available": False,
        "unavailable_reason": None,
    }
    if decision >= END:
        return {
            **base,
            "unavailable_reason": "DECISION_OUTSIDE_DEVELOPMENT",
            "feature_lineage_hash": canonical_hash([case["decision_facts_hash"], "DECISION_OUTSIDE_DEVELOPMENT"]),
        }
    if known_index is None or pivot_index is None:
        return {**base, "unavailable_reason": "MISSING_PIVOT_OR_KNOWN_BAR", "feature_lineage_hash": canonical_hash([case["decision_facts_hash"], "MISSING_PIVOT_OR_KNOWN_BAR"])}
    if known_index < pivot_index or decision > END:
        return {**base, "unavailable_reason": "INVALID_DECISION_CHRONOLOGY", "feature_lineage_hash": canonical_hash([case["decision_facts_hash"], "INVALID_DECISION_CHRONOLOGY"])}
    reference = events_by_id.get(str(case["reference_event_id"]))
    if reference is None:
        return {**base, "unavailable_reason": "MISSING_REFERENCE_EVENT", "feature_lineage_hash": canonical_hash([case["decision_facts_hash"], "MISSING_REFERENCE_EVENT"])}
    reference_at = parse_dt(str(reference["event_at_utc"]))
    if implementation == "primary":
        reference_index = close_indexes[timeframe].get(reference_at)
    else:
        candidate = bisect.bisect_left(close_times[timeframe], reference_at)
        reference_index = candidate if candidate < len(values) and values[candidate].close_at == reference_at else None
    if reference_index is None or not (reference_index < pivot_index <= known_index):
        return {**base, "unavailable_reason": "INVALID_REFERENCE_CHRONOLOGY", "feature_lineage_hash": canonical_hash([case["decision_facts_hash"], reference.get("evidence_hash"), "INVALID_REFERENCE_CHRONOLOGY"])}

    pivot = values[pivot_index]
    confirmation = values[known_index]
    atr = atrs[timeframe][known_index]
    if atr is None or atr <= 0:
        return {**base, "unavailable_reason": "ATR14_UNAVAILABLE", "feature_lineage_hash": canonical_hash([case["decision_facts_hash"], "ATR14_UNAVAILABLE"])}
    impulse_slice = values[reference_index : pivot_index + 1]
    if sign > 0:
        impulse_relative = max(range(len(impulse_slice)), key=lambda idx: (impulse_slice[idx].high_e8, -idx))
        impulse_price = impulse_slice[impulse_relative].high_e8
        retrace_depth = impulse_price - int(case["pivot_price_e8"])
        impulse_extension = impulse_price - int(case["reference_level_e8"])
    else:
        impulse_relative = min(range(len(impulse_slice)), key=lambda idx: (impulse_slice[idx].low_e8, idx))
        impulse_price = impulse_slice[impulse_relative].low_e8
        retrace_depth = int(case["pivot_price_e8"]) - impulse_price
        impulse_extension = int(case["reference_level_e8"]) - impulse_price
    impulse_index = reference_index + impulse_relative
    retrace_fraction = ratio(retrace_depth, impulse_extension if impulse_extension > 0 else None)

    impulse_closes = [item.close_e8 for item in values[reference_index : impulse_index + 1]]
    impulse_path = sum(abs(right - left) for left, right in zip(impulse_closes, impulse_closes[1:]))
    impulse_net = sign * (impulse_closes[-1] - impulse_closes[0]) if impulse_closes else 0
    impulse_efficiency = ratio(max(0, impulse_net), impulse_path) if impulse_path else (1.0 if impulse_net > 0 else 0.0)
    pullback_closes = [item.close_e8 for item in values[impulse_index : pivot_index + 1]]
    pullback_path = sum(abs(right - left) for left, right in zip(pullback_closes, pullback_closes[1:]))
    pullback_net = -sign * (pullback_closes[-1] - pullback_closes[0]) if pullback_closes else 0
    pullback_efficiency = ratio(max(0, pullback_net), pullback_path) if pullback_path else 0.0

    def mean_tr(left: int, right: int) -> float | None:
        values_tr = []
        for idx in range(max(0, left), min(len(values), right + 1)):
            previous_close = values[idx - 1].close_e8 if idx else values[idx].open_e8
            values_tr.append(max(values[idx].high_e8 - values[idx].low_e8, abs(values[idx].high_e8 - previous_close), abs(values[idx].low_e8 - previous_close)))
        return statistics.fmean(values_tr) if values_tr else None

    impulse_tr = mean_tr(reference_index, impulse_index)
    pullback_tr = mean_tr(impulse_index + 1, pivot_index)
    compression = ratio(pullback_tr, impulse_tr)
    pivot_geo = candle_geometry(pivot, values[pivot_index - 1] if pivot_index else None, direction, atr)
    confirm_geo = candle_geometry(confirmation, values[known_index - 1] if known_index else None, direction, atr)
    response_closes = [item.close_e8 for item in values[pivot_index : known_index + 1]]
    response_path = sum(abs(right - left) for left, right in zip(response_closes, response_closes[1:]))
    response_net = sign * (confirmation.close_e8 - pivot.close_e8)
    response_efficiency = ratio(max(0, response_net), response_path) if response_path else 0.0
    aligned_close_count = sum(sign * (values[idx].close_e8 - values[idx - 1].close_e8) > 0 for idx in range(pivot_index + 1, known_index + 1))
    prior_volumes = [item.volume for item in values[max(0, known_index - 20) : known_index] if item.volume is not None]
    volume_ratio = ratio(confirmation.volume, statistics.median(prior_volumes)) if confirmation.volume is not None and prior_volumes else None

    reference_level = int(case["reference_level_e8"])
    reference_touch = pivot.low_e8 <= reference_level <= pivot.high_e8
    reference_reclaim = pivot.low_e8 < reference_level and confirmation.close_e8 > reference_level if sign > 0 else pivot.high_e8 > reference_level and confirmation.close_e8 < reference_level

    daily_index, prior_day = previous_daily(daily, decision)
    prior_touch, prior_reclaim = level_flags(pivot, confirmation, direction, prior_day.high_e8 if prior_day else None, prior_day.low_e8 if prior_day else None)
    completed_daily = daily[: daily_index + 1] if daily_index >= 0 else []
    daily_alignment = None
    if len(completed_daily) >= 3:
        daily_alignment = sign * (completed_daily[-1].close_e8 - completed_daily[-3].close_e8) > 0
    completed_weekly = weekly_completed(weekly, decision)
    weekly_alignment = None
    if len(completed_weekly) >= 2:
        weekly_alignment = sign * (completed_weekly[-1].close_e8 - completed_weekly[-2].close_e8) > 0

    asia_index = bisect.bisect_right(asia_times, decision) - 1
    asia_value = asia[asia_index] if asia_index >= 0 and decision - asia[asia_index].completed_at <= timedelta(hours=24) else None
    asia_touch, asia_reclaim = level_flags(pivot, confirmation, direction, asia_value.high_e8 if asia_value else None, asia_value.low_e8 if asia_value else None)

    h1_state = state_at(timelines, "H1", decision)
    h4_state = state_at(timelines, "H4", decision)
    h1_alignment = h1_state == direction if timeframe == "M15" and h1_state != "UNKNOWN" else None
    h4_alignment = h4_state == direction if timeframe in {"M15", "H1"} and h4_state != "UNKNOWN" else None
    alignment_values = [item for item in (h1_alignment, h4_alignment, daily_alignment, weekly_alignment) if item is not None]

    fundamental_index = bisect.bisect_right(fundamental_times, decision) - 1
    fundamental = fundamentals[fundamental_index] if fundamental_index >= 0 else None
    fundamental_age = (decision - fundamental["available_at"]).total_seconds() / 3600 if fundamental else None
    if fundamental_age is None or fundamental_age < 0 or fundamental_age > 96:
        fundamental = None
    score = fundamental.get("score") if fundamental else None
    confidence = fundamental.get("confidence") if fundamental else None
    coverage = fundamental.get("coverage") if fundamental else None
    score_aligned = sign * score if score is not None else None
    if fundamental is None or score_aligned is None or confidence is None or coverage is None:
        fundamental_state = "UNKNOWN"
    elif score_aligned >= 20 and coverage >= 50 and confidence >= 35:
        fundamental_state = "ALIGNED"
    elif score_aligned <= -20 and coverage >= 50 and confidence >= 35:
        fundamental_state = "OPPOSED"
    else:
        fundamental_state = "NEUTRAL_OR_WEAK"
    component_values: dict[str, float | None] = {}
    for code, column in COMPONENT_COLUMNS.items():
        component = fundamental["components"].get(code) if fundamental else None
        contribution = finite(component.get("contribution")) if isinstance(component, Mapping) else None
        component_values[column] = sign * contribution if contribution is not None else None

    positioning_index = bisect.bisect_right(positioning_times, decision) - 1
    cot = positioning[positioning_index] if positioning_index >= 0 else None
    cot_age = (decision - cot["available_at"]).total_seconds() / 86_400 if cot else None
    if cot_age is None or cot_age < 0 or cot_age > 14:
        cot = None
    cot_change = cot.get("net_change") if cot else None

    segment_prior = [item for item in segment_events.get(str(case["segment_id"]), []) if parse_dt(str(item["event_at_utc"])) <= decision]
    prior_continuations = sum("CONTINUATION" in str(item["event_type"]) for item in segment_prior)
    pivot_rejection_strong = bool(
        pivot_geo["rejection_wick"] is not None
        and pivot_geo["rejection_wick"] >= 0.40
        and pivot_geo["close_location"] is not None
        and pivot_geo["close_location"] >= 0.60
        and pivot_geo["body_state"] != "OPPOSED"
    )
    confirmation_displacement = bool(
        confirm_geo["range_atr"] is not None
        and confirm_geo["range_atr"] >= 0.80
        and confirm_geo["body_fraction"] is not None
        and confirm_geo["body_fraction"] >= 0.50
        and confirm_geo["close_location"] is not None
        and confirm_geo["close_location"] >= (2 / 3)
        and confirm_geo["body_state"] == "ALIGNED"
    )

    lineage = {
        "case": str(case["decision_facts_hash"]),
        "reference": str(reference["evidence_hash"]),
        "price": [item.record_hash for item in values[reference_index : known_index + 1]],
        "prior_day": prior_day.evidence_hash if prior_day else None,
        "asia": asia_value.evidence_hash if asia_value else None,
        "fundamental": fundamental.get("record_hash") if fundamental else None,
        "cot": cot.get("record_hash") if cot else None,
    }
    row = {
        **base,
        "feature_available": True,
        "unavailable_reason": None,
        "atr14_e8": float(atr),
        "trend_age_bars": known_index - reference_index,
        "event_to_pivot_bars": pivot_index - reference_index,
        "impulse_to_pivot_bars": pivot_index - impulse_index,
        "prior_continuation_count": prior_continuations,
        "impulse_extension_atr": ratio(impulse_extension, atr),
        "impulse_efficiency": impulse_efficiency,
        "pullback_efficiency": pullback_efficiency,
        "retracement_fraction": retrace_fraction,
        "retracement_depth_atr": ratio(retrace_depth, atr),
        "compression_ratio": compression,
        "reference_distance_atr": ratio(sign * (confirmation.close_e8 - reference_level), atr),
        "pivot_range_atr": pivot_geo["range_atr"],
        "pivot_body_fraction": pivot_geo["body_fraction"],
        "pivot_close_location_trend": pivot_geo["close_location"],
        "pivot_rejection_wick_fraction": pivot_geo["rejection_wick"],
        "pivot_opposite_wick_fraction": pivot_geo["opposite_wick"],
        "confirmation_range_atr": confirm_geo["range_atr"],
        "confirmation_body_fraction": confirm_geo["body_fraction"],
        "confirmation_close_location_trend": confirm_geo["close_location"],
        "confirmation_rejection_wick_fraction": confirm_geo["rejection_wick"],
        "confirmation_opposite_wick_fraction": confirm_geo["opposite_wick"],
        "response_displacement_atr": ratio(response_net, atr),
        "response_efficiency": response_efficiency,
        "response_aligned_close_count": aligned_close_count,
        "confirmation_volume_ratio_20": volume_ratio,
        "retracement_zone": retracement_zone(retrace_fraction),
        "pivot_body_state": pivot_geo["body_state"],
        "confirmation_body_state": confirm_geo["body_state"],
        "pivot_engulfing_aligned": pivot_geo["engulfing_aligned"],
        "pivot_inside_bar": pivot_geo["inside_bar"],
        "pivot_outside_bar": pivot_geo["outside_bar"],
        "pivot_close_through_prior_extreme": pivot_geo["close_through_prior_extreme"],
        "confirmation_engulfing_aligned": confirm_geo["engulfing_aligned"],
        "confirmation_inside_bar": confirm_geo["inside_bar"],
        "confirmation_outside_bar": confirm_geo["outside_bar"],
        "confirmation_close_through_prior_extreme": confirm_geo["close_through_prior_extreme"],
        "pivot_rejection_strong": pivot_rejection_strong,
        "confirmation_displacement": confirmation_displacement,
        "reference_touch": bool(reference_touch),
        "reference_sweep_reclaim": bool(reference_reclaim),
        "prior_day_level_touch": prior_touch,
        "prior_day_sweep_reclaim": prior_reclaim,
        "asia_level_touch": asia_touch,
        "asia_sweep_reclaim": asia_reclaim,
        "session_state": session_state(decision),
        "h1_structure_state": h1_state,
        "h1_structure_alignment": h1_alignment,
        "h4_structure_state": h4_state,
        "h4_structure_alignment": h4_alignment,
        "daily_3bar_alignment": daily_alignment,
        "weekly_2bar_alignment": weekly_alignment,
        "higher_timeframe_alignment_count": sum(item is True for item in alignment_values),
        "higher_timeframe_known_count": len(alignment_values),
        "fundamental_available": fundamental is not None,
        "fundamental_age_hours": fundamental_age if fundamental is not None else None,
        "fundamental_score": score,
        "fundamental_score_aligned": score_aligned,
        "fundamental_confidence": confidence,
        "fundamental_coverage": coverage,
        "fundamental_alignment_state": fundamental_state,
        "fundamental_regime": fundamental.get("regime") if fundamental else "UNKNOWN",
        "reaction_function": fundamental.get("reaction_function") if fundamental else "UNKNOWN",
        "event_risk": fundamental.get("event_risk") if fundamental else "UNKNOWN",
        **component_values,
        "cot_available": cot is not None,
        "cot_age_days": cot_age if cot is not None else None,
        "cot_managed_money_net_percentile": cot.get("percentile") if cot else None,
        "cot_managed_money_net_change_aligned": sign * cot_change if cot_change is not None else None,
        "cot_crowding_state": cot.get("crowding") if cot else "UNKNOWN",
        "cot_long_liquidation_risk": cot.get("long_liquidation") if cot else "UNKNOWN",
        "cot_short_covering_risk": cot.get("short_covering") if cot else "UNKNOWN",
        "feature_lineage_hash": canonical_hash(lineage),
    }
    return row


def null_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    keys = rows[0].keys() if rows else []
    return {key: sum(row.get(key) is None for row in rows) for key in keys}


def materialize() -> dict[str, Any]:
    freeze = verify_design()
    if any(path.exists() for path in (PRIMARY_FEATURES, REFERENCE_FEATURES, CERTIFICATION, PREOUTCOME_FREEZE, STATE)):
        raise FileExistsError("TPCE materialization artifact already exists")
    bars, price_diagnostics = load_bars()
    close_times = {key: [item.close_at for item in value] for key, value in bars.items()}
    close_indexes = {key: {item.close_at: index for index, item in enumerate(value)} for key, value in bars.items()}
    atrs = {key: rolling_atr(value) for key, value in bars.items()}
    daily, _, weekly = build_daily_and_weekly(bars["M15"])
    asia, asia_times = build_asia_ranges(bars["M15"])
    fundamentals, fundamental_times, fundamental_diagnostics = load_fundamentals()
    positioning, positioning_times, positioning_diagnostics = load_positioning()

    primary_cases = load_registry(CENSUS / "primary_pullback_cases.parquet", CASE_COLUMNS)
    reference_cases = load_registry(CENSUS / "reference_pullback_cases.parquet", CASE_COLUMNS)
    primary_events = load_registry(CENSUS / "primary_structure_events.parquet", EVENT_COLUMNS)
    reference_events = load_registry(CENSUS / "reference_structure_events.parquet", EVENT_COLUMNS)
    if canonical_hash(primary_cases) != canonical_hash(reference_cases):
        raise ValueError("Census case content differs")
    if canonical_hash(primary_events) != canonical_hash(reference_events):
        raise ValueError("Census event content differs")

    def context(events: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]], dict[str, tuple[list[datetime], list[str]]]]:
        by_id = {str(item["event_id"]): item for item in events}
        by_segment: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for item in events:
            by_segment[str(item["segment_id"])].append(item)
        for values in by_segment.values():
            values.sort(key=lambda item: (item["event_at_utc"], item["event_id"]))
        return by_id, by_segment, structure_timelines(events)

    p_events, p_segments, p_timeline = context(primary_events)
    r_events, r_segments, r_timeline = context(reference_events)
    shared = (bars, close_times, close_indexes, atrs, daily, weekly, asia, asia_times, fundamentals, fundamental_times, positioning, positioning_times)
    primary_rows = [feature_row(case, shared[0], shared[1], shared[2], shared[3], p_events, p_segments, p_timeline, *shared[4:], "primary") for case in primary_cases]
    reference_rows = [feature_row(case, shared[0], shared[1], shared[2], shared[3], r_events, r_segments, r_timeline, *shared[4:], "reference") for case in reference_cases]
    primary_rows.sort(key=lambda row: (row["known_at_utc"], row["timeframe"], row["scale"], row["pullback_id"]))
    reference_rows.sort(key=lambda row: (row["known_at_utc"], row["timeframe"], row["scale"], row["pullback_id"]))
    if primary_rows != reference_rows:
        raise ValueError("Primary/reference feature rows differ")
    if len(primary_rows) != 37_191 or len({row["pullback_id"] for row in primary_rows}) != 37_191:
        raise ValueError("Census denominator changed")
    if any(parse_dt(row["known_at_utc"]) >= END and row["feature_available"] for row in primary_rows):
        raise ValueError("Forward case received feature values")
    write_parquet_exclusive(PRIMARY_FEATURES, primary_rows)
    write_parquet_exclusive(REFERENCE_FEATURES, reference_rows)
    if sha256_file(PRIMARY_FEATURES) != sha256_file(REFERENCE_FEATURES):
        raise ValueError("Primary/reference Parquet bytes differ")

    by_population = Counter(f"{row['timeframe']}|{row['scale']}" for row in primary_rows)
    available = Counter(f"{row['timeframe']}|{row['scale']}|{row['feature_available']}" for row in primary_rows)
    actionable = Counter(f"{row['timeframe']}|{row['scale']}|{row['actionable_at_known']}" for row in primary_rows)
    reasons = Counter(str(row["unavailable_reason"] or "AVAILABLE") for row in primary_rows)
    certification = {
        "version": "GOLD_TPCE_V1_MATERIALIZATION_CERTIFICATION_1_0",
        "status": "PASS_OUTCOME_BLIND_FEATURE_MATERIALIZATION",
        "certified_at_utc": utc_now(),
        "rows": len(primary_rows),
        "unique_pullback_ids": len({row["pullback_id"] for row in primary_rows}),
        "by_population": dict(sorted(by_population.items())),
        "feature_availability": dict(sorted(available.items())),
        "actionability_audit": dict(sorted(actionable.items())),
        "unavailable_reasons": dict(sorted(reasons.items())),
        "null_counts": null_counts(primary_rows),
        "schema": str(pq.read_schema(PRIMARY_FEATURES)),
        "feature_rows_hash": canonical_hash(primary_rows),
        "primary": file_record(PRIMARY_FEATURES),
        "reference": file_record(REFERENCE_FEATURES),
        "byte_identical": True,
        "price_diagnostics": price_diagnostics,
        "fundamental_diagnostics": fundamental_diagnostics,
        "positioning_diagnostics": positioning_diagnostics,
        "daily_ranges": len(daily),
        "weekly_ranges": len(weekly),
        "asia_ranges": len(asia),
        "development_outcomes_accessed": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(CERTIFICATION, certification)
    preoutcome = {
        "version": "GOLD_TPCE_V1_PREOUTCOME_FREEZE_1_0",
        "status": "SEALED_AFTER_FEATURES_BEFORE_OUTCOME_JOIN",
        "sealed_at_utc": utc_now(),
        "design_freeze": file_record(DESIGN_FREEZE),
        "controls": freeze["controls"],
        "feature_matrix_primary": file_record(PRIMARY_FEATURES),
        "feature_matrix_reference": file_record(REFERENCE_FEATURES),
        "materialization_certification": file_record(CERTIFICATION),
        "rows": len(primary_rows),
        "feature_rows_hash": certification["feature_rows_hash"],
        "development_outcomes_accessed": False,
        "forward_values_accessed": False,
        "execution_or_pnl_permitted": False,
    }
    write_json_exclusive(PREOUTCOME_FREEZE, preoutcome)
    write_json_exclusive(
        STATE,
        {
            "version": "GOLD_TPCE_V1_STATE_M2_1_0",
            "status": certification["status"],
            "recorded_at_utc": utc_now(),
            "preoutcome_freeze": file_record(PREOUTCOME_FREEZE),
            "next_step": "ONE_CONTROLLED_DEVELOPMENT_OUTCOME_JOIN_AND_REGISTERED_RELATIONSHIP_DISCOVERY",
            "forward_locked": ["2025", "2026"],
        },
    )
    return certification


def selftest() -> None:
    now = datetime(2024, 1, 2, 12, tzinfo=UTC)
    assert trading_day(now) == (now.astimezone(NY) - timedelta(hours=17)).date()
    assert retracement_zone(0.236) == "RET_236_382"
    assert retracement_zone(0.382) == "RET_382_500"
    bar = Bar("M15", now, now + timedelta(minutes=15), 100, 130, 90, 125, 10, True, "x")
    prior = Bar("M15", now - timedelta(minutes=15), now, 110, 120, 100, 105, 10, True, "y")
    result = candle_geometry(bar, prior, "UP", 20)
    assert result["body_state"] == "ALIGNED" and result["close_location"] == 0.875


def main() -> None:
    selftest()
    result = materialize()
    print(json.dumps({
        "status": result["status"],
        "rows": result["rows"],
        "by_population": result["by_population"],
        "unavailable_reasons": result["unavailable_reasons"],
        "primary": result["primary"],
        "preoutcome_freeze": file_record(PREOUTCOME_FREEZE),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
