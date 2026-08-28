from __future__ import annotations

import bisect
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from gold_intel.analytics.structure import AggregateBar

LIQUIDITY_SHIFT_V2_RULESET = "gold-hierarchical-liquidity-shift-v2"
Direction = Literal["BULLISH", "BEARISH"]
PivotKind = Literal["HIGH", "LOW"]
EntryFamily = Literal[
    "SHIFT_HALF_RETRACE_LIMIT_V2",
    "SHIFT_M5_STRUCTURE_CONFIRMATION_V2",
]


@dataclass(frozen=True, slots=True)
class LiquidityShiftV2Config:
    pivot_left: int = 2
    pivot_right: int = 2
    atr_window: int = 14
    pivot_prominence_atr: float = 0.25
    zone_displacement_atr: float = 1.25
    zone_body_ratio: float = 0.60
    zone_break_buffer_atr: float = 0.05
    zone_origin_lookback_bars: int = 6
    zone_invalidation_buffer_atr: float = 0.10
    zone_expiry_calendar_days: int = 45
    minimum_zone_age_minutes: int = 30
    maximum_contact_episodes: int = 2
    contact_separation_m5_bars: int = 12
    reaction_m5_bars: int = 3
    transition_m15_bars: int = 16
    transition_range_atr: float = 0.90
    transition_body_ratio: float = 0.55
    transition_break_buffer_atr: float = 0.05
    retracement_min: float = 0.382
    retracement_max: float = 0.786
    limit_retracement: float = 0.50
    entry_expiry_m5_bars: int = 12
    confirmation_body_ratio: float = 0.55
    confirmation_break_prior_m5_bars: int = 2
    stop_buffer_m15_atr: float = 0.10
    minimum_stop_m15_atr: float = 0.10
    maximum_stop_m15_atr: float = 1.50
    tick_size: float = 0.01


@dataclass(frozen=True, slots=True)
class LiquidityPivotV2:
    identity: str
    timeframe: str
    kind: PivotKind
    pivot_at: datetime
    detected_at: datetime
    level: float
    atr14: float
    prominence_atr: float
    index: int


@dataclass(frozen=True, slots=True)
class LiquidityShiftZoneV2:
    identity: str
    timeframe: str
    direction: Direction
    origin_at: datetime
    detected_at: datetime
    lower_bound: float
    upper_bound: float
    midpoint: float
    broken_pivot_identity: str
    creation_atr14: float
    invalidated_at: datetime | None
    expires_at: datetime
    terminal_at: datetime
    epistemic_status: Literal["INFERRED"] = "INFERRED"


@dataclass(frozen=True, slots=True)
class LiquidityContactV2:
    identity: str
    zone_identity: str
    direction: Direction
    episode: int
    contact_at: datetime
    reaction_at: datetime
    contact_extreme: float


@dataclass(frozen=True, slots=True)
class LiquidityTransitionV2:
    identity: str
    zone_identity: str
    contact_identity: str
    direction: Direction
    transition_at: datetime
    broken_m15_pivot_identity: str
    broken_m15_level: float
    contact_extreme: float
    transition_close: float
    transition_atr14: float
    retracement_lower: float
    retracement_upper: float
    half_retrace: float


@dataclass(frozen=True, slots=True)
class LiquidityEntryIntentV2:
    identity: str
    transition_identity: str
    zone_identity: str
    zone_timeframe: str
    family: EntryFamily
    direction: Direction
    order_at: datetime
    expires_at: datetime
    triggered_at: datetime | None
    entry_reference: float
    stop: float
    stop_distance_atr: float
    state: Literal["PENDING", "TRIGGERED", "INVALID_GEOMETRY", "EXPIRED"]


@dataclass(frozen=True, slots=True)
class LiquidityShiftStudyV2:
    ruleset: str
    config: LiquidityShiftV2Config
    pivots: Mapping[str, tuple[LiquidityPivotV2, ...]]
    zones: tuple[LiquidityShiftZoneV2, ...]
    contacts: tuple[LiquidityContactV2, ...]
    transitions: tuple[LiquidityTransitionV2, ...]
    entry_intents: tuple[LiquidityEntryIntentV2, ...]


