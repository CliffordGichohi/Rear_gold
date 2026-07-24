from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from gold_intel.domain.signals import SignalResult, clamp

STRUCTURE_RULESET_VERSION = "market-structure-1"
NEW_YORK = ZoneInfo("America/New_York")
TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1_440,
}


@dataclass(frozen=True, slots=True)
class MinuteBar:
    id: UUID
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    available_at: datetime


@dataclass(frozen=True, slots=True)
class AggregateBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    complete: bool
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StructureConfig:
    pivot_left_bars: int = 2
    pivot_right_bars: int = 2
    atr_window: int = 14
    minimum_pivot_prominence_atr: float = 0.25
    breakout_buffer_atr: float = 0.10
    acceptance_bars: int = 2
    range_window_bars: int = 20
    compression_recent_bars: int = 5
    compression_ratio: float = 0.70
    expansion_ratio: float = 1.40
    displacement_atr: float = 1.80
    displacement_body_ratio: float = 0.65
    retest_tolerance_atr: float = 0.25
    tick_size: float = 0.01
    daily_session_start_hour_new_york: int = 18
    daily_session_end_hour_new_york: int = 17
    monday_session_start_hour_new_york: int = 18
    daily_pause_start_minute_new_york: int = 0
    daily_pause_end_minute_new_york: int = 0


@dataclass(frozen=True, slots=True)
class StructureDetection:
    kind: str
    direction: str
    timestamp: datetime
    detected_at: datetime
    price_level: float
    timeframe: str
    detection_method: str
    confidence: float
    epistemic_status: str
    evidence: dict[str, Any]
    invalidation_condition: str


@dataclass(frozen=True, slots=True)
class TimeframeStructure:
    timeframe: str
    status: str
    source_bar_count: int
    complete_bar_count: int
    last_close: float | None
    atr14: float | None
    trend: str
    support: float | None
    resistance: float | None
    range_low: float | None
    range_high: float | None
    compression_ratio: float | None
    momentum_atr: float | None
    detections: tuple[StructureDetection, ...]


@dataclass(frozen=True, slots=True)
class MarketStructureSnapshot:
    as_of: datetime
    ruleset_version: str
    config: StructureConfig
    source_bar_count: int
    data_hash: str
    timeframes: tuple[TimeframeStructure, ...]
    chart_bars: tuple[AggregateBar, ...]


@dataclass(frozen=True, slots=True)
class _Pivot:
    kind: str
    classification: str
    index: int
    level: float
    timestamp: datetime
    detected_at: datetime
    atr: float
    prominence_atr: float
    confidence: float


def aggregate_five_minutes(bars: list[MinuteBar], as_of: datetime) -> list[AggregateBar]:
    eligible = sorted(
        (bar for bar in bars if bar.available_at <= as_of and bar.close_time <= as_of),
        key=lambda bar: bar.open_time,
    )
    buckets: dict[datetime, list[MinuteBar]] = {}
    for bar in eligible:
        bucket = bar.open_time.replace(
            minute=bar.open_time.minute - bar.open_time.minute % 5,
            second=0,
            microsecond=0,
        )
        buckets.setdefault(bucket, []).append(bar)

    aggregates: list[AggregateBar] = []
    for bucket, members in sorted(buckets.items()):
        expected_opens = {bucket + timedelta(minutes=index) for index in range(5)}
        actual_opens = {member.open_time for member in members}
        complete = len(members) == 5 and actual_opens == expected_opens
        total_volume = None
        if all(member.volume is not None for member in members):
            total_volume = sum(member.volume or 0 for member in members)
        aggregates.append(
            AggregateBar(
                open_time=bucket,
                close_time=bucket + timedelta(minutes=5),
                open=members[0].open,
                high=max(member.high for member in members),
                low=min(member.low for member in members),
                close=members[-1].close,
                volume=total_volume,
                complete=complete,
                source_ids=tuple(str(member.id) for member in members),
            )
        )
    return aggregates


