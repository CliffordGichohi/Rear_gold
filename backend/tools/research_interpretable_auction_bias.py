from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from explore_session_playbooks import Bar
from research_auction_state_playbooks import (
    AuctionDay,
    _auction_days,
    _signals,
)
from research_daily_session_playbooks import (
    Side,
    Signal,
    Trade,
    _atr_by_close,
)
from research_intraday_usd_confirmation import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
)
from research_session_state_transitions import (
    Candidate,
    ManagedResult,
    _candidate_report,
    _portfolio_report,
    _select_discovery_candidates,
    _simulate_all,
)

from gold_intel.infrastructure.database import session_factory

FEATURE_NAMES = (
    "pre_return_atr",
    "pre_range_atr",
    "gold_60m_atr",
    "gold_4h_atr",
    "gold_24h_atr",
    "eurusd_60m_atr",
    "eurusd_4h_atr",
    "pre_close_location",
    "pre_range_percentile",
    "relative_volume",
    "relative_spread",
)
MINIMUM_LEAF = 60
MAXIMUM_DEPTH = 2
MINIMUM_SPLIT_GAIN = 0.005
MINIMUM_LEAF_DIRECTIONAL_PROBABILITY = 0.55


@dataclass(frozen=True, slots=True)
class FeatureRecord:
    session_date: date
    window: str
    features: dict[str, float]
    label_long: bool
    post_return: float
    entry_spread: float
    exit_spread: float


@dataclass(frozen=True, slots=True)
class TreeNode:
    support: int
    long_probability: float
    feature: str | None = None
    threshold: float | None = None
    gain: float | None = None
    left: TreeNode | None = None
    right: TreeNode | None = None

    @property
    def is_leaf(self) -> bool:
        return self.feature is None


