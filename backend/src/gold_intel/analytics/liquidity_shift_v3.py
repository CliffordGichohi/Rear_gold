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
    LiquidityTransitionV2,
    build_liquidity_shift_study_v2,
)
from gold_intel.analytics.structure import AggregateBar

PERSISTENT_LIQUIDITY_SHIFT_V3_RULESET = (
    "gold-persistent-liquidity-shift-auction-state-v3"
)
EntryFamilyV3 = Literal[
    "STATE_M5_HALF_RETRACE_LIMIT_V3",
    "STATE_M5_RETEST_CONFIRMATION_V3",
]


@dataclass(frozen=True, slots=True)
class PersistentLiquidityShiftV3Config:
    maximum_state_hours: int = 36
    opposite_transition_range_atr: float = 0.90
    opposite_transition_body_ratio: float = 0.55
    opposite_transition_break_buffer_atr: float = 0.05
    m5_impulse_range_atr: float = 0.80
    m5_impulse_body_ratio: float = 0.55
    m5_impulse_break_buffer_atr: float = 0.05
    m5_origin_lookback_bars: int = 4
    retracement_min: float = 0.382
    retracement_max: float = 0.786
    limit_retracement: float = 0.50
    entry_expiry_m5_bars: int = 12
    confirmation_body_ratio: float = 0.55
    confirmation_break_prior_m5_bars: int = 2
    stop_buffer_m5_atr: float = 0.10
    minimum_stop_m15_atr: float = 0.10
    maximum_stop_m15_atr: float = 6.50
    tick_size: float = 0.01


@dataclass(frozen=True, slots=True)
class PersistentAuctionStateV3:
    identity: str
    transition_identity: str
    source_zone_identity: str
    source_zone_timeframe: str
    direction: Direction
    started_at: datetime
    terminal_at: datetime
    terminal_reason: str
    transition_m15_atr14: float


@dataclass(frozen=True, slots=True)
class M5ContinuationImpulseV3:
    identity: str
    state_identity: str
    direction: Direction
    origin_at: datetime
    detected_at: datetime
    broken_pivot_identity: str
    impulse_atr14: float
    origin_extreme: float
    impulse_close: float
    retracement_lower: float
    retracement_upper: float
    half_retrace: float


@dataclass(frozen=True, slots=True)
class PersistentEntryIntentV3:
    identity: str
    state_identity: str
    impulse_identity: str
    family: EntryFamilyV3
    direction: Direction
    order_at: datetime
    expires_at: datetime
    triggered_at: datetime | None
    entry_reference: float
    stop: float
    stop_distance_m15_atr: float
    state: Literal["PENDING", "TRIGGERED", "EXPIRED", "INVALID_GEOMETRY"]


@dataclass(frozen=True, slots=True)
class PersistentLiquidityShiftStudyV3:
    ruleset: str
    config: PersistentLiquidityShiftV3Config
    states: tuple[PersistentAuctionStateV3, ...]
    impulses: tuple[M5ContinuationImpulseV3, ...]
    entry_intents: tuple[PersistentEntryIntentV3, ...]


