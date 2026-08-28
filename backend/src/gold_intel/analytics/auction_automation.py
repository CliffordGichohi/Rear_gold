from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from gold_intel.analytics.sessions import session_at
from gold_intel.analytics.structure import AggregateBar, MinuteBar, aggregate_minutes
from gold_intel.domain.signals import clamp

AUCTION_AUTOMATION_RULESET_VERSION = "gold-auction-automation-1"
MacroDirection = Literal["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]
Direction = Literal["BULLISH", "BEARISH"]


@dataclass(frozen=True, slots=True)
class AuctionAutomationConfig:
    pivot_left_bars: int = 2
    pivot_right_bars: int = 2
    atr_window: int = 14
    minimum_pivot_prominence_atr: float = 0.25
    break_buffer_atr: float = 0.10
    displacement_atr: float = 1.80
    displacement_body_ratio: float = 0.65
    zone_origin_lookback_bars: int = 4
    zone_expiry_m15_bars: int = 460
    zone_invalidation_buffer_atr: float = 0.10
    confirmed_retest_body_ratio: float = 0.55
    confirmed_retest_tolerance_atr: float = 0.10
    minimum_target_r: float = 1.25
    maximum_planned_risk_usd: float = 50.0
    macro_max_age_hours: int = 24
    tick_size: float = 0.01


@dataclass(frozen=True, slots=True)
class AuctionSwing:
    identity: str
    timeframe: str
    base_kind: Literal["HIGH", "LOW"]
    classification: str
    pivot_at: datetime
    detected_at: datetime
    price_level: float
    atr14: float
    prominence_atr: float
    confidence: float
    epistemic_status: Literal["CALCULATED"]
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AuctionShiftZone:
    identity: str
    timeframe: Literal["15m"]
    direction: Direction
    origin_at: datetime
    created_at: datetime
    detected_at: datetime
    lower_bound: float
    upper_bound: float
    midpoint: float
    broken_swing_identity: str
    broken_swing_level: float
    creation_atr14: float
    state: str
    first_touch_at: datetime | None
    retest_confirmed_at: datetime | None
    invalidated_at: datetime | None
    expires_at: datetime | None
    epistemic_status: Literal["INFERRED"]
    confidence: float
    detection_method: str
    invalidation_condition: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AuctionPaperProposal:
    identity: str
    zone_identity: str
    family: Literal["RETEST_LIMIT_V0_1", "CONFIRMED_RETEST_V0_1"]
    direction: Direction
    disposition: str
    triggered_at: datetime | None
    entry_reference: float | None
    stop: float
    target: float | None
    target_swing_identity: str | None
    planned_risk_usd: float | None
    quantity_ounces: int | None
    reward_to_risk: float | None
    macro_direction: MacroDirection
    macro_relationship: str
    liquidity_status: str
    epistemic_status: Literal["INFERRED"]
    explanation: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AuctionAutomationSnapshot:
    as_of: datetime
    ruleset_version: str
    config: AuctionAutomationConfig
    source_bar_count: int
    source_first_at: datetime | None
    source_last_at: datetime | None
    data_hash: str
    macro_direction: MacroDirection
    macro_bias_label: str
    macro_available_at: datetime | None
    liquidity_status: str
    timeframe_trends: dict[str, str]
    swings: tuple[AuctionSwing, ...]
    zones: tuple[AuctionShiftZone, ...]
    proposals: tuple[AuctionPaperProposal, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SwingPoint:
    public: AuctionSwing
    index: int


def build_auction_automation_snapshot(
    bars: list[MinuteBar],
    *,
    as_of: datetime,
    macro_bias_label: str = "UNKNOWN",
    macro_available_at: datetime | None = None,
    liquidity_status: str = "UNKNOWN",
    config: AuctionAutomationConfig | None = None,
) -> AuctionAutomationSnapshot:
    """Build point-in-time swing, zone and paper-proposal evidence.

    The function deliberately produces proposals rather than trades. It never
    reads a bar whose close or availability timestamp is after ``as_of``.
    """

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    active = config or AuctionAutomationConfig()
    _validate_config(active)
    cutoff = as_of.astimezone(UTC)
    if macro_available_at is not None and macro_available_at.tzinfo is None:
        raise ValueError("macro_available_at must be timezone-aware")
    macro_clock = macro_available_at.astimezone(UTC) if macro_available_at else None
    eligible = _canonical_minutes(bars, cutoff)
    macro_direction = _macro_direction(macro_bias_label)

    aggregates: dict[str, list[AggregateBar]] = {}
    points: dict[str, list[_SwingPoint]] = {}
    for timeframe, minutes in (("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240)):
        complete = [
            bar
            for bar in aggregate_minutes(
                eligible,
                timeframe_minutes=minutes,
                as_of=cutoff,
            )
            if bar.complete and bar.close_time <= cutoff
        ]
        aggregates[timeframe] = complete
        points[timeframe] = _confirmed_swings(
            complete,
            timeframe=timeframe,
            config=active,
        )

    zones = _auction_shift_zones(
        aggregates["15m"],
        points["15m"],
        aggregates["5m"],
        eligible,
        cutoff=cutoff,
        config=active,
    )
    public_zones = zones[-24:]
    target_points = points["15m"] + points["1h"] + points["4h"]
    proposals = _paper_proposals(
        public_zones,
        target_points,
        aggregates["5m"],
        eligible,
        macro_direction=macro_direction,
        macro_available_at=macro_clock,
        liquidity_status=liquidity_status,
        config=active,
    )
    warnings: list[str] = []
    for timeframe in ("5m", "15m", "1h", "4h"):
        if len(aggregates[timeframe]) < active.atr_window + 5:
            warnings.append(
                f"{timeframe} has only {len(aggregates[timeframe])} complete bars; "
                "automation evidence is incomplete."
            )
    if macro_direction in {"UNKNOWN", "NEUTRAL"}:
        warnings.append("Fundamental direction is not actionable; proposals cannot be PAPER_READY.")
    if liquidity_status not in {"NORMAL", "ELEVATED"}:
        warnings.append("Execution liquidity is unknown or abnormal; proposals cannot be PAPER_READY.")

    public_swings = tuple(
        point.public
        for timeframe in ("4h", "1h", "15m", "5m")
        for point in points[timeframe]
    )
    return AuctionAutomationSnapshot(
        as_of=cutoff,
        ruleset_version=AUCTION_AUTOMATION_RULESET_VERSION,
        config=active,
        source_bar_count=len(eligible),
        source_first_at=eligible[0].open_time if eligible else None,
        source_last_at=eligible[-1].close_time if eligible else None,
        data_hash=_automation_hash(
            eligible,
            cutoff,
            active,
            macro_bias_label,
            macro_clock,
            liquidity_status,
        ),
        macro_direction=macro_direction,
        macro_bias_label=macro_bias_label,
        macro_available_at=macro_clock,
        liquidity_status=liquidity_status,
        timeframe_trends={
            timeframe: _trend_label(points[timeframe])
            for timeframe in ("4h", "1h", "15m", "5m")
        },
        swings=public_swings,
        zones=tuple(public_zones),
        proposals=tuple(proposals),
        warnings=tuple(warnings),
    )


def auction_automation_to_dict(snapshot: AuctionAutomationSnapshot) -> dict[str, Any]:
    return {
        "as_of": snapshot.as_of,
        "ruleset_version": snapshot.ruleset_version,
        "config": asdict(snapshot.config),
        "source_bar_count": snapshot.source_bar_count,
        "source_first_at": snapshot.source_first_at,
        "source_last_at": snapshot.source_last_at,
        "data_hash": snapshot.data_hash,
        "macro_direction": snapshot.macro_direction,
        "macro_bias_label": snapshot.macro_bias_label,
        "macro_available_at": snapshot.macro_available_at,
        "liquidity_status": snapshot.liquidity_status,
        "timeframe_trends": snapshot.timeframe_trends,
        "swings": [asdict(item) for item in snapshot.swings],
        "zones": [asdict(item) for item in snapshot.zones],
        "proposals": [asdict(item) for item in snapshot.proposals],
        "warnings": list(snapshot.warnings),
    }


def _validate_config(config: AuctionAutomationConfig) -> None:
    if config.pivot_left_bars < 1 or config.pivot_right_bars < 1:
        raise ValueError("pivot confirmation bars must be positive")
    if config.atr_window < 2:
        raise ValueError("atr_window must be at least two")
    if not 0 < config.displacement_body_ratio <= 1:
        raise ValueError("displacement_body_ratio must be in (0, 1]")
    if not 0 < config.confirmed_retest_body_ratio <= 1:
        raise ValueError("confirmed_retest_body_ratio must be in (0, 1]")
    if config.zone_origin_lookback_bars < 1 or config.zone_expiry_m15_bars < 1:
        raise ValueError("zone lookback and expiry must be positive")
    if config.maximum_planned_risk_usd <= 0 or config.tick_size <= 0:
        raise ValueError("risk and tick_size must be positive")
    if config.macro_max_age_hours < 1:
        raise ValueError("macro_max_age_hours must be positive")


def _canonical_minutes(bars: list[MinuteBar], cutoff: datetime) -> list[MinuteBar]:
    canonical: dict[datetime, MinuteBar] = {}
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        open_at = bar.open_time.astimezone(UTC)
        if bar.close_time <= cutoff and bar.available_at <= cutoff:
            canonical[open_at] = bar
    return sorted(canonical.values(), key=lambda item: item.open_time)


def _true_ranges(bars: list[AggregateBar]) -> list[float]:
    output: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            output.append(bar.high - bar.low)
        else:
            prior_close = bars[index - 1].close
            output.append(
                max(
                    bar.high - bar.low,
                    abs(bar.high - prior_close),
                    abs(bar.low - prior_close),
                )
            )
    return output


def _rolling_mean(values: list[float], index: int, window: int) -> float:
    members = values[max(0, index - window + 1) : index + 1]
    return sum(members) / max(1, len(members))


def _confirmed_swings(
    bars: list[AggregateBar],
    *,
    timeframe: str,
    config: AuctionAutomationConfig,
) -> list[_SwingPoint]:
    if len(bars) < config.pivot_left_bars + config.pivot_right_bars + 1:
        return []
    true_ranges = _true_ranges(bars)
    points: list[_SwingPoint] = []
    prior_by_kind: dict[str, float] = {}
    left = config.pivot_left_bars
    right = config.pivot_right_bars
    for index in range(left, len(bars) - right):
        bar = bars[index]
        neighbors = bars[index - left : index] + bars[index + 1 : index + right + 1]
        atr = max(_rolling_mean(true_ranges, index, config.atr_window), config.tick_size)
        high_prominence = bar.high - min(item.low for item in neighbors)
        low_prominence = max(item.high for item in neighbors) - bar.low
        minimum = max(config.minimum_pivot_prominence_atr * atr, 2 * config.tick_size)
        detected_at = bars[index + right].close_time
        candidates = (
            ("HIGH", bar.high, high_prominence),
            ("LOW", bar.low, low_prominence),
        )
        for kind, level, prominence in candidates:
            strict = (
                all(level > item.high for item in neighbors)
                if kind == "HIGH"
                else all(level < item.low for item in neighbors)
            )
            if not strict or prominence < minimum:
                continue
            classification = _swing_classification(
                kind,
                level,
                prior_by_kind.get(kind),
                config.tick_size,
            )
            identity = _identity(
                "SWING",
                timeframe,
                kind,
                bar.open_time.isoformat(),
                f"{level:.8f}",
                detected_at.isoformat(),
            )
            public = AuctionSwing(
                identity=identity,
                timeframe=timeframe,
                base_kind=kind,  # type: ignore[arg-type]
                classification=classification,
                pivot_at=bar.open_time,
                detected_at=detected_at,
                price_level=round(level, 8),
                atr14=round(atr, 8),
                prominence_atr=round(prominence / atr, 6),
                confidence=round(
                    clamp(55 + min(2.0, prominence / atr) * 17.5, 55, 90),
                    2,
                ),
                epistemic_status="CALCULATED",
                evidence={
                    "pivot_index": index,
                    "left_confirmation_bars": left,
                    "right_confirmation_bars": right,
                    "source_bar_ids": list(bar.source_ids),
                },
            )
            points.append(_SwingPoint(public=public, index=index))
            prior_by_kind[kind] = level
    return sorted(points, key=lambda item: (item.public.detected_at, item.public.base_kind))


def _swing_classification(
    kind: str,
    level: float,
    prior: float | None,
    tick_size: float,
) -> str:
    if prior is None:
        return f"SWING_{kind}"
    if kind == "HIGH":
        if level > prior + tick_size:
            return "HIGHER_HIGH"
        if level < prior - tick_size:
            return "LOWER_HIGH"
        return "EQUAL_HIGH"
    if level > prior + tick_size:
        return "HIGHER_LOW"
    if level < prior - tick_size:
        return "LOWER_LOW"
    return "EQUAL_LOW"


def _trend_label(points: list[_SwingPoint]) -> str:
    highs = [item.public for item in points if item.public.base_kind == "HIGH"]
    lows = [item.public for item in points if item.public.base_kind == "LOW"]
    if not highs or not lows:
        return "UNKNOWN"
    high_state = highs[-1].classification
    low_state = lows[-1].classification
    if high_state == "HIGHER_HIGH" and low_state == "HIGHER_LOW":
        return "BULLISH"
    if high_state == "LOWER_HIGH" and low_state == "LOWER_LOW":
        return "BEARISH"
    if high_state == "EQUAL_HIGH" and low_state == "EQUAL_LOW":
        return "RANGE"
    return "MIXED_OR_TRANSITIONING"


def _auction_shift_zones(
    m15: list[AggregateBar],
    m15_swings: list[_SwingPoint],
    m5: list[AggregateBar],
    minute_bars: list[MinuteBar],
    *,
    cutoff: datetime,
    config: AuctionAutomationConfig,
) -> list[AuctionShiftZone]:
    if len(m15) < config.atr_window + config.zone_origin_lookback_bars:
        return []
    true_ranges = _true_ranges(m15)
    used_swings: set[str] = set()
    output: list[AuctionShiftZone] = []
    for index in range(config.atr_window, len(m15)):
        bar = m15[index]
        atr = max(_rolling_mean(true_ranges, index, config.atr_window), config.tick_size)
        bar_range = max(bar.high - bar.low, config.tick_size)
        body_ratio = abs(bar.close - bar.open) / bar_range
        range_atr = true_ranges[index] / atr
        if (
            range_atr < config.displacement_atr
            or body_ratio < config.displacement_body_ratio
            or bar.close == bar.open
        ):
            continue
        direction: Direction = "BULLISH" if bar.close > bar.open else "BEARISH"
        required_kind = "HIGH" if direction == "BULLISH" else "LOW"
        eligible_swings = [
            point
            for point in m15_swings
            if point.public.base_kind == required_kind
            and point.public.detected_at <= bar.open_time
            and point.index < index
            and point.public.identity not in used_swings
        ]
        if not eligible_swings:
            continue
        buffer = max(config.break_buffer_atr * atr, 2 * config.tick_size)
        broken = [
            point
            for point in eligible_swings
            if (
                bar.close > point.public.price_level + buffer
                if direction == "BULLISH"
                else bar.close < point.public.price_level - buffer
            )
        ]
        if not broken:
            continue
        swing = max(broken, key=lambda item: item.index)
        origin_candidates = m15[max(0, index - config.zone_origin_lookback_bars) : index]
        origin = next(
            (
                candidate
                for candidate in reversed(origin_candidates)
                if (
                    candidate.close < candidate.open
                    if direction == "BULLISH"
                    else candidate.close > candidate.open
                )
            ),
            None,
        )
        if origin is None:
            continue
        if direction == "BULLISH":
            lower = origin.low
            upper = max(origin.open, origin.close)
        else:
            lower = min(origin.open, origin.close)
            upper = origin.high
        if upper - lower < config.tick_size:
            continue
        used_swings.add(swing.public.identity)
        zone_identity = _identity(
            "ZONE",
            direction,
            origin.open_time.isoformat(),
            bar.close_time.isoformat(),
            swing.public.identity,
        )
        invalidation_buffer = max(
            config.zone_invalidation_buffer_atr * atr,
            2 * config.tick_size,
        )
        expiry_index = index + config.zone_expiry_m15_bars
        expires_at = m15[expiry_index].close_time if expiry_index < len(m15) else None
        terminal_at = min(
            (value for value in (expires_at, cutoff) if value is not None),
            default=cutoff,
        )
        invalidated_at: datetime | None = None
        for candidate in m15[index + 1 :]:
            if candidate.close_time > terminal_at:
                break
            invalidated = (
                candidate.close < lower - invalidation_buffer
                if direction == "BULLISH"
                else candidate.close > upper + invalidation_buffer
            )
            if invalidated:
                invalidated_at = candidate.close_time
                terminal_at = invalidated_at
                break
        touch_at = _first_zone_touch(
            minute_bars,
            created_at=bar.close_time,
            terminal_at=terminal_at,
            lower=lower,
            upper=upper,
        )
        confirmation_at = _first_retest_confirmation(
            m5,
            direction=direction,
            created_at=bar.close_time,
            touch_at=touch_at,
            terminal_at=terminal_at,
            lower=lower,
            upper=upper,
            creation_atr=atr,
            config=config,
            session_required=False,
        )
        if invalidated_at is not None:
            state = "INVALIDATED"
        elif expires_at is not None and expires_at <= cutoff:
            state = "EXPIRED"
        elif confirmation_at is not None:
            state = "RETEST_CONFIRMED"
        elif touch_at is not None:
            state = "TOUCHED"
        else:
            state = "ACTIVE_UNTOUCHED"
        output.append(
            AuctionShiftZone(
                identity=zone_identity,
                timeframe="15m",
                direction=direction,
                origin_at=origin.open_time,
                created_at=bar.close_time,
                detected_at=bar.close_time,
                lower_bound=round(lower, 8),
                upper_bound=round(upper, 8),
                midpoint=round((lower + upper) / 2, 8),
                broken_swing_identity=swing.public.identity,
                broken_swing_level=swing.public.price_level,
                creation_atr14=round(atr, 8),
                state=state,
                first_touch_at=touch_at,
                retest_confirmed_at=confirmation_at,
                invalidated_at=invalidated_at,
                expires_at=expires_at,
                epistemic_status="INFERRED",
                confidence=82.0,
                detection_method="M15_DISPLACEMENT_CLOSE_BREAK_LAST_CONFIRMED_SWING",
                invalidation_condition=(
                    f"Completed M15 close below {lower - invalidation_buffer:.2f}"
                    if direction == "BULLISH"
                    else f"Completed M15 close above {upper + invalidation_buffer:.2f}"
                ),
                evidence={
                    "range_atr": round(range_atr, 6),
                    "body_ratio": round(body_ratio, 6),
                    "break_buffer": round(buffer, 8),
                    "origin_source_bar_ids": list(origin.source_ids),
                    "displacement_source_bar_ids": list(bar.source_ids),
                    "zone_active_only_from": bar.close_time.isoformat(),
                    "classification_warning": (
                        "The zone is inferred from price structure; resting institutional "
                        "orders are not directly observed."
                    ),
                },
            )
        )
    return sorted(output, key=lambda item: (item.created_at, item.identity))


def _first_zone_touch(
    minute_bars: list[MinuteBar],
    *,
    created_at: datetime,
    terminal_at: datetime,
    lower: float,
    upper: float,
) -> datetime | None:
    for bar in minute_bars:
        if bar.open_time < created_at or bar.close_time > terminal_at:
            continue
        if bar.low <= upper and bar.high >= lower:
            return bar.close_time
    return None


def _first_retest_confirmation(
    bars: list[AggregateBar],
    *,
    direction: Direction,
    created_at: datetime,
    touch_at: datetime | None,
    terminal_at: datetime,
    lower: float,
    upper: float,
    creation_atr: float,
    config: AuctionAutomationConfig,
    session_required: bool,
) -> datetime | None:
    if touch_at is None:
        return None
    tolerance = max(
        config.confirmed_retest_tolerance_atr * creation_atr,
        2 * config.tick_size,
    )
    for bar in bars:
        if bar.close_time < touch_at or bar.open_time < created_at or bar.close_time > terminal_at:
            continue
        if session_required and not _entry_session(bar.close_time):
            continue
        bar_range = max(bar.high - bar.low, config.tick_size)
        body_ratio = abs(bar.close - bar.open) / bar_range
        if body_ratio < config.confirmed_retest_body_ratio:
            continue
        if direction == "BULLISH":
            touched = bar.low <= upper + tolerance and bar.high >= lower
            confirmed = bar.close > upper and bar.close > bar.open
        else:
            touched = bar.high >= lower - tolerance and bar.low <= upper
            confirmed = bar.close < lower and bar.close < bar.open
        if touched and confirmed:
            return bar.close_time
    return None


def _paper_proposals(
    zones: list[AuctionShiftZone],
    target_points: list[_SwingPoint],
    m5: list[AggregateBar],
    minute_bars: list[MinuteBar],
    *,
    macro_direction: MacroDirection,
    macro_available_at: datetime | None,
    liquidity_status: str,
    config: AuctionAutomationConfig,
) -> list[AuctionPaperProposal]:
    output: list[AuctionPaperProposal] = []
    for zone in zones:
        terminal_at = zone.invalidated_at or zone.expires_at or minute_bars[-1].close_time
        limit_fill = _first_limit_fill(
            minute_bars,
            direction=zone.direction,
            created_at=zone.created_at,
            terminal_at=terminal_at,
            entry=zone.midpoint,
        )
        output.append(
            _proposal(
                zone,
                family="RETEST_LIMIT_V0_1",
                triggered_at=limit_fill,
                entry_reference=zone.midpoint if limit_fill is not None else None,
                target_points=target_points,
                macro_direction=macro_direction,
                macro_available_at=macro_available_at,
                liquidity_status=liquidity_status,
                config=config,
            )
        )

        active_confirmation = _first_retest_confirmation(
            m5,
            direction=zone.direction,
            created_at=zone.created_at,
            touch_at=zone.first_touch_at,
            terminal_at=terminal_at,
            lower=zone.lower_bound,
            upper=zone.upper_bound,
            creation_atr=zone.creation_atr14,
            config=config,
            session_required=True,
        )
        confirmed_entry_bar = (
            next(
                (
                    bar
                    for bar in minute_bars
                    if active_confirmation is not None
                    and bar.open_time >= active_confirmation
                    and bar.close_time <= terminal_at
                ),
                None,
            )
            if active_confirmation is not None
            else None
        )
        output.append(
            _proposal(
                zone,
                family="CONFIRMED_RETEST_V0_1",
                triggered_at=confirmed_entry_bar.open_time if confirmed_entry_bar else None,
                entry_reference=confirmed_entry_bar.open if confirmed_entry_bar else None,
                target_points=target_points,
                macro_direction=macro_direction,
                macro_available_at=macro_available_at,
                liquidity_status=liquidity_status,
                config=config,
                confirmation_at=active_confirmation,
            )
        )
    return output


def _first_limit_fill(
    minute_bars: list[MinuteBar],
    *,
    direction: Direction,
    created_at: datetime,
    terminal_at: datetime,
    entry: float,
) -> datetime | None:
    del direction  # Direction is retained in the signature to bind the frozen family identity.
    for bar in minute_bars:
        if bar.open_time < created_at or bar.close_time > terminal_at:
            continue
        if not _entry_session(bar.open_time):
            continue
        if bar.low <= entry <= bar.high:
            return bar.open_time
    return None


def _proposal(
    zone: AuctionShiftZone,
    *,
    family: Literal["RETEST_LIMIT_V0_1", "CONFIRMED_RETEST_V0_1"],
    triggered_at: datetime | None,
    entry_reference: float | None,
    target_points: list[_SwingPoint],
    macro_direction: MacroDirection,
    macro_available_at: datetime | None,
    liquidity_status: str,
    config: AuctionAutomationConfig,
    confirmation_at: datetime | None = None,
) -> AuctionPaperProposal:
    adverse_buffer = max(
        config.zone_invalidation_buffer_atr * zone.creation_atr14,
        2 * config.tick_size,
    )
    stop = (
        zone.lower_bound - adverse_buffer
        if zone.direction == "BULLISH"
        else zone.upper_bound + adverse_buffer
    )
    target: float | None = None
    target_identity: str | None = None
    quantity: int | None = None
    planned_risk: float | None = None
    reward_to_risk: float | None = None
    target_point: _SwingPoint | None = None
    if triggered_at is not None and entry_reference is not None:
        target_point = _nearest_known_target(
            target_points,
            direction=zone.direction,
            entry=entry_reference,
            at=triggered_at,
        )
        if target_point is not None:
            target = target_point.public.price_level
            target_identity = target_point.public.identity
        risk_distance = abs(entry_reference - stop)
        if risk_distance > 0:
            quantity = math.floor(config.maximum_planned_risk_usd / risk_distance)
            if quantity >= 1:
                planned_risk = risk_distance * quantity
                if target is not None:
                    reward_to_risk = abs(target - entry_reference) / risk_distance
    point_in_time_macro: MacroDirection = (
        macro_direction
        if triggered_at is not None
        and macro_available_at is not None
        and macro_available_at <= triggered_at
        and triggered_at - macro_available_at <= timedelta(hours=config.macro_max_age_hours)
        else "UNKNOWN"
    )
    macro_relationship = _macro_relationship(zone.direction, point_in_time_macro)
    if triggered_at is None:
        if zone.state == "INVALIDATED":
            disposition = "CANCELLED_INVALIDATED"
        elif zone.state == "EXPIRED":
            disposition = "EXPIRED"
        else:
            disposition = "WAITING_RETEST"
    elif quantity is None or quantity < 1 or planned_risk is None:
        disposition = "BLOCKED_RISK_GEOMETRY"
    elif target is None or reward_to_risk is None or reward_to_risk < config.minimum_target_r:
        disposition = "BLOCKED_TARGET_GEOMETRY"
    elif macro_relationship == "COUNTER_MACRO":
        disposition = "COUNTER_MACRO"
    elif macro_relationship != "ALIGNED":
        disposition = "WAITING_MACRO"
    elif liquidity_status not in {"NORMAL", "ELEVATED"}:
        disposition = "WAITING_LIQUIDITY"
    else:
        disposition = "PAPER_READY"
    identity = _identity("PROPOSAL", family, zone.identity)
    return AuctionPaperProposal(
        identity=identity,
        zone_identity=zone.identity,
        family=family,
        direction=zone.direction,
        disposition=disposition,
        triggered_at=triggered_at,
        entry_reference=round(entry_reference, 8) if entry_reference is not None else None,
        stop=round(stop, 8),
        target=round(target, 8) if target is not None else None,
        target_swing_identity=target_identity,
        planned_risk_usd=round(planned_risk, 8) if planned_risk is not None else None,
        quantity_ounces=quantity if quantity is not None and quantity >= 1 else None,
        reward_to_risk=round(reward_to_risk, 6) if reward_to_risk is not None else None,
        macro_direction=point_in_time_macro,
        macro_relationship=macro_relationship,
        liquidity_status=liquidity_status,
        epistemic_status="INFERRED",
        explanation=_proposal_explanation(
            family,
            zone.direction,
            disposition,
            macro_relationship,
        ),
        evidence={
            "zone_created_at": zone.created_at.isoformat(),
            "zone_state": zone.state,
            "confirmation_at": confirmation_at.isoformat() if confirmation_at else None,
            "quantity_rule": "FLOOR_50_USD_DIVIDED_BY_ACTUAL_ENTRY_TO_STOP_DISTANCE",
            "target_rule": "NEAREST_POINT_IN_TIME_CONFIRMED_M15_H1_H4_OPPOSING_SWING",
            "minimum_target_r": config.minimum_target_r,
            "snapshot_macro_available_at": (
                macro_available_at.isoformat() if macro_available_at else None
            ),
            "macro_backfill_prohibited": True,
            "live_order_permitted": False,
        },
    )


def _nearest_known_target(
    points: list[_SwingPoint],
    *,
    direction: Direction,
    entry: float,
    at: datetime,
) -> _SwingPoint | None:
    kind = "HIGH" if direction == "BULLISH" else "LOW"
    eligible = [
        point
        for point in points
        if point.public.base_kind == kind
        and point.public.detected_at <= at
        and (
            point.public.price_level > entry
            if direction == "BULLISH"
            else point.public.price_level < entry
        )
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda item: abs(item.public.price_level - entry))


def _entry_session(value: datetime) -> bool:
    context = session_at(value)
    return "LONDON" in context.active or "NEW_YORK" in context.active


def _macro_direction(label: str) -> MacroDirection:
    normalized = label.upper()
    if "BULLISH" in normalized:
        return "BULLISH"
    if "BEARISH" in normalized:
        return "BEARISH"
    if "NEUTRAL" in normalized or "CONFLICT" in normalized:
        return "NEUTRAL"
    return "UNKNOWN"


def _macro_relationship(direction: Direction, macro: MacroDirection) -> str:
    if macro in {"UNKNOWN", "NEUTRAL"}:
        return macro
    return "ALIGNED" if direction == macro else "COUNTER_MACRO"


def _proposal_explanation(
    family: str,
    direction: str,
    disposition: str,
    macro_relationship: str,
) -> str:
    return (
        f"{family} {direction.lower()} proposal is {disposition}. "
        f"The zone is inferred from a completed M15 displacement break; "
        f"macro relationship is {macro_relationship}. No live order was submitted."
    )


def _identity(*parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _automation_hash(
    bars: list[MinuteBar],
    as_of: datetime,
    config: AuctionAutomationConfig,
    macro_bias_label: str,
    macro_available_at: datetime | None,
    liquidity_status: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(AUCTION_AUTOMATION_RULESET_VERSION.encode("utf-8"))
    digest.update(as_of.isoformat().encode("utf-8"))
    digest.update(
        json.dumps(asdict(config), sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    digest.update(macro_bias_label.encode("utf-8"))
    digest.update((macro_available_at.isoformat() if macro_available_at else "UNKNOWN").encode("utf-8"))
    digest.update(liquidity_status.encode("utf-8"))
    for bar in bars:
        digest.update(
            json.dumps(
                {
                    "id": str(bar.id),
                    "open_time": bar.open_time.isoformat(),
                    "close_time": bar.close_time.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "available_at": bar.available_at.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return digest.hexdigest()