def calculate_five_minute_acceptance(
    bars: list[AggregateBar], as_of: datetime, tick_size: float = 0.01
) -> SignalResult:
    complete = [bar for bar in bars if bar.complete and bar.close_time <= as_of]
    if len(complete) < 20:
        return _unknown(as_of, "At least 20 complete five-minute bars are required.")

    true_ranges: list[float] = []
    for index, bar in enumerate(complete):
        if index == 0:
            true_ranges.append(bar.high - bar.low)
        else:
            prior_close = complete[index - 1].close
            true_ranges.append(
                max(bar.high - bar.low, abs(bar.high - prior_close), abs(bar.low - prior_close))
            )

    swing_candidates: list[tuple[int, float, datetime]] = []
    for index in range(2, len(complete) - 2):
        bar = complete[index]
        if not (
            bar.high > complete[index - 1].high
            and bar.high > complete[index - 2].high
            and bar.high > complete[index + 1].high
            and bar.high > complete[index + 2].high
        ):
            continue
        atr_at_pivot = _rolling_mean(true_ranges, index, 14)
        local_floor = min(
            complete[index - 2].low,
            complete[index - 1].low,
            complete[index + 1].low,
            complete[index + 2].low,
        )
        if bar.high - local_floor < max(0.25 * atr_at_pivot, 2 * tick_size):
            continue
        detection_time = complete[index + 2].close_time
        if detection_time <= as_of:
            swing_candidates.append((index, bar.high, detection_time))

    if not swing_candidates:
        return _unknown(as_of, "No confirmed qualifying swing high is available.")

    latest_two = complete[-2:]
    candidates_before_confirmation = [
        candidate for candidate in swing_candidates if candidate[0] < len(complete) - 2
    ]
    if not candidates_before_confirmation:
        return _unknown(as_of, "No resistance swing predates the confirmation bars.")

    pivot_index, resistance, detection_time = candidates_before_confirmation[-1]
    atr14 = _rolling_mean(true_ranges, len(complete) - 1, 14)
    buffer = max(0.10 * atr14, 2 * tick_size)
    threshold = resistance + buffer
    accepted = all(bar.close > threshold for bar in latest_two)
    direction = 1.0 if accepted else 0.0
    strength = (
        min(
            100.0,
            max(0.0, (min(bar.close for bar in latest_two) - resistance) / max(atr14, tick_size))
            * 100,
        )
        if accepted
        else 0.0
    )

    return SignalResult(
        name="FIVE_MINUTE_ACCEPTANCE_V1",
        layer=7,
        driver="PRICE_CONFIRMATION",
        epistemic_status="INFERRED",
        direction=direction,
        strength=round(strength, 3),
        confidence=78.0 if accepted else 65.0,
        freshness=100.0,
        data_quality=100.0,
        explanation=(
            "Two complete five-minute bars closed above confirmed resistance and the ATR/tick buffer; "
            "this is inferred price acceptance."
            if accepted
            else "The latest two complete five-minute bars have not confirmed acceptance above resistance."
        ),
        observed_at=latest_two[-1].close_time,
        available_at=latest_two[-1].close_time,
        expires_at=latest_two[-1].close_time + timedelta(minutes=30),
        evidence={
            "resistance": round(resistance, 6),
            "threshold": round(threshold, 6),
            "atr14": round(atr14, 6),
            "buffer": round(buffer, 6),
            "confirmation_closes": [round(bar.close, 6) for bar in latest_two],
            "pivot_open_time": complete[pivot_index].open_time.isoformat(),
            "pivot_detection_time": detection_time.isoformat(),
            "source_bar_ids": [source_id for bar in latest_two for source_id in bar.source_ids],
            "invalidation": f"A complete five-minute close back below {resistance:.2f}",
        },
    )


def _rolling_mean(values: list[float], end_index: int, window: int) -> float:
    start = max(0, end_index - window + 1)
    selected = values[start : end_index + 1]
    return sum(selected) / len(selected)


def _unknown(as_of: datetime, explanation: str) -> SignalResult:
    return SignalResult(
        name="FIVE_MINUTE_ACCEPTANCE_V1",
        layer=7,
        driver="PRICE_CONFIRMATION",
        epistemic_status="UNKNOWN",
        direction=0,
        strength=0,
        confidence=0,
        freshness=0,
        data_quality=0,
        explanation=explanation,
        observed_at=as_of,
        available_at=as_of,
    )


