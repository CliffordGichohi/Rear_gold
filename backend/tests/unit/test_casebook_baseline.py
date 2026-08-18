from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from gold_intel.backtesting.casebook_baseline import (
    BaselineCase,
    BaselineExecutionConfig,
    BaselinePriceBar,
    calculate_baseline_metrics,
    direction_for_control,
    simulate_baseline_case,
)

EXECUTION_HASH = "a" * 64


def _case(*, case_id: str = "SESSION-LONDON-20220103") -> BaselineCase:
    decision_at = datetime(2022, 1, 3, 8, 0, tzinfo=UTC)
    return BaselineCase(
        case_id=case_id,
        case_record_hash="b" * 64,
        session_code="LONDON",
        session_date=date(2022, 1, 3),
        decision_at=decision_at,
        observation_end=decision_at + timedelta(hours=4),
    )


def _bar(
    *,
    record_id: str,
    open_time: datetime,
    open_price: float,
    close_price: float,
    spread: float | None,
) -> BaselinePriceBar:
    close_time = open_time + timedelta(minutes=1)
    return BaselinePriceBar(
        record_id=record_id,
        record_hash="c" * 64,
        open_time=open_time,
        close_time=close_time,
        open=open_price,
        close=close_price,
        spread_price=spread,
        available_at=close_time,
    )


def _bars(
    case: BaselineCase,
) -> tuple[BaselinePriceBar, BaselinePriceBar]:
    return (
        _bar(
            record_id="ENTRY",
            open_time=case.decision_at + timedelta(minutes=1),
            open_price=2_000.0,
            close_price=2_000.2,
            spread=0.2,
        ),
        _bar(
            record_id="EXIT",
            open_time=case.observation_end - timedelta(minutes=1),
            open_price=2_001.8,
            close_price=2_002.0,
            spread=0.3,
        ),
    )


def _config() -> BaselineExecutionConfig:
    return BaselineExecutionConfig(execution_manifest_hash=EXECUTION_HASH)


def test_long_and_short_use_symmetric_frozen_costs() -> None:
    case = _case()
    entry, exit_ = _bars(case)

    long_trade = simulate_baseline_case(
        case,
        control_code="ALWAYS_LONG",
        entry_bar=entry,
        exit_bar=exit_,
        config=_config(),
    )
    short_trade = simulate_baseline_case(
        case,
        control_code="ALWAYS_SHORT",
        entry_bar=entry,
        exit_bar=exit_,
        config=_config(),
    )

    assert long_trade.executed_entry_price == pytest.approx(2_000.15)
    assert long_trade.executed_exit_price == pytest.approx(2_001.8)
    assert short_trade.executed_entry_price == pytest.approx(1_999.85)
    assert short_trade.executed_exit_price == pytest.approx(2_002.2)
    assert long_trade.gross_pnl_usd == pytest.approx(2.0)
    assert short_trade.gross_pnl_usd == pytest.approx(-2.0)
    assert long_trade.total_cost_usd == pytest.approx(0.42)
    assert short_trade.total_cost_usd == pytest.approx(0.42)
    assert long_trade.net_pnl_usd == pytest.approx(1.58)
    assert short_trade.net_pnl_usd == pytest.approx(-2.42)
    assert (
        long_trade.gross_pnl_usd - long_trade.net_pnl_usd
        == pytest.approx(long_trade.total_cost_usd)
    )


def test_random_control_is_stable_and_order_independent() -> None:
    case_ids = [
        "SESSION-LONDON-20220103",
        "SESSION-LONDON-20220104",
        "SESSION-NEW_YORK-20220103",
        "SESSION-NEW_YORK-20220104",
    ]
    namespace = "GOLD_CASEBOOK_BASELINE_RANDOM_V0_1"

    forward = {
        case_id: direction_for_control(
            "DETERMINISTIC_RANDOM",
            case_id=case_id,
            random_namespace=namespace,
        )
        for case_id in case_ids
    }
    reverse = {
        case_id: direction_for_control(
            "DETERMINISTIC_RANDOM",
            case_id=case_id,
            random_namespace=namespace,
        )
        for case_id in reversed(case_ids)
    }

    assert forward == reverse
    assert forward == {
        "SESSION-LONDON-20220103": "SHORT",
        "SESSION-LONDON-20220104": "LONG",
        "SESSION-NEW_YORK-20220103": "SHORT",
        "SESSION-NEW_YORK-20220104": "SHORT",
    }


def test_fill_clock_mismatch_and_unknown_spread_are_rejected() -> None:
    case = _case()
    entry, exit_ = _bars(case)
    wrong_entry = _bar(
        record_id="WRONG",
        open_time=case.decision_at,
        open_price=2_000.0,
        close_price=2_000.1,
        spread=0.2,
    )

    with pytest.raises(ValueError, match="ENTRY_BAR_TIME_MISMATCH"):
        simulate_baseline_case(
            case,
            control_code="ALWAYS_LONG",
            entry_bar=wrong_entry,
            exit_bar=exit_,
            config=_config(),
        )

    unknown_spread = _bar(
        record_id="ENTRY",
        open_time=entry.open_time,
        open_price=entry.open,
        close_price=entry.close,
        spread=None,
    )
    with pytest.raises(ValueError, match="ENTRY_SPREAD_UNKNOWN"):
        simulate_baseline_case(
            case,
            control_code="ALWAYS_LONG",
            entry_bar=unknown_spread,
            exit_bar=exit_,
            config=_config(),
        )


def test_metrics_preserve_totals_costs_directions_and_years() -> None:
    case = _case()
    entry, exit_ = _bars(case)
    trades = [
        simulate_baseline_case(
            case,
            control_code=control,
            entry_bar=entry,
            exit_bar=exit_,
            config=_config(),
        )
        for control in ("ALWAYS_LONG", "ALWAYS_SHORT")
    ]

    metrics = calculate_baseline_metrics(trades)

    assert metrics["observations"] == 2
    assert metrics["net_win_rate_pct"] == 50.0
    assert metrics["total_gross_pnl_usd_per_ounce"] == pytest.approx(0.0)
    assert metrics["total_net_pnl_usd_per_ounce"] == pytest.approx(-0.84)
    assert metrics["total_cost_usd_per_ounce"] == pytest.approx(0.84)
    assert metrics["long_direction_count"] == 1
    assert metrics["short_direction_count"] == 1
    assert metrics["results_by_year"]["2022"]["observations"] == 2
    assert metrics["mean_net_return_95pct_normal_ci_basis_points"] != [
        None,
        None,
    ]
