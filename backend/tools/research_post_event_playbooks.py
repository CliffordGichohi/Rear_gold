from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import text

from gold_intel.infrastructure.database import session_factory

Side = Literal["LONG", "SHORT"]

SURPRISE_SQL = text(
    """
    WITH canonical AS (
        SELECT DISTINCT ON (surprise.release_id)
            surprise.event_id,
            surprise.release_id,
            surprise.component_code,
            surprise.released_at,
            surprise.available_at,
            surprise.gold_direction,
            surprise.strength,
            surprise.confidence,
            surprise.history_count,
            surprise.method,
            event.event_code,
            event.name AS event_name,
            event.importance
        FROM analytics.economic_surprises AS surprise
        JOIN market.economic_events AS event
          ON event.id = surprise.event_id
        WHERE surprise.is_synthetic = false
          AND surprise.released_at >= :start
          AND surprise.released_at < :end
          AND surprise.available_at <= surprise.released_at
        ORDER BY
            surprise.release_id,
            surprise.history_count DESC,
            surprise.created_at DESC
    )
    SELECT *
    FROM canonical
    ORDER BY released_at, event_code, component_code
    """
)

EVENT_BAR_SQL = text(
    """
    WITH event_times AS (
        SELECT DISTINCT released_at
        FROM analytics.economic_surprises
        WHERE is_synthetic = false
          AND released_at >= :start
          AND released_at < :end
          AND available_at <= released_at
    ),
    window_bars AS (
        SELECT candidate.*
        FROM event_times AS event
        CROSS JOIN LATERAL (
            SELECT DISTINCT ON (bar.open_time)
                bar.open_time,
                bar.close_time,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.spread_price,
                bar.available_at
            FROM market.price_bars AS bar
            WHERE bar.instrument_code = :instrument
              AND bar.timeframe = '1m'
              AND bar.provider_code = 'IC_MARKETS_MT5'
              AND bar.is_synthetic = false
              AND bar.open_time >= event.released_at - INTERVAL '65 minutes'
              AND bar.open_time < event.released_at + INTERVAL '245 minutes'
            ORDER BY bar.open_time, bar.available_at
        ) AS candidate
    )
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
    FROM window_bars
    ORDER BY open_time, available_at
    """
)

COMPONENT_WEIGHTS: dict[str, float] = {
    "CPI_CORE_MOM": 1.00,
    "CPI_HEADLINE_MOM": 0.80,
    "CPI_CORE_YOY": 0.70,
    "CPI_HEADLINE_YOY": 0.50,
    "PCE_CORE_MOM": 1.00,
    "PCE_HEADLINE_MOM": 0.75,
    "PCE_CORE_YOY": 0.70,
    "PCE_HEADLINE_YOY": 0.50,
    "NFP_CHANGE": 1.00,
    "AVERAGE_HOURLY_EARNINGS_MOM": 0.80,
    "UNEMPLOYMENT_RATE": 0.80,
    "AVERAGE_HOURLY_EARNINGS_YOY": 0.50,
    "RETAIL_SALES_MOM": 0.80,
    "GDP_QOQ_ANNUALIZED": 0.65,
    "INITIAL_JOBLESS_CLAIMS": 0.35,
    "FED_TARGET_RATE": 1.00,
}


@dataclass(frozen=True, slots=True)
class EventComponent:
    event_code: str
    event_name: str
    component_code: str
    released_at: datetime
    available_at: datetime
    gold_direction: float
    confidence: float
    history_count: int
    method: str


@dataclass(frozen=True, slots=True)
class EventSet:
    released_at: datetime
    event_codes: tuple[str, ...]
    event_names: tuple[str, ...]
    components: tuple[EventComponent, ...]
    composite_direction: float
    agreement_ratio: float

    @property
    def side(self) -> Side:
        return "LONG" if self.composite_direction > 0 else "SHORT"


@dataclass(frozen=True, slots=True)
class MinuteBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    spread: float
    available_at: datetime


