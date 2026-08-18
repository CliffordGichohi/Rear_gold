from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from explore_session_playbooks import FIVE_MINUTE_SQL, Bar
from research_auction_state_playbooks import (
    _auction_days,
    _signals,
)
from research_daily_session_playbooks import Signal, Trade
from research_session_state_transitions import (
    Candidate,
    ContextRule,
    ManagedResult,
    _candidate_report,
    _portfolio_report,
    _select_discovery_candidates,
)
from sqlalchemy import text

from gold_intel.infrastructure.database import session_factory

ONE_MINUTE_SQL = text(
    """
    SELECT DISTINCT ON (open_time)
        open_time,
        close_time,
        open,
        high,
        low,
        close,
        volume,
        spread_price
    FROM market.price_bars
    WHERE instrument_code = 'XAUUSD'
      AND provider_code = 'IC_MARKETS_MT5'
      AND timeframe = '1m'
      AND is_complete
      AND NOT is_synthetic
      AND open_time >= :load_start
      AND open_time < :load_end
      AND available_at <= close_time
    ORDER BY open_time, available_at
    """
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    async with session_factory() as session:
        query = {
            "load_start": start - timedelta(days=8),
            "load_end": end,
        }
        five_rows = (
            await session.execute(FIVE_MINUTE_SQL, query)
        ).mappings()
        five_minute_bars = [
            Bar(
                open_time=row["open_time"],
                close_time=row["close_time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                spread=float(row["spread_price"]),
            )
            for row in five_rows
        ]
        minute_rows = (
            await session.execute(ONE_MINUTE_SQL, query)
        ).mappings()
        minute_bars = [
            Bar(
                open_time=row["open_time"],
                close_time=row["close_time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                spread=float(row["spread_price"]),
            )
            for row in minute_rows
        ]

    auction_days = _auction_days(
        five_minute_bars,
        start=start,
        end=end,
    )
    source_signals = _signals(auction_days, bars=five_minute_bars)
    managed = _micro_results(
        source_signals,
        minute_bars=minute_bars,
    )
    candidates, candidate_trades = _candidate_results(managed)
    selected = _select_discovery_candidates(
        candidates,
        candidate_trades=candidate_trades,
    )
    report = {
        "contract": {
            "version": "ONE_MINUTE_AUCTION_EXECUTION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "auction_days": len(auction_days),
            "source_signals": len(source_signals),
            "managed_results": len(managed),
            "candidate_hypotheses": len(candidates),
            "entry": (
                "The 5-minute auction state is known at its close. Entry is "
                "the next one-minute open with a stop behind the last 3 or 5 "
                "completed one-minute bars."
            ),
            "costs": (
                "Observed entry/exit spread, $0.05/oz slippage per side, and "
                "$7/lot round-turn commission; also tested at 1.50x."
            ),
            "ambiguity": (
                "When stop and target occur inside the same one-minute bar, "
                "the stop is assumed first."
            ),
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
        },
        "signal_funnel": {
            playbook: sum(
                result.signal.playbook == playbook for result in managed
            )
            for playbook in sorted(
                {result.signal.playbook for result in managed}
            )
        },
        "selected_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in selected
        ],
        "top_discovery_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in sorted(
                candidates,
                key=lambda candidate: _discovery_rank(
                    candidate,
                    candidate_trades=candidate_trades,
                ),
                reverse=True,
            )[: args.top]
        ],
        "portfolios": {
            f"{cost_multiplier:.2f}x": _portfolio_report(
                selected,
                candidate_trades=candidate_trades,
                cost_multiplier=cost_multiplier,
            )
            for cost_multiplier in (1.0, 1.5)
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _micro_results(
    signals: Sequence[Signal],
    *,
    minute_bars: Sequence[Bar],
) -> list[ManagedResult]:
    bars_by_open = {bar.open_time: bar for bar in minute_bars}
    output: list[ManagedResult] = []
    for source in signals:
        for stop_lookback in (3, 5):
            micro_signal = _micro_signal(
                source,
                bars_by_open=bars_by_open,
                stop_lookback=stop_lookback,
            )
            if micro_signal is None:
                continue
            for cost_multiplier in (1.0, 1.5):
                for manager, target_r in (
                    ("FIXED_1_50R", 1.5),
                    ("FIXED_2_00R", 2.0),
                    ("FIXED_3_00R", 3.0),
                ):
                    trade = _simulate_minute(
                        micro_signal,
                        bars_by_open=bars_by_open,
                        target_r=target_r,
                        cost_multiplier=cost_multiplier,
                    )
                    if trade is not None:
                        output.append(
                            ManagedResult(
                                signal=micro_signal,
                                manager=manager,
                                cost_multiplier=cost_multiplier,
                                trade=trade,
                            )
                        )
    return output


def _micro_signal(
    source: Signal,
    *,
    bars_by_open: dict[datetime, Bar],
    stop_lookback: int,
) -> Signal | None:
    entry_bar = bars_by_open.get(source.entry_time)
    completed = [
        bars_by_open.get(source.entry_time - timedelta(minutes=offset))
        for offset in range(stop_lookback, 0, -1)
    ]
    if entry_bar is None or any(bar is None for bar in completed):
        return None
    history = [bar for bar in completed if bar is not None]
    buffer = max(0.05, 0.03 * source.atr, entry_bar.spread / 2)
    stop = (
        min(bar.low for bar in history) - buffer
        if source.side == "LONG"
        else max(bar.high for bar in history) + buffer
    )
    if (source.side == "LONG" and stop >= entry_bar.open) or (
        source.side == "SHORT" and stop <= entry_bar.open
    ):
        return None
    risk = abs(entry_bar.open - stop)
    risk_atr = risk / source.atr
    estimated_cost = entry_bar.spread + 0.10 + 0.07
    estimated_cost_r = estimated_cost / risk
    if not 0.08 <= risk_atr <= 2.0 or estimated_cost_r > 0.30:
        return None
    return Signal(
        playbook=f"{source.playbook}|MICRO_{stop_lookback}",
        session_date=source.session_date,
        side=source.side,
        signal_time=source.signal_time,
        entry_time=source.entry_time,
        entry_reference=entry_bar.open,
        stop=stop,
        base_target_r=2.0,
        max_holding_minutes=source.max_holding_minutes,
        atr=source.atr,
        evidence={
            **source.evidence,
            "micro_stop_lookback": stop_lookback,
            "micro_risk_atr": risk_atr,
            "estimated_cost_r": estimated_cost_r,
        },
    )


def _simulate_minute(
    signal: Signal,
    *,
    bars_by_open: dict[datetime, Bar],
    target_r: float,
    cost_multiplier: float,
) -> Trade | None:
    risk = abs(signal.entry_reference - signal.stop)
    if risk <= 0:
        return None
    expected = [
        signal.entry_time + timedelta(minutes=offset)
        for offset in range(signal.max_holding_minutes)
    ]
    path = [bars_by_open.get(open_time) for open_time in expected]
    if any(bar is None for bar in path):
        return None
    bars = [bar for bar in path if bar is not None]
    direction = 1 if signal.side == "LONG" else -1
    target = signal.entry_reference + direction * target_r * risk
    exit_bar = bars[-1]
    exit_price = exit_bar.close
    exit_reason = "TIME"
    favourable = 0.0
    adverse = 0.0
    for bar in bars:
        if signal.side == "LONG":
            stop_hit = bar.low <= signal.stop
            target_hit = bar.high >= target
            favourable = max(
                favourable,
                bar.high - signal.entry_reference,
            )
            adverse = max(
                adverse,
                signal.entry_reference - bar.low,
            )
        else:
            stop_hit = bar.high >= signal.stop
            target_hit = bar.low <= target
            favourable = max(
                favourable,
                signal.entry_reference - bar.low,
            )
            adverse = max(
                adverse,
                bar.high - signal.entry_reference,
            )
        if stop_hit:
            exit_bar = bar
            exit_price = signal.stop
            exit_reason = "STOP"
            break
        if target_hit:
            exit_bar = bar
            exit_price = target
            exit_reason = "TARGET"
            break
    gross_r = direction * (exit_price - signal.entry_reference) / risk
    cost_price = (
        bars[0].spread / 2
        + exit_bar.spread / 2
        + 0.10
        + 0.07
    ) * cost_multiplier
    cost_r = cost_price / risk
    return Trade(
        playbook=signal.playbook,
        session_date=signal.session_date,
        side=signal.side,
        signal_time=signal.signal_time,
        entry_time=signal.entry_time,
        exit_time=exit_bar.close_time,
        exit_reason=exit_reason,
        risk_distance=round(risk, 6),
        gross_r=round(gross_r, 6),
        net_r=round(gross_r - cost_r, 6),
        cost_r=round(cost_r, 6),
        mfe_r=round(max(0.0, favourable / risk), 6),
        mae_r=round(max(0.0, adverse / risk), 6),
        holding_minutes=int(
            (exit_bar.close_time - signal.entry_time).total_seconds()
            // 60
        ),
        evidence={
            **signal.evidence,
            "target_r": target_r,
            "entry_spread": bars[0].spread,
            "exit_spread": exit_bar.spread,
            "bar_resolution": "1m",
            "same_bar_ambiguity": "STOP_FIRST",
        },
    )


def _context_rules() -> tuple[ContextRule, ...]:
    return (
        ContextRule("BASE", lambda signal: True),
        ContextRule(
            "COST_LE_0_15R",
            lambda signal: (
                _evidence_float(signal, "estimated_cost_r") <= 0.15
            ),
        ),
        ContextRule(
            "PRE_RANGE_COMPRESSION_P30",
            lambda signal: (
                _evidence_float(signal, "pre_range_percentile") <= 30
            ),
        ),
        ContextRule(
            "VOLUME_GE_1_20X",
            lambda signal: (
                _evidence_float(signal, "relative_volume") >= 1.20
            ),
        ),
        ContextRule(
            "PRE_DIRECTION_ALIGNED",
            lambda signal: (
                _evidence_float(signal, "signed_pre_return") > 0
            ),
        ),
        ContextRule(
            "PRE_DIRECTION_OPPOSED",
            lambda signal: (
                _evidence_float(signal, "signed_pre_return") < 0
            ),
        ),
    )


def _candidate_results(
    managed: Sequence[ManagedResult],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Trade]]]:
    playbooks = sorted({result.signal.playbook for result in managed})
    managers = sorted({result.manager for result in managed})
    candidates = [
        Candidate(
            archetype=playbook,
            rule=rule.name,
            manager=manager,
        )
        for playbook in playbooks
        for rule in _context_rules()
        for manager in managers
    ]
    rules = {rule.name: rule for rule in _context_rules()}
    output: dict[tuple[str, float], list[Trade]] = {}
    for candidate in candidates:
        rule = rules[candidate.rule]
        for cost_multiplier in (1.0, 1.5):
            output[(candidate.key, cost_multiplier)] = [
                result.trade
                for result in managed
                if result.signal.playbook == candidate.archetype
                and result.manager == candidate.manager
                and result.cost_multiplier == cost_multiplier
                and rule.predicate(result.signal)
            ]
    return candidates, output


def _discovery_rank(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
) -> tuple[float, float, int]:
    trades = [
        trade
        for trade in candidate_trades[(candidate.key, 1.0)]
        if trade.session_date < date(2023, 1, 1)
    ]
    expectancy = (
        statistics.mean(trade.net_r for trade in trades)
        if trades
        else -999.0
    )
    wins = sum(max(0.0, trade.net_r) for trade in trades)
    losses = abs(sum(min(0.0, trade.net_r) for trade in trades))
    return (
        expectancy,
        wins / losses if losses > 0 else -999.0,
        len(trades),
    )


def _evidence_float(signal: Signal, key: str) -> float:
    value: Any = signal.evidence.get(key)
    return float(value) if value is not None else -999.0


if __name__ == "__main__":
    asyncio.run(main())
