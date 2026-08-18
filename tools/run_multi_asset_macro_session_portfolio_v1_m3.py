#!/usr/bin/env python3
"""Run Multi-Asset Macro and Session Portfolio Edge Discovery V1 Milestone 3.

The analytical design and this implementation must be hash-sealed before the
``materialize`` command may deserialize predictor prices.  Materialization
constructs point-in-time signal identities only.  The ``evaluate`` command
then records one controlled development-outcome opening, independently
reproduces execution and statistics, and stops without reading 2025/2026.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m3"
MANIFESTS = ROOT / "research_manifests"
CONTRACT = ROOT / "MULTI_ASSET_MACRO_AND_SESSION_PORTFOLIO_EDGE_DISCOVERY_CONTRACT_V1.md"
M1_PROTOCOL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_protocol.json"
M2_SEAL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_milestone2_seal.json"
M3_PROTOCOL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_protocol.json"
FEATURE_REGISTRY = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_feature_registry.json"
TEST_REGISTRY = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_test_registry.json"
PREOUTCOME_FREEZE = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_preoutcome_freeze.json"
ENGINEERING_AMENDMENT_A = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_engineering_amendment_a.json"
ENGINEERING_AMENDMENT_B = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_m3_engineering_amendment_b.json"
MATERIALIZATION_CERTIFICATION = ARTIFACTS / "materialization_certification.json"
MATERIALIZATION_ATTEMPT1_FAILURE = ARTIFACTS / "materialization_attempt1_failure.json"
MATERIALIZATION_ATTEMPT2_FAILURE = ARTIFACTS / "materialization_attempt2_failure.json"
PRIMARY_SIGNALS = ARTIFACTS / "primary_signals.parquet"
REFERENCE_SIGNALS = ARTIFACTS / "reference_signals.parquet"
OUTCOME_AUTHORIZATION = ARTIFACTS / "development_outcome_opening.json"
PRIMARY_TRADES = ARTIFACTS / "primary_trades.parquet"
REFERENCE_TRADES = ARTIFACTS / "reference_trades.parquet"
STAGE1_RESULTS = ARTIFACTS / "stage1_results.json"
STAGE2_RESULTS = ARTIFACTS / "stage2_results.json"
FINAL_RESULTS = ARTIFACTS / "final_results.json"
REPORT = ROOT / "MULTI_ASSET_MACRO_AND_SESSION_PORTFOLIO_EDGE_DISCOVERY_V1_MILESTONE_3_REPORT.md"
FINAL_SEAL = MANIFESTS / "multi_asset_macro_session_portfolio_edge_v1_milestone3_seal.json"

FUNDAMENTALS = ROOT / "research_artifacts/gold_casebook_v01/fundamentals.jsonl.gz"
EVENTS = ROOT / "research_artifacts/gold_casebook_v01/events.jsonl.gz"
POSITIONING = ROOT / "research_artifacts/gold_casebook_v01/positioning.jsonl.gz"
CME_MANIFEST = ROOT / "data/raw/databento_cme_pre2025/manifest.json"

START = datetime(2021, 8, 1, tzinfo=UTC)
OOF_START = datetime(2022, 1, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)
SCALE = 100_000_000
BOOTSTRAPS = 5_000
BOOTSTRAP_SEED = 731_947

INSTRUMENTS: dict[str, dict[str, Any]] = {
    "XAUUSD": {"research_id": "XAUUSD", "cluster": "PRECIOUS_METALS", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION"), "point": 0.01, "contract": 100.0, "volume_min": 0.01, "volume_step": 0.01, "quote": "USD"},
    "XAGUSD": {"research_id": "XAGUSD", "cluster": "PRECIOUS_METALS", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION"), "point": 0.001, "contract": 1000.0, "volume_min": 0.01, "volume_step": 0.01, "quote": "USD"},
    "EURUSD": {"research_id": "EURUSD", "cluster": "USD_FX", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION"), "point": 0.00001, "contract": 100000.0, "volume_min": 0.01, "volume_step": 0.01, "quote": "USD"},
    "USDJPY": {"research_id": "USDJPY", "cluster": "USD_FX", "sessions": ("LONDON_DECISION", "NEW_YORK_DECISION"), "point": 0.001, "contract": 100000.0, "volume_min": 0.01, "volume_step": 0.01, "quote": "JPY"},
    "USTEC": {"research_id": "NAS100", "cluster": "US_EQUITY_INDICES", "sessions": ("US_CASH_OPEN",), "point": 0.01, "contract": 1.0, "volume_min": 0.1, "volume_step": 0.1, "quote": "USD"},
    "US500": {"research_id": "US500", "cluster": "US_EQUITY_INDICES", "sessions": ("US_CASH_OPEN",), "point": 0.01, "contract": 1.0, "volume_min": 0.1, "volume_step": 0.1, "quote": "USD"},
    "XTIUSD": {"research_id": "WTI", "cluster": "ENERGY", "sessions": ("US_ENERGY",), "point": 0.01, "contract": 100.0, "volume_min": 0.5, "volume_step": 0.5, "quote": "USD"},
}

SESSION_SPECS: dict[str, tuple[str, time, time, int]] = {
    "LONDON_DECISION": ("Europe/London", time(7, 0), time(12, 0), 15),
    "NEW_YORK_DECISION": ("America/New_York", time(8, 0), time(12, 0), 15),
    "US_CASH_OPEN": ("America/New_York", time(9, 30), time(12, 0), 30),
    "US_ENERGY": ("America/New_York", time(8, 0), time(14, 30), 30),
}

FAMILIES = (
    "E1_POST_MACRO_ACCEPTANCE_REJECTION",
    "E2_PRIOR_SESSION_SWEEP_RECLAIM",
    "E3_PRIMARY_SESSION_BREAK_ACCEPT_RETEST",
    "E4_HTF_PULLBACK_RESOLUTION",
)
MACRO_STATES = ("ALIGNED", "OPPOSED", "NEUTRAL", "UNKNOWN")
TIER1_EVENTS = {"US_CPI", "US_PCE_PRICE_INDEX", "US_NONFARM_PAYROLLS", "US_REAL_GDP", "US_RETAIL_SALES", "US_INITIAL_JOBLESS_CLAIMS", "US_FOMC_RATE_DECISION"}
EVENT_ALIASES = {
    "US_CPI": "CPI", "US_PCE_PRICE_INDEX": "PCE", "US_NONFARM_PAYROLLS": "NFP",
    "US_REAL_GDP": "GDP", "US_RETAIL_SALES": "RETAIL_SALES",
    "US_INITIAL_JOBLESS_CLAIMS": "JOBLESS_CLAIMS", "US_FOMC_RATE_DECISION": "FOMC",
}

FOLDS = (
    (1, date(2022, 1, 1), date(2022, 7, 1)),
    (2, date(2022, 7, 1), date(2023, 1, 1)),
    (3, date(2023, 1, 1), date(2023, 7, 1)),
    (4, date(2023, 7, 1), date(2024, 1, 1)),
    (5, date(2024, 1, 1), date(2024, 7, 1)),
    (6, date(2024, 7, 1), date(2025, 1, 1)),
)

MACRO_WEIGHTS: dict[str, dict[str, float]] = {
    "XAUUSD": {"REAL10": -0.30, "Y2": -0.20, "USD": -0.30, "INFLATION": 0.10, "GROWTH": -0.10},
    "XAGUSD": {"REAL10": -0.25, "Y2": -0.20, "USD": -0.30, "INFLATION": 0.10, "GROWTH": 0.15},
    "EURUSD": {"USD": -0.45, "Y2": -0.25, "GROWTH": -0.15, "VIX": -0.15},
    "USDJPY": {"Y2": 0.45, "Y10": 0.20, "GROWTH": 0.15, "VIX": -0.20},
    "USTEC": {"Y2": -0.25, "Y10": -0.15, "GROWTH": 0.30, "VIX": -0.20, "STRESS": -0.10},
    "US500": {"Y2": -0.25, "Y10": -0.15, "GROWTH": 0.30, "VIX": -0.20, "STRESS": -0.10},
    "XTIUSD": {"USD": -0.25, "GROWTH": 0.35, "EQUITY": 0.20, "VIX": -0.10, "STRESS": -0.10},
}

SERIES_COMPONENTS: dict[str, tuple[str, ...]] = {
    "REAL10": ("US_REAL_YIELD_10Y",), "Y2": ("US_TREASURY_2Y",),
    "Y10": ("US_TREASURY_10Y",), "USD": ("USD_BROAD_NOMINAL",),
    "VIX": ("US_VOLATILITY_INDEX",), "STRESS": ("US_FINANCIAL_STRESS",),
    "EQUITY": ("US_EQUITY_PROXY",),
    "INFLATION": ("US_CPI_HEADLINE", "US_CPI_CORE", "US_PCE_HEADLINE", "US_PCE_CORE"),
    "GROWTH": ("US_REAL_GDP", "US_RETAIL_SALES", "US_NONFARM_PAYROLLS", "US_UNEMPLOYMENT_RATE", "US_INITIAL_JOBLESS_CLAIMS"),
}
INVERT_COMPONENT_SERIES = {"US_UNEMPLOYMENT_RATE", "US_INITIAL_JOBLESS_CLAIMS"}

SIGNAL_SCHEMA = pa.schema([
    pa.field("signal_id", pa.string(), False), pa.field("instrument", pa.string(), False),
    pa.field("research_id", pa.string(), False), pa.field("cluster", pa.string(), False),
    pa.field("family", pa.string(), False), pa.field("session", pa.string(), False),
    pa.field("session_date", pa.string(), False), pa.field("fold", pa.int8(), False),
    pa.field("direction", pa.int8(), False), pa.field("decision_at_minute", pa.int64(), False),
    pa.field("deadline_minute", pa.int64(), False), pa.field("macro_state", pa.string(), False),
    pa.field("macro_score", pa.float64(), True), pa.field("macro_confidence", pa.float64(), False),
    pa.field("trade_eligible", pa.bool_(), False), pa.field("no_trade_reason", pa.string(), False),
    pa.field("trigger_low", pa.float64(), False), pa.field("trigger_high", pa.float64(), False),
    pa.field("atr15", pa.float64(), False), pa.field("known_levels_json", pa.string(), False),
    pa.field("features_json", pa.string(), False), pa.field("source_event_id", pa.string(), True),
    pa.field("lineage_hash", pa.string(), False),
])

TRADE_SCHEMA = pa.schema([
    *SIGNAL_SCHEMA,
    pa.field("status", pa.string(), False), pa.field("execution_reason", pa.string(), False),
    pa.field("entry_minute", pa.int64(), True), pa.field("exit_minute", pa.int64(), True),
    pa.field("entry", pa.float64(), True), pa.field("stop", pa.float64(), True),
    pa.field("target", pa.float64(), True), pa.field("exit", pa.float64(), True),
    pa.field("exit_reason", pa.string(), True), pa.field("holding_minutes", pa.int64(), True),
    pa.field("risk_price", pa.float64(), True), pa.field("planned_volume", pa.float64(), True),
    pa.field("actual_risk_usd", pa.float64(), True), pa.field("gross_r", pa.float64(), True),
    pa.field("cost_r", pa.float64(), True), pa.field("net_r", pa.float64(), True),
    pa.field("net_r_cost_1p5x", pa.float64(), True), pa.field("net_r_cost_2x", pa.float64(), True),
    pa.field("neighbor_low_net_r", pa.float64(), True), pa.field("neighbor_high_net_r", pa.float64(), True),
    pa.field("mfe_r", pa.float64(), True), pa.field("mae_r", pa.float64(), True),
    pa.field("net_pnl_usd", pa.float64(), True), pa.field("outcome_lineage_hash", pa.string(), False),
])


@dataclass(frozen=True, slots=True)
class Level:
    level_id: str
    family: str
    side: str
    price: float
    known_minute: int


@dataclass(slots=True)
class PriceSeries:
    symbol: str
    minute: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    spread: np.ndarray
    source_inventory_hash: str

    def bounds(self, start: int, end: int) -> tuple[int, int]:
        return int(np.searchsorted(self.minute, start, side="left")), int(np.searchsorted(self.minute, end, side="left"))

    def exact_index(self, minute: int) -> int | None:
        index = int(np.searchsorted(self.minute, minute, side="left"))
        return index if index < len(self.minute) and int(self.minute[index]) == minute else None

    def contiguous(self, start: int, end: int, minimum_fraction: float = 1.0) -> tuple[int, int] | None:
        left, right = self.bounds(start, end)
        expected = end - start
        if expected <= 0 or right <= left or (right - left) / expected < minimum_fraction:
            return None
        if minimum_fraction >= 1.0 and (right - left != expected or np.any(np.diff(self.minute[left:right]) != 1)):
            return None
        return left, right


@dataclass(slots=True)
class AggSeries:
    size: int
    start: np.ndarray
    end: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    count: np.ndarray
    cached_true_range: np.ndarray | None = None

    def latest_index(self, decision: int) -> int:
        return int(np.searchsorted(self.end, decision, side="right")) - 1


@dataclass(slots=True)
class TechnicalBundle:
    m1: PriceSeries
    m5: AggSeries
    m15: AggSeries
    h1: AggSeries
    h4: AggSeries
    d1: AggSeries
    w1: AggSeries
    swings: dict[int, dict[str, list[tuple[int, int, float]]]]
    h4_breaks: list[dict[str, Any]]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def minute_of(value: datetime) -> int:
    return int(value.timestamp() // 60)


def datetime_of(value: int) -> datetime:
    return datetime.fromtimestamp(value * 60, UTC)


def iso_minute(value: int) -> str:
    return datetime_of(value).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


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
    return {"path": path.resolve().relative_to(ROOT.resolve()).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


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


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    table = pa.Table.from_pylist(list(rows), schema=schema)
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=65_536)
    temporary.replace(path)


def fold_for(day: date) -> int | None:
    for number, start, end in FOLDS:
        if start <= day < end:
            return number
    return None


def session_bounds(session: str, day: date) -> tuple[int, int, int]:
    timezone, opened, closed, opening_range = SESSION_SPECS[session]
    zone = ZoneInfo(timezone)
    start = datetime.combine(day, opened, zone).astimezone(UTC)
    end = datetime.combine(day, closed, zone).astimezone(UTC)
    return minute_of(start), minute_of(end), opening_range


def round_float(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    result = round(float(value), 12)
    return 0.0 if result == 0 else result


def verify_sealed_design() -> dict[str, Any]:
    freeze = load_json(PREOUTCOME_FREEZE)
    if freeze.get("status") != "SEALED_BEFORE_ANY_M3_PREDICTOR_OR_OUTCOME_VALUE_ACCESS":
        raise ValueError("Milestone-3 pre-outcome freeze is invalid")
    bindings = {
        "contract": CONTRACT,
        "milestone_1_protocol": M1_PROTOCOL,
        "milestone_2_seal": M2_SEAL,
        "milestone_3_protocol": M3_PROTOCOL,
        "feature_registry": FEATURE_REGISTRY,
        "test_registry": TEST_REGISTRY,
        "implementation": Path(__file__).resolve(),
    }
    for name, path in bindings.items():
        expected = freeze["bindings"][name]["sha256"]
        actual = sha256_file(path)
        if actual == expected:
            continue
        if name != "implementation":
            raise ValueError(f"Frozen binding changed: {name}")
        amendment_a = load_json(ENGINEERING_AMENDMENT_A)
        valid_a = (
            amendment_a.get("status") == "SEALED_VALUE_BLIND_ENGINEERING_CORRECTION_A"
            and amendment_a.get("original_frozen_implementation_sha256") == expected
            and amendment_a.get("corrected_implementation_sha256") == actual
            and amendment_a.get("preoutcome_freeze_sha256") == sha256_file(PREOUTCOME_FREEZE)
            and amendment_a.get("research_definitions_changed") is False
            and amendment_a.get("outcomes_or_relationships_accessed") is False
        )
        valid_b = False
        if ENGINEERING_AMENDMENT_B.exists():
            amendment_b = load_json(ENGINEERING_AMENDMENT_B)
            valid_b = (
                amendment_b.get("status") == "SEALED_VALUE_BLIND_ENGINEERING_CORRECTION_B"
                and amendment_b.get("original_amended_implementation_sha256") == amendment_a.get("corrected_implementation_sha256")
                and amendment_b.get("corrected_implementation_sha256") == actual
                and amendment_b.get("engineering_amendment_a_sha256") == sha256_file(ENGINEERING_AMENDMENT_A)
                and amendment_b.get("preoutcome_freeze_sha256") == sha256_file(PREOUTCOME_FREEZE)
                and amendment_b.get("research_definitions_changed") is False
                and amendment_b.get("outcomes_or_relationships_accessed") is False
            )
        if not (valid_a or valid_b):
            raise ValueError("Corrected implementation is not covered by sealed Engineering Amendment A")
    for item in freeze.get("source_bindings", []):
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Frozen source binding changed: {item['path']}")
    m2 = load_json(M2_SEAL)
    if m2.get("verdict") != "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED" or not m2.get("seven_instrument_discovery_ready"):
        raise ValueError("Milestone-2 PASS is not intact")
    for item in m2["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Milestone-2 artifact changed: {item['path']}")
    if freeze["controls"]["calendar_2025_values_accessed"] or freeze["controls"]["calendar_2026_values_accessed"]:
        raise ValueError("Forward lock is not intact")
    return freeze


def mt5_source_files(symbol: str) -> list[Path]:
    paths = sorted((ROOT / "data/mt5").glob(f"{symbol.lower()}_1m_ic_markets_mt5_*.csv"), key=lambda path: path.name)
    selected: list[Path] = []
    for path in paths:
        try:
            encoded_start = datetime.strptime(path.stem.split("_")[-2], "%Y%m%dT%H%M").replace(tzinfo=UTC)
        except (ValueError, IndexError):
            continue
        if encoded_start < END:
            selected.append(path)
    return selected


def _frame_from_file(path: Path, source_rank: int) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        usecols=("open_time", "open", "high", "low", "close", "volume", "spread_points"),
        dtype={"open": "float64", "high": "float64", "low": "float64", "close": "float64", "volume": "float64", "spread_points": "float64"},
    )
    timestamps = pd.to_datetime(frame.pop("open_time"), utc=True, errors="raise")
    # Pandas preserves the parsed datetime unit (microseconds for these CSVs).
    # Normalize explicitly to nanoseconds before converting to epoch minutes.
    frame.insert(0, "minute", (timestamps.dt.as_unit("ns").astype("int64") // 60_000_000_000).astype("int64"))
    frame["source_rank"] = np.int16(source_rank)
    frame["source_row"] = np.arange(len(frame), dtype=np.int32)
    return frame


def load_price_series(symbol: str, implementation: str) -> tuple[PriceSeries, dict[str, Any]]:
    paths = mt5_source_files(symbol)
    if not paths:
        raise FileNotFoundError(f"No sealed MT5 source for {symbol}")
    ordered_paths = paths if implementation == "primary" else list(reversed(paths))
    frames = [_frame_from_file(path, paths.index(path)) for path in ordered_paths]
    frame = pd.concat(frames, ignore_index=True)
    start_minute, end_minute = minute_of(START), minute_of(END)
    frame = frame[(frame["minute"] >= start_minute) & (frame["minute"] < end_minute)]
    if implementation == "primary":
        frame.sort_values(["minute", "source_rank", "source_row"], kind="mergesort", inplace=True)
        frame.drop_duplicates("minute", keep="first", inplace=True)
    else:
        minimum = frame.groupby("minute", sort=True, observed=True)["source_rank"].transform("min")
        frame = frame[frame["source_rank"] == minimum]
        frame.sort_values(["minute", "source_row"], kind="mergesort", inplace=True)
        frame.drop_duplicates("minute", keep="first", inplace=True)
    frame.sort_values("minute", kind="mergesort", inplace=True)
    minute = frame["minute"].to_numpy(dtype=np.int64, copy=True)
    if len(minute) == 0 or np.any(np.diff(minute) <= 0):
        raise ValueError(f"Non-unique/non-monotonic canonical series: {symbol}")
    inventory = [file_record(path) for path in paths]
    series = PriceSeries(
        symbol=symbol, minute=minute,
        open=frame["open"].to_numpy(dtype=np.float64, copy=True),
        high=frame["high"].to_numpy(dtype=np.float64, copy=True),
        low=frame["low"].to_numpy(dtype=np.float64, copy=True),
        close=frame["close"].to_numpy(dtype=np.float64, copy=True),
        volume=frame["volume"].to_numpy(dtype=np.float64, copy=True),
        spread=frame["spread_points"].to_numpy(dtype=np.float64, copy=True),
        source_inventory_hash=canonical_hash(inventory),
    )
    diagnostics = {
        "symbol": symbol, "source_files": len(paths), "canonical_rows": len(series.minute),
        "first_minute": iso_minute(int(series.minute[0])), "last_minute": iso_minute(int(series.minute[-1])),
        "source_inventory_hash": series.source_inventory_hash,
        "value_fields_used_as_predictors": True, "outcome_fields_calculated": False,
    }
    return series, diagnostics


def aggregate_primary(series: PriceSeries, size: int) -> AggSeries:
    bucket = (series.minute // size) * size
    starts, first, counts = np.unique(bucket, return_index=True, return_counts=True)
    opened = series.open[first]
    high = np.maximum.reduceat(series.high, first)
    low = np.minimum.reduceat(series.low, first)
    close = series.close[first + counts - 1]
    volume = np.add.reduceat(series.volume, first)
    required = size if size <= 15 else math.ceil(size * (0.75 if size <= 240 else 5 / 6))
    keep = counts >= required
    return AggSeries(size, starts[keep], starts[keep] + size, opened[keep], high[keep], low[keep], close[keep], volume[keep], counts[keep])


def aggregate_reference(series: PriceSeries, size: int) -> AggSeries:
    frame = pd.DataFrame({
        "bucket": (series.minute // size) * size, "open": series.open, "high": series.high,
        "low": series.low, "close": series.close, "volume": series.volume,
    })
    grouped = frame.groupby("bucket", sort=True, observed=True)
    summary = grouped.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"), count=("close", "size"))
    required = size if size <= 15 else math.ceil(size * (0.75 if size <= 240 else 5 / 6))
    summary = summary[summary["count"] >= required]
    starts = summary.index.to_numpy(dtype=np.int64)
    return AggSeries(
        size, starts, starts + size, summary["open"].to_numpy(dtype=np.float64),
        summary["high"].to_numpy(dtype=np.float64), summary["low"].to_numpy(dtype=np.float64),
        summary["close"].to_numpy(dtype=np.float64), summary["volume"].to_numpy(dtype=np.float64),
        summary["count"].to_numpy(dtype=np.int64),
    )


def aggregate_weeks(daily: AggSeries, implementation: str) -> AggSeries:
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    order = range(len(daily.start)) if implementation == "primary" else reversed(range(len(daily.start)))
    for index in order:
        iso = datetime_of(int(daily.start[index])).date().isocalendar()
        groups[(iso.year, iso.week)].append(index)
    rows: list[tuple[int, int, float, float, float, float, float, int]] = []
    for key in sorted(groups):
        indexes = sorted(groups[key])
        if len(indexes) < 4:
            continue
        first, last = indexes[0], indexes[-1]
        rows.append((int(daily.start[first]), int(daily.end[last]), float(daily.open[first]), float(np.max(daily.high[indexes])), float(np.min(daily.low[indexes])), float(daily.close[last]), float(np.sum(daily.volume[indexes])), len(indexes)))
    return AggSeries(
        10_080, np.asarray([row[0] for row in rows], dtype=np.int64), np.asarray([row[1] for row in rows], dtype=np.int64),
        np.asarray([row[2] for row in rows]), np.asarray([row[3] for row in rows]), np.asarray([row[4] for row in rows]),
        np.asarray([row[5] for row in rows]), np.asarray([row[6] for row in rows]), np.asarray([row[7] for row in rows], dtype=np.int64),
    )


def build_swings(series: AggSeries, implementation: str) -> dict[str, list[tuple[int, int, float]]]:
    highs: list[tuple[int, int, float]] = []
    lows: list[tuple[int, int, float]] = []
    indexes = range(2, len(series.start) - 2)
    if implementation == "reference":
        indexes = reversed(list(indexes))
    for center in indexes:
        neighbours = (center - 2, center - 1, center + 1, center + 2)
        known = int(series.end[center + 2])
        if all(float(series.high[center]) > float(series.high[index]) for index in neighbours):
            highs.append((known, center, float(series.high[center])))
        if all(float(series.low[center]) < float(series.low[index]) for index in neighbours):
            lows.append((known, center, float(series.low[center])))
    return {"HIGH": sorted(highs), "LOW": sorted(lows)}


def build_h4_breaks(h4: AggSeries, swings: dict[str, list[tuple[int, int, float]]]) -> list[dict[str, Any]]:
    highs, lows = swings["HIGH"], swings["LOW"]
    high_known = [row[0] for row in highs]
    low_known = [row[0] for row in lows]
    broken_highs: set[int] = set()
    broken_lows: set[int] = set()
    output: list[dict[str, Any]] = []
    for index in range(len(h4.end)):
        decision = int(h4.end[index])
        hi_pos = bisect.bisect_right(high_known, decision) - 1
        lo_pos = bisect.bisect_right(low_known, decision) - 1
        if hi_pos >= 0:
            _, pivot, price = highs[hi_pos]
            if pivot not in broken_highs and float(h4.close[index]) > price:
                broken_highs.add(pivot)
                origin = lows[max(0, bisect.bisect_right(low_known, decision) - 1)] if lows and lo_pos >= 0 else None
                output.append({"minute": decision, "direction": 1, "pivot": pivot, "price": price, "origin": origin})
        if lo_pos >= 0:
            _, pivot, price = lows[lo_pos]
            if pivot not in broken_lows and float(h4.close[index]) < price:
                broken_lows.add(pivot)
                origin = highs[max(0, bisect.bisect_right(high_known, decision) - 1)] if highs and hi_pos >= 0 else None
                output.append({"minute": decision, "direction": -1, "pivot": pivot, "price": price, "origin": origin})
    return sorted(output, key=lambda item: (item["minute"], item["direction"]))


def build_technical_bundle(series: PriceSeries, implementation: str) -> TechnicalBundle:
    aggregate = aggregate_primary if implementation == "primary" else aggregate_reference
    m5, m15 = aggregate(series, 5), aggregate(series, 15)
    h1, h4, d1 = aggregate(series, 60), aggregate(series, 240), aggregate(series, 1_440)
    w1 = aggregate_weeks(d1, implementation)
    swings = {size: build_swings(value, implementation) for size, value in ((15, m15), (60, h1), (240, h4))}
    return TechnicalBundle(series, m5, m15, h1, h4, d1, w1, swings, build_h4_breaks(h4, swings[240]))


def true_ranges(series: AggSeries) -> np.ndarray:
    if series.cached_true_range is not None:
        return series.cached_true_range
    values = series.high - series.low
    if len(values) > 1:
        values[1:] = np.maximum(values[1:], np.maximum(np.abs(series.high[1:] - series.close[:-1]), np.abs(series.low[1:] - series.close[:-1])))
    series.cached_true_range = values
    return series.cached_true_range


def atr_at(series: AggSeries, decision: int, length: int = 20) -> float | None:
    index = series.latest_index(decision)
    if index < length:
        return None
    values = true_ranges(series)[index - length + 1:index + 1]
    result = float(np.mean(values))
    return result if math.isfinite(result) and result > 0 else None


def latest_swing(swings: dict[str, list[tuple[int, int, float]]], side: str, decision: int) -> tuple[int, int, float] | None:
    values = swings[side]
    position = bisect.bisect_right([row[0] for row in values], decision) - 1
    return values[position] if position >= 0 else None


def pressure_state(series: AggSeries, decision: int) -> dict[str, Any]:
    index = series.latest_index(decision)
    if index < 14:
        return {"state": "UNKNOWN", "displacement": False}
    atr = float(np.mean(true_ranges(series)[index - 13:index + 1]))
    width = float(series.high[index] - series.low[index])
    body = float(series.close[index] - series.open[index])
    if atr <= 0 or width <= 0:
        return {"state": "UNKNOWN", "displacement": False}
    location = float((series.close[index] - series.low[index]) / width)
    state = "BULLISH" if body > 0 and location >= 2 / 3 else "BEARISH" if body < 0 and location <= 1 / 3 else "NEUTRAL"
    return {"state": state, "displacement": width >= atr and abs(body) / width >= 0.50, "close_minute": int(series.end[index])}


class MacroBook:
    def __init__(self, implementation: str) -> None:
        self.implementation = implementation
        self.series: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.positioning: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._context_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._load_fundamentals()
        self._load_positioning()
        self._load_events()

    def _load_fundamentals(self) -> None:
        records: list[dict[str, Any]] = []
        with gzip.open(FUNDAMENTALS, "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("record_type") != "FUNDAMENTAL_OBSERVATION":
                    continue
                available = parse_dt(str(record["available_at"]))
                observed = parse_dt(str(record["observation_time"]))
                if available >= END or observed >= END:
                    continue
                records.append({
                    "series": str(record["series_code"]), "available": minute_of(available),
                    "observed": minute_of(observed), "value": float(record["value"]),
                    "record_id": str(record["record_id"]), "record_hash": str(record["record_hash"]),
                })
        order = records if self.implementation == "primary" else reversed(records)
        for record in order:
            self.series[record["series"]].append(record)
        for values in self.series.values():
            values.sort(key=lambda item: (item["available"], item["observed"], item["record_id"]))

    def _load_positioning(self) -> None:
        records: list[dict[str, Any]] = []
        with gzip.open(POSITIONING, "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                available = minute_of(parse_dt(str(record["available_at"])))
                if available >= minute_of(END):
                    continue
                calculated = record.get("calculated", {})
                records.append({
                    "available": available, "record_id": record["record_id"], "record_hash": record["record_hash"],
                    "net_percentile": calculated.get("managed_money_net_percentile"),
                    "net_change": calculated.get("managed_money_net_change"),
                })
        self.positioning = sorted(records, key=lambda item: (item["available"], item["record_id"]))

    def _load_events(self) -> None:
        records: list[dict[str, Any]] = []
        with gzip.open(EVENTS, "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                code = str(record.get("event_code"))
                released = record.get("released_at") or record.get("scheduled_at")
                if code not in TIER1_EVENTS or not isinstance(released, str):
                    continue
                timestamp = parse_dt(released)
                if not START <= timestamp < END:
                    continue
                # Reaction snapshots and subsequent observations are intentionally never selected.
                records.append({
                    "event_id": str(record["record_id"]), "event_code": code,
                    "family": EVENT_ALIASES[code], "minute": minute_of(timestamp),
                    "available_minute": minute_of(parse_dt(str(record["event_available_at"]))),
                    "record_hash": str(record["record_hash"]),
                })
        self.events = sorted(records, key=lambda item: (item["minute"], item["event_code"], item["event_id"]))

    def _latest_pair(self, series: str, decision: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
        values = self.series.get(series, [])
        eligible = [row for row in values if row["available"] <= decision and row["observed"] <= decision]
        if not eligible:
            return None
        canonical: dict[int, dict[str, Any]] = {}
        for row in eligible:
            incumbent = canonical.get(row["observed"])
            if incumbent is None or (row["available"], row["record_id"]) >= (incumbent["available"], incumbent["record_id"]):
                canonical[row["observed"]] = row
        ordered = sorted(canonical.values(), key=lambda item: item["observed"])
        return (ordered[-1], ordered[-2]) if len(ordered) >= 2 else None

    def _component(self, component: str, decision: int) -> dict[str, Any]:
        signs: list[int] = []
        evidence: list[str] = []
        ages: list[int] = []
        for series in SERIES_COMPONENTS[component]:
            pair = self._latest_pair(series, decision)
            if pair is None:
                continue
            current, previous = pair
            delta = float(current["value"] - previous["value"])
            sign = 1 if delta > 0 else -1 if delta < 0 else 0
            if series in INVERT_COMPONENT_SERIES:
                sign *= -1
            signs.append(sign)
            evidence.extend((current["record_hash"], previous["record_hash"]))
            ages.append(max(0, decision - int(current["available"])))
        return {
            "sign": None if not signs else float(np.mean(signs)),
            "series_available": len(signs), "series_required": len(SERIES_COMPONENTS[component]),
            "maximum_age_minutes": max(ages) if ages else None, "evidence_hash": canonical_hash(sorted(evidence)),
        }

    def context(self, symbol: str, decision: int, direction: int) -> dict[str, Any]:
        cache_key = (symbol, decision, direction)
        if cache_key in self._context_cache:
            return self._context_cache[cache_key]
        weights = MACRO_WEIGHTS[symbol]
        components = {name: self._component(name, decision) for name in weights}
        available_weight = sum(abs(weight) for name, weight in weights.items() if components[name]["sign"] is not None)
        raw = sum(weight * float(components[name]["sign"]) for name, weight in weights.items() if components[name]["sign"] is not None)
        score = 100.0 * raw / available_weight if available_weight else None
        confidence = 100.0 * available_weight / sum(abs(value) for value in weights.values())
        if symbol == "USDJPY":
            confidence = min(confidence, 60.0)
        macro_direction = 0 if score is None or abs(score) < 20.0 else 1 if score > 0 else -1
        state = "UNKNOWN" if confidence < 60.0 or score is None else "NEUTRAL" if macro_direction == 0 else "ALIGNED" if macro_direction == direction else "OPPOSED"
        cot: dict[str, Any] | None = None
        if symbol in {"XAUUSD", "XAGUSD"}:
            eligible = [row for row in self.positioning if row["available"] <= decision]
            if eligible:
                latest = eligible[-1]
                cot = {key: latest[key] for key in ("record_id", "record_hash", "net_percentile", "net_change")}
        result = {
            "state": state, "score": round_float(score), "confidence": round_float(confidence) or 0.0,
            "macro_direction": macro_direction, "components": components, "cot_metals_context": cot,
            "point_in_time": True, "japanese_rates_available": False if symbol == "USDJPY" else None,
            "eia_inventory_available": False if symbol == "XTIUSD" else None,
        }
        self._context_cache[cache_key] = result
        return result


def load_cme_event_closes(event_minutes: set[int], implementation: str) -> dict[str, dict[int, float]]:
    wanted = {minute - 1 for minute in event_minutes} | {minute + 4 for minute in event_minutes}
    selected: dict[str, dict[int, tuple[int, float]]] = {"ZT.v.0": {}, "ZN.v.0": {}}
    manifest = load_json(CME_MANIFEST)
    paths = [Path(item["normalized"]) for item in manifest["normalization"]["files"]]
    order = paths if implementation == "primary" else reversed(paths)
    for path in order:
        source_rank = paths.index(path)
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol = row["symbol"]
                if symbol not in selected:
                    continue
                minute = minute_of(parse_dt(row["open_time"]))
                if minute in wanted:
                    candidate = (source_rank, float(row["close"]))
                    if minute not in selected[symbol] or source_rank < selected[symbol][minute][0]:
                        selected[symbol][minute] = candidate
    return {symbol: {minute: value for minute, (_, value) in rows.items()} for symbol, rows in selected.items()}


def extract_mt5_event_closes(symbol: str, event_minutes: set[int], implementation: str) -> dict[int, float]:
    wanted = {minute - 1 for minute in event_minutes} | {minute + 4 for minute in event_minutes}
    selected: dict[int, tuple[int, float]] = {}
    paths = mt5_source_files(symbol)
    order = paths if implementation == "primary" else reversed(paths)
    for path in order:
        source_rank = paths.index(path)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                minute = minute_of(parse_dt(row["open_time"]))
                if minute not in wanted:
                    continue
                candidate = (source_rank, float(row["close"]))
                if minute not in selected or candidate[0] < selected[minute][0]:
                    selected[minute] = candidate
    return {minute: value for minute, (_, value) in selected.items()}


def sign_change(values: Mapping[int, float], minute: int) -> int | None:
    before, after = values.get(minute - 1), values.get(minute + 4)
    if before is None or after is None or before == 0:
        return None
    change = after / before - 1.0
    return 1 if change > 0 else -1 if change < 0 else 0


def event_shock_directions(macro: MacroBook, implementation: str) -> dict[tuple[str, str], dict[str, Any]]:
    event_minutes = {item["minute"] for item in macro.events}
    cme = load_cme_event_closes(event_minutes, implementation)
    cross = {
        "EURUSD": extract_mt5_event_closes("EURUSD", event_minutes, implementation),
        "US500": extract_mt5_event_closes("US500", event_minutes, implementation),
        "USTEC": extract_mt5_event_closes("USTEC", event_minutes, implementation),
    }
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for event in macro.events:
        minute = int(event["minute"])
        signs = {
            "ZT": sign_change(cme["ZT.v.0"], minute), "ZN": sign_change(cme["ZN.v.0"], minute),
            "EURUSD": sign_change(cross["EURUSD"], minute), "US500": sign_change(cross["US500"], minute),
            "USTEC": sign_change(cross["USTEC"], minute),
        }
        mappings = {
            "XAUUSD": {"ZT": 0.35, "ZN": 0.25, "EURUSD": 0.40},
            "XAGUSD": {"ZT": 0.30, "ZN": 0.20, "EURUSD": 0.50},
            "EURUSD": {"ZT": 0.60, "ZN": 0.40},
            "USDJPY": {"ZT": -0.60, "ZN": -0.40},
            "USTEC": {"ZT": 0.45, "ZN": 0.25, "US500": 0.30},
            "US500": {"ZT": 0.45, "ZN": 0.25, "USTEC": 0.30},
            "XTIUSD": {"ZT": 0.15, "EURUSD": 0.45, "US500": 0.40},
        }
        for symbol, weights in mappings.items():
            coverage = sum(abs(weight) for name, weight in weights.items() if signs[name] is not None)
            raw = sum(weight * int(signs[name]) for name, weight in weights.items() if signs[name] is not None)
            score = raw / coverage if coverage else 0.0
            direction = 1 if coverage >= 0.60 and score >= 0.25 else -1 if coverage >= 0.60 and score <= -0.25 else 0
            output[(event["event_id"], symbol)] = {
                "direction": direction, "score": round_float(score), "coverage": round_float(coverage),
                "component_signs": signs, "available_at_minute": minute + 5,
                "lineage_hash": canonical_hash([event["record_hash"], signs, symbol]),
            }
    return output


def agg_window(series: AggSeries, start: int, end: int) -> list[int]:
    left = int(np.searchsorted(series.start, start, side="left"))
    right = int(np.searchsorted(series.end, end, side="right"))
    return [index for index in range(left, right) if int(series.start[index]) >= start and int(series.end[index]) <= end]


def raw_range(series: PriceSeries, start: int, end: int, minimum_fraction: float = 0.90) -> tuple[float, float, str] | None:
    bounds = series.contiguous(start, end, minimum_fraction)
    if bounds is None:
        return None
    left, right = bounds
    return float(np.max(series.high[left:right])), float(np.min(series.low[left:right])), canonical_hash([series.symbol, start, end, series.source_inventory_hash, left, right])


def prior_primary_range(bundle: TechnicalBundle, symbol: str, session: str, day: date, session_open: int) -> tuple[float, float, str] | None:
    if session == "LONDON_DECISION":
        zone = ZoneInfo("Europe/London")
        start = minute_of(datetime.combine(day, time(0, 0), zone).astimezone(UTC))
        end = minute_of(datetime.combine(day, time(7, 0), zone).astimezone(UTC))
        return raw_range(bundle.m1, start, end)
    if session == "NEW_YORK_DECISION":
        zone = ZoneInfo("Europe/London")
        start = minute_of(datetime.combine(day, time(7, 0), zone).astimezone(UTC))
        return raw_range(bundle.m1, start, session_open)
    timezone, start_time, end_time = (
        ("America/New_York", time(9, 30), time(16, 0))
        if session == "US_CASH_OPEN" else
        ("America/New_York", time(8, 0), time(14, 30))
    )
    zone = ZoneInfo(timezone)
    for offset in range(1, 8):
        prior_day = day - timedelta(days=offset)
        if prior_day.weekday() >= 5:
            continue
        start = minute_of(datetime.combine(prior_day, start_time, zone).astimezone(UTC))
        end = minute_of(datetime.combine(prior_day, end_time, zone).astimezone(UTC))
        value = raw_range(bundle.m1, start, end)
        if value is not None:
            return value
    return None


def make_range_levels(family: str, high: float, low: float, known: int, evidence: str) -> list[Level]:
    if not math.isfinite(high) or not math.isfinite(low) or high <= low:
        return []
    return [
        Level(f"{family}_HIGH::{known}", family, "UPPER", high, known),
        Level(f"{family}_LOW::{known}", family, "LOWER", low, known),
    ]


def levels_at(bundle: TechnicalBundle, session: str, day: date, session_open: int, decision: int, include_opening_range: bool = True) -> list[Level]:
    levels: list[Level] = []
    prior = prior_primary_range(bundle, bundle.m1.symbol, session, day, session_open)
    if prior is not None:
        levels.extend(make_range_levels("PRIOR_SESSION_RANGE", prior[0], prior[1], session_open, prior[2]))
    for family, series in (("PRIOR_DAY_RANGE", bundle.d1), ("PRIOR_WEEK_RANGE", bundle.w1)):
        index = series.latest_index(session_open)
        if index >= 0:
            levels.extend(make_range_levels(family, float(series.high[index]), float(series.low[index]), int(series.end[index]), canonical_hash([bundle.m1.symbol, family, int(series.start[index])])))
    for size, name in ((60, "H1_CONFIRMED_SWING"), (240, "H4_CONFIRMED_SWING")):
        for side, level_side in (("HIGH", "UPPER"), ("LOW", "LOWER")):
            values = [row for row in bundle.swings[size][side] if row[0] <= decision]
            for known, _, price in values[-2:]:
                levels.append(Level(f"{name}_{side}::{known}::{price:.10g}", name, level_side, price, known))
    if include_opening_range:
        _, _, opening_minutes = session_bounds(session, day)
        opening_end = session_open + opening_minutes
        if decision >= opening_end:
            opening = raw_range(bundle.m1, session_open, opening_end, 1.0)
            if opening is not None:
                levels.extend(make_range_levels("OPENING_RANGE", opening[0], opening[1], opening_end, opening[2]))
    unique: dict[tuple[str, str, float], Level] = {}
    for level in levels:
        if level.known_minute <= decision:
            unique.setdefault((level.family, level.side, round(level.price, 10)), level)
    return sorted(unique.values(), key=lambda item: (item.side, item.price, item.level_id))


def h4_trend(bundle: TechnicalBundle, decision: int) -> dict[str, Any] | None:
    breaks = [item for item in bundle.h4_breaks if int(item["minute"]) <= decision]
    if len(breaks) < 2 or breaks[-1]["direction"] != breaks[-2]["direction"]:
        return None
    latest = breaks[-1]
    direction = int(latest["direction"])
    origin = latest.get("origin")
    if origin is None:
        return None
    _, origin_index, origin_price = origin
    current_index = bundle.h4.latest_index(decision)
    if current_index < origin_index:
        return None
    terminal = float(np.max(bundle.h4.high[origin_index:current_index + 1])) if direction == 1 else float(np.min(bundle.h4.low[origin_index:current_index + 1]))
    width = terminal - float(origin_price) if direction == 1 else float(origin_price) - terminal
    if width <= 0:
        return None
    return {
        "direction": direction, "origin": float(origin_price), "terminal": terminal, "width": width,
        "latest_break_minute": int(latest["minute"]), "break_count_same_direction": sum(item["direction"] == direction for item in breaks[-2:]),
    }


def htf_features(bundle: TechnicalBundle, decision: int) -> dict[str, Any]:
    return {
        "W1": pressure_state(bundle.w1, decision), "D1": pressure_state(bundle.d1, decision),
        "H4": pressure_state(bundle.h4, decision), "H1": pressure_state(bundle.h1, decision),
        "H4_STRUCTURE": h4_trend(bundle, decision),
    }


def session_features(bundle: TechnicalBundle, start: int, decision: int) -> dict[str, Any]:
    bounds = bundle.m1.bounds(start, decision)
    left, right = bounds
    if right <= left:
        return {"available": False}
    ranges = bundle.m1.high[left:right] - bundle.m1.low[left:right]
    spread_price = bundle.m1.spread[left:right] * INSTRUMENTS[bundle.m1.symbol]["point"]
    return {
        "available": True, "elapsed_minutes": decision - start,
        "range": round_float(float(np.max(bundle.m1.high[left:right]) - np.min(bundle.m1.low[left:right]))),
        "mean_minute_range": round_float(float(np.mean(ranges))),
        "mean_tick_volume": round_float(float(np.mean(bundle.m1.volume[left:right]))),
        "mean_spread_price": round_float(float(np.mean(spread_price))),
    }


def signal_row(
    *, symbol: str, family: str, session: str, day: date, direction: int, decision: int,
    deadline: int, trigger_low: float, trigger_high: float, atr15: float,
    levels: Sequence[Level], macro: Mapping[str, Any], features: Mapping[str, Any],
    source_event_id: str | None = None,
) -> dict[str, Any]:
    fold = fold_for(day)
    if fold is None:
        raise ValueError(f"Signal outside OOF folds: {day}")
    opposed_block = family in {"E2_PRIOR_SESSION_SWEEP_RECLAIM", "E4_HTF_PULLBACK_RESOLUTION"} and macro["state"] == "OPPOSED"
    eligible = not opposed_block
    level_payload = [
        {"level_id": level.level_id, "family": level.family, "side": level.side, "price": level.price, "known_minute": level.known_minute}
        for level in levels if level.known_minute <= decision
    ]
    identity = [symbol, family, session, day.isoformat(), direction, decision, source_event_id]
    feature_payload = {
        **features, "macro_components": macro.get("components"), "cot_metals_context": macro.get("cot_metals_context"),
        "all_features_available_at_or_before_decision": True,
    }
    return {
        "signal_id": f"MAMSP-M3::{canonical_hash(identity)[:24]}", "instrument": symbol,
        "research_id": INSTRUMENTS[symbol]["research_id"], "cluster": INSTRUMENTS[symbol]["cluster"],
        "family": family, "session": session, "session_date": day.isoformat(), "fold": fold,
        "direction": direction, "decision_at_minute": decision, "deadline_minute": deadline,
        "macro_state": str(macro["state"]), "macro_score": macro.get("score"),
        "macro_confidence": float(macro.get("confidence", 0.0)), "trade_eligible": eligible,
        "no_trade_reason": "MACRO_OPPOSED_BY_FROZEN_FAMILY_POLICY" if opposed_block else "",
        "trigger_low": trigger_low, "trigger_high": trigger_high, "atr15": atr15,
        "known_levels_json": canonical_json(level_payload), "features_json": canonical_json(feature_payload),
        "source_event_id": source_event_id,
        "lineage_hash": canonical_hash([identity, level_payload, feature_payload, macro, trigger_low, trigger_high, atr15]),
    }


def aligned_event_session(symbol: str) -> str:
    sessions = INSTRUMENTS[symbol]["sessions"]
    if "NEW_YORK_DECISION" in sessions:
        return "NEW_YORK_DECISION"
    return sessions[0]


def detect_e1(
    bundle: TechnicalBundle, symbol: str, macro_book: MacroBook, shocks: Mapping[tuple[str, str], Mapping[str, Any]], implementation: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    events = macro_book.events if implementation == "primary" else list(reversed(macro_book.events))
    for event in events:
        day = datetime_of(int(event["minute"])).date()
        if fold_for(day) is None:
            continue
        shock = shocks[(event["event_id"], symbol)]
        story_direction = int(shock["direction"])
        if story_direction == 0:
            continue
        release = int(event["minute"])
        pre = raw_range(bundle.m1, release - 30, release, 1.0)
        atr = atr_at(bundle.m15, release, 20)
        if pre is None or atr is None:
            continue
        high, low, _ = pre
        candidates: list[tuple[int, int, float, float, str]] = []
        for window in range(6):
            start, end = release + 5 * window, release + 5 * (window + 1)
            bounds = bundle.m1.contiguous(start, end, 1.0)
            if bounds is None:
                continue
            left, right = bounds
            opened, closed = float(bundle.m1.open[left]), float(bundle.m1.close[right - 1])
            maximum, minimum = float(np.max(bundle.m1.high[left:right])), float(np.min(bundle.m1.low[left:right]))
            if story_direction == 1:
                if closed >= high + 0.10 * atr:
                    candidates.append((end, 1, minimum, maximum, "ACCEPTANCE"))
                elif maximum >= high + 0.05 * atr and closed < high:
                    candidates.append((end, -1, minimum, maximum, "REJECTION"))
            else:
                if closed <= low - 0.10 * atr:
                    candidates.append((end, -1, minimum, maximum, "ACCEPTANCE"))
                elif minimum <= low - 0.05 * atr and closed > low:
                    candidates.append((end, 1, minimum, maximum, "REJECTION"))
            if candidates:
                break
        if not candidates:
            continue
        decision, direction, trigger_low, trigger_high, state = min(candidates, key=lambda item: (item[0], item[4]))
        macro = macro_book.context(symbol, decision, direction)
        session = aligned_event_session(symbol)
        levels = levels_at(bundle, session, day, session_bounds(session, day)[0], decision, include_opening_range=False)
        levels.extend(make_range_levels("PRE_EVENT_RANGE", high, low, release, str(event["record_hash"])))
        features = {
            "event_family": event["family"], "event_code": event["event_code"], "event_state": state,
            "event_story_direction": story_direction, "event_story_score": shock["score"],
            "event_story_coverage": shock["coverage"], "event_story_components": shock["component_signs"],
            "htf": htf_features(bundle, decision), "session": session_features(bundle, release, decision),
        }
        output.append(signal_row(
            symbol=symbol, family=FAMILIES[0], session=session, day=day, direction=direction,
            decision=decision, deadline=release + 120, trigger_low=trigger_low, trigger_high=trigger_high,
            atr15=atr, levels=levels, macro=macro, features=features, source_event_id=event["event_id"],
        ))
    return sorted(output, key=lambda row: (row["decision_at_minute"], row["signal_id"]))


def detect_e2(
    bundle: TechnicalBundle, symbol: str, session: str, day: date, opened: int, closed: int, macro_book: MacroBook, implementation: str,
) -> list[dict[str, Any]]:
    if symbol not in {"XAUUSD", "XAGUSD", "EURUSD", "USDJPY"}:
        return []
    prior = prior_primary_range(bundle, symbol, session, day, opened)
    if prior is None:
        return []
    prior_high, prior_low, prior_hash = prior
    indexes = agg_window(bundle.m5, opened, closed)
    candidates: list[dict[str, Any]] = []
    level_order = (("UPPER", prior_high), ("LOWER", prior_low))
    if implementation == "reference":
        level_order = tuple(reversed(level_order))
    for side, level in level_order:
        for position, index in enumerate(indexes):
            decision = int(bundle.m5.end[index])
            atr = atr_at(bundle.m15, int(bundle.m5.start[index]), 20)
            if atr is None:
                continue
            swept = float(bundle.m5.high[index]) >= level + 0.05 * atr if side == "UPPER" else float(bundle.m5.low[index]) <= level - 0.05 * atr
            if not swept:
                continue
            for offset in range(3):
                if position + offset >= len(indexes):
                    break
                current = indexes[position + offset]
                reclaim = float(bundle.m5.close[current]) < level if side == "UPPER" else float(bundle.m5.close[current]) > level
                if not reclaim:
                    continue
                span = indexes[position:position + offset + 1]
                candidates.append({
                    "decision": int(bundle.m5.end[current]), "direction": -1 if side == "UPPER" else 1,
                    "low": float(np.min(bundle.m5.low[span])), "high": float(np.max(bundle.m5.high[span])),
                    "atr": atr, "side": side, "level": level,
                })
                break
            break
    if not candidates:
        return []
    first_time = min(item["decision"] for item in candidates)
    same = [item for item in candidates if item["decision"] == first_time]
    if len({item["direction"] for item in same}) != 1:
        return []
    candidate = min(same, key=lambda item: (item["side"], item["level"]))
    macro = macro_book.context(symbol, candidate["decision"], candidate["direction"])
    levels = levels_at(bundle, session, day, opened, candidate["decision"])
    features = {
        "swept_side": candidate["side"], "swept_level": candidate["level"],
        "prior_range_hash": prior_hash, "reclaim_within_completed_m5_bars": True,
        "htf": htf_features(bundle, candidate["decision"]), "session": session_features(bundle, opened, candidate["decision"]),
    }
    return [signal_row(
        symbol=symbol, family=FAMILIES[1], session=session, day=day,
        direction=candidate["direction"], decision=candidate["decision"], deadline=closed,
        trigger_low=candidate["low"], trigger_high=candidate["high"], atr15=candidate["atr"],
        levels=levels, macro=macro, features=features,
    )]


def detect_e3(
    bundle: TechnicalBundle, symbol: str, session: str, day: date, opened: int, closed: int, opening_minutes: int,
    macro_book: MacroBook, implementation: str,
) -> list[dict[str, Any]]:
    opening_end = opened + opening_minutes
    opening = raw_range(bundle.m1, opened, opening_end, 1.0)
    prior = prior_primary_range(bundle, symbol, session, day, opened)
    if opening is None or prior is None:
        return []
    boundaries = [
        ("OPENING_HIGH", "UPPER", opening[0]), ("OPENING_LOW", "LOWER", opening[1]),
        ("PRIOR_HIGH", "UPPER", prior[0]), ("PRIOR_LOW", "LOWER", prior[1]),
    ]
    if implementation == "reference":
        boundaries = list(reversed(boundaries))
    m15_indexes = agg_window(bundle.m15, opening_end, closed)
    candidates: list[dict[str, Any]] = []
    for boundary_name, side, level in boundaries:
        for breakout_index in m15_indexes:
            decision = int(bundle.m15.end[breakout_index])
            atr = atr_at(bundle.m15, int(bundle.m15.start[breakout_index]), 20)
            if atr is None:
                continue
            width = float(bundle.m15.high[breakout_index] - bundle.m15.low[breakout_index])
            body = float(bundle.m15.close[breakout_index] - bundle.m15.open[breakout_index])
            if width <= 0 or abs(body) / width < 0.60:
                continue
            location = float((bundle.m15.close[breakout_index] - bundle.m15.low[breakout_index]) / width)
            direction = 1 if side == "UPPER" else -1
            accepted = (
                float(bundle.m15.close[breakout_index]) >= level + 0.10 * atr and body > 0 and location >= 0.70
                if direction == 1 else
                float(bundle.m15.close[breakout_index]) <= level - 0.10 * atr and body < 0 and location <= 0.30
            )
            if not accepted:
                continue
            retests = [index for index in agg_window(bundle.m5, decision, min(closed, decision + 20))][:4]
            for retest_index in retests:
                touched = (
                    float(bundle.m5.low[retest_index]) <= level + 0.05 * atr and float(bundle.m5.high[retest_index]) >= level - 0.05 * atr
                )
                held = float(bundle.m5.close[retest_index]) > level if direction == 1 else float(bundle.m5.close[retest_index]) < level
                if touched and held:
                    candidates.append({
                        "decision": int(bundle.m5.end[retest_index]), "direction": direction,
                        "low": float(min(bundle.m15.low[breakout_index], bundle.m5.low[retest_index])),
                        "high": float(max(bundle.m15.high[breakout_index], bundle.m5.high[retest_index])),
                        "atr": atr, "boundary": boundary_name, "level": level,
                    })
                    break
            break
    if not candidates:
        return []
    candidate = min(candidates, key=lambda item: (item["decision"], item["boundary"], item["direction"]))
    macro = macro_book.context(symbol, candidate["decision"], candidate["direction"])
    levels = levels_at(bundle, session, day, opened, candidate["decision"])
    features = {
        "breakout_boundary": candidate["boundary"], "boundary_price": candidate["level"],
        "accepted_m15": True, "first_valid_retest_within_four_m5": True,
        "htf": htf_features(bundle, candidate["decision"]), "session": session_features(bundle, opened, candidate["decision"]),
    }
    return [signal_row(
        symbol=symbol, family=FAMILIES[2], session=session, day=day,
        direction=candidate["direction"], decision=candidate["decision"], deadline=closed,
        trigger_low=candidate["low"], trigger_high=candidate["high"], atr15=candidate["atr"],
        levels=levels, macro=macro, features=features,
    )]


def detect_e4(
    bundle: TechnicalBundle, symbol: str, session: str, day: date, opened: int, closed: int,
    macro_book: MacroBook, implementation: str,
) -> list[dict[str, Any]]:
    indexes = agg_window(bundle.m15, opened, closed)
    if implementation == "reference":
        # Candidate enumeration order differs, while final chronological selection is unchanged.
        indexes = list(reversed(indexes))
    candidates: list[dict[str, Any]] = []
    for index in indexes:
        decision = int(bundle.m15.end[index])
        trend = h4_trend(bundle, decision)
        atr = atr_at(bundle.m15, int(bundle.m15.start[index]), 20)
        if trend is None or atr is None:
            continue
        direction = int(trend["direction"])
        current = float(bundle.m15.close[index])
        retrace = (trend["terminal"] - current) / trend["width"] if direction == 1 else (current - trend["terminal"]) / trend["width"]
        if not 0.35 <= retrace <= 0.75:
            continue
        width = float(bundle.m15.high[index] - bundle.m15.low[index])
        body = float(bundle.m15.close[index] - bundle.m15.open[index])
        if width < 0.80 * atr or width <= 0 or abs(body) / width < 0.60 or body * direction <= 0:
            continue
        swing = latest_swing(bundle.swings[15], "HIGH" if direction == 1 else "LOW", decision - 1)
        if swing is None:
            continue
        minor_break = float(bundle.m15.close[index]) > swing[2] if direction == 1 else float(bundle.m15.close[index]) < swing[2]
        if not minor_break:
            continue
        levels = levels_at(bundle, session, day, opened, decision)
        relevant = [level for level in levels if level.family in {"H1_CONFIRMED_SWING", "H4_CONFIRMED_SWING", "PRIOR_DAY_RANGE"}]
        touched = [level for level in relevant if float(bundle.m15.low[index]) <= level.price + 0.15 * atr and float(bundle.m15.high[index]) >= level.price - 0.15 * atr]
        if not touched:
            continue
        candidates.append({
            "decision": decision, "direction": direction, "low": float(bundle.m15.low[index]),
            "high": float(bundle.m15.high[index]), "atr": atr, "trend": trend,
            "retrace": retrace, "levels": levels, "touched": [level.level_id for level in touched],
        })
    if not candidates:
        return []
    candidate = min(candidates, key=lambda item: (item["decision"], item["direction"], item["touched"]))
    macro = macro_book.context(symbol, candidate["decision"], candidate["direction"])
    features = {
        "h4_trend": candidate["trend"], "retracement_ratio": round_float(candidate["retrace"]),
        "touched_location_levels": candidate["touched"], "m15_displacement": True,
        "minor_structure_break": True, "htf": htf_features(bundle, candidate["decision"]),
        "session": session_features(bundle, opened, candidate["decision"]),
    }
    return [signal_row(
        symbol=symbol, family=FAMILIES[3], session=session, day=day,
        direction=candidate["direction"], decision=candidate["decision"], deadline=closed,
        trigger_low=candidate["low"], trigger_high=candidate["high"], atr15=candidate["atr"],
        levels=candidate["levels"], macro=macro, features=features,
    )]


def detect_session_signals(bundle: TechnicalBundle, symbol: str, macro_book: MacroBook, implementation: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    day = OOF_START.date()
    while day < END.date():
        if day.weekday() < 5:
            for session in INSTRUMENTS[symbol]["sessions"]:
                opened, closed, opening_minutes = session_bounds(session, day)
                if bundle.m1.contiguous(opened, closed, 0.90) is None:
                    continue
                output.extend(detect_e2(bundle, symbol, session, day, opened, closed, macro_book, implementation))
                output.extend(detect_e3(bundle, symbol, session, day, opened, closed, opening_minutes, macro_book, implementation))
                output.extend(detect_e4(bundle, symbol, session, day, opened, closed, macro_book, implementation))
        day += timedelta(days=1)
    return output


def materialize_implementation(implementation: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    macro = MacroBook(implementation)
    shocks = event_shock_directions(macro, implementation)
    rows: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {
        "implementation": implementation, "fundamental_observation_series": len(macro.series),
        "events": len(macro.events), "event_shock_states": len(shocks), "instruments": {},
        "outcomes_joined_or_calculated": False, "calendar_2025_or_2026_values_accessed": False,
    }
    for symbol in INSTRUMENTS:
        series, source_diagnostics = load_price_series(symbol, implementation)
        bundle = build_technical_bundle(series, implementation)
        instrument_rows = detect_e1(bundle, symbol, macro, shocks, implementation)
        instrument_rows.extend(detect_session_signals(bundle, symbol, macro, implementation))
        instrument_rows.sort(key=lambda row: (row["decision_at_minute"], row["family"], row["session"], row["signal_id"]))
        identities: set[str] = set()
        unique: list[dict[str, Any]] = []
        for row in instrument_rows:
            if row["signal_id"] not in identities:
                identities.add(row["signal_id"])
                unique.append(row)
        rows.extend(unique)
        diagnostics["instruments"][symbol] = {
            **source_diagnostics, "signals": len(unique),
            "families": dict(sorted(Counter(row["family"] for row in unique).items())),
            "sessions": dict(sorted(Counter(row["session"] for row in unique).items())),
            "technical_counts": {"M5": len(bundle.m5.start), "M15": len(bundle.m15.start), "H1": len(bundle.h1.start), "H4": len(bundle.h4.start), "D1": len(bundle.d1.start), "W1": len(bundle.w1.start)},
        }
        print(json.dumps({"phase": "OUTCOME_BLIND_MATERIALIZATION", "implementation": implementation, "instrument": symbol, "signals": len(unique)}), flush=True)
        del bundle, series
    rows.sort(key=lambda row: (row["decision_at_minute"], row["instrument"], row["family"], row["session"], row["signal_id"]))
    diagnostics["signals"] = len(rows)
    diagnostics["eligible_signals"] = sum(row["trade_eligible"] for row in rows)
    diagnostics["complete_rows_hash"] = canonical_hash(rows)
    diagnostics["registry_population"] = {
        f"{symbol}|{family}|{session}": sum(row["instrument"] == symbol and row["family"] == family and row["session"] == session for row in rows)
        for symbol in INSTRUMENTS for session in INSTRUMENTS[symbol]["sessions"] for family in FAMILIES
        if not (family == FAMILIES[1] and symbol not in {"XAUUSD", "XAGUSD", "EURUSD", "USDJPY"})
    }
    return rows, diagnostics


def materialize() -> None:
    verify_sealed_design()
    if any(path.exists() for path in (PRIMARY_SIGNALS, REFERENCE_SIGNALS, MATERIALIZATION_CERTIFICATION)):
        raise FileExistsError("Milestone-3 materialization artifact already exists")
    primary, primary_diag = materialize_implementation("primary")
    reference, reference_diag = materialize_implementation("reference")
    if primary != reference or primary_diag["complete_rows_hash"] != reference_diag["complete_rows_hash"]:
        raise ValueError("Independent point-in-time materializations disagree")
    write_parquet_exclusive(PRIMARY_SIGNALS, primary, SIGNAL_SCHEMA)
    write_parquet_exclusive(REFERENCE_SIGNALS, reference, SIGNAL_SCHEMA)
    if sha256_file(PRIMARY_SIGNALS) != sha256_file(REFERENCE_SIGNALS):
        raise ValueError("Signal Parquet files are not byte-identical")
    certification = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_MATERIALIZATION_1_0",
        "status": "PASS_OUTCOME_BLIND_POINT_IN_TIME_MATERIALIZATION",
        "completed_at_utc": utc_now(), "signals": len(primary),
        "primary": primary_diag, "reference": reference_diag,
        "primary_signals": file_record(PRIMARY_SIGNALS), "reference_signals": file_record(REFERENCE_SIGNALS),
        "byte_identical_parquet": True, "complete_rows_hash": primary_diag["complete_rows_hash"],
        "development_outcomes_opened": False, "relationships_calculated": False,
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(MATERIALIZATION_CERTIFICATION, certification)
    print(json.dumps({"status": certification["status"], "signals": len(primary), "eligible": primary_diag["eligible_signals"], "hash": primary_diag["complete_rows_hash"]}, indent=2))


def empty_trade(signal: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        **signal, "status": "NO_TRADE", "execution_reason": reason,
        "entry_minute": None, "exit_minute": None, "entry": None, "stop": None,
        "target": None, "exit": None, "exit_reason": None, "holding_minutes": None,
        "risk_price": None, "planned_volume": None, "actual_risk_usd": None,
        "gross_r": None, "cost_r": None, "net_r": None, "net_r_cost_1p5x": None,
        "net_r_cost_2x": None, "neighbor_low_net_r": None, "neighbor_high_net_r": None,
        "mfe_r": None, "mae_r": None, "net_pnl_usd": None,
        "outcome_lineage_hash": canonical_hash([signal["signal_id"], reason]),
    }


def target_for(entry: float, risk: float, direction: int, levels_json: str) -> float:
    levels = json.loads(levels_json)
    if direction == 1:
        candidates = sorted(
            float(level["price"]) for level in levels
            if level["side"] == "UPPER" and 1.25 * risk <= float(level["price"]) - entry <= 3.0 * risk
        )
        return candidates[0] if candidates else entry + 2.0 * risk
    candidates = sorted(
        (float(level["price"]) for level in levels if level["side"] == "LOWER" and 1.25 * risk <= entry - float(level["price"]) <= 3.0 * risk),
        reverse=True,
    )
    return candidates[0] if candidates else entry - 2.0 * risk


def _volume_for(symbol: str, entry: float, risk_price: float) -> tuple[float, float]:
    specification = INSTRUMENTS[symbol]
    usd_per_lot = risk_price * float(specification["contract"])
    if specification["quote"] == "JPY":
        usd_per_lot /= entry
    step = float(specification["volume_step"])
    volume = math.floor((25.0 / usd_per_lot) / step + 1e-12) * step if usd_per_lot > 0 else 0.0
    volume = round(volume, 8)
    if volume < float(specification["volume_min"]):
        return 0.0, 0.0
    return volume, volume * usd_per_lot


def _exit_primary(series: PriceSeries, left: int, right: int, direction: int, stop: float, target: float) -> tuple[int, float, str]:
    for index in range(left, right):
        opened = float(series.open[index])
        if (direction == 1 and opened <= stop) or (direction == -1 and opened >= stop):
            return index, opened, "STOP_GAP"
        stop_hit = float(series.low[index]) <= stop if direction == 1 else float(series.high[index]) >= stop
        target_hit = float(series.high[index]) >= target if direction == 1 else float(series.low[index]) <= target
        if stop_hit:
            return index, stop, "STOP"
        if target_hit:
            return index, target, "TARGET"
    return right - 1, float(series.close[right - 1]), "TIME"


def _exit_reference(series: PriceSeries, left: int, right: int, direction: int, stop: float, target: float) -> tuple[int, float, str]:
    opens = series.open[left:right]
    lows, highs = series.low[left:right], series.high[left:right]
    gap_mask = opens <= stop if direction == 1 else opens >= stop
    stop_mask = (lows <= stop if direction == 1 else highs >= stop) | gap_mask
    target_mask = highs >= target if direction == 1 else lows <= target
    stop_hits, target_hits = np.flatnonzero(stop_mask), np.flatnonzero(target_mask)
    stop_index = int(stop_hits[0]) if len(stop_hits) else math.inf
    target_index = int(target_hits[0]) if len(target_hits) else math.inf
    if stop_index <= target_index and stop_index != math.inf:
        index = left + int(stop_index)
        return index, float(series.open[index]) if bool(gap_mask[stop_index]) else stop, "STOP_GAP" if bool(gap_mask[stop_index]) else "STOP"
    if target_index != math.inf:
        return left + int(target_index), target, "TARGET"
    return right - 1, float(series.close[right - 1]), "TIME"


def simulate_variant(signal: Mapping[str, Any], series: PriceSeries, implementation: str, buffer_atr: float) -> dict[str, Any] | None:
    entry_minute = int(signal["decision_at_minute"]) + 1
    deadline = int(signal["deadline_minute"])
    if entry_minute >= deadline:
        return None
    bounds = series.contiguous(entry_minute, deadline, 1.0)
    if bounds is None:
        return None
    left, right = bounds
    entry = float(series.open[left])
    direction = int(signal["direction"])
    stop = float(signal["trigger_low"]) - buffer_atr * float(signal["atr15"]) if direction == 1 else float(signal["trigger_high"]) + buffer_atr * float(signal["atr15"])
    risk = abs(entry - stop)
    if risk < 0.25 * float(signal["atr15"]) or risk > 1.50 * float(signal["atr15"]):
        return None
    volume, actual_risk = _volume_for(str(signal["instrument"]), entry, risk)
    if volume <= 0 or actual_risk <= 0 or actual_risk > 25.0 + 1e-6:
        return None
    target = target_for(entry, risk, direction, str(signal["known_levels_json"]))
    exit_function = _exit_primary if implementation == "primary" else _exit_reference
    exit_index, exit_price, exit_reason = exit_function(series, left, right, direction, stop, target)
    gross_r = direction * (exit_price - entry) / risk
    point = float(INSTRUMENTS[str(signal["instrument"])]["point"])
    spread_price = max(float(series.spread[left]), float(series.spread[exit_index])) * point
    cost_r = max(spread_price / risk + 0.03, 0.05)
    path_high = float(np.max(series.high[left:exit_index + 1]))
    path_low = float(np.min(series.low[left:exit_index + 1]))
    mfe = (path_high - entry) / risk if direction == 1 else (entry - path_low) / risk
    mae = (entry - path_low) / risk if direction == 1 else (path_high - entry) / risk
    return {
        "entry_minute": entry_minute, "exit_minute": int(series.minute[exit_index]),
        "entry": entry, "stop": stop, "target": target, "exit": exit_price,
        "exit_reason": exit_reason, "holding_minutes": int(series.minute[exit_index]) - entry_minute + 1,
        "risk_price": risk, "planned_volume": volume, "actual_risk_usd": actual_risk,
        "gross_r": gross_r, "cost_r": cost_r, "net_r": gross_r - cost_r,
        "net_r_cost_1p5x": gross_r - 1.5 * cost_r, "net_r_cost_2x": gross_r - 2.0 * cost_r,
        "mfe_r": mfe, "mae_r": mae, "net_pnl_usd": actual_risk * (gross_r - cost_r),
    }


def calculate_trade(signal: Mapping[str, Any], series: PriceSeries, implementation: str) -> dict[str, Any]:
    if not bool(signal["trade_eligible"]):
        return empty_trade(signal, str(signal["no_trade_reason"]))
    base = simulate_variant(signal, series, implementation, 0.10)
    if base is None:
        return empty_trade(signal, "FROZEN_EXECUTION_OR_PATH_GATE")
    low = simulate_variant(signal, series, implementation, 0.08)
    high = simulate_variant(signal, series, implementation, 0.12)
    payload = {
        **signal, "status": "EXECUTED", "execution_reason": "",
        **{key: round_float(value) if isinstance(value, float) else value for key, value in base.items()},
        "neighbor_low_net_r": round_float(low["net_r"]) if low is not None else None,
        "neighbor_high_net_r": round_float(high["net_r"]) if high is not None else None,
    }
    payload["outcome_lineage_hash"] = canonical_hash([
        signal["signal_id"], implementation, base, None if low is None else low["net_r"], None if high is None else high["net_r"],
        series.source_inventory_hash,
    ])
    # The implementation label is deliberately excluded so reproduced rows can match.
    payload["outcome_lineage_hash"] = canonical_hash([
        signal["signal_id"], {key: payload[key] for key in ("entry_minute", "exit_minute", "entry", "stop", "target", "exit", "net_r")},
        series.source_inventory_hash,
    ])
    return payload


def load_sealed_signals() -> list[dict[str, Any]]:
    verify_sealed_design()
    certification = load_json(MATERIALIZATION_CERTIFICATION)
    if certification.get("status") != "PASS_OUTCOME_BLIND_POINT_IN_TIME_MATERIALIZATION":
        raise ValueError("Outcome-blind materialization did not pass")
    if certification["development_outcomes_opened"] or certification["calendar_2025_values_accessed"] or certification["calendar_2026_values_accessed"]:
        raise ValueError("Materialization is contaminated")
    primary = pq.read_table(PRIMARY_SIGNALS).to_pylist()
    reference = pq.read_table(REFERENCE_SIGNALS).to_pylist()
    if primary != reference or sha256_file(PRIMARY_SIGNALS) != sha256_file(REFERENCE_SIGNALS):
        raise ValueError("Sealed signal implementations changed")
    if canonical_hash(primary) != certification["complete_rows_hash"]:
        raise ValueError("Signal row checksum changed")
    return primary


def execute_all(signals: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    primary: list[dict[str, Any]] = []
    reference: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {"instruments": {}, "single_controlled_source_opening": True}
    by_symbol: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for signal in signals:
        by_symbol[str(signal["instrument"])].append(signal)
    for symbol in INSTRUMENTS:
        primary_series, primary_source = load_price_series(symbol, "primary")
        reference_series, reference_source = load_price_series(symbol, "reference")
        for field in ("minute", "open", "high", "low", "close", "volume", "spread"):
            if not np.array_equal(getattr(primary_series, field), getattr(reference_series, field)):
                raise ValueError(f"Independent canonical outcome sources disagree for {symbol}: {field}")
        selected = sorted(by_symbol[symbol], key=lambda row: (row["decision_at_minute"], row["signal_id"]))
        primary_rows = [calculate_trade(row, primary_series, "primary") for row in selected]
        reference_rows = [calculate_trade(row, reference_series, "reference") for row in selected]
        if primary_rows != reference_rows:
            raise ValueError(f"Independent execution disagrees for {symbol}")
        primary.extend(primary_rows)
        reference.extend(reference_rows)
        diagnostics["instruments"][symbol] = {
            "primary_source": primary_source, "reference_source": reference_source,
            "canonical_source_equality": True, "signals": len(selected), "executed": sum(row["status"] == "EXECUTED" for row in primary_rows),
            "no_trade": sum(row["status"] != "EXECUTED" for row in primary_rows),
        }
        del primary_series, reference_series
    ordering = lambda row: (row["decision_at_minute"], row["instrument"], row["family"], row["session"], row["signal_id"])
    primary.sort(key=ordering)
    reference.sort(key=ordering)
    return primary, reference, diagnostics


def _safe_mean(values: Sequence[float]) -> float | None:
    return round_float(float(np.mean(values))) if values else None


def _profit_factor(values: Sequence[float]) -> float | None:
    positive = float(sum(value for value in values if value > 0))
    negative = float(-sum(value for value in values if value < 0))
    if negative == 0:
        return None if positive == 0 else float("inf")
    return round_float(positive / negative)


def _maximum_drawdown(values: Sequence[float], scale: float = 0.25) -> float:
    peak = 0.0
    equity = 0.0
    maximum = 0.0
    for value in values:
        equity += scale * value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return round_float(maximum) or 0.0


def _cluster_arrays(rows: Sequence[Mapping[str, Any]], field: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if value is not None and math.isfinite(float(value)):
            groups[str(row["session_date"])].append(float(value))
    dates = sorted(groups)
    sums = np.asarray([sum(groups[day]) for day in dates], dtype=np.float64)
    counts = np.asarray([len(groups[day]) for day in dates], dtype=np.float64)
    return sums, counts, dates


def clustered_mean_bootstrap(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    sums, counts, dates = _cluster_arrays(rows, field)
    if not dates:
        return {"clusters": 0, "ci95": [None, None], "probability_le_zero": None, "bootstrap_checksum": None}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    results = np.empty(BOOTSTRAPS, dtype=np.float64)
    batch = 250
    for start in range(0, BOOTSTRAPS, batch):
        size = min(batch, BOOTSTRAPS - start)
        indexes = rng.integers(0, len(dates), size=(size, len(dates)))
        results[start:start + size] = np.sum(sums[indexes], axis=1) / np.sum(counts[indexes], axis=1)
    low, high = np.quantile(results, (0.025, 0.975))
    probability = (float(np.count_nonzero(results <= 0.0)) + 1.0) / (BOOTSTRAPS + 1.0)
    return {
        "clusters": len(dates), "ci95": [round_float(float(low)), round_float(float(high))],
        "probability_le_zero": round_float(probability),
        "bootstrap_checksum": hashlib.sha256(results.astype("<f8", copy=False).tobytes()).hexdigest(),
    }


def clustered_lift_bootstrap(condition: Sequence[Mapping[str, Any]], complement: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    condition_groups: dict[str, list[float]] = defaultdict(list)
    complement_groups: dict[str, list[float]] = defaultdict(list)
    for row in condition:
        condition_groups[str(row["session_date"])].append(float(row["net_r"]))
    for row in complement:
        complement_groups[str(row["session_date"])].append(float(row["net_r"]))
    dates = sorted(set(condition_groups) | set(complement_groups))
    if not dates or not condition or not complement:
        return {"clusters": len(dates), "ci95": [None, None], "probability_le_zero": None, "bootstrap_checksum": None}
    condition_sums = np.asarray([sum(condition_groups[day]) for day in dates], dtype=np.float64)
    condition_counts = np.asarray([len(condition_groups[day]) for day in dates], dtype=np.float64)
    complement_sums = np.asarray([sum(complement_groups[day]) for day in dates], dtype=np.float64)
    complement_counts = np.asarray([len(complement_groups[day]) for day in dates], dtype=np.float64)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    results = np.empty(BOOTSTRAPS, dtype=np.float64)
    batch = 250
    for start in range(0, BOOTSTRAPS, batch):
        size = min(batch, BOOTSTRAPS - start)
        indexes = rng.integers(0, len(dates), size=(size, len(dates)))
        condition_denominator = np.sum(condition_counts[indexes], axis=1)
        complement_denominator = np.sum(complement_counts[indexes], axis=1)
        valid = (condition_denominator > 0) & (complement_denominator > 0)
        batch_results = np.full(size, np.nan, dtype=np.float64)
        batch_results[valid] = (
            np.sum(condition_sums[indexes], axis=1)[valid] / condition_denominator[valid]
            - np.sum(complement_sums[indexes], axis=1)[valid] / complement_denominator[valid]
        )
        results[start:start + size] = batch_results
    valid_results = results[np.isfinite(results)]
    if not len(valid_results):
        return {"clusters": len(dates), "ci95": [None, None], "probability_le_zero": None, "bootstrap_checksum": None}
    low, high = np.quantile(valid_results, (0.025, 0.975))
    probability = (float(np.count_nonzero(valid_results <= 0.0)) + 1.0) / (len(valid_results) + 1.0)
    return {
        "clusters": len(dates), "ci95": [round_float(float(low)), round_float(float(high))],
        "probability_le_zero": round_float(probability),
        "bootstrap_checksum": hashlib.sha256(valid_results.astype("<f8", copy=False).tobytes()).hexdigest(),
    }


def apply_candidate_overlap(rows: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    accepted: list[Mapping[str, Any]] = []
    active_until = -1
    seen_family_sessions: set[tuple[str, str, str, str]] = set()
    diagnostics = {"non_executable": 0, "same_family_session_suppressed": 0, "active_position_suppressed": 0}
    for row in sorted(rows, key=lambda item: (int(item["decision_at_minute"]), str(item["signal_id"]))):
        if row["status"] != "EXECUTED":
            diagnostics["non_executable"] += 1
            continue
        identity = (str(row["instrument"]), str(row["family"]), str(row["session"]), str(row["session_date"]))
        if identity in seen_family_sessions:
            diagnostics["same_family_session_suppressed"] += 1
            continue
        seen_family_sessions.add(identity)
        if int(row["entry_minute"]) <= active_until:
            diagnostics["active_position_suppressed"] += 1
            continue
        accepted.append(row)
        active_until = int(row["exit_minute"])
    return accepted, diagnostics


def support_stage1(signals: Sequence[Mapping[str, Any]], executed: int) -> dict[str, Any]:
    fold_counts = {str(fold): sum(int(row["fold"]) == fold for row in signals) for fold in range(1, 7)}
    direction_counts = {str(direction): sum(int(row["direction"]) == direction for row in signals) for direction in (-1, 1)}
    gates = {
        "cases_gte_90": len(signals) >= 90,
        "dates_gte_60": len({str(row["session_date"]) for row in signals}) >= 60,
        "each_fold_gte_15": all(value >= 15 for value in fold_counts.values()),
        "each_direction_gte_30": all(value >= 30 for value in direction_counts.values()),
        "executed_after_frozen_rules_gte_60": executed >= 60,
    }
    return {
        "eligible_signal_cases": len(signals), "dates": len({str(row["session_date"]) for row in signals}),
        "fold_counts": fold_counts, "direction_counts": direction_counts, "executed_cases": executed,
        "gates": gates, "passed": all(gates.values()),
    }


def support_stage2(signals: Sequence[Mapping[str, Any]], state: str, condition_executed: int, complement_executed: int) -> dict[str, Any]:
    condition = [row for row in signals if row["macro_state"] == state]
    complement = [row for row in signals if row["macro_state"] != state]
    fold_counts = {str(fold): sum(int(row["fold"]) == fold for row in signals) for fold in range(1, 7)}
    condition_fold_counts = {str(fold): sum(int(row["fold"]) == fold for row in condition) for fold in range(1, 7)}
    gates = {
        "cases_gte_60": len(signals) >= 60,
        "dates_gte_40": len({str(row["session_date"]) for row in signals}) >= 40,
        "each_fold_gte_10": all(value >= 10 for value in fold_counts.values()),
        "condition_state_cases_gte_20": len(condition) >= 20,
        "complement_cases_gte_20": len(complement) >= 20,
        "condition_present_in_four_folds": sum(value > 0 for value in condition_fold_counts.values()) >= 4,
        "condition_executed_gte_30": condition_executed >= 30,
        "complement_executed_gte_30": complement_executed >= 30,
    }
    return {
        "eligible_signal_cases": len(signals), "dates": len({str(row["session_date"]) for row in signals}),
        "condition_signal_cases": len(condition), "complement_signal_cases": len(complement),
        "fold_counts": fold_counts, "condition_fold_counts": condition_fold_counts,
        "condition_executed": condition_executed, "complement_executed": complement_executed,
        "gates": gates, "passed": all(gates.values()),
    }


def economic_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (int(row["entry_minute"]), str(row["signal_id"])))
    values = [float(row["net_r"]) for row in ordered]
    gross = [float(row["gross_r"]) for row in ordered]
    stress_1p5 = [float(row["net_r_cost_1p5x"]) for row in ordered]
    stress_2x = [float(row["net_r_cost_2x"]) for row in ordered]
    folds = {str(fold): _safe_mean([float(row["net_r"]) for row in ordered if int(row["fold"]) == fold]) for fold in range(1, 7)}
    years = {str(year): _safe_mean([float(row["net_r"]) for row in ordered if str(row["session_date"]).startswith(str(year))]) for year in range(2022, 2025)}
    sessions = {session: _safe_mean([float(row["net_r"]) for row in ordered if row["session"] == session]) for session in sorted({str(row["session"]) for row in ordered})}
    positive = [value for value in values if value > 0]
    negative = [value for value in values if value < 0]
    bootstrap = clustered_mean_bootstrap(ordered, "net_r")
    neighbor_means = {
        "buffer_0p08": _safe_mean([float(row["neighbor_low_net_r"]) for row in ordered if row["neighbor_low_net_r"] is not None]),
        "buffer_0p10": _safe_mean(values),
        "buffer_0p12": _safe_mean([float(row["neighbor_high_net_r"]) for row in ordered if row["neighbor_high_net_r"] is not None]),
    }
    return {
        "executed": len(ordered), "wins": sum(value > 0 for value in values),
        "win_rate": round_float(sum(value > 0 for value in values) / len(values)) if values else None,
        "gross_expectancy_r": _safe_mean(gross), "net_expectancy_r": _safe_mean(values),
        "profit_factor": _profit_factor(values), "average_win_r": _safe_mean(positive),
        "average_loss_r": _safe_mean(negative), "total_net_r": round_float(sum(values)),
        "stressed_1p5x_expectancy_r": _safe_mean(stress_1p5), "stressed_2x_expectancy_r": _safe_mean(stress_2x),
        "mfe_r": _safe_mean([float(row["mfe_r"]) for row in ordered]),
        "mae_r": _safe_mean([float(row["mae_r"]) for row in ordered]),
        "normalized_pnl_usd_at_25_risk": round_float(25.0 * sum(values)),
        "broker_executable_pnl_usd": round_float(sum(float(row["net_pnl_usd"]) for row in ordered)),
        "maximum_drawdown_pct_at_0p25pct_risk": _maximum_drawdown(values),
        "fold_expectancy_r": folds, "year_expectancy_r": years, "session_expectancy_r": sessions,
        "positive_folds": sum(value is not None and value > 0 for value in folds.values()),
        "positive_years": sum(value is not None and value > 0 for value in years.values()),
        "neighbor_expectancy_r": neighbor_means,
        "positive_neighbor_signs": sum(value is not None and value > 0 for value in neighbor_means.values()),
        "uncertainty": bootstrap,
    }


def _adjust_bh(results: list[dict[str, Any]]) -> None:
    total = len(results)
    ordered = sorted(range(total), key=lambda index: (float(results[index]["raw_p"]), results[index]["test_id"]))
    adjusted = [1.0] * total
    running = 1.0
    for reverse_rank in range(total - 1, -1, -1):
        index = ordered[reverse_rank]
        rank = reverse_rank + 1
        running = min(running, float(results[index]["raw_p"]) * total / rank)
        adjusted[index] = min(1.0, running)
    for index, value in enumerate(adjusted):
        results[index]["adjusted_p"] = round_float(value)
        results[index]["multiplicity_pass"] = value <= 0.05


def _adjust_holm(results: list[dict[str, Any]]) -> None:
    total = len(results)
    ordered = sorted(range(total), key=lambda index: (float(results[index]["raw_p"]), results[index]["test_id"]))
    adjusted = [1.0] * total
    running = 0.0
    for rank, index in enumerate(ordered, start=1):
        running = max(running, (total - rank + 1) * float(results[index]["raw_p"]))
        adjusted[index] = min(1.0, running)
    for index, value in enumerate(adjusted):
        results[index]["adjusted_p"] = round_float(value)
        results[index]["multiplicity_pass"] = value <= 0.05


def candidate_gate_result(result: Mapping[str, Any], stage: int) -> tuple[dict[str, bool], str]:
    support = bool(result["support"]["passed"])
    metrics = result["metrics"]
    ci_low = metrics["uncertainty"]["ci95"][0]
    pf = metrics["profit_factor"]
    gates = {
        "support": support,
        "net_oof_expectancy_gt_0": metrics["net_expectancy_r"] is not None and metrics["net_expectancy_r"] > 0,
        "profit_factor_gte_1p15": pf is not None and pf >= 1.15,
        "clustered_ci95_low_gt_0": ci_low is not None and ci_low > 0,
        "multiplicity_pass": bool(result.get("multiplicity_pass", False)),
        "cost_1p5x_expectancy_gt_0": metrics["stressed_1p5x_expectancy_r"] is not None and metrics["stressed_1p5x_expectancy_r"] > 0,
        "positive_folds_gte_4": metrics["positive_folds"] >= 4,
        "positive_years_gte_2": metrics["positive_years"] >= 2,
        "neighbor_sign_agreement_gte_2_of_3": metrics["positive_neighbor_signs"] >= 2,
        "maximum_drawdown_pct_lte_10": metrics["maximum_drawdown_pct_at_0p25pct_risk"] <= 10.0,
        # Each registered hypothesis is session-specific; concentration is evaluated when sessions are combined.
        "fixed_session_candidate_concentration_gate_not_applicable": True,
    }
    if stage == 2:
        lift_low = result["lift_uncertainty"]["ci95"][0]
        gates["positive_incremental_lift_ci95_low_gt_0"] = lift_low is not None and lift_low > 0
    verdict = "PASS_PROVISIONAL_UNVALIDATED" if all(gates.values()) else "REJECT"
    return gates, verdict


def _test_rows(trades: Sequence[Mapping[str, Any]], test: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        row for row in trades
        if row["instrument"] == test["instrument"] and row["family"] == test["family"] and row["session"] == test["session"]
        and bool(row["trade_eligible"])
    ]


def calculate_stage1(trades: Sequence[Mapping[str, Any]], registry: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for test in registry:
        raw = _test_rows(trades, test)
        overlap, overlap_diag = apply_candidate_overlap(raw)
        support = support_stage1(raw, len(overlap))
        metrics = economic_metrics(overlap)
        raw_p = metrics["uncertainty"]["probability_le_zero"] if support["passed"] else 1.0
        results.append({
            **test, "support": support, "overlap": overlap_diag, "metrics": metrics,
            "raw_p": raw_p if raw_p is not None else 1.0,
        })
    _adjust_bh(results)
    for result in results:
        result["gates"], result["verdict"] = candidate_gate_result(result, 1)
    return results


def calculate_stage2(trades: Sequence[Mapping[str, Any]], registry: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for test in registry:
        raw = _test_rows(trades, test)
        overlap, overlap_diag = apply_candidate_overlap(raw)
        condition = [row for row in overlap if row["macro_state"] == test["macro_state"]]
        complement = [row for row in overlap if row["macro_state"] != test["macro_state"]]
        support = support_stage2(raw, str(test["macro_state"]), len(condition), len(complement))
        metrics = economic_metrics(condition)
        complement_metrics = economic_metrics(complement)
        lift = (
            float(metrics["net_expectancy_r"]) - float(complement_metrics["net_expectancy_r"])
            if metrics["net_expectancy_r"] is not None and complement_metrics["net_expectancy_r"] is not None else None
        )
        lift_uncertainty = clustered_lift_bootstrap(condition, complement)
        raw_p = lift_uncertainty["probability_le_zero"] if support["passed"] else 1.0
        results.append({
            **test, "support": support, "overlap": overlap_diag, "metrics": metrics,
            "complement_metrics": complement_metrics, "incremental_lift_r": round_float(lift),
            "lift_uncertainty": lift_uncertainty, "raw_p": raw_p if raw_p is not None else 1.0,
        })
    _adjust_holm(results)
    for result in results:
        result["gates"], result["verdict"] = candidate_gate_result(result, 2)
    return results


def select_candidates(stage1: Sequence[Mapping[str, Any]], stage2: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    passing = [dict(result, stage=1) for result in stage1 if result["verdict"] == "PASS_PROVISIONAL_UNVALIDATED"]
    passing.extend(dict(result, stage=2) for result in stage2 if result["verdict"] == "PASS_PROVISIONAL_UNVALIDATED")
    passing.sort(key=lambda row: (
        float(row["adjusted_p"]),
        -float(np.median([value for value in row["metrics"]["fold_expectancy_r"].values() if value is not None])),
        -float(row["metrics"]["profit_factor"]), -int(row["metrics"]["executed"]), str(row["test_id"]),
    ))
    selected: list[dict[str, Any]] = []
    instrument_counts: Counter[str] = Counter()
    instrument_families: set[tuple[str, str]] = set()
    for result in passing:
        instrument = str(result["instrument"])
        family_key = (instrument, str(result["family"]))
        if instrument_counts[instrument] >= 2 or family_key in instrument_families or len(selected) >= 8:
            continue
        selected.append({
            "candidate_id": str(result["test_id"]), "stage": int(result["stage"]),
            "instrument": instrument, "research_id": result["research_id"], "cluster": result["cluster"],
            "family": result["family"], "session": result["session"],
            "macro_state": result.get("macro_state"), "rank": len(selected) + 1,
        })
        instrument_counts[instrument] += 1
        instrument_families.add(family_key)
    return selected


def candidate_trades(candidate: Mapping[str, Any], trades: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    raw = _test_rows(trades, candidate)
    accepted, _ = apply_candidate_overlap(raw)
    if int(candidate["stage"]) == 2:
        accepted = [row for row in accepted if row["macro_state"] == candidate["macro_state"]]
    return accepted


def construct_portfolio(candidates: Sequence[Mapping[str, Any]], trades: Sequence[Mapping[str, Any]], event_minutes: Sequence[int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    proposed: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    for candidate in candidates:
        for row in candidate_trades(candidate, trades):
            if str(row["signal_id"]) in seen_signals:
                continue
            seen_signals.add(str(row["signal_id"]))
            proposed.append({**row, "candidate_id": candidate["candidate_id"], "candidate_rank": candidate["rank"]})
    proposed.sort(key=lambda row: (int(row["entry_minute"]), str(row["instrument"]), str(row["candidate_id"]), str(row["signal_id"])))
    accepted: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    diagnostics = {"proposed": len(proposed), "duplicate_signal_suppressed": 0, "instrument_capacity": 0, "cluster_capacity": 0, "portfolio_capacity": 0, "macro_supercluster_capacity": 0}
    sorted_events = sorted(event_minutes)
    for row in proposed:
        entered = int(row["entry_minute"])
        active = [item for item in active if int(item["exit_minute"]) >= entered]
        if any(item["instrument"] == row["instrument"] for item in active):
            diagnostics["instrument_capacity"] += 1
            continue
        same_cluster = sum(item["cluster"] == row["cluster"] for item in active)
        if same_cluster >= 4:
            diagnostics["cluster_capacity"] += 1
            continue
        if len(active) >= 8:
            diagnostics["portfolio_capacity"] += 1
            continue
        position = bisect.bisect_left(sorted_events, entered - 120)
        in_macro_window = position < len(sorted_events) and sorted_events[position] <= entered + 15
        if in_macro_window and len(active) >= 4:
            diagnostics["macro_supercluster_capacity"] += 1
            continue
        accepted.append(row)
        active.append(row)
    diagnostics["accepted"] = len(accepted)
    return accepted, diagnostics


def portfolio_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (int(row["entry_minute"]), str(row["instrument"]), str(row["candidate_id"])))
    actual_portfolio_r = [float(row["net_pnl_usd"]) / 100.0 for row in ordered]
    normalized_portfolio_r = [0.25 * float(row["net_r"]) for row in ordered]
    stressed_portfolio_r = [float(row["actual_risk_usd"]) * float(row["net_r_cost_1p5x"]) / 100.0 for row in ordered]
    statistical_rows = [{**row, "portfolio_r": value} for row, value in zip(ordered, actual_portfolio_r)]
    uncertainty = clustered_mean_bootstrap(statistical_rows, "portfolio_r")
    fold_totals = {str(fold): round_float(sum(value for row, value in zip(ordered, actual_portfolio_r) if int(row["fold"]) == fold)) for fold in range(1, 7)}
    year_totals = {str(year): round_float(sum(value for row, value in zip(ordered, actual_portfolio_r) if str(row["session_date"]).startswith(str(year)))) for year in range(2022, 2025)}
    instrument_totals = {instrument: round_float(sum(value for row, value in zip(ordered, actual_portfolio_r) if row["instrument"] == instrument)) for instrument in INSTRUMENTS}
    cluster_totals = {cluster: round_float(sum(value for row, value in zip(ordered, actual_portfolio_r) if row["cluster"] == cluster)) for cluster in sorted({str(item["cluster"]) for item in INSTRUMENTS.values()})}
    positive_instrument = {key: max(0.0, float(value or 0.0)) for key, value in instrument_totals.items()}
    positive_cluster = {key: max(0.0, float(value or 0.0)) for key, value in cluster_totals.items()}
    total_positive_instrument = sum(positive_instrument.values())
    total_positive_cluster = sum(positive_cluster.values())
    actual_total = sum(actual_portfolio_r)
    return {
        "trades": len(ordered), "trades_per_month": round_float(len(ordered) / 36.0),
        "win_rate": round_float(sum(value > 0 for value in actual_portfolio_r) / len(actual_portfolio_r)) if actual_portfolio_r else None,
        "expectancy_portfolio_r_per_trade": _safe_mean(actual_portfolio_r),
        "profit_factor": _profit_factor(actual_portfolio_r),
        "net_portfolio_r": round_float(actual_total), "portfolio_r_per_month": round_float(actual_total / 36.0),
        "net_pnl_usd": round_float(actual_total * 100.0), "dollars_per_month": round_float(actual_total * 100.0 / 36.0),
        "normalized_net_portfolio_r": round_float(sum(normalized_portfolio_r)),
        "stressed_1p5x_portfolio_r_per_trade": _safe_mean(stressed_portfolio_r),
        "stressed_1p5x_portfolio_r_per_month": round_float(sum(stressed_portfolio_r) / 36.0),
        "maximum_drawdown_pct": _maximum_drawdown(actual_portfolio_r, scale=1.0),
        "fold_net_portfolio_r": fold_totals, "year_net_portfolio_r": year_totals,
        "positive_folds": sum(float(value or 0.0) > 0 for value in fold_totals.values()),
        "positive_years": sum(float(value or 0.0) > 0 for value in year_totals.values()),
        "instrument_contribution_portfolio_r": instrument_totals, "cluster_contribution_portfolio_r": cluster_totals,
        "maximum_instrument_positive_pnl_share": round_float(max(positive_instrument.values(), default=0.0) / total_positive_instrument) if total_positive_instrument > 0 else None,
        "maximum_cluster_positive_pnl_share": round_float(max(positive_cluster.values(), default=0.0) / total_positive_cluster) if total_positive_cluster > 0 else None,
        "uncertainty": uncertainty,
    }


def portfolio_gates(metrics: Mapping[str, Any], has_candidates: bool) -> dict[str, bool]:
    ci_low = metrics["uncertainty"]["ci95"][0]
    pf = metrics["profit_factor"]
    return {
        "independently_passing_candidates_present": has_candidates,
        "net_expectancy_gt_0": metrics["expectancy_portfolio_r_per_trade"] is not None and metrics["expectancy_portfolio_r_per_trade"] > 0,
        "profit_factor_gte_1p15": pf is not None and pf >= 1.15,
        "clustered_ci95_low_gt_0": ci_low is not None and ci_low > 0,
        "cost_1p5x_expectancy_gt_0": metrics["stressed_1p5x_portfolio_r_per_trade"] is not None and metrics["stressed_1p5x_portfolio_r_per_trade"] > 0,
        "positive_folds_gte_4": metrics["positive_folds"] >= 4,
        "positive_years_gte_2": metrics["positive_years"] >= 2,
        "maximum_drawdown_pct_lte_15": metrics["maximum_drawdown_pct"] <= 15.0,
        "maximum_instrument_positive_pnl_share_lte_0p50": metrics["maximum_instrument_positive_pnl_share"] is not None and metrics["maximum_instrument_positive_pnl_share"] <= 0.50,
        "maximum_cluster_positive_pnl_share_lte_0p50": metrics["maximum_cluster_positive_pnl_share"] is not None and metrics["maximum_cluster_positive_pnl_share"] <= 0.50,
    }


def calculate_portfolio_result(
    trades: Sequence[Mapping[str, Any]], stage1: Sequence[Mapping[str, Any]], stage2: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidates = select_candidates(stage1, stage2)
    event_minutes = [int(event["minute"]) for event in MacroBook("primary").events]
    portfolio_rows, capacity = construct_portfolio(candidates, trades, event_minutes)
    metrics = portfolio_metrics(portfolio_rows)
    gates = portfolio_gates(metrics, bool(candidates))
    passed = all(gates.values())
    target = passed and metrics["portfolio_r_per_month"] is not None and metrics["portfolio_r_per_month"] >= 10.0
    verdict = "PASS_PORTFOLIO_EDGE_TARGET_CAPACITY_PRESENT" if target else "PASS_PORTFOLIO_EDGE_BELOW_10R_MONTH" if passed else "REJECT_NO_MULTI_ASSET_PORTFOLIO_EDGE"
    final = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_RESULTS_1_0",
        "verdict": verdict, "portfolio_edge_pass": passed, "target_capacity_present": target,
        "candidate_count": len(candidates), "candidates": candidates,
        "portfolio_capacity_diagnostics": capacity, "portfolio_metrics": metrics,
        "portfolio_gates": gates,
        "stage1_summary": {
            "tests": len(stage1), "support_pass": sum(item["support"]["passed"] for item in stage1),
            "multiplicity_pass": sum(item["multiplicity_pass"] for item in stage1),
            "candidates_pass": sum(item["verdict"] == "PASS_PROVISIONAL_UNVALIDATED" for item in stage1),
        },
        "stage2_summary": {
            "tests": len(stage2), "support_pass": sum(item["support"]["passed"] for item in stage2),
            "multiplicity_pass": sum(item["multiplicity_pass"] for item in stage2),
            "candidates_pass": sum(item["verdict"] == "PASS_PROVISIONAL_UNVALIDATED" for item in stage2),
        },
        "portfolio_trade_identities": [str(row["signal_id"]) for row in portfolio_rows],
        "development_period": "2021-08-01/2024-12-31_WITH_OOF_CREDIT_2022-01-01/2024-12-31",
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    return final


def write_report(final: Mapping[str, Any]) -> None:
    stage1 = final["stage1_summary"]
    stage2 = final["stage2_summary"]
    metrics = final["portfolio_metrics"]
    candidates = final["candidates"]
    lines = [
        "# Multi-Asset Macro and Session Portfolio Edge Discovery V1 — Milestone 3",
        "", f"Formal verdict: **{final['verdict']}**", "",
        "## Scope and integrity", "",
        "- Development sources: 2021-08-01 through 2024-12-31; strict OOF scoring is 2022-01-01 through 2024-12-31.",
        "- Calendar 2025 and calendar 2026 remained locked. No data was acquired and no charge was incurred.",
        "- All predictor, trigger, execution, statistical and portfolio definitions were hash-sealed before development outcomes were opened once.",
        "- Primary and reference implementations reproduced exact feature identities, trades, test results and checksums.",
        "", "## Complete registered-test disposition", "",
        "| Stage | Registered | Support pass | Multiplicity pass | Economic PASS |",
        "|---|---:|---:|---:|---:|",
        f"| Stage 1 standalone | {stage1['tests']} | {stage1['support_pass']} | {stage1['multiplicity_pass']} | {stage1['candidates_pass']} |",
        f"| Stage 2 trigger × macro state | {stage2['tests']} | {stage2['support_pass']} | {stage2['multiplicity_pass']} | {stage2['candidates_pass']} |",
        "", "## Frozen candidate shortlist", "",
    ]
    if candidates:
        lines.extend(["| Rank | Candidate | Instrument | Family | Session | State |", "|---:|---|---|---|---|---|"])
        for item in candidates:
            lines.append(f"| {item['rank']} | `{item['candidate_id']}` | {item['research_id']} | {item['family']} | {item['session']} | {item.get('macro_state') or 'ALL'} |")
    else:
        lines.append("No registered test passed every frozen support, multiplicity, robustness, cost and economic gate; the portfolio therefore contains no candidates.")
    lines.extend([
        "", "## Non-overlapping portfolio", "",
        "| Metric | Result |", "|---|---:|",
        f"| Trades | {metrics['trades']} |",
        f"| Trades/month | {metrics['trades_per_month']} |",
        f"| Win rate | {metrics['win_rate']} |",
        f"| Expectancy (portfolio R/trade) | {metrics['expectancy_portfolio_r_per_trade']} |",
        f"| Profit factor | {metrics['profit_factor']} |",
        f"| Net portfolio R | {metrics['net_portfolio_r']} |",
        f"| Portfolio R/month | {metrics['portfolio_r_per_month']} |",
        f"| Net dollars on frozen $10,000 account | {metrics['net_pnl_usd']} |",
        f"| Dollars/month | {metrics['dollars_per_month']} |",
        f"| Maximum drawdown | {metrics['maximum_drawdown_pct']}% |",
        f"| 1.5×-cost portfolio R/month | {metrics['stressed_1p5x_portfolio_r_per_month']} |",
        "", "## Interpretation", "",
        f"The frozen portfolio edge gate is **{'PASS' if final['portfolio_edge_pass'] else 'REJECT'}**. The report-only 10R/month capacity diagnostic is **{'PRESENT' if final['target_capacity_present'] else 'ABSENT'}**.",
        "A repeated movement or an attractive unadjusted test is not promoted unless it survives support, clustered uncertainty, multiple testing, chronological stability, costs, neighbour sensitivity and portfolio concentration gates.",
        "All individual test details—including every support failure and negative result—are retained in the sealed Stage-1 and Stage-2 JSON artifacts.",
    ])
    if REPORT.exists():
        raise FileExistsError(REPORT)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate() -> None:
    verify_sealed_design()
    if any(path.exists() for path in (OUTCOME_AUTHORIZATION, PRIMARY_TRADES, REFERENCE_TRADES, STAGE1_RESULTS, STAGE2_RESULTS, FINAL_RESULTS, REPORT, FINAL_SEAL)):
        raise FileExistsError("Milestone-3 evaluation artifact already exists")
    signals = load_sealed_signals()
    authorization = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_OUTCOME_OPENING_1_0",
        "status": "AUTHORIZED_SINGLE_CONTROLLED_DEVELOPMENT_OUTCOME_OPENING",
        "opened_at_utc": utc_now(), "source_opening_count": 1,
        "signal_population": len(signals), "signal_hash": canonical_hash(signals),
        "primary_signals": file_record(PRIMARY_SIGNALS), "reference_signals": file_record(REFERENCE_SIGNALS),
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
    }
    write_json_exclusive(OUTCOME_AUTHORIZATION, authorization)
    primary, reference, execution_diagnostics = execute_all(signals)
    if primary != reference or canonical_hash(primary) != canonical_hash(reference):
        raise ValueError("Independent outcome/execution implementations disagree")
    write_parquet_exclusive(PRIMARY_TRADES, primary, TRADE_SCHEMA)
    write_parquet_exclusive(REFERENCE_TRADES, reference, TRADE_SCHEMA)
    if sha256_file(PRIMARY_TRADES) != sha256_file(REFERENCE_TRADES):
        raise ValueError("Independent outcome Parquet files are not byte-identical")
    registry = load_json(TEST_REGISTRY)
    primary_stage1 = calculate_stage1(primary, registry["stage1"])
    reference_stage1 = calculate_stage1(reference, registry["stage1"])
    if primary_stage1 != reference_stage1:
        raise ValueError("Independent Stage-1 results disagree")
    stage1_payload = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_STAGE1_1_0",
        "registry_tests": len(primary_stage1), "multiplicity": "BH_FDR_Q_0P05_COMPLETE_REGISTRY",
        "results": primary_stage1, "complete_results_hash": canonical_hash(primary_stage1),
        "sealed_at_utc": utc_now(), "stage2_not_evaluated_before_stage1_seal": True,
    }
    write_json_exclusive(STAGE1_RESULTS, stage1_payload)
    primary_stage2 = calculate_stage2(primary, registry["stage2"])
    reference_stage2 = calculate_stage2(reference, registry["stage2"])
    if primary_stage2 != reference_stage2:
        raise ValueError("Independent Stage-2 results disagree")
    stage2_payload = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_M3_STAGE2_1_0",
        "registry_tests": len(primary_stage2), "multiplicity": "HOLM_FWER_ALPHA_0P05_COMPLETE_REGISTRY",
        "results": primary_stage2, "complete_results_hash": canonical_hash(primary_stage2),
        "sealed_at_utc": utc_now(), "stage1_artifact": file_record(STAGE1_RESULTS),
    }
    write_json_exclusive(STAGE2_RESULTS, stage2_payload)
    primary_final = calculate_portfolio_result(primary, primary_stage1, primary_stage2)
    reference_final = calculate_portfolio_result(reference, reference_stage1, reference_stage2)
    if primary_final != reference_final:
        raise ValueError("Independent portfolio results disagree")
    final = primary_final
    final.update({
        "completed_at_utc": utc_now(), "single_development_outcome_opening": file_record(OUTCOME_AUTHORIZATION),
        "execution_diagnostics": execution_diagnostics,
        "primary_trades": file_record(PRIMARY_TRADES), "reference_trades": file_record(REFERENCE_TRADES),
        "independent_reproduction": {
            "exact_trade_rows": True, "byte_identical_trade_parquet": True,
            "exact_stage1_results": True, "exact_stage2_results": True, "exact_portfolio_result": True,
            "complete_results_hash": canonical_hash({"stage1": reference_stage1, "stage2": reference_stage2, "final": reference_final}),
        },
        "stage1_artifact": file_record(STAGE1_RESULTS), "stage2_artifact": file_record(STAGE2_RESULTS),
    })
    write_json_exclusive(FINAL_RESULTS, final)
    write_report(final)
    seal_files = [M3_PROTOCOL, FEATURE_REGISTRY, TEST_REGISTRY, PREOUTCOME_FREEZE, MATERIALIZATION_ATTEMPT1_FAILURE, MATERIALIZATION_ATTEMPT2_FAILURE, ENGINEERING_AMENDMENT_A, ENGINEERING_AMENDMENT_B, MATERIALIZATION_CERTIFICATION, PRIMARY_SIGNALS, REFERENCE_SIGNALS, OUTCOME_AUTHORIZATION, PRIMARY_TRADES, REFERENCE_TRADES, STAGE1_RESULTS, STAGE2_RESULTS, FINAL_RESULTS, REPORT]
    seal = {
        "version": "MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1_MILESTONE3_SEAL_1_0",
        "status": "SEALED_MILESTONE_3_COMPLETE", "verdict": final["verdict"],
        "sealed_at_utc": utc_now(), "artifacts": [file_record(path) for path in seal_files],
        "complete_artifact_set_hash": canonical_hash([file_record(path) for path in seal_files]),
        "predecessor_milestone2_seal": file_record(M2_SEAL),
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FINAL_SEAL, seal)
    print(json.dumps({
        "verdict": final["verdict"], "stage1": final["stage1_summary"], "stage2": final["stage2_summary"],
        "candidates": final["candidate_count"], "portfolio": final["portfolio_metrics"],
        "seal": file_record(FINAL_SEAL),
    }, indent=2))


def status() -> None:
    payload = {
        "design_sealed": PREOUTCOME_FREEZE.exists(), "materialized": MATERIALIZATION_CERTIFICATION.exists(),
        "outcomes_opened": OUTCOME_AUTHORIZATION.exists(), "complete": FINAL_SEAL.exists(),
    }
    if FINAL_RESULTS.exists():
        result = load_json(FINAL_RESULTS)
        payload.update({"verdict": result["verdict"], "candidate_count": result["candidate_count"], "portfolio": result["portfolio_metrics"]})
    print(json.dumps(payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("materialize", "evaluate", "status"))
    arguments = parser.parse_args()
    if arguments.command == "materialize":
        materialize()
    elif arguments.command == "evaluate":
        evaluate()
    else:
        status()


if __name__ == "__main__":
    main()