def build_liquidity_shift_study_v2(
    bars_by_timeframe: Mapping[str, Sequence[AggregateBar]],
    *,
    cutoff: datetime | None = None,
    config: LiquidityShiftV2Config | None = None,
) -> LiquidityShiftStudyV2:
    active = config or LiquidityShiftV2Config()
    _validate_config(active)
    required = {"1m", "5m", "15m", "1h", "4h"}
    if not required.issubset(bars_by_timeframe):
        raise ValueError(f"Missing timeframes: {sorted(required - set(bars_by_timeframe))}")
    normalized = {
        timeframe: _canonical_bars(values, cutoff)
        for timeframe, values in bars_by_timeframe.items()
        if timeframe in required
    }
    pivots = {
        timeframe: tuple(_confirmed_pivots(normalized[timeframe], timeframe, active))
        for timeframe in ("5m", "15m", "1h", "4h")
    }
    atrs = {
        timeframe: _rolling_atr(normalized[timeframe], active.atr_window, active.tick_size)
        for timeframe in ("5m", "15m", "1h", "4h")
    }
    zones: list[LiquidityShiftZoneV2] = []
    for timeframe in ("15m", "1h", "4h"):
        zones.extend(
            _shift_zones(
                normalized[timeframe],
                pivots[timeframe],
                atrs[timeframe],
                timeframe,
                active,
            )
        )
    zones.sort(key=lambda item: (item.detected_at, item.timeframe, item.identity))
    m1_opens = [item.open_time.astimezone(UTC) for item in normalized["1m"]]
    m5_opens = [item.open_time.astimezone(UTC) for item in normalized["5m"]]
    m5_closes = [item.close_time.astimezone(UTC) for item in normalized["5m"]]
    m15_closes = [item.close_time.astimezone(UTC) for item in normalized["15m"]]
    contacts: list[LiquidityContactV2] = []
    for zone in zones:
        contacts.extend(_zone_contacts(zone, normalized["5m"], m5_opens, active))
    contacts.sort(key=lambda item: (item.reaction_at, item.zone_identity, item.episode))
    transitions: list[LiquidityTransitionV2] = []
    zone_by_id = {zone.identity: zone for zone in zones}
    for contact in contacts:
        zone = zone_by_id[contact.zone_identity]
        transition = _transition_after_contact(
            zone,
            contact,
            normalized["15m"],
            m15_closes,
            pivots["15m"],
            atrs["15m"],
            active,
        )
        if transition is not None:
            transitions.append(transition)
    transitions.sort(key=lambda item: (item.transition_at, item.identity))
    intents: list[LiquidityEntryIntentV2] = []
    for transition in transitions:
        zone = zone_by_id[transition.zone_identity]
        intents.extend(
            _entry_intents(
                transition,
                zone,
                normalized["1m"],
                m1_opens,
                normalized["5m"],
                m5_closes,
                active,
            )
        )
    intents.sort(key=lambda item: (item.order_at, item.family, item.identity))
    return LiquidityShiftStudyV2(
        ruleset=LIQUIDITY_SHIFT_V2_RULESET,
        config=active,
        pivots=pivots,
        zones=tuple(zones),
        contacts=tuple(contacts),
        transitions=tuple(transitions),
        entry_intents=tuple(intents),
    )


