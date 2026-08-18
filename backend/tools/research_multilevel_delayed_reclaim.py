from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from research_daily_session_playbooks import (
    FIVE_MINUTE_SQL,
    Bar,
    Day,
    Signal,
    Trade,
    _atr_by_close,
    _bootstrap_mean,
    _build_days,
    _directional_bar,
    _simulate,
)
from research_usd_retest_lead import USD_SQL, UsdPoint, _usd_direction

from gold_intel.infrastructure.database import session_factory

Side = Literal["LONG", "SHORT"]


@dataclass(frozen=True, slots=True)
class Level:
    side: Side
    price: float
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReclaimLead:
    signal: Signal
    session_name: str
    level_names: tuple[str, ...]
    signed_usd_direction: float | None


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
                    "load_start": start - timedelta(days=7),
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
    atr_by_close = _atr_by_close(bars)
    open_times = [bar.open_time for bar in bars]
    leads: list[ReclaimLead] = []
    funnel: dict[str, int] = defaultdict(int)
    for day in days:
        london_atr = atr_by_close.get(day.london[0].close_time)
        new_york_atr = atr_by_close.get(day.new_york[0].close_time)
        if london_atr is None or new_york_atr is None:
            funnel["ATR_UNKNOWN"] += 1
            continue
        rolling = _rolling_levels(
            bars,
            open_times,
            cutoff=day.asia[0].open_time,
        )
        asia_high = max(bar.high for bar in day.asia)
        asia_low = min(bar.low for bar in day.asia)
        london_levels = _cluster_levels(
            [
                Level("SHORT", asia_high, ("ASIA_HIGH",)),
                Level("LONG", asia_low, ("ASIA_LOW",)),
                *rolling,
            ],
            atr=london_atr,
            session_open=day.london[0].open,
        )
        london_signal = _delayed_reclaim(
            day,
            session_bars=day.london,
            session_name="LONDON",
            levels=london_levels,
            atr_by_close=atr_by_close,
        )
        london_high = max(bar.high for bar in day.london)
        london_low = min(bar.low for bar in day.london)
        new_york_levels = _cluster_levels(
            [
                Level("SHORT", london_high, ("LONDON_HIGH",)),
                Level("LONG", london_low, ("LONDON_LOW",)),
                Level("SHORT", asia_high, ("ASIA_HIGH",)),
                Level("LONG", asia_low, ("ASIA_LOW",)),
                *[level for level in rolling if "PRIOR_24H" in level.names[0]],
            ],
            atr=new_york_atr,
            session_open=day.new_york[0].open,
        )
        new_york_signal = _delayed_reclaim(
            day,
            session_bars=day.new_york,
            session_name="NEW_YORK",
            levels=new_york_levels,
            atr_by_close=atr_by_close,
        )
        usd = _usd_direction(
            usd_points,
            day.london[0].open_time - timedelta(minutes=5),
        )
        for session_name, result in (
            ("LONDON", london_signal),
            ("NEW_YORK", new_york_signal),
        ):
            if result is None:
                funnel[f"{session_name}_NO_TRIGGER"] += 1
                continue
            side_sign = 1 if result.side == "LONG" else -1
            signed_usd = side_sign * usd[0] if usd is not None else None
            leads.append(
                ReclaimLead(
                    signal=result,
                    session_name=session_name,
                    level_names=tuple(result.evidence["level_names"]),
                    signed_usd_direction=signed_usd,
                )
            )
            funnel[f"{session_name}_TRIGGERED"] += 1

    bars_by_open = {bar.open_time: bar for bar in bars}
    report: dict[str, Any] = {
        "contract": {
            "version": "MULTILEVEL_DELAYED_RECLAIM_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "signals": len(leads),
            "funnel": dict(sorted(funnel.items())),
            "same_bar_reclaims": "EXCLUDED",
            "base_target_r": 1.0,
            "base_max_holding_minutes": 240,
            "locked_validation": "calendar year 2025 (not loaded)",
        },
        "cohorts": {},
        "target_holding_neighbourhood": {},
        "cost_stress": {},
    }
    cohorts = {
        "PRICE_CONTROL": leads,
        "BROAD_USD_ALIGNED": [
            lead
            for lead in leads
            if (lead.signed_usd_direction or 0.0) > 0
        ],
        "LEVEL_CONFLUENCE_GE_2": [
            lead for lead in leads if len(lead.level_names) >= 2
        ],
        "USD_ALIGNED_AND_CONFLUENCE": [
            lead
            for lead in leads
            if (lead.signed_usd_direction or 0.0) > 0
            and len(lead.level_names) >= 2
        ],
    }
    for name, selected in cohorts.items():
        report["cohorts"][name] = _evaluate(
            selected,
            bars_by_open,
            target_r=1.0,
            holding_minutes=240,
            cost_multiplier=1.0,
        )
    primary = cohorts["BROAD_USD_ALIGNED"]
    for target_r in (0.75, 1.0, 1.25, 1.5):
        for holding_minutes in (180, 240, 300):
            key = f"{target_r:.2f}R_{holding_minutes}M"
            report["target_holding_neighbourhood"][key] = _evaluate(
                primary,
                bars_by_open,
                target_r=target_r,
                holding_minutes=holding_minutes,
                cost_multiplier=1.0,
                compact=True,
            )
    for multiplier in (1.0, 1.5, 2.0):
        report["cost_stress"][f"{multiplier:.2f}x"] = _evaluate(
            primary,
            bars_by_open,
            target_r=1.0,
            holding_minutes=240,
            cost_multiplier=multiplier,
            compact=True,
        )
    print(json.dumps(report, indent=2, sort_keys=True))


