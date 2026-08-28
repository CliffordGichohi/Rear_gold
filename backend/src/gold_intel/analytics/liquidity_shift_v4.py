from __future__ import annotations

import bisect
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from gold_intel.analytics.liquidity_shift_v2 import (
    Direction,
    LiquidityPivotV2,
    LiquidityShiftV2Config,
    build_liquidity_shift_study_v2,
)
from gold_intel.analytics.structure import AggregateBar

LIQUIDITY_RESPONSE_M5_STATE_V4_RULESET = "gold-liquidity-response-m5-state-v4"
EntryFamilyV4 = Literal["M5_BREAK_NEXT_M1_V4", "M5_BROKEN_PIVOT_RETEST_V4"]


@dataclass(frozen=True, slots=True)
class LiquidityResponseM5StateV4Config:
    maximum_location_hours: int = 36
    maximum_activation_hours: int = 4
    break_buffer_ticks: int = 2
    stop_buffer_m5_atr: float = 0.10
    tick_size: float = 0.01


@dataclass(frozen=True, slots=True)
class LiquidityLocationEpisodeV4:
    identity: str
    zone_identity: str
    contact_identity: str
    zone_timeframe: str
    direction: Direction
    started_at: datetime
    terminal_at: datetime
    terminal_reason: str


@dataclass(frozen=True, slots=True)
class CausalM5BreakV4:
    identity: str
    direction: Direction
    pivot_identity: str
    pivot_level: float
    detected_at: datetime
    close: float
    atr14: float
    break_margin_atr: float
    opposing_pivot_identity: str | None
    opposing_pivot_level: float | None


@dataclass(frozen=True, slots=True)
class M5ActivationStateV4:
    identity: str
    location_identity: str
    zone_identity: str
    zone_timeframe: str
    direction: Direction
    broken_pivot_identity: str
    broken_pivot_level: float
    opposing_pivot_identity: str | None
    opposing_pivot_level: float | None
    started_at: datetime
    terminal_at: datetime
    terminal_reason: str
    m5_atr14: float


@dataclass(frozen=True, slots=True)
class M5ActivationEntryIntentV4:
    identity: str
    activation_identity: str
    family: EntryFamilyV4
    direction: Direction
    order_at: datetime
    expires_at: datetime
    triggered_at: datetime | None
    entry_reference: float | None
    stop: float | None
    state: Literal["TRIGGERED", "PENDING", "EXPIRED", "INVALID_GEOMETRY"]


@dataclass(frozen=True, slots=True)
class LiquidityResponseM5StateStudyV4:
    ruleset: str
    config: LiquidityResponseM5StateV4Config
    locations: tuple[LiquidityLocationEpisodeV4, ...]
    breaks: tuple[CausalM5BreakV4, ...]
    activations: tuple[M5ActivationStateV4, ...]
    entry_intents: tuple[M5ActivationEntryIntentV4, ...]


