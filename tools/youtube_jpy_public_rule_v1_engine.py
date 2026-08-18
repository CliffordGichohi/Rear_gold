#!/usr/bin/env python3
"""Frozen mechanics for YouTube JPY Public-Rule Translation V1.

There are no file-opening side effects in this module. The sealed runner owns
all source openings and calls these deterministic functions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


UTC = ZoneInfo("UTC")
EAT = ZoneInfo("Africa/Nairobi")
SOURCE_START = pd.Timestamp("2021-08-01T00:00:00Z")
SOURCE_END = pd.Timestamp("2025-01-01T00:00:00Z")
CALENDAR_START_EAT = pd.Timestamp("2021-08-01T00:00:00", tz=EAT)
CALENDAR_END_EAT = pd.Timestamp("2025-01-01T00:00:00", tz=EAT)
STRICT_START = "2023-01-01"
STRICT_END = "2024-12-31"
PIP = 0.01
POINT = 0.001
STOP_PRICE = 0.15
TARGET_PRICE = 0.45
BE_PRICE = 0.20
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_SEED = 20260813
RANDOMIZATION_DRAWS = 20_000
RANDOMIZATION_SEED = 20260814
FOLDS = (
    ("2023_H1", "2023-01-01", "2023-07-01"),
    ("2023_H2", "2023-07-01", "2024-01-01"),
    ("2024_H1", "2024-01-01", "2024-07-01"),
    ("2024_H2", "2024-07-01", "2025-01-01"),
)
FULL_DAY_EVENT_IDS = {
    "840030001", "840030002", "840030003", "840030004",
    "840030005", "840030006", "840030007", "840030008",
    "840030009", "840030010", "840030033", "840030034",
    "840030035", "840030036", "840050014",
}
NFP_EVENT_IDS = {"840030016"}
MARKET_COLUMNS = [
    "open_time", "close_time", "available_at", "open", "high", "low",
    "close", "spread_points",
]


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def rounded(value: Any, digits: int = 12) -> Any:
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return round(number, digits)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): rounded(item, digits) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(item, digits) for item in value]
    return value


def _parse_utc_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, utc=True, errors="raise")


def read_market_primary(root: Path, source_paths: Sequence[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for relative in sorted(source_paths):
        frame = pd.read_csv(root / relative, usecols=MARKET_COLUMNS)
        frame["source_path"] = relative
        frame["source_row"] = np.arange(1, len(frame) + 1, dtype=np.int64)
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)
    for column in ("open_time", "close_time", "available_at"):
        data[column] = _parse_utc_series(data[column])
    for column in ("open", "high", "low", "close", "spread_points"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    data = data[(data["open_time"] >= SOURCE_START) & (data["open_time"] < SOURCE_END)]
    data = data.sort_values(["source_path", "source_row"], kind="mergesort")
    data = data.drop_duplicates("open_time", keep="first")
    return data.sort_values("open_time", kind="mergesort").reset_index(drop=True)


def read_market_reference(root: Path, source_paths: Sequence[str]) -> pd.DataFrame:
    """Independent stdlib CSV reader; first lexicographic source occurrence wins."""

    rows: dict[str, tuple[Any, ...]] = {}
    for relative in sorted(source_paths):
        with (root / relative).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row_number, row in enumerate(reader, start=1):
                stamp = datetime.fromisoformat(str(row["open_time"]).replace("Z", "+00:00")).astimezone(UTC)
                if stamp < SOURCE_START.to_pydatetime() or stamp >= SOURCE_END.to_pydatetime():
                    continue
                key = stamp.isoformat()
                if key in rows:
                    continue
                rows[key] = (
                    stamp,
                    datetime.fromisoformat(str(row["close_time"]).replace("Z", "+00:00")).astimezone(UTC),
                    datetime.fromisoformat(str(row["available_at"]).replace("Z", "+00:00")).astimezone(UTC),
                    float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]),
                    float(row["spread_points"]), relative, row_number,
                )
    ordered = [rows[key] for key in sorted(rows)]
    return pd.DataFrame(
        ordered,
        columns=MARKET_COLUMNS + ["source_path", "source_row"],
    )


def market_integrity(data: pd.DataFrame) -> dict[str, Any]:
    minute = pd.Timedelta(minutes=1)
    checks = {
        "rows": len(data),
        "unique_open_times": int(data["open_time"].nunique()),
        "duplicates": int(data["open_time"].duplicated().sum()),
        "ordered": bool(data["open_time"].is_monotonic_increasing),
        "close_exact_plus_one_minute": bool(((data["close_time"] - data["open_time"]) == minute).all()),
        "available_at_not_before_close": bool((data["available_at"] >= data["close_time"]).all()),
        "ohlc_valid": bool(
            (data["high"] >= data[["open", "close", "low"]].max(axis=1)).all()
            and (data["low"] <= data[["open", "close", "high"]].min(axis=1)).all()
        ),
        "spread_nonnegative": bool((data["spread_points"] >= 0).all()),
    }
    checks["pass"] = bool(
        checks["rows"] == checks["unique_open_times"]
        and checks["duplicates"] == 0
        and all(checks[key] for key in (
            "ordered", "close_exact_plus_one_minute", "available_at_not_before_close", "ohlc_valid", "spread_nonnegative"
        ))
    )
    return checks


def read_news_primary(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path, usecols=["event_id", "event_time_server", "event_name"])
    frame["event_id"] = frame["event_id"].astype(str)
    selected = frame[frame["event_id"].isin(FULL_DAY_EVENT_IDS | NFP_EVENT_IDS)].copy()
    selected["event_time_eat"] = pd.to_datetime(selected["event_time_server"], format="%Y.%m.%d %H:%M:%S", errors="raise").dt.tz_localize(EAT)
    selected = selected[(selected["event_time_eat"] >= CALENDAR_START_EAT) & (selected["event_time_eat"] < CALENDAR_END_EAT)]
    return _news_payload(selected.to_dict("records"))


def read_news_reference(path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            event_id = str(row["event_id"])
            if event_id not in FULL_DAY_EVENT_IDS | NFP_EVENT_IDS:
                continue
            stamp = datetime.strptime(row["event_time_server"], "%Y.%m.%d %H:%M:%S").replace(tzinfo=EAT)
            if stamp < CALENDAR_START_EAT.to_pydatetime() or stamp >= CALENDAR_END_EAT.to_pydatetime():
                continue
            rows.append({"event_id": event_id, "event_time_eat": stamp, "event_name": row["event_name"]})
    return _news_payload(rows)


def _news_payload(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    full_dates: set[str] = set()
    nfp_weeks: set[str] = set()
    identities: list[dict[str, str]] = []
    for row in rows:
        stamp = pd.Timestamp(row["event_time_eat"]).to_pydatetime()
        event_id = str(row["event_id"])
        day = stamp.date().isoformat()
        iso = stamp.date().isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        if event_id in FULL_DAY_EVENT_IDS:
            full_dates.add(day)
        if event_id in NFP_EVENT_IDS:
            nfp_weeks.add(week)
        identities.append({"event_id": event_id, "event_time_eat": stamp.isoformat(), "event_name": str(row["event_name"])})
    identities.sort(key=lambda item: (item["event_time_eat"], item["event_id"], item["event_name"]))
    return {
        "full_dates": sorted(full_dates),
        "nfp_weeks": sorted(nfp_weeks),
        "identities": identities,
        "checksum": canonical_hash(identities),
    }


def _aggregate_ohlc(grouped: Any, minimum_rows: int, interval_minutes: int) -> pd.DataFrame:
    result = grouped.agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        rows=("open", "size"), first_utc=("open_time", "first"), last_utc=("open_time", "last"),
    ).reset_index()
    result["complete"] = result["rows"] >= minimum_rows
    result["interval_minutes"] = interval_minutes
    return result


def prepare_market(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frame = data.copy()
    frame["eat_time"] = frame["open_time"].dt.tz_convert(EAT)
    frame["eat_date"] = frame["eat_time"].dt.strftime("%Y-%m-%d")
    frame["eat_clock"] = frame["eat_time"].dt.strftime("%H:%M")
    frame["m15_start"] = frame["eat_time"].dt.floor("15min")
    frame["h1_start"] = frame["eat_time"].dt.floor("1h")

    daily = _aggregate_ohlc(frame.groupby("eat_date", sort=True), 1200, 1440)
    daily["weekday"] = pd.to_datetime(daily["eat_date"]).dt.weekday
    daily = daily[(daily["weekday"] < 5) & daily["complete"]].reset_index(drop=True)
    previous_close = daily["close"].shift(1)
    daily["true_range"] = np.maximum.reduce([
        (daily["high"] - daily["low"]).to_numpy(float),
        (daily["high"] - previous_close).abs().to_numpy(float),
        (daily["low"] - previous_close).abs().to_numpy(float),
    ])
    daily["atr20"] = daily["true_range"].rolling(20, min_periods=20).mean()

    m15 = _aggregate_ohlc(frame.groupby("m15_start", sort=True), 14, 15)
    m15["end_time"] = m15["m15_start"] + pd.Timedelta(minutes=15)
    m15["eat_date"] = m15["m15_start"].dt.strftime("%Y-%m-%d")
    m15 = m15[m15["complete"]].reset_index(drop=True)
    prior_m15_close = m15["close"].shift(1)
    m15["true_range"] = np.maximum.reduce([
        (m15["high"] - m15["low"]).to_numpy(float),
        (m15["high"] - prior_m15_close).abs().to_numpy(float),
        (m15["low"] - prior_m15_close).abs().to_numpy(float),
    ])
    m15["atr14"] = m15["true_range"].rolling(14, min_periods=14).mean()

    h1 = _aggregate_ohlc(frame.groupby("h1_start", sort=True), 56, 60)
    h1["end_time"] = h1["h1_start"] + pd.Timedelta(hours=1)
    h1["eat_date"] = h1["h1_start"].dt.strftime("%Y-%m-%d")
    h1 = h1[h1["complete"]].reset_index(drop=True)

    session_mask = (frame["eat_clock"] >= "06:00") & (frame["eat_clock"] < "20:00")
    sessions: dict[str, dict[str, Any]] = {}
    for day, subset in frame[session_mask].groupby("eat_date", sort=True):
        subset = subset.sort_values("open_time", kind="mergesort")
        by_clock = {str(row.eat_clock): row for row in subset.itertuples(index=False)}
        sessions[day] = {
            "rows": len(subset),
            "complete": len(subset) >= 798 and "06:00" in by_clock and "19:59" in by_clock,
            "open": float(by_clock["06:00"].open) if "06:00" in by_clock else None,
            "close": float(by_clock["19:59"].close) if "19:59" in by_clock else None,
            "first_utc": subset.iloc[0]["open_time"],
            "last_utc": subset.iloc[-1]["open_time"],
        }
    return {"m1": frame, "daily": daily, "m15": m15, "h1": h1, "sessions": sessions}


def _iso_week(day: str) -> str:
    iso = date.fromisoformat(day).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _fold(day: str) -> str | None:
    for name, start, end in FOLDS:
        if start <= day < end:
            return name
    return None


def _session_path(subset: pd.DataFrame, direction: int, origin: float) -> dict[str, Any]:
    signed_close = direction * (float(subset.iloc[-1]["close"]) - origin) / PIP
    if direction > 0:
        mfe = (float(subset["high"].max()) - origin) / PIP
        mae = (origin - float(subset["low"].min())) / PIP
    else:
        mfe = (origin - float(subset["low"].min())) / PIP
        mae = (float(subset["high"].max()) - origin) / PIP
    passage = "UNRESOLVED"
    for row in subset.itertuples(index=False):
        if direction > 0:
            stop_hit, target_hit = float(row.low) <= origin - STOP_PRICE, float(row.high) >= origin + TARGET_PRICE
        else:
            stop_hit, target_hit = float(row.high) >= origin + STOP_PRICE, float(row.low) <= origin - TARGET_PRICE
        if stop_hit:
            passage = "ADVERSE_15_FIRST"
            break
        if target_hit:
            passage = "FAVOURABLE_45_FIRST"
            break
    return rounded({
        "signed_displacement_pips": round(signed_close, 9),
        "direction_hit": signed_close > 0,
        "mfe_pips": round(mfe, 9),
        "mae_pips": round(mae, 9),
        "session_first_passage": passage,
    })


def build_stage1_cases(prepared: Mapping[str, Any], news: Mapping[str, Any]) -> list[dict[str, Any]]:
    daily = prepared["daily"].reset_index(drop=True)
    m1 = prepared["m1"]
    sessions = prepared["sessions"]
    daily_dates = daily["eat_date"].tolist()
    m1_by_day = {
        str(day): subset.sort_values("open_time", kind="mergesort")
        for day, subset in m1.groupby("eat_date", sort=True)
    }
    full_dates = set(news["full_dates"])
    nfp_weeks = set(news["nfp_weeks"])
    output: list[dict[str, Any]] = []
    for session_day in sorted(sessions):
        if not sessions[session_day]["complete"] or date.fromisoformat(session_day).weekday() >= 5:
            continue
        prior_index = bisect_left(daily_dates, session_day) - 1
        if prior_index < 0:
            continue
        if prior_index < 251:
            continue
        closes = daily.iloc[prior_index - 251: prior_index + 1]["close"].to_numpy(float)
        if len(closes) != 252 or not np.isfinite(closes).all():
            continue
        slope = float(np.polyfit(np.arange(252, dtype=float), closes, 1)[0])
        direction = 1 if slope > 0 else -1 if slope < 0 else 0
        if direction == 0:
            continue
        previous = daily.iloc[prior_index]
        body = float(previous["close"] - previous["open"])
        if body == 0 or (1 if body > 0 else -1) != direction:
            continue
        if session_day in full_dates or _iso_week(session_day) in nfp_weeks:
            continue
        day_rows = m1_by_day.get(session_day)
        if day_rows is None:
            continue
        subset = day_rows[(day_rows["eat_clock"] >= "06:00") & (day_rows["eat_clock"] < "20:00")]
        if len(subset) < 798:
            continue
        opens = subset[subset["eat_clock"] == "06:00"]
        closes_ = subset[subset["eat_clock"] == "19:59"]
        if len(opens) != 1 or len(closes_) != 1:
            continue
        origin = float(opens.iloc[0]["open"])
        path = _session_path(subset, direction, origin)
        output.append(rounded({
            "case_id": hashlib.sha256(f"USDJPY|{session_day}|{direction}".encode()).hexdigest(),
            "session_date": session_day,
            "direction": direction,
            "trend_slope": slope,
            "prior_day": str(previous["eat_date"]),
            "prior_day_open": float(previous["open"]),
            "prior_day_high": float(previous["high"]),
            "prior_day_low": float(previous["low"]),
            "prior_day_close": float(previous["close"]),
            "prior_day_atr20": float(previous["atr20"]) if pd.notna(previous["atr20"]) else None,
            "session_open": origin,
            "session_close": float(closes_.iloc[0]["close"]),
            "cluster_week": _iso_week(session_day),
            "year": session_day[:4],
            "fold": _fold(session_day),
            **path,
        }))
    return output


def _pivot_rows(daily: pd.DataFrame, side: str) -> list[dict[str, Any]]:
    values = daily["low"].to_numpy(float) if side == "LOW" else daily["high"].to_numpy(float)
    output = []
    for index in range(2, len(values) - 2):
        center = values[index]
        neighbors = [values[index - 2], values[index - 1], values[index + 1], values[index + 2]]
        condition = all(center < item for item in neighbors) if side == "LOW" else all(center > item for item in neighbors)
        if condition:
            output.append({"index": index, "known_index": index + 2, "price": center, "date": str(daily.iloc[index]["eat_date"])})
    return output


def find_location(daily: pd.DataFrame, prior_index: int, direction: int) -> dict[str, Any] | None:
    atr = float(daily.iloc[prior_index]["atr20"])
    if not math.isfinite(atr) or atr <= 0:
        return None
    side = "LOW" if direction > 0 else "HIGH"
    pivots = [item for item in _pivot_rows(daily, side) if max(0, prior_index - 504) <= item["index"] and item["known_index"] < prior_index]
    clusters: list[list[dict[str, Any]]] = []
    for pivot in pivots:
        accepted = False
        for cluster in clusters:
            median = float(np.median([item["price"] for item in cluster]))
            if abs(pivot["price"] - median) <= 0.15 * atr and pivot["index"] - cluster[-1]["index"] >= 5:
                cluster.append(pivot)
                accepted = True
                break
        if not accepted:
            clusters.append([pivot])
    previous = daily.iloc[prior_index]
    candidates: list[dict[str, Any]] = []
    for cluster in clusters:
        if len(cluster) < 3:
            continue
        level = float(np.median([item["price"] for item in cluster]))
        since = daily.iloc[cluster[-1]["index"] + 1: prior_index]
        if direction > 0 and len(since) and bool((since["close"] < level - 0.20 * atr).any()):
            continue
        if direction < 0 and len(since) and bool((since["close"] > level + 0.20 * atr).any()):
            continue
        extreme = float(previous["low"] if direction > 0 else previous["high"])
        bounce = abs(extreme - level) <= 0.20 * atr
        bounce = bounce and (float(previous["close"]) > level if direction > 0 else float(previous["close"]) < level)
        if not bounce:
            continue
        candidates.append({
            "level": level, "touches": len(cluster), "last_touch_date": cluster[-1]["date"],
            "distance_atr": abs(extreme - level) / atr,
        })
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["distance_atr"], -item["touches"], item["last_touch_date"], item["level"]))
    return rounded(candidates[0])


def attach_locations(cases: Sequence[Mapping[str, Any]], daily: pd.DataFrame) -> list[dict[str, Any]]:
    index_by_date = {str(row.eat_date): index for index, row in enumerate(daily.itertuples(index=False))}
    output = []
    for source in cases:
        row = dict(source)
        prior_index = index_by_date[str(row["prior_day"])]
        location = find_location(daily, prior_index, int(row["direction"]))
        row["location"] = location
        row["location_eligible"] = location is not None
        output.append(rounded(row))
    return output


def _strict_credit(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if STRICT_START <= str(row["session_date"]) <= STRICT_END]


def _period_summary(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    values = np.asarray([float(row[field]) for row in rows], dtype=float)
    return rounded({"support": len(rows), "mean": float(values.mean()) if len(values) else None, "sum": float(values.sum()) if len(values) else None})


def _cluster_bootstrap(rows: Sequence[Mapping[str, Any]], field: str, comparator: str | None = None) -> dict[str, Any]:
    clusters: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        clusters[str(row["cluster_week"])].append(row)
    keys = sorted(clusters)
    if not keys:
        return {
            "draws": 0,
            "seed": BOOTSTRAP_SEED,
            "ci95": [None, None],
            "p_lte_zero": None,
        }
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        sampled = rng.choice(keys, size=len(keys), replace=True)
        selected = [row for key in sampled for row in clusters[str(key)]]
        if comparator is None:
            draws[draw] = float(np.mean([float(row[field]) for row in selected]))
        else:
            left = [float(row[field]) for row in selected if bool(row[comparator])]
            right = [float(row[field]) for row in selected if not bool(row[comparator])]
            draws[draw] = float(np.mean(left) - np.mean(right)) if left and right else np.nan
    draws = draws[np.isfinite(draws)]
    return rounded({
        "draws": int(len(draws)), "seed": BOOTSTRAP_SEED,
        "ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
        "p_lte_zero": float(np.mean(draws <= 0)),
    })


def _cluster_sign_randomization(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    clusters: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        clusters[str(row["cluster_week"])].append(float(row[field]))
    keys = sorted(clusters)
    if not keys:
        return {
            "draws": RANDOMIZATION_DRAWS,
            "seed": RANDOMIZATION_SEED,
            "one_sided_p": None,
        }
    totals = np.asarray([sum(clusters[key]) for key in keys], dtype=float)
    count = sum(len(clusters[key]) for key in keys)
    observed = float(totals.sum() / count)
    rng = np.random.default_rng(RANDOMIZATION_SEED)
    greater = 0
    for _ in range(RANDOMIZATION_DRAWS):
        value = float((totals * rng.choice(np.asarray([-1.0, 1.0]), size=len(totals))).sum() / count)
        greater += value >= observed
    return rounded({"draws": RANDOMIZATION_DRAWS, "seed": RANDOMIZATION_SEED, "one_sided_p": (greater + 1) / (RANDOMIZATION_DRAWS + 1)})


def _support_breakdown(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "overall": len(rows),
        "years": {year: sum(str(row["session_date"]).startswith(year) for row in rows) for year in ("2023", "2024")},
        "folds": {name: sum(str(row.get("fold")) == name for row in rows) for name, _, _ in FOLDS},
    }


def evaluate_stage1(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _strict_credit(cases)
    support = _support_breakdown(rows)
    values = np.asarray([float(row["signed_displacement_pips"]) for row in rows], dtype=float)
    years = {year: _period_summary([row for row in rows if str(row["session_date"]).startswith(year)], "signed_displacement_pips") for year in ("2023", "2024")}
    folds = {name: _period_summary([row for row in rows if row.get("fold") == name], "signed_displacement_pips") for name, _, _ in FOLDS}
    bootstrap = _cluster_bootstrap(rows, "signed_displacement_pips")
    randomization = _cluster_sign_randomization(rows, "signed_displacement_pips")
    hit_rate = float(np.mean([bool(row["direction_hit"]) for row in rows])) if rows else 0.0
    gates = {
        "support": support["overall"] >= 150 and all(value >= 60 for value in support["years"].values()) and all(value >= 25 for value in support["folds"].values()),
        "mean_signed_pips_gt_zero": bool(len(values)) and float(values.mean()) > 0,
        "cluster_ci95_low_gt_zero": bootstrap["ci95"][0] is not None and float(bootstrap["ci95"][0]) > 0,
        "cluster_randomization_p_lte_0p05": randomization["one_sided_p"] is not None and float(randomization["one_sided_p"]) <= 0.05,
        "direction_hit_rate_gt_0p50": hit_rate > 0.50,
        "both_years_positive": all(float(item["mean"] or 0) > 0 for item in years.values()),
        "positive_folds_gte_3": sum(float(item["mean"] or 0) > 0 for item in folds.values()) >= 3,
    }
    return rounded({
        "stage": "STAGE_1_CONTEXTUAL_PREMISE", "support": support,
        "mean_signed_displacement_pips": float(values.mean()) if len(values) else None,
        "direction_hit_rate": hit_rate,
        "mean_mfe_pips": float(np.mean([float(row["mfe_pips"]) for row in rows])) if rows else None,
        "mean_mae_pips": float(np.mean([float(row["mae_pips"]) for row in rows])) if rows else None,
        "first_passage": {state: sum(row["session_first_passage"] == state for row in rows) for state in ("FAVOURABLE_45_FIRST", "ADVERSE_15_FIRST", "UNRESOLVED")},
        "bootstrap": bootstrap, "randomization": randomization, "years": years, "folds": folds,
        "gates": gates, "failed_gates": [key for key, value in gates.items() if not value],
        "verdict": "PASS" if all(gates.values()) else "REJECT",
    })


def evaluate_stage2(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    all_rows = _strict_credit(cases)
    rows = [row for row in all_rows if bool(row["location_eligible"])]
    support = _support_breakdown(rows)
    values = np.asarray([float(row["signed_displacement_pips"]) for row in rows], dtype=float)
    years = {year: _period_summary([row for row in rows if str(row["session_date"]).startswith(year)], "signed_displacement_pips") for year in ("2023", "2024")}
    folds = {name: _period_summary([row for row in rows if row.get("fold") == name], "signed_displacement_pips") for name, _, _ in FOLDS}
    bootstrap = _cluster_bootstrap(rows, "signed_displacement_pips") if rows else {"ci95": [None, None]}
    incremental = _cluster_bootstrap(all_rows, "signed_displacement_pips", "location_eligible") if rows and len(rows) < len(all_rows) else {"ci95": [None, None]}
    location_hit = float(np.mean([bool(row["direction_hit"]) for row in rows])) if rows else 0.0
    baseline_hit = float(np.mean([bool(row["direction_hit"]) for row in all_rows])) if all_rows else 0.0
    non_location = [float(row["signed_displacement_pips"]) for row in all_rows if not bool(row["location_eligible"])]
    increment_mean = float(values.mean() - np.mean(non_location)) if len(values) and non_location else None
    gates = {
        "support": support["overall"] >= 50 and all(value >= 15 for value in support["years"].values()) and all(value >= 8 for value in support["folds"].values()),
        "location_mean_gt_zero": bool(len(values)) and float(values.mean()) > 0,
        "location_ci95_low_gt_zero": bool(rows) and bootstrap["ci95"][0] is not None and float(bootstrap["ci95"][0]) > 0,
        "incremental_mean_gt_zero": increment_mean is not None and increment_mean > 0,
        "incremental_ci95_low_gt_zero": incremental["ci95"][0] is not None and float(incremental["ci95"][0]) > 0,
        "location_hit_rate_gt_baseline": location_hit > baseline_hit,
        "both_years_positive": all(float(item["mean"] or 0) > 0 for item in years.values()),
        "positive_folds_gte_3": sum(float(item["mean"] or 0) > 0 for item in folds.values()) >= 3,
    }
    return rounded({
        "stage": "STAGE_2_LOCATION_INCREMENT", "support": support,
        "location_mean_signed_pips": float(values.mean()) if len(values) else None,
        "non_location_mean_signed_pips": float(np.mean(non_location)) if non_location else None,
        "incremental_mean_pips": increment_mean, "location_hit_rate": location_hit, "baseline_hit_rate": baseline_hit,
        "bootstrap": bootstrap, "incremental_bootstrap": incremental, "years": years, "folds": folds,
        "gates": gates, "failed_gates": [key for key, value in gates.items() if not value],
        "verdict": "PASS" if all(gates.values()) else "REJECT",
    })


def _pivots_m15(bars: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lows, highs = [], []
    for index in range(1, len(bars) - 1):
        if float(bars.iloc[index]["low"]) < float(bars.iloc[index - 1]["low"]) and float(bars.iloc[index]["low"]) < float(bars.iloc[index + 1]["low"]):
            lows.append({"index": index, "known_index": index + 1, "price": float(bars.iloc[index]["low"])})
        if float(bars.iloc[index]["high"]) > float(bars.iloc[index - 1]["high"]) and float(bars.iloc[index]["high"]) > float(bars.iloc[index + 1]["high"]):
            highs.append({"index": index, "known_index": index + 1, "price": float(bars.iloc[index]["high"])})
    return lows, highs


def _latest(items: Sequence[Mapping[str, Any]], before_index: int) -> Mapping[str, Any] | None:
    eligible = [item for item in items if int(item["index"]) < before_index and int(item["known_index"]) <= before_index]
    return eligible[-1] if eligible else None


def _aligned_h1(h1: pd.DataFrame, fill_time: pd.Timestamp, direction: int) -> bool:
    eligible = h1[h1["end_time"] <= fill_time]
    if len(eligible) == 0:
        return False
    row = eligible.iloc[-1]
    body = float(row["close"] - row["open"])
    return body != 0 and (1 if body > 0 else -1) == direction


def find_trigger(case: Mapping[str, Any], prepared: Mapping[str, Any]) -> dict[str, Any] | None:
    day = str(case["session_date"])
    direction = int(case["direction"])
    m15 = prepared["m15"]
    bars = m15[(m15["eat_date"] == day) & (m15["m15_start"].dt.strftime("%H:%M") >= "00:00") & (m15["m15_start"].dt.strftime("%H:%M") < "20:00")].reset_index(drop=True)
    if len(bars) < 20:
        return None
    lows, highs = _pivots_m15(bars)
    m1 = prepared["m1"]
    day_m1 = m1[(m1["eat_date"] == day) & (m1["eat_clock"] >= "06:00") & (m1["eat_clock"] < "20:00")].sort_values("open_time")
    h1 = prepared["h1"]
    h1_day = h1[h1["eat_date"] == day]
    processed: set[tuple[int, int, int]] = set()
    for confirm_index in range(len(bars)):
        confirm = bars.iloc[confirm_index]
        end_clock = confirm["end_time"].strftime("%H:%M")
        if end_clock < "06:00" or end_clock > "19:45" or pd.isna(confirm["atr14"]):
            continue
        atr = float(confirm["atr14"])
        if direction > 0:
            leg2 = _latest(lows, confirm_index)
            neck = _latest(highs, int(leg2["index"])) if leg2 else None
            leg1 = _latest(lows, int(neck["index"])) if neck else None
            impulse_high = _latest(highs, int(leg1["index"])) if leg1 else None
            impulse_low = _latest(lows, int(impulse_high["index"])) if impulse_high else None
        else:
            leg2 = _latest(highs, confirm_index)
            neck = _latest(lows, int(leg2["index"])) if leg2 else None
            leg1 = _latest(highs, int(neck["index"])) if neck else None
            impulse_low = _latest(lows, int(leg1["index"])) if leg1 else None
            impulse_high = _latest(highs, int(impulse_low["index"])) if impulse_low else None
        if not all(item is not None for item in (leg2, neck, leg1, impulse_low, impulse_high)):
            continue
        key = (int(leg1["index"]), int(neck["index"]), int(leg2["index"]))
        if key in processed:
            continue
        if confirm_index - int(leg1["index"]) > 16:
            continue
        neckline = float(neck["price"])
        if direction > 0:
            body_ok = float(confirm["close"]) > float(confirm["open"])
            break_ok = float(confirm["close"]) >= neckline + 0.02 * atr
            legs_ok = neckline - float(leg1["price"]) >= 0.25 * atr and neckline - float(leg2["price"]) >= 0.25 * atr
            impulse_size = float(impulse_high["price"]) - float(impulse_low["price"])
            depth = (float(impulse_high["price"]) - min(float(leg1["price"]), float(leg2["price"]))) / impulse_size if impulse_size > 0 else math.nan
            invalidation = float(leg2["price"]) - 0.02 * atr
        else:
            body_ok = float(confirm["close"]) < float(confirm["open"])
            break_ok = float(confirm["close"]) <= neckline - 0.02 * atr
            legs_ok = float(leg1["price"]) - neckline >= 0.25 * atr and float(leg2["price"]) - neckline >= 0.25 * atr
            impulse_size = float(impulse_high["price"]) - float(impulse_low["price"])
            depth = (max(float(leg1["price"]), float(leg2["price"])) - float(impulse_low["price"])) / impulse_size if impulse_size > 0 else math.nan
            invalidation = float(leg2["price"]) + 0.02 * atr
        if not (body_ok and break_ok and legs_ok and impulse_size >= 0.75 * atr and 0.382 <= depth <= 1.0):
            continue
        processed.add(key)
        eligible_at = pd.Timestamp(confirm["end_time"]) + pd.Timedelta(minutes=1)
        path = day_m1[day_m1["eat_time"] >= eligible_at]
        for row in path.itertuples(index=False):
            invalid = float(row.low) <= invalidation if direction > 0 else float(row.high) >= invalidation
            touched = float(row.low) <= neckline <= float(row.high)
            if invalid:
                break
            if touched:
                fill_time = pd.Timestamp(row.eat_time)
                if _aligned_h1(h1_day, fill_time, direction):
                    return rounded({
                        "case_id": case["case_id"], "session_date": day, "direction": direction,
                        "decision_time": pd.Timestamp(confirm["end_time"]), "fill_time": fill_time,
                        "entry_price": neckline, "entry_spread_points": float(row.spread_points),
                        "confirmation_atr14": atr, "pullback_depth": depth,
                        "impulse_atr": impulse_size / atr, "leg1_atr": abs(neckline - float(leg1["price"])) / atr,
                        "leg2_atr": abs(neckline - float(leg2["price"])) / atr,
                        "pattern_bars": confirm_index - int(leg1["index"]),
                        "cluster_week": case["cluster_week"], "year": case["year"], "fold": case["fold"],
                    })
                break
    return None


def _path_result(trigger: Mapping[str, Any], prepared: Mapping[str, Any], break_even: bool) -> dict[str, Any] | None:
    direction = int(trigger["direction"])
    entry = float(trigger["entry_price"])
    start = pd.Timestamp(str(trigger["fill_time"]))
    if start.tzinfo is None:
        start = start.tz_localize(EAT)
    deadline = start + pd.Timedelta(hours=10)
    m1 = prepared["m1"]
    path = m1[(m1["eat_time"] >= start) & (m1["eat_time"] < deadline)].sort_values("open_time")
    expected = int((deadline - start).total_seconds() // 60)
    if len(path) < math.ceil(0.95 * expected) or len(path) == 0 or pd.Timestamp(path.iloc[0]["eat_time"]) != start:
        return None
    be_active = False
    outcome = "TIME_EXIT"
    gross_r = None
    exit_row = None
    for row in path.itertuples(index=False):
        if direction > 0:
            original_stop = float(row.low) <= entry - STOP_PRICE
            active_be_stop = be_active and float(row.low) <= entry
            target = float(row.high) >= entry + TARGET_PRICE
            activates = float(row.high) >= entry + BE_PRICE
            revisits = float(row.low) <= entry
        else:
            original_stop = float(row.high) >= entry + STOP_PRICE
            active_be_stop = be_active and float(row.high) >= entry
            target = float(row.low) <= entry - TARGET_PRICE
            activates = float(row.low) <= entry - BE_PRICE
            revisits = float(row.high) >= entry
        if original_stop:
            outcome, gross_r, exit_row = "STOP", -1.0, row
            break
        if break_even and active_be_stop:
            outcome, gross_r, exit_row = "BREAK_EVEN", 0.0, row
            break
        if break_even and not be_active and activates and revisits:
            outcome, gross_r, exit_row = "BREAK_EVEN", 0.0, row
            break
        if target:
            outcome, gross_r, exit_row = "TARGET", 3.0, row
            break
        if break_even and activates:
            be_active = True
    if exit_row is None:
        exit_row = list(path.itertuples(index=False))[-1]
        gross_r = max(-1.0, min(3.0, direction * (float(exit_row.close) - entry) / STOP_PRICE))
    return rounded({
        **dict(trigger), "path_rows": len(path), "outcome": outcome, "gross_r": gross_r,
        "exit_time": pd.Timestamp(exit_row.eat_time), "exit_price": float(exit_row.close),
        "exit_spread_points": float(exit_row.spread_points), "break_even_policy": break_even,
    })


def materialize_triggers(cases: Sequence[Mapping[str, Any]], prepared: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = []
    busy_until: pd.Timestamp | None = None
    for case in sorted(cases, key=lambda item: item["session_date"]):
        if not bool(case.get("location_eligible")):
            continue
        trigger = find_trigger(case, prepared)
        if trigger is None:
            continue
        fill = pd.Timestamp(str(trigger["fill_time"]))
        if busy_until is not None and fill < busy_until:
            continue
        raw = _path_result(trigger, prepared, False)
        if raw is None:
            continue
        busy_until = pd.Timestamp(str(raw["exit_time"]))
        output.append(raw)
    return output


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    return gains / losses if losses > 0 else None


def _maximum_drawdown(values: Sequence[float]) -> float:
    equity = peak = maximum = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def evaluate_stage3(triggers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _strict_credit(triggers)
    support = _support_breakdown(rows)
    values = [float(row["gross_r"]) for row in rows]
    years = {year: _period_summary([row for row in rows if str(row["session_date"]).startswith(year)], "gross_r") for year in ("2023", "2024")}
    folds = {name: _period_summary([row for row in rows if row.get("fold") == name], "gross_r") for name, _, _ in FOLDS}
    bootstrap = _cluster_bootstrap(rows, "gross_r") if rows else {"ci95": [None, None]}
    pf = _profit_factor(values)
    gates = {
        "support": support["overall"] >= 30 and all(value >= 10 for value in support["years"].values()) and all(value >= 5 for value in support["folds"].values()),
        "gross_expectancy_gt_zero": bool(values) and float(np.mean(values)) > 0,
        "profit_factor_gte_1p10": pf is not None and pf >= 1.10,
        "cluster_ci95_low_gt_zero": bool(rows) and bootstrap["ci95"][0] is not None and float(bootstrap["ci95"][0]) > 0,
        "both_years_positive": all(float(item["mean"] or 0) > 0 for item in years.values()),
        "positive_folds_gte_3": sum(float(item["mean"] or 0) > 0 for item in folds.values()) >= 3,
    }
    return rounded({
        "stage": "STAGE_3_TRIGGER_INCREMENT", "support": support,
        "gross_expectancy_r": float(np.mean(values)) if values else None, "profit_factor": pf,
        "target_rate": float(np.mean([row["outcome"] == "TARGET" for row in rows])) if rows else None,
        "stop_rate": float(np.mean([row["outcome"] == "STOP" for row in rows])) if rows else None,
        "bootstrap": bootstrap, "years": years, "folds": folds, "gates": gates,
        "failed_gates": [key for key, value in gates.items() if not value], "verdict": "PASS" if all(gates.values()) else "REJECT",
    })


def materialize_economics(triggers: Sequence[Mapping[str, Any]], prepared: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = []
    for trigger in triggers:
        result = _path_result(trigger, prepared, True)
        if result is None:
            continue
        cost = max(max(float(result["entry_spread_points"]), float(result["exit_spread_points"])) * POINT / STOP_PRICE + 0.03, 0.05)
        entry = float(result["entry_price"])
        raw_lots = 100.0 / (STOP_PRICE * 100_000.0 / entry)
        lots = math.floor((raw_lots + 1e-12) / 0.01) * 0.01
        actual_risk = lots * STOP_PRICE * 100_000.0 / entry
        result.update(rounded({
            "base_cost_r": cost, "net_r": float(result["gross_r"]) - cost,
            "stress_1p5_net_r": float(result["gross_r"]) - 1.5 * cost,
            "stress_2p0_net_r": float(result["gross_r"]) - 2.0 * cost,
            "volume_lots": lots, "actual_planned_risk_usd": actual_risk,
            "net_usd_at_frozen_100_per_r": (float(result["gross_r"]) - cost) * 100.0,
        }))
        output.append(rounded(result))
    return output


def evaluate_stage4(economics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _strict_credit(economics)
    values = [float(row["net_r"]) for row in rows]
    stress = [float(row["stress_1p5_net_r"]) for row in rows]
    years = {year: _period_summary([row for row in rows if str(row["session_date"]).startswith(year)], "net_r") for year in ("2023", "2024")}
    folds = {name: _period_summary([row for row in rows if row.get("fold") == name], "net_r") for name, _, _ in FOLDS}
    bootstrap = _cluster_bootstrap(rows, "net_r") if rows else {"ci95": [None, None]}
    pf = _profit_factor(values)
    positive_years = [float(item["sum"]) for item in years.values() if float(item["sum"] or 0) > 0]
    maximum_year_share = max(positive_years) / sum(positive_years) if positive_years else None
    gates = {
        "net_expectancy_gt_zero": bool(values) and float(np.mean(values)) > 0,
        "profit_factor_gte_1p10": pf is not None and pf >= 1.10,
        "cluster_ci95_low_gt_zero": bool(rows) and bootstrap["ci95"][0] is not None and float(bootstrap["ci95"][0]) > 0,
        "stress_1p5_expectancy_gt_zero": bool(stress) and float(np.mean(stress)) > 0,
        "both_years_positive": all(float(item["mean"] or 0) > 0 for item in years.values()),
        "positive_folds_gte_3": sum(float(item["mean"] or 0) > 0 for item in folds.values()) >= 3,
        "maximum_drawdown_lte_15r": _maximum_drawdown(values) <= 15.0,
        "maximum_positive_year_share_lte_0p70": maximum_year_share is not None and maximum_year_share <= 0.70,
    }
    months = 24.0
    return rounded({
        "stage": "STAGE_4_PUBLISHED_ECONOMICS", "support": len(rows),
        "win_rate": float(np.mean(np.asarray(values) > 0)) if values else None,
        "net_expectancy_r": float(np.mean(values)) if values else None, "profit_factor": pf,
        "net_r": sum(values), "net_r_per_month": sum(values) / months, "usd_per_month": sum(values) * 100.0 / months,
        "trades_per_month": len(rows) / months, "maximum_drawdown_r": _maximum_drawdown(values),
        "stress_1p5_expectancy_r": float(np.mean(stress)) if stress else None,
        "bootstrap": bootstrap, "years": years, "folds": folds, "maximum_positive_year_share": maximum_year_share,
        "gates": gates, "failed_gates": [key for key, value in gates.items() if not value],
        "verdict": "PASS" if all(gates.values()) else "REJECT",
    })


def identity_view(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [rounded(dict(row)) for row in rows]
