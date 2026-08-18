from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from gold_intel.backtesting.casebook_baseline import BaselineTrade
from gold_intel.backtesting.casebook_outcome_atlas import (
    OutcomePair,
    SourceTrade,
    absolute_move_bin,
    build_atlas,
    build_outcome_case,
    quantile_type_7,
    summarize_pairs,
)


def test_build_outcome_case_describes_direction_cost_and_bin() -> None:
    pair = _pair(
        case_id="LONDON-2024-01-02",
        session_code="LONDON",
        session_date=date(2024, 1, 2),
        move=7.0,
        cost=0.2,
    )

    outcome = build_outcome_case(
        pair,
        measurement_manifest_hash="manifest",
    )

    assert outcome.direction == "UP"
    assert outcome.cost_hurdle_state == "LONG_NET_WIN"
    assert outcome.absolute_move_bin == "ABS_5_TO_LT_10"
    assert outcome.gross_move_usd_per_ounce == 7.0
    assert outcome.long_net_pnl_usd == 6.8
    assert outcome.short_net_pnl_usd == -7.2


def test_small_move_does_not_clear_frozen_cost_hurdle() -> None:
    outcome = build_outcome_case(
        _pair(
            case_id="NEW_YORK-2024-01-02",
            session_code="NEW_YORK",
            session_date=date(2024, 1, 2),
            move=-0.1,
            cost=0.2,
        ),
        measurement_manifest_hash="manifest",
    )

    assert outcome.direction == "DOWN"
    assert outcome.cost_hurdle_state == "NO_SIDE_NET_WIN"
    assert outcome.absolute_move_bin == "ABS_LT_2"


def test_atlas_keeps_sessions_separate_and_orders_time_buckets() -> None:
    pairs = [
        _pair(
            case_id="LONDON-2023-04-03",
            session_code="LONDON",
            session_date=date(2023, 4, 3),
            move=-4.0,
        ),
        _pair(
            case_id="LONDON-2024-01-02",
            session_code="LONDON",
            session_date=date(2024, 1, 2),
            move=6.0,
        ),
        _pair(
            case_id="NEW_YORK-2024-01-02",
            session_code="NEW_YORK",
            session_date=date(2024, 1, 2),
            move=-3.0,
        ),
    ]

    outcomes, atlas = build_atlas(
        pairs,
        measurement_manifest_hash="manifest",
    )

    assert len(outcomes) == 3
    assert atlas["LONDON"]["overall"]["case_count"] == 2
    assert atlas["NEW_YORK"]["overall"]["case_count"] == 1
    assert list(atlas["LONDON"]["by_calendar_year"]) == ["2023", "2024"]
    assert list(atlas["LONDON"]["by_calendar_quarter"]) == ["2023-Q2", "2024-Q1"]
    assert list(atlas["LONDON"]["by_calendar_month"]) == ["2023-04", "2024-01"]


def test_summary_reports_predeclared_categories_without_ranking() -> None:
    summary = summarize_pairs(
        [
            _pair(
                case_id="LONDON-A",
                session_code="LONDON",
                session_date=date(2024, 1, 2),
                move=1.0,
            ),
            _pair(
                case_id="LONDON-B",
                session_code="LONDON",
                session_date=date(2024, 1, 3),
                move=-8.0,
            ),
        ]
    )

    assert summary["direction"]["UP"] == {"count": 1, "pct": 50.0}
    assert summary["direction"]["DOWN"] == {"count": 1, "pct": 50.0}
    assert summary["absolute_move_bins_usd_per_ounce"]["ABS_LT_2"]["count"] == 1
    assert summary["absolute_move_bins_usd_per_ounce"]["ABS_5_TO_LT_10"]["count"] == 1
    assert summary["absolute_move_usd_per_ounce"]["median"] == 4.5


def test_pair_integrity_rejects_cost_mismatch() -> None:
    pair = _pair(
        case_id="LONDON-BAD",
        session_code="LONDON",
        session_date=date(2024, 1, 2),
        move=2.0,
    )
    bad_short = _trade(
        case_id="LONDON-BAD",
        session_code="LONDON",
        session_date=date(2024, 1, 2),
        side="SHORT",
        move=2.0,
        cost=0.3,
    )

    with pytest.raises(ValueError, match="Long/short .* mismatch"):
        build_outcome_case(
            OutcomePair(
                long=pair.long,
                short=SourceTrade("short", "short-hash", bad_short),
            ),
            measurement_manifest_hash="manifest",
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "ABS_LT_2"),
        (1.999, "ABS_LT_2"),
        (2.0, "ABS_2_TO_LT_5"),
        (5.0, "ABS_5_TO_LT_10"),
        (10.0, "ABS_10_TO_LT_20"),
        (20.0, "ABS_GE_20"),
    ],
)
def test_absolute_move_bins_are_exhaustive(value: float, expected: str) -> None:
    assert absolute_move_bin(value) == expected


def test_type_7_quantile_matches_linear_interpolation() -> None:
    assert quantile_type_7([1.0, 2.0, 3.0, 4.0], 0.25) == 1.75


def _pair(
    *,
    case_id: str,
    session_code: str,
    session_date: date,
    move: float,
    cost: float = 0.2,
) -> OutcomePair:
    return OutcomePair(
        long=SourceTrade(
            f"LONG-{case_id}",
            f"LONG-HASH-{case_id}",
            _trade(
                case_id=case_id,
                session_code=session_code,
                session_date=session_date,
                side="LONG",
                move=move,
                cost=cost,
            ),
        ),
        short=SourceTrade(
            f"SHORT-{case_id}",
            f"SHORT-HASH-{case_id}",
            _trade(
                case_id=case_id,
                session_code=session_code,
                session_date=session_date,
                side="SHORT",
                move=move,
                cost=cost,
            ),
        ),
    )


def _trade(
    *,
    case_id: str,
    session_code: str,
    session_date: date,
    side: str,
    move: float,
    cost: float,
) -> BaselineTrade:
    entry = 1900.0
    exit_price = entry + move
    direction = 1.0 if side == "LONG" else -1.0
    gross = direction * move
    net = gross - cost
    decision = datetime.combine(
        session_date,
        datetime.min.time(),
        tzinfo=UTC,
    )
    entry_time = decision + timedelta(minutes=1)
    exit_time = decision + timedelta(hours=4)
    return BaselineTrade(
        case_id=case_id,
        case_record_hash=f"CASE-{case_id}",
        session_code=session_code,
        session_date=session_date,
        control_code=("ALWAYS_LONG" if side == "LONG" else "ALWAYS_SHORT"),
        side=side,  # type: ignore[arg-type]
        decision_at=decision,
        entry_time=entry_time,
        exit_time=exit_time,
        holding_minutes=239,
        entry_bar_id=f"ENTRY-{case_id}",
        entry_bar_hash=f"ENTRY-HASH-{case_id}",
        exit_bar_id=f"EXIT-{case_id}",
        exit_bar_hash=f"EXIT-HASH-{case_id}",
        reference_entry_price=entry,
        reference_exit_price=exit_price,
        executed_entry_price=entry,
        executed_exit_price=exit_price,
        entry_spread_price=0.03,
        exit_spread_price=0.03,
        quantity_ounces=1.0,
        quantity_lots=0.01,
        gross_pnl_usd=gross,
        spread_cost_usd=0.03,
        slippage_cost_usd=0.10,
        commission_usd=cost - 0.13,
        total_cost_usd=cost,
        net_pnl_usd=net,
        gross_return_basis_points=10_000 * gross / entry,
        net_return_basis_points=10_000 * net / entry,
        execution_manifest_hash="execution",
    )
