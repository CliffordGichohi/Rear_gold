from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from research_daily_session_playbooks import (
    Bar,
    Signal,
    Trade,
    _atr_by_close,
    _bootstrap_mean,
    _build_days,
    _signals_for_day,
    _simulate,
)
from research_usd_retest_lead import USD_SQL, UsdPoint, _usd_direction
from sqlalchemy import text

from gold_intel.infrastructure.database import session_factory

FIVE_MINUTE_INSTRUMENT_SQL = text(
    """
    WITH canonical AS (
        SELECT DISTINCT ON (open_time)
            open_time,
            close_time,
            open,
            high,
            low,
            close,
            volume,
            spread_price,
            available_at
        FROM market.price_bars
        WHERE instrument_code = :instrument
          AND timeframe = '1m'
          AND provider_code = 'IC_MARKETS_MT5'
          AND is_synthetic = false
          AND open_time >= :load_start
          AND open_time < :load_end
        ORDER BY open_time, available_at
    ),
    bucketed AS (
        SELECT
            time_bucket(INTERVAL '5 minutes', open_time) AS open_time,
            first(open, open_time) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, open_time) AS close,
            sum(volume) AS volume,
            avg(spread_price) AS spread_price,
            count(*) AS members,
            max(close_time) AS close_time
        FROM canonical
        GROUP BY 1
    )
    SELECT
        open_time,
        close_time,
        open,
        high,
        low,
        close,
        volume,
        spread_price
    FROM bucketed
    WHERE members = 5
      AND close_time = open_time + INTERVAL '5 minutes'
    ORDER BY open_time
    """
)

Predicate = Callable[["ConfirmationRecord"], bool]


@dataclass(frozen=True, slots=True)
class ConfirmationRecord:
    signal: Signal
    trade: Trade
    eurusd_15m_signed_atr: float
    eurusd_60m_signed_atr: float
    daily_usd_signed_direction: float | None
    expected_entry_cost_r: float


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    predicate: Predicate


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded during discovery")

    async with session_factory() as session:
        load_start = start - timedelta(days=6)
        load_end = end
        gold_rows = (
            await session.execute(
                FIVE_MINUTE_INSTRUMENT_SQL,
                {
                    "instrument": "XAUUSD",
                    "load_start": load_start,
                    "load_end": load_end,
                },
            )
        ).mappings()
        gold_bars = _bars(gold_rows)
        eurusd_rows = (
            await session.execute(
                FIVE_MINUTE_INSTRUMENT_SQL,
                {
                    "instrument": "EURUSD",
                    "load_start": load_start,
                    "load_end": load_end,
                },
            )
        ).mappings()
        eurusd_bars = _bars(eurusd_rows)
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

    days = _build_days(gold_bars, start=start, end=end)
    records = _records(
        days,
        gold_bars=gold_bars,
        eurusd_bars=eurusd_bars,
        usd_points=usd_points,
    )
    scopes = {
        "ALL_PLAYBOOKS": records,
        **{
            playbook: [
                record
                for record in records
                if record.signal.playbook == playbook
            ]
            for playbook in sorted(
                {record.signal.playbook for record in records}
            )
        },
    }
    report: dict[str, Any] = {
        "contract": {
            "version": "INTRADAY_USD_CONFIRMATION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_gold_sessions": len(days),
            "eurusd_5m_bars": len(eurusd_bars),
            "complete_matched_trades": len(records),
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_validation": "calendar year 2025 (not loaded)",
            "proxy_semantics": (
                "Observed IC Markets EURUSD; rising EURUSD is inferred weak-USD "
                "confirmation for long gold. It is not licensed DXY."
            ),
        },
        "scopes": {},
    }
    for scope_name, members in scopes.items():
        results = [
            _rule_result(rule, members) for rule in _rules()
        ]
        results.sort(
            key=lambda item: (
                item["eligible_for_ranking"],
                item["weakest_slice_expectancy_r"]
                if item["weakest_slice_expectancy_r"] is not None
                else -999.0,
                min(
                    item["discovery_2021_2022"]["trades"],
                    item["validation_2023"]["trades"],
                    item["forward_2024"]["trades"],
                ),
            ),
            reverse=True,
        )
        report["scopes"][scope_name] = {
            "records": len(members),
            "positive_all_three_count": sum(
                result["positive_all_three"] for result in results
            ),
            "top_rules": results[: args.top],
        }
    print(json.dumps(report, indent=2, sort_keys=True))