def _rolling_levels(
    bars: Sequence[Bar],
    open_times: Sequence[datetime],
    *,
    cutoff: datetime,
) -> list[Level]:
    end = bisect_left(open_times, cutoff)
    one_day = bisect_left(open_times, cutoff - timedelta(hours=24))
    five_days = bisect_left(open_times, cutoff - timedelta(days=5))
    prior_24h = bars[one_day:end]
    prior_5d = bars[five_days:end]
    output: list[Level] = []
    if len(prior_24h) >= 100:
        output.extend(
            (
                Level(
                    "SHORT",
                    max(bar.high for bar in prior_24h),
                    ("PRIOR_24H_HIGH",),
                ),
                Level(
                    "LONG",
                    min(bar.low for bar in prior_24h),
                    ("PRIOR_24H_LOW",),
                ),
            )
        )
    if len(prior_5d) >= 500:
        output.extend(
            (
                Level(
                    "SHORT",
                    max(bar.high for bar in prior_5d),
                    ("PRIOR_5D_HIGH",),
                ),
                Level(
                    "LONG",
                    min(bar.low for bar in prior_5d),
                    ("PRIOR_5D_LOW",),
                ),
            )
        )
    return output


def _cluster_levels(
    levels: Sequence[Level],
    *,
    atr: float,
    session_open: float,
) -> list[Level]:
    eligible = [
        level
        for level in levels
        if (
            level.price >= session_open - 0.25 * atr
            if level.side == "SHORT"
            else level.price <= session_open + 0.25 * atr
        )
    ]
    output: list[Level] = []
    for side in ("LONG", "SHORT"):
        members = sorted(
            (level for level in eligible if level.side == side),
            key=lambda level: level.price,
        )
        clusters: list[list[Level]] = []
        for level in members:
            if (
                not clusters
                or abs(level.price - clusters[-1][-1].price) > 0.25 * atr
            ):
                clusters.append([level])
            else:
                clusters[-1].append(level)
        for cluster in clusters:
            price = (
                min(level.price for level in cluster)
                if side == "LONG"
                else max(level.price for level in cluster)
            )
            output.append(
                Level(
                    side=side,
                    price=price,
                    names=tuple(
                        sorted(
                            {
                                name
                                for level in cluster
                                for name in level.names
                            }
                        )
                    ),
                )
            )
    return output