def trend_state_at(
    pivots: Sequence[LiquidityPivotV2],
    at: datetime,
    *,
    tick_size: float = 0.01,
) -> str:
    known = [item for item in pivots if item.detected_at <= at]
    highs = [item for item in known if item.kind == "HIGH"][-2:]
    lows = [item for item in known if item.kind == "LOW"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return "UNKNOWN"
    highs_up = highs[-1].level > highs[-2].level + tick_size
    highs_down = highs[-1].level < highs[-2].level - tick_size
    lows_up = lows[-1].level > lows[-2].level + tick_size
    lows_down = lows[-1].level < lows[-2].level - tick_size
    if highs_up and lows_up:
        return "BULLISH"
    if highs_down and lows_down:
        return "BEARISH"
    return "MIXED_OR_RANGE"


def latest_swing_range_at(
    pivots: Sequence[LiquidityPivotV2], at: datetime
) -> tuple[float, float] | None:
    known = [item for item in pivots if item.detected_at <= at]
    highs = [item.level for item in known if item.kind == "HIGH"]
    lows = [item.level for item in known if item.kind == "LOW"]
    if not highs or not lows or highs[-1] <= lows[-1]:
        return None
    return lows[-1], highs[-1]


def _validate_config(config: LiquidityShiftV2Config) -> None:
    positive_ints = (
        config.pivot_left,
        config.pivot_right,
        config.atr_window,
        config.zone_origin_lookback_bars,
        config.maximum_contact_episodes,
        config.contact_separation_m5_bars,
        config.reaction_m5_bars,
        config.transition_m15_bars,
        config.entry_expiry_m5_bars,
    )
    if any(value < 1 for value in positive_ints):
        raise ValueError("Bar counts must be positive")
    ratios = (
        config.zone_body_ratio,
        config.transition_body_ratio,
        config.confirmation_body_ratio,
        config.retracement_min,
        config.retracement_max,
        config.limit_retracement,
    )
    if any(not 0 < value < 1 for value in ratios):
        raise ValueError("Body and retracement ratios must be inside (0, 1)")
    if not config.retracement_min < config.limit_retracement < config.retracement_max:
        raise ValueError("The limit retracement must lie inside the retracement band")
    if config.minimum_stop_m15_atr >= config.maximum_stop_m15_atr:
        raise ValueError("Stop ATR bounds are invalid")
    if config.tick_size <= 0:
        raise ValueError("tick_size must be positive")


def _canonical_bars(
    values: Sequence[AggregateBar], cutoff: datetime | None
) -> list[AggregateBar]:
    effective_cutoff = cutoff.astimezone(UTC) if cutoff is not None else None
    canonical: dict[datetime, AggregateBar] = {}
    for bar in sorted(values, key=lambda item: (item.open_time, item.close_time)):
        if bar.open_time.tzinfo is None or bar.close_time.tzinfo is None:
            raise ValueError("All bars must be timezone-aware")
        if effective_cutoff is not None and bar.close_time.astimezone(UTC) > effective_cutoff:
            continue
        if not (bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high):
            raise ValueError(f"Invalid OHLC at {bar.open_time.isoformat()}")
        canonical[bar.open_time.astimezone(UTC)] = bar
    return sorted(canonical.values(), key=lambda item: item.open_time)


def _true_ranges(bars: Sequence[AggregateBar]) -> list[float]:
    output: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            output.append(bar.high - bar.low)
        else:
            previous = bars[index - 1].close
            output.append(max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous)))
    return output


def _rolling_atr(
    bars: Sequence[AggregateBar], window: int, tick_size: float
) -> list[float]:
    true_ranges = _true_ranges(bars)
    prefix = [0.0]
    for value in true_ranges:
        prefix.append(prefix[-1] + value)
    return [
        max(
            (prefix[index + 1] - prefix[max(0, index - window + 1)])
            / (index - max(0, index - window + 1) + 1),
            tick_size,
        )
        for index in range(len(true_ranges))
    ]