@dataclass(frozen=True, slots=True)
class EventSignal:
    playbook: str
    released_at: datetime
    side: Side
    signal_time: datetime
    entry_time: datetime
    entry_reference: float
    stop: float
    base_target_r: float
    max_holding_minutes: int
    pre_atr: float
    composite_direction: float
    agreement_ratio: float
    event_codes: tuple[str, ...]
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EventTrade:
    playbook: str
    released_at: datetime
    side: Side
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    gross_r: float
    net_r: float
    cost_r: float
    mfe_r: float
    mae_r: float
    composite_direction: float
    agreement_ratio: float
    event_codes: tuple[str, ...]


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
        surprise_rows = (
            await session.execute(SURPRISE_SQL, {"start": start, "end": end})
        ).mappings()
        components = [
            EventComponent(
                event_code=row["event_code"],
                event_name=row["event_name"],
                component_code=row["component_code"],
                released_at=row["released_at"],
                available_at=row["available_at"],
                gold_direction=float(row["gold_direction"]),
                confidence=float(row["confidence"]),
                history_count=int(row["history_count"]),
                method=row["method"],
            )
            for row in surprise_rows
            if row["component_code"] in COMPONENT_WEIGHTS
        ]
        bar_rows = (
            await session.execute(
                EVENT_BAR_SQL,
                {
                    "start": start,
                    "end": end,
                    "instrument": "XAUUSD",
                },
            )
        ).mappings()
        bars = [
            MinuteBar(
                open_time=row["open_time"],
                close_time=row["close_time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                spread=float(row["spread_price"]),
                available_at=row["available_at"],
            )
            for row in bar_rows
        ]
        eurusd_rows = (
            await session.execute(
                EVENT_BAR_SQL,
                {
                    "start": start,
                    "end": end,
                    "instrument": "EURUSD",
                },
            )
        ).mappings()
        eurusd_bars = [
            MinuteBar(
                open_time=row["open_time"],
                close_time=row["close_time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                spread=float(row["spread_price"]),
                available_at=row["available_at"],
            )
            for row in eurusd_rows
        ]

    event_sets = _event_sets(components)
    bars_by_open = {bar.open_time: bar for bar in bars}
    eurusd_by_open = {bar.open_time: bar for bar in eurusd_bars}
    signals: list[EventSignal] = []
    exclusions: dict[str, int] = defaultdict(int)
    for event in event_sets:
        generated, reason = _signals(
            event,
            bars_by_open,
            eurusd_by_open,
        )
        if reason is not None:
            exclusions[reason] += 1
        signals.extend(generated)

    report: dict[str, Any] = {
        "contract": {
            "version": "POST_EVENT_PLAYBOOK_DISCOVERY_V0_2",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "event_sets": len(event_sets),
            "components": len(components),
            "signals": len(signals),
            "eurusd_event_window_bars": len(eurusd_bars),
            "exclusions": dict(sorted(exclusions.items())),
            "composite_minimum": 0.25,
            "agreement_minimum": 0.35,
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_validation": "calendar year 2025 (not loaded)",
            "selection": (
                "Base playbook fixed before validation; discovery n>=18, "
                "expectancy>=0.15R, PF>=1.20, 1.50x-cost expectancy>0, and "
                "bootstrap lower>=-0.05R."
            ),
            "intraday_rates_usd_confirmation": "UNKNOWN / NOT CLAIMED",
            "cost_model": {
                "observed_entry_exit_spread": True,
                "slippage_price_per_side": 0.05,
                "commission_price_round_turn": 0.07,
            },
        },
        "playbooks": {},
    }
    for playbook in sorted({signal.playbook for signal in signals}):
        selected = [signal for signal in signals if signal.playbook == playbook]
        report["playbooks"][playbook] = _playbook_report(
            selected,
            bars_by_open,
        )
    report["selected_candidates"] = [
        playbook
        for playbook, result in report["playbooks"].items()
        if result["selectable_on_discovery"]
    ]
    print(json.dumps(report, indent=2, sort_keys=True))


def _event_sets(components: Sequence[EventComponent]) -> list[EventSet]:
    grouped: dict[datetime, list[EventComponent]] = defaultdict(list)
    for component in components:
        grouped[component.released_at].append(component)
    output: list[EventSet] = []
    for released_at, members in sorted(grouped.items()):
        weighted_direction = 0.0
        total_weight = 0.0
        directional_weight = 0.0
        for member in members:
            weight = (
                COMPONENT_WEIGHTS[member.component_code]
                * member.confidence
                / 100
            )
            weighted_direction += weight * member.gold_direction
            total_weight += weight
            directional_weight += weight * abs(member.gold_direction)
        if total_weight <= 0 or directional_weight <= 0:
            continue
        composite = weighted_direction / total_weight
        agreement = abs(weighted_direction) / directional_weight
        if abs(composite) < 0.25 or agreement < 0.35:
            continue
        output.append(
            EventSet(
                released_at=released_at,
                event_codes=tuple(
                    sorted({member.event_code for member in members})
                ),
                event_names=tuple(
                    sorted({member.event_name for member in members})
                ),
                components=tuple(
                    sorted(members, key=lambda item: item.component_code)
                ),
                composite_direction=round(composite, 6),
                agreement_ratio=round(agreement, 6),
            )
        )
    return output


def _signals(
    event: EventSet,
    bars: dict[datetime, MinuteBar],
    eurusd_bars: dict[datetime, MinuteBar],
) -> tuple[list[EventSignal], str | None]:
    if event.released_at.second or event.released_at.microsecond:
        return [], "NON_MINUTE_RELEASE_CLOCK"
    pre = [
        bars.get(event.released_at - timedelta(minutes=offset))
        for offset in range(60, 0, -1)
    ]
    post = [
        bars.get(event.released_at + timedelta(minutes=offset))
        for offset in range(0, 245)
    ]
    if any(bar is None for bar in pre) or any(bar is None for bar in post):
        return [], "INCOMPLETE_EVENT_PRICE_WINDOW"
    before = [bar for bar in pre if bar is not None]
    after = [bar for bar in post if bar is not None]
    if any(bar.available_at > bar.close_time for bar in (*before, *after)):
        return [], "BAR_NOT_POINT_IN_TIME_ELIGIBLE"
    pre_atr = _pre_event_atr(before[-31:])
    if pre_atr <= 0:
        return [], "INVALID_PRE_EVENT_ATR"
    reference = before[-1].close
    pre_15 = before[-15:]
    high = max(bar.high for bar in pre_15)
    low = min(bar.low for bar in pre_15)
    reaction = after[:5]
    accepted = _accepted(
        event.side,
        reaction,
        boundary=high if event.side == "LONG" else low,
        reference=reference,
        pre_atr=pre_atr,
    )
    output: list[EventSignal] = []
    if accepted:
        acceptance = _acceptance_signal(
            event,
            after,
            boundary=high if event.side == "LONG" else low,
            pre_atr=pre_atr,
            reference=reference,
        )
        if acceptance is not None:
            output.append(acceptance)
        retest = _retest_signal(
            event,
            after,
            boundary=high if event.side == "LONG" else low,
            pre_atr=pre_atr,
            reference=reference,
        )
        if retest is not None:
            output.append(retest)
        continuation = _continuation_signal(
            event,
            after,
            pre_atr=pre_atr,
            reference=reference,
        )
        if continuation is not None:
            output.append(continuation)
    reversal = _first_move_reversal_signal(
        event,
        before,
        after,
        pre_atr=pre_atr,
        reference=reference,
    )
    if reversal is not None:
        output.append(reversal)
    eurusd_before = [
        eurusd_bars.get(event.released_at - timedelta(minutes=offset))
        for offset in range(60, 0, -1)
    ]
    eurusd_after = [
        eurusd_bars.get(event.released_at + timedelta(minutes=offset))
        for offset in range(0, 11)
    ]
    if not any(bar is None for bar in (*eurusd_before, *eurusd_after)):
        eurusd_pre = [
            bar for bar in eurusd_before if bar is not None
        ]
        eurusd_post = [
            bar for bar in eurusd_after if bar is not None
        ]
        dual = _dual_confirmation_signal(
            event,
            after,
            eurusd_pre,
            eurusd_post,
            gold_pre_atr=pre_atr,
            gold_reference=reference,
        )
        if dual is not None:
            output.append(dual)
        catch_up = _usd_led_catch_up_signal(
            event,
            before,
            after,
            eurusd_pre,
            eurusd_post,
            gold_pre_atr=pre_atr,
            gold_reference=reference,
        )
        if catch_up is not None:
            output.append(catch_up)
    return output, None


def _accepted(
    side: Side,
    bars: Sequence[MinuteBar],
    *,
    boundary: float,
    reference: float,
    pre_atr: float,
) -> bool:
    direction = 1 if side == "LONG" else -1
    final = bars[-1]
    closes_outside = sum(
        bar.close > boundary if side == "LONG" else bar.close < boundary
        for bar in bars
    )
    last_two_outside = all(
        bar.close > boundary if side == "LONG" else bar.close < boundary
        for bar in bars[-2:]
    )
    reaction_high = max(bar.high for bar in bars)
    reaction_low = min(bar.low for bar in bars)
    reaction_range = reaction_high - reaction_low
    if reaction_range <= 0:
        return False
    close_location = (
        (final.close - reaction_low) / reaction_range
        if side == "LONG"
        else (reaction_high - final.close) / reaction_range
    )
    net_move = direction * (final.close - reference)
    return (
        closes_outside >= 2
        and last_two_outside
        and close_location >= 0.65
        and net_move >= pre_atr
    )


def _acceptance_signal(
    event: EventSet,
    bars: Sequence[MinuteBar],
    *,
    boundary: float,
    pre_atr: float,
    reference: float,
) -> EventSignal | None:
    signal_bar = bars[4]
    entry_bar = bars[5]
    stop = (
        min(bar.low for bar in bars[-2:]) - 0.10 * pre_atr
        if event.side == "LONG"
        else max(bar.high for bar in bars[-2:]) + 0.10 * pre_atr
    )
    return _signal(
        playbook="E1_EVENT_5M_ACCEPTANCE",
        event=event,
        signal_bar=signal_bar,
        entry_bar=entry_bar,
        stop=stop,
        target_r=1.5,
        holding_minutes=120,
        pre_atr=pre_atr,
        evidence={"pre_event_boundary": boundary, "reference": reference},
    )


def _retest_signal(
    event: EventSet,
    bars: Sequence[MinuteBar],
    *,
    boundary: float,
    pre_atr: float,
    reference: float,
) -> EventSignal | None:
    for index in range(5, 15):
        bar = bars[index]
        touched = (
            bar.low <= boundary + 0.25 * pre_atr
            if event.side == "LONG"
            else bar.high >= boundary - 0.25 * pre_atr
        )
        held = (
            bar.close > boundary
            if event.side == "LONG"
            else bar.close < boundary
        )
        if touched and held and _directional_bar(
            bar,
            side=event.side,
            atr=pre_atr,
            min_body_atr=0.20,
        ):
            stop = (
                bar.low - 0.10 * pre_atr
                if event.side == "LONG"
                else bar.high + 0.10 * pre_atr
            )
            return _signal(
                playbook="E2_EVENT_ACCEPTED_RETEST",
                event=event,
                signal_bar=bar,
                entry_bar=bars[index + 1],
                stop=stop,
                target_r=2.0,
                holding_minutes=120,
                pre_atr=pre_atr,
                evidence={
                    "pre_event_boundary": boundary,
                    "reference": reference,
                },
            )
    return None


def _continuation_signal(
    event: EventSet,
    bars: Sequence[MinuteBar],
    *,
    pre_atr: float,
    reference: float,
) -> EventSignal | None:
    reaction_high = max(bar.high for bar in bars[:5])
    reaction_low = min(bar.low for bar in bars[:5])
    for index in range(5, 20):
        bar = bars[index]
        breakout = (
            bar.close > reaction_high
            if event.side == "LONG"
            else bar.close < reaction_low
        )
        if breakout and _directional_bar(
            bar,
            side=event.side,
            atr=pre_atr,
            min_body_atr=0.25,
        ):
            return _signal(
                playbook="E3_EVENT_CONTINUATION_BREAKOUT",
                event=event,
                signal_bar=bar,
                entry_bar=bars[index + 1],
                stop=(reaction_high + reaction_low) / 2,
                target_r=1.5,
                holding_minutes=120,
                pre_atr=pre_atr,
                evidence={
                    "reaction_high": reaction_high,
                    "reaction_low": reaction_low,
                    "reference": reference,
                },
            )
    return None


def _first_move_reversal_signal(
    event: EventSet,
    before: Sequence[MinuteBar],
    after: Sequence[MinuteBar],
    *,
    pre_atr: float,
    reference: float,
) -> EventSignal | None:
    direction = 1 if event.side == "LONG" else -1
    first_move = direction * (after[0].close - reference)
    if first_move > -0.50 * pre_atr:
        return None
    extreme = after[0].low if event.side == "LONG" else after[0].high
    for index in range(1, 10):
        bar = after[index]
        prior = after[max(0, index - 2) : index]
        reclaimed = (
            bar.close > reference
            if event.side == "LONG"
            else bar.close < reference
        )
        breaks_micro = (
            bar.close > max(item.high for item in prior)
            if event.side == "LONG"
            else bar.close < min(item.low for item in prior)
        )
        if reclaimed and breaks_micro and _directional_bar(
            bar,
            side=event.side,
            atr=pre_atr,
            min_body_atr=0.30,
        ):
            stop = (
                min(extreme, min(item.low for item in after[: index + 1]))
                - 0.10 * pre_atr
                if event.side == "LONG"
                else max(extreme, max(item.high for item in after[: index + 1]))
                + 0.10 * pre_atr
            )
            return _signal(
                playbook="E4_EVENT_FIRST_MOVE_REVERSAL",
                event=event,
                signal_bar=bar,
                entry_bar=after[index + 1],
                stop=stop,
                target_r=1.5,
                holding_minutes=120,
                pre_atr=pre_atr,
                evidence={
                    "first_move_price": after[0].close - before[-1].close,
                    "reference": reference,
                },
            )
    return None


def _dual_confirmation_signal(
    event: EventSet,
    gold_after: Sequence[MinuteBar],
    eurusd_before: Sequence[MinuteBar],
    eurusd_after: Sequence[MinuteBar],
    *,
    gold_pre_atr: float,
    gold_reference: float,
) -> EventSignal | None:
    eurusd_atr = _pre_event_atr(eurusd_before[-31:])
    if eurusd_atr <= 0:
        return None
    gold_reaction = gold_after[:5]
    eurusd_reaction = eurusd_after[:5]
    eurusd_reference = eurusd_before[-1].close
    if not (
        _five_minute_confirmation(
            event.side,
            gold_reaction,
            reference=gold_reference,
            atr=gold_pre_atr,
        )
        and _five_minute_confirmation(
            event.side,
            eurusd_reaction,
            reference=eurusd_reference,
            atr=eurusd_atr,
        )
    ):
        return None
    stop = (
        min(bar.low for bar in gold_reaction[-2:]) - 0.10 * gold_pre_atr
        if event.side == "LONG"
        else max(bar.high for bar in gold_reaction[-2:]) + 0.10 * gold_pre_atr
    )
    return _signal(
        playbook="E5_EVENT_DUAL_CONFIRMATION",
        event=event,
        signal_bar=gold_reaction[-1],
        entry_bar=gold_after[5],
        stop=stop,
        target_r=1.5,
        holding_minutes=120,
        pre_atr=gold_pre_atr,
        evidence={
            "gold_reference": gold_reference,
            "eurusd_reference": eurusd_reference,
            "eurusd_pre_atr": eurusd_atr,
            "cross_market_classification": (
                "EURUSD observed; weak/strong USD interpretation inferred"
            ),
        },
    )


def _usd_led_catch_up_signal(
    event: EventSet,
    gold_before: Sequence[MinuteBar],
    gold_after: Sequence[MinuteBar],
    eurusd_before: Sequence[MinuteBar],
    eurusd_after: Sequence[MinuteBar],
    *,
    gold_pre_atr: float,
    gold_reference: float,
) -> EventSignal | None:
    eurusd_atr = _pre_event_atr(eurusd_before[-31:])
    if eurusd_atr <= 0:
        return None
    eurusd_reference = eurusd_before[-1].close
    if not _five_minute_confirmation(
        event.side,
        eurusd_after[:5],
        reference=eurusd_reference,
        atr=eurusd_atr,
    ):
        return None
    if _five_minute_confirmation(
        event.side,
        gold_after[:5],
        reference=gold_reference,
        atr=gold_pre_atr,
    ):
        return None
    for index in range(5, 10):
        bar = gold_after[index]
        prior = gold_after[index - 2 : index]
        reclaimed = (
            bar.close > gold_reference
            if event.side == "LONG"
            else bar.close < gold_reference
        )
        breaks_micro = (
            bar.close > max(item.high for item in prior)
            if event.side == "LONG"
            else bar.close < min(item.low for item in prior)
        )
        if reclaimed and breaks_micro and _directional_bar(
            bar,
            side=event.side,
            atr=gold_pre_atr,
            min_body_atr=0.30,
        ):
            observed = gold_after[: index + 1]
            stop = (
                min(item.low for item in observed) - 0.10 * gold_pre_atr
                if event.side == "LONG"
                else max(item.high for item in observed) + 0.10 * gold_pre_atr
            )
            return _signal(
                playbook="E6_USD_LED_GOLD_CATCH_UP",
                event=event,
                signal_bar=bar,
                entry_bar=gold_after[index + 1],
                stop=stop,
                target_r=1.5,
                holding_minutes=120,
                pre_atr=gold_pre_atr,
                evidence={
                    "gold_reference": gold_reference,
                    "gold_pre_release_close": gold_before[-1].close,
                    "eurusd_reference": eurusd_reference,
                    "eurusd_pre_atr": eurusd_atr,
                    "cross_market_classification": (
                        "EURUSD moved first; gold catch-up is inferred"
                    ),
                },
            )
    return None


def _five_minute_confirmation(
    side: Side,
    bars: Sequence[MinuteBar],
    *,
    reference: float,
    atr: float,
) -> bool:
    if len(bars) != 5 or atr <= 0:
        return False
    direction = 1 if side == "LONG" else -1
    reaction_high = max(bar.high for bar in bars)
    reaction_low = min(bar.low for bar in bars)
    reaction_range = reaction_high - reaction_low
    if reaction_range <= 0:
        return False
    final = bars[-1]
    close_location = (
        (final.close - reaction_low) / reaction_range
        if side == "LONG"
        else (reaction_high - final.close) / reaction_range
    )
    confirming_closes = sum(
        bar.close > reference if side == "LONG" else bar.close < reference
        for bar in bars
    )
    return (
        direction * (final.close - reference) >= 0.75 * atr
        and confirming_closes >= 3
        and close_location >= 0.60
    )


def _signal(
    *,
    playbook: str,
    event: EventSet,
    signal_bar: MinuteBar,
    entry_bar: MinuteBar,
    stop: float,
    target_r: float,
    holding_minutes: int,
    pre_atr: float,
    evidence: dict[str, Any],
) -> EventSignal | None:
    if entry_bar.open_time != signal_bar.close_time:
        return None
    direction = 1 if event.side == "LONG" else -1
    risk = direction * (entry_bar.open - stop)
    if risk <= 0 or risk < 0.20 * pre_atr or risk > 20 * pre_atr:
        return None
    return EventSignal(
        playbook=playbook,
        released_at=event.released_at,
        side=event.side,
        signal_time=signal_bar.close_time,
        entry_time=entry_bar.open_time,
        entry_reference=entry_bar.open,
        stop=stop,
        base_target_r=target_r,
        max_holding_minutes=holding_minutes,
        pre_atr=pre_atr,
        composite_direction=event.composite_direction,
        agreement_ratio=event.agreement_ratio,
        event_codes=event.event_codes,
        evidence={
            **evidence,
            "event_names": event.event_names,
            "component_codes": [
                component.component_code for component in event.components
            ],
        },
    )


def _simulate(
    signal: EventSignal,
    bars: dict[datetime, MinuteBar],
    *,
    target_r: float,
    cost_multiplier: float,
) -> EventTrade | None:
    expected = [
        signal.entry_time + timedelta(minutes=offset)
        for offset in range(signal.max_holding_minutes)
    ]
    members = [bars.get(open_time) for open_time in expected]
    if any(bar is None for bar in members):
        return None
    path = [bar for bar in members if bar is not None]
    direction = 1 if signal.side == "LONG" else -1
    risk = abs(signal.entry_reference - signal.stop)
    target = signal.entry_reference + direction * target_r * risk
    reference_exit = path[-1].close
    exit_bar = path[-1]
    exit_reason = "TIME"
    favourable = 0.0
    adverse = 0.0
    for bar in path:
        if signal.side == "LONG":
            stop_hit = bar.low <= signal.stop
            target_hit = bar.high >= target
            favourable = max(favourable, bar.high - signal.entry_reference)
            adverse = max(adverse, signal.entry_reference - bar.low)
        else:
            stop_hit = bar.high >= signal.stop
            target_hit = bar.low <= target
            favourable = max(favourable, signal.entry_reference - bar.low)
            adverse = max(adverse, bar.high - signal.entry_reference)
        if stop_hit:
            reference_exit = signal.stop
            exit_bar = bar
            exit_reason = "STOP"
            break
        if target_hit:
            reference_exit = target
            exit_bar = bar
            exit_reason = "TARGET"
            break
    gross_r = direction * (reference_exit - signal.entry_reference) / risk
    cost_price = (
        (path[0].spread + exit_bar.spread) / 2 + 0.10 + 0.07
    ) * cost_multiplier
    cost_r = cost_price / risk
    return EventTrade(
        playbook=signal.playbook,
        released_at=signal.released_at,
        side=signal.side,
        entry_time=signal.entry_time,
        exit_time=exit_bar.close_time,
        exit_reason=exit_reason,
        gross_r=round(gross_r, 6),
        net_r=round(gross_r - cost_r, 6),
        cost_r=round(cost_r, 6),
        mfe_r=round(max(0.0, favourable / risk), 6),
        mae_r=round(max(0.0, adverse / risk), 6),
        composite_direction=signal.composite_direction,
        agreement_ratio=signal.agreement_ratio,
        event_codes=signal.event_codes,
    )


def _playbook_report(
    signals: Sequence[EventSignal],
    bars: dict[datetime, MinuteBar],
) -> dict[str, Any]:
    base = [
        trade
        for signal in signals
        if (
            trade := _simulate(
                signal,
                bars,
                target_r=signal.base_target_r,
                cost_multiplier=1.0,
            )
        )
        is not None
    ]
    discovery = [
        trade
        for trade in base
        if trade.released_at < datetime(2023, 1, 1, tzinfo=UTC)
    ]
    validation = [
        trade
        for trade in base
        if datetime(2023, 1, 1, tzinfo=UTC)
        <= trade.released_at
        < datetime(2024, 1, 1, tzinfo=UTC)
    ]
    forward = [
        trade for trade in base if trade.released_at >= datetime(2024, 1, 1, tzinfo=UTC)
    ]
    discovery_stressed = [
        trade
        for signal in signals
        if signal.released_at < datetime(2023, 1, 1, tzinfo=UTC)
        and (
            trade := _simulate(
                signal,
                bars,
                target_r=signal.base_target_r,
                cost_multiplier=1.5,
            )
        )
        is not None
    ]
    discovery_metrics = _metrics(discovery, months=17)
    discovery_stress_metrics = _metrics(
        discovery_stressed,
        months=17,
    )
    interval = discovery_metrics.get("bootstrap_95ci")
    selectable = bool(
        discovery_metrics["trades"] >= 18
        and discovery_metrics["net_expectancy_r"] is not None
        and float(discovery_metrics["net_expectancy_r"]) >= 0.15
        and discovery_metrics["profit_factor"] is not None
        and float(discovery_metrics["profit_factor"]) >= 1.20
        and discovery_stress_metrics["net_expectancy_r"] is not None
        and float(discovery_stress_metrics["net_expectancy_r"]) > 0
        and isinstance(interval, list)
        and float(interval[0]) >= -0.05
    )
    return {
        "signals": len(signals),
        "base_target_r": signals[0].base_target_r if signals else None,
        "selectable_on_discovery": selectable,
        "all_development": _metrics(base, months=41),
        "discovery_2021_2022": discovery_metrics,
        "discovery_1_50x_cost": discovery_stress_metrics,
        "validation_2023": _metrics(validation, months=12),
        "forward_2024": _metrics(forward, months=12),
        "strong_composite_abs_ge_0_50": {
            "discovery": _metrics(
                [
                    trade
                    for trade in discovery
                    if abs(trade.composite_direction) >= 0.50
                ],
                months=17,
            ),
            "validation": _metrics(
                [
                    trade
                    for trade in validation
                    if abs(trade.composite_direction) >= 0.50
                ],
                months=12,
            ),
            "forward": _metrics(
                [
                    trade
                    for trade in forward
                    if abs(trade.composite_direction) >= 0.50
                ],
                months=12,
            ),
        },
        "target_neighbourhood": {
            f"{target_r:.2f}R": {
                "discovery": _metrics(
                    [
                        trade
                        for signal in signals
                        if signal.released_at
                        < datetime(2023, 1, 1, tzinfo=UTC)
                        and (
                            trade := _simulate(
                                signal,
                                bars,
                                target_r=target_r,
                                cost_multiplier=1.0,
                            )
                        )
                        is not None
                    ],
                    months=17,
                ),
                "validation": _metrics(
                    [
                        trade
                        for signal in signals
                        if datetime(2023, 1, 1, tzinfo=UTC)
                        <= signal.released_at
                        < datetime(2024, 1, 1, tzinfo=UTC)
                        and (
                            trade := _simulate(
                                signal,
                                bars,
                                target_r=target_r,
                                cost_multiplier=1.0,
                            )
                        )
                        is not None
                    ],
                    months=12,
                ),
                "forward": _metrics(
                    [
                        trade
                        for signal in signals
                        if signal.released_at
                        >= datetime(2024, 1, 1, tzinfo=UTC)
                        and (
                            trade := _simulate(
                                signal,
                                bars,
                                target_r=target_r,
                                cost_multiplier=1.0,
                            )
                        )
                        is not None
                    ],
                    months=12,
                ),
            }
            for target_r in (1.0, 1.5, 2.0)
        },
        "cost_stress": {
            f"{multiplier:.2f}x": _tiny_metrics(
                [
                    trade
                    for signal in signals
                    if (
                        trade := _simulate(
                            signal,
                            bars,
                            target_r=signal.base_target_r,
                            cost_multiplier=multiplier,
                        )
                    )
                    is not None
                ]
            )
            for multiplier in (1.0, 1.5, 2.0)
        },
    }


def _metrics(
    trades: Sequence[EventTrade],
    *,
    months: int,
) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "net_expectancy_r": None,
            "profit_factor": None,
        }
    values = [trade.net_r for trade in trades]
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    interval = _bootstrap(values)
    by_year: dict[str, list[float]] = defaultdict(list)
    by_event: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        by_year[str(trade.released_at.year)].append(trade.net_r)
        for event_code in trade.event_codes:
            by_event[event_code].append(trade.net_r)
    total = sum(values)
    return {
        "trades": len(trades),
        "long_trades": sum(trade.side == "LONG" for trade in trades),
        "short_trades": sum(trade.side == "SHORT" for trade in trades),
        "win_rate_pct": round(len(winners) / len(trades) * 100, 3),
        "net_expectancy_r": round(statistics.mean(values), 6),
        "profit_factor": (
            round(sum(winners) / abs(sum(losers)), 6)
            if winners and losers
            else None
        ),
        "total_net_r": round(total, 6),
        "bootstrap_95ci": [round(interval[0], 6), round(interval[1], 6)],
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
        "average_monthly_r_including_zero_months": round(total / months, 6),
        "average_monthly_usd_at_1pct_risk": round(total * 100 / months, 2),
        "by_year": {
            key: _group(value) for key, value in sorted(by_year.items())
        },
        "by_event_code": {
            key: _group(value)
            for key, value in sorted(
                by_event.items(),
                key=lambda item: len(item[1]),
                reverse=True,
            )
        },
    }


def _tiny_metrics(trades: Sequence[EventTrade]) -> dict[str, Any]:
    metrics = _metrics(trades, months=41)
    return {
        key: metrics[key]
        for key in (
            "trades",
            "win_rate_pct",
            "net_expectancy_r",
            "profit_factor",
            "total_net_r",
        )
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


def _pre_event_atr(bars: Sequence[MinuteBar]) -> float:
    ranges: list[float] = []
    for prior, current in zip(bars, bars[1:], strict=False):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - prior.close),
                abs(current.low - prior.close),
            )
        )
    return statistics.mean(ranges) if ranges else 0.0


def _directional_bar(
    bar: MinuteBar,
    *,
    side: Side,
    atr: float,
    min_body_atr: float,
) -> bool:
    candle_range = bar.high - bar.low
    if candle_range <= 0 or atr <= 0:
        return False
    body = bar.close - bar.open if side == "LONG" else bar.open - bar.close
    close_location = (
        (bar.close - bar.low) / candle_range
        if side == "LONG"
        else (bar.high - bar.close) / candle_range
    )
    return (
        body >= min_body_atr * atr
        and body / candle_range >= 0.50
        and close_location >= 0.60
    )


def _bootstrap(values: Sequence[float]) -> tuple[float, float]:
    if len(values) < 2:
        value = values[0] if values else 0.0
        return value, value
    generator = random.Random(20260727)
    estimates = [
        statistics.mean(generator.choice(values) for _ in values)
        for _ in range(5_000)
    ]
    estimates.sort()
    return (
        estimates[math.floor(0.025 * (len(estimates) - 1))],
        estimates[math.ceil(0.975 * (len(estimates) - 1))],
    )


if __name__ == "__main__":
    asyncio.run(main())