def build_persistent_liquidity_shift_study_v3(
    bars_by_timeframe: Mapping[str, Sequence[AggregateBar]],
    *,
    cutoff: datetime | None = None,
    config: PersistentLiquidityShiftV3Config | None = None,
) -> PersistentLiquidityShiftStudyV3:
    active = config or PersistentLiquidityShiftV3Config()
    _validate_config(active)
    v2 = build_liquidity_shift_study_v2(
        bars_by_timeframe,
        cutoff=cutoff,
        config=LiquidityShiftV2Config(maximum_stop_m15_atr=6.5),
    )
    normalized = {
        timeframe: _canonical_bars(values, cutoff)
        for timeframe, values in bars_by_timeframe.items()
        if timeframe in {"1m", "5m", "15m", "1h", "4h"}
    }
    m15_atr = _rolling_atr(normalized["15m"], 14, active.tick_size)
    m5_atr = _rolling_atr(normalized["5m"], 14, active.tick_size)
    zone_by_id = {item.identity: item for item in v2.zones}
    selected_transitions: dict[tuple[datetime, Direction], LiquidityTransitionV2] = {}
    priority = {"4h": 3, "1h": 2, "15m": 1}
    for transition in v2.transitions:
        key = (transition.transition_at, transition.direction)
        current = selected_transitions.get(key)
        if current is None:
            selected_transitions[key] = transition
            continue
        current_zone = zone_by_id[current.zone_identity]
        candidate_zone = zone_by_id[transition.zone_identity]
        if priority[candidate_zone.timeframe] > priority[current_zone.timeframe]:
            selected_transitions[key] = transition

    states: list[PersistentAuctionStateV3] = []
    for transition in sorted(
        selected_transitions.values(),
        key=lambda item: (item.transition_at, item.identity),
    ):
        zone = zone_by_id[transition.zone_identity]
        natural_end = min(
            zone.terminal_at,
            transition.transition_at + timedelta(hours=active.maximum_state_hours),
        )
        opposite_at = _first_opposite_m15_transition(
            direction=transition.direction,
            started_at=transition.transition_at,
            natural_end=natural_end,
            m15=normalized["15m"],
            pivots=v2.pivots["15m"],
            atrs=m15_atr,
            config=active,
        )
        terminal_at = opposite_at or natural_end
        terminal_reason = (
            "OPPOSITE_M15_TRANSITION"
            if opposite_at is not None
            else "SOURCE_ZONE_TERMINAL"
            if zone.terminal_at
            <= transition.transition_at + timedelta(hours=active.maximum_state_hours)
            else "MAXIMUM_36_HOURS"
        )
        states.append(
            PersistentAuctionStateV3(
                identity=_identity(
                    "AUCTION_STATE_V3",
                    transition.identity,
                    terminal_at.isoformat(),
                ),
                transition_identity=transition.identity,
                source_zone_identity=zone.identity,
                source_zone_timeframe=zone.timeframe,
                direction=transition.direction,
                started_at=transition.transition_at,
                terminal_at=terminal_at,
                terminal_reason=terminal_reason,
                transition_m15_atr14=transition.transition_atr14,
            )
        )
    states.sort(key=lambda item: (item.started_at, item.direction, item.identity))

    impulses: list[M5ContinuationImpulseV3] = []
    for state in states:
        impulses.extend(
            _m5_impulses_in_state(
                state,
                normalized["5m"],
                v2.pivots["5m"],
                m5_atr,
                active,
            )
        )
    impulses = _deduplicate_impulses(impulses)
    state_by_id = {item.identity: item for item in states}
    m1_opens = [item.open_time.astimezone(UTC) for item in normalized["1m"]]
    m5_closes = [item.close_time.astimezone(UTC) for item in normalized["5m"]]
    intents: list[PersistentEntryIntentV3] = []
    for impulse in impulses:
        intents.extend(
            _entry_intents(
                impulse,
                state_by_id[impulse.state_identity],
                normalized["1m"],
                m1_opens,
                normalized["5m"],
                m5_closes,
                active,
            )
        )
    intents.sort(key=lambda item: (item.order_at, item.family, item.identity))
    return PersistentLiquidityShiftStudyV3(
        ruleset=PERSISTENT_LIQUIDITY_SHIFT_V3_RULESET,
        config=active,
        states=tuple(states),
        impulses=tuple(impulses),
        entry_intents=tuple(intents),
    )


def _validate_config(config: PersistentLiquidityShiftV3Config) -> None:
    if config.maximum_state_hours < 1 or config.m5_origin_lookback_bars < 1:
        raise ValueError("State hours and origin lookback must be positive")
    if config.entry_expiry_m5_bars < 1 or config.confirmation_break_prior_m5_bars < 1:
        raise ValueError("Entry bar counts must be positive")
    ratios = (
        config.opposite_transition_body_ratio,
        config.m5_impulse_body_ratio,
        config.retracement_min,
        config.retracement_max,
        config.limit_retracement,
        config.confirmation_body_ratio,
    )
    if any(not 0 < value < 1 for value in ratios):
        raise ValueError("Ratios must lie inside (0, 1)")
    if not config.retracement_min < config.limit_retracement < config.retracement_max:
        raise ValueError("Half retrace must lie inside the retracement band")
    if config.minimum_stop_m15_atr >= config.maximum_stop_m15_atr:
        raise ValueError("Stop bounds are invalid")


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
    ranges = [_true_range_at(bars, index) for index in range(len(bars))]
    prefix = [0.0]
    for value in ranges:
        prefix.append(prefix[-1] + value)
    output: list[float] = []
    for index in range(len(ranges)):
        start = max(0, index - window + 1)
        output.append(max((prefix[index + 1] - prefix[start]) / (index - start + 1), tick_size))
    return output