def _confirmed_pivots(
    bars: Sequence[AggregateBar],
    timeframe: str,
    config: LiquidityShiftV2Config,
) -> list[LiquidityPivotV2]:
    if len(bars) < config.pivot_left + config.pivot_right + 1:
        return []
    atrs = _rolling_atr(bars, config.atr_window, config.tick_size)
    output: list[LiquidityPivotV2] = []
    for index in range(config.pivot_left, len(bars) - config.pivot_right):
        bar = bars[index]
        neighbors = (
            list(bars[index - config.pivot_left : index])
            + list(bars[index + 1 : index + config.pivot_right + 1])
        )
        atr = atrs[index]
        candidates: tuple[tuple[PivotKind, float, float], ...] = (
            ("HIGH", bar.high, bar.high - min(item.low for item in neighbors)),
            ("LOW", bar.low, max(item.high for item in neighbors) - bar.low),
        )
        for kind, level, prominence in candidates:
            strict = (
                all(level > item.high for item in neighbors)
                if kind == "HIGH"
                else all(level < item.low for item in neighbors)
            )
            if not strict or prominence < max(config.pivot_prominence_atr * atr, 2 * config.tick_size):
                continue
            detected_at = bars[index + config.pivot_right].close_time.astimezone(UTC)
            output.append(
                LiquidityPivotV2(
                    identity=_identity(
                        "PIVOT", timeframe, kind, bar.open_time.isoformat(), f"{level:.8f}", detected_at.isoformat()
                    ),
                    timeframe=timeframe,
                    kind=kind,
                    pivot_at=bar.open_time.astimezone(UTC),
                    detected_at=detected_at,
                    level=round(level, 8),
                    atr14=round(atr, 8),
                    prominence_atr=round(prominence / atr, 6),
                    index=index,
                )
            )
    return sorted(output, key=lambda item: (item.detected_at, item.kind, item.identity))


def _shift_zones(
    bars: Sequence[AggregateBar],
    pivots: Sequence[LiquidityPivotV2],
    atrs: Sequence[float],
    timeframe: str,
    config: LiquidityShiftV2Config,
) -> list[LiquidityShiftZoneV2]:
    used: set[str] = set()
    output: list[LiquidityShiftZoneV2] = []
    close_times = [item.close_time.astimezone(UTC) for item in bars]
    for index in range(config.atr_window, len(bars)):
        bar = bars[index]
        atr = atrs[index]
        bar_range = max(bar.high - bar.low, config.tick_size)
        body_ratio = abs(bar.close - bar.open) / bar_range
        true_range = _true_range_at(bars, index)
        if true_range / atr < config.zone_displacement_atr or body_ratio < config.zone_body_ratio:
            continue
        direction: Direction = "BULLISH" if bar.close > bar.open else "BEARISH"
        kind: PivotKind = "HIGH" if direction == "BULLISH" else "LOW"
        known = [
            item
            for item in pivots
            if item.kind == kind
            and item.index < index
            and item.detected_at <= bar.open_time
            and item.identity not in used
        ]
        if not known:
            continue
        broken = max(known, key=lambda item: item.index)
        break_buffer = max(config.zone_break_buffer_atr * atr, 2 * config.tick_size)
        if direction == "BULLISH" and bar.close <= broken.level + break_buffer:
            continue
        if direction == "BEARISH" and bar.close >= broken.level - break_buffer:
            continue
        origins = bars[max(0, index - config.zone_origin_lookback_bars) : index]
        origin = next(
            (
                item
                for item in reversed(origins)
                if (item.close < item.open if direction == "BULLISH" else item.close > item.open)
            ),
            None,
        )
        if origin is None:
            continue
        lower = origin.low if direction == "BULLISH" else min(origin.open, origin.close)
        upper = max(origin.open, origin.close) if direction == "BULLISH" else origin.high
        if upper - lower < config.tick_size:
            continue
        detected_at = bar.close_time.astimezone(UTC)
        expires_at = detected_at + timedelta(days=config.zone_expiry_calendar_days)
        invalidated_at: datetime | None = None
        invalidation_buffer = max(config.zone_invalidation_buffer_atr * atr, 2 * config.tick_size)
        scan_start = bisect.bisect_right(close_times, detected_at)
        scan_end = bisect.bisect_right(close_times, expires_at)
        for candidate in bars[scan_start:scan_end]:
            invalid = (
                candidate.close < lower - invalidation_buffer
                if direction == "BULLISH"
                else candidate.close > upper + invalidation_buffer
            )
            if invalid:
                invalidated_at = candidate.close_time.astimezone(UTC)
                break
        terminal_at = min(expires_at, invalidated_at) if invalidated_at else expires_at
        used.add(broken.identity)
        output.append(
            LiquidityShiftZoneV2(
                identity=_identity(
                    "SHIFT_ZONE_V2", timeframe, direction, origin.open_time.isoformat(), detected_at.isoformat(), broken.identity
                ),
                timeframe=timeframe,
                direction=direction,
                origin_at=origin.open_time.astimezone(UTC),
                detected_at=detected_at,
                lower_bound=round(lower, 8),
                upper_bound=round(upper, 8),
                midpoint=round((lower + upper) / 2, 8),
                broken_pivot_identity=broken.identity,
                creation_atr14=round(atr, 8),
                invalidated_at=invalidated_at,
                expires_at=expires_at,
                terminal_at=terminal_at,
            )
        )
    return output


