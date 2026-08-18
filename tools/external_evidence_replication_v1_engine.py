#!/usr/bin/env python3
"""Frozen mechanics for External Evidence Edge Replication V1.

This module contains no source-opening side effects.  The runner verifies the
pre-outcome seal before calling either reader.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
DEVELOPMENT_START = "2021-08-01T00:00:00Z"
DEVELOPMENT_END = "2025-01-01T00:00:00Z"
GATE_START_DATE = "2022-01-01"
GATE_END_DATE = "2024-12-31"
BOOTSTRAP_SEED = 20260813
RANDOMIZATION_SEED = 20260814
BOOTSTRAP_DRAWS = 5_000
RANDOMIZATION_DRAWS = 20_000
ACCOUNT_USD = 10_000.0
PORTFOLIO_R_USD = 100.0
NOTIONAL_CAP_USD = 50_000.0
REQUIRED_OPEN_TIMES = ("09:59", "14:59", "15:29", "15:59")
FOLDS = (
    ("2022_H1", "2022-01-01", "2022-07-01"),
    ("2022_H2", "2022-07-01", "2023-01-01"),
    ("2023_H1", "2023-01-01", "2023-07-01"),
    ("2023_H2", "2023-07-01", "2024-01-01"),
    ("2024_H1", "2024-01-01", "2024-07-01"),
    ("2024_H2", "2024-07-01", "2025-01-01"),
)
CANDIDATE_ORDER = (
    "EER_C01_EQUITY_MIM_R1",
    "EER_C02_EQUITY_MIM_R1_R12",
    "EER_C03_WTI_MIM_R1",
)


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    cluster: str
    point: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float


SPECS: dict[str, SymbolSpec] = {
    "US500": SymbolSpec("US500", "US_EQUITY_INDICES", 0.01, 1.0, 0.1, 250.0, 0.1),
    "USTEC": SymbolSpec("USTEC", "US_EQUITY_INDICES", 0.01, 1.0, 0.1, 250.0, 0.1),
    "XTIUSD": SymbolSpec("XTIUSD", "ENERGY", 0.01, 100.0, 0.5, 50.0, 0.5),
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def rounded(value: Any, digits: int = 12) -> Any:
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return round(float(value), digits)
    if isinstance(value, dict):
        return {str(key): rounded(item, digits) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(item, digits) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    size = len(p_values)
    order = sorted(range(size), key=lambda index: (p_values[index], index))
    adjusted = [1.0] * size
    running = 0.0
    for rank, index in enumerate(order):
        candidate = min(1.0, (size - rank) * float(p_values[index]))
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def floor_step(value: float, step: float) -> float:
    if value <= 0.0:
        return 0.0
    return math.floor((value + 1e-12) / step) * step


def _source_identity(path: str, row_number: int) -> str:
    return hashlib.sha256(f"{path}:{row_number}".encode("utf-8")).hexdigest()


def _parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _required_local_clock(timestamp: datetime) -> str | None:
    local = timestamp.astimezone(NY)
    clock = local.strftime("%H:%M")
    return clock if clock in REQUIRED_OPEN_TIMES else None


def _anchor_payload(
    *, timestamp: datetime, close: float, spread_points: float, source_path: str, source_row: int
) -> dict[str, Any]:
    local = timestamp.astimezone(NY)
    return {
        "open_time_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "session_date": local.date().isoformat(),
        "clock": local.strftime("%H:%M"),
        "close": float(close),
        "spread_points": float(spread_points),
        "source_path": source_path,
        "source_row": int(source_row),
        "source_identity": _source_identity(source_path, source_row),
    }


def read_required_anchors_primary(root: Path, source_paths: Sequence[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """Pandas implementation; earliest lexicographic source/row wins."""

    frames: list[pd.DataFrame] = []
    for relative in sorted(source_paths):
        path = root / relative
        frame = pd.read_csv(path, usecols=["open_time", "close", "spread_points"])
        frame["source_path"] = relative
        frame["source_row"] = np.arange(1, len(frame) + 1, dtype=np.int64)
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)
    timestamps = pd.to_datetime(data["open_time"], utc=True, errors="raise")
    data["timestamp"] = timestamps
    data = data.sort_values(["source_path", "source_row"], kind="mergesort")
    data = data.drop_duplicates("timestamp", keep="first")
    local = data["timestamp"].dt.tz_convert("America/New_York")
    data["clock"] = local.dt.strftime("%H:%M")
    data = data[data["clock"].isin(REQUIRED_OPEN_TIMES)].copy()
    data["session_date"] = data["timestamp"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    output: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in data.itertuples(index=False):
        stamp = row.timestamp.to_pydatetime().astimezone(UTC)
        output[str(row.session_date)][str(row.clock)] = _anchor_payload(
            timestamp=stamp,
            close=float(row.close),
            spread_points=float(row.spread_points),
            source_path=str(row.source_path),
            source_row=int(row.source_row),
        )
    return {day: clocks for day, clocks in sorted(output.items())}


def read_required_anchors_reference(root: Path, source_paths: Sequence[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """Independent csv-module streaming implementation."""

    by_timestamp: dict[str, dict[str, Any]] = {}
    for relative in sorted(source_paths):
        path = root / relative
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row_number, row in enumerate(reader, start=1):
                timestamp = _parse_utc(str(row["open_time"]))
                clock = _required_local_clock(timestamp)
                if clock is None:
                    continue
                key = timestamp.isoformat()
                if key in by_timestamp:
                    continue
                by_timestamp[key] = _anchor_payload(
                    timestamp=timestamp,
                    close=float(row["close"]),
                    spread_points=float(row["spread_points"]),
                    source_path=relative,
                    source_row=row_number,
                )
    output: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for payload in sorted(by_timestamp.values(), key=lambda item: item["open_time_utc"]):
        output[payload["session_date"]][payload["clock"]] = payload
    return {day: clocks for day, clocks in sorted(output.items())}


def build_base_cases(symbol: str, anchors: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Create source-rule anchors and lagged volatility without future values."""

    p13_history: list[tuple[str, Mapping[str, Any]]] = []
    for day in sorted(anchors):
        clocks = anchors[day]
        if "15:59" in clocks:
            p13_history.append((day, clocks["15:59"]))
    previous_close: dict[str, Mapping[str, Any]] = {}
    for index in range(1, len(p13_history)):
        current_day = p13_history[index][0]
        previous_close[current_day] = p13_history[index - 1][1]

    prelim: list[dict[str, Any]] = []
    for day in sorted(anchors):
        clocks = anchors[day]
        if not all(clock in clocks for clock in REQUIRED_OPEN_TIMES) or day not in previous_close:
            continue
        p0 = previous_close[day]
        p1 = clocks["09:59"]
        p11 = clocks["14:59"]
        p12 = clocks["15:29"]
        p13 = clocks["15:59"]
        values = [float(item["close"]) for item in (p0, p1, p11, p12, p13)]
        if any(value <= 0.0 for value in values):
            continue
        r1 = values[1] / values[0] - 1.0
        r12 = values[3] / values[2] - 1.0
        last_half_return = values[4] / values[3] - 1.0
        prelim.append(
            {
                "base_case_id": hashlib.sha256(f"{symbol}|{day}".encode("utf-8")).hexdigest(),
                "symbol": symbol,
                "session_date": day,
                "p0": values[0],
                "p1": values[1],
                "p11": values[2],
                "p12": values[3],
                "p13": values[4],
                "r1": r1,
                "r12": r12,
                "last_half_return": last_half_return,
                "entry_spread_points": float(p12["spread_points"]),
                "exit_spread_points": float(p13["spread_points"]),
                "anchor_identities": [p0["source_identity"], p1["source_identity"], p11["source_identity"], p12["source_identity"], p13["source_identity"]],
            }
        )

    history: deque[float] = deque(maxlen=60)
    output: list[dict[str, Any]] = []
    for row in prelim:
        if len(history) >= 20:
            row = dict(row)
            row["exante_sigma"] = float(np.std(np.asarray(history, dtype=float), ddof=1))
            if row["exante_sigma"] > 0.0 and math.isfinite(row["exante_sigma"]):
                output.append(row)
        history.append(float(row["last_half_return"]))
    return output


