from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from research_daily_session_playbooks import (
    Bar,
    Day,
    Signal,
    Trade,
    _atr_by_close,
    _bootstrap_mean,
    _build_days,
    _signals_for_day,
    _simulate,
)
from sqlalchemy import text

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory

FIVE_MINUTE_SQL = text(
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
        WHERE instrument_code = 'XAUUSD'
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

Predicate = Callable[["ContextRecord"], bool]


@dataclass(frozen=True, slots=True)
class ContextRecord:
    signal: Signal
    trade: Trade
    fundamental_score: float
    fundamental_confidence: float
    fundamental_coverage: float
    regime: str
    reaction_function: str
    crowding_percentile: float | None
    signed_components: dict[str, float | None]
    signed_momentum_4h_atr: float | None
    signed_momentum_24h_atr: float | None
    asia_range_atr: float
    asia_range_percentile: float
    risk_atr: float

    @property
    def side_sign(self) -> int:
        return 1 if self.signal.side == "LONG" else -1

    @property
    def signed_fundamental_score(self) -> float:
        return self.side_sign * self.fundamental_score

    @property
    def core_confirmation_count(self) -> int:
        return sum(
            (self.signed_components.get(code) or 0.0) > 0
            for code in ("REAL_YIELD", "TWO_YEAR_YIELD", "USD")
        )

    @property
    def cot_not_crowded(self) -> bool:
        if self.crowding_percentile is None:
            return False
        if self.signal.side == "LONG":
            return self.crowding_percentile < 90
        return self.crowding_percentile > 10


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
        rows = (
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
            for row in rows
        ]
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)

    days = _build_days(bars, start=start, end=end)
    records = _build_records(
        days,
        bars=bars,
        fundamental_inputs=fundamental_inputs,
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
    rules = _rules()
    report: dict[str, Any] = {
        "contract": {
            "version": "SESSION_CONTEXT_GATE_DISCOVERY_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "complete_trades": len(records),
            "discovery": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_validation": "calendar year 2025 (not loaded)",
            "selection_policy": (
                "Predeclared causal gates only; rank by the weaker of 2023 and "
                "2024 expectancy with minimum 10 trades in each slice."
            ),
        },
        "scopes": {},
    }
    for scope_name, scope_records in scopes.items():
        candidates = []
        for rule in rules:
            selected = [record for record in scope_records if rule.predicate(record)]
            discovery = [
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
            forward_metrics = _metrics(forward)
            eligible = (
                discovery_metrics["trades"] >= 10
                and forward_metrics["trades"] >= 10
            )
            weaker_expectancy = (
                min(
                    float(discovery_metrics["net_expectancy_r"]),
                    float(forward_metrics["net_expectancy_r"]),
                )
                if eligible
                else -999.0
            )
            candidates.append(
                {
                    "rule": rule.name,
                    "eligible_for_ranking": eligible,
                    "weaker_slice_expectancy_r": (
                        round(weaker_expectancy, 6) if eligible else None
                    ),
                    "discovery_2023": discovery_metrics,
                    "forward_2024": forward_metrics,
                    "both_slices_positive": (
                        eligible
                        and float(discovery_metrics["net_expectancy_r"]) > 0
                        and float(forward_metrics["net_expectancy_r"]) > 0
                    ),
                }
            )
        candidates.sort(
            key=lambda item: (
                item["eligible_for_ranking"],
                item["weaker_slice_expectancy_r"]
                if item["weaker_slice_expectancy_r"] is not None
                else -999.0,
                min(
                    item["discovery_2023"]["trades"],
                    item["forward_2024"]["trades"],
                ),
            ),
            reverse=True,
        )
        report["scopes"][scope_name] = {
            "records_all_years": len(scope_records),
            "top_rules": candidates[: args.top],
            "positive_both_count": sum(
                item["both_slices_positive"] for item in candidates
            ),
        }
    print(json.dumps(report, indent=2, sort_keys=True))


def _build_records(
    days: Sequence[Day],
    *,
    bars: Sequence[Bar],
    fundamental_inputs: Any,
) -> list[ContextRecord]:
    atr_by_close = _atr_by_close(bars)
    bars_by_open = {bar.open_time: bar for bar in bars}
    close_times = [bar.close_time for bar in bars]
    london_range_history: list[float] = []
    asia_range_history: list[float] = []
    output: list[ContextRecord] = []
    for day in days:
        asia_range = max(bar.high for bar in day.asia) - min(
            bar.low for bar in day.asia
        )
        asia_percentile = _percentile(
            asia_range,
            asia_range_history[-60:],
        )
        signals = _signals_for_day(
            day,
            atr_by_close=atr_by_close,
            london_range_history=london_range_history,
        )
        state = None
        if day.session_date >= date(2023, 1, 1) and signals:
            fundamental_freeze = day.london[0].open_time - timedelta(minutes=5)
            state = fundamental_inputs.state_at(fundamental_freeze)
        for signal in signals:
            if state is None:
                continue
            trade = _simulate(
                signal,
                bars_by_open,
                target_r=signal.base_target_r,
                cost_multiplier=1.0,
            )
            if trade is None:
                continue
            components = {
                component.code: (
                    component.direction
                    if signal.side == "LONG"
                    else -component.direction
                )
                for component in state.components
                if component.epistemic_status != "UNKNOWN"
            }
            signal_index = bisect_right(close_times, signal.signal_time) - 1
            current = bars[signal_index]
            momentum_4h = _signed_momentum(
                bars,
                signal_index,
                lookback=48,
                side=signal.side,
                atr=signal.atr,
            )
            momentum_24h = _signed_momentum(
                bars,
                signal_index,
                lookback=288,
                side=signal.side,
                atr=signal.atr,
            )
            risk = abs(signal.entry_reference - signal.stop)
            crowding = state.reasoning.get("crowding", {})
            output.append(
                ContextRecord(
                    signal=signal,
                    trade=trade,
                    fundamental_score=state.directional_score,
                    fundamental_confidence=state.confidence,
                    fundamental_coverage=state.coverage,
                    regime=state.regime_label,
                    reaction_function=state.reaction_function,
                    crowding_percentile=_optional_float(
                        crowding.get("percentile")
                    ),
                    signed_components={
                        code: _optional_float(components.get(code))
                        for code in (
                            "REAL_YIELD",
                            "TWO_YEAR_YIELD",
                            "USD",
                            "POSITIONING_FLOW",
                            "CATALYST_SURPRISE",
                            "INFLATION_REGIME",
                            "GROWTH_REGIME",
                            "LABOUR_REGIME",
                        )
                    },
                    signed_momentum_4h_atr=momentum_4h,
                    signed_momentum_24h_atr=momentum_24h,
                    asia_range_atr=asia_range / signal.atr,
                    asia_range_percentile=asia_percentile,
                    risk_atr=risk / signal.atr,
                )
            )
            if current.close_time != signal.signal_time:
                raise RuntimeError("Signal bar lookup is not point-in-time aligned")
        london_range_history.append(
            max(bar.high for bar in day.london)
            - min(bar.low for bar in day.london)
        )
        asia_range_history.append(asia_range)
    return output


def _rules() -> tuple[Rule, ...]:
    return (
        Rule("BASE", lambda record: True),
        Rule(
            "MACRO_NOT_OPPOSED_MINUS_5",
            lambda record: record.signed_fundamental_score >= -5,
        ),
        Rule(
            "MACRO_ALIGNED_0",
            lambda record: record.signed_fundamental_score >= 0,
        ),
        Rule(
            "MACRO_ALIGNED_5",
            lambda record: record.signed_fundamental_score >= 5,
        ),
        Rule(
            "MACRO_ALIGNED_10",
            lambda record: record.signed_fundamental_score >= 10,
        ),
        Rule(
            "REAL_YIELD_ALIGNED",
            lambda record: _component(record, "REAL_YIELD") > 0,
        ),
        Rule(
            "TWO_YEAR_ALIGNED",
            lambda record: _component(record, "TWO_YEAR_YIELD") > 0,
        ),
        Rule(
            "USD_ALIGNED",
            lambda record: _component(record, "USD") > 0,
        ),
        Rule(
            "RATES_USD_2_OF_3",
            lambda record: record.core_confirmation_count >= 2,
        ),
        Rule(
            "RATES_USD_ALL_3",
            lambda record: record.core_confirmation_count == 3,
        ),
        Rule(
            "PRICE_4H_ALIGNED",
            lambda record: (record.signed_momentum_4h_atr or 0.0) > 0,
        ),
        Rule(
            "PRICE_24H_ALIGNED",
            lambda record: (record.signed_momentum_24h_atr or 0.0) > 0,
        ),
        Rule(
            "PRICE_4H_AND_24H_ALIGNED",
            lambda record: (
                (record.signed_momentum_4h_atr or 0.0) > 0
                and (record.signed_momentum_24h_atr or 0.0) > 0
            ),
        ),
        Rule(
            "MACRO_0_AND_PRICE_4H",
            lambda record: (
                record.signed_fundamental_score >= 0
                and (record.signed_momentum_4h_atr or 0.0) > 0
            ),
        ),
        Rule(
            "MACRO_5_AND_PRICE_4H",
            lambda record: (
                record.signed_fundamental_score >= 5
                and (record.signed_momentum_4h_atr or 0.0) > 0
            ),
        ),
        Rule(
            "CORE_2_OF_3_AND_PRICE_4H",
            lambda record: (
                record.core_confirmation_count >= 2
                and (record.signed_momentum_4h_atr or 0.0) > 0
            ),
        ),
        Rule(
            "MACRO_0_AND_COT_NOT_CROWDED",
            lambda record: (
                record.signed_fundamental_score >= 0
                and record.cot_not_crowded
            ),
        ),
        Rule(
            "MACRO_0_AND_ASIA_COMPRESSION",
            lambda record: (
                record.signed_fundamental_score >= 0
                and record.asia_range_percentile <= 40
            ),
        ),
        Rule(
            "MACRO_0_AND_COST_LE_0_15R",
            lambda record: (
                record.signed_fundamental_score >= 0
                and record.trade.cost_r <= 0.15
            ),
        ),
        Rule(
            "CORE_2_OF_3_AND_COST_LE_0_15R",
            lambda record: (
                record.core_confirmation_count >= 2
                and record.trade.cost_r <= 0.15
            ),
        ),
        Rule(
            "FULL_CONFLUENCE",
            lambda record: (
                record.signed_fundamental_score >= 5
                and record.core_confirmation_count >= 2
                and (record.signed_momentum_4h_atr or 0.0) > 0
                and record.cot_not_crowded
                and record.trade.cost_r <= 0.15
            ),
        ),
    )


def _metrics(records: Sequence[ContextRecord]) -> dict[str, Any]:
    if not records:
        return {
            "trades": 0,
            "net_expectancy_r": None,
            "profit_factor": None,
        }
    values = [record.trade.net_r for record in records]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    by_side: dict[str, list[float]] = defaultdict(list)
    by_playbook: dict[str, list[float]] = defaultdict(list)
    for record in records:
        by_side[record.signal.side].append(record.trade.net_r)
        by_playbook[record.signal.playbook].append(record.trade.net_r)
    interval = _bootstrap_mean(values)
    return {
        "trades": len(values),
        "win_rate_pct": round(len(winners) / len(values) * 100, 3),
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
        "long_trades": len(by_side["LONG"]),
        "short_trades": len(by_side["SHORT"]),
        "playbook_mix": {
            key: len(value) for key, value in sorted(by_playbook.items())
        },
    }


def _signed_momentum(
    bars: Sequence[Bar],
    index: int,
    *,
    lookback: int,
    side: str,
    atr: float,
) -> float | None:
    if index < lookback or atr <= 0:
        return None
    direction = 1 if side == "LONG" else -1
    return direction * (bars[index].close - bars[index - lookback].close) / atr


def _component(record: ContextRecord, code: str) -> float:
    return record.signed_components.get(code) or 0.0


def _percentile(value: float, history: Sequence[float]) -> float:
    if not history:
        return 50.0
    return sum(item <= value for item in history) / len(history) * 100


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


if __name__ == "__main__":
    asyncio.run(main())
