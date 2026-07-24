from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, Literal

from gold_intel.analytics.sessions import session_at

LIQUIDITY_RULESET_VERSION = "broker-liquidity-1"
LiquidityStatus = Literal["NORMAL", "ELEVATED", "ABNORMAL", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class LiquidityBar:
    open_time: datetime
    close_time: datetime
    high: float
    low: float
    close: float
    tick_volume: float | None
    spread_points: int | None
    spread_price: float | None
    available_at: datetime


@dataclass(frozen=True, slots=True)
class LiquiditySnapshot:
    as_of: datetime
    latest_bar_at: datetime | None
    primary_session: str
    special_windows: tuple[str, ...]
    status: LiquidityStatus
    epistemic_status: Literal["CALCULATED", "UNKNOWN"]
    ruleset_version: str
    current_window_minutes: int
    current_bar_count: int
    baseline_bar_count: int
    spread_observation_count: int
    current_spread_points: float | None
    current_spread_price: float | None
    current_spread_bps: float | None
    baseline_spread_points: float | None
    p95_spread_points: float | None
    spread_percentile: float | None
    current_range_bps: float | None
    baseline_range_bps: float | None
    p95_range_bps: float | None
    range_percentile: float | None
    current_tick_volume: float | None
    baseline_tick_volume: float | None
    tick_volume_percentile: float | None
    execution_confidence_multiplier: float
    data_quality_score: float
    freshness_score: float
    explanation: str
    evidence: dict[str, Any]
    warnings: tuple[str, ...]
    data_hash: str


def calculate_liquidity_snapshot(
    bars: Sequence[LiquidityBar],
    as_of: datetime,
    *,
    provider_code: str = "UNKNOWN",
    current_window_minutes: int = 15,
    baseline_days: int = 20,
    minimum_baseline_bars: int = 100,
) -> LiquiditySnapshot:
    """Classify broker-quote liquidity without using information after ``as_of``.

    The current robust median is compared with historical one-minute observations
    from the same DST-aware primary session and special-window state. Spread is
    the IC Markets quote carried on each completed MT5 bar. Tick volume is broker
    activity, not centralized COMEX traded volume.
    """

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if current_window_minutes < 1:
        raise ValueError("current_window_minutes must be positive")
    if baseline_days < 1:
        raise ValueError("baseline_days must be positive")
    if minimum_baseline_bars < 1:
        raise ValueError("minimum_baseline_bars must be positive")

    cutoff = as_of.astimezone(UTC)
    canonical = _canonical_eligible_bars(bars, cutoff)
    context = session_at(cutoff)
    empty_hash = _data_hash(
        (),
        cutoff=cutoff,
        provider_code=provider_code,
        current_window_minutes=current_window_minutes,
        baseline_days=baseline_days,
        minimum_baseline_bars=minimum_baseline_bars,
    )
    if not canonical:
        return LiquiditySnapshot(
            as_of=cutoff,
            latest_bar_at=None,
            primary_session=context.primary,
            special_windows=context.special_windows,
            status="UNKNOWN",
            epistemic_status="UNKNOWN",
            ruleset_version=LIQUIDITY_RULESET_VERSION,
            current_window_minutes=current_window_minutes,
            current_bar_count=0,
            baseline_bar_count=0,
            spread_observation_count=0,
            current_spread_points=None,
            current_spread_price=None,
            current_spread_bps=None,
            baseline_spread_points=None,
            p95_spread_points=None,
            spread_percentile=None,
            current_range_bps=None,
            baseline_range_bps=None,
            p95_range_bps=None,
            range_percentile=None,
            current_tick_volume=None,
            baseline_tick_volume=None,
            tick_volume_percentile=None,
            execution_confidence_multiplier=0.5,
            data_quality_score=0.0,
            freshness_score=0.0,
            explanation="Liquidity is unknown because no closed, point-in-time eligible bars exist.",
            evidence={
                "source": provider_code,
                "spread_scope": "Provider quote, not centralized COMEX liquidity",
                "volume_scope": "MT5 tick activity, not centralized traded volume",
            },
            warnings=("No eligible broker-liquidity observations.",),
            data_hash=empty_hash,
        )

    latest = canonical[-1]
    analysis_clock = latest.close_time.astimezone(UTC)
    latest_context = session_at(analysis_clock)
    current_start = analysis_clock - timedelta(minutes=current_window_minutes)
    current = [bar for bar in canonical if current_start < bar.close_time <= analysis_clock]

    baseline_start = analysis_clock - timedelta(days=baseline_days)
    current_special = latest_context.special_windows
    baseline = [
        bar
        for bar in canonical
        if baseline_start <= bar.close_time <= current_start
        and _same_liquidity_bucket(
            bar.close_time,
            primary_session=latest_context.primary,
            special_windows=current_special,
        )
    ]

    current_spread_points_values = [
        float(bar.spread_points) for bar in current if bar.spread_points is not None
    ]
    current_spread_price_values = [
        bar.spread_price for bar in current if bar.spread_price is not None
    ]
    current_spread_bps_values = [
        spread_bps for bar in current if (spread_bps := _spread_bps(bar)) is not None
    ]
    baseline_spread_points_values = [
        float(bar.spread_points) for bar in baseline if bar.spread_points is not None
    ]
    current_range_values = [_range_bps(bar) for bar in current if bar.close > 0]
    baseline_range_values = [_range_bps(bar) for bar in baseline if bar.close > 0]
    current_tick_values = [float(bar.tick_volume) for bar in current if bar.tick_volume is not None]
    baseline_tick_values = [
        float(bar.tick_volume) for bar in baseline if bar.tick_volume is not None
    ]

    current_spread_points = _median_or_none(current_spread_points_values)
    current_spread_price = _median_or_none(current_spread_price_values)
    current_spread_bps = _median_or_none(current_spread_bps_values)
    baseline_spread_points = _median_or_none(baseline_spread_points_values)
    p95_spread_points = _percentile_value(baseline_spread_points_values, 95)
    spread_percentile = _percentile_rank(
        current_spread_points,
        baseline_spread_points_values,
    )
    current_range_bps = _median_or_none(current_range_values)
    baseline_range_bps = _median_or_none(baseline_range_values)
    p95_range_bps = _percentile_value(baseline_range_values, 95)
    range_percentile = _percentile_rank(current_range_bps, baseline_range_values)
    current_tick_volume = _median_or_none(current_tick_values)
    baseline_tick_volume = _median_or_none(baseline_tick_values)
    tick_volume_percentile = _percentile_rank(current_tick_volume, baseline_tick_values)

    warnings: list[str] = []
    if len(current) < current_window_minutes:
        warnings.append(
            f"Current {current_window_minutes}-minute window has only {len(current)} bars."
        )
    if not current_spread_points_values:
        warnings.append("Current bars contain no observed broker-spread values.")
    if len(baseline_spread_points_values) < minimum_baseline_bars:
        warnings.append(
            "The same-session spread baseline is too small for a reliable classification."
        )
    if not current_tick_values:
        warnings.append("Current bars contain no MT5 tick-activity values.")

    sufficient = (
        bool(current_spread_points_values)
        and len(baseline_spread_points_values) >= minimum_baseline_bars
    )
    status: LiquidityStatus
    if not sufficient:
        status = "UNKNOWN"
    elif _at_or_above(spread_percentile, 97.5) or _at_or_above(
        range_percentile,
        97.5,
    ):
        status = "ABNORMAL"
    elif _at_or_above(spread_percentile, 90.0) or _at_or_above(
        range_percentile,
        90.0,
    ):
        status = "ELEVATED"
    elif _at_or_below(tick_volume_percentile, 2.5) and _at_or_above(
        spread_percentile,
        75.0,
    ):
        status = "ABNORMAL"
    elif _at_or_below(tick_volume_percentile, 10.0) and _at_or_above(
        spread_percentile,
        60.0,
    ):
        status = "ELEVATED"
    else:
        status = "NORMAL"

    multiplier = {
        "NORMAL": 1.0,
        "ELEVATED": 0.75,
        "ABNORMAL": 0.5,
        "UNKNOWN": 0.5,
    }[status]
    spread_completeness = len(current_spread_points_values) / max(1, len(current))
    tick_completeness = len(current_tick_values) / max(1, len(current))
    window_completeness = min(1.0, len(current) / current_window_minutes)
    baseline_sufficiency = min(
        1.0,
        len(baseline_spread_points_values) / minimum_baseline_bars,
    )
    data_quality = round(
        100
        * (
            0.4 * spread_completeness
            + 0.2 * tick_completeness
            + 0.2 * window_completeness
            + 0.2 * baseline_sufficiency
        ),
        2,
    )
    freshness = _freshness_score(cutoff, latest.available_at)
    explanation = _explanation(
        status,
        spread_percentile=spread_percentile,
        range_percentile=range_percentile,
        tick_volume_percentile=tick_volume_percentile,
    )
    used = (*baseline, *current)

    return LiquiditySnapshot(
        as_of=cutoff,
        latest_bar_at=analysis_clock,
        primary_session=latest_context.primary,
        special_windows=latest_context.special_windows,
        status=status,
        epistemic_status="CALCULATED" if sufficient else "UNKNOWN",
        ruleset_version=LIQUIDITY_RULESET_VERSION,
        current_window_minutes=current_window_minutes,
        current_bar_count=len(current),
        baseline_bar_count=len(baseline),
        spread_observation_count=len(baseline_spread_points_values),
        current_spread_points=_rounded(current_spread_points, 3),
        current_spread_price=_rounded(current_spread_price, 6),
        current_spread_bps=_rounded(current_spread_bps, 4),
        baseline_spread_points=_rounded(baseline_spread_points, 3),
        p95_spread_points=_rounded(p95_spread_points, 3),
        spread_percentile=_rounded(spread_percentile, 2),
        current_range_bps=_rounded(current_range_bps, 4),
        baseline_range_bps=_rounded(baseline_range_bps, 4),
        p95_range_bps=_rounded(p95_range_bps, 4),
        range_percentile=_rounded(range_percentile, 2),
        current_tick_volume=_rounded(current_tick_volume, 3),
        baseline_tick_volume=_rounded(baseline_tick_volume, 3),
        tick_volume_percentile=_rounded(tick_volume_percentile, 2),
        execution_confidence_multiplier=multiplier,
        data_quality_score=data_quality,
        freshness_score=freshness,
        explanation=explanation,
        evidence={
            "source": provider_code,
            "source_timeframe": "1m",
            "spread_scope": "Broker quote observed on a completed bar; not a COMEX-wide spread",
            "volume_scope": "Broker tick activity; not centralized COMEX traded volume",
            "baseline_method": (
                f"Prior {baseline_days} calendar days, matched by DST-aware primary session "
                "and special-window state"
            ),
            "thresholds": {
                "elevated_percentile": 90.0,
                "abnormal_percentile": 97.5,
                "minimum_baseline_bars": minimum_baseline_bars,
            },
            "point_in_time_cutoff": cutoff.isoformat(),
        },
        warnings=tuple(warnings),
        data_hash=_data_hash(
            used,
            cutoff=cutoff,
            provider_code=provider_code,
            current_window_minutes=current_window_minutes,
            baseline_days=baseline_days,
            minimum_baseline_bars=minimum_baseline_bars,
        ),
    )


def _canonical_eligible_bars(
    bars: Sequence[LiquidityBar],
    cutoff: datetime,
) -> list[LiquidityBar]:
    if any(
        bar.open_time.tzinfo is None
        or bar.close_time.tzinfo is None
        or bar.available_at.tzinfo is None
        for bar in bars
    ):
        raise ValueError("liquidity bar timestamps must be timezone-aware")
    eligible = [
        bar
        for bar in bars
        if bar.close_time.astimezone(UTC) <= cutoff and bar.available_at.astimezone(UTC) <= cutoff
    ]
    canonical: dict[datetime, LiquidityBar] = {}
    for bar in sorted(eligible, key=lambda item: (item.open_time, item.available_at)):
        canonical[bar.open_time.astimezone(UTC)] = bar
    return sorted(canonical.values(), key=lambda item: item.open_time)


def _same_liquidity_bucket(
    timestamp: datetime,
    *,
    primary_session: str,
    special_windows: tuple[str, ...],
) -> bool:
    context = session_at(timestamp)
    return context.primary == primary_session and context.special_windows == special_windows


def _spread_bps(bar: LiquidityBar) -> float | None:
    if bar.spread_price is None or bar.close <= 0:
        return None
    return bar.spread_price / bar.close * 10_000


def _range_bps(bar: LiquidityBar) -> float:
    return max(0.0, bar.high - bar.low) / bar.close * 10_000


def _median_or_none(values: Sequence[float]) -> float | None:
    return float(median(values)) if values else None


def _percentile_value(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _percentile_rank(value: float | None, baseline: Sequence[float]) -> float | None:
    if value is None or not baseline:
        return None
    below = sum(item < value for item in baseline)
    equal = sum(item == value for item in baseline)
    return 100 * (below + 0.5 * equal) / len(baseline)


def _at_or_above(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _at_or_below(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def _freshness_score(cutoff: datetime, available_at: datetime) -> float:
    age_minutes = max(
        0.0,
        (cutoff - available_at.astimezone(UTC)).total_seconds() / 60,
    )
    if age_minutes <= 5:
        return 100.0
    if age_minutes >= 60:
        return 0.0
    return round(100 * (60 - age_minutes) / 55, 2)


def _explanation(
    status: LiquidityStatus,
    *,
    spread_percentile: float | None,
    range_percentile: float | None,
    tick_volume_percentile: float | None,
) -> str:
    if status == "UNKNOWN":
        return (
            "Broker liquidity is unknown because spread history is missing or the matched "
            "point-in-time baseline is insufficient."
        )
    metrics = (
        f"spread percentile {_display_percentile(spread_percentile)}, "
        f"one-minute range percentile {_display_percentile(range_percentile)}, and "
        f"tick-activity percentile {_display_percentile(tick_volume_percentile)}"
    )
    if status == "ABNORMAL":
        return (
            f"Broker execution conditions are abnormal ({metrics}). Reduce execution "
            "confidence; this is not a directional gold signal."
        )
    if status == "ELEVATED":
        return (
            f"Broker execution friction is elevated ({metrics}). Require additional "
            "confirmation and allow for slippage; this is not a directional signal."
        )
    return (
        f"Broker execution conditions are within their matched-session baseline ({metrics}). "
        "This does not create macro permission or a trade trigger."
    )


def _display_percentile(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f}"


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _data_hash(
    bars: Sequence[LiquidityBar],
    *,
    cutoff: datetime,
    provider_code: str,
    current_window_minutes: int,
    baseline_days: int,
    minimum_baseline_bars: int,
) -> str:
    payload = {
        "ruleset": LIQUIDITY_RULESET_VERSION,
        "provider_code": provider_code,
        "cutoff": cutoff.isoformat(),
        "current_window_minutes": current_window_minutes,
        "baseline_days": baseline_days,
        "minimum_baseline_bars": minimum_baseline_bars,
        "bars": [
            {
                "open_time": bar.open_time.astimezone(UTC).isoformat(),
                "close_time": bar.close_time.astimezone(UTC).isoformat(),
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "tick_volume": bar.tick_volume,
                "spread_points": bar.spread_points,
                "spread_price": bar.spread_price,
                "available_at": bar.available_at.astimezone(UTC).isoformat(),
            }
            for bar in bars
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