def base_case_identity_view(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        rounded(
            {
                "base_case_id": row["base_case_id"],
                "symbol": row["symbol"],
                "session_date": row["session_date"],
                "p0": row["p0"],
                "p1": row["p1"],
                "p11": row["p11"],
                "p12": row["p12"],
                "p13": row["p13"],
                "r1": row["r1"],
                "r12": row["r12"],
                "last_half_return": row["last_half_return"],
                "entry_spread_points": row["entry_spread_points"],
                "exit_spread_points": row["exit_spread_points"],
                "exante_sigma": row["exante_sigma"],
                "anchor_identities": row["anchor_identities"],
            }
        )
        for row in rows
    ]


def candidate_direction(candidate_id: str, row: Mapping[str, Any]) -> int:
    r1 = float(row["r1"])
    if candidate_id == "EER_C02_EQUITY_MIM_R1_R12":
        r12 = float(row["r12"])
        if r1 > 0.0 and r12 > 0.0:
            return 1
        if r1 <= 0.0 and r12 <= 0.0:
            return -1
        return 0
    return 1 if r1 > 0.0 else -1


def _leg_economics(row: Mapping[str, Any], direction: int, risk_budget_usd: float) -> dict[str, Any] | None:
    spec = SPECS[str(row["symbol"])]
    entry = float(row["p12"])
    exit_price = float(row["p13"])
    sigma_price = entry * float(row["exante_sigma"])
    if sigma_price <= 0.0:
        return None
    by_risk = risk_budget_usd / (sigma_price * spec.contract_size)
    by_notional = NOTIONAL_CAP_USD / (entry * spec.contract_size)
    volume = floor_step(min(by_risk, by_notional, spec.volume_max), spec.volume_step)
    if volume + 1e-12 < spec.volume_min:
        return None
    planned_risk_usd = sigma_price * spec.contract_size * volume
    gross_usd = direction * (exit_price - entry) * spec.contract_size * volume
    spread_points = float(row["entry_spread_points"] if direction > 0 else row["exit_spread_points"])
    observed_spread_usd = spread_points * spec.point * spec.contract_size * volume
    base_cost_usd = max(observed_spread_usd + 0.03 * planned_risk_usd, 0.05 * planned_risk_usd)
    return rounded(
        {
            "base_case_id": row["base_case_id"],
            "symbol": row["symbol"],
            "session_date": row["session_date"],
            "direction": direction,
            "source_style_return": direction * float(row["last_half_return"]),
            "risk_budget_usd": risk_budget_usd,
            "planned_risk_usd": planned_risk_usd,
            "volume": volume,
            "gross_usd": gross_usd,
            "base_cost_usd": base_cost_usd,
            "net_usd": gross_usd - base_cost_usd,
            "stress_1p5_net_usd": gross_usd - 1.5 * base_cost_usd,
            "stress_2p0_net_usd": gross_usd - 2.0 * base_cost_usd,
        }
    )


