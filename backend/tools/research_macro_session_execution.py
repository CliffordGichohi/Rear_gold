from __future__ import annotations

import argparse
import asyncio
import json
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from explore_session_playbooks import Bar, Day, _build_days
from research_daily_session_playbooks import (
    Side,
    Signal,
    Trade,
    _atr_by_close,
    _directional_bar,
    _metrics,
    _signal,
    _simulate,
)
from research_intraday_usd_confirmation import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
)

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory

Predicate = Callable[["ExecutionRecord"], bool]


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    signal: Signal
    trade: Trade
    eurusd_60m_signed_atr: float | None


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    predicate: Predicate


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded during development")

    async with session_factory() as session:
        query = {
            "load_start": start - timedelta(days=6),
            "load_end": end,
        }
        gold_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "XAUUSD", **query},
                )
            ).mappings()
        )
        eurusd_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "EURUSD", **query},
                )
            ).mappings()
        )
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)

    days = _build_days(gold_bars, start=start, end=end)
    records = _build_records(
        days,
        gold_bars=gold_bars,
        eurusd_bars=eurusd_bars,
        fundamental_inputs=fundamental_inputs,
    )
    report: dict[str, Any] = {
        "contract": {
            "version": "MACRO_SESSION_EXECUTION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "complete_trades": len(records),
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
            "bias": (
                "Production point-in-time score at 07:55 London; absolute score "
                "must be at least 10 and trade side is the score direction."
            ),
            "cost_model": {
                "observed_entry_exit_broker_spread": True,
                "adverse_slippage_price_per_side": 0.05,
                "commission_price_round_turn": 0.07,
                "same_bar_ordering": "STOP_FIRST",
            },
        },
        "playbooks": {},
    }
    playbooks = sorted({record.signal.playbook for record in records})
    gold_by_open = {bar.open_time: bar for bar in gold_bars}
    for playbook in playbooks:
        members = [
            record for record in records if record.signal.playbook == playbook
        ]
        report["playbooks"][playbook] = {
            "records": len(members),
            "rules": {
                rule.name: _rule_report(members, rule=rule)
                for rule in _rules()
            },
            "target_neighbourhood": _target_neighbourhood(
                members,
                bars_by_open=gold_by_open,
            ),
            "cost_stress": {
                f"{multiplier:.2f}x": _split_metrics(
                    [
                        trade
                        for record in members
                        if (
                            trade := _simulate(
                                record.signal,
                                gold_by_open,
                                target_r=record.signal.base_target_r,
                                cost_multiplier=multiplier,
                            )
                        )
                        is not None
                    ]
                )
                for multiplier in (1.0, 1.5, 2.0)
            },
        }
    print(json.dumps(report, indent=2, sort_keys=True))


def _build_records(
    days: Sequence[Day],
    *,
    gold_bars: Sequence[Bar],
    eurusd_bars: Sequence[Bar],
    fundamental_inputs: Any,
) -> list[ExecutionRecord]:
    gold_atr = _atr_by_close(gold_bars)
    eurusd_atr = _atr_by_close(eurusd_bars)
    gold_by_open = {bar.open_time: bar for bar in gold_bars}
    eurusd_close_times = [bar.close_time for bar in eurusd_bars]
    output: list[ExecutionRecord] = []
    for day in days:
        decision_at = day.london[0].open_time - timedelta(minutes=5)
        state = fundamental_inputs.state_at(decision_at)
        if abs(state.directional_score) < 10:
            continue
        side: Side = "LONG" if state.directional_score > 0 else "SHORT"
        atr = gold_atr.get(decision_at)
        if atr is None or atr <= 0:
            continue
        signals = [
            signal
            for signal in (
                _session_carry(
                    day,
                    side=side,
                    atr=atr,
                ),
                _opening_range_continuation(
                    day,
                    side=side,
                    atr_by_close=gold_atr,
                ),
                _adverse_auction_reclaim(
                    day,
                    side=side,
                    atr_by_close=gold_atr,
                ),
            )
            if signal is not None
        ]
        for signal in signals:
            context = {
                "fundamental_score": state.directional_score,
                "fundamental_confidence": state.confidence,
                "fundamental_coverage": state.coverage,
                "regime": state.regime_label,
                "reaction_function": state.reaction_function,
                "dominant_driver": state.dominant_driver,
                "fundamental_data_hash": state.data_hash,
                "score_is_not_trade_signal": True,
            }
            enriched = replace(
                signal,
                evidence={**signal.evidence, **context},
            )
            trade = _simulate(
                enriched,
                gold_by_open,
                target_r=enriched.base_target_r,
                cost_multiplier=1.0,
            )
            if trade is None:
                continue
            eurusd_signed = _eurusd_60m_confirmation(
                eurusd_bars,
                close_times=eurusd_close_times,
                atr_by_close=eurusd_atr,
                signal=enriched,
            )
            output.append(
                ExecutionRecord(
                    signal=enriched,
                    trade=trade,
                    eurusd_60m_signed_atr=eurusd_signed,
                )
            )
    return output


