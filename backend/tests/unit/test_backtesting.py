from dataclasses import replace
from datetime import UTC, datetime, timedelta

from gold_intel.analytics.fundamentals import FundamentalState
from gold_intel.backtesting.engine import (
    BacktestBar,
    StrategyConfig,
    TradeResult,
    _bootstrap_mean_interval,
    _trade_order_monte_carlo,
    run_asia_range_acceptance,
)


def _designed_breakout(*, missing_asia_minute: bool = False) -> list[BacktestBar]:
    start = datetime(2026, 1, 5, 22, 0, tzinfo=UTC)
    output: list[BacktestBar] = []
    for minute in range(24 * 60):
        open_time = start + timedelta(minutes=minute)
        if missing_asia_minute and open_time == datetime(2026, 1, 6, 1, 17, tzinfo=UTC):
            continue
        close_time = open_time + timedelta(minutes=1)
        open_price = 2400.0
        close_price = 2400.0
        high = 2400.5
        low = 2399.5
        if (
            datetime(2026, 1, 6, 8, 0, tzinfo=UTC)
            <= open_time
            < datetime(2026, 1, 6, 8, 5, tzinfo=UTC)
        ):
            open_price, close_price, high, low = 2402.0, 2402.0, 2402.2, 2400.5
        elif (
            datetime(2026, 1, 6, 8, 5, tzinfo=UTC)
            <= open_time
            < datetime(2026, 1, 6, 8, 10, tzinfo=UTC)
        ):
            open_price, close_price, high, low = 2402.5, 2402.5, 2402.7, 2401.8
        elif (
            datetime(2026, 1, 6, 8, 10, tzinfo=UTC)
            <= open_time
            < datetime(2026, 1, 6, 8, 15, tzinfo=UTC)
        ):
            open_price, close_price, high, low = 2406.0, 2406.0, 2407.0, 2405.5
            if open_time == datetime(2026, 1, 6, 8, 10, tzinfo=UTC):
                open_price, low = 2402.6, 2402.4
        output.append(
            BacktestBar(
                open_time=open_time,
                close_time=close_time,
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=1,
                available_at=close_time,
            )
        )
    return output


