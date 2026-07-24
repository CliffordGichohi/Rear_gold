from datetime import UTC, datetime, timedelta

from gold_intel.analytics.liquidity import (
    LiquidityBar,
    calculate_liquidity_snapshot,
)


def _window(
    end_at: datetime,
    *,
    spread_points: int,
    tick_volume: float = 100,
    half_range: float = 0.10,
) -> list[LiquidityBar]:
    start = end_at - timedelta(minutes=15)
    return [
        LiquidityBar(
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            high=2400 + half_range,
            low=2400 - half_range,
            close=2400,
            tick_volume=tick_volume,
            spread_points=spread_points,
            spread_price=spread_points * 0.01,
            available_at=start + timedelta(minutes=index + 1),
        )
        for index in range(15)
    ]


def _history(
    cutoff: datetime,
    *,
    current_spread: int = 5,
    current_tick_volume: float = 100,
    current_half_range: float = 0.10,
) -> list[LiquidityBar]:
    bars: list[LiquidityBar] = []
    for days_ago in (4, 3, 2, 1):
        bars.extend(
            _window(
                cutoff - timedelta(days=days_ago),
                spread_points=5,
            )
        )
    bars.extend(
        _window(
            cutoff,
            spread_points=current_spread,
            tick_volume=current_tick_volume,
            half_range=current_half_range,
        )
    )
    return bars


def test_normal_liquidity_uses_same_session_point_in_time_baseline() -> None:
    cutoff = datetime(2026, 7, 24, 15, 0, tzinfo=UTC)

    result = calculate_liquidity_snapshot(
        _history(cutoff),
        cutoff,
        provider_code="IC_MARKETS_MT5",
        baseline_days=7,
        minimum_baseline_bars=30,
    )

    assert result.status == "NORMAL"
    assert result.epistemic_status == "CALCULATED"
    assert result.current_bar_count == 15
    assert result.spread_observation_count == 60
    assert result.current_spread_points == 5
    assert result.spread_percentile == 50
    assert result.execution_confidence_multiplier == 1
    assert result.data_quality_score == 100
    assert result.evidence["source"] == "IC_MARKETS_MT5"


def test_abnormal_spread_reduces_execution_confidence_without_direction() -> None:
    cutoff = datetime(2026, 7, 24, 15, 0, tzinfo=UTC)

    result = calculate_liquidity_snapshot(
        _history(cutoff, current_spread=30),
        cutoff,
        provider_code="IC_MARKETS_MT5",
        baseline_days=7,
        minimum_baseline_bars=30,
    )

    assert result.status == "ABNORMAL"
    assert result.spread_percentile == 100
    assert result.execution_confidence_multiplier == 0.5
    assert "not a directional gold signal" in result.explanation


def test_future_bar_cannot_change_historical_liquidity_snapshot() -> None:
    cutoff = datetime(2026, 7, 24, 15, 0, tzinfo=UTC)
    history = _history(cutoff)
    original = calculate_liquidity_snapshot(
        history,
        cutoff,
        baseline_days=7,
        minimum_baseline_bars=30,
    )
    future = LiquidityBar(
        open_time=cutoff,
        close_time=cutoff + timedelta(minutes=1),
        high=2450,
        low=2350,
        close=2400,
        tick_volume=10_000,
        spread_points=1_000,
        spread_price=10,
        available_at=cutoff + timedelta(minutes=1),
    )

    replayed = calculate_liquidity_snapshot(
        [*history, future],
        cutoff,
        baseline_days=7,
        minimum_baseline_bars=30,
    )

    assert replayed.status == original.status
    assert replayed.current_spread_points == original.current_spread_points
    assert replayed.data_hash == original.data_hash


def test_insufficient_spread_baseline_remains_unknown() -> None:
    cutoff = datetime(2026, 7, 24, 15, 0, tzinfo=UTC)

    result = calculate_liquidity_snapshot(
        _history(cutoff),
        cutoff,
        baseline_days=7,
        minimum_baseline_bars=100,
    )

    assert result.status == "UNKNOWN"
    assert result.epistemic_status == "UNKNOWN"
    assert result.execution_confidence_multiplier == 0.5
    assert result.spread_observation_count == 60
    assert result.warnings