def _zone_contacts(
    zone: LiquidityShiftZoneV2,
    m5: Sequence[AggregateBar],
    opens: Sequence[datetime],
    config: LiquidityShiftV2Config,
) -> list[LiquidityContactV2]:
    earliest = zone.detected_at + timedelta(minutes=config.minimum_zone_age_minutes)
    index = bisect.bisect_left(opens, earliest)
    stop = bisect.bisect_left(opens, zone.terminal_at)
    output: list[LiquidityContactV2] = []
    prior_episode_index: int | None = None
    in_overlap = False
    while index < stop and len(output) < config.maximum_contact_episodes:
        bar = m5[index]
        overlap = bar.low <= zone.upper_bound and bar.high >= zone.lower_bound
        eligible_new_episode = overlap and not in_overlap and (
            prior_episode_index is None
            or index - prior_episode_index >= config.contact_separation_m5_bars
        )
        if eligible_new_episode:
            reaction_end = min(stop, index + config.reaction_m5_bars)
            contact_slice = m5[index:reaction_end]
            reaction: AggregateBar | None = None
            reaction_offset = 0
            for offset, candidate in enumerate(contact_slice):
                accepted = (
                    candidate.close > zone.upper_bound
                    if zone.direction == "BULLISH"
                    else candidate.close < zone.lower_bound
                )
                if accepted:
                    reaction = candidate
                    reaction_offset = offset
                    break
            prior_episode_index = index
            if reaction is not None:
                observed = contact_slice[: reaction_offset + 1]
                extreme = (
                    min(item.low for item in observed)
                    if zone.direction == "BULLISH"
                    else max(item.high for item in observed)
                )
                episode = len(output) + 1
                output.append(
                    LiquidityContactV2(
                        identity=_identity(
                            "CONTACT_V2", zone.identity, str(episode), bar.open_time.isoformat(), reaction.close_time.isoformat()
                        ),
                        zone_identity=zone.identity,
                        direction=zone.direction,
                        episode=episode,
                        contact_at=bar.open_time.astimezone(UTC),
                        reaction_at=reaction.close_time.astimezone(UTC),
                        contact_extreme=round(extreme, 8),
                    )
                )
        in_overlap = overlap
        index += 1
    return output