def _delayed_reclaim(
    day: Day,
    *,
    session_bars: Sequence[Bar],
    session_name: str,
    levels: Sequence[Level],
    atr_by_close: dict[datetime, float],
) -> Signal | None:
    candidates: list[tuple[datetime, int, Signal]] = []
    for sweep_index in range(0, len(session_bars) - 5):
        sweep = session_bars[sweep_index]
        atr = atr_by_close.get(sweep.close_time)
        if atr is None or atr <= 0:
            continue
        for level in levels:
            depth = (
                level.price - sweep.low
                if level.side == "LONG"
                else sweep.high - level.price
            )
            closed_outside = (
                sweep.close < level.price
                if level.side == "LONG"
                else sweep.close > level.price
            )
            if not closed_outside or not 0.02 * atr <= depth <= 0.75 * atr:
                continue
            reclaim_index = sweep_index + 1
            reclaim = session_bars[reclaim_index]
            reclaimed = (
                reclaim.close > level.price
                if level.side == "LONG"
                else reclaim.close < level.price
            )
            if not reclaimed:
                continue
            members = session_bars[sweep_index : reclaim_index + 1]
            extreme = (
                min(bar.low for bar in members)
                if level.side == "LONG"
                else max(bar.high for bar in members)
            )
            for signal_index in range(
                reclaim_index,
                min(len(session_bars) - 1, reclaim_index + 4),
            ):
                if signal_index < 3:
                    continue
                bar = session_bars[signal_index]
                micro = session_bars[signal_index - 3 : signal_index]
                breaks_structure = (
                    bar.close > max(item.high for item in micro)
                    if level.side == "LONG"
                    else bar.close < min(item.low for item in micro)
                )
                signal_atr = atr_by_close.get(bar.close_time)
                if (
                    signal_atr is not None
                    and breaks_structure
                    and _directional_bar(
                        bar,
                        side=level.side,
                        atr=signal_atr,
                        min_body_atr=0.25,
                        min_body_ratio=0.55,
                        min_close_location=0.65,
                    )
                ):
                    entry = session_bars[signal_index + 1]
                    stop = (
                        extreme - 0.10 * signal_atr
                        if level.side == "LONG"
                        else extreme + 0.10 * signal_atr
                    )
                    risk = abs(entry.open - stop)
                    if risk < 0.20 * signal_atr or risk > 8 * signal_atr:
                        break
                    signal = Signal(
                        playbook=f"P6_{session_name}_MULTILEVEL_DELAYED_RECLAIM",
                        session_date=day.session_date,
                        side=level.side,
                        signal_time=bar.close_time,
                        entry_time=entry.open_time,
                        entry_reference=entry.open,
                        stop=stop,
                        base_target_r=1.0,
                        max_holding_minutes=240,
                        atr=signal_atr,
                        evidence={
                            "level_price": level.price,
                            "level_names": list(level.names),
                            "sweep_time": sweep.open_time.isoformat(),
                            "reclaim_time": reclaim.close_time.isoformat(),
                            "reclaim_speed": "DELAYED_ONE_BAR",
                        },
                    )
                    candidates.append(
                        (
                            signal.signal_time,
                            -len(level.names),
                            signal,
                        )
                    )
                    break
    return (
        min(candidates, key=lambda item: (item[0], item[1]))[2]
        if candidates
        else None
    )


def _evaluate(
    leads: Sequence[ReclaimLead],
    bars: dict[datetime, Bar],
    *,
    target_r: float,
    holding_minutes: int,
    cost_multiplier: float,
    compact: bool = False,
) -> dict[str, Any]:
    paired: list[tuple[ReclaimLead, Trade]] = []
    for lead in leads:
        trade = _simulate(
            replace(
                lead.signal,
                max_holding_minutes=holding_minutes,
            ),
            bars,
            target_r=target_r,
            cost_multiplier=cost_multiplier,
        )
        if trade is not None:
            paired.append((lead, trade))
    metrics = _metrics(paired)
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
                "by_session",
            )
        }
    return metrics


def _metrics(
    paired: Sequence[tuple[ReclaimLead, Trade]],
) -> dict[str, Any]:
    if not paired:
        return {
            "trades": 0,
            "net_expectancy_r": None,
            "profit_factor": None,
        }
    values = [trade.net_r for _, trade in paired]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    by_year: dict[str, list[float]] = defaultdict(list)
    by_session: dict[str, list[float]] = defaultdict(list)
    by_level: dict[str, list[float]] = defaultdict(list)
    by_side: dict[str, list[float]] = defaultdict(list)
    for lead, trade in paired:
        by_year[str(trade.session_date.year)].append(trade.net_r)
        by_session[lead.session_name].append(trade.net_r)
        by_side[trade.side].append(trade.net_r)
        for level in lead.level_names:
            by_level[level].append(trade.net_r)
    interval = _bootstrap_mean(values)
    return {
        "trades": len(paired),
        "long_trades": len(by_side["LONG"]),
        "short_trades": len(by_side["SHORT"]),
        "win_rate_pct": round(len(winners) / len(paired) * 100, 3),
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
            statistics.mean(trade.cost_r for _, trade in paired),
            6,
        ),
        "by_year": {
            key: _group(value) for key, value in sorted(by_year.items())
        },
        "by_session": {
            key: _group(value) for key, value in sorted(by_session.items())
        },
        "by_side": {
            key: _group(value) for key, value in sorted(by_side.items())
        },
        "by_level": {
            key: _group(value)
            for key, value in sorted(
                by_level.items(),
                key=lambda item: len(item[1]),
                reverse=True,
            )
        },
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