def aggregate_minutes(
    bars: list[MinuteBar],
    *,
    timeframe_minutes: int,
    as_of: datetime,
) -> list[AggregateBar]:
    """Aggregate canonical minute bars without silently filling missing minutes."""

    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(UTC)
    canonical: dict[datetime, MinuteBar] = {}
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        if bar.available_at <= cutoff and bar.close_time <= cutoff:
            canonical[bar.open_time.astimezone(UTC)] = bar

    buckets: dict[datetime, list[MinuteBar]] = {}
    for open_time, bar in canonical.items():
        minute_number = int(open_time.timestamp() // 60)
        bucket_number = minute_number - minute_number % timeframe_minutes
        bucket = datetime.fromtimestamp(bucket_number * 60, tz=UTC)
        buckets.setdefault(bucket, []).append(bar)

    aggregates: list[AggregateBar] = []
    for bucket, raw_members in sorted(buckets.items()):
        members = sorted(raw_members, key=lambda item: item.open_time)
        expected_opens = {bucket + timedelta(minutes=index) for index in range(timeframe_minutes)}
        actual_opens = {member.open_time.astimezone(UTC) for member in members}
        complete = len(members) == timeframe_minutes and actual_opens == expected_opens
        total_volume = None
        if all(member.volume is not None for member in members):
            total_volume = sum(member.volume or 0 for member in members)
        aggregates.append(
            AggregateBar(
                open_time=bucket,
                close_time=bucket + timedelta(minutes=timeframe_minutes),
                open=members[0].open,
                high=max(member.high for member in members),
                low=min(member.low for member in members),
                close=members[-1].close,
                volume=total_volume,
                complete=complete,
                source_ids=tuple(str(member.id) for member in members),
            )
        )
    return aggregates


def build_market_structure_snapshot(
    bars: list[MinuteBar],
    *,
    as_of: datetime,
    config: StructureConfig | None = None,
    chart_timeframe: str = "5m",
    chart_bar_limit: int = 180,
) -> MarketStructureSnapshot:
    """Build a deterministic, point-in-time multi-timeframe structure snapshot."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if chart_timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported chart timeframe: {chart_timeframe}")
    if chart_bar_limit < 20:
        raise ValueError("chart_bar_limit must be at least 20")
    cutoff = as_of.astimezone(UTC)
    active_config = config or StructureConfig()
    eligible = sorted(
        (bar for bar in bars if bar.available_at <= cutoff and bar.close_time <= cutoff),
        key=lambda item: item.open_time,
    )
    timeframes: list[TimeframeStructure] = []
    aggregates_by_timeframe: dict[str, list[AggregateBar]] = {}
    for timeframe, minutes in TIMEFRAME_MINUTES.items():
        aggregates = (
            aggregate_trading_days(
                eligible,
                as_of=cutoff,
                session_start_hour=active_config.daily_session_start_hour_new_york,
                session_end_hour=active_config.daily_session_end_hour_new_york,
                monday_start_hour=active_config.monday_session_start_hour_new_york,
                pause_start_minute=active_config.daily_pause_start_minute_new_york,
                pause_end_minute=active_config.daily_pause_end_minute_new_york,
            )
            if timeframe == "1d"
            else aggregate_minutes(
                eligible,
                timeframe_minutes=minutes,
                as_of=cutoff,
            )
        )
        aggregates_by_timeframe[timeframe] = aggregates
        timeframes.append(
            analyze_timeframe_structure(
                aggregates,
                timeframe=timeframe,
                as_of=cutoff,
                config=active_config,
            )
        )

    chart_bars = tuple(bar for bar in aggregates_by_timeframe[chart_timeframe] if bar.complete)[
        -chart_bar_limit:
    ]
    return MarketStructureSnapshot(
        as_of=cutoff,
        ruleset_version=STRUCTURE_RULESET_VERSION,
        config=active_config,
        source_bar_count=len(eligible),
        data_hash=_structure_data_hash(eligible, cutoff, active_config),
        timeframes=tuple(timeframes),
        chart_bars=chart_bars,
    )


def aggregate_trading_days(
    bars: list[MinuteBar],
    *,
    as_of: datetime,
    session_start_hour: int = 18,
    session_end_hour: int = 17,
    monday_start_hour: int = 18,
    pause_start_minute: int = 0,
    pause_end_minute: int = 0,
) -> list[AggregateBar]:
    """Aggregate the COMEX/FX-style New York trading day without filling its break."""

    if (
        not 0 <= session_start_hour <= 23
        or not 0 <= session_end_hour <= 23
        or not 0 <= monday_start_hour <= 23
    ):
        raise ValueError("daily session hours must be in [0, 23]")
    if not 0 <= pause_start_minute <= 1_440 or not 0 <= pause_end_minute <= 1_440:
        raise ValueError("daily pause minutes must be in [0, 1440]")
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(UTC)
    session_start = time(session_start_hour)
    session_end = time(session_end_hour)
    canonical: dict[datetime, MinuteBar] = {}
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        if bar.available_at <= cutoff and bar.close_time <= cutoff:
            canonical[bar.open_time.astimezone(UTC)] = bar

    buckets: dict[date, list[MinuteBar]] = {}
    for open_time, bar in canonical.items():
        local = open_time.astimezone(NEW_YORK)
        local_clock = local.timetz().replace(tzinfo=None)
        if session_end <= local_clock < session_start:
            continue
        trading_date = (
            local.date() + timedelta(days=1) if local_clock >= session_start else local.date()
        )
        if trading_date.weekday() >= 5:
            continue
        buckets.setdefault(trading_date, []).append(bar)

    output: list[AggregateBar] = []
    for trading_date, raw_members in sorted(buckets.items()):
        effective_start = time(monday_start_hour) if trading_date.weekday() == 0 else session_start
        start_local = datetime.combine(
            trading_date - timedelta(days=1),
            effective_start,
            tzinfo=NEW_YORK,
        )
        end_local = datetime.combine(
            trading_date,
            session_end,
            tzinfo=NEW_YORK,
        )
        start_at = start_local.astimezone(UTC)
        end_at = end_local.astimezone(UTC)
        members = sorted(raw_members, key=lambda item: item.open_time)
        elapsed_minutes = int((end_at - start_at).total_seconds() // 60)
        candidate_opens = (start_at + timedelta(minutes=index) for index in range(elapsed_minutes))
        expected_opens = {
            candidate
            for candidate in candidate_opens
            if not _minute_in_window(
                _minute_of_day(candidate.astimezone(NEW_YORK)),
                pause_start_minute,
                pause_end_minute,
            )
        }
        expected_count = len(expected_opens)
        actual_opens = {member.open_time.astimezone(UTC) for member in members}
        complete = (
            end_at <= cutoff and len(members) == expected_count and actual_opens == expected_opens
        )
        total_volume = None
        if all(member.volume is not None for member in members):
            total_volume = sum(member.volume or 0 for member in members)
        output.append(
            AggregateBar(
                open_time=start_at,
                close_time=end_at,
                open=members[0].open,
                high=max(member.high for member in members),
                low=min(member.low for member in members),
                close=members[-1].close,
                volume=total_volume,
                complete=complete,
                source_ids=tuple(str(member.id) for member in members),
            )
        )
    return output


def _minute_of_day(value: datetime) -> int:
    return value.hour * 60 + value.minute


def _minute_in_window(value: int, start: int, end: int) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= value < end
    return value >= start or value < end


def analyze_timeframe_structure(
    bars: list[AggregateBar],
    *,
    timeframe: str,
    as_of: datetime,
    config: StructureConfig,
) -> TimeframeStructure:
    complete = [bar for bar in bars if bar.complete and bar.close_time <= as_of]
    minimum = max(
        config.atr_window + 2,
        config.pivot_left_bars + config.pivot_right_bars + 3,
    )
    if len(complete) < minimum:
        return TimeframeStructure(
            timeframe=timeframe,
            status="INSUFFICIENT_DATA",
            source_bar_count=sum(len(bar.source_ids) for bar in bars),
            complete_bar_count=len(complete),
            last_close=complete[-1].close if complete else None,
            atr14=None,
            trend="UNKNOWN",
            support=None,
            resistance=None,
            range_low=None,
            range_high=None,
            compression_ratio=None,
            momentum_atr=None,
            detections=(),
        )

    true_ranges = _true_ranges(complete)
    atr = _rolling_mean(true_ranges, len(true_ranges) - 1, config.atr_window)
    pivots = _confirmed_pivots(complete, true_ranges, config)
    high_pivots = [pivot for pivot in pivots if pivot.kind == "HIGH"]
    low_pivots = [pivot for pivot in pivots if pivot.kind == "LOW"]
    support = low_pivots[-1].level if low_pivots else None
    resistance = high_pivots[-1].level if high_pivots else None
    trend = _trend_label(high_pivots, low_pivots)

    detections: list[StructureDetection] = [
        _pivot_detection(pivot, timeframe, config) for pivot in pivots[-18:]
    ]
    if high_pivots:
        detections.append(
            _level_detection(
                high_pivots[-1],
                timeframe=timeframe,
                kind="RESISTANCE",
                config=config,
            )
        )
    if low_pivots:
        detections.append(
            _level_detection(
                low_pivots[-1],
                timeframe=timeframe,
                kind="SUPPORT",
                config=config,
            )
        )
    detections.extend(
        _breakout_detections(
            complete,
            pivots,
            true_ranges,
            timeframe=timeframe,
            config=config,
        )
    )
    detections.extend(
        _latest_price_action_detections(
            complete,
            pivots,
            true_ranges,
            timeframe=timeframe,
            config=config,
        )
    )
    state_detections, compression_ratio, momentum_atr, range_low, range_high = _state_detections(
        complete,
        true_ranges,
        timeframe=timeframe,
        config=config,
    )
    detections.extend(state_detections)
    detections.sort(key=lambda item: (item.detected_at, item.kind))

    return TimeframeStructure(
        timeframe=timeframe,
        status="READY",
        source_bar_count=sum(len(bar.source_ids) for bar in bars),
        complete_bar_count=len(complete),
        last_close=round(complete[-1].close, 6),
        atr14=round(atr, 6),
        trend=trend,
        support=round(support, 6) if support is not None else None,
        resistance=round(resistance, 6) if resistance is not None else None,
        range_low=round(range_low, 6) if range_low is not None else None,
        range_high=round(range_high, 6) if range_high is not None else None,
        compression_ratio=(round(compression_ratio, 4) if compression_ratio is not None else None),
        momentum_atr=round(momentum_atr, 4) if momentum_atr is not None else None,
        detections=tuple(detections[-36:]),
    )


def market_structure_to_dict(snapshot: MarketStructureSnapshot) -> dict[str, Any]:
    return {
        "as_of": snapshot.as_of,
        "ruleset_version": snapshot.ruleset_version,
        "config": asdict(snapshot.config),
        "source_bar_count": snapshot.source_bar_count,
        "data_hash": snapshot.data_hash,
        "timeframes": [
            {
                **{key: value for key, value in asdict(timeframe).items() if key != "detections"},
                "detections": [asdict(detection) for detection in timeframe.detections],
            }
            for timeframe in snapshot.timeframes
        ],
        "chart_bars": [asdict(bar) for bar in snapshot.chart_bars],
    }


def _true_ranges(bars: list[AggregateBar]) -> list[float]:
    output: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            output.append(bar.high - bar.low)
            continue
        prior_close = bars[index - 1].close
        output.append(
            max(
                bar.high - bar.low,
                abs(bar.high - prior_close),
                abs(bar.low - prior_close),
            )
        )
    return output


def _confirmed_pivots(
    bars: list[AggregateBar],
    true_ranges: list[float],
    config: StructureConfig,
) -> list[_Pivot]:
    pivots: list[_Pivot] = []
    prior_high: _Pivot | None = None
    prior_low: _Pivot | None = None
    left = config.pivot_left_bars
    right = config.pivot_right_bars
    for index in range(left, len(bars) - right):
        bar = bars[index]
        neighbors = bars[index - left : index] + bars[index + 1 : index + right + 1]
        atr = max(
            _rolling_mean(true_ranges, index, config.atr_window),
            config.tick_size,
        )
        high_prominence = bar.high - min(candidate.low for candidate in neighbors)
        low_prominence = max(candidate.high for candidate in neighbors) - bar.low
        minimum = max(
            config.minimum_pivot_prominence_atr * atr,
            2 * config.tick_size,
        )
        detected_at = bars[index + right].close_time
        if all(bar.high > candidate.high for candidate in neighbors) and high_prominence >= minimum:
            classification = _high_classification(
                bar.high,
                prior_high.level if prior_high else None,
                config.tick_size,
            )
            pivot = _Pivot(
                kind="HIGH",
                classification=classification,
                index=index,
                level=bar.high,
                timestamp=bar.open_time,
                detected_at=detected_at,
                atr=atr,
                prominence_atr=high_prominence / atr,
                confidence=round(
                    clamp(55 + min(2.0, high_prominence / atr) * 17.5, 55, 90),
                    2,
                ),
            )
            pivots.append(pivot)
            prior_high = pivot
        if all(bar.low < candidate.low for candidate in neighbors) and low_prominence >= minimum:
            classification = _low_classification(
                bar.low,
                prior_low.level if prior_low else None,
                config.tick_size,
            )
            pivot = _Pivot(
                kind="LOW",
                classification=classification,
                index=index,
                level=bar.low,
                timestamp=bar.open_time,
                detected_at=detected_at,
                atr=atr,
                prominence_atr=low_prominence / atr,
                confidence=round(
                    clamp(55 + min(2.0, low_prominence / atr) * 17.5, 55, 90),
                    2,
                ),
            )
            pivots.append(pivot)
            prior_low = pivot
    return sorted(pivots, key=lambda item: (item.index, item.kind))


def _high_classification(
    level: float,
    prior: float | None,
    tick_size: float,
) -> str:
    if prior is None:
        return "SWING_HIGH"
    if level > prior + tick_size:
        return "HIGHER_HIGH"
    if level < prior - tick_size:
        return "LOWER_HIGH"
    return "EQUAL_HIGH"


def _low_classification(
    level: float,
    prior: float | None,
    tick_size: float,
) -> str:
    if prior is None:
        return "SWING_LOW"
    if level > prior + tick_size:
        return "HIGHER_LOW"
    if level < prior - tick_size:
        return "LOWER_LOW"
    return "EQUAL_LOW"


def _trend_label(
    high_pivots: list[_Pivot],
    low_pivots: list[_Pivot],
) -> str:
    high_state = high_pivots[-1].classification if high_pivots else "UNKNOWN"
    low_state = low_pivots[-1].classification if low_pivots else "UNKNOWN"
    if high_state == "HIGHER_HIGH" and low_state == "HIGHER_LOW":
        return "BULLISH"
    if high_state == "LOWER_HIGH" and low_state == "LOWER_LOW":
        return "BEARISH"
    if high_state == "EQUAL_HIGH" and low_state == "EQUAL_LOW":
        return "RANGE"
    return "MIXED_OR_TRANSITIONING"


def _pivot_detection(
    pivot: _Pivot,
    timeframe: str,
    config: StructureConfig,
) -> StructureDetection:
    direction = "BULLISH" if pivot.kind == "LOW" else "BEARISH"
    invalidation = (
        f"Complete {timeframe} close below {pivot.level - config.tick_size:.2f}"
        if pivot.kind == "LOW"
        else f"Complete {timeframe} close above {pivot.level + config.tick_size:.2f}"
    )
    return StructureDetection(
        kind=pivot.classification,
        direction=direction,
        timestamp=pivot.timestamp,
        detected_at=pivot.detected_at,
        price_level=round(pivot.level, 6),
        timeframe=timeframe,
        detection_method=(
            f"FRACTAL_{config.pivot_left_bars}L_{config.pivot_right_bars}R"
            f"_PROMINENCE_{config.minimum_pivot_prominence_atr:.2f}ATR"
        ),
        confidence=pivot.confidence,
        epistemic_status="CALCULATED",
        evidence={
            "base_kind": f"SWING_{pivot.kind}",
            "pivot_index": pivot.index,
            "atr_at_pivot": round(pivot.atr, 6),
            "prominence_atr": round(pivot.prominence_atr, 4),
            "confirmation_bars_required": config.pivot_right_bars,
        },
        invalidation_condition=invalidation,
    )


def _level_detection(
    pivot: _Pivot,
    *,
    timeframe: str,
    kind: str,
    config: StructureConfig,
) -> StructureDetection:
    if kind == "SUPPORT":
        invalidation = (
            f"Complete {timeframe} close below "
            f"{pivot.level - config.breakout_buffer_atr * pivot.atr:.2f}"
        )
        direction = "BULLISH"
    else:
        invalidation = (
            f"Complete {timeframe} close above "
            f"{pivot.level + config.breakout_buffer_atr * pivot.atr:.2f}"
        )
        direction = "BEARISH"
    return StructureDetection(
        kind=kind,
        direction=direction,
        timestamp=pivot.timestamp,
        detected_at=pivot.detected_at,
        price_level=round(pivot.level, 6),
        timeframe=timeframe,
        detection_method="LATEST_CONFIRMED_QUALIFYING_SWING",
        confidence=pivot.confidence,
        epistemic_status="CALCULATED",
        evidence={
            "source_pivot": pivot.classification,
            "atr_at_pivot": round(pivot.atr, 6),
            "prominence_atr": round(pivot.prominence_atr, 4),
        },
        invalidation_condition=invalidation,
    )


def _breakout_detections(
    bars: list[AggregateBar],
    pivots: list[_Pivot],
    true_ranges: list[float],
    *,
    timeframe: str,
    config: StructureConfig,
) -> list[StructureDetection]:
    output: list[StructureDetection] = []
    for pivot in pivots[-16:]:
        first_eligible = pivot.index + config.pivot_right_bars + 1
        break_index: int | None = None
        threshold = pivot.level
        for index in range(first_eligible, len(bars)):
            atr = max(
                _rolling_mean(true_ranges, index, config.atr_window),
                config.tick_size,
            )
            buffer = max(config.breakout_buffer_atr * atr, 2 * config.tick_size)
            threshold = pivot.level + buffer if pivot.kind == "HIGH" else pivot.level - buffer
            crossed = (
                bars[index].close > threshold
                if pivot.kind == "HIGH"
                else bars[index].close < threshold
            )
            if crossed:
                break_index = index
                break
        if break_index is None:
            continue
        prior_high = next(
            (
                candidate
                for candidate in reversed(pivots)
                if candidate.kind == "HIGH" and candidate.index <= pivot.index
            ),
            None,
        )
        prior_low = next(
            (
                candidate
                for candidate in reversed(pivots)
                if candidate.kind == "LOW" and candidate.index < break_index
            ),
            None,
        )
        bullish_shift = (
            pivot.kind == "HIGH"
            and prior_high is not None
            and prior_high.classification == "LOWER_HIGH"
            and prior_low is not None
            and prior_low.classification == "LOWER_LOW"
        )
        bearish_shift = (
            pivot.kind == "LOW"
            and prior_low is not None
            and prior_low.classification == "HIGHER_LOW"
            and prior_high is not None
            and prior_high.classification == "HIGHER_HIGH"
        )
        if bullish_shift:
            kind = "MARKET_STRUCTURE_SHIFT_BULLISH"
        elif bearish_shift:
            kind = "MARKET_STRUCTURE_SHIFT_BEARISH"
        else:
            kind = (
                "BREAK_OF_STRUCTURE_BULLISH"
                if pivot.kind == "HIGH"
                else "BREAK_OF_STRUCTURE_BEARISH"
            )
        bar = bars[break_index]
        output.append(
            StructureDetection(
                kind=kind,
                direction="BULLISH" if pivot.kind == "HIGH" else "BEARISH",
                timestamp=bar.close_time,
                detected_at=bar.close_time,
                price_level=round(pivot.level, 6),
                timeframe=timeframe,
                detection_method="CLOSE_BEYOND_CONFIRMED_SWING_PLUS_ATR_BUFFER",
                confidence=78.0 if "SHIFT" in kind else 74.0,
                epistemic_status="CALCULATED",
                evidence={
                    "broken_pivot": pivot.classification,
                    "pivot_detected_at": pivot.detected_at.isoformat(),
                    "break_close": round(bar.close, 6),
                    "threshold": round(threshold, 6),
                    "buffer_atr_multiple": config.breakout_buffer_atr,
                    "source_bar_ids": list(bar.source_ids),
                },
                invalidation_condition=(
                    f"Complete {timeframe} close back "
                    f"{'below' if pivot.kind == 'HIGH' else 'above'} {pivot.level:.2f}"
                ),
            )
        )
    return output[-8:]


def _latest_price_action_detections(
    bars: list[AggregateBar],
    pivots: list[_Pivot],
    true_ranges: list[float],
    *,
    timeframe: str,
    config: StructureConfig,
) -> list[StructureDetection]:
    output: list[StructureDetection] = []
    highs = [pivot for pivot in pivots if pivot.kind == "HIGH"]
    lows = [pivot for pivot in pivots if pivot.kind == "LOW"]
    latest = bars[-1]
    atr = max(
        _rolling_mean(true_ranges, len(true_ranges) - 1, config.atr_window),
        config.tick_size,
    )
    buffer = max(config.breakout_buffer_atr * atr, 2 * config.tick_size)
    confirmation = bars[-config.acceptance_bars :]

    if highs:
        resistance = highs[-1]
        threshold = resistance.level + buffer
        if (
            resistance.detected_at <= confirmation[0].open_time
            and len(confirmation) == config.acceptance_bars
            and all(bar.close > threshold for bar in confirmation)
        ):
            output.append(
                _price_action_detection(
                    kind="ACCEPTANCE_ABOVE_RESISTANCE",
                    direction="BULLISH",
                    bar=latest,
                    level=resistance.level,
                    timeframe=timeframe,
                    method="CONSECUTIVE_CLOSES_BEYOND_ATR_BUFFER",
                    confidence=80.0,
                    status="INFERRED",
                    evidence={
                        "threshold": round(threshold, 6),
                        "confirmation_closes": [round(bar.close, 6) for bar in confirmation],
                        "required_closes": config.acceptance_bars,
                        "atr14": round(atr, 6),
                    },
                    invalidation=(f"Complete {timeframe} close back below {resistance.level:.2f}"),
                )
            )
            tolerance = config.retest_tolerance_atr * atr
            if latest.low <= resistance.level + tolerance and latest.close > resistance.level:
                output.append(
                    _price_action_detection(
                        kind="RETEST_HELD_ABOVE_RESISTANCE",
                        direction="BULLISH",
                        bar=latest,
                        level=resistance.level,
                        timeframe=timeframe,
                        method="POST_BREAK_TOUCH_WITH_CLOSE_HOLD",
                        confidence=76.0,
                        status="INFERRED",
                        evidence={
                            "tolerance": round(tolerance, 6),
                            "bar_low": round(latest.low, 6),
                            "bar_close": round(latest.close, 6),
                        },
                        invalidation=(f"Complete {timeframe} close below {resistance.level:.2f}"),
                    )
                )
        if latest.high > threshold and latest.close < resistance.level:
            output.append(
                _price_action_detection(
                    kind="REJECTION_ABOVE_RESISTANCE",
                    direction="BEARISH",
                    bar=latest,
                    level=resistance.level,
                    timeframe=timeframe,
                    method="WICK_BEYOND_BUFFER_CLOSE_BACK_INSIDE",
                    confidence=72.0,
                    status="INFERRED",
                    evidence={
                        "threshold": round(threshold, 6),
                        "bar_high": round(latest.high, 6),
                        "bar_close": round(latest.close, 6),
                    },
                    invalidation=(f"Complete {timeframe} close above {threshold:.2f}"),
                )
            )
        prior_break = next(
            (bar for bar in reversed(bars[-7:-1]) if bar.close > threshold),
            None,
        )
        if prior_break is not None and latest.close < resistance.level:
            output.extend(
                _failed_breakout_pair(
                    side="LONG",
                    bar=latest,
                    breakout_bar=prior_break,
                    level=resistance.level,
                    timeframe=timeframe,
                )
            )

    if lows:
        support = lows[-1]
        threshold = support.level - buffer
        if (
            support.detected_at <= confirmation[0].open_time
            and len(confirmation) == config.acceptance_bars
            and all(bar.close < threshold for bar in confirmation)
        ):
            output.append(
                _price_action_detection(
                    kind="ACCEPTANCE_BELOW_SUPPORT",
                    direction="BEARISH",
                    bar=latest,
                    level=support.level,
                    timeframe=timeframe,
                    method="CONSECUTIVE_CLOSES_BEYOND_ATR_BUFFER",
                    confidence=80.0,
                    status="INFERRED",
                    evidence={
                        "threshold": round(threshold, 6),
                        "confirmation_closes": [round(bar.close, 6) for bar in confirmation],
                        "required_closes": config.acceptance_bars,
                        "atr14": round(atr, 6),
                    },
                    invalidation=(f"Complete {timeframe} close back above {support.level:.2f}"),
                )
            )
            tolerance = config.retest_tolerance_atr * atr
            if latest.high >= support.level - tolerance and latest.close < support.level:
                output.append(
                    _price_action_detection(
                        kind="RETEST_HELD_BELOW_SUPPORT",
                        direction="BEARISH",
                        bar=latest,
                        level=support.level,
                        timeframe=timeframe,
                        method="POST_BREAK_TOUCH_WITH_CLOSE_HOLD",
                        confidence=76.0,
                        status="INFERRED",
                        evidence={
                            "tolerance": round(tolerance, 6),
                            "bar_high": round(latest.high, 6),
                            "bar_close": round(latest.close, 6),
                        },
                        invalidation=(f"Complete {timeframe} close above {support.level:.2f}"),
                    )
                )
        if latest.low < threshold and latest.close > support.level:
            output.append(
                _price_action_detection(
                    kind="REJECTION_BELOW_SUPPORT",
                    direction="BULLISH",
                    bar=latest,
                    level=support.level,
                    timeframe=timeframe,
                    method="WICK_BEYOND_BUFFER_CLOSE_BACK_INSIDE",
                    confidence=72.0,
                    status="INFERRED",
                    evidence={
                        "threshold": round(threshold, 6),
                        "bar_low": round(latest.low, 6),
                        "bar_close": round(latest.close, 6),
                    },
                    invalidation=(f"Complete {timeframe} close below {threshold:.2f}"),
                )
            )
        prior_break = next(
            (bar for bar in reversed(bars[-7:-1]) if bar.close < threshold),
            None,
        )
        if prior_break is not None and latest.close > support.level:
            output.extend(
                _failed_breakout_pair(
                    side="SHORT",
                    bar=latest,
                    breakout_bar=prior_break,
                    level=support.level,
                    timeframe=timeframe,
                )
            )
    return output


def _failed_breakout_pair(
    *,
    side: str,
    bar: AggregateBar,
    breakout_bar: AggregateBar,
    level: float,
    timeframe: str,
) -> list[StructureDetection]:
    direction = "BEARISH" if side == "LONG" else "BULLISH"
    invalidation = (
        f"Complete {timeframe} close back above {level:.2f}"
        if side == "LONG"
        else f"Complete {timeframe} close back below {level:.2f}"
    )
    base_evidence = {
        "failed_side": side,
        "initial_break_close": round(breakout_bar.close, 6),
        "initial_break_at": breakout_bar.close_time.isoformat(),
        "return_close": round(bar.close, 6),
    }
    return [
        _price_action_detection(
            kind="FAILED_BREAKOUT",
            direction=direction,
            bar=bar,
            level=level,
            timeframe=timeframe,
            method="CLOSE_OUTSIDE_THEN_CLOSE_BACK_INSIDE",
            confidence=79.0,
            status="INFERRED",
            evidence=base_evidence,
            invalidation=invalidation,
        ),
        _price_action_detection(
            kind=f"TRAPPED_BREAKOUT_{side}S",
            direction=direction,
            bar=bar,
            level=level,
            timeframe=timeframe,
            method="FAILED_BREAKOUT_PARTICIPANT_RISK_PROXY",
            confidence=65.0,
            status="INFERRED",
            evidence={
                **base_evidence,
                "classification_warning": (
                    "Trapped positioning is inferred from price behaviour; "
                    "participant inventory is not directly observed."
                ),
            },
            invalidation=invalidation,
        ),
    ]


def _price_action_detection(
    *,
    kind: str,
    direction: str,
    bar: AggregateBar,
    level: float,
    timeframe: str,
    method: str,
    confidence: float,
    status: str,
    evidence: dict[str, Any],
    invalidation: str,
) -> StructureDetection:
    return StructureDetection(
        kind=kind,
        direction=direction,
        timestamp=bar.close_time,
        detected_at=bar.close_time,
        price_level=round(level, 6),
        timeframe=timeframe,
        detection_method=method,
        confidence=confidence,
        epistemic_status=status,
        evidence={
            **evidence,
            "source_bar_ids": list(bar.source_ids),
        },
        invalidation_condition=invalidation,
    )


def _state_detections(
    bars: list[AggregateBar],
    true_ranges: list[float],
    *,
    timeframe: str,
    config: StructureConfig,
) -> tuple[
    list[StructureDetection],
    float | None,
    float | None,
    float | None,
    float | None,
]:
    output: list[StructureDetection] = []
    latest = bars[-1]
    atr = max(
        _rolling_mean(true_ranges, len(true_ranges) - 1, config.atr_window),
        config.tick_size,
    )
    recent_count = config.compression_recent_bars
    baseline_end = len(true_ranges) - recent_count
    compression_ratio: float | None = None
    if baseline_end >= recent_count:
        recent_mean = sum(true_ranges[-recent_count:]) / recent_count
        baseline_values = true_ranges[
            max(0, baseline_end - config.range_window_bars) : baseline_end
        ]
        baseline_mean = sum(baseline_values) / len(baseline_values)
        if baseline_mean:
            compression_ratio = recent_mean / baseline_mean
            if compression_ratio <= config.compression_ratio:
                output.append(
                    _state_detection(
                        kind="COMPRESSION",
                        direction="NEUTRAL",
                        bar=latest,
                        timeframe=timeframe,
                        confidence=76.0,
                        evidence={
                            "recent_true_range_mean": round(recent_mean, 6),
                            "baseline_true_range_mean": round(baseline_mean, 6),
                            "ratio": round(compression_ratio, 4),
                            "threshold": config.compression_ratio,
                        },
                        invalidation=(
                            f"True-range ratio rises above {config.compression_ratio:.2f}"
                        ),
                    )
                )
            elif compression_ratio >= config.expansion_ratio:
                output.append(
                    _state_detection(
                        kind="EXPANSION",
                        direction=(
                            "BULLISH"
                            if latest.close > latest.open
                            else "BEARISH"
                            if latest.close < latest.open
                            else "NEUTRAL"
                        ),
                        bar=latest,
                        timeframe=timeframe,
                        confidence=76.0,
                        evidence={
                            "recent_true_range_mean": round(recent_mean, 6),
                            "baseline_true_range_mean": round(baseline_mean, 6),
                            "ratio": round(compression_ratio, 4),
                            "threshold": config.expansion_ratio,
                        },
                        invalidation=(f"True-range ratio falls below {config.expansion_ratio:.2f}"),
                    )
                )

    latest_range = max(latest.high - latest.low, config.tick_size)
    body_ratio = abs(latest.close - latest.open) / latest_range
    range_atr = true_ranges[-1] / atr
    if range_atr >= config.displacement_atr and body_ratio >= config.displacement_body_ratio:
        direction = "BULLISH" if latest.close > latest.open else "BEARISH"
        output.append(
            _state_detection(
                kind="DISPLACEMENT",
                direction=direction,
                bar=latest,
                timeframe=timeframe,
                confidence=82.0,
                evidence={
                    "true_range_atr": round(range_atr, 4),
                    "body_ratio": round(body_ratio, 4),
                    "minimum_true_range_atr": config.displacement_atr,
                    "minimum_body_ratio": config.displacement_body_ratio,
                },
                invalidation=(
                    f"Complete {timeframe} close through the displacement-bar midpoint "
                    f"{(latest.open + latest.close) / 2:.2f}"
                ),
            )
        )

    momentum_atr: float | None = None
    if len(bars) >= 6:
        momentum_atr = (latest.close - bars[-6].close) / atr
        if abs(momentum_atr) >= 0.50:
            output.append(
                _state_detection(
                    kind="MOMENTUM",
                    direction="BULLISH" if momentum_atr > 0 else "BEARISH",
                    bar=latest,
                    timeframe=timeframe,
                    confidence=70.0,
                    evidence={
                        "five_bar_change_atr": round(momentum_atr, 4),
                        "atr14": round(atr, 6),
                    },
                    invalidation=(
                        f"Five-bar momentum falls back inside +/-0.50 ATR on {timeframe}"
                    ),
                )
            )

    range_window = bars[-config.range_window_bars :]
    range_low = min(bar.low for bar in range_window)
    range_high = max(bar.high for bar in range_window)
    range_width_atr = (range_high - range_low) / atr
    if len(range_window) == config.range_window_bars and range_width_atr <= 5.0:
        output.append(
            _state_detection(
                kind="RANGE",
                direction="NEUTRAL",
                bar=latest,
                timeframe=timeframe,
                confidence=68.0,
                evidence={
                    "range_low": round(range_low, 6),
                    "range_high": round(range_high, 6),
                    "range_width_atr": round(range_width_atr, 4),
                    "lookback_bars": config.range_window_bars,
                },
                invalidation=(
                    f"Complete {timeframe} close outside "
                    f"{range_low:.2f}-{range_high:.2f} plus breakout buffer"
                ),
            )
        )
    return output, compression_ratio, momentum_atr, range_low, range_high


def _state_detection(
    *,
    kind: str,
    direction: str,
    bar: AggregateBar,
    timeframe: str,
    confidence: float,
    evidence: dict[str, Any],
    invalidation: str,
) -> StructureDetection:
    return StructureDetection(
        kind=kind,
        direction=direction,
        timestamp=bar.close_time,
        detected_at=bar.close_time,
        price_level=round(bar.close, 6),
        timeframe=timeframe,
        detection_method=f"DETERMINISTIC_{STRUCTURE_RULESET_VERSION.upper()}",
        confidence=confidence,
        epistemic_status="CALCULATED",
        evidence={
            **evidence,
            "source_bar_ids": list(bar.source_ids),
        },
        invalidation_condition=invalidation,
    )


def _structure_data_hash(
    bars: list[MinuteBar],
    as_of: datetime,
    config: StructureConfig,
) -> str:
    digest = hashlib.sha256()
    digest.update(STRUCTURE_RULESET_VERSION.encode())
    digest.update(as_of.isoformat().encode())
    digest.update(json.dumps(asdict(config), sort_keys=True, separators=(",", ":")).encode())
    for bar in bars:
        digest.update(
            (
                f"{bar.id}|{bar.open_time.isoformat()}|{bar.available_at.isoformat()}|"
                f"{bar.open:.6f}|{bar.high:.6f}|{bar.low:.6f}|{bar.close:.6f}"
            ).encode()
        )
    return digest.hexdigest()
