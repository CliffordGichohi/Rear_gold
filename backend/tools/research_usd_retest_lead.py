from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from research_daily_session_playbooks import (
    FIVE_MINUTE_SQL,
    Bar,
    Signal,
    Trade,
    _atr_by_close,
    _bootstrap_mean,
    _build_days,
    _signals_for_day,
    _simulate,
)
from sqlalchemy import text

from gold_intel.infrastructure.database import session_factory

USD_SQL = text(
    """
    SELECT
        observation_time,
        available_at,
        value,
        source_record_key
    FROM market.observations
    WHERE series_code = 'USD_BROAD_NOMINAL'
      AND is_synthetic = false
      AND available_at < :end
      AND observation_time < :end
    ORDER BY observation_time, available_at
    """
)


@dataclass(frozen=True, slots=True)
class UsdPoint:
    observation_time: datetime
    available_at: datetime
    value: float
    source_record_key: str


@dataclass(frozen=True, slots=True)
class LeadSignal:
    signal: Signal
    signed_usd_direction: float
    usd_change_pct: float


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded during discovery")

    async with session_factory() as session:
        bar_rows = (
            await session.execute(
                FIVE_MINUTE_SQL,
                {
                    "load_start": start - timedelta(days=6),
                    "load_end": end,
                },
            )
        ).mappings()
        bars = [
            Bar(
                open_time=row["open_time"],
                close_time=row["close_time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                spread=float(row["spread_price"]),
            )
            for row in bar_rows
        ]
        usd_rows = (await session.execute(USD_SQL, {"end": end})).mappings()
        usd_points = [
            UsdPoint(
                observation_time=row["observation_time"],
                available_at=row["available_at"],
                value=float(row["value"]),
                source_record_key=row["source_record_key"],
            )
            for row in usd_rows
        ]

    days = _build_days(bars, start=start, end=end)
    bars_by_open = {bar.open_time: bar for bar in bars}
    atr_by_close = _atr_by_close(bars)
    london_range_history: list[float] = []
    leads: list[LeadSignal] = []
    for day in days:
        signals = _signals_for_day(
            day,
            atr_by_close=atr_by_close,
            london_range_history=london_range_history,
        )
        retests = [
            signal
            for signal in signals
            if signal.playbook == "P2_LONDON_ACCEPTED_RETEST"
        ]
        freeze = day.london[0].open_time - timedelta(minutes=5)
        usd = _usd_direction(usd_points, freeze)
        if usd is not None:
            direction, change_pct = usd
            for signal in retests:
                side_sign = 1 if signal.side == "LONG" else -1
                leads.append(
                    LeadSignal(
                        signal=signal,
                        signed_usd_direction=side_sign * direction,
                        usd_change_pct=change_pct,
                    )
                )
        london_range_history.append(
            max(bar.high for bar in day.london)
            - min(bar.low for bar in day.london)
        )

    report = {
        "contract": {
            "version": "USD_ALIGNED_LONDON_RETEST_LEAD_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "p2_signals_with_usd": len(leads),
            "base_rule": (
                "P2 accepted London retest; five-observation broad-USD gold "
                "direction strictly aligned; 2.0R; 240-minute maximum hold."
            ),
            "locked_validation": "calendar year 2025 (not loaded)",
        },
        "cohorts": {},
        "target_holding_neighbourhood": {},
        "cost_stress": {},
    }
    for name, threshold in (
        ("USD_SIGN_ALIGNED", 0.0),
        ("USD_DIRECTION_GE_0_25", 0.25),
        ("USD_DIRECTION_GE_0_50", 0.50),
    ):
        selected = [
            lead for lead in leads if lead.signed_usd_direction > threshold
        ]
        report["cohorts"][name] = _evaluate(
            selected,
            bars_by_open,
            target_r=2.0,
            holding_minutes=240,
            cost_multiplier=1.0,
        )

    base = [lead for lead in leads if lead.signed_usd_direction > 0]
    for target_r in (1.0, 1.5, 2.0):
        for holding_minutes in (180, 240, 300):
            key = f"{target_r:.2f}R_{holding_minutes}M"
            report["target_holding_neighbourhood"][key] = _evaluate(
                base,
                bars_by_open,
                target_r=target_r,
                holding_minutes=holding_minutes,
                cost_multiplier=1.0,
                compact=True,
            )
    for multiplier in (1.0, 1.5, 2.0):
        report["cost_stress"][f"{multiplier:.2f}x"] = _evaluate(
            base,
            bars_by_open,
            target_r=2.0,
            holding_minutes=240,
            cost_multiplier=multiplier,
            compact=True,
        )
    print(json.dumps(report, indent=2, sort_keys=True))


def _usd_direction(
    points: Sequence[UsdPoint],
    as_of: datetime,
) -> tuple[float, float] | None:
    canonical: dict[datetime, UsdPoint] = {}
    for point in points:
        if point.observation_time <= as_of and point.available_at <= as_of:
            canonical[point.observation_time] = point
    eligible = [canonical[key] for key in sorted(canonical)]
    if len(eligible) < 6 or eligible[-6].value == 0:
        return None
    change = eligible[-1].value / eligible[-6].value - 1
    gold_direction = max(-1.0, min(1.0, -change / 0.01))
    return gold_direction, change


def _evaluate(
    leads: Sequence[LeadSignal],
    bars: dict[datetime, Bar],
    *,
    target_r: float,
    holding_minutes: int,
    cost_multiplier: float,
    compact: bool = False,
) -> dict[str, Any]:
    trades = [
        trade
        for lead in leads
        if (
            trade := _simulate(
                replace(
                    lead.signal,
                    max_holding_minutes=holding_minutes,
                ),
                bars,
                target_r=target_r,
                cost_multiplier=cost_multiplier,
            )
        )
        is not None
    ]
    metrics = _metrics(trades)
    if compact:
        return {
            key: metrics[key]
            for key in (
                "trades",
                "win_rate_pct",
                "net_expectancy_r",
                "profit_factor",
                "total_net_r",
                "by_year",
            )
        }
    return metrics


def _metrics(trades: Sequence[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "net_expectancy_r": None,
            "profit_factor": None,
        }
    values = [trade.net_r for trade in trades]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    by_year: dict[str, list[float]] = defaultdict(list)
    by_side: dict[str, list[float]] = defaultdict(list)
    by_month: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        by_year[str(trade.session_date.year)].append(trade.net_r)
        by_side[trade.side].append(trade.net_r)
        by_month[trade.session_date.strftime("%Y-%m")].append(trade.net_r)
    interval = _bootstrap_mean(values)
    return {
        "trades": len(trades),
        "long_trades": len(by_side["LONG"]),
        "short_trades": len(by_side["SHORT"]),
        "win_rate_pct": round(len(winners) / len(trades) * 100, 3),
        "net_expectancy_r": round(statistics.mean(values), 6),
        "profit_factor": (
            round(sum(winners) / abs(sum(losers)), 6)
            if winners and losers
            else None
        ),
        "total_net_r": round(sum(values), 6),
        "bootstrap_95ci": [
            round(interval[0], 6),
            round(interval[1], 6),
        ],
        "average_cost_r": round(
            statistics.mean(trade.cost_r for trade in trades),
            6,
        ),
        "average_mfe_r": round(
            statistics.mean(trade.mfe_r for trade in trades),
            6,
        ),
        "average_mae_r": round(
            statistics.mean(trade.mae_r for trade in trades),
            6,
        ),
        "by_year": {
            key: _group(value) for key, value in sorted(by_year.items())
        },
        "by_side": {
            key: _group(value) for key, value in sorted(by_side.items())
        },
        "months_with_trades": len(by_month),
        "positive_month_pct": round(
            sum(sum(value) > 0 for value in by_month.values())
            / len(by_month)
            * 100,
            3,
        ),
    }


def _group(values: Sequence[float]) -> dict[str, Any]:
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    return {
        "trades": len(values),
        "net_expectancy_r": round(statistics.mean(values), 6),
        "profit_factor": (
            round(sum(winners) / abs(sum(losers)), 6)
            if winners and losers
            else None
        ),
        "total_net_r": round(sum(values), 6),
    }


if __name__ == "__main__":
    asyncio.run(main())