def _first_opposite_m15_transition(
    *,
    direction: Direction,
    started_at: datetime,
    natural_end: datetime,
    m15: Sequence[AggregateBar],
    pivots: Sequence[LiquidityPivotV2],
    atrs: Sequence[float],
    config: PersistentLiquidityShiftV3Config,
) -> datetime | None:
    closes = [item.close_time.astimezone(UTC) for item in m15]
    start = bisect.bisect_right(closes, started_at)
    stop = bisect.bisect_right(closes, natural_end)
    opposite: Direction = "BEARISH" if direction == "BULLISH" else "BULLISH"
    kind = "LOW" if opposite == "BEARISH" else "HIGH"
    for index in range(start, stop):
        bar = m15[index]
        known = [
            item
            for item in pivots
            if item.kind == kind and item.detected_at <= bar.open_time and item.index < index
        ]
        if not known:
            continue
        pivot = max(known, key=lambda item: (item.pivot_at, item.detected_at))
        atr = atrs[index]
        bar_range = max(bar.high - bar.low, config.tick_size)
        aligned = bar.close < bar.open if opposite == "BEARISH" else bar.close > bar.open
        broke = (
            bar.close < pivot.level - config.opposite_transition_break_buffer_atr * atr
            if opposite == "BEARISH"
            else bar.close > pivot.level + config.opposite_transition_break_buffer_atr * atr
        )
        if (
            aligned
            and broke
            and abs(bar.close - bar.open) / bar_range
            >= config.opposite_transition_body_ratio
            and _true_range_at(m15, index) / atr >= config.opposite_transition_range_atr
        ):
            return bar.close_time.astimezone(UTC)
    return None


def _m5_impulses_in_state(
    state: PersistentAuctionStateV3,
    m5: Sequence[AggregateBar],
    pivots: Sequence[LiquidityPivotV2],
    atrs: Sequence[float],
    config: PersistentLiquidityShiftV3Config,
) -> list[M5ContinuationImpulseV3]:
    closes = [item.close_time.astimezone(UTC) for item in m5]
    start = bisect.bisect_right(closes, state.started_at)
    stop = bisect.bisect_right(closes, state.terminal_at)
    kind = "HIGH" if state.direction == "BULLISH" else "LOW"
    used: set[str] = set()
    output: list[M5ContinuationImpulseV3] = []
    for index in range(max(start, config.m5_origin_lookback_bars), stop):
        bar = m5[index]
        atr = atrs[index]
        bar_range = max(bar.high - bar.low, config.tick_size)
        aligned = bar.close > bar.open if state.direction == "BULLISH" else bar.close < bar.open
        if (
            not aligned
            or _true_range_at(m5, index) / atr < config.m5_impulse_range_atr
            or abs(bar.close - bar.open) / bar_range < config.m5_impulse_body_ratio
        ):
            continue
        known = [
            item
            for item in pivots
            if item.kind == kind
            and item.detected_at <= bar.open_time
            and item.index < index
            and item.identity not in used
        ]
        if not known:
            continue
        pivot = max(known, key=lambda item: (item.pivot_at, item.detected_at))
        buffer = max(config.m5_impulse_break_buffer_atr * atr, 2 * config.tick_size)
        broke = (
            bar.close > pivot.level + buffer
            if state.direction == "BULLISH"
            else bar.close < pivot.level - buffer
        )
        if not broke:
            continue
        origins = m5[index - config.m5_origin_lookback_bars : index]
        origin = next(
            (
                item
                for item in reversed(origins)
                if (item.close < item.open if state.direction == "BULLISH" else item.close > item.open)
            ),
            None,
        )
        if origin is None:
            continue
        origin_extreme = origin.low if state.direction == "BULLISH" else origin.high
        distance = (
            bar.close - origin_extreme
            if state.direction == "BULLISH"
            else origin_extreme - bar.close
        )
        if distance <= 4 * config.tick_size:
            continue
        if state.direction == "BULLISH":
            first = bar.close - config.retracement_max * distance
            second = bar.close - config.retracement_min * distance
            half = bar.close - config.limit_retracement * distance
        else:
            first = bar.close + config.retracement_min * distance
            second = bar.close + config.retracement_max * distance
            half = bar.close + config.limit_retracement * distance
        used.add(pivot.identity)
        output.append(
            M5ContinuationImpulseV3(
                identity=_identity("M5_IMPULSE_V3", state.identity, pivot.identity, bar.close_time.isoformat()),
                state_identity=state.identity,
                direction=state.direction,
                origin_at=origin.open_time.astimezone(UTC),
                detected_at=bar.close_time.astimezone(UTC),
                broken_pivot_identity=pivot.identity,
                impulse_atr14=round(atr, 8),
                origin_extreme=round(origin_extreme, 8),
                impulse_close=round(bar.close, 8),
                retracement_lower=round(min(first, second), 8),
                retracement_upper=round(max(first, second), 8),
                half_retrace=round(half, 8),
            )
        )
    return output