@dataclass(frozen=True, slots=True)
class Prediction:
    side: Side | None
    probability: float
    leaf_support: int


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
    managed = _simulate_all(source_signals, gold_bars=gold_bars)
    aligned = [
        result
        for result in managed
        if _aligned(
            result.signal,
            predictions=predictions,
        )
    ]
    candidates, candidate_trades = _candidate_results(aligned)
    selected = _select_discovery_candidates(
        candidates,
        candidate_trades=candidate_trades,
    )
    report = {
        "contract": {
            "version": "INTERPRETABLE_AUCTION_BIAS_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "features": list(FEATURE_NAMES),
            "model": (
                f"One deterministic depth-{MAXIMUM_DEPTH} binary tree per "
                f"auction window; minimum leaf {MINIMUM_LEAF}; minimum Gini "
                f"gain {MINIMUM_SPLIT_GAIN}; no black-box estimator."
            ),
            "prediction_gate": (
                "Trade-side permission only when the discovery leaf's "
                f"directional probability is at least "
                f"{MINIMUM_LEAF_DIRECTIONAL_PROBABILITY:.2f}; price still "
                "must produce an auction-state trigger."
            ),
            "training": "2021-08-01 through 2022-12-31 only",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
            "feature_records": len(feature_records),
            "source_signals": len(source_signals),
            "aligned_managed_results": len(aligned),
            "candidate_hypotheses": len(candidates),
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
                        and _in_period(record.session_date, period)
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


def _feature_records(
    auction_days: Sequence[AuctionDay],
    *,
    gold_bars: Sequence[Bar],
    eurusd_bars: Sequence[Bar],
) -> list[FeatureRecord]:
    gold_close_times = [bar.close_time for bar in gold_bars]
    eurusd_close_times = [bar.close_time for bar in eurusd_bars]
    gold_atr = _atr_by_close(gold_bars)
    eurusd_atr = _atr_by_close(eurusd_bars)
    range_history: dict[str, list[float]] = {}
    output: list[FeatureRecord] = []
    for day in auction_days:
        window = day.specification.name
        history = range_history.setdefault(window, [])
        as_of = day.post[0].open_time
        atr = gold_atr.get(as_of)
        eur_atr = eurusd_atr.get(as_of)
        if atr is None or atr <= 0 or eur_atr is None or eur_atr <= 0:
            history.append(
                max(bar.high for bar in day.pre)
                - min(bar.low for bar in day.pre)
            )
            continue
        pre_high = max(bar.high for bar in day.pre)
        pre_low = min(bar.low for bar in day.pre)
        pre_range = pre_high - pre_low
        pre_return = day.pre[-1].close - day.pre[0].open
        gold_60m = _momentum(
            gold_bars,
            close_times=gold_close_times,
            as_of=as_of,
            lookback=12,
            atr=atr,
        )
        gold_4h = _momentum(
            gold_bars,
            close_times=gold_close_times,
            as_of=as_of,
            lookback=48,
            atr=atr,
        )
        gold_24h = _momentum(
            gold_bars,
            close_times=gold_close_times,
            as_of=as_of,
            lookback=288,
            atr=atr,
        )
        eurusd_60m = _momentum(
            eurusd_bars,
            close_times=eurusd_close_times,
            as_of=as_of,
            lookback=12,
            atr=eur_atr,
        )
        eurusd_4h = _momentum(
            eurusd_bars,
            close_times=eurusd_close_times,
            as_of=as_of,
            lookback=48,
            atr=eur_atr,
        )
        values = (gold_60m, gold_4h, gold_24h, eurusd_60m, eurusd_4h)
        if any(value is None for value in values):
            history.append(pre_range)
            continue
        volume_history = [bar.volume for bar in day.pre[:-1]]
        spread_history = [bar.spread for bar in day.pre[:-1]]
        volume_median = statistics.median(volume_history)
        spread_median = statistics.median(spread_history)
        output.append(
            FeatureRecord(
                session_date=day.session_date,
                window=window,
                features={
                    "pre_return_atr": pre_return / atr,
                    "pre_range_atr": pre_range / atr,
                    "gold_60m_atr": float(gold_60m),
                    "gold_4h_atr": float(gold_4h),
                    "gold_24h_atr": float(gold_24h),
                    "eurusd_60m_atr": float(eurusd_60m),
                    "eurusd_4h_atr": float(eurusd_4h),
                    "pre_close_location": (
                        (day.pre[-1].close - pre_low) / pre_range
                        if pre_range > 0
                        else 0.5
                    ),
                    "pre_range_percentile": _percentile(
                        pre_range,
                        history[-60:],
                    ),
                    "relative_volume": (
                        day.pre[-1].volume / volume_median
                        if volume_median > 0
                        else 1.0
                    ),
                    "relative_spread": (
                        day.pre[-1].spread / spread_median
                        if spread_median > 0
                        else 1.0
                    ),
                },
                label_long=day.post[-1].close > day.post[0].open,
                post_return=day.post[-1].close - day.post[0].open,
                entry_spread=day.post[0].spread,
                exit_spread=day.post[-1].spread,
            )
        )
        history.append(pre_range)
    return output


def _fit_trees(
    records: Sequence[FeatureRecord],
) -> dict[str, TreeNode]:
    windows = sorted({record.window for record in records})
    return {
        window: _fit_tree(
            [
                record
                for record in records
                if record.window == window
                and record.session_date < date(2023, 1, 1)
            ],
            depth=0,
        )
        for window in windows
    }


def _fit_tree(
    records: Sequence[FeatureRecord],
    *,
    depth: int,
) -> TreeNode:
    probability = (
        sum(record.label_long for record in records) / len(records)
        if records
        else 0.5
    )
    leaf = TreeNode(
        support=len(records),
        long_probability=round(probability, 6),
    )
    if depth >= MAXIMUM_DEPTH or len(records) < 2 * MINIMUM_LEAF:
        return leaf
    base_impurity = _gini(probability)
    best: tuple[
        float,
        str,
        float,
        list[FeatureRecord],
        list[FeatureRecord],
    ] | None = None
    for feature in FEATURE_NAMES:
        ordered = sorted(record.features[feature] for record in records)
        thresholds = {
            ordered[int((len(ordered) - 1) * quantile)]
            for quantile in (0.25, 0.50, 0.75)
        }
        for threshold in thresholds:
            left = [
                record
                for record in records
                if record.features[feature] <= threshold
            ]
            right = [
                record
                for record in records
                if record.features[feature] > threshold
            ]
            if min(len(left), len(right)) < MINIMUM_LEAF:
                continue
            weighted = (
                len(left)
                / len(records)
                * _gini(
                    sum(record.label_long for record in left) / len(left)
                )
                + len(right)
                / len(records)
                * _gini(
                    sum(record.label_long for record in right) / len(right)
                )
            )
            gain = base_impurity - weighted
            candidate = (gain, feature, threshold, left, right)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
    if best is None or best[0] < MINIMUM_SPLIT_GAIN:
        return leaf
    gain, feature, threshold, left, right = best
    return TreeNode(
        support=len(records),
        long_probability=round(probability, 6),
        feature=feature,
        threshold=round(threshold, 8),
        gain=round(gain, 8),
        left=_fit_tree(left, depth=depth + 1),
        right=_fit_tree(right, depth=depth + 1),
    )


def _predict(
    tree: TreeNode,
    features: dict[str, float],
) -> Prediction:
    node = tree
    while not node.is_leaf:
        if (
            node.feature is None
            or node.threshold is None
            or node.left is None
            or node.right is None
        ):
            raise RuntimeError("Malformed decision tree")
        node = (
            node.left
            if features[node.feature] <= node.threshold
            else node.right
        )
    probability = node.long_probability
    side: Side | None = (
        "LONG"
        if probability >= MINIMUM_LEAF_DIRECTIONAL_PROBABILITY
        else "SHORT"
        if probability <= 1 - MINIMUM_LEAF_DIRECTIONAL_PROBABILITY
        else None
    )
    return Prediction(
        side=side,
        probability=probability,
        leaf_support=node.support,
    )


def _bias_metrics(
    records: Sequence[FeatureRecord],
    *,
    tree: TreeNode,
) -> dict[str, Any]:
    predictions = [
        (record, _predict(tree, record.features)) for record in records
    ]
    eligible = [
        (record, prediction)
        for record, prediction in predictions
        if prediction.side is not None
    ]
    if not eligible:
        return {
            "observations": len(records),
            "predictions": 0,
            "coverage_pct": 0.0,
        }
    correct = sum(
        (prediction.side == "LONG") == record.label_long
        for record, prediction in eligible
    )
    net_returns = [
        (
            record.post_return
            if prediction.side == "LONG"
            else -record.post_return
        )
        - (record.entry_spread / 2 + record.exit_spread / 2 + 0.10 + 0.07)
        for record, prediction in eligible
    ]
    return {
        "observations": len(records),
        "predictions": len(eligible),
        "coverage_pct": round(len(eligible) / len(records) * 100, 3),
        "directional_accuracy_pct": round(
            correct / len(eligible) * 100,
            3,
        ),
        "average_net_close_return_usd": round(
            statistics.mean(net_returns),
            6,
        ),
        "median_net_close_return_usd": round(
            statistics.median(net_returns),
            6,
        ),
    }


def _aligned(
    signal: Signal,
    *,
    predictions: dict[tuple[str, date], Prediction],
) -> bool:
    window = str(signal.evidence["auction_window"])
    prediction = predictions.get((window, signal.session_date))
    return prediction is not None and prediction.side == signal.side


def _candidate_results(
    managed: Sequence[ManagedResult],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Trade]]]:
    playbooks = sorted({result.signal.playbook for result in managed})
    managers = sorted({result.manager for result in managed})
    candidates = [
        Candidate(
            archetype=playbook,
            rule="TREE_BIAS_ALIGNED",
            manager=manager,
        )
        for playbook in playbooks
        for manager in managers
    ]
    output: dict[tuple[str, float], list[Trade]] = {}
    for candidate in candidates:
        for cost_multiplier in (1.0, 1.5):
            output[(candidate.key, cost_multiplier)] = [
                result.trade
                for result in managed
                if result.signal.playbook == candidate.archetype
                and result.manager == candidate.manager
                and result.cost_multiplier == cost_multiplier
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


def _momentum(
    bars: Sequence[Bar],
    *,
    close_times: Sequence[datetime],
    as_of: datetime,
    lookback: int,
    atr: float,
) -> float | None:
    index = bisect_right(close_times, as_of) - 1
    if (
        index < lookback
        or index >= len(bars)
        or close_times[index] != as_of
    ):
        return None
    return (bars[index].close - bars[index - lookback].close) / atr


def _gini(probability: float) -> float:
    return 2 * probability * (1 - probability)


def _tree_dict(tree: TreeNode) -> dict[str, Any]:
    output = asdict(tree)
    output["is_leaf"] = tree.is_leaf
    return output


def _in_period(session_date: date, period: str) -> bool:
    if period == "discovery":
        return session_date < date(2023, 1, 1)
    if period == "validation":
        return date(2023, 1, 1) <= session_date < date(2024, 1, 1)
    if period == "forward":
        return date(2024, 1, 1) <= session_date < date(2025, 1, 1)
    raise ValueError(f"Unknown period: {period}")


def _percentile(value: float, history: Sequence[float]) -> float:
    if not history:
        return 50.0
    return sum(item <= value for item in history) / len(history) * 100


if __name__ == "__main__":
    asyncio.run(main())
