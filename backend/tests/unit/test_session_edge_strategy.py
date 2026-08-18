from datetime import UTC, date, datetime, timedelta

from gold_intel.backtesting.session_edge_strategy import (
    SessionExecutionBar,
    SessionStrategyConfig,
    SessionStrategySetup,
    run_delayed_reclaim_strategy,
)

ENTRY = datetime(2024, 1, 2, 8, 0, tzinfo=UTC)


def _setup(
    *,
    reclaim_delay_minutes: int = 5,
    alignment: str = "ALIGNED",
) -> SessionStrategySetup:
    sweep_time = ENTRY - timedelta(minutes=15)
    reclaim_time = sweep_time + timedelta(minutes=reclaim_delay_minutes)
    return SessionStrategySetup(
        source_opportunity_id="opportunity-1",
        source_run_id="run-1",
        source_data_hash="source-hash",
        session_date=date(2024, 1, 2),
        status="TRIGGERED",
        side="LONG",
        signal_time=ENTRY,
        entry_time=ENTRY,
        entry_reference_price=100.0,
        invalidation_price=99.0,
        risk_distance=1.0,
        bias_alignment=alignment,
        event_risk="UNKNOWN",
        regime_label="TEST_REGIME",
        dominant_driver="REAL_YIELD",
        facts={
            "attempts": [
                {
                    "sweep_time": sweep_time.isoformat(),
                    "reclaim_time": reclaim_time.isoformat(),
                }
            ]
        },
        outcomes=[{"horizon_minutes": 240, "status": "COMPLETE"}],
        evidence={"primary_attempt_index": 0},
    )


def _bars(
    *,
    collide_stop_and_target: bool = False,
    missing_spread: bool = False,
) -> list[SessionExecutionBar]:
    rows: list[SessionExecutionBar] = []
    for offset in range(300):
        open_time = ENTRY + timedelta(minutes=offset)
        high = 100.2
        low = 99.8
        close = 100.0
        if offset == 1:
            high = 101.1
            close = 101.0
            if collide_stop_and_target:
                low = 98.9
        rows.append(
            SessionExecutionBar(
                open_time=open_time,
                close_time=open_time + timedelta(minutes=1),
                open=100.0,
                high=high,
                low=low,
                close=close,
                spread_price=None if missing_spread else 0.10,
                available_at=open_time + timedelta(minutes=1),
                source_record_key=f"bar-{offset}",
            )
        )
    return rows


def _run(
    setup: SessionStrategySetup,
    bars: list[SessionExecutionBar] | None = None,
    *,
    mode: str = "DELAYED_RECLAIM_PRICE_CONTROL",
):
    return run_delayed_reclaim_strategy(
        [setup],
        bars or _bars(),
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 3, tzinfo=UTC),
        config=SessionStrategyConfig(
            strategy_mode=mode,  # type: ignore[arg-type]
            calculate_robustness=True,
        ),
    )


def test_delayed_reclaim_executes_next_bar_with_explicit_costs() -> None:
    result = _run(_setup())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "TARGET"
    assert trade.gross_pnl == 100
    assert trade.costs == 27
    assert trade.net_pnl == 73
    assert trade.r_multiple == 0.73
    assert trade.evidence["spread_cost_usd"] == 10
    assert trade.evidence["slippage_cost_usd"] == 10
    assert trade.evidence["commission_usd"] == 7
    assert result.metrics["net_expectancy_r"] == 0.73
    assert result.metrics["unknown_catalyst_trades"] == 1
    assert len(result.metrics["robustness"]["parameter_neighbourhood"]) == 9
    assert result.metrics["development_gate"]["status"] == "FAIL"


def test_same_bar_reclaim_is_not_silently_included() -> None:
    result = _run(_setup(reclaim_delay_minutes=0))

    assert result.trades == ()
    assert result.exclusions == {"SAME_BAR_RECLAIM": 1}


def test_primary_variant_requires_fundamental_alignment() -> None:
    result = _run(
        _setup(alignment="OPPOSED"),
        mode="DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED",
    )

    assert result.trades == ()
    assert result.exclusions == {"FUNDAMENTAL_OPPOSED": 1}


def test_same_minute_stop_and_target_collision_is_stop_first() -> None:
    result = _run(
        _setup(),
        _bars(collide_stop_and_target=True),
    )

    trade = result.trades[0]
    assert trade.exit_reason == "STOP"
    assert trade.gross_pnl == -100
    assert trade.net_pnl == -127
    assert trade.r_multiple == -1.27


def test_unknown_observed_spread_excludes_the_trade() -> None:
    result = _run(_setup(), _bars(missing_spread=True))

    assert result.trades == ()
    assert result.exclusions == {"ENTRY_SPREAD_UNKNOWN": 1}


def test_late_bar_revision_cannot_replace_point_in_time_execution_bar() -> None:
    bars = _bars()
    bars.append(
        SessionExecutionBar(
            open_time=ENTRY,
            close_time=ENTRY + timedelta(minutes=1),
            open=9_999,
            high=9_999,
            low=9_999,
            close=9_999,
            spread_price=99,
            available_at=ENTRY + timedelta(hours=1),
            source_record_key="late-revision",
        )
    )

    result = _run(_setup(), bars)

    assert result.trades[0].reference_entry_price == 100
    assert result.trades[0].evidence["entry_bar_source_record_key"] == "bar-0"