def _bars(rows: Any) -> list[Bar]:
    return [
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
        for row in rows
    ]


def _records(
    days: Sequence[Any],
    *,
    gold_bars: Sequence[Bar],
    eurusd_bars: Sequence[Bar],
    usd_points: Sequence[UsdPoint],
) -> list[ConfirmationRecord]:
    gold_atr = _atr_by_close(gold_bars)
    eurusd_atr = _atr_by_close(eurusd_bars)
    gold_by_open = {bar.open_time: bar for bar in gold_bars}
    eurusd_close_times = [bar.close_time for bar in eurusd_bars]
    london_range_history: list[float] = []
    output: list[ConfirmationRecord] = []
    for day in days:
        signals = _signals_for_day(
            day,
            atr_by_close=gold_atr,
            london_range_history=london_range_history,
        )
        trapped_fades = [
            fade
            for signal in signals
            if (
                fade := _trapped_breakout_fade(
                    signal,
                    gold_by_open,
                )
            )
            is not None
        ]
        signals.extend(trapped_fades)
        daily_usd = _usd_direction(
            usd_points,
            day.london[0].open_time - timedelta(minutes=5),
        )
        for signal in signals:
            trade = _simulate(
                signal,
                gold_by_open,
                target_r=signal.base_target_r,
                cost_multiplier=1.0,
            )
            if trade is None:
                continue
            index = bisect_right(
                eurusd_close_times,
                signal.signal_time,
            ) - 1
            if (
                index < 12
                or eurusd_bars[index].close_time != signal.signal_time
            ):
                continue
            atr = eurusd_atr.get(signal.signal_time)
            if atr is None or atr <= 0:
                continue
            side_sign = 1 if signal.side == "LONG" else -1
            momentum_15 = (
                side_sign
                * (
                    eurusd_bars[index].close
                    - eurusd_bars[index - 3].close
                )
                / atr
            )
            momentum_60 = (
                side_sign
                * (
                    eurusd_bars[index].close
                    - eurusd_bars[index - 12].close
                )
                / atr
            )
            entry_bar = gold_by_open[signal.entry_time]
            risk = abs(signal.entry_reference - signal.stop)
            expected_cost = (entry_bar.spread + 0.10 + 0.07) / risk
            output.append(
                ConfirmationRecord(
                    signal=signal,
                    trade=trade,
                    eurusd_15m_signed_atr=momentum_15,
                    eurusd_60m_signed_atr=momentum_60,
                    daily_usd_signed_direction=(
                        side_sign * daily_usd[0]
                        if daily_usd is not None
                        else None
                    ),
                    expected_entry_cost_r=expected_cost,
                )
            )
        london_range_history.append(
            max(bar.high for bar in day.london)
            - min(bar.low for bar in day.london)
        )
    return output


def _trapped_breakout_fade(
    signal: Signal,
    bars_by_open: dict[datetime, Bar],
) -> Signal | None:
    if signal.playbook != "P1_LONDON_ACCEPTANCE_CONTINUATION":
        return None
    first = bars_by_open.get(signal.signal_time - timedelta(minutes=10))
    second = bars_by_open.get(signal.signal_time - timedelta(minutes=5))
    entry = bars_by_open.get(signal.entry_time)
    if first is None or second is None or entry is None:
        return None
    fade_side = "SHORT" if signal.side == "LONG" else "LONG"
    stop = (
        max(first.high, second.high) + 0.10 * signal.atr
        if fade_side == "SHORT"
        else min(first.low, second.low) - 0.10 * signal.atr
    )
    risk = abs(entry.open - stop)
    if risk < 0.20 * signal.atr or risk > 8 * signal.atr:
        return None
    return Signal(
        playbook="P8_CROSS_MARKET_TRAPPED_BREAKOUT_FADE",
        session_date=signal.session_date,
        side=fade_side,
        signal_time=signal.signal_time,
        entry_time=signal.entry_time,
        entry_reference=entry.open,
        stop=stop,
        base_target_r=1.0,
        max_holding_minutes=180,
        atr=signal.atr,
        evidence={
            "source_playbook": signal.playbook,
            "source_breakout_side": signal.side,
            "asia_boundary": signal.evidence["asia_boundary"],
            "classification": (
                "Potential trapped breakout inferred from cross-market "
                "contradiction; not observed institutional intent."
            ),
        },
    )


