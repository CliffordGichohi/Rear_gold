from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from research_auction_state_playbooks import _auction_days, _signals
from research_interpretable_auction_bias import (
    _aligned,
    _bias_metrics,
    _feature_records,
    _fit_trees,
    _predict,
    _tree_dict,
)
from research_intraday_usd_confirmation import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
)
from research_one_minute_auction_execution import (
    ONE_MINUTE_SQL,
    _candidate_results,
    _discovery_rank,
    _micro_results,
)
from research_session_state_transitions import (
    _candidate_report,
    _portfolio_report,
    _select_discovery_candidates,
    _slice,
)

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

    auction_days = _auction_days(gold_bars, start=start, end=end)
    feature_records = _feature_records(
        auction_days,
        gold_bars=gold_bars,
        eurusd_bars=eurusd_bars,
    )
    trees = _fit_trees(feature_records)
    predictions = {
        (record.window, record.session_date): _predict(
            trees[record.window],
            record.features,
        )
        for record in feature_records
    }
    source_signals = _signals(auction_days, bars=gold_bars)
    aligned_signals = [
        signal
        for signal in source_signals
        if _aligned(signal, predictions=predictions)
    ]
    managed = _micro_results(
        aligned_signals,
        minute_bars=minute_bars,
    )
    candidates, candidate_trades = _candidate_results(managed)
    selected = _select_discovery_candidates(
        candidates,
        candidate_trades=candidate_trades,
    )
    report = {
        "contract": {
            "version": "INTERPRETABLE_BIAS_MICRO_EXECUTION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "feature_records": len(feature_records),
            "source_signals": len(source_signals),
            "tree_aligned_signals": len(aligned_signals),
            "managed_results": len(managed),
            "candidate_hypotheses": len(candidates),
            "bias": (
                "The deterministic depth-2 auction-window trees are fitted "
                "only on 2021-08-01 through 2022-12-31. A signal is permitted "
                "only when its side matches a discovery leaf with directional "
                "probability >=0.55."
            ),
            "entry": (
                "The auction-state trigger is known at the five-minute close. "
                "Entry is the next one-minute open with a stop behind the last "
                "3 or 5 completed one-minute bars."
            ),
            "costs": (
                "Observed entry/exit spread, $0.05/oz slippage per side, and "
                "$7/lot round-turn commission; also tested at 1.50x."
            ),
            "selection": (
                "No additional feature or threshold search. The predeclared "
                "one-minute contexts, managers, and discovery qualification "
                "rules are reused unchanged."
            ),
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
        },
        "trees": {
            window: _tree_dict(tree) for window, tree in sorted(trees.items())
        },
        "bias_performance": {
            window: {
                period: _bias_metrics(
                    [
                        record
                        for record in feature_records
                        if record.window == window
                        and (
                            (
                                period == "discovery"
                                and record.session_date.year < 2023
                            )
                            or (
                                period == "validation"
                                and record.session_date.year == 2023
                            )
                            or (
                                period == "forward"
                                and record.session_date.year == 2024
                            )
                        )
                    ],
                    tree=tree,
                )
                for period in ("discovery", "validation", "forward")
            }
            for window, tree in sorted(trees.items())
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
        "top_minimum_sample_candidates": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in sorted(
                [
                    candidate
                    for candidate in candidates
                    if len(
                        _slice(
                            candidate_trades[(candidate.key, 1.0)],
                            "discovery",
                        )
                    )
                    >= 40
                ],
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


if __name__ == "__main__":
    asyncio.run(main())