def simulate_candidate(candidate_id: str, base_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    if candidate_id in ("EER_C01_EQUITY_MIM_R1", "EER_C02_EQUITY_MIM_R1_R12"):
        symbols = ("US500", "USTEC")
    elif candidate_id == "EER_C03_WTI_MIM_R1":
        symbols = ("XTIUSD",)
    else:
        raise KeyError(candidate_id)

    indexed: dict[str, dict[str, Mapping[str, Any]]] = {
        symbol: {str(row["session_date"]): row for row in base_by_symbol[symbol]} for symbol in symbols
    }
    dates = sorted(set().union(*(set(rows) for rows in indexed.values())))
    legs: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    for day in dates:
        decisions: list[tuple[Mapping[str, Any], int]] = []
        for symbol in symbols:
            row = indexed[symbol].get(day)
            if row is None:
                continue
            direction = candidate_direction(candidate_id, row)
            if direction:
                decisions.append((row, direction))
        if not decisions:
            continue
        risk_budget = PORTFOLIO_R_USD / len(decisions)
        day_legs: list[dict[str, Any]] = []
        for row, direction in decisions:
            item = _leg_economics(row, direction, risk_budget)
            if item is not None:
                item["candidate_id"] = candidate_id
                day_legs.append(item)
                legs.append(item)
        if not day_legs:
            continue
        daily.append(
            rounded(
                {
                    "candidate_id": candidate_id,
                    "session_date": day,
                    "symbols": sorted(item["symbol"] for item in day_legs),
                    "legs": len(day_legs),
                    "gross_r": sum(float(item["gross_usd"]) for item in day_legs) / PORTFOLIO_R_USD,
                    "cost_r": sum(float(item["base_cost_usd"]) for item in day_legs) / PORTFOLIO_R_USD,
                    "net_r": sum(float(item["net_usd"]) for item in day_legs) / PORTFOLIO_R_USD,
                    "stress_1p5_net_r": sum(float(item["stress_1p5_net_usd"]) for item in day_legs) / PORTFOLIO_R_USD,
                    "stress_2p0_net_r": sum(float(item["stress_2p0_net_usd"]) for item in day_legs) / PORTFOLIO_R_USD,
                    "source_style_return": float(np.mean([float(item["source_style_return"]) for item in day_legs])),
                }
            )
        )
    return {"candidate_id": candidate_id, "legs": legs, "daily": daily}


def _maximum_drawdown(values: Sequence[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        cumulative += float(value)
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return maximum


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0.0)
    losses = -sum(value for value in values if value < 0.0)
    if losses <= 0.0:
        return None
    return gains / losses


def _bootstrap_ci(values: np.ndarray) -> dict[str, Any]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    size = len(values)
    for index in range(BOOTSTRAP_DRAWS):
        means[index] = float(np.mean(values[rng.integers(0, size, size=size)]))
    return {
        "draws": BOOTSTRAP_DRAWS,
        "seed": BOOTSTRAP_SEED,
        "ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
        "p_mean_lte_zero": float(np.mean(means <= 0.0)),
    }


def _randomization_p(gross: np.ndarray, costs: np.ndarray) -> dict[str, Any]:
    rng = np.random.default_rng(RANDOMIZATION_SEED)
    observed = float(np.mean(gross - costs))
    greater_equal = 0
    for _ in range(RANDOMIZATION_DRAWS):
        signs = rng.choice(np.array([-1.0, 1.0]), size=len(gross), replace=True)
        null_mean = float(np.mean(signs * gross - costs))
        if null_mean >= observed:
            greater_equal += 1
    return {
        "draws": RANDOMIZATION_DRAWS,
        "seed": RANDOMIZATION_SEED,
        "one_sided_p": (greater_equal + 1.0) / (RANDOMIZATION_DRAWS + 1.0),
    }


def _period_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    net = [float(row["net_r"]) for row in rows]
    stress = [float(row["stress_1p5_net_r"]) for row in rows]
    return rounded(
        {
            "dates": len(rows),
            "net_r": sum(net),
            "expectancy_r": float(np.mean(net)) if net else None,
            "stress_1p5_expectancy_r": float(np.mean(stress)) if stress else None,
            "profit_factor": _profit_factor(net),
            "win_rate": float(np.mean(np.asarray(net) > 0.0)) if net else None,
        }
    )


def evaluate_candidate(simulation: Mapping[str, Any]) -> dict[str, Any]:
    candidate_id = str(simulation["candidate_id"])
    all_daily = sorted(simulation["daily"], key=lambda item: item["session_date"])
    gate_daily = [row for row in all_daily if GATE_START_DATE <= row["session_date"] <= GATE_END_DATE]
    gate_legs = [row for row in simulation["legs"] if GATE_START_DATE <= row["session_date"] <= GATE_END_DATE]
    if not gate_daily:
        raise ValueError(f"No gate rows for {candidate_id}")
    net = np.asarray([float(row["net_r"]) for row in gate_daily], dtype=float)
    gross = np.asarray([float(row["gross_r"]) for row in gate_daily], dtype=float)
    costs = np.asarray([float(row["cost_r"]) for row in gate_daily], dtype=float)
    stress = np.asarray([float(row["stress_1p5_net_r"]) for row in gate_daily], dtype=float)
    years = {
        str(year): _period_metrics([row for row in gate_daily if row["session_date"].startswith(str(year))])
        for year in (2022, 2023, 2024)
    }
    folds = {
        name: _period_metrics([row for row in gate_daily if start <= row["session_date"] < end])
        for name, start, end in FOLDS
    }
    instruments: dict[str, dict[str, Any]] = {}
    for symbol in sorted({str(row["symbol"]) for row in gate_legs}):
        subset = [row for row in gate_legs if row["symbol"] == symbol]
        instruments[symbol] = rounded(
            {
                "legs": len(subset),
                "net_r": sum(float(row["net_usd"]) for row in subset) / PORTFOLIO_R_USD,
                "positive_net_r": sum(max(0.0, float(row["net_usd"]) / PORTFOLIO_R_USD) for row in subset),
            }
        )
    positive_years = [float(item["net_r"]) for item in years.values() if float(item["net_r"]) > 0.0]
    positive_instruments = [float(item["net_r"]) for item in instruments.values() if float(item["net_r"]) > 0.0]
    maximum_year_share = max(positive_years) / sum(positive_years) if positive_years else None
    maximum_instrument_share = max(positive_instruments) / sum(positive_instruments) if positive_instruments else None
    bootstrap = _bootstrap_ci(net)
    randomization = _randomization_p(gross, costs)
    support_gate = (
        len(gate_daily) >= 300
        and all(int(item["dates"]) >= 80 for item in years.values())
        and all(int(item["dates"]) >= 40 for item in folds.values())
    )
    base_gates = {
        "support": support_gate,
        "net_expectancy_gt_zero": float(np.mean(net)) > 0.0,
        "profit_factor_gte_1p10": (_profit_factor(net) or 0.0) >= 1.10,
        "cluster_ci95_low_gt_zero": float(bootstrap["ci95"][0]) > 0.0,
        "stress_1p5_expectancy_gt_zero": float(np.mean(stress)) > 0.0,
        "positive_folds_gte_4": sum(float(item["net_r"]) > 0.0 for item in folds.values()) >= 4,
        "positive_years_gte_2": sum(float(item["net_r"]) > 0.0 for item in years.values()) >= 2,
        "maximum_drawdown_lte_15r": _maximum_drawdown(net.tolist()) <= 15.0,
        "year_concentration_lte_0p70": maximum_year_share is not None and maximum_year_share <= 0.70,
        "instrument_concentration_lte_0p70": candidate_id == "EER_C03_WTI_MIM_R1" or (maximum_instrument_share is not None and maximum_instrument_share <= 0.70),
    }
    months = 36.0
    return rounded(
        {
            "candidate_id": candidate_id,
            "population": {"all_replication_dates": len(all_daily), "gate_dates": len(gate_daily), "gate_legs": len(gate_legs)},
            "raw_source_style": {
                "mean_return": float(np.mean([float(row["source_style_return"]) for row in gate_daily])),
                "annualized_mean_return": float(np.mean([float(row["source_style_return"]) for row in gate_daily])) * 252.0,
            },
            "economics": {
                "win_rate": float(np.mean(net > 0.0)),
                "net_expectancy_r": float(np.mean(net)),
                "stress_1p5_expectancy_r": float(np.mean(stress)),
                "stress_2p0_expectancy_r": float(np.mean([float(row["stress_2p0_net_r"]) for row in gate_daily])),
                "profit_factor": _profit_factor(net),
                "net_r": float(np.sum(net)),
                "net_r_per_month": float(np.sum(net)) / months,
                "net_usd": float(np.sum(net)) * PORTFOLIO_R_USD,
                "usd_per_month": float(np.sum(net)) * PORTFOLIO_R_USD / months,
                "trades_per_month": len(gate_daily) / months,
                "legs_per_month": len(gate_legs) / months,
                "maximum_drawdown_r": _maximum_drawdown(net.tolist()),
                "distance_to_10r_per_month": 10.0 - float(np.sum(net)) / months,
            },
            "bootstrap": bootstrap,
            "randomization": randomization,
            "years": years,
            "folds": folds,
            "instruments": instruments,
            "maximum_positive_year_share": maximum_year_share,
            "maximum_positive_instrument_share": maximum_instrument_share,
            "base_gates": base_gates,
        }
    )


def apply_holm_and_verdict(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item["candidate_id"]): dict(item) for item in results}
    ordered = [by_id[candidate_id] for candidate_id in CANDIDATE_ORDER]
    adjusted = holm_adjust([float(item["randomization"]["one_sided_p"]) for item in ordered])
    output: list[dict[str, Any]] = []
    for item, holm_p in zip(ordered, adjusted):
        gates = dict(item["base_gates"])
        gates["holm_p_lte_0p05"] = holm_p <= 0.05
        item["holm_adjusted_p"] = holm_p
        item["gates"] = gates
        item["failed_gates"] = [name for name, passed in gates.items() if not passed]
        item["verdict"] = "PASS" if all(gates.values()) else "REJECT"
        output.append(rounded(item))
    return output


def select_portfolio(results: Sequence[Mapping[str, Any]]) -> list[str]:
    passed = {str(item["candidate_id"]) for item in results if item["verdict"] == "PASS"}
    selected: list[str] = []
    if "EER_C01_EQUITY_MIM_R1" in passed:
        selected.append("EER_C01_EQUITY_MIM_R1")
    elif "EER_C02_EQUITY_MIM_R1_R12" in passed:
        selected.append("EER_C02_EQUITY_MIM_R1_R12")
    if "EER_C03_WTI_MIM_R1" in passed:
        selected.append("EER_C03_WTI_MIM_R1")
    return selected


def portfolio_metrics(selected: Sequence[str], simulations: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    if not selected:
        return None
    by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate_id in selected:
        for row in simulations[candidate_id]["daily"]:
            if GATE_START_DATE <= row["session_date"] <= GATE_END_DATE:
                by_date[str(row["session_date"])].append(row)
    rows: list[dict[str, Any]] = []
    for day, items in sorted(by_date.items()):
        rows.append(
            rounded(
                {
                    "session_date": day,
                    "net_r": sum(float(item["net_r"]) for item in items),
                    "stress_1p5_net_r": sum(float(item["stress_1p5_net_r"]) for item in items),
                    "candidates": [item["candidate_id"] for item in items],
                }
            )
        )
    net = [float(row["net_r"]) for row in rows]
    return rounded(
        {
            "selected_candidates": list(selected),
            "trading_dates": len(rows),
            "net_r": sum(net),
            "net_r_per_month": sum(net) / 36.0,
            "usd_per_month": sum(net) * PORTFOLIO_R_USD / 36.0,
            "profit_factor": _profit_factor(net),
            "win_rate": float(np.mean(np.asarray(net) > 0.0)),
            "maximum_drawdown_r": _maximum_drawdown(net),
            "stress_1p5_expectancy_r": float(np.mean([float(row["stress_1p5_net_r"]) for row in rows])),
            "distance_to_10r_per_month": 10.0 - sum(net) / 36.0,
            "rows_checksum": canonical_hash(rows),
        }
    )

