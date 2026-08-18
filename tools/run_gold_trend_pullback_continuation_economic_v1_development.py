from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_trend_pullback_continuation_economic_v1_v01"
PREDECESSOR = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
CASEBOOK = ARTIFACTS / "gold_casebook_v01"

CONTRACT = ROOT / "GOLD_TREND_PULLBACK_CONTINUATION_ECONOMIC_EDGE_VALIDATION_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_trend_pullback_continuation_economic_v1_protocol.json"
DESIGN_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_economic_v1_design_freeze.json"
PREPATH_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_economic_v1_prepath_freeze.json"
SIGNAL_IMPLEMENTATION = ROOT / "tools" / "materialize_gold_trend_pullback_continuation_economic_v1_signals.py"

PRIMARY_SIGNALS = OUTPUT / "primary_development_signals.parquet"
REFERENCE_SIGNALS = OUTPUT / "reference_development_signals.parquet"
AUTHORIZATION = OUTPUT / "development_path_opening_authorization.json"
PRIMARY_TRADES = OUTPUT / "primary_development_trades.parquet"
REFERENCE_TRADES = OUTPUT / "reference_development_trades.parquet"
PRIMARY_RESULTS = OUTPUT / "primary_development_economic_results.json"
REFERENCE_RESULTS = OUTPUT / "reference_development_economic_results.json"
PORTFOLIO_PRIMARY = OUTPUT / "primary_development_portfolio_decisions.parquet"
PORTFOLIO_REFERENCE = OUTPUT / "reference_development_portfolio_decisions.parquet"
FROZEN_CANDIDATES = OUTPUT / "frozen_development_economic_candidates.json"
REPORT = ROOT / "GOLD_TREND_PULLBACK_CONTINUATION_ECONOMIC_V1_DEVELOPMENT.md"
DEVELOPMENT_SEAL = OUTPUT / "development_seal.json"
STATE = OUTPUT / "state_m3.json"