def _session_carry(
    day: Day,
    *,
    side: Side,
    atr: float,
) -> Signal | None:
    if len(day.london) < 2:
        return None
    asia_high = max(bar.high for bar in day.asia)
    asia_low = min(bar.low for bar in day.asia)
    stop = asia_low - 0.10 * atr if side == "LONG" else asia_high + 0.10 * atr
    entry_bar = day.london[1]
    if (side == "LONG" and stop >= entry_bar.open) or (
        side == "SHORT" and stop <= entry_bar.open
    ):
        return None
    holding = _holding_to_new_york_close(day, entry_bar=entry_bar)
    if holding < 5:
        return None
    return _signal(
        playbook="P9_MACRO_SESSION_CARRY",
        day=day,
        side=side,
        signal_bar=day.london[0],
        entry_bar=entry_bar,
        stop=stop,
        target_r=1_000.0,
        holding_minutes=holding,
        atr=atr,
        evidence={
            "asia_high": asia_high,
            "asia_low": asia_low,
            "exit_contract": "NEW_YORK_RESEARCH_WINDOW_CLOSE_OR_STOP",
        },
    )


def _opening_range_continuation(
    day: Day,
    *,
    side: Side,
    atr_by_close: dict[datetime, float],
) -> Signal | None:
    opening = day.london[:6]
    if len(opening) != 6:
        return None
    opening_high = max(bar.high for bar in opening)
    opening_low = min(bar.low for bar in opening)
    stop = (opening_high + opening_low) / 2
    for index in range(6, min(len(day.london) - 1, 30)):
        bar = day.london[index]
        atr = atr_by_close.get(bar.close_time)
        if atr is None or atr <= 0:
            continue
        broke = (
            bar.close > opening_high
            if side == "LONG"
            else bar.close < opening_low
        )
        if not broke or not _directional_bar(
            bar,
            side=side,
            atr=atr,
            min_body_atr=0.20,
            min_body_ratio=0.50,
            min_close_location=0.60,
        ):
            continue
        entry_bar = day.london[index + 1]
        if (side == "LONG" and stop >= entry_bar.open) or (
            side == "SHORT" and stop <= entry_bar.open
        ):
            return None
        holding = _holding_to_new_york_close(day, entry_bar=entry_bar)
        return _signal(
            playbook="P10_MACRO_LONDON_OPENING_RANGE",
            day=day,
            side=side,
            signal_bar=bar,
            entry_bar=entry_bar,
            stop=stop,
            target_r=1.5,
            holding_minutes=holding,
            atr=atr,
            evidence={
                "opening_range_high": opening_high,
                "opening_range_low": opening_low,
            },
        )
    return None


def _adverse_auction_reclaim(
    day: Day,
    *,
    side: Side,
    atr_by_close: dict[datetime, float],
) -> Signal | None:
    london_open = day.london[0].open
    for index in range(3, min(len(day.london) - 1, 30)):
        bar = day.london[index]
        atr = atr_by_close.get(bar.close_time)
        if atr is None or atr <= 0:
            continue
        prior = day.london[:index]
        adverse_extreme = (
            min(member.low for member in prior)
            if side == "LONG"
            else max(member.high for member in prior)
        )
        adverse_distance = (
            london_open - adverse_extreme
            if side == "LONG"
            else adverse_extreme - london_open
        )
        if adverse_distance < 0.50 * atr:
            continue
        micro = day.london[index - 3 : index]
        reclaimed = (
            bar.close > london_open
            if side == "LONG"
            else bar.close < london_open
        )
        displaced = (
            bar.close > max(member.high for member in micro)
            if side == "LONG"
            else bar.close < min(member.low for member in micro)
        )
        if not reclaimed or not displaced or not _directional_bar(
            bar,
            side=side,
            atr=atr,
            min_body_atr=0.25,
            min_body_ratio=0.55,
            min_close_location=0.65,
        ):
            continue
        entry_bar = day.london[index + 1]
        stop = (
            adverse_extreme - 0.10 * atr
            if side == "LONG"
            else adverse_extreme + 0.10 * atr
        )
        if (side == "LONG" and stop >= entry_bar.open) or (
            side == "SHORT" and stop <= entry_bar.open
        ):
            return None
        holding = _holding_to_new_york_close(day, entry_bar=entry_bar)
        return _signal(
            playbook="P11_MACRO_ADVERSE_AUCTION_RECLAIM",
            day=day,
            side=side,
            signal_bar=bar,
            entry_bar=entry_bar,
            stop=stop,
            target_r=1.5,
            holding_minutes=holding,
            atr=atr,
            evidence={
                "london_open": london_open,
                "adverse_distance_atr": adverse_distance / atr,
            },
        )
    return None