def build_liquidity_response_m5_state_study_v4(
    bars_by_timeframe: Mapping[str, Sequence[AggregateBar]],
    *,
    cutoff: datetime | None = None,
    config: LiquidityResponseM5StateV4Config | None = None,
) -> LiquidityResponseM5StateStudyV4:
    active = config or LiquidityResponseM5StateV4Config()
    _validate_config(active)
    required = {"1m", "5m", "15m", "1h", "4h"}
    if not required.issubset(bars_by_timeframe):
        raise ValueError(f"Missing timeframes: {sorted(required - set(bars_by_timeframe))}")
    normalized = {
        timeframe: _canonical_bars(bars_by_timeframe[timeframe], cutoff)
        for timeframe in required
    }
    v2 = build_liquidity_shift_study_v2(
        normalized,
        cutoff=cutoff,
        config=LiquidityShiftV2Config(maximum_stop_m15_atr=6.5),
    )
    zone_by_id = {item.identity: item for item in v2.zones}
    locations: list[LiquidityLocationEpisodeV4] = []
    for contact in v2.contacts:
        zone = zone_by_id[contact.zone_identity]
        elapsed_terminal = contact.reaction_at + timedelta(
            hours=active.maximum_location_hours
        )
        terminal = min(zone.terminal_at, elapsed_terminal)
        if terminal <= contact.reaction_at:
            continue
        locations.append(
            LiquidityLocationEpisodeV4(
                identity=_identity(
                    "LOCATION_V4", contact.identity, contact.reaction_at.isoformat()
                ),
                zone_identity=zone.identity,
                contact_identity=contact.identity,
                zone_timeframe=zone.timeframe,
                direction=zone.direction,
                started_at=contact.reaction_at,
                terminal_at=terminal,
                terminal_reason=(
                    "SOURCE_ZONE_TERMINAL"
                    if zone.terminal_at <= elapsed_terminal
                    else "MAXIMUM_36_HOURS"
                ),
            )
        )
    locations.sort(key=lambda item: (item.started_at, item.identity))
    m5_atrs = _rolling_atr(normalized["5m"], 14, active.tick_size)
    breaks = _causal_breaks(
        normalized["5m"], v2.pivots["5m"], m5_atrs, active
    )
    raw_activations: list[M5ActivationStateV4] = []
    for location in locations:
        same_direction = [
            event
            for event in breaks
            if event.direction == location.direction
            and location.started_at <= event.detected_at < location.terminal_at
        ]
        opposite = [
            event
            for event in breaks
            if event.direction != location.direction
            and location.started_at <= event.detected_at < location.terminal_at
        ]
        for event in same_direction:
            elapsed_terminal = event.detected_at + timedelta(
                hours=active.maximum_activation_hours
            )
            opposite_at = next(
                (
                    item.detected_at
                    for item in opposite
                    if event.detected_at < item.detected_at < elapsed_terminal
                ),
                None,
            )
            terminal = min(
                elapsed_terminal,
                location.terminal_at,
                opposite_at or elapsed_terminal,
            )
            reason = (
                "OPPOSITE_M5_BREAK"
                if opposite_at is not None and terminal == opposite_at
                else "LOCATION_TERMINAL"
                if terminal == location.terminal_at
                else "MAXIMUM_4_HOURS"
            )
            raw_activations.append(
                M5ActivationStateV4(
                    identity=_identity(
                        "ACTIVATION_V4",
                        location.identity,
                        event.identity,
                        terminal.isoformat(),
                    ),
                    location_identity=location.identity,
                    zone_identity=location.zone_identity,
                    zone_timeframe=location.zone_timeframe,
                    direction=event.direction,
                    broken_pivot_identity=event.pivot_identity,
                    broken_pivot_level=event.pivot_level,
                    opposing_pivot_identity=event.opposing_pivot_identity,
                    opposing_pivot_level=event.opposing_pivot_level,
                    started_at=event.detected_at,
                    terminal_at=terminal,
                    terminal_reason=reason,
                    m5_atr14=event.atr14,
                )
            )
    activations = _deduplicate_activations(raw_activations)
    m1_opens = [item.open_time.astimezone(UTC) for item in normalized["1m"]]
    observation_end = (
        normalized["1m"][-1].close_time.astimezone(UTC)
        if normalized["1m"]
        else datetime.min.replace(tzinfo=UTC)
    )
    intents: list[M5ActivationEntryIntentV4] = []
    for activation in activations:
        intents.extend(
            _entry_intents(
                activation,
                normalized["1m"],
                m1_opens,
                observation_end,
                active,
            )
        )
    intents.sort(key=lambda item: (item.order_at, item.family, item.identity))
    return LiquidityResponseM5StateStudyV4(
        ruleset=LIQUIDITY_RESPONSE_M5_STATE_V4_RULESET,
        config=active,
        locations=tuple(locations),
        breaks=tuple(breaks),
        activations=tuple(activations),
        entry_intents=tuple(intents),
    )


def _validate_config(config: LiquidityResponseM5StateV4Config) -> None:
    if config.maximum_location_hours < 1 or config.maximum_activation_hours < 1:
        raise ValueError("State durations must be positive")
    if config.break_buffer_ticks < 1 or config.tick_size <= 0:
        raise ValueError("Tick configuration must be positive")
    if config.stop_buffer_m5_atr <= 0:
        raise ValueError("Stop buffer must be positive")