def _rules() -> tuple[Rule, ...]:
    return (
        Rule("BASE", lambda record: True),
        Rule(
            "EURUSD_15M_ALIGNED",
            lambda record: record.eurusd_15m_signed_atr > 0,
        ),
        Rule(
            "EURUSD_60M_ALIGNED",
            lambda record: record.eurusd_60m_signed_atr > 0,
        ),
        Rule(
            "EURUSD_15M_AND_60M_ALIGNED",
            lambda record: (
                record.eurusd_15m_signed_atr > 0
                and record.eurusd_60m_signed_atr > 0
            ),
        ),
        Rule(
            "EURUSD_15M_OR_60M_ALIGNED",
            lambda record: (
                record.eurusd_15m_signed_atr > 0
                or record.eurusd_60m_signed_atr > 0
            ),
        ),
        Rule(
            "EURUSD_15M_MATERIAL_GE_0_25ATR",
            lambda record: record.eurusd_15m_signed_atr >= 0.25,
        ),
        Rule(
            "DAILY_BROAD_USD_ALIGNED",
            lambda record: (record.daily_usd_signed_direction or 0.0) > 0,
        ),
        Rule(
            "DAILY_AND_EURUSD_15M",
            lambda record: (
                (record.daily_usd_signed_direction or 0.0) > 0
                and record.eurusd_15m_signed_atr > 0
            ),
        ),
        Rule(
            "DAILY_AND_EURUSD_60M",
            lambda record: (
                (record.daily_usd_signed_direction or 0.0) > 0
                and record.eurusd_60m_signed_atr > 0
            ),
        ),
        Rule(
            "DAILY_AND_EURUSD_BOTH",
            lambda record: (
                (record.daily_usd_signed_direction or 0.0) > 0
                and record.eurusd_15m_signed_atr > 0
                and record.eurusd_60m_signed_atr > 0
            ),
        ),
        Rule(
            "EURUSD_15M_AND_EXPECTED_COST_LE_0_20R",
            lambda record: (
                record.eurusd_15m_signed_atr > 0
                and record.expected_entry_cost_r <= 0.20
            ),
        ),
        Rule(
            "EURUSD_BOTH_AND_EXPECTED_COST_LE_0_20R",
            lambda record: (
                record.eurusd_15m_signed_atr > 0
                and record.eurusd_60m_signed_atr > 0
                and record.expected_entry_cost_r <= 0.20
            ),
        ),
    )


def _rule_result(
    rule: Rule,
    records: Sequence[ConfirmationRecord],
) -> dict[str, Any]:
    selected = [record for record in records if rule.predicate(record)]
    discovery = [
        record
        for record in selected
        if record.signal.session_date < date(2023, 1, 1)
    ]
    validation = [
        record
        for record in selected
        if date(2023, 1, 1)
        <= record.signal.session_date
        < date(2024, 1, 1)
    ]
    forward = [
        record
        for record in selected
        if date(2024, 1, 1)
        <= record.signal.session_date
        < date(2025, 1, 1)
    ]
    discovery_metrics = _metrics(discovery)
    validation_metrics = _metrics(validation)
    forward_metrics = _metrics(forward)
    eligible = all(
        metrics["trades"] >= 10
        for metrics in (
            discovery_metrics,
            validation_metrics,
            forward_metrics,
        )
    )
    expectancies = (
        discovery_metrics["net_expectancy_r"],
        validation_metrics["net_expectancy_r"],
        forward_metrics["net_expectancy_r"],
    )
    positive = (
        eligible
        and all(float(value) > 0 for value in expectancies)
    )
    return {
        "rule": rule.name,
        "eligible_for_ranking": eligible,
        "weakest_slice_expectancy_r": (
            round(min(float(value) for value in expectancies), 6)
            if eligible
            else None
        ),
        "positive_all_three": positive,
        "discovery_2021_2022": discovery_metrics,
        "validation_2023": validation_metrics,
        "forward_2024": forward_metrics,
    }


def _metrics(
    records: Sequence[ConfirmationRecord],
) -> dict[str, Any]:
    if not records:
        return {
            "trades": 0,
            "net_expectancy_r": None,
            "profit_factor": None,
        }
    values = [record.trade.net_r for record in records]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    interval = _bootstrap_mean(values)
    return {
        "trades": len(records),
        "long_trades": sum(
            record.signal.side == "LONG" for record in records
        ),
        "short_trades": sum(
            record.signal.side == "SHORT" for record in records
        ),
        "win_rate_pct": round(len(winners) / len(records) * 100, 3),
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
    }


if __name__ == "__main__":
    asyncio.run(main())