def _transition_after_contact(
    zone: LiquidityShiftZoneV2,
    contact: LiquidityContactV2,
    m15: Sequence[AggregateBar],
    closes: Sequence[datetime],
    pivots: Sequence[LiquidityPivotV2],
    atrs: Sequence[float],
    config: LiquidityShiftV2Config,
) -> LiquidityTransitionV2 | None:
    known = [
        item
        for item in pivots
        if item.detected_at <= contact.reaction_at
        and item.kind == ("HIGH" if zone.direction == "BULLISH" else "LOW")
    ]
    if not known:
        return None
    broken = max(known, key=lambda item: (item.pivot_at, item.detected_at))
    start = bisect.bisect_left(closes, contact.reaction_at)
    end_time = min(
        zone.terminal_at,
        contact.reaction_at + timedelta(minutes=15 * config.transition_m15_bars),
    )
    stop = bisect.bisect_right(closes, end_time)
    for index in range(start, stop):
        bar = m15[index]
        atr = atrs[index]
        bar_range = max(bar.high - bar.low, config.tick_size)
        body_ratio = abs(bar.close - bar.open) / bar_range
        aligned = bar.close > bar.open if zone.direction == "BULLISH" else bar.close < bar.open
        break_buffer = max(config.transition_break_buffer_atr * atr, 2 * config.tick_size)
        broke = (
            bar.close > broken.level + break_buffer
            if zone.direction == "BULLISH"
            else bar.close < broken.level - break_buffer
        )
        if (
            not aligned
            or not broke
            or body_ratio < config.transition_body_ratio
            or _true_range_at(m15, index) / atr < config.transition_range_atr
        ):
            continue
        distance = (
            bar.close - contact.contact_extreme
            if zone.direction == "BULLISH"
            else contact.contact_extreme - bar.close
        )
        if distance <= 4 * config.tick_size:
            continue
        if zone.direction == "BULLISH":
            band_a = bar.close - config.retracement_max * distance
            band_b = bar.close - config.retracement_min * distance
            half = bar.close - config.limit_retracement * distance
        else:
            band_a = bar.close + config.retracement_min * distance
            band_b = bar.close + config.retracement_max * distance
            half = bar.close + config.limit_retracement * distance
        return LiquidityTransitionV2(
            identity=_identity("TRANSITION_V2", zone.identity, contact.identity, bar.close_time.isoformat(), broken.identity),
            zone_identity=zone.identity,
            contact_identity=contact.identity,
            direction=zone.direction,
            transition_at=bar.close_time.astimezone(UTC),
            broken_m15_pivot_identity=broken.identity,
            broken_m15_level=broken.level,
            contact_extreme=contact.contact_extreme,
            transition_close=round(bar.close, 8),
            transition_atr14=round(atr, 8),
            retracement_lower=round(min(band_a, band_b), 8),
            retracement_upper=round(max(band_a, band_b), 8),
            half_retrace=round(half, 8),
        )
    return None


def _entry_intents(
    transition: LiquidityTransitionV2,
    zone: LiquidityShiftZoneV2,
    m1: Sequence[AggregateBar],
    m1_opens: Sequence[datetime],
    m5: Sequence[AggregateBar],
    m5_closes: Sequence[datetime],
    config: LiquidityShiftV2Config,
) -> list[LiquidityEntryIntentV2]:
    expires_at = min(
        zone.terminal_at,
        transition.transition_at + timedelta(minutes=5 * config.entry_expiry_m5_bars),
    )
    stop_buffer = max(config.stop_buffer_m15_atr * transition.transition_atr14, 2 * config.tick_size)
    contact_stop = (
        transition.contact_extreme - stop_buffer
        if transition.direction == "BULLISH"
        else transition.contact_extreme + stop_buffer
    )
    limit_trigger = _first_m1_touch(
        m1,
        m1_opens,
        transition.transition_at,
        expires_at,
        transition.half_retrace,
    )
    limit_state, limit_distance = _intent_state(
        transition.direction,
        transition.half_retrace,
        contact_stop,
        transition.transition_atr14,
        limit_trigger,
        expires_at,
        m1[-1].close_time.astimezone(UTC) if m1 else transition.transition_at,
        config,
    )
    output = [
        LiquidityEntryIntentV2(
            identity=_identity("ENTRY_V2", transition.identity, "SHIFT_HALF_RETRACE_LIMIT_V2"),
            transition_identity=transition.identity,
            zone_identity=zone.identity,
            zone_timeframe=zone.timeframe,
            family="SHIFT_HALF_RETRACE_LIMIT_V2",
            direction=transition.direction,
            order_at=transition.transition_at,
            expires_at=expires_at,
            triggered_at=limit_trigger,
            entry_reference=transition.half_retrace,
            stop=round(contact_stop, 8),
            stop_distance_atr=round(limit_distance, 6),
            state=limit_state,
        )
    ]

    confirmation = _m5_confirmation(
        transition,
        m5,
        m5_closes,
        m1,
        m1_opens,
        expires_at,
        config,
    )
    if confirmation is None:
        confirmation_at = None
        confirmation_entry = transition.transition_close
        confirmation_stop = contact_stop
    else:
        confirmation_at, confirmation_entry, pullback_extreme = confirmation
        confirmation_stop = (
            pullback_extreme - stop_buffer
            if transition.direction == "BULLISH"
            else pullback_extreme + stop_buffer
        )
    confirmation_state, confirmation_distance = _intent_state(
        transition.direction,
        confirmation_entry,
        confirmation_stop,
        transition.transition_atr14,
        confirmation_at,
        expires_at,
        m1[-1].close_time.astimezone(UTC) if m1 else transition.transition_at,
        config,
    )
    output.append(
        LiquidityEntryIntentV2(
            identity=_identity("ENTRY_V2", transition.identity, "SHIFT_M5_STRUCTURE_CONFIRMATION_V2"),
            transition_identity=transition.identity,
            zone_identity=zone.identity,
            zone_timeframe=zone.timeframe,
            family="SHIFT_M5_STRUCTURE_CONFIRMATION_V2",
            direction=transition.direction,
            order_at=transition.transition_at,
            expires_at=expires_at,
            triggered_at=confirmation_at,
            entry_reference=round(confirmation_entry, 8),
            stop=round(confirmation_stop, 8),
            stop_distance_atr=round(confirmation_distance, 6),
            state=confirmation_state,
        )
    )
    return output


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