SCALE = 100_000_000
NY = ZoneInfo("America/New_York")
TF_SOURCE = {"15m": "M15", "1h": "H1", "4h": "H4"}
TIMEFRAME_PRIORITY = {"H4": 0, "H1": 1, "M15": 2}
BLOCKS = [
    ("2021-08-01", "2022-06-30"),
    ("2022-07-01", "2023-03-31"),
    ("2023-04-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
]


@dataclass(frozen=True, slots=True)
class PriceData:
    open_ns: np.ndarray
    open_e8: np.ndarray
    high_e8: np.ndarray
    low_e8: np.ndarray
    close_e8: np.ndarray
    spread: np.ndarray
    parent_closes: Mapping[str, np.ndarray]
    diagnostics: Mapping[str, Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def dt_ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def ns_dt(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)


def scaled(value: Any) -> int:
    return int((Decimal(str(value)) * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    result = round(float(value), 12)
    return 0.0 if result == 0 else result


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


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    table = pa.Table.from_pylist(list(rows))
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=16_384)
    temporary.replace(path)


def verify_prepath() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    freeze = json.loads(DESIGN_FREEZE.read_text(encoding="utf-8"))
    prepath = json.loads(PREPATH_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_POST_DECISION_PRICE_PATH_ACCESS":
        raise ValueError("Economic design freeze invalid")
    if prepath.get("status") != "SEALED_EXACT_SIGNAL_POPULATION_BEFORE_PRICE_PATHS":
        raise ValueError("Economic prepath freeze invalid")
    for name, path in {"contract": CONTRACT, "protocol": PROTOCOL}.items():
        if sha256_file(path) != freeze["controls"][name]["sha256"]:
            raise ValueError(f"Control changed: {name}")
    if sha256_file(SIGNAL_IMPLEMENTATION) != prepath["implementation"]["sha256"]:
        raise ValueError("Signal materializer changed after freeze")
    for path, key in ((PRIMARY_SIGNALS, "primary_signals"), (REFERENCE_SIGNALS, "reference_signals")):
        if sha256_file(path) != prepath[key]["sha256"]:
            raise ValueError(f"Signal source changed: {key}")
    primary = pq.read_table(PRIMARY_SIGNALS).to_pylist()
    reference = pq.read_table(REFERENCE_SIGNALS).to_pylist()
    if primary != reference or canonical_hash(primary) != prepath["signals_hash"]:
        raise ValueError("Frozen signals do not reproduce")
    return freeze, prepath, primary


def synthetic_proof() -> dict[str, Any]:
    opens = np.array([100, 101, 102], dtype=np.int64)
    highs = np.array([102, 105, 104], dtype=np.int64)
    lows = np.array([99, 100, 97], dtype=np.int64)
    primary = select_exit(opens, highs, lows, np.array([101, 103, 103]), "UP", 98, 105, "primary")
    reference = select_exit(opens, highs, lows, np.array([101, 103, 103]), "UP", 98, 105, "reference")
    if primary != reference or primary[:3] != (1, 105, "TARGET"):
        raise ValueError("Synthetic target proof failed")
    ambiguous_primary = select_exit(opens, np.array([106, 105, 104]), np.array([97, 100, 99]), np.array([101, 103, 103]), "UP", 98, 105, "primary")
    ambiguous_reference = select_exit(opens, np.array([106, 105, 104]), np.array([97, 100, 99]), np.array([101, 103, 103]), "UP", 98, 105, "reference")
    if ambiguous_primary != ambiguous_reference or ambiguous_primary[:3] != (0, 98, "STOP"):
        raise ValueError("Synthetic stop-first proof failed")
    adjusted = holm_adjust([(0, 0.01), (1, 0.04), (2, 0.03)])
    if not math.isclose(adjusted[0], 0.03) or not math.isclose(adjusted[1], 0.06):
        raise ValueError("Synthetic Holm proof failed")
    return {"status": "PASS", "exit_hash": canonical_hash([primary, ambiguous_primary]), "holm": adjusted}


def load_price() -> PriceData:
    source_path = CASEBOOK / "price_bars.jsonl.gz"
    source_sha256 = sha256_file(source_path)
    open_ns: list[int] = []
    opens: list[int] = []
    highs: list[int] = []
    lows: list[int] = []
    closes: list[int] = []
    spreads: list[float] = []
    parent: dict[str, list[int]] = {"M15": [], "H1": [], "H4": []}
    scanned = selected_m1 = malformed = bad_availability = forward_deserialized = 0
    with gzip.open(source_path, "rb") as handle:
        for raw in handle:
            scanned += 1
            if b'"instrument_code":"XAUUSD"' not in raw:
                continue
            if b'"open_time":"2025' in raw or b'"open_time":"2026' in raw:
                continue
            record = json.loads(raw)
            timeframe = record.get("timeframe")
            if timeframe in TF_SOURCE:
                closed = parse_dt(str(record["close_time"]))
                if closed <= datetime(2025, 1, 1, tzinfo=UTC):
                    parent[TF_SOURCE[str(timeframe)]].append(dt_ns(closed))
                continue
            if timeframe != "1m":
                continue
            opened = parse_dt(str(record["open_time"]))
            if opened >= datetime(2025, 1, 1, tzinfo=UTC):
                forward_deserialized += 1
                continue
            closed = parse_dt(str(record["close_time"]))
            available = parse_dt(str(record["available_at"]))
            if available > closed:
                bad_availability += 1
                continue
            ohlc = record.get("ohlc") if isinstance(record.get("ohlc"), Mapping) else {}
            if any(ohlc.get(key) is None for key in ("open", "high", "low", "close")):
                malformed += 1
                continue
            o, h, low, c = (scaled(ohlc[key]) for key in ("open", "high", "low", "close"))
            if not (low <= min(o, c) <= max(o, c) <= h):
                malformed += 1
                continue
            spread = finite(record.get("spread_price"))
            open_ns.append(dt_ns(opened)); opens.append(o); highs.append(h); lows.append(low); closes.append(c)
            spreads.append(float("nan") if spread is None else spread)
            selected_m1 += 1
    arrays = [np.asarray(value, dtype=np.int64) for value in (open_ns, opens, highs, lows, closes)]
    if not len(arrays[0]) or np.any(np.diff(arrays[0]) <= 0):
        raise ValueError("Development M1 timestamps are empty, duplicated or unordered")
    parent_arrays: dict[str, np.ndarray] = {}
    for timeframe, values in parent.items():
        array = np.asarray(sorted(set(values)), dtype=np.int64)
        if not len(array) or np.any(np.diff(array) <= 0):
            raise ValueError(f"Parent timestamps invalid: {timeframe}")
        parent_arrays[timeframe] = array
    return PriceData(
        arrays[0], arrays[1], arrays[2], arrays[3], arrays[4], np.asarray(spreads, dtype=np.float64), parent_arrays,
        {
            "source_rows_scanned": scanned,
            "selected_m1_rows": selected_m1,
            "malformed_rows": malformed,
            "bad_availability_rows": bad_availability,
            "forward_rows_deserialized": forward_deserialized,
            "first_m1_open": iso_z(ns_dt(int(arrays[0][0]))),
            "last_m1_open": iso_z(ns_dt(int(arrays[0][-1]))),
            "parent_counts": {key: len(value) for key, value in parent_arrays.items()},
            "source_sha256": source_sha256,
        },
    )


def load_target_registry() -> tuple[dict[str, list[dict[str, Any]]], dict[str, datetime]]:
    swing_columns = ["swing_id", "timeframe", "scale", "side", "known_at_utc", "price_e8", "evidence_hash"]
    event_columns = ["event_at_utc", "broken_swing_ids_json"]
    swings = pq.read_table(CENSUS / "primary_swings.parquet", columns=swing_columns).to_pylist()
    events = pq.read_table(CENSUS / "primary_structure_events.parquet", columns=event_columns).to_pylist()
    broken_at: dict[str, datetime] = {}
    for event in sorted(events, key=lambda row: row["event_at_utc"]):
        when = parse_dt(str(event["event_at_utc"]))
        for swing_id in json.loads(str(event["broken_swing_ids_json"])):
            broken_at.setdefault(str(swing_id), when)
    by_timeframe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for swing in swings:
        if swing["scale"] != "STANDARD":
            continue
        row = dict(swing)
        row["known_dt"] = parse_dt(str(row["known_at_utc"]))
        by_timeframe[str(row["timeframe"])].append(row)
    for values in by_timeframe.values():
        values.sort(key=lambda row: (row["known_at_utc"], row["price_e8"], row["swing_id"]))
    return dict(by_timeframe), broken_at


def target_for(signal: Mapping[str, Any], entry: int, swings: Mapping[str, Sequence[Mapping[str, Any]]], broken_at: Mapping[str, datetime], implementation: str) -> tuple[int | None, str | None, str | None]:
    decision = parse_dt(str(signal["known_at_utc"]))
    side = "UPPER" if signal["direction"] == "UP" else "LOWER"
    eligible = []
    if implementation == "primary":
        eligible = [
            item for item in swings[str(signal["timeframe"])]
            if item["side"] == side
            and item["known_dt"] <= decision
            and (broken_at.get(str(item["swing_id"])) is None or broken_at[str(item["swing_id"])] > decision)
            and (int(item["price_e8"]) > entry if signal["direction"] == "UP" else int(item["price_e8"]) < entry)
        ]
        if not eligible:
            return None, None, None
        chosen = min(eligible, key=lambda item: ((int(item["price_e8"]) - entry) if signal["direction"] == "UP" else (entry - int(item["price_e8"])), item["known_at_utc"], item["swing_id"]))
    else:
        chosen = None
        best = None
        for item in swings[str(signal["timeframe"] )]:
            if item["side"] != side or item["known_dt"] > decision:
                continue
            broken = broken_at.get(str(item["swing_id"]))
            if broken is not None and broken <= decision:
                continue
            distance = int(item["price_e8"]) - entry if signal["direction"] == "UP" else entry - int(item["price_e8"])
            if distance <= 0:
                continue
            key = (distance, item["known_at_utc"], item["swing_id"])
            if best is None or key < best:
                best, chosen = key, item
        if chosen is None:
            return None, None, None
    return int(chosen["price_e8"]), str(chosen["swing_id"]), str(chosen["evidence_hash"])


def select_exit(opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, direction: str, stop: int, target: int, implementation: str) -> tuple[int, int, str]:
    if implementation == "primary":
        stop_hits = np.flatnonzero(lows <= stop if direction == "UP" else highs >= stop)
        target_hits = np.flatnonzero(highs >= target if direction == "UP" else lows <= target)
        stop_index = int(stop_hits[0]) if len(stop_hits) else math.inf
        target_index = int(target_hits[0]) if len(target_hits) else math.inf
        if stop_index <= target_index and stop_index != math.inf:
            fill = min(stop, int(opens[stop_index])) if direction == "UP" else max(stop, int(opens[stop_index]))
            return int(stop_index), fill, "STOP"
        if target_index != math.inf:
            return int(target_index), target, "TARGET"
        return len(opens) - 1, int(closes[-1]), "TIME"
    for index, (opened, high, low) in enumerate(zip(opens, highs, lows)):
        stop_hit = low <= stop if direction == "UP" else high >= stop
        target_hit = high >= target if direction == "UP" else low <= target
        if stop_hit:
            fill = min(stop, int(opened)) if direction == "UP" else max(stop, int(opened))
            return index, fill, "STOP"
        if target_hit:
            return index, target, "TARGET"
    return len(opens) - 1, int(closes[-1]), "TIME"


def empty_trade(signal: Mapping[str, Any], reason: str, lineage: Any, session: str) -> dict[str, Any]:
    return {
        "trade_id": f"TPCE-ECON-TRADE::{signal['signal_id']}",
        "signal_id": signal["signal_id"], "candidate_id": signal["candidate_id"], "candidate_rank": signal["candidate_rank"],
        "pullback_id": signal["pullback_id"], "timeframe": signal["timeframe"], "direction": signal["direction"],
        "session_state": session, "known_at_utc": signal["known_at_utc"], "cluster_date": trading_date(str(signal["known_at_utc"])),
        "status": "NO_TRADE", "no_trade_reason": reason, "entry_at_utc": None, "exit_at_utc": None,
        "entry_delay_minutes": None, "entry_e8": None, "stop_e8": None, "target_e8": None, "target_swing_id": None,
        "exit_e8": None, "risk_e8": None, "target_r": None, "entry_spread_usd_oz": None, "spread_fallback_used": None,
        "commission_usd_oz": None, "slippage_usd_oz": None, "total_cost_usd_oz": None, "cost_r": None,
        "exit_reason": None, "holding_minutes": None, "gross_r": None, "net_r": None, "net_r_cost_1p5x": None,
        "net_r_cost_2x": None, "mfe_r": None, "mae_r": None, "planned_lots": None, "ounces": None,
        "actual_stop_risk_usd": None, "net_pnl_usd": None, "outcome_lineage_hash": canonical_hash(lineage),
    }


def trading_date(value: str) -> str:
    return (parse_dt(value).astimezone(NY) - timedelta(hours=17)).date().isoformat()


def simulate(signal: Mapping[str, Any], prices: PriceData, swings: Mapping[str, Sequence[Mapping[str, Any]]], broken_at: Mapping[str, datetime], implementation: str, session: str) -> dict[str, Any]:
    decision_ns = dt_ns(parse_dt(str(signal["known_at_utc"])))
    entry_index = int(np.searchsorted(prices.open_ns, decision_ns, side="left"))
    if entry_index >= len(prices.open_ns):
        return empty_trade(signal, "NO_TRADE_MISSING_ENTRY_BAR", [signal["signal_lineage_hash"], "ENTRY_EOF"], session)
    delay_minutes = (int(prices.open_ns[entry_index]) - decision_ns) / 60_000_000_000
    if delay_minutes < 0 or delay_minutes > 5:
        return empty_trade(signal, "NO_TRADE_ENTRY_DELAY_EXCEEDS_5M", [signal["signal_lineage_hash"], int(prices.open_ns[entry_index]), delay_minutes], session)
    parent = prices.parent_closes[str(signal["timeframe"])]
    first_parent = int(np.searchsorted(parent, decision_ns, side="right"))
    deadline_index = first_parent + 15
    if deadline_index >= len(parent):
        return empty_trade(signal, "NO_TRADE_INCOMPLETE_16_PARENT_BAR_PATH", [signal["signal_lineage_hash"], "PARENT_EOF"], session)
    deadline_ns = int(parent[deadline_index])
    path_end = int(np.searchsorted(prices.open_ns, deadline_ns, side="left"))
    if path_end <= entry_index:
        return empty_trade(signal, "NO_TRADE_EMPTY_M1_PATH", [signal["signal_lineage_hash"], deadline_ns], session)
    entry = int(prices.open_e8[entry_index])
    buffer_e8 = int(round(0.15 * float(signal["atr14_e8"])))
    stop = int(signal["pivot_price_e8"]) - buffer_e8 if signal["direction"] == "UP" else int(signal["pivot_price_e8"]) + buffer_e8
    risk = entry - stop if signal["direction"] == "UP" else stop - entry
    if risk <= 0:
        return empty_trade(signal, "NO_TRADE_STOP_NOT_BEYOND_ENTRY", [signal["signal_lineage_hash"], entry, stop], session)
    target, target_id, target_hash = target_for(signal, entry, swings, broken_at, implementation)
    if target is None:
        return empty_trade(signal, "NO_TRADE_NO_KNOWN_LIQUIDITY_TARGET", [signal["signal_lineage_hash"], entry], session)
    raw_spread = float(prices.spread[entry_index])
    fallback = not math.isfinite(raw_spread) or raw_spread < 0
    spread = 0.30 if fallback else raw_spread
    total_cost = spread + 0.07 + 0.10
    risk_usd_oz = risk / SCALE
    max_ounces = math.floor((50.0 / (risk_usd_oz + total_cost)) + 1e-12)
    if max_ounces < 1:
        return empty_trade(signal, "NO_TRADE_MINIMUM_LOT_EXCEEDS_RISK", [signal["signal_lineage_hash"], risk, total_cost], session)
    ounces = int(max_ounces)
    lots = ounces / 100.0
    sl = slice(entry_index, path_end)
    path_open = prices.open_e8[sl]; path_high = prices.high_e8[sl]; path_low = prices.low_e8[sl]; path_close = prices.close_e8[sl]
    exit_offset, exit_price, exit_reason = select_exit(path_open, path_high, path_low, path_close, str(signal["direction"]), stop, target, implementation)
    used_high = path_high[: exit_offset + 1]; used_low = path_low[: exit_offset + 1]
    sign = 1 if signal["direction"] == "UP" else -1
    gross_r = sign * (exit_price - entry) / risk
    cost_r = total_cost / risk_usd_oz
    net_r = gross_r - cost_r
    favorable = int(np.max(used_high)) - entry if sign > 0 else entry - int(np.min(used_low))
    adverse = entry - int(np.min(used_low)) if sign > 0 else int(np.max(used_high)) - entry
    exit_index = entry_index + exit_offset
    actual_stop_risk = (risk_usd_oz + total_cost) * ounces
    net_pnl = (sign * ((exit_price - entry) / SCALE) - total_cost) * ounces
    lineage = [
        signal["signal_lineage_hash"], prices.diagnostics["source_sha256"], entry_index, exit_index,
        int(prices.open_ns[entry_index]), int(prices.open_ns[exit_index]), target_id, target_hash, exit_reason,
    ]
    return {
        "trade_id": f"TPCE-ECON-TRADE::{signal['signal_id']}",
        "signal_id": signal["signal_id"], "candidate_id": signal["candidate_id"], "candidate_rank": signal["candidate_rank"],
        "pullback_id": signal["pullback_id"], "timeframe": signal["timeframe"], "direction": signal["direction"],
        "session_state": session, "known_at_utc": signal["known_at_utc"], "cluster_date": trading_date(str(signal["known_at_utc"])),
        "status": "EXECUTED", "no_trade_reason": "", "entry_at_utc": iso_z(ns_dt(int(prices.open_ns[entry_index]))),
        "exit_at_utc": iso_z(ns_dt(int(prices.open_ns[exit_index]) + 60_000_000_000)), "entry_delay_minutes": rounded(delay_minutes),
        "entry_e8": entry, "stop_e8": stop, "target_e8": target, "target_swing_id": target_id, "exit_e8": exit_price,
        "risk_e8": risk, "target_r": rounded(abs(target - entry) / risk), "entry_spread_usd_oz": rounded(spread),
        "spread_fallback_used": fallback, "commission_usd_oz": 0.07, "slippage_usd_oz": 0.10,
        "total_cost_usd_oz": rounded(total_cost), "cost_r": rounded(cost_r), "exit_reason": exit_reason,
        "holding_minutes": int((int(prices.open_ns[exit_index]) - int(prices.open_ns[entry_index])) / 60_000_000_000) + 1,
        "gross_r": rounded(gross_r), "net_r": rounded(net_r), "net_r_cost_1p5x": rounded(gross_r - 1.5 * cost_r),
        "net_r_cost_2x": rounded(gross_r - 2.0 * cost_r), "mfe_r": rounded(max(0, favorable) / risk),
        "mae_r": rounded(max(0, adverse) / risk), "planned_lots": rounded(lots), "ounces": ounces,
        "actual_stop_risk_usd": rounded(actual_stop_risk), "net_pnl_usd": rounded(net_pnl),
        "outcome_lineage_hash": canonical_hash(lineage),
    }


def load_sessions() -> dict[str, str]:
    table = pq.read_table(PREDECESSOR / "primary_features.parquet", columns=["pullback_id", "session_state"])
    return {str(row["pullback_id"]): str(row["session_state"]) for row in table.to_pylist()}


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], field: str, seed: int, resamples: int = 5000) -> dict[str, Any]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_date[str(row["cluster_date"])].append(float(row[field]))
    dates = sorted(by_date)
    if not dates:
        return {"ci90": [None, None], "ci95": [None, None], "p_one_sided": None, "valid_resamples": 0}
    sums = np.array([sum(by_date[key]) for key in dates], dtype=np.float64)
    counts = np.array([len(by_date[key]) for key in dates], dtype=np.int64)
    rng = np.random.default_rng(seed)
    values = []
    for left in range(0, resamples, 250):
        size = min(250, resamples - left)
        sample = rng.integers(0, len(dates), size=(size, len(dates)))
        values.extend((sums[sample].sum(axis=1) / counts[sample].sum(axis=1)).tolist())
    array = np.asarray(values, dtype=np.float64)
    return {
        "ci90": [float(np.quantile(array, 0.05)), float(np.quantile(array, 0.95))],
        "ci95": [float(np.quantile(array, 0.025)), float(np.quantile(array, 0.975))],
        "p_one_sided": float((1 + np.sum(array <= 0)) / (len(array) + 1)),
        "valid_resamples": len(array),
    }


def holm_adjust(indexed_p: Sequence[tuple[int, float]]) -> dict[int, float]:
    ordered = sorted(indexed_p, key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[int, float] = {}
    running = 0.0
    for rank, (index, p_value) in enumerate(ordered, 1):
        running = max(running, (count - rank + 1) * p_value)
        adjusted[index] = min(1.0, running)
    return adjusted


def month_sequence(start: str, end: str) -> list[str]:
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    output = []
    while (year, month) <= (end_year, end_month):
        output.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1; month = 1
    return output


def basic_metrics(rows: Sequence[Mapping[str, Any]], field: str = "net_r") -> dict[str, Any]:
    values = [float(row[field]) for row in rows]
    if not values:
        return {"trades": 0, "expectancy_r": None, "profit_factor": None, "win_rate_pct": None}
    positives = [value for value in values if value > 0]
    negatives = [value for value in values if value < 0]
    profit_factor = sum(positives) / abs(sum(negatives)) if negatives else math.inf
    cumulative = peak = drawdown = 0.0
    consecutive = max_consecutive = 0
    for value in values:
        cumulative += value; peak = max(peak, cumulative); drawdown = max(drawdown, peak - cumulative)
        if value <= 0:
            consecutive += 1; max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0
    pnl_values = [float(row["net_pnl_usd"]) for row in rows]
    equity = 10_000.0; equity_peak = equity; account_dd = 0.0
    for pnl in pnl_values:
        equity += pnl; equity_peak = max(equity_peak, equity); account_dd = max(account_dd, (equity_peak - equity) / equity_peak * 100)
    monthly: dict[str, float] = defaultdict(float)
    for row, pnl in zip(rows, pnl_values):
        monthly[str(row["known_at_utc"])[:7]] += pnl
    months = month_sequence(str(rows[0]["known_at_utc"])[:7], str(rows[-1]["known_at_utc"])[:7])
    monthly_returns = [monthly.get(key, 0.0) / 10_000.0 for key in months]
    mean_monthly = statistics.fmean(monthly_returns) if monthly_returns else 0.0
    stdev = statistics.stdev(monthly_returns) if len(monthly_returns) > 1 else 0.0
    downside = [min(0.0, item) for item in monthly_returns]
    downside_dev = math.sqrt(statistics.fmean([item * item for item in downside])) if downside else 0.0
    concentration = max(positives) / sum(positives) if positives else None
    return {
        "trades": len(values), "net_r": rounded(sum(values)), "expectancy_r": rounded(statistics.fmean(values)),
        "median_r": rounded(statistics.median(values)), "win_rate_pct": rounded(100 * len(positives) / len(values)),
        "average_win_r": rounded(statistics.fmean(positives)) if positives else None,
        "average_loss_r": rounded(statistics.fmean(negatives)) if negatives else None,
        "profit_factor": rounded(profit_factor) if math.isfinite(profit_factor) else "INF",
        "max_drawdown_r": rounded(drawdown), "max_drawdown_pct": rounded(account_dd),
        "max_consecutive_nonwins": max_consecutive, "net_pnl_usd": rounded(sum(pnl_values)),
        "average_monthly_pnl_usd": rounded(statistics.fmean([monthly.get(key, 0.0) for key in months])) if months else None,
        "average_monthly_return_pct": rounded(mean_monthly * 100),
        "monthly_sharpe": rounded(mean_monthly / stdev * math.sqrt(12)) if stdev > 0 else None,
        "monthly_sortino": rounded(mean_monthly / downside_dev * math.sqrt(12)) if downside_dev > 0 else None,
        "average_mfe_r": rounded(statistics.fmean(float(row["mfe_r"]) for row in rows)),
        "average_mae_r": rounded(statistics.fmean(float(row["mae_r"]) for row in rows)),
        "median_holding_minutes": rounded(statistics.median(float(row["holding_minutes"]) for row in rows)),
        "median_target_r": rounded(statistics.median(float(row["target_r"]) for row in rows)),
        "average_cost_r": rounded(statistics.fmean(float(row["cost_r"]) for row in rows)),
        "profit_concentration": rounded(concentration),
        "exit_reasons": dict(sorted(Counter(str(row["exit_reason"]) for row in rows).items())),
    }


def expectation(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    return statistics.fmean(float(row[field]) for row in rows) if rows else None


def profit_factor(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows]
    positives = sum(value for value in values if value > 0); negatives = abs(sum(value for value in values if value < 0))
    return positives / negatives if negatives else (math.inf if positives else None)


def support(candidate_id: str, rows: Sequence[Mapping[str, Any]], all_rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    timeframe = candidate_id.split("|", 1)[0]
    floors = {"M15": (100, 75, 40), "H1": (50, 40, 25), "H4": (30, 25, 15)}[timeframe]
    counts = {
        "signals": len(all_rows), "trades": len(rows), "dates": len({row["cluster_date"] for row in rows}),
        "weeks": len({parse_dt(str(row["known_at_utc"])).date().isocalendar()[:2] for row in rows}),
        "net_winners": sum(float(row["net_r"]) > 0 for row in rows), "net_losers": sum(float(row["net_r"]) < 0 for row in rows),
        "no_trade_reasons": dict(sorted(Counter(str(row["no_trade_reason"]) for row in all_rows if row["status"] != "EXECUTED").items())),
    }
    failures = []
    for name, actual, floor in (("TRADES", counts["trades"], floors[0]), ("DATES", counts["dates"], floors[1]), ("WEEKS", counts["weeks"], floors[2]), ("WINNERS", counts["net_winners"], 15), ("LOSERS", counts["net_losers"], 15)):
        if actual < floor:
            failures.append(f"{name}_LT_{floor}")
    return counts, failures


def block_diagnostics(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for index, (start, end) in enumerate(BLOCKS, 1):
        selected = [row for row in rows if start <= str(row["known_at_utc"])[:10] <= end]
        output.append({"block": index, "start": start, "end": end, "trades": len(selected), "expectancy_r": rounded(expectation(selected, "net_r"))})
    return output


def candidate_result(candidate_id: str, all_rows: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    executed = sorted((row for row in all_rows if row["status"] == "EXECUTED"), key=lambda row: (row["entry_at_utc"], row["trade_id"]))
    counts, support_failures = support(candidate_id, executed, all_rows)
    metrics = basic_metrics(executed)
    bootstrap = cluster_bootstrap(executed, "net_r", seed) if not support_failures else {"ci90": [None, None], "ci95": [None, None], "p_one_sided": None, "valid_resamples": 0}
    blocks = block_diagnostics(executed)
    annual = []
    for year in (2021, 2022, 2023, 2024):
        selected = [row for row in executed if str(row["known_at_utc"]).startswith(str(year))]
        annual.append({"year": year, "trades": len(selected), "expectancy_r": rounded(expectation(selected, "net_r")), "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected))})
    sides = [{"direction": side, "trades": len(selected := [row for row in executed if row["direction"] == side]), "expectancy_r": rounded(expectation(selected, "net_r"))} for side in ("UP", "DOWN")]
    sessions = [{"session": session, "trades": len(selected := [row for row in executed if row["session_state"] == session]), "expectancy_r": rounded(expectation(selected, "net_r"))} for session in ("ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP", "OTHER")]
    return {
        "candidate_id": candidate_id, "timeframe": candidate_id.split("|", 1)[0], "support": counts,
        "support_failures": support_failures, "support_pass": not support_failures, "metrics": metrics,
        "bootstrap": bootstrap, "holm_p": None, "blocks": blocks, "annual": annual, "sides": sides, "sessions": sessions,
        "stress": {
            "cost_1p5x_expectancy_r": rounded(expectation(executed, "net_r_cost_1p5x")),
            "cost_1p5x_profit_factor": rounded(value) if (value := profit_factor(executed, "net_r_cost_1p5x")) is not None and math.isfinite(value) else ("INF" if value == math.inf else None),
            "cost_2x_expectancy_r": rounded(expectation(executed, "net_r_cost_2x")),
            "cost_2x_profit_factor": rounded(value2) if (value2 := profit_factor(executed, "net_r_cost_2x")) is not None and math.isfinite(value2) else ("INF" if value2 == math.inf else None),
        },
        "verdict": "PENDING_MULTIPLICITY" if not support_failures else "INCONCLUSIVE_SUPPORT",
        "failed_gates": list(support_failures),
    }


def finalize_candidates(results: list[dict[str, Any]]) -> None:
    indexed = [(index, float(item["bootstrap"]["p_one_sided"])) for index, item in enumerate(results) if item["support_pass"] and item["bootstrap"]["p_one_sided"] is not None]
    adjusted = holm_adjust(indexed)
    for index, item in enumerate(results):
        if not item["support_pass"]:
            continue
        item["holm_p"] = adjusted[index]
        failures = []
        metrics = item["metrics"]
        if metrics["expectancy_r"] is None or metrics["expectancy_r"] <= 0: failures.append("NET_EXPECTANCY_NOT_POSITIVE")
        if item["bootstrap"]["ci95"][0] is None or item["bootstrap"]["ci95"][0] <= 0: failures.append("CI95_LOWER_NOT_POSITIVE")
        if item["holm_p"] > 0.05: failures.append("HOLM_P_GT_0_05")
        pf = metrics["profit_factor"]
        if pf != "INF" and (pf is None or float(pf) < 1.20): failures.append("PROFIT_FACTOR_LT_1_20")
        block_values = [entry["expectancy_r"] for entry in item["blocks"] if entry["trades"] >= 10 and entry["expectancy_r"] is not None]
        if sum(value > 0 for value in block_values) < 3: failures.append("POSITIVE_BLOCKS_LT_3")
        if block_values and min(block_values) < -0.15: failures.append("BLOCK_BELOW_MINUS_0_15R")
        stress = item["stress"]
        if stress["cost_1p5x_expectancy_r"] is None or stress["cost_1p5x_expectancy_r"] <= 0: failures.append("COST_1P5X_EXPECTANCY_NOT_POSITIVE")
        stress_pf = stress["cost_1p5x_profit_factor"]
        if stress_pf != "INF" and (stress_pf is None or float(stress_pf) < 1.05): failures.append("COST_1P5X_PF_LT_1_05")
        if metrics["max_drawdown_pct"] is None or metrics["max_drawdown_pct"] > 15: failures.append("MAX_DRAWDOWN_GT_15PCT")
        if metrics["profit_concentration"] is None or metrics["profit_concentration"] > 0.35: failures.append("PROFIT_CONCENTRATION_GT_35PCT")
        item["failed_gates"] = failures
        item["verdict"] = "PASS_DEVELOPMENT_ECONOMIC_CANDIDATE" if not failures else "REJECT_DEVELOPMENT_ECONOMICS"


def portfolio_decisions(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_pullback: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in trades:
        by_pullback[str(row["pullback_id"])].append(row)
    canonical = []
    for values in by_pullback.values():
        values.sort(key=lambda row: (TIMEFRAME_PRIORITY[str(row["timeframe"])], int(row["candidate_rank"]), str(row["candidate_id"])))
        canonical.append(values[0])
    canonical.sort(key=lambda row: (row["known_at_utc"], TIMEFRAME_PRIORITY[str(row["timeframe"])], int(row["candidate_rank"]), row["pullback_id"]))
    output = []
    open_until: str | None = None
    for row in canonical:
        decision = dict(row)
        if row["status"] != "EXECUTED":
            decision["portfolio_status"] = "SKIPPED_NO_TRADE"
            decision["portfolio_reason"] = row["no_trade_reason"]
        elif open_until is not None and str(row["entry_at_utc"]) < open_until:
            decision["portfolio_status"] = "SKIPPED_OVERLAPPING_POSITION"
            decision["portfolio_reason"] = "ONE_OPEN_XAUUSD_POSITION"
        else:
            decision["portfolio_status"] = "ACCEPTED"
            decision["portfolio_reason"] = ""
            open_until = str(row["exit_at_utc"])
        output.append(decision)
    return output


def portfolio_result(decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    accepted = [row for row in decisions if row["portfolio_status"] == "ACCEPTED"]
    accepted.sort(key=lambda row: (row["entry_at_utc"], row["trade_id"]))
    return {
        "signals_after_same_pullback_merge": len(decisions), "accepted_trades": len(accepted),
        "decision_counts": dict(sorted(Counter(str(row["portfolio_status"]) for row in decisions).items())),
        "metrics": basic_metrics(accepted), "bootstrap": cluster_bootstrap(accepted, "net_r", 999_001),
        "blocks": block_diagnostics(accepted),
        "candidate_attribution": dict(sorted(Counter(str(row["candidate_id"]) for row in accepted).items())),
    }


def report_text(results: Mapping[str, Any]) -> str:
    lines = [
        "# Gold Trend-Pullback Continuation Economic Validation V1 — Development",
        "",
        f"Status: **{results['verdict']}**",
        "",
        "This is the constant-execution 2021-2024 economic test. Calendar 2025 and 2026 were not opened during this stage.",
        "",
        "## Candidate results",
        "",
        "| Candidate | Trades | Win rate | Net exp. R | PF | Net PnL | Avg/month | Max DD | 95% CI | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for item in results["candidates"]:
        metrics = item["metrics"]; ci = item["bootstrap"]["ci95"]
        def show(value: Any, suffix: str = "") -> str:
            return "NA" if value is None else f"{value}{suffix}"
        ci_text = "NA" if ci[0] is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"
        lines.append(f"| {item['candidate_id']} | {metrics['trades']} | {show(metrics.get('win_rate_pct'), '%')} | {show(metrics.get('expectancy_r'))} | {show(metrics.get('profit_factor'))} | ${show(metrics.get('net_pnl_usd'))} | ${show(metrics.get('average_monthly_pnl_usd'))} | {show(metrics.get('max_drawdown_pct'), '%')} | {ci_text} | {item['verdict']} |")
    portfolio = results["portfolio"]
    lines.extend([
        "", "## Non-overlapping portfolio", "",
        f"Accepted trades: **{portfolio['accepted_trades']}**. Net expectancy: **{portfolio['metrics'].get('expectancy_r')}R**. Profit factor: **{portfolio['metrics'].get('profit_factor')}**. Net PnL: **${portfolio['metrics'].get('net_pnl_usd')}**. Average monthly PnL: **${portfolio['metrics'].get('average_monthly_pnl_usd')}**.",
        "", "## Integrity", "",
        "Primary and reference signal paths, targets, trades, portfolio decisions and statistics reproduced exactly. No rule was retuned after price-path access. Development candidates were frozen before any forward value could be opened.", "",
    ])
    return "\n".join(lines)


def execute() -> dict[str, Any]:
    artifacts = (AUTHORIZATION, PRIMARY_TRADES, REFERENCE_TRADES, PRIMARY_RESULTS, REFERENCE_RESULTS, PORTFOLIO_PRIMARY, PORTFOLIO_REFERENCE, FROZEN_CANDIDATES, REPORT, DEVELOPMENT_SEAL, STATE)
    if any(path.exists() for path in artifacts):
        raise FileExistsError("Development economic artifact already exists")
    freeze, prepath, signals = verify_prepath()
    proof = synthetic_proof()
    authorization = {
        "version": "GOLD_TPCE_ECONOMIC_V1_DEVELOPMENT_OPENING_1_0",
        "status": "AUTHORIZED_EXACTLY_ONE_DEVELOPMENT_POST_DECISION_PRICE_PATH_OPENING",
        "authorized_at_utc": utc_now(), "design_freeze": file_record(DESIGN_FREEZE), "prepath_freeze": file_record(PREPATH_FREEZE),
        "implementation": file_record(Path(__file__).resolve()), "synthetic_proof": proof, "signal_rows": len(signals),
        "development_source_opening_limit": 1, "forward_values_authorized": False, "paid_acquisition_authorized": False,
    }
    write_json_exclusive(AUTHORIZATION, authorization)
    prices = load_price()
    swings, broken_at = load_target_registry()
    sessions = load_sessions()
    primary = [simulate(signal, prices, swings, broken_at, "primary", sessions[str(signal["pullback_id"])]) for signal in signals]
    reference = [simulate(signal, prices, swings, broken_at, "reference", sessions[str(signal["pullback_id"])]) for signal in signals]
    primary.sort(key=lambda row: (row["known_at_utc"], row["candidate_rank"], row["pullback_id"], row["trade_id"]))
    reference.sort(key=lambda row: (row["known_at_utc"], row["candidate_rank"], row["pullback_id"], row["trade_id"]))
    if primary != reference:
        raise ValueError("Independent development trade paths differ")
    write_parquet_exclusive(PRIMARY_TRADES, primary); write_parquet_exclusive(REFERENCE_TRADES, reference)
    if sha256_file(PRIMARY_TRADES) != sha256_file(REFERENCE_TRADES):
        raise ValueError("Development trade Parquet bytes differ")
    candidate_ids = freeze["predecessor"]["candidate_ids"]
    candidate_results = []
    reference_candidate_results = []
    for index, candidate_id in enumerate(candidate_ids):
        selected = [row for row in primary if row["candidate_id"] == candidate_id]
        reference_selected = [row for row in reference if row["candidate_id"] == candidate_id]
        candidate_results.append(candidate_result(candidate_id, selected, int(json.loads(PROTOCOL.read_text(encoding="utf-8"))["bootstrap"]["seed"]) + index))
        reference_candidate_results.append(candidate_result(candidate_id, reference_selected, int(json.loads(PROTOCOL.read_text(encoding="utf-8"))["bootstrap"]["seed"]) + index))
    finalize_candidates(candidate_results)
    finalize_candidates(reference_candidate_results)
    if candidate_results != reference_candidate_results:
        raise ValueError("Independent candidate statistics differ")
    decisions_primary = portfolio_decisions(primary); decisions_reference = portfolio_decisions(reference)
    if decisions_primary != decisions_reference:
        raise ValueError("Independent portfolio decisions differ")
    write_parquet_exclusive(PORTFOLIO_PRIMARY, decisions_primary); write_parquet_exclusive(PORTFOLIO_REFERENCE, decisions_reference)
    if sha256_file(PORTFOLIO_PRIMARY) != sha256_file(PORTFOLIO_REFERENCE):
        raise ValueError("Portfolio Parquet bytes differ")
    portfolio = portfolio_result(decisions_primary)
    reference_portfolio = portfolio_result(decisions_reference)
    if portfolio != reference_portfolio:
        raise ValueError("Independent portfolio statistics differ")
    passing = [item["candidate_id"] for item in candidate_results if item["verdict"] == "PASS_DEVELOPMENT_ECONOMIC_CANDIDATE"]
    verdict = "PASS_DEVELOPMENT_ECONOMIC_CANDIDATES_FROZEN" if passing else "REJECT_NO_DEVELOPMENT_ECONOMIC_CANDIDATE"
    results = {
        "version": "GOLD_TPCE_ECONOMIC_V1_DEVELOPMENT_RESULTS_1_0", "verdict": verdict,
        "candidate_count": len(candidate_results), "passing_candidate_count": len(passing), "passing_candidate_ids": passing,
        "signal_rows": len(signals), "trade_rows": len(primary), "executed_trade_rows": sum(row["status"] == "EXECUTED" for row in primary),
        "price_diagnostics": prices.diagnostics, "candidates": candidate_results, "portfolio": portfolio,
        "primary_reference_exact": True, "development_source_opening_count": 1,
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    reference_results = dict(results)
    reference_results["candidates"] = reference_candidate_results
    reference_results["portfolio"] = reference_portfolio
    write_json_exclusive(PRIMARY_RESULTS, results); write_json_exclusive(REFERENCE_RESULTS, reference_results)
    if sha256_file(PRIMARY_RESULTS) != sha256_file(REFERENCE_RESULTS):
        raise ValueError("Development result bytes differ")
    frozen = {
        "version": "GOLD_TPCE_ECONOMIC_V1_FROZEN_DEVELOPMENT_CANDIDATES_1_0",
        "status": "FROZEN_BEFORE_FORWARD_VALUES", "candidate_count": len(passing), "candidate_ids": passing,
        "candidate_results": [item for item in candidate_results if item["candidate_id"] in passing],
        "execution_protocol": file_record(PROTOCOL), "development_results": file_record(PRIMARY_RESULTS),
        "retuning_permitted": False, "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False,
    }
    write_json_exclusive(FROZEN_CANDIDATES, frozen)
    write_text_exclusive(REPORT, report_text(results))
    seal_items = [AUTHORIZATION, PRIMARY_TRADES, REFERENCE_TRADES, PRIMARY_RESULTS, REFERENCE_RESULTS, PORTFOLIO_PRIMARY, PORTFOLIO_REFERENCE, FROZEN_CANDIDATES, REPORT]
    seal = {
        "version": "GOLD_TPCE_ECONOMIC_V1_DEVELOPMENT_SEAL_1_0", "status": verdict, "sealed_at_utc": utc_now(),
        "artifacts": {path.name: file_record(path) for path in seal_items},
        "artifact_set_hash": canonical_hash({path.name: sha256_file(path) for path in seal_items}),
        "passing_candidate_ids": passing, "primary_reference_exact": True, "forward_values_accessed": False,
    }
    write_json_exclusive(DEVELOPMENT_SEAL, seal)
    write_json_exclusive(STATE, {
        "version": "GOLD_TPCE_ECONOMIC_V1_STATE_M3_1_0", "status": verdict, "recorded_at_utc": utc_now(),
        "passing_candidate_ids": passing, "development_seal": file_record(DEVELOPMENT_SEAL),
        "next_step": "OPEN_FORWARD_ONCE" if passing else "FINALIZE_ZERO_CANDIDATE_AND_LEDGER",
    })
    return results


def selftest() -> None:
    proof = synthetic_proof()
    if proof["status"] != "PASS":
        raise ValueError("Synthetic proof failed")
    fake = [
        {"cluster_date": "2024-01-01", "net_r": 1.0, "net_pnl_usd": 40.0, "known_at_utc": "2024-01-01T10:00:00Z", "mfe_r": 1.2, "mae_r": 0.2, "holding_minutes": 10, "target_r": 1.0, "cost_r": 0.1, "exit_reason": "TARGET"},
        {"cluster_date": "2024-01-02", "net_r": -1.1, "net_pnl_usd": -45.0, "known_at_utc": "2024-01-02T10:00:00Z", "mfe_r": 0.1, "mae_r": 1.0, "holding_minutes": 20, "target_r": 1.0, "cost_r": 0.1, "exit_reason": "STOP"},
    ]
    metrics = basic_metrics(fake)
    if metrics["trades"] != 2 or not math.isclose(float(metrics["expectancy_r"]), -0.05):
        raise ValueError("Synthetic metrics proof failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args(); selftest()
    if args.selftest:
        print(json.dumps({"status": "PASS_SYNTHETIC_DEVELOPMENT_EXECUTION_PROOF"}, indent=2)); return
    results = execute()
    print(json.dumps({
        "status": results["verdict"], "signals": results["signal_rows"], "executed_trade_rows": results["executed_trade_rows"],
        "passing_candidate_ids": results["passing_candidate_ids"],
        "candidates": [{"id": item["candidate_id"], "trades": item["metrics"]["trades"], "expectancy_r": item["metrics"].get("expectancy_r"), "pf": item["metrics"].get("profit_factor"), "pnl": item["metrics"].get("net_pnl_usd"), "verdict": item["verdict"], "failed_gates": item["failed_gates"]} for item in results["candidates"]],
        "portfolio": {"trades": results["portfolio"]["accepted_trades"], "metrics": results["portfolio"]["metrics"]},
        "development_seal": file_record(DEVELOPMENT_SEAL),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
