from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from explore_session_playbooks import Bar
from research_auction_state_playbooks import _auction_days, _signals
from research_daily_session_playbooks import Signal, _atr_by_close
from research_fundamental_state_transitions import (
    _candidate_report,
    _candidate_results,
    _coverage_report,
    _fundamental_records,
    _ranking_key,
    _rules,
    _select_candidates,
)
from research_interpretable_auction_bias import _momentum
from research_intraday_usd_confirmation import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
)
from research_one_minute_auction_execution import (
    ONE_MINUTE_SQL,
    _micro_results,
)
from research_session_state_transitions import _portfolio_report, _slice

from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.database import session_factory


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
        gold_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "XAUUSD", **query},
                )
            ).mappings()
        )
        eurusd_bars = _bars(
            (
                await session.execute(
                    FIVE_MINUTE_INSTRUMENT_SQL,
                    {"instrument": "EURUSD", **query},
                )
            ).mappings()
        )
        minute_bars = _bars(
            (
                await session.execute(
                    ONE_MINUTE_SQL,
                    query,
                )
            ).mappings()
        )
        fundamental_inputs = await load_fundamental_inputs(
            session,
            as_of=end,
        )

    auction_days = _auction_days(gold_bars, start=start, end=end)
    source_signals = _enrich_intraday_usd(
        _signals(auction_days, bars=gold_bars),
        eurusd_bars=eurusd_bars,
    )
    managed = _micro_results(
        source_signals,
        minute_bars=minute_bars,
    )
    records = _fundamental_records(
        managed,
        fundamental_inputs=fundamental_inputs,
    )
    rules = _rules()
    candidates, candidate_trades = _candidate_results(records, rules=rules)
    selected = _select_candidates(
        candidates,
        candidate_trades=candidate_trades,
        rules=rules,
    )
    minimum_by_rule = {
        rule.name: rule.minimum_discovery_trades for rule in rules
    }
    sampled = [
        candidate
        for candidate in candidates
        if len(
            _slice(
                candidate_trades[(candidate.key, 1.0)],
                "discovery",
            )
        )
        >= minimum_by_rule[candidate.rule]
    ]
    report = {
        "contract": {
            "version": "FUNDAMENTAL_AUCTION_MICRO_EXECUTION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "auction_days": len(auction_days),
            "source_signals": len(source_signals),
            "managed_results": len(managed),
            "fundamental_records": len(records),
            "candidate_hypotheses": len(candidates),
            "architecture": (
                "Point-in-time macro/reaction-function permission -> completed "
                "auction-state trigger -> completed 60-minute EURUSD inverse-USD "
                "confirmation where required -> next one-minute open -> "
                "three- or five-minute structural invalidation."
            ),
            "fundamental_rules": [rule.name for rule in rules],
            "entry": (
                "The five-minute auction state and intraday USD observation are "
                "known at the signal close. Entry is the next one-minute open."
            ),
            "costs": (
                "Observed entry/exit spread, $0.05/oz slippage per side, and "
                "$7/lot round-turn commission; also tested at 1.50x."
            ),
            "ambiguity": (
                "When stop and target occur in the same one-minute bar, the "
                "stop is assumed first."
            ),
            "bulk_research_hashing": (
                "Per-signal provenance hashes are omitted; all point-in-time "
                "components, scores, confidence, evidence clocks, and rules are "
                "unchanged and regression tested."
            ),
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
            "monthly_hurdle": (
                "At 1% account risk, the requested $1,000 average on a $10,000 "
                "reference account requires approximately 10R per month."
            ),
        },
        "fundamental_coverage": _coverage_report(records),
        "selected_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
                rules=rules,
            )
            for candidate in selected
        ],
        "top_discovery_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
                rules=rules,
            )
            for candidate in sorted(
                candidates,
                key=lambda candidate: _ranking_key(
                    candidate,
                    candidate_trades=candidate_trades,
                ),
                reverse=True,
            )[: args.top]
        ],
        "top_minimum_sample_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
                rules=rules,
            )
            for candidate in sorted(
                sampled,
                key=lambda candidate: _ranking_key(
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


def _enrich_intraday_usd(
    signals: Sequence[Signal],
    *,
    eurusd_bars: Sequence[Bar],
) -> list[Signal]:
    close_times = [bar.close_time for bar in eurusd_bars]
    atr_by_close = _atr_by_close(eurusd_bars)
    output: list[Signal] = []
    for signal in signals:
        atr = atr_by_close.get(signal.signal_time)
        momentum = (
            _momentum(
                eurusd_bars,
                close_times=close_times,
                as_of=signal.signal_time,
                lookback=12,
                atr=atr,
            )
            if atr is not None and atr > 0
            else None
        )
        signed = (
            (1 if signal.side == "LONG" else -1) * momentum
            if momentum is not None
            else None
        )
        output.append(
            replace(
                signal,
                evidence={
                    **signal.evidence,
                    "eurusd_60m_atr": momentum,
                    "eurusd_60m_signed_atr": signed,
                },
            )
        )
    return output


if __name__ == "__main__":
    asyncio.run(main())