def _deduplicate_impulses(
    impulses: Sequence[M5ContinuationImpulseV3],
) -> list[M5ContinuationImpulseV3]:
    state_priority: dict[tuple[datetime, Direction, str], M5ContinuationImpulseV3] = {}
    for item in impulses:
        key = (item.detected_at, item.direction, item.broken_pivot_identity)
        current = state_priority.get(key)
        if current is None or item.state_identity < current.state_identity:
            state_priority[key] = item
    return sorted(state_priority.values(), key=lambda item: (item.detected_at, item.identity))


def _entry_intents(
    impulse: M5ContinuationImpulseV3,
    state: PersistentAuctionStateV3,
    m1: Sequence[AggregateBar],
    m1_opens: Sequence[datetime],
    m5: Sequence[AggregateBar],
    m5_closes: Sequence[datetime],
    config: PersistentLiquidityShiftV3Config,
) -> list[PersistentEntryIntentV3]:
    expires_at = min(
        state.terminal_at,
        impulse.detected_at + timedelta(minutes=5 * config.entry_expiry_m5_bars),
    )
    stop_buffer = max(config.stop_buffer_m5_atr * impulse.impulse_atr14, 2 * config.tick_size)
    limit_stop = (
        impulse.origin_extreme - stop_buffer
        if impulse.direction == "BULLISH"
        else impulse.origin_extreme + stop_buffer
    )
    limit_trigger = _first_m1_touch(
        m1, m1_opens, impulse.detected_at, expires_at, impulse.half_retrace
    )
    observation_end = m1[-1].close_time.astimezone(UTC) if m1 else impulse.detected_at
    limit_state, limit_distance = _state(
        impulse.direction,
        impulse.half_retrace,
        limit_stop,
        state.transition_m15_atr14,
        limit_trigger,
        expires_at,
        observation_end,
        config,
    )
    output = [
        PersistentEntryIntentV3(
            identity=_identity("ENTRY_V3", impulse.identity, "STATE_M5_HALF_RETRACE_LIMIT_V3"),
            state_identity=state.identity,
            impulse_identity=impulse.identity,
            family="STATE_M5_HALF_RETRACE_LIMIT_V3",
            direction=impulse.direction,
            order_at=impulse.detected_at,
            expires_at=expires_at,
            triggered_at=limit_trigger,
            entry_reference=impulse.half_retrace,
            stop=round(limit_stop, 8),
            stop_distance_m15_atr=round(limit_distance, 6),
            state=limit_state,
        )
    ]
    confirmation = _confirmation(
        impulse,
        m5,
        m5_closes,
        m1,
        m1_opens,
        expires_at,
        config,
    )
    if confirmation is None:
        confirmation_at = None
        confirmation_entry = impulse.impulse_close
        confirmation_stop = limit_stop
    else:
        confirmation_at, confirmation_entry, pullback_extreme = confirmation
        confirmation_stop = (
            pullback_extreme - stop_buffer
            if impulse.direction == "BULLISH"
            else pullback_extreme + stop_buffer
        )
    confirmation_state, confirmation_distance = _state(
        impulse.direction,
        confirmation_entry,
        confirmation_stop,
        state.transition_m15_atr14,
        confirmation_at,
        expires_at,
        observation_end,
        config,
    )
    output.append(
        PersistentEntryIntentV3(
            identity=_identity("ENTRY_V3", impulse.identity, "STATE_M5_RETEST_CONFIRMATION_V3"),
            state_identity=state.identity,
            impulse_identity=impulse.identity,
            family="STATE_M5_RETEST_CONFIRMATION_V3",
            direction=impulse.direction,
            order_at=impulse.detected_at,
            expires_at=expires_at,
            triggered_at=confirmation_at,
            entry_reference=round(confirmation_entry, 8),
            stop=round(confirmation_stop, 8),
            stop_distance_m15_atr=round(confirmation_distance, 6),
            state=confirmation_state,
        )
    )
    return output