def _canonical_bars(
    values: Sequence[AggregateBar], cutoff: datetime | None
) -> list[AggregateBar]:
    effective_cutoff = cutoff.astimezone(UTC) if cutoff is not None else None
    canonical: dict[datetime, AggregateBar] = {}
    for bar in sorted(values, key=lambda item: (item.open_time, item.close_time)):
        if effective_cutoff is not None and bar.close_time.astimezone(UTC) > effective_cutoff:
            continue
        canonical[bar.open_time.astimezone(UTC)] = bar
    return sorted(canonical.values(), key=lambda item: item.open_time)


def _rolling_atr(
    bars: Sequence[AggregateBar], window: int, tick_size: float
) -> list[float]:
    values = [_true_range_at(bars, index) for index in range(len(bars))]
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    output: list[float] = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        output.append(
            max((prefix[index + 1] - prefix[start]) / (index - start + 1), tick_size)
        )
    return output


def _causal_breaks(
    bars: Sequence[AggregateBar],
    pivots: Sequence[LiquidityPivotV2],
    atrs: Sequence[float],
    config: LiquidityResponseM5StateV4Config,
) -> list[CausalM5BreakV4]:
    available = sorted(pivots, key=lambda item: (item.detected_at, item.identity))
    pointer = 0
    latest: dict[str, LiquidityPivotV2] = {}
    used: set[tuple[Direction, str]] = set()
    output: list[CausalM5BreakV4] = []
    buffer = config.break_buffer_ticks * config.tick_size
    for index, bar in enumerate(bars):
        while pointer < len(available) and available[pointer].detected_at <= bar.open_time:
            pivot = available[pointer]
            current = latest.get(pivot.kind)
            if current is None or (pivot.pivot_at, pivot.detected_at) > (
                current.pivot_at,
                current.detected_at,
            ):
                latest[pivot.kind] = pivot
            pointer += 1
        for direction, kind, opposing_kind in (
            ("BULLISH", "HIGH", "LOW"),
            ("BEARISH", "LOW", "HIGH"),
        ):
            pivot = latest.get(kind)
            if pivot is None or (direction, pivot.identity) in used:
                continue
            margin = (
                bar.close - pivot.level
                if direction == "BULLISH"
                else pivot.level - bar.close
            )
            if margin < buffer:
                continue
            opposing = latest.get(opposing_kind)
            output.append(
                CausalM5BreakV4(
                    identity=_identity(
                        "M5_BREAK_V4", direction, pivot.identity, bar.close_time.isoformat()
                    ),
                    direction=direction,
                    pivot_identity=pivot.identity,
                    pivot_level=round(pivot.level, 8),
                    detected_at=bar.close_time.astimezone(UTC),
                    close=round(bar.close, 8),
                    atr14=round(atrs[index], 8),
                    break_margin_atr=round(margin / max(atrs[index], config.tick_size), 8),
                    opposing_pivot_identity=opposing.identity if opposing else None,
                    opposing_pivot_level=(round(opposing.level, 8) if opposing else None),
                )
            )
            used.add((direction, pivot.identity))
    return output


def _deduplicate_activations(
    values: Sequence[M5ActivationStateV4],
) -> list[M5ActivationStateV4]:
    priority = {"4h": 3, "1h": 2, "15m": 1}
    selected: dict[tuple[datetime, Direction, str], M5ActivationStateV4] = {}
    for item in values:
        key = (item.started_at, item.direction, item.broken_pivot_identity)
        current = selected.get(key)
        if current is None:
            selected[key] = item
            continue
        candidate_rank = (priority[item.zone_timeframe], item.location_identity)
        current_rank = (priority[current.zone_timeframe], current.location_identity)
        if candidate_rank > current_rank:
            selected[key] = item
    return sorted(selected.values(), key=lambda item: (item.started_at, item.identity))


