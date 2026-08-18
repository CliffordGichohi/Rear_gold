from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from explore_session_playbooks import _build_days
from research_cross_market_auction_micro_execution import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
    _five_minute_bars_from_minutes,
)
from research_fundamental_state_transitions import (
    FundamentalRecord,
    _fundamental_records,
)
from research_liquidity_level_state_machine import (
    _enrich_cross_market,
    _liquidity_signals,
)
from research_one_minute_auction_execution import (
    ONE_MINUTE_SQL,
    _simulate_minute,
)
from research_session_state_transitions import (
    Candidate,
    ManagedResult,
    _compact_metrics,
    _portfolio_report,
    _slice,
)

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory

SYMBOLS = ("ZT.v.0", "ZN.v.0", "ZQ.v.0", "SR3.v.0")
HORIZONS = (5, 15, 30, 60)
MANAGERS = {
    "FIXED_1_50R": 1.5,
    "FIXED_2_00R": 2.0,
    "FIXED_3_00R": 3.0,
    "FIXED_4_00R": 4.0,
}
Rule = Callable[["ExecutionContext"], bool]


@dataclass(frozen=True, slots=True)
class RateSnapshot:
    values: dict[str, float]

    def value(self, key: str) -> float:
        return self.values.get(key, math.nan)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    fundamental: FundamentalRecord
    rates: RateSnapshot

    @property
    def trade(self) -> Any:
        return self.fundamental.managed.trade


