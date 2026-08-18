from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from explore_session_playbooks import Bar
from research_auction_state_playbooks import _auction_days, _signals
from research_daily_session_playbooks import (
    Signal,
    Trade,
    _atr_by_close,
)
from research_intraday_usd_confirmation import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    _bars,
)
from research_one_minute_auction_execution import (
    ONE_MINUTE_SQL,
    _micro_results,
)
from research_session_state_transitions import (
    Candidate,
    ContextRule,
    ManagedResult,
    _candidate_report,
    _portfolio_report,
    _select_discovery_candidates,
    _slice,
)

from gold_intel.infrastructure.database import session_factory

CROSS_MARKETS = ("EURUSD", "XAGUSD", "US500", "TLT.NAS")
POINT_SIZES = {
    "EURUSD": 0.00001,
    "XAGUSD": 0.001,
    "US500": 0.01,
    "TLT.NAS": 0.01,
}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--eurusd-csv-dir", type=Path)
    parser.add_argument("--xagusd-csv-dir", type=Path)
    parser.add_argument("--us500-csv-dir", type=Path)
    parser.add_argument("--tlt-csv-dir", type=Path)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

    query = {
        "load_start": start - timedelta(days=8),
        "load_end": end,
    }
    run_started = time.perf_counter()
    phase_started = run_started
    _phase("START", elapsed=0.0)
    local_directories = {
        "EURUSD": args.eurusd_csv_dir,
        "XAGUSD": args.xagusd_csv_dir,
        "US500": args.us500_csv_dir,
        "TLT.NAS": args.tlt_csv_dir,
    }
    async with session_factory() as session:
        minute_bars = _bars(
            (
                await session.execute(
                    ONE_MINUTE_SQL,
                    query,
                )
            ).mappings()
        )
        gold_bars = _five_minute_bars_from_minutes(minute_bars)
        _phase(
            "GOLD_LOADED",
            elapsed=time.perf_counter() - phase_started,
        )
        phase_started = time.perf_counter()
        cross_market_bars: dict[str, list[Bar]] = {}
        for instrument in CROSS_MARKETS:
            directory = local_directories[instrument]
            if directory is not None:
                cross_market_bars[instrument] = _five_minute_bars_from_csv_directory(
                    directory,
                    load_start=query["load_start"],
                    load_end=query["load_end"],
                    point_size=POINT_SIZES[instrument],
                )
            else:
                cross_market_bars[instrument] = _bars(
                    (
                        await session.execute(
                            FIVE_MINUTE_INSTRUMENT_SQL,
                            {"instrument": instrument, **query},
                        )
                    ).mappings()
                )
            _phase(
                f"{instrument}_LOADED",
                elapsed=time.perf_counter() - phase_started,
            )
            phase_started = time.perf_counter()

    _require_history(cross_market_bars, start=start, end=end)
    auction_days = _auction_days(gold_bars, start=start, end=end)
    source_signals = _enrich_cross_markets(
        _signals(auction_days, bars=gold_bars),
        cross_market_bars=cross_market_bars,
    )
    _phase(
        "FEATURES_BUILT",
        elapsed=time.perf_counter() - phase_started,
    )
    phase_started = time.perf_counter()
    managed = _micro_results(source_signals, minute_bars=minute_bars)
    _phase(
        "TRADES_SIMULATED",
        elapsed=time.perf_counter() - phase_started,
    )
    phase_started = time.perf_counter()
    candidates, candidate_trades = _candidate_results(managed)
    selected = _select_discovery_candidates(
        candidates,
        candidate_trades=candidate_trades,
    )
    _phase(
        "CANDIDATES_SELECTED",
        elapsed=time.perf_counter() - phase_started,
    )
    sampled = [
        candidate
        for candidate in candidates
        if len(
            _slice(
                candidate_trades[(candidate.key, 1.0)],
                "discovery",
            )
        )
        >= 40
    ]
    report = {
        "contract": {
            "version": "CROSS_MARKET_AUCTION_MICRO_EXECUTION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "auction_days": len(auction_days),
            "source_signals": len(source_signals),
            "managed_results": len(managed),
            "candidate_hypotheses": len(candidates),
            "cross_markets": {
                "EURUSD": "Observed inverse intraday USD proxy.",
                "XAGUSD": "Observed precious-metals confirmation.",
                "US500": "Observed equity-risk proxy.",
                "TLT.NAS": (
                    "Observed long-duration Treasury ETF price; an inferred "
                    "inverse nominal-yield proxy, not an observed yield."
                ),
            },
            "features": (
                "Completed 60-minute and four-hour return divided by each "
                "instrument's own completed five-minute ATR at signal time."
            ),
            "architecture": (
                "Auction-state trigger -> cross-market confirmation or "
                "contradiction -> next one-minute open -> three- or "
                "five-minute structural invalidation."
            ),
            "costs": (
                "Observed XAUUSD entry/exit spread, $0.05/oz slippage per side, "
                "and $7/lot round-turn commission; also tested at 1.50x."
            ),
            "ambiguity": (
                "When stop and target occur in the same one-minute bar, the "
                "stop is assumed first."
            ),
            "selection": (
                "Discovery only: n>=40, expectancy>=0.10R, PF>=1.15, "
                "1.50x-cost expectancy>0, bootstrap lower>=-0.05R; at most "
                "one rule/manager per auction-state/micro-stop archetype."
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
        "data_coverage": {
            instrument: {
                **_coverage(bars),
                "source": (
                    str(local_directories[instrument].resolve())
                    if local_directories[instrument] is not None
                    else "market.price_bars"
                ),
            }
            for instrument, bars in sorted(cross_market_bars.items())
        },
        "feature_coverage": _feature_coverage(source_signals),
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
                sampled,
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
    _phase(
        "REPORT_COMPLETE",
        elapsed=time.perf_counter() - run_started,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def _require_history(
    cross_market_bars: dict[str, list[Bar]],
    *,
    start: datetime,
    end: datetime,
) -> None:
    missing = [
        instrument
        for instrument, bars in cross_market_bars.items()
        if not bars
    ]
    if missing:
        raise RuntimeError(
            "Missing observed five-minute history for: "
            + ", ".join(sorted(missing))
        )
    incomplete = [
        instrument
        for instrument, bars in cross_market_bars.items()
        if bars[0].close_time > start
        or bars[-1].close_time < end - timedelta(days=5)
    ]
    if incomplete:
        raise RuntimeError(
            "Incomplete observed history for the research interval: "
            + ", ".join(sorted(incomplete))
        )


def _five_minute_bars_from_csv_directory(
    directory: Path,
    *,
    load_start: datetime,
    load_end: datetime,
    point_size: float,
) -> list[Bar]:
    """Stream immutable one-minute exports into complete five-minute bars."""

    files = sorted(directory.glob("*.csv"))
    if not files:
        raise RuntimeError(f"No CSV files found in {directory}")

    output: list[Bar] = []
    bucket: datetime | None = None
    members: list[Bar] = []
    previous_open: datetime | None = None

    def flush() -> None:
        nonlocal members
        if bucket is None or len(members) != 5:
            members = []
            return
        expected_opens = [
            bucket + timedelta(minutes=offset)
            for offset in range(5)
        ]
        if (
            [member.open_time for member in members] != expected_opens
            or members[-1].close_time != bucket + timedelta(minutes=5)
        ):
            members = []
            return
        output.append(
            Bar(
                open_time=bucket,
                close_time=bucket + timedelta(minutes=5),
                open=members[0].open,
                high=max(member.high for member in members),
                low=min(member.low for member in members),
                close=members[-1].close,
                volume=sum(member.volume for member in members),
                spread=statistics.mean(member.spread for member in members),
            )
        )
        members = []

    for path in files:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise RuntimeError(f"CSV file has no header row: {path}")
            for row in reader:
                open_time = _csv_timestamp(row["open_time"])
                if open_time < load_start or open_time >= load_end:
                    continue
                if previous_open is not None and open_time <= previous_open:
                    raise RuntimeError(
                        "CSV history is duplicated or out of order at "
                        f"{open_time.isoformat()} in {path}"
                    )
                previous_open = open_time
                close_time = _csv_timestamp(row["close_time"])
                available_at = _csv_timestamp(row["available_at"])
                if (
                    close_time != open_time + timedelta(minutes=1)
                    or available_at < close_time
                ):
                    raise RuntimeError(
                        f"Invalid point-in-time minute bar at {open_time.isoformat()}"
                    )
                current_bucket = open_time.replace(
                    minute=open_time.minute - open_time.minute % 5,
                    second=0,
                    microsecond=0,
                )
                if bucket is None:
                    bucket = current_bucket
                elif current_bucket != bucket:
                    flush()
                    bucket = current_bucket
                spread = (
                    float(row["spread_price"])
                    if row.get("spread_price")
                    else float(row.get("spread_points") or 0) * point_size
                )
                members.append(
                    Bar(
                        open_time=open_time,
                        close_time=close_time,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                        spread=spread,
                    )
                )
    flush()
    return output


def _five_minute_bars_from_minutes(
    minute_bars: Sequence[Bar],
) -> list[Bar]:
    output: list[Bar] = []
    bucket: datetime | None = None
    members: list[Bar] = []
    for bar in minute_bars:
        current_bucket = bar.open_time.replace(
            minute=bar.open_time.minute - bar.open_time.minute % 5,
            second=0,
            microsecond=0,
        )
        if bucket is None:
            bucket = current_bucket
        elif current_bucket != bucket:
            aggregated = _aggregate_five_minute_bucket(bucket, members)
            if aggregated is not None:
                output.append(aggregated)
            bucket = current_bucket
            members = []
        members.append(bar)
    if bucket is not None:
        aggregated = _aggregate_five_minute_bucket(bucket, members)
        if aggregated is not None:
            output.append(aggregated)
    return output


def _aggregate_five_minute_bucket(
    bucket: datetime,
    members: Sequence[Bar],
) -> Bar | None:
    expected_opens = [
        bucket + timedelta(minutes=offset)
        for offset in range(5)
    ]
    if (
        len(members) != 5
        or [member.open_time for member in members] != expected_opens
        or members[-1].close_time != bucket + timedelta(minutes=5)
    ):
        return None
    return Bar(
        open_time=bucket,
        close_time=bucket + timedelta(minutes=5),
        open=members[0].open,
        high=max(member.high for member in members),
        low=min(member.low for member in members),
        close=members[-1].close,
        volume=sum(member.volume for member in members),
        spread=statistics.mean(member.spread for member in members),
    )


def _csv_timestamp(value: str | None) -> datetime:
    if not value:
        raise RuntimeError("CSV timestamp is missing")
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise RuntimeError(f"CSV timestamp is timezone-naive: {value}")
    return timestamp.astimezone(UTC)


def _phase(name: str, *, elapsed: float) -> None:
    print(
        json.dumps(
            {
                "phase": name,
                "elapsed_seconds": round(elapsed, 3),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )


def _enrich_cross_markets(
    signals: Sequence[Signal],
    *,
    cross_market_bars: dict[str, list[Bar]],
) -> list[Signal]:
    clocks = {
        instrument: [bar.close_time for bar in bars]
        for instrument, bars in cross_market_bars.items()
    }
    atrs = {
        instrument: _atr_by_close(bars)
        for instrument, bars in cross_market_bars.items()
    }
    feature_prefix = {
        "EURUSD": "usd_proxy",
        "XAGUSD": "silver",
        "US500": "equity",
        "TLT.NAS": "tlt",
    }
    output: list[Signal] = []
    for signal in signals:
        evidence = dict(signal.evidence)
        side_sign = 1 if signal.side == "LONG" else -1
        for instrument, prefix in feature_prefix.items():
            bars = cross_market_bars[instrument]
            atr = atrs[instrument].get(signal.signal_time)
            for label, lookback in (("60m", 12), ("4h", 48)):
                value = (
                    _contiguous_momentum(
                        bars,
                        close_times=clocks[instrument],
                        as_of=signal.signal_time,
                        lookback=lookback,
                        atr=atr,
                    )
                    if atr is not None and atr > 0
                    else None
                )
                evidence[f"{prefix}_{label}_atr"] = value
                evidence[f"{prefix}_{label}_signed_atr"] = (
                    side_sign * value if value is not None else None
                )
        output.append(replace(signal, evidence=evidence))
    return output


def _rules() -> tuple[ContextRule, ...]:
    return (
        ContextRule("BASE", lambda signal: True),
        ContextRule(
            "USD_60M_ALIGNED",
            lambda signal: _positive(signal, "usd_proxy_60m_signed_atr"),
        ),
        ContextRule(
            "SILVER_60M_ALIGNED",
            lambda signal: _positive(signal, "silver_60m_signed_atr"),
        ),
        ContextRule(
            "USD_AND_SILVER_60M",
            lambda signal: (
                _positive(signal, "usd_proxy_60m_signed_atr")
                and _positive(signal, "silver_60m_signed_atr")
            ),
        ),
        ContextRule(
            "TLT_60M_ALIGNED",
            lambda signal: _positive(signal, "tlt_60m_signed_atr"),
        ),
        ContextRule(
            "USD_AND_TLT_60M",
            lambda signal: (
                _positive(signal, "usd_proxy_60m_signed_atr")
                and _positive(signal, "tlt_60m_signed_atr")
            ),
        ),
        ContextRule(
            "BREADTH_2_OF_3_60M",
            lambda signal: (
                _known_count(
                    signal,
                    (
                        "usd_proxy_60m_signed_atr",
                        "silver_60m_signed_atr",
                        "tlt_60m_signed_atr",
                    ),
                )
                >= 2
                and _positive_count(
                    signal,
                    (
                        "usd_proxy_60m_signed_atr",
                        "silver_60m_signed_atr",
                        "tlt_60m_signed_atr",
                    ),
                )
                >= 2
            ),
        ),
        ContextRule(
            "BREADTH_2_OF_3_4H",
            lambda signal: (
                _known_count(
                    signal,
                    (
                        "usd_proxy_4h_signed_atr",
                        "silver_4h_signed_atr",
                        "tlt_4h_signed_atr",
                    ),
                )
                >= 2
                and _positive_count(
                    signal,
                    (
                        "usd_proxy_4h_signed_atr",
                        "silver_4h_signed_atr",
                        "tlt_4h_signed_atr",
                    ),
                )
                >= 2
            ),
        ),
        ContextRule(
            "METALS_AND_EQUITY_SAME_SIDE_60M",
            lambda signal: (
                _positive(signal, "silver_60m_signed_atr")
                and _positive(signal, "equity_60m_signed_atr")
            ),
        ),
        ContextRule(
            "DEFENSIVE_LONG_60M",
            lambda signal: (
                signal.side == "LONG"
                and _negative(signal, "equity_60m_atr")
                and _positive(signal, "tlt_60m_atr")
            ),
        ),
    )


def _candidate_results(
    managed: Sequence[ManagedResult],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Trade]]]:
    playbooks = sorted({result.signal.playbook for result in managed})
    managers = sorted({result.manager for result in managed})
    rules = _rules()
    candidates = [
        Candidate(
            archetype=playbook,
            rule=rule.name,
            manager=manager,
        )
        for playbook in playbooks
        for rule in rules
        for manager in managers
    ]
    rule_by_name = {rule.name: rule for rule in rules}
    managed_by_scope: dict[
        tuple[str, str, float],
        list[ManagedResult],
    ] = {}
    for result in managed:
        managed_by_scope.setdefault(
            (
                result.signal.playbook,
                result.manager,
                result.cost_multiplier,
            ),
            [],
        ).append(result)
    output: dict[tuple[str, float], list[Trade]] = {}
    for candidate in candidates:
        rule = rule_by_name[candidate.rule]
        for cost_multiplier in (1.0, 1.5):
            output[(candidate.key, cost_multiplier)] = [
                result.trade
                for result in managed_by_scope.get(
                    (
                        candidate.archetype,
                        candidate.manager,
                        cost_multiplier,
                    ),
                    [],
                )
                if rule.predicate(result.signal)
            ]
    return candidates, output


def _contiguous_momentum(
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
        or close_times[index - lookback]
        != as_of - timedelta(minutes=5 * lookback)
    ):
        return None
    return (bars[index].close - bars[index - lookback].close) / atr


def _discovery_rank(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
) -> tuple[float, float, int]:
    trades = _slice(
        candidate_trades[(candidate.key, 1.0)],
        "discovery",
    )
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


def _positive(signal: Signal, key: str) -> bool:
    value = signal.evidence.get(key)
    return value is not None and float(value) > 0


def _negative(signal: Signal, key: str) -> bool:
    value = signal.evidence.get(key)
    return value is not None and float(value) < 0


def _known_count(signal: Signal, keys: Sequence[str]) -> int:
    return sum(signal.evidence.get(key) is not None for key in keys)


def _positive_count(signal: Signal, keys: Sequence[str]) -> int:
    return sum(_positive(signal, key) for key in keys)


def _coverage(bars: Sequence[Bar]) -> dict[str, Any]:
    return {
        "bars_5m": len(bars),
        "first_close": bars[0].close_time.isoformat() if bars else None,
        "last_close": bars[-1].close_time.isoformat() if bars else None,
    }


def _feature_coverage(signals: Sequence[Signal]) -> dict[str, Any]:
    keys = (
        "usd_proxy_60m_signed_atr",
        "silver_60m_signed_atr",
        "equity_60m_signed_atr",
        "tlt_60m_signed_atr",
    )
    by_year: dict[int, list[Signal]] = {}
    for signal in signals:
        by_year.setdefault(signal.session_date.year, []).append(signal)
    return {
        str(year): {
            "signals": len(members),
            **{
                key: sum(
                    member.evidence.get(key) is not None
                    for member in members
                )
                for key in keys
            },
        }
        for year, members in sorted(by_year.items())
    }


if __name__ == "__main__":
    asyncio.run(main())