def test_signal_is_filled_only_on_next_bar_and_costs_are_applied() -> None:
    bars = _designed_breakout()
    result = run_asia_range_acceptance(
        bars,
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
        config=StrategyConfig(),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_time == trade.signal_time
    assert trade.entry_price > trade.reference_entry_price
    assert trade.costs > 0
    assert trade.exit_reason == "TARGET"
    assert trade.r_multiple < 2.0
    assert result.metrics["expectancy_r_bootstrap_95ci"] == [None, None]
    assert result.metrics["monte_carlo_trade_order"]["status"] == "INSUFFICIENT_SAMPLE"


def _trade(sequence: int, net_pnl: float) -> TradeResult:
    timestamp = datetime(2026, 1, sequence, 8, 0, tzinfo=UTC)
    return TradeResult(
        sequence=sequence,
        side="LONG" if sequence % 2 else "SHORT",
        signal_time=timestamp,
        entry_time=timestamp + timedelta(minutes=5),
        exit_time=timestamp + timedelta(minutes=35),
        entry_price=2400,
        exit_price=2401,
        reference_entry_price=2400,
        reference_exit_price=2401,
        stop_price=2398,
        target_price=2404,
        quantity_lots=0.1,
        exit_reason="TARGET" if net_pnl > 0 else "STOP",
        gross_pnl=net_pnl + 1,
        costs=1,
        net_pnl=net_pnl,
        r_multiple=net_pnl / 100,
        mfe_r=max(0, net_pnl / 100),
        mae_r=max(0, -net_pnl / 100),
        holding_minutes=30,
        evidence={},
    )


def test_robustness_resampling_is_deterministic_and_ordered() -> None:
    r_values = [1.1, -0.8, 0.6, -1.0, 1.4, -0.4, 0.2]
    first_interval = _bootstrap_mean_interval(r_values, iterations=500)
    second_interval = _bootstrap_mean_interval(r_values, iterations=500)

    assert first_interval == second_interval
    assert first_interval[0] is not None
    assert first_interval[1] is not None
    assert first_interval[0] <= first_interval[1]

    trades = [
        _trade(sequence, pnl)
        for sequence, pnl in enumerate(
            [110, -80, 60, -100, 140, -40, 20],
            start=1,
        )
    ]
    first_monte_carlo = _trade_order_monte_carlo(
        trades,
        initial_equity=10_000,
        iterations=500,
    )
    second_monte_carlo = _trade_order_monte_carlo(
        trades,
        initial_equity=10_000,
        iterations=500,
    )

    assert first_monte_carlo == second_monte_carlo
    assert first_monte_carlo["status"] == "COMPLETED"
    assert (
        first_monte_carlo["drawdown_pct_p50"]
        <= first_monte_carlo["drawdown_pct_p95"]
        <= first_monte_carlo["drawdown_pct_p99"]
    )


def test_incomplete_asia_range_cannot_generate_a_trade() -> None:
    result = run_asia_range_acceptance(
        _designed_breakout(missing_asia_minute=True),
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
        config=StrategyConfig(),
    )

    assert result.trades == ()


def test_later_price_revision_is_not_used_at_original_decision_time() -> None:
    bars = _designed_breakout()
    original = bars[10]
    bars.append(
        BacktestBar(
            open_time=original.open_time,
            close_time=original.close_time,
            open=9999,
            high=9999,
            low=9999,
            close=9999,
            volume=1,
            available_at=datetime(2026, 1, 7, 0, 0, tzinfo=UTC),
        )
    )
    result = run_asia_range_acceptance(
        bars,
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
        config=StrategyConfig(),
    )

    assert len(result.trades) == 1
    assert result.trades[0].evidence["asia_high"] < 3000


def _fundamental_state(
    as_of: datetime,
    *,
    score: float,
    event_risk: str = "UNKNOWN",
) -> FundamentalState:
    return FundamentalState(
        as_of=as_of,
        directional_score=score,
        confidence=70,
        coverage=60,
        bias_label="MODERATELY_BULLISH" if score > 0 else "MODERATELY_BEARISH",
        regime_label="TEST_REGIME",
        reaction_function="TEST_REACTION_FUNCTION",
        dominant_driver="REAL_YIELD",
        main_contradiction=None,
        event_risk=event_risk,
        upcoming_catalyst=(
            {
                "event_code": "US_CPI",
                "scheduled_at": datetime(
                    2026,
                    1,
                    6,
                    10,
                    0,
                    tzinfo=UTC,
                ).isoformat(),
                "importance": 5,
            }
            if event_risk != "UNKNOWN"
            else None
        ),
        components=(),
        layers=(),
        reasoning={"score_is_not_trade_signal": True},
        data_hash=f"fundamental:{score}",
    )


def test_fundamental_gate_rejects_a_mechanical_trigger_against_the_bias() -> None:
    result = run_asia_range_acceptance(
        _designed_breakout(),
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
        config=StrategyConfig(
            strategy_mode="FUNDAMENTAL_ALIGNED",
            allow_unknown_liquidity=True,
        ),
        fundamental_state_at=lambda at: _fundamental_state(at, score=-20),
    )

    assert result.trades == ()
    assert result.metrics["mechanical_candidates"] == 1
    assert result.metrics["fundamental_gate_rejected"] == 1
    assert result.provenance["fundamental_gate"]["decisions"][0]["permitted"] is False


def test_fundamental_gate_allows_and_attaches_traceable_evidence() -> None:
    result = run_asia_range_acceptance(
        _designed_breakout(),
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
        config=StrategyConfig(
            strategy_mode="FUNDAMENTAL_ALIGNED",
            allow_unknown_liquidity=True,
        ),
        fundamental_state_at=lambda at: _fundamental_state(at, score=20),
    )

    assert len(result.trades) == 1
    evidence = result.trades[0].evidence["fundamental_permission"]
    assert evidence["directional_score"] == 20
    assert evidence["data_hash"] == "fundamental:20"


def test_book_aligned_mode_blocks_when_historical_liquidity_is_unknown() -> None:
    result = run_asia_range_acceptance(
        _designed_breakout(),
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
        config=StrategyConfig(strategy_mode="FUNDAMENTAL_ALIGNED"),
        fundamental_state_at=lambda at: _fundamental_state(at, score=20),
    )

    assert result.trades == ()
    assert (
        result.metrics["fundamental_gate_rejection_reasons"][
            "LIQUIDITY_UNKNOWN_GATE"
        ]
        == 1
    )
    decision = result.provenance["fundamental_gate"]["decisions"][0]
    assert decision["liquidity"]["status"] == "UNKNOWN"


def test_fundamental_gate_blocks_a_major_event_even_when_bias_aligns() -> None:
    result = run_asia_range_acceptance(
        _designed_breakout(),
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
        config=StrategyConfig(
            strategy_mode="FUNDAMENTAL_ALIGNED",
            allow_unknown_liquidity=True,
        ),
        fundamental_state_at=lambda at: _fundamental_state(
            at,
            score=20,
            event_risk="HIGH",
        ),
    )

    assert result.trades == ()
    assert result.metrics["fundamental_gate_rejection_reasons"]["MAJOR_EVENT_BLACKOUT"] == 1
    decision = result.provenance["fundamental_gate"]["decisions"][0]
    assert decision["event_risk"] == "HIGH"
    assert decision["upcoming_catalyst"]["event_code"] == "US_CPI"


def test_fundamental_gate_can_reconsider_after_the_event_blackout_clears() -> None:
    bars = [
        replace(
            bar,
            open=2406.0,
            high=2407.0,
            low=2405.5,
            close=2406.0,
        )
        if (
            datetime(2026, 1, 6, 8, 15, tzinfo=UTC)
            <= bar.open_time
            < datetime(2026, 1, 6, 8, 20, tzinfo=UTC)
        )
        else bar
        for bar in _designed_breakout()
    ]

    result = run_asia_range_acceptance(
        bars,
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
        config=StrategyConfig(
            strategy_mode="FUNDAMENTAL_ALIGNED",
            allow_unknown_liquidity=True,
        ),
        fundamental_state_at=lambda at: _fundamental_state(
            at,
            score=20,
            event_risk=("HIGH" if at <= datetime(2026, 1, 6, 8, 10, tzinfo=UTC) else "UNKNOWN"),
        ),
    )

    assert len(result.trades) == 1
    decisions = result.provenance["fundamental_gate"]["decisions"]
    assert [decision["reason"] for decision in decisions] == [
        "MAJOR_EVENT_BLACKOUT",
        "FUNDAMENTALS_ALIGNED",
    ]
    assert result.trades[0].signal_time == datetime(2026, 1, 6, 8, 15, tzinfo=UTC)