@dataclass(frozen=True, slots=True)
class Permission:
    name: str
    predicate: Rule


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rates-dir", type=Path, required=True)
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--cache-output", type=Path)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    started = time.perf_counter()
    query = {"load_start": start - timedelta(days=32), "load_end": end}
    async with session_factory() as session:
        minute_bars = _bars(
            (await session.execute(ONE_MINUTE_SQL, query)).mappings(),
        )
        five_minute_gold = _five_minute_bars_from_minutes(minute_bars)
        eurusd_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "EURUSD", **query},
                )
            ).mappings(),
        )
        silver_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "XAGUSD", **query},
                )
            ).mappings(),
        )
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)
    _phase("SOURCE_DATA_LOADED", started)

    days = _build_days(five_minute_gold, start=start, end=end)
    signals = _enrich_cross_market(
        _liquidity_signals(
            days,
            minute_bars=minute_bars,
            five_minute_gold=five_minute_gold,
        ),
        eurusd_bars=eurusd_bars,
        silver_bars=silver_bars,
    )
    managed = _managed_results(signals, minute_bars=minute_bars)
    fundamentals = _fundamental_records(
        managed,
        fundamental_inputs=fundamental_inputs,
    )
    _phase("EXECUTIONS_AND_FUNDAMENTALS_BUILT", started)

    panel, rates_contract = _rates_panel(
        args.rates_dir,
        load_start=query["load_start"],
        end=end,
        target_times=sorted(
            {item.managed.signal.signal_time for item in fundamentals},
        ),
    )
    contexts = _contexts(fundamentals, panel=panel)
    if args.cache_output is not None:
        _write_context_cache(contexts, args.cache_output)
    candidates, candidate_trades = _candidate_results(contexts)
    selected = _select(candidates, candidate_trades=candidate_trades)
    _phase("RATES_FEATURES_AND_CANDIDATES_BUILT", started)

    base_portfolio = _portfolio_report(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    stress_portfolio = _portfolio_report(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.5,
    )
    annual_gate = _annual_gate(
        selected,
        candidate_trades=candidate_trades,
    )
    target_gate = _target_gate(base_portfolio, stress_portfolio)
    ranked = sorted(
        candidates,
        key=lambda item: _rank(item, candidate_trades=candidate_trades),
        reverse=True,
    )
    report = {
        "contract": {
            "version": "RATES_POLICY_SESSION_EDGE_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "causal_direction": (
                "Completed CME bars are available one minute after interval start. "
                "Higher ZT/ZN/ZQ/SR3 prices represent lower yields or a more dovish "
                "policy path and are therefore gold-bullish. Roll-crossing returns "
                "are invalidated."
            ),
            "search_space": (
                "Six auction families, thirteen declared causal permissions, and four "
                "fixed-R exits; no opaque classifier."
            ),
            "selection": (
                "Discovery only: at least 30 trades, expectancy >=0.10R, PF >=1.20, "
                "positive expectancy at 1.50x costs, and bootstrap lower bound "
                ">=-0.05R. One permission/manager per auction family."
            ),
            "portfolio": (
                "One open position at a time and no new entry after -2R realized "
                "on the session date."
            ),
            "target": (
                "10R average per calendar month at 1% risk; this is a promotion "
                "hurdle, not an assumed return."
            ),
        },
        "source_counts": {
            "complete_sessions": len(days),
            "auction_signals": len(signals),
            "managed_executions": len(managed),
            "contexts": len(contexts),
            "candidate_hypotheses": len(candidates),
        },
        "rates_data": rates_contract,
        "rates_feature_coverage_pct": _feature_coverage(contexts),
        "selected_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in selected
        ],
        "portfolio": {
            "base_cost": base_portfolio,
            "cost_stress_1_50x": stress_portfolio,
            "positive_each_development_year": annual_gate,
            "ten_r_monthly_promotion_gate": target_gate,
        },
        "top_discovery_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in ranked[: args.top]
        ],
        "side_diagnostics": _side_diagnostics(
            selected,
            candidate_trades=candidate_trades,
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _managed_results(
    signals: Sequence[Any],
    *,
    minute_bars: Sequence[Any],
) -> list[ManagedResult]:
    bars_by_open = {bar.open_time: bar for bar in minute_bars}
    output: list[ManagedResult] = []
    for signal in signals:
        for cost_multiplier in (1.0, 1.5):
            for manager, target_r in MANAGERS.items():
                trade = _simulate_minute(
                    signal,
                    bars_by_open=bars_by_open,
                    target_r=target_r,
                    cost_multiplier=cost_multiplier,
                )
                if trade is not None:
                    output.append(
                        ManagedResult(
                            signal=signal,
                            manager=manager,
                            cost_multiplier=cost_multiplier,
                            trade=trade,
                        ),
                    )
    return output


def _rates_panel(
    directory: Path,
    *,
    load_start: datetime,
    end: datetime,
    target_times: Sequence[datetime],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    files = sorted(directory.rglob("*.csv.gz"))
    if not files:
        raise RuntimeError(f"No normalized rates CSV files found under {directory}")
    frames = [
        pd.read_csv(
            path,
            parse_dates=["open_time", "available_at"],
            usecols=[
                "open_time",
                "available_at",
                "symbol",
                "instrument_id",
                "close",
                "volume",
            ],
        )
        for path in files
    ]
    raw = pd.concat(frames, ignore_index=True)
    raw["available_at"] = pd.to_datetime(raw["available_at"], utc=True)
    raw = raw[
        (raw["available_at"] >= pd.Timestamp(load_start))
        & (raw["available_at"] < pd.Timestamp(end))
    ].sort_values(["symbol", "available_at"])
    if raw.empty:
        raise RuntimeError("Normalized rates history does not overlap the research range")
    if (raw["available_at"] >= pd.Timestamp("2025-01-01T00:00:00Z")).any():
        raise RuntimeError("Locked 2025 rates data was loaded")

    minute_index = pd.date_range(
        start=pd.Timestamp(load_start).floor("min"),
        end=pd.Timestamp(end).floor("min"),
        freq="1min",
        inclusive="left",
        tz="UTC",
    )
    target_index = pd.DatetimeIndex(
        sorted({pd.Timestamp(value).floor("min") for value in target_times}),
    )
    panel = pd.DataFrame(index=target_index)
    coverage: dict[str, Any] = {}
    for symbol in SYMBOLS:
        source = raw[raw["symbol"] == symbol].copy()
        if source.empty:
            raise RuntimeError(f"Missing rates history for {symbol}")
        if source["available_at"].duplicated().any():
            raise RuntimeError(f"Duplicate available_at values for {symbol}")
        source = source.set_index("available_at").reindex(minute_index)
        observed_at = pd.Series(
            source.index.where(source["close"].notna()),
            index=minute_index,
        ).ffill()
        stale_minutes = (
            pd.Series(minute_index, index=minute_index) - observed_at
        ).dt.total_seconds() / 60
        maximum_staleness = 10 if symbol in {"ZT.v.0", "ZN.v.0"} else 60
        close = source["close"].ffill()
        instrument = source["instrument_id"].ffill()
        close = close.where(stale_minutes <= maximum_staleness)
        instrument = instrument.where(stale_minutes <= maximum_staleness)
        panel[f"{symbol}|stale"] = stale_minutes.reindex(target_index)
        panel[f"{symbol}|volume"] = source["volume"].fillna(0.0).reindex(target_index)

        for horizon in HORIZONS:
            raw_return = np.log(close / close.shift(horizon))
            same_contract = instrument == instrument.shift(horizon)
            raw_return = raw_return.where(same_contract)
            volatility = raw_return.rolling(28 * 24 * 60, min_periods=5_000).std().shift(1)
            z_score = (raw_return / volatility).replace(
                [np.inf, -np.inf],
                np.nan,
            )
            panel[f"{symbol}|z{horizon}"] = z_score.clip(-6.0, 6.0).reindex(
                target_index,
            )
        coverage[symbol] = {
            "rows": int(raw[raw["symbol"] == symbol].shape[0]),
            "first_available": raw.loc[
                raw["symbol"] == symbol,
                "available_at",
            ]
            .min()
            .isoformat(),
            "last_available": raw.loc[
                raw["symbol"] == symbol,
                "available_at",
            ]
            .max()
            .isoformat(),
            "instrument_ids": int(
                raw.loc[raw["symbol"] == symbol, "instrument_id"].nunique(),
            ),
        }

    return panel, {
        "files": [str(path) for path in files],
        "raw_rows": int(len(raw)),
        "symbols": coverage,
        "normalization": (
            "Each horizon return is divided by its own trailing 28-calendar-day "
            "standard deviation using only prior observations."
        ),
        "sparse_bar_policy": (
            "Last observed price is carried for at most 10 minutes for Treasury "
            "futures and 60 minutes for policy futures; staler values are UNKNOWN."
        ),
    }


def _contexts(
    fundamentals: Sequence[FundamentalRecord],
    *,
    panel: pd.DataFrame,
) -> list[ExecutionContext]:
    snapshot_by_key: dict[tuple[datetime, str], RateSnapshot] = {}
    output: list[ExecutionContext] = []
    for fundamental in fundamentals:
        signal = fundamental.managed.signal
        key = (signal.signal_time, signal.side)
        snapshot = snapshot_by_key.get(key)
        if snapshot is None:
            timestamp = pd.Timestamp(signal.signal_time).floor("min")
            if timestamp not in panel.index:
                continue
            row = panel.loc[timestamp]
            side_sign = 1.0 if signal.side == "LONG" else -1.0
            values: dict[str, float] = {}
            for horizon in HORIZONS:
                signed = {
                    symbol: side_sign * float(row[f"{symbol}|z{horizon}"])
                    for symbol in SYMBOLS
                    if pd.notna(row[f"{symbol}|z{horizon}"])
                }
                for symbol, value in signed.items():
                    values[f"{symbol}|aligned_{horizon}"] = value
                values[f"coverage_{horizon}"] = float(len(signed))
                values[f"agreement_{horizon}"] = float(
                    sum(value > 0 for value in signed.values()),
                )
                values[f"composite_{horizon}"] = _median_or_nan(signed.values())
                values[f"treasury_{horizon}"] = _median_or_nan(
                    signed[symbol] for symbol in ("ZT.v.0", "ZN.v.0") if symbol in signed
                )
                values[f"policy_{horizon}"] = _median_or_nan(
                    signed[symbol] for symbol in ("ZQ.v.0", "SR3.v.0") if symbol in signed
                )
            snapshot = RateSnapshot(values)
            snapshot_by_key[key] = snapshot
        output.append(ExecutionContext(fundamental=fundamental, rates=snapshot))
    return output


def _permissions() -> tuple[Permission, ...]:
    return (
        Permission("BASE", lambda item: True),
        Permission(
            "RATES_15_AGREE_3",
            lambda item: _rate_gate(item, 15, minimum=0.0, agreement=3),
        ),
        Permission(
            "RATES_15_STRONG",
            lambda item: _rate_gate(item, 15, minimum=0.50, agreement=3),
        ),
        Permission(
            "TREASURY_15_BOTH",
            lambda item: _treasury_both(item, 15, minimum=0.0),
        ),
        Permission(
            "TREASURY_15_STRONG",
            lambda item: _treasury_both(item, 15, minimum=0.50),
        ),
        Permission(
            "TREASURY_15_60_PERSISTENT",
            lambda item: (
                _treasury_both(item, 15, minimum=0.0) and _treasury_both(item, 60, minimum=0.0)
            ),
        ),
        Permission(
            "TREASURY_15_POLICY_NOT_OPPOSED",
            lambda item: (
                _treasury_both(item, 15, minimum=0.0) and item.rates.value("policy_15") >= -0.25
            ),
        ),
        Permission(
            "MACRO_AND_TREASURY_15",
            lambda item: (
                item.fundamental.signed_score >= -5 and _treasury_both(item, 15, minimum=0.0)
            ),
        ),
        Permission(
            "RATES_60_CONFIRM",
            lambda item: _rate_gate(item, 60, minimum=0.25, agreement=3),
        ),
        Permission(
            "RATES_MULTI_HORIZON",
            lambda item: (
                _rate_gate(item, 5, minimum=0.0, agreement=2)
                and _rate_gate(item, 15, minimum=0.25, agreement=3)
                and _rate_gate(item, 60, minimum=0.0, agreement=2)
            ),
        ),
        Permission(
            "POLICY_AND_TREASURY_15",
            lambda item: (
                item.rates.value("coverage_15") >= 4
                and item.rates.value("policy_15") > 0
                and item.rates.value("treasury_15") > 0
            ),
        ),
        Permission(
            "MACRO_AND_RATES_15",
            lambda item: (
                item.fundamental.signed_score >= 0
                and _rate_gate(item, 15, minimum=0.0, agreement=3)
            ),
        ),
        Permission(
            "POST_EVENT_RATES_15",
            lambda item: (
                item.fundamental.event_age_hours is not None
                and 0 <= item.fundamental.event_age_hours <= 2
                and _rate_gate(item, 15, minimum=0.50, agreement=3)
            ),
        ),
    )


def _rate_gate(
    item: ExecutionContext,
    horizon: int,
    *,
    minimum: float,
    agreement: int,
) -> bool:
    return bool(
        item.rates.value(f"coverage_{horizon}") >= 3
        and item.rates.value(f"agreement_{horizon}") >= agreement
        and item.rates.value(f"composite_{horizon}") >= minimum
    )


def _treasury_both(
    item: ExecutionContext,
    horizon: int,
    *,
    minimum: float,
) -> bool:
    zt = item.rates.value(f"ZT.v.0|aligned_{horizon}")
    zn = item.rates.value(f"ZN.v.0|aligned_{horizon}")
    return bool(
        math.isfinite(zt)
        and math.isfinite(zn)
        and zt > 0
        and zn > 0
        and item.rates.value(f"treasury_{horizon}") >= minimum
    )


def _candidate_results(
    contexts: Sequence[ExecutionContext],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Any]]]:
    permissions = _permissions()
    families = sorted(
        {
            family
            for item in contexts
            if (family := _family(item.fundamental.managed.signal.playbook))
        },
    )
    candidates = [
        Candidate(family, permission.name, manager)
        for family in families
        for permission in permissions
        for manager in MANAGERS
    ]
    permission_by_name = {item.name: item for item in permissions}
    output: dict[tuple[str, float], list[Any]] = {}
    for candidate in candidates:
        permission = permission_by_name[candidate.rule]
        for cost_multiplier in (1.0, 1.5):
            output[(candidate.key, cost_multiplier)] = [
                item.trade
                for item in contexts
                if _family(item.fundamental.managed.signal.playbook) == candidate.archetype
                and item.fundamental.managed.manager == candidate.manager
                and item.fundamental.managed.cost_multiplier == cost_multiplier
                and permission.predicate(item)
            ]
    return candidates, output