def _confirmation(
    impulse: M5ContinuationImpulseV3,
    m5: Sequence[AggregateBar],
    closes: Sequence[datetime],
    m1: Sequence[AggregateBar],
    m1_opens: Sequence[datetime],
    expires_at: datetime,
    config: PersistentLiquidityShiftV3Config,
) -> tuple[datetime, float, float] | None:
    start = bisect.bisect_right(closes, impulse.detected_at)
    stop = bisect.bisect_right(closes, expires_at)
    pullback_seen = False
    pullback_extreme: float | None = None
    for index in range(start, stop):
        bar = m5[index]
        if bar.low <= impulse.retracement_upper and bar.high >= impulse.retracement_lower:
            pullback_seen = True
        if pullback_seen:
            pullback_extreme = (
                min(pullback_extreme if pullback_extreme is not None else bar.low, bar.low)
                if impulse.direction == "BULLISH"
                else max(pullback_extreme if pullback_extreme is not None else bar.high, bar.high)
            )
        if not pullback_seen or index < config.confirmation_break_prior_m5_bars:
            continue
        bar_range = max(bar.high - bar.low, config.tick_size)
        aligned = bar.close > bar.open if impulse.direction == "BULLISH" else bar.close < bar.open
        prior = m5[index - config.confirmation_break_prior_m5_bars : index]
        broke = (
            bar.close > max(item.high for item in prior)
            if impulse.direction == "BULLISH"
            else bar.close < min(item.low for item in prior)
        )
        invalid = (
            bar.close < impulse.origin_extreme
            if impulse.direction == "BULLISH"
            else bar.close > impulse.origin_extreme
        )
        if invalid:
            return None
        if aligned and broke and abs(bar.close - bar.open) / bar_range >= config.confirmation_body_ratio:
            next_minute = _next_m1(m1, m1_opens, bar.close_time.astimezone(UTC), expires_at)
            if next_minute is None:
                return None
            return next_minute.open_time.astimezone(UTC), next_minute.open, float(pullback_extreme)
    return None


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


def _state(
    direction: Direction,
    entry: float,
    stop: float,
    m15_atr: float,
    triggered_at: datetime | None,
    expires_at: datetime,
    observation_end: datetime,
    config: PersistentLiquidityShiftV3Config,
) -> tuple[Literal["PENDING", "TRIGGERED", "EXPIRED", "INVALID_GEOMETRY"], float]:
    risk = entry - stop if direction == "BULLISH" else stop - entry
    distance = risk / max(m15_atr, config.tick_size)
    if risk <= 0 or not config.minimum_stop_m15_atr <= distance <= config.maximum_stop_m15_atr:
        return "INVALID_GEOMETRY", distance
    if triggered_at is not None:
        return "TRIGGERED", distance
    if expires_at <= observation_end:
        return "EXPIRED", distance
    return "PENDING", distance


def _true_range_at(bars: Sequence[AggregateBar], index: int) -> float:
    bar = bars[index]
    if index == 0:
        return bar.high - bar.low
    previous = bars[index - 1].close
    return max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous))


def _identity(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