def _m5_confirmation(
    transition: LiquidityTransitionV2,
    m5: Sequence[AggregateBar],
    closes: Sequence[datetime],
    m1: Sequence[AggregateBar],
    m1_opens: Sequence[datetime],
    expires_at: datetime,
    config: LiquidityShiftV2Config,
) -> tuple[datetime, float, float] | None:
    start = bisect.bisect_right(closes, transition.transition_at)
    stop = bisect.bisect_right(closes, expires_at)
    pullback_seen = False
    pullback_extreme: float | None = None
    for index in range(start, stop):
        bar = m5[index]
        overlaps = bar.low <= transition.retracement_upper and bar.high >= transition.retracement_lower
        if overlaps:
            pullback_seen = True
        if pullback_seen:
            pullback_extreme = (
                min(pullback_extreme if pullback_extreme is not None else bar.low, bar.low)
                if transition.direction == "BULLISH"
                else max(pullback_extreme if pullback_extreme is not None else bar.high, bar.high)
            )
        if not pullback_seen or index < config.confirmation_break_prior_m5_bars:
            continue
        bar_range = max(bar.high - bar.low, config.tick_size)
        body_ratio = abs(bar.close - bar.open) / bar_range
        aligned = bar.close > bar.open if transition.direction == "BULLISH" else bar.close < bar.open
        prior = m5[index - config.confirmation_break_prior_m5_bars : index]
        broke = (
            bar.close > max(item.high for item in prior)
            if transition.direction == "BULLISH"
            else bar.close < min(item.low for item in prior)
        )
        invalid = (
            bar.close < transition.contact_extreme
            if transition.direction == "BULLISH"
            else bar.close > transition.contact_extreme
        )
        if invalid:
            return None
        if aligned and broke and body_ratio >= config.confirmation_body_ratio:
            next_minute = _next_m1_after(
                m1,
                m1_opens,
                bar.close_time.astimezone(UTC),
                expires_at,
            )
            if next_minute is None:
                return None
            return (
                next_minute.open_time.astimezone(UTC),
                next_minute.open,
                float(pullback_extreme),
            )
    return None


def _next_m1_after(
    m1: Sequence[AggregateBar],
    opens: Sequence[datetime],
    start: datetime,
    expires_at: datetime,
) -> AggregateBar | None:
    index = bisect.bisect_left(opens, start)
    if index >= len(m1):
        return None
    candidate = m1[index]
    return candidate if candidate.open_time.astimezone(UTC) < expires_at else None


def _intent_state(
    direction: Direction,
    entry: float,
    stop: float,
    atr: float,
    triggered_at: datetime | None,
    expires_at: datetime,
    observation_end: datetime,
    config: LiquidityShiftV2Config,
) -> tuple[Literal["PENDING", "TRIGGERED", "INVALID_GEOMETRY", "EXPIRED"], float]:
    risk = entry - stop if direction == "BULLISH" else stop - entry
    distance = risk / max(atr, config.tick_size)
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
    prior_close = bars[index - 1].close
    return max(bar.high - bar.low, abs(bar.high - prior_close), abs(bar.low - prior_close))


def _identity(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