def _family(playbook: str) -> str | None:
    session = "LONDON" if playbook.startswith("LONDON|") else "NEW_YORK"
    if "ACCEPTED_RETEST" in playbook:
        return f"{session}_ACCEPTED_RETEST"
    if "FAST_REJECTION" in playbook:
        return f"{session}_FAST_REJECTION"
    if "HANDOVER_CONFIRMATION" in playbook:
        return "NEW_YORK_HANDOVER_CONFIRMATION"
    if "HANDOVER_REJECTION" in playbook:
        return "NEW_YORK_HANDOVER_REJECTION"
    return None


def _select(
    candidates: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> list[Candidate]:
    eligible = [
        candidate
        for candidate in candidates
        if _selectable(candidate, candidate_trades=candidate_trades)
    ]
    by_family: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in eligible:
        by_family[candidate.archetype].append(candidate)
    selected = [
        max(
            members,
            key=lambda item: _rank(item, candidate_trades=candidate_trades),
        )
        for members in by_family.values()
    ]
    return sorted(
        selected,
        key=lambda item: _rank(item, candidate_trades=candidate_trades),
        reverse=True,
    )


def _selectable(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> bool:
    base = _slice(candidate_trades[(candidate.key, 1.0)], "discovery")
    stressed = _slice(candidate_trades[(candidate.key, 1.5)], "discovery")
    if len(base) < 30 or len(stressed) != len(base):
        return False
    metrics = _compact_metrics(
        base,
        calendar_start=date(2021, 8, 1),
        calendar_end=date(2023, 1, 1),
    )
    stress = _compact_metrics(
        stressed,
        calendar_start=date(2021, 8, 1),
        calendar_end=date(2023, 1, 1),
    )
    interval = metrics.get("bootstrap_95ci")
    return bool(
        metrics["net_expectancy_r"] is not None
        and float(metrics["net_expectancy_r"]) >= 0.10
        and metrics["profit_factor"] is not None
        and float(metrics["profit_factor"]) >= 1.20
        and stress["net_expectancy_r"] is not None
        and float(stress["net_expectancy_r"]) > 0
        and isinstance(interval, list)
        and float(interval[0]) >= -0.05
    )


def _rank(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> tuple[float, float, int]:
    trades = _slice(candidate_trades[(candidate.key, 1.0)], "discovery")
    if not trades:
        return (-999.0, -999.0, 0)
    expectancy = statistics.mean(item.net_r for item in trades)
    winners = sum(max(item.net_r, 0.0) for item in trades)
    losers = abs(sum(min(item.net_r, 0.0) for item in trades))
    return (expectancy, winners / losers if losers else 999.0, len(trades))


def _candidate_report(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> dict[str, Any]:
    base = candidate_trades[(candidate.key, 1.0)]
    stressed = candidate_trades[(candidate.key, 1.5)]
    return {
        "key": candidate.key,
        "selectable_on_discovery": _selectable(
            candidate,
            candidate_trades=candidate_trades,
        ),
        "discovery": _compact_metrics(
            _slice(base, "discovery"),
            calendar_start=date(2021, 8, 1),
            calendar_end=date(2023, 1, 1),
        ),
        "discovery_1_50x_cost": _compact_metrics(
            _slice(stressed, "discovery"),
            calendar_start=date(2021, 8, 1),
            calendar_end=date(2023, 1, 1),
        ),
        "validation_2023": _compact_metrics(
            _slice(base, "validation"),
            calendar_start=date(2023, 1, 1),
            calendar_end=date(2024, 1, 1),
        ),
        "forward_2024": _compact_metrics(
            _slice(base, "forward"),
            calendar_start=date(2024, 1, 1),
            calendar_end=date(2025, 1, 1),
        ),
    }


def _accepted_portfolio_trades(
    selected: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
    cost_multiplier: float,
) -> list[Any]:
    priority = {item.key: index for index, item in enumerate(selected)}
    members = [
        (trade, candidate)
        for candidate in selected
        for trade in candidate_trades[(candidate.key, cost_multiplier)]
    ]
    members.sort(key=lambda item: (item[0].entry_time, priority[item[1].key]))
    accepted: list[Any] = []
    open_until: datetime | None = None
    realized_by_day: dict[date, float] = defaultdict(float)
    for trade, _ in members:
        if open_until is not None and trade.entry_time < open_until:
            continue
        if realized_by_day[trade.session_date] <= -2.0:
            continue
        accepted.append(trade)
        open_until = trade.exit_time
        realized_by_day[trade.session_date] += trade.net_r
    return accepted


def _annual_gate(
    selected: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> dict[str, Any]:
    trades = _accepted_portfolio_trades(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    years: dict[str, dict[str, Any]] = {}
    for year in (2022, 2023, 2024):
        members = [item for item in trades if item.session_date.year == year]
        years[str(year)] = {
            "trades": len(members),
            "total_net_r": round(sum(item.net_r for item in members), 6),
            "expectancy_r": (
                round(statistics.mean(item.net_r for item in members), 6) if members else None
            ),
        }
    return {
        "passed": all(
            item["trades"] >= 15
            and item["expectancy_r"] is not None
            and float(item["expectancy_r"]) > 0
            for item in years.values()
        ),
        "years": years,
    }


def _target_gate(
    base: dict[str, Any],
    stress: dict[str, Any],
) -> dict[str, Any]:
    periods = ("discovery", "validation_2023", "forward_2024")
    checks = {
        period: (
            base[period].get("average_monthly_r") is not None
            and float(base[period]["average_monthly_r"]) >= 10
        )
        for period in periods
    }
    stress_positive = all(
        stress[period].get("net_expectancy_r") is not None
        and float(stress[period]["net_expectancy_r"]) > 0
        for period in periods
    )
    return {
        "passed": bool(checks and all(checks.values()) and stress_positive),
        "period_10r_checks": checks,
        "positive_expectancy_at_1_50x_costs": stress_positive,
    }


def _side_diagnostics(
    selected: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> dict[str, Any]:
    trades = _accepted_portfolio_trades(
        selected,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    output: dict[str, Any] = {}
    for side in ("LONG", "SHORT"):
        members = [trade for trade in trades if trade.side == side]
        output[side] = {
            "trades": len(members),
            "total_net_r": round(sum(trade.net_r for trade in members), 6),
            "expectancy_r": (
                round(statistics.mean(trade.net_r for trade in members), 6) if members else None
            ),
        }
    return output


def _feature_coverage(contexts: Sequence[ExecutionContext]) -> dict[str, float]:
    if not contexts:
        return {}
    keys = [
        f"{name}_{horizon}" for horizon in HORIZONS for name in ("composite", "treasury", "policy")
    ]
    return {
        key: round(
            sum(math.isfinite(item.rates.value(key)) for item in contexts) / len(contexts) * 100,
            4,
        )
        for key in keys
    }


def _write_context_cache(
    contexts: Sequence[ExecutionContext],
    destination: Path,
) -> None:
    rows: list[dict[str, Any]] = []
    for item in contexts:
        fundamental = item.fundamental
        managed = fundamental.managed
        trade = managed.trade
        evidence = managed.signal.evidence
        rows.append(
            {
                "playbook": trade.playbook,
                "family": _family(trade.playbook),
                "session_date": trade.session_date.isoformat(),
                "side": trade.side,
                "signal_time": trade.signal_time.isoformat(),
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat(),
                "manager": managed.manager,
                "cost_multiplier": managed.cost_multiplier,
                "gross_r": trade.gross_r,
                "net_r": trade.net_r,
                "cost_r": trade.cost_r,
                "mfe_r": trade.mfe_r,
                "mae_r": trade.mae_r,
                "holding_minutes": trade.holding_minutes,
                "signed_fundamental_score": fundamental.signed_score,
                "fundamental_confidence": fundamental.confidence,
                "fundamental_coverage": fundamental.coverage,
                "regime": fundamental.regime,
                "reaction_function": fundamental.reaction_function,
                "event_risk": fundamental.event_risk,
                "minutes_to_catalyst": fundamental.minutes_to_catalyst,
                "event_age_hours": fundamental.event_age_hours,
                "session": evidence.get("session"),
                "level_type": evidence.get("level_type"),
                "asia_range_percentile": evidence.get(
                    "asia_range_percentile",
                ),
                "risk_atr": evidence.get("risk_atr"),
                "event_id": evidence.get("event_id"),
                "event_code": evidence.get("event_code"),
                "event_importance": evidence.get("event_importance"),
                "rates_strength": evidence.get("rates_strength"),
                "signed_gold_move_atr": evidence.get(
                    "signed_gold_move_atr",
                ),
                "surprise_aligned": evidence.get("surprise_aligned"),
                **item.rates.values,
            },
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    pd.DataFrame(rows).to_csv(
        temporary,
        index=False,
        compression="gzip",
    )
    temporary.replace(destination)


def _median_or_nan(values: Any) -> float:
    materialized = list(values)
    return float(statistics.median(materialized)) if materialized else math.nan


def _phase(name: str, started: float) -> None:
    print(
        f"{name} elapsed={time.perf_counter() - started:.3f}s",
        flush=True,
        file=__import__("sys").stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