def _holding_to_new_york_close(day: Day, *, entry_bar: Bar) -> int:
    return int(
        (day.new_york[-1].close_time - entry_bar.open_time).total_seconds()
        // 60
    )


def _eurusd_60m_confirmation(
    bars: Sequence[Bar],
    *,
    close_times: Sequence[datetime],
    atr_by_close: dict[datetime, float],
    signal: Signal,
) -> float | None:
    index = bisect_right(close_times, signal.signal_time) - 1
    if index < 12 or close_times[index] != signal.signal_time:
        return None
    atr = atr_by_close.get(signal.signal_time)
    if atr is None or atr <= 0:
        return None
    side_sign = 1 if signal.side == "LONG" else -1
    return side_sign * (bars[index].close - bars[index - 12].close) / atr


def _rules() -> tuple[Rule, ...]:
    return (
        Rule("BASE", lambda record: True),
        Rule(
            "EURUSD_60M_NOT_OPPOSED",
            lambda record: (
                record.eurusd_60m_signed_atr is not None
                and record.eurusd_60m_signed_atr >= 0
            ),
        ),
        Rule(
            "EURUSD_60M_ALIGNED",
            lambda record: (
                record.eurusd_60m_signed_atr is not None
                and record.eurusd_60m_signed_atr > 0
            ),
        ),
        Rule(
            "EURUSD_60M_MATERIAL_GE_0_25ATR",
            lambda record: (
                record.eurusd_60m_signed_atr is not None
                and record.eurusd_60m_signed_atr >= 0.25
            ),
        ),
    )


def _rule_report(
    records: Sequence[ExecutionRecord],
    *,
    rule: Rule,
) -> dict[str, Any]:
    selected = [record for record in records if rule.predicate(record)]
    metrics = _split_metrics([record.trade for record in selected])
    discovery = metrics["discovery_2021_2022"]
    validation = metrics["validation_2023"]
    forward = metrics["forward_2024"]
    qualified = (
        sum(item["trades"] for item in (discovery, validation, forward)) >= 150
        and all(
            item["net_expectancy_r"] is not None
            and item["net_expectancy_r"] > 0
            for item in (discovery, validation, forward)
        )
        and metrics["all_pre_2025"]["profit_factor"] is not None
        and metrics["all_pre_2025"]["profit_factor"] > 1.25
    )
    return {
        **metrics,
        "positive_all_three_splits": all(
            item["net_expectancy_r"] is not None
            and item["net_expectancy_r"] > 0
            for item in (discovery, validation, forward)
        ),
        "preliminary_qualification_without_cost_stress": qualified,
    }


def _split_metrics(trades: Sequence[Trade]) -> dict[str, Any]:
    return {
        "all_pre_2025": _metrics(trades),
        "discovery_2021_2022": _metrics(
            [trade for trade in trades if trade.session_date < date(2023, 1, 1)]
        ),
        "validation_2023": _metrics(
            [
                trade
                for trade in trades
                if date(2023, 1, 1)
                <= trade.session_date
                < date(2024, 1, 1)
            ]
        ),
        "forward_2024": _metrics(
            [
                trade
                for trade in trades
                if date(2024, 1, 1)
                <= trade.session_date
                < date(2025, 1, 1)
            ]
        ),
    }


def _target_neighbourhood(
    records: Sequence[ExecutionRecord],
    *,
    bars_by_open: dict[datetime, Bar],
) -> dict[str, Any]:
    if not records:
        return {}
    playbook = records[0].signal.playbook
    targets = (
        (1.0, 1.5)
        if playbook == "P9_MACRO_SESSION_CARRY"
        else (1.0, 1.5, 2.0)
    )
    return {
        f"{target:.2f}R": _split_metrics(
            [
                trade
                for record in records
                if (
                    trade := _simulate(
                        record.signal,
                        bars_by_open,
                        target_r=target,
                        cost_multiplier=1.0,
                    )
                )
                is not None
            ]
        )
        for target in targets
    }


if __name__ == "__main__":
    asyncio.run(main())