def _entry_intents(
    activation: M5ActivationStateV4,
    m1: Sequence[AggregateBar],
    opens: Sequence[datetime],
    observation_end: datetime,
    config: LiquidityResponseM5StateV4Config,
) -> list[M5ActivationEntryIntentV4]:
    if activation.opposing_pivot_level is None:
        stop = None
    else:
        buffer = max(config.stop_buffer_m5_atr * activation.m5_atr14, 2 * config.tick_size)
        stop = (
            activation.opposing_pivot_level - buffer
            if activation.direction == "BULLISH"
            else activation.opposing_pivot_level + buffer
        )
    market_bar = _next_m1(m1, opens, activation.started_at, activation.terminal_at)
    market_at = market_bar.open_time.astimezone(UTC) if market_bar is not None else None
    market_entry = market_bar.open if market_bar is not None else None
    market_state = _intent_state(
        activation.direction,
        market_entry,
        stop,
        market_at,
        activation.terminal_at,
        observation_end,
    )
    retest_at = _first_m1_touch(
        m1,
        opens,
        activation.started_at,
        activation.terminal_at,
        activation.broken_pivot_level,
    )
    retest_state = _intent_state(
        activation.direction,
        activation.broken_pivot_level,
        stop,
        retest_at,
        activation.terminal_at,
        observation_end,
    )
    return [
        M5ActivationEntryIntentV4(
            identity=_identity("ENTRY_V4", activation.identity, "M5_BREAK_NEXT_M1_V4"),
            activation_identity=activation.identity,
            family="M5_BREAK_NEXT_M1_V4",
            direction=activation.direction,
            order_at=activation.started_at,
            expires_at=activation.terminal_at,
            triggered_at=market_at,
            entry_reference=round(market_entry, 8) if market_entry is not None else None,
            stop=round(stop, 8) if stop is not None else None,
            state=market_state,
        ),
        M5ActivationEntryIntentV4(
            identity=_identity(
                "ENTRY_V4", activation.identity, "M5_BROKEN_PIVOT_RETEST_V4"
            ),
            activation_identity=activation.identity,
            family="M5_BROKEN_PIVOT_RETEST_V4",
            direction=activation.direction,
            order_at=activation.started_at,
            expires_at=activation.terminal_at,
            triggered_at=retest_at,
            entry_reference=activation.broken_pivot_level,
            stop=round(stop, 8) if stop is not None else None,
            state=retest_state,
        ),
    ]


def _intent_state(
    direction: Direction,
    entry: float | None,
    stop: float | None,
    triggered_at: datetime | None,
    expires_at: datetime,
    observation_end: datetime,
) -> Literal["TRIGGERED", "PENDING", "EXPIRED", "INVALID_GEOMETRY"]:
    if entry is None or stop is None:
        return "INVALID_GEOMETRY"
    risk = entry - stop if direction == "BULLISH" else stop - entry
    if risk <= 0:
        return "INVALID_GEOMETRY"
    if triggered_at is not None:
        return "TRIGGERED"
    return "EXPIRED" if expires_at <= observation_end else "PENDING"


def _next_m1(
    m1: Sequence[AggregateBar],
    opens: Sequence[datetime],
    start: datetime,
    end: datetime,
) -> AggregateBar | None:
    index = bisect.bisect_left(opens, start)
    if index >= len(m1):
        return None
    return m1[index] if m1[index].open_time.astimezone(UTC) < end else None


def _first_m1_touch(
    m1: Sequence[AggregateBar],
    opens: Sequence[datetime],
    start: datetime,
    end: datetime,
    level: float,
) -> datetime | None:
    index = bisect.bisect_left(opens, start)
    stop = bisect.bisect_left(opens, end)
    for bar in m1[index:stop]:
        if bar.low <= level <= bar.high:
            return bar.open_time.astimezone(UTC)
    return None


def _true_range_at(bars: Sequence[AggregateBar], index: int) -> float:
    bar = bars[index]
    if index == 0:
        return bar.high - bar.low
    previous = bars[index - 1].close
    return max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous))


def _identity(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
